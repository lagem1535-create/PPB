// 퍼플루 브라우저 손: 이 PC에서 돌아가는 퍼플루(ws://127.0.0.1:8765/ext)와 연결해서
// 퍼플루가 보내는 명령(탭·읽기·클릭·입력·키보드·스크롤·스크린샷·하이라이트)을 실행하고 결과를 돌려준다.
//
// 클릭·입력은 Claude in Chrome처럼 크롬 디버거(CDP)로 '진짜' 마우스·키보드 신호를 보낸다.
// (웹페이지가 가짜 click()을 무시하는 경우가 많아서.) 디버거를 못 쓰면 예전 방식으로 대신 한다.

// 퍼플루와의 연결은 숨은 페이지(offscreen.html)가 늘 붙잡고 있다.
// (백그라운드 일꾼은 브라우저가 수시로 재워서 — 특히 웨일 — 연결이 끊겼었다.)
// 숨은 페이지 → 여기: {type:"cmd", msg} 를 받아 실행하고 결과를 돌려준다.
let connected = false;

async function ensureOffscreen() {
  if (!chrome.offscreen) { legacyConnect(); return; }   // 숨은 페이지를 못 쓰는 브라우저면 예전 방식
  try {
    if (await chrome.offscreen.hasDocument()) return;
    await chrome.offscreen.createDocument({ url: "offscreen.html", reasons: ["WORKERS"], justification: "PC의 퍼플루와 연결을 유지" });
  } catch (e) {
    if (!String(e.message || e).includes("single offscreen")) legacyConnect();
  }
}

async function handle(msg) {
  if (msg.type === "settings") { await chrome.storage.local.set({ purplu_settings: msg.data || {} }); return null; }
  if (!msg.id) return null;
  const show = WORK_CMDS.has(msg.cmd);
  if (show) await working(true, msg.cmd);
  let reply;
  try { reply = { id: msg.id, ok: true, result: await run(msg.cmd, msg.args || {}) }; }
  catch (err) { reply = { id: msg.id, ok: false, error: String(err && err.message || err) }; }
  if (show) working(false);
  return reply;
}

chrome.runtime.onMessage.addListener((m, sender, send) => {
  if (m && m.type === "cmd") { handle(m.msg).then(send); return true; }      // 숨은 페이지가 보낸 명령
  if (m && m.type === "conn") { connected = !!m.on; chrome.action.setBadgeText({ text: m.on ? "" : "off" }); return; }
  if (m && m.type === "keepalive") { send({ ok: true }); return; }
});
function toPurplu(data) { chrome.runtime.sendMessage({ type: "to_purplu", data }).catch(() => {}); }

// 숨은 페이지를 못 쓸 때만: 예전처럼 여기서 직접 연결
let ws = null, retry = 0;
function legacyConnect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  try { ws = new WebSocket("ws://127.0.0.1:8765/ext"); } catch { return; }
  ws.onopen = () => { connected = true; retry = 0; ws.send(JSON.stringify({ type: "hello", version: chrome.runtime.getManifest().version, browser: browserName() })); };
  ws.onclose = () => { connected = false; retry = Math.min(retry * 2 || 1000, 8000); setTimeout(legacyConnect, retry); };
  ws.onmessage = async e => {
    const msg = JSON.parse(e.data);
    if (msg.type === "ping") { ws.send('{"type":"pong"}'); return; }
    const reply = await handle(msg);
    if (reply && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(reply));
  };
}

