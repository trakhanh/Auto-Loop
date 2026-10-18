"""Thông số máy, FFmpeg và khả năng tăng tốc phần cứng (CUDA / NVENC / Quick Sync / AMF)."""
from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import encoders
from . import ffmpeg_tools as ft


@dataclass
class GPU:
    name: str
    driver: str = ""
    vram_mb: int = 0
    extra: str = ""  # nhiệt độ, tải… (NVIDIA)


@dataclass
class SystemInfo:
    os: str = ""
    cpu: str = ""
    cores: int = 0
    ram_gb: float = 0.0
    gpus: list[GPU] = field(default_factory=list)
    cuda_version: str = ""


@dataclass
class AccelInfo:
    ffmpeg_path: str = ""
    ffmpeg_version: str = ""
    ffprobe_path: str = ""
    hwaccels: list[str] = field(default_factory=list)
    encoders: dict[str, bool] = field(default_factory=dict)  # tên encoder → chạy được
    cuda_decode: bool = False
    error: str = ""


# ---------------- máy tính ----------------
def _reg(path: str, name: str) -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return ""


def _ram_gb() -> float:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    try:
        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        return st.ullTotalPhys / 1024 ** 3
    except Exception:  # noqa: BLE001
        return 0.0


def _windows_name() -> str:
    key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    name, disp, build = _reg(key, "ProductName"), _reg(key, "DisplayVersion"), _reg(key, "CurrentBuild")
    if build.isdigit() and int(build) >= 22000:  # Windows 11 vẫn ghi "Windows 10" trong registry
        name = name.replace("Windows 10", "Windows 11")
    return " ".join(x for x in (name, disp, f"(build {build})" if build else "") if x) or platform.platform()


def _run(cmd: list[str], timeout: float = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=ft.CREATE_NO_WINDOW)
        return r.stdout
    except Exception:  # noqa: BLE001
        return ""


def gather_system() -> SystemInfo:
    info = SystemInfo(os=_windows_name(), cores=os.cpu_count() or 0, ram_gb=_ram_gb())
    info.cpu = _reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString").strip() \
        or platform.processor()
    # card đồ hoạ (mọi hãng)
    out = _run(["powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name + '|' + $_.DriverVersion + '|' "
                "+ $_.AdapterRAM }"])
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) == 3 and parts[0]:
            ram = int(parts[2]) // 1024 ** 2 if parts[2].isdigit() else 0
            info.gpus.append(GPU(parts[0], parts[1], ram))
    # NVIDIA: thông số chính xác hơn (VRAM thật, nhiệt độ, phiên bản CUDA)
    smi = shutil.which("nvidia-smi")
    if smi:
        q = _run([smi, "--query-gpu=name,driver_version,memory.total,temperature.gpu,utilization.gpu",
                  "--format=csv,noheader,nounits"])
        for line in q.splitlines():
            p = [x.strip() for x in line.split(",")]
            if len(p) == 5:
                g = next((g for g in info.gpus if g.name == p[0]), None)
                if g is None:
                    g = GPU(p[0])
                    info.gpus.append(g)
                g.driver = p[1]
                g.vram_mb = int(float(p[2])) if p[2].replace(".", "").isdigit() else g.vram_mb
                g.extra = f"{p[3]}°C · đang dùng {p[4]}%"
        m = re.search(r"CUDA Version:\s*([\d.]+)", _run([smi]))
        if m:
            info.cuda_version = m.group(1)
    return info


# ---------------- FFmpeg + tăng tốc ----------------
TEST_ENCODERS = ["h264_nvenc", "hevc_nvenc", "av1_nvenc", "h264_qsv", "hevc_qsv", "av1_qsv",
                 "h264_amf", "hevc_amf", "av1_amf", "libx264", "libx265"]


def _test_encoder(name: str) -> bool:
    return encoders._test(name)


def _test_cuda_decode() -> bool:
    """Giải mã H.264 bằng CUDA thật sự (ép khung hình nằm trên GPU, lỗi là biết ngay)."""
    if "cuda_decode" in encoders._TEST_CACHE:
        return encoders._TEST_CACHE["cuda_decode"]
    tmp = Path(tempfile.gettempdir()) / f"ktls_cuda_test_{os.getpid()}_{threading.get_ident()}.mp4"
    try:
        ft.run([ft.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                "testsrc2=s=640x360:r=24:d=0.3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp)], timeout=15)
        r = ft.run([ft.ffmpeg(), "-hide_banner", "-v", "error", "-hwaccel", "cuda", "-hwaccel_output_format",
                    "cuda", "-i", str(tmp), "-vf", "hwdownload,format=nv12", "-f", "null", "-"], timeout=15)
        ok = r.returncode == 0
    except Exception:  # noqa: BLE001
        ok = False
    finally:
        tmp.unlink(missing_ok=True)
    encoders._TEST_CACHE["cuda_decode"] = ok
    return ok


def gather_accel() -> AccelInfo:
    info = AccelInfo()
    try:
        info.ffmpeg_path, info.ffprobe_path = ft.ffmpeg(), ft.ffprobe()
    except FileNotFoundError as e:
        info.error = str(e)
        return info
    first = (ft.run([info.ffmpeg_path, "-hide_banner", "-version"], timeout=15).stdout.splitlines() or [""])[0]
    info.ffmpeg_version = first.replace("ffmpeg version ", "").split(" Copyright")[0].strip()
    out = ft.run([info.ffmpeg_path, "-hide_banner", "-hwaccels"], timeout=15).stdout
    info.hwaccels = [x.strip() for x in out.splitlines()[1:] if x.strip()]
    with ThreadPoolExecutor(max_workers=4) as ex:
        cuda = ex.submit(_test_cuda_decode) if "cuda" in info.hwaccels else None
        info.encoders = dict(zip(TEST_ENCODERS, ex.map(_test_encoder, TEST_ENCODERS)))
        info.cuda_decode = bool(cuda and cuda.result())
    return info


def benchmark(encoder: str, quality: str = "high", seconds: int = 10) -> float:
    """Mã hoá `seconds` giây video 1080p thử; trả về số lần nhanh hơn thời gian thực (0 = lỗi)."""
    from .encoders import encoder_args, pix_fmt
    args = [ft.ffmpeg(), "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
            f"testsrc2=s=1920x1080:r=24:d={seconds}", "-pix_fmt", pix_fmt(encoder),
            *encoder_args(encoder, quality, 48), "-f", "null", "-"]
    t0 = time.perf_counter()
    try:
        r = ft.run(args, timeout=300)
    except Exception:  # noqa: BLE001
        return 0.0
    took = time.perf_counter() - t0
    return seconds / took if r.returncode == 0 and took > 0 else 0.0
