"""트레이 아이콘 + 말풍선 + 퍼플루 커서 + 설정창 + 탭 서버를 묶는 곳."""
import html
import os
import threading
import webbrowser

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

from . import config, store
from .cursor import STATE_COLORS, PurpluCursor
from .highlight import HighlightOverlay
from .memo import MemoBoard
from .workframe import WorkFrame
from .notes import notes_dir, recorder
from .settings_window import SettingsWindow
from .tools import control, images, pyrun

STATE_TEXT = {
    "sleep": "자는 중 · Zzz", "idle": "기다리는 중", "listening": "듣는 중…",
    "thinking": "생각 중…", "acting": "하는 중…", "speaking": "말하는 중",
}


class Bridge(QObject):
    """두뇌·탭 서버 스레드 → UI 스레드."""
    event = Signal(str, object)


def theme() -> QColor:
    return QColor(config.settings().get("color") or "#8B5CF6")


def blob_icon(color: str | None = None, eyes_closed=False, size=64) -> QIcon:
    color = color or theme().name()
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(4, 6, size - 8, size - 10))
    p.setBrush(QColor("white"))
    if eyes_closed:
        p.setPen(QColor("white"))
        p.drawLine(18, 30, 26, 30)
        p.drawLine(38, 30, 46, 30)
    else:
        p.drawEllipse(QRectF(16, 22, 12, 14))
        p.drawEllipse(QRectF(36, 22, 12, 14))
        p.setBrush(QColor("#1F1235"))
        p.drawEllipse(QRectF(20, 27, 6, 7))
        p.drawEllipse(QRectF(40, 27, 6, 7))
    p.end()
    return QIcon(pm)


def _wrap(text: str) -> str:
    """긴 명령어도 말풍선 안에서 줄바꿈되게 (\, _, (, 쉼표 뒤 등에 보이지 않는 줄바꿈 자리)."""
    out = html.escape(text)
    for ch in ("\\", "_", "(", ",", ".", "/", "=", "&amp;"):
        out = out.replace(ch, ch + "&#8203;")
    return out


LIGHT_SWAP = {  # 밝은 테마: 어두운 배경용 글자색 → 흰 배경에서 잘 보이는 색
    "#C4B5FD": "#6D28D9", "#A1A1AA": "#52525B", "#FDE68A": "#92400E", "#86EFAC": "#15803D", "#FCA5A5": "#B91C1C",
    "#93C5FD": "#1D4ED8", "#B8B0CC": "#57534E", "#E9D5FF": "#4C1D95", "#DDD6FE": "#5B21B6", "#6D5BA8": "#C4B5FD",
}


def is_light() -> bool:
    return config.settings().get("theme") == "light"


