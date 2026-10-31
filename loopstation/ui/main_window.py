"""Cửa sổ chính: thanh bên, tiêu đề + chỉ số, 3 trang, mở/lưu dự án, điều phối xuất."""
from __future__ import annotations

import copy
import html
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings, QSize, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QKeySequence, QShortcut
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QSizePolicy,
    QFrame, QScrollArea, QStackedWidget,
    QApplication, QButtonGroup, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..core import encoders, ffmpeg_tools, planner, power, probe, render, render_queue as rq, size_estimate, sysinfo, timeline
from ..core import updater
from ..core.ffmpeg_tools import CancelledError
from ..core.project import PROJECT_EXT, ClipItem, Project, is_sample_file
from ..core.render import RenderJob, clean_filename, default_output_name, output_path, strip_ext
from . import branding, effects, icons, motion, theme, widgets as w
from .export_tab import ExportTab
from .help_page import HelpPage
from .settings_page import SettingsPage
from .update_dialog import UpdateChecker, UpdateDialog, status_text as update_status_text
from .music_tab import MusicTab
from .theme import APP_NAME, APP_VERSION, AUTHOR, SETTINGS_ORG
from .video_tab import VideoTab
from .widgets import fmt_dur

AUTOSAVE = "autosave" + PROJECT_EXT
BACKUP_DIR = "ban-luu"  # 5 bản tự lưu gần nhất (khôi phục khi lỡ tay / app bị tắt ngang)
BACKUP_KEEP = 5
BACKUP_EVERY = 120  # giây: tối đa một bản lưu dự phòng mỗi 2 phút
AUTOSAVE_DELAY_MS = 3000
SESSION_FLAG = "phien-dang-mo.txt"  # còn file này lúc mở app = lần trước app không đóng đúng cách
HOME_PAGE = 5  # trang "Bắt đầu" trong self.stack
QUEUE_FILE = "queue.json"


class Bridge(QObject):
    """Chuyển sự kiện từ luồng nền về luồng giao diện."""
    progress = Signal(float, str)
    log = Signal(str)
    finished = Signal(str, str)  # (file xuất, lỗi)
    encoders = Signal(dict)
    system = Signal(object)
    accel = Signal(object)
    size = Signal(int, object, str)  # (lượt đo, kết quả dự đoán dung lượng, lỗi)
    ambient_ready = Signal()  # tiếng nền có sẵn vừa tạo xong ở luồng nền → tính lại
    audio_preview = Signal(object, str)  # ((kênh PCM, mốc bắt đầu), lỗi)


