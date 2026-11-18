"""Hộp "Nhạc ở clip nào" (trang Nhạc → Chọn clip…): gõ nhanh 5-10 hoặc 2-3, 7-8, hoặc tick từng clip."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from ..core.clip_ranges import parse_ranges, ranges_input, ranges_text
from . import icons, theme


class ClipMusicDialog(QDialog):
    def __init__(self, names: list[str], flags: list[bool], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nhạc ở clip nào")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        intro = QLabel("Chọn các clip có <b>nhạc nền</b>. Clip không chọn: nhạc ngừng, tới clip có chọn thì sang bài kế "
                       "(phát từ đầu). Số clip = số thứ tự dòng trong bảng clip trang Video.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Gõ nhanh"))
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText("vd 5-10  ·  2-3, 7-8  ·  5- (từ clip 5 tới hết)")
        self.ranges.setClearButtonEnabled(True)
        row.addWidget(self.ranges, 1)
        self.all_btn = QPushButton("Tất cả")
        self.all_btn.setObjectName("pill")
        self.none_btn = QPushButton("Bỏ hết")
        self.none_btn.setObjectName("pill")
        row.addWidget(self.all_btn)
        row.addWidget(self.none_btn)
        lay.addLayout(row)
        self.state = QLabel("")
        self.state.setObjectName("muted")
        lay.addWidget(self.state)
        self.list = QListWidget()
        self.list.setMinimumHeight(240)
        self.items: list[QListWidgetItem] = []
        for k, name in enumerate(names):
            it = QListWidgetItem(icons.icon("music", 14), f"{k + 1}  ·  {name}")
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            it.setCheckState(Qt.CheckState.Checked if k < len(flags) and flags[k] else Qt.CheckState.Unchecked)
            self.list.addItem(it)
            self.items.append(it)
        lay.addWidget(self.list, 1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Áp dụng")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("Huỷ")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

        self._sync = False
        self.ranges.textChanged.connect(self._on_typed)
        self.list.itemChanged.connect(lambda *_: self._on_ticked())
        self.all_btn.clicked.connect(lambda: self._set_all(True))
        self.none_btn.clicked.connect(lambda: self._set_all(False))
        self._on_ticked()

    def flags(self) -> list[bool]:
        return [it.checkState() == Qt.CheckState.Checked for it in self.items]

    def _set_flags(self, flags: list[bool]) -> None:
        self._sync = True
        try:
            for it, on in zip(self.items, flags):
                it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        finally:
            self._sync = False

    def _set_all(self, on: bool) -> None:
        self._set_flags([on] * len(self.items))
        self._on_ticked()

    def _on_typed(self, text: str) -> None:
        if self._sync:
            return
        flags = parse_ranges(text, len(self.items))
        if flags is None:
            self.state.setText(f"<span style='color:{theme.css_color('warn_text')}'>Chưa hiểu — gõ số clip từ 1 đến "
                               f"{len(self.items)}, ví dụ 5-10 hoặc 2-3, 7-8</span>")
            return
        self._set_flags(flags)
        self.state.setText(f"Nhạc ở: <b>{ranges_text(flags)}</b>")

    def _on_ticked(self) -> None:
        if self._sync:
            return
        flags = self.flags()
        self._sync = True
        try:
            self.ranges.setText(ranges_input(flags))
        finally:
            self._sync = False
        self.state.setText(f"Nhạc ở: <b>{ranges_text(flags)}</b>")
