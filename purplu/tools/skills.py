"""스킬: 사용자가 만든 '할 일 설명서'. 퍼플루는 이름·한 줄 설명만 알고 있다가, 맞는 일이 오면 use_skill로 전체 설명을 읽고 따른다.

Firebase purplu/skills/{id} = {name, description, instructions, enabled, created}
"""
from .. import store

DEFAULT_SKILLS = [
    {"name": "아침 브리핑", "description": "'좋은 아침', '오늘 어때?' 하면 오늘 날씨·일정·알림을 한 번에 알려 주기",
     "instructions": "1) web_research로 사용자 지역 오늘 날씨(기본 서울)를 찾아.\n2) list_reminders와 list_memos로 오늘 할 일을 모아.\n"
                     "3) system_status로 배터리가 30% 아래면 충전하라고 덧붙여.\n4) 세 줄 이내로 밝게 말해."},
    {"name": "번역해서 복사", "description": "'이거 영어로 바꿔 줘' 처럼 복사한 글을 번역해서 다시 클립보드에 넣기",
     "instructions": "read_clipboard로 글을 읽고, 원하는 언어(말이 없으면 한국어↔영어)로 자연스럽게 번역해서 write_clipboard로 넣어. "
                     "끝나면 'Ctrl+V 하면 돼'라고 말해."},
    {"name": "집중 모드", "description": "'집중할래', '공부 시작' 하면 방해 요소를 줄이고 타이머 맞추기",
     "instructions": "1) media_control로 음악을 멈추고 볼륨을 20으로.\n2) 몇 분 할지 말 안 했으면 25분으로 set_reminder('쉬는 시간!').\n"
                     "3) windows_action open_settings '방해 금지'를 열어 줘.\n4) '파이팅! 25분 뒤에 알려 줄게'라고 말해."},
]


def _all() -> dict:
    data = store.get("skills") or {}
    if not data and store.get("skills_seeded") is None:  # 처음 한 번 예시 스킬을 넣어 둔다
        for s in DEFAULT_SKILLS:
            store.post("skills", {**s, "enabled": True, "created": store.now_ms()})
        store.put("skills_seeded", True)
        data = store.get("skills") or {}
    return data


def enabled_summary() -> str:
    """시스템 지시에 넣을 '쓸 수 있는 스킬' 목록 (이름과 한 줄 설명만)."""
    try:
        rows = [s for s in _all().values() if s.get("enabled", True)]
    except Exception:
        return ""
    if not rows:
        return ""
    return "\n".join(f"  · {s['name']}: {s.get('description', '')}" for s in rows[:40])


def list_skills() -> dict:
    return {"ok": True, "skills": [{"id": k, "name": v.get("name"), "description": v.get("description"),
                                    "enabled": v.get("enabled", True)} for k, v in _all().items()]}


def use_skill(name: str) -> dict:
    want = (name or "").strip().lower()
    for k, v in _all().items():
        if v.get("name", "").strip().lower() == want or want and want in v.get("name", "").lower():
            if not v.get("enabled", True):
                return {"ok": False, "error": f"'{v['name']}' 스킬은 꺼져 있어요."}
            return {"ok": True, "skill": v["name"], "instructions": v.get("instructions", ""),
                    "note": "이 설명서대로 지금 바로 도구를 써서 해."}
    return {"ok": False, "error": f"'{name}' 스킬이 없어요.", "skills": [v.get("name") for v in _all().values()]}


def save_skill(name: str, description: str, instructions: str) -> dict:
    """새 스킬 만들기 (같은 이름이 있으면 고친다)."""
    name = (name or "").strip()[:40]
    if not name or not instructions:
        return {"ok": False, "error": "이름과 설명서(instructions)가 필요해요."}
    row = {"name": name, "description": (description or "")[:150], "instructions": instructions[:4000], "enabled": True}
    for k, v in _all().items():
        if v.get("name", "").strip().lower() == name.lower():
            store.patch(f"skills/{k}", row)
            return {"ok": True, "updated": name}
    store.post("skills", {**row, "created": store.now_ms()})
    return {"ok": True, "created": name, "note": "다음 대화부터 이 스킬을 쓸 수 있어."}


def delete_skill(name: str) -> dict:
    for k, v in _all().items():
        if v.get("name", "").strip().lower() == (name or "").strip().lower():
            store.delete(f"skills/{k}")
            return {"ok": True, "deleted": v["name"]}
    return {"ok": False, "error": f"'{name}' 스킬이 없어요."}
