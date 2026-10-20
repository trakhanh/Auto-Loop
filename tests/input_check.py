"""Thử gõ phím thật vào các ô nhập (không hiện cửa sổ, dữ liệu riêng): ô thời lượng, ô số, ô trong bảng.

python tests/input_check.py <thư_mục_tạm>
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
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
from loopstation.ui.widgets import WheelGuard  # noqa: E402
guard = WheelGuard(app)
app.installEventFilter(guard)
import loopstation.ui.main_window as mw  # noqa: E402
from loopstation.core.project import Project  # noqa: E402
from loopstation.ui import music_tab as mt  # noqa: E402
from loopstation.ui.video_tab import set_combo  # noqa: E402

ini = os.path.join(scratch, "s.ini")
mw.QSettings = lambda org, name: QSettings(ini, QSettings.Format.IniFormat)
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))


def wait(sec=0.1):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def click(wd):
    QTest.mouseClick(wd, Qt.MouseButton.LeftButton, pos=wd.rect().center())
    wait(0.05)


win = mw.MainWindow()
win.resize(1440, 900)
win.show()
wait(1)
win._load_initial_project()
win.load_project(Project.load(os.path.join(ROOT, "Mau-Test", "Du-an-mau - Loop 70 lan.lsproj")))
win.go_to(0)
vt = win.video_tab
set_combo(vt.length_mode, "target")
vt.right_tabs.setCurrentIndex(0)
wait(0.5)
tg = vt.target
tg.set_seconds(3600)

# 1) bấm vào ô → bôi đen sẵn → gõ 2h → Enter
click(tg)
check("bấm vào ô thời lượng là bôi đen sẵn", tg.selectedText() == tg.text(), repr(tg.selectedText()))
QTest.keyClicks(tg, "2h")
check("đang gõ dở: dự án chưa đổi", win.collect_project().video.target_duration == 3600)
QTest.keyClick(tg, Qt.Key.Key_Return)
wait()
check("gõ “2h” + Enter → 2 giờ", tg.seconds() == 7200 and tg.text() == "02:00:00", tg.text())
check("dự án nhận 2 giờ", win.collect_project().video.target_duration == 7200)

# 2) xoá chữ số ở giữa / cuối rồi gõ tiếp (trước đây bị chặn phím)
click(tg)
QTest.keyClick(tg, Qt.Key.Key_End)
QTest.keyClick(tg, Qt.Key.Key_Backspace)
QTest.keyClick(tg, Qt.Key.Key_Backspace)
check("xoá được chữ số ở cuối", tg.text() == "02:00:", tg.text())
QTest.keyClicks(tg, "30")
QTest.keyClick(tg, Qt.Key.Key_Tab)
wait()
check("gõ tiếp “30” → 2:00:30", tg.seconds() == 7230, tg.text())
click(tg)
QTest.keyClick(tg, Qt.Key.Key_Home)
QTest.keyClick(tg, Qt.Key.Key_Right)
QTest.keyClick(tg, Qt.Key.Key_Backspace)  # bỏ số 0 đầu: "2:00:30" vẫn hợp lệ
QTest.keyClick(tg, Qt.Key.Key_Return)
check("xoá chữ số ở giữa vẫn được", tg.seconds() == 7230, tg.text())

# 3) gõ sai → giữ giá trị cũ
click(tg)
QTest.keyClicks(tg, "abc")
check("gõ sai: viền cam báo ngay", bool(tg.property("bad")))
QTest.keyClick(tg, Qt.Key.Key_Return)
wait()
check("gõ sai + Enter → quay về giá trị cũ", tg.seconds() == 7230 and tg.text() == "02:00:30" and not tg.property("bad"))
wait(0.1)
for txt, sec in (("90p", 5400), ("3 tiếng", 10800), ("1h30", 5400), ("45", 2700)):
    # Enter xong ô vẫn được chọn và đã bôi đen sẵn → gõ tiếp là thay luôn
    check(f"sau Enter đã bôi đen sẵn (trước “{txt}”)", tg.selectedText() == tg.text(), repr(tg.selectedText()))
    if txt.isascii():
        QTest.keyClicks(tg, txt)
    else:  # QTest không gõ được chữ có dấu (sập) → chèn như bộ gõ tiếng Việt, vẫn qua bộ lọc ký tự
        tg.insert(txt)
    QTest.keyClick(tg, Qt.Key.Key_Return)
    wait(0.05)
    check(f"gõ “{txt}”", tg.seconds() == sec, tg.text())

# 4) nút đặt nhanh vẫn chạy
btn = next(b for b in vt.target_wrap.findChildren(type(vt.next_btn)) if b.text() == "10h")
btn.click()
wait()
check("nút đặt nhanh 10h", tg.seconds() == 36000 and win.collect_project().video.target_duration == 36000)

# 5) ô số trong form: bấm vào là bôi đen, gõ đè; gõ "120" chỉ áp dụng 1 lần
vt.right_tabs.setCurrentIndex(1)
wait(0.3)
fo = vt.fade_out
hits = []
fo.valueChanged.connect(lambda v: hits.append(v))
click(fo.lineEdit())
QTest.keyClicks(fo, "12")
check("ô số: chưa Enter thì chưa áp dụng", not hits)
QTest.keyClick(fo, Qt.Key.Key_Return)
check("ô số: gõ đè “12” (không thành “3.012”)", abs(fo.value() - 12) < 1e-6 and hits == [12.0], f"{fo.value()} {hits}")

# 6) ô trong bảng (Âm lượng % của bài nhạc): mở ra là bôi đen sẵn
win.go_to(1)
wait(0.5)
lst = win.music_tab.list
it = lst.items()[0]
lst.setCurrentItem(it, mt.COL_VOL)
lst.editItem(it, mt.COL_VOL)
wait(0.2)
ed = app.focusWidget()
QTest.keyClicks(ed, "60")
QTest.keyClick(ed, Qt.Key.Key_Return)
wait(0.2)
check("ô Âm lượng % trong bảng: gõ đè “60”", it.text(mt.COL_VOL) == "60", it.text(mt.COL_VOL))

# 7) ô "Nghe từ" của Bảng trộn âm
at = win.music_tab.mixer.at
click(at)
QTest.keyClicks(at, "1h")
check("Nghe từ: bấm nghe khi chưa Enter vẫn lấy “1h”", win.music_tab.mixer.start_seconds() == 3600)

# 8) ô Số lần phát (bảng clip) nhận 1h30 và báo khi gõ sai
win.go_to(0)
wait(0.3)
vl = vt.list
row = vl.items()[0]
col = next(c for c in range(vl.columnCount()) if vl.headerItem().text(c) == "Số lần phát")
vl.setCurrentItem(row, col)
vl.editItem(row, col)
wait(0.2)
ed = app.focusWidget()
QTest.keyClicks(ed, "1h30")
QTest.keyClick(ed, Qt.Key.Key_Return)
wait(0.2)
check("Số lần phát: gõ đè “1h30” → 1:30:00", row.text(col) == "1:30:00", row.text(col))

check("không có lỗi ngầm", not errs, errs[0][-500:] if errs else "")
print("TẤT CẢ OK" if ok else "CÓ LỖI")
win._closing = True
win.close()
sys.exit(0 if ok else 1)
