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
