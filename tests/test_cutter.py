"""Lõi trang Cắt video (loopstation/core/cutter.py): đọc thời gian, tính đoạn, kích thước, tham số FFmpeg, đặt tên.
Hàm thuần — không cần Qt, không chạy FFmpeg (chạy thật ở tests/test_cutter_ffmpeg.py)."""
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loopstation.core import cutter as c  # noqa: E402


def test_parse_time_formats():
    assert c.parse_time("00:01:15") == 75
    assert c.parse_time("1:15") == 75
    assert c.parse_time("75") == 75
    assert c.parse_time(" 00:01:15.5 ") == 75.5
    assert c.parse_time("1:00:00") == 3600
    assert c.parse_time("0:01:15,5") == 75.5  # dấu phẩy thập phân kiểu Việt


@pytest.mark.parametrize("bad", ["", "abc", "00:75:00", "1:2:3:4", "-5", "1:60", "00:01:60"])
def test_parse_time_bad(bad):
    with pytest.raises(ValueError):
        c.parse_time(bad)


def test_parse_marks_and_ranges():
    assert c.parse_marks("00:01:15, 00:05:30\n12:00;") == [75, 330, 720]
    assert c.parse_marks("  ") == []
    assert c.parse_ranges("00:01:10-00:01:45, 5:00 – 5:30") == [(70, 105), (300, 330)]
    assert c.parse_ranges("1:00—1:30\n2:00 - 2:10") == [(60, 90), (120, 130)]
    with pytest.raises(ValueError, match="00:02:00-00:01:00"):
        c.parse_ranges("00:02:00-00:01:00")
    with pytest.raises(ValueError, match="00:75:00"):
        c.parse_marks("00:01:00, 00:75:00")
    with pytest.raises(ValueError, match="00:01:00"):
        c.parse_ranges("00:01:00")  # thiếu điểm cuối


def test_fmt_time():
    assert c.fmt_time(75.9) == "00:01:15"
    assert c.fmt_time(3725) == "01:02:05"


def segs(d, **kw):
    out, note = c.plan_segments(d, c.SplitSettings(**kw), random.Random(1))
    return [(round(x.start, 3), round(x.dur, 3)) for x in out], note


def test_parts():
    assert segs(90, mode="parts", parts=3)[0] == [(0, 30), (30, 30), (60, 30)]
    s, note = segs(2.5, mode="parts", parts=10)  # mỗi phần < 1 s → hạ N
    assert len(s) == 2 and note


def test_fixed_tail():
    s, note = segs(95, mode="fixed", fixed=30)
    assert s[-1] == (90, 5) and len(s) == 4 and not note  # đoạn cuối dư giữ lại
    assert len(segs(90.5, mode="fixed", fixed=30)[0]) == 3  # dư < 1 s → bỏ
    with pytest.raises(ValueError):
        segs(90, mode="fixed", fixed=0)


def test_random_bounds_and_cover():
    for seed in range(20):
        out, _ = c.plan_segments(600, c.SplitSettings(mode="random", rmin=10, rmax=45), random.Random(seed))
        assert out[0].start == 0 and abs(sum(x.dur for x in out) - 600) < 1e-6
        assert all(10 - 1e-6 <= x.dur <= 45 + 1e-6 for x in out)
    with pytest.raises(ValueError):
        segs(600, mode="random", rmin=50, rmax=10)


def test_random_differs_between_runs():
    a, _ = c.plan_segments(600, c.SplitSettings(mode="random"), random.Random(1))
    b, _ = c.plan_segments(600, c.SplitSettings(mode="random"), random.Random(2))
    assert [x.dur for x in a] != [x.dur for x in b]


def test_random_short_video_one_piece():
    assert segs(8, mode="random", rmin=10, rmax=45)[0] == [(0, 8)]


def test_marks():
    s, note = segs(600, mode="marks", marks="00:05:30, 00:01:15, 00:01:15, 00:20:00")
    assert s == [(0, 75), (75, 255), (330, 270)] and "00:20:00" in note


def test_ranges():
    s, note = segs(100, mode="ranges", ranges="00:00:10-00:00:20, 00:01:30-00:02:00, 00:03:00-00:03:10")
    assert s == [(10, 10), (90, 10)] and "00:03:00" in note  # vượt cuối → cắt tới hết; ngoài video → bỏ


