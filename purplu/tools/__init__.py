"""퍼플루가 쓸 수 있는 도구 목록 (Gemini 함수 선언 + 실행)."""
from google.genai import types

from . import control
from .apps import open_app, open_url
from .files import find_file, open_path
from ..notes import start_meeting_notes, stop_meeting_notes
from .memos import delete_memo, leave_memo, list_memos
from .pyrun import run_python
from .shell import run_command
from . import web_browser as wb
from .reminders import cancel_reminder, list_reminders, set_reminder
from .system import media_control, read_clipboard, write_clipboard
from .windows import system_status, windows_action
from .skills import delete_skill, list_skills, save_skill, use_skill
from .images import generate_image
from .search import search_web
from .web import web_research

S, I, B, N = types.Type.STRING, types.Type.INTEGER, types.Type.BOOLEAN, types.Type.NUMBER
GX = (N, "0=왼쪽 끝, 1000=오른쪽 끝 (화면 격자)")
GY = (N, "0=위쪽 끝, 1000=아래쪽 끝 (화면 격자)")
TARGET = (S, "look_at_screen에서 받은 C(버튼) 또는 L(글자 줄) 번호")
TEXT = (S, "화면에 보이는 글자 그대로(예: '4. 하이라이트', '저장') 또는 글자가 아닌 것의 짧은 설명"
            "(예: '빨간 닫기 버튼', '고양이 사진'). 찾을 땐 이게 제일 정확하다")


def _fn(name, description, props=None, required=()):
    params = None
    if props:
        params = types.Schema(type=types.Type.OBJECT, required=list(required),
                              properties={k: types.Schema(type=t, description=d) for k, (t, d) in props.items()})
    return types.FunctionDeclaration(name=name, description=description, parameters=params)


