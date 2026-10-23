"""Màn hình chào lần đầu mở app: cách làm 3 bước + mở dự án mẫu để tập.

Là một lớp phủ ngay trong cửa sổ chính (không phải hộp thoại riêng): nền tối mờ, thẻ ở giữa hiện dần và trượt lên.
Bấm Bắt đầu / Esc / Enter để đóng. Mở lại được ở Cài đặt → Giao diện hiển thị → Xem lại màn hình chào.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QParallelAnimationGroup, QPoint, QPropertyAnimation, QSize, Qt,
    QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from . import branding, effects, icons, theme
from .theme import APP_NAME
from .widgets import sample_label

STEPS = (
    ("film", "accent_text", "Thêm video",
     "Kéo thả clip vào bảng. Gõ số lần loop ở cột <b>Số lần phát</b>: <b>70</b> = 70 lần, "
     "<b>10p</b> = đủ 10 phút."),
    ("music", "success_text", "Thêm nhạc",
     "Thêm playlist — nhạc <b>tự lặp</b> cho đủ độ dài video, bài cuối nhỏ dần. Thêm tiếng mưa, sóng… nếu muốn."),
    ("export", "info_text", "Xuất file",
     "Chọn thư mục lưu rồi bấm <b>Bắt đầu xuất</b>. Xem trước bất cứ lúc nào ở trình phát bên phải "
     "(phím <b>Space</b>)."),
)
def _label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return lab


class StepCard(QFrame):
    def __init__(self, num: int, ic: str, color: str, title: str, desc: str, parent=None):
        super().__init__(parent)
        self.setObjectName("welcomeStep")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP["xl"], theme.SP["lg"], theme.SP["xl"], theme.SP["lg"])
        lay.setSpacing(theme.SP["sm"])
        top = QHBoxLayout()
        top.setSpacing(theme.SP["md"])
        badge = QLabel(str(num))
        badge.setObjectName("welcomeNum")
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico = QLabel()
        ico.setPixmap(icons.pixmap(ic, 18, color))
        top.addWidget(badge)
        top.addWidget(ico)
        top.addWidget(_label(title, "welcomeStepTitle", wrap=False), 1)
        lay.addLayout(top)
        lay.addWidget(_label(desc, "welcomeStepText"))
        lay.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)


class WelcomeOverlay(QWidget):
    finished = Signal()
    sampleRequested = Signal(str)  # mở dự án mẫu (đường dẫn .lsproj)

    def __init__(self, host: QWidget, samples: list[Path] | None = None):
        super().__init__(host)
        self.setObjectName("welcomeOverlay")
        self.host = host
        self._dim = 0.0  # độ tối của nền (0 → 1), chạy theo hiệu ứng
        self._closing = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        card = QFrame()
        card.setObjectName("welcomeCard")
        card.setMaximumWidth(900)
        self.card = card
        cv = QVBoxLayout(card)
        cv.setContentsMargins(theme.SP["xxl"] + 4, theme.SP["xxl"], theme.SP["xxl"] + 4, theme.SP["xl"] + 4)
        cv.setSpacing(theme.SP["lg"])

        head = QHBoxLayout()
        head.setSpacing(theme.SP["lg"])
        logo = QLabel()
        logo.setPixmap(branding.pixmap(52, self.devicePixelRatioF()))
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(effects.HeadingLabel(f"Chào mừng đến với {APP_NAME}"))
        texts.addWidget(_label("Làm video loop dài cho YouTube — clip lặp ×70, nhạc tự lặp đủ giờ — chỉ với 3 bước.",
                               "muted"))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(texts, 1)
        cv.addLayout(head)

        self.steps_box = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.steps_box.setSpacing(theme.SP["md"])
        self._arrows: list[QLabel] = []
        for k, (ic, color, title, desc) in enumerate(STEPS):
            if k:
                arrow = QLabel()
                arrow.setPixmap(icons.pixmap("arrow_right", 14, "text_muted"))
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._arrows.append(arrow)
                self.steps_box.addWidget(arrow)
            self.steps_box.addWidget(StepCard(k + 1, ic, color, title, desc), 1)
        cv.addLayout(self.steps_box)


        foot = QHBoxLayout()
        foot.setSpacing(theme.SP["md"])
        foot.addWidget(_label("Bấm <b>F1</b> bất cứ lúc nào để xem hướng dẫn. Xem lại màn hình này ở <b>Cài đặt → Giao diện hiển thị</b>.", "muted"), 1)
        sample = next(iter(samples or []), None)
        if sample is not None:
            b = QPushButton(f"Mở dự án mẫu ({sample_label(sample.stem).replace('Thử: ', '')})")
            b.setObjectName("pill")
            b.setToolTip(f"Mở {sample.name} để bấm thử — đã có sẵn clip và nhạc")
            b.clicked.connect(lambda _=False, p=str(sample): self._finish(sample=p))
            foot.addWidget(b)
        self.start_btn = QPushButton("Bắt đầu")
        self.start_btn.setObjectName("primary")
        self.start_btn.setIcon(icons.icon("arrow_right", 15, "text_on_accent"))
        self.start_btn.setIconSize(QSize(15, 15))
        self.start_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.start_btn.setMinimumWidth(150)
        self.start_btn.clicked.connect(lambda: self._finish())
        foot.addWidget(self.start_btn)
        cv.addLayout(foot)

        # thẻ nằm giữa vùng cuộn: cửa sổ thấp vẫn cuộn xem hết được
        inner = QWidget()
        inner.setObjectName("welcomeInner")
        il = QVBoxLayout(inner)
        il.setContentsMargins(theme.SP["xxl"], theme.SP["xxl"], theme.SP["xxl"], theme.SP["xxl"])
        il.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card, 100)
        row.addStretch(1)
        il.addLayout(row)
        il.addStretch(1)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("welcomeScroll")
        self.scroll.setWidget(inner)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.scroll)

        host.installEventFilter(self)
        self.setGeometry(host.rect())
        self._dim_anim = QVariantAnimation(self)
        self._dim_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._dim_anim.valueChanged.connect(self._set_dim)
        self.hide()

    # ---------- hiện / ẩn ----------
    def open(self) -> None:
        self.setGeometry(self.host.rect())
        self._arrange()
        eff = QGraphicsOpacityEffect(self.card)  # thẻ ẩn hẳn cho tới khi bố cục xếp xong rồi mới hiện dần
        eff.setOpacity(0.0)
        self.card.setGraphicsEffect(eff)
        self.show()
        self.raise_()
        self.start_btn.setFocus()
        QTimer.singleShot(30, lambda: self._animate(True))

    def _finish(self, sample: str = "") -> None:
        if self._closing:
            return
        self._closing = True
        self.finished.emit()
        if sample:
            self.sampleRequested.emit(sample)
        self._animate(False)

    def _animate(self, show: bool) -> None:
        self._dim_anim.stop()
        self._dim_anim.setDuration(240 if show else 180)
        self._dim_anim.setStartValue(self._dim)
        self._dim_anim.setEndValue(1.0 if show else 0.0)
        eff = self.card.graphicsEffect()
        if not isinstance(eff, QGraphicsOpacityEffect):
            eff = QGraphicsOpacityEffect(self.card)
            eff.setOpacity(1.0)
            self.card.setGraphicsEffect(eff)
        fade = QPropertyAnimation(eff, b"opacity")
        fade.setDuration(260 if show else 170)
        fade.setStartValue(eff.opacity())
        fade.setEndValue(1.0 if show else 0.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)
        if show:
            # trượt lên nhẹ: chạy sau khi bố cục đã đặt thẻ vào chỗ
            end = self.card.pos()
            slide = QPropertyAnimation(self.card, b"pos")
            slide.setDuration(300)
            slide.setStartValue(end + QPoint(0, 22))
            slide.setEndValue(end)
            slide.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(slide)

        def done():
            self.card.setGraphicsEffect(None)  # xong: vẽ thẳng cho chữ sắc nét
            if not show:
                self.hide()
                self.deleteLater()

        group.finished.connect(done)
        self._dim_anim.start()
        group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _set_dim(self, v) -> None:
        self._dim = float(v)
        self.update()

    # ---------- bố cục co giãn ----------
    def _arrange(self) -> None:
        narrow = self.width() < 860
        d = QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        self.steps_box.setDirection(d)
        for a in self._arrows:
            a.setVisible(not narrow)

    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self.host and ev.type() == QEvent.Type.Resize:
            self.setGeometry(self.host.rect())
            self._arrange()
        return False

    # ---------- vẽ + phím ----------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), theme.qcolor("black", int(214 * self._dim)))

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        e.accept()  # bấm ra ngoài thẻ: không lọt xuống giao diện bên dưới

    def wheelEvent(self, e) -> None:  # noqa: N802
        e.accept()


def show_welcome(host: QWidget, on_done, on_sample=None) -> WelcomeOverlay:
    """Tạo + mở màn hình chào trên cửa sổ `host`. on_done() khi đóng; on_sample(path) khi chọn dự án mẫu."""
    from ..core import ffmpeg_tools as ft
    sample_dir = Path(ft.app_dir()) / "Mau-Test"
    samples = sorted(sample_dir.glob("*.lsproj")) if sample_dir.is_dir() else []
    # ưu tiên dự án mẫu "Loop 70 lần" (đúng việc hay làm nhất)
    samples.sort(key=lambda p: 0 if "70" in p.stem else 1)
    ov = WelcomeOverlay(host, samples)
    ov.finished.connect(on_done)
    if on_sample is not None:
        ov.sampleRequested.connect(on_sample)
    QTimer.singleShot(0, ov.open)
    return ov
