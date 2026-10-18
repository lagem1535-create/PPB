"""회의록 (원본 Bluey의 Meeting notes처럼).

회의록을 켜면 PC 마이크 소리를 계속 녹음해서 5분마다 WAV 조각으로 저장하고,
조각마다 뒤에서 Gemini가 화자를 구분해 받아써서 notes.md에 이어 붙인다.
끝내면 마지막 조각까지 받아쓴 뒤 맨 위에 요약·결정사항·할 일을 정리한다.

저장 위치: D:\bot\data\notes\<날짜 시간 제목>\notes.md, audio\chunk_001.wav ...
"""
import queue
import re
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

from . import config
from . import trace
from .audio import IN_RATE

CHUNK_SECONDS = 5 * 60
BYTES_PER_SECOND = IN_RATE * 2  # 16비트 모노

TRANSCRIBE_PROMPT = """이 회의 녹음을 한국어로 받아써 주세요.
- 말하는 사람을 구분해서 '화자 1', '화자 2'처럼 표시 (같은 사람은 계속 같은 번호)
- 줄마다 앞에 [mm:ss] 시간. 이 녹음은 회의 시작 후 {offset}부터 시작하니, 시간은 회의 시작 기준으로 적어 주세요.
- 형식: [mm:ss] 화자 N: 말한 내용
- 말소리가 없으면 '(말소리 없음)' 한 줄만.
받아쓴 내용만 쓰고 다른 설명은 하지 마세요."""

SUMMARY_PROMPT = """다음은 회의 받아쓰기입니다. 한국어 마크다운으로 정리해 주세요.
## 요약
(3~5줄)
## 결정된 것
(- 목록, 없으면 '- 없음')
## 할 일
(- [ ] 누가: 무엇을 (언제까지) 형식, 없으면 '- 없음')

받아쓰기:
{text}"""


def notes_dir() -> Path:
    d = config.settings().get("notes_dir") or ""
    if d:
        return Path(d)
    return config.NOTES_DIR


