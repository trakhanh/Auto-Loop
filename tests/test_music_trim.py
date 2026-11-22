"""Nhạc không phát từ đầu: (1) "Nhạc vào lúc" — nhạc bắt đầu ở một mốc bất kỳ trong video; (2) "Đoạn nghe" của từng
bài — bỏ đầu / bỏ cuối bài hát (vd bỏ 30 giây intro).

Chạy offscreen, dữ liệu + cài đặt vào thư mục tạm — không đụng dữ liệu thật của app."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VIDEO = sorted((ROOT / "Mau-Test" / "Video").glob("*.mp4"))
MUSIC = sorted((ROOT / "Mau-Test" / "Nhac").glob("*.mp3"))
need_media = pytest.mark.skipif(len(VIDEO) < 3 or len(MUSIC) < 3, reason="thiếu Mau-Test/")
_KEEP: list = []


def test_project_keeps_trim_and_start_at():
    from loopstation.core.project import MusicTrack, Project
    p = Project()
    p.music.tracks = [MusicTrack(path="a.mp3", trim_start=30.0, trim_end=12.5), MusicTrack(path="b.mp3")]
    p.music.start_at = 180.0
    q = Project.from_dict(p.to_dict())
    assert [(t.trim_start, t.trim_end) for t in q.music.tracks] == [(30.0, 12.5), (0.0, 0.0)]
    assert q.music.start_at == 180.0


def _proj(**music):
    from loopstation.core.project import ClipItem, MusicTrack, Project
    p = Project()
    p.video.clips = [ClipItem(str(v), count=10) for v in VIDEO[:3]]
    p.video.length_mode = "manual"
    p.music.tracks = [MusicTrack(path=str(m)) for m in MUSIC[:3]]
    for k, v in music.items():
        setattr(p.music, k, v)
    return p


@need_media
def test_trimmed_track_is_shorter_on_timeline():
    from loopstation.core import timeline
    p = _proj()
    full = timeline.build(p).track_durations[0]
    p.music.tracks[0].trim_start, p.music.tracks[0].trim_end = 20.0, 10.0
    tl = timeline.build(p)
    assert abs(tl.track_durations[0] - (full - 30.0)) < 0.05


@need_media
def test_music_starts_at_chosen_time():
    from loopstation.core import timeline
    tl = timeline.build(_proj(start_at=60.0))
    assert tl.ok and tl.music_items
    assert abs(tl.music_items[0].start - 60.0) < 0.05
    assert all(it.start >= 60.0 - 1e-6 for it in tl.music_items)


@need_media
def test_start_at_zero_is_unchanged():
    from loopstation.core import planner, timeline
    p = _proj()
    tl = timeline.build(p)
    assert tl.music_items == planner.plan_music(p.music, tl.track_durations, tl.total)


def test_graph_skips_the_start_of_a_trimmed_track():
    from loopstation.core import audio_build
    from loopstation.core.planner import MusicItem
    from loopstation.core.project import MusicSettings, MusicTrack
    ms = MusicSettings(tracks=[MusicTrack(path="a.mp3", trim_start=30.0), MusicTrack(path="b.mp3")])
    g = "".join(audio_build.music_graph([MusicItem(0, 0.0, 10.0), MusicItem(1, 7.0, 10.0)],
                                        {0: "a.mp3", 1: "b.mp3"}, {}, ms, 17.0))
    assert g.count("atrim=start=30.000") == 1


@need_media
def test_trimmed_track_really_starts_later(tmp_path):
    """Xuất thật: bài bỏ đầu 2 giây phải trùng với đoạn từ giây 2 của bài gốc."""
    os.environ.setdefault("KTLS_DATA_DIR", str(tmp_path / "data"))
    import struct
    import wave
    from loopstation.core import audio_build, ffmpeg_tools as ft
    from loopstation.core.planner import MusicItem
    from loopstation.core.project import MusicSettings, MusicTrack

    def render(trim: float, out: Path) -> list[int]:
        ms = MusicSettings(tracks=[MusicTrack(path=str(MUSIC[0]), trim_start=trim)])
        ms.fade_in = ms.fade_out = 0.0
        g = "".join(audio_build.music_graph([MusicItem(0, 0.0, 1.0)], {0: str(MUSIC[0])}, {}, ms, 1.0))
        ft.Runner().ffmpeg(["-v", "error", "-filter_complex", g + "[music]anull[o]", "-map", "[o]", "-ac", "1",
                            str(out)])
        with wave.open(str(out)) as wf:
            raw = wf.readframes(wf.getnframes())
        return [v for (v,) in struct.iter_unpack("<h", raw[: len(raw) // 2 * 2])]

    trimmed = render(2.0, tmp_path / "a.wav")
    ms = MusicSettings(tracks=[MusicTrack(path=str(MUSIC[0]))])
    ms.fade_in = ms.fade_out = 0.0
    g = "".join(audio_build.music_graph([MusicItem(0, 0.0, 3.0)], {0: str(MUSIC[0])}, {}, ms, 3.0))
    out = tmp_path / "b.wav"
    ft.Runner().ffmpeg(["-v", "error", "-filter_complex", g + "[music]atrim=start=2,asetpts=PTS-STARTPTS[o]",
                        "-map", "[o]", "-ac", "1", str(out)])
    with wave.open(str(out)) as wf:
        raw = wf.readframes(wf.getnframes())
    ref = [v for (v,) in struct.iter_unpack("<h", raw[: len(raw) // 2 * 2])]
    n = min(len(trimmed), len(ref), 20000)
    diff = sum(abs(a - b) for a, b in zip(trimmed[:n], ref[:n])) / n
    assert diff < 50, diff


# ---------------- trang Nhạc ----------------
@pytest.fixture(scope="module")
def env():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_musictrim_")
    mp.setenv("QT_QPA_PLATFORM", "offscreen")
    mp.setenv("KTLS_DATA_DIR", os.path.join(scratch, "data"))
    mp.setenv("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
    mp.setenv("KTLS_NO_UPDATE", "1")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from loopstation.ui import theme
    theme.apply(app, 10)
    settings = QSettings(os.path.join(scratch, "s.ini"), QSettings.Format.IniFormat)
    yield app, settings
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


@need_media
def test_music_tab_trim_and_legacy_start_at(env):
    from loopstation.core.project import MusicSettings, MusicTrack
    from loopstation.ui.music_tab import COL_DUR, MusicTab
    mt = MusicTab(env[1])
    _KEEP.append(mt)
    mt.load(MusicSettings(tracks=[MusicTrack(path=str(m)) for m in MUSIC[:2]], start_at=90.0))
    assert mt.collect().start_at == 90.0  # "Nhạc vào lúc" của dự án cũ giữ nguyên tới khi cửa sổ chính quy đổi
    mt.set_track_trim([0], 30.0, 5.0)
    t = mt.collect().tracks[0]
    assert (t.trim_start, t.trim_end) == (30.0, 5.0)
    it = mt.list.topLevelItem(0)
    assert "✂" in it.text(COL_DUR) and "0:30" in it.toolTip(COL_DUR)
    assert any("đoạn nghe" in txt.lower() for _ic, txt, _f in mt.list.menu_extras)
    assert not hasattr(mt, "start_at")  # ô "Nhạc vào lúc" đã gom vào dòng "Nhạc chạy từ clip …"
    mt.set_mode("music_only")
    assert not mt.range_bar.isVisibleTo(mt)
    mt.set_mode("video_music")
    assert mt.range_bar.isVisibleTo(mt)
