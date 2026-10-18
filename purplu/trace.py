"""도구가 실제로 실행하는 명령(파이썬 함수 호출, 프로그램 실행, HTTP 요청)을 알려 주는 장치.

두뇌가 도구를 실행할 때 sink를 걸어 두면, 그 도구 안에서 cmd("...")로 남긴 줄이 말풍선에 나온다.
asyncio.to_thread는 contextvars를 같이 넘겨 주므로 도구 스레드에서도 그대로 보인다.
도구 밖(배경 동기화 등)에서는 아무것도 안 한다.
"""
import contextvars

_sink = contextvars.ContextVar("purplu_trace", default=None)


def cmd(text: str) -> None:
    fn = _sink.get()
    if fn:
        fn(str(text)[:300])


def run_with(sink, func, *args):
    token = _sink.set(sink)
    try:
        return func(*args)
    finally:
        _sink.reset(token)