def _mmss(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class MeetingRecorder:
    def __init__(self):
        self.mic = None                 # Brain이 PC 마이크를 넣어 준다
        self.on_event = lambda kind, data: None
        self.folder: Path | None = None
        self.title = ""
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._chunks = 0
        self._offset = 0.0              # 지금 쌓고 있는 조각이 회의 시작 후 몇 초부터인지
        self._started = 0.0
        self._jobs: queue.Queue = queue.Queue()
        self._recording = False
        threading.Thread(target=self._worker, daemon=True, name="purplu-notes").start()

    @property
    def recording(self) -> bool:
        return self._recording

    def elapsed(self) -> float:
        return time.monotonic() - self._started if self._recording else 0.0

    # ---- 시작 / 끝 ----

    def start(self, title: str = "") -> dict:
        if self._recording:
            return {"ok": False, "error": f"이미 '{self.title}' 회의록을 쓰고 있어요."}
        if not self.mic:
            return {"ok": False, "error": "PC 마이크를 열 수 없어요."}
        self.title = (title or "회의").strip()[:40]
        safe = re.sub(r'[\\/:*?"<>|]+', " ", self.title).strip() or "회의"
        self.folder = notes_dir() / f"{datetime.now():%Y-%m-%d %H-%M} {safe}"
        try:
            (self.folder / "audio").mkdir(parents=True, exist_ok=True)
            (self.folder / "notes.md").write_text(
                f"# 회의록: {self.title}\n\n- 시작: {datetime.now():%Y-%m-%d %H:%M}\n\n## 받아쓰기\n\n", encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": f"회의록 폴더를 못 만들었어요: {e}"}
        with self._lock:
            self._buf.clear()
        self._chunks, self._offset, self._started = 0, 0.0, time.monotonic()
        self._recording = True
        trace.cmd(f"sounddevice.RawInputStream(16kHz) → {self.folder}\audio\chunk_*.wav")
        self.mic.on_record = self._on_audio
        threading.Thread(target=self._ticker, daemon=True).start()
        self.on_event("meeting", {"status": "recording", "title": self.title, "folder": str(self.folder)})
        return {"ok": True, "folder": str(self.folder), "note": "5분마다 받아써서 notes.md에 쌓을게."}

    def stop(self) -> dict:
        if not self._recording:
            return {"ok": False, "error": "지금 쓰고 있는 회의록이 없어요."}
        self._recording = False
        if self.mic:
            self.mic.on_record = None
        minutes = round(self.elapsed_total() / 60, 1)
        self._flush(final=True)
        self._jobs.put(("summary", self.folder, self.title, None, None))
        self.on_event("meeting", {"status": "finishing", "title": self.title, "folder": str(self.folder)})
        return {"ok": True, "folder": str(self.folder), "minutes": minutes,
                "note": "마지막 부분을 받아쓰고 요약을 정리하는 중이야. 끝나면 알려 줄게."}

    def elapsed_total(self) -> float:
        return time.monotonic() - self._started

    # ---- 녹음 ----

    def _on_audio(self, chunk: bytes):
        with self._lock:
            self._buf += chunk

    def _ticker(self):
        while self._recording:
            time.sleep(1)
            with self._lock:
                full = len(self._buf) >= CHUNK_SECONDS * BYTES_PER_SECOND
            if full:
                self._flush()

    def _flush(self, final=False):
        with self._lock:
            data = bytes(self._buf[:CHUNK_SECONDS * BYTES_PER_SECOND]) if not final else bytes(self._buf)
            del self._buf[:len(data)]
        if len(data) < BYTES_PER_SECOND:  # 1초도 안 되면 버림
            return
        self._chunks += 1
        path = self.folder / "audio" / f"chunk_{self._chunks:03d}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(IN_RATE)
            w.writeframes(data)
        self._jobs.put(("chunk", self.folder, self.title, path, self._offset))
        self._offset += len(data) / BYTES_PER_SECOND

    # ---- 받아쓰기·요약 (순서대로 하나씩) ----

    def _worker(self):
        while True:
            kind, folder, title, path, offset = self._jobs.get()  # 다음 회의가 시작돼도 이 회의 폴더에 쓴다
            try:
                if kind == "chunk":
                    text = self._transcribe(path, offset)
                    self._append(folder, text)
                    self.on_event("meeting", {"status": "transcribed", "chunk": path.name})
                else:
                    self._summarize(folder)
                    self.on_event("meeting", {"status": "done", "title": title, "folder": str(folder)})
            except Exception as e:
                msg = f"_(받아쓰기 실패: {str(e)[:200]})_\n\n" if kind == "chunk" else ""
                if msg:
                    self._append(folder, (f"[{_mmss(offset)}] " if offset is not None else "") + msg)
                else:
                    self.on_event("meeting", {"status": "done", "title": title, "folder": str(folder),
                                              "error": str(e)[:200]})

    def _client(self):
        key = config.get_api_key()
        if not key:
            raise RuntimeError("Gemini 키가 없어요")
        return genai.Client(api_key=key)

    def _transcribe(self, path: Path, offset: float) -> str:
        client = self._client()  # 변수에 잡아 둬야 요청 중에 닫히지 않는다
        resp = client.models.generate_content(
            model=config.settings()["research_model"],
            contents=[types.Part.from_bytes(data=path.read_bytes(), mime_type="audio/wav"),
                      TRANSCRIBE_PROMPT.format(offset=_mmss(offset))])
        return (resp.text or "").strip() + "\n\n"

    def _append(self, folder: Path, text: str):
        with open(folder / "notes.md", "a", encoding="utf-8") as f:
            f.write(text)

    def _summarize(self, folder: Path):
        notes = (folder / "notes.md").read_text(encoding="utf-8")
        body = notes.split("## 받아쓰기", 1)[-1].strip()
        if not re.search(r"화자\s*\d", body):
            raise RuntimeError("받아쓴 내용이 없어서 요약을 못 했어요")
        client = self._client()
        resp = client.models.generate_content(
            model=config.settings()["research_model"], contents=SUMMARY_PROMPT.format(text=body[:60000]))
        summary = (resp.text or "").strip()
        head, rest = notes.split("## 받아쓰기", 1)
        (folder / "notes.md").write_text(
            head.rstrip() + f"\n- 끝: {datetime.now():%Y-%m-%d %H:%M}\n\n{summary}\n\n## 받아쓰기" + rest, encoding="utf-8")


recorder = MeetingRecorder()


# ---- 도구 (Gemini가 부른다) ----

def start_meeting_notes(title: str = "") -> dict:
    return recorder.start(title)


def stop_meeting_notes() -> dict:
    return recorder.stop()
