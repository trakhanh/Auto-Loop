from loopstation.core import profiles as prof
from loopstation.core.project import ClipItem, MusicTrack, Project


def test_capture_and_apply_keeps_clips(tmp_path):
    music = tmp_path / "nhac"
    music.mkdir()
    for n in ("a.mp3", "b.mp3"):
        (music / n).write_bytes(b"")
    intro = tmp_path / "intro.mp4"
    intro.write_bytes(b"")
    p = Project(name="x")
    p.video.intro, p.video.color_preset = str(intro), "warm"
    p.music.tracks = [MusicTrack(str(music / "a.mp3"))]
    p.export.resolution, p.export.output_dir, p.export.filename = "720p", str(tmp_path), "Tập 1"
    profile = prof.capture("Kênh A", p, "Loop A ×57 kẹp Loop B")
    assert profile["music_dir"] == str(music) and "filename" not in profile["export"]
    (music / "c.mp3").write_bytes(b"")  # bài mới thêm sau: hồ sơ theo thư mục nên có luôn

    q = Project(name="y")
    q.video.clips = [ClipItem("D:/v/1_LOOP A.mp4", count=57)]
    q.export.filename = "Tập 2"
    r, notes = prof.apply(profile, q)
    assert not notes
    assert r.video.intro == str(intro) and r.video.color_preset == "warm" and r.export.resolution == "720p"
    assert len(r.music.tracks) == 3 and r.video.clips[0].count == 57 and r.export.filename == "Tập 2"
    assert "Intro" in prof.describe(profile) and "mẫu: Loop A" in prof.describe(profile)


def test_apply_reports_missing_files(tmp_path):
    profile = {"name": "k", "video": {"intro": str(tmp_path / "khong-co.mp4")}, "music_dir": str(tmp_path / "mat"),
               "export": {"output_dir": str(tmp_path / "mat-luon")}}
    r, notes = prof.apply(profile, Project())
    assert r.video.intro == "" and len(notes) == 3
