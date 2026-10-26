"""화면 위 퍼플루 커서 (원본 블루이처럼 물방울 모양 + 말랑한 눈).

- 기본은 '필요할 때만': 가리키거나 클릭·하이라이트할 때만 나타나서 날아가고, 끝나면 스르르 사라진다.
- 설정에서 '항상 보이기'로 바꾸면 화면 오른쪽 아래(탭 위쪽)에 머문다.
  그때는 꾹 누르기 = 말하기, 우클릭 = 설정, 톡 = 말풍선.
- 날아다니는 동안엔 클릭이 통과된다 (조작을 막지 않게). 날 때 혜성 꼬리를 남긴다.
- 눈은 스프링처럼 출렁이며 마우스나 날아가는 쪽을 본다.
"""
import ctypes
import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from . import config

GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED, WS_EX_NOACTIVATE = -20, 0x20, 0x80000, 0x08000000
user32 = ctypes.windll.user32

STATE_COLORS = {
    "sleep": "#7C6AA8", "idle": "#8B5CF6", "listening": "#A855F7",
    "thinking": "#F59E0B", "acting": "#3B82F6", "speaking": "#EC4899",
}
HOLD_TO_TALK_MS = 250
LINGER_SECONDS = 2.5  # 가리키기가 끝나고 이만큼 있다가 사라진다


def pen(color, width) -> QPen:
    q = QPen(QColor(color), width)
    q.setCapStyle(Qt.RoundCap)
    return q


def ease(t: float) -> float:
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


class GooglyEye:
    """눈동자가 목표 쪽으로 스프링처럼 흔들리며 따라간다."""

    def __init__(self):
        self.pos = QPointF()
        self.vel = QPointF()

    def step(self, target: QPointF, dt: float):
        k, damping = 260.0, 11.0
        acc = (target - self.pos) * k - self.vel * damping
        self.vel += acc * dt
        self.pos += self.vel * dt


