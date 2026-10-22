"""대화창 위쪽에 들어가는 터미널 (PowerShell). 내가 직접 치고, 퍼플루가 실행한 명령도 여기에 보인다.

명령마다 PowerShell 을 새로 띄우고, 'cd' 로 옮긴 폴더는 기억해서 다음 명령에 이어 준다.
"""
from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

MARK = "@@PURPLU_CWD@@"


class Terminal(QWidget):
    purplu_ran = Signal(str, str, int)   # 퍼플루가 실행한 명령 (다른 스레드 → 화면 스레드)

    def __init__(self, cwd: str, colors: dict, accent: str):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.cwd, self.c, self.accent = cwd, colors, accent
        self.hist, self.hi = [], 0
        self.proc = None
        font = QFont()
        font.setFamilies(["Cascadia Mono", "Consolas", "D2Coding"])   # 고정폭 (한글 글꼴이면 \ 가 ₩ 로 보인다)
        font.setStyleHint(QFont.Monospace)
        font.setPointSizeF(9.5)

        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(font)
        self.out.setFrameShape(QPlainTextEdit.NoFrame)
        self.out.setMaximumBlockCount(4000)
        self.out.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        self.prompt = QLabel()
        self.prompt.setFont(font)
        self.inp = QLineEdit()
        self.inp.setFont(font)
        self.inp.setFrame(False)
        self.inp.returnPressed.connect(self._enter)
        self.inp.installEventFilter(self)
        row = QHBoxLayout()
        row.setContentsMargins(10, 0, 10, 8)
        row.setSpacing(6)
        row.addWidget(self.prompt)
        row.addWidget(self.inp, 1)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.out, 1)
        v.addLayout(row)
        self.purplu_ran.connect(self._show_purplu)
        self.apply_colors(colors, accent)
        self._write("Windows PowerShell — 퍼플루 터미널\n", self.c["dim"])
        self._write("명령을 치고 Enter · ↑↓ 지난 명령 · Ctrl+C 멈추기 · cls 지우기\n\n", self.c["dim"])
        self._show_prompt()

    def apply_colors(self, colors: dict, accent: str):
        self.c, self.accent = colors, accent
        c = colors
        self.setStyleSheet(f"Terminal {{ background:{c['bg']}; }}")
        mono = "font-family:'Cascadia Mono','Consolas','D2Coding'; font-size:9.5pt;"   # 대화창 글꼴이 덮지 않게
        self.out.setStyleSheet(f"QPlainTextEdit {{ background:{c['bg']}; color:{c['text']}; padding:8px 10px; {mono} }}"
                               f"QScrollBar:vertical {{ width:6px; background:transparent; }}"
                               f"QScrollBar::handle:vertical {{ background:{c['line']}; border-radius:3px; }}")
        self.inp.setStyleSheet(f"QLineEdit {{ background:transparent; color:{c['text']}; {mono} }}")
        self.prompt.setStyleSheet(f"color:{accent}; font-weight:600; {mono}")

    # ---- 글쓰기 ----
    def _write(self, text: str, color: str | None = None, bold=False):
        cur = self.out.textCursor()
        cur.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color or self.c["text"]))
        fmt.setFontWeight(QFont.Bold if bold else QFont.Normal)   # 앞 글자의 굵기가 이어지지 않게
        cur.insertText(text, fmt)
        self.out.setTextCursor(cur)
        self.out.ensureCursorVisible()

    def _show_prompt(self):
        self.prompt.setText(f"PS {self.cwd}>")
        self.inp.setEnabled(True)
        self.inp.setFocus()

    # ---- 내가 친 명령 ----
    def _enter(self):
        cmd = self.inp.text()
        self.inp.clear()
        if self.proc:
            return
        self._write(f"PS {self.cwd}> ", self.accent, True)
        self._write(cmd + "\n")
        if not cmd.strip():
            return self._show_prompt()
        self.hist.append(cmd)
        self.hi = len(self.hist)
        if cmd.strip().lower() in ("cls", "clear", "clear-host"):
            self.out.clear()
            return self._show_prompt()
        self._run(cmd)

    def _run(self, cmd: str):
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.setWorkingDirectory(self.cwd)
        script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ProgressPreference='SilentlyContinue'; "
                  f"{cmd}\n; '{MARK}' + (Get-Location).Path")
        p.readyReadStandardOutput.connect(lambda: self._read(p))
        p.finished.connect(lambda code, _s: self._done(p, code))
        self.proc = p
        self._buf = ""
        self.inp.setEnabled(False)
        self.prompt.setText("실행 중…  (Ctrl+C 멈추기)")
        p.start("powershell.exe", ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])

    def _read(self, p):
        self._buf += bytes(p.readAllStandardOutput()).decode("utf-8", "replace")
        lines = self._buf.split("\n")
        self._buf = lines.pop()   # 덜 끝난 줄은 기다린다
        for line in lines:
            if line.startswith(MARK):
                self.cwd = line[len(MARK):].strip() or self.cwd
            else:
                self._write(line.rstrip("\r") + "\n")

    def _done(self, p, code):
        if self._buf:
            if self._buf.startswith(MARK):
                self.cwd = self._buf[len(MARK):].strip() or self.cwd
            else:
                self._write(self._buf + "\n")
            self._buf = ""
        if code:
            self._write(f"(끝: 코드 {code})\n", "#DC2626")
        self.proc = None
        p.deleteLater()
        self._show_prompt()

    def eventFilter(self, obj, e):
        if obj is self.inp and e.type() == e.Type.KeyPress:
            k = e.key()
            if k in (Qt.Key_Up, Qt.Key_Down) and self.hist:
                self.hi = max(0, min(len(self.hist), self.hi + (-1 if k == Qt.Key_Up else 1)))
                self.inp.setText(self.hist[self.hi] if self.hi < len(self.hist) else "")
                return True
            if k == Qt.Key_L and e.modifiers() & Qt.ControlModifier:
                self.out.clear()
                return True
        return False

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_C and e.modifiers() & Qt.ControlModifier and self.proc:
            self.proc.kill()
            self._write("^C\n", "#DC2626")
            return
        super().keyPressEvent(e)

    # ---- 퍼플루가 실행한 명령 ----
    def _show_purplu(self, cmd: str, output: str, code: int):
        self._write("퍼플루 ", self.accent, True)
        self._write(f"PS {self.cwd}> ", self.c["dim"])
        self._write(cmd.strip() + "\n", self.c["text"], True)
        if output.strip():
            self._write(output.rstrip() + "\n")
        if code:
            self._write(f"(끝: 코드 {code})\n", "#DC2626")
        self._write("\n")