class Bubble(QWidget):
    """퍼플루 커서 옆 말풍선: 상태, 생각, 단계, 대답, 리포트. 우클릭 → 설정, 꾹 누르기 → 말하기."""
    open_settings = Signal()
    talk_start = Signal()
    talk_end = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(430)
        self.face = QLabel()
        self.status = QLabel()
        self.status.setStyleSheet("color:#E9D5FF; font-weight:600;")
        top = QHBoxLayout()
        top.addWidget(self.face)
        top.addWidget(self.status, 1)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setOpenExternalLinks(True)
        self.body.setStyleSheet("color:white;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.addLayout(top)
        lay.addWidget(self.body)
        self.setFont(QFont("Malgun Gothic", 10))
        self._hide_timer = QTimer(self, singleShot=True, timeout=self.hide)
        self._long = QTimer(self, singleShot=True, timeout=self._hold_started)
        self._talking = False
        self.anchor = None  # 퍼플루 커서 (그 옆에 붙는다)
        self.reset()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.open_settings.emit()
        elif e.button() == Qt.LeftButton:
            self._long.start(250)

    def mouseReleaseEvent(self, e):
        self._long.stop()
        if self._talking:
            self._talking = False
            self.talk_end.emit()

    def _hold_started(self):
        self._talking = True
        self.talk_start.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(255, 255, 255, 245) if is_light() else QColor(30, 18, 53, 235))
        border = theme()
        border.setAlpha(220)
        p.setPen(QPen(border, 2))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 18, 18)

    redirect = None  # 설정이 켜져 있으면 말풍선 대신 부를 것 (App이 대화창 열기를 넣는다)

    def reset(self):
        self.heard, self.thought, self.reply = "", "", ""
        self.steps: list[dict] = []
        self.extra = ""

    def set_state(self, state: str, dots: int = 0):
        self.face.setPixmap(blob_icon(None, state == "sleep").pixmap(32, 32))
        self.status.setStyleSheet(f"color:{STATE_COLORS[state] if state not in ('idle', 'sleep') else ('#4C1D95' if is_light() else '#E9D5FF')};"
                                  " font-weight:600;")
        text = STATE_TEXT[state]
        if state == "thinking":  # 생각 중 점 애니메이션
            text = "생각 중" + "." * (dots % 4)
        self.status.setText(text)

    def render(self):
        parts = []
        if self.heard:
            parts.append(f"<div style='color:#C4B5FD'>🗣 {html.escape(self.heard)}</div>")
        s_ = config.settings()
        if self.thought and s_.get("show_thoughts", True):
            parts.append("<div style='margin-top:6px; padding:6px 8px; border-left:3px solid #6D5BA8; color:#B8B0CC;"
                         " font-style:italic; font-size:9pt'>💭 <b style='font-style:normal'>생각</b><br>"
                         f"{html.escape(self.thought[-500:]).replace(chr(10), '<br>')}</div>")
        hidden = max(0, len(self.steps) - 5)  # 단계가 많으면 최근 5개만
        if hidden:
            parts.append(f"<div style='color:#A1A1AA; font-size:9pt; margin-top:4px'>… 앞의 단계 {hidden}개</div>")
        for s in self.steps[hidden:]:
            mark = "●" if not s["done"] else ("✓" if s.get("ok") else "✗")
            color = "#93C5FD" if not s["done"] else ("#86EFAC" if s.get("ok") else "#FCA5A5")
            if s_.get("show_steps", True) and s.get("call"):
                # Claude처럼: 실행한 명령 한 줄 + 결과 한 줄
                secs = f" · {s['secs']}초" if s.get("secs") is not None else ""
                cmds = ""
                if s_.get("show_commands", True) and s.get("cmds"):
                    grouped = []  # 같은 명령이 이어서 반복되면 한 줄로 (×4)
                    for c in s["cmds"]:
                        if grouped and grouped[-1][0] == c:
                            grouped[-1][1] += 1
                        else:
                            grouped.append([c, 1])
                    shown = grouped[-6:]
                    more = len(grouped) - len(shown)
                    cmds = "".join(f"<br><span style='color:#FDE68A'>  $ {_wrap(c)}{f' ×{n}' if n > 1 else ''}</span>"
                                   for c, n in shown)
                    if more:
                        cmds = f"<br><span style='color:#A1A1AA'>  … 앞의 명령 {more}개</span>" + cmds
                res = (f"<br><span style='color:#A1A1AA'>  └ {html.escape(s.get('result', ''))}{secs}</span>"
                       if s["done"] else "<br><span style='color:#A1A1AA'>  └ 실행 중…</span>")
                parts.append(f"<div style='margin-top:4px; font-family:Consolas,monospace; font-size:9pt; color:{color}'>"
                             f"{mark} {_wrap(s['call'])}{cmds}{res}</div>")
            else:
                parts.append(f"<div style='color:{color}; margin-top:4px'>{mark} {html.escape(s['label'])}</div>")
        if self.reply:
            parts.append(f"<div style='margin-top:8px; font-size:11pt'>{html.escape(self.reply)}</div>")
        if self.extra:
            parts.append(f"<div style='margin-top:8px'>{self.extra}</div>")
        text = "".join(parts)
        if is_light():
            for dark_c, light_c in LIGHT_SWAP.items():
                text = text.replace(dark_c, light_c)
        self.body.setStyleSheet("color:#1F1235;" if is_light() else "color:white;")
        self.body.setText(text)
        self.body.setVisible(bool(parts))
        # 줄바꿈된 글 높이를 정확히 맞춘다 (안 하면 마지막 줄이 잘린다)
        self.body.setMinimumHeight(self.body.heightForWidth(self.width() - 32) if parts else 0)
        self.adjustSize()
        self.place()

    def place(self):
        area = QGuiApplication.primaryScreen().availableGeometry()
        if self.anchor and self.anchor.isVisible():
            g = self.anchor.geometry()
            x, y = g.left() - self.width() - 4, g.top() + 20 - self.height() // 2
            if x < area.left():
                x = g.right() + 4
            x = max(area.left() + 8, min(x, area.right() - self.width() - 8))
            y = max(area.top() + 8, min(y, area.bottom() - self.height() - 8))
            self.move(QPoint(x, y))
        else:
            self.move(QPoint(area.right() - self.width() - 16, area.bottom() - self.height() - 16))

    def pop(self, hide_after_ms: int | None = None):
        if self.redirect and config.settings().get("pc_chat_window", True):
            self.hide()
            if self.heard or self.reply or self.steps or self.extra or self.thought:
                self.redirect()   # 말풍선 대신 대화창 (보여 줄 내용이 있을 때만)
            return
        self.render()
        self.show()
        self.raise_()
        if hide_after_ms:
            self._hide_timer.start(hide_after_ms)
        else:
            self._hide_timer.stop()


