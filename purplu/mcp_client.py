"""MCP 서버 붙이기: 설정에서 추가한 MCP 서버의 도구를 퍼플루가 쓸 수 있게 한다.

- 서버 목록은 data/mcp.json 에만 저장한다 (키·토큰이 들어갈 수 있어서 Firebase로 안 올림).
- 종류: stdio(명령어로 실행, 예: npx -y @modelcontextprotocol/server-filesystem D:\\) / http(주소) / sse(주소)
- 서버마다 작업 하나가 연결을 붙잡고 있고, 도구 호출은 그 작업의 줄(queue)로 보낸다
  (anyio 연결은 연 작업 안에서 닫아야 해서).
"""
import asyncio
import json
import re
import threading
import time

from . import config

FILE = config.DATA_DIR / "mcp.json"
LOG_DIR = config.DATA_DIR / "mcp_logs"

_loop: asyncio.AbstractEventLoop | None = None
_tasks: dict[str, asyncio.Task] = {}
_queues: dict[str, asyncio.Queue] = {}
status: dict[str, dict] = {}        # 이름 → {"state": connecting|ok|error|off, "error": "", "tools": [Tool…]}
listeners = []                      # 상태가 바뀌면 부를 함수 (설정창, 퍼플루 다시 연결)
_lock = threading.Lock()


# ---------------- 저장 ----------------
def load() -> list[dict]:
    try:
        return json.loads(FILE.read_text(encoding="utf-8")).get("servers", [])
    except Exception:
        return []


def save(servers: list[dict]):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"servers": servers}, ensure_ascii=False, indent=2), encoding="utf-8")
    reload()


def parse_config_json(text: str) -> list[dict]:
    """Claude·Cursor 에서 쓰는 {"mcpServers": {...}} 모양을 그대로 받아 준다."""
    data = json.loads(text)
    if isinstance(data, dict) and "mcpServers" in data:
        data = data["mcpServers"]
    if isinstance(data, dict) and ("command" in data or "url" in data):
        data = {data.get("name") or "서버": data}
    out = []
    for name, c in (data or {}).items():
        if not isinstance(c, dict):
            continue
        if c.get("url"):
            kind = "sse" if c.get("type") == "sse" or str(c["url"]).rstrip("/").endswith("/sse") else "http"
            out.append({"name": name, "type": kind, "url": c["url"], "headers": c.get("headers") or {}, "enabled": True})
        else:
            out.append({"name": name, "type": "stdio", "command": c.get("command", ""), "args": c.get("args") or [],
                        "env": c.get("env") or {}, "enabled": True})
    return out


# ---------------- 돌리기 ----------------
def start():
    """퍼플루가 켜질 때 한 번: 뒤에서 도는 이벤트 루프를 만들고 켜진 서버에 붙는다."""
    global _loop
    with _lock:
        if _loop:
            return
        _loop = asyncio.new_event_loop()
        threading.Thread(target=_loop.run_forever, daemon=True, name="mcp").start()
    reload()


def reload():
    if not _loop:
        return
    asyncio.run_coroutine_threadsafe(_reload(), _loop)


async def _reload():
    for t in list(_tasks.values()):
        t.cancel()
    for t in list(_tasks.values()):
        try:
            await t
        except BaseException:
            pass
    _tasks.clear()
    _queues.clear()
    status.clear()
    for s in load():
        name = s.get("name") or "서버"
        if not s.get("enabled", True):
            status[name] = {"state": "off", "error": "", "tools": []}
            continue
        status[name] = {"state": "connecting", "error": "", "tools": []}
        _queues[name] = asyncio.Queue()
        _tasks[name] = asyncio.create_task(_serve(name, s))
    _changed()


def _changed():
    for fn in list(listeners):
        try:
            fn()
        except Exception:
            pass