class PurpluCursor(QWidget):
    # 다른 스레드(도구 실행)에서 부를 수 있게 시그널로 받는다
    fly_to_physical = Signal(int, int, str)
    go_home = Signal()
    open_settings = Signal()
    clicked = Signal()
    talk_start = Signal()
    talk_end = Signal()
    moved = Signal(QPointF)  # 날아가는 중 위치 (혜성 꼬리용, 논리 좌표)

    PAD = 16

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.state = "sleep"
        self.mode = "home"            # home | follow | fly | point
        self._from = QPointF()
        self._to = QPointF()
        self._t0 = 0.0
        self._dur = 0.45
        self._after_fly = "point"
        self._tip = QPointF()        # 커서 끝이 가리키는 화면 위치 (논리 좌표)
        self._look = QPointF(1, 1)
        self._eyes = [GooglyEye(), GooglyEye()]
        self._blink_at = time.monotonic() + 3
        self._squash = 0.0
        self._holding = False
        self._talking = False
        self._hold = QTimer(self, singleShot=True, timeout=self._hold_started)
        self._phase = 0.0
        self._last = time.monotonic()
        self._needed_until = 0.0     # 이 시각까지는 보여야 한다
        self._alpha = 0.0
        self.apply_size()
        self.fly_to_physical.connect(self._fly_physical)
        self.go_home.connect(self.home)
        self._timer = QTimer(self, timeout=self._tick)
        self._timer.start(16)
        self.home(instant=True)
        self._set_click_through(False)

    # ---- 크기·위치 ----

    def apply_size(self):
        s = int(config.settings()["cursor_size"])
        self.size_px = max(32, min(120, s))
        w = int(self.size_px * 1.45) + self.PAD
        self.setFixedSize(w, w)

    def always(self) -> bool:
        return config.settings().get("cursor_mode", "auto") == "always"

    dock = None  # 대화창이 떠 있으면 그 창(QRect)을 넣어 준다 → 퍼플루가 대화창 왼쪽 아래 옆에 선다

    def home_point(self) -> QPointF:
        area = QGuiApplication.primaryScreen().availableGeometry()
        d = self.dock() if callable(self.dock) else None
        if d is not None:
            return QPointF(d.left() - self.width() + self.PAD - 4, d.bottom() - self.height() + self.PAD - 10)
        return QPointF(area.right() - self.width() + self.PAD - 10, area.bottom() - self.height() + self.PAD - 10)

    def _place(self, tip: QPointF):
        self._tip = tip
        self.move(int(tip.x() - self.PAD), int(tip.y() - self.PAD))

    def body_center(self) -> QPointF:
        s = self.size_px
        return self._tip + QPointF(s * 0.62, s * 0.64)

    def visible_needed(self) -> bool:
        if not config.settings().get("cursor_visible", True):
            return False
        if self.always() or self.mode in ("fly", "follow") or self._holding:
            return True
        if self.state in ("listening", "thinking", "acting", "speaking"):  # 대화하는 동안엔 오른쪽에 나타난다
            return True
        return time.monotonic() < self._needed_until

    # ---- 움직임 ----

    def home(self, instant=False):
        if instant or self._alpha < 0.05:
            self.mode = "home"
            self._place(self.home_point())
            self._set_click_through(False)
            return
        self._start_fly(self.home_point(), after="home")

    def show_at_mouse(self):
        """Ctrl+Alt+P: 지금 마우스 자리로 날아가서 가리킨다."""
        self._start_fly(QPointF(QCursor.pos()), after="point")

    def _fly_physical(self, x: int, y: int, kind: str):
        dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        self._start_fly(QPointF(x / dpr, y / dpr), after="point")

    def _start_fly(self, target: QPointF, after: str):
        if self._alpha < 0.05 and not self.always():
            # 숨어 있다가 나올 땐 화면 오른쪽 아래(탭 쪽)에서 출발 — 원본처럼 집에서 날아 나온다
            self._place(self.home_point())
        self._from = QPointF(self._tip)
        self._to = target
        dist = math.hypot(target.x() - self._from.x(), target.y() - self._from.y())
        self._dur = min(0.75, max(0.22, dist / 2000))
        self._t0 = time.monotonic()
        self._after_fly = after
        self.mode = "fly"
        self._needed_until = time.monotonic() + self._dur + LINGER_SECONDS
        self._set_click_through(True)

    def _tick(self):
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        self._phase += dt
        if self.mode == "fly":
            t = min(1.0, (now - self._t0) / self._dur)
            k = ease(t)
            mid = QPointF((self._from.x() + self._to.x()) / 2, min(self._from.y(), self._to.y()) - 90)
            a = self._from * (1 - k) ** 2 + mid * 2 * (1 - k) * k + self._to * k * k
            self._look = self._to - self.body_center()
            self._place(a)
            self.moved.emit(self.body_center())
            if t >= 1.0:
                self.mode = self._after_fly
                if self.mode == "point":
                    self._needed_until = now + LINGER_SECONDS + (6 if self.state == "acting" else 0)
                self._set_click_through(self.mode != "home")
        elif self.mode in ("home", "follow"):
            want_follow = config.settings()["cursor_follow"] and self.state in ("sleep", "idle")
            if want_follow:
                if self.mode != "follow":
                    self.mode = "follow"
                    self._set_click_through(True)
                m = QPointF(QCursor.pos()) + QPointF(26, 30)
                self._place(self._tip + (m - self._tip) * 0.12)
            elif self.mode == "follow":
                self.home()
            self._look = QPointF(QCursor.pos()) - self.body_center()
        elif self.mode == "point":
            if self.state == "acting":
                self._needed_until = max(self._needed_until, now + 1.5)
            self._look = QPointF(QCursor.pos()) - self.body_center()
            if now > self._needed_until and not self.always():
                pass  # 아래에서 사라지고 나면 집으로

        # 나타나기 / 스르르 사라지기
        want = 1.0 if self.visible_needed() else 0.0
        self._alpha += (want - self._alpha) * min(1.0, dt * (10 if want else 4))
        if self._alpha > 0.02:
            if not self.isVisible():
                self.show()
                self._set_click_through(self.mode != "home")
            self.setWindowOpacity(self._alpha)
        elif self.isVisible():
            self.hide()
            if self.mode == "point":
                self.mode = "home"
                self._place(self.home_point())

        # 눈동자 (생각 중엔 위쪽을 데굴데굴)
        r = self.size_px * 0.36
        lim = r * 0.12
        n = math.hypot(self._look.x(), self._look.y()) or 1
        reach = min(1.0, n / 200)
        target = QPointF(self._look.x() / n * lim * reach, self._look.y() / n * lim * reach)
        if self.state == "thinking":
            target = QPointF(math.cos(self._phase * 2.2) * lim * 0.8, -lim * 0.9)
        for i, eye in enumerate(self._eyes):
            eye.step(target + QPointF(0, 0.5 * i), dt)
        self._squash += ((0.12 if self._holding else 0.0) - self._squash) * min(1.0, dt * 18)
        if now > self._blink_at + 0.14:
            self._blink_at = now + random.uniform(2.5, 5.5)
        if self.isVisible():
            self.update()

    def set_state(self, state: str):
        if state in ("idle", "sleep") and self.state in ("listening", "thinking", "acting", "speaking"):
            self._needed_until = max(self._needed_until, time.monotonic() + 6)  # 대답이 끝나도 잠깐 더 있다가 들어간다
        if state in ("listening", "thinking", "speaking") and self.mode == "home":
            self._place(self.home_point())   # 대화창 옆 제자리로
        self.state = state
        if state == "acting":
            self._needed_until = max(self._needed_until, time.monotonic() + 3)

    def _set_click_through(self, on: bool):
        hwnd = int(self.winId())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_NOACTIVATE
        style = style | WS_EX_TRANSPARENT if on else style & ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    # ---- 마우스 (항상 보이기일 때): 꾹 = 말하기, 우클릭 = 설정, 톡 = 말풍선 ----

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.open_settings.emit()
            return
        if e.button() == Qt.LeftButton:
            self._holding = True
            self._hold.start(HOLD_TO_TALK_MS)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self._holding = False
        if self._talking:
            self._talking = False
            self.talk_end.emit()
        elif self._hold.isActive():
            self._hold.stop()
            self.clicked.emit()

    def _hold_started(self):
        if self._holding:
            self._talking = True
            self.talk_start.emit()

    # ---- 그리기: 물방울 커서 + 작은 말랑한 눈 ----

    def paintEvent(self, _):
        """원본 블루이 커서처럼: 매끈한 물방울, 하얀 테두리, 은은한 빛, 작은 말랑한 눈 두 개."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.size_px
        color = QColor(config.settings().get("color") or "#8B5CF6")
        if self.state == "sleep":
            color = color.darker(120)
        ring = QColor(STATE_COLORS.get(self.state, "#ffffff"))
        o = QPointF(self.PAD, self.PAD)                       # 커서 끝 (가리키는 곳)
        breathe = math.sin(self._phase * (7 if self.state == "listening" else 2.0)) * 0.015
        c = o + QPointF(s * 0.6, s * 0.6)                      # 동그란 몸
        r = s * 0.37 * (1 + breathe)

        # 은은한 빛: 평소엔 퍼플루 색, 일할 땐 상태 색
        halo = QColor(color if self.state in ("sleep", "idle", "speaking", "listening") else ring)
        g = QRadialGradient(c, r * 2.1)
        halo.setAlpha(0 if self.state == "listening" else 120 if self.mode == "fly" or self.state == "acting" else 70)  # 들을 땐 대화창이 빛난다
        g.setColorAt(0, halo)
        g.setColorAt(0.55, QColor(halo.red(), halo.green(), halo.blue(), halo.alpha() // 3))
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, r * 2.1, r * 2.1)

        # 매끈한 물방울: 원 둘레를 따라 돌다가 끝(o)에서 살짝 둥글게 모인다
        sx, sy = 1 + self._squash, 1 - self._squash * 0.8
        ang = math.atan2(o.y() - c.y(), o.x() - c.x())        # 몸 중심에서 끝을 향한 방향
        d = math.hypot(o.x() - c.x(), o.y() - c.y())
        spread = math.acos(min(0.99, r / d))                   # 접선이 닿는 각도
        tip_r = s * 0.05
        tip_in = QPointF(o.x() + math.cos(ang + math.pi) * tip_r * 1.6, o.y() + math.sin(ang + math.pi) * tip_r * 1.6)
        drop = QPainterPath()
        start = ang + spread
        sweep = 2 * math.pi - 2 * spread
        steps = 48
        for i in range(steps + 1):
            a = start + sweep * i / steps
            pt = QPointF(c.x() + math.cos(a) * r * sx, c.y() + math.sin(a) * r * sy)
            if i == 0:
                drop.moveTo(pt)
            else:
                drop.lineTo(pt)
        # 끝 부분: 두 접선이 o 근처에서 둥글게 만나도록
        side1 = QPointF(c.x() + math.cos(ang - spread) * r * sx, c.y() + math.sin(ang - spread) * r * sy)
        side2 = QPointF(c.x() + math.cos(ang + spread) * r * sx, c.y() + math.sin(ang + spread) * r * sy)
        near1 = o + (side1 - o) * 0.18
        near2 = o + (side2 - o) * 0.18
        drop.lineTo(near1)
        drop.quadTo(o + (tip_in - o) * -0.15, near2)
        drop.closeSubpath()

        body = QRadialGradient(c - QPointF(r * 0.5, r * 0.65), r * 1.9)
        body.setColorAt(0, color.lighter(175))
        body.setColorAt(0.5, color)
        body.setColorAt(1, color.darker(150))
        outline = QPen(QColor(255, 255, 255, 245), max(2.5, s / 14))
        outline.setJoinStyle(Qt.RoundJoin)
        p.setPen(outline)
        p.setBrush(body)
        p.drawPath(drop)

        # 윗부분 광택
        p.setPen(Qt.NoPen)
        shine = QRadialGradient(c - QPointF(r * 0.35, r * 0.45), r * 0.6)
        shine.setColorAt(0, QColor(255, 255, 255, 110))
        shine.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.drawEllipse(c - QPointF(r * 0.35, r * 0.45), r * 0.6, r * 0.45)

        # 작은 말랑한 눈 두 개 (원본처럼 몸 가운데 살짝 아래)
        blinking = time.monotonic() > self._blink_at and self.state != "sleep"
        for i, side in enumerate((-1, 1)):
            e = c + QPointF(side * r * 0.3 + r * 0.05, r * 0.1 + i * r * 0.07)
            er = r * 0.25
            if self.state == "sleep" or blinking:
                p.setPen(pen("white", max(1.6, s / 24)))
                p.setBrush(Qt.NoBrush)
                p.drawArc(QRectF(e.x() - er, e.y() - er * 0.5, er * 2, er), 200 * 16, 140 * 16)
                continue
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("white"))
            p.drawEllipse(e, er, er)
            pupil = e + self._eyes[i].pos * 1.1
            p.setBrush(QColor("#15111C"))
            p.drawEllipse(pupil, er * 0.52, er * 0.52)
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawEllipse(pupil + QPointF(-er * 0.18, -er * 0.2), er * 0.15, er * 0.15)

        # 생각 중: 머리 위 점점점
        if self.state == "thinking":
            for k in range(3):
                a = 1 - k * 0.25
                wob = math.sin(self._phase * 3 + k) * r * 0.06
                p.setPen(QPen(QColor(124, 58, 237, int(190 * a)), max(1.0, s / 70)))  # 흰 배경에서도 보이게
                p.setBrush(QColor(255, 255, 255, int(255 * a)))
                p.drawEllipse(c + QPointF(r * (0.55 + k * 0.3), -r * (1.1 + k * 0.2) + wob), r * 0.1, r * 0.1)
        if self.state == "sleep":
            p.setPen(QColor(255, 255, 255, 210))
            p.setFont(QFont("Segoe UI", max(7, int(s / 7)), QFont.Bold))
            p.drawText(c + QPointF(r * 0.75, -r * 0.95 - (self._phase * 8 % 8)), "z")
        p.end()
