from pathlib import Path

from loopstation.core import batch
from loopstation.core import interleave as il
from loopstation.core.project import ClipItem, MusicTrack, Project


def touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")


def test_scan_and_build(tmp_path):
    touch(tmp_path / "Video 2" / "loop_b.mp4")
    touch(tmp_path / "Video 2" / "3_x.mp4")
    touch(tmp_path / "Video 2" / "2_y.mp4")
    touch(tmp_path / "Video 2" / "Nhac" / "song.mp3")
    touch(tmp_path / "Video 10" / "a.mp4")
    touch(tmp_path / "Video 10" / "b.png")
    (tmp_path / "Video 3 trống").mkdir()
    touch(tmp_path / "_chung" / "z.mp4")  # thư mục bắt đầu bằng _ bị bỏ qua
    jobs = batch.scan(str(tmp_path))
    assert [j.name for j in jobs] == ["Video 2", "Video 3 trống", "Video 10"]
    v2, v3, v10 = jobs
    assert Path(v2.base).name == "loop_b.mp4" and [Path(m).name for m in v2.music] == ["song.mp3"]
    assert v3.error and v10.base is None and v10.notes

    tpl = Project(name="khuôn")
    tpl.music.tracks = [MusicTrack("chung.mp3")]

    def arrange(clips, b):
        return il.build(clips, il.InterleaveOptions(base_index=b, base_plays=("fixed", 70, 70, 0.0)))

    p2 = batch.build_project(tpl, v2, "auto", arrange, loop_xfade=1.0, next_xfade=0.5)
    assert [Path(c.path).name for c in p2.video.clips] == ["loop_b.mp4", "2_y.mp4", "loop_b.mp4", "3_x.mp4",
                                                           "loop_b.mp4"]
    assert p2.video.clips[0].count == 70 and p2.video.clips[0].loop_xfade == 1.0
    assert all(c.next_xfade == 0.5 for c in p2.video.clips)
    assert [Path(t.path).name for t in p2.music.tracks] == ["song.mp3"]  # nhạc riêng của thư mục
    assert p2.name == "Video 2" and p2.export.filename == "Video 2"
    p10 = batch.build_project(tpl, v10, "auto", arrange)
    assert [Path(c.path).name for c in p10.video.clips] == ["a.mp4", "b.png"]
    assert [t.path for t in p10.music.tracks] == ["chung.mp3"]  # thiếu nhạc → playlist của khuôn
    assert batch.build_project(tpl, v10, "folder").music.tracks == []
    assert tpl.music.tracks[0].path == "chung.mp3" and not tpl.video.clips  # khuôn không bị đổi


def test_scan_music_only(tmp_path):
    touch(tmp_path / "Playlist A" / "1.mp3")
    touch(tmp_path / "Playlist B" / "clip.mp4")
    jobs = batch.scan(str(tmp_path), music_only=True)
    assert not jobs[0].error and jobs[1].error


def test_manual_override_keeps_order_and_applies_crossfade(tmp_path):
    for n in ("loop_a.mp4", "2_b.mp4", "3_c.mp4"):
        touch(tmp_path / "V" / n)
    job = batch.scan(str(tmp_path))[0]
    manual = [ClipItem(str(tmp_path / "V" / "loop_a.mp4"), count=5),
              ClipItem(str(tmp_path / "V" / "3_c.mp4")), ClipItem(str(tmp_path / "V" / "loop_a.mp4"), count=5),
              ClipItem(str(tmp_path / "V" / "2_b.mp4"))]
    p = batch.build_project(Project(), job, "auto", None, loop_xfade=2.0, next_xfade=0.5, clips_override=manual)
    assert [Path(c.path).name for c in p.video.clips] == ["loop_a.mp4", "3_c.mp4", "loop_a.mp4", "2_b.mp4"]
    assert p.video.clips[0].loop_xfade == 2.0 and all(c.next_xfade == 0.5 for c in p.video.clips)
    assert manual[0].loop_xfade == 0.0  # bản chỉnh tay gốc không bị sửa


def test_batch_source_audio_choice(tmp_path):
    touch(tmp_path / "V" / "loop_a.mp4")
    job = batch.scan(str(tmp_path))[0]
    tpl = Project()
    assert tpl.video.source_audio == "mix"  # mặc định: giữ tiếng gốc clip
    assert batch.build_project(tpl, job).video.source_audio == "mix"  # theo khuôn
    assert batch.build_project(tpl, job, source_audio="off").video.source_audio == "off"
    assert batch.build_project(tpl, job, source_audio="only").video.source_audio == "only"
    assert tpl.video.source_audio == "mix"  # khuôn không đổi
