"""Hộp thoại "Xuất hàng loạt theo thư mục": mỗi thư mục con = một video, cài đặt lấy theo dự án đang mở."""
from __future__ import annotations

import copy
import os
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QMenu, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core import ambient_lib, batch, encoders, timeline
from ..core import ffmpeg_tools as ft
from ..core.project import Project, format_hms
from . import icons
from . import widgets as w
from ..core.probe import probe_many
from .interleave_dialog import USER_PREFIX, InterleaveDialog, all_presets, arrange_from_preset
from .live_mix import LivePlayer
from .mixer_panel import MixerPanel
from .preview_worker import StemsJob

MUSIC = [("auto", "Nhạc trong từng thư mục; thư mục không có nhạc dùng playlist của dự án đang mở"),
         ("template", "Luôn dùng playlist của dự án đang mở"),
         ("folder", "Chỉ dùng nhạc trong từng thư mục (không có thì không có nhạc)")]
C_NAME, C_BASE, C_CLIPS, C_MUSIC, C_DUR, C_EDIT, C_PLAY, C_NOTE = range(8)
LISTEN_AT = [("start", "Đầu video"), ("mid", "Giữa video"), ("change", "Chỗ đổi bài nhạc đầu tiên")]
LISTEN_AT_MUSIC = [("start", "Đầu file"), ("mid", "Giữa file"), ("change", "Chỗ đổi bài nhạc đầu tiên")]


class VolSlider(QWidget):
    """Tên · thanh trượt · ô % (0–200) gọn trên một dòng."""

    def __init__(self, name: str, value: int, tip: str = "", parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QSlider, QSpinBox
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        self.label = QLabel(name)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 200)
        self.slider.setFixedWidth(110)
        self.spin = QSpinBox()
        self.spin.setRange(0, 200)
        self.spin.setSuffix(" %")
        self.spin.setFixedWidth(92)  # đủ chỗ cho “200 %”
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        self.spin.setValue(int(value))
        self.slider.setValue(int(value))
        for wd in (self.label, self.slider, self.spin):
            wd.setToolTip(tip or f"Âm lượng {name} cho cả loạt (100% = giữ nguyên)")
            lay.addWidget(wd)
        self.valueChanged = self.spin.valueChanged

    def value(self) -> int:
        return self.spin.value()

    def setValue(self, v: int) -> None:  # noqa: N802
        self.spin.setValue(int(v))

    def set_usable(self, on: bool, why: str = "") -> None:
        for wd in (self.label, self.slider, self.spin):
            wd.setEnabled(on)
        if why:
            self.setToolTip(why)