class PythonApproval(QWidget):
    """퍼플루가 파이썬 코드를 실행하기 전에 코드를 보여 주고 허락을 받는 창."""

    def __init__(self, req: dict, on_answer):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint)
        self.req, self.on_answer = req, on_answer
        self.setWindowTitle(f"퍼플루 — {req.get('kind', '파이썬 코드')} 실행 확인")
        bg, fg, code_bg, code_fg = (("#FAF8FF", "#1F1235", "white", "#3B0764") if is_light()
                                    else ("#1E1235", "#F5F3FF", "#0F0A1C", "#E9D5FF"))
        self.setStyleSheet(f"QWidget{{background:{bg};color:{fg};font-family:'Malgun Gothic';font-size:10pt}}"
                           f"QPlainTextEdit{{background:{code_bg};color:{code_fg};font-family:Consolas,monospace;"
                           "border:1px solid #4C3A75;border-radius:8px;padding:6px}}"
                           "QPushButton{border:none;border-radius:8px;padding:9px 18px;font-weight:700}")
        lay = QVBoxLayout(self)
        title = QLabel(f"{'🐍' if req.get('kind', '파이썬').startswith('파이썬') else '⌨'} 퍼플루가 이 {req.get('kind', '파이썬 코드')}를 실행하려고 해요<br><b>{html.escape(req.get('purpose') or '')}</b>")
        title.setTextFormat(Qt.RichText)
        lay.addWidget(title)
        if req.get("risks"):
            warn = QLabel("⚠ 검사에서 찾은 위험한 부분: " + " · ".join(req["risks"]))
            warn.setWordWrap(True)
            warn.setStyleSheet("background:#7F1D1D;color:#FEE2E2;padding:8px;border-radius:8px")
            lay.addWidget(warn)
        code = QPlainTextEdit(req["code"])
        code.setReadOnly(True)
        code.setMinimumSize(640, 280)
        lay.addWidget(code)
        note = QLabel("코드를 읽어 보고 괜찮으면 실행을 눌러 주세요. 2분 안에 답이 없으면 실행하지 않아요.")
        note.setStyleSheet("color:#A1A1AA;font-size:9pt")
        lay.addWidget(note)
        row = QHBoxLayout()
        row.addStretch(1)
        no = QPushButton("취소")
        no.setStyleSheet("background:#3B2A63")
        yes = QPushButton("▶ 실행")
        yes.setStyleSheet("background:#8B5CF6")
        no.clicked.connect(lambda: self._answer(False))
        yes.clicked.connect(lambda: self._answer(True))
        row.addWidget(no)
        row.addWidget(yes)
        lay.addLayout(row)
        self._done = False

    def _answer(self, ok: bool):
        if not self._done:
            self._done = True
            self.on_answer(self.req["id"], ok)
        self.close()

    def closeEvent(self, e):
        if not self._done:  # 창을 그냥 닫으면 취소
            self._done = True
            self.on_answer(self.req["id"], False)
        super().closeEvent(e)


