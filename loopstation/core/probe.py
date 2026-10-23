"""Đọc thông tin media bằng ffprobe (có cache trong bộ nhớ)."""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from fractions import Fraction

from . import ffmpeg_tools as ft

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass
class MediaInfo:
    path: str
    duration: float = 0.0
    has_video: bool = False
    width: int = 0
    height: int = 0
    fps: Fraction = Fraction(0)
    nb_frames: int | None = None
    has_audio: bool = False
    is_image: bool = False  # ảnh tĩnh: thời lượng lấy từ cài đặt, không từ file
    error: str | None = None
    # hệ màu ghi trong file ("" = không ghi) — clip HD không ghi thì coi là bt709, không để ffmpeg tự đổi
    color_space: str = ""
    color_primaries: str = ""
    color_transfer: str = ""
    color_range: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None

    def fps_text(self) -> str:
        if not self.fps:
            return "?"
        f = float(self.fps)
        return f"{f:.3f}".rstrip("0").rstrip(".")


_cache: dict[tuple, MediaInfo] = {}
_lock = threading.Lock()


def _key(path: str) -> tuple:
    st = os.stat(path)
    return (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns)


def cold_keys(paths) -> dict[tuple, str]:
    """Các file chưa có trong bộ nhớ đệm probe (key → path). File không tồn tại không tính: probe() trả lỗi ngay."""
    out: dict[tuple, str] = {}
    for p in paths:
        try:
            k = _key(p)
        except OSError:
            continue
        with _lock:
            hit = k in _cache
        if not hit:
            out[k] = p
    return out


def _parse_rate(text: str | None) -> Fraction:
    if not text or text in ("0/0", "0"):
        return Fraction(0)
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


def probe(path: str) -> MediaInfo:
    try:
        key = _key(path)
    except OSError:
        return MediaInfo(path=path, error="Không tìm thấy file")
    with _lock:
        if key in _cache:
            return _cache[key]
    info = _probe_uncached(path)
    if info.ok:
        with _lock:
            _cache[key] = info
    return info


def _rotation(stream: dict) -> int:
    """Góc xoay hiển thị (0/90/180/270) từ side data (Display Matrix) hoặc thẻ rotate kiểu cũ."""
    rot = 0.0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rot = float(sd["rotation"])
            except (TypeError, ValueError):
                pass
    tag = (stream.get("tags") or {}).get("rotate")
    if not rot and tag:
        try:
            rot = float(tag)
        except (TypeError, ValueError):
            pass
    return int(round(rot)) % 360


def _probe_uncached(path: str) -> MediaInfo:
    info = MediaInfo(path=path, is_image=os.path.splitext(path)[1].lower() in IMAGE_EXTS)
    try:
        r = ft.run([ft.ffprobe(), "-v", "error", "-print_format", "json",
                    "-show_format", "-show_streams", path], timeout=60)
    except Exception as e:  # noqa: BLE001
        info.error = str(e)
        return info
    if r.returncode != 0:
        info.error = (r.stderr.strip().splitlines() or ["ffprobe lỗi"])[-1]
        return info
    data = json.loads(r.stdout or "{}")
    fmt_dur = float(data.get("format", {}).get("duration", 0) or 0)
    v_dur = 0.0
    for s in data.get("streams", []):
        kind = s.get("codec_type")
        disposition = s.get("disposition", {})
        if kind == "video" and not info.has_video and not disposition.get("attached_pic"):
            info.has_video = True
            info.width = int(s.get("width", 0))
            info.height = int(s.get("height", 0))
            for f in ("color_space", "color_primaries", "color_transfer", "color_range"):
                val = str(s.get(f, "") or "")
                setattr(info, f, "" if val in ("unknown", "unspecified", "reserved") else val)
            if _rotation(s) in (90, 270):  # ffmpeg tự xoay khi giải mã → kích thước hiển thị đổi chiều
                info.width, info.height = info.height, info.width
            fps = _parse_rate(s.get("avg_frame_rate"))
            if not fps or fps > 240:
                fps = _parse_rate(s.get("r_frame_rate"))
            info.fps = fps
            if s.get("nb_frames", "").isdigit():
                info.nb_frames = int(s["nb_frames"])
            v_dur = float(s.get("duration", 0) or 0)
        elif kind == "audio" and not info.has_audio:
            info.has_audio = True
    info.duration = v_dur or fmt_dur
    if info.is_image:
        info.duration, info.nb_frames, info.fps, info.has_audio = 0.0, None, Fraction(0), False
        if not info.has_video:
            info.error = "Không đọc được ảnh"
        return info
    if info.duration <= 0:
        info.error = "Không đọc được thời lượng"
    return info


def probe_many(paths: list[str]) -> list[MediaInfo]:
    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(probe, paths))


def frames_at(info: MediaInfo, fps: Fraction, image_duration: float = 8.0) -> int:
    """Số frame của clip khi chuẩn hoá về `fps` (ảnh tĩnh: theo `image_duration`)."""
    if info.is_image:
        return max(2, round(image_duration * fps))
    if info.nb_frames and info.fps == fps:
        return max(1, info.nb_frames)
    return max(1, round(info.duration * fps))
