"""단축키. 전역 후킹 대신 키 상태를 50번/초 확인한다 (관리자 권한·후킹 불필요)."""
import ctypes
import threading
import time

VK = {f"f{i}": 0x6F + i for i in range(1, 25)}
VK.update({"scrolllock": 0x91, "pause": 0x13, "insert": 0x2D, "capslock": 0x14,
           "ctrl": 0x11, "alt": 0x12, "shift": 0x10})
VK.update({chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)})


def watch(keys: str, on_down, on_up=None):
    """keys: 'f9' 또는 'ctrl+alt+s'. 누를 때 on_down, 뗄 때 on_up."""
    try:
        vks = [VK[k.strip().lower()] for k in keys.split("+")]
    except KeyError:
        raise ValueError(f"지원하지 않는 키: {keys}") from None
    state = ctypes.windll.user32.GetAsyncKeyState

    def loop():
        was = False
        while True:
            down = all(state(vk) & 0x8000 for vk in vks)
            if down != was:
                fn = on_down if down else on_up
                if fn:
                    fn()
                was = down
            time.sleep(0.02)

    threading.Thread(target=loop, daemon=True, name=f"purplu-key-{keys}").start()
