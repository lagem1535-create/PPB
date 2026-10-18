"""화면 하이라이트: 퍼플루가 버튼·글자·영역에 반짝이는 테두리와 이름표를 그린다.

화면 전체를 덮는 투명 창이지만 클릭은 그대로 통과한다.
"""
import ctypes
import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import config

GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED, WS_EX_NOACTIVATE = -20, 0x20, 0x80000, 0x08000000


class HighlightOverlay(QWidget):
    # [(left, top, right, bottom 물리 픽셀, 이름표)], 보여줄 초
    show_marks = Signal(list, float)
    clear_marks = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.marks: list[dict] = []
        self.trail: list[tuple] = []  # 혜성 꼬리 (위치, 시각)
        self._timer = QTimer(self, timeout=self._tick)
        self.show_marks.connect(self._show)
        self.clear_marks.connect(self.clear)

    def _cover_screen(self):
        self.setGeometry(QGuiApplication.primaryScreen().geometry())

    def _click_through(self):
        hwnd = int(self.winId())
        u = ctypes.windll.user32
        u.SetWindowLongW(hwnd, GWL_EXSTYLE,
                         u.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE)

    def _show(self, rects: list, seconds: float):
        dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        now = time.monotonic()
        for left, top, right, bottom, label in rects:
            r = QRectF(left / dpr, top / dpr, (right - left) / dpr, (bottom - top) / dpr).adjusted(-6, -6, 6, 6)
            self.marks.append({"rect": r, "label": label or "", "born": now, "until": now + seconds})
        self._cover_screen()
        self.show()
        self._click_through()
        self.raise_()
        self._timer.start(16)

    def add_trail(self, pt):
        """퍼플루 커서가 날아갈 때 혜성 꼬리 (원본의 pointer-comet처럼)."""
        self.trail.append((pt, time.monotonic()))
        if not self.isVisible():
            self._cover_screen()
            self.show()
            self._click_through()
        self._timer.start(16)

    def clear(self):
        self.marks.clear()
        self.trail.clear()
        self._timer.stop()
        self.hide()

    def _tick(self):
        now = time.monotonic()
        self.marks = [m for m in self.marks if m["until"] > now]
        self.trail = [t for t in self.trail if now - t[1] < 0.35]
        if not self.marks and not self.trail:
            self.clear()
            return
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base = QColor(config.settings().get("color") or "#8B5CF6")
        now = time.monotonic()
        font = QFont("Malgun Gothic", 11, QFont.Bold)
        p.setFont(font)
        fm = QFontMetrics(font)
        origin = self.geometry().topLeft()
        for i, (pt, born) in enumerate(self.trail):
            k = 1 - (now - born) / 0.35
            c = QColor(base).lighter(140)
            c.setAlphaF(max(0.0, 0.55 * k))
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            rad = 3 + 13 * k
            p.drawEllipse(pt - origin.toPointF(), rad, rad)
        for m in self.marks:
            age, left = now - m["born"], m["until"] - now
            fade = min(1.0, age / 0.25, left / 0.5)              # 나타날 때·사라질 때 부드럽게
            pulse = 0.5 + 0.5 * math.sin(age * 5)
            r = m["rect"]
            if age < 0.35:                                       # 처음엔 크게 시작해서 쏙 맞춰짐
                k = (0.35 - age) / 0.35 * 18
                r = r.adjusted(-k, -k, k, k)
            fill = QColor(base)
            fill.setAlphaF(0.16 * fade)
            glow = QColor(base)
            glow.setAlphaF(0.35 * fade * (0.6 + 0.4 * pulse))
            p.setPen(QPen(glow, 10))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 12, 12)
            line = QColor(base).lighter(130)
            line.setAlphaF(fade)
            p.setPen(QPen(line, 3))
            p.setBrush(fill)
            p.drawRoundedRect(r, 12, 12)
            if m["label"]:
                text = m["label"][:40]
                w, h = fm.horizontalAdvance(text) + 18, fm.height() + 8
                tag = QRectF(r.left(), r.top() - h - 4, w, h)
                if tag.top() < 4:
                    tag.moveTop(r.bottom() + 4)
                bg = QColor(base)
                bg.setAlphaF(0.95 * fade)
                p.setPen(Qt.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(tag, 8, 8)
                p.setPen(QColor(255, 255, 255, int(255 * fade)))
                p.drawText(tag, Qt.AlignCenter, text)
        p.end()
