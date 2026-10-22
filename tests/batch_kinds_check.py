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
check("VM: có ô Nhạc + Chế độ độ dài", "Nhạc:" in labels and "Chế độ độ dài:" in labels, str(labels))
check("VM: quét 3 video", len(d.jobs) == 3)
check("VM: độ dài theo dự án (2 giờ)", d.len_target.seconds() == 7200 and d.len_mode.currentData() == "target")
check("VM: chữ giống trang Video", [d.len_mode.itemText(i) for i in range(d.len_mode.count())] ==
      ["Thủ công — đúng số lần phát trong bảng", "Thời lượng mục tiêu (ví dụ 1h, 3h, 10h)", "Theo độ dài nhạc (1 lượt playlist)"])
check("VM: hàng Dài bao lâu + dòng giải thích", "Dài bao lâu:" in form_labels(d) and "3 giờ" not in d.len_hint.text()
      and "2 giờ" in d.len_hint.text(), d.len_hint.text())
from PySide6.QtWidgets import QPushButton as _QB  # noqa: E402
next(b for b in d.len_target_wrap.findChildren(_QB) if b.text() == "1h").click()
wait(0.3)
check("VM: nút nhanh 1h → 1 giờ", d.len_target.seconds() == 3600)
d.len_mode.setCurrentIndex(d.len_mode.findData("manual"))
wait(0.3)
check("VM: Thủ công → ẩn hàng Dài bao lâu", "Dài bao lâu:" not in form_labels(d))
d.len_mode.setCurrentIndex(d.len_mode.findData("target"))
d.len_target.set_seconds(1800)
wait(0.5)
check("VM: đổi độ dài → bảng tính lại 30 phút", d.tree.topLevelItem(0).text(C_DUR).startswith(("30:00", "00:30:00")),
      d.tree.topLevelItem(0).text(C_DUR))
d.grab().save(os.path.join(scratch, "batch_video_music.png"))
# bấm đổi kiểu ngay trong hộp thoại: không đóng / mở lại, giữ cài đặt, khung hướng dẫn giữ nguyên chiều cao
from PySide6.QtCore import Qt  # noqa: E402
card_h = d.card_text.parentWidget().height()
size0 = d.size()
d.tree.topLevelItem(1).setCheckState(0, Qt.CheckState.Unchecked)
d.kind_buttons["video_only"].click()
wait(0.05)
check("VM→VO: hộp thoại vẫn mở, đổi kiểu tại chỗ", d.isVisible() and d.kind == "video_only" and d.result() == 0)
check("VM→VO: đang hiện dần (hiệu ứng)", d.body.graphicsEffect() is not None)
wait(0.5)
check("VM→VO: hiện dần xong thì bỏ hiệu ứng", d.body.graphicsEffect() is None)
labels = form_labels(d)
check("VM→VO: ẩn ô Nhạc, khung nói không nhạc", "Nhạc:" not in labels and "không nhạc" in d.card_text.text(), str(labels))
check("VM→VO: giữ độ dài 30 phút, bỏ lựa chọn Theo độ dài nhạc",
      d.len_target.seconds() == 1800 and d.len_mode.findData("music") < 0 and d.len_mode.currentData() == "target")
check("VM→VO: bảng tính lại theo kiểu mới", len(d.jobs) == 3 and all(p is not None and p.output_kind == "video_only"
                                                                    for p in d._projects))
check("VM→VO: dòng đã bỏ tick vẫn bỏ tick", d.tree.topLevelItem(1).checkState(0) == Qt.CheckState.Unchecked)
check("VM→VO: cỡ hộp thoại và khung hướng dẫn không nhảy", d.size() == size0
      and d.card_text.parentWidget().height() == card_h, f"{card_h} → {d.card_text.parentWidget().height()}")
check("VM→VO: báo đang khác kiểu dự án", "Video có nhạc" in d.kind_hint.text())
d.grab().save(os.path.join(scratch, "switch_video_only.png"))
d.kind_buttons["music_only"].click()
wait(0.5)
labels = form_labels(d)
check("VM→MO: chỉ còn hàng của Chỉ nhạc", "Tính theo:" in labels and "Mẫu xếp clip:" not in labels
      and "Tiếng gốc clip:" not in labels, str(labels))
