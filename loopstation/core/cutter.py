"""Trang "Cắt video": chia video thành nhiều đoạn + xuất ảnh từ video (FFmpeg đi kèm).

Xem docs/superpowers/specs/2026-11-20-chia-video-xuat-khung-design.md. Phần này không dùng Qt: đọc thời gian gõ tay,
tính danh sách đoạn (5 cách), kích thước + filter đổi tỉ lệ, tham số FFmpeg, đặt tên không ghi đè, chạy thật."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path

from . import encoders
from .probe import MediaInfo

EPS = 1e-6
MIN_PIECE = 1.0  # đoạn ngắn hơn 1 giây thì bỏ (hoặc nhập vào đoạn trước)


# ---------- thời gian gõ tay ----------
def parse_time(text: str) -> float:
    """"00:01:15" / "1:15" / "75" / "00:01:15.5" (cả "75,5") → giây. Sai → ValueError (câu tiếng Việt)."""
    t = (text or "").strip()
    m = re.fullmatch(r"(\d+)(?::(\d+))?(?::(\d+))?(?:[.,](\d+))?", t)
    if not m:
        raise ValueError(f"Thời gian «{t}» sai")
    parts = [int(g) for g in m.groups()[:3] if g is not None]
    frac = float("0." + m.group(4)) if m.group(4) else 0.0
    if len(parts) == 3:
        h, mi, s = parts
        if mi >= 60 or s >= 60:
            raise ValueError(f"Thời gian «{t}» sai")
        return h * 3600 + mi * 60 + s + frac
    if len(parts) == 2:
        mi, s = parts
        if s >= 60:
            raise ValueError(f"Thời gian «{t}» sai")
        return mi * 60 + s + frac
    return parts[0] + frac


def _items(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,;\n]+", text or "") if x.strip()]


def parse_marks(text: str) -> list[float]:
    """"00:01:15, 00:05:30" (phẩy / chấm phẩy / xuống dòng) → [75, 330]. Ô trống → []."""
    out = []
    for item in _items(text):
        try:
            out.append(parse_time(item))
        except ValueError:
            raise ValueError(f"Mốc «{item}» sai") from None
    return out


def parse_ranges(text: str) -> list[tuple[float, float]]:
    """"00:01:10-00:01:45, 5:00 – 5:30" → [(70, 105), (300, 330)]. Đầu ≥ cuối hoặc gõ sai → ValueError."""
    out = []
    for item in _items(text):
        ab = re.split(r"\s*[-–—]\s*", item)
        if len(ab) != 2:
            raise ValueError(f"Khoảng «{item}» sai — gõ dạng 00:01:10-00:01:45")
        try:
            a, b = parse_time(ab[0]), parse_time(ab[1])
        except ValueError:
            raise ValueError(f"Khoảng «{item}» sai") from None
        if a >= b:
            raise ValueError(f"Khoảng «{item}» sai: đầu phải trước cuối")
        out.append((a, b))
    return out


def fmt_time(sec: float) -> str:
    s = max(0, int(sec + EPS))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


# ---------- danh sách đoạn ----------
@dataclass
class Segment:
    start: float
    dur: float


SPLIT_MODES = ("parts", "fixed", "random", "marks", "ranges")


@dataclass
class SplitSettings:
    mode: str = "fixed"
    parts: int = 2
    fixed: float = 30.0
    rmin: float = 10.0
    rmax: float = 45.0
    marks: str = ""
    ranges: str = ""
    exact: bool = True
    aspect: str = "keep"
    fit: str = "blur"
    per_video: bool = True
    open_after: bool = False


def _even(duration: float, n: int) -> list[Segment]:
    step = duration / n
    return [Segment(i * step, step) for i in range(n)]


def _random(duration: float, rmin: float, rmax: float, rng: random.Random) -> list[Segment]:
    out: list[Segment] = []
    t = 0.0
    while duration - t > EPS:
        rest = duration - t
        if rest <= rmax:
            d = rest
        else:
            hi = min(rmax, rest - rmin)  # phần còn lại sau đoạn này vẫn ≥ ngắn nhất
            if hi >= rmin:
                d = rng.uniform(rmin, hi)
            else:  # không chia được cho đủ dài: đoạn dài nhất, phần dư giữ riêng
                d = rmax
                if rest - d < MIN_PIECE:
                    d = rest
        out.append(Segment(t, d))
        t += d
    return out


def plan_segments(duration: float, s: SplitSettings, rng: random.Random | None = None) -> tuple[list[Segment], str]:
    """Danh sách đoạn cho một video + ghi chú (vàng) nếu app phải bỏ / đổi gì. Cài đặt sai → ValueError."""
    note = ""
    if duration <= EPS:
        raise ValueError("Video không có thời lượng")
    if s.mode == "parts":
        n = max(1, int(s.parts))
        if duration / n < MIN_PIECE:
            n = max(1, int(duration))
            note = f"Video dài {fmt_time(duration)} — chia tối đa {n} phần"
        return _even(duration, n), note
    if s.mode == "fixed":
        if s.fixed < MIN_PIECE:
            raise ValueError("Độ dài mỗi đoạn phải từ 1 giây")
        out = []
        t = 0.0
        while duration - t > EPS:
            d = min(s.fixed, duration - t)
            if d < MIN_PIECE and out:
                break
            out.append(Segment(t, d))
            t += d
        return out, note
    if s.mode == "random":
        if s.rmin < MIN_PIECE:
            raise ValueError("Đoạn ngắn nhất phải từ 1 giây")
        if s.rmin > s.rmax:
            raise ValueError("Khoảng ngẫu nhiên sai: số đầu phải nhỏ hơn số sau")
        return _random(duration, s.rmin, s.rmax, rng or random.Random()), note
    if s.mode == "marks":
        marks = parse_marks(s.marks)
        if not marks:
            raise ValueError("Chưa nhập mốc nào")
        outside = [m for m in marks if m <= EPS or m >= duration - EPS]
        cuts = sorted({round(m, 3) for m in marks if m not in outside})
        if outside:
            note = "Bỏ mốc ngoài video: " + ", ".join(fmt_time(m) for m in outside)
        edges = [0.0, *cuts, duration]
        return [Segment(a, b - a) for a, b in zip(edges, edges[1:])], note
    if s.mode == "ranges":
        ranges = parse_ranges(s.ranges)
        if not ranges:
            raise ValueError("Chưa nhập khoảng nào")
        out, skipped = [], []
        for a, b in ranges:
            if a >= duration - EPS:
                skipped.append(a)
                continue
            out.append(Segment(a, min(b, duration) - a))
        if not out:
            raise ValueError("Mọi khoảng đều nằm ngoài video")
        if skipped:
            note = "Bỏ khoảng ngoài video: " + ", ".join(fmt_time(a) for a in skipped)
        return out, note
    raise ValueError(f"Cách cắt không rõ: {s.mode}")


# ---------- kích thước + đổi tỉ lệ khung ----------
ASPECTS = ("keep", "9:16", "16:9", "1:1", "4:5")
FITS = ("blur", "black", "crop")
_RATIOS = {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1), "4:5": (4, 5)}


def _ev(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def out_size(w: int, h: int, aspect: str) -> tuple[int, int]:
    """Kích thước ra. 9:16 / 16:9: cạnh dài = cạnh dài nguồn; 1:1 / 4:5: cạnh dài = cạnh ngắn nguồn (không phóng
    to quá nguồn). Luôn số chẵn (H.264 yêu cầu)."""
    if aspect not in _RATIOS:
        return w, h
    rw, rh = _RATIOS[aspect]
    long = max(w, h) if aspect in ("9:16", "16:9") else min(w, h)
    if rw >= rh:
        return _ev(long), _ev(long * rh / rw)
    return _ev(long * rw / rh), _ev(long)


def aspect_filter(w: int, h: int, aspect: str, fit: str) -> str:
    """Chuỗi -vf đổi tỉ lệ: nền mờ / viền đen / cắt. "" = giữ nguyên."""
    if aspect not in _RATIOS:
        return ""
    W, H = out_size(w, h, aspect)  # noqa: N806
    if fit == "black":
        return (f"scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    if fit == "crop":
        return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    w4, h4 = _ev(W / 4), _ev(H / 4)  # làm mờ trên ảnh nhỏ rồi phóng lên: nhanh, mờ mịn
    return (f"split=2[bg][fg];"
            f"[bg]scale={w4}:{h4}:force_original_aspect_ratio=increase,crop={w4}:{h4},gblur=sigma=12,"
            f"scale={W}:{H}[b];"
            f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2[f];"
            f"[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1")


def split_args(src: str, seg: Segment, out: Path, info: MediaInfo, s: SplitSettings, encoder: str) -> list[str]:
    """Tham số FFmpeg cắt một đoạn (không gồm tên chương trình). Nhanh = chép nguyên (-c copy), bỏ qua đổi tỉ lệ."""
    head = ["-ss", f"{seg.start:.3f}", "-i", src, "-t", f"{seg.dur:.3f}", "-map", "0:v:0", "-map", "0:a?"]
    if not s.exact:
        return [*head, "-c", "copy", "-avoid_negative_ts", "make_zero", str(out)]
    flt = aspect_filter(info.width, info.height, s.aspect, s.fit)
    gop = max(1, round(float(info.fps or 30) * 2))
    return [*head, *(["-vf", flt] if flt else []), *encoders.encoder_args(encoder, "high", gop),
            "-pix_fmt", encoders.pix_fmt(encoder), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(out)]


# ---------- xuất ảnh ----------
FRAME_MODES = ("count", "every_sec", "every_n", "scene")


@dataclass
class FrameSettings:
    mode: str = "count"
    count: int = 100
    every_sec: float = 5.0
    every_n: int = 150
    scene: int = 10
    fmt: str = "jpg"
    per_video: bool = True
    open_after: bool = False


def scene_threshold(pct: int) -> float:
    """% thay đổi giữa hai khung → ngưỡng điểm đổi cảnh của FFmpeg (10 % → 0,10). Số nhỏ = nhiều ảnh."""
    return max(1, min(100, int(pct))) / 100


def frame_args(src: str, info: MediaInfo, s: FrameSettings, pattern: Path) -> list[str]:
    """Tham số FFmpeg xuất ảnh ra `pattern` (vd …/tên_%04d.jpg)."""
    d = max(info.duration, 0.001)
    pre: list[str] = []
    post: list[str] = []
    if s.mode == "count":
        n = max(1, int(s.count))
        # ảnh thứ k = khung đầu tiên từ mốc t0 + k × bước (giữa từng khoảng đều nhau). Chọn theo mốc tuyệt đối:
        # bộ lọc fps hay rơi mất ảnh cuối ở video ngắn, còn "cách ảnh trước ≥ bước" thì trôi dần.
        t0, step = f"{d / (2 * n):.4f}".rstrip("0").rstrip("."), f"{d / n:.6f}".rstrip("0").rstrip(".")
        flt = ("select=gte(t\\," + t0 + ")*(isnan(prev_selected_t)+gt(floor((t-" + t0 + ")/" + step
               + ")\\,floor((prev_selected_t-" + t0 + ")/" + step + ")))")
        post = ["-fps_mode", "vfr", "-frames:v", str(n)]
    elif s.mode == "every_sec":
        flt = f"fps=1/{max(0.01, float(s.every_sec)):g}"
    elif s.mode == "every_n":
        flt = "select=not(mod(n\\," + f"{max(1, int(s.every_n))}))"
        post = ["-fps_mode", "vfr"]
    else:
        flt = "select=eq(n\\,0)+gt(scene\\," + f"{scene_threshold(s.scene):g})"
        post = ["-fps_mode", "vfr"]
    q = ["-q:v", "2"] if s.fmt == "jpg" else []
    return [*pre, "-i", src, "-map", "0:v:0", "-vf", flt, *post, *q, str(pattern)]


def frame_estimate(info: MediaInfo, s: FrameSettings) -> int | None:
    """Số ảnh dự kiến (đổi cảnh: không biết trước → None)."""
    if s.mode == "count":
        return max(1, int(s.count))
    if s.mode == "every_sec":
        return max(1, int(info.duration / max(0.01, s.every_sec) + EPS))
    if s.mode == "every_n":
        frames = info.nb_frames or info.duration * float(info.fps or 30)
        return max(1, int(frames / max(1, s.every_n) + EPS))
    return None


# ---------- đặt tên, không ghi đè ----------
def out_dir(folder: Path, src: str, per_video: bool) -> Path:
    """Thư mục ra. Thư mục riêng mỗi video: <thư mục>/<tên gốc>, đã có file thì "<tên gốc> (2)", (3)…"""
    folder = Path(folder)
    if not per_video:
        return folder
    stem = Path(src).stem
    k = 1
    while True:
        cand = folder / (stem if k == 1 else f"{stem} ({k})")
        if not cand.exists() or (cand.is_dir() and not any(cand.iterdir())):
            return cand
        k += 1


def unique_stem(folder: Path, stem: str, ext: str) -> str:
    """Tên gốc cho các file "<stem>_01.<ext>"…; đã có file cùng kiểu trong thư mục → "<stem> (2)"…"""
    folder = Path(folder)
    k = 1
    while True:
        cand = stem if k == 1 else f"{stem} ({k})"
        if not own_files(folder, cand, ext):
            return cand
        k += 1


def glob_escape(text: str) -> str:
    """Ký tự đặc biệt của glob ([ ] * ?) trong tên file → khớp đúng chữ."""
    return "".join(f"[{ch}]" if ch in "[]*?" else ch for ch in text)


def digits(n: int, minimum: int) -> int:
    return max(minimum, len(str(max(0, int(n)))))


def own_files(folder: Path, stem: str, ext: str) -> list[Path]:
    """Các file "<stem>_<số>.<ext>" trong thư mục (đúng tên gốc này, không lẫn video khác)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    pat = re.compile(re.escape(stem) + r"_\d+\." + re.escape(ext) + r"$", re.IGNORECASE)
    return sorted(p for p in folder.iterdir() if pat.match(p.name))


