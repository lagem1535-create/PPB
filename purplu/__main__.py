"""퍼플루 실행: python -m purplu"""
import ctypes
import os
import sys
import threading
import time
import traceback

# 좌표를 실제 화면 픽셀로 맞추기 위해 가장 먼저 (화면 배율 125%·150%에서도 정확히 클릭)
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

from PySide6.QtWidgets import QApplication  # noqa: E402

from . import config, hotkey, store  # noqa: E402
from .brain import Brain  # noqa: E402
from .server import TabletServer  # noqa: E402
from .tools.apps import all_apps  # noqa: E402
from .ui import App  # noqa: E402


def _setup_log():
    """pythonw로 켜면 콘솔이 없으니 오류를 파일에 남긴다: D:\\bot\\data\\purplu.log"""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        log = open(config.DATA_DIR / "purplu.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    print(f"\n==== 퍼플루 시작 {time.strftime('%Y-%m-%d %H:%M:%S')} ====")
    sys.excepthook = lambda t, v, tb: traceback.print_exception(t, v, tb)
    try:  # 프로그램이 통째로 죽을 때도 어디서 죽었는지 남긴다
        import faulthandler
        faulthandler.enable(open(config.DATA_DIR / "crash.log", "a", encoding="utf-8"), all_threads=True)
    except Exception:
        pass
    threading.excepthook = lambda a: traceback.print_exception(a.exc_type, a.exc_value, a.exc_traceback)


def _already_running() -> bool:
    """두 번 켜면 포트가 겹쳐서 탭 연결이 꼬인다 → 하나만."""
    import win32api
    import win32event
    import winerror
    globals()["_mutex"] = win32event.CreateMutex(None, False, "Purplu.SingleInstance")
    return win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS


def main():
    if _already_running():  # 켜져 있는 퍼플루가 쓰는 파일은 건드리지 않게 먼저 확인
        if not os.environ.get("PURPLU_KEEPER"):
            ctypes.windll.user32.MessageBoxW(None, "퍼플루가 이미 켜져 있어요. 작업 표시줄 트레이를 확인해 주세요.", "퍼플루", 0x40)
        sys.exit(3)  # 지킴이에게 '이미 켜져 있음'을 알린다
    moved = config.migrate_old_data()  # 예전에 C 드라이브 등에 있던 데이터를 data/ 로
    _setup_log()
    if moved:
        print("예전 데이터를 data/ 로 옮김:", len(moved), "개")
    qt = QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)
    config.load()
    app = App(qt, Brain, TabletServer)
    # Firebase 실시간 동기화: 탭·다른 PC에서 바꾼 설정과 대화목록이 바로 반영된다
    def conversations_changed():
        app.bridge.event.emit("conversations_changed", None)
        app.server.broadcast("conversations_changed", None)
    def memos_changed():
        app.bridge.event.emit("memos_changed", None)
        app.server.broadcast("memos_changed", None)
    store.listen(config.apply_remote, conversations_changed, memos_changed)
    threading.Thread(target=all_apps, daemon=True).start()
    if config.get_api_key():
        app.brain.wake()  # 켜자마자 Gemini에 미리 연결 → 첫 말부터 바로 대답  # 앱 목록 미리 불러두기 (몇 초 걸림)

    if config.settings().get("pc_chat_pinned"):  # 고정해 둔 대화창은 켤 때 다시 오른쪽에
        app.open_chat(activate=False)
        app.chat_window.apply_pin()
    hotkey.watch(config.settings()["talk_key"], app.brain.talk_start, app.brain.talk_end)
    hotkey.watch("ctrl+alt+s", lambda: app.bridge.event.emit("stop", None))
    # 원본의 단축키들: 마우스 자리 가리키기 / 커서 항상 보이기 켜고 끄기 / 집으로
    hotkey.watch("ctrl+alt+c", lambda: app.bridge.event.emit("open_chat", None))
    hotkey.watch("ctrl+alt+p", lambda: app.bridge.event.emit("cursor_point", None))
    hotkey.watch("ctrl+alt+h", lambda: app.bridge.event.emit("cursor_toggle", None))
    hotkey.watch("ctrl+alt+d", lambda: app.bridge.event.emit("cursor_home", None))

    sys.exit(qt.exec())


if __name__ == "__main__":
    main()
