"""퍼플루 얼굴 그리기 + 꾸미기 (눈 · 모자 · 더듬이 · 소품).

디자인 좌표는 844×390 (아래에서 쏙 올라온 몸). 몸 위쪽 가운데가 (422, top).
꾸미기는 설정 face_eyes / face_hat / face_antenna / face_extra / face_hat_color 에 저장된다.
"""
import math
import random
import time
from types import SimpleNamespace

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient

from . import config

EYES = [("basic", "기본"), ("sparkle", "반짝"), ("heart", "하트"), ("sleepy", "졸린"), ("smile", "웃는"),
        ("dot", "콩알"), ("cat", "고양이"), ("star", "별")]
HATS = [("none", "없음"), ("crown", "왕관"), ("party", "고깔"), ("beanie", "비니"), ("cap", "야구모자"),
        ("wizard", "마법사"), ("tophat", "신사 모자"), ("santa", "산타"), ("bow", "리본"), ("flowers", "꽃 화관"),
        ("chef", "요리사"), ("halo", "천사 고리")]
ANTENNAS = [("none", "없음"), ("ball", "동그라미"), ("bug", "곤충"), ("heart", "하트"), ("star", "별"),
            ("sprout", "새싹"), ("bolt", "번개")]
EXTRAS = [("none", "없음"), ("glasses", "안경"), ("sunglasses", "선글라스"), ("heart_cheeks", "하트 볼"),
          ("mustache", "콧수염"), ("bandage", "반창고"), ("freckles", "주근깨")]
HAT_COLORS = ["", "#EF4444", "#F59E0B", "#22C55E", "#3B82F6", "#8B5CF6", "#EC4899", "#111827", "#FFFFFF"]

INK = QColor("#1A1426")


def options(**over) -> dict:
    s = config.settings()
    o = {"eyes": s.get("face_eyes") or "basic", "hat": s.get("face_hat") or "none",
         "antenna": s.get("face_antenna") or "none", "extra": s.get("face_extra") or "none",
         "hat_color": s.get("face_hat_color") or ""}
    o.update(over)
    return o


def still(state="idle"):
    """움직이지 않는 얼굴 (미리보기·작은 그림용)."""
    t = time.monotonic()
    return SimpleNamespace(state=state, talk=0.0, _gx=0.15, _gy=0.1, _blink=t - 10, _happy_until=0.0, _t0=t)


