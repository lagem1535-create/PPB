"""퍼플루 브라우저: 퍼플루가 직접 쓰고, 나도 직접 쓸 수 있는 작은 브라우저 (크롬처럼 탭 여러 개).

따로 도는 프로그램이다 (python -m purplu.ownbrowser). 웹 엔진이 죽어도 퍼플루는 안 죽는다.
- 퍼플루와는 표준 입출력으로 한 줄씩 JSON을 주고받는다: {"id":1,"cmd":"open","args":{...}} → {"id":1,"result":{...}}
- 시작하면 {"hwnd": 창번호} 를 알려 주고, 대화창이 그 창을 위쪽 칸에 끼워 넣는다.
- 확장 브라우저용 page.js 를 그대로 넣어 읽기·찾기·입력을 똑같이 한다.
"""
import base64
import json
import re
import sys
import threading
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QPointF, Qt, QTimer, QUrl, QUrlQuery, Signal, QObject
import math

from PySide6.QtCore import QPoint, QRectF
from PySide6.QtGui import QColor, QKeyEvent, QKeySequence, QMouseEvent, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLineEdit, QProgressBar, QPushButton, QStackedWidget,
                               QTabBar, QVBoxLayout, QWidget)
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

ROOT = Path(__file__).resolve().parent.parent
PAGE_JS = (ROOT / "chrome_extension" / "page.js").read_text(encoding="utf-8")
HOME = "https://www.google.com/"


