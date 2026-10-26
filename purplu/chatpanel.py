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

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QConicalGradient, QCursor, QFont, QFontMetrics, QGuiApplication, QLinearGradient, QPainter,
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
EXAMPLES = ["30분 뒤에 스트레칭하라고 알려줘", "다운로드 폴더에서 어제 받은 파일 찾아줘", "지금 컴퓨터 배터리랑 메모리 어때?"]   # 새 대화 예시 3개
# '/' 를 치면 뜨는 명령 (이름, 설명). 한글로 쳐도 설명에서 찾아진다
COMMANDS = [
    ("settings", "설정 열기"),
    ("new", "새 대화 시작"),
    ("rename", "이 대화 이름 바꾸기"),
    ("delete", "이 대화 지우기"),
    ("chats", "다른 대화로 바꾸기"),
    ("web", "위쪽을 퍼플루 ↔ 퍼플루 브라우저로"),
    ("term", "위쪽을 퍼플루 ↔ 터미널로"),
    ("hide", "위 칸(퍼플루·브라우저·터미널) 숨기기 / 보이기"),
    ("model", "모델 · 노력 정도 고르기"),
    ("temp", "임시 대화 (저장 안 됨) 시작 / 끝내기"),
    ("mini", "작게: 퍼플루만 보기 (꾹 눌러 말하기) / 크게"),
    ("pin", "오른쪽에 고정 / 풀기"),
    ("top", "언제나 맨 위로 켜기/끄기"),
    ("image", "그림 붙이기"),
    ("skills", "스킬 목록 (# 으로도 불러요)"),
    ("mcp", "MCP 서버 보기 · 켜고 끄기 · 예시 추가"),
    ("custom", "퍼플루 꾸미기 (눈 · 모자 · 더듬이 · 소품)"),
    ("close", "대화창 닫기"),
]
CMD_ALIAS = {"costom": "custom", "customize": "custom", "꾸미기": "custom", "terminal": "term", "터미널": "term", "browser": "web", "브라우저": "web", "setting": "settings", "설정": "settings", "새대화": "new", "clear": "new"}

def model_slug(name: str) -> str:
    """'Gemini 3.8 Flash' → 'gemini3.8flash' (/model-gemini3.8 처럼 앞부분만 쳐도 된다)."""
    return "".join(name.lower().split())


def quick_models() -> list[dict]:
    """/model- 로 바로 바꿀 수 있는 모델 (지금 쓸 수 있는 것만). 칠 때마다 키 창고를 열지 않게 10초 기억."""
    import time
    now = time.time()
    if _quick_cache[1] is not None and now - _quick_cache[0] < 10:
        return _quick_cache[1]
    from .model_ui import catalog
    rows = []
    for g in catalog():
        for it in g["items"]:
            if it["ready"]:
                rows.append({"slug": model_slug(it["name"]), "mid": it["mid"], "name": it["name"], "group": g["name"],
                             "kind": {"cli": "터미널", "local": "이 PC"}.get(it["kind"], "")})
    _quick_cache[:] = [now, rows]
    return rows


def find_model(q: str):
    """짧은 이름으로 모델 찾기: 똑같은 것 → 앞부분이 같은 것 → 들어 있는 것."""
    q = model_slug(q)
    rows = quick_models()
    for test in (lambda r: r["slug"] == q, lambda r: r["slug"].startswith(q), lambda r: q in r["slug"]):
        hit = next((r for r in rows if test(r)), None)
        if hit:
            return hit
    return None


_quick_cache = [0.0, None]

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
    """입력칸 둘레 빛. '내 색'(기본)이면 고른 색에서 이웃 색을 만들어 흐르게."""
    s = config.settings()
    if s.get("chat_glow") in GLOWS:
        return GLOWS[s["chat_glow"]]
    base = QColor(s.get("chat_color") or s.get("color") or "#3B82F6")
    h, sat, v, _a = base.getHsv()
    near = lambda dh, dv=0: QColor.fromHsv((h + dh) % 360, sat, max(0, min(255, v + dv))).name()   # noqa: E731
    return [base.name(), near(28, 10), base.lighter(135).name(), near(-28, -10)]


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
        """꾹 누르면 말하기. 작게 보기에선 누른 채 끌면 창 옮기기 (그땐 말하기를 시작하지 않는다)."""
        if e.button() != Qt.LeftButton:
            return
        win = self.window()
        if getattr(win, "mini", False) and not config.settings().get("pc_chat_pinned"):
            self._press_at = e.globalPosition().toPoint()
            self._talk_wait = QTimer(self, singleShot=True, timeout=self._start_talk)
            self._talk_wait.start(220)   # 잠깐 기다려 보고 안 움직이면 말하기
            return
        self._start_talk()

    def _start_talk(self):
        self._press_at = None
        self._talking = True
        self.pressed.emit()

    def mouseMoveEvent(self, e):
        at = getattr(self, "_press_at", None)
        if at is not None and (e.globalPosition().toPoint() - at).manhattanLength() > 8:
            self._press_at = None
            self._talk_wait.stop()
            if self.window().windowHandle():
                self.window().windowHandle().startSystemMove()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if getattr(self, "_press_at", None) is not None:   # 짧게 눌렀다 뗌: 말하기를 짧게
            self._talk_wait.stop()
            self._start_talk()
        if getattr(self, "_talking", False):
            self._talking = False
            self.released.emit()

    def paintEvent(self, _):
        from .face import draw_face, options   # 눈·모자·더듬이·소품까지 (꾸미기: /custom)
        p = QPainter(self)
        opts = options(extra="sunglasses") if getattr(self, "temp", False) else None   # 임시 대화: 선글라스
        draw_face(p, self.width(), self.height(), self, opts, bg=pal()["face_bg"])
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


# ------------------------------------------------------------------ 메시지 칸 (첫 화면 빛)
class GlowBody(QFrame):
    """대화 칸 전체. 새 대화 첫 화면이면 바닥에서 옆으로 퍼지는 빛을 그린다 (입력칸 뒤·둘레까지 번짐).
    색은 내 색과, 내 색에서 색상만 살짝 돌린 두 색 → 서로 어울리게 섞인다. 아주 천천히 흔들리고 숨쉰다."""

    def __init__(self):
        super().__init__()
        self.glow = False
        self.base = QColor("#8B5CF6")
        self.dark = False
        self.anchor = None   # 입력칸: 빛의 가운데를 입력칸 윗부분에 둔다 (입력칸 위·둘레로 번지게)
        self._t0 = time.monotonic()
        self._timer = QTimer(self, timeout=self.update)

    def set_glow(self, on: bool, color: str, dark: bool, mono: bool = False, strength: float = 1.0):
        self.glow, self.base, self.dark = on, QColor(color), dark
        self.mono, self.level = mono, strength
        if on and self.isVisible():
            self._timer.start(50)
        else:
            self._timer.stop()
        self.update()

    def showEvent(self, e):
        if self.glow:
            self._timer.start(50)
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _turn_(self, c, dh, ds=1.0, dv=1.0):
        return QColor(c) if getattr(self, "mono", False) else self._turn(c, dh, ds, dv)

    @staticmethod
    def _turn(c: QColor, dh: int, ds: float = 1.0, dv: float = 1.0) -> QColor:
        h, sat, v, _ = c.getHsv()
        return QColor.fromHsv((max(h, 0) + dh) % 360, max(0, min(255, int(sat * ds))), max(0, min(255, int(v * dv))))

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.glow:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        t = time.monotonic() - self._t0
        b = self.base
        strength = (1.0 if self.dark else 0.8) * getattr(self, "level", 1.0)
        if getattr(self, "mono", False):   # 임시 대화: 색 없이 부드러운 검은빛 (어두운 테마면 은은한 회색빛)
            b = QColor("#A1A1AA") if self.dark else QColor("#27272A")
            strength *= 0.42
        breathe = 0.92 + 0.08 * math.sin(t * 0.9)
        # (가로 위치, 색, 가로 반지름, 세로 반지름, 진하기) — 가운데 넓은 빛 + 양옆 어울리는 색 둘
        # (가로, 위로 올린 정도 px, 색, 가로 반지름, 세로 반지름, 진하기)
        # 아래(입력칸 근처)는 내 색 → 위로 갈수록 색상이 조금씩 돌아간 색으로 바뀐다
        blobs = [
            (0.50 + 0.03 * math.sin(t * 0.35), 0, b, 0.85, 300, 150),
            (0.18 + 0.05 * math.sin(t * 0.27 + 1.3), 0, self._turn_(b, -38, 1.0, 1.05), 0.55, 260, 115),
            (0.82 + 0.05 * math.sin(t * 0.31 + 2.1), 0, self._turn_(b, 42, 0.9, 1.08), 0.55, 260, 115),
            (0.45 + 0.06 * math.sin(t * 0.25 + 0.4), 170, self._turn_(b, 55, 0.95, 1.1), 0.75, 280, 105),   # 중간: 색이 바뀌기 시작
            (0.55 + 0.06 * math.sin(t * 0.2 + 2.0), 330, self._turn_(b, 110, 0.8, 1.15), 0.70, 260, 75),   # 위: 더 바뀐 색, 옅게
            (0.50 + 0.08 * math.sin(t * 0.22 + 0.6), 0, self._turn_(b, 0, 0.45, 1.25), 1.05, 160, 80),   # 밝은 띠
        ]
        a_ = self.anchor
        cy = (a_.geometry().top() + a_.height() * 0.5) if a_ is not None and a_.isVisible() else H
        p.setPen(Qt.NoPen)
        for fx, up, col, rx, ry, alpha in blobs:
            a = alpha * strength * breathe
            p.save()
            p.translate(W * fx, cy - up)
            p.scale(W * rx, ry)   # 원을 납작하게 → 옆으로 넓게 퍼진다 (세로는 화면 크기와 상관없이 일정)
            g = QRadialGradient(0, 0, 1)
            for stop, k in ((0, 1), (0.3, 0.62), (0.6, 0.24), (0.82, 0.07), (1, 0)):
                g.setColorAt(stop, QColor(col.red(), col.green(), col.blue(), int(a * k)))
            p.setBrush(g)
            p.drawEllipse(QPointF(0, 0), 1, 1)
            p.restore()
        p.end()


