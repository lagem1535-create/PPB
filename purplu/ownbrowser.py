"""퍼플루 브라우저: 퍼플루가 직접 쓰고, 나도 직접 쓸 수 있는 작은 브라우저 (탭 하나).

따로 도는 프로그램이다 (python -m purplu.ownbrowser). 웹 엔진이 죽어도 퍼플루는 안 죽는다.
- 퍼플루와는 표준 입출력으로 한 줄씩 JSON을 주고받는다: {"id":1,"cmd":"open","args":{...}} → {"id":1,"result":{...}}
- 시작하면 {"hwnd": 창번호} 를 알려 주고, 대화창이 그 창을 위쪽 칸에 끼워 넣는다.
- 확장 브라우저용 page.js 를 그대로 넣어 읽기·찾기·입력을 똑같이 한다.
"""
import base64
import json
import sys
import threading
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QPointF, Qt, QTimer, QUrl, Signal, QObject
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

ROOT = Path(__file__).resolve().parent.parent
PAGE_JS = (ROOT / "chrome_extension" / "page.js").read_text(encoding="utf-8")
HOME = "https://www.google.com/"


def _out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return HOME
    if "://" in u or u.startswith(("about:", "data:")):
        return u
    if "." in u and " " not in u:
        return "https://" + u
    return "https://www.google.com/search?q=" + quote(u)   # 주소가 아니면 검색


class _Reader(QObject):
    got = Signal(dict)

    def run(self):
        for line in sys.stdin:
            try:
                self.got.emit(json.loads(line))
            except Exception:
                pass
        QTimer.singleShot(0, QApplication.quit)   # 퍼플루가 꺼지면 같이 꺼진다


