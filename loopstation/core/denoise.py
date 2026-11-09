"""Lọc tạp âm (gió, ù nền, xì) cho tiếng gốc clip — kiểu "trừ phổ tự học tạp âm" như Premiere (Essential Sound →
Repair → Reduce Noise / hiệu ứng DeNoise): tự nghe xem dải tần nào lúc nào cũng có (gió, ù máy quay…) rồi trừ đi,
giữ âm thanh lúc có lúc không (tiếng bước chân, nước chảy, lửa tách…). Mức "Vừa" chỉnh khớp cặp video mẫu
(DenoiseTest: demo4kkk_NoDeNoise → demo4kkk_DeNoise): cùng độ to, cùng chỗ câm giữa các tiếng bước chân.

Chỉ cần numpy. Chạy theo từng đoạn trên file tạm (memmap) nên clip dài cả giờ cũng không tốn RAM. Kết quả là bản
tiếng đã lọc (FLAC 48 kHz stereo, đúng độ dài và mốc giờ như tiếng gốc) trong bộ nhớ đệm — xuất lần sau dùng lại."""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

from . import ffmpeg_tools as ft

SR = 48000
N = 2048  # khung FFT ~43 ms
HOP = N // 4
VERSION = 1  # đổi cách lọc → tăng số này để bản cũ trong bộ nhớ đệm không bị dùng lại
# mức → (phân vị coi là tạp âm, hệ số trừ, sàn dB — phần bị trừ hết vẫn chừa lại chừng này cho tự nhiên)
LEVELS = {
    "light": (40, 1.5, -20.0),
    "medium": (50, 1.5, -40.0),  # khớp mẫu Premiere (độ to, chỗ câm) trên cả video
    "strong": (50, 2.0, -60.0),  # sạch hơn mẫu: giữa các tiếng bước chân câm hẳn
}
LABELS = {"off": "Tắt", "light": "Nhẹ — bớt ù, gió", "medium": "Vừa — giống mẫu Premiere", "strong": "Mạnh — sạch hẳn"}
BLOCK = 256  # học tạp âm theo từng khối ~2,7 giây…
SPAN = 4  # …gộp ±4 khối (~±11 giây) quanh chỗ đang lọc: gió to lên / nhỏ đi thì mức trừ đổi theo (như Premiere)
CHUNK = 1024  # số khung xử lý mỗi lượt (~11 giây)
SMOOTH_T, SMOOTH_F = 1, 2  # làm mượt mức giảm ± ô theo thời gian / tần số: bớt tiếng "lục bục" kiểu robot
SHARP = 2.0  # 1 = trừ biên độ; 2 = trừ công suất (âm to hơn hẳn tạp âm giữ gần nguyên, sát tạp âm mới cắt)


def available() -> bool:
    try:
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def _window():
    import numpy as np
    return (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N) / N)).astype(np.float32)  # Hann tuần hoàn


def _frames(x, starts):
    """Các khung N mẫu bắt đầu ở `starts` (ngoài biên → 0). x: (L, 2) → (len(starts), N, 2)."""
    import numpy as np
    out = np.zeros((len(starts), N, x.shape[1]), dtype=np.float32)
    total = len(x)
    for j, s in enumerate(starts):
        a, b = max(0, s), min(total, s + N)
        if b > a:
            out[j, a - s:b - s] = x[a:b]
    return out


def _box(a, r: int, axis: int):
    """Trung bình trượt 2r+1 ô theo `axis` (biên: lặp ô cuối)."""
    import numpy as np
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    zero = np.zeros_like(np.take(c, [0], axis=axis))
    c = np.concatenate([zero, c], axis=axis)
    n = a.shape[axis]
    k = 2 * r + 1
    return ((np.take(c, range(k, k + n), axis=axis) - np.take(c, range(0, n), axis=axis)) / k).astype(np.float32)


