// 페이지 안에서 쓰는 함수들. background.js가 먼저 이 파일을 넣고 PURPLU_PAGE.이름(...)으로 부른다.
// (executeScript로 함수 하나만 보내면 그 안에서 부르는 다른 함수가 없어서 실패했었다)

function pageRead(maxChars) {
  const sel = "a[href], button, input:not([type=hidden]), textarea, select, [role=button], [role=link], [role=tab], [role=menuitem], [role=option], " +
    "[role=checkbox], [role=radio], [role=switch], [role=combobox], [role=searchbox], [role=textbox], [contenteditable=true], [contenteditable=''], " +
    "[onclick], summary, label[for], [tabindex]:not([tabindex='-1'])";
  const visible = (el) => { const r = el.getBoundingClientRect(); if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el); return s.visibility !== "hidden" && s.display !== "none" && +s.opacity > 0.05; };
  const all = [];
  (function walk(root) {   // 그림자 DOM(웹 컴포넌트) 안까지
    root.querySelectorAll(sel).forEach(el => all.push(el));
    root.querySelectorAll("*").forEach(el => { if (el.shadowRoot) walk(el.shadowRoot); });
  })(document);
  document.querySelectorAll("[data-purplu-id]").forEach(el => el.removeAttribute("data-purplu-id"));
  const labelOf = (el) => {
    let t = el.getAttribute("aria-label") || el.getAttribute("title") || "";
    if (!t && el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) t = l.innerText; }
    if (!t && el.getAttribute("aria-labelledby")) t = el.getAttribute("aria-labelledby").split(" ").map(i => document.getElementById(i)?.innerText || "").join(" ");
    if (!t) t = el.innerText || el.value || el.placeholder || el.alt || el.name || "";
    if (!t) { const img = el.querySelector("img[alt], svg[aria-label]"); if (img) t = img.getAttribute("alt") || img.getAttribute("aria-label"); }
    return t.trim().replace(/\s+/g, " ");
  };
  const seen = new Set(), elements = [];
  let n = 0;
  // 화면에 보이는 것부터
  const items = all.filter(el => !seen.has(el) && seen.add(el) && visible(el)).map(el => ({ el, r: el.getBoundingClientRect() }))
    .sort((p, q) => ((p.r.bottom < 0 || p.r.top > innerHeight) - (q.r.bottom < 0 || q.r.top > innerHeight)) || p.r.top - q.r.top || p.r.left - q.r.left);
  for (const { el, r } of items) {
    const id = "E" + (++n);
    el.setAttribute("data-purplu-id", id);
    const tag = el.tagName.toLowerCase();
    const e = { id, tag, role: el.getAttribute("role") || el.type || "", text: labelOf(el).slice(0, 80),
      in_view: r.top < innerHeight && r.bottom > 0, x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
    if (el.href) e.href = String(el.href).slice(0, 120);
    if (["input", "textarea", "select"].includes(tag) && el.type !== "password") e.value = String(el.value || "").slice(0, 60);
    if (el.disabled) e.disabled = true;
    if (el.checked) e.checked = true;
    elements.push(e);
    if (elements.length >= 250) break;
  }
  const text = (document.body ? document.body.innerText : "").replace(/\n{3,}/g, "\n\n");
  return { title: document.title, url: location.href, text: text.slice(0, maxChars), text_truncated: text.length > maxChars,
           scroll: Math.round(scrollY), page_height: document.documentElement.scrollHeight, viewport: [innerWidth, innerHeight],
           focused: document.activeElement && document.activeElement !== document.body ? (document.activeElement.getAttribute("data-purplu-id") || document.activeElement.tagName) : null,
           elements };
}

function pageFindEl(id, text) {
  const deepQuery = (s) => { const out = []; (function walk(root) { root.querySelectorAll(s).forEach(e => out.push(e));
    root.querySelectorAll("*").forEach(e => { if (e.shadowRoot) walk(e.shadowRoot); }); })(document); return out; };
  if (id) { const el = deepQuery(`[data-purplu-id="${id}"]`)[0]; if (el) return el; }
  if (text) {
    const t = text.trim().toLowerCase();
    const cands = deepQuery("a, button, input, textarea, select, [role=button], [role=link], [role=tab], [role=menuitem], [role=option], summary, label, [onclick], [tabindex]");
    const score = (el) => { const s = (el.getAttribute("aria-label") || el.innerText || el.value || el.placeholder || el.title || "").trim().toLowerCase();
      if (!s) return 0; const r = el.getBoundingClientRect(); if (r.width < 2) return 0;
      return s === t ? 4 : s.startsWith(t) ? 3 : s.includes(t) ? 2 : t.includes(s) && s.length > 2 ? 1 : 0; };
    let best = null, bs = 0;
    for (const el of cands) { const s = score(el); if (s > bs) { best = el; bs = s; } }
    if (best) return best;
  }
  return null;
}

