chrome.runtime.sendMessage("status", (r) => {
  const st = document.getElementById("st");
  if (r && r.connected) { st.textContent = "● 퍼플루와 연결됨"; st.className = "on"; }
  else { st.textContent = "○ 연결 안 됨 — PC의 퍼플루를 켜 주세요"; st.className = "off"; }
});
