"""설정과 Gemini 키.

- 설정: Firebase(/purplu/settings)에 저장해서 PC와 탭이 같이 쓴다. 오프라인일 땐 로컬 사본.
- Gemini 키: 이 PC의 Windows 자격 증명 관리자에만 저장 (Firebase·파일에 절대 안 올림).
"""
import json
import os
import threading
from pathlib import Path

import keyring

from . import store

APP = "Purplu"
# 모든 데이터는 프로젝트 폴더 안 data/ 에 (C 드라이브를 쓰지 않는다)
BASE_DIR = Path(__file__).resolve().parent.parent          # D:\bot
DATA_DIR = BASE_DIR / "data"
NOTES_DIR = DATA_DIR / "notes"                             # 회의록
PYTHON_DIR = DATA_DIR / "python"                           # 파이썬 작업 폴더
OLD_DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP  # 예전 위치 (C 드라이브)
LOCAL_FILE = DATA_DIR / "settings.json"


def migrate_old_data() -> list[str]:
    """예전 위치(%APPDATA%\\Purplu, D:\\Purplu Notes, D:\\Purplu Python)의 데이터를 data/ 로 옮긴다."""
    import shutil
    moved = []
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for old, new in ((OLD_DATA_DIR, DATA_DIR), (Path(r"D:\Purplu Notes"), NOTES_DIR),
                     (Path(r"D:\Purplu Python"), PYTHON_DIR)):
        if not old.is_dir() or old.resolve() == new.resolve():
            continue
        new.mkdir(parents=True, exist_ok=True)
        for item in old.iterdir():
            target = new / item.name
            if target.exists():
                continue
            try:
                shutil.move(str(item), str(target))
                moved.append(str(target))
            except OSError:
                pass
        shutil.rmtree(old, ignore_errors=True)
    return moved

