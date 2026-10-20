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

changes = []
tg.valueChanged.connect(lambda v: changes.append(v))


def type_into(box, text):
    click(box.lineEdit())
    QTest.keyClicks(box, text)


# 1) gõ 10 vào ô giờ → Enter → 10 giờ
type_into(tg.h, "10")
check("bấm vào ô giờ là bôi đen sẵn → gõ đè (không thành “110”)", tg.h.text() == "10", tg.h.text())
check("đang gõ dở: dự án chưa đổi", win.collect_project().video.target_duration == 3600)
QTest.keyClick(tg.h, Qt.Key.Key_Return)
wait()
check("ô giờ “10” + Enter → 10 giờ", tg.seconds() == 36000, tg.text())
check("dự án nhận 10 giờ", win.collect_project().video.target_duration == 36000)

# 2) Tab sang ô phút, gõ 30 → 10:30:00
QTest.keyClick(tg.h, Qt.Key.Key_Tab)
wait(0.05)
check("Tab chuyển sang ô phút", app.focusWidget() in (tg.m, tg.m.lineEdit()), str(app.focusWidget()))
QTest.keyClicks(tg.m, "30")
QTest.keyClick(tg.m, Qt.Key.Key_Return)
wait()
check("ô phút “30” → 10 giờ 30 phút", tg.seconds() == 37800, tg.text())

# 3) gõ dư tự quy đổi: 90 phút → 1 giờ 30 phút
type_into(tg.h, "0")
QTest.keyClick(tg.h, Qt.Key.Key_Return)
type_into(tg.m, "90")
QTest.keyClick(tg.m, Qt.Key.Key_Return)
wait()
check("gõ 0 giờ 90 phút → tự thành 1 giờ 30 phút", tg.seconds() == 5400 and (tg.h.value(), tg.m.value()) == (1, 30),
      f"{tg.h.value()} giờ {tg.m.value()} phút")
type_into(tg.s, "75")
QTest.keyClick(tg.s, Qt.Key.Key_Return)
wait()
check("75 giây → 1 phút 15 giây", (tg.h.value(), tg.m.value(), tg.s.value()) == (1, 31, 15), tg.text())

# 4) toàn 0 → giữ giá trị cũ
before = tg.seconds()
for box in (tg.h, tg.m, tg.s):
    type_into(box, "0")
    QTest.keyClick(box, Qt.Key.Key_Return)
wait()
check("đặt hết về 0 → giữ giá trị cũ (thời lượng phải > 0)", tg.seconds() > 0, tg.text())

# 5) bấm ▲ ở ô giờ → tăng ngay 1 giờ
tg.set_seconds(7200)
tg.h.stepUp()
wait()
check("▲ ô giờ → 3 giờ", tg.seconds() == 10800, tg.text())

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
type_into(at.h, "1")
type_into(at.m, "5")  # chưa Enter (đang ở ô phút)
check("Nghe từ: gõ 1 giờ 5 phút, bấm Nghe khi chưa Enter vẫn lấy đúng", win.music_tab.mixer.start_seconds() == 3900,
      str(win.music_tab.mixer.start_seconds()))

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