function pageFlash(el) {
  const old = el.style.outline, oo = el.style.outlineOffset;
  el.style.outline = "3px solid #8B5CF6"; el.style.outlineOffset = "2px";
  setTimeout(() => { el.style.outline = old; el.style.outlineOffset = oo; }, 1200);
}

// 누를 곳의 화면 좌표 (가려져 있으면 실제로 맨 위에 있는 걸 알려 준다)
function pageLocate(id, text) {
  const el = pageFindEl(id, text);
  if (!el) return { ok: false, error: "그 요소를 못 찾았어요. browser_read로 번호를 다시 받거나 screenshot으로 보고 x,y로 누르세요." };
  el.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
  const r = el.getBoundingClientRect();
  const x = Math.round(r.left + Math.min(r.width / 2, r.width - 2)), y = Math.round(r.top + r.height / 2);
  pageFlash(el);
  return { ok: true, x, y, clicked: (el.getAttribute("aria-label") || el.innerText || el.value || el.tagName).trim().slice(0, 60) };
}

function pageLocateInput(id, allowPassword) {
  let el = id ? pageFindEl(id, "") : null;
  if (!el) {
    const a = document.activeElement;
    if (a && a !== document.body && (a.isContentEditable || ["INPUT", "TEXTAREA"].includes(a.tagName))) el = a;
  }
  if (!el) el = document.querySelector("input[type=search], input[type=text]:not([disabled]), textarea, [contenteditable=true]");
  if (!el) return { ok: false, error: "입력할 칸을 못 찾았어요. browser_read로 칸의 번호를 확인하세요." };
  if ((el.type || "").toLowerCase() === "password" && !allowPassword)
    return { ok: false, error: "비밀번호 칸에는 입력하지 않아요 (퍼플루 설정의 보안 수준이 '강하게')." };
  el.scrollIntoView({ block: "center", behavior: "instant" });
  const r = el.getBoundingClientRect();
  pageFlash(el);
  return { ok: true, x: Math.round(r.left + Math.min(20, r.width / 2)), y: Math.round(r.top + r.height / 2) };
}

// 디버거를 못 쓸 때의 예전 방식
function pageClick(id, text, x, y) {
  const el = pageFindEl(id, text) || document.elementFromPoint(x, y);
  if (!el) return { ok: false, error: "그 요소를 못 찾았어요." };
  const opts = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y };
  ["pointerdown", "mousedown", "pointerup", "mouseup"].forEach(t => el.dispatchEvent(new (t.startsWith("pointer") ? PointerEvent : MouseEvent)(t, opts)));
  el.click();
  return { ok: true, clicked: (el.innerText || el.value || el.getAttribute("aria-label") || el.tagName).trim().slice(0, 60), how: "가짜 클릭" };
}

function pageType(id, text, submit, allowPassword) {
  const el = pageFindEl(id, "") || (document.activeElement !== document.body ? document.activeElement : null);
  if (!el) return { ok: false, error: "입력할 칸을 못 찾았어요." };
  if ((el.type || "").toLowerCase() === "password" && !allowPassword) return { ok: false, error: "비밀번호 칸에는 입력하지 않아요." };
  el.focus();
  if (el.isContentEditable) {
    document.execCommand("selectAll", false); document.execCommand("insertText", false, text);
  } else {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, text);   // React 같은 화면에서도 값이 들어가게
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  if (submit) {
    const o = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true };
    ["keydown", "keypress", "keyup"].forEach(t => el.dispatchEvent(new KeyboardEvent(t, o)));
    if (el.form) { try { el.form.requestSubmit(); } catch { el.form.submit(); } }
  }
  return { ok: true, typed: text.slice(0, 60), submitted: !!submit, how: "가짜 입력" };
}

function pageScroll(direction, amount) {
  const step = innerHeight * 0.8 * Math.max(1, Math.min(10, amount)) / 3;
  if (direction === "top") scrollTo(0, 0);
  else if (direction === "bottom") scrollTo(0, document.documentElement.scrollHeight);
  else scrollBy(0, direction === "up" ? -step : step);
  return { ok: true, scroll: Math.round(scrollY), page_height: document.documentElement.scrollHeight };
}

globalThis.PURPLU_PAGE = { pageRead, pageFindEl, pageLocate, pageLocateInput, pageClick, pageType, pageScroll };
