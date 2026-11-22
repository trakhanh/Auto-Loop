"""Dòng thời gian không khựng: rê chuột / kéo khối chỉ vẽ lớp trên cùng, phần đứng yên (khối, chữ, thước giờ) vẽ sẵn
một lần và chỉ vẽ lại khi dữ liệu, khung nhìn, cỡ hoặc màu đổi.

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


@pytest.fixture(scope="module")
def app():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_tlperf_")
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


def _bar(app):
    from loopstation.core import timeline
    from loopstation.core.project import ClipItem, MusicTrack, Project
    from loopstation.ui.timeline_bar import TimelineBar
    p = Project()
    p.video.clips = [ClipItem(str(v), count=1) for v in VIDEO[:3]]
    p.video.length_mode, p.video.fill, p.video.target_duration = "target", "repeat_sequence", 1800.0
    p.music.tracks = [MusicTrack(path=str(m)) for m in MUSIC[:3]]
    tl = timeline.build(p)
    assert tl.ok, tl.errors
    bar = TimelineBar()
    bar.resize(1300, 118)
    bar.set_timeline(tl, [Path(c.path).stem for c in p.video.clips], [Path(t.path).stem for t in p.music.tracks])
    bar.show()
    _KEEP.append(bar)
    bar.grab()
    renders = {"n": 0}
    orig = bar._paint_static

    def counted(painter):
        renders["n"] += 1
        return orig(painter)
    bar._paint_static = counted
    return bar, renders, tl, p


def _ev(bar, kind, x, y, held=False):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    t = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
         "release": QEvent.Type.MouseButtonRelease}[kind]
    btn = Qt.MouseButton.NoButton if kind == "move" else Qt.MouseButton.LeftButton
    h = Qt.MouseButton.LeftButton if held and kind != "release" else Qt.MouseButton.NoButton
    pos = QPointF(x, y)
    QApplication.sendEvent(bar, QMouseEvent(t, pos, bar.mapToGlobal(pos), btn, h, Qt.KeyboardModifier.NoModifier))


@need_media
def test_hover_and_drag_reuse_the_static_layer(app):
    bar, renders, _tl, _p = _bar(app)
    y_clip = bar.TOP_V + bar.LANE_V / 2
    y_music = bar.TOP_V + bar.LANE_V + 6 + bar.LANE_M / 2
    for k in range(40):  # rê qua cả hai làn
        _ev(bar, "move", bar.PAD_L + 5 + k * 25, y_music if k % 2 else y_clip)
        bar.grab()
    b = bar.video[len(bar.video) // 3]
    x0 = (bar._x(b.start) + bar._x(b.end)) / 2
    _ev(bar, "press", x0, y_clip, True)
    for k in range(1, 31):  # kéo khối
        _ev(bar, "move", x0 + k * 12, y_clip, True)
        bar.grab()
    assert renders["n"] == 0, "rê / kéo không được vẽ lại hàng trăm khối"
    t = time.perf_counter()
    for _ in range(20):
        bar.grab()
    assert (time.perf_counter() - t) / 20 < 0.006  # mỗi lần vẽ (lớp trên, kể cả chụp ảnh) dưới 6 ms
    _ev(bar, "release", x0 + 360, y_clip)


@need_media
def test_static_layer_redraws_when_something_really_changes(app):
    bar, renders, tl, p = _bar(app)
    bar.set_playhead(tl.total / 3)
    bar.grab()
    assert renders["n"] == 0  # vạch phát chạy (lúc xem trước) cũng chỉ vẽ lớp trên
    bar.set_timeline(tl, [Path(c.path).stem for c in p.video.clips], [Path(t.path).stem for t in p.music.tracks])
    bar.grab()
    assert renders["n"] == 1  # dữ liệu mới
    bar.view0, bar.view1 = 0.0, tl.total / 2
    bar.grab()
    assert renders["n"] == 2  # phóng to / di chuyển khung nhìn
    bar.resize(1100, 118)
    bar.grab()
    assert renders["n"] == 3  # đổi cỡ
    assert bar._hits  # chú thích khi rê chuột vẫn còn (lấy từ lần vẽ sẵn)
