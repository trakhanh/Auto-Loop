"""Kiểm thử các lỗi tìm thấy khi audit bản 1.4.2 (sửa ở 1.4.3)."""
import os
import time
from fractions import Fraction
from pathlib import Path

from loopstation.core import batch, encoders, markers, planner, render
from loopstation.core import interleave as il
from loopstation.core.project import ClipItem, MusicSettings, MusicTrack, Project


def touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")


# ---------- mốc thời gian ----------
def test_timecode_ntsc_counts_frames():
    fps = Fraction(30000, 1001)
    assert markers.timecode(107892, fps) == "00:59:56:12"  # 1 giờ thật ở 29.97 = 107892 khung
    assert markers.timecode(915, fps) == "00:00:30:15"
    assert markers.timecode(0, fps, 1) == "01:00:00:00"
    assert markers.timecode(25 * 61, Fraction(25)) == "00:01:01:00"


def test_csv_uses_integer_ms():
    m = [markers.Mark(0, 840, 0, "a.mp4", 1), markers.Mark(840, 900, 1, "b.mp4", 1)]
    text = markers.to_csv(m, Fraction(30000, 1001))
    row = text.splitlines()[1].split(",")
    assert "28028" in row and "." not in "".join(row[7:])  # không còn số thập phân kiểu 28.028
    edl = markers.to_edl(m, Fraction(30000, 1001), "t")
    assert "|D:840" in edl


# ---------- tên file ----------
def test_filename_with_dots_and_bad_chars(tmp_path):
    a = render.version_outputs(str(tmp_path), "Lofi Vol.1", ".mp3", True, 2)
    b = render.version_outputs(str(tmp_path), "Lofi Vol.2", ".mp3", True, 2)
    assert set(a).isdisjoint(b) and Path(a[0]).name == "Lofi Vol.1_ban-1.mp3"
    assert render.strip_ext("Chill Mix Vol.3", ".mp4") == "Chill Mix Vol.3"
    assert render.strip_ext("abc.mp4", ".mp4") == "abc"
    assert render.clean_filename('Mưa: đêm? "hay" <1>|2*. ') == "Mưa_ đêm_ _hay_ _1__2_"


def test_finalize_keeps_file_when_target_locked(tmp_path, monkeypatch):
    part = tmp_path / "v.dang-xuat.mp4"
    part.write_bytes(b"video")
    out = tmp_path / "v.mp4"
    real = os.replace

    def locked(a, b):
        if Path(b) == out:
            raise PermissionError(5, "Access is denied")
        return real(a, b)

    monkeypatch.setattr(render.os, "replace", locked)
    monkeypatch.setattr(render.time, "sleep", lambda s: None)
    logs = []
    got = render._finalize(part, out, logs.append)
    assert got.name == "v_moi.mp4" and got.read_bytes() == b"video" and logs


def test_encoder_failure_classification():
    from loopstation.core.ffmpeg_tools import FFmpegError
    assert render._is_encoder_failure(FFmpegError("x", "[h264_nvenc @ 0x] OpenEncodeSessionEx failed: out of memory"))
    assert not render._is_encoder_failure(FFmpegError("x", "Invalid data found when processing input"))
    assert not render._is_encoder_failure(FFmpegError("x", "[hevc_nvenc] No space left on device"))


# ---------- trần bitrate ----------
def test_bitrate_cap_accounts_for_block_bursts():
    one = encoders.maxrate_kbps("mbps", 8, 1920, 1080, 30, 3600, 192, 0)
    many = encoders.maxrate_kbps("mbps", 8, 1920, 1080, 30, 3600, 192, 900)  # khối 4 giây
    assert one == 8000 and many < one
    assert encoders.maxrate_kbps("youtube", 0, 1920, 1080, 30, 3600, 192, 900) == 8000  # YouTube: không đổi
    assert encoders.cap_blocks("h264_nvenc", 900) == 0 and encoders.cap_blocks("libx264", 900) == 900
    strict = encoders.encoder_args("h264_nvenc", "high", 60, 8000, strict=True)
    assert "-cq" not in strict and strict[strict.index("-b:v") + 1] == "6400k"
    soft = encoders.encoder_args("h264_nvenc", "high", 60, 8000)
    assert "-cq" in soft and "-maxrate" in soft


# ---------- nhạc ----------
def _ms(plays, order="shuffle_no_repeat", pin=0, pin_pos="first"):
    ms = MusicSettings()
    ms.tracks = [MusicTrack(f"{i}.mp3", plays=p, pinned=(i == pin)) for i, p in enumerate(plays)]
    ms.order, ms.pin_pos, ms.crossfade = order, pin_pos, 0
    return ms


def test_pins_keep_no_repeat():
    bad = 0
    for seed in range(300):
        for pos in ("first", "random"):
            ms = _ms([2, 3, 1, 1], pin=0, pin_pos=pos)
            ms.seed = seed
            d = {i: 60.0 for i in range(4)}
            seq = [it.track for it in planner.plan_music(ms, d, 7 * 60)]
            assert 0 in seq
            bad += any(a == b for a, b in zip(seq, seq[1:]))
    assert bad == 0


