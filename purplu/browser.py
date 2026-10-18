"""크롬 확장(퍼플루 브라우저 손)과의 연결.

확장은 ws://127.0.0.1:<포트>/ext 로 붙고, 퍼플루 도구는 call()로 명령을 보내 결과를 기다린다.
이 PC 안(127.0.0.1)에서 온, 크롬 확장 주소(chrome-extension://)의 연결만 받는다.
"""
import asyncio
import itertools
import json

_ws = None            # 지금 연결된 확장
_loop = None          # 탭 서버의 이벤트 루프
_waiting: dict[int, asyncio.Future] = {}
_ids = itertools.count(1)


def connected() -> bool:
    return _ws is not None and not _ws.closed


async def handle(ws, loop):
    """서버가 /ext 웹소켓을 넘겨준다. 끊길 때까지 응답을 받아 기다리는 도구에 전달."""
    global _ws, _loop
    _ws, _loop = ws, loop
    print("크롬 확장 연결됨")
    ping = loop.create_task(_keepalive(ws))
    try:
        async for msg in ws:
            try:
                data = json.loads(msg.data)
            except (ValueError, TypeError):
                continue
            fut = _waiting.pop(data.get("id"), None) if data.get("id") else None
            if fut and not fut.done():
                fut.set_result(data)
    finally:
        ping.cancel()
        if _ws is ws:
            _ws = None
        print("크롬 확장 연결 끊김")


async def _keepalive(ws):
    """크롬 확장(서비스 워커)이 잠들지 않게 20초마다 신호."""
    while True:
        await asyncio.sleep(20)
        try:
            await ws.send_str('{"type":"ping"}')
        except Exception:
            return


async def _send(cmd, args, timeout):
    rid = next(_ids)
    fut = asyncio.get_running_loop().create_future()
    _waiting[rid] = fut
    await _ws.send_str(json.dumps({"id": rid, "cmd": cmd, "args": args}, ensure_ascii=False))
    try:
        return await asyncio.wait_for(fut, timeout)
    finally:
        _waiting.pop(rid, None)


def call(cmd: str, args: dict | None = None, timeout: float = 25) -> dict:
    """도구 스레드에서 부른다: 확장에 명령을 보내고 결과를 기다린다."""
    if not connected():
        raise RuntimeError("크롬 확장 '퍼플루 브라우저 손'이 연결돼 있지 않아요. 크롬에 확장을 설치하고 크롬을 켜 두세요 "
                           "(설치 방법: README의 '크롬 확장'). 그동안은 look_at_screen·click으로 해요.")
    reply = asyncio.run_coroutine_threadsafe(_send(cmd, args or {}, timeout), _loop).result(timeout + 2)
    if not reply.get("ok"):
        raise RuntimeError(reply.get("error") or "크롬에서 실패했어요")
    return reply.get("result") or {}
