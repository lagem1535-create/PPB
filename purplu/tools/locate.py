"""화면에서 무언가의 정확한 위치 찾기.

1) Windows OCR에서 글자가 그대로 보이면 그 위치 (빠르고 정확)
2) 아니면 Gemini에게 스크린샷을 보여주고 상자 좌표(box_2d)를 받는다 (글자가 아닌 것도 찾음)
3) 그래도 없으면 OCR에서 가장 비슷한 글자
좌표는 실제 화면 픽셀 (l, t, r, b).
"""
import io
import json

import mss
from google import genai
from google.genai import types
from PIL import Image

from .. import config
from .. import trace
from . import ocr

PROMPT = """이 스크린샷에서 다음을 찾아 주세요: "{q}"
찾은 것마다 정확히 감싸는 상자를 JSON 목록으로만 답하세요 (최대 {n}개, 제일 맞는 것부터).
형식: [{{"box_2d": [ymin, xmin, ymax, xmax], "label": "찾은 것의 실제 글자나 짧은 설명"}}]
좌표는 0~1000으로 정규화. 없으면 []."""


def _screenshot():
    with mss.mss() as sct:
        mon = sct.monitors[1]
        shot = sct.grab(mon)
    return mon, Image.frombytes("RGB", shot.size, shot.rgb)


def ask_gemini(query: str, limit: int = 3) -> list[dict]:
    key = config.get_api_key()
    if not key:
        return []
    mon, img = _screenshot()
    small = img.copy()
    small.thumbnail((1920, 1920))
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=85)
    client = genai.Client(api_key=key)
    trace.cmd(f"Gemini {config.settings()['research_model']}.generate_content(스크린샷, '{query}' 위치 찾기 box_2d)")
    resp = client.models.generate_content(
        model=config.settings()["research_model"],
        contents=[types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"),
                  PROMPT.format(q=query, n=limit)],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
    )
    try:
        items = json.loads(resp.text or "[]")
    except ValueError:
        return []
    out = []
    for it in items[:limit] if isinstance(items, list) else []:
        box = it.get("box_2d") if isinstance(it, dict) else None
        if not box or len(box) != 4:
            continue
        y0, x0, y1, x1 = (float(v) for v in box)
        out.append({"text": it.get("label") or query,
                    "rect": (int(mon["left"] + x0 * mon["width"] / 1000), int(mon["top"] + y0 * mon["height"] / 1000),
                             int(mon["left"] + x1 * mon["width"] / 1000), int(mon["top"] + y1 * mon["height"] / 1000)),
                    "how": "gemini"})
    return out


def find(query: str, lines: list[dict] | None = None, limit: int = 3) -> list[dict]:
    """query(화면 글자 또는 설명)의 위치들."""
    lines = ocr.read_screen() if lines is None else lines
    exact = ocr.find_text(lines, query, limit=limit, fuzzy=False)
    if exact:
        return [{**h, "how": "ocr"} for h in exact]
    try:
        hits = ask_gemini(query, limit)
        if hits:
            return hits
    except Exception as e:
        print("Gemini 위치 찾기 실패:", e)
    return [{**h, "how": "ocr_similar"} for h in ocr.find_text(lines, query, limit=limit)]
