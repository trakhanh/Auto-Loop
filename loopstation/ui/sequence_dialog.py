"""Hộp thoại "Xếp lần lượt từng loop": Content → Loop1 ×60 → Loop2 ×60 → … → Loop6 ×60.

Dùng khi thư mục có nhiều clip loop (Loop1, Loop2… hoặc nen1, bg2…) muốn phát nối tiếp nhau, mỗi cái lặp N lần,
kèm clip nội dung (Content, Intro…) ở đầu / cuối. Khác với "Xen kẽ clip nền" (một clip nền xen giữa các cảnh).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QSpinBox,
    QVBoxLayout,
)

from ..core import interleave as il
from ..core.project import ClipItem
from . import icons, theme
from . import widgets as w

LAST_KEY = "sequence/last"
CONTENT_POS = [("start", "Ở đầu video (Content → Loop1 → Loop2 …)"), ("end", "Ở cuối video (… → Loop cuối → Content)"),
               ("both", "Cả đầu và cuối")]


def parse_loop_plays(text: str):
    """'60' → ('fixed', 60, 60, 0) · '50-80' → ngẫu nhiên · '10p' → loop cho đủ 10 phút. None nếu sai."""
    parsed = w.parse_plays(text)
    if parsed is None:
        return None
    mode, lo, hi = parsed
    if mode == "duration":
        return ("duration", 1, 1, float(lo)) if lo > 0 else None
    return (mode, int(lo), int(hi), 0.0) if hi > 0 else None


class SequenceDialog(QDialog):
    def __init__(self, clips: list[ClipItem], durations: dict[str, float], settings: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Xếp lần lượt từng loop")
        self.setMinimumWidth(560)
        self.clips, self.durations, self.settings = clips, durations, settings
        self.result_clips: list[ClipItem] = []
        self.contents, self.loops = il.split_loops(clips)

        intro = QLabel("Phát <b>clip nội dung</b> (tên không có chữ <i>loop</i>, ví dụ Content.mp4) rồi lần lượt "
                       "<b>từng clip loop theo tên</b> (Loop1, Loop2…), mỗi cái lặp N lần.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        last = settings.value(LAST_KEY + "/plays", "60")
        self.plays = QLineEdit(str(last))
        self.plays.setProperty("selectOnFocus", True)
        self.plays.setMaximumWidth(120)
        self.plays.setToolTip(w.PLAYS_HELP)
        self.plays.textChanged.connect(self._update)
        self.pos = QComboBox()
        for k, t in CONTENT_POS:
            self.pos.addItem(t, k)
        self.pos.setCurrentIndex(max(0, self.pos.findData(settings.value(LAST_KEY + "/pos", "start"))))
        self.pos.currentIndexChanged.connect(self._update)
        self.repeat = QSpinBox()
        self.repeat.setRange(1, 999)
        self.repeat.setSuffix(" lượt")
        self.repeat.setValue(int(settings.value(LAST_KEY + "/repeat", 1)))
        self.repeat.setToolTip("Phát hết Loop1 → … → Loop cuối rồi lặp lại cả chuỗi bao nhiêu lượt")
        self.repeat.valueChanged.connect(self._update)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.addRow("Số lần phát mỗi loop:", self.plays)
        form.addRow("Clip nội dung:", self.pos)
        form.addRow("Lặp lại cả chuỗi:", self.repeat)

        self.order = QListWidget()
        self.order.setMinimumHeight(170)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = bb.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setText("Áp dụng vào bảng")
        self.ok_btn.setObjectName("accentBtn")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Huỷ")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addLayout(form)
        lay.addWidget(QLabel("<b>Thứ tự sẽ phát</b>"))
        lay.addWidget(self.order, 1)
        lay.addWidget(self.summary)
        lay.addWidget(bb)
        self._update()

    def _parsed(self):
        return parse_loop_plays(self.plays.text().strip())

    def _build(self) -> list[ClipItem]:
        p = self._parsed()
        if p is None or not self.loops:
            return []
        return il.build_sequence(self.clips, p, self.pos.currentData(), self.repeat.value())

    def _dur(self, c: ClipItem) -> float:
        import os
        d = self.durations.get(os.path.normcase(c.path), 0.0)
        if c.plays_mode == "duration":
            return c.play_seconds
        n = (c.min + c.max) / 2 if c.plays_mode == "random" else c.count
        return d * n

    def _update(self) -> None:
        self.order.clear()
        p = self._parsed()
        bad = p is None
        self.plays.setProperty("bad", bad)
        self.plays.style().unpolish(self.plays)
        self.plays.style().polish(self.plays)
        if not self.loops:
            self.summary.setText("<span style='color:" + theme.T["warn_text"] + "'>Không có clip nào tên chứa chữ <b>loop</b> "
                                 "(hoặc nen / bg) — đặt tên kiểu Loop1.mp4, Loop2.mp4… rồi thử lại.</span>")
            self.ok_btn.setEnabled(False)
            return
        if bad:
            self.summary.setText("<span style='color:" + theme.T["warn_text"] + "'>Số lần phát chưa đúng — ví dụ 60, 50-80 hoặc 10p.</span>")
            self.ok_btn.setEnabled(False)
            return
        out = [c for c in self._build() if c.enabled]
        total = 0.0
        for c in out:
            d = self._dur(c)
            total += d
            if c.plays_mode == "duration":
                times = f"loop cho đủ {w.fmt_dur(c.play_seconds)}"
            elif c.plays_mode == "random":
                times = f"×{c.min}–{c.max}"
            else:
                times = f"×{c.count}"
            loop = il.looks_like_base(c.path)
            it = QListWidgetItem(icons.icon("repeat" if loop else "film", 14),
                                 f"{Path(c.path).name}   {times}   ≈ {w.fmt_dur(d)}")
            self.order.addItem(it)
        n_loops = len(self.loops) * self.repeat.value()
        self.summary.setText(f"{len(self.contents)} clip nội dung · {n_loops} lượt loop ({len(self.loops)} file"
                             f"{f' × {self.repeat.value()} lượt' if self.repeat.value() > 1 else ''}) · "
                             f"tổng ≈ <b>{w.fmt_dur(total)}</b> (chưa trừ crossfade).")
        self.ok_btn.setEnabled(True)

    def _accept(self) -> None:
        self.result_clips = self._build()
        if not self.result_clips:
            return
        s = self.settings
        s.setValue(LAST_KEY + "/plays", self.plays.text().strip())
        s.setValue(LAST_KEY + "/pos", self.pos.currentData())
        s.setValue(LAST_KEY + "/repeat", self.repeat.value())
        self.accept()
