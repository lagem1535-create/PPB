// 퍼플루 브라우저 손: 이 PC에서 돌아가는 퍼플루(ws://127.0.0.1:8765/ext)와 연결해서
// 퍼플루가 보내는 명령(탭 열기·페이지 읽기·클릭·입력·스크롤)을 실행하고 결과를 돌려준다.

const PURPLU_URL = "ws://127.0.0.1:8765/ext";
let ws = null;
let connected = false;

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  try { ws = new WebSocket(PURPLU_URL); } catch { return; }
  ws.onopen = () => {
    connected = true;
    ws.send(JSON.stringify({ type: "hello", version: chrome.runtime.getManifest().version }));
    chrome.action.setBadgeText({ text: "" });
  };
  ws.onclose = () => { connected = false; chrome.action.setBadgeText({ text: "off" }); };
  ws.onerror = () => {};
  ws.onmessage = async (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "ping") { ws.send(JSON.stringify({ type: "pong" })); return; }
    if (!msg.id) return;
    let reply;
    try { reply = { id: msg.id, ok: true, result: await run(msg.cmd, msg.args || {}) }; }
    catch (err) { reply = { id: msg.id, ok: false, error: String(err && err.message || err) }; }
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(reply));
  };
}

// 서비스 워커가 잠들어도 30초마다 깨어나서 다시 연결
chrome.alarms.create("purplu-keepalive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => connect());
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.runtime.onMessage.addListener((m, _s, send) => { if (m === "status") send({ connected }); });
connect();

// ---------- 명령 ----------

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) throw new Error("열린 탭이 없어요");
  return tab;
}

