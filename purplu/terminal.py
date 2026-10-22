"""대화창 위쪽에 들어가는 터미널 (PowerShell). Claude 터미널처럼: 위에 '터미널 +  ⋮ ⤢ ✕', 아래는 글 한 칸에서 바로 친다.

명령마다 PowerShell 을 새로 띄우고, 'cd' 로 옮긴 폴더는 기억해서 다음 명령에 이어 준다.
퍼플루가 run_command 로 실행한 명령도 여기에 보인다.
"""
from PySide6.QtCore import QProcess, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

MARK = "@@PURPLU_CWD@@"
BANNER = "Windows PowerShell\nCopyright (C) Microsoft Corporation. All rights reserved.\n\n"
MONO = "font-family:'Cascadia Mono','Consolas','D2Coding'; font-size:10pt;"


class Console(QPlainTextEdit):
    """프롬프트 뒤에만 쓸 수 있는 글 칸. 커서는 파란 네모."""
    submitted = Signal(str)
    interrupted = Signal()

    def __init__(self):
        super().__init__()
        self.start = 0          # 지금 입력이 시작되는 위치 (그 앞은 못 고침)
        self.busy = False
        self.hist, self.hi = [], 0
        self.caret = QColor("#2563EB")
        self.setCursorWidth(0)  # 기본 커서 대신 직접 그린다
        self.setUndoRedoEnabled(False)
        self.setFrameShape(QPlainTextEdit.NoFrame)
        self.setMaximumBlockCount(4000)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setContextMenuPolicy(Qt.NoContextMenu)

    def _input(self) -> str:
        return self.toPlainText()[self.start:]

    def _set_input(self, text: str):
        c = self.textCursor()
        c.setPosition(self.start)
        c.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        c.insertText(text)
        self.setTextCursor(c)

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        c = self.textCursor()
        if k == Qt.Key_C and mods & Qt.ControlModifier:
            if c.hasSelection():
                return super().keyPressEvent(e)   # 고른 글 복사
            return self.interrupted.emit()
        if k == Qt.Key_L and mods & Qt.ControlModifier:
            return self.submitted.emit("cls")
        if self.busy:
            return
        if c.position() < self.start or (c.hasSelection() and c.selectionStart() < self.start):
            c.movePosition(QTextCursor.End)   # 앞쪽을 누르고 쳐도 맨 끝에 쓰이게
            self.setTextCursor(c)
        if k in (Qt.Key_Return, Qt.Key_Enter):
            cmd = self._input()
            self.moveCursor(QTextCursor.End)
            if cmd.strip():
                self.hist.append(cmd)
            self.hi = len(self.hist)
            return self.submitted.emit(cmd)
        if k in (Qt.Key_Up, Qt.Key_Down):
            if self.hist:
                self.hi = max(0, min(len(self.hist), self.hi + (-1 if k == Qt.Key_Up else 1)))
                self._set_input(self.hist[self.hi] if self.hi < len(self.hist) else "")
            return
        if k in (Qt.Key_Backspace, Qt.Key_Left) and self.textCursor().position() <= self.start and not self.textCursor().hasSelection():
            return
        if k == Qt.Key_Home:
            c = self.textCursor()
            c.setPosition(self.start, QTextCursor.KeepAnchor if mods & Qt.ShiftModifier else QTextCursor.MoveAnchor)
            return self.setTextCursor(c)
        super().keyPressEvent(e)

    def insertFromMimeData(self, src):   # 붙여넣기는 한 줄로
        if self.busy:
            return
        c = self.textCursor()
        if c.position() < self.start:
            self.moveCursor(QTextCursor.End)
        self.insertPlainText(src.text().replace("\r", "").replace("\n", " "))

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.busy:
            return
        r = self.cursorRect()
        w = self.fontMetrics().horizontalAdvance("M")
        p = QPainter(self.viewport())
        col = QColor(self.caret)
        if not self.hasFocus():
            col.setAlpha(110)   # 다른 곳을 보고 있으면 옅게
        p.fillRect(QRectF(r.x(), r.y() + 1, w, r.height() - 2), col)


