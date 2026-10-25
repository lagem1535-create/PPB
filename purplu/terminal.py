"""대화창 위쪽에 들어가는 터미널 (PowerShell). Claude 터미널처럼: 위에 '터미널  터미널 2 +  ⋮ ⤢ ✕', 아래는 글 한 칸에서 바로 친다.

명령마다 PowerShell 을 새로 띄우고, 'cd' 로 옮긴 폴더는 기억해서 다음 명령에 이어 준다.
퍼플루가 run_command 로 실행한 명령도 여기에 보인다.
"""
import os

from PySide6.QtCore import QProcess, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

MARK = "@@PURPLU_CWD@@"
CURRENT_CWD = [os.path.expanduser("~")]   # 지금 고른 터미널 탭의 폴더 (터미널 에이전트가 여기서 일한다)
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


class Session(QWidget):
    """터미널 탭 하나: 글 칸 + 폴더 + 실행 중인 명령."""

    def __init__(self, cwd: str, term):
        super().__init__()
        self.t = term
        self.home = self.cwd = cwd
        self.proc = None
        self._buf = ""
        self.con = Console()
        self.con.submitted.connect(self._submit)
        self.con.interrupted.connect(self._interrupt)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.con)
        self.apply_colors()
        self._write(BANNER)
        self._prompt()

    @property
    def c(self):
        return self.t.c

    def apply_colors(self):
        c = self.c
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
        CURRENT_CWD[0] = self.cwd
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
        if cmd.strip().lower() == "exit":   # exit 하면 이 탭을 닫는다
            return self.t.close_session(self)
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

    def stop(self):
        if self.proc:
            self.proc.kill()
            self.proc = None

    # ---- 터미널 에이전트 (한 줄씩 흘려 보이기) ----
    def ext(self, kind: str, data: str):
        if kind == "start":
            self._ext_typed = "" if self.con.busy else self.con._input()
            if not self.con.busy:   # 지금 프롬프트 줄을 지우고
                text = self.con.toPlainText()
                cur = self.con.textCursor()
                cur.setPosition(text.rfind("\n", 0, self.con.start) + 1)
                cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
                cur.removeSelectedText()
            self.con.busy = True
            cmd, _, note = data.partition("    # ")
            self._write(f"PS {self.cwd}> ")
            self._write(cmd, self.t.accent)
            self._write(f"    # {note}\n" if note else "\n", self.c["dim"])
        elif kind == "line":
            self._write(data + "\n")
        elif kind == "end":
            if str(data) not in ("0", ""):
                self._write(f"(끝: 코드 {data})\n", "#DC2626")
            self._write("\n")
            self._prompt()
            self._write(getattr(self, "_ext_typed", ""))

    # ---- 퍼플루가 실행한 명령 ----
    def show_purplu(self, cmd: str, output: str, code: int):
        """치던 줄은 그대로 두고, 그 위에 퍼플루가 실행한 명령과 결과를 끼워 넣는다."""
        typed = "" if self.con.busy else self.con._input()
        if not self.con.busy:   # 지금 프롬프트 줄을 지우고
            text = self.con.toPlainText()
            cur = self.con.textCursor()
            cur.setPosition(text.rfind("\n", 0, self.con.start) + 1)
            cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            cur.removeSelectedText()
        self._write(f"PS {self.cwd}> ")
        self._write(cmd.strip(), self.t.accent)
        self._write("    # 퍼플루\n", self.c["dim"])
        if output.strip():
            self._write(output.rstrip() + "\n")
        self._write("\n")
        if not self.con.busy:   # 프롬프트와 치던 글을 다시
            self._prompt()
            self._write(typed)