class VolumeDialog(QDialog):
    """Âm lượng riêng cho một video của loạt — giống Bảng trộn âm, có nghe thử 20 giây."""

    def __init__(self, proj: Project, vol: dict, info: tuple[float, list[float]], title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Âm lượng riêng — {title}")
        self.setMinimumWidth(520)
        self.proj = proj
        self.reset = False
        self.mixer = MixerPanel(self, hints=False)
        self.mixer.setTitle(f"Âm lượng riêng: {title}")
        self.mixer.set_values(vol["music"], vol["source"])
        self.mixer.set_ambient([(ambient_lib.display_name(a.path), v, a.enabled)
                                for a, v in zip(proj.music.ambient, vol["amb"])])
        v = proj.video
        self.mixer.set_state(proj.output_kind, v.source_audio, bool(v.intro or v.outro) and v.bookend_audio)
        self.mixer.set_timeline(*info)
        self.job = StemsJob(self)
        self.job.done.connect(self._on_stems)
        self.mixer.previewRequested.connect(self._listen)
        note = w.muted("Chỉ áp cho video này. Các video khác vẫn theo hàng <b>Âm lượng</b> chung của hộp thoại "
                       "hàng loạt.")
        note.setWordWrap(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setObjectName("accentBtn")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Huỷ")
        use_common = bb.addButton("Dùng mức chung của loạt", QDialogButtonBox.ButtonRole.ResetRole)
        use_common.clicked.connect(self._use_common)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(note)
        lay.addWidget(self.mixer)
        lay.addWidget(bb)

    def _listen(self, start: float) -> None:
        self.mixer.set_busy(True)
        self.job.start(self.proj, start)

    def _on_stems(self, payload, err: str, _tag) -> None:
        if err or not payload:
            self.mixer.show_error("Chưa nghe thử được: " + (err or "lỗi").strip().splitlines()[-1][:200])
            return
        self.mixer.play_stems(*payload)

    def _use_common(self) -> None:
        self.reset = True
        self.accept()

    def values(self) -> dict:
        m, s = self.mixer.values()
        return {"music": m, "source": s, "amb": self.mixer.ambient_values()}

    def done(self, r) -> None:
        self.mixer.stop(quiet=True)
        self.job.cancel()
        super().done(r)
KIND_TEXT = {"video_music": "Video có nhạc", "video_only": "Chỉ video", "music_only": "Chỉ nhạc"}
KINDS = (("video_music", "video_music", "segL", "Mỗi thư mục con → một video .mp4 có nhạc"),
         ("video_only", "film", "segM", "Mỗi thư mục con → một video .mp4 không nhạc (giữ tiếng gốc clip)"),
         ("music_only", "music", "segR", "Mỗi thư mục con → một file nhạc (playlist của thư mục đó)"))
# độ dài mỗi video / file: (giá trị, chữ hiện)
VIDEO_LEN = [("target", "Đúng thời lượng"), ("music", "Theo độ dài nhạc (playlist phát hết một lượt)"),
             ("manual", "Theo số lần phát của clip (mỗi cảnh phát 1 lần, clip nền theo mẫu xếp)")]
MUSIC_LEN = [("target", "Đúng thời lượng"), ("rounds", "Số lượt playlist")]


def _k(text: str) -> str:
    """Tên file / thư mục nổi bật trong khung hướng dẫn (QLabel hiện <code> chữ rất nhỏ)."""
    return f"<b style='color:#c4b5fd'>{text}</b>"


def _li(items) -> str:
    return "".join(f"<tr><td style='color:#7c5cff; padding-right:6px;'>•</td><td>{t}</td></tr>" for t in items)


def kind_card_html(kind: str, audio_ext: str = ".mp3") -> tuple[str, str]:
    """(nội dung bên trái, sơ đồ thư mục mẫu bên phải) cho khung "Mỗi thư mục con cần có gì"."""
    common = ("Thư mục con bắt đầu bằng " + _k("_") + " được bỏ qua.",
              "Cấu hình xuất, thư mục lưu, intro / outro, tiếng nền… lấy theo <b>dự án đang mở</b>.")
    if kind == "music_only":
        head = f"Mỗi thư mục con → <b>một file nhạc {audio_ext}</b>"
        items = ("Các bài nhạc trong thư mục con (kể cả thư mục bên trong) = <b>playlist</b> của file đó.",
                 "Playlist được lặp cho đủ <b>Độ dài mỗi file</b> bên dưới. Video / ảnh trong thư mục bị bỏ qua.",
                 *common)
        tree = ("Nhac-can-lam\\           <span style='color:#8c96b0'>← chọn thư mục này</span>\n"
                "├─ Piano-dem\\           <span style='color:#10b981'>→ Piano-dem" + audio_ext + "</span>\n"
                "│    bai1.mp3  bai2.mp3\n"
                "├─ Lofi-hoc-bai\\        <span style='color:#10b981'>→ Lofi-hoc-bai" + audio_ext + "</span>\n"
                "│    01.mp3  02.mp3  03.mp3\n"
                "└─ _chung\\              <span style='color:#8c96b0'>← bỏ qua</span>")
    else:
        music = kind == "video_music"
        head = "Mỗi thư mục con → <b>một video .mp4" + (" có nhạc" if music else " không nhạc") + "</b>"
        items = ["<b>Clip nền</b>: file có chữ " + _k("loop") + " trong tên (lặp suốt video).",
                 "<b>Cảnh chèn</b>: xếp theo số đầu tên " + _k("2_") + ", " + _k("3_") + "… xen giữa clip nền."]
        if music:
            items.append("<b>Nhạc</b>: file nhạc trong thư mục con (hoặc thư mục " + _k("Nhac") + " bên trong). "
                         "Không có thì dùng playlist của dự án đang mở — đổi ở ô <b>Nhạc</b>.")
        else:
            items.append("<b>Âm thanh</b>: tiếng gốc của clip (+ tiếng nền nếu dự án có). File nhạc trong thư mục "
                         "bị bỏ qua.")
        items += common
        tree = ("Video-can-lam\\          <span style='color:#8c96b0'>← chọn thư mục này</span>\n"
                "├─ Mua-dem\\             <span style='color:#10b981'>→ Mua-dem.mp4</span>\n"
                "│    loop_mua.mp4  2_pho.mp4  3_cafe.mp4\n"
                + ("│    Nhac\\ bai1.mp3     <span style='color:#8c96b0'>← không bắt buộc</span>\n" if music else "")
                + "├─ Rung-xanh\\           <span style='color:#10b981'>→ Rung-xanh.mp4</span>\n"
                "│    loop_rung.mp4  2_suoi.mp4\n"
                "└─ _chung\\              <span style='color:#8c96b0'>← bỏ qua</span>")
    left = (f"<div style='font-size:11pt; margin-bottom:4px;'>{head}</div>"
            f"<table cellspacing='0' cellpadding='1'>{_li(items)}</table>")
    right = f"<pre style='font-family:Consolas,monospace; margin:0;'>{tree}</pre>"
    return left, right


class BatchDialog(QDialog):
    def __init__(self, template: Project, settings: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Xuất hàng loạt theo thư mục")
        self.setMinimumSize(1000, 640)
        # bản riêng của hộp thoại: đổi kiểu ngay tại chỗ, không đụng dự án đang mở
        self.template = copy.deepcopy(template)
        self.settings = settings
        self.kind = template.output_kind
        self._project_kind = template.output_kind
        self.result_projects: list[Project] = []
        self.jobs: list[batch.FolderJob] = []
        # thư mục → (bảng clip đã chỉnh tay, trạng thái hộp thoại để mở lại đúng như lúc bấm OK)
        self._overrides: dict[str, tuple[list, dict]] = {}
        self._unchecked: set[str] = set()
        self._vol_overrides: dict[str, dict] = {}  # thư mục → âm lượng riêng {"music", "source", "amb": [...]}
        self._row_info: list[tuple[float, list[float]]] = []  # (thời lượng, mốc đổi bài) để chọn chỗ nghe thử
        self._play_btns: dict[int, QPushButton] = {}
        self._playing_row: int | None = None
        self._fade = None

        # ---- chọn kiểu ngay trong hộp thoại (mặc định theo dự án đang mở) ----
        kind_row = QHBoxLayout()
        kind_row.setSpacing(0)
        kl = QLabel("Xuất ra:")
        kl.setStyleSheet("font-weight:600; margin-right:10px;")
        kind_row.addWidget(kl)
        self.kind_group = QButtonGroup(self)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.kind_buttons: dict[str, QPushButton] = {}
        for key, ic, obj, tip in KINDS:
            b = QPushButton(KIND_TEXT[key])
            b.setObjectName(obj)
            b.setIcon(icons.icon(ic, 14))
            b.setIconSize(QSize(14, 14))
            b.setCheckable(True)
            b.setChecked(key == self.kind)
            b.setToolTip(tip)
            b.setMinimumWidth(130)
            b.clicked.connect(lambda _=False, k=key: self._switch_kind(k))
            self.kind_group.addButton(b)
            self.kind_buttons[key] = b
            seg.addWidget(b)
        self.kind_bar = self._wrap(seg)
        kind_row.addWidget(self.kind_bar)
        kind_row.addSpacing(12)
        self.kind_hint = w.muted("")
        self.kind_hint.setWordWrap(True)
        kind_row.addWidget(self.kind_hint, 1)

        # ---- khung "mỗi thư mục con cần có gì" + sơ đồ thư mục mẫu ----
        card = QFrame()
        card.setObjectName("batchCard")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(14, 10, 14, 10)
        cl.setSpacing(18)
        self.card_text = QLabel()
        self.card_text.setWordWrap(True)
        self.card_text.setTextFormat(Qt.TextFormat.RichText)
        self.card_tree = QLabel()
        self.card_tree.setTextFormat(Qt.TextFormat.RichText)
        self.card_tree.setObjectName("batchTree")
        cl.addWidget(self.card_text, 1)
        cl.addWidget(self.card_tree, 0, Qt.AlignmentFlag.AlignTop)
        # khung giữ một chiều cao cho cả 3 kiểu → bấm đổi kiểu không làm cả hộp thoại nhảy lên xuống
        fmt = encoders.AUDIO_FORMATS.get(self.template.music.export_format)
        self._audio_ext = fmt.ext if fmt else ".mp3"
        tree_h = text_h = 0
        for k in KIND_TEXT:
            left, right = kind_card_html(k, self._audio_ext)
            self.card_tree.setText(right)
            self.card_text.setText(left)
            tree_h = max(tree_h, self.card_tree.sizeHint().height())
            text_h = max(text_h, self.card_text.heightForWidth(560))
        self.card_tree.setMinimumHeight(tree_h)
        card.setMinimumHeight(max(tree_h, text_h) + 20)

        self.folder = QLineEdit(settings.value("batch/folder", ""))
        self.folder.setPlaceholderText("Ví dụ: D:\\Video-can-lam\\Tuan-1")
        browse = QPushButton("Chọn…")
        browse.clicked.connect(self._browse)
        self.sample = QPushButton("Thư mục mẫu")
        self.sample.setObjectName("ghost")
        self.sample.setIcon(icons.icon("folder", 14))
        self.sample.setIconSize(QSize(14, 14))
        self.sample.setToolTip("Dùng thư mục mẫu Mau-Test\\Hang-loat (3 video) để thử")
        self._sample_dir = Path(ft.app_dir()) / "Mau-Test" / "Hang-loat"
        self.sample.clicked.connect(lambda: self.folder.setText(str(self._sample_dir)))
        frow = QHBoxLayout()
        frow.setSpacing(6)
        frow.addWidget(self.folder, 1)
        frow.addWidget(browse)
        frow.addWidget(self.sample)

        self.preset = QComboBox()
        for p in all_presets(settings):
            self.preset.addItem((USER_PREFIX if p.get("user") else "") + p["name"], p)
        self.preset.addItem("Không xen kẽ — phát lần lượt theo tên file", None)
        last = settings.value("batch/preset", "")
        idx = self.preset.findText(last) if last else -1
        self.preset.setCurrentIndex(idx if idx >= 0 else 0)
        self.preset.setToolTip("Mẫu xếp clip (giống nút Xen kẽ clip nền). Mẫu tự lưu cũng có ở đây.")
        # crossfade không bắt buộc: 0 = "Cắt" (nối thẳng, không hoà hình) — giống ô crossfade ở trang Video
        self.loop_xf = w.xf_spin()
        self.loop_xf.setValue(float(settings.value("batch/loop_xf", 1.0)))
        self.loop_xf.setToolTip("Hoà hình giữa các lần lặp của clip nền. Kéo về 0 (hiện “Cắt”) = nối thẳng.")
        self.next_xf = w.xf_spin()
        self.next_xf.setValue(float(settings.value("batch/next_xf", 0.5)))
        self.next_xf.setToolTip("Hoà hình khi chuyển giữa clip nền và cảnh chèn. Kéo về 0 (hiện “Cắt”) = cắt thẳng.")
        no_xf = QPushButton("Không dùng crossfade")
        no_xf.setObjectName("pill")
        no_xf.setToolTip("Đặt cả hai về “Cắt”: các đoạn nối thẳng với nhau, không hoà hình")
        no_xf.clicked.connect(lambda: (self.loop_xf.setValue(0), self.next_xf.setValue(0)))
        xrow = QHBoxLayout()
        xrow.setSpacing(6)
        xrow.addWidget(QLabel("Nối loop"))
        xrow.addWidget(self.loop_xf)
        xrow.addSpacing(10)
        xrow.addWidget(QLabel("Chuyển cảnh"))
        xrow.addWidget(self.next_xf)
        xrow.addSpacing(10)
        xrow.addWidget(no_xf)
        xrow.addStretch(1)
        self.xf_box = self._wrap(xrow)
        self.music = QComboBox()
        for k, t in MUSIC:
            self.music.addItem(t, k)
        w_idx = self.music.findData(settings.value("batch/music", "auto"))
        self.music.setCurrentIndex(max(0, w_idx))

        # độ dài mỗi video / file nhạc (mặc định theo dự án đang mở; danh sách lựa chọn đổi theo kiểu)
        self.len_mode = QComboBox()
        t = self.template
        self.len_target = w.DurationEdit((t.music.export_target if self.music_only else t.video.target_duration) or 3600)
        self.len_rounds = QSpinBox()
        self.len_rounds.setRange(1, 999)
        self.len_rounds.setSuffix(" lượt")
        self.len_rounds.setValue(t.music.export_rounds)
        self.len_rounds.setToolTip("Playlist phát hết bao nhiêu lượt (mỗi lượt đổi thứ tự nếu dự án để ngẫu nhiên)")
        len_row = QHBoxLayout()
        len_row.setSpacing(10)
        len_row.addWidget(self.len_mode)
        len_row.addWidget(self.len_target)
        len_row.addWidget(self.len_rounds)
        len_row.addStretch(1)
        self.len_mode.currentIndexChanged.connect(self._update_len_widgets)

        # tiếng gốc của clip cho cả loạt (mặc định theo dự án khuôn; danh sách đổi theo kiểu)
        self.source = QComboBox()
        self.source.setToolTip("Áp cho mọi video trong loạt. Clip không có tiếng thì phần đó im lặng.")

        # âm lượng chung cho cả loạt (mặc định = Bảng trộn âm của dự án đang mở)
        self.vol_music = VolSlider("Nhạc", t.video.music_volume)
        self.vol_source = VolSlider("Tiếng gốc", t.video.source_volume)
        self.vol_amb = [VolSlider(ambient_lib.display_name(a.path), a.volume) for a in t.music.ambient]
        for k, (a, s) in enumerate(zip(t.music.ambient, self.vol_amb)):
            s.set_usable(a.enabled, "Lớp này đang tắt trong dự án đang mở")
        vol_box = QWidget()
        vfl = w.FlowLayout(vol_box, spacing=12)
        vfl.addWidget(self.vol_music)
        vfl.addWidget(self.vol_source)
        for s in self.vol_amb:
            vfl.addWidget(s)
        vol_reset = QPushButton("Theo dự án đang mở")
        vol_reset.setObjectName("ghost")
        vol_reset.setToolTip("Đặt lại theo Bảng trộn âm của dự án đang mở")
        vol_reset.clicked.connect(self._reset_volumes)
        vfl.addWidget(vol_reset)
        for s in (self.vol_music, self.vol_source, *self.vol_amb):
            s.valueChanged.connect(lambda *_: self._volumes_changed())
        # nghe thử từng dòng
        self.listen_at = QComboBox()
        self.listen_status = w.muted("")
        self.listen_status.setWordWrap(True)
        lrow = QHBoxLayout()
        lrow.setSpacing(8)
        lrow.addWidget(QLabel("Nghe từ"))
        lrow.addWidget(self.listen_at)
        lrow.addWidget(self.listen_status, 1)
        self.live = LivePlayer(self)
        self.live.finished.connect(self._listen_finished)
        self.stems_job = StemsJob(self)
        self.stems_job.done.connect(self._on_stems)
        self._listen_tick = QTimer(self)
        self._listen_tick.setInterval(250)
        self._listen_tick.timeout.connect(self._update_listen_status)

        # mọi hàng đều dựng sẵn; đổi kiểu chỉ ẩn / hiện hàng (không đóng mở lại hộp thoại)
        self.form = form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setVerticalSpacing(8)
        form.addRow("Thư mục cha:", self._wrap(frow))
        self.len_label = QLabel()
        self.len_box = self._wrap(len_row)
        form.addRow(self.len_label, self.len_box)
        form.addRow("Mẫu xếp clip:", self.preset)
        form.addRow("Crossfade:", self.xf_box)
        form.addRow("Tiếng gốc clip:", self.source)
        form.addRow("Nhạc:", self.music)
        form.addRow("Âm lượng:", vol_box)
        form.addRow("Nghe thử:", self._wrap(lrow))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Clip nền", "Clip", "", "Thời lượng", "Thứ tự cảnh", "Nghe thử", "Ghi chú"])
        self.tree.headerItem().setToolTip(C_EDIT, "Bấm Chỉnh… để đổi thứ tự cảnh / số lần phát riêng cho video đó")
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        hdr = self.tree.header()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(C_NAME, QHeaderView.ResizeMode.Stretch)
        for c in (C_BASE, C_CLIPS, C_MUSIC, C_DUR, C_EDIT, C_PLAY):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._row_menu)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._edit(self.tree.indexOfTopLevelItem(it)))
        self.tree.itemChanged.connect(lambda *_: self._update_summary())
        self.summary = QLabel("Chọn thư mục cha để xem danh sách video sẽ tạo.")
        self.summary.setWordWrap(True)
        self.run_now = QCheckBox("Chạy hàng đợi ngay sau khi thêm")
        self.run_now.setChecked(settings.value("batch/run_now", "true") in (True, "true"))

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = bb.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setObjectName("accentBtn")
        self.ok_btn.setEnabled(False)
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Huỷ")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.run_now)
        bottom.addStretch(1)
        bottom.addWidget(bb)

        # phần đổi theo kiểu (khung hướng dẫn, các hàng, bảng) — mờ dần vào khi đổi kiểu
        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(10)
        bl.addWidget(card)
        bl.addLayout(form)
        bl.addWidget(self.tree, 1)
        bl.addWidget(self.summary)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addLayout(kind_row)
        lay.addWidget(self.body, 1)
        lay.addLayout(bottom)

        # quét khi gõ xong (Enter / rời ô) hoặc ngừng gõ 0,8 giây — không quét từng ký tự (gõ "E:" là quét cả ổ)
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(800)
        self._scan_timer.timeout.connect(self._rescan)
        self._scanned = None
        self.folder.editingFinished.connect(self._rescan)
        self.folder.textChanged.connect(lambda *_: self._scan_timer.start())
        self.source.currentIndexChanged.connect(self._update_music_enabled)
        self._apply_kind(initial=True)
        for sig in (self.preset.currentIndexChanged, self.music.currentIndexChanged, self.loop_xf.valueChanged,
                    self.next_xf.valueChanged, self.source.currentIndexChanged, self.len_mode.currentIndexChanged,
                    self.len_target.valueChanged, self.len_rounds.valueChanged):
            sig.connect(lambda *_: self._rebuild())
        if os.path.isdir(self.folder.text().strip()):
            self._rescan()

    @property
    def music_only(self) -> bool:
        return self.kind == "music_only"

    @property
    def _unit(self) -> str:
        return "file nhạc" if self.music_only else "video"

    @staticmethod
    def _refill(combo: QComboBox, items, want) -> None:
        """Đổi danh sách lựa chọn của ô mà không phát tín hiệu; giữ lựa chọn cũ nếu còn, không thì chọn mục đầu."""
        combo.blockSignals(True)
        combo.clear()
        for k, txt in items:
            combo.addItem(txt, k)
        combo.setCurrentIndex(max(0, combo.findData(want)))
        combo.blockSignals(False)

    def _apply_kind(self, initial: bool = False) -> None:
        """Hiện đúng những gì kiểu đang chọn cần: khung hướng dẫn, các hàng, lựa chọn trong ô, cột của bảng."""
        k, mo, t = self.kind, self.music_only, self.template
        self.kind_buttons[k].setChecked(True)
        if k == self._project_kind:
            self.kind_hint.setText("Kiểu của dự án đang mở được chọn sẵn — bấm để đổi kiểu cho cả loạt.")
        else:
            self.kind_hint.setText(f"Chỉ đổi cho loạt này — dự án đang mở vẫn là <b>{KIND_TEXT[self._project_kind]}</b>.")
        left, right = kind_card_html(k, self._audio_ext)
        self.card_text.setText(left)
        self.card_tree.setText(right)
        self.sample.setVisible(self._sample_dir.is_dir() and not mo)  # thư mục mẫu là thư mục video

        # độ dài: giữ con số đang gõ khi đổi kiểu; kiểu mới không có cách tính cũ thì về "Đúng thời lượng"
        if mo:
            items = MUSIC_LEN
            want = t.music.export_mode if initial else self.len_mode.currentData()
        else:
            items = [(v, txt) for v, txt in VIDEO_LEN if not (v == "music" and k == "video_only")]
            want = t.video.length_mode if initial else self.len_mode.currentData()
        if want not in [v for v, _ in items]:
            want = "target"
        self._refill(self.len_mode, items, want)
        self.len_label.setText("Độ dài mỗi file:" if mo else "Độ dài mỗi video:")
        self.len_mode.setToolTip(f"Áp cho mọi {self._unit} trong loạt")
        self._update_len_widgets()

        if k == "video_only":
            src_items = [("mix", "Giữ tiếng gốc của clip"), ("off", "Tắt tiếng gốc của clip")]
        else:
            src_items = [("mix", "Giữ tiếng gốc, trộn với nhạc"), ("only", "Chỉ tiếng gốc của clip — không dùng nhạc"),
                         ("off", "Tắt tiếng gốc của clip")]
        cur = t.video.source_audio if initial or self.source.count() == 0 else self.source.currentData()
        self._refill(self.source, src_items, "mix" if (k == "video_only" and cur == "only") else cur)

        for wd in (self.preset, self.xf_box, self.source):
            self.form.setRowVisible(wd, not mo)
        # Chỉ video: không có nhạc → ẩn hẳn ô Nhạc (không để mờ gây khó hiểu)
        self.form.setRowVisible(self.music, k == "video_music")
        self.vol_music.setVisible(k != "video_only")
        self.vol_source.setVisible(not mo)

        self._refill(self.listen_at, LISTEN_AT_MUSIC if mo else LISTEN_AT, self.listen_at.currentData() or "start")
        self.listen_at.setToolTip(f"Bấm Nghe ở một dòng để nghe 20 giây của đúng {self._unit} đó, từ mốc này")
        self.listen_status.setText(f"Bấm <b>Nghe</b> ở một dòng để nghe thử 20 giây của {self._unit} đó — kéo thanh "
                                   "âm lượng là nghe đổi ngay.")
        head = self.tree.headerItem()
        head.setText(C_NAME, f"Thư mục (= tên {self._unit})")
        head.setText(C_MUSIC, "Âm thanh" if k == "video_only" else "Nhạc")
        head.setToolTip(C_PLAY, f"Nghe 20 giây của {self._unit} đó với âm lượng đang chọn")
        for c in (C_BASE, C_CLIPS, C_EDIT):
            self.tree.setColumnHidden(c, mo)
        self._update_music_enabled()

    def _update_music_enabled(self, *_) -> None:
        """Chỉ tiếng gốc / kiểu Chỉ video: playlist không dùng → khoá ô chọn nhạc (và thanh âm lượng nhạc)."""
        no_music = self.source.currentData() == "only" or self.template.output_kind == "video_only"
        self.music.setEnabled(not no_music)
        if hasattr(self, "vol_music"):
            self.vol_music.set_usable(not no_music, "Loạt này không dùng nhạc")
            t = self.template.video
            src_on = self.source.currentData() != "off" or (bool(t.intro or t.outro) and t.bookend_audio)
            self.vol_source.set_usable(src_on, "Tiếng gốc clip đang tắt")

    def _update_len_widgets(self, *_) -> None:
        mode = self.len_mode.currentData()
        self.len_target.setVisible(mode == "target")
        self.len_rounds.setVisible(mode == "rounds")

    def _apply_len(self, p: Project) -> None:
        """Độ dài chung của hộp thoại → dự án (khuôn hoặc từng video)."""
        mode = self.len_mode.currentData()
        if p.output_kind == "music_only":
            p.music.export_mode = mode if mode in ("target", "rounds") else "target"
            p.music.export_target = self.len_target.seconds()
            p.music.export_rounds = self.len_rounds.value()
        else:
            p.video.length_mode = mode if mode in ("target", "music", "manual") else "target"
            if p.video.length_mode == "music" and p.output_kind == "video_only":
                p.video.length_mode = "target"
            p.video.target_duration = self.len_target.seconds()

    def _switch_kind(self, kind: str) -> None:
        """Đổi kiểu cho cả loạt ngay tại chỗ: giữ thư mục cha, độ dài, âm lượng, dòng đã bỏ tick, chỉnh tay."""
        if kind == self.kind:
            return
        self._stop_listen()
        self.kind = kind
        self.template.output_kind = kind
        self.setUpdatesEnabled(False)  # đổi một lượt rồi mới vẽ lại — không thấy từng ô nhảy
        try:
            self._apply_kind()
            self._scanned = None  # Chỉ nhạc quét file nhạc, kiểu video quét clip → quét lại thư mục
            self._rescan()
        finally:
            self.setUpdatesEnabled(True)
        self._fade_in()

    def _fade_in(self) -> None:
        """Phần thân hộp thoại hiện dần (~0,2 giây) sau khi đổi kiểu."""
        from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPropertyAnimation
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        if self._fade is not None:
            self._fade.stop()
        eff = QGraphicsOpacityEffect(self.body)
        eff.setOpacity(0.2)
        self.body.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.2)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def end():
            self._fade = None
            self.body.setGraphicsEffect(None)  # bỏ hiệu ứng khi xong: bảng cuộn / vẽ nhanh như thường

        anim.finished.connect(end)
        self._fade = anim
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    @staticmethod
    def _wrap(layout) -> QWidget:
        box = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        box.setLayout(layout)
        return box

    def _browse(self) -> None:
        d = w.pick_folder(self, "Chọn thư mục cha (mỗi thư mục con = một video)", self.folder.text())
        if d:
            self.folder.setText(d)

    # ---------- quét + dựng thử ----------
    def _rescan(self) -> None:
        self._scan_timer.stop()
        text = self.folder.text().strip()
        if text == self._scanned:
            return
        self._scanned = text
        if text and os.path.isdir(text) and batch.is_drive_root(text):
            self.jobs = []
            self._rebuild()
            self.summary.setText("<span style='color:#f59e0b'>Đây là cả ổ đĩa — hãy chọn đúng <b>thư mục cha</b> chứa "
                                 "các thư mục video (ví dụ D:\\Video-can-lam\\Tuan-1).</span>")
            return
        self.jobs = batch.scan(text, self.music_only) if os.path.isdir(text) else []
        self._rebuild()

    def _out_dir(self) -> str:
        """Thư mục lưu nằm trong thư mục cha → lưu vào <cha>/_Xuat (bắt đầu bằng _ nên lần quét sau bỏ qua),
        tránh video xuất ra bị nhận nhầm thành clip / thư mục video mới."""
        out = self.template.export.output_dir
        parent = self.folder.text().strip()
        if not out or not parent:
            return out
        try:
            rel = os.path.relpath(os.path.abspath(out), os.path.abspath(parent))
        except ValueError:  # khác ổ đĩa
            return out
        if rel.startswith(".."):
            return out
        first = rel.replace("\\", "/").split("/")[0]
        if first == "." and not self.template.export.own_folder:
            return out  # file nằm thẳng trong thư mục cha: không bị quét (chỉ quét thư mục con)
        if first != "." and first.startswith(("_", ".")):
            return out
        return os.path.join(parent, "_Xuat")

    def _build(self, job: batch.FolderJob) -> Project:
        p = self.preset.currentData()
        arrange = arrange_from_preset(p) if p else None
        ov = self._overrides.get(job.folder)
        proj = batch.build_project(self.template, job, self.music.currentData() if not self.music_only else "folder",
                                   arrange, self.loop_xf.value(), self.next_xf.value(),
                                   clips_override=ov[0] if ov else None,
                                   source_audio=None if self.music_only else self.source.currentData(),
                                   base_override=ov[1].get("base") if ov else None)
        proj.export.output_dir = self._out_dir()
        self._apply_len(proj)
        return proj

    def _rebuild(self) -> None:
        # giữ lựa chọn bỏ tick của người dùng khi dựng lại bảng
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            folder = it.toolTip(C_NAME)
            if it.flags() & Qt.ItemFlag.ItemIsEnabled:
                (self._unchecked.add if it.checkState(C_NAME) != Qt.CheckState.Checked
                 else self._unchecked.discard)(folder)
        self.tree.blockSignals(True)
        self._stop_listen()
        self.tree.clear()
        self._projects: list[Project | None] = []
        self._row_info = []
        self._play_btns = {}
        if not self.jobs:
            self.tree.blockSignals(False)
            self.summary.setText("<span style='color:#f59e0b'>Không thấy thư mục con nào.</span>"
                                 if self.folder.text().strip() else "Chọn thư mục cha để xem danh sách video sẽ tạo.")
            self.ok_btn.setEnabled(False)
            return
        self.summary.setText("Đang đọc các thư mục…")
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._fill_rows()
        finally:
            QApplication.restoreOverrideCursor()
        self.tree.blockSignals(False)
        self._update_summary()

    def _fill_rows(self) -> None:
        for job in self.jobs:
            it = QTreeWidgetItem([job.name, "", "", "", "", ""])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setToolTip(C_NAME, job.folder)
            proj, total, note = None, 0.0, job.error
            changes: list[float] = []
            extra: list[str] = []  # ghi chú của riêng lần dựng bảng này
            if not job.error:
                proj = self._build(job)
                tl = timeline.build_audio(proj) if self.music_only else timeline.build(proj)
                if tl.ok:
                    total = tl.total
                    changes = [m.start for m in tl.music_items[1:]]
                    # clip lỗi bị bỏ qua, crossfade tự giảm, ngắn hơn mục tiêu… (bỏ thông báo tạm "đang tạo tiếng nền")
                    extra += [x for x in tl.warnings if not x.startswith("Đang tạo tiếng nền")]
                else:
                    note = " · ".join(tl.errors)
                    proj = None
            if not self.music_only:
                it.setText(C_BASE, Path(job.base).name if job.base else "—")
                it.setText(C_CLIPS, str(len(job.clips)))
            if proj is not None:
                tracks = [t for t in proj.music.tracks if t.enabled]
                own = bool(job.music) and (self.music_only or self.music.currentData() != "template")
                src = proj.video.source_audio
                if proj.output_kind == "video_only" or src == "only":
                    music_txt = ""
                else:
                    music_txt = f"{len(tracks)} bài" + (" (riêng)" if own else " (chung)" if tracks else "")
                if not self.music_only and src in ("mix", "only"):
                    if any(on for k, on in tl.audible.items() if k >= 0):  # chỉ tính clip chính, không tính Intro/Outro
                        music_txt = (music_txt + " + tiếng gốc") if music_txt else "Tiếng gốc clip"
                    else:
                        extra.append("Clip không có tiếng gốc")
                it.setText(C_MUSIC, music_txt or "—")
                it.setText(C_DUR, w.fmt_dur(total))
            ok = proj is not None
            edited = job.folder in self._overrides
            vol_edited = job.folder in self._vol_overrides
            notes = (["Thứ tự cảnh đã chỉnh tay"] if edited else []) + (["Đã chỉnh âm lượng riêng"] if vol_edited
                                                                        else []) + job.notes + extra
            it.setText(C_NOTE, note or " · ".join(notes) or ("Sẵn sàng" if ok else ""))
            it.setToolTip(C_NOTE, "\n".join([note] if note else notes))
            it.setCheckState(C_NAME, Qt.CheckState.Checked if ok and job.folder not in self._unchecked
                             else Qt.CheckState.Unchecked)
            if not ok:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsUserCheckable & ~Qt.ItemFlag.ItemIsEnabled)
                it.setForeground(C_NOTE, QColor("#f87171"))
            elif edited or vol_edited:
                it.setForeground(C_NOTE, QColor("#a78bfa"))
            elif job.notes or extra:
                it.setForeground(C_NOTE, QColor("#fbbf24"))
            else:
                it.setForeground(C_NOTE, QColor("#6ee7b7"))
            it.setData(C_NAME, Qt.ItemDataRole.UserRole, total)
            self._projects.append(proj)
            self._row_info.append((total, changes))
            self.tree.addTopLevelItem(it)
            if ok:
                pbtn = QPushButton("Nghe")
                pbtn.setObjectName("pill")
                pbtn.setIcon(icons.icon("play", 12))
                pbtn.setIconSize(QSize(12, 12))
                pbtn.setToolTip("Nghe 20 giây của video này (mốc chọn ở ô Nghe từ) với âm lượng đang đặt")
                pbtn.setMinimumWidth(pbtn.sizeHint().width() + 10)
                pbtn.clicked.connect(lambda _=False, k=len(self._projects) - 1: self._listen(k))
                self.tree.setItemWidget(it, C_PLAY, pbtn)
                self._play_btns[len(self._projects) - 1] = pbtn
            if ok and not self.music_only:
                btn = QPushButton("Đã chỉnh tay" if edited else "Chỉnh…")
                btn.setObjectName("accentBtn" if edited else "pill")
                btn.setToolTip("Đổi thứ tự cảnh, số lần xuất hiện / số lần phát riêng cho video này "
                               "(kéo thả, ↑ ↓). Các video khác vẫn theo mẫu chung.")
                btn.setMinimumWidth(btn.sizeHint().width() + 14)  # chữ không bị cắt
                btn.clicked.connect(lambda _=False, k=len(self._projects) - 1: self._edit(k))
                self.tree.setItemWidget(it, C_EDIT, btn)

    # ---------- chỉnh tay từng video ----------
    def _edit(self, row: int) -> None:
        if self.music_only or not (0 <= row < len(self._projects)) or self._projects[row] is None:
            return
        job, proj = self.jobs[row], self._projects[row]
        clips = proj.video.clips
        durations = {}
        for c, info in zip(clips, probe_many([c.path for c in clips])):
            if info.ok:
                durations[os.path.normcase(c.path)] = (self.template.video.image_duration if info.is_image
                                                       else info.duration)
        ov = self._overrides.get(job.folder)
        preset = None if ov else self.preset.currentText()
        dlg = InterleaveDialog(clips, durations, self.settings, self, preset_name=preset)
        dlg.setWindowTitle(f"Chỉnh thứ tự cảnh — {job.name}")
        if ov:  # mở lại: điền đúng như lần bấm OK trước (số lần xuất hiện, số lượt, cảnh bỏ tick…)
            self._restore_state(dlg, ov[1])
        if dlg.exec() and dlg.result_clips:
            self._overrides[job.folder] = (dlg.result_clips, self._dialog_state(dlg))
            self._rebuild()

    @staticmethod
    def _dialog_state(dlg: InterleaveDialog) -> dict:
        base_i = dlg.base.currentData()
        return {"base": dlg.clips[base_i].path if base_i is not None else None,
                "base_text": dlg.base_plays.text(), "repeat": dlg.repeat.value(),
                "reshuffle": dlg.reshuffle.isChecked(), "start": dlg.start_base.isChecked(),
                "end": dlg.end_base.isChecked(),
                "specs": [(sp.path, sp.appear, sp.plays, sp.enabled) for sp in dlg._specs()]}

    @staticmethod
    def _restore_state(dlg: InterleaveDialog, st: dict) -> None:
        base_key = os.path.normcase(st.get("base") or "")
        for k in range(dlg.base.count()):
            i = dlg.base.itemData(k)
            if i is not None and os.path.normcase(dlg.clips[i].path) == base_key:
                dlg.base.setCurrentIndex(k)
                break
        dlg._busy = True
        dlg.base_plays.setText(st.get("base_text", "70"))
        dlg.repeat.setValue(int(st.get("repeat", 1)))
        dlg.reshuffle.setChecked(bool(st.get("reshuffle", False)))
        dlg.start_base.setChecked(bool(st.get("start", True)))
        dlg.end_base.setChecked(bool(st.get("end", True)))
        dlg._busy = False
        dlg._fill_tree("table", None)
        order = {os.path.normcase(p): (k, a, n, on) for k, (p, a, n, on) in enumerate(st.get("specs", []))}
        items = [dlg.tree.takeTopLevelItem(0) for _ in range(dlg.tree.topLevelItemCount())]
        items.sort(key=lambda it: order.get(os.path.normcase(it.data(0, Qt.ItemDataRole.UserRole)), (10 ** 6,))[0])
        dlg._busy = True
        for it in items:
            sp = order.get(os.path.normcase(it.data(0, Qt.ItemDataRole.UserRole)))
            if sp:
                it.setText(1, str(sp[1]))
                it.setText(2, str(sp[2]))
                it.setCheckState(0, Qt.CheckState.Checked if sp[3] else Qt.CheckState.Unchecked)
            dlg.tree.addTopLevelItem(it)
        dlg._busy = False
        dlg._update()

    def _reset(self, row: int) -> None:
        if 0 <= row < len(self.jobs) and self.jobs[row].folder in self._overrides:
            del self._overrides[self.jobs[row].folder]
            self._rebuild()

    def _row_menu(self, pos) -> None:
        it = self.tree.itemAt(pos)
        if it is None:
            return
        row = self.tree.indexOfTopLevelItem(it)
        if self._projects[row] is None:
            return
        what = "file nhạc" if self.music_only else "video"
        folder = self.jobs[row].folder
        menu = QMenu(self)
        if not self.music_only:
            menu.addAction(icons.icon("repeat", 14), "Chỉnh thứ tự cảnh cho video này…", lambda: self._edit(row))
            if folder in self._overrides:
                menu.addAction(icons.icon("undo", 14), "Bỏ chỉnh tay — dùng lại mẫu chung", lambda: self._reset(row))
            menu.addSeparator()
        menu.addAction(icons.icon("sliders", 14), f"Chỉnh âm lượng {what} này…", lambda: self._edit_volume(row))
        if folder in self._vol_overrides:
            menu.addAction(icons.icon("undo", 14), "Bỏ âm lượng riêng — dùng mức chung", lambda: self._reset_volume(row))
        menu.addAction(icons.icon("play", 14), "Nghe thử 20 giây", lambda: self._listen(row))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ---------- âm lượng ----------
    def _batch_vol(self) -> dict:
        return {"music": self.vol_music.value(), "source": self.vol_source.value(),
                "amb": [s.value() for s in self.vol_amb]}

    def _vol_for(self, row: int) -> dict:
        return self._vol_overrides.get(self.jobs[row].folder) or self._batch_vol()

    @staticmethod
    def _apply_vol(proj: Project, vol: dict) -> Project:
        proj.video.music_volume, proj.video.source_volume = vol["music"], vol["source"]
        for a, v in zip(proj.music.ambient, vol["amb"]):
            a.volume = v
        return proj

    @staticmethod
    def _gains(vol: dict) -> dict[str, float]:
        g = {"music": vol["music"] / 100, "source": vol["source"] / 100}
        for k, v in enumerate(vol["amb"]):
            g[f"amb:{k}"] = v / 100
        return g

    def _reset_volumes(self) -> None:
        t = self.template
        self.vol_music.setValue(t.video.music_volume)
        self.vol_source.setValue(t.video.source_volume)
        for a, s in zip(t.music.ambient, self.vol_amb):
            s.setValue(a.volume)

    def _volumes_changed(self) -> None:
        """Kéo thanh âm lượng chung: đang nghe dòng nào (không có âm lượng riêng) thì đổi ngay."""
        r = self._playing_row
        if r is not None and self.live.is_playing() and self.jobs[r].folder not in self._vol_overrides:
            for k, v in self._gains(self._batch_vol()).items():
                self.live.set_gain(k, v)

    def _edit_volume(self, row: int) -> None:
        proj = self._projects[row]
        if proj is None:
            return
        self._stop_listen()
        dlg = VolumeDialog(proj, self._vol_for(row), self._row_info[row], self.jobs[row].name, self)
        if dlg.exec():
            folder = self.jobs[row].folder
            if dlg.reset:
                self._vol_overrides.pop(folder, None)
            else:
                self._vol_overrides[folder] = dlg.values()
            self._rebuild()

    def _reset_volume(self, row: int) -> None:
        if self._vol_overrides.pop(self.jobs[row].folder, None) is not None:
            self._rebuild()

    # ---------- nghe thử từng dòng ----------
    def _listen(self, row: int) -> None:
        if self._projects[row] is None:
            return
        if self._playing_row == row:  # bấm lại dòng đang nghe / đang chuẩn bị = dừng
            self._stop_listen()
            return
        self._stop_listen()
        total, changes = self._row_info[row]
        at = self.listen_at.currentData()
        start = {"start": 0.0, "mid": total / 2,
                 "change": max(0.0, changes[0] - 8) if changes else 0.0}[at]
        self._playing_row = row
        btn = self._play_btns.get(row)
        if btn:
            btn.setText("Dừng")
            btn.setIcon(icons.icon("stop", 12))
        self.listen_status.setText(f"Đang chuẩn bị <b>{self.jobs[row].name}</b> (lần đầu đo độ to các bài nên lâu "
                                   "hơn một chút)…")
        self.stems_job.start(self._projects[row], start, tag=row)

    def _on_stems(self, payload, err: str, tag) -> None:
        if tag != self._playing_row:
            return
        if err or not payload:
            self.listen_status.setText("<span style='color:#fca5a5'>Chưa nghe thử được: "
                                       + (err or "lỗi").strip().splitlines()[-1][:200] + "</span>")
            self._reset_play_btn(tag)
            self._playing_row = None
            return
        data, start = payload
        self._listen_start = start
        gains = self._gains(self._vol_for(tag))
        if self.live.available():
            self.live.play(data, gains)
            self._listen_tick.start()
            self._update_listen_status()
        else:  # máy không phát trực tiếp được: hoà sẵn rồi mở bằng trình phát mặc định
            import wave
            from .live_mix import CH, RATE, WIDTH, Mixer
            out = ft.preview_dir() / "nghe-thu_hang-loat.wav"
            with wave.open(str(out), "wb") as f:
                f.setnchannels(CH)
                f.setsampwidth(WIDTH)
                f.setframerate(RATE)
                f.writeframes(Mixer(data, gains).mix_all())
            w.open_with_default_app(str(out))
            self._listen_finished()

    def _update_listen_status(self) -> None:
        r = self._playing_row
        if r is None or not self.live.is_playing():
            return
        pos = min(20.0, self.live.position())
        own = " (âm lượng riêng)" if self.jobs[r].folder in self._vol_overrides else ""
        self.listen_status.setText(f"Đang nghe <b>{self.jobs[r].name}</b>{own} — {format_hms(self._listen_start + pos)} "
                                   f"({int(pos)}/20 giây). Kéo thanh âm lượng là nghe đổi ngay.")

    def _reset_play_btn(self, row) -> None:
        btn = self._play_btns.get(row) if row is not None else None
        if btn:
            btn.setText("Nghe")
            btn.setIcon(icons.icon("play", 12))

    def _listen_finished(self) -> None:
        self._listen_tick.stop()
        self._reset_play_btn(self._playing_row)
        self._playing_row = None
        self.listen_status.setText("Đã nghe xong. Bấm <b>Nghe</b> ở dòng khác, hoặc đổi mốc <b>Nghe từ</b>.")

    def _stop_listen(self) -> None:
        if not hasattr(self, "live"):
            return
        self.stems_job.cancel()
        self.live.stop()
        self._listen_tick.stop()
        self._reset_play_btn(self._playing_row)
        self._playing_row = None

    def done(self, r) -> None:  # đóng hộp thoại: dừng nghe
        self._stop_listen()
        super().done(r)

    def _update_summary(self) -> None:
        chosen = [i for i in range(self.tree.topLevelItemCount())
                  if self.tree.topLevelItem(i).checkState(C_NAME) == Qt.CheckState.Checked and self._projects[i]]
        total = sum(self.tree.topLevelItem(i).data(C_NAME, Qt.ItemDataRole.UserRole) or 0 for i in chosen)
        bad = sum(1 for p in self._projects if p is None)
        n_ver = max(1, self.template.music.versions) if self.music_only else 1
        what = "file nhạc" if self.music_only else "video"
        extra = f" × {n_ver} bản" if n_ver > 1 else ""
        out = self._out_dir()
        moved = out and os.path.normcase(out) != os.path.normcase(self.template.export.output_dir or "")
        self.summary.setText(f"Sẽ thêm <b>{len(chosen)}</b> {what}{extra} vào hàng đợi · tổng thời lượng ≈ "
                             f"<b>{w.fmt_dur(total)}</b>"
                             + (f" · <span style='color:#f87171'>{bad} thư mục bị bỏ qua (xem Ghi chú)</span>"
                                if bad else "")
                             + (f"<br><span style='color:#fbbf24'>Thư mục lưu nằm trong thư mục cha → file sẽ lưu vào "
                                f"<b>{out}</b> để lần quét sau không lẫn với clip.</span>" if moved else ""))
        self.ok_btn.setText(f"Thêm {len(chosen)} {what} vào hàng đợi")
        self.ok_btn.setEnabled(bool(chosen))

    def _accept(self) -> None:
        self.result_projects = [self._apply_vol(self._projects[i], self._vol_for(i))
                                for i in range(self.tree.topLevelItemCount())
                                if self.tree.topLevelItem(i).checkState(C_NAME) == Qt.CheckState.Checked
                                and self._projects[i] is not None]
        self._save_settings()
        self.accept()

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("batch/folder", self.folder.text().strip())
        s.setValue("batch/preset", self.preset.currentText())
        s.setValue("batch/music", self.music.currentData())
        s.setValue("batch/loop_xf", self.loop_xf.value())
        s.setValue("batch/next_xf", self.next_xf.value())
        s.setValue("batch/run_now", "true" if self.run_now.isChecked() else "false")
