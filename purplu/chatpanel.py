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
                               QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QStyle,
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
            glow.setColorAt(0, QColor(168, 85, 247, 150))
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
        if option.state & QStyle.State_Selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(P["bubble"]))
            p.drawRoundedRect(QRectF(r).adjusted(2, 1, -2, -1), 8, 8)
        kind = index.data(Qt.UserRole) or ""
        f = QFont(option.font)
        f.setPointSizeF(8.5)
        p.setFont(f)
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
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.face = FaceView()
        self.face.pressed.connect(self._talk_start)
        self.face.released.connect(self._talk_end)
        lay.addWidget(self.face, 34)

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
        head.addWidget(self.title)
        head.addSpacing(6)
        head.addWidget(self.conv, 0)
        head.addWidget(self.status)
        head.addStretch(1)
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
        for b in (btn_new, self.btn_mini, self.btn_pin, btn_set):
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
        self.sugg.itemEntered.connect(lambda it: self.sugg.setCurrentItem(it))   # 마우스를 올리면 그게 골라짐
        bl.addWidget(self.sugg)
        self.attach_lbl = QLabel()
        self.attach_lbl.hide()
        bl.addWidget(self.attach_lbl)

        self.glow = GlowBox()
        gl = QVBoxLayout(self.glow)
        gl.setContentsMargins(14, 10, 12, 6)
        self.input = QPlainTextEdit()
        self.input.setObjectName("input")
        self.input.setPlaceholderText("퍼플루에게 물어보기  ( / 스킬 · @ 멘션 )")
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
        for b in (b_img, self.b_mic, self.b_send):
            b.setFixedSize(36, 36)
        b_img.setObjectName("icon")
        self.b_mic.setObjectName("icon")
        tools.addWidget(b_img)
        tools.addWidget(self.model)
        tools.addStretch(1)
        tools.addWidget(self.b_mic)
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
        self.face.setVisible(s.get("pc_layout", "stack") != "full" and not self.mini)
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

    def _steps(self, steps: list, open_=False):
        s = config.settings()
        if not steps or not s.get("show_steps", True):
            return None
        P = pal()
        lines = []
        for st in steps:
            mark = "●" if not st.get("done", True) else ("✓" if st.get("ok") else "✗")
            col = "#3B82F6" if not st.get("done", True) else ("#16A34A" if st.get("ok") else "#DC2626")
            line = f"<span style='color:{col}'>{mark}</span> {html.escape(st.get('call') or st.get('label', ''))}"
            if s.get("show_commands", True):
                for c in (st.get("cmds") or [])[-4:]:
                    line += f"<br><span style='color:#B45309'>&nbsp;&nbsp;$ {html.escape(c)}</span>"
            if st.get("done", True) and st.get("result"):
                line += f"<br><span style='color:{P['dim']}'>&nbsp;&nbsp;└ {html.escape(st['result'])}</span>"
            lines.append(line)
        box = QPushButton(f"⚙ 실행 {len(steps)}개  ▸")
        box.setStyleSheet(f"text-align:left; background:{P['card']}; border:1px solid {P['line']}; border-radius:10px; padding:6px 10px;")
        detail = self._text("<br>".join(lines), "9pt")
        detail.setStyleSheet(f"font-family:Consolas; font-size:9pt; background:{P['card']}; border-radius:8px; padding:6px 10px;")
        detail.setVisible(open_)
        box.clicked.connect(lambda: (detail.setVisible(not detail.isVisible()),
                                     box.setText(f"⚙ 실행 {len(steps)}개  {'▾' if detail.isVisible() else '▸'}")))
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        v.addWidget(box)
        v.addWidget(detail)
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
                add(self._steps([{**st, "done": True} for st in m.get("steps") or []]))
                if m.get("text") and m["text"] != "(실행만 했어요)":
                    add(self._text(html.escape(m["text"], quote=False).replace("\n", "<br>")))
        for i, t in enumerate(([] if self.mini else self.past[-10:]) + [self.turn]):
            live = t is self.turn
            if t["heard"]:
                add(self._bubble(t["heard"], t.get("img", "")))
            if live and self.state in ("thinking", "acting") and not t["reply"]:
                add(self._text(f"<span style='color:{P['dim']}'>💭 생각 중…</span>"))
            add(self._steps(t["steps"], live and self.state in ("thinking", "acting")))
            if t["reply"]:
                add(self._text(html.escape(t["reply"], quote=False).replace("\n", "<br>")))
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
        m.addSeparator()
        for c in getattr(self, "convs", [])[:15]:
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

    def _new_chat(self):
        self._hist_gen = getattr(self, "_hist_gen", 0) + 1   # 불러오던 옛 기록은 무시
        self.brain.new_conversation()
        self.history, self.past, self.turn = [], [], self._new_turn()
        self._show_title("새 대화")
        QTimer.singleShot(1500, self._load_convs)
        self._render()
        self.input.setFocus()

    def _toggle_mini(self):
        """작은 모드: 얼굴을 숨기고 마지막 대화만, 창도 작게."""
        self.mini = not self.mini
        self.btn_mini.active = self.mini
        self.btn_mini.update()
        if self.mini:
            self._big_geom = self.geometry()
            self.face.hide()
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.setGeometry(area.right() - 400, area.bottom() - 290, 380, 270)
        else:
            self.face.setVisible(config.settings().get("pc_layout", "stack") != "full")
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
        mentions, self.chosen = self.chosen, []
        img, self.attach = self.attach, None
        self.attach_lbl.hide()
        self.input.clear()
        self.sugg.hide()

        def work():
            from .server import _expand_chat
            data, mime = (img or (None, None))
            self.brain.send_text(_expand_chat(text, mentions), data, mime or "image/jpeg")
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
            if k in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
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
        if before.startswith("/") and " " not in before:
            q = before[1:].lower()
            rows = getattr(self, "_skills", None)
            if rows is None:   # 처음 한 번 뒤에서 불러오고, 오면 다시 보여 준다
                self._skills = []
                self._ask_skills()
                rows = []
            self._kind = "/"
            self._items = [{"label": r["name"], "sub": r.get("description") or "스킬"} for r in rows
                           if r.get("enabled", True) and q in r["name"].lower()]
        else:
            at = before.rfind("@")
            if at >= 0 and " " not in before[at:] and (at == 0 or before[at - 1] in " \n"):
                q = before[at + 1:].lower()
                self._kind = "@"
                if q == "" or not self.mentions:
                    self._ask_mentions()
                self._items = [{"label": m["label"], "sub": m["kind"], "m": m} for m in self.mentions
                               if q in m["label"].lower()][:30]
        self.sugg.clear()
        for it in self._items:
            item = QListWidgetItem(f"{'/' if self._kind == '/' else '@'}{it['label']}")
            item.setData(Qt.UserRole, it["sub"])
            self.sugg.addItem(item)
        self.sugg.setVisible(bool(self._items))
        if self._items:
            self.sugg.setCurrentRow(0)

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
        if self._kind == "/":
            new_before = f"/{it['label']} "
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
