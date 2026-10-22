"""Màn hình "Bắt đầu": chọn việc muốn làm bằng các thẻ lớn → app tự chuyển đúng kiểu sản phẩm và đúng bước."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..core import ffmpeg_tools as ft
from . import branding, effects, icons, theme
from .theme import APP_NAME, AUTHOR
from .widgets import sample_label

# (khoá, biểu tượng, màu biểu tượng, tiêu đề, mô tả, ví dụ)
CARDS = [
    ("video_music", "video_music", "#a78bfa", "Video có nhạc",
     "Clip loop (Google Flow…) + playlist nhạc → video dài cho YouTube.",
     "Ví dụ: clip nền ×70 xen các cảnh, nhạc tự lặp đủ 1 giờ"),
    ("video_only", "film", "#60a5fa", "Chỉ video",
     "Ghép / loop clip, không dùng playlist (giữ tiếng gốc hoặc thêm tiếng nền).",
     "Ví dụ: video cảnh mưa 3 giờ có tiếng mưa"),
    ("music_only", "music", "#34d399", "Chỉ nhạc",
     "Playlist → một file nhạc dài, hoặc nhiều bản khác thứ tự.",
     "Ví dụ: 10 bài → file MP3 1 giờ, xuất 4 bản"),
    ("ambient", "waves", "#22d3ee", "Tiếng nền (ASMR)",
     "Chỉ tiếng mưa, lửa, sóng… phối nhiều lớp, tự lặp liền mạch.",
     "Ví dụ: mưa 70% + lửa 50% → file 8 giờ"),
    ("batch", "folder", "#fbbf24", "Xuất hàng loạt",
     "Nhiều video cùng kiểu một lần: mỗi thư mục con = một video.",
     "Dùng dự án đang mở làm khuôn"),
    ("open", "save", "#f472b6", "Mở dự án đã lưu",
     "Tiếp tục một dự án .lsproj đã làm trước đó.",
     "Hoặc mở dự án mẫu bên dưới để tập dùng"),
]


class HomeCard(QPushButton):
    def __init__(self, ic: str, color: str, title: str, desc: str, example: str, parent=None):
        super().__init__(parent)
        self.setObjectName("homeCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(138)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP['xl'], theme.SP['xl'], theme.SP['xl'], theme.SP['lg'])
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        badge = QLabel()
        badge.setObjectName("homeBadge")
        badge.setFixedSize(38, 38)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(icons.pixmap(ic, 20, color))
        t = QLabel(title)
        t.setObjectName("homeTitle")
        top.addWidget(badge)
        top.addWidget(t, 1)
        d = QLabel(desc)
        d.setObjectName("homeDesc")
        d.setWordWrap(True)
        ex = QLabel(example)
        ex.setObjectName("homeExample")
        ex.setWordWrap(True)
        for lab in (badge, t, d, ex):
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addLayout(top)
        lay.addWidget(d)
        lay.addStretch(1)
        lay.addWidget(ex)

    def tint(self, color: str) -> None:
        """Mỗi thẻ ánh một màu riêng (màu biểu tượng) ở góc trên trái, rê chuột thì đậm hơn."""
        c = theme.rgba
        self.setStyleSheet(
            f"QPushButton#homeCard {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c(color, 0.20)}, "
            f"stop:0.55 {c(theme.C['surface'], 0.92)}, stop:1 {c(theme.C['surface'], 0.92)}); "
            f"border: 1px solid {c(color, 0.30)}; border-radius: 14px; text-align: left; padding: 0; }}"
            f"QPushButton#homeCard:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c(color, 0.32)}, "
            f"stop:0.6 {c(theme.C['surface2'], 0.95)}, stop:1 {c(theme.C['surface2'], 0.95)}); border-color: {color}; }}"
            f"QPushButton#homeCard:pressed {{ background: {c(color, 0.28)}; }}"
            f"QLabel#homeBadge {{ background: {c(color, 0.18)}; border-radius: 10px; }}")


class HomePage(QWidget):
    chosen = Signal(str)  # khoá trong CARDS
    openSample = Signal(str)  # đường dẫn dự án mẫu
    resumeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        logo = QLabel()
        logo.setPixmap(branding.pixmap(56, self.devicePixelRatioF()))
        title = effects.GradientLabel("Bạn muốn làm gì hôm nay?")  # chữ chuyển màu theo màu chủ đạo
        sub = QLabel(f"{APP_NAME} · {AUTHOR} — chọn một việc bên dưới, app tự mở đúng bước. "
                     "Có thể đổi kiểu sản phẩm bất cứ lúc nào ở thanh trên cùng.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        head = QHBoxLayout()
        head.setSpacing(theme.SP['lg'])
        head.addWidget(logo)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(title)
        texts.addWidget(sub)
        head.addLayout(texts, 1)

        self.resume = QPushButton("")
        self.resume.setObjectName("nextStepBtn")
        self.resume.setIcon(icons.icon("arrow_right", 14, "#ffffff"))
        self.resume.setIconSize(QSize(14, 14))
        self.resume.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resume.clicked.connect(lambda: self.resumeRequested.emit())
        self.resume.hide()

        grid = QGridLayout()
        grid.setSpacing(theme.SP['lg'])
        self.cards: dict[str, HomeCard] = {}
        for k, (key, ic, color, t, d, ex) in enumerate(CARDS):
            card = HomeCard(ic, color, t, d, ex)
            card.clicked.connect(lambda _=False, kk=key: self.chosen.emit(kk))
            effects.Glow(card, color, blur=34, alpha=120)  # rê chuột: thẻ sáng lên theo màu biểu tượng
            card.tint(color)
            grid.addWidget(card, k // 3, k % 3)
            self.cards[key] = card

        self.samples_row = QHBoxLayout()
        self.samples_row.setSpacing(8)
        lab = QLabel("Dự án mẫu để tập dùng:")
        lab.setObjectName("muted")
        self.samples_row.addWidget(lab)
        sample_dir = Path(ft.app_dir()) / "Mau-Test"
        has = False
        for proj in sorted(sample_dir.glob("*.lsproj")) if sample_dir.is_dir() else []:
            b = QPushButton(sample_label(proj.stem))
            b.setObjectName("pill")
            b.setToolTip(str(proj))
            b.clicked.connect(lambda _=False, p=str(proj): self.openSample.emit(p))
            self.samples_row.addWidget(b)
            has = True
        self.samples_row.addStretch(1)

        steps = QLabel("<b>Cách làm chung — 3 bước:</b> &nbsp;① <b>Video</b>: thêm clip, chỉnh số lần loop "
                       "&nbsp;→&nbsp; ② <b>Nhạc</b>: thêm playlist (tự lặp theo độ dài video) "
                       "&nbsp;→&nbsp; ③ <b>Xuất</b>: chọn thư mục lưu, bấm Xuất. "
                       "Thanh hướng dẫn phía trên mỗi trang luôn nói bước tiếp theo. Bấm <b>F1</b> để xem hướng dẫn.")
        steps.setObjectName("info")
        steps.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP['xxl'], theme.SP['xl'] + theme.SP['xs'], theme.SP['xxl'], theme.SP['xl'])
        lay.setSpacing(16)
        lay.addLayout(head)
        lay.addWidget(self.resume, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addLayout(grid)
        if has:
            lay.addLayout(self.samples_row)
        lay.addWidget(steps)
        lay.addStretch(1)

    def set_resume(self, text: str) -> None:
        """Nút "Tiếp tục dự án đang làm" (ẩn khi dự án trống)."""
        self.resume.setText(text)
        self.resume.setVisible(bool(text))

    def adapt(self, width: int) -> None:
        pass