def test_version_seeds_fast_when_few_tracks():
    ms = _ms([1])
    t = time.time()
    seeds, dup = planner.version_seeds(ms, {0: 30.0}, 36000, 50)
    assert time.time() - t < 1.0 and len(seeds) == 50 and dup
    ms2 = _ms([1, 1])
    t = time.time()
    planner.version_seeds(ms2, {0: 180.0, 1: 180.0}, 36000, 50)
    assert time.time() - t < 3.0
    t = time.time()
    planner.version_seeds(ms2, {0: 180.0, 1: 180.0}, 36000, 50)  # lần 2: nhớ kết quả
    assert time.time() - t < 0.05


# ---------- xen kẽ ----------
def test_detect_base_names():
    for n in ("nen1.mp4", "bg01.mp4", "background2.mp4", "1loop.mp4", "LOOP_mua.mov"):
        assert il.looks_like_base(n), n
    import unicodedata
    assert il.looks_like_base(unicodedata.normalize("NFD", "nền mưa.mp4"))
    clips = [ClipItem("bg_logo.png"), ClipItem("loop_rain.mp4"), ClipItem("2_a.mp4")]
    assert il.detect_base(clips) == 1
    clips = [ClipItem("background.jpg"), ClipItem("nen_mua.mp4")]
    assert il.detect_base(clips) == 1


def test_zero_plays_scene_is_skipped():
    clips = [ClipItem("loop.mp4"), ClipItem("2_a.mp4"), ClipItem("3_b.mp4")]
    specs = [il.InsertSpec("2_a.mp4", 1, 0), il.InsertSpec("3_b.mp4", 1, 1)]
    out = il.build(clips, il.InterleaveOptions(0, inserts=specs))
    on = [Path(c.path).name for c in out if c.enabled]
    assert on == ["loop.mp4", "3_b.mp4", "loop.mp4"]


def test_unique_inserts_can_include_disabled():
    clips = [ClipItem("loop.mp4"), ClipItem("2_a.mp4"), ClipItem("3_b.mp4", enabled=False)]
    assert [c.path for c in il.unique_inserts(clips, 0, "table")] == ["2_a.mp4"]
    got = il.unique_inserts(clips, 0, "table", include_off=True)
    assert [(c.path, c.enabled) for c in got] == [("2_a.mp4", True), ("3_b.mp4", False)]


# ---------- hàng loạt ----------
def test_batch_arranged_order_not_reshuffled(tmp_path):
    for n in ("loop_a.mp4", "2_b.mp4", "3_c.mp4"):
        touch(tmp_path / "V" / n)
    job = batch.scan(str(tmp_path))[0]
    tpl = Project()
    tpl.video.order = "shuffle"

    def arrange(clips, b):
        return il.build(clips, il.InterleaveOptions(base_index=b))

    assert batch.build_project(tpl, job, "auto", arrange).video.order == "list"
    manual = [ClipItem(str(tmp_path / "V" / "2_b.mp4"), count=9), ClipItem(str(tmp_path / "V" / "3_c.mp4"))]
    p = batch.build_project(tpl, job, "auto", None, loop_xfade=1.5, clips_override=manual,
                            base_override=str(tmp_path / "V" / "2_b.mp4"))
    assert p.video.order == "list" and p.video.clips[0].loop_xfade == 1.5 and p.video.clips[1].loop_xfade == 0.0


def test_batch_scan_skips_drive_root_and_system_dirs(tmp_path):
    assert batch.scan(os.path.abspath(os.sep)) == []
    touch(tmp_path / "$RECYCLE.BIN" / "a.mp4")
    touch(tmp_path / "Video 1" / "a.mp4")
    assert [j.name for j in batch.scan(str(tmp_path))] == ["Video 1"]


# ---------- dự án ----------
def test_project_moved_keeps_media_links(tmp_path):
    media = tmp_path / "Media" / "loop.mp4"
    touch(media)
    proj = Project()
    proj.video.clips = [ClipItem(str(media))]
    p1 = tmp_path / "Projects" / "Kenh1" / "a.lsproj"
    p1.parent.mkdir(parents=True)
    proj.save(str(p1))
    p2 = tmp_path / "Projects" / "Kenh1" / "2026" / "a.lsproj"  # chỉ chuyển file dự án vào thư mục con
    p2.parent.mkdir()
    p1.replace(p2)
    assert Path(Project.load(str(p2)).video.clips[0].path) == media
    assert not list(p2.parent.glob("*.tmp"))  # lưu an toàn không để lại file tạm


def test_video_only_ignores_music_length(tmp_path):
    from loopstation.core import timeline
    proj = Project(output_kind="video_only")
    proj.video.length_mode = "music"
    proj.video.clips = [ClipItem(str(tmp_path / "khong-co.mp4"))]
    tl = timeline.build(proj)
    assert not any("Theo độ dài nhạc" in e for e in tl.errors)
