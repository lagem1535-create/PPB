"""퍼플루 꾸미기 창 (/custom): 눈 · 모자 · 더듬이 · 소품을 골라 바로 바꾼다. 왼쪽은 움직이는 미리보기."""
import random
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QToolButton,
                               QVBoxLayout, QWidget)

from . import config, face

SECTIONS = [("eyes", "눈", face.EYES), ("hat", "모자", face.HATS), ("antenna", "더듬이", face.ANTENNAS),
            ("extra", "소품", face.EXTRAS)]
KEYS = {"eyes": "face_eyes", "hat": "face_hat", "antenna": "face_antenna", "extra": "face_extra", "hat_color": "face_hat_color"}


class Preview(QWidget):
    """움직이는 미리보기 (눈 깜빡임·숨쉬기 그대로)."""

    def __init__(self, bg):
        super().__init__()
        self.v = face.still()
        self.v._blink = time.monotonic() + 2
        self.bg = bg
        self.setMinimumSize(300, 240)
        self._t = QTimer(self, timeout=self._tick)
        self._t.start(33)

    def _tick(self):
        now = time.monotonic()
        if now > self.v._blink + 0.2 and random.random() < 0.01:
            self.v._blink = now
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        face.draw_face(p, self.width(), self.height(), self.v, face.options(), bg=self.bg)
        p.end()


class CustomizeWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("퍼플루 꾸미기")
        light = config.settings().get("theme") == "light"
        self.c = (dict(bg="#FAF8FF", panel="#FFFFFF", text="#1F1235", dim="#71717A", line="#E9E5F5", face="#F3EEFF")
                  if light else dict(bg="#120B22", panel="#1B1230", text="#F5F3FF", dim="#A1A1AA", line="#2E1F4F", face="#000000"))
        c = self.c
        self.accent = config.settings().get("chat_color") or config.settings().get("color") or "#3B82F6"
        self.setStyleSheet(f"CustomizeWindow, QWidget#page {{ background:{c['bg']}; }} QLabel {{ color:{c['text']}; background:transparent; }}"
                           f"QScrollArea {{ border:none; background:transparent; }}")
        self.resize(900, 600)

        # 왼쪽: 미리보기 + 랜덤·처음대로
        left = QVBoxLayout()
        frame = QFrame()
        frame.setStyleSheet(f"QFrame {{ background:{c['face']}; border-radius:18px; }}")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        self.preview = Preview(c["face"])
        fl.addWidget(self.preview)
        left.addWidget(frame, 1)
        row = QHBoxLayout()
        for text, fn in (("🎲 랜덤", self._random), ("처음대로", self._reset)):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['line']}; border-radius:10px; padding:8px 14px; font-weight:600; }}"
                            f"QPushButton:hover {{ border-color:{self.accent}; }}")
            b.clicked.connect(fn)
            row.addWidget(b)
        left.addLayout(row)
        tip = QLabel("고르면 바로 바뀌어요 (대화창의 퍼플루도 같이).")
        tip.setStyleSheet(f"color:{c['dim']}; font-size:9pt;")
        left.addWidget(tip)

        # 오른쪽: [눈] [모자] [더듬이] [소품] + 고르는 칸
        right = QVBoxLayout()
        seg = QHBoxLayout()
        self.seg_btns = []
        for i, (_, title, _) in enumerate(SECTIONS):
            b = QPushButton(title)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self._section(i))
            self.seg_btns.append(b)
            seg.addWidget(b)
        seg.addStretch(1)
        right.addLayout(seg)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        right.addWidget(self.scroll, 1)
        self.colors_row = QHBoxLayout()
        self.colors_box = QWidget()
        self.colors_box.setLayout(self.colors_row)
        right.addWidget(self.colors_box)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(16)
        lay.addLayout(left, 4)
        lay.addLayout(right, 6)
        self._sec = 0
        self._section(0)

    # ---- 고르기 ----
    def _section(self, i):
        self._sec = i
        c = self.c
        for k, b in enumerate(self.seg_btns):
            on = k == i
            b.setStyleSheet(f"QPushButton {{ background:{self.accent if on else c['panel']}; color:{'white' if on else c['text']};"
                            f" border:1px solid {self.accent if on else c['line']}; border-radius:14px; padding:6px 16px; font-weight:600; }}")
        key, _, opts = SECTIONS[i]
        cur = face.options()[key]
        page = QWidget()
        page.setObjectName("page")
        grid = QGridLayout(page)
        grid.setSpacing(10)
        for n, (val, name) in enumerate(opts):
            b = QToolButton()
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setText(name)
            b.setIcon(QIcon(face.thumbnail(face.options(**{key: val}), 128, 100, c["face"])))
            b.setIconSize(QSize(128, 100))
            b.setCursor(Qt.PointingHandCursor)
            on = val == cur
            b.setStyleSheet(f"QToolButton {{ background:{c['panel']}; color:{c['text']}; border:{'3px' if on else '1px'} solid {self.accent if on else c['line']};"
                            f" border-radius:14px; padding:6px; font-size:10pt; font-weight:{'700' if on else '500'}; }}"
                            f"QToolButton:hover {{ border-color:{self.accent}; }}")
            b.clicked.connect(lambda _=False, key=key, val=val: self._pick(key, val))
            grid.addWidget(b, n // 3, n % 3)
        grid.setRowStretch(len(opts) // 3 + 1, 1)
        self.scroll.setWidget(page)
        self._colors(key == "hat")

    def _colors(self, show):
        while self.colors_row.count():
            w = self.colors_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.colors_box.setVisible(show)
        if not show:
            return
        lab = QLabel("모자 색")
        lab.setStyleSheet(f"color:{self.c['dim']};")
        self.colors_row.addWidget(lab)
        cur = face.options()["hat_color"]
        for col in face.HAT_COLORS:
            b = QPushButton("기본" if not col else "")
            b.setFixedSize(46 if not col else 28, 28)
            b.setCursor(Qt.PointingHandCursor)
            on = col == cur
            b.setStyleSheet(f"QPushButton {{ background:{col or self.c['panel']}; color:{self.c['text']}; font-size:8.5pt;"
                            f" border:{'3px' if on else '1px'} solid {self.accent if on else self.c['line']}; border-radius:14px; }}")
            b.clicked.connect(lambda _=False, col=col: self._pick("hat_color", col))
            self.colors_row.addWidget(b)
        self.colors_row.addStretch(1)

    def _pick(self, key, val):
        config.save_settings(**{KEYS[key]: val})
        self._section(self._sec)   # 고른 칸 표시·작은 그림 다시

    def _random(self):
        config.save_settings(**{KEYS[k]: random.choice(opts)[0] for k, _, opts in SECTIONS},
                             face_hat_color=random.choice(face.HAT_COLORS))
        self._section(self._sec)

    def _reset(self):
        config.save_settings(face_eyes="basic", face_hat="none", face_antenna="none", face_extra="none", face_hat_color="")
        self._section(self._sec)

    def open(self):
        self._section(self._sec)
        self.show()
        self.raise_()
        self.activateWindow()
