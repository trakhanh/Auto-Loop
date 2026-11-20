"""Trang "Tải video": dán link (lẻ / danh sách phát / kênh) → xem trước → tải MP4 / MP3 về thư mục bằng yt-dlp.

Xem docs/superpowers/specs/2026-11-20-tai-video-design.md. Công cụ (yt-dlp + Deno) cài khi dùng lần đầu, tự cập
nhật; file tải về chỉ nằm trong thư mục lưu — không tự đưa vào bảng clip / playlist / dự án."""
from __future__ import annotations

import hashlib
import re
import threading
import time
import urllib.request
from datetime import date
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation, QObject, QPropertyAnimation, QRect, QSettings, QSize, QStandardPaths, Qt, QTimer,
    QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QGuiApplication, QIcon, QKeySequence, QLinearGradient, QPainter, QPen, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QBoxLayout, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core import dl_tools, downloader, ffmpeg_tools, updater
from ..core import download_queue as dq
from ..core.downloader import Options
from . import icons, theme
from . import widgets as w

ROLE = Qt.ItemDataRole.UserRole
PROG_ROLE = Qt.ItemDataRole.UserRole + 1  # tiến độ 0..1 (None = không vẽ thanh)
# màu nhãn nền tảng (token theme.py)
PLATFORM_TOKENS = {"YouTube": "danger_text", "TikTok": "text", "Bilibili": "info_text", "X": "text_2",
                   "Facebook": "accent_text", "Instagram": "warn_text"}
PLATFORM_CHIPS = (("YouTube", "error"), ("TikTok", "text"), ("Bilibili", "info"), ("X", "muted"),
                  ("Facebook", "accent"), ("Instagram", "warn"))
MORE = "__more__"  # dòng "Hiện thêm" trong nhóm
CANCELLED = "__cancel__"


class _Bridge(QObject):
    info = Signal(str, object, str)  # (link, Item | Group | None, lỗi)
    more = Signal(str, object, str)  # (url nhóm, list[Item] | None, lỗi)
    read_done = Signal()
    progress = Signal(object, object)  # (Entry, Progress)
    stage = Signal(object, str)
    finished = Signal(object, object, str, str)  # (Entry, Result | None, câu lỗi / CANCELLED, stderr)
    install_progress = Signal(int, int)
    installed = Signal(str)  # lỗi ("" = xong)
    updated = Signal(object)  # list[str]
    thumb = Signal(str, str)  # (url ảnh, file đã lưu)


def default_folder() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation) or str(Path.home())
    return str(Path(base) / "KT Loop Station")


def combo(pairs, current) -> QComboBox:
    c = QComboBox()
    # chữ dài ("1080p — mở được mọi phần mềm") không được ép cả trang rộng ra: ô co lại, danh sách thả xuống vẫn đủ chữ
    c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    c.setMinimumContentsLength(8)
    for key, label in pairs:
        c.addItem(label, key)
    i = c.findData(current)
    c.setCurrentIndex(max(i, 0))
    return c


def fmt_speed(bps: float) -> str:
    if bps <= 0:
        return ""
    mb = bps / (1 << 20)
    return f"{mb:.1f} MB/s".replace(".", ",") if mb >= 1 else f"{bps / 1024:.0f} KB/s"


