"""파이썬 코드 실행: 다른 도구로 안 되는 일(계산, 데이터 정리, 파일 만들기·변환 등)을 퍼플루가 코드로 해결한다.

안전장치
- 설정에서 끌 수 있고(python_enabled), 기본은 실행 전에 코드를 보여 주고 물어본다(python_confirm).
- 별도 파이썬 프로세스(-I 격리 모드)에서, 작업 폴더 안에서, 시간 제한(python_timeout초)으로 실행한다.
- 결과(출력·오류·새로 생긴 파일)만 돌려준다. 실행한 코드는 작업 폴더에 run_NNN.py로 남는다.
"""
import itertools
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import config, trace

OUTPUT_LIMIT = 4000

# 확인 요청: UI(PC 창)와 탭이 같은 요청을 보고, 먼저 답한 쪽으로 정해진다
ask_user = lambda req: None  # noqa: E731  UI가 연결: 확인창 띄우기 (req: {id, code, purpose})
_pending: dict[int, dict] = {}
_ids = itertools.count(1)


# 미리 검사: 이런 게 들어 있으면 '위험'으로 보고 (자동 모드여도) 물어본다
RISKS = [
    (r"\b(os\.(remove|unlink|rmdir|removedirs|rename|replace)|shutil\.(rmtree|move)|\.unlink\(|\.rmdir\(|send2trash)",
     "파일·폴더를 지우거나 옮겨요"),
    (r"\b(subprocess|os\.system|os\.popen|os\.startfile|Popen|os\.exec|os\.spawn)", "다른 프로그램·명령을 실행해요"),
    (r"\b(requests|httpx|urllib|socket|http\.client|ftplib|smtplib|aiohttp|webbrowser)\b", "인터넷에 접속해요"),
    (r"\b(winreg|ctypes|win32\w*|pywintypes|comtypes|keyring)\b", "Windows 시스템 기능에 손대요"),
    (r"\b(eval|exec|compile|__import__|importlib)\s*\(", "코드를 만들어서 또 실행해요"),
    (r"\bpip\b|ensurepip", "패키지를 설치해요"),
    (r"open\([^)]*['\"](w|a|wb|ab|x|r\+|w\+)['\"]", "파일에 써요"),
    (r"\.(write_text|write_bytes)\(|\.save\(|to_csv\(|savetxt\(", "파일을 만들거나 덮어써요"),
    (r"[A-Za-z]:[\\/]|Path\.home\(\)|expanduser|~[\\/]|\.\.[\\/]", "작업 폴더 밖의 경로를 써요"),
    (r"\b(os\.environ|getpass|input\s*\()", "환경 정보·입력에 접근해요"),
    (r"\bwhile\s+True\b", "끝없이 돌 수 있어요"),
]
SAFE_WRITE_INSIDE = ("파일에 써요", "파일을 만들거나 덮어써요")  # 작업 폴더 안에 쓰는 건 괜찮다


def analyze(code: str) -> list[str]:
    """코드에서 위험해 보이는 부분 목록. 작업 폴더 안에 파일 만드는 것만 있으면 안전으로 본다."""
    found = []
    for pattern, why in RISKS:
        if re.search(pattern, code) and why not in found:
            found.append(why)
    outside = "작업 폴더 밖의 경로를 써요" in found
    if not outside:
        found = [w for w in found if w not in SAFE_WRITE_INSIDE]
    return found


def answer(req_id: int, ok: bool):
    p = _pending.get(int(req_id))
    if p and not p["event"].is_set():
        p["ok"] = bool(ok)
        p["event"].set()


def workspace() -> Path:
    d = config.settings().get("python_dir") or ""
    if d:
        return Path(d)
    return config.PYTHON_DIR


def _python_exe() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":  # 창 없는 pythonw로 켜져 있어도 출력은 python.exe로 받는다
        exe = exe.with_name("python.exe")
    return str(exe)


def _confirm(code: str, purpose: str, risks: list[str], kind: str = "파이썬 코드") -> bool:
    req = {"id": next(_ids), "code": code, "purpose": purpose, "risks": risks, "kind": kind}
    _pending[req["id"]] = {"event": threading.Event(), "ok": False}
    try:
        ask_user(req)
        _pending[req["id"]]["event"].wait(120)
        return _pending[req["id"]]["ok"]
    finally:
        _pending.pop(req["id"], None)


def run_python(code: str, purpose: str = "") -> dict:
    s = config.settings()
    if not s.get("python_enabled", True):
        return {"ok": False, "error": "파이썬 실행이 꺼져 있어요. 설정에서 켤 수 있어요."}
    code = (code or "").strip()
    if not code:
        return {"ok": False, "error": "실행할 코드가 없어요."}
    mode = s.get("python_approval", "ask")
    risks = analyze(code)
    if mode == "ask" or (mode == "auto_safe" and risks):
        if not _confirm(code, purpose, risks):
            return {"ok": False, "error": "사용자가 실행을 허락하지 않았어요(또는 2분 동안 답이 없었어요). 실행하지 않았어."}
        how = "사용자가 허락함"
    elif mode == "auto_safe":
        how = "자동 실행: 안전 검사 통과"
    else:
        how = "자동 실행: 모두 자동 모드" + (f" (경고: {', '.join(risks)})" if risks else "")

    ws = workspace()
    ws.mkdir(parents=True, exist_ok=True)
    n = len(list(ws.glob("run_*.py"))) + 1
    script = ws / f"run_{n:03d}.py"
    script.write_text(f"# 퍼플루가 만든 코드 — {purpose}\n# {time.strftime('%Y-%m-%d %H:%M:%S')}\n{code}\n", encoding="utf-8")
    before = {p: p.stat().st_mtime for p in ws.rglob("*") if p.is_file()}
    timeout = int(s.get("python_timeout", 60))

    trace.cmd(f"# {how}")
    trace.cmd(f'cd "{ws}"')
    trace.cmd(f"python -I -X utf8 {script.name}   # 시간 제한 {timeout}초")
    for line in code.splitlines()[:12]:
        trace.cmd(f"  {line}")
    if len(code.splitlines()) > 12:
        trace.cmd(f"  … ({len(code.splitlines()) - 12}줄 더)")

    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    t0 = time.perf_counter()
    try:
        # -I(격리 모드)는 환경변수를 무시하므로 UTF-8은 -X utf8로 켠다
        r = subprocess.run([_python_exe(), "-I", "-X", "utf8", str(script)], cwd=ws, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        return {"ok": False, "error": f"{timeout}초 안에 안 끝나서 멈췄어요.", "stdout": out[-OUTPUT_LIMIT:],
                "script": str(script)}
    secs = round(time.perf_counter() - t0, 2)
    new_files = [str(p) for p in ws.rglob("*") if p.is_file() and p != script
                 and (p not in before or p.stat().st_mtime > before[p])]
    result = {"ok": r.returncode == 0, "exit_code": r.returncode, "seconds": secs, "approval": how,
              "stdout": r.stdout[-OUTPUT_LIMIT:], "script": str(script), "workspace": str(ws)}
    if r.stderr.strip():
        result["stderr"] = r.stderr[-OUTPUT_LIMIT:]
    if new_files:
        result["new_files"] = new_files[:20]
    if r.returncode != 0:
        result["error"] = (r.stderr.strip().splitlines() or ["오류"])[-1][:200]
    return result