# ---------- chạy thật ----------
@dataclass
class RunResult:
    files: list[Path]
    errors: list[str]
    folder: Path
    total: int | None = None  # số đoạn dự định (xuất ảnh: None)


def _out_seconds(block: dict) -> float | None:
    raw = block.get("out_time_us") or block.get("out_time_ms") or ""
    try:
        return int(raw) / 1e6  # cả hai trường đều là micro giây
    except ValueError:
        return None


def _last_line(err: Exception) -> str:
    lines = [x for x in str(err).strip().splitlines() if x.strip()]
    return lines[-1].strip() if lines else "lỗi không rõ"


def split_video(runner, src: str, info: MediaInfo, s: SplitSettings, folder: Path, encoder: str,
                segments: list[Segment], on_progress=None, on_file=None,
                reuse: tuple[Path, str] | None = None) -> RunResult:
    """Cắt `segments` của một video ra <thư mục>/<tên gốc>_01.mp4…; đoạn lỗi ghi vào errors rồi chạy tiếp.
    `reuse` = (thư mục, tên gốc) của lượt bị Dừng trước đó: ghi lại đúng chỗ đó (ghi đè file của chính app).
    Bị Dừng → xoá file đang ghi dở, ném CancelledError có thuộc tính `files` (các đoạn đã xong)."""
    from .ffmpeg_tools import CancelledError, FFmpegError
    ext = ".mp4" if s.exact else (Path(src).suffix.lower() or ".mp4")
    if reuse:
        d, stem = Path(reuse[0]), reuse[1]
    else:
        d = out_dir(folder, src, s.per_video)
        stem = unique_stem(d, Path(src).stem, ext[1:])
    d.mkdir(parents=True, exist_ok=True)
    n = len(segments)
    nd = digits(n, 2)
    total = sum(x.dur for x in segments) or 1.0
    files: list[Path] = []
    errors: list[str] = []
    done = 0.0
    for i, seg in enumerate(segments):
        text = f"đoạn {i + 1}/{n}"
        out = d / f"{stem}_{i + 1:0{nd}d}{ext}"
        if on_progress:
            on_progress(min(1.0, done / total), text)

        def prog(block, base=done, seg=seg, text=text):
            t = _out_seconds(block)
            if t is not None and on_progress:
                on_progress(min(1.0, (base + min(max(t, 0.0), seg.dur)) / total), text)
        try:
            runner.ffmpeg(split_args(src, seg, out, info, s, encoder), on_progress=prog)
        except CancelledError as e:
            out.unlink(missing_ok=True)
            e.files, e.folder, e.stem, e.total = files, d, stem, n  # để chạy lại đúng chỗ (reuse)
            raise
        except FFmpegError as e:
            out.unlink(missing_ok=True)
            errors.append(f"Đoạn {i + 1}: {_last_line(e)}")
        else:
            files.append(out)
            if on_file:
                on_file(out)
        done += seg.dur
    if on_progress:
        on_progress(1.0, f"đoạn {n}/{n}")
    return RunResult(files, errors, d, n)