# ------------------------------------------------------------------ 노력 정도 막대
class EffortBar(QWidget):
    """낮음 · 중간 · 높음 · 최대. 고른 곳까지 초록 → 노랑 → 빨강으로 차오르고, 최대는 보라색까지."""
    changed = Signal(str)

    def __init__(self, efforts, current):
        super().__init__()
        self.efforts, self.cur = efforts, current
        self.setFixedHeight(46)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(220)

    def _x(self, i):
        pad = 26
        return pad + (self.width() - pad * 2) * i / (len(self.efforts) - 1)

    def _pick(self, x):
        i = min(range(len(self.efforts)), key=lambda k: abs(self._x(k) - x))
        if self.efforts[i][0] != self.cur:
            self.cur = self.efforts[i][0]
            self.changed.emit(self.cur)
            self.update()

    def mousePressEvent(self, e):
        self._pick(e.position().x())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._pick(e.position().x())

    SOFT = ["#9BE3B4", "#FBE3A1", "#F8B4B4", "#D9C2F7"]     # 낮음 · 중간 · 높음 · 최대 (파스텔)
    INK = ["#2F7D4F", "#9A6B12", "#B4413F", "#7C4DBE"]      # 고른 글자 색 (같은 색의 진한 쪽)

    def _anim_to(self, x):
        """손잡이가 톡 튀지 않고 부드럽게 미끄러지게."""
        from PySide6.QtCore import QVariantAnimation, QEasingCurve
        start = getattr(self, "_hx", None)
        if start is None:
            self._hx = x
            return
        a = QVariantAnimation(self, startValue=float(start), endValue=float(x), duration=220)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.valueChanged.connect(lambda v: (setattr(self, "_hx", float(v)), self.update()))
        a.start()
        self._a = a

    def paintEvent(self, _):
        """둥글고 도톰한 줄 + 하얀 손잡이 (그림자만). 색은 파스텔로 은은하게."""
        P = pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        idx = next((i for i, (k, _) in enumerate(self.efforts) if k == self.cur), 1)
        y, th = 15, 12
        x0, x1 = self._x(0), self._x(len(self.efforts) - 1)
        target = self._x(idx)
        if getattr(self, "_hx", None) is None or getattr(self, "_last", None) != idx:
            self._last = idx
            self._anim_to(target)
        hx = getattr(self, "_hx", target)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ECEAF3") if light() else QColor(P["line"]))
        p.drawRoundedRect(QRectF(x0 - th / 2, y - th / 2, x1 - x0 + th, th), th / 2, th / 2)   # 바탕
        g = QLinearGradient(x0, 0, x1, 0)
        for k, col in enumerate(self.SOFT[:len(self.efforts)]):
            g.setColorAt(k / (len(self.efforts) - 1), QColor(col))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(x0 - th / 2, y - th / 2, hx - x0 + th, th), th / 2, th / 2)   # 찬 부분
        for r, a in ((12, 14), (10, 22)):                                                      # 부드러운 그림자
            p.setBrush(QColor(0, 0, 0, a))
            p.drawEllipse(QPointF(hx, y + 1.5), r, r)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(hx, y), 9, 9)
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        for i, (k, name) in enumerate(self.efforts):
            p.setPen(QColor(self.INK[i]) if i == idx else QColor(P["dim"]))
            p.drawText(QRectF(self._x(i) - 30, y + 13, 60, 18), Qt.AlignCenter, name)
        p.end()


class Chevron(QWidget):
    """묶음 머리줄의 작은 꺾쇠: 접히면 ›, 펴지면 ⌄ — 글자 대신 둥근 선으로 그리고, 바뀔 때 살짝 돈다."""

    def __init__(self, color, down=False):
        super().__init__()
        self.setFixedSize(14, 14)
        self.color = QColor(color)
        self.angle = 90.0 if down else 0.0
        self.anim = None

    def turn(self, down):
        from PySide6.QtCore import QEasingCurve, QVariantAnimation
        self.anim = QVariantAnimation(self, startValue=self.angle, endValue=90.0 if down else 0.0, duration=160)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._set)
        self.anim.start()

    def _set(self, a):
        self.angle = float(a)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self.color, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.translate(7, 7)
        p.rotate(self.angle)
        p.drawPolyline([QPointF(-1.6, -3.6), QPointF(2.0, 0), QPointF(-1.6, 3.6)])


