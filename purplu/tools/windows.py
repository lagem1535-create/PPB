"""Windows 기본 기능: 배터리·시스템 상태, 화면 밝기, 다크 모드, 잠금·절전·끄기, 설정 페이지, 스크린샷, 열린 창 다루기."""
import ctypes
import os
import shutil
import subprocess
import time
import winreg
from datetime import datetime

import mss
import psutil
from PIL import Image

from .. import config, trace

user32 = ctypes.windll.user32
NO_WINDOW = subprocess.CREATE_NO_WINDOW

SETTINGS_PAGES = {
    "디스플레이": "display", "소리": "sound", "블루투스": "bluetooth", "와이파이": "network-wifi", "네트워크": "network",
    "배터리": "batterysaver", "전원": "powersleep", "업데이트": "windowsupdate", "앱": "appsfeatures", "개인 설정": "personalization",
    "배경": "personalization-background", "색": "colors", "알림": "notifications", "저장소": "storagesense", "마우스": "mousetouchpad",
    "키보드": "typing", "언어": "regionlanguage", "시간": "dateandtime", "프린터": "printers", "방해 금지": "quiethours",
    "야간 모드": "nightlight", "개인정보": "privacy", "정보": "about",
}


def _ps(cmd: str, timeout=15) -> str:
    trace.cmd(f"powershell -NoProfile -Command \"{cmd[:120]}\"")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, creationflags=NO_WINDOW)
    return (r.stdout or "").strip()


def _wifi() -> dict:
    try:
        trace.cmd("netsh wlan show interfaces")
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True,
                             encoding="cp949", errors="replace", timeout=8, creationflags=NO_WINDOW).stdout
    except Exception:
        return {}
    info = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        kl = k.lower()
        if kl in ("ssid", "상태", "state"):
            info["ssid" if kl == "ssid" else "state"] = v
        elif kl in ("신호", "signal"):
            info["signal"] = v
    return info