DECLARATIONS = [
    _fn("open_app", "PC에서 앱을 열거나 그 앱으로 전환한다. 예: 크롬, 메모장, 카카오톡, 엑셀.",
        {"name": (S, "앱 이름. 사용자가 말한 그대로(한글 가능).")}, ["name"]),
    _fn("open_url", "기본 브라우저로 웹사이트를 연다. 예: youtube.com, 네이버, 전체 링크.",
        {"url": (S, "주소 또는 잘 알려진 사이트 이름")}, ["url"]),
    _fn("find_file", "내 PC에서 파일을 찾는다(파일 이름과 내용). 결과는 최근 수정순 목록.",
        {"keyword": (S, "파일 이름이나 내용에 들어갈 단어. 짧게 핵심만."),
         "file_type": (S, "확장자. 예: pdf, docx, xlsx, jpg, hwp"),
         "modified_within_days": (I, "최근 며칠 안에 수정된 것만. 예: 지난주면 7")}),
    _fn("open_path", "find_file로 찾은 파일을 열거나, 탐색기에서 그 위치를 보여준다.",
        {"path": (S, "find_file 결과의 전체 경로"),
         "show_in_folder": (B, "true면 파일을 여는 대신 탐색기에서 선택해서 보여준다")}, ["path"]),
    _fn("web_research", "웹에서 찾아본다. 최신 정보, 날씨, 뉴스, 가격, 사실 확인 등 확실하지 않은 것 전부.",
        {"question": (S, "조사할 내용을 그것만 읽어도 이해되는 질문으로")}, ["question"]),
    _fn("leave_memo", "메모를 남긴다. PC 화면에 포스트잇으로 붙고 탭에서도 보인다. "
        "'메모해줘', '기억해줘', '적어둬' 같은 부탁이나, 조사·화면 내용을 정리해서 남겨 달라고 할 때.",
        {"text": (S, "메모 내용. 짧고 알아보기 쉽게, 필요하면 여러 줄"),
         "pin": (B, "PC 화면에 포스트잇으로 붙이기 (기본 true)")}, ["text"]),
    _fn("list_memos", "남겨 둔 메모 목록을 본다."),
    _fn("run_command", "PC 명령어를 실행한다 (PowerShell 기본, cmd도). Windows 기능은 거의 다 된다: 끄기·다시 시작 "
        "(shutdown /s /t 60), 예약 종료 취소(shutdown /a), 프로그램·서비스 목록, 네트워크(ipconfig), 파일 옮기기·찾기, "
        "설정 바꾸기, 프린터, 블루투스 등. 다른 도구로 안 되면 이걸 써. 실행 전에 사용자가 확인할 수 있다.",
        {"command": (S, "실행할 명령어"), "purpose": (S, "무슨 일을 하는지 한 줄 (확인창에 보인다)"),
         "shell": (S, "powershell (기본) 또는 cmd"), "timeout": (I, "초, 기본 60")}, ["command", "purpose"]),
    _fn("run_python", "파이썬 코드를 써서 이 PC에서 실행한다. 다른 도구로 안 되는 일에만: 복잡한 계산, 표·CSV·엑셀 정리, "
        "파일 만들기·변환(이미지 크기 바꾸기 등), 데이터 분석, 날짜 계산 등. 결과는 print로 출력한다. "
        "작업 폴더에서 실행되니 새 파일은 거기에 만든다(다른 폴더 파일은 전체 경로로 읽기만). "
        "쓸 수 있는 패키지: 표준 라이브러리, numpy, PIL(Pillow), httpx. 사용자가 실행 전에 코드를 보고 허락할 수 있다.",
        {"code": (S, "실행할 파이썬 코드 전체"),
         "purpose": (S, "이 코드가 하는 일 한 줄 (확인창에 보인다)")}, ["code", "purpose"]),
    _fn("start_meeting_notes", "회의록을 시작한다. PC 마이크로 계속 녹음하고 5분마다 화자를 구분해 받아쓴다. "
        "'회의록 시작해', '지금부터 회의 기록해줘' 할 때.",
        {"title": (S, "회의 제목. 모르면 '회의'")}),
    _fn("stop_meeting_notes", "회의록을 끝낸다. 마지막까지 받아쓰고 요약·결정사항·할 일을 정리해 notes.md에 저장한다."),
    _fn("set_reminder", "알림·타이머를 맞춘다. 때가 되면 퍼플루가 목소리로 알려 준다. "
        "'10분 뒤에 알려줘'면 minutes=10, '3시에 회의 알려줘'면 at='15:00'.",
        {"text": (S, "알려 줄 내용. 예: '회의', '라면 다 됐어'"),
         "minutes": (N, "지금부터 몇 분 뒤 (초 단위면 나누기 60)"),
         "at": (S, "시각. 'HH:MM'(24시간) 또는 'YYYY-MM-DD HH:MM'")}, ["text"]),
    _fn("list_reminders", "맞춰 둔 알림 목록을 본다."),
    _fn("cancel_reminder", "알림을 취소한다.",
        {"reminder_id": (S, "list_reminders의 id"), "text": (S, "id를 모르면 알림 내용 글자")}),
    _fn("search_web", "웹·뉴스를 바로 검색한다 (빠름). 요즘 유행, 인기 순위, 뉴스, 날씨, 가격, 사람·회사 소식, 모르는 것 등 "
        "최신이거나 확실하지 않은 건 대답하기 전에 꼭 먼저 이걸 써.",
        {"query": (S, "검색어 (한국어, 짧게)"), "kind": (S, "all / news / web (기본 all)")}, ["query"]),
    _fn("system_status", "PC 상태를 본다: 배터리(%·충전 중·남은 시간), CPU, 메모리, 디스크 여유, 와이파이, 켜진 시간, 메모리 많이 쓰는 앱."),
    _fn("windows_action", "Windows 기본 기능. action: lock(화면 잠금) / sleep(절전) / shutdown·restart(value=몇 초 뒤, 기본 60) / "
        "cancel_shutdown / brightness(value=0~100, 비우면 지금 밝기) / dark_mode(value=on·off) / "
        "open_settings(value=디스플레이·소리·블루투스·와이파이·배터리·업데이트·알림·방해 금지·야간 모드 등) / "
        "screenshot(저장) / list_windows / focus_window·minimize_window·close_window(value=창 이름 일부) / show_desktop",
        {"action": (S, "동작"), "value": (S, "값")}, ["action"]),
    _fn("use_skill", "스킬(사용자가 만든 할 일 설명서)을 불러온다. 사용자의 부탁이 스킬 목록의 설명과 맞으면 먼저 이걸 부르고 설명서대로 해.",
        {"name": (S, "스킬 이름")}, ["name"]),
    _fn("list_skills", "스킬 목록을 본다."),
    _fn("save_skill", "새 스킬을 만들거나 고친다. '이걸 스킬로 저장해', '앞으로 ~하면 이렇게 해 줘' 할 때. "
        "instructions는 퍼플루가 따라 할 단계별 설명(어떤 도구를 어떤 순서로)으로 써.",
        {"name": (S, "짧은 이름"), "description": (S, "언제 쓰는지 한 줄"), "instructions": (S, "단계별 설명서")},
        ["name", "description", "instructions"]),
    _fn("delete_skill", "스킬을 지운다.", {"name": (S, "스킬 이름")}, ["name"]),
    _fn("generate_image", "그림을 만든다(또는 채팅으로 첨부한 그림을 고친다). 만든 그림은 화면에 보여 주고 data\\images에 저장된다.",
        {"prompt": (S, "만들 그림 설명 (자세할수록 좋다)"), "edit_attached": (B, "방금 첨부한 그림을 고치기")}, ["prompt"]),
    _fn("media_control", "PC 소리·음악을 조절한다. 볼륨 올리기/내리기/정하기, 음소거, 음악 재생·멈춤·다음 곡·이전 곡.",
        {"action": (S, "volume_set / volume_up / volume_down / mute / unmute / status / play_pause / next / previous / stop"),
         "level": (N, "volume_set이면 0~100, volume_up/down이면 얼마나(기본 10)")}, ["action"]),
    _fn("read_clipboard", "사용자가 복사(Ctrl+C)해 둔 글을 읽는다. '복사한 거 요약해줘/번역해줘/읽어줘' 할 때."),
    _fn("write_clipboard", "글을 클립보드에 복사해 둔다(사용자가 Ctrl+V로 붙여넣게). 요약·번역 결과를 넘겨줄 때.",
        {"text": (S, "복사할 글")}, ["text"]),
    _fn("delete_memo", "메모를 지운다.",
        {"memo_id": (S, "list_memos의 id"), "text": (S, "id를 모르면 메모에 들어 있는 글자")}),
]

