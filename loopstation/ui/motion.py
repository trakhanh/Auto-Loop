"""Chuyển động giao diện: cuộn mượt, hộp thoại hiện dần, thông báo nổi (toast), thanh trượt, vạch chọn thanh bên,
bộ chọn có khối sáng trượt (SegmentBox), chữ hiện dần khi đổi, gợn sóng khi bấm + viền sáng ô đang gõ
(effects.py).

Tất cả hiệu ứng đều ngắn (150–260 ms) và dùng đường cong OutCubic để cảm giác nhanh mà không giật.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRect, Qt, QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractScrollArea, QApplication, QDialog, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPlainTextEdit, QScrollBar, QWidget,
)

from .effects import Ripple, on_focus, wants_focus_glow

EASE = QEasingCurve.Type.OutCubic


class UiMotion(QObject):
    """Bộ lọc sự kiện toàn app: cuộn mượt cho mọi vùng cuộn + hộp thoại hiện dần khi mở."""

    SCROLL_MS = 240

    def __init__(self, parent=None):
        super().__init__(parent)
        self._targets: dict[int, int] = {}

    def eventFilter(self, obj, event):  # noqa: N802
        t = event.type()
        if t == QEvent.Type.Polish:
            if isinstance(obj, QAbstractItemView):
                # cuộn theo điểm ảnh thay vì nhảy từng dòng
                obj.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
                obj.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
                obj.verticalScrollBar().setSingleStep(18)
            return False
        if t == QEvent.Type.Show and isinstance(obj, QDialog) and obj.isWindow():
            from . import branding
            branding.apply_window_frame(obj)  # thanh tiêu đề + viền tối theo màu theme (như cửa sổ chính)
            fade_window_in(obj, 160)
            return False
        if t == QEvent.Type.Wheel:
            return self._wheel(obj, event)
        if t == QEvent.Type.MouseButtonPress:
            from PySide6.QtWidgets import QPushButton
            if isinstance(obj, QPushButton) and obj.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
                Ripple(obj, event.position().toPoint())  # gợn sóng từ chỗ bấm
            return False
        if t in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            if isinstance(obj, QWidget) and wants_focus_glow(obj):
                on_focus(obj, t == QEvent.Type.FocusIn)  # viền sáng ô đang gõ
            return False
        return False

    def _wheel(self, obj, ev) -> bool:
        if not ev.pixelDelta().isNull() or ev.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False  # bàn di chuột đã mượt sẵn; Ctrl/Shift để mặc định
        dy = ev.angleDelta().y()
        if not dy or ev.angleDelta().x():
            return False
        bar = None
        if isinstance(obj, QScrollBar) and obj.orientation() == Qt.Orientation.Vertical:
            bar = obj
        else:
            area = obj.parentWidget() if isinstance(obj, QWidget) else None
            if isinstance(area, QAbstractScrollArea) and obj is area.viewport() \
                    and not isinstance(area, QPlainTextEdit):  # ô chữ cuộn theo dòng: để mặc định
                bar = area.verticalScrollBar()
        if bar is None or bar.maximum() <= bar.minimum() or not bar.isEnabled():
            return False
        key = id(bar)
        anim: QVariantAnimation | None = bar.property("_smooth_anim")
        running = anim is not None and anim.state() == QAbstractAnimation.State.Running
        start_target = self._targets.get(key, bar.value()) if running else bar.value()
        step = max(48, bar.singleStep() * QApplication.wheelScrollLines())
        target = int(min(bar.maximum(), max(bar.minimum(), start_target - dy / 120 * step)))
        if target == bar.value() and not running:
            return False  # đã chạm đầu/cuối: để vùng cuộn bên ngoài nhận
        self._targets[key] = target
        if anim is None:
            anim = QVariantAnimation(bar)
            anim.setEasingCurve(EASE)
            anim.valueChanged.connect(lambda v, b=bar: b.setValue(int(v)))
            bar.setProperty("_smooth_anim", anim)
            bar.sliderPressed.connect(anim.stop)
            bar.destroyed.connect(lambda *_, k=key: self._targets.pop(k, None))
        anim.stop()
        anim.setDuration(self.SCROLL_MS)
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        anim.start()
        return True


def fade_window_in(win: QWidget, ms: int = 220) -> None:
    """Cửa sổ hiện dần (độ mờ 0 → 1)."""
    win.setWindowOpacity(0.0)
    anim = QPropertyAnimation(win, b"windowOpacity", win)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(EASE)
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def slide_visible(widget: QWidget, show: bool, ms: int = 220) -> None:
    """Hiện / ẩn widget bằng cách trượt chiều cao (cho thanh gợi ý, thông báo trong trang)."""
    if show == (widget.isVisible() and widget.maximumHeight() > 0):
        return
    old = widget.property("_slide_anim")
    if old is not None:
        old.stop()
    if show:
        widget.setMaximumHeight(0)
        widget.setVisible(True)
        end = max(1, widget.sizeHint().height())
    else:
        end = 0
    anim = QPropertyAnimation(widget, b"maximumHeight", widget)
    anim.setDuration(ms)
    anim.setStartValue(widget.height() if not show else 0)
    anim.setEndValue(end)
    anim.setEasingCurve(EASE)

    def done():
        if show:
            widget.setMaximumHeight(16777215)
        else:
            widget.setVisible(False)
            widget.setMaximumHeight(16777215)

    anim.finished.connect(done)
    widget.setProperty("_slide_anim", anim)
    anim.start()


class NavPill(QWidget):
    """Nền + vạch sáng của mục đang chọn ở thanh bên, trượt mượt khi đổi trang."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("navPill")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lower()
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(EASE)
        self._target: QWidget | None = None

    def move_to(self, button: QWidget | None, animate: bool = True) -> None:
        self._target = button
        if button is None or not button.isVisible():
            self.hide()
            return
        top_left = button.mapTo(self.parentWidget(), QPoint(0, 0))
        rect = QRect(top_left, button.size())
        self._anim.stop()
        if not animate or not self.isVisible() or self.geometry().isEmpty():
            self.setGeometry(rect)
            self.show()
            self.lower()
            return
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(rect)
        self._anim.start()

    def refresh(self) -> None:
        self.move_to(self._target, animate=False)


