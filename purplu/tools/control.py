"""화면 보기 + 컴퓨터 조작 (클릭, 타이핑, 단축키, 스크롤).

좌표는 모두 실제 화면 픽셀(물리 픽셀). AI에게는 0~1000 격자로 보여준다.
퍼플루 커서가 먼저 날아가서 보여준 다음 조작하고, 내 진짜 마우스는 원래 자리로 돌려놓는다.
"""
import ctypes
import io
import threading
import time
from ctypes import wintypes

import mss
import numpy as np
import pyautogui
import uiautomation as uia
from PIL import Image

from . import locate, ocr
from .. import trace

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.02
uia.SetGlobalSearchTimeout(1)

user32 = ctypes.windll.user32

# UI가 연결하는 고리: 커서를 (x, y) 물리 픽셀로 날려 보내기 / 집으로
on_point = lambda x, y, kind: None  # noqa: E731
on_home = lambda: None  # noqa: E731
on_highlight = lambda rects, seconds: None  # noqa: E731  [(l, t, r, b, 이름표)]
on_clear_highlights = lambda: None  # noqa: E731
FLY_SECONDS = 0.22

stop_event = threading.Event()  # Ctrl+Alt+S 비상정지

_snapshot: dict = {"controls": {}, "lines": {}, "screen": (0, 0, 1, 1)}
MAX_LINES = 150

INTERESTING = {
    "ButtonControl", "EditControl", "MenuItemControl", "ListItemControl", "TabItemControl",
    "HyperlinkControl", "CheckBoxControl", "RadioButtonControl", "ComboBoxControl",
    "TreeItemControl", "DocumentControl", "TextControl", "SplitButtonControl",
}
MAX_CONTROLS = 100
BLOCKED_KEYS = {"win+l", "ctrl+alt+delete", "ctrl+alt+del", "alt+f4+ctrl", "win+x+u"}


def _screen_rect():
    m = mss.mss().monitors[1]  # 주 모니터
    return m["left"], m["top"], m["width"], m["height"]


def _to_grid(x, y):
    left, top, w, h = _snapshot["screen"]
    return round((x - left) * 1000 / w), round((y - top) * 1000 / h)


def _from_grid(gx, gy):
    left, top, w, h = _screen_rect()
    return int(left + float(gx) * w / 1000), int(top + float(gy) * h / 1000)


def _screenshot_jpeg() -> bytes:
    trace.cmd("mss.grab(모니터 1) → JPEG 1024px")
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
    img = Image.frombytes("RGB", shot.size, shot.rgb)
    img.thumbnail((1024, 1024))  # 작게 보내야 Gemini도 빨리 본다
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=60)
    return buf.getvalue()


def _controls_of_foreground():
    trace.cmd("uiautomation.WalkControl(앞 창, maxDepth=14)  # 버튼·글자칸 목록")
    controls = {}
    with uia.UIAutomationInitializerInThread():
        win = uia.GetForegroundControl()
        top = win.GetTopLevelControl() if win else None
        if not top:
            return "", controls
        title = top.Name
        deadline = time.monotonic() + 1.2
        for ctrl, depth in uia.WalkControl(top, maxDepth=14):
            if time.monotonic() > deadline or len(controls) >= MAX_CONTROLS:
                break
            if ctrl.ControlTypeName not in INTERESTING:
                continue
            name = (ctrl.Name or "").strip()
            if not name and ctrl.ControlTypeName != "EditControl":
                continue
            if name and all("" <= ch <= "" for ch in name):  # 아이콘 글꼴 기호는 빼기
                continue
            try:
                r = ctrl.BoundingRectangle
            except Exception:
                continue
            if r.width() <= 2 or r.height() <= 2 or ctrl.IsOffscreen:
                continue
            cid = f"C{len(controls) + 1}"
            controls[cid] = {"type": ctrl.ControlTypeName.replace("Control", ""), "name": name[:80],
                             "x": (r.left + r.right) // 2, "y": (r.top + r.bottom) // 2,
                             "rect": (r.left, r.top, r.right, r.bottom)}
    return title, controls


_ocr_cache = {"sig": None, "at": 0.0, "lines": []}


def _screen_sig():
    """화면이 바뀌었는지 빨리 알아보는 작은 지문 (64×40으로 줄인 화면)."""
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
    return np.asarray(Image.frombytes("RGB", shot.size, shot.rgb).resize((64, 40)), dtype=np.int16)


