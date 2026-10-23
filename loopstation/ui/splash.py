"""Màn hình chờ lúc mở app: logo, tên app, thanh tiến trình mảnh có ánh sáng chạy, hiện/ẩn dần."""
from __future__ import annotations

import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from . import branding, theme
from .theme import APP_NAME, APP_VERSION, AUTHOR

MIN_SHOW = 0.9  # giây: đủ để thấy, không làm chậm việc mở app


class Splash(QWidget):
    W, H = 440, 260

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(self.W, self.H)
        self.status = "Đang khởi động…"
        self.progress = 0.0  # 0..1 hiển thị (chạy mượt tới mục tiêu)
        self.shine = 0.0  # 0..1 vệt sáng chạy trên thanh
        self.pulse = 0.0
        self._t0 = time.monotonic()
        self._logo = branding.pixmap(68, self.devicePixelRatioF())
        self._prog = QVariantAnimation(self)
        self._prog.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._prog.valueChanged.connect(self._set_progress)
        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._advance)
        self._tick.start()
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - self.W // 2, geo.center().y() - self.H // 2)

    # ---------- trạng thái ----------
    def _set_progress(self, v) -> None:
        self.progress = float(v)
        self.update()

    def _advance(self) -> None:
        self.shine = (self.shine + 0.012) % 1.0
        self.pulse = (self.pulse + 0.02) % 2.0
        self.update()

    def step(self, text: str, value: float) -> None:
        """Đổi chữ trạng thái và chạy thanh tiến trình tới `value` (0..1)."""
        self.status = text
        self._prog.stop()
        self._prog.setDuration(380)
        self._prog.setStartValue(self.progress)
        self._prog.setEndValue(max(self.progress, value))
        self._prog.start()
        self._pump(0.05)

    def _pump(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.008)

    def start(self) -> None:
        self.setWindowOpacity(0.0)
        self.show()
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(200)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.start()
        self._pump(0.12)

    def finish(self, win: QWidget) -> None:
        """Chạy thanh tới 100%, đợi đủ thời gian tối thiểu rồi mờ dần; cửa sổ chính hiện dần lên."""
        self.step("Sẵn sàng!", 1.0)
        left = MIN_SHOW - (time.monotonic() - self._t0)
        self._pump(max(0.25, left))
        from .motion import fade_window_in
        fade_window_in(win, 280)
        win.show()
        win.raise_()
        win.activateWindow()
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(220)
        fade.setStartValue(self.windowOpacity())
        fade.setEndValue(0.0)
        fade.finished.connect(self.close)
        fade.finished.connect(self._tick.stop)
        fade.start()

    # ---------- vẽ ----------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(8, 8, self.W - 16, self.H - 16)
        path = QPainterPath()
        path.addRoundedRect(card, theme.R["xl"], theme.R["xl"])
        # bóng mờ nhẹ
        for i, a in ((6, 18), (3, 30)):
            sh = QPainterPath()
            sh.addRoundedRect(card.adjusted(-i / 2, -i / 2 + 2, i / 2, i / 2 + 2), 20, 20)
            p.fillPath(sh, theme.qcolor("black", a))
        p.fillPath(path, theme.qcolor("panel"))
        p.setPen(QPen(theme.qcolor("accent", 110), 1.2))
        p.drawPath(path)

        # quầng sáng nhịp thở sau logo
        cx, cy = self.W / 2, 82
        k = 0.5 - abs(self.pulse - 1.0) / 2  # 0..0.5
        glow = theme.qcolor("accent", int(40 + 70 * k))
        for r, alpha in ((52, 0.35), (44, 0.6), (38, 1.0)):
            c = QColor(glow)
            c.setAlpha(int(glow.alpha() * alpha))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        lw = self._logo.width() / self._logo.devicePixelRatioF()
        p.drawPixmap(int(cx - lw / 2), int(cy - lw / 2), self._logo)

        f = QFont(self.font())
        f.setPointSize(17)
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.qcolor("text"))
        p.drawText(QRectF(0, 128, self.W, 30), Qt.AlignmentFlag.AlignCenter, APP_NAME)
        f2 = QFont(self.font())
        f2.setPointSize(9)
        p.setFont(f2)
        p.setPen(theme.qcolor("text_2"))
        p.drawText(QRectF(0, 158, self.W, 20), Qt.AlignmentFlag.AlignCenter, f"{AUTHOR} · Phiên bản {APP_VERSION}")

        # thanh tiến trình mảnh + vệt sáng
        bar = QRectF(70, 198, self.W - 140, 5)
        track = QPainterPath()
        track.addRoundedRect(bar, 2.5, 2.5)
        p.fillPath(track, theme.qcolor("line"))
        done = QRectF(bar.left(), bar.top(), bar.width() * max(0.02, self.progress), bar.height())
        fill = QPainterPath()
        fill.addRoundedRect(done, 2.5, 2.5)
        p.fillPath(fill, theme.qcolor("accent"))
        sx = bar.left() + (bar.width() + 120) * self.shine - 60
        sg = QLinearGradient(sx - 50, 0, sx + 50, 0)
        sg.setColorAt(0.0, theme.qcolor("white", 0))
        sg.setColorAt(0.5, theme.qcolor("white", 120))
        sg.setColorAt(1.0, theme.qcolor("white", 0))
        p.save()
        p.setClipPath(fill)
        p.fillRect(QRectF(sx - 50, bar.top(), 100, bar.height()), sg)
        p.restore()

        p.setFont(f2)
        p.setPen(theme.qcolor("text_muted"))
        p.drawText(QRectF(0, 210, self.W, 22), Qt.AlignmentFlag.AlignCenter, self.status)