class Toast(QWidget):
    """Thông báo nổi nhỏ ở góc dưới phải, tự ẩn sau vài giây."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.host = host
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 16, 10)
        lay.setSpacing(10)
        self.dot = QLabel("●")
        self.dot.setObjectName("toastDot")
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setMaximumWidth(420)
        lay.addWidget(self.dot)
        lay.addWidget(self.text, 1)
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self._fade = QPropertyAnimation(self.effect, b"opacity", self)
        self._fade.setEasingCurve(EASE)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setEasingCurve(EASE)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._hide_anim)
        self._fade.finished.connect(self._after_fade)
        self.hide()

    def _home(self) -> QPoint:
        h = self.host
        return QPoint(h.width() - self.width() - 22, h.height() - self.height() - 78)  # trên nút "Tiếp theo"

    def show_message(self, text: str, kind: str = "ok", ms: int = 2800) -> None:
        from . import theme
        theme.tag(self.dot, tone=kind if kind in ("ok", "warn", "error") else "info")
        self.text.setText(text)
        self.text.setWordWrap(len(text) > 70)  # câu ngắn nằm trên một dòng
        self.adjustSize()
        home = self._home()
        self._fade.stop()
        self._slide.stop()
        self._hiding = False
        if not self.isVisible():
            self.move(home + QPoint(0, 18))
            self.effect.setOpacity(0.0)
            self.show()
        self.raise_()
        self._fade.setDuration(200)
        self._fade.setStartValue(self.effect.opacity())
        self._fade.setEndValue(1.0)
        self._slide.setDuration(260)
        self._slide.setStartValue(self.pos())
        self._slide.setEndValue(home)
        self._fade.start()
        self._slide.start()
        self._timer.start(ms)

    def _hide_anim(self) -> None:
        self._hiding = True
        self._fade.stop()
        self._fade.setDuration(260)
        self._fade.setStartValue(self.effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _after_fade(self) -> None:
        if getattr(self, "_hiding", False):
            self.hide()

    def reposition(self) -> None:
        if self.isVisible() and self._slide.state() != QAbstractAnimation.State.Running:
            self.move(self._home())


class SegmentBox(QWidget):
    """Bộ chọn nhiều lựa chọn (kiểu sản phẩm, Đơn giản / Đầy đủ…): một khối sáng trượt mượt sang nút được chọn.

    Nút truyền vào phải là nút bật / tắt (checkable) nằm trong một QButtonGroup loại trừ."""

    def __init__(self, buttons: list[QAbstractButton], parent=None):
        super().__init__(parent)
        self.setObjectName("segBox")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.pill = QWidget(self)
        self.pill.setObjectName("segPill")
        self.pill.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.pill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.pill.hide()
        self._anim = QPropertyAnimation(self.pill, b"geometry", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(EASE)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.buttons = list(buttons)
        for b in self.buttons:
            b.setObjectName("segBtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            lay.addWidget(b)
            b.toggled.connect(lambda on, bb=b: on and self._follow(bb, True))
            b.installEventFilter(self)

    def _current(self) -> QAbstractButton | None:
        return next((b for b in self.buttons if b.isChecked()), None)

    def _follow(self, b: QAbstractButton, animate: bool) -> None:
        if not b.isVisible() or b.width() <= 0:
            return
        rect = b.geometry()
        self._anim.stop()
        if not animate or not self.pill.isVisible() or not self.isVisible():
            self.pill.setGeometry(rect)
            self.pill.show()
            self.pill.lower()
            return
        self._anim.setStartValue(self.pill.geometry())
        self._anim.setEndValue(rect)
        self._anim.start()

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show) and obj is self._current()                 and self._anim.state() != QAbstractAnimation.State.Running:
            QTimer.singleShot(0, lambda: (cur := self._current()) is not None and self._follow(cur, False))
        return False

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        QTimer.singleShot(0, lambda: (cur := self._current()) is not None and self._follow(cur, False))


def fade_in(widget: QWidget, ms: int = 180, start: float = 0.25) -> None:
    """Widget (chữ hướng dẫn, chip…) hiện dần khi nội dung đổi — mắt nhận ra có thay đổi mà không bị giật."""
    if not widget.isVisible():
        return
    eff = widget.graphicsEffect()
    if eff is not None and not isinstance(eff, QGraphicsOpacityEffect):
        return  # widget đang có quầng sáng: không đè
    if eff is None:
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)
    anim = widget.property("_fade_anim")
    if anim is None:
        anim = QPropertyAnimation(eff, b"opacity", widget)
        anim.setEasingCurve(EASE)
        # xong thì bỏ hiệu ứng: chữ vẽ thẳng, sắc nét như thường
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        widget.setProperty("_fade_anim", anim)
    else:
        anim.stop()
        anim.setTargetObject(eff)
    anim.setDuration(ms)
    anim.setStartValue(start)
    anim.setEndValue(1.0)
    anim.start()
