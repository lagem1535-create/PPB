"""Firebase Realtime Database (로그인 없이 REST) — 설정과 대화목록 저장.

저장 방식 (data/firebase_url.txt):
  local            이 PC에만 (data/local_db.json)
  https://…        온라인 (Firebase) 에만
  both|https://…   이 PC + 온라인 같이: 먼저 이 PC에 쓰고(인터넷 없어도 됨) 뒤에서 온라인에도 쓴다.
                   못 보낸 건 data/sync_queue.json 에 모아 두었다가 인터넷이 돌아오면 보낸다.
                   다른 PC가 바꾼 건 온라인에서 받아 이 PC에도 넣는다. (rtc 는 온라인에만)

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

LOCAL = "local"
BOTH = "both|"


def clean_url(url: str) -> str:
    """'https://x.firebasedatabase.app/' · '…/.json' → 'https://x.firebasedatabase.app'"""
    u = (url or "").strip().rstrip("/")
    if u.endswith(".json"):
        u = u[:-5].rstrip("/")
    return u


def parse(raw: str) -> tuple[str, str]:
    """파일 글 → (방식, Firebase 주소). 방식: 'local' · 'online' · 'both' · '' (아직 없음)."""
    raw = (raw or "").strip()
    if raw == LOCAL:
        return "local", ""
    if raw.startswith(BOTH):
        return "both", clean_url(raw[len(BOTH):])
    return ("online", clean_url(raw)) if raw else ("", "")


def _db_url() -> str:
    """Firebase 주소는 코드에 두지 않는다 (로그인 없는 DB라 주소가 곧 열쇠). data/firebase_url.txt 에서 읽는다."""
    path = Path(__file__).resolve().parent.parent / "data" / "firebase_url.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""   # 아직 없음 → 처음 켤 때 '퍼플루 시작하기' 창에서 넣는다


MODE, REMOTE = parse(_db_url())
DB_URL = LOCAL if MODE == "local" else REMOTE   # 예전 이름 (탭 주소 등에서 Firebase 주소로 쓴다)
ROOT = "purplu"
_client = httpx.Client(timeout=10)


def set_url(url: str):
    """처음 설정 창에서 주소를 넣으면 바로 쓰게. ('local' · 'https://…' · 'both|https://…')"""
    global MODE, REMOTE, DB_URL
    MODE, REMOTE = parse(url)
    DB_URL = LOCAL if MODE == "local" else REMOTE


def _url(path: str, base: str | None = None) -> str:
    base = clean_url(base) if base else REMOTE
    if not base:
        raise RuntimeError("Firebase 주소가 아직 없어요 (처음 설정에서 연결 코드를 넣어 주세요)")
    return f"{base}/{ROOT}/{path.strip('/')}.json" if path.strip("/") else f"{base}/{ROOT}.json"


# ---- 'local' = Firebase 없이 이 PC에만 저장 (data/local_db.json). 처음 쓰는 사람은 이걸로 바로 시작 ----
_LOCAL_FILE = Path(__file__).resolve().parent.parent / "data" / "local_db.json"
_local_lock = threading.Lock()
_local_tree = None


def is_local() -> bool:
    return MODE == "local"


def is_both() -> bool:
    return MODE == "both"


def _here(path: str) -> bool:
    """이 PC 파일에서 읽고 쓰나? (이 PC + 온라인 이어도 rtc 는 온라인에만)"""
    return is_local() or (is_both() and path.strip("/").split("/")[0] != "rtc")


def _merge(dst: dict, src: dict):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


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
            if key is None:
                _ltree().clear()
            else:
                parent.pop(key, None)
        elif op == "merge":   # 받은 나무를 합치기 (같은 자리는 받은 쪽)
            _merge(_ltree() if key is None else parent.setdefault(key, {}), value or {})
        elif op == "replace":   # 통째로 바꾸기
            _ltree().clear()
            _ltree().update(value or {})
        _lsave()
    for fn in list(_local_listeners):   # 같은 PC 안에서 바뀐 걸 알려 준다 (Firebase 스트림 대신)
        try:
            fn(path)
        except Exception:
            pass


_local_listeners = []


def remote(op: str, path: str, value=None, base: str | None = None):
    """온라인(Firebase)에 바로. base 를 주면 그 주소로 (옮길 때)."""
    url = _url(path, base)
    trace.cmd(f"HTTP {op.upper()} {url}")
    if op == "get":
        r = _client.get(url)
        r.raise_for_status()
        return r.json()
    if op == "post":
        r = _client.post(url, json=value)
        r.raise_for_status()
        return r.json()["name"]
    {"put": _client.put, "patch": _client.patch}.get(op, lambda u, json=None: _client.delete(u))(url, json=value).raise_for_status()


def get(path: str):
    return _local("get", path) if _here(path) else remote("get", path)


def put(path: str, value):
    if not _here(path):
        return remote("put", path, value)
    _local("put", path, value)
    _mirror("put", path, value)


def patch(path: str, value: dict):
    if not _here(path):
        return remote("patch", path, value)
    _local("patch", path, value)
    _mirror("patch", path, value)


def post(path: str, value) -> str:
    if not _here(path):
        return remote("post", path, value)
    name = _local("post", path, value)
    _mirror("put", f"{path.strip('/')}/{name}", value)   # 온라인에도 같은 이름으로
    return name


def delete(path: str):
    if not _here(path):
        return remote("delete", path)
    _local("delete", path)
    _mirror("delete", path)


# ---- 이 PC + 온라인: 온라인에 보낼 것 줄 세우기 (인터넷이 없으면 모아 뒀다가) ----
_QUEUE_FILE = _LOCAL_FILE.with_name("sync_queue.json")
_queue_lock = threading.Lock()
_queue = None
_queue_wake = threading.Event()
sync_state = {"online": None, "pending": 0, "error": ""}   # 설정창에 보여 줄 상태


def _q() -> list:
    global _queue
    if _queue is None:
        try:
            _queue = json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _queue = []
    return _queue


def _qsave():
    tmp = _QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_q(), ensure_ascii=False), encoding="utf-8")
    tmp.replace(_QUEUE_FILE)


def _mirror(op: str, path: str, value=None):
    if not is_both():
        return
    with _queue_lock:
        _q().append([op, path, value])
        _qsave()
        sync_state["pending"] = len(_q())
    _start_flusher()
    _queue_wake.set()


_flusher = None


def _start_flusher():
    global _flusher
    if _flusher is not None or not is_both():
        return

    def run():
        wait = 1
        while True:
            _queue_wake.wait(timeout=30)
            _queue_wake.clear()
            while True:
                with _queue_lock:
                    item = _q()[0] if _q() else None
                if item is None:
                    break
                try:
                    remote(item[0], item[1], item[2])
                except Exception as e:   # 인터넷 없음 등: 모아 둔 채로 조금 뒤에 다시
                    sync_state.update(online=False, error=str(e)[:120])
                    time.sleep(wait)
                    wait = min(wait * 2, 30)
                    continue
                wait = 1
                with _queue_lock:
                    if _q() and _q()[0] == item:
                        _q().pop(0)
                        _qsave()
                    sync_state.update(online=True, pending=len(_q()), error="")

    _flusher = threading.Thread(target=run, daemon=True, name="purplu-upload")
    _flusher.start()


def flush(timeout: float = 20) -> bool:
    """모아 둔 걸 다 보낼 때까지 잠깐 기다린다 (방식을 바꾸기 전에). 다 보냈으면 True."""
    _start_flusher()
    _queue_wake.set()
    end = time.time() + timeout
    while time.time() < end:
        with _queue_lock:
            if not _q():
                return True
        time.sleep(0.3)
    return False


# ---- 옮기기: 이 PC ↔ 온라인 ----
def check_remote(url: str) -> str:
    """Firebase 주소가 맞는지 (읽어 보기). 맞으면 깨끗한 주소를 돌려준다."""
    u = clean_url(url)
    if not u.startswith("https://") or "firebase" not in u:
        raise ValueError("Firebase 주소(https://…firebasedatabase.app 또는 …firebaseio.com)를 넣어 주세요")
    r = _client.get(f"{u}/{ROOT}.json", params={"shallow": "true"}, timeout=12)
    if r.status_code in (401, 403):
        raise ValueError("이 Firebase 는 읽기가 막혀 있어요 (규칙에서 read/write 를 true 로 해 주세요)")
    r.raise_for_status()
    return u


def local_tree() -> dict:
    return _local("get", "") or {}


def remote_tree(url: str | None = None) -> dict:
    t = remote("get", "", base=url) or {}
    t.pop("rtc", None)
    return t


def upload_tree(tree: dict, url: str | None = None):
    """이 나무를 온라인에 합쳐 넣기 (윗칸마다 PATCH: 같은 대화는 덮고, 다른 대화는 그대로 둔다)."""
    for top, val in (tree or {}).items():
        if top == "rtc":
            continue
        if isinstance(val, dict) and val:
            remote("patch", top, val, base=url)
        elif not isinstance(val, dict):
            remote("put", top, val, base=url)


def wipe_remote(url: str | None = None):
    remote("delete", "", base=url)


def save_local_tree(tree: dict, merge: bool = False):
    """이 PC 파일에 넣기 (바꾸기 전 것은 local_db.backup.json 으로 남긴다)."""
    try:
        if _LOCAL_FILE.exists():
            _LOCAL_FILE.with_name("local_db.backup.json").write_text(_LOCAL_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass
    tree = {k: v for k, v in (tree or {}).items() if k != "rtc"}
    _local("merge" if merge else "replace", "", tree)


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
    if is_local() or is_both():   # 같은 PC 안에서 바뀐 것
        _local_listeners.append(lambda path: _dispatch({"path": "/" + path.strip("/")}, on_settings, on_conversations, on_memos))
    if is_local():
        return
    if is_both():
        _start_flusher()

    def run():
        backoff = 1
        while True:
            try:
                # Firebase는 30초마다 살아 있다는 신호를 보낸다 → 45초 동안 아무것도 없으면 멈춘 연결로 보고 새로 붙는다
                with httpx.stream("GET", f"{REMOTE}/{ROOT}.json", headers={"Accept": "text/event-stream"},
                                  timeout=httpx.Timeout(8, read=45)) as r:
                    r.raise_for_status()
                    backoff = 1
                    event = None
                    for line in r.iter_lines():
                        if line.startswith("event:"):
                            event = line[6:].strip()
                        elif line.startswith("data:") and event in ("put", "patch"):
                            msg = json.loads(line[5:])
                            if is_both() and _take_remote(event, msg):
                                continue   # 이 PC 파일에 넣었고, 그쪽 알림으로 화면이 바뀐다
                            _dispatch(msg, on_settings, on_conversations, on_memos)
                        elif event == "auth_revoked" or event == "cancel":
                            break
            except Exception as e:
                print("Firebase 동기화 다시 연결:", e)
            time.sleep(backoff)
            backoff = min(backoff * 2, 3)  # 인터넷이 잠깐 끊겨도 돌아오면 3초 안에 다시 동기화

    threading.Thread(target=run, daemon=True, name="purplu-sync").start()


def _take_remote(event: str, msg: dict) -> bool:
    """이 PC + 온라인: 다른 PC가 바꾼 걸 이 PC 파일에도. 넣었으면 True (rtc 는 그냥 알림만)."""
    path = (msg.get("path") or "/").strip("/")
    data = msg.get("data")
    if path.split("/")[0] == "rtc":
        return False
    if not path:   # 처음 붙을 때 받는 통째: 합치기 (이 PC에만 있던 건 남긴다)
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "rtc"}
            _local("merge", "", data)
            if "rtc" in (msg.get("data") or {}):
                return False
        return True
    if event == "put":
        _local("delete" if data is None else "put", path, data)
    else:
        for k, v in (data or {}).items():
            _local("delete" if v is None else "put", f"{path}/{k}", v)
    return True


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
