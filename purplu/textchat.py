"""글 대화는 고른 제미나이 모델로 (말은 계속 라이브).

- 설정 text_model: "live" 면 예전처럼 라이브 세션에 글을 넣는다. 아니면 그 모델의 generate_content 로 대답한다.
- 같은 도구·같은 '실행됨 명령' 표시를 쓴다 (brain.run_tool_calls).
- 생각하는 모델이면 노력 정도(effort: low·medium·high·max)를 thinking_level 로 준다.
- 대화 기록은 같은 대화목록에서 불러오고, 대답은 brain 이 하던 대로 저장한다 (임시 대화면 저장 안 함).
"""
import asyncio
import time

from google import genai
from google.genai import types

from . import config, store

# (모델 id, 보이는 이름, 한 줄 설명, 생각하는 모델인가)
TEXT_MODELS = [
    ("gemini-3.8-flash", "Gemini 3.8 Flash", "빠르고 똑똑해요", True),
    ("gemini-3.1-pro-preview", "Gemini 3.1 Pro", "어려운 문제·긴 글을 깊이 생각해요", True),
    ("gemini-3.5-flash", "Gemini 3.5 Flash", "빠르고 안정적이에요", True),
    ("live", "Gemini 3.8 Live", "말과 같은 라이브 대화", False),
    # ↓ '더 많은 모델'
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite", "가장 빠르고 가벼워요", True),
    ("gemini-4-argon", "Gemini 4 Argon", "가장 새 모델 (실험)", True),
]
MAIN_MODELS = 4   # 처음 보이는 개수 (1~4 키로 고르기), 나머지는 '더 많은 모델'
EFFORT_NOTE = {"max": "최대는 한도를 많이 써요."}
EFFORT_WARN = {"max"}   # 주황 글씨로 보일 것
EFFORTS = [("low", "낮음"), ("medium", "중간"), ("high", "높음"), ("max", "최대")]
FALLBACK = "gemini-3.5-flash-lite"   # 고른 모델이 바쁘거나(503·504) 한도(429)일 때 대신
LEVEL = {"low": "low", "medium": "medium", "high": "high", "max": "high"}   # 최대 = 높음 + 더 길게 생각하고 더 길게 대답


def model_info(mid: str):
    """(id, 이름, 설명, 생각하는 모델인가). Claude·GPT 도 (키가 있으면 고를 수 있다)."""
    from .providers import CLAUDE_MODELS, OPENAI_PREFIX
    for m in TEXT_MODELS:
        if m[0] == mid:
            return m
    for cid, name, desc in CLAUDE_MODELS:
        if cid == mid:
            return (cid, name, desc, True)
    if mid and mid.startswith(OPENAI_PREFIX):
        return (mid, mid[len(OPENAI_PREFIX):].replace("gpt-", "GPT-"), "OpenAI", True)
    if mid and mid.startswith("ollama:"):
        from .providers import ollama_status
        m = next((x for x in ollama_status()["models"] if x[0] == mid), None)
        return (mid, mid[7:], (m[2] if m else "Ollama (꺼져 있음)"), bool(m and m[4]))
    from .cli_agents import AGENTS, PREFIX as CLI
    if mid and mid.startswith(CLI) and mid[len(CLI):] in AGENTS:
        return (mid, AGENTS[mid[len(CLI):]]["name"] + " (터미널)", "터미널에서 일하는 에이전트", False)
    return TEXT_MODELS[0]


def name_of(mid: str) -> str:
    if mid and mid.startswith("gemini-3.8-live"):
        return "Gemini 3.8 Live" + (" 생각" if "thinking" in mid else "")
    return model_info(mid)[1] if mid else ""