BROWSER_DECLARATIONS = [
    _fn("browser_open", "브라우저에서 주소를 연다(검색어를 주면 구글 검색). 웹 일은 open_url 대신 이걸 쓴다. "
        "기본은 '퍼플루 브라우저'(대화창 위에 보이는 탭 하나짜리 브라우저)에서 연다 — 같은 탭을 계속 다시 쓰니까 "
        "찾을 때마다 새로 열지 말고 이 탭에서 이어서 해. 사용자가 웨일·크롬에서 하라고 하면 where에 그 이름.",
        {"url": (S, "주소 또는 검색어"), "where": (S, "비우면 퍼플루 브라우저. '웨일'·'크롬'·'엣지'면 사용자의 그 브라우저"),
         "new_tab": (B, "지금 탭은 두고 새 탭에서 열 때 true (기본 false: 지금 탭에서 엶). 여러 곳을 비교할 때만")}, ["url"]),
    _fn("browser_tabs", "열린 탭 목록(번호·제목·주소). 기본은 퍼플루 브라우저의 탭, where='웨일'·'크롬'이면 내 브라우저의 탭.",
        {"where": (S, "비우면 퍼플루 브라우저")}),
    _fn("browser_switch_tab", "탭을 바꾼다 (browser_tabs의 tab_id).", {"tab_id": (I, "browser_tabs의 tab_id")}, ["tab_id"]),
    _fn("browser_close_tab", "탭을 닫는다. tab_id가 없으면 지금 탭.", {"tab_id": (I, "닫을 탭")}),
    _fn("browser_read", "브라우저의 지금 탭을 읽는다: 제목, 주소, 본문 글, 누를 수 있는 것·입력칸 목록(E1, E2…). "
        "페이지마다 한 번만 (누르거나 옮긴 뒤에만 다시). 질문에 답하려고 쓰지 말고 search_web 을 써.",
        {"max_chars": (I, "본문을 몇 글자까지 (기본 6000)")}),
    _fn("browser_click", "브라우저 페이지를 진짜 마우스로 누른다. browser_read의 E 번호가 가장 정확하고, "
        "번호가 없으면 글자(text), 그래도 안 되면 browser_screenshot 사진의 x,y 좌표로.",
        {"element_id": (S, "E 번호"), "text": (S, "번호를 모르면 버튼·링크 글자"), "x": (I, "사진 좌표 x"), "y": (I, "사진 좌표 y"),
         "double": (B, "두 번 누르기"), "right": (B, "오른쪽 버튼")}),
    _fn("browser_type", "브라우저 페이지의 입력칸을 눌러 진짜 키보드로 글을 넣는다 (한글 OK). 원래 있던 글은 지우고 넣는다.",
        {"text": (S, "넣을 글"), "element_id": (S, "입력칸 E 번호 (없으면 지금 커서가 있는 칸)"),
         "submit": (B, "넣고 Enter (검색·전송)"), "clear": (B, "원래 글 지우기 (기본 true)")}, ["text"]),
    _fn("browser_keys", "브라우저에 키보드 키를 누른다. 예: 'Enter', 'Tab', 'Escape', 'ArrowDown', 'ctrl+a', 'shift+tab', "
        "'PageDown'. 여러 개는 공백으로: 'ArrowDown ArrowDown Enter'",
        {"keys": (S, "누를 키")}, ["keys"]),
    _fn("browser_screenshot", "브라우저 지금 화면을 사진으로 본다. 그림·버튼 모양을 봐야 하거나 번호로 못 찾을 때. "
        "사진 좌표 = browser_click의 x,y."),
    _fn("browser_scroll", "브라우저 페이지를 스크롤한다.",
        {"direction": (S, "down / up / top / bottom"), "amount": (I, "1~10, 기본 3")}),
    _fn("browser_nav", "브라우저 뒤로/앞으로/새로고침.", {"action": (S, "back / forward / reload")}, ["action"]),
    _fn("browser_highlight", "브라우저 페이지의 글자에 형광펜을 칠하고(노트도 붙일 수 있음) 그곳으로 스크롤한다. "
        "이 사이트에 저장돼서 새로고침해도 남는다. text에는 페이지 글을 그대로.",
        {"text": (S, "칠할 글자 (페이지에 있는 그대로)"), "note": (S, "붙일 노트 (선택)"),
         "color": (S, "yellow / green / pink / purple (기본 purple)")}, ["text"]),
    _fn("browser_bookmarks", "브라우저 즐겨찾기(북마크)에서 찾는다. '즐겨찾기에 있는 ~ 열어 줘' 하면 이걸로 찾고 browser_open으로 연다. "
        "이름이 정확하지 않아도 단어 일부로 찾는다.", {"query": (S, "찾을 이름·주소 일부 (비우면 전체)")}),
    _fn("browser_history", "브라우저 방문 기록에서 찾는다 (최근 90일). '전에 갔던 ~' 할 때.", {"query": (S, "찾을 말")}),
    _fn("browser_notes", "하이라이트·노트 목록을 본다. 기본은 지금 페이지, all_sites=true면 모든 사이트.",
        {"all_sites": (B, "모든 사이트")}),
]

