"""Encode các khối video (thân lần phát, đoạn crossfade) cùng thông số để nối bằng stream copy."""
from __future__ import annotations

import hashlib
import os
import threading
from fractions import Fraction
from pathlib import Path

from . import encoders
from . import ffmpeg_tools as ft
from .planner import Segment
from .probe import IMAGE_EXTS

BLOCK_VERSION = "v4"  # v4: clip HD không ghi hệ màu được coi là bt709 (không đổi màu, không nhiễu chuyển đổi)
COLOR_TAGS = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
SAMPLE_RATE = 48000


def fit_chain(fit: str, w: int, h: int, p: str = "") -> str:
    """Đưa khung hình về w×h. `p`: tiền tố nhãn để dùng nhiều lần trong một filtergraph."""
    sc = "flags=lanczos"
    if fit == "stretch":
        return f"scale={w}:{h}:{sc},setsar=1"
    if fit == "crop":
        return (f"scale={w}:{h}:force_original_aspect_ratio=increase:{sc},"
                f"crop={w}:{h},setsar=1")
    if fit == "blur":
        # làm mờ ở độ phân giải 1/8 rồi phóng lại: nhanh hơn rất nhiều so với mờ ở khung gốc
        sw, sh = max(2, w // 8 // 2 * 2), max(2, h // 8 // 2 * 2)
        return (f"split[{p}a][{p}b];"
                f"[{p}a]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
                f"boxblur=luma_radius=8:luma_power=2:chroma_radius=4,scale={w}:{h}[{p}bg];"
                f"[{p}b]scale={w}:{h}:force_original_aspect_ratio=decrease:{sc}[{p}fg];"
                f"[{p}bg][{p}fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    # letterbox (mặc định)
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease:{sc},"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")


def timescale(fps: Fraction) -> int:
    return fps.numerator * 1000 if fps.denominator == 1 else fps.numerator


def _key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:24]


def _file_id(path: str) -> str:
    st = os.stat(path)
    return f"{os.path.normcase(os.path.abspath(path))}:{st.st_size}:{st.st_mtime_ns}"


def seconds(frames: int, fps: Fraction) -> float:
    return float(Fraction(frames) / fps)


def _input(path: str, fps: Fraction) -> list[str]:
    """Tham số đầu vào: ảnh tĩnh được lặp thành luồng hình ở đúng fps."""
    if os.path.splitext(path)[1].lower() in IMAGE_EXTS:
        return ["-loop", "1", "-framerate", f"{fps.numerator}/{fps.denominator}", "-i", path]
    hw = ft.OPTIONS.get("hwdec")
    return (["-hwaccel", hw] if hw else []) + ["-i", path]


def color_fix(path: str) -> str:
    """Clip HD không ghi hệ màu (rất hay gặp ở video tạo bằng AI / xuất từ web): ffmpeg mặc định coi là hệ SD cũ
    (bt601) rồi đổi sang bt709 khi xuất → màu lệch nhẹ so với clip gốc và thêm nhiễu làm file nặng hơn 20–25%.
    Trình phát luôn hiểu clip HD không ghi hệ màu là bt709 → gắn đúng nhãn đó (không chuyển đổi gì)."""
    if not path or os.path.splitext(path)[1].lower() in IMAGE_EXTS:
        return ""
    from .probe import probe
    info = probe(path)
    if not info.ok:
        return ""
    if info.wide_gamut:  # HDR / bt2020 thiếu nhãn phụ: điền theo bt2020 (không phải bt709) để tone_chain đổi đúng
        parts = [f"{k}={v}" for k, v, have in (("colorspace", "bt2020nc", info.color_space),
                                                ("color_primaries", "bt2020", info.color_primaries)) if not have]
        return f"setparams={':'.join(parts)}," if parts else ""
    if not (max(info.width, info.height) >= 1280 or min(info.width, info.height) >= 720):
        return ""  # SD: giữ cách hiểu mặc định (bt601)
    parts = [f"{k}=bt709" for k, have in (("colorspace", info.color_space), ("color_primaries", info.color_primaries),
                                          ("color_trc", info.color_transfer)) if not have]
    if not info.color_range:
        parts.append("range=tv")
    return f"setparams={':'.join(parts)}," if parts else ""