def test_empty_marks_or_ranges_is_error():
    with pytest.raises(ValueError):
        segs(100, mode="marks", marks="")
    with pytest.raises(ValueError):
        segs(100, mode="ranges", ranges=" ")


def test_all_marks_outside_is_error():
    with pytest.raises(ValueError):
        segs(100, mode="ranges", ranges="00:03:00-00:03:10")


# ---------- kích thước, filter, tham số FFmpeg, đặt tên ----------
from fractions import Fraction  # noqa: E402

from loopstation.core.probe import MediaInfo  # noqa: E402

INFO = MediaInfo(path="a.mp4", duration=100, has_video=True, width=1920, height=1080, fps=Fraction(30),
                 has_audio=True)


def test_out_size():
    assert c.out_size(1920, 1080, "9:16") == (1080, 1920)
    assert c.out_size(1080, 1920, "16:9") == (1920, 1080)
    assert c.out_size(1920, 1080, "1:1") == (1080, 1080)
    assert c.out_size(1920, 1080, "4:5") == (864, 1080)
    assert c.out_size(1281, 721, "9:16") == (720, 1280)  # số chẵn
    assert c.out_size(1080, 1920, "9:16") == (1080, 1920)  # video dọc (đã xoay) giữ nguyên
    assert c.out_size(1920, 1080, "keep") == (1920, 1080)


def test_aspect_filter_kinds():
    assert c.aspect_filter(1920, 1080, "keep", "blur") == ""
    blur = c.aspect_filter(1920, 1080, "9:16", "blur")
    assert "gblur" in blur and "overlay" in blur and "split" in blur
    assert "pad=1080:1920" in c.aspect_filter(1920, 1080, "9:16", "black")
    assert "crop=1080:1920" in c.aspect_filter(1920, 1080, "9:16", "crop")


def test_split_args_exact():
    a = c.split_args("a.mp4", c.Segment(10, 5), Path("o.mp4"), INFO, c.SplitSettings(aspect="9:16"), "h264_nvenc")
    assert a[a.index("-ss") + 1] == "10.000" and a.index("-ss") < a.index("-i")
    assert a[a.index("-t") + 1] == "5.000"
    assert "h264_nvenc" in a and "0:a?" in a and "aac" in a
    assert "gblur" in a[a.index("-vf") + 1]
    assert a[-1] == "o.mp4"
    assert "-vf" not in c.split_args("a.mp4", c.Segment(0, 5), Path("o.mp4"), INFO, c.SplitSettings(), "libx264")


def test_split_args_fast_ignores_aspect():
    f = c.split_args("a.mp4", c.Segment(10, 5), Path("o.mkv"), INFO,
                     c.SplitSettings(exact=False, aspect="9:16"), "h264_nvenc")
    assert f[f.index("-c") + 1] == "copy" and "-vf" not in f and "h264_nvenc" not in f


def vf(args):
    return args[args.index("-vf") + 1]


def test_frame_args_modes():
    p = Path("x_%04d.jpg")
    a = c.frame_args("a.mp4", INFO, c.FrameSettings(mode="count", count=4), p)
    # ảnh thứ k ở khung đầu tiên từ (k + 0,5) × 100/4 giây: 12,5 s, 37,5 s… (chọn theo mốc tuyệt đối, không trôi)
    assert vf(a) == (r"select=gte(t\,12.5)*(isnan(prev_selected_t)"
                     r"+gt(floor((t-12.5)/25)\,floor((prev_selected_t-12.5)/25)))")
    assert a[a.index("-frames:v") + 1] == "4" and "vfr" in a and "-ss" not in a
    assert vf(c.frame_args("a.mp4", INFO, c.FrameSettings(mode="every_sec", every_sec=5), p)) == "fps=1/5"
    assert vf(c.frame_args("a.mp4", INFO, c.FrameSettings(mode="every_sec", every_sec=0.5), p)) == "fps=1/0.5"
    every_n = c.frame_args("a.mp4", INFO, c.FrameSettings(mode="every_n"), p)
    assert vf(every_n) == r"select=not(mod(n\,150))" and "vfr" in every_n
    scene = c.frame_args("a.mp4", INFO, c.FrameSettings(mode="scene", scene=10), p)
    assert vf(scene) == r"select=eq(n\,0)+gt(scene\,0.1)" and "vfr" in scene
    jpg = c.frame_args("a.mp4", INFO, c.FrameSettings(), p)
    assert jpg[jpg.index("-q:v") + 1] == "2" and jpg[-1] == str(p)
    assert "-q:v" not in c.frame_args("a.mp4", INFO, c.FrameSettings(fmt="png"), Path("x_%04d.png"))