def _transport(s: dict):
    kind = s.get("type", "stdio")
    if kind == "stdio":
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        import os
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log = open(LOG_DIR / f"{re.sub(r'[^\w.-]', '_', s.get('name', 'server'))}.log", "a", encoding="utf-8")
        env = {**os.environ, **{k: str(v) for k, v in (s.get("env") or {}).items()}}
        params = StdioServerParameters(command=s.get("command", ""), args=[str(a) for a in s.get("args") or []],
                                       env=env, cwd=s.get("cwd") or None)
        return stdio_client(params, errlog=log)   # 퍼플루는 창 없이 돌아서 stderr 대신 파일로
    if kind == "sse":
        from mcp.client.sse import sse_client
        return sse_client(s["url"], headers=s.get("headers") or None)
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client
    return streamable_http_client(s["url"], http_client=create_mcp_http_client(headers=s.get("headers") or None))


async def _serve(name: str, s: dict):
    """연결 → 도구 목록 → 부탁(도구 호출)을 기다리며 연결 유지. 끊기면 잠깐 쉬고 다시."""
    from mcp import ClientSession
    wait = 3
    while True:
        try:
            async with _transport(s) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as sess:
                    await asyncio.wait_for(sess.initialize(), 40)
                    tools = (await sess.list_tools()).tools
                    status[name] = {"state": "ok", "error": "", "tools": tools}
                    _changed()
                    wait = 3
                    q = _queues[name]
                    while True:
                        tool, args, fut = await q.get()
                        try:
                            r = await sess.call_tool(tool, args, read_timeout_seconds=120)
                            if not fut.done():
                                fut.set_result(r)
                        except Exception as e:
                            if not fut.done():
                                fut.set_exception(e)
                            if "closed" in str(e).lower():
                                raise
        except asyncio.CancelledError:
            raise
        except BaseException as e:   # ExceptionGroup 도
            msg = _short_error(e)
            status[name] = {"state": "error", "error": msg, "tools": []}
            _changed()
        await asyncio.sleep(wait)
        wait = min(60, wait * 2)
        status[name] = {"state": "connecting", "error": status[name].get("error", ""), "tools": [], "tried": True}
        _changed()


def _short_error(e: BaseException) -> str:
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    text = f"{type(e).__name__}: {e}"
    if isinstance(e, FileNotFoundError):
        text = "명령어를 못 찾았어요 (예: npx 는 Node.js가 있어야 해요)"
    return text[:200]