def process(raw_in: Path, raw_out: Path, level: str, check=None, on_step=None) -> None:
    """Lọc file PCM f32le stereo 48 kHz `raw_in` → `raw_out` (cùng độ dài)."""
    import numpy as np
    pct, over, floor_db = LEVELS[level]
    x = np.memmap(raw_in, dtype=np.float32, mode="r")
    x = x[:len(x) // 2 * 2].reshape(-1, 2)
    total = len(x)
    out = np.memmap(raw_out, dtype=np.float32, mode="w+", shape=(total + 2 * N, 2))
    if total == 0:
        out.flush()
        return
    w = _window()
    w3 = w[None, :, None]
    first = -(N - HOP)  # khung đầu bắt đầu trước mẫu 0 → mẫu nào cũng nằm trong đúng N/HOP khung
    count = (total - first) // HOP + 1

    # lượt 1: học tạp âm từng khối — phân vị độ lớn mỗi dải tần (lấy 1/4 số khung: các khung không chồng nhau)
    blocks = []
    for k in range(0, count, BLOCK):
        if check:
            check()
        idx = np.arange(k, min(count, k + BLOCK), N // HOP)
        mag = np.abs(np.fft.rfft(_frames(x, first + idx * HOP) * w3, axis=1))
        blocks.append(np.percentile(mag, pct, axis=0))
    blocks = np.stack(blocks)  # (số khối, dải tần, 2)
    g_floor = np.float32(10 ** (floor_db / 20))

    # lượt 2: trừ phổ từng đoạn (thêm SMOOTH_T khung hai bên để làm mượt liền mạch giữa các đoạn)
    for a in range(0, count, CHUNK):
        if check:
            check()
        b = min(count, a + CHUNK)
        lo, hi = max(0, a - SMOOTH_T), min(count, b + SMOOTH_T)
        spec = np.fft.rfft(_frames(x, first + np.arange(lo, hi) * HOP) * w3, axis=1)
        mid = (a + b) // 2 // BLOCK
        noise = over * np.median(blocks[max(0, mid - SPAN):mid + SPAN + 1], axis=0)[None] + 1e-9
        snr = np.abs(spec) / noise
        gain = np.clip(1 - 1 / np.maximum(snr, 1e-9) ** SHARP, 0, 1)
        if SMOOTH_T:
            gain = _box(gain, SMOOTH_T, 0)
        if SMOOTH_F:
            gain = _box(gain, SMOOTH_F, 1)
        gain = np.maximum(gain, g_floor)
        keep = slice(a - lo, a - lo + (b - a))
        y = np.fft.irfft(spec[keep] * gain[keep], n=N, axis=1).astype(np.float32) * w3
        # cộng chồng: khung cách nhau 4 bước nằm sát nhau không chồng → mỗi nhóm cộng một lần (nhanh hơn từng khung)
        for r in range(min(N // HOP, b - a)):
            grp = y[r::N // HOP]
            s = first + (a + r) * HOP + N  # out lệch N mẫu: khung đầu (bắt đầu trước mẫu 0) vẫn ghi được
            out[s:s + len(grp) * N] += grp.reshape(-1, 2)
        if on_step:
            on_step(b / count)
    out[:] /= np.float32(1.5)  # tổng w² của Hann chồng 4 lớp = 1.5
    out.flush()
    del out


def _file_id(path: str) -> str:
    st = os.stat(path)
    return f"{os.path.normcase(os.path.abspath(path))}:{st.st_size}:{st.st_mtime_ns}"


def denoised_copy(runner: ft.Runner, path: str, level: str, on_step=None) -> str:
    """Tiếng của `path` đã lọc tạp âm (FLAC trong bộ nhớ đệm; có rồi thì dùng lại). Mốc giờ y như lúc app tách tiếng
    gốc (luồng âm thanh đầu, bỏ khoảng trễ đầu) nên thay thẳng vào chỗ file gốc được."""
    if level not in LEVELS:
        return path
    key = hashlib.sha1(f"dn{VERSION}|{level}|{_file_id(path)}".encode("utf-8")).hexdigest()[:20]
    out = ft.cache_dir("denoise") / f"{key}.flac"
    if out.is_file() and out.stat().st_size > 0:
        return str(out)
    tag = f"{key}.{os.getpid()}-{threading.get_ident()}"
    raw_in, raw_out = out.with_name(tag + ".in.tmp"), out.with_name(tag + ".out.tmp")
    tmp = out.with_name(tag + ".tmp.flac")
    dec = ["-af", "asetpts=PTS-STARTPTS,aresample=48000", "-ac", "2", "-f", "f32le", str(raw_in)]
    try:
        try:
            runner.ffmpeg(["-v", "error", "-err_detect", "ignore_err", "-i", path, "-map", "0:a:0", "-vn", *dec])
        except ft.FFmpegError:  # tiếng gốc có đoạn dữ liệu rác: đọc từ bản sạch (giữ đúng độ dài)
            from . import audio_build
            raw_in.unlink(missing_ok=True)
            runner.ffmpeg(["-v", "error", "-i", audio_build.clean_copy(runner, path), *dec])
        process(raw_in, raw_out, level, runner.check, on_step)
        total = raw_in.stat().st_size // 8
        runner.ffmpeg(["-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(raw_out),
                       "-af", f"atrim=start_sample={N}:end_sample={N + total},asetpts=PTS-STARTPTS",
                       "-c:a", "flac", str(tmp)])
        try:
            os.replace(tmp, out)
        except OSError:
            if not (out.is_file() and out.stat().st_size > 0):
                raise
    finally:
        for p in (raw_in, raw_out, tmp):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    return str(out)


def denoise_paths(runner: ft.Runner, paths: dict[int, str], audible: dict[int, bool], level: str, log=None,
                  on_step=None) -> dict[int, str]:
    """Đường dẫn tiếng gốc để tách: clip có tiếng → bản đã lọc tạp âm; clip khác giữ nguyên."""
    if level not in LEVELS:
        return paths
    if not available():
        if log:
            log("Cảnh báo: thiếu thư viện numpy — bỏ qua bước lọc tạp âm tiếng gốc.")
        return paths
    files = list(dict.fromkeys(p for k, p in sorted(paths.items()) if audible.get(k)))
    done: dict[str, str] = {}
    for n, p in enumerate(files):
        step = (lambda f, n=n: on_step((n + f) / len(files))) if on_step else None
        done[p] = denoised_copy(runner, p, level, step)
        if log:
            log(f"  Lọc tạp âm ({LABELS[level]}): {Path(p).name}")
    return {k: done.get(p, p) for k, p in paths.items()}