def test_scene_threshold():
    assert c.scene_threshold(10) == 0.1
    assert c.scene_threshold(0) == 0.01
    assert c.scene_threshold(150) == 1.0


def test_frame_estimate():
    assert c.frame_estimate(INFO, c.FrameSettings(mode="count", count=100)) == 100
    assert c.frame_estimate(INFO, c.FrameSettings(mode="every_sec", every_sec=5)) == 20
    assert c.frame_estimate(INFO, c.FrameSettings(mode="every_n", every_n=150)) == 20  # 100 s × 30 fps / 150
    assert c.frame_estimate(INFO, c.FrameSettings(mode="scene")) is None


def test_names(tmp_path):
    assert c.out_dir(tmp_path, "D:/v/Cảnh mưa.mp4", True) == tmp_path / "Cảnh mưa"
    (tmp_path / "Cảnh mưa").mkdir()
    assert c.out_dir(tmp_path, "D:/v/Cảnh mưa.mp4", True) == tmp_path / "Cảnh mưa"  # thư mục rỗng: dùng luôn
    (tmp_path / "Cảnh mưa" / "x.mp4").write_bytes(b"1")
    assert c.out_dir(tmp_path, "D:/v/Cảnh mưa.mp4", True) == tmp_path / "Cảnh mưa (2)"
    assert c.out_dir(tmp_path, "a.mp4", False) == tmp_path
    (tmp_path / "a_01.mp4").write_bytes(b"1")
    assert c.unique_stem(tmp_path, "a", "mp4") == "a (2)"
    assert c.unique_stem(tmp_path, "a", "jpg") == "a"
    assert c.unique_stem(tmp_path, "b", "mp4") == "b"
    assert c.digits(9, 2) == 2 and c.digits(120, 2) == 3 and c.digits(50, 4) == 4


# ---------- sửa sau đọc soát ----------
@pytest.mark.parametrize("a,b,d", [(10, 15, 600), (20, 30, 754), (60, 90, 3600), (10, 45, 600), (5, 6, 61)])
def test_random_tight_bounds_stay_inside(a, b, d):
    for seed in range(200):
        out, _ = c.plan_segments(d, c.SplitSettings(mode="random", rmin=a, rmax=b), random.Random(seed))
        assert abs(sum(x.dur for x in out) - d) < 1e-6 and out[0].start == 0
        assert all(a - 1e-6 <= x.dur <= b + 1e-6 for x in out), (seed, [round(x.dur, 2) for x in out])


def test_random_impossible_range_falls_back():
    out, _ = c.plan_segments(25, c.SplitSettings(mode="random", rmin=20, rmax=22), random.Random(1))
    assert abs(sum(x.dur for x in out) - 25) < 1e-6


def test_split_args_start_zero_has_no_seek():
    a = c.split_args("a.flv", c.Segment(0, 5), Path("o.mp4"), INFO, c.SplitSettings(), "libx264")
    assert "-ss" not in a
    f = c.split_args("a.flv", c.Segment(0, 5), Path("o.flv"), INFO, c.SplitSettings(exact=False), "libx264")
    assert "-ss" not in f


def test_split_args_odd_size_keep_makes_even():
    odd = MediaInfo(path="a.mp4", duration=10, has_video=True, width=641, height=361, fps=Fraction(30))
    a = c.split_args("a.mp4", c.Segment(1, 5), Path("o.mp4"), odd, c.SplitSettings(), "libx264")
    assert vf(a) == "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def test_last_line_skips_generic_ffmpeg_tail():
    err = Exception("ffmpeg lỗi (mã 1):\n[libx264 @ 0x1] width not divisible by 2 (641x361)\n"
                    "Error while opening encoder - maybe incorrect parameters\nConversion failed!")
    assert "Error while opening encoder" in c._last_line(err) or "641x361" in c._last_line(err)
    assert c._last_line(err) != "Conversion failed!"
