"""Khoảng clip gõ tay ("5-10", "2-3, 7-8", "5-" = từ 5 tới hết) ↔ danh sách bật / tắt theo dòng — dùng cho "Nhạc ở clip"."""
from __future__ import annotations

import re

_ALL = ("tất cả", "tat ca", "all", "*")


def parse_ranges(text: str, n: int) -> list[bool] | None:
    """Số thứ tự dòng (bắt đầu từ 1) → n giá trị bật / tắt. Ô trống = không dòng nào. Gõ sai / số quá n → None."""
    t = text.strip().lower()
    if t in _ALL:
        return [True] * n
    out = [False] * n
    t = re.sub(r"\s*[-–—]\s*", "-", t)  # "5 - 10", "6–7" → "5-10", "6-7"
    for part in re.split(r"[,;\s]+", t):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(-(\d*))?", part)
        if not m:
            return None
        a = int(m.group(1))
        b = a if m.group(2) is None else (int(m.group(3)) if m.group(3) else n)  # "5-" = từ 5 tới hết
        if a < 1 or b > n or a > b:
            return None
        for k in range(a - 1, b):
            out[k] = True
    return out


def ranges_text(flags: list[bool], prefix: str = "Clip ") -> str:
    """[F, F, F, F, T, T] → "Clip 5–6"; tất cả → "Tất cả clip"; không dòng nào → "Không clip nào"."""
    if flags and all(flags):
        return "Tất cả clip"
    spans = _spans(flags)
    if not spans:
        return "Không clip nào"
    return prefix + ", ".join(f"{a}–{b}" if b > a else f"{a}" for a, b in spans)


def ranges_input(flags: list[bool]) -> str:
    """Như ranges_text nhưng để điền vào ô gõ: "2-3, 7-8" (trống khi không dòng nào)."""
    return ", ".join(f"{a}-{b}" if b > a else f"{a}" for a, b in _spans(flags))


def _spans(flags: list[bool]) -> list[tuple[int, int]]:
    spans, start = [], None
    for k, on in enumerate(list(flags) + [False]):
        if on and start is None:
            start = k + 1
        elif not on and start is not None:
            spans.append((start, k))
            start = None
    return spans
