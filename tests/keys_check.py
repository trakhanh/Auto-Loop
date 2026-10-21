"""Kiểm tra phím Space = Phát / Dừng ở mọi chỗ trong cửa sổ (trừ khi đang gõ chữ), Ctrl+Space bật / tắt dòng.
Không hiện cửa sổ, dữ liệu riêng, âm lượng trình phát tắt.

python tests/keys_check.py <thư_mục_tạm>
"""
import os
import sys
import time
import traceback
import warnings

scratch = sys.argv[1]
os.makedirs(scratch, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
os.environ["KTLS_DATA_DIR"] = os.path.join(scratch, "data")
os.environ.setdefault("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
warnings.simplefilter("ignore", DeprecationWarning)
errs = []
sys.excepthook = lambda t, v, tb: errs.append("".join(traceback.format_exception(t, v, tb)))
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
from loopstation.core.project import Project  # noqa: E402
from loopstation.ui import main_window as mw  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.01)
    return bool(cond and cond())


win = mw.MainWindow()
win.resize(1440, 900)
win.show()
wait(1)
win._load_initial_project()
win.load_project(Project.load(os.path.join(ROOT, "Mau-Test", "Du-an-mau - Loop 70 lan.lsproj")))
win.go_to(0)
pl = win.viewer.player
pl.set_muted(True)
check("trình phát nạp xong", wait(40, lambda: pl.state == "paused"), pl.state)
win.activateWindow()
vt = win.video_tab
playing = ("playing", "loading", "buffering")


def space(widget, mods=Qt.KeyboardModifier.NoModifier):
    widget.setFocus()
    wait(0.05)
    QTest.keyClick(widget, Qt.Key.Key_Space, mods)
    wait(0.15)


# 1) đang chọn dòng trong bảng clip
lst = vt.list
lst.clearSelection()
lst.topLevelItem(0).setSelected(True)
lst.setCurrentItem(lst.topLevelItem(0))
before = [lst.topLevelItem(i).checkState(0) for i in range(lst.topLevelItemCount())]
space(lst)
check("bảng clip: Space → phát (không bật / tắt clip)", pl.state in playing
      and [lst.topLevelItem(i).checkState(0) for i in range(lst.topLevelItemCount())] == before, pl.state)
space(lst)
check("bảng clip: Space lần nữa → dừng", wait(2, lambda: pl.state == "paused"), pl.state)

# 2) Ctrl+Space: bật / tắt dòng đang chọn
space(lst, Qt.KeyboardModifier.ControlModifier)
check("bảng clip: Ctrl+Space → tắt dòng đang chọn, trình phát không đổi",
      lst.topLevelItem(0).checkState(0) != before[0] and pl.state == "paused")
space(lst, Qt.KeyboardModifier.ControlModifier)
check("Ctrl+Space lần nữa → bật lại", lst.topLevelItem(0).checkState(0) == before[0])
wait(1.5, lambda: pl.state == "paused")

# 3) ô tick đang được chọn (ví dụ "Thư mục con"): Space không tick, mà phát / dừng
cb = vt.toolbar.recursive
was = cb.isChecked()
space(cb)
check("ô tick: Space → phát, không đổi ô tick", pl.state in playing and cb.isChecked() == was, pl.state)
space(cb)
check("ô tick: Space → dừng", wait(2, lambda: pl.state == "paused"))

# 4) ô số (giờ / phút / giây): Space vẫn là phát / dừng
box = vt.target.h
space(box)
check("ô số giờ: Space → phát", pl.state in playing, pl.state)
space(box)
check("ô số giờ: Space → dừng", wait(2, lambda: pl.state == "paused"))

# 5) đang gõ chữ (ô tìm tên file): Space là dấu cách
search = vt.toolbar.search
search.setText("ab")
search.setCursorPosition(2)
space(search)
check("ô tìm: Space gõ dấu cách, không phát", search.text() == "ab " and pl.state == "paused",
      f"{search.text()!r} · {pl.state}")
search.clear()

# 6) trang Nhạc: playlist + Space
win.go_to(1)
wait(0.5)
ml = win.music_tab.list
if ml.topLevelItemCount():
    ml.clearSelection()
    ml.topLevelItem(0).setSelected(True)
    b0 = ml.topLevelItem(0).checkState(0)
    space(ml)
    check("playlist: Space → phát, không bỏ tick bài", pl.state in playing and ml.topLevelItem(0).checkState(0) == b0,
          pl.state)
    space(ml)
    wait(2, lambda: pl.state == "paused")

# 7) trang Cài đặt (không có trình phát): Space không làm gì trình phát
win.go_to(3)
wait(0.4)
space(win.settings_page)
check("trang Cài đặt: Space không bật trình phát", pl.state == "paused", pl.state)
check("không có lỗi ngầm", not errs, errs[0][-1200:] if errs else "")
print("TẤT CẢ OK" if ok else "CÓ LỖI")
sys.exit(0 if ok else 1)
