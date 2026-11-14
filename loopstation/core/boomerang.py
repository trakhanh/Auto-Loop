"""Lặp xuôi–ngược (boomerang): clip chạy xuôi rồi chạy ngược → mỗi lần lặp đều nối vào đúng khung hình kế bên, không
còn cú giật ở chỗ nối (khói, nước, lửa, lá cây… mà clip gốc không quay sẵn để lặp).

Thứ tự khung: 0, 1, …, N-1, rồi N-2, …, 1 — khung ở hai đầu chỉ hiện một lần nên chuyển động không bị khựng khi quay
đầu; lần lặp sau bắt đầu lại ở khung 0 (ngay cạnh khung 1). Tiếng: phần sau là tiếng phát ngược (gió, nước, mưa nghe
vẫn tự nhiên; tiếng nói thì nghe ngược — nên tắt tiếng gốc cho clip đó).

Phần ngược được làm theo từng khúc ngắn (~1 giây) rồi ghép lại: bộ lọc `reverse` của FFmpeg giữ cả đoạn trong bộ nhớ,
đảo cả clip 4K dài một lúc có thể tốn hàng GB RAM.
"""
from __future__ import annotations

import os
import shutil
from fractions import Fraction
from pathlib import Path

from . import ffmpeg_tools as ft
from .probe import probe

SUFFIX = "_XuoiNguoc"
CHUNK_MB = 160  # bộ nhớ tối đa cho một khúc đảo ngược (khung thô yuv420p)
X264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "15", "-pix_fmt", "yuv420p"]  # bản trung gian gần như không mất


def output_path(src: str) -> Path:
    """"D:/a/khoi.mp4" → "D:/a/khoi_XuoiNguoc.mp4" (đã có thì _XuoiNguoc2…)."""
    p = Path(src)
    out = p.with_name(f"{p.stem}{SUFFIX}.mp4")
    n = 2
    while out.exists():
        out = p.with_name(f"{p.stem}{SUFFIX}{n}.mp4")
        n += 1
    return out


def chunk_frames(width: int, height: int, fps: float) -> int:
    """Số khung mỗi khúc đảo ngược: ~1 giây, nhưng không quá CHUNK_MB bộ nhớ (4K: ít khung hơn)."""
    per = max(1, width * height * 3 // 2)
    return max(4, min(int(round(fps)) or 30, CHUNK_MB * 1024 * 1024 // per))


def plan_chunks(n: int, size: int) -> list[tuple[int, int]]:
    """Các khúc của phần ngược, theo thứ tự phát: khung [s, e) của clip, phát từ e-1 lùi về s.
    Phần ngược gồm khung N-2 … 1 (khung 0 và N-1 không lặp lại)."""
    out = []
    e = n - 1
    while e > 1:
        s = max(1, e - size)
        out.append((s, e))
        e = s
    return out


def make(runner: ft.Runner, src: str, out: Path, trim_start: float = 0.0, trim_end: float = 0.0,
         on_step=None) -> Path:
    """Tạo bản xuôi–ngược của đoạn [trim_start, duration - trim_end] → `out` (ghi tên tạm rồi đổi tên)."""
    info = probe(src)
    if not info.ok or not info.has_video or info.is_image:
        raise ValueError("Chỉ làm được với video (không phải ảnh tĩnh / file lỗi).")
    fps = Fraction(info.fps).limit_denominator(1001) if info.fps else Fraction(30)
    length = max(0.0, info.duration - trim_start - trim_end)
    n = int(length * fps + 1e-6)
    if n < 3:
        raise ValueError("Clip quá ngắn để làm xuôi–ngược (cần ít nhất 3 khung hình).")
    rate = f"{fps.numerator}/{fps.denominator}"
    work = ft.cache_dir("boomerang") / f"{os.getpid()}_{abs(hash((src, trim_start, trim_end, n)))}"
    work.mkdir(parents=True, exist_ok=True)
    chunks = plan_chunks(n, chunk_frames(info.width, info.height, float(fps)))
    steps = 1 + len(chunks) + 1
    done = 0

    def step() -> None:
        nonlocal done
        done += 1
        if on_step:
            on_step(min(1.0, done / steps))

    def seek(frame: int) -> str:
        # lùi 1/4 khung: ffmpeg tua chính xác bỏ mọi khung trước mốc này → khung `frame` là khung đầu tiên ra
        return f"{max(0.0, trim_start + (frame - 0.25) / float(fps)):.6f}"

    try:
        parts: list[Path] = []
        fwd = work / "0000_xuoi.mp4"
        runner.ffmpeg(["-v", "error", "-ss", seek(0), "-i", src, "-an",
                       "-vf", f"fps={rate},trim=end_frame={n},setpts=PTS-STARTPTS", "-frames:v", str(n),
                       *X264, "-r", rate, str(fwd)])
        parts.append(fwd)
        step()
        for i, (s, e) in enumerate(chunks, start=1):
            part = work / f"{i:04d}_nguoc.mp4"
            runner.ffmpeg(["-v", "error", "-ss", seek(s), "-i", src, "-an",
                           "-vf", f"fps={rate},trim=end_frame={e - s},setpts=PTS-STARTPTS,reverse",
                           "-frames:v", str(e - s), *X264, "-r", rate, str(part)])
            parts.append(part)
            step()
        lst = work / "list.ffconcat"
        lst.write_text("ffconcat version 1.0\n" + "".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        total = (2 * n - 2) / float(fps)
        tmp = out.with_name(out.stem + ".dang-tao" + out.suffix)
        args = ["-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
        if info.has_audio:
            a0, a1 = trim_start, trim_start + n / float(fps)
            one = 1 / float(fps)
            graph = (f"[1:a]atrim=start={a0:.6f}:end={a1:.6f},asetpts=PTS-STARTPTS,aresample=48000,asplit[f][r];"
                     f"[r]atrim=start={one:.6f}:end={(n - 1) * one:.6f},asetpts=PTS-STARTPTS,areverse[rr];"
                     f"[f][rr]concat=n=2:v=0:a=1,apad,atrim=end={total:.6f}[a]")
            args += ["-i", src, "-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "320k"]
        else:
            args += ["-map", "0:v"]
        args += ["-c:v", "copy", "-movflags", "+faststart", str(tmp)]
        try:
            runner.ffmpeg(args)
            os.replace(tmp, out)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        step()
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
