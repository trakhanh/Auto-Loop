"""Trang "Tải video": dán link (lẻ / danh sách phát / kênh) → xem trước → tải MP4 / MP3 về thư mục bằng yt-dlp.

Xem docs/superpowers/specs/2026-11-20-tai-video-design.md. Công cụ (yt-dlp + Deno) cài khi dùng lần đầu, tự cập
nhật; file tải về chỉ nằm trong thư mục lưu — không tự đưa vào bảng clip / playlist / dự án."""
from __future__ import annotations

import hashlib
import threading
import urllib.request
from datetime import date
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QSize, QStandardPaths, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPlainTextEdit, QProgressBar, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core import dl_tools, downloader, ffmpeg_tools, updater
from ..core import download_queue as dq
from ..core.downloader import Options
from . import icons, theme
from . import widgets as w

ROLE = Qt.ItemDataRole.UserRole
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
        for e in self.queue.entries:
            self._add_row(e)
        self._refresh_ready()
        self._update_tool_label()

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

        top = QHBoxLayout()
        self.links_edit = QPlainTextEdit()
        self.links_edit.setPlaceholderText("Dán một hoặc nhiều link (mỗi dòng một link): YouTube, TikTok, Bilibili, "
                                           "X, Facebook, Instagram… — link danh sách phát / kênh cũng được")
        self.links_edit.setFixedHeight(theme.px(78))
        self.read_btn = QPushButton("Đọc link")
        theme.tag(self.read_btn, variant="tonal")
        self.read_btn.setIcon(icons.icon("search", 15, "accent_text"))
        self.read_btn.setToolTip("Lấy tên, ảnh nhỏ, thời lượng để xem trước — chưa tải gì")
        self.read_btn.clicked.connect(self.read_links)
        top.addWidget(self.links_edit, 1)
        top.addWidget(self.read_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)
        self.info_label = w.muted("")
        lay.addWidget(self.info_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Video", "Nền tảng", "Thời lượng", "Trạng thái"])
        self.tree.setRootIsDecorated(True)
        self.tree.setIconSize(QSize(theme.px(64), theme.px(36)))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double)
        hd = self.tree.header()
        hd.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            hd.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.tree, 1)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Lưu vào:"))
        self.folder_label = w.ElidedLabel("")
        self.folder_label.setMinimumWidth(theme.px(120))
        bar.addWidget(self.folder_label, 1)
        self.folder_btn = QPushButton("Đổi")
        theme.tag(self.folder_btn, variant="ghost")
        self.folder_btn.clicked.connect(self.pick_folder)
        bar.addWidget(self.folder_btn)
        bar.addWidget(w.hairline())
        self.quality_box = combo(downloader.QUALITY_LABELS, self.opts.quality)
        self.quality_box.setToolTip("Cao nhất (2K/4K) của YouTube là VP9 / AV1 — Premiere cũ, CapCut có thể không mở "
                                    "được. 1080p luôn là H.264, mở được mọi phần mềm dựng.")
        self.quality_box.currentIndexChanged.connect(lambda _i: self._set_opt("quality", self.quality_box.currentData()))
        bar.addWidget(self.quality_box)
        self.login_box = combo(downloader.LOGINS, str(self.settings.value("download/login", "") or ""))
        self.login_box.setToolTip("Dùng đăng nhập từ trình duyệt cho trang bắt đăng nhập (Facebook, Instagram…). "
                                  "Firefox chắc chắn nhất; Chrome / Edge hay bị Windows chặn — khi đó dùng file "
                                  "đăng nhập (cookies.txt).")
        self._login_prev = self.login_box.currentIndex()
        self.login_box.currentIndexChanged.connect(self._login_changed)
        bar.addWidget(QLabel("Đăng nhập:"))
        bar.addWidget(self.login_box)
        bar.addWidget(w.hairline())
        self.start_btn = QPushButton("Tải đã chọn")
        theme.tag(self.start_btn, variant="primary")
        self.start_btn.setIcon(icons.icon("download", 15, "white"))
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
        bar.addWidget(self.start_btn)
        bar.addWidget(self.open_btn)
        bar.addWidget(self.more_btn)
        lay.addLayout(bar)

        orow = QHBoxLayout()
        self.opts_btn = QPushButton("Tuỳ chỉnh")
        theme.tag(self.opts_btn, variant="ghost")
        self.opts_btn.setCheckable(True)
        self.opts_btn.setIcon(icons.icon("sliders", 14))
        self.opts_btn.toggled.connect(self._toggle_opts)
        self.opts_summary = w.muted("")
        self.opts_summary.setWordWrap(False)
        orow.addWidget(self.opts_btn)
        orow.addWidget(self.opts_summary, 1)
        lay.addLayout(orow)
        self.opts_panel = self._build_opts()
        lay.addWidget(self.opts_panel)
        self.tool_label = w.muted("")
        lay.addWidget(self.tool_label)

        open_ = str(self.settings.value("download/opts_open", "false")).lower() in ("true", "1")
        self.opts_panel.setVisible(open_)
        self.opts_btn.setChecked(open_)
        self._sync_opts_widgets()
        self.folder_label.setText(self.folder())
        self.folder_label.setToolTip(self.folder())
        sc = QShortcut(QKeySequence(QKeySequence.StandardKey.Paste), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(self._paste)

    def _build_opts(self) -> QWidget:
        box = QGroupBox()
        g = QGridLayout(box)
        g.setContentsMargins(14, 12, 14, 12)
        g.setHorizontalSpacing(theme.px(14))
        self.fmt_box = combo(downloader.FORMAT_LABELS, self.opts.fmt)
        self.subs_box = combo(downloader.SUBS_LABELS, self.opts.subs)
        self.subs_box.setToolTip("Phụ đề tiếng Việt / tiếng Anh (kể cả phụ đề tự tạo) nếu video có")
        self.name_box = combo(downloader.NAME_LABELS, self.opts.name)
        self.name_box.setToolTip("Cuối tên luôn có [mã video] để app nhận ra video đã tải, không tải trùng")
        self.subdir_box = combo(downloader.SUBDIR_LABELS, self.opts.subdir)
        self.conc_box = combo([(n, f"{n} video") for n in downloader.CONCURRENT], self.opts.concurrent)
        self.rate_box = combo(downloader.RATE_LABELS, self.opts.rate)
        self.rate_box.setToolTip("Giới hạn tốc độ mỗi video — để mạng văn phòng không bị nghẽn")
        self.page_box = combo([(n, f"{n} video") for n in downloader.PAGE_SIZES], self.opts.page)
        self.page_box.setToolTip("Link kênh / danh sách phát: mỗi lần đọc (và mỗi lần Hiện thêm) lấy bao nhiêu video")
        self.embed_chk = QCheckBox("Ghi tiêu đề, kênh, ảnh bìa vào file")
        self.embed_chk.setChecked(self.opts.embed)
        self.extra_edit = QLineEdit(self.opts.extra)
        self.extra_edit.setPlaceholderText('Tham số thêm cho yt-dlp (cho người rành) — vd --match-filter "duration < 600"')
        self.extra_edit.setToolTip("Nối vào cuối lệnh yt-dlp. Gõ sai có thể làm tải lỗi — để trống nếu không chắc.")
        self.reset_opts_btn = QPushButton("Về mặc định")
        theme.tag(self.reset_opts_btn, variant="ghost")
        self.reset_opts_btn.clicked.connect(self.reset_opts)
        cells = (("Định dạng", self.fmt_box), ("Phụ đề", self.subs_box), ("Tên file", self.name_box),
                 ("Thư mục con", self.subdir_box), ("Tải cùng lúc", self.conc_box), ("Giới hạn tốc độ", self.rate_box),
                 ("Mỗi lần đọc kênh", self.page_box))
        for i, (label, wid) in enumerate(cells):
            r, c = divmod(i, 4)
            g.addWidget(QLabel(label), r * 2, c)
            g.addWidget(wid, r * 2 + 1, c)
        g.addWidget(self.embed_chk, 3, 3)
        g.addWidget(self.extra_edit, 4, 0, 1, 3)
        g.addWidget(self.reset_opts_btn, 4, 3)
        for name, cb in (("fmt", self.fmt_box), ("subs", self.subs_box), ("name", self.name_box),
                          ("subdir", self.subdir_box), ("concurrent", self.conc_box), ("rate", self.rate_box),
                          ("page", self.page_box)):
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
                             (self.subs_box, self.opts.subs), (self.name_box, self.opts.name),
                             (self.subdir_box, self.opts.subdir), (self.conc_box, self.opts.concurrent),
                             (self.rate_box, self.opts.rate), (self.page_box, self.opts.page)):
                i = box.findData(val)
                if i >= 0 and box.currentIndex() != i:
                    box.setCurrentIndex(i)
            self.embed_chk.setChecked(self.opts.embed)
            if self.extra_edit.text() != self.opts.extra:
                self.extra_edit.setText(self.opts.extra)
        finally:
            self._syncing = False
        self.quality_box.setEnabled(self.opts.fmt == "mp4")
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
        self.info_label.setText(f"Bỏ qua {bad} dòng không phải link." if bad else "")
        if not links or not self.ready() or self._reading:
            return
        self.links_edit.clear()
        self._read(links)

    def _read(self, links: list[str]) -> None:
        self._reading = True
        self.read_btn.setEnabled(False)
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

    def _on_info(self, link: str, res, err: str) -> None:
        if isinstance(res, downloader.Group):
            if res.url in self.queue.groups:
                return
            self.queue.add_group(res, self.opts.page)
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
        for e in self.queue.extend_group(group_url, items, self.opts.page):
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
        self.start_btn.setText("Dừng" if on else "Tải đã chọn")
        theme.tag(self.start_btn, variant="danger" if on else "primary")
        self.start_btn.setIcon(icons.icon("stop" if on else "download", 15, "danger_text" if on else "white"))
        self.busyChanged.emit(on)

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
        self._changed()
        cancel = threading.Event()
        self._cancels[id(e)] = cancel
        login, cookies = self.login()
        try:
            ff = ffmpeg_tools.ffmpeg()
        except FileNotFoundError:
            ff = "ffmpeg"
        args = downloader.download_args(e.url, folder, Options(**vars(self.opts)), login, cookies, ff,
                                        str(dl_tools.deno_path()), e.section)
        exe = self._exe()

        def run() -> None:
            try:
                res = downloader.run_download(exe, args, lambda p: self.b.progress.emit(e, p),
                                              lambda s: self.b.stage.emit(e, s), cancel, login, e.vid)
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

    def _on_stage(self, e: dq.Entry, text: str) -> None:
        if e.status == "running":
            self._paint(e, text)

    def _on_finished(self, e: dq.Entry, res, friendly: str, stderr: str) -> None:
        self._cancels.pop(id(e), None)
        if friendly == CANCELLED:
            e.status = "pending"
        elif res is not None:
            e.status, e.path, e.codec = "done", res.path, res.codec
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
            done = sum(1 for e in self.queue.entries if e.status == "done")
            bad = sum(1 for e in self.queue.entries if e.status == "error" and e.checked)
            self.notice.emit(f"Tải xong: {done} video" + (f", {bad} lỗi" if bad else ""), "warn" if bad else "ok")
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
        self.save()

    def adapt(self, width: int, height: int = 0) -> None:
        """Hẹp: ẩn cột Thời lượng cho cột tên đủ chỗ."""
        self.tree.setColumnHidden(2, width < theme.px(760))
