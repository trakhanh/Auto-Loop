"""Cập nhật trong app: kiểm tra bản mới (luồng nền) và hộp thoại tải + cài bản mới."""
from __future__ import annotations

import re
import threading
import time

from PySide6.QtCore import QObject, QSettings, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout,
)

from ..core import ffmpeg_tools, updater
from . import icons, theme
from . import widgets as w

AUTO_KEY = "update/auto"  # tự kiểm tra khi mở app
LAST_KEY = "update/last_check"  # lần kiểm tra gần nhất (giây)
SKIP_KEY = "update/skip"  # bản người dùng chọn "Bỏ qua bản này"
AUTO_EVERY_S = 6 * 3600


class UpdateChecker(QObject):
    """Hỏi GitHub ở luồng nền. checked(release | None, lỗi, bấm tay?)."""

    checked = Signal(object, str, bool)

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.busy = False
        self.latest: updater.Release | None = None

    def auto_on(self) -> bool:
        return self.settings.value(AUTO_KEY, "true") in (True, "true")

    def maybe_auto(self) -> None:
        """Lúc mở app: tự kiểm tra nếu được bật và đã lâu chưa kiểm tra."""
        if not updater.enabled() or not self.auto_on():
            return
        try:
            last = float(self.settings.value(LAST_KEY, 0) or 0)
        except (TypeError, ValueError):
            last = 0.0
        if time.time() - last >= AUTO_EVERY_S:
            self.check(manual=False)

    def check(self, manual: bool = True) -> None:
        if self.busy:
            return
        self.busy = True

        def work() -> None:
            try:
                rel, err = updater.fetch_latest(), ""
            except Exception as e:  # noqa: BLE001 — mất mạng, GitHub chặn…
                rel, err = None, str(e) or e.__class__.__name__
            try:
                self.checked.emit(rel, err, manual)
            except RuntimeError:  # app đã đóng
                pass

        threading.Thread(target=work, daemon=True).start()

    def on_result(self, rel, err: str) -> None:
        self.busy = False
        if rel is not None:
            self.latest = rel
            self.settings.setValue(LAST_KEY, time.time())

    def is_update(self, rel, include_skipped: bool = True) -> bool:
        if rel is None or not updater.is_newer(rel.version, theme.APP_VERSION):
            return False
        return include_skipped or self.settings.value(SKIP_KEY, "") != rel.version


class _Bridge(QObject):
    progress = Signal(int, int)
    done = Signal(str, str)  # (file bộ cài, lỗi)


