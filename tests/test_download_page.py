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


# ---------- soát cuối (review) ----------
def _add(page, vid):
    from loopstation.core.downloader import Item
    e = page.queue.add_item(Item(f"https://y/{vid}", vid, vid, "YouTube", 1, ""))
    page._add_row(e)
    return e


def test_broken_tool_shows_install_card(env, tmp_path):
    """I3: yt-dlp.exe hỏng / bị chặn → hiện lại thẻ cài, dừng lượt tải (không biến cả hàng thành lỗi)."""
    from PySide6.QtCore import QSettings
    from loopstation.ui.download_page import DownloadPage
    s = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    s.setValue("download/folder", str(tmp_path / "out"))
    p = DownloadPage(s, exe_override=[str(tmp_path / "hong.exe")])
    p.show()
    a, b = _add(p, "t1"), _add(p, "t2")
    p.start()
    assert wait(lambda: not p.is_busy())
    assert a.status == "error" and b.status == "pending"
    assert p.install_card.isVisible() and "Cài lại" in p.install_btn.text()
    p.close()


def test_network_error_pauses_run(page, monkeypatch):
    """I7: mất mạng → tạm dừng lượt tải, video sau vẫn Chờ; "Thử lại các video lỗi" đưa về Chờ."""
    monkeypatch.setenv("FAKE_YTDLP_MODE", "fail_net")
    a, b = _add(page, "n1"), _add(page, "n2")
    page.start()
    assert wait(lambda: not page.is_busy())
    assert a.status == "error" and "Mất kết nối mạng" in a.message and b.status == "pending"
    page.retry_errors()
    assert a.status == "pending" and a.checked


def test_retry_unread_row_reads_again(page, monkeypatch):
    """I4: Thử lại dòng đọc-link-lỗi = đọc lại link (không đem link kênh đi tải)."""
    monkeypatch.setenv("FAKE_YTDLP_MODE", "fail_login")
    read(page, "https://y/q1")
    e = page.queue.entries[0]
    assert e.unread and e.status == "error"
    monkeypatch.setenv("FAKE_YTDLP_MODE", "info")
    page.retry([e])
    assert wait(lambda: not page._reading and len(page.queue.entries) == 1 and not page.queue.entries[0].unread)
    assert page.queue.entries[0].vid == "q1" and page.tree.topLevelItemCount() == 1


def test_group_unknown_count_keeps_show_more(page, monkeypatch):
    """I6: kênh không báo tổng số video → vẫn có dòng "Hiện thêm"."""
    monkeypatch.setenv("FAKE_YTDLP_NOCOUNT", "1")
    read(page, "https://y/list7")
    g = page.tree.topLevelItem(0)
    assert "50+" in g.text(0)
    assert any(g.child(i).text(0).startswith("Hiện thêm") for i in range(g.childCount()))


def test_extra_placeholder_not_risky(page):
    """M3: chữ gợi ý không được là cờ làm hỏng nhận file dở (--no-part)."""
    assert "--no-part" not in page.extra_edit.placeholderText()


def test_page_fits_without_horizontal_scroll(page):
    """Soát ảnh: thanh dưới / khung Tuỳ chỉnh không được đòi rộng hơn vùng trang (cửa sổ 1280, thanh bên 236)."""
    page.opts_btn.setChecked(True)
    page.adapt(960)  # vùng trang ~960 px: không đủ chỗ 2 cột thì cột Cài đặt xuống dưới — không tràn ngang
    pump()
    assert page.minimumSizeHint().width() <= 960


# ---------- 2c: giao diện mới + tuỳ chọn mới ----------
def test_empty_state_then_list(page):
    assert page.list_stack.currentWidget() is page.empty_view
    read(page, "https://y/e9")
    assert page.list_stack.currentWidget() is page.tree


def test_start_button_counts_selected(page):
    read(page, "https://y/b1\nhttps://y/b2")
    assert "Tải 2 video" in page.start_btn.text() and "Đã chọn 2" in page.selected_label.text()
    page.queue.entries[0].checked = False
    page._paint(page.queue.entries[0])
    page._changed()
    assert "Tải 1 video" in page.start_btn.text()


def test_mp3_shows_audio_quality(page):
    page.fmt_box.setCurrentIndex(page.fmt_box.findData("mp3"))
    assert page.audio_box.isVisibleTo(page) and not page.quality_box.isVisibleTo(page)
    page.audio_box.setCurrentIndex(page.audio_box.findData("192"))
    assert page.opts.audio_q == "192" and page.settings.value("download/opt/audio_q") == "192"
    page.fmt_box.setCurrentIndex(page.fmt_box.findData("mp4"))
    assert page.quality_box.isVisibleTo(page) and not page.audio_box.isVisibleTo(page)


