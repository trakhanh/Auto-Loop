"""Hiệu ứng trang trí nhẹ, dùng chung toàn app:

- Glow: quầng sáng màu quanh nút / thẻ (sáng lên khi rê chuột; nút chính có thể "thở" nhẹ để mời bấm).
- Ripple: gợn sóng lan ra từ chỗ bấm chuột trên nút.
- FocusGlow: ô đang gõ có viền sáng mờ theo màu chủ đạo.
- Shimmer: vệt sáng chạy trên thanh tiến trình trong lúc đang xuất.
- AccentLine: vạch dải màu dưới thanh trên cùng; đang xuất thì dải màu chạy liên tục.

Màu luôn đọc từ theme.C lúc vẽ, nên đổi bộ màu chủ đạo là các hiệu ứng đổi theo ngay.
Mọi hiệu ứng đều tự tắt khi không cần (không tốn công vẽ lúc đứng yên) để app luôn mượt.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QObject, QPoint, QPointF, Qt, QTimer, \
    QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QComboBox, QGraphicsDropShadowEffect, QLineEdit, QProgressBar, QWidget,
)

from . import theme

EASE = QEasingCurve.Type.OutCubic


class Glow(QObject):
    """Quầng sáng màu (bóng đổ màu chủ đạo) quanh widget.

    idle > 0: lúc thường vẫn sáng nhẹ. breathe(True): quầng sáng "thở" chậm (2,6 giây một nhịp)."""

    def __init__(self, widget: QWidget, color: str | None = None, idle: float = 0.0, blur: float = 28,
                 offset_y: float = 5, alpha: int = 120):
        super().__init__(widget)
        self.w = widget
        self.color, self.idle, self.blur, self.alpha = color, idle, blur, alpha
        self.fx = QGraphicsDropShadowEffect(widget)
        self.fx.setOffset(0, offset_y)
        widget.setGraphicsEffect(self.fx)
        self._hover = 0.0
        self._phase = 0.0
        self._want_breath = False
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(EASE)
        self._anim.valueChanged.connect(self._set_hover)
        self._breath = QVariantAnimation(self)
        self._breath.setDuration(2600)
        self._breath.setStartValue(0.0)
        self._breath.setKeyValueAt(0.5, 1.0)
        self._breath.setEndValue(0.0)
        self._breath.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._breath.setLoopCount(-1)
        self._breath.valueChanged.connect(self._set_phase)
        widget.installEventFilter(self)
        self.refresh()

    def _set_hover(self, v) -> None:
        self._hover = float(v)
        self.refresh()

    def _set_phase(self, v) -> None:
        self._phase = float(v)
        self.refresh()

    def breathing(self) -> bool:
        return self._breath.state() == QAbstractAnimation.State.Running

    def refresh(self) -> None:
        if not self.w.isEnabled():
            t = 0.0
        else:
            rest = self.idle + (0.45 * self._phase if self.breathing() else 0.0)
            t = max(self._hover, min(1.0, rest))
        self.fx.setEnabled(t > 0.01)  # không sáng: tắt hẳn, widget vẽ thẳng như thường
        self.fx.setBlurRadius(self.blur * (0.35 + 0.65 * t))
        c = QColor(self.color or theme.C["accent"])
        c.setAlpha(int(self.alpha * t))
        self.fx.setColor(c)

    def breathe(self, on: bool) -> None:
        self._want_breath = on
        self._sync_breath()

    def _sync_breath(self) -> None:
        # chỉ "thở" khi widget đang hiện và bấm được: trang khác / đang khoá thì dừng hẳn, không tốn công vẽ
        on = self._want_breath and self.w.isVisible() and self.w.isEnabled()
        if on and not self.breathing():
            self._breath.start()
        elif not on and self.breathing():
            self._breath.stop()
            self._phase = 0.0
            self.refresh()

    def _go(self, end: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(end)
        self._anim.start()

    def eventFilter(self, obj, ev):  # noqa: N802
        t = ev.type()
        if t == QEvent.Type.Enter and obj.isEnabled():
            self._go(1.0)
        elif t in (QEvent.Type.Leave, QEvent.Type.Hide):
            self._go(0.0)
        elif t == QEvent.Type.EnabledChange:
            self.refresh()
        if t in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.EnabledChange) and self._want_breath:
            QTimer.singleShot(0, self._sync_breath)
        return False


class Ripple(QWidget):
    """Gợn sóng lan ra từ chỗ bấm chuột, mờ dần trong ~0,45 giây rồi tự xoá."""

    def __init__(self, button: QWidget, pos: QPoint):
        super().__init__(button)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        r = button.rect()
        self.setGeometry(r)
        self.center = QPointF(pos)
        self.max_r = max(((pos.x() - x) ** 2 + (pos.y() - y) ** 2) ** 0.5
                         for x, y in ((r.left(), r.top()), (r.right(), r.top()), (r.left(), r.bottom()),
                                      (r.right(), r.bottom())))
        self.t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(460)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(EASE)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self.deleteLater)
        self.show()
        self.raise_()
        self._anim.start()

    def _step(self, v) -> None:
        self.t = float(v)
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        rad = min(12.0, self.height() / 2)
        clip.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), rad, rad)
        p.setClipPath(clip)
        c = QColor(theme.C["soft"])
        c.setAlpha(int(80 * (1 - self.t)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        r = self.max_r * (0.2 + 0.8 * self.t)
        p.drawEllipse(self.center, r, r)


class FocusGlow(QObject):
    """Viền sáng mờ quanh ô đang gõ (hiện / tắt mượt; tắt xong thì gỡ hẳn hiệu ứng)."""

    def __init__(self, widget: QWidget):
        super().__init__(widget)
        self.w = widget
        self.fx = QGraphicsDropShadowEffect(widget)
        self.fx.setOffset(0, 0)
        self.fx.setBlurRadius(0)
        widget.setGraphicsEffect(self.fx)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(EASE)
        self._anim.valueChanged.connect(self._apply)
        self._anim.finished.connect(self._done)
        self._t = 0.0
        self._target = 0.0

    def _apply(self, v) -> None:
        self._t = float(v)
        self.fx.setBlurRadius(16 * self._t)
        c = QColor(theme.C["accent"])
        c.setAlpha(int(170 * self._t))
        self.fx.setColor(c)

    def go(self, on: bool) -> None:
        self._target = 1.0 if on else 0.0
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(self._target)
        self._anim.start()

    def _done(self) -> None:
        if self._target == 0.0:
            if self.w.graphicsEffect() is self.fx:
                self.w.setGraphicsEffect(None)
            self.w.setProperty("_focus_glow", None)
            self.deleteLater()


def wants_focus_glow(w) -> bool:
    if isinstance(w, QLineEdit):
        if isinstance(w.parentWidget(), (QAbstractSpinBox, QComboBox)):
            return False  # ô số / ô chọn: làm sáng chính ô đó, không phải ô chữ bên trong
    elif not isinstance(w, QAbstractSpinBox):
        return False
    a = w.parentWidget()
    while a is not None:  # ô sửa nhanh trong bảng (bấm đúp ô số): không làm sáng
        if isinstance(a, QAbstractItemView):
            return False
        a = a.parentWidget()
    return True


def on_focus(obj, focus_in: bool) -> None:
    """Gọi từ bộ lọc sự kiện toàn app (motion.UiMotion) khi một ô nhận / mất con trỏ gõ."""
    glow = obj.property("_focus_glow")
    if focus_in:
        if glow is None:
            if obj.graphicsEffect() is not None:
                return  # đã có hiệu ứng khác: không đè
            glow = FocusGlow(obj)
            obj.setProperty("_focus_glow", glow)
        glow.go(True)
    elif glow is not None:
        glow.go(False)


class GradientLabel(QWidget):
    """Tiêu đề lớn có chữ chuyển màu theo màu chủ đạo (màu → màu thứ hai)."""

    def __init__(self, text: str, object_name: str = "homeHero", parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QSizePolicy
        self.setObjectName(object_name)  # lấy cỡ chữ / độ đậm từ QSS như QLabel cùng tên
        self._text = text
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = text
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def _font(self):
        from PySide6.QtGui import QFont
        f = QFont(self.font())
        f.setWeight(QFont.Weight.ExtraBold)
        return f

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(self._font())
        return QSize(fm.horizontalAdvance(self._text) + 4, fm.height() + 4)

    def minimumSizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize
        return QSize(40, self.sizeHint().height())

    def paintEvent(self, e) -> None:  # noqa: N802
        from PySide6.QtGui import QFontMetrics
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = self._font()
        fm = QFontMetrics(f)
        text = fm.elidedText(self._text, Qt.TextElideMode.ElideRight, self.width() - 2)
        path = QPainterPath()
        path.addText(1, (self.height() + fm.ascent() - fm.descent()) / 2, f, text)
        w = max(1.0, fm.horizontalAdvance(text))
        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0.0, QColor("#ffffff"))
        g.setColorAt(0.45, QColor(theme.C["soft"]))
        g.setColorAt(1.0, QColor(theme.C["accent2"]).lighter(125))
        p.fillPath(path, g)


class Shimmer(QWidget):
    """Vệt sáng chạy dọc phần đã xong của thanh tiến trình (chỉ chạy trong lúc đang xuất)."""

    def __init__(self, bar: QProgressBar):
        super().__init__(bar)
        self.bar = bar
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._x = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        bar.installEventFilter(self)
        self.hide()

    def running(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        self.setGeometry(self.bar.rect())
        self.show()
        self.raise_()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._x = (self._x + 0.006) % 1.4
        self.update()

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Type.Resize:
            self.setGeometry(self.bar.rect())
        return False

    def paintEvent(self, e) -> None:  # noqa: N802
        bar = self.bar
        span = max(1, bar.maximum() - bar.minimum())
        fill_w = (self.width() - 4) * (bar.value() - bar.minimum()) / span
        if fill_w < 8:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(2, 2, fill_w, self.height() - 4, 8, 8)
        p.setClipPath(clip)
        band = max(60.0, fill_w * 0.22)
        cx = (self._x - 0.2) * (fill_w + band)
        g = QLinearGradient(cx - band, 0, cx + band, 0)
        g.setColorAt(0.0, QColor(255, 255, 255, 0))
        g.setColorAt(0.5, QColor(255, 255, 255, 90))
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(self.rect(), g)


class AccentLine(QWidget):
    """Vạch dải màu chủ đạo dưới thanh trên cùng. Đang xuất: dải màu chạy liên tục + đốm sáng chạy theo — đang ở
    trang nào cũng biết app đang làm việc."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(2)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def running(self) -> bool:
        return self._timer.isActive()

    def set_running(self, on: bool) -> None:
        if on and not self.running():
            self._timer.start()
        elif not on:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.004) % 1.0
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        w = max(1, self.width())
        a1, a2 = theme.qcolor("accent"), theme.qcolor("accent2")
        run = self.running()
        if not run:
            a1.setAlpha(170)
            a2.setAlpha(170)
        off = self._phase * w
        g = QLinearGradient(-off, 0, w - off, 0)
        g.setSpread(QLinearGradient.Spread.RepeatSpread)  # lặp liền mạch khi trượt
        g.setColorAt(0.0, a1)
        g.setColorAt(0.5, a2)
        g.setColorAt(1.0, a1)
        p.fillRect(self.rect(), g)
        if run:
            x = (self._phase * 3 % 1.0) * (w + 200) - 100
            hg = QLinearGradient(x - 90, 0, x + 90, 0)
            hg.setColorAt(0.0, QColor(255, 255, 255, 0))
            hg.setColorAt(0.5, QColor(255, 255, 255, 210))
            hg.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(self.rect(), hg)
