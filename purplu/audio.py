"""마이크(16kHz 입력)와 스피커(24kHz 출력). Gemini Live 형식: 16비트 PCM, 모노."""
import queue
import threading

import numpy as np
import sounddevice as sd

IN_RATE, OUT_RATE = 16000, 24000
CHUNK_MS = 40


class Mic:
    """켜져 있는 동안 on_chunk(bytes)를 계속 부른다. on_level(0~1)로 소리 크기도 알려준다."""

    def __init__(self, on_chunk, on_level=None):
        self.on_chunk, self.on_level = on_chunk, on_level
        self.active = False
        self.on_record = None  # 회의록 녹음 중이면 말하기와 상관없이 모든 소리를 받는다
        self._stream = sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16",
                                         blocksize=IN_RATE * CHUNK_MS // 1000, callback=self._cb)
        self._stream.start()

    def _cb(self, data, frames, time_info, status):
        chunk = bytes(data)
        if self.on_record:
            self.on_record(chunk)
        if not self.active:
            return
        self.on_chunk(chunk)
        if self.on_level:
            samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
            self.on_level(min(1.0, float(np.sqrt(np.mean(samples ** 2))) / 6000))

    def close(self):
        self._stream.stop()
        self._stream.close()


class Speaker:
    """받은 음성 조각을 순서대로 재생. 다 말하고 나면 on_done()."""

    def __init__(self, on_done=None):
        self.on_done = on_done
        self._q: queue.Queue[bytes] = queue.Queue()
        self._buf = b""
        self._playing = False
        self._lock = threading.Lock()
        self._stream = sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16",
                                          blocksize=OUT_RATE // 50, callback=self._cb)
        self._stream.start()

    def play(self, pcm: bytes):
        with self._lock:
            self._playing = True
        self._q.put(pcm)

    def clear(self):
        with self._lock:
            self._buf = b""
            while not self._q.empty():
                self._q.get_nowait()

    @property
    def playing(self) -> bool:
        return self._playing

    def _cb(self, out, frames, time_info, status):
        need = frames * 2
        with self._lock:
            while len(self._buf) < need and not self._q.empty():
                self._buf += self._q.get_nowait()
            chunk, self._buf = self._buf[:need], self._buf[need:]
            finished = self._playing and not chunk and self._q.empty()
            if finished:
                self._playing = False
        out[:] = chunk + b"\x00" * (need - len(chunk))
        if finished and self.on_done:
            self.on_done()

    def close(self):
        self._stream.stop()
        self._stream.close()
