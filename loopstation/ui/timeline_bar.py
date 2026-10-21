"""Thanh dòng thời gian trực quan: hiển thị cấu trúc các khối Hình, Âm thanh (nhạc / tiếng gốc) và Tiếng nền.

- Cùng một file luôn cùng một màu (clip nền xuất hiện nhiều lần dễ nhận ra).
- Clip rất ngắn so với tổng thời lượng (ví dụ cảnh 10 giây giữa các đoạn loop 10 phút) vẫn được vẽ thành
  vạch có nhãn số, không bị mất.
- Lăn chuột để phóng to / thu nhỏ quanh con trỏ, kéo để di chuyển, nhấp đúp để xem toàn bộ.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from fractions import Fraction

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..core import planner
from . import icons
from .widgets import fmt_dur

PALETTE = ["#7c5cff", "#10b981", "#f59e0b", "#ec4899", "#3b82f6", "#06b6d4", "#84cc16", "#f97316",
           "#8b5cf6", "#14b8a6"]
BOOKEND = "#64748b"
MUSIC = ["#3b5bdb", "#2b6cb0", "#4c51bf", "#2c7a7b"]
SOURCE = "#334155"
MARK_W = 7.0  # bề rộng tối thiểu (px) của clip quá ngắn
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


def short_label(name: str) -> str:
    m = re.match(r"\s*(\d+)", name)
    if m:
        return m.group(1)
    return name[:3]


class TimelineBar(QWidget):
    seekRequested = Signal(float)  # bấm (không kéo) vào dòng thời gian khi cửa sổ Xem trước đang mở
    LANE_V, LANE_M = 28, 20
    PAD_L, PAD_R = 116, 12
    TOP_V = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(90)
        self.setMaximumHeight(94)
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
        self.note = "Kéo thả video hoặc nhạc vào dự án để xem trước dòng thời gian trực quan"

    # ---------- dữ liệu ----------
    def set_timeline(self, tl, clip_names: list[str], track_names: list[str]) -> None:
        if self._zoom_running():  # dữ liệu mới: dừng hiệu ứng phóng to dở dang
            self._zoom_anim.stop()
        self.video, self.music, self.source = [], [], []
        self.music_only = False
        if tl is None or not tl.ok or not tl.total:
            self.total = 0.0
            self.note = ("Chưa tính được dòng thời gian — kiểm tra lại cài đặt"
                         if tl is not None else "Kéo thả video hoặc nhạc vào dự án để xem trước dòng thời gian trực quan")
            self.update()
            return
        old_total = self.total
        self.total = tl.total
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
        self.update()

    @staticmethod
    def _len_txt(sec: float) -> str:
        return f"{sec:.1f} giây" if sec < 60 else fmt_dur(sec)

    def _full_view(self, total: float) -> bool:
        return self.view0 <= 1e-6 and self.view1 >= total - 1e-6

    # ---------- toạ độ ----------
    def _span_px(self) -> float:
        return max(10.0, self.width() - self.PAD_L - self.PAD_R)

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
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.35)
        w, h = self.width(), self.height()
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 10, 10)
        p.fillPath(bg, QColor("#121621"))
        p.setPen(QPen(QColor("#242b3d"), 1))
        p.drawPath(bg)
        self._hits = []

        small = QFont(self.font())
        small.setPointSize(max(8, small.pointSize() - 1))
        bold = QFont(small)
        bold.setBold(True)
        tiny = QFont(small)
        tiny.setPointSize(max(7, small.pointSize() - 1))
        tiny.setBold(True)

        if not self.total:
            p.setFont(small)
            p.setPen(QColor("#78839e"))
            pm = icons.pixmap("timeline", 15, "#68728a")
            tw = p.fontMetrics().horizontalAdvance(self.note)
            start_x = max(16.0, (w - (tw + 24)) / 2.0)
            p.drawPixmap(int(start_x), int((h - 15) / 2), pm)
            p.drawText(QRectF(start_x + 22, 0, w - start_x - 28, h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.note)
            return

        top_v = self.TOP_V
        top_m = top_v + self.LANE_V + 6
        track_w = self._span_px()
        audio_lane_name = self._audio_lane_name()

        p.setFont(bold)
        p.setPen(QColor("#8c96b0"))
        p.drawPixmap(10, int(top_v + (self.LANE_V - 13) / 2), icons.pixmap("film", 13, "#8c96b0"))
        p.drawText(QRectF(27, top_v, self.PAD_L - 30, self.LANE_V),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "CLIP")
        p.drawPixmap(10, int(top_m + (self.LANE_M - 13) / 2), icons.pixmap("music", 13, "#8c96b0"))
        p.drawText(QRectF(27, top_m, self.PAD_L - 30, self.LANE_M),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, audio_lane_name)

        for y_lane, h_lane in ((top_v, self.LANE_V), (top_m, self.LANE_M)):
            slot = QPainterPath()
            slot.addRoundedRect(QRectF(self.PAD_L, y_lane, track_w, h_lane), 6, 6)
            p.fillPath(slot, QColor("#0b0d13"))

        p.save()
        p.setClipRect(QRectF(self.PAD_L, 0, track_w, h))
        p.setFont(small)
        if self.video:
            self._draw_lane(p, self.video, top_v, self.LANE_V, small, tiny, gradient=True)
        else:
            p.setPen(QColor("#525a70"))
            msg = "Chế độ Chỉ nhạc — không dùng hình ảnh" if self.music_only else "Chưa có clip video"
            p.drawText(QRectF(self.PAD_L + 10, top_v, track_w - 20, self.LANE_V),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, msg)

        if self.music:
            self._draw_lane(p, self.music, top_m, self.LANE_M, small, tiny, gradient=False)
        elif self.source:
            self._draw_source(p, top_m, small)
        else:
            p.setPen(QColor("#525a70"))
            p.drawText(QRectF(self.PAD_L + 10, top_m, track_w - 20, self.LANE_M),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "Chỉ có tiếng nền" if self.ambient else
                       "Chưa có nhạc · tiếng gốc của clip đang tắt (bật ở thẻ Khung & Tiếng, trang Video)" if self.source_off
                       else "Không có âm thanh (chưa có nhạc, clip không có tiếng gốc)")
        if self.playhead is not None and self.view0 <= self.playhead <= self.view1:
            x = self._x(self.playhead)
            p.setPen(QPen(QColor("#f8fafc"), 2))
            p.drawLine(QPointF(x, top_v - 4), QPointF(x, top_m + self.LANE_M + 2))
            head = QPainterPath()
            head.moveTo(x - 5, top_v - 7)
            head.lineTo(x + 5, top_v - 7)
            head.lineTo(x, top_v - 1)
            head.closeSubpath()
            p.fillPath(head, QColor("#f8fafc"))
        p.restore()
        self._draw_ruler(p, top_m + self.LANE_M + 4, small, bold)
        if self.playhead is not None and self.view0 <= self.playhead <= self.view1:
            # tay nắm vạch phát trên thước giờ (kéo để tua, như CapCut / Premiere)
            x = self._x(self.playhead)
            ry = top_m + self.LANE_M + 4
            knob = QPainterPath()
            knob.addRoundedRect(QRectF(x - 5, ry + 1, 10, max(8.0, h - ry - 4)), 3, 3)
            p.fillPath(knob, QColor("#f8fafc"))
            p.setPen(QPen(QColor("#f8fafc"), 2))
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
                p.setPen(QColor("white"))
                p.drawText(vis.adjusted(indent, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           fm.elidedText(disp, Qt.TextElideMode.ElideRight, int(vis.width() - indent - 4)))
            elif vis.width() > 14:
                p.setFont(tiny)
                p.setPen(QColor("white"))
                p.drawText(vis, Qt.AlignmentFlag.AlignCenter, b.short)
        # clip quá ngắn: vạch nổi có viền + nhãn số phía trên các khối dài
        p.setFont(tiny)
        fm = p.fontMetrics()
        for r, b in shorts:
            path = QPainterPath()
            path.addRoundedRect(r, 2.5, 2.5)
            p.fillPath(path, QColor(b.color).lighter(115))
            p.setPen(QPen(QColor("#f8fafc"), 1.2))
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
            p.fillPath(bp, QColor("#0b0d13"))
            p.setPen(QPen(QColor(b.color).lighter(130), 1.2))
            p.drawPath(bp)
            p.setPen(QColor("#f8fafc"))
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
            p.fillPath(path, QBrush(QColor(255, 255, 255, 18), Qt.BrushStyle.BDiagPattern))
            self._hits.append((r, s.tip))
            vis = r.intersected(QRectF(self.PAD_L, top, self._span_px(), self.LANE_M))
            if vis.width() > 110:
                p.setPen(QColor("#cbd5e1"))
                p.drawText(vis.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           "Tiếng gốc của clip")

    def _draw_ruler(self, p: QPainter, y: float, small, bold) -> None:
        h = self.height()
        track_w = self._span_px()
        vs = max(1e-6, self.view1 - self.view0)
        step = next((s for s in NICE_STEPS if track_w * s / vs >= 95), NICE_STEPS[-1])
        p.setFont(small)
        fm = p.fontMetrics()
        zoomed = not self._full_view(self.total)
        right_label = (f"{fmt_dur(self.view0)} – {fmt_dur(self.view1)} / {fmt_dur(self.total)}"
                       if zoomed else fmt_dur(self.total))
        if self.ambient:
            right_label = f"{self.ambient} lớp tiếng nền  ·  " + right_label
        p.setFont(bold)
        right_w = p.fontMetrics().horizontalAdvance(right_label) + 4
        right_x = self.PAD_L + track_w - right_w
        p.setPen(QColor("#eef1f8"))
        p.drawText(QRectF(right_x, y, right_w, h - y - 2), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   right_label)
        p.setFont(small)
        t = (self.view0 // step) * step
        while t <= self.view1 + 1e-6:
            x = self._x(t)
            if x >= self.PAD_L - 0.5:
                p.setPen(QPen(QColor("#2b3346"), 1))
                p.drawLine(QPointF(x, y - 3), QPointF(x, y))
                label = fmt_dur(t)
                lw = fm.horizontalAdvance(label)
                lx = max(self.PAD_L, x - lw / 2)
                if lx + lw < right_x - 8:
                    p.setPen(QColor("#8c96b0"))
                    p.drawText(QRectF(lx, y, lw + 2, h - y - 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                               label)
            t += step

    # ---------- tương tác ----------
    def wheelEvent(self, e) -> None:  # noqa: N802
        if not self.total:
            return super().wheelEvent(e)
        x = e.position().x()
        if x < self.PAD_L:
            x = self.PAD_L
        # tính từ đích đang tới (lăn liên tục vẫn mượt), neo tại vị trí con trỏ
        c0, c1 = self._zoom_target if self._zoom_running() else (self.view0, self.view1)
        vs = c1 - c0
        anchor = c0 + (x - self.PAD_L) / self._span_px() * vs
        factor = 0.8 ** (e.angleDelta().y() / 120.0)
        new_vs = min(self.total, max(min(self.total, 5.0), vs * factor))
        frac = (anchor - c0) / vs if vs else 0
        v0 = anchor - frac * new_vs
        v0 = min(max(0.0, v0), self.total - new_vs)
        self._animate_view(v0, v0 + new_vs)
        e.accept()

    def _zoom_running(self) -> bool:
        a = getattr(self, "_zoom_anim", None)
        return a is not None and a.state() == QVariantAnimation.State.Running

    def _animate_view(self, v0: float, v1: float, ms: int = 180) -> None:
        """Phóng to / thu nhỏ mượt tới khoảng [v0, v1]."""
        if getattr(self, "_zoom_anim", None) is None:
            self._zoom_anim = QVariantAnimation(self)
            self._zoom_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._zoom_anim.setStartValue(0.0)
            self._zoom_anim.setEndValue(1.0)
            self._zoom_anim.valueChanged.connect(self._on_zoom_step)
        self._zoom_anim.stop()
        self._zoom_from = (self.view0, self.view1)
        self._zoom_target = (v0, v1)
        self._zoom_anim.setDuration(ms)
        self._zoom_anim.start()

    def _on_zoom_step(self, k) -> None:
        k = float(k)
        (a0, a1), (b0, b1) = self._zoom_from, self._zoom_target
        self.view0, self.view1 = a0 + (b0 - a0) * k, a1 + (b1 - a1) * k
        self.update()

    def set_playhead(self, t: float | None) -> None:
        if t != self.playhead:
            self.playhead = t
            self.update()

    def _ruler_y(self) -> float:
        return self.TOP_V + self.LANE_V + 6 + self.LANE_M + 4

    def _on_scrub_zone(self, pos) -> bool:
        """Bấm trên thước giờ, hoặc ngay vạch phát → kéo để tua (không phải kéo khung nhìn)."""
        if not (self.seek_enabled and self.total and pos.x() >= self.PAD_L):
            return False
        if pos.y() >= self._ruler_y() - 2:
            return True
        return self.playhead is not None and abs(self._x(self.playhead) - pos.x()) <= 6

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self._on_scrub_zone(e.position()):
            self._scrub = True
            self._press = None
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self.seekRequested.emit(max(0.0, min(self.total, self._t(e.position().x()))))
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position()
        if e.button() == Qt.MouseButton.LeftButton and self.total and not self._full_view(self.total):
            if self._zoom_running():
                self._zoom_anim.stop()
            self._drag = (e.position().x(), self.view0)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._scrub:
            self._scrub = False
            self.unsetCursor()
            return
        press, self._press = self._press, None
        self._drag = None
        self.unsetCursor()
        if (press is not None and self.seek_enabled and self.total and e.button() == Qt.MouseButton.LeftButton
                and (e.position() - press).manhattanLength() < 4 and e.position().x() >= self.PAD_L):
            self.seekRequested.emit(max(0.0, min(self.total, self._t(e.position().x()))))

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        if self.total:
            self._animate_view(0.0, self.total, 260)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self.total:
            return
        if self._scrub:
            t = max(0.0, min(self.total, self._t(e.position().x())))
            self.set_playhead(t)
            self.seekRequested.emit(t)
            return
        if self._on_scrub_zone(e.position()):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif self._drag is None:
            self.unsetCursor()
        if self._drag is not None:
            x0, v0 = self._drag
            vs = self.view1 - self.view0
            dt = (x0 - e.position().x()) / self._span_px() * vs
            nv = min(max(0.0, v0 + dt), self.total - vs)
            self.view0, self.view1 = nv, nv + vs
            self.update()
            return
        pos = e.position()
        hit = None
        for r, tip in reversed(self._hits):  # vạch / nhãn ngắn vẽ sau nên ưu tiên
            if r.contains(pos):
                hit = tip
                break
        if hit:
            QToolTip.showText(e.globalPosition().toPoint(), hit, self)
        elif pos.x() >= self.PAD_L:
            QToolTip.showText(e.globalPosition().toPoint(),
                              f"{fmt_dur(self._t(pos.x()))}\n"
                              + ("Bấm để xem trước từ chỗ này · " if self.seek_enabled else "")
                              + "Lăn chuột để phóng to · kéo để di chuyển · nhấp đúp để xem toàn bộ", self)
        else:  # rê vào tên làn: giải thích làn đó
            QToolTip.showText(e.globalPosition().toPoint(), self._lane_tip(pos.y()), self)