// 어떤 브라우저인지 (크롬·웨일·엣지 모두 같은 확장을 쓴다)
function browserName() {
  const ua = navigator.userAgent;
  if (/Whale\//.test(ua)) return "웨일";
  if (/Edg\//.test(ua)) return "엣지";
  if (/OPR\//.test(ua)) return "오페라";
  if (/SamsungBrowser/.test(ua)) return "삼성 인터넷";
  return "크롬";
}
// 사용자가 이 브라우저 창을 누르면 퍼플루에 알려서, 명령이 지금 쓰는 브라우저로 오게 한다
chrome.windows.onFocusChanged.addListener(id => {
  if (id === chrome.windows.WINDOW_ID_NONE) return;
  if (ws && ws.readyState === WebSocket.OPEN) ws.send('{"type":"focus"}'); else toPurplu({ type: "focus" });
});

// ---------- 작업 중 표시: 퍼플루가 이 탭을 쓰는 동안 화면 가장자리에 보라색 빛 ----------
const WORK_CMDS = new Set(["open", "read", "click", "type", "keys", "scroll", "screenshot", "highlight", "back", "forward", "reload", "switch"]);
let workTimer = null, workTab = null;
async function working(on, cmd) {
  const s = await settings();
  if (s.work_indicator === false) return;
  clearTimeout(workTimer);
  if (!on) { workTimer = setTimeout(() => showWork(false), 1500); return; }   // 다음 명령이 곧 오면 계속 켜 둔다
  await showWork(true, cmd, s);
}
async function showWork(on, cmd, s) {
  let tab;
  try { tab = await activeTab(); } catch { return; }
  if (workTab && workTab !== tab.id) chrome.tabs.sendMessage(workTab, { type: "working", on: false }).catch(() => {});
  workTab = on ? tab.id : null;
  chrome.action.setBadgeText({ text: on ? "●" : "" });
  chrome.action.setBadgeBackgroundColor({ color: (s && (s.work_indicator_color || s.color)) || "#8B5CF6" });
  if (!/^https?:/.test(tab.url || "")) return;
  const msg = { type: "working", on, cmd, color: s && (s.work_indicator_color || s.color) };
  try { await chrome.tabs.sendMessage(tab.id, msg); }
  catch {   // 확장을 깔기 전에 열린 탭이면 표시 스크립트를 넣고 다시
    try { await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] }); await chrome.tabs.sendMessage(tab.id, msg); } catch {}
  }
}

// 서비스 워커가 잠들어도 30초마다 깨어나서 다시 연결
chrome.alarms.create("purplu-keepalive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => ensureOffscreen());
chrome.runtime.onStartup.addListener(ensureOffscreen);
chrome.runtime.onInstalled.addListener(ensureOffscreen);
chrome.runtime.onMessage.addListener((m, _s, send) => { if (m === "status" && !chrome.offscreen) send({ connected }); });
ensureOffscreen();

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
async function settings() { return (await chrome.storage.local.get("purplu_settings")).purplu_settings || {}; }

// ---------- 디버거 (진짜 마우스·키보드) ----------
const attached = new Set();
chrome.debugger.onDetach.addListener(src => attached.delete(src.tabId));
chrome.tabs.onRemoved.addListener(id => attached.delete(id));

async function cdp(tabId, method, params = {}) {
  if (!attached.has(tabId)) {
    try { await chrome.debugger.attach({ tabId }, "1.3"); } catch (e) {
      if (!String(e.message || e).includes("Already attached")) throw e;
    }
    attached.add(tabId);
  }
  return chrome.debugger.sendCommand({ tabId }, method, params);
}
async function useCdp() { return (await settings()).browser_real_input !== false; }

async function mouseClick(tabId, x, y, clicks = 1, button = "left") {
  await cdp(tabId, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  for (let i = 1; i <= clicks; i++) {
    await cdp(tabId, "Input.dispatchMouseEvent", { type: "mousePressed", x, y, button, clickCount: i });
    await cdp(tabId, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button, clickCount: i });
  }
}

const KEYS = {
  enter: ["Enter", "Enter", 13, "\r"], tab: ["Tab", "Tab", 9], escape: ["Escape", "Escape", 27], esc: ["Escape", "Escape", 27],
  backspace: ["Backspace", "Backspace", 8], delete: ["Delete", "Delete", 46], space: [" ", "Space", 32, " "],
  arrowup: ["ArrowUp", "ArrowUp", 38], arrowdown: ["ArrowDown", "ArrowDown", 40], arrowleft: ["ArrowLeft", "ArrowLeft", 37],
  arrowright: ["ArrowRight", "ArrowRight", 39], up: ["ArrowUp", "ArrowUp", 38], down: ["ArrowDown", "ArrowDown", 40],
  left: ["ArrowLeft", "ArrowLeft", 37], right: ["ArrowRight", "ArrowRight", 39], home: ["Home", "Home", 36], end: ["End", "End", 35],
  pageup: ["PageUp", "PageUp", 33], pagedown: ["PageDown", "PageDown", 34],
  f5: ["F5", "F5", 116],
};
const MODS = { alt: 1, ctrl: 2, control: 2, meta: 4, cmd: 4, shift: 8 };

// "ctrl+a", "Enter", "shift+tab" 같은 키 하나 누르기
async function pressKey(tabId, combo) {
  const parts = combo.toLowerCase().split("+").map(s => s.trim()).filter(Boolean);
  let mods = 0;
  for (const p of parts.slice(0, -1)) mods |= MODS[p] || 0;
  const k = parts[parts.length - 1];
  let key, code, vk, text;
  if (KEYS[k]) [key, code, vk, text] = KEYS[k];
  else if (k.length === 1) {
    key = k; vk = k.toUpperCase().charCodeAt(0);
    code = /[a-z]/.test(k) ? "Key" + k.toUpperCase() : /[0-9]/.test(k) ? "Digit" + k : "";
    text = mods & (2 | 4 | 1) ? undefined : k;
  } else throw new Error("모르는 키: " + combo);
  const base = { modifiers: mods, key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk };
  await cdp(tabId, "Input.dispatchKeyEvent", { type: text ? "keyDown" : "rawKeyDown", ...base, text, unmodifiedText: text });
  await cdp(tabId, "Input.dispatchKeyEvent", { type: "keyUp", ...base });
}

// ---------- 공통 ----------
async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) throw new Error("열린 탭이 없어요");
  return tab;
}

