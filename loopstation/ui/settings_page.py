"""Trang Cài đặt: thông số máy, FFmpeg + tăng tốc phần cứng (CUDA/NVENC…), đo tốc độ, tuỳ chọn hệ thống."""
from __future__ import annotations

import os
import shutil
import threading

from PySide6.QtCore import QObject, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from ..core import encoders, sysinfo
from ..core import ffmpeg_tools as ft
from . import icons, theme
from . import widgets as w

FONT_SIZES = [("Nhỏ", 9), ("Vừa (mặc định)", 10), ("Lớn", 11), ("Rất lớn", 12)]
VENDOR_ROWS = [
    ("NVIDIA NVENC", ["h264_nvenc", "hevc_nvenc", "av1_nvenc"]),
    ("Intel Quick Sync", ["h264_qsv", "hevc_qsv", "av1_qsv"]),
    ("AMD AMF", ["h264_amf", "hevc_amf", "av1_amf"]),
    ("CPU (phần mềm)", ["libx264", "libx265"]),
]
CODEC_SHORT = {"h264": "H.264", "hevc": "H.265", "av1": "AV1", "libx264": "H.264", "libx265": "H.265"}


def pill(ok: bool | None, text: str) -> QLabel:
    lab = QLabel(("✓ " if ok else "✗ " if ok is not None else "") + text)
    lab.setObjectName("chip" if ok is None else ("chipOk" if ok else "chipOff"))
    return lab


def _short(enc: str) -> str:
    return CODEC_SHORT.get(enc) or CODEC_SHORT.get(enc.split("_")[0], enc)


def _swatch(accent: str):
    """Chấm màu nhấn (phẳng) cạnh tên bộ màu."""
    from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap
    pm = QPixmap(28, 28)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(3, 3, 22, 22)
    p.fillPath(path, QColor(accent))
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


class _Bridge(QObject):
    bench = Signal(str, float)
    bench_done = Signal()
    cache = Signal(str)


