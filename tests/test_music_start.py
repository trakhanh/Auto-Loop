"""Chọn bài nhạc theo clip: ô "Nhạc" của mỗi clip = Tiếp tục / Không nhạc / Bắt đầu bằng bài X. Tới clip "bắt đầu bằng
bài 1" thì phát bài 1 từ đầu, hết bài thì sang bài 2, 3… qua các clip sau (để "Tiếp tục").

Chạy offscreen, dữ liệu + cài đặt vào thư mục tạm — không đụng dữ liệu thật của app."""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VIDEO = sorted((ROOT / "Mau-Test" / "Video").glob("*.mp4"))
MUSIC = sorted((ROOT / "Mau-Test" / "Nhac").glob("*.mp3"))
need_media = pytest.mark.skipif(len(VIDEO) < 5 or len(MUSIC) < 3, reason="thiếu Mau-Test/")
_KEEP: list = []


def _ms(**kw):
    from loopstation.core.project import MusicSettings, MusicTrack
    ms = MusicSettings(tracks=[MusicTrack(path=f"t{i}.mp3") for i in range(3)])
    ms.crossfade, ms.gap = 0.0, 0.0
    for k, v in kw.items():
        setattr(ms, k, v)
    return ms


# ---------------- lịch nhạc ----------------
def test_forced_start_track_then_playlist_continues():
    from loopstation.core import planner
    d = {0: 6.0, 1: 6.0, 2: 6.0}
    items = planner.plan_music_windows(_ms(), d, [(0.0, 10.0, None), (10.0, 30.0, 0)], 30.0)
    got = [(it.track, round(it.start, 3), round(it.duration, 3)) for it in items]
    # 0–10: bài 0, bài 1 (cắt) · từ 10: bắt đầu lại bằng bài 0, rồi 1, 2, 0
    assert got == [(0, 0.0, 6.0), (1, 6.0, 4.0), (0, 10.0, 6.0), (1, 16.0, 6.0), (2, 22.0, 6.0), (0, 28.0, 2.0)]
    assert items[1].cut and not items[0].cut  # bài bị cắt ở chỗ đổi bài: dựng âm thanh cho nhỏ dần


def test_forced_start_after_silence():
    from loopstation.core import planner
    d = {0: 6.0, 1: 6.0, 2: 6.0}
    items = planner.plan_music_windows(_ms(), d, [(12.0, 20.0, 2)], 20.0)
    assert [(it.track, it.start) for it in items] == [(2, 12.0), (0, 18.0)]


def test_cut_item_fades_even_without_gap():
    from loopstation.core import audio_build
    from loopstation.core.planner import MusicItem
    a = MusicItem(0, 0.0, 4.0)
    a.cut = True
    items = [a, MusicItem(1, 4.0, 6.0)]
    fi, fo, pad, lead = audio_build.music_edges(items, _ms(), 10.0)
    assert fo[0] > 0 and fi[1] > 0 and pad[0] == 0 and lead == 0


def test_project_keeps_music_start(tmp_path):
    from loopstation.core.project import ClipItem, Project
    p = Project()
    p.video.clips = [ClipItem("a.mp4"), ClipItem("b.mp4", music_start="C:/n/bai1.mp3")]
    q = Project.from_dict(p.to_dict())
    norm = lambda x: os.path.normcase(os.path.normpath(x)) if x else ""  # noqa: E731
    assert [norm(c.music_start) for c in q.video.clips] == ["", norm("C:/n/bai1.mp3")]


