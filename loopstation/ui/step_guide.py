"""Thanh hướng dẫn từng bước (dùng chung cho trang Video / Nhạc / Xuất): đang ở bước mấy + việc cần làm tiếp."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from . import icons
from .widgets import ElidedLabel


class StepGuide(QWidget):
    goTo = Signal(int)  # chỉ số trang

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stepGuide")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 5, 16, 5)
        lay.setSpacing(6)
        self._steps_box = QHBoxLayout()
        self._steps_box.setSpacing(4)
        lay.addLayout(self._steps_box, 0)
        lay.addSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedWidth(18)
        self.hint = ElidedLabel("")  # một dòng, dài quá thì rút gọn; câu đầy đủ nằm trong tooltip
        self.hint.setObjectName("stepHint")
        lay.addWidget(self.icon)
        lay.addWidget(self.hint, 1)
        self._buttons: list[QWidget] = []

    def set_state(self, steps: list[tuple[str, int, bool]], current: int, hint: str, ok: bool = False,
                  tip: str = "") -> None:
        """steps: (tên, chỉ số trang, đã xong) theo thứ tự; current: trang đang mở; hint: việc cần làm (một dòng,
        chữ thường); tip: câu hướng dẫn đầy đủ (HTML) hiện khi rê chuột."""
        key = (tuple(steps), current)
        if key != getattr(self, "_key", None):  # chỉ dựng lại các nút bước khi bước / trạng thái thật sự đổi
            self._key = key
            self._rebuild(steps, current)
        self._set_hint(hint, ok, tip)

    def _rebuild(self, steps: list[tuple[str, int, bool]], current: int) -> None:
        for b in self._buttons:  # ẩn + tách ngay: nút cũ không được vẽ chồng trong lúc chờ xoá
            b.hide()
            b.setParent(None)
            b.deleteLater()
        self._buttons = []
        while self._steps_box.count():
            self._steps_box.takeAt(0)
        for k, (name, page, done) in enumerate(steps):
            if k:
                arrow = QLabel("›")
                arrow.setObjectName("stepArrow")
                self._steps_box.addWidget(arrow)
                self._buttons.append(arrow)
            b = QPushButton(f"{k + 1}. {name}")
            b.setObjectName("stepPill")
            if done and page != current:
                b.setIcon(icons.icon("check", 12, "success_text"))
                b.setIconSize(QSize(12, 12))
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            b.setProperty("state", "current" if page == current else ("done" if done else "todo"))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip("Bấm để chuyển tới bước này")
            b.clicked.connect(lambda _=False, p=page: self.goTo.emit(p))
            self._steps_box.addWidget(b)
            self._buttons.append(b)

    def _set_hint(self, hint: str, ok: bool, tip: str = "") -> None:
        if ok != getattr(self, "_ok", None):
            self._ok = ok
            self.icon.setPixmap(icons.pixmap("check" if ok else "arrow_right", 15, "success_text" if ok else "accent_text"))
        if (hint, tip) != (self.hint.full_text(), getattr(self, "_tip", "")):
            self._tip = tip
            self.hint.set_full_text(hint, tip)