# ---------------------------------------------------------------- 그리기
def draw_face(p: QPainter, W: float, H: float, v, opts: dict | None = None, bg: str | None = None, base: str | None = None):
    """v: state·talk·_gx·_gy·_blink·_happy_until·_t0 가 있는 것 (FaceView 또는 still())."""
    o = opts or options()
    p.setRenderHint(QPainter.Antialiasing)
    if bg:
        p.fillRect(QRectF(0, 0, W, H), QColor(bg))
    now = time.monotonic()
    base = QColor(base or config.settings().get("color") or "#8B5CF6")
    extra_top = 150 if (o["hat"] != "none" or o["antenna"] != "none") else 0   # 모자·더듬이가 잘리지 않게 위를 비운다
    s = min(W / 884, H * 0.95 / (390 + extra_top))
    p.save()
    p.translate((W - 844 * s) / 2, H - 390 * s)
    p.scale(s, s)
    bob = math.sin((now - v._t0) * 1.8) * 3 - v.talk * 14
    body = QRectF(12, 44 + bob, 820, 700)
    T, cx = body.top(), body.center().x()
    if v.state == "listening":
        glow = QRadialGradient(cx, T + 200, 520)
        aura = QColor(config.settings().get("chat_color") or config.settings().get("color") or "#8B5CF6")
        aura.setAlpha(150)
        glow.setColorAt(0, aura)   # 듣는 동안의 빛 = 내가 고른 색
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(-200, -400, 1300, 1100), glow)

    _antenna(p, o["antenna"], cx, T, base, now)

    path = QPainterPath()
    bot = body.bottom()
    path.moveTo(body.left(), bot)
    path.cubicTo(body.left() - 4, T + body.height() * .36, cx - body.width() * .36, T, cx, T)
    path.cubicTo(cx + body.width() * .36, T, body.right() + 4, T + body.height() * .36, body.right(), bot)
    path.closeSubpath()
    grad = QLinearGradient(body.topLeft(), QPointF(body.right(), T + body.height() * .6))
    grad.setColorAt(0, base.lighter(170))
    grad.setColorAt(.5, base)
    grad.setColorAt(1, base.darker(140))
    p.fillPath(path, grad)
    shine = QRadialGradient(body.left() + 246, T + 126, 243)
    shine.setColorAt(0, QColor(255, 255, 255, 120))
    shine.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillPath(path, shine)

    navy = QColor(base).darker(260)
    happy = now < v._happy_until or o["eyes"] == "smile"
    bt = (now - v._blink) / 0.15
    closed = math.sin(math.pi * bt) if 0 <= bt <= 1 else 0
    for i, ex in enumerate((body.left() + 280, body.left() + 540)):
        ey = T + 157
        side = -1 if i == 0 else 1
        p.setPen(QPen(navy, 14, Qt.SolidLine, Qt.RoundCap))   # 눈썹
        lift = {"listening": 10, "thinking": 4, "speaking": 8}.get(v.state, 0)
        brow = QPainterPath()
        brow.moveTo(ex - 38 + side * 6, ey - 106 - lift * .7)
        brow.quadTo(ex + side * 6, ey - 124 - lift * .7, ex + 38 + side * 6, ey - 106 - lift * .7)
        p.drawPath(brow)
        _eye(p, o["eyes"], ex, ey, side, v, closed, happy, base)

    # 볼
    p.setPen(Qt.NoPen)
    if o["extra"] == "heart_cheeks":
        for ex in (body.left() + 218, body.left() + 602):
            _heart(p, QPointF(ex, T + 268), 38, QColor(244, 114, 182, 210))
    else:
        p.setBrush(QColor(243, 166, 216, 110 if happy else 70))
        for ex in (body.left() + 218, body.left() + 602):
            p.drawEllipse(QPointF(ex, T + 274), 45, 21)
    # 입
    nw, nh = 60 - v.talk * 8, 38 + v.talk * 34
    nx, ny = body.left() + 410 - nw / 2, T + 272 - v.talk * 6
    p.setBrush(navy)
    if happy and v.talk < .1:
        m = QPainterPath()
        m.moveTo(nx - 8, ny + 8)
        m.quadTo(nx + nw / 2, ny + 58, nx + nw + 8, ny + 8)
        m.closeSubpath()
        p.drawPath(m)
    else:
        p.drawEllipse(QRectF(nx, ny, nw, nh))

    _extra(p, o["extra"], body, T, navy)
    _hat(p, o["hat"], cx, T, QColor(o["hat_color"]) if o.get("hat_color") else None, base, now)

    if v.state == "thinking":   # 생각 중: 점점점
        p.setPen(Qt.NoPen)
        for k in range(3):
            p.setBrush(QColor(255, 255, 255, int(255 * (1 - k * .3))))
            p.drawEllipse(QPointF(body.left() + 698 + k * 26, T + 48 - k * 12 + math.sin(now * 3 + k) * 4), 8, 8)
    p.restore()


