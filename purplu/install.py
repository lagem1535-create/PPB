"""설치 도우미: 다른 PC 연결 코드 · 바로가기(아이콘) 만들기.

연결 코드 = "PURPLU-" + base64( {"fb": Firebase 주소, "keys": {...}} )
- Firebase 주소가 같으면 설정·대화목록·메모·스킬이 모든 PC에서 같다 (1단계: 내 PC들 모두 동기화).
- 키를 넣으면 새 PC에서 키를 다시 칠 필요가 없다 (코드를 다른 사람에게 보여 주면 안 됨).
- 이 PC에만 남는 것: MCP 서버(data/mcp.json), 탭 짝 열쇠(data/rtc_key.txt), 브라우저 로그인(data/browser).
"""
import base64
import json
import os
import sys
from pathlib import Path

from . import config

ROOT = Path(__file__).resolve().parent.parent
FB_FILE = config.DATA_DIR / "firebase_url.txt"
ICON_FILE = config.DATA_DIR / "purplu.ico"
AUMID = "Purplu.Companion"   # 작업 표시줄에서 '파이썬'이 아니라 퍼플루로 보이게


def firebase_url() -> str:
    try:
        return FB_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def set_firebase_url(url: str):
    FB_FILE.parent.mkdir(parents=True, exist_ok=True)
    FB_FILE.write_text(url.strip().rstrip("/"), encoding="utf-8")


def make_code(with_keys: bool) -> str:
    from .store import parse
    data = {"fb": parse(firebase_url())[1]}   # 'both|주소' 여도 주소만 (새 PC는 스스로 방식을 고른다)
    if with_keys:
        data["keys"] = {p: config.get_key(p) for p in ("gemini", "anthropic", "openai") if config.get_key(p)}
    raw = json.dumps(data, separators=(",", ":")).encode()
    return "PURPLU-" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def read_code(text: str) -> dict:
    """연결 코드 또는 Firebase 주소를 받아 {"fb":…, "keys":{…}} 로."""
    t = (text or "").strip()
    if not t or t.lower() == "local":   # 비우면 이 PC에만 저장 (Firebase 없이)
        return {"fb": "local", "keys": {}}
    if t.startswith("https://") and "firebase" in t:
        from .store import clean_url
        return {"fb": clean_url(t), "keys": {}}
    if t.upper().startswith("PURPLU-"):
        body = t[7:]
        body += "=" * (-len(body) % 4)
        data = json.loads(base64.urlsafe_b64decode(body.encode()).decode())
        if not str(data.get("fb", "")).startswith("https://"):
            raise ValueError("코드 안에 Firebase 주소가 없어요")
        return {"fb": data["fb"], "keys": data.get("keys") or {}}
    raise ValueError("연결 코드(PURPLU-…) 또는 Firebase 주소(https://…firebasedatabase.app)를 넣어 주세요")


def set_app_id():
    """작업 표시줄에서 퍼플루 아이콘으로 묶이게 (QApplication 만들기 전에)."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)
    except Exception:
        pass


def make_icon(color: str | None = None) -> Path:
    from .face import save_icon_file
    ICON_FILE.parent.mkdir(parents=True, exist_ok=True)
    save_icon_file(ICON_FILE, color)
    return ICON_FILE


def make_shortcuts(desktop=True, start_menu=True) -> list[str]:
    """바탕화면·시작 메뉴에 '퍼플루' 바로가기 (지킴이와 함께 켜기, 퍼플루 아이콘)."""
    import win32com.client
    make_icon()
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pyw.exists():
        pyw = Path(sys.executable).with_name("pythonw.exe")
    shell = win32com.client.Dispatch("WScript.Shell")
    places = []
    if desktop:
        places.append(Path(shell.SpecialFolders("Desktop")))
    if start_menu:
        places.append(Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    made = []
    for folder in places:
        try:
            lnk = shell.CreateShortcut(str(folder / "퍼플루.lnk"))
            lnk.TargetPath = str(pyw)
            lnk.Arguments = "-m purplu.keeper"
            lnk.WorkingDirectory = str(ROOT)
            lnk.IconLocation = str(ICON_FILE)
            lnk.Description = "퍼플루 - 보라색 AI 친구"
            lnk.Save()
            made.append(str(folder / "퍼플루.lnk"))
        except Exception as e:
            print("바로가기 실패:", folder, e)
    return made
