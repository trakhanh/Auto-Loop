"""Giao diện Sáng / Tối / Theo Windows + đổi màu hoà dần.

- token chế độ sáng đủ và đọc rõ (WCAG ≥ 4.5) với mọi bộ màu;
- QSS chế độ sáng không còn lớp phủ trắng (vô hình trên nền sáng);
- "Theo Windows" đi theo Windows; đổi chế độ không đặt lại style (chậm) và QSS mới thay hẳn QSS cũ;
- icon đã gắn sẵn (nút, nhãn, logo nền tảng) vẽ lại theo chế độ mới;
- motion.crossfade: chạy thay đổi bên dưới một ảnh chụp rồi mờ dần, xong thì dọn sạch;
- Cài đặt → Giao diện lưu lựa chọn theo người dùng; cửa sổ chính đổi màu khi lựa chọn đổi.
Chạy offscreen, dữ liệu + cài đặt vào thư mục tạm."""
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
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("KTLS_DATA_DIR", os.path.join(tempfile.mkdtemp(prefix="ktls_mode_"), "data"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from loopstation.ui import theme  # noqa: E402

TEXT_FG = ("text", "text_2", "text_muted", "accent_text", "accent_soft", "success_text", "warn_text",
           "danger_text", "info_text")


@pytest.fixture(scope="module", autouse=True)
def _fresh_app():
    """Đóng cửa sổ test trước để lại: mỗi lần đổi màu Qt áp QSS cho MỌI widget còn sống (chạy cả bộ test có thể
    tới hàng chục nghìn widget → mỗi lần đổi mất vài chục giây)."""
    from PySide6.QtCore import QCoreApplication, QEvent
    a = QApplication.instance() or QApplication([])
    for wd in QApplication.topLevelWidgets():
        wd.close()
        wd.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    # hẹn giờ một lần (QTimer.singleShot với lambda) của cửa sổ vừa xoá vẫn chạy và gọi vào widget đã xoá:
    # cho chúng chạy hết ở đây (~2,5 s) và bỏ qua lỗi, để không văng vào giữa test của file này
    t = time.time()
    while time.time() - t < 2.5:
        try:
            a.processEvents()
        except Exception:  # noqa: BLE001 - lỗi của widget đã xoá, không thuộc file test này
            pass
        time.sleep(0.02)
    yield


@pytest.fixture
def app():
    a = QApplication.instance() or QApplication([])
    start = (theme.PALETTE, theme.MODE)
    yield a
    theme.apply(a, theme.FONT_PT, start[0], start[1])


def pump(sec: float = 0.1) -> None:
    t = time.time()
    while time.time() - t < sec:
        QApplication.processEvents()
        time.sleep(0.01)


@pytest.mark.parametrize("key", list(theme.PALETTES))
def test_light_tokens_complete_and_readable(key):
    dark, light = theme.build_tokens(key, False), theme.build_tokens(key, True)
    assert set(light) == set(dark)
    for name, val in light.items():
        assert re.fullmatch(r"#[0-9a-f]{6}", val.lower()), (key, name, val)
    assert theme.contrast(light["text_on_accent"], light["accent"]) >= 4.5
    for surface in ("bg", "panel", "raised", "field", "overlay"):
        for fg in TEXT_FG:
            assert theme.contrast(light[fg], light[surface]) >= 4.5, (key, fg, surface)
    assert theme.contrast(light["line_control"], light["panel"]) >= 2.5
    # nền sáng thật sự sáng, chữ đậm; bản tối giữ nguyên như trước
    assert theme._lum(light["bg"]) > 0.8 and theme._lum(light["text"]) < 0.05
    assert dark["text"] == theme._FIXED["text"] and dark["tint"] == "#ffffff"


@pytest.mark.parametrize("key", list(theme.PALETTES))
def test_light_qss_has_no_white_hover_overlay(key):
    theme.set_palette(key, "light")
    try:
        q = theme.qss(10)
        assert "rgba(255,255,255" not in q, "lớp phủ trắng không thấy trên nền sáng"
        assert theme.T["accent"] in q and q.count("{") == q.count("}")
        assert theme.T["bg"] in q and theme.T["text"] in q
    finally:
        theme.set_palette("neon", "dark")


def test_system_mode_follows_windows(monkeypatch):
    monkeypatch.setattr(theme, "system_light", lambda: True)
    theme.set_palette("ocean", "system")
    assert theme.MODE == "system" and theme.LIGHT and theme.T["panel"] == theme.build_tokens("ocean", True)["panel"]
    monkeypatch.setattr(theme, "system_light", lambda: False)
    theme.set_palette("ocean")
    assert theme.MODE == "system" and not theme.LIGHT
    theme.set_palette("neon", "bogus")
    assert theme.MODE == "dark"


def test_apply_swaps_qss_without_resetting_style(app, monkeypatch):
    theme.apply(app, 10, "neon", "dark")
    calls = []
    monkeypatch.setattr(app, "setStyle", lambda *a: calls.append(a))
    theme.apply(app, 10, "neon", "light")
    assert not calls, "đổi màu không được đặt lại style (Qt dựng lại mọi widget, chậm gần 1 giây)"
    assert app.styleSheet() == theme.qss(10) and theme.LIGHT
    assert app.palette().window().color().name() == theme.T["bg"]


def test_mounted_icons_follow_mode(app):
    from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

    from loopstation.ui import brand, icons
    theme.apply(app, 10, "neon", "dark")
    b = QPushButton("x")
    b.setIcon(icons.icon("play", 16, "text_2"))
    lab = QLabel()
    icons.set_label(lab, icons.pixmap("home", 16, "text"))
    logo = QLabel()
    icons.set_label(logo, brand.pixmap("X", 16))
    combo = QComboBox()
    combo.addItem(brand.icon("X", 14), "X")
    before = (b.icon().pixmap(16, 16).toImage(), lab.pixmap().toImage(), logo.pixmap().toImage(),
              combo.itemIcon(0).pixmap(14, 14).toImage())
    theme.apply(app, 10, "neon", "light")
    after = (b.icon().pixmap(16, 16).toImage(), lab.pixmap().toImage(), logo.pixmap().toImage(),
             combo.itemIcon(0).pixmap(14, 14).toImage())
    for i, (x, y) in enumerate(zip(before, after)):
        assert x != y, f"icon #{i} không đổi màu theo chế độ sáng"
    # bật / rê chuột: chữ đậm ở chế độ sáng (trước đây luôn trắng → mất hút trên nền sáng)
    assert theme.T["text_hi"] == theme.T["text"]
    for wd in (b, lab, logo, combo):
        wd.deleteLater()


def test_crossfade_runs_change_under_snapshot_then_cleans_up(app):
    from PySide6.QtWidgets import QMainWindow

    from loopstation.ui import motion
    theme.apply(app, 10, "neon", "dark")
    win = QMainWindow()
    win.resize(500, 300)
    win.show()
    pump(0.1)
    seen = {}

    def change():
        seen["covered"] = motion.fading()
        theme.apply(app, 10, "neon", "light")

    motion.crossfade(change, ms=120)
    assert seen.get("covered") is True, "phải phủ ảnh cũ TRƯỚC khi đổi màu bên dưới"
    assert theme.LIGHT and motion.fading()
    cover = next(c for c in QApplication.topLevelWidgets() if c.objectName() == "themeFade")
    assert cover.geometry().size() == win.size()
    # đổi tiếp khi đang hoà dở: không chồng nhiều lớp phủ
    motion.crossfade(lambda: theme.apply(app, 10, "ocean", "light"), ms=120)
    assert len(motion._covers) == 1
    t = time.time()
    while motion.fading() and time.time() - t < 3:
        pump(0.05)
    assert not motion.fading()
    win.close()
    win.deleteLater()


def test_crossfade_without_windows_just_changes(app):
    from loopstation.ui import motion
    ran = []
    for wd in QApplication.topLevelWidgets():
        if wd.isVisible():
            wd.hide()
    motion.crossfade(lambda: ran.append(1))
    assert ran == [1] and not motion.fading()


@pytest.fixture
def mainwin():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_mode_win_")
    mp.setenv("KTLS_DATA_DIR", os.path.join(scratch, "data"))
    mp.setenv("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
    mp.setenv("KTLS_NO_UPDATE", "1")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox
    app = QApplication.instance() or QApplication([])
    theme.apply(app, 10, "neon", "dark")
    mp.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    mp.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    import loopstation.ui.main_window as mw
    ini = os.path.join(scratch, "s.ini")
    mp.setattr(mw, "QSettings", lambda o, n: QSettings(ini, QSettings.Format.IniFormat))
    QSettings(ini, QSettings.Format.IniFormat).setValue("ui/welcome_done", "1")
    w = mw.MainWindow()
    w.resize(1280, 800)
    w.show()
    pump(0.3)
    yield w, ini
    w.close()
    theme.apply(app, 10, "neon", "dark")
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def test_settings_mode_switch_recolors_window(mainwin, monkeypatch):
    from PySide6.QtCore import QSettings

    from loopstation.ui import motion
    win, ini = mainwin
    sp = win.settings_page
    assert set(sp.mode_buttons) == {"dark", "light", "system"} and sp.mode_buttons["dark"].isChecked()
    used = []
    real = motion.crossfade
    monkeypatch.setattr(motion, "crossfade", lambda fn, *a, **k: (used.append(1), real(fn, *a, **k)))
    sp.set_mode("light")
    pump(0.2)
    assert QSettings(ini, QSettings.Format.IniFormat).value("pref/theme_mode") == "light"
    assert theme.MODE == "light" and theme.LIGHT and used, "đổi chế độ phải hoà màu dần"
    assert app_bg() == theme.T["bg"]
    # Theo Windows: ghi rõ Windows đang để gì; Windows đổi thì app đổi theo
    monkeypatch.setattr(theme, "system_light", lambda: False)
    sp.set_mode("system")
    pump(0.2)
    assert theme.MODE == "system" and not theme.LIGHT
    assert "Tối" in sp.mode_note.text()
    monkeypatch.setattr(theme, "system_light", lambda: True)
    win._on_system_scheme()
    pump(0.2)
    assert theme.LIGHT and "Sáng" in sp.mode_note.text()
    # đổi bộ màu ở chế độ sáng: vẫn sáng, màu nhấn mới
    sp.palette_combo.setCurrentIndex(sp.palette_combo.findData("sunset"))
    pump(0.2)
    assert theme.PALETTE == "sunset" and theme.LIGHT and theme.T["accent"] == theme.PALETTES["sunset"][1]
    sp.set_mode("dark")
    pump(0.2)
    assert not theme.LIGHT
    t = time.time()
    while motion.fading() and time.time() - t < 3:
        pump(0.05)
    assert not motion.fading()


def app_bg() -> str:
    return QApplication.instance().palette().window().color().name()


def test_baked_item_and_label_colours_follow_mode(app):
    """Màu tô sẵn lúc tạo dòng bảng / nhãn chữ (mốc giờ, lưu ý màu vàng…) cũng đổi theo Sáng / Tối."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem
    theme.apply(app, 10, "neon", "dark")
    tree = QTreeWidget()
    tree.setColumnCount(2)
    it = QTreeWidgetItem(["0:00", "Bài 1"])
    it.setForeground(0, QColor(theme.T["info_text"]))
    tree.addTopLevelItem(it)
    lab = QLabel(theme.span("warn", "Lưu ý") + " · " + theme.span("muted", "phụ"))
    theme.apply(app, 10, "neon", "light")
    assert it.foreground(0).color().name() == theme.T["info_text"]
    assert theme.T["warn_text"] in lab.text() and theme.T["text_muted"] in lab.text()
    theme.apply(app, 10, "ocean", "dark")
    assert it.foreground(0).color().name() == theme.T["info_text"] == theme._FIXED["info_text"]
    tree.deleteLater()
    lab.deleteLater()
