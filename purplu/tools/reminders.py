"""알림·타이머: "10분 뒤에 알려줘", "3시에 회의 알려줘".

Firebase(/purplu/reminders)에 저장해서 PC를 껐다 켜도 남고, 탭에서도 보인다.
때가 되면 PC가 퍼플루 목소리로 알려 주고, 말풍선·탭에도 띄운다.
"""
import re
import threading
from datetime import datetime, timedelta

from .. import store

_cache: list[dict] = []
_lock = threading.Lock()


def refresh():
    """Firebase에서 다시 읽기 (시작할 때, 바뀌었다는 소식이 올 때)."""
    global _cache
    try:
        data = store.get("reminders") or {}
    except Exception as e:
        print("알림 불러오기 실패:", e)
        return
    rows = [{"id": k, **v} for k, v in data.items() if isinstance(v, dict)]
    with _lock:
        _cache = sorted(rows, key=lambda r: r.get("due", 0))


def due_now() -> list[dict]:
    now = store.now_ms()
    with _lock:
        return [r for r in _cache if not r.get("done") and r.get("due", 0) <= now]


def mark_done(rid: str):
    with _lock:
        for r in _cache:
            if r["id"] == rid:
                r["done"] = True
    store.in_background(store.patch, f"reminders/{rid}", {"done": True})


def _parse_at(at: str) -> datetime | None:
    """'15:30', '오후 3시', '3시 30분', '2026-10-18 09:00' 같은 시각."""
    at = at.strip()
    now = datetime.now()
    for fmt in ("%Y-%m-%d %H:%M", "%m-%d %H:%M", "%H:%M"):
        try:
            t = datetime.strptime(at, fmt)
            if fmt == "%H:%M":
                t = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            elif fmt == "%m-%d %H:%M":
                t = t.replace(year=now.year)
            return t if t > now else t + timedelta(days=1) if fmt == "%H:%M" else t
        except ValueError:
            pass
    m = re.search(r"(오전|오후)?\s*(\d{1,2})\s*시\s*(?:(\d{1,2})\s*분|반)?", at)
    if m:
        h = int(m.group(2)) % 12 if m.group(1) else int(m.group(2))
        if m.group(1) == "오후":
            h += 12
        mi = 30 if "반" in at else int(m.group(3) or 0)
        t = now.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
        if t <= now:
            t += timedelta(hours=12) if not m.group(1) and h < 12 and t + timedelta(hours=12) > now else timedelta(days=1)
        return t
    return None


def set_reminder(text: str, minutes: float | None = None, at: str = "") -> dict:
    text = (text or "").strip() or "알림"
    if minutes:
        due = datetime.now() + timedelta(minutes=float(minutes))
    elif at:
        due = _parse_at(at)
        if not due:
            return {"ok": False, "error": f"'{at}' 시각을 못 알아들었어요. 'HH:MM'이나 minutes로 주세요."}
    else:
        return {"ok": False, "error": "minutes(몇 분 뒤) 또는 at(시각)이 필요해요."}
    rid = store.post("reminders", {"text": text, "due": int(due.timestamp() * 1000), "done": False,
                                   "created": store.now_ms()})
    refresh()
    return {"ok": True, "id": rid, "when": due.strftime("%m/%d %H:%M"), "text": text}


def list_reminders() -> dict:
    refresh()
    with _lock:
        rows = [r for r in _cache if not r.get("done")]
    return {"ok": True, "reminders": [{"id": r["id"], "text": r.get("text", ""),
                                       "when": datetime.fromtimestamp(r["due"] / 1000).strftime("%m/%d %H:%M")}
                                      for r in rows]}


def cancel_reminder(reminder_id: str = "", text: str = "") -> dict:
    refresh()
    with _lock:
        rows = [r for r in _cache if not r.get("done")]
    hit = next((r for r in rows if r["id"] == reminder_id), None) if reminder_id else None
    if not hit and text:
        hit = next((r for r in rows if text.strip() in r.get("text", "")), None)
    if not hit:
        return {"ok": False, "error": "그 알림을 못 찾았어요. list_reminders로 확인해 보세요."}
    store.delete(f"reminders/{hit['id']}")
    refresh()
    return {"ok": True, "cancelled": hit.get("text", "")}