SCREEN_DECLARATIONS = [
    _fn("look_at_screen", "지금 화면을 본다. 앞에 있는 창 이름, 누를 수 있는 것들(C 번호, 0~1000 격자 위치), 스크린샷. "
        "가리키거나 조작하기 전에, 그리고 화면이 바뀌었을 때마다 부른다."),
    _fn("point_at", "퍼플루 커서를 날려서 화면의 무언가를 가리킨다. 그걸 말하기 직전에 부른다. "
        "글자면 text, 버튼이면 target_id, 그림이면 x, y.",
        {"text": TEXT, "target_id": TARGET, "x": GX, "y": GY}),
    _fn("stop_pointing", "가리키기를 끝내고 커서를 집으로 돌려보낸다."),
    _fn("highlight", "화면의 글자·버튼·영역에 반짝이는 테두리(하이라이트)와 이름표를 그려서 사용자에게 보여준다. "
        "글자를 표시할 땐 text에 화면 글자를 그대로 넣으면 정확한 위치를 찾아 준다(눈대중 좌표 쓰지 말 것). "
        "결과의 highlighted에 실제로 표시된 글자가 나오니 확인하고 말한다.",
        {"text": (S, "표시할 화면 글자 그대로, 또는 글자가 아닌 것의 설명. 여러 개면 | 로: '4. 하이라이트|3. 동기화'"),
         "target_ids": (S, "look_at_screen의 C/L 번호. 여러 개면 쉼표로: C3,L7"),
         "x": GX, "y": GY,
         "width": (N, "영역 너비 (0~1000 격자 단위). 글자가 아닌 그림·영역을 표시할 때"),
         "height": (N, "영역 높이 (0~1000 격자 단위)"),
         "label": (S, "하이라이트 옆에 붙일 짧은 이름표. 예: '여기!', '저장', '1번'"),
         "seconds": (N, "보여줄 시간(초). 기본 8")}),
    _fn("clear_highlights", "화면의 하이라이트를 모두 지운다."),
    _fn("what_is_under_mouse", "사용자 마우스 아래 있는 것을 알아본다(버튼 이름, 근처 글자, 확대 사진). "
        "'이게 뭐야?', '이거 뭐야?', '여기 뭐라고 써 있어?'처럼 가리키는 말이 나오면 이걸 먼저 쓴다."),
]