DEFAULTS = {
    "live_model": "gemini-3.8-live",                    # 빠른 모델(기본). 깊이 생각해야 하면 gemini-3.8-live-extended-thinking
    "thinking_level": "low",                           # low / medium / high (extended-thinking 모델만)
    "show_thoughts": True,
    "show_steps": True,
    "show_commands": True,
    "work_indicator": True,                            # 퍼플루가 앱·브라우저를 쓰는 동안 둘레에 빛 + '사용 중' 표시
    "work_indicator_color": "",                       # 작업 표시 색 (비우면 퍼플루 색)
    "browser_real_input": True,                        # 크롬 확장: 진짜 마우스·키보드(디버거)로 조작
    "browser_highlights": True,                        # 크롬 확장: 사이트 하이라이트·노트
    "python_enabled": True,
    "shell_enabled": True,                             # PC 명령어(PowerShell·cmd) 실행 허용 — 확인 방식은 python_approval과 같음                            # 퍼플루가 파이썬 코드를 써서 실행하기
    "security_level": "strict",                       # strict 강하게 / normal 보통 / relaxed 약하게
    "theme": "dark",
    "pc_chat_window": True,
    "pc_chat_pinned": False,                          # PC 대화창을 오른쪽에 고정 (안 사라짐)
    "pc_chat_autohide": 15,                           # 대답이 끝나고 몇 초 뒤 대화창 숨기기 (0 = 안 숨김)                           # PC: 말풍선 대신 타이핑할 수 있는 대화창을 오른쪽 아래에
    "chat_glow": "rainbow",                            # 입력칸 빛 색 조합: rainbow(다채로운) / blue_purple / pink_purple / sunset / ocean / mono
    "chat_color": "",                                 # 대화창 색 (내 말풍선·보내기 버튼). 비우면 퍼플루 색
    "image_model": "gemini-3.1-flash-image",          # 그림 만들기 모델                                   # dark 어둡게 / light 밝게
    "python_approval": "ask",                          # ask = 매번 물어보기 / auto_safe = 안전하면 자동 / auto_all = 모두 자동
    "python_timeout": 60,                              # 초
    "python_dir": "",                                 # 작업 폴더 (비우면 D:\bot\data\python)                             # 실제로 실행하는 명령어(파이썬 함수·프로그램·HTTP)도 보여주기                                # 실행하는 명령(도구)과 결과 보여주기 — Claude처럼                             # 생각 요약이 오면 말풍선에 보여주기
    "research_model": "gemini-flash-latest",
    "voice": "Leda",
    "talk_key": "f9",                                  # 누르고 있는 동안 듣기
    "speak": True,                                     # 퍼플루 목소리 재생
    "computer_control": True,                          # 클릭·타이핑으로 PC 조작 허용
    "cursor_visible": True,                            # 퍼플루 커서 보이기
    "cursor_mode": "auto",                            # auto = 필요할 때만 / always = 항상
    "cursor_follow": False,                            # 평소에 내 마우스 따라다니기
    "cursor_size": 64,
    "color": "#8B5CF6",                               # 퍼플루 색
    "notes_dir": "",                                  # 회의록 폴더 (비우면 D:\bot\data\notes)
    "tablet_port": 8765,
    "pages_url": "",                                  # GitHub Pages 주소 (예: https://이름.github.io/PPB/) — 이 주소에서만 PC에 붙을 수 있다
    "current_conversation": "",
}
COLORS = {  # 설정창에 나오는 색 견본
    "보라": "#8B5CF6", "파랑": "#3B82F6", "하늘": "#38BDF8", "민트": "#14B8A6", "초록": "#22C55E",
    "노랑": "#EAB308", "주황": "#F97316", "빨강": "#EF4444", "분홍": "#EC4899", "회색": "#64748B",
}
VOICES = {  # Gemini 목소리 이름 → 느낌 (설정창에서 들어보고 고른다)
    "Leda": "앳되고 귀여운", "Aoede": "산뜻한", "Zephyr": "밝은", "Puck": "신나는", "Kore": "또렷하고 단단한",
    "Autonoe": "밝고 맑은", "Laomedeia": "통통 튀는", "Sadachbia": "활기찬", "Achird": "친근한",
    "Vindemiatrix": "다정한", "Sulafat": "따뜻한", "Despina": "부드러운", "Achernar": "포근한",
    "Callirrhoe": "느긋한", "Umbriel": "여유로운", "Erinome": "또렷한", "Iapetus": "깔끔한",
    "Algieba": "매끄러운", "Zubenelgenubi": "캐주얼한", "Schedar": "차분하고 고른", "Charon": "차분한 설명",
    "Rasalgethi": "정보 전달", "Sadaltager": "박식한", "Gacrux": "성숙한", "Pulcherrima": "또박또박",
    "Enceladus": "숨결 섞인", "Algenib": "허스키한", "Fenrir": "들뜬", "Orus": "묵직한", "Alnilam": "단호한",
}
SECURITY_LEVELS = {
    "strict": "🔒 강하게 (기본) — 비밀번호·개인정보 막기, 되돌리기 어려운 일은 매번 물어보기",
    "normal": "🔓 보통 — 시킨 일은 바로, 돈이 드는 일만 물어보기, 비밀번호는 내가 말해 준 것만",
    "relaxed": "⚠ 약하게 — 개인정보·비밀번호 허용, 거의 묻지 않고 바로 실행",
}
SECURITY_PYTHON = {"strict": "ask", "normal": "auto_safe", "relaxed": "auto_all"}  # 보안 수준을 바꾸면 파이썬도 같이
SECURITY_WARNING = {
    "normal": "보안을 '보통'으로 낮추면:\n\n"
              "• 로그인·글 올리기·메일 보내기를 사용자가 시키면 묻지 않고 바로 해요\n"
              "• 사용자가 말해 준 비밀번호는 크롬 비밀번호 칸에 입력할 수 있어요\n"
              "• 파이썬 코드는 안전 검사를 통과하면 바로 실행돼요\n"
              "• 결제·구매·송금 같은 돈이 드는 일은 그래도 물어봐요\n\n"
              "퍼플루가 말을 잘못 알아들으면 원하지 않은 메일이 가거나 글이 올라갈 수 있어요. 바꿀까요?",
    "relaxed": "⚠ 보안을 '약하게'로 낮추면:\n\n"
               "• 비밀번호·카드번호·주민번호 같은 개인정보도 입력하고 다룰 수 있어요\n"
               "• 파일 지우기, 프로그램 설치, 메일 보내기도 거의 묻지 않고 바로 해요\n"
               "• 파이썬 코드가 검사 없이 바로 실행돼요\n\n"
               "퍼플루가 잘못 알아듣거나, 웹페이지·화면 글에 속으면 개인정보가 새거나 파일이 지워지거나\n"
               "돈이 나갈 수 있어요. 무슨 일이 생겨도 되돌리기 어려울 수 있어요.\n\n"
               "이 PC를 나만 쓰고, 위험을 알고 있을 때만 켜세요. 정말 바꿀까요?",
}
THEMES = {"dark": "🌙 어둡게", "light": "☀ 밝게 (흰 배경)"}
PYTHON_APPROVAL = {
    "ask": "매번 물어보기 (가장 안전)",
    "auto_safe": "안전해 보이면 자동 실행 (위험하면 물어보기)",
    "auto_all": "모두 자동 실행 (위험)",
}
PYTHON_APPROVAL_WARNING = {
    "auto_safe": "퍼플루가 쓴 코드를 미리 검사해서, 파일 지우기·프로그램 실행·인터넷 접속·시스템 접근이 없으면\n"
                 "물어보지 않고 바로 실행해요.\n\n검사는 완벽하지 않아요. 교묘하게 쓴 코드는 못 알아챌 수 있어요.\n"
                 "화면이나 웹페이지 글이 퍼플루를 속여 코드를 쓰게 할 수도 있어요.\n\n그래도 켤까요?",
    "auto_all": "퍼플루가 쓴 파이썬 코드를 검사 결과와 상관없이 전부 바로 실행해요.\n\n"
                "잘못된 코드가 파일을 지우거나 바꾸거나, 개인정보를 밖으로 보낼 수도 있어요.\n"
                "화면·웹페이지 글이 퍼플루를 속여 위험한 코드를 실행하게 할 수도 있어요.\n\n"
                "무슨 일이 생겨도 되돌리기 어려울 수 있어요. 정말 켤까요?",
}
CHOICES = {
    "live_model": ["gemini-3.8-live", "gemini-3.8-live-extended-thinking"],
    "image_model": ["gemini-3.1-flash-image", "gemini-3-pro-image", "gemini-3.1-flash-lite-image"],
    "thinking_level": ["low", "medium", "high"],
    "voice": list(VOICES),
    "talk_key": ["f9", "f8", "f10", "f12", "scrolllock", "pause", "insert"],
}