class Segmented(QWidget):
    """Hàng nút chọn một (thấy hết lựa chọn, bấm là xong) — API giống QComboBox để dùng thay chỗ nhau."""
    currentIndexChanged = Signal(int)

    def __init__(self, pairs, current, tips: dict | None = None, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._data: list = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for i, (key, label) in enumerate(pairs):
            b = QPushButton(label)
            b.setCheckable(True)
            theme.tag(b, variant="ghost")
            # chia đều bề ngang, không để chữ dài nhất ép cả cột Cài đặt rộng ra
            b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            b.setMinimumWidth(theme.px(48))
            if tips and key in tips:
                b.setToolTip(tips[key])
            self._group.addButton(b, i)
            lay.addWidget(b, 1)
            self._data.append(key)
        self._group.idClicked.connect(self.currentIndexChanged.emit)
        i = self.findData(current)
        self._group.button(i if i >= 0 else 0).setChecked(True)

    def findData(self, value) -> int:  # noqa: N802
        return self._data.index(value) if value in self._data else -1

    def currentIndex(self) -> int:  # noqa: N802
        return self._group.checkedId()

    def currentData(self):  # noqa: N802
        i = self.currentIndex()
        return self._data[i] if 0 <= i < len(self._data) else None

    def setCurrentIndex(self, i: int) -> None:  # noqa: N802
        if not 0 <= i < len(self._data) or i == self.currentIndex():
            return
        self._group.button(i).setChecked(True)
        self.currentIndexChanged.emit(i)

    def button(self, i: int) -> QPushButton:
        return self._group.button(i)


class PlatformDelegate(QStyledItemDelegate):
    """Cột Nền tảng: nhãn bo tròn, màu theo nền tảng."""

    def paint(self, painter: QPainter, option, index) -> None:
        text = index.data() or ""
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        st = opt.widget.style() if opt.widget else None
        if st is not None:
            st.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        if not text:
            return
        key = PLATFORM_TOKENS.get(text, "text_muted")
        fm = opt.fontMetrics
        wpx = fm.horizontalAdvance(text) + 16
        h = fm.height() + 4
        r = QRect(opt.rect.left() + 4, opt.rect.center().y() - h // 2, min(wpx, opt.rect.width() - 8), h)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(key, 46))
        painter.drawRoundedRect(r, h / 2, h / 2)
        painter.setPen(theme.qcolor(key))
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        sz = super().sizeHint(option, index)
        return QSize(sz.width() + 20, sz.height())


class ProgressDelegate(QStyledItemDelegate):
    """Cột Trạng thái: chữ như thường + thanh tiến độ màu ở dưới khi đang tải (vệt sáng chạy dọc thanh; chưa biết
    phần trăm — đang bắt đầu / ghép / chuyển mã — thì một khúc sáng chạy qua lại)."""

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        frac = index.data(PROG_ROLE)
        if frac is None:
            return
        frac = float(frac)
        r = option.rect.adjusted(6, 0, -8, 0)
        bar = QRect(r.left(), r.bottom() - 7, r.width(), 5)
        phase = (time.monotonic() * 0.7) % 1.0
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor("line"))
        painter.drawRoundedRect(bar, 2.5, 2.5)
        if frac < 0:  # chưa biết phần trăm
            seg = max(24, bar.width() // 3)
            x = bar.left() - seg + int((bar.width() + seg) * phase)
            part = QRect(max(bar.left(), x), bar.top(), min(seg, bar.right() - x) - max(0, bar.left() - x), bar.height())
            if part.width() > 0:
                painter.setBrush(theme.qcolor("accent"))
                painter.drawRoundedRect(part, 2.5, 2.5)
        else:
            done = QRect(bar.left(), bar.top(), max(5, int(bar.width() * max(0.0, min(1.0, frac)))), bar.height())
            painter.setBrush(theme.qcolor("accent"))
            painter.drawRoundedRect(done, 2.5, 2.5)
            sx = done.left() + int((done.width() + 40) * phase) - 40  # vệt sáng chạy trong phần đã tải
            g = QLinearGradient(sx, 0, sx + 40, 0)
            g.setColorAt(0.0, theme.qcolor("text", 0))
            g.setColorAt(0.5, theme.qcolor("text", 120))
            g.setColorAt(1.0, theme.qcolor("text", 0))
            painter.setClipRect(done)
            painter.setBrush(QBrush(g))
            painter.drawRoundedRect(done, 2.5, 2.5)
        painter.restore()


class Spinner(QWidget):
    """Vòng xoay "đang làm" (màu nhấn của bộ màu đang chọn)."""

    def __init__(self, size: int = 18, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._a = 0
        self._t = QTimer(self)
        self._t.setInterval(16)
        self._t.timeout.connect(self._tick)
        self.hide()

    def start(self) -> None:
        self.show()
        self._t.start()

    def stop(self) -> None:
        self._t.stop()
        self.hide()

    def _tick(self) -> None:
        self._a = (self._a + 7) % 360
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pw = max(2, self.width() // 9)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(pw, pw, -pw, -pw)
        pen = QPen(theme.qcolor("line"), pw)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawEllipse(r)
        pen.setColor(theme.qcolor("accent"))
        p.setPen(pen)
        p.drawArc(r, -self._a * 16, 110 * 16)


class DownloadPage(QWidget):
    busyChanged = Signal(bool)
    counterChanged = Signal(str)
    notice = Signal(str, str)  # (văn bản, "ok" | "info" | "warn")

    def __init__(self, settings: QSettings, exe_override: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._exe_override = exe_override
        self.opts = Options.from_settings(settings)
        self.queue = dq.DownloadQueue.load(self._queue_path())
        self._rows: dict[int, QTreeWidgetItem] = {}
        self._group_rows: dict[str, QTreeWidgetItem] = {}
        self._cancels: dict[int, threading.Event] = {}
        self._busy = False
        self._stopping = False
        self._reading = False
        self._updating_tree = False
        self._want_update = False
        self._tool_broken = False  # yt-dlp.exe không chạy được (hỏng / bị diệt virus chặn) → hiện lại thẻ cài
        self._halt = ""  # lý do tạm dừng lượt tải (mất mạng / công cụ hỏng)
        self._run_done = 0  # số video tải xong trong lượt này
        self._fracs: dict[int, float] = {}  # tiến độ từng video đang tải (cho thanh tổng)
        self._read_total = self._read_count = 0
        self.flashed: list[str] = []  # video vừa xong (dòng loé xanh)
        self._flash_anims: dict[int, QVariantAnimation] = {}
        self._anim = QTimer(self)  # vẽ lại thanh tiến độ cho vệt sáng chạy (chỉ chạy khi đang tải)
        self._anim.setInterval(40)
        self._h264_enc = "libx264"  # cửa sổ chính đổi sang encoder card đồ hoạ khi dò xong (set_encoders)
        self._install_cancel: threading.Event | None = None
        self._thumbs_wanted: set[str] = set()
        self.b = _Bridge()
        self.b.info.connect(self._on_info)
        self.b.more.connect(self._on_more)
        self.b.read_done.connect(self._on_read_done)
        self.b.progress.connect(self._on_progress)
        self.b.stage.connect(self._on_stage)
        self.b.finished.connect(self._on_finished)
        self.b.install_progress.connect(self._on_install_progress)
        self.b.installed.connect(self._on_installed)
        self.b.updated.connect(self._on_updated)
        self.b.thumb.connect(self._on_thumb)
        self._build()
        self._anim.timeout.connect(lambda: self.tree.viewport().update())
        for e in self.queue.entries:
            self._add_row(e)
        self._refresh_ready()
        self._update_tool_label()
        self._update_counts()

    # ---------- dựng giao diện ----------
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        theme.page_layout(lay)

        self.install_card = QGroupBox("Công cụ tải")
        ic = QVBoxLayout(self.install_card)
        ic.setContentsMargins(14, 30, 14, 12)
        ic.addWidget(w.muted("Cần cài công cụ tải (~65 MB, một lần): yt-dlp và Deno, lấy từ trang phát hành chính "
                             "thức, có kiểm tra file. Sau đó app tự cập nhật."))
        row = QHBoxLayout()
        self.install_btn = QPushButton("Cài công cụ tải")
        theme.tag(self.install_btn, variant="primary")
        self.install_btn.setIcon(icons.icon("download", 15, "white"))
        self.install_btn.clicked.connect(self.install_tools)
        self.install_bar = QProgressBar()
        self.install_bar.setTextVisible(False)
        self.install_bar.hide()
        self.install_cancel_btn = QPushButton("Huỷ")
        theme.tag(self.install_cancel_btn, variant="ghost")
        self.install_cancel_btn.hide()
        self.install_cancel_btn.clicked.connect(lambda: self._install_cancel and self._install_cancel.set())
        self.install_msg = w.muted("")
        row.addWidget(self.install_btn)
        row.addWidget(self.install_bar, 1)
        row.addWidget(self.install_cancel_btn)
        ic.addLayout(row)
        ic.addWidget(self.install_msg)
        lay.addWidget(self.install_card)

        # ----- thân trang: trái = dán link + danh sách · phải = Cài đặt tải (hẹp: xếp dọc) -----
        self.body = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.body.setSpacing(theme.SP['lg'])
        left_w = QWidget()
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(theme.SP['sm'])
        top = QHBoxLayout()
        self.links_edit = QPlainTextEdit()
        self.links_edit.setObjectName("linkBox")
        self.links_edit.setPlaceholderText("Dán link video vào đây — một hoặc nhiều link, mỗi dòng một link. "
                                           "Link danh sách phát / kênh cũng được.")
        self.links_edit.setFixedHeight(theme.px(64))
        self.read_btn = QPushButton("Đọc link")
        theme.tag(self.read_btn, variant="primary")
        self.read_btn.setIcon(icons.icon("search", 15, "white"))
        self.read_btn.setToolTip("Lấy tên, ảnh nhỏ, thời lượng để xem trước — chưa tải gì")
        self.read_btn.setMinimumHeight(theme.px(36))
        self.read_btn.clicked.connect(self.read_links)
        rcol = QVBoxLayout()
        rcol.setSpacing(6)
        rcol.addWidget(self.read_btn)
        self.read_spinner = Spinner(theme.px(18))
        rcol.addWidget(self.read_spinner, 0, Qt.AlignmentFlag.AlignHCenter)
        rcol.addStretch(1)
        top.addWidget(self.links_edit, 1)
        top.addLayout(rcol)
        left.addLayout(top)
        plat = QLabel(" · ".join(theme.span(tone, name) for name, tone in PLATFORM_CHIPS) +
                      theme.span("muted", " · và hơn 1.000 trang khác"))
        plat.setObjectName("muted")
        plat.setWordWrap(True)
        left.addWidget(plat)
        self.info_label = w.muted("")
        left.addWidget(self.info_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Video", "Nền tảng", "Thời lượng", "Trạng thái"])
        self.tree.setRootIsDecorated(True)
        self.tree.setIconSize(QSize(theme.px(64), theme.px(36)))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double)
        self.tree.setItemDelegateForColumn(1, PlatformDelegate(self.tree))
        self.tree.setItemDelegateForColumn(3, ProgressDelegate(self.tree))
        hd = self.tree.header()
        hd.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2):
            hd.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hd.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hd.resizeSection(3, theme.px(230))
        hd.setStretchLastSection(False)
        self.empty_view = self._build_empty()
        self.loading_view = self._build_loading()
        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.empty_view)
        self.list_stack.addWidget(self.loading_view)
        self.list_stack.addWidget(self.tree)
        self.list_stack.setMinimumHeight(theme.px(160))
        left.addWidget(self.list_stack, 1)
        self.body.addWidget(left_w, 1)

        self.side_card = self._build_side()
        self.side_scroll = QScrollArea()
        self.side_scroll.setWidget(self.side_card)
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.side_scroll.setFixedWidth(theme.px(345))
        self.body.addWidget(self.side_scroll)
        lay.addLayout(self.body, 1)

        # ----- thanh dưới: luôn trong màn hình -----
        bar = QHBoxLayout()
        bar.setSpacing(theme.SP['md'])
        self.selected_label = QLabel("")
        self.selected_label.setObjectName("h3")
        self.opts_summary = w.ElidedLabel("")
        self.opts_summary.setObjectName("muted")
        self.start_btn = QPushButton("Tải video")
        theme.tag(self.start_btn, variant="primary")
        self.start_btn.setIcon(icons.icon("download", 16, "white"))
        self.start_btn.setMinimumHeight(theme.px(38))
        self.start_btn.setMinimumWidth(theme.px(150))
        self.start_btn.clicked.connect(lambda: self.stop() if self._busy else self.start())
        self.open_btn = QPushButton("Mở thư mục")
        theme.tag(self.open_btn, variant="ghost")
        self.open_btn.setIcon(icons.icon("folder", 15))
        self.open_btn.clicked.connect(self.open_folder)
        self.more_btn = QPushButton()
        theme.tag(self.more_btn, variant="ghost")
        self.more_btn.setIcon(icons.icon("more", 15))
        self.more_btn.setToolTip("Thêm")
        m = QMenu(self.more_btn)
        m.addAction("Thử lại các video lỗi", self.retry_errors)
        m.addAction("Xoá danh sách (không xoá file)", self.clear_list)
        self.more_btn.setMenu(m)
        bar.addWidget(self.selected_label)
        bar.addWidget(self.opts_summary, 1)
        bar.addWidget(self.more_btn)
        bar.addWidget(self.open_btn)
        bar.addWidget(self.start_btn)
        self.run_bar = QProgressBar()  # tiến độ cả lượt tải (chạy mượt), chỉ hiện khi đang tải
        self.run_bar.setRange(0, 1000)
        self.run_bar.setTextVisible(False)
        self.run_bar.setFixedHeight(theme.px(6))
        self.run_bar.hide()
        self._run_anim = QPropertyAnimation(self.run_bar, b"value", self)
        self._run_anim.setDuration(260)
        lay.addWidget(self.run_bar)
        lay.addLayout(bar)

        open_ = str(self.settings.value("download/opts_open", "false")).lower() in ("true", "1")
        self.opts_panel.setVisible(open_)
        self.opts_btn.setChecked(open_)
        self._sync_opts_widgets()
        self.folder_label.setText(self.folder())
        self.folder_label.setToolTip(self.folder())
        sc = QShortcut(QKeySequence(QKeySequence.StandardKey.Paste), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(self._paste)

    def _build_empty(self) -> QWidget:
        box = QGroupBox()
        v = QVBoxLayout(box)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(theme.SP['md'])
        v.addStretch(1)
        ic = QLabel()
        icons.bind(ic, "download", 44, "accent_text")
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Chưa có video nào")
        title.setObjectName("h2")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        steps = QLabel("<b>1.</b> Dán link vào ô phía trên &nbsp;&nbsp; <b>2.</b> Bấm <b>Đọc link</b> để xem trước "
                       "&nbsp;&nbsp; <b>3.</b> Tick video muốn lấy rồi bấm <b>Tải</b>")
        steps.setObjectName("muted")
        steps.setWordWrap(True)
        steps.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = w.muted("Link kênh hoặc danh sách phát: app hiện cả nhóm, tick sẵn 50 video đầu.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for x in (ic, title, steps, hint):
            v.addWidget(x)
        v.addStretch(1)
        return box

    def _build_loading(self) -> QWidget:
        box = QGroupBox()
        v = QVBoxLayout(box)
        v.addStretch(1)
        self.big_spinner = Spinner(theme.px(44))
        v.addWidget(self.big_spinner, 0, Qt.AlignmentFlag.AlignHCenter)
        self.loading_label = QLabel("Đang đọc link…")
        self.loading_label.setObjectName("h2")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.loading_label)
        sub = w.muted("Đang lấy tên, ảnh nhỏ, thời lượng — chưa tải gì. Link kênh có thể mất vài giây.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(sub)
        v.addStretch(1)
        return box

    def _section(self, lay: QVBoxLayout, text: str) -> None:
        lab = QLabel(text)
        lab.setObjectName("sectionLabel")
        lay.addSpacing(theme.SP['xs'])
        lay.addWidget(lab)

    def _build_side(self) -> QWidget:
        card = QGroupBox("Cài đặt tải")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 30, 14, 14)
        v.setSpacing(theme.SP['xs'])
        self._section(v, "Định dạng")
        self.fmt_box = Segmented(downloader.FORMAT_LABELS, self.opts.fmt, downloader.FORMAT_TIPS)
        v.addWidget(self.fmt_box)
        self._section(v, "Chất lượng")
        self.quality_box = Segmented(downloader.QUALITY_LABELS, self.opts.quality,
                                     {"best": "Nét nhất trang có. YouTube trên 1080p là VP9 / AV1 — với MP4 + "
                                              "\"Luôn ra H.264\" app tự chuyển để mở được mọi phần mềm."})
        self.audio_box = Segmented(downloader.AUDIO_Q_LABELS, self.opts.audio_q)
        v.addWidget(self.quality_box)
        v.addWidget(self.audio_box)
        self.h264_chk = QCheckBox("Luôn ra H.264")
        self.h264_chk.setToolTip("Trang chỉ có H.265 / AV1 / VP9 (TikTok, Bilibili, YouTube 2K/4K…) → tải xong app tự "
                                 "chuyển sang H.264 bằng card đồ hoạ, để mở được mọi phần mềm dựng. "
                                 "Tắt nếu muốn giữ nguyên bản gốc.")
        self.h264_chk.setChecked(self.opts.h264)
        v.addWidget(self.h264_chk)

        self._section(v, "Lưu vào")
        frow = QHBoxLayout()
        frow.setSpacing(6)
        fic = QLabel()
        icons.bind(fic, "folder", 15, "accent_text")
        self.folder_label = w.ElidedLabel("", Qt.TextElideMode.ElideMiddle)
        self.folder_btn = QPushButton("Đổi")
        theme.tag(self.folder_btn, variant="ghost")
        self.folder_btn.clicked.connect(self.pick_folder)
        frow.addWidget(fic)
        frow.addWidget(self.folder_label, 1)
        frow.addWidget(self.folder_btn)
        v.addLayout(frow)

        self._section(v, "Đăng nhập")
        self.login_box = combo(downloader.LOGINS, str(self.settings.value("download/login", "") or ""))
        self.login_box.setToolTip("Dùng đăng nhập từ trình duyệt cho trang bắt đăng nhập. Firefox chắc chắn nhất; "
                                  "Chrome / Edge hay bị Windows chặn — khi đó dùng file đăng nhập (cookies.txt).")
        self._login_prev = self.login_box.currentIndex()
        self.login_box.currentIndexChanged.connect(self._login_changed)
        v.addWidget(self.login_box)

        self._section(v, "Lưu kèm")
        self.thumb_chk = QCheckBox("Ảnh bìa (.jpg)")
        self.thumb_chk.setToolTip("Lưu ảnh bìa (thumbnail) của video thành file .jpg cạnh video")
        self.desc_chk = QCheckBox("Mô tả (.txt)")
        self.desc_chk.setToolTip("Ghi tiêu đề, kênh, ngày đăng, link và mô tả của video ra file .txt cạnh video")
        self.open_after_chk = QCheckBox("Mở thư mục khi xong")
        for c, val in ((self.thumb_chk, self.opts.thumb), (self.desc_chk, self.opts.desc),
                       (self.open_after_chk, self.opts.open_after)):
            c.setChecked(val)
            v.addWidget(c)

        v.addSpacing(theme.SP['sm'])
        self.opts_btn = QPushButton("Nâng cao")
        theme.tag(self.opts_btn, variant="ghost")
        self.opts_btn.setCheckable(True)
        self.opts_btn.setIcon(icons.icon("sliders", 14))
        self.opts_btn.setToolTip("Phụ đề, tên file, thư mục con, tải cùng lúc, giới hạn tốc độ…")
        self.opts_btn.toggled.connect(self._toggle_opts)
        v.addWidget(self.opts_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.opts_panel = self._build_opts()
        v.addWidget(self.opts_panel)
        v.addStretch(1)
        self.tool_label = w.muted("")
        v.addWidget(self.tool_label)

        for name, sb in (("fmt", self.fmt_box), ("quality", self.quality_box), ("audio_q", self.audio_box)):
            sb.currentIndexChanged.connect(lambda _i, n=name, b=sb: self._set_opt(n, b.currentData()))
        for name, c in (("h264", self.h264_chk), ("thumb", self.thumb_chk), ("desc", self.desc_chk),
                        ("open_after", self.open_after_chk)):
            c.toggled.connect(lambda on, n=name: self._set_opt(n, bool(on)))
        return card

    def _build_opts(self) -> QWidget:
        box = QWidget()
        f = QFormLayout(box)
        f.setContentsMargins(0, 4, 0, 0)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)  # nhãn nằm trên ô: cột hẹp vẫn đủ chỗ
        self.subs_box = combo(downloader.SUBS_LABELS, self.opts.subs)
        self.subs_box.setToolTip("Phụ đề tiếng Việt / tiếng Anh (kể cả phụ đề tự tạo) nếu video có")
        self.name_box = combo(downloader.NAME_LABELS, self.opts.name)
        self.name_box.setToolTip("Cuối tên luôn có [mã video] để app nhận ra video đã tải, không tải trùng. "
                                 "\"Số thứ tự\" dùng cho video trong danh sách phát / kênh.")
        self.subdir_box = combo(downloader.SUBDIR_LABELS, self.opts.subdir)
        self.conc_box = combo([(n, f"{n} video") for n in downloader.CONCURRENT], self.opts.concurrent)
        self.rate_box = combo(downloader.RATE_LABELS, self.opts.rate)
        self.rate_box.setToolTip("Giới hạn tốc độ mỗi video — để mạng văn phòng không bị nghẽn")
        self.page_box = combo([(n, f"{n} video") for n in downloader.PAGE_SIZES], self.opts.page)
        self.page_box.setToolTip("Link kênh / danh sách phát: mỗi lần đọc (và mỗi lần Hiện thêm) lấy bao nhiêu video")
        self.max_box = combo(downloader.MAX_MIN_LABELS, self.opts.max_minutes)
        for cb in (self.subs_box, self.name_box, self.subdir_box, self.max_box, self.login_box):
            cb.setMinimumContentsLength(6)
        self.max_box.setToolTip("Khi đọc kênh / danh sách phát: video dài hơn mức này được bỏ tick sẵn "
                                "(vẫn tick lại được)")
        self.embed_chk = QCheckBox("Ghi thông tin")
        self.embed_chk.setMinimumWidth(0)
        self.embed_chk.setToolTip("Ghi tiêu đề, kênh, mô tả và ảnh bìa vào trong file video / nhạc")
        self.embed_chk.setChecked(self.opts.embed)
        self.extra_edit = QLineEdit(self.opts.extra)
        self.extra_edit.setPlaceholderText("vd --no-mtime")
        self.extra_edit.setToolTip("Tham số thêm cho yt-dlp (cho người rành), nối vào cuối lệnh. "
                                   "Gõ sai có thể làm tải lỗi — để trống nếu không chắc.")
        self.reset_opts_btn = QPushButton("Về mặc định")
        theme.tag(self.reset_opts_btn, variant="ghost")
        self.reset_opts_btn.clicked.connect(self.reset_opts)
        for label, wid in (("Phụ đề", self.subs_box), ("Tên file", self.name_box), ("Thư mục con", self.subdir_box),
                           ("Tải cùng lúc", self.conc_box), ("Giới hạn tốc độ", self.rate_box),
                           ("Mỗi lần đọc kênh", self.page_box), ("Bỏ tick video dài hơn", self.max_box)):
            f.addRow(label, wid)
        f.addRow(self.embed_chk)
        f.addRow("Tham số thêm", self.extra_edit)
        f.addRow(self.reset_opts_btn)
        for name, cb in (("subs", self.subs_box), ("name", self.name_box), ("subdir", self.subdir_box),
                         ("concurrent", self.conc_box), ("rate", self.rate_box), ("page", self.page_box),
                         ("max_minutes", self.max_box)):
            cb.currentIndexChanged.connect(lambda _i, n=name, b=cb: self._set_opt(n, b.currentData()))
        self.embed_chk.toggled.connect(lambda on: self._set_opt("embed", bool(on)))
        self.extra_edit.editingFinished.connect(lambda: self._set_opt("extra", self.extra_edit.text().strip()))
        return box

    # ---------- Tuỳ chỉnh ----------
    def _set_opt(self, name: str, value) -> None:
        if getattr(self, "_syncing", False) or value is None:
            return
        setattr(self.opts, name, value)
        self.opts.to_settings(self.settings)
        self._sync_opts_widgets()
        if name == "concurrent" and self._busy:
            self._fill()

    def _sync_opts_widgets(self) -> None:
        self._syncing = True
        try:
            for box, val in ((self.fmt_box, self.opts.fmt), (self.quality_box, self.opts.quality),
                             (self.audio_box, self.opts.audio_q),
                             (self.subs_box, self.opts.subs), (self.name_box, self.opts.name),
                             (self.subdir_box, self.opts.subdir), (self.conc_box, self.opts.concurrent),
                             (self.rate_box, self.opts.rate), (self.page_box, self.opts.page),
                             (self.max_box, self.opts.max_minutes)):
                i = box.findData(val)
                if i >= 0 and box.currentIndex() != i:
                    box.setCurrentIndex(i)
            for c, val in ((self.embed_chk, self.opts.embed), (self.h264_chk, self.opts.h264),
                           (self.thumb_chk, self.opts.thumb), (self.desc_chk, self.opts.desc),
                           (self.open_after_chk, self.opts.open_after)):
                c.setChecked(val)
            if self.extra_edit.text() != self.opts.extra:
                self.extra_edit.setText(self.opts.extra)
        finally:
            self._syncing = False
        video = self.opts.fmt in ("mp4", "mkv")
        self.quality_box.setVisible(video)
        self.quality_box.setEnabled(video)
        self.audio_box.setVisible(self.opts.fmt == "mp3")
        self.h264_chk.setVisible(self.opts.fmt == "mp4")
        self.opts_summary.setText(downloader.summary(self.opts))

    def reset_opts(self) -> None:
        self.opts = Options()
        self.opts.to_settings(self.settings)
        self._sync_opts_widgets()

    def _toggle_opts(self, on: bool) -> None:
        self.opts_panel.setVisible(on)
        self.settings.setValue("download/opts_open", bool(on))

    def _login_changed(self, i: int) -> None:
        key = self.login_box.itemData(i)
        if key == "file":
            start = str(self.settings.value("download/cookies_file", "") or "")
            path, _ = QFileDialog.getOpenFileName(self, "Chọn file đăng nhập (cookies.txt)", start,
                                                  "cookies.txt (*.txt);;Tất cả (*.*)")
            if not path:
                self.login_box.blockSignals(True)
                self.login_box.setCurrentIndex(self._login_prev)
                self.login_box.blockSignals(False)
                return
            self.settings.setValue("download/cookies_file", path)
        self._login_prev = i
        self.settings.setValue("download/login", key)

    def login(self) -> tuple[str, str]:
        return str(self.login_box.currentData() or ""), str(self.settings.value("download/cookies_file", "") or "")

    # ---------- thư mục ----------
    def folder(self) -> str:
        return str(self.settings.value("download/folder", "") or default_folder())

    def pick_folder(self) -> bool:
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video tải về", self.folder())
        if not d:
            return False
        self.settings.setValue("download/folder", d)
        self.folder_label.setText(d)
        self.folder_label.setToolTip(d)
        return True

    def open_folder(self) -> None:
        if ffmpeg_tools.usable_dir(self.folder()):
            w.open_with_default_app(self.folder())

    # ---------- công cụ ----------
    def _exe(self) -> list[str]:
        return self._exe_override or [str(dl_tools.ytdlp_path())]

    def ready(self) -> bool:
        return not self._tool_broken and (bool(self._exe_override) or dl_tools.installed())

    def _refresh_ready(self) -> None:
        ok = self.ready()
        self.install_card.setVisible(not ok)
        self.install_btn.setText("Cài lại công cụ tải" if self._tool_broken else "Cài công cụ tải")
        self.read_btn.setEnabled(ok and not self._reading)
        self.start_btn.setEnabled(ok)

    def _update_tool_label(self, updated: str = "") -> None:
        v = dl_tools.versions().get("yt-dlp", "")
        if updated:
            self.tool_label.setText(f"Đã cập nhật công cụ tải lên bản {updated}")
        else:
            self.tool_label.setText(f"Công cụ tải: yt-dlp {v}" if v else "")

    def shown(self) -> None:
        """Mỗi lần mở trang: công cụ còn không (diệt virus có thể xoá), đến hạn thì kiểm tra bản mới ở nền."""
        self._refresh_ready()
        self._update_tool_label()
        if self.ready() and not self._exe_override and updater.enabled() and \
                (dl_tools.due("yt-dlp", date.today()) or dl_tools.due("deno", date.today())):
            self._check_update(force=False)

    def _check_update(self, force: bool) -> None:
        def run() -> None:
            self.b.updated.emit(dl_tools.update_if_newer(self.is_busy, date.today(), force=force))
        threading.Thread(target=run, daemon=True).start()

    def _on_updated(self, done: list) -> None:
        if done:
            ver = done[0].split(" ", 1)[-1]
            self._update_tool_label(ver)
            if self._want_update:
                self.notice.emit(f"Đã cập nhật công cụ tải lên bản {ver} — bấm chuột phải › Thử lại ở video lỗi",
                                 "info")
        self._want_update = False

    def install_tools(self) -> None:
        self._install_cancel = threading.Event()
        cancel = self._install_cancel
        self.install_btn.setEnabled(False)
        self.install_bar.setRange(0, 0)
        self.install_bar.show()
        self.install_cancel_btn.show()
        self.install_msg.setText("Đang tải công cụ…")

        def run() -> None:
            try:
                rels = [dl_tools.fetch_release("yt-dlp"), dl_tools.fetch_release("deno")]
                dl_tools.install(rels, lambda d, t: self.b.install_progress.emit(d, t), cancel)
                self.b.installed.emit("")
            except updater.CancelledError:
                self.b.installed.emit("Đã huỷ.")
            except Exception as e:  # noqa: BLE001
                self.b.installed.emit(f"Không cài được: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _on_install_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.install_bar.setRange(0, 1000)
            self.install_bar.setValue(int(done * 1000 / total))
            self.install_msg.setText(f"Đang tải công cụ… {done / (1 << 20):.0f} / {total / (1 << 20):.0f} MB")

    def _on_installed(self, err: str) -> None:
        self.install_btn.setEnabled(True)
        self.install_bar.hide()
        self.install_cancel_btn.hide()
        self.install_msg.setText(err)
        if not err:
            self._tool_broken = False
            self.notice.emit("Đã cài công cụ tải — dán link để bắt đầu", "ok")
        self._refresh_ready()
        self._update_tool_label()

    # ---------- đọc link ----------
    def _paste(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text:
            cur = self.links_edit.toPlainText()
            self.links_edit.setPlainText((cur.rstrip("\n") + "\n" if cur.strip() else "") + text)
            self.links_edit.setFocus()

    def read_links(self) -> None:
        text = self.links_edit.toPlainText()
        links = downloader.split_links(text)
        bad = downloader.count_non_links(text)
        self._skip_note = f"Bỏ qua {bad} dòng không phải link." if bad else ""
        self.info_label.setText(self._skip_note)
        if not links or not self.ready() or self._reading:
            return
        self.links_edit.clear()
        self._read(links)

    def _read(self, links: list[str]) -> None:
        self._reading = True
        self.read_btn.setEnabled(False)
        self._read_total, self._read_count = len(links), 0
        self._show_reading()
        login, cookies = self.login()
        exe, deno, page = self._exe(), str(dl_tools.deno_path()), self.opts.page

        def run() -> None:
            for link in links:
                try:
                    data = downloader.read_info(exe, downloader.info_args(link, 1, page, login, cookies, deno))
                    tab = downloader.channel_tab_url(data)
                    src = link
                    if tab:
                        src = tab
                        data = downloader.read_info(exe, downloader.info_args(tab, 1, page, login, cookies, deno))
                    self.b.info.emit(link, downloader.parse_info(data, src), "")
                except downloader.DownloadError as e:
                    self.b.info.emit(link, None, e.friendly + "\n" + e.stderr)
                    if e.friendly == downloader.TOOL_BLOCKED:
                        break
                except Exception as e:  # noqa: BLE001
                    self.b.info.emit(link, None, f"Lỗi tải (rê chuột vào ⓘ xem chi tiết)\n{e}")
            self.b.read_done.emit()
        threading.Thread(target=run, daemon=True).start()

    def _show_reading(self) -> None:
        on = self._reading
        self.read_btn.setText("Đang đọc…" if on else "Đọc link")
        if on:
            self.read_spinner.start()
            self.big_spinner.start()
            n = f" {self._read_count + 1}/{self._read_total}" if self._read_total > 1 else ""
            self.info_label.setText(f"Đang đọc{n} link…")
            self.loading_label.setText(f"Đang đọc{n} link…")
        else:
            self.read_spinner.stop()
            self.big_spinner.stop()
        self._update_counts()

    def _on_info(self, link: str, res, err: str) -> None:
        self._read_count += 1
        if self._reading and self._read_count < self._read_total:
            self._show_reading()
        if isinstance(res, downloader.Group):
            if res.url in self.queue.groups:
                return
            self.queue.add_group(res, self.opts.page, self.opts.max_minutes * 60)
            for e in self.queue.entries:
                if e.group == res.url:
                    self._add_row(e)
        elif isinstance(res, downloader.Item):
            e = self.queue.add_item(res)
            if e is not None:
                self._add_row(e)
        else:
            friendly, _, detail = err.partition("\n")
            if friendly == downloader.TOOL_BLOCKED and not self._tool_broken:
                self._tool_broken = True
                self._refresh_ready()
            e = self.queue.add_unread(link, friendly)
            if e is None:
                return
            self._add_row(e, detail)
        self._changed()

    def _on_read_done(self) -> None:
        self._reading = False
        if self.info_label.text().startswith("Đang đọc"):
            self.info_label.setText(getattr(self, "_skip_note", ""))
        self._show_reading()
        self._refresh_ready()

    def show_more(self, group_url: str) -> None:
        gi = self.queue.groups.get(group_url)
        if gi is None or self._reading or not self.ready():
            return
        self._reading = True
        self.read_btn.setEnabled(False)
        login, cookies = self.login()
        exe, deno = self._exe(), str(dl_tools.deno_path())
        start, end = gi.loaded + 1, gi.loaded + self.opts.page
        self._read_total, self._read_count = 1, 0
        self._show_reading()

        def run() -> None:
            try:
                data = downloader.read_info(exe, downloader.info_args(group_url, start, end, login, cookies, deno))
                g = downloader.parse_info(data, group_url)
                self.b.more.emit(group_url, g.items if isinstance(g, downloader.Group) else [], "")
            except downloader.DownloadError as e:
                self.b.more.emit(group_url, None, e.friendly)
            except Exception as e:  # noqa: BLE001
                self.b.more.emit(group_url, None, str(e))
            self.b.read_done.emit()
        threading.Thread(target=run, daemon=True).start()

    def _on_more(self, group_url: str, items, err: str) -> None:
        if items is None:
            self.notice.emit(f"Không đọc thêm được: {err}", "warn")
            return
        for e in self.queue.extend_group(group_url, items, self.opts.page, self.opts.max_minutes * 60):
            self._add_row(e)
        self._refresh_group(group_url)
        self._changed()

    # ---------- danh sách ----------
    def _row(self, e: dq.Entry) -> QTreeWidgetItem | None:
        return self._rows.get(id(e))

    def _group_row(self, url: str) -> QTreeWidgetItem:
        row = self._group_rows.get(url)
        if row is None:
            row = QTreeWidgetItem()
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            row.setData(0, ROLE, ("group", url))
            row.setIcon(0, icons.icon("queue", 16))
            self._updating_tree = True
            self.tree.addTopLevelItem(row)
            row.setExpanded(True)
            self._updating_tree = False
            self._group_rows[url] = row
            self._refresh_group(url)
        return row

    def _refresh_group(self, url: str) -> None:
        row = self._group_rows.get(url)
        gi = self.queue.groups.get(url)
        if row is None or gi is None:
            return
        self._updating_tree = True
        n = f"{gi.count}" if gi.count else (f"{gi.loaded}+" if not gi.complete else f"{gi.loaded}")
        row.setText(0, f"{gi.title} — {n} video")
        more = next((row.child(i) for i in range(row.childCount()) if row.child(i).data(0, ROLE) == MORE), None)
        if not gi.complete:
            if more is None:
                more = QTreeWidgetItem([f"Hiện thêm {self.opts.page} video…"])
                more.setData(0, ROLE, MORE)
                more.setFlags(Qt.ItemFlag.ItemIsEnabled)
                more.setForeground(0, theme.qcolor("accent_text"))
                more.setToolTip(0, "Bấm đúp để đọc thêm (mục thêm vào chưa được tick)")
            else:
                row.removeChild(more)
            more.setText(0, f"Hiện thêm {self.opts.page} video…  (đã đọc {gi.loaded}"
                            + (f" / {gi.count})" if gi.count else ")"))
            row.addChild(more)
        elif more is not None:
            row.removeChild(more)
        self._updating_tree = False

    def _add_row(self, e: dq.Entry, detail: str = "") -> None:
        row = QTreeWidgetItem([e.title, e.platform, w.fmt_dur(e.duration) if e.duration else "—", ""])
        if not e.unread:
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        row.setData(0, ROLE, ("entry", id(e)))
        row.setToolTip(0, e.url)
        if detail:
            row.setToolTip(3, "\n".join(detail.strip().splitlines()[-6:]))
        self._rows[id(e)] = row
        self._updating_tree = True
        if e.group:
            parent = self._group_row(e.group)
            more = next((parent.child(i) for i in range(parent.childCount()) if parent.child(i).data(0, ROLE) == MORE),
                        None)
            if more is not None:
                parent.insertChild(parent.indexOfChild(more), row)
            else:
                parent.addChild(row)
        else:
            self.tree.addTopLevelItem(row)
        self._updating_tree = False
        self._paint(e)
        self._want_thumb(e)

    def _entry_of(self, row: QTreeWidgetItem) -> dq.Entry | None:
        d = row.data(0, ROLE)
        if isinstance(d, tuple) and d[0] == "entry":
            return next((e for e in self.queue.entries if id(e) == d[1]), None)
        return None

    def _paint(self, e: dq.Entry, extra: str = "") -> None:
        row = self._row(e)
        if row is None:
            return
        self._updating_tree = True
        if not e.unread:
            row.setCheckState(0, Qt.CheckState.Checked if e.checked else Qt.CheckState.Unchecked)
        sec = f" · {downloader.section_label(e.section)}" if e.section else ""
        tone = "text_2"
        if e.status == "pending":
            text = "Chờ" + sec
        elif e.status == "running":
            text = (extra or "Đang tải…") + sec
            tone = "accent_text"
        elif e.status == "done":
            text = "✓ Xong" + (f" · {e.codec}" if e.codec else "") + sec
            tone = "success_text"
        elif e.status == "exists":
            text = "✓ Đã có"
            tone = "success_text"
        else:
            text = "✕ " + (e.message or "Lỗi tải") + "  ⓘ"
            tone = "danger_text"
        row.setText(3, text)
        row.setForeground(3, theme.qcolor(tone))
        if e.status != "running":
            row.setData(3, PROG_ROLE, None)
        self._updating_tree = False

    def _on_item_changed(self, row: QTreeWidgetItem, col: int) -> None:
        if self._updating_tree or col != 0:
            return
        e = self._entry_of(row)
        if e is not None:
            e.checked = row.checkState(0) == Qt.CheckState.Checked
            self._changed()
        else:
            d = row.data(0, ROLE)
            if isinstance(d, tuple) and d[0] == "group":
                for i in range(row.childCount()):
                    ce = self._entry_of(row.child(i))
                    if ce is not None:
                        ce.checked = row.child(i).checkState(0) == Qt.CheckState.Checked
                self._changed()

    def _on_double(self, row: QTreeWidgetItem, _col: int) -> None:
        if row.data(0, ROLE) == MORE and row.parent() is not None:
            d = row.parent().data(0, ROLE)
            self.show_more(d[1])
            return
        e = self._entry_of(row)
        if e is not None and e.path and Path(e.path).is_file():
            w.reveal_in_explorer(e.path)

    def _menu(self, pos) -> None:
        row = self.tree.itemAt(pos)
        if row is None:
            return
        m = QMenu(self)
        e = self._entry_of(row)
        d = row.data(0, ROLE)
        if e is not None:
            if e.status == "error":
                sel = [x for x in (self._entry_of(r) for r in self.tree.selectedItems()) if x is not None]
                targets = [x for x in sel if x.status == "error"] if e in sel else [e]
                m.addAction("Thử lại" + (f" ({len(targets)} video)" if len(targets) > 1 else ""),
                            lambda: self.retry(targets))
            if e.status in ("pending", "error"):
                m.addAction("Chỉ tải đoạn…", lambda: self._ask_section(e))
                if e.section:
                    m.addAction("Bỏ đoạn (tải cả video)", lambda: self.set_section(e, "", ""))
            if e.path and Path(e.path).exists():
                m.addAction("Mở thư mục chứa file", lambda: w.reveal_in_explorer(e.path))
            m.addAction("Chép link", lambda: QGuiApplication.clipboard().setText(e.url))
            if e.status != "running":
                m.addAction("Bỏ khỏi danh sách", lambda: self._remove([e]))
        elif isinstance(d, tuple) and d[0] == "group":
            url = d[1]
            m.addAction("Bỏ cả nhóm khỏi danh sách",
                        lambda: self._remove([x for x in self.queue.entries if x.group == url and x.status != "running"]))
        if not m.isEmpty():
            m.exec(self.tree.viewport().mapToGlobal(pos))

    def retry(self, entries: list[dq.Entry]) -> None:
        """Thử lại: dòng tải lỗi → Chờ; dòng đọc-link-lỗi → bỏ dòng và đọc lại link."""
        relink = [e.url for e in entries if e.unread]
        self._remove([e for e in entries if e.unread])
        for e in entries:
            if not e.unread and e.status == "error":
                self.queue.retry(e)
                self._paint(e)
        self._changed()
        if relink:
            self._tool_broken = False if self._exe_override else self._tool_broken
            self._read(relink)

    def retry_errors(self) -> None:
        self.retry([e for e in self.queue.entries if e.status == "error"])

    def _remove(self, entries: list[dq.Entry]) -> None:
        for e in entries:
            row = self._rows.pop(id(e), None)
            if row is not None:
                (row.parent().removeChild(row) if row.parent() else
                 self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(row)))
            group = e.group
            self.queue.remove(e)
            if group and group not in self.queue.groups:
                g = self._group_rows.pop(group, None)
                if g is not None:
                    self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(g))
        self._changed()

    def clear_list(self) -> None:
        if self._busy:
            self.notice.emit("Đang tải — bấm Dừng trước khi xoá danh sách", "warn")
            return
        self.queue.clear()
        self._rows.clear()
        self._group_rows.clear()
        self.tree.clear()
        self._changed()

    def _ask_section(self, e: dq.Entry) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Chỉ tải đoạn")
        f = QFormLayout(dlg)
        a, b = QLineEdit(), QLineEdit()
        a.setPlaceholderText("vd 1:00")
        b.setPlaceholderText("vd 2:30")
        if e.section:
            s0, s1 = (int(x) for x in e.section.split("-"))
            a.setText(downloader.fmt_time(s0))
            b.setText(downloader.fmt_time(s1))
        f.addRow("Từ", a)
        f.addRow("Đến", b)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.set_section(e, a.text(), b.text())
            except ValueError as err:
                self.notice.emit(str(err), "warn")
        w.dispose(dlg)

    def set_section(self, e: dq.Entry, text_from: str, text_to: str) -> None:
        """Chỉ tải đoạn Từ–Đến (mm:ss / hh:mm:ss); cả hai trống = tải cả video. Sai → ValueError."""
        e.section = "" if not text_from.strip() and not text_to.strip() else \
            downloader.parse_section(text_from, text_to)
        self._paint(e)
        self._changed()

    # ---------- ảnh nhỏ ----------
    def _want_thumb(self, e: dq.Entry) -> None:
        url = e.thumbnail
        if not url or not url.lower().startswith("https://") or not updater.enabled():
            return
        path = ffmpeg_tools.cache_dir("dlthumbs") / (hashlib.sha1(url.encode()).hexdigest() + ".img")
        if path.is_file():
            self._on_thumb(url, str(path))
            return
        if url in self._thumbs_wanted:
            return
        self._thumbs_wanted.add(url)

        def run() -> None:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "KTLoopStation"})
                with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 — chỉ https
                    data = r.read(2 << 20)
                path.write_bytes(data)
                self.b.thumb.emit(url, str(path))
            except Exception:  # noqa: BLE001 — không có ảnh nhỏ thì thôi
                pass
        threading.Thread(target=run, daemon=True).start()

    def _on_thumb(self, url: str, path: str) -> None:
        pm = QPixmap(path)
        if pm.isNull():
            return
        icon = QIcon(pm.scaled(self.tree.iconSize(), Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
        for e in self.queue.entries:
            if e.thumbnail == url and self._row(e) is not None:
                self._row(e).setIcon(0, icon)

    # ---------- tải ----------
    def is_busy(self) -> bool:
        return self._busy

    def remaining(self) -> int:
        return self.queue.remaining()

    def _set_busy(self, on: bool) -> None:
        if on == self._busy:
            return
        self._busy = on
        theme.tag(self.start_btn, variant="danger" if on else "primary")
        self.start_btn.setIcon(icons.icon("stop" if on else "download", 16, "danger_text" if on else "white"))
        if on:
            self.run_bar.setValue(0)
            self.run_bar.show()
            self._anim.start()
        else:
            self._anim.stop()
            self._fracs.clear()
            self.run_bar.hide()
        self._update_counts()
        self.busyChanged.emit(on)

    def set_encoders(self, available: dict) -> None:
        """Cửa sổ chính dò xong card đồ hoạ: chuyển sang H.264 bằng NVENC / QSV / AMF nếu có."""
        from ..core import encoders
        self._h264_enc = encoders.pick("h264", "auto", available)

    def _update_counts(self) -> None:
        """Nút Tải ghi rõ số video đã chọn; danh sách trống → hướng dẫn 3 bước."""
        n = self.queue.remaining()
        if self._busy:
            self.start_btn.setText("Dừng")
        else:
            self.start_btn.setText(f"Tải {n} video" if n else "Tải video")
        has = bool(self.queue.entries)
        self.selected_label.setText((f"Đã chọn {n} video" if n else "Chưa chọn video nào") if has else "")
        self.list_stack.setCurrentWidget(self.tree if has else (self.loading_view if self._reading
                                                                  else self.empty_view))
        self._update_run_bar()

    def _update_run_bar(self) -> None:
        """Thanh tổng: (video đã xong trong lượt + phần đã tải của video đang tải) / tổng video của lượt."""
        if not self._busy:
            return
        total = self._run_done + self.queue.remaining()
        if total <= 0:
            return
        val = int(1000 * (self._run_done + sum(max(0.0, f) for f in self._fracs.values())) / total)
        if abs(val - self.run_bar.value()) >= 3:
            self._run_anim.stop()
            self._run_anim.setStartValue(self.run_bar.value())
            self._run_anim.setEndValue(max(0, min(1000, val)))
            self._run_anim.start()

    def start(self) -> None:
        if self._busy or not self.ready():
            return
        if self.queue.next_pending() is None:
            self.notice.emit("Chưa có video nào được tick để tải", "info")
            return
        if not ffmpeg_tools.usable_dir(self.folder()):
            self.notice.emit("Thư mục lưu không ghi được — chọn thư mục khác", "warn")
            if not self.pick_folder() or not ffmpeg_tools.usable_dir(self.folder()):
                return
        self._stopping = False
        self._run_done = 0
        self._set_busy(True)
        self._fill()

    def stop(self) -> None:
        if not self._busy:
            return
        self._stopping = True
        for ev in self._cancels.values():
            ev.set()
        if not self._cancels:
            self._finish_run()

    def _fill(self) -> None:
        if self._stopping:
            return
        folder = self.folder()
        while len(self._cancels) < self.opts.concurrent:
            e = self.queue.next_pending()
            if e is None:
                break
            found = downloader.find_existing(folder, e.vid, self.opts.fmt) if not e.section else None
            if found is not None:
                e.status, e.checked, e.path = "exists", False, str(found)
                self._paint(e)
                self._changed()
                continue
            self._launch(e, folder)
        if not self._cancels:
            self._finish_run()

    def _launch(self, e: dq.Entry, folder: str) -> None:
        e.status, e.message = "running", ""
        self._paint(e)
        row = self._row(e)
        if row is not None:
            row.setData(3, PROG_ROLE, -1.0)  # đang bắt đầu: khúc sáng chạy qua lại
        self._changed()
        cancel = threading.Event()
        self._cancels[id(e)] = cancel
        login, cookies = self.login()
        try:
            ff = ffmpeg_tools.ffmpeg()
        except FileNotFoundError:
            ff = "ffmpeg"
        opts = Options(**vars(self.opts))
        args = downloader.download_args(e.url, folder, opts, login, cookies, ff,
                                        str(dl_tools.deno_path()), e.section, e.index)
        exe, enc = self._exe(), self._h264_enc

        def run() -> None:
            try:
                res = downloader.run_download(exe, args, lambda p: self.b.progress.emit(e, p),
                                              lambda s: self.b.stage.emit(e, s), cancel, login, e.vid)
                if opts.desc and res.meta:
                    try:
                        downloader.write_meta_txt(res.path, res.meta)
                    except OSError:
                        pass
                if downloader.needs_h264(opts, res.codec):  # trang chỉ có H.265 / AV1 / VP9 → chuyển sang H.264
                    self.b.stage.emit(e, "Đang chuyển sang H.264…")
                    try:
                        res.path = downloader.convert_to_h264(
                            res.path, enc, cancel,
                            lambda f: self.b.stage.emit(e, f"Đang chuyển sang H.264… {int(f * 100)}%"))
                        res.codec = ""
                    except downloader.CancelledError:
                        raise
                    except Exception:  # noqa: BLE001 — chuyển không được: giữ bản gốc, cột trạng thái ghi codec
                        pass
                self.b.finished.emit(e, res, "", "")
            except downloader.CancelledError:
                self.b.finished.emit(e, None, CANCELLED, "")
            except downloader.DownloadError as err:
                self.b.finished.emit(e, None, err.friendly, err.stderr)
            except Exception as err:  # noqa: BLE001
                self.b.finished.emit(e, None, "Lỗi tải (rê chuột vào ⓘ xem chi tiết)", str(err))
        threading.Thread(target=run, daemon=True).start()

    def _on_progress(self, e: dq.Entry, p) -> None:
        if e.status != "running":
            return
        pct = f"{p.done * 100 // p.total}%" if p.total else f"{p.done / (1 << 20):.0f} MB"
        sp = fmt_speed(p.speed)
        self._paint(e, pct + (f" · {sp}" if sp else ""))
        row = self._row(e)
        frac = (p.done / p.total) if p.total else -1.0
        self._fracs[id(e)] = max(0.0, frac)
        if row is not None:
            row.setData(3, PROG_ROLE, frac)
        self._update_run_bar()

    def _on_stage(self, e: dq.Entry, text: str) -> None:
        if e.status == "running":
            self._paint(e, text)
            m = re.search(r"(\d+)%", text)
            row = self._row(e)
            if row is not None:
                row.setData(3, PROG_ROLE, int(m.group(1)) / 100 if m else -1.0)

    def _on_finished(self, e: dq.Entry, res, friendly: str, stderr: str) -> None:
        self._cancels.pop(id(e), None)
        self._fracs.pop(id(e), None)
        if friendly == CANCELLED:
            e.status = "pending"
        elif res is not None:
            e.status, e.path, e.codec = "done", res.path, res.codec
            self._run_done += 1
            self._flash(e)
        else:
            e.status, e.message = "error", friendly
            row = self._row(e)
            if row is not None:
                row.setToolTip(3, "\n".join(stderr.strip().splitlines()[-6:]) or friendly)
            if friendly in (downloader.TOOL_BLOCKED, downloader.NETWORK_ERROR) and not self._stopping:
                self._halt = friendly  # không chạy tiếp: các video sau sẽ lỗi y hệt
                self._stopping = True
            if friendly == downloader.TOOL_BLOCKED:
                self._tool_broken = True
                self._refresh_ready()
            if downloader.is_blocked_error(stderr) and dl_tools.due("yt-dlp", date.today()):
                self._want_update = True
        if e in self.queue.entries:
            self._paint(e)
        self._changed()
        if self._stopping:
            if not self._cancels:
                self._finish_run()
        else:
            self._fill()

    def _flash(self, e: dq.Entry) -> None:
        """Dòng vừa tải xong loé xanh rồi nhạt dần (~0,9 giây)."""
        row = self._row(e)
        self.flashed.append(e.vid)
        if row is None:
            return
        anim = QVariantAnimation(self)
        anim.setDuration(900)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)

        def step(v) -> None:
            if self._row(e) is not row:
                return
            brush = QBrush(theme.qcolor("success_text", int(70 * float(v)))) if float(v) > 0.02 else QBrush()
            for c in range(self.tree.columnCount()):
                row.setBackground(c, brush)
        anim.valueChanged.connect(step)
        anim.finished.connect(lambda: (step(0.0), self._flash_anims.pop(id(e), None)))
        self._flash_anims[id(e)] = anim
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _finish_run(self) -> None:
        self.queue.stop_all()
        for e in self.queue.entries:
            if e.status == "pending":
                self._paint(e)
        was = self._busy
        stopped = self._stopping
        halt, self._halt = self._halt, ""
        self._stopping = False
        self._set_busy(False)
        self._refresh_ready()
        self._changed()
        if halt:
            self.notice.emit(halt if halt != downloader.TOOL_BLOCKED else
                             "Công cụ tải bị chặn hoặc hỏng — bấm Cài lại công cụ tải", "warn")
        elif was and not stopped:
            bad = sum(1 for e in self.queue.entries if e.status == "error" and e.checked)
            self.notice.emit(f"Tải xong: {self._run_done} video" + (f", {bad} lỗi" if bad else ""),
                             "warn" if bad else "ok")
            if self.opts.open_after and self._run_done:
                w.open_with_default_app(self.folder())
        if self._want_update and not self._exe_override:
            self._check_update(force=True)

    # ---------- lưu ----------
    def _queue_path(self) -> Path:
        return ffmpeg_tools.data_dir() / dq.QUEUE_FILE

    def save(self) -> None:
        try:
            self.queue.save(self._queue_path())
        except OSError:
            pass

    def _changed(self) -> None:
        self.counterChanged.emit(self.queue.counter_text())
        self._update_counts()
        self.save()

    def adapt(self, width: int, height: int = 0) -> None:
        """Rộng: Cài đặt tải là cột bên phải. Hẹp: xếp xuống dưới danh sách, ẩn cột Thời lượng."""
        narrow = width < theme.px(900)
        if narrow:
            self.body.setDirection(QBoxLayout.Direction.TopToBottom)
            self.side_scroll.setMinimumWidth(0)
            self.side_scroll.setMaximumWidth(16777215)
            self.side_scroll.setMinimumHeight(self.side_card.sizeHint().height())
        else:
            self.body.setDirection(QBoxLayout.Direction.LeftToRight)
            self.side_scroll.setMinimumHeight(0)
            self.side_scroll.setFixedWidth(theme.px(345))
        self.tree.setColumnHidden(2, width < theme.px(760))
