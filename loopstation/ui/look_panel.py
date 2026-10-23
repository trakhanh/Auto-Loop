"""Thẻ "Màu & Logo" (trang Video): chọn bộ lọc màu + cường độ, logo / khung PNG, có ảnh xem trước ngay."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from ..core import look as lk
from ..core.project import VideoSettings
from . import icons, theme
from . import widgets as w

PREVIEW_W = 400


class _Bridge(QObject):
    done = Signal(int, str)  # (lượt, file ảnh hoặc "")


class LookPanel(QWidget):
    changed = Signal()

    def __init__(self, settings: QSettings, slider_row, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._loading = False
        self._src: tuple | None = None  # (path, is_image, giây, rộng, cao, fit)
        self._gen = 0
        self._bridge = _Bridge()
        self._bridge.done.connect(self._on_preview)
        from ..core import ffmpeg_tools as ft
        self._tmp = ft.cache_dir("lookpreview")  # một thư mục cố định, ghi đè vòng 4 file → không tích rác

        # ----- chỉnh màu -----
        self.color = QComboBox()
        for k, (name, _) in lk.COLOR_PRESETS.items():
            self.color.addItem(name, k)
        self.strength = QSpinBox()
        self.strength.setRange(0, 100)
        self.strength.setSuffix(" %")
        self.strength.setValue(100)
        self.strength_row = slider_row(self.strength)
        self.lbl_strength = QLabel("Cường độ")
        g_color = QGroupBox("Chỉnh màu")
        fc = QFormLayout(g_color)
        fc.setVerticalSpacing(8)
        fc.addRow("Bộ lọc màu", self.color)
        fc.addRow(self.lbl_strength, self.strength_row)

        # ----- logo / khung -----
        self.logo = QLineEdit()
        self.logo.setReadOnly(True)
        self.logo.setPlaceholderText("Chưa chọn — ảnh PNG nền trong suốt")
        pick = QPushButton("Chọn…")
        pick.setObjectName("pill")
        pick.clicked.connect(self._pick_logo)
        self.clear = QPushButton("Xoá")
        self.clear.setObjectName("ghost")
        self.clear.clicked.connect(lambda: self._set_logo(""))
        lrow = QHBoxLayout()
        lrow.setContentsMargins(0, 0, 0, 0)
        lrow.setSpacing(4)
        lrow.addWidget(self.logo, 1)
        lrow.addWidget(pick)
        lrow.addWidget(self.clear)
        lwrap = QWidget()
        lwrap.setLayout(lrow)
        self.pos = QComboBox()
        for k, name in lk.LOGO_POS.items():
            self.pos.addItem(name, k)
        self.size = QSpinBox()
        self.size.setRange(2, 60)
        self.size.setSuffix(" %")
        self.size.setValue(14)
        self.size.setToolTip("Chiều rộng logo so với chiều rộng khung hình")
        self.size_row = slider_row(self.size)
        self.opacity = QSpinBox()
        self.opacity.setRange(0, 100)
        self.opacity.setSuffix(" %")
        self.opacity.setValue(100)
        self.opacity_row = slider_row(self.opacity)
        self.lbl_pos, self.lbl_size, self.lbl_opacity = QLabel("Vị trí"), QLabel("Kích thước"), QLabel("Độ rõ")
        g_logo = QGroupBox("Logo / Khung PNG (đóng dấu thương hiệu)")
        fl = QFormLayout(g_logo)
        fl.setVerticalSpacing(8)
        fl.addRow("File PNG", lwrap)
        fl.addRow(self.lbl_pos, self.pos)
        fl.addRow(self.lbl_size, self.size_row)
        fl.addRow(self.lbl_opacity, self.opacity_row)
        self.bookends = QCheckBox("Áp màu & logo cả lên Intro / Outro")
        self.bookends.setToolTip("Mặc định Intro / Outro giữ nguyên như file gốc (thường đã có thương hiệu riêng)")

        # ----- xem trước -----
        self.preview = QLabel("Thêm clip ở bảng bên trái để xem trước.")
        self.preview.setObjectName("previewBox")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(120, 90)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)  # co theo bề rộng khung
        self.preview.setFixedHeight(200)
        self._pm: QPixmap | None = None
        self._aspect = 9 / 16
        self.preview_note = w.muted("")
        g_prev = QGroupBox("Xem trước (clip đầu tiên, giữa clip)")
        pv = QVBoxLayout(g_prev)
        pv.addWidget(self.preview)
        pv.addWidget(self.preview_note)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 4, 0)
        lay.setSpacing(8)
        lay.addWidget(g_prev)
        lay.addWidget(g_color)
        lay.addWidget(g_logo)
        lay.addWidget(self.bookends)
        lay.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._render_preview)
        for sig in (self.color.currentIndexChanged, self.strength.valueChanged, self.pos.currentIndexChanged,
                    self.size.valueChanged, self.opacity.valueChanged, self.bookends.toggled):
            sig.connect(self._emit)
        self._update_enabled()

    # ---------- dữ liệu ----------
    def load(self, vs: VideoSettings) -> None:
        self._loading = True
        i = self.color.findData(vs.color_preset)
        self.color.setCurrentIndex(max(0, i))
        self.strength.setValue(vs.color_strength)
        self._set_logo(vs.logo, emit=False)
        i = self.pos.findData(vs.logo_pos)
        self.pos.setCurrentIndex(max(0, i))
        self.size.setValue(vs.logo_size)
        self.opacity.setValue(vs.logo_opacity)
        self.bookends.setChecked(vs.look_bookends)
        self._loading = False
        self._update_enabled()
        self._timer.start()

    def fill(self, vs: VideoSettings) -> None:
        vs.color_preset = self.color.currentData()
        vs.color_strength = self.strength.value()
        vs.logo = self.logo.toolTip()
        vs.logo_pos = self.pos.currentData()
        vs.logo_size = self.size.value()
        vs.logo_opacity = self.opacity.value()
        vs.look_bookends = self.bookends.isChecked()

    def _current_look(self) -> lk.Look:
        return lk.Look(color=self.color.currentData(), strength=self.strength.value(), logo=self.logo.toolTip(),
                       logo_opacity=self.opacity.value(), logo_pos=self.pos.currentData(), logo_size=self.size.value())

    def summary(self) -> str:
        """Mô tả ngắn cho bảng tóm tắt trang Xuất."""
        parts = []
        if self.color.currentData() != "none" and self.strength.value() > 0:
            parts.append(f"màu {self.color.currentText()} {self.strength.value()}%")
        if self.logo.toolTip():
            parts.append(f"logo {Path(self.logo.toolTip()).name}")
        return ", ".join(parts)

    # ---------- thao tác ----------
    def _pick_logo(self) -> None:
        start = self.settings.value("dir/logo", "")
        f, _ = QFileDialog.getOpenFileName(self, "Chọn logo / khung PNG (nền trong suốt)", start,
                                           "Ảnh PNG / WebP (*.png *.webp);;Mọi ảnh (*.png *.webp *.jpg *.jpeg)")
        if f:
            self.settings.setValue("dir/logo", os.path.dirname(f))
            self._set_logo(f)

    def _set_logo(self, path: str, emit: bool = True) -> None:
        self.logo.setText(Path(path).name if path else "")
        self.logo.setToolTip(path)
        self.clear.setEnabled(bool(path))
        if emit:
            self._emit()

    def _update_enabled(self) -> None:
        has_color = self.color.currentData() != "none"
        self.lbl_strength.setVisible(has_color)
        self.strength_row.setVisible(has_color)
        has_logo = bool(self.logo.toolTip())
        frame = self.pos.currentData() == "frame"
        for wd in (self.lbl_pos, self.pos, self.lbl_opacity, self.opacity_row):
            wd.setVisible(has_logo)
        self.lbl_size.setVisible(has_logo and not frame)
        self.size_row.setVisible(has_logo and not frame)

    def _emit(self, *_) -> None:
        self._update_enabled()
        if self._loading:
            return
        self._timer.start()
        self.changed.emit()

    # ---------- xem trước ----------
    def set_preview_source(self, path: str | None, is_image: bool = False, at: float = 0.0, w: int = 1920,
                           h: int = 1080, fit: str = "letterbox") -> None:
        src = (path, is_image, round(at, 2), w, h, fit) if path else None
        if src != self._src:
            self._src = src
            self._timer.start()

    def _render_preview(self) -> None:
        if not self._src:
            self._pm = None
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Thêm clip ở bảng bên trái để xem trước.")
            self.preview_note.setText("")
            return
        path, is_image, at, w0, h0, fit = self._src
        pw = PREVIEW_W
        ph = max(2, int(pw * h0 / max(1, w0)) // 2 * 2)
        self._gen += 1
        gen = self._gen
        look = self._current_look()
        out = str(self._tmp / f"pv_{gen % 4}.png")
        self.preview_note.setText("Đang tạo ảnh xem trước…")

        def work():
            try:
                ok = lk.preview_frame(path, is_image, at, pw, ph, fit, look, out)
            except Exception:  # noqa: BLE001
                ok = False
            self._bridge.done.emit(gen, out if ok else "")

        threading.Thread(target=work, daemon=True).start()

    def _fit_preview(self) -> None:
        """Ảnh xem trước luôn vừa bề rộng khung, giữ đúng tỉ lệ khung hình xuất."""
        avail = max(120, self.preview.width() - 10)
        self.preview.setFixedHeight(int(avail * self._aspect) + 10)
        if self._pm is None or self._pm.isNull():
            return
        dpr = self.devicePixelRatioF()
        shown = self._pm.scaledToWidth(int(avail * dpr), Qt.TransformationMode.SmoothTransformation)
        shown.setDevicePixelRatio(dpr)
        self.preview.setPixmap(shown)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        QTimer.singleShot(0, self._fit_preview)

    def _on_preview(self, gen: int, out: str) -> None:
        if gen != self._gen:
            return
        if not out:
            self.preview_note.setText("<span style='color:" + theme.T["danger_text"] + "'>Không tạo được ảnh xem trước (kiểm tra file logo).</span>")
            return
        self._pm = QPixmap(out)
        self._aspect = self._pm.height() / max(1, self._pm.width())
        self._fit_preview()
        lkk = self._current_look()
        self.preview_note.setText("Đúng như khi xuất (đã áp màu & logo)." if lkk.active
                                  else "Chưa chỉnh màu / chưa có logo — đây là hình gốc.")
