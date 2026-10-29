"""Tab Nhạc: playlist, thứ tự phát, crossfade, âm lượng, lớp tiếng nền, xuất riêng nhạc."""
from __future__ import annotations

import os
import random
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core import ambient_lib, audio_build
from ..core.planner import MusicItem
from ..core.probe import MediaInfo
from ..core.project import AmbientLayer, MusicSettings, MusicTrack, format_hms, parse_hms
from . import effects, icons, motion, theme
from . import widgets as w
from .mixer_panel import MixerPanel
from .video_tab import combo, hms_edit, quick_buttons, set_combo

COL_NAME, COL_DUR, COL_PLAYS, COL_VOL, COL_LUFS = range(5)
ORDER = [("list", "Theo thứ tự trong bảng"), ("shuffle", "Ngẫu nhiên"),
         ("shuffle_no_repeat", "Ngẫu nhiên — không lặp bài liền nhau")]
EXPORT_MODE = [("target", "Theo thời lượng"), ("rounds", "Theo số lượt playlist")]
PIN_POS = [("first", "Mở đầu file (mọi bản)"), ("random", "Vị trí ngẫu nhiên — chắc chắn có trong file")]
AMBIENT_EXTS = w.AUDIO_EXTS | w.VIDEO_EXTS


class MusicTab(QWidget):
    versionPreviewChanged = Signal(int)
    changed = Signal()
    switchModeRequested = Signal(str)
    nextStepRequested = Signal()

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._loading = False
        self._prober = None
        self._amb_prober = None

        self.banner = QLabel("")
        self.banner.setObjectName("info")
        self.banner.setWordWrap(True)

        self.list = w.MediaList(["Tên bài nhạc", "Thời lượng", "Số lần/lượt", "Âm lượng %", "Độ to gốc"])
        theme.on_change(self.list, lambda _wd: (self._refresh_track_styles(), self._update_pin_info()))
        self.list.placeholder = (
            "Chưa có bài nhạc nào trong playlist\n"
            "Kéo thả file hoặc thư mục nhạc vào đây, hoặc bấm nút bên dưới"
        )
        self.list.placeholder_action = "Thêm nhạc"
        self.list.setItemDelegateForColumn(COL_PLAYS, w.SpinDelegate(0, 99, self.list))
        self.list.setItemDelegateForColumn(COL_VOL, w.SpinDelegate(0, 200, self.list))
        hdr = self.list.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)

        def size_cols(*_) -> None:  # column widths follow the font size so header text is never clipped
            for col, width in ((COL_DUR, 92), (COL_PLAYS, 102), (COL_VOL, 96), (COL_LUFS, 110)):
                self.list.setColumnWidth(col, theme.px(width))
            self.schedule.setColumnWidth(0, theme.px(105))
        self._size_cols = size_cols
        self.list.viewport().installEventFilter(self)
        for _c in (COL_DUR, COL_PLAYS, COL_VOL, COL_LUFS):
            self.list.headerItem().setTextAlignment(_c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.list.headerItem().setToolTip(COL_PLAYS, "Số lần bài này được phát trong mỗi lượt playlist (0 = bỏ qua)")
        self.list.headerItem().setToolTip(COL_VOL, "Âm lượng riêng của bài (bấm đúp để sửa). 100% = giữ nguyên; "
                                                   "50% ≈ nhỏ đi 6 dB. Áp sau khi chuẩn hoá LUFS.")
        self.list.headerItem().setToolTip(COL_LUFS, "Độ to đo được của file gốc (đo khi xuất / nghe thử lần đầu)")
        self.list.itemChanged.connect(lambda *_: self._refresh_track_styles())
        self.list.changed.connect(self._emit)
        self.list.filesDropped.connect(self.add_paths)
        self.list.emptyClicked.connect(self._add_files)
        self.list.openRequested.connect(w.open_with_default_app)
        self.list.menu_extras = [("pin", "Ghim / bỏ ghim: luôn có trong file (mọi bản)", self._toggle_pin),
                                 ("volume", "Đặt âm lượng bài đang chọn…", self._ask_track_volume),
                                 ("copy", "Nhân bản bài (Ctrl+D) — phát lại bài này ở chỗ khác", lambda _it: self._duplicate()),
                                 ("copy", "Chép các bài đang chọn (Ctrl+C)", lambda _it: self._copy_rows()),
                                 ("file_plus", "Dán bên dưới (Ctrl+V)", lambda _it: self._paste_rows())]
        # Ctrl+D nhân bản · Ctrl+C / Ctrl+V chép rồi dán xuống dưới bài đang chọn (giữ số lần, âm lượng, ghim)
        from PySide6.QtGui import QKeySequence, QShortcut
        self._clipboard: list[tuple] = []
        for seq, fn, ctx in ((QKeySequence("Ctrl+D"), self._duplicate, Qt.ShortcutContext.WidgetWithChildrenShortcut),
                             (QKeySequence(QKeySequence.StandardKey.Copy), self._copy_rows, Qt.ShortcutContext.WidgetShortcut),
                             (QKeySequence(QKeySequence.StandardKey.Paste), self._paste_rows,
                              Qt.ShortcutContext.WidgetShortcut)):
            sc = QShortcut(seq, self.list)
            sc.setContext(ctx)
            sc.activated.connect(fn)
        self.toolbar = w.ListToolbar(self.list, self._add_files, self._add_folder, random.Random)
        self.count_label = QLabel("0 bài")
        self.count_label.setObjectName("chip")
        self.status = w.muted("")
        hint = w.ElidedLabel()
        hint.setObjectName("muted")
        hint.set_full_text("Mẹo: bỏ tick bài không muốn dùng · kéo dòng để đổi thứ tự",
                           "Bỏ tick bài không muốn dùng · Kéo dòng để đổi thứ tự · Bấm đúp tên bài để nghe · "
                           "Bấm đúp cột Âm lượng % để chỉnh to / nhỏ riêng bài đó")

        # Khung trên của cột trái: Playlist
        top_left = QWidget()
        tlv = QVBoxLayout(top_left)
        tlv.setContentsMargins(0, 0, 0, 0)
        tlv.setSpacing(6)
        head_row = QHBoxLayout()
        pl_title = QLabel("Playlist nhạc")
        pl_title.setObjectName("h2")
        head_row.addWidget(pl_title)
        head_row.addWidget(self.count_label)
        head_row.addStretch(1)
        head_row.addWidget(self.status)
        tlv.addLayout(head_row)
        tlv.addWidget(self.toolbar)
        self.list.setMinimumHeight(170)
        tlv.addWidget(self.list, 1)
        self.hint_label = hint
        tlv.addWidget(hint)

        # Khung dưới của cột trái: Lịch phát nhạc (Chapters)
        self.schedule = w.PlaceholderTree("Lịch phát dự kiến (mốc thời gian từng bài) sẽ hiện tại đây khi có nhạc.")
        self.schedule.setHeaderLabels(["Mốc bắt đầu", "Tên bài nhạc"])
        self.schedule.setRootIsDecorated(False)
        self.schedule.setAlternatingRowColors(True)
        self._size_cols()
        theme.on_change(self.schedule, self._size_cols)
        self.schedule_label = QLabel("Lịch phát dự kiến (YouTube Chapters)")
        self.schedule_label.setObjectName("h2")
        self.schedule_badge = QLabel("0 lượt")
        self.schedule_badge.setObjectName("chip")

        bot_left = QWidget()
        blv = QVBoxLayout(bot_left)
        blv.setContentsMargins(0, 4, 0, 0)
        blv.setSpacing(6)
        sch_hdr = QHBoxLayout()
        sch_hdr.addWidget(self.schedule_label)
        sch_hdr.addWidget(self.schedule_badge)
        sch_hdr.addStretch(1)
        self.lbl_view_version = QLabel("Xem bản")
        self.view_version = QComboBox()
        self.view_version.setToolTip("Xuất nhiều bản: xem lịch phát (thứ tự bài) của từng bản")
        self.view_version.currentIndexChanged.connect(
            lambda i: None if self._loading or i < 0 else self.versionPreviewChanged.emit(i))
        sch_hdr.addWidget(self.lbl_view_version)
        sch_hdr.addWidget(self.view_version)
        self.lbl_view_version.hide()
        self.view_version.hide()
        blv.addLayout(sch_hdr)
        blv.addWidget(self.schedule, 1)

        left_split = QSplitter(Qt.Orientation.Vertical)
        left_split.setChildrenCollapsible(False)
        left_split.addWidget(top_left)
        left_split.addWidget(bot_left)
        left_split.setStretchFactor(0, 3)
        left_split.setStretchFactor(1, 2)
        left_split.setSizes([420, 220])

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        lv.addWidget(self.banner)
        lv.addWidget(left_split, 1)
        self.next_btn = w.ShrinkButton("Tiếp theo: Xuất thành phẩm")
        self.next_btn.setObjectName("nextStepBtn")
        self.next_btn.setIcon(icons.icon("arrow_right", 14, "text_on_accent"))
        self.next_btn.setIconSize(QSize(14, 14))
        self.next_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.next_btn.clicked.connect(self.nextStepRequested.emit)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.settings_btn = w.ShrinkButton("Cài đặt nhạc")
        self.settings_btn.setObjectName("ghost")
        self.settings_btn.setIcon(icons.icon("down", 14, "text_2"))
        self.settings_btn.setIconSize(QSize(14, 14))
        self.settings_btn.setToolTip("Cuộn xuống phần cài đặt: độ dài file nhạc, bảng trộn âm, tiếng nền, thứ tự phát")
        self.settings_btn.clicked.connect(lambda: w.scroll_page_to_bottom(self))
        self.settings_btn.setVisible(False)
        foot.addStretch(1)
        foot.addWidget(self.settings_btn)
        foot.addWidget(self.next_btn)
        lv.addLayout(foot)

        # ----- Cột phải: Cài đặt Nhạc & Tiếng nền -----
        self.order = combo(ORDER)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_000_000_000)
        dice = QPushButton("Đổi mầm")
        dice.setIcon(icons.icon("refresh", 13))
        dice.setIconSize(QSize(13, 13))
        dice.setToolTip("Tạo thứ tự phát ngẫu nhiên khác")
        dice.clicked.connect(lambda: self.seed.setValue(random.randint(0, 999_999)))
        self.seed_wrap = QWidget()
        seed_row = QHBoxLayout(self.seed_wrap)
        seed_row.setContentsMargins(0, 0, 0, 0)
        seed_row.setSpacing(6)
        seed_row.addWidget(self.seed, 1)
        seed_row.addWidget(dice)
        self.lbl_seed = QLabel("Số mầm (Seed)")

        g_order = QGroupBox("Thứ tự phát Playlist")
        f = QFormLayout(g_order)
        f.setVerticalSpacing(8)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)  # cột hẹp / chữ to: nhãn lên trên, không đẩy cột
        f.addRow("Chế độ phát", self.order)
        f.addRow(self.lbl_seed, self.seed_wrap)
        self.pin_info = QLabel("")
        self.pin_info.setObjectName("muted")
        self.pin_info.setWordWrap(True)
        self.pin_pos = combo(PIN_POS)
        self.pin_pos.setToolTip("Bài ghim (chuột phải bài → Ghim) đặt ở đâu trong file")
        self.lbl_pin_pos = QLabel("Bài ghim đặt ở")
        f.addRow("Bài ghim", self.pin_info)
        f.addRow(self.lbl_pin_pos, self.pin_pos)
        self.pin_pos.currentIndexChanged.connect(self._emit)

        def secs(hi: float, special: str = "") -> QDoubleSpinBox:
            sb = QDoubleSpinBox()
            sb.setRange(0, hi)
            sb.setSingleStep(0.5)
            sb.setSuffix(" giây")
            sb.setDecimals(1)
            if special:
                sb.setSpecialValueText(special)
            sb.valueChanged.connect(self._emit)
            return sb

        self.crossfade = secs(30, "Nối thẳng (0s)")
        self.gap = secs(30, "Không nghỉ (0s)")
        self.fade_in = secs(30)
        self.fade_out = secs(30)
        self.lbl_gap = QLabel("Khoảng lặng giữa bài")
        self.gap_hint = w.muted("Khi bật Crossfade > 0s, các bài sẽ hoà âm trực tiếp vào nhau (bỏ qua khoảng lặng).")
        g_tr = QGroupBox("Chuyển bài && Mở / Kết")
        f = QFormLayout(g_tr)
        f.setVerticalSpacing(8)
        f.addRow("Crossfade giữa bài", self.crossfade)
        f.addRow(self.lbl_gap, self.gap)
        f.addRow(self.gap_hint)
        f.addRow("To dần ở đầu (Fade-in)", self.fade_in)
        f.addRow("Nhỏ dần ở cuối (Fade-out)", self.fade_out)

        self.loud_on = QCheckBox("Chuẩn hoá âm lượng các bài cho đều nhau")
        self.lufs = QDoubleSpinBox()
        self.lufs.setRange(-30, -5)
        self.lufs.setSuffix(" LUFS")
        self.lufs.setToolTip("YouTube chuẩn hoá về khoảng -14 LUFS")
        self.lbl_lufs = QLabel("Mức âm lượng đích")
        g_loud = QGroupBox("Chuẩn hoá âm lượng (YouTube LUFS)")
        f = QFormLayout(g_loud)
        f.setVerticalSpacing(8)
        f.addRow(self.loud_on)
        f.addRow(self.lbl_lufs, self.lufs)

        # ----- tiếng nền -----
        self.ambient = w.MediaList(["Lớp tiếng nền (tự lặp)", "Âm lượng %"])
        self.ambient.placeholder = (
            "Chưa có tiếng nền (mưa, lửa trại, sóng biển…)\n"
            "Kéo thả file âm thanh vào đây, hoặc bấm nút bên dưới"
        )
        self.ambient.placeholder_action = "Thêm tiếng nền"
        self.ambient.setItemDelegateForColumn(1, w.SpinDelegate(0, 200, self.ambient))
        self.ambient.header().setStretchLastSection(False)
        self.ambient.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.ambient.setColumnWidth(1, 96)
        self.ambient.setMinimumHeight(120)
        self.ambient.setMaximumHeight(165)
        self.ambient.changed.connect(self._emit)
        self.ambient.filesDropped.connect(self.add_ambient)
        self.ambient.emptyClicked.connect(self._pick_ambient)
        self.ambient.openRequested.connect(lambda p: w.open_with_default_app(ambient_lib.resolve(p)))
        a_add = QPushButton("Thêm tiếng nền")
        a_add.setObjectName("accentBtn")
        icons.bind(a_add, "plus", 13, "accent_text")
        a_add.setIconSize(QSize(13, 13))
        a_add.clicked.connect(self._pick_ambient)
        a_lib = QPushButton("Thư viện có sẵn…")
        a_lib.setObjectName("pill")
        a_lib.setIcon(icons.icon("waves", 13, "info_text"))
        a_lib.setIconSize(QSize(13, 13))
        a_lib.setToolTip("Mưa, sóng biển, gió, lửa củi, white / pink / brown noise — app tự tạo, không cần file")
        a_lib.clicked.connect(self._open_ambient_library)
        self.a_lib = a_lib
        a_del = QPushButton("Xoá lớp")
        a_del.setObjectName("ghost")
        a_del.setIcon(icons.icon("trash", 13))
        a_del.setIconSize(QSize(13, 13))
        a_del.clicked.connect(self.ambient.remove_selected)
        g_amb = QGroupBox("Lớp tiếng nền (Mưa, Lửa, Sóng…)")
        self.g_amb = g_amb
        av = QVBoxLayout(g_amb)
        av.setSpacing(6)
        av.addWidget(w.muted("Phát lặp xuyên suốt dưới nền nhạc/video. Chỉnh % âm lượng bằng cách bấm đúp cột Âm lượng."))
        av.addWidget(self.ambient)
        ar_box = QWidget()  # tự xuống dòng khi cột hẹp
        ar = w.FlowLayout(ar_box, spacing=5)
        ar.addWidget(a_lib)
        a_add.setText("Thêm file…")
        ar.addWidget(a_add)
        for v_pct in (25, 50, 80):
            vb = QPushButton(f"{v_pct}%")
            vb.setObjectName("pill")
            vb.setToolTip(f"Đặt âm lượng {v_pct}% cho lớp tiếng nền đang chọn")
            vb.clicked.connect(lambda _=False, val=v_pct: self._set_ambient_vol(val))
            ar.addWidget(vb)
        ar.addWidget(a_del)
        av.addWidget(ar_box)

        # ----- xuất riêng nhạc: chuyển sang kiểu "Chỉ nhạc" -----
        to_music = QPushButton("Chuyển sang kiểu “Chỉ nhạc”")
        to_music.setIcon(icons.icon("music", 14))
        to_music.setIconSize(QSize(14, 14))
        to_music.clicked.connect(lambda: self.switchModeRequested.emit("music_only"))
        self.g_exp = QGroupBox("Chỉ cần xuất file nhạc dài (không hình)?")
        ev = QVBoxLayout(self.g_exp)
        ev.addWidget(w.muted("Chuyển sang chế độ <b>Chỉ nhạc</b> để ghép playlist này thành file MP3 / M4A / FLAC / WAV "
                             "theo thời lượng bất kỳ."))
        ev.addWidget(to_music, 0, Qt.AlignmentFlag.AlignLeft)

        # ----- độ dài file nhạc (chỉ hiện ở kiểu "Chỉ nhạc") -----
        self.len_mode = combo(EXPORT_MODE)
        self.len_target = hms_edit()
        self.len_rounds = QSpinBox()
        self.len_rounds.setRange(1, 999)
        self.len_rounds.setSuffix(" lượt")
        self.len_info = QLabel("")
        self.len_info.setObjectName("info")
        self.len_info.setWordWrap(True)
        self.g_length = QGroupBox("Độ dài file nhạc")
        f_len = QFormLayout(self.g_length)
        f_len.setVerticalSpacing(8)
        f_len.addRow(w.muted("Playlist tự lặp cho đủ độ dài này. Ví dụ 10 bài dài 30 phút → chọn <b>1h</b> "
                             "là ra file 1 giờ."))
        f_len.addRow("Tính theo", self.len_mode)
        self.len_target_wrap = QWidget()
        self.len_target_wrap.setLayout(quick_buttons(
            self.len_target, (("30p", 1800), ("1h", 3600), ("2h", 7200), ("3h", 10800), ("10h", 36000))))
        self.len_target_wrap.layout().setContentsMargins(0, 0, 0, 0)
        self.lbl_len_target = QLabel("Dài bao lâu")
        self.lbl_len_rounds = QLabel("Số lượt playlist")
        f_len.addRow(self.lbl_len_target, self.len_target_wrap)
        f_len.addRow(self.lbl_len_rounds, self.len_rounds)
        self.versions = QSpinBox()
        self.versions.setRange(1, 50)
        self.versions.setSuffix(" bản")
        self.versions.setToolTip("Xuất nhiều file cùng các bài nhưng mỗi file một thứ tự phát khác nhau "
                                 "(và cố gắng mở đầu bằng bài khác nhau)")
        ver_row = QHBoxLayout()
        ver_row.setContentsMargins(0, 0, 0, 0)
        ver_row.setSpacing(4)
        ver_row.addWidget(self.versions)
        for n in (1, 2, 4, 6):
            q = QPushButton(f"{n}")
            q.setObjectName("pill")
            q.clicked.connect(lambda _=False, v=n: self.versions.setValue(v))
            ver_row.addWidget(q)
        ver_row.addStretch(1)
        ver_wrap = QWidget()
        ver_wrap.setLayout(ver_row)
        f_len.addRow("Số bản xuất", ver_wrap)
        self.ver_info = w.muted("")
        self.ver_info.setWordWrap(True)
        f_len.addRow(self.ver_info)
        self.versions.valueChanged.connect(self._emit)
        f_len.addRow(self.len_info)
        self.g_length.hide()
        self.len_mode.currentIndexChanged.connect(self._emit)
        self.len_rounds.valueChanged.connect(self._emit)
        self.len_target.valueChanged.connect(self._emit)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 6, 0)
        rv.setSpacing(8)
        self.playlist_cards = (g_order, g_tr, g_loud)
        # thứ tự theo mức hay dùng: độ dài (Chỉ nhạc) → tiếng nền → thứ tự phát → [nâng cao: chuyển bài, âm lượng]
        self.adv_btn = w.ShrinkButton("Nâng cao ▾  (chuyển bài, âm lượng)")  # co lại được, không đẩy cột phải
        self.adv_btn.setObjectName("ghost")
        self.adv_btn.setCheckable(True)
        self.adv_btn.setToolTip("Mặc định đã tốt cho YouTube: crossfade 3 giây, chuẩn hoá -14 LUFS")
        self.mixer = MixerPanel()
        self.mixer.ambientVolumeChanged.connect(self._mixer_ambient)
        for g in (self.g_length, self.mixer, g_amb, g_order, self.adv_btn, g_tr, g_loud, self.g_exp):
            rv.addWidget(g)
        rv.addStretch(1)
        self._adv_cards = (g_tr, g_loud)

        def show_adv(on: bool) -> None:
            for g in self._adv_cards:
                if g.isVisible() != on and self.isVisible():
                    motion.slide_visible(g, on, 220)  # mở / gấp mượt
                else:
                    g.setVisible(on)
            self.adv_btn.setText("Ẩn tuỳ chọn nâng cao ▴" if on else
                                 "Nâng cao ▾  (chuyển bài, âm lượng)")
            self.settings.setValue("ui/music_advanced", "true" if on else "false")

        self.adv_btn.toggled.connect(show_adv)
        self.adv_btn.setChecked(self.settings.value("ui/music_advanced", "false") in (True, "true"))
        show_adv(self.adv_btn.isChecked())
        scroll = QScrollArea()
        scroll.setWidget(right)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(440)
        left.setMinimumWidth(420)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        right_panel = QWidget()
        rp_lay = QVBoxLayout(right_panel)
        rp_lay.setContentsMargins(0, 0, 0, 0)
        rp_lay.setSpacing(8)
        rp_lay.addWidget(scroll, 1)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(left)
        split.addWidget(right_panel)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([980, 460])
        self.split = split
        lay = QVBoxLayout(self)
        theme.page_layout(lay)
        lay.addWidget(split)

        self.order.currentIndexChanged.connect(self._emit)
        for wdg in (self.seed, self.lufs):
            wdg.valueChanged.connect(self._emit)
        self.loud_on.toggled.connect(self._emit)

    def _mixer_ambient(self, row: int, vol: int) -> None:
        """Kéo thanh tiếng nền ở Bảng trộn âm → ghi vào bảng tiếng nền."""
        items = self.ambient.items()
        if 0 <= row < len(items):  # chỉ ghi số vào bảng; cửa sổ chính tự tính lại khi người dùng ngừng kéo
            self.ambient.blockSignals(True)
            items[row].setText(1, str(vol))
            self.ambient.blockSignals(False)

    def _sync_mixer(self) -> None:
        layers = []
        for it in self.ambient.items():
            try:
                vol = int(it.text(1))
            except ValueError:
                vol = 50
            layers.append((ambient_lib.display_name(it.data(0, w.ROLE_DATA).path), vol,
                           it.checkState(0) == Qt.CheckState.Checked))
        self.mixer.set_ambient(layers)

    def _ask_track_volume(self, item) -> None:
        from PySide6.QtWidgets import QInputDialog
        sel = self.list.selectedItems() or [item]
        try:
            cur = int(item.text(COL_VOL))
        except ValueError:
            cur = 100
        vol, ok = QInputDialog.getInt(self, "Âm lượng bài nhạc",
                                      f"Âm lượng cho {len(sel)} bài đang chọn (%):\n100 = giữ nguyên · 50 ≈ nhỏ đi 6 dB "
                                      "· 150 ≈ to thêm 3,5 dB", cur, 0, 200, 5)
        if not ok:
            return
        self.list.blockSignals(True)
        for it in sel:
            it.setText(COL_VOL, str(vol))
        self.list.blockSignals(False)
        self._emit()

    def _set_ambient_vol(self, vol: int) -> None:
        sel = self.ambient.selectedItems() or self.ambient.items()
        if not sel:
            return
        self.ambient.blockSignals(True)
        for it in sel:
            it.setText(1, str(vol))
        self.ambient.blockSignals(False)
        self._emit()

    def _refresh_track_styles(self) -> None:
        items = self.list.items()
        active = 0
        self.list.blockSignals(True)
        for it in items:
            try:
                plays = int(it.text(COL_PLAYS))
            except ValueError:
                plays = 1
            on = it.checkState(0) == Qt.CheckState.Checked and plays > 0
            if on:
                active += 1
            col_main = theme.qcolor("text") if on else theme.qcolor("text_disabled")
            col_sub = theme.qcolor("text_muted") if on else theme.qcolor("text_disabled")
            col_Acc = QColor(theme.T['accent_soft']) if on else theme.qcolor("text_disabled")
            it.setForeground(COL_NAME, col_main)
            it.setForeground(COL_DUR, col_sub)
            it.setForeground(COL_PLAYS, col_Acc)
            it.setForeground(COL_VOL, (theme.qcolor("warn_text") if it.text(COL_VOL) != "100" else col_sub) if on else col_sub)
            it.setForeground(COL_LUFS, theme.qcolor("success_text") if (on and it.text(COL_LUFS) != "—") else col_sub)
        self.list.blockSignals(False)
        total = len(items)
        self.count_label.setText(f"{active}/{total} bài bật" if total else "0 bài")

    # ---------- dữ liệu ----------
    def load(self, ms: MusicSettings) -> None:
        self._loading = True
        self._load_gen = getattr(self, "_load_gen", 0) + 1
        self.list.blockSignals(True)
        self.list.clear()
        for t, info in zip(ms.tracks, w.probe.probe_many([t.path for t in ms.tracks])):
            self.list.addTopLevelItem(self._make_item(t, info))
        self.list.blockSignals(False)
        self._refresh_track_styles()
        self.ambient.blockSignals(True)
        self.ambient.clear()
        for a in ms.ambient:
            self.ambient.addTopLevelItem(self._make_ambient(a))
        self.ambient.blockSignals(False)
        set_combo(self.order, ms.order)
        self.seed.setValue(ms.seed)
        self.crossfade.setValue(ms.crossfade)
        self.gap.setValue(ms.gap)
        self.fade_in.setValue(ms.fade_in)
        self.fade_out.setValue(ms.fade_out)
        self.loud_on.setChecked(ms.loudness_enabled)
        self.lufs.setValue(ms.lufs)
        set_combo(self.len_mode, ms.export_mode)
        self.versions.setValue(max(1, ms.versions))
        set_combo(self.pin_pos, ms.pin_pos)
        self.len_target.set_seconds(ms.export_target, emit=False)
        self.len_rounds.setValue(max(1, ms.export_rounds))
        self._loading = False
        self._update_enabled()
        self._update_pin_info()
        self._sync_mixer()

    def collect(self) -> MusicSettings:
        ms = MusicSettings()
        for it in self.list.items():
            t: MusicTrack = it.data(0, w.ROLE_DATA)
            try:
                plays = int(it.text(COL_PLAYS))
            except ValueError:
                plays = 1
            try:
                vol = max(0, min(200, int(it.text(COL_VOL))))
            except ValueError:
                vol = 100
            ms.tracks.append(MusicTrack(path=t.path, plays=plays, pinned=t.pinned, volume=vol,
                                        enabled=it.checkState(0) == Qt.CheckState.Checked))
        for it in self.ambient.items():
            a: AmbientLayer = it.data(0, w.ROLE_DATA)
            try:
                vol = int(it.text(1))
            except ValueError:
                vol = 50
            ms.ambient.append(AmbientLayer(path=a.path, volume=vol,
                                           enabled=it.checkState(0) == Qt.CheckState.Checked))
        ms.order = self.order.currentData()
        ms.seed = self.seed.value()
        ms.crossfade = self.crossfade.value()
        ms.gap = self.gap.value()
        ms.fade_in = self.fade_in.value()
        ms.fade_out = self.fade_out.value()
        ms.loudness_enabled = self.loud_on.isChecked()
        ms.lufs = self.lufs.value()
        ms.export_mode = self.len_mode.currentData()
        ms.export_target = self.len_target.seconds()
        ms.export_rounds = self.len_rounds.value()
        ms.versions = self.versions.value()
        ms.pin_pos = self.pin_pos.currentData()
        return ms

    # ---------- ghim bài / nhiều bản ----------
    def _toggle_pin(self, item) -> None:
        sel = self.list.selectedItems() or [item]
        on = not item.data(0, w.ROLE_DATA).pinned
        for it in sel:
            t: MusicTrack = it.data(0, w.ROLE_DATA)
            t.pinned = on
            it.setData(0, w.ROLE_DATA, t)
            self._style_pin(it)
        self._emit()

    def _style_pin(self, it) -> None:
        t: MusicTrack = it.data(0, w.ROLE_DATA)
        it.setIcon(COL_NAME, icons.icon("pin", 14, "warn_text") if t.pinned else QIcon())
        tip = t.path + ("\nBài ghim: luôn có trong file (mọi bản)" if t.pinned else "")
        it.setToolTip(COL_NAME, tip)

    def _update_pin_info(self) -> None:
        pins = [Path(it.data(0, w.ROLE_DATA).path).stem for it in self.list.items() if it.data(0, w.ROLE_DATA).pinned]
        if pins:
            shown = ", ".join(pins[:2]) + (f" và {len(pins) - 2} bài nữa" if len(pins) > 2 else "")
            self.pin_info.setText(f"<span style='color:{theme.T['warn_text']}'>Đã ghim {len(pins)} bài:</span> {shown}")
        else:
            self.pin_info.setText("Chưa ghim bài nào — chuột phải một bài → <i>Ghim</i> để bài đó luôn có trong file.")
        self.lbl_pin_pos.setVisible(bool(pins))
        self.pin_pos.setVisible(bool(pins))

    def preview_version(self) -> int:
        # isHidden (không phải isVisible): trang Nhạc đang khuất thì vẫn xem đúng bản đã chọn
        return max(0, self.view_version.currentIndex()) if not self.view_version.isHidden() else 0

    def set_versions_view(self, n: int, music_only: bool) -> None:
        """Ô "Xem bản 1 / 2 / …" cạnh lịch phát khi xuất nhiều bản."""
        show = music_only and n > 1
        cur = self.view_version.currentIndex()
        if self.view_version.count() != n:
            self._loading, was = True, self._loading
            self.view_version.clear()
            for k in range(n):
                self.view_version.addItem(f"Bản {k + 1}")
            self.view_version.setCurrentIndex(min(max(0, cur), n - 1))
            self._loading = was
        self.lbl_view_version.setVisible(show)
        self.view_version.setVisible(show)
        if n > 1:
            self.ver_info.setText(f"→ {n} file, cùng các bài nhưng <b>mỗi file một thứ tự</b>, cố gắng mở đầu bằng "
                                  "bài khác nhau. Bài ghim luôn có trong mọi bản.")
        else:
            self.ver_info.setText("Muốn nhiều bản khác thứ tự (để đăng nhiều video), tăng số bản.")

    def set_audio_info(self, text: str) -> None:
        self.len_info.setText(text)

    def set_schedule(self, items: list[MusicItem], paths: list[str], total: float, banner: str) -> None:
        self.banner.setText(banner)
        self.schedule.clear()
        long = total >= 3600
        rows = []
        for it in items[:3000]:
            start = w.fmt_dur(it.start) if long else f"{int(it.start) // 60:02d}:{int(it.start) % 60:02d}"
            row = QTreeWidgetItem([start, Path(paths[it.track]).stem])
            row.setForeground(0, theme.qcolor("info_text"))
            rows.append(row)
        self.schedule.addTopLevelItems(rows)
        self.schedule_badge.setText(f"{len(items)} lượt phát")

    def _fit_cols(self) -> None:
        """Narrow list: hide Độ to gốc, then Âm lượng, until ~16 characters of the track name fit."""
        lst = self.list
        need = lst.fontMetrics().horizontalAdvance("0") * 18 + 44
        widths = {c: theme.px(x) for c, x in ((COL_DUR, 92), (COL_PLAYS, 102), (COL_VOL, 96), (COL_LUFS, 110))}
        free = lst.viewport().width() - sum(widths.values())
        for c in (COL_LUFS, COL_VOL):
            hide = free < need
            lst.setColumnHidden(c, hide)
            if hide:
                free += widths[c]

    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self.list.viewport() and ev.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._fit_cols)
        return super().eventFilter(obj, ev)

    def adapt(self, width: int, height: int = 0) -> None:
        """Gọi từ cửa sổ chính khi đổi kích thước: hẹp thì xếp phần cài đặt xuống dưới (bảng cao vừa một màn hình)."""
        w.adapt_tab(self, width, height, 440, 900, 500)

    def set_playlist_enabled(self, enabled: bool) -> None:
        for wdg in (self.toolbar, self.list, *self.playlist_cards):
            wdg.setEnabled(enabled)

    def set_mode(self, mode: str) -> None:
        """Kiểu 'Chỉ video': playlist không dùng (khoá thao tác)."""
        self.set_playlist_enabled(mode != "video_only")
        self.g_exp.setVisible(mode == "video_music")
        self.g_length.setVisible(mode == "music_only")

    def _row_copy(self, it) -> tuple:
        t: MusicTrack = it.data(0, w.ROLE_DATA)
        return (t, it.data(0, w.ROLE_INFO), it.text(COL_PLAYS), it.text(COL_VOL), it.checkState(0))

    def _insert_rows(self, rows: list[tuple], pos: int, what: str) -> None:
        self.list.blockSignals(True)
        new_items = []
        for k, (t, info, plays, vol, check) in enumerate(rows):
            # bản sao không mang ghim (ghim 2 lần = bài đó phát 2 lần liền ở đầu file)
            it = self._make_item(MusicTrack(path=t.path, enabled=True, plays=t.plays, pinned=False,
                                            volume=t.volume), info)
            self.list.insertTopLevelItem(pos + k, it)
            it.setText(COL_PLAYS, plays)
            it.setText(COL_VOL, vol)
            it.setCheckState(0, check)
            new_items.append(it)
        self.list.blockSignals(False)
        self.list.clearSelection()
        for it in new_items:
            it.setSelected(True)
        self.list.scrollToItem(new_items[-1])
        self._refresh_track_styles()
        self.status.setText(f"{what} {len(new_items)} bài — cùng một bài có thể phát ở nhiều chỗ trong playlist.")
        self._emit()

    def _duplicate(self) -> None:
        sel = sorted(self.list.selectedItems(), key=self.list.indexOfTopLevelItem)
        if not sel:
            return
        self._insert_rows([self._row_copy(it) for it in sel], self.list.indexOfTopLevelItem(sel[-1]) + 1, "Đã nhân bản")

    def _copy_rows(self) -> None:
        sel = sorted(self.list.selectedItems(), key=self.list.indexOfTopLevelItem)
        if not sel:
            return
        self._clipboard = [self._row_copy(it) for it in sel]
        self.status.setText(f"Đã chép {len(sel)} bài — chọn chỗ muốn dán rồi bấm Ctrl+V (dán ngay bên dưới).")

    def _paste_rows(self) -> None:
        if not self._clipboard:
            self.status.setText("Chưa chép bài nào — bôi đen các bài rồi bấm Ctrl+C trước.")
            return
        sel = self.list.selectedItems()
        pos = max(self.list.indexOfTopLevelItem(it) for it in sel) + 1 if sel else self.list.topLevelItemCount()
        self._insert_rows(self._clipboard, pos, "Đã dán")

    def _make_item(self, t: MusicTrack, info: MediaInfo) -> QTreeWidgetItem:
        lufs = audio_build.cached_loudness(t.path) if info.ok else None
        it = self.list.new_item([Path(t.path).name,
                                 w.fmt_dur(info.duration) if info.ok else f"LỖI: {info.error}",
                                 str(t.plays), str(t.volume), f"{lufs:.1f} LUFS" if lufs is not None else "—"],
                                t.enabled)
        it.setData(0, w.ROLE_DATA, t)
        it.setData(0, w.ROLE_INFO, info)
        it.setToolTip(COL_NAME, t.path)
        it.setToolTip(COL_LUFS, "Đo khi xuất lần đầu, sau đó được nhớ lại")
        it.setTextAlignment(COL_PLAYS, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        it.setTextAlignment(COL_VOL, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        it.setTextAlignment(COL_DUR, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        it.setTextAlignment(COL_LUFS, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if t.pinned:
            self._style_pin(it)
        return it

    def _make_ambient(self, a: AmbientLayer) -> QTreeWidgetItem:
        builtin = ambient_lib.is_builtin(a.path)
        it = self.ambient.new_item([ambient_lib.display_name(a.path), str(a.volume)], a.enabled)
        it.setData(0, w.ROLE_DATA, a)
        it.setToolTip(0, "Âm có sẵn do app tự tạo, tự lặp liền mạch" if builtin else a.path)
        if builtin:
            it.setIcon(0, icons.icon("waves", 13, "info_text"))
        it.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
        return it

    # ---------- thêm file ----------
    def _add_files(self) -> None:
        files = w.pick_files(self, "Chọn nhạc", w.AUDIO_EXTS, self.settings.value("dir/music", ""))
        if files:
            self.settings.setValue("dir/music", os.path.dirname(files[0]))
            self.add_paths(files)

    def _add_folder(self) -> None:
        folder = w.pick_folder(self, "Chọn thư mục nhạc", self.settings.value("dir/music", ""))
        if folder:
            self.settings.setValue("dir/music", folder)
            self.add_paths(w.scan_folder(folder, w.AUDIO_EXTS, self.toolbar.recursive.isChecked()))

    def add_paths(self, paths: list[str]) -> None:
        files = w.expand_dropped(paths, w.AUDIO_EXTS, self.toolbar.recursive.isChecked())
        have = self.list.paths()
        files = [os.path.normpath(p) for p in files if os.path.normcase(os.path.normpath(p)) not in have]
        if not files:
            self.status.setText("Không có bài nhạc mới.")
            return
        self._prober = w.Prober()
        self._prober.progress.connect(lambda i, n: self.status.setText(f"Đang đọc {i}/{n} file…"))
        gen = getattr(self, "_load_gen", 0)
        self._prober.finished.connect(lambda infos, g=gen: self._on_probed(infos, g))
        self._prober.start(files)

    def _on_probed(self, infos: list[MediaInfo], gen: int | None = None) -> None:
        if gen is not None and gen != getattr(self, "_load_gen", 0):
            return  # đã mở / tạo dự án khác trong lúc đang đọc file
        bad = [i for i in infos if not (i.ok and i.has_audio)]
        self.list.blockSignals(True)
        for info in infos:
            if info.ok and info.has_audio:
                self.list.addTopLevelItem(self._make_item(MusicTrack(path=info.path), info))
        self.list.blockSignals(False)
        self._refresh_track_styles()
        msg = f"Đã thêm {len(infos) - len(bad)} bài."
        if bad:
            msg += f" Bỏ qua {len(bad)} file lỗi."
            QMessageBox.warning(self, "Có file không đọc được",
                                "\n".join(f"• {b.path}: {b.error or 'không có tiếng'}" for b in bad[:15]))
        self.status.setText(msg)
        self._emit()

    def _pick_ambient(self) -> None:
        files = w.pick_files(self, "Chọn tiếng nền", AMBIENT_EXTS, self.settings.value("dir/ambient", ""))
        if files:
            self.settings.setValue("dir/ambient", os.path.dirname(files[0]))
            self.add_ambient(files)

    def _open_ambient_library(self) -> None:
        from .ambient_library import AmbientLibraryDialog
        dlg = AmbientLibraryDialog(self.ambient.paths(), self)
        if not dlg.exec() or not dlg.result_keys:
            return
        self.ambient.blockSignals(True)
        for key in dlg.result_keys:
            self.ambient.addTopLevelItem(self._make_ambient(
                AmbientLayer(path=ambient_lib.PREFIX + key, volume=dlg.volume.value())))
        self.ambient.blockSignals(False)
        self._emit()

    def add_ambient(self, paths: list[str]) -> None:
        files = w.expand_dropped(paths, AMBIENT_EXTS, False)
        have = self.ambient.paths()
        files = [os.path.normpath(p) for p in files if os.path.normcase(os.path.normpath(p)) not in have]
        if not files:
            return
        self._amb_prober = w.Prober()
        gen = getattr(self, "_load_gen", 0)
        self._amb_prober.finished.connect(
            lambda infos, g=gen: self._on_ambient_probed(infos) if g == getattr(self, "_load_gen", 0) else None)
        self._amb_prober.start(files)

    def _on_ambient_probed(self, infos: list[MediaInfo]) -> None:
        bad = [i for i in infos if not (i.ok and i.has_audio)]
        self.ambient.blockSignals(True)
        for info in infos:
            if info.ok and info.has_audio:
                self.ambient.addTopLevelItem(self._make_ambient(AmbientLayer(path=info.path)))
        self.ambient.blockSignals(False)
        if bad:
            QMessageBox.warning(self, "File không có tiếng",
                                "\n".join(f"• {b.path}" for b in bad[:15]))
        self._emit()

    def refresh_loudness(self) -> None:
        self.list.blockSignals(True)
        for it in self.list.items():
            lufs = audio_build.cached_loudness(it.data(0, w.ROLE_DATA).path)
            if lufs is not None:
                it.setText(COL_LUFS, f"{lufs:.1f} LUFS")
        self.list.blockSignals(False)
        self._refresh_track_styles()

    def _update_enabled(self) -> None:
        by_time = self.len_mode.currentData() == "target"
        for wdg in (self.lbl_len_target, self.len_target_wrap):
            wdg.setVisible(by_time)
        for wdg in (self.lbl_len_rounds, self.len_rounds):
            wdg.setVisible(not by_time)
        has_xfade = self.crossfade.value() > 0
        self.lbl_gap.setVisible(not has_xfade)
        self.gap.setVisible(not has_xfade)
        self.gap.setEnabled(not has_xfade)
        self.gap_hint.setVisible(has_xfade)

        is_random = self.order.currentData() != "list"
        self.lbl_seed.setVisible(is_random)
        self.seed_wrap.setVisible(is_random)

        loud = self.loud_on.isChecked()
        self.lbl_lufs.setVisible(loud)
        self.lufs.setVisible(loud)
        self.lufs.setEnabled(loud)

    def _emit(self, *_) -> None:
        if self._loading:
            return
        self._sync_mixer()
        self._refresh_track_styles()
        self._update_enabled()
        self._update_pin_info()
        self.changed.emit()

