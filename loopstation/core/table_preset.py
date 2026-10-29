"""Mẫu bảng clip: lưu cả bảng (thứ tự dòng, số lần phát, nối loop, cắt đoạn…) theo VAI của file, không theo tên đầy đủ.

Vai = tên file bỏ số thứ tự ở đầu: "5_loopB.mp4" → "loopb", "12 - loopA.mov" → "loopa". Nhờ vậy một mẫu
"STT_loopB ×1 → STT_loopA ×57 → STT_loopB ×1 → STT_loopA ×1" dùng được cho video 5, video 6… (6_loopA, 6_loopB…).
Tên có hai số ở đầu là Tập_STT_Vai: "33_4_LOOP A.mp4" → tập 33, tình huống 4, vai "loopa" (bỏ qua hoa / thường,
dấu cách, "_", "-"). Mỗi tập là một video riêng.
"""
from __future__ import annotations

import os
import re
from dataclasses import fields

from .probe import IMAGE_EXTS
from .project import ClipItem

NUMS_RE = re.compile(r"^\s*(\d+)\s*[_\-.\s]+(?:(\d+)\s*[_\-.\s]+)?")  # "5_", "12 - " (STT) hoặc "33_4_" (tập + STT)
SEP_RE = re.compile(r"[\s_\-.]+")
MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mts", ".m2ts", ".ts", ".wmv", ".flv"} | IMAGE_EXTS
_ROW_FIELDS = [f.name for f in fields(ClipItem) if f.name != "path"]


def _parts(path: str) -> tuple[int | None, int | None, str]:
    """(tập, STT, phần tên còn lại): "33_4_LOOP A.mp4" → (33, 4, "LOOP A"), "5_loopB.mp4" → (None, 5, "loopB")."""
    stem = os.path.splitext(os.path.basename(path))[0]
    m = NUMS_RE.match(stem)
    if not m or not stem[m.end():].strip():
        return None, None, stem
    if m.group(2):
        return int(m.group(1)), int(m.group(2)), stem[m.end():]
    return None, int(m.group(1)), stem[m.end():]


def norm_role(role: str) -> str:
    """"LOOP A" = "loopA" = "loop_a" = "Loop-A" → "loopa"."""
    return SEP_RE.sub("", role).lower()


def role_of(path: str) -> str:
    """Vai của file: tên bỏ đuôi, bỏ số tập / số thứ tự ở đầu ("5_loopB.mp4", "33_4_LOOP B.mp4" → "loopb")."""
    return norm_role(_parts(path)[2])


def role_label(path_or_role: str, sample: str = "") -> str:
    """Tên hiển thị của vai: "STT_loopB" (giữ chữ hoa / thường như file mẫu)."""
    base = os.path.splitext(os.path.basename(sample or path_or_role))[0]
    _ep, stt, rest = _parts(base)
    return f"STT_{rest.strip()}" if stt is not None else base


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
        k = _row_role(r)
        if k and k not in out:
            out.append(k)
    return out


def _row_role(r: dict) -> str:
    return norm_role(str(r.get("role", "")))  # mẫu lưu từ bản cũ có thể còn "loop_a", "loop a"


def stt_of(path: str) -> int | None:
    """Số thứ tự (tình huống) ở đầu tên file ("7_loopA.mp4" → 7, "33_4_LOOP A.mp4" → 4); không có → None."""
    return _parts(path)[1]


def episode_of(path: str) -> int | None:
    """Số tập: tên có hai số ở đầu ("33_4_LOOP A.mp4" → 33); không có → None."""
    return _parts(path)[0]


def episodes(paths: list[str]) -> list[int]:
    """Các số tập có trong `paths`, tăng dần."""
    return sorted({e for e in map(episode_of, paths) if e is not None})


def in_episode(path: str, ep: int) -> bool:
    """File thuộc tập `ep` — file không đánh số (Content.mp4…) dùng chung cho mọi tập."""
    return episode_of(path) == ep or stt_of(path) is None


def by_episode(paths: list[str]) -> dict[int, list[str]]:
    """Tập → các file của tập đó (kèm file dùng chung). Rỗng khi tên file không có số tập."""
    return {ep: [p for p in paths if in_episode(p, ep)] for ep in episodes(paths)}


def _natural(path: str) -> tuple:
    """Sắp theo số tập rồi số thứ tự thật (2 trước 10), file không có số ở cuối."""
    ep, n, _rest = _parts(path)
    return (n is None, ep or 0, n or 0, os.path.basename(path).lower())


def plan(rows: list[dict], paths: list[str], episode: int | None = None
         ) -> tuple[list[tuple[dict, str, int | None]], list[str], list[int | None]]:
    """Dựng bảng theo mẫu cho MỌI số thứ tự có trong `paths`, nối tiếp (1 → 2 → … → 10) thành một video.
    → ([(dòng mẫu, file, STT)…], các vai thiếu file ("loopb", "7_loopb" khi nhiều STT, "33_7_loopb" khi có số tập),
    các STT đã dùng). File không có số ở đầu (Content.mp4…) dùng chung: lấp vai còn thiếu ở mọi số thứ tự.
    Tên có số tập (33_4_LOOP A): chỉ dùng file của tập `episode` (mặc định tập nhỏ nhất) — mỗi tập một video."""
    eps = episodes(paths)
    if eps:
        episode = episode if episode in eps else eps[0]
        paths = [p for p in paths if in_episode(p, episode)]
    else:
        episode = None
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
            path = found.get(_row_role(r))
            if path:
                out.append((r, path, g))
        missing += [m if (len(used) < 2 and episode is None) or g is None
                    else f"{g}_{m}" if episode is None else f"{episode}_{g}_{m}" for m in need if m not in found]
    if not used:
        missing = list(need)
    return out, missing, used


def match(rows: list[dict], paths: list[str]) -> tuple[dict[str, str], list[str]]:
    """Vai → file của số thứ tự đầu tiên (xem nhanh) và các vai thiếu file."""
    items, missing, _used = plan(rows, paths)
    found: dict[str, str] = {}
    for r, path, _g in items:
        found.setdefault(_row_role(r), path)
    return found, missing


def missing_names(rows: list[dict], missing: list[str], paths: list[str] = ()) -> list[str]:
    """Viết lại vai thiếu như tên file: "loopb" → "STT_loopB", "7_loopb" → "7_loopB", "33_7_loopb" → "33_7_LOOP B"
    (theo cách viết của các file đang có trong `paths`, không có thì theo mẫu)."""
    labels = {_row_role(r): str(r.get("label") or r.get("role", "")) for r in rows}
    for p in paths:
        ep, stt, rest = _parts(p)
        if stt is not None and norm_role(rest) in labels:
            labels[norm_role(rest)] = "STT_" + rest.strip()
    out = []
    for m in missing:
        prefix, _, role = m.rpartition("_")
        lab = labels.get(role, role)
        out.append(f"{prefix}_{lab.removeprefix('STT_')}" if prefix else lab)
    return out


def build(rows: list[dict], paths: list[str], episode: int | None = None) -> tuple[list[ClipItem], list[str]]:
    """Dựng bảng clip từ mẫu cho các file `paths` → (bảng, các vai thiếu file). Dòng thiếu file bị bỏ.
    Nhiều số thứ tự (1_loopA … 10_loopB) → lặp mẫu cho từng số, nối tiếp thành một bảng.
    Tên có số tập (33_4_LOOP A): chỉ tập `episode` (mặc định tập nhỏ nhất)."""
    items, missing, _used = plan(rows, paths, episode)
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
