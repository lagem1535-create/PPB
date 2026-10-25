"""처음 켤 때 (깃허브에서 받아서 처음): 어떤 AI를 쓸지 고르고 키를 넣는다. 저장할 곳도 고른다.

- AI: Gemini · Claude · GPT 중 하나 (나머지는 나중에 설정 > 기본에서 더할 수 있다).
  말(라이브 목소리 대화)은 Gemini 키가 있어야 한다. 다른 AI만 고르면 글 대화로 시작.
- 저장할 곳: '이 PC에만' (아무것도 안 해도 됨) 또는 '여러 PC 같이' (다른 PC의 연결 코드 / Firebase 주소).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QRadioButton, QVBoxLayout)

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
"""
AIS = [("gemini", "Gemini", "Google · 말(목소리)까지 돼요", "aistudio.google.com 에서 무료로 받아요"),
       ("anthropic", "Claude", "Anthropic · 글 대화", "console.anthropic.com 에서 받아요"),
       ("openai", "GPT", "OpenAI · 글 대화", "platform.openai.com 에서 받아요")]
DEFAULT_TEXT = {"gemini": "gemini-3.8-flash", "anthropic": "claude-opus-5-5"}


def needed() -> bool:
    return not install.firebase_url() or not any(config.get_key(p) for p, *_ in AIS)


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
        self.local = QRadioButton("이 PC에만  (간단해요 · 추천)")
        self.shared = QRadioButton("여러 PC에서 같이 쓰기  (연결 코드 넣기)")
        self.where.addButton(self.local)
        self.where.addButton(self.shared)
        cur = install.firebase_url()
        (self.shared if cur and cur != "local" else self.local).setChecked(True)
        v.addWidget(self.local)
        v.addWidget(self.shared)
        self.code = QLineEdit(cur if cur and cur != "local" else "")
        self.code.setPlaceholderText("PURPLU-…  (다른 PC의 설정 > 연결 > 다른 PC 연결 코드)  또는 Firebase 주소")
        v.addWidget(self.code)
        self.code_hint = self._dim("다른 PC의 연결 코드를 넣으면 그 PC와 대화·설정·메모가 모두 같아져요. 코드에 키가 들어 있으면 키도 같이 와요.")
        v.addWidget(self.code_hint)
        self.local.toggled.connect(self._where_changed)
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
            for w in (self.key_head, self.key, self.key_hint):
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
        for w in (self.key_head, self.key, self.key_hint):
            w.show()
        self.key.setFocus()
        for p, card in self.cards.items():
            card.setProperty("on", p == prov)
            card.style().unpolish(card)
            card.style().polish(card)
        name, hint = next((n, h) for p, n, _d, h in AIS if p == prov)
        self.key_head.setText(f"{name} 키")
        self.key_hint.setText(hint + ("  ·  이미 저장돼 있어요 (바꾸려면 새로 넣기)" if config.get_key(prov) else ""))
        self.key.setPlaceholderText(f"{name} API 키 붙여 넣기")

    def _where_changed(self, *_):
        on = self.shared.isChecked()
        self.code.setVisible(on)
        self.code_hint.setVisible(on)

    def _save(self):
        try:
            data = install.read_code(self.code.text() if self.shared.isChecked() else "local")
        except Exception as e:
            return QMessageBox.information(self, "퍼플루", str(e))
        keys = dict(data.get("keys", {}))
        if not self.ai:
            if not keys:
                return QMessageBox.information(self, "퍼플루", "먼저 쓸 AI를 하나 골라 주세요 (Gemini · Claude · GPT).")
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