def _read_text():
    """화면 글자(OCR). 화면이 그대로면 방금 읽은 걸 다시 쓴다 (OCR은 몇 초 걸린다)."""
    try:
        sig = _screen_sig()
        old = _ocr_cache["sig"]
        # 시계·깜빡이는 커서 같은 아주 작은 변화는 '같은 화면'으로 본다
        if old is not None and float(np.abs(sig - old).mean()) < 1.5 and time.monotonic() - _ocr_cache["at"] < 20:
            return _ocr_cache["lines"]
        lines = ocr.read_screen()
        _ocr_cache.update(sig=sig, at=time.monotonic(), lines=lines)
        return lines
    except Exception as e:
        print("OCR 실패:", e)
        return []


def look_at_screen() -> dict:
    """앞에 있는 창의 이름, 누를 수 있는 것들(C 번호), 화면 글자(L 번호, OCR), 스크린샷."""
    _snapshot["screen"] = _screen_rect()
    ocr_result = {}
    t = threading.Thread(target=lambda: ocr_result.setdefault("lines", _read_text()), daemon=True)
    trace.cmd("Windows.Media.Ocr.OcrEngine(\"ko\").RecognizeAsync(화면)  # 같은 화면이면 캐시")
    t.start()  # 글자 읽기(OCR)는 버튼 목록 모으는 동안 같이
    title, controls = _controls_of_foreground()
    for _ in range(3):  # 막 뜬 창은 내용이 늦게 그려진다 → 잠깐 기다렸다 다시
        if len(controls) > 5:
            break
        time.sleep(0.35)
        title, controls = _controls_of_foreground()
    _snapshot["controls"] = controls
    # 버튼 정보가 충분하면(계산기 등) 글자 읽기를 기다리지 않는다. 읽기는 뒤에서 계속돼서 다음 하이라이트에 쓰인다.
    t.join(0.05 if len(controls) >= 25 else 8)
    text_lines = {}
    for i, l in enumerate(ocr_result.get("lines", [])[:MAX_LINES], 1):
        r = l["rect"]
        text_lines[f"L{i}"] = {"type": "Text", "name": l["text"][:100], "x": (r[0] + r[2]) // 2,
                               "y": (r[1] + r[3]) // 2, "rect": r}
    _snapshot["lines"] = text_lines
    mx, my = pyautogui.position()
    out_controls = []
    for cid, c in controls.items():
        gx, gy = _to_grid(c["x"], c["y"])
        out_controls.append(f"{cid} {c['type']} \"{c['name']}\" @({gx},{gy})")
    out_text = []
    for lid, l in text_lines.items():
        gx, gy = _to_grid(l["x"], l["y"])
        out_text.append(f"{lid} \"{l['name']}\" @({gx},{gy})")
    return {
        "ok": True,
        "foreground_window": title,
        "mouse_at": _to_grid(mx, my),
        "controls": out_controls,
        "text_lines": out_text,
        "note": ("좌표는 0~1000 격자. 스크린샷도 함께 보냈어. 글자(L)는 OCR이라 조금 틀리게 읽힐 수 있어. "
                 "글자를 가리키거나 하이라이트할 땐 text에 화면에 보이는 글자를 그대로 넣는 게 제일 정확하고, "
                 "버튼은 C 번호가 정확해. 눈대중 x, y는 마지막 수단."),
        "_image": _screenshot_jpeg(),
    }


def _lookup(tid: str):
    tid = str(tid).strip()
    return _snapshot["controls"].get(tid) or _snapshot["lines"].get(tid)


def _find_on_screen(text: str) -> list[dict]:
    """지금 화면에서 찾는다: OCR 글자 → Gemini 눈 → 비슷한 글자."""
    return locate.find(text, _read_text())


def _target_point(target_id=None, x=None, y=None, text=None):
    if text:
        hits = _find_on_screen(text)
        if not hits:
            raise ValueError(f"화면에서 '{text}' 글자를 못 찾았어요. look_at_screen으로 다시 보세요.")
        r = hits[0]["rect"]
        return (r[0] + r[2]) // 2, (r[1] + r[3]) // 2, hits[0]["text"]
    if target_id:
        c = _lookup(target_id)
        if not c:
            raise ValueError(f"{target_id}가 없어요. look_at_screen을 다시 불러서 새 번호를 받으세요.")
        return c["x"], c["y"], c["name"]
    if x is None or y is None:
        raise ValueError("target_id 또는 x, y가 필요해요.")
    px, py = _from_grid(x, y)
    return px, py, None


def _check_stop():
    if stop_event.is_set():
        raise RuntimeError("비상정지 상태예요 (Ctrl+Alt+S). 사용자에게 알려 주세요.")


def _fly(px, py, kind):
    on_point(px, py, kind)
    time.sleep(FLY_SECONDS)


def point_at(target_id=None, x=None, y=None, text=None) -> dict:
    if text:
        hits = _find_on_screen(text)
        if not hits:
            return {"ok": False, "error": f"화면에서 '{text}' 글자를 못 찾았어요."}
        r = hits[0]["rect"]
        on_point(r[0] + (r[2] - r[0]) // 2, r[3] + 2, "point")
        on_highlight([(*r, "")], 4.0)
        return {"ok": True, "pointing_at": hits[0]["text"]}
    px, py, name = _target_point(target_id, x, y)
    c = _lookup(target_id) if target_id else None
    if c:  # 가리키는 것에 하이라이트도 살짝
        px, py = (c["rect"][0] + c["rect"][2]) // 2, c["rect"][3] + 2
        on_highlight([(*c["rect"], "")], 4.0)
    on_point(px, py, "point")
    return {"ok": True, "pointing_at": name or _to_grid(px, py)}


def highlight(text: str = "", target_ids: str = "", x=None, y=None, width=None, height=None, label: str = "",
              seconds: float = 8) -> dict:
    """화면 글자(text, 여러 개는 | 로), 버튼·줄(C/L 번호, 쉼표) 또는 격자 영역에 반짝이는 테두리 + 이름표."""
    rects, names = [], []
    if text:
        lines = _read_text()
        missing = []
        for q in [t.strip() for t in str(text).split("|") if t.strip()]:
            hits = locate.find(q, lines, limit=3)
            if not hits:
                missing.append(q)
            for h in hits:
                rects.append((*h["rect"], label))
                names.append(h["text"])
        if missing and not rects:
            return {"ok": False, "error": f"화면에서 {missing} 글자를 못 찾았어요. look_at_screen의 L 번호로 해 보세요."}
    for tid in [t.strip() for t in str(target_ids or "").split(",") if t.strip()]:
        c = _lookup(tid)
        if not c:
            return {"ok": False, "error": f"{tid}가 없어요. look_at_screen을 다시 불러서 새 번호를 받으세요."}
        rects.append((*c["rect"], label))
        names.append(c["name"])
    if x is not None and y is not None:
        left, top = _from_grid(x, y)
        right, bottom = _from_grid(float(x) + float(width or 60), float(y) + float(height or 40))
        rects.append((left, top, right, bottom, label))
        names.append(f"영역({x},{y})")
    if not rects:
        return {"ok": False, "error": "text, target_ids 또는 x, y(와 width, height)가 필요해요."}
    seconds = max(2.0, min(60.0, float(seconds or 8)))
    on_highlight(rects, seconds)
    return {"ok": True, "highlighted": names, "seconds": seconds}


def what_is_under_mouse() -> dict:
    """원본의 "이게 뭐야?": 마우스 아래 있는 것(버튼 이름, 근처 글자, 확대 사진)을 알려 주고 그걸 가리킨다."""
    mx, my = pyautogui.position()
    info = {"ok": True, "mouse_at": _to_grid(mx, my)}
    try:
        with uia.UIAutomationInitializerInThread():
            trace.cmd(f"uiautomation.ControlFromPoint({mx}, {my})")
            ctrl = uia.ControlFromPoint(mx, my)
            if ctrl:
                r = ctrl.BoundingRectangle
                info["element"] = {"type": ctrl.ControlTypeName.replace("Control", ""), "name": (ctrl.Name or "")[:200]}
                top = ctrl.GetTopLevelControl()
                info["window"] = top.Name if top else ""
                if r.width() > 2 and r.height() > 2 and r.width() < 1200:
                    info["_rect"] = (r.left, r.top, r.right, r.bottom)
    except Exception as e:
        info["element_error"] = str(e)[:100]
    near = []
    for line in _read_text():
        l, t, r_, b = line["rect"]
        if l - 250 < mx < r_ + 250 and t - 60 < my < b + 60:
            near.append(line["text"])
    info["text_near_mouse"] = near[:12]
    with mss.mss() as sct:  # 마우스 주변을 확대해서 Gemini가 직접 보게
        box = {"left": max(0, mx - 300), "top": max(0, my - 200), "width": 600, "height": 400}
        shot = sct.grab(box)
    img = Image.frombytes("RGB", shot.size, shot.rgb)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    info["_image"] = buf.getvalue()
    rect = info.pop("_rect", None)
    on_point(mx, my, "point")
    if rect:
        on_highlight([(*rect, "")], 4.0)
    info["note"] = "마우스 주변 확대 사진을 같이 보냈어. 이게 뭔지 한두 문장으로 설명해."
    return info


def clear_highlights() -> dict:
    on_clear_highlights()
    return {"ok": True}


def click(target_id=None, x=None, y=None, double=False, right=False, text=None) -> dict:
    _check_stop()
    px, py, name = _target_point(target_id, x, y, text)
    _fly(px, py, "click")
    _check_stop()
    real = pyautogui.position()
    trace.cmd(f"pyautogui.click({px}, {py}, clicks={2 if double else 1}, button='{'right' if right else 'left'}')")
    pyautogui.click(px, py, clicks=2 if double else 1, interval=0.08, button="right" if right else "left")
    pyautogui.moveTo(*real)  # 내 마우스는 제자리로
    time.sleep(0.12)
    return {"ok": True, "clicked": name or _to_grid(px, py)}


# ---- 타이핑: 한글도 되도록 유니코드 SendInput ----

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send_char(ch: str):
    code = ord(ch)
    seq = []
    for flags in (0x0004, 0x0004 | 0x0002):  # KEYEVENTF_UNICODE, + KEYUP
        inp = _INPUT(type=1)
        inp.ki = _KEYBDINPUT(0, code, flags, 0, 0)
        seq.append(inp)
    arr = (_INPUT * 2)(*seq)
    user32.SendInput(2, arr, ctypes.sizeof(_INPUT))


def _focused_is_password() -> bool:
    try:
        with uia.UIAutomationInitializerInThread():
            f = uia.GetFocusedControl()
            return bool(f and f.GetPropertyValue(uia.PropertyId.IsPasswordProperty))
    except Exception:
        return False


def type_text(text: str, press_return: bool = False) -> dict:
    _check_stop()
    if _focused_is_password():
        return {"ok": False, "error": "비밀번호 칸에는 입력하지 않아요. 사용자에게 직접 입력해 달라고 하세요."}
    trace.cmd(f"SendInput(KEYEVENTF_UNICODE, {text!r})")
    for ch in text:
        _check_stop()
        if ch == "\n":
            pyautogui.press("enter")
        else:
            _send_char(ch)
        time.sleep(0.003)
    if press_return:
        pyautogui.press("enter")
    time.sleep(0.08)
    return {"ok": True, "typed": text}


KEY_NAMES = {"cmd": "win", "windows": "win", "control": "ctrl", "return": "enter", "esc": "escape",
             "del": "delete", "option": "alt", "pgdn": "pagedown", "pgup": "pageup"}


def press_keys(keys: str) -> dict:
    _check_stop()
    parts = [KEY_NAMES.get(k.strip().lower(), k.strip().lower()) for k in keys.replace(" ", "").split("+") if k]
    combo = "+".join(parts)
    if combo in BLOCKED_KEYS or set(parts) >= {"ctrl", "alt", "delete"} or set(parts) == {"win", "l"}:
        return {"ok": False, "error": "잠금/로그아웃 같은 단축키는 쓰지 않아요."}
    bad = [k for k in parts if k not in pyautogui.KEYBOARD_KEYS]
    if bad:
        return {"ok": False, "error": f"모르는 키: {bad}"}
    trace.cmd(f"pyautogui.hotkey({', '.join(repr(k) for k in parts)})")
    pyautogui.hotkey(*parts)
    time.sleep(0.1)
    return {"ok": True, "pressed": combo}


def scroll(direction: str = "down", amount: int = 3, target_id=None, x=None, y=None) -> dict:
    _check_stop()
    if target_id or (x is not None and y is not None):
        px, py, _ = _target_point(target_id, x, y)
    else:
        left, top, w, h = _screen_rect()
        px, py = left + w // 2, top + h // 2
    _fly(px, py, "scroll")
    real = pyautogui.position()
    pyautogui.moveTo(px, py)
    n = max(1, min(10, int(amount))) * 120
    trace.cmd(f"pyautogui.scroll('{direction}', {n}) at ({px}, {py})")
    if direction in ("up", "down"):
        pyautogui.scroll(n if direction == "up" else -n)
    else:
        pyautogui.hscroll(n if direction == "right" else -n)
    pyautogui.moveTo(*real)
    return {"ok": True}


def stop_pointing() -> dict:
    on_home()
    return {"ok": True}
