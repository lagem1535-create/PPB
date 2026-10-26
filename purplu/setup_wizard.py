"""처음 켤 때 (깃허브에서 받아서 처음): 어떤 AI를 쓸지 고르고 키를 넣는다. 저장할 곳도 고른다.

- AI: API 키 (Gemini · Claude · GPT) 또는 키 없이 (Claude Code · Codex · Antigravity 터미널 연동, Ollama).
  말(라이브 목소리 대화)은 Gemini 키가 있어야 한다. 다른 AI만 고르면 글 대화로 시작.
- 저장할 곳: '이 PC에만' · '온라인 (여러 PC 같이)' · '이 PC + 온라인' (연결 코드 / Firebase 주소).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QRadioButton, QVBoxLayout)

from . import config, install

CSS = """
QDialog { background:#FAF8FF; } QLabel, QRadioButton, QCheckBox { color:#1F1235; font-family:'Malgun Gothic'; }
QLabel#title { font-size:17pt; font-weight:800; } QLabel#dim { color:#71717A; font-size:9pt; }
QLabel#head { font-weight:700; margin-top:8px; }
QLineEdit { background:white; border:1px solid #E4E0F0; border-radius:10px; padding:8px 10px; font-size:10pt; }
QLineEdit:focus { border-color:#8B5CF6; }
QPushButton { background:#8B5CF6; color:white; border:none; border-radius:10px; padding:9px 18px; font-weight:700; }
QPushButton#plain { background:transparent; color:#4C1D95; border:1px solid #E4E0F0; }
QFrame#ai { background:white; border:1px solid #E4E0F0; border-radius:12px; }
QFrame#ai[on="true"] { border:2px solid #8B5CF6; background:#F5F3FF; }
QComboBox { background:white; border:1px solid #E4E0F0; border-radius:10px; padding:7px 10px; }
"""
AIS = [("gemini", "Gemini", "Google · 말(목소리)까지 돼요", "aistudio.google.com 에서 무료로 받아요"),
       ("anthropic", "Claude", "Anthropic · 글 대화", "console.anthropic.com 에서 받아요"),
       ("openai", "GPT", "OpenAI · 글 대화", "platform.openai.com 에서 받아요")]
# 키 없이 쓰는 것: 터미널 에이전트 (이 PC에 깔려 있고 로그인돼 있으면) · Ollama (이 PC의 모델)
NOKEY = [("claude", "Claude Code", "터미널 연동"), ("codex", "Codex", "터미널 연동"),
         ("antigravity", "Antigravity", "터미널 연동"), ("ollama", "Ollama", "이 PC · 인터넷 없이")]
DEFAULT_TEXT = {"gemini": "gemini-3.8-flash", "anthropic": "claude-opus-5-5"}


def _ready_without_key() -> bool:
    tm = config.settings().get("text_model") or ""
    return bool(config.settings().get("cli_agents")) and tm.startswith("cli:") or tm.startswith("ollama:")


def needed() -> bool:
    return not install.firebase_url() or not (any(config.get_key(p) for p, *_ in AIS) or _ready_without_key())


class SetupDialog(QDialog):
    def __init__(self):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("퍼플루 시작하기")
        self.setStyleSheet(CSS)
        self.setMinimumWidth(540)
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 22, 26, 22)
        v.setSpacing(6)
        from .face import app_icon
        icon = QLabel()
        icon.setPixmap(app_icon(72))
        v.addWidget(icon)
        t = QLabel("퍼플루 시작하기")
        t.setObjectName("title")
        v.addWidget(t)
        v.addWidget(self._dim("처음 한 번만 하면 돼요. 키는 이 PC의 Windows 자격 증명에만 저장돼요."))

        # ---- 1. 어떤 AI ----
        v.addWidget(self._head("1. 어떤 AI를 쓸까요?  (나중에 설정에서 더할 수 있어요)"))
        row = QHBoxLayout()
        self.ai = "gemini"
        self.cards = {}
        for prov, name, desc, _hint in AIS:
            card = QFrame()
            card.setObjectName("ai")
            card.setCursor(Qt.PointingHandCursor)
            cv = QVBoxLayout(card)
            cv.setContentsMargins(12, 10, 12, 10)
            n = QLabel(f"<b style='font-size:12pt'>{name}</b>")
            d = QLabel(desc)
            d.setObjectName("dim")
            d.setWordWrap(True)
            cv.addWidget(n)
            cv.addWidget(d)
            card.mousePressEvent = lambda _e, p=prov: self._pick(p)
            self.cards[prov] = card
            row.addWidget(card)
        v.addLayout(row)
        v.addWidget(self._dim("키 없이 쓰기 (글 대화만):"))
        row2 = QHBoxLayout()
        for prov, name, desc in NOKEY:
            card = QFrame()
            card.setObjectName("ai")
            card.setCursor(Qt.PointingHandCursor)
            cv = QVBoxLayout(card)
            cv.setContentsMargins(10, 8, 10, 8)
            n = QLabel(f"<b style='font-size:10.5pt'>{name}</b>")
            d = QLabel(desc)
            d.setObjectName("dim")
            d.setWordWrap(True)
            cv.addWidget(n)
            cv.addWidget(d)
            card.mousePressEvent = lambda _e, p=prov: self._pick(p)
            self.cards[prov] = card
            row2.addWidget(card)
        v.addLayout(row2)
        # 터미널 연동 / Ollama 고르기 줄 (키 칸 대신)
        self.nokey_row = QHBoxLayout()
        self.nokey_state = self._dim("")
        self.nokey_btn = QPushButton("터미널로 연동")
        self.nokey_btn.clicked.connect(self._connect_nokey)
        self.ollama_box = QComboBox()
        self.nokey_row.addWidget(self.nokey_state, 1)
        self.nokey_row.addWidget(self.ollama_box)
        self.nokey_row.addWidget(self.nokey_btn)
        v.addLayout(self.nokey_row)
        from .model_ui import CliConnector
        self.cli = CliConnector(self, on_connected=lambda _a: self._pick(self.ai), on_progress=self.nokey_state.setText)
        self.key_head = self._head("")
        v.addWidget(self.key_head)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        v.addWidget(self.key)
        self.key_hint = self._dim("")
        v.addWidget(self.key_hint)

        # ---- 2. 저장할 곳 ----
        v.addWidget(self._head("2. 대화·설정을 어디에 저장할까요?"))
        self.where = QButtonGroup(self)
        self.local = QRadioButton("이 PC에만  (간단해요 · 인터넷 없이도 · 추천)")
        self.shared = QRadioButton("온라인  (여러 PC에서 같이 · 연결 코드 넣기)")
        self.both = QRadioButton("이 PC + 온라인  (인터넷이 없어도 저장되고, 돌아오면 다른 PC와 맞춰요)")
        for b in (self.local, self.shared, self.both):
            self.where.addButton(b)
            v.addWidget(b)
        from .store import parse
        mode, cur = parse(install.firebase_url())
        {"online": self.shared, "both": self.both}.get(mode, self.local).setChecked(True)
        self.code = QLineEdit(cur)
        self.code.setPlaceholderText("PURPLU-…  (다른 PC의 설정 > 연결 > 다른 PC 연결 코드)  또는 Firebase 주소")
        v.addWidget(self.code)
        self.code_hint = self._dim("다른 PC의 연결 코드를 넣으면 그 PC와 대화·설정·메모가 모두 같아져요. 코드에 키가 들어 있으면 키도 같이 와요.")
        v.addWidget(self.code_hint)
        self.local.toggled.connect(self._where_changed)
        self.both.toggled.connect(self._where_changed)
        self._where_changed()

        self.shortcut = QCheckBox("바탕화면과 시작 메뉴에 퍼플루 바로가기 만들기")
        self.shortcut.setChecked(True)
        v.addSpacing(6)
        v.addWidget(self.shortcut)
        btns = QHBoxLayout()
        btns.addStretch(1)
        later = QPushButton("나중에", objectName="plain")
        later.clicked.connect(self.reject)
        ok = QPushButton("시작하기")
        ok.clicked.connect(self._save)
        btns.addWidget(later)
        btns.addWidget(ok)
        v.addSpacing(6)
        v.addLayout(btns)
        have = next((p for p, *_ in AIS if config.get_key(p)), None)   # 미리 고르지 않는다 (Gemini 기본 아님)
        if have:
            self._pick(have)
        else:
            self.ai = None
            for w in (self.key_head, self.key, self.key_hint, self.nokey_state, self.nokey_btn, self.ollama_box):
                w.hide()

    @staticmethod
    def _dim(text):
        lab = QLabel(text)
        lab.setObjectName("dim")
        lab.setWordWrap(True)
        return lab

    @staticmethod
    def _head(text):
        lab = QLabel(text)
        lab.setObjectName("head")
        return lab

    def _pick(self, prov):
        self.ai = prov
        for p, card in self.cards.items():
            card.setProperty("on", p == prov)
            card.style().unpolish(card)
            card.style().polish(card)
        keyed = any(p == prov for p, *_ in AIS)
        for w in (self.key_head, self.key, self.key_hint):
            w.setVisible(keyed)
        self.nokey_state.setVisible(not keyed)
        self.nokey_btn.setVisible(not keyed and prov != "ollama")
        self.ollama_box.setVisible(prov == "ollama")
        if not keyed:
            return self._paint_nokey()
        self.key.setFocus()
        name, hint = next((n, h) for p, n, _d, h in AIS if p == prov)
        self.key_head.setText(f"{name} 키")
        self.key_hint.setText(hint + ("  ·  이미 저장돼 있어요 (바꾸려면 새로 넣기)" if config.get_key(prov) else ""))
        self.key.setPlaceholderText(f"{name} API 키 붙여 넣기")

    def _paint_nokey(self):
        """터미널 에이전트: 연동됐나 / Ollama: 켜져 있나·깔린 모델."""
        from . import cli_agents
        if self.ai == "ollama":
            from .providers import ollama_status
            st = ollama_status(fresh=True)
            self.ollama_box.clear()
            for mid, name, desc, *_ in st["models"]:
                self.ollama_box.addItem(f"{name}  ·  {desc}", mid)
            self.ollama_box.setVisible(bool(st["models"]))
            self.nokey_state.setText(
                "깔린 모델 중에서 골라요. 말(목소리)은 Gemini 키가 있어야 해요." if st["models"] else
                ("Ollama 는 켜져 있는데 깔린 모델이 없어요. 터미널에서: ollama pull gemma3" if st["running"] else
                 "Ollama 가 꺼져 있거나 없어요. ollama.com 에서 설치하고 켠 뒤 이 카드를 다시 눌러 주세요."))
            return
        name = cli_agents.AGENTS[self.ai]["name"]
        ok = self.ai in cli_agents.connected()
        self.nokey_btn.setText("다시 확인" if ok else "터미널로 연동")
        self.nokey_state.setText(f"{name} 연동됐어요. 대화창 위 '터미널'의 폴더에서 일해요." if ok else
                                 f"{name}가 이 PC에 깔려 있고 로그인돼 있으면 연동돼요 (키 필요 없음).")

    def _connect_nokey(self):
        if self.ai and self.ai != "ollama":
            self.cli.start(self.ai)

    def _where_changed(self, *_):
        on = not self.local.isChecked()
        self.code.setVisible(on)
        self.code_hint.setVisible(on)

    def _save(self):
        try:
            data = install.read_code(self.code.text() if not self.local.isChecked() else "local")
            if self.both.isChecked():
                from .store import BOTH
                data["fb"] = BOTH + data["fb"]
        except Exception as e:
            return QMessageBox.information(self, "퍼플루", str(e))
        keys = dict(data.get("keys", {}))
        if self.ai and not any(p == self.ai for p, *_ in AIS):   # 키 없이: 터미널 에이전트 · Ollama
            from . import cli_agents
            if self.ai == "ollama":
                mid = self.ollama_box.currentData()
                if not mid:
                    return QMessageBox.information(self, "퍼플루", "Ollama 모델을 하나 골라 주세요 (깔린 모델이 없으면 먼저 받아 주세요).")
                text_model = mid
            elif self.ai in cli_agents.connected():
                text_model = "cli:" + self.ai
            else:
                return QMessageBox.information(self, "퍼플루", "먼저 '터미널로 연동' 을 눌러 연동해 주세요.")
            install.set_firebase_url(data["fb"])
            from . import store
            store.set_url(data["fb"])
            for p, k in keys.items():
                config.set_key(p, k)
            config.load()
            config.save_settings(text_model=text_model)
            if self.shortcut.isChecked():
                try:
                    install.make_shortcuts()
                except Exception as e:
                    print("바로가기 만들기 실패:", e)
            return self.accept()
        if not self.ai:
            if not keys:
                return QMessageBox.information(self, "퍼플루", "먼저 쓸 AI를 하나 골라 주세요.")
            self.ai = next(p for p, *_ in AIS if p in keys)   # 연결 코드에 키가 들어 있으면 그걸로
        if self.key.text().strip():
            keys[self.ai] = self.key.text().strip()
        if not keys.get(self.ai) and not config.get_key(self.ai):
            name = next(n for p, n, *_ in AIS if p == self.ai)
            return QMessageBox.information(self, "퍼플루", f"{name} 키를 넣어 주세요. ({next(h for p, _n, _d, h in AIS if p == self.ai)})")
        install.set_firebase_url(data["fb"])
        from . import store
        store.set_url(data["fb"])
        for p, k in keys.items():
            config.set_key(p, k)
        config.load()
        if self.ai == "openai":   # GPT 는 키로 쓸 수 있는 모델 중 첫 번째
            from .providers import openai_models
            gpts = openai_models(refresh=True)
            text_model = gpts[0][0] if gpts else ""
        else:
            text_model = DEFAULT_TEXT[self.ai]
        if text_model:
            config.save_settings(text_model=text_model)
        if self.shortcut.isChecked():
            try:
                install.make_shortcuts()
            except Exception as e:
                print("바로가기 만들기 실패:", e)
        self.accept()


def run_if_needed() -> bool:
    """필요하면 설정 창을 띄운다. 계속해도 되면 True."""
    if not needed():
        return True
    return SetupDialog().exec() == QDialog.Accepted and not needed()