# ---------------------------------------------------------------- 눈
def _eye(p, kind, ex, ey, side, v, closed, happy, base):
    if happy:   # ^ ^
        p.setPen(QPen(INK, 24, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        arc = QPainterPath()
        arc.moveTo(ex - 60, ey + 34)
        arc.quadTo(ex, ey - 54, ex + 60, ey + 34)
        p.drawPath(arc)
        return
    open_ = max(0.06, 1 - closed) * (1 - v.talk * 0.12)
    p.setPen(Qt.NoPen)
    if kind == "dot":   # 콩알눈: 흰자 없이 까만 콩
        p.setBrush(INK)
        p.drawEllipse(QPointF(ex + v._gx * 14, ey + 10 + v._gy * 10), 30, 40 * open_)
        p.setBrush(QColor("white"))
        if open_ > .3:
            p.drawEllipse(QPointF(ex + v._gx * 14 - 9, ey - 4), 9, 9)
        return
    rx, ry = 95, 95 * open_
    p.setBrush(QColor("white"))
    p.drawEllipse(QPointF(ex, ey), rx, ry)
    if open_ <= 0.2:
        return
    r = 46 * (1.12 if v.state == "listening" else 1)
    px, py = ex + v._gx * 50 - side * 3, ey + v._gy * 50 * open_
    clip = QPainterPath()
    clip.addEllipse(QPointF(ex, ey), rx, ry)
    p.save()
    p.setClipPath(clip)
    if kind == "heart":
        _heart(p, QPointF(px, py + 4), r * 1.05, QColor("#E11D48"))
        p.setBrush(QColor(255, 255, 255, 220))
        p.drawEllipse(QPointF(px - r * .35, py - r * .25), r * .18, r * .18)
    elif kind == "cat":
        p.setBrush(QColor("#A3E635"))
        p.drawEllipse(QPointF(px, py), r * 1.15, r * 1.15)
        p.setBrush(INK)
        p.drawEllipse(QPointF(px, py), r * .28, r * 1.0)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(px - r * .45, py - r * .5), r * .2, r * .2)
    elif kind == "star":
        p.setBrush(INK)
        p.drawEllipse(QPointF(px, py), r, r)
        _star(p, QPointF(px, py), r * .62, QColor("#FDE047"))
    else:
        p.setBrush(INK)
        p.drawEllipse(QPointF(px, py), r, r)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(px - r * .3, py - r * .44), r * .28, r * .28)
        p.setBrush(QColor(255, 255, 255, 215))
        p.drawEllipse(QPointF(px + r * .4, py + r * .34), r * .12, r * .12)
        if kind == "sparkle":   # 반짝이는 별 하이라이트
            _sparkle(p, QPointF(px + r * .2, py - r * .2), r * .55, QColor(255, 255, 255, 235))
    p.restore()
    if kind == "sleepy":   # 졸린 눈: 위쪽 반을 눈꺼풀로
        p.save()
        p.setClipPath(clip)
        p.setBrush(QColor(base).darker(115))
        p.drawRect(QRectF(ex - rx, ey - ry - 2, rx * 2, ry * 1.05))
        p.setPen(QPen(INK, 10, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(ex - rx, ey + ry * .05), QPointF(ex + rx, ey + ry * .05))
        p.restore()


# ---------------------------------------------------------------- 모양 도우미
def _heart(p, c: QPointF, r, color):
    path = QPainterPath()
    x, y = c.x(), c.y()
    path.moveTo(x, y + r * .9)
    path.cubicTo(x - r * 1.5, y - r * .1, x - r * .7, y - r * 1.1, x, y - r * .35)
    path.cubicTo(x + r * .7, y - r * 1.1, x + r * 1.5, y - r * .1, x, y + r * .9)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(path)


def _star(p, c: QPointF, r, color, points=5, inner=.45):
    pts = []
    for k in range(points * 2):
        a = -math.pi / 2 + k * math.pi / points
        rr = r if k % 2 == 0 else r * inner
        pts.append(QPointF(c.x() + math.cos(a) * rr, c.y() + math.sin(a) * rr))
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPolygon(QPolygonF(pts))


def _sparkle(p, c, r, color):
    _star(p, c, r, color, points=4, inner=.22)


def _ellipse_top(cx, cy, rx, ry) -> QPainterPath:
    """윗쪽 반원 (모자 돔)."""
    path = QPainterPath()
    path.moveTo(cx - rx, cy)
    path.arcTo(QRectF(cx - rx, cy - ry, rx * 2, ry * 2), 180, -180)
    path.closeSubpath()
    return path


# ---------------------------------------------------------------- 더듬이
def _antenna(p, kind, cx, T, base, now):
    if kind == "none":
        return
    dark = QColor(base).darker(170)
    wob = math.sin(now * 2.2) * 6
    p.setBrush(Qt.NoBrush)

    def stalk(x0, x1, y1, bend):
        path = QPainterPath()
        path.moveTo(x0, T + 30)
        path.quadTo(x0 + bend, (T + y1) / 2 - 20, x1 + wob, y1)
        p.setPen(QPen(dark, 12, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(path)
        return QPointF(x1 + wob, y1)

    if kind == "bug":
        for d in (-1, 1):
            tip = stalk(cx + d * 70, cx + d * 150, T - 120, d * 10)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(base).lighter(130))
            p.drawEllipse(tip, 24, 24)
        return
    tip = stalk(cx, cx + 20, T - 130, -30)
    p.setPen(Qt.NoPen)
    if kind == "ball":
        p.setBrush(QColor(base).lighter(140))
        p.drawEllipse(tip, 28, 28)
        p.setBrush(QColor(255, 255, 255, 170))
        p.drawEllipse(tip + QPointF(-9, -9), 8, 8)
    elif kind == "heart":
        _heart(p, tip, 34, QColor("#F43F5E"))
    elif kind == "star":
        _star(p, tip, 40, QColor("#FACC15"))
    elif kind == "sprout":
        p.setBrush(QColor("#22C55E"))
        for d in (-1, 1):
            leaf = QPainterPath()
            leaf.moveTo(tip)
            leaf.cubicTo(tip + QPointF(d * 20, -50), tip + QPointF(d * 80, -40), tip + QPointF(d * 90, -10))
            leaf.cubicTo(tip + QPointF(d * 60, 10), tip + QPointF(d * 20, 10), tip)
            p.drawPath(leaf)
    elif kind == "bolt":
        x, y = tip.x(), tip.y()
        p.setBrush(QColor("#FACC15"))
        p.drawPolygon(QPolygonF([QPointF(x + 10, y - 50), QPointF(x - 24, y + 4), QPointF(x - 2, y + 4),
                                 QPointF(x - 14, y + 46), QPointF(x + 26, y - 10), QPointF(x + 4, y - 10)]))


# ---------------------------------------------------------------- 모자
def _hat(p, kind, cx, T, color, base, now):
    if kind == "none":
        return
    p.setPen(Qt.NoPen)
    col = lambda default: color or QColor(default)   # noqa: E731
    if kind == "crown":
        c = col("#FBBF24")
        y0, w = T + 34, 300
        pts = [QPointF(cx - w / 2, y0), QPointF(cx - w / 2, y0 - 110), QPointF(cx - w / 4, y0 - 40), QPointF(cx, y0 - 140),
               QPointF(cx + w / 4, y0 - 40), QPointF(cx + w / 2, y0 - 110), QPointF(cx + w / 2, y0)]
        p.setBrush(c)
        p.drawPolygon(QPolygonF(pts))
        p.setBrush(c.darker(120))
        p.drawRoundedRect(QRectF(cx - w / 2, y0 - 24, w, 30), 8, 8)
        for x, gc in ((cx - w / 2, "#EF4444"), (cx, "#3B82F6"), (cx + w / 2, "#22C55E")):
            p.setBrush(QColor(gc))
            p.drawEllipse(QPointF(x, y0 - 112 if x != cx else y0 - 142), 16, 16)
    elif kind == "party":
        c = col("#EC4899")
        base_y = T + 40
        tri = QPainterPath()
        tri.moveTo(cx - 120, base_y)
        tri.lineTo(cx + 40, T - 230)
        tri.lineTo(cx + 130, base_y)
        tri.closeSubpath()
        p.fillPath(tri, c)
        p.save()
        p.setClipPath(tri)
        p.setBrush(QColor(255, 255, 255, 150))
        for k in range(4):
            y = base_y - 50 - k * 62
            p.drawRect(QRectF(cx - 200, y, 400, 18))
        p.restore()
        p.setBrush(QColor("#FDE047"))
        p.drawEllipse(QPointF(cx + 40, T - 236), 26, 26)
    elif kind == "beanie":
        c = col("#3B82F6")
        p.fillPath(_ellipse_top(cx, T + 70, 290, 190), c)
        p.setBrush(c.darker(125))
        p.drawRoundedRect(QRectF(cx - 300, T + 40, 600, 64), 28, 28)
        p.setPen(QPen(c.darker(140), 6))
        for k in range(-5, 6):
            p.drawLine(QPointF(cx + k * 50, T + 48), QPointF(cx + k * 50, T + 96))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(cx, T - 126), 42, 42)
    elif kind == "cap":
        c = col("#EF4444")
        p.fillPath(_ellipse_top(cx - 10, T + 70, 270, 175), c)
        brim = QPainterPath()
        brim.moveTo(cx + 150, T + 66)
        brim.quadTo(cx + 380, T + 40, cx + 420, T + 88)
        brim.quadTo(cx + 300, T + 100, cx + 150, T + 86)
        brim.closeSubpath()
        p.fillPath(brim, c.darker(120))
        p.setBrush(c.darker(130))
        p.drawEllipse(QPointF(cx - 10, T - 104), 18, 12)
        p.setBrush(QColor(255, 255, 255, 200))
        p.drawRoundedRect(QRectF(cx - 70, T - 20, 110, 60), 14, 14)   # 앞 로고 자리
    elif kind == "wizard":
        c = col("#312E81")
        p.setBrush(c.darker(115))
        p.drawEllipse(QPointF(cx, T + 46), 330, 52)
        cone = QPainterPath()
        cone.moveTo(cx - 180, T + 40)
        cone.quadTo(cx - 40, T - 120, cx + 120, T - 270)
        cone.quadTo(cx + 60, T - 100, cx + 180, T + 40)
        cone.closeSubpath()
        p.fillPath(cone, c)
        for (dx, dy, r) in ((-60, -10, 22), (30, -90, 16), (60, 0, 14), (-10, -170, 12)):
            _star(p, QPointF(cx + dx, T + dy), r, QColor("#FDE047"))
    elif kind == "tophat":
        c = col("#111827")
        p.setBrush(c)
        p.drawEllipse(QPointF(cx, T + 46), 260, 40)
        p.drawRoundedRect(QRectF(cx - 150, T - 210, 300, 256), 18, 18)
        p.setBrush(QColor(base).lighter(110))
        p.drawRect(QRectF(cx - 150, T - 6, 300, 40))
    elif kind == "santa":
        c = col("#DC2626")
        cone = QPainterPath()
        cone.moveTo(cx - 260, T + 60)
        cone.quadTo(cx - 80, T - 220, cx + 200, T - 150)
        cone.quadTo(cx + 300, T - 120, cx + 310, T - 40)
        cone.quadTo(cx + 160, T - 60, cx + 260, T + 60)
        cone.closeSubpath()
        p.fillPath(cone, c)
        p.setBrush(QColor("white"))
        p.drawRoundedRect(QRectF(cx - 290, T + 30, 580, 70), 35, 35)
        p.drawEllipse(QPointF(cx + 316, T - 34), 36, 36)
    elif kind == "bow":
        c = col("#F472B6")
        bx, by = cx + 150, T + 34
        for d in (-1, 1):
            wing = QPainterPath()
            wing.moveTo(bx, by)
            wing.cubicTo(bx + d * 60, by - 110, bx + d * 170, by - 60, bx + d * 150, by + 10)
            wing.cubicTo(bx + d * 170, by + 80, bx + d * 60, by + 100, bx, by)
            p.fillPath(wing, c)
        p.setBrush(c.darker(120))
        p.drawEllipse(QPointF(bx, by), 34, 30)
    elif kind == "flowers":
        cols = [QColor("#F472B6"), QColor("#FDE047"), QColor("#FFFFFF"), QColor("#A78BFA"), QColor("#FB923C")]
        p.setPen(QPen(QColor("#16A34A"), 10, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        vine = QPainterPath()
        vine.moveTo(cx - 300, T + 70)
        vine.quadTo(cx, T - 10, cx + 300, T + 70)
        p.drawPath(vine)
        p.setPen(Qt.NoPen)
        for k in range(7):
            t = k / 6
            x = cx - 300 + 600 * t
            y = T + 70 - 160 * t * (1 - t)
            for a in range(5):
                ang = a * 2 * math.pi / 5
                p.setBrush(cols[k % len(cols)])
                p.drawEllipse(QPointF(x + math.cos(ang) * 20, y + math.sin(ang) * 20), 17, 17)
            p.setBrush(QColor("#F59E0B"))
            p.drawEllipse(QPointF(x, y), 12, 12)
    elif kind == "chef":
        c = col("#FFFFFF")
        p.setBrush(c)
        for dx, dy, r in ((-110, -70, 90), (0, -120, 105), (110, -70, 90)):
            p.drawEllipse(QPointF(cx + dx, T + dy), r, r)
        p.drawRoundedRect(QRectF(cx - 170, T - 60, 340, 120), 20, 20)
        p.setPen(QPen(QColor("#E5E7EB"), 6))
        for k in (-80, 0, 80):
            p.drawLine(QPointF(cx + k, T - 20), QPointF(cx + k, T + 50))
    elif kind == "halo":
        c = col("#FDE047")
        y = T - 70 + math.sin(now * 2) * 6
        glow = QRadialGradient(cx, y, 260)
        glow.setColorAt(0, QColor(c.red(), c.green(), c.blue(), 90))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(cx - 300, y - 200, 600, 400), glow)
        p.setPen(QPen(c, 22))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, y), 190, 42)


