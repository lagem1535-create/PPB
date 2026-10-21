"""갤럭시 탭 연결 서버 (https + WebSocket).

탭은 마이크·스피커·얼굴 역할만 하고, 두뇌(Gemini)는 PC에서 돈다. 그래서 Gemini 키가 탭에 갈 일이 없다.

탭 → PC: 바이너리 = 마이크 소리(16kHz PCM16), JSON = {"type": ...}
  talk_start / talk_end / get_settings / save_settings{changes} / list_conversations /
  new_conversation / select_conversation{id} / get_messages{id} / rename_conversation{id,title} / delete_conversation{id}
PC → 탭: 바이너리 = 대답 목소리(24kHz PCM16), JSON = {"type": 이벤트 이름, "data": ...}
"""
import asyncio
import datetime
import ipaddress
import json
import socket
import ssl
import subprocess
import threading
from pathlib import Path

from aiohttp import WSMsgType, web

from . import config, store

WEB_DIR = Path(__file__).parent / "web"
CERT = config.DATA_DIR / "tablet-cert.pem"
KEY = config.DATA_DIR / "tablet-key.pem"


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # 실제로 보내지는 않음
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


CA_CERT = config.DATA_DIR / "purplu-ca.pem"
CA_KEY = config.DATA_DIR / "purplu-ca-key.pem"


def _ca():
    """퍼플루 전용 인증 기관(CA). 탭에 이 CA를 한 번 설치하면 '안전하지 않음' 경고가 없어진다. 이 PC에만 있다."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    if CA_CERT.exists() and CA_KEY.exists():
        return (x509.load_pem_x509_certificate(CA_CERT.read_bytes()),
                serialization.load_pem_private_key(CA_KEY.read_bytes(), None))
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Purplu Local CA ({socket.gethostname()})")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    CA_KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    CA_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, key


def _make_cert(ip: str):
    """탭 크롬이 마이크를 쓰려면 https가 필요 → 퍼플루 CA로 이 PC 주소용 인증서를 만든다 (크롬 규칙상 1년짜리)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    ca_cert, ca_key = _ca()
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    alt = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    try:
        alt.append(x509.IPAddress(ipaddress.ip_address(ip)))
    except ValueError:
        pass
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Purplu PC {ip}")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=360))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
    (config.DATA_DIR / "tablet-cert-ip.txt").write_text(ip)


def _cert_is_current(ip: str) -> bool:
    """인증서가 퍼플루 CA로 만든 것이고, 지금 IP용이고, 30일 넘게 남았는지."""
    from cryptography import x509
    try:
        ip_file = config.DATA_DIR / "tablet-cert-ip.txt"
        if not (CERT.exists() and KEY.exists() and CA_CERT.exists() and ip_file.read_text() == ip):
            return False
        cert = x509.load_pem_x509_certificate(CERT.read_bytes())
        ca = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
        left = cert.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc)
        return cert.issuer == ca.subject and left.days > 30
    except Exception:
        return False


def _local_networks() -> list:
    """이 PC가 붙어 있는 네트워크(와이파이·유선)의 주소 범위."""
    import psutil
    nets = []
    for addrs in psutil.net_if_addrs().values():
        for a in addrs:
            if a.family == socket.AF_INET and a.netmask and not a.address.startswith("127."):
                try:
                    nets.append(ipaddress.ip_network(f"{a.address}/{a.netmask}", strict=False))
                except ValueError:
                    pass
    return nets


