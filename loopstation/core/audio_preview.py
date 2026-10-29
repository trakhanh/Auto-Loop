"""Nghe thử bản trộn âm: dựng nhanh ~20 giây âm thanh y như khi xuất (nhạc + tiếng gốc clip + tiếng nền,
đúng âm lượng của Bảng trộn âm và của từng bài), bắt đầu từ một mốc bất kỳ trên timeline.

Chỉ giải mã các bài / đoạn clip nằm trong khoảng nghe → vài giây là xong, kể cả video 10 tiếng."""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from pathlib import Path

from . import audio_build, planner, timeline, video_build
from . import ffmpeg_tools as ft
from .planner import MusicItem
from .probe import probe

PREVIEW_SECONDS = 20.0


class PreviewError(RuntimeError):
    pass


def clean_old(keep: str | None = None, min_age: float = 120.0) -> None:
    """Dọn bản nghe thử cũ. Chỉ xoá thứ đã cũ hơn `min_age` giây: nhiều chỗ dựng cùng lúc (Bảng trộn âm,
    cửa sổ Xem trước, hộp thoại hàng loạt) không xoá nhầm thư mục của nhau khi đang đọc dở."""
    now = time.time()
    for f in ft.preview_dir().glob("nghe-thu_*"):
        if keep and f.name == Path(keep).name:
            continue
        try:
            if now - f.stat().st_mtime < min_age:
                continue
            if f.is_dir():
                import shutil
                shutil.rmtree(f, ignore_errors=True)
            else:
                f.unlink()
        except OSError:
            pass


def music_change_points(tl: timeline.Timeline) -> list[float]:
    """Mốc chuyển bài (để nghe thử chỗ crossfade giữa 2 bài)."""
    return [it.start for it in tl.music_items[1:]]


@dataclass
class Stems:
    """Các kênh âm thanh riêng (WAV s16 48 kHz stereo, cùng độ dài) — app tự hoà khi phát để chỉnh âm lượng tức thì.
    key: "music" | "source" | "amb:<chỉ số lớp trong music.ambient>"."""
    files: dict[str, Path]
    start: float
    seconds: float
    folder: Path


def render_preview(project, start: float, runner: ft.Runner | None = None, version: int = 0,
                   seconds: float = PREVIEW_SECONDS) -> Path:
    """Một file WAV đã trộn sẵn theo âm lượng hiện tại (dùng khi không phát trực tiếp được / kiểm thử)."""
    return _render(project, start, runner, version, seconds, stems=False)


def render_stems(project, start: float, runner: ft.Runner | None = None, version: int = 0,
                 seconds: float = PREVIEW_SECONDS) -> Stems:
    """Các kênh riêng ở 100% (nhạc đã gồm chuẩn hoá LUFS + âm lượng từng bài). Ném PreviewError / CancelledError."""
    return _render(project, start, runner, version, seconds, stems=True)


