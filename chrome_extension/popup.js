const $ = s => document.getElementById(s);
const COLORS = { yellow: "#FDE68A", green: "#BBF7D0", pink: "#FBCFE8", purple: "#DDD6FE" };
const esc = s => String(s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

chrome.runtime.sendMessage("status", r => {
  const st = $("st");
  if (r && r.connected) { st.textContent = "● 퍼플루와 연결됨"; st.className = "on"; }
  else { st.textContent = "○ 연결 안 됨 — PC의 퍼플루를 켜 주세요"; st.className = "off"; }
});

(async () => {
  const s = await chrome.storage.local.get(["purplu_settings", "purplu_hl_enabled"]);
  const ps = s.purplu_settings || {};
  $("hlon").checked = s.purplu_hl_enabled !== false && ps.browser_highlights !== false;
  $("realin").checked = ps.browser_real_input !== false;
  $("hlon").onchange = e => chrome.storage.local.set({ purplu_hl_enabled: e.target.checked });
  $("realin").onchange = e => chrome.storage.local.set({ purplu_settings: { ...ps, browser_real_input: e.target.checked } });

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  let res = null;
  try { res = await chrome.tabs.sendMessage(tab.id, { type: "hl_list" }); } catch {}
  const rows = (res && res.highlights) || [];
  $("cnt").textContent = rows.length ? `(${rows.length})` : "";
  $("list").innerHTML = rows.map(h => `<div class="hl" style="background:${COLORS[h.color] || COLORS.yellow}">${esc(h.text.slice(0, 100))}${h.note ? `<i>📝 ${esc(h.note)}</i>` : ""}</div>`).join("")
    || `<div class="note">아직 하이라이트가 없어요.</div>`;
  $("clear").onclick = async () => { if (confirm("이 페이지의 하이라이트·노트를 모두 지울까요?")) { await chrome.tabs.sendMessage(tab.id, { type: "hl_clear" }); location.reload(); } };
})();
