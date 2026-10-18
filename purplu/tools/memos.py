"""퍼플루가 메모를 남기고, 보여주고, 지운다. 메모는 Firebase에 저장 (PC 화면 포스트잇 + 탭에서도 보임)."""
from .. import store


def leave_memo(text: str, pin: bool = True) -> dict:
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "메모할 내용이 없어요."}
    mid = store.add_memo(text, pinned=bool(pin))
    return {"ok": True, "memo_id": mid, "note": "PC 화면에 포스트잇으로 붙였어." if pin else "저장했어."}


def list_memos() -> dict:
    rows = store.list_memos()
    return {"ok": True, "memos": [{"id": r["id"], "text": r.get("text", ""), "pinned": r.get("pinned", False)}
                                  for r in rows[:30]]}


def delete_memo(memo_id: str = "", text: str = "") -> dict:
    rows = store.list_memos()
    hit = next((r for r in rows if r["id"] == memo_id), None) if memo_id else None
    if not hit and text:
        hit = next((r for r in rows if text.strip() and text.strip() in r.get("text", "")), None)
    if not hit:
        return {"ok": False, "error": "그 메모를 못 찾았어요. list_memos로 확인해 보세요."}
    store.delete_memo(hit["id"])
    return {"ok": True, "deleted": hit.get("text", "")[:60]}