def wait_ready(timeout: float = 6):
    """아직 연결 중인 서버가 있으면 조금 기다린다 (퍼플루가 Gemini에 도구 목록을 보내기 전에)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end and any(v["state"] == "connecting" and not v.get("tried") for v in status.values()):
        time.sleep(0.2)


# ---------------- 도구 ----------------
def _slug(t: str) -> str:
    t = re.sub(r"[^A-Za-z0-9_]", "_", t)
    return re.sub(r"_+", "_", t).strip("_") or "x"


_names: dict[str, tuple[str, str]] = {}   # Gemini에 보낸 이름 → (서버, 도구)


def tool_list() -> list[tuple[str, str, object]]:
    """(Gemini 이름, 서버, Tool) — 켜져서 연결된 서버의 도구만."""
    out = []
    used = set()
    for i, (server, st) in enumerate(status.items(), 1):
        if st["state"] != "ok":
            continue
        sv = _slug(server)
        sv = sv if sv != "x" else f"s{i}"
        for t in st["tools"]:
            name = f"mcp_{sv}__{_slug(t.name)}"[:64]
            k = 2
            while name in used:
                name = f"{name[:60]}_{k}"
                k += 1
            used.add(name)
            _names[name] = (server, t.name)
            out.append((name, server, t))
    return out


def find(gemini_name: str):
    if gemini_name not in _names:
        tool_list()
    server, tool = _names.get(gemini_name, (None, None))
    st = status.get(server or "", {})
    t = next((x for x in st.get("tools", []) if x.name == tool), None)
    return server, tool, t


def call(gemini_name: str, args: dict, timeout: float = 130) -> dict:
    server, tool, _ = find(gemini_name)
    if not server:
        return {"ok": False, "error": "그 MCP 도구를 못 찾았어요 (서버가 꺼졌거나 다시 연결 중)."}
    if status.get(server, {}).get("state") != "ok" or server not in _queues:
        return {"ok": False, "error": f"MCP 서버 '{server}'가 연결돼 있지 않아요."}
    fut = asyncio.run_coroutine_threadsafe(_ask(server, tool, args), _loop)
    try:
        r = fut.result(timeout)
    except Exception as e:
        return {"ok": False, "error": f"MCP '{server}' 오류: {_short_error(e)}"}
    return _result(server, tool, r)


async def _ask(server, tool, args):
    fut = asyncio.get_running_loop().create_future()
    await _queues[server].put((tool, args, fut))
    return await fut


def _result(server, tool, r) -> dict:
    texts, images = [], []
    for c in getattr(r, "content", None) or []:
        kind = getattr(c, "type", "")
        if kind == "text":
            texts.append(c.text)
        elif kind == "image":
            images.append(getattr(c, "mime_type", "image"))
        elif kind == "resource":
            res = getattr(c, "resource", None)
            texts.append(getattr(res, "text", None) or f"[자료 {getattr(res, 'uri', '')}]")
        else:
            texts.append(f"[{kind}]")
    sc = getattr(r, "structured_content", None)
    if sc and not texts:
        texts.append(json.dumps(sc, ensure_ascii=False)[:8000])
    text = "\n".join(texts)[:12000]
    out = {"ok": not getattr(r, "is_error", False), "mcp": f"{server}/{tool}", "text": text}
    if images:
        out["images"] = images
    if not out["ok"]:
        out["error"] = text[:300] or "MCP 도구가 실패했어요."
    return out


# ---------------- JSON 스키마 → Gemini ----------------
def to_schema(js: dict, depth: int = 0):
    from google.genai import types
    T = types.Type
    js = js or {}
    if depth > 6:
        return types.Schema(type=T.STRING)
    for key in ("anyOf", "oneOf"):   # 여러 모양이면 null 이 아닌 첫 번째
        if key in js:
            opts = [o for o in js[key] if isinstance(o, dict) and o.get("type") != "null"]
            if opts:
                return to_schema({**opts[0], "description": js.get("description") or opts[0].get("description")}, depth + 1)
    t = js.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    desc = (js.get("description") or "")[:500] or None
    if t == "object" or (t is None and "properties" in js):
        props = {k: to_schema(v, depth + 1) for k, v in (js.get("properties") or {}).items() if isinstance(v, dict)}
        if not props:
            return types.Schema(type=T.STRING, description=(desc or "") + " (JSON 글로)")
        req = [r for r in js.get("required") or [] if r in props]
        return types.Schema(type=T.OBJECT, properties=props, required=req or None, description=desc)
    if t == "array":
        return types.Schema(type=T.ARRAY, items=to_schema(js.get("items") or {"type": "string"}, depth + 1), description=desc)
    kind = {"integer": T.INTEGER, "number": T.NUMBER, "boolean": T.BOOLEAN}.get(t, T.STRING)
    enum = [str(e) for e in js.get("enum") or []] if kind == T.STRING and js.get("enum") else None
    return types.Schema(type=kind, description=desc, enum=enum)


def declarations():
    from google.genai import types
    out = []
    for name, server, t in tool_list():
        schema = t.input_schema or {}
        params = to_schema(schema) if (schema.get("properties")) else None
        if params is not None and params.type != types.Type.OBJECT:
            params = None
        desc = f"[MCP '{server}'] {(t.description or t.title or t.name)[:900]}"
        out.append(types.FunctionDeclaration(name=name, description=desc, parameters=params))
    return out


def fix_args(gemini_name: str, args: dict) -> dict:
    """'JSON 글로' 받은 칸(속을 모르는 객체)은 다시 객체로."""
    _, _, t = find(gemini_name)
    props = ((t.input_schema or {}).get("properties") or {}) if t else {}
    out = dict(args)
    for k, v in args.items():
        if isinstance(v, str) and (props.get(k) or {}).get("type") == "object":
            try:
                out[k] = json.loads(v)
            except Exception:
                pass
    return out
