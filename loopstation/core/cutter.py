"""Trang "Cắt video": chia video thành nhiều đoạn + xuất ảnh từ video (FFmpeg đi kèm).

Xem docs/superpowers/specs/2026-11-20-chia-video-xuat-khung-design.md. Phần này không dùng Qt: đọc thời gian gõ tay,
tính danh sách đoạn (5 cách), kích thước + filter đổi tỉ lệ, tham số FFmpeg, đặt tên không ghi đè, chạy thật."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

EPS = 1e-6
MIN_PIECE = 1.0  # đoạn ngắn hơn 1 giây thì bỏ (hoặc nhập vào đoạn trước)


# ---------- thời gian gõ tay ----------
def parse_time(text: str) -> float:
    """"00:01:15" / "1:15" / "75" / "00:01:15.5" (cả "75,5") → giây. Sai → ValueError (câu tiếng Việt)."""
    t = (text or "").strip()
    m = re.fullmatch(r"(\d+)(?::(\d+))?(?::(\d+))?(?:[.,](\d+))?", t)
    if not m:
        raise ValueError(f"Thời gian «{t}» sai")
    parts = [int(g) for g in m.groups()[:3] if g is not None]
    frac = float("0." + m.group(4)) if m.group(4) else 0.0
    if len(parts) == 3:
        h, mi, s = parts
        if mi >= 60 or s >= 60:
            raise ValueError(f"Thời gian «{t}» sai")
        return h * 3600 + mi * 60 + s + frac
    if len(parts) == 2:
        mi, s = parts
        if s >= 60:
            raise ValueError(f"Thời gian «{t}» sai")
        return mi * 60 + s + frac
    return parts[0] + frac


def _items(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,;\n]+", text or "") if x.strip()]


def parse_marks(text: str) -> list[float]:
    """"00:01:15, 00:05:30" (phẩy / chấm phẩy / xuống dòng) → [75, 330]. Ô trống → []."""
    out = []
    for item in _items(text):
        try:
            out.append(parse_time(item))
        except ValueError:
            raise ValueError(f"Mốc «{item}» sai") from None
    return out


def parse_ranges(text: str) -> list[tuple[float, float]]:
    """"00:01:10-00:01:45, 5:00 – 5:30" → [(70, 105), (300, 330)]. Đầu ≥ cuối hoặc gõ sai → ValueError."""
    out = []
    for item in _items(text):
        ab = re.split(r"\s*[-–—]\s*", item)
        if len(ab) != 2:
            raise ValueError(f"Khoảng «{item}» sai — gõ dạng 00:01:10-00:01:45")
        try:
            a, b = parse_time(ab[0]), parse_time(ab[1])
        except ValueError:
            raise ValueError(f"Khoảng «{item}» sai") from None
        if a >= b:
            raise ValueError(f"Khoảng «{item}» sai: đầu phải trước cuối")
        out.append((a, b))
    return out


def fmt_time(sec: float) -> str:
    s = max(0, int(sec + EPS))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


# ---------- danh sách đoạn ----------
@dataclass
class Segment:
    start: float
    dur: float


SPLIT_MODES = ("parts", "fixed", "random", "marks", "ranges")


@dataclass
class SplitSettings:
    mode: str = "fixed"
    parts: int = 2
    fixed: float = 30.0
    rmin: float = 10.0
    rmax: float = 45.0
    marks: str = ""
    ranges: str = ""
    exact: bool = True
    aspect: str = "keep"
    fit: str = "blur"
    per_video: bool = True
    open_after: bool = False


def _even(duration: float, n: int) -> list[Segment]:
    step = duration / n
    return [Segment(i * step, step) for i in range(n)]


def _random(duration: float, rmin: float, rmax: float, rng: random.Random) -> list[Segment]:
    out: list[Segment] = []
    t = 0.0
    while duration - t > EPS:
        rest = duration - t
        if rest <= rmax:
            d = rest
        else:
            hi = min(rmax, rest - rmin)  # phần còn lại sau đoạn này vẫn ≥ ngắn nhất
            if hi >= rmin:
                d = rng.uniform(rmin, hi)
            else:  # không chia được cho đủ dài: đoạn dài nhất, phần dư giữ riêng
                d = rmax
                if rest - d < MIN_PIECE:
                    d = rest
        out.append(Segment(t, d))
        t += d
    return out


def plan_segments(duration: float, s: SplitSettings, rng: random.Random | None = None) -> tuple[list[Segment], str]:
    """Danh sách đoạn cho một video + ghi chú (vàng) nếu app phải bỏ / đổi gì. Cài đặt sai → ValueError."""
    note = ""
    if duration <= EPS:
        raise ValueError("Video không có thời lượng")
    if s.mode == "parts":
        n = max(1, int(s.parts))
        if duration / n < MIN_PIECE:
            n = max(1, int(duration))
            note = f"Video dài {fmt_time(duration)} — chia tối đa {n} phần"
        return _even(duration, n), note
    if s.mode == "fixed":
        if s.fixed < MIN_PIECE:
            raise ValueError("Độ dài mỗi đoạn phải từ 1 giây")
        out = []
        t = 0.0
        while duration - t > EPS:
            d = min(s.fixed, duration - t)
            if d < MIN_PIECE and out:
                break
            out.append(Segment(t, d))
            t += d
        return out, note
    if s.mode == "random":
        if s.rmin < MIN_PIECE:
            raise ValueError("Đoạn ngắn nhất phải từ 1 giây")
        if s.rmin > s.rmax:
            raise ValueError("Khoảng ngẫu nhiên sai: số đầu phải nhỏ hơn số sau")
        return _random(duration, s.rmin, s.rmax, rng or random.Random()), note
    if s.mode == "marks":
        marks = parse_marks(s.marks)
        if not marks:
            raise ValueError("Chưa nhập mốc nào")
        outside = [m for m in marks if m <= EPS or m >= duration - EPS]
        cuts = sorted({round(m, 3) for m in marks if m not in outside})
        if outside:
            note = "Bỏ mốc ngoài video: " + ", ".join(fmt_time(m) for m in outside)
        edges = [0.0, *cuts, duration]
        return [Segment(a, b - a) for a, b in zip(edges, edges[1:])], note
    if s.mode == "ranges":
        ranges = parse_ranges(s.ranges)
        if not ranges:
            raise ValueError("Chưa nhập khoảng nào")
        out, skipped = [], []
        for a, b in ranges:
            if a >= duration - EPS:
                skipped.append(a)
                continue
            out.append(Segment(a, min(b, duration) - a))
        if not out:
            raise ValueError("Mọi khoảng đều nằm ngoài video")
        if skipped:
            note = "Bỏ khoảng ngoài video: " + ", ".join(fmt_time(a) for a in skipped)
        return out, note
    raise ValueError(f"Cách cắt không rõ: {s.mode}")
