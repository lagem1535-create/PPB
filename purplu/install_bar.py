"""install&check.bat 이 부른다: 필요한 프로그램을 하나씩 설치하며, 색이 흐르는 긴 막대로 얼마나 됐는지 보여 준다.

    .venv\\Scripts\\python purplu\\install_bar.py requirements.txt

표준 라이브러리만 쓴다 (아직 아무것도 안 깔렸을 때 돌기 때문).
"""
import os
import shutil
import subprocess
import sys
import threading
import time

BAR = "━"


def _rgb(t: float):
    """0~1 → 보라 → 분홍 → 주황 → 분홍 → 보라 (끊김 없이 돌게)."""
    stops = [(139, 92, 246), (236, 72, 153), (249, 115, 22), (236, 72, 153), (139, 92, 246)]
    t = (t % 1.0) * (len(stops) - 1)
    i = int(t)
    a, b = stops[i], stops[min(i + 1, len(stops) - 1)]
    f = t - i
    return tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))


def _line(done: int, total: int, name: str, now: float) -> str:
    cols = shutil.get_terminal_size((80, 20)).columns
    width = max(20, min(50, cols - 34))
    frac = done / total if total else 1
    filled = int(width * frac)
    shift = now * 0.35   # 색이 오른쪽으로 흘러간다
    out = []
    for i in range(width):
        if i < filled or (i == filled and int(now * 4) % 2 == 0 and done < total):   # 끝 칸은 깜빡
            r, g, b = _rgb(i / width * 0.6 - shift)
            out.append(f"\x1b[38;2;{r};{g};{b}m{BAR}")
        else:
            out.append(f"\x1b[38;2;70;70;84m{BAR}")
    pct = int(frac * 100)
    label = (name[:22] + "…") if len(name) > 23 else name
    return f"\r  {''.join(out)}\x1b[0m  \x1b[1m{pct:3d}%\x1b[0m\x1b[38;2;160;160;170m{label:<24}\x1b[0m"


def main() -> int:
    req = sys.argv[1] if len(sys.argv) > 1 else "requirements.txt"
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.system("")   # 윈도우 콘솔에서 색 글자(VT) 켜기
    pkgs = []
    for raw in open(req, encoding="utf-8"):
        line = raw.split("#")[0].strip()
        if line and not line.startswith("-"):
            pkgs.append(line)
    steps = [["--upgrade", "pip"]] + [[p] for p in pkgs] + [["-r", req]]   # 마지막: 전체가 서로 맞는지 한 번 더
    names = ["pip"] + pkgs + ["마무리 확인"]
    state = {"done": 0, "name": names[0], "run": True}

    def draw():
        while state["run"]:
            sys.stdout.write(_line(state["done"], len(steps), state["name"], time.time()))
            sys.stdout.flush()
            time.sleep(0.08)

    t = threading.Thread(target=draw, daemon=True)
    t.start()
    failed = []
    for args, name in zip(steps, names):
        state["name"] = name
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            failed.append((name, (r.stderr or r.stdout).strip().splitlines()[-3:]))
        state["done"] += 1
    state["run"] = False
    t.join()
    sys.stdout.write(_line(len(steps), len(steps), "다 됐어요" if not failed else "일부 실패", time.time()) + "\n")
    for name, tail in failed:
        print(f"      설치 실패: {name}")
        for x in tail:
            print(f"        {x}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
