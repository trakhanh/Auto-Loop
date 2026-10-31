import random
import subprocess

from loopstation.core import audio_build, ffmpeg_tools as ft


def _make(path, corrupt: bool):
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=color=pink:d=20",
                    "-c:a", "aac", "-b:a", "192k", str(path)], check=True)
    if corrupt:  # rải byte hỏng giữa phần âm thanh (như file tải về bị lỗi)
        d = bytearray(path.read_bytes())
        rnd = random.Random(3)
        for _ in range(300):
            i = rnd.randint(len(d) // 3, len(d) * 2 // 3)
            d[i] = rnd.randint(0, 255)
        path.write_bytes(bytes(d))


def test_damaged_music_gets_clean_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    good, bad = tmp_path / "lanh.m4a", tmp_path / "hong.m4a"
    _make(good, False)
    _make(bad, True)
    r = ft.Runner()
    assert not audio_build.is_damaged(r, str(good))
    assert audio_build.is_damaged(r, str(bad))
    logs = []
    out = audio_build.usable_paths(r, {0: str(good), 1: str(bad), 2: str(bad)}, logs.append)
    assert out[0] == str(good)  # bài lành: dùng nguyên file
    assert out[1] == out[2] and out[1].endswith(".flac") and "cleanaudio" in out[1]
    assert len(logs) == 1 and "hong.m4a" in logs[0]
    # bản sạch đọc bằng amovie (cách app ghép nhạc) không còn lỗi
    src = audio_build.escape_filter_value(out[1].replace("\\", "/"))
    p = subprocess.run([ft.ffmpeg(), "-v", "error", "-filter_complex", f"amovie=filename={src}[o]", "-map", "[o]",
                        "-f", "null", "-"], capture_output=True, text=True)
    assert p.returncode == 0


def test_damage_missed_by_quick_check_retries_with_clean_copies(tmp_path, monkeypatch):
    """Bài hỏng mà bước kiểm tra nhanh báo "lành" (hoặc tiếng nền hỏng): lượt ghép lỗi → tự dùng bản sạch, ghép lại."""
    import json
    from loopstation.core.project import AmbientLayer, MusicTrack, Project
    from loopstation.core.render import RenderJob
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    music, amb = tmp_path / "nhac.m4a", tmp_path / "nen.m4a"
    _make(music, True)
    _make(amb, True)
    # giả lập kiểm tra nhanh bỏ sót: sổ ghi "lành" cho cả hai file
    db = {audio_build._file_id(str(p)): False for p in (music, amb)}
    (tmp_path / "data").mkdir(exist_ok=True)
    audio_build._check_db_path().write_text(json.dumps(db), encoding="utf-8")
    p = Project(name="Hỏng")
    p.music.tracks = [MusicTrack(str(music))]
    p.music.ambient = [AmbientLayer(str(amb), volume=40)]
    p.music.export_mode, p.music.export_target, p.music.export_format = "target", 45.0, "wav"
    p.music.loudness_enabled = False
    logs = []
    out = RenderJob(p, {}, str(tmp_path / "ra.wav"), on_log=logs.append, audio_only=True).run()
    assert out.is_file() and out.stat().st_size > 1_000_000
    assert any("ghép lại" in s or "dựng lại" in s for s in logs), logs
    r = ft.Runner()
    assert audio_build.is_damaged(r, str(music)) and audio_build.is_damaged(r, str(amb))  # lần sau dùng bản sạch ngay


def test_damaged_ambient_uses_clean_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    amb = tmp_path / "nen.m4a"
    _make(amb, True)
    from loopstation.core.project import AmbientLayer, Project
    from loopstation.core.render import RenderJob
    p = Project(name="Nền")
    p.music.ambient = [AmbientLayer(str(amb), volume=40)]
    p.music.export_mode, p.music.export_target, p.music.export_format = "target", 30.0, "wav"
    logs = []
    out = RenderJob(p, {}, str(tmp_path / "nen.wav"), on_log=logs.append, audio_only=True).run()
    assert out.is_file()
    assert any("nen.m4a có đoạn bị hỏng" in s for s in logs), logs
    assert not any("ghép lại" in s or "dựng lại" in s for s in logs)


def test_second_audio_stream_damaged(tmp_path, monkeypatch):
    """File 2 luồng âm thanh, luồng hỏng không phải luồng đầu (bản 1.8.7 bỏ sót → xuất lỗi “Pulse data corrupt”)."""
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    bad, mono, two = tmp_path / "hong.m4a", tmp_path / "mono.m4a", tmp_path / "hai_luong.m4a"
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=color=pink:d=20", "-ac", "2",
                    "-c:a", "aac", "-b:a", "192k", str(bad)], check=True)
    d = bytearray(bad.read_bytes())
    rnd = random.Random(3)
    for _ in range(300):
        i = rnd.randint(len(d) // 3, len(d) * 2 // 3)
        d[i] = rnd.randint(0, 255)
    bad.write_bytes(bytes(d))
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:d=20", "-c:a", "aac",
                    "-b:a", "64k", "-ac", "1", str(mono)], check=True)
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-i", str(mono), "-i", str(bad), "-map", "0:a", "-map", "1:a",
                    "-c", "copy", str(two)], check=True)
    r = ft.Runner()
    assert audio_build.is_damaged(r, str(two))
    clean = audio_build.usable_paths(r, {0: str(two)})[0]
    assert clean.endswith(".flac")
    ch = subprocess.run([ft.ffprobe(), "-v", "error", "-show_entries", "stream=channels", "-of", "csv=p=0", clean],
                        capture_output=True, text=True).stdout.split()
    assert ch == ["2"]  # đúng luồng mà ghép nhạc (amovie) chọn: stereo, không phải luồng mono đầu tiên
    src = audio_build.escape_filter_value(clean.replace("\\", "/"))
    p = subprocess.run([ft.ffmpeg(), "-v", "error", "-filter_complex", f"amovie=filename={src}[o]", "-map", "[o]",
                        "-f", "null", "-"], capture_output=True, text=True)
    assert p.returncode == 0
