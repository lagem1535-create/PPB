"""모델 목록을 회사별로 묶기 + 터미널 에이전트 연동 흐름 (대화창 모델 창 · 설정 '모델 관리' 가 같이 쓴다).

묶음:  Gemini (API 키 모델 · Antigravity) / GPT (API · Codex) / Claude (API · Claude Code) /
       Ollama (이 PC에 깔린 모델만) / 그외 (Copilot)
"""
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from . import config

GROUPS = [
    # (id, 이름, 색, 키 이름(없으면 None), 터미널 에이전트)
    ("gemini", "Gemini", "#4C8DF6", "gemini", "antigravity"),
    ("gpt", "GPT", "#10A37F", "openai", "codex"),
    ("claude", "Claude", "#D97757", "anthropic", "claude"),
    ("ollama", "Ollama", "#71717A", None, None),
    ("other", "그외", "#8B5CF6", None, "copilot"),
]


def catalog(include_hidden=False) -> list[dict]:
    """[{id, name, color, key, items: [{mid, name, desc, kind(api|cli|local), ready, why}]}]"""
    from . import cli_agents, providers, textchat
    hidden = set() if include_hidden else set(config.settings().get("hidden_models") or [])
    connected = set(cli_agents.connected())
    out = []
    for gid, gname, color, key, agent in GROUPS:
        items = []
        has_key = bool(key and config.get_key(key))
        if gid == "gemini":
            for mid, name, desc, _t in textchat.TEXT_MODELS:
                items.append({"mid": mid, "name": name, "desc": desc, "kind": "api", "ready": has_key})
        elif gid == "gpt":
            for mid, name, desc in (providers.openai_models() if has_key else []):
                items.append({"mid": mid, "name": name, "desc": desc, "kind": "api", "ready": True})
        elif gid == "claude":
            for mid, name, desc in providers.CLAUDE_MODELS:
                items.append({"mid": mid, "name": name, "desc": desc, "kind": "api", "ready": has_key})
        elif gid == "ollama":
            st = providers.ollama_status()
            for m in st["models"]:
                items.append({"mid": m[0], "name": m[1], "desc": m[2], "kind": "local", "ready": True})
        if agent:
            info = cli_agents.AGENTS[agent]
            items.append({"mid": "cli:" + agent, "name": info["name"], "desc": "터미널에서 일해요", "kind": "cli",
                          "ready": agent in connected, "agent": agent})
        items = [it for it in items if it["mid"] not in hidden]
        out.append({"id": gid, "name": gname, "color": color, "key": key, "has_key": has_key, "items": items})
    return out


def group_of(mid: str) -> str:
    for g in catalog():
        if any(it["mid"] == mid for it in g["items"]):
            return g["id"]
    return ""


class CliConnector(QObject):
    """'터미널로 연동': 동의 → 설치 확인 → 로그인 확인 → 연동. 대화창·설정창 어디서든."""
    _done = Signal(str, dict)

    def __init__(self, parent, on_connected=None, on_progress=None):
        super().__init__(parent)
        self.parent_w = parent
        self.on_connected = on_connected or (lambda agent: None)
        self.on_progress = on_progress or (lambda text: None)
        self._done.connect(self._checked)

    def start(self, agent):
        from . import cli_agents
        name = cli_agents.AGENTS[agent]["name"]
        if QMessageBox.question(self.parent_w, f"{name} 연동",
                                f"{name}를 퍼플루와 연동할까요?\n\n연동하면 글 대화에서 {name}를 고를 수 있고, "
                                f"대화창 위 '터미널'의 지금 폴더에서 일해요 (파일을 만들고 고칠 수 있어요).\n"
                                f"설치·로그인돼 있는지 먼저 확인할게요 (짧은 시험 질문을 한 번 보내요).") != QMessageBox.Yes:
            return
        self.on_progress(f"{name} 확인하는 중… (설치 · 로그인)")
        threading.Thread(target=lambda: self._done.emit(agent, cli_agents.check(agent)), daemon=True).start()

    def _checked(self, agent, r):
        from . import cli_agents
        info = cli_agents.AGENTS[agent]
        name = info["name"]
        if not r.get("installed"):
            how = info["install"]
            QMessageBox.information(self.parent_w, name, f"{name}가 이 PC에 설치돼 있지 않아요.\n\n" +
                                    (f"터미널에서 이렇게 설치해요 (Node.js 필요):\n  {how}" if how else f"{info['site']} 에서 설치해 주세요."))
            self.on_progress(f"{name}: 설치 안 됨")
            return
        if not r.get("logged_in"):
            if QMessageBox.question(self.parent_w, name, f"{name}는 설치돼 있지만 로그인이 필요해 보여요.\n\n"
                                    f"새 창에서 로그인할까요? {info.get('login_hint', '')}\n"
                                    f"로그인한 뒤 다시 '연동'을 눌러 주세요.\n\n({r.get('output', '')[:160]})") == QMessageBox.Yes:
                cli_agents.open_login(agent)
            self.on_progress(f"{name}: 로그인 필요")
            return
        have = list(dict.fromkeys((config.settings().get("cli_agents") or []) + [agent]))
        config.save_settings(cli_agents=have)
        self.on_progress(f"✓ {name} 연동됐어요")
        self.on_connected(agent)
