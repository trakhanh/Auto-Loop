"""Xen kẽ clip nền: nền ×N → cảnh 1 → nền ×N → cảnh 2 → … → nền ×N (dựng bảng clip tự động)."""
from __future__ import annotations

import os
import random
import re
import unicodedata
from dataclasses import dataclass, replace

from .project import ClipItem

# tên file có các từ này được coi là clip nền (vòng lặp chính)
BASE_WORDS = ("loop", "nen", "nền", "base", "bg", "background")


def natural_key(path: str):
    """clip2 đứng trước clip10; so theo tên file, không phân biệt hoa thường."""
    name = os.path.basename(path).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def _base_rank(path: str) -> int:
    """2 = tên có chữ loop, 1 = nen/bg/base/background, 0 = không phải clip nền.
    Tách cả theo số: nen1, bg01, 1loop, background2 đều nhận; tên tiếng Việt kiểu NFD (macOS) cũng nhận."""
    stem = unicodedata.normalize("NFC", os.path.splitext(os.path.basename(path))[0]).lower()
    words = [w for w in re.split(r"[^a-zà-ỹđ]+", stem) if w]
    if any(w.startswith("loop") for w in words):
        return 2
    return 1 if any(w in BASE_WORDS for w in words) else 0


def looks_like_base(path: str) -> bool:
    return _base_rank(path) > 0


def detect_base(clips: list[ClipItem]) -> int | None:
    """Chỉ số clip nền đoán theo tên: ưu tiên file xuất hiện nhiều lần nhất trong bảng, rồi video hơn ảnh
    (bg_logo.png không thắng loop_mua.mp4), rồi chữ "loop" hơn nen/bg, rồi file đứng trước."""
    cands = [i for i, c in enumerate(clips) if looks_like_base(c.path)]
    if not cands:
        return None
    counts: dict[str, int] = {}
    for c in clips:
        key = os.path.normcase(c.path)
        counts[key] = counts.get(key, 0) + 1

    def rank(i: int):
        p = clips[i].path
        return (counts[os.path.normcase(p)], os.path.splitext(p)[1].lower() not in IMAGE_EXT, _base_rank(p), -i)

    return max(cands, key=rank)


@dataclass
class InsertSpec:
    """Một cảnh chèn trong mẫu: xuất hiện mấy lần mỗi lượt mẫu, mỗi lần phát mấy lần."""
    path: str
    appear: int = 1
    plays: int = 1
    enabled: bool = True


@dataclass
class InterleaveOptions:
    base_index: int
    base_plays: tuple[str, int, int, float] = ("fixed", 70, 70, 0.0)  # (mode, lo, hi, giây nếu kiểu duration)
    insert_plays: int = 1
    order: str = "name"  # name | table | shuffle (khi không có `inserts`)
    start_with_base: bool = True
    end_with_base: bool = True
    seed: int = 1
    inserts: list[InsertSpec] | None = None  # thứ tự + số lần do người dùng chỉnh (ưu tiên hơn `order`)
    repeat: int = 1  # lặp lại cả mẫu (các cảnh chèn) bao nhiêu lượt
    reshuffle: bool = False  # mỗi lượt lặp xáo lại thứ tự cảnh


def unique_inserts(clips: list[ClipItem], base_index: int, order: str = "name", seed: int = 1,
                   include_off: bool = False) -> list[ClipItem]:
    """Các file cảnh chèn (mỗi file một lần, bỏ clip nền và — trừ khi `include_off` — clip đang tắt), xếp theo `order`."""
    seen = {os.path.normcase(clips[base_index].path)}
    on = {os.path.normcase(c.path) for c in clips if c.enabled}
    out: list[ClipItem] = []
    for c in clips:
        key = os.path.normcase(c.path)
        if key in seen or not c.enabled and (not include_off or key in on):
            continue
        seen.add(key)
        out.append(c)
    if order == "name":
        out.sort(key=lambda c: natural_key(c.path))
    elif order == "shuffle":
        random.Random(seed).shuffle(out)
    return out


def build(clips: list[ClipItem], opt: InterleaveOptions) -> list[ClipItem]:
    """Trả về danh sách clip mới: [nền] → cảnh → nền → cảnh … [→ nền], cả mẫu lặp `repeat` lượt.
    Mỗi file chỉ lấy một lần (bỏ các bản trùng cũ), giữ cài đặt cắt đoạn/crossfade của lần xuất hiện đầu tiên;
    clip đang tắt hoặc cảnh bị bỏ chọn được giữ lại ở cuối bảng (tắt) để không mất."""
    base = clips[opt.base_index]
    base_key = os.path.normcase(base.path)
    first: dict[str, ClipItem] = {}
    for c in clips:
        first.setdefault(os.path.normcase(c.path), c)
    if opt.inserts is None:
        specs = [InsertSpec(c.path, 1, opt.insert_plays) for c in unique_inserts(clips, opt.base_index, opt.order,
                                                                                opt.seed)]
    else:
        specs = [sp for sp in opt.inserts if os.path.normcase(sp.path) in first
                 and os.path.normcase(sp.path) != base_key]
    used = {os.path.normcase(sp.path) for sp in specs if sp.enabled and sp.appear > 0 and sp.plays > 0}
    kept_off = [replace(c, enabled=False) for k, c in first.items() if k != base_key and k not in used]

    mode, lo, hi, secs = opt.base_plays

    def base_copy() -> ClipItem:
        return replace(base, enabled=True, plays_mode=mode, count=lo, min=lo, max=hi, play_seconds=secs)

    def insert_copy(sp: InsertSpec) -> ClipItem:
        n = max(0, sp.plays)
        c = first[os.path.normcase(sp.path)]
        return replace(c, enabled=True, plays_mode="fixed", count=n, min=n, max=n, play_seconds=0.0)

    active = [sp for sp in specs if sp.enabled and sp.appear > 0 and sp.plays > 0]
    rng = random.Random(opt.seed)
    seq: list[InsertSpec] = []
    for r in range(max(1, opt.repeat)):
        round_specs = list(active)
        if opt.reshuffle and r > 0:
            rng.shuffle(round_specs)
            if seq and round_specs and len(round_specs) > 1 and round_specs[0].path == seq[-1].path:
                round_specs.append(round_specs.pop(0))  # tránh một cảnh phát 2 lần liền nhau giữa 2 lượt
        for sp in round_specs:
            seq += [sp] * sp.appear

    out: list[ClipItem] = []
    if opt.start_with_base:
        out.append(base_copy())
    for k, sp in enumerate(seq):
        out.append(insert_copy(sp))
        if k < len(seq) - 1 or opt.end_with_base:
            out.append(base_copy())
    if not out:
        out.append(base_copy())
    return out + kept_off