SDR_WHITE_NITS = 203  # BT.2408: trắng chuẩn của HDR = trắng 100 % của SDR
TONE_VERSION = "t1"  # đổi khi đổi cách chuyển HDR → SDR (khối cũ trong bộ nhớ đệm không còn dùng)


def tone_chain(path: str) -> str:
    """Clip HDR (HLG / PQ) hoặc gam màu rộng bt2020 → SDR bt709 (kết thúc bằng dấu phẩy; "" = clip thường).
    Không chuyển thì hình bị xỉn, tối, lệch màu hẳn: điểm ảnh HDR bị hiểu như SDR. Trắng chuẩn HDR (203 nit) thành
    trắng SDR, vùng sáng hơn được nén mềm (mobius, giữ nguyên dưới 80 %) — màu sát bản gốc nhất khi đo thử.
    Đặt SAU bước đổi cỡ khung: chuyển ở độ phân giải xuất nhanh hơn ~3 lần so với ở khung 4K gốc."""
    if not path or os.path.splitext(path)[1].lower() in IMAGE_EXTS:
        return ""
    from .probe import probe
    info = probe(path)
    if not info.ok or not info.wide_gamut:
        return ""
    lin = f"zscale=t=linear:npl={SDR_WHITE_NITS},format=gbrpf32le,zscale=p=bt709,"
    tm = "tonemap=mobius:param=0.8:desat=0," if info.hdr else ""
    return f"{lin}{tm}zscale=t=bt709:m=bt709:r=tv,format=yuv420p,"


def color_key(*paths: str) -> list[str]:
    """Phần thêm vào khoá bộ nhớ đệm: chỉ clip phải chuyển màu (HDR) mới đổi khoá — khối của clip thường giữ nguyên."""
    return [TONE_VERSION] if any(tone_chain(p) for p in paths) else []


def _norm(fit: str, w: int, h: int, fps: Fraction, p: str = "", path: str = "") -> str:
    """Chuỗi chuẩn hoá chung: hệ màu, khung hình, HDR → SDR, fps cố định, đệm frame cuối để luôn đủ frame."""
    return (f"{color_fix(path)}setpts=PTS-STARTPTS,{fit_chain(fit, w, h, p)},{tone_chain(path)}"
            f"fps={fps.numerator}/{fps.denominator},tpad=stop_mode=clone:stop_duration=5")


def _run_cached(runner: ft.Runner, sub: str, key: str, ext: str, build) -> Path:
    out = ft.cache_dir(sub) / f"{key}{ext}"
    if out.is_file() and out.stat().st_size > 0:
        try:
            os.utime(out)  # đánh dấu vừa dùng: tự dọn bộ nhớ đệm sẽ xoá khối lâu không dùng trước
        except OSError:
            pass
        return out
    # tên tạm riêng cho từng luồng / tiến trình: hai lượt cùng tạo một khối không ghi đè lên nhau
    tmp = out.with_name(f"{key}.{os.getpid()}-{threading.get_ident()}.tmp{ext}")
    try:
        runner.ffmpeg(build(str(tmp)))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, out)
    return out


def segment_look(seg: Segment, look, look_bookends: bool):
    """Màu & logo cho một khối: mặc định không áp lên khối chỉ có Intro/Outro (trừ `look_bookends`).
    Trả về (look hoặc None, side): side = "a"/"b" khi crossfade giữa Intro/Outro và clip chính — chỉ áp màu & logo
    lên phía clip chính (không "bật" đột ngột lên intro)."""
    main = seg.clip >= 0 or (seg.kind == "xfade" and seg.clip_b >= 0)
    if look is not None and not (look.active and (main or look_bookends)):
        look = None
    side = ""
    if look is not None and seg.kind == "xfade" and not look_bookends:
        side = "a" if seg.clip_b < 0 <= seg.clip else ("b" if seg.clip < 0 <= seg.clip_b else "")
    return look, side


