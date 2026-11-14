"""Đo chỗ nối khi lặp: khung cuối của clip (sau khi cắt đầu / cuối) khác khung đầu bao nhiêu, so với độ đổi bình
thường giữa hai khung liền nhau trong clip. Chênh nhiều lần → lặp lại sẽ thấy cú "giật" ở chỗ nối.

Chỉ gợi ý: app báo clip nào giật và đề xuất hoà hình ở chỗ nối hoặc làm bản xuôi–ngược; người dùng quyết định.
Ảnh được thu nhỏ còn 64×36, xám — mỗi clip chỉ giải mã vài khung ở đầu và cuối (nhanh, chạy nền).
"""
from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass

import numpy as np

from . import ffmpeg_tools as ft

W, H = 64, 36
K = 4  # số khung lấy ở mỗi đầu
RATIO = 3.0  # chỗ nối đổi nhiều hơn mức bình thường bao nhiêu lần thì coi là giật
MIN_JUMP = 6.0  # và chênh tối thiểu (thang 0–255) — clip gần như đứng yên thì chênh 2–3 không ai thấy


@dataclass(frozen=True)
class Seam:
    jump: float  # độ chênh khung cuối → khung đầu
    steady: float  # độ chênh bình thường giữa hai khung liền nhau
    jumpy: bool

    @property
    def times(self) -> float:
        return self.jump / max(self.steady, 0.5)


def judge(jump: float, steady: float) -> bool:
    return jump >= MIN_JUMP and jump >= RATIO * max(steady, 0.5)


def _frames(path: str, start: float, dur: float) -> np.ndarray:
    args = [ft.ffmpeg(), "-v", "error", "-nostdin", "-ss", f"{max(0.0, start):.6f}", "-i", path, "-t", f"{dur:.6f}",
            "-an", "-vf", f"scale={W}:{H}:flags=area,format=gray", "-f", "rawvideo", "-"]
    r = subprocess.run(args, capture_output=True, timeout=60, creationflags=ft.CREATE_NO_WINDOW)
    data = np.frombuffer(r.stdout, np.uint8)
    n = len(data) // (W * H)
    return data[: n * W * H].reshape(n, H, W).astype(np.float32)


def measure(path: str, duration: float, fps: float, trim_start: float = 0.0, trim_end: float = 0.0) -> Seam | None:
    """None = không đo được (file lỗi, quá ngắn)."""
    fps = fps or 30.0
    end = duration - trim_end
    span = (K + 1) / fps
    if end - trim_start < 2 * span:
        return None
    try:
        head = _frames(path, trim_start, span)[:K]
        tail = _frames(path, end - span - 0.5 / fps, span + 0.5 / fps)[-K:]
    except (OSError, subprocess.SubprocessError):
        return None
    if len(head) < 2 or len(tail) < 2:
        return None

    def diff(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.abs(a - b).mean())

    steps = [diff(head[i], head[i + 1]) for i in range(len(head) - 1)] + \
            [diff(tail[i], tail[i + 1]) for i in range(len(tail) - 1)]
    steady = float(np.median(steps))
    jump = diff(tail[-1], head[0])
    return Seam(jump, steady, judge(jump, steady))


_cache: dict[tuple, Seam | None] = {}
_lock = threading.Lock()


def key(path: str, trim_start: float, trim_end: float) -> tuple:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    return os.path.normcase(path), round(trim_start, 3), round(trim_end, 3), mtime


def cached(path: str, trim_start: float, trim_end: float):
    """(đã đo chưa, kết quả)."""
    k = key(path, trim_start, trim_end)
    with _lock:
        return (k in _cache), _cache.get(k)


def measure_cached(path: str, duration: float, fps: float, trim_start: float = 0.0, trim_end: float = 0.0):
    k = key(path, trim_start, trim_end)
    with _lock:
        if k in _cache:
            return _cache[k]
    res = measure(path, duration, fps, trim_start, trim_end)
    with _lock:
        _cache[k] = res
        if len(_cache) > 2000:
            _cache.pop(next(iter(_cache)))
    return res
