"""퍼플루 브라우저(ownbrowser.py)를 켜고 명령을 보낸다. 죽으면 다음 명령 때 다시 켠다."""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_lock = threading.Lock()
_proc = None
_waiting: dict[int, dict] = {}
_next = [0]
hwnd = [0]                 # 대화창이 끼워 넣을 창 번호
listeners = []             # 새 창 번호가 생기면 부를 함수들 (대화창)


def _reader(p):
    for line in p.stdout:
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if "hwnd" in msg:
            hwnd[0] = msg["hwnd"]
            for fn in list(listeners):
                try:
                    fn(msg["hwnd"])
                except Exception:
                    pass
        elif msg.get("id") in _waiting:
            box = _waiting[msg["id"]]
            box["result"] = msg.get("result")
            box["ev"].set()
    hwnd[0] = 0


def alive() -> bool:
    return _proc is not None and _proc.poll() is None


def start():
    """켜져 있지 않으면 켠다. 창 번호가 올 때까지 잠깐 기다린다."""
    global _proc
    with _lock:
        if alive():
            return
        from . import config
        args = [sys.executable, "-m", "purplu.ownbrowser"]
        if config.settings().get("theme") != "light":
            args.append("--dark")
        st = config.settings()
        args.append("--color=" + (st.get("chat_color") or st.get("color") or "#8B5CF6"))
        import os
        args.append(f"--parent={os.getpid()}")
        hwnd[0] = 0
        _proc = subprocess.Popen(args, cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=_reader, args=(_proc,), daemon=True).start()
    deadline = time.monotonic() + 15
    while not hwnd[0] and alive() and time.monotonic() < deadline:
        time.sleep(0.05)


def call(cmd: str, args: dict | None = None, timeout: float = 30) -> dict:
    start()
    if not alive():
        return {"ok": False, "error": "퍼플루 브라우저를 못 켰어요."}
    with _lock:
        _next[0] += 1
        mid = _next[0]
        box = {"ev": threading.Event(), "result": None}
        _waiting[mid] = box
        try:
            _proc.stdin.write(json.dumps({"id": mid, "cmd": cmd, "args": args or {}}, ensure_ascii=False) + "\n")
            _proc.stdin.flush()
        except Exception as e:
            _waiting.pop(mid, None)
            return {"ok": False, "error": f"퍼플루 브라우저에 못 보냈어요: {e}"}
    try:
        if not box["ev"].wait(timeout):
            return {"ok": False, "error": "퍼플루 브라우저가 대답이 없어요 (시간 초과)."}
        return box["result"] or {"ok": False, "error": "빈 대답"}
    finally:
        _waiting.pop(mid, None)


def stop():
    global _proc
    if alive():
        try:
            _proc.stdin.close()
            _proc.wait(3)
        except Exception:
            _proc.kill()
    _proc = None
