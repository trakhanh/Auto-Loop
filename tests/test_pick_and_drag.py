"""Bảng clip không tự tick dòng mới + nút Chọn tất cả, và kéo / thả khối clip trên dòng thời gian để đổi thứ tự.

Chạy không cửa sổ (offscreen), dữ liệu + cài đặt vào thư mục tạm — không đụng dữ liệu thật của app."""
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
need_media = pytest.mark.skipif(len(VIDEO) < 3, reason="thiếu Mau-Test/")
_KEEP: list = []


@pytest.fixture(scope="module")
def env():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_pickdrag_")
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


def pump(app, sec: float = 0.0, cond=None) -> bool:
    t = time.time()
    while True:
        app.processEvents()
        if cond is not None and cond():
            return True
        if time.time() - t >= sec:
            return bool(cond and cond())
        time.sleep(0.01)


def make_tab(env, clips=None, enabled=True):
    from loopstation.core.project import ClipItem, VideoSettings
    from loopstation.ui import video_tab as vt
    _app, settings, _ = env
    tab = vt.VideoTab(settings)
    if clips:
        tab.load(VideoSettings(clips=[ClipItem(str(p), enabled=enabled, count=1) for p in clips]))
    tab.resize(1300, 800)
    tab.show()
    _KEEP.append(tab)
    return tab


def checked(tab) -> list[bool]:
    from PySide6.QtCore import Qt
    return [it.checkState(0) == Qt.CheckState.Checked for it in tab.list.items()]


def names(tab) -> list[str]:
    from loopstation.ui import widgets as w
    return [Path(it.data(0, w.ROLE_DATA).path).name for it in tab.list.items()]


# ---------------- 1. dòng mới không tự tick ----------------
@need_media
def test_added_clips_come_in_unticked(env):
    app = env[0]
    tab = make_tab(env)
    tab.add_paths([str(p) for p in VIDEO[:3]])
    assert pump(app, 20, lambda: tab.list.topLevelItemCount() == 3)
    assert checked(tab) == [False, False, False], "file vừa thêm không được tự tick — người dùng tự chọn"
    assert "Chọn tất cả" in tab.status.full_text()  # nhắc cách chọn


@need_media
def test_duplicate_keeps_tick_state(env):
    tab = make_tab(env, VIDEO[:2], enabled=True)
    tab._duplicate(tab.list.topLevelItem(0))
    assert checked(tab) == [True, True, True]


def test_no_ticked_clip_says_so(env):
    from loopstation.core import timeline
    from loopstation.core.project import ClipItem, Project
    proj = Project()
    proj.video.clips = [ClipItem(str(p), enabled=False) for p in VIDEO[:2]] or [ClipItem("x.mp4", enabled=False)]
    tl = timeline.build(proj)
    assert not tl.ok
    assert "Chưa chọn clip nào" in tl.errors[0]


# ---------------- 2. nút Chọn tất cả ----------------
@need_media
def test_select_all_box_follows_rows_and_toggles(env):
    from PySide6.QtCore import Qt
    app = env[0]
    tab = make_tab(env, VIDEO[:3], enabled=False)
    box = tab.toolbar.check_all
    assert box.isVisible() and box.text()
    pump(app, 0.05)
    assert box.checkState() == Qt.CheckState.Unchecked
    tab.list.topLevelItem(1).setCheckState(0, Qt.CheckState.Checked)
    pump(app, 0.05)
    assert box.checkState() == Qt.CheckState.PartiallyChecked
    box.click()  # chưa đủ → tick tất cả
    pump(app, 0.05)
    assert checked(tab) == [True, True, True]
    assert box.checkState() == Qt.CheckState.Checked
    box.click()  # đủ rồi → bỏ chọn tất cả
    pump(app, 0.05)
    assert checked(tab) == [False, False, False]
    assert box.checkState() == Qt.CheckState.Unchecked
    tab.undo()  # một bấm = một bước Hoàn tác
    pump(app, 0.05)
    assert checked(tab) == [True, True, True]


@need_media
def test_select_all_only_touches_rows_matching_search(env):
    app = env[0]
    tab = make_tab(env, VIDEO[:3], enabled=False)
    first = VIDEO[0].stem.split()[0]  # "01"
    tab.toolbar.search.setText(first)
    pump(app, 0.05)
    tab.toolbar.check_all.click()
    pump(app, 0.05)
    assert checked(tab) == [True, False, False]


