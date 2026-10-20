"""PC 대화창: 탭·웹과 똑같은 대화창을 퍼플루 앱 안에서 연다 (브라우저 없이).

같은 대화로 이어지고, 🎤를 꾹 누르면 PC 마이크로 말할 수도 있다.
"""
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


class ChatWindow(QWidget):
    def __init__(self, icon: QIcon | None = None):
        super().__init__()
        self.setWindowTitle("퍼플루 대화")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)   # 다른 창 위에 떠 있게
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
        if url.fragment().startswith("close"):  # 대화창의 ✕
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