def mix(a: str, b: str, t: float) -> str:
    """색 a 에 색 b 를 t 만큼 섞기 (윗줄을 내 색으로 옅게 물들일 때)."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def _out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def to_url(u: str) -> QUrl:
    """주소면 그 주소, 아니면 구글 검색. 이미 %EC%98… 처럼 바뀐 글도 한 번만 바뀌게 (두 번 바뀌면 검색창에 %가 보인다)."""
    u = (u or "").strip()
    if not u:
        return QUrl(HOME)
    if "://" in u or u.startswith(("about:", "data:")) or ("." in u and " " not in u and not re.search(r"[가-힣]", u)):
        return QUrl.fromUserInput(u)
    if re.search(r"%[0-9A-Fa-f]{2}", u):
        u = unquote(u)
    url = QUrl("https://www.google.com/search")
    q = QUrlQuery()
    q.addQueryItem("q", u.replace("+", " ") if "%" not in u else u)
    url.setQuery(q)
    return url


class _Reader(QObject):
    got = Signal(dict)

    def run(self):
        for line in sys.stdin:
            try:
                self.got.emit(json.loads(line))
            except Exception:
                pass
        QTimer.singleShot(0, QApplication.quit)   # 퍼플루가 꺼지면 같이 꺼진다


class NavButton(QPushButton):
    """뒤로·앞으로·새로고침·홈·밖에서 열기를 같은 굵기의 선으로 (대화창 머리줄 아이콘과 같은 모양)."""

    def __init__(self, kind, tip, fg, hover, accent):
        super().__init__()
        self.kind, self.fg, self.hover_bg, self.accent = kind, QColor(fg), QColor(hover), QColor(accent)
        self._hover = False
        self.setToolTip(tip)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._hover and self.isEnabled():
            p.setPen(Qt.NoPen)
            p.setBrush(self.hover_bg)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)
        col = QColor(self.fg)
        if not self.isEnabled():
            col.setAlpha(70)
        p.setPen(QPen(col, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        cx, cy, k = self.width() / 2, self.height() / 2, self.kind
        if k in ("back", "forward"):
            d = -1 if k == "back" else 1
            p.drawLine(QPointF(cx - 6 * d, cy), QPointF(cx + 6 * d, cy))
            p.drawLine(QPointF(cx + 6 * d, cy), QPointF(cx + 1 * d, cy - 5))
            p.drawLine(QPointF(cx + 6 * d, cy), QPointF(cx + 1 * d, cy + 5))
        elif k == "reload":
            p.drawArc(QRectF(cx - 6, cy - 6, 12, 12), 60 * 16, 290 * 16)
            a = math.radians(60)
            tip = QPointF(cx + 6 * math.cos(a), cy - 6 * math.sin(a))
            p.drawLine(tip, tip + QPointF(-4.5, -0.5))
            p.drawLine(tip, tip + QPointF(0.5, 4.5))
        elif k == "stop":
            p.drawLine(QPointF(cx - 5, cy - 5), QPointF(cx + 5, cy + 5))
            p.drawLine(QPointF(cx + 5, cy - 5), QPointF(cx - 5, cy + 5))
        elif k == "home":
            path = QPainterPath()
            path.moveTo(cx - 6.5, cy - 0.5)
            path.lineTo(cx, cy - 6.5)
            path.lineTo(cx + 6.5, cy - 0.5)
            p.drawPath(path)
            p.drawRoundedRect(QRectF(cx - 4.5, cy - 2, 9, 8), 1.5, 1.5)
        elif k == "plus":
            p.drawLine(QPointF(cx - 6, cy), QPointF(cx + 6, cy))
            p.drawLine(QPointF(cx, cy - 6), QPointF(cx, cy + 6))
        elif k == "external":   # 네모 + 오른쪽 위 화살표 (내 브라우저로 열기)
            p.drawRoundedRect(QRectF(cx - 6, cy - 4, 10, 10), 2, 2)
            p.drawLine(QPointF(cx - 0.5, cy + 0.5), QPointF(cx + 6.5, cy - 6.5))
            p.drawLine(QPointF(cx + 6.5, cy - 6.5), QPointF(cx + 2, cy - 6.5))
            p.drawLine(QPointF(cx + 6.5, cy - 6.5), QPointF(cx + 6.5, cy - 2))


class UrlBox(QLineEdit):
    """평소엔 'google.com' 처럼 짧게, 누르면 전체 주소를 골라 둔 채로."""

    def __init__(self):
        super().__init__()
        self.full = ""

    def show_url(self, u: QUrl):
        self.full = u.toString()
        if not self.hasFocus():
            host = u.host().removeprefix("www.")
            self.setText(host + (u.path() if u.path() not in ("", "/") else "") if host else self.full)
            self.setCursorPosition(0)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.setText(self.full)
        QTimer.singleShot(0, self.selectAll)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.show_url(QUrl(self.full))


class Tab:
    """탭 하나 = 페이지 하나. id 는 1, 2, 3… (퍼플루가 browser_switch_tab 으로 고른다)."""

    def __init__(self, tid, view, page):
        self.id, self.view, self.page = tid, view, page
        self.waiters = []


class Browser(QWidget):
    def __init__(self, light=True, accent="#8B5CF6"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool)
        self.setWindowTitle("퍼플루 브라우저")
        data = ROOT / "data" / "browser"
        data.mkdir(parents=True, exist_ok=True)
        self.profile = QWebEngineProfile("purplu", self)   # 로그인·쿠키가 남는다 (data/browser)
        self.profile.setPersistentStoragePath(str(data / "storage"))
        self.profile.setCachePath(str(data / "cache"))
        # 'QtWebEngine' 이 보이면 구글이 "크롬을 쓰세요" 창을 띄운다 → 보통 크롬처럼
        ua = self.profile.httpUserAgent()
        self.profile.setHttpUserAgent(" ".join(t for t in ua.split() if not t.startswith("QtWebEngine")))
        self._hide_google_footer()
        self.tabs: list[Tab] = []
        self._next_id = 1
        self._loading = False

        bg, fg, dim, field, line = (("#FFFFFF", "#18181B", "#71717A", "#F4F4F5", "#E4E4E7") if light
                                    else ("#18181B", "#F4F4F5", "#A1A1AA", "#27272A", "#3F3F46"))
        # 윗줄만 내 색: 바탕은 아주 옅게, 주소창은 조금 더, 아이콘은 내 색
        top, field, hover = mix(bg, accent, 0.06 if light else 0.12), mix(bg, accent, 0.13 if light else 0.22), mix(bg, accent, 0.22 if light else 0.32)
        strip = mix(bg, accent, 0.14 if light else 0.2)   # 탭 줄 바탕 (고른 탭은 윗줄과 같은 색으로 이어진다)
        self.setStyleSheet(f"Browser {{ background:{bg}; }}")

        # ---- 탭 줄 ----
        tabrow = QFrame()
        tabrow.setObjectName("tabrow")
        tabrow.setStyleSheet(f"QFrame#tabrow {{ background:{strip}; }}")
        tr = QHBoxLayout(tabrow)
        tr.setContentsMargins(6, 5, 6, 0)
        tr.setSpacing(2)
        self.tabbar = QTabBar()
        self.tabbar.setTabsClosable(True)
        self.tabbar.setMovable(True)
        self.tabbar.setExpanding(False)
        self.tabbar.setDocumentMode(True)
        self.tabbar.setElideMode(Qt.ElideRight)
        self.tabbar.setUsesScrollButtons(True)
        self.tabbar.setDrawBase(False)
        self.tabbar.setStyleSheet(
            f"QTabBar {{ background:transparent; }}"
            f"QTabBar::tab {{ background:transparent; color:{dim}; border:none; border-top-left-radius:9px; border-top-right-radius:9px;"
            f" padding:6px 6px 6px 10px; margin-right:1px; min-width:60px; max-width:170px; font-size:9pt; }}"
            f"QTabBar::tab:selected {{ background:{top}; color:{fg}; }}"
            f"QTabBar::tab:hover:!selected {{ background:{mix(strip, bg, 0.45)}; }}"
            f"QTabBar::close-button {{ subcontrol-position:right; }}")
        self.tabbar.currentChanged.connect(self._tab_changed)
        self.tabbar.tabCloseRequested.connect(lambda i: self.close_tab(self._tab_at(i)))
        self.tabbar.tabMoved.connect(self._tab_moved)
        tr.addWidget(self.tabbar, 0, Qt.AlignBottom)
        self.b_new = NavButton("plus", "새 탭 (Ctrl+T)", accent, hover, accent)
        self.b_new.setFixedSize(28, 28)
        self.b_new.clicked.connect(lambda: self.new_tab(HOME))
        tr.addWidget(self.b_new, 0, Qt.AlignVCenter)
        tr.addStretch(1)

        # ---- 윗줄: 뒤로 앞으로 새로고침 [주소] 밖에서 열기 ----
        bar = QFrame()
        bar.setObjectName("bar")
        bar.setStyleSheet(f"QFrame#bar {{ background:{top}; }}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(2)
        mk = lambda kind, tip: NavButton(kind, tip, accent, hover, accent)   # noqa: E731
        self.b_back, self.b_fwd, self.b_reload = mk("back", "뒤로"), mk("forward", "앞으로"), mk("reload", "새로고침")
        self.b_back.clicked.connect(lambda: self.view.back())
        self.b_fwd.clicked.connect(lambda: self.view.forward())
        self.b_reload.clicked.connect(lambda: self.view.stop() if self._loading else self.view.reload())
        for b in (self.b_back, self.b_fwd, self.b_reload):
            h.addWidget(b)
        h.addSpacing(4)

        pill = QFrame()
        pill.setObjectName("pill")
        pill.setStyleSheet(f"QFrame#pill {{ background:{field}; border:1px solid transparent; border-radius:16px; }}"
                           f"QFrame#pill[focus=\"true\"] {{ border:1.5px solid {accent}; background:{bg}; }}")
        pl = QHBoxLayout(pill)
        pl.setContentsMargins(12, 0, 6, 0)
        pl.setSpacing(6)
        self.url = UrlBox()
        self.url.setPlaceholderText("주소나 검색어")
        self.url.setStyleSheet(f"QLineEdit {{ background:transparent; color:{fg}; border:none; padding:6px 0; font-size:10pt; }}"
                               f"QLineEdit::placeholder {{ color:{dim}; }}")
        self.url.returnPressed.connect(lambda: (self.view.setUrl(to_url(self.url.text())), self.view.setFocus()))
        self.url.installEventFilter(self)
        self._pill = pill
        pl.addWidget(self.url, 1)
        self.b_home = mk("home", "처음 화면 (구글)")
        self.b_home.setFixedSize(26, 26)
        self.b_home.clicked.connect(lambda: self.view.setUrl(QUrl(HOME)))
        pl.addWidget(self.b_home)
        h.addWidget(pill, 1)
        h.addSpacing(2)
        self.b_out = mk("external", "내 브라우저(웨일·크롬)에서 열기")
        self.b_out.clicked.connect(lambda: __import__("webbrowser").open(self.page_.url().toString()))
        h.addWidget(self.b_out)

        # 불러오는 중: 윗줄 아래 가는 줄 (내 색)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(2)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(f"QProgressBar {{ background:{line}; border:none; }} QProgressBar::chunk {{ background:{accent}; }}")

        self.stack = QStackedWidget()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(tabrow)
        v.addWidget(bar)
        v.addWidget(self.progress)
        v.addWidget(self.stack, 1)

        # 크롬과 같은 단축키
        for keys, fn in (("Ctrl+T", lambda: (self.new_tab(HOME), self.url.setFocus())), ("Ctrl+W", lambda: self.close_tab(self.cur)),
                         ("Ctrl+Tab", lambda: self._step_tab(1)), ("Ctrl+Shift+Tab", lambda: self._step_tab(-1)),
                         ("Ctrl+L", lambda: self.url.setFocus()), ("F5", lambda: self.view.reload()),
                         ("Alt+Left", lambda: self.view.back()), ("Alt+Right", lambda: self.view.forward())):
            QShortcut(QKeySequence(keys), self, fn, context=Qt.WindowShortcut)
        self.new_tab(HOME)

    # ---- 탭 ----
    @property
    def cur(self) -> Tab:
        return self._tab_at(self.tabbar.currentIndex()) or self.tabs[0]

    @property
    def view(self):
        return self.cur.view

    @property
    def page_(self):
        return self.cur.page

    def _tab_at(self, i):
        tid = self.tabbar.tabData(i)
        return next((t for t in self.tabs if t.id == tid), None)

    def _index_of(self, tab):
        return next((i for i in range(self.tabbar.count()) if self.tabbar.tabData(i) == tab.id), -1)

    def find(self, tid):
        return next((t for t in self.tabs if t.id == int(tid)), None)

    def new_tab(self, url, switch=True) -> Tab:
        page = QWebEnginePage(self.profile, self)
        view = QWebEngineView()
        view.setPage(page)
        view.setZoomFactor(0.9)   # 대화창 위 좁은 칸에서도 한눈에
        tab = Tab(self._next_id, view, page)
        self._next_id += 1
        self.tabs.append(tab)
        self.stack.addWidget(view)
        i = self.tabbar.addTab("새 탭")
        self.tabbar.setTabData(i, tab.id)
        # 새 창·새 탭으로 열려는 링크는 새 탭으로 (뒤에서 열라는 건 뒤에서)
        page.newWindowRequested.connect(lambda req: self.new_tab(req.requestedUrl(), switch=req.destination() != req.DestinationType.InNewBackgroundTab))
        page.titleChanged.connect(lambda t, tab=tab: self._set_title(tab, t))
        page.iconChanged.connect(lambda ic, tab=tab: self.tabbar.setTabIcon(self._index_of(tab), ic))
        view.loadStarted.connect(lambda tab=tab: tab is self.cur and self._set_loading(True))
        view.loadProgress.connect(lambda p, tab=tab: tab is self.cur and self.progress.setValue(p))
        view.loadFinished.connect(lambda ok, tab=tab: self._loaded(tab))
        view.urlChanged.connect(lambda u, tab=tab: tab is self.cur and self._url_changed(u))
        page.windowCloseRequested.connect(lambda tab=tab: self.close_tab(tab))
        view.setUrl(url if isinstance(url, QUrl) else to_url(url))
        if switch:
            self.tabbar.setCurrentIndex(i)
        return tab

    def close_tab(self, tab):
        if tab is None:
            return
        if len(self.tabs) == 1:   # 마지막 탭은 닫는 대신 처음 화면으로
            tab.view.setUrl(QUrl(HOME))
            return
        i = self._index_of(tab)
        self.tabs.remove(tab)
        self.tabbar.removeTab(i)
        self.stack.removeWidget(tab.view)
        tab.view.deleteLater()

    def _step_tab(self, d):
        n = self.tabbar.count()
        self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + d) % n)

    def _tab_changed(self, i):
        tab = self._tab_at(i)
        if tab is None:
            return
        self.stack.setCurrentWidget(tab.view)
        self.url.show_url(tab.page.url())
        self._set_loading(tab.page.isLoading() if hasattr(tab.page, "isLoading") else False)

    def _tab_moved(self, *_):
        pass   # 탭 줄의 순서만 바뀌고, 탭 번호(id)는 그대로

    def _set_title(self, tab, t):
        i = self._index_of(tab)
        if i >= 0:
            self.tabbar.setTabText(i, t or "새 탭")
            self.tabbar.setTabToolTip(i, t)

    def eventFilter(self, obj, e):
        if obj is self.url and e.type() in (QEvent.FocusIn, QEvent.FocusOut):   # 주소창을 누르면 테두리를 내 색으로
            self._pill.setProperty("focus", e.type() == QEvent.FocusIn)
            self._pill.style().unpolish(self._pill)
            self._pill.style().polish(self._pill)
        return False

    def _set_loading(self, on: bool):
        self._loading = on
        self.b_reload.kind = "stop" if on else "reload"
        self.b_reload.setToolTip("멈추기" if on else "새로고침")
        self.b_reload.update()
        self.progress.setVisible(on)
        if on:
            self.progress.setValue(5)
        self._nav_buttons()

    def _url_changed(self, u):
        self.url.show_url(u)
        self._nav_buttons()

    def _nav_buttons(self):
        hist = self.page_.history()
        self.b_back.setEnabled(hist.canGoBack())
        self.b_fwd.setEnabled(hist.canGoForward())

    def _hide_google_footer(self):
        """구글 화면 맨 아래 '대한민국 · 광고 · 비즈니스 · Google 검색의 작동 방식' 줄을 안 보이게."""
        from PySide6.QtWebEngineCore import QWebEngineScript
        js = r"""(() => {
  if (!/(^|\.)google\.[a-z.]+$/.test(location.hostname)) return;
  const st = document.createElement("style");
  st.textContent = "[role=contentinfo], #footcnt, .fbar, .c93Gbe { display:none !important; }";
  (document.head || document.documentElement).appendChild(st);
  const hide = () => {
    const a = [...document.querySelectorAll("a")].find(x => /검색의 작동 방식|How Search works/.test(x.textContent));
    if (!a) return;
    let el = a;   // 그 링크를 감싼 아래쪽 띠 전체 (너무 큰 덩어리까지는 안 올라감)
    while (el.parentElement && el.parentElement !== document.body && el.parentElement.getBoundingClientRect().height < 180) el = el.parentElement;
    el.style.setProperty("display", "none", "important");
  };
  // "Chrome을 선택하세요" 창은 '사용 안함'을 눌러 닫는다 (한 번 닫으면 구글이 기억함)
  const noChrome = () => {
    const b = [...document.querySelectorAll("button, [role=button], a")].find(x => /^(Chrome 사용 안함|사용 안함|No thanks)$/.test((x.textContent || "").trim()));
    if (b) b.click();
  };
  const both = () => { hide(); noChrome(); };
  both(); setTimeout(both, 800); setTimeout(both, 2500); setTimeout(both, 5000);
})();"""
        sc = QWebEngineScript()
        sc.setName("purplu-hide-google-footer")
        sc.setSourceCode(js)
        sc.setInjectionPoint(QWebEngineScript.DocumentReady)
        sc.setWorldId(QWebEngineScript.ApplicationWorld)
        sc.setRunsOnSubFrames(False)
        self.profile.scripts().insert(sc)

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

    def _loaded(self, tab):
        if tab is self.cur:
            self._set_loading(False)
        waiters, tab.waiters = tab.waiters, []
        for w in waiters:
            w()

    def _after_load(self, fn, timeout=20000, tab=None):
        tab = tab or self.cur
        done = {"x": False}

        def once():
            if not done["x"]:
                done["x"] = True
                QTimer.singleShot(400, fn)   # 그려질 시간을 조금 준다
        tab.waiters.append(once)
        QTimer.singleShot(timeout, once)

    def _js(self, call: str, cb):
        """page.js 를 넣고 PURPLU_PAGE.이름(...) 결과를 cb 로."""
        # 큰 객체는 그대로 넘기면 비어서 오므로 JSON 글로 받아서 푼다
        self.page_.runJavaScript(PAGE_JS + "\n;JSON.stringify(" + call + ")", 0,
                                 lambda r: cb(json.loads(r) if isinstance(r, str) and r else None))

    def _info(self, tab=None):
        tab = tab or self.cur
        return {"tab_id": tab.id, "title": tab.page.title(), "url": tab.page.url().toString()}

    def c_open(self, a, reply):
        if a.get("new_tab"):
            tab = self.new_tab(to_url(a.get("url", "")))
        else:
            tab = self.cur
            tab.view.setUrl(to_url(a.get("url", "")))
        self._after_load(lambda: reply({"ok": True, "opened": tab.page.title() or a.get("url"), **self._info(tab)}), tab=tab)

    def c_tabs(self, a, reply):
        order = [self._tab_at(i) for i in range(self.tabbar.count())]
        reply({"ok": True, "tabs": [{**self._info(t), "active": t is self.cur} for t in order if t]})

    def c_switch(self, a, reply):
        tab = self.find(a.get("tab_id", 0))
        if not tab:
            return reply({"ok": False, "error": "그 번호의 탭이 없어요. browser_tabs로 번호를 확인하세요."})
        self.tabbar.setCurrentIndex(self._index_of(tab))
        reply({"ok": True, **self._info(tab)})

    def c_close(self, a, reply):
        tab = self.find(a["tab_id"]) if a.get("tab_id") is not None else self.cur
        if not tab:
            return reply({"ok": False, "error": "그 번호의 탭이 없어요."})
        self.close_tab(tab)
        reply({"ok": True, "closed": True, "tabs_left": len(self.tabs)})

    def c_read(self, a, reply):
        n = int(a.get("max_chars") or 6000)
        tab = self.cur
        self._js(f"PURPLU_PAGE.pageRead({n})", lambda r: reply({"ok": True, "tab_id": tab.id, "tabs_open": len(self.tabs), **(r or {})}))

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
            z = self.view.zoomFactor()   # 페이지 좌표 → 화면 좌표 (작게 보기)
            self._mouse(r["x"] * z, r["y"] * z, a.get("double"), a.get("right"))   # 진짜 마우스처럼
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
    accent = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--color=")), "#8B5CF6")
    w = Browser(light, accent)
    w.resize(640, 420)
    w.move(-20000, -20000)   # 대화창에 끼워지기 전엔 화면 밖에서 그려 둔다
    w.show()
    _out({"hwnd": int(w.winId())})
    parent = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--parent=")), 0)
    if parent:   # 퍼플루가 강제로 꺼져도 혼자 남지 않게 3초마다 확인
        import psutil
        watch = QTimer(timeout=lambda: psutil.pid_exists(parent) or app.quit())
        watch.start(3000)
    reader = _Reader()
    reader.got.connect(w.handle)
    threading.Thread(target=reader.run, daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
