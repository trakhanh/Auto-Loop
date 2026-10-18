"""Render thật vài kịch bản từ samples/ và kiểm tra kết quả bằng ffprobe.

python tests/render_check.py <thư_mục_xuất> [tên_kịch_bản ...]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import os  # noqa: E402

# dữ liệu test (cache, nhật ký) để riêng, không lẫn với app thật
os.environ.setdefault("KTLS_DATA_DIR", str(ROOT / ".test-data"))
os.environ.setdefault("KTLS_SETTINGS_ORG", "KTLoopStation-Test")

from loopstation.core import encoders, timeline  # noqa: E402
from loopstation.core.project import ClipItem, MusicTrack, Project  # noqa: E402
from loopstation.core.render import RenderJob  # noqa: E402

SAMPLES = ROOT / "samples"


def base_project(counts) -> Project:
    p = Project(name="Kiểm tra")
    clips = sorted((SAMPLES / "clips").glob("*.mp4"))
    for path, n in zip(clips, counts):
        p.video.clips.append(ClipItem(path=str(path), count=n))
    for path in sorted((SAMPLES / "music").iterdir()):
        p.music.tracks.append(MusicTrack(path=str(path)))
    return p


def scenario_manual():
    p = base_project([5, 1, 3, 1, 2, 3])
    return p


def scenario_target_cpu():
    p = base_project([3, 1, 2, 1, 1, 2])
    v = p.video
    v.length_mode, v.target_duration, v.fill = "target", 150.0, "repeat_sequence"
    v.order, v.reshuffle_each_round, v.exact_end = "shuffle", True, True
    v.source_audio, v.fit = "mix", "blur"
    v.clips[0].plays_mode, v.clips[0].min, v.clips[0].max = "random", 1, 4
    p.export.encoder = "cpu"
    p.music.order, p.music.gap, p.music.crossfade = "shuffle_no_repeat", 1.0, 0.0
    return p


def scenario_music_hevc():
    p = base_project([1, 1, 1, 1, 1, 1])
    v = p.video
    v.length_mode, v.fill, v.fit = "music", "stretch_marked", "crop"
    v.clips[0].stretch = v.clips[3].stretch = True
    p.export.preset = "youtube_1080p_hevc"
    p.music.tracks[1].enabled = False
    return p


def scenario_intel():
    p = scenario_manual()
    p.export.encoder = "intel"
    return p


def scenario_source_only():
    p = base_project([2, 2, 0, 2, 0, 1])
    p.video.source_audio = "only"
    return p


def scenario_xfade():
    p = base_project([4, 1, 3, 1, 1, 2])
    for c in p.video.clips:
        c.loop_xfade, c.next_xfade = 1.0, 1.5
    p.video.source_audio = "mix"
    return p


def scenario_full_gd2():
    from loopstation.core.project import AmbientLayer
    p = base_project([3, 1, 2, 1, 1, 2])
    v = p.video
    v.length_mode, v.target_duration, v.fill, v.exact_end = "target", 130.0, "repeat_sequence", True
    v.order, v.fit = "shuffle", "blur"
    for c in v.clips:
        c.loop_xfade, c.next_xfade = 0.5, 1.0
    v.intro, v.intro_xfade = str(SAMPLES / "extra" / "Intro.mp4"), 1.0
    v.outro, v.outro_xfade = str(SAMPLES / "extra" / "Outro.mp4"), 1.0
    p.music.ambient.append(AmbientLayer(path=str(SAMPLES / "extra" / "Mưa (tiếng nền).wav"), volume=40))
    return p


def scenario_xfade_intel():
    p = scenario_xfade()
    p.export.encoder = "intel"
    p.video.source_audio = "off"
    return p


def scenario_audio_only():
    from loopstation.core.project import AmbientLayer
    p = base_project([1])
    p.music.export_mode, p.music.export_target, p.music.export_format = "target", 300.0, "mp3_320"
    p.music.order = "shuffle_no_repeat"
    p.music.ambient.append(AmbientLayer(path=str(SAMPLES / "extra" / "Mưa (tiếng nền).wav"), volume=30))
    return p


def check_audio(name: str, out_dir: Path, available) -> bool:
    proj = SCENARIOS[name]()
    tl = timeline.build_audio(proj)
    assert tl.ok, tl.errors
    fmt = encoders.AUDIO_FORMATS[proj.music.export_format]
    out = out_dir / f"{name}{fmt.ext}"
    t0 = time.time()
    RenderJob(proj, available, str(out), on_log=lambda s: print("   ", s), audio_only=True).run()
    info = ffprobe_json(out)
    dur = float(info["format"]["duration"])
    ok = abs(dur - tl.total) < 0.1 and (out_dir / f"{name}_tracklist.txt").is_file()
    print(f"{'OK ' if ok else 'SAI'} {name}: {fmt.label} dur={dur:.3f}/{tl.total:.3f} "
          f"bài={len(tl.music_items)} render={time.time() - t0:.1f}s")
    return ok


def scenario_image_vertical():
    p = base_project([2, 1, 0, 0, 1, 0])
    p.video.clips.insert(1, ClipItem(path=str(SAMPLES / "extra" / "Ảnh 4x3.png"), count=2, loop_xfade=1.0,
                                     next_xfade=1.0))
    p.video.image_duration = 5.0
    p.video.fit = "blur"
    p.export.resolution, p.export.fps = "vertical", "30"
    return p


def scenario_720p_4k():
    p = base_project([1, 1, 1, 0, 0, 0])
    p.export.resolution = "4k"
    p.export.preset = "youtube_1080p_hevc"
    return p


def scenario_source_res():
    p = base_project([0, 0, 2, 0, 0, 0])  # chỉ clip 720p 30fps
    p.export.resolution, p.export.fps = "source", "source"
    return p


def scenario_trim():
    """V1 8s bỏ 2s đầu + 2s cuối → 4s × 3 lần; V2 bỏ 3s đầu → 5s; tiếng gốc bật để kiểm tra tiếng cũng cắt theo."""
    p = base_project([3, 1, 0, 0, 0, 0])
    p.video.clips[0].trim_start, p.video.clips[0].trim_end = 2.0, 2.0
    p.video.clips[1].trim_start = 3.0
    p.video.source_audio = "mix"
    return p


def scenario_trim_xfade():
    p = scenario_trim()
    for c in p.video.clips:
        c.loop_xfade, c.next_xfade = 1.0, 1.0
    return p


SCENARIOS = {f.__name__.removeprefix("scenario_"): f for f in
             [scenario_manual, scenario_target_cpu, scenario_music_hevc, scenario_intel,
              scenario_source_only, scenario_xfade, scenario_full_gd2, scenario_xfade_intel, scenario_audio_only, scenario_image_vertical, scenario_720p_4k,
              scenario_source_res, scenario_trim, scenario_trim_xfade]}


def ffprobe_json(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-print_format", "json",
                        "-show_format", "-show_streams", str(path)], capture_output=True, text=True)
    return json.loads(r.stdout)


def check(name: str, out_dir: Path, available) -> bool:
    proj = SCENARIOS[name]()
    tl = timeline.build(proj)
    assert tl.ok, tl.errors
    out = out_dir / f"{name}.mp4"
    job = RenderJob(proj, available, str(out), on_log=lambda s: print("   ", s))
    t0 = time.time()
    job.run()
    took = time.time() - t0
    info = ffprobe_json(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    frames = int(v["nb_read_packets"])
    dur = float(info["format"]["duration"])
    ok = frames == tl.video.total_frames and abs(dur - tl.total) < 0.1
    if a is not None:
        ok &= abs(float(a["duration"]) - tl.total) < 0.1
    dec = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "null", "-"],
                         capture_output=True, text=True)
    ok &= not dec.stderr.strip()
    ok &= (v["width"], v["height"]) == (tl.width, tl.height)
    print(f"{'OK ' if ok else 'SAI'} {name}: {v['codec_name']} {v['width']}x{v['height']} {v['r_frame_rate']} "
          f"frames={frames}/{tl.video.total_frames} dur={dur:.3f}/{tl.total:.3f} "
          f"audio={'có' if a else 'không'} render={took:.1f}s")
    if dec.stderr.strip():
        print("   Lỗi giải mã:", dec.stderr.strip()[:500])
    return ok


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    names = sys.argv[2:] or list(SCENARIOS)
    available = encoders.detect()
    print("Encoder khả dụng:", available)
    results = [(check_audio if n.startswith('audio') else check)(n, out_dir, available) for n in names]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
