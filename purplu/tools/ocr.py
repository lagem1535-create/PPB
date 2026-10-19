"""Windows 내장 OCR(한국어)로 화면 글자와 그 위치를 읽는다.

Claude 앱·웹페이지처럼 버튼 정보(UI Automation)가 없는 화면도 글자 위치를 정확히 알 수 있다.
좌표는 모두 실제 화면 픽셀.
"""
import asyncio
import re
import threading
from difflib import SequenceMatcher

import mss

# winrt는 쓸 때 불러온다: PySide6보다 먼저 불러오면 프로그램이 죽는다
_engine = None
_lock = threading.Lock()  # Windows OCR은 한 번에 하나만 돌 수 있다


def _get_engine():
    global _engine
    if _engine is None:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        _engine = (OcrEngine.try_create_from_language(Language("ko"))
                   or OcrEngine.try_create_from_user_profile_languages())
    return _engine


async def _recognize(bgra: bytes, w: int, h: int):
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.storage.streams import DataWriter
    writer = DataWriter()
    writer.write_bytes(bgra)
    bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h)
    return await _get_engine().recognize_async(bitmap)


def read_screen() -> list[dict]:
    """[{text, rect:(l,t,r,b), words:[{text, rect}]}] — 위에서 아래로. 동시에 부르면 앞의 것이 끝날 때까지 기다린다."""
    with _lock:
        return _read_screen()


def _read_screen() -> list[dict]:
    if not _get_engine():
        return []
    with mss.mss() as sct:
        mon = sct.monitors[1]
        shot = sct.grab(mon)
    result = asyncio.run(_recognize(bytes(shot.bgra), shot.width, shot.height))
    ox, oy = mon["left"], mon["top"]
    lines = []
    for line in result.lines:
        words = []
        for w in line.words:
            r = w.bounding_rect
            words.append({"text": w.text,
                          "rect": (int(ox + r.x), int(oy + r.y), int(ox + r.x + r.width), int(oy + r.y + r.height))})
        if not words:
            continue
        rect = (min(w["rect"][0] for w in words), min(w["rect"][1] for w in words),
                max(w["rect"][2] for w in words), max(w["rect"][3] for w in words))
        lines.append({"text": line.text, "rect": rect, "words": words})
    lines.sort(key=lambda l: (l["rect"][1] // 12, l["rect"][0]))
    return lines


def _squash(s: str) -> str:
    return re.sub(r"[\s'\"“”‘’`.,·:;!?()\[\]{}<>-]+", "", s).lower()


def find_text(lines: list[dict], query: str, limit: int = 5, fuzzy: bool = True) -> list[dict]:
    """화면 글자에서 query를 찾아 딱 그 부분의 사각형을 돌려준다 (띄어쓰기·문장부호 무시)."""
    q = _squash(query)
    if not q:
        return []
    hits = []
    for line in lines:
        if q not in _squash(line["text"]):
            continue
        # 줄 안에서 query를 덮는 가장 짧은 단어 묶음을 찾는다
        words = line["words"]
        best = None
        for i in range(len(words)):
            joined = ""
            for j in range(i, len(words)):
                joined += _squash(words[j]["text"])
                if q in joined:
                    if best is None or (j - i) < (best[1] - best[0]):
                        best = (i, j)
                    break
        span = words[best[0]:best[1] + 1] if best else words
        rect = (min(w["rect"][0] for w in span), min(w["rect"][1] for w in span),
                max(w["rect"][2] for w in span), max(w["rect"][3] for w in span))
        text = " ".join(w["text"] for w in span)
        if len(span) == 1 and _squash(text) != q:  # 한 덩어리로 붙은 단어 안의 일부 → 글자 비율로 잘라 낸다
            whole = _squash(text)
            k = whole.find(q)
            n = len(whole) or 1
            l, t, r, b = rect
            rect = (int(l + (r - l) * k / n), t, int(l + (r - l) * (k + len(q)) / n), b)
            text = query
        hits.append({"text": text, "rect": rect})
        if len(hits) >= limit:
            break
    if hits or not fuzzy:
        return hits
    # OCR이 글자를 조금 틀리게 읽을 수 있으니, 정확히 없으면 가장 비슷한 부분을 찾는다
    scored = []
    for line in lines:
        words = line["words"]
        for i in range(len(words)):
            joined = ""
            for j in range(i, min(len(words), i + 12)):
                joined += _squash(words[j]["text"])
                if len(joined) > len(q) * 1.6 + 2:
                    break
                score = SequenceMatcher(None, q, joined).ratio()
                if score >= 0.6:
                    span = words[i:j + 1]
                    rect = (min(w["rect"][0] for w in span), min(w["rect"][1] for w in span),
                            max(w["rect"][2] for w in span), max(w["rect"][3] for w in span))
                    scored.append((score, {"text": " ".join(w["text"] for w in span), "rect": rect}))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, hit in scored:
        if all(hit["rect"] != h["rect"] for h in out) and score >= scored[0][0] - 0.1:
            out.append(hit)
        if len(out) >= limit:
            break
    return out
