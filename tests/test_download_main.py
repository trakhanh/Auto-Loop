"""Trang Tải video trong cửa sổ chính: thanh bên, thẻ Bắt đầu, giữ máy thức, hỏi tải tiếp, tắt máy chờ tải xong,
Cài đặt (công cụ tải), Hướng dẫn. Offscreen, dữ liệu + cài đặt vào thư mục tạm."""
import os
import shutil
import subprocess
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
    scratch = tempfile.mkdtemp(prefix="ktls_dlmain_")
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


def test_sidebar_and_home_card_open_page(win):
    import loopstation.ui.main_window as mw
    assert mw.DOWNLOAD_PAGE == 6
    pump(2.5)  # đợi mở dự án ban đầu (dự án trống → trang Bắt đầu) xong
    win.download_btn.click()
    pump()
    assert win.stack.currentIndex() == 6
    assert not win.timeline_wrap.isVisible() and not win.guide.isVisible()
    win.go_to(0)
    win._home_choice("download")
    pump()
    assert win.stack.currentIndex() == 6
    assert "download" in win.home.cards
    win.go_to(0)


def test_counter_in_sidebar_text(win):
    win.download_page.counterChanged.emit("2/10")
    assert "Tải video (2/10)" in win.download_btn.text()
    win.download_page.counterChanged.emit("")
    assert win.download_btn.text().strip() == "Tải video"


def test_busy_holds_power(win, monkeypatch):
    from loopstation.core import power
    monkeypatch.setattr(power, "keep_awake", lambda on: True)
    win.download_page.busyChanged.emit(True)
    assert "download" in power.holders()
    assert win.settings.value("download/was_running") == "running"
    win.download_page.busyChanged.emit(False)
    assert "download" not in power.holders() and not win.settings.value("download/was_running")


def test_resume_prompt_after_crash(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from loopstation.core.downloader import Item
    page = win.download_page
    page.queue.add_item(Item("https://y/z1", "z1", "Z", "YouTube", 1, ""))
    win.settings.setValue("download/was_running", "running")
    asked, started = [], []
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(page, "start", lambda: started.append(1))
    win._dl_resume_asked = False  # lần hỏi tự động lúc mở cửa sổ (hẹn giờ) có thể đã chạy trước test này
    win._maybe_resume_downloads()
    assert started == [1] and "1 video" in asked[0]
    assert not win.settings.value("download/was_running")
    win._maybe_resume_downloads()  # đã hỏi rồi: không hỏi lại
    assert started == [1]
    page.clear_list()


def test_shutdown_waits_for_downloads(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    calls = []
    real_run = subprocess.run

    def fake_run(args, **k):  # chỉ chặn lệnh tắt máy; lệnh khác (ffmpeg chạy nền) vẫn chạy thật
        if list(args)[:1] == ["shutdown"]:
            calls.append(list(args))
            return None
        return real_run(args, **k)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    page = win.download_page
    win.settings_page.shutdown.setChecked(True)
    monkeypatch.setattr(page, "is_busy", lambda: True)
    win._shutdown_countdown(1, 0)
    assert calls == []
    monkeypatch.setattr(page, "is_busy", lambda: False)
    page.busyChanged.emit(False)
    pump()
    assert calls and calls[0][0] == "shutdown"
    page.busyChanged.emit(False)  # chỉ chờ một lần
    assert len([c for c in calls if c[:2] == ["shutdown", "/s"]]) == 1
    win.settings_page.shutdown.setChecked(False)


def test_settings_tool_row(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from loopstation.core import dl_tools
    sp = win.settings_page
    sp.refresh_dl_tools()
    assert "Chưa cài" in sp.dl_tools_label.text()
    dl_tools.ytdlp_path().write_bytes(b"x")
    dl_tools.deno_path().write_bytes(b"x")
    dl_tools._write_versions({"yt-dlp": "2026.11.19", "deno": "2.5.6"})
    sp.refresh_dl_tools()
    assert "yt-dlp 2026.11.19" in sp.dl_tools_label.text() and sp.dl_remove_btn.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    sp.dl_remove_btn.click()
    pump()
    assert not dl_tools.installed() and "Chưa cài" in sp.dl_tools_label.text()


def test_help_topic_present():
    from loopstation.ui import help_page
    t = {x[0]: x for x in help_page.TOPICS}
    assert "taivideo" in t and "bản quyền" in t["taivideo"][4] and "cookies.txt" in t["taivideo"][4]


def test_help_topic_group_listed():
    """Soát cuối (help_check): nhóm của chủ đề Tải video phải có trong danh sách nhóm của trang Hướng dẫn."""
    from loopstation.ui import help_page
    assert {t[1] for t in help_page.TOPICS} <= set(help_page.GROUPS)


def test_download_is_prominent(win):
    """2c: Tải video là mục riêng ngay dưới Bắt đầu (không lẫn trong Công cụ); thẻ lớn riêng ở trang Bắt đầu."""
    sv = win.side.layout()
    order = [sv.itemAt(i).widget() for i in range(sv.count()) if sv.itemAt(i).widget() is not None]
    i_home = next(i for i, x in enumerate(order) if x is win.nav.button(5))
    assert order.index(win.download_btn) < order.index(win.steps_label)
    assert order.index(win.download_btn) > i_home
    assert not win.home.cards["download"].property("compact")


def test_header_shows_page_title_on_download(win):
    win.go_to(6)
    pump()
    assert win.page_title.isVisible() and "Tải video" in win.page_title.text()
    assert not win.name_edit.isVisible() and not win.mode_box.isVisible() and not win.profile_btn.isVisible()
    win.go_to(0)
    pump()
    assert not win.page_title.isVisible() and win.name_edit.isVisible() and win.mode_box.isVisible()


def test_encoders_reach_download_page(win):
    win._on_encoders({"h264": ["nvidia", "cpu"], "hevc": ["cpu"], "audio": []})
    assert win.download_page._h264_enc == "h264_nvenc"
