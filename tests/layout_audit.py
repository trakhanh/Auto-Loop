"""Rà chữ bị cắt / che ở mọi trang, nhiều cỡ cửa sổ: nút, ô tick, nhãn không xuống dòng mà chữ dài hơn chỗ chứa.
Kèm kiểm tra lăn chuột: ô số / dropdown / thanh trượt không đổi giá trị khi lăn qua (chỉ cuộn trang).

python tests/layout_audit.py <thư_mục_tạm>      (ảnh từng trang × cỡ cửa sổ lưu vào thư mục đó)
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
sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
warnings.simplefilter("ignore", DeprecationWarning)
errs = []
sys.excepthook = lambda t, v, tb: errs.append("".join(traceback.format_exception(t, v, tb)))

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton, QAbstractSlider, QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QLabel, QPushButton,
    QRadioButton,
)

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
import loopstation.ui.main_window as mw  # noqa: E402
from loopstation.core.project import Project  # noqa: E402
from loopstation.ui import widgets as w  # noqa: E402

guard = w.WheelGuard(app)
app.installEventFilter(guard)
mw.MainWindow._confirm_sample_bookends = lambda self: True
ini = os.path.join(scratch, "settings.ini")
_st = QSettings(ini, QSettings.Format.IniFormat)
_st.clear()
_st.setValue("ui/welcome_done", "1")
_st.sync()
mw.QSettings = lambda org, name: QSettings(ini, QSettings.Format.IniFormat)
fails = []


def check(name, ok, extra=""):
    print(("OK   " if ok else "LỖI ") + name + (f"  ({extra})" if extra and not ok else ""))
    if not ok:
        fails.append(name)


def pump(t=0.3):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()


def visible_in_window(wd) -> bool:
    if not wd.isVisible() or wd.width() <= 4 or wd.height() <= 4:
        return False
    p = wd.parentWidget()
    while p is not None:  # nằm trong vùng cuộn mà đang bị cuộn khuất: không tính
        if not p.isVisible():
            return False
        p = p.parentWidget()
    return True


def cut_by_parent(wd) -> str:
    """Widget thò ra ngoài phần nhìn thấy của khung chứa (cột / vùng cuộn không cuộn ngang) → bị cắt mất một phần."""
    from PySide6.QtWidgets import QAbstractScrollArea
    g = wd.mapToGlobal(wd.rect().topLeft()).x(), wd.mapToGlobal(wd.rect().topRight()).x()
    p = wd.parentWidget()
    while p is not None and not p.isWindow():
        area = p.parentWidget()
        if isinstance(area, QAbstractScrollArea) and p is area.viewport():
            if area.horizontalScrollBar().isVisible():
                return ""  # cuộn ngang được: không tính là bị cắt
            right = p.mapToGlobal(p.rect().topRight()).x()
            if g[1] > right + 2 and g[0] < right:
                return f"thò {g[1] - right}px ra ngoài {type(area).__name__}"
        p = p.parentWidget()
    return ""


def clipped(root) -> list[str]:
    out = []
    from PySide6.QtWidgets import QAbstractSpinBox as _S, QComboBox as _C
    for wd in root.findChildren(QAbstractButton) + root.findChildren(QLabel) + root.findChildren(_S) +             root.findChildren(_C):
        if not visible_in_window(wd):
            continue
        why = cut_by_parent(wd)
        if why:
            txt = wd.text() if hasattr(wd, "text") and isinstance(wd.text(), str) else                 (wd.currentText() if isinstance(wd, _C) else "")
            out.append(f"{type(wd).__name__} “{txt[:50]}” {why}")
    for wd in root.findChildren(QAbstractButton) + root.findChildren(QLabel):
        if not visible_in_window(wd) or isinstance(wd, (w.ElidedLabel,)) or type(wd).__name__.startswith("Elided"):
            continue
        if isinstance(wd, QLabel) and (wd.wordWrap() or not wd.text() or wd.pixmap() is not None and
                                       not wd.pixmap().isNull()):
            continue
        if isinstance(wd, QAbstractButton) and not wd.text().strip():
            continue
        if isinstance(wd, QLabel) and wd.textFormat() == Qt.TextFormat.RichText or (
                isinstance(wd, QLabel) and "<" in wd.text()):
            continue  # chữ có định dạng: đo bằng sizeHint không chuẩn, xem ảnh
        need = wd.sizeHint().width()
        if need > wd.width() + 3:
            out.append(f"{type(wd).__name__} “{wd.text()[:60]}” cần {need}px, có {wd.width()}px")
    return out


win = mw.MainWindow()
win.show()
win.load_project(Project.load(os.path.join(ROOT, "Mau-Test", "Du-an-mau - Loop 70 lan.lsproj")))
pump(3)
PAGES = {0: "video", 1: "nhac", 2: "xuat", 3: "caidat", 4: "huongdan"}
total = 0
for font in (10, 12):
    _st.setValue("pref/font_pt", font)
    win._apply_prefs()
    for mode in ("video_music", "video_only", "music_only"):
        win.set_mode(mode)
        for size in ((1280, 720), (1366, 768), (1600, 900), (1920, 1080)):
            win.resize(*size)
            pump(0.6)
            for idx, name in PAGES.items():
                if mode == "music_only" and idx == 0 or font == 12 and idx == 4:
                    continue
                win.go_to(idx)
                pump(0.5)
                bad = clipped(win)
                total += len(bad)
                if font == 10 and mode == "video_music":
                    win.grab().save(os.path.join(scratch, f"la_{size[0]}_{name}.png"))
                for b in bad[:8]:
                    print(f"   [chữ {font} · {mode} · {size[0]}×{size[1]} · {name}] {b}")
# hộp thoại hay dùng
from loopstation.ui.batch_dialog import BatchDialog  # noqa: E402
from loopstation.ui.preset_library import PresetLibraryDialog  # noqa: E402
_st.setValue("pref/font_pt", 10)
win._apply_prefs()
win.set_mode("video_music")
for make, name in ((lambda: BatchDialog(win.collect_project(), _st, win), "hangloat"),
                   (lambda: PresetLibraryDialog(win.collect_project().video.clips, _st, win), "thuvien")):
    dlg = make()
    for size in ((1000, 700), (1280, 860)):
        dlg.resize(*size)
        dlg.show()
        pump(1.2)
        bad = clipped(dlg)
        total += len(bad)
        for b in bad[:8]:
            print(f"   [{name} {size[0]}×{size[1]}] {b}")
    dlg.grab().save(os.path.join(scratch, f"la_dlg_{name}.png"))
    dlg.reject()
    pump(0.3)
check("không chữ nào bị cắt (nút / ô tick / nhãn một dòng)", total == 0, f"{total} chỗ")

# ---- lăn chuột: không đổi giá trị, chỉ cuộn ----
win.resize(1366, 768)
win.go_to(1)
pump(1)
mx = win.music_tab.mixer
before = (mx.values(), mx.music.slider.value())


def wheel(wd, dy=-120):
    pos = QPointF(wd.width() / 2, wd.height() / 2)
    ev = QWheelEvent(pos, QPointF(wd.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(wd, ev)


for wd in (mx.music.slider, mx.music.spin, mx.source.spin):
    wd.setFocus()  # kể cả khi ô đang được chọn
    wheel(wd)
    wheel(wd, 120)
pump(0.3)
check("lăn chuột qua thanh trượt / ô % không đổi âm lượng", (mx.values(), mx.music.slider.value()) == before,
      f"{before} → {(mx.values(), mx.music.slider.value())}")
win.go_to(0)
pump(0.5)
combos = [c for c in win.video_tab.findChildren(QComboBox)]
vals = [c.currentIndex() for c in combos]
for c in combos:
    c.setFocus()
    wheel(c)
pump(0.3)
check("lăn chuột qua dropdown không đổi lựa chọn", [c.currentIndex() for c in combos] == vals)
spins = win.findChildren(QAbstractSpinBox)
sv = [s.text() for s in spins]
for s in spins:
    wheel(s)
pump(0.3)
check("lăn chuột qua mọi ô số không đổi giá trị", [s.text() for s in spins] == sv)

win._closing = True
win.close()
pump(0.3)
check("không có lỗi ngầm", not errs, errs[0][-400:] if errs else "")
print("TẤT CẢ OK" if not fails else f"CÓ LỖI: {len(fails)}")
sys.exit(1 if fails else 0)