def test_desc_txt_written(page):
    page.desc_chk.setChecked(True)
    read(page, "https://y/t1")
    page.start()
    assert wait(lambda: not page.is_busy())
    e = page.queue.entries[0]
    assert e.status == "done" and Path(e.path).with_suffix(".txt").is_file()


def test_open_after_download(page, monkeypatch):
    from loopstation.ui import widgets
    opened = []
    monkeypatch.setattr(widgets, "open_with_default_app", lambda p: opened.append(p))
    page.open_after_chk.setChecked(True)
    read(page, "https://y/o1")
    page.start()
    assert wait(lambda: not page.is_busy())
    assert opened == [page.folder()]


def test_long_videos_unticked_on_read(page, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_LONG", "1")
    page.max_box.setCurrentIndex(page.max_box.findData(60))
    read(page, "https://y/list5")
    es = page.queue.entries
    assert es and all(e.checked == (e.duration <= 3600) for e in es) and not all(e.checked for e in es)


def test_h264_conversion_after_download(page, monkeypatch):
    from loopstation.core import downloader
    conv = []
    monkeypatch.setattr(downloader, "convert_to_h264",
                        lambda path, enc, cancel, prog=None: conv.append((path, enc)) or path)
    monkeypatch.setenv("FAKE_YTDLP_CODEC", "hvc1.1.6.L120")
    read(page, "https://y/v5")
    page.start()
    assert wait(lambda: not page.is_busy())
    e = page.queue.entries[0]
    assert conv and conv[0][0] == e.path and e.status == "done" and e.codec == ""
    page.h264_chk.setChecked(False)
    conv.clear()
    read(page, "https://y/v6")
    page.start()
    assert wait(lambda: not page.is_busy())
    assert not conv and page.queue.entries[-1].codec == "H.265"


def test_side_card_stacks_when_narrow(page):
    from PySide6.QtWidgets import QBoxLayout
    page.adapt(700)
    assert page.body.direction() == QBoxLayout.Direction.TopToBottom
    page.adapt(1300)
    assert page.body.direction() == QBoxLayout.Direction.LeftToRight


def test_side_card_not_clipped(page):
    """Soát ảnh 2c: cột Cài đặt tải không được rộng hơn khung của nó (bị cắt mất nút MP3 / M4A)."""
    page.opts_btn.setChecked(True)
    page.adapt(1300)
    pump()
    assert page.side_card.minimumSizeHint().width() <= page.side_scroll.width() - 2


# ---------- hiệu ứng: đang đọc link / đang tải / xong ----------
def test_spinner_while_reading(page, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_SLOW_INFO", "1.0")
    page.links_edit.setPlainText("https://y/w1\nhttps://y/w2")
    page.read_btn.click()
    assert wait(lambda: page.read_spinner.isVisible(), 3)
    assert "Đang đọc" in page.read_btn.text() and page.list_stack.currentWidget() is page.loading_view
    assert wait(lambda: not page._reading, 10)
    pump(0.1)
    assert not page.read_spinner.isVisible() and page.read_btn.text() == "Đọc link"
    assert page.list_stack.currentWidget() is page.tree


def test_run_bar_and_animation_while_downloading(page, monkeypatch):
    read(page, "https://y/r7")
    assert not page.run_bar.isVisible() and not page._anim.isActive()
    monkeypatch.setenv("FAKE_YTDLP_MODE", "hang")
    page.start()
    assert wait(lambda: page.queue.entries[0].status == "running")
    pump(0.3)
    assert page.run_bar.isVisible() and page._anim.isActive()
    page.stop()
    assert wait(lambda: not page.is_busy(), 6)
    pump(0.5)
    assert not page.run_bar.isVisible() and not page._anim.isActive()


def test_done_row_flashes(page):
    read(page, "https://y/f3")
    page.start()
    assert wait(lambda: not page.is_busy())
    assert page.queue.entries[0].vid in page.flashed


# ---------- 2d: xem trước + cột Cài đặt gọn ----------
def test_paste_auto_reads(page):
    from PySide6.QtCore import QMimeData
    md = QMimeData()
    md.setText("https://y/p1\nhttps://y/p2")
    page.links_edit.insertFromMimeData(md)
    assert wait(lambda: len(page.queue.entries) == 2 and not page._reading)


def test_preview_tooltip(page):
    from loopstation.ui.download_page import preview_html
    read(page, "https://y/q7")
    e = page.queue.entries[0]
    assert e.uploader == "Kênh A" and e.views == 12345
    html = preview_html(e, "C:/x/anh.jpg")
    assert "<img" in html and "Kênh A" in html and "12.345 lượt xem" in html and "20/11/2026" in html
    assert "<img" not in preview_html(e, "")
    assert "Demo q7" in page._row(e).toolTip(0)


def test_double_click_opens_browser(page, monkeypatch):
    import loopstation.ui.download_page as dp
    opened = []
    monkeypatch.setattr(dp.QDesktopServices, "openUrl", staticmethod(lambda u: opened.append(u.toString()) or True))
    read(page, "https://y/d8")
    e = page.queue.entries[0]
    page._on_double(page._row(e), 0)
    assert opened == ["https://y/d8"]


def test_side_controls_not_clipped(page):
    page.opts_btn.setChecked(True)
    page.adapt(1300)
    pump(0.2)
    for seg in (page.fmt_box, page.quality_box):
        for i in range(len(seg._data)):
            b = seg.button(i)
            assert b.width() >= b.minimumSizeHint().width() - 1, b.text()
    assert page.side_card.minimumSizeHint().width() <= page.side_scroll.viewport().width()
    assert page.run_bar.maximumHeight() <= 8


def test_advanced_combos_show_full_text(page):
    """Soát ảnh 2d: ô chọn trong Nâng cao không cắt chữ ("Nền tảng – Tiê…", "Không giới hạ…")."""
    page.opts_btn.setChecked(True)
    page.adapt(1300)
    pump(0.2)
    for cb in (page.subs_box, page.name_box, page.subdir_box, page.conc_box, page.rate_box, page.page_box,
               page.max_box, page.login_box):
        longest = max(cb.fontMetrics().horizontalAdvance(cb.itemText(i)) for i in range(cb.count()))
        assert longest <= cb.width() - 24, (cb.currentText(), longest, cb.width())


# ---------- 2e: Douyin qua trình duyệt trong app ----------
DY = "https://www.douyin.com/video/7445552550692031763"


def _fake_grabber(fail: str = ""):
    from PySide6.QtCore import QObject, QTimer, Signal

    class FakeGrabber(QObject):
        grabbed = Signal(str, dict)
        failed = Signal(str, str)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.calls = []

        def grab(self, link):
            self.calls.append(link)
            from loopstation.core import douyin
            data = douyin.parse_grab({"title": "Bài Douyin - 抖音", "srcs": ["https://v.zjcdn.com/x.mp4"],
                                      "duration": 12, "poster": "", "author": "Kênh D", "ua": "UA"}, link)
            QTimer.singleShot(20, (lambda: self.failed.emit(link, fail)) if fail else
                              (lambda: self.grabbed.emit(link, data)))

        def cancel(self, link):
            pass

        def busy(self):
            return False

        def shutdown(self):
            pass
    return FakeGrabber


def _fake_dy_download(monkeypatch):
    from loopstation.core import douyin, ffmpeg_tools

    def fake(url, out, ua, on_progress, cancel):
        ffmpeg_tools.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
                          "testsrc=size=160x120:rate=25:duration=1", "-f", "lavfi", "-i", "sine=duration=1",
                          "-c:v", "libx264", "-c:a", "aac", "-shortest", str(out)])
        if on_progress:
            on_progress(10, 10)
        return out
    monkeypatch.setattr(douyin, "download", fake)