CONTROL_DECLARATIONS = [
    _fn("click", "퍼플루 커서로 화면의 무언가를 클릭한다. 버튼은 C 번호, 글자 링크·메뉴는 text가 정확하다.",
        {"text": TEXT, "target_id": TARGET, "x": GX, "y": GY,
         "double": (B, "더블클릭"), "right": (B, "오른쪽 클릭")}),
    _fn("type_text", "키보드처럼 글자를 입력한다(한글 가능). 입력할 칸을 먼저 클릭해 둔다. "
        "계산기는 창이 앞에 있으면 '3*9=' 처럼 바로 입력하면 된다.",
        {"text": (S, "입력할 글자"), "press_return": (B, "다 쓰고 Enter")}, ["text"]),
    _fn("press_keys", "키나 단축키를 누른다. 예: enter, escape, tab, ctrl+c, ctrl+v, ctrl+t, alt+tab, win+d",
        {"keys": (S, "누를 키. +로 묶는다")}, ["keys"]),
    _fn("scroll", "화면을 스크롤한다.",
        {"direction": (S, "up / down / left / right"), "amount": (I, "1(조금)~10(많이), 기본 3"),
         "target_id": TARGET, "x": GX, "y": GY}, ["direction"]),
]


def declarations(computer_control: bool):
    from .. import mcp_client
    mcp_client.wait_ready(6)   # 막 켜져서 MCP 서버가 붙는 중이면 조금 기다린다
    try:
        extra = mcp_client.declarations()   # 설정에서 추가한 MCP 서버의 도구
    except Exception as e:
        print("MCP 도구 목록 실패:", e)
        extra = []
    return DECLARATIONS + BROWSER_DECLARATIONS + SCREEN_DECLARATIONS + (CONTROL_DECLARATIONS if computer_control else []) + extra


