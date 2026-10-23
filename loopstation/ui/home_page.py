"""Màn hình "Bắt đầu": chọn việc muốn làm bằng các thẻ lớn → app tự chuyển đúng kiểu sản phẩm và đúng bước."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..core import ffmpeg_tools as ft
from . import branding, effects, icons, theme
from .theme import APP_NAME, AUTHOR
from .widgets import sample_label

# (khoá, biểu tượng, tông ô biểu tượng, tiêu đề, mô tả, ví dụ)
CARDS = [
    ("video_music", "video_music", "accent", "Video có nhạc",
     "Clip loop (Google Flow…) + playlist nhạc → video dài cho YouTube.",
     "Ví dụ: clip nền ×70 xen các cảnh, nhạc tự lặp đủ 1 giờ"),
    ("video_only", "film", "info", "Chỉ video",
     "Ghép / loop clip, không dùng playlist (giữ tiếng gốc hoặc thêm tiếng nền).",
     "Ví dụ: video cảnh mưa 3 giờ có tiếng mưa"),
    ("music_only", "music", "success", "Chỉ nhạc",
     "Playlist → một file nhạc dài, hoặc nhiều bản khác thứ tự.",
     "Ví dụ: 10 bài → file MP3 1 giờ, xuất 4 bản"),
    ("ambient", "waves", "info", "Tiếng nền (ASMR)",
     "Chỉ tiếng mưa, lửa, sóng… phối nhiều lớp, tự lặp liền mạch.",
     "Ví dụ: mưa 70% + lửa 50% → file 8 giờ"),
    ("batch", "folder", "warn", "Xuất hàng loạt",
     "Nhiều video cùng kiểu một lần: mỗi thư mục con = một video.",
     "Dùng dự án đang mở làm khuôn"),
    ("open", "save", "neutral", "Mở dự án đã lưu",
     "Tiếp tục một dự án .lsproj đã làm trước đó.",
     "Hoặc mở dự án mẫu bên dưới để tập dùng"),
]


MAIN_KEYS = ("video_music", "video_only", "music_only")  # ba kiểu sản phẩm: hàng chính; còn lại là công cụ, nhẹ hơn


class HomeCard(QPushButton):
    def __init__(self, ic: str, tone: str, title: str, desc: str, example: str, parent=None, compact: bool = False):
        super().__init__(parent)
        self.setObjectName("homeCard")
        self.setProperty("compact", compact)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(92 if compact else 138)
        self.setToolTip(f"{desc}\n{example}" if compact else "")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP['xl'], theme.SP['xl'], theme.SP['xl'], theme.SP['lg'])
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        badge = QLabel()
        badge.setObjectName("homeBadge")
        badge.setFixedSize(38, 38)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setProperty("tone", tone)  # chỉ ô biểu tượng mang màu; viền thẻ luôn trung tính
        icons.bind(badge, ic, 20, {"accent": "accent_text", "neutral": "text_2"}.get(tone, tone + "_text"))
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
        if compact:
            ex.hide()  # công cụ phụ: chỉ tiêu đề + một câu; ví dụ nằm trong tooltip
            lay.addStretch(1)
            return
        lay.addStretch(1)
        lay.addWidget(ex)


class HomePage(QWidget):
    chosen = Signal(str)  # khoá trong CARDS
    openSample = Signal(str)  # đường dẫn dự án mẫu
    resumeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        logo = QLabel()
        logo.setPixmap(branding.pixmap(56, self.devicePixelRatioF()))
        title = effects.HeadingLabel("Bạn muốn làm gì hôm nay?")  # chữ chuyển màu theo màu chủ đạo
        sub = QLabel("Chọn một kiểu bên dưới, app tự mở đúng bước. Đổi kiểu bất cứ lúc nào ở thanh trên cùng.")
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
        self.resume.setIcon(icons.icon("arrow_right", 14, "text_on_accent"))
        self.resume.setIconSize(QSize(14, 14))
        self.resume.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resume.clicked.connect(lambda: self.resumeRequested.emit())
        self.resume.hide()

        grid = QGridLayout()
        grid.setSpacing(theme.SP['lg'])
        tools = QGridLayout()
        tools.setSpacing(theme.SP['lg'])
        self.cards: dict[str, HomeCard] = {}
        n_main = n_tool = 0
        for key, ic, color, t, d, ex in CARDS:
            main = key in MAIN_KEYS
            card = HomeCard(ic, color, t, d, ex, compact=not main)
            card.clicked.connect(lambda _=False, kk=key: self.chosen.emit(kk))
            if main:
                grid.addWidget(card, 0, n_main)
                n_main += 1
            else:
                tools.addWidget(card, 0, n_tool)
                n_tool += 1
            self.cards[key] = card
        main_lab = QLabel("Kiểu sản phẩm")
        main_lab.setObjectName("h2")
        tool_lab = QLabel("Công cụ khác")
        tool_lab.setObjectName("h2")

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

        steps = QLabel("<b>Cách làm:</b> 1. Video: thêm clip, chỉnh số lần loop · 2. Nhạc: thêm playlist · "
                       "3. Xuất: chọn thư mục lưu, bấm Xuất. Bấm <b>F1</b> để xem hướng dẫn.")
        steps.setObjectName("info")
        steps.setWordWrap(True)

        # nội dung rộng tối đa 1080 px, căn giữa: không loãng trên màn hình rộng
        col = QWidget()
        col.setMaximumWidth(1080)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP['lg'])
        lay.addLayout(head)
        lay.addWidget(self.resume, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addSpacing(theme.SP['sm'])
        lay.addWidget(main_lab)
        lay.addLayout(grid)
        lay.addSpacing(theme.SP['sm'])
        lay.addWidget(tool_lab)
        lay.addLayout(tools)
        if has:
            lay.addSpacing(theme.SP['sm'])
            lay.addLayout(self.samples_row)
        lay.addWidget(steps)
        lay.addStretch(1)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(theme.SP['xxl'], theme.SP['xl'] + theme.SP['xs'], theme.SP['xxl'], theme.SP['xl'])
        outer.addStretch(1)
        outer.addWidget(col, 100)
        outer.addStretch(1)

    def set_resume(self, text: str) -> None:
        """Nút "Tiếp tục dự án đang làm" (ẩn khi dự án trống)."""
        self.resume.setText(text)
        self.resume.setVisible(bool(text))

    def adapt(self, width: int, height: int = 0) -> None:
        pass