def segment_graph(seg: Segment, paths: dict[int, str], fps: Fraction, width: int, height: int, fit: str, pix: str,
                  fade: float, off_a: int, off_b: int, look, side: str, skip: int = 0, seek_a: int = 0) -> str:
    """Filtergraph của một khối (chỉ hình) → nhãn [v]. Dùng chung cho lúc xuất (mã hoá) và bộ phát xem trước
    (khung hình thô), nên hình xem trước giống hệt bản xuất.
    `skip`: bỏ `skip` frame đầu của khối (xem trước bắt đầu giữa khối).
    `seek_a`: số frame đầu vào A đã được tua sẵn bằng -ss (xem trước clip dài: không giải mã lại từ đầu clip)."""
    from .look import graph as look_graph
    n = seg.frames
    n_out = n - skip
    fade_f = ""
    if fade > 0:
        st = seconds(n, fps) - fade - seconds(skip, fps)
        fade_f = (f",fade=t=out:st={st:.6f}:d={fade:.6f}" if st >= 0
                  else f",fade=t=out:st=0:d={max(0.001, fade + st):.6f}")  # bắt đầu giữa đoạn mờ dần
    a0 = seg.start + off_a + skip - seek_a
    if seg.kind == "body":
        pre = (f"[0:v]{_norm(fit, width, height, fps, '', paths[seg.clip])},"
               f"trim=start_frame={a0}:end_frame={a0 + n_out},setpts=PTS-STARTPTS")
        if look is not None:
            fx = (fade_f[1:] + ",") if fade_f else ""
            return f"{pre}[pre];{look_graph(look, 'pre', 'lk', width, height)};[lk]{fx}format={pix}[v]"
        return f"{pre}{fade_f},format={pix}[v]"
    d = seconds(n, fps)
    graph = (f"[0:v]{_norm(fit, width, height, fps, 'x', paths[seg.clip])},"
             f"trim=start_frame={seg.start + off_a}:end_frame={seg.end + off_a},setpts=PTS-STARTPTS[va];"
             f"[1:v]{_norm(fit, width, height, fps, 'y', paths[seg.clip_b])},"
             f"trim=start_frame={off_b}:end_frame={off_b + n},setpts=PTS-STARTPTS[vb];")
    va, vb = "va", "vb"
    if look is not None and side:
        src = "va" if side == "a" else "vb"
        graph += f"{look_graph(look, src, src + 'l', width, height, 'l' + side)};"
        va, vb = (va + "l", vb) if side == "a" else (va, vb + "l")
    graph += f"[{va}][{vb}]xfade=transition=fade:duration={d:.6f}:offset=0"
    tr = f"trim=start_frame={skip},setpts=PTS-STARTPTS," if skip else ""
    if look is not None and not side:
        graph += f"[xv];{look_graph(look, 'xv', 'lk', width, height)};[lk]{tr}format={pix}[v]"
    else:
        graph += f",{tr}format={pix}[v]"
    return graph


def encode_segment(
    runner: ft.Runner,
    seg: Segment,
    paths: dict[int, str],
    fps: Fraction,
    width: int,
    height: int,
    fit: str,
    encoder: str,
    quality: str,
    fade_out: float = 0.0,
    offsets: dict[int, int] | None = None,
    maxrate: int = 0,
    look=None,
    look_bookends: bool = False,
    strict_cap: bool = False,
) -> Path:
    """Encode một khối (chỉ hình). Cùng nội dung + thông số thì dùng lại từ cache.
    `offsets`: số frame bỏ ở đầu mỗi clip (cắt chỉ lấy đoạn giữa); vị trí trong `seg` tính từ sau đoạn bỏ.
    `look`: màu & logo (core.look.Look); mặc định không áp lên khối chỉ có Intro/Outro (trừ `look_bookends`)."""
    n = seg.frames
    look, side = segment_look(seg, look, look_bookends)
    fade = min(fade_out, seconds(n, fps)) if seg.fade else 0.0
    off_a = (offsets or {}).get(seg.clip, 0)
    off_b = (offsets or {}).get(seg.clip_b, 0) if seg.kind == "xfade" else 0
    ids = [_file_id(paths[seg.clip])] + ([_file_id(paths[seg.clip_b])] if seg.kind == "xfade" else [])
    key = _key(BLOCK_VERSION, seg.kind, *ids, seg.start + off_a, seg.end + off_a, off_b, fps, width, height,
               fit, encoder, quality, f"{fade:.3f}", *([f"max{maxrate}{'s' if strict_cap else ''}"] if maxrate else []),
               *([f"look{look.key()}"] if look is not None else []), *([f"side{side}"] if side else []),
               *color_key(*(paths[seg.clip], *([paths[seg.clip_b]] if seg.kind == "xfade" else []))))
    pix = encoders.pix_fmt(encoder)
    gop = max(1, round(float(fps) * 2))
    tail = (["-frames:v", str(n), *encoders.encoder_args(encoder, quality, gop, maxrate, strict_cap),
             *COLOR_TAGS,
             "-video_track_timescale", str(timescale(fps)), "-an", "-sn", "-dn", "-f", "mp4"])
    graph = segment_graph(seg, paths, fps, width, height, fit, pix, fade, off_a, off_b, look, side)
    inputs = _input(paths[seg.clip], fps) + (_input(paths[seg.clip_b], fps) if seg.kind == "xfade" else [])

    def build(out: str) -> list[str]:
        return ["-v", "error", *inputs, "-filter_complex", graph, "-map", "[v]", *tail, out]

    return _run_cached(runner, "blocks", key, ".mp4", build)