async function inPage(tabId, func, args = []) {
  try {
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

function normUrl(u) {
  u = (u || "").trim();
  if (!/^[a-z][a-z0-9+.-]*:/i.test(u)) u = (u.includes(".") && !u.includes(" ")) ? "https://" + u : "https://www.google.com/search?q=" + encodeURIComponent(u);
  return u;
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
    case "read": { const tab = await activeTab(); return { tab_id: tab.id, ...(await inPage(tab.id, pageRead, [a.max_chars || 6000])) }; }
    case "click": { const tab = await activeTab(); const r = await inPage(tab.id, pageClick, [a.element_id || "", a.text || ""]); await sleep(700); return r; }
    case "type": { const tab = await activeTab(); const r = await inPage(tab.id, pageType, [a.element_id || "", a.text || "", !!a.submit, !!a.allow_password]); if (a.submit) await sleep(900); return r; }
    case "scroll": { const tab = await activeTab(); return await inPage(tab.id, pageScroll, [a.direction || "down", a.amount || 3]); }
    case "highlight": { const tab = await activeTab(); return await inPage(tab.id, pageHighlight, [a.text || ""]); }
    default: throw new Error("모르는 명령: " + cmd);
  }
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// ---------- 페이지 안에서 실행되는 함수들 (executeScript로 들어감) ----------

function pageRead(maxChars) {
  const sel = "a[href], button, input, textarea, select, [role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], [contenteditable=true], [onclick], summary";
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== "hidden" && s.display !== "none"; };
  let n = 0; const elements = [];
  document.querySelectorAll("[data-purplu-id]").forEach(el => el.removeAttribute("data-purplu-id"));
  for (const el of document.querySelectorAll(sel)) {
    if (!visible(el)) continue;
    const id = "E" + (++n);
    el.setAttribute("data-purplu-id", id);
    const label = (el.getAttribute("aria-label") || el.innerText || el.value || el.placeholder || el.title || el.alt || el.name || "").trim().replace(/\s+/g, " ");
    const r = el.getBoundingClientRect();
    elements.push({ id, tag: el.tagName.toLowerCase(), type: el.type || el.getAttribute("role") || "", text: label.slice(0, 70),
                    href: el.href ? String(el.href).slice(0, 120) : undefined, in_view: r.top < innerHeight && r.bottom > 0 });
    if (elements.length >= 200) break;
  }
  const text = (document.body ? document.body.innerText : "").replace(/\n{3,}/g, "\n\n");
  return { title: document.title, url: location.href, text: text.slice(0, maxChars), text_truncated: text.length > maxChars,
           scroll: Math.round(scrollY), page_height: document.documentElement.scrollHeight, elements };
}

function pageFind(id, text) {
  if (id) { const el = document.querySelector(`[data-purplu-id="${id}"]`); if (el) return el; }
  if (text) {
    const t = text.trim().toLowerCase();
    const cands = [...document.querySelectorAll("a, button, input, textarea, select, [role=button], [role=link], [role=tab], [role=menuitem], summary, label, [onclick]")];
    const score = (el) => { const s = (el.getAttribute("aria-label") || el.innerText || el.value || el.placeholder || "").trim().toLowerCase();
      return s === t ? 3 : s.startsWith(t) ? 2 : s.includes(t) ? 1 : 0; };
    let best = null, bs = 0;
    for (const el of cands) { const s = score(el); if (s > bs) { best = el; bs = s; } }
    if (best) return best;
  }
  return null;
}

function pageFlash(el) {
  const old = el.style.outline; el.style.outline = "3px solid #8B5CF6"; el.style.outlineOffset = "2px";
  setTimeout(() => { el.style.outline = old; }, 1500);
}

function pageClick(id, text) {
  const el = pageFind(id, text);
  if (!el) return { ok: false, error: "그 요소를 못 찾았어요. 다시 read로 번호를 받으세요." };
  el.scrollIntoView({ block: "center", behavior: "instant" });
  pageFlash(el);
  el.click();
  return { ok: true, clicked: (el.innerText || el.value || el.getAttribute("aria-label") || el.tagName).trim().slice(0, 60) };
}

function pageType(id, text, submit, allowPassword) {
  const el = pageFind(id, "") || (document.activeElement !== document.body ? document.activeElement : null);
  if (!el) return { ok: false, error: "입력할 칸을 못 찾았어요." };
  if ((el.type || "").toLowerCase() === "password" && !allowPassword)
    return { ok: false, error: "비밀번호 칸에는 입력하지 않아요 (퍼플루 설정의 보안 수준이 '강하게')." };
  el.scrollIntoView({ block: "center", behavior: "instant" });
  el.focus(); pageFlash(el);
  if (el.isContentEditable) {
    document.execCommand("selectAll", false); document.execCommand("insertText", false, text);
  } else {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;   // React 같은 화면에서도 값이 들어가게
    setter.call(el, text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  if (submit) {
    const opts = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true };
    el.dispatchEvent(new KeyboardEvent("keydown", opts));
    el.dispatchEvent(new KeyboardEvent("keypress", opts));
    el.dispatchEvent(new KeyboardEvent("keyup", opts));
    if (el.form) { try { el.form.requestSubmit(); } catch { el.form.submit(); } }
  }
  return { ok: true, typed: text.slice(0, 60), submitted: !!submit };
}

function pageScroll(direction, amount) {
  const step = innerHeight * 0.8 * Math.max(1, Math.min(10, amount)) / 3;
  if (direction === "top") scrollTo(0, 0);
  else if (direction === "bottom") scrollTo(0, document.documentElement.scrollHeight);
  else scrollBy(0, direction === "up" ? -step : step);
  return { ok: true, scroll: Math.round(scrollY), page_height: document.documentElement.scrollHeight };
}

function pageHighlight(text) {
  const t = text.trim().toLowerCase();
  if (!t) return { ok: false, error: "표시할 글자가 없어요." };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const hits = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.nodeValue.toLowerCase().includes(t) && node.parentElement && node.parentElement.offsetParent !== null) hits.push(node.parentElement);
    if (hits.length >= 5) break;
  }
  if (!hits.length) return { ok: false, error: "페이지에서 그 글자를 못 찾았어요." };
  hits[0].scrollIntoView({ block: "center", behavior: "smooth" });
  for (const el of hits) {
    const old = el.style.cssText;
    el.style.background = "rgba(139,92,246,.25)"; el.style.outline = "3px solid #8B5CF6"; el.style.borderRadius = "6px";
    setTimeout(() => { el.style.cssText = old; }, 8000);
  }
  return { ok: true, highlighted: hits.length };
}
