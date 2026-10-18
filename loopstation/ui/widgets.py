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
from PySide6.QtGui import (QFontMetrics, QColor, QFont, QKeyEvent, QKeySequence, QPainter, QPainterPath, QPen,
                           QRegularExpressionValidator, QShortcut)
from PySide6.QtWidgets import (
    QApplication, QAbstractScrollArea, QAbstractSpinBox, QComboBox, QFrame, QGraphicsOpacityEffect,
    QLayout, QMenu, QSizePolicy, QStackedWidget,
    QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QLineEdit, QPushButton,
    QDoubleSpinBox, QLabel, QSpinBox, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QWidget,
)

from ..core import ffmpeg_tools as ft
from ..core import probe
from . import icons

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
        sub_color = index.data(ROLE_SUB_COLOR) or QColor("#8c96b0")
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
        col = title_color.color() if hasattr(title_color, "color") else (title_color or QColor("#eef1f8"))
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

    def setModelData(self, editor, model, index):  # noqa: N802
        editor.interpretText()
        model.setData(index, xf_text(editor.value()))


# 70 · 50-80 · hoặc thời lượng: 10p / 10m / 90s / 1.5h / 10:00 / 1:30:00
PLAYS_RE = (r"(?i)^\s*(\d{1,6}\s*(-\s*\d{1,6})?|\d+([.,]\d+)?\s*(p|m|ph|phút|phut|s|giây|giay|h|giờ|gio|')"
            r"|\d{1,3}:\d{1,2}(:\d{1,2})?)\s*$")

_UNITS = {"p": 60, "m": 60, "ph": 60, "phút": 60, "phut": 60, "'": 60, "s": 1, "giây": 1, "giay": 1,
          "h": 3600, "giờ": 3600, "gio": 3600}


