"""Bảng trộn âm (1.4.4): âm lượng riêng từng bài, âm lượng nhạc ở kiểu Chỉ nhạc, nghe thử 20 giây."""
import re
import subprocess
from pathlib import Path

import pytest

from loopstation.core import audio_build, audio_preview
from loopstation.core import ffmpeg_tools as ft
from loopstation.core.planner import MusicItem
from loopstation.core.project import AmbientLayer, ClipItem, MusicSettings, MusicTrack, Project

ROOT = Path(__file__).resolve().parents[1]
CLIPS = sorted((ROOT / "samples" / "clips").glob("*.mp4"))
RAIN = ROOT / "samples" / "extra" / "Mưa (tiếng nền).wav"


def test_track_volume_roundtrip(tmp_path):
    p = Project()
    p.music.tracks = [MusicTrack(str(tmp_path / "a.mp3"), volume=40), MusicTrack(str(tmp_path / "b.mp3"))]
    p.video.music_volume = 70
    f = tmp_path / "x.lsproj"
    p.save(str(f))
    q = Project.load(str(f))
    assert [t.volume for t in q.music.tracks] == [40, 100] and q.video.music_volume == 70
    assert "volume" not in f.read_text(encoding="utf-8").split('"b.mp3"')[1].split("}")[0]  # 100% không ghi thừa


def test_volume_db_and_gains():
    assert abs(audio_build.volume_db(50) + 6.02) < 0.01 and audio_build.volume_db(100) == 0
    assert audio_build.volume_db(0) <= -90
    ms = MusicSettings()
    ms.loudness_enabled = False
    ms.tracks = [MusicTrack("a.mp3", volume=50), MusicTrack("b.mp3")]
    g = audio_build.track_gains(ft.Runner(), ms, {0: "a.mp3", 1: "b.mp3"})
    assert set(g) == {0} and abs(g[0] + 6.02) < 0.01
    lines = audio_build.music_graph([MusicItem(0, 0, 5)], {0: "a.mp3"}, g, ms, 5)
    assert "volume=-6.02dB" in lines[0]


def _mean_db(path: Path) -> float:
    r = subprocess.run([ft.ffmpeg(), "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return float(re.search(r"mean_volume: (-?[\d.]+)", r.stderr).group(1))


def _dur(path: Path) -> float:
    r = subprocess.run([ft.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout)


@pytest.mark.skipif(not CLIPS or not RAIN.exists(), reason="thiếu samples/")
def test_preview_20s_follows_mixer(tmp_path, monkeypatch):
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    p = Project(output_kind="video_only")
    p.video.clips = [ClipItem(str(c), count=3) for c in CLIPS[:2]]
    p.video.source_audio = "mix"
    p.music.ambient = [AmbientLayer(str(RAIN), volume=100)]
    a = audio_preview.render_preview(p, 5)
    assert abs(_dur(a) - 20) < 0.05
    loud = _mean_db(a)
    p.music.ambient[0].volume = 25
    p.video.source_volume = 25
    b = audio_preview.render_preview(p, 5)
    assert _mean_db(b) < loud - 8  # cả hai nguồn 25% ≈ nhỏ đi 12 dB
    p.music.ambient = []
    p.video.source_audio = "off"
    p.video.intro = p.video.outro = ""
    with pytest.raises(audio_preview.PreviewError):
        audio_preview.render_preview(p, 0)
    assert len(list(ft.preview_dir().glob("nghe-thu_*.wav"))) <= 2  # bản cũ tự dọn


@pytest.mark.skipif(not CLIPS or not RAIN.exists(), reason="thiếu samples/")
def test_stems_mix_like_export(tmp_path, monkeypatch):
    """Kênh riêng + hoà trong app ≈ bản trộn sẵn của FFmpeg (cùng âm lượng)."""
    import wave
    from loopstation.ui.live_mix import Mixer, read_pcm
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    p = Project(output_kind="video_only")
    p.video.clips = [ClipItem(str(c), count=3) for c in CLIPS[:2]]
    p.video.source_audio, p.video.source_volume = "mix", 60
    p.music.ambient = [AmbientLayer(str(RAIN), volume=0), AmbientLayer(str(RAIN), volume=30, enabled=False)]
    st = audio_preview.render_stems(p, 5)
    assert set(st.files) == {"source", "amb:0"}  # lớp 0% vẫn có kênh (kéo lên khi đang nghe), lớp tắt thì không
    data = {k: read_pcm(f) for k, f in st.files.items()}
    assert all(len(b) == len(data["source"]) for b in data.values())
    p.music.ambient[0].volume = 80
    ref = audio_preview.render_preview(p, 5)
    out = tmp_path / "mix.wav"
    with wave.open(str(out), "wb") as f:
        f.setnchannels(2), f.setsampwidth(2), f.setframerate(48000)
        f.writeframes(Mixer(data, {"source": 0.6, "amb:0": 0.8}).mix_all())
    assert abs(_mean_db(out) - _mean_db(ref)) < 0.6


def test_mixer_gain_and_limiter():
    import audioop
    from loopstation.ui.live_mix import LIMIT, Mixer
    tone = (16384).to_bytes(2, 'little', signed=True) * 2 * 4800  # 0.1 s, mức 16384
    m = Mixer({"a": tone}, {"a": 0.5})
    assert abs(audioop.max(m.mix_all(), 2) - 8192) <= 2
    m = Mixer({"a": tone, "b": tone}, {"a": 2.0, "b": 2.0})  # 4 × 16384 → bị giới hạn
    assert audioop.max(m.mix_all(), 2) <= LIMIT + 2
    m = Mixer({"a": tone}, {"a": 1.0})
    first = m.mix(4800)
    m.gains["a"] = 0.0  # đổi giữa chừng có tác dụng ngay ở đoạn sau
    assert audioop.max(first, 2) > 16000 and audioop.max(m.mix(4800), 2) == 0
