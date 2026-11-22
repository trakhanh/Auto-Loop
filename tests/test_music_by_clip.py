"""Nhạc theo clip (cột tick "Nhạc": clip bỏ tick thì lúc đó không có nhạc, tới clip có tick thì sang bài kế từ đầu)
và kéo / thả khối bài nhạc trên làn NHẠC của dòng thời gian để đổi thứ tự playlist.

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
need_media = pytest.mark.skipif(len(VIDEO) < 3 or len(MUSIC) < 3, reason="thiếu Mau-Test/")
_KEEP: list = []


# ======================= lên lịch nhạc theo đoạn =======================
def _ms(**kw):
    from loopstation.core.project import MusicSettings, MusicTrack
    ms = MusicSettings(tracks=[MusicTrack(path=f"t{i}.mp3") for i in range(3)])
    ms.crossfade, ms.gap = 0.0, 0.0
    for k, v in kw.items():
        setattr(ms, k, v)
    return ms


def test_one_full_window_is_the_old_plan():
    from loopstation.core import planner
    ms = _ms()
    d = {0: 6.0, 1: 6.0, 2: 6.0}
    assert planner.plan_music_windows(ms, d, [(0.0, 40.0)], 40.0) == planner.plan_music(ms, d, 40.0)


def test_windows_start_next_song_from_the_beginning():
    from loopstation.core import planner
    ms = _ms()
    d = {0: 6.0, 1: 6.0, 2: 6.0}
    items = planner.plan_music_windows(ms, d, [(0.0, 10.0), (20.0, 40.0)], 40.0)
    got = [(it.track, round(it.start, 3), round(it.duration, 3)) for it in items]
    assert got == [(0, 0.0, 6.0), (1, 6.0, 4.0),            # đoạn 1: bài 2 bị cắt ở cuối đoạn
                   (2, 20.0, 6.0), (0, 26.0, 6.0), (1, 32.0, 6.0), (2, 38.0, 2.0)]  # đoạn 2: bài kế, từ đầu


def test_windows_with_crossfade_stay_inside_windows():
    from loopstation.core import planner
    ms = _ms(crossfade=1.0)
    d = {0: 6.0, 1: 6.0, 2: 6.0}
    wins = [(5.0, 15.0), (30.0, 33.0)]
    items = planner.plan_music_windows(ms, d, wins, 40.0)
    assert items
    for it in items:
        assert any(a - 1e-6 <= it.start and it.start + it.duration <= b + 1e-6 for a, b in wins), it
    assert items[0].start == 5.0


def test_no_window_no_music():
    from loopstation.core import planner
    assert planner.plan_music_windows(_ms(), {0: 6.0}, [], 40.0) == []


# ======================= dựng âm thanh có khoảng lặng =======================
def test_music_graph_pads_silence_and_fades_at_window_edges():
    from loopstation.core import audio_build
    from loopstation.core.planner import MusicItem
    ms = _ms()
    items = [MusicItem(0, 2.0, 6.0), MusicItem(1, 8.0, 4.0), MusicItem(2, 20.0, 6.0)]
    g = "".join(audio_build.music_graph(items, {0: "a.mp3", 1: "b.mp3", 2: "c.mp3"}, {}, ms, 30.0))
    assert "aevalsrc" in g  # im lặng trước đoạn đầu và giữa hai đoạn
    assert g.count("afade=t=out") >= 1 and g.count("afade=t=in") >= 1  # bài bị cắt nhỏ dần, đoạn mới to dần


def test_music_graph_unchanged_without_windows():
    """Không dùng cột Nhạc: đồ thị y như trước (bộ nhớ đệm, tốc độ không đổi)."""
    from loopstation.core import audio_build
    from loopstation.core.planner import MusicItem
    ms = _ms(gap=2.0)
    items = [MusicItem(0, 0.0, 6.0), MusicItem(1, 8.0, 6.0)]
    g = "".join(audio_build.music_graph(items, {0: "a.mp3", 1: "b.mp3"}, {}, ms, 14.0))
    # không có khoảng lặng chèn thêm, không fade riêng từng bài (fade đầu / cuối cả file vẫn như cũ)
    assert "aevalsrc" not in g and "curve=tri" not in g and "apad=pad_dur=2.000" in g


@need_media
def test_music_really_silent_between_windows(tmp_path):
    """Xuất thật một đoạn ngắn: khoảng giữa hai đoạn có nhạc phải im lặng."""
    os.environ.setdefault("KTLS_DATA_DIR", str(tmp_path / "data"))
    from loopstation.core import audio_build, ffmpeg_tools as ft
    from loopstation.core.planner import MusicItem
    ms = _ms()
    items = [MusicItem(0, 0.0, 3.0), MusicItem(1, 7.0, 3.0)]
    g = audio_build.music_graph(items, {0: str(MUSIC[0]), 1: str(MUSIC[1])}, {}, ms, 10.0)
    out = tmp_path / "m.wav"
    graph = "".join(g) + "[music]atrim=start=4:end=6[o]"
    ft.Runner().ffmpeg(["-v", "error", "-filter_complex", graph, "-map", "[o]", str(out)])
    import struct
    import wave
    with wave.open(str(out)) as wf:
        raw = wf.readframes(wf.getnframes())
    peak = max(abs(v) for (v,) in struct.iter_unpack("<h", raw[: len(raw) // 2 * 2]))
    assert peak < 50, peak


# ======================= dự án lưu / mở =======================
def test_project_keeps_music_flag(tmp_path):
    from loopstation.core.project import ClipItem, Project
    p = Project()
    p.video.clips = [ClipItem("a.mp4"), ClipItem("b.mp4", music=False)]
    q = Project.from_dict(p.to_dict())
    assert [c.music for c in q.video.clips] == [True, False]


# ======================= timeline: cửa sổ nhạc theo clip =======================
@pytest.fixture(scope="module")
def env():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_musicclip_")
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


def pump(app, sec: float = 0.1) -> None:
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def _proj(music_flags):
    from loopstation.core.project import ClipItem, MusicTrack, Project
    p = Project()
    p.video.clips = [ClipItem(str(v), count=1, music=m) for v, m in zip(VIDEO, music_flags)]
    p.video.length_mode = "manual"
    p.music.tracks = [MusicTrack(path=str(m)) for m in MUSIC[:3]]
    return p


def _clip_spans(tl):
    from fractions import Fraction
    spans, pos = [], 0
    plan = tl.video
    for j, (clip, _r) in enumerate(plan.plays):
        f = plan.ends.get(j, tl.frames[clip])
        spans.append((clip, float(Fraction(pos) / tl.fps), float(Fraction(pos + f) / tl.fps)))
        if j < len(plan.overlaps):
            pos += f - plan.overlaps[j]
    return spans


@need_media
def test_timeline_music_only_on_ticked_clips(env):
    from loopstation.core import timeline
    tl = timeline.build(_proj([False, True, True]))
    assert tl.ok, tl.errors
    spans = _clip_spans(tl)
    first_on = next(a for c, a, _b in spans if c == 1)
    assert tl.music_items and min(it.start for it in tl.music_items) >= first_on - 0.05
    tl2 = timeline.build(_proj([True, False, True]))
    _c, a1, b1 = next(s for s in _clip_spans(tl2) if s[0] == 1)
    for it in tl2.music_items:  # không bài nào phát trong clip 2
        assert it.start + it.duration <= a1 + 0.05 or it.start >= b1 - 0.05, (it, a1, b1)


@need_media
def test_timeline_all_ticked_is_unchanged(env):
    from loopstation.core import planner, timeline
    tl = timeline.build(_proj([True, True, True]))
    assert tl.music_items == planner.plan_music(_proj([True] * 3).music, tl.track_durations, tl.total)


# ======================= bảng clip: cột Nhạc =======================
def _tab(env, flags):
    from loopstation.core.project import ClipItem, VideoSettings
    from loopstation.ui import video_tab as vt
    tab = vt.VideoTab(env[1])
    tab.load(VideoSettings(clips=[ClipItem(str(v), count=1, music=m) for v, m in zip(VIDEO, flags)]))
    tab.resize(1300, 800)
    tab.show()
    _KEEP.append(tab)
    return tab


def _mouse(bar, kind, x, y):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    t = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
         "release": QEvent.Type.MouseButtonRelease}[kind]
    btn = Qt.MouseButton.NoButton if kind == "move" else Qt.MouseButton.LeftButton
    held = Qt.MouseButton.NoButton if kind == "release" else Qt.MouseButton.LeftButton
    pos = QPointF(x, y)
    QApplication.sendEvent(bar, QMouseEvent(t, pos, bar.mapToGlobal(pos), btn, held, Qt.KeyboardModifier.NoModifier))


def _drag(app, bar, x0, x1, y):
    _mouse(bar, "press", x0, y)
    for k in range(1, 9):
        _mouse(bar, "move", x0 + (x1 - x0) * k / 8, y)
        pump(app, 0.01)
    _mouse(bar, "release", x1, y)
    pump(app, 0.05)


def _music_bar(env):
    from loopstation.core import timeline
    from loopstation.ui.timeline_bar import TimelineBar
    p = _proj([True, True, True])
    p.video.length_mode, p.video.target_duration = "target", 900.0  # đủ dài cho 3 bài
    tl = timeline.build(p)
    assert tl.ok and len(tl.music_items) >= 3, tl.errors
    bar = TimelineBar()
    bar.resize(1200, 94)
    bar.set_timeline(tl, [Path(c.path).stem for c in p.video.clips], [Path(t.path).stem for t in p.music.tracks])
    bar.show()
    _KEEP.append(bar)
    return bar


@need_media
def test_drag_first_song_after_third_emits_track_move(env):
    app = env[0]
    bar = _music_bar(env)
    moves = []
    bar.trackMoveRequested.connect(lambda *a: moves.append(a))
    y = bar.TOP_V + bar.LANE_V + 6 + bar.LANE_M / 2
    m0 = bar.music[0]
    m2 = next(b for b in bar.music if b.clip == 2)
    _drag(app, bar, (bar._x(m0.start) + bar._x(m0.end)) / 2, bar._x(m2.end) - 2, y)
    assert moves and moves[0][0] == 0 and moves[0][1] == 2


@need_media
def test_music_drag_blocked_when_shuffled(env):
    app = env[0]
    bar = _music_bar(env)
    bar.music_reorder_block = "Đang phát ngẫu nhiên"
    moves, asked = [], []
    bar.trackMoveRequested.connect(lambda *a: moves.append(a))
    bar.blockedMoveRequested.connect(lambda *a: asked.append(a))
    y = bar.TOP_V + bar.LANE_V + 6 + bar.LANE_M / 2
    m0 = bar.music[0]
    m2 = next(b for b in bar.music if b.clip == 2)
    _drag(app, bar, (bar._x(m0.start) + bar._x(m0.end)) / 2, (bar._x(m2.start) + bar._x(m2.end)) / 2, y)
    assert moves == []  # không tự đổi khi đang ngẫu nhiên…
    assert asked == [("m", 0, 2, True)]  # …mà báo để app hỏi người dùng có chuyển sang theo thứ tự không


@need_media
def test_music_tab_moves_track_row(env):
    from loopstation.core.project import MusicSettings, MusicTrack
    from loopstation.ui.music_tab import MusicTab
    app = env[0]
    mt = MusicTab(env[1])
    _KEEP.append(mt)
    mt.load(MusicSettings(tracks=[MusicTrack(path=str(m)) for m in MUSIC[:3]]))
    pump(app)
    names = lambda: [Path(t.path).name for t in mt.collect().tracks]  # noqa: E731
    before = names()
    mt.move_track_row(0, 2, True)
    assert names() == [before[1], before[2], before[0]]
