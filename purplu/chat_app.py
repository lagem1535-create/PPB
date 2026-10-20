"""PC 대화창 전용 프로그램 (퍼플루와 따로 돈다).

웹 엔진(Qt WebEngine)이 가끔 스스로 죽어서 퍼플루 전체가 꺼지던 문제 때문에 따로 떼어 냈다.
대화창이 죽어도 퍼플루는 계속 돌고, 필요하면 대화창만 다시 켠다.

퍼플루 → 대화창 (표준 입력 한 줄씩): show / show_quiet / hide / pin / autohide
대화창 → 퍼플루 (표준 출력 한 줄씩): geom 왼쪽 위 너비 높이 보이는지(1/0)
"""
import os
import sys
import threading

# 그래픽 카드 쪽 문제로 죽는 일을 줄인다 (대화창엔 소프트웨어 그리기로 충분)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing")

import PySide6.QtWebEngineWidgets  # noqa: E402,F401  QApplication보다 먼저
from PySide6.QtCore import QObject, QTimer, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from . import config  # noqa: E402
from .chatwindow import ChatWindow  # noqa: E402


class _Pipe(QObject):
    command = Signal(str)


def main():
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)
    qt = QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)
    config.load()
    w = ChatWindow()
    pipe = _Pipe()

    def run(cmd: str):
        if cmd == "show":
            w.open(activate=True)
        elif cmd == "show_quiet":
            w.open(activate=False)
        elif cmd == "hide":
            w.hide()
        elif cmd == "pin":
            config.load()
            w.apply_pin()
        elif cmd == "autohide":
            config.load()
            w.auto_hide()
        elif cmd == "quit":
            qt.quit()
    pipe.command.connect(run)

    def read_stdin():  # 퍼플루가 꺼지면(입력이 끊기면) 대화창도 같이 끝난다
        for line in sys.stdin:
            pipe.command.emit(line.strip())
        pipe.command.emit("quit")
    threading.Thread(target=read_stdin, daemon=True).start()

    def report():
        g = w.frameGeometry()
        try:
            print(f"geom {g.left()} {g.top()} {g.width()} {g.height()} {1 if w.isVisible() else 0}", flush=True)
        except Exception:
            qt.quit()
    QTimer(qt, timeout=report).start(500)
    for cmd in sys.argv[1:]:
        run(cmd)
    sys.exit(qt.exec())


if __name__ == "__main__":
    main()
