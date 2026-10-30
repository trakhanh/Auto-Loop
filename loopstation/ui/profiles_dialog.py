"""Quản lý hồ sơ kênh: xem từng hồ sơ có gì, áp dụng, cập nhật từ dự án đang mở, đổi tên, xoá, xuất / nhập file."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..core import profiles as prof
from . import icons, theme
from . import widgets as w
from .help_hub import badge
from .share_io import export_file, import_file, read_profiles, write_profiles


class ProfileDialog(QDialog):
    """`capture(name)` → hồ sơ mới từ dự án đang mở; `on_apply(hồ sơ)` → áp vào dự án. `choice`: hồ sơ vừa áp."""

    def __init__(self, settings: QSettings, capture: Callable[[str], dict], on_apply: Callable[[dict], None],
                 current: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hồ sơ kênh")
        self.resize(760, 620)
        self.settings, self.capture, self.on_apply, self.current = settings, capture, on_apply, current

        head = QHBoxLayout()
        head.addWidget(badge("video_music", "accent", 38, 20))
        tv = QVBoxLayout()
        tv.setSpacing(2)
        title = QLabel("Hồ sơ kênh")
        title.setObjectName("updateTitle")
        tv.addWidget(title)
        tv.addWidget(w.muted("Mỗi kênh một bộ: intro / outro, màu & logo, âm thanh, thư mục nhạc, tiếng nền, mẫu bảng, "
                             "nơi lưu + chất lượng xuất. Chọn hồ sơ là áp cả bộ — bảng clip giữ nguyên."))
        head.addLayout(tv, 1)
        new = QPushButton("Lưu cài đặt hiện tại thành hồ sơ…")
        new.setObjectName("accentBtn")
        new.setIcon(icons.icon("plus", 13, "accent_text"))
        new.clicked.connect(self._new)
        head.addWidget(new, 0, Qt.AlignmentFlag.AlignTop)

        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 6, 0)
        self.body_lay.setSpacing(theme.SP["md"])
        scroll = QScrollArea()
        scroll.setWidget(self.body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        exp = QPushButton("Xuất ra file…")
        exp.setObjectName("pill")
        exp.setIcon(icons.icon("upload", 13))
        exp.setToolTip("Lưu hồ sơ kênh + mẫu của bạn ra file .ktls để gửi máy khác")
        exp.clicked.connect(lambda: export_file(self, self.settings))
        imp = QPushButton("Nhập từ file…")
        imp.setObjectName("pill")
        imp.setIcon(icons.icon("download", 13))
        imp.setToolTip("Nhận hồ sơ kênh + mẫu từ file .ktls của máy khác")
        imp.clicked.connect(self._import)
        close = QPushButton("Đóng")
        close.clicked.connect(self.reject)
        bb = QHBoxLayout()
        bb.addWidget(exp)
        bb.addWidget(imp)
        bb.addStretch(1)
        bb.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SP["md"])
        lay.addLayout(head)
        lay.addWidget(scroll, 1)
        lay.addLayout(bb)
        self._fill()

    def _profiles(self) -> list[dict]:
        return read_profiles(self.settings)

    def _fill(self) -> None:
        while self.body_lay.count():
            it = self.body_lay.takeAt(0)
            wd = it.widget()
            if wd is not None:
                wd.hide()
                wd.deleteLater()
        items = self._profiles()
        if not items:
            self.body_lay.addWidget(w.muted(
                "Chưa có hồ sơ nào. Cách tạo: mở / làm một video của kênh đúng ý (intro / outro, logo, nhạc, nơi lưu…) "
                "→ bấm <b>Lưu cài đặt hiện tại thành hồ sơ…</b> → đặt tên kênh. Lần sau chỉ cần chọn kênh."))
        for p in items:
            self.body_lay.addWidget(self._card(p))
        self.body_lay.addStretch(1)

    def _card(self, p: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("presetCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(theme.SP["lg"], theme.SP["md"], theme.SP["lg"], theme.SP["md"])
        row = QHBoxLayout()
        name = QLabel(p["name"])
        name.setObjectName("presetName")
        row.addWidget(name)
        if p["name"] == self.current:
            chip = QLabel("đang dùng")
            chip.setObjectName("chipOk")
            row.addWidget(chip)
        row.addStretch(1)
        for text, tip, fn, obj in (
                ("Cập nhật", "Ghi đè hồ sơ này bằng cài đặt của dự án đang mở", lambda: self._update(p), "ghost"),
                ("Đổi tên", "", lambda: self._rename(p), "ghost"),
                ("", "Xoá hồ sơ này", lambda: self._delete(p), "danger"),
                ("Dùng hồ sơ này", "Áp intro / outro, nhạc, xuất… vào dự án đang mở (bảng clip giữ nguyên)",
                 lambda: self._apply(p), "tonal")):
            b = QPushButton(text)
            if not text:
                b.setIcon(icons.icon("trash", 14))
                b.setFixedWidth(34)
                theme.tag(b, variant="danger")
            elif obj == "tonal":
                theme.tag(b, variant="tonal")
            else:
                theme.tag(b, variant="ghost")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        cv.addLayout(row)
        desc = w.muted(prof.describe(p))
        desc.setWordWrap(True)
        cv.addWidget(desc)
        return card

    def _save(self, items: list[dict]) -> None:
        write_profiles(self.settings, items)
        self._fill()

    def _ask_name(self, title: str, default: str = "") -> str:
        name, ok = QInputDialog.getText(self, title, "Tên kênh (ví dụ: Kênh Mưa Đêm):", text=default)
        return name.strip() if ok else ""

    def _new(self) -> None:
        name = self._ask_name("Lưu thành hồ sơ kênh")
        if not name:
            return
        items = self._profiles()
        if any(p["name"] == name for p in items) and QMessageBox.question(
                self, "Hồ sơ kênh", f"Đã có hồ sơ “{name}”. Ghi đè?") != QMessageBox.StandardButton.Yes:
            return
        self._save([p for p in items if p["name"] != name] + [self.capture(name)])

    def _update(self, p: dict) -> None:
        if QMessageBox.question(self, "Cập nhật hồ sơ", f"Ghi đè “{p['name']}” bằng cài đặt của dự án đang mở?") \
                != QMessageBox.StandardButton.Yes:
            return
        self._save([self.capture(p["name"]) if x["name"] == p["name"] else x for x in self._profiles()])

    def _rename(self, p: dict) -> None:
        name = self._ask_name("Đổi tên hồ sơ", p["name"])
        if not name or name == p["name"]:
            return
        if any(x["name"] == name for x in self._profiles()):
            QMessageBox.information(self, "Hồ sơ kênh", f"Đã có hồ sơ “{name}”.")
            return
        if self.current == p["name"]:
            self.current = name
        self._save([dict(x, name=name) if x["name"] == p["name"] else x for x in self._profiles()])

    def _delete(self, p: dict) -> None:
        if QMessageBox.question(self, "Xoá hồ sơ", f"Xoá hồ sơ “{p['name']}”?") != QMessageBox.StandardButton.Yes:
            return
        self._save([x for x in self._profiles() if x["name"] != p["name"]])

    def _apply(self, p: dict) -> None:
        self.on_apply(p)
        self.accept()

    def _import(self) -> None:
        if import_file(self, self.settings):
            self._fill()
