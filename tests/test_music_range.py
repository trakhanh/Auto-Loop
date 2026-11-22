"""Nhạc chạy từ clip nào — một dòng: "♪ Nhạc chạy từ clip [N] tới [M / hết] · bài đầu [bài]" + tay nắm ♪ trên dòng
thời gian. "Clip N" = khối thứ N trên làn CLIP (lần phát, kể cả khi bảng lặp cả chuỗi), không phải dòng N của bảng.
Dự án cũ (chỉnh nhạc theo từng clip / Nhạc vào lúc) được quy về một dòng khi mở, có báo nếu phải gộp.

Xem docs/superpowers/specs/2026-11-22-nhac-mot-dong-design.md. Chạy offscreen, dữ liệu + cài đặt vào thư mục tạm."""
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


def _proj(n=5, repeat=False, **music):
    from loopstation.core.project import ClipItem, MusicTrack, Project
    p = Project()
    p.video.clips = [ClipItem(str(VIDEO[k % len(VIDEO)]), count=2) for k in range(n)]
    if repeat:
        p.video.length_mode, p.video.fill, p.video.target_duration = "target", "repeat_sequence", 600.0
    else:
        p.video.length_mode = "manual"
    p.music.tracks = [MusicTrack(path=str(m)) for m in MUSIC[:3]]
    for k, v in music.items():
        setattr(p.music, k, v)
    return p


# ---------------- lõi ----------------
def test_project_keeps_music_range():
    from loopstation.core.project import Project
    p = Project()
    p.music.start_clip, p.music.end_clip, p.music.first_track = 5, 9, "C:/n/bai1.mp3"
    q = Project.from_dict(p.to_dict())
    assert (q.music.start_clip, q.music.end_clip) == (5, 9)
    assert os.path.normcase(os.path.normpath(q.music.first_track)) == os.path.normcase(os.path.normpath("C:/n/bai1.mp3"))


@need_media
def test_numbered_blocks_match_the_clip_lane():
    from loopstation.core import timeline
    tl = timeline.build(_proj())
    blocks = timeline.numbered_blocks(tl)
    assert [b[0] for b in blocks] == [0, 1, 2, 3, 4]  # mỗi dòng phát 2 lần liền = một khối
    assert blocks[0][1] == 0.0 and abs(blocks[-1][2] - tl.total) < 0.05


@need_media
def test_music_starts_at_clip_n():
    from loopstation.core import timeline
    tl = timeline.build(_proj(start_clip=3))
    b3 = timeline.numbered_blocks(tl)[2]
    assert tl.music_items and abs(tl.music_items[0].start - b3[1]) < 0.05
    assert abs(max(it.start + it.duration for it in tl.music_items) - tl.total) < 0.05  # chạy tới hết video


@need_media
def test_repeat_sequence_counts_plays_not_rows():
    """Bảng 5 dòng lặp cả chuỗi: "clip 7" là lần phát thứ 7 (vòng 2), nhạc vào một lần rồi chạy liền tới hết."""
    from loopstation.core import timeline
    tl = timeline.build(_proj(repeat=True, start_clip=7))
    blocks = timeline.numbered_blocks(tl)
    assert len(blocks) > 10
    items = tl.music_items
    assert abs(items[0].start - blocks[6][1]) < 0.05
    for a, b in zip(items, items[1:]):  # không có khoảng lặng giữa chừng
        assert b.start <= a.start + a.duration + 0.05


@need_media
def test_music_ends_after_clip_m_and_first_song():
    from loopstation.core import timeline
    tl = timeline.build(_proj(start_clip=2, end_clip=4, first_track=str(MUSIC[2])))
    blocks = timeline.numbered_blocks(tl)
    items = tl.music_items
    assert items[0].track == 2 and abs(items[0].start - blocks[1][1]) < 0.05
    assert abs(max(it.start + it.duration for it in items) - blocks[3][2]) < 0.05


@need_media
def test_default_range_is_unchanged():
    from loopstation.core import planner, timeline
    p = _proj()
    tl = timeline.build(p)
    assert tl.music_items == planner.plan_music(p.music, tl.track_durations, tl.total)


@need_media
def test_legacy_per_clip_music_converts_to_one_range():
    from loopstation.core import timeline
    p = _proj()
    for k in (0, 1):
        p.video.clips[k].music = False
    p.video.clips[2].music_start = str(MUSIC[1])
    tl = timeline.build(p)
    start, end, first, note = timeline.legacy_music_range(p, tl)
    assert (start, end) == (3, 0) and first == str(MUSIC[1]) and note == ""
    p2 = _proj()
    for k in (0, 2):  # nhạc ngắt quãng: clip 2, rồi clip 4–5
        p2.video.clips[k].music = False
    start, end, first, note = timeline.legacy_music_range(p2, timeline.build(p2))
    assert (start, end) == (2, 0) and "ngắt quãng" in note
    assert timeline.legacy_music_range(_proj(), timeline.build(_proj())) is None  # dự án mới: không đổi gì


