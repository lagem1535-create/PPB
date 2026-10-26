"""PC 화면 포스트잇: 퍼플루가 남긴 메모 중 '붙이기'인 것들을 화면 오른쪽 위에 띄운다.

메모는 Firebase에 있으니 탭이나 다른 PC에서 지우거나 떼면 여기서도 바로 사라진다.
끌어서 옮길 수 있고, 📌 = 떼기(메모는 남김), 🗑 = 지우기.
"""
import html
from datetime import datetime

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import config, store


def _when(ms) -> str:
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%m/%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


class StickyNote(QWidget):
    unpin = Signal(str)
    remove = Signal(str)

    def __init__(self, memo: dict):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.memo_id = memo["id"]
        self.setFixedWidth(260)
        head = QLabel(f"📝 퍼플루 메모 · {_when(memo.get('created'))}")
        head.setStyleSheet("color:#4C1D95; font-weight:700; font-size:9pt;")
        pin = QPushButton("📌")
        pin.setToolTip("화면에서 떼기 (메모는 남아요)")
        trash = QPushButton("🗑")
        trash.setToolTip("메모 지우기")
        for b in (pin, trash):
            b.setFixedSize(26, 24)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QPushButton{background:transparent;border:none;font-size:11pt}"
                            "QPushButton:hover{background:rgba(0,0,0,.08);border-radius:6px}")
        pin.clicked.connect(lambda: self.unpin.emit(self.memo_id))
        trash.clicked.connect(lambda: self.remove.emit(self.memo_id))
        top = QHBoxLayout()
        top.addWidget(head, 1)
        top.addWidget(pin)
        top.addWidget(trash)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setStyleSheet("color:#1F1235; font-size:10.5pt;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 14)
        lay.addLayout(top)
        lay.addWidget(self.body)
        self.setFont(QFont("Malgun Gothic", 10))
        self._drag = None
        self.moved = False
        self.set_text(memo.get("text", ""))

    def set_text(self, text: str):
        self.body.setText(html.escape(text).replace("\n", "<br>"))
        self.adjustSize()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base = QColor(config.settings().get("color") or "#8B5CF6")
        paper = QColor.fromHsv(base.hsvHue(), 40, 255)  # 퍼플루 색을 아주 연하게 → 포스트잇 종이
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRoundedRect(rect.translated(2, 3), 12, 12)
        p.setBrush(paper)
        p.setPen(QPen(base.lighter(120), 1.5))
        p.drawRoundedRect(rect, 12, 12)
        p.setPen(Qt.NoPen)
        p.setBrush(base)
        p.drawRoundedRect(QRectF(rect.left() + 12, rect.top() - 1, 46, 7), 3, 3)  # 테이프

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)
            self.moved = True

    def mouseReleaseEvent(self, e):
        self._drag = None


class MemoBoard:
    """Firebase 메모 목록과 화면 포스트잇을 맞춘다. refresh()는 UI 스레드에서."""

    def __init__(self):
        self.notes: dict[str, StickyNote] = {}

    def refresh(self, rows: list[dict] | None = None):
        if rows is None:
            try:
                rows = store.list_memos()
            except Exception as e:
                print("메모 불러오기 실패:", e)
                return
        pinned = {r["id"]: r for r in rows if r.get("pinned")}
        for mid in list(self.notes):
            if mid not in pinned:
                self.notes.pop(mid).close()
        for mid, r in pinned.items():
            if mid in self.notes:
                self.notes[mid].set_text(r.get("text", ""))
            else:
                n = StickyNote(r)
                n.unpin.connect(lambda m: store.in_background(store.update_memo, m, pinned=False) or self._drop(m))
                n.remove.connect(lambda m: store.in_background(store.delete_memo, m) or self._drop(m))
                self.notes[mid] = n
                n.show()
        self._stack()

    def _drop(self, mid: str):
        if mid in self.notes:
            self.notes.pop(mid).close()
        self._stack()

    def _stack(self):
        """새 메모가 위로 오게 화면 오른쪽 위부터 쌓는다."""
        area = QGuiApplication.primaryScreen().availableGeometry()
        y = area.top() + 16
        for n in reversed(list(self.notes.values())):
            if n.moved:
                continue
            n.move(QPoint(area.right() - n.width() - 16, y))
            y += n.height() + 10

    def repaint_all(self):
        for n in self.notes.values():
            n.update()
