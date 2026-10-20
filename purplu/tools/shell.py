"""PC 명령어 실행 (PowerShell / cmd): 다른 도구로 안 되는 Windows 일을 명령어로 한다.

파이썬 실행과 같은 확인 방식을 쓴다 (설정 '실행 전 확인': 매번 물어보기 / 안전하면 자동 / 모두 자동).
위험한 명령(끄기·지우기·포맷·레지스트리·설치 등)은 '안전하면 자동'이어도 물어본다.
"""
import re
import subprocess
import time

from .. import config, trace
from . import pyrun

OUTPUT_LIMIT = 4000
RISKS = [
    (r"\b(shutdown|restart-computer|stop-computer|logoff)\b", "PC를 끄거나 다시 시작해요"),
    (r"\b(del|erase|rd|rmdir|remove-item|rm|format|diskpart|cipher\s+/w)\b", "파일·디스크를 지워요"),
    (r"\b(reg|set-itemproperty|new-itemproperty|remove-itemproperty|bcdedit|sc\s+(config|delete))\b", "시스템 설정(레지스트리·서비스)을 바꿔요"),
    (r"\b(winget|choco|msiexec|install-package|pip)\b", "프로그램을 설치·삭제해요"),
    (r"\b(taskkill|stop-process|kill)\b", "프로그램을 강제로 꺼요"),
    (r"\b(netsh|set-netfirewall|new-netfirewall|disable-netadapter)\b", "네트워크·방화벽을 바꿔요"),
    (r"\b(invoke-webrequest|iwr|curl|wget|invoke-restmethod|irm|start-bitstransfer)\b", "인터넷에서 받거나 보내요"),
    (r"\b(set-executionpolicy|runas|start-process\s.*-verb\s+runas)\b", "관리자 권한·실행 정책을 바꿔요"),
    (r"\b(iex|invoke-expression)\b", "받은 글을 명령으로 실행해요"),
]


def analyze(command: str) -> list[str]:
    low = command.lower()
    return [why for pattern, why in RISKS if re.search(pattern, low)]


def run_command(command: str, purpose: str = "", shell: str = "powershell", timeout: int = 60) -> dict:
    s = config.settings()
    if not s.get("shell_enabled", True):
        return {"ok": False, "error": "명령어 실행이 꺼져 있어요. 설정에서 켤 수 있어요."}
    command = (command or "").strip()
    if not command:
        return {"ok": False, "error": "실행할 명령어가 없어요."}
    mode = s.get("python_approval", "ask")
    risks = analyze(command)
    if mode == "ask" or (mode == "auto_safe" and risks):
        if not pyrun._confirm(command, purpose, risks, kind=f"{shell} 명령어"):
            return {"ok": False, "error": "사용자가 실행을 허락하지 않았어요(또는 2분 동안 답이 없었어요). 실행하지 않았어."}
        how = "사용자가 허락함"
    else:
        how = "자동 실행" + (f" (경고: {', '.join(risks)})" if risks else "")
    if shell == "cmd":
        args, enc = ["cmd", "/c", command], "cp949"
    else:
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command]
        enc = "utf-8"
    trace.cmd(f"# {how}")
    trace.cmd(f"{shell}> {command[:200]}")
    t0 = time.perf_counter()
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding=enc, errors="replace",
                           timeout=max(5, min(600, int(timeout or 60))), creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{timeout}초 안에 안 끝나서 멈췄어요.", "approval": how}
    out = {"ok": r.returncode == 0, "exit_code": r.returncode, "seconds": round(time.perf_counter() - t0, 2),
           "stdout": (r.stdout or "")[-OUTPUT_LIMIT:], "approval": how}
    if (r.stderr or "").strip():
        out["stderr"] = r.stderr[-OUTPUT_LIMIT:]
        if r.returncode != 0:
            out["error"] = r.stderr.strip().splitlines()[-1][:200]
    return out
