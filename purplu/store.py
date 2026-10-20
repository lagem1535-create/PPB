"""Firebase Realtime Database (로그인 없이 REST) — 설정과 대화목록 저장.

구조:
  /purplu/settings                     설정 (API 키는 절대 여기 안 올림)
  /purplu/conversations/<id>           {title, created, updated}
  /purplu/messages/<id>/<push id>      {role: "user"|"model", text, t}
"""
import json
import threading
import time

import httpx

from . import trace

def _db_url() -> str:
    """Firebase 주소는 코드에 두지 않는다 (로그인 없는 DB라 주소가 곧 열쇠). data/firebase_url.txt 에서 읽는다."""
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "data" / "firebase_url.txt"
    try:
        return path.read_text(encoding="utf-8").strip().rstrip("/")
    except OSError:
        raise SystemExit("data\firebase_url.txt 에 Firebase Realtime Database 주소를 넣어 주세요 (README '처음 설치').")


DB_URL = _db_url()
ROOT = "purplu"
_client = httpx.Client(timeout=10)


def _url(path: str) -> str:
    return f"{DB_URL}/{ROOT}/{path.strip('/')}.json"


def get(path: str):
    trace.cmd(f"HTTP GET {_url(path)}")
    r = _client.get(_url(path))
    r.raise_for_status()
    return r.json()


def put(path: str, value):
    trace.cmd(f"HTTP PUT {_url(path)}")
    _client.put(_url(path), json=value).raise_for_status()


def patch(path: str, value: dict):
    trace.cmd(f"HTTP PATCH {_url(path)}")
    _client.patch(_url(path), json=value).raise_for_status()


def post(path: str, value) -> str:
    trace.cmd(f"HTTP POST {_url(path)}")
    r = _client.post(_url(path), json=value)
    r.raise_for_status()
    return r.json()["name"]


def delete(path: str):
    trace.cmd(f"HTTP DELETE {_url(path)}")
    _client.delete(_url(path)).raise_for_status()


def in_background(fn, *args):
    """UI를 멈추지 않게 저장은 뒤에서. 실패해도 앱은 계속 돈다."""
    def run():
        try:
            fn(*args)
        except Exception as e:
            print("Firebase 저장 실패:", e)
    threading.Thread(target=run, daemon=True).start()


# ---- 대화목록 ----

def now_ms() -> int:
    return int(time.time() * 1000)


def new_conversation(title: str = "새 대화") -> str:
    t = now_ms()
    return post("conversations", {"title": title, "created": t, "updated": t})


def list_conversations() -> list[dict]:
    data = get("conversations") or {}
    rows = [{"id": k, **v} for k, v in data.items() if isinstance(v, dict)]
    return sorted(rows, key=lambda r: r.get("updated", 0), reverse=True)


def rename_conversation(cid: str, title: str):
    patch(f"conversations/{cid}", {"title": title})


def delete_conversation(cid: str):
    delete(f"messages/{cid}")
    delete(f"conversations/{cid}")


def messages(cid: str) -> list[dict]:
    data = get(f"messages/{cid}") or {}
    return [data[k] for k in sorted(data)]  # push id는 시간순으로 정렬됨


def add_message(cid: str, role: str, text: str):
    t = now_ms()
    post(f"messages/{cid}", {"role": role, "text": text, "t": t})
    patch(f"conversations/{cid}", {"updated": t})


# ---- 실시간 동기화: Firebase가 바뀌면 바로 알려 준다 (REST 스트리밍, 로그인 없음) ----

def listen(on_settings, on_conversations, on_memos=None):
    """/purplu 아래가 바뀔 때마다 on_settings(dict) / on_conversations() 를 부른다. 끊기면 다시 붙는다."""
    def run():
        backoff = 1
        while True:
            try:
                # Firebase는 30초마다 살아 있다는 신호를 보낸다 → 45초 동안 아무것도 없으면 멈춘 연결로 보고 새로 붙는다
                with httpx.stream("GET", f"{DB_URL}/{ROOT}.json", headers={"Accept": "text/event-stream"},
                                  timeout=httpx.Timeout(8, read=45)) as r:
                    r.raise_for_status()
                    backoff = 1
                    event = None
                    for line in r.iter_lines():
                        if line.startswith("event:"):
                            event = line[6:].strip()
                        elif line.startswith("data:") and event in ("put", "patch"):
                            _dispatch(json.loads(line[5:]), on_settings, on_conversations, on_memos)
                        elif event == "auth_revoked" or event == "cancel":
                            break
            except Exception as e:
                print("Firebase 동기화 다시 연결:", e)
            time.sleep(backoff)
            backoff = min(backoff * 2, 3)  # 인터넷이 잠깐 끊겨도 돌아오면 3초 안에 다시 동기화

    threading.Thread(target=run, daemon=True, name="purplu-sync").start()


def _dispatch(msg: dict, on_settings, on_conversations, on_memos=None):
    path = (msg.get("path") or "/").strip("/")
    top = path.split("/")[0] if path else ""
    if top in ("", "settings"):
        try:
            settings = get("settings")
        except Exception:
            settings = None
        if isinstance(settings, dict):
            on_settings(settings)
    if top in ("", "conversations", "messages"):
        on_conversations()
    if top in ("", "memos") and on_memos:
        on_memos()
    if top in ("", "reminders"):
        from .tools import reminders
        reminders.refresh()


# ---- 메모 ----

def add_memo(text: str, pinned: bool = True) -> str:
    return post("memos", {"text": text, "created": now_ms(), "pinned": pinned})


def list_memos() -> list[dict]:
    data = get("memos") or {}
    rows = [{"id": k, **v} for k, v in data.items() if isinstance(v, dict)]
    return sorted(rows, key=lambda r: r.get("created", 0), reverse=True)


def update_memo(mid: str, **fields):
    patch(f"memos/{mid}", fields)


def delete_memo(mid: str):
    delete(f"memos/{mid}")
