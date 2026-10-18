"""앱 열기 / 사이트 열기."""
import json
import os
import re
import subprocess
import threading
import time
import webbrowser
from difflib import SequenceMatcher
from pathlib import Path

from .. import trace

# 한글로 부르는 이름 → 시작 메뉴에 있는 영어 이름
ALIASES = {
    "크롬": "chrome", "구글 크롬": "chrome", "엣지": "edge", "파이어폭스": "firefox", "웨일": "whale",
    "메모장": "notepad", "계산기": "calculator", "그림판": "paint", "탐색기": "file explorer",
    "파일 탐색기": "file explorer", "설정": "settings", "작업 관리자": "task manager",
    "명령 프롬프트": "command prompt", "터미널": "terminal", "파워쉘": "powershell",
    "카톡": "kakaotalk", "카카오톡": "kakaotalk", "디스코드": "discord", "슬랙": "slack",
    "줌": "zoom", "팀즈": "teams", "스포티파이": "spotify", "스팀": "steam",
    "워드": "word", "엑셀": "excel", "파워포인트": "powerpoint", "아웃룩": "outlook",
    "한글": "hwp", "한컴": "hwp", "비주얼 스튜디오 코드": "visual studio code", "브이에스코드": "visual studio code",
    "vs code": "visual studio code", "vscode": "visual studio code", "클로드": "claude",
}

# 시작 메뉴에 바로가기가 없는 기본 앱들
BUILTIN = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "paint": "mspaint.exe",
    "file explorer": "explorer.exe", "settings": "ms-settings:", "task manager": "taskmgr.exe",
    "command prompt": "cmd.exe", "powershell": "powershell.exe", "terminal": "wt.exe",
}

SITES = {
    "유튜브": "https://www.youtube.com", "네이버": "https://www.naver.com", "구글": "https://www.google.com",
    "지메일": "https://mail.google.com", "깃허브": "https://github.com", "다음": "https://www.daum.net",
    "넷플릭스": "https://www.netflix.com", "쿠팡": "https://www.coupang.com",
}

_START_MENUS = [
    Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]
_apps: dict[str, str] | None = None
_lock = threading.Lock()


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-.]+", " ", s.lower()).strip()


def _start_apps() -> dict[str, str]:
    """Windows 시작 앱 목록(스토어 앱 포함) → 'shell:AppsFolder\\<AppID>'."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        rows = json.loads(r.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    return {_norm(row["Name"]): "shell:AppsFolder\\" + row["AppID"] for row in rows if row.get("AppID")}


def _shortcuts() -> dict[str, str]:
    found = {}
    for root in _START_MENUS:
        if root.is_dir():
            for p in root.rglob("*"):
                if p.suffix.lower() in (".lnk", ".url", ".appref-ms"):
                    found.setdefault(_norm(p.stem), str(p))
    return found


def all_apps() -> dict[str, str]:
    """이름 → 실행 대상. 처음 한 번 모으고 기억한다 (시작할 때 미리 불러두면 빠름)."""
    global _apps
    with _lock:
        if _apps is None:
            apps = _shortcuts()
            apps.update(_start_apps())
            _apps = {k: v for k, v in apps.items() if "uninstall" not in k and "제거" not in k}
        return _apps


def find_app(name: str):
    """이름에 가장 잘 맞는 앱 (실행 대상, 이름)을 돌려준다."""
    raw = _norm(name)
    alias = _norm(ALIASES.get(raw, raw))
    apps = all_apps()
    for w in (raw, alias):
        if w in apps:
            return apps[w], w
    if alias in BUILTIN:
        return BUILTIN[alias], alias
    best, best_score = None, 0.0
    for label, target in apps.items():
        for w in {raw, alias}:
            score = SequenceMatcher(None, w, label).ratio()
            if w in label.split() or label.startswith(w):
                score += 0.5
            elif w in label:
                score += 0.3
            if score > best_score:
                best, best_score = (target, label), score
    return best if best and best_score >= 0.6 else None


def open_app(name: str) -> dict:
    hit = find_app(name)
    if not hit:
        return {"ok": False, "error": f"'{name}' 앱을 못 찾았어요."}
    target, label = hit
    try:
        if target.startswith("shell:"):
            trace.cmd(f'explorer.exe "{target}"')
            subprocess.Popen(["explorer.exe", target])
        else:
            trace.cmd(f'os.startfile(r"{target}")')
            os.startfile(target)
    except OSError as e:
        return {"ok": False, "error": f"'{label}'을(를) 여는 데 실패했어요: {e}"}
    _wait_for_new_window()
    return {"ok": True, "opened": label, "note": "창이 앞에 떴어. 바로 조작해도 돼."}


def _wait_for_new_window(limit=2.0):
    """앞 창이 바뀔 때까지만 기다린다 (최대 limit초). 예전처럼 무조건 1.5초 쉬지 않는다."""
    import ctypes
    user32 = ctypes.windll.user32
    before = user32.GetForegroundWindow()
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        time.sleep(0.05)
        hwnd = user32.GetForegroundWindow()
        if hwnd and hwnd != before:
            time.sleep(0.8)  # 창 안 내용(버튼 등)이 그려질 시간
            return


def open_url(url: str) -> dict:
    url = url.strip()
    url = SITES.get(url, url)
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        if " " in url or "." not in url:
            return {"ok": False, "error": "주소가 아니에요. 검색이 필요하면 web_research를 쓰세요."}
        url = "https://" + url
    if not url.lower().startswith(("http://", "https://")):
        return {"ok": False, "error": "http/https 주소만 열 수 있어요."}
    trace.cmd(f'webbrowser.open("{url}")')
    webbrowser.open(url)
    return {"ok": True, "opened": url}