def samples_of(frames: int, fps: Fraction) -> int:
    return round(Fraction(frames) / fps * SAMPLE_RATE)


def source_audio_segment(
    runner: ft.Runner,
    seg: Segment,
    paths: dict[int, str],
    audible: dict[int, bool],
    fps: Fraction,
    fade_out: float = 0.0,
    offsets: dict[int, int] | None = None,
    gains: dict[int, float] | None = None,
) -> Path:
    """Tiếng gốc khớp đúng khối video (WAV 48 kHz stereo). Clip tắt tiếng/không có tiếng → im lặng.
    `gains`: dB tự cân cho từng clip (audio_build.source_gains) — clip to / nhỏ khác nhau về cùng mức."""
    n_s = samples_of(seg.frames, fps)
    dur = n_s / SAMPLE_RATE
    fade = min(fade_out, dur) if seg.fade else 0.0
    offs = offsets or {}
    sides = [(seg.clip, samples_of(seg.start + offs.get(seg.clip, 0), fps))]
    if seg.kind == "xfade":
        sides.append((seg.clip_b, samples_of(offs.get(seg.clip_b, 0), fps)))
    ids = [(_file_id(paths[c]) if audible.get(c) else "silence", s) for c, s in sides]
    gdb = {c: round((gains or {}).get(c, 0.0), 2) for c, _ in sides}
    key = _key(BLOCK_VERSION, "a", seg.kind, *ids, n_s, f"{fade:.3f}",
               *(f"g{gdb[c]:.2f}" for c, _ in sides if gdb[c]))
    fmt = "aformat=sample_fmts=s16:channel_layouts=stereo"

    def build(out: str) -> list[str]:
        inputs, chains = [], []
        for k, (clip, start) in enumerate(sides):
            if audible.get(clip):
                inputs += ["-i", paths[clip]]
                vol = f"volume={gdb[clip]:.2f}dB," if gdb[clip] else ""
                chains.append(f"[{k}:a:0]asetpts=PTS-STARTPTS,aresample=48000,{vol}{fmt},apad,"
                              f"atrim=start_sample={start}:end_sample={start + n_s},"
                              f"asetpts=PTS-STARTPTS[s{k}]")
            else:
                inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                chains.append(f"[{k}:a]{fmt},atrim=end_sample={n_s}[s{k}]")
        if seg.kind == "xfade":
            chains.append(f"[s0][s1]acrossfade=ns={n_s}:c1=tri:c2=tri[mix]")
            last = "mix"
        else:
            last = "s0"
        f = f",afade=t=out:st={dur - fade:.6f}:d={fade:.6f}" if fade > 0 else ""
        chains.append(f"[{last}]anull{f}[out]")
        return ["-v", "error", *inputs, "-filter_complex", ";".join(chains), "-map", "[out]",
                "-c:a", "pcm_s16le", "-f", "wav", out]

    return _run_cached(runner, "srcaudio", key, ".wav", build)


def concat_line(path: Path | str) -> str:
    p = str(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{p}'"


def write_concat(list_path: Path, items: list[tuple[Path, float]]) -> None:
    """items: (file, thời lượng giây). Dòng `duration` giúp ghép không bị lệch thời gian."""
    lines = ["ffconcat version 1.0"]
    for path, dur in items:
        lines.append(concat_line(path))
        lines.append(f"duration {dur:.6f}")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
