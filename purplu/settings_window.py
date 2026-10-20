"""설정창: [대화] 새 대화·대화목록·대화 고르기 / [설정] / [갤럭시 탭] 연결 안내.

설정과 대화는 Firebase에 저장된다 (로그인 없음). Gemini 키만 이 PC에 저장.
"""
import io
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSlider, QTabWidget,
                               QPlainTextEdit, QTextBrowser, QVBoxLayout, QWidget)

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
"""


def style() -> str:
    return STYLE_LIGHT if config.settings().get("theme") == "light" else STYLE


def _when(ms) -> str:
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%m/%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


class SettingsWindow(QWidget):
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
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)
        key_row = QHBoxLayout()
        self.key_label = QLabel()
        btn_key = QPushButton("키 입력/변경")
        btn_key.clicked.connect(self._ask_key)
        key_row.addWidget(self.key_label, 1)
        key_row.addWidget(btn_key)
        form.addRow("Gemini 키", key_row)

        # 퍼플루 색: 누르면 바로 바뀌고 Firebase에 저장 (탭도 같이 바뀜)
        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self.swatches = {}
        for name, hexv in config.COLORS.items():
            b = QPushButton()
            b.setToolTip(name)
            b.setFixedSize(30, 30)
            b.clicked.connect(lambda _=False, h=hexv: self._set_color(h))
            self.swatches[hexv.lower()] = b
            color_row.addWidget(b)
        pick = QPushButton("직접…", objectName="plain")
        pick.clicked.connect(self._pick_color)
        color_row.addWidget(pick)
        color_row.addStretch(1)
        form.addRow("퍼플루 색", color_row)

        # 작업 중 표시 색 (비우면 퍼플루 색)
        work_row = QHBoxLayout()
        work_row.setSpacing(6)
        self.work_btn = QPushButton(objectName="plain")
        self.work_btn.clicked.connect(self._pick_work_color)
        same = QPushButton("퍼플루 색과 같게", objectName="plain")
        same.clicked.connect(lambda: (config.save_settings(work_indicator_color=""), self._paint_work_btn()))
        work_row.addWidget(self.work_btn)
        work_row.addWidget(same)
        work_row.addStretch(1)
        form.addRow("💜 작업 중 표시 색", work_row)

        self.combos = {}
        for key, label in (("live_model", "대화 모델"), ("thinking_level", "생각 깊이"),
                           ("talk_key", "누르고 말하기 키")):
            cb = QComboBox()
            cb.addItems(config.CHOICES[key])
            self.combos[key] = cb
            form.addRow(label, cb)
        self.checks = {}
        for key, label in (("speak", "목소리로 대답"),
                           ("show_thoughts", "💭 생각 내용 보여주기 (생각하는 모델에서 나와요)"),
                           ("show_steps", "⚙ 실행하는 명령과 결과 보여주기 (Claude처럼)"),
                           ("show_commands", "$ 실제로 실행하는 명령어도 보여주기 (파이썬 함수·프로그램·HTTP)"),
                           ("shell_enabled", "⌨ PC 명령어(PowerShell·cmd) 실행 허용 (확인 방식은 파이썬과 같아요)"),
                           ("python_enabled", "🐍 파이썬 코드 실행 허용 (작업 폴더: D:\\bot\\data\\python)"),

                           ("computer_control", "컴퓨터 조작 허용 (클릭·타이핑)"),
                           ("cursor_visible", "퍼플루 커서 쓰기 (가리키기·클릭할 때 나타남)"),
                           ("cursor_always", "커서 항상 보이기 (끄면 필요할 때만)"),
                           ("cursor_follow", "내 마우스 따라다니기"),
                           ("pc_chat_window", "💬 말풍선 대신 대화창 (오른쪽 아래, 글로도 입력)"),
                           ("pc_chat_pinned", "📌 PC 대화창을 오른쪽에 고정 (안 사라짐)"),
                           ("work_indicator", "💜 작업 중 표시 (퍼플루가 쓰는 앱·브라우저 둘레가 빛나요)"),
                           ("browser_real_input", "🌐 브라우저: 진짜 마우스·키보드로 조작 (확장, 위에 디버깅 알림이 떠요)"),
                           ("browser_highlights", "🖍 브라우저: 사이트 하이라이트·노트 (새로고침해도 유지)")):
            ch = QCheckBox(label)
            self.checks[key] = ch
            form.addRow("", ch)
        self.sec_level = QComboBox()
        for key, text in config.SECURITY_LEVELS.items():
            self.sec_level.addItem(text, key)
        self.sec_level.activated.connect(self._security_changed)
        form.addRow("🔒 보안 수준", self.sec_level)
        self.theme_box = QComboBox()
        for key, text in config.THEMES.items():
            self.theme_box.addItem(text, key)
        self.theme_box.activated.connect(lambda _=None: config.save_settings(theme=self.theme_box.currentData()))
        form.addRow("🎨 화면 테마", self.theme_box)
        self.pages_edit = QLineEdit(config.settings().get("pages_url", ""))
        self.pages_edit.setPlaceholderText("https://내아이디.github.io/PPB/  (GitHub Pages로 퍼플루 열 때)")
        self.pages_edit.editingFinished.connect(
            lambda: config.save_settings(pages_url=self.pages_edit.text().strip()))
        form.addRow("🌐 웹 주소", self.pages_edit)
        self.hide_box = QComboBox()
        for secs, text in ((0, "안 사라짐"), (5, "5초 뒤"), (10, "10초 뒤"), (15, "15초 뒤"), (30, "30초 뒤"), (60, "1분 뒤")):
            self.hide_box.addItem(text, secs)
        self.hide_box.setCurrentIndex(max(0, self.hide_box.findData(int(config.settings().get("pc_chat_autohide", 15)))))
        self.hide_box.activated.connect(lambda _=None: config.save_settings(pc_chat_autohide=self.hide_box.currentData()))
        form.addRow("💬 대화창 사라지기", self.hide_box)
        self.py_mode = QComboBox()
        for key, text in config.PYTHON_APPROVAL.items():
            self.py_mode.addItem(text, key)
        self.py_mode.activated.connect(self._python_mode_changed)
        form.addRow("🐍 실행 전 확인", self.py_mode)
        self.size_slider = QSlider(Qt.Horizontal, minimum=40, maximum=120)
        form.addRow("커서 크기", self.size_slider)
        save = QPushButton("저장 (Firebase)")
        save.clicked.connect(self._save)
        self.saved_label = QLabel()
        row = QHBoxLayout()
        row.addWidget(save)
        row.addWidget(self.saved_label, 1)
        form.addRow("", row)
        note = QLabel("설정은 Firebase에 저장돼서 갤럭시 탭과 같이 써요. Gemini 키는 이 PC에만 저장돼요.\n"
                      "누르고 말하기 키는 다시 켜야 바뀌어요. 비상정지: Ctrl+Alt+S")
        note.setStyleSheet("color:#A1A1AA; font-size:9pt;")
        form.addRow("", note)
        return w

    def _fill_settings(self):
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
