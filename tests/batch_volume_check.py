"""Kiểm tra âm lượng trong Xuất hàng loạt (không hiện cửa sổ, dữ liệu riêng, nghe thử ở mức 0% = im lặng).

python tests/batch_volume_check.py <thư_mục_tạm>
"""
import os
import shutil
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
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
from loopstation.core.project import AmbientLayer, MusicTrack, Project  # noqa: E402
from loopstation.ui.batch_dialog import C_NOTE, VolumeDialog, BatchDialog  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.01)
    return False


parent = os.path.join(scratch, "Hang-loat")
shutil.rmtree(parent, ignore_errors=True)
shutil.copytree(os.path.join(ROOT, "Mau-Test", "Hang-loat"), parent)
tpl = Project(name="khuôn")
tpl.export.output_dir = os.path.join(scratch, "out")
tpl.music.tracks = [MusicTrack(os.path.join(ROOT, "Mau-Test", "Nhac", "01 - Mưa Trên Phố Cũ.mp3"))]
tpl.music.ambient = [AmbientLayer("builtin:rain_light", volume=60)]
tpl.video.music_volume, tpl.video.source_volume = 80, 100
st = QSettings(os.path.join(scratch, "s.ini"), QSettings.Format.IniFormat)
st.setValue("batch/folder", parent)
dlg = BatchDialog(tpl, st)
dlg.resize(1180, 760)
dlg.show()
wait(1.5)
check("quét 3 video", len(dlg.jobs) == 3)
check("âm lượng chung lấy theo dự án đang mở", (dlg.vol_music.value(), dlg.vol_source.value(),
                                               dlg.vol_amb[0].value()) == (80, 100, 60))
check("mỗi dòng có nút Xem", len(dlg._play_btns) == sum(p is not None for p in dlg._projects))
pp = dlg.player_panel.player
check("trình phát bên phải tự hiện video của dòng đầu", wait(40, lambda: pp.state == "paused" and pp.total > 0)
      and dlg._current_row() == 0, pp.state)

# âm lượng riêng cho dòng 1 (giả lập bấm OK trong hộp thoại riêng)
vd = VolumeDialog(dlg._projects[1], dlg._vol_for(1), dlg._row_info[1], dlg.jobs[1].name, dlg)
vd.mixer.music.spin.setValue(3)  # mức rất nhỏ: nghe thử gần như im lặng
vd.mixer.source.spin.setValue(0)
vd.mixer._amb_rows[0].spin.setValue(1)
vd.resize(560, 520)
vd.show()
wait(0.5)
vd.grab().save(os.path.join(scratch, "volume_dialog.png"))
check("hộp thoại âm lượng riêng trả đúng giá trị", vd.values() == {"music": 3, "source": 0, "amb": [1]},
      str(vd.values()))
dlg._vol_overrides[dlg.jobs[1].folder] = vd.values()
vd.done(0)
dlg._rebuild()
wait(0.5)
check("dòng có âm lượng riêng được ghi chú", "âm lượng riêng" in dlg.tree.topLevelItem(1).text(C_NOTE))

# xem trong trình phát (mọi mức 0% → im lặng), kéo thanh chung trong lúc phát
dlg.vol_music.setValue(0)
dlg.vol_source.setValue(0)
dlg.vol_amb[0].setValue(0)
t0 = time.time()
dlg._watch(0)
check("dòng 0: bấm Xem → phát", wait(120, lambda: pp.state == "playing"), f"{time.time() - t0:.1f}s chuẩn bị")
dlg.vol_amb[0].setValue(2)
wait(0.2)
check("kéo thanh chung → trình phát đổi ngay", pp.audio.mixer is not None and pp.audio.mixer.gains.get("amb:0") == 0.02,
      str(pp.audio.mixer.gains if pp.audio.mixer else None))
dlg.grab().save(os.path.join(scratch, "batch_volume.png"))
dlg._watch(1)  # dòng có âm lượng riêng
check("dòng 1: phát với âm lượng riêng", wait(120, lambda: pp.state == "playing" and dlg._current_row() == 1
                                                 and pp.audio.mixer is not None
                                                 and pp.audio.mixer.gains.get("music") == 0.03),
      str(pp.audio.mixer.gains if pp.audio.mixer else None))
dlg.vol_music.setValue(1)
wait(0.2)
check("thanh chung không đè âm lượng riêng", pp.audio.mixer.gains.get("music") == 0.03)
dlg._stop_listen()
check("tạm dừng trình phát", wait(3, lambda: pp.state == "paused"), pp.state)

# OK: âm lượng vào dự án hàng đợi
dlg.vol_music.setValue(55)
dlg._accept()
res = {p.name: p for p in dlg.result_projects}
r0, r1 = res[dlg.jobs[0].name], res[dlg.jobs[1].name]
check("dự án hàng đợi: mức chung", (r0.video.music_volume, r0.music.ambient[0].volume) == (55, 2))
check("dự án hàng đợi: âm lượng riêng", (r1.video.music_volume, r1.music.ambient[0].volume) == (3, 1))
check("dự án khuôn không bị đổi", tpl.video.music_volume == 80 and tpl.music.ambient[0].volume == 60)
check("không có lỗi ngầm", not errs, errs[0][-600:] if errs else "")
print("TẤT CẢ OK" if ok else "CÓ LỖI")
sys.exit(0 if ok else 1)