class ModelPopup(QFrame):
    """모델 이름 단추를 누르면 뜨는 작은 창 (Claude 의 모델 고르기처럼).
    회사별 묶음 (● Gemini · GPT · Claude · Ollama · 그외, 눌러서 접기/펴기) → 노력 › → (라이브면) 말 모델 → 모델 관리 ›.
    '노력 ›' 은 같은 창 안에서 그 장으로 넘어간다 (〈 로 돌아오기)."""

    def __init__(self, owner):
        super().__init__(owner, Qt.Popup)
        self.owner = owner
        self.setObjectName("modelpop")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(6, 6, 6, 6)
        self.v.setSpacing(0)
        self.page = "main"
        self.setFixedWidth(300)
        self.build()

    # ---- 줄 ----
    def _clear(self):
        while self.v.count():
            it = self.v.takeAt(0)
            w = it.widget()
            if w:
                w.hide()               # 바로 숨겨야 새 장과 겹쳐 보이지 않는다
                w.setParent(None)
                w.deleteLater()

    def _sep(self):
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{pal()['line']}; margin:4px 8px;")
        self.v.addWidget(line)

    def _label(self, text, small=False):
        lab = QLabel(text)   # 짧은 한 줄 (줄바꿈 칸은 창 높이를 엉뚱하게 늘려서 안 씀)
        lab.setStyleSheet(f"color:{pal()['dim']}; font-size:{'8.5pt' if small else '9pt'}; padding:6px 12px 4px; background:transparent;")
        self.v.addWidget(lab)

    def _row(self, left, right="", fn=None, on=False, badge="", color=None, indent=False, sub="", into=None):
        P = pal()
        b = QPushButton()
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(34 if indent else 38)
        h = QHBoxLayout(b)
        h.setContentsMargins(34 if indent else 12, 0, 12, 0)
        h.setSpacing(6)
        name = QLabel(left)
        name.setStyleSheet(f"color:{color or P['text']}; font-size:{'10pt' if indent else '10.5pt'}; background:transparent;")
        h.addWidget(name)
        if sub:   # 터미널 · 이 PC 같은 작은 꼬리표
            sb = QLabel(sub)
            sb.setStyleSheet(f"color:{P['dim']}; background:{P['card']}; border-radius:5px; padding:0 6px; font-size:8pt;")
            sb.setFixedHeight(18)
            h.addWidget(sb, 0, Qt.AlignVCenter)
        if badge:
            bd = QLabel(badge)
            warn = False
            bd.setStyleSheet(f"background:{'#FDE68A' if warn else P['card']}; color:{'#92400E' if warn else P['dim']};"
                             f" border-radius:6px; padding:1px 6px; font-size:8.5pt;")
            h.addWidget(bd)
        h.addStretch(1)
        r = QLabel("✓" if on else right)
        r.setStyleSheet(f"color:{self.owner._cc if on else P['dim']}; font-size:{'12pt' if on else '10pt'};"
                        f" font-weight:{'800' if on else '400'}; background:transparent;")
        h.addWidget(r)
        b.setStyleSheet(f"QPushButton {{ background:transparent; border:none; border-radius:8px; text-align:left; }}"
                        f"QPushButton:hover {{ background:{P['card']}; }}")
        if fn:
            b.clicked.connect(fn)
        (into or self.v).addWidget(b)
        return b

    def build(self):
        from .textchat import EFFORTS, model_info
        self._clear()
        self._boxes = {}
        P = pal()
        self.setStyleSheet(f"QFrame#modelpop {{ background:{P['bg']}; border:1px solid {P['line']}; border-radius:14px; }}")
        s = config.settings()
        cur = s.get("text_model") or "gemini-3.8-flash"
        if self.page == "effort":
            self._row("〈  생각 강도", fn=lambda: self._go("main"))
            self._label("높을수록 깊게 생각하지만 더 느려요.", small=True)
            eff = s.get("effort") or "medium"
            bar = EffortBar(EFFORTS, eff)
            bar.changed.connect(lambda e, bar=bar, before=eff: self._pick_effort(e, bar, before))
            self.v.addWidget(bar)
            self.v.addSpacing(6)
        else:
            from .model_ui import catalog
            opened = self.owner.__dict__.setdefault("_model_groups_open", set())
            groups = catalog()
            if not opened:   # 처음엔 지금 고른 모델이 든 묶음만 펼친다
                opened.update(g["id"] for g in groups if any(it["mid"] == cur for it in g["items"]))
            for g in groups:
                is_open = g["id"] in opened
                has_cur = any(it["mid"] == cur for it in g["items"])
                head = self._group_row(g, is_open, has_cur)
                box = QWidget()
                box.setStyleSheet("background:transparent;")
                bl = QVBoxLayout(box)
                bl.setContentsMargins(0, 0, 0, 0)
                bl.setSpacing(0)
                if g["key"] and not g["has_key"]:
                    self._row(f"{g['name']} 키 넣기", "모델 관리 ›", fn=self._open_manage, indent=True, into=bl)
                elif g["id"] == "ollama" and not g["items"]:
                    self._row("깔린 모델이 없어요 (Ollama 를 켜 주세요)", "›", fn=self._open_manage, indent=True, into=bl)
                for it in g["items"]:
                    if it["kind"] == "api" and not it["ready"]:
                        continue   # 키가 없는 API 모델은 '키 넣기' 한 줄로
                    if it["kind"] == "cli" and not it["ready"]:
                        self._row(it["name"], "연동 ›", indent=True, sub="터미널", into=bl,
                                  fn=lambda _=False, a=it["agent"]: (self.close(), self.owner._cli_connect(a)))
                    else:
                        self._row(it["name"], fn=lambda _=False, m=it["mid"]: self._set(text_model=m), on=it["mid"] == cur,
                                  indent=True, sub={"cli": "터미널", "local": "이 PC"}.get(it["kind"], ""), into=bl)
                self.v.addWidget(box)     # 먼저 이 창 안에 넣고 나서 보이기/숨기기
                box.setVisible(is_open)   # (넣기 전에 보이면 따로 빈 창이 떠서, 모델 창이 닫혀 버린다)
                self._boxes[g["id"]] = (box, head)
            self._sep()
            if model_info(cur)[3]:   # 생각 강도: 생각하는 모델이면 바꿀 수 있고, 아니면 흐리게 안내만
                self._row("생각 강도", dict(EFFORTS).get(s.get("effort") or "medium", "") + "  ›", fn=lambda: self._go("effort"))
            else:
                self._row("생각 강도", "이 모델은 못 바꿔요", color=pal()["dim"]).setEnabled(False)
            if cur == "live":   # 라이브를 골랐을 때만: 말 모델
                self._label("라이브 모델")
                for mid, name in MODELS.items():
                    self._row(name.replace("⚡ ", "").replace("🧠 ", ""), fn=lambda _=False, m=mid: self._set(live_model=m),
                              on=mid == s.get("live_model"), indent=True)
            self._row("모델 관리", "›", fn=self._open_manage)
        self._fit()
        QTimer.singleShot(0, self._fit)   # 새 줄들이 자리 잡은 뒤 한 번 더 (같으면 아무것도 안 함)

    def _group_row(self, g, is_open, has_cur):
        """묶음 머리줄: Gemini ⌄ (누르면 접기/펴기). 접혀 있어도 지금 고른 모델이 들어 있으면 ✓."""
        P = pal()
        b = QPushButton()
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(36)
        h = QHBoxLayout(b)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(8)
        name = QLabel(g["name"])
        name.setStyleSheet(f"color:{P['text']}; font-weight:700; font-size:10.5pt; background:transparent;")
        h.addWidget(name)
        b.chev = Chevron(P["dim"], is_open)
        h.addWidget(b.chev, 0, Qt.AlignVCenter)
        h.addStretch(1)
        b.ck = QLabel("✓")
        b.ck.setStyleSheet(f"color:{self.owner._cc}; font-weight:800; background:transparent;")
        h.addWidget(b.ck)
        b.ck.setVisible(has_cur and not is_open)   # 넣은 다음에 (먼저 보이면 따로 창이 뜬다)
        b.has_cur = has_cur
        b.setStyleSheet(f"QPushButton {{ background:transparent; border:none; border-radius:8px; }}"
                        f"QPushButton:hover {{ background:{P['card']}; }}")
        b.clicked.connect(lambda: self._toggle_group(g["id"]))
        self.v.addWidget(b)
        return b

    def _toggle_group(self, gid):
        opened = self.owner.__dict__.setdefault("_model_groups_open", set())
        opened.symmetric_difference_update({gid})
        box, head = self._boxes[gid]
        is_open = gid in opened
        box.setVisible(is_open)
        head.ck.setVisible(head.has_cur and not is_open)
        self._fit()
        head.chev.turn(is_open)

    def _open_manage(self):
        self.close()
        self.owner.open_settings("모델")

    def _fit(self):
        """창 높이를 내용에 딱 맞게 (예전 장의 높이가 남아 빈 칸이 생기던 것)."""
        self.v.activate()
        h = max(60, self.v.totalSizeHint().height() if hasattr(self.v, "totalSizeHint") else self.v.sizeHint().height())
        g = self.owner.model.mapToGlobal(QPoint(0, 0))
        rect = QRect(g.x(), g.y() - h - 6, self.width(), h)
        if rect != self.geometry():
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.setGeometry(rect)
            self.setFixedHeight(h)

    def _pick_effort(self, e, bar, before):
        """최대로 올리면 경고 → '동의' 를 눌러야 바뀐다. 아니면 원래대로."""
        if e == "max" and before != "max":
            from .dialog import ask
            self.hide()   # 경고창이 이 작은 창 뒤에 숨지 않게
            if not ask(self.owner, "생각 강도를 최대로 할까요?",
                       "최대는 한도를 많이 써요. 더 깊게 생각하지만 느리고, 하루에 쓸 수 있는 양을 훨씬 빨리 써요.",
                       ok="동의", cancel="취소", danger=False):   # 취소: 막대를 원래 자리로
                self.show()
                self.build()
                return
        config.save_settings(effort=e)
        self.owner._paint_model_btn()
        if self.isHidden():
            self.show()
        self.build()

    def _place(self):
        self._fit()

    def _go(self, page):
        self.page = page
        self.build()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Left, Qt.Key_Backspace) and self.page != "main":
            return self._go("main")
        super().keyPressEvent(e)

    def _set(self, **kw):
        config.save_settings(**kw)
        self.owner._paint_model_btn()
        if "effort" in kw:   # 노력은 고르면 첫 장으로
            self.page = "main"
        self.build()