def _mention_list() -> list[dict]:
    """@로 부를 수 있는 것: 지금 열린 탭·창 먼저, 그다음 브라우저, 앱, 메모."""
    out, later = [], []
    try:
        from . import browser
        connected = browser.names()
        for name in ("크롬", "웨일", "엣지"):
            later.append({"label": name, "kind": "브라우저" if name in connected else "브라우저 (확장 연결 안 됨)", "id": name})
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        import psutil

        from . import browser
        from .tools.windows import _windows
        connected = set(browser.names())
        app_names = {"explorer.exe": "탐색기", "chrome.exe": "크롬", "whale.exe": "웨일", "msedge.exe": "엣지",
                     "notepad.exe": "메모장", "calculatorapp.exe": "계산기", "code.exe": "VS Code", "kakaotalk.exe": "카카오톡",
                     "systemsettings.exe": "설정", "claude.exe": "Claude", "winword.exe": "워드", "excel.exe": "엑셀",
                     "powerpnt.exe": "파워포인트", "hwp.exe": "한글", "discord.exe": "디스코드", "spotify.exe": "스포티파이",
                     "applicationframehost.exe": ""}   # 윈도우 기본 앱(설정·계산기 등)은 창 제목이 곧 앱 이름
        browser_exe = {"chrome.exe": "크롬", "whale.exe": "웨일", "msedge.exe": "엣지"}
        for hwnd, title in _windows()[:25]:
            if "퍼플루" in title:
                continue
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                exe = psutil.Process(pid.value).name().lower()
            except Exception:
                exe = ""
            if browser_exe.get(exe) in connected:
                continue   # 확장이 붙은 브라우저는 창 대신 탭으로 보여 준다
            app = app_names[exe] if exe in app_names else exe.replace(".exe", "")
            short = title.split(" - ")[0].strip() or title   # '6학년 … - Whale' 같은 꼬리 떼기
            label = short if short == app else (f"{app}_{short}" if app else short)
            out.append({"label": label[:44], "kind": "열린 창", "id": title})
    except Exception:
        pass
    try:  # 브라우저마다 열린 탭: '웨일_새 메시지'처럼
        from . import browser
        for bname in browser.names():
            try:
                tabs = browser.call_to(bname, "tabs", timeout=4)
            except Exception:
                continue
            for t in tabs[:20]:
                out.insert(0, {"label": f"{bname}_{(t.get('title') or t.get('url') or '')[:36]}", "kind": "열린 탭",
                               "id": t["tab_id"], "url": t.get("url", ""), "browser": bname})
    except Exception:
        pass
    seen, uniq = set(), []
    for m in out:   # 같은 탭·창이 두 번 나오지 않게
        key = (m["kind"], m["label"])
        if key not in seen:
            seen.add(key)
            uniq.append(m)
    out = uniq
    if config.settings().get("mention_open_only", True):   # 설정: 지금 열린 탭·창만
        return [m for m in out if m["kind"] in ("열린 탭", "열린 창")] + later
    try:
        from .tools.apps import all_apps
        out += later
        for name in sorted(all_apps())[:400]:
            out.append({"label": name[:40], "kind": "앱", "id": name})
    except Exception:
        pass
    try:
        for mm in store.list_memos()[:10]:
            out.append({"label": (mm.get("text") or "")[:30], "kind": "메모", "id": mm["id"]})
    except Exception:
        pass
    return out


