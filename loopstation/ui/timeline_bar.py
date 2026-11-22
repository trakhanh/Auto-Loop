"""Thanh dòng thời gian trực quan: hiển thị cấu trúc các khối Hình, Âm thanh (nhạc / tiếng gốc) và Tiếng nền.

- Cùng một file luôn cùng một màu (clip nền xuất hiện nhiều lần dễ nhận ra).
- Clip rất ngắn so với tổng thời lượng (ví dụ cảnh 10 giây giữa các đoạn loop 10 phút) vẫn được vẽ thành
  vạch có nhãn số, không bị mất.
- Như Premiere: Ctrl + lăn để phóng to / thu nhỏ quanh con trỏ; lăn (hoặc Shift + lăn) để trượt ngang; kéo bằng nút
  giữa chuột, kéo chỗ trống hoặc thanh cuộn bên dưới để di chuyển; nút −/+ / Vừa khung; nhấp đúp để xem toàn bộ.
  Đang phát thì vạch phát tự cuộn theo.
- Kéo một khối ở làn CLIP sang chỗ khác: đổi thứ tự dòng trong bảng clip (bóng khối theo chuột, vạch chèn trượt mượt
  giữa các khối, thả xong khối vừa chuyển nhấp sáng). Ctrl+Z ở trang Video để quay lại.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from fractions import Fraction

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QScrollBar, QToolTip, QWidget

from ..core import planner
from . import icons, theme
from .widgets import fmt_dur

PALETTE = theme.CLIP_COLORS
BOOKEND = theme.BOOKEND_COLOR
MUSIC = theme.MUSIC_COLORS
SOURCE = theme.SOURCE_COLOR
MARK_W = 7.0  # bề rộng tối thiểu (px) của clip quá ngắn
DRAG_PX = 5.0  # kéo quá ngần này (px) mới tính là kéo khối — ít hơn vẫn là bấm để tua
NICE_STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200)


@dataclass
class Block:
    start: float
    end: float
    color: str
    label: str
    tip: str
    count: int = 1
    clip: int = 0
    short: str = ""  # nhãn ngắn dùng khi khối quá hẹp (số đầu tên file, Intro…)


@dataclass
class Slot:
    """Chỗ thả khối clip đang kéo: mép giữa hai khối (thời điểm `t`) = đặt dòng nguồn trước / sau dòng `target`.
    `target` None = chỗ thả không đổi gì (ngay mép của chính khối đang kéo)."""
    t: float
    target: int | None
    after: bool = False


def short_label(name: str) -> str:
    m = re.match(r"\s*(\d+)", name)
    if m:
        return m.group(1)
    return name[:3]


class TimelineBar(QWidget):
    seekRequested = Signal(float)  # bấm (không kéo) vào dòng thời gian khi cửa sổ Xem trước đang mở
    clipMoveRequested = Signal(int, int, bool)  # kéo khối clip: (dòng nguồn, dòng đích, đặt sau dòng đích)
    trackMoveRequested = Signal(int, int, bool)  # kéo khối bài nhạc: (bài nguồn, bài đích, đặt sau bài đích)
    # kéo thả khi làn đang không cho đổi chỗ (phát ngẫu nhiên): (làn "v"/"m", nguồn, đích, sau) — nơi nhận hỏi người dùng
    # có chuyển sang "Theo thứ tự trong bảng" rồi đổi chỗ không (gợi ý, người dùng quyết)
    blockedMoveRequested = Signal(str, int, int, bool)
    musicStartRequested = Signal(int)  # nhạc chạy từ khối thứ n trên làn CLIP (0 = đầu video)
    musicEndRequested = Signal(int)  # nhạc dừng ở hết khối thứ n (0 = hết video)
    LANE_V, LANE_M = 40, 30  # làn CLIP / NHẠC cao hơn: khối to, dễ bấm và kéo
    PAD_L, PAD_R = 116, 12
    TOP_V = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(112)
        self.setMaximumHeight(118)
        self.setMouseTracking(True)
        self.total = 0.0
        self.video: list[Block] = []
        self.music: list[Block] = []
        self.source: list[Block] = []
        self.ambient = 0
        self.music_only = False
        self.source_off = False
        self.use_source = False
        self.view0, self.view1 = 0.0, 0.0  # khoảng thời gian đang xem (phóng to)
        self._drag: tuple[float, float] | None = None
        self._press: QPointF | None = None
        self.playhead: float | None = None  # vạch đang xem (trình phát)
        self.seek_enabled = False
        self._scrub = False  # đang kéo vạch phát
        self._hits: list[tuple[QRectF, str]] = []
        # kéo khối clip để đổi thứ tự. reorder_block khác rỗng = đang không cho kéo (lý do, hiện khi rê chuột)
        self.reorder_block = ""
        self.music_reorder_block = ""  # như trên, cho làn NHẠC (playlist đang xáo ngẫu nhiên…)
        self.music_rows: list[bool] = []  # dòng nào của bảng clip có nhạc nền (trang Video cập nhật)
        self.track_names: list[str] = []  # tên các bài trong playlist (menu "Bắt đầu nhạc bằng bài")
        self.use_music = False  # video này có playlist nhạc (mới cho kéo mép đoạn nhạc / bật tắt nhạc theo clip)
        self._hd: dict | None = None  # đang kéo mép dải nhạc: {"kind": start|end, "t0", "t", "n"}
        self._hd_hover: str | None = None
        self.follow_playhead = False  # đang phát: vạch phát chạy ra ngoài khung thì khung tự cuộn theo (như Premiere)
        # thanh cuộn ngang: cửa sổ chính đặt ngay dưới dòng thời gian; kéo thanh = trượt khung nhìn
        self.scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self.scrollbar.setToolTip("Kéo để trượt dòng thời gian (Ctrl + lăn chuột để phóng to / thu nhỏ)")
        self.scrollbar.valueChanged.connect(self._on_scroll)
        self._span_override: float | None = None  # đang vẽ dải sẵn: bề ngang dải (px) thay cho bề ngang khung
        self._chrome: QPixmap | None = None
        self._chrome_for: tuple | None = None
        self._strip_t: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (s0, s1, px / giây) của dải vẽ sẵn
        # Lớp vẽ sẵn: các khối, chữ, thước giờ vẽ một lần vào ảnh đệm; rê / kéo / vạch phát chỉ vẽ lớp trên cùng
        # (trước đây mỗi lần nhích chuột vẽ lại hàng trăm khối → khựng). Vẽ lại khi dữ liệu / khung nhìn / cỡ / màu đổi.
        self._data_ver = 0
        self._static: QPixmap | None = None
        self._static_for: tuple | None = None
        self._sections: list[tuple[float, float]] | None = None
        self._tip_last = ""
        self._mv: dict | None = None  # {"lane", "block", "clip", "x0", "x", "on", "slot"}
        self._caret_x: float | None = None  # vạch chèn đang vẽ (trượt mượt tới chỗ thả)
        self._land: tuple[QRectF, QRectF, str, str] | None = None  # bóng khối bay về chỗ thả sau khi nhả chuột
        self._land_k = 1.0
        self._flash_clip: tuple[str, int] | None = None  # (làn, dòng) vừa chuyển: nhấp sáng khi dòng thời gian vẽ lại
        self._flash_now: tuple[str, int] | None = None
        self._flash_k = 0.0
        self.note = "Kéo thả video hoặc nhạc vào dự án để xem trước dòng thời gian trực quan"

    # ---------- dữ liệu ----------
    def set_timeline(self, tl, clip_names: list[str], track_names: list[str]) -> None:
        if self._zoom_running():  # dữ liệu mới: dừng hiệu ứng phóng to dở dang
            self._zoom_anim.stop()
        if self._mv is not None:  # khối đang kéo không còn đúng chỗ nữa
            self._mv = None
            self._caret_x = None
            self.unsetCursor()
        self.video, self.music, self.source = [], [], []
        self.music_only = False
        self._data_ver += 1
        self._sections = None
        if tl is None or not tl.ok or not tl.total:
            self.total = 0.0
            self.note = ((tl.errors[0] if tl.errors else "Chưa tính được dòng thời gian — kiểm tra lại cài đặt")
                         if tl is not None else "Kéo thả video hoặc nhạc vào dự án để xem trước dòng thời gian trực quan")
            self._sync_scrollbar()
            self.update()
            return
        old_total = self.total
        self.total = tl.total
        self.track_names = list(track_names)
        self.use_music = bool(getattr(tl, "use_music", False))
        self._hd = None
        if not old_total or self.view1 <= self.view0 or abs(old_total - self.total) > 1e-6 and self._full_view(old_total):
            self.view0, self.view1 = 0.0, self.total
        self.view1 = min(self.view1, self.total)
        if self.view1 - self.view0 < 1.0:
            self.view0, self.view1 = 0.0, self.total
        self.ambient = len(tl.ambient_infos)
        # clip có tiếng nhưng đang tắt tiếng gốc → nhắc đúng chỗ bật
        # chỉ tính tiếng gốc của clip chính (Intro/Outro giữ tiếng riêng không tính)
        self.use_source = any(on for k, on in tl.audible.items() if k >= 0)
        self.source_off = not tl.use_source and any(i.has_audio for k, i in tl.clip_infos.items() if k >= 0)
        colors: dict[str, str] = {}  # cùng file → cùng màu
        if tl.video and not tl.video.error:
            plan, frames, fps = tl.video, tl.frames, tl.fps
            pos = 0
            for j, (clip, _rnd) in enumerate(plan.plays):
                f = plan.ends.get(j, frames[clip])
                start = float(Fraction(pos) / fps)
                end = float(Fraction(pos + f) / fps)
                name = {planner.INTRO: "Intro", planner.OUTRO: "Outro"}.get(clip) or (
                    clip_names[clip] if 0 <= clip < len(clip_names) else f"Clip {clip + 1}"
                )
                if clip < 0:
                    color = BOOKEND
                else:
                    color = colors.setdefault(os.path.normcase(name), PALETTE[len(colors) % len(PALETTE)])
                last = self.video[-1] if self.video else None
                if last and last.clip == clip:
                    last.end = end
                    last.count += 1
                else:
                    self.video.append(Block(start, end, color, name, "", 1, clip,
                                            {planner.INTRO: "In", planner.OUTRO: "Out"}.get(clip) or short_label(name)))
                if j < len(plan.overlaps):
                    pos += f - plan.overlaps[j]
            for b in self.video:
                cnt_txt = f" (×{b.count} lần)" if b.count > 1 else ""
                b.tip = (f"Hình: {b.label}{cnt_txt}\nThời gian: {fmt_dur(b.start)} → {fmt_dur(b.end)} "
                         f"({self._len_txt(b.end - b.start)})")
            # tiếng gốc của clip (khi không có playlist hoặc trộn cùng nhạc)
            for b in self.video:
                if tl.audible.get(b.clip):
                    last = self.source[-1] if self.source else None
                    if last and abs(last.end - b.start) < 0.05:
                        last.end = b.end
                    else:
                        self.source.append(Block(b.start, b.end, SOURCE, "Tiếng gốc clip", ""))
            for s in self.source:
                s.tip = f"Tiếng gốc của clip\nThời gian: {fmt_dur(s.start)} → {fmt_dur(s.end)}"
        else:
            self.music_only = True

        for k, it in enumerate(tl.music_items):
            name = track_names[it.track] if 0 <= it.track < len(track_names) else f"Bài {it.track + 1}"
            self.music.append(Block(
                it.start, it.start + it.duration, MUSIC[k % len(MUSIC)], name,
                f"Nhạc: {name}\nThời gian: {fmt_dur(it.start)} → {fmt_dur(it.start + it.duration)} "
                f"({self._len_txt(it.duration)})", 1, it.track, short_label(name)
            ))
        self.note = ""
        self._sync_scrollbar()
        if self._flash_clip is not None:
            self._flash_now, self._flash_clip = self._flash_clip, None
            if any(b.clip == self._flash_now[1] for b in self._blocks(self._flash_now[0])):
                self._anim("_flash_anim", 900, QEasingCurve.Type.OutQuad, 1.0, 0.0,
                           lambda k: self._set_k("_flash_k", k))
        self.update()

    # ---------- kéo khối clip / bài nhạc đổi thứ tự ----------
    def flash_clip(self, row: int) -> None:
        """Dòng `row` của bảng clip vừa được chuyển chỗ: khi dòng thời gian tính lại xong thì khối của nó nhấp sáng."""
        self._flash_clip = ("v", row)

    def flash_track(self, row: int) -> None:
        """Bài `row` của playlist vừa được chuyển chỗ: khối nhạc của nó nhấp sáng khi vẽ lại."""
        self._flash_clip = ("m", row)

    def _anim(self, name: str, ms: int, curve, v0: float, v1: float, step) -> QVariantAnimation:
        a = getattr(self, name, None)
        if a is None:
            a = QVariantAnimation(self)
            setattr(self, name, a)
        else:
            a.stop()
            a.valueChanged.disconnect()
        a.valueChanged.connect(lambda v: step(float(v)))
        a.setEasingCurve(curve)
        a.setDuration(ms)
        a.setStartValue(float(v0))
        a.setEndValue(float(v1))
        a.start()
        return a

    def _set_k(self, name: str, k: float) -> None:
        setattr(self, name, k)
        self.update()

    def _set_caret(self, x: float) -> None:
        if self._mv is not None:
            self._caret_x = x
            self.update()

    # làn "v" = CLIP (khối là dòng bảng clip), làn "m" = NHẠC (khối là bài trong playlist)
    def _blocks(self, lane: str) -> list[Block]:
        return self.video if lane == "v" else self.music

    def _lane_y(self, lane: str) -> tuple[float, float]:
        return (self.TOP_V, self.LANE_V) if lane == "v" else (self.TOP_V + self.LANE_V + 6, self.LANE_M)

    def _block_reason(self, lane: str) -> str:
        return self.reorder_block if lane == "v" else self.music_reorder_block

    def _target_block(self, x: float, lane: str) -> int | None:
        """Khối (không phải Intro / Outro) ở vị trí x: khối chứa x, không thì khối gần nhất."""
        vb = self._blocks(lane)
        movable = [k for k, b in enumerate(vb) if b.clip >= 0]
        if not movable:
            return None
        t = self._t(x)
        inside = [k for k in movable if vb[k].start <= t <= vb[k].end]
        if inside:
            return inside[0]
        return min(movable, key=lambda k: min(abs(self._x(vb[k].start) - x), abs(self._x(vb[k].end) - x)))

    def _nearest_slot(self, block: int, x: float, lane: str = "v") -> Slot | None:
        """Thả khối `block` ở x: lấy chỗ của khối đang chỉ vào (như kéo trong danh sách) — dòng nguồn đứng sau dòng đích
        nếu đang ở trên nó trong bảng, đứng trước nếu ở dưới. Cùng một dòng (kể cả lần phát lặp lại của nó) = không đổi.
        Chuỗi lặp nhiều vòng (01 02 03 01 02 03…) vẫn luôn ra một thay đổi thấy được."""
        vb = self._blocks(lane)
        if not (0 <= block < len(vb)) or vb[block].clip < 0:
            return None
        k = self._target_block(x, lane)
        if k is None:
            return None
        src, tgt = vb[block].clip, vb[k].clip
        if tgt == src:
            return Slot(vb[k].start, None, False)
        after = src < tgt
        return Slot(vb[k].end if after else vb[k].start, tgt, after)

    def _drop_slots(self, block: int, lane: str = "v") -> list[Slot]:
        """Các kết quả thả khác nhau (mỗi cặp dòng đích / trước-sau một lần), theo thứ tự trên dòng thời gian."""
        vb = self._blocks(lane)
        seen, out = set(), []
        for k, b in enumerate(vb):
            if b.clip < 0:
                continue
            s = self._nearest_slot(block, (self._x(b.start) + self._x(b.end)) / 2, lane)
            if s is not None and s.target is not None and (s.target, s.after) not in seen:
                seen.add((s.target, s.after))
                out.append(s)
        return out

    def _block_rect(self, b: Block, lane: str = "v") -> QRectF:
        top, h = self._lane_y(lane)
        x0, x1 = self._x(b.start), self._x(b.end)
        if x1 - x0 < MARK_W + 1:
            return QRectF((x0 + x1) / 2 - MARK_W / 2 - 4, top, MARK_W + 8, h)
        return QRectF(x0, top, x1 - x0 - 1.0, h)

    def _block_at(self, pos) -> tuple[str, int] | None:
        """(làn, khối) dưới con trỏ (khối ngắn vẽ thành vạch được ưu tiên)."""
        if pos.x() < self.PAD_L:
            return None
        for lane in ("v", "m"):
            top, h = self._lane_y(lane)
            if top <= pos.y() <= top + h:
                blocks = self._blocks(lane)
                hits = [k for k, b in enumerate(blocks) if self._block_rect(b, lane).contains(pos)]
                if hits:
                    return lane, min(hits, key=lambda k: (self._block_rect(blocks[k], lane).width(),
                                                          abs(self._block_rect(blocks[k], lane).center().x() - pos.x())))
        return None

    def _movable_at(self, pos) -> tuple[str, int] | None:
        hit = self._block_at(pos)
        if hit is None or self._blocks(hit[0])[hit[1]].clip < 0:
            return None
        return hit

    def _ghost_rect(self, mv: dict) -> QRectF:
        b = self._blocks(mv["lane"])[mv["block"]]
        top, h = self._lane_y(mv["lane"])
        w = min(180.0, max(44.0, self._x(b.end) - self._x(b.start)))
        return QRectF(mv["x"] - w / 2, top - 4, w, h + 2)

    def _draw_drag(self, p: QPainter, small) -> None:
        """Khối đang kéo: chỗ cũ mờ đi + viền chấm, vạch chèn có núm, bóng khối nổi theo chuột."""
        mv = self._mv
        if mv is not None and mv["on"] and 0 <= mv["block"] < len(self._blocks(mv["lane"])):
            lane = mv["lane"]
            b = self._blocks(lane)[mv["block"]]
            hole = QPainterPath()
            hole.addRoundedRect(self._block_rect(b, lane), 5, 5)
            p.fillPath(hole, theme.qcolor("panel", 170))
            p.setPen(QPen(theme.qcolor("line_strong"), 1.2, Qt.PenStyle.DashLine))
            p.drawPath(hole)
            if self._caret_x is not None:
                x = self._caret_x
                y0, h = self._lane_y(lane)
                top, bot = y0 - 3, y0 + h + 3
                p.fillRect(QRectF(x - 4, top, 8, bot - top), theme.qcolor("accent", 60))  # quầng sáng
                p.setPen(QPen(theme.qcolor("accent"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(x, top), QPointF(x, bot))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.qcolor("accent"))
                p.drawEllipse(QPointF(x, top), 4, 4)
                p.drawEllipse(QPointF(x, bot), 4, 4)
                p.setBrush(Qt.BrushStyle.NoBrush)
            slot = mv["slot"]
            label = b.label
            if slot is not None and slot.target is not None:
                names = {x.clip: x.label for x in self._blocks(lane)}
                label = f"{b.label}  →  {'sau' if slot.after else 'trước'} {names.get(slot.target, '')}"
            elif slot is not None:
                label = f"{b.label}  ·  giữ nguyên"
            g = self._ghost_rect(mv)
            if slot is not None and slot.target is not None:
                g.setWidth(max(g.width(), min(320.0, p.fontMetrics().horizontalAdvance(label) + 24)))
                g.moveLeft(min(max(self.PAD_L, mv["x"] - g.width() / 2), self.width() - self.PAD_R - g.width()))
            self._paint_ghost(p, g, b.color, label, small, 1.0)
        if self._land is not None and self._land_k < 1.0:
            r0, r1, color, label = self._land
            k = self._land_k
            r = QRectF(r0.x() + (r1.x() - r0.x()) * k, r0.y() + (r1.y() - r0.y()) * k,
                       r0.width() + (r1.width() - r0.width()) * k, r0.height() + (r1.height() - r0.height()) * k)
            self._paint_ghost(p, r, color, label, small, 1.0 - k)

    def _paint_ghost(self, p: QPainter, r: QRectF, color: str, label: str, small, alpha: float) -> None:
        p.save()
        p.setOpacity(p.opacity() * max(0.0, min(1.0, alpha)))
        shadow = QPainterPath()
        shadow.addRoundedRect(r.translated(0, 3), 6, 6)
        p.fillPath(shadow, theme.qcolor("black", 70))
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        base = QColor(color)
        grad = QLinearGradient(r.topLeft(), r.bottomLeft())
        grad.setColorAt(0.0, base.lighter(125))
        grad.setColorAt(1.0, base)
        p.fillPath(path, grad)
        p.setPen(QPen(theme.qcolor("white", 220), 1.5))
        p.drawPath(path)
        p.setFont(small)
        p.setPen(theme.qcolor("white"))
        fm = p.fontMetrics()
        p.drawText(r.adjusted(8, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm.elidedText(label, Qt.TextElideMode.ElideRight, int(max(0.0, r.width() - 14))))
        p.restore()

    def _draw_flash(self, p: QPainter) -> None:
        if self._flash_now is None or self._flash_k <= 0.0:
            return
        lane, row = self._flash_now
        for b in self._blocks(lane):
            if b.clip == row and not (b.end < self.view0 or b.start > self.view1):
                path = QPainterPath()
                path.addRoundedRect(self._block_rect(b, lane).adjusted(-1, -2, 1, 2), 6, 6)
                p.fillPath(path, theme.qcolor("white", int(110 * self._flash_k)))
                p.setPen(QPen(theme.qcolor("accent", int(255 * self._flash_k)), 2))
                p.drawPath(path)

    def _move_drag(self, x: float) -> None:
        mv = self._mv
        mv["x"] = x
        slot = self._nearest_slot(mv["block"], x, mv["lane"])
        mv["slot"] = slot
        if slot is not None and slot.target is not None:
            to = self._x(slot.t)
            if self._caret_x is None:
                self._caret_x = to
            elif abs(to - self._caret_x) > 0.5:  # vạch chèn trượt tới chỗ thả mới
                self._anim("_caret_anim", 120, QEasingCurve.Type.OutCubic, self._caret_x, to, self._set_caret)
        else:
            self._caret_x = None
        self.update()

    def _finish_drag(self) -> None:
        mv, self._mv = self._mv, None
        self.unsetCursor()
        if mv is None or not mv["on"] or not (0 <= mv["block"] < len(self._blocks(mv["lane"]))):
            return
        lane, slot = mv["lane"], mv["slot"]
        b = self._blocks(lane)[mv["block"]]
        g = self._ghost_rect(mv)
        if slot is not None and slot.target is not None:
            x = self._x(slot.t)
            top, h = self._lane_y(lane)
            dest = QRectF(x - g.width() / 2, top, g.width(), h)
        else:
            dest = self._block_rect(b, lane)  # thả chỗ không đổi gì: bóng bay về chỗ cũ
        self._land = (g, dest, b.color, b.label)
        self._land_k = 0.0
        self._anim("_land_anim", 240, QEasingCurve.Type.OutCubic, 0.0, 1.0, lambda k: self._set_k("_land_k", k))
        self._caret_x = None
        self.update()
        if slot is not None and slot.target is not None:
            if self._block_reason(lane):
                self.blockedMoveRequested.emit(lane, mv["clip"], slot.target, slot.after)
                return
            sig = self.clipMoveRequested if lane == "v" else self.trackMoveRequested
            sig.emit(mv["clip"], slot.target, slot.after)

    # ---------- nhạc chạy từ clip nào: một tay nắm ♪ (thay cho kéo mép, chuột phải, Alt + quét) ----------
    def _music_sections(self) -> list[tuple[float, float]]:
        """Các đoạn có nhạc trên làn NHẠC (gộp các bài liền / chồng crossfade) — tính một lần cho mỗi lần dựng."""
        if self._sections is not None:
            return self._sections
        out: list[tuple[float, float]] = []
        for b in sorted(self.music, key=lambda b: b.start):
            if out and b.start <= out[-1][1] + 0.1:
                out[-1] = (out[-1][0], max(out[-1][1], b.end))
            else:
                out.append((b.start, b.end))
        self._sections = out
        return out

    def _numbered(self) -> list[Block]:
        """Khối được đánh số "clip 1, 2, 3…" trong dòng chọn nhạc (bỏ Intro / Outro)."""
        return [b for b in self.video if b.clip >= 0]

    def _handle_t(self) -> float | None:
        """Mép đầu dải nhạc (tay nắm ♪)."""
        if not (self.use_music and self.video and self.music):
            return None
        if self._hd is not None and self._hd["kind"] == "start":
            return self._hd["t"]
        secs = self._music_sections()
        return secs[0][0] if secs else None

    def _end_handle_t(self) -> float | None:
        """Mép cuối dải nhạc."""
        if not (self.use_music and self.video and self.music):
            return None
        if self._hd is not None and self._hd["kind"] == "end":
            return self._hd["t"]
        secs = self._music_sections()
        return secs[-1][1] if secs else None

    def _handle_x(self) -> float | None:
        t = self._handle_t()
        return None if t is None else self._x(t)

    def _end_handle_x(self) -> float | None:
        t = self._end_handle_t()
        return None if t is None else self._x(t)

    def _handle_y(self) -> float:
        top, h = self._lane_y("m")
        return top + h / 2

    def _which_handle(self, pos) -> str | None:
        """Mép dải nhạc dưới con trỏ: "start" / "end" (gần nhất trong 9 px)."""
        top, h = self._lane_y("m")
        if not (top - 4 <= pos.y() <= top + h + 4):
            return None
        best, bd = None, 9.0
        for kind, x in (("start", self._handle_x()), ("end", self._end_handle_x())):
            if x is not None and abs(pos.x() - x) <= bd:
                best, bd = kind, abs(pos.x() - x)
        return best

    def _on_handle(self, pos) -> bool:
        return self._which_handle(pos) is not None

    def _handle_snap(self, x: float, kind: str = "start") -> tuple[float, int]:
        """Hít vào ranh giới clip gần nhất: mép đầu → đầu khối (0 = đầu video); mép cuối → hết khối (0 = hết video)."""
        nb = self._numbered()
        if kind == "start":
            pts = [(0.0, 0)] + [(b.start, k + 1) for k, b in enumerate(nb)]
        else:
            pts = [(b.end, k + 1) for k, b in enumerate(nb)] + [(self.total, 0)]
        return min(pts, key=lambda q: abs(self._x(q[0]) - x))

    def _handle_label(self, n: int, kind: str = "start") -> str:
        nb = self._numbered()
        name = f" · {nb[n - 1].label}" if 0 < n <= len(nb) else ""
        if kind == "start":
            return f"Nhạc chạy từ clip {n}{name}" if n else "Nhạc chạy từ đầu video"
        return f"Nhạc chạy tới hết clip {n}{name}" if n else "Nhạc chạy tới hết video"

    def _hd_label(self) -> str:
        return self._handle_label(self._hd["n"], self._hd["kind"]) if self._hd else ""

    def _music_menu(self, block: int) -> list[tuple[str, object]]:
        """Chuột phải vào khối clip: bấm thẳng vào clip để đặt chỗ nhạc vào / nhạc dừng (khỏi phải đếm số)."""
        nb = self._numbered()
        b = self.video[block] if 0 <= block < len(self.video) else None
        if b is None or b.clip < 0 or b not in nb:
            return []
        n = nb.index(b) + 1
        return [("Nhạc bắt đầu từ clip này", lambda: self.musicStartRequested.emit(n)),
                ("Nhạc dừng ở hết clip này", lambda: self.musicEndRequested.emit(n)),
                ("Nhạc chạy từ đầu video", lambda: self.musicStartRequested.emit(0)),
                ("Nhạc chạy tới hết video", lambda: self.musicEndRequested.emit(0))]

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        hit = self._movable_at(e.pos())
        acts = self._music_menu(hit[1]) if hit is not None and hit[0] == "v" and self.use_music else []
        if not acts:
            return super().contextMenuEvent(e)
        menu = QMenu(self)
        n = self._numbered().index(self.video[hit[1]]) + 1
        head = menu.addAction(icons.icon("music", 14), f"Clip {n} · {self.video[hit[1]].label}")
        head.setEnabled(False)
        menu.addSeparator()
        for k, (label, fn) in enumerate(acts):
            if k == 2:
                menu.addSeparator()
            menu.addAction(label, fn)
        menu.exec(e.globalPos())

    def _draw_music_gaps(self, p: QPainter, small) -> None:
        """Khoảng không nhạc (gạch chéo mờ) — phần đứng yên, nằm trong lớp vẽ sẵn."""
        if not (self.use_music and self.video and self.music):
            return
        top, h = self._lane_y("m")
        secs = self._music_sections()
        gaps, pos = [], 0.0
        for a, b in secs:
            if a - pos > 0.05:
                gaps.append((pos, a))
            pos = max(pos, b)
        if self.total - pos > 0.05:
            gaps.append((pos, self.total))
        p.setFont(small)
        for a, b in gaps:
            r = QRectF(self._x(a), top, max(1.0, self._x(b) - self._x(a) - 1.0), h)
            path = QPainterPath()
            path.addRoundedRect(r, 4, 4)
            p.fillPath(path, QBrush(theme.qcolor("text_muted", 40), Qt.BrushStyle.BDiagPattern))
            if r.width() > 70:
                p.setPen(theme.qcolor("text_muted"))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, "không nhạc")

    def _draw_music_edit(self, p: QPainter, small) -> None:
        """Hai tay nắm ở mép đầu (♪) / mép cuối dải nhạc (lớp trên): rê vào sáng lên, kéo thì có vạch dẫn + bong bóng."""
        top, h = self._lane_y("m")
        hd = self._hd
        if hd is not None:
            lo, hi = sorted((hd["t0"], hd["t"]))
            if hi - lo > 1e-6:
                r = QRectF(self._x(lo), top, self._x(hi) - self._x(lo), h)
                path = QPainterPath()
                path.addRoundedRect(r, 4, 4)
                grow = (hd["t"] < hd["t0"]) == (hd["kind"] == "start")  # dải nhạc dài ra
                if grow:
                    p.fillPath(path, theme.qcolor("accent", 90))
                else:
                    p.fillPath(path, QBrush(theme.qcolor("text_muted", 120), Qt.BrushStyle.BDiagPattern))
            x = self._x(hd["t"])
            p.setPen(QPen(theme.qcolor("accent"), 2))
            p.drawLine(QPointF(x, self.TOP_V - 3), QPointF(x, top + h + 3))
            self._bubble(p, x, self._hd_label(), small)
        for kind, hx in (("start", self._handle_x()), ("end", self._end_handle_x())):
            if hx is None:
                continue
            hot = (hd is not None and hd["kind"] == kind) or self._hd_hover == kind
            knob = QRectF(hx - (8 if hot else 7) - (0 if kind == "start" else 1), top + 2, 16 if hot else 14, h - 4)
            if kind == "end":
                knob.moveRight(hx + 1)
            else:
                knob.moveLeft(hx - 1)
            path = QPainterPath()
            path.addRoundedRect(knob, 5, 5)
            p.fillPath(path, theme.qcolor("accent" if hot else "panel", 255 if hot else 235))
            p.setPen(QPen(theme.qcolor("accent"), 1.5))
            p.drawPath(path)
            p.drawPixmap(int(knob.center().x() - 6), int(knob.center().y() - 6),
                         icons.pixmap("music" if kind == "start" else "stop", 12,
                                      "text_on_accent" if hot else "accent_text"))

    def _bubble(self, p: QPainter, x: float, text: str, small) -> None:
        p.setFont(small)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 16
        r = QRectF(min(max(self.PAD_L, x - w / 2), self.width() - self.PAD_R - w), 1, w, 16)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.fillPath(path, theme.qcolor("accent"))
        p.setPen(theme.qcolor("text_on_accent"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _len_txt(sec: float) -> str:
        return f"{sec:.1f} giây" if sec < 60 else fmt_dur(sec)

    def _full_view(self, total: float) -> bool:
        return self.view0 <= 1e-6 and self.view1 >= total - 1e-6

    # ---------- toạ độ ----------
    def _span_px(self) -> float:
        if self._span_override is not None:
            return self._span_override
        return max(10.0, self.width() - self.PAD_L - self.PAD_R)

    def _scale(self) -> float:
        """px / giây của khung nhìn hiện tại."""
        return self._span_px() / max(1e-6, self.view1 - self.view0)

    def _x(self, t: float) -> float:
        vs = max(1e-6, self.view1 - self.view0)
        return self.PAD_L + self._span_px() * (t - self.view0) / vs

    def _t(self, x: float) -> float:
        vs = max(1e-6, self.view1 - self.view0)
        return self.view0 + (x - self.PAD_L) / self._span_px() * vs

    def _audio_lane_name(self) -> str:
        """Tên làn dưới theo đúng thứ đang có trong video."""
        if self.music:
            return "NHẠC + GỐC" if self.use_source else "NHẠC"
        return "TIẾNG GỐC" if self.source else "NHẠC"

    def _lane_tip(self, y: float) -> str:
        if y < self.TOP_V + self.LANE_V + 3:
            return "CLIP: các clip trong bảng ở trang Video, xếp theo đúng thứ tự phát (cùng một file luôn cùng màu)"
        return {
            "NHẠC": "NHẠC: các bài trong playlist ở trang Nhạc, tự lặp cho đủ độ dài video",
            "NHẠC + GỐC": "NHẠC + GỐC: playlist nhạc trộn với tiếng gốc của clip (chỉnh âm lượng ở Bảng trộn âm)",
            "TIẾNG GỐC": "TIẾNG GỐC: chỉ dùng tiếng có sẵn trong clip, không có playlist nhạc",
        }[self._audio_lane_name()]

    # ---------- vẽ ----------
    def _fonts(self) -> tuple[QFont, QFont, QFont]:
        small = QFont(self.font())
        small.setPointSize(max(8, small.pointSize() - 1))
        bold = QFont(small)
        bold.setBold(True)
        tiny = QFont(small)
        tiny.setPointSize(max(7, small.pointSize() - 1))
        tiny.setBold(True)
        return small, bold, tiny

    def _look_key(self) -> tuple:
        return (self.height(), self.devicePixelRatioF(), self._data_ver, self.font().key(),
                theme.qcolor("panel").rgba(), theme.qcolor("accent").rgba(), theme.qcolor("text").rgba(),
                theme.qcolor("field").rgba())

    def _new_pixmap(self, w: float) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(1, round(w * dpr)), max(1, round(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        return pm

    def _chrome_layer(self) -> QPixmap:
        """Nền, tên làn, rãnh làn — chỉ đổi khi cỡ / màu / dữ liệu đổi."""
        key = (self.width(),) + self._look_key()
        if self._chrome is None or self._chrome_for != key:
            pm = self._new_pixmap(self.width())
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_chrome(p)
            p.end()
            self._chrome, self._chrome_for = pm, key
        return self._chrome

    def _strip_layer(self) -> tuple[QPixmap, float]:
        """Dải vẽ sẵn (khối clip / nhạc, khoảng không nhạc, vạch thước giờ) rộng hơn khung nhìn: trượt ngang chỉ dịch
        ảnh, không vẽ lại (như Premiere). Vẽ lại khi phóng to / thu nhỏ, khi trượt ra ngoài dải, hoặc dữ liệu đổi.
        Trả về (ảnh, độ lệch x để dán)."""
        k = self._scale()
        s0, s1, sk = self._strip_t
        key = self._look_key()
        fresh = (self._static is not None and self._static_for == key and abs(sk - k) <= k * 1e-9
                 and s0 - 1e-9 <= self.view0 and self.view1 <= s1 + 1e-9)
        if not fresh:
            vs = self.view1 - self.view0
            margin = 0.0 if self._zoom_running() and abs(sk - k) > k * 1e-9 else vs  # đang zoom: chỉ khung nhìn
            s0, s1 = max(0.0, self.view0 - margin), min(self.total, self.view1 + margin)
            strip_w = (s1 - s0) * k
            pm = self._new_pixmap(self.PAD_L + strip_w + 2)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            saved = (self.view0, self.view1)
            self.view0, self.view1, self._span_override = s0, s1, strip_w
            try:
                self._hits = []
                self._paint_static(p)
            finally:
                self.view0, self.view1 = saved
                self._span_override = None
            p.end()
            self._static, self._static_for, self._strip_t = pm, key, (s0, s1, k)
        return self._static, (self._strip_t[0] - self.view0) * k

    def _paint_background(self, p: QPainter) -> None:
        w, h = self.width(), self.height()
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), theme.R["lg"], theme.R["lg"])
        p.fillPath(bg, theme.qcolor("panel"))
        p.setPen(QPen(theme.qcolor("line"), 1))
        p.drawPath(bg)

    def _paint_chrome(self, p: QPainter) -> None:
        _small, bold, _tiny = self._fonts()
        self._paint_background(p)
        top_v = self.TOP_V
        top_m = top_v + self.LANE_V + 6
        p.setFont(bold)
        p.setPen(theme.qcolor("text_muted"))
        p.drawPixmap(10, int(top_v + (self.LANE_V - 13) / 2), icons.pixmap("film", 13, "text_muted"))
        p.drawText(QRectF(27, top_v, self.PAD_L - 30, self.LANE_V),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "CLIP")
        p.drawPixmap(10, int(top_m + (self.LANE_M - 13) / 2), icons.pixmap("music", 13, "text_muted"))
        p.drawText(QRectF(27, top_m, self.PAD_L - 30, self.LANE_M),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._audio_lane_name())
        for y_lane, h_lane in ((top_v, self.LANE_V), (top_m, self.LANE_M)):
            slot = QPainterPath()
            slot.addRoundedRect(QRectF(self.PAD_L, y_lane, self._span_px(), h_lane), 6, 6)
            p.fillPath(slot, theme.qcolor("field"))

    def _paint_static(self, p: QPainter) -> None:
        """Nội dung dải vẽ sẵn (toạ độ theo dải: view0 / view1 / bề ngang đã đặt tạm cho cả dải)."""
        h = self.height()
        small, bold, tiny = self._fonts()
        top_v = self.TOP_V
        top_m = top_v + self.LANE_V + 6
        track_w = self._span_px()
        p.save()
        p.setClipRect(QRectF(self.PAD_L, 0, track_w, h))
        p.setFont(small)
        if self.video:
            self._draw_lane(p, self.video, top_v, self.LANE_V, small, tiny, gradient=True)
        if self.music:
            self._draw_lane(p, self.music, top_m, self.LANE_M, small, tiny, gradient=False)
        elif self.source:
            self._draw_source(p, top_m, small)
        self._draw_music_gaps(p, small)
        p.restore()
        self._draw_ruler(p, top_m + self.LANE_M + 4, small, bold)

    def _paint_lane_notes(self, p: QPainter, small) -> None:
        """Làn trống: dòng chữ giải thích (vẽ thẳng, cố định trong khung)."""
        track_w = self._span_px()
        top_v = self.TOP_V
        top_m = top_v + self.LANE_V + 6
        p.setFont(small)
        p.setPen(theme.qcolor("text_disabled"))
        if not self.video:
            msg = "Chế độ Chỉ nhạc — không dùng hình ảnh" if self.music_only else "Chưa có clip video"
            p.drawText(QRectF(self.PAD_L + 10, top_v, track_w - 20, self.LANE_V),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, msg)
        if not self.music and not self.source:
            p.drawText(QRectF(self.PAD_L + 10, top_m, track_w - 20, self.LANE_M),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "Chỉ có tiếng nền" if self.ambient else
                       "Chưa có nhạc · tiếng gốc của clip đang tắt (bật ở thẻ Khung & Tiếng, trang Video)" if self.source_off
                       else "Không có âm thanh (chưa có nhạc, clip không có tiếng gốc)")

    def _paint_sticky_labels(self, p: QPainter, small) -> None:
        """Khối dài bắt đầu ở bên trái khung nhìn (đang phóng to): giữ tên ở mép trái để luôn đọc được."""
        p.setFont(small)
        fm = p.fontMetrics()
        for blocks, top, lane_h, grad in ((self.video, self.TOP_V, self.LANE_V, True),
                                          (self.music, self.TOP_V + self.LANE_V + 6, self.LANE_M, False)):
            b = next((b for b in blocks if b.start < self.view0 - 1e-6 < b.end), None)
            if b is None:
                continue
            vis_w = self._x(b.end) - self.PAD_L - 1
            disp = f"{b.label} ×{b.count}" if b.count > 1 else b.label
            w = min(vis_w, fm.horizontalAdvance(disp) + 14)
            if w < 40:
                continue
            r = QRectF(self.PAD_L, top, w, lane_h)
            base = QColor(b.color)
            if grad:
                g = QLinearGradient(r.topLeft(), r.bottomLeft())
                g.setColorAt(0.0, base.lighter(112))
                g.setColorAt(1.0, base.darker(115))
                p.fillRect(r, g)
            else:
                p.fillRect(r, base)
            p.setPen(theme.qcolor("white"))
            p.drawText(r.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText(disp, Qt.TextElideMode.ElideRight, int(w - 10)))

    def _paint_view_label(self, p: QPainter, bold) -> None:
        """Góc phải thước giờ: khoảng đang xem / tổng (theo khung nhìn, vẽ trên cùng có nền che vạch thước)."""
        h = self.height()
        y = self._ruler_y()
        zoomed = not self._full_view(self.total)
        text = (f"{fmt_dur(self.view0)} – {fmt_dur(self.view1)} / {fmt_dur(self.total)}"
                if zoomed else fmt_dur(self.total))
        if self.ambient:
            text = f"{self.ambient} lớp tiếng nền  ·  " + text
        p.setFont(bold)
        w = p.fontMetrics().horizontalAdvance(text) + 12
        r = QRectF(self.PAD_L + self._span_px() - w, y, w, h - y - 2)
        p.fillRect(r, theme.qcolor("panel"))
        p.setPen(theme.qcolor("text"))
        p.drawText(r.adjusted(0, 0, -4, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.35)
        w, h = self.width(), self.height()
        small, bold, _tiny = self._fonts()

        if not self.total:
            self._hits = []
            self._paint_background(p)
            p.setFont(small)
            p.setPen(theme.qcolor("text_muted"))
            pm = icons.pixmap("timeline", 15, "text_muted")
            tw = p.fontMetrics().horizontalAdvance(self.note)
            start_x = max(16.0, (w - (tw + 24)) / 2.0)
            p.drawPixmap(int(start_x), int((h - 15) / 2), pm)
            p.drawText(QRectF(start_x + 22, 0, w - start_x - 28, h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.note)
            return

        p.drawPixmap(0, 0, self._chrome_layer())  # nền + tên làn: vẽ sẵn
        top_v = self.TOP_V
        top_m = top_v + self.LANE_V + 6
        p.save()
        p.setClipRect(QRectF(self.PAD_L, 0, self._span_px(), h))
        if self._zoom_running() and self._static is not None and self._static_for == self._look_key():
            # đang zoom (hiệu ứng ~0,2 giây): kéo giãn dải đã vẽ, zoom xong mới vẽ lại nét (vẽ lại mỗi khung thì giật)
            s0, _s1, sk = self._strip_t
            k = self._scale()
            sx = k / sk
            p.translate(self.PAD_L + (s0 - self.view0) * k - self.PAD_L * sx, 0)
            p.scale(sx, 1.0)
            p.drawPixmap(0, 0, self._static)
            p.resetTransform()
        else:
            strip, dx = self._strip_layer()  # khối, nhạc, thước giờ: dải vẽ sẵn, trượt ngang chỉ dịch ảnh
            p.drawPixmap(QPointF(dx, 0), strip)
        self._paint_sticky_labels(p, small)
        p.restore()
        self._paint_lane_notes(p, small)
        self._paint_view_label(p, bold)
        # ----- lớp trên: nhấp sáng, mép dải nhạc, vạch phát, khối đang kéo -----
        p.save()
        p.setClipRect(QRectF(self.PAD_L, 0, self._span_px(), h))
        self._draw_flash(p)
        self._draw_music_edit(p, small)
        if self.playhead is not None and self.view0 <= self.playhead <= self.view1:
            x = self._x(self.playhead)
            p.setPen(QPen(theme.qcolor("text"), 2))
            p.drawLine(QPointF(x, top_v - 4), QPointF(x, top_m + self.LANE_M + 2))
            head = QPainterPath()
            head.moveTo(x - 5, top_v - 7)
            head.lineTo(x + 5, top_v - 7)
            head.lineTo(x, top_v - 1)
            head.closeSubpath()
            p.fillPath(head, theme.qcolor("text"))
        self._draw_drag(p, small)
        p.restore()
        if self.playhead is not None and self.view0 <= self.playhead <= self.view1:
            # tay nắm vạch phát trên thước giờ (kéo để tua, như CapCut / Premiere)
            x = self._x(self.playhead)
            ry = top_m + self.LANE_M + 4
            knob = QPainterPath()
            knob.addRoundedRect(QRectF(x - 5, ry + 1, 10, max(8.0, h - ry - 4)), 3, 3)
            p.fillPath(knob, theme.qcolor("text"))
            p.setPen(QPen(theme.qcolor("text"), 2))
            p.drawLine(QPointF(x, top_m + self.LANE_M), QPointF(x, ry + 1))

    def _draw_lane(self, p: QPainter, blocks: list[Block], top: float, lane_h: float, small, tiny,
                   gradient: bool) -> None:
        span0, span1 = self.view0, self.view1
        shorts: list[tuple[QRectF, Block]] = []
        prev_short = False
        for b in blocks:
            if b.end < span0 or b.start > span1:
                continue
            x0, x1 = self._x(b.start), self._x(b.end)
            if x1 - x0 < MARK_W + 1:
                shorts.append((QRectF((x0 + x1) / 2 - MARK_W / 2, top, MARK_W, lane_h), b))
                prev_short = True
                continue
            indent = 20 if prev_short else 6  # chừa chỗ cho nhãn số của clip ngắn ngay trước
            prev_short = False
            r = QRectF(x0, top, x1 - x0 - 1.0, lane_h)
            path = QPainterPath()
            path.addRoundedRect(r, 5 if gradient else 4, 5 if gradient else 4)
            base_col = QColor(b.color)
            if gradient:
                grad = QLinearGradient(r.topLeft(), r.bottomLeft())
                grad.setColorAt(0.0, base_col.lighter(112))
                grad.setColorAt(1.0, base_col.darker(115))
                p.fillPath(path, grad)
            else:
                p.fillPath(path, base_col)
            self._hits.append((r, b.tip))
            # chữ nằm trong phần đang nhìn thấy của khối
            vis = r.intersected(QRectF(self.PAD_L, top, self._span_px(), lane_h))
            disp = f"{b.label} ×{b.count}" if b.count > 1 else b.label
            p.setFont(small)
            fm = p.fontMetrics()
            if vis.width() > 40:
                p.setPen(theme.qcolor("white"))
                p.drawText(vis.adjusted(indent, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           fm.elidedText(disp, Qt.TextElideMode.ElideRight, int(vis.width() - indent - 4)))
            elif vis.width() > 14:
                p.setFont(tiny)
                p.setPen(theme.qcolor("white"))
                p.drawText(vis, Qt.AlignmentFlag.AlignCenter, b.short)
        # clip quá ngắn: vạch nổi có viền + nhãn số phía trên các khối dài
        p.setFont(tiny)
        fm = p.fontMetrics()
        dense = len(shorts) > 120  # hàng trăm vạch sát nhau (video dài, đang xem rộng): khối phẳng, không viền — nhanh
        light: dict[str, QColor] = {}
        pen = QPen(theme.qcolor("text"), 1.2)
        for r, b in shorts:
            col = light.get(b.color)
            if col is None:
                col = light[b.color] = QColor(b.color).lighter(115)
            if dense:
                p.fillRect(r, col)
                continue
            path = QPainterPath()
            path.addRoundedRect(r, 2.5, 2.5)
            p.fillPath(path, col)
            p.setPen(pen)
            p.drawPath(path)
            self._hits.append((r.adjusted(-4, 0, 4, 0), b.tip))
        # nhãn vẽ sau tất cả các vạch để không bị vạch bên cạnh đè; giữ trong khung, bỏ nhãn khi quá dày
        lo_x, hi_x = self.PAD_L + 1, self.PAD_L + self._span_px() - 1
        last_badge_right = -1e9
        if len(shorts) * 30 > self._span_px():
            shorts = []  # quá dày (ví dụ video 3 giờ, 100 cảnh): chỉ giữ vạch, phóng to để thấy nhãn
        for r, b in shorts:
            bw = max(16.0, fm.horizontalAdvance(b.short) + 8)
            bx = min(max(r.center().x() - bw / 2, lo_x), hi_x - bw)
            badge = QRectF(bx, top + lane_h / 2 - 7, bw, 14)
            if badge.left() < last_badge_right + 2:
                continue
            last_badge_right = badge.right()
            bp = QPainterPath()
            bp.addRoundedRect(badge, 7, 7)
            p.fillPath(bp, theme.qcolor("field"))
            p.setPen(QPen(QColor(b.color).lighter(130), 1.2))
            p.drawPath(bp)
            p.setPen(theme.qcolor("text"))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, b.short)
            self._hits.append((badge, b.tip))

    def _draw_source(self, p: QPainter, top: float, small) -> None:
        p.setFont(small)
        for s in self.source:
            if s.end < self.view0 or s.start > self.view1:
                continue
            x0, x1 = self._x(s.start), self._x(s.end)
            r = QRectF(x0, top, max(2.0, x1 - x0 - 1.0), self.LANE_M)
            path = QPainterPath()
            path.addRoundedRect(r, 4, 4)
            p.fillPath(path, QColor(SOURCE))
            p.fillPath(path, QBrush(theme.qcolor("white", 18), Qt.BrushStyle.BDiagPattern))
            self._hits.append((r, s.tip))
            vis = r.intersected(QRectF(self.PAD_L, top, self._span_px(), self.LANE_M))
            if vis.width() > 110:
                p.setPen(theme.qcolor("text_2"))
                p.drawText(vis.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           "Tiếng gốc của clip")

    def _draw_ruler(self, p: QPainter, y: float, small, bold) -> None:
        """Vạch + số của thước giờ; bước tự đổi theo mức phóng to (1 giây … 12 giờ), luôn ≥ ~95 px giữa hai vạch."""
        h = self.height()
        vs = max(1e-6, self.view1 - self.view0)
        step = next((s for s in NICE_STEPS if self._span_px() * s / vs >= 95), NICE_STEPS[-1])
        p.setFont(small)
        fm = p.fontMetrics()
        t = (self.view0 // step) * step
        while t <= self.view1 + 1e-6:
            x = self._x(t)
            if x >= self.PAD_L - 0.5:
                p.setPen(QPen(theme.qcolor("line"), 1))
                p.drawLine(QPointF(x, y - 3), QPointF(x, y))
                label = fmt_dur(t)
                lw = fm.horizontalAdvance(label)
                p.setPen(theme.qcolor("text_muted"))
                p.drawText(QRectF(max(self.PAD_L, x - lw / 2), y, lw + 2, h - y - 2),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            t += step

    # ---------- tương tác ----------
    def wheelEvent(self, e) -> None:  # noqa: N802
        """Như Premiere: Ctrl + lăn = phóng to / thu nhỏ quanh con trỏ; lăn hoặc Shift + lăn = trượt ngang."""
        if not self.total:
            return super().wheelEvent(e)
        dy = e.angleDelta().y()
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._zoom_at(e.position().x(), 0.8 ** (dy / 120.0))
            e.accept()
            return
        if self._full_view(self.total):
            return super().wheelEvent(e)  # cả video vừa khung: không có gì để trượt
        c0, c1 = self._zoom_target if self._zoom_running() else (self.view0, self.view1)
        vs = c1 - c0
        d = -(dy or e.angleDelta().x()) / 120.0 * vs * 0.15
        v0 = min(max(0.0, c0 + d), self.total - vs)
        self._animate_view(v0, v0 + vs, 120)
        e.accept()

    def _zoom_at(self, x: float, factor: float) -> None:
        """Phóng to (factor < 1) / thu nhỏ quanh điểm x, giữ nguyên thời điểm dưới x."""
        x = min(max(x, self.PAD_L), self.PAD_L + self._span_px())
        c0, c1 = self._zoom_target if self._zoom_running() else (self.view0, self.view1)
        vs = c1 - c0
        anchor = c0 + (x - self.PAD_L) / self._span_px() * vs
        new_vs = min(self.total, max(min(self.total, 5.0), vs * factor))
        frac = (anchor - c0) / vs if vs else 0
        v0 = min(max(0.0, anchor - frac * new_vs), self.total - new_vs)
        self._animate_view(v0, v0 + new_vs)

    def _zoom_anchor_x(self) -> float:
        if self.playhead is not None and self.view0 <= self.playhead <= self.view1:
            return self._x(self.playhead)  # như Premiere: phóng quanh vạch phát
        return self.PAD_L + self._span_px() / 2

    def zoom_in(self) -> None:
        if self.total:
            self._zoom_at(self._zoom_anchor_x(), 0.5)

    def zoom_out(self) -> None:
        if self.total:
            self._zoom_at(self._zoom_anchor_x(), 2.0)

    def fit(self) -> None:
        """Vừa khung: xem cả video."""
        if self.total:
            self._animate_view(0.0, self.total, 260)

    def _set_view(self, v0: float, v1: float) -> None:
        vs = min(self.total, max(min(self.total, 5.0), v1 - v0))
        v0 = min(max(0.0, v0), max(0.0, self.total - vs))
        self.view0, self.view1 = v0, v0 + vs
        self._sync_scrollbar()
        self.update()

    def _sync_scrollbar(self) -> None:
        sb = self.scrollbar
        vs = self.view1 - self.view0
        hi = int(round(max(0.0, self.total - vs) * 1000)) if self.total else 0
        sb.blockSignals(True)
        sb.setRange(0, hi)
        sb.setPageStep(max(1, int(round(vs * 1000))))
        sb.setSingleStep(max(1, int(round(vs * 100))))
        sb.setValue(int(round(self.view0 * 1000)))
        sb.blockSignals(False)
        if sb.parent() is not None:  # chỉ khi đã nằm trong cửa sổ (không bật thành cửa sổ riêng)
            sb.setVisible(hi > 0)

    def _on_scroll(self, value: int) -> None:
        if self._zoom_running():
            self._zoom_anim.stop()
        vs = self.view1 - self.view0
        self._set_view(value / 1000.0, value / 1000.0 + vs)

    def _zoom_running(self) -> bool:
        a = getattr(self, "_zoom_anim", None)
        return a is not None and a.state() == QVariantAnimation.State.Running

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._sync_scrollbar()

    def _animate_view(self, v0: float, v1: float, ms: int = 180) -> None:
        """Phóng to / thu nhỏ mượt tới khoảng [v0, v1]."""
        if getattr(self, "_zoom_anim", None) is None:
            self._zoom_anim = QVariantAnimation(self)
            self._zoom_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._zoom_anim.setStartValue(0.0)
            self._zoom_anim.setEndValue(1.0)
            self._zoom_anim.valueChanged.connect(self._on_zoom_step)
            self._zoom_anim.finished.connect(self.update)  # zoom xong: vẽ lại nét ở tỉ lệ mới
        self._zoom_anim.stop()
        self._zoom_from = (self.view0, self.view1)
        self._zoom_target = (v0, v1)
        self._zoom_anim.setDuration(ms)
        self._zoom_anim.start()

    def _on_zoom_step(self, k) -> None:
        k = float(k)
        (a0, a1), (b0, b1) = self._zoom_from, self._zoom_target
        self.view0, self.view1 = a0 + (b0 - a0) * k, a1 + (b1 - a1) * k
        self._sync_scrollbar()
        self.update()

    def set_playhead(self, t: float | None) -> None:
        if t != self.playhead:
            self.playhead = t
            if (t is not None and self.follow_playhead and self.total and not self._full_view(self.total)
                    and not self._scrub and self._drag is None and self._mv is None and self._hd is None):
                vs = self.view1 - self.view0
                if t > self.view1 - vs * 0.02 or t < self.view0:  # như Premiere: lật sang trang kế, vạch phát ở 10%
                    self._animate_view(max(0.0, t - vs * 0.1), max(0.0, t - vs * 0.1) + vs, 160)
            self.update()

    def _ruler_y(self) -> float:
        return self.TOP_V + self.LANE_V + 6 + self.LANE_M + 4

    def _on_scrub_zone(self, pos) -> bool:
        """Bấm trên thước giờ, hoặc ngay vạch phát → kéo để tua (không phải kéo khung nhìn)."""
        if not (self.seek_enabled and self.total and pos.x() >= self.PAD_L):
            return False
        if pos.y() >= self._ruler_y() - 2:
            return True
        if self.playhead is None or abs(self._x(self.playhead) - pos.x()) > 6:
            return False
        return self._movable_at(pos) is None  # trên khối kéo được: khối được ưu tiên (tua bằng thước giờ bên dưới)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self._on_scrub_zone(e.position()):
            self._scrub = True
            self._press = None
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self.seekRequested.emit(max(0.0, min(self.total, self._t(e.position().x()))))
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position()
        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)  # Shift + kéo = luôn là di chuyển khung nhìn
        left = e.button() == Qt.MouseButton.LeftButton
        if e.button() == Qt.MouseButton.MiddleButton and self.total and not self._full_view(self.total):
            self._start_pan(e.position().x())  # nút giữa chuột: kéo để trượt (như Premiere)
            return
        kind = self._which_handle(e.position()) if left and not shift else None
        if kind is not None:  # mép dải nhạc: kéo để nhạc chạy từ / tới clip khác (hít vào ranh giới clip)
            t = self._handle_t() if kind == "start" else self._end_handle_t()
            self._hd = {"kind": kind, "t0": t, "t": t, "n": self._handle_snap(self._x(t), kind)[1]}
            self._press = None
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self.update()
            return
        hit = self._movable_at(e.position()) if left and not shift else None
        if hit is not None:  # bấm vào khối: kéo quá vài px là kéo đổi chỗ (đang ngẫu nhiên thì thả xong sẽ hỏi)
            lane, k = hit
            x = e.position().x()
            self._mv = {"lane": lane, "block": k, "clip": self._blocks(lane)[k].clip, "x0": x, "x": x, "on": False,
                        "slot": None}
            return
        if e.button() == Qt.MouseButton.LeftButton and self.total and not self._full_view(self.total):
            self._start_pan(e.position().x())

    def _start_pan(self, x: float) -> None:
        if self._zoom_running():
            self._zoom_anim.stop()
        self._drag = (x, self.view0)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._scrub:
            self._scrub = False
            self.unsetCursor()
            return
        if self._hd is not None:
            hd, self._hd = self._hd, None
            self.unsetCursor()
            self.update()
            if abs(hd["t"] - hd["t0"]) > 1e-6:
                (self.musicStartRequested if hd["kind"] == "start" else self.musicEndRequested).emit(hd["n"])
            return
        if self._mv is not None and self._mv["on"]:
            self._press = None
            self._finish_drag()
            return
        self._mv = None
        press, self._press = self._press, None
        self._drag = None
        self.unsetCursor()
        if (press is not None and self.seek_enabled and self.total and e.button() == Qt.MouseButton.LeftButton
                and (e.position() - press).manhattanLength() < 4 and e.position().x() >= self.PAD_L):
            self.seekRequested.emit(max(0.0, min(self.total, self._t(e.position().x()))))

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        self.fit()

    def _hit_tip(self, pos) -> str:
        """Chú thích của khối dưới con trỏ (tính theo vị trí khối, không phụ thuộc dải vẽ sẵn)."""
        hit = self._block_at(pos)
        if hit is not None:
            return self._blocks(hit[0])[hit[1]].tip
        top, h = self._lane_y("m")
        if self.source and top <= pos.y() <= top + h:
            t = self._t(pos.x())
            s = next((s for s in self.source if s.start <= t <= s.end), None)
            if s is not None:
                return s.tip
        return ""

    def _tip(self, e, text: str) -> None:
        if text != self._tip_last or not QToolTip.isVisible():
            self._tip_last = text
            QToolTip.showText(e.globalPosition().toPoint(), text, self)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self.total:
            return
        if self._scrub:
            t = max(0.0, min(self.total, self._t(e.position().x())))
            self.set_playhead(t)
            self.seekRequested.emit(t)
            return
        if self._hd is not None:
            t, n = self._handle_snap(e.position().x(), self._hd["kind"])
            if t != self._hd["t"]:
                self._hd["t"], self._hd["n"] = t, n
                self.update()
            return
        hov = self._which_handle(e.position()) if self._drag is None else None
        if hov != self._hd_hover:
            self._hd_hover = hov
            self.update()
        if hov:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._tip(e, ("♪ Chỗ nhạc vào — kéo sang trái / phải để nhạc chạy từ clip khác"
                          if hov == "start" else "Chỗ nhạc dừng — kéo sang trái / phải để nhạc dừng ở hết clip khác")
                      + " (hít vào ranh giới clip; chuột phải khối clip cũng đặt được)")
            return
        if self._mv is not None:
            x = e.position().x()
            if not self._mv["on"] and abs(x - self._mv["x0"]) >= DRAG_PX:
                self._mv["on"] = True
                QToolTip.hideText()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._mv["on"]:
                self._move_drag(x)
            return
        if self._on_scrub_zone(e.position()):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif self._drag is None:
            mh = self._movable_at(e.position())
            if mh is not None:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
        if self._drag is not None:
            x0, v0 = self._drag
            vs = self.view1 - self.view0
            dt = (x0 - e.position().x()) / self._span_px() * vs
            self._set_view(v0 + dt, v0 + dt + vs)
            return
        pos = e.position()
        hit = self._hit_tip(pos)
        if hit:
            mh = self._movable_at(pos)
            if mh is not None:
                why = self._block_reason(mh[0])
                hit += ("\n" + why if why else "\nKéo sang trái / phải để đổi thứ tự trong bảng clip (Ctrl+Z để quay lại)"
                        if mh[0] == "v" else "\nKéo sang trái / phải để đổi thứ tự bài trong playlist")
            self._tip(e, hit)
        elif pos.x() >= self.PAD_L:
            self._tip(e, f"{fmt_dur(self._t(pos.x()))}\n"
                      + ("Bấm để xem trước từ chỗ này · " if self.seek_enabled else "")
                      + "Ctrl + lăn để phóng to / thu nhỏ · lăn để trượt ngang · kéo khối để đổi thứ tự · "
                      "nhấp đúp để xem toàn bộ")
        else:  # rê vào tên làn: giải thích làn đó
            self._tip(e, self._lane_tip(pos.y()))
