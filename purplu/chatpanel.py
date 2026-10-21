"""PC 대화창 (웹 엔진 없이 Qt로 직접 그린다).

예전 대화창은 웹 엔진(Qt WebEngine)이 스스로 죽고, 움직일 때 깜빡였다. 이건 퍼플루 안에서 가볍게 돈다.
위: 퍼플루 얼굴 (꾹 누르면 PC 마이크로 듣기) · 아래: 대화 · 맨 아래: 빛이 도는 입력칸.
고정(📌)·자리 차지·언제나 맨 위로·몇 초 뒤 사라지기, /스킬 · @멘션 · 그림 첨부.
"""
import ctypes
import html
import math
import random
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QConicalGradient, QCursor, QFont, QGuiApplication, QLinearGradient, QPainter,
                           QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from . import config, store

GLOWS = {
    "rainbow": ["#4285F4", "#9B72CB", "#D96570", "#F2A60C"],
    "blue_purple": ["#3B82F6", "#8B5CF6", "#6366F1", "#06B6D4"],
    "pink_purple": ["#EC4899", "#A855F7", "#F472B6"],
    "sunset": ["#F97316", "#EF4444", "#EC4899", "#FACC15"],
    "ocean": ["#06B6D4", "#3B82F6", "#10B981"],
}
EXAMPLES = ["오늘 날씨 어때?", "요즘 유행하는 거 알려줘", "계산기 열어서 3 곱하기 9 해줘"]   # 새 대화 예시 3개
# '/' 를 치면 뜨는 명령 (이름, 설명). 한글로 쳐도 설명에서 찾아진다
COMMANDS = [
    ("settings", "설정 열기"),
    ("new", "새 대화 시작"),
    ("rename", "이 대화 이름 바꾸기"),
    ("delete", "이 대화 지우기"),
    ("chats", "다른 대화로 바꾸기"),
    ("web", "위쪽을 퍼플루 ↔ 퍼플루 브라우저로"),
    ("model", "빠른 모델 ↔ 생각하는 모델"),
    ("mini", "작은 모드 켜기/끄기"),
    ("pin", "오른쪽에 고정 / 풀기"),
    ("top", "언제나 맨 위로 켜기/끄기"),
    ("image", "그림 붙이기"),
    ("skills", "스킬 목록 (# 으로도 불러요)"),
    ("close", "대화창 닫기"),
]
CMD_ALIAS = {"browser": "web", "브라우저": "web", "setting": "settings", "설정": "settings", "새대화": "new", "clear": "new"}

MODELS = {"gemini-3.8-live": "⚡ 빠른 모델", "gemini-3.8-live-extended-thinking": "🧠 생각하는 모델"}
STATUS = {"sleep": "듣는 중", "idle": "듣는 중", "listening": "듣는 중…", "thinking": "생각 중…",
          "acting": "하는 중…", "speaking": "말하는 중"}


def light() -> bool:
    return config.settings().get("theme") == "light"


def pal():
    """지금 테마의 색들."""
    if light():
        return dict(bg="#FFFFFF", face_bg="#FAF8FF", text="#1F1235", dim="#71717A", bubble="#EDE9FE", line="#EDE9FE", card="#FAF8FF")
    return dict(bg="#120B22", face_bg="#000000", text="#F5F3FF", dim="#A1A1AA", bubble="#2E1F4F", line="#2E1F4F", card="#1B1230")


def on_color(hexv: str) -> str:
    c = QColor(hexv)
    lum = 0.2126 * c.redF() ** 2.2 + 0.7152 * c.greenF() ** 2.2 + 0.0722 * c.blueF() ** 2.2
    return "#1F1235" if lum > 0.45 else "#FFFFFF"


def glow_colors() -> list[str]:
    s = config.settings()
    return GLOWS.get(s.get("chat_glow") or "rainbow") or [s.get("color") or "#8B5CF6", "#FFFFFF", s.get("color") or "#8B5CF6"]


# ------------------------------------------------------------------ 얼굴
class FaceView(QWidget):
    """위쪽 퍼플루 얼굴. 눈이 마우스를 따라가고, 깜빡이고, 말하면 입이 움직인다. 꾹 누르면 듣기."""
    pressed = Signal()
    released = Signal()

    def __init__(self):
        super().__init__()
        self.state = "idle"
        self.talk = 0.0
        self._gx = self._gy = 0.0
        self._blink_at, self._blink = time.monotonic() + 3, 0.0
        self._t0 = time.monotonic()
        self._happy_until = 0.0
        self._timer = QTimer(self, timeout=self._tick)
        self.setMinimumHeight(140)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("꾹 누르고 말하기")

    def showEvent(self, e):
        self._timer.start(33)  # 보일 때만 움직인다 (가볍게)
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def set_state(self, s: str):
        if self.state == "speaking" and s == "idle":
            self._happy_until = time.monotonic() + 1.5
        self.state = s

    def _tick(self):
        now = time.monotonic()
        # 눈: 마우스 쪽으로 부드럽게
        c = self.mapToGlobal(self.rect().center())
        m = QCursor.pos()
        tx = max(-1, min(1, (m.x() - c.x()) / 600))
        ty = max(-1, min(1, (m.y() - c.y()) / 400))
        if self.state == "thinking":
            tx, ty = 0.6 + 0.1 * math.sin(now * 1.3), -0.8
        self._gx += (tx - self._gx) * 0.18
        self._gy += (ty - self._gy) * 0.18
        want = (0.5 + 0.5 * math.sin(now * 19) * math.sin(now * 7.3)) if self.state == "speaking" else 0
        self.talk += (want - self.talk) * 0.5
        if now > self._blink_at:
            self._blink = now
            self._blink_at = now + random.uniform(2, 5)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.pressed.emit()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.released.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        P = pal()
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QColor(P["face_bg"]))
        now = time.monotonic()
        base = QColor(config.settings().get("color") or "#8B5CF6")
        s = min(W / 884, H * 0.95 / 390)  # 원래 디자인(844×390)이 다 들어오게
        p.translate((W - 844 * s) / 2, H - 390 * s)
        p.scale(s, s)
        bob = math.sin((now - self._t0) * 1.8) * 3 - self.talk * 14
        body = QRectF(12, 44 + bob, 820, 700)
        # 빛
        if self.state == "listening":
            glow = QRadialGradient(body.center().x(), body.top() + 200, 520)
            aura = QColor(config.settings().get("chat_color") or config.settings().get("color") or "#8B5CF6")
            aura.setAlpha(150)
            glow.setColorAt(0, aura)   # 듣는 동안의 빛 = 내가 고른 색
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(QRectF(-200, -200, 1300, 900), glow)
        path = QPainterPath()
        cx, top, bot = body.center().x(), body.top(), body.bottom()
        path.moveTo(body.left(), bot)
        path.cubicTo(body.left() - 4, top + body.height() * .36, cx - body.width() * .36, top, cx, top)
        path.cubicTo(cx + body.width() * .36, top, body.right() + 4, top + body.height() * .36, body.right(), bot)
        path.closeSubpath()
        grad = QLinearGradient(body.topLeft(), QPointF(body.right(), body.top() + body.height() * .6))
        grad.setColorAt(0, base.lighter(170))
        grad.setColorAt(.5, base)
        grad.setColorAt(1, base.darker(140))
        p.fillPath(path, grad)
        shine = QRadialGradient(body.left() + 246, body.top() + 126, 243)
        shine.setColorAt(0, QColor(255, 255, 255, 120))
        shine.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, shine)
        navy = QColor(base).darker(260)
        ink = QColor("#1A1426")
        happy = time.monotonic() < self._happy_until
        sleeping = self.state == "sleep" and False
        bt = (now - self._blink) / 0.15
        closed = math.sin(math.pi * bt) if 0 <= bt <= 1 else 0
        for i, ex in enumerate((body.left() + 280, body.left() + 540)):
            ey = body.top() + 157
            side = -1 if i == 0 else 1
            # 눈썹
            p.setPen(QPen(navy, 14, Qt.SolidLine, Qt.RoundCap))
            lift = {"listening": 10, "thinking": 4, "speaking": 8}.get(self.state, 0)
            brow = QPainterPath()
            brow.moveTo(ex - 38 + side * 6, ey - 106 - lift * .7)
            brow.quadTo(ex + side * 6, ey - 124 - lift * .7, ex + 38 + side * 6, ey - 106 - lift * .7)
            p.drawPath(brow)
            if happy:
                p.setPen(QPen(ink, 24, Qt.SolidLine, Qt.RoundCap))
                arc = QPainterPath()
                arc.moveTo(ex - 60, ey + 34)
                arc.quadTo(ex, ey - 54, ex + 60, ey + 34)
                p.drawPath(arc)
                continue
            open_ = max(0.06, 1 - closed) * (1 - self.talk * 0.12)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("white"))
            p.drawEllipse(QPointF(ex, ey), 95, 95 * open_)
            if open_ > 0.2:
                r = 46 * (1.12 if self.state == "listening" else 1)
                px, py = ex + self._gx * 50 - side * 3, ey + self._gy * 50 * open_
                clip = QPainterPath()
                clip.addEllipse(QPointF(ex, ey), 95, 95 * open_)
                p.save()
                p.setClipPath(clip)
                p.setBrush(ink)
                p.drawEllipse(QPointF(px, py), r, r)
                p.setBrush(QColor("white"))
                p.drawEllipse(QPointF(px - r * .3, py - r * .44), r * .28, r * .28)
                p.setBrush(QColor(255, 255, 255, 215))
                p.drawEllipse(QPointF(px + r * .4, py + r * .34), r * .12, r * .12)
                p.restore()
        # 볼
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(243, 166, 216, 110 if happy else 70))
        for ex in (body.left() + 218, body.left() + 602):
            p.drawEllipse(QPointF(ex, body.top() + 274), 45, 21)
        # 입
        nw, nh = 60 - self.talk * 8, 38 + self.talk * 34
        nx, ny = body.left() + 410 - nw / 2, body.top() + 272 - self.talk * 6
        p.setBrush(navy)
        if happy and self.talk < .1:
            m = QPainterPath()
            m.moveTo(nx - 8, ny + 8)
            m.quadTo(nx + nw / 2, ny + 58, nx + nw + 8, ny + 8)
            m.closeSubpath()
            p.drawPath(m)
        else:
            p.drawEllipse(QRectF(nx, ny, nw, nh))
        # 생각 중: 점점점
        if self.state == "thinking":
            for k in range(3):
                p.setBrush(QColor(255, 255, 255, int(255 * (1 - k * .3))))
                p.drawEllipse(QPointF(body.left() + 698 + k * 26, body.top() + 48 - k * 12 + math.sin(now * 3 + k) * 4), 8, 8)
        p.end()


