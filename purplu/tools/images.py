"""그림 만들기·고치기 (Gemini 이미지 모델). 만든 그림은 data/images 에 저장하고 탭·채팅 화면에 보여 준다."""
from datetime import datetime

from google import genai
from google.genai import types

from .. import config, trace

on_image = lambda path, caption: None  # noqa: E731  UI가 연결: 만든 그림 보여 주기
last_attached: dict = {"bytes": None, "mime": None}  # 채팅으로 첨부한 마지막 그림 (고치기에 쓴다)


def generate_image(prompt: str, edit_attached: bool = False) -> dict:
    key = config.get_api_key()
    if not key:
        return {"ok": False, "error": "Gemini 키가 없어요."}
    model = config.settings().get("image_model", "gemini-3.1-flash-image")
    contents = [prompt]
    if edit_attached and last_attached["bytes"]:
        contents = [types.Part.from_bytes(data=last_attached["bytes"], mime_type=last_attached["mime"]), prompt]
    trace.cmd(f"Gemini {model}.generate_content({'첨부 그림 + ' if len(contents) > 1 else ''}{prompt[:60]!r}, IMAGE)")
    client = genai.Client(api_key=key)
    try:
        resp = client.models.generate_content(model=model, contents=contents,
                                              config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]))
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            return {"ok": False, "error": "지금 Gemini 키로는 그림 만들기 한도가 없어요 (무료 키는 그림 모델을 못 쓰는 경우가 많아요). "
                                          "Google AI Studio에서 결제를 켜면 쓸 수 있어요."}
        return {"ok": False, "error": f"그림을 못 만들었어요: {str(e)[:200]}"}
    folder = config.DATA_DIR / "images"
    folder.mkdir(parents=True, exist_ok=True)
    saved, text = [], ""
    for part in (resp.candidates[0].content.parts if resp.candidates and resp.candidates[0].content else []):
        if part.inline_data and part.inline_data.data:
            ext = "png" if "png" in (part.inline_data.mime_type or "") else "jpg"
            path = folder / f"{datetime.now():%Y-%m-%d_%H-%M-%S}_{len(saved)}.{ext}"
            path.write_bytes(part.inline_data.data)
            saved.append(str(path))
            on_image(str(path), prompt)
        elif part.text:
            text += part.text
    if not saved:
        return {"ok": False, "error": "그림이 안 나왔어요. " + text[:200]}
    return {"ok": True, "images": saved, "note": "화면(탭·채팅)에 그림을 보여 줬어. 저장 위치: data\\images"}
