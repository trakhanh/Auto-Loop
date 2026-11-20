"""Trình duyệt ẩn trong app (QtWebEngine) để lấy video Douyin: mở trang, đọc link file trong thẻ <video>.

Douyin bắt xác minh (không ra link sau `verify_after` giây) → hiện cửa sổ trình duyệt cho người dùng tự kéo thanh xác
minh; xong thì lấy tiếp. Hồ sơ trình duyệt riêng của app (cookie giữ cho lần sau), không đụng trình duyệt của máy.
QtWebEngine chỉ được nạp khi cần (mở app không chậm thêm)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout

from ..core import douyin, ffmpeg_tools
from . import widgets as w

META_WAIT = 6.0  # giây chờ tiêu đề / thời lượng sau khi đã có link video
GIVE_UP_MSG = "Không lấy được video Douyin — thử lại, hoặc bấm đúp để mở trên trình duyệt"


class WebGrabber(QObject):
    grabbed = Signal(str, dict)  # (link đã xếp hàng, dữ liệu douyin.parse_grab)
    failed = Signal(str, str)  # (link, câu lỗi)

    def __init__(self, parent=None, storage: Path | None = None, verify_after: float = 12.0,
                 give_up: float = 120.0, show_verify: bool = True, poll_ms: int = 1500):
        super().__init__(parent)
        self._storage = storage
        self._verify_after, self._give_up, self._show_verify = verify_after, give_up, show_verify
        self._queue: list[str] = []
        self._cur = ""
        self._t0 = 0.0
        self._page = None
        self._profile = None
        self._dlg: QDialog | None = None
        self._seen_at: float | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self._poll)

    def busy(self) -> bool:
        return bool(self._cur or self._queue)

    def grab(self, link: str) -> None:
        self._queue.append(link)
        if not self._cur:
            self._next()

    def cancel(self, link: str) -> None:
        if link in self._queue:
            self._queue.remove(link)

    def shutdown(self) -> None:
        self._timer.stop()
        self._queue.clear()
        self._cur = ""
        self._close_dialog()
        if self._page is not None:
            self._page.deleteLater()
            self._page = None

    # ---------- bên trong ----------
    def _ensure(self) -> None:
        if self._page is not None:
            return
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        self._profile = QWebEngineProfile("ktls-web", self)
        store = self._storage or (ffmpeg_tools.data_dir() / "web")
        store.mkdir(parents=True, exist_ok=True)
        self._profile.setPersistentStoragePath(str(store))
        self._profile.setCachePath(str(store / "cache"))
        self._profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self._page = QWebEnginePage(self._profile, self)
        self._page.setAudioMuted(True)

    def _next(self) -> None:
        self._close_dialog()
        if not self._queue:
            self._cur = ""
            self._timer.stop()
            return
        self._cur = self._queue.pop(0)
        self._t0 = time.monotonic()
        self._seen_at = None
        try:
            self._ensure()
        except Exception as e:  # noqa: BLE001 — thiếu QtWebEngine (bản cài hỏng)
            link, self._cur = self._cur, ""
            self.failed.emit(link, f"Trình duyệt trong app không chạy được: {e}")
            self._next()
            return
        self._page.load(QUrl(self._cur))
        self._timer.start()

    def _poll(self) -> None:
        if not self._cur or self._page is None:
            return
        link = self._cur
        elapsed = time.monotonic() - self._t0
        if elapsed > self._give_up:
            self._cur = ""
            self.failed.emit(link, GIVE_UP_MSG)
            self._next()
            return
        if elapsed > self._verify_after and self._show_verify and self._dlg is None:
            self._open_dialog()
        self._page.runJavaScript(douyin.JS_GRAB, 0, lambda r, lk=link: self._on_js(lk, r))

    def _on_js(self, link: str, result) -> None:
        if link != self._cur or not result:
            return
        try:
            data = douyin.parse_grab(json.loads(result), link)
        except (ValueError, TypeError):
            return
        if not data["srcs"]:
            return
        # link video thường có trước tiêu đề / thời lượng: chờ thêm tối đa META_WAIT giây cho đủ thông tin
        if (not data["title"] or not data["duration"]) and time.monotonic() - self._t0 < self._src_seen():
            return
        self._cur = ""
        self.grabbed.emit(link, data)
        self._next()

    def _src_seen(self) -> float:
        """Hạn chờ thông tin: tính từ lần đầu thấy link video."""
        if self._seen_at is None:
            self._seen_at = time.monotonic() - self._t0
        return self._seen_at + META_WAIT

    def _open_dialog(self) -> None:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        dlg = QDialog()
        dlg.setWindowTitle("Douyin cần xác minh")
        v = QVBoxLayout(dlg)
        v.addWidget(w.muted("Douyin đang hỏi xác minh: kéo thanh / bấm theo hướng dẫn trong trang. Xong, app tự tải "
                            "tiếp và đóng cửa sổ này."))
        view = QWebEngineView(dlg)
        view.setPage(self._page)
        v.addWidget(view, 1)
        dlg.resize(1000, 760)
        dlg.rejected.connect(lambda: self._user_closed())
        self._dlg = dlg
        dlg.show()

    def _user_closed(self) -> None:
        if self._dlg is None:
            return
        self._dlg = None
        link, self._cur = self._cur, ""
        if link:
            self.failed.emit(link, "Đã đóng cửa sổ xác minh Douyin")
        self._next()

    def _close_dialog(self) -> None:
        dlg, self._dlg = self._dlg, None
        if dlg is not None:  # trang có cha là WebGrabber: đóng cửa sổ không xoá trang (dùng tiếp)
            dlg.blockSignals(True)
            dlg.close()
            dlg.deleteLater()

