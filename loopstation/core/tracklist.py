"""Tạo tracklist dạng chapter YouTube."""
from __future__ import annotations

from pathlib import Path

from .planner import MusicItem


def fmt_ts(seconds: float, long: bool) -> str:
    s = int(seconds)
    if long:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


def title_of(path: str) -> str:
    return Path(path).stem


def build(items: list[MusicItem], paths: dict[int, str], total: float) -> tuple[str, list[str]]:
    """Trả về (nội dung, cảnh báo theo luật chapter YouTube)."""
    long = total >= 3600
    lines, warnings = [], []
    starts = []
    for it in items:
        # mốc chapter đặt ở giữa đoạn crossfade sẽ tự nhiên hơn, nhưng YouTube cần mốc đầu là 0
        lines.append(f"{fmt_ts(it.start, long)} {title_of(paths[it.track])}")
        starts.append(it.start)
    if len(lines) < 3:
        warnings.append("YouTube cần ít nhất 3 mốc để hiện chapter.")
    ends = starts[1:] + [total]
    if any(e - s < 10 for s, e in zip(starts, ends)):
        warnings.append("Có đoạn ngắn hơn 10 giây — YouTube có thể không hiện chapter.")
    return "\n".join(lines) + "\n", warnings
