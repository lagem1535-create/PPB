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
    import win32event, win32api, winerror   # 지킴이도 하나만
    globals()["_m"] = win32event.CreateMutex(None, False, "Purplu.Keeper")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return
    crashes = []
    import win32con
    while True:
        # 퍼플루가 이미 켜져 있으면(지킴이 없이 켰을 때 등) 새로 켜지 말고, 꺼질 때까지 가볍게 지켜본다
        while True:
            try:
                h = win32event.OpenMutex(win32con.SYNCHRONIZE, False, "Purplu.SingleInstance")
                win32api.CloseHandle(h)
            except Exception:
                break
            if FLAG.exists():
                FLAG.unlink(missing_ok=True)
                return
            time.sleep(3)
        started = time.time()
        p = subprocess.Popen([sys.executable, "-m", "purplu"], cwd=str(DATA.parent), env={**os.environ, "PURPLU_KEEPER": "1"})
        code = p.wait()
        if FLAG.exists():  # 사용자가 트레이에서 '종료'
            FLAG.unlink(missing_ok=True)
            log("사용자가 종료해서 지킴이도 끝")
            return
        if code == ALREADY_RUNNING:   # 퍼플루가 이미 켜져 있음 → 그게 꺼질 때까지 지켜보다가, 갑자기 꺼지면 다시 켠다
            time.sleep(3)
            continue
        crashes = [t for t in crashes if time.time() - t < 120] + [time.time()]
        wait = 60 if len(crashes) >= 5 else 2  # 2분에 5번 넘게 죽으면 1분 쉬었다가
        log(f"퍼플루가 꺼졌어요 (코드 {code}, {time.time() - started:.0f}초 동안 켜져 있었음) → {wait}초 뒤 다시 켜요")
        time.sleep(wait)


if __name__ == "__main__":
    main()
