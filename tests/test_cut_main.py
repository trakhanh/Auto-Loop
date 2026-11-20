"""Trang Cắt video trong cửa sổ chính: nút thanh bên dưới Tải video, 2 thẻ trang Bắt đầu mở đúng thẻ, nhãn MỚI,
chữ đếm trên nút, giữ máy thức, encoder, hỏi khi thoát. Offscreen, dữ liệu + cài đặt vào thư mục tạm."""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def win():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_cutmain_")
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
    w._test_mp = mp
    yield w
    w.close()
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def pump(sec=0.2):
    from PySide6.QtWidgets import QApplication
    t = time.time()
    while time.time() - t < sec:
        QApplication.processEvents()
        time.sleep(0.01)


def test_sidebar_button_under_download(win):
    import loopstation.ui.main_window as mw
    assert mw.CUT_PAGE == 7
    sv = win.side.layout()
    order = [sv.itemAt(i).widget() for i in range(sv.count()) if sv.itemAt(i).widget() is not None]
    assert order.index(win.download_btn) + 1 == order.index(win.cut_btn)
    assert order.index(win.cut_btn) < order.index(win.steps_label)
    pump(2.5)  # đợi mở dự án ban đầu xong
    assert win.cut_tool_new is not None and not win.cut_tool_new.isHidden()
    win.cut_btn.click()
    pump()
    assert win.stack.currentIndex() == mw.CUT_PAGE
    assert not win.timeline_wrap.isVisible() and not win.guide.isVisible()
    assert win.page_title.isVisible() and "Cắt video" in win.page_title.text()
    assert not win.name_edit.isVisible()
    assert win.settings.value("new/cut_seen") == "1" and win.cut_tool_new.isHidden()
    win.go_to(6)
    pump()
    assert "Tải video" in win.page_title.text()
    win.go_to(0)


def test_home_cards_open_right_tab(win):
    import loopstation.ui.main_window as mw
    assert not win.home.cards["cut"].property("compact") and not win.home.cards["frames"].property("compact")
    win._home_choice("frames")
    pump()
    assert win.stack.currentIndex() == mw.CUT_PAGE and win.cut_page.tab() == "frames"
    win._home_choice("cut")
    pump()
    assert win.cut_page.tab() == "split"
    win.go_to(0)


def test_counter_label(win):
    win.cut_page.counterChanged.emit("2/3")
    assert "Cắt video (2/3)" in win.cut_btn.text()
    win.cut_page.counterChanged.emit("")
    assert win.cut_btn.text().strip() == "Cắt video"


def test_busy_holds_power(win, monkeypatch):
    import loopstation.ui.main_window as mw
    calls = []
    monkeypatch.setattr(mw.power, "hold", lambda key, on: calls.append((key, on)))
    win.cut_page.busyChanged.emit(True)
    win.cut_page.busyChanged.emit(False)
    assert calls == [("cut", True), ("cut", False)]


def test_encoders_reach_cut_page(win):
    win._on_encoders({"h264": ["nvidia", "cpu"], "hevc": ["cpu"], "audio": []})
    assert win.cut_page._encoder == "h264_nvenc"


def test_help_action_opens_cut(win):
    import loopstation.ui.main_window as mw
    win._help_action("cut")
    pump()
    assert win.stack.currentIndex() == mw.CUT_PAGE
    win.go_to(0)


def test_close_asks_when_cutting(win, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    asked = []
    monkeypatch.setattr(win.cut_page, "is_busy", lambda: True)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No))
    e = QCloseEvent()
    win.closeEvent(e)
    assert not e.isAccepted() and asked and "cắt video" in asked[0].lower()


def test_shutdown_waits_for_cutting(win, monkeypatch):
    monkeypatch.setattr(win.cut_page, "is_busy", lambda: True)
    monkeypatch.setattr(win.download_page, "is_busy", lambda: False)
    ran = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: ran.append(a))
    win._shutdown_countdown(1, 0)
    assert not ran and getattr(win, "_shutdown_waiting", False)
