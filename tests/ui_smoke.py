"""Chạy khắp giao diện (không hiện cửa sổ, dữ liệu + cài đặt riêng) và bắt mọi lỗi ngầm trong slot Qt.

python tests/ui_smoke.py <thư_mục_tạm>
"""
import os
import sys
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

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
import loopstation.ui.main_window as mw  # noqa: E402
from loopstation.core.project import Project  # noqa: E402

ini = os.path.join(scratch, "settings.ini")
st = QSettings(ini, QSettings.Format.IniFormat)
st.setValue("ui/timeline_dock", "off")  # trường hợp từng gây lỗi lúc khởi động
st.sync()
mw.QSettings = lambda org, name: QSettings(ini, QSettings.Format.IniFormat)
win = mw.MainWindow()
win.show()


def pump(n=5):
    for _ in range(n):
        app.processEvents()


pump(20)
win._load_initial_project()
pump()
S = os.path.join(ROOT, "Mau-Test")
steps = 0
for proj in ("Du-an-mau - Loop 70 lan.lsproj", "Du-an-mau - 3 tieng.lsproj"):
    win.open_project_path(os.path.join(S, proj))
    pump()
    for mode in ("video_music", "video_only", "music_only", "video_music"):
        win.set_mode(mode)
        win.recompute()
        for page in (0, 1, 2, 3, 4, 5, 0):
            win.go_to(page)
            pump(2)
            steps += 1
    for wsz in ((900, 700), (1366, 768), (1920, 1080)):
        win.resize(*wsz)
        pump(3)
    win.video_tab.source.setCurrentIndex(1)
    win.recompute()
    win.go_to(1)
    pump()
    win.video_tab.source.setCurrentIndex(0)
    win.music_tab.versions.setValue(3)
    mx = win.music_tab.mixer
    for v in (0, 50, 150, 100):
        mx.music.spin.setValue(v)
        mx.source.spin.setValue(v)
    win.set_mode("music_only")
    win.recompute()
    win.add_to_queue("audio")
    win.set_mode("video_music")
    win.recompute()
    win.add_to_queue("video")
    pump()
for k in ("video_music", "video_only", "music_only", "ambient"):
    win._home_choice(k)
    pump(3)
st.setValue("pref/font_pt", 12)
win._apply_prefs()
pump(5)
st.setValue("pref/font_pt", 10)
win._apply_prefs()
pump(5)
win.load_project(Project())
pump(5)
win._closing = True
win.close()
pump(5)
print(f"{steps} lần chuyển trang · {len(win.queue)} mục hàng đợi · lỗi ngầm: {len(errs)}")
for e in errs[:5]:
    print(e)
sys.exit(1 if errs else 0)