def _expand_chat(text: str, mentions: list) -> str:
    """'#스킬이름 …' → 그 스킬을 쓰라는 지시, '@멘션' → 무엇을 가리키는지 덧붙인다."""
    text = (text or "").strip()
    if "#" in text:   # 띄어쓰기가 있는 스킬 이름도 (예: #아침 브리핑) — 가장 길게 맞는 이름
        try:
            from .tools.skills import list_skills
            names = sorted((r["name"] for r in list_skills()["skills"]), key=len, reverse=True)
            hit = next((n for n in names if f"#{n}" in text), None)
            if hit:
                rest = text.replace(f"#{hit}", "", 1).strip()
                text = f"[#{hit} 스킬] {rest}\n(지시: use_skill('{hit}')로 설명서를 먼저 읽고 그대로 해.)"
        except Exception:
            pass
    elif text.startswith("/"):   # 예전 방식 '/스킬' 도 그대로 알아듣기
        name, _, rest = text[1:].partition(" ")
        try:  # 띄어쓰기가 있는 스킬 이름도 (예: /아침 브리핑) — 가장 길게 맞는 이름
            from .tools.skills import list_skills
            names = sorted((r["name"] for r in list_skills()["skills"]), key=len, reverse=True)
            hit = next((n for n in names if text[1:].startswith(n)), None)
            if hit:
                name, rest = hit, text[1 + len(hit):].strip()
        except Exception:
            pass
        text = f"[/{name} 스킬] {rest}\n(지시: use_skill('{name}')로 설명서를 먼저 읽고 그대로 해.)"
    notes = []
    # 목록에서 안 고르고 그냥 쓴 @웨일, @계산기 같은 것도 알아듣기
    import re
    picked = {m.get("label") for m in mentions}
    for tok in re.findall(r"@(\S+)", text):
        if tok in picked:
            continue
        if tok in ("웨일", "크롬", "엣지", "whale", "chrome", "edge"):
            name = {"whale": "웨일", "chrome": "크롬", "edge": "엣지"}.get(tok.lower(), tok)
            mentions = mentions + [{"label": tok, "kind": "브라우저", "id": name}]
        else:
            try:
                from .tools.apps import find_app
                hit = find_app(tok)
                if hit:
                    mentions = mentions + [{"label": tok, "kind": "앱", "id": hit[1]}]
            except Exception:
                pass
    for m in mentions:
        label = m.get("label", "")
        if f"@{label}" not in text:
            continue
        if str(m.get("kind", "")).startswith("브라우저"):
            from . import browser
            name = m.get("id")
            if name in browser.names():
                browser.prefer(name)
                notes.append(f"@{label} = {name} 브라우저 → browser_* 도구는 이제 {name}으로 가 (확장 연결됨)")
            else:
                notes.append(f"@{label} = {name} 브라우저. 확장이 아직 연결 안 됐어 → open_app('{name}')로 켜고, "
                             f"안 되면 사용자에게 {name}에 퍼플루 확장을 설치·새로고침해 달라고 해")
        elif m.get("kind") == "앱":
            notes.append(f"@{label} = PC 앱 '{m.get('id')}' → open_app으로 열고 조작")
        elif m.get("kind") in ("탭", "열린 탭"):
            if m.get("browser"):
                from . import browser
                browser.prefer(m["browser"])   # 그 탭이 있는 브라우저로
            notes.append(f"@{label} = 브라우저 탭 (tab_id {m.get('id')}, {m.get('url', '')}) → browser_switch_tab 후 browser_read")
        elif m.get("kind") in ("창", "열린 창"):
            notes.append(f"@{label} = PC에 열린 창 '{m.get('id')}' → windows_action focus_window 후 look_at_screen")
        elif m.get("kind") == "메모":
            notes.append(f"@{label} = 메모 (id {m.get('id')})")
    return text + ("\n[멘션] " + " / ".join(notes) if notes else "")