// func가 함수면 그대로, 글자면 page.js의 PURPLU_PAGE[이름]을 부른다
async function inPage(tabId, func, args = []) {
  try {
    if (typeof func === "string") {
      await chrome.scripting.executeScript({ target: { tabId }, files: ["page.js"], world: "ISOLATED" });
      const [res] = await chrome.scripting.executeScript({ target: { tabId }, world: "ISOLATED", args: [func, args],
        func: (name, a) => globalThis.PURPLU_PAGE[name](...a) });
      return res && res.result;
    }
    const [res] = await chrome.scripting.executeScript({ target: { tabId }, func, args, world: "ISOLATED" });
    return res && res.result;
  } catch (err) {
    throw new Error("이 페이지는 확장이 손댈 수 없어요 (크롬 설정·웹스토어 같은 특수 페이지): " + err.message);
  }
}

function waitLoaded(tabId, timeoutMs = 15000) {
  return new Promise((resolve) => {
    const t = setTimeout(() => { chrome.tabs.onUpdated.removeListener(fn); resolve(); }, timeoutMs);
    function fn(id, info) {
      if (id === tabId && info.status === "complete") { clearTimeout(t); chrome.tabs.onUpdated.removeListener(fn); resolve(); }
    }
    chrome.tabs.onUpdated.addListener(fn);
  });
}

// 클릭 뒤 페이지가 바뀌는 중이면 다 뜰 때까지 조금 기다린다
async function settle(tabId) {
  await sleep(350);
  const t = await chrome.tabs.get(tabId);
  if (t.status === "loading") await waitLoaded(tabId, 10000);
  else await sleep(250);
}

function normUrl(u) {
  u = (u || "").trim();
  if (!/^[a-z][a-z0-9+.-]*:/i.test(u)) u = (u.includes(".") && !u.includes(" ")) ? "https://" + u : "https://www.google.com/search?q=" + encodeURIComponent(u);
  return u;
}