class SettingsPage(QWidget):
    prefsChanged = Signal()
    recheckRequested = Signal()
    welcomeRequested = Signal()  # xem lại màn hình chào

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.accel: sysinfo.AccelInfo | None = None
        self._bridge = _Bridge()
        self._bridge.bench.connect(self._on_bench)
        self._bridge.bench_done.connect(lambda: self.bench_btn.setEnabled(True))
        self._bridge.cache.connect(lambda t: self.cache_label.setText(t))

        title = QLabel("Cài đặt hệ thống & Thông số phần cứng")
        title.setObjectName("appName")
        recheck = QPushButton("Kiểm tra lại phần cứng")
        recheck.setObjectName("accentBtn")
        recheck.setIcon(icons.icon("refresh", 14, "accent_text"))
        recheck.setIconSize(QSize(14, 14))
        recheck.clicked.connect(lambda: self.recheckRequested.emit())
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(recheck)

        # ----- máy tính -----
        self.sys_form = QFormLayout()
        self.sys_form.setVerticalSpacing(8)
        g_sys = QGroupBox("Thông số máy tính của bạn")
        g_sys.setLayout(self.sys_form)
        self.sys_form.addRow(w.muted("Đang đọc thông số máy…"))

        # ----- tăng tốc -----
        self.verdict = QLabel("Đang kiểm tra FFmpeg và card đồ hoạ…")
        self.verdict.setObjectName("info")
        self.verdict.setWordWrap(True)
        self.accel_grid = QGridLayout()
        self.accel_grid.setHorizontalSpacing(8)
        self.accel_grid.setVerticalSpacing(8)
        g_acc = QGroupBox("FFmpeg && Tăng tốc phần cứng (GPU)")
        av = QVBoxLayout(g_acc)
        av.setSpacing(8)
        av.addWidget(self.verdict)
        av.addLayout(self.accel_grid)

        # ----- đo tốc độ -----
        self.bench_btn = QPushButton("Đo tốc độ mã hoá (khoảng 30 giây)")
        self.bench_btn.setObjectName("accentBtn")
        self.bench_btn.setIcon(icons.icon("play", 13, "accent_text"))
        self.bench_btn.setIconSize(QSize(13, 13))
        self.bench_btn.clicked.connect(self._run_bench)
        self.bench_rows = QFormLayout()
        self.bench_rows.setVerticalSpacing(8)
        g_bench = QGroupBox("Đo tốc độ mã hoá thực tế")
        bv = QVBoxLayout(g_bench)
        bv.setSpacing(8)
        bv.addWidget(w.muted("Mã hoá thử 10 giây video 1080p bằng từng bộ mã hoá có trên máy. "
                             "Con số càng lớn càng nhanh (×1 = bằng thời gian thực)."))
        bv.addWidget(self.bench_btn, 0, Qt.AlignmentFlag.AlignLeft)
        bv.addLayout(self.bench_rows)
        self._bars: dict[str, tuple[QProgressBar, QLabel]] = {}

        left = QVBoxLayout()
        left.setSpacing(10)
        for g in (g_sys, g_acc, g_bench):
            left.addWidget(g)
        left.addStretch(1)

        # ----- tuỳ chọn xuất -----
        self.out_dir = QLineEdit(settings.value("pref/output_dir", ""))
        self.out_dir.setPlaceholderText("Mặc định: thư mục Videos")
        self.out_dir.setMinimumWidth(120)
        pick = QPushButton("Chọn…")
        pick.clicked.connect(self._pick_out)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.out_dir, 1)
        row.addWidget(pick)
        self.hwdec = QCheckBox("Giải mã video nguồn bằng GPU (CUDA)")
        self.hwdec.setToolTip("Thường KHÔNG nhanh hơn với clip ngắn (CPU giải mã rất nhanh, CUDA tốn thời gian khởi "
                              "động). Chỉ nên bật trên máy CPU yếu hoặc clip nguồn 4K dài.")
        self.open_folder = QCheckBox("Mở thư mục chứa file khi xuất xong")
        self.beep = QCheckBox("Phát âm báo khi xuất xong")
        self.shutdown = QCheckBox("Tắt máy khi chạy xong hàng đợi (có 2 phút để huỷ)")
        self.shutdown.setToolTip("Chỉ áp dụng cho lần chạy hiện tại — mở lại app sẽ tự bỏ tick")
        g_exp = QGroupBox("Tuỳ chọn xuất video")
        f = QFormLayout(g_exp)
        f.setVerticalSpacing(8)
        f.addRow("Thư mục xuất mặc định", row)
        f.addRow(self.hwdec)
        f.addRow(w.muted("Tốc độ xuất đến chủ yếu từ bộ mã hoá trên card (NVENC/Quick Sync/AMF), app luôn tự dùng. "
                         "Giải mã bằng GPU là tuỳ chọn thêm."))
        f.addRow(self.open_folder)
        f.addRow(self.beep)
        f.addRow(self.shutdown)

        # ----- ffmpeg -----
        self.ff_dir = QLineEdit(settings.value("pref/ffmpeg_dir", ""))
        self.ff_dir.setPlaceholderText("Tự động (thư mục bin cạnh app, hoặc PATH)")
        self.ff_dir.setReadOnly(True)
        self.ff_dir.setMinimumWidth(120)
        ff_pick = QPushButton("Chọn…")
        ff_pick.clicked.connect(self._pick_ffmpeg)
        ff_auto = QPushButton("Tự động")
        ff_auto.setObjectName("ghost")
        ff_auto.clicked.connect(lambda: self._set_ffmpeg(""))
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        r2.addWidget(self.ff_dir, 1)
        r2.addWidget(ff_pick)
        r2.addWidget(ff_auto)
        g_ff = QGroupBox("Đường dẫn FFmpeg")
        f = QFormLayout(g_ff)
        f.setVerticalSpacing(8)
        f.addRow("Thư mục chứa ffmpeg.exe", r2)
        f.addRow(w.muted("Chỉ cần đổi khi muốn dùng bản FFmpeg khác. Cần FFmpeg 7 trở lên."))

        # ----- bộ nhớ đệm -----
        self.cache_label = QLabel("…")
        self.cache_label.setObjectName("chip")
        clear = QPushButton("Xoá bộ nhớ đệm")
        clear.setObjectName("danger")
        clear.setIcon(icons.icon("trash", 14, "danger_text"))
        clear.setIconSize(QSize(14, 14))
        clear.clicked.connect(self._clear_cache)
        self.clear_cache_btn = clear
        open_data = QPushButton("Mở thư mục dữ liệu")
        open_data.setObjectName("ghost")
        open_data.setIcon(icons.icon("folder", 14))
        open_data.setIconSize(QSize(14, 14))
        open_data.clicked.connect(lambda: os.startfile(str(ft.data_dir())))  # type: ignore[attr-defined]
        r3_box = QWidget()  # tự xuống dòng khi khung hẹp / chữ to → nút không bị cắt chữ
        r3 = w.FlowLayout(r3_box, spacing=8)
        r3.addWidget(self.cache_label)
        r3.addWidget(open_data)
        r3.addWidget(clear)
        g_cache = QGroupBox("Bộ nhớ đệm (Cache)")
        cv = QVBoxLayout(g_cache)
        cv.setSpacing(8)
        cv.addWidget(r3_box)
        cv.addWidget(w.muted("Lưu các clip đã mã hoá để lần xuất sau nhanh hơn. Xoá thoải mái khi cần chỗ trống; "
                             "lần xuất sau sẽ mã hoá lại."))

        # ----- giao diện -----
        self.font_combo = QComboBox()
        for label, pt in FONT_SIZES:
            self.font_combo.addItem(label, pt)
        self.font_combo.setCurrentIndex(max(0, self.font_combo.findData(int(settings.value("pref/font_pt", 10)))))
        g_ui = QGroupBox("Giao diện hiển thị")
        f = QFormLayout(g_ui)
        f.setVerticalSpacing(8)
        f.addRow("Cỡ chữ ứng dụng", self.font_combo)
        self.palette_combo = QComboBox()
        for key, (label, accent, _a2, _text, _soft) in theme.PALETTES.items():
            self.palette_combo.addItem(_swatch(accent), label, key)
        self.palette_combo.setIconSize(QSize(14, 14))
        self.palette_combo.setCurrentIndex(max(0, self.palette_combo.findData(
            settings.value("pref/palette", theme.PALETTE))))
        self.palette_combo.setToolTip("Màu của nút chính, thanh chọn, quầng sáng… Đổi là thấy ngay.")
        f.addRow("Màu chủ đạo", self.palette_combo)
        welcome = QPushButton("Xem lại màn hình chào")
        welcome.setObjectName("pill")
        welcome.setIcon(icons.icon("home", 13))
        welcome.setIconSize(QSize(13, 13))
        welcome.clicked.connect(self.welcomeRequested.emit)
        wrow = QHBoxLayout()
        wrow.setContentsMargins(0, 0, 0, 0)
        wrow.addWidget(welcome)
        wrow.addStretch(1)
        f.addRow(wrow)

        right = QVBoxLayout()
        right.setSpacing(10)
        # ----- giới thiệu: tên app, phiên bản, tác giả -----
        from .theme import APP_NAME, APP_VERSION, AUTHOR
        g_about = QGroupBox("Giới thiệu")
        fa = QFormLayout(g_about)
        fa.setVerticalSpacing(theme.FORM_GAP)
        ver = QLabel(f"<b>{APP_VERSION}</b>")
        ver.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        fa.addRow("Ứng dụng", QLabel(f"<b>{APP_NAME}</b>"))
        fa.addRow("Phiên bản", ver)
        fa.addRow("Tác giả", QLabel(AUTHOR.replace("By ", "")))
        fa.addRow(w.muted("Báo lỗi: gửi kèm số phiên bản này và file nhật ký (Thư mục dữ liệu → logs)."))
        for g in (g_exp, g_ff, g_cache, g_ui, g_about):
            right.addWidget(g)
        right.addStretch(1)

        cols = QHBoxLayout()
        cols.setSpacing(theme.SP['lg'])
        lw, rw = QWidget(), QWidget()
        lw.setLayout(left)
        rw.setLayout(right)
        for col in (left, right):
            col.setContentsMargins(0, 0, 0, 0)
        lw.setMinimumWidth(480)
        rw.setMinimumWidth(420)
        cols.addWidget(lw, 3)
        cols.addWidget(rw, 2)
        self._cols = cols
        lay = QVBoxLayout(self)
        theme.page_layout(lay)
        lay.addLayout(head)
        lay.addLayout(cols, 1)

        for c, key, default in ((self.hwdec, "pref/hwdec", False), (self.open_folder, "pref/open_folder", True),
                                (self.beep, "pref/beep", True)):
            c.setChecked(str(settings.value(key, default)).lower() in ("true", "1"))
            c.toggled.connect(lambda v, k=key: self._save(k, v))
        self.shutdown.toggled.connect(lambda _: self.prefsChanged.emit())
        self.out_dir.editingFinished.connect(lambda: self._save("pref/output_dir", self.out_dir.text().strip()))
        self.font_combo.currentIndexChanged.connect(lambda _: self._save("pref/font_pt", self.font_combo.currentData()))
        self.palette_combo.currentIndexChanged.connect(
            lambda _: self._save("pref/palette", self.palette_combo.currentData()))
        self.refresh_cache()

    # ---------- dữ liệu từ cửa sổ chính ----------
    def set_system(self, info: sysinfo.SystemInfo) -> None:
        f = self.sys_form
        while f.rowCount():
            f.removeRow(0)
        f.addRow("Hệ điều hành", QLabel(info.os))
        f.addRow("CPU", QLabel(f"{info.cpu} · {info.cores} luồng"))
        f.addRow("RAM", QLabel(f"{info.ram_gb:.0f} GB"))
        for i, g in enumerate(info.gpus or [sysinfo.GPU("Không đọc được")]):
            text = g.name
            details = [x for x in (f"driver {g.driver}" if g.driver else "",
                                   f"{g.vram_mb / 1024:.0f} GB VRAM" if g.vram_mb >= 1024 else "", g.extra) if x]
            lab = QLabel(text + ("\n" + " · ".join(details) if details else ""))
            f.addRow("Card đồ hoạ" if i == 0 else "", lab)
        has_nvidia = any("nvidia" in g.name.lower() for g in info.gpus)
        if info.cuda_version:
            cuda_txt = f"CUDA {info.cuda_version}"
        elif has_nvidia:  # có card nhưng không đọc được số phiên bản: KHÔNG được ghi là "không có card NVIDIA"
            cuda_txt = "Có card NVIDIA (chưa đọc được số phiên bản CUDA)"
        else:
            cuda_txt = "Không có (máy không có card NVIDIA)"
        f.addRow("CUDA", pill(bool(info.cuda_version) or has_nvidia, cuda_txt))
        out = self.out_dir.text().strip() or os.path.expanduser("~/Videos")
        try:
            du = shutil.disk_usage(out if os.path.isdir(out) else os.path.expanduser("~"))
            f.addRow("Ổ đĩa xuất", QLabel(f"còn trống {du.free / 1024 ** 3:.0f} GB / {du.total / 1024 ** 3:.0f} GB"))
        except OSError:
            pass

    def set_accel(self, info: sysinfo.AccelInfo, audio_mf: bool) -> None:
        self.accel = info
        g = self.accel_grid
        while g.count():
            item = g.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if info.error:
            self.verdict.setText(f"Lỗi: {info.error}")
            return
        g.addWidget(QLabel("FFmpeg"), 0, 0)
        ff = QLabel(f"✓ {info.ffmpeg_version}")
        ff.setObjectName("chipOk")
        g.addWidget(ff, 0, 1, 1, 3)
        path = QLabel(self.fontMetrics().elidedText(info.ffmpeg_path, Qt.TextElideMode.ElideMiddle, 420))
        path.setObjectName("muted")
        path.setToolTip(info.ffmpeg_path)
        g.addWidget(path, 1, 1, 1, 3)
        g.addWidget(QLabel("Giải mã CUDA"), 2, 0)
        g.addWidget(pill(info.cuda_decode, "dùng được" if info.cuda_decode else "không có"), 2, 1)
        r = 3
        for vendor, encs in VENDOR_ROWS:
            g.addWidget(QLabel(vendor), r, 0)
            for c, enc in enumerate(encs):
                g.addWidget(pill(info.encoders.get(enc, False), _short(enc)), r, 1 + c)
            r += 1
        g.addWidget(QLabel("AAC nhanh (Windows)"), r, 0)
        g.addWidget(pill(audio_mf, "dùng được" if audio_mf else "không có"), r, 1)
        g.setColumnStretch(4, 1)
        self.hwdec.setEnabled(info.cuda_decode)
        if not info.cuda_decode:
            self.hwdec.setChecked(False)

        best = next((v for v, encs in VENDOR_ROWS[:3] if info.encoders.get(encs[0])), None)
        if best:
            self.verdict.setText(f"Máy này xuất bằng <b>{best}</b> trên card đồ hoạ — tốc độ cao. "
                                 + ("CUDA cũng sẵn sàng. " if info.cuda_decode else "")
                                 + "Bạn không cần cài thêm gì.")
        else:
            self.verdict.setText("Không dùng được bộ mã hoá trên card đồ hoạ — app sẽ xuất bằng CPU (chậm hơn "
                                 "khoảng 3 lần). Thử cập nhật driver card đồ hoạ rồi bấm 'Kiểm tra lại phần cứng'.")

    def refresh_cache(self) -> None:
        def work():
            size = ft.cache_size()
            self._bridge.cache.emit(f"Đang dùng {size / 1024 ** 2:,.0f} MB".replace(",", "."))
        threading.Thread(target=work, daemon=True).start()

    # ---------- đo tốc độ ----------
    def _run_bench(self) -> None:
        if not self.accel or self.accel.error:
            return
        encs = [e for e in ("h264_nvenc", "h264_qsv", "h264_amf", "libx264") if self.accel.encoders.get(e)]
        while self.bench_rows.rowCount():
            self.bench_rows.removeRow(0)
        self._bars.clear()
        for e in encs:
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat("đang đo…")
            lab = QLabel("")
            row = QHBoxLayout()
            row.addWidget(bar, 1)
            row.addWidget(lab)
            name = next(v for v, es in VENDOR_ROWS if e in es)
            self.bench_rows.addRow(name, row)
            self._bars[e] = (bar, lab)
        self.bench_btn.setEnabled(False)

        def work():
            for e in encs:  # lần lượt để không tranh nhau tài nguyên
                self._bridge.bench.emit(e, sysinfo.benchmark(e))
            self._bridge.bench_done.emit()
        threading.Thread(target=work, daemon=True).start()

    def _on_bench(self, enc: str, speed: float) -> None:
        bar, lab = self._bars[enc]
        bar.setValue(min(100, int(speed / 10 * 100)))
        bar.setFormat(f"×{speed:.1f}" if speed else "lỗi")
        lab.setText(f"1 phút video ≈ {60 / speed:.0f} giây" if speed else "")

    # ---------- tuỳ chọn ----------
    def _save(self, key: str, value) -> None:
        self.settings.setValue(key, value)
        self.prefsChanged.emit()

    def _pick_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Thư mục xuất mặc định", self.out_dir.text())
        if d:
            self.out_dir.setText(os.path.normpath(d))
            self._save("pref/output_dir", self.out_dir.text())

    def _pick_ffmpeg(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Thư mục chứa ffmpeg.exe và ffprobe.exe", self.ff_dir.text())
        if not d:
            return
        if not (os.path.isfile(os.path.join(d, "ffmpeg.exe")) and os.path.isfile(os.path.join(d, "ffprobe.exe"))):
            QMessageBox.warning(self, "Không đúng thư mục", "Thư mục này không có cả ffmpeg.exe và ffprobe.exe.")
            return
        self._set_ffmpeg(os.path.normpath(d))

    def _set_ffmpeg(self, folder: str) -> None:
        self.ff_dir.setText(folder)
        self.settings.setValue("pref/ffmpeg_dir", folder)
        ft.set_custom_dir(folder or None)
        self.recheckRequested.emit()

    def set_job_running(self, running: bool) -> None:
        """Đang xuất: khoá nút xoá bộ nhớ đệm (xoá giữa chừng làm hỏng lượt xuất đang ghép khối)."""
        self.clear_cache_btn.setEnabled(not running)
        self.clear_cache_btn.setToolTip("Đang xuất file — chờ xuất xong rồi mới xoá được." if running else "")

    def _clear_cache(self) -> None:
        if QMessageBox.question(self, "Xoá bộ nhớ đệm", "Xoá các clip đã mã hoá sẵn và các bản xem thử nối? Lần xuất sau sẽ chậm hơn một chút.") \
                != QMessageBox.StandardButton.Yes:
            return
        ft.clear_cache()
        self.refresh_cache()

    # ---------- đọc tuỳ chọn ----------
    def pref(self, key: str, default=False) -> bool:
        return str(self.settings.value(key, default)).lower() in ("true", "1")

    def adapt(self, width: int, height: int = 0) -> None:
        self._cols.setDirection(QHBoxLayout.Direction.TopToBottom if width < 1150
                                else QHBoxLayout.Direction.LeftToRight)
