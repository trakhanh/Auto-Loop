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
_st = QSettings(ini, QSettings.Format.IniFormat)
_st.setValue("ui/welcome_done", "1")  # màn hình chào chụp riêng bên dưới
_st.sync()
mw.QSettings = lambda org, name: QSettings(ini, QSettings.Format.IniFormat)


def wait(sec: float) -> None:
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.02)


def wait_for(cond, limit: float = 40) -> None:
    t = time.time()
    while time.time() - t < limit and not cond():
        wait(0.1)


def player_ready(pl) -> bool:
    return pl.state == "paused" and pl._seek_to is None and pl.sch is not None


win = mw.MainWindow()
win.resize(1440, 900)
win.show()
wait(2)
win._load_initial_project()
wait(1)
win.grab().save(str(OUT / "01-bat-dau.png"))

# màn hình chào lần đầu
win.show_welcome()
wait(1.5)
win.grab().save(str(OUT / "00-chao-mung.png"))
win._welcome._finish()
wait(0.8)

p = Project.load(str(ROOT / "Mau-Test" / "Du-an-mau - Loop 70 lan.lsproj"))
p.music.ambient = [AmbientLayer("builtin:rain_light", volume=60)]
win.load_project(p)
win.go_to(0)
wait(8)  # đợi tạo xong tiếng nền có sẵn (không còn dòng “Đang tạo tiếng nền…” trong ảnh)
win.recompute()
pl = win.viewer.player
wait_for(lambda: player_ready(pl) and win.viewer.view.image is not None)
pl.seek(404)  # khung hình có chữ, vạch phát nằm giữa dòng thời gian
wait(1.5)
wait_for(lambda: player_ready(pl))
wait(1.5)
win.grab().save(str(OUT / "02-video.png"))
win.go_to(1)
wait(1.5)
win._scroll_to(win.music_tab.mixer)
wait(1)
win.grab().save(str(OUT / "03-nhac-bang-tron-am.png"))
win.go_to(2)
wait(1.5)
win.grab().save(str(OUT / "04-xuat.png"))

# trang Cài đặt (2 cột trên màn hình rộng) — đợi đọc xong thông số máy / card đồ hoạ
win.go_to(3)
wait(8)
win.grab().save(str(OUT / "07-cai-dat.png"))

# trang Hướng dẫn: Tổng quan (có gì mới, 3 bước có ảnh, lưới chủ đề)
win.go_to(4)
win.help_page.show_hub()
wait(1.5)
win.grab().save(str(OUT / "08-huong-dan.png"))
win.help_page.show_topic("xenke")
wait(1.2)
win.grab().save(str(OUT / "09-huong-dan-chu-de.png"))


from loopstation.ui.batch_dialog import BatchDialog  # noqa: E402
st = QSettings(ini, QSettings.Format.IniFormat)
st.setValue("batch/folder", str(ROOT / "Mau-Test" / "Hang-loat"))
dlg = BatchDialog(win.collect_project(), st, win)
dlg.resize(1280, 860)
dlg.show()
bp = dlg.player_panel.player
wait_for(lambda: player_ready(bp) and dlg.player_panel.view.image is not None)
bp.seek(404)
wait(1.5)
wait_for(lambda: player_ready(bp))
wait(1.5)
dlg.grab().save(str(OUT / "05-hang-loat.png"))
dlg.done(0)

# Xếp lần lượt: thư mục kiểu Content.mp4 + Loop1..Loop3.mp4
import shutil  # noqa: E402
from loopstation.core.project import ClipItem  # noqa: E402
from loopstation.ui.sequence_dialog import SequenceDialog  # noqa: E402
src = ROOT / "Mau-Test" / "Hang-loat"
seq_dir = tmp / "seq"
seq_dir.mkdir()
shutil.copy(src / "Video 01 - Mua dem" / "2_hoang-hon.mp4", seq_dir / "Content.mp4")
for k, f in enumerate(("Video 01 - Mua dem/loop_mua-dem.mp4", "Video 02 - Rung xanh/loop_rung-xanh.mp4",
                       "Video 01 - Mua dem/3_bau-troi-sao.mp4"), 1):
    shutil.copy(src / f, seq_dir / f"Loop{k}.mp4")
clips = [ClipItem(str(f)) for f in sorted(seq_dir.iterdir())]
sd = SequenceDialog(clips, {os.path.normcase(c.path): 8.0 for c in clips}, st, win)
sd.plays.setText("60")
sd.resize(580, 470)
sd.show()
wait(0.8)
sd.grab().save(str(OUT / "06-xep-lan-luot.png"))
sd.reject()

# Thư viện mẫu: 6 mẫu có sẵn + một mẫu bảng clip tự lưu (5_loopB ×1 → 5_loopA ×57 → 5_loopB ×1 → 5_loopA ×1)
from loopstation.core import table_preset as tp  # noqa: E402
from loopstation.ui.interleave_dialog import save_table_presets  # noqa: E402
from loopstation.ui.preset_library import PresetLibraryDialog  # noqa: E402
demo = [ClipItem("5_loopB.mp4"), ClipItem("5_loopA.mp4", count=57), ClipItem("5_loopB.mp4"), ClipItem("5_loopA.mp4")]
save_table_presets(st, [{"name": "Loop A ×57 kẹp Loop B", "rows": tp.from_clips(demo)}])
lib = PresetLibraryDialog(demo, st, win)
lib.resize(980, 760)
lib.show()
wait(0.8)
lib.grab().save(str(OUT / "10-thu-vien-mau.png"))
lib.reject()

win._closing = True
win.close()
wait(0.3)
print("Đã lưu ảnh vào", OUT)