def _run_mcp(name: str, args: dict) -> dict:
    """MCP 도구: '실행 전 확인' 설정을 따른다 (안전하면 자동 = 읽기만 하는 도구만 자동)."""
    from .. import config, mcp_client, trace
    server, tool, t = mcp_client.find(name)
    if not server:
        return {"ok": False, "error": "그 MCP 도구를 못 찾았어요."}
    args = mcp_client.fix_args(name, args)
    shown = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in args.items())
    trace.cmd(f"mcp.{server}.{tool}({shown})")
    mode = config.settings().get("python_approval", "ask")
    read_only = bool(getattr(getattr(t, "annotations", None), "readOnlyHint", False))
    if mode == "ask" or (mode == "auto_safe" and not read_only):
        from . import pyrun
        risks = [] if read_only else ["MCP 서버의 도구가 무언가를 바꿀 수 있어요"]
        if not pyrun._confirm(f"{tool}({shown})", f"MCP 서버 '{server}'의 도구", risks, kind="MCP 도구"):
            return {"ok": False, "error": "사용자가 허락하지 않았어요. 실행하지 않았어."}
    return mcp_client.call(name, args)


_RUNNERS = {
    "open_app": open_app, "open_url": open_url, "find_file": find_file,
    "open_path": open_path, "web_research": web_research,
    "leave_memo": leave_memo, "list_memos": list_memos, "delete_memo": delete_memo, "run_python": run_python,
    "run_command": run_command,
    "start_meeting_notes": start_meeting_notes, "stop_meeting_notes": stop_meeting_notes,
    "browser_tabs": wb.browser_tabs, "browser_open": wb.browser_open, "browser_switch_tab": wb.browser_switch_tab,
    "browser_close_tab": wb.browser_close_tab, "browser_read": wb.browser_read, "browser_click": wb.browser_click,
    "browser_type": wb.browser_type, "browser_scroll": wb.browser_scroll, "browser_nav": wb.browser_nav,
    "browser_highlight": wb.browser_highlight, "browser_keys": wb.browser_keys,
    "browser_screenshot": wb.browser_screenshot, "browser_notes": wb.browser_notes,
    "browser_bookmarks": wb.browser_bookmarks, "browser_history": wb.browser_history,
    "set_reminder": set_reminder, "list_reminders": list_reminders, "cancel_reminder": cancel_reminder,
    "media_control": media_control, "read_clipboard": read_clipboard, "write_clipboard": write_clipboard,
    "search_web": search_web, "system_status": system_status, "windows_action": windows_action, "use_skill": use_skill, "list_skills": list_skills,
    "save_skill": save_skill, "delete_skill": delete_skill, "generate_image": generate_image,
    "look_at_screen": control.look_at_screen, "point_at": control.point_at,
    "stop_pointing": control.stop_pointing, "click": control.click, "type_text": control.type_text,
    "press_keys": control.press_keys, "scroll": control.scroll,
    "highlight": control.highlight, "clear_highlights": control.clear_highlights,
    "what_is_under_mouse": control.what_is_under_mouse,
}
ACTIONS = {"click", "type_text", "press_keys", "scroll", "browser_click", "browser_type", "browser_keys"}