class UpdateDialog(QDialog):
    """Có bản mới: ghi chú phát hành + Tải & cài đặt (app tự đóng, cài xong tự mở lại)."""

    def __init__(self, rel: updater.Release, settings: QSettings, parent=None):
        super().__init__(parent)
        self.rel = rel
        self.settings = settings
        self.install_path = ""  # bộ cài đã tải + kiểm tra xong → cửa sổ chính đóng app và chạy bộ cài
        self.skipped = False
        self._cancel = threading.Event()
        self._downloading = False
        self.setWindowTitle(f"Có bản mới {rel.version}")
        self.setMinimumSize(560, 460)

        head = QHBoxLayout()
        head.setSpacing(theme.SP['md'])
        ic = QLabel()
        icons.bind(ic, "download", 30, "accent_text")
        ic.setFixedSize(30, 30)
        title = QLabel(f"KT Loop Station <b>{rel.version}</b> đã có")
        title.setObjectName("updateTitle")
        head.addWidget(ic)
        head.addWidget(title, 1)
        sub = w.muted(f"Bạn đang dùng bản {theme.APP_VERSION}. Cài đè lên bản cũ: dự án, hàng đợi và cài đặt "
                      "được giữ nguyên. App sẽ tự đóng để cài rồi tự mở lại.")
        sub.setWordWrap(True)

        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        # `tên file` trong ghi chú: QTextBrowser hiện chữ code rất nhỏ → in đậm thay thế
        notes = re.sub(r"(?<!`)`([^`\n]+)`(?!`)", r"**\1**", rel.notes or "")
        self.notes.setMarkdown(notes or "_(Bản này không có ghi chú.)_")

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        self.status = w.muted("")
        self.status.setWordWrap(True)
        self.status.setVisible(False)

        self.install_btn = QPushButton("Tải && cài đặt" if updater.can_install() else "Mở trang tải")
        theme.tag(self.install_btn, variant="primary")
        self.install_btn.setIcon(icons.icon("download", 15, "text_on_accent"))
        self.install_btn.clicked.connect(self._install)
        self.later_btn = QPushButton("Để sau")
        self.later_btn.clicked.connect(self.reject)
        self.skip_btn = QPushButton("Bỏ qua bản này")
        theme.tag(self.skip_btn, variant="ghost")
        self.skip_btn.setToolTip("Không tự nhắc bản này nữa (vẫn cài được ở Cài đặt → Kiểm tra cập nhật)")
        self.skip_btn.clicked.connect(self._skip)
        page = QPushButton("Xem trên GitHub")
        theme.tag(page, variant="ghost")
        page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(rel.page)))
        bb = QHBoxLayout()
        bb.addWidget(self.skip_btn)
        bb.addWidget(page)
        bb.addStretch(1)
        bb.addWidget(self.later_btn)
        bb.addWidget(self.install_btn)

        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SP['md'])
        lay.addLayout(head)
        lay.addWidget(sub)
        lay.addWidget(self.notes, 1)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        lay.addLayout(bb)

        self._bridge = _Bridge(self)
        self._bridge.progress.connect(self._on_progress)
        self._bridge.done.connect(self._on_done)

    def _skip(self) -> None:
        self.settings.setValue(SKIP_KEY, self.rel.version)
        self.skipped = True
        self.reject()

    def _say(self, text: str, tone: str = "") -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))
        theme.tag(self.status, tone=tone)

    def _install(self) -> None:
        if not updater.can_install():
            QDesktopServices.openUrl(QUrl(self.rel.page))
            self.accept()
            return
        if not self.rel.url:
            self._say("Bản này chưa có bộ cài để tải — mở trang GitHub để tải tay.", "danger")
            return
        self._downloading = True
        self._cancel.clear()
        self.install_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.later_btn.setText("Huỷ tải")
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self._say("Đang tải bộ cài…")
        dest = ffmpeg_tools.data_dir() / "updates"
        rel, bridge, cancel = self.rel, self._bridge, self._cancel

        def work() -> None:
            try:
                updater.cleanup(dest, keep=f"KTLoopStation-Setup-{rel.version}.exe")
                path, err = str(updater.download(rel, dest, bridge.progress.emit, cancel)), ""
            except updater.CancelledError:
                path, err = "", "cancel"
            except Exception as e:  # noqa: BLE001
                path, err = "", str(e) or e.__class__.__name__
            try:
                bridge.done.emit(path, err)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.setValue(int(done * 1000 / total))
            self._say(f"Đang tải bộ cài… {done / 1048576:.0f} / {total / 1048576:.0f} MB")
        else:
            self._say(f"Đang tải bộ cài… {done / 1048576:.0f} MB")

    def _on_done(self, path: str, err: str) -> None:
        self._downloading = False
        self.later_btn.setText("Để sau")
        self.install_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        if err == "cancel":
            self.bar.setVisible(False)
            self._say("Đã huỷ tải.")
            return
        if err:
            self.bar.setVisible(False)
            self._say(f"Chưa tải được: {err[:300]}", "danger")
            self.install_btn.setText("Thử lại")
            return
        self.bar.setValue(1000)
        self._say("Đã tải và kiểm tra xong (SHA-256 khớp). Đang đóng app để cài…", "success")
        self.install_path = path
        self.accept()

    def reject(self) -> None:
        if self._downloading:
            self._cancel.set()  # _on_done sẽ báo "Đã huỷ tải"
            return
        super().reject()

    def closeEvent(self, e) -> None:  # noqa: N802
        self._cancel.set()
        super().closeEvent(e)


def status_text(rel, err: str) -> tuple[str, str]:
    """(chữ, tone) cho dòng trạng thái ở Cài đặt → Giới thiệu."""
    if err:
        return "Chưa kiểm tra được (mất mạng?): " + err.splitlines()[0][:120], "danger"
    if rel is None:
        return "", ""
    if updater.is_newer(rel.version, theme.APP_VERSION):
        return f"Có bản mới {rel.version}", "success"
    return f"Đang dùng bản mới nhất ({theme.APP_VERSION})", ""

