"""Hộp thoại "Xếp kịch bản clip nền": nền ×N → cảnh → nền → cảnh … → nền, lặp cả mẫu N lượt.

- Cảnh chèn: kéo thả đổi thứ tự, mỗi cảnh chỉnh số lần xuất hiện trong một lượt mẫu và số lần phát.
- Mẫu có sẵn (preset) + lưu mẫu của riêng mình để dùng lại cho dự án khác.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

from PySide6.QtCore import QRegularExpression, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core import interleave as il
from ..core.project import ClipItem
from . import icons, theme
from . import widgets as w

COL_NAME, COL_APPEAR, COL_PLAYS = range(3)
PRESET_KEY = "interleave/presets"
USER_PREFIX = "Mẫu riêng: "  # tiền tố tên mẫu do người dùng lưu
LAST_KEY = "interleave/last"

# mẫu dựng sẵn: chỉ chứa quy tắc, không chứa tên file → dùng được cho mọi dự án
BUILTIN = [
    {"name": "Nền ×70 xen từng cảnh", "base": "70", "repeat": 1, "reshuffle": False, "order": "name",
     "plays": 1, "start": True, "end": True},
    {"name": "Nền 10 phút xen từng cảnh", "base": "10p", "repeat": 1, "reshuffle": False, "order": "name",
     "plays": 1, "start": True, "end": True},
    {"name": "Nền ×70 xen cảnh — lặp cả mẫu 4 lượt", "base": "70", "repeat": 4, "reshuffle": False,
     "order": "name", "plays": 1, "start": True, "end": True},
    {"name": "Nền 5 phút, cảnh ngẫu nhiên — lặp 6 lượt", "base": "5p", "repeat": 6, "reshuffle": True,
     "order": "shuffle", "plays": 1, "start": True, "end": True},
]

# mẫu "lần lượt từng loop" (Content → Loop1 ×60 → Loop2 ×60 …) — dùng ở Xuất hàng loạt (trang Video có hộp thoại riêng)
SEQUENCE_PRESETS = [
    {"name": "Từng loop ×60, clip nội dung ở đầu", "kind": "sequence", "base": "60", "content": "start"},
    {"name": "Từng loop ×60, clip nội dung ở cuối", "kind": "sequence", "base": "60", "content": "end"},
]


class InterleaveDialog(QDialog):
    """durations: path (normcase) → độ dài một lần phát (đã trừ phần cắt) để ước tính tổng thời lượng."""

    def __init__(self, clips: list[ClipItem], durations: dict[str, float], settings: QSettings | None = None,
                 parent=None, preset_name: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Xen kẽ clip nền")
        self.setMinimumSize(960, 640)
        self.clips = clips
        self.durations = durations
        self.settings = settings
        self.result_clips: list[ClipItem] | None = None
        self._busy = False

        # danh sách file duy nhất theo thứ tự xuất hiện
        self._unique: list[int] = []
        seen: set[str] = set()
        for i, c in enumerate(clips):
            k = os.path.normcase(c.path)
            if k not in seen:
                seen.add(k)
                self._unique.append(i)
        auto = il.detect_base(clips)

        intro = QLabel("Dựng bảng theo mẫu <b>nền → cảnh → nền → cảnh … → nền</b>, có thể <b>lặp cả mẫu</b> nhiều "
                       "lượt. Clip nền được nhận theo tên có chữ <b>loop</b> / <b>nen</b> / <b>bg</b>. "
                       "Kéo thả cảnh để đổi thứ tự; bấm đúp ô số để sửa.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")

        # ----- mẫu có sẵn -----
        self.preset = QComboBox()
        self.preset.setToolTip("Chọn một mẫu để điền nhanh mọi ô bên dưới")
        save_btn = QPushButton("Lưu mẫu…")
        save_btn.setObjectName("pill")
        save_btn.setToolTip("Lưu cách xếp hiện tại thành mẫu để dùng lại cho dự án khác")
        save_btn.clicked.connect(self._save_preset)
        self.del_btn = QPushButton("Xoá mẫu")
        self.del_btn.setObjectName("ghost")
        self.del_btn.clicked.connect(self._delete_preset)
        prow = QHBoxLayout()
        prow.setSpacing(6)
        prow.addWidget(self.preset, 1)
        prow.addWidget(save_btn)
        prow.addWidget(self.del_btn)

        # ----- clip nền -----
        self.base = QComboBox()
        for i in self._unique:
            tag = "   (tự nhận theo tên)" if i == auto else ""
            self.base.addItem(Path(clips[i].path).name + tag, i)
        if auto is not None:
            key = os.path.normcase(clips[auto].path)
            self.base.setCurrentIndex(next(k for k, i in enumerate(self._unique)
                                           if os.path.normcase(clips[i].path) == key))
        self.base_plays = QLineEdit("70")
        self.base_plays.setValidator(QRegularExpressionValidator(QRegularExpression(w.PLAYS_RE)))
        self.base_plays.setProperty("selectOnFocus", True)
        self.base_plays.setMaximumWidth(84)
        self.base_plays.setToolTip("Số lần (70), ngẫu nhiên (50-80) hoặc thời lượng (10p, 10:00, 1h)")
        brow = QHBoxLayout()
        brow.setSpacing(4)
        brow.addWidget(self.base_plays)
        for t in ("×70", "5p", "10p", "30p"):
            q = QPushButton(t)
            q.setObjectName("pill")
            q.clicked.connect(lambda _=False, v=t.lstrip("×"): self.base_plays.setText(v))
            brow.addWidget(q)
        brow.addStretch(1)

        # ----- lặp mẫu -----
        self.repeat = QSpinBox()
        self.repeat.setRange(1, 999)
        self.repeat.setSuffix(" lượt")
        self.repeat.setToolTip("Lặp lại cả dãy cảnh chèn bao nhiêu lượt (nền vẫn nằm giữa mọi cảnh)")
        self.reshuffle = QCheckBox("Mỗi lượt xáo lại thứ tự cảnh")
        rrow = QHBoxLayout()
        rrow.setSpacing(8)
        rrow.addWidget(self.repeat)
        rrow.addWidget(self.reshuffle)
        rrow.addStretch(1)
        self.start_base = QCheckBox("Mở đầu bằng nền")
        self.end_base = QCheckBox("Kết thúc bằng nền")
        self.start_base.setChecked(True)
        self.end_base.setChecked(True)
        erow = QHBoxLayout()
        erow.addWidget(self.start_base)
        erow.addWidget(self.end_base)
        erow.addStretch(1)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setVerticalSpacing(8)
        form.addRow("Mẫu có sẵn:", self._wrap(prow))
        form.addRow("Clip nền:", self.base)
        form.addRow("Số lần phát clip nền:", self._wrap(brow))
        form.addRow("Lặp lại cả chuỗi:", self._wrap(rrow))
        form.addRow("", self._wrap(erow))

        # ----- danh sách cảnh chèn -----
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Cảnh chèn (kéo để đổi thứ tự)", "Xuất hiện", "Phát"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                  | QAbstractItemView.EditTrigger.SelectedClicked
                                  | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.tree.setItemDelegateForColumn(COL_APPEAR, w.SpinDelegate(0, 99, self.tree))
        self.tree.setItemDelegateForColumn(COL_PLAYS, w.SpinDelegate(0, 9999, self.tree))
        self.tree.setItemDelegateForColumn(COL_NAME, w.NoEditDelegate(self.tree))
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_APPEAR, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_PLAYS, QHeaderView.ResizeMode.ResizeToContents)
        head = self.tree.headerItem()
        head.setToolTip(COL_APPEAR, "Cảnh này xuất hiện mấy lần trong MỘT lượt mẫu (0 = bỏ qua)")
        head.setToolTip(COL_PLAYS, "Mỗi lần xuất hiện phát mấy lần liền (1 = không loop)")
        self.tree.itemChanged.connect(lambda *_: self._update())
        self.tree.model().rowsInserted.connect(lambda *_: QTimer.singleShot(0, self._update))
        self.tree.model().rowsRemoved.connect(lambda *_: QTimer.singleShot(0, self._update))

        def tool(text, tip, fn, icon=""):
            b = QPushButton(text)
            b.setObjectName("ghost")
            b.setToolTip(tip)
            if icon:
                b.setIcon(icons.icon(icon, 14))
                b.setIconSize(QSize(14, 14))
            b.clicked.connect(fn)
            return b

        trow = QHBoxLayout()
        trow.setSpacing(4)
        trow.addWidget(tool("", "Đưa cảnh đang chọn lên trên", lambda: self._move(-1), "up"))
        trow.addWidget(tool("", "Đưa cảnh đang chọn xuống sau", lambda: self._move(1), "down"))
        trow.addWidget(tool("A–Z", "Xếp theo số / tên file (2, 3, … 10)", lambda: self._sort("name"), "sort"))
        trow.addWidget(tool("Xáo", "Xáo ngẫu nhiên thứ tự cảnh", lambda: self._sort("shuffle"), "shuffle"))
        trow.addStretch(1)
        trow.addWidget(QLabel("Đặt cho dòng chọn: phát"))
        self.bulk_plays = QSpinBox()
        self.bulk_plays.setRange(0, 9999)
        self.bulk_plays.setValue(1)
        trow.addWidget(self.bulk_plays)
        trow.addWidget(tool("Áp dụng", "Đặt số lần phát cho các cảnh đang chọn (hoặc tất cả nếu chưa chọn)",
                            self._apply_bulk_plays))

        g_ins = QGroupBox("Cảnh chèn giữa các đoạn nền")
        gl = QVBoxLayout(g_ins)
        gl.setContentsMargins(10, 8, 10, 8)
        gl.addWidget(self.tree, 1)
        gl.addLayout(trow)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(10)
        lv.addWidget(intro)
        lv.addLayout(form)
        lv.addWidget(g_ins, 1)

        # ----- xem trước -----
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.preview = QListWidget()
        self.preview.setAlternatingRowColors(True)
        g_prev = QGroupBox("Xem trước bảng clip sau khi xếp")
        pv = QVBoxLayout(g_prev)
        pv.setContentsMargins(10, 8, 10, 8)
        pv.addWidget(self.summary)
        pv.addWidget(self.preview, 1)
        note = QLabel("Các dòng trùng của cùng một file được gộp rồi dựng lại. Clip nền giữ nguyên cắt đoạn / "
                      "crossfade của nó. Cảnh bỏ tick vẫn nằm cuối bảng (tắt). Hoàn tác: Ctrl+Z.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        pv.addWidget(note)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(left)
        split.addWidget(g_prev)
        split.setSizes([560, 400])

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = bb.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setText("Áp dụng vào bảng")
        self.ok_btn.setObjectName("accentBtn")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Huỷ")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(split, 1)
        lay.addWidget(bb)

        self._fill_tree("name", 1)
        self._load_presets()
        for sig in (self.base.currentIndexChanged, self.repeat.valueChanged, self.reshuffle.toggled,
                    self.start_base.toggled, self.end_base.toggled, self.base_plays.textChanged):
            sig.connect(lambda *_: self._update())
        self.base.currentIndexChanged.connect(lambda *_: self._fill_tree("keep", None))
        self.preset.currentIndexChanged.connect(self._apply_preset)
        # mở từ hộp thoại hàng loạt: bắt đầu từ đúng mẫu đang chọn ở đó
        last = preset_name if preset_name is not None else (self.settings.value(LAST_KEY, "") if self.settings else "")
        idx = self.preset.findText(last) if last else -1
        self.preset.setCurrentIndex(idx if idx >= 0 else 0)
        self._apply_preset()

    @staticmethod
    def _wrap(layout) -> QWidget:
        box = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        box.setLayout(layout)
        return box

    # ---------- danh sách cảnh ----------
    def _specs(self) -> list[il.InsertSpec]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            out.append(il.InsertSpec(it.data(0, Qt.ItemDataRole.UserRole), _int(it.text(COL_APPEAR), 1),
                                     _int(it.text(COL_PLAYS), 1), it.checkState(0) == Qt.CheckState.Checked))
        return out

    def _fill_tree(self, order: str, plays: int | None) -> None:
        """order: name | shuffle | table | keep (giữ thứ tự + số lần đang có, chỉ đổi khi đổi clip nền)."""
        base_i = self.base.currentData()
        if base_i is None:
            return
        old = {os.path.normcase(sp.path): sp for sp in self._specs()} if self.tree.topLevelItemCount() else {}
        old_order = [os.path.normcase(sp.path) for sp in self._specs()]
        files = il.unique_inserts(self.clips, base_i, "table", include_off=True)
        if order == "name":
            files.sort(key=lambda c: il.natural_key(c.path))
        elif order == "shuffle":
            random.shuffle(files)
        elif order == "keep" and old_order:
            files.sort(key=lambda c: old_order.index(os.path.normcase(c.path))
                       if os.path.normcase(c.path) in old_order else 10 ** 6)
        self._busy = True
        self.tree.clear()
        flags = (Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                 | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsEditable)  # không nhận thả vào trong
        for c in files:
            # áp mẫu (plays có giá trị): làm lại từ đầu; còn lại giữ số lần đang chỉnh
            sp = old.get(os.path.normcase(c.path)) if plays is None else None
            n_plays = plays if plays is not None else (sp.plays if sp else 1)
            it = QTreeWidgetItem([Path(c.path).name, str(sp.appear if sp else 1), str(n_plays)])
            it.setData(0, Qt.ItemDataRole.UserRole, c.path)
            it.setFlags(flags)
            it.setCheckState(0, Qt.CheckState.Checked if (sp.enabled if sp else c.enabled) else Qt.CheckState.Unchecked)
            it.setTextAlignment(COL_APPEAR, Qt.AlignmentFlag.AlignCenter)
            it.setTextAlignment(COL_PLAYS, Qt.AlignmentFlag.AlignCenter)
            it.setToolTip(0, c.path)
            self.tree.addTopLevelItem(it)
        self._busy = False
        self._update()

    def _move(self, d: int) -> None:
        sel = sorted((self.tree.indexOfTopLevelItem(it) for it in self.tree.selectedItems()), reverse=d > 0)
        if not sel:
            return
        n = self.tree.topLevelItemCount()
        self._busy = True
        moved = []
        for i in sel:
            j = i + d
            if 0 <= j < n:
                it = self.tree.takeTopLevelItem(i)
                self.tree.insertTopLevelItem(j, it)
                moved.append(it)
            else:
                moved.append(self.tree.topLevelItem(i))
        self.tree.clearSelection()
        for it in moved:
            it.setSelected(True)
        self._busy = False
        self._update()

    def _sort(self, how: str) -> None:
        self._fill_tree(how, None)

    def _apply_bulk_plays(self) -> None:
        items = self.tree.selectedItems() or [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        self._busy = True
        for it in items:
            it.setText(COL_PLAYS, str(self.bulk_plays.value()))
        self._busy = False
        self._update()

    # ---------- mẫu ----------
    def _user_presets(self) -> list[dict]:
        if not self.settings:
            return []
        try:
            data = json.loads(self.settings.value(PRESET_KEY, "[]") or "[]")
            return [p for p in data if isinstance(p, dict) and p.get("name")]
        except (TypeError, ValueError):
            return []

    def _load_presets(self, select: str = "") -> None:
        self.preset.blockSignals(True)
        self.preset.clear()
        for p in BUILTIN:
            self.preset.addItem(p["name"], p)
        users = self._user_presets()
        if users:
            self.preset.insertSeparator(self.preset.count())
            for p in users:
                self.preset.addItem(USER_PREFIX + p["name"], dict(p, user=True))
        if select:
            idx = self.preset.findText(select)
            if idx >= 0:
                self.preset.setCurrentIndex(idx)
        self.preset.blockSignals(False)
        self._update_del_btn()

    def _update_del_btn(self) -> None:
        p = self.preset.currentData()
        self.del_btn.setEnabled(bool(p and p.get("user")))

    def _apply_preset(self, *_) -> None:
        p = self.preset.currentData()
        self._update_del_btn()
        if not p:
            return
        self._busy = True
        self.base_plays.setText(str(p.get("base", "70")))
        self.repeat.setValue(int(p.get("repeat", 1)))
        self.reshuffle.setChecked(bool(p.get("reshuffle", False)))
        self.start_base.setChecked(bool(p.get("start", True)))
        self.end_base.setChecked(bool(p.get("end", True)))
        self._busy = False
        scenes = p.get("scenes")
        if not scenes:
            self._fill_tree(p.get("order", "name"), int(p.get("plays", 1)))
            return
        # mẫu tự lưu: xếp theo thứ tự đã lưu (khớp tên file), cảnh mới chưa có trong mẫu nằm sau theo tên
        self._fill_tree("name", int(p.get("plays", 1)))
        by_name = {str(sc.get("file", "")).lower(): (k, sc) for k, sc in enumerate(scenes)}
        items = [self.tree.takeTopLevelItem(0) for _ in range(self.tree.topLevelItemCount())]
        items.sort(key=lambda it: by_name.get(it.text(0).lower(), (10 ** 6, None))[0])
        self._busy = True
        for it in items:
            sc = by_name.get(it.text(0).lower(), (0, None))[1]
            if sc:
                it.setText(COL_APPEAR, str(int(sc.get("appear", 1))))
                it.setText(COL_PLAYS, str(int(sc.get("plays", 1))))
                it.setCheckState(0, Qt.CheckState.Checked if sc.get("on", True) else Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(it)
        self._busy = False
        self._update()

    def _save_preset(self) -> None:
        if not self.settings:
            return
        cur = self.preset.currentData() or {}
        name, ok = QInputDialog.getText(self, "Lưu mẫu", "Tên mẫu (ví dụ: Nền 10 phút xen 2 cảnh ×4):",
                                        text=cur.get("name", "") if cur.get("user") else "")
        name = name.strip()
        if not ok or not name:
            return
        specs = self._specs()
        plays = specs[0].plays if specs and all(sp.plays == specs[0].plays for sp in specs) else 1
        data = {"name": name, "base": self.base_plays.text().strip() or "70", "repeat": self.repeat.value(),
                "reshuffle": self.reshuffle.isChecked(), "order": "custom", "plays": plays,
                "start": self.start_base.isChecked(), "end": self.end_base.isChecked(),
                # thứ tự + số lần từng cảnh, khớp lại theo tên file khi dùng cho dự án khác
                "scenes": [{"file": Path(sp.path).name, "appear": sp.appear, "plays": sp.plays,
                            "on": sp.enabled} for sp in specs]}
        users = [p for p in self._user_presets() if p["name"] != name] + [data]
        self.settings.setValue(PRESET_KEY, json.dumps(users, ensure_ascii=False))
        self._load_presets(USER_PREFIX + name)

    def _delete_preset(self) -> None:
        p = self.preset.currentData()
        if not (p and p.get("user") and self.settings):
            return
        if QMessageBox.question(self, "Xoá mẫu", f"Xoá mẫu “{p['name']}”?") != QMessageBox.StandardButton.Yes:
            return
        users = [u for u in self._user_presets() if u["name"] != p["name"]]
        self.settings.setValue(PRESET_KEY, json.dumps(users, ensure_ascii=False))
        self._load_presets()
        self._apply_preset()

    # ---------- dựng + xem trước ----------
    def _options(self) -> il.InterleaveOptions | None:
        parsed = w.parse_plays(self.base_plays.text())
        if parsed is None or self.base.currentData() is None:
            return None
        mode, lo, hi = parsed
        base_plays = ("duration", 1, 1, float(lo)) if mode == "duration" else (mode, int(lo), int(hi), 0.0)
        return il.InterleaveOptions(base_index=self.base.currentData(), base_plays=base_plays,
                                    start_with_base=self.start_base.isChecked(),
                                    end_with_base=self.end_base.isChecked(), inserts=self._specs(),
                                    repeat=self.repeat.value(), reshuffle=self.reshuffle.isChecked(),
                                    seed=random.randrange(1 << 30) if self.reshuffle.isChecked() else 1)

    def _seconds(self, c: ClipItem) -> float:
        d = self.durations.get(os.path.normcase(c.path), 0.0)
        if c.plays_mode == "duration":
            return c.play_seconds
        n = c.count if c.plays_mode == "fixed" else (c.min + c.max) / 2
        if n <= 0:
            return 0.0
        x = min(c.loop_xfade, d * 0.45)
        return n * d - (n - 1) * x

    def _update(self) -> None:
        if self._busy:
            return
        self.preview.clear()
        opt = self._options()
        if opt is None:
            self.summary.setText("<span style='color:#f59e0b'>Số lần phát của clip nền chưa hợp lệ.</span>")
            self.ok_btn.setEnabled(False)
            return
        out = il.build(self.clips, opt)
        self._last = (opt, out)
        base_key = os.path.normcase(self.clips[opt.base_index].path)
        n_ins = 0
        total = 0.0
        for k, c in enumerate(out):
            is_base = os.path.normcase(c.path) == base_key
            plays = (w.fmt_play_seconds(c.play_seconds) if c.plays_mode == "duration"
                     else "×" + w.plays_text(c.plays_mode, c.count, c.min, c.max))
            sec = self._seconds(c) if c.enabled else 0.0
            total += sec
            tag = "NỀN" if is_base else ("tắt" if not c.enabled else "cảnh")
            if not is_base and c.enabled:
                n_ins += 1
            it = QListWidgetItem(f"{k + 1:>3}.  [{tag}]  {Path(c.path).name}    {plays}    ≈ {w.fmt_dur(sec)}")
            it.setForeground(QColor(theme.C["mid"]) if is_base else QColor("#64748b") if not c.enabled
                             else QColor("#eef1f8"))
            self.preview.addItem(it)
        if n_ins == 0:
            self.summary.setText("<span style='color:#f59e0b'>Chưa có cảnh chèn nào được chọn — tick ít nhất "
                                 "một cảnh (và Xuất hiện ≥ 1).</span>")
        else:
            rnd = f" · {opt.repeat} lượt mẫu" if opt.repeat > 1 else ""
            self.summary.setText(f"<b>{len(out)}</b> dòng · <b>{n_ins}</b> lần chèn cảnh{rnd} · tổng ≈ "
                                 f"<b>{w.fmt_dur(total)}</b> (chưa trừ phần nối crossfade)")
        self.ok_btn.setEnabled(n_ins > 0)

    def _accept(self) -> None:
        if self._options() is None:
            return
        self.result_clips = self._last[1]  # đúng như bản xem trước (kể cả thứ tự đã xáo)
        if self.settings:
            self.settings.setValue(LAST_KEY, self.preset.currentText())
        self.accept()


def _int(text: str, default: int) -> int:
    try:
        return max(0, int(text))
    except (TypeError, ValueError):
        return default


def has_base_candidate(paths: list[str]) -> bool:
    return any(il.looks_like_base(p) for p in paths) and len(paths) >= 2


def all_presets(settings: QSettings | None) -> list[dict]:
    """Mẫu có sẵn + mẫu người dùng đã lưu (dùng chung cho hộp thoại xếp kịch bản và xuất hàng loạt)."""
    users = []
    if settings is not None:
        try:
            data = json.loads(settings.value(PRESET_KEY, "[]") or "[]")
            users = [dict(p, user=True) for p in data if isinstance(p, dict) and p.get("name")]
        except (TypeError, ValueError):
            users = []
    return [dict(p) for p in BUILTIN] + [dict(p) for p in SEQUENCE_PRESETS] + users


def arrange_from_preset(preset: dict):
    """Hàm (clips, chỉ số clip nền) → bảng clip đã xếp theo mẫu. None nếu số lần phát của nền không hợp lệ.
    Mẫu "lần lượt từng loop" (kind = sequence) không cần clip nền: hàm có thuộc tính `kind = "sequence"`."""
    parsed = w.parse_plays(str(preset.get("base", "70")))
    if parsed is None:
        return None
    mode, lo, hi = parsed
    base_plays = ("duration", 1, 1, float(lo)) if mode == "duration" else (mode, int(lo), int(hi), 0.0)
    if preset.get("kind") == "sequence":
        def arrange_seq(clips: list[ClipItem], _base_i: int = -1) -> list[ClipItem]:
            return il.build_sequence(clips, base_plays, str(preset.get("content", "start")),
                                     int(preset.get("repeat", 1)))
        arrange_seq.kind = "sequence"
        return arrange_seq
    plays = int(preset.get("plays", 1))
    scenes = {str(sc.get("file", "")).lower(): (k, sc) for k, sc in enumerate(preset.get("scenes") or [])}

    def arrange(clips: list[ClipItem], base_i: int) -> list[ClipItem]:
        files = il.unique_inserts(clips, base_i, "shuffle" if preset.get("order") == "shuffle" else "name",
                                  random.randrange(1 << 30))
        if scenes:  # mẫu tự lưu: thứ tự + số lần theo tên file, cảnh mới xếp sau
            files.sort(key=lambda c: scenes.get(Path(c.path).name.lower(), (10 ** 6, None))[0])
        specs = []
        for c in files:
            sc = scenes.get(Path(c.path).name.lower(), (0, None))[1]
            specs.append(il.InsertSpec(c.path, int(sc.get("appear", 1)) if sc else 1,
                                       int(sc.get("plays", plays)) if sc else plays,
                                       bool(sc.get("on", True)) if sc else True))
        opt = il.InterleaveOptions(base_index=base_i, base_plays=base_plays, inserts=specs,
                                   start_with_base=bool(preset.get("start", True)),
                                   end_with_base=bool(preset.get("end", True)),
                                   repeat=int(preset.get("repeat", 1)), reshuffle=bool(preset.get("reshuffle", False)),
                                   seed=random.randrange(1 << 30))
        return il.build(clips, opt)

    return arrange
