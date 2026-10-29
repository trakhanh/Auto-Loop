"""Tìm ffmpeg/ffprobe, chạy tiến trình và quản lý thư mục cache."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class CancelledError(Exception):
    """Người dùng đã bấm huỷ."""


class FFmpegError(RuntimeError):
    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


# Tuỳ chọn toàn cục, đặt từ trang Cài đặt
OPTIONS: dict[str, str] = {"hwdec": ""}  # "" = giải mã bằng CPU; hoặc tên hwaccel (cuda, d3d11va…)
_custom_dir: str | None = None


def set_custom_dir(folder: str | None) -> None:
    """Dùng ffmpeg.exe/ffprobe.exe trong thư mục do người dùng chọn (None = tự tìm)."""
    global _custom_dir
    _custom_dir = folder or None
    _tools.clear()


def _find_tool(name: str) -> str:
    exe = f"{name}.exe" if os.name == "nt" else name
    candidates = [Path(_custom_dir) / exe] if _custom_dir else []
    candidates.append(app_dir() / "bin" / exe)
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "bin" / exe)
    for c in candidates:
        if c.is_file():
            return str(c)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"Không tìm thấy {exe}. Hãy đặt {exe} vào thư mục 'bin' cạnh ứng dụng."
    )


_tools: dict[str, str] = {}


def ffmpeg() -> str:
    if "ffmpeg" not in _tools:
        _tools["ffmpeg"] = _find_tool("ffmpeg")
    return _tools["ffmpeg"]


def ffprobe() -> str:
    if "ffprobe" not in _tools:
        _tools["ffprobe"] = _find_tool("ffprobe")
    return _tools["ffprobe"]


def data_dir() -> Path:
    # KTLS_DATA_DIR: thư mục riêng cho test, để không đụng dữ liệu của app thật
    override = os.environ.get("KTLS_DATA_DIR")
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    d = Path(override) if override else Path(base) / "KTLoopStation"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir(sub: str = "") -> Path:
    d = data_dir() / "cache"
    if sub:
        d = d / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


CACHE_PARTS = ("blocks", "srcaudio", "thumbs", "jobs", "estimate", "ambient", "ambientlib", "lookpreview")


def preview_dir() -> Path:
    """Nơi chứa bản "Xem thử nối" (file tạm, app tự dọn)."""
    d = data_dir() / "preview"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean_previews(keep: str | None = None) -> int:
    """Xoá các bản xem thử cũ (trừ `keep`). File đang mở trong trình xem thì bỏ qua, lần sau xoá. Trả về số byte đã xoá."""
    freed = 0
    for f in [*preview_dir().glob("seam_*.mp4"), *preview_dir().glob("nghe-thu_*.wav")]:
        if keep and os.path.normcase(str(f)) == os.path.normcase(keep):
            continue
        try:
            size = f.stat().st_size
            f.unlink()
            freed += size
        except OSError:
            pass
    return freed


def clean_temp() -> None:
    """Dọn file tạm cũ: bản xem thử nối, thư mục tạm của bản cũ trong %TEMP% (ảnh xem trước, tự kiểm tra)."""
    import tempfile
    import time
    clean_previews()
    _clean_stale_cache()
    prune_cache()
    now = time.time()
    for d in Path(tempfile.gettempdir()).glob("ktls_*"):
        try:
            if d.is_dir() and now - d.stat().st_mtime > 3600:  # bỏ qua thư mục của app đang mở
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


CACHE_LIMIT = 30 * 1024 ** 3  # bộ nhớ đệm khối video/tiếng gốc vượt mức này thì tự xoá bớt khối cũ nhất
PRUNE_PARTS = ("blocks", "srcaudio", "estimate", "thumbs")


def _cache_files(parts=PRUNE_PARTS) -> list[tuple[float, int, Path]]:
    out = []
    for part in parts:
        d = data_dir() / "cache" / part
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if not f.is_file() or ".tmp" in f.name:
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            out.append((st.st_mtime, st.st_size, f))
    return out


def prune_cache(limit: int = CACHE_LIMIT, need_free: int = 0) -> int:
    """Xoá khối cũ nhất (ít dùng lại nhất) cho tới khi bộ nhớ đệm dưới 80% `limit` và ổ đĩa còn trống ít nhất
    `need_free` byte. Chỉ gọi khi KHÔNG có lượt xuất nào đang chạy. Trả về số byte đã xoá."""
    files = sorted(_cache_files())
    total = sum(s for _, s, _ in files)
    try:
        free = shutil.disk_usage(data_dir()).free
    except OSError:
        free = need_free
    freed = 0
    for _, size, f in files:
        if total - freed <= limit * 0.8 and free + freed >= need_free:
            break
        try:
            f.unlink()
            freed += size
        except OSError:
            pass
    return freed


def _clean_stale_cache() -> None:
    """File tạm (.tmp) và thư mục việc (jobs) bỏ dở khi app bị tắt đột ngột / mất điện."""
    import time
    now = time.time()
    for part in CACHE_PARTS:
        d = data_dir() / "cache" / part
        if not d.is_dir():
            continue
        for f in d.iterdir():
            try:
                if part == "jobs" and f.is_dir() and now - f.stat().st_mtime > 86400:
                    shutil.rmtree(f, ignore_errors=True)
                elif f.is_file() and ".tmp" in f.name and now - f.stat().st_mtime > 3600:
                    f.unlink()
            except OSError:
                pass


def cache_size() -> int:
    total = 0
    for d in [cache_dir(part) for part in CACHE_PARTS] + [preview_dir()]:
        for root, _, files in os.walk(d):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return total


def clear_cache() -> None:
    for part in CACHE_PARTS:
        shutil.rmtree(data_dir() / "cache" / part, ignore_errors=True)
    clean_previews()


_job_handle: int | None = None
_job_lock = threading.Lock()


def _kill_on_close_job() -> int:
    """Windows Job Object có cờ KILL_ON_JOB_CLOSE: app thoát (kể cả bị kill) thì mọi ffmpeg con cũng dừng."""
    global _job_handle
    with _job_lock:
        if _job_handle is not None:
            return _job_handle
        _job_handle = 0
        if os.name != "nt":
            return 0
        try:
            import ctypes
            from ctypes import wintypes

            class Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class Io(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes",
                                                           "WriteBytes", "OtherBytes")]

            class Ext(ctypes.Structure):
                _fields_ = [("Basic", Basic), ("Io", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            h = k32.CreateJobObjectW(None, None)
            if not h:
                return 0
            info = Ext()
            info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info)):
                k32.CloseHandle(h)
                return 0
            _job_handle = int(h)
        except Exception:  # noqa: BLE001
            _job_handle = 0
        return _job_handle


def _attach(proc: subprocess.Popen) -> None:
    job = _kill_on_close_job()
    if not job:
        return
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.AssignProcessToJobObject(job, int(proc._handle))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def run(args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


class Runner:
    """Chạy ffmpeg có thể huỷ, đọc tiến trình từ `-progress pipe:1`."""

    def __init__(self) -> None:
        self._procs: set[subprocess.Popen] = set()  # chạy song song được (chuẩn hoá nhiều clip cùng lúc)
        self._lock = threading.Lock()
        self.cancelled = False

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True
            for p in list(self._procs):
                if p.poll() is None:
                    p.kill()

    def check(self) -> None:
        if self.cancelled:
            raise CancelledError()

    def ffmpeg(
        self,
        args: list[str],
        on_progress: Callable[[dict[str, str]], None] | None = None,
    ) -> str:
        """Chạy ffmpeg với `args` (không gồm tên chương trình). Trả về stderr."""
        self.check()
        cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-y"]
        if on_progress:
            cmd += ["-progress", "pipe:1", "-nostats"]
        cmd += args
        with self._lock:
            if self.cancelled:
                raise CancelledError()
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW,
            )
            self._procs.add(proc)
            _attach(proc)
        err_chunks: list[bytes] = []
        t = threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True)
        t.start()
        block: dict[str, str] = {}
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            block[k] = v
            if k == "progress":
                if on_progress:
                    on_progress(block)
                block = {}
        proc.wait()
        t.join()
        stderr = b"".join(err_chunks).decode("utf-8", "replace")
        with self._lock:
            self._procs.discard(proc)
        if self.cancelled:
            raise CancelledError()
        if proc.returncode != 0:
            tail = "\n".join(stderr.strip().splitlines()[-15:])
            raise FFmpegError(f"ffmpeg lỗi (mã {proc.returncode}):\n{tail}", stderr)
        return stderr
