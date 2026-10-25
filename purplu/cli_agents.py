"""터미널 에이전트 연동: Claude Code · Codex · GitHub Copilot · Antigravity 를 퍼플루 글 대화 모델처럼 쓴다.

- '터미널로 연동' 을 누르면: 설치돼 있는지(PATH) → 로그인돼 있는지(아주 짧은 시험 질문) 확인 → 연동.
- 쓰면: 대화창 위 '터미널'의 지금 폴더에서 그 에이전트를 한 번 실행하고(-p), 나오는 글을 터미널과 대화에 그대로 보여 준다.
  같은 대화에서 다시 물으면 이어서 (--continue 등).
- 에이전트는 그 폴더에서 파일을 만들고 고칠 수 있다 (연동할 때 동의를 받는다).
"""
import asyncio
import os
import re
import shutil
import subprocess

from . import config

AGENTS = {
    "claude": {"name": "Claude Code", "exe": ["claude"], "install": "npm install -g @anthropic-ai/claude-code",
               "login": "claude", "site": "claude.com/claude-code",
               "login_hint": "새 창에 Claude Code 가 열리면 /login 을 치고 Enter → 브라우저에서 로그인하세요."},
    "codex": {"name": "Codex", "exe": ["codex"], "install": "npm install -g @openai/codex",
              "login": "codex login", "site": "github.com/openai/codex",
              "login_hint": "새 창에서 브라우저 로그인이 열려요. 로그인하면 돼요."},
    "copilot": {"name": "GitHub Copilot", "exe": ["copilot"], "install": "npm install -g @github/copilot",
                "login": "copilot login", "site": "github.com/features/copilot/cli",
                "login_hint": "새 창에 나오는 코드를 github.com/login/device 에 넣어 로그인하세요."},
    "antigravity": {"name": "Antigravity", "exe": ["agy", "antigravity"], "install": "",
                    "login": "agy", "site": "antigravity.google",
                    "login_hint": "새 창에서 안내대로 구글 계정으로 로그인하세요."},
}
PREFIX = "cli:"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
stream_listeners = []   # (종류, 글): ("start", 명령줄) · ("line", 한 줄) · ("end", 끝 코드) → 대화창 터미널


def find(agent: str) -> str | None:
    for exe in AGENTS[agent]["exe"]:
        p = shutil.which(exe)
        if p:
            return p
    if agent == "antigravity":   # 기본 설치 위치
        p = os.path.join(os.environ.get("LOCALAPPDATA", ""), "agy", "bin", "agy.exe")
        if os.path.exists(p):
            return p
    return None


def _safe(text: str) -> str:
    """npm 으로 깐 .cmd 를 거칠 때 cmd 가 글을 명령으로 읽지 않게 (따옴표·%·줄바꿈)."""
    return text.replace('"', "“").replace("%", "％").replace("\r", " ").replace("\n", " ").strip()


def command(agent: str, prompt: str, cont: bool) -> list[str]:
    exe = find(agent) or AGENTS[agent]["exe"][0]
    p = _safe(prompt) if exe.lower().endswith((".cmd", ".bat")) else prompt
    if agent == "claude":
        return [exe, "-p", p, "--permission-mode", "acceptEdits"] + (["--continue"] if cont else [])
    if agent == "codex":
        return [exe, "exec"] + (["resume", "--last"] if cont else []) + [p]
    if agent == "copilot":   # 글로만 하는 모드는 도구 허락이 꼭 필요하다
        return [exe, "-p", p, "-s", "--allow-all-tools"] + (["--continue"] if cont else [])
    return [exe, "-p", p] + (["-c"] if cont else [])


def pretty(cmd: list[str]) -> str:
    """터미널에 보일 명령줄 (경로는 짧게)."""
    shown = [os.path.splitext(os.path.basename(cmd[0]))[0]] + cmd[1:]
    return " ".join(f'"{a}"' if " " in a else a for a in shown)


def check(agent: str) -> dict:
    """설치·로그인 확인 (짧은 시험 질문, 최대 2분)."""
    path = find(agent)
    if not path:
        return {"installed": False, "logged_in": False}
    try:
        r = subprocess.run(command(agent, "Reply with just: OK", False), capture_output=True, text=True,
                           stdin=subprocess.DEVNULL,   # 입력을 닫아 둔다 (안 그러면 더 읽을 글을 기다리며 멈춘다)
                           encoding="utf-8", errors="replace", timeout=120, cwd=os.path.expanduser("~"),
                           creationflags=subprocess.CREATE_NO_WINDOW)
        out = ANSI.sub("", (r.stdout or "") + (r.stderr or ""))
        ok = r.returncode == 0 and "OK" in out.upper()
        return {"installed": True, "logged_in": ok, "path": path, "output": out.strip()[-300:]}
    except subprocess.TimeoutExpired:
        return {"installed": True, "logged_in": False, "path": path, "output": "2분 안에 대답이 없었어요"}


def open_login(agent: str):
    """새 명령 창에서 로그인 (브라우저로 로그인하는 에이전트가 많아서 진짜 창이 필요)."""
    subprocess.Popen(["cmd", "/c", "start", "퍼플루 - 로그인", "cmd", "/k", AGENTS[agent]["login"]],
                     cwd=os.path.expanduser("~"))


def _emit(kind, data):
    for fn in list(stream_listeners):
        try:
            fn(kind, data)
        except Exception:
            pass


async def run(agent: str, prompt: str, cont: bool, cwd: str, on_line) -> tuple[int, str]:
    """에이전트를 한 번 실행하고, 한 줄씩 on_line·터미널로. (끝 코드, 전체 글)."""
    cmd = command(agent, prompt, cont)
    _emit("start", f"{pretty(cmd)}    # 퍼플루 · {AGENTS[agent]['name']}")
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=cwd, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT,
                                                creationflags=subprocess.CREATE_NO_WINDOW)
    lines = []
    try:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = ANSI.sub("", raw.decode("utf-8", "replace")).rstrip("\r\n")
            lines.append(line)
            _emit("line", line)
            on_line(line)
        code = await proc.wait()
    except asyncio.CancelledError:
        proc.kill()
        _emit("end", -1)
        raise
    _emit("end", code)
    return code, "\n".join(lines)


def connected() -> list[str]:
    return [a for a in config.settings().get("cli_agents") or [] if a in AGENTS]
