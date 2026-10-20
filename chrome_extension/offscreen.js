// 숨은 페이지: PC의 퍼플루(ws://127.0.0.1:8765/ext)와 연결을 늘 붙잡고 있는다.
// 퍼플루 명령은 백그라운드로 넘겨 실행하고, 결과를 다시 퍼플루로 보낸다.
// 백그라운드(서비스 워커)는 브라우저가 재우지만, 이 페이지는 안 꺼져서 연결이 끊기지 않는다.

const URL_ = "ws://127.0.0.1:8765/ext";
let ws = null, retry = 0;

function browserName() {
  const ua = navigator.userAgent;
  if (/Whale\//.test(ua)) return "웨일";
  if (/Edg\//.test(ua)) return "엣지";
  if (/OPR\//.test(ua)) return "오페라";
  return "크롬";
}

function setConn(on) { chrome.runtime.sendMessage({ type: "conn", on }).catch(() => {}); }

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  try { ws = new WebSocket(URL_); } catch { setTimeout(connect, 2000); return; }
  ws.onopen = () => {
    retry = 0; setConn(true);
    ws.send(JSON.stringify({ type: "hello", version: chrome.runtime.getManifest().version, browser: browserName() }));
  };
  ws.onclose = () => { setConn(false); retry = Math.min(retry * 2 || 1000, 5000); setTimeout(connect, retry); };
  ws.onerror = () => {};
  ws.onmessage = async e => {
    const msg = JSON.parse(e.data);
    if (msg.type === "ping") { ws.send('{"type":"pong"}'); return; }
    let reply = null;
    try { reply = await chrome.runtime.sendMessage({ type: "cmd", msg }); }   // 백그라운드를 깨워서 실행
    catch (err) { if (msg.id) reply = { id: msg.id, ok: false, error: "확장 백그라운드가 응답하지 않아요: " + err.message }; }
    if (reply && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(reply));
  };
}

// 백그라운드가 퍼플루에 보낼 것 (창 포커스 등)
chrome.runtime.onMessage.addListener((m, _s, send) => {
  if (m && m.type === "to_purplu" && ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(m.data));
  if (m === "status") send({ connected: !!(ws && ws.readyState === WebSocket.OPEN) });
});

// 백그라운드가 너무 오래 잠들지 않게 20초마다 살짝 깨운다
setInterval(() => chrome.runtime.sendMessage({ type: "keepalive" }).catch(() => {}), 20000);
connect();
