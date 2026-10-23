"""Tab Video: danh sách clip, số lần phát, crossfade, thứ tự, độ dài, intro/outro, âm thanh gốc."""
from __future__ import annotations

import os
import random
from pathlib import Path

import shiboken6
from PySide6.QtCore import QTimer, QRegularExpression, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPixmap, QRegularExpressionValidator, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSplitter, QTabWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core.probe import MediaInfo
from ..core.project import ClipItem, VideoSettings, format_hms, parse_hms
from . import effects, icons, motion, theme
from . import widgets as w
from .timeline_bar import TimelineBar
from .interleave_dialog import InterleaveDialog, has_base_candidate
from .trim_dialog import MIN_KEEP, TrimDialog, trim_text

COL_NAME, COL_INFO, COL_TRIM, COL_PLAYS, COL_STRETCH, COL_LOOPXF, COL_NEXTXF, COL_DUR = range(8)

ORDER = [("list", "Theo thứ tự trong bảng"), ("shuffle", "Ngẫu nhiên (xáo khi xuất)")]
LENGTH = [("manual", "Thủ công — đúng số lần phát trong bảng"),
          ("target", "Thời lượng mục tiêu (ví dụ 1h, 3h, 10h)"),
          ("music", "Theo độ dài nhạc (1 lượt playlist)")]
FILL = [("repeat_sequence", "Lặp lại cả chuỗi (V1→Vn, V1→Vn…)"),
        ("stretch_marked", "Tăng số lần phát của clip tick 'Tự giãn'")]
FIT = [("letterbox", "Viền đen (giữ nguyên tỉ lệ)"), ("blur", "Nền mờ (đẹp cho clip dọc/khác tỉ lệ)"),
       ("crop", "Cắt cho đầy khung hình"), ("stretch", "Kéo giãn đầy khung")]
SOURCE = [("mix", "Giữ tiếng gốc clip, trộn với nhạc (mặc định)"), ("only", "Chỉ tiếng gốc clip — không dùng nhạc"),
          ("off", "Tắt tiếng gốc clip")]


def combo(options: list[tuple[str, str]]) -> QComboBox:
    cb = QComboBox()
    cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    cb.setMinimumContentsLength(10)
    for key, label in options:
        cb.addItem(label, key)
    return cb


def set_combo(cb: QComboBox, key: str) -> None:
    cb.setCurrentIndex(max(0, cb.findData(key)))


def hms_edit() -> QWidget:
    """Ô thời lượng 3 ô giờ / phút / giây — xem widgets.DurationEdit."""
    return w.DurationEdit()


def quick_buttons(target: QWidget, presets) -> QVBoxLayout:
    """Ô thời lượng (giờ / phút / giây) + hàng nút đặt nhanh bên dưới."""
    box = QVBoxLayout()
    box.setSpacing(theme.SP['sm'])
    box.addWidget(target)
    row = QHBoxLayout()
    row.setSpacing(4)
    box.addLayout(row)
    for label, sec in presets:
        b = QPushButton(label)
        b.setObjectName("pill")
        b.setMaximumWidth(44)
        b.setToolTip(f"Đặt nhanh {format_hms(sec)}")
        b.clicked.connect(lambda _=False, s=sec: target.setText(format_hms(s)))
        row.addWidget(b)
    row.addStretch(1)
    return box


def flow_row(hbox: QHBoxLayout) -> QWidget:
    """Chuyển một hàng QHBoxLayout thành hàng tự xuống dòng (FlowLayout). Nhãn được dính với ô nhập ngay sau
    nó để khi xuống dòng không bị tách rời."""
    widgets = [hbox.itemAt(i).widget() for i in range(hbox.count()) if hbox.itemAt(i).widget()]
    box = QWidget()
    fl = w.FlowLayout(box, spacing=6)
    group: list[QWidget] = []
    for wd in widgets:
        group.append(wd)
        if isinstance(wd, QLabel):
            continue  # chờ ô nhập / nút phía sau
        if len(group) == 1:
            fl.addWidget(wd)
        else:
            pair = QWidget()
            pl = QHBoxLayout(pair)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(6)
            for g in group:
                pl.addWidget(g)
            fl.addWidget(pair)
        group = []
    for g in group:
        fl.addWidget(g)
    return box


def slider_spin_row(spin: QSpinBox) -> QWidget:
    """Thanh trượt đi kèm ô số % đồng bộ hai chiều."""
    wrap = QWidget()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    sl = QSlider(Qt.Orientation.Horizontal)
    sl.setRange(spin.minimum(), spin.maximum())
    sl.setValue(spin.value())
    sl.valueChanged.connect(spin.setValue)
    spin.valueChanged.connect(sl.setValue)
    spin.setMinimumWidth(78)
    lay.addWidget(sl, 1)
    lay.addWidget(spin)
    return wrap