# 말풍선에 보여줄 "하는 중" 문구
LABELS = {
    "open_app": lambda a: f"{a.get('name', '')} 여는 중…",
    "open_url": lambda a: f"{a.get('url', '')} 여는 중…",
    "find_file": lambda a: f"'{a.get('keyword') or a.get('file_type', '')}' 파일 찾는 중…",
    "open_path": lambda a: "파일 여는 중…",
    "web_research": lambda a: "웹에서 찾아보는 중…",
    "search_web": lambda a: f"🔎 '{a.get('query', '')}' 검색 중…",
    "system_status": lambda a: "PC 상태 보는 중…",
    "windows_action": lambda a: f"Windows: {a.get('action', '')} {a.get('value', '')}",
    "use_skill": lambda a: f"🧩 스킬 '{a.get('name', '')}' 쓰는 중…",
    "list_skills": lambda a: "스킬 목록 보는 중…",
    "save_skill": lambda a: f"🧩 스킬 '{a.get('name', '')}' 저장 중…",
    "delete_skill": lambda a: f"스킬 '{a.get('name', '')}' 지우는 중…",
    "generate_image": lambda a: "🎨 그림 그리는 중…",
    "browser_tabs": lambda a: "브라우저 탭 보는 중…",
    "browser_open": lambda a: f"{a.get('where') or '브라우저'}에서 '{a.get('url', '')}' 여는 중…",
    "browser_switch_tab": lambda a: "브라우저 탭 바꾸는 중…",
    "browser_close_tab": lambda a: "브라우저 탭 닫는 중…",
    "browser_read": lambda a: "브라우저 페이지 읽는 중…",
    "browser_click": lambda a: f"브라우저에서 '{a.get('text') or a.get('element_id', '')}' 누르는 중…",
    "browser_type": lambda a: "브라우저에 입력하는 중…",
    "browser_keys": lambda a: f"브라우저 키보드: {a.get('keys', '')}",
    "browser_screenshot": lambda a: "브라우저 화면 보는 중…",
    "browser_notes": lambda a: "하이라이트·노트 보는 중…",
    "browser_bookmarks": lambda a: f"즐겨찾기에서 '{a.get('query', '')}' 찾는 중…",
    "browser_history": lambda a: f"방문 기록에서 '{a.get('query', '')}' 찾는 중…",
    "browser_scroll": lambda a: "브라우저 스크롤하는 중…",
    "browser_nav": lambda a: f"브라우저 {a.get('action', '')}…",
    "browser_highlight": lambda a: f"브라우저에서 '{a.get('text', '')}' 표시하는 중…",
    "leave_memo": lambda a: "메모 남기는 중…",
    "run_python": lambda a: f"🐍 파이썬 실행: {a.get('purpose', '')}",
    "run_command": lambda a: f"⌨ 명령어: {a.get('purpose', '')}",
    "start_meeting_notes": lambda a: "● 회의록 녹음 시작",
    "stop_meeting_notes": lambda a: "회의록 정리하는 중…",
    "set_reminder": lambda a: f"⏰ '{a.get('text', '')}' 알림 맞추는 중…",
    "list_reminders": lambda a: "알림 목록 보는 중…",
    "cancel_reminder": lambda a: "알림 취소하는 중…",
    "media_control": lambda a: "소리 조절하는 중…",
    "read_clipboard": lambda a: "복사한 글 읽는 중…",
    "write_clipboard": lambda a: "클립보드에 복사하는 중…",
    "list_memos": lambda a: "메모 보는 중…",
    "delete_memo": lambda a: "메모 지우는 중…",
    "look_at_screen": lambda a: "화면 보는 중…",
    "point_at": lambda a: "가리키는 중…",
    "stop_pointing": lambda a: "커서 집으로",
    "click": lambda a: "클릭하는 중…",
    "type_text": lambda a: f"'{a.get('text', '')[:20]}' 입력하는 중…",
    "press_keys": lambda a: f"{a.get('keys', '')} 누르는 중…",
    "scroll": lambda a: "스크롤하는 중…",
    "highlight": lambda a: f"하이라이트 표시 {a.get('label', '')}".strip(),
    "clear_highlights": lambda a: "하이라이트 지우기",
}


