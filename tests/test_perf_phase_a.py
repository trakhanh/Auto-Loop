"""Phase A (smoothness): glow update throttling, off-thread probe warm-up with stale-safe recompute,
thumbnail delivery to the right rows, hidden help page not re-rendering."""
import os
import sys
import tempfile
from fractions import Fraction

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="module")
def win():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_perfA_")
    mp.setenv("QT_QPA_PLATFORM", "offscreen")
    mp.setenv("KTLS_DATA_DIR", os.path.join(scratch, "data"))
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from loopstation.ui import theme
    theme.apply(app, 10)
    import loopstation.ui.main_window as mw
    ini = os.path.join(scratch, "s.ini")
    mp.setattr(mw, "QSettings", lambda o, n: QSettings(ini, QSettings.Format.IniFormat))
    QSettings(ini, QSettings.Format.IniFormat).setValue("ui/welcome_done", "1")
    win = mw.MainWindow()
    win.show()
    app.processEvents()
    win._load_initial_project()
    yield win
    win._closing = True
    win.close()
    mp.undo()


def test_glow_skips_unchanged_and_quantizes(win):
    from PySide6.QtWidgets import QPushButton
    from loopstation.ui import effects
    btn = QPushButton("x")
    g = effects.Glow(btn, idle=0.5)
    calls = []
    real = g.fx.setBlurRadius
    g.fx.setBlurRadius = lambda v: (calls.append(v), real(v))
    g.refresh()
    g.refresh()
    assert calls == []  # same visual state: no repaint-triggering update
    g._hover = 0.8
    g.refresh()
    n = len(calls)
    assert n == 1
    g._hover = 0.8001  # sub-step change: invisible, must be ignored
    g.refresh()
    assert len(calls) == n
    g._hover = 1.0
    g.refresh()
    assert len(calls) == n + 1


def test_cold_keys(tmp_path):
    from loopstation.core import probe
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    assert list(probe.cold_keys([str(f), str(tmp_path / "missing.mp4")]).values()) == [str(f)]
    key = probe._key(str(f))
    probe._cache[key] = probe.MediaInfo(path=str(f), duration=1.0, fps=Fraction(30))
    try:
        assert probe.cold_keys([str(f)]) == {}
    finally:
        probe._cache.pop(key, None)


def test_recompute_defers_until_probes_done_and_never_loops(win, monkeypatch, tmp_path):
    import loopstation.ui.main_window as mw
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    key = ("fake", 1, 1)
    runs, warms = [], []
    monkeypatch.setattr(win, "_recompute_core", lambda: runs.append(1))
    monkeypatch.setattr(win._prober, "warm", lambda cold: warms.append(dict(cold)))
    monkeypatch.setattr(mw.probe, "cold_keys", lambda paths: {key: str(f)})
    win._probe_tried.clear()
    win._probe_inflight.clear()

    win.recompute()
    win.recompute()  # second request while the first read is in flight: no duplicate read, no UI-thread work
    assert runs == [] and len(warms) == 1 and key in win._probe_inflight

    win._probes_done(frozenset({key}))  # result arrives (even if the file failed to probe)
    assert runs == [1]
    win.recompute()  # file still not cached (failed probe) but already tried: must not wait again
    assert runs == [1, 1] and len(warms) == 1


def test_stale_result_for_removed_file_is_harmless(win, monkeypatch):
    runs = []
    monkeypatch.setattr(win, "_recompute_core", lambda: runs.append(1))
    monkeypatch.setattr(win, "_cold_media", lambda: {})
    win._probe_inflight = {("gone", 1, 1)}
    win._probes_done(frozenset({("gone", 1, 1)}))  # file no longer in the project: recompute from current state
    assert runs == [1] and not win._probe_inflight


def test_thumb_goes_to_waiting_rows_and_skips_deleted(win):
    from PySide6.QtGui import QColor, QImage
    from loopstation.core.probe import MediaInfo
    from loopstation.core.project import ClipItem
    from loopstation.ui.video_tab import COL_NAME
    vt = win.video_tab
    vt.list.blockSignals(True)
    vt.list.clear()
    c1, c2 = ClipItem(path="C:/nope/a.mp4"), ClipItem(path="C:/nope/b.mp4")
    it1 = vt._make_item(c1, MediaInfo(path=c1.path))
    it2 = vt._make_item(c2, MediaInfo(path=c2.path))
    vt.list.addTopLevelItem(it1)
    vt.list.addTopLevelItem(it2)
    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    vt._on_thumb(c1.path, img)
    assert not it1.icon(COL_NAME).isNull() and it2.icon(COL_NAME).isNull()
    vt.list.clear()  # rows deleted before their thumbnail arrives
    vt._on_thumb(c2.path, img)  # must not raise
    assert c1.path not in vt._thumb_waiting
    vt.list.blockSignals(False)


def test_help_page_hidden_does_not_rerender(win):
    hp = win.help_page
    win.stack.setCurrentIndex(0)
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    assert not hp.isVisible()
    hp._last_w = -1000
    hp._resize_timer.stop()
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    hp.resizeEvent(QResizeEvent(QSize(900, 600), QSize(800, 600)))
    assert not hp._resize_timer.isActive() and hp._stale