class Terminal(QWidget):
    """머리줄: [터미널] [터미널 2] … +            ⋮ ⤢ ✕  /  아래: 고른 탭의 글 칸."""
    purplu_ran = Signal(str, str, int)   # 퍼플루가 실행한 명령 (다른 스레드 → 화면 스레드)
    agent_event = Signal(str, str)       # 터미널 에이전트: start · line · end
    close_clicked = Signal()
    expand_clicked = Signal()

    def __init__(self, cwd: str, colors: dict, accent: str):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.home, self.c, self.accent = cwd, colors, accent
        self.sessions: list[Session] = []
        self._count = 0

        head = QHBoxLayout()
        head.setContentsMargins(8, 6, 6, 2)
        head.setSpacing(2)
        self.tabrow = QHBoxLayout()
        self.tabrow.setSpacing(2)
        head.addLayout(self.tabrow)
        self.b_new = self._btn("+", "새 터미널", self.new_session, 15)
        head.addWidget(self.b_new)
        head.addStretch(1)
        self.b_more = self._btn("⋮", "더 보기", self._menu, 17)
        self.b_big = self._btn("⤢", "크게 / 작게", self.expand_clicked.emit, 16)
        self.b_close = self._btn("✕", "닫기 (퍼플루로)", self.close_clicked.emit, 13)
        for b in (self.b_more, self.b_big, self.b_close):
            head.addWidget(b)

        from PySide6.QtWidgets import QStackedWidget
        self.stack = QStackedWidget()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addLayout(head)
        v.addWidget(self.stack, 1)
        self.purplu_ran.connect(self._show_purplu)
        self.agent_event.connect(lambda k, d: self.cur.ext(k, d))
        self.apply_colors(colors, accent)
        self.new_session()

    @property
    def cur(self) -> Session:
        return self.stack.currentWidget()

    @property
    def con(self):   # 예전 이름 (대화창이 term.con 으로 부르던 것)
        return self.cur.con

    def focus(self):
        self.cur.focus()

    def _btn(self, text, tip, fn, size):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setFixedSize(28, 28)
        b.setCursor(Qt.PointingHandCursor)
        b.setProperty("sz", size)
        b.clicked.connect(lambda _=False: fn())
        return b

    def apply_colors(self, colors: dict, accent: str):
        self.c, self.accent = colors, accent
        c = colors
        self.setStyleSheet(f"Terminal {{ background:{c['bg']}; }}")
        for b in (self.b_new, self.b_more, self.b_big, self.b_close):
            b.setStyleSheet(f"QPushButton {{ background:transparent; border:none; border-radius:7px; color:{c['text']}; font-size:{b.property('sz')}pt; }}"
                            f"QPushButton:hover {{ background:{c['card']}; }}")
        for s in self.sessions:
            s.apply_colors()
        self._tabs()

    # ---- 탭 ----
    def new_session(self):
        self._count += 1
        s = Session(self.home, self)
        s.title = "터미널" if self._count == 1 else f"터미널 {self._count}"
        self.sessions.append(s)
        self.stack.addWidget(s)
        self.stack.setCurrentWidget(s)
        self._tabs()
        s.focus()
        return s

    def close_session(self, s):
        s.stop()
        if len(self.sessions) == 1:   # 마지막 탭은 닫지 않고 새로
            self.sessions.remove(s)
            self.stack.removeWidget(s)
            s.deleteLater()
            self._count = 0
            return self.new_session()
        i = self.sessions.index(s)
        self.sessions.remove(s)
        self.stack.removeWidget(s)
        s.deleteLater()
        self.stack.setCurrentWidget(self.sessions[max(0, i - 1)])
        self._tabs()
        self.cur.focus()

    def _switch(self, s):
        self.stack.setCurrentWidget(s)
        CURRENT_CWD[0] = s.cwd
        self._tabs()
        s.focus()

    def _tabs(self):
        """탭 글자 단추를 다시 만든다. 고른 탭은 진하게, 탭이 둘 이상이면 고른 탭에 × ."""
        while self.tabrow.count():
            w = self.tabrow.takeAt(0).widget()
            if w:
                w.deleteLater()
        c = self.c
        many = len(self.sessions) > 1
        for s in self.sessions:
            on = s is self.cur
            b = QPushButton(s.title + ("  ×" if on and many else ""))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip("누르면 이 터미널로" + (" · 한 번 더 누르면 닫기" if on and many else ""))
            b.setStyleSheet(f"QPushButton {{ background:{c['card'] if on and many else 'transparent'}; border:none; border-radius:7px;"
                            f" color:{c['text'] if on else c['dim']}; font-size:10.5pt; padding:3px 8px; }}"
                            f"QPushButton:hover {{ background:{c['card']}; }}")
            b.clicked.connect(lambda _=False, s=s, on=on: self.close_session(s) if on and many else self._switch(s))
            self.tabrow.addWidget(b)

    def _menu(self):
        m = QMenu(self)
        m.addAction("새 터미널", self.new_session)
        m.addAction("이 터미널 닫기", lambda: self.close_session(self.cur))
        m.addSeparator()
        m.addAction("화면 지우기", lambda: (self.cur.con.clear(), self.cur._prompt()))
        m.addAction("모두 복사", lambda: QGuiApplication.clipboard().setText(self.cur.con.toPlainText()))
        m.exec(self.b_more.mapToGlobal(self.b_more.rect().bottomLeft()))

    def _show_purplu(self, cmd: str, output: str, code: int):
        self.cur.show_purplu(cmd, output, code)
