"""1.9.2 — lọc tạp âm tiếng gốc (gió, ù nền) kiểu Premiere Reduce Noise: trừ phổ tự học tạp âm theo đoạn."""
import subprocess

import numpy as np
import pytest

from loopstation.core import denoise, ffmpeg_tools as ft

SR = 48000


def _wind_steps(path, secs=20):
    """Gió (tiếng ồn nâu, đều) + "bước chân" (chùm tiếng lạo xạo 0,15 s, mỗi 0,8 s) — giống video đi trên tuyết."""
    rnd = np.random.default_rng(5)
    n = secs * SR
    wind = np.cumsum(rnd.standard_normal(n)).astype(np.float32)
    wind -= np.convolve(wind, np.ones(4801) / 4801, mode="same")  # bỏ trôi DC
    wind *= 0.02 / (np.abs(wind).mean() + 1e-9)
    steps = np.zeros(n, dtype=np.float32)
    burst = int(0.15 * SR)
    for s in range(SR // 2, n - burst, int(0.8 * SR)):
        env = np.hanning(burst).astype(np.float32)
        steps[s:s + burst] += rnd.standard_normal(burst).astype(np.float32) * env * 0.25
    x = np.stack([wind + steps, wind * 0.9 + steps], axis=1)
    raw = path.with_suffix(".raw")
    x.astype(np.float32).tofile(raw)
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(raw),
                    "-c:a", "aac", "-b:a", "256k", str(path)], check=True)
    return n, burst


def _pcm(path):
    out = subprocess.run([ft.ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def _db(x):
    return 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


@pytest.fixture()
def clip(tmp_path, monkeypatch):
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    p = tmp_path / "di-tren-tuyet.m4a"
    _wind_steps(p)
    return p


def _gaps_and_steps(x, secs=20):
    burst = int(0.15 * SR)
    starts = list(range(SR // 2, secs * SR - burst, int(0.8 * SR)))
    gaps = np.concatenate([x[s + burst + 2000:s + int(0.8 * SR) - 2000] for s in starts[:-1]])
    steps = np.concatenate([x[s + burst // 4:s + 3 * burst // 4] for s in starts])
    return _db(gaps), _db(steps)


@pytest.mark.parametrize("level, min_cut", [("light", 5), ("medium", 10), ("strong", 14)])
def test_wind_removed_steps_kept(clip, level, min_cut):
    r = ft.Runner()
    out = denoise.denoised_copy(r, str(clip), level)
    src, got = _pcm(clip), _pcm(out)
    assert abs(len(got) - len(src)) <= 2  # đúng độ dài: thay thẳng vào chỗ tiếng gốc, không lệch hình
    g0, s0 = _gaps_and_steps(src)
    g1, s1 = _gaps_and_steps(got)
    assert g0 - g1 >= min_cut  # gió giữa các bước chân bị trừ
    assert s0 - s1 <= 4  # tiếng bước chân giữ gần nguyên
    assert denoise.denoised_copy(r, str(clip), level) == out  # lần sau dùng lại bộ nhớ đệm
    left = [p.name for p in ft.cache_dir("denoise").iterdir() if not p.name.endswith(".flac")]
    assert left == []  # không sót file tạm


def test_alignment_sample_exact(tmp_path, monkeypatch):
    """Tiếng chỉ có một xung ở giây 3,5: bản lọc phải giữ xung đúng mẫu đó (khối tiếng gốc cắt theo số mẫu)."""
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    rnd = np.random.default_rng(1)
    n = 6 * SR
    x = (rnd.standard_normal((n, 2)) * 0.01).astype(np.float32)
    at = int(3.5 * SR)
    x[at:at + 480] += 0.8
    raw = tmp_path / "x.raw"
    x.tofile(raw)
    wav = tmp_path / "x.wav"
    subprocess.run([ft.ffmpeg(), "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(raw), str(wav)],
                   check=True)
    got = _pcm(denoise.denoised_copy(ft.Runner(), str(wav), "strong"))
    assert len(got) == n
    assert abs(int(np.argmax(np.abs(got))) - at) < 480


def test_render_with_denoise_and_project_roundtrip(clip, tmp_path):
    from loopstation.core.project import ClipItem, Project
    from loopstation.core.render import RenderJob
    video = tmp_path / "clip.mp4"
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=20", "-i",
                    str(clip), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
                    "-shortest", str(video)], check=True)
    p = Project(name="tuyet", output_kind="video_only")
    p.video.clips = [ClipItem(str(video), count=2)]
    p.video.source_audio = "only"
    p.video.source_level = False
    p.video.denoise = "medium"
    p.export.encoder = "cpu"
    saved = tmp_path / "du-an.lsproj"
    p.save(str(saved))
    assert Project.load(str(saved)).video.denoise == "medium"
    logs = []
    out = RenderJob(p, {"h264": ["cpu"]}, str(tmp_path / "ra.mp4"), on_log=logs.append).run()
    assert any("Lọc tạp âm tiếng gốc" in line for line in logs)
    a = _pcm(out)
    g0, _ = _gaps_and_steps(_pcm(clip))
    g1, _ = _gaps_and_steps(a[:20 * SR])
    assert g0 - g1 >= 10  # video xuất ra dùng đúng tiếng đã lọc


def test_profile_keeps_denoise():
    from loopstation.core import profiles
    assert "denoise" in profiles.VIDEO_KEYS


def test_denoise_tool_keeps_video_and_names_output(clip, tmp_path):
    """Công cụ Lọc tạp âm video: hình chép nguyên (đủ mọi khung), tiếng đã lọc, ra tên _DeNoise cạnh file gốc."""
    from loopstation.ui.denoise_dialog import denoise_file, output_path
    video = tmp_path / "demo_NoDeNoise.mp4"
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=20.04", "-i",
                    str(clip), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
                    str(video)], check=True)
    out = denoise_file(ft.Runner(), str(video), "medium", output_path(str(video)))
    assert out.name == "demo_NoDeNoise_DeNoise.mp4" and out.parent == tmp_path
    assert output_path(str(video)).name == "demo_NoDeNoise_DeNoise2.mp4"  # không ghi đè bản trước

    def md5(p):
        return subprocess.run([ft.ffmpeg(), "-v", "error", "-i", str(p), "-map", "0:v", "-c", "copy", "-f", "md5",
                               "-"], capture_output=True, text=True).stdout
    assert md5(video) == md5(out)  # hình y nguyên, không mã hoá lại, không mất khung cuối
    g0, _ = _gaps_and_steps(_pcm(video))
    g1, _ = _gaps_and_steps(_pcm(out))
    assert g0 - g1 >= 10
    song = tmp_path / "nhac.mp3"
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-i", str(clip), str(song)], check=True)
    assert output_path(str(song)).suffix == ".m4a"  # file chỉ có tiếng → .m4a
    assert denoise_file(ft.Runner(), str(song), "light", output_path(str(song))).is_file()
