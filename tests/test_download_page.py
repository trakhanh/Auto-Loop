"""Trang Tải video (giao diện, offscreen): cài công cụ, đọc link, tải lần lượt / cùng lúc, Tuỳ chỉnh, dừng, nhớ lựa chọn.
yt-dlp giả: tests/fake_ytdlp.py. Dữ liệu + cài đặt vào thư mục tạm, không gọi mạng."""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAKE = [sys.executable, str(ROOT / "tests" / "fake_ytdlp.py")]


@pytest.fixture(scope="module")
def env():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_dlpage_")
    mp.setenv("QT_QPA_PLATFORM", "offscreen")
    mp.setenv("KTLS_DATA_DIR", os.path.join(scratch, "data"))
    mp.setenv("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
    mp.setenv("KTLS_NO_UPDATE", "1")
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    from loopstation.ui import theme
    theme.apply(app, 10)
    mp.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    mp.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    yield scratch
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def pump(sec=0.2):
    from PySide6.QtWidgets import QApplication
    t = time.time()
    while time.time() - t < sec:
        QApplication.processEvents()
        time.sleep(0.01)


def wait(cond, limit=10.0):
    t = time.time()
    while time.time() - t < limit:
        pump(0.05)
        if cond():
            return True
    return False


@pytest.fixture
def page(env, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from loopstation.core import download_queue, ffmpeg_tools
    from loopstation.ui.download_page import DownloadPage
    (ffmpeg_tools.data_dir() / download_queue.QUEUE_FILE).unlink(missing_ok=True)
    s = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    s.setValue("download/folder", str(tmp_path / "out"))
    monkeypatch.setenv("FAKE_YTDLP_MODE", "ok")
    p = DownloadPage(s, exe_override=FAKE)
    p.resize(1100, 700)
    p.show()
    pump()
    yield p
    p.stop()
    wait(lambda: not p.is_busy(), 6)
    p.close()


def read(p, text):
    p.links_edit.setPlainText(text)
    p.read_btn.click()
    assert wait(lambda: p.read_btn.isEnabled() and not p._reading)


def test_missing_exe_shows_install_card(env, tmp_path):
    from PySide6.QtCore import QSettings
    from loopstation.ui.download_page import DownloadPage
    p = DownloadPage(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    p.show()
    p.shown()
    pump()
    assert p.install_card.isVisible()
    assert not p.read_btn.isEnabled() and not p.start_btn.isEnabled()
    assert p.links_edit.isEnabled()
    p.close()


def test_read_link_adds_rows(page):
    read(page, "https://y/a1\nhttps://y/a2\nhttps://y/a1\nkhông phải link")
    assert len(page.queue.entries) == 2 and page.tree.topLevelItemCount() == 2
    assert "1 dòng" in page.info_label.text()
    read(page, "https://y/a1")
    assert len(page.queue.entries) == 2


def test_group_and_show_more(page):
    read(page, "https://y/list9")
    assert page.tree.topLevelItemCount() == 1
    g = page.tree.topLevelItem(0)
    assert "120" in g.text(0) and len(page.queue.entries) == 50 and all(e.checked for e in page.queue.entries)
    page.show_more(page.queue.groups["https://y/list9"].url)
    assert wait(lambda: len(page.queue.entries) == 100)
    assert sum(e.checked for e in page.queue.entries) == 50


def test_download_flow_marks_done(page):
    seen = []
    page.counterChanged.connect(seen.append)
    read(page, "https://y/d1")
    page.start()
    assert wait(lambda: not page.is_busy())
    e = page.queue.entries[0]
    assert e.status == "done" and Path(e.path).is_file()
    assert "0/1" in seen and seen[-1] == ""


def test_existing_file_marked_exists(page, tmp_path, monkeypatch):
    mark = tmp_path / "mark.txt"
    monkeypatch.setenv("FAKE_YTDLP_MARK", str(mark))
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    (out / "YouTube - Demo [e1].mp4").write_bytes(b"x")
    read(page, "https://y/e1")
    mark.unlink(missing_ok=True)
    page.start()
    assert wait(lambda: not page.is_busy())
    e = page.queue.entries[0]
    assert e.status == "exists" and e.checked is False
    assert not mark.exists()


def test_unwritable_folder_blocks_start(page, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    page.settings.setValue("download/folder", "Q:\\khong-co\\thu-muc")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    read(page, "https://y/u1")
    page.start()
    pump(0.3)
    assert not page.is_busy() and page.queue.entries[0].status == "pending"


def test_quality_and_login_remembered(env, page, tmp_path):
    from loopstation.ui.download_page import DownloadPage
    page.quality_box.setCurrentIndex(page.quality_box.findData("best"))
    page.login_box.setCurrentIndex(page.login_box.findData("firefox"))
    assert page.settings.value("download/opt/quality") == "best"
    assert page.settings.value("download/login") == "firefox"
    p2 = DownloadPage(page.settings, exe_override=FAKE)
    assert p2.quality_box.currentData() == "best" and p2.login_box.currentData() == "firefox"
    p2.close()


def test_stop_returns_pending(page, monkeypatch):
    read(page, "https://y/h1")
    monkeypatch.setenv("FAKE_YTDLP_MODE", "hang")
    page.start()
    assert wait(lambda: page.queue.entries[0].status == "running")
    pump(0.5)
    page.stop()
    assert wait(lambda: not page.is_busy(), 5)
    e = page.queue.entries[0]
    assert e.status == "pending" and e.checked


def test_opts_panel_summary_and_persist(page):
    assert not page.opts_panel.isVisible()
    page.opts_btn.click()
    pump()
    assert page.opts_panel.isVisible() and page.settings.value("download/opts_open") in (True, "true")
    page.fmt_box.setCurrentIndex(page.fmt_box.findData("mp3"))
    assert page.opts.fmt == "mp3" and page.opts_summary.text().startswith("MP3")
    assert not page.quality_box.isEnabled()
    page.reset_opts_btn.click()
    assert page.opts.fmt == "mp4" and page.quality_box.isEnabled()


def test_concurrent_two_runs_two(page, monkeypatch):
    page.conc_box.setCurrentIndex(page.conc_box.findData(2))
    read(page, "https://y/c1\nhttps://y/c2\nhttps://y/c3")
    monkeypatch.setenv("FAKE_YTDLP_MODE", "hang")
    page.start()
    assert wait(lambda: len(page.queue.running()) == 2)
    pump(0.5)
    assert len(page.queue.running()) == 2
    page.stop()
    assert wait(lambda: not page.is_busy(), 6)
    assert all(e.status == "pending" for e in page.queue.entries)


def test_section_sets_entry_section(page):
    read(page, "https://y/s1")
    e = page.queue.entries[0]
    page.set_section(e, "1:00", "2:30")
    assert e.section == "60-150" and "đoạn 1:00–2:30" in page._row(e).text(3)
    page.set_section(e, "", "")
    assert e.section == ""


def test_list_restored_on_open(page):
    from loopstation.ui.download_page import DownloadPage
    read(page, "https://y/r1")
    page.queue.entries[0].status = "done"
    page.save()
    p2 = DownloadPage(page.settings, exe_override=FAKE)
    assert len(p2.queue.entries) == 1 and p2.tree.topLevelItemCount() == 1
    p2.close()
