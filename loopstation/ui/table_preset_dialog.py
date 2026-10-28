"""Hộp thoại "Mẫu bảng clip": lưu bảng hiện tại thành mẫu theo tên file (STT_loopB ×1 → STT_loopA ×57 → …)
rồi áp mẫu cho bộ clip khác (6_loopA, 6_loopB…) — ở trang Video hoặc Xuất hàng loạt."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMessageBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ..core import table_preset as tp
from ..core.project import ClipItem
from . import icons, theme
from . import widgets as w
from .interleave_dialog import all_table_presets, save_table_presets, table_presets

C_NO, C_ROLE, C_PLAYS, C_LOOP, C_NEXT, C_TRIM, C_FILE = range(7)
LAST_KEY = "table/last"  # mẫu dùng lần trước: mở hộp thoại là chọn sẵn
EMPTY_GUIDE = (
    "<b>Chưa có mẫu nào — tạo mẫu trong 3 bước:</b>"
    "<ol style='margin-top:4px'>"
    "<li><b>Xếp bảng clip của 1 video cho đúng ý</b> ở trang Video — ví dụ 5_loopB ×1 → 5_loopA ×57 → 5_loopB ×1 "
    "→ 5_loopA ×1 (số lần phát, nối loop, cắt đoạn…).</li>"
    "<li>Mở <b>Thư viện mẫu…</b> → bấm <b>Lưu bảng hiện tại thành mẫu…</b> → đặt tên, ví dụ <i>Loop A ×57 kẹp Loop B</i>.</li>"
    "<li><b>Lần sau</b>: thêm file của video khác (6_loopA, 6_loopB…) vào bảng, hoặc bấm <b>Lấy file từ thư mục khác…</b> "
    "→ chọn mẫu → <b>Áp dụng vào bảng</b>. Thư mục có 1_… đến 10_… thì 10 tình huống nối thành một video.</li>"
    "</ol>")


class TablePresetDialog(QDialog):
    """`clips`: bảng hiện tại (để lưu thành mẫu và làm nguồn file khi áp). Bấm Áp dụng → `result_clips`."""

    def __init__(self, clips: list[ClipItem], settings: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mẫu bảng clip")
        self.setMinimumSize(760, 520)
        self.clips = clips
        self.settings = settings
        self.result_clips: list[ClipItem] | None = None
        self.paths = list(dict.fromkeys(c.path for c in clips))  # nguồn file khi áp mẫu (mặc định: file trong bảng)
        self.source_dir = ""

        intro = w.muted("Lưu cả bảng clip (thứ tự, số lần phát, nối loop, cắt đoạn) thành <b>mẫu</b>. Mẫu nhớ "
                        "file theo <b>tên bỏ số thứ tự ở đầu</b>: <b>5_loopB.mp4</b> → <b>STT_loopB</b>, nên áp được "
                        "cho video khác (<b>6_loopA</b>, <b>6_loopB</b>…) và cho từng thư mục ở Xuất hàng loạt.")
        intro.setWordWrap(True)

        self.preset = QComboBox()
        self.preset.setMinimumContentsLength(24)
        self.save_btn = QPushButton("Lưu bảng hiện tại thành mẫu…")
        self.save_btn.setIcon(icons.icon("save", 14))
        self.save_btn.setIconSize(QSize(14, 14))
        self.save_btn.setEnabled(bool(clips))
        self.save_btn.clicked.connect(self._save)
        self.del_btn = QPushButton()
        self.del_btn.setIcon(icons.icon("trash", 14))
        self.del_btn.setIconSize(QSize(14, 14))
        self.del_btn.setFixedWidth(36)
        self.del_btn.setToolTip("Xoá mẫu đang chọn")
        theme.tag(self.del_btn, variant="danger")
        self.del_btn.clicked.connect(self._delete)
        top = QHBoxLayout()
        top.addWidget(QLabel("Mẫu:"))
        top.addWidget(self.preset, 1)
        top.addWidget(self.del_btn)
        top.addWidget(self.save_btn)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["#", "Vai (tên file)", "Số lần phát", "Nối loop", "Sang clip", "Cắt đoạn",
                                   "Sẽ dùng file"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.empty = QLabel(EMPTY_GUIDE)  # chưa có mẫu: hướng dẫn tạo mẫu thay cho bảng trống
        self.empty.setObjectName("info")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        hdr = self.tree.header()
        hdr.setStretchLastSection(True)
        for c in (C_NO, C_ROLE, C_PLAYS, C_LOOP, C_NEXT, C_TRIM):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        self.src_label = w.muted("")
        self.src_label.setWordWrap(True)
        pick = QPushButton("Lấy file từ thư mục khác…")
        pick.setIcon(icons.icon("folder", 14))
        pick.setIconSize(QSize(14, 14))
        pick.setToolTip("Ví dụ thư mục video 6 có 6_loopA.mp4, 6_loopB.mp4 — mẫu tự khớp theo tên")
        pick.clicked.connect(self._pick_folder)
        src_row = QHBoxLayout()
        src_row.addWidget(self.src_label, 1)
        src_row.addWidget(pick)

        self.note = w.muted("")
        self.note.setWordWrap(True)
        self.apply_btn = QPushButton("Áp dụng vào bảng")
        theme.tag(self.apply_btn, variant="primary")
        self.apply_btn.clicked.connect(self._apply)
        cancel = QPushButton("Đóng")
        cancel.clicked.connect(self.reject)
        bb = QHBoxLayout()
        bb.addWidget(self.note, 1)
        bb.addWidget(cancel)
        bb.addWidget(self.apply_btn)

        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SP['md'])
        lay.addWidget(intro)
        lay.addLayout(top)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.empty, 1)
        lay.addLayout(src_row)
        lay.addLayout(bb)

        self.preset.currentIndexChanged.connect(self._show)
        self._load()

    # ---------- dữ liệu ----------
    def _presets(self) -> list[dict]:
        return all_table_presets(self.settings)

    def _load(self, select: str = "") -> None:
        self.preset.blockSignals(True)
        self.preset.clear()
        for p in self._presets():
            self.preset.addItem(p["name"], p)
        if self.preset.count() == 0:
            self.preset.addItem("(chưa có mẫu — bấm “Lưu bảng hiện tại thành mẫu…”)", None)
        select = select or str(self.settings.value(LAST_KEY, "") or "")
        i = self.preset.findText(select) if select else -1
        self.preset.setCurrentIndex(max(0, i))
        self.preset.blockSignals(False)
        self._show()

    def _show(self, *_) -> None:
        p = self.preset.currentData()
        self.del_btn.setEnabled(bool(p and p.get("user")))  # mẫu có sẵn không xoá được
        self.del_btn.setToolTip("Xoá mẫu đang chọn" if p is None or p.get("user") else "Mẫu có sẵn — không xoá được")
        self.tree.setVisible(p is not None)
        self.empty.setVisible(p is None)
        self.tree.clear()
        n_files = len(self.paths)
        where = (f"thư mục <b>{os.path.basename(self.source_dir) or self.source_dir}</b>" if self.source_dir
                 else "bảng clip hiện tại")
        self.src_label.setText(f"Lấy file từ {where} ({n_files} file).")
        if p is None:
            self.apply_btn.setEnabled(False)
            self.note.setText("")
            return
        rows = p["rows"]
        # nhiều số thứ tự (1_loopA … 10_loopB): mẫu lặp cho từng số, nối tiếp thành MỘT video — hiện đúng bảng sẽ tạo
        items, missing, used = tp.plan(rows, self.paths)
        many = len(used) > 1
        last_g = object()
        for k, (r, path, g) in enumerate(items, 1):
            trim = ("Toàn bộ" if not (r.get("trim_start") or r.get("trim_end"))
                    else f"bỏ {r.get('trim_start', 0):g}s đầu, {r.get('trim_end', 0):g}s cuối")
            it = QTreeWidgetItem([str(k), r.get("label") or r.get("role", ""), tp.plays_text(r),
                                  w.xf_text(float(r.get("loop_xfade", 0))), w.xf_text(float(r.get("next_xfade", 0))),
                                  trim, os.path.basename(path)])
            it.setForeground(C_FILE, theme.qcolor("text_muted"))
            if many and g != last_g:  # dòng đầu của mỗi tình huống: tô đậm số thứ tự
                it.setForeground(C_FILE, theme.qcolor("accent_text"))
                it.setToolTip(C_FILE, f"Tình huống {g}")
            last_g = g
            if not r.get("enabled", True):
                for c in range(7):
                    it.setForeground(c, theme.qcolor("text_disabled"))
            self.tree.addTopLevelItem(it)
        self.apply_btn.setEnabled(bool(items))
        head = (f"{len(used)} tình huống (STT {used[0]} → {used[-1]}) nối tiếp thành <b>1 video</b>: "
                if many else "")
        if missing:
            labels = {r.get("role"): r.get("label") or r.get("role") for r in rows}

            def name(m: str) -> str:  # "7_loopb" → "7_loopB", "loopb" → "STT_loopB"
                num, _, role = m.partition("_")
                if many and num.isdigit() and role in labels:
                    return f"{num}_{labels[role].removeprefix('STT_')}"
                return labels.get(m, m)
            names = ", ".join(name(m) for m in missing)
            self.note.setText(f"{head}<span style='color:{theme.css_color('warn_text')}'>Thiếu file: {names} — "
                              "dòng đó bị bỏ.</span>")
        else:
            self.note.setText(f"{head}bảng {len(items)} dòng.")

    def _pick_folder(self) -> None:
        start = self.source_dir or (os.path.dirname(self.paths[0]) if self.paths else "")
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục có các file STT_loopA, STT_loopB…", start)
        if not d:
            return
        files = tp.media_in(d)
        if not files:
            QMessageBox.information(self, "Mẫu bảng clip", "Thư mục này không có file video / ảnh nào.")
            return
        self.source_dir, self.paths = d, files
        self._show()

    def _save(self) -> None:
        name, ok = QInputDialog.getText(self, "Lưu mẫu bảng clip", "Tên mẫu (ví dụ: Loop A ×57 kẹp Loop B):")
        name = name.strip()
        if not ok or not name:
            return
        presets = table_presets(self.settings)
        if any(p["name"] == name for p in presets):
            if QMessageBox.question(self, "Lưu mẫu", f"Đã có mẫu “{name}”. Ghi đè?") != QMessageBox.StandardButton.Yes:
                return
            presets = [p for p in presets if p["name"] != name]
        presets.append({"name": name, "rows": tp.from_clips(self.clips)})
        save_table_presets(self.settings, presets)
        self.settings.setValue(LAST_KEY, name)
        self._load(name)

    def _delete(self) -> None:
        p = self.preset.currentData()
        if p is None or QMessageBox.question(self, "Xoá mẫu", f"Xoá mẫu “{p['name']}”?") \
                != QMessageBox.StandardButton.Yes:
            return
        save_table_presets(self.settings, [x for x in table_presets(self.settings) if x["name"] != p["name"]])
        self._load()

    def _apply(self) -> None:
        p = self.preset.currentData()
        if p is None:
            return
        clips, _missing = tp.build(p["rows"], self.paths)
        if not clips:
            return
        self.result_clips = clips
        self.settings.setValue(LAST_KEY, p["name"])
        self.accept()

