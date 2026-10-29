"""Hộp thoại hàng đợi: "Đã thêm vào hàng đợi" (đã thêm gì, lưu ở đâu, bước tiếp theo) — to, rõ, khó bấm nhầm."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import theme
from . import widgets as w
from .help_hub import badge


def _fit(dlg: QDialog, width: int) -> None:
    """Rộng cố định, cao vừa khít nội dung (chữ xuống dòng) — không khoảng trống thừa, không bị co hẹp."""
    dlg.setFixedWidth(width)
    lay = dlg.layout()
    h = lay.totalHeightForWidth(width) if lay.hasHeightForWidth() else lay.sizeHint().height()
    dlg.setFixedHeight(max(h, lay.minimumSize().height()))


def _choice(icon_name: str, title: str, sub: str, primary: bool = False) -> QPushButton:
    """Nút lớn: biểu tượng + tên việc + một dòng giải thích (như thẻ ở trang Hướng dẫn)."""
    b = QPushButton()
    b.setObjectName("helpCard")
    b.setProperty("primary", primary)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setMinimumHeight(64)
    lay = QHBoxLayout(b)
    lay.setContentsMargins(theme.SP["lg"], theme.SP["md"], theme.SP["lg"], theme.SP["md"])
    lay.setSpacing(theme.SP["md"])
    lay.addWidget(badge(icon_name, "accent" if primary else "info", 32, 16))
    tv = QVBoxLayout()
    tv.setSpacing(1)
    t = QLabel(title)
    t.setObjectName("helpCardTitle")
    s = QLabel(sub)
    s.setObjectName("muted")
    s.setWordWrap(True)
    for lab in (t, s):
        lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        tv.addWidget(lab)
    lay.addLayout(tv, 1)
    return b


class QueueAddedDialog(QDialog):
    """Sau khi bấm Thêm vào hàng đợi. `choice`: "next" (làm video tiếp theo), "run" (chạy hàng đợi), "stay"."""

    def __init__(self, out: str, summary: str, pending: int, can_run: bool, parent=None,
                 lines: list[str] | None = None, name: str = ""):
        """`lines`: nhiều video một lúc (thả cả mùa) — mỗi dòng một video thay cho chip tóm tắt."""
        super().__init__(parent)
        self.setWindowTitle("Đã thêm vào hàng đợi")
        self.choice = "stay"

        head = QHBoxLayout()
        head.setSpacing(theme.SP["md"])
        head.addWidget(badge("check", "success", 38, 20))
        title = QLabel("Đã thêm vào hàng đợi")
        title.setObjectName("updateTitle")
        head.addWidget(title)
        head.addStretch(1)
        count = QLabel(f"{pending} video đang chờ")
        count.setObjectName("chipAccent")
        head.addWidget(count)

        card = QFrame()
        card.setObjectName("presetCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(theme.SP["lg"], theme.SP["md"], theme.SP["lg"], theme.SP["md"])
        cv.setSpacing(theme.SP["sm"])
        title_lab = QLabel(name or Path(out).stem)
        title_lab.setObjectName("presetName")
        cv.addWidget(title_lab)
        if lines:
            for ln in lines:
                lab = QLabel(ln)
                lab.setObjectName("queueDetail")
                cv.addWidget(lab)
        else:
            chips = QHBoxLayout()
            chips.setSpacing(6)
            for part in [p for p in summary.split(" · ") if p]:
                c = QLabel(part)
                c.setObjectName("chip")
                chips.addWidget(c)
            chips.addStretch(1)
            cv.addLayout(chips)
        where = w.muted(f"Lưu tại: <b>{out}</b>")
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cv.addWidget(where)

        ask = QLabel("Tiếp theo làm gì?")
        ask.setObjectName("helpCardTitle")
        nxt = _choice("plus", "Làm video tiếp theo", "Bảng clip và tên file để trống — giữ nguyên mẫu, intro / outro, "
                      "nhạc, cài đặt xuất.", primary=True)
        nxt.clicked.connect(lambda: self._done("next"))
        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SP["md"])
        lay.addLayout(head)
        lay.addWidget(card)
        lay.addWidget(ask)
        lay.addWidget(nxt)
        if can_run:
            run = _choice("play", f"Chạy hàng đợi ngay ({pending})", "Xuất lần lượt các video đang chờ, từ trên xuống.")
            run.clicked.connect(lambda: self._done("run"))
            lay.addWidget(run)
        else:
            lay.addWidget(w.muted("Đang xuất — mục này sẽ được xuất khi tới lượt."))
        stay = QPushButton("Ở lại trang Xuất")
        stay.setObjectName("ghost")
        stay.clicked.connect(lambda: self._done("stay"))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(stay)
        lay.addLayout(row)
        nxt.setFocus()
        _fit(self, 580)

    def _done(self, choice: str) -> None:
        self.choice = choice
        self.accept()


class SeasonDialog(QDialog):
    """Thả file của nhiều tập (33_…, 34_…, 35_…): đưa cả mùa vào hàng đợi bằng 1 lần bấm, hoặc chỉ làm 1 tập.
    `choice`: "all" | "one" (tập ở `episode`) | "keep" (để nguyên bảng)."""

    def __init__(self, episodes: list[tuple[int, str]], preset: str, folder: str, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox
        self.setWindowTitle("Nhiều tập một lúc")
        self.choice = "keep"
        self.episode = episodes[0][0] if episodes else 0

        head = QHBoxLayout()
        head.setSpacing(theme.SP["md"])
        head.addWidget(badge("queue", "accent", 38, 20))
        title = QLabel(f"Có {len(episodes)} tập trong các file vừa thả")
        title.setObjectName("updateTitle")
        head.addWidget(title, 1)

        card = QFrame()
        card.setObjectName("presetCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(theme.SP["lg"], theme.SP["md"], theme.SP["lg"], theme.SP["md"])
        cv.setSpacing(4)
        cv.addWidget(w.muted(f"Mẫu: <b>{preset}</b> · mỗi tập một video, tên file theo tập."))
        for ep, desc in episodes:
            lab = QLabel(f"<b>Tập {ep}</b> — {desc}")
            lab.setObjectName("queueDetail")
            cv.addWidget(lab)
        where = w.muted(f"Lưu vào: <b>{folder}</b>" if folder else
                        "<span>Chưa chọn thư mục lưu — app sẽ hỏi trước khi thêm.</span>")
        where.setWordWrap(True)
        cv.addWidget(where)

        allb = _choice("queue", f"Đưa cả {len(episodes)} tập vào hàng đợi",
                       "Mỗi tập thành 1 video (Tập 33.mp4, Tập 34.mp4…), giữ intro / outro, nhạc, cài đặt xuất.",
                       primary=True)
        allb.clicked.connect(lambda: self._done("all"))
        self.pick = QComboBox()
        for ep, _d in episodes:
            self.pick.addItem(f"Tập {ep}", ep)
        oneb = _choice("film", "Chỉ làm một tập ở bảng này", "Xếp tập đang chọn vào bảng để xem / sửa trước khi thêm.")
        oneb.clicked.connect(lambda: self._done("one"))
        orow = QHBoxLayout()
        orow.addWidget(oneb, 1)
        orow.addWidget(self.pick, 0, Qt.AlignmentFlag.AlignVCenter)
        keep = QPushButton("Để nguyên bảng")
        keep.setObjectName("ghost")
        keep.clicked.connect(lambda: self._done("keep"))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(keep)
        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SP["md"])
        lay.addLayout(head)
        lay.addWidget(card)
        lay.addWidget(allb)
        lay.addLayout(orow)
        lay.addLayout(row)
        allb.setFocus()
        _fit(self, 600)

    def _done(self, choice: str) -> None:
        self.choice = choice
        self.episode = self.pick.currentData()
        self.accept()
