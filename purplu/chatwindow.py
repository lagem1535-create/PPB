"""PC 대화창: 탭·웹과 똑같은 대화창을 퍼플루 앱 안에서 연다 (브라우저 없이).

같은 대화로 이어지고, 🎤를 꾹 누르면 PC 마이크로 말할 수도 있다.
"""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from . import config


class _Page(QWebEnginePage):
    """이 PC의 퍼플루 화면이니 마이크 권한은 바로 허락 (다른 사이트로는 못 나간다)."""

    def __init__(self, profile, parent):
        super().__init__(profile, parent)
        if hasattr(self, "permissionRequested"):  # PySide6 6.8+
            self.permissionRequested.connect(lambda perm: perm.grant() if self._local(perm.origin()) else perm.deny())
        self.featurePermissionRequested.connect(self._feature)

    @staticmethod
    def _local(url: QUrl) -> bool:
        return url.host() in ("localhost", "127.0.0.1")

    def _feature(self, origin, feature):
        ok = self._local(origin)
        self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionGrantedByUser if ok
                                  else QWebEnginePage.PermissionDeniedByUser)

    def acceptNavigationRequest(self, url, nav_type, is_main):
        if is_main and not self._local(url):  # 대화창 안의 링크는 기본 브라우저로
            import webbrowser
            webbrowser.open(url.toString())
            return False
        return True


class _APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uCallbackMessage", wintypes.UINT),
                ("uEdge", wintypes.UINT), ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]


ABM_NEW, ABM_REMOVE, ABM_QUERYPOS, ABM_SETPOS, ABE_RIGHT = 0, 1, 2, 3, 2


class ChatWindow(QWidget):
    def __init__(self, icon: QIcon | None = None):
        super().__init__()
        self.setWindowTitle("퍼플루 대화")
        self._appbar = False
        self.apply_on_top()
        if icon:
            self.setWindowIcon(icon)
        self.resize(480, 760)
        profile = QWebEngineProfile("purplu-chat", self)  # 설정(대화창 모양 등)을 기억하는 저장 공간
        self.view = QWebEngineView(self)
        self.view.setPage(_Page(profile, self.view))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self._loaded = False
        self._placed = False
        self.view.urlChanged.connect(self._url_changed)

    def _url_changed(self, url: QUrl):
        frag = url.fragment()
        if frag.startswith("close"):  # 대화창의 ✕
            config.save_settings(pc_chat_pinned=False)
            self.hide()
        elif frag.startswith("pin"):  # 📌 고정 켜기/끄기
            config.save_settings(pc_chat_pinned=not config.settings().get("pc_chat_pinned", False))

    def apply_on_top(self):
        """설정 '언제나 맨 위로'."""
        on_top = config.settings().get("pc_chat_on_top", True)
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on_top))
        if visible:
            self.show()

    def apply_pin(self):
        """고정이면 화면 오른쪽에 붙여 늘 보이게. '자리 차지'가 켜져 있으면 작업 표시줄처럼 그만큼 다른 창이 작아진다."""
        s = config.settings()
        if not s.get("pc_chat_pinned"):
            self._release_space()
            return
        if s.get("pc_chat_dock", True):
            self.open(activate=False)
            self._reserve_space()
        else:
            self._release_space()
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(440, area.height() - 60)
            self.move(area.right() - self.width() - 8, area.top() + 20)
            self._placed = True
            self.open(activate=False)

    # ---- 자리 차지 (Windows 앱바: 최대화한 창도 이 자리는 비워 둔다) ----
    def _bar(self) -> _APPBARDATA:
        d = _APPBARDATA()
        d.cbSize = ctypes.sizeof(d)
        d.hWnd = int(self.winId())
        return d

    def _reserve_space(self):
        shell = ctypes.windll.shell32
        scr = QGuiApplication.primaryScreen()
        dpr = scr.devicePixelRatio()
        full = scr.geometry()   # 모니터 전체 (논리 좌표)
        width_px = int(440 * dpr)
        d = self._bar()
        if not self._appbar:
            d.uCallbackMessage = 0x0400 + 77
            shell.SHAppBarMessage(ABM_NEW, ctypes.byref(d))
            self._appbar = True
        d.uEdge = ABE_RIGHT
        d.rc.top, d.rc.bottom = int(full.top() * dpr), int(full.bottom() * dpr) + 1
        d.rc.right = int((full.right() + 1) * dpr)
        d.rc.left = d.rc.right - width_px
        shell.SHAppBarMessage(ABM_QUERYPOS, ctypes.byref(d))   # 작업 표시줄 등과 겹치지 않게 Windows가 고쳐 준다
        d.rc.left = d.rc.right - width_px
        shell.SHAppBarMessage(ABM_SETPOS, ctypes.byref(d))
        # 정해진 자리로 창 옮기기 (작업 표시줄 위까지)
        avail = scr.availableGeometry()
        self.setGeometry(int(d.rc.left / dpr), avail.top(), int(width_px / dpr), avail.height())
        self._placed = True

    def _release_space(self):
        if self._appbar:
            ctypes.windll.shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(self._bar()))
            self._appbar = False

    def closeEvent(self, e):
        self._release_space()
        super().closeEvent(e)

    def hideEvent(self, e):
        self._release_space()   # 숨기면 자리를 돌려준다
        super().hideEvent(e)

    def auto_hide(self):
        """설정한 초가 지나면 숨기기 (고정이거나, 사용자가 대화창에서 쓰는 중이면 안 숨김)."""
        if config.settings().get("pc_chat_pinned") or self.isActiveWindow():
            return
        self.hide()

    def _place(self):
        """처음엔 화면 오른쪽 아래(작업 표시줄 위)에."""
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(440, min(700, area.height() - 40))
        self.move(area.right() - self.width() - 16, area.bottom() - self.height() - 40)
        self._placed = True

    def open(self, activate: bool = True):
        if not self._loaded:
            port = config.settings()["tablet_port"]
            self.view.load(QUrl(f"http://localhost:{port}/?view=chat"))
            self._loaded = True
        if not self._placed:
            self._place()
        if activate:
            self.show()
            self.raise_()
            self.activateWindow()
        elif not self.isVisible():
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)   # 말할 때 뜨더라도 하던 일을 빼앗지 않게
            self.show()
            self.setAttribute(Qt.WA_ShowWithoutActivating, False)
