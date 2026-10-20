"""퍼플루 쪽에서 PC 대화창 프로그램(chat_app.py)을 켜고 부리는 곳.

대화창은 따로 도는 프로그램이라, 웹 엔진이 죽어도 퍼플루는 안 꺼진다. 죽었으면 다음에 부를 때 다시 켠다.
"""
import subprocess
import sys
import threading

from PySide6.QtCore import QRect

from . import config


class ChatProcess:
    def __init__(self):
        self._p = None
        self._geom = None      # 대화창 자리 (보일 때만)
        self._lock = threading.Lock()

    def _alive(self) -> bool:
        return self._p is not None and self._p.poll() is None

    def _ensure(self):
        with self._lock:
            if self._alive():
                return
            exe = sys.executable.replace("pythonw.exe", "python.exe") if sys.executable.endswith("pythonw.exe") else sys.executable
            self._p = subprocess.Popen([exe, "-m", "purplu.chat_app"], cwd=str(config.BASE_DIR),
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       text=True, encoding="utf-8", bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
            threading.Thread(target=self._read, args=(self._p,), daemon=True).start()

    def _read(self, p):
        for line in p.stdout:
            parts = line.split()
            if len(parts) == 6 and parts[0] == "geom":
                l, t, w, h, vis = map(int, parts[1:])
                self._geom = QRect(l, t, w, h) if vis else None
        self._geom = None
        code = p.wait()
        if code not in (0, None) and p is self._p:
            print(f"PC 대화창이 꺼졌어요 (코드 {code}) — 퍼플루는 그대로, 대화창만 다시 켜요")
            import time
            time.sleep(1)
            if config.settings().get("pc_chat_pinned"):   # 고정해 둔 대화창이면 바로 다시
                self._send("show_quiet")
                self._send("pin")

    def _send(self, cmd: str):
        self._ensure()
        try:
            self._p.stdin.write(cmd + "\n")
            self._p.stdin.flush()
        except (OSError, ValueError):  # 방금 죽었으면 한 번 더 켜서
            self._p = None
            self._ensure()
            self._p.stdin.write(cmd + "\n")
            self._p.stdin.flush()

    # ---- 예전 대화창과 같은 이름으로 ----
    def open(self, activate: bool = True):
        self._send("show" if activate else "show_quiet")

    def apply_pin(self):
        self._send("pin")

    def apply_settings(self):
        if self._alive():
            self._send("settings")

    def auto_hide(self):
        if self._alive():
            self._send("autohide")

    def isVisible(self) -> bool:
        return self._alive() and self._geom is not None

    def frameGeometry(self):
        return self._geom

    def close(self):
        if self._alive():
            p = self._p
            try:
                self._send("quit")
            except Exception:
                pass
            threading.Timer(2.0, lambda: p.poll() is None and p.terminate()).start()  # 안 닫히면 2초 뒤 확실히
