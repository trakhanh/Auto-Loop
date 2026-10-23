"""Trang Xuất: codec, độ phân giải, fps, encoder, nơi lưu, nút xuất, hàng đợi, tiến trình, nhật ký."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core import encoders
from ..core.project import ExportSettings, MusicSettings, format_hms, parse_hms
from ..core.render_queue import KIND_LABELS, STATUS_LABELS, QueueItem
from . import effects, icons, theme
from . import widgets as w
from .video_tab import combo, hms_edit, quick_buttons, set_combo

AUDIO_LENGTH = [("target", "Theo thời lượng đích"), ("rounds", "Theo số lượt phát playlist")]


class ExportTab(QWidget):
    changed = Signal()
    startRequested = Signal()
    cancelRequested = Signal()
    queueAddRequested = Signal()
    queueRunRequested = Signal()
    queueEdited = Signal()
    emptyActionRequested = Signal(int)  # nút ở màn hình trống: chuyển tới trang (0 = Video, 1 = Nhạc)
    batchRequested = Signal()  # thêm hàng loạt từ thư mục  # xoá/đổi thứ tự mục trong hàng đợi

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._loading = False
        self._running = False
        self._can_export = False
        self.available: dict[str, list[str]] | None = None
        self.last_output: str | None = None

        self.preset = QComboBox()
        for p in encoders.PRESETS.values():
            self.preset.addItem(p.label, p.key)
        self.resolution = QComboBox()
        for k, (label, _, _) in encoders.RESOLUTIONS.items():
            self.resolution.addItem(label, k)
        self.fps = QComboBox()
        for k, label in encoders.FPS_CHOICES.items():
            self.fps.addItem(label, k)
        self.encoder = QComboBox()
        self.encoder.addItem("Đang kiểm tra card đồ hoạ…", "auto")
        self.encoder.setEnabled(False)
        self.quality = QComboBox()
        for k, v in encoders.QUALITY_LABELS.items():
            self.quality.addItem(v, k)
        self.audio = QComboBox()
        for k, v in encoders.AUDIO_LABELS.items():
            self.audio.addItem(v, k)
        # ----- giới hạn dung lượng + dự đoán -----
        self.cap = QComboBox()
        for k, v in encoders.BITRATE_CAPS.items():
            self.cap.addItem(v, k)
        self.cap.setToolTip("Chặn bitrate tối đa của hình để file nhẹ hơn. Cảnh nhiều chi tiết sẽ mềm hơn một chút.")
        self.cap_mbps = QDoubleSpinBox()
        self.cap_mbps.setRange(0.5, 200.0)
        self.cap_mbps.setDecimals(1)
        self.cap_mbps.setSingleStep(1.0)
        self.cap_mbps.setSuffix(" Mbps")
        self.cap_mbps.setValue(8.0)
        self.cap_gb = QDoubleSpinBox()
        self.cap_gb.setRange(0.1, 2000.0)
        self.cap_gb.setDecimals(1)
        self.cap_gb.setSingleStep(1.0)
        self.cap_gb.setSuffix(" GB")
        self.cap_gb.setValue(10.0)
        self.cap_gb.setToolTip("Dung lượng tối đa mong muốn của cả file (app tự tính bitrate theo độ dài video)")
        cap_row = QHBoxLayout()
        cap_row.setContentsMargins(0, 0, 0, 0)
        cap_row.setSpacing(6)
        cap_row.addWidget(self.cap, 1)
        cap_row.addWidget(self.cap_mbps)
        cap_row.addWidget(self.cap_gb)
        cap_box = QWidget()
        cap_box.setLayout(cap_row)
        self.size_label = QLabel("—")
        self.size_label.setObjectName("sizeEst")
        self.size_label.setProperty("busy", False)
        self.size_label.setToolTip("Mã hoá thử vài giây của từng clip với đúng cấu hình đang chọn rồi nhân theo "
                                   "độ dài video — sai số thường dưới 10%.")

        label_w = int(150 * max(1.0, theme.scale()))  # cột nhãn cố định: ô nhập ở mọi thẻ bắt đầu cùng một mép trái

        def lab(text: str) -> QLabel:
            lb = QLabel(text)
            lb.setMinimumWidth(label_w)
            lb.setProperty("role", "fieldlabel")
            return lb

        def form(box: QGroupBox) -> QFormLayout:
            fl = QFormLayout(box)
            fl.setVerticalSpacing(theme.FORM_GAP)
            fl.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            fl.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            return fl

        g_fmt = QGroupBox("Định dạng && Chất lượng Video")
        f = form(g_fmt)
        f.addRow(lab("Chuẩn nén (Codec)"), self.preset)
        f.addRow(lab("Độ phân giải"), self.resolution)
        f.addRow(lab("Khung hình/giây"), self.fps)
        f.addRow(lab("Bộ mã hoá (GPU/CPU)"), self.encoder)
        self.quality.setToolTip("Độ nét phần HÌNH ẢNH của video. Không ảnh hưởng tới âm thanh.\n"
                                "Đây là thứ quyết định gần như toàn bộ dung lượng file.")
        self.audio.setToolTip("Chất lượng ÂM THANH của video (nhạc + tiếng gốc + tiếng nền), độc lập với hình ảnh.\n"
                              "192 kbps đã đủ cho YouTube; 320 kbps chỉ thêm khoảng 60 MB mỗi giờ nhưng xuất chậm hơn.")
        f.addRow(lab("Chất lượng hình ảnh"), self.quality)
        f.addRow(lab("Chất lượng âm thanh"), self.audio)
        f.addRow(lab("Giới hạn dung lượng"), cap_box)
        # tuỳ chọn ít khi cần đổi: gấp lại cho gọn (app tự chọn tốt nhất)
        self.adv_btn = QPushButton("Tuỳ chọn nâng cao")
        self.adv_btn.setObjectName("ghost")
        self.adv_btn.setProperty("align", "left")
        self.adv_btn.setIconSize(QSize(12, 12))
        self.adv_btn.setToolTip("Chuẩn nén (codec), khung hình/giây, bộ mã hoá, chất lượng âm thanh. App tự chọn mức tốt nhất.")
        self.adv_btn.setCheckable(True)
        f.addRow(self.adv_btn)
        self._fmt_form = f
        self._adv_widgets = (self.preset, self.fps, self.encoder, self.audio)

        def show_adv(on: bool) -> None:
            for wd in self._adv_widgets:
                f.setRowVisible(wd, on)
            self.adv_btn.setIcon(icons.icon("up" if on else "down", 12, "text_2"))
            self.settings.setValue("ui/export_advanced", "true" if on else "false")

        self.adv_btn.toggled.connect(show_adv)
        self.adv_btn.setChecked(self.settings.value("ui/export_advanced", "false") in (True, "true"))
        show_adv(self.adv_btn.isChecked())

        # ----- xuất nhạc (kiểu "Chỉ nhạc") -----
        self.exp_format = combo([(k, f.label) for k, f in encoders.AUDIO_FORMATS.items()])
        self.exp_info = QLabel("")
        self.exp_info.setObjectName("muted")
        self.exp_info.setWordWrap(True)
        self.g_audio = QGroupBox("Định dạng File nhạc")
        f_aud = form(self.g_audio)
        f_aud.addRow(lab("Định dạng xuất"), self.exp_format)
        f_aud.addRow(self.exp_info)
        f_aud.addRow(w.muted("Độ dài file nhạc (ví dụ 10 bài → 1 giờ) chỉnh ở trang <b>2. Nhạc</b>, "
                             "thẻ <b>Độ dài file nhạc</b> trên cùng bên phải."))
        self.g_audio.hide()
        self.g_video = g_fmt
        self.exp_format.currentIndexChanged.connect(self._emit)
        self.mode = "video_music"

        self.out_dir = QLineEdit()
        browse = QPushButton("Chọn…")
        browse.clicked.connect(self._browse)
        open_dir = QPushButton("Mở thư mục")
        open_dir.setIcon(icons.icon("folder", 14))
        open_dir.setIconSize(QSize(14, 14))
        open_dir.setToolTip("Mở thư mục xuất trong Windows Explorer")
        open_dir.clicked.connect(lambda: self.out_dir.text() and w.open_with_default_app(self.out_dir.text()))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.out_dir, 1)
        row.addWidget(browse)
        row.addWidget(open_dir)
        self.filename = QLineEdit()
        self.filename.setPlaceholderText("Để trống = tự đặt theo Tên dự án + Ngày giờ")
        self.tracklist = QCheckBox("Xuất kèm tracklist .txt (dán vào mô tả YouTube để tạo Chapter)")
        self.project_copy = QCheckBox("Lưu kèm bản sao dự án (.lsproj) cạnh file xuất để dùng lại sau")
        self.own_folder = QCheckBox("Mỗi video một thư mục riêng (video + các file kèm nằm chung)")
        self.own_folder.setToolTip("Ví dụ: Thư mục lưu › Ten-video › Ten-video.mp4 cùng file mốc thời gian, tracklist…")
        self.markers = QCheckBox("Xuất kèm file mốc thời gian cho editor (đoạn LOOP / đoạn THƯỜNG)")
        self.markers.setToolTip("4 file: .txt để đọc, .csv mở bằng Excel, .srt kéo vào Premiere / CapCut / DaVinci "
                                "thành track chữ trên timeline, .edl nhập marker vào DaVinci Resolve. "
                                "Đoạn THƯỜNG là cảnh chèn — chỗ editor thêm sound effect.")
        g_out = QGroupBox("Nơi lưu && File xuất kèm")
        f_out = form(g_out)
        f_out.addRow(lab("Thư mục lưu"), row)
        f_out.addRow(lab("Tên file"), self.filename)
        f_out.addRow(self.own_folder)
        f_out.addRow(self.markers)
        f_out.addRow(self.tracklist)
        f_out.addRow(self.project_copy)

        # ----- thẻ tóm tắt (đầu trang) -----
        summary_card = QWidget()
        summary_card.setObjectName("quickBar")
        sc = QHBoxLayout(summary_card)
        sc.setContentsMargins(theme.SP['xl'], theme.SP['lg'], theme.SP['xl'], theme.SP['lg'])
        sc.setSpacing(theme.SP['xl'])
        self.summary = QLabel("")
        self.summary.setObjectName("info")
        self.summary.setWordWrap(True)
        self.summary.setProperty("plain", True)  # trong thẻ: không khung riêng
        sc.addWidget(self.summary, 1)
        size_box = QVBoxLayout()
        size_box.setSpacing(2)
        size_cap = QLabel("Dung lượng dự đoán")
        size_cap.setObjectName("muted")
        size_cap.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.size_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        size_box.addWidget(size_cap)
        size_box.addWidget(self.size_label)
        sc.addLayout(size_box)
        self.summary_card = summary_card

        # ----- màn hình trống: chưa có gì để xuất -----
        self.empty_card = QWidget()
        ev = QVBoxLayout(self.empty_card)
        ev.setContentsMargins(0, 32, 0, 24)
        ev.setSpacing(10)
        ev.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        tile = QLabel()
        tile.setObjectName("homeBadge")
        tile.setProperty("tone", "accent")
        tile.setPixmap(icons.pixmap("export", 22, theme.T["accent_text"]))
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile.setFixedSize(48, 48)
        self.empty_title = QLabel("Chưa có gì để xuất")
        self.empty_title.setObjectName("h2")
        self.empty_text = QLabel("")
        self.empty_text.setObjectName("muted")
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_btn = QPushButton("Thêm clip")
        self.empty_btn.setObjectName("primary")
        self.empty_btn.setIcon(icons.icon("plus", 15, "text_on_accent"))
        self.empty_btn.setIconSize(QSize(15, 15))
        self.empty_btn.clicked.connect(lambda: self.emptyActionRequested.emit(self._empty_target))
        self._empty_target = 0
        for wd, al in ((tile, Qt.AlignmentFlag.AlignHCenter), (self.empty_title, Qt.AlignmentFlag.AlignHCenter),
                       (self.empty_text, Qt.AlignmentFlag.AlignHCenter), (self.empty_btn, Qt.AlignmentFlag.AlignHCenter)):
            ev.addWidget(wd, 0, al)
        self.empty_card.setVisible(False)

        # ----- thanh hành động dính đáy (luôn hiện, không bị cắt): một nút chính "Xuất" -----
        footer = self.footer = QWidget()
        footer.setObjectName("exportFooter")
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(theme.SP['xl'], theme.SP['md'], theme.SP['xl'], theme.SP['md'])
        fv.setSpacing(theme.SP['md'])

        self.start_btn = QPushButton("Bắt đầu xuất video")
        self.start_btn.setObjectName("primary")
        self.start_btn.setIcon(icons.icon("play", 15, "text_on_accent"))
        self.start_btn.setIconSize(QSize(15, 15))
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(lambda: self.startRequested.emit())

        self.queue_add_btn = QPushButton("Thêm vào hàng đợi")
        self.queue_add_btn.setIcon(icons.icon("plus", 15, "text_2"))
        self.queue_add_btn.setIconSize(QSize(15, 15))
        self.queue_add_btn.setMinimumHeight(40)
        self.queue_add_btn.setToolTip("Lưu cấu hình hiện tại thành một mục chờ xuất. Thêm nhiều dự án rồi chạy "
                                      "lần lượt qua đêm.")
        self.queue_add_btn.clicked.connect(lambda: self.queueAddRequested.emit())

        # chỉ hiện khi dùng được: đang xuất mới có Huỷ, xuất xong mới có Hiện file
        self.cancel_btn = QPushButton("Huỷ xuất")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.setIcon(icons.icon("stop", 14, "danger_text"))
        self.cancel_btn.setIconSize(QSize(14, 14))
        self.cancel_btn.setMinimumHeight(40)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(lambda: self.cancelRequested.emit())

        self.open_out_btn = QPushButton("Hiện file vừa xuất")
        self.open_out_btn.setIcon(icons.icon("folder", 14, "text_2"))
        self.open_out_btn.setIconSize(QSize(14, 14))
        self.open_out_btn.setMinimumHeight(40)
        self.open_out_btn.setEnabled(False)
        self.open_out_btn.setVisible(False)
        self.open_out_btn.clicked.connect(self._open_output)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFormat("%p%")
        self._prog_anim = QPropertyAnimation(self.progress, b"value", self)
        self._prog_anim.setDuration(140)
        self._prog_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._shimmer = effects.Shimmer(self.progress)  # vệt sáng chạy trên thanh tiến trình lúc đang xuất
        self.status = w.ElidedLabel("Sẵn sàng xuất.")
        self.status.setObjectName("muted")

        self.prog_row = QWidget()
        prog_row = QHBoxLayout(self.prog_row)
        prog_row.setContentsMargins(0, 0, 0, 0)
        prog_row.setSpacing(12)
        prog_row.addWidget(self.progress, 2)
        prog_row.addWidget(self.status, 3)
        self.prog_row.setVisible(False)

        self.footer_info = w.ElidedLabel("")
        self.footer_info.setObjectName("muted")
        act_row = QHBoxLayout()
        act_row.setSpacing(8)
        act_row.addWidget(self.footer_info, 1)
        for b in (self.open_out_btn, self.cancel_btn, self.queue_add_btn, self.start_btn):
            act_row.addWidget(b)
        fv.addWidget(self.prog_row)
        fv.addLayout(act_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)

        # ----- hàng đợi & nhật ký -----
        self.queue = w.PlaceholderTree(
            "Hàng đợi đang trống\n"
            "Bấm 'Thêm vào hàng đợi' để xếp nhiều dự án,\n"
            "rồi bấm 'Chạy hàng đợi' để xuất lần lượt."
        )
        self.queue.setHeaderLabels(["Dự án", "Loại", "File đầu ra", "Trạng thái"])
        self.queue.setRootIsDecorated(False)
        self.queue.setAlternatingRowColors(True)
        self.queue.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        qh = self.queue.header()
        qh.setStretchLastSection(False)
        qh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.queue.setColumnWidth(0, 165)
        self.queue.setColumnWidth(1, 65)
        self.queue.setColumnWidth(3, 135)

        self.queue_run_btn = QPushButton("Chạy hàng đợi")
        self.queue_run_btn.setObjectName("accentBtn")
        self.queue_run_btn.setIcon(icons.icon("play", 13, "accent_text"))
        self.queue_run_btn.setIconSize(QSize(13, 13))
        self.queue_run_btn.setEnabled(False)
        self.queue_run_btn.clicked.connect(lambda: self.queueRunRequested.emit())
        q_del = QPushButton("Xoá mục chọn")
        q_del.setObjectName("ghost")
        q_del.setIcon(icons.icon("trash", 13))
        q_del.setIconSize(QSize(13, 13))
        q_del.clicked.connect(self._remove_selected)
        q_batch = QPushButton("Xuất hàng loạt…")
        q_batch.setObjectName("pill")
        q_batch.setIcon(icons.icon("folder", 13))
        q_batch.setIconSize(QSize(13, 13))
        q_batch.setToolTip("Mỗi thư mục con = một video: tự dựng theo mẫu rồi thêm cả loạt vào hàng đợi")
        q_batch.clicked.connect(lambda: self.batchRequested.emit())
        self.q_batch = q_batch
        self.queue.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self._queue_menu)
        q_clean = QPushButton("Dọn mục đã xong")
        q_clean.setObjectName("ghost")
        q_clean.clicked.connect(self._remove_finished)
        q_up = QPushButton("")
        q_up.setObjectName("ghost")
        q_up.setIcon(icons.icon("up", 14))
        q_up.setIconSize(QSize(14, 14))
        q_up.setToolTip("Đưa mục đang chọn lên trên")
        q_up.clicked.connect(lambda: self._move(-1))
        q_down = QPushButton("")
        q_down.setObjectName("ghost")
        q_down.setIcon(icons.icon("down", 14))
        q_down.setIconSize(QSize(14, 14))
        q_down.setToolTip("Đưa mục đang chọn xuống sau")
        q_down.clicked.connect(lambda: self._move(1))
        self.items: list[QueueItem] = []

        g_queue = QGroupBox("Hàng đợi xuất (Chạy nhiều dự án liên tiếp)")
        qv = QVBoxLayout(g_queue)
        qv.setContentsMargins(10, 6, 10, 8)
        qv.setSpacing(6)
        qv.addWidget(self.queue, 1)
        qr = QHBoxLayout()
        for b in (self.queue_run_btn, self.q_batch, q_up, q_down):
            qr.addWidget(b)
        qr.addStretch(1)
        qr.addWidget(q_del)
        qr.addWidget(q_clean)
        qv.addLayout(qr)

        g_log = QGroupBox("Nhật ký xử lý (FFmpeg Log)")
        lv_log = QVBoxLayout(g_log)
        lv_log.setContentsMargins(10, 6, 10, 8)
        lv_log.setSpacing(6)
        lv_log.addWidget(self.log, 1)
        log_bar = QHBoxLayout()
        log_hint = w.ElidedLabel("Chi tiết từng bước chuẩn hoá, ghép khối và dựng âm thanh.")
        log_hint.setObjectName("muted")
        log_bar.addWidget(log_hint, 1)
        btn_clear_log = QPushButton("Xoá nhật ký")
        btn_clear_log.setObjectName("ghost")
        btn_clear_log.clicked.connect(self.log.clear)
        log_bar.addWidget(btn_clear_log)
        lv_log.addLayout(log_bar)

        bottom = QSplitter(Qt.Orientation.Horizontal)
        bottom.setChildrenCollapsible(False)
        bottom.addWidget(g_queue)
        bottom.addWidget(g_log)
        bottom.setSizes([720, 680])

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(g_fmt, 1)
        top.addWidget(self.g_audio, 1)
        top.addWidget(g_out, 1)
        self.top_layout, self.bottom_split = top, bottom
        self._top_widgets = (g_fmt, self.g_audio, g_out)
        self._empty = None
        self.queue.setMinimumHeight(105)
        self.log.setMinimumHeight(105)

        # nội dung cuộn được; thanh hành động nằm ngoài vùng cuộn nên không bao giờ bị cắt
        content = QWidget()
        cl = QVBoxLayout(content)
        theme.page_layout(cl)
        cl.addWidget(self.empty_card)
        cl.addWidget(summary_card)
        cl.addLayout(top)
        cl.addWidget(bottom, 1)
        bottom.setMinimumHeight(560)
        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_scroll = scroll
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(scroll, 1)
        lay.addWidget(footer)

        for cb in (self.preset, self.resolution, self.fps, self.encoder, self.quality, self.audio, self.cap):
            cb.currentIndexChanged.connect(self._emit)
        self.cap.currentIndexChanged.connect(self._update_cap_ui)
        for sb in (self.cap_mbps, self.cap_gb):
            sb.valueChanged.connect(self._emit)
        self._update_cap_ui()
        self.out_dir.textChanged.connect(self._emit)
        self.filename.textChanged.connect(self._emit)
        for c in (self.tracklist, self.project_copy, self.own_folder, self.markers):
            c.toggled.connect(self._emit)

    # ---------- dữ liệu ----------
    def load(self, ex: ExportSettings) -> None:
        self._loading = True
        set_combo(self.preset, ex.preset)
        set_combo(self.resolution, ex.resolution)
        set_combo(self.fps, ex.fps)
        self._wanted_encoder = ex.encoder
        set_combo(self.encoder, ex.encoder)
        set_combo(self.quality, ex.quality)
        set_combo(self.audio, ex.audio)
        default_dir = str(Path.home() / "Videos")
        self.out_dir.setText(ex.output_dir or self.settings.value("pref/output_dir", "")
                             or self.settings.value("dir/output", default_dir))
        self.filename.setText(ex.filename)
        self.tracklist.setChecked(ex.tracklist)
        self.project_copy.setChecked(ex.save_project_copy)
        set_combo(self.cap, ex.bitrate_cap)
        self.cap_mbps.setValue(ex.cap_mbps)
        self.cap_gb.setValue(ex.cap_gb)
        self.own_folder.setChecked(ex.own_folder)
        self.markers.setChecked(ex.markers)
        self._update_cap_ui()
        self._loading = False

    def collect(self) -> ExportSettings:
        return ExportSettings(
            preset=self.preset.currentData(),
            resolution=self.resolution.currentData(),
            fps=self.fps.currentData(),
            encoder=(self.encoder.currentData() if self.encoder.isEnabled()
                     else getattr(self, "_wanted_encoder", "auto")) or "auto",
            quality=self.quality.currentData(),
            audio=self.audio.currentData(),
            output_dir=self.out_dir.text().strip(),
            filename=self.filename.text().strip(),
            tracklist=self.tracklist.isChecked(),
            save_project_copy=self.project_copy.isChecked(),
            bitrate_cap=self.cap.currentData() or "off",
            cap_mbps=self.cap_mbps.value(),
            cap_gb=self.cap_gb.value(),
            own_folder=self.own_folder.isChecked(),
            markers=self.markers.isChecked(),
        )

    def _update_cap_ui(self, *_) -> None:
        mode = self.cap.currentData()
        self.cap_mbps.setVisible(mode == "mbps")
        self.cap_gb.setVisible(mode == "size")

    def set_size(self, text: str, tip: str = "", busy: bool = False) -> None:
        """Dòng dự đoán dung lượng (busy: đang đo lại → chữ mờ đi)."""
        self.size_label.setText(text)
        self.size_label.setProperty("busy", busy)  # màu theo QSS (QLabel#sizeEst[busy=…])
        self.size_label.style().unpolish(self.size_label)
        self.size_label.style().polish(self.size_label)
        if tip:
            self.size_label.setToolTip(tip)

    def set_available(self, available: dict[str, list[str]]) -> None:
        self.available = available
        wanted = self.encoder.currentData() if self.encoder.isEnabled() else getattr(self, "_wanted_encoder", "auto")
        self._loading = True
        self.encoder.clear()
        self.encoder.addItem(encoders.VENDOR_LABELS["auto"], "auto")
        vendors = []
        for codec in encoders.ENCODERS:
            for v in available.get(codec, []):
                if v not in vendors:
                    vendors.append(v)
        for v in vendors:
            self.encoder.addItem(encoders.VENDOR_LABELS[v], v)
        set_combo(self.encoder, wanted)
        self.encoder.setEnabled(True)
        self._loading = False
        self._emit()

    def gpu_text(self) -> str:
        if self.available is None:
            return "Đang kiểm tra card đồ hoạ…"
        gpus = [encoders.VENDOR_LABELS[v].split(" ")[0] for v in self.available.get("h264", []) if v != "cpu"]
        return ("GPU: " + ", ".join(gpus)) if gpus else "Không dùng được GPU — sẽ mã hoá bằng CPU"

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)
        plain = re.sub(r"<br\s*/?>", " · ", text)
        plain = re.sub(r"<[^>]+>", "", plain)
        self.footer_info.set_full_text(plain)

    def free_bytes(self) -> int | None:
        d = self.out_dir.text().strip()
        try:
            while d and not os.path.isdir(d):
                d = os.path.dirname(d)
            return shutil.disk_usage(d).free if d else None
        except OSError:
            return None

    def free_space_text(self) -> str:
        d = self.out_dir.text().strip()
        try:
            while d and not os.path.isdir(d):
                d = os.path.dirname(d)
            free = shutil.disk_usage(d).free if d else 0
        except OSError:
            return ""
        return f"{free / 1024 ** 3:.1f} GB trống" if d else ""

    # ---------- trạng thái render ----------
    def set_empty(self, kind: str | None) -> None:
        """Màn hình trống ("video" | "music" | None): thay thẻ tóm tắt + cài đặt bằng một lời nhắc và một nút việc cần làm."""
        if kind == self._empty:
            return
        self._empty = kind
        on = kind is not None
        if on:
            music = kind == "music"
            self._empty_target = 1 if music else 0
            self.empty_text.setText("Thêm bài nhạc hoặc tiếng nền, rồi quay lại đây để xuất file nhạc." if music
                                    else "Thêm clip vào dự án, rồi quay lại đây để xuất video.")
            self.empty_btn.setText("Thêm nhạc" if music else "Thêm clip")
        self.empty_card.setVisible(on)
        self.summary_card.setVisible(not on)
        self._apply_mode_visibility()
        self._sync_footer()

    def _apply_mode_visibility(self) -> None:
        music = self.mode == "music_only"
        on = self._empty is not None
        self.g_video.setVisible(not on and not music)
        self.g_audio.setVisible(not on and music)
        self._top_widgets[2].setVisible(not on)

    def _sync_footer(self) -> None:
        self.footer.setVisible(self._empty is None or self._running)

    def set_can_export(self, ok: bool) -> None:
        self.set_empty(None)
        self._can_export = ok
        self.start_btn.setEnabled(ok and not self._running)
        self.queue_add_btn.setEnabled(ok)

    def set_running(self, running: bool, clear_log: bool = True) -> None:
        self._running = running
        self._sync_footer()
        self.start_btn.setEnabled(self._can_export and not running)
        self.queue_add_btn.setEnabled(self._can_export)
        pending = sum(1 for i in self.items if i.status == "pending")
        self.queue_run_btn.setEnabled(not running and pending > 0)
        self.cancel_btn.setEnabled(running)
        self.cancel_btn.setVisible(running)
        if running:
            self.prog_row.setVisible(True)
            self._shimmer.start()
        else:
            self._shimmer.stop()
        if running:
            self.open_out_btn.setEnabled(False)
            self.open_out_btn.setVisible(False)
            self._prog_anim.stop()
            self.progress.setValue(0)
            if clear_log:
                self.log.clear()

    def on_progress(self, frac: float, status: str) -> None:
        target_val = int(frac * 1000)
        self._prog_anim.stop()
        self._prog_anim.setStartValue(self.progress.value())
        self._prog_anim.setEndValue(target_val)
        self._prog_anim.start()
        self.status.setText(status)

    def append_log(self, line: str) -> None:
        self.log.appendPlainText(line)

    def done(self, output: str | None) -> None:
        self.last_output = output
        self.open_out_btn.setEnabled(bool(output))
        self.open_out_btn.setVisible(bool(output))

    def adapt(self, width: int, height: int = 0) -> None:
        narrow = width < 1100
        self.top_layout.setDirection(QHBoxLayout.Direction.TopToBottom if narrow
                                     else QHBoxLayout.Direction.LeftToRight)
        want = Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal
        if self.bottom_split.orientation() != want:
            self.bottom_split.setOrientation(want)
        self.bottom_split.setMinimumHeight(560 if narrow else 280)

    # ---------- kiểu sản phẩm ----------
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        music = mode == "music_only"
        video_only = mode == "video_only"
        self._apply_mode_visibility()
        self.tracklist.setEnabled(not video_only)
        self.project_copy.setVisible(True)
        self.start_btn.setText("Bắt đầu xuất file nhạc" if music else "Bắt đầu xuất video")
        self._update_audio_enabled()

    def load_audio_export(self, ms: MusicSettings) -> None:
        """Trang Xuất chỉ giữ định dạng file nhạc; độ dài nằm ở trang Nhạc."""
        self._loading = True
        set_combo(self.exp_format, ms.export_format)
        self._loading = False

    def fill_audio_export(self, ms: MusicSettings) -> None:
        ms.export_format = self.exp_format.currentData()

    def set_audio_info(self, text: str) -> None:
        self.exp_info.setText(text)

    def _update_audio_enabled(self) -> None:
        pass  # độ dài file nhạc đã chuyển sang trang Nhạc

    # ---------- hàng đợi ----------
    def set_queue(self, items: list[QueueItem]) -> None:
        self.items = items
        self.queue.clear()
        status_colors = {
            "done": "success_text",
            "running": "info_text",
            "error": "danger_text",
            "cancelled": "warn_text",
            "pending": "text_2",
        }
        for it in items:
            row = QTreeWidgetItem([it.project.name, KIND_LABELS.get(it.kind, it.kind),
                                   os.path.basename(it.output), STATUS_LABELS.get(it.status, it.status)])
            row.setToolTip(2, it.output)
            row.setToolTip(3, it.message)
            col = status_colors.get(it.status)
            if col:
                row.setForeground(3, theme.qcolor(col))
            self.queue.addTopLevelItem(row)
        pending = sum(1 for i in items if i.status == "pending")
        self.queue_run_btn.setText(f"Chạy hàng đợi ({pending})" if pending else "Chạy hàng đợi")
        self.queue_run_btn.setEnabled(not self._running and pending > 0)

    def set_queue_status(self, index: int, text: str) -> None:
        row = self.queue.topLevelItem(index)
        if row:
            row.setText(3, text)
            row.setForeground(3, theme.qcolor("info_text"))

    def _remove_selected(self) -> None:
        rows = sorted({self.queue.indexOfTopLevelItem(r) for r in self.queue.selectedItems()}, reverse=True)
        for r in rows:
            if self.items[r].status != "running":
                del self.items[r]
        self.set_queue(self.items)
        self.queueEdited.emit()

    def _queue_menu(self, pos) -> None:
        rows = sorted({self.queue.indexOfTopLevelItem(r) for r in self.queue.selectedItems()})
        if not rows:
            return
        again = [self.items[r] for r in rows if self.items[r].status in ("error", "cancelled")]
        menu = QMenu(self)
        act = menu.addAction(icons.icon("repeat", 14), f"Chạy lại ({len(again)} mục) — đặt về Đang chờ")
        act.setEnabled(bool(again))
        act.triggered.connect(lambda: self._requeue(again))
        menu.addAction(icons.icon("trash", 14), "Xoá mục chọn", self._remove_selected)
        menu.exec(self.queue.viewport().mapToGlobal(pos))

    def _requeue(self, items: list[QueueItem]) -> None:
        for it in items:
            it.status, it.message = "pending", ""
        self.set_queue(self.items)
        self.queueEdited.emit()

    def _remove_finished(self) -> None:
        self.items[:] = [i for i in self.items if not i.finished]
        self.set_queue(self.items)
        self.queueEdited.emit()

    def _move(self, delta: int) -> None:
        sel = self.queue.selectedItems()
        if not sel:
            return
        r = self.queue.indexOfTopLevelItem(sel[0])
        j = r + delta
        if 0 <= j < len(self.items):
            self.items[r], self.items[j] = self.items[j], self.items[r]
            self.set_queue(self.items)
            self.queue.topLevelItem(j).setSelected(True)
            self.queueEdited.emit()

    def _open_output(self) -> None:
        if self.last_output and os.path.exists(self.last_output):
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.last_output)])

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video", self.out_dir.text())
        if d:
            self.out_dir.setText(os.path.normpath(d))
            self.settings.setValue("dir/output", d)

    def _emit(self, *_) -> None:
        if not self._loading:
            self._update_audio_enabled()
            self.changed.emit()

