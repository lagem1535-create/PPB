"""작업 중 표시: 퍼플루가 PC 앱(계산기 등)을 조작하는 동안 그 창 둘레에 빛나는 테두리 (글자 없이 색만).

클릭은 통과하고(조작을 막지 않게), 앞 창을 따라다닌다. 브라우저는 확장이 따로 표시하므로 여기서는 건너뛴다.
설정: work_indicator(켜기), work_indicator_color(비우면 퍼플루 색)
"""
import ctypes
import os
from ctypes import wintypes

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import browser, config

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x20, 0x80000, 0x08000000, 0x80
SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
BROWSERS = {"chrome.exe", "whale.exe", "msedge.exe", "opera.exe", "brave.exe"}
PAD = 14
LINGER_MS = 1500


def _proc_name(hwnd) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil
        return psutil.Process(pid.value).name().lower(), pid.value
    except Exception:
        return "", pid.value


def _window_rect(hwnd):
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:  # 그림자 뺀 실제 크기
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


class WorkFrame(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.label = "퍼플루가 사용 중"
        self.app_name = ""
        self._phase = 0.0
        self._follow = QTimer(self, timeout=self._track)
        self._off = QTimer(self, singleShot=True, timeout=self._hide_now)

    def color(self) -> QColor:
        s = config.settings()
        return QColor(s.get("work_indicator_color") or s.get("color") or "#3B82F6")

    # ---- 켜고 끄기 ----
    def start(self, label: str = ""):
        if not config.settings().get("work_indicator", True):
            return
        self._off.stop()
        if label:
            self.label = label
        if not self._follow.isActive():
            self._follow.start(120)
        self._track()

    def stop(self):
        if self._follow.isActive() or self.isVisible():
            self._off.start(LINGER_MS)  # 다음 동작이 곧 오면 계속 켜 둔다

    def _hide_now(self):
        self._follow.stop()
        self.hide()

    # ---- 앞 창 따라가기 ----
    def _track(self):
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        name, pid = _proc_name(hwnd)
        if cls.value in SKIP_CLASSES or pid == os.getpid() or (name in BROWSERS and browser.connected()):
            self.hide()  # 바탕화면·퍼플루 자신·확장이 따로 표시하는 브라우저
            return
        self.app_name = name.replace(".exe", "")
        l, t, r, b = _window_rect(hwnd)
        dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        x, y, w, h = l / dpr - PAD, t / dpr - PAD, (r - l) / dpr + PAD * 2, (b - t) / dpr + PAD * 2
        if w < 80 or h < 80:
            return
        self.setGeometry(int(x), int(y), int(w), int(h))
        self._phase += 0.12
        if not self.isVisible():
            self.show()
            self._click_through()
        self.update()

    def _click_through(self):
        hwnd = int(self.winId())
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                              | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)

    def paintEvent(self, _):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.color()
        pulse = 0.65 + 0.35 * (0.5 + 0.5 * math.sin(self._phase * 2.2))
        frame = QRectF(PAD / 2, PAD / 2, self.width() - PAD, self.height() - PAD)
        for i, (width, alpha) in enumerate(((14, 40), (8, 80), (3, 255))):  # 바깥쪽부터 은은한 빛 → 선명한 선
            col = QColor(c)
            col.setAlpha(int(alpha * pulse))
            p.setPen(QPen(col, width))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(frame, 12, 12)
        p.end()
