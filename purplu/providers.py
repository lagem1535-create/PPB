"""글 대화를 Claude(Anthropic)·GPT(OpenAI)로 (키가 있을 때). 말(라이브)은 계속 Gemini.

textchat.py 가 부른다. 도구는 Gemini 모양(FunctionDeclaration)을 JSON 스키마로 바꿔서 그대로 쓰고,
실행은 brain.run_tool_calls 로 (그래서 '실행됨 명령' 표시·확인창이 모두 같다).
"""
import base64
import json
import time
from types import SimpleNamespace

from google.genai import types as gtypes

from . import config

CLAUDE_MODELS = [
    ("claude-opus-5-5", "Claude Opus 5.5", "가장 똑똑해요"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5", "빠르고 똑똑해요"),
    ("claude-haiku-5-5", "Claude Haiku 5.5", "가장 빠르고 싸요"),
]
CLAUDE_FALLBACK_OK = {"claude-opus-5-5", "claude-sonnet-5-5"}   # 안전 거절 시 서버가 다른 모델로 이어 주기
OPENAI_PREFIX = "openai:"
OPENAI_CACHE = config.DATA_DIR / "openai_models.json"


# ---------------- 도구 모양 바꾸기 (Gemini → JSON 스키마) ----------------
_T = {gtypes.Type.STRING: "string", gtypes.Type.INTEGER: "integer", gtypes.Type.NUMBER: "number",
      gtypes.Type.BOOLEAN: "boolean", gtypes.Type.ARRAY: "array", gtypes.Type.OBJECT: "object"}


def schema_json(s) -> dict:
    if s is None:
        return {"type": "object", "properties": {}}
    out = {"type": _T.get(s.type, "string")}
    if s.description:
        out["description"] = s.description
    if s.enum:
        out["enum"] = list(s.enum)
    if s.properties:
        out["properties"] = {k: schema_json(v) for k, v in s.properties.items()}
    if s.required:
        out["required"] = list(s.required)
    if s.items is not None:
        out["items"] = schema_json(s.items)
    if out["type"] == "object" and "properties" not in out:
        out["properties"] = {}
    return out


def tool_specs(computer_control: bool) -> list[tuple[str, str, dict]]:
    from . import tools
    return [(d.name, d.description or "", schema_json(d.parameters)) for d in tools.declarations(computer_control)]


def _result_text(resp) -> str:
    """brain.run_tool_calls 가 돌려준 FunctionResponse → 글."""
    return json.dumps(resp.response, ensure_ascii=False, default=str)[:30000]


# ---------------- 기록 ----------------
def _rows_to_messages(rows) -> list[dict]:
    """대화목록 기록 → [{"role": "user"|"assistant", "content": 글}]."""
    msgs = []
    for r in rows[-30:]:
        if r.get("text") and r.get("role") in ("user", "model"):
            msgs.append({"role": "user" if r["role"] == "user" else "assistant", "content": r["text"]})
    while msgs and msgs[0]["role"] != "user":   # 첫 말은 사용자여야 한다
        msgs.pop(0)
    return msgs


# ---------------- Claude ----------------
async def claude_turn(b, mid, effort, rows, text, image, mime, system, computer_control):
    """Claude 로 한 번 대답 (도구 → 결과 → 다시, 끝날 때까지)."""
    import anthropic
    key = config.get_key("anthropic")
    if not key:
        raise RuntimeError("Claude 키가 없어요. 설정 > 기본에서 Claude 키를 넣어 주세요.")
    client = anthropic.AsyncAnthropic(api_key=key)
    tools = [{"name": n, "description": d[:1000], "input_schema": sch, "eager_input_streaming": True}
             for n, d, sch in tool_specs(computer_control)]
    messages = _rows_to_messages(rows)
    content = []
    if image and (mime or "").startswith("image/"):
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime,
                                                    "data": base64.standard_b64encode(image).decode()}})
    elif image and mime == "application/pdf":
        content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                       "data": base64.standard_b64encode(image).decode()}})
    content.append({"type": "text", "text": text or "이 파일 봐 줘"})
    messages.append({"role": "user", "content": content})
    level = {"low": "low", "medium": "medium", "high": "high", "max": "max"}.get(effort, "medium")
    extra = {}
    if mid in CLAUDE_FALLBACK_OK:   # 안전 거절이면 서버가 알맞은 모델로 이어서 대답 (기본으로 켬)
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    for _round in range(40):
        async with client.beta.messages.stream(
                model=mid, max_tokens=64000, system=system, tools=tools, messages=messages,
                output_config={"effort": level}, **extra) as stream:
            async for t in stream.text_stream:
                b._turn_model += t
                b.emit("reply", t)
            msg = await stream.get_final_message()
        if msg.stop_reason == "refusal":
            b.emit("hint", "Claude 가 이 부탁은 도와주기 어렵다고 했어요.")
            return
        uses = [x for x in msg.content if x.type == "tool_use"]
        if msg.stop_reason == "max_tokens" and uses:   # 잘린 도구 입력은 실행하지 않는다
            b.emit("hint", "대답이 너무 길어져서 멈췄어요.")
            return
        if msg.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": msg.content})
            continue
        if not uses:
            return
        messages.append({"role": "assistant", "content": msg.content})
        calls, bad = [], {}
        for u in uses:
            if isinstance(u.input, dict):   # 흘려 받은 입력이 망가졌으면 실행하지 않고 다시 하게
                calls.append(SimpleNamespace(name=u.name, args=u.input, id=u.id))
            else:
                bad[u.id] = "INVALID_JSON: 도구 입력이 망가졌어. 다시 불러 줘."
        responses, imgs = await b.run_tool_calls(calls) if calls else ([], [])
        results = [{"type": "tool_result", "tool_use_id": r.id, "content": _result_text(r)} for r in responses]
        results += [{"type": "tool_result", "tool_use_id": i, "content": why, "is_error": True} for i, why in bad.items()]
        for img in imgs:   # 스크린샷은 그림으로 같이
            results.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                       "data": base64.standard_b64encode(img).decode()}})
        messages.append({"role": "user", "content": results})
        b.emit("state", "thinking")