_cache: dict | None = None
_lock = threading.Lock()
_listeners = []


def _read_local() -> dict:
    try:
        return json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_local(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load() -> dict:
    """Firebase에서 새로 읽어온다 (시작할 때, 설정창 열 때)."""
    global _cache
    data = dict(DEFAULTS)
    data.update(_read_local())
    try:
        remote = store.get("settings")
        if isinstance(remote, dict):
            data.update({k: v for k, v in remote.items() if k in DEFAULTS})
        else:  # 처음이면 지금 설정을 Firebase에 올려 둔다
            store.in_background(store.put, "settings", data)
    except Exception as e:
        print("Firebase 설정 읽기 실패, 로컬 사본 사용:", e)
    with _lock:
        _cache = data
    _write_local(data)
    return dict(data)


def settings() -> dict:
    if _cache is None:
        return load()
    with _lock:
        return dict(_cache)


def save_settings(**changes) -> None:
    changes = {k: v for k, v in changes.items() if k in DEFAULTS}
    with _lock:
        data = dict(_cache or DEFAULTS)
        data.update(changes)
        globals()["_cache"] = data
    _write_local(data)
    store.in_background(store.patch, "settings", changes)
    for fn in list(_listeners):
        fn(changes)


def apply_remote(remote: dict) -> None:
    """Firebase에서 설정이 바뀌었다는 소식(다른 기기·탭에서 바꿈) → 다른 것만 반영하고 알린다."""
    with _lock:
        data = dict(_cache or DEFAULTS)
        changes = {k: v for k, v in remote.items() if k in DEFAULTS and data.get(k) != v}
        if not changes:
            return
        data.update(changes)
        globals()["_cache"] = data
    _write_local(data)
    for fn in list(_listeners):
        fn(changes)


def on_change(fn):
    _listeners.append(fn)


def get_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or keyring.get_password(APP, "gemini")


def set_api_key(key: str) -> None:
    keyring.set_password(APP, "gemini", key.strip())