_VERBS = {"여는": "열기", "읽는": "읽기", "누르는": "누르기", "입력하는": "입력하기", "찾아보는": "찾아보기", "찾는": "찾기",
          "보는": "보기", "그리는": "그리기", "바꾸는": "바꾸기", "닫는": "닫기", "표시하는": "표시하기", "남기는": "남기기",
          "쓰는": "쓰기", "지우는": "지우기", "하는": "하기", "스크롤하는": "스크롤하기", "정리하는": "정리하기",
          "확인하는": "확인하기", "검색": "검색", "계산하는": "계산하기", "옮기는": "옮기기", "저장": "저장"}


def _done_title(label: str) -> str:
    """'웨일에서 'naver.com' 여는 중…' → '웨일에서 'naver.com' 열기' (끝난 일은 짧게)."""
    t = label.rstrip("…. ").strip()
    if t.endswith(" 중"):
        t = t[:-2]
        head, _, last = t.rpartition(" ")
        t = (head + " " if head else "") + _VERBS.get(last, last)
    return t


# ------------------------------------------------------------------ @·/ 목록 한 줄
class _SuggestDelegate(QStyledItemDelegate):
    """왼쪽: 이름(길면 …로 줄임) · 오른쪽: 종류(작게, 흐리게). 가로로 넘치지 않게."""

    def sizeHint(self, option, index):
        from PySide6.QtCore import QSize
        return QSize(option.rect.width(), 34)

    def paint(self, p, option, index):
        P = pal()
        p.save()
        r = option.rect
        if option.state & (QStyle.State_Selected | QStyle.State_MouseOver):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(P["bubble"]))
            p.drawRoundedRect(QRectF(r).adjusted(2, 1, -2, -1), 8, 8)
        kind = index.data(Qt.UserRole) or ""
        f = QFont(option.font)
        f.setPointSizeF(8.5)
        p.setFont(f)
        kind = p.fontMetrics().elidedText(kind, Qt.ElideRight, int(r.width() * 0.4))   # 긴 설명은 줄여서 이름을 가리지 않게
        kw = p.fontMetrics().horizontalAdvance(kind) + 14
        p.setPen(QColor(P["dim"]))
        p.drawText(QRectF(r.right() - kw, r.top(), kw - 10, r.height()), Qt.AlignVCenter | Qt.AlignRight, kind)
        p.setFont(option.font)
        p.setPen(QColor(P["text"]))
        name = p.fontMetrics().elidedText(index.data(Qt.DisplayRole) or "", Qt.ElideRight, r.width() - kw - 24)
        p.drawText(QRectF(r.left() + 12, r.top(), r.width() - kw - 12, r.height()), Qt.AlignVCenter | Qt.AlignLeft, name)
        p.restore()


# ------------------------------------------------------------------ 머리줄 선 아이콘
class IconButton(QPushButton):
    """⚙·＋·작게·고정·닫기를 같은 굵기의 선으로 그린다 (이모티콘마다 색·크기가 달라 지저분하던 것)."""

    def __init__(self, kind: str, tip: str):
        super().__init__()
        self.kind, self.active, self._hover = kind, False, False
        self.setToolTip(tip)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        P = pal()
        accent = QColor(config.settings().get("chat_color") or config.settings().get("color") or "#8B5CF6")
        if self._hover or self.active:
            bg = QColor(accent if self.active else P["bubble"])
            if self.active:
                bg.setAlpha(40)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)
        col = accent if self.active else QColor(P["dim"] if not self._hover else P["text"])
        pen = QPen(col, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        cx, cy = self.width() / 2, self.height() / 2
        k = self.kind
        if k == "settings":   # 톱니: 동그라미 + 짧은 살 8개
            p.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
            for i in range(8):
                a = i * math.pi / 4
                p.drawLine(QPointF(cx + math.cos(a) * 5.6, cy + math.sin(a) * 5.6), QPointF(cx + math.cos(a) * 7.6, cy + math.sin(a) * 7.6))
            p.drawEllipse(QPointF(cx, cy), 5.6, 5.6)
        elif k == "new":      # 연필 달린 네모 (새 대화)
            p.drawRoundedRect(QRectF(cx - 7, cy - 6, 12, 13), 2.5, 2.5)
            p.drawLine(QPointF(cx - 1, cy + 2), QPointF(cx + 7, cy - 6))
        elif k == "mini":     # 작게: 가로선 / 크게: 네모
            if self.active:
                p.drawRoundedRect(QRectF(cx - 6, cy - 6, 12, 12), 2, 2)
            else:
                p.drawLine(QPointF(cx - 6, cy + 4), QPointF(cx + 6, cy + 4))
        elif k == "pin":      # 압정
            path = QPainterPath()
            path.moveTo(cx - 5, cy - 7)
            path.lineTo(cx + 5, cy - 7)
            path.lineTo(cx + 3, cy - 1)
            path.lineTo(cx + 6, cy + 2)
            path.lineTo(cx - 6, cy + 2)
            path.lineTo(cx - 3, cy - 1)
            path.closeSubpath()
            if self.active:
                p.setBrush(accent)
            p.drawPath(path)
            p.drawLine(QPointF(cx, cy + 2), QPointF(cx, cy + 8))
        elif k == "web":      # 지구본 (퍼플루 브라우저)
            p.drawEllipse(QPointF(cx, cy), 7, 7)
            p.drawEllipse(QPointF(cx, cy), 3, 7)
            p.drawLine(QPointF(cx - 7, cy), QPointF(cx + 7, cy))
        elif k == "close":
            p.drawLine(QPointF(cx - 5.5, cy - 5.5), QPointF(cx + 5.5, cy + 5.5))
            p.drawLine(QPointF(cx + 5.5, cy - 5.5), QPointF(cx - 5.5, cy + 5.5))
        p.end()


# ------------------------------------------------------------------ 빛이 도는 입력칸
class GlowBox(QFrame):
    def __init__(self):
        super().__init__()
        self.angle = 0.0
        self.fast = False
        self._timer = QTimer(self, timeout=self._spin)
        self.setContentsMargins(3, 3, 3, 3)

    def showEvent(self, e):
        self._timer.start(40)
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _spin(self):
        self.angle = (self.angle - (9 if self.fast else 3)) % 360
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        g = QConicalGradient(r.center(), self.angle)
        cols = glow_colors()
        for i, c in enumerate(cols + [cols[0]]):
            g.setColorAt(i / len(cols), QColor(c))
        p.setPen(QPen(g, 3))
        p.setBrush(QColor(pal()["bg"]))
        p.drawRoundedRect(r, 22, 22)
        p.end()


class StatusLabel(QLabel):
    """'듣는 중' 글자. 듣는 동안엔 내 그라데이션이 오른쪽으로 흘러간다."""

    def __init__(self):
        super().__init__()
        self.flow = False
        self._x = 0.0
        self._timer = QTimer(self, timeout=self._step)

    def set_flow(self, on: bool):
        self.flow = on
        (self._timer.start(40) if on else self._timer.stop())
        self.update()

    def _step(self):
        self._x = (self._x + 6) % 300
        self.update()

    def paintEvent(self, e):
        if not self.flow:
            return super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        cols = glow_colors()
        w = max(1, self.width())
        g = QLinearGradient(self._x - 300, 0, self._x - 300 + w * 1.5, 0)
        g.setSpread(QLinearGradient.RepeatSpread)
        for i, c in enumerate(cols + [cols[0]]):
            g.setColorAt(i / len(cols), QColor(c))
        f = self.font()
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(g, 1))
        path = QPainterPath()
        path.addText(0, self.height() / 2 + p.fontMetrics().ascent() / 2 - 2, f, self.text())
        p.fillPath(path, g)
        p.end()


