"""Kiểm tra màu chủ đạo, hiệu ứng, chuyển trang và màn hình chào (không hiện cửa sổ, dữ liệu + cài đặt riêng).

python tests/look_check.py <thư_mục_tạm>
"""
import os
import sys
import time
import traceback
import warnings

scratch = sys.argv[1]
os.makedirs(scratch, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["KTLS_DATA_DIR"] = os.path.join(scratch, "data")
sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
warnings.simplefilter("ignore", DeprecationWarning)
errs = []
sys.excepthook = lambda t, v, tb: errs.append("".join(traceback.format_exception(t, v, tb)))

import shiboken6  # noqa: E402
from PySide6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import effects, motion, theme  # noqa: E402
theme.apply(app, 10)
app.installEventFilter(motion.UiMotion(app))  # như app.py: gợn sóng, viền sáng ô đang gõ, cuộn mượt
import loopstation.ui.main_window as mw  # noqa: E402
from loopstation.core.project import Project  # noqa: E402

ini = os.path.join(scratch, "settings.ini")
if os.path.exists(ini):
    os.remove(ini)
mw.QSettings = lambda org, name: QSettings(ini, QSettings.Format.IniFormat)
fails = []


def check(name, ok, info=""):
    print(("OK  " if ok else "FAIL") + f" {name}" + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(name)


def wait(sec=0.3):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


# 1) bộ màu: QSS dựng được cho mọi bộ, không còn sót màu tím của bản cũ
for key in theme.PALETTES:
    theme.set_palette(key)
    q = theme.qss(10)
    if key != "classic":
        check(f"bộ màu {key}: QSS không còn màu tím bản cũ", "#7c5cff" not in q and "124,92,255" not in q)
    check(f"bộ màu {key}: dùng đúng màu chính", theme.PALETTES[key][1] in q)
theme.apply(app, 10, "neon")
check("mặc định: Neon tím hồng", theme.PALETTE == "neon" and theme.T["accent"] == theme.PALETTES["neon"][1])

def looping_anims(widget):
    """Hoạt ảnh đang chạy lặp vô hạn trong widget (hiệu ứng "thở"): thiết kế hiện tại không có cái nào."""
    from PySide6.QtCore import QAbstractAnimation
    return [a for a in widget.findChildren(QAbstractAnimation)
            if a.state() == QAbstractAnimation.State.Running and a.loopCount() != 1]


# 2) màn hình chào lần đầu: chỉ còn 3 bước + Bắt đầu (không còn chọn Đơn giản / Đầy đủ)
win = mw.MainWindow()
win.resize(1440, 900)
win.show()
wait(1.5)
ov = win._welcome
check("màn hình chào tự mở lần đầu", ov is not None and ov.isVisible())
check("màn hình chào không còn chọn giao diện", not hasattr(ov, "options"))
check("nút Bắt đầu: không có hiệu ứng chạy liên tục (đã bỏ quầng sáng)", not looping_anims(ov) and ov.start_btn.graphicsEffect() is None)
was_playing = win.viewer.is_playing()
ov.start_btn.setFocus()
QTest.keyClick(ov.start_btn, Qt.Key.Key_Space)
wait(0.6)
check("Space ở màn hình chào bấm Bắt đầu, không bật trình phát",
      win._welcome is None and win.viewer.is_playing() == was_playing)
check("đã đánh dấu xem màn hình chào", QSettings(ini, QSettings.Format.IniFormat).value("ui/welcome_done") == "1")
check("không còn nút Đơn giản / Đầy đủ", not hasattr(win, "level_box") and not hasattr(win, "set_ui_level"))

# 3) chuyển trang bằng ảnh chụp: chạy xong thì trang thật về đúng chỗ, không còn lớp vẽ tạm
p = Project.load(os.path.join(ROOT, "Mau-Test", "Du-an-mau - Loop 70 lan.lsproj"))
win.load_project(p)
win.go_to(0)
wait(0.6)
win.go_to(2)
check("đang chuyển trang: có lớp ảnh chụp", win.stack._overlay is not None)
wait(0.6)
page = win.stack.currentWidget()
check("chuyển trang xong: trang thật ở đúng chỗ", page.pos() == QPoint(0, 0), str(page.pos()))
check("chuyển trang xong: đã gỡ lớp ảnh chụp", win.stack._overlay is None)
win.go_to(0)
win.go_to(1)  # bấm liền 2 trang: không kẹt
wait(0.6)
check("bấm chuyển liền nhau: trang cuối hiện đúng", win.stack.currentIndex() == 1
      and win.stack.currentWidget().pos() == QPoint(0, 0))
win.resize(1300, 860)
win.go_to(2)
win.resize(1440, 900)  # đổi cỡ giữa chừng
wait(0.5)
check("đổi cỡ giữa lúc chuyển trang: trang hiện đúng chỗ", win.stack.currentWidget().pos() == QPoint(0, 0))

# 4) nút chính: sáng nhẹ + thở khi sẵn sàng xuất, dừng khi đang xuất
et = win.export_tab
wait(0.5)
check("sẵn sàng xuất: nút Bắt đầu phẳng, không hiệu ứng chạy liên tục", not looping_anims(et) and et.start_btn.graphicsEffect() is None)
et.set_running(True)
win.accent_line.set_running(True)
wait(0.2)
check("đang xuất: thanh tiến trình có vệt sáng chạy", et._shimmer.running() and et._shimmer.isVisible())
check("đang xuất: vạch màu dưới thanh trên cùng chạy", win.accent_line.running())
et.set_running(False)
win.accent_line.set_running(False)
wait(0.2)
check("xuất xong: tắt vệt sáng + vạch chạy", not et._shimmer.running() and not win.accent_line.running())
win.go_to(0)
wait(0.6)
win.go_to(2)
wait(0.6)
check("quay lại trang Xuất: vẫn không có hiệu ứng chạy liên tục khi rảnh", not looping_anims(et))

# 5) gợn sóng khi bấm nút; viền sáng ô đang gõ
btn = et.open_out_btn if et.open_out_btn.isEnabled() else win.tl_toggle
QTest.mousePress(btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, btn.rect().center())
ripples = btn.findChildren(effects.Ripple)
QTest.mouseRelease(btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, btn.rect().center())
check("bấm nút → có gợn sóng", len(ripples) == 1)
wait(0.8)
check("gợn sóng tự xoá sau khi chạy", not btn.findChildren(effects.Ripple))
win.activateWindow()
ed = et.filename
ed.setFocus()
wait(0.4)
check("ô đang gõ có viền sáng", isinstance(ed.graphicsEffect(), effects.QGraphicsDropShadowEffect))
et.out_dir.setFocus()
wait(0.5)
check("rời ô: gỡ viền sáng", ed.graphicsEffect() is None)

# 6) đổi màu chủ đạo ở Cài đặt → áp ngay
sp = win.settings_page
sp.palette_combo.setCurrentIndex(sp.palette_combo.findData("ocean"))
wait(0.4)
check("Cài đặt → Đại dương: áp ngay", theme.PALETTE == "ocean" and theme.T["accent"] == theme.PALETTES["ocean"][1])
check("đã lưu màu chủ đạo", QSettings(ini, QSettings.Format.IniFormat).value("pref/palette") == "ocean")
check("QSS toàn app đổi theo", theme.PALETTES["ocean"][1] in app.styleSheet())
win.go_to(0)
wait(0.6)
win.grab()  # vẽ lại mọi phần tự vẽ với màu mới: không lỗi
sp.palette_combo.setCurrentIndex(sp.palette_combo.findData("neon"))
wait(0.3)

# 7) mở lại màn hình chào từ Cài đặt
sp.welcomeRequested.emit()
wait(0.8)
check("Cài đặt → Xem lại màn hình chào", win._welcome is not None and win._welcome.isVisible())
w2 = win._welcome
QTest.keyClick(w2, Qt.Key.Key_Escape)
wait(0.6)
check("Esc đóng màn hình chào", win._welcome is None and (not shiboken6.isValid(w2) or not w2.isVisible()))

win._closing = True
win.close()
wait(0.3)
check("không có lỗi ngầm", not errs, "\n".join(errs))
print("TẤT CẢ OK" if not fails else "CÓ LỖI")
sys.exit(1 if fails else 0)
