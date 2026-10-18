from fractions import Fraction
from pathlib import Path

from loopstation.core import encoders, markers, planner, render
from loopstation.core.project import ClipItem, VideoSettings


class _TL:
    def __init__(self, plan, frames, fps):
        self.video, self.frames, self.fps = plan, frames, fps


def test_markers_loop_and_normal():
    vs = VideoSettings(clips=[ClipItem("loop.mp4", count=3, loop_xfade=1.0, next_xfade=1.0), ClipItem("2_a.mp4"),
                              ClipItem("loop.mp4", count=2)])
    fps = Fraction(24)
    frames = {0: 240, 1: 120, 2: 240}
    plan = planner.plan_video(vs, frames, fps, None)
    marks = markers.build(_TL(plan, frames, fps), ["loop.mp4", "2_a.mp4", "loop.mp4"])
    assert [m.kind for m in marks] == ["LOOP", "THƯỜNG", "LOOP"]
    assert [m.plays for m in marks] == [3, 1, 2]
    # 3 lần × 240 frame, 2 lần nối 24 frame → 672; cảnh thường bắt đầu sớm 24 frame (crossfade)
    assert marks[0].end == 672 and marks[1].start == 648 and marks[0].xfade_next == 24
    assert marks[1].end == 648 + 120 == marks[2].start
    assert markers.clock(648, fps) == "00:00:27.000"
    assert markers.timecode(648, fps, 1) == "01:00:27:00"
    srt = markers.to_srt(marks, fps)
    assert "00:00:27,000 --> 00:00:32,000" in srt and "THƯỜNG" in srt


def test_maxrate_modes():
    assert encoders.maxrate_kbps("off", 0, 1920, 1080, 30, 600) == 0
    assert encoders.maxrate_kbps("youtube", 0, 1920, 1080, 30, 600) == 8000
    assert encoders.maxrate_kbps("youtube", 0, 2560, 1440, 30, 600) == 16000
    assert encoders.maxrate_kbps("mbps", 5, 1920, 1080, 30, 600) == 5000
    # 1 GB trong 1 giờ ≈ 2.3 Mbps tổng → trừ 192k tiếng
    k = encoders.maxrate_kbps("size", 1.0, 1920, 1080, 30, 3600)
    assert 2000 < k < 2300
    args = encoders.encoder_args("h264_nvenc", "saving", 60, 4000)
    assert "-maxrate" in args and args[args.index("-cq") + 1] == "26"


def test_output_path_own_folder(tmp_path):
    p = render.output_path(str(tmp_path), "Video A.mp4", True)
    assert Path(p) == tmp_path / "Video A" / "Video A.mp4"
    (tmp_path / "Video A").mkdir()
    Path(p).write_bytes(b"x")
    q = render.output_path(str(tmp_path), "Video A.mp4", True, set())
    assert Path(q) == tmp_path / "Video A_2" / "Video A_2.mp4"
    assert Path(render.output_path(str(tmp_path), "B.mp4", False)) == tmp_path / "B.mp4"


def test_output_dir_relative_inside_project(tmp_path):
    from loopstation.core.project import Project
    p = Project()
    p.export.output_dir = str(tmp_path / "Xuat")
    f = tmp_path / "a.lsproj"
    p.save(str(f))
    assert '"output_dir": "Xuat"' in f.read_text(encoding="utf-8")
    moved = tmp_path / "moved"
    moved.mkdir()
    (moved / "a.lsproj").write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    assert Path(Project.load(str(moved / "a.lsproj")).export.output_dir) == moved / "Xuat"
    p.export.output_dir = str(tmp_path.parent / "Khac")  # ngoài thư mục dự án → giữ tuyệt đối
    p.save(str(f))
    assert Path(Project.load(str(f)).export.output_dir) == tmp_path.parent / "Khac"


def test_clean_previews(tmp_path, monkeypatch):
    from loopstation.core import ffmpeg_tools as ft
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path))
    d = ft.preview_dir()
    old, new = d / "seam_080000.mp4", d / "seam_090000.mp4"
    old.write_bytes(b"x" * 10)
    new.write_bytes(b"y" * 5)
    assert ft.clean_previews(keep=str(new)) == 10
    assert not old.exists() and new.exists()
    ft.clear_cache()
    assert not new.exists()