# ---------------------------------------------------------------- 소품
def _extra(p, kind, body, T, navy):
    L = body.left()
    if kind == "none" or kind == "heart_cheeks":
        return
    if kind in ("glasses", "sunglasses"):
        dark = kind == "sunglasses"
        p.setPen(QPen(QColor("#111827"), 14))
        p.setBrush(QColor(17, 24, 39, 225) if dark else Qt.NoBrush)
        for ex in (L + 280, L + 540):
            if dark:
                p.drawRoundedRect(QRectF(ex - 112, T + 92, 224, 140), 50, 50)
            else:
                p.drawEllipse(QPointF(ex, T + 157), 112, 112)
        p.setBrush(Qt.NoBrush)
        bridge = QPainterPath()
        bridge.moveTo(L + 392, T + 150)
        bridge.quadTo(L + 410, T + 128, L + 428, T + 150)
        p.drawPath(bridge)
        if dark:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 70))
            for ex in (L + 280, L + 540):
                p.drawRoundedRect(QRectF(ex - 80, T + 110, 60, 22), 10, 10)
    elif kind == "mustache":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#3F2A1D"))
        for d in (-1, 1):
            m = QPainterPath()
            m.moveTo(L + 410, T + 262)
            m.cubicTo(L + 410 + d * 50, T + 236, L + 410 + d * 120, T + 250, L + 410 + d * 130, T + 278)
            m.cubicTo(L + 410 + d * 90, T + 272, L + 410 + d * 50, T + 290, L + 410, T + 272)
            p.drawPath(m)
    elif kind == "bandage":
        p.save()
        p.translate(L + 620, T + 250)
        p.rotate(-25)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FCD9B6"))
        p.drawRoundedRect(QRectF(-70, -22, 140, 44), 22, 22)
        p.setBrush(QColor("#F2B88A"))
        p.drawRect(QRectF(-24, -22, 48, 44))
        p.setBrush(QColor(0, 0, 0, 40))
        for x in (-12, 0, 12):
            for y in (-8, 8):
                p.drawEllipse(QPointF(x, y), 3, 3)
        p.restore()
    elif kind == "freckles":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(120, 72, 40, 150))
        rnd = random.Random(7)
        for ex in (L + 218, L + 602):
            for _ in range(6):
                p.drawEllipse(QPointF(ex + rnd.uniform(-40, 40), T + 268 + rnd.uniform(-16, 16)), 6, 6)