# ---------------- timeline ----------------
@pytest.fixture(scope="module")
def env():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_musicstart_")
    mp.setenv("QT_QPA_PLATFORM", "offscreen")
    mp.setenv("KTLS_DATA_DIR", os.path.join(scratch, "data"))
    mp.setenv("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
    mp.setenv("KTLS_NO_UPDATE", "1")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    from loopstation.ui import theme
    theme.apply(app, 10)
    mp.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    mp.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    settings = QSettings(os.path.join(scratch, "s.ini"), QSettings.Format.IniFormat)
    yield app, settings, Path(scratch)
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def _proj(clips):
    from loopstation.core.project import ClipItem, MusicTrack, Project
    p = Project()
    p.video.clips = [ClipItem(str(VIDEO[k % len(VIDEO)]), count=4, **kw) for k, kw in enumerate(clips)]
    p.video.length_mode = "manual"
    p.music.tracks = [MusicTrack(path=str(m)) for m in MUSIC[:3]]
    return p


def _clip_start(tl, row):
    from fractions import Fraction
    pos, plan = 0, tl.video
    for j, (clip, _r) in enumerate(plan.plays):
        f = plan.ends.get(j, tl.frames[clip])
        if clip == row:
            return float(Fraction(pos) / tl.fps)
        if j < len(plan.overlaps):
            pos += f - plan.overlaps[j]
    raise AssertionError(row)


@need_media
def test_song_one_starts_at_clip_five(env):
    from loopstation.core import timeline
    clips = [dict(music=False)] * 4 + [dict(music_start=str(MUSIC[0]))] + [dict()] * 3
    tl = timeline.build(_proj(clips))
    assert tl.ok, tl.errors
    first = tl.music_items[0]
    assert first.track == 0 and abs(first.start - _clip_start(tl, 4)) < 0.05


@need_media
def test_pick_second_song_for_clip_three_without_silence(env):
    from loopstation.core import timeline
    clips = [dict()] * 2 + [dict(music_start=str(MUSIC[2]))] + [dict()] * 2
    tl = timeline.build(_proj(clips))
    t3 = _clip_start(tl, 2)
    at = [it for it in tl.music_items if abs(it.start - t3) < 0.05]
    assert at and at[0].track == 2
    assert all(it.start + it.duration <= t3 + 0.05 for it in tl.music_items if it.start < t3 - 0.05)


@need_media
def test_all_continue_is_unchanged(env):
    from loopstation.core import planner, timeline
    p = _proj([dict()] * 3)
    tl = timeline.build(p)
    assert tl.music_items == planner.plan_music(p.music, tl.track_durations, tl.total)


# ---------------- bảng clip: ô Nhạc ----------------
def _tab(env, clips):
    from loopstation.core.project import ClipItem, VideoSettings
    from loopstation.ui import video_tab as vt
    tab = vt.VideoTab(env[1])
    tab.load(VideoSettings(clips=[ClipItem(str(VIDEO[k % len(VIDEO)]), count=1, **kw) for k, kw in enumerate(clips)]))
    tab.set_tracks([(str(m), m.stem) for m in MUSIC[:3]])
    tab.resize(1300, 800)
    tab.show()
    _KEEP.append(tab)
    return tab


def pump(app, sec=0.1):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


@need_media
def test_music_cell_choices_and_undo(env):
    from loopstation.ui import video_tab as vt
    app = env[0]
    tab = _tab(env, [dict()] * 5)
    it = tab.list.topLevelItem(4)
    assert it.text(vt.COL_MUSIC) == "Tiếp tục"
    labels = [lab for lab, _on, _start in tab.music_choices()]
    assert labels[:2] == ["Tiếp tục playlist", "Không nhạc"] and any(MUSIC[0].stem in lab for lab in labels)
    tab.set_music_choice([4], True, str(MUSIC[0]))
    pump(app)
    c = tab.collect().clips[4]
    assert c.music and c.music_start == str(MUSIC[0])
    assert "1" in it.text(vt.COL_MUSIC) and MUSIC[0].stem[:6] in it.toolTip(vt.COL_MUSIC)
    tab.set_music_choice([0, 1, 2, 3], False, "")
    assert [c.music for c in tab.collect().clips] == [False] * 4 + [True]
    assert tab.list.topLevelItem(0).text(vt.COL_MUSIC) == "Không nhạc"
    tab.undo()
    pump(app)
    assert [c.music for c in tab.collect().clips] == [True] * 5


@need_media
def test_timeline_menu_offers_start_song(env):
    from loopstation.core import timeline
    from loopstation.core.project import MusicTrack, Project
    tab = _tab(env, [dict()] * 3)
    p = Project()
    p.video = tab.collect()
    p.music.tracks = [MusicTrack(path=str(m)) for m in MUSIC[:3]]
    tl = timeline.build(p)
    bar = tab.timeline
    bar.resize(1200, 118)
    bar.set_timeline(tl, [Path(c.path).stem for c in p.video.clips], [Path(t.path).stem for t in p.music.tracks])
    got = []
    bar.musicStartRequested.connect(lambda *a: got.append(a))
    k = next(i for i, b in enumerate(bar.video) if b.clip == 1)
    songs = bar._start_song_choices()
    assert [name for _i, name in songs] == [m.stem for m in MUSIC[:3]]
    bar.musicStartRequested.emit(bar.video[k].clip, 0)
    pump(env[0])
    assert tab.collect().clips[1].music_start == str(MUSIC[0])