DESKTOP_TOOLS = {"open_app", "click", "type_text", "press_keys", "scroll", "look_at_screen", "point_at", "highlight",
                 "what_is_under_mouse", "windows_action"}  # PC 앱을 직접 다루는 도구 → 작업 중 테두리


class App:
    def __init__(self, qt: QApplication, brain_factory, server_factory):
        self.qt = qt
        self.bridge = Bridge()
        self.bridge.event.connect(self.on_event)
        self.state = "sleep"
        self._dots = 0
        self._dot_timer = QTimer(timeout=self._tick)
        self._dot_timer.start(350)

        # 퍼플루 커서: 도구가 다른 스레드에서 부르므로 시그널로 연결
        self.cursor = PurpluCursor()
        self.cursor.open_settings.connect(self.open_settings)
        self.cursor.clicked.connect(lambda: self.bubble.pop(8000))
        control.on_point = lambda x, y, kind: self.cursor.fly_to_physical.emit(x, y, kind)
        control.on_home = lambda: self.cursor.go_home.emit()
        self.highlights = HighlightOverlay()
        self.workframe = WorkFrame()  # PC 앱을 조작하는 동안 그 창 둘레에 '퍼플루가 사용 중' 빛
        self.cursor.moved.connect(self.highlights.add_trail)
        control.on_highlight = lambda rects, seconds: self.highlights.show_marks.emit(rects, seconds)
        control.on_clear_highlights = lambda: self.highlights.clear_marks.emit()
        self._approvals: dict[int, PythonApproval] = {}

        def ask_python(req):  # 도구 스레드에서 불린다 → PC 창과 탭에 같이 묻는다
            self.bridge.event.emit("python_ask", req)
            if self.server:
                self.server.broadcast("python_ask", req)
        pyrun.ask_user = ask_python

        def show_image(path, caption):  # 도구 스레드 → 탭·채팅 화면과 말풍선에
            url = "/img/" + os.path.basename(path)
            if self.server:
                self.server.broadcast("image", {"url": url, "caption": caption, "path": path})
            self.bridge.event.emit("image", {"path": path, "caption": caption})
        images.on_image = show_image

        self.bubble = Bubble()
        self.bubble.redirect = lambda: self.open_chat(activate=False)  # 설정에 따라 말풍선 대신 대화창
        self._chat_hide = QTimer(singleShot=True, timeout=lambda: getattr(self, "chat_window", None) and self.chat_window.auto_hide())
        cw = lambda: self.chat_window.frameGeometry() if getattr(self, "chat_window", None) and self.chat_window.isVisible() else None  # noqa: E731
        self.cursor.dock = cw
        self.bubble.anchor = self.cursor
        self.bubble.open_settings.connect(self.open_settings)
        # 꾹 누르고 있는 동안 말하기 (커서·말풍선 둘 다)
        for w in (self.cursor, self.bubble):
            w.talk_start.connect(lambda: self.brain.talk_start())
            w.talk_end.connect(lambda: self.brain.talk_end())

        # 두뇌 이벤트는 탭(바로)과 PC 화면(시그널) 양쪽으로
        self.server = None

        def emit(kind, data):
            if self.server:
                self.server.broadcast(kind, data)
            if kind != "audio":
                self.bridge.event.emit(kind, data)
        self.brain = brain_factory(emit)
        self.server = server_factory(self.brain)
        self.server.on_python_answered = lambda req_id: self.bridge.event.emit("python_answered", {"id": req_id})
        config.on_change(lambda changes: self.bridge.event.emit("settings_changed", changes))
        config.on_change(lambda changes: self.server.broadcast("settings", config.settings()))
        from . import browser
        config.on_change(browser.push_settings)
        self.settings_window = SettingsWindow(self.brain, lambda: self.server.url, lambda: self.server.local_url,
                                              lambda: self.server.network_problem)
        self.settings_window.pages_link_fn = self.server.pages_link
        self.memos = MemoBoard()
        self.load_memos()

        self.tray = QSystemTrayIcon(blob_icon(None, True))
        self.tray.setToolTip("퍼플루")
        menu = QMenu()
        key = config.settings()["talk_key"].upper()
        menu.addAction(QAction(f"말하기: {key} 키를 누르고 있기", menu, enabled=False))
        menu.addSeparator()
        menu.addAction("설정 · 대화목록…", self.open_settings)
        menu.addAction("💬 대화창 열기 (Ctrl+Alt+C)", self.open_chat)
        menu.addAction("🌐 브라우저로 열기", lambda: webbrowser.open(f"http://localhost:{config.settings()['tablet_port']}/"))
        menu.addAction("새 대화", lambda: self.brain.new_conversation())
        self.act_meeting = menu.addAction("● 회의록 시작", self.toggle_meeting)
        menu.addAction("회의록 폴더 열기", self.open_notes_folder)
        menu.addAction("말풍선 보기", lambda: self.bubble.pop(8000))
        menu.addAction("커서 집으로", lambda: self.cursor.home())
        menu.addAction("하이라이트 지우기", lambda: self.highlights.clear())
        menu.addAction("재우기 (연결 끊기)", lambda: self.brain.sleep())
        menu.addSeparator()
        menu.addAction("종료", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.bubble.pop(8000) if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self._menu = menu

        self.bubble.set_state("sleep")
        if not config.get_api_key():
            self.bubble.extra = "안녕! 나를 <b>우클릭</b>해서 Gemini 키를 넣어 줘."
        else:
            self.bubble.extra = (f"안녕! 나를 <b>꾹 누르고</b> 있거나 <b>{key}</b> 키를 누르고 있는 동안 말해 줘.<br>"
                                 "나를 우클릭하면 설정이 열려.")
        self.bubble.pop(8000)

    def open_chat(self, activate: bool = True):
        """PC 대화창 (탭·웹과 같은 대화창, 같은 대화)."""
        if not getattr(self, "chat_window", None):
            from .chatpanel import ChatPanel   # 웹 엔진 없이 Qt로 그린 대화창 (가볍고 안 죽음)
            self.chat_window = ChatPanel(self.brain, blob_icon(None, False))
        self.chat_window.open(activate)

    def open_settings(self):
        self.settings_window.open()

    def toggle_meeting(self):
        r = recorder.stop() if recorder.recording else recorder.start("회의")
        if not r.get("ok"):
            self.bubble.extra = f"<div style='color:#FCA5A5'>⚠ {html.escape(r['error'])}</div>"
            self.bubble.pop(8000)

    def open_notes_folder(self):
        d = recorder.folder if recorder.folder else notes_dir()
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(d)

    def load_memos(self):
        """메모를 뒤에서 불러와서 UI 스레드로 넘긴다."""
        def run():
            try:
                self.bridge.event.emit("memo_rows", store.list_memos())
            except Exception as e:
                print("메모 불러오기 실패:", e)
        threading.Thread(target=run, daemon=True).start()

    def _tick(self):
        if self.state == "thinking":
            self._dots += 1
            self.bubble.set_state("thinking", self._dots)
        if recorder.recording:  # 회의록 녹음 중: ● REC 시간
            t = int(recorder.elapsed())
            self.tray.setToolTip(f"퍼플루 — ● 회의록 녹음 중 {t // 60:02d}:{t % 60:02d}")
            self.bubble.status.setText(self.bubble.status.text().split("  ●")[0] + f"  ● REC {t // 60:02d}:{t % 60:02d}")

    def on_event(self, kind: str, data):
        if getattr(self, "chat_window", None):
            self.chat_window.on_event(kind, data)
        b = self.bubble
        if kind == "state":
            if data == "listening":
                b.reset()
            self.state = data
            self.cursor.set_state(data)
            b.set_state(data, self._dots)
            self.tray.setIcon(blob_icon(None, data == "sleep"))
            self.tray.setToolTip(f"퍼플루 — {STATE_TEXT[data]}")
            b.pop(10000 if data in ("idle", "sleep") else None)
            if data != "acting":
                self.workframe.stop()
            # 대답이 끝나면 몇 초 뒤 대화창 숨기기 (설정)
            secs = int(config.settings().get("pc_chat_autohide", 15) or 0)
            if data in ("idle", "sleep") and secs > 0 and getattr(self, "chat_window", None):
                self._chat_hide.start(secs * 1000)
            else:
                self._chat_hide.stop()
        elif kind == "heard":
            b.heard += data
            b.render()
        elif kind == "thought":
            b.thought += data
            b.render()
        elif kind == "reply":
            b.reply += data
            b.render()
        elif kind == "cmd":
            if b.steps:
                b.steps[-1].setdefault("cmds", []).append(data)
                b.render()
        elif kind == "step":
            if data["done"] and b.steps and b.steps[-1]["label"] == data["label"]:
                data["cmds"] = b.steps[-1].get("cmds", [])
                b.steps[-1] = data
            else:
                b.steps.append(data)
            b.render()
            tool = (data.get("call") or "").split("(")[0]
            if tool in DESKTOP_TOOLS and not data["done"]:
                self.workframe.start(data["label"].rstrip("…"))
        elif kind == "report":
            text = html.escape(data["report"]).replace("\n", "<br>")
            links = " · ".join(f"<a style='color:#C4B5FD' href='{html.escape(s['url'])}'>{html.escape(s['title'] or '출처')}</a>"
                               for s in data["sources"])
            b.extra = (f"<div style='background:#2E1F4F; padding:8px; border-radius:8px'>{text}"
                       + (f"<br><br><span style='font-size:9pt'>{links}</span>" if links else "") + "</div>")
            b.render()
        elif kind == "files":
            rows = "".join(f"<div style='font-size:9pt'>📄 {html.escape(os.path.basename(f['path']))}"
                           f" <span style='color:#A1A1AA'>{html.escape(f.get('modified', ''))}</span></div>"
                           for f in data[:5])
            b.extra = rows or "<div style='color:#A1A1AA'>찾은 파일이 없어요</div>"
            b.render()
        elif kind == "error":
            b.extra = f"<div style='color:#FCA5A5'>⚠ {html.escape(str(data))}</div>"
            b.pop(12000)
        elif kind in ("conversation", "conversations_changed"):
            if self.settings_window.isVisible():
                self.settings_window.refresh_conversations()
            if kind == "conversation":
                b.reset()
                b.extra = "새 대화를 시작했어요."
                b.pop(4000)
        elif kind == "hint":
            b.extra = f"<div style='color:#FDE68A'>🙉 {html.escape(str(data))}</div>"
            b.pop(5000)
        elif kind == "meeting":
            st = data.get("status")
            self.act_meeting.setText("■ 회의록 끝내기" if recorder.recording else "● 회의록 시작")
            if st == "recording":
                b.extra = f"<div style='color:#FCA5A5'>● 회의록 녹음 시작: <b>{html.escape(data['title'])}</b></div>"
                b.pop(6000)
            elif st == "finishing":
                b.extra = "<div style='color:#FDE68A'>■ 녹음 끝! 마지막 부분 받아쓰고 요약하는 중…</div>"
                b.pop(8000)
            elif st == "done":
                folder = data.get("folder", "")
                err = data.get("error")
                b.extra = ((f"<div style='color:#FCA5A5'>⚠ 요약 못 함: {html.escape(err)}</div>" if err else
                            "<div style='color:#86EFAC'>✓ 회의록 정리 끝!</div>")
                           + f"<div style='font-size:9pt'><a style='color:#C4B5FD' href='file:///{html.escape(folder)}/notes.md'>"
                           f"notes.md 열기</a></div>")
                b.pop(20000)
        elif kind == "reminder":
            b.reset()
            b.extra = (f"<div style='background:#F59E0B; color:#1F1235; padding:10px; border-radius:10px; font-size:12pt'>"
                       f"⏰ <b>{html.escape(data['text'])}</b></div>")
            b.pop(30000)
            threading.Thread(target=lambda: [__import__("winsound").MessageBeep(0x40) or __import__("time").sleep(0.35)
                                             for _ in range(3)], daemon=True).start()
        elif kind == "voice_preview":
            if self.settings_window.isVisible():
                self.settings_window.voice_preview_status(data)
        elif kind == "memos_changed":
            self.load_memos()
        elif kind == "memo_rows":
            self.memos.refresh(data)
            if self.settings_window.isVisible():
                self.settings_window.show_memos(data)
        elif kind == "open_chat":
            self.open_chat()
        elif kind == "cursor_point":
            self.cursor.show_at_mouse()
        elif kind == "cursor_toggle":
            config.save_settings(cursor_mode="auto" if config.settings().get("cursor_mode") == "always" else "always")
        elif kind == "cursor_home":
            self.cursor.home()
        elif kind == "image":
            b.extra = (f"<div>🎨 그림 완성! <a style='color:#C4B5FD' href='file:///{html.escape(data['path'])}'>열기</a></div>"
                       f"<img src='{html.escape(data['path'])}' width='300'>")
            b.pop(20000)
        elif kind == "python_ask":
            def answered(req_id, ok):
                pyrun.answer(req_id, ok)
                self._approvals.pop(req_id, None)
                self.server.broadcast("python_answered", {"id": req_id, "ok": ok})
            w = PythonApproval(data, answered)
            self._approvals[data["id"]] = w
            w.show()
            w.raise_()
            w.activateWindow()
        elif kind == "python_answered":
            w = self._approvals.pop(data["id"], None)
            if w:
                w._done = True
                w.close()
        elif kind == "stop":
            self.emergency_stop()
        elif kind == "settings_changed":
            if "cursor_size" in data:
                self.cursor.apply_size()
                self.cursor.home(instant=True)
            if "color" in data:
                self.memos.repaint_all()
                self.tray.setIcon(blob_icon(None, self.state == "sleep"))
                b.set_state(self.state, self._dots)
                b.update()
            if self.settings_window.isVisible():
                self.settings_window.sync_fields(data)
            if "current_conversation" in data and self.settings_window.isVisible():
                self.settings_window.refresh_conversations()
            if "pc_chat_pinned" in data:
                if data["pc_chat_pinned"]:
                    self.open_chat(activate=False)
                self.chat_window.apply_pin() if getattr(self, "chat_window", None) else None
            if {"pc_chat_on_top", "pc_chat_dock", "theme", "color", "chat_color", "chat_glow", "pc_layout", "live_model",
                "show_steps", "show_commands"} & set(data) and getattr(self, "chat_window", None):
                self.chat_window.apply_settings()
            if "theme" in data:
                self.bubble.render()
                self.bubble.update()
            if "cursor_mode" in data and data["cursor_mode"] == "always":
                self.cursor.home(instant=True)

    def emergency_stop(self):
        control.stop_event.set()
        self.highlights.clear()
        self.brain.talk_end()
        self.cursor.home()
        self.bubble.extra = "<div style='color:#FCA5A5'>■ 비상정지! 조작을 멈췄어요.</div>"
        self.bubble.pop(6000)

    def quit(self):
        try:  # 사용자가 끈 것 → 지킴이가 다시 켜지 않게
            (config.DATA_DIR / "quit.flag").write_text("quit", encoding="utf-8")
        except OSError:
            pass
        if getattr(self, "chat_window", None):
            self.chat_window.close()
        self.brain.shutdown()
        self.tray.hide()
        self.cursor.hide()
        QTimer.singleShot(300, self.qt.quit)
