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


def _wait_signal(sig, trigger, ms=5000):
    from PySide6.QtCore import QEventLoop, QTimer
    got = []
    loop = QEventLoop()
    sig.connect(lambda *a: (got.append(a), loop.quit()))
    QTimer.singleShot(ms, loop.quit)
    trigger()
    if not got:
        loop.exec()
    return got


def test_prober_real_path_emits_done_even_when_probe_raises(win, monkeypatch, tmp_path):
    from loopstation.core import probe
    seen = []

    def fake(p):
        seen.append(p)
        if p.endswith("bad.mp4"):
            raise RuntimeError("boom")
    monkeypatch.setattr(probe, "probe", fake)
    cold = {("k1", 1, 1): str(tmp_path / "ok.mp4"), ("k2", 1, 1): str(tmp_path / "bad.mp4")}
    got = _wait_signal(win._prober.done, lambda: win._prober.warm(cold))
    assert got and got[0][0] == frozenset(cold) and sorted(seen) == sorted(cold.values())


def test_broken_file_probed_once_then_cached(monkeypatch, tmp_path):
    from loopstation.core import ffmpeg_tools as ft, probe
    f = tmp_path / "broken.mp4"
    f.write_bytes(b"junk")
    calls = []

    class R:
        returncode, stdout, stderr = 1, "", "Invalid data"
    monkeypatch.setattr(ft, "run", lambda *a, **k: calls.append(1) or R())
    monkeypatch.setattr(ft, "ffprobe", lambda: "ffprobe")
    try:
        assert not probe.probe(str(f)).ok and not probe.probe(str(f)).ok
        assert len(calls) == 1 and probe.cold_keys([str(f)]) == {}
    finally:
        probe._cache.pop(probe._key(str(f)), None)


def test_tool_failure_is_not_cached(monkeypatch, tmp_path):
    from loopstation.core import ffmpeg_tools as ft, probe
    f = tmp_path / "x.mp4"
    f.write_bytes(b"junk")

    def boom(*a, **k):
        raise OSError("ffprobe missing")
    monkeypatch.setattr(ft, "run", boom)
    monkeypatch.setattr(ft, "ffprobe", lambda: "ffprobe")
    assert not probe.probe(str(f)).ok
    assert len(probe.cold_keys([str(f)])) == 1  # fixing the tool path later must allow a retry


def test_export_disabled_while_probing_and_watchdog_clears(win, monkeypatch, tmp_path):
    import loopstation.ui.main_window as mw
    key = ("fake2", 1, 1)
    runs = []
    monkeypatch.setattr(win, "_recompute_core", lambda: runs.append(1))
    monkeypatch.setattr(win._prober, "warm", lambda cold: None)  # task never reports back
    monkeypatch.setattr(mw.probe, "cold_keys", lambda paths: {key: "C:/x/y.mp4"})
    win._probe_tried.clear()
    win._probe_inflight.clear()
    win.export_tab.set_can_export(True)
    win.recompute()
    assert not win.export_tab._can_export and win._probe_watchdog.isActive() and runs == []
    win._probes_stuck()  # watchdog fires: flag cleared, recompute runs
    assert not win._probe_inflight and runs == [1] and not win._probe_watchdog.isActive()


def test_failed_thumbnail_cleans_waiting(win):
    from PySide6.QtGui import QImage
    from loopstation.core.probe import MediaInfo
    from loopstation.core.project import ClipItem
    vt = win.video_tab
    c = ClipItem(path="C:/nope/c.mp4")
    vt._make_item(c, MediaInfo(path=c.path))
    assert c.path in vt._thumb_waiting
    vt._on_thumb(c.path, QImage())
    assert c.path not in vt._thumb_waiting


def test_help_page_rerenders_on_show_after_hidden_resize(win, monkeypatch):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    from PySide6.QtWidgets import QApplication
    hp = win.help_page
    win.stack.setCurrentIndex(0)
    QApplication.processEvents()
    hp._last_w = -1000
    hp.resizeEvent(QResizeEvent(QSize(900, 600), QSize(800, 600)))
    assert hp._stale
    renders = []
    monkeypatch.setattr(hp, "_render", lambda keep_pos=False: renders.append(keep_pos))
    win.go_to(4)
    QApplication.processEvents()
    hp._resize_timer.timeout.emit()  # the debounce timer firing (interval 150 ms)
    assert not hp._stale and renders == [True]
