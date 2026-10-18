"""볼륨·음악 제어와 클립보드."""
import ctypes
import time

import win32clipboard
import win32con

from .. import trace

user32 = ctypes.windll.user32
MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}


def _endpoint():
    import comtypes
    from pycaw.pycaw import AudioUtilities
    comtypes.CoInitialize()
    return AudioUtilities.GetSpeakers().EndpointVolume


def _tap(vk: int):
    trace.cmd(f"keybd_event(0x{vk:X})  # 미디어 키")
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)


def media_control(action: str, level: float | None = None) -> dict:
    """action: volume_set(level 0~100) / volume_up / volume_down / mute / unmute / play_pause / next / previous / stop"""
    action = (action or "").strip().lower()
    if action in MEDIA_KEYS:
        _tap(MEDIA_KEYS[action])
        return {"ok": True, "done": action}
    try:
        vol = _endpoint()
    except Exception as e:
        return {"ok": False, "error": f"소리 장치를 못 찾았어요: {e}"}
    trace.cmd("pycaw IAudioEndpointVolume.GetMasterVolumeLevelScalar()")
    now = round(vol.GetMasterVolumeLevelScalar() * 100)
    if action == "volume_set":
        if level is None:
            return {"ok": False, "error": "level(0~100)이 필요해요."}
        new = max(0, min(100, float(level)))
    elif action == "volume_up":
        new = min(100, now + (float(level) if level else 10))
    elif action == "volume_down":
        new = max(0, now - (float(level) if level else 10))
    elif action in ("mute", "unmute"):
        trace.cmd(f"pycaw IAudioEndpointVolume.SetMute({action == 'mute'})")
        vol.SetMute(1 if action == "mute" else 0, None)
        return {"ok": True, "muted": action == "mute", "volume": now}
    elif action == "status":
        return {"ok": True, "volume": now, "muted": bool(vol.GetMute())}
    else:
        return {"ok": False, "error": f"모르는 동작: {action}"}
    vol.SetMute(0, None)
    trace.cmd(f"pycaw IAudioEndpointVolume.SetMasterVolumeLevelScalar({new / 100:.2f})")
    vol.SetMasterVolumeLevelScalar(new / 100, None)
    return {"ok": True, "volume": round(new), "before": now}


def read_clipboard() -> dict:
    for _ in range(5):  # 다른 프로그램이 잡고 있으면 잠깐 기다렸다 다시
        try:
            win32clipboard.OpenClipboard()
            break
        except Exception:
            time.sleep(0.1)
    else:
        return {"ok": False, "error": "클립보드를 열 수 없어요."}
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            trace.cmd("win32clipboard.GetClipboardData(CF_UNICODETEXT)")
            text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            return {"ok": True, "text": text[:8000], "truncated": len(text) > 8000}
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
            files = win32clipboard.GetClipboardData(win32con.CF_HDROP)
            return {"ok": True, "files": list(files)[:20]}
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
            return {"ok": True, "note": "복사한 건 그림이에요. 화면에 보이면 look_at_screen으로 볼 수 있어요."}
        return {"ok": True, "text": "", "note": "클립보드가 비어 있어요."}
    finally:
        win32clipboard.CloseClipboard()


def write_clipboard(text: str) -> dict:
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            break
        except Exception:
            time.sleep(0.1)
    else:
        return {"ok": False, "error": "클립보드를 열 수 없어요."}
    try:
        win32clipboard.EmptyClipboard()
        trace.cmd(f"win32clipboard.SetClipboardData(CF_UNICODETEXT, {len(text)}자)")
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()
    return {"ok": True, "copied_chars": len(text), "note": "이제 Ctrl+V로 붙여넣을 수 있어요."}