def test_douyin_read_and_download(page, monkeypatch):
    page.grabber_factory = _fake_grabber()
    _fake_dy_download(monkeypatch)
    read(page, DY)
    e = page.queue.entries[0]
    assert e.platform == "Douyin" and e.title == "Bài Douyin" and e.vid == "7445552550692031763"
    assert e.uploader == "Kênh D" and e.duration == 12
    page.start()
    assert wait(lambda: not page.is_busy(), 20)
    assert e.status == "done" and Path(e.path).name == "Douyin - Bài Douyin [7445552550692031763].mp4"
    assert Path(e.path).is_file()


def test_douyin_mp3(page, monkeypatch):
    page.grabber_factory = _fake_grabber()
    _fake_dy_download(monkeypatch)
    page.fmt_box.setCurrentIndex(page.fmt_box.findData("mp3"))
    read(page, DY)
    page.start()
    assert wait(lambda: not page.is_busy(), 20)
    e = page.queue.entries[0]
    assert e.status == "done" and e.path.endswith(".mp3") and Path(e.path).is_file()
    assert not Path(e.path).with_suffix(".mp4").exists()


def test_douyin_user_page_unsupported(page):
    page.grabber_factory = _fake_grabber()
    read(page, "https://www.douyin.com/user/MS4wLjABAAAA")
    e = page.queue.entries[0]
    assert e.unread and "Kênh Douyin chưa hỗ trợ" in e.message