class TabletServer:
    def __init__(self, brain):
        self.brain = brain
        self.port = int(config.settings()["tablet_port"])
        self._nets, self._nets_at = [], -1e9
        self.ip = local_ip()
        self.clients: set[web.WebSocketResponse] = set()
        self.loop = asyncio.new_event_loop()
        self.error = None
        self.network_problem = ""
        self.on_python_answered = lambda req_id: None  # UI가 연결: PC 확인창 닫기
        threading.Thread(target=self._run, daemon=True, name="purplu-tablet").start()
        threading.Thread(target=self._check_network, daemon=True).start()

    def _check_network(self):
        """와이파이가 '공용'이면 Windows 방화벽이 탭 연결을 막는 경우가 많다 → 설정창에 알려 준다."""
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-NetConnectionProfile | Where-Object IPv4Connectivity -ne 'Disconnected' | "
                 "Select-Object -First 1).NetworkCategory"],
                capture_output=True, text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
        except Exception:
            return
        if out == "Public":
            self.network_problem = ("지금 와이파이가 '공용 네트워크'로 되어 있어서 Windows 방화벽이 탭 연결을 막고 있을 수 있어요.\n"
                                    "Windows 설정 → 네트워크 및 인터넷 → Wi-Fi → 연결된 와이파이 → '개인 네트워크'로 바꿔 주세요.")

    @property
    def https_port(self) -> int:
        return self.port + 1

    @property
    def url(self) -> str:
        """탭에서 열 주소 (마이크 때문에 https)."""
        return f"https://{self.ip}:{self.https_port}"

    @property
    def local_url(self) -> str:
        """이 PC에서 열 주소 (localhost는 http여도 마이크가 된다)."""
        return f"http://localhost:{self.port}"

    # ---- 같은 와이파이(같은 네트워크)와 이 PC에서만 들어올 수 있다 ----
    def _allowed(self, request) -> bool:
        if any(h in request.headers for h in ("Cf-Connecting-Ip", "X-Forwarded-For", "Forwarded", "X-Real-Ip")):
            return False  # 터널·프록시를 거친 인터넷 접속은 막는다
        try:
            ip = ipaddress.ip_address((request.remote or "").split("%")[0])
        except ValueError:
            return False
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_loopback:
            return True
        now = __import__("time").monotonic()
        if now - self._nets_at > 30:  # 와이파이가 바뀌어도 따라가게 30초마다 다시 본다
            self._nets, self._nets_at = _local_networks(), now
        return any(ip in n for n in self._nets)

    def _deny(self, request):
        print(f"막은 접속: {request.remote} (다른 네트워크)")
        return web.Response(status=403, content_type="text/html", text=(
            "<meta charset=utf-8><body style='font-family:sans-serif;background:#120B22;color:#eee;padding:40px'>"
            "<h2>🔒 퍼플루</h2><p>PC와 <b>같은 와이파이</b>에서만 열 수 있어요.</p>"))

    async def _hello(self, request):
        """GitHub Pages 화면이 '인증서 허용'을 확인하는 주소."""
        if not self._allowed(request):
            return self._deny(request)
        back = request.query.get("back", "")
        pages = (config.settings().get("pages_url") or "").strip()
        if back and pages and back.startswith(pages.rstrip("/")):
            raise web.HTTPFound(back)  # 경고를 넘기고 들어왔으면 앱으로 돌아가기
        return web.Response(content_type="text/html", text=(
            "<meta charset=utf-8><body style='font-family:sans-serif;background:#120B22;color:#eee;padding:40px'>"
            "<h2>✓ 퍼플루 PC 연결 허용됨</h2><p>이 창을 닫고 퍼플루 화면으로 돌아가세요.</p>"))

    async def _ca_file(self, request):
        """탭에 설치할 퍼플루 인증서 (한 번만 설치하면 경고가 안 떠요)."""
        if not self._allowed(request):
            return self._deny(request)
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        der = x509.load_pem_x509_certificate(CA_CERT.read_bytes()).public_bytes(serialization.Encoding.DER)
        return web.Response(body=der, content_type="application/x-x509-ca-cert",
                            headers={"Content-Disposition": 'attachment; filename="purplu-ca.crt"'})

    async def _page(self, request):
        if not self._allowed(request):
            return self._deny(request)
        host = request.host.split(":")[0]
        print(f"탭 접속: {request.remote} → {request.scheme}://{request.host}{request.path}")  # 패드가 PC에 닿았는지 확인용
        if request.secure or host in ("localhost", "127.0.0.1", "[::1]"):
            return web.FileResponse(WEB_DIR / "tablet.html", headers={"Cache-Control": "no-store"})
        # 다른 기기에서 http로 오면 마이크가 막히므로 https로 보낸다
        raise web.HTTPFound(f"https://{host}:{self.https_port}/")

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            if not _cert_is_current(self.ip):
                _make_cert(self.ip)
            ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ctx.load_cert_chain(CERT, KEY)
            app = web.Application()
            app.router.add_get("/", self._page)
            app.router.add_get("/ws", self._ws)
            app.router.add_get("/ext", self._ext)
            app.router.add_get("/img/{name}", self._img)
            app.router.add_get("/ca.crt", self._ca_file)
            app.router.add_get("/hello", self._hello)
            runner = web.AppRunner(app, access_log=None)
            self.loop.run_until_complete(runner.setup())
            # http (localhost용, 그리고 https로 안내) + https (탭용)
            self.loop.run_until_complete(web.TCPSite(runner, "0.0.0.0", self.port).start())
            self.loop.run_until_complete(web.TCPSite(runner, "0.0.0.0", self.https_port, ssl_context=ctx).start())
        except Exception as e:
            self.error = str(e)
            print("탭 서버 시작 실패:", e)
            return
        self.loop.create_task(self._send_mouse())
        self.loop.run_forever()

    async def _send_mouse(self):
        """탭의 퍼플루 눈이 PC 마우스를 따라보게 위치를 보낸다 (블루이처럼)."""
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        u = ctypes.windll.user32
        last = None
        while True:
            await asyncio.sleep(1 / 15)
            if not self.clients:
                continue
            u.GetCursorPos(ctypes.byref(pt))
            w, h = u.GetSystemMetrics(0) or 1, u.GetSystemMetrics(1) or 1
            pos = (round(pt.x / w, 3), round(pt.y / h, 3))
            if pos != last:
                last = pos
                await self._send_all(json.dumps({"type": "mouse", "data": pos}))

    # ---- PC → 탭 ----

    def broadcast(self, kind: str, data):
        if not self.clients:
            return
        if kind == "audio":
            payload = data
        else:
            payload = json.dumps({"type": kind, "data": data}, ensure_ascii=False, default=str)
        asyncio.run_coroutine_threadsafe(self._send_all(payload), self.loop)

    async def _send_all(self, payload):
        for ws in list(self.clients):
            try:
                if isinstance(payload, bytes):
                    await ws.send_bytes(payload)
                else:
                    await ws.send_str(payload)
            except Exception:
                self.clients.discard(ws)

    async def _ext(self, request):
        """크롬 확장 연결. 이 PC 안에서 온 크롬 확장만 받는다 (와이파이의 다른 기기는 거절)."""
        origin = request.headers.get("Origin", "")
        if request.remote not in ("127.0.0.1", "::1") or not origin.startswith("chrome-extension://"):
            raise web.HTTPForbidden(text="퍼플루 크롬 확장만 연결할 수 있어요")
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=8 * 1024 * 1024)
        await ws.prepare(request)
        from . import browser
        await browser.handle(ws, self.loop, request.headers.get("User-Agent", ""))
        return ws

    # ---- 탭 → PC ----

    async def _img(self, request):
        if not self._allowed(request):
            return self._deny(request)
        name = request.match_info["name"]
        path = (config.DATA_DIR / "images" / name).resolve()
        if path.parent != (config.DATA_DIR / "images").resolve() or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    def _origin_ok(self, request) -> bool:
        """웹소켓은 PC가 준 페이지 또는 설정한 GitHub Pages 페이지에서 온 것만 받는다 (다른 웹사이트가 몰래 붙지 못하게)."""
        origin = request.headers.get("Origin", "")
        if not origin:
            return True  # 브라우저가 아닌 프로그램 (같은 와이파이 안)
        host = origin.split("://", 1)[-1]
        if host.split(":")[0] in ("localhost", "127.0.0.1", self.ip):
            return True
        pages = (config.settings().get("pages_url") or "").strip()
        if pages:
            from urllib.parse import urlsplit
            p = urlsplit(pages)
            return origin == f"{p.scheme}://{p.netloc}"
        return False

    def pages_link(self) -> str:
        """GitHub Pages 링크 (PC 주소를 붙여서 그대로 열면 바로 연결)."""
        pages = (config.settings().get("pages_url") or "").strip()
        return f"{pages.rstrip('/')}/?pc={self.ip}:{self.https_port}" if pages else ""

    async def _ws(self, request):
        if not self._allowed(request):
            return self._deny(request)
        if not self._origin_ok(request):
            print("막은 웹소켓 출처:", request.headers.get("Origin"))
            raise web.HTTPForbidden(text="이 페이지에서는 퍼플루에 연결할 수 없어요")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        self.clients.add(ws)
        await ws.send_str(json.dumps({"type": "hello", "data": {"settings": config.settings(), "voices": config.VOICES,
                                                                 "python_approval": config.PYTHON_APPROVAL,
                                                                 "python_warning": config.PYTHON_APPROVAL_WARNING,
                                                                 "security_levels": config.SECURITY_LEVELS,
                                                                 "security_warning": config.SECURITY_WARNING,
                                                                 "security_python": config.SECURITY_PYTHON,
                                                                 "themes": config.THEMES,
                                                                 "state": getattr(self.brain, "last_state", "idle"),
                                                                 "models": {"gemini-3.8-live": "⚡ 빠른 모델",
                                                                            "gemini-3.8-live-extended-thinking": "🧠 생각하는 모델"}}},
                                     ensure_ascii=False))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    self.brain.feed_audio(msg.data)
                elif msg.type == WSMsgType.TEXT:
                    try:
                        await self._handle(ws, json.loads(msg.data))
                    except Exception as e:
                        await ws.send_str(json.dumps({"type": "error", "data": f"{e}"}, ensure_ascii=False))
        finally:
            self.clients.discard(ws)
            self.brain.talk_end()
        return ws

    async def _reply(self, ws, kind, data):
        await ws.send_str(json.dumps({"type": kind, "data": data}, ensure_ascii=False, default=str))

    async def _handle(self, ws, m: dict):
        t = m.get("type")
        if t == "talk_start":
            self.brain.talk_start("pc" if m.get("pc") else "tablet")   # PC 대화창 = PC 마이크·스피커
        elif t == "talk_end":
            self.brain.talk_end(quiet=bool(m.get("short")))
        elif t == "get_settings":
            await self._reply(ws, "settings", await asyncio.to_thread(config.load))
        elif t == "save_settings":
            changes = {k: v for k, v in (m.get("changes") or {}).items() if k in config.DEFAULTS}
            await asyncio.to_thread(lambda: config.save_settings(**changes))
            await self._reply(ws, "settings", config.settings())
        elif t == "list_conversations":
            rows = await asyncio.to_thread(store.list_conversations)
            await self._reply(ws, "conversations", {"items": rows,
                                                    "current": config.settings().get("current_conversation")})
        elif t == "chat_history":
            cid = config.settings().get("current_conversation") or ""
            items = (await asyncio.to_thread(store.messages, cid))[-60:] if cid else []
            await self._reply(ws, "history", {"id": cid, "items": items})
        elif t == "get_messages":
            await self._reply(ws, "messages", {"id": m["id"], "items": await asyncio.to_thread(store.messages, m["id"])})
        elif t == "new_conversation":
            self.brain.new_conversation()
        elif t == "select_conversation":
            self.brain.select_conversation(m["id"])
        elif t == "rename_conversation":
            await asyncio.to_thread(store.rename_conversation, m["id"], m["title"])
            self.broadcast("conversations_changed", None)
        elif t == "python_answer":
            from .tools import pyrun
            pyrun.answer(m["id"], bool(m.get("ok")))
            self.broadcast("python_answered", {"id": m["id"], "ok": bool(m.get("ok"))})
            self.on_python_answered(m["id"])
        elif t == "chat":
            import base64
            img = base64.b64decode(m["image"]) if m.get("image") else None
            text = await asyncio.to_thread(_expand_chat, m.get("text", ""), m.get("mentions") or [])
            self.brain.send_text(text, img, m.get("mime") or "image/jpeg", shown=m.get("text", ""))
        elif t == "mentions":
            await self._reply(ws, "mentions", await asyncio.to_thread(_mention_list))
        elif t == "list_skills":
            from .tools import skills
            await self._reply(ws, "skills", (await asyncio.to_thread(skills.list_skills))["skills"])
        elif t == "get_skill":
            from . import store as st
            await self._reply(ws, "skill", {"id": m["id"], **(await asyncio.to_thread(st.get, f"skills/{m['id']}") or {})})
        elif t in ("save_skill_row", "toggle_skill", "delete_skill_row"):
            from . import store as st
            if t == "save_skill_row":
                row = {k: m.get(k, "") for k in ("name", "description", "instructions")}
                row["enabled"] = True
                if m.get("id"):
                    await asyncio.to_thread(st.patch, f"skills/{m['id']}", row)
                else:
                    await asyncio.to_thread(st.post, "skills", {**row, "created": st.now_ms()})
            elif t == "toggle_skill":
                await asyncio.to_thread(st.patch, f"skills/{m['id']}", {"enabled": bool(m.get("enabled"))})
            else:
                await asyncio.to_thread(st.delete, f"skills/{m['id']}")
            from .tools import skills
            self.broadcast("skills", (await asyncio.to_thread(skills.list_skills))["skills"])
            self.brain.refresh_session()
        elif t == "wake":
            self.brain.wake()
        elif t == "sleep":
            self.brain.sleep()
        elif t == "preview_voice":
            self.brain.preview_voice(str(m.get("voice", "")), "tablet" if m.get("on") != "pc" else "pc")
        elif t == "list_memos":
            await self._reply(ws, "memos", await asyncio.to_thread(store.list_memos))
        elif t == "add_memo":
            await asyncio.to_thread(store.add_memo, m["text"], m.get("pinned", True))
        elif t == "update_memo":
            fields = {k: v for k, v in m.items() if k in ("text", "pinned")}
            await asyncio.to_thread(lambda: store.update_memo(m["id"], **fields))
        elif t == "delete_memo":
            await asyncio.to_thread(store.delete_memo, m["id"])
        elif t == "delete_conversation":
            await asyncio.to_thread(store.delete_conversation, m["id"])
            if m["id"] == config.settings().get("current_conversation"):
                self.brain.new_conversation()
            self.broadcast("conversations_changed", None)