# ------------------------------------------------------------------ 대화 제목 ▾ 를 누르면 뜨는 창
class ConvPopup(QFrame):
    """새 대화 · 이름 바꾸기 · 지우기 + 최근 대화 목록 (모델 창과 같은 모양, 이모티콘 없이)."""

    def __init__(self, owner):
        super().__init__(owner, Qt.Popup)
        self.owner = owner
        self.setObjectName("convpop")
        P = pal()
        self.setStyleSheet(f"QFrame#convpop {{ background:{P['bg']}; border:1px solid {P['line']}; border-radius:14px; }}")
        self.setFixedWidth(320)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(0)
        cur = config.settings().get("current_conversation") or ""
        self._row(v, "새 대화", "", owner._new_chat)
        self._row(v, "이 대화 이름 바꾸기", "", owner._rename_conv)
        self._row(v, "이 대화 지우기", "", owner._delete_conv, color="#E5484D")
        line = QFrame(self)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{P['line']}; margin:4px 8px;")
        v.addWidget(line)
        lab = QLabel("최근 대화", self)
        lab.setStyleSheet(f"color:{P['dim']}; font-size:8.5pt; padding:6px 12px 4px; background:transparent;")
        v.addWidget(lab)
        convs = getattr(owner, "convs", None)
        shown = [c for c in (convs or [])
                 if c["id"] == cur or not (c.get("title") == "새 대화" and c.get("updated") == c.get("created"))][:30]
        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setStyleSheet(f"QScrollArea {{ background:transparent; border:none; }}"
                           f"QScrollBar:vertical {{ background:transparent; width:8px; margin:2px; }}"
                           f"QScrollBar::handle:vertical {{ background:{P['line']}; border-radius:3px; min-height:24px; }}"
                           f"QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}")
        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        lv = QVBoxLayout(inner)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        for c in shown:
            self._row(lv, c.get("title") or "새 대화", _ago(c.get("updated")),
                      lambda _=False, cid=c["id"]: owner._switch_conv(cid), on=c["id"] == cur)
        if not convs:
            self._row(lv, "대화를 불러오는 중…", "", None, color=P["dim"])
            owner._load_convs()
        area.setWidget(inner)
        area.setFixedHeight(min(len(shown) or 1, 9) * 36 + 2)
        v.addWidget(area)
        self.adjustSize()
        g = owner.conv.mapToGlobal(QPoint(0, owner.conv.height() + 4))
        scr = QGuiApplication.screenAt(g) or QGuiApplication.primaryScreen()
        a = scr.availableGeometry()
        self.move(min(max(g.x(), a.left() + 4), a.right() - self.width() - 4), min(g.y(), a.bottom() - self.height() - 4))

    def _row(self, lay, text, right, fn, on=False, color=None):
        P = pal()
        b = QPushButton(self)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(36)
        h = QHBoxLayout(b)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(8)
        name = QLabel(b)
        name.setText(QFontMetrics(name.font()).elidedText(text, Qt.ElideRight, 210))
        name.setStyleSheet(f"color:{color or (self.owner._cc if on else P['text'])}; font-size:10.5pt;"
                           f" font-weight:{'700' if on else '400'}; background:transparent;")
        h.addWidget(name)
        h.addStretch(1)
        if right:
            r = QLabel(right, b)
            r.setStyleSheet(f"color:{P['dim']}; font-size:8.5pt; background:transparent;")
            h.addWidget(r)
        b.setStyleSheet(f"QPushButton {{ background:{P['card'] if on else 'transparent'}; border:none; border-radius:8px; }}"
                        f"QPushButton:hover {{ background:{P['card']}; }}")
        if fn:
            b.clicked.connect(lambda: (self.close(), fn()))
        else:
            b.setEnabled(False)
        lay.addWidget(b)


def _ago(ms) -> str:
    """마지막 대화가 언제였는지 짧게: 방금 · 5분 · 3시간 · 어제 · 10/24."""
    import time as _t
    try:
        d = _t.time() - float(ms) / 1000
    except (TypeError, ValueError):
        return ""
    if d < 60:
        return "방금"
    if d < 3600:
        return f"{int(d // 60)}분 전"
    if d < 86400:
        return f"{int(d // 3600)}시간 전"
    if d < 172800:
        return "어제"
    return _t.strftime("%m/%d", _t.localtime(float(ms) / 1000))


