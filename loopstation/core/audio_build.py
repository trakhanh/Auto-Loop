"""Đo âm lượng, dựng filtergraph cho nhạc (crossfade, lặp, fade) và trộn âm gốc."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from . import ffmpeg_tools as ft
from .planner import MusicItem
from .project import MusicSettings

_lock = threading.Lock()


def _loudness_db() -> dict:
    p = ft.data_dir() / "loudness.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def _file_id(path: str) -> str:
    st = os.stat(path)
    return f"{os.path.normcase(os.path.abspath(path))}:{st.st_size}:{st.st_mtime_ns}"


def cached_loudness(path: str) -> float | None:
    try:
        return _loudness_db().get(_file_id(path))
    except OSError:
        return None


def volume_db(pct: int) -> float:
    """% âm lượng (100 = giữ nguyên) → dB. 0% = tắt hẳn."""
    import math
    return -90.0 if pct <= 0 else 20 * math.log10(pct / 100)


def track_gains(runner: ft.Runner, ms: MusicSettings, paths: dict[int, str], log=None, on_step=None) -> dict[int, float]:
    """Độ khuếch đại (dB) cho từng bài đang dùng: chuẩn hoá về mức LUFS đích (nếu bật) + âm lượng riêng của bài."""
    gains: dict[int, float] = {}
    tracks = sorted(paths)
    for k, t in enumerate(tracks):
        if ms.loudness_enabled:
            if on_step:
                on_step(k, len(tracks))
            lufs = measure_loudness(runner, paths[t])
            if lufs is not None:
                gains[t] = max(-20.0, min(20.0, ms.lufs - lufs))
                if log:
                    log(f"  {Path(paths[t]).name}: {lufs:.1f} LUFS → {gains[t]:+.1f} dB")
        vol = ms.tracks[t].volume if 0 <= t < len(ms.tracks) else 100
        if vol != 100:
            gains[t] = gains.get(t, 0.0) + volume_db(vol)
            if log:
                log(f"  {Path(paths[t]).name}: âm lượng riêng {vol}% ({volume_db(vol):+.1f} dB)")
    return gains


def measure_loudness(runner: ft.Runner, path: str) -> float | None:
    """Độ to tích hợp (LUFS) của bài. Có cache trên đĩa."""
    cached = cached_loudness(path)
    if cached is not None:
        return cached
    stderr = runner.ffmpeg(["-v", "info", "-i", path, "-vn", "-af",
                            "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr)
    if not m:
        return None
    try:
        value = float(json.loads(m.group(0))["input_i"])
    except (ValueError, KeyError):
        return None
    if value < -70:  # bài gần như im lặng
        return None
    with _lock:
        db = _loudness_db()
        db[_file_id(path)] = value
        (ft.data_dir() / "loudness.json").write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
    return value


def escape_filter_value(value: str) -> str:
    """Escape một giá trị option nằm trong filtergraph (2 cấp: option rồi graph)."""
    level1 = re.sub(r"([\\':])", r"\\\1", value)
    return re.sub(r"([\\'\[\],;])", r"\\\1", level1)


def music_graph(
    items: list[MusicItem],
    paths: dict[int, str],
    gains_db: dict[int, float],
    ms: MusicSettings,
    total: float,
    out_label: str = "music",
) -> list[str]:
    """Các dòng filtergraph tạo nhãn [out_label] dài đúng `total` giây."""
    lines = []
    xf = ms.crossfade if ms.crossfade > 0 else 0.0
    n = len(items)
    for k, it in enumerate(items):
        src = escape_filter_value(paths[it.track].replace("\\", "/"))
        chain = (f"amovie=filename={src},asetpts=PTS-STARTPTS,aresample=48000,"
                 f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                 f"volume={gains_db.get(it.track, 0.0):.2f}dB,"
                 # MP3 VBR thiếu header / AAC thô: ffprobe đoán dài hơn thực tế → đệm im lặng cho đúng độ dài
                 # đã lên lịch, để bài sau không bị lệch (không có khoảng lặng giữa chừng / 2 bài chồng nhau)
                 f"apad=whole_dur={it.duration:.6f},atrim=end={it.duration:.6f}")
        if xf > 0 and k > 0:
            chain += f",afade=t=in:d={xf:.3f}:curve=tri"
        if xf > 0 and k < n - 1:
            chain += f",afade=t=out:st={it.duration - xf:.6f}:d={xf:.3f}:curve=tri"
        if xf == 0 and ms.gap > 0 and k < n - 1:
            chain += f",apad=pad_dur={ms.gap:.3f}"
        lines.append(f"{chain}[m{k}];")
    if n == 1:
        last = "m0"
    elif xf > 0:
        # Crossfade bằng 2 "làn": bài chẵn ở làn A, bài lẻ ở làn B, đệm khoảng lặng cho đúng
        # vị trí rồi trộn 2 làn. Chi phí tuyến tính, không bị chậm dần như chuỗi acrossfade.
        for lane in (0, 1):
            parts, pos = [], 0.0
            for k in range(lane, n, 2):
                it = items[k]
                if it.start - pos > 1e-4:
                    lab = f"z{k}"
                    lines.append(f"aevalsrc=exprs=0|0:s=48000:d={it.start - pos:.6f},"
                                 f"aformat=sample_fmts=fltp:channel_layouts=stereo[{lab}];")
                    parts.append(f"[{lab}]")
                parts.append(f"[m{k}]")
                pos = it.start + it.duration
            lines.append("".join(parts) + f"concat=n={len(parts)}:v=0:a=1[lane{lane}];")
        lines.append("[lane0][lane1]amix=inputs=2:normalize=0:duration=longest[xc];")
        last = "xc"
    else:
        lines.append("".join(f"[m{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1[xc];")
        last = "xc"
    tail = f"[{last}]apad,atrim=end={total:.6f}"
    if ms.fade_in > 0:
        tail += f",afade=t=in:d={min(ms.fade_in, total):.3f}"
    if ms.fade_out > 0:
        fo = min(ms.fade_out, total)
        tail += f",afade=t=out:st={total - fo:.6f}:d={fo:.3f}"
    lines.append(f"{tail}[{out_label}];")
    return lines


def seamless_loop(runner: ft.Runner, path: str, duration: float) -> str:
    """Bản lặp liền mạch của một lớp tiếng nền: đoạn cuối hoà dần vào đoạn đầu (equal-power), nên khi lặp lại
    không còn tiếng "khựng" ở chỗ nối. Lưu bộ nhớ đệm (FLAC) theo file + độ dài."""
    if duration < 1.0:
        return path
    x = min(3.0, duration * 0.2)
    st = os.stat(path)
    import hashlib
    key = hashlib.sha1(f"loop2|{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{st.st_mtime_ns}|{duration:.3f}"
                       .encode("utf-8")).hexdigest()[:24]
    out = ft.cache_dir("ambient") / f"{key}.flac"
    if out.is_file() and out.stat().st_size > 0:
        return str(out)
    d = duration
    graph = (f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=3[a][b][c];"
             f"[a]atrim=start={x:.6f}:end={d - x:.6f},asetpts=PTS-STARTPTS[mid];"
             f"[b]atrim=start={d - x:.6f}:end={d:.6f},asetpts=PTS-STARTPTS,afade=t=out:d={x:.6f}:curve=qsin[tail];"
             f"[c]atrim=start=0:end={x:.6f},asetpts=PTS-STARTPTS,afade=t=in:d={x:.6f}:curve=qsin[head];"
             f"[tail][head]amix=inputs=2:normalize=0:duration=longest[x];"
             f"[mid][x]concat=n=2:v=0:a=1[out]")
    tmp = out.with_name(f"{key}.{os.getpid()}-{threading.get_ident()}.tmp.flac")
    try:
        runner.ffmpeg(["-v", "error", "-i", path, "-filter_complex", graph, "-map", "[out]", "-c:a", "flac",
                       str(tmp)])
        os.replace(tmp, out)
    except ft.CancelledError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception:  # noqa: BLE001 — không tạo được thì dùng file gốc (lặp thẳng)
        tmp.unlink(missing_ok=True)
        return path
    return str(out)


def ambient_graph(paths: list[str], volumes: list[int], total: float, fade_in: float = 0.0,
                  fade_out: float = 0.0) -> tuple[list[str], list[str]]:
    """Mỗi lớp tiếng nền tự lặp vô hạn rồi cắt đúng `total` giây. Trả về (dòng graph, nhãn)."""
    lines, labels = [], []
    for k, (path, vol) in enumerate(zip(paths, volumes)):
        src = escape_filter_value(path.replace("\\", "/"))
        lines.append(f"amovie=filename={src}:loop=0,asetpts=N/SR/TB,aresample=48000,"
                     f"aformat=sample_fmts=fltp:channel_layouts=stereo,volume={vol / 100:.3f},"
                     f"atrim=end={total:.6f}{_fades(fade_in, fade_out, total)}[amb{k}];")
        labels.append(f"amb{k}")
    return lines, labels


def _fades(fade_in: float, fade_out: float, total: float) -> str:
    out = ""
    if fade_in > 0:
        out += f",afade=t=in:d={min(fade_in, total):.3f}"
    if fade_out > 0:
        fo = min(fade_out, total)
        out += f",afade=t=out:st={total - fo:.6f}:d={fo:.3f}"
    return out


def master_graph(
    music_label: str | None,
    source_label: str | None,
    music_volume: int,
    source_volume: int,
    total: float,
    ambient_labels: list[str] | None = None,
) -> list[str]:
    """Trộn nhạc + tiếng gốc + tiếng nền, chống vỡ tiếng, ra nhãn [aout]."""
    parts = []
    inputs = []
    if music_label:
        parts.append(f"[{music_label}]volume={music_volume / 100:.3f}[mv];")
        inputs.append("[mv]")
    if source_label:
        parts.append(f"[{source_label}]aresample=48000:async=1,apad,atrim=end={total:.6f},"
                     f"volume={source_volume / 100:.3f}[sv];")
        inputs.append("[sv]")
    inputs += [f"[{lab}]" for lab in ambient_labels or []]
    if len(inputs) > 1:
        parts.append(f"{''.join(inputs)}amix=inputs={len(inputs)}:normalize=0:duration=longest[mx];")
        src = "[mx]"
    else:
        src = inputs[0]
    parts.append(f"{src}apad,alimiter=limit=0.891:level=0:latency=1,atrim=end={total:.6f}[aout]")
    return parts