class Browser(QWidget):
    def __init__(self, light=True):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool)
        self.setWindowTitle("퍼플루 브라우저")
        data = ROOT / "data" / "browser"
        data.mkdir(parents=True, exist_ok=True)
        self.profile = QWebEngineProfile("purplu", self)   # 로그인·쿠키가 남는다 (data/browser)
        self.profile.setPersistentStoragePath(str(data / "storage"))
        self.profile.setCachePath(str(data / "cache"))
        self.page_ = QWebEnginePage(self.profile, self)
        self.view = QWebEngineView()
        self.view.setPage(self.page_)
        # 새 창·새 탭으로 열려는 링크도 이 탭 하나에서 (탭이 늘어나지 않게)
        self.page_.newWindowRequested.connect(lambda req: self.page_.setUrl(req.requestedUrl()))

        bg, fg, line = ("#FFFFFF", "#18181B", "#E4E4E7") if light else ("#18181B", "#F4F4F5", "#3F3F46")
        bar = QWidget()
        bar.setStyleSheet(f"background:{bg}; border-bottom:1px solid {line};")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(4)
        btn_css = (f"QPushButton {{ background:transparent; border:none; border-radius:8px; color:{fg}; font-size:13pt; }}"
                   f"QPushButton:hover {{ background:{line}; }}")
        for text, tip, fn in (("←", "뒤로", self.view.back), ("→", "앞으로", self.view.forward), ("⟳", "새로고침", self.view.reload)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedSize(30, 28)
            b.setStyleSheet(btn_css)
            b.clicked.connect(fn)
            h.addWidget(b)
        self.url = QLineEdit()
        self.url.setPlaceholderText("주소나 검색어 입력")
        self.url.setStyleSheet(f"QLineEdit {{ background:{line}; color:{fg}; border:none; border-radius:12px; padding:5px 12px; }}")
        self.url.returnPressed.connect(lambda: self.view.setUrl(QUrl(norm_url(self.url.text()))))
        h.addWidget(self.url, 1)
        self.view.urlChanged.connect(lambda u: self.url.setText(u.toString()) if not self.url.hasFocus() else None)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(bar)
        v.addWidget(self.view, 1)

        self._load_waiters = []
        self.view.loadFinished.connect(self._loaded)
        self.view.setUrl(QUrl(HOME))

    # ---- 명령 ----
    def handle(self, msg: dict):
        mid, cmd, a = msg.get("id"), msg.get("cmd"), msg.get("args") or {}

        def reply(result):
            _out({"id": mid, "result": result})
        try:
            fn = getattr(self, "c_" + str(cmd), None)
            if not fn:
                return reply({"ok": False, "error": f"모르는 명령: {cmd}"})
            fn(a, reply)
        except Exception as e:
            reply({"ok": False, "error": f"{type(e).__name__}: {e}"})

    def _loaded(self, ok):
        waiters, self._load_waiters = self._load_waiters, []
        for w in waiters:
            w()

    def _after_load(self, fn, timeout=20000):
        done = {"x": False}

        def once():
            if not done["x"]:
                done["x"] = True
                QTimer.singleShot(400, fn)   # 그려질 시간을 조금 준다
        self._load_waiters.append(once)
        QTimer.singleShot(timeout, once)

    def _js(self, call: str, cb):
        """page.js 를 넣고 PURPLU_PAGE.이름(...) 결과를 cb 로."""
        # 큰 객체는 그대로 넘기면 비어서 오므로 JSON 글로 받아서 푼다
        self.page_.runJavaScript(PAGE_JS + "\n;JSON.stringify(" + call + ")", 0,
                                 lambda r: cb(json.loads(r) if isinstance(r, str) and r else None))

    def _info(self):
        return {"title": self.page_.title(), "url": self.page_.url().toString()}

    def c_open(self, a, reply):
        self.view.setUrl(QUrl(norm_url(a.get("url", ""))))
        self._after_load(lambda: reply({"ok": True, "tab_id": 1, "opened": self.page_.title() or a.get("url"), **self._info()}))

    def c_tabs(self, a, reply):
        reply({"ok": True, "tabs": [{"tab_id": 1, "active": True, **self._info()}]})

    def c_switch(self, a, reply):
        reply({"ok": True, "tab_id": 1, **self._info()})

    def c_close(self, a, reply):
        self.view.setUrl(QUrl(HOME))
        reply({"ok": True, "closed": True})

    def c_read(self, a, reply):
        n = int(a.get("max_chars") or 6000)
        self._js(f"PURPLU_PAGE.pageRead({n})", lambda r: reply({"ok": True, "tab_id": 1, **(r or {})}))

    def _mouse(self, x, y, double=False, right=False):
        target = self.view.focusProxy() or self.view
        p = QPointF(x, y)
        btn = Qt.RightButton if right else Qt.LeftButton
        for _ in range(2 if double else 1):
            for t in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                QApplication.sendEvent(target, QMouseEvent(t, p, p, btn, btn if t == QEvent.MouseButtonPress else Qt.NoButton, Qt.NoModifier))
        if double:
            QApplication.sendEvent(target, QMouseEvent(QEvent.MouseButtonDblClick, p, p, btn, btn, Qt.NoModifier))

    def c_click(self, a, reply):
        if a.get("x") is not None and a.get("y") is not None:
            self._mouse(a["x"], a["y"], a.get("double"), a.get("right"))
            return QTimer.singleShot(700, lambda: reply({"ok": True, "clicked": f"({a['x']}, {a['y']})", **self._info()}))

        def got(r):
            if not r or not r.get("ok"):
                return reply(r or {"ok": False, "error": "그 요소를 못 찾았어요."})
            self._mouse(r["x"], r["y"], a.get("double"), a.get("right"))   # 진짜 마우스처럼
            QTimer.singleShot(700, lambda: reply({"ok": True, "clicked": r.get("clicked"), **self._info()}))
        self._js(f"PURPLU_PAGE.pageLocate({json.dumps(a.get('element_id') or '')}, {json.dumps(a.get('text') or '')})", got)

    def c_type(self, a, reply):
        text = str(a.get("text", ""))

        def typed(r):
            if not r or not r.get("ok"):
                return reply(r or {"ok": False, "error": "입력할 칸을 못 찾았어요."})
            if a.get("submit"):
                self._key("Enter")
                return self._after_load(lambda: reply({"ok": True, "typed": text[:60], "submitted": True, **self._info()}), 4000)
            reply({"ok": True, "typed": text[:60]})
        self._js(f"PURPLU_PAGE.pageType({json.dumps(a.get('element_id') or '')}, {json.dumps(text)}, false, "
                 f"{'true' if a.get('allow_password') else 'false'})", typed)

    KEYS = {"enter": Qt.Key_Return, "tab": Qt.Key_Tab, "escape": Qt.Key_Escape, "esc": Qt.Key_Escape,
            "backspace": Qt.Key_Backspace, "delete": Qt.Key_Delete, "up": Qt.Key_Up, "down": Qt.Key_Down,
            "left": Qt.Key_Left, "right": Qt.Key_Right, "pagedown": Qt.Key_PageDown, "pageup": Qt.Key_PageUp,
            "home": Qt.Key_Home, "end": Qt.Key_End, "space": Qt.Key_Space}
    MODS = {"ctrl": Qt.ControlModifier, "control": Qt.ControlModifier, "shift": Qt.ShiftModifier, "alt": Qt.AltModifier}

    def _key(self, combo: str):
        target = self.view.focusProxy() or self.view
        parts = [p.strip().lower() for p in combo.replace("-", "+").split("+") if p.strip()]
        mods = Qt.NoModifier
        for p in parts[:-1]:
            mods |= self.MODS.get(p, Qt.NoModifier)
        k = parts[-1] if parts else ""
        if k in self.KEYS:
            code, text = self.KEYS[k], {"enter": "\r", "space": " ", "tab": "\t"}.get(k, "")
        elif len(k) == 1:
            code, text = ord(k.upper()), ("" if mods & Qt.ControlModifier else k)
        else:
            return False
        for t in (QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(target, QKeyEvent(t, code, mods, text))
        return True

    def c_keys(self, a, reply):
        done = [k for k in str(a.get("keys", "")).split() if self._key(k)]
        QTimer.singleShot(500, lambda: reply({"ok": bool(done), "pressed": " ".join(done) or a.get("keys")}))

    def c_scroll(self, a, reply):
        self._js(f"PURPLU_PAGE.pageScroll({json.dumps(a.get('direction', 'down'))}, {int(a.get('amount') or 3)})",
                 lambda r: reply(r or {"ok": True}))

    def c_back(self, a, reply):
        self.view.back()
        self._after_load(lambda: reply({"ok": True, **self._info()}), 6000)

    def c_forward(self, a, reply):
        self.view.forward()
        self._after_load(lambda: reply({"ok": True, **self._info()}), 6000)

    def c_reload(self, a, reply):
        self.view.reload()
        self._after_load(lambda: reply({"ok": True, **self._info()}), 8000)

    def c_screenshot(self, a, reply):
        pm = self.view.grab()
        pm.setDevicePixelRatio(1)
        pm = pm.scaled(self.view.width(), self.view.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)   # 사진 1px = 페이지 1px
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.WriteOnly)
        pm.save(buf, "PNG")
        reply({"ok": True, "image_b64": base64.b64encode(bytes(ba)).decode(), "width": pm.width(), "height": pm.height(), **self._info()})

    def c_highlight(self, a, reply):
        color = {"yellow": "#FDE047", "green": "#86EFAC", "blue": "#93C5FD", "pink": "#F9A8D4"}.get(a.get("color"), "#C4B5FD")
        js = ("(function(t,c){if(!window.find(t))return {ok:false,error:'그 글을 못 찾았어요.'};"
              "const s=getSelection();if(!s.rangeCount)return {ok:false};const m=document.createElement('mark');"
              "m.style.background=c;try{s.getRangeAt(0).surroundContents(m)}catch(e){};s.removeAllRanges();"
              "m.scrollIntoView({block:'center'});return {ok:true,highlighted:t}})"
              f"({json.dumps(a.get('text', ''))},{json.dumps(color)})")
        self.page_.runJavaScript(js, 0, lambda r: reply(r or {"ok": False}))

    def c_show(self, a, reply):
        reply({"ok": True, **self._info()})


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    app = QApplication(sys.argv)
    light = "--dark" not in sys.argv
    w = Browser(light)
    w.resize(640, 420)
    w.move(-20000, -20000)   # 대화창에 끼워지기 전엔 화면 밖에서 그려 둔다
    w.show()
    _out({"hwnd": int(w.winId())})
    reader = _Reader()
    reader.got.connect(w.handle)
    threading.Thread(target=reader.run, daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
