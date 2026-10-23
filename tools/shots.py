r"""Capture UI screenshots of every main page (offscreen, isolated data + settings).

Run:  .venv\Scripts\python.exe tools\shots.py [--out docs\ui\before] [--palette neon] [--font 10]
Writes 1440x900 PNGs. Nothing touches the user's real settings or data.
"""
import argparse
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser()
ap.add_argument("--out", default=os.path.join(ROOT, "docs", "ui", "before"))
ap.add_argument("--palette", default="neon")
ap.add_argument("--font", type=int, default=10)
ap.add_argument("--w", type=int, default=1440)
ap.add_argument("--h", type=int, default=900)
args = ap.parse_args()

scratch = tempfile.mkdtemp(prefix="ktls_shots_")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
os.environ["KTLS_DATA_DIR"] = os.path.join(scratch, "data")
sys.dont_write_bytecode = True
sys.path.insert(0, ROOT)
os.makedirs(args.out, exist_ok=True)

from PySide6.QtCore import QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, args.font, args.palette)
import loopstation.ui.main_window as mw  # noqa: E402

ini = os.path.join(scratch, "settings.ini")
mw.QSettings = lambda org, name: QSettings(ini, QSettings.Format.IniFormat)


def pump(sec: float) -> None:
    loop = QEventLoop()
    QTimer.singleShot(int(sec * 1000), loop.quit)
    loop.exec()


def shot(win, name: str) -> None:
    pump(0.6)
    path = os.path.join(args.out, f"{name}.png")
    win.grab().save(path)
    print("saved", path)


win = mw.MainWindow()
win.resize(args.w, args.h)
win.show()
pump(2.0)
# first launch shows the welcome overlay -> capture it, then close it
if getattr(win, "_welcome", None) is not None:
    shot(win, "00-welcome")
    try:
        win._welcome.close()
    except Exception:  # noqa: BLE001
        pass
    pump(0.5)
else:
    win.show_welcome()
    shot(win, "00-welcome")
    try:
        win._welcome.close()
    except Exception:  # noqa: BLE001
        pass

win.go_to(mw.HOME_PAGE)
shot(win, "01-home")
win.go_to(0)
shot(win, "02-video-empty")
win.go_to(1)
shot(win, "03-music-empty")
win.go_to(2)
shot(win, "04-export-empty")

# with a sample project (media resolved relative to Mau-Test)
sample = os.path.join(ROOT, "Mau-Test", "Du-an-mau - 3 tieng.lsproj")
win.open_project_path(sample)
pump(3.0)  # let thumbnails/probes finish
win.go_to(0)
shot(win, "05-video-project")
win.go_to(1)
shot(win, "06-music-project")
win.go_to(2)
shot(win, "07-export-project")
win.go_to(3)
shot(win, "08-settings")
win.go_to(4)
shot(win, "09-help")
sys.stdout.flush()
os._exit(0)
