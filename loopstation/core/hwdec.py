"""Giải mã video nguồn bằng card đồ hoạ khi cắt video / xuất ảnh / chuyển H.264.

Khi card đã lo phần mã hoá, CPU giải mã là phần chậm nhất (đo 1080p: card NVIDIA giải mã + 3 đoạn song song nhanh gấp
~2 lần). Chọn theo card đang mã hoá:
  - NVIDIA (NVENC) → CUDA;
  - AMD (AMF) và Intel (Quick Sync) → D3D11 — chung cho mọi hãng card trên Windows, có sẵn trong FFmpeg đi kèm;
  - không có card mã hoá (libx264) → CPU.
Trước khi dùng, thử giải mã thật vài khung của chính video đó (ép khung hình nằm trên card rồi mới chép về, nên card
không đọc được codec — vd DivX / Xvid cũ trên D3D11 — là báo lỗi ngay, không lặng lẽ chạy bằng CPU). Lỗi → CPU.
Cách viết "d3d11va:1" = D3D11 trên card thứ 2 (máy nhiều card; dùng khi kiểm tra)."""
from __future__ import annotations

import os
import subprocess
import threading

from . import ffmpeg_tools as ft

_OUT_FMT = {"cuda": "cuda", "d3d11va": "d3d11", "dxva2": "dxva2_vld", "qsv": "qsv", "vulkan": "vulkan"}
_LABELS = {"cuda": "card NVIDIA (CUDA)", "d3d11va": "card đồ hoạ (D3D11)"}
_cache: dict[tuple, bool] = {}
_lock = threading.Lock()


def candidate(encoder: str) -> str:
    """Cách giải mã nên thử theo encoder đang dùng ("" = CPU)."""
    if encoder.endswith("_nvenc"):
        return "cuda"
    if encoder.endswith(("_amf", "_qsv")):
        return "d3d11va"
    return ""


def _split(hw: str) -> tuple[str, str]:
    name, _, dev = hw.partition(":")
    return name, dev


def args(hw: str) -> list[str]:
    """Tham số FFmpeg đặt TRƯỚC -i. "" → []."""
    if not hw:
        return []
    name, dev = _split(hw)
    return ["-hwaccel", name, *(["-hwaccel_device", dev] if dev else [])]


def label(hw: str) -> str:
    """Chữ cho nhật ký: "card NVIDIA (CUDA)", "card đồ hoạ (D3D11)", "CPU"."""
    if not hw:
        return "CPU"
    return _LABELS.get(_split(hw)[0], _split(hw)[0])


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def works(hw: str, src: str) -> bool:
    """Card giải mã được video `src` thật không (thử 5 khung, 8-bit rồi 10-bit). Nhớ kết quả theo file."""
    if not hw:
        return False
    try:
        st = os.stat(src)
        key = (hw, os.path.abspath(src), st.st_mtime_ns, st.st_size)
    except OSError:
        return False
    with _lock:
        if key in _cache:
            return _cache[key]
    name, _ = _split(hw)
    out = _OUT_FMT.get(name, name)
    ok = False
    for fmt in ("nv12", "p010le"):  # khung trên card phải chép về đúng độ sâu màu (8-bit / 10-bit)
        try:
            r = ft.run([ft.ffmpeg(), "-hide_banner", "-v", "error", *args(hw), "-hwaccel_output_format", out,
                        "-i", src, "-map", "0:v:0", "-frames:v", "5", "-vf", f"hwdownload,format={fmt}",
                        "-f", "null", "-"], timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            break
        if r.returncode == 0:
            ok = True
            break
    with _lock:
        _cache[key] = ok
    return ok


def choose(encoder: str, src: str, enabled: bool = True) -> str:
    """Cách giải mã sẽ dùng cho video này ("" = CPU): theo card mã hoá, đã thử được thật."""
    hw = candidate(encoder) if enabled else ""
    return hw if hw and works(hw, src) else ""


def export_choice(accel, enabled: bool) -> str:
    """Ô Cài đặt "Giải mã video nguồn bằng GPU" khi xuất video: NVIDIA → CUDA, AMD / Intel → D3D11 (đã dò được lúc
    kiểm tra phần cứng). Tắt / chưa dò xong / không có → "" (CPU)."""
    if not enabled or accel is None:
        return ""
    if getattr(accel, "cuda_decode", False):
        return "cuda"
    if getattr(accel, "d3d11_decode", False):
        return "d3d11va"
    return ""


# dấu hiệu lỗi do bước giải mã bằng card (không phải bước mã hoá)
_DECODE_ERRORS = ("hwaccel", "failed setup for format", "hw_frames", "hardware device", "d3d11va", "dxva",
                  "cuvid", "nvdec", "cuda_error", "cuda error", "device creation failed")


def is_decode_failure(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _DECODE_ERRORS)