# ------------------------------------------------------------------ 자리 차지 (Windows 앱바)
class _APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uCallbackMessage", wintypes.UINT),
                ("uEdge", wintypes.UINT), ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]


# ------------------------------------------------------------------ 대화창
class ChatPanel(QWidget):
    _mentions_ready = Signal(list)
    _history_ready = Signal(list)
    _skills_ready = Signal(list)
    _convs_ready = Signal(list)
    _web_hwnd = Signal(int)    # 퍼플루 브라우저 창이 생김 → 위쪽 칸에 끼우기
    _web_used = Signal()       # 퍼플루가 브라우저를 씀 → 위쪽 칸을 브라우저로

    def __init__(self, brain, icon=None, open_settings=None):
        super().__init__(None, Qt.Window)
        self.brain = brain
        self.open_settings = open_settings or (lambda: None)
        self.mini = False
        self.setWindowTitle("퍼플루 대화")
        if icon:
            self.setWindowIcon(icon)
        self.state = "idle"
        self.history: list[dict] = []
        self.past: list[dict] = []
        self.turn = self._new_turn()
        self.attach = None
        self.mentions, self.chosen = [], []
        self._appbar = False
        self._placed = False
        self._render_timer = QTimer(self, singleShot=True, timeout=self._render)

        lay = QVBoxLayout(self)
        from PySide6.QtWidgets import QLayout, QSizePolicy
        lay.setSizeConstraint(QLayout.SetNoConstraint)   # 글이 길어지거나 상태 글자가 바뀌어도 창 크기는 그대로
        self.setMinimumSize(300, 220)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.face = FaceView()
        self.face.pressed.connect(self._talk_start)
        self.face.released.connect(self._talk_end)
        from PySide6.QtWidgets import QStackedWidget
        self.top = QStackedWidget()
        self.top.addWidget(self.face)
        self.web_holder = QWidget()
        wl = QVBoxLayout(self.web_holder)
        wl.setContentsMargins(0, 0, 0, 0)
        self.web_wait = QLabel("퍼플루 브라우저 켜는 중…")
        self.web_wait.setAlignment(Qt.AlignCenter)
        wl.addWidget(self.web_wait)
        self.top.addWidget(self.web_holder)
        self._web_box = None
        lay.addWidget(self.top, 34)
        self._lay = lay
        self._web_hwnd.connect(self._embed_web)
        self._web_used.connect(lambda: self._show_web(True, auto=True))
        from . import ownbrowser_client
        from .tools import web_browser
        ownbrowser_client.listeners.append(self._web_hwnd.emit)
        web_browser.on_use.append(self._web_used.emit)

        self.body = QFrame()
        self.body.setObjectName("body")
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(14, 8, 14, 12)
        head = QHBoxLayout()
        self.title = QLabel("퍼플루")
        self.title.setObjectName("title")
        self.conv = QPushButton("새 대화 ▾")
        self.conv.setObjectName("conv")
        self.conv.setCursor(Qt.PointingHandCursor)
        self.conv.setToolTip("대화 바꾸기 · 이름 바꾸기")
        self.conv.clicked.connect(self._conv_menu)
        self.status = StatusLabel()
        self.status.setObjectName("status")
        self.status.hide()
        from PySide6.QtWidgets import QSizePolicy
        for wdg in (self.conv, self.status):
            wdg.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # 글자가 길어도 창이 넓어지지 않게
            wdg.setMinimumWidth(40)
        self.conv.setMinimumWidth(190)   # 대화 제목이 너무 잘리지 않게
        self.status.setMinimumWidth(96)   # '말하는 중' 이 잘리지 않게
        head.addWidget(self.title)
        head.addSpacing(6)
        head.addWidget(self.conv, 0)
        head.addWidget(self.status)
        head.addStretch(1)
        self.btn_web = IconButton("web", "위쪽을 퍼플루 ↔ 퍼플루 브라우저로 바꾸기")
        self.btn_web.clicked.connect(lambda: self._show_web(self.top.currentIndex() == 0))
        btn_new = IconButton("new", "새 대화")
        btn_new.clicked.connect(self._new_chat)
        self.btn_mini = IconButton("mini", "작게 / 크게")
        self.btn_mini.clicked.connect(self._toggle_mini)
        self.btn_pin = IconButton("pin", "오른쪽에 고정 / 풀기")
        self.btn_pin.clicked.connect(lambda: config.save_settings(pc_chat_pinned=not config.settings().get("pc_chat_pinned")))
        btn_set = IconButton("settings", "설정")
        btn_set.clicked.connect(lambda: self.open_settings())
        btn_close = IconButton("close", "닫기 (Ctrl+Alt+C로 다시 열기)")
        btn_close.clicked.connect(self._close_clicked)
        head.setSpacing(2)
        for b in (self.btn_web, btn_new, self.btn_mini, self.btn_pin, btn_set):
            head.addWidget(b)
        sep = QFrame()
        sep.setFixedSize(1, 16)
        sep.setObjectName("sep")
        head.addSpacing(4)
        head.addWidget(sep)
        head.addSpacing(4)
        head.addWidget(btn_close)
        bl.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setMinimumSize(10, 10)
        self.msgs = QWidget()
        self.msgs.setObjectName("msgs")
        self.msg_lay = QVBoxLayout(self.msgs)
        self.msg_lay.setContentsMargins(0, 4, 4, 4)
        self.msg_lay.setSpacing(8)
        self.msg_lay.addStretch(1)
        self.scroll.setWidget(self.msgs)
        bl.addWidget(self.scroll, 1)

        self.sugg = QListWidget()
        self.sugg.setItemDelegate(_SuggestDelegate(self.sugg))
        self.sugg.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sugg.setUniformItemSizes(True)
        self.sugg.setObjectName("sugg")
        self.sugg.setMaximumHeight(170)
        self.sugg.hide()
        self.sugg.itemClicked.connect(lambda it: self._pick(self.sugg.row(it)))
        self.sugg.setFocusPolicy(Qt.NoFocus)          # 눌러도 입력칸에서 글쓰기가 이어지게
        self.sugg.setMouseTracking(True)
        self.sugg.viewport().setMouseTracking(True)   # 이게 있어야 마우스를 올렸을 때 알 수 있다
        self.sugg.itemEntered.connect(lambda it: self.sugg.setCurrentItem(it))   # 마우스를 올리면 그게 골라짐
        bl.addWidget(self.sugg)
        self.attach_lbl = QLabel()
        self.attach_lbl.hide()
        bl.addWidget(self.attach_lbl)
        self.reply_to = ""
        self.reply_box = QFrame()
        rb = QHBoxLayout(self.reply_box)
        rb.setContentsMargins(10, 6, 6, 6)
        self.reply_lbl = QLabel()
        self.reply_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        rx = QPushButton("✕")
        rx.setFixedSize(22, 22)
        rx.setCursor(Qt.PointingHandCursor)
        rx.setStyleSheet("background:transparent; border:none;")
        rx.clicked.connect(lambda: (setattr(self, "reply_to", ""), self.reply_box.hide()))
        rb.addWidget(self.reply_lbl, 1)
        rb.addWidget(rx)
        self.reply_box.hide()
        bl.addWidget(self.reply_box)
        # 대답 글을 드래그해서 고르면 뜨는 '답글' 버튼
        self.quote_btn = QPushButton("↪ 답글", self)
        self.quote_btn.setCursor(Qt.PointingHandCursor)
        self.quote_btn.hide()
        self.quote_btn.clicked.connect(lambda: self._reply(self._picked_text))
        self.scroll.verticalScrollBar().valueChanged.connect(lambda _: self.quote_btn.hide())   # 스크롤하면 숨기기

        self.glow = GlowBox()
        gl = QVBoxLayout(self.glow)
        gl.setContentsMargins(14, 10, 12, 6)
        self.input = QPlainTextEdit()
        self.input.setObjectName("input")
        self.input.setPlaceholderText("퍼플루에게 물어보기  ( / 명령 · # 스킬 · @ 멘션 )")
        self.input.setFixedHeight(46)
        self.input.installEventFilter(self)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().installEventFilter(self)   # 한글 입력기가 화살표를 먼저 가져가도 잡도록
        self.input.textChanged.connect(self._text_changed)
        gl.addWidget(self.input)
        tools = QHBoxLayout()
        b_img = QPushButton("📎")
        b_img.setToolTip("그림 첨부")
        b_img.clicked.connect(self._attach)
        self.model = QComboBox()
        for k, t in MODELS.items():
            self.model.addItem(t, k)
        self.model.activated.connect(lambda _=None: config.save_settings(live_model=self.model.currentData()))
        self.b_mic = QPushButton("🎤")
        self.b_mic.setToolTip("꾹 누르고 말하기")
        self.b_mic.pressed.connect(self._talk_start)
        self.b_mic.released.connect(self._talk_end)
        self.b_send = QPushButton("➤")
        self.b_send.setObjectName("send")
        self.b_send.clicked.connect(self._send)
        self.b_mic.hide()   # 위의 퍼플루를 꾹 누르면 되니까 마이크 버튼은 안 보이게
        for b in (b_img, self.b_send):
            b.setFixedSize(36, 36)
        b_img.setObjectName("icon")
        self.b_mic.setObjectName("icon")
        tools.addWidget(b_img)
        tools.addWidget(self.model)
        tools.addStretch(1)
        tools.addWidget(self.b_send)
        gl.addLayout(tools)
        bl.addWidget(self.glow)
        lay.addWidget(self.body, 66)

        self._mentions_ready.connect(self._got_mentions)
        self._history_ready.connect(self._got_history)
        self._skills_ready.connect(self._got_skills)
        self._convs_ready.connect(self._got_convs)
        self.apply_theme()
        self.apply_on_top()
        self.set_state(getattr(brain, "last_state", "idle"))
        self.load_history()

    # ---------------- 모양 ----------------
    def apply_theme(self):
        s, P = config.settings(), pal()
        c = s.get("color") or "#8B5CF6"
        cc = s.get("chat_color") or c
        self._cc = cc
        self.setStyleSheet(f"""
            QWidget {{ font-family:'Malgun Gothic'; font-size:10.5pt; color:{P['text']}; }}
            QFrame#body, QWidget#msgs, QScrollArea, QScrollArea > QWidget > QWidget {{ background:{P['bg']}; }}
            QLabel#title {{ color:{c}; font-weight:700; font-size:12pt; }}
            QFrame#sep {{ background:{P['line']}; }}
            QLabel#status {{ color:{P['dim']}; }}
            QPushButton#conv {{ background:transparent; border:none; color:{P['dim']}; text-align:left; padding:2px 6px; border-radius:8px; max-width:230px; }}
            QPushButton#conv:hover {{ background:{P['bubble']}; color:{P['text']}; }}
            QMenu {{ background:{P['bg']}; color:{P['text']}; border:1px solid {P['line']}; border-radius:10px; padding:6px; }}
            QMenu::item {{ padding:7px 18px; border-radius:6px; }}
            QMenu::item:selected {{ background:{P['bubble']}; }}
            QMenu::separator {{ height:1px; background:{P['line']}; margin:4px 8px; }}
            QPushButton#icon {{ background:transparent; border:none; border-radius:17px; font-size:13pt; }}
            QPushButton#icon:hover {{ background:{P['bubble']}; }}
            QPushButton#send {{ background:{cc}; color:{on_color(cc)}; border:none; border-radius:18px; font-size:13pt; }}
            QPlainTextEdit#input {{ background:transparent; border:none; font-size:11pt; }}
            QComboBox {{ background:{cc}; color:{on_color(cc)}; border:none; border-radius:12px; padding:4px 10px; }}
            QComboBox QAbstractItemView {{ background:{P['bg']}; color:{P['text']}; selection-background-color:{P['bubble']}; }}
            QComboBox::drop-down {{ border:none; width:18px; }}
            QListWidget#sugg {{ background:{P['bg']}; border:1px solid {P['line']}; border-radius:10px; }}
            QListWidget#sugg::item:selected {{ background:{P['bubble']}; color:{P['text']}; }}
            QScrollBar:vertical {{ width:6px; background:transparent; }}
            QScrollBar::handle:vertical {{ background:{P['line']}; border-radius:3px; }}
        """)
        self.top.setVisible((s.get("pc_layout", "stack") != "full" or self.top.currentIndex() == 1) and not self.mini)
        idx = self.model.findData(s.get("live_model"))
        if idx >= 0:
            self.model.setCurrentIndex(idx)
        self.btn_pin.active = bool(s.get("pc_chat_pinned"))
        self.btn_pin.update()
        self._render()

    def apply_on_top(self):
        on = bool(config.settings().get("pc_chat_on_top", True))
        vis = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        if vis:
            self.show()

    def apply_settings(self):
        self.apply_theme()
        self.apply_on_top()
        self.apply_pin()

    # ---------------- 상태·이벤트 (퍼플루 → 대화창) ----------------
    @staticmethod
    def _new_turn():
        return {"heard": "", "reply": "", "thought": "", "steps": [], "results": []}

    def set_state(self, s: str):
        if s == "listening" and (self.turn["heard"] or self.turn["reply"]):
            self.past.append(self.turn)
            self.turn = self._new_turn()
        self.state = s
        self.face.set_state(s)
        active = s in ("listening", "thinking", "acting", "speaking")
        self.status.setText(STATUS.get(s, ""))
        self.status.set_flow(s == "listening")
        self.status.setVisible(active)          # 대화하는 동안엔 '듣는 중…' 같은 상태, 평소엔 대화 제목만
        self.conv.setVisible(not active)
        self.glow.fast = s in ("listening", "thinking", "acting")
        self._schedule()

    def on_event(self, kind: str, data):
        t = self.turn
        if kind == "state":
            self.set_state(data)
            return
        if kind == "heard":
            t["heard"] += data
        elif kind == "reply":
            t["reply"] += data
        elif kind == "thought":
            t["thought"] += data
        elif kind == "step":
            if data.get("done") and t["steps"] and t["steps"][-1]["label"] == data["label"]:
                data = {**data, "cmds": t["steps"][-1].get("cmds", [])}
                t["steps"][-1] = data
            else:
                t["steps"].append(dict(data))
        elif kind == "cmd" and t["steps"]:
            t["steps"][-1].setdefault("cmds", []).append(data)
        elif kind == "image":
            t["results"].append(f"🎨 {html.escape(data.get('caption', ''))}<br><img src='{html.escape(data['path'])}' width='300'>")
        elif kind == "report":
            t["results"].append("🔎 " + html.escape(data.get("report", "")).replace("\n", "<br>"))
        elif kind == "files":
            t["results"].append("<br>".join(f"📄 {html.escape(f['path'].split(chr(92))[-1])}" for f in data[:8]) or "찾은 파일이 없어요")
        elif kind == "error":
            t["results"].append(f"<span style='color:#EF4444'>⚠ {html.escape(str(data))}</span>")
        elif kind == "hint":
            t["results"].append(f"🙉 {html.escape(str(data))}")
        elif kind == "conversation":   # 다른 대화로 바뀜
            self.load_history()
            return
        elif kind == "conversations_changed":
            self._load_convs()
            return
        else:
            return
        self._schedule()

    # ---------------- 그리기 (모아서 한 번에) ----------------
    def _schedule(self):
        if not self._render_timer.isActive():
            self._render_timer.start(60)

    def _bubble(self, text: str, img: str = ""):
        # 예전에 저장된 말에 붙어 있던 퍼플루용 설명([멘션] …, (지시: …))은 빼고 내가 친 글만
        text = "\n".join(l for l in text.split("\n") if not l.startswith(("[멘션]", "(지시:"))).strip()
        lab = QLabel(html.escape(text, quote=False).replace("\n", "<br>") + (f"<br><img src='{img}' width='200'>" if img else ""))
        lab.setTextFormat(Qt.RichText)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setStyleSheet(f"background:{self._cc}; color:{on_color(self._cc)}; border-radius:14px; padding:8px 12px;")
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(lab, 0)
        lab.setMaximumWidth(int(self.scroll.width() * 0.82))
        w = QWidget()
        w.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        return w

    def _text(self, rich: str, size="11pt"):
        lab = QLabel(rich)
        lab.setTextFormat(Qt.RichText)   # &quot; 같은 게 그대로 보이지 않게
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        lab.setOpenExternalLinks(True)
        lab.setStyleSheet(f"font-size:{size};")
        return lab

    def _reply_text(self, text: str):
        """퍼플루의 대답: 글 아래에 복사 · 답글. 글을 드래그하면 고른 부분에만 답글."""
        P = pal()
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        lab = self._text(html.escape(text, quote=False).replace("\n", "<br>"))
        lab.installEventFilter(self)
        lab.setProperty("reply", True)
        v.addWidget(lab)
        row = QHBoxLayout()
        row.setSpacing(2)
        style = (f"QPushButton {{ background:transparent; border:none; border-radius:8px; color:{P['dim']}; padding:3px 8px; font-size:9pt; }}"
                 f"QPushButton:hover {{ background:{P['card']}; color:{P['text']}; }}")
        cp = QPushButton("⧉ 복사")
        rp = QPushButton("↪ 답글")
        for b in (cp, rp):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(style)
            row.addWidget(b)
        row.addStretch(1)

        def copy():
            QGuiApplication.clipboard().setText(text)
            cp.setText("✓ 복사됨")
            QTimer.singleShot(1200, lambda: cp.setText("⧉ 복사") if cp.parent() else None)
        cp.clicked.connect(copy)
        rp.clicked.connect(lambda: self._reply(lab.selectedText() or text))
        v.addLayout(row)
        return w

    def _reply(self, quote: str):
        quote = " ".join((quote or "").split())
        self.quote_btn.hide()
        if not quote:
            return
        self.reply_to = quote
        P = pal()
        fm = self.reply_lbl.fontMetrics()
        self.reply_lbl.setText(fm.elidedText(f"↪ 답글: {quote}", Qt.ElideRight, max(120, self.width() - 90)))
        self.reply_lbl.setToolTip(quote[:500])
        self.reply_box.setStyleSheet(f"QFrame {{ background:{P['card']}; border-left:3px solid {self._cc}; border-radius:8px; }}"
                                     f"QLabel {{ color:{P['dim']}; border:none; background:transparent; }}")
        self.reply_box.show()
        self.input.setFocus()

    def _steps(self, steps: list, open_=False, key=""):
        """'실행됨 명령 N개 ⌄' 아래에 한 줄씩. 줄을 누르면 실제 명령·결과가 펼쳐진다. 펼친 상태는 다시 그려도 유지."""
        s = config.settings()
        if not steps or not s.get("show_steps", True):
            return None
        P = pal()
        opened = getattr(self, "_open", set())
        self._open = opened
        running = any(not st.get("done", True) for st in steps)
        is_open = (key in opened) or (open_ and key + "!closed" not in opened)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 2, 0, 2)
        v.setSpacing(4)
        head = QPushButton(f"{'실행 중' if running else '실행됨'} 명령 {len(steps)}개  {'⌃' if is_open else '⌄'}")
        head.setCursor(Qt.PointingHandCursor)
        head.setStyleSheet(f"QPushButton {{ text-align:left; background:transparent; border:none; color:{P['dim']}; padding:2px 2px; font-size:10pt; }}"
                           f"QPushButton:hover {{ color:{P['text']}; }}")
        v.addWidget(head)
        box = QFrame()
        box.setStyleSheet(f"QFrame#stepbox {{ border:1px solid {P['line']}; border-radius:12px; background:{P['bg']}; }}")
        box.setObjectName("stepbox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        for n, st in enumerate(steps):
            rk = f"{key}#{n}"
            done, ok = st.get("done", True), st.get("ok", True)
            title = st.get("label") or st.get("call") or ""
            title = _done_title(title) if done else title
            if done and st.get("result"):
                title += f"  ·  {st['result']}"
            mark = "" if done and ok else ("⏳ " if not done else "⚠ ")
            row = QPushButton(f"{mark}{title}")
            row.setCursor(Qt.PointingHandCursor)
            border = f"border-top:1px solid {P['line']};" if n else ""
            col = P["dim"] if ok or not done else "#DC2626"
            row.setStyleSheet(f"QPushButton {{ text-align:left; background:transparent; border:none; {border} color:{col}; padding:9px 12px; font-size:10pt; }}"
                              f"QPushButton:hover {{ background:{P['card']}; color:{P['text']}; }}")
            fm = row.fontMetrics()
            row.setText(fm.elidedText(row.text(), Qt.ElideRight, max(120, self.scroll.width() - 70)) + "  ›")
            bl.addWidget(row)
            detail = None
            if rk in opened:
                parts = [f"<b>{html.escape(st.get('call') or '')}</b>"]
                if s.get("show_commands", True):
                    parts += [f"<span style='color:#B45309'>$ {html.escape(c)}</span>" for c in (st.get("cmds") or [])[-6:]]
                if st.get("result"):
                    parts.append(f"<span style='color:{P['dim']}'>└ {html.escape(st['result'])}"
                                 + (f" · {st['secs']}초" if st.get("secs") is not None else "") + "</span>")
                detail = self._text("<br>".join(parts), "9pt")
                detail.setStyleSheet(f"font-family:Consolas; font-size:9pt; background:{P['card']}; padding:8px 14px;")
                bl.addWidget(detail)
            row.clicked.connect(lambda _=False, k=rk: (opened.symmetric_difference_update({k}), self._render()))
        box.setVisible(is_open)
        v.addWidget(box)

        def toggle():
            if box.isVisible():
                opened.discard(key)
                opened.add(key + "!closed")
            else:
                opened.add(key)
                opened.discard(key + "!closed")
            self._render()
        head.clicked.connect(toggle)
        return w

    def _render(self):
        bar = self.scroll.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 30
        while self.msg_lay.count() > 1:  # 맨 끝 늘어나는 칸만 남기고 지우기
            wdg = self.msg_lay.takeAt(0).widget()
            if wdg:
                wdg.hide()                    # 바로 숨겨야 겹쳐 보이지 않는다
                wdg.setParent(None)
                wdg.deleteLater()
        def add(w):
            if w is not None:
                self.msg_lay.insertWidget(self.msg_lay.count() - 1, w)
                w.show()   # 이미 보이는 창에 새로 넣은 건 직접 보여 줘야 한다
        P = pal()
        if self.history and not self.mini:
            add(self._text(f"<div align='center' style='color:{P['dim']}; font-size:9pt'>이전 대화</div>"))
        for m in ([] if self.mini else self.history[-30:]):
            if m.get("role") == "user":
                add(self._bubble(m.get("text", "")))
            else:
                add(self._steps([{**st, "done": True, "label": st.get("label") or st.get("call")} for st in m.get("steps") or []],
                                key=f"h{m.get('t', '')}"))
                if m.get("text") and m["text"] != "(실행만 했어요)":
                    add(self._reply_text(m["text"]))
        for i, t in enumerate(([] if self.mini else self.past[-10:]) + [self.turn]):
            live = t is self.turn
            if t["heard"]:
                add(self._bubble(t["heard"], t.get("img", "")))
            if live and self.state in ("thinking", "acting") and not t["reply"]:
                add(self._text(f"<span style='color:{P['dim']}'>💭 생각 중…</span>"))
            add(self._steps(t["steps"], live and self.state in ("thinking", "acting"), key=f"t{id(t)}"))
            if t["reply"]:
                if live and self.state != "idle":   # 아직 말하는 중이면 글만
                    add(self._text(html.escape(t["reply"], quote=False).replace("\n", "<br>")))
                else:
                    add(self._reply_text(t["reply"]))
            for r in t["results"]:
                lab = self._text(r, "10pt")
                lab.setStyleSheet(f"background:{P['card']}; border:1px solid {P['line']}; border-radius:12px; padding:8px 10px;")
                add(lab)
        if self.msg_lay.count() == 1 and not self.mini:
            add(self._text(f"<div align='center' style='font-size:15pt; font-weight:600'><br>무엇을 도와드릴까요?</div>"))
            for ex in EXAMPLES:   # 누르면 바로 보내기
                b = QPushButton(ex)
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet(f"QPushButton {{ text-align:left; background:{P['card']}; border:1px solid {P['line']}; border-radius:14px; padding:10px 16px; color:{P['text']}; }}"
                                f"QPushButton:hover {{ background:{self._cc}; color:{on_color(self._cc)}; border-color:{self._cc}; }}")   # 올리면 내 색
                b.clicked.connect(lambda _=False, t=ex: (self.input.setPlainText(t), self._send()))
                add(b)
        if at_bottom or self.state != "idle" or not getattr(self, "_scrolled_once", False):
            self._scrolled_once = True
            for ms in (30, 120, 300):   # 새 말풍선 크기가 정해진 뒤 맨 아래로
                QTimer.singleShot(ms, lambda: bar.setValue(bar.maximum()))

    # ---------------- 대화 제목 · 바꾸기 · 이름 바꾸기 ----------------
    def _show_title(self, title: str):
        t = title or "새 대화"
        fm = self.conv.fontMetrics()
        self.conv.setText(fm.elidedText(t, Qt.ElideRight, 165) + " ▾")
        self.conv.setToolTip(f"{t}\n누르면 대화 바꾸기 · 이름 바꾸기")

    def _load_convs(self):
        def work():
            try:
                rows = store.list_conversations()
            except Exception:
                rows = []
            self._convs_ready.emit(rows)
        threading.Thread(target=work, daemon=True).start()

    def _got_convs(self, rows):
        self.convs = rows
        cur = config.settings().get("current_conversation") or ""
        self._show_title(next((c.get("title") for c in rows if c["id"] == cur), "새 대화"))

    def _conv_menu(self):
        m = QMenu(self)
        cur = config.settings().get("current_conversation") or ""
        m.addAction("＋  새 대화", self._new_chat)
        m.addAction("✎  이 대화 이름 바꾸기", self._rename_conv)
        m.addAction("🗑  이 대화 지우기", self._delete_conv)
        m.addSeparator()
        shown = [c for c in getattr(self, "convs", [])
                 if c["id"] == cur or not (c.get("title") == "새 대화" and c.get("updated") == c.get("created"))]
        for c in shown[:15]:
            title = (c.get("title") or "새 대화")[:34]
            act = m.addAction(("●  " if c["id"] == cur else "     ") + title)
            act.triggered.connect(lambda _=False, cid=c["id"]: self._switch_conv(cid))
        if not getattr(self, "convs", None):
            m.addAction("(대화를 불러오는 중…)").setEnabled(False)
            self._load_convs()
        m.exec(self.conv.mapToGlobal(self.conv.rect().bottomLeft()))

    def _switch_conv(self, cid: str):
        if cid == config.settings().get("current_conversation"):
            return
        self.brain.select_conversation(cid)
        self.past, self.turn = [], self._new_turn()
        self._show_title(next((c.get("title") for c in getattr(self, "convs", []) if c["id"] == cid), ""))
        QTimer.singleShot(400, self.load_history)   # 바뀐 대화의 지난 말 불러오기

    def _rename_conv(self):
        cid = config.settings().get("current_conversation") or ""
        if not cid:
            return
        old = next((c.get("title") for c in getattr(self, "convs", []) if c["id"] == cid), "")
        title, ok = QInputDialog.getText(self, "대화 이름 바꾸기", "새 이름:", text=old)
        if ok and title.strip():
            threading.Thread(target=lambda: store.rename_conversation(cid, title.strip()), daemon=True).start()
            self._show_title(title.strip())
            for c in getattr(self, "convs", []):
                if c["id"] == cid:
                    c["title"] = title.strip()

    def _delete_conv(self):
        from PySide6.QtWidgets import QMessageBox
        cid = config.settings().get("current_conversation") or ""
        if not cid:
            return
        title = next((c.get("title") for c in getattr(self, "convs", []) if c["id"] == cid), "이 대화")
        if QMessageBox.question(self, "대화 지우기", f"'{title}' 대화를 지울까요?\n지우면 되돌릴 수 없어요.") != QMessageBox.Yes:
            return
        self.convs = [c for c in getattr(self, "convs", []) if c["id"] != cid]
        threading.Thread(target=lambda: store.delete_conversation(cid), daemon=True).start()
        self._new_chat()   # 지운 뒤엔 새 대화로

    def _new_chat(self):
        self._hist_gen = getattr(self, "_hist_gen", 0) + 1   # 불러오던 옛 기록은 무시
        self.brain.new_conversation()
        self.history, self.past, self.turn = [], [], self._new_turn()
        self._show_title("새 대화")
        QTimer.singleShot(1500, self._load_convs)
        self._render()
        self.input.setFocus()

    def _show_web(self, on: bool, auto: bool = False):
        """위쪽 칸을 퍼플루 브라우저(on) 또는 퍼플루 얼굴로. 퍼플루가 브라우저를 쓰면 저절로 브라우저로."""
        if on == (self.top.currentIndex() == 1):
            return
        self.top.setCurrentIndex(1 if on else 0)
        self.btn_web.active = on
        self.btn_web.update()
        self._lay.setStretch(0, 60 if on else 34)   # 브라우저일 땐 위쪽을 더 크게
        if on:
            if self.mini:
                self._toggle_mini()
            self.top.show()
            if auto and not self.isVisible():
                self.open(False)
            from . import ownbrowser_client as ob
            if ob.alive() and ob.hwnd[0]:
                self._embed_web(ob.hwnd[0])
            else:
                threading.Thread(target=ob.start, daemon=True).start()
        else:
            self.top.setVisible(config.settings().get("pc_layout", "stack") != "full" and not self.mini)

    def _embed_web(self, hwnd: int):
        """따로 도는 퍼플루 브라우저 창을 위쪽 칸에 끼운다 (브라우저가 죽어도 대화창은 안 죽음)."""
        if getattr(self, "_web_embedded", 0) == hwnd:
            return
        from PySide6.QtGui import QWindow
        win = QWindow.fromWinId(hwnd)
        if win is None:
            return
        if self._web_box is not None:
            self._web_box.hide()
            self._web_box.setParent(None)
            self._web_box.deleteLater()
        self._web_box = QWidget.createWindowContainer(win, self.web_holder)
        self._web_box.setFocusPolicy(Qt.StrongFocus)
        self.web_wait.hide()
        self.web_holder.layout().addWidget(self._web_box)
        self._web_embedded = hwnd

    def _toggle_mini(self):
        """작은 모드: 얼굴을 숨기고 마지막 대화만, 창도 작게."""
        self.mini = not self.mini
        self.btn_mini.active = self.mini
        self.btn_mini.update()
        if self.mini:
            self._big_geom = self.geometry()
            self.top.hide()
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.setGeometry(area.right() - 400, area.bottom() - 290, 380, 270)
        else:
            self.top.setVisible(config.settings().get("pc_layout", "stack") != "full" or self.top.currentIndex() == 1)
            if getattr(self, "_big_geom", None):
                self.setGeometry(self._big_geom)
        self._render()

    # ---------------- 지난 대화 ----------------
    def load_history(self):
        self._hist_gen = getattr(self, "_hist_gen", 0) + 1
        gen = self._hist_gen

        def work():
            try:
                cid = config.settings().get("current_conversation") or ""
                rows = store.messages(cid)[-60:] if cid else []
            except Exception:
                rows = []
            self._history_ready.emit([gen, rows])
        threading.Thread(target=work, daemon=True).start()

    def _got_history(self, packed):
        gen, rows = packed
        if gen != getattr(self, "_hist_gen", 0):   # 그사이 새 대화를 시작했으면 옛 기록은 버린다
            return
        self._load_convs()
        self.history = rows
        self.past = []
        self._render()

    # ---------------- 보내기·말하기 ----------------
    def _talk_start(self):
        self.brain.talk_start("pc")

    def _talk_end(self):
        self.brain.talk_end()

    def _send(self):
        text = self.input.toPlainText().strip()
        if not text and not self.attach:
            return
        if text.startswith("/") and " " not in text:
            name = CMD_ALIAS.get(text[1:].lower(), text[1:].lower())
            if any(n == name for n, _ in COMMANDS):
                self.input.clear()
                self.sugg.hide()
                self._run_command(name)
                return
        mentions, self.chosen = self.chosen, []
        img, self.attach = self.attach, None
        self.attach_lbl.hide()
        self.input.clear()
        self.sugg.hide()

        quote, self.reply_to = self.reply_to, ""
        self.reply_box.hide()

        def work():
            from .server import _expand_chat
            data, mime = (img or (None, None))
            full = _expand_chat(text, mentions)
            shown = text
            if quote:   # 답글: 퍼플루에게는 어느 부분에 대한 말인지, 말풍선에는 짧게
                full = f"(네 앞 대답 중 이 부분에 대한 말이야: \"{quote[:600]}\")\n{full}"
                shown = f"↪ {quote[:60]}{'…' if len(quote) > 60 else ''}\n{text}"
            self.brain.send_text(full, data, mime or "image/jpeg", shown=shown)
        threading.Thread(target=work, daemon=True).start()

    def _attach(self):
        path, _ = QFileDialog.getOpenFileName(self, "그림 고르기", "", "그림 (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if not path:
            return
        from PIL import Image
        import io
        im = Image.open(path).convert("RGB")
        im.thumbnail((1600, 1600))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        self.attach = (buf.getvalue(), "image/jpeg")
        self.attach_lbl.setText(f"📎 {path.split('/')[-1]}  (보내면 같이 가요)")
        self.attach_lbl.show()

    def eventFilter(self, obj, e):
        t = e.type()
        if t == e.Type.MouseButtonRelease and isinstance(obj, QLabel) and obj.property("reply"):
            sel = obj.selectedText().strip()
            if sel:
                self._picked_text = sel
                P = pal()
                self.quote_btn.setStyleSheet(f"QPushButton {{ background:{self._cc}; color:{on_color(self._cc)}; border:none; border-radius:10px; padding:5px 12px; font-weight:600; }}")
                self.quote_btn.adjustSize()
                pos = self.mapFromGlobal(e.globalPosition().toPoint())
                x = max(6, min(self.width() - self.quote_btn.width() - 6, pos.x() - self.quote_btn.width() // 2))
                self.quote_btn.move(x, max(6, pos.y() - self.quote_btn.height() - 12))
                self.quote_btn.show()
                self.quote_btn.raise_()
            else:
                self.quote_btn.hide()
            return False
        if t == e.Type.MouseButtonPress and self.quote_btn.isVisible() and obj is not self.quote_btn:
            QTimer.singleShot(150, self.quote_btn.hide)
        if t == e.Type.MouseMove and obj is self.sugg.viewport():   # 마우스가 있는 줄이 골라지게
            it = self.sugg.itemAt(e.position().toPoint())
            if it is not None and it is not self.sugg.currentItem():
                self.sugg.setCurrentItem(it)
            return False
        # @·/ 목록이 떠 있으면 화살표·엔터는 어디로 가든 목록이 먼저 받는다 (한글 입력 중에도)
        if t in (e.Type.KeyPress, e.Type.ShortcutOverride) and self.sugg.isVisible() and self.isActiveWindow():
            k = e.key()
            if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab, Qt.Key_Escape):
                if t == e.Type.ShortcutOverride:
                    e.accept()
                    return True
                if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
                    step = {Qt.Key_Down: 1, Qt.Key_Up: -1, Qt.Key_PageDown: 5, Qt.Key_PageUp: -5}[k]
                    r = self.sugg.currentRow() + step
                    self.sugg.setCurrentRow(max(0, min(self.sugg.count() - 1, r)))
                    self.sugg.scrollToItem(self.sugg.currentItem())
                elif k == Qt.Key_Escape:
                    self.sugg.hide()
                elif e.modifiers() & Qt.ShiftModifier and k in (Qt.Key_Return, Qt.Key_Enter):
                    self.sugg.hide()
                    self.input.insertPlainText("\n")
                else:
                    self._pick(max(0, self.sugg.currentRow()))
                return True
        if obj is self.input and t == e.Type.KeyPress:
            k = e.key()
            if self.sugg.isVisible() and k in (Qt.Key_Down, Qt.Key_Up):
                r = self.sugg.currentRow() + (1 if k == Qt.Key_Down else -1)
                self.sugg.setCurrentRow(max(0, min(self.sugg.count() - 1, r)))
                self.sugg.scrollToItem(self.sugg.currentItem())   # 고른 줄이 보이게 따라 내려가기
                return True
            if self.sugg.isVisible() and k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                self._pick(max(0, self.sugg.currentRow()))
                return True
            if k == Qt.Key_Escape:
                self.sugg.hide()
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                if e.modifiers() & Qt.ShiftModifier:   # 쉬프트+엔터 = 줄바꿈
                    self.input.insertPlainText("\n")
                else:
                    self._send()
                return True
        return super().eventFilter(obj, e)

    # ---------------- /스킬 · @멘션 ----------------
    def _text_changed(self):
        lines = max(1, min(6, self.input.document().blockCount() + self.input.toPlainText().count("\n") // 2))
        self.input.setFixedHeight(26 + 20 * lines)
        cur = self.input.textCursor()
        before = self.input.toPlainText()[:cur.position()]
        self._items = []
        sharp = before.rfind("#")
        if before.startswith("/") and " " not in before:
            q = before[1:].lower()
            self._kind = "/"
            self._items = [{"label": n, "sub": d} for n, d in COMMANDS
                           if n.startswith(q) or q in d.lower() or CMD_ALIAS.get(q, "") == n]
        elif sharp >= 0 and " " not in before[sharp:] and (sharp == 0 or before[sharp - 1] in " \n"):
            q = before[sharp + 1:].lower()
            rows = getattr(self, "_skills", None)
            if rows is None:   # 처음 한 번 뒤에서 불러오고, 오면 다시 보여 준다
                self._skills = []
                self._ask_skills()
                rows = []
            self._kind = "#"
            self._items = [{"label": r["name"], "sub": r.get("description") or "스킬"} for r in rows
                           if r.get("enabled", True) and q in r["name"].lower()]
        else:
            at = before.rfind("@")
            if at >= 0 and " " not in before[at:] and (at == 0 or before[at - 1] in " \n"):
                q = before[at + 1:].lower()
                self._kind = "@"
                at_key = (at, len(self.input.toPlainText()[:at]))   # 이번 @ 하나당 목록은 한 번만 새로 받는다
                if getattr(self, "_asked_at", None) != at_key:
                    self._asked_at = at_key
                    self._ask_mentions()
                self._items = [{"label": m["label"], "sub": m["kind"], "m": m} for m in self.mentions
                               if q in m["label"].lower()][:30]
        labels = [f"{self._kind}{it['label']}" for it in self._items]
        old = [self.sugg.item(i).text() for i in range(self.sugg.count())]
        if labels != old:   # 목록이 그대로면 다시 만들지 않는다 (고른 줄·스크롤이 위로 튀지 않게)
            keep = self.sugg.currentItem().text() if self.sugg.currentItem() else None
            bar = self.sugg.verticalScrollBar().value()
            self.sugg.clear()
            for text, it in zip(labels, self._items):
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, it["sub"])
                self.sugg.addItem(item)
            row = labels.index(keep) if keep in labels else 0
            self.sugg.setCurrentRow(row)
            if keep in labels:
                self.sugg.verticalScrollBar().setValue(bar)
        self.sugg.setVisible(bool(self._items))

    def _run_command(self, name: str):
        s = config.settings()
        if name == "settings":
            self.open_settings()
        elif name == "new":
            self._new_chat()
        elif name == "rename":
            self._rename_conv()
        elif name == "delete":
            self._delete_conv()
        elif name == "chats":
            self._conv_menu()
        elif name == "model":
            other = next(k for k in MODELS if k != s.get("live_model"))
            config.save_settings(live_model=other)
            self.turn["results"].append(f"모델을 {MODELS[other]}(으)로 바꿨어요")
            self._schedule()
        elif name == "mini":
            self._toggle_mini()
        elif name == "web":
            self._show_web(self.top.currentIndex() == 0)
        elif name == "pin":
            config.save_settings(pc_chat_pinned=not s.get("pc_chat_pinned"))
        elif name == "top":
            config.save_settings(pc_chat_on_top=not s.get("pc_chat_on_top", True))
        elif name == "image":
            self._attach()
        elif name == "skills":
            self.input.setPlainText("#")
            self.input.moveCursor(self.input.textCursor().MoveOperation.End)
        elif name == "close":
            self._close_clicked()
        self.input.setFocus()

    def _ask_skills(self):
        def work():
            try:
                from .tools.skills import list_skills
                rows = list_skills()["skills"]
            except Exception:
                rows = []
            self._skills_ready.emit(rows)
        threading.Thread(target=work, daemon=True).start()

    def _got_skills(self, rows):
        self._skills = rows
        self._text_changed()

    def _ask_mentions(self):
        if getattr(self, "_asking", False):
            return
        self._asking = True

        def work():
            from .server import _mention_list
            try:
                rows = _mention_list()
            except Exception:
                rows = []
            self._mentions_ready.emit(rows)
        threading.Thread(target=work, daemon=True).start()

    def _got_mentions(self, rows):
        self._asking = False
        self.mentions = rows
        self._text_changed()

    def _pick(self, i: int):
        if not (0 <= i < len(getattr(self, "_items", []))):
            return
        it = self._items[i]
        text = self.input.toPlainText()
        pos = self.input.textCursor().position()
        before, after = text[:pos], text[pos:]
        if self._kind == "/":   # 명령은 고르면 바로 실행
            self.input.clear()
            self.sugg.hide()
            self._run_command(it["label"])
            return
        if self._kind == "#":
            new_before = before[:before.rfind("#")] + f"#{it['label']} "
        else:
            new_before = before[:before.rfind("@")] + f"@{it['label']} "
            self.chosen.append(it["m"])
        self.input.setPlainText(new_before + after)
        c = self.input.textCursor()
        c.setPosition(len(new_before))
        self.input.setTextCursor(c)
        self.sugg.hide()

    # ---------------- 창: 열기·고정·자리 차지·숨기기 ----------------
    def _place(self):
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(440, min(760, area.height() - 40))
        self.move(area.right() - self.width() - 16, area.bottom() - self.height() - 30)
        self._placed = True

    def open(self, activate: bool = True):
        if not self._placed:
            self._place()
        if activate:
            self.show()
            self.raise_()
            self.activateWindow()
            self.input.setFocus()
        elif not self.isVisible():
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            self.show()
            self.setAttribute(Qt.WA_ShowWithoutActivating, False)

    def _close_clicked(self):
        if config.settings().get("pc_chat_pinned"):
            config.save_settings(pc_chat_pinned=False)
        self.hide()

    def auto_hide(self):
        if config.settings().get("pc_chat_pinned") or self.isActiveWindow() or self.input.toPlainText().strip():
            return
        self.hide()

    def apply_pin(self):
        s = config.settings()
        self.btn_pin.active = bool(s.get("pc_chat_pinned"))
        self.btn_pin.update()
        if not s.get("pc_chat_pinned"):
            self._release_space()
            return
        self.open(activate=False)
        if s.get("pc_chat_dock", True):
            self._reserve_space()
        else:
            self._release_space()
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.setGeometry(area.right() - 448, area.top() + 10, 440, area.height() - 20)
            self._placed = True

    def _bar(self):
        d = _APPBARDATA()
        d.cbSize = ctypes.sizeof(d)
        d.hWnd = int(self.winId())
        return d

    def _reserve_space(self):
        shell = ctypes.windll.shell32
        scr = QGuiApplication.primaryScreen()
        dpr = scr.devicePixelRatio()
        full = scr.geometry()
        width_px = int(440 * dpr)
        d = self._bar()
        if not self._appbar:
            d.uCallbackMessage = 0x0400 + 77
            shell.SHAppBarMessage(0, ctypes.byref(d))           # ABM_NEW
            self._appbar = True
        d.uEdge = 2                                              # 오른쪽
        d.rc.top, d.rc.bottom = int(full.top() * dpr), int((full.bottom() + 1) * dpr)
        d.rc.right = int((full.right() + 1) * dpr)
        d.rc.left = d.rc.right - width_px
        shell.SHAppBarMessage(2, ctypes.byref(d))               # ABM_QUERYPOS
        d.rc.left = d.rc.right - width_px
        shell.SHAppBarMessage(3, ctypes.byref(d))               # ABM_SETPOS
        avail = scr.availableGeometry()
        self.setGeometry(int(d.rc.left / dpr), avail.top(), int(width_px / dpr), avail.height())
        self._placed = True

    def _release_space(self):
        if self._appbar:
            ctypes.windll.shell32.SHAppBarMessage(1, ctypes.byref(self._bar()))   # ABM_REMOVE
            self._appbar = False

    def hideEvent(self, e):
        self._release_space()
        super().hideEvent(e)

    def closeEvent(self, e):
        self._release_space()
        super().closeEvent(e)
