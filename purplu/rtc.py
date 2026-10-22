"""GitHub Pages 화면 ↔ PC 를 WebRTC 로 잇기 (인증서 없이, 경고 없이, 마이크까지).

- Pages 는 https(깃허브 인증서)라 경고가 없고 마이크도 된다. 그런데 https 페이지는 PC의 http/자체 인증서에 못 붙는다.
- 그래서 WebRTC 데이터 채널을 쓴다: WebRTC 는 자기 암호화(DTLS)를 써서 인증서가 필요 없다.
- 첫 인사(offer/answer)만 Firebase(/purplu/rtc/{sid})로 주고받는다. 짝 열쇠(data/rtc_key.txt)로 서명해서
  열쇠를 모르는 기기는 붙을 수 없다. 열쇠는 설정 > 갤럭시 탭의 QR 링크(#k=…)로만 탭에 전해진다.
- STUN/TURN 없이 (iceServers 없음) → 같은 와이파이에서만 연결된다.
- 데이터 채널은 웹소켓 손님 하나처럼 다룬다 (server.clients 에 넣어 같은 _handle 로 처리).
"""
import asyncio
import hashlib
import hmac
import json
import secrets
import time

from . import config, store

KEY_FILE = config.DATA_DIR / "rtc_key.txt"
CHUNK = 48000   # 데이터 채널 한 번에 보낼 글 크기 (큰 기록·그림은 나눠 보낸다)


def key() -> str:
    try:
        k = KEY_FILE.read_text(encoding="utf-8").strip()
        if len(k) >= 32:
            return k
    except Exception:
        pass
    k = secrets.token_urlsafe(32)
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(k, encoding="utf-8")
    return k


def sign(*parts) -> str:
    return hmac.new(key().encode(), "|".join(str(p) for p in parts).encode(), hashlib.sha256).hexdigest()


class DcClient:
    """데이터 채널을 웹소켓처럼 (server 가 쓰는 send_str / send_bytes)."""

    def __init__(self, ch):
        self.ch = ch
        self._parts = {}

    @property
    def closed(self):
        return self.ch.readyState != "open"

    async def send_str(self, s: str):
        if len(s) <= CHUNK:
            self.ch.send(s)
            return
        cid = secrets.token_hex(4)
        n = (len(s) + CHUNK - 1) // CHUNK
        for i in range(n):
            self.ch.send(json.dumps({"_chunk": cid, "i": i, "n": n, "d": s[i * CHUNK:(i + 1) * CHUNK]}, ensure_ascii=False))

    async def send_bytes(self, b: bytes):
        self.ch.send(b)

    async def close(self):
        self.ch.close()

    def join(self, text: str):
        """나눠 온 글 다시 붙이기. 다 오면 원래 글, 아니면 None."""
        if not text.startswith('{"_chunk"'):
            return text
        m = json.loads(text)
        parts = self._parts.setdefault(m["_chunk"], {})
        parts[m["i"]] = m["d"]
        if len(parts) < m["n"]:
            return None
        del self._parts[m["_chunk"]]
        return "".join(parts[i] for i in range(m["n"]))


class RtcBridge:
    def __init__(self, server):
        self.s = server
        self.seen: set[str] = set()
        self.pcs = set()
        key()
        store.rtc_listener = self.check

    def check(self):
        """Firebase /rtc 가 바뀌었을 때 (Firebase 스레드에서 불림): 새 offer 에 답한다."""
        try:
            rows = store.get("rtc") or {}
        except Exception:
            return
        now = time.time() * 1000
        for sid, row in rows.items():
            if not isinstance(row, dict):
                continue
            if now - float(row.get("t") or 0) > 5 * 60 * 1000:   # 오래된 인사는 치운다
                store.in_background(store.delete, f"rtc/{sid}")
                continue
            if sid in self.seen or "answer" in row or "offer" not in row:
                continue
            self.seen.add(sid)
            asyncio.run_coroutine_threadsafe(self._answer(sid, row), self.s.loop)

    async def _answer(self, sid: str, row: dict):
        from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
        offer = row.get("offer") or {}
        t = row.get("t")
        if not hmac.compare_digest(sign(sid, t, offer.get("sdp", "")), str(row.get("mac", ""))):
            print("WebRTC: 열쇠가 틀린 연결 요청을 막았어요", sid)
            return
        if abs(time.time() * 1000 - float(t or 0)) > 2 * 60 * 1000:
            return
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))   # STUN 없음 = 같은 와이파이에서만
        self.pcs.add(pc)

        @pc.on("datachannel")
        def on_dc(ch):
            client = DcClient(ch)

            @ch.on("open")
            def _open():
                self._joined(client)

            if ch.readyState == "open":
                self._joined(client)

            @ch.on("message")
            def on_msg(msg):
                if isinstance(msg, (bytes, bytearray)):
                    self.s.brain.feed_audio(bytes(msg))
                    return
                text = client.join(msg)
                if text is None:
                    return
                asyncio.ensure_future(self._handle(client, text))

            @ch.on("close")
            def _close():
                self.s.clients.discard(client)
                self.s.brain.talk_end()

        @pc.on("connectionstatechange")
        async def on_state():
            if pc.connectionState in ("failed", "closed"):
                self.pcs.discard(pc)
                await pc.close()

        await pc.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type=offer.get("type", "offer")))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)   # 후보(내 주소) 모으기까지 기다린다
        sdp = pc.localDescription.sdp
        await asyncio.to_thread(store.patch, f"rtc/{sid}", {"answer": {"sdp": sdp, "type": "answer"},
                                                            "mac2": sign(sid, "answer", sdp)})
        print("WebRTC: 탭 연결 요청에 답했어요", sid)
        await asyncio.sleep(60)
        await asyncio.to_thread(lambda: store.delete(f"rtc/{sid}"))   # 인사는 다 썼으면 지운다

    def _joined(self, client):
        if client in self.s.clients:
            return
        self.s.clients.add(client)
        print("WebRTC: 탭이 연결됐어요 (인증서 없이)")
        asyncio.ensure_future(client.send_str(json.dumps({"type": "hello", "data": self.s.hello_data()}, ensure_ascii=False)))

    async def _handle(self, client, text):
        try:
            await self.s._handle(client, json.loads(text))
        except Exception as e:
            await client.send_str(json.dumps({"type": "error", "data": f"{e}"}, ensure_ascii=False))
