"""Cửa sổ "Thứ tự sẽ xuất" khi trộn ngẫu nhiên: 40–50 clip vẫn đọc rõ — mỗi clip một dòng (số thứ tự, tên, số lần
phát, bắt đầu ở phút nào, dài bao lâu), có Trộn lại / Dùng thứ tự này ngay tại đây."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..core.render_queue import fmt_len
from . import icons, theme
from . import widgets as w


class ShuffleOrderDialog(QDialog):
    """`provider(lượt)` → {"title", "rows": [(tên, số lần, giây bắt đầu, giây dài, đường dẫn)], "order": [chỉ số clip],
    "rounds": số lượt có thứ tự riêng} (None khi chưa tính được). `reshuffle()` đổi số mầm; `keep(order)` chép vào bảng."""

    def __init__(self, provider: Callable[[int], dict | None], reshuffle: Callable[[], None],
                 keep: Callable[[list[int]], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thứ tự sẽ xuất (trộn ngẫu nhiên)")
        self.resize(780, 680)
        self.provider, self.reshuffle, self.keep = provider, reshuffle, keep
        self._order: list[int] = []
        self._icons: dict[str, QIcon] = {}  # ảnh xem trước theo file (cache dùng chung với bảng clip)
        self._waiting: dict[str, list[int]] = {}
        self.thumbs = w.ThumbLoader(self)
        self.thumbs.image.connect(self._on_thumb)
        self.finished.connect(lambda *_: self.thumbs.shutdown())

        self.title = QLabel()
        self.title.setObjectName("updateTitle")
        self.title.setWordWrap(True)
        self.round = QComboBox()
        self.round.currentIndexChanged.connect(lambda *_: self._fill())
        self.round_label = QLabel("Lượt:")
        head = QHBoxLayout()
        head.addWidget(self.title, 1)
        head.addWidget(self.round_label)
        head.addWidget(self.round)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Clip", "Số lần", "Phát lúc", "Dài"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(w.ThumbLoader.H + 14)  # đủ cao cho ảnh xem trước
        self.table.setIconSize(QSize(w.ThumbLoader.W, w.ThumbLoader.H))
        self.table.setShowGrid(False)
        self.table.horizontalHeaderItem(1).setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in (0, 2, 3, 4):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        note = w.muted("Xuất ra đúng thứ tự này (cùng số mầm luôn ra cùng thứ tự). Giờ bắt đầu là ước tính — chỗ nối "
                       "có crossfade sẽ sớm hơn vài giây.")
        note.setWordWrap(True)

        again = QPushButton("Trộn lại")
        again.setObjectName("pill")
        again.setIcon(icons.icon("refresh", 13))
        again.clicked.connect(self._again)
        use = QPushButton("Dùng thứ tự này")
        use.setObjectName("accentBtn")
        use.setToolTip("Chép thứ tự vào bảng (chuyển sang Theo thứ tự trong bảng) để sửa tay tiếp — Ctrl+Z quay lại")
        use.clicked.connect(self._use)
        close = QPushButton("Đóng")
        close.clicked.connect(self.reject)
        bb = QHBoxLayout()
        bb.addWidget(again)
        bb.addStretch(1)
        bb.addWidget(close)
        bb.addWidget(use)
        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SP["md"])
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(note)
        lay.addLayout(bb)
        self._reload()

    def _reload(self) -> None:
        data = self.provider(0)
        rounds = (data or {}).get("rounds", 1)
        keep = self.round.currentIndex()
        self.round.blockSignals(True)
        self.round.clear()
        for r in range(rounds):
            self.round.addItem(f"Lượt {r + 1}", r)
        self.round.setCurrentIndex(max(0, min(keep, rounds - 1)))
        self.round.blockSignals(False)
        for wd in (self.round, self.round_label):
            wd.setVisible(rounds > 1)
        self._fill()

    def _fill(self) -> None:
        data = self.provider(max(0, self.round.currentIndex()))
        rows = (data or {}).get("rows", [])
        self._order = (data or {}).get("order", [])
        self.title.setText((data or {}).get("title", "Chưa tính được thứ tự."))
        self.table.setRowCount(len(rows))
        self._waiting.clear()
        want: list[str] = []
        accent, muted = theme.qcolor("accent_text"), theme.qcolor("text_muted")
        for i, (name, n, start, dur, path) in enumerate(rows):
            cells = [str(i + 1), name, f"×{n}" if n > 1 else "1", f"{fmt_len(start)} → {fmt_len(start + dur)}",
                     fmt_len(dur)]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c != 1:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 0:
                    it.setForeground(muted)
                if c == 2 and n > 1:
                    it.setForeground(accent)
                if c == 1:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                    it.setToolTip(path)
                    if path in self._icons:
                        it.setIcon(self._icons[path])
                    else:
                        self._waiting.setdefault(path, []).append(i)
                        if path not in want:
                            want.append(path)
                self.table.setItem(i, c, it)
        if want:
            self.thumbs.request(want)

    def _on_thumb(self, path: str, img) -> None:
        if img.isNull():
            return
        icon = self._icons[path] = QIcon(QPixmap.fromImage(img))
        for row in self._waiting.pop(path, []):
            it = self.table.item(row, 1)
            if it is not None:
                it.setIcon(icon)

    def _again(self) -> None:
        self.reshuffle()
        self._reload()

    def _use(self) -> None:
        if self._order:
            self.keep(self._order)
        self.accept()
