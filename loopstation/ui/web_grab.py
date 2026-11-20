"""Trình duyệt trong app (QtWebEngine) để lấy video Douyin: mở trang ẩn, đọc link file trong thẻ <video>.

Douyin hỏi xác minh (thấy khung captcha, hoặc quá `verify_after` giây chưa ra link) → mở CỬA SỔ trình duyệt hiện rõ,
TẢI LẠI trang ngay trong cửa sổ đó để người dùng tự xác minh như trên trình duyệt thường; xác minh xong (trang ra
video) thì lấy link, đóng cửa sổ. App không né / tự giải xác minh. Hồ sơ trình duyệt riêng của app (cookie giữ cho lần
sau → ít bị hỏi lại), không đụng trình duyệt của máy. QtWebEngine chỉ được nạp khi cần."""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..core import douyin, ffmpeg_tools
from . import theme
from . import widgets as w

META_WAIT = 6.0  # giây chờ tiêu đề / thời lượng sau khi đã có link video
VERIFY_WAIT = 180.0  # cửa sổ xác minh đang mở: chờ người dùng tối đa 3 phút
GIVE_UP_MSG = "Không lấy được video Douyin — thử lại, hoặc bấm đúp để mở trên trình duyệt"


class WebGrabber(QObject):
    grabbed = Signal(str, dict)  # (link đã xếp hàng, dữ liệu douyin.parse_grab)
    failed = Signal(str, str)  # (link, câu lỗi)
    verifying = Signal(str)  # (link) — đã mở cửa sổ xác minh

    def __init__(self, parent=None, storage: Path | None = None, verify_after: float = 12.0,
                 give_up: float = 120.0, show_verify: bool = True, poll_ms: int = 1500):
        super().__init__(parent)
        self._storage = storage
        self._verify_after, self._give_up, self._show_verify = verify_after, give_up, show_verify
        self._queue: list[str] = []
        self._cur = ""
        self._t0 = 0.0
        self._seen_at: float | None = None
        self._page = None  # trang ẩn
        self._active = None  # trang đang đọc (ẩn, hoặc trang trong cửa sổ xác minh)
        self._profile = None
        self._dlg: QDialog | None = None
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
        self._active = None

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
        self._active = self._page
        self._page.load(QUrl(self._cur))
        self._timer.start()

    def _poll(self) -> None:
        if not self._cur or self._active is None:
            return
        link = self._cur
        elapsed = time.monotonic() - self._t0
        limit = VERIFY_WAIT if self._dlg is not None else self._give_up
        if elapsed > limit:
            self._cur = ""
            self.failed.emit(link, GIVE_UP_MSG)
            self._next()
            return
        if elapsed > self._verify_after and self._show_verify and self._dlg is None:
            self._open_dialog()
            return
        self._active.runJavaScript(douyin.JS_GRAB, 0, lambda r, lk=link: self._on_js(lk, r))

    def _on_js(self, link: str, result) -> None:
        if link != self._cur or not result:
            return
        try:
            data = douyin.parse_grab(json.loads(result), link)
        except (ValueError, TypeError):
            return
        if not data["srcs"]:
            if data["verify"] and self._show_verify and self._dlg is None:
                self._open_dialog()  # thấy khung xác minh: mở cửa sổ ngay, không chờ hết giờ
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
        """Cửa sổ xác minh: trang MỚI trong cửa sổ hiện rõ (cùng hồ sơ, cùng cookie), tải lại link để người dùng tự
        xác minh; trang ẩn ngừng tải để không chạy song song."""
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView
        link = self._cur
        dlg = QDialog()
        dlg.setWindowTitle("Douyin cần xác minh — KT Loop Station")
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(12, 12, 12, 12)
        tip = QLabel("<b>Douyin đang hỏi xác minh.</b> Làm theo hướng dẫn trong trang (kéo thanh / bấm hình) như trên "
                     "trình duyệt thường. Xong là app tự lấy video và đóng cửa sổ này.")
        tip.setWordWrap(True)
        v.addWidget(tip)
        view = QWebEngineView(dlg)
        vpage = QWebEnginePage(self._profile, view)
        vpage.setAudioMuted(True)
        view.setPage(vpage)
        v.addWidget(view, 1)
        row = QHBoxLayout()
        reload_btn = QPushButton("Tải lại trang")
        theme.tag(reload_btn, variant="ghost")
        reload_btn.clicked.connect(lambda: vpage.load(QUrl(link)))
        cancel_btn = QPushButton("Bỏ qua video này")
        theme.tag(cancel_btn, variant="ghost")
        cancel_btn.clicked.connect(dlg.reject)
        row.addWidget(w.muted("Cửa sổ chờ tối đa 3 phút."), 1)
        row.addWidget(reload_btn)
        row.addWidget(cancel_btn)
        v.addLayout(row)
        dlg.resize(1100, 820)
        dlg.rejected.connect(self._user_closed)
        self._dlg = dlg
        if self._page is not None:
            self._page.load(QUrl("about:blank"))
        self._active = vpage
        self._t0 = time.monotonic()  # đếm lại: chờ người dùng xác minh
        self._seen_at = None
        vpage.load(QUrl(link))
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        self.verifying.emit(link)

    def _user_closed(self) -> None:
        if self._dlg is None:
            return
        self._dlg = None
        self._active = self._page
        link, self._cur = self._cur, ""
        if link:
            self.failed.emit(link, "Đã bỏ qua xác minh Douyin — bấm chuột phải › Thử lại khi sẵn sàng")
        self._next()

    def _close_dialog(self) -> None:
        dlg, self._dlg = self._dlg, None
        self._active = self._page
        if dlg is not None:
            dlg.blockSignals(True)
            dlg.close()
            dlg.deleteLater()
