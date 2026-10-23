"""Widget dùng chung: bảng danh sách file (kéo thả, phím tắt), delegate, đọc file nền."""
from __future__ import annotations

import os
import re
import threading
import unicodedata
from pathlib import Path

import hashlib
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QFontMetrics, QColor, QFont, QImage, QKeyEvent, QKeySequence, QPainter, QPainterPath, QPen,
                           QRegularExpressionValidator, QShortcut)
from PySide6.QtWidgets import (
    QApplication, QAbstractScrollArea, QAbstractSpinBox, QComboBox, QFrame, QGraphicsOpacityEffect,
    QLayout, QMenu, QSizePolicy, QStackedWidget,
    QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QLineEdit, QPushButton,
    QDoubleSpinBox, QLabel, QSpinBox, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QWidget,
)

from ..core import ffmpeg_tools as ft
from ..core import probe
from . import icons, theme

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".mts",
              ".m2ts", ".wmv", ".flv", ".3gp"}
IMAGE_EXTS = probe.IMAGE_EXTS
VISUAL_EXTS = VIDEO_EXTS | IMAGE_EXTS
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif"}

ROLE_DATA = Qt.ItemDataRole.UserRole
ROLE_INFO = Qt.ItemDataRole.UserRole + 1


def natural_key(path: str):
    """Sắp xếp tự nhiên: clip2 đứng trước clip10."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", Path(path).name.lower())]


def scan_folder(folder: str, exts: set[str], recursive: bool) -> list[str]:
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.startswith(".") and Path(f).suffix.lower() in exts:
                out.append(os.path.join(root, f))
        if not recursive:
            break
    return sorted(out, key=natural_key)


def fmt_dur(sec: float) -> str:
    s = int(round(sec))
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def open_with_default_app(path: str) -> None:
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except OSError:
        pass


def reveal_in_explorer(path: str) -> None:
    if os.path.exists(path):
        import subprocess
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


class Prober(QObject):
    """Đọc thông tin nhiều file ở luồng nền, báo tiến trình về giao diện."""
    progress = Signal(int, int)
    finished = Signal(list)  # list[MediaInfo]

    def start(self, paths: list[str]) -> None:
        def work():
            results = []
            for i, info in enumerate(_iter_probe(paths), 1):
                results.append(info)
                self.progress.emit(i, len(paths))
            self.finished.emit(results)
        threading.Thread(target=work, daemon=True).start()


class ProbeWarmer(QObject):
    """Đọc trước (ffprobe) các file chưa có trong bộ nhớ đệm, ở luồng nền của pool dùng chung. Kết quả vào
    bộ nhớ đệm của probe; `done(keys)` báo về giao diện để tính lại (bộ nhớ đệm khoá theo đường dẫn + cỡ + giờ sửa,
    nên kết quả của file đã bị sửa / bỏ khỏi dự án không bao giờ dùng nhầm)."""
    done = Signal(object)  # tập key đã đọc xong (kể cả file lỗi)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._closed = False

    def shutdown(self) -> None:
        self._closed = True

    def warm(self, cold: dict) -> None:
        # luồng daemon (không phải QThreadPool/Executor): đóng app không phải chờ ffprobe treo tới 60 giây
        todo = iter(list(cold.values()))
        lock = threading.Lock()
        alive = [min(4, len(cold))]

        def work():
            try:
                while not self._closed:
                    with lock:
                        p = next(todo, None)
                    if p is None:
                        break
                    try:
                        probe.probe(p)
                    except Exception:  # noqa: BLE001
                        pass
            finally:
                with lock:
                    alive[0] -= 1
                    last = alive[0] == 0
                if last:
                    try:
                        self.done.emit(frozenset(cold))
                    except RuntimeError:  # cửa sổ đã đóng
                        pass
        for _ in range(alive[0]):
            threading.Thread(target=work, daemon=True).start()


def _iter_probe(paths):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        yield from ex.map(probe.probe, paths)


ROLE_SUB = Qt.ItemDataRole.UserRole + 5  # dòng phụ dưới tên (thông số clip)
ROLE_SUB_COLOR = Qt.ItemDataRole.UserRole + 6


class TwoLineNameDelegate(QStyledItemDelegate):
    """Cột tên: ô tick + ảnh nhỏ + 2 dòng chữ (tên file / thông số). Tự rút gọn bằng "…" khi hẹp."""

    def createEditor(self, parent, option, index):  # noqa: N802
        return None

    def paint(self, painter, option, index):
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
        o = QStyleOptionViewItem(option)
        self.initStyleOption(o, index)
        title = o.text
        sub = index.data(ROLE_SUB) or ""
        sub_color = index.data(ROLE_SUB_COLOR) or theme.qcolor("text_muted")
        title_color = index.data(Qt.ItemDataRole.ForegroundRole)
        o.text = ""
        style = o.widget.style() if o.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, o, painter, o.widget)
        r = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, o, o.widget).adjusted(4, 0, -4, 0)
        painter.save()
        f1 = QFont(o.font)
        f1.setBold(True)
        f2 = QFont(o.font)
        f2.setPointSizeF(max(7.0, o.font.pointSizeF() - 1.5))
        fm1, fm2 = QFontMetrics(f1), QFontMetrics(f2)
        total_h = fm1.height() + (fm2.height() + 2 if sub else 0)
        y = r.top() + (r.height() - total_h) // 2
        painter.setFont(f1)
        col = title_color.color() if hasattr(title_color, "color") else (title_color or theme.qcolor("text"))
        painter.setPen(QColor(col))
        painter.drawText(QRect(r.left(), y, r.width(), fm1.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         fm1.elidedText(title, Qt.TextElideMode.ElideMiddle, r.width()))
        if sub:
            painter.setFont(f2)
            painter.setPen(QColor(sub_color))
            painter.drawText(QRect(r.left(), y + fm1.height() + 2, r.width(), fm2.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             fm2.elidedText(sub, Qt.TextElideMode.ElideRight, r.width()))
        painter.restore()


class NoEditDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):  # noqa: N802
        return None


class SpinDelegate(QStyledItemDelegate):
    def __init__(self, lo: int, hi: int, parent=None):
        super().__init__(parent)
        self.lo, self.hi = lo, hi

    def createEditor(self, parent, option, index):  # noqa: N802
        sb = QSpinBox(parent)
        sb.setRange(self.lo, self.hi)
        return sb

    def setEditorData(self, editor, index):  # noqa: N802
        try:
            editor.setValue(int(index.data()))
        except (TypeError, ValueError):
            editor.setValue(self.lo)
        select_all_soon(editor)

    def setModelData(self, editor, model, index):  # noqa: N802
        editor.interpretText()
        model.setData(index, str(editor.value()))


def xf_text(sec: float) -> str:
    return "Cắt" if sec <= 0 else f"{sec:g}s"


def parse_xf(text: str) -> float:
    t = (text or "").strip().lower().rstrip("s").replace(",", ".")
    try:
        return max(0.0, float(t))
    except ValueError:
        return 0.0


def xf_spin(parent=None) -> QDoubleSpinBox:
    sb = QDoubleSpinBox(parent)
    sb.setRange(0, 10)
    sb.setSingleStep(0.5)
    sb.setDecimals(1)
    sb.setSuffix(" s")
    sb.setSpecialValueText("Cắt")
    return sb


class XfadeDelegate(QStyledItemDelegate):
    """Ô crossfade: 0 = cắt thẳng, hoặc số giây hoà hình. Không cho sửa khi ô đang bị bỏ qua ('—')."""

    def createEditor(self, parent, option, index):  # noqa: N802
        if str(index.data() or "").strip() in ("—", "-"):
            return None
        return xf_spin(parent)

    def setEditorData(self, editor, index):  # noqa: N802
        editor.setValue(parse_xf(str(index.data())))
        select_all_soon(editor)

    def setModelData(self, editor, model, index):  # noqa: N802
        editor.interpretText()
        model.setData(index, xf_text(editor.value()))


# Ô gõ số lần phát / thời lượng: chỉ chặn ký tự lạ (chữ, số, khoảng trắng, : . , - ' "). Hiểu đúng hay không
# do lúc bấm Enter / rời ô quyết định — không chặn phím giữa chừng (trước đây xoá một chữ số ở giữa cũng bị chặn).
PLAYS_RE = r"^[\w\s:.,'\"\-]{0,40}$"

_UNITS = {"p": 60, "m": 60, "ph": 60, "phút": 60, "phut": 60, "min": 60, "'": 60,
          "s": 1, "giây": 1, "giay": 1, "sec": 1, "\"": 1,
          "h": 3600, "giờ": 3600, "gio": 3600, "tiếng": 3600, "tieng": 3600, "hr": 3600}
_NEXT_UNIT = {3600: 60, 60: 1}  # "1h30" → 30 là phút, "5p30" → 30 là giây


def parse_duration(text: str, bare: float | None = None) -> float | None:
    """Thời lượng gõ tự do → giây. '10p' 600 · '90s' 90 · '1.5h' 5400 · '3 tiếng' 10800 · '1h30' 5400 ·
    '1h 30m' 5400 · '10:00' 600 (phút:giây) · '1:30:00' 5400. `bare`: số không đơn vị nhân với bao nhiêu giây
    (None = không phải thời lượng, ví dụ ô Số lần phát hiểu '70' là 70 lần)."""
    t = unicodedata.normalize("NFC", (text or "")).strip().lower().replace(",", ".")
    if not t:
        return None
    m = re.fullmatch(r"(\d{1,3}):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?", t)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
        return a * 3600 + b * 60 + float(c) if c is not None else a * 60 + b
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return float(t) * bare if bare else None
    if not re.fullmatch(r"(?:\s*\d+(?:\.\d+)?\s*[a-zà-ỹđ'\"]*)+\s*", t):
        return None
    total, prev = 0.0, None
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([a-zà-ỹđ'\"]*)", t):
        if unit:
            if unit not in _UNITS:
                return None
            k = _UNITS[unit]
        elif prev in _NEXT_UNIT:
            k = _NEXT_UNIT[prev]
        else:
            return None
        total += float(num) * k
        prev = k
    return total


def parse_plays(text: str):
    """'70' → ('fixed', 70, 70) · '50-80' → ('random', 50, 80) · '10p' / '1h30' → ('duration', giây, giây).
    Kẹp ở mức tối đa (99.999 lần / 48 giờ) — số quá lớn làm app treo khi tính lịch phát."""
    from ..core.project import MAX_DURATION, MAX_PLAYS
    dur = parse_duration(text)
    if dur is not None:
        dur = min(dur, float(MAX_DURATION))
        return ("duration", dur, dur) if dur > 0 else ("fixed", 0, 0)
    m = re.match(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$", text or "")
    if not m:
        return None
    a = min(int(m.group(1)), MAX_PLAYS)
    if m.group(2) is None:
        return "fixed", a, a
    b = min(int(m.group(2)), MAX_PLAYS)
    lo, hi = min(a, b), max(a, b)
    return ("fixed", lo, lo) if lo == hi else ("random", lo, hi)


def fmt_play_seconds(sec: float) -> str:
    s = int(round(sec))
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def plays_text(mode: str, count, lo, hi) -> str:
    if mode == "duration":
        return fmt_play_seconds(lo)
    return str(count) if mode == "fixed" else f"{lo}-{hi}"


PLAYS_HELP = ("Không hiểu số lần phát vừa gõ. Gõ ví dụ: 70 (70 lần) · 50-80 (ngẫu nhiên) · "
              "10p / 1h30 / 3 tiếng / 10:00 (cho đủ thời lượng).")


SAMPLE_NAMES = {"loop 70 lan": "Loop 70 lần", "3 tieng": "3 tiếng"}


def sample_label(stem: str) -> str:
    """'Du-an-mau - Loop 70 lan' → 'Thử: Loop 70 lần' (tên hiện trên nút dự án thử)."""
    name = stem.replace("Du-an-mau - ", "")
    return "Thử: " + SAMPLE_NAMES.get(name.lower(), name)


def select_all_soon(widget) -> None:
    """Bôi đen hết chữ ngay sau khi ô nhận focus (gõ là thay luôn, khỏi xoá từng chữ)."""
    QTimer.singleShot(0, widget, widget.selectAll)


class DurationEdit(QWidget):
    """Thời lượng = 3 ô số riêng [giờ] [phút] [giây] — gõ số vào đúng ô, không phải nhớ định dạng.
    Gõ dư tự quy đổi (90 phút → 1 giờ 30 phút). Áp dụng khi Enter / rời ô / bấm ▲▼ (đang gõ dở không tính lại)."""
    valueChanged = Signal(float)
    HELP = ("Gõ số vào từng ô: giờ · phút · giây (phím ↑ ↓ để tăng / giảm, Tab để sang ô sau). Gõ dư tự quy đổi, "
            "ví dụ 90 phút → 1 giờ 30 phút. Bấm Enter hoặc bấm ra ngoài để áp dụng.")

    def __init__(self, seconds: float = 0.0, parent=None, allow_zero: bool = False, max_seconds: float | None = None):
        super().__init__(parent)
        from PySide6.QtWidgets import QAbstractSpinBox, QHBoxLayout, QSpinBox
        from ..core.project import MAX_DURATION
        self._max = float(MAX_DURATION if max_seconds is None else max_seconds)
        self._sec = min(self._max, max(0.0, float(seconds)))
        self._allow_zero = allow_zero
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.h, self.m, self.s = QSpinBox(), QSpinBox(), QSpinBox()
        h_max = max(1, int(self._max // 3600))
        for box, hi, unit, width in ((self.h, h_max, "giờ", 50), (self.m, 9999, "phút", 46), (self.s, 99999, "giây", 46)):
            box.setRange(0, hi)
            box.setKeyboardTracking(False)
            box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.setFixedWidth(width)  # gọn: 3 ô + chữ đơn vị vừa cột cài đặt hẹp
            # không mũi tên ▲▼ (chiếm chỗ làm che mất số); tăng / giảm bằng phím ↑ ↓ hoặc lăn chuột khi đã bấm vào ô
            box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            box.setObjectName("timeBox")
            box.setToolTip(self.HELP)
            box.valueChanged.connect(lambda *_: self._commit())
            box.editingFinished.connect(self._commit)
            lab = QLabel(unit)
            lab.setObjectName("muted")
            lay.addWidget(box)
            lay.addWidget(lab)
            if box is not self.s:
                lay.addSpacing(2)
        lay.addStretch(1)
        self._show(self._sec)

    # ---- API dùng chung (giống ô cũ) ----
    def seconds(self) -> float:
        return self._sec

    def text(self) -> str:
        s = int(round(self._sec))
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"

    def setText(self, text: str) -> None:  # noqa: N802 — nút đặt nhanh gọi setText("10:00:00")
        v = parse_duration(text, 60)
        if v is not None:
            self.set_seconds(v)

    def set_seconds(self, sec: float, emit: bool = True) -> None:
        sec = min(self._max, max(0.0, float(sec)))
        changed = abs(sec - self._sec) > 1e-6
        self._sec = sec
        self._show(sec)
        if changed and emit:
            self.valueChanged.emit(sec)

    def setToolTip(self, text: str) -> None:  # noqa: N802
        super().setToolTip(text)
        for box in (self.h, self.m, self.s):
            box.setToolTip(text)

    # ---- bên trong ----
    def _show(self, sec: float) -> None:
        t = int(round(sec))
        for box, v in ((self.h, t // 3600), (self.m, t % 3600 // 60), (self.s, t % 60)):
            box.blockSignals(True)
            box.setValue(v)
            box.blockSignals(False)

    def _commit(self) -> None:
        for box in (self.h, self.m, self.s):
            box.blockSignals(True)
            box.interpretText()
            box.blockSignals(False)
        total = self.h.value() * 3600 + self.m.value() * 60 + self.s.value()
        if total > self._max:
            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())),
                              f"Tối đa {int(self._max // 3600)} giờ — đã đặt về mức tối đa.", self)
            total = self._max
        if total <= 0 and not self._allow_zero:
            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())),
                              "Thời lượng phải lớn hơn 0 — đã giữ giá trị cũ.", self)
            self._show(self._sec)
            return
        self.set_seconds(total)  # hiện lại đã quy đổi (90 phút → 1 giờ 30 phút)


class PlaysDelegate(QStyledItemDelegate):
    """Ô 'Số lần phát': nhập 70 (cố định) hoặc 50-80 (ngẫu nhiên)."""

    def createEditor(self, parent, option, index):  # noqa: N802
        ed = QLineEdit(parent)
        ed.setValidator(QRegularExpressionValidator(PLAYS_RE, ed))
        return ed

    def setEditorData(self, editor, index):  # noqa: N802
        editor.setText(str(index.data() or ""))
        select_all_soon(editor)

    def setModelData(self, editor, model, index):  # noqa: N802
        parsed = parse_plays(editor.text())
        if parsed:
            mode, lo, hi = parsed
            model.setData(index, plays_text(mode, lo, lo, hi))
        elif editor.text().strip():  # gõ sai: báo cách gõ thay vì im lặng giữ số cũ
            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(editor.mapToGlobal(QPoint(0, editor.height())), PLAYS_HELP)


def paint_placeholder(tree: QTreeWidget, text: str, hovered: bool = False, clickable: bool = False,
                      action: str = "") -> None:
    if tree.topLevelItemCount() == 0 and text:
        vp = tree.viewport()
        p = QPainter(vp)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(vp.rect()).adjusted(16, 14, -16, -14)
        if r.width() > 120 and r.height() > 54:
            path = QPainterPath()
            path.addRoundedRect(r, 10, 10)
            border_col = theme.qcolor("accent") if (hovered and clickable) else theme.qcolor("line")
            pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
            p.setPen(pen)
            bg_col = theme.qcolor("accent", 22) if (hovered and clickable) else theme.qcolor("field", 120)
            p.fillPath(path, bg_col)
            p.drawPath(path)

        lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
        cx = vp.width() / 2.0
        cy = vp.height() / 2.0

        if clickable and r.height() >= 110 and len(lines) >= 2:
            # Vẽ vòng tròn icon cộng ở giữa phía trên
            circle_r = 20.0
            circle_y = cy - 28.0
            circle_path = QPainterPath()
            circle_path.addEllipse(QRectF(cx - circle_r, circle_y - circle_r, circle_r * 2, circle_r * 2))
            p.fillPath(circle_path, theme.qcolor("accent", 40 if hovered else 24))
            p.setPen(QPen(theme.qcolor("accent") if hovered else theme.qcolor("line_strong"), 1.2))
            p.drawPath(circle_path)
            pm = icons.pixmap("file_plus", 20, "accent_text" if hovered else "text_muted")
            p.drawPixmap(int(cx - 10), int(circle_y - 10), pm)

            f_title = QFont(tree.font())
            f_title.setPointSize(f_title.pointSize() + 1)
            f_title.setBold(True)
            p.setFont(f_title)
            p.setPen(theme.qcolor("text" if hovered else "text_2"))
            p.drawText(QRectF(24, circle_y + 24, vp.width() - 48, 24),
                       Qt.AlignmentFlag.AlignCenter, lines[0])

            f_sub = QFont(tree.font())
            p.setFont(f_sub)
            p.setPen(theme.qcolor("text_2" if hovered else "text_muted"))
            p.drawText(QRectF(24, circle_y + 46, vp.width() - 48, 36),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "\n".join(lines[1:]))
            if action and r.height() >= 170:  # nút hành động chính (cả khung đều bấm được; nút chỉ để thấy việc cần làm)
                f_btn = QFont(tree.font())
                f_btn.setBold(True)
                p.setFont(f_btn)
                bw = QFontMetrics(f_btn).horizontalAdvance(action) + 52
                br = QRectF(cx - bw / 2, circle_y + 96, bw, 34)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.qcolor("accent_hover" if hovered else "accent"))
                p.drawRoundedRect(br, theme.R["md"], theme.R["md"])
                p.drawPixmap(int(br.left() + 14), int(br.center().y() - 8), icons.pixmap("plus", 16, "text_on_accent"))
                p.setPen(theme.qcolor("text_on_accent"))
                p.drawText(br.adjusted(30, 0, 0, 0), Qt.AlignmentFlag.AlignCenter, action)
        else:
            p.setPen(theme.qcolor("text_muted"))
            f = QFont(tree.font())
            p.setFont(f)
            p.drawText(vp.rect().adjusted(24, 14, -24, -14), Qt.AlignmentFlag.AlignCenter, text)


class PlaceholderTree(QTreeWidget):
    """Bảng chỉ đọc, hiện dòng gợi ý khi trống."""

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.placeholder = placeholder

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        paint_placeholder(self, self.placeholder, False, False)


def fold(text: str) -> str:
    """Bỏ dấu tiếng Việt + chữ thường để tìm kiếm: "Mưa Tháng 6" → "mua thang 6"."""
    s = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower()


class MediaList(QTreeWidget):
    """Bảng file: tick bật/tắt, kéo thả đổi thứ tự, kéo file từ Explorer vào,
    bấm trực tiếp khi bảng trống để chọn file, Ctrl+Space bật/tắt, Delete để xoá."""
    changed = Signal()
    filesDropped = Signal(list)
    openRequested = Signal(str)
    emptyClicked = Signal()
    filterChanged = Signal(int, int)  # (số dòng khớp, tổng số dòng)

    def __init__(self, headers: list[str], parent=None):
        super().__init__(parent)
        self.filter_text = ""
        self.setHeaderLabels(headers)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                             | QAbstractItemView.EditTrigger.SelectedClicked
                             | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setItemDelegate(NoEditDelegate(self))
        self.placeholder = ""
        self.placeholder_action = ""  # chữ trên nút chính vẽ giữa bảng trống (rỗng = không vẽ)
        self._empty_hover = False
        self.itemChanged.connect(lambda *_: self._on_item_changed())
        self.itemDoubleClicked.connect(self._on_double_click)

    def _on_item_changed(self) -> None:
        self._update_cursor()
        self.changed.emit()

    def _update_cursor(self) -> None:
        if self.topLevelItemCount() == 0:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().unsetCursor()

    ITEM_FLAGS = (Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                  | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled
                  | Qt.ItemFlag.ItemIsEditable)

    def new_item(self, texts: list[str], checked: bool) -> QTreeWidgetItem:
        it = QTreeWidgetItem(texts)
        it.setFlags(self.ITEM_FLAGS)
        it.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return it

    def items(self) -> list[QTreeWidgetItem]:
        return [self.topLevelItem(i) for i in range(self.topLevelItemCount())]

    # ----- tìm kiếm -----
    def apply_filter(self, text: str | None = None) -> None:
        """Ẩn các dòng không khớp tên file (không phân biệt hoa thường, không cần gõ dấu, nhiều từ = phải có đủ)."""
        if text is not None:
            self.filter_text = text
        words = fold(self.filter_text).split()
        shown = 0
        for it in self.items():
            data = it.data(0, ROLE_DATA)
            name = os.path.basename(data.path) if data is not None and hasattr(data, "path") else it.text(0)
            ok = all(wd in fold(name) for wd in words)
            it.setHidden(not ok)
            shown += ok
        if words:  # bỏ chọn các dòng bị ẩn để thao tác (xoá, bật/tắt…) chỉ tác động lên dòng đang thấy
            for it in super().selectedItems():
                if it.isHidden():
                    it.setSelected(False)
        self.filterChanged.emit(shown, self.topLevelItemCount())
        self.viewport().update()

    def filtering(self) -> bool:
        return bool(self.filter_text.strip())

    def selectedItems(self):  # noqa: N802 — chỉ các dòng đang hiện (khi đang tìm kiếm)
        return [it for it in super().selectedItems() if not it.isHidden()]

    def visible_items(self) -> list[QTreeWidgetItem]:
        return [it for it in self.items() if not it.isHidden()]

    def paths(self) -> set[str]:
        return {os.path.normcase(it.data(0, ROLE_DATA).path) for it in self.items()}

    # ----- thao tác -----
    def set_all_checked(self, mode: str) -> None:
        """mode: all | none | invert | selected"""
        sel = set(id(i) for i in self.selectedItems())
        self.blockSignals(True)
        for it in self.visible_items():  # đang tìm kiếm: chỉ áp cho các dòng khớp
            on = it.checkState(0) == Qt.CheckState.Checked
            new = {"all": True, "none": False, "invert": not on, "selected": id(it) in sel}[mode]
            it.setCheckState(0, Qt.CheckState.Checked if new else Qt.CheckState.Unchecked)
        self.blockSignals(False)
        self.changed.emit()

    def toggle_selected_checked(self) -> None:
        sel = self.selectedItems()
        if not sel:
            return
        on = sel[0].checkState(0) != Qt.CheckState.Checked
        self.blockSignals(True)
        for it in sel:
            it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.blockSignals(False)
        self.changed.emit()

    def remove_selected(self) -> None:
        for it in self.selectedItems():
            self.takeTopLevelItem(self.indexOfTopLevelItem(it))
        self._update_cursor()
        self.changed.emit()

    def clear_all(self) -> None:
        self.clear()
        self._update_cursor()
        self.changed.emit()

    def move_selected(self, delta: int) -> None:
        rows = sorted(self.indexOfTopLevelItem(i) for i in self.selectedItems())
        if not rows:
            return
        if delta < 0 and rows[0] == 0 or delta > 0 and rows[-1] == self.topLevelItemCount() - 1:
            return
        self.blockSignals(True)
        for r in (rows if delta < 0 else reversed(rows)):
            it = self.takeTopLevelItem(r)
            self.insertTopLevelItem(r + delta, it)
            it.setSelected(True)
        self.blockSignals(False)
        self.changed.emit()

    def shuffle(self, rng) -> None:
        its = [self.takeTopLevelItem(0) for _ in range(self.topLevelItemCount())]
        rng.shuffle(its)
        self.blockSignals(True)
        self.addTopLevelItems(its)
        self.blockSignals(False)
        self.changed.emit()

    def sort_by_name(self) -> None:
        its = [self.takeTopLevelItem(0) for _ in range(self.topLevelItemCount())]
        its.sort(key=lambda it: natural_key(it.data(0, ROLE_DATA).path))
        self.blockSignals(True)
        self.addTopLevelItems(its)
        self.blockSignals(False)
        self.changed.emit()

    # ----- sự kiện -----
    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        self._update_cursor()
        paint_placeholder(self, self.placeholder, self._empty_hover, True, self.placeholder_action)
        if self.filtering() and self.topLevelItemCount() and not self.visible_items():
            p = QPainter(self.viewport())
            p.setPen(theme.qcolor("text_muted"))
            p.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                       f"Không có file nào khớp “{self.filter_text.strip()}”")

    def enterEvent(self, e) -> None:  # noqa: N802
        super().enterEvent(e)
        if self.topLevelItemCount() == 0:
            self._empty_hover = True
            self.viewport().update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        super().leaveEvent(e)
        if self._empty_hover:
            self._empty_hover = False
            self.viewport().update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if self.topLevelItemCount() == 0 and e.button() == Qt.MouseButton.LeftButton:
            self.emptyClicked.emit()
            return
        super().mousePressEvent(e)

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        item = self.itemAt(e.pos())
        menu = QMenu(self)
        if item is not None:
            data = item.data(0, ROLE_DATA)
            path = getattr(data, "path", "")
            if path:
                menu.addAction(icons.icon("play", 14), "Mở / Xem thử file", lambda: self.openRequested.emit(path))
                menu.addAction(icons.icon("folder", 14), "Hiện trong Explorer", lambda: reveal_in_explorer(path))
                for ic, text, fn in getattr(self, "menu_extras", []):  # mục riêng của từng bảng
                    menu.addAction(icons.icon(ic, 14), text, lambda f=fn, it=item: f(it))
                menu.addSeparator()
            menu.addAction(icons.icon("check", 14), "Bật / Tắt dòng chọn (Ctrl+Space)", self.toggle_selected_checked)
            menu.addAction(icons.icon("up", 14), "Đưa lên trên", lambda: self.move_selected(-1))
            menu.addAction(icons.icon("down", 14), "Đưa xuống dưới", lambda: self.move_selected(1))
            menu.addSeparator()
            menu.addAction(icons.icon("trash", 14, "danger_text"), "Xoá dòng đang chọn (Delete)", self.remove_selected)
        if self.topLevelItemCount() > 0:
            if not menu.isEmpty():
                menu.addSeparator()
            menu.addAction(icons.icon("check", 14), "Bật tất cả", lambda: self.set_all_checked("all"))
            menu.addAction("Tắt tất cả", lambda: self.set_all_checked("none"))
        if not menu.isEmpty():
            menu.exec(e.globalPos())

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        # Ctrl+Space bật / tắt dòng (Space để dành cho Phát / Dừng trình phát, như CapCut / Premiere)
        if (e.key() == Qt.Key.Key_Space and e.modifiers() & Qt.KeyboardModifier.ControlModifier
                and self.state() != QAbstractItemView.State.EditingState):
            self.toggle_selected_checked()
            return
        if e.key() == Qt.Key.Key_Delete and self.state() != QAbstractItemView.State.EditingState:
            self.remove_selected()
            return
        super().keyPressEvent(e)

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            self._empty_hover = True
            self.viewport().update()
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragLeaveEvent(self, e):  # noqa: N802
        self._empty_hover = False
        self.viewport().update()
        super().dragLeaveEvent(e)

    def dragMoveEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):  # noqa: N802
        self._empty_hover = False
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            e.acceptProposedAction()
            self.filesDropped.emit(paths)
            return
        super().dropEvent(e)
        self.changed.emit()

    def _on_double_click(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0:
            self.openRequested.emit(item.data(0, ROLE_DATA).path)


def expand_dropped(paths: list[str], exts: set[str], recursive: bool = True) -> list[str]:
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += scan_folder(p, exts, recursive)
        elif Path(p).suffix.lower() in exts:
            out.append(p)
    return out


class ListToolbar(QWidget):
    """Một hàng: [+ Thêm file] [Thư mục] [Cả thư mục con] [ô tìm kiếm] [Xoá] [⋯]. Sắp xếp, xáo, bật / tắt, đưa lên / xuống,
    xoá hết nằm trong menu ⋯ (ít dùng hơn, và nút đỏ "Xoá hết" không còn nằm sát nút thường dùng)."""

    def __init__(self, lst: MediaList, add_files, add_folder, rng_factory, parent=None):
        super().__init__(parent)
        self.lst = lst
        self.recursive = QCheckBox("Cả thư mục con")
        self.recursive.setFixedHeight(32)
        self.recursive.setToolTip("Quét thư mục con: khi thêm thư mục hoặc kéo thả thư mục, tự quét cả các thư mục con bên trong")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        add_btn = QPushButton("Thêm file")
        add_btn.setObjectName("accentBtn")
        add_btn.setIcon(icons.icon("plus", 14, "accent_text"))
        add_btn.setIconSize(QSize(14, 14))
        add_btn.setToolTip("Thêm file lẻ (hoặc bấm vào bảng trống / kéo thả file vào bảng)")
        add_btn.clicked.connect(add_files)
        folder_btn = QPushButton("Thư mục")
        folder_btn.setIcon(icons.icon("folder", 14, "text_2"))
        folder_btn.setIconSize(QSize(14, 14))
        folder_btn.setToolTip("Chọn và quét cả thư mục")
        folder_btn.clicked.connect(add_folder)
        for b in (add_btn, folder_btn):
            b.setFixedHeight(32)
            lay.addWidget(b)
        lay.addWidget(self.recursive)

        # ----- tìm theo tên file -----
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Tìm tên file…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", 14, "text_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setMinimumWidth(120)
        self.search.setFixedHeight(32)
        self.search.setToolTip("Gõ một phần tên file, không cần dấu (\"mua\" ra \"Mưa…\"). Nhiều từ = phải có đủ.\n"
                               "Khi đang tìm: Xoá, Bật/Tắt, Chọn tất cả chỉ áp cho các dòng đang hiện. Esc để xoá.")
        self.search.textChanged.connect(lst.apply_filter)
        lay.addWidget(self.search, 1)
        self.match = QLabel("")
        self.match.setProperty("role", "match")
        lay.addWidget(self.match)

        del_btn = QPushButton("")
        del_btn.setObjectName("ghost")
        del_btn.setProperty("icononly", True)
        del_btn.setIcon(icons.icon("trash", 16, "text_2"))
        del_btn.setIconSize(QSize(16, 16))
        del_btn.setFixedSize(32, 32)
        del_btn.setToolTip("Xoá các dòng đang chọn khỏi danh sách (phím Delete)")
        del_btn.clicked.connect(lst.remove_selected)
        lay.addWidget(del_btn)

        more = QPushButton("")
        more.setObjectName("ghost")
        more.setProperty("icononly", True)
        more.setIcon(icons.icon("more", 16, "text_2"))
        more.setIconSize(QSize(16, 16))
        more.setFixedSize(32, 32)
        more.setToolTip("Thêm thao tác: đưa lên / xuống, sắp xếp, xáo, bật / tắt, xoá tất cả")
        menu = QMenu(more)
        menu.addAction(icons.icon("up", 14), "Đưa dòng chọn lên trên", lambda: lst.move_selected(-1))
        menu.addAction(icons.icon("down", 14), "Đưa dòng chọn xuống dưới", lambda: lst.move_selected(1))
        menu.addSeparator()
        menu.addAction(icons.icon("sort", 14), "Sắp xếp A–Z (clip2 trước clip10)", lst.sort_by_name)
        menu.addAction(icons.icon("shuffle", 14), "Xáo ngẫu nhiên thứ tự", lambda: lst.shuffle(rng_factory()))
        menu.addSeparator()
        sel = menu.addMenu(icons.icon("check", 14), "Bật / tắt nhanh")
        sel.addAction("Bật tất cả", lambda: lst.set_all_checked("all"))
        sel.addAction("Tắt tất cả", lambda: lst.set_all_checked("none"))
        sel.addAction("Đảo ngược trạng thái bật/tắt", lambda: lst.set_all_checked("invert"))
        sel.addAction("Chỉ bật các dòng đang bôi đen", lambda: lst.set_all_checked("selected"))
        menu.addSeparator()
        menu.addAction(icons.icon("trash", 14, "danger_text"), "Xoá tất cả", lst.clear_all)
        more.setMenu(menu)
        self.more_btn = more
        lay.addWidget(more)

        lst.filterChanged.connect(self._on_filter)
        # file mới thêm / xếp lại: lọc lại theo ô tìm kiếm
        lst.model().rowsInserted.connect(lambda *_: QTimer.singleShot(0, self._refilter))
        find = QShortcut(QKeySequence.StandardKey.Find, self)
        find.setContext(Qt.ShortcutContext.WindowShortcut)
        find.activated.connect(self._focus_search)
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.search)
        esc.setContext(Qt.ShortcutContext.WidgetShortcut)
        esc.activated.connect(self.search.clear)

    def _refilter(self) -> None:
        if self.lst.filtering():
            self.lst.apply_filter()

    def _on_filter(self, shown: int, total: int) -> None:
        self.match.setText(f"{shown}/{total} khớp" if self.lst.filtering() else "")
        theme.tag(self.match, role="match", tone="danger" if self.lst.filtering() and not shown else "")

    def _focus_search(self) -> None:
        if self.isVisible():  # chỉ trang đang mở
            self.search.setFocus()
            self.search.selectAll()


class _PageTransition(QWidget):
    """Lớp vẽ tạm khi chuyển trang: chỉ vẽ 2 ảnh chụp (trang cũ mờ dần, trang mới trượt vào + hiện dần).
    Vẽ ảnh chụp rất nhẹ nên chuyển trang luôn mượt, kể cả trang có bảng dài và nhiều ảnh thu nhỏ."""

    def __init__(self, stack, old_pm, new_pm, dx: int):
        super().__init__(stack)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setGeometry(stack.rect())
        self.old_pm, self.new_pm, self.dx = old_pm, new_pm, dx
        self.t = 0.0
        self.show()
        self.raise_()

    def set_t(self, v) -> None:
        self.t = float(v)
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        t = self.t
        if self.old_pm is not None and t < 1:
            p.setOpacity(max(0.0, 1 - t * 2.4))  # trang cũ tắt nhanh, hai trang không chồng chữ lên nhau lâu
            p.drawPixmap(int(-self.dx * 0.35 * t), 0, self.old_pm)
        p.setOpacity(t)
        p.drawPixmap(int(self.dx * (1 - t)), 0, self.new_pm)


class AnimatedStackedWidget(QStackedWidget):
    """QStackedWidget có hiệu ứng chuyển trang: trang mới trượt nhẹ theo hướng chuyển + hiện dần (260 ms).

    Chụp ảnh trang cũ / trang mới một lần rồi chỉ vẽ ảnh trong lúc chạy hiệu ứng (không vẽ lại cả trang mỗi khung
    hình như dùng QGraphicsOpacityEffect) → mượt hơn hẳn. Xong hiệu ứng thì trang thật hiện lại đúng chỗ."""

    SLIDE = 34
    MS = 260

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim = None
        self._overlay: _PageTransition | None = None
        self._anim_widget: QWidget | None = None

    def _cleanup_anim(self) -> None:
        if self._anim is not None:
            try:
                self._anim.stop()
                self._anim.deleteLater()
            except RuntimeError:
                pass
            self._anim = None
        if self._overlay is not None:
            try:
                self._overlay.hide()
                self._overlay.deleteLater()
            except RuntimeError:
                pass
            self._overlay = None
        if self._anim_widget is not None:
            try:
                self._anim_widget.move(0, 0)
            except RuntimeError:
                pass
            self._anim_widget = None

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self._overlay is not None:
            self._cleanup_anim()  # đổi cỡ giữa chừng: bỏ hiệu ứng, hiện trang thật ngay

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        from PySide6.QtCore import QVariantAnimation
        old = self.currentIndex()
        if old == index or not (0 <= index < self.count()):
            super().setCurrentIndex(index)
            return
        self._cleanup_anim()
        old_w = self.currentWidget()
        visible = self.isVisible() and self.width() > 0
        old_pm = old_w.grab() if (visible and old_w is not None) else None
        super().setCurrentIndex(index)
        w = self.widget(index)
        if not visible or w is None:
            return
        w.setGeometry(self.rect())
        if w.layout() is not None:
            w.layout().activate()
        new_pm = w.grab()
        dx = self.SLIDE if index > old else -self.SLIDE
        self._overlay = _PageTransition(self, old_pm, new_pm, dx)
        w.move(self.width() * 3, 0)  # trang thật nằm ngoài khung trong lúc chạy hiệu ứng (vẫn nhận dữ liệu như thường)
        self._anim_widget = w
        anim = QVariantAnimation(self)
        anim.setDuration(self.MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._overlay.set_t)
        anim.finished.connect(self._cleanup_anim)
        self._anim = anim
        anim.start()


def adapt_split(split, width: int, threshold: int, side_min: int = 440, page=None,
                stacked_height: int = 1450, first_height: int = 0) -> None:
    """Cửa sổ hẹp: xếp phần cài đặt xuống dưới thay vì bên phải; trang cao hơn và cuộn dọc.

    first_height > 0: khi xếp dọc, khối trên (danh sách) cao đúng bằng phần nhìn thấy của trang → bảng + thanh thao tác
    vừa một màn hình, phần cài đặt nằm ngay bên dưới (cuộn xuống là thấy)."""
    want = Qt.Orientation.Vertical if width < threshold else Qt.Orientation.Horizontal
    if split.orientation() == want:
        if want == Qt.Orientation.Vertical and first_height and split.property("_first_h") != first_height:
            second = max(300, stacked_height - first_height)
            split.setProperty("_first_h", first_height)
            if page is not None:
                page.setMinimumHeight(first_height + second)
            split.setSizes([first_height, second])
        return
    split.setOrientation(want)
    side = split.widget(1)
    if want == Qt.Orientation.Vertical:
        side.setMinimumWidth(0)
        if first_height:
            second = max(300, stacked_height - first_height)
            split.setProperty("_first_h", first_height)
            if page is not None:
                page.setMinimumHeight(first_height + second)
            split.setSizes([first_height, second])
        else:
            if page is not None:
                page.setMinimumHeight(stacked_height)
            split.setSizes([int(stacked_height * 0.55), int(stacked_height * 0.45)])
    else:
        side.setMinimumWidth(side_min)
        if page is not None:
            page.setMinimumHeight(0)
        split.setSizes([max(1, width - side_min), side_min])


class ElidedLabel(QLabel):
    """Nhãn một dòng: chữ dài tự rút gọn bằng "…" theo chiều rộng, đầy đủ nằm trong tooltip. Không đòi chiều rộng tối thiểu."""

    def __init__(self, text: str = "", mode=Qt.TextElideMode.ElideRight, parent=None):
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self._tip = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.set_full_text(text)

    def full_text(self) -> str:
        return self._full

    def setText(self, text: str) -> None:  # noqa: N802
        self.set_full_text(text)

    def set_full_text(self, text: str, tip: str = "") -> None:
        self._full, self._tip = text, tip
        self._refit()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._refit()

    def _refit(self) -> None:
        shown = QFontMetrics(self.font()).elidedText(self._full, self._mode, max(0, self.width() - 2))
        if shown != self.text():
            super().setText(shown)
        self.setToolTip(self._tip or (self._full if shown != self._full else ""))


def hairline() -> QFrame:
    """Vạch dọc mảnh ngăn các nhóm điều khiển trên một hàng."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setProperty("role", "hairline")
    line.setFixedHeight(20)
    return line


def muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab


def pick_files(parent, title: str, exts: set[str], start_dir: str) -> list[str]:
    pattern = " ".join(f"*{e}" for e in sorted(exts))
    files, _ = QFileDialog.getOpenFileNames(parent, title, start_dir, f"Media ({pattern});;Tất cả (*.*)")
    return files


def pick_folder(parent, title: str, start_dir: str) -> str:
    return QFileDialog.getExistingDirectory(parent, title, start_dir)


class FlowLayout(QLayout):
    """Xếp widget theo hàng, tự xuống dòng khi không đủ chỗ (giao diện co giãn)."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect, test_only):
        sp = self.spacing()
        lines: list[list] = [[]]
        x = rect.x()
        for item in self._items:
            hint = item.sizeHint()
            if lines[-1] and x + hint.width() > rect.right() + 1:
                lines.append([])
                x = rect.x()
            lines[-1].append((item, hint))
            x += hint.width() + sp
        y = rect.y()
        for line in lines:
            if not line:
                continue
            line_h = max(h.height() for _, h in line)
            x = rect.x()
            for item, hint in line:
                if not test_only:  # canh giữa theo chiều dọc để các nút thẳng hàng
                    item.setGeometry(QRect(QPoint(x, y + (line_h - hint.height()) // 2), hint))
                x += hint.width() + sp
            y += line_h + sp
        return max(0, y - sp - rect.y())


class ThumbLoader(QObject):
    """Tạo ảnh nhỏ (frame giây thứ 1) cho clip ở luồng nền, có cache trên đĩa."""
    image = Signal(str, QImage)  # (đường dẫn clip, ảnh đã giải mã ở luồng nền — rỗng nếu lỗi; QPixmap chỉ tạo ở luồng giao diện)
    W, H = 72, 40

    def __init__(self, parent=None):
        super().__init__(parent)
        self._closed = False
        self._pool = ThreadPoolExecutor(max_workers=2)

    def shutdown(self) -> None:
        self._closed = True
        try:
            self._pool.shutdown(wait=False, cancel_futures=True)
        except Exception:  # noqa: BLE001
            pass

    def request(self, paths: list[str]) -> None:
        if self._closed:
            return
        for p in paths:
            try:
                self._pool.submit(self._work, p)
            except RuntimeError:
                break

    def _work(self, path: str) -> None:
        if self._closed:
            return
        img = self._render(path) or QImage()
        if not self._closed:
            try:
                self.image.emit(path, img)  # ảnh rỗng = lỗi: giao diện dọn dòng đang chờ
            except RuntimeError:
                pass

    def _render(self, path: str):
        try:
            st = os.stat(path)
        except OSError:
            return
        key = hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8")).hexdigest()[:20]
        out = ft.cache_dir("thumbs") / f"{key}.jpg"
        if not out.is_file():
            is_img = Path(path).suffix.lower() in IMAGE_EXTS
            seek = [] if is_img else ["-ss", "1"]
            vf = (f"scale={self.W * 2}:{self.H * 2}:force_original_aspect_ratio=decrease,"
                  f"pad={self.W * 2}:{self.H * 2}:(ow-iw)/2:(oh-ih)/2:color=0x11141b")
            try:
                ft.run([ft.ffmpeg(), "-v", "error", "-y", *seek, "-i", path, "-frames:v", "1", "-vf", vf,
                        "-q:v", "4", str(out)], timeout=30)
                if not out.is_file() and not self._closed:  # clip ngắn hơn 1 giây
                    ft.run([ft.ffmpeg(), "-v", "error", "-y", "-i", path, "-frames:v", "1", "-vf", vf,
                            str(out)], timeout=30)
            except Exception:  # noqa: BLE001
                return
        if out.is_file():
            img = QImage(str(out))
            return None if img.isNull() else img
        return None


class WheelGuard(QObject):
    """Lăn chuột chỉ cuộn trang: ô chọn/ô số chỉ đổi giá trị bằng lăn chuột khi đã được bấm chọn (có focus).
    Tránh việc cuộn ngang qua làm đổi cài đặt mà người dùng không biết."""

    TYPES = (QComboBox, QAbstractSpinBox)

    def eventFilter(self, obj, event):  # noqa: N802
        t = event.type()
        if t == QEvent.Type.FocusIn and (isinstance(obj, QAbstractSpinBox)
                                          or (isinstance(obj, QLineEdit) and obj.property("selectOnFocus"))):
            if event.reason() in (Qt.FocusReason.MouseFocusReason, Qt.FocusReason.TabFocusReason,
                                  Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason):
                select_all_soon(obj)  # gõ là thay cả số (không phải xoá từng chữ); bấm lần nữa để đặt con trỏ
            return False
        if t == QEvent.Type.Polish and isinstance(obj, self.TYPES):
            obj.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # mặc định WheelFocus: lăn qua là chiếm focus
            if isinstance(obj, QAbstractSpinBox):
                # gõ "120" không làm app tính lại 3 lần (1 → 12 → 120): áp khi Enter / rời ô / bấm mũi tên
                obj.setKeyboardTracking(False)
        elif t == QEvent.Type.Wheel and isinstance(obj, self.TYPES) and not obj.hasFocus():
            area = obj.parentWidget()
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parentWidget()
            if area is not None:
                QApplication.sendEvent(area.verticalScrollBar(), event)
            return True
        return False
