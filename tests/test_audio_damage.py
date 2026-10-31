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
