"""퍼플루 지킴이: 퍼플루가 갑자기 꺼지면(오류로 죽으면) 바로 다시 켠다.

트레이의 '종료'로 끈 건 다시 켜지 않는다 (퍼플루가 data/quit.flag를 남긴다).
run.bat이 이걸 켠다:  pythonw -m purplu.keeper
"""
import os
import subprocess
import sys
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
FLAG = DATA / "quit.flag"
LOG = DATA / "purplu.log"
ALREADY_RUNNING = 3  # 퍼플루가 '이미 켜져 있어요'로 끝날 때의 번호


def log(msg: str):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[지킴이 {time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    FLAG.unlink(missing_ok=True)
    crashes = []
    while True:
        started = time.time()
        p = subprocess.Popen([sys.executable, "-m", "purplu"], cwd=str(DATA.parent), env={**os.environ, "PURPLU_KEEPER": "1"})
        code = p.wait()
        if FLAG.exists():  # 사용자가 트레이에서 '종료'
            FLAG.unlink(missing_ok=True)
            log("사용자가 종료해서 지킴이도 끝")
            return
        if code == ALREADY_RUNNING:
            return
        crashes = [t for t in crashes if time.time() - t < 120] + [time.time()]
        wait = 60 if len(crashes) >= 5 else 2  # 2분에 5번 넘게 죽으면 1분 쉬었다가
        log(f"퍼플루가 꺼졌어요 (코드 {code}, {time.time() - started:.0f}초 동안 켜져 있었음) → {wait}초 뒤 다시 켜요")
        time.sleep(wait)


if __name__ == "__main__":
    main()