check("VM→MO: cột clip ẩn, tên cột theo file nhạc", d.tree.isColumnHidden(1)
      and "file nhạc" in d.tree.headerItem().text(0))
check("VM→MO: quét lại theo nhạc (2 thư mục thiếu nhạc)", len(d.jobs) == 3 and sum(1 for j in d.jobs if j.error) == 2)
check("VM→MO: khung hướng dẫn không nhảy", d.card_text.parentWidget().height() == card_h,
      f"{card_h} → {d.card_text.parentWidget().height()}")
d.grab().save(os.path.join(scratch, "switch_music_only.png"))
d.kind_buttons["video_music"].click()
wait(0.5)
check("MO→VM: quay lại đủ hàng + 3 video", "Nhạc:" in form_labels(d) and len(d.jobs) == 3
      and all(p is not None for p in d._projects) and not d.tree.isColumnHidden(1))
check("dự án gốc không đổi", tpl.output_kind == "video_music" and tpl.video.target_duration == 7200)
d.done(0)

# ---- Chỉ video ----
d = open_dlg("video_only", vid_parent)
labels = form_labels(d)
check("VO: ẩn ô Nhạc", "Nhạc:" not in labels, str(labels))
check("VO: khung hướng dẫn nói không nhạc", "không nhạc" in d.card_text.text())
check("VO: không có lựa chọn Theo độ dài nhạc", d.len_mode.findData("music") < 0)
check("VO: quét 3 video", len(d.jobs) == 3 and all(p is not None for p in d._projects))
d.grab().save(os.path.join(scratch, "batch_video_only.png"))
d.done(0)

# ---- Chỉ nhạc ----
d = open_dlg("music_only", mus_parent)
labels = form_labels(d)
check("MO: có Tính theo, không có Mẫu xếp clip / Nhạc", "Tính theo:" in labels
      and "Mẫu xếp clip:" not in labels and "Nhạc:" not in labels, str(labels))
check("MO: khung hướng dẫn nói playlist → file nhạc", "playlist" in d.card_text.text())
check("MO: quét 2 playlist", len(d.jobs) == 2 and all(p is not None for p in d._projects))
d.len_mode.setCurrentIndex(d.len_mode.findData("rounds"))
d.len_rounds.setValue(3)
wait(0.3)
check("MO: Số lượt → ẩn ô giờ, hiện ô lượt", not d.len_target_wrap.isVisible() and d.len_rounds.isVisible() and "Số lượt playlist:" in form_labels(d))
d.grab().save(os.path.join(scratch, "batch_music_only.png"))
d._accept()
check("MO: dự án hàng đợi nhận 3 lượt", d.result_projects and all(
    p.music.export_mode == "rounds" and p.music.export_rounds == 3 for p in d.result_projects))
check("MO: dự án gốc không đổi", tpl.music.export_mode == "target")

# ---- cửa sổ chính: đang ở kiểu Video có nhạc, đổi sang Chỉ nhạc trong hộp thoại → hàng đợi nhận file nhạc ----
from loopstation.ui import batch_dialog as bdm  # noqa: E402
from loopstation.ui import main_window as mw  # noqa: E402

from PySide6.QtCore import QSettings as _QS  # noqa: E402
from loopstation.ui.theme import APP_NAME as _APP, SETTINGS_ORG as _ORG  # noqa: E402
_QS(_ORG, _APP).setValue("ui/welcome_done", "1")  # màn hình chào: kiểm tra riêng ở look_check
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
    self.folder.setText(mus_parent)
    self._rescan()
    self.kind_buttons["music_only"].click()
    wait(0.5)
    seen.append(self.kind)
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
    check("cửa sổ chính: đổi kiểu trong cùng hộp thoại", seen == ["video_music", "music_only"], str(seen))
    check("cửa sổ chính: thêm 2 file nhạc vào hàng đợi", len(added) == 2 and all(i.kind == "audio" for i in added),
          str([(i.kind, os.path.basename(i.output)) for i in added]))
    check("cửa sổ chính: dự án đang mở vẫn là Video có nhạc", win.collect_project().output_kind == "video_music")
else:
    print("BỎ QUA kiểm tra cửa sổ chính (dự án mẫu chưa có thư mục lưu)")

check("không có lỗi ngầm", not errs, errs[0][-800:] if errs else "")
print("TẤT CẢ OK" if ok else "CÓ LỖI")
sys.exit(0 if ok else 1)