# ---------------- giao diện ----------------
@pytest.fixture(scope="module")
def win():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_musicrange_")
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
    import loopstation.ui.main_window as mw
    ini = os.path.join(scratch, "s.ini")
    mp.setattr(mw, "QSettings", lambda o, n: QSettings(ini, QSettings.Format.IniFormat))
    QSettings(ini, QSettings.Format.IniFormat).setValue("ui/welcome_done", "1")
    w = mw.MainWindow()
    w.resize(1440, 900)
    w.show()
    yield w
    w.close()
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def pump(sec=0.3):
    from PySide6.QtWidgets import QApplication
    t = time.time()
    while time.time() - t < sec:
        QApplication.processEvents()
        time.sleep(0.01)


def _load(win, p):
    win.load_project(p)
    win.recompute()
    pump(1.0)
    win.recompute()
    pump(0.5)


@need_media
def test_one_row_controls_the_music(win):
    _load(win, _proj())
    bar = win.music_tab.range_bar
    assert bar.isVisibleTo(win)
    starts = [bar.start.itemText(k) for k in range(bar.start.count())]
    assert starts[0] == "đầu video" and starts[3].startswith("3 · ")
    bar.start.setCurrentIndex(bar.start.findData(3))
    bar.first.setCurrentIndex(bar.first.findData(str(MUSIC[1])))
    pump(0.2)
    ms = win.music_tab.collect()
    assert (ms.start_clip, ms.end_clip, ms.first_track) == (3, 0, str(MUSIC[1]))
    win.recompute()
    pump(0.5)
    tl_bar = win.video_tab.timeline
    b3 = tl_bar.video[2]
    assert tl_bar.music and abs(tl_bar.music[0].start - b3.start) < 0.05


@need_media
def test_old_controls_are_gone(win):
    from loopstation.ui import video_tab as vt
    _load(win, _proj())
    assert win.video_tab.list.isColumnHidden(vt.COL_MUSIC)
    assert not any("Nhạc" in t for _ic, t, _f in win.video_tab.list.menu_extras)
    assert not hasattr(win.music_tab, "clip_music_btn") or not win.music_tab.clip_music_btn.isVisibleTo(win)
    assert not hasattr(win.music_tab, "start_at") or not win.music_tab.start_at.isVisibleTo(win)
    assert not hasattr(win.video_tab.timeline, "_sweep")  # Alt + quét đã bỏ


@need_media
def test_drag_the_music_handle_to_clip_four(win):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    _load(win, _proj())
    bar = win.video_tab.timeline
    hx = bar._handle_x()
    assert hx is not None and abs(hx - bar._x(0.0)) < 1.0  # mặc định: nhạc từ đầu video
    y = bar._handle_y()
    b4 = bar.video[3]

    def ev(kind, x, held=True):
        t = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
             "release": QEvent.Type.MouseButtonRelease}[kind]
        btn = Qt.MouseButton.NoButton if kind == "move" else Qt.MouseButton.LeftButton
        h = Qt.MouseButton.LeftButton if held and kind != "release" else Qt.MouseButton.NoButton
        pos = QPointF(x, y)
        QApplication.sendEvent(bar, QMouseEvent(t, pos, bar.mapToGlobal(pos), btn, h, Qt.KeyboardModifier.NoModifier))
    ev("press", hx)
    for k in range(1, 11):
        ev("move", hx + (bar._x(b4.start) + 3 - hx) * k / 10)
    ev("release", bar._x(b4.start) + 3)
    pump(0.3)
    assert win.music_tab.collect().start_clip == 4


@need_media
def test_opening_an_old_project_converts_and_tells(win):
    notes = []
    orig = win.notify
    win.notify = lambda text, *a, **k: (notes.append(text), orig(text, *a, **k))[1]
    try:
        p = _proj()
        for k in (0, 2):  # nhạc ngắt quãng kiểu cũ
            p.video.clips[k].music = False
        _load(win, p)
    finally:
        win.notify = orig
    ms = win.music_tab.collect()
    assert ms.start_clip == 2 and all(c.music and not c.music_start for c in win.video_tab.collect().clips)
    assert any("ngắt quãng" in n for n in notes)
