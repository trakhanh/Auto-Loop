"""Mẫu bảng clip: lưu cả bảng (thứ tự dòng, số lần phát, nối loop, cắt đoạn…) theo VAI của file, không theo tên đầy đủ.

Vai = tên file bỏ số thứ tự ở đầu: "5_loopB.mp4" → "loopb", "12 - loopA.mov" → "loopa". Nhờ vậy một mẫu
"STT_loopB ×1 → STT_loopA ×57 → STT_loopB ×1 → STT_loopA ×1" dùng được cho video 5, video 6… (6_loopA, 6_loopB…).
"""
from __future__ import annotations

import os
import re
from dataclasses import fields

from .probe import IMAGE_EXTS
from .project import ClipItem

STT_RE = re.compile(r"^\s*\d+\s*[_\-.\s]+")  # "5_", "12 - ", "03." ở đầu tên
MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mts", ".m2ts", ".ts", ".wmv", ".flv"} | IMAGE_EXTS
_ROW_FIELDS = [f.name for f in fields(ClipItem) if f.name != "path"]


def role_of(path: str) -> str:
    """Vai của file: tên bỏ đuôi, bỏ số thứ tự ở đầu, chữ thường ("5_loopB.mp4" → "loopb")."""
    stem = os.path.splitext(os.path.basename(path))[0]
    rest = STT_RE.sub("", stem, count=1)
    return (rest or stem).strip().lower()


def role_label(path_or_role: str, sample: str = "") -> str:
    """Tên hiển thị của vai: "STT_loopB" (giữ chữ hoa / thường như file mẫu)."""
    base = os.path.splitext(os.path.basename(sample or path_or_role))[0]
    m = STT_RE.match(base)
    if m:
        return "STT" + m.group(0).strip(" ")[-1:].replace(" ", "_") + base[m.end():]
    return base


def from_clips(clips: list[ClipItem]) -> list[dict]:
    """Bảng hiện tại → các dòng của mẫu (vai + mọi thông số của dòng, trừ đường dẫn)."""
    rows = []
    for c in clips:
        row = {"role": role_of(c.path), "label": role_label(c.path)}
        row.update({k: getattr(c, k) for k in _ROW_FIELDS})
        rows.append(row)
    return rows


def roles(rows: list[dict]) -> list[str]:
    """Các vai khác nhau của mẫu, theo thứ tự xuất hiện."""
    out: list[str] = []
    for r in rows:
        if r.get("role") and r["role"] not in out:
            out.append(r["role"])
    return out


def stt_of(path: str) -> int | None:
    """Số thứ tự ở đầu tên file ("7_loopA.mp4" → 7); không có → None."""
    m = re.match(r"\s*(\d+)", os.path.splitext(os.path.basename(path))[0])
    return int(m.group(1)) if m and STT_RE.match(os.path.basename(path)) else None


def _natural(path: str) -> tuple:
    """Sắp theo số thứ tự thật (2 trước 10), file không có số ở cuối."""
    n = stt_of(path)
    return (n is None, n or 0, os.path.basename(path).lower())


def plan(rows: list[dict], paths: list[str]) -> tuple[list[tuple[dict, str, int | None]], list[str], list[int | None]]:
    """Dựng bảng theo mẫu cho MỌI số thứ tự có trong `paths`, nối tiếp (1 → 2 → … → 10) thành một video.
    → ([(dòng mẫu, file, STT)…], các vai thiếu file ("loopb" hoặc "7_loopb" khi nhiều STT), các STT đã dùng).
    File không có số ở đầu (Content.mp4…) dùng chung: lấp vai còn thiếu ở mọi số thứ tự."""
    groups: dict[int | None, dict[str, str]] = {}
    for p in sorted(paths, key=_natural):
        groups.setdefault(stt_of(p), {}).setdefault(role_of(p), p)
    need = roles(rows)
    shared = groups.get(None, {})
    numbered = [g for g in groups if g is not None and any(r in groups[g] for r in need)]
    used: list[int | None] = numbered or ([None] if any(r in shared for r in need) else [])
    out, missing = [], []
    for g in used:
        found = dict(shared, **groups.get(g, {})) if g is not None else shared
        for r in rows:
            path = found.get(r.get("role", ""))
            if path:
                out.append((r, path, g))
        missing += [m if len(used) < 2 or g is None else f"{g}_{m}" for m in need if m not in found]
    if not used:
        missing = list(need)
    return out, missing, used


def match(rows: list[dict], paths: list[str]) -> tuple[dict[str, str], list[str]]:
    """Vai → file của số thứ tự đầu tiên (xem nhanh) và các vai thiếu file."""
    items, missing, _used = plan(rows, paths)
    found: dict[str, str] = {}
    for r, path, _g in items:
        found.setdefault(r.get("role", ""), path)
    return found, missing


def build(rows: list[dict], paths: list[str]) -> tuple[list[ClipItem], list[str]]:
    """Dựng bảng clip từ mẫu cho các file `paths` → (bảng, các vai thiếu file). Dòng thiếu file bị bỏ.
    Nhiều số thứ tự (1_loopA … 10_loopB) → lặp mẫu cho từng số, nối tiếp thành một bảng."""
    items, missing, _used = plan(rows, paths)
    clips = []
    for r, path, _g in items:
        c = ClipItem(path)
        for k in _ROW_FIELDS:
            if k in r:
                try:
                    setattr(c, k, type(getattr(c, k))(r[k]))
                except (TypeError, ValueError):
                    pass
        clips.append(c)
    return clips, missing


def media_in(folder: str) -> list[str]:
    """File video / ảnh nằm thẳng trong thư mục (không vào thư mục con)."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return [os.path.join(folder, n) for n in sorted(names)
            if os.path.splitext(n)[1].lower() in MEDIA_EXTS and os.path.isfile(os.path.join(folder, n))]


def plays_text(r: dict) -> str:
    mode = r.get("plays_mode", "fixed")
    if mode == "duration":
        s = int(r.get("play_seconds", 0))
        return f"{s // 60} phút" if s % 60 == 0 and s >= 60 else f"{s} giây"
    if mode == "random":
        return f"×{r.get('min', 1)}–{r.get('max', 1)}"
    return f"×{r.get('count', 1)}"


def summary(rows: list[dict], limit: int = 8) -> str:
    """"STT_loopB ×1 → STT_loopA ×57 → STT_loopB ×1 → …" (để hiện trong danh sách mẫu)."""
    parts = [f"{r.get('label') or r.get('role')} {plays_text(r)}" for r in rows if r.get("enabled", True)]
    more = len(parts) - limit
    return " → ".join(parts[:limit]) + (f" → … (+{more} dòng)" if more > 0 else "")