def run(name: str, args: dict, computer_control: bool = True) -> dict:
    if name.startswith("mcp_"):
        try:
            return _run_mcp(name, args)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    fn = _RUNNERS.get(name)
    if not fn:
        return {"ok": False, "error": f"모르는 도구: {name}"}
    if name in ACTIONS and not computer_control:
        return {"ok": False, "error": "컴퓨터 조작이 꺼져 있어요. 설정에서 켤 수 있어요."}
    try:
        return fn(**args)
    except TypeError as e:
        return {"ok": False, "error": f"인자가 잘못됐어요: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def call_text(name: str, args: dict) -> str:
    """Claude처럼 보여 줄 명령 한 줄: open_app("계산기")"""
    from .. import config
    if name == "browser_type" and config.settings().get("security_level", "strict") != "strict":
        args = {**args, "text": f"<{len(str(args.get('text', '')))}자 가림>"}  # 비밀번호가 화면에 보이지 않게
    shown = []
    for k, v in args.items():
        v = str(v).replace("\n", " ")
        shown.append(f'{k}="{v[:40]}{"…" if len(v) > 40 else ""}"' if isinstance(v, str) else f"{k}={v}")
    return f"{name}({', '.join(shown)})"


def result_text(result: dict) -> str:
    """결과를 한 줄로: 무엇이 됐는지, 또는 왜 안 됐는지."""
    if not result.get("ok"):
        return str(result.get("error", "실패"))[:90]
    for key, fmt in (("opened", "열었어: {}"), ("clicked", "클릭: {}"), ("typed", "입력: {}"), ("pressed", "눌렀어: {}"),
                     ("highlighted", "표시: {}"), ("pointing_at", "가리킴: {}"), ("volume", "볼륨 {}"),
                     ("when", "{}에 알림"), ("memo_id", "메모 남김"), ("deleted", "지움: {}"), ("cancelled", "취소: {}"),
                     ("copied_chars", "{}글자 복사"), ("folder", "{}"), ("foreground_window", "화면: {}"), ("title", "{}"), ("done", "{}"), ("saved", "저장: {}"),
                     ("created", "스킬 만듦: {}"), ("updated", "스킬 고침: {}"), ("windows", "창: {}")):
        if key in result:
            v = result[key]
            v = ", ".join(map(str, v)) if isinstance(v, list) else v
            return fmt.format(str(v)[:70])
    if "mcp" in result:
        first = (result.get("text") or "").strip().split("\n")[0]
        return f"{result['mcp']} · {first[:60]}" if first else result["mcp"]
    if "news" in result or "web" in result:
        return f"뉴스 {len(result.get('news', []))}개 · 웹 {len(result.get('web', []))}개"
    if "battery" in result:
        bt = result["battery"]
        return (f"배터리 {bt['percent']}%{' 충전 중' if bt['charging'] else ''} · CPU {result['cpu_percent']}%"
                if isinstance(bt, dict) else f"CPU {result['cpu_percent']}% · 메모리 {result['memory_percent']}%")
    if "images" in result:
        return f"그림 {len(result['images'])}장"
    if "skills" in result:
        return f"스킬 {len(result['skills'])}개"
    if "instructions" in result:
        return f"스킬 '{result.get('skill')}' 불러옴"
    if "exit_code" in result:
        out = (result.get("stdout") or "").strip().splitlines()
        return (f"{result.get('seconds')}초, 출력: {out[-1][:60]}" if out else f"{result.get('seconds')}초, 출력 없음")
    if "elements" in result:
        return f"{(result.get('title') or '')[:40]} · 누를 것 {len(result['elements'])}개"
    if "bookmarks" in result:
        return f"즐겨찾기 {len(result['bookmarks'])}개"
    if "history" in result:
        return f"방문 기록 {len(result['history'])}개"
    if "tabs" in result:
        return f"탭 {len(result['tabs'])}개"
    if "files" in result:
        return f"파일 {len(result['files'])}개 찾음"
    if "report" in result:
        return (result["report"].split("\n")[0] or "조사 끝")[:70]
    if "memos" in result:
        return f"메모 {len(result['memos'])}개"
    if "reminders" in result:
        return f"알림 {len(result['reminders'])}개"
    if "text" in result:
        return f"글 {len(result['text'])}자 읽음"
    return "완료"


def label(name: str, args: dict) -> str:
    if name.startswith("mcp_"):
        from .. import mcp_client
        server, tool, _ = mcp_client.find(name)
        return f"🔌 {server or 'MCP'}: {tool or name} 쓰는 중…"
    return LABELS.get(name, lambda a: f"{name} 하는 중…")(args)
