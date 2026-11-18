"""Gọn giao diện (phản hồi người dùng: rối, nhiều chữ, nhiều chức năng) — bớt chữ lặp, gom nút, không mất tính năng.

Xem docs/superpowers/specs/2026-11-18-gon-giao-dien-design.md. Chạy offscreen, dữ liệu + cài đặt vào thư mục tạm."""
import os
import re
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
need_media = pytest.mark.skipif(len(VIDEO) < 3 or len(MUSIC) < 2, reason="thiếu Mau-Test/")


@pytest.fixture(scope="module")
def win():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_declutter_")
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
    yield w
    w.close()
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def pump(sec: float = 0.2) -> None:
    from PySide6.QtWidgets import QApplication
    t = time.time()
    while time.time() - t < sec:
        QApplication.processEvents()
        time.sleep(0.01)


def load_sample(win):
    from loopstation.core.project import ClipItem, MusicTrack, Project
    p = Project(name="Gọn")
    p.video.clips = [ClipItem(str(v), count=k) for v, k in zip(VIDEO[:3], (70, 1, 70))]
    p.music.tracks = [MusicTrack(path=str(m)) for m in MUSIC[:4]]
    win.load_project(p)
    win.recompute()
    pump(1.0)


def visible_texts(widget, cls_name: str) -> list[str]:
    from PySide6.QtWidgets import QWidget
    return [c.text() for c in widget.findChildren(QWidget)
            if type(c).__name__ == cls_name and c.isVisibleTo(widget) and hasattr(c, "text")]


def plain(html_text: str) -> str:
    return re.sub(r"<[^>]+>", "", html_text)


# ---------- 1. một dòng trạng thái: mẹo vào chú thích ----------
def test_no_tip_lines_under_tables(win):
    from loopstation.ui.widgets import ElidedLabel
    for tab in (win.video_tab, win.music_tab):
        tips = [lb for lb in tab.findChildren(ElidedLabel) if lb.full_text().startswith("Mẹo")]
        assert not tips, "dòng “Mẹo: …” dưới bảng nói lại điều đã có — chuyển vào chú thích"
    assert "Bấm đúp" in win.video_tab.list.toolTip()
    assert "kéo dòng" in win.music_tab.list.toolTip().lower()


# ---------- 2. một nút "Xếp clip ▾" thay cho 3 nút ----------
def test_arrange_buttons_merged_into_one_menu(win):
    vt = win.video_tab
    btn = vt.arrange_btn
    assert btn.isVisibleTo(vt) and "Xếp clip" in btn.text()
    texts = " | ".join(a.text() for a in btn.menu().actions())
    for want in ("Xen kẽ", "Xếp lần lượt", "Thư viện mẫu"):
        assert want in texts
    shown = visible_texts(vt, "QPushButton")
    assert not any(t.startswith(("Xen kẽ nền", "Xếp lần lượt", "Thư viện mẫu")) for t in shown)
    assert vt.interleave_btn is btn  # chỗ khác (ảnh hướng dẫn) vẫn trỏ được tới nút xếp


# ---------- 3. Đặt nhanh: các nút số gộp vào ô nhập ----------
@need_media
def test_quick_plays_presets_live_in_the_input(win):
    load_sample(win)
    vt = win.video_tab
    shown = visible_texts(vt, "QPushButton")
    assert not any(t in ("×1", "×10", "×70", "10p", "1h") for t in shown), shown
    acts = {a.text(): a for a in vt.bulk_presets.actions()}
    assert {"×1", "×10", "×70", "10p", "1h"} <= {t.split()[0] for t in acts}
    vt.list.clearSelection()
    vt.list.topLevelItem(1).setSelected(True)
    next(a for t, a in acts.items() if t.startswith("×10")).trigger()
    pump(0.3)
    assert vt.collect().clips[1].count == 10


# ---------- 4. File xuất kèm: một dòng tóm tắt, bấm để mở ----------
def test_export_extras_fold_into_summary_line(win):
    et = win.export_tab
    boxes = (et.own_folder, et.markers, et.tracklist, et.project_copy)
    et.set_extras_open(False)
    pump(0.3)
    assert not any(b.isVisibleTo(et) for b in boxes)
    et.own_folder.setChecked(True)
    et.tracklist.setChecked(True)
    et.markers.setChecked(False)
    pump(0.1)
    s = et.extras_summary.text()
    assert "thư mục riêng" in s and "tracklist" in s and "mốc thời gian" not in s
    et.set_extras_open(True)
    pump(0.5)
    assert all(b.isVisibleTo(et) for b in boxes)


# ---------- 5. thông báo ngắn ----------
@need_media
def test_music_banner_is_one_short_line(win):
    load_sample(win)
    text = plain(win.music_tab.banner.text())
    assert text and len(text) <= 90, text
    assert win.music_tab.banner.toolTip()  # chi tiết vẫn còn, rê chuột để xem


@need_media
def test_export_footer_does_not_repeat_summary(win):
    load_sample(win)
    et = win.export_tab
    top = plain(et.summary.text())
    foot = et.footer_info.full_text()
    assert foot and len(foot) <= 60, foot
    assert foot != top
