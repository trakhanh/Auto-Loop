"""Trang "Cắt video": thẻ Chia đoạn (cắt video dài thành nhiều đoạn ngắn để up hàng loạt) + thẻ Xuất ảnh.

Xem docs/superpowers/specs/2026-11-20-chia-video-xuat-khung-design.md. Lõi ở core/cutter.py. File ra chỉ nằm trong
thư mục lưu — không đưa vào bảng clip / playlist / dự án. Bố cục giống trang Tải video: trái = danh sách video +
nhật ký, phải = thẻ cài đặt, dưới = nút Bắt đầu / Dừng."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import fields
from pathlib import Path

from PySide6.QtCore import QObject, QPropertyAnimation, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QBoxLayout, QButtonGroup, QCheckBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QSpinBox, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core import cutter, ffmpeg_tools, probe
from ..core.cutter import FrameSettings, SplitSettings
from . import icons, theme
from . import widgets as w
from .download_page import PROG_ROLE, ProgressDelegate, Segmented, default_folder

PATH_ROLE = Qt.ItemDataRole.UserRole
TABS = (("split", "Chia đoạn"), ("frames", "Xuất ảnh"))
SPLIT_LABELS = {
    "parts": ("Chia thành số phần", "Chia đều video thành N đoạn bằng nhau"),
    "fixed": ("Mỗi đoạn dài", "Mỗi đoạn dài đúng bấy nhiêu; đoạn cuối dư ngắn hơn vẫn giữ (bỏ nếu dưới 1 giây)"),
    "random": ("Dài ngẫu nhiên", "Mỗi đoạn dài ngẫu nhiên trong khoảng — mỗi lần chạy ra cách chia khác"),
    "marks": ("Theo mốc thời gian", "Cắt tại các mốc, vd 00:01:15, 00:05:30 — mỗi mốc cách nhau dấu phẩy"),
    "ranges": ("Theo khoảng A-B", "Mỗi khoảng thành một đoạn, vd 00:01:10-00:01:45, 00:05:00-00:05:30"),
}
FRAME_LABELS = {
    "count": ("Tổng số ảnh", "Lấy đều đúng bấy nhiêu ảnh trên cả video"),
    "every_sec": ("Mỗi N giây", "Cứ mỗi N giây lấy một ảnh"),
    "every_n": ("Mỗi N khung hình", "Cứ mỗi N khung hình lấy một ảnh (video 30 khung/giây: 30 = mỗi giây)"),
    "scene": ("Theo chuyển động (%)", "Lấy ảnh khi hình thay đổi ít nhất bấy nhiêu % so với khung trước "
                                      "(đổi cảnh). Số nhỏ = nhiều ảnh. Ảnh đầu tiên luôn có."),
}
ASPECT_LABELS = (("keep", "Giữ nguyên"), ("9:16", "9:16"), ("16:9", "16:9"), ("1:1", "1:1"), ("4:5", "4:5"))
FIT_LABELS = (("blur", "Nền mờ"), ("black", "Viền đen"), ("crop", "Cắt"))
EXACT_LABELS = ((True, "Chính xác"), (False, "Nhanh"))
EXACT_TIPS = {True: "Cắt đúng từng giây, xử lý lại hình (card đồ hoạ nếu có). Đổi được tỉ lệ khung.",
              False: "Chép nguyên, không xử lý lại hình — gần như tức thì, giữ nguyên chất lượng, nhưng mỗi đoạn có "
                     "thể lệch 1–2 giây (cắt ở khung khoá gần nhất). Không đổi được tỉ lệ khung."}
FIT_TIPS = {"blur": "Hình gốc nằm giữa, phần trống là chính hình đó phóng to làm mờ (hợp TikTok / Shorts)",
            "black": "Hình gốc nằm giữa, phần trống là viền đen", "crop": "Cắt bớt hai bên để lấp đầy khung"}
FMT_LABELS = (("jpg", "JPG"), ("png", "PNG"))
STATUS_TONE = {"wait": "text_muted", "run": "accent_text", "done": "success_text", "warn": "warn_text",
               "error": "danger_text", "stopped": "warn_text"}
LOG_MAX = 500
MIN_FREE = 500 * 1024 * 1024  # dưới 500 MB trống: dừng trước video tiếp


class _Bridge(QObject):
    probed = Signal(str, object)  # (đường dẫn, MediaInfo)
    progress = Signal(str, float, str)  # (đường dẫn, 0..1, chữ)
    video_done = Signal(str, object, str, object)  # (đường dẫn, RunResult | None, lỗi / "stop", file đã tạo)
    all_done = Signal(str)  # lý do dừng sớm ("" = chạy hết)


def _load(settings: QSettings, prefix: str, obj):
    """Đọc các trường dataclass từ QSettings (`prefix/<trường>`), sai kiểu thì giữ mặc định."""
    for f in fields(obj):
        raw = settings.value(f"{prefix}/{f.name}")
        if raw is None:
            continue
        cur = getattr(obj, f.name)
        try:
            if isinstance(cur, bool):
                val = str(raw).lower() in ("true", "1")
            elif isinstance(cur, int):
                val = int(float(raw))
            elif isinstance(cur, float):
                val = float(raw)
            else:
                val = str(raw)
        except (TypeError, ValueError):
            continue
        setattr(obj, f.name, val)
    return obj


def _save(settings: QSettings, prefix: str, obj) -> None:
    for f in fields(obj):
        settings.setValue(f"{prefix}/{f.name}", getattr(obj, f.name))


def fmt_secs(sec: float) -> str:
    """Giây → "1 phút 12 giây" (nhật ký)."""
    s = int(round(sec))
    return f"{s // 60} phút {s % 60} giây" if s >= 60 else f"{s} giây"


class CutPage(QWidget):
    busyChanged = Signal(bool)
    counterChanged = Signal(str)
    notice = Signal(str, str)  # (văn bản, "ok" | "info" | "warn")

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.split = _load(settings, "cut/split", SplitSettings())
        self.frames = _load(settings, "cut/frames", FrameSettings())
        if self.split.mode not in cutter.SPLIT_MODES:
            self.split.mode = "fixed"
        if self.frames.mode not in cutter.FRAME_MODES:
            self.frames.mode = "count"
        self.infos: dict[str, probe.MediaInfo] = {}
        self.status: dict[str, dict[str, str]] = {"split": {}, "frames": {}}
        self.status_text: dict[str, dict[str, str]] = {"split": {}, "frames": {}}
        self._stopped: dict[tuple[str, str], tuple[Path, str, list[Path]]] = {}
        self._encoder = "libx264"
        self._busy = False
        self._runner: ffmpeg_tools.Runner | None = None
        self._loading = True
        self.b = _Bridge()
        self.b.probed.connect(self._on_probed)
        self.b.progress.connect(self._on_progress)
        self.b.video_done.connect(self._on_video_done)
        self.b.all_done.connect(self._on_all_done)
        self._run: dict = {}
        self._anim = QTimer(self)  # vẽ lại thanh tiến độ trong danh sách (vệt sáng chạy) khi đang chạy
        self._anim.setInterval(40)
        self._build()
        self._anim.timeout.connect(lambda: self.tree.viewport().update())
        self._fill_widgets()
        self._loading = False
        tab = str(settings.value("cut/tab", "split") or "split")
        self.set_tab(tab if tab in dict(TABS) else "split")
        try:
            saved = json.loads(str(settings.value("cut/files", "[]") or "[]"))
        except ValueError:
            saved = []
        self.add_files([p for p in saved if isinstance(p, str) and Path(p).is_file()])
        self.setAcceptDrops(True)
        self._refresh()

    # ---------- dựng giao diện ----------
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        theme.page_layout(lay)
        self.tabs = Segmented(TABS, "split", {"split": "Cắt video dài thành nhiều đoạn ngắn",
                                              "frames": "Lấy ảnh từ video"})
        self.tabs.setMaximumWidth(theme.px(360))
        self.tabs.currentIndexChanged.connect(lambda _i: self.set_tab(self.tabs.currentData()))
        lay.addWidget(self.tabs)

        self.body = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.body.setSpacing(theme.SP['lg'])
        left_w = QWidget()
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(theme.SP['sm'])
        tools = QHBoxLayout()
        self.add_btn = QPushButton("Thêm video")
        theme.tag(self.add_btn, variant="tonal")
        self.add_btn.setIcon(icons.icon("file_plus", 15, "accent_text"))
        self.add_btn.clicked.connect(self._pick_files)
        self.add_dir_btn = QPushButton("Thêm thư mục")
        theme.tag(self.add_dir_btn, variant="ghost")
        self.add_dir_btn.setIcon(icons.icon("folder", 15))
        self.add_dir_btn.setToolTip("Thêm mọi video trong một thư mục")
        self.add_dir_btn.clicked.connect(self._pick_dir)
        self.list_label = w.muted("")
        tools.addWidget(self.add_btn)
        tools.addWidget(self.add_dir_btn)
        tools.addWidget(self.list_label, 1)
        left.addLayout(tools)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Video", "Thời lượng", "Khung hình", "Trạng thái"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemChanged.connect(lambda *_: self._loading or self._refresh())
        self.tree.setItemDelegateForColumn(3, ProgressDelegate(self.tree))
        hd = self.tree.header()
        hd.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2):
            hd.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hd.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hd.resizeSection(3, theme.px(210))
        hd.setStretchLastSection(False)
        self.empty_view = self._build_empty()
        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.empty_view)
        self.list_stack.addWidget(self.tree)
        self.list_stack.setMinimumHeight(theme.px(180))
        left.addWidget(self.list_stack, 1)
        lab = QLabel("Nhật ký")
        lab.setObjectName("fieldLabel")
        left.addWidget(lab)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(LOG_MAX)
        self.log.setFixedHeight(theme.px(112))
        self.log.setPlaceholderText("Chưa có gì — bấm Bắt đầu để chạy")
        left.addWidget(self.log)
        self.body.addWidget(left_w, 1)

        self.side_stack = QStackedWidget()
        self.side_stack.addWidget(self._build_split_card())
        self.side_stack.addWidget(self._build_frames_card())
        self.side_scroll = QScrollArea()
        self.side_scroll.setWidget(self.side_stack)
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.side_scroll.setFixedWidth(theme.px(360))
        self.body.addWidget(self.side_scroll)
        lay.addLayout(self.body, 1)

        bar = QHBoxLayout()
        bar.setSpacing(theme.SP['md'])
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("h3")
        self.more_btn = QPushButton()
        theme.tag(self.more_btn, variant="ghost")
        self.more_btn.setIcon(icons.icon("more", 15))
        self.more_btn.setToolTip("Thêm")
        m = QMenu(self.more_btn)
        m.addAction("Bỏ video đã chọn khỏi danh sách", self.remove_selected)
        m.addAction("Xoá danh sách (không xoá file)", self.clear_list)
        self.more_btn.setMenu(m)
        self.open_btn = QPushButton("Mở thư mục")
        theme.tag(self.open_btn, variant="ghost")
        self.open_btn.setIcon(icons.icon("folder", 15))
        self.open_btn.clicked.connect(lambda: self._open_dir(self.folder(self.tab())))
        self.start_btn = QPushButton("Bắt đầu chia")
        theme.tag(self.start_btn, variant="primary")
        self.start_btn.setIcon(icons.icon("scissors", 16, "white"))
        self.start_btn.setMinimumHeight(theme.px(38))
        self.start_btn.setMinimumWidth(theme.px(170))
        self.start_btn.clicked.connect(lambda: self.stop() if self._busy else self.start())
        bar.addWidget(self.summary_label, 1)
        bar.addWidget(self.more_btn)
        bar.addWidget(self.open_btn)
        bar.addWidget(self.start_btn)
        self.run_bar = QProgressBar()
        self.run_bar.setRange(0, 1000)
        self.run_bar.setTextVisible(False)
        self.run_bar.setObjectName("thinBar")
        self.run_bar.setFixedHeight(6)
        self.run_bar.hide()
        self._run_anim = QPropertyAnimation(self.run_bar, b"value", self)
        self._run_anim.setDuration(260)
        lay.addWidget(self.run_bar)
        lay.addLayout(bar)

    def _build_empty(self) -> QWidget:
        box = QGroupBox()
        v = QVBoxLayout(box)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(theme.SP['md'])
        v.addStretch(1)
        ic = QLabel()
        icons.bind(ic, "scissors", 44, "accent_text")
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Kéo thả video hoặc thư mục vào đây")
        title.setObjectName("h2")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = w.muted("Hoặc bấm Thêm video. Một video hay nhiều video đều được — app chạy lần lượt.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for x in (ic, title, hint):
            v.addWidget(x)
        v.addStretch(1)
        return box

    def _section(self, lay: QVBoxLayout, text: str) -> None:
        lab = QLabel(text)
        lab.setObjectName("fieldLabel")
        lay.addSpacing(theme.SP['md'])
        lay.addWidget(lab)

    def _time_edit(self, tip: str) -> QLineEdit:
        e = QLineEdit()
        e.setPlaceholderText("00:00:30")
        e.setToolTip(tip)
        e.setMaximumWidth(theme.px(96))
        e.textChanged.connect(self._settings_changed)
        return e

    def _folder_row(self, v: QVBoxLayout, tab: str) -> tuple[w.ElidedLabel, QCheckBox, QCheckBox]:
        self._section(v, "Lưu vào")
        row = QHBoxLayout()
        row.setSpacing(6)
        lab = w.ElidedLabel("", Qt.TextElideMode.ElideMiddle)
        lab.setObjectName("pathBox")
        btn = QPushButton("Đổi")
        theme.tag(btn, variant="ghost")
        btn.clicked.connect(lambda: self.pick_folder(tab))
        row.addWidget(lab, 1)
        row.addWidget(btn)
        v.addLayout(row)
        per = QCheckBox("Thư mục riêng mỗi video")
        per.setToolTip("Mỗi video gốc ra một thư mục con mang tên video, không lẫn với nhau")
        after = QCheckBox("Mở thư mục khi xong")
        per.toggled.connect(self._settings_changed)
        after.toggled.connect(self._settings_changed)
        v.addWidget(per)
        v.addWidget(after)
        return lab, per, after

    def _build_split_card(self) -> QWidget:
        card = QGroupBox("Cài đặt chia đoạn")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 30, 14, 14)
        v.setSpacing(theme.SP['xs'])
        self._section(v, "Cách cắt")
        g = QGridLayout()
        g.setHorizontalSpacing(theme.SP['sm'])
        g.setVerticalSpacing(theme.SP['sm'])
        self.mode_group = QButtonGroup(self)
        self.mode_radio: dict[str, QRadioButton] = {}
        self.parts_spin = QSpinBox()
        self.parts_spin.setRange(2, 999)
        self.parts_spin.setMaximumWidth(theme.px(96))
        self.parts_spin.valueChanged.connect(self._settings_changed)
        self.fixed_edit = self._time_edit("Độ dài mỗi đoạn (giờ:phút:giây)")
        self.rmin_edit = self._time_edit("Ngắn nhất")
        self.rmax_edit = self._time_edit("Dài nhất")
        rnd = QHBoxLayout()
        rnd.setSpacing(4)
        rnd.addWidget(self.rmin_edit)
        rnd.addWidget(QLabel("~"))
        rnd.addWidget(self.rmax_edit)
        rnd.addStretch(1)
        self.marks_edit = QLineEdit()
        self.marks_edit.setPlaceholderText("Ví dụ: 00:01:15, 00:05:30, 00:12:00")
        self.ranges_edit = QLineEdit()
        self.ranges_edit.setPlaceholderText("Ví dụ: 00:01:10-00:01:45, 00:05:00-00:05:30")
        for e in (self.marks_edit, self.ranges_edit):
            e.textChanged.connect(self._settings_changed)
        inputs = {"parts": self.parts_spin, "fixed": self.fixed_edit, "random": rnd}
        row = 0
        for key in cutter.SPLIT_MODES:
            text, tip = SPLIT_LABELS[key]
            r = QRadioButton(text)
            r.setToolTip(tip)
            self.mode_group.addButton(r)
            self.mode_radio[key] = r
            r.toggled.connect(self._settings_changed)
            g.addWidget(r, row, 0)
            item = inputs.get(key)
            if isinstance(item, QHBoxLayout):
                g.addLayout(item, row, 1)
            elif item is not None:
                g.addWidget(item, row, 1)
            else:  # mốc / khoảng: ô dài, xuống dòng dưới
                row += 1
                g.addWidget(self.marks_edit if key == "marks" else self.ranges_edit, row, 0, 1, 2)
            row += 1
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        self.estimate_label = QLabel("")
        self.estimate_label.setObjectName("muted")
        self.estimate_label.setWordWrap(True)
        v.addSpacing(theme.SP['xs'])
        v.addWidget(self.estimate_label)

        self._section(v, "Chế độ xuất")
        self.exact_box = Segmented(EXACT_LABELS, True, EXACT_TIPS)
        v.addWidget(self.exact_box)
        self._section(v, "Tỉ lệ khung hình")
        self.aspect_box = Segmented(ASPECT_LABELS, "keep",
                                    {"keep": "Giữ nguyên khung hình gốc", "9:16": "Dọc — TikTok, Shorts, Reels",
                                     "16:9": "Ngang — YouTube", "1:1": "Vuông", "4:5": "Dọc 4:5 — Facebook, Instagram"})
        v.addWidget(self.aspect_box)
        self._section(v, "Khi đổi tỉ lệ")
        self.fit_box = Segmented(FIT_LABELS, "blur", FIT_TIPS)
        v.addWidget(self.fit_box)
        for sb in (self.exact_box, self.aspect_box, self.fit_box):
            sb.currentIndexChanged.connect(self._settings_changed)
        self.folder_label, self.per_video_chk, self.open_after_chk = self._folder_row(v, "split")
        v.addStretch(1)
        return card

    def _build_frames_card(self) -> QWidget:
        card = QGroupBox("Cài đặt xuất ảnh")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 30, 14, 14)
        v.setSpacing(theme.SP['xs'])
        self._section(v, "Cách lấy ảnh")
        g = QGridLayout()
        g.setHorizontalSpacing(theme.SP['sm'])
        g.setVerticalSpacing(theme.SP['sm'])
        self.frame_group = QButtonGroup(self)
        self.frame_radio: dict[str, QRadioButton] = {}
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 9999)
        self.sec_spin = QDoubleSpinBox()
        self.sec_spin.setRange(0.1, 3600)
        self.sec_spin.setDecimals(2)
        self.sec_spin.setSingleStep(0.5)
        self.n_spin = QSpinBox()
        self.n_spin.setRange(1, 100000)
        self.scene_spin = QSpinBox()
        self.scene_spin.setRange(1, 100)
        self.scene_spin.setSuffix(" %")
        spins = {"count": self.count_spin, "every_sec": self.sec_spin, "every_n": self.n_spin,
                 "scene": self.scene_spin}
        for i, key in enumerate(cutter.FRAME_MODES):
            text, tip = FRAME_LABELS[key]
            r = QRadioButton(text)
            r.setToolTip(tip)
            self.frame_group.addButton(r)
            self.frame_radio[key] = r
            r.toggled.connect(self._settings_changed)
            spins[key].setMaximumWidth(theme.px(96))
            spins[key].setToolTip(tip)
            spins[key].valueChanged.connect(self._settings_changed)
            g.addWidget(r, i, 0)
            g.addWidget(spins[key], i, 1)
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        self.frames_estimate = QLabel("")
        self.frames_estimate.setObjectName("muted")
        self.frames_estimate.setWordWrap(True)
        v.addSpacing(theme.SP['xs'])
        v.addWidget(self.frames_estimate)
        self._section(v, "Định dạng ảnh")
        self.fmt_box = Segmented(FMT_LABELS, "jpg", {"jpg": "Nhẹ, hợp đăng mạng", "png": "Không nén mất nét, file nặng"})
        self.fmt_box.currentIndexChanged.connect(self._settings_changed)
        v.addWidget(self.fmt_box)
        self.frames_folder_label, self.frames_per_video_chk, self.frames_open_after_chk = self._folder_row(v, "frames")
        v.addStretch(1)
        return card

    def _fill_widgets(self) -> None:
        """Cài đặt đã nhớ → ô nhập (lúc mở trang)."""
        s, f = self.split, self.frames
        self.mode_radio[s.mode].setChecked(True)
        self.parts_spin.setValue(s.parts)
        self.fixed_edit.setText(cutter.fmt_time(s.fixed))
        self.rmin_edit.setText(cutter.fmt_time(s.rmin))
        self.rmax_edit.setText(cutter.fmt_time(s.rmax))
        self.marks_edit.setText(s.marks)
        self.ranges_edit.setText(s.ranges)
        self.exact_box.setCurrentIndex(self.exact_box.findData(s.exact))
        self.aspect_box.setCurrentIndex(max(0, self.aspect_box.findData(s.aspect)))
        self.fit_box.setCurrentIndex(max(0, self.fit_box.findData(s.fit)))
        self.per_video_chk.setChecked(s.per_video)
        self.open_after_chk.setChecked(s.open_after)
        self.frame_radio[f.mode].setChecked(True)
        self.count_spin.setValue(f.count)
        self.sec_spin.setValue(f.every_sec)
        self.n_spin.setValue(f.every_n)
        self.scene_spin.setValue(f.scene)
        self.fmt_box.setCurrentIndex(max(0, self.fmt_box.findData(f.fmt)))
        self.frames_per_video_chk.setChecked(f.per_video)
        self.frames_open_after_chk.setChecked(f.open_after)
        for tab, lab in (("split", self.folder_label), ("frames", self.frames_folder_label)):
            lab.setText(self.folder(tab))
            lab.setToolTip(self.folder(tab))

    # ---------- thẻ, thư mục ----------
    def tab(self) -> str:
        return self.tabs.currentData() or "split"

    def set_tab(self, key: str) -> None:
        if self._busy and key != self.tab():
            self.tabs.setCurrentIndex(self.tabs.findData(self.tab()))
            return
        i = self.tabs.findData(key)
        if i < 0:
            return
        if self.tabs.currentIndex() != i:
            self.tabs.setCurrentIndex(i)  # gọi lại set_tab qua tín hiệu
            return
        self.side_stack.setCurrentIndex(i)
        self._paint_all()
        self._refresh()

    def folder(self, tab: str) -> str:
        key = "cut/folder" if tab == "split" else "cut/frames_folder"
        sub = "Chia video" if tab == "split" else "Xuất ảnh"
        return str(self.settings.value(key, "") or "") or str(Path(default_folder()) / sub)

    def pick_folder(self, tab: str) -> bool:
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu", self.folder(tab))
        if not d:
            return False
        self.settings.setValue("cut/folder" if tab == "split" else "cut/frames_folder", d)
        lab = self.folder_label if tab == "split" else self.frames_folder_label
        lab.setText(d)
        lab.setToolTip(d)
        return True

    def _open_dir(self, path: str) -> None:
        if Path(path).is_dir():
            w.open_with_default_app(path)
        else:
            self.notice.emit("Thư mục chưa có — chạy xong một lượt sẽ có", "info")

    # ---------- danh sách video ----------
    def _pick_files(self) -> None:
        start = str(self.settings.value("cut/last_dir", "") or "")
        files = w.pick_files(self, "Chọn video", w.VIDEO_EXTS, start)
        if files:
            self.settings.setValue("cut/last_dir", str(Path(files[0]).parent))
            self.add_files(files)

    def _pick_dir(self) -> None:
        d = w.pick_folder(self, "Chọn thư mục có video", str(self.settings.value("cut/last_dir", "") or ""))
        if d:
            self.settings.setValue("cut/last_dir", d)
            self.add_files([d])

    def _rows(self) -> list[QTreeWidgetItem]:
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def _row(self, path: str) -> QTreeWidgetItem | None:
        return next((r for r in self._rows() if r.data(0, PATH_ROLE) == path), None)

    def add_files(self, paths: list[str]) -> None:
        """Thêm video (thư mục → các file video cấp đầu). Trùng / không phải video thì bỏ qua."""
        if self._busy:
            return
        have = {r.data(0, PATH_ROLE) for r in self._rows()}
        new: list[str] = []
        for raw in paths:
            p = Path(raw)
            cands = sorted((x for x in p.iterdir() if x.is_file()), key=lambda x: x.name.lower()) \
                if p.is_dir() else [p]
            for c in cands:
                if c.suffix.lower() in w.VIDEO_EXTS and c.is_file():
                    key = str(c)
                    if key not in have:
                        have.add(key)
                        new.append(key)
        if not new:
            return
        self._loading = True
        for key in new:
            r = QTreeWidgetItem([Path(key).name, "", "", ""])
            r.setData(0, PATH_ROLE, key)
            r.setToolTip(0, key)
            r.setFlags(r.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            r.setCheckState(0, Qt.CheckState.Checked)
            self.tree.addTopLevelItem(r)
            self._paint(key)
        self._loading = False
        threading.Thread(target=self._probe_all, args=(new,), daemon=True).start()
        self._refresh()

    def _probe_all(self, paths: list[str]) -> None:
        for p in paths:
            self.b.probed.emit(p, probe.probe(p))

    def _on_probed(self, path: str, info) -> None:
        self.infos[path] = info
        r = self._row(path)
        if r is None:
            return
        self._loading = True
        if info.ok and info.has_video and info.duration > 0:
            r.setText(1, cutter.fmt_time(info.duration))
            r.setText(2, f"{info.width}×{info.height}")
        else:
            r.setText(1, "—")
            r.setText(2, "—")
            for tab in self.status:
                self.status[tab][path] = "error"
                self.status_text[tab][path] = "Không đọc được video"
        self._loading = False
        self._paint(path)
        self._refresh()

    def files(self) -> list[str]:
        """Các video đang tick (theo thứ tự danh sách)."""
        return [r.data(0, PATH_ROLE) for r in self._rows() if r.checkState(0) == Qt.CheckState.Checked]

    def _ready_files(self) -> list[str]:
        out = []
        for p in self.files():
            info = self.infos.get(p)
            if info is not None and info.ok and info.has_video and info.duration > 0:
                out.append(p)
        return out

    def remove_selected(self) -> None:
        if self._busy:
            return
        for r in self.tree.selectedItems():
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(r))
        self._refresh()

    def clear_list(self) -> None:
        if self._busy:
            return
        self.tree.clear()
        self._refresh()

    def _menu(self, pos) -> None:
        r = self.tree.itemAt(pos)
        if r is None:
            return
        path = r.data(0, PATH_ROLE)
        m = QMenu(self)
        m.addAction("Bỏ khỏi danh sách", self.remove_selected).setEnabled(not self._busy)
        m.addAction("Mở file gốc", lambda: w.open_with_default_app(path))
        m.addAction("Mở thư mục kết quả", lambda: self._open_dir(self.folder(self.tab())))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls() and not self._busy:
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        self.add_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # ---------- cài đặt ----------
    def _read_settings(self) -> str:
        """Ô nhập → self.split / self.frames. Trả câu lỗi của thẻ đang mở ("" = hợp lệ)."""
        s, f = self.split, self.frames
        s.mode = next((k for k, r in self.mode_radio.items() if r.isChecked()), s.mode)
        s.parts = self.parts_spin.value()
        s.marks = self.marks_edit.text()
        s.ranges = self.ranges_edit.text()
        s.exact = bool(self.exact_box.currentData())
        s.aspect = self.aspect_box.currentData() or "keep"
        s.fit = self.fit_box.currentData() or "blur"
        s.per_video = self.per_video_chk.isChecked()
        s.open_after = self.open_after_chk.isChecked()
        err = ""
        for attr, edit in (("fixed", self.fixed_edit), ("rmin", self.rmin_edit), ("rmax", self.rmax_edit)):
            try:
                setattr(s, attr, cutter.parse_time(edit.text()))
            except ValueError as e:
                if s.mode == ("fixed" if attr == "fixed" else "random"):
                    err = str(e)
        f.mode = next((k for k, r in self.frame_radio.items() if r.isChecked()), f.mode)
        f.count = self.count_spin.value()
        f.every_sec = self.sec_spin.value()
        f.every_n = self.n_spin.value()
        f.scene = self.scene_spin.value()
        f.fmt = self.fmt_box.currentData() or "jpg"
        f.per_video = self.frames_per_video_chk.isChecked()
        f.open_after = self.frames_open_after_chk.isChecked()
        return err

    def _settings_changed(self, *_a) -> None:
        if self._loading:
            return
        sender = self.sender()
        tab = "frames" if sender is not None and self.side_stack.widget(1).isAncestorOf(sender) else "split"
        self._read_settings()
        # đổi cài đặt → các dòng đã chạy của thẻ này về "Chờ" (lượt sau chạy lại theo cài đặt mới)
        for p in list(self.status[tab]):
            if self.status[tab][p] != "error" or self.infos.get(p) is None or self.infos[p].ok:
                self.status[tab].pop(p, None)
                self.status_text[tab].pop(p, None)
        self._paint_all()
        self._refresh()

    def save(self) -> None:
        self._read_settings()
        _save(self.settings, "cut/split", self.split)
        _save(self.settings, "cut/frames", self.frames)
        self.settings.setValue("cut/tab", self.tab())
        self.settings.setValue("cut/files", json.dumps([r.data(0, PATH_ROLE) for r in self._rows()],
                                                       ensure_ascii=False))

    # ---------- dự kiến + nút ----------
    def _first_info(self):
        ready = self._ready_files()
        return self.infos[ready[0]] if ready else None

    def _estimate(self) -> str:
        """Cập nhật dòng Dự kiến của 2 thẻ; trả câu lỗi của thẻ đang mở ("" = chạy được)."""
        err = self._read_settings()
        info = self._first_info()
        s = self.split
        split_err = err
        text = ""
        if not split_err:
            try:
                if info is None:
                    cutter.plan_segments(3600, s)  # kiểm tra ô gõ dù chưa có video
                    text = theme.span("muted", "Dự kiến: thêm video để xem số đoạn")
                else:
                    segs, note = cutter.plan_segments(info.duration, s)
                    avg = sum(x.dur for x in segs) / len(segs)
                    approx = "~" if s.mode in ("random", "marks", "ranges") or len(segs) > 1 else ""
                    text = f"Dự kiến: <b>{len(segs)} đoạn</b> · mỗi đoạn {approx}{fmt_secs(avg)}"
                    if len(self._ready_files()) > 1:
                        text += theme.span("muted", " (video đầu)")
                    if note:
                        text += "<br>" + theme.span("warn", note)
            except ValueError as e:
                split_err = str(e)
        if split_err:
            text = theme.span("error", split_err)
        self.estimate_label.setText(text)
        n = cutter.frame_estimate(info, self.frames) if info is not None else None
        if self.frames.mode == "scene":
            ftext = theme.span("muted", "Số ảnh tuỳ video (mỗi lần đổi cảnh một ảnh)")
        elif info is None:
            ftext = theme.span("muted", "Dự kiến: thêm video để xem số ảnh")
        else:
            ftext = f"Dự kiến: <b>~{n} ảnh</b>" + (theme.span("muted", " (video đầu)")
                                                    if len(self._ready_files()) > 1 else "")
        self.frames_estimate.setText(ftext)
        return split_err if self.tab() == "split" else ""

    def _refresh(self) -> None:
        if not hasattr(self, "start_btn"):
            return
        err = self._estimate()
        fast = not self.split.exact
        self.aspect_box.setEnabled(not fast and not self._busy)
        self.aspect_box.setToolTip("Đổi tỉ lệ cần chế độ Chính xác" if fast else "")
        self.fit_box.setEnabled(not fast and self.split.aspect != "keep" and not self._busy)
        has = self.tree.topLevelItemCount() > 0
        self.list_stack.setCurrentWidget(self.tree if has else self.empty_view)
        ready = self._ready_files()
        tab = self.tab()
        if self._busy:
            self.start_btn.setText("Dừng")
            self.start_btn.setEnabled(True)
        else:
            todo = [p for p in ready if self.status[tab].get(p) != "done"]
            again = bool(ready) and not todo
            verb = "Chia" if tab == "split" else "Xuất ảnh"
            if again:
                self.start_btn.setText("Chạy lại")
            elif tab == "split":
                self.start_btn.setText(f"Bắt đầu chia {len(todo)} video" if len(todo) > 1 else "Bắt đầu chia")
            else:
                self.start_btn.setText(f"Bắt đầu xuất ảnh {len(todo)} video" if len(todo) > 1
                                       else "Bắt đầu xuất ảnh")
            self.start_btn.setEnabled(bool(ready) and not err)
            self.start_btn.setToolTip(err or ("" if ready else f"Thêm video để {verb.lower()}"))
        n_all = self.tree.topLevelItemCount()
        self.list_label.setText(f"{n_all} video" + (f" · đã chọn {len(self.files())}" if n_all else ""))
        self.summary_label.setText("" if not ready else f"{len(ready)} video")

    # ---------- trạng thái từng dòng ----------
    def _paint(self, path: str, frac: float | None = None) -> None:
        r = self._row(path)
        if r is None:
            return
        tab = self.tab()
        st = self.status[tab].get(path, "wait")
        text = self.status_text[tab].get(path, "Chờ")
        self._loading = True
        r.setText(3, text)
        r.setForeground(3, theme.qcolor(STATUS_TONE.get(st, "text_muted")))
        r.setData(3, PROG_ROLE, frac if st == "run" else None)
        self._loading = False

    def _paint_all(self) -> None:
        for r in self._rows():
            self._paint(r.data(0, PATH_ROLE))

    # ---------- chạy (Task 5) ----------
    def is_busy(self) -> bool:
        return self._busy

    def set_encoders(self, available: dict) -> None:
        """Cửa sổ chính dò xong card đồ hoạ: chế độ Chính xác dùng H.264 bằng NVENC / QSV / AMF nếu có."""
        from ..core import encoders
        self._encoder = encoders.pick("h264", "auto", available)

    def _set_busy(self, on: bool) -> None:
        if on == self._busy:
            return
        self._busy = on
        theme.tag(self.start_btn, variant="stop" if on else "primary")
        self.start_btn.setIcon(icons.icon("stop" if on else "scissors", 16, "danger_text" if on else "white"))
        for wd in (self.add_btn, self.add_dir_btn, self.side_stack, self.tabs, self.more_btn):
            wd.setEnabled(not on)
        if on:
            self.run_bar.setValue(0)
            self.run_bar.show()
            self._anim.start()
        else:
            self._anim.stop()
            self.run_bar.hide()
        self._refresh()
        self.busyChanged.emit(on)

    def start(self) -> None:
        """Chạy các video đang tick chưa xong ở thẻ này (tất cả đã xong → chạy lại tất cả, ra thư mục mới)."""
        if self._busy:
            return
        self._refresh()
        if not self.start_btn.isEnabled():
            return
        tab = self.tab()
        ready = self._ready_files()
        todo = [p for p in ready if self.status[tab].get(p) != "done"] or ready
        folder = self.folder(tab)
        if not ffmpeg_tools.usable_dir(folder):
            self.notice.emit("Thư mục lưu không ghi được — chọn thư mục khác", "warn")
            if not self.pick_folder(tab) or not ffmpeg_tools.usable_dir(self.folder(tab)):
                return
            folder = self.folder(tab)
        self._read_settings()
        job = SplitSettings(**vars(self.split)) if tab == "split" else FrameSettings(**vars(self.frames))
        reuse = {p: self._stopped.pop((tab, p)) for p in todo if (tab, p) in self._stopped}
        for p in todo:
            self.status[tab][p] = "wait"
            self.status_text[tab][p] = "Chờ"
            self._paint(p)
        self._run = {"tab": tab, "todo": todo, "done": 0, "outputs": 0, "user_stop": False, "t0": {},
                     "folder": folder}
        self._runner = ffmpeg_tools.Runner()
        self._set_busy(True)
        self.counterChanged.emit(f"1/{len(todo)}")
        self._log(f"Bắt đầu {'chia' if tab == 'split' else 'xuất ảnh'} {len(todo)} video → {folder}")
        args = (self._runner, tab, todo, job, Path(folder), self._encoder, {p: self.infos[p] for p in todo}, reuse)
        threading.Thread(target=self._work, args=args, daemon=True).start()

    def _work(self, runner, tab, todo, job, folder, encoder, infos, reuse) -> None:
        """Luồng nền: lần lượt từng video. Không đụng giao diện — chỉ phát tín hiệu."""
        for p in todo:
            if runner.cancelled:
                break
            if 0 <= ffmpeg_tools.disk_free(folder) < MIN_FREE:
                self.b.all_done.emit("disk")
                return
            self.b.progress.emit(p, -1.0, "")
            old = reuse.get(p)
            if old is not None:  # lượt trước bị Dừng: dọn file chính lượt đó tạo, chạy lại đúng chỗ cũ
                for f in old[2]:
                    Path(f).unlink(missing_ok=True)
            spot = (old[0], old[1]) if old is not None else None

            def prog(frac, text, p=p):
                self.b.progress.emit(p, frac, text)
            try:
                if tab == "split":
                    segs, _note = cutter.plan_segments(infos[p].duration, job)
                    res = cutter.split_video(runner, p, infos[p], job, folder, encoder, segs, on_progress=prog,
                                             reuse=spot)
                else:
                    res = cutter.extract_frames(runner, p, infos[p], job, folder, on_progress=prog, reuse=spot)
                self.b.video_done.emit(p, res, "", None)
            except ffmpeg_tools.CancelledError as e:
                self.b.video_done.emit(p, None, "stop", (getattr(e, "folder", folder), getattr(e, "stem", ""),
                                                         list(getattr(e, "files", [])), getattr(e, "total", None)))
                break
            except ValueError as e:
                self.b.video_done.emit(p, None, str(e), None)
            except Exception as e:  # noqa: BLE001 — lỗi lạ của một video không làm hỏng cả lượt
                self.b.video_done.emit(p, None, f"Lỗi: {e}", None)
        self.b.all_done.emit("")

    def stop(self) -> None:
        if self._busy and self._runner is not None:
            self._run["user_stop"] = True
            self._runner.cancel()

    def _log(self, text: str) -> None:
        self.log.appendPlainText(f"{time.strftime('%H:%M')}  {text}")

    @staticmethod
    def _unit(tab: str) -> str:
        return "đoạn" if tab == "split" else "ảnh"

    def _on_progress(self, path: str, frac: float, text: str) -> None:
        if not self._busy:
            return
        tab = self._run["tab"]
        if self.status[tab].get(path) != "run":
            self._run["t0"][path] = time.monotonic()
            i = self._run["todo"].index(path) + 1 if path in self._run["todo"] else 1
            self.counterChanged.emit(f"{i}/{len(self._run['todo'])}")
        self.status[tab][path] = "run"
        if frac < 0:
            self.status_text[tab][path] = "Đang bắt đầu…"
        else:
            self.status_text[tab][path] = f"{int(frac * 100)}%" + (f" · {text}" if text else "")
        if tab == self.tab():
            self._paint(path, frac)
        total = len(self._run["todo"]) or 1
        val = int(1000 * (self._run["done"] + max(0.0, frac)) / total)
        if abs(val - self.run_bar.value()) >= 3:
            self._run_anim.stop()
            self._run_anim.setStartValue(self.run_bar.value())
            self._run_anim.setEndValue(max(0, min(1000, val)))
            self._run_anim.start()

    def _on_video_done(self, path: str, res, err: str, stopped) -> None:
        if not self._run:
            return
        tab = self._run["tab"]
        name = Path(path).name
        unit = self._unit(tab)
        self._run["done"] += 1
        spent = time.monotonic() - self._run["t0"].get(path, time.monotonic())
        if res is not None:
            n = len(res.files)
            self._run["outputs"] += n
            if res.errors and (n == 0 or res.total is None):
                self.status[tab][path] = "error"
                self.status_text[tab][path] = res.errors[0][:120]
                self._log(f"{name}: lỗi — {res.errors[0]}")
            elif res.errors:
                self.status[tab][path] = "warn"
                self.status_text[tab][path] = f"✓ {n}/{res.total} {unit} · {len(res.errors)} lỗi"
                self._log(f"{name} → {n}/{res.total} {unit} ({fmt_secs(spent)}) · {len(res.errors)} lỗi")
                for e in res.errors[:5]:
                    self._log(f"   {e}")
            else:
                self.status[tab][path] = "done"
                self.status_text[tab][path] = f"✓ {n} {unit}"
                self._log(f"{name} → {n} {unit} ({fmt_secs(spent)})")
        elif err == "stop":
            folder, stem, files, total = stopped
            self._stopped[(tab, path)] = (Path(folder), stem, [Path(f) for f in files])
            self.status[tab][path] = "stopped"
            of = f"/{total}" if total else ""
            self.status_text[tab][path] = f"Đã dừng ({len(files)}{of} {unit})"
            self._log(f"{name}: Đã dừng ({len(files)}{of} {unit} xong — chạy lại sẽ làm lại từ đầu)")
        else:
            self.status[tab][path] = "error"
            self.status_text[tab][path] = err[:120]
            self._log(f"{name}: {err}")
        if tab == self.tab():
            self._paint(path)

    def _on_all_done(self, reason: str) -> None:
        if not self._busy:
            return
        run = self._run
        tab = run["tab"]
        for p in run["todo"]:  # dòng chưa tới lượt (dừng sớm) về "Chờ"
            if self.status[tab].get(p) in ("wait", "run"):
                self.status[tab].pop(p, None)
                self.status_text[tab].pop(p, None)
        self._runner = None
        self._set_busy(False)
        self._paint_all()
        self.counterChanged.emit("")
        unit = self._unit(tab)
        if reason == "disk":
            self._log("Ổ đĩa sắp đầy (dưới 500 MB) — đã dừng")
            self.notice.emit("Ổ đĩa lưu sắp đầy — đã dừng. Dọn bớt rồi bấm Bắt đầu để chạy tiếp", "warn")
        elif run["user_stop"]:
            self.notice.emit("Đã dừng", "info")
        else:
            ok = sum(1 for p in run["todo"] if self.status[tab].get(p) == "done")
            self._log(f"Xong: {ok}/{len(run['todo'])} video → {run['outputs']} {unit}")
            self.notice.emit(f"Xong: {len(run['todo'])} video → {run['outputs']} {unit}",
                             "ok" if ok == len(run["todo"]) else "warn")
            after = self.split.open_after if tab == "split" else self.frames.open_after
            if after:
                self._open_dir(run["folder"])

    # ---------- cửa sổ chính ----------
    def shown(self) -> None:
        self._refresh()

    def _side_need(self) -> int:
        return max(theme.px(340), self.side_stack.minimumSizeHint().width()
                   + self.side_scroll.verticalScrollBar().sizeHint().width() + 4)

    def adapt(self, width: int, height: int = 0) -> None:
        """Rộng: cài đặt là cột bên phải. Hẹp: xếp xuống dưới danh sách, ẩn cột Khung hình."""
        narrow = width < max(theme.px(900), theme.px(420) + self._side_need() + theme.SP['lg'])
        if narrow:
            self.body.setDirection(QBoxLayout.Direction.TopToBottom)
            self.side_scroll.setMinimumWidth(0)
            self.side_scroll.setMaximumWidth(16777215)
            self.side_scroll.setMinimumHeight(self.side_stack.currentWidget().sizeHint().height())
        else:
            self.body.setDirection(QBoxLayout.Direction.LeftToRight)
            self.side_scroll.setMinimumHeight(0)
            self.side_scroll.setFixedWidth(self._side_need())
        self.tree.setColumnHidden(2, width < theme.px(760))
