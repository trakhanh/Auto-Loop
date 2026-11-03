"""1.8.10 — file nhạc / tiếng gốc có cả một vùng dữ liệu rác (file chưa tải hết từ Google Drive, ổ hỏng…): gói rác giải
ra âm thanh "37 kênh" → ffmpeg dừng cả lệnh ("Rematrix is needed…"), cả bước đo âm lượng lẫn bước tạo bản sạch.
Giờ: bản sạch giải mã từng đoạn (chỗ hỏng thành im lặng, giữ đúng độ dài), bước đo không bao giờ làm dừng lượt xuất."""
import random
import subprocess

import pytest

from loopstation.core import audio_build, ffmpeg_tools as ft


def _song(path, secs=60):
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"anoisesrc=d={secs}:c=pink:seed=7",
                    "-c:a", "aac", "-b:a", "128k", str(path)], check=True)


def _garbage(src, dst, start=0.5, size=0.45, seed=1):
    d = bytearray(src.read_bytes())
    rnd = random.Random(seed)
    lo = int(len(d) * start)
    hi = min(len(d) - 3000, lo + int(len(d) * size))
    d[lo:hi] = bytes(rnd.randrange(256) for _ in range(hi - lo))
    dst.write_bytes(bytes(d))


@pytest.fixture()
def rac(tmp_path, monkeypatch):
    """Bài 60 giây có vùng rác làm ffmpeg dừng hẳn (kiểm tra trước: kiểu cũ đúng là không tạo nổi bản sạch)."""
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    good, bad = tmp_path / "goc.m4a", tmp_path / "rac.m4a"
    _song(good)
    _garbage(good, bad)
    old = subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-err_detect", "ignore_err", "-i", str(bad), "-vn",
                          "-c:a", "flac", str(tmp_path / "cu.flac")], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if old.returncode == 0:
        pytest.skip("bản ffmpeg này không còn dừng ở file rác mẫu")
    return bad


def test_clean_copy_survives_garbage_and_keeps_length(rac):
    r = ft.Runner()
    assert audio_build.is_damaged(r, str(rac))
    out = audio_build.clean_copy(r, str(rac))
    assert abs(audio_build._seconds(audio_build.Path(out)) - 60.0) < 0.1  # chỗ hỏng thành im lặng, không lệch giờ
    assert not audio_build.fails_in_graph(r, out)  # ghép bằng amovie đọc được
    assert audio_build.measure_loudness(r, out) is not None
    left = [p.name for p in audio_build.Path(out).parent.iterdir() if p.name != audio_build.Path(out).name]
    assert left == []  # không sót đoạn tạm


def test_lightly_damaged_clean_copy_keeps_length(tmp_path, monkeypatch):
    """Hỏng nhẹ (kiểu cũ tạo được bản sạch) nhưng trước đây bản sạch ngắn hơn bài gốc → nhạc phía sau bị dồn sớm."""
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    good, bad = tmp_path / "goc.m4a", tmp_path / "hong.m4a"
    _song(good)
    _garbage(good, bad, 0.2, 0.4)
    r = ft.Runner()
    out = audio_build.clean_copy(r, str(bad))
    assert abs(audio_build._seconds(audio_build.Path(out)) - 60.0) < 0.1


def test_loudness_never_stops_render(tmp_path, monkeypatch):
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))

    def boom(runner, path):
        raise ft.FFmpegError("ffmpeg lỗi", "Conversion failed!")
    monkeypatch.setattr(audio_build, "measure_loudness", boom)
    monkeypatch.setattr(audio_build, "clean_copy", lambda runner, path: path)
    logs = []
    assert audio_build.loudness_or_none(ft.Runner(), str(tmp_path / "x.m4a"), str(tmp_path / "x.m4a"),
                                        logs.append) is None
    assert logs and "giữ nguyên âm lượng" in logs[0]


def _render(tmp_path, clip, music=None, source="off"):
    from loopstation.core.project import ClipItem, MusicTrack, Project
    from loopstation.core.render import RenderJob
    p = Project(name="rac", output_kind="video_music" if music else "video_only")
    p.video.clips = [ClipItem(str(clip), count=2)]
    p.video.source_audio = source
    if music:
        p.music.tracks = [MusicTrack(str(music))]
    p.export.encoder = "cpu"
    logs = []
    out = RenderJob(p, {"h264": ["cpu"]}, str(tmp_path / "ra.mp4"), on_log=logs.append).run()
    return out, logs


def _clip(path, audio=None, secs=20):
    a = ["-i", str(audio)] if audio else ["-f", "lavfi", "-i", f"anoisesrc=d={secs}:c=pink:seed=5"]
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=24:d={secs}", *a,
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    *(["-c:a", "copy"] if audio else ["-c:a", "aac"]), "-shortest", str(path)], check=True)


def test_garbage_music_renders(rac, tmp_path):
    clip = tmp_path / "clip.mp4"
    _clip(clip)
    out, logs = _render(tmp_path, clip, music=rac)  # trước đây: "Conversion failed!" ở bước đo âm lượng nhạc
    assert out.is_file() and out.stat().st_size > 0
    assert any("rac.m4a có đoạn bị hỏng" in line for line in logs)


def test_garbage_source_audio_renders(rac, tmp_path):
    clip = tmp_path / "clip_rac.mp4"
    _clip(clip, audio=rac, secs=60)
    out, logs = _render(tmp_path, clip, source="only")
    assert out.is_file() and out.stat().st_size > 0
    assert any("tách lại" in line for line in logs)