def extract_frames(runner, src: str, info: MediaInfo, s: FrameSettings, folder: Path,
                   on_progress=None, reuse: tuple[Path, str] | None = None) -> RunResult:
    """Xuất ảnh ra <thư mục>/<tên gốc>_0001.jpg…; bị Dừng → CancelledError có `files` (ảnh đã ra)."""
    from .ffmpeg_tools import CancelledError, FFmpegError
    ext = "png" if s.fmt == "png" else "jpg"
    if reuse:
        d, stem = Path(reuse[0]), reuse[1]
    else:
        d = out_dir(folder, src, s.per_video)
        stem = unique_stem(d, Path(src).stem, ext)
    d.mkdir(parents=True, exist_ok=True)
    nd = digits(frame_estimate(info, s) or 9999, 4)
    # mẫu tên của FFmpeg: mọi "%" có sẵn trong đường dẫn (cả tên thư mục) phải viết thành "%%"
    pattern = Path(str(d / stem).replace("%", "%%") + f"_%0{nd}d.{ext}")
    total = max(info.duration, 0.001)

    def prog(block):
        t = _out_seconds(block)
        if t is not None and on_progress:
            on_progress(min(1.0, max(t, 0.0) / total), "")
    if on_progress:
        on_progress(0.0, "")
    errors: list[str] = []
    try:
        runner.ffmpeg(frame_args(src, info, s, pattern), on_progress=prog)
    except CancelledError as e:
        e.files, e.folder, e.stem, e.total = own_files(d, stem, ext), d, stem, None
        raise
    except FFmpegError as e:
        errors.append(_last_line(e))
    files = own_files(d, stem, ext)
    if on_progress:
        on_progress(1.0, "")
    if not files and not errors:
        errors.append("Không lấy được ảnh nào")
    return RunResult(files, errors, d)
