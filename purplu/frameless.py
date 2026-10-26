"""테두리 없는 창 (윈도우 위 줄 _ ㅁ X 없이) 을 쓰기 편하게.

- 가장자리 6px: 커서가 ↔ 로 바뀌고, 끌면 크기가 바뀐다 (안쪽 위젯이 덮고 있어도)
- 빈 곳을 끌면 옮겨진다 (화면 끝에 대면 반으로 나누기도 된다)
- Windows 11 둥근 모서리
쓰는 법: Frameless(창, can_resize=lambda: True)
"""
import ctypes

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

EDGE = 6
_CURSOR = {Qt.LeftEdge: Qt.SizeHorCursor, Qt.RightEdge: Qt.SizeHorCursor,
           Qt.TopEdge: Qt.SizeVerCursor, Qt.BottomEdge: Qt.SizeVerCursor}


def round_corners(w):
    try:
        pref = ctypes.c_int(2)   # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(w.winId()), 33, ctypes.byref(pref), 4)
    except Exception:
        pass


class Frameless(QObject):
    def __init__(self, win, can_resize=lambda: True, can_move=lambda: True):
        super().__init__(win)
        self.win, self.can_resize, self.can_move = win, can_resize, can_move
        self._cursor_on = False
        QApplication.instance().installEventFilter(self)

    def _edges(self, gpos):
        if not self.can_resize() or self.win.isMaximized():
            return Qt.Edges()
        g = self.win.frameGeometry()
        x, y = gpos.x() - g.left(), gpos.y() - g.top()
        e = Qt.Edges()
        if 0 <= y <= g.height():
            if x <= EDGE:
                e |= Qt.LeftEdge
            elif x >= g.width() - EDGE:
                e |= Qt.RightEdge
        if 0 <= x <= g.width():
            if y <= EDGE:
                e |= Qt.TopEdge
            elif y >= g.height() - EDGE:
                e |= Qt.BottomEdge
        return e

    def _set_cursor(self, edges):
        if not edges:
            if self._cursor_on:
                QApplication.restoreOverrideCursor()
                self._cursor_on = False
            return
        if (edges & (Qt.LeftEdge | Qt.RightEdge)) and (edges & (Qt.TopEdge | Qt.BottomEdge)):
            diag = bool(edges & Qt.LeftEdge) == bool(edges & Qt.TopEdge)
            cur = Qt.SizeFDiagCursor if diag else Qt.SizeBDiagCursor
        else:
            cur = next(c for k, c in _CURSOR.items() if edges & k)
        if self._cursor_on:
            QApplication.changeOverrideCursor(cur)
        else:
            QApplication.setOverrideCursor(cur)
            self._cursor_on = True

    def eventFilter(self, obj, e):
        t = e.type()
        if t not in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.Leave):
            return False
        try:
            mine = hasattr(obj, "window") and obj.window() is self.win and self.win.isVisible()
        except RuntimeError:
            return False
        if not mine:
            if t == QEvent.MouseMove and self._cursor_on:
                self._set_cursor(Qt.Edges())
            return False
        if t == QEvent.Leave:
            if obj is self.win:
                self._set_cursor(Qt.Edges())
            return False
        edges = self._edges(QCursor.pos())
        if t == QEvent.MouseMove and not (e.buttons() & Qt.LeftButton):
            self._set_cursor(edges)
            return False
        if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton and edges and self.win.windowHandle():
            self._set_cursor(Qt.Edges())
            self.win.windowHandle().startSystemResize(edges)
            return True
        return False

    def drag(self, e) -> bool:
        """창의 mousePressEvent 에서 부른다: 빈 곳을 누르면 옮기기 시작."""
        if e.button() == Qt.LeftButton and self.can_move() and self.win.windowHandle():
            self.win.windowHandle().startSystemMove()
            return True
        return False