async function toContent(tabId, msg) {
  try { return await chrome.tabs.sendMessage(tabId, msg); }
  catch { throw new Error("이 페이지에서는 하이라이트를 쓸 수 없어요 (새로고침 후 다시 해 보세요)"); }
}

async function run(cmd, a) {
  switch (cmd) {
    case "tabs": {
      const tabs = await chrome.tabs.query({});
      return tabs.map(t => ({ tab_id: t.id, title: t.title, url: t.url, active: t.active, window_id: t.windowId }));
    }
    case "open": {
      const url = normUrl(a.url);
      let tab;
      if (a.new_tab !== false) tab = await chrome.tabs.create({ url, active: true });
      else { tab = await activeTab(); await chrome.tabs.update(tab.id, { url }); }
      await chrome.windows.update(tab.windowId, { focused: true });
      await waitLoaded(tab.id);
      await working(true, "open");
      const t = await chrome.tabs.get(tab.id);
      return { tab_id: t.id, title: t.title, url: t.url };
    }
    case "switch": {
      const t = await chrome.tabs.update(a.tab_id, { active: true });
      await chrome.windows.update(t.windowId, { focused: true });
      return { tab_id: t.id, title: t.title, url: t.url };
    }
    case "close": { await chrome.tabs.remove(a.tab_id ?? (await activeTab()).id); return { closed: true }; }
    case "back": case "forward": case "reload": {
      const tab = await activeTab();
      if (cmd === "back") await chrome.tabs.goBack(tab.id);
      else if (cmd === "forward") await chrome.tabs.goForward(tab.id);
      else await chrome.tabs.reload(tab.id);
      await waitLoaded(tab.id, 8000);
      const t = await chrome.tabs.get(tab.id);
      return { title: t.title, url: t.url };
    }
    case "read": { const tab = await activeTab(); return { tab_id: tab.id, ...(await inPage(tab.id, "pageRead", [a.max_chars || 6000])) }; }

    case "screenshot": {   // 화면 사진 (사진 1픽셀 = 페이지 1 CSS 픽셀 → 사진 좌표로 바로 클릭 가능)
      const tab = await activeTab();
      const vp = await inPage(tab.id, () => ({ w: innerWidth, h: innerHeight, title: document.title, url: location.href }));
      let data;
      try {
        const r = await cdp(tab.id, "Page.captureScreenshot", { format: "jpeg", quality: 60,
          clip: { x: 0, y: 0, width: vp.w, height: vp.h, scale: 1 } });
        data = r.data;
      } catch {
        data = (await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 60 })).split(",")[1];
      }
      return { image_b64: data, width: vp.w, height: vp.h, title: vp.title, url: vp.url };
    }

    case "click": {
      const tab = await activeTab();
      let target;
      if (a.x != null && a.y != null) target = { ok: true, x: +a.x, y: +a.y, clicked: `(${a.x}, ${a.y})` };
      else target = await inPage(tab.id, "pageLocate", [a.element_id || "", a.text || ""]);
      if (!target || !target.ok) return target || { ok: false, error: "못 찾았어요" };
      if (await useCdp()) {
        try {
          await mouseClick(tab.id, target.x, target.y, a.double ? 2 : 1, a.right ? "right" : "left");
          await settle(tab.id);
          return { ok: true, clicked: target.clicked, how: "진짜 마우스" };
        } catch (e) { /* 디버거를 못 쓰면 아래 예전 방식 */ }
      }
      const r = await inPage(tab.id, "pageClick", [a.element_id || "", a.text || "", target.x, target.y]);
      await settle(tab.id);
      return r;
    }

    case "type": {
      const tab = await activeTab();
      const target = await inPage(tab.id, "pageLocateInput", [a.element_id || "", !!a.allow_password]);
      if (!target.ok) return target;
      if (await useCdp()) {
        try {
          await mouseClick(tab.id, target.x, target.y);          // 칸을 진짜로 눌러서 커서를 넣고
          if (a.clear !== false) { await pressKey(tab.id, "ctrl+a"); await pressKey(tab.id, "backspace"); }
          await cdp(tab.id, "Input.insertText", { text: a.text || "" });   // 한글도 그대로 들어간다
          if (a.submit) { await pressKey(tab.id, "enter"); await settle(tab.id); }
          return { ok: true, typed: (a.text || "").slice(0, 60), submitted: !!a.submit, how: "진짜 키보드" };
        } catch (e) { /* 예전 방식으로 */ }
      }
      const r = await inPage(tab.id, "pageType", [a.element_id || "", a.text || "", !!a.submit, !!a.allow_password]);
      if (a.submit) await settle(tab.id);
      return r;
    }

    case "keys": {   // 키보드: "Enter", "Tab", "ctrl+a", "shift+tab", "ArrowDown" ... 여러 개는 공백으로
      const tab = await activeTab();
      const list = String(a.keys || "").split(/\s+/).filter(Boolean);
      for (const k of list) { await pressKey(tab.id, k); await sleep(60); }
      await settle(tab.id);
      return { ok: true, pressed: list };
    }

    case "scroll": {
      const tab = await activeTab();
      if (["top", "bottom"].includes(a.direction) || !(await useCdp())) return await inPage(tab.id, "pageScroll", [a.direction || "down", a.amount || 3]);
      const vp = await inPage(tab.id, () => ({ w: innerWidth, h: innerHeight }));
      const dy = (a.direction === "up" ? -1 : 1) * vp.h * 0.8 * Math.max(1, Math.min(10, a.amount || 3)) / 3;
      const x = a.x ?? vp.w / 2, y = a.y ?? vp.h / 2;
      await cdp(tab.id, "Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaX: 0, deltaY: dy });
      await sleep(400);
      return await inPage(tab.id, () => ({ ok: true, scroll: Math.round(scrollY), page_height: document.documentElement.scrollHeight }));
    }

    // 하이라이트·노트 (새로고침해도 남는다)
    case "highlight": { const tab = await activeTab(); return await toContent(tab.id, { type: "hl_add_text", text: a.text || "", note: a.note || "", color: a.color }); }
    case "notes": {
      if (a.all) {
        const all = await chrome.storage.local.get(null);
        return { pages: Object.entries(all).filter(([k]) => k.startsWith("hl:")).map(([k, v]) => ({ url: k.slice(3),
          highlights: (v || []).map(h => ({ text: h.text.slice(0, 120), note: h.note || "" })) })).filter(p => p.highlights.length) };
      }
      const tab = await activeTab();
      return await toContent(tab.id, { type: "hl_list" });
    }
    case "bookmarks": {   // 즐겨찾기 찾기 (이름·주소 일부로)
      const q = (a.query || "").trim();
      let rows = q ? await chrome.bookmarks.search(q) : [];
      if (!rows.length) {   // 검색어가 없거나 못 찾으면 전체에서 비슷한 것
        const flat = []; (function walk(n) { (n || []).forEach(x => { if (x.url) flat.push(x); walk(x.children); }); })(await chrome.bookmarks.getTree());
        const words = q.toLowerCase().split(/\s+/).filter(Boolean);
        rows = words.length ? flat.filter(b => words.some(w => (b.title + " " + b.url).toLowerCase().includes(w))) : flat;
      }
      return { bookmarks: rows.filter(b => b.url).slice(0, 30).map(b => ({ title: b.title, url: b.url })) };
    }
    case "history": {   // 방문 기록 찾기
      const rows = await chrome.history.search({ text: a.query || "", maxResults: 25, startTime: Date.now() - 1000 * 60 * 60 * 24 * 90 });
      return { history: rows.map(h => ({ title: h.title, url: h.url, visits: h.visitCount })) };
    }
    case "clear_highlights": { const tab = await activeTab(); return await toContent(tab.id, { type: "hl_clear" }); }
    default: throw new Error("모르는 명령: " + cmd);
  }
}
