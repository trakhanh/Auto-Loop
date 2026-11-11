"""Công cụ "Lọc tạp âm video": chọn một hoặc nhiều video → bản _DeNoise cạnh file gốc (hình giữ nguyên, chỉ lọc
tiếng) — như Premiere: Essential Sound → Reduce Noise rồi xuất lại."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..core import denoise, ffmpeg_tools
from . import icons, theme
from . import widgets as w
from .video_tab import DENOISE, combo, set_combo

SUFFIX = "_DeNoise"
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}


def output_path(src: str, folder: str = "") -> Path:
    """"D:/a/demo.mp4" → "D:/a/demo_DeNoise.mp4" (đã có thì _DeNoise2…). File chỉ có tiếng → .m4a."""
    p = Path(src)
    ext = ".m4a" if p.suffix.lower() in AUDIO_EXTS else p.suffix
    base = Path(folder) if folder else p.parent
    out = base / f"{p.stem}{SUFFIX}{ext}"
    n = 2
    while out.exists():
        out = base / f"{p.stem}{SUFFIX}{n}{ext}"
        n += 1
    return out


def has_video(runner: ffmpeg_tools.Runner, path: str) -> bool:
    from ..core import probe
    return probe.probe(path).has_video


def denoise_file(runner: ffmpeg_tools.Runner, src: str, level: str, out: Path, on_step=None) -> Path:
    """Một file: tiếng đã lọc (bộ nhớ đệm) + hình chép nguyên → `out` (ghi tên tạm rồi đổi tên)."""
    clean = denoise.denoised_copy(runner, src, level, on_step)
    part = out.with_name(out.stem + ".dang-xuat" + out.suffix)
    args = ["-v", "error", "-i", src, "-i", clean]
    if has_video(runner, src):
        args += ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-map_metadata", "0"]
        if out.suffix.lower() in (".mp4", ".mov", ".m4v"):
            args += ["-movflags", "+faststart"]
    else:
        args += ["-map", "1:a:0"]
    args += ["-c:a", "aac", "-b:a", "320k", str(part)]  # không -shortest: tiếng ngắn hơn hình vài ms là mất khung cuối
    try:
        runner.ffmpeg(args)
        os.replace(part, out)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return out


def _label(path: str) -> str:
    p = Path(path)
    return f"{p.name}   ·   {p.parent}"


class _Bridge(QObject):
    progress = Signal(int, float, str)  # (thứ tự file, tỉ lệ, chữ)
    finished = Signal(int, str, str)  # (thứ tự file, file ra, lỗi)
    all_done = Signal()


class DenoiseDialog(QDialog):
    def __init__(self, settings: QSettings, files: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Lọc tạp âm video")
        self.setMinimumSize(640, 520)
        self.runner: ffmpeg_tools.Runner | None = None
        self._busy = False
        self.outputs: list[str] = []

        head = QHBoxLayout()
        head.setSpacing(theme.SP["md"])
        ic = QLabel()
        icons.bind(ic, "waves", 28, "accent_text")
        ic.setFixedSize(28, 28)
        title = QLabel("Lọc tạp âm — gió, ù nền, tiếng xì")
        title.setObjectName("updateTitle")
        head.addWidget(ic)
        head.addWidget(title, 1)
        sub = w.muted("Giữ tiếng bước chân, nước, lửa…; hình giữ nguyên (không mã hoá lại). Mỗi file ra bản "
                      f"<b>tên{SUFFIX}</b> cạnh file gốc — file gốc không bị đổi. Như Premiere: <i>Essential Sound → "
                      "Repair → Reduce Noise</i>.")
        sub.setWordWrap(True)

        self.list = QListWidget()
        self.list.setToolTip("Kéo thả video / file nhạc vào đây")
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)
        add = QPushButton("Thêm file…")
        add.setIcon(icons.icon("file_plus", 14))
        add.clicked.connect(self._pick)
        clear = QPushButton("Bỏ hết")
        theme.tag(clear, variant="ghost")
        clear.clicked.connect(lambda: (self.list.clear(), self.go.setEnabled(False)))
        files_row = QHBoxLayout()
        files_row.addWidget(add)
        files_row.addWidget(clear)
        files_row.addStretch(1)

        self.level = combo([x for x in DENOISE if x[0] != "off"])
        set_combo(self.level, str(settings.value("denoise/level", "medium") or "medium"))
        self.open_after = QCheckBox("Mở thư mục khi xong")
        self.open_after.setChecked(str(settings.value("denoise/open", "true")).lower() in ("true", "1"))
        form = QFormLayout()
        form.addRow("Mức lọc", self.level)
        form.addRow(self.open_after)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.status = w.muted("Thêm file rồi bấm Lọc tạp âm.")
        self.status.setWordWrap(True)

        self.go = QPushButton("Lọc tạp âm")
        theme.tag(self.go, variant="primary")
        self.go.setIcon(icons.icon("waves", 15, "text_on_accent"))
        self.go.clicked.connect(self._start)
        self.close_btn = QPushButton("Đóng")
        self.close_btn.setMinimumWidth(96)  # đổi qua lại Đóng / Huỷ không bị cắt chữ
        self.close_btn.clicked.connect(self._close_or_cancel)
        bb = QHBoxLayout()
        bb.addStretch(1)
        bb.addWidget(self.close_btn)
        bb.addWidget(self.go)

        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SP["md"])
        lay.addLayout(head)
        lay.addWidget(sub)
        lay.addWidget(self.list, 1)
        lay.addLayout(files_row)
        lay.addLayout(form)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        lay.addLayout(bb)

        self._bridge = _Bridge(self)
        self._bridge.progress.connect(self._on_progress)
        self._bridge.finished.connect(self._on_file_done)
        self._bridge.all_done.connect(self._on_all_done)
        self.add_files(files or [])

    # ---------- danh sách file ----------
    def files(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def add_files(self, paths: list[str]) -> None:
        if self._busy:
            return
        exts = w.VIDEO_EXTS | AUDIO_EXTS
        have = {os.path.normcase(p) for p in self.files()}
        for p in w.expand_dropped(paths, exts, True):
            p = os.path.normpath(p)
            if os.path.normcase(p) not in have and SUFFIX not in Path(p).stem:  # bỏ qua bản đã lọc
                item = QListWidgetItem(_label(p))
                item.setData(Qt.ItemDataRole.UserRole, p)
                item.setToolTip(p)
                self.list.addItem(item)
                have.add(os.path.normcase(p))
        self.go.setEnabled(self.list.count() > 0 and denoise.available())
        if not denoise.available():
            self.status.setText("Thiếu thư viện numpy — cài lại app bản mới nhất.")

    def _pick(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(w.VIDEO_EXTS | AUDIO_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn video / file nhạc cần lọc tạp âm",
                                                str(self.settings.value("denoise/dir", "") or ""),
                                                f"Video và nhạc ({exts})")
        if files:
            self.settings.setValue("denoise/dir", os.path.dirname(files[0]))
            self.add_files(files)

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        self.add_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # ---------- chạy ----------
    def _start(self) -> None:
        files = self.files()
        if not files or self._busy:
            return
        level = self.level.currentData()
        self.settings.setValue("denoise/level", level)
        self.settings.setValue("denoise/open", self.open_after.isChecked())
        self._busy = True
        self.outputs = []
        self._errors: list[str] = []
        self.go.setEnabled(False)
        self.list.setEnabled(False)
        self.close_btn.setText("Huỷ")
        self.runner = ffmpeg_tools.Runner()
        runner, bridge, n = self.runner, self._bridge, len(files)

        def work() -> None:
            for i, src in enumerate(files):
                try:
                    out = output_path(src)
                    bridge.progress.emit(i, 0.0, f"Đang lọc {i + 1}/{n}: {Path(src).name}")
                    denoise_file(runner, src, level, out,
                                 lambda f, i=i: bridge.progress.emit(i, f * 0.9, ""))
                    bridge.finished.emit(i, str(out), "")
                except ffmpeg_tools.CancelledError:
                    break
                except Exception as e:  # noqa: BLE001
                    bridge.finished.emit(i, "", str(e)[-400:])
            bridge.all_done.emit()

        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, i: int, frac: float, text: str) -> None:
        n = max(1, self.list.count())
        self.bar.setValue(int(1000 * (i + frac) / n))
        if text:
            self.status.setText(text)

    def _on_file_done(self, i: int, out: str, err: str) -> None:
        item = self.list.item(i)
        src = item.data(Qt.ItemDataRole.UserRole)
        if out:
            self.outputs.append(out)
            item.setText(f"{_label(src)}   →   {Path(out).name}")
        else:
            self._errors.append(f"{Path(src).name}: {err}")
            item.setText(f"{_label(src)}   —   lỗi")

    def _on_all_done(self) -> None:
        cancelled = bool(self.runner and self.runner.cancelled)
        self._busy = False
        self.runner = None
        self.bar.setValue(1000 if not cancelled else self.bar.value())
        self.close_btn.setText("Đóng")
        self.list.setEnabled(True)
        self.go.setEnabled(True)  # chạy lại (vd đổi mức lọc): ra thêm bản _DeNoise2, không ghi đè bản trước
        bits = [f"Xong {len(self.outputs)} file"] + ([f"{len(self._errors)} lỗi"] if self._errors else [])
        text = "Đã huỷ. " if cancelled else ""
        self.status.setText(text + " · ".join(bits) + "." + ("\n" + "\n".join(self._errors[:3]) if self._errors else ""))
        if self.outputs and self.open_after.isChecked() and not cancelled:
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.outputs[-1])])

    def _close_or_cancel(self) -> None:
        if self._busy and self.runner:
            self.runner.cancel()
            self.status.setText("Đang huỷ…")
            return
        self.reject()

    def reject(self) -> None:
        if self._busy and self.runner:
            self.runner.cancel()
        super().reject()
