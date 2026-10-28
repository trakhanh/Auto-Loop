"""Xuất hàng loạt theo thư mục: mỗi thư mục con của thư mục cha = một video (hoặc một file nhạc ở kiểu Chỉ nhạc).

    Thư mục cha\\
      Video 01 - Mưa đêm\\   loop_mua.mp4, 2_canh.mp4, 3_canh.mp4 [, Nhac\\*.mp3]
      Video 02 - Rừng xanh\\ …

Mọi cài đặt khác (cấu hình xuất, intro/outro, tiếng nền, crossfade nhạc, độ dài…) lấy theo một dự án làm khuôn.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import interleave as il
from .probe import IMAGE_EXTS
from .project import ClipItem, MusicTrack, Project

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".mts",
              ".m2ts", ".wmv", ".flv", ".3gp"}
VISUAL_EXTS = VIDEO_EXTS | IMAGE_EXTS
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif"}
MUSIC_MODES = ("auto", "template", "folder")  # nhạc thư mục, thiếu thì khuôn | luôn khuôn | chỉ nhạc thư mục


@dataclass
class FolderJob:
    folder: str
    name: str
    clips: list[str] = field(default_factory=list)
    music: list[str] = field(default_factory=list)
    base: str | None = None  # clip nền nhận theo tên (loop…)
    error: str = ""
    notes: list[str] = field(default_factory=list)


SKIP_DIRS = {"$recycle.bin", "system volume information", "recovery", "windows", "program files",
             "program files (x86)", "programdata", "appdata"}


def _skip_dir(name: str) -> bool:
    return name.startswith((".", "_", "$")) or name.lower() in SKIP_DIRS


def is_drive_root(path: str) -> bool:
    p = os.path.abspath(path)
    return os.path.dirname(p) == p


def _files(folder: Path, exts: set[str]) -> list[str]:
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not _skip_dir(d))
        for f in files:
            if not f.startswith((".", "~")) and Path(f).suffix.lower() in exts and ".dang-xuat." not in f:
                out.append(os.path.join(root, f))
    return sorted(out, key=il.natural_key)


def scan(parent: str, music_only: bool = False) -> list[FolderJob]:
    """Mỗi thư mục con trực tiếp = một việc. Thư mục bắt đầu bằng "_" hoặc "." được bỏ qua (để chứa đồ dùng chung)."""
    root = Path(parent)
    jobs: list[FolderJob] = []
    if not parent or not root.is_dir() or is_drive_root(parent):  # cả ổ đĩa (D:\): không quét, tránh treo app
        return jobs
    subs = sorted((d for d in root.iterdir() if d.is_dir() and not _skip_dir(d.name)),
                  key=lambda d: il.natural_key(d.name))
    for d in subs:
        job = FolderJob(folder=str(d), name=d.name, clips=[] if music_only else _files(d, VISUAL_EXTS),
                        music=_files(d, AUDIO_EXTS))
        if music_only:
            if not job.music:
                job.error = "Không có file nhạc"
        elif not job.clips:
            job.error = "Không có video / ảnh"
        else:
            items = [ClipItem(p) for p in job.clips]
            b = il.detect_base(items)
            job.base = job.clips[b] if b is not None else None
            if job.base is None and len(job.clips) > 1:
                job.notes.append("Không có clip nền (tên chứa “loop”) — phát lần lượt theo tên")
        jobs.append(job)
    return jobs


def safe_name(name: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in " -_.()" else "_" for ch in name).strip(" .")
    return keep or "video"


def build_project(template: Project, job: FolderJob, music_mode: str = "auto",
                  arrange: Callable[[list[ClipItem], int], list[ClipItem]] | None = None,
                  loop_xfade: float = 1.0, next_xfade: float = 0.0,
                  clips_override: list[ClipItem] | None = None, source_audio: str | None = None,
                  base_override: str | None = None) -> Project:
    """Dự án cho một thư mục: sao chép khuôn rồi thay clip (và nhạc nếu thư mục có nhạc).
    `clips_override`: bảng clip người dùng đã chỉnh tay riêng cho thư mục này (bỏ qua mẫu xếp chung).
    `source_audio`: tiếng gốc clip cho cả loạt (mix = giữ + trộn nhạc, only = chỉ tiếng gốc, off = tắt; None = theo khuôn).
    `base_override`: clip nền người dùng chọn trong bảng chỉnh tay (nhận crossfade "Nối loop")."""
    p = copy.deepcopy(template)
    if source_audio in ("mix", "only", "off") and p.output_kind != "music_only":
        p.video.source_audio = source_audio
    p.name = job.name
    p.export.filename = safe_name(job.name)
    if p.output_kind != "music_only":
        base = base_override or job.base
        if clips_override is not None:
            clips = copy.deepcopy(clips_override)
            p.video.order = "list"  # bảng đã xếp tay: không xáo lại (khuôn để "Ngẫu nhiên" sẽ phá mẫu xen kẽ)
        else:
            clips = [ClipItem(path) for path in job.clips]
            base_i = next((i for i, c in enumerate(clips) if base and c.path == base), None)
            if arrange is not None and getattr(arrange, "kind", "") in ("sequence", "table"):
                clips = arrange(clips, -1)  # lần lượt từng loop / mẫu bảng clip: không cần clip nền
                p.video.order = "list"
            elif base_i is not None and arrange is not None:
                clips = arrange(clips, base_i)
                p.video.order = "list"
        seq = arrange is not None and getattr(arrange, "kind", "") == "sequence"
        table = clips_override is None and arrange is not None and getattr(arrange, "kind", "") == "table"
        for c in clips if not table else ():  # mẫu bảng clip: giữ nối loop / sang clip đã lưu trong mẫu  # crossfade chung của hộp thoại hàng loạt (áp cả cho bảng chỉnh tay)
            if (base and os.path.normcase(c.path) == os.path.normcase(base)) or (seq and il.looks_like_base(c.path)):
                c.loop_xfade = loop_xfade
            c.next_xfade = next_xfade
        p.video.clips = clips
    if music_mode == "template":
        pass
    elif job.music:
        p.music.tracks = [MusicTrack(m) for m in job.music]
    elif music_mode == "folder":
        p.music.tracks = []
    return p