# ---------------- 3. kéo / thả khối clip trên dòng thời gian ----------------
def _timeline_for(tab):
    from loopstation.core import timeline
    from loopstation.core.project import Project
    proj = Project()
    proj.output_kind = "video_only"
    proj.video = tab.collect()
    tl = timeline.build(proj)
    assert tl.ok, tl.errors
    bar = tab.timeline
    bar.resize(1000, 94)
    bar.set_timeline(tl, [Path(c.path).stem for c in proj.video.clips], [])
    return bar


def _mouse(bar, kind, x, y, buttons=True):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    t = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
         "release": QEvent.Type.MouseButtonRelease}[kind]
    btn = Qt.MouseButton.NoButton if kind == "move" else Qt.MouseButton.LeftButton
    held = Qt.MouseButton.LeftButton if buttons and kind != "release" else Qt.MouseButton.NoButton
    pos = QPointF(x, y)
    ev = QMouseEvent(t, pos, bar.mapToGlobal(pos), btn, held, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(bar, ev)


def _drag(app, bar, x0, x1):
    y = bar.TOP_V + bar.LANE_V / 2
    _mouse(bar, "press", x0, y)
    for k in range(1, 9):
        _mouse(bar, "move", x0 + (x1 - x0) * k / 8, y)
        pump(app, 0.01)
    _mouse(bar, "release", x1, y)
    pump(app, 0.05)


def _center(bar, clip):
    b = next(b for b in bar.video if b.clip == clip)
    return (bar._x(b.start) + bar._x(b.end)) / 2


@need_media
def test_drag_first_block_to_end_reorders_table_and_undo(env):
    app = env[0]
    tab = make_tab(env, VIDEO[:3])
    before = names(tab)
    bar = _timeline_for(tab)
    moves = []
    bar.clipMoveRequested.connect(lambda *a: moves.append(a))
    end_x = bar._x(bar.video[-1].end) - 2
    _drag(app, bar, _center(bar, 0), end_x)
    assert moves == [(0, 2, True)]
    assert names(tab) == [before[1], before[2], before[0]]
    assert tab.list.topLevelItem(2).isSelected()  # dòng vừa chuyển được chọn để dễ thấy
    tab.undo()
    pump(app, 0.05)
    assert names(tab) == before


@need_media
def test_drag_last_block_to_front(env):
    app = env[0]
    tab = make_tab(env, VIDEO[:3])
    before = names(tab)
    bar = _timeline_for(tab)
    _drag(app, bar, _center(bar, 2), bar._x(0.0) + 2)
    assert names(tab) == [before[2], before[0], before[1]]


@need_media
def test_small_move_is_still_a_click_not_a_drag(env):
    app = env[0]
    tab = make_tab(env, VIDEO[:3])
    before = names(tab)
    bar = _timeline_for(tab)
    x = _center(bar, 0)
    _drag(app, bar, x, x + 2)
    assert names(tab) == before


@need_media
def test_drop_on_own_place_changes_nothing(env):
    app = env[0]
    tab = make_tab(env, VIDEO[:3])
    bar = _timeline_for(tab)
    moves = []
    bar.clipMoveRequested.connect(lambda *a: moves.append(a))
    b = bar.video[1]
    _drag(app, bar, _center(bar, 1), bar._x(b.start) + 3)  # thả ngay mép của chính nó
    assert moves == []


@need_media
def test_shuffle_order_blocks_drag_with_hint(env):
    from loopstation.ui.video_tab import set_combo
    app = env[0]
    tab = make_tab(env, VIDEO[:3])
    set_combo(tab.order, "shuffle")
    pump(app, 0.05)
    assert tab.timeline.reorder_block  # có lời giải thích vì sao không kéo được
    tab.order.setCurrentIndex(tab.order.findData("list"))
    pump(app, 0.05)
    assert not tab.timeline.reorder_block
    set_combo(tab.order, "shuffle")
    pump(app, 0.05)
    bar = _timeline_for(tab)
    moves = []
    bar.clipMoveRequested.connect(lambda *a: moves.append(a))
    _drag(app, bar, _center(bar, bar.video[0].clip), bar._x(bar.video[-1].end) - 2)
    assert moves == []


@need_media
def test_drop_slots_skip_own_edges(env):
    tab = make_tab(env, VIDEO[:3])
    bar = _timeline_for(tab)
    slots = bar._drop_slots(0)
    # kéo khối đầu: chỉ còn 2 chỗ thả có nghĩa (trước khối 3, sau khối 3)
    assert [(s.target, s.after) for s in slots] == [(2, False), (2, True)]
