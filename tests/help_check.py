"""Kiểm tra trang Hướng dẫn: mọi chủ đề hiển thị được, ảnh có thật, ô tìm, nút “Mở …”.

python tests/help_check.py <thư_mục_tạm>   (chụp vài ảnh trang hướng dẫn vào thư mục đó)
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
from PySide6.QtCore import QSettings, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
import loopstation.ui.main_window as mw  # noqa: E402
from loopstation.ui import help_page as hp  # noqa: E402

ini = os.path.join(scratch, "s.ini")
mw.QSettings = lambda org, name: QSettings(ini, QSettings.Format.IniFormat)
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))


def wait(sec):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.02)


win = mw.MainWindow()
win.resize(int(sys.argv[2]) if len(sys.argv) > 2 else 1440, int(sys.argv[3]) if len(sys.argv) > 3 else 900)
win.show()
wait(1.5)
win._load_initial_project()
win.go_to(4)
wait(1)
h = win.help_page
import re  # noqa: E402
missing = []
for tid, _g, _i, title, html in hp.TOPICS:
    for name in re.findall(r"@IMG:([\w-]+)@", html):
        if not (hp.HELP_DIR / "help" / f"{name}.png").is_file():
            missing.append(name)
    h.show_topic(tid)
    wait(0.15)
check(f"{len(hp.TOPICS)} chủ đề hiển thị được", not errs, errs[0][-400:] if errs else "")
check("mọi ảnh minh hoạ có thật", not missing, str(missing))
h.search.setText("tron am")
wait(0.2)
vis = [tid for tid, it in h._items.items() if not it.isHidden()]
check("tìm không dấu “tron am” ra Bảng trộn âm", "tron" in vis, str(vis))
h.search.setText("xyz không có")
wait(0.2)
check("tìm không thấy → báo", h.no_hit.isVisibleTo(h))
h.search.clear()
for act, page in (("app:video", 0), ("app:export", 2), ("app:mixer", 1), ("app:settings", 3)):
    win.go_to(4)
    h._on_link(QUrl(act))
    wait(0.4)
    check(f"nút {act} → trang {page}", win.stack.currentIndex() == page, str(win.stack.currentIndex()))
win.go_to(4)
for tid in ("batdau", "video", "tron", "hangloat", "xenke"):
    h.show_topic(tid)
    wait(0.6)
    win.grab().save(os.path.join(scratch, f"help_{tid}_{win.width()}.png"))
check("không có lỗi ngầm", not errs, errs[0][-400:] if errs else "")
print("TẤT CẢ OK" if ok else "CÓ LỖI")
win._closing = True
win.close()
sys.exit(0 if ok else 1)
