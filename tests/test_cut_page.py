"""Trang Cắt video (giao diện, offscreen): 2 thẻ, thêm video, cài đặt nhớ, Dự kiến, chạy / Dừng / chạy lại.
Video mẫu tạo bằng FFmpeg; dữ liệu + cài đặt vào thư mục tạm."""
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
def env():
    mp = pytest.MonkeyPatch()
    scratch = Path(tempfile.mkdtemp(prefix="ktls_cutpage_"))
    mp.setenv("QT_QPA_PLATFORM", "offscreen")
    mp.setenv("KTLS_DATA_DIR", str(scratch / "data"))
    mp.setenv("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
    mp.setenv("KTLS_NO_UPDATE", "1")
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    from loopstation.ui import theme
    theme.apply(app, 10)
    mp.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    mp.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    from loopstation.core import ffmpeg_tools
    src = scratch / "src"
    src.mkdir()
    ff = ffmpeg_tools.ffmpeg()
    for name, secs in (("mua.mp4", 6), ("lua.mp4", 4)):
        r = ffmpeg_tools.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i",
                              f"testsrc=size=320x180:rate=25:duration={secs}", "-f", "lavfi", "-i",
                              f"sine=frequency=440:duration={secs}", "-c:v", "libx264", "-g", "25", "-pix_fmt",
                              "yuv420p", "-c:a", "aac", "-shortest", str(src / name)])
        assert r.returncode == 0, r.stderr
    (src / "ghi-chu.txt").write_text("không phải video", encoding="utf-8")
    yield src
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def pump(sec=0.1):
    from PySide6.QtWidgets import QApplication
    t = time.time()
    while time.time() - t < sec:
        QApplication.processEvents()
        time.sleep(0.01)


def wait(cond, limit=20.0):
    t = time.time()
    while time.time() - t < limit:
        pump(0.05)
        if cond():
            return True
    return False


@pytest.fixture
def settings(env, tmp_path):
    from PySide6.QtCore import QSettings
    s = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    s.setValue("cut/folder", str(tmp_path / "out"))
    s.setValue("cut/frames_folder", str(tmp_path / "anh"))
    return s


@pytest.fixture
def page(settings):
    from loopstation.ui.cut_page import CutPage
    p = CutPage(settings)
    p.resize(1200, 800)
    p.show()
    yield p
    if p.is_busy():
        p.stop()
        wait(lambda: not p.is_busy())
    p.close()


def add_ready(page, *paths):
    page.add_files([str(x) for x in paths])
    assert wait(lambda: all(page.tree.topLevelItem(i).text(1) for i in range(page.tree.topLevelItemCount())))


# ---------- Task 4: giao diện, cài đặt, Dự kiến ----------
def test_tabs_switch_and_remember(page, settings):
    page.set_tab("frames")
    assert page.tabs.currentData() == "frames" and page.side_stack.currentIndex() == 1
    assert "ảnh" in page.start_btn.text().lower()
    page.set_tab("split")
    assert "chia" in page.start_btn.text().lower()
    page.set_tab("frames")
    page.save()
    assert settings.value("cut/tab") == "frames"


def test_add_files_and_folder(page, env):
    page.add_files([str(env)])  # thư mục → các video cấp đầu (bỏ file .txt)
    page.add_files([str(env / "mua.mp4")])  # trùng → bỏ qua
    assert sorted(Path(p).name for p in page.files()) == ["lua.mp4", "mua.mp4"]
    assert wait(lambda: page.tree.topLevelItem(0).text(1) and page.tree.topLevelItem(1).text(1))
    texts = {page.tree.topLevelItem(i).text(0): page.tree.topLevelItem(i) for i in range(2)}
    assert texts["mua.mp4"].text(1) == "00:00:06" and texts["mua.mp4"].text(2) == "320×180"


def test_untick_excludes(page, env):
    from PySide6.QtCore import Qt
    add_ready(page, env / "mua.mp4", env / "lua.mp4")
    page.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    assert len(page.files()) == 1


def test_files_remembered(settings, env):
    from loopstation.ui.cut_page import CutPage
    a = CutPage(settings)
    a.add_files([str(env / "mua.mp4")])
    a.save()
    b = CutPage(settings)
    assert [Path(p).name for p in b.files()] == ["mua.mp4"]


def test_estimate_and_invalid_blocks_start(page, env):
    add_ready(page, env / "mua.mp4")
    page.mode_radio["parts"].setChecked(True)
    page.parts_spin.setValue(3)
    assert "3 đoạn" in page.estimate_label.text() and page.start_btn.isEnabled()
    page.mode_radio["marks"].setChecked(True)
    page.marks_edit.setText("00:75:00")
    assert "00:75:00" in page.estimate_label.text() and not page.start_btn.isEnabled()
    page.marks_edit.setText("00:00:02")
    assert "2 đoạn" in page.estimate_label.text() and page.start_btn.isEnabled()


def test_frames_estimate(page, env):
    add_ready(page, env / "mua.mp4")
    page.set_tab("frames")
    page.frame_radio["every_sec"].setChecked(True)
    page.sec_spin.setValue(2.0)
    assert "3 ảnh" in page.frames_estimate.text()


def test_fast_locks_aspect(page):
    page.aspect_box.setCurrentIndex(page.aspect_box.findData("9:16"))
    assert page.fit_box.isEnabled()
    page.exact_box.setCurrentIndex(page.exact_box.findData(False))
    assert not page.aspect_box.isEnabled() and not page.fit_box.isEnabled()
    page.exact_box.setCurrentIndex(page.exact_box.findData(True))
    page.aspect_box.setCurrentIndex(page.aspect_box.findData("keep"))
    assert page.aspect_box.isEnabled() and not page.fit_box.isEnabled()


def test_settings_persist(settings):
    from loopstation.ui.cut_page import CutPage
    a = CutPage(settings)
    a.mode_radio["random"].setChecked(True)
    a.rmin_edit.setText("00:00:15")
    a.rmax_edit.setText("00:01:00")
    a.aspect_box.setCurrentIndex(a.aspect_box.findData("1:1"))
    a.fit_box.setCurrentIndex(a.fit_box.findData("crop"))
    a.frame_radio["scene"].setChecked(True)
    a.scene_spin.setValue(25)
    a.save()
    b = CutPage(settings)
    assert b.split.mode == "random" and b.split.rmin == 15 and b.split.rmax == 60
    assert b.split.aspect == "1:1" and b.split.fit == "crop" and b.mode_radio["random"].isChecked()
    assert b.frames.mode == "scene" and b.frames.scene == 25 and b.rmin_edit.text() == "00:00:15"


def test_empty_list_cannot_start(page):
    assert not page.start_btn.isEnabled()