def parse_duration(text: str) -> float | None:
    """'10p' → 600 · '90s' → 90 · '1.5h' → 5400 · '10:00' → 600 · '1:30:00' → 5400."""
    t = (text or "").strip().lower().replace(",", ".")
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(p|m|ph|phút|phut|s|giây|giay|h|giờ|gio|')$", t)
    if m:
        return float(m.group(1)) * _UNITS[m.group(2)]
    m = re.match(r"^(\d{1,3}):(\d{1,2})(?::(\d{1,2}))?$", t)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
        return a * 3600 + b * 60 + int(c) if c is not None else a * 60 + b
    return None


def parse_plays(text: str):
    """'70' → ('fixed', 70, 70) · '50-80' → ('random', 50, 80) · '10p' → ('duration', 600.0, 600.0)."""
    dur = parse_duration(text)
    if dur is not None:
        return ("duration", dur, dur) if dur > 0 else ("fixed", 0, 0)
    m = re.match(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$", text or "")
    if not m:
        return None
    a = int(m.group(1))
    if m.group(2) is None:
        return "fixed", a, a
    b = int(m.group(2))
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


class PlaysDelegate(QStyledItemDelegate):
    """Ô 'Số lần phát': nhập 70 (cố định) hoặc 50-80 (ngẫu nhiên)."""

    def createEditor(self, parent, option, index):  # noqa: N802
        ed = QLineEdit(parent)
        ed.setValidator(QRegularExpressionValidator(PLAYS_RE, ed))
        return ed

    def setEditorData(self, editor, index):  # noqa: N802
        editor.setText(str(index.data() or ""))
        editor.selectAll()

    def setModelData(self, editor, model, index):  # noqa: N802
        parsed = parse_plays(editor.text())
        if parsed:
            mode, lo, hi = parsed
            model.setData(index, plays_text(mode, lo, lo, hi))


def paint_placeholder(tree: QTreeWidget, text: str, hovered: bool = False, clickable: bool = False) -> None:
    if tree.topLevelItemCount() == 0 and text:
        vp = tree.viewport()
        p = QPainter(vp)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(vp.rect()).adjusted(16, 14, -16, -14)
        if r.width() > 120 and r.height() > 54:
            path = QPainterPath()
            path.addRoundedRect(r, 10, 10)
            border_col = QColor("#6c63ff") if (hovered and clickable) else QColor("#263046")
            pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
            p.setPen(pen)
            bg_col = QColor(108, 99, 255, 18) if (hovered and clickable) else QColor(13, 16, 24, 120)
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
            p.fillPath(circle_path, QColor(108, 99, 255, 36 if hovered else 22))
            p.setPen(QPen(QColor("#6c63ff" if hovered else "#3b4766"), 1.2))
            p.drawPath(circle_path)
            pm = icons.pixmap("file_plus", 20, "#a5b4fc" if hovered else "#8b95b0")
            p.drawPixmap(int(cx - 10), int(circle_y - 10), pm)

            f_title = QFont(tree.font())
            f_title.setPointSize(f_title.pointSize() + 1)
            f_title.setBold(True)
            p.setFont(f_title)
            p.setPen(QColor("#eef1f8" if hovered else "#c3cbe0"))
            p.drawText(QRectF(24, circle_y + 24, vp.width() - 48, 24),
                       Qt.AlignmentFlag.AlignCenter, lines[0])

            f_sub = QFont(tree.font())
            p.setFont(f_sub)
            p.setPen(QColor("#8c96b0" if hovered else "#6d7792"))
            p.drawText(QRectF(24, circle_y + 46, vp.width() - 48, 36),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "\n".join(lines[1:]))
        else:
            p.setPen(QColor("#7d87a3"))
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
    bấm trực tiếp khi bảng trống để chọn file, phím Space bật/tắt, Delete để xoá."""
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
        paint_placeholder(self, self.placeholder, self._empty_hover, True)
        if self.filtering() and self.topLevelItemCount() and not self.visible_items():
            p = QPainter(self.viewport())
            p.setPen(QColor("#7c86a2"))
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
            menu.addAction(icons.icon("check", 14), "Bật / Tắt dòng chọn (Space)", self.toggle_selected_checked)
            menu.addAction(icons.icon("up", 14), "Đưa lên trên", lambda: self.move_selected(-1))
            menu.addAction(icons.icon("down", 14), "Đưa xuống dưới", lambda: self.move_selected(1))
            menu.addSeparator()
            menu.addAction(icons.icon("trash", 14, "#fca5a5"), "Xoá dòng đang chọn (Delete)", self.remove_selected)
        if self.topLevelItemCount() > 0:
            if not menu.isEmpty():
                menu.addSeparator()
            menu.addAction(icons.icon("check", 14), "Tick chọn tất cả", lambda: self.set_all_checked("all"))
            menu.addAction("Bỏ tick tất cả", lambda: self.set_all_checked("none"))
        if not menu.isEmpty():
            menu.exec(e.globalPos())

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Space and self.state() != QAbstractItemView.State.EditingState:
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
    """Hàng nút thao tác cho MediaList tinh gọn với vector icons và menu chọn nhanh."""

    def __init__(self, lst: MediaList, add_files, add_folder, rng_factory, parent=None):
        super().__init__(parent)
        self.recursive = QCheckBox("Thư mục con")
        self.recursive.setFixedHeight(32)
        self.recursive.setToolTip("Khi thêm thư mục hoặc kéo thả thư mục, tự quét cả các thư mục con bên trong")
        lay = FlowLayout(self, spacing=4)

        def btn(text, tip, fn, name="", icon_name="", icon_color="#c3cbe0"):
            b = QPushButton(text)
            b.setToolTip(tip)
            if name:
                b.setObjectName(name)
            if icon_name:
                b.setIcon(icons.icon(icon_name, 14, icon_color))
                b.setIconSize(QSize(14, 14))
            b.clicked.connect(fn)
            b.setFixedHeight(32)
            lay.addWidget(b)
            return b

        def sep():
            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setStyleSheet("color: #252c3f;")
            line.setFixedHeight(20)
            lay.addWidget(line)

        btn("Thêm file", "Thêm file lẻ (hoặc bấm vào bảng trống / kéo thả file vào bảng)",
            add_files, "accentBtn", "plus", "#ffffff")
        btn("Thư mục", "Chọn và quét cả thư mục", add_folder, "", "folder")
        lay.addWidget(self.recursive)
        sep()
        btn("", "Đưa dòng đang chọn lên trên", lambda: lst.move_selected(-1), "ghost", "up")
        btn("", "Đưa dòng đang chọn xuống dưới", lambda: lst.move_selected(1), "ghost", "down")
        btn("A–Z", "Sắp xếp tự nhiên theo tên (clip2 trước clip10)", lst.sort_by_name, "ghost", "sort")
        btn("Trộn", "Xáo trộn ngẫu nhiên thứ tự ngay trên bảng",
            lambda: lst.shuffle(rng_factory()), "ghost", "shuffle")
        sep()

        sel_btn = QPushButton("Chọn")
        sel_btn.setObjectName("ghost")
        sel_btn.setIcon(icons.icon("check", 14, "#c3cbe0"))
        sel_btn.setIconSize(QSize(14, 14))
        sel_btn.setToolTip("Các thao tác bật/tắt nhanh danh sách")
        sel_menu = QMenu(sel_btn)
        sel_menu.addAction(icons.icon("check", 14), "Bật (tick) tất cả", lambda: lst.set_all_checked("all"))
        sel_menu.addAction("Tắt (bỏ tick) tất cả", lambda: lst.set_all_checked("none"))
        sel_menu.addAction("Đảo ngược trạng thái bật/tắt", lambda: lst.set_all_checked("invert"))
        sel_menu.addAction("Chỉ bật các dòng đang bôi đen", lambda: lst.set_all_checked("selected"))
        sel_btn.setMenu(sel_menu)
        sel_btn.setFixedHeight(32)
        lay.addWidget(sel_btn)

        btn("Xoá", "Xoá các dòng đang chọn khỏi danh sách (phím Delete)",
            lst.remove_selected, "ghost", "trash")
        btn("Xoá hết", "Xoá toàn bộ danh sách", lst.clear_all, "danger", "trash", "#fca5a5")
        sep()

        # ----- tìm theo tên file -----
        self.lst = lst
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Tìm tên file…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", 14, "#8c96b0"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setFixedWidth(230)
        self.search.setFixedHeight(32)
        self.search.setToolTip("Gõ một phần tên file, không cần dấu (\"mua\" ra \"Mưa…\"). Nhiều từ = phải có đủ.\n"
                               "Khi đang tìm: Xoá, Bật/Tắt, Chọn tất cả chỉ áp cho các dòng đang hiện. Esc để xoá.")
        self.search.textChanged.connect(lst.apply_filter)
        lay.addWidget(self.search)
        self.match = QLabel("")
        self.match.setObjectName("muted")
        self.match.setFixedHeight(32)
        lay.addWidget(self.match)
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
        color = "#f87171" if self.lst.filtering() and not shown else "#a78bfa"
        self.match.setStyleSheet(f"color: {color}; font-weight: 600;")

    def _focus_search(self) -> None:
        if self.isVisible():  # chỉ trang đang mở
            self.search.setFocus()
            self.search.selectAll()


class AnimatedStackedWidget(QStackedWidget):
    """QStackedWidget có hiệu ứng chuyển trang: trang mới hiện dần và trượt nhẹ theo hướng chuyển (240 ms)."""

    SLIDE = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim = None
        self._anim_widget: QWidget | None = None

    def _cleanup_anim(self) -> None:
        if self._anim is not None:
            try:
                self._anim.stop()
                self._anim.deleteLater()
            except RuntimeError:
                pass
            self._anim = None
        if self._anim_widget is not None:
            try:
                self._anim_widget.setGraphicsEffect(None)
                self._anim_widget.move(0, 0)
            except RuntimeError:
                pass
            self._anim_widget = None

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        from PySide6.QtCore import QParallelAnimationGroup, QPoint
        old = self.currentIndex()
        if old == index or not (0 <= index < self.count()):
            super().setCurrentIndex(index)
            return
        self._cleanup_anim()
        super().setCurrentIndex(index)
        if not self.isVisible():
            return
        w = self.widget(index)
        if w is None:
            return
        eff = QGraphicsOpacityEffect(w)
        eff.setOpacity(0.0)
        w.setGraphicsEffect(eff)
        fade = QPropertyAnimation(eff, b"opacity")
        fade.setDuration(220)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        dx = self.SLIDE if index > old else -self.SLIDE
        slide = QPropertyAnimation(w, b"pos")
        slide.setDuration(260)
        slide.setStartValue(QPoint(dx, 0))
        slide.setEndValue(QPoint(0, 0))
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)
        group.addAnimation(slide)
        w.move(dx, 0)
        self._anim = group
        self._anim_widget = w
        group.finished.connect(self._cleanup_anim)
        group.start()


def adapt_split(split, width: int, threshold: int, side_min: int = 440, page=None,
                stacked_height: int = 1450) -> None:
    """Cửa sổ hẹp: xếp phần cài đặt xuống dưới thay vì bên phải; trang cao hơn và cuộn dọc."""
    want = Qt.Orientation.Vertical if width < threshold else Qt.Orientation.Horizontal
    if split.orientation() == want:
        return
    split.setOrientation(want)
    side = split.widget(1)
    if want == Qt.Orientation.Vertical:
        side.setMinimumWidth(0)
        if page is not None:
            page.setMinimumHeight(stacked_height)
        split.setSizes([int(stacked_height * 0.55), int(stacked_height * 0.45)])
    else:
        side.setMinimumWidth(side_min)
        if page is not None:
            page.setMinimumHeight(0)
        split.setSizes([max(1, width - side_min), side_min])


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
    ready = Signal(str, str)  # (đường dẫn clip, file ảnh nhỏ)
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
        if out.is_file() and not self._closed:
            try:
                self.ready.emit(path, str(out))
            except RuntimeError:
                pass


class WheelGuard(QObject):
    """Lăn chuột chỉ cuộn trang: ô chọn/ô số chỉ đổi giá trị bằng lăn chuột khi đã được bấm chọn (có focus).
    Tránh việc cuộn ngang qua làm đổi cài đặt mà người dùng không biết."""

    TYPES = (QComboBox, QAbstractSpinBox)

    def eventFilter(self, obj, event):  # noqa: N802
        t = event.type()
        if t == QEvent.Type.Polish and isinstance(obj, self.TYPES):
            obj.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # mặc định WheelFocus: lăn qua là chiếm focus
        elif t == QEvent.Type.Wheel and isinstance(obj, self.TYPES) and not obj.hasFocus():
            area = obj.parentWidget()
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parentWidget()
            if area is not None:
                QApplication.sendEvent(area.verticalScrollBar(), event)
            return True
        return False
