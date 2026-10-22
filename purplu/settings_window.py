"""설정창: [대화] 새 대화·대화목록·대화 고르기 / [설정] / [갤럭시 탭] 연결 안내.

설정과 대화는 Firebase에 저장된다 (로그인 없음). Gemini 키만 이 PC에 저장.
"""
import io
from datetime import datetime

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QFrame, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSlider, QTabWidget,
                               QPlainTextEdit, QTextBrowser, QVBoxLayout, QWidget)

from html import escape as html_escape

from . import config, store
from .server import local_ip

STYLE = """
QWidget { background:#1E1235; color:#F5F3FF; font-family:'Malgun Gothic'; font-size:10pt; }
QTabWidget::pane { border:1px solid #4C3A75; border-radius:10px; top:-1px; }
QTabBar::tab { background:#2E1F4F; padding:8px 18px; border-top-left-radius:8px; border-top-right-radius:8px; margin-right:2px; }
QTabBar::tab:selected { background:#8B5CF6; }
QPushButton { background:#8B5CF6; border:none; border-radius:8px; padding:7px 14px; font-weight:600; }
QPushButton:hover { background:#A78BFA; }
QPushButton#plain { background:#3B2A63; }
QPushButton#danger { background:#7F1D1D; }
QListWidget, QTextBrowser, QComboBox, QLineEdit, QPlainTextEdit { background:#2E1F4F; border:1px solid #4C3A75; border-radius:8px; padding:4px; }
QListWidget::item { padding:8px; border-radius:6px; }
QListWidget::item:selected { background:#6D28D9; }
QCheckBox::indicator { width:18px; height:18px; }
QFrame#card { background:#241640; border-radius:14px; }
QFrame#srow { background:transparent; border-bottom:1px solid #2E1F4F; }
QLabel#cardtitle { color:#A1A1AA; font-weight:700; font-size:9.5pt; margin:4px 2px 0; }
QFrame#card QLabel, QFrame#srow QLabel { background:transparent; }
QLabel#rtitle { font-weight:600; } QLabel#rdesc { color:#A1A1AA; font-size:9pt; } QLabel#saved { color:#86EFAC; }
QWidget#setpage { background:#1E1235; }
"""
STYLE_LIGHT = """
QWidget { background:#FAF8FF; color:#1F1235; font-family:'Malgun Gothic'; font-size:10pt; }
QTabWidget::pane { border:1px solid #DDD6FE; border-radius:10px; top:-1px; }
QTabBar::tab { background:#EDE9FE; color:#4C1D95; padding:8px 18px; border-top-left-radius:8px; border-top-right-radius:8px; margin-right:2px; }
QTabBar::tab:selected { background:#8B5CF6; color:white; }
QPushButton { background:#8B5CF6; color:white; border:none; border-radius:8px; padding:7px 14px; font-weight:600; }
QPushButton:hover { background:#7C3AED; }
QPushButton#plain { background:#EDE9FE; color:#4C1D95; }
QPushButton#danger { background:#DC2626; }
QListWidget, QTextBrowser, QComboBox, QLineEdit, QPlainTextEdit { background:white; border:1px solid #DDD6FE; border-radius:8px; padding:4px; }
QListWidget::item { padding:8px; border-radius:6px; }
QListWidget::item:selected { background:#DDD6FE; color:#1F1235; }
QCheckBox::indicator { width:18px; height:18px; }
QFrame#card { background:#F3F0FF; border-radius:14px; }
QFrame#srow { background:transparent; border-bottom:1px solid #E9E3FB; }
QLabel#cardtitle { color:#71717A; font-weight:700; font-size:9.5pt; margin:4px 2px 0; }
QFrame#card QLabel, QFrame#srow QLabel { background:transparent; }
QLabel#rtitle { font-weight:600; } QLabel#rdesc { color:#71717A; font-size:9pt; } QLabel#saved { color:#15803D; }
QWidget#setpage { background:#FAF8FF; }
"""


def style() -> str:
    return STYLE_LIGHT if config.settings().get("theme") == "light" else STYLE


def _when(ms) -> str:
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%m/%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


