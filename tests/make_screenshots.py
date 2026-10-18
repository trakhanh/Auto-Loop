"""Chụp ảnh màn hình cho README (không hiện cửa sổ, dữ liệu + cài đặt riêng).

python tests/make_screenshots.py [thư_mục_ảnh]   (mặc định docs/screenshots)
"""
import os
import sys
import tempfile
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="ktls_shots_"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
os.environ["KTLS_DATA_DIR"] = str(tmp / "data")
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore", DeprecationWarning)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
import loopstation.ui.main_window as mw  # noqa: E402
from loopstation.core.project import AmbientLayer, Project  # noqa: E402

ini = str(tmp / "s.ini")
mw.QSettings = lambda org, name: QSettings(ini, QSettings.Format.IniFormat)


def wait(sec: float) -> None:
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.02)


win = mw.MainWindow()
win.resize(1440, 900)
win.show()
wait(2)
win._load_initial_project()
wait(1)
win.grab().save(str(OUT / "01-bat-dau.png"))

p = Project.load(str(ROOT / "Mau-Test" / "Du-an-mau - Loop 70 lan.lsproj"))
p.music.ambient = [AmbientLayer("builtin:rain_light", volume=60)]
win.load_project(p)
win.go_to(0)
wait(2.5)
win.grab().save(str(OUT / "02-video.png"))
win.go_to(1)
wait(1.5)
win._scroll_to(win.music_tab.mixer)
wait(1)
win.grab().save(str(OUT / "03-nhac-bang-tron-am.png"))
win.go_to(2)
wait(1.5)
win.grab().save(str(OUT / "04-xuat.png"))

from loopstation.ui.batch_dialog import BatchDialog  # noqa: E402
st = QSettings(ini, QSettings.Format.IniFormat)
st.setValue("batch/folder", str(ROOT / "Mau-Test" / "Hang-loat"))
dlg = BatchDialog(win.collect_project(), st, win)
dlg.resize(1180, 720)
dlg.show()
wait(2)
dlg.grab().save(str(OUT / "05-hang-loat.png"))
dlg.done(0)
win._closing = True
win.close()
wait(0.3)
print("Đã lưu ảnh vào", OUT)
