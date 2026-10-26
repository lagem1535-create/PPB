"""퍼플루 안내창: 윈도우 기본 알림창 대신 둥글고 깔끔한 퍼플루 모양.

- ask(...)  → 고르면 True / 취소 False
- info(...) → 확인 하나
- install() → 프로그램 전체의 QMessageBox.question · information · warning · critical 을 이 모양으로 바꾼다
  (예전 코드는 그대로 두고, 켤 때 한 번만 부르면 된다)
"""
from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout)

from . import config

DANGER = "#E5484D"


def _pal():
    if config.settings().get("theme") == "light":
        return dict(bg="#FFFFFF", text="#1F1235", dim="#6B6478", line="#ECE8F5", soft="#F4F1FA", hover="#EAE5F4")
    return dict(bg="#1B1230", text="#F5F3FF", dim="#B4AEC4", line="#2E1F4F", soft="#2A1D45", hover="#352656")


def _on(hexv: str) -> str:
    c = QColor(hexv)
    lum = 0.2126 * c.redF() ** 2.2 + 0.7152 * c.greenF() ** 2.2 + 0.0722 * c.blueF() ** 2.2
    return "#1F1235" if lum > 0.45 else "#FFFFFF"


class PurpluDialog(QDialog):
    def __init__(self, parent, title, text, buttons, default=0, danger=False):
        """buttons: [(글, 값)] — 마지막이 주 단추(진한 색). default: Enter 로 누를 단추 번호."""
        super().__init__(parent.window() if parent else None)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.result_value = None
        self._drag = None
        P = _pal()
        accent = DANGER if danger else (config.settings().get("color") or "#8B5CF6")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 22)   # 그림자 자리
        card = QFrame(objectName="pcard")
        card.setStyleSheet(f"""
            QFrame#pcard {{ background:{P['bg']}; border:1px solid {P['line']}; border-radius:16px; }}
            QLabel {{ background:transparent; border:none; font-family:'Malgun Gothic'; }}
            QLabel#ptitle {{ color:{P['text']}; font-size:12pt; font-weight:700; }}
            QLabel#pbody {{ color:{P['dim']}; font-size:10pt; }}
            QPushButton {{ font-family:'Malgun Gothic'; font-size:10pt; border:none; border-radius:10px;
                           padding:0 18px; min-height:36px; }}
            QPushButton#psub {{ background:{P['soft']}; color:{P['text']}; }}
            QPushButton#psub:hover {{ background:{P['hover']}; }}
            QPushButton#pmain {{ background:{accent}; color:{_on(accent)}; font-weight:700; }}
            QPushButton#pmain:hover {{ background:{QColor(accent).darker(110).name()}; }}
            QPushButton:focus {{ outline:none; }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 10, 40, 70))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        v = QVBoxLayout(card)
        v.setContentsMargins(24, 22, 24, 18)
        v.setSpacing(8)
        t = QLabel(title, objectName="ptitle")
        t.setWordWrap(True)
        v.addWidget(t)
        if text:
            b = QLabel(text, objectName="pbody")
            b.setWordWrap(True)
            b.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v.addWidget(b)
        v.addSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        self.btns = []
        for i, (label, value) in enumerate(buttons):
            btn = QPushButton(label, objectName="pmain" if i == len(buttons) - 1 else "psub")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, val=value: self._done(val))
            row.addWidget(btn)
            self.btns.append((btn, value))
        v.addLayout(row)
        self.setFixedWidth(420)
        if self.btns:
            btn = self.btns[max(0, min(default, len(self.btns) - 1))][0]
            btn.setDefault(True)
            btn.setFocus()
        self._cancel = buttons[0][1] if buttons else None

    def _done(self, value):
        self.result_value = value
        self.accept()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._done(self._cancel)
            return
        super().keyPressEvent(e)

    # 창 아무 데나 잡고 옮기기
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def showEvent(self, e):
        super().showEvent(e)
        self.adjustSize()
        host = self.parentWidget()
        area = (host.frameGeometry() if host and host.isVisible()
                else QGuiApplication.primaryScreen().availableGeometry())
        scr = QGuiApplication.primaryScreen().availableGeometry()
        x = min(max(area.center().x() - self.width() // 2, scr.left()), scr.right() - self.width())
        y = min(max(area.center().y() - self.height() // 2, scr.top()), scr.bottom() - self.height())
        self.move(QPoint(x, y))
        self.setWindowOpacity(0.0)   # 살짝 나타나기
        self._fade = QPropertyAnimation(self, b"windowOpacity", self, duration=140, startValue=0.0, endValue=1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.start()

    def run(self):
        self.exec()
        return self.result_value if self.result_value is not None else self._cancel


def _clean(title: str) -> str:
    for pre in ("퍼플루 — ", "퍼플루 - ", "퍼플루: "):
        if title.startswith(pre):
            return title[len(pre):]
    return title or "퍼플루"


def _is_danger(*texts) -> bool:
    return any(w in (t or "") for t in texts for w in ("지울까요", "지우기", "삭제", "되돌릴 수 없", "위험"))


def ask(parent, title, text="", ok="네", cancel="아니요", danger=None, default_ok=True) -> bool:
    danger = _is_danger(title, text) if danger is None else danger
    d = PurpluDialog(parent, _clean(title), text, [(cancel, False), (ok, True)], default=1 if default_ok else 0, danger=danger)
    return bool(d.run())


def info(parent, title, text="", ok="확인"):
    PurpluDialog(parent, _clean(title), text, [(ok, True)]).run()


# ---- QMessageBox 를 이 모양으로 (예전 부르는 법 그대로) ----
_Y, _N, _OK, _C = QMessageBox.Yes, QMessageBox.No, QMessageBox.Ok, QMessageBox.Cancel
_LABEL = {_Y: "네", _N: "아니요", _OK: "확인", _C: "취소", QMessageBox.Save: "저장", QMessageBox.Discard: "버리기",
          QMessageBox.Retry: "다시 하기", QMessageBox.Close: "닫기", QMessageBox.Abort: "그만두기", QMessageBox.Ignore: "무시"}
_ORDER = [_N, _C, QMessageBox.Close, QMessageBox.Abort, QMessageBox.Ignore, QMessageBox.Discard, QMessageBox.Retry,
          _OK, QMessageBox.Save, _Y]   # 앞쪽 = 취소 쪽, 뒤쪽 = 주 단추


def _box(parent, title, text, buttons, default, fallback):
    flags = [b for b in _ORDER if buttons & b] or [fallback]
    danger = _is_danger(title, text)
    rows = [((("지우기" if danger and b == _Y else _LABEL[b]) if b == flags[-1] else
             ("취소" if danger and b == _N else _LABEL[b])), b) for b in flags]
    dflt = flags.index(default) if default in flags else len(flags) - 1
    return PurpluDialog(parent, _clean(title), text, rows, default=dflt, danger=danger).run()


def _question(parent, title, text, buttons=_Y | _N, defaultButton=QMessageBox.NoButton):
    return _box(parent, title, text, buttons, defaultButton, _Y)


def _plain(parent, title, text, buttons=_OK, defaultButton=QMessageBox.NoButton):
    return _box(parent, title, text, buttons, defaultButton, _OK)


def install():
    QMessageBox.question = staticmethod(_question)
    QMessageBox.information = staticmethod(_plain)
    QMessageBox.warning = staticmethod(_plain)
    QMessageBox.critical = staticmethod(_plain)
