"""Chỉnh nhạc theo clip ngay trong app: kéo mép đoạn nhạc trên làn NHẠC, chuột phải / Alt + quét khối clip, và hộp
"Chọn clip…" ở trang Nhạc (gõ 5-10 hoặc 2-3, 7-8).

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


# ---------------- gõ khoảng clip ----------------
def test_parse_ranges():
    from loopstation.core.clip_ranges import parse_ranges
    on = lambda txt, n=10: [k + 1 for k, v in enumerate(parse_ranges(txt, n)) if v]  # noqa: E731
    assert on("5-10") == [5, 6, 7, 8, 9, 10]
    assert on("2-3, 7-8") == [2, 3, 7, 8]
    assert on("5-") == [5, 6, 7, 8, 9, 10]
    assert on("3 ; 6–7") == [3, 6, 7]  # chấm phẩy, gạch dài cũng được
    assert on("") == []
    assert on("tất cả") == list(range(1, 11))
    assert parse_ranges("abc", 10) is None and parse_ranges("12", 10) is None


def test_ranges_text():
    from loopstation.core.clip_ranges import ranges_text
    assert ranges_text([True] * 10) == "Tất cả clip"
    assert ranges_text([False] * 4 + [True] * 6) == "Clip 5–10"
    assert ranges_text([k in (1, 2, 6, 7) for k in range(10)]) == "Clip 2–3, 7–8"
    assert ranges_text([False] * 3) == "Không clip nào"
    assert ranges_text([False, True, False]) == "Clip 2"


# ---------------- môi trường Qt ----------------
@pytest.fixture(scope="module")
def env():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_musicedit_")
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


def _tab(env, flags):
    from loopstation.core.project import ClipItem, VideoSettings
    from loopstation.ui import video_tab as vt
    tab = vt.VideoTab(env[1])
    tab.load(VideoSettings(clips=[ClipItem(str(v), count=1, music=m) for v, m in zip(VIDEO, flags)]))
    tab.resize(1300, 800)
    tab.show()
    _KEEP.append(tab)
    return tab


def _music(tab):
    return [c.music for c in tab.collect().clips]


def _bar(env, tab):
    """Dòng thời gian của tab (có nhạc) như cửa sổ chính dựng."""
    from loopstation.core import timeline
    from loopstation.core.project import MusicTrack, Project
    p = Project()
    p.video = tab.collect()
    p.music.tracks = [MusicTrack(path=str(m)) for m in MUSIC[:3]]
    tl = timeline.build(p)
    assert tl.ok, tl.errors
    bar = tab.timeline
    bar.resize(1200, 118)
    bar.set_timeline(tl, [Path(c.path).stem for c in p.video.clips], [Path(t.path).stem for t in p.music.tracks])
    return bar


def _mouse(bar, kind, x, y, alt=False):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    t = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
         "release": QEvent.Type.MouseButtonRelease}[kind]
    btn = Qt.MouseButton.NoButton if kind == "move" else Qt.MouseButton.LeftButton
    held = Qt.MouseButton.NoButton if kind == "release" else Qt.MouseButton.LeftButton
    mod = Qt.KeyboardModifier.AltModifier if alt else Qt.KeyboardModifier.NoModifier
    pos = QPointF(x, y)
    QApplication.sendEvent(bar, QMouseEvent(t, pos, bar.mapToGlobal(pos), btn, held, mod))


def _drag(app, bar, x0, x1, y, alt=False):
    _mouse(bar, "press", x0, y, alt)
    for k in range(1, 11):
        _mouse(bar, "move", x0 + (x1 - x0) * k / 10, y, alt)
        pump(app, 0.01)
    _mouse(bar, "release", x1, y, alt)
    pump(app, 0.1)


def _music_y(bar):
    return bar.TOP_V + bar.LANE_V + 6 + bar.LANE_M / 2


def _clip_y(bar):
    return bar.TOP_V + bar.LANE_V / 2


# ---------------- bảng clip: bật / tắt nhạc theo dòng ----------------
# ---------------- kéo mép đoạn nhạc ----------------
# ---------------- chuột phải / Alt + quét trên khối clip ----------------
# ---------------- trang Nhạc: hộp Chọn clip… ----------------
