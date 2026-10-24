"""처음 켤 때 (깃허브에서 받아서 처음): 연결 코드 · 키를 한 화면에서 넣는다.

- 연결 코드: 이미 퍼플루를 쓰는 PC의 설정 > 연결 > '다른 PC 연결 코드' 를 붙여 넣으면 그 PC와 모든 것이 같아진다.
  처음 쓰는 사람은 Firebase Realtime Database 주소를 넣는다.
- Gemini 키는 꼭, Claude·OpenAI 키는 선택.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout)

from . import config, install

CSS = """
QDialog { background:#FAF8FF; } QLabel { color:#1F1235; font-family:'Malgun Gothic'; }
QLabel#title { font-size:17pt; font-weight:800; } QLabel#dim { color:#71717A; font-size:9pt; }
QLineEdit { background:white; border:1px solid #E4E0F0; border-radius:10px; padding:8px 10px; font-size:10pt; }
QLineEdit:focus { border-color:#8B5CF6; }
QPushButton { background:#8B5CF6; color:white; border:none; border-radius:10px; padding:9px 18px; font-weight:700; }
QPushButton#plain { background:transparent; color:#4C1D95; border:1px solid #E4E0F0; }
"""


def needed() -> bool:
    return not install.firebase_url() or not config.get_api_key()


class SetupDialog(QDialog):
    def __init__(self):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("퍼플루 시작하기")
        self.setStyleSheet(CSS)
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 22, 26, 22)
        v.setSpacing(8)
        from .face import app_icon
        icon = QLabel()
        icon.setPixmap(app_icon(72))
        v.addWidget(icon)
        t = QLabel("퍼플루 시작하기")
        t.setObjectName("title")
        v.addWidget(t)
        v.addWidget(self._dim("처음 한 번만 하면 돼요. 넣은 키는 이 PC의 Windows 자격 증명에만 저장돼요."))

        v.addWidget(QLabel("<b>연결 코드</b> 또는 Firebase 주소"))
        self.code = QLineEdit(install.firebase_url())
        self.code.setPlaceholderText("PURPLU-…  (다른 PC: 설정 > 연결 > '다른 PC 연결 코드')")
        v.addWidget(self.code)
        v.addWidget(self._dim("이미 퍼플루를 쓰는 PC가 있으면 그 PC의 연결 코드를 붙여 넣으세요 → 대화·설정·메모가 모두 같아져요.\n"
                              "처음이면 Firebase Realtime Database 주소(https://…firebasedatabase.app)를 넣어요."))
        self.keys = {}
        for prov, title, hint, need in (("gemini", "Gemini 키 (꼭)", "aistudio.google.com 에서 무료로 받아요", True),
                                        ("anthropic", "Claude 키 (선택)", "console.anthropic.com", False),
                                        ("openai", "OpenAI 키 (선택)", "platform.openai.com", False)):
            v.addWidget(QLabel(f"<b>{title}</b>  <span style='color:#71717A;font-size:9pt'>{hint}</span>"))
            e = QLineEdit()
            e.setEchoMode(QLineEdit.Password)
            e.setPlaceholderText("저장돼 있어요 (바꾸려면 새로 넣기)" if config.get_key(prov) else "")
            self.keys[prov] = e
            v.addWidget(e)
        self.shortcut = QCheckBox("바탕화면과 시작 메뉴에 퍼플루 바로가기 만들기")
        self.shortcut.setChecked(True)
        v.addWidget(self.shortcut)
        row = QHBoxLayout()
        row.addStretch(1)
        quit_ = QPushButton("나중에", objectName="plain")
        quit_.clicked.connect(self.reject)
        ok = QPushButton("시작하기")
        ok.clicked.connect(self._save)
        row.addWidget(quit_)
        row.addWidget(ok)
        v.addSpacing(6)
        v.addLayout(row)

    @staticmethod
    def _dim(text):
        lab = QLabel(text)
        lab.setObjectName("dim")
        lab.setWordWrap(True)
        return lab

    def _save(self):
        try:
            data = install.read_code(self.code.text())
        except Exception as e:
            return QMessageBox.information(self, "퍼플루", str(e))
        typed = {p: e.text().strip() for p, e in self.keys.items() if e.text().strip()}
        keys = {**data.get("keys", {}), **typed}   # 코드에 든 키 < 직접 넣은 키
        if not keys.get("gemini") and not config.get_api_key():
            return QMessageBox.information(self, "퍼플루", "Gemini 키가 필요해요. aistudio.google.com 에서 무료로 받을 수 있어요.")
        install.set_firebase_url(data["fb"])
        from . import store
        store.set_url(data["fb"])
        for p, k in keys.items():
            config.set_key(p, k)
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
