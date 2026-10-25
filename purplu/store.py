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
from pathlib import Path

from . import trace

def _db_url() -> str:
    """Firebase 주소는 코드에 두지 않는다 (로그인 없는 DB라 주소가 곧 열쇠). data/firebase_url.txt 에서 읽는다."""
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "data" / "firebase_url.txt"
    try:
        return path.read_text(encoding="utf-8").strip().rstrip("/")
    except OSError:
        return ""   # 아직 없음 → 처음 켤 때 '퍼플루 시작하기' 창에서 넣는다


DB_URL = _db_url()
ROOT = "purplu"
_client = httpx.Client(timeout=10)


def set_url(url: str):
    """처음 설정 창에서 주소를 넣으면 바로 쓰게."""
    global DB_URL
    DB_URL = url.strip().rstrip("/")


def _url(path: str) -> str:
    if not DB_URL:
        raise RuntimeError("Firebase 주소가 아직 없어요 (처음 설정에서 연결 코드를 넣어 주세요)")
    return f"{DB_URL}/{ROOT}/{path.strip('/')}.json"


# ---- 'local' = Firebase 없이 이 PC에만 저장 (data/local_db.json). 처음 쓰는 사람은 이걸로 바로 시작 ----
LOCAL = "local"
_LOCAL_FILE = Path(__file__).resolve().parent.parent / "data" / "local_db.json"
_local_lock = threading.Lock()
_local_tree = None


def is_local() -> bool:
    return DB_URL == LOCAL


def _ltree() -> dict:
    global _local_tree
    if _local_tree is None:
        try:
            _local_tree = json.loads(_LOCAL_FILE.read_text(encoding="utf-8"))
        except Exception:
            _local_tree = {}
    return _local_tree


def _lsave():
    _LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _LOCAL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_local_tree, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_LOCAL_FILE)


def _lwalk(path: str, make=False):
    node, keys = _ltree(), [k for k in path.strip("/").split("/") if k]
    for k in keys[:-1]:
        if k not in node or not isinstance(node[k], dict):
            if not make:
                return None, None
            node[k] = {}
        node = node[k]
    return node, (keys[-1] if keys else None)


def _local(op: str, path: str, value=None):
    import copy
    import secrets
    with _local_lock:
        if op == "get":
            if not path.strip("/"):
                return copy.deepcopy(_ltree())
            parent, key = _lwalk(path)
            return copy.deepcopy(parent.get(key)) if parent is not None else None
        parent, key = _lwalk(path, make=True)
        if op == "put":
            parent[key] = value
        elif op == "patch":
            cur = parent.get(key) if isinstance(parent.get(key), dict) else {}
            cur.update(value or {})
            parent[key] = cur
        elif op == "post":   # 시간 순서로 정렬되는 이름 (Firebase push id 처럼)
            name = f"-{now_ms():013d}{secrets.token_hex(3)}"
            node = parent.setdefault(key, {}) if isinstance(parent.get(key), dict) else parent.setdefault(key, {})
            node[name] = value
            _lsave()
            return name
        elif op == "delete":
            parent.pop(key, None)
        _lsave()
    for fn in list(_local_listeners):   # 같은 PC 안에서 바뀐 걸 알려 준다 (Firebase 스트림 대신)
        try:
            fn(path)
        except Exception:
            pass


_local_listeners = []


def get(path: str):
    if is_local():
        return _local("get", path)
    trace.cmd(f"HTTP GET {_url(path)}")
    r = _client.get(_url(path))
    r.raise_for_status()
    return r.json()


def put(path: str, value):
    if is_local():
        return _local("put", path, value)
    trace.cmd(f"HTTP PUT {_url(path)}")
    _client.put(_url(path), json=value).raise_for_status()


def patch(path: str, value: dict):
    if is_local():
        return _local("patch", path, value)
    trace.cmd(f"HTTP PATCH {_url(path)}")
    _client.patch(_url(path), json=value).raise_for_status()


def post(path: str, value) -> str:
    if is_local():
        return _local("post", path, value)
    trace.cmd(f"HTTP POST {_url(path)}")
    r = _client.post(_url(path), json=value)
    r.raise_for_status()
    return r.json()["name"]


def delete(path: str):
    if is_local():
        return _local("delete", path)
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


def add_message(cid: str, role: str, text: str, steps: list | None = None, meta: dict | None = None):
    t = now_ms()
    row = {"role": role, "text": text, "t": t}
    if steps:
        row["steps"] = steps[:20]  # 실행한 명령 (대화창에서 다시 볼 수 있게)
    if meta:
        row["meta"] = meta         # 대답한 모델 · 글/말 · 노력 · 걸린 시간 (대화창의 ⋯)
    post(f"messages/{cid}", row)
    patch(f"conversations/{cid}", {"updated": t})


# ---- 실시간 동기화: Firebase가 바뀌면 바로 알려 준다 (REST 스트리밍, 로그인 없음) ----

def listen(on_settings, on_conversations, on_memos=None):
    """/purplu 아래가 바뀔 때마다 on_settings(dict) / on_conversations() 를 부른다. 끊기면 다시 붙는다."""
    if is_local():
        _local_listeners.append(lambda path: _dispatch({"path": "/" + path.strip("/")}, on_settings, on_conversations, on_memos))
        return

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


rtc_listener = None   # WebRTC 연결 요청(/rtc)이 오면 부를 함수 (server.RtcBridge)


def _dispatch(msg: dict, on_settings, on_conversations, on_memos=None):
    path = (msg.get("path") or "/").strip("/")
    top = path.split("/")[0] if path else ""
    if top in ("", "rtc") and rtc_listener:
        try:
            rtc_listener()
        except Exception as e:
            print("WebRTC 요청 확인 실패:", e)
        if top == "rtc":
            return
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
