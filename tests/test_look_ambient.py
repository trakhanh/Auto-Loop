from pathlib import Path

from loopstation.core import look, timeline
from loopstation.core.project import AmbientLayer, Project, VideoSettings

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "loopstation" / "ui" / "assets" / "logo-512.png"


def test_look_off_by_default():
    assert look.from_settings(VideoSettings()) is None


def test_look_graph_color_strength_and_logo():
    vs = VideoSettings(color_preset="warm", color_strength=40, logo=str(LOGO), logo_opacity=60, logo_pos="bottom_left",
                       logo_size=10)
    lk = look.from_settings(vs)
    g = look.graph(lk, "pre", "lk", 1920, 1080)
    assert "blend=all_mode=normal:all_opacity=0.400" in g  # cường độ 40% = trộn với hình gốc
    assert "colorchannelmixer=aa=0.600" in g and "scale=192:-1" in g and "y=H-h-" in g
    assert g.endswith("[lk]")
    full = look.graph(look.Look(color="bw", strength=100), "a", "b", 1280, 720)
    assert "blend" not in full and "hue=s=0" in full
    frame = look.graph(look.Look(logo=str(LOGO), logo_pos="frame"), "a", "b", 1280, 720)
    assert "scale=1280:720" in frame and "x=0:y=0" in frame


def test_look_key_changes_with_settings():
    a = look.Look(color="warm", strength=50).key()
    b = look.Look(color="warm", strength=60).key()
    assert a != b


def test_ambient_only_music_file():
    p = Project(output_kind="music_only")
    p.music.ambient = [AmbientLayer(str(ROOT / "Mau-Test" / "Tieng-nen" / "Mưa rơi.mp3"), volume=60)]
    p.music.export_mode, p.music.export_target = "rounds", 600  # lượt playlist không áp dụng → theo thời lượng
    tl = timeline.build_audio(p)
    assert tl.ok and tl.total == 600 and not tl.music_items
    p.music.ambient = []
    assert not timeline.build_audio(p).ok


def test_builtin_ambient_saved_as_key(tmp_path):
    p = Project(output_kind="music_only")
    p.music.ambient = [AmbientLayer("builtin:rain_heavy", volume=70)]
    f = tmp_path / "x.lsproj"
    p.save(str(f))
    assert '"builtin:rain_heavy"' in f.read_text(encoding="utf-8")
    q = Project.load(str(tmp_path / "x.lsproj"))
    assert q.music.ambient[0].path == "builtin:rain_heavy"