# ---------------- GPT (OpenAI) ----------------
def openai_models(refresh=False) -> list[tuple[str, str, str]]:
    """키로 쓸 수 있는 GPT 글 모델 (하루 한 번만 물어보고 data 에 기억)."""
    try:
        if not refresh and OPENAI_CACHE.exists() and time.time() - OPENAI_CACHE.stat().st_mtime < 86400:
            return [tuple(x) for x in json.loads(OPENAI_CACHE.read_text(encoding="utf-8"))]
    except Exception:
        pass
    key = config.get_key("openai")
    if not key:
        return []
    try:
        import openai
        ids = [m.id for m in openai.OpenAI(api_key=key, timeout=15).models.list()]
    except Exception:
        return []
    import re
    skip = ("audio", "realtime", "tts", "transcribe", "image", "embedding", "moderation", "search", "instruct", "codex", "dall")
    chat = sorted({i for i in ids if (i.startswith("gpt-") or i[:2] in ("o1", "o3", "o4"))
                   and not any(k in i for k in skip) and not re.search(r"-\d{4}(-\d{2}-\d{2})?$", i)},
                  reverse=True)[:12]   # 날짜 붙은 옛 버전은 빼고
    rows = [(OPENAI_PREFIX + i, i.replace("gpt-", "GPT-"), "OpenAI") for i in chat]
    try:
        OPENAI_CACHE.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return rows


async def openai_turn(b, mid, effort, rows, text, image, mime, system, computer_control):
    import openai
    key = config.get_key("openai")
    if not key:
        raise RuntimeError("OpenAI 키가 없어요. 설정 > 기본에서 OpenAI 키를 넣어 주세요.")
    model = mid[len(OPENAI_PREFIX):]
    client = openai.AsyncOpenAI(api_key=key)
    tools = [{"type": "function", "function": {"name": n, "description": d[:1000], "parameters": sch}}
             for n, d, sch in tool_specs(computer_control)]
    messages = [{"role": "system", "content": system}] + _rows_to_messages(rows)
    if image and (mime or "").startswith("image/"):
        url = f"data:{mime};base64," + base64.b64encode(image).decode()
        messages.append({"role": "user", "content": [{"type": "text", "text": text or "이 그림 봐 줘"},
                                                     {"type": "image_url", "image_url": {"url": url}}]})
    else:
        messages.append({"role": "user", "content": text or "이 파일 봐 줘"})
    reasoning = {"low": "low", "medium": "medium", "high": "high", "max": "high"}.get(effort, "medium")
    use_reasoning = True
    for _round in range(40):
        kw = dict(model=model, messages=messages, tools=tools, stream=True)
        if use_reasoning:
            kw["reasoning_effort"] = reasoning
        try:
            stream = await client.chat.completions.create(**kw)
        except openai.BadRequestError as e:   # 생각하는 모델이 아니면 노력 정도 없이 다시
            if use_reasoning and "reasoning" in str(e).lower():
                use_reasoning = False
                continue
            raise
        calls = {}
        async for chunk in stream:
            if not chunk.choices:
                continue
            d = chunk.choices[0].delta
            if d.content:
                b._turn_model += d.content
                b.emit("reply", d.content)
            for tc in d.tool_calls or []:
                slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                slot["id"] = tc.id or slot["id"]
                if tc.function:
                    slot["name"] += tc.function.name or ""
                    slot["args"] += tc.function.arguments or ""
        if not calls:
            return
        items = [calls[i] for i in sorted(calls)]
        messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["args"] or "{}"}} for c in items]})
        run, bad = [], {}
        for c in items:
            try:
                run.append(SimpleNamespace(name=c["name"], args=json.loads(c["args"] or "{}"), id=c["id"]))
            except json.JSONDecodeError:
                bad[c["id"]] = "INVALID_JSON: 도구 입력이 망가졌어. 다시 불러 줘."
        responses, _imgs = await b.run_tool_calls(run) if run else ([], [])
        for r in responses:
            messages.append({"role": "tool", "tool_call_id": r.id, "content": _result_text(r)})
        for i, why in bad.items():
            messages.append({"role": "tool", "tool_call_id": i, "content": why})
        b.emit("state", "thinking")