class TextChat:
    def __init__(self, brain):
        self.b = brain
        self.task = None

    def start(self, text: str, image: bytes | None, mime: str, shown: str | None):
        self.b._call(self._go(text, image, mime, shown))

    def cancel(self):
        if self.task and not self.task.done():
            self.task.cancel()

    async def _go(self, text, image, mime, shown):
        self.task = asyncio.current_task()
        b = self.b
        s = config.settings()
        mid = s.get("text_model") or "gemini-3.8-flash"
        effort = s.get("effort") or "medium"
        thinking = model_info(mid)[3]
        b._flush_turn()
        b._new_request()
        b._turn_user = ((shown or "").strip() or text) + (" [그림 첨부]" if image and (mime or "").startswith("image/") else "")
        b._turn_meta = {"model": mid, "via": "글", "effort": effort if thinking else "", "t0": time.time()}
        b.emit("state", "listening")
        b.emit("heard", b._turn_user)
        b.emit("state", "thinking")
        from .providers import OPENAI_PREFIX
        if mid.startswith("cli:"):   # 터미널 에이전트 (Claude Code · Codex · Copilot · Antigravity)
            return await self._cli(mid[4:], text)
        if mid.startswith("claude-") or mid.startswith(OPENAI_PREFIX) or mid.startswith("ollama:"):   # Claude · GPT · Ollama
            return await self._other(mid, effort, text, image, mime, s)
        key = config.get_api_key()
        if not key:
            b.emit("error", "Gemini 키가 없어요. 설정에서 키를 넣어 주세요.")
            b.emit("state", "idle")
            return
        client = genai.Client(api_key=key)
        contents = await self._history()
        parts = [types.Part(text=text or "이 그림 봐 줘")]
        if image:
            if (mime or "").startswith("image/"):   # 그림이면 '이 그림 고쳐 줘'(generate_image)에도 쓰이게
                from .tools import images
                images.last_attached.update(bytes=image, mime=mime)
            parts.insert(0, types.Part(inline_data=types.Blob(data=image, mime_type=mime)))
        contents.append(types.Content(role="user", parts=parts))
        from . import brain as brain_mod, tools
        cfg = dict(system_instruction=brain_mod.system_prompt() + "\n- 지금은 글 대화야. 목소리가 아니라 글로 읽기 좋게, 필요하면 줄을 나눠 답해.",
                   tools=[types.Tool(function_declarations=tools.declarations(s["computer_control"]))])
        if thinking:
            cfg["thinking_config"] = types.ThinkingConfig(thinking_level=LEVEL.get(effort, "medium"),
                                                          include_thoughts=bool(s.get("show_thoughts")) or None)
            if effort == "max":
                cfg["max_output_tokens"] = 32768
        config_obj = types.GenerateContentConfig(**cfg)
        try:
            for _round in range(40):   # 도구 → 대답 을 되풀이 (보통 몇 번이면 끝)
                for attempt in range(2):   # 고른 모델이 바쁘거나 한도면 한 번 가벼운 모델로
                    calls, model_parts = [], []
                    try:
                        stream = await client.aio.models.generate_content_stream(model=mid, contents=contents, config=config_obj)
                        async for chunk in stream:
                            for cand in chunk.candidates or []:
                                for part in (cand.content.parts if cand.content else None) or []:
                                    model_parts.append(part)
                                    if part.function_call:
                                        calls.append(part.function_call)
                                    elif part.text and part.thought:
                                        b.emit("thought", part.text)
                                    elif part.text:
                                        b._turn_model += part.text
                                        b.emit("reply", part.text)
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        head = str(e)[:16]
                        busy = any(code in head for code in ("429", "503", "504", "500"))
                        if not busy or mid == FALLBACK or model_parts:
                            raise
                        why = "사용량 한도가 다 돼서" if "429" in head else "지금 너무 바빠서"
                        b.emit("hint", f"{model_info(mid)[1]}가 {why} {model_info(FALLBACK)[1]}로 대답할게요.")
                        b._turn_meta["note"] = f"{model_info(mid)[1]}가 {why} 대신 대답"
                        mid = FALLBACK
                        b._turn_meta["model"] = mid
                if not calls:
                    break
                contents.append(types.Content(role="model", parts=model_parts))
                responses, imgs = await b.run_tool_calls(calls)
                resp_parts = [types.Part(function_response=r) for r in responses]
                for img in imgs:   # 스크린샷은 그림으로 같이
                    resp_parts.append(types.Part(inline_data=types.Blob(data=img, mime_type="image/jpeg")))
                contents.append(types.Content(role="user", parts=resp_parts))
                b.emit("state", "thinking")
        except asyncio.CancelledError:
            b._turn_model = (b._turn_model + " (멈춤)").strip()
        except Exception as e:
            b.emit("error", f"{model_info(mid)[1]} 대답 실패: {str(e)[:200]}")
        finally:
            b._turn_meta["secs"] = round(time.time() - b._turn_meta.pop("t0", time.time()), 1)
            b.emit("meta", dict(b._turn_meta))
            b._cid = config.settings().get("current_conversation") or getattr(b, "_cid", None)
            b._flush_turn()
            b.emit("state", "idle")
            self.task = None

    async def _other(self, mid, effort, text, image, mime, s):
        """Claude·GPT 로 대답. 실패하면(한도·키 문제 등) 알려 주고, 바쁘면 Gemini 가벼운 모델로 대신."""
        from . import brain as brain_mod, providers
        b = self.b
        rows = await self._rows()
        system = brain_mod.system_prompt() + "\n- 지금은 글 대화야. 글로 읽기 좋게, 필요하면 줄을 나눠 답해."
        turn = (providers.claude_turn if mid.startswith("claude-") else
                providers.ollama_turn if mid.startswith("ollama:") else providers.openai_turn)
        try:
            await turn(b, mid, effort, rows, text, image, mime, system, s["computer_control"])
        except asyncio.CancelledError:
            b._turn_model = (b._turn_model + " (멈춤)").strip()
        except Exception as e:
            msg = str(e)
            if any(k in msg for k in ("429", "529", "overloaded", "rate_limit", "Rate limit")) and not b._turn_model:
                b.emit("hint", f"{model_info(mid)[1]}가 지금 바쁘거나 한도라서 {model_info(FALLBACK)[1]}로 대답할게요.")
                b._turn_meta["note"] = f"{model_info(mid)[1]}가 바빠서 대신 대답"
                b._turn_meta["model"] = FALLBACK
                await self._gemini_fallback(text, image, mime)
                return
            b.emit("error", f"{model_info(mid)[1]} 대답 실패: {msg[:200]}")
        finally:
            if b._turn_meta and "t0" in b._turn_meta:
                b._turn_meta["secs"] = round(time.time() - b._turn_meta.pop("t0", time.time()), 1)
                b.emit("meta", dict(b._turn_meta))
                b._cid = config.settings().get("current_conversation") or getattr(b, "_cid", None)
                b._flush_turn()
                b.emit("state", "idle")
                self.task = None

    async def _cli(self, agent, text):
        """터미널 에이전트를 지금 터미널 폴더에서 한 번 실행. 같은 대화에서 다시 물으면 이어서."""
        from . import cli_agents, terminal
        b = self.b
        cid = config.settings().get("current_conversation") or "temp"
        cont = getattr(self, "_cli_last", None) == (agent, cid)
        cwd = terminal.CURRENT_CWD[0]
        name = cli_agents.AGENTS[agent]["name"]
        label = f"{name}(터미널)에서 하는 중…"
        call = cli_agents.pretty(cli_agents.command(agent, text, cont))
        b.emit("step", {"label": label, "call": call, "done": False})
        b.emit("state", "acting")
        t0 = time.time()
        code, out = -1, ""
        try:
            def line(t):
                b._turn_model += t + "\n"
                b.emit("reply", t + "\n")
            code, out = await cli_agents.run(agent, text, cont, cwd, line)
            self._cli_last = (agent, cid)
        except asyncio.CancelledError:
            b._turn_model = (b._turn_model + " (멈춤)").strip()
        except Exception as e:
            b.emit("error", f"{name} 실행 실패: {str(e)[:200]}")
        finally:
            last = next((x for x in reversed(out.splitlines()) if x.strip()), "")
            done = {"label": label, "call": call, "done": True, "ok": code == 0,
                    "result": (last[:70] or "끝") if code == 0 else f"끝 코드 {code}", "secs": round(time.time() - t0, 1)}
            b.emit("step", done)
            b._turn_steps = getattr(b, "_turn_steps", []) + [{k: done[k] for k in ("call", "ok", "result", "secs")}]
            b._turn_meta["note"] = f"폴더: {cwd}"
            b._turn_meta["secs"] = round(time.time() - b._turn_meta.pop("t0", time.time()), 1)
            b.emit("meta", dict(b._turn_meta))
            b._cid = config.settings().get("current_conversation") or getattr(b, "_cid", None)
            b._flush_turn()
            b.emit("state", "idle")
            self.task = None

    async def _gemini_fallback(self, text, image, mime):
        """Claude·GPT 가 바쁠 때 Gemini 가벼운 모델로 한 번 (도구 없이 짧게)."""
        b = self.b
        client = genai.Client(api_key=config.get_api_key())
        contents = await self._history()
        contents.append(types.Content(role="user", parts=[types.Part(text=text or "이 파일 봐 줘")]))
        stream = await client.aio.models.generate_content_stream(model=FALLBACK, contents=contents)
        async for chunk in stream:
            if chunk.text:
                b._turn_model += chunk.text
                b.emit("reply", chunk.text)

    async def _rows(self) -> list:
        b = self.b
        if getattr(b, "temporary", False):
            return list(getattr(b, "_temp_history", []))
        cid = config.settings().get("current_conversation") or ""
        try:
            return await asyncio.to_thread(store.messages, cid) if cid else []
        except Exception:
            return []

    async def _history(self) -> list:
        b = self.b
        if getattr(b, "temporary", False):
            rows = list(getattr(b, "_temp_history", []))
        else:
            cid = config.settings().get("current_conversation") or ""
            try:
                rows = await asyncio.to_thread(store.messages, cid) if cid else []
            except Exception:
                rows = []
        out = []
        for r in rows[-30:]:
            if r.get("text") and r.get("role") in ("user", "model"):
                out.append(types.Content(role=r["role"], parts=[types.Part(text=r["text"])]))
        return out