class Terminal(QWidget):
    purplu_ran = Signal(str, str, int)   # 퍼플루가 실행한 명령 (다른 스레드 → 화면 스레드)
    close_clicked = Signal()
    expand_clicked = Signal()

    def __init__(self, cwd: str, colors: dict, accent: str):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.home = cwd
        self.cwd, self.c, self.accent = cwd, colors, accent
        self.proc = None
        self._buf = ""

        # 머리줄: 터미널 +            ⋮ ⤢ ✕
        head = QHBoxLayout()
        head.setContentsMargins(12, 6, 6, 2)
        head.setSpacing(2)
        self.title = QLabel("터미널")
        head.addWidget(self.title)
        self.b_new = self._btn("+", "새 터미널 (지우고 처음 폴더로)", self.new_session, 15)
        head.addWidget(self.b_new)
        head.addStretch(1)
        self.b_more = self._btn("⋮", "더 보기", self._menu, 17)
        self.b_big = self._btn("⤢", "크게 / 작게", self.expand_clicked.emit, 16)
        self.b_close = self._btn("✕", "닫기 (퍼플루로)", self.close_clicked.emit, 13)
        for b in (self.b_more, self.b_big, self.b_close):
            head.addWidget(b)

        self.con = Console()
        self.con.submitted.connect(self._submit)
        self.con.interrupted.connect(self._interrupt)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addLayout(head)
        v.addWidget(self.con, 1)
        self.purplu_ran.connect(self._show_purplu)
        self.apply_colors(colors, accent)
        self._write(BANNER)
        self._prompt()

    def _btn(self, text, tip, fn, size):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setFixedSize(28, 28)
        b.setCursor(Qt.PointingHandCursor)
        b.setProperty("sz", size)
        b.clicked.connect(fn)
        return b

    def apply_colors(self, colors: dict, accent: str):
        self.c, self.accent = colors, accent
        c = colors
        self.setStyleSheet(f"Terminal {{ background:{c['bg']}; }}")
        self.title.setStyleSheet(f"color:{c['dim']}; font-size:10.5pt;")
        for b in (self.b_new, self.b_more, self.b_big, self.b_close):
            b.setStyleSheet(f"QPushButton {{ background:transparent; border:none; border-radius:7px; color:{c['text']}; font-size:{b.property('sz')}pt; }}"
                            f"QPushButton:hover {{ background:{c['card']}; }}")
        self.con.setStyleSheet(f"QPlainTextEdit {{ background:{c['bg']}; color:{c['text']}; padding:4px 8px; border:none; {MONO} }}"
                               f"QScrollBar:vertical {{ width:6px; background:transparent; }}"
                               f"QScrollBar::handle:vertical {{ background:{c['line']}; border-radius:3px; }}")
        self.con.viewport().update()

    # ---- 글쓰기 ----
    def _write(self, text: str, color: str | None = None):
        cur = self.con.textCursor()
        cur.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color or self.c["text"]))
        fmt.setFontWeight(QFont.Normal)
        cur.insertText(text, fmt)
        self.con.setTextCursor(cur)
        self.con.ensureCursorVisible()

    def _prompt(self):
        self._write(f"PS {self.cwd}> ")
        self.con.start = len(self.con.toPlainText())
        self.con.busy = False
        self.con.viewport().update()

    def focus(self):
        self.con.setFocus()
        self.con.moveCursor(QTextCursor.End)

    # ---- 내가 친 명령 ----
    def _submit(self, cmd: str):
        self._write("\n")
        if not cmd.strip():
            return self._prompt()
        if cmd.strip().lower() in ("cls", "clear", "clear-host"):
            self.con.clear()
            return self._prompt()
        self._run(cmd)

    def _run(self, cmd: str):
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.setWorkingDirectory(self.cwd)
        script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ProgressPreference='SilentlyContinue'; "
                  f"{cmd}\n; '{MARK}' + (Get-Location).Path")
        p.readyReadStandardOutput.connect(lambda: self._read(p))
        p.finished.connect(lambda code, _s: self._done(p, code))
        self.proc, self._buf = p, ""
        self.con.busy = True
        self.con.viewport().update()
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
        if self.proc is p:
            self.proc = None
        p.deleteLater()
        self._write("\n")
        self._prompt()

    def _interrupt(self):
        if self.proc:
            self.proc.kill()
            self._write("^C\n", "#DC2626")
        else:
            self._write("^C\n\n")
            self._prompt()

    def new_session(self):
        if self.proc:
            self.proc.kill()
            self.proc = None
        self.cwd = self.home
        self.con.clear()
        self._write(BANNER)
        self._prompt()
        self.focus()

    def _menu(self):
        m = QMenu(self)
        m.addAction("화면 지우기", lambda: (self.con.clear(), self._prompt()))
        m.addAction("모두 복사", lambda: QGuiApplication.clipboard().setText(self.con.toPlainText()))
        m.addAction("새 터미널", self.new_session)
        m.exec(self.b_more.mapToGlobal(self.b_more.rect().bottomLeft()))

    # ---- 퍼플루가 실행한 명령 ----
    def _show_purplu(self, cmd: str, output: str, code: int):
        """치던 줄은 그대로 두고, 그 위에 퍼플루가 실행한 명령과 결과를 끼워 넣는다."""
        typed = "" if self.con.busy else self.con._input()
        if not self.con.busy:   # 지금 프롬프트 줄을 지우고
            text = self.con.toPlainText()
            cur = self.con.textCursor()
            cur.setPosition(text.rfind("\n", 0, self.con.start) + 1)
            cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            cur.removeSelectedText()
        self._write(f"PS {self.cwd}> ")
        self._write(cmd.strip(), self.accent)
        self._write("    # 퍼플루\n", self.c["dim"])
        if output.strip():
            self._write(output.rstrip() + "\n")
        self._write("\n")
        if not self.con.busy:   # 프롬프트와 치던 글을 다시
            self._prompt()
            self._write(typed)