def chip(text: str = "", name: str = "chip") -> QLabel:
    lab = QLabel(text)
    lab.setObjectName(name)
    return lab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(SETTINGS_ORG, APP_NAME)
        # nơi đặt bộ nhớ đệm (Cài đặt → Bộ nhớ đệm): đặt trước mọi việc dùng tới bộ nhớ đệm (ảnh nhỏ, dọn file tạm)
        cdir = str(self.settings.value("pref/cache_dir", "") or "")
        ffmpeg_tools.OPTIONS["cache_dir"] = cdir if cdir and ffmpeg_tools.usable_dir(cdir) else ""
        self.project_path: str | None = None
        self.job: RenderJob | None = None
        self._job_kind = "video"
        self.bridge = Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.log.connect(lambda s: self.export_tab.append_log(s))
        self.bridge.finished.connect(self._on_finished)
        self.bridge.encoders.connect(self._on_encoders)
        self.bridge.system.connect(lambda info: self.settings_page.set_system(info))
        self.bridge.accel.connect(self._on_accel)
        self.bridge.size.connect(self._on_size)
        self.bridge.ambient_ready.connect(self._schedule)
        self.bridge.audio_preview.connect(self._on_audio_preview)
        self._audio_prev_runner: ffmpeg_tools.Runner | None = None
        from ..core import ambient_lib
        ambient_lib.on_ready = self.bridge.ambient_ready.emit
        self._accel: sysinfo.AccelInfo | None = None
        # dự đoán dung lượng: đo thử ở luồng nền, chờ người dùng ngừng chỉnh một chút rồi mới đo
        self._size_gen = 0
        self._size_runner: size_estimate.Group | None = None
        self._size_pending = None
        self._size_text = ""
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.setInterval(450)
        self._size_timer.timeout.connect(self._run_size)

        self.video_tab = VideoTab(self.settings)
        self.music_tab = MusicTab(self.settings)
        self.export_tab = ExportTab(self.settings)
        self.stack = QStackedWidget()  # chuyển trang tức thì, không hiệu ứng
        self.stack.setObjectName("pageStack")
        for t in (self.video_tab, self.music_tab, self.export_tab):
            # mỗi trang nằm trong vùng cuộn: cửa sổ nhỏ hơn nội dung thì hiện thanh cuộn thay vì bị kẹt
            sa = QScrollArea()
            sa.setWidget(t)
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.Shape.NoFrame)
            self.stack.addWidget(sa)
            t.changed.connect(self._schedule)
        self.music_tab.versionPreviewChanged.connect(lambda _i: self.recompute())
        # kéo thanh âm lượng: KHÔNG tính lại cả dự án mỗi bước (làm khựng giao diện / tiếng nghe thử);
        # chỉ tính lại khi ngừng kéo, và khi đang nghe thử thì đợi nghe xong
        self._mixer_idle = QTimer(self)
        self._mixer_idle.setSingleShot(True)
        self._mixer_idle.setInterval(1200)
        self._mixer_idle.timeout.connect(self._mixer_settled)
        self._mixer_dirty = False
        self.music_tab.mixer.changed.connect(self._mixer_idle.start)
        self._preview_sig = ""
        self._preview_timer = QTimer(self)  # chỉnh dự án → bản xem trước tự cập nhật (gom các lần sửa liền nhau)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(700)
        self._preview_timer.timeout.connect(self._preview_refresh)
        self.music_tab.mixer.changed.connect(self._preview_gains)
        self.video_tab.timeline.seekRequested.connect(self._preview_seek)
        self.video_tab.timeline.seek_enabled = True
        self.music_tab.mixer.playbackStopped.connect(self._mixer_stopped)
        self.music_tab.mixer.previewRequested.connect(self.preview_audio)
        self.music_tab.list.changed.connect(lambda: self.music_tab.mixer.mark_stale(
            "Playlist / âm lượng từng bài vừa đổi — bấm Dừng rồi Nghe thử lại để nghe bản mới."))
        self.video_tab.mixerRequested.connect(self._open_mixer)
        self.video_tab.queueAddRequested.connect(lambda: self.add_to_queue("video"))
        self.video_tab.seasonDropped.connect(self._season_dropped)
        self.video_tab.shuffleDetailsRequested.connect(self._show_shuffle_order)
        self.music_tab.mixer.sourceModeChanged.connect(self._set_source_mode)
        self.settings_page = SettingsPage(self.settings)
        self.settings_page.prefsChanged.connect(self._apply_prefs)
        self.settings_page.recheckRequested.connect(lambda: self._detect_encoders(force=True))
        sp = QScrollArea()
        sp.setWidget(self.settings_page)
        sp.setWidgetResizable(True)
        sp.setFrameShape(QFrame.Shape.NoFrame)
        self.stack.addWidget(sp)
        self.pages = (self.video_tab, self.music_tab, self.export_tab, self.settings_page)
        self.help_page = HelpPage()
        self.help_page.openProjectRequested.connect(self.open_project_path)
        self.help_page.actionRequested.connect(self._help_action)
        hp = QScrollArea()
        hp.setWidget(self.help_page)
        hp.setWidgetResizable(True)
        hp.setFrameShape(QFrame.Shape.NoFrame)
        self.stack.addWidget(hp)
        from .home_page import HomePage
        from .step_guide import StepGuide
        self.home = HomePage()
        self.home.chosen.connect(self._home_choice)
        self.home.openSample.connect(self.open_project_path)
        self.home.resumeRequested.connect(lambda: self.go_to(1 if self.mode == "music_only" else 0))
        hm = QScrollArea()
        hm.setWidget(self.home)
        hm.setWidgetResizable(True)
        hm.setFrameShape(QFrame.Shape.NoFrame)
        self.stack.addWidget(hm)  # chỉ số HOME_PAGE
        self.guide = StepGuide()
        self.guide.goTo.connect(self.go_to)
        self.export_tab.emptyActionRequested.connect(self.go_to)
        self.export_tab.startRequested.connect(self.start_render)
        self.export_tab.cancelRequested.connect(self.cancel_render)
        self.video_tab.previewSeamRequested.connect(self.preview_seam)
        self.video_tab.nextStepRequested.connect(self._on_video_next)
        self.music_tab.nextStepRequested.connect(lambda: self.go_to(2))
        self.export_tab.queueAddRequested.connect(
            lambda: self.add_to_queue("audio" if self.mode == "music_only" else "video"))
        self.music_tab.switchModeRequested.connect(self.set_mode)
        self.video_tab.switchModeRequested.connect(self.set_mode)
        self.export_tab.queueRunRequested.connect(self.run_queue)
        self.export_tab.batchRequested.connect(self.batch_from_folders)
        self.export_tab.queueEdited.connect(self._save_queue)
        self.export_tab.queueEditRequested.connect(self._edit_queue_item)
        self.export_tab.queuePauseRequested.connect(self._toggle_pause)
        self._pause_after = False
        QTimer.singleShot(1000, self._refresh_eta)
        self.settings_page.cacheChanged.connect(self._check_disk)
        QTimer.singleShot(4000, self._check_disk)
        self._editing_item: rq.QueueItem | None = None  # mục hàng đợi đang mở lại để sửa ("Sửa mục này")
        self._auto_name = ""  # tên file app tự gợi ý ("Tập 33") — người dùng tự gõ tên khác thì không đè
        self.queue: list[rq.QueueItem] = rq.load(ffmpeg_tools.data_dir() / QUEUE_FILE)
        self._queue_running = False
        self._queue_item: rq.QueueItem | None = None
        self._queue_results: list[str] = []
        self._queue_only: set[int] | None = None  # chỉ chạy các mục này (Xuất N bản nhạc), None = cả hàng đợi
        self._size_redo = False
        self._closing = False
        self._initial_loaded = False
        threading.Thread(target=ffmpeg_tools.clean_temp, daemon=True).start()  # dọn file tạm của các lần trước
        self.export_tab.set_queue(self.queue)

        self.setCentralWidget(self._build_shell())
        self.settings_page.welcomeRequested.connect(self.show_welcome)
        self._welcome = None
        self.updates = UpdateChecker(self.settings, self)  # cập nhật trong app (GitHub Releases)
        self.updates.checked.connect(self._on_update_checked)
        self.settings_page.updateCheckRequested.connect(self._check_updates)
        self.viewer.positionChanged.connect(self.video_tab.timeline.set_playhead)
        from .preview_player import SpaceToggle
        self._space = SpaceToggle(self, lambda: self.viewer)  # Space = Phát / Dừng ở mọi chỗ (trừ khi đang gõ chữ)
        self.viewer.player.stateChanged.connect(self._preview_state)
        self.music_tab.mixer.previewRequested.connect(lambda *_: self.viewer.player.pause())
        self.toast = motion.Toast(self)
        self.video_tab.notify.connect(self.notify)
        for key, fn in ((QKeySequence.StandardKey.New, self.new_project),
                        (QKeySequence.StandardKey.Open, self.open_project),
                        (QKeySequence.StandardKey.Save, self.save_project),
                        (QKeySequence.StandardKey.SaveAs, self.save_project_as)):
            QShortcut(key, self, activated=fn)
        QShortcut(QKeySequence(Qt.Key.Key_F1), self, activated=lambda: self.go_to(4))

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.recompute)
        # tự lưu liên tục: có thay đổi → vài giây sau ghi bản tự lưu (trước đây chỉ lưu lúc đóng app bình thường —
        # mất điện / máy tự khởi động lại / app bị tắt ngang là mất hết phần đã chỉnh)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(AUTOSAVE_DELAY_MS)
        self._autosave_timer.timeout.connect(self._autosave)
        self._last_saved = ""
        self._last_backup = 0.0
        # phiên trước có đóng đúng cách không: cờ "đang mở" còn nằm đó = app bị tắt ngang
        flag = ffmpeg_tools.data_dir() / SESSION_FLAG
        self._crashed_last = flag.is_file()
        try:
            flag.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
        except OSError:
            pass
        self._probe_tried: set = set()
        self._probe_inflight: set = set()
        self._probe_warm: set = set()  # đường dẫn đã chắc chắn có trong bộ nhớ đệm probe
        self._probe_watchdog = QTimer(self)  # ffprobe treo / luồng chết: gỡ cờ "đang đọc" để không kẹt mãi
        self._probe_watchdog.setSingleShot(True)
        self._probe_watchdog.setInterval(120_000)
        self._probe_watchdog.timeout.connect(self._probes_stuck)
        self._prober = w.ProbeWarmer(self)
        self._prober.done.connect(self._probes_done)

        self.resize(1480, 900)
        geo = self.settings.value("window/geometry")
        if geo:
            self.restoreGeometry(geo)
            if QApplication.screenAt(self.geometry().center()) is None:
                self.setWindowState(Qt.WindowState.WindowNoState)
                self.resize(1480, 900)

        self._update_title()
        branding.apply_window_frame(self)
        QTimer.singleShot(20, self._load_initial_project)
        QTimer.singleShot(450, self._maybe_welcome)  # lần đầu mở app: màn hình chào (sau khi cửa sổ đã hiện)
        QTimer.singleShot(250, self._detect_encoders)
        QTimer.singleShot(5000, self.updates.maybe_auto)  # sau khi app đã mở xong, không tranh lúc khởi động

    def show_welcome(self) -> None:
        """Màn hình chào: cách làm 3 bước + chọn Đơn giản / Đầy đủ (tự mở lần đầu; mở lại ở Cài đặt)."""
        if self._welcome is not None:
            return
        from .welcome import show_welcome

        def done() -> None:
            self._welcome = None
            self.settings.setValue("ui/welcome_done", "1")

        self._welcome = show_welcome(self, done, self.open_project_path)

    # ---------- cập nhật trong app ----------
    def _check_updates(self) -> None:
        self.settings_page.set_update_status("Đang kiểm tra…", busy=True)
        self.updates.check(manual=True)

    def _on_update_checked(self, rel, err: str, manual: bool) -> None:
        if self._closing:
            return
        self.updates.on_result(rel, err)
        text, tone = update_status_text(rel, err)
        self.settings_page.set_update_status(text if manual or not err else "", tone)
        if self.updates.is_update(rel, include_skipped=manual):
            self._update_text = f"  Có bản mới {rel.version}"
            self.update_btn.setText("" if self._compact else self._update_text)
            self.update_btn.setToolTip(f"Bản {rel.version} đã có — bấm để xem có gì mới và cài")
            self.update_btn.show()
            if manual:
                self._show_update()
            else:
                self.notify(f"Có bản mới {rel.version} — bấm nút “Có bản mới” ở thanh bên để cập nhật.", "ok", 7000)
        elif manual and not err:
            self.notify(f"Bạn đang dùng bản mới nhất ({APP_VERSION}).", "ok")

    def _show_update(self) -> None:
        rel = self.updates.latest
        if rel is None:
            return
        dlg = UpdateDialog(rel, self.settings, self)
        dlg.exec()
        if dlg.skipped:
            self.update_btn.hide()
        if dlg.install_path:
            self._install_update(dlg.install_path)

    def _install_update(self, path: str) -> None:
        """Đóng app như bình thường (lưu dự án, hỏi nếu đang xuất) rồi chạy bộ cài; cài xong bộ cài tự mở lại app."""
        self.close()
        if self.isVisible():  # người dùng chọn không huỷ lượt đang xuất
            self.notify("Chưa cài bản mới — xuất xong bấm “Có bản mới” để cài (bộ cài đã tải sẵn).", "warn", 7000)
            return
        try:
            updater.launch_installer(Path(path))
        except OSError as e:
            QMessageBox.warning(None, "Chưa cài được", f"Không chạy được bộ cài:\n{e}\n\nFile ở: {path}")
        QApplication.quit()

    def _maybe_welcome(self) -> None:
        if not self._closing and not self.settings.value("ui/welcome_done"):
            self.show_welcome()

    def _on_video_next(self) -> None:
        playlist = self.mode == "video_music" and self.video_tab.source.currentData() != "only"
        self.go_to(1 if playlist else 2)  # không dùng nhạc: sang thẳng Xuất (tiếng nền vẫn mở ở trang 2)

    def _load_initial_project(self) -> None:
        if self._initial_loaded or self._closing:
            return
        autosave = ffmpeg_tools.data_dir() / AUTOSAVE
        proj = Project()
        if autosave.is_file():
            try:
                proj = Project.load(str(autosave))
            except Exception:  # noqa: BLE001
                proj = Project()
        self.project_path = self.settings.value("project/path") or None
        if self.project_path and not os.path.isfile(self.project_path):
            self.project_path = None
        self.load_project(proj)
        self._last_saved = self._project_json(proj)
        if not (proj.video.clips or proj.music.tracks or proj.music.ambient):
            self.go_to(HOME_PAGE)  # dự án trống: mở màn hình Bắt đầu
        if self._crashed_last and autosave.is_file():
            when = datetime.fromtimestamp(autosave.stat().st_mtime).strftime("%H:%M %d/%m")
            self.restore_text.setText(f"Lần trước app bị tắt đột ngột (mất điện, máy khởi động lại…). Đã khôi phục dự án "
                                      f"từ bản tự lưu lúc <b>{when}</b>. Muốn lấy bản cũ hơn: <b>Bản lưu trước…</b>")
            self.restore_banner.setVisible(True)

    # ---------- khung giao diện ----------
    def _build_shell(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(236)
        self.side = side
        self._compact = None
        self._side_buttons: list[tuple[QPushButton, str, str]] = []
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 18, 14, 14)
        sv.setSpacing(theme.SP['xs'])

        logo = QLabel()
        logo.setPixmap(branding.pixmap(40, self.devicePixelRatioF()))
        logo.setFixedSize(42, 42)
        name = QLabel(APP_NAME)
        name.setObjectName("appName")
        name.setWordWrap(True)
        author = QLabel(f"{AUTHOR} · v{APP_VERSION}")
        author.setToolTip(f"{APP_NAME} phiên bản {APP_VERSION}")
        author.setObjectName("appAuthor")
        self.app_name, self.app_author = name, author
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.addWidget(logo)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(name)
        texts.addWidget(author)
        brand.addLayout(texts, 1)
        sv.addLayout(brand)
        sv.addSpacing(14)

        lbl_steps = QLabel("Trang làm việc")
        lbl_steps.setObjectName("sectionLabel")
        self.steps_label = lbl_steps
        self.nav = QButtonGroup(self)
        home_btn = QPushButton("  Bắt đầu")
        home_btn.setObjectName("nav")
        home_btn.setIcon(icons.icon("home", 16))
        home_btn.setIconSize(QSize(16, 16))
        home_btn.setCheckable(True)
        home_btn.setToolTip("Chọn việc muốn làm: video loop, chỉ nhạc, âm thanh nền, hàng loạt…")
        self._side_buttons.append((home_btn, "home", "Bắt đầu"))
        self.nav.addButton(home_btn, HOME_PAGE)
        sv.addWidget(home_btn)
        sv.addSpacing(6)
        sv.addWidget(lbl_steps)

        nav_items = (
            ("film", "Video"),
            ("music", "Nhạc && Nền"),
            ("export", "Xuất file"),
            ("settings", "Cài đặt"),
            ("help", "Hướng dẫn (F1)"),
        )
        for i, (ic_name, text) in enumerate(nav_items):
            if i == 3:
                sv.addSpacing(10)
                lbl_util = QLabel("Hệ thống")
                lbl_util.setObjectName("sectionLabel")
                self.util_label = lbl_util
                sv.addWidget(lbl_util)
            b = QPushButton(f"  {text}")
            b.setObjectName("nav")
            b.setIcon(icons.icon(ic_name, 16))
            b.setIconSize(QSize(16, 16))
            b.setCheckable(True)
            b.setToolTip(text.replace("&&", "&"))
            self._side_buttons.append((b, ic_name, text))
            self.nav.addButton(b, i)
            sv.addWidget(b)
        self.nav.idClicked.connect(self.go_to)
        self.nav.button(0).setChecked(True)
        self.nav_pill = motion.NavPill(side)  # nền mục đang chọn, trượt theo khi đổi trang
        sv.addStretch(1)

        lab = QLabel("Công cụ")
        lab.setObjectName("sectionLabel")
        self.project_label = lab
        sv.addWidget(lab)
        # Mới / Mở / Lưu đã có trên thanh trên cùng — thanh bên chỉ giữ công cụ riêng
        for ic_name, text, fn in (("folder", "Xuất hàng loạt…", self.batch_from_folders),):
            b = QPushButton(f"  {text}")
            b.setObjectName("nav")
            b.setIcon(icons.icon(ic_name, 15))
            b.setIconSize(QSize(15, 15))
            b.setToolTip(text)
            b.clicked.connect(fn)
            self._side_buttons.append((b, ic_name, text))
            sv.addWidget(b)

        self._update_text = ""
        self.update_btn = QPushButton()  # chỉ hiện khi có bản mới
        self.update_btn.setObjectName("updateBtn")
        theme.tag(self.update_btn, variant="tonal")
        self.update_btn.setIcon(icons.icon("download", 15, "accent_text"))
        self.update_btn.setIconSize(QSize(15, 15))
        self.update_btn.clicked.connect(self._show_update)
        self.update_btn.hide()
        sv.addSpacing(6)
        sv.addWidget(self.update_btn)

        sv.addSpacing(8)
        hw_card = QWidget()
        hw_card.setObjectName("sidebarCard")
        self.hw_card = hw_card
        hw_lay = QHBoxLayout(hw_card)
        hw_lay.setContentsMargins(10, 8, 10, 8)
        hw_lay.setSpacing(6)
        hw_ic = QLabel()
        icons.bind(hw_ic, "chip", 14, "accent_text")
        hw_ic.setFixedSize(14, 14)
        self.gpu_label = QLabel("Đang kiểm tra card đồ hoạ…")
        self.gpu_label.setObjectName("muted")
        self.gpu_label.setWordWrap(True)
        hw_lay.addWidget(hw_ic)
        hw_lay.addWidget(self.gpu_label, 1)
        sv.addWidget(hw_card)

        # ----- Thanh tiêu đề trên cùng (Header) -----
        header = QWidget()
        header.setObjectName("header")
        hv = QHBoxLayout(header)
        hv.setContentsMargins(16, 8, 16, 8)
        hv.setSpacing(8)

        # Nhóm 1: tên dự án + thao tác tệp
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("title")
        self.name_edit.setPlaceholderText("Tên dự án…")
        self.name_edit.setMinimumWidth(150)
        self.name_edit.setMaximumWidth(340)
        self.name_edit.setToolTip("Tên dự án (dùng làm tên file xuất mặc định)")
        self.name_edit.textChanged.connect(self._schedule)
        self.name_edit.textChanged.connect(self._update_title)
        self.name_edit.textChanged.connect(lambda t: self.name_edit.setToolTip(
            f"{t}\n\nTên dự án (dùng làm tên file xuất mặc định)" if t else "Tên dự án (dùng làm tên file xuất mặc định)"))
        hv.addWidget(self.name_edit, 1)

        proj_bar = QHBoxLayout()
        proj_bar.setSpacing(2)
        for ic_name, text, tip, fn in (
            ("plus", "Mới", "Dự án mới (Ctrl+N)", self.new_project),
            ("folder", "Mở", "Mở dự án .lsproj (Ctrl+O)", self.open_project),
            ("save", "Lưu", "Lưu dự án (Ctrl+S)", self.save_project),
            ("save_as", "Lưu thành…", "Lưu thành file dự án khác (Ctrl+Shift+S)", self.save_project_as),
        ):
            tb = QPushButton("")
            tb.setObjectName("ghost")
            tb.setProperty("icononly", True)
            tb.setIcon(icons.icon(ic_name, 16))
            tb.setIconSize(QSize(16, 16))
            tb.setFixedSize(32, 32)
            tb.setToolTip(tip)
            tb.setAccessibleName(text)
            tb.clicked.connect(fn)
            proj_bar.addWidget(tb)
        hv.addLayout(proj_bar)
        # hồ sơ kênh: chọn kênh là áp cả bộ intro / outro, logo, nhạc, mẫu bảng, nơi lưu…
        self.profile_btn = QPushButton("Kênh: chưa chọn")
        self.profile_btn.setObjectName("pill")
        self.profile_btn.setIcon(icons.icon("video_music", 14))
        self.profile_btn.setToolTip("Hồ sơ kênh — mỗi kênh một bộ cài đặt (intro / outro, logo, nhạc, mẫu, nơi lưu…)")
        self.profile_menu = QMenu(self.profile_btn)
        self.profile_menu.aboutToShow.connect(self._fill_profile_menu)
        self.profile_btn.setMenu(self.profile_menu)
        self._profile_collapsed = False
        self._set_profile_label(str(self.settings.value("profiles/last", "") or ""))
        hv.addWidget(self.profile_btn)
        hv.addSpacing(4)
        hv.addWidget(w.hairline())
        hv.addSpacing(4)

        # Nhóm 2: kiểu sản phẩm (bộ chọn một trong ba)
        # Chọn kiểu sản phẩm: quyết định trang nào được dùng và nút Xuất ra file gì
        self.mode = "video_music"
        self.mode_group = QButtonGroup(self)
        modes = (("video_music", "video_music", "Video có nhạc",
                  "Clip loop + nhạc tự lặp theo độ dài video → file .mp4"),
                 ("video_only", "film", "Chỉ video",
                  "Chỉ loop clip, bỏ qua trang Nhạc → file .mp4"),
                 ("music_only", "music", "Chỉ nhạc",
                  "Chỉ loop playlist nhạc cho đủ thời lượng → file .mp3/.m4a/.flac/.wav, bỏ qua trang Video"))
        self.mode_buttons = {}
        for key, ic_name, text, tip in modes:
            b = QPushButton(text)
            b.setIcon(icons.icon(ic_name, 14))
            b.setIconSize(QSize(14, 14))
            b.setCheckable(True)
            b.setToolTip(tip)
            bold = b.font()
            bold.setBold(True)
            b.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(text) + 46)
            b.setProperty("full_text", text)
            self.mode_group.addButton(b)
            self.mode_buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
        self.mode_buttons["video_music"].setChecked(True)
        self.mode_box = motion.SegmentBox(list(self.mode_buttons.values()))  # khối sáng trượt theo kiểu đang chọn
        hv.addWidget(self.mode_box)
        hv.addSpacing(4)
        hv.addWidget(w.hairline())
        hv.addSpacing(4)

        # Nhóm 3: tổng thời lượng + bật / tắt dòng thời gian
        self.chip_seq = chip()
        self.chip_rounds = chip()
        self.chip_total = chip("", "chipAccent")
        self.chip_warn = chip("", "chipWarn")
        self.chip_size = chip()
        self.chip_size.hide()
        # các chip nằm trong khung không đòi chiều rộng tối thiểu → cửa sổ thu nhỏ được; chip phụ tự ẩn khi hẹp
        chip_box = QWidget()
        chip_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        chip_box.setMinimumWidth(0)
        cb = QHBoxLayout(chip_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(8)
        cb.addStretch(1)
        for c in (self.chip_warn, self.chip_seq, self.chip_rounds, self.chip_size, self.chip_total):
            cb.addWidget(c)
        self.chip_box = chip_box
        chip_box.installEventFilter(self)  # khung chip đổi cỡ thật (sau khi thanh tiêu đề xếp xong) → chọn lại chip
        hv.addWidget(chip_box, 1)

        self.tl_toggle = QPushButton("Dòng thời gian")
        self.tl_toggle.setObjectName("ghost")
        self.tl_toggle.setMinimumHeight(32)
        self.tl_toggle.setIcon(icons.icon("timeline", 14))
        self.tl_toggle.setIconSize(QSize(14, 14))
        self.tl_toggle.setCheckable(True)
        self.tl_toggle.setChecked(True)
        self.tl_toggle.setToolTip("Ẩn / hiện dòng thời gian ở đáy màn hình (kéo vạch phát trên đó để tua trình phát)")
        pref = self.settings.value("ui/timeline_dock", "")
        self._tl_user = pref in ("on", "off")  # người dùng đã tự chọn → không tự ẩn / hiện nữa
        if self._tl_user:
            self.tl_toggle.setChecked(pref == "on")
        # nối tín hiệu SAU khi đặt trạng thái đã lưu: lúc này khung dòng thời gian chưa được tạo
        self.tl_toggle.toggled.connect(self._update_timeline_visibility)
        self.tl_toggle.clicked.connect(lambda on: (self.settings.setValue("ui/timeline_dock", "on" if on else "off"),
                                                   setattr(self, "_tl_user", True)))
        hv.addWidget(self.tl_toggle)

        # Thanh dòng thời gian dùng chung cho cả 3 bước (Video, Nhạc, Xuất) — nằm ở đáy như CapCut / Premiere
        self.timeline_wrap = QWidget()
        self.timeline_wrap.setObjectName("timelineDock")
        tl_lay = QVBoxLayout(self.timeline_wrap)
        tl_lay.setContentsMargins(16, 4, 16, 6)
        tl_lay.setSpacing(2)
        # thanh mảnh luôn hiện: bấm để thu gọn / mở dòng thời gian (nhớ lựa chọn)
        self.dock_bar = QPushButton("Dòng thời gian")
        self.dock_bar.setObjectName("dockBar")
        self.dock_bar.setIcon(icons.icon("down", 12, "text_muted"))
        self.dock_bar.setIconSize(QSize(12, 12))
        self.dock_bar.setFixedHeight(22)
        self.dock_bar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dock_bar.setToolTip("Thu gọn / mở dòng thời gian (kéo vạch phát trên đó để tua trình phát)")
        self.dock_bar.clicked.connect(lambda: self.tl_toggle.click())
        tl_lay.addWidget(self.dock_bar, 0, Qt.AlignmentFlag.AlignLeft)
        tl_lay.addWidget(self.video_tab.timeline)

        # Trình phát xem trước luôn hiện cạnh trang đang làm (bước Video / Nhạc / Xuất)
        from PySide6.QtWidgets import QSplitter
        from .preview_player import PreviewPanel
        self.viewer = PreviewPanel(self.settings, self)
        self.viewer.setMinimumWidth(320)
        self.work = QSplitter(Qt.Orientation.Horizontal)
        self.work.setObjectName("workSplit")
        self.work.setHandleWidth(3)
        self.work.setChildrenCollapsible(False)
        self.work.addWidget(self.stack)
        self.work.addWidget(self.viewer)
        self.work.setStretchFactor(0, 2)
        self.work.setStretchFactor(1, 1)
        state = self.settings.value("ui/work_split")
        if state is None or not self.work.restoreState(state):
            self.work.setSizes([660, 340])
        self.work.splitterMoved.connect(self._work_split_moved)

        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        mv.addWidget(header)
        self.accent_line = effects.AccentLine()  # vạch dải màu; đang xuất thì chạy liên tục
        mv.addWidget(self.accent_line)
        mv.addWidget(self.guide)
        self.edit_banner = QFrame()
        self.edit_banner.setObjectName("editBanner")
        eb = QHBoxLayout(self.edit_banner)
        eb.setContentsMargins(16, 6, 12, 6)
        eb.setSpacing(10)
        eb_icon = QLabel()
        icons.bind(eb_icon, "edit", 15, "accent_text")
        self.edit_text = QLabel()
        eb_update = QPushButton("Cập nhật mục")
        eb_update.setObjectName("accentBtn")
        eb_update.setToolTip("Lưu thay đổi vào đúng mục này trong hàng đợi (không tạo mục mới)")
        eb_update.clicked.connect(lambda: self.add_to_queue("video"))
        eb_cancel = QPushButton("Huỷ sửa")
        eb_cancel.setObjectName("ghost")
        eb_cancel.setToolTip("Thôi sửa — mục trong hàng đợi giữ nguyên như lúc thêm")
        eb_cancel.clicked.connect(self._cancel_edit)
        eb.addWidget(eb_icon)
        eb.addWidget(self.edit_text, 1)
        eb.addWidget(eb_update)
        eb.addWidget(eb_cancel)
        self.edit_banner.setVisible(False)
        mv.addWidget(self.edit_banner)
        # ổ đĩa sắp đầy (bộ nhớ đệm / thư mục lưu): báo sớm, kèm cách xử lý ngay tại chỗ
        self.disk_banner = QFrame()
        self.disk_banner.setObjectName("warnBar")
        db = QHBoxLayout(self.disk_banner)
        db.setContentsMargins(16, 6, 12, 6)
        db.setSpacing(10)
        db_icon = QLabel()
        icons.bind(db_icon, "info", 15, "warn_text")
        self.disk_text = QLabel()
        self.disk_text.setWordWrap(True)
        db_move = QPushButton("Chuyển bộ nhớ đệm sang ổ khác…")
        db_move.setObjectName("pill")
        db_move.clicked.connect(lambda: self.settings_page.pick_cache_dir())
        db_clean = QPushButton("Dọn bộ nhớ đệm")
        db_clean.setObjectName("ghost")
        db_clean.clicked.connect(lambda: self.settings_page._clear_cache())
        db_hide = QPushButton("Ẩn")
        db_hide.setObjectName("ghost")
        db_hide.clicked.connect(self._hide_disk_banner)
        self._disk_buttons = (db_move, db_clean)
        db.addWidget(db_icon)
        db.addWidget(self.disk_text, 1)
        for b in (db_move, db_clean, db_hide):
            db.addWidget(b)
        self.disk_banner.setVisible(False)
        self._disk_hidden = False
        mv.addWidget(self.disk_banner)
        # lần trước app bị tắt ngang: báo đã khôi phục từ bản tự lưu, cho mở bản lưu cũ hơn
        self.restore_banner = QFrame()
        self.restore_banner.setObjectName("editBanner")
        rb = QHBoxLayout(self.restore_banner)
        rb.setContentsMargins(16, 6, 12, 6)
        rb.setSpacing(10)
        rb_icon = QLabel()
        icons.bind(rb_icon, "undo", 15, "accent_text")
        self.restore_text = QLabel()
        self.restore_text.setWordWrap(True)
        rb_old = QPushButton("Bản lưu trước…")
        rb_old.setObjectName("pill")
        rb_old.setToolTip("Mở một trong 5 bản tự lưu gần nhất (mỗi bản cách nhau ít nhất 2 phút)")
        rb_old.clicked.connect(self._open_backup)
        rb_ok = QPushButton("OK")
        rb_ok.setObjectName("ghost")
        rb_ok.clicked.connect(lambda: self.restore_banner.setVisible(False))
        rb.addWidget(rb_icon)
        rb.addWidget(self.restore_text, 1)
        rb.addWidget(rb_old)
        rb.addWidget(rb_ok)
        self.restore_banner.setVisible(False)
        mv.addWidget(self.restore_banner)
        mv.addWidget(self.work, 1)
        mv.addWidget(self.timeline_wrap)
        shell = QWidget()
        shell.setObjectName("shell")
        lay = QHBoxLayout(shell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(side)
        lay.addWidget(main, 1)
        return shell

    def _update_timeline_visibility(self) -> None:
        if not hasattr(self, "timeline_wrap"):
            return
        idx = self.stack.currentIndex()
        on_steps = idx in (0, 1, 2)
        expanded = self.tl_toggle.isChecked()
        self.timeline_wrap.setVisible(on_steps)  # thanh mảnh luôn hiện; nội dung chỉ hiện khi mở
        self.video_tab.timeline.setVisible(expanded)
        self.dock_bar.setIcon(icons.icon("down" if expanded else "up", 12, "text_muted"))
        self.dock_bar.setText("Dòng thời gian" if expanded else "Dòng thời gian (đang thu gọn)")
        self.tl_toggle.setVisible(on_steps)
        if hasattr(self, "viewer"):
            was = self.viewer.isVisible()
            self.viewer.setVisible(on_steps)
            if not on_steps and self.viewer.is_playing():
                self.viewer.player.pause()  # sang trang khác (Cài đặt, Hướng dẫn…): dừng phát
            if on_steps and not was:
                self._preview_timer.start()
            QTimer.singleShot(0, self._adapt_pages)

    def _work_split_moved(self, *_) -> None:
        # kéo vạch chia: chỉ sắp xếp lại trang khi ngừng kéo (~0,12 giây) — kéo mượt, không giật
        if not hasattr(self, "_split_idle"):
            self._split_idle = QTimer(self)
            self._split_idle.setSingleShot(True)
            self._split_idle.setInterval(120)
            self._split_idle.timeout.connect(lambda: (self.settings.setValue("ui/work_split", self.work.saveState()),
                                                      self._adapt_pages()))
        self._split_idle.start()

    def _adapt_pages(self) -> None:
        """Trang đang làm co giãn theo chỗ còn lại cạnh trình phát (hẹp thì phần cài đặt xếp xuống dưới)."""
        avail = self.stack.width() if self.stack.width() > 200 else self.width() - self.side.width() - 20
        height = self.stack.height() if self.stack.height() > 200 else 0
        for page in self.pages:
            page.adapt(avail, height)

    def _update_header_chips_visibility(self) -> None:
        width = self.width()
        self.tl_toggle.setText("" if width < 1360 else "Dòng thời gian")
        # bộ chọn kiểu: cửa sổ hẹp → chỉ còn biểu tượng (rê chuột để xem tên)
        narrow = width < 1100
        for b in self.mode_buttons.values():
            full = b.property("full_text") or ""
            b.setText("" if narrow else full)
            bold = b.font()
            bold.setBold(True)
            b.setMinimumWidth(40 if narrow else QFontMetrics(bold).horizontalAdvance(full) + 46)
        # nút Kênh: cửa sổ hẹp → chỉ biểu tượng (tên kênh trong tooltip) để Tổng / dung lượng không bị cắt chữ
        self._profile_collapsed = width < 1500 * max(1.0, theme.scale())
        self.profile_btn.setText("" if self._profile_collapsed else getattr(self, "_profile_text", "Kênh"))
        self._fit_chips()
        QTimer.singleShot(0, self._fit_chips)  # đo lại sau khi thanh tiêu đề sắp xếp xong

    def _fit_chips(self) -> None:
        """Hiện chip theo độ ưu tiên (Tổng → lưu ý → số vòng → một chuỗi) cho vừa chỗ, không chip nào bị cắt chữ."""
        has_err = self.chip_total.objectName() in ("chip", "chipError") and not self.chip_seq.text()
        cands = [c for c, ok in ((self.chip_size, getattr(self, "_size_wanted", False)),
                                 (self.chip_warn, getattr(self, "_warn_wanted", False))) if ok and not has_err]
        # ô Tổng luôn đủ chữ: khung chip giữ tối thiểu bằng nó (ô tên dự án co lại thay vì cắt chữ "Tổng 1:00:00")
        self.chip_box.setMinimumWidth(self.chip_total.sizeHint().width() + 2)
        avail = self.chip_box.width()
        used = self.chip_total.sizeHint().width()
        show = set()
        for c in cands:
            need = c.sizeHint().width() + 8
            if used + need + 12 <= avail:  # chừa chút: thanh tiêu đề còn xếp lại sau khi đo
                show.add(c)
                used += need
        for c in (self.chip_size, self.chip_warn, self.chip_rounds, self.chip_seq):
            c.setVisible(c in show)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is getattr(self, "chip_box", None) and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._fit_chips)
        return super().eventFilter(obj, event)

    def resizeEvent(self, e) -> None:  # noqa: N802
        if e is not None:
            super().resizeEvent(e)
        self._set_compact(self.width() < 1280 * max(1.0, theme.scale()))  # bigger fonts need more room
        if not getattr(self, "_tl_user", True):  # màn hình laptop thấp: nhường chỗ cho nội dung chính
            want = self.height() >= 820  # màn hình thấp: thu gọn dòng thời gian để bảng clip có chỗ
            if self.tl_toggle.isChecked() != want:
                self.tl_toggle.setChecked(want)
        self._adapt_pages()
        QTimer.singleShot(0, self._adapt_pages)  # đo lại khi bố cục đã xếp xong
        self._update_header_chips_visibility()
        QTimer.singleShot(0, self._refresh_overlays)

    def _refresh_overlays(self) -> None:
        """Đặt lại vị trí các lớp nổi (nền mục chọn ở thanh bên, thông báo) sau khi đổi kích thước."""
        btn = self.nav.checkedButton()
        if btn is not None:
            self.nav_pill.move_to(btn, animate=False)
        if hasattr(self, "toast"):
            self.toast.reposition()

    def notify(self, text: str, kind: str = "ok", ms: int = 2800) -> None:
        """Thông báo nổi nhỏ ở góc dưới phải (tự ẩn)."""
        self.toast.show_message(text, kind, ms)

    def _set_compact(self, compact: bool) -> None:
        """Cửa sổ hẹp: thanh bên chỉ còn biểu tượng."""
        if compact == self._compact:
            return
        self._compact = compact
        from . import theme
        self.side.setFixedWidth(68 if compact else int(236 * max(1.0, theme.scale())))  # rộng theo cỡ chữ
        self.app_name.setVisible(not compact)
        self.app_author.setVisible(not compact)
        self.steps_label.setVisible(not compact)
        self.util_label.setVisible(not compact)
        self.project_label.setVisible(not compact)
        self.hw_card.setVisible(not compact)
        self.update_btn.setText("" if compact else self._update_text)
        for b, _ic, text in self._side_buttons:
            b.setText("" if compact else f"  {text}")

    def _update_nav_badges(self, proj: Project) -> None:
        n_clips = sum(1 for c in proj.video.clips if c.enabled and (c.count > 0 if c.plays_mode == "fixed" else c.max > 0))
        n_tracks = sum(1 for t in proj.music.tracks if t.enabled and t.plays > 0)
        n_amb = sum(1 for a in proj.music.ambient if a.enabled and a.volume > 0)
        n_q = sum(1 for i in self.queue if i.status == "pending")

        video_skipped = self.mode == "music_only"
        # Chỉ video / chỉ tiếng gốc: playlist không dùng, nhưng trang 2 vẫn mở để thêm / chỉnh / xoá TIẾNG NỀN
        # (lớp tiếng nền vẫn được trộn vào video — không được để người dùng mất cách chỉnh nó)
        music_skipped = self.mode == "video_only" or (self.mode == "video_music" and proj.video.source_audio == "only")

        self.nav.button(0).setEnabled(not video_skipped)
        self.nav.button(1).setEnabled(True)
        self.music_tab.set_playlist_enabled(not music_skipped)

        if video_skipped and self.stack.currentIndex() == 0:
            self.go_to(1)

        v_txt = "Video (bỏ qua)" if video_skipped else (f"Video ({n_clips})" if n_clips else "Video")
        if music_skipped:
            m_txt = f"Tiếng nền ({n_amb})" if n_amb else "Tiếng nền"
        else:
            m_parts = ([f"{n_tracks} bài"] if n_tracks else []) + ([f"{n_amb} nền"] if n_amb else [])
            m_txt = f"Nhạc ({', '.join(m_parts)})" if m_parts else "Nhạc && Nền"
        e_txt = f"Xuất file ({n_q} chờ)" if n_q else "Xuất file"

        for page, new_text in ((0, v_txt), (1, m_txt), (2, e_txt)):
            btn = self.nav.button(page)
            idx = next(i for i, (b, _ic, _t) in enumerate(self._side_buttons) if b is btn)
            b, ic_name, _ = self._side_buttons[idx]
            self._side_buttons[idx] = (b, ic_name, new_text)
            b.setToolTip(new_text.replace("&&", "&"))
            if not self._compact:
                b.setText(f"  {new_text}")

    def go_to(self, index: int) -> None:
        btn = self.nav.button(index)
        if btn is not None and not btn.isEnabled():
            return
        self.stack.setCurrentIndex(index)
        if btn is not None:
            btn.setChecked(True)
            self.nav_pill.move_to(btn, animate=False)
        self._update_timeline_visibility()
        self._update_guide()

    # ---------- màn hình Bắt đầu + hướng dẫn từng bước ----------
    def _home_choice(self, key: str) -> None:
        if key in ("video_music", "video_only"):
            self.set_mode(key)
            self.go_to(0)
            self.notify("Bước 1: kéo thả clip / thư mục vào bảng (hoặc bấm vào khung trống)", "info", 4500)
        elif key == "music_only":
            self.set_mode("music_only")
            self.go_to(1)
            self.notify("Thêm bài nhạc vào playlist, rồi đặt độ dài ở thẻ Độ dài file nhạc", "info", 4500)
        elif key == "ambient":
            self.set_mode("music_only")
            self.go_to(1)
            QTimer.singleShot(300, lambda: self.music_tab.g_amb.parentWidget() and self._scroll_to(self.music_tab.g_amb))
            self.notify("Tiếng nền: thêm file mưa / lửa / sóng ở thẻ Lớp tiếng nền (bên phải) — "
                        "không cần thêm bài nhạc", "info", 6000)
        elif key == "batch":
            self.batch_from_folders()
        elif key == "open":
            self.open_project()

    def _scroll_to(self, widget) -> None:
        area = widget.parentWidget()
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parentWidget()
        if area is not None:
            area.ensureWidgetVisible(widget, 0, 40)

    def _steps_for_mode(self) -> list[tuple[str, int]]:
        if self.mode == "video_only":
            return [("Video", 0), ("Tiếng nền", 1), ("Xuất", 2)]
        if self.mode == "music_only":
            return [("Nhạc", 1), ("Xuất", 2)]
        return [("Video", 0), ("Nhạc", 1), ("Xuất", 2)]

    def _update_guide(self) -> None:
        """Thanh hướng dẫn: bước hiện tại + việc cần làm tiếp, theo kiểu sản phẩm và trạng thái dự án."""
        if not hasattr(self, "guide"):
            return
        idx = self.stack.currentIndex()
        proj = self.collect_project()
        n_clips = sum(1 for c in proj.video.clips if c.enabled)
        n_tracks = sum(1 for t in proj.music.tracks if t.enabled)
        n_amb = sum(1 for a in proj.music.ambient if a.enabled)
        total = getattr(self, "_last_total", 0.0)
        ok_tl = getattr(self, "_last_ok", False)
        name = proj.name or "Dự án"
        if n_clips or n_tracks or n_amb:
            parts = ([f"{n_clips} clip"] if n_clips else []) + ([f"{n_tracks} bài"] if n_tracks else []) \
                + ([f"{n_amb} tiếng nền"] if n_amb else [])
            self.home.set_resume(f"Tiếp tục dự án đang làm: {name} ({', '.join(parts)})")
        else:
            self.home.set_resume("")
        self.guide.setVisible(idx in (0, 1, 2))
        if idx not in (0, 1, 2):
            return
        no_playlist = self.mode == "video_only" or proj.video.source_audio == "only"
        done = {0: n_clips > 0 and ok_tl,
                1: n_tracks > 0 or n_amb > 0 or (no_playlist and self.mode != "music_only" and n_clips > 0),
                2: False}
        steps = [(nm, page, done.get(page, False)) for nm, page in self._steps_for_mode()]
        dur = fmt_dur(total) if total else ""
        ok = False
        long = ""  # câu hướng dẫn đầy đủ (HTML) trong tooltip; hint là bản một dòng
        if idx == 0:
            if self.mode == "music_only":
                hint = "Kiểu Chỉ nhạc không dùng trang Video: sang bước Nhạc."
            elif not n_clips:
                hint = "Thêm clip: kéo thả video / ảnh / thư mục vào bảng."
                long = ("<b>Thêm clip:</b> kéo thả video / ảnh / cả thư mục vào bảng (hoặc bấm vào khung trống). "
                        "Có clip tên <i>loop…</i> và các cảnh <i>2_, 3_…</i>? Bấm <b>Xen kẽ clip nền</b> để tự xếp.")
            elif not ok_tl:
                hint = "Còn lỗi ở bảng clip: xem dòng đỏ ở thanh trên cùng."
            else:
                ok = True
                nxt = "Nhạc" if self.mode == "video_music" else "Xuất"
                hint = f"{n_clips} clip, dài {dur}. Sửa cột Số lần phát nếu cần, rồi sang bước {nxt}."
                long = (f"<b>{n_clips} clip</b> · video dài <b>{dur}</b>. Đổi số lần loop ở cột <i>Số lần phát</i> "
                        f"(<code>70</code> = 70 lần, <code>10p</code> = 10 phút). Xong thì bấm <b>Tiếp theo: {nxt}</b>.")
        elif idx == 1:
            if self.mode == "video_only" or (self.mode == "video_music" and proj.video.source_audio == "only"):
                why = "Kiểu Chỉ video" if self.mode == "video_only" else "Đang dùng chỉ tiếng gốc clip"
                hint = f"{why}: không dùng playlist. Có thể thêm tiếng nền, rồi sang bước Xuất."
                long = (f"<b>{why}</b>: playlist nhạc không dùng. (Tuỳ chọn) thêm <b>tiếng nền</b> — mưa, sóng, gió… — ở cột "
                        "phải, tự lặp hết video. Xong thì sang bước <b>Xuất</b>.")
                ok = True
            elif self.mode == "music_only":
                if not (n_tracks or n_amb):
                    hint = "Thêm bài nhạc vào playlist, hoặc chỉ thêm tiếng nền ở cột phải."
                    long = ("<b>Thêm bài nhạc</b> vào playlist (kéo thả file / thư mục) — hoặc chỉ thêm "
                            "<b>tiếng nền</b> (mưa, lửa…) ở cột phải để làm âm thanh môi trường.")
                else:
                    ok = True
                    hint = f"File dài {dur}. Đổi độ dài ở thẻ Độ dài file nhạc, rồi sang bước Xuất."
                    long = (f"File dài <b>{dur}</b>. Đổi độ dài / số bản ở thẻ <b>Độ dài file nhạc</b> (cột phải). "
                            "Xong thì sang bước <b>Xuất</b>.")
            elif not n_tracks:
                hint = "Thêm bài nhạc: nhạc tự lặp cho đủ độ dài video. Không cần nhạc? Chọn Chỉ video."
                long = (f"<b>Thêm bài nhạc</b>: nhạc tự lặp cho đủ video <b>{dur}</b>, bài cuối nhỏ dần. "
                        "Không cần nhạc? Chọn <b>Chỉ video</b> ở thanh trên cùng.")
            else:
                ok = True
                hint = f"{n_tracks} bài tự lặp theo video {dur}. Chỉnh âm lượng ở Bảng trộn âm, rồi sang bước Xuất."
                long = (f"<b>{n_tracks} bài</b> tự lặp theo video <b>{dur}</b>. (Tuỳ chọn) chỉnh to / nhỏ ở Bảng trộn âm (có nghe thử), "
                        "thêm tiếng nền, ghim bài, đổi thứ tự ở cột phải. Xong thì sang bước <b>Xuất</b>.")
        else:
            if not proj.export.output_dir:
                hint = "Chọn thư mục lưu ở thẻ Nơi lưu, rồi bấm Xuất."
                long = "<b>Chọn thư mục lưu</b> ở thẻ <i>Nơi lưu</i>, rồi bấm <b>Bắt đầu xuất</b>."
            elif not ok_tl:
                hint = "Chưa xuất được: quay lại bước trước để thêm clip / nhạc."
            else:
                ok = True
                size = getattr(self, "_size_text", "")
                hint = f"Sẵn sàng: dài {dur}{(', ' + size) if size else ''}. Bấm Xuất, hoặc thêm vào hàng đợi."
                long = (f"Sẵn sàng: dài <b>{dur}</b>{(' · dung lượng ' + size) if size else ''} → bấm "
                        "<b>Bắt đầu xuất</b>, hoặc <b>Thêm vào hàng đợi</b> để xuất nhiều dự án liền nhau.")
        self.guide.set_state(steps, idx, hint, ok, long)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        branding.apply_window_frame(self)
        QTimer.singleShot(0, lambda: self.resizeEvent(None))

    # ---------- dự án ----------
    def collect_project(self) -> Project:
        music = self.music_tab.collect()
        self.export_tab.fill_audio_export(music)  # độ dài/định dạng file nhạc nằm ở trang Xuất
        video = self.video_tab.collect()
        video.music_volume, video.source_volume = self.music_tab.mixer.values()  # Bảng trộn âm (mọi chế độ)
        video.source_level = self.music_tab.mixer.level_on()
        return Project(name=self.name_edit.text().strip() or "Dự án", output_kind=self.mode,
                       video=video, music=music, export=self.export_tab.collect())

    def set_mode(self, mode: str) -> None:
        """Đổi kiểu sản phẩm: Video có nhạc / Chỉ video / Chỉ nhạc."""
        self.mode = mode
        self.mode_buttons[mode].setChecked(True)
        self.video_tab.set_mode(mode)
        self.music_tab.set_mode(mode)
        self.export_tab.set_mode(mode)
        self.nav.button(0).setEnabled(mode != "music_only")
        self.nav.button(1).setEnabled(True)  # Chỉ video: trang 2 = tiếng nền
        # Tự chuyển khỏi trang bị bỏ qua
        if mode == "music_only" and self.stack.currentIndex() == 0:
            self.go_to(1)
        self._schedule()

    def load_project(self, proj: Project, editing: rq.QueueItem | None = None) -> None:
        self._set_editing(editing)  # mở dự án khác / dự án mới: thôi sửa mục hàng đợi
        self._auto_name = ""
        self._initial_loaded = True
        self.name_edit.blockSignals(True)
        self.name_edit.setText(proj.name)
        self.name_edit.setCursorPosition(0)
        self.name_edit.blockSignals(False)
        self.video_tab.load(proj.video)
        self.music_tab.load(proj.music)
        self.music_tab.mixer.set_values(proj.video.music_volume, proj.video.source_volume)
        self.music_tab.mixer.set_level(proj.video.source_level)
        self.export_tab.load(proj.export)
        self.export_tab.load_audio_export(proj.music)
        self.set_mode(proj.output_kind)
        self._update_title()
        self.recompute()
        for note in getattr(proj, "notes", []):
            QTimer.singleShot(600, lambda n=note: self.notify(n, "warn", 8000))

    def new_project(self) -> None:
        if QMessageBox.question(self, "Dự án mới", "Xoá danh sách hiện tại và bắt đầu dự án mới?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.project_path = None
        proj = Project()
        proj.export = self.export_tab.collect()  # giữ thư mục xuất, preset
        proj.export.filename = ""
        sample = os.path.normcase(str(ffmpeg_tools.app_dir() / "Mau-Test"))
        if proj.export.output_dir and os.path.normcase(os.path.abspath(proj.export.output_dir)).startswith(sample):
            proj.export.output_dir = ""  # thư mục Xuat của dự án mẫu nằm trong thư mục cài app (gỡ app là mất)
        self.load_project(proj)
        self.go_to(HOME_PAGE)

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Mở dự án", self.settings.value("dir/project", ""),
                                              f"Dự án {APP_NAME} (*{PROJECT_EXT})")
        if path:
            self.open_project_path(path)

    def open_project_path(self, path: str) -> None:
        try:
            proj = Project.load(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Không mở được", str(e))
            return
        self.project_path = path
        self.settings.setValue("dir/project", os.path.dirname(path))
        self.load_project(proj)
        self.go_to(1 if proj.output_kind == "music_only" else 0)

    def save_project(self) -> None:
        if not self.project_path:
            self.save_project_as()
            return
        try:
            self.collect_project().save(self.project_path)
        except OSError as e:
            QMessageBox.critical(self, "Không lưu được dự án",
                                 f"Không ghi được file:\n{self.project_path}\n\n{e}\n\n"
                                 "Thư mục chỉ đọc, ổ đầy hoặc USB đã rút? Thử “Lưu thành…” vào chỗ khác.")
            return
        self.notify(f"Đã lưu dự án: {os.path.basename(self.project_path)}")
        self._update_title()

    def save_project_as(self) -> None:
        start = os.path.join(self.settings.value("dir/project", ""),
                             (self.name_edit.text().strip() or "du-an") + PROJECT_EXT)
        path, _ = QFileDialog.getSaveFileName(self, "Lưu dự án", start, f"Dự án {APP_NAME} (*{PROJECT_EXT})")
        if not path:
            return
        if not path.endswith(PROJECT_EXT):
            path += PROJECT_EXT
        self.project_path = path
        self.settings.setValue("dir/project", os.path.dirname(path))
        self.save_project()

    def _update_title(self) -> None:
        name = self.name_edit.text().strip() or "Dự án"
        suffix = f" — {self.project_path}" if self.project_path else ""
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — {name}{suffix}")

    # ---------- tính toán xem trước ----------
    def _schedule(self, *_) -> None:
        self._timer.start()

    def _cold_media(self) -> dict:
        """File của dự án chưa được probe (chưa trong bộ nhớ đệm, chưa thử): đọc ở luồng nền thay vì chặn giao diện.
        Đường dẫn đã biết là nóng thì khỏi os.stat lại mỗi lần tính."""
        proj = self.collect_project()
        v, ms = proj.video, proj.music
        paths = [c.path for c in v.clips if c.enabled] + [p for p in (v.intro, v.outro) if p]             + [t.path for t in ms.tracks if t.enabled]
        paths = [p for p in dict.fromkeys(paths) if p not in self._probe_warm]
        cold = probe.cold_keys(paths)
        self._probe_warm.update(set(paths) - set(cold.values()))
        return {k: p for k, p in cold.items() if k not in self._probe_tried and k not in self._probe_inflight}

    def _probes_done(self, keys) -> None:
        self._probe_inflight -= keys
        self._probe_tried |= keys  # lỗi không ghi nhớ được (thiếu ffprobe / quá giờ): đừng đọc lại mãi
        if not self._probe_inflight:
            self._probe_watchdog.stop()
            if not self._closing:
                self.recompute()

    def _probes_stuck(self) -> None:
        if self._probe_inflight:
            self._probes_done(frozenset(self._probe_inflight))

    def recompute(self) -> None:
        if self._initial_loaded and not self._closing:
            self._autosave_timer.start()  # mọi thay đổi đều qua đây → vài giây sau tự lưu
        cold = self._cold_media()
        if cold:
            self._probe_inflight |= set(cold)
            self._probe_watchdog.start()
            self._prober.warm(cold)
        if self._probe_inflight:
            # chờ đọc xong rồi tính lại; trong lúc đó không cho xuất theo số liệu cũ
            self.export_tab.set_can_export(False)
            self.export_tab.set_summary("Đang đọc file…")
            return
        self._recompute_core()
        self._update_guide()
        if hasattr(self, "viewer") and self.viewer.isVisible():
            self._preview_timer.start()

    # ---------- Xem trước ----------
    @staticmethod
    def _preview_signature(proj) -> str:
        from .preview_player import project_signature
        return project_signature(proj)

    def open_preview(self) -> None:
        """Nút "Mở trình phát" ở trang Hướng dẫn: sang bước Video (hoặc Nhạc) và đưa con trỏ vào trình phát."""
        if self.stack.currentIndex() not in (0, 1, 2):
            self.go_to(1 if self.mode == "music_only" else 0)
        self._preview_refresh()
        self.viewer.view.setFocus()

    def _preview_refresh(self) -> None:
        if not hasattr(self, "viewer") or not self.viewer.isVisible():
            return
        proj = self.collect_project()
        version = self.music_tab.preview_version() if proj.output_kind == "music_only" else 0
        sig = self._preview_signature(proj) + f"|v{version}"
        if sig == self._preview_sig:
            return
        self._preview_sig = sig
        if proj.output_kind != "music_only" and not proj.video.clips:
            self.viewer.clear("Kéo thả clip vào trang Video để xem trước")
            return
        self.viewer.open_project(proj, self.music_tab.mixer.gains(), version)

    def _preview_gains(self) -> None:
        if hasattr(self, "viewer"):
            self.viewer.player.set_gains(self.music_tab.mixer.gains())

    def _preview_seek(self, t: float) -> None:
        if hasattr(self, "viewer") and self.viewer.player.tl is not None:
            self.viewer.player.seek(t)

    def _preview_state(self, state: str) -> None:
        # chỉ khi trình phát thật sự phát (không phải lúc tính lại vì dự án vừa đổi): không phát chồng Nghe thử 20 giây
        if state == "playing":
            self.music_tab.mixer.stop(quiet=True)

    def _suggest_filename(self, proj: Project) -> None:
        """Bảng dùng file kiểu 33_4_LOOP A (một tập): tên file tự là "Tập 33" — khỏi quên đổi tên, khỏi trùng.
        Người dùng đã tự gõ tên khác thì giữ nguyên."""
        from ..core import table_preset as tp
        eps = tp.episodes([c.path for c in proj.video.clips if c.enabled]) if self.mode != "music_only" else []
        want = f"Tập {eps[0]}" if len(eps) == 1 else ""
        cur = self.export_tab.filename.text().strip()
        if want != self._auto_name and cur in ("", self._auto_name):
            self.export_tab.filename.setText(want)
            proj.export.filename = want
        self._auto_name = want

    def _recompute_core(self) -> None:
        proj = self.collect_project()
        self._suggest_filename(proj)
        v = proj.video
        self.music_tab.mixer.set_state(self.mode, v.source_audio, bool(v.intro or v.outro) and v.bookend_audio)
        self._update_nav_badges(proj)
        self._update_audio_info(proj)
        self.music_tab.set_versions_view(max(1, proj.music.versions), self.mode == "music_only")
        if self.mode == "music_only":
            self.video_tab.set_ready("")
            self._recompute_music_only(proj)
            return
        self.video_tab.set_ready("")
        self.video_tab.set_shuffle("", [])
        self.video_tab.timeline.setEnabled(True)
        try:
            tl = timeline.build(proj)
        except Exception as e:  # noqa: BLE001
            self.export_tab.set_can_export(False)
            self._set_chips(error=f"Lỗi: {e}")
            return
        self.music_tab.mixer.set_timeline(tl.total if tl.ok else 0.0, [it.start for it in tl.music_items[1:]])
        clip_names = [Path(c.path).stem for c in proj.video.clips]
        track_paths = [t.path for t in proj.music.tracks]
        self.video_tab.timeline.set_timeline(tl if proj.video.clips else None, clip_names,
                                             [Path(t).stem for t in track_paths])
        if not proj.video.clips:
            self.export_tab.set_can_export(False)
            self.export_tab.set_empty("video")
            self._set_chips(error="Chưa có clip", neutral=True)
            self.video_tab.set_preview("Kéo thả video, ảnh hoặc thư mục vào bảng phía trên để bắt đầu.")
            self.music_tab.set_schedule([], track_paths, 0, "Kiểu “Chỉ video”: trang Nhạc đã được bỏ qua."
                                        if self.mode == "video_only" else
                                        "Thêm clip ở trang Video trước — nhạc sẽ tự lặp theo độ dài video.")
            self.export_tab.set_summary("Chưa có clip để xuất. Hãy thêm clip ở trang <b>1. Video</b>.")
            return
        if not tl.ok:
            self.export_tab.set_can_export(False)
            self._set_chips(error=" · ".join(tl.errors))
            self.video_tab.set_preview("\n".join(tl.errors + tl.warnings))
            self.music_tab.set_schedule([], track_paths, 0, "Chưa tính được lịch phát: " + " ".join(tl.errors))
            self.export_tab.set_summary("<span style='color:" + theme.T["danger_text"] + "'>" + "<br>".join(tl.errors) + "</span>")
            return
        self.export_tab.set_can_export(True)
        self._update_ready(proj, tl)
        v = tl.video
        first = next((c for c in proj.video.clips if c.enabled), None)
        info = tl.clip_infos.get(proj.video.clips.index(first)) if first else None
        if first and info is not None and info.ok:
            mid = first.trim_start + max(0.0, info.duration - first.trim_start - first.trim_end) / 2
            self.video_tab.look.set_preview_source(first.path, info.is_image, mid, tl.width, tl.height,
                                                   proj.video.fit)
        self._set_chips(seq=v.sequence_seconds, rounds=v.rounds, plays=v.body_plays, total=tl.total,
                        warnings=tl.warnings)
        self._update_shuffle(proj, v, clip_names)
        preview = planner.describe_rounds(v, clip_names)
        if tl.warnings:
            preview = "\n".join("Cảnh báo: " + w for w in tl.warnings) + "\n\n" + preview
        self.video_tab.set_preview(preview)

        vs = proj.video
        if self.mode == "video_only":
            banner = ("Chế độ <b>Chỉ video</b>: không dùng playlist nhạc. Có thể thêm <b>tiếng nền</b> (mưa, sóng, "
                      "gió…) ở cột phải — tự lặp hết video.")
        elif vs.source_audio == "only":
            banner = "Đang ở chế độ <b>chỉ tiếng gốc của clip</b> — playlist nhạc được bỏ qua."
        elif not tl.use_music:
            banner = "Chưa có bài nào được bật. Thêm nhạc vào bảng bên dưới — nhạc sẽ tự lặp theo độ dài video."
        elif vs.length_mode == "music":
            banner = (f"Video đang chạy <b>theo độ dài nhạc</b>: 1 lượt playlist = "
                      f"<b>{fmt_dur(tl.total)}</b>.")
        else:
            one = planner.rounds_seconds(proj.music, tl.track_durations, 1)
            n_songs = len(tl.track_durations)
            if n_songs == 1:
                how = f"1 bài dài {fmt_dur(one)} → phát lặp <b>{tl.total / one:.1f} lần</b>" if one else ""
            elif one and tl.total > one:
                how = f"playlist {n_songs} bài dài {fmt_dur(one)} → phát <b>{tl.total / one:.1f} lượt</b>"
            else:
                how = (f"playlist {n_songs} bài dài {fmt_dur(one)} dài hơn video → chỉ kịp phát "
                       f"<b>{len(tl.music_items)} bài</b>")
            banner = (f"Nhạc <b>tự lặp theo độ dài video ({fmt_dur(tl.total)})</b>: {how} "
                      f"({len(tl.music_items)} lượt bài), bài cuối nhỏ dần khi video kết thúc.")
        if tl.ambient_infos:
            banner += f" · {len(tl.ambient_infos)} lớp tiếng nền."
        self.music_tab.set_schedule(tl.music_items, track_paths, tl.total, banner)

        parts = (["nhạc"] if tl.use_music else []) + (["tiếng gốc"] if tl.use_source else []) \
            + (["tiếng nền"] if tl.ambient_infos else [])
        lines = [f"<b>Video {tl.width}×{tl.height} · {float(tl.fps):g} fps</b> · Tổng thời lượng: <b>{fmt_dur(tl.total)}</b> · "
                 f"Âm thanh: <b>{' + '.join(parts) or 'không có'}</b>",
                 f"Ổ lưu: {self.export_tab.free_space_text() or 'chưa chọn thư mục'} · {self.export_tab.gpu_text()}"]
        if tl.warnings:
            lines.append("<span style='color:" + theme.T["warn_text"] + "'>Lưu ý: " + "<br>Lưu ý: ".join(tl.warnings) + "</span>")
        self.export_tab.set_summary("<br>".join(lines))
        self.export_tab.set_format(tl.width, tl.height, float(tl.fps))
        m = tl.main_info
        self.export_tab.set_source((m.width, m.height, float(timeline.snap_fps(m.fps))) if m else None,
                                   (tl.width, tl.height, float(tl.fps)))
        self._schedule_size(proj, tl)

    # ---------- dự đoán dung lượng ----------
    def _schedule_size(self, proj: Project, tl) -> None:
        self._size_pending = (copy.deepcopy(proj), tl)
        self._size_gen += 1  # cấu hình đã đổi: bỏ kết quả của lượt đo đang chạy
        if self._size_runner:
            self._size_runner.cancel()
        self.export_tab.set_size(self._size_text or "Đang đo…",
                                 "Đang mã hoá thử từng clip với cấu hình vừa chọn để tính dung lượng…", busy=True)
        self._size_timer.start()

    def _run_size(self) -> None:
        if self._size_pending is None or self._closing:
            return
        if self.export_tab.available is None:
            return  # chờ kiểm tra card đồ hoạ xong (sẽ tự tính lại)
        if self.job:  # đang xuất: không tranh GPU với lượt xuất
            self.export_tab.set_size(self._size_text or "—", "Đang xuất file — sẽ đo lại khi xuất xong.", busy=True)
            return
        proj, tl = self._size_pending
        self._size_pending = None
        self._size_gen += 1
        gen = self._size_gen
        if self._size_runner:
            self._size_runner.cancel()
        runner = self._size_runner = size_estimate.Group()
        available = self.export_tab.available

        def work():
            try:
                try:
                    est = size_estimate.estimate(proj, tl, available, runner)
                except CancelledError:
                    return
                except Exception as e:  # noqa: BLE001
                    self.bridge.size.emit(gen, None, str(e))
                    return
                self.bridge.size.emit(gen, (est, proj, tl), "")
            except RuntimeError:  # cửa sổ đã đóng trong lúc đang đo
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_size(self, gen: int, result, err: str) -> None:
        if gen != self._size_gen or self._closing:
            return
        if result is None:
            self._size_text = ""
            self.export_tab.set_size("—", f"Chưa đo được dung lượng: {err[:200]}")
            self._set_size_chip("")
            return
        est, proj, tl = result
        ex = proj.export
        size = size_estimate.fmt_size(est.bytes)
        self._size_text = f"≈ {size}"
        text = f"≈ {size}   ·   hình {est.video_bps / 1e6:.1f} Mbps"
        tips = []
        warn = ""
        free = self.export_tab.free_bytes()
        if free is not None and free < est.bytes * 1.05:
            warn = f"Ổ đĩa chỉ còn {size_estimate.fmt_size(free)} — không đủ chỗ."
            tips.append(warn)
        if est.maxrate_kbps:
            tips.append(f"Đang chặn bitrate hình tối đa {est.maxrate_kbps / 1000:.1f} Mbps.")
        if ex.bitrate_cap == "size" and est.bytes < ex.cap_gb * 1024 ** 3 * 0.8:
            tips.append("Hình không cần nhiều bitrate nên file nhỏ hơn mức tối đa bạn đặt.")
        if tl.width * tl.height > 1920 * 1080 * 1.1:
            tips.append("Mẹo: chọn độ phân giải 1080p thường nhẹ hơn khoảng 2 lần (YouTube vẫn nét).")
        if encoders.PRESETS[ex.preset].codec == "h264":
            tips.append("Mẹo: chuẩn nén H.265/HEVC nhẹ hơn khoảng 20–40% với cùng độ nét.")
        if ex.quality in ("high", "very_high") and ex.bitrate_cap == "off":
            tips.append("Mẹo: chất lượng <b>Tiết kiệm dung lượng</b> hoặc <b>Bitrate hình</b> → Tự đặt bitrate "
                        "cho file nhẹ hơn.")
        tips.append(f"Đo thử bằng {est.encoder} trên {est.measured} clip · sai số thường dưới 10%.")
        self.export_tab.set_size(text, "<br>".join(tips[:3] + tips[-1:] if len(tips) > 4 else tips),
                                 warn=warn)
        self._set_size_chip(self._size_text)

    def _set_size_chip(self, text: str) -> None:
        self.chip_size.setText(text)
        self.chip_size.setToolTip("Dung lượng file xuất dự đoán (đo thử theo cấu hình ở trang Xuất)")
        self._size_wanted = bool(text)
        self._fit_chips()

    def _update_audio_info(self, proj: Project) -> None:
        try:
            tl = timeline.build_audio(proj)
        except Exception as e:  # noqa: BLE001
            self.export_tab.set_audio_info(f"Lỗi: {e}")
            self.music_tab.set_audio_info(f"Lỗi: {e}")
            return
        if not tl.ok:
            self.export_tab.set_audio_info(" ".join(tl.errors))
            self.music_tab.set_audio_info(" ".join(tl.errors))
            return
        one = planner.rounds_seconds(proj.music, tl.track_durations, 1)
        info = (f"File nhạc dài <b>{fmt_dur(tl.total)}</b> · {len(tl.music_items)} lượt bài "
                f"(1 lượt playlist = {fmt_dur(one)})") if tl.music_items else \
            f"Chỉ có tiếng nền: file dài <b>{fmt_dur(tl.total)}</b> (độ dài tính theo thời lượng)"
        self.export_tab.set_audio_info(info)
        self.music_tab.set_audio_info(info)

    def _recompute_music_only(self, proj: Project) -> None:
        n_ver = max(1, proj.music.versions)
        self.music_tab.set_versions_view(n_ver, True)
        tl = timeline.build_audio(proj, self.music_tab.preview_version())
        self.music_tab.mixer.set_timeline(tl.total if tl.ok else 0.0, [it.start for it in tl.music_items[1:]])
        track_paths = [t.path for t in proj.music.tracks]
        fmt = encoders.AUDIO_FORMATS[proj.music.export_format]
        self.video_tab.timeline.setEnabled(True)
        self.video_tab.timeline.set_timeline(tl if tl.ok and tl.music_items else None, [],
                                             [Path(t).stem for t in track_paths])
        if not tl.ok:
            self.export_tab.set_can_export(False)
            empty = not (proj.music.tracks or proj.music.ambient)
            if empty:
                self.export_tab.set_empty("music")
            self._set_chips(error="Chưa có nhạc" if empty else " · ".join(tl.errors), neutral=empty)
            self.music_tab.set_schedule([], track_paths, 0, "Chế độ <b>Chỉ nhạc</b>: thêm bài nhạc vào bảng bên dưới "
                                                           "(hoặc chỉ thêm <b>tiếng nền</b> ở cột phải). Độ dài file chỉnh ở "
                                                           "thẻ <b>Độ dài file nhạc</b>, định dạng ở trang <b>Xuất</b>.")
            self.export_tab.set_summary("Chưa có bài nhạc hoặc tiếng nền nào được bật. Hãy thêm ở trang <b>2. Nhạc</b>.")
            return
        self.export_tab.set_can_export(True)
        one = planner.rounds_seconds(proj.music, tl.track_durations, 1)
        self._set_chips(seq=one, rounds=0, plays=len(tl.music_items), total=tl.total, warnings=tl.warnings,
                        music_only=True)
        if not tl.music_items:  # chỉ tiếng nền: âm thanh môi trường / ASMR / white noise
            n_ver = 1
            banner = (f"Chế độ <b>Chỉ nhạc</b> — <b>chỉ có tiếng nền</b> ({len(tl.ambient_infos)} lớp, tự lặp liền mạch) "
                      f"dài <b>{fmt_dur(tl.total)}</b> → file {fmt.label}. Đổi độ dài ở thẻ <b>Độ dài file nhạc</b> "
                      "(tính theo thời lượng).")
        else:
            banner = (f"Chế độ <b>Chỉ nhạc</b>: playlist {len(tl.track_durations)} bài dài {fmt_dur(one)} lặp cho đủ "
                      f"<b>{fmt_dur(tl.total)}</b> ({len(tl.music_items)} lượt bài) → file {fmt.label}. "
                      "Đổi độ dài ở thẻ <b>Độ dài file nhạc</b> bên phải.")
        if n_ver > 1:
            banner += (f" · <b>{n_ver} bản</b>, mỗi bản một thứ tự phát khác nhau (đang xem "
                       f"<b>bản {self.music_tab.preview_version() + 1}</b>).")
        if tl.ambient_infos:
            banner += f" · {len(tl.ambient_infos)} lớp tiếng nền."
        if tl.warnings:
            banner += "<br><span style='color:" + theme.T["warn_text"] + "'>" + "<br>".join(tl.warnings) + "</span>"
        self.music_tab.set_schedule(tl.music_items, track_paths, tl.total, banner)
        self.export_tab.start_btn.setText(f"Xuất {n_ver} bản nhạc" if n_ver > 1 else "Bắt đầu xuất file nhạc")
        self.video_tab.set_preview("Kiểu “Chỉ nhạc” — trang Video đã được bỏ qua.")
        # byte/giây theo định dạng (FLAC tuỳ bài, lấy mức trung bình)
        size = {"mp3_320": 40_000, "flac": 110_000, "wav": 192_000}.get(proj.music.export_format, 24_000)
        est = size_estimate.fmt_size(size * tl.total)
        if n_ver > 1:
            est = f"{est} × {n_ver} bản"
        self._size_gen += 1
        self._size_pending = None
        self._size_text = f"≈ {est}"
        self.export_tab.set_size(f"≈ {est}", "Tính theo bitrate của định dạng nhạc"
                                 + (" (FLAC thay đổi theo từng bài)." if proj.music.export_format == "flac" else "."))
        self._set_size_chip(self._size_text)
        self.export_tab.set_summary(
            f"<b>File nhạc {fmt.label}</b> · Tổng thời lượng: <b>{fmt_dur(tl.total)}</b> · {len(tl.music_items)} lượt bài<br>"
            f"Dung lượng ước tính: <b>~{est}</b> ({self.export_tab.free_space_text()})")

    def _set_chips(self, seq=0.0, rounds=0, plays=0, total=0.0, warnings=(), error: str = "",
                   neutral: bool = False, music_only: bool = False) -> None:
        self._last_total, self._last_ok = (0.0, False) if error else (total, True)
        if error:
            self.chip_total.setObjectName("chip" if neutral else "chipError")
            self.chip_total.setText(error[:120])
            self.chip_total.setToolTip(error)
            self.chip_seq.setText("")
            self.chip_rounds.setText("")
            self._warn_wanted = False
            self._size_wanted = False
            self._size_pending = None
            self._size_gen += 1  # bỏ kết quả đo đang chạy dở
            self.export_tab.set_size("—")
        else:
            self.chip_total.setObjectName("chipAccent")
            new_total = f"Tổng  {fmt_dur(total)}"
            if self.chip_total.text() != new_total and self.chip_total.text().startswith("Tổng"):
                motion.fade_in(self.chip_total, 320, 0.35)  # tổng thời lượng vừa đổi: nháy nhẹ cho dễ thấy
            self.chip_total.setText(new_total)
            self.chip_total.setToolTip(
                (f"Thời lượng file nhạc: {fmt_dur(total)}\n1 lượt playlist: {fmt_dur(seq)} · {plays} lượt bài")
                if music_only else
                (f"Thời lượng video: {fmt_dur(total)}\nMột lượt các clip: {fmt_dur(seq)} · {rounds} lượt · "
                 f"{plays} lần phát clip"))
            if music_only:
                self.chip_seq.setText(f"1 lượt playlist {fmt_dur(seq)}")
                self.chip_rounds.setText(f"{plays} lượt bài")
            else:
                self.chip_seq.setText(f"Một chuỗi {fmt_dur(seq)}")
                self.chip_rounds.setText(f"{rounds} lượt · {plays} lần phát")
            self._warn_wanted = bool(warnings)
            self.chip_warn.setText(f"{len(warnings)} lưu ý")
            self.chip_warn.setToolTip("\n".join(warnings))
        self.chip_total.style().unpolish(self.chip_total)
        self.chip_total.style().polish(self.chip_total)
        self._fit_chips()
        QTimer.singleShot(0, self._fit_chips)


    # ---------- encoder ----------
    def _detect_encoders(self, force: bool = False) -> None:
        if self._closing:
            return
        if getattr(self, "_detecting", False):  # đang kiểm tra dở → bỏ qua lần bấm thêm
            return
        self._detecting = True
        if force:
            encoders.clear_cache()
        self.gpu_label.setText("Đang kiểm tra card đồ hoạ…")

        def work():
            try:
                self._detect_work()
            finally:
                self._detecting = False

        threading.Thread(target=work, daemon=True).start()

    def _detect_work(self) -> None:
        """Chạy ở luồng nền: kiểm tra encoder, thông số máy, tăng tốc phần cứng."""
        try:
            res = encoders.detect()
        except Exception:  # noqa: BLE001
            res = {c: ["cpu"] for c in encoders.ENCODERS}
        if self._closing:
            return
        try:
            self.bridge.encoders.emit(res)
            sys_info = sysinfo.gather_system()
            if self._closing:
                return
            self.bridge.system.emit(sys_info)
            acc_info = sysinfo.gather_accel()
            if self._closing:
                return
            self.bridge.accel.emit(acc_info)
        except RuntimeError:  # cửa sổ đã đóng
            pass

    def _on_accel(self, info) -> None:
        self._accel = info
        mf = "mf" in (self.export_tab.available or {}).get("audio", [])
        self.settings_page.set_accel(info, mf)
        self._apply_prefs()

    def _apply_prefs(self) -> None:
        """Áp tuỳ chọn từ trang Cài đặt."""
        sp = self.settings_page
        cuda_ok = bool(self._accel and self._accel.cuda_decode)
        ffmpeg_tools.OPTIONS["hwdec"] = "cuda" if cuda_ok and sp.pref("pref/hwdec") else ""
        try:
            pt = int(self.settings.value("pref/font_pt", 10))
        except (TypeError, ValueError):
            pt = 10
        app = QApplication.instance()
        from . import theme
        pal = str(self.settings.value("pref/palette", theme.PALETTE) or theme.PALETTE)
        if pal in theme.PALETTES and pal != theme.PALETTE:  # đổi bộ màu: dựng lại QSS, vẽ lại phần tự vẽ
            theme.apply(app, theme.FONT_PT, pal)
            for wd in QApplication.allWidgets():
                wd.update()
            branding.apply_window_frame(self)
            self.notify(f"Đã đổi màu chủ đạo: {theme.PALETTES[pal][0]}", "ok", 2500)
        if theme.FONT_PT != pt:  # áp ngay: dựng lại QSS với cỡ chữ mới (chỉ setFont thì QSS lấn át, không đổi gì)
            theme.apply(app, pt)
            self.help_page.refresh_font()
            self._compact = None  # dựng lại thanh bên theo cỡ chữ mới
            self._update_header_chips_visibility()
            QTimer.singleShot(0, lambda: self.resizeEvent(None))
            self.notify(f"Đã đổi cỡ chữ: {pt}pt", "ok", 2500)

    def _on_encoders(self, available: dict) -> None:
        self.export_tab.set_available(available)
        self.gpu_label.setText(self.export_tab.gpu_text())
        self.recompute()
        QTimer.singleShot(1500, self._maybe_resume_queue)  # cần biết card đồ hoạ rồi mới chạy được hàng đợi

    # ---------- xuất ----------
    def _check_ready(self) -> bool:
        if self.job or self._queue_running:
            QMessageBox.information(self, "Đang bận", "Đang xuất một file khác, chờ xong hoặc bấm Huỷ.")
            return False
        if self.export_tab.available is None:
            QMessageBox.information(self, "Chờ chút", "Đang kiểm tra card đồ hoạ, thử lại sau vài giây.")
            return False
        return True

    def _output_path(self, proj: Project, default_name: str, ext: str, for_queue: bool = False) -> str | None:
        ex = proj.export
        if not ex.output_dir:
            QMessageBox.warning(self, "Thiếu thư mục", "Hãy chọn thư mục lưu ở trang Xuất.")
            self.go_to(2)
            return None
        # bỏ ký tự Windows không cho phép; "Vol.3" giữ nguyên (chỉ bỏ đuôi khi đó là đuôi media)
        name = strip_ext(clean_filename(ex.filename) or default_name, ext) + ext
        if for_queue:  # không hỏi: tự thêm hậu tố để không trùng file hay mục khác trong hàng đợi
            self.settings.setValue("dir/output", ex.output_dir)
            return output_path(ex.output_dir, name, ex.own_folder,
                               {i.output.lower() for i in self.queue if not i.finished})
        out = output_path(ex.output_dir, name, ex.own_folder)
        if os.path.exists(out) and QMessageBox.question(
                self, "Ghi đè?", f"File đã tồn tại:\n{out}\n\nGhi đè?") != QMessageBox.StandardButton.Yes:
            return None
        self.settings.setValue("dir/output", ex.output_dir)
        return out

    def start_render(self) -> None:
        if self.mode == "music_only":
            self.export_audio()
            return
        if not self._check_ready():
            return
        if not self._confirm_sample_bookends():
            return
        proj = self.collect_project()
        tl = timeline.build(proj)
        if not tl.ok:
            QMessageBox.warning(self, "Chưa xuất được", "\n".join(tl.errors))
            return
        out = self._output_path(proj, default_output_name(proj), ".mp4")
        if out:
            self._start_job(RenderJob(proj, self.export_tab.available, out,
                                      on_progress=self.bridge.progress.emit, on_log=self.bridge.log.emit),
                            "video", seconds=tl.total)

    @staticmethod
    def _multi_version(proj: Project) -> bool:
        """Xuất nhiều bản chỉ có nghĩa khi có bài nhạc (chỉ tiếng nền thì mọi bản như nhau → xuất 1 file)."""
        return proj.music.versions > 1 and any(t.enabled and t.plays > 0 for t in proj.music.tracks)

    def _audio_versions(self, proj: Project, taken: set[str] | None = None) -> list[rq.QueueItem] | None:
        """Kiểu Chỉ nhạc, nhiều bản: mỗi bản là một mục hàng đợi với thứ tự phát đã chốt sẵn.
        `taken`: đường dẫn đã dùng (cả loạt xuất hàng loạt) để các bản không ghi đè lên nhau."""
        tl = timeline.build_audio(proj)
        if not tl.ok:
            QMessageBox.warning(self, "Chưa xuất được", "\n".join(tl.errors))
            return None
        ex = proj.export
        if not ex.output_dir:
            QMessageBox.warning(self, "Thiếu thư mục", "Hãy chọn thư mục lưu ở trang Xuất.")
            self.go_to(2)
            return None
        fmt = encoders.AUDIO_FORMATS[proj.music.export_format]
        name = clean_filename(ex.filename) or os.path.splitext(default_output_name(proj))[0].replace("_", "_nhac_", 1)
        seeds = tl.version_seeds or [proj.music.seed]
        used = {i.output.lower() for i in self.queue if not i.finished} | (taken or set())
        outs = render.version_outputs(ex.output_dir, name, fmt.ext, ex.own_folder, len(seeds), used)
        items = []
        for k, (seed, out) in enumerate(zip(seeds, outs)):
            p = copy.deepcopy(proj)
            p.music = planner.music_variant(p.music, seed)  # chốt thứ tự của bản này
            p.name = f"{proj.name} — bản {k + 1}"
            items.append(rq.QueueItem(project=p, output=out, kind="audio", seconds=tl.total,
                                      summary=rq.describe(p, "audio", tl.total) + f" · bản {k + 1}"))
        self.settings.setValue("dir/output", ex.output_dir)
        return items

    def export_audio(self) -> None:
        if not self._check_ready():
            return
        proj = self.collect_project()
        if self._multi_version(proj):
            items = self._audio_versions(proj)
            if not items:
                return
            self.queue.extend(items)
            self.export_tab.set_queue(self.queue)
            self._save_queue()
            self.notify(f"Đang xuất {len(items)} bản nhạc (mỗi bản một thứ tự) qua hàng đợi…", "info", 4000)
            self.run_queue(only=items)  # chỉ chạy các bản này, mục cũ đang chờ trong hàng đợi để nguyên
            return
        tl = timeline.build_audio(proj)
        if not tl.ok:
            QMessageBox.warning(self, "Chưa xuất được", "\n".join(tl.errors))
            return
        fmt = encoders.AUDIO_FORMATS[proj.music.export_format]
        base = os.path.splitext(default_output_name(proj))[0].replace("_", "_nhac_", 1)
        out = self._output_path(proj, base + fmt.ext, fmt.ext)
        if out:
            self._start_job(RenderJob(proj, self.export_tab.available, out, audio_only=True,
                                      on_progress=self.bridge.progress.emit, on_log=self.bridge.log.emit),
                            "audio")

    # ---------- hàng đợi ----------
    def _confirm_sample_bookends(self) -> bool:
        """Intro / Outro đang là file MẪU (chữ “KT Loop Station”) — hay gặp khi làm từ dự án mẫu: hỏi trước khi xuất."""
        vt = self.video_tab
        rows = [r for r in (vt.intro, vt.outro) if r.value() and is_sample_file(r.value())]
        if not rows or self.mode == "music_only":
            return True
        names = " và ".join(r.title for r in rows)
        box = QMessageBox(QMessageBox.Icon.Warning, f"{names} mẫu",
                          f"Video đang dùng <b>{names} MẪU</b> của bộ tập dùng — màn hình chữ "
                          "<b>“KT Loop Station · By Khánh Trà”</b> sẽ nằm trong video xuất ra.<br><br>"
                          "Thường là do làm tiếp từ dự án mẫu.", parent=self)
        drop = box.addButton(f"Bỏ {names.lower()} mẫu rồi xuất", QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton("Vẫn giữ", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Huỷ", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(drop)
        box.exec()
        if box.clickedButton() is drop:
            for r in rows:
                r.set_path("")
            return True
        return box.clickedButton() is keep

    def add_to_queue(self, kind: str) -> None:
        if kind == "video" and not self._confirm_sample_bookends():
            return
        proj = self.collect_project()
        if kind == "audio" and self._multi_version(proj):
            items = self._audio_versions(proj)
            if not items:
                return
            self.queue.extend(items)
            self.export_tab.set_queue(self.queue)
            self._save_queue()
            pending = sum(1 for i in self.queue if i.status == "pending")
            self.notify(f"Đã thêm {len(items)} bản nhạc vào hàng đợi — {pending} mục đang chờ.", "info", 4000)
            self.go_to(2)
            return
        tl = timeline.build(proj) if kind == "video" else timeline.build_audio(proj)
        if not tl.ok:
            QMessageBox.warning(self, "Chưa thêm được", "\n".join(tl.errors))
            return
        editing = self._editing_item if kind == "video" and self._editing_item in self.queue else None
        sig = rq.signature(proj, kind)
        twin = next((i for i in self.queue if not i.finished and i is not editing
                     and i.kind == kind and rq.signature(i.project, i.kind) == sig), None)
        if twin is not None and QMessageBox.question(
                self, "Có thể bị trùng",
                f"Video này giống hệt mục “{Path(twin.output).stem}” đang có trong hàng đợi (cùng clip, cùng số lần "
                "phát, cùng intro / outro).\n\nVẫn thêm?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        if editing is not None:  # chỉ loại đường dẫn của chính mục này khỏi danh sách trùng tên
            editing.output, keep = "", editing.output
        if kind == "video":
            out = self._output_path(proj, default_output_name(proj), ".mp4", for_queue=True)
        else:
            fmt = encoders.AUDIO_FORMATS[proj.music.export_format]
            base = os.path.splitext(default_output_name(proj))[0].replace("_", "_nhac_", 1)
            out = self._output_path(proj, base + fmt.ext, fmt.ext, for_queue=True)
        if editing is not None and not out:
            editing.output = keep
        if not out:
            return
        summary = rq.describe(proj, kind, tl.total if tl.ok else 0.0)
        if editing is not None:  # "Cập nhật …": thay đúng mục đang sửa, chạy lại từ đầu
            editing.project, editing.output, editing.summary = copy.deepcopy(proj), out, summary
            editing.seconds = tl.total if tl.ok else 0.0
            editing.status, editing.message = "pending", ""
            self._set_editing(None)
            self._save_queue()
            self.go_to(2)
            self.notify(f"Đã cập nhật mục “{Path(out).stem}” trong hàng đợi.", "ok", 4000)
            return
        self.queue.append(rq.QueueItem(project=copy.deepcopy(proj), output=out, kind=kind, summary=summary,
                                       seconds=tl.total if tl.ok else 0.0))
        self.export_tab.set_queue(self.queue)
        self._save_queue()
        if kind == "audio":
            pending = sum(1 for i in self.queue if i.status == "pending")
            self.notify(f"Đã thêm vào hàng đợi: {os.path.basename(out)} — {pending} mục đang chờ.", "info", 4000)
            self.go_to(2)
            return
        self._after_queue_add(out, summary)

    def _after_queue_add(self, out: str, summary: str) -> None:
        """Thêm xong: nói rõ đã thêm gì, lưu ở đâu, và bước tiếp theo (làm video tiếp / chạy luôn)."""
        from .queue_dialogs import QueueAddedDialog
        pending = sum(1 for i in self.queue if i.status == "pending")
        dlg = QueueAddedDialog(out, summary, pending, not (self.job or self._queue_running), self)
        dlg.exec()
        if dlg.choice == "next":
            self.next_video()
        elif dlg.choice == "run":
            self.go_to(2)
            self.run_queue()
        else:
            self.go_to(2)

    def next_video(self) -> None:
        """Làm video tiếp theo: bảng clip trống + tên file trống, giữ mọi cài đặt khác (intro / outro, nhạc, xuất…)."""
        proj = self.collect_project()
        proj.video.clips = []
        proj.export.filename = ""
        self.load_project(proj)
        self.go_to(0)
        self.notify("Bảng clip đã trống — thêm file video tiếp theo (Thư viện mẫu… để áp mẫu).", "info", 4500)

    def _set_editing(self, item: rq.QueueItem | None) -> None:
        self._editing_item = item
        self.export_tab.set_editing(item)
        banner = getattr(self, "edit_banner", None)
        if banner is not None:
            if item is not None:
                self.edit_text.setText(f"Đang sửa mục <b>“{html.escape(Path(item.output).stem)}”</b> trong hàng đợi — "
                                       "sửa xong bấm <b>Cập nhật mục</b>. Mục chỉ đổi khi bạn bấm Cập nhật.")
            banner.setVisible(item is not None)

    # ---------- tự lưu + khôi phục phiên ----------
    @staticmethod
    def _project_json(proj: Project) -> str:
        import json
        return json.dumps(proj.to_dict(None), ensure_ascii=False, sort_keys=True)

    def _autosave(self) -> None:
        """Ghi bản tự lưu khi dự án đổi; mỗi ≥ 2 phút giữ thêm một bản dự phòng (giữ 5 bản gần nhất)."""
        if not self._initial_loaded or self._closing:
            return
        proj = self.collect_project()
        text = self._project_json(proj)
        if text == self._last_saved:
            return
        data = ffmpeg_tools.data_dir()
        try:
            proj.save(str(data / AUTOSAVE))
        except OSError:
            return
        self._last_saved = text
        if time.time() - self._last_backup < BACKUP_EVERY:
            return
        self._last_backup = time.time()
        folder = data / BACKUP_DIR
        try:
            folder.mkdir(exist_ok=True)
            proj.save(str(folder / f"tu-luu_{datetime.now():%Y%m%d_%H%M%S}{PROJECT_EXT}"))
            for old in sorted(folder.glob(f"tu-luu_*{PROJECT_EXT}"))[:-BACKUP_KEEP]:
                old.unlink(missing_ok=True)
        except OSError:
            pass

    def _open_backup(self) -> None:
        folder = ffmpeg_tools.data_dir() / BACKUP_DIR
        folder.mkdir(exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(self, "Mở bản tự lưu (tên file = ngày giờ lưu)", str(folder),
                                              f"Dự án {APP_NAME} (*{PROJECT_EXT})")
        if not path:
            return
        try:
            proj = Project.load(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Không mở được", str(e))
            return
        self.load_project(proj)
        self.restore_banner.setVisible(False)
        self.notify(f"Đã mở bản tự lưu {Path(path).stem.removeprefix('tu-luu_')}.", "ok", 4000)

    def _maybe_resume_queue(self) -> None:
        """Lần trước app tắt ngang lúc hàng đợi đang chạy: hỏi chạy tiếp (đếm ngược 60 giây rồi tự chạy)."""
        if getattr(self, "_resume_asked", False) or self._closing:
            return
        self._resume_asked = True
        if str(self.settings.value("queue/was_running", "")) != "running":
            return
        pending = [i for i in self.queue if i.status == "pending"]
        self.settings.setValue("queue/was_running", "")
        if not pending or self.job or self._queue_running:
            return
        from .queue_dialogs import ResumeQueueDialog
        dlg = ResumeQueueDialog([Path(i.output).stem for i in pending], 60, self)
        dlg.exec()
        if dlg.run:
            self.go_to(2)
            self.run_queue()

    def _check_disk(self) -> None:
        """Ổ chứa bộ nhớ đệm / thư mục lưu còn dưới ~8 GB: hiện dải cảnh báo (xuất video dài dễ lỗi thiếu chỗ)."""
        if self._closing or self._disk_hidden:
            return
        from .settings_page import LOW_DISK
        places: dict[str, tuple[str, str]] = {}
        root = ffmpeg_tools.cache_root()
        places[os.path.splitdrive(str(root))[0].upper() or str(root)] = ("bộ nhớ đệm", str(root))
        out = self.export_tab.out_dir.text().strip()
        if out and os.path.isdir(os.path.splitdrive(out)[0] + os.sep):
            places.setdefault(os.path.splitdrive(out)[0].upper(), ("thư mục lưu video", out))
        low = []
        for drive, (what, path) in places.items():
            free = ffmpeg_tools.disk_free(path if os.path.exists(path) else drive + os.sep)
            if 0 <= free < LOW_DISK:
                low.append(f"Ổ <b>{drive}</b> chỉ còn <b>{free / 1024 ** 3:.1f} GB</b> trống (đang chứa {what})")
        if not low:
            self.disk_banner.setVisible(False)
            return
        self.disk_text.setText(" · ".join(low) + " — xuất video dài có thể lỗi thiếu chỗ. Chuyển bộ nhớ đệm sang ổ "
                               "khác hoặc dọn bớt.")
        for b in self._disk_buttons:
            b.setEnabled(self.job is None and not self._queue_running)
        self.disk_banner.setVisible(True)

    def _hide_disk_banner(self) -> None:
        self._disk_hidden = True  # tới lần mở app sau
        self.disk_banner.setVisible(False)

    def _cancel_edit(self) -> None:
        item = self._editing_item
        self._set_editing(None)
        self._schedule()  # nút trên dải Sẵn sàng về lại "Thêm vào hàng đợi"
        if item is not None:
            self.notify(f"Đã thôi sửa — “{Path(item.output).stem}” trong hàng đợi giữ nguyên.", "info", 3500)

    def _edit_queue_item(self, index: int) -> None:
        """"Sửa mục này": mở lại mục ở trang Video; nút Thêm thành "Cập nhật …" để lưu vào đúng mục đó."""
        if not 0 <= index < len(self.queue) or self.queue[index].status == "running":
            return
        item = self.queue[index]
        if QMessageBox.question(
                self, "Sửa mục hàng đợi",
                f"Mở lại “{Path(item.output).stem}” để sửa?\n\nBảng clip và cài đặt đang mở sẽ được thay bằng mục "
                "này (lưu dự án trước nếu cần). Sửa xong bấm “Cập nhật …” ở trang Xuất.") \
                != QMessageBox.StandardButton.Yes:
            return
        self.load_project(copy.deepcopy(item.project), editing=item)
        self.go_to(0)
        self.notify(f"Đang sửa “{Path(item.output).stem}” — sửa xong bấm Cập nhật mục (dải tím phía trên).", "info", 5000)

    def batch_from_folders(self) -> None:
        """Mỗi thư mục con = một video, dựng theo dự án đang mở làm khuôn rồi thêm cả loạt vào hàng đợi."""
        from .batch_dialog import BatchDialog
        if not self._confirm_sample_bookends():  # cả loạt lấy Intro / Outro theo dự án đang mở
            return
        template = self.collect_project()
        if not template.export.output_dir:
            QMessageBox.warning(self, "Thiếu thư mục lưu", "Chọn thư mục lưu ở trang Xuất trước — cả loạt sẽ "
                                "xuất vào đó (mỗi video một thư mục riêng nếu đang bật).")
            self.go_to(2)
            return
        self.viewer.player.pause()  # hộp thoại hàng loạt có trình phát riêng: không phát chồng phía sau
        dlg = BatchDialog(template, self.settings, self)  # đổi kiểu (Video có nhạc / Chỉ video / Chỉ nhạc) ngay trong hộp thoại
        dlg.exec()
        if dlg.result() != QDialog.DialogCode.Accepted or not dlg.result_projects:
            return
        taken = {i.output.lower() for i in self.queue if not i.finished}
        added = []
        for p in dlg.result_projects:
            if p.output_kind == "music_only":
                p.export.filename = p.export.filename or p.name
                if self._multi_version(p):
                    items = self._audio_versions(p, taken) or []
                else:
                    fmt = encoders.AUDIO_FORMATS[p.music.export_format]
                    out = output_path(p.export.output_dir, p.export.filename + fmt.ext, p.export.own_folder, taken)
                    items = [rq.QueueItem(project=p, output=out, kind="audio")]
            else:
                out = output_path(p.export.output_dir, p.export.filename + ".mp4", p.export.own_folder, taken)
                items = [rq.QueueItem(project=p, output=out, kind="video")]
            for it in items:
                taken.add(it.output.lower())
                try:
                    tl = timeline.build_audio(it.project) if it.kind == "audio" else timeline.build(it.project)
                    it.summary = rq.describe(it.project, it.kind, tl.total if tl.ok else 0.0)
                    it.seconds = it.seconds or (tl.total if tl.ok else 0.0)
                except Exception:  # noqa: BLE001 — tóm tắt chỉ để xem, không chặn việc thêm
                    it.summary = rq.describe(it.project, it.kind)
            added += items
        if not added:
            return
        self.queue.extend(added)
        self.export_tab.set_queue(self.queue)
        self._save_queue()
        self.go_to(2)
        self.notify(f"Đã thêm {len(added)} mục từ thư mục vào hàng đợi.", "ok", 4000)
        if dlg.run_now.isChecked():
            self.run_queue()

    def run_queue(self, only: list | None = None) -> None:
        if not self._check_ready():
            return
        if not any(i.status == "pending" for i in self.queue):
            QMessageBox.information(self, "Hàng đợi trống", "Chưa có mục nào đang chờ. Bấm 'Thêm vào hàng đợi' "
                                    "ở trang Xuất để thêm (kiểu Chỉ nhạc thì thêm file nhạc).")
            return
        self._queue_only = {id(i) for i in only} if only else None
        self._pause_after = False
        self.export_tab.set_paused(False)
        self.settings.setValue("queue/was_running", "running")  # app bị tắt ngang lúc này → lần mở sau hỏi chạy tiếp
        self._queue_running = True
        self._queue_results = []
        self._run_next()

    def _run_next(self) -> None:
        if self.job or self._closing:
            return
        only = self._queue_only
        if self._pause_after and self._queue_results:  # "Tạm dừng sau video này": dừng êm, chạy tiếp lúc nào cũng được
            self.settings.setValue("queue/was_running", "")
            self._pause_after = False
            self._queue_running = False
            self._queue_item = None
            self._queue_only = None
            self.export_tab.set_running(False)
            self.export_tab.set_paused(False)
            self.accent_line.set_running(False)
            left = sum(1 for i in self.queue if i.status == "pending")
            self.export_tab.on_progress(0, f"Đã tạm dừng hàng đợi — còn {left} video. Bấm Chạy hàng đợi để chạy tiếp.")
            self.notify(f"Đã tạm dừng hàng đợi — còn {left} video chờ.", "info", 5000)
            self._refresh_eta()
            QTimer.singleShot(300, self._update_power)
            return
        item = next((i for i in self.queue if i.status == "pending" and (only is None or id(i) in only)), None)
        if item is None:
            self.settings.setValue("queue/was_running", "")
            self._queue_running = False
            self._queue_item = None
            self._queue_only = None
            self.export_tab.set_running(False)
            self.accent_line.set_running(False)
            ok = self._queue_results.count("done")
            bad = len(self._queue_results) - ok
            QApplication.alert(self)
            last = next((i.output for i in reversed(self.queue) if i.status == "done"), None)
            if ok and last:  # chỉ báo / mở thư mục khi lượt chạy này có mục thành công
                self._after_success(last)
            self.export_tab.set_paused(False)
            self._refresh_eta()
            self._windows_notice("Hàng đợi xong", f"{ok} video xong" + (f", {bad} lỗi" if bad else "") + ".")
            if self.settings_page.shutdown.isChecked():
                self._shutdown_countdown(ok, bad)
                return
            self.export_tab.on_progress(1.0, f"Hàng đợi xong: {ok} thành công, {bad} lỗi.")
            QMessageBox.information(self, "Hàng đợi xong", f"Đã chạy xong hàng đợi: {ok} thành công, {bad} lỗi.")
            return
        item.status, item.message = "running", ""
        self._queue_item = item
        self.export_tab.set_queue(self.queue)
        self._save_queue()
        self.export_tab.append_log(f"===== Hàng đợi: {item.project.name} → {item.output} =====")
        self._start_job(RenderJob(item.project, self.export_tab.available, item.output,
                                  audio_only=item.kind == "audio",
                                  on_progress=self.bridge.progress.emit, on_log=self.bridge.log.emit),
                        "queue", clear_log=False, seconds=item.seconds if item.kind == "video" else 0.0)

    def _after_success(self, output: str) -> None:
        sp = self.settings_page
        if sp.pref("pref/beep", True):
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:  # noqa: BLE001
                pass
        if sp.pref("pref/open_folder", True) and os.path.exists(output):
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(output)])
        sp.refresh_cache()

    def _shutdown_countdown(self, ok: int, bad: int) -> None:
        import subprocess
        self._save_queue()  # lưu trước khi Windows tắt máy (có thể không kịp đóng app bình thường)
        try:
            self.collect_project().save(str(ffmpeg_tools.data_dir() / AUTOSAVE))
        except Exception:  # noqa: BLE001
            pass
        subprocess.run(["shutdown", "/s", "/t", "120", "/c",
                        f"{APP_NAME}: hàng đợi xong ({ok} thành công, {bad} lỗi). Máy sẽ tắt sau 2 phút."],
                       creationflags=ffmpeg_tools.CREATE_NO_WINDOW)
        box = QMessageBox(self)
        box.setWindowTitle("Sắp tắt máy")
        box.setText(f"Hàng đợi xong: {ok} thành công, {bad} lỗi.\nMáy sẽ tự tắt sau 2 phút.")
        cancel = box.addButton("Huỷ tắt máy", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is cancel:
            subprocess.run(["shutdown", "/a"], creationflags=ffmpeg_tools.CREATE_NO_WINDOW)
            self.settings_page.shutdown.setChecked(False)

    def _save_queue(self) -> None:
        try:
            rq.save(self.queue, ffmpeg_tools.data_dir() / QUEUE_FILE)
        except OSError:
            pass
        self._refresh_eta()

    # ---------- hàng đợi: giờ xong, tạm dừng, thông báo ----------
    def _speed_ratio(self) -> float:
        """Giây máy làm cho mỗi giây video (đo từ các lần xuất trước). 0 = chưa đo."""
        try:
            return float(self.settings.value("perf/ratio", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _refresh_eta(self, frac: float = 0.0) -> None:
        """Dòng "Còn 3 video · ~25 phút · xong khoảng 23:40" trên hàng đợi + ước tính từng mục đang chờ."""
        ratio = self._speed_ratio()
        pend = [i for i in self.queue if i.status == "pending"]
        run = self._queue_item if self._queue_running and self._queue_item in self.queue else None
        self.export_tab.set_eta_ratio(ratio)
        if not pend and run is None:
            self.export_tab.set_queue_eta("")
            return
        n = len(pend) + (1 if run else 0)
        left = sum(i.seconds for i in pend) + (run.seconds * (1 - frac) if run else 0.0)
        if ratio <= 0 or left <= 0:
            self.export_tab.set_queue_eta(f"Còn {n} video · giờ xong sẽ hiện sau lần xuất đầu tiên (app đo tốc độ máy)")
            return
        sec = left * ratio
        done_at = datetime.now() + timedelta(seconds=sec)
        day = "" if done_at.date() == datetime.now().date() else " ngày mai" \
            if (done_at.date() - datetime.now().date()).days == 1 else f" {done_at:%d/%m}"
        self.export_tab.set_queue_eta(f"Còn <b>{n} video</b> · {rq.eta_text(sec)} · xong khoảng <b>{done_at:%H:%M}"
                                      f"{day}</b>" + ("" if self._queue_running else " (nếu bấm Chạy ngay)"))

    def _record_speed(self) -> None:
        """Xuất video xong: cập nhật tỉ lệ thời gian làm / độ dài video (trung bình trượt, bỏ lần quá lệch)."""
        secs = getattr(self, "_job_secs", 0.0)
        if secs <= 30:
            return
        r = (time.time() - self._job_t0) / secs
        old = self._speed_ratio()
        new = r if old <= 0 else old * 0.6 + r * 0.4
        self.settings.setValue("perf/ratio", round(new, 5))

    def _toggle_pause(self) -> None:
        self._pause_after = not self._pause_after
        self.export_tab.set_paused(self._pause_after)
        if self._pause_after:
            self.notify("Hàng đợi sẽ dừng sau khi xong video đang chạy.", "info", 4000)

    def _windows_notice(self, title: str, text: str) -> None:
        """Thông báo của Windows (góc màn hình) — người dùng đi đâu cũng biết hàng đợi đã xong."""
        from PySide6.QtWidgets import QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = getattr(self, "_tray", None)
        if tray is None:
            tray = self._tray = QSystemTrayIcon(self.windowIcon(), self)
            tray.setToolTip(APP_NAME)
            tray.messageClicked.connect(lambda: (self.showNormal(), self.raise_(), self.activateWindow()))
        tray.show()
        tray.showMessage(f"{APP_NAME} — {title}", text, QSystemTrayIcon.MessageIcon.Information, 10000)
        QTimer.singleShot(30000, tray.hide)

    # ---------- Bảng trộn âm: nghe thử 20 giây ----------
    def _help_action(self, act: str) -> None:
        """Nút “Mở …” trong trang Hướng dẫn → đi tới đúng chỗ."""
        pages = {"home": HOME_PAGE, "video": 0, "music": 1, "export": 2, "settings": 3}
        if act in pages:
            if act == "video" and self.mode == "music_only":
                self.set_mode("video_music")
            self.go_to(pages[act])
        elif act == "mixer":
            self._open_mixer()
        elif act == "batch":
            self.batch_from_folders()
        elif act == "preview":
            self.open_preview()
        elif act == "interleave":
            if self.mode == "music_only":
                self.set_mode("video_music")
            self.go_to(0)
            QTimer.singleShot(200, self.video_tab._open_interleave)
        elif act == "ambient_lib":
            self.go_to(1)
            QTimer.singleShot(200, self.music_tab._open_ambient_library)
        elif act == "mode_music":
            self.set_mode("music_only")
            self.go_to(1)
        elif act == "welcome":
            self.show_welcome()

    def _update_ready(self, proj: Project, tl) -> None:
        """Dải "Sẵn sàng" ở trang Video: nhìn một chỗ biết video sẽ ra sao, thêm vào hàng đợi ngay tại đó."""
        v = proj.video
        bits = [rq.describe(proj, "video", tl.total)]
        ends = [x for x, on in (("Intro", v.intro), ("Outro", v.outro)) if on]
        bits.append(" + ".join(ends) if ends else "không intro / outro")
        n_music = sum(1 for t in proj.music.tracks if t.enabled)
        if self.mode == "video_music" and v.source_audio != "only":
            bits.append(f"nhạc {n_music} bài" if n_music else "chưa có nhạc")
        heard = sorted(k for k, on in tl.audible.items() if on and k >= 0)
        n_heard = len({tl.clip_infos[k].path for k in heard if k in tl.clip_infos})
        src = {"mix": "giữ tiếng gốc", "only": "chỉ tiếng gốc", "off": "tắt tiếng gốc"}.get(v.source_audio, "")
        bits.append(src + (f" ({n_heard} file có tiếng)" if v.source_audio != "off" and n_heard else ""))
        name = proj.export.filename.strip() or "tên tự đặt"
        where = "" if proj.export.output_dir else \
            f" <span style='color:{theme.css_color('warn_text')}'>· chưa chọn thư mục lưu (trang Xuất)</span>"
        item = self._editing_item
        self.video_tab.set_ready(f"<b>Sẵn sàng:</b> {html.escape(' · '.join(bits))} → <b>{html.escape(name)}.mp4</b>"
                                 + where, f"Cập nhật “{Path(item.output).stem}”" if item else "Thêm vào hàng đợi")
        names = [Path(tl.clip_infos[k].path).stem for k in heard if k in tl.clip_infos]
        self.music_tab.mixer.set_sources(list(dict.fromkeys(names)), len({c.path for c in v.clips if c.enabled}))

    def _update_shuffle(self, proj: Project, plan, names: list[str]) -> None:
        """Trộn ngẫu nhiên: hiện ngay thứ tự sẽ xuất (lượt đầu) thay vì "xáo khi xuất" mù mờ."""
        if proj.video.order != "shuffle":
            self.video_tab.set_shuffle("", [])
            return
        order = planner.round_order(plan)
        if not order:
            self.video_tab.set_shuffle("", [])
            return
        shown = order[:6]  # dải chỉ tóm tắt; đủ cả 40–50 clip ở cửa sổ "Xem đủ thứ tự"
        parts = [f"<b>{k}.</b> {html.escape(names[c])}" + (f" ×{n}" if n > 1 else "") for k, (c, n) in enumerate(shown, 1)]
        more = f" → … (+{len(order) - len(shown)})" if len(order) > len(shown) else ""
        rounds = plan.rounds or 1
        tail = ""
        if rounds > 1:
            tail = (" · mỗi lượt lặp lại xáo thứ tự mới" if proj.video.reshuffle_each_round
                    else f" · {rounds} lượt cùng thứ tự này")
        self.video_tab.set_shuffle(f"<b>Thứ tự sẽ xuất</b> (số mầm {proj.video.seed}{tail}): " + " → ".join(parts) + more,
                                   [c for c, _n in order], f"Xem đủ thứ tự ({len(order)} dòng)…")

    def _shuffle_data(self, round_idx: int = 0) -> dict | None:
        """Thứ tự một lượt trộn để xem trong cửa sổ riêng: (tên, số lần, giây bắt đầu ≈, giây dài) mỗi dòng."""
        proj = self.collect_project()
        try:
            tl = timeline.build(proj)
        except Exception:  # noqa: BLE001
            return None
        if not tl.ok or tl.video is None:
            return None
        plan, vs = tl.video, proj.video

        def play_len(k: int) -> float:
            info = tl.clip_infos.get(k)
            if info is None or not info.ok:
                return 0.0
            if info.is_image:
                return vs.image_duration
            c = vs.clips[k] if 0 <= k < len(vs.clips) else None
            return max(0.1, info.duration - (c.trim_start + c.trim_end if c else 0.0))

        rows, order, t = [], [], 0.0
        for clip, n, rnd in plan.all_plays():
            d = play_len(clip) * n
            if rnd == round_idx and clip >= 0:
                if order and order[-1] == clip:
                    name, n0, s0, d0, p0 = rows[-1]
                    rows[-1] = (name, n0 + n, s0, d0 + d, p0)
                else:
                    rows.append((Path(vs.clips[clip].path).stem, n, t, d, vs.clips[clip].path))
                    order.append(clip)
            t += d
        rounds = (plan.rounds or 1) if vs.reshuffle_each_round else 1
        return {"title": f"Thứ tự sẽ xuất — {len(rows)} dòng (số mầm {vs.seed})", "rows": rows, "order": order,
                "rounds": rounds}

    def _show_shuffle_order(self) -> None:
        import random
        from .shuffle_dialog import ShuffleOrderDialog
        vt = self.video_tab
        dlg = ShuffleOrderDialog(self._shuffle_data, lambda: vt.seed.setValue(random.randint(0, 999_999)),
                                 vt._freeze_order, self)
        dlg.exec()

    # ---------- hồ sơ kênh ----------
    def _set_profile_label(self, name: str) -> None:
        short = name if len(name) <= 18 else name[:17] + "…"
        self._profile_text = f"Kênh: {short}" if name else "Kênh: chưa chọn"
        self.profile_btn.setToolTip(f"{self._profile_text} — hồ sơ kênh: mỗi kênh một bộ cài đặt (intro / outro, logo, "
                                    "nhạc, mẫu, nơi lưu…)")
        if self.profile_btn.text() or not getattr(self, "_profile_collapsed", False):
            self.profile_btn.setText(self._profile_text)

    def _fill_profile_menu(self) -> None:
        from .share_io import read_profiles
        m = self.profile_menu
        m.clear()
        cur = str(self.settings.value("profiles/last", "") or "")
        items = read_profiles(self.settings)
        for p in items:
            act = m.addAction(p["name"], lambda p=p: self._apply_profile(p))
            act.setCheckable(True)
            act.setChecked(p["name"] == cur)
        if not items:
            m.addAction("Chưa có hồ sơ nào").setEnabled(False)
        m.addSeparator()
        m.addAction(icons.icon("plus", 14), "Lưu cài đặt hiện tại thành hồ sơ…", self._new_profile)
        m.addAction(icons.icon("settings", 14), "Quản lý hồ sơ kênh…", self._open_profiles)

    def _capture_profile(self, name: str) -> dict:
        from ..core import profiles as prof
        return prof.capture(name, self.collect_project(), str(self.settings.value("table/last", "") or ""))

    def _new_profile(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        from .share_io import read_profiles, write_profiles
        name, ok = QInputDialog.getText(self, "Lưu thành hồ sơ kênh", "Tên kênh (ví dụ: Kênh Mưa Đêm):")
        name = name.strip()
        if not ok or not name:
            return
        items = read_profiles(self.settings)
        if any(p["name"] == name for p in items) and QMessageBox.question(
                self, "Hồ sơ kênh", f"Đã có hồ sơ “{name}”. Ghi đè?") != QMessageBox.StandardButton.Yes:
            return
        write_profiles(self.settings, [p for p in items if p["name"] != name] + [self._capture_profile(name)])
        self.settings.setValue("profiles/last", name)
        self._set_profile_label(name)
        self.notify(f"Đã lưu hồ sơ kênh “{name}” — lần sau chọn ở nút Kênh trên cùng.", "ok", 4000)

    def _open_profiles(self) -> None:
        from .profiles_dialog import ProfileDialog
        ProfileDialog(self.settings, self._capture_profile, self._apply_profile,
                      str(self.settings.value("profiles/last", "") or ""), self).exec()

    def _apply_profile(self, p: dict) -> None:
        """Áp hồ sơ kênh vào dự án đang mở: intro / outro, màu & logo, âm thanh, nhạc, tiếng nền, mẫu bảng, xuất.
        Bảng clip + tên file giữ nguyên."""
        from ..core import profiles as prof
        new, notes = prof.apply(p, self.collect_project())
        self.load_project(new, editing=self._editing_item)
        if p.get("table_preset"):
            self.settings.setValue("table/last", p["table_preset"])  # thả file sau đó: tự áp đúng mẫu của kênh
        self.settings.setValue("profiles/last", p["name"])
        self._set_profile_label(p["name"])
        self.notify(f"Đã áp hồ sơ kênh “{p['name']}”: {prof.describe(p)}", "ok", 5000)
        if notes:
            QMessageBox.warning(self, "Hồ sơ kênh", "Đã áp hồ sơ, nhưng có vài thứ không còn trên máy này:\n\n• "
                                + "\n• ".join(notes))

    def _set_source_mode(self, mode: str) -> None:
        """Bảng trộn âm đổi kiểu tiếng gốc → đồng bộ ô Tiếng gốc clip ở trang Video (một nguồn sự thật)."""
        cb = self.video_tab.source
        i = cb.findData(mode)
        if i >= 0 and cb.model().item(i).isEnabled():
            cb.setCurrentIndex(i)

    def _season_dropped(self, paths: list, preset_name: str) -> None:
        """Thả file của nhiều tập: hỏi một câu → đưa cả mùa vào hàng đợi (mỗi tập một video) hoặc làm một tập."""
        from ..core import table_preset as tp
        from .interleave_dialog import all_table_presets
        from .queue_dialogs import QueueAddedDialog, SeasonDialog
        preset = next((p for p in all_table_presets(self.settings) if p["name"] == preset_name), None)
        if preset is None:
            return
        rows, groups = preset["rows"], tp.by_episode(paths)
        desc = []
        for ep, files in groups.items():
            clips, missing = tp.build(rows, files, ep)
            stts = sorted({n for n in map(tp.stt_of, files) if n is not None})
            d = (f"tình huống {stts[0]} → {stts[-1]} · " if len(stts) > 1 else "") + f"{len(clips)} dòng"
            if missing:
                d += " · thiếu " + ", ".join(tp.missing_names(rows, missing, files)[:2])
            desc.append((ep, d))
        dlg = SeasonDialog(desc, preset_name, self.export_tab.out_dir.text().strip(), self)
        dlg.exec()
        if dlg.choice == "one":
            clips, _missing = tp.build(rows, groups.get(dlg.episode, []), dlg.episode)
            _c, infos, _d = self.video_tab._table_media()
            self.video_tab._apply_arranged(clips, infos, f"Tập {dlg.episode} — mẫu “{preset_name}”")
            self.settings.setValue("table/last", preset_name)
            return
        if dlg.choice != "all" or not self._confirm_sample_bookends():
            return
        if not self.export_tab.out_dir.text().strip():
            d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu cả mùa", self.settings.value("dir/output", ""))
            if not d:
                return
            self.export_tab.out_dir.setText(d)
        template = self.collect_project()
        taken = {i.output.lower() for i in self.queue if not i.finished}
        added = []
        for ep, files in groups.items():
            p = copy.deepcopy(template)
            p.video.clips = tp.build(rows, files, ep)[0]
            if not p.video.clips:
                continue
            p.export.filename = f"Tập {ep}"
            out = output_path(p.export.output_dir, p.export.filename + ".mp4", p.export.own_folder, taken)
            taken.add(out.lower())
            secs = 0.0
            try:
                tl = timeline.build(p)
                secs = tl.total if tl.ok else 0.0
                summary = rq.describe(p, "video", secs)
            except Exception:  # noqa: BLE001 — tóm tắt chỉ để xem
                summary = rq.describe(p, "video")
            added.append(rq.QueueItem(project=p, output=out, kind="video", summary=summary, seconds=secs))
        if not added:
            return
        self.settings.setValue("table/last", preset_name)
        self.settings.setValue("dir/output", template.export.output_dir)
        self.queue.extend(added)
        self.export_tab.set_queue(self.queue)
        self._save_queue()
        cleared = self.collect_project()  # bảng trống chờ mùa sau, giữ mọi cài đặt
        cleared.video.clips, cleared.export.filename = [], ""
        self.load_project(cleared)
        pending = sum(1 for i in self.queue if i.status == "pending")
        box = QueueAddedDialog(template.export.output_dir, "", pending, not (self.job or self._queue_running), self,
                               lines=[f"<b>{html.escape(Path(i.output).stem)}</b> — {html.escape(i.summary)}"
                                      for i in added], name=f"{len(added)} tập đã vào hàng đợi")
        box.exec()
        if box.choice == "run":
            self.go_to(2)
            self.run_queue()
        elif box.choice == "next":
            self.go_to(0)
        else:
            self.go_to(2)

    def _open_mixer(self) -> None:
        self.go_to(1)
        QTimer.singleShot(250, lambda: self._scroll_to(self.music_tab.mixer))

    def _mixer_settled(self) -> None:
        """Ngừng kéo thanh âm lượng 1,2 giây: tính lại (đang nghe thử thì đợi nghe xong)."""
        if self.music_tab.mixer.is_playing():
            self._mixer_dirty = True
            return
        self._mixer_dirty = False
        self._schedule()

    def _mixer_stopped(self) -> None:
        if self._mixer_dirty:
            self._mixer_dirty = False
            self._schedule()

    def preview_audio(self, start: float) -> None:
        """Trộn nhanh 20 giây ở luồng nền (không cần card đồ hoạ, chạy được cả khi đang xuất) rồi phát trong app."""
        from ..core import audio_preview
        proj = self.collect_project()
        if self._audio_prev_runner:
            self._audio_prev_runner.cancel()
        runner = self._audio_prev_runner = ffmpeg_tools.Runner()
        version = self.music_tab.preview_version()
        self.music_tab.mixer.set_busy(True)

        def work():
            import shutil
            from .live_mix import read_pcm
            try:
                st = audio_preview.render_stems(proj, start, runner, version)
                try:
                    data = {k: read_pcm(f) for k, f in st.files.items()}  # đọc hết vào RAM (~4 MB / kênh)
                finally:
                    shutil.rmtree(st.folder, ignore_errors=True)
            except CancelledError:
                return
            except Exception as e:  # noqa: BLE001
                if not runner.cancelled:
                    self.bridge.audio_preview.emit(None, str(e))
                return
            if not runner.cancelled:
                self.bridge.audio_preview.emit((data, st.start), "")

        threading.Thread(target=work, daemon=True).start()

    def _on_audio_preview(self, payload, err: str) -> None:
        if self._closing:
            return
        if err or not payload:
            self.music_tab.mixer.show_error("Chưa nghe thử được: " + (err or "lỗi").strip().splitlines()[-1][:240])
            return
        data, start = payload
        self.music_tab.mixer.play_stems(data, start)
        self.music_tab.refresh_loudness()  # lần đầu nghe thử đã đo độ to các bài

    def preview_seam(self, index: int) -> None:
        """Xuất nhanh: clip đang chọn phát 2 lần rồi sang clip kế tiếp, mở bằng trình xem mặc định."""
        if not self._check_ready():
            return
        proj = self.collect_project()
        clips = proj.video.clips
        if index < 0 or index >= len(clips):
            return
        cur = clips[index]
        nxt = next((c for c in clips[index + 1:] + clips[:index] if c.enabled and c.path != cur.path), None)
        p = copy.deepcopy(proj)
        p.name = "Xem thử chỗ nối"
        v = p.video
        # giữ nguyên đoạn cắt (bỏ đầu/bỏ cuối) để bản xem thử đúng như khi xuất
        v.clips = [ClipItem(path=cur.path, count=2, loop_xfade=cur.loop_xfade, next_xfade=cur.next_xfade,
                            trim_start=cur.trim_start, trim_end=cur.trim_end)]
        if nxt:
            v.clips.append(ClipItem(path=nxt.path, count=1, trim_start=nxt.trim_start, trim_end=nxt.trim_end))
        v.length_mode, v.order, v.fade_out, v.intro, v.outro = "manual", "list", 0.0, "", ""
        p.music.tracks, p.music.ambient = [], []
        p.export.tracklist = p.export.save_project_copy = p.export.markers = False
        ffmpeg_tools.clean_previews()  # bản xem thử là file tạm: chỉ giữ bản mới nhất
        out = str(ffmpeg_tools.preview_dir() / f"seam_{datetime.now():%H%M%S}.mp4")
        self._start_job(RenderJob(p, self.export_tab.available, out,
                                  on_progress=self.bridge.progress.emit, on_log=self.bridge.log.emit),
                        "preview")

    def _start_job(self, job: RenderJob, kind: str, clear_log: bool = True, seconds: float = 0.0) -> None:
        self.job, self._job_kind = job, kind
        self._job_t0, self._job_secs = time.time(), seconds  # đo tốc độ máy để ước tính giờ xong hàng đợi
        power.keep_awake(True)  # máy không tự ngủ khi đang xuất (hàng đợi qua đêm)
        self.settings_page.set_job_running(True)
        if self._size_runner:  # dừng đo dung lượng đang chạy: không tranh card đồ hoạ (giới hạn phiên NVENC)
            self._size_runner.cancel()
            self._size_runner = None
            self._size_gen += 1
            self._size_redo = True
        self.go_to(2)
        self.export_tab.set_running(True, clear_log=clear_log)
        self.export_tab.q_pause_btn.setVisible(kind == "queue")  # tạm dừng chỉ có nghĩa khi chạy hàng đợi
        self.accent_line.set_running(True)

        def work():
            try:
                result = str(job.run())
                self.bridge.finished.emit(result, "")
            except CancelledError:
                self.bridge.finished.emit("", "cancel")
            except Exception as e:  # noqa: BLE001
                self.bridge.finished.emit("", str(e))
        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def cancel_render(self) -> None:
        text = "Dừng mục đang xuất và dừng cả hàng đợi?" if self._queue_running else "Dừng việc đang xuất?"
        if self.job and QMessageBox.question(self, "Huỷ xuất?", text) == QMessageBox.StandardButton.Yes:
            if self.job:  # việc có thể đã xong trong lúc hộp thoại đang mở
                self.job.cancel()
            else:
                self._queue_running = False

    def _on_progress(self, frac: float, status: str) -> None:
        self.export_tab.on_progress(frac, status)
        if self._queue_item in self.queue:
            self.export_tab.set_queue_status(self.queue.index(self._queue_item), f"Đang chạy {int(frac * 100)}%")
            if int(frac * 100) != getattr(self, "_eta_pct", -1):  # cập nhật giờ xong mỗi 1%
                self._eta_pct = int(frac * 100)
                self._refresh_eta(frac)
        self.setWindowTitle(f"{int(frac * 100)}% — {APP_NAME}")

    def _update_power(self) -> None:
        """Hết việc (không còn xuất, hàng đợi đã dừng) → trả lại chế độ ngủ bình thường của Windows."""
        if self.job is None and not self._queue_running:
            QTimer.singleShot(500, self._check_disk)  # xuất xong: ổ đĩa có thể vừa đầy thêm
            power.keep_awake(False)
            self.settings_page.set_job_running(False)
            threading.Thread(target=ffmpeg_tools.prune_cache, daemon=True).start()  # bộ nhớ đệm quá lớn → dọn bớt

    def _on_finished(self, output: str, error: str) -> None:
        kind = self._job_kind
        if output and kind in ("video", "queue"):
            self._record_speed()
        self.job = None
        if self._closing:  # đang đóng app: mục hàng đợi dở đã được đặt lại "Đang chờ" trong closeEvent
            return
        QTimer.singleShot(1500, self._update_power)
        if self._size_pending is not None:
            self._size_timer.start()  # đo lại dung lượng đã hoãn trong lúc xuất
        elif self._size_redo:
            self._size_redo = False
            self._schedule()
        continuing = kind == "queue" and error != "cancel"
        self.export_tab.set_running(continuing, clear_log=False)
        self.accent_line.set_running(continuing)
        self.export_tab.done(output or None)
        self._update_title()
        self.music_tab.refresh_loudness()
        if kind == "queue":
            item = self._queue_item
            if item is not None:
                item.status = "done" if output else ("cancelled" if error == "cancel" else "error")
                item.message = output or error
                self._queue_results.append(item.status)
            self.export_tab.set_queue(self.queue)
            self._save_queue()
            if error == "cancel":
                self.settings.setValue("queue/was_running", "")
                self._queue_running = False
                self._queue_item = None
                self.export_tab.on_progress(0, "Đã dừng hàng đợi.")
            else:
                QTimer.singleShot(300, self._run_next)
            return
        if output and kind == "preview":
            self.export_tab.on_progress(1.0, "Đã tạo bản xem thử.")
            os.startfile(output)  # type: ignore[attr-defined]
            self.go_to(0)
            return
        QApplication.alert(self)
        if output:
            self._after_success(output)
            self.export_tab.on_progress(1.0, f"Xong! {output}")
            what = "File nhạc" if kind == "audio" else "Video"
            pending = sum(1 for i in self.queue if i.status == "pending")
            if pending and kind in ("video", "audio"):  # thêm vào hàng đợi trong lúc xuất: hỏi chạy luôn
                if QMessageBox.question(self, "Xuất xong", f"{what} đã lưu tại:\n{output}\n\nHàng đợi còn "
                                        f"{pending} mục đang chờ. Chạy hàng đợi luôn?") == QMessageBox.StandardButton.Yes:
                    self.go_to(2)
                    self.run_queue()
            else:
                QMessageBox.information(self, "Xuất xong", f"{what} đã lưu tại:\n{output}")
        elif error == "cancel":
            self.export_tab.on_progress(0, "Đã huỷ.")
            self.notify("Đã huỷ xuất file.", "warn")
        else:
            self.export_tab.on_progress(0, "Lỗi — xem nhật ký bên dưới.")
            QMessageBox.critical(self, "Xuất lỗi", error[-1500:])

    # ---------- đóng ----------
    def closeEvent(self, e) -> None:  # noqa: N802
        if self.job:
            if QMessageBox.question(self, "Đang xuất", "Đang xuất file. Huỷ và thoát?") \
                    != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self._closing = True
            self.settings.setValue("queue/was_running", "")  # tự đóng giữa chừng (có hỏi): lần sau không hỏi chạy tiếp
            if self._queue_running and self._queue_item is not None and self._queue_item.status == "running":
                self._queue_item.status, self._queue_item.message = "pending", ""  # mở app lần sau chạy lại
            self._queue_running = False
            job = self.job
            if job:  # có thể vừa xong trong lúc hộp thoại đang mở
                job.cancel()
            worker = getattr(self, "_worker", None)
            if worker:
                worker.join(timeout=10)  # để luồng xuất kịp xoá file dở
        self._closing = True
        self._timer.stop()
        power.keep_awake(False)
        self.music_tab.mixer.stop()
        self.viewer.shutdown()
        if self._audio_prev_runner:
            self._audio_prev_runner.cancel()
        if self._size_runner:
            self._size_runner.cancel()
        self.video_tab.thumbs.shutdown()
        self._prober.shutdown()
        self._save_queue()
        ffmpeg_tools.clean_previews()  # bản xem thử nối là file tạm (file còn mở trong trình xem: lần mở app sau xoá)
        if self._initial_loaded:
            try:
                self.collect_project().save(str(ffmpeg_tools.data_dir() / AUTOSAVE))
            except Exception:  # noqa: BLE001
                pass
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("project/path", self.project_path or "")
        try:
            (ffmpeg_tools.data_dir() / SESSION_FLAG).unlink(missing_ok=True)  # đóng đúng cách
        except OSError:
            pass
        super().closeEvent(e)