# ------------------------------------------------------------------ [빨리 대답 Ctrl F] 같은 단추
class KeyButton(QFrame):
    """글자 옆에 단축키를 작은 키 모양으로 보여 주는 단추. primary = 진한 바탕."""
    clicked = Signal()

    def __init__(self, text, keys, primary=True):
        super().__init__()
        self.primary = primary
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("keybtn")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 6, 8 if keys else 14, 6)
        h.setSpacing(5)
        self.lbl = QLabel(text)
        h.addWidget(self.lbl)
        self.keys = []
        for k in keys:
            kl = QLabel(k)
            kl.setAlignment(Qt.AlignCenter)
            self.keys.append(kl)
            h.addWidget(kl)

    def paint_colors(self, P):
        dark = light()
        bg, fg = (("#18181B", "#FFFFFF") if dark else ("#F5F3FF", "#120B22")) if self.primary else ("transparent", P["text"])
        border = "none" if self.primary else f"1px solid {P['line']}"
        self.setStyleSheet(f"QFrame#keybtn {{ background:{bg}; border:{border}; border-radius:10px; }}"
                           f"QFrame#keybtn:hover {{ background:{'#3F3F46' if self.primary and dark else P['bubble']}; }}")
        self.lbl.setStyleSheet(f"color:{fg}; font-weight:700; font-size:10pt; background:transparent;")
        key_bg = "#3F3F46" if dark else "#2E1F4F"
        for kl in self.keys:
            kl.setStyleSheet(f"color:{fg}; background:{key_bg if self.primary else 'transparent'}; border:1px solid {'#52525B' if dark else '#4C3A75'};"
                             f" border-radius:5px; padding:0 5px; font-size:8.5pt; font-weight:600;")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


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
        accent = QColor(config.settings().get("chat_color") or config.settings().get("color") or "#3B82F6")
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
        elif k == "temp":     # 점선 말풍선 (임시 대화)
            pen2 = QPen(col, 1.6, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin)
            pen2.setDashPattern([2.2, 2.0])
            p.setPen(pen2)
            p.drawRoundedRect(QRectF(cx - 7.5, cy - 6.5, 15, 11), 4, 4)
            p.setPen(pen)
            p.drawLine(QPointF(cx - 3, cy + 4.5), QPointF(cx - 5, cy + 7.5))
        elif k == "top":
            p.drawRoundedRect(QRectF(cx - 8, cy - 7, 16, 14), 2.5, 2.5)
            p.drawLine(QPointF(cx - 8, cy - 1), QPointF(cx + 8, cy - 1))
            if self.active:
                p.setBrush(col)
                p.drawRoundedRect(QRectF(cx - 8, cy - 7, 16, 6), 2.5, 2.5)
                p.setBrush(Qt.NoBrush)
        elif k == "face":
            path = QPainterPath()
            path.moveTo(cx - 7, cy + 6)
            path.cubicTo(cx - 7, cy - 9, cx + 7, cy - 9, cx + 7, cy + 6)
            path.closeSubpath()
            p.drawPath(path)
            p.setBrush(col)
            p.drawEllipse(QPointF(cx - 2.6, cy), 1.3, 1.6)
            p.drawEllipse(QPointF(cx + 2.6, cy), 1.3, 1.6)
            p.setBrush(Qt.NoBrush)
        elif k == "term":     # >_ (터미널)
            p.drawRoundedRect(QRectF(cx - 8, cy - 6.5, 16, 13), 2.5, 2.5)
            p.drawLine(QPointF(cx - 4.5, cy - 2.5), QPointF(cx - 1.5, cy))
            p.drawLine(QPointF(cx - 1.5, cy), QPointF(cx - 4.5, cy + 2.5))
            p.drawLine(QPointF(cx + 0.5, cy + 3), QPointF(cx + 4.5, cy + 3))
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
        cols = ["#52525B", "#D4D4D8", "#18181B"] if getattr(self, "mono", False) else glow_colors()
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
    _term_used = Signal()      # 퍼플루가 명령을 실행함 → 위쪽 칸을 터미널로
    _agent_line = Signal(str, str)   # 터미널 에이전트의 한 줄 (다른 스레드 → 화면)

    def __init__(self, brain, icon=None, open_settings=None):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)   # 윈도우 위 줄 없이 (퍼플루 단추만)
        self.brain = brain
        self.open_settings = open_settings or (lambda: None)
        self.mini = False
        self.setWindowTitle("퍼플루 대화")
        from .frameless import Frameless
        self._frame = Frameless(self, can_resize=lambda: not self.mini and not config.settings().get("pc_chat_pinned"),
                                can_move=lambda: not config.settings().get("pc_chat_pinned"))
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
        self.term, self._term_backlog = None, []
        from .tools import shell as _shell
        _shell.listeners.append(self._purplu_ran)
        from . import cli_agents as _cli
        _cli.stream_listeners.append(lambda k, d: self._agent_line.emit(k, str(d)))
        self._agent_line.connect(self._agent_event)
        # 위쪽 칸 맨 위: 퍼플루 · 브라우저 · 터미널 고르기
        self.topwrap = QWidget()
        tw = QVBoxLayout(self.topwrap)
        tw.setContentsMargins(0, 0, 0, 0)
        tw.setSpacing(0)
        self.switch = QFrame()
        self.switch.setObjectName("switch")
        sw = QHBoxLayout(self.switch)
        sw.setContentsMargins(8, 4, 8, 2)
        sw.setSpacing(2)
        self.btn_face = IconButton("face", "퍼플루")
        self.btn_face.clicked.connect(lambda: self._show_top(0))
        self.btn_web = IconButton("web", "퍼플루 브라우저")
        self.btn_web.clicked.connect(lambda: self._show_top(1))
        self.btn_term = IconButton("term", "터미널")
        self.btn_term.clicked.connect(lambda: self._show_top(2))
        for b in (self.btn_face, self.btn_web, self.btn_term):
            sw.addWidget(b)
        sw.addStretch(1)
        self.btn_face.active = True
        tw.addWidget(self.switch)
        tw.addWidget(self.top, 1)
        from PySide6.QtWidgets import QSplitter
        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(10)
        self.split.addWidget(self.topwrap)
        self.split.splitterMoved.connect(self._split_moved)
        self._split_save = QTimer(self, singleShot=True, interval=700, timeout=self._save_split)
        lay.addWidget(self.split, 1)
        self._lay = lay
        self._web_hwnd.connect(self._embed_web)
        self._web_used.connect(lambda: self._show_web(True, auto=True))
        self._term_used.connect(lambda: self._top_index() != 2 and self._show_top(2, auto=True))
        from . import ownbrowser_client
        from .tools import web_browser
        ownbrowser_client.listeners.append(self._web_hwnd.emit)
        web_browser.on_use.append(self._web_used.emit)

        self.body = GlowBody()
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
        self.conv.setMinimumWidth(120)   # 대화 제목이 너무 잘리지 않게
        self.status.setMinimumWidth(96)   # '말하는 중' 이 잘리지 않게
        head.addWidget(self.title)
        head.addSpacing(6)
        head.addWidget(self.conv, 0)
        head.addWidget(self.status)
        head.addStretch(1)
        self.btn_top = IconButton("top", "위 칸(퍼플루·브라우저·터미널) 보이기 / 숨기기")
        self.btn_top.clicked.connect(self._toggle_top)
        self.btn_temp = IconButton("temp", "임시 대화 (저장 안 됨) 켜기 / 끄기")
        self.btn_temp.clicked.connect(self._toggle_temp)
        btn_new = IconButton("new", "새 대화")
        btn_new.clicked.connect(self._new_chat)
        self.btn_restore = QPushButton("⤢", self)
        self.btn_restore.setToolTip("크게 (대화창 다시 보기)")
        self.btn_restore.setFixedSize(30, 30)
        self.btn_restore.setCursor(Qt.PointingHandCursor)
        self.btn_restore.setStyleSheet("QPushButton { background:rgba(0,0,0,90); color:white; border:none; border-radius:15px; font-size:13pt; font-weight:700; }"
                                       "QPushButton:hover { background:rgba(0,0,0,150); }")
        self.btn_restore.clicked.connect(self._toggle_mini)
        self.btn_restore.hide()
        self.btn_mini = IconButton("mini", "작게 (퍼플루만) / 크게")
        self.btn_mini.clicked.connect(self._toggle_mini)
        self.btn_pin = IconButton("pin", "오른쪽에 고정 / 풀기")
        self.btn_pin.clicked.connect(lambda: config.save_settings(pc_chat_pinned=not config.settings().get("pc_chat_pinned")))
        btn_set = IconButton("settings", "설정")
        btn_set.clicked.connect(lambda: self.open_settings())
        btn_close = IconButton("close", "닫기 (Ctrl+Alt+C로 다시 열기)")
        btn_close.clicked.connect(self._close_clicked)
        head.setSpacing(2)
        for b in (self.btn_top, self.btn_temp, btn_new, self.btn_mini, self.btn_pin, btn_set):
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
        b_img = QPushButton("+")
        b_img.setToolTip("파일 첨부 (그림 · PDF · 글 파일 등)")
        b_img.clicked.connect(self._attach)
        self.model = QPushButton()
        self.model.setObjectName("modelbtn")
        self.model.setCursor(Qt.PointingHandCursor)
        self.model.setToolTip("글 대화 모델 · 노력 정도 · 말 모델")
        self.model.clicked.connect(self._model_popup)
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
        self.b_stop = QPushButton("■")
        self.b_stop.setObjectName("stop")
        self.b_stop.setToolTip("멈추기 (Ctrl+S)")
        self.b_stop.setFixedSize(36, 36)
        self.b_stop.setCursor(Qt.PointingHandCursor)
        self.b_stop.clicked.connect(self._stop)
        self.b_stop.hide()
        tools.addWidget(self.b_stop)
        tools.addSpacing(4)
        tools.addWidget(self.b_send)
        self._hurry_timer = QTimer(self, singleShot=True, interval=7000, timeout=self._offer_hurry)
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("Ctrl+S"), self, self._stop, context=Qt.WindowShortcut)
        QShortcut(QKeySequence("Ctrl+F"), self, self._hurry, context=Qt.WindowShortcut)
        gl.addLayout(tools)
        # 오래 걸릴 때: "오래 걸리고 있어요"  [빨리 대답 Ctrl F]  [기다리기]
        self.hurry_bar = QFrame()
        hb = QHBoxLayout(self.hurry_bar)
        hb.setContentsMargins(4, 2, 4, 6)
        hb.setSpacing(8)
        self.hurry_lbl = QLabel("오래 걸리고 있어요")
        hb.addWidget(self.hurry_lbl)
        hb.addStretch(1)
        self.b_hurry = KeyButton("빨리 대답", ["Ctrl", "F"], primary=True)
        self.b_hurry.clicked.connect(self._hurry)
        self.b_wait = KeyButton("기다리기", [], primary=False)
        self.b_wait.clicked.connect(self._wait)
        hb.addWidget(self.b_hurry)
        hb.addWidget(self.b_wait)
        self.hurry_bar.hide()
        bl.addWidget(self.hurry_bar)
        bl.addWidget(self.glow)
        self.body.anchor = self.glow
        self.split.addWidget(self.body)
        self.split.setStretchFactor(0, 34)
        self.split.setStretchFactor(1, 66)

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
        c = s.get("color") or "#3B82F6"
        cc = s.get("chat_color") or c
        self._cc = cc
        if hasattr(self, "b_hurry"):
            self.b_hurry.paint_colors(P)
            self.b_wait.paint_colors(P)
            self.hurry_lbl.setStyleSheet(f"color:{P['dim']}; font-size:9.5pt; background:transparent;")
            self.hurry_bar.setStyleSheet("QFrame { background:transparent; }")
        if getattr(self, "switch", None) is not None:
            self.switch.setStyleSheet(f"QFrame#switch {{ background:{P['face_bg']}; }}")
        if getattr(self, "term", None) is not None:
            self.term.apply_colors(pal(), cc)
        self.setStyleSheet(f"""
            QWidget {{ font-family:'Malgun Gothic'; font-size:10.5pt; color:{P['text']}; }}
            QFrame#body {{ background:{P['bg']}; }}
            QWidget#msgs, QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{ background:transparent; }}
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
            QPushButton#modelbtn {{ background:transparent; color:{P['text']}; border:1px solid {P['line']}; border-radius:14px; padding:5px 12px; font-weight:600; }}
            QPushButton#modelbtn:hover {{ background:{P['card']}; border-color:{cc}; }}
            QPushButton#icon {{ font-size:16pt; font-weight:300; }}
            QComboBox QAbstractItemView {{ background:{P['bg']}; color:{P['text']}; selection-background-color:{P['bubble']}; }}
            QComboBox::drop-down {{ border:none; width:18px; }}
            QListWidget#sugg {{ background:{P['bg']}; border:1px solid {P['line']}; border-radius:10px; }}
            QListWidget#sugg::item:selected {{ background:{P['bubble']}; color:{P['text']}; }}
            QScrollBar:vertical {{ width:6px; background:transparent; }}
            QScrollBar::handle:vertical {{ background:{P['line']}; border-radius:3px; }}
            QPushButton#stop {{ background:{P['card']}; color:{P['text']}; border:1px solid {P['line']}; border-radius:18px; font-size:12pt; }}
            QPushButton#stop:hover {{ background:{P['bubble']}; }}
            QSplitter::handle:vertical {{ background:{P['bg']}; image:none; border-top:1px solid {P['line']}; }}
            QSplitter::handle:vertical:hover {{ background:{cc}; border-top:1px solid {cc}; }}
        """)
        self._apply_top()
        self._paint_model_btn()
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
        working = s in ("thinking", "acting", "speaking")
        self.b_stop.setVisible(working)   # 일하는 동안만 ■
        if s in ("thinking", "acting"):
            if not self._hurry_timer.isActive() and not self.hurry_bar.isVisible() and not getattr(self, "_waiting", False):
                self._hurry_timer.start()   # 7초 넘게 걸리면 '빨리 대답 / 기다리기' 가 나온다
        elif s != "speaking":
            self._hurry_timer.stop()
            self.hurry_bar.hide()
            self._waiting = False
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
        elif kind == "meta":   # 대답한 모델 · 글/말 · 걸린 시간 (대답 아래에)
            t["meta"] = data
        elif kind == "temporary":
            return self._temp_changed(bool(data))
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

    @staticmethod
    def _md(text: str) -> str:
        """**굵게** · `코드` 정도만 예쁘게 (나머지는 그대로)."""
        import re
        t = html.escape(text, quote=False)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        return t.replace("\n", "<br>")

    def _reply_text(self, text: str, meta: dict | None = None):
        """퍼플루의 대답: 글 아래에 복사 · 답글 ……… 모델 · 글/말 ⋯. 글을 드래그하면 고른 부분에만 답글."""
        P = pal()
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        lab = self._text(self._md(text))
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
        if meta:
            more = QPushButton("⋯")
            more.setToolTip("자세히 (모델 · 글/말 · 노력 · 걸린 시간)")
            more.setCursor(Qt.PointingHandCursor)
            more.setStyleSheet(style.replace("font-size:9pt", "font-size:13pt; font-weight:700"))
            more.clicked.connect(lambda: self._meta_menu(more, meta, text))
            row.addWidget(more)
        v.addLayout(row)
        return w

    def _meta_menu(self, btn, meta, text):
        from .textchat import EFFORTS, name_of
        m = QMenu(self)
        rows = [f"모델: {name_of(meta.get('model', ''))}",
                "입력: " + {"글": "글로 입력했어요", "말": "말로 했어요"}.get(meta.get("via"), "-")]
        if meta.get("effort"):
            rows.append("노력 정도: " + dict(EFFORTS).get(meta["effort"], meta["effort"]))
        if meta.get("secs") is not None:
            rows.append(f"걸린 시간: {meta['secs']}초")
        if meta.get("note"):
            rows.append(meta["note"])
        for r in rows:
            m.addAction(r).setEnabled(False)
        m.addSeparator()
        m.addAction("⧉ 대답 복사", lambda: QGuiApplication.clipboard().setText(text))
        m.addAction("모델 바꾸기", self._model_popup)
        m.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

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
                    add(self._reply_text(m["text"], m.get("meta")))
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
                    add(self._reply_text(t["reply"], t.get("meta")))
            for r in t["results"]:
                lab = self._text(r, "10pt")
                lab.setStyleSheet(f"background:{P['card']}; border:1px solid {P['line']}; border-radius:12px; padding:8px 10px;")
                add(lab)
        empty = self.msg_lay.count() == 1 and not self.mini
        self._empty_glow(empty)
        if empty:
            if getattr(self, "temp", False):
                add(self._text(f"<div align='center' style='font-size:15pt; font-weight:600'><br>임시 대화</div>"
                               f"<div align='center' style='color:{P['dim']}; font-size:9.5pt'>아무도 훔쳐보지 않아요. 끝내면 다 잊어버려요.</div>"))
            else:
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
        self.conv.setText(fm.elidedText(t, Qt.ElideRight, 120) + " ▾")   # 아이콘을 덮지 않게 (끝은 …)
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
        pop = ConvPopup(self)
        pop.show()
        pop.setFocus()

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
        if auto and self._top_index() == 1:
            return
        self._show_top(1 if on else 0, auto)

    def _show_top(self, which: int, auto: bool = False):
        """위쪽 칸: 0 퍼플루 얼굴 · 1 퍼플루 브라우저 · 2 터미널. 같은 단추를 또 누르면 얼굴로."""
        if which == 2 and self.term is None:   # 터미널은 처음 열 때 만든다
            from .terminal import Terminal
            self.term = Terminal(str(config.BASE_DIR), pal(), self._cc)
            self.term.close_clicked.connect(lambda: self._show_top(0))
            self.term.expand_clicked.connect(self._term_expand)
            self.top.addWidget(self.term)
            for line in self._term_backlog:
                self.term.purplu_ran.emit(*line)
            self._term_backlog = []
        if which == self.top.currentIndex():
            return
        self.top.setCurrentWidget(self.face if which == 0 else self.web_holder if which == 1 else self.term)
        for b, n in ((self.btn_face, 0), (self.btn_web, 1), (self.btn_term, 2)):
            b.active = which == n
            b.update()
        if which == 0:
            self._apply_top()
            return
        if self.mini:
            self._toggle_mini()
        if config.settings().get("pc_top_hidden") and not auto:   # 내가 고르면 숨긴 위 칸도 다시 보이게
            config.save_settings(pc_top_hidden=False)
        self._apply_top()
        if auto and not self.isVisible():
            self.open(False)
        if which == 1:
            from . import ownbrowser_client as ob
            if ob.alive() and ob.hwnd[0]:
                self._embed_web(ob.hwnd[0])
            else:
                threading.Thread(target=ob.start, daemon=True).start()
        else:
            self.term.focus()

    # ---------------- 터미널 에이전트 연동 ----------------
    _cli_done = Signal(str, dict)

    def _cli_connect(self, agent):
        """'터미널로 연동': 동의 → 설치 확인 → 로그인 확인 → 연동 (확인은 뒤에서, 최대 2분)."""
        from PySide6.QtWidgets import QMessageBox
        from .cli_agents import AGENTS
        name = AGENTS[agent]["name"]
        if QMessageBox.question(self, f"{name} 연동",
                                f"{name}를 퍼플루와 연동할까요?\n\n연동하면 글 대화에서 {name}를 고를 수 있고, "
                                f"대화창 위 '터미널'의 지금 폴더에서 일해요 (파일을 만들고 고칠 수 있어요).\n"
                                f"설치·로그인돼 있는지 먼저 확인할게요 (짧은 시험 질문을 한 번 보내요).") != QMessageBox.Yes:
            return
        self.turn["results"].append(f"{html.escape(name)} 확인하는 중… (설치 · 로그인)")
        self._schedule()
        if not hasattr(self, "_cli_hooked"):
            self._cli_done.connect(self._cli_checked)
            self._cli_hooked = True

        def work():
            from . import cli_agents
            self._cli_done.emit(agent, cli_agents.check(agent))
        threading.Thread(target=work, daemon=True).start()

    def _cli_checked(self, agent, r):
        from PySide6.QtWidgets import QMessageBox
        from . import cli_agents
        info = cli_agents.AGENTS[agent]
        name = info["name"]
        if not r.get("installed"):
            how = info["install"]
            msg = f"{name}가 이 PC에 설치돼 있지 않아요."
            if how:
                if QMessageBox.question(self, name, msg + f"\n\n터미널에서 설치할까요?\n  {how}\n(Node.js 가 있어야 해요)") == QMessageBox.Yes:
                    self._show_top(2)
                    self.term.cur.con.insertPlainText(how)   # 엔터를 누르면 설치 (직접 확인하고)
                    self.term.focus()
            else:
                QMessageBox.information(self, name, msg + f"\n{info['site']} 에서 설치해 주세요.")
            return
        if not r.get("logged_in"):
            if QMessageBox.question(self, name, f"{name}는 설치돼 있지만 로그인이 필요해 보여요.\n\n"
                                    f"새 창에서 로그인할까요? {info.get('login_hint', '')}\n로그인한 뒤 다시 '터미널로 연동'을 눌러 주세요.\n\n"
                                    f"({r.get('output', '')[:160]})") == QMessageBox.Yes:
                cli_agents.open_login(agent)
            return
        have = list(dict.fromkeys((config.settings().get("cli_agents") or []) + [agent]))
        config.save_settings(cli_agents=have, text_model="cli:" + agent)
        self._paint_model_btn()
        self.turn["results"].append(f"✓ {html.escape(name)} 연동됐어요. 이제 글로 부탁하면 터미널에서 {html.escape(name)}가 일해요.")
        self._schedule()

    def _agent_event(self, kind, data):
        if kind == "start" and self._top_index() != 2:
            self._show_top(2, auto=True)
        if self.term is None:
            self._show_top(2, auto=True)
        self.term.agent_event.emit(kind, data)

    def _term_expand(self):
        """터미널 ⤢: 위쪽을 크게(대화는 조금만) ↔ 보통."""
        self._term_big = not getattr(self, "_term_big", False)
        self._apply_split()

    # ---------------- 위 칸 보이기 · 높이 ----------------
    def _top_visible(self) -> bool:
        s = config.settings()
        if self.mini:
            return True   # 작게 = 퍼플루 얼굴만
        if s.get("pc_top_hidden"):
            return False
        return s.get("pc_layout", "stack") != "full" or self._top_index() != 0

    def _apply_top(self):
        on = self._top_visible()
        self.topwrap.setVisible(on)
        self.btn_top.active = on
        self.btn_top.update()
        if on:
            self._apply_split()
        else:   # 숨기면 대화가 바로 그 자리까지
            self.split.setSizes([0, max(200, self.split.height())])
            self.split.updateGeometry()

    def _toggle_top(self):
        hide = self.topwrap.isVisible()
        config.save_settings(pc_top_hidden=hide)
        if not hide and config.settings().get("pc_layout") == "full" and self._top_index() == 0:
            config.save_settings(pc_layout="stack")   # '얼굴 안 보이기' 였어도 다시 보이게
        self._apply_top()

    def _apply_split(self):
        """끌어서 정한 높이: 얼굴일 때와 브라우저·터미널일 때를 따로 기억한다."""
        s = config.settings()
        frac = 0.88 if (getattr(self, "_term_big", False) and self._top_index() == 2) else \
            float(s.get("pc_split_face" if self._top_index() == 0 else "pc_split_tool") or 0.4)
        total = max(200, self.split.height())
        frac = max(0.12, min(0.88, frac))
        self.split.setSizes([int(total * frac), int(total * (1 - frac))])

    def _split_moved(self, *_):
        a, b = self.split.sizes()
        if a and b:
            self._split_frac = a / (a + b)
            self._split_save.start()

    def _save_split(self):
        key = "pc_split_face" if self._top_index() == 0 else "pc_split_tool"
        config.save_settings(**{key: round(self._split_frac, 3)})

    def _top_index(self) -> int:
        w = self.top.currentWidget()
        return 0 if w is self.face else 1 if w is self.web_holder else 2

    def _purplu_ran(self, cmd: str, output: str, code: int):
        """퍼플루가 run_command 로 실행한 명령 → 터미널에 (다른 스레드에서 불림)."""
        if self.term is not None:
            self.term.purplu_ran.emit(cmd, output[-6000:], code)
        else:
            self._term_backlog = (self._term_backlog + [(cmd, output[-6000:], code)])[-20:]
        self._term_used.emit()

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
        """작게: 대화창은 숨기고 퍼플루 얼굴만 (꾹 누르면 말하기). 오른쪽 위 ⤢ 로 다시 크게."""
        self.mini = not self.mini
        self.btn_mini.active = self.mini
        self.btn_mini.update()
        if self.mini:
            self._big_geom = self.geometry()
            self._mini_prev = self._top_index()
            if self._appbar:
                self._release_space()   # 고정(자리 차지) 중이었으면 잠깐 풀기
            self.body.hide()
            self.switch.hide()
            self.top.setCurrentWidget(self.face)
            self.topwrap.show()
            self.setMinimumSize(150, 130)
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.setGeometry(area.right() - 276, area.bottom() - 250, 260, 230)
            self._place_restore()
            self.btn_restore.show()
            self.btn_restore.raise_()
        else:
            self.btn_restore.hide()
            self.setMinimumSize(300, 220)
            self.body.show()
            self.switch.show()
            prev = getattr(self, "_mini_prev", 0)
            self.top.setCurrentWidget(self.face if prev == 0 else self.web_holder if prev == 1 else (self.term or self.face))
            self._apply_top()
            if getattr(self, "_big_geom", None):
                self.setGeometry(self._big_geom)
            if config.settings().get("pc_chat_pinned"):
                self.apply_pin()
        self._render()

    def _place_restore(self):
        self.btn_restore.move(self.width() - self.btn_restore.width() - 8, 8)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "mini", False) and hasattr(self, "btn_restore"):
            self._place_restore()

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
    def _empty_glow(self, on: bool):
        """새 대화(첫 화면)일 때만 대화 칸 바닥의 빛을 켠다. 임시 대화면 부드러운 검은 빛 (대화 중에도 옅게)."""
        temp = bool(getattr(self, "temp", False))
        key = (on, self._cc, light(), temp)
        if getattr(self, "_glow_on", None) == key:
            return
        self._glow_on = key
        self.glow.mono = temp
        self.glow.update()
        if temp:
            self.body.set_glow(True, "#3F3F46" if light() else "#000000", not light(), mono=True, strength=1.0 if on else 0.45)
        else:
            self.body.set_glow(on, self._cc, not light())

    def _toggle_temp(self):
        self.brain.set_temporary(not bool(getattr(self.brain, "temporary", False)))

    def _temp_changed(self, on: bool):
        """임시 대화: 화면을 비우고 '임시 대화' 로, 끝내면 원래 대화로 돌아간다."""
        self.temp = on
        self.btn_temp.active = on
        self.btn_temp.update()
        self.face.temp = on   # 임시 대화 동안 퍼플루가 선글라스를 쓴다
        self.face.update()
        self.history, self.past, self.turn = [], [], self._new_turn()
        if on:
            self._show_title("임시 대화")
            self._render()
        else:
            self.load_history()
        self._glow_on = None
        self._render()

    def _model_popup(self):
        pop = ModelPopup(self)
        pop.show()
        pop.setFocus()

    def _paint_model_btn(self):
        from .textchat import EFFORTS, model_info
        s = config.settings()
        mid, name, _d, think = model_info(s.get("text_model") or "gemini-3.8-flash")
        eff = dict(EFFORTS).get(s.get("effort") or "medium", "")
        self.model.setText(f"{name}" + (f"  ·  {eff}" if think else "") + "  ▾")

    def _stop(self):
        if self.state in ("thinking", "acting", "speaking", "listening"):
            self.brain.stop_turn()
            self.hurry_bar.hide()

    def _hurry(self):
        if self.state in ("thinking", "acting"):
            self.brain.hurry()
            self.hurry_bar.hide()
            self._waiting = True   # 이번 부탁에는 다시 묻지 않는다

    def _offer_hurry(self):
        if self.state in ("thinking", "acting") and not getattr(self, "_waiting", False):
            self.hurry_bar.show()

    def _wait(self):
        """기다리기: 이번 부탁은 끝까지 기다린다 (다시 묻지 않음)."""
        self.hurry_bar.hide()
        self._waiting = True

    def _talk_start(self):
        self.brain.talk_start("pc")

    def _talk_end(self):
        self.brain.talk_end()

    def _send(self):
        text = self.input.toPlainText().strip()
        if not text and not self.attach:
            return
        if text.lower().startswith("/model-") and len(text) > 7:
            self.input.clear()
            self.sugg.hide()
            self._quick_model(text[7:])
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
            att = img or {}
            data, mime = att.get("data"), att.get("mime")
            full = _expand_chat(text or "이 파일 봐 줘", mentions)
            shown = text
            if att:
                live = (config.settings().get("text_model") or "") == "live"
                if att.get("text") is not None:   # 글 파일: 내용을 그대로 붙인다
                    full += f"\n\n[첨부 파일: {att['name']}]\n{att['text'][:120000]}"
                elif mime == "application/pdf" and live:   # 라이브는 PDF 를 못 받아서 경로로
                    data = mime = None
                if data is None and att.get("text") is None:
                    full += f"\n\n[첨부 파일: {att['name']} — 경로: {att['path']} (필요하면 도구로 열거나 읽어)]"
                shown = (text + "\n" if text else "") + f"📎 {att['name']}"
            if quote:   # 답글: 퍼플루에게는 어느 부분에 대한 말인지, 말풍선에는 짧게
                full = f"(네 앞 대답 중 이 부분에 대한 말이야: \"{quote[:600]}\")\n{full}"
                shown = f"↪ {quote[:60]}{'…' if len(quote) > 60 else ''}\n{text}"
            self.brain.send_text(full, data, mime or "image/jpeg", shown=shown)
        threading.Thread(target=work, daemon=True).start()

    TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css", ".xml", ".yaml", ".yml",
                ".log", ".ini", ".bat", ".ps1", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".sql", ".tsv"}

    def _attach(self):
        """+ : 파일을 바로 고른다. 그림·PDF 는 그대로 보내고, 글 파일은 내용을 붙이고, 나머지는 경로를 알려 준다."""
        path, _ = QFileDialog.getOpenFileName(self, "첨부할 파일 고르기", "", "모든 파일 (*.*)")
        if not path:
            return
        import io
        import os
        name, ext = os.path.basename(path), os.path.splitext(path)[1].lower()
        win_path = path.replace("/", "\\")
        att = {"name": name, "path": win_path, "data": None, "mime": None, "text": None}
        try:
            if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
                from PIL import Image
                im = Image.open(path).convert("RGB")
                im.thumbnail((1600, 1600))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=85)
                att.update(data=buf.getvalue(), mime="image/jpeg")
            elif ext == ".pdf" and os.path.getsize(path) < 15 * 1024 * 1024:
                att.update(data=open(path, "rb").read(), mime="application/pdf")
            elif ext in self.TEXT_EXT and os.path.getsize(path) < 400 * 1024:
                raw = open(path, "rb").read()
                for enc in ("utf-8", "cp949"):
                    try:
                        att["text"] = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        pass
        except Exception as e:
            att["error"] = str(e)
        self.attach = att
        self.attach_lbl.setText(f"📎 {name}  (보내면 같이 가요 · 다시 + 로 바꾸기)")
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
                           if not q.startswith("model-") and (n.startswith(q) or q in d.lower() or CMD_ALIAS.get(q, "") == n)]
            if q.startswith("model"):   # /model-gemini3.8 처럼 바로 바꾸기
                want = model_slug(q[6:]) if q.startswith("model-") else ""
                cur = config.settings().get("text_model") or ""
                self._items += [{"label": "model-" + r["slug"], "mid": r["mid"],
                                 "sub": f"{r['group']} · {r['name']}" + (f" ({r['kind']})" if r["kind"] else "")
                                 + ("  · 지금 쓰는 중" if r["mid"] == cur else "")}
                                for r in quick_models() if want in r["slug"]]
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

    def _quick_model(self, q: str):
        """/model-이름: 창을 열지 않고 글 대화 모델을 바로 바꾼다."""
        hit = find_model(q)
        if not hit:
            old = self.input.placeholderText()
            self.input.setPlaceholderText(f"'{q}' 모델은 없어요. /model- 을 치면 목록이 나와요")
            QTimer.singleShot(4000, lambda: self.input.setPlaceholderText(old))
            return
        config.save_settings(text_model=hit["mid"])
        self._paint_model_btn()
        self.input.setFocus()

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
            self._model_popup()
        elif name == "temp":
            self._toggle_temp()
        elif name == "mini":
            self._toggle_mini()
        elif name == "web":
            self._show_top(0 if self._top_index() == 1 else 1)
        elif name == "hide":
            self._toggle_top()
        elif name == "term":
            self._show_top(0 if self._top_index() == 2 else 2)
        elif name == "pin":
            config.save_settings(pc_chat_pinned=not s.get("pc_chat_pinned"))
        elif name == "top":
            config.save_settings(pc_chat_on_top=not s.get("pc_chat_on_top", True))
        elif name == "image":
            self._attach()
        elif name == "mcp":
            return self._mcp_menu()
        elif name == "custom":
            from .customize import CustomizeWindow
            if getattr(self, "_custom_win", None) is None:
                self._custom_win = CustomizeWindow()
            return self._custom_win.open()
        elif name == "skills":
            self.input.setPlainText("#")
            self.input.moveCursor(self.input.textCursor().MoveOperation.End)
        elif name == "close":
            self._close_clicked()
        self.input.setFocus()

    def _mcp_menu(self):
        """/mcp: 붙인 MCP 서버를 보고 켜고 끄기, 예시 추가, 다시 연결, 설정 열기 (Claude 의 /mcp 처럼)."""
        from . import mcp_client
        m = QMenu(self)
        servers = mcp_client.load()
        head = m.addAction(f"MCP 서버 {len(servers)}개")
        head.setEnabled(False)
        for sv in servers:
            st = mcp_client.status.get(sv["name"], {})
            state = {"ok": f"● 도구 {len(st.get('tools', []))}개", "connecting": "… 연결 중", "error": "⚠ 오류"}.get(st.get("state"), "○ 꺼짐")
            act = m.addAction(f"{sv['name']}    {state}")
            act.setCheckable(True)
            act.setChecked(sv.get("enabled", True))
            act.setToolTip(st.get("error", ""))

            def flip(on, name=sv["name"]):
                rows = mcp_client.load()
                for x in rows:
                    if x["name"] == name:
                        x["enabled"] = on
                mcp_client.save(rows)
            act.toggled.connect(flip)
        if not servers:
            m.addAction("(아직 없어요 — 아래 예시에서 골라 보세요)").setEnabled(False)
        m.addSeparator()
        ex = m.addMenu("예시에서 추가")
        have = {x["name"] for x in servers}
        for p in mcp_client.PRESETS:
            a = ex.addAction(f"{p['name']}  —  {p['desc']}" + ("   (추가됨)" if p["name"] in have else ""))
            a.triggered.connect(lambda _=False, p=p: self._mcp_add_preset(p))
        m.addAction("다시 연결", mcp_client.reload)
        m.addAction("MCP 설정 열기", lambda: self.open_settings("MCP"))
        m.exec(self.input.mapToGlobal(self.input.rect().topLeft()) - QPoint(0, m.sizeHint().height()))
        self.input.setFocus()

    def _mcp_add_preset(self, p):
        from .settings_window import add_preset
        sv = add_preset(self, p)
        if sv:
            self.turn["results"].append(f"🔌 MCP '{html.escape(sv['name'])}' 추가했어요. 연결하는 중… (처음엔 30초쯤 걸릴 수 있어요)")
            self._schedule()

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
            if it.get("mid"):
                self._quick_model(it["label"][6:])
            else:
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
        if self.mini:
            return   # 작게 보는 동안은 고정 자리로 늘리지 않는다 (크게 하면 다시)
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

    def mousePressEvent(self, e):
        if not self._frame.drag(e):   # 빈 곳을 끌면 창 옮기기 (오른쪽에 고정해 두면 안 움직인다)
            super().mousePressEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        from .frameless import round_corners
        round_corners(self)

    def closeEvent(self, e):
        self._release_space()
        super().closeEvent(e)