def system_status() -> dict:
    """배터리, CPU, 메모리, 디스크, 와이파이, 켜진 시간."""
    trace.cmd("psutil.sensors_battery(), cpu_percent(), virtual_memory(), disk_usage()")
    b = psutil.sensors_battery()
    battery = ({"percent": round(b.percent), "charging": bool(b.power_plugged),
                "minutes_left": (b.secsleft // 60 if b.secsleft and b.secsleft > 0 and not b.power_plugged else None)}
               if b else "배터리 없음 (데스크톱)")
    mem = psutil.virtual_memory()
    disks = {}
    for d in ("C:\\", "D:\\"):
        if os.path.exists(d):
            u = shutil.disk_usage(d)
            disks[d[0]] = {"free_gb": round(u.free / 2**30, 1), "total_gb": round(u.total / 2**30, 1)}
    top = sorted(psutil.process_iter(["name", "memory_info"]), key=lambda p: (p.info["memory_info"].rss if p.info["memory_info"] else 0),
                 reverse=True)[:5]
    return {"ok": True, "time": datetime.now().strftime("%Y-%m-%d %H:%M (%a)"), "battery": battery,
            "cpu_percent": psutil.cpu_percent(interval=0.4), "memory_percent": round(mem.percent),
            "memory_free_gb": round(mem.available / 2**30, 1), "disks": disks, "wifi": _wifi(),
            "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
            "top_memory_apps": [p.info["name"] for p in top]}


def _windows():
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4):  # 보이고, 주인 창이 없는 것
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                found.append((hwnd, buf.value))
        return True
    user32.EnumWindows(cb, 0)
    return [(h, t) for h, t in found if t not in ("Program Manager", "Windows 입력 환경")]


def windows_action(action: str, value: str = "") -> dict:
    """action: lock / sleep / shutdown / restart / cancel_shutdown / brightness / dark_mode / open_settings /
    screenshot / list_windows / focus_window / minimize_window / close_window / show_desktop / empty_trash_info"""
    a = (action or "").strip().lower()
    if a == "lock":
        trace.cmd("user32.LockWorkStation()")
        user32.LockWorkStation()
        return {"ok": True, "done": "화면 잠금"}
    if a == "sleep":
        trace.cmd("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], creationflags=NO_WINDOW)
        return {"ok": True, "done": "절전 모드"}
    if a in ("shutdown", "restart"):
        secs = int(value) if str(value).isdigit() else 60
        flag = "/s" if a == "shutdown" else "/r"
        trace.cmd(f"shutdown {flag} /t {secs}")
        subprocess.run(["shutdown", flag, "/t", str(secs)], creationflags=NO_WINDOW)
        return {"ok": True, "done": f"{secs}초 뒤 {'꺼짐' if a == 'shutdown' else '다시 시작'}",
                "note": "취소하려면 cancel_shutdown"}
    if a == "cancel_shutdown":
        trace.cmd("shutdown /a")
        subprocess.run(["shutdown", "/a"], creationflags=NO_WINDOW)
        return {"ok": True, "done": "끄기 취소"}
    if a == "brightness":
        try:
            level = max(0, min(100, int(float(value))))
        except ValueError:
            cur = _ps("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness")
            return {"ok": bool(cur), "brightness": cur or "모니터가 밝기 조절을 지원하지 않아요 (데스크톱 모니터는 보통 안 돼요)"}
        _ps(f"(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
            f".WmiSetBrightness(1,{level})")
        return {"ok": True, "done": f"밝기 {level}%", "note": "데스크톱 모니터는 안 바뀔 수 있어요"}
    if a == "dark_mode":
        on = str(value).lower() not in ("off", "false", "0", "끄기", "라이트", "light")
        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        trace.cmd(f"winreg HKCU\\{key} AppsUseLightTheme/SystemUsesLightTheme = {0 if on else 1}")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 0 if on else 1)
        return {"ok": True, "done": "다크 모드 켬" if on else "라이트 모드 켬"}
    if a == "open_settings":
        page = SETTINGS_PAGES.get(value.strip(), value.strip() or "")
        trace.cmd(f'os.startfile("ms-settings:{page}")')
        os.startfile(f"ms-settings:{page}")
        return {"ok": True, "done": f"설정 열기: {value or '처음 화면'}"}
    if a == "screenshot":
        folder = config.DATA_DIR / "screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.png"
        trace.cmd(f"mss.grab(모니터 1) → {path}")
        with mss.mss() as s:
            shot = s.grab(s.monitors[1])
        Image.frombytes("RGB", shot.size, shot.rgb).save(path)
        return {"ok": True, "saved": str(path)}
    if a == "list_windows":
        return {"ok": True, "windows": [t[:60] for _, t in _windows()][:30]}
    if a in ("focus_window", "minimize_window", "close_window"):
        want = value.strip().lower()
        hits = [(h, t) for h, t in _windows() if want and want in t.lower()]
        if not hits:
            return {"ok": False, "error": f"'{value}' 창을 못 찾았어요. list_windows로 이름을 확인해."}
        h, t = hits[0]
        if a == "focus_window":
            trace.cmd(f"SetForegroundWindow('{t[:40]}')")
            user32.ShowWindow(h, 9)
            user32.SetForegroundWindow(h)
        elif a == "minimize_window":
            trace.cmd(f"ShowWindow('{t[:40]}', SW_MINIMIZE)")
            user32.ShowWindow(h, 6)
        else:
            trace.cmd(f"PostMessage('{t[:40]}', WM_CLOSE)  # 저장 안 한 게 있으면 앱이 물어봐요")
            user32.PostMessageW(h, 0x0010, 0, 0)
        return {"ok": True, "done": f"{a}: {t[:50]}"}
    if a == "show_desktop":
        trace.cmd("Shell.Application.ToggleDesktop()")
        _ps("(New-Object -ComObject Shell.Application).ToggleDesktop()")
        return {"ok": True, "done": "바탕화면 보기"}
    return {"ok": False, "error": f"모르는 동작: {action}"}