# ---------------- Ollama (이 PC에 깔린 모델만, 클라우드 모델은 빼고) ----------------
OLLAMA_PREFIX = "ollama:"
OLLAMA_URL = "http://127.0.0.1:11434"


_ollama_cache = [0.0, None]


def ollama_status(fresh: bool = False) -> dict:
    """{"running", "installed", "models": [(id, 이름, 설명, 도구, 생각, 그림)]}. 메뉴가 느려지지 않게 20초 기억."""
    if not fresh and _ollama_cache[1] is not None and time.time() - _ollama_cache[0] < 20:
        return _ollama_cache[1]
    _ollama_cache[1] = _ollama_status()
    _ollama_cache[0] = time.time()
    return _ollama_cache[1]


def _ollama_status() -> dict:
    import shutil
    import httpx
    out = {"running": False, "installed": bool(shutil.which("ollama")), "models": []}
    try:
        tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.5).json()
    except Exception:
        return out
    out["running"] = out["installed"] = True
    for m in tags.get("models", []):
        name = m.get("name") or m.get("model") or ""
        if m.get("remote_host") or m.get("remote_model") or name.endswith("-cloud") or ":cloud" in name:
            continue   # 클라우드 모델은 빼기 (깔린 것만)
        d = m.get("details") or {}
        caps = m.get("capabilities") or []
        desc = " · ".join(x for x in (d.get("parameter_size"), "도구 됨" if "tools" in caps else "", "그림 됨" if "vision" in caps else "") if x)
        out["models"].append((OLLAMA_PREFIX + name, name, desc or "이 PC", "tools" in caps, "thinking" in caps, "vision" in caps))
    return out


async def ollama_turn(b, mid, effort, rows, text, image, mime, system, computer_control):
    import httpx
    name = mid[len(OLLAMA_PREFIX):]
    info = next((m for m in ollama_status()["models"] if m[0] == mid), None)
    if not info:
        raise RuntimeError("Ollama 가 꺼져 있거나 그 모델이 없어요. Ollama 를 켜 주세요.")
    _id, _n, _d, can_tools, can_think, can_see = info
    if not can_tools:   # 도구를 못 쓰는 작은 모델: 긴 도구 설명 대신 짧게 (훨씬 빨라진다)
        system = ("너는 '퍼플루'야. 사용자의 PC에 사는 귀여운 보라색 AI 친구야. 항상 한국어 반말로, 친근하고 짧게 대답해. "
                  "모르는 건 지어내지 말고 모른다고 말해.")
    messages = [{"role": "system", "content": system}] + _rows_to_messages(rows)
    user = {"role": "user", "content": text or "이 그림 봐 줘"}
    if image and can_see and (mime or "").startswith("image/"):
        user["images"] = [base64.b64encode(image).decode()]
    messages.append(user)
    tools = ([{"type": "function", "function": {"name": n, "description": d[:1000], "parameters": sch}}
              for n, d, sch in tool_specs(computer_control)] if can_tools else None)
    async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=5)) as client:
        for _round in range(40):
            body = {"model": name, "messages": messages, "stream": True}
            if tools:
                body["tools"] = tools
            if can_think:
                body["think"] = effort in ("high", "max") or None
            calls, content = [], ""
            async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=body) as r:
                if r.status_code >= 400:
                    raise RuntimeError(f"Ollama 오류 {r.status_code}: {(await r.aread()).decode('utf-8', 'replace')[:200]}")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    msg = json.loads(line).get("message") or {}
                    if msg.get("thinking"):
                        b.emit("thought", msg["thinking"])
                    if msg.get("content"):
                        content += msg["content"]
                        b._turn_model += msg["content"]
                        b.emit("reply", msg["content"])
                    for tc in msg.get("tool_calls") or []:
                        calls.append(tc)
            if not calls:
                return
            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            run = [SimpleNamespace(name=tc["function"]["name"], args=tc["function"].get("arguments") or {}, id=str(i))
                   for i, tc in enumerate(calls)]
            responses, _imgs = await b.run_tool_calls(run)
            for r_ in responses:
                messages.append({"role": "tool", "content": _result_text(r_), "tool_name": r_.name})
            b.emit("state", "thinking")
