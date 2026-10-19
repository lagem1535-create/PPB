// 퍼플루 하이라이트·노트: 글을 드래그하면 형광펜 도구가 뜨고, 칠한 곳과 노트는 이 사이트에 저장돼
// 스크롤해도, 새로고침해도, 다음에 와도 그대로 남는다. (퍼플루 설정 또는 확장 팝업에서 켜고 끈다)
(() => {
  if (window.__purpluHL) return;
  window.__purpluHL = true;

  const COLORS = { yellow: "#FDE68A", green: "#BBF7D0", pink: "#FBCFE8", purple: "#DDD6FE" };
  const pageKey = () => "hl:" + location.origin + location.pathname + location.search;
  let items = [], enabled = true, applying = false;

  // ---------- 저장 ----------
  async function load() { items = (await chrome.storage.local.get(pageKey()))[pageKey()] || []; }
  async function save() { await chrome.storage.local.set({ [pageKey()]: items }); }
  async function isEnabled() {
    const s = await chrome.storage.local.get(["purplu_settings", "purplu_hl_enabled"]);
    if (s.purplu_hl_enabled === false) return false;
    return (s.purplu_settings || {}).browser_highlights !== false;
  }

  // ---------- 글자 위치 (본문 글을 이어 붙인 문자열 기준) ----------
  function textNodes() {
    const out = [];
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: n => {
        const p = n.parentElement;
        if (!p || !n.nodeValue) return NodeFilter.FILTER_REJECT;
        if (p.closest("script,style,noscript,textarea,input,select,#purplu-hl-ui")) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    let pos = 0;
    while (w.nextNode()) { const n = w.currentNode; out.push({ n, start: pos }); pos += n.nodeValue.length; }
    return { nodes: out, text: out.map(o => o.n.nodeValue).join("") };
  }

  // 저장한 글(앞뒤 문맥 포함)을 지금 페이지에서 다시 찾는다
  function locate(item, idx) {
    const { text } = idx;
    let best = -1, bestScore = -1, from = 0;
    while (true) {
      const i = text.indexOf(item.text, from);
      if (i < 0) break;
      let score = 0;
      if (item.prefix && text.slice(Math.max(0, i - item.prefix.length), i) === item.prefix) score += 2;
      if (item.suffix && text.slice(i + item.text.length, i + item.text.length + item.suffix.length) === item.suffix) score += 2;
      if (score > bestScore) { best = i; bestScore = score; }
      from = i + 1;
    }
    return best;
  }

  function wrap(item, start, idx) {
    const end = start + item.text.length;
    for (const { n, start: s } of idx.nodes) {
      const e = s + n.nodeValue.length;
      if (e <= start || s >= end) continue;
      let node = n;
      const a = Math.max(0, start - s), b = Math.min(n.nodeValue.length, end - s);
      if (b < node.nodeValue.length) node.splitText(b);
      if (a > 0) node = node.splitText(a);
      const mark = document.createElement("mark");
      mark.className = "purplu-hl";
      mark.dataset.id = item.id;
      mark.style.background = COLORS[item.color] || COLORS.yellow;
      if (item.note) { mark.dataset.note = "1"; mark.title = "📝 " + item.note; }
      node.parentNode.insertBefore(mark, node);
      mark.appendChild(node);
    }
  }

  function applyAll() {
    if (!enabled || !document.body) return;
    applying = true;
    try {
      for (const it of items) {
        if (document.querySelector(`mark.purplu-hl[data-id="${it.id}"]`)) continue;
        const idx = textNodes();
        const at = locate(it, idx);
        if (at >= 0) wrap(it, at, idx);
      }
    } finally { setTimeout(() => { applying = false; }, 0); }
  }

  function unwrap(id) {
    document.querySelectorAll(`mark.purplu-hl${id ? `[data-id="${id}"]` : ""}`).forEach(m => {
      const p = m.parentNode; while (m.firstChild) p.insertBefore(m.firstChild, m); p.removeChild(m); p.normalize();
    });
  }

  function refreshMark(it) {
    document.querySelectorAll(`mark.purplu-hl[data-id="${it.id}"]`).forEach(m => {
      m.style.background = COLORS[it.color] || COLORS.yellow;
      if (it.note) { m.dataset.note = "1"; m.title = "📝 " + it.note; } else { delete m.dataset.note; m.removeAttribute("title"); }
    });
  }

  // 선택한 곳 → 저장할 항목
  function itemFromRange(range, color, note = "") {
    const idx = textNodes();
    const text = range.toString();
    if (!text.trim()) return null;
    let start = -1;
    const sc = range.startContainer;
    const hit = idx.nodes.find(o => o.n === sc);
    if (hit) start = hit.start + range.startOffset;
    if (start < 0 || idx.text.slice(start, start + text.length) !== text) start = idx.text.indexOf(text);
    if (start < 0) return null;
    return { id: Math.random().toString(36).slice(2, 10), text, color: color || "yellow", note,
             prefix: idx.text.slice(Math.max(0, start - 32), start), suffix: idx.text.slice(start + text.length, start + text.length + 32),
             created: Date.now(), _start: start, _idx: idx };
  }

  async function addItem(it) {
    const { _start, _idx } = it; delete it._start; delete it._idx;
    items.push(it); await save();
    applying = true; wrap(it, _start, _idx); setTimeout(() => { applying = false; }, 0);
    return it;
  }

  // ---------- 화면 UI (페이지 글꼴·색에 안 섞이게 그림자 DOM) ----------
  const host = document.createElement("div");
  host.id = "purplu-hl-ui";
  host.style.cssText = "position:absolute;top:0;left:0;z-index:2147483647;";
  const ui = host.attachShadow({ mode: "open" });
  ui.innerHTML = `<style>
    .bar,.pop{position:absolute;background:#1E1235;color:#F5F3FF;border-radius:12px;box-shadow:0 8px 24px #0006;font:13px "Malgun Gothic",sans-serif;}
    .bar{display:none;padding:6px;gap:6px;align-items:center}
    .bar button,.pop button{border:0;border-radius:8px;cursor:pointer;font:inherit}
    .dot{width:22px;height:22px;border-radius:50%!important}
    .txt{background:#3B2A63;color:#fff;padding:5px 9px}
    .pop{display:none;width:260px;padding:10px}
    .pop textarea{width:100%;box-sizing:border-box;height:80px;border-radius:8px;border:1px solid #4C3A75;background:#120B22;color:#fff;padding:8px;font:inherit;resize:vertical}
    .row{display:flex;gap:6px;margin-top:8px;align-items:center}
    .save{background:#8B5CF6;color:#fff;padding:6px 12px} .del{background:#7F1D1D;color:#fff;padding:6px 10px;margin-left:auto}
    .q{color:#C4B5FD;font-size:12px;margin-bottom:6px;max-height:40px;overflow:hidden}
  </style>
  <div class="bar">${Object.entries(COLORS).map(([k, c]) => `<button class="dot" data-c="${k}" title="하이라이트" style="background:${c}"></button>`).join("")}
    <button class="txt" data-note>📝 노트</button></div>
  <div class="pop"><div class="q"></div><textarea placeholder="노트를 남겨요 (이 사이트에 저장)"></textarea>
    <div class="row">${Object.entries(COLORS).map(([k, c]) => `<button class="dot" data-pc="${k}" style="background:${c}"></button>`).join("")}
    <button class="save">저장</button><button class="del">삭제</button></div></div>`;
  const bar = ui.querySelector(".bar"), pop = ui.querySelector(".pop");
  let pendingRange = null, popItem = null;

  function place(el, rect) {
    el.style.left = Math.max(8, Math.min(scrollX + rect.left, scrollX + innerWidth - 280)) + "px";
    el.style.top = (scrollY + rect.bottom + 8) + "px";
  }
  function hideAll() { bar.style.display = "none"; pop.style.display = "none"; pendingRange = null; popItem = null; }

  document.addEventListener("mouseup", e => {
    if (!enabled || e.composedPath().includes(host)) return;
    setTimeout(() => {
      const sel = getSelection();
      if (!sel || sel.isCollapsed || !sel.toString().trim()) { if (!pop.matches(":hover")) bar.style.display = "none"; return; }
      const r = sel.getRangeAt(0);
      if (r.commonAncestorContainer.parentElement?.closest("input,textarea,[contenteditable]")) return;
      pendingRange = r.cloneRange();
      place(bar, r.getBoundingClientRect()); bar.style.display = "flex"; pop.style.display = "none";
    }, 10);
  }, true);
  document.addEventListener("mousedown", e => { if (!e.composedPath().includes(host)) { bar.style.display = "none"; if (!e.target.closest?.("mark.purplu-hl")) pop.style.display = "none"; } }, true);

  bar.addEventListener("click", async e => {
    const b = e.target.closest("button"); if (!b || !pendingRange) return;
    const it = itemFromRange(pendingRange, b.dataset.c || "yellow");
    getSelection().removeAllRanges(); bar.style.display = "none";
    if (!it) return;
    await addItem(it);
    if (b.hasAttribute("data-note")) openPop(it, document.querySelector(`mark.purplu-hl[data-id="${it.id}"]`));
  });

  function openPop(it, mark) {
    if (!mark) return;
    popItem = it;
    pop.querySelector(".q").textContent = "“" + it.text.slice(0, 90) + "”";
    pop.querySelector("textarea").value = it.note || "";
    place(pop, mark.getBoundingClientRect()); pop.style.display = "block"; bar.style.display = "none";
    pop.querySelector("textarea").focus();
  }
  document.addEventListener("click", e => {
    const m = e.target.closest?.("mark.purplu-hl"); if (!m || !enabled) return;
    const it = items.find(x => x.id === m.dataset.id); if (it) openPop(it, m);
  }, true);
  pop.querySelector(".save").onclick = async () => { if (!popItem) return; popItem.note = pop.querySelector("textarea").value.trim(); await save(); refreshMark(popItem); hideAll(); };
  pop.querySelector(".del").onclick = async () => { if (!popItem) return; items = items.filter(x => x.id !== popItem.id); await save(); unwrap(popItem.id); hideAll(); };
  pop.querySelectorAll("[data-pc]").forEach(b => b.onclick = async () => { if (!popItem) return; popItem.color = b.dataset.pc; await save(); refreshMark(popItem); });

  // ---------- 작업 중 표시: 퍼플루가 이 탭을 쓰는 동안 가장자리에 빛 + 위쪽 알림 ----------
  const CMD_NAMES = { open: "여는 중", read: "읽는 중", click: "누르는 중", type: "입력하는 중", keys: "키보드 누르는 중",
    scroll: "스크롤하는 중", screenshot: "화면 보는 중", highlight: "표시하는 중", back: "뒤로", forward: "앞으로", reload: "새로고침", switch: "탭 바꾸는 중" };
  const work = document.createElement("div");
  work.id = "purplu-work";
  work.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483646;display:none;";
  const ws_ = work.attachShadow({ mode: "open" });
  ws_.innerHTML = `<style>
    .glow{position:fixed;inset:0;border:3px solid var(--c);box-shadow:inset 0 0 28px 6px color-mix(in srgb,var(--c) 55%,transparent);
      border-radius:6px;animation:pulse 1.6s ease-in-out infinite}
    @keyframes pulse{0%,100%{opacity:.65}50%{opacity:1}}
    .pill{position:fixed;top:10px;left:50%;transform:translateX(-50%);background:var(--c);color:#fff;padding:6px 14px;border-radius:999px;
      font:600 13px "Malgun Gothic",sans-serif;box-shadow:0 6px 20px #0005;white-space:nowrap}
  </style><div class="glow"></div><div class="pill"></div>`;
  function setWorking(on, cmd, color) {
    if (!work.isConnected) document.documentElement.appendChild(work);
    work.style.setProperty("--c", color || "#8B5CF6");
    ws_.host.style.setProperty("--c", color || "#8B5CF6");
    ws_.querySelector(".pill").textContent = "💜 퍼플루가 사용 중" + (CMD_NAMES[cmd] ? " · " + CMD_NAMES[cmd] : "");
    work.style.display = on ? "block" : "none";
  }

  // ---------- 퍼플루·팝업이 보내는 명령 ----------
  chrome.runtime.onMessage.addListener((m, _s, send) => {
    (async () => {
      if (m.type === "working") { setWorking(m.on, m.cmd, m.color); return { ok: true }; }
      if (m.type === "hl_list") return { ok: true, url: location.href, title: document.title,
        highlights: items.map(i => ({ text: i.text.slice(0, 200), note: i.note || "", color: i.color })) };
      if (m.type === "hl_clear") { unwrap(); items = []; await save(); return { ok: true, cleared: true }; }
      if (m.type === "hl_add_text") {   // 퍼플루가 "이 문장 표시해 줘"
        if (!enabled) return { ok: false, error: "하이라이트가 꺼져 있어요 (퍼플루 설정 또는 확장 팝업에서 켜기)" };
        const idx = textNodes();
        let at = idx.text.indexOf(m.text);
        if (at < 0) at = idx.text.toLowerCase().indexOf(String(m.text).toLowerCase());
        if (at < 0) return { ok: false, error: "페이지에서 그 글자를 못 찾았어요. 페이지 글을 그대로 넣어 주세요." };
        const text = idx.text.slice(at, at + m.text.length);
        const it = { id: Math.random().toString(36).slice(2, 10), text, color: m.color || "purple", note: m.note || "",
                     prefix: idx.text.slice(Math.max(0, at - 32), at), suffix: idx.text.slice(at + text.length, at + text.length + 32),
                     created: Date.now(), _start: at, _idx: idx };
        await addItem(it);
        document.querySelector(`mark.purplu-hl[data-id="${it.id}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
        return { ok: true, highlighted: text.slice(0, 80), note: it.note, saved: "이 사이트에 저장됨 (새로고침해도 남아요)" };
      }
      if (m.type === "hl_enabled") { await start(); return { ok: true }; }
    })().then(send);
    return true;
  });

  // ---------- 시작 ----------
  async function start() {
    enabled = await isEnabled();
    if (!enabled) { unwrap(); hideAll(); return; }
    await load();
    applyAll();
  }
  const style = document.createElement("style");
  style.textContent = `mark.purplu-hl{color:inherit;border-radius:3px;padding:0 1px;cursor:pointer;box-shadow:0 0 0 1px #0001}
    mark.purplu-hl[data-note]:last-of-type::after{content:"📝";font-size:.8em;margin-left:2px}`;
  (document.head || document.documentElement).appendChild(style);
  document.documentElement.appendChild(host);
  chrome.storage.onChanged.addListener(ch => { if (ch.purplu_settings || ch.purplu_hl_enabled) start(); });
  start();

  // 페이지가 나중에 글을 채우거나(검색 결과·SNS) 주소만 바뀌는 앱이면 다시 칠한다
  let lastKey = pageKey(), timer = null;
  new MutationObserver(() => {
    if (applying || !enabled) return;
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (pageKey() !== lastKey) { lastKey = pageKey(); unwrap(); await load(); }
      if (items.length) applyAll();
    }, 700);
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
})();