class BookendRow(QWidget):
    """Chọn file intro/outro + crossfade."""
    changed = Signal()

    def __init__(self, title: str, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings, self.title = settings, title
        self._path = ""
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.path.setPlaceholderText("Chưa chọn file")
        self.path.setMinimumWidth(110)
        pick = QPushButton("Chọn…")
        pick.setObjectName("pill")
        pick.clicked.connect(self._pick)
        self.clear = QPushButton("Xoá")
        self.clear.setObjectName("ghost")
        self.clear.setToolTip("Bỏ " + title.lower())
        self.clear.setEnabled(False)
        self.clear.clicked.connect(lambda: self.set_path(""))
        self.xf = w.xf_spin()
        self.xf.setMaximumWidth(84)
        self.xf.setEnabled(False)
        self.xf.setToolTip("Crossfade nối " + title.lower() + " với phần chính")
        self.xf.valueChanged.connect(lambda *_: self.changed.emit())
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self.path, 1)
        row.addWidget(pick)
        row.addWidget(self.clear)
        row.addWidget(self.xf)

    def value(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        self._path = path
        has_file = bool(path)
        self.path.setText(Path(path).name if has_file else "")
        self.path.setToolTip(path)
        self.clear.setEnabled(has_file)
        self.xf.setEnabled(has_file)
        self.changed.emit()

    def _pick(self) -> None:
        files = w.pick_files(self, f"Chọn {self.title.lower()}", w.VISUAL_EXTS, self.settings.value("dir/clips", ""))
        if files:
            self.set_path(os.path.normpath(files[0]))


class VideoTab(QWidget):
    changed = Signal()
    previewSeamRequested = Signal(int)
    switchModeRequested = Signal(str)
    notify = Signal(str, str)  # (nội dung, kiểu ok|info|warn|error) → thông báo nổi của cửa sổ chính
    nextStepRequested = Signal()
    mixerRequested = Signal()  # mở Bảng trộn âm (trang 2)

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._loading = False
        self._prober = None
        self._mode = "video_music"

        # ----- bảng clip -----
        self.list = w.MediaList(["Clip", "Thông tin nguồn", "Đoạn lấy", "Số lần phát", "Tự giãn",
                                 "Nối loop", "Sang clip", "Thời lượng"])
        self.list.setObjectName("clips")
        self.list.setIconSize(QSize(w.ThumbLoader.W, w.ThumbLoader.H))
        self.list.placeholder = (
            "Chưa có video hoặc ảnh nào trong dự án\n"
            "Bấm trực tiếp vào khung này hoặc kéo thả file / thư mục vào đây để bắt đầu"
        )
        self.thumbs = w.ThumbLoader(self)
        self._thumb_waiting: dict[str, list] = {}  # đường dẫn → các dòng đang chờ ảnh nhỏ
        self.thumbs.image.connect(self._on_thumb)
        self.list.setItemDelegateForColumn(COL_PLAYS, w.PlaysDelegate(self.list))
        self.list.setItemDelegateForColumn(COL_LOOPXF, w.XfadeDelegate(self.list))
        self.list.setItemDelegateForColumn(COL_NEXTXF, w.XfadeDelegate(self.list))
        # cột tên vẽ 2 dòng (tên + thông số) nên cột "Thông tin nguồn" riêng được ẩn đi cho rộng chỗ
        self.list.setItemDelegateForColumn(COL_NAME, w.TwoLineNameDelegate(self.list))
        self.list.setColumnHidden(COL_INFO, True)
        hdr = self.list.header()
        hdr.setStretchLastSection(False)
        hdr.setMinimumSectionSize(56)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col in (COL_TRIM, COL_PLAYS, COL_STRETCH, COL_LOOPXF, COL_NEXTXF, COL_DUR):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)  # luôn vừa chữ, không bị cắt
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        head = self.list.headerItem()
        head.setToolTip(COL_PLAYS, "Bấm đúp để sửa. 70 = phát 70 lần · 1 = không loop · 0 = bỏ qua · "
                                   "50-80 = ngẫu nhiên từ 50 đến 80 · 10p / 10:00 = loop cho đủ 10 phút "
                                   "(cũng nhận 90s, 1h, 1:30:00)")
        head.setToolTip(COL_TRIM, "Bấm đúp để chọn đoạn lấy: bỏ phần đầu / phần cuối, chỉ dùng đoạn giữa của clip")
        head.setToolTip(COL_NAME, "Tên file và thông số của clip (độ phân giải · fps · thời lượng gốc)")
        head.setToolTip(COL_LOOPXF, "Crossfade giữa các lần loop của clip này. Cắt = nối thẳng")
        head.setToolTip(COL_NEXTXF, "Crossfade khi chuyển sang clip kế tiếp. Cắt = nối thẳng")
        head.setTextAlignment(COL_NAME, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.changed.connect(self._emit)
        self.list.filesDropped.connect(self.add_paths)
        self.list.emptyClicked.connect(self._add_files)
        self.list.openRequested.connect(w.open_with_default_app)
        self.list.itemDoubleClicked.connect(self._on_double_click)
        self.list.menu_extras = [("scissors", "Chọn đoạn lấy (cắt đầu/cuối)…", self._open_trim),
                                 ("copy", "Nhân bản dòng (Ctrl+D) — dùng lại clip này ở chỗ khác", self._duplicate),
                                 ("copy", "Chép các dòng đang chọn (Ctrl+C)", lambda _it: self._copy_rows()),
                                 ("file_plus", "Dán bên dưới (Ctrl+V)", lambda _it: self._paste_rows()),
                                 ("repeat", "Xen kẽ clip nền giữa các cảnh…", lambda _it: self._open_interleave())]
        self.toolbar = w.ListToolbar(self.list, self._add_files, self._add_folder, random.Random)

        # ----- thanh đặt nhanh (Quick Action Bar) -----
        self.bulk = QLineEdit("70")
        self.bulk.setMaximumWidth(74)
        self.bulk.setValidator(QRegularExpressionValidator(QRegularExpression(w.PLAYS_RE)))
        self.bulk.setProperty("selectOnFocus", True)
        self.bulk.setToolTip("Nhập số lần (70), khoảng ngẫu nhiên (50-80), hoặc thời lượng muốn loop (10p, 10:00, 1h)")
        self.bulk.returnPressed.connect(self._apply_bulk)
        b_apply = QPushButton("Áp dụng")
        b_apply.setToolTip("Gán số lần phát này cho các dòng đang chọn")
        b_apply.clicked.connect(self._apply_bulk)

        st_on = QPushButton("Bật tự giãn")
        st_on.setObjectName("pill")
        st_on.setIcon(icons.icon("check", 13))
        st_on.setIconSize(QSize(13, 13))
        st_on.setToolTip("Đánh dấu Tự giãn cho các dòng đang chọn")
        st_on.clicked.connect(lambda: self._set_stretch(True))
        st_off = QPushButton("Bỏ giãn")
        st_off.setObjectName("pill")
        st_off.setToolTip("Bỏ đánh dấu Tự giãn cho các dòng đang chọn")
        st_off.clicked.connect(lambda: self._set_stretch(False))
        self.stretch_buttons = (st_on, st_off)

        self.bulk_loop = w.xf_spin()
        self.bulk_next = w.xf_spin()
        self.bulk_loop.setValue(1.0)
        self.bulk_next.setValue(1.0)
        x_apply = QPushButton("Áp dụng nối")
        x_apply.setToolTip("Gán thời gian crossfade cho các dòng đang chọn")
        x_apply.clicked.connect(self._apply_xfade)
        x_clear = QPushButton("Bỏ nối")
        x_clear.setObjectName("pill")
        x_clear.setToolTip("Bỏ crossfade: các dòng đang chọn quay về nối thẳng (Cắt) ở cả 2 cột")
        x_clear.clicked.connect(lambda: self._apply_xfade(clear=True))
        self.undo_btn = QPushButton("Hoàn tác")
        self.undo_btn.setObjectName("pill")
        self.undo_btn.setIcon(icons.icon("undo", 13))
        self.undo_btn.setIconSize(QSize(13, 13))
        self.undo_btn.setToolTip("(Ctrl+Z) Quay lại bước trước trong bảng clip: số lần phát, cắt đoạn, nối, "
                                 "nhân bản, xoá dòng, đổi thứ tự…")
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.undo)
        undo_key = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_key.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo_key.activated.connect(self.undo)
        self._history: list[list[ClipItem]] = []
        self._restoring = False
        self._hist_timer = QTimer(self)
        self._hist_timer.setSingleShot(True)
        self._hist_timer.setInterval(250)
        self._hist_timer.timeout.connect(self._push_history)
        preview_btn = QPushButton("Xem thử nối")
        preview_btn.setObjectName("accentBtn")
        preview_btn.setIcon(icons.icon("play", 13, "accent_text"))
        preview_btn.setIconSize(QSize(13, 13))
        preview_btn.setToolTip("Xuất nhanh đoạn ngắn (clip đang chọn phát 2 lần rồi chuyển sang clip kế) để kiểm tra crossfade")
        preview_btn.clicked.connect(self._preview_seam)

        quick_bar = QWidget()
        quick_bar.setObjectName("quickBar")
        gl = QVBoxLayout(quick_bar)
        gl.setContentsMargins(theme.SP['lg'], theme.SP['md'], theme.SP['lg'], theme.SP['md'])
        gl.setSpacing(6)

        r1 = QHBoxLayout()
        r1.setSpacing(6)
        fast_ic = QLabel()
        fast_ic.setPixmap(icons.pixmap("sliders", 14, theme.T['accent_text']))
        lbl_fast = QLabel("Đặt nhanh (dòng chọn):")
        lbl_fast.setProperty("role", "strong")
        r1.addWidget(fast_ic)
        r1.addWidget(lbl_fast)
        r1.addWidget(QLabel("Số lần phát:"))
        r1.addWidget(self.bulk)
        for p_txt, p_val in (("×1", "1"), ("×10", "10"), ("×70", "70"), ("10p", "10p"), ("1h", "1h")):
            pb = QPushButton(p_txt)
            pb.setObjectName("pill")
            pb.setToolTip(f"Loop cho đủ {p_val.replace('p', ' phút').replace('h', ' giờ')} cho dòng đang chọn"
                          if not p_val.isdigit() else f"Đặt nhanh {p_val} lần phát cho dòng đang chọn")
            pb.clicked.connect(lambda _=False, v=p_val: self._quick_plays(v))
            r1.addWidget(pb)
        r1.addWidget(b_apply)
        r1.addSpacing(8)
        r1.addWidget(st_on)
        r1.addWidget(st_off)
        r1.addStretch(1)
        self.more_tools = QPushButton("Cắt đoạn && hoà hình ▾")
        self.more_tools.setObjectName("ghost")
        self.more_tools.setCheckable(True)
        self.more_tools.setToolTip("Hiện thêm: bỏ đầu / bỏ cuối clip, nhân bản dòng, crossfade nối loop / sang clip, "
                                   "xem thử chỗ nối")
        r1.addWidget(self.more_tools)
        r1.addWidget(self.undo_btn)

        self.bulk_cut_start = QDoubleSpinBox()
        self.bulk_cut_end = QDoubleSpinBox()
        for sb in (self.bulk_cut_start, self.bulk_cut_end):
            sb.setRange(0, 600)
            sb.setDecimals(1)
            sb.setSingleStep(0.5)
            sb.setSuffix(" s")
            sb.setMaximumWidth(84)
            sb.setValue(2.0)
        cut_apply = QPushButton("Áp dụng cắt")
        cut_apply.setToolTip("Bỏ số giây này ở đầu và cuối của các clip đang chọn (chỉ lấy đoạn giữa)")
        cut_apply.clicked.connect(self._apply_cut)
        cut_reset = QPushButton("Lấy toàn bộ")
        cut_reset.setObjectName("pill")
        cut_reset.setToolTip("Bỏ cắt: dùng nguyên clip cho các dòng đang chọn")
        cut_reset.clicked.connect(lambda: self._apply_cut(reset=True))
        dup_btn = QPushButton("Nhân bản")
        dup_btn.setIcon(icons.icon("copy", 13))
        dup_btn.setIconSize(QSize(13, 13))
        dup_btn.setToolTip("(Ctrl+D) Tạo bản sao của clip đang chọn ngay bên dưới — dùng khi muốn phát lại clip đó ở chỗ khác, "
                           "ví dụ A 10 phút → B → A 10 phút")
        dup_btn.clicked.connect(self._duplicate_selected)
        dup_key = QShortcut(QKeySequence("Ctrl+D"), self.list)
        dup_key.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        dup_key.activated.connect(self._duplicate_selected)
        # Ctrl+C / Ctrl+V: chép các dòng đang chọn rồi dán xuống dưới dòng đang chọn (giữ số lần phát, cắt, crossfade).
        # Chỉ khi đang chọn trong bảng (đang sửa chữ trong một ô thì Ctrl+C / V vẫn là chép / dán chữ như thường).
        self._clipboard: list[tuple] = []
        for seq, fn in ((QKeySequence.StandardKey.Copy, self._copy_rows), (QKeySequence.StandardKey.Paste, self._paste_rows)):
            sc = QShortcut(QKeySequence(seq), self.list)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(fn)
        cut_dialog = QPushButton("Chọn đoạn…")
        cut_dialog.setIcon(icons.icon("scissors", 13))
        cut_dialog.setIconSize(QSize(13, 13))
        cut_dialog.setToolTip("Mở hộp thoại kéo chọn đoạn lấy, có ảnh khung đầu/cuối và xem thử")
        cut_dialog.clicked.connect(self._open_trim_selected)
        r_cut = QHBoxLayout()
        r_cut.setSpacing(6)
        cut_ic = QLabel()
        cut_ic.setPixmap(icons.pixmap("scissors", 14, theme.T['accent_text']))
        r_cut.addWidget(cut_ic)
        r_cut.addWidget(QLabel("Cắt đoạn:  Bỏ đầu"))
        r_cut.addWidget(self.bulk_cut_start)
        r_cut.addWidget(QLabel("Bỏ cuối"))
        r_cut.addWidget(self.bulk_cut_end)
        r_cut.addWidget(cut_apply)
        r_cut.addWidget(cut_reset)
        r_cut.addStretch(1)
        r_cut.addWidget(dup_btn)
        r_cut.addWidget(cut_dialog)

        r2 = QHBoxLayout()
        r2.setSpacing(6)
        r2.addWidget(QLabel("Hoà hình:"))
        r2.addWidget(QLabel("Nối loop"))
        r2.addWidget(self.bulk_loop)
        r2.addWidget(QLabel("Sang clip"))
        r2.addWidget(self.bulk_next)
        r2.addWidget(x_apply)
        r2.addWidget(x_clear)
        r2.addStretch(1)
        r2.addWidget(preview_btn)
        rows = [flow_row(row) for row in (r1, r_cut, r2)]  # tự xuống dòng khi khung hẹp → nút không bị cắt chữ
        for box in rows:
            gl.addWidget(box)
        # hàng cắt đoạn + chuyển cảnh: gấp lại cho gọn, bấm nút để mở (nhớ lựa chọn)
        self._extra_rows = rows[1:]

        def show_more(on: bool) -> None:
            for box in self._extra_rows:
                if box.isVisible() != on and self.isVisible():
                    motion.slide_visible(box, on, 200)  # mở / gấp mượt
                else:
                    box.setVisible(on)
            self.more_tools.setText("Cắt đoạn && hoà hình ▴" if on else "Cắt đoạn && hoà hình ▾")
            self.settings.setValue("ui/video_more_tools", "true" if on else "false")

        self.more_tools.toggled.connect(show_more)
        self.more_tools.setChecked(self.settings.value("ui/video_more_tools", "false") in (True, "true"))
        show_more(self.more_tools.isChecked())

        self.count_label = QLabel("0 clip")
        self.count_label.setObjectName("chip")
        self.status = w.muted("")
        hint = w.muted("Kéo dòng để đổi thứ tự · Bấm đúp tên file để mở xem · Bấm đúp ô số để sửa · "
                       "Chuột phải mở menu · Ctrl+A chọn hết")

        # Khu vực xem trước thứ tự phát có thể thu gọn/mở rộng
        self.preview = QPlainTextEdit()
        self.preview.setMinimumHeight(74)
        self.preview.setMaximumHeight(130)
        self.preview.setReadOnly(True)
        self.preview.setMaximumBlockCount(500)
        self.preview.setVisible(False)

        self.preview_toggle = QPushButton("Xem chi tiết từng lượt phát")
        self.preview_toggle.setObjectName("ghost")
        self.preview_toggle.setIcon(icons.icon("eye", 14))
        self.preview_toggle.setIconSize(QSize(14, 14))
        self.preview_toggle.setCheckable(True)
        self.preview_toggle.toggled.connect(self._toggle_preview)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        top_bar = QHBoxLayout()
        top_title = QLabel("Danh sách Clip & Ảnh")
        top_title.setObjectName("h2")
        top_bar.addWidget(top_title)
        top_bar.addWidget(self.count_label)
        top_bar.addStretch(1)
        top_bar.addWidget(self.status)
        self.interleave_btn = QPushButton("Xen kẽ clip nền…")
        self.interleave_btn.setObjectName("pill")
        self.interleave_btn.setIcon(icons.icon("repeat", 13))
        self.interleave_btn.setIconSize(QSize(13, 13))
        self.interleave_btn.setToolTip("Tự dựng bảng theo mẫu nền ×70 → cảnh 2 → nền ×70 → cảnh 3 … dựa theo tên file "
                                       "(clip nền có chữ 'loop' trong tên, cảnh chèn xếp theo số đầu tên)")
        self.interleave_btn.clicked.connect(self._open_interleave)
        top_bar.addWidget(self.interleave_btn)
        self.sequence_btn = QPushButton("Xếp lần lượt…")
        self.sequence_btn.setObjectName("pill")
        self.sequence_btn.setIcon(icons.icon("sort", 13))
        self.sequence_btn.setIconSize(QSize(13, 13))
        self.sequence_btn.setToolTip("Content → Loop1 ×60 → Loop2 ×60 → … : phát lần lượt từng clip loop theo tên, mỗi "
                                     "cái lặp N lần, clip nội dung (không có chữ 'loop') ở đầu / cuối")
        self.sequence_btn.clicked.connect(self._open_sequence)
        top_bar.addWidget(self.sequence_btn)
        lv.addLayout(top_bar)
        lv.addWidget(self.toolbar)
        # gợi ý khi vừa thêm file có clip nền (loop…) cùng các cảnh khác
        self.suggest = QFrame()
        self.suggest.setObjectName("suggestBar")
        sg = QHBoxLayout(self.suggest)
        sg.setContentsMargins(10, 6, 6, 6)
        sg_ic = QLabel()
        sg_ic.setPixmap(icons.pixmap("repeat", 14, theme.T['accent_text']))
        sg.addWidget(sg_ic)
        self.suggest_text = QLabel()
        self.suggest_text.setWordWrap(True)
        sg.addWidget(self.suggest_text, 1)
        self.suggest_go = sg_go = QPushButton("Xen kẽ ngay…")
        sg_go.setObjectName("accentBtn")
        sg_go.clicked.connect(lambda: self._open_sequence() if self._suggest_kind == "sequence"
                              else self._open_interleave())
        self._suggest_kind = "interleave"
        sg.addWidget(sg_go)
        sg_close = QPushButton("Để sau")
        sg_close.setObjectName("ghost")
        sg_close.clicked.connect(lambda: motion.slide_visible(self.suggest, False))
        sg.addWidget(sg_close)
        self.suggest.setVisible(False)
        lv.addWidget(self.suggest)
        self.list.setMinimumHeight(210)
        lv.addWidget(self.list, 1)
        lv.addWidget(quick_bar)
        foot = QHBoxLayout()
        foot.addWidget(hint, 1)
        foot.addWidget(self.preview_toggle)
        lv.addLayout(foot)
        lv.addWidget(self.preview)

        # ----- Cột phải: Cài đặt chia thành 2 tab gọn gàng, không phải cuộn dài -----
        # 1. Độ dài video
        self.length_mode = combo(LENGTH)
        self.target = hms_edit()
        self.fill = combo(FILL)
        self.reshuffle = QCheckBox("Mỗi lượt lặp lại xáo thứ tự mới")
        self.exact_end = QCheckBox("Cắt chính xác đúng thời lượng đích (kèm mờ dần)")
        self.stretch_hint = w.muted("Tick cột <b>Tự giãn</b> trong bảng cho các clip được phép tăng số lần phát. "
                                    "Clip không tick sẽ giữ nguyên số lần phát.")
        g_len = QGroupBox("Độ dài tổng của video")
        self.form_len = QFormLayout(g_len)
        self.form_len.setVerticalSpacing(8)
        self.form_len.addRow("Chế độ độ dài", self.length_mode)
        self.target_wrap = QWidget()
        self.target_wrap.setLayout(quick_buttons(
            self.target, (("30p", 1800), ("1h", 3600), ("2h", 7200), ("3h", 10800), ("10h", 36000))
        ))
        self.target_wrap.layout().setContentsMargins(0, 0, 0, 0)
        self.lbl_target = QLabel("Dài bao lâu")
        self.form_len.addRow(self.lbl_target, self.target_wrap)
        self.lbl_fill = QLabel("Cách lấp đầy")
        self.form_len.addRow(self.lbl_fill, self.fill)
        self.form_len.addRow(self.stretch_hint)
        self.form_len.addRow(self.reshuffle)
        self.form_len.addRow(self.exact_end)

        # 2. Thứ tự và ngẫu nhiên
        self.order = combo(ORDER)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_000_000_000)
        dice = QPushButton("Đổi mầm")
        dice.setIcon(icons.icon("refresh", 13))
        dice.setIconSize(QSize(13, 13))
        dice.setToolTip("Tạo kết quả ngẫu nhiên khác (cùng số mầm luôn cho ra cùng kết quả)")
        dice.clicked.connect(lambda: self.seed.setValue(random.randint(0, 999_999)))
        self.seed_wrap = QWidget()
        seed_row = QHBoxLayout(self.seed_wrap)
        seed_row.setContentsMargins(0, 0, 0, 0)
        seed_row.setSpacing(6)
        seed_row.addWidget(self.seed, 1)
        seed_row.addWidget(dice)
        self.lbl_seed = QLabel("Số mầm (Seed)")
        g_order = QGroupBox("Thứ tự phát && Ngẫu nhiên")
        f_ord = QFormLayout(g_order)
        f_ord.setVerticalSpacing(8)
        f_ord.addRow("Thứ tự clip", self.order)
        f_ord.addRow(self.lbl_seed, self.seed_wrap)

        # 3. Intro / Outro
        self.intro = BookendRow("Intro", settings)
        self.outro = BookendRow("Outro", settings)
        self.bookend_audio = QCheckBox("Giữ nguyên tiếng gốc của Intro / Outro")
        g_book = QGroupBox("Intro / Outro cố định (đầu && cuối video)")
        f_book = QFormLayout(g_book)
        f_book.setVerticalSpacing(8)
        f_book.addRow("Intro mở đầu", self.intro)
        f_book.addRow("Outro kết thúc", self.outro)
        f_book.addRow(self.bookend_audio)

        # 4. Hình ảnh & Khung hình
        self.fit = combo(FIT)
        self.fade_out = QDoubleSpinBox()
        self.fade_out.setRange(0, 60)
        self.fade_out.setSingleStep(0.5)
        self.fade_out.setSuffix(" giây")
        self.fade_out.setDecimals(1)
        self.image_dur = QDoubleSpinBox()
        self.image_dur.setRange(0.5, 600)
        self.image_dur.setSingleStep(1)
        self.image_dur.setDecimals(1)
        self.image_dur.setSuffix(" giây")
        self.image_dur.setToolTip("Ảnh tĩnh (jpg, png…) trong bảng: mỗi lần phát dài bao nhiêu giây")
        g_img = QGroupBox("Khung hình && Ảnh tĩnh")
        f_img = QFormLayout(g_img)
        f_img.setVerticalSpacing(8)
        f_img.addRow("Clip khác tỉ lệ", self.fit)
        f_img.addRow("Mỗi ảnh tĩnh hiện", self.image_dur)
        f_img.addRow("Mờ dần cuối video", self.fade_out)

        # 5. Âm thanh gốc & Trộn nhạc
        self.source = combo(SOURCE)
        # âm lượng nhạc / tiếng gốc chỉnh ở Bảng trộn âm (trang 2, dùng chung mọi chế độ); ở đây chỉ giữ giá trị
        self._source_volume = 100
        self._music_volume = 100
        mix_btn = QPushButton("Chỉnh âm lượng ở Bảng trộn âm…")
        mix_btn.setObjectName("pill")
        mix_btn.setIcon(icons.icon("sliders", 13))
        mix_btn.setIconSize(QSize(13, 13))
        mix_btn.setToolTip("Âm lượng nhạc, tiếng gốc clip, từng lớp tiếng nền + nghe thử 20 giây")
        mix_btn.clicked.connect(self.mixerRequested.emit)
        g_audio = QGroupBox("Âm thanh clip && Phối trộn")
        f_aud = QFormLayout(g_audio)
        f_aud.setVerticalSpacing(8)
        f_aud.addRow("Tiếng gốc clip", self.source)
        f_aud.addRow(w.muted("Âm lượng nhạc, tiếng gốc và tiếng nền chỉnh chung ở <b>Bảng trộn âm</b> (trang 2) — "
                             "có nút nghe thử 20 giây."))
        f_aud.addRow(mix_btn)

        # Tổ chức thành 2 sub-tab trên cột phải để không cần cuộn dọc
        tab1 = QWidget()
        t1_lay = QVBoxLayout(tab1)
        t1_lay.setContentsMargins(0, 4, 4, 0)
        t1_lay.setSpacing(8)
        t1_lay.addWidget(g_len)
        t1_lay.addWidget(g_order)
        t1_lay.addWidget(g_book)
        t1_lay.addStretch(1)

        tab2 = QWidget()
        t2_lay = QVBoxLayout(tab2)
        t2_lay.setContentsMargins(0, 4, 4, 0)
        t2_lay.setSpacing(8)
        t2_lay.addWidget(g_img)
        t2_lay.addWidget(g_audio)
        t2_lay.addStretch(1)

        from .look_panel import LookPanel
        self.look = LookPanel(settings, slider_spin_row)
        self.look.changed.connect(self._emit)
        look_scroll = QScrollArea()
        look_scroll.setWidgetResizable(True)
        look_scroll.setFrameShape(QFrame.Shape.NoFrame)
        look_scroll.setWidget(self.look)
        look_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(tab1, "Độ dài")
        self.right_tabs.addTab(tab2, "Khung && Tiếng")
        self.right_tabs.addTab(look_scroll, "Màu && Logo")
        self.right_tabs.setTabToolTip(0, "Video dài bao lâu, thứ tự phát, Intro / Outro")
        self.right_tabs.setTabToolTip(1, "Clip khác tỉ lệ, ảnh tĩnh, mờ dần cuối video, tiếng gốc & âm lượng")
        self.right_tabs.setTabToolTip(2, "Chỉnh màu, đóng logo / khung PNG — có ảnh xem trước")
        self.right_tabs.tabBar().setExpanding(True)
        self.right_tabs.setMinimumWidth(390)
        left.setMinimumWidth(420)

        self.next_btn = QPushButton("Tiếp theo: Chọn nhạc")
        self.next_btn.setObjectName("nextStepBtn")
        self.next_btn.setIcon(icons.icon("arrow_right", 14, "text_on_accent"))
        self.next_btn.setIconSize(QSize(14, 14))
        self.next_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.next_btn.clicked.connect(lambda: self.nextStepRequested.emit())  # clicked(bool) → tín hiệu không đối số

        right_panel = QWidget()
        rp_lay = QVBoxLayout(right_panel)
        rp_lay.setContentsMargins(0, 0, 0, 0)
        rp_lay.setSpacing(8)
        rp_lay.addWidget(self.right_tabs, 1)
        next_row = QHBoxLayout()
        next_row.addStretch(1)
        next_row.addWidget(self.next_btn)
        rp_lay.addLayout(next_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(left)
        split.addWidget(right_panel)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([980, 460])
        self.split = split
        self.timeline = TimelineBar()

        # thông báo khi ở kiểu "Chỉ nhạc": trang này không dùng
        self.mode_banner = QWidget()
        mb = QHBoxLayout(self.mode_banner)
        mb.setContentsMargins(0, 0, 0, 0)
        mb_text = QLabel("Đang ở chế độ <b>Chỉ nhạc</b>: trang Video đã được bỏ qua. "
                         "Vào trang <b>Nhạc</b> để chọn bài, rồi trang <b>Xuất</b> để xuất file nhạc.")
        mb_text.setObjectName("info")
        mb_text.setWordWrap(True)
        mb_btn = QPushButton("Chuyển sang Video có nhạc")
        mb_btn.setIcon(icons.icon("video_music", 14))
        mb_btn.clicked.connect(lambda: self.switchModeRequested.emit("video_music"))
        mb.addWidget(mb_text, 1)
        mb.addWidget(mb_btn)
        self.mode_banner.hide()

        lay = QVBoxLayout(self)
        theme.page_layout(lay)
        lay.addWidget(self.mode_banner)
        lay.addWidget(split, 1)

        for wdg in (self.order, self.length_mode, self.fill, self.fit, self.source):
            wdg.currentIndexChanged.connect(self._emit)
        for wdg in (self.seed,):
            wdg.valueChanged.connect(self._emit)
        self.fade_out.valueChanged.connect(self._emit)
        self.image_dur.valueChanged.connect(self._on_image_dur)
        self.target.valueChanged.connect(self._emit)
        for wdg in (self.reshuffle, self.exact_end, self.bookend_audio):
            wdg.toggled.connect(self._emit)
        self.intro.changed.connect(self._emit)
        self.outro.changed.connect(self._emit)

    def _toggle_preview(self, checked: bool) -> None:
        self.preview.setVisible(checked)
        self.preview_toggle.setText(
            ("Ẩn chi tiết kịch bản phát" if checked else "Xem chi tiết từng lượt phát")
        )

    def _quick_plays(self, val: str) -> None:
        self.bulk.setText(val)
        if self.list.selectedItems():
            self._apply_bulk()

    # ---------- dữ liệu ----------
    def load(self, vs: VideoSettings) -> None:
        self._loading = True
        # lựa chọn nhớ tạm của dự án trước (khi đổi sang Chỉ video) không được lẫn sang dự án mới mở
        self._saved_length = None
        self._saved_source = None
        self._load_gen = getattr(self, "_load_gen", 0) + 1  # file đang đọc dở của dự án cũ: bỏ
        self.list.blockSignals(True)
        self.list.clear()
        self._thumb_waiting.clear()
        infos = w.probe.probe_many([c.path for c in vs.clips])
        for c, info in zip(vs.clips, infos):
            self.list.addTopLevelItem(self._make_item(c, info))
        self._refresh_rows()
        self.list.blockSignals(False)
        set_combo(self.order, vs.order)
        self.seed.setValue(vs.seed)
        set_combo(self.length_mode, vs.length_mode)
        self.target.set_seconds(vs.target_duration, emit=False)
        set_combo(self.fill, vs.fill)
        self.reshuffle.setChecked(vs.reshuffle_each_round)
        self.exact_end.setChecked(vs.exact_end)
        self.fade_out.setValue(vs.fade_out)
        self.image_dur.setValue(vs.image_duration)
        set_combo(self.fit, vs.fit)
        set_combo(self.source, vs.source_audio)
        self._source_volume, self._music_volume = vs.source_volume, vs.music_volume
        self.intro.set_path(vs.intro)
        self.intro.xf.setValue(vs.intro_xfade)
        self.outro.set_path(vs.outro)
        self.outro.xf.setValue(vs.outro_xfade)
        self.bookend_audio.setChecked(vs.bookend_audio)
        self.look.load(vs)
        self.list.blockSignals(True)
        self._refresh_rows()
        self.list.blockSignals(False)
        self._loading = False
        self._update_enabled()
        self._reset_history()
        self.suggest.setVisible(False)

    def collect(self) -> VideoSettings:
        vs = VideoSettings()
        vs.clips = [self._clip_from_item(it) for it in self.list.items()]
        vs.order = self.order.currentData()
        vs.seed = self.seed.value()
        vs.length_mode = self.length_mode.currentData()
        vs.target_duration = self.target.seconds()
        vs.fill = self.fill.currentData()
        vs.reshuffle_each_round = self.reshuffle.isChecked()
        vs.exact_end = self.exact_end.isChecked()
        vs.fade_out = self.fade_out.value()
        vs.fit = self.fit.currentData()
        vs.image_duration = self.image_dur.value()
        vs.source_audio = self.source.currentData()
        # kiểu Chỉ video tạm đổi ô hiển thị; khi lưu vẫn giữ lựa chọn của người dùng (Chỉ video không dùng nhạc nên
        # "trộn nhạc" = giữ tiếng gốc, "theo nhạc" = theo số lần phát) — quay lại kiểu có nhạc không bị mất
        if getattr(self, "_saved_source", None) and vs.source_audio == "only":
            vs.source_audio = self._saved_source
        if getattr(self, "_saved_length", None) and vs.length_mode == "manual":
            vs.length_mode = self._saved_length
        vs.source_volume, vs.music_volume = self._source_volume, self._music_volume
        vs.intro, vs.intro_xfade = self.intro.value(), self.intro.xf.value()
        vs.outro, vs.outro_xfade = self.outro.value(), self.outro.xf.value()
        vs.bookend_audio = self.bookend_audio.isChecked()
        self.look.fill(vs)
        return vs

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        music_only = mode == "music_only"
        video_only = mode == "video_only"
        self.mode_banner.setVisible(music_only)
        self.timeline.setEnabled(not music_only)
        self.split.setEnabled(not music_only)
        # "Theo độ dài nhạc" vô nghĩa khi không có nhạc
        item = self.length_mode.model().item(self.length_mode.findData("music"))
        if item is not None:
            item.setEnabled(not video_only)
        # nhớ lựa chọn cũ để khi quay lại kiểu có nhạc thì trả lại đúng như trước
        if video_only and self.length_mode.currentData() == "music":
            self._saved_length = "music"
            set_combo(self.length_mode, "manual")
        elif not video_only and getattr(self, "_saved_length", None):
            if self.length_mode.currentData() == "manual":
                set_combo(self.length_mode, self._saved_length)
            self._saved_length = None
        # "Trộn tiếng gốc với nhạc nền" vô nghĩa khi ở chế độ Chỉ video
        mix_item = self.source.model().item(self.source.findData("mix"))
        if mix_item is not None:
            mix_item.setEnabled(not video_only)
        if video_only and self.source.currentData() == "mix":
            self._saved_source = "mix"
            set_combo(self.source, "only")
        elif not video_only and getattr(self, "_saved_source", None):
            if self.source.currentData() == "only":
                set_combo(self.source, self._saved_source)
            self._saved_source = None
        self._update_enabled()

    def set_preview(self, text: str) -> None:
        self.preview.setPlainText(text)

    # ---------- dòng ----------
    def _make_item(self, c: ClipItem, info: MediaInfo) -> QTreeWidgetItem:
        single_play = c.plays_mode == "fixed" and c.count <= 1
        plays = (w.fmt_play_seconds(c.play_seconds) if c.plays_mode == "duration"
                 else w.plays_text(c.plays_mode, c.count, c.min, c.max))
        it = self.list.new_item([Path(c.path).name, "", "", plays,
                                 "", "—" if single_play else w.xf_text(c.loop_xfade),
                                 w.xf_text(c.next_xfade), ""], c.enabled)
        it.setCheckState(COL_STRETCH, Qt.CheckState.Checked if c.stretch else Qt.CheckState.Unchecked)
        it.setData(0, w.ROLE_DATA, c)
        it.setData(0, w.ROLE_INFO, info)
        it.setToolTip(COL_NAME, c.path)
        waiting = self._thumb_waiting.setdefault(c.path, [])
        waiting[:] = [i for i in waiting if shiboken6.isValid(i)]  # dòng đã xoá khỏi bảng: bỏ
        waiting.append(it)
        self.thumbs.request([c.path])
        for col in (COL_TRIM, COL_PLAYS, COL_LOOPXF, COL_NEXTXF):
            it.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
        it.setTextAlignment(COL_DUR, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return it

    def _clip_from_item(self, it: QTreeWidgetItem) -> ClipItem:
        old: ClipItem = it.data(0, w.ROLE_DATA)
        mode, lo, hi = w.parse_plays(it.text(COL_PLAYS)) or ("fixed", 1, 1)
        loop_txt = (it.text(COL_LOOPXF) or "").strip()
        loop_xf = old.loop_xfade if loop_txt in ("—", "-") else w.parse_xf(loop_txt)
        play_seconds = 0.0
        if mode == "duration":  # loop cho đủ thời lượng → ước tính số lần để hiển thị; số chính xác tính khi xuất
            play_seconds = float(lo)
            est = self._estimate_loops(it, play_seconds, old, loop_xf)
            lo = hi = est
        return ClipItem(path=old.path, enabled=it.checkState(0) == Qt.CheckState.Checked,
                        plays_mode=mode, count=lo if mode in ("fixed", "duration") else old.count, min=lo, max=hi,
                        play_seconds=play_seconds,
                        stretch=it.checkState(COL_STRETCH) == Qt.CheckState.Checked,
                        loop_xfade=loop_xf,
                        next_xfade=w.parse_xf(it.text(COL_NEXTXF)),
                        trim_start=old.trim_start, trim_end=old.trim_end)

    def _estimate_loops(self, it: QTreeWidgetItem, seconds: float, c: ClipItem, loop_xf: float) -> int:
        info: MediaInfo = it.data(0, w.ROLE_INFO)
        if info is None or not info.ok:
            return 1
        d = self.image_dur.value() if info.is_image else max(MIN_KEEP, info.duration - c.trim_start - c.trim_end)
        if seconds <= 0:
            return 0
        if seconds <= d:
            return 1
        x = min(loop_xf, d * 0.45)
        return 1 + int(-(-(seconds - d) // max(0.05, d - x)))

    def _refresh_rows(self) -> None:
        items = self.list.items()
        ref = next((it.data(0, w.ROLE_INFO) for it in items
                    if it.data(0, w.ROLE_INFO).ok and not it.data(0, w.ROLE_INFO).is_image), None)
        active = 0
        for it in items:
            self._refresh_row(it, ref)
            c: ClipItem = it.data(0, w.ROLE_DATA)
            if c.enabled and (c.count > 0 if c.plays_mode == "fixed" else c.max > 0):
                active += 1
        total = len(items)
        self.count_label.setText(f"{active}/{total} clip bật" if total else "0 clip")

    def _refresh_row(self, it: QTreeWidgetItem, ref: MediaInfo | None) -> None:
        self._refresh_row_inner(it, ref)
        it.setData(COL_NAME, w.ROLE_SUB, it.text(COL_INFO))
        it.setData(COL_NAME, w.ROLE_SUB_COLOR, it.foreground(COL_INFO).color())
        tip = it.data(0, w.ROLE_DATA).path
        if it.toolTip(COL_INFO):
            tip += "\n" + it.toolTip(COL_INFO)
        it.setToolTip(COL_NAME, tip)

    def _refresh_row_inner(self, it: QTreeWidgetItem, ref: MediaInfo | None) -> None:
        info: MediaInfo = it.data(0, w.ROLE_INFO)
        c = self._clip_from_item(it)
        it.setData(0, w.ROLE_DATA, c)
        skipped = not c.enabled or (c.plays_mode == "fixed" and c.count == 0)
        it.setForeground(COL_NAME, theme.qcolor("text_disabled") if skipped else theme.qcolor("text"))
        it.setForeground(COL_PLAYS, theme.qcolor("text_disabled") if skipped else QColor(theme.T['accent_soft']))

        if not info.ok:
            it.setText(COL_INFO, f"LỖI: {info.error}")
            it.setForeground(COL_INFO, theme.qcolor("danger_text"))
            return
        if info.is_image:
            it.setText(COL_TRIM, "—")
            it.setForeground(COL_TRIM, theme.qcolor("text_disabled"))
            it.setToolTip(COL_TRIM, "Ảnh tĩnh: không cần cắt đoạn")
            d = self.image_dur.value()
            it.setText(COL_INFO, f"Ảnh {info.width}×{info.height} · {d:g}s/lần")
            it.setForeground(COL_INFO, theme.qcolor("text_disabled") if skipped else theme.qcolor("info_text"))
            it.setToolTip(COL_INFO, "Ảnh tĩnh — thời lượng mỗi lần phát chỉnh ở thẻ Khung & Tiếng")
        else:
            d = info.duration
            text = f"{info.width}×{info.height} · {info.fps_text()} fps · {info.duration:.1f}s"
            if info.has_audio:
                text += " · Có tiếng"
            it.setText(COL_INFO, text)
            differs = ref is not None and (info.width, info.height, info.fps_text()) != (
                ref.width, ref.height, ref.fps_text())
            it.setForeground(COL_INFO, theme.qcolor("text_disabled") if skipped else (
                theme.qcolor("warn_text") if differs else theme.qcolor("text_muted")))
            it.setToolTip(COL_INFO, "Khác thông số clip đầu tiên — sẽ được chuẩn hoá tự động khi xuất" if differs else "")
            # đoạn lấy: thời lượng hiệu dụng sau khi bỏ đầu/cuối
            trimmed = c.trim_start > 0 or c.trim_end > 0
            d = max(min(MIN_KEEP, info.duration), info.duration - c.trim_start - c.trim_end)
            it.setText(COL_TRIM, trim_text(info.duration, c.trim_start, c.trim_end))
            it.setForeground(COL_TRIM, theme.qcolor("text_disabled") if skipped else (
                theme.qcolor("warn_text") if trimmed else theme.qcolor("text_muted")))
            it.setToolTip(COL_TRIM, (f"Bỏ {c.trim_start:g}s đầu, {c.trim_end:g}s cuối → mỗi lần phát dài {d:.1f}s. "
                                     if trimmed else "Lấy toàn bộ clip. ") + "Bấm đúp để chọn đoạn lấy.")

        # Cảnh báo crossfade vượt d <= L/2 hoặc khoá ô nối vòng lặp khi chỉ phát <= 1 lần
        single_play = c.plays_mode == "fixed" and c.count <= 1
        if single_play:
            it.setText(COL_LOOPXF, "—")
            it.setForeground(COL_LOOPXF, theme.qcolor("text_disabled"))
            it.setToolTip(COL_LOOPXF, "Clip phát 1 lần (không lặp) nên không có Nối loop")
        else:
            it.setText(COL_LOOPXF, w.xf_text(c.loop_xfade))
            if c.loop_xfade > d * 0.5:
                it.setForeground(COL_LOOPXF, theme.qcolor("danger_text"))
                it.setToolTip(COL_LOOPXF, f"Vượt quá 1/2 độ dài clip ({d * 0.5:.1f}s) — sẽ tự giới hạn khi xuất")
            else:
                it.setForeground(COL_LOOPXF, theme.qcolor("text_disabled") if skipped else theme.qcolor("text"))
                it.setToolTip(COL_LOOPXF, "")

        if c.next_xfade > d * 0.5:
            it.setForeground(COL_NEXTXF, theme.qcolor("danger_text"))
            it.setToolTip(COL_NEXTXF, f"Vượt quá 1/2 độ dài clip ({d * 0.5:.1f}s) — sẽ tự giới hạn khi xuất")
        else:
            it.setForeground(COL_NEXTXF, theme.qcolor("text_disabled") if skipped else theme.qcolor("text"))
            it.setToolTip(COL_NEXTXF, "")

        x = min(c.loop_xfade, d * 0.45)
        if c.plays_mode == "duration":
            n = c.count
            it.setText(COL_DUR, f"{w.fmt_dur(n * d - max(0, n - 1) * x)} · {n} lần" if n else "bỏ qua")
            it.setToolTip(COL_PLAYS, f"Loop cho đủ {w.fmt_play_seconds(c.play_seconds)} → khoảng {n} lần phát "
                                     f"(mỗi lần {d:.1f}s)")
        elif c.plays_mode == "fixed":
            it.setText(COL_DUR, w.fmt_dur(c.count * d - max(0, c.count - 1) * x) if c.count else "bỏ qua")
        else:
            lo = c.min * d - max(0, c.min - 1) * x
            hi = c.max * d - max(0, c.max - 1) * x
            it.setText(COL_DUR, f"{w.fmt_dur(lo)}–{w.fmt_dur(hi)}")
        it.setForeground(COL_DUR, theme.qcolor("text_disabled") if skipped else theme.qcolor("text"))

    def _on_thumb(self, path: str, img) -> None:
        items = self._thumb_waiting.pop(path, None)
        if not items or img.isNull():
            return
        icon = QIcon(QPixmap.fromImage(img))  # giải mã đã làm ở luồng nền; ở đây chỉ đổi sang QPixmap
        self.list.blockSignals(True)
        for it in items:
            if shiboken6.isValid(it):  # dòng đã bị xoá khỏi bảng thì bỏ qua
                it.setIcon(COL_NAME, icon)
        self.list.blockSignals(False)

    def adapt(self, width: int) -> None:
        """Gọi từ cửa sổ chính khi đổi kích thước: hẹp thì xếp phần cài đặt xuống dưới."""
        w.adapt_split(self.split, width, 1040, side_min=390, page=self, stacked_height=1350)

    # ---------- cắt đoạn lấy ----------
    def _on_double_click(self, it: QTreeWidgetItem, column: int) -> None:
        if column == COL_TRIM:
            self._open_trim(it)

    def _open_trim_selected(self) -> None:
        sel = self.list.selectedItems()
        if not sel:
            QMessageBox.information(self, "Chưa chọn clip", "Bôi đen một (hoặc nhiều) clip để chọn đoạn lấy.")
            return
        self._open_trim(sel[0])

    def _open_trim(self, it: QTreeWidgetItem) -> None:
        info: MediaInfo = it.data(0, w.ROLE_INFO)
        c: ClipItem = it.data(0, w.ROLE_DATA)
        if not info.ok or info.is_image:
            QMessageBox.information(self, "Không cắt được", "Ảnh tĩnh hoặc file lỗi thì không cần cắt đoạn.")
            return
        sel = [s for s in self.list.selectedItems() if not s.data(0, w.ROLE_INFO).is_image]
        if it not in sel:
            sel = [it]
        dlg = TrimDialog(c.path, info.duration, c.trim_start, c.trim_end, len(sel), self)
        if dlg.exec() != TrimDialog.DialogCode.Accepted or not dlg.result_values:
            return
        a, b, all_sel = dlg.result_values
        self._set_trim(sel if all_sel else [it], a, b)

    def _apply_cut(self, reset: bool = False) -> None:
        sel = self._selected_or_warn()
        if sel:
            a, b = (0.0, 0.0) if reset else (self.bulk_cut_start.value(), self.bulk_cut_end.value())
            self._set_trim(sel, a, b)

    def _set_trim(self, items: list[QTreeWidgetItem], a: float, b: float) -> None:
        self.list.blockSignals(True)
        for it in items:
            info: MediaInfo = it.data(0, w.ROLE_INFO)
            if not info.ok or info.is_image:
                continue
            c: ClipItem = it.data(0, w.ROLE_DATA)
            c.trim_start, c.trim_end = a, b
            it.setData(0, w.ROLE_DATA, c)
        self._refresh_rows()
        self.list.blockSignals(False)
        self._emit()

    # ---------- nhân bản dòng ----------
    def _copy_rows(self) -> None:
        sel = sorted(self.list.selectedItems(), key=self.list.indexOfTopLevelItem)
        if not sel:
            return
        self._clipboard = [(self._clip_from_item(it), it.data(0, w.ROLE_INFO), it.text(COL_PLAYS), it.text(COL_LOOPXF),
                            it.text(COL_NEXTXF)) for it in sel]
        self.status.setText(f"Đã chép {len(sel)} dòng — chọn chỗ muốn dán rồi bấm Ctrl+V (dán ngay bên dưới).")

    def _paste_rows(self) -> None:
        if not self._clipboard:
            self.status.setText("Chưa chép dòng nào — bôi đen các dòng rồi bấm Ctrl+C trước.")
            return
        sel = self.list.selectedItems()
        pos = max(self.list.indexOfTopLevelItem(it) for it in sel) + 1 if sel else self.list.topLevelItemCount()
        self.list.blockSignals(True)
        new_items = []
        for k, (c, info, plays, loop_xf, next_xf) in enumerate(self._clipboard):
            it = self._make_item(ClipItem(**c.__dict__), info)
            self.list.insertTopLevelItem(pos + k, it)
            it.setText(COL_PLAYS, plays)
            it.setText(COL_LOOPXF, loop_xf)
            it.setText(COL_NEXTXF, next_xf)
            new_items.append(it)
        self._refresh_rows()
        self.list.blockSignals(False)
        self.list.clearSelection()
        for it in new_items:
            it.setSelected(True)
        self.list.scrollToItem(new_items[-1])
        self.status.setText(f"Đã dán {len(new_items)} dòng — Ctrl+Z để hoàn tác.")
        self._emit()

    def _duplicate_selected(self) -> None:
        sel = self._selected_or_warn()
        for it in sorted(sel, key=self.list.indexOfTopLevelItem, reverse=True):
            self._duplicate(it)

    def _duplicate(self, it: QTreeWidgetItem) -> None:
        """Bản sao ngay dưới dòng gốc (cùng file, cùng cài đặt) — kéo đi chỗ khác nếu cần."""
        c = self._clip_from_item(it)
        info: MediaInfo = it.data(0, w.ROLE_INFO)
        new = self._make_item(ClipItem(**c.__dict__), info)
        self.list.blockSignals(True)
        self.list.insertTopLevelItem(self.list.indexOfTopLevelItem(it) + 1, new)
        new.setText(COL_PLAYS, it.text(COL_PLAYS))
        new.setText(COL_LOOPXF, it.text(COL_LOOPXF))
        new.setText(COL_NEXTXF, it.text(COL_NEXTXF))
        self._refresh_rows()
        self.list.blockSignals(False)
        self.list.clearSelection()
        new.setSelected(True)
        self.status.setText(f"Đã nhân bản {Path(c.path).name} — kéo dòng mới tới vị trí muốn phát lại.")
        self._emit()

    def _on_image_dur(self, *_) -> None:
        self.list.blockSignals(True)
        self._refresh_rows()
        self.list.blockSignals(False)
        self._emit()

    def _on_item_changed(self, it: QTreeWidgetItem, column: int) -> None:
        if self._loading:
            return
        self.list.blockSignals(True)
        if column == COL_PLAYS:
            parsed = w.parse_plays(it.text(COL_PLAYS))
            if not parsed:
                it.setText(COL_PLAYS, "1")
            elif parsed[0] == "duration":  # "10p", "600s"… → hiển thị thống nhất "10:00"
                it.setText(COL_PLAYS, w.plays_text(*parsed[:1], parsed[1], parsed[1], parsed[2]))
        self._refresh_rows()
        self.list.blockSignals(False)
        self._update_enabled()  # vd. vừa nhập "50-80" → hiện ngay ô Số mầm

    def _selected_or_warn(self) -> list[QTreeWidgetItem]:
        sel = self.list.selectedItems()
        if not sel:
            QMessageBox.information(self, "Chưa chọn dòng",
                                    "Hãy bôi đen các dòng muốn đặt (Ctrl/Shift + bấm chuột, hoặc Ctrl+A để chọn hết), "
                                    "rồi bấm Áp dụng.")
        return sel

    def _apply_bulk(self) -> None:
        parsed = w.parse_plays(self.bulk.text())
        sel = self._selected_or_warn()
        if not parsed or not sel:
            return
        mode, lo, hi = parsed
        self.list.blockSignals(True)
        for it in sel:
            it.setText(COL_PLAYS, w.plays_text(mode, lo, lo, hi))
        self._refresh_rows()
        self.list.blockSignals(False)
        self._emit()

    def _apply_xfade(self, clear: bool = False) -> None:
        sel = self._selected_or_warn()
        if not sel:
            return
        loop_v, next_v = (0.0, 0.0) if clear else (self.bulk_loop.value(), self.bulk_next.value())
        self.list.blockSignals(True)
        for it in sel:
            c: ClipItem = it.data(0, w.ROLE_DATA)
            c.loop_xfade = loop_v
            it.setData(0, w.ROLE_DATA, c)
            if not (c.plays_mode == "fixed" and c.count <= 1):
                it.setText(COL_LOOPXF, w.xf_text(loop_v))
            it.setText(COL_NEXTXF, w.xf_text(next_v))
        self._refresh_rows()
        self.list.blockSignals(False)
        self._emit()

    def _set_stretch(self, on: bool) -> None:
        sel = self._selected_or_warn()
        if not sel:
            return
        self.list.blockSignals(True)
        for it in sel:
            it.setCheckState(COL_STRETCH, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self._emit()

    def _preview_seam(self) -> None:
        sel = self.list.selectedItems()
        if not sel:
            QMessageBox.information(self, "Chưa chọn clip", "Bôi đen một clip để xem thử chỗ nối của nó.")
            return
        self.previewSeamRequested.emit(self.list.indexOfTopLevelItem(sel[0]))

    # ---------- thêm file ----------
    def _add_files(self) -> None:
        files = w.pick_files(self, "Chọn video hoặc ảnh", w.VISUAL_EXTS, self.settings.value("dir/clips", ""))
        if files:
            self.settings.setValue("dir/clips", os.path.dirname(files[0]))
            self.add_paths(files)

    def _add_folder(self) -> None:
        folder = w.pick_folder(self, "Chọn thư mục video", self.settings.value("dir/clips", ""))
        if folder:
            self.settings.setValue("dir/clips", folder)
            self.add_paths(w.scan_folder(folder, w.VISUAL_EXTS, self.toolbar.recursive.isChecked()))

    def add_paths(self, paths: list[str]) -> None:
        files = w.expand_dropped(paths, w.VISUAL_EXTS, self.toolbar.recursive.isChecked())
        have = self.list.paths()
        files = [os.path.normpath(p) for p in files if os.path.normcase(os.path.normpath(p)) not in have]
        if not files:
            self.status.setText("File đã có trong bảng. Muốn phát lại clip ở chỗ khác: chuột phải → Nhân bản dòng.")
            return
        self.status.setText(f"Đang đọc 0/{len(files)} file…")
        self._prober = w.Prober()
        self._prober.progress.connect(lambda i, n: self.status.setText(f"Đang đọc {i}/{n} file…"))
        gen = getattr(self, "_load_gen", 0)
        self._prober.finished.connect(lambda infos, g=gen: self._on_probed(infos, g))
        self._prober.start(files)

    def _on_probed(self, infos: list[MediaInfo], gen: int | None = None) -> None:
        if gen is not None and gen != getattr(self, "_load_gen", 0):
            return  # đã mở / tạo dự án khác trong lúc đang đọc file
        bad = [i for i in infos if not (i.ok and i.has_video)]
        self.list.blockSignals(True)
        for info in infos:
            if info.ok and info.has_video:
                self.list.addTopLevelItem(self._make_item(ClipItem(path=info.path), info))
        self._refresh_rows()
        self.list.blockSignals(False)
        msg = f"Đã thêm {len(infos) - len(bad)} clip/ảnh."
        if bad:
            msg += f" Bỏ qua {len(bad)} file lỗi."
            QMessageBox.warning(self, "Có file không đọc được",
                                "\n".join(f"• {b.path}: {b.error or 'không có hình'}" for b in bad[:15]))
        self.status.setText(msg)
        self._emit()
        self._maybe_suggest_interleave()

    # ---------- xen kẽ clip nền ----------
    def _maybe_suggest_interleave(self) -> None:
        clips = [it.data(0, w.ROLE_DATA) for it in self.list.items()]
        unique = {os.path.normcase(c.path): c.path for c in clips}
        from ..core import interleave as il
        if len(clips) == len(unique) and il.looks_like_sequence(list(unique.values())):
            # nhiều clip loop (Loop1, Loop2…): gợi ý phát lần lượt từng loop thay cho "nền xen cảnh"
            contents, loops = il.split_loops(clips)
            names = " → ".join(Path(c.path).stem for c in loops[:3]) + (" → …" if len(loops) > 3 else "")
            head = (", ".join(Path(c.path).stem for c in contents[:2]) + " → ") if contents else ""
            self._suggest_kind = "sequence"
            self.suggest_go.setText("Xếp lần lượt…")
            self.suggest_text.setText(f"Có <b>{len(loops)} clip loop</b>"
                                      + (f" và {len(contents)} clip nội dung" if contents else "")
                                      + f". Xếp <b>{head}{names}</b>, mỗi loop lặp nhiều lần?")
            motion.slide_visible(self.suggest, True)
            return
        self._suggest_kind = "interleave"
        self.suggest_go.setText("Xen kẽ ngay…")
        if len(unique) < 3 or len(clips) > len(unique) or not has_base_candidate(list(unique.values())):
            self.suggest.setVisible(False)  # đã xen kẽ (có dòng trùng) hoặc không có clip nền theo tên
            return
        base = il.detect_base(clips)
        self.suggest_text.setText(f"Có clip nền <b>{Path(clips[base].path).name}</b> và {len(unique) - 1} cảnh khác. "
                                  "Tự xếp thành <b>nền → cảnh → nền → cảnh … → nền</b>?")
        motion.slide_visible(self.suggest, True)

    def _open_interleave(self) -> None:
        items = self.list.items()
        if len({os.path.normcase(it.data(0, w.ROLE_DATA).path) for it in items}) < 2:
            QMessageBox.information(self, "Xen kẽ clip nền",
                                    "Cần ít nhất 2 file khác nhau trong bảng: 1 clip nền (ví dụ loop_….mp4) và "
                                    "các cảnh chèn (2_….mp4, 3_….mp4…).")
            return
        clips = [self._clip_from_item(it) for it in items]
        infos: dict[str, MediaInfo] = {}
        durations: dict[str, float] = {}
        for it, c in zip(items, clips):
            key = os.path.normcase(c.path)
            info: MediaInfo = it.data(0, w.ROLE_INFO)
            infos.setdefault(key, info)
            if key not in durations and info is not None and info.ok:
                durations[key] = (self.image_dur.value() if info.is_image
                                  else max(MIN_KEEP, info.duration - c.trim_start - c.trim_end))
        dlg = InterleaveDialog(clips, durations, self.settings, self)
        if not dlg.exec() or not dlg.result_clips:
            return
        self._apply_arranged(dlg.result_clips, infos, "Đã xen kẽ")

    def _table_media(self):
        """(clip của bảng, MediaInfo theo file, thời lượng một lần phát theo file) cho các hộp thoại xếp kịch bản."""
        items = self.list.items()
        clips = [self._clip_from_item(it) for it in items]
        infos: dict[str, MediaInfo] = {}
        durations: dict[str, float] = {}
        for it, c in zip(items, clips):
            key = os.path.normcase(c.path)
            info: MediaInfo = it.data(0, w.ROLE_INFO)
            infos.setdefault(key, info)
            if key not in durations and info is not None and info.ok:
                durations[key] = (self.image_dur.value() if info.is_image
                                  else max(MIN_KEEP, info.duration - c.trim_start - c.trim_end))
        return clips, infos, durations

    def _open_sequence(self) -> None:
        from .sequence_dialog import SequenceDialog
        clips, infos, durations = self._table_media()
        if not clips:
            QMessageBox.information(self, "Xếp lần lượt", "Thêm clip vào bảng trước (ví dụ Content.mp4, Loop1.mp4, "
                                    "Loop2.mp4…).")
            return
        dlg = SequenceDialog(clips, durations, self.settings, self)
        if not dlg.exec() or not dlg.result_clips:
            return
        self._apply_arranged(dlg.result_clips, infos, "Đã xếp lần lượt")

    def _apply_arranged(self, result: list[ClipItem], infos: dict, what: str) -> None:
        """Thay bảng clip bằng bảng đã xếp (Hoàn tác được)."""
        dlg_result = result
        self._hist_timer.stop()
        self._push_history()  # để Hoàn tác quay lại đúng bảng trước khi xen kẽ
        self.list.blockSignals(True)
        self.list.clear()
        self._thumb_waiting.clear()
        for c in dlg_result:
            self.list.addTopLevelItem(self._make_item(ClipItem(**c.__dict__), infos[os.path.normcase(c.path)]))
        self._refresh_rows()
        self.list.blockSignals(False)
        motion.slide_visible(self.suggest, False)
        self.status.setText(f"{what}: {len(dlg_result)} dòng. Bấm Hoàn tác (Ctrl+Z) để quay lại.")
        self.notify.emit(f"{what} {len(dlg_result)} dòng — Ctrl+Z để quay lại", "ok")
        self._emit()

    # ---------- cập nhật hiển thị thông minh (Progressive Disclosure) ----------
    def _update_enabled(self) -> None:
        mode = self.length_mode.currentData()
        is_target = mode == "target"
        not_manual = mode != "manual"
        stretch_on = not_manual and self.fill.currentData() == "stretch_marked"

        # Ẩn/hiện cột Tự giãn và các nút liên quan
        self.list.setColumnHidden(COL_STRETCH, not stretch_on)
        for b in self.stretch_buttons:
            b.setVisible(stretch_on)
        self.stretch_hint.setVisible(stretch_on)

        # Ẩn/hiện các dòng trong thẻ Độ dài theo ngữ cảnh
        self.lbl_target.setVisible(is_target)
        self.target_wrap.setVisible(is_target)
        self.target.setEnabled(is_target)

        self.lbl_fill.setVisible(not_manual)
        self.fill.setVisible(not_manual)
        self.fill.setEnabled(not_manual)

        self.reshuffle.setVisible(not_manual and self.fill.currentData() == "repeat_sequence")
        self.exact_end.setVisible(not_manual)
        self.exact_end.setEnabled(not_manual)

        # Chỉ hiện Số mầm khi chọn thứ tự ngẫu nhiên hoặc có clip đặt số lần phát ngẫu nhiên
        has_rand_plays = any(it.data(0, w.ROLE_DATA) and it.data(0, w.ROLE_DATA).plays_mode == "random"
                             for it in self.list.items())
        need_seed = self.order.currentData() == "shuffle" or has_rand_plays
        self.lbl_seed.setVisible(need_seed)
        self.seed_wrap.setVisible(need_seed)

        has_bookend = bool(self.intro.value() or self.outro.value())
        self.bookend_audio.setEnabled(has_bookend)

        src = self.source.currentData()

        if self._mode == "video_only" or src == "only":
            self.next_btn.setText("Tiếp theo: Xuất video")
        else:
            self.next_btn.setText("Tiếp theo: Chọn nhạc")

        # Chấm báo hiệu trên tiêu đề tab phụ khi có tuỳ chỉnh khác mặc định
        has_custom_tab2 = (self.fit.currentData() != "letterbox" or self.source.currentData() != "mix"
                           or self.fade_out.value() != 3.0)
        self.right_tabs.setTabText(1, "Khung && Tiếng ●" if has_custom_tab2 else "Khung && Tiếng")

    def _emit(self, *_) -> None:
        if self._loading:
            return
        self._update_enabled()
        if not self._restoring:
            self._hist_timer.start()
        self.changed.emit()

    # ---------- hoàn tác ----------
    def _snapshot(self) -> list[ClipItem]:
        return [ClipItem(**self._clip_from_item(it).__dict__) for it in self.list.items()]

    def _push_history(self) -> None:
        snap = self._snapshot()
        if self._history and self._history[-1] == snap:
            return
        self._history.append(snap)
        del self._history[:-60]  # giữ tối đa 60 bước
        self.undo_btn.setEnabled(len(self._history) > 1)

    def _reset_history(self) -> None:
        self._hist_timer.stop()
        self._history = [self._snapshot()]
        self.undo_btn.setEnabled(False)

    def undo(self) -> None:
        self._hist_timer.stop()
        self._push_history()  # ghi lại thay đổi vừa làm (nếu chưa kịp ghi)
        if len(self._history) < 2:
            return
        self._history.pop()
        clips = self._history[-1]
        self._restoring = True
        self.list.blockSignals(True)
        self.list.clear()
        self._thumb_waiting.clear()
        for c, info in zip(clips, w.probe.probe_many([c.path for c in clips])):
            self.list.addTopLevelItem(self._make_item(ClipItem(**c.__dict__), info))
        self._refresh_rows()
        self.list.blockSignals(False)
        self.status.setText("Đã hoàn tác 1 bước.")
        self.notify.emit("Đã hoàn tác 1 bước", "info")
        self._emit()
        self._restoring = False
        self.undo_btn.setEnabled(len(self._history) > 1)

