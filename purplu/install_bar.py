"""install&check.bat 이 부른다: 필요한 프로그램을 하나씩 설치하며, 긴 막대와 퍼센트로 얼마나 됐는지 보여 준다.

    .venv\\Scripts\\python purplu\\install_bar.py requirements.txt

표준 라이브러리만 쓴다 (아직 아무것도 안 깔렸을 때 돌기 때문).
"""
import os
import shutil
import subprocess
import sys

BAR = "━"
ESC = "\x1b"


def _rgb(t: float):
    """0~1 → 짙은 파랑 → 파랑 → 하늘 (막대 왼쪽에서 오른쪽으로, 움직이지 않는 색)."""
    stops = [(37, 99, 235), (59, 130, 246), (56, 189, 248)]
    t = max(0.0, min(1.0, t)) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    a, b = stops[i], stops[i + 1]
    f = t - i
    return tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))


def _line(done: int, total: int) -> str:
    """━━━━━━━━━━━━━━━━  42%   (채워진 만큼만 색, 나머지는 흐린 회색)"""
    cols = shutil.get_terminal_size((80, 20)).columns
    width = max(20, min(50, cols - 14))
    frac = done / total if total else 1
    filled = int(width * frac)
    out = []
    for i in range(width):
        if i < filled:
            r, g, b = _rgb(i / max(1, width - 1))
            out.append(f"{ESC}[38;2;{r};{g};{b}m{BAR}")
        else:
            out.append(f"{ESC}[38;2;70;70;84m{BAR}")
    return "\r  " + "".join(out) + f"{ESC}[0m  {ESC}[1m{int(frac * 100):3d}%{ESC}[0m"


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
    failed = []
    for n, (args, name) in enumerate(zip(steps, names)):
        sys.stdout.write(_line(n, len(steps)))   # 하나 끝날 때만 다시 그린다 (기다리는 동안엔 가만히)
        sys.stdout.flush()
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            failed.append((name, (r.stderr or r.stdout).strip().splitlines()[-3:]))
    sys.stdout.write(_line(len(steps), len(steps)) + "\n")
    for name, tail in failed:
        print(f"      설치 실패: {name}")
        for x in tail:
            print(f"        {x}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
