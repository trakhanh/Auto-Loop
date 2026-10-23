"""Rà mọi nút bấm và ô nhập trên các trang + hộp thoại: có bấm / gõ được không (không hiện cửa sổ, dữ liệu riêng).

python tests/clickable_check.py <thư_mục_tạm>

Bắt các lỗi kiểu: ô số có phần gõ chữ bị bóp còn 1 px (Qt 6.12 + NoButtons), nút bị widget khác che, nút /
ô bị ép còn vài điểm ảnh. Chạy được với mọi bản PySide6 (nên chạy cả bằng .venv của run.bat).
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

import PySide6  # noqa: E402
from PySide6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QWidget,
)

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
import loopstation.ui.main_window as mw  # noqa: E402
from loopstation.core.project import Project  # noqa: E402

ini = os.path.join(scratch, "settings.ini")
if os.path.exists(ini):
    os.remove(ini)
_st = QSettings(ini, QSettings.Format.IniFormat)
_st.setValue("ui/welcome_done", "1")
_st.sync()
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


def label(w: QWidget) -> str:
    txt = ""
    for attr in ("text", "placeholderText", "toolTip"):
        try:
            txt = getattr(w, attr)() or txt
        except (AttributeError, TypeError):
            pass
        if txt:
            break
    return f"{type(w).__name__}#{w.objectName() or '-'} “{txt[:40]}”"


def audit(top: QWidget, where: str) -> None:
    """Mọi nút / ô đang hiện trong `top`: đủ lớn, phần gõ chữ đủ rộng, điểm giữa không bị widget khác che."""
    bad = []
    n = 0
    for w in top.findChildren(QWidget):
        if not isinstance(w, (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit)):
            continue
        if not w.isVisible() or w.visibleRegion().isEmpty():
            continue  # đang ẩn / cuộn khuất
        if isinstance(w, QLineEdit) and isinstance(w.parentWidget(), (QAbstractSpinBox, QComboBox)):
            continue  # ô chữ bên trong ô số / ô chọn: kiểm tra cùng ô cha
        n += 1
        if w.width() < 8 or w.height() < 8:
            bad.append(f"quá nhỏ {w.width()}×{w.height()}: {label(w)}")
            continue
        inner = None
        if isinstance(w, QAbstractSpinBox):
            inner = w.findChild(QLineEdit)
        elif isinstance(w, QComboBox) and w.isEditable():
            inner = w.lineEdit()
        if inner is not None and (inner.width() < 12 or inner.height() < 8):
            bad.append(f"phần gõ chữ chỉ còn {inner.width()}×{inner.height()} px: {label(w)}")
        # điểm giữa có bị widget khác che không (chỉ xét điểm nằm trong phần đang thấy)
        c = w.rect().center()
        if not w.visibleRegion().contains(c):
            continue
        win = w.window()
        hit = win.childAt(w.mapTo(win, c))
        ok = hit is not None and (hit is w or w.isAncestorOf(hit))
        if not ok:
            bad.append(f"bị che bởi {label(hit) if hit else 'không có gì'}: {label(w)}")
    check(f"{where}: {n} nút / ô bấm được", not bad, "; ".join(bad[:6]) + (f" … (+{len(bad) - 6})" if len(bad) > 6 else ""))


win = mw.MainWindow()
win.resize(1600, 960)
win.show()
wait(1.5)
win._load_initial_project()
p = Project.load(os.path.join(ROOT, "Mau-Test", "Du-an-mau - Loop 70 lan.lsproj"))
win.load_project(p)
wait(0.8)
print("PySide6", PySide6.__version__)

# màn hình Bắt đầu + 3 bước + Cài đặt + Hướng dẫn; mỗi trang thử thêm cửa sổ hẹp (cài đặt xếp xuống dưới)
pages = {"Bắt đầu": mw.HOME_PAGE, "Video": 0, "Nhạc": 1, "Xuất": 2, "Cài đặt": 3, "Hướng dẫn": 4}
for size in ((1600, 960), (1180, 760)):
    win.resize(*size)
    for name, idx in pages.items():
        win.go_to(idx)
        wait(0.7)
        audit(win, f"{name} {size[0]}×{size[1]}")
win.resize(1600, 960)

# các thẻ phụ trang Video + chế độ độ dài có ô giờ / phút / giây
from loopstation.ui.video_tab import set_combo  # noqa: E402
vt = win.video_tab
win.go_to(0)
set_combo(vt.length_mode, "target")
vt.more_tools.setChecked(True)
for k in range(vt.right_tabs.count()):
    vt.right_tabs.setCurrentIndex(k)
    wait(0.4)
    audit(win, f"Video · thẻ {vt.right_tabs.tabText(k)}")

# ô giờ / phút / giây: bấm vào gõ được (đúng lỗi Qt 6.12)
win.activateWindow()
tg = vt.target
for box, unit in ((tg.h, "giờ"), (tg.m, "phút"), (tg.s, "giây")):
    box.selectAll()
    QTest.mouseClick(box, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, box.rect().center())
    box.lineEdit().selectAll()
    QTest.keyClicks(box.lineEdit(), "12")
    QTest.keyClick(box.lineEdit(), Qt.Key.Key_Return)
    wait(0.1)
check("Dài bao lâu: gõ 12 giờ 12 phút 12 giây", abs(tg.seconds() - (12 * 3600 + 12 * 60 + 12)) < 1, tg.text())
for box in (tg.h, tg.m, tg.s):
    check(f"ô {box.value()}: thấy số (phần gõ chữ {box.lineEdit().width()} px)", box.lineEdit().width() >= 20)

# trang Nhạc kiểu Chỉ nhạc (ô độ dài) + Bảng trộn âm (ô Nghe từ)
win.set_mode("music_only")
win.go_to(1)
wait(0.7)
audit(win, "Nhạc · Chỉ nhạc")
win._scroll_to(win.music_tab.mixer)
wait(0.4)
audit(win, "Nhạc · Bảng trộn âm")
win.set_mode("video_music")

# hộp thoại
from loopstation.ui.batch_dialog import BatchDialog  # noqa: E402
from loopstation.ui.interleave_dialog import InterleaveDialog  # noqa: E402
from loopstation.ui.sequence_dialog import SequenceDialog  # noqa: E402
st = QSettings(ini, QSettings.Format.IniFormat)
st.setValue("batch/folder", os.path.join(ROOT, "Mau-Test", "Hang-loat"))
dialogs = []
bd = BatchDialog(win.collect_project(), st, win)
dialogs.append(("Xuất hàng loạt", bd))
clips = vt.collect().clips
from loopstation.core.probe import probe_many  # noqa: E402
durs = {os.path.normcase(c.path): i.duration for c, i in zip(clips, probe_many([c.path for c in clips])) if i.ok}
dialogs.append(("Xen kẽ clip nền", InterleaveDialog(clips, durs, st, win)))
dialogs.append(("Xếp lần lượt", SequenceDialog(clips, durs, st, win)))
try:
    from loopstation.ui.trim_dialog import TrimDialog
    c0 = clips[0]
    dialogs.append(("Đoạn lấy", TrimDialog(c0.path, durs.get(os.path.normcase(c0.path), 8.0), 0, 0, 1, win)))
except Exception as e:  # noqa: BLE001
    print("bỏ qua hộp thoại Đoạn lấy:", e)
for name, dlg in dialogs:
    dlg.resize(1280, 860)
    dlg.show()
    wait(1.2)
    audit(dlg, f"Hộp thoại {name}")
    if name == "Xuất hàng loạt":
        for k in ("video_only", "music_only"):
            dlg.kind_buttons[k].click()
            wait(0.6)
            audit(dlg, f"Hộp thoại {name} · {k}")
        # màn hình thấp (laptop 768 px / phóng to 125 %): hộp thoại cuộn, không ép dẹt hàng nút 30p / 1h…
        dlg.kind_buttons["video_music"].click()
        dlg.len_mode.setCurrentIndex(dlg.len_mode.findData("target"))
        dlg.resize(1100, 680)
        wait(0.6)
        pills = [b for b in dlg.len_target_wrap.findChildren(QAbstractButton) if b.text() in ("30p", "1h", "10h")]
        check("Xuất hàng loạt cao 680 px: nút 30p / 1h / 10h đủ cao để bấm",
              pills and all(b.height() >= 18 for b in pills), str([b.height() for b in pills]))
        audit(dlg, f"Hộp thoại {name} · cao 680 px")
    dlg.done(0)
    wait(0.3)

win._closing = True
win.close()
wait(0.3)
check("không có lỗi ngầm", not errs, "\n".join(errs))
print("TẤT CẢ OK" if not fails else "CÓ LỖI")
sys.exit(1 if fails else 0)
