"""Phần trực quan của trang Hướng dẫn: trang Tổng quan (thẻ lớn có ảnh, lưới chủ đề theo nhóm, phím tắt) và thanh
tiêu đề / thanh chuyển chủ đề của khung đọc. Dựng bằng widget thật (không phải HTML) nên bấm được cả thẻ,
đổi bộ màu / cỡ chữ là đổi theo.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from . import icons, theme
from .widgets import FlowLayout

# nhóm chủ đề → (biểu tượng, tông màu ô biểu tượng — dùng chung QSS QLabel#homeBadge[tone])
GROUP_STYLE = {
    "Bắt đầu": ("home", "accent"),
    "Làm video": ("film", "info"),
    "Âm thanh": ("music", "success"),
    "Xuất file": ("export", "warn"),
    "Khác": ("settings", "neutral"),
}
# 3 bước làm video đầu tiên: (chủ đề, tiêu đề, mô tả, ảnh minh hoạ)
FIRST_STEPS = (
    ("video", "Thêm clip & số lần loop",
     "Kéo thả clip vào bảng, gõ số lần phát: 70 = 70 lần, 10p = đủ 10 phút.", "video"),
    ("nhac", "Thêm nhạc & tiếng nền",
     "Playlist tự lặp cho đủ độ dài video, bài cuối nhỏ dần. Thêm mưa, sóng… nếu muốn.", "music"),
    ("xuat", "Xem trước & xuất file",
     "Bấm Phát để xem thử, chọn thư mục lưu rồi Bắt đầu xuất. Xuất nhanh bằng card đồ hoạ.", "export"),
)
# "Có gì mới" của bản đang chạy — hiện ở đầu trang Tổng quan (sửa cùng lúc với APP_VERSION khi ra bản mới)
WHATS_NEW = (
    ("zap", "Xuất nhanh hơn ~3 lần",
     "Ghép nhiều clip: app chuẩn hoá 3 clip cùng lúc trên card NVIDIA / AMD, mã hoá nhanh cho mức Cao (độ nét như cũ), bước "
     "cuối không ghi lại cả file. Đo thật: 45 clip 2K, video 22 phút — 229 giây còn 74 giây."),
    ("shuffle", "Trộn ngẫu nhiên: thấy trước thứ tự",
     "Chọn Ngẫu nhiên là ngay trên bảng clip hiện Thứ tự sẽ xuất (1. → 2. → …). Trộn lại để ra thứ tự khác, Dùng thứ tự "
     "này để chép vào bảng rồi sửa tay."),
    ("folder", "Thả file là xong — ít bước hơn",
     "Thả file / cả thư mục vào trang Video: app tự nhận tập, tự áp mẫu dùng lần trước, dải Sẵn sàng có nút Thêm vào hàng "
     "đợi. Thả cả mùa: một câu hỏi là đưa hết các tập vào hàng đợi."),
    ("sliders", "Tiếng gốc rõ, chỉnh ở một chỗ",
     "Tiếng gốc tự cân về cùng mức với nhạc. Bảng trộn âm có 3 nút Giữ / Chỉ / Tắt tiếng gốc và chọn nhanh Nhạc là chính · "
     "Cân bằng · Tiếng gốc là chính."),
    ("queue", "Hàng đợi dễ dùng, khó nhầm",
     "Thêm xong app hỏi Làm video tiếp theo hay Chạy hàng đợi; tên file tự gợi ý Tập 33; mỗi mục ghi rõ nội dung, bấm vào "
     "xem chi tiết, Sửa mục này rồi Cập nhật đúng mục đó; lỡ thêm trùng thì app hỏi lại."),
    ("plus", "LOOP AB lên đầu tình huống — dòng “Chỉ khi có file”",
     "Mẫu Loop A ×57 kẹp Loop B có dòng LOOP AB ở đầu: tình huống có file 33_2_LOOP AB thì mở đầu bằng AB, tình huống "
     "khác giữ nguyên. Tự tạo mẫu: tick Chỉ khi có file. File có vai mẫu chưa có (34_5_LOOP C) được báo tên."),
)
SHORTCUTS = (("Space", "Phát / dừng"), ("F1", "Hướng dẫn"), ("Ctrl+S", "Lưu dự án"), ("Ctrl+Z", "Hoàn tác"),
             ("Ctrl+D", "Nhân bản dòng"), ("Ctrl+F", "Tìm"))


def _tone_icon(tone: str) -> str:
    return {"accent": "accent_text", "neutral": "text_2"}.get(tone, tone + "_text")


def badge(icon_name: str, tone: str, size: int = 34, icon_size: int = 18) -> QLabel:
    lab = QLabel()
    lab.setObjectName("homeBadge")
    lab.setProperty("tone", tone)
    lab.setFixedSize(size, size)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icons.bind(lab, icon_name, icon_size, _tone_icon(tone))
    lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return lab


def _label(text: str, name: str = "", wrap: bool = True, rich: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    if rich:
        lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return lab


class Thumb(QWidget):
    """Ảnh chụp app thu nhỏ, giữ đúng tỉ lệ theo bề ngang thẻ, bo góc."""

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.pix = QPixmap(str(path))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def _ratio(self) -> float:
        return 0.56 if self.pix.isNull() else min(0.62, self.pix.height() / max(1, self.pix.width()))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return int(w * self._ratio())

    def sizeHint(self):  # noqa: N802
        return QSize(300, int(300 * self._ratio()))

    def minimumSizeHint(self):  # noqa: N802
        return QSize(160, int(160 * self._ratio()))

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(r, 8, 8)
        p.setClipPath(clip)
        p.fillRect(self.rect(), theme.qcolor("field") if hasattr(theme, "qcolor") else Qt.GlobalColor.black)
        if not self.pix.isNull():
            # lấy phần trên của ảnh (thanh trên cùng + nội dung chính) cho vừa khung, không méo hình
            src_h = min(self.pix.height(), self.pix.width() * self._ratio())
            p.drawPixmap(self.rect(), self.pix, QRectF(0, 0, self.pix.width(), src_h).toRect())
        p.setClipping(False)
        p.setPen(theme.qcolor("line") if hasattr(theme, "qcolor") else Qt.GlobalColor.gray)
        p.drawRoundedRect(r, 8, 8)


class StepCard(QPushButton):
    """Thẻ một bước (số thứ tự lớn + ảnh minh hoạ + mô tả), bấm để mở chủ đề."""

    def __init__(self, num: int, title: str, desc: str, image: Path, parent=None):
        super().__init__(parent)
        self.setObjectName("helpCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP["lg"], theme.SP["lg"], theme.SP["lg"], theme.SP["lg"])
        lay.setSpacing(theme.SP["sm"])
        top = QHBoxLayout()
        top.setSpacing(theme.SP["sm"])
        n = _label(str(num), "helpNum", wrap=False)
        n.setFixedSize(28, 28)
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(n)
        top.addWidget(_label(title, "homeTitle", wrap=True), 1)
        lay.addLayout(top)
        lay.addWidget(Thumb(image))
        lay.addWidget(_label(desc, "homeDesc"))
        lay.addStretch(1)
        lay.addWidget(_label("Xem cách làm →", "helpMore", wrap=False))


class TopicCard(QPushButton):
    """Thẻ chủ đề nhỏ: ô biểu tượng màu theo nhóm + tên + một dòng "dùng khi nào"."""

    def __init__(self, icon_name: str, tone: str, title: str, when: str, parent=None):
        super().__init__(parent)
        self.setObjectName("helpCard")
        self.setProperty("compact", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(when)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.SP["lg"], theme.SP["md"], theme.SP["lg"], theme.SP["md"])
        lay.setSpacing(theme.SP["md"])
        lay.addWidget(badge(icon_name, tone), 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(_label(title, "helpCardTitle"))
        short = when if len(when) <= 92 else when[:89].rsplit(" ", 1)[0] + "…"
        texts.addWidget(_label(short, "homeExample"))
        lay.addLayout(texts, 1)
        self.setMinimumHeight(74)


class _Grid(QWidget):
    """Lưới thẻ tự đổi số cột theo bề ngang (1 / 2 / 3 / 4 cột)."""

    def __init__(self, min_col: int = 290, max_cols: int = 4, parent=None):
        super().__init__(parent)
        self.min_col, self.max_cols = min_col, max_cols
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(theme.SP["md"])
        self.grid.setVerticalSpacing(theme.SP["md"])
        self.cards: list[QWidget] = []
        self._cols = 0

    def add(self, card: QWidget) -> None:
        self.cards.append(card)
        self._relayout(force=True)

    def _relayout(self, force: bool = False) -> None:
        cols = max(1, min(self.max_cols, len(self.cards) or 1, self.width() // self.min_col or 1))
        if cols == self._cols and not force:
            return
        self._cols = cols
        for c in self.cards:
            self.grid.removeWidget(c)
        for k, c in enumerate(self.cards):
            self.grid.addWidget(c, k // cols, k % cols)
        for k in range(self.max_cols):
            self.grid.setColumnStretch(k, 1 if k < cols else 0)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._relayout()


def _section(title: str, icon_name: str = "", tone: str = "accent", note: str = "") -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, theme.SP["md"], 0, 0)
    lay.setSpacing(theme.SP["sm"])
    if icon_name:
        lay.addWidget(badge(icon_name, tone, 26, 14))
    lay.addWidget(_label(title, "helpSection", wrap=False))
    if note:
        lay.addWidget(_label(note, "muted", wrap=False))
    lay.addStretch(1)
    return row


class HubPage(QScrollArea):
    """Trang Tổng quan: mở đầu trang Hướng dẫn."""
    topicRequested = Signal(str)
    linkRequested = Signal(str)  # "app:…" → giống nút trong khung đọc

    def __init__(self, topics, meta: dict, groups: list[str], help_dir: Path, version: str, samples=(),
                 tools=(), parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("helpHubBody")
        v = QVBoxLayout(body)
        v.setContentsMargins(theme.SP["xs"], 0, theme.SP["md"], theme.SP["xl"])
        v.setSpacing(theme.SP["lg"])

        # ---- đầu trang ----
        hero = QFrame()
        hero.setObjectName("helpHero")
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(theme.SP["xxl"], theme.SP["xl"], theme.SP["xxl"], theme.SP["xl"])
        hv.setSpacing(theme.SP["sm"])
        hv.addWidget(_label(f"HƯỚNG DẪN SỬ DỤNG · BẢN {version}", "helpEyebrow", wrap=False))
        hv.addWidget(_label("Làm video loop dài cho YouTube — xem cách làm từng bước", "homeHero"))
        hv.addWidget(_label("Mỗi chủ đề một trang ngắn: ảnh chụp app có đánh số ①②③, ví dụ gõ sẵn, mẹo, và nút "
                            "đưa thẳng tới đúng chỗ trong app. Gõ vào ô tìm bên trái — không dấu cũng được.", "homeDesc"))
        btns = QHBoxLayout()
        btns.setSpacing(theme.SP["sm"])
        b1 = QPushButton("Bắt đầu trong 3 bước")
        theme.tag(b1, variant="primary")
        b1.setIcon(icons.icon("arrow_right", 14, "white"))
        b1.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        b1.clicked.connect(lambda: self.topicRequested.emit("batdau"))
        btns.addWidget(b1)
        if samples:
            b2 = QPushButton("Mở dự án mẫu để tập")
            theme.tag(b2, variant="tonal")
            b2.setIcon(icons.icon("folder", 14, "accent_text"))
            b2.clicked.connect(lambda: self.linkRequested.emit("app:sample"))
            btns.addWidget(b2)
        b3 = QPushButton("Phím tắt")
        theme.tag(b3, variant="ghost")
        b3.setIcon(icons.icon("zap", 14))
        b3.clicked.connect(lambda: self.topicRequested.emit("phim"))
        btns.addWidget(b3)
        btns.addStretch(1)
        hv.addLayout(btns)
        v.addWidget(hero)

        # ---- có gì mới ở bản này ----
        news = QFrame()
        news.setObjectName("helpNews")
        nv = QVBoxLayout(news)
        nv.setContentsMargins(theme.SP["xl"], theme.SP["lg"], theme.SP["xl"], theme.SP["lg"])
        nv.setSpacing(theme.SP["sm"])
        nh = QHBoxLayout()
        nh.setSpacing(theme.SP["sm"])
        nh.addWidget(_label("MỚI", "helpNewTag", wrap=False))
        nh.addWidget(_label(f"Có gì mới ở bản {version}", "helpSection", wrap=False))
        nh.addStretch(1)
        nv.addLayout(nh)
        ng = _Grid(min_col=330, max_cols=2)
        for ic, title, desc in WHATS_NEW:
            item = QWidget()
            il = QHBoxLayout(item)
            il.setContentsMargins(0, theme.SP["xs"], 0, theme.SP["xs"])
            il.setSpacing(theme.SP["md"])
            il.addWidget(badge(ic, "accent", 30, 16), 0, Qt.AlignmentFlag.AlignTop)
            tv = QVBoxLayout()
            tv.setSpacing(1)
            tv.addWidget(_label(title, "helpCardTitle"))
            tv.addWidget(_label(desc, "homeExample"))
            il.addLayout(tv, 1)
            ng.add(item)
        nv.addWidget(ng)
        v.addWidget(news)

        # ---- 3 bước ----
        v.addWidget(_section("Video đầu tiên trong 3 bước", "play", "accent", "· bấm một thẻ để xem chi tiết"))
        steps = _Grid(min_col=240, max_cols=3)
        for k, (tid, title, desc, img) in enumerate(FIRST_STEPS, 1):
            card = StepCard(k, title, desc, help_dir / "help" / f"{img}.png")
            card.clicked.connect(lambda _=False, t=tid: self.topicRequested.emit(t))
            steps.add(card)
        v.addWidget(steps)

        # ---- mọi chủ đề, theo nhóm ----
        self.cards: dict[str, TopicCard] = {}
        for g in groups:
            ic, tone = GROUP_STYLE.get(g, ("help", "neutral"))
            items = [t for t in topics if t[1] == g]
            if not items:
                continue
            v.addWidget(_section(g, ic, tone, f"· {len(items)} chủ đề"))
            grid = _Grid(min_col=290, max_cols=3)
            for tid, _g, t_icon, title, _html in items:
                card = TopicCard(t_icon, tone, title, meta.get(tid, {}).get("when", ""))
                card.clicked.connect(lambda _=False, t=tid: self.topicRequested.emit(t))
                grid.add(card)
                self.cards[tid] = card
            v.addWidget(grid)

        # ---- phím tắt hay dùng ----
        v.addWidget(_section("Phím tắt hay dùng", "zap", "warn"))
        kb = QWidget()
        kf = FlowLayout(kb, spacing=theme.SP["sm"])
        for key, what in SHORTCUTS:
            chip = QFrame()
            chip.setObjectName("helpKeyChip")
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(theme.SP["sm"], theme.SP["xs"], theme.SP["md"], theme.SP["xs"])
            cl.setSpacing(theme.SP["sm"])
            cl.addWidget(_label(key, "helpKbd", wrap=False))
            cl.addWidget(_label(what, "homeDesc", wrap=False))
            kf.addWidget(chip)
        v.addWidget(kb)

        # ---- dự án mẫu + công cụ ----
        if tools:
            v.addWidget(_section("Dự án mẫu & công cụ", "folder", "neutral"))
            tb = QWidget()
            tf = FlowLayout(tb, spacing=theme.SP["sm"])
            for btn in tools:
                tf.addWidget(btn)
            v.addWidget(tb)
        v.addStretch(1)
        self.setWidget(body)


class TopicHeader(QFrame):
    """Đầu khung đọc: đường dẫn (Tổng quan › nhóm), ô biểu tượng + tên chủ đề, "dùng khi nào", nút đi tới chỗ làm."""
    homeRequested = Signal()
    linkRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("helpHead")
        v = QVBoxLayout(self)
        v.setContentsMargins(theme.SP["xl"], theme.SP["md"], theme.SP["xl"], theme.SP["lg"])
        v.setSpacing(theme.SP["sm"])
        crumb = QHBoxLayout()
        crumb.setSpacing(theme.SP["xs"])
        self.home_btn = QPushButton("Tổng quan")
        theme.tag(self.home_btn, variant="ghost")
        self.home_btn.setIcon(icons.icon("arrow_left", 13))
        self.home_btn.setToolTip("Về trang Tổng quan của Hướng dẫn")
        self.home_btn.clicked.connect(self.homeRequested.emit)
        self.group_lab = _label("", "muted", wrap=False)
        crumb.addWidget(self.home_btn)
        crumb.addWidget(_label("›", "muted", wrap=False))
        crumb.addWidget(self.group_lab)
        crumb.addStretch(1)
        v.addLayout(crumb)
        title_row = QHBoxLayout()
        title_row.setSpacing(theme.SP["md"])
        self.badge_box = QHBoxLayout()
        self.badge_box.setContentsMargins(0, 0, 0, 0)
        title_row.addLayout(self.badge_box)
        self.title = _label("", "helpTitle")
        title_row.addWidget(self.title, 1)
        v.addLayout(title_row)
        self.when = _label("", "homeDesc")
        v.addWidget(self.when)
        self.btn_row = QHBoxLayout()
        self.btn_row.setSpacing(theme.SP["sm"])
        v.addLayout(self.btn_row)
        self._badge: QLabel | None = None
        self._btns: list[QPushButton] = []

    def set_topic(self, group: str, icon_name: str, title: str, when: str, actions) -> None:
        _ic, tone = GROUP_STYLE.get(group, ("help", "neutral"))
        if self._badge is not None:
            self._badge.setParent(None)
            self._badge.deleteLater()
        self._badge = badge(icon_name, tone, 40, 22)
        self.badge_box.addWidget(self._badge)
        self.group_lab.setText(group)
        self.title.setText(title)
        self.when.setText(when)
        self.when.setVisible(bool(when))
        for b in self._btns:
            b.setParent(None)
            b.deleteLater()
        self._btns = []
        while self.btn_row.count():
            self.btn_row.takeAt(0)
        for k, (label, href) in enumerate(actions or ()):
            b = QPushButton(label.replace("&", "&&"))
            theme.tag(b, variant="primary" if k == 0 else "tonal")
            if k == 0:
                b.setIcon(icons.icon("arrow_right", 13, "white"))
                b.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            b.clicked.connect(lambda _=False, h=href: self.linkRequested.emit(h))
            self.btn_row.addWidget(b)
            self._btns.append(b)
        self.btn_row.addStretch(1)


class TopicNav(QWidget):
    """Cuối khung đọc: ← chủ đề trước · chủ đề sau →."""
    topicRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, theme.SP["xs"], 0, 0)
        lay.setSpacing(theme.SP["sm"])
        self.prev = QPushButton()
        theme.tag(self.prev, variant="ghost")
        self.prev.setIcon(icons.icon("arrow_left", 13))
        self.next = QPushButton()
        theme.tag(self.next, variant="tonal")
        self.next.setIcon(icons.icon("arrow_right", 13, "accent_text"))
        self.next.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        lay.addWidget(self.prev)
        lay.addStretch(1)
        lay.addWidget(self.next)
        self._prev_tid = self._next_tid = ""
        self.prev.clicked.connect(lambda: self._prev_tid and self.topicRequested.emit(self._prev_tid))
        self.next.clicked.connect(lambda: self._next_tid and self.topicRequested.emit(self._next_tid))

    def set_neighbours(self, prev: tuple[str, str] | None, nxt: tuple[str, str] | None) -> None:
        self._prev_tid = prev[0] if prev else ""
        self._next_tid = nxt[0] if nxt else ""
        self.prev.setVisible(bool(prev))
        self.next.setVisible(bool(nxt))
        # "&" trong tên chủ đề: nút Qt coi là phím tắt (nuốt mất) → ghi "&&" để hiện đúng dấu &
        if prev:
            self.prev.setText(f"Trước: {prev[1]}".replace("&", "&&"))
        if nxt:
            self.next.setText(f"Tiếp: {nxt[1]}".replace("&", "&&"))
