"""Kiểm tra Xuất hàng loạt cho đủ 3 kiểu (Video có nhạc / Chỉ video / Chỉ nhạc): nút chọn kiểu, khung hướng dẫn,
ô độ dài, đổi kiểu ngay trong hộp thoại. Không hiện cửa sổ, dữ liệu riêng; lưu ảnh chụp vào thư mục tạm.

python tests/batch_kinds_check.py <thư_mục_tạm>
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
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
from loopstation.core.project import MusicTrack, Project  # noqa: E402
from loopstation.ui.batch_dialog import C_DUR, BatchDialog  # noqa: E402

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


def form_labels(dlg):
    return [lb.text() for lb in dlg.findChildren(QLabel) if lb.text().endswith(":") and lb.isVisibleTo(dlg)]


vid_parent = os.path.join(scratch, "Hang-loat")
shutil.rmtree(vid_parent, ignore_errors=True)
shutil.copytree(os.path.join(ROOT, "Mau-Test", "Hang-loat"), vid_parent)
mus_parent = os.path.join(scratch, "Nhac-loat")
shutil.rmtree(mus_parent, ignore_errors=True)
songs = sorted(os.listdir(os.path.join(ROOT, "Mau-Test", "Nhac")))
for i, name in enumerate(("Piano dem", "Lofi hoc bai")):
    d = os.path.join(mus_parent, name)
    os.makedirs(d)
    for s in songs[i * 2:i * 2 + 2]:
        shutil.copy(os.path.join(ROOT, "Mau-Test", "Nhac", s), d)

tpl = Project(name="khuôn")
tpl.export.output_dir = os.path.join(scratch, "out")
tpl.music.tracks = [MusicTrack(os.path.join(ROOT, "Mau-Test", "Nhac", songs[0]))]
tpl.video.length_mode, tpl.video.target_duration = "target", 2 * 3600
tpl.music.export_mode, tpl.music.export_target = "target", 3600
st = QSettings(os.path.join(scratch, "s.ini"), QSettings.Format.IniFormat)


def open_dlg(kind, folder):
    import copy
    t = copy.deepcopy(tpl)
    t.output_kind = kind
    st.setValue("batch/folder", folder)
    dlg = BatchDialog(t, st)
    dlg.resize(1180, 820)
    dlg.show()
    wait(1.5)
    return dlg


# ---- Video có nhạc ----
d = open_dlg("video_music", vid_parent)
check("VM: nút kiểu Video có nhạc được chọn sẵn", d.kind_buttons["video_music"].isChecked())
check("VM: khung hướng dẫn nói video có nhạc", "có nhạc" in d.card_text.text() and "loop" in d.card_text.text())
labels = form_labels(d)
check("VM: có ô Nhạc + Độ dài mỗi video", "Nhạc:" in labels and "Độ dài mỗi video:" in labels, str(labels))
check("VM: quét 3 video", len(d.jobs) == 3)
check("VM: độ dài theo dự án (2 giờ)", d.len_target.seconds() == 7200 and d.len_mode.currentData() == "target")
d.len_target.set_seconds(1800)
wait(0.5)
check("VM: đổi độ dài → bảng tính lại 30 phút", d.tree.topLevelItem(0).text(C_DUR).startswith(("30:00", "00:30:00")),
      d.tree.topLevelItem(0).text(C_DUR))
d.grab().save(os.path.join(scratch, "batch_video_music.png"))
# bấm đổi sang Chỉ video → hộp thoại đóng với khuôn mới, giữ độ dài
d.kind_buttons["video_only"].click()
wait(0.2)
check("VM→VO: đóng hộp thoại để mở lại kiểu mới", d.switch_to is not None and d.result() == 2)
check("VM→VO: khuôn mới là Chỉ video, giữ 30 phút", d.switch_to.output_kind == "video_only"
      and d.switch_to.video.target_duration == 1800, str(d.switch_to.video.target_duration))
check("VM→VO: dự án gốc không đổi", tpl.output_kind == "video_music" and tpl.video.target_duration == 7200)

# ---- Chỉ video ----
d = open_dlg("video_only", vid_parent)
labels = form_labels(d)
check("VO: ẩn ô Nhạc", "Nhạc:" not in labels, str(labels))
check("VO: khung hướng dẫn nói không nhạc", "không nhạc" in d.card_text.text())
check("VO: không có lựa chọn Theo độ dài nhạc", d.len_mode.findData("music") < 0)
check("VO: quét 3 video", len(d.jobs) == 3 and all(p is not None for p in d._projects))
d.grab().save(os.path.join(scratch, "batch_video_only.png"))
d.kind_buttons["music_only"].click()
wait(0.2)
check("VO→MO: khuôn Chỉ nhạc, độ dài file = độ dài video", d.switch_to.output_kind == "music_only"
      and d.switch_to.music.export_target == 7200)

# ---- Chỉ nhạc ----
d = open_dlg("music_only", mus_parent)
labels = form_labels(d)
check("MO: có Độ dài mỗi file, không có Mẫu xếp clip / Nhạc", "Độ dài mỗi file:" in labels
      and "Mẫu xếp clip:" not in labels and "Nhạc:" not in labels, str(labels))
check("MO: khung hướng dẫn nói playlist → file nhạc", "playlist" in d.card_text.text())
check("MO: quét 2 playlist", len(d.jobs) == 2 and all(p is not None for p in d._projects))
d.len_mode.setCurrentIndex(d.len_mode.findData("rounds"))
d.len_rounds.setValue(3)
wait(0.3)
check("MO: Số lượt → ẩn ô giờ, hiện ô lượt", not d.len_target.isVisible() and d.len_rounds.isVisible())
d.grab().save(os.path.join(scratch, "batch_music_only.png"))
d._accept()
check("MO: dự án hàng đợi nhận 3 lượt", d.result_projects and all(
    p.music.export_mode == "rounds" and p.music.export_rounds == 3 for p in d.result_projects))
check("MO: dự án gốc không đổi", tpl.music.export_mode == "target")

# ---- cửa sổ chính: đang ở kiểu Video có nhạc, đổi sang Chỉ nhạc trong hộp thoại → hàng đợi nhận file nhạc ----
from loopstation.ui import batch_dialog as bdm  # noqa: E402
from loopstation.ui import main_window as mw  # noqa: E402

win = mw.MainWindow()
win.resize(1440, 900)
win.show()
wait(1)
win._load_initial_project()
win.load_project(Project.load(os.path.join(ROOT, "Mau-Test", "Du-an-mau - Loop 70 lan.lsproj")))
win.export_tab.out_dir.setText(os.path.join(scratch, "out-win"))
wait(0.5)
seen = []
orig_exec = bdm.BatchDialog.exec


def fake_exec(self):
    seen.append(self.kind)
    self.show()
    wait(1.0)
    if len(seen) == 1:
        self.folder.setText(mus_parent)
        self._rescan()
        self.kind_buttons["music_only"].click()
    else:
        self.run_now.setChecked(False)
        self._accept()
    return self.result()


bdm.BatchDialog.exec = fake_exec
before = len(win.queue)
tpl_out = win.collect_project().export.output_dir
if tpl_out:
    win.batch_from_folders()
    bdm.BatchDialog.exec = orig_exec
    added = win.queue[before:]
    check("cửa sổ chính: mở lại hộp thoại theo kiểu mới", seen == ["video_music", "music_only"], str(seen))
    check("cửa sổ chính: thêm 2 file nhạc vào hàng đợi", len(added) == 2 and all(i.kind == "audio" for i in added),
          str([(i.kind, os.path.basename(i.output)) for i in added]))
    check("cửa sổ chính: dự án đang mở vẫn là Video có nhạc", win.collect_project().output_kind == "video_music")
else:
    print("BỎ QUA kiểm tra cửa sổ chính (dự án mẫu chưa có thư mục lưu)")

check("không có lỗi ngầm", not errs, errs[0][-800:] if errs else "")
print("TẤT CẢ OK" if ok else "CÓ LỖI")
sys.exit(0 if ok else 1)
