"""Cắt video chạy thật bằng FFmpeg: chia đoạn đúng độ dài / kích thước, xuất ảnh, không ghi đè, Dừng không để file dở.
Video mẫu tạo bằng FFmpeg (testsrc + sine) trong thư mục tạm; dữ liệu app vào thư mục tạm."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def media():
    mp = pytest.MonkeyPatch()
    scratch = Path(tempfile.mkdtemp(prefix="ktls_cutter_"))
    mp.setenv("KTLS_DATA_DIR", str(scratch / "data"))
    mp.setenv("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
    mp.setenv("KTLS_NO_UPDATE", "1")
    from loopstation.core import ffmpeg_tools
    src = scratch / "src"
    src.mkdir()
    sample = src / "Cảnh 'mưa' 100%.mp4"
    silent = src / "silent.mp4"
    ff = ffmpeg_tools.ffmpeg()
    r = ffmpeg_tools.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=6",
                          "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:v", "libx264", "-g", "25",
                          "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(sample)])
    assert r.returncode == 0, r.stderr
    r = ffmpeg_tools.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=4",
                          "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)])
    assert r.returncode == 0, r.stderr
    yield sample, silent
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def run_split(src, out, runner=None, **kw):
    from loopstation.core import cutter, ffmpeg_tools, probe
    info = probe.probe(str(src))
    s = cutter.SplitSettings(**kw)
    segs, _ = cutter.plan_segments(info.duration, s)
    return cutter.split_video(runner or ffmpeg_tools.Runner(), str(src), info, s, out, "libx264", segs)


def dur(p):
    from loopstation.core import probe
    return probe.probe(str(p)).duration


def test_split_three_parts_exact(media, tmp_path):
    sample, _ = media
    r = run_split(sample, tmp_path, mode="parts", parts=3)
    assert r.folder == tmp_path / sample.stem and not r.errors
    assert [p.name for p in r.files] == [f"{sample.stem}_{i:02d}.mp4" for i in (1, 2, 3)]
    assert all(abs(dur(p) - 2.0) < 0.15 for p in r.files)


def test_split_9x16_blur_size(media, tmp_path):
    from loopstation.core import probe
    sample, _ = media
    r = run_split(sample, tmp_path, mode="parts", parts=2, aspect="9:16", fit="blur")
    info = probe.probe(str(r.files[0]))
    assert (info.width, info.height) == (180, 320) and info.has_audio


def test_split_fast_copy_and_silent(media, tmp_path):
    _, silent = media
    r = run_split(silent, tmp_path, mode="fixed", fixed=2, exact=False, per_video=False)
    assert len(r.files) == 2 and not r.errors and r.files[0].suffix == ".mp4" and r.folder == tmp_path
    assert all(dur(p) > 0.5 for p in r.files)


def test_split_exact_silent(media, tmp_path):
    _, silent = media
    r = run_split(silent, tmp_path, mode="parts", parts=2)
    assert len(r.files) == 2 and not r.errors


def test_second_run_no_overwrite(media, tmp_path):
    sample, _ = media
    a = run_split(sample, tmp_path, mode="parts", parts=2)
    b = run_split(sample, tmp_path, mode="parts", parts=2)
    assert a.folder != b.folder and b.folder.name == f"{sample.stem} (2)"
    c = run_split(sample, tmp_path, mode="parts", parts=2, per_video=False)
    d = run_split(sample, tmp_path, mode="parts", parts=2, per_video=False)
    assert c.files[0].name == f"{sample.stem}_01.mp4" and d.files[0].name == f"{sample.stem} (2)_01.mp4"


def test_progress_reported(media, tmp_path):
    sample, _ = media
    seen = []
    from loopstation.core import cutter, ffmpeg_tools, probe
    info = probe.probe(str(sample))
    s = cutter.SplitSettings(mode="parts", parts=2)
    segs, _ = cutter.plan_segments(info.duration, s)
    cutter.split_video(ffmpeg_tools.Runner(), str(sample), info, s, tmp_path, "libx264", segs,
                       on_progress=lambda f, t: seen.append((f, t)))
    assert seen and seen[-1][0] == pytest.approx(1.0) and all(0 <= f <= 1 for f, _ in seen)
    assert any("2/2" in t for _, t in seen)


def frames(src, out, **kw):
    from loopstation.core import cutter, ffmpeg_tools, probe
    return cutter.extract_frames(ffmpeg_tools.Runner(), str(src), probe.probe(str(src)), cutter.FrameSettings(**kw),
                                 out)


def test_frames_count(media, tmp_path):
    sample, _ = media
    r = frames(sample, tmp_path, mode="count", count=5)
    assert len(r.files) == 5 and r.files[0].name == f"{sample.stem}_0001.jpg"
    assert r.folder == tmp_path / sample.stem


def test_frames_every_sec_and_n(media, tmp_path):
    sample, _ = media
    assert len(frames(sample, tmp_path / "a", mode="every_sec", every_sec=2).files) in (3, 4)
    assert len(frames(sample, tmp_path / "b", mode="every_n", every_n=50).files) == 3  # 150 khung / 50


def test_frames_scene_png(media, tmp_path):
    sample, _ = media
    r = frames(sample, tmp_path, mode="scene", scene=10, fmt="png")
    assert r.files and r.files[0].suffix == ".png"


def test_frames_no_overwrite(media, tmp_path):
    sample, _ = media
    a = frames(sample, tmp_path, mode="count", count=2, per_video=False)
    b = frames(sample, tmp_path, mode="count", count=2, per_video=False)
    assert len(set(a.files) | set(b.files)) == 4


def test_cancel_leaves_no_partial(media, tmp_path):
    from loopstation.core import ffmpeg_tools, probe
    sample, _ = media
    runner = ffmpeg_tools.Runner()
    with pytest.raises(ffmpeg_tools.CancelledError) as ei:
        _cancel_mid(sample, tmp_path, runner)
    files = sorted((tmp_path / sample.stem).iterdir())
    assert files and all(probe.probe(str(p)).ok and probe.probe(str(p)).duration > 1 for p in files)
    assert sorted(getattr(ei.value, "files", [])) == files  # app biết file nào do lượt này tạo


def _cancel_mid(sample, out, runner):
    from loopstation.core import cutter, probe
    info = probe.probe(str(sample))
    s = cutter.SplitSettings(mode="parts", parts=3)
    segs, _ = cutter.plan_segments(info.duration, s)

    def prog(frac, text):
        if "2/3" in text:
            runner.cancel()
    return cutter.split_video(runner, str(sample), info, s, out, "libx264", segs, on_progress=prog)


def test_reuse_folder_after_stop(media, tmp_path):
    from loopstation.core import cutter, ffmpeg_tools, probe
    sample, _ = media
    info = probe.probe(str(sample))
    s = cutter.SplitSettings(mode="parts", parts=2)
    segs, _ = cutter.plan_segments(info.duration, s)
    first = cutter.split_video(ffmpeg_tools.Runner(), str(sample), info, s, tmp_path, "libx264", segs)
    for f in first.files:  # trang Cắt video dọn file của lượt bị Dừng trước khi chạy lại
        f.unlink()
    again = cutter.split_video(ffmpeg_tools.Runner(), str(sample), info, s, tmp_path, "libx264", segs,
                               reuse=(first.folder, sample.stem))
    assert again.folder == first.folder and [p.name for p in again.files] == [p.name for p in first.files]


def test_odd_size_keep_exact(tmp_path):
    from loopstation.core import ffmpeg_tools
    src = tmp_path / "odd.mp4"
    r = ffmpeg_tools.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
                          "testsrc=size=321x181:rate=25:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv444p", str(src)])
    assert r.returncode == 0, r.stderr
    res = run_split(src, tmp_path / "out", mode="parts", parts=2)
    assert len(res.files) == 2 and not res.errors


def test_reuse_never_overwrites_other_results(media, tmp_path):
    """Lượt dừng dùng lại tên gốc, nhưng thư mục đã có kết quả của lượt khác cùng kiểu → ra tên mới, không ghi đè."""
    import os
    from loopstation.core import cutter, ffmpeg_tools, probe
    sample, _ = media
    info = probe.probe(str(sample))
    s = cutter.SplitSettings(mode="parts", parts=2, per_video=False)
    segs, _ = cutter.plan_segments(info.duration, s)
    first = cutter.split_video(ffmpeg_tools.Runner(), str(sample), info, s, tmp_path, "libx264", segs)
    stamps = {p: os.path.getmtime(p) for p in first.files}
    again = cutter.split_video(ffmpeg_tools.Runner(), str(sample), info, s, tmp_path, "libx264", segs,
                               reuse=(tmp_path, sample.stem))
    assert not set(again.files) & set(first.files)
    assert all(os.path.getmtime(p) == t for p, t in stamps.items())


def test_frames_cancel_lists_only_new_files(media, tmp_path):
    from loopstation.core import cutter, ffmpeg_tools, probe
    sample, _ = media
    info = probe.probe(str(sample))
    s = cutter.FrameSettings(mode="count", count=3, fmt="png", per_video=False)
    first = cutter.extract_frames(ffmpeg_tools.Runner(), str(sample), info, s, tmp_path)
    runner = ffmpeg_tools.Runner()
    with pytest.raises(ffmpeg_tools.CancelledError) as ei:
        cutter.extract_frames(runner, str(sample), info, s, tmp_path, on_progress=lambda f, t: runner.cancel(),
                              reuse=(tmp_path, sample.stem))
    assert not set(ei.value.files) & set(first.files)
    assert all(p.exists() for p in first.files)


def test_parallel_split_same_result(media, tmp_path):
    from loopstation.core import cutter, ffmpeg_tools, probe
    sample, _ = media
    info = probe.probe(str(sample))
    s = cutter.SplitSettings(mode="parts", parts=3)
    segs, _ = cutter.plan_segments(info.duration, s)
    seen = []
    r = cutter.split_video(ffmpeg_tools.Runner(), str(sample), info, s, tmp_path, "libx264", segs, jobs=3,
                           on_progress=lambda f, t: seen.append(f))
    assert [p.name for p in r.files] == [f"{sample.stem}_{i:02d}.mp4" for i in (1, 2, 3)] and not r.errors
    assert all(abs(dur(p) - 2.0) < 0.15 for p in r.files)
    assert seen[-1] == pytest.approx(1.0) and all(0 <= f <= 1 for f in seen)


def test_parallel_cancel_leaves_no_partial(media, tmp_path):
    from loopstation.core import cutter, ffmpeg_tools, probe
    sample, _ = media
    info = probe.probe(str(sample))
    s = cutter.SplitSettings(mode="parts", parts=3, aspect="9:16")
    segs, _ = cutter.plan_segments(info.duration, s)
    runner = ffmpeg_tools.Runner()
    with pytest.raises(ffmpeg_tools.CancelledError) as ei:
        cutter.split_video(runner, str(sample), info, s, tmp_path, "libx264", segs, jobs=3,
                           on_progress=lambda f, t: f > 0.2 and runner.cancel())
    left = sorted((tmp_path / sample.stem).iterdir())
    assert left == sorted(ei.value.files)  # chỉ còn đoạn đã xong hẳn
    assert all(probe.probe(str(p)).ok for p in left)


def test_hwdec_failure_falls_back_to_cpu(media, tmp_path):
    """Card không giải mã được video này (hoặc không có CUDA) → tự chạy lại bằng CPU, không báo lỗi."""
    from loopstation.core import cutter, ffmpeg_tools, probe
    sample, _ = media
    info = probe.probe(str(sample))
    s = cutter.SplitSettings(mode="parts", parts=2)
    segs, _ = cutter.plan_segments(info.duration, s)
    r = cutter.split_video(ffmpeg_tools.Runner(), str(sample), info, s, tmp_path, "libx264", segs,
                           hwdec="khong-co-that")
    assert len(r.files) == 2 and not r.errors
    f = cutter.extract_frames(ffmpeg_tools.Runner(), str(sample), info, cutter.FrameSettings(count=3), tmp_path / "a",
                              hwdec="khong-co-that")
    assert len(f.files) == 3 and not f.errors
