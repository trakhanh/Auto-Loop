"""Dòng chọn nhạc một hàng, nằm ngay trên dòng thời gian:

    ♪ Nhạc chạy từ clip [5 · Loop1 · 0:40 ▾] tới [hết video ▾] · bài đầu [theo playlist ▾]

"Clip N" = khối thứ N trên làn CLIP (lần phát, kể cả bảng lặp cả chuỗi). Thay cho 7 cách chỉnh cũ (ô Nhạc từng clip,
Nhạc vào lúc, Chọn clip…, kéo mép, chuột phải, Alt + quét). Tay nắm ♪ trên dòng thời gian đổi cùng giá trị "từ clip".
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QWidget

from . import icons
from .widgets import fmt_dur

MAX_ITEMS = 60  # bảng lặp dài: liệt kê 60 lần phát đầu; xa hơn thì kéo tay nắm ♪ trên dòng thời gian


class MusicRangeBar(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        ic = QLabel()
        icons.bind(ic, "music", 14, "accent_text")
        ic.setFixedSize(QSize(14, 14))
        lay.addWidget(ic)
        self.start, self.end, self.first = QComboBox(), QComboBox(), QComboBox()
        for cb, tip in ((self.start, "Nhạc vào ở đầu clip này (đếm theo khối trên dòng thời gian, kể cả khi lặp nhiều "
                                     "vòng). Kéo tay nắm ♪ trên dòng thời gian cũng được."),
                        (self.end, "Nhạc nhỏ dần rồi tắt ở cuối clip này — hoặc chạy tới hết video"),
                        (self.first, "Bài phát đầu tiên khi nhạc vào, rồi tiếp các bài sau theo playlist")):
            cb.setToolTip(tip)
            cb.setObjectName("rangeCombo")  # theme.py: viền màu nhấn + mũi tên — nhìn ra là bấm chọn được
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(14)
            cb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            cb.currentIndexChanged.connect(self._on_changed)
        for text, wdg in (("Nhạc chạy từ", self.start), ("tới", self.end), ("· bài đầu", self.first)):
            lab = QLabel(text)
            lab.setObjectName("muted")
            lay.addWidget(lab)
            lay.addWidget(wdg)
        lay.addStretch(1)
        self._values = (0, 0, "")
        self._quiet = False
        self._blocks: list[tuple[str, float, float]] = []
        self._tracks: list[tuple[str, str]] = []
        self._sync()

    # ----- dữ liệu -----
    def values(self) -> tuple[int, int, str]:
        return self._values

    def set_values(self, start: int, end: int, first: str, emit: bool = False) -> None:
        self._values = (max(0, int(start)), max(0, int(end)), first or "")
        self._sync()
        if emit:
            self.changed.emit()

    def set_blocks(self, blocks: list[tuple[str, float, float]]) -> None:
        """Các khối trên làn CLIP [(tên, bắt đầu, kết thúc)] theo thứ tự — đánh số 1, 2, 3…"""
        self._blocks = list(blocks)
        self._sync()

    def set_tracks(self, tracks: list[tuple[str, str]]) -> None:
        """Các bài trong playlist [(đường dẫn, tên)]."""
        self._tracks = list(tracks)
        self._sync()

    # ----- bên trong -----
    def _sync(self) -> None:
        start, end, first = self._values
        self._quiet = True
        try:
            self._fill(self.start, [(0, "đầu video")] + [
                (k + 1, f"{k + 1} · {name} · {fmt_dur(a)}") for k, (name, a, _b) in enumerate(self._blocks[:MAX_ITEMS])],
                start, lambda n: f"{n} · (lần phát thứ {n})")
            self._fill(self.end, [(0, "hết video")] + [  # chỉ các clip từ clip bắt đầu trở đi
                (k + 1, f"hết clip {k + 1} · {name}") for k, (name, _a, _b) in enumerate(self._blocks[:MAX_ITEMS])
                if k + 1 >= max(1, start)],
                end, lambda n: f"hết clip {n}")
            self._fill(self.first, [("", "theo playlist")] + [
                (path, f"Bài {k + 1} · {name}") for k, (path, name) in enumerate(self._tracks)],
                first, lambda p: "bài đã chọn (không còn trong playlist)")
        finally:
            self._quiet = False

    @staticmethod
    def _fill(cb: QComboBox, items: list, current, missing) -> None:
        cb.blockSignals(True)
        cb.clear()
        for data, text in items:
            cb.addItem(text, data)
        if cb.findData(current) < 0:  # giá trị ngoài danh sách (lần phát thứ 80, bài đã xoá): vẫn hiện, không đổi ngầm
            cb.addItem(missing(current), current)
        cb.setCurrentIndex(cb.findData(current))
        cb.blockSignals(False)

    def _on_changed(self, *_) -> None:
        if self._quiet:
            return
        start, end = int(self.start.currentData() or 0), int(self.end.currentData() or 0)
        if end and start and end < start:
            end = 0  # dừng trước chỗ bắt đầu thì vô nghĩa: chạy tới hết video (ô "tới" hiện đúng như vậy)
        self._values = (start, end, str(self.first.currentData() or ""))
        self._sync()  # ô "tới" chỉ liệt kê các clip sau clip bắt đầu
        self.changed.emit()
