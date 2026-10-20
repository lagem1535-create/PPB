"""브라우저 확장(퍼플루 브라우저 손)과의 연결 — 크롬·웨일·엣지 등 크로뮴 브라우저 여러 개를 함께 받는다.

확장은 ws://127.0.0.1:<포트>/ext 로 붙고, 퍼플루 도구는 call()로 명령을 보내 결과를 기다린다.
명령은 '마지막으로 사용자가 쓴(창을 누른) 브라우저'로 간다.
이 PC 안(127.0.0.1)에서 온, 확장 주소(chrome-extension://)의 연결만 받는다.
"""
import asyncio
import itertools
import json
import time

_conns: dict = {}      # ws → {"name": "크롬", "focus": 마지막으로 쓴 시각}
_loop = None           # 탭 서버의 이벤트 루프
_waiting: dict[int, asyncio.Future] = {}
_ids = itertools.count(1)

EXT_KEYS = ("browser_real_input", "browser_highlights", "security_level", "work_indicator", "work_indicator_color", "color")


def _alive():
    return [(ws, info) for ws, info in list(_conns.items()) if not ws.closed]


def connected() -> bool:
    return bool(_alive())


def names() -> list[str]:
    return [info["name"] for _, info in _alive()]


_prefer = {"name": "", "until": 0.0}


def prefer(name: str, seconds: float = 180):
    """'@웨일'처럼 사용자가 브라우저를 고르면, 한동안 그 브라우저로 명령을 보낸다."""
    _prefer.update(name=name, until=time.monotonic() + seconds)


def _current():
    alive = _alive()
    if not alive:
        return None, None
    if _prefer["name"] and time.monotonic() < _prefer["until"]:
        for ws, info in alive:
            if info["name"] == _prefer["name"]:
                return ws, info
    return max(alive, key=lambda x: x[1]["focus"])


def current_name() -> str:
    _, info = _current()
    return info["name"] if info else ""


async def handle(ws, loop):
    """서버가 /ext 웹소켓을 넘겨준다. 끊길 때까지 응답을 받아 기다리는 도구에 전달."""
    global _loop
    _loop = loop
    _conns[ws] = {"name": "브라우저", "focus": time.monotonic()}
    await _send_settings(ws)
    ping = loop.create_task(_keepalive(ws))
    try:
        async for msg in ws:
            try:
                data = json.loads(msg.data)
            except (ValueError, TypeError):
                continue
            if data.get("type") == "hello":
                _conns[ws]["name"] = data.get("browser") or "브라우저"
                print(f"브라우저 확장 연결됨: {_conns[ws]['name']} (확장 {data.get('version')})")
            elif data.get("type") == "focus":
                _conns[ws]["focus"] = time.monotonic()
            fut = _waiting.pop(data.get("id"), None) if data.get("id") else None
            if fut and not fut.done():
                fut.set_result(data)
    finally:
        ping.cancel()
        info = _conns.pop(ws, {})
        print(f"브라우저 확장 연결 끊김: {info.get('name', '')}")


async def _send_settings(ws):
    from . import config
    s = config.settings()
    await ws.send_str(json.dumps({"type": "settings", "data": {k: s.get(k) for k in EXT_KEYS}}))


def push_settings(changes: dict):
    """퍼플루 설정이 바뀌면 확장들에도 알려 준다 (하이라이트·작업 표시 켜기/끄기, 색 등)."""
    if _loop and set(changes) & set(EXT_KEYS):
        for ws, _ in _alive():
            asyncio.run_coroutine_threadsafe(_send_settings(ws), _loop)


async def _keepalive(ws):
    """확장(서비스 워커)이 잠들지 않게 20초마다 신호."""
    while True:
        await asyncio.sleep(20)
        try:
            await ws.send_str('{"type":"ping"}')
        except Exception:
            return


async def _send(ws, cmd, args, timeout):
    rid = next(_ids)
    fut = asyncio.get_running_loop().create_future()
    _waiting[rid] = fut
    await ws.send_str(json.dumps({"id": rid, "cmd": cmd, "args": args}, ensure_ascii=False))
    try:
        return await asyncio.wait_for(fut, timeout)
    finally:
        _waiting.pop(rid, None)


def call(cmd: str, args: dict | None = None, timeout: float = 25) -> dict:
    """도구 스레드에서 부른다: 마지막으로 쓴 브라우저의 확장에 명령을 보내고 결과를 기다린다."""
    ws, _ = _current()
    deadline = time.monotonic() + 10
    while not ws and time.monotonic() < deadline:  # 퍼플루가 막 켜졌거나 확장이 다시 붙는 중이면 잠깐 기다린다
        time.sleep(0.3)
        ws, _ = _current()
    if not ws:
        raise RuntimeError("브라우저 확장 '퍼플루 브라우저 손'이 연결돼 있지 않아요. 크롬·웨일·엣지에 확장을 설치하고 브라우저를 켜 두세요 "
                           "(설치 방법: README의 '브라우저 확장'). 그동안은 look_at_screen·click으로 해요.")
    reply = asyncio.run_coroutine_threadsafe(_send(ws, cmd, args or {}, timeout), _loop).result(timeout + 2)
    if not reply.get("ok"):
        raise RuntimeError(reply.get("error") or "브라우저에서 실패했어요")
    return reply.get("result") or {}
