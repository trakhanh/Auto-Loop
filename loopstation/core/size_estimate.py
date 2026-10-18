"""Dự đoán dung lượng file xuất bằng cách mã hoá thử vài giây của từng clip với đúng cấu hình đang chọn.

Video loop lặp lại cùng một nội dung nhưng MP4 không có cách "phát lại khối này 70 lần" — mỗi lần lặp vẫn
chiếm dung lượng như nhau. Vì vậy dung lượng ≈ Σ (thời lượng của clip trong video × bitrate của clip đó).
Bitrate đo thật (cùng encoder, chất lượng, độ phân giải, fps, giới hạn bitrate) nên sát thực tế hơn nhiều so
với đoán theo file nguồn. Kết quả được nhớ lại, đổi qua lại cấu hình cũ không phải đo lại.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from fractions import Fraction

from . import encoders, planner
from . import ffmpeg_tools as ft
from . import video_build as vb

SAMPLE_SECONDS = 12.0  # clip loop thường 6–10 giây → đo nguyên cả clip
MP4_OVERHEAD = 1.004
XFADE_FACTOR = 1.15
XFADE_P = 1.0  # khung thường trong đoạn crossfade ≈ tổng hai bên (đo thực tế: sai số ±10%)
_cache: dict[str, tuple[float, float]] = {}  # khoá mẫu → (bit khung gốc, bit khung thường)
_lock = threading.Lock()
MIN_SHARE = 0.03  # clip chiếm dưới 3% thời lượng thì không cần đo thật
WORKERS = 3  # số clip mã hoá thử cùng lúc (GPU làm được nhiều phiên song song)


class Group:
    """Nhóm Runner để huỷ cùng lúc mọi lượt mã hoá thử đang chạy."""

    def __init__(self) -> None:
        self.cancelled = False
        self._runners: list[ft.Runner] = []
        self._lock = threading.Lock()

    def runner(self) -> ft.Runner:
        r = ft.Runner()
        with self._lock:
            if self.cancelled:
                r.cancel()
            self._runners.append(r)
        return r

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True
            for r in self._runners:
                r.cancel()


@dataclass
class Estimate:
    bytes: float = 0.0
    video_bps: float = 0.0  # bitrate hình trung bình
    audio_bps: float = 0.0
    encoder: str = ""
    maxrate_kbps: int = 0
    measured: int = 0  # số clip đã đo thật
    per_clip: dict[str, float] = field(default_factory=dict)  # tên file → bit/giây
    xfade_bits: float = 0.0


def _sample(runner: ft.Runner, path: str, is_image: bool, start: float, dur: float, fps: Fraction, w: int, h: int,
            fit: str, encoder: str, quality: str, maxrate: int, gop: int, strict: bool = False) -> tuple[float, float]:
    """Mã hoá thử → (bit của 1 khung gốc I-frame, bit trung bình của 1 khung thường)."""
    n = max(1, round(dur * float(fps)))
    key = vb._key("est3", vb._file_id(path), f"{start:.2f}", n, fps, w, h, fit, encoder, quality, maxrate, gop,
                  *(["strict"] if strict and maxrate else []))
    with _lock:
        if key in _cache:
            return _cache[key]
    out = ft.cache_dir("estimate") / f"{key}.mp4"
    seek = [] if is_image else ["-ss", f"{start:.3f}"]
    args = ["-v", "error", *seek, *vb._input(path, fps), "-map", "0:v:0",
            "-vf", f"{vb._norm(fit, w, h, fps, '', path)},format={encoders.pix_fmt(encoder)}", *vb.COLOR_TAGS,
            "-frames:v", str(n), *encoders.encoder_args(encoder, quality, gop, maxrate, strict),
            "-an", "-sn", "-dn", "-f", "mp4", str(out)]
    try:
        runner.ffmpeg(args)
        r = ft.run([ft.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=size,flags",
                    "-of", "csv=p=0", str(out)], timeout=60)
        size = out.stat().st_size
    finally:
        try:
            out.unlink()
        except OSError:
            pass
    keys, others = [], []
    for line in r.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 2 and parts[0].isdigit():
            (keys if "K" in parts[1] else others).append(int(parts[0]) * 8)
    if keys:
        res = (sum(keys) / len(keys), sum(others) / len(others) if others else sum(keys) / len(keys))
    else:  # không đọc được gói → chia đều
        res = (size * 8 / n, size * 8 / n)
    with _lock:
        _cache[key] = res
    return res


def estimate(project, tl, available: dict[str, list[str]], group: Group | None = None) -> Estimate:
    """Chạy ở luồng nền (mỗi clip mất khoảng 0,3–2 giây với GPU). Ném ft.CancelledError nếu bị huỷ.

    Mỗi khối khi ghép (thân một lần phát, đoạn crossfade) bắt đầu bằng một khung gốc nặng, sau đó cứ 2 giây
    lại có một khung gốc → tính đúng theo cấu trúc khối như lúc xuất thật."""
    ex, vs = project.export, project.video
    group = group or Group()
    codec = encoders.PRESETS[ex.preset].codec
    encoder = encoders.pick(codec, ex.encoder, available)
    audio_kbps = 320 if ex.audio == "max" else 192
    segs = planner.segments(tl.video, tl.frames)
    maxrate = encoders.maxrate_kbps(ex.bitrate_cap, ex.cap_gb if ex.bitrate_cap == "size" else ex.cap_mbps,
                                    tl.width, tl.height, float(tl.fps), tl.total, audio_kbps,
                                    encoders.cap_blocks(encoder, len(segs)))
    strict = ex.bitrate_cap in ("mbps", "size")
    est = Estimate(encoder=encoder, maxrate_kbps=maxrate)
    gop = max(1, round(float(tl.fps) * 2))
    counts: dict = {}
    for sg in segs:
        counts[sg] = counts.get(sg, 0) + 1
    rates: dict[int, tuple[float, float]] = {}
    clips = list(dict.fromkeys(c for sg in counts
                               for c in ((sg.clip, sg.clip_b) if sg.kind == "xfade" else (sg.clip,))))

    def measure(clip: int) -> tuple[int, tuple[float, float], bool]:
        info = tl.clip_infos[clip]
        used = tl.frames[clip] / float(tl.fps)
        sdur = min(SAMPLE_SECONDS, used)
        start = tl.offsets.get(clip, 0) / float(tl.fps) + max(0.0, (used - sdur) / 2)
        try:
            return clip, _sample(group.runner(), info.path, info.is_image, start, sdur, tl.fps, tl.width,
                                 tl.height, vs.fit, encoder, ex.quality, maxrate, gop, strict), True
        except ft.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — encoder lỗi: đoán theo bitrate file nguồn
            try:
                per = os.path.getsize(info.path) * 8 / max(info.duration, 0.1) / float(tl.fps)
            except OSError:
                per = 8e6 / float(tl.fps)
            return clip, (per * 3, per), False

    # cùng file + cùng đoạn cắt (clip nền xuất hiện ở nhiều dòng) chỉ đo một lần
    def ukey(c: int) -> tuple:
        return os.path.normcase(tl.clip_infos[c].path), tl.offsets.get(c, 0), tl.frames[c]

    same: dict[tuple, list[int]] = {}
    weight: dict[tuple, float] = {}
    for c in clips:
        same.setdefault(ukey(c), []).append(c)
    for sg, cnt in counts.items():
        weight[ukey(sg.clip)] = weight.get(ukey(sg.clip), 0) + cnt * sg.frames
    order = sorted(same, key=lambda k: -weight.get(k, 0))
    total_w = sum(weight.values()) or 1
    # chỉ đo thật các clip chiếm phần đáng kể thời lượng (clip nền loop); cảnh ngắn suy ra theo tỉ lệ
    big = [k for k in order if weight.get(k, 0) / total_w >= MIN_SHARE] or order[:1]
    small = [k for k in order if k not in big]

    def src_per_frame(c: int) -> float:
        info = tl.clip_infos[c]
        try:
            return os.path.getsize(info.path) * 8 / max(info.duration, 0.1) / float(tl.fps)
        except OSError:
            return 8e6 / float(tl.fps)

    ratios = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for clip, rate, ok in pool.map(measure, [same[k][0] for k in big]):
            for c in same[ukey(clip)]:
                rates[c] = rate
            est.measured += ok
            info = tl.clip_infos[clip]
            if ok and not info.is_image:
                ratios.append((rate[0] + rate[1] * (gop - 1)) / gop / src_per_frame(clip))
    ratio = sorted(ratios)[len(ratios) // 2] if ratios else 1.0
    for k in small:
        c0 = same[k][0]
        if tl.clip_infos[c0].is_image:  # ảnh tĩnh: gần như chỉ tốn khung gốc
            _, rate, ok = measure(c0)
            est.measured += ok
        else:
            per = src_per_frame(c0) * ratio
            rate = (per * 3, per * 0.85)
        for c in same[k]:
            rates[c] = rate
    for c, rate in rates.items():
        est.per_clip[os.path.basename(tl.clip_infos[c].path)] = (rate[0] + rate[1] * (gop - 1)) / gop * float(tl.fps)
    if group.cancelled:
        raise ft.CancelledError()
    video_bits = 0.0
    for sg, cnt in counts.items():
        i_b, p_b = rates[sg.clip]
        if sg.kind == "xfade":  # hai hình hoà vào nhau: khung nào cũng đổi → nặng hơn nhiều so với từng bên
            i2, p2 = rates[sg.clip_b]
            i_b, p_b = max(i_b, i2) * XFADE_FACTOR, (p_b + p2) * XFADE_P
        n = sg.frames
        k = -(-n // gop)
        bits = cnt * (k * i_b + (n - k) * p_b)
        video_bits += bits
        if sg.kind == "xfade":
            est.xfade_bits += bits
    est.audio_bps = audio_kbps * 1000 if tl.has_audio else 0.0
    est.video_bps = video_bits / tl.total if tl.total else 0.0
    est.bytes = (video_bits + est.audio_bps * tl.total) / 8 * MP4_OVERHEAD
    return est


def fmt_size(b: float) -> str:
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.1f} GB" if b < 100 * 1024 ** 3 else f"{b / 1024 ** 3:.0f} GB"
    return f"{b / 1024 ** 2:.0f} MB"