def thumbnail(opts: dict, w=120, h=96, bg="#FAF8FF") -> QPixmap:
    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(QColor(bg))
    p = QPainter(pm)
    draw_face(p, w, h, still(), opts)
    p.end()
    return pm


def app_icon(size: int = 256, color: str | None = None) -> QPixmap:
    """앱 아이콘: 둥근 네모 안에서 퍼플루가 아래에서 쏙 올라온 모습 (작업 표시줄·바로가기)."""
    color = color or config.settings().get("color") or "#8B5CF6"
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = size * 0.22
    tile = QRectF(size * 0.03, size * 0.03, size * 0.94, size * 0.94)
    clip = QPainterPath()
    clip.addRoundedRect(tile, r, r)
    p.setClipPath(clip)
    g = QLinearGradient(0, 0, 0, size)
    g.setColorAt(0, QColor("#FFFFFF"))
    g.setColorAt(1, QColor(color).lighter(185))
    p.fillRect(tile, g)
    z = 1.75   # 크게 당겨서 (양옆은 잘려도) 눈이 작은 아이콘에서도 잘 보이게
    w = tile.width() * z
    h = w * 390 / 884 / 0.95
    p.translate(tile.x() - (w - tile.width()) / 2, tile.bottom() - h + size * 0.02)
    draw_face(p, w, h, still(), options(hat="none", antenna="none", extra="none"), base=color)
    p.end()
    return pm


def save_icon_file(path, color: str | None = None):
    """여러 크기가 든 .ico 파일 (바로가기·작업 표시줄용)."""
    import io
    from PIL import Image
    from PySide6.QtCore import QBuffer, QByteArray
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    app_icon(256, color).save(buf, "PNG")
    img = Image.open(io.BytesIO(bytes(ba)))
    img.save(str(path), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