class Toggle(QCheckBox):
    """동그란 손잡이가 움직이는 켜기/끄기 스위치."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(46, 26)
        self.setCursor(Qt.PointingHandCursor)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(config.settings().get("color") or "#8B5CF6") if on else QColor("#71717A"))
        p.drawRoundedRect(QRectF(0, 0, 46, 26), 13, 13)
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(23 if on else 3, 3, 20, 20))
        p.end()


class SettingsWindow(QWidget):
    _mcp_status = Signal()   # MCP 서버 상태가 바뀜 (다른 스레드 → 화면)

    def __init__(self, brain, tablet_url_fn, local_url_fn=None, network_problem_fn=None):
        super().__init__(None, Qt.Window)
        self.brain = brain
        self.tablet_url_fn = tablet_url_fn
        self.local_url_fn = local_url_fn
        self.network_problem_fn = network_problem_fn
        self.setWindowTitle("퍼플루 설정")
        self.setStyleSheet(style())
        self.resize(760, 560)
        tabs = QTabWidget()
        tabs.addTab(self._chat_tab(), "💬 대화")
        tabs.addTab(self._memo_tab(), "📝 메모")
        tabs.addTab(self._voice_tab(), "🔊 목소리")
        tabs.addTab(self._skills_tab(), "🧩 스킬")
        tabs.addTab(self._mcp_tab(), "🔌 MCP")
        tabs.addTab(self._settings_tab(), "⚙ 설정")
        tabs.addTab(self._tablet_tab(), "📱 갤럭시 탭")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.addWidget(tabs)

    def open(self, tab: int | None = None):
        config.load()
        self._fill_settings()
        self.refresh_conversations()
        self.refresh_memos()
        self.refresh_skills()
        self.refresh_mcp()
        self._refresh_tablet()
        self.show()
        self.raise_()
        self.activateWindow()

    # ---- 대화 탭 ----

    def _chat_tab(self):
        w = QWidget()
        self.conv_list = QListWidget()
        self.conv_list.currentItemChanged.connect(self._show_messages)
        self.conv_list.itemDoubleClicked.connect(lambda _: self._select())
        self.preview = QTextBrowser()
        btn_new = QPushButton("＋ 새 대화")
        btn_new.clicked.connect(self._new)
        btn_use = QPushButton("이 대화로 이어가기")
        btn_use.clicked.connect(self._select)
        btn_rename = QPushButton("이름 바꾸기", objectName="plain")
        btn_rename.clicked.connect(self._rename)
        btn_del = QPushButton("삭제", objectName="danger")
        btn_del.clicked.connect(self._delete)
        left = QVBoxLayout()
        left.addWidget(btn_new)
        left.addWidget(self.conv_list, 1)
        row = QHBoxLayout()
        row.addWidget(btn_rename)
        row.addWidget(btn_del)
        left.addLayout(row)
        right = QVBoxLayout()
        self.conv_title = QLabel()
        self.conv_title.setFont(QFont("Malgun Gothic", 12, QFont.Bold))
        right.addWidget(self.conv_title)
        right.addWidget(self.preview, 1)
        right.addWidget(btn_use)
        lay = QHBoxLayout(w)
        lay.addLayout(left, 2)
        lay.addLayout(right, 3)
        return w

    def refresh_conversations(self):
        current = config.settings().get("current_conversation")
        self.conv_list.blockSignals(True)
        self.conv_list.clear()
        try:
            convs = store.list_conversations()
        except Exception as e:
            self.conv_list.addItem(f"⚠ Firebase에 연결 못 했어요: {e}")
            convs = []
        for c in convs:
            mark = "● " if c["id"] == current else "   "
            item = QListWidgetItem(f"{mark}{c.get('title', '새 대화')}\n     {_when(c.get('updated'))}")
            item.setData(Qt.UserRole, c["id"])
            self.conv_list.addItem(item)
            if c["id"] == current:
                self.conv_list.setCurrentItem(item)
        self.conv_list.blockSignals(False)
        self._show_messages(self.conv_list.currentItem())

    def _selected_id(self):
        item = self.conv_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _show_messages(self, item, _prev=None):
        cid = item.data(Qt.UserRole) if item else None
        if not cid:
            self.conv_title.setText("대화를 골라 주세요")
            self.preview.setHtml("")
            return
        self.conv_title.setText(item.text().split("\n")[0].strip("● ").strip())
        try:
            rows = store.messages(cid)
        except Exception as e:
            self.preview.setHtml(f"⚠ {e}")
            return
        html = []
        for r in rows:
            who, color = ("나", "#C4B5FD") if r.get("role") == "user" else ("퍼플루", "#F9A8D4")
            text = (r.get("text") or "").replace("<", "&lt;")
            html.append(f"<p><b style='color:{color}'>{who}</b> <span style='color:#71717A'>{_when(r.get('t'))}</span><br>{text}</p>")
        self.preview.setHtml("".join(html) or "<p style='color:#A1A1AA'>아직 나눈 말이 없어요.</p>")

    def _new(self):
        self.brain.new_conversation()
        QTimer.singleShot(800, self.refresh_conversations)

    def _select(self):
        cid = self._selected_id()
        if cid:
            self.brain.select_conversation(cid)
            QTimer.singleShot(400, self.refresh_conversations)

    def _rename(self):
        cid = self._selected_id()
        if not cid:
            return
        title, ok = QInputDialog.getText(self, "이름 바꾸기", "대화 이름:", text=self.conv_title.text())
        if ok and title.strip():
            store.rename_conversation(cid, title.strip())
            self.refresh_conversations()

    def _delete(self):
        cid = self._selected_id()
        if not cid:
            return
        if QMessageBox.question(self, "대화 삭제", f"'{self.conv_title.text()}' 대화를 지울까요?\n되돌릴 수 없어요.") \
                != QMessageBox.Yes:
            return
        store.delete_conversation(cid)
        if cid == config.settings().get("current_conversation"):
            self.brain.new_conversation()
        QTimer.singleShot(600, self.refresh_conversations)

    # ---- 목소리 탭: 들어보고 고르기 ----

    def _voice_tab(self):
        w = QWidget()
        self.voice_list = QListWidget()
        for name, desc in config.VOICES.items():
            item = QListWidgetItem(f"{name}  ·  {desc}")
            item.setData(Qt.UserRole, name)
            self.voice_list.addItem(item)
        self.voice_list.itemDoubleClicked.connect(lambda _: self._preview())
        play = QPushButton("▶ 들어보기")
        play.clicked.connect(self._preview)
        pick = QPushButton("✓ 이 목소리로 정하기")
        pick.clicked.connect(self._pick_voice)
        self.voice_status = QLabel()
        self.voice_status.setStyleSheet("color:#DDD6FE;")
        row = QHBoxLayout()
        row.addWidget(play)
        row.addWidget(pick)
        row.addWidget(self.voice_status, 1)
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("목소리를 골라 ▶ 들어보고(더블클릭도 돼요), 마음에 들면 '이 목소리로 정하기'."))
        lay.addWidget(self.voice_list, 1)
        lay.addLayout(row)
        note = QLabel("처음 듣는 목소리는 만드는 데 몇 초 걸려요. 한 번 들은 건 저장돼서 바로 나와요.")
        note.setStyleSheet("color:#A1A1AA; font-size:9pt;")
        lay.addWidget(note)
        return w

    def _selected_voice(self):
        item = self.voice_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _preview(self):
        v = self._selected_voice()
        if v and self.brain:
            self.voice_status.setText(f"{v} 준비 중…")
            self.brain.preview_voice(v, "pc")

    def _pick_voice(self):
        v = self._selected_voice()
        if v:
            config.save_settings(voice=v)
            self._mark_voice()
            self.voice_status.setText(f"✓ 이제 '{v}' 목소리로 말해요")

    def _mark_voice(self):
        cur = config.settings().get("voice")
        for i in range(self.voice_list.count()):
            item = self.voice_list.item(i)
            name = item.data(Qt.UserRole)
            item.setText(f"{'● ' if name == cur else '   '}{name}  ·  {config.VOICES.get(name, '')}")
            if name == cur and not self.voice_list.currentItem():
                self.voice_list.setCurrentItem(item)

    def voice_preview_status(self, data: dict):
        v, st = data.get("voice"), data.get("status")
        text = {"loading": f"{v} 목소리 만드는 중…", "playing": f"🔊 {v} 재생 중",
                "error": f"⚠ {data.get('error', '')}"}.get(st, "")
        self.voice_status.setText(text)

    # ---- 메모 탭 ----

    def _memo_tab(self):
        w = QWidget()
        self.memo_list = QListWidget()
        self.memo_input = QLineEdit()
        self.memo_input.setPlaceholderText("직접 메모 쓰기… (Enter)")
        self.memo_input.returnPressed.connect(self._add_memo)
        btn_pin = QPushButton("📌 붙이기/떼기", objectName="plain")
        btn_pin.clicked.connect(self._toggle_pin)
        btn_del = QPushButton("삭제", objectName="danger")
        btn_del.clicked.connect(self._delete_memo)
        row = QHBoxLayout()
        row.addWidget(btn_pin)
        row.addWidget(btn_del)
        row.addStretch(1)
        lay = QVBoxLayout(w)
        lay.addWidget(self.memo_input)
        lay.addWidget(self.memo_list, 1)
        lay.addLayout(row)
        note = QLabel("퍼플루에게 \"메모해줘\"라고 하면 여기와 PC 화면(포스트잇)에 남아요. 📌 = 화면에 붙어 있는 메모.")
        note.setStyleSheet("color:#A1A1AA; font-size:9pt;")
        lay.addWidget(note)
        return w

    # ---- 스킬: 왼쪽 목록(체크 = 켜기), 오른쪽 편집 ----
    def _skills_tab(self):
        w = QWidget()
        self.skill_list = QListWidget()
        self.skill_list.currentItemChanged.connect(self._pick_skill)
        self.skill_list.itemChanged.connect(self._toggle_skill)
        self.skill_list.setWordWrap(True)
        self.skill_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        new = QPushButton("＋ 새 스킬")
        new.clicked.connect(self._new_skill)
        left = QVBoxLayout()
        left.addWidget(new)
        left.addWidget(self.skill_list, 1)
        tip = QLabel("체크 = 켜기. 퍼플루는 '언제 쓰나요'를 보고 스킬을 골라요.\n"
                     "말로 \"이걸 스킬로 저장해\"라고 해도 만들어져요.")
        tip.setStyleSheet("color:#A1A1AA; font-size:9pt;")
        tip.setWordWrap(True)
        left.addWidget(tip)
        self.sk_name = QLineEdit(placeholderText="이름 (예: 아침 브리핑)")
        self.sk_desc = QLineEdit(placeholderText="언제 쓰나요? (예: '좋은 아침' 하면 날씨·일정 알려 주기)")
        self.sk_inst = QPlainTextEdit(placeholderText="설명서 (단계별로)\n1) 오늘 서울 날씨를 찾아\n"
                                                      "2) 오늘 알림과 메모를 모아\n3) 세 줄 이내로 밝게 말해")
        save = QPushButton("💾 저장")
        save.clicked.connect(self._save_skill)
        self.sk_del = QPushButton("삭제", objectName="danger")
        self.sk_del.clicked.connect(self._delete_skill)
        btns = QHBoxLayout()
        btns.addWidget(save)
        btns.addStretch(1)
        btns.addWidget(self.sk_del)
        right = QVBoxLayout()
        for label, widget in (("이름", self.sk_name), ("언제 쓰나요?", self.sk_desc), ("설명서", self.sk_inst)):
            lab = QLabel(label)
            lab.setStyleSheet("color:#A1A1AA; font-size:9pt;")
            right.addWidget(lab)
            right.addWidget(widget, 1 if widget is self.sk_inst else 0)
        right.addLayout(btns)
        lay = QHBoxLayout(w)
        lay.addLayout(left, 2)
        lay.addLayout(right, 3)
        self._skill_id = None
        return w

    def refresh_skills(self):
        from .tools import skills
        try:
            rows = skills.list_skills()["skills"]
        except Exception as e:
            self.skill_list.clear()
            self.skill_list.addItem(f"⚠ Firebase에 연결 못 했어요: {e}")
            return
        self.skill_list.blockSignals(True)
        self.skill_list.clear()
        for r in rows:
            item = QListWidgetItem(f"🧩 {r['name']}\n     {r.get('description') or ''}")
            item.setData(Qt.UserRole, r["id"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if r.get("enabled", True) else Qt.Unchecked)
            self.skill_list.addItem(item)
            if r["id"] == self._skill_id:
                self.skill_list.setCurrentItem(item)
        self.skill_list.blockSignals(False)
        self.sk_del.setEnabled(bool(self._skill_id))

    def _pick_skill(self, item, _prev=None):
        if not item or not item.data(Qt.UserRole):
            return
        self._skill_id = item.data(Qt.UserRole)
        row = store.get(f"skills/{self._skill_id}") or {}
        self.sk_name.setText(row.get("name", ""))
        self.sk_desc.setText(row.get("description", ""))
        self.sk_inst.setPlainText(row.get("instructions", ""))
        self.sk_del.setEnabled(True)

    def _toggle_skill(self, item):
        sid = item.data(Qt.UserRole)
        if sid:
            store.patch(f"skills/{sid}", {"enabled": item.checkState() == Qt.Checked})
            self.brain.refresh_session()

    def _new_skill(self):
        self._skill_id = None
        self.skill_list.clearSelection()
        for wdg in (self.sk_name, self.sk_desc):
            wdg.clear()
        self.sk_inst.clear()
        self.sk_del.setEnabled(False)
        self.sk_name.setFocus()

    def _save_skill(self):
        row = {"name": self.sk_name.text().strip(), "description": self.sk_desc.text().strip(),
               "instructions": self.sk_inst.toPlainText().strip(), "enabled": True}
        if not row["name"] or not row["instructions"]:
            QMessageBox.information(self, "퍼플루", "이름과 설명서를 써 주세요.")
            return
        if self._skill_id:
            store.patch(f"skills/{self._skill_id}", row)
        else:
            self._skill_id = store.post("skills", {**row, "created": store.now_ms()})
        self.brain.refresh_session()
        self.refresh_skills()

    def _delete_skill(self):
        if self._skill_id and QMessageBox.question(self, "퍼플루", "이 스킬을 지울까요?") == QMessageBox.Yes:
            store.delete(f"skills/{self._skill_id}")
            self.brain.refresh_session()
            self._new_skill()
            self.refresh_skills()

    def refresh_memos(self):
        try:
            self.show_memos(store.list_memos())
        except Exception as e:
            self.memo_list.clear()
            self.memo_list.addItem(f"⚠ Firebase에 연결 못 했어요: {e}")

    def show_memos(self, rows):
        self.memo_list.clear()
        for r in rows:
            item = QListWidgetItem(f"{'📌 ' if r.get('pinned') else '    '}{r.get('text', '')}\n     {_when(r.get('created'))}")
            item.setData(Qt.UserRole, r["id"])
            item.setData(Qt.UserRole + 1, bool(r.get("pinned")))
            self.memo_list.addItem(item)

    def _add_memo(self):
        text = self.memo_input.text().strip()
        if text:
            store.add_memo(text)
            self.memo_input.clear()

    def _toggle_pin(self):
        item = self.memo_list.currentItem()
        if item and item.data(Qt.UserRole):
            store.update_memo(item.data(Qt.UserRole), pinned=not item.data(Qt.UserRole + 1))

    def _delete_memo(self):
        item = self.memo_list.currentItem()
        if item and item.data(Qt.UserRole):
            store.delete_memo(item.data(Qt.UserRole))

    # ---- 설정 탭 ----

    def _settings_tab(self):
        """묶음 카드 + 스위치. 바꾸면 바로 저장돼요 (저장 버튼 없음)."""
        outer = QWidget()
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(0, 0, 0, 0)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        page = QWidget()
        page.setObjectName("setpage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 12, 16, 16)
        lay.setSpacing(14)
        area.setWidget(page)
        ol.addWidget(area)
        self.checks, self.combos = {}, {}

        def card(title):
            box = QFrame()
            box.setObjectName("card")
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 2, 0, 2)
            v.setSpacing(0)
            head = QLabel(title)
            head.setObjectName("cardtitle")
            lay.addWidget(head)
            lay.addWidget(box)
            return v

        def row(v, title, desc, control, wide=False):
            r = QFrame()
            r.setObjectName("srow")
            h = QVBoxLayout(r) if wide else QHBoxLayout(r)
            h.setContentsMargins(14, 10, 14, 10)
            t = QVBoxLayout()
            t.setSpacing(1)
            a = QLabel(title)
            a.setObjectName("rtitle")
            t.addWidget(a)
            if desc:
                d = QLabel(desc)
                d.setObjectName("rdesc")
                d.setWordWrap(True)
                t.addWidget(d)
            h.addLayout(t, 1)
            if isinstance(control, QHBoxLayout):
                h.addLayout(control)
            else:
                h.addWidget(control, 0 if not wide else 1)
            v.addWidget(r)

        def toggle(v, key, title, desc=""):
            sw = Toggle()
            self.checks[key] = sw
            sw.toggled.connect(lambda on, k=key: self._toggle_saved(k, on))
            row(v, title, desc, sw)

        def combo(key, choices):
            cb = QComboBox()
            cb.addItems(choices)
            cb.activated.connect(lambda _=None, k=key, c=cb: (config.save_settings(**{k: c.currentText()}), self._flash()))
            self.combos[key] = cb
            return cb

        # ---- 기본 ----
        v = card("기본")
        key_row = QHBoxLayout()
        self.key_label = QLabel()
        btn_key = QPushButton("키 입력/변경")
        btn_key.clicked.connect(self._ask_key)
        key_row.addWidget(self.key_label)
        key_row.addWidget(btn_key)
        row(v, "Gemini 키", "이 PC의 Windows 자격 증명에만 저장돼요", key_row)
        row(v, "대화 모델", "", combo("live_model", config.CHOICES["live_model"]))
        row(v, "생각 깊이", "생각하는 모델일 때만", combo("thinking_level", config.CHOICES["thinking_level"]))
        row(v, "누르고 말하기 키", "다시 켜야 바뀌어요", combo("talk_key", config.CHOICES["talk_key"]))
        toggle(v, "speak", "목소리로 대답")

        # ---- 화면 ----
        v = card("화면")
        self.theme_box = QComboBox()
        for key, text in config.THEMES.items():
            self.theme_box.addItem(text, key)
        self.theme_box.activated.connect(lambda _=None: (config.save_settings(theme=self.theme_box.currentData()), self._flash()))
        row(v, "테마", "", self.theme_box)
        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self.swatches = {}
        for name, hexv in config.COLORS.items():
            b = QPushButton()
            b.setToolTip(name)
            b.setFixedSize(26, 26)
            b.clicked.connect(lambda _=False, h=hexv: self._set_color(h))
            self.swatches[hexv.lower()] = b
            color_row.addWidget(b)
        pick = QPushButton("직접…", objectName="plain")
        pick.clicked.connect(self._pick_color)
        color_row.addWidget(pick)
        color_row.addStretch(1)
        row(v, "퍼플루 색", "", color_row, wide=True)
        work_row = QHBoxLayout()
        self.work_btn = QPushButton(objectName="plain")
        self.work_btn.clicked.connect(self._pick_work_color)
        same = QPushButton("퍼플루 색과 같게", objectName="plain")
        same.clicked.connect(lambda: (config.save_settings(work_indicator_color=""), self._paint_work_btn()))
        work_row.addWidget(self.work_btn)
        work_row.addWidget(same)
        row(v, "작업 중 표시 색", "", work_row)
        toggle(v, "work_indicator", "작업 중 표시", "퍼플루가 쓰는 앱·브라우저 둘레가 빛나요")
        toggle(v, "show_thoughts", "생각 내용 보여주기", "생각하는 모델에서 나와요")
        toggle(v, "show_steps", "실행하는 명령 보여주기", "open_app(\"계산기\") 처럼")
        toggle(v, "show_commands", "실제 명령어도 보여주기", "파이썬 함수·프로그램·HTTP")

        # ---- PC 대화창 ----
        v = card("PC 대화창")
        toggle(v, "pc_chat_window", "말풍선 대신 대화창", "말하면 오른쪽 아래에 글로도 쓸 수 있는 대화창이 떠요")
        toggle(v, "pc_chat_pinned", "오른쪽에 고정", "안 사라지고 늘 보여요")
        toggle(v, "pc_chat_dock", "고정하면 자리 차지", "작업 표시줄처럼 대화창만큼 다른 창이 작아져요")
        toggle(v, "pc_chat_on_top", "언제나 맨 위로")
        self.hide_box = QComboBox()
        for secs, text in ((0, "안 사라짐"), (5, "5초 뒤"), (10, "10초 뒤"), (15, "15초 뒤"), (30, "30초 뒤"), (60, "1분 뒤")):
            self.hide_box.addItem(text, secs)
        self.hide_box.activated.connect(lambda _=None: (config.save_settings(pc_chat_autohide=self.hide_box.currentData()), self._flash()))
        row(v, "대답 뒤 사라지기", "", self.hide_box)
        toggle(v, "mention_open_only", "@ 목록에 열린 것만", "지금 열린 탭·창만 (끄면 앱·메모도)")

        # ---- 보안 · 실행 ----
        v = card("보안 · 실행")
        self.sec_level = QComboBox()
        for key, text in config.SECURITY_LEVELS.items():
            self.sec_level.addItem(text, key)
        self.sec_level.activated.connect(self._security_changed)
        row(v, "보안 수준", "낮추면 경고가 떠요", self.sec_level, wide=True)
        toggle(v, "computer_control", "컴퓨터 조작 허용", "클릭·입력·키 누르기")
        toggle(v, "shell_enabled", "PC 명령어 실행 허용", "PowerShell·cmd (끄기·설정·네트워크 등)")
        toggle(v, "python_enabled", "파이썬 실행 허용", "작업 폴더: D:\\bot\\data\\python")
        self.py_mode = QComboBox()
        for key, text in config.PYTHON_APPROVAL.items():
            self.py_mode.addItem(text, key)
        self.py_mode.activated.connect(self._python_mode_changed)
        row(v, "실행 전 확인", "파이썬·명령어 둘 다", self.py_mode, wide=True)

        # ---- 커서 · 브라우저 ----
        v = card("커서 · 브라우저")
        toggle(v, "cursor_visible", "퍼플루 커서 쓰기", "가리키기·클릭할 때 나타나요")
        toggle(v, "cursor_always", "커서 항상 보이기", "끄면 필요할 때만")
        toggle(v, "cursor_follow", "내 마우스 따라다니기")
        self.size_slider = QSlider(Qt.Horizontal, minimum=40, maximum=120)
        self.size_slider.setFixedWidth(160)
        self.size_slider.sliderReleased.connect(lambda: (config.save_settings(cursor_size=self.size_slider.value()), self._flash()))
        row(v, "커서 크기", "", self.size_slider)
        toggle(v, "browser_real_input", "브라우저: 진짜 마우스·키보드", "확장이 디버깅 알림을 띄워요")
        toggle(v, "own_browser", "퍼플루 브라우저 쓰기", "웹 일은 대화창 위의 탭 하나짜리 브라우저에서 (끄면 웨일·크롬)")
        toggle(v, "browser_highlights", "브라우저: 하이라이트·노트", "새로고침해도 남아요")

        # ---- 연결 ----
        v = card("연결")
        self.pages_edit = QLineEdit(config.settings().get("pages_url", ""))
        self.pages_edit.setPlaceholderText("https://내아이디.github.io/PPB/")
        self.pages_edit.editingFinished.connect(lambda: (config.save_settings(pages_url=self.pages_edit.text().strip()), self._flash()))
        row(v, "웹 주소 (GitHub Pages)", "이 주소에서 연 화면만 PC에 연결돼요", self.pages_edit, wide=True)

        self.saved_label = QLabel()
        self.saved_label.setObjectName("saved")
        lay.addWidget(self.saved_label)
        note = QLabel("바꾸면 바로 저장돼서 갤럭시 탭과 같이 써요. 비상정지: Ctrl+Alt+S")
        note.setObjectName("rdesc")
        lay.addWidget(note)
        lay.addStretch(1)
        return outer

    def _toggle_saved(self, key, on):
        if getattr(self, "_filling", False):
            return
        if key == "cursor_always":
            config.save_settings(cursor_mode="always" if on else "auto")
        else:
            config.save_settings(**{key: bool(on)})
        self._flash()

    def _flash(self, text="✓ 저장했어요"):
        if hasattr(self, "saved_label"):
            self.saved_label.setText(text)
            QTimer.singleShot(1500, lambda: self.saved_label.setText(""))

    def _fill_settings(self):
        self._filling = True
        try:
            self._fill_settings_inner()
        finally:
            self._filling = False

    def _fill_settings_inner(self):
        s = config.settings()
        self.key_label.setText("✓ 저장됨" if config.get_api_key() else "⚠ 아직 없어요")
        for key, cb in self.combos.items():
            if cb.findText(str(s[key])) < 0:
                cb.addItem(str(s[key]))
            cb.setCurrentText(str(s[key]))
        for key, ch in self.checks.items():
            ch.setChecked(s.get("cursor_mode") == "always" if key == "cursor_always" else bool(s[key]))
        self.size_slider.setValue(int(s["cursor_size"]))
        self.py_mode.setCurrentIndex(max(0, self.py_mode.findData(s.get("python_approval", "ask"))))
        self._paint_work_btn()
        self.sec_level.setCurrentIndex(max(0, self.sec_level.findData(s.get("security_level", "strict"))))
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(s.get("theme", "dark"))))
        self.hide_box.setCurrentIndex(max(0, self.hide_box.findData(int(s.get("pc_chat_autohide", 15) or 0))))
        self.saved_label.setText("")
        self._mark_voice()
        self._paint_swatches()

    def _security_changed(self, _=None):
        """보안을 낮출 땐 무엇이 바뀌는지 경고하고, 동의해야 저장한다. 파이썬 실행 확인도 같이 바뀐다."""
        new = self.sec_level.currentData()
        old = config.settings().get("security_level", "strict")
        if new == old:
            return
        order = list(config.SECURITY_LEVELS)
        if order.index(new) > order.index(old):  # 낮추는 쪽만 경고
            box = QMessageBox(QMessageBox.Warning, "퍼플루 — 보안 경고", config.SECURITY_WARNING[new],
                              QMessageBox.Yes | QMessageBox.No, self)
            box.button(QMessageBox.Yes).setText("위험을 알고 바꿀게요")
            box.button(QMessageBox.No).setText("취소")
            box.setDefaultButton(QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                self.sec_level.setCurrentIndex(self.sec_level.findData(old))
                return
        config.save_settings(security_level=new, python_approval=config.SECURITY_PYTHON[new])
        self.saved_label.setText("✓ 보안 수준을 바꿨어요 (다음에 말할 때부터 적용)")

    def _python_mode_changed(self, _=None):
        """자동 실행으로 바꿀 땐 경고를 보여 주고, 동의해야 저장한다."""
        new = self.py_mode.currentData()
        old = config.settings().get("python_approval", "ask")
        if new == old:
            return
        if new in config.PYTHON_APPROVAL_WARNING:
            box = QMessageBox(QMessageBox.Warning, "퍼플루 — 자동 실행 경고", config.PYTHON_APPROVAL_WARNING[new],
                              QMessageBox.Yes | QMessageBox.No, self)
            box.button(QMessageBox.Yes).setText("알겠어요, 켤게요")
            box.button(QMessageBox.No).setText("취소")
            box.setDefaultButton(QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                self.py_mode.setCurrentIndex(self.py_mode.findData(old))
                return
        config.save_settings(python_approval=new)
        self.saved_label.setText("✓ 실행 전 확인 방식을 바꿨어요")

    def sync_fields(self, changes: dict):
        self._filling = True   # 다른 기기에서 바뀐 걸 보여 줄 땐 다시 저장하지 않게
        try:
            self._sync_fields_inner(changes)
        finally:
            self._filling = False

    def _sync_fields_inner(self, changes: dict):
        """다른 기기에서 바뀐 설정을 열려 있는 창에 반영."""
        for k, v in changes.items():
            if k in self.combos:
                self.combos[k].setCurrentText(str(v))
            elif k in self.checks:
                self.checks[k].setChecked(bool(v))
            elif k == "cursor_mode":
                self.checks["cursor_always"].setChecked(v == "always")
            elif k == "cursor_size":
                self.size_slider.setValue(int(v))
            elif k == "voice":
                self._mark_voice()
            elif k == "security_level":
                self.sec_level.setCurrentIndex(max(0, self.sec_level.findData(v)))
            elif k == "theme":
                self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(v)))
                self.setStyleSheet(style())
            elif k == "python_approval":
                self.py_mode.setCurrentIndex(max(0, self.py_mode.findData(v)))
        self._paint_swatches()

    def _paint_swatches(self):
        cur = (config.settings().get("color") or "").lower()
        for hexv, b in self.swatches.items():
            border = "3px solid white" if hexv == cur else "2px solid #4C3A75"
            b.setStyleSheet(f"background:{hexv}; border:{border}; border-radius:15px; padding:0;")

    def _set_color(self, hexv: str):
        config.save_settings(color=hexv)
        self._paint_swatches()

    def _paint_work_btn(self):
        c = config.settings().get("work_indicator_color") or ""
        shown = c or config.settings().get("color") or "#8B5CF6"
        self.work_btn.setText("  " + (c or "퍼플루 색") + "  ")
        self.work_btn.setStyleSheet(f"background:{shown}; color:white; border-radius:8px; padding:6px 10px;")

    def _pick_work_color(self):
        cur = config.settings().get("work_indicator_color") or config.settings().get("color")
        c = QColorDialog.getColor(QColor(cur), self, "작업 중 표시 색 고르기")
        if c.isValid():
            config.save_settings(work_indicator_color=c.name())
            self._paint_work_btn()

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(config.settings().get("color")), self, "퍼플루 색 고르기")
        if c.isValid():
            self._set_color(c.name())

    def _save(self):
        changes = {k: cb.currentText() for k, cb in self.combos.items()}
        changes.update({k: ch.isChecked() for k, ch in self.checks.items() if k != "cursor_always"})
        changes["cursor_mode"] = "always" if self.checks["cursor_always"].isChecked() else "auto"
        changes["cursor_size"] = self.size_slider.value()
        old = config.settings()
        changes = {k: v for k, v in changes.items() if old.get(k) != v}
        if changes:
            config.save_settings(**changes)
        self.saved_label.setText("✓ 저장했어요" if changes else "바뀐 게 없어요")

    def _ask_key(self):
        key, ok = QInputDialog.getText(self, "Gemini 키", "Google AI Studio에서 받은 Gemini API 키:",
                                       QLineEdit.Password)
        if ok and key.strip():
            config.set_api_key(key)
            self.brain.sleep()
            self.key_label.setText("✓ 저장됨")

    # ---- 갤럭시 탭 ----

    # ---- MCP 탭 ----

    MCP_KINDS = [("stdio", "명령어로 실행 (stdio)"), ("http", "주소 (HTTP)"), ("sse", "주소 (SSE)")]

    def _mcp_tab(self):
        from . import mcp_client
        w = QWidget()
        self.mcp_list = QListWidget()
        self.mcp_list.setWordWrap(True)
        self.mcp_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.mcp_list.currentItemChanged.connect(self._pick_mcp)
        self.mcp_list.itemChanged.connect(self._toggle_mcp)
        new = QPushButton("＋ 새 서버")
        new.clicked.connect(self._new_mcp)
        paste = QPushButton("JSON 붙여넣기", objectName="plain")
        paste.setToolTip('Claude·Cursor 설정의 {"mcpServers": {...}} 를 그대로 붙여 넣어요')
        paste.clicked.connect(self._paste_mcp)
        top = QHBoxLayout()
        top.addWidget(new)
        top.addWidget(paste)
        left = QVBoxLayout()
        left.addLayout(top)
        left.addWidget(self.mcp_list, 1)
        tip = QLabel("MCP 서버를 붙이면 퍼플루가 그 도구를 써요. 체크 = 켜기.\n"
                     "서버는 이 PC에서 프로그램을 실행하니 믿을 수 있는 것만 추가하세요.\n"
                     "키·토큰은 이 PC(data\\mcp.json)에만 저장돼요.")
        tip.setStyleSheet("color:#A1A1AA; font-size:9pt;")
        tip.setWordWrap(True)
        left.addWidget(tip)

        self.mcp_name = QLineEdit(placeholderText="이름 (예: 파일, 깃허브)")
        self.mcp_kind = QComboBox()
        for key, text in self.MCP_KINDS:
            self.mcp_kind.addItem(text, key)
        self.mcp_kind.currentIndexChanged.connect(self._mcp_kind_changed)
        self.mcp_cmd = QLineEdit(placeholderText="npx -y @modelcontextprotocol/server-filesystem D:\\")
        self.mcp_url = QLineEdit(placeholderText="https://example.com/mcp")
        self.mcp_env = QPlainTextEdit(placeholderText="이름=값 (한 줄에 하나)\n예: GITHUB_TOKEN=ghp_…")
        self.mcp_env.setFixedHeight(70)
        self.mcp_info = QTextBrowser()
        self.mcp_info.setOpenExternalLinks(False)
        save = QPushButton("💾 저장")
        save.clicked.connect(self._save_mcp)
        again = QPushButton("다시 연결", objectName="plain")
        again.clicked.connect(lambda: mcp_client.reload())
        self.mcp_del = QPushButton("삭제", objectName="danger")
        self.mcp_del.clicked.connect(self._delete_mcp)
        btns = QHBoxLayout()
        btns.addWidget(save)
        btns.addWidget(again)
        btns.addStretch(1)
        btns.addWidget(self.mcp_del)
        right = QVBoxLayout()
        self._mcp_labels = {}
        for key, label, widget in (("name", "이름", self.mcp_name), ("kind", "종류", self.mcp_kind), ("cmd", "명령어", self.mcp_cmd),
                                   ("url", "주소", self.mcp_url), ("env", "환경 변수", self.mcp_env),
                                   ("info", "상태 · 도구", self.mcp_info)):
            lab = QLabel(label)
            lab.setStyleSheet("color:#A1A1AA; font-size:9pt;")
            self._mcp_labels[key] = lab
            right.addWidget(lab)
            right.addWidget(widget, 1 if widget is self.mcp_info else 0)
        right.addLayout(btns)
        lay = QHBoxLayout(w)
        lay.addLayout(left, 2)
        lay.addLayout(right, 3)
        self._mcp_name = None
        self._mcp_kind_changed()
        self._mcp_status.connect(self.refresh_mcp)
        mcp_client.listeners.append(self._mcp_status.emit)
        return w

    def _mcp_kind_changed(self, *_):
        stdio = self.mcp_kind.currentData() == "stdio"
        for key, on in (("cmd", stdio), ("url", not stdio)):
            self._mcp_labels[key].setVisible(on)
        self.mcp_cmd.setVisible(stdio)
        self.mcp_url.setVisible(not stdio)
        self._mcp_labels["env"].setText("환경 변수 (이름=값, 한 줄에 하나)" if stdio else "헤더 (이름=값, 예: Authorization=Bearer …)")

    @staticmethod
    def _mcp_state_text(st: dict) -> str:
        state = (st or {}).get("state")
        if state == "ok":
            return f"● 연결됨 · 도구 {len(st['tools'])}개"
        if state == "connecting":
            return "… 연결 중" + (f" (지난 오류: {st['error'][:40]})" if st.get("error") else "")
        if state == "error":
            return f"⚠ {st['error'][:70]}"
        return "○ 꺼짐"

    def refresh_mcp(self):
        from . import mcp_client
        servers = mcp_client.load()
        self.mcp_list.blockSignals(True)
        self.mcp_list.clear()
        for sv in servers:
            st = mcp_client.status.get(sv["name"], {"state": "off" if not sv.get("enabled", True) else "connecting"})
            item = QListWidgetItem(f"🔌 {sv['name']}\n     {self._mcp_state_text(st)}")
            item.setData(Qt.UserRole, sv["name"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if sv.get("enabled", True) else Qt.Unchecked)
            self.mcp_list.addItem(item)
            if sv["name"] == self._mcp_name:
                self.mcp_list.setCurrentItem(item)
        if not servers:
            self.mcp_list.addItem("아직 없어요. '＋ 새 서버'나 'JSON 붙여넣기'로 추가하세요.")
        self.mcp_list.blockSignals(False)
        self.mcp_del.setEnabled(bool(self._mcp_name))
        self._show_mcp_info()

    def _show_mcp_info(self):
        from . import mcp_client
        if not self._mcp_name:
            self.mcp_info.setHtml("<span style='color:#A1A1AA'>예) 파일 서버: 종류 '명령어로 실행', 명령어 "
                                  "<code>npx -y @modelcontextprotocol/server-filesystem D:\\</code><br>"
                                  "주소로 붙는 서버는 종류 '주소 (HTTP)'에 주소를 넣어요.</span>")
            return
        st = mcp_client.status.get(self._mcp_name, {})
        rows = [f"<b>{html_escape(self._mcp_state_text(st))}</b>"]
        if st.get("state") == "error" or st.get("error"):
            rows.append(f"<span style='color:#FCA5A5'>{html_escape(st.get('error', ''))}</span>")
            rows.append(f"<span style='color:#A1A1AA'>자세한 기록: data\\mcp_logs\\{html_escape(self._mcp_name)}.log</span>")
        for t in st.get("tools", []):
            rows.append(f"• <b>{html_escape(t.name)}</b> <span style='color:#A1A1AA'>{html_escape((t.description or '')[:120])}</span>")
        self.mcp_info.setHtml("<br>".join(rows))

    def _pick_mcp(self, item, _prev=None):
        from . import mcp_client
        if not item or not item.data(Qt.UserRole):
            return
        self._mcp_name = item.data(Qt.UserRole)
        sv = next((x for x in mcp_client.load() if x["name"] == self._mcp_name), {})
        self.mcp_name.setText(sv.get("name", ""))
        self.mcp_kind.setCurrentIndex(max(0, self.mcp_kind.findData(sv.get("type", "stdio"))))
        args = [sv.get("command", "")] + [str(a) for a in sv.get("args") or []]
        self.mcp_cmd.setText(" ".join(f'"{a}"' if " " in a else a for a in args if a))
        self.mcp_url.setText(sv.get("url", ""))
        pairs = sv.get("env") if sv.get("type", "stdio") == "stdio" else sv.get("headers")
        self.mcp_env.setPlainText("\n".join(f"{k}={v}" for k, v in (pairs or {}).items()))
        self.mcp_del.setEnabled(True)
        self._show_mcp_info()

    def _new_mcp(self):
        self._mcp_name = None
        self.mcp_list.clearSelection()
        for wdg in (self.mcp_name, self.mcp_cmd, self.mcp_url):
            wdg.clear()
        self.mcp_env.clear()
        self.mcp_kind.setCurrentIndex(0)
        self.mcp_del.setEnabled(False)
        self._show_mcp_info()
        self.mcp_name.setFocus()

    def _save_mcp(self):
        import shlex
        from . import mcp_client
        name = self.mcp_name.text().strip()
        if not name:
            return QMessageBox.information(self, "MCP", "이름을 넣어 주세요.")
        kind = self.mcp_kind.currentData()
        pairs = {}
        for line in self.mcp_env.toPlainText().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip():
                    pairs[k.strip()] = v.strip()
        sv = {"name": name, "type": kind, "enabled": True}
        if kind == "stdio":
            parts = [p.strip('"').strip("'") for p in shlex.split(self.mcp_cmd.text().strip(), posix=False)]
            if not parts:
                return QMessageBox.information(self, "MCP", "실행할 명령어를 넣어 주세요.")
            sv.update(command=parts[0], args=parts[1:], env=pairs)
        else:
            url = self.mcp_url.text().strip()
            if not url.startswith(("http://", "https://")):
                return QMessageBox.information(self, "MCP", "주소는 http:// 나 https:// 로 시작해야 해요.")
            sv.update(url=url, headers=pairs)
        servers = mcp_client.load()
        old = next((x for x in servers if x["name"] == (self._mcp_name or name)), None)
        if old:
            sv["enabled"] = old.get("enabled", True)
            servers[servers.index(old)] = sv
        elif any(x["name"] == name for x in servers):
            return QMessageBox.information(self, "MCP", "같은 이름의 서버가 이미 있어요.")
        else:
            servers.append(sv)
        self._mcp_name = name
        mcp_client.save(servers)
        self._flash_mcp()

    def _flash_mcp(self):
        self.refresh_mcp()
        if hasattr(self, "_flash"):
            self._flash("✓ 저장했어요 · 연결하는 중…")

    def _delete_mcp(self):
        from . import mcp_client
        if not self._mcp_name:
            return
        if QMessageBox.question(self, "MCP 서버 지우기", f"'{self._mcp_name}' 서버를 지울까요?") != QMessageBox.Yes:
            return
        mcp_client.save([x for x in mcp_client.load() if x["name"] != self._mcp_name])
        self._new_mcp()
        self.refresh_mcp()

    def _toggle_mcp(self, item):
        from . import mcp_client
        name = item.data(Qt.UserRole)
        if not name:
            return
        servers = mcp_client.load()
        for x in servers:
            if x["name"] == name:
                x["enabled"] = item.checkState() == Qt.Checked
        mcp_client.save(servers)

    def _paste_mcp(self):
        from . import mcp_client
        text, ok = QInputDialog.getMultiLineText(self, "MCP 설정 붙여넣기",
                                                 'Claude·Cursor 의 설정 JSON 을 붙여 넣으세요.\n예: {"mcpServers": {"파일": {"command": "npx", "args": [...]}}}')
        if not ok or not text.strip():
            return
        try:
            new = mcp_client.parse_config_json(text)
        except Exception as e:
            return QMessageBox.warning(self, "MCP", f"JSON 을 읽지 못했어요: {e}")
        if not new:
            return QMessageBox.information(self, "MCP", "서버를 찾지 못했어요.")
        servers = mcp_client.load()
        names = {x["name"] for x in servers}
        for sv in new:
            if sv["name"] in names:
                servers = [sv if x["name"] == sv["name"] else x for x in servers]
            else:
                servers.append(sv)
        mcp_client.save(servers)
        self._mcp_name = new[0]["name"]
        self._flash_mcp()

    def _tablet_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.tablet_url = QLabel()
        self.tablet_url.setFont(QFont("Consolas", 16, QFont.Bold))
        self.tablet_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.qr = QLabel()
        guide = QLabel(
            "1. 갤럭시 탭을 PC와 같은 와이파이에 연결해요.\n"
            "2. 탭의 카메라로 QR을 찍거나, 크롬에 위 주소를 입력해요.\n"
            "3. 경고 없애기 (처음 한 번): 탭 크롬에서 http://" + local_ip() + ":"
            + str(config.settings()["tablet_port"]) + "/ca.crt 를 열어 받은 뒤\n"
            "   탭 설정 → 보안 및 개인정보 보호 → 기타 보안 설정 → 기기에 저장된 인증서 설치 → CA 인증서 → purplu-ca.crt\n"
            "   (설치 전엔 '연결이 비공개로 설정되어 있지 않습니다' → 고급 → 계속 진행으로도 돼요.)\n"
            "   PC와 같은 와이파이에서만 열려요. 다른 와이파이·인터넷에서는 막혀요.\n"
            "4. 마이크 권한 허용 → 크롬 메뉴 ⋮ → '홈 화면에 추가'로 앱처럼 쓰기.\n\n"
            "탭에서: 퍼플루를 꾹 누르고 있는 동안 말하고, 떼면 대답해요.\n"
            "            오른쪽 위 ⚙ 버튼(또는 마우스 우클릭)으로 설정·대화목록·메모를 열어요.\n\n"
            "안 될 때: Windows 방화벽 창이 뜨면 '개인 네트워크' 허용. 공유기의 '게스트 와이파이'는 안 돼요.")
        guide.setStyleSheet("color:#DDD6FE;")
        lay.addWidget(QLabel("탭 크롬에서 이 주소를 여세요:"))
        lay.addWidget(self.tablet_url)
        self.local_url = QLabel()
        self.local_url.setStyleSheet("color:#A1A1AA;")
        self.local_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.local_url)
        self.net_warn = QLabel()
        self.net_warn.setWordWrap(True)
        self.net_warn.setStyleSheet("background:#7F1D1D; color:#FEE2E2; padding:10px; border-radius:8px;")
        self.net_warn.hide()
        lay.addWidget(self.net_warn)
        row = QHBoxLayout()
        row.addWidget(self.qr)
        row.addWidget(guide, 1)
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    def _refresh_tablet(self):
        pages = getattr(self, "pages_link_fn", None)
        url = (pages() if pages else "") or self.tablet_url_fn()
        self.tablet_url.setText(url)
        if self.local_url_fn:
            self.local_url.setText(f"이 PC 브라우저에서 시험해 보려면: {self.local_url_fn()}")
        problem = self.network_problem_fn() if self.network_problem_fn else ""
        self.net_warn.setText("⚠ " + problem)
        self.net_warn.setVisible(bool(problem))
        try:
            import qrcode
            img = qrcode.make(url, box_size=6, border=2)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            pm = QPixmap()
            pm.loadFromData(buf.getvalue())
            self.qr.setPixmap(pm)
        except Exception:
            self.qr.setText("")
