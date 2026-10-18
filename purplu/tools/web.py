"""웹에서 찾기: Gemini + Google 검색 그라운딩."""
from google import genai
from google.genai import types

from .. import config
from .. import trace

PROMPT = """다음 질문을 웹에서 조사해서 한국어로 짧은 리포트를 써 주세요.
형식: 첫 줄은 제목, 그다음 최대 4개 문단. 핵심부터. 숫자·날짜는 정확하게.

질문: {q}"""


def web_research(question: str) -> dict:
    key = config.get_api_key()
    if not key:
        return {"ok": False, "error": "Gemini 키가 없어요."}
    client = genai.Client(api_key=key)
    try:
        trace.cmd(f"Gemini {config.settings()['research_model']}.generate_content(tools=[google_search], {question!r})")
        resp = client.models.generate_content(
            model=config.settings()["research_model"],
            contents=PROMPT.format(q=question),
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        )
    except Exception as e:
        if "429" not in str(e) and "RESOURCE_EXHAUSTED" not in str(e):
            return {"ok": False, "error": f"조사에 실패했어요: {str(e)[:200]}"}
        # Gemini 검색 한도가 없으면: 무료 검색 결과를 모아서 그걸로 리포트를 쓴다
        from .search import search_text
        found = search_text(question)
        if not found:
            return {"ok": False, "error": "검색 결과를 못 가져왔어요."}
        trace.cmd(f"Gemini {config.settings()['research_model']}.generate_content(검색 결과 {found.count(chr(10)) + 1}줄로 리포트)")
        try:
            resp = client.models.generate_content(
                model=config.settings()["research_model"],
                contents=PROMPT.format(q=question) + "\n\n아래 최신 검색 결과만 근거로 써 주세요:\n" + found)
        except Exception as e2:
            return {"ok": False, "error": f"조사에 실패했어요: {str(e2)[:200]}"}
        return {"ok": True, "report": (resp.text or "").strip(), "sources": []}
    sources = []
    try:
        for chunk in resp.candidates[0].grounding_metadata.grounding_chunks or []:
            if chunk.web:
                sources.append({"title": chunk.web.title, "url": chunk.web.uri})
    except (AttributeError, IndexError, TypeError):
        pass
    return {"ok": True, "report": (resp.text or "").strip(), "sources": sources[:5]}
