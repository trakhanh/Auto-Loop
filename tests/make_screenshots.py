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

# Thư viện mẫu: 7 mẫu có sẵn (có mẫu bảng Loop A ×57 kẹp Loop B) + một mẫu bảng tự lưu
from loopstation.core import table_preset as tp  # noqa: E402
from loopstation.ui.interleave_dialog import save_table_presets  # noqa: E402
from loopstation.ui.preset_library import PresetLibraryDialog  # noqa: E402
demo = [ClipItem("5_loopB.mp4"), ClipItem("5_loopA.mp4", count=57), ClipItem("5_loopB.mp4"), ClipItem("5_loopA.mp4")]
mine = [ClipItem("5_loopB.mp4", count=2), ClipItem("5_loopA.mp4", count=30, loop_xfade=1.0), ClipItem("5_loopB.mp4", count=2)]
save_table_presets(st, [{"name": "Loop A ×30, Loop B ×2 hai đầu", "rows": tp.from_clips(mine)}])
lib = PresetLibraryDialog(demo, st, win)
lib.resize(980, 760)
lib.show()
wait(0.8)
lib.grab().save(str(OUT / "10-thu-vien-mau.png"))
lib.reject()

# Tải video: danh sách mẫu (không gọi mạng) — logo nền tảng, đang tải có thanh tiến độ, nhóm kênh, cột Cài đặt tải
from loopstation.core.downloader import Group, Item  # noqa: E402
from loopstation.ui.download_page import PROG_ROLE  # noqa: E402
dp = win.download_page
dp._exe_override = ["khong-goi-mang"]  # coi như đã cài công cụ tải (ảnh chụp không tải gì)
dp._refresh_ready()
win.go_to(mw.DOWNLOAD_PAGE)
wait(0.5)
win.grab().save(str(OUT / "12-tai-video-trong.png"))  # màn hình trống: hướng dẫn 3 bước + logo
demo_rows = [("Mưa rừng nhiệt đới 3 giờ — tiếng mưa thư giãn", "YouTube", 10800, "Kênh Chill"),
             ("Hoàng hôn trên biển", "TikTok", 45, "@bien.xanh"), ("城市夜景 4K", "Bilibili", 312, "UP主"),
             ("Phố cổ về đêm", "Douyin", 30, "抖音用户"), ("Reel cà phê sáng", "Instagram", 20, "cafe.sang"),
             ("Timelapse mây trời", "X", 58, "@sky"), ("Lửa trại ấm áp", "Facebook", 600, "Camping VN")]
for i, (t, pf, d, up) in enumerate(demo_rows):
    e = dp.queue.add_item(Item(f"https://example.com/v{i}", f"v{i}", t, pf, d, "", uploader=up))
    dp._add_row(e)
es = dp.queue.entries
es[0].status, es[0].codec = "done", ""
es[1].status = "running"
es[6].status, es[6].message, es[6].checked = "error", "Cần đăng nhập — bấm Đăng nhập trong app", False
for e in es:
    dp._paint(e)
dp._paint(es[1], "62% · 4,8 MB/s")
dp._row(es[1]).setData(3, PROG_ROLE, 0.62)
dp.queue.add_group(Group("https://example.com/@kenh/videos", "Kênh Lofi Chill", 0,
                         [Item(f"https://example.com/k{i}", f"k{i}", f"Lofi số {i + 1}", "YouTube", 180 + i, "",
                               uploader="Kênh Lofi Chill") for i in range(50)]), 50)
for e in dp.queue.entries[len(demo_rows):len(demo_rows) + 3]:
    dp._add_row(e)
dp._busy = False
dp._set_busy(True)
dp._fracs[id(es[1])] = 0.62
dp._run_done = 1
dp._changed()
wait(0.8)
win.grab().save(str(OUT / "11-tai-video.png"))
dp._anim.stop()
dp._busy = False
dp.queue.clear()
dp.tree.clear()
dp._rows.clear()
dp._group_rows.clear()

# Cắt video: Chia đoạn + Xuất ảnh với 2 video mẫu
cp = win.cut_page
cp.add_files([str(x) for x in sorted((ROOT / "Mau-Test" / "Video").glob("*.mp4"))[:3]])
win.go_to(mw.CUT_PAGE)
wait(2.5)
win.grab().save(str(OUT / "13-cat-video.png"))
cp.set_tab("frames")
wait(0.8)
win.grab().save(str(OUT / "14-xuat-anh.png"))

win._closing = True
win.close()
wait(0.3)
print("Đã lưu ảnh vào", OUT)
