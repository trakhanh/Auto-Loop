"""Dòng thời gian kiểu Premiere + chỉnh dải nhạc ngay trên dòng thời gian.

- Ctrl + lăn: zoom quanh con trỏ · lăn / Shift + lăn: trượt ngang · nút −/+ / Vừa khung · thanh cuộn ngang
- Kéo bằng nút giữa chuột hoặc Space + kéo để trượt · vạch phát tự cuộn theo khi đang phát
- Chuột phải khối clip: "Nhạc bắt đầu từ clip này" / "Nhạc dừng ở hết clip này"
- Kéo mép đầu / mép cuối dải nhạc, hít vào ranh giới clip, có nhãn "từ clip 5 · …" / "tới hết clip 7 · …"
- Ô "tới" chỉ liệt kê các clip sau clip bắt đầu
- Trượt ngang không vẽ lại phần đứng yên (dải vẽ sẵn rộng hơn khung nhìn)

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


@pytest.fixture(scope="module")
def app():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_tlpremiere_")
    mp.setenv("QT_QPA_PLATFORM", "offscreen")
    mp.setenv("KTLS_DATA_DIR", os.path.join(scratch, "data"))
    mp.setenv("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
    mp.setenv("KTLS_NO_UPDATE", "1")
    from PySide6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    from loopstation.ui import theme
    theme.apply(a, 10)
    yield a
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def pump(app, sec=0.3):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def _bar(app, n=10):
    from loopstation.core import timeline
    from loopstation.core.project import ClipItem, MusicTrack, Project
    from loopstation.ui.timeline_bar import TimelineBar
    p = Project()
    p.video.clips = [ClipItem(str(VIDEO[k % len(VIDEO)]), count=4) for k in range(n)]
    p.video.length_mode = "manual"
    p.music.tracks = [MusicTrack(path=str(m)) for m in MUSIC[:3]]
    tl = timeline.build(p)
    assert tl.ok, tl.errors
    bar = TimelineBar()
    bar.resize(1200, 118)
    bar.set_timeline(tl, [Path(c.path).stem for c in p.video.clips], [Path(t.path).stem for t in p.music.tracks])
    bar.show()
    _KEEP.append(bar)
    bar.grab()
    return bar


def _wheel(bar, x, dy, mods=None):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    pos = QPointF(x, bar.TOP_V + 10)
    ev = QWheelEvent(pos, bar.mapToGlobal(pos), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                     mods or Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(bar, ev)


def _mouse(bar, kind, x, y, button=None, mods=None):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    t = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
         "release": QEvent.Type.MouseButtonRelease}[kind]
    b = button or Qt.MouseButton.LeftButton
    btn = Qt.MouseButton.NoButton if kind == "move" else b
    held = Qt.MouseButton.NoButton if kind == "release" else b
    pos = QPointF(x, y)
    QApplication.sendEvent(bar, QMouseEvent(t, pos, bar.mapToGlobal(pos), btn, held,
                                            mods or Qt.KeyboardModifier.NoModifier))


def _settle(app, bar):
    pump(app, 0.4)  # hết hiệu ứng zoom / trượt


# ---------------- zoom / trượt ----------------
@need_media
def test_ctrl_wheel_zooms_around_the_cursor(app):
    from PySide6.QtCore import Qt
    bar = _bar(app)
    x = bar.PAD_L + bar._span_px() * 0.6
    t_under = bar._t(x)
    _wheel(bar, x, 240, Qt.KeyboardModifier.ControlModifier)
    _settle(app, bar)
    assert bar.view1 - bar.view0 < bar.total * 0.8
    assert abs(bar._t(x) - t_under) < (bar.view1 - bar.view0) * 0.02


@need_media
def test_plain_wheel_scrolls_sideways_when_zoomed(app):
    bar = _bar(app)
    bar.zoom_in()
    bar.zoom_in()
    _settle(app, bar)
    vs, v0 = bar.view1 - bar.view0, bar.view0
    _wheel(bar, bar.PAD_L + 200, -240)  # lăn xuống = sang phải
    _settle(app, bar)
    assert bar.view0 > v0 and abs((bar.view1 - bar.view0) - vs) < 1e-6


@need_media
def test_zoom_buttons_and_fit(app):
    bar = _bar(app)
    bar.zoom_in()
    _settle(app, bar)
    assert bar.view1 - bar.view0 < bar.total * 0.9
    bar.fit()
    _settle(app, bar)
    assert bar._full_view(bar.total)


@need_media
def test_scrollbar_follows_and_drives_the_view(app):
    bar = _bar(app)
    sb = bar.scrollbar
    assert not sb.isVisibleTo(bar.parentWidget() or bar) or sb.maximum() == 0  # cả video vừa khung: không cần cuộn
    bar.zoom_in()
    bar.zoom_in()
    _settle(app, bar)
    assert sb.maximum() > 0
    sb.setValue(sb.maximum())
    pump(app, 0.1)
    assert abs(bar.view1 - bar.total) < 0.05


@need_media
def test_middle_drag_pans(app):
    from PySide6.QtCore import Qt
    bar = _bar(app)
    bar.zoom_in()
    bar.zoom_in()
    _settle(app, bar)
    bar._set_view(bar.total * 0.3, bar.total * 0.3 + (bar.view1 - bar.view0))
    v0 = bar.view0
    y = bar.TOP_V + bar.LANE_V / 2
    _mouse(bar, "press", 600, y, Qt.MouseButton.MiddleButton)
    _mouse(bar, "move", 450, y, Qt.MouseButton.MiddleButton)
    _mouse(bar, "release", 450, y, Qt.MouseButton.MiddleButton)
    assert bar.view0 > v0  # kéo sang trái = xem phần phía sau


@need_media
def test_playhead_is_followed_while_playing(app):
    bar = _bar(app)
    bar.zoom_in()
    bar.zoom_in()
    _settle(app, bar)
    bar._set_view(0.0, bar.view1 - bar.view0)
    bar.follow_playhead = True
    bar.set_playhead(bar.view1 + 1.0)
    _settle(app, bar)
    assert bar.view0 <= bar.playhead <= bar.view1


@need_media
def test_panning_reuses_the_prerendered_strip(app):
    bar = _bar(app, n=10)
    bar.zoom_in()
    bar.zoom_in()
    _settle(app, bar)
    bar.grab()
    renders = {"n": 0}
    orig = bar._paint_static

    def counted(p):
        renders["n"] += 1
        return orig(p)
    bar._paint_static = counted
    vs = bar.view1 - bar.view0
    start = bar.total * 0.3
    t = time.perf_counter()
    for k in range(20):
        bar._set_view(start + k * vs * 0.02, start + k * vs * 0.02 + vs)
        bar.grab()
    per = (time.perf_counter() - t) / 20
    assert renders["n"] <= 1, "trượt ngang không được vẽ lại toàn bộ mỗi bước"
    assert per < 0.006


# ---------------- dải nhạc ngay trên dòng thời gian ----------------
@need_media
def test_clip_menu_sets_music_start_and_end(app):
    bar = _bar(app)
    bar.use_music = True
    starts, ends = [], []
    bar.musicStartRequested.connect(starts.append)
    bar.musicEndRequested.connect(ends.append)
    k = next(i for i, b in enumerate(bar.video) if b.clip == 4)
    acts = dict(bar._music_menu(k))
    acts["Nhạc bắt đầu từ clip này"]()
    acts["Nhạc dừng ở hết clip này"]()
    assert starts == [5] and ends == [5]


@need_media
def test_drag_music_end_edge_to_clip_seven(app):
    bar = _bar(app)
    ends = []
    bar.musicEndRequested.connect(ends.append)
    hx = bar._end_handle_x()
    assert hx is not None and abs(hx - bar._x(bar.total)) < 1.0
    y = bar._handle_y()
    b7 = [b for b in bar.video if b.clip >= 0][6]
    _mouse(bar, "press", hx - 2, y)
    for k in range(1, 11):
        _mouse(bar, "move", hx - 2 + (bar._x(b7.end) - 3 - hx) * k / 10, y)
    assert "tới hết clip 7" in bar._hd_label()
    _mouse(bar, "release", bar._x(b7.end) - 3, y)
    assert ends == [7]


def test_end_list_only_after_start(app):
    from loopstation.ui.music_range import MusicRangeBar
    bar = MusicRangeBar()
    _KEEP.append(bar)
    bar.set_blocks([(f"Loop{k}", k * 10.0, k * 10.0 + 10) for k in range(1, 11)])
    bar.set_values(5, 0, "")
    ends = [bar.end.itemData(k) for k in range(bar.end.count())]
    assert ends[0] == 0 and min(e for e in ends if e) == 5
    assert bar.start.objectName() == "rangeCombo" and bar.end.objectName() == "rangeCombo"
