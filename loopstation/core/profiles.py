"""Hồ sơ kênh: mỗi kênh YouTube một bộ cài đặt dùng lại (intro / outro, màu & logo, âm thanh, thư mục nhạc, tiếng nền,
mẫu bảng clip, nơi lưu + chất lượng xuất). Chọn hồ sơ là áp cả bộ vào dự án đang làm — bảng clip giữ nguyên."""
from __future__ import annotations

import copy
import os
from dataclasses import asdict, fields
from pathlib import Path

from .project import AmbientLayer, ExportSettings, MusicTrack, Project

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
VIDEO_KEYS = ("intro", "intro_xfade", "outro", "outro_xfade", "bookend_audio", "fit", "source_audio", "source_volume",
              "music_volume", "source_level", "color_preset", "color_strength", "logo", "logo_opacity", "logo_pos",
              "logo_size", "look_bookends", "fade_out")
MUSIC_KEYS = ("order", "crossfade", "gap", "fade_in", "fade_out", "loudness_enabled", "lufs")
EXPORT_SKIP = ("filename",)  # tên file đổi theo từng video, không thuộc hồ sơ


def music_folder(proj: Project) -> str:
    """Thư mục chung của playlist (mọi bài cùng một thư mục) — hồ sơ nhớ thư mục để bài mới thêm sau cũng có."""
    dirs = {os.path.dirname(t.path) for t in proj.music.tracks}
    return dirs.pop() if len(dirs) == 1 else ""


def capture(name: str, proj: Project, table_preset: str = "") -> dict:
    """Lưu cài đặt của dự án đang mở thành hồ sơ kênh (không lưu clip / tên file)."""
    v, m = proj.video, proj.music
    folder = music_folder(proj)
    return {
        "name": name,
        "mode": proj.output_kind,
        "video": {k: getattr(v, k) for k in VIDEO_KEYS},
        "music": {k: getattr(m, k) for k in MUSIC_KEYS},
        "music_dir": folder,
        "tracks": [] if folder else [t.path for t in m.tracks if t.enabled],
        "ambient": [{"path": a.path, "enabled": a.enabled, "volume": a.volume} for a in m.ambient],
        "export": {k: v2 for k, v2 in asdict(proj.export).items() if k not in EXPORT_SKIP},
        "table_preset": table_preset,
    }


def audio_in(folder: str) -> list[str]:
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names
            if os.path.splitext(n)[1].lower() in AUDIO_EXTS and os.path.isfile(os.path.join(folder, n))]


def apply(profile: dict, proj: Project) -> tuple[Project, list[str]]:
    """Áp hồ sơ lên bản sao dự án: giữ bảng clip + tên file. Trả về (dự án mới, ghi chú — ví dụ file không còn)."""
    p = copy.deepcopy(proj)
    notes: list[str] = []
    p.output_kind = profile.get("mode", p.output_kind)
    for k, val in (profile.get("video") or {}).items():
        if k in VIDEO_KEYS:
            setattr(p.video, k, val)
    for key in ("intro", "outro", "logo"):
        path = getattr(p.video, key)
        if path and not os.path.isfile(path):
            notes.append(f"Không thấy file {key}: {path}")
            setattr(p.video, key, "")
    for k, val in (profile.get("music") or {}).items():
        if k in MUSIC_KEYS:
            setattr(p.music, k, val)
    folder = profile.get("music_dir") or ""
    if folder:
        files = audio_in(folder)
        if files:
            p.music.tracks = [MusicTrack(f) for f in files]
        else:
            notes.append(f"Thư mục nhạc không có bài nào (hoặc không còn): {folder}")
    elif profile.get("tracks"):
        keep = [t for t in profile["tracks"] if os.path.isfile(t)]
        p.music.tracks = [MusicTrack(t) for t in keep]
        if len(keep) < len(profile["tracks"]):
            notes.append(f"{len(profile['tracks']) - len(keep)} bài nhạc không còn trên máy")
    if "ambient" in profile:
        amb = [a for a in profile["ambient"] if os.path.isfile(a.get("path", ""))]
        p.music.ambient = [AmbientLayer(a["path"], bool(a.get("enabled", True)), int(a.get("volume", 50))) for a in amb]
    names = {f.name for f in fields(ExportSettings)}
    for k, val in (profile.get("export") or {}).items():
        if k in names and k not in EXPORT_SKIP:
            setattr(p.export, k, val)
    if p.export.output_dir and not os.path.isdir(p.export.output_dir):
        notes.append(f"Thư mục lưu không còn: {p.export.output_dir}")
    return p, notes


def describe(profile: dict) -> str:
    """Một dòng tóm tắt hồ sơ để hiện trong danh sách."""
    v, e = profile.get("video") or {}, profile.get("export") or {}
    bits = []
    ends = [x for x in ("intro", "outro") if v.get(x)]
    bits.append(" + ".join(x.capitalize() for x in ends) if ends else "không intro / outro")
    if v.get("logo"):
        bits.append("logo")
    if profile.get("music_dir"):
        bits.append(f"nhạc: {Path(profile['music_dir']).name}")
    elif profile.get("tracks"):
        bits.append(f"{len(profile['tracks'])} bài nhạc")
    if profile.get("table_preset"):
        bits.append(f"mẫu: {profile['table_preset']}")
    if e.get("resolution"):
        bits.append(str(e["resolution"]))
    if e.get("output_dir"):
        bits.append(f"lưu: {Path(e['output_dir']).name}")
    return " · ".join(bits)