def test_douyin_grab_fail_row(page):
    page.grabber_factory = _fake_grabber(fail="Không lấy được video Douyin — thử lại")
    read(page, DY)
    e = page.queue.entries[0]
    assert e.unread and e.status == "error" and "Không lấy được video Douyin" in e.message


# ---------- logo nền tảng ----------
def test_platform_logos_on_page(page):
    from loopstation.ui import brand
    assert [c.property("platform") for c in page.platform_chips] == list(brand.SHOWN)
    assert all(c.isVisibleTo(page) for c in page.platform_chips)
    assert len(page.empty_logos) == len(brand.SHOWN)


def test_platform_column_has_logo(page):
    from PySide6.QtWidgets import QStyleOptionViewItem
    from loopstation.ui.download_page import PlatformDelegate
    read(page, "https://y/lg1")
    row = page._row(page.queue.entries[0])
    d = page.tree.itemDelegateForColumn(1)
    assert isinstance(d, PlatformDelegate)
    opt = QStyleOptionViewItem()
    opt.font = page.tree.font()
    idx = page.tree.indexFromItem(row, 1)
    assert d.sizeHint(opt, idx).width() >= page.tree.fontMetrics().horizontalAdvance("YouTube") + 16 + 20


def test_douyin_reuses_read_src(page, monkeypatch):
    """Đọc link đã có link file video còn mới → lúc tải không mở trang Douyin lần nữa (nhanh, ít bị hỏi xác minh)."""
    fg = _fake_grabber()
    made = []
    page.grabber_factory = lambda parent: made.append(fg(parent)) or made[-1]
    _fake_dy_download(monkeypatch)
    read(page, DY)
    page.start()
    assert wait(lambda: not page.is_busy(), 20)
    assert page.queue.entries[0].status == "done" and len(made[0].calls) == 1


def test_douyin_stale_src_regrabs(page, monkeypatch):
    """Link file cũ hết hạn (403) → mở lại trang lấy link mới rồi tải tiếp, không báo lỗi."""
    import urllib.error
    from loopstation.core import douyin
    fg = _fake_grabber()
    made = []
    page.grabber_factory = lambda parent: made.append(fg(parent)) or made[-1]
    _fake_dy_download(monkeypatch)
    real = douyin.download
    n = [0]

    def flaky(url, out, ua, prog, cancel, **k):
        n[0] += 1
        if n[0] == 1:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        return real(url, out, ua, prog, cancel)
    monkeypatch.setattr(douyin, "download", flaky)
    read(page, DY)
    page.start()
    assert wait(lambda: not page.is_busy(), 20)
    assert page.queue.entries[0].status == "done" and len(made[0].calls) == 2


# ---------- Đăng nhập trong app ----------
def test_app_login_choice(page, monkeypatch):
    from loopstation.core import webcookies
    opened = []
    monkeypatch.setattr(page, "open_login", lambda *a, **k: opened.append(1))
    webcookies.cookie_file().unlink(missing_ok=True)
    page.login_box.setCurrentIndex(page.login_box.findData("app"))
    assert opened == [1]  # chưa đăng nhập lần nào: mở cửa sổ đăng nhập ngay
    assert page.login() == ("app", "")
    webcookies.write([{"domain": ".bilibili.com", "name": "SESSDATA", "value": "v"}], webcookies.cookie_file())
    assert page.login() == ("app", str(webcookies.cookie_file()))
    page.login_btn.click()
    assert opened == [1, 1]


def test_login_done_selects_app_and_shows_sites(page):
    page.login_box.setCurrentIndex(page.login_box.findData(""))
    page._on_login_done(["Bilibili", "Instagram"])
    assert page.login_box.currentData() == "app"
    assert "Bilibili" in page.login_status.text() and "Instagram" in page.login_status.text()
    assert page.settings.value("download/app_logins") == "Bilibili, Instagram"
    page._on_login_done([])
    assert "Chưa đăng nhập" in page.login_status.text()