def _render(project, start: float, runner: ft.Runner | None, version: int, seconds: float, stems: bool):
    runner = runner or ft.Runner()
    proj = project
    if stems:  # mọi lớp đang bật đều có kênh riêng (kể cả lớp đang để 0%)
        proj = copy.deepcopy(project)
        for a in proj.music.ambient:
            a.volume = 100 if a.enabled else 0
    vs, ms = proj.video, proj.music
    music_only = proj.output_kind == "music_only"
    tl = timeline.build_audio(proj, version) if music_only else timeline.build(proj)
    if not tl.ok:
        raise PreviewError("\n".join(tl.errors))
    total = tl.total
    if total <= 0:
        raise PreviewError("Thời lượng bằng 0.")
    start = max(0.0, min(start, max(0.0, total - 1.0)))
    end = min(total, start + seconds)
    dur = end - start
    if music_only and ms.versions > 1 and tl.version_seeds:
        ms = planner.music_variant(ms, tl.version_seeds[min(version, len(tl.version_seeds) - 1)])

    inputs: list[str] = []
    graph: list[str] = []
    work = ft.preview_dir() / f"nghe-thu_{time.strftime('%H%M%S')}_{id(runner) % 10000}"
    work.mkdir(parents=True, exist_ok=True)

    # ----- nhạc: chỉ các bài chạm khoảng nghe (+1 bài trước để crossfade vào đúng) -----
    music_label = None
    items = tl.music_items if tl.use_music else []
    hit = [k for k, it in enumerate(items) if it.start < end and it.start + it.duration > start]
    if hit:
        k0, k1 = max(0, hit[0] - 1), hit[-1]
        sub = items[k0:k1 + 1]
        base = sub[0].start
        shifted = [MusicItem(it.track, it.start - base, it.duration) for it in sub]
        paths = {it.track: tl.track_infos[it.track].path for it in sub}
        gains = audio_build.track_gains(runner, ms, paths)
        runner.check()
        m2 = copy.copy(ms)
        m2.fade_in = ms.fade_in if base <= 0 else 0.0
        m2.fade_out = ms.fade_out if end >= total - 1e-3 else 0.0
        graph += audio_build.music_graph(shifted, paths, gains, m2, end - base, "mfull")
        graph.append(f"[mfull]atrim=start={start - base:.6f},asetpts=PTS-STARTPTS[music];")
        music_label = "music"

    # ----- tiếng gốc clip: các khối nằm trong khoảng nghe (dùng chung bộ nhớ đệm với lúc xuất) -----
    source_label = None
    if not music_only and tl.use_source and tl.video is not None:
        segs = planner.segments(tl.video, tl.frames)
        paths = {k: inf.path for k, inf in tl.clip_infos.items()}
        pos, chosen, p0 = 0.0, [], None
        for seg in segs:
            d = video_build.seconds(seg.frames, tl.fps)
            if pos < end and pos + d > start:
                if p0 is None:
                    p0 = pos
                chosen.append((seg, d))
            pos += d
            if pos >= end:
                break
        if chosen:
            blocks = []
            sgains = (audio_build.source_gains(runner, paths, tl.audible, project.music.lufs)
                      if vs.source_level else {})
            for seg, d in chosen:
                runner.check()
                blocks.append((video_build.source_audio_segment(runner, seg, paths, tl.audible, tl.fps, vs.fade_out,
                                                                tl.offsets, sgains), d))
            alist = work / "source.ffconcat"
            video_build.write_concat(alist, blocks)
            inputs += ["-f", "concat", "-safe", "0", "-i", str(alist)]
            graph.append(f"[0:a]atrim=start={start - p0:.6f},asetpts=PTS-STARTPTS[src];")
            source_label = "src"

    # ----- tiếng nền -----
    ambient_labels: list[str] = []
    if tl.ambient_infos:
        keys = sorted(tl.ambient_infos)
        a_paths = [audio_build.seamless_loop(runner, tl.ambient_infos[k].path, tl.ambient_infos[k].duration)
                   for k in keys]
        offsets = []  # đang ở giây thứ mấy của vòng lặp tiếng nền tại mốc `start` (giống bản xuất)
        for ap in a_paths:
            loop_len = probe(ap).duration
            offsets.append(start % loop_len if loop_len and loop_len > 0.5 else 0.0)
        lines, ambient_labels = audio_build.ambient_graph(
            a_paths, [ms.ambient[k].volume for k in keys], dur,
            ms.fade_in if start <= 0 else 0.0, ms.fade_out if end >= total - 1e-3 else 0.0, offsets)
        graph += lines

    if not (music_label or source_label or ambient_labels):
        raise PreviewError("Chưa có âm thanh nào để nghe: thêm nhạc / tiếng nền, hoặc giữ tiếng gốc của clip.")
    clean_old(keep=str(work))
    pcm = ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", "-t", f"{dur:.6f}"]
    import shutil
    if not stems:
        graph += audio_build.master_graph(music_label, source_label, vs.music_volume,
                                          0 if music_only else vs.source_volume, dur, ambient_labels)
        gpath = work / "graph.txt"
        gpath.write_text("\n".join(graph), encoding="utf-8")
        out = ft.preview_dir() / f"{work.name}.wav"
        try:
            runner.ffmpeg(["-v", "error", *inputs, "-/filter_complex", str(gpath), "-map", "[aout]", *pcm, str(out)])
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return out
    # mỗi nguồn một file, cùng độ dài, CHƯA nhân âm lượng của Bảng trộn âm (app nhân khi phát)
    labels = {}
    if music_label:
        labels["music"] = music_label
    if source_label and not music_only:
        graph.append(f"[{source_label}]aresample=48000:async=1[srcr];")
        labels["source"] = "srcr"
    for k, lab in zip(sorted(tl.ambient_infos), ambient_labels):
        labels[f"amb:{k}"] = lab
    files: dict[str, Path] = {}
    for key, lab in labels.items():
        graph.append(f"[{lab}]aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=end={dur:.6f}"
                     f"[o{len(files)}];")
        files[key] = work / f"{key.replace(':', '_')}.wav"
    graph[-1] = graph[-1].rstrip(";")
    gpath = work / "graph.txt"
    gpath.write_text("\n".join(graph), encoding="utf-8")
    args = ["-v", "error", *inputs, "-/filter_complex", str(gpath)]
    for k, f in enumerate(files.values()):
        args += ["-map", f"[o{k}]", *pcm, str(f)]
    try:
        runner.ffmpeg(args)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return Stems(files=files, start=start, seconds=dur, folder=work)
