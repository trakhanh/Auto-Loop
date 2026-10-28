"""Thư viện mẫu xếp clip: mọi mẫu (dựng sẵn + của người dùng) kèm ví dụ kết quả, và trình tạo / sửa mẫu bảng clip.

Ví dụ kết quả được TÍNH THẬT: áp mẫu lên bộ tên file mẫu (loop_nen + 2_canh…, Content + Loop1…, 5_loopA / 5_loopB…)
bằng đúng hàm xếp của app, nên dải màu khớp với bảng sẽ tạo.
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QRectF, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QTableWidget, QVBoxLayout, QWidget,
)

from ..core import interleave as il
from ..core import table_preset as tp
from ..core.project import ClipItem
from . import icons, theme
from . import widgets as w
from .interleave_dialog import (
    BUILTIN, SEQUENCE_PRESETS, USER_PREFIX, all_presets, arrange_from_preset, save_table_presets, table_presets,
)

EXAMPLE_SEC = 10.0  # mỗi clip ví dụ dài 10 giây
MAX_BLOCKS = 9  # dải ví dụ: tối đa 9 khối, phần còn lại gộp "… +N"
KIND_TEXT = {"interleave": "Xen kẽ clip nền", "sequence": "Xếp lần lượt", "table": "Mẫu bảng clip"}
KIND_ICON = {"interleave": "repeat", "sequence": "sort", "table": "save"}
KIND_FILES = {
    "interleave": "Cần: 1 clip nền tên có chữ <b>loop</b> (loop_mua.mp4) + các cảnh đánh số <b>2_…, 3_…</b>",
    "sequence": "Cần: clip nội dung (<b>Content.mp4</b>) + các clip <b>Loop1, Loop2, Loop3…</b>",
    "table": "Cần: file đặt tên theo vai — {roles}",
}


def kind_of(p: dict) -> str:
    return p.get("kind") if p.get("kind") in ("sequence", "table") else "interleave"


def describe(p: dict) -> str:
    k = kind_of(p)
    if k == "sequence":
        pos = {"start": "ở đầu", "end": "ở cuối", "both": "ở đầu và cuối"}.get(p.get("content", "start"), "ở đầu")
        return f"Phát lần lượt từng clip loop, mỗi cái <b>×{p.get('base', '60')}</b>; clip nội dung {pos}."
    if k == "table":
        return "Bảng tự lưu theo tên file, giữ nguyên số lần phát / nối loop / cắt đoạn của từng dòng."
    base = str(p.get("base", "70"))
    base_t = f"lặp đủ {base[:-1]} phút" if base.endswith("p") else f"×{base}"
    extra = (f", lặp cả mẫu <b>{p.get('repeat')} lượt</b>" if int(p.get("repeat", 1)) > 1 else "") + \
        (", mỗi lượt <b>xáo thứ tự cảnh</b>" if p.get("reshuffle") or p.get("order") == "shuffle" else "")
    return f"1 clip nền <b>{base_t}</b> nằm giữa mọi cảnh{extra}."


def example(p: dict) -> tuple[list[tuple[str, str, int, float]], float, str]:
    """(khối [(tên, số lần, nhóm màu, giây)], tổng giây, dòng file ví dụ) — áp mẫu thật lên bộ tên file ví dụ."""
    k = kind_of(p)
    if k == "table":
        rows = p.get("rows") or []
        names = [f"5_{(r.get('label') or r.get('role', '')).removeprefix('STT_')}.mp4" for r in rows]
        clips = tp.build(rows, list(dict.fromkeys(names)))[0]
        files = ", ".join(dict.fromkeys(os.path.basename(c.path) for c in clips))
    else:
        names = (["Content.mp4", "Loop1.mp4", "Loop2.mp4", "Loop3.mp4"] if k == "sequence"
                 else ["loop_nen.mp4", "2_canh.mp4", "3_canh.mp4", "4_canh.mp4"])
        arrange = arrange_from_preset(p)
        clips = arrange([ClipItem(n) for n in names], 0) if arrange else []
        files = ", ".join(names)
    roles: list[str] = []
    blocks = []
    total = 0.0
    for c in clips:
        if not c.enabled:
            continue
        stem = os.path.splitext(os.path.basename(c.path))[0]
        name = ("Nền" if k == "interleave" and il.looks_like_base(c.path)
                else re.sub(r"^(\d+)_canh$", r"Cảnh \1", stem))
        if c.plays_mode == "duration":
            sec, plays = c.play_seconds, (f"{c.play_seconds / 60:g} phút" if c.play_seconds >= 60
                                          else f"{c.play_seconds:g} giây")
        elif c.plays_mode == "random":
            sec, plays = EXAMPLE_SEC * (c.min + c.max) / 2, f"×{c.min}–{c.max}"
        else:
            sec, plays = EXAMPLE_SEC * c.count, f"×{c.count}"
        role = tp.role_of(c.path)
        if role not in roles:
            roles.append(role)
        blocks.append((name, plays, roles.index(role), sec))
        total += sec
    return blocks, total, files


class FlowStrip(QWidget):
    """Dải khối màu: thứ tự phát của ví dụ (rộng theo thời lượng, có chặn dưới để chữ đọc được)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.blocks: list[tuple[str, str, int, float]] = []
        self.setMinimumHeight(46)
        self.setMaximumHeight(46)

    def set_blocks(self, blocks) -> None:
        self.blocks = list(blocks)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shown = self.blocks[:MAX_BLOCKS]
        more = len(self.blocks) - len(shown)
        if not shown:
            p.setPen(theme.qcolor("text_muted"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter, "Không xếp được với bộ file ví dụ")
            return
        gap, W, H = 4.0, float(self.width()), float(self.height())
        more_w = 54.0 if more > 0 else 0.0
        weights = [max(1.0, b[3]) ** 0.5 for b in shown]
        avail = W - more_w - gap * (len(shown) - (0 if more else 1))
        min_w = min(70.0, avail / len(shown))
        scale = (avail - min_w * len(shown)) / sum(weights)
        colors = [QColor(c) for c in theme.FLOW_COLORS] + [theme.qcolor("info"), theme.qcolor("success"),
                                                           theme.qcolor("warn")]
        fm = QFontMetrics(self.font())
        bold = self.font()
        bold.setBold(True)
        fmb = QFontMetrics(bold)
        x = 0.0
        for (name, plays, group, _sec), wt in zip(shown, weights):
            bw = min_w + wt * scale
            r = QRectF(x, 0, bw, H)
            path = QPainterPath()
            path.addRoundedRect(r, 6, 6)
            p.fillPath(path, colors[group % len(colors)])
            p.setPen(theme.qcolor("text"))
            inner = r.adjusted(6, 4, -6, -4)
            p.setFont(bold)
            p.drawText(inner, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       fmb.elidedText(name, Qt.TextElideMode.ElideRight, int(inner.width())))
            p.setFont(self.font())
            p.drawText(inner, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       fm.elidedText(plays, Qt.TextElideMode.ElideRight, int(inner.width())))
            x += bw + gap
        if more > 0:
            r = QRectF(x, 0, W - x, H)
            path = QPainterPath()
            path.addRoundedRect(r, 6, 6)
            p.fillPath(path, theme.qcolor("raised"))
            p.setPen(theme.qcolor("text_2"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, f"… +{more}")


def _fmt(sec: float) -> str:
    s = int(round(sec))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class PresetCard(QFrame):
    def __init__(self, p: dict, on_use, on_edit=None, on_delete=None, parent=None):
        super().__init__(parent)
        self.setObjectName("presetCard")
        k = kind_of(p)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP['lg'], theme.SP['md'], theme.SP['lg'], theme.SP['md'])
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(theme.SP['md'])
        ic = QLabel()
        icons.bind(ic, KIND_ICON[k], 16, "accent_text")
        ic.setFixedSize(16, 16)
        name = QLabel(p["name"])
        name.setObjectName("presetName")
        chip = QLabel(KIND_TEXT[k] + (" · của bạn" if p.get("user") else " · có sẵn"))
        chip.setObjectName("chip")
        head.addWidget(ic)
        head.addWidget(name)
        head.addWidget(chip)
        head.addStretch(1)
        if on_edit:
            b = QPushButton("Sửa")
            theme.tag(b, variant="ghost")
            b.clicked.connect(lambda: on_edit(p))
            head.addWidget(b)
        if on_delete:
            b = QPushButton()
            b.setIcon(icons.icon("trash", 14))
            b.setIconSize(QSize(14, 14))
            b.setFixedWidth(34)
            b.setToolTip("Xoá mẫu này")
            theme.tag(b, variant="danger")
            b.clicked.connect(lambda: on_delete(p))
            head.addWidget(b)
        use = QPushButton("Dùng mẫu này")
        theme.tag(use, variant="tonal")
        use.clicked.connect(lambda: on_use(p))
        head.addWidget(use)
        lay.addLayout(head)
        desc = w.muted(describe(p))
        desc.setWordWrap(True)
        lay.addWidget(desc)
        blocks, total, files = example(p)
        strip = FlowStrip()
        strip.set_blocks(blocks)
        lay.addWidget(strip)
        roles = ", ".join(dict.fromkeys(f"<b>{(r.get('label') or r.get('role'))}</b>" for r in p.get("rows") or []))
        foot = w.muted(f"Ví dụ ({files}, mỗi clip {EXAMPLE_SEC:g} giây) → video dài <b>{_fmt(total)}</b>, "
                       f"{len(blocks)} dòng. " + KIND_FILES[k].format(roles=roles))
        foot.setWordWrap(True)
        lay.addWidget(foot)


class PresetLibraryDialog(QDialog):
    """Mọi mẫu xếp clip. Bấm "Dùng mẫu này" → `choice` = mẫu đã chọn (trang Video mở đúng hộp thoại để áp)."""

    def __init__(self, clips: list[ClipItem], settings: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thư viện mẫu xếp clip")
        self.setMinimumSize(860, 640)
        self.clips = clips
        self.settings = settings
        self.choice: dict | None = None

        title = QLabel("Thư viện mẫu xếp clip")
        title.setObjectName("updateTitle")
        self.count = w.muted("")
        new_btn = QPushButton("Tạo mẫu mới…")
        theme.tag(new_btn, variant="primary")
        new_btn.setIcon(icons.icon("plus", 14, "text_on_accent"))
        new_btn.setToolTip("Tự đặt từng dòng: vai (tên file sau số thứ tự) + số lần phát + nối loop")
        new_btn.clicked.connect(lambda: self._edit(None))
        from_table = QPushButton("Lưu bảng hiện tại thành mẫu…")
        from_table.setIcon(icons.icon("save", 14))
        from_table.setIconSize(QSize(14, 14))
        from_table.setEnabled(bool(clips))
        from_table.clicked.connect(self._from_table)
        top = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(2)
        tv.addWidget(title)
        tv.addWidget(self.count)
        top.addLayout(tv, 1)
        top.addWidget(from_table)
        top.addWidget(new_btn)

        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 6, 0)
        self.body_lay.setSpacing(theme.SP['md'])
        scroll = QScrollArea()
        scroll.setWidget(self.body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        close = QPushButton("Đóng")
        close.clicked.connect(self.reject)
        bb = QHBoxLayout()
        bb.addWidget(w.muted("Mẫu của bạn cũng có ở <b>Xuất hàng loạt</b> → ô <i>Cách xếp clip</i>."), 1)
        bb.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SP['md'])
        lay.addLayout(top)
        lay.addWidget(scroll, 1)
        lay.addLayout(bb)
        self._fill()

    def _fill(self) -> None:
        while self.body_lay.count():
            it = self.body_lay.takeAt(0)
            wd = it.widget()
            if wd is not None:  # ẩn ngay: deleteLater chỉ xoá khi về vòng lặp sự kiện → chữ cũ còn đè lên một lúc
                wd.hide()
                wd.deleteLater()
        everything = all_presets(self.settings)
        users_il = [p for p in everything if p.get("user") and kind_of(p) == "interleave"]
        users_tb = [p for p in everything if kind_of(p) == "table"]
        n_builtin = len(BUILTIN) + len(SEQUENCE_PRESETS)
        n_user = len(users_il) + len(users_tb)
        self.count.setText(f"App có <b>{n_builtin} mẫu dựng sẵn</b> · bạn đã tạo <b>{n_user} mẫu</b>. "
                           "Dải màu là ví dụ kết quả thật khi áp mẫu.")
        sections = [
            ("Mẫu của bạn — bảng clip", users_tb, True, True),
            ("Mẫu của bạn — xen kẽ clip nền", users_il, False, True),
            ("Xen kẽ clip nền (có sẵn)", [dict(p) for p in BUILTIN], False, False),
            ("Xếp lần lượt từng loop (có sẵn)", [dict(p) for p in SEQUENCE_PRESETS], False, False),
        ]
        for title, items, editable, deletable in sections:
            if not items and not editable:
                continue
            h = QLabel(f"{title} ({len(items)})")
            h.setObjectName("h2")
            self.body_lay.addWidget(h)
            if not items:
                self.body_lay.addWidget(w.muted("Chưa có — bấm <b>Tạo mẫu mới…</b> hoặc <b>Lưu bảng hiện tại thành "
                                                "mẫu…</b> ở trên."))
            for p in items:
                self.body_lay.addWidget(PresetCard(p, self._use, self._edit if editable else None,
                                                   self._delete if deletable else None))
        self.body_lay.addStretch(1)

    def _use(self, p: dict) -> None:
        self.choice = p
        self.accept()

    def _from_table(self) -> None:
        dlg = PresetEditor(self.settings, {"name": "", "rows": tp.from_clips(self.clips)}, self)
        if dlg.exec():
            self._fill()

    def _edit(self, p: dict | None) -> None:
        dlg = PresetEditor(self.settings, p, self)
        if dlg.exec():
            self._fill()

    def _delete(self, p: dict) -> None:
        if QMessageBox.question(self, "Xoá mẫu", f"Xoá mẫu “{p['name']}”?") != QMessageBox.StandardButton.Yes:
            return
        if kind_of(p) == "table":
            save_table_presets(self.settings, [x for x in table_presets(self.settings) if x["name"] != p["name"]])
        else:
            import json
            from .interleave_dialog import PRESET_KEY
            try:
                data = json.loads(self.settings.value(PRESET_KEY, "[]") or "[]")
            except (TypeError, ValueError):
                data = []
            self.settings.setValue(PRESET_KEY, json.dumps([x for x in data if x.get("name") != p["name"]],
                                                          ensure_ascii=False))
        self._fill()


C_ROLE, C_PLAYS, C_LOOP, C_NEXT, C_ACT = range(5)


class PresetEditor(QDialog):
    """Tạo / sửa mẫu bảng clip: mỗi dòng = vai (tên file sau số thứ tự) + số lần phát + nối loop + sang clip."""

    def __init__(self, settings: QSettings, preset: dict | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.orig_name = (preset or {}).get("name", "")
        self.setWindowTitle("Sửa mẫu bảng clip" if self.orig_name else "Tạo mẫu bảng clip")
        self.setMinimumSize(760, 560)
        self._rows: list[dict] = [dict(r) for r in (preset or {}).get("rows") or []] or [
            {"role": "loopb", "label": "STT_loopB", "count": 1}, {"role": "loopa", "label": "STT_loopA", "count": 57}]

        self.name = QLineEdit(self.orig_name)
        self.name.setPlaceholderText("Tên mẫu, ví dụ: Loop A ×57 kẹp Loop B")
        guide = w.muted("Mỗi dòng là một lần xuất hiện trong video. <b>Vai</b> = phần tên file sau số thứ tự: gõ "
                        "<b>loopA</b> thì app dùng <b>5_loopA.mp4</b>, <b>6_loopA.mp4</b>… <b>Số lần phát</b>: "
                        "<b>57</b> = 57 lần · <b>10p</b> = loop đủ 10 phút · <b>50-80</b> = ngẫu nhiên.")
        guide.setWordWrap(True)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Vai (tên file sau STT_)", "Số lần phát", "Nối loop", "Sang clip", ""])
        self.table.verticalHeader().setVisible(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(C_ROLE, QHeaderView.ResizeMode.Stretch)
        for c in (C_PLAYS, C_LOOP, C_NEXT, C_ACT):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        add = QPushButton("Thêm dòng")
        add.setIcon(icons.icon("plus", 14))
        add.setIconSize(QSize(14, 14))
        add.clicked.connect(lambda: self._add({"role": "loopa", "label": "STT_loopA", "count": 1}))
        self.strip = FlowStrip()
        self.preview = w.muted("")
        self.preview.setWordWrap(True)
        self.err = w.muted("")
        theme.tag(self.err, tone="danger")
        save = QPushButton("Lưu mẫu")
        theme.tag(save, variant="primary")
        save.clicked.connect(self._save)
        cancel = QPushButton("Huỷ")
        cancel.clicked.connect(self.reject)
        bb = QHBoxLayout()
        bb.addWidget(self.err, 1)
        bb.addWidget(cancel)
        bb.addWidget(save)
        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SP['md'])
        lay.addWidget(self.name)
        lay.addWidget(guide)
        lay.addWidget(self.table, 1)
        arow = QHBoxLayout()
        arow.addWidget(add)
        arow.addStretch(1)
        lay.addLayout(arow)
        lay.addWidget(QLabel("Ví dụ kết quả (thư mục video 5, mỗi clip 10 giây):"))
        lay.addWidget(self.strip)
        lay.addWidget(self.preview)
        lay.addLayout(bb)
        for r in self._rows:
            self._add(r, refresh=False)
        self._refresh()

    # ---------- bảng ----------
    def _add(self, r: dict, refresh: bool = True) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        role = QLineEdit((r.get("label") or r.get("role", "")).removeprefix("STT_"))
        role.setPlaceholderText("loopA")
        role.textChanged.connect(self._refresh)
        plays = QLineEdit(tp.plays_text(r).lstrip("×").replace("–", "-").replace(" phút", "p").replace(" giây", "s"))
        plays.setMaximumWidth(110)
        plays.setToolTip(w.PLAYS_HELP)
        plays.textChanged.connect(self._refresh)
        loop, nxt = w.xf_spin(), w.xf_spin()
        loop.setValue(float(r.get("loop_xfade", 0)))
        nxt.setValue(float(r.get("next_xfade", 0)))
        for sb in (loop, nxt):
            sb.valueChanged.connect(self._refresh)
        acts = QWidget()
        al = QHBoxLayout(acts)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(2)
        for ic, tip, fn in (("up", "Lên", lambda: self._move(acts, -1)), ("down", "Xuống", lambda: self._move(acts, 1)),
                            ("trash", "Xoá dòng", lambda: self._remove(acts))):
            b = QPushButton()
            b.setIcon(icons.icon(ic, 13))
            b.setIconSize(QSize(13, 13))
            b.setFixedWidth(30)
            b.setToolTip(tip)
            theme.tag(b, variant="ghost")
            b.clicked.connect(fn)
            al.addWidget(b)
        for c, wd in ((C_ROLE, role), (C_PLAYS, plays), (C_LOOP, loop), (C_NEXT, nxt), (C_ACT, acts)):
            self.table.setCellWidget(row, c, wd)
        self.table.setRowHeight(row, 40)
        acts.setProperty("extra", {k: v for k, v in r.items()
                                   if k not in ("role", "label", "count", "min", "max", "plays_mode", "play_seconds",
                                                "loop_xfade", "next_xfade")})
        if refresh:
            self._refresh()

    def _row_of(self, wd: QWidget) -> int:
        return next((i for i in range(self.table.rowCount()) if self.table.cellWidget(i, C_ACT) is wd), -1)

    def _read(self) -> tuple[list[dict], str]:
        rows, err = [], ""
        for i in range(self.table.rowCount()):
            role_t = re.sub(r"^\s*(stt[_\-\s]*|\d+\s*[_\-.\s]+)", "", self.table.cellWidget(i, C_ROLE).text(),
                            flags=re.IGNORECASE).strip()
            plays_t = self.table.cellWidget(i, C_PLAYS).text().strip()
            if not role_t:
                err = err or f"Dòng {i + 1}: chưa gõ vai (ví dụ loopA)."
                continue
            parsed = w.parse_plays(plays_t)
            if parsed is None:
                err = err or f"Dòng {i + 1}: số lần phát “{plays_t}” chưa đúng (vd 57, 10p, 50-80)."
                continue
            mode, lo, hi = parsed
            r = dict(self.table.cellWidget(i, C_ACT).property("extra") or {})
            r.update({"role": role_t.lower(), "label": "STT_" + role_t, "plays_mode": mode,
                      "count": int(lo) if mode == "fixed" else 1, "min": int(lo) if mode == "random" else 1,
                      "max": int(hi) if mode == "random" else 1, "play_seconds": float(lo) if mode == "duration" else 0.0,
                      "loop_xfade": self.table.cellWidget(i, C_LOOP).value(),
                      "next_xfade": self.table.cellWidget(i, C_NEXT).value()})
            r.setdefault("enabled", True)
            rows.append(r)
        if not rows and not err:
            err = "Mẫu cần ít nhất 1 dòng."
        return rows, err

    def _refresh(self, *_) -> None:
        rows, err = self._read()
        blocks, total, files = example({"kind": "table", "rows": rows})
        self.strip.set_blocks(blocks)
        self.preview.setText(f"File ví dụ: {files or '—'} → video dài <b>{_fmt(total)}</b>, {len(blocks)} dòng. "
                             "Thư mục có 1_… đến 10_… thì mẫu lặp cho từng số, nối thành một video."
                             if rows else "")
        self.err.setText(err)

    def _move(self, acts: QWidget, d: int) -> None:
        i = self._row_of(acts)
        j = i + d
        if i < 0 or not 0 <= j < self.table.rowCount():
            return
        rows, _ = self._read_raw()
        rows[i], rows[j] = rows[j], rows[i]
        self._reload(rows)

    def _remove(self, acts: QWidget) -> None:
        i = self._row_of(acts)
        if i < 0:
            return
        rows, _ = self._read_raw()
        del rows[i]
        self._reload(rows)

    def _read_raw(self) -> tuple[list[dict], None]:
        """Đọc mọi dòng kể cả dòng chưa hợp lệ (để đổi thứ tự / xoá không làm mất chữ đang gõ)."""
        out = []
        for i in range(self.table.rowCount()):
            r = dict(self.table.cellWidget(i, C_ACT).property("extra") or {})
            r["label"] = "STT_" + self.table.cellWidget(i, C_ROLE).text().strip().removeprefix("STT_")
            r["_plays"] = self.table.cellWidget(i, C_PLAYS).text()
            r["loop_xfade"] = self.table.cellWidget(i, C_LOOP).value()
            r["next_xfade"] = self.table.cellWidget(i, C_NEXT).value()
            out.append(r)
        return out, None

    def _reload(self, rows: list[dict]) -> None:
        self.table.setRowCount(0)
        for r in rows:
            plays = r.pop("_plays", None)
            self._add(r, refresh=False)
            if plays is not None:
                self.table.cellWidget(self.table.rowCount() - 1, C_PLAYS).setText(plays)
        self._refresh()

    def _save(self) -> None:
        name = self.name.text().strip()
        rows, err = self._read()
        if not name:
            err = "Đặt tên cho mẫu."
        if err:
            self.err.setText(err)
            return
        presets = table_presets(self.settings)
        if name != self.orig_name and any(p["name"] == name for p in presets):
            if QMessageBox.question(self, "Lưu mẫu", f"Đã có mẫu “{name}”. Ghi đè?") != QMessageBox.StandardButton.Yes:
                return
        presets = [p for p in presets if p["name"] not in (name, self.orig_name)]
        presets.append({"name": name, "rows": rows})
        save_table_presets(self.settings, presets)
        self.accept()


def interleave_key(p: dict) -> str:
    """Tên mẫu xen kẽ như hộp thoại Xen kẽ hiển thị (mẫu riêng có tiền tố)."""
    return (USER_PREFIX if p.get("user") else "") + p["name"]
