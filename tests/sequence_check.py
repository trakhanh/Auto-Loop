"""Kiểm tra kiểu xếp "Lần lượt từng loop" (Content → Loop1 ×60 → Loop2 ×60 …), fps theo clip chính, mẫu trong
Xuất hàng loạt, và Ctrl+C / Ctrl+V / Ctrl+D ở bảng clip + playlist nhạc. Không hiện cửa sổ, dữ liệu riêng.

python tests/sequence_check.py <thư_mục_tạm>
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
os.environ.setdefault("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
warnings.simplefilter("ignore", DeprecationWarning)
errs = []
sys.excepthook = lambda t, v, tb: errs.append("".join(traceback.format_exception(t, v, tb)))
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
from loopstation.core import batch, timeline  # noqa: E402
from loopstation.core.project import Project  # noqa: E402
from loopstation.ui import main_window as mw  # noqa: E402
from loopstation.ui import sequence_dialog as sqd  # noqa: E402
from loopstation.ui.interleave_dialog import SEQUENCE_PRESETS, all_presets, arrange_from_preset  # noqa: E402

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
    return bool(cond and cond())


# thư mục giống VideoTest2: Content.mp4 + Loop1..Loop3.mp4 (lấy clip mẫu, đổi tên)
src = os.path.join(ROOT, "Mau-Test", "Hang-loat")
parent = os.path.join(scratch, "loat")
shutil.rmtree(parent, ignore_errors=True)
folder = os.path.join(parent, "Video A")
os.makedirs(folder)
# Content 30 fps (các loop 24 fps) — như VideoTest2: xuất phải theo fps của loop (phát lâu nhất)
from loopstation.core import ffmpeg_tools as ft  # noqa: E402
ft.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30", "-f", "lavfi",
        "-i", "sine=frequency=440:sample_rate=48000", "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", os.path.join(folder, "Content.mp4")], timeout=120)
for k, f in enumerate(("Video 01 - Mua dem/loop_mua-dem.mp4", "Video 02 - Rung xanh/loop_rung-xanh.mp4",
                       "Video 01 - Mua dem/3_bau-troi-sao.mp4"), 1):
    shutil.copy(os.path.join(src, f), os.path.join(folder, f"Loop{k}.mp4"))
files = sorted(os.path.join(folder, f) for f in os.listdir(folder))

from PySide6.QtCore import QSettings as _QS  # noqa: E402
from loopstation.ui.theme import APP_NAME as _APP, SETTINGS_ORG as _ORG  # noqa: E402
_QS(_ORG, _APP).setValue("ui/welcome_done", "1")  # màn hình chào: kiểm tra riêng ở look_check
win = mw.MainWindow()
win.resize(1440, 900)
win.show()
wait(1)
win._load_initial_project()
wait(0.5)
win.go_to(0)
vt = win.video_tab
vt.list.clear()
vt.add_paths(files)
wait(1.5, lambda: vt.list.topLevelItemCount() == 4)
check("gợi ý tự đổi sang Xếp lần lượt khi có nhiều clip loop", vt.suggest.isVisible() or vt._suggest_kind == "sequence")
check("nút gợi ý ghi Xếp lần lượt…", vt.suggest_go.text() == "Xếp lần lượt…", vt.suggest_go.text())

# ---- hộp thoại Xếp lần lượt: mỗi loop 60 lần, Content ở đầu ----
st = QSettings(os.path.join(scratch, "s.ini"), QSettings.Format.IniFormat)
clips, infos, durs = vt._table_media()
dlg = sqd.SequenceDialog(clips, durs, st)
dlg.plays.setText("60")
dlg.pos.setCurrentIndex(dlg.pos.findData("start"))
wait(0.2)
names = [dlg.order.item(i).text().split()[0] for i in range(dlg.order.count())]
check("xem trước thứ tự: Content → Loop1 → Loop2 → Loop3", names == ["Content.mp4", "Loop1.mp4", "Loop2.mp4", "Loop3.mp4"],
      str(names))
dlg.show()
wait(0.3)
dlg.grab().save(os.path.join(scratch, "sequence_dialog.png"))
dlg._accept()
vt._apply_arranged(dlg.result_clips, infos, "Đã xếp lần lượt")
wait(0.5)
rows = [(os.path.basename(vt._clip_from_item(it).path), vt._clip_from_item(it).count) for it in vt.list.items()]
check("bảng clip sau khi áp dụng", rows == [("Content.mp4", 1), ("Loop1.mp4", 60), ("Loop2.mp4", 60), ("Loop3.mp4", 60)],
      str(rows))
dlg2 = sqd.SequenceDialog(clips, durs, st)
dlg2.plays.setText("10p")
dlg2.pos.setCurrentIndex(dlg2.pos.findData("both"))
dlg2.repeat.setValue(2)
r = [c for c in dlg2._build() if c.enabled]
check("10 phút mỗi loop · Content đầu + cuối · lặp 2 lượt",
      [os.path.basename(c.path) for c in r] == ["Content.mp4"] + ["Loop1.mp4", "Loop2.mp4", "Loop3.mp4"] * 2 + ["Content.mp4"]
      and all(c.plays_mode == "duration" and c.play_seconds == 600 for c in r if os.path.basename(c.path).startswith("Loop")))
dlg2.plays.setText("abc")
wait(0.1)
check("gõ sai số lần → không cho áp dụng", not dlg2.ok_btn.isEnabled())

# ---- fps theo clip phát lâu nhất ----
p = win.collect_project()
tl = timeline.build(p)
infos_fps = {os.path.basename(i.path): float(i.fps) for i in tl.clip_infos.values()}
loop_fps = timeline.snap_fps(next(i.fps for i in tl.clip_infos.values() if "Loop1" in i.path))
check("fps xuất theo clip loop (phát lâu nhất)", tl.fps == loop_fps, f"{float(tl.fps)} · {infos_fps}")

# ---- Ctrl+C / Ctrl+V / Ctrl+D ở bảng clip ----
win.activateWindow()
wait(0.3)
lst = vt.list
lst.setFocus()
wait(0.2)
lst.clearSelection()
lst.topLevelItem(0).setSelected(True)
lst.setCurrentItem(lst.topLevelItem(0))
QTest.keyClick(lst, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
lst.clearSelection()
lst.topLevelItem(3).setSelected(True)
QTest.keyClick(lst, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
wait(0.4)
names = [os.path.basename(vt._clip_from_item(it).path) for it in lst.items()]
check("Ctrl+C rồi Ctrl+V: dán Content xuống dưới dòng đang chọn", names[-1] == "Content.mp4" and len(names) == 5, str(names))
lst.clearSelection()
lst.topLevelItem(1).setSelected(True)
QTest.keyClick(lst, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
wait(0.4)
rows = [(os.path.basename(vt._clip_from_item(it).path), vt._clip_from_item(it).count) for it in lst.items()]
check("Ctrl+D: nhân bản dòng, giữ số lần phát", rows[1] == rows[2] == ("Loop1.mp4", 60) and len(rows) == 6, str(rows))
QTest.keyClick(lst, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
wait(0.5)
check("Ctrl+Z: hoàn tác nhân bản", lst.topLevelItemCount() == 5, str(lst.topLevelItemCount()))

# ---- Ctrl+C / Ctrl+V / Ctrl+D ở playlist nhạc ----
win.go_to(1)
wait(0.4)
mt = win.music_tab
songs = sorted(os.path.join(ROOT, "Mau-Test", "Nhac", f) for f in os.listdir(os.path.join(ROOT, "Mau-Test", "Nhac")))[:3]
mt.list.clear()
mt.add_paths(songs)
wait(1, lambda: mt.list.topLevelItemCount() == 3)
ml = mt.list
win.activateWindow()
ml.setFocus()
wait(0.2)
ml.clearSelection()
ml.topLevelItem(0).setSelected(True)
ml.topLevelItem(0).setText(3, "70")  # âm lượng riêng 70% → bản sao giữ nguyên
QTest.keyClick(ml, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
wait(0.3)
tracks = win.collect_project().music.tracks
check("nhạc Ctrl+D: nhân bản bài, giữ âm lượng riêng", len(tracks) == 4 and tracks[1].path == tracks[0].path
      and tracks[1].volume == 70, str([(os.path.basename(t.path), t.volume) for t in tracks]))
ml.clearSelection()
ml.topLevelItem(2).setSelected(True)
QTest.keyClick(ml, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
ml.clearSelection()
ml.topLevelItem(3).setSelected(True)
QTest.keyClick(ml, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
wait(0.3)
tracks = win.collect_project().music.tracks
check("nhạc Ctrl+C / Ctrl+V: dán xuống cuối", len(tracks) == 5 and tracks[4].path == tracks[2].path,
      str([os.path.basename(t.path) for t in tracks]))
tl = timeline.build(win.collect_project())
check("playlist có bài trùng vẫn tính lịch phát được", tl.ok, " · ".join(tl.errors))

# ---- Xuất hàng loạt: mẫu Lần lượt từng loop ----
names = [p["name"] for p in all_presets(None)]
check("Mẫu xếp clip của hàng loạt có kiểu Lần lượt từng loop", all(p["name"] in names for p in SEQUENCE_PRESETS))
arrange = arrange_from_preset(SEQUENCE_PRESETS[0])
jobs = batch.scan(parent)
tpl = Project()
proj = batch.build_project(tpl, jobs[0], "template", arrange, loop_xfade=1.0, next_xfade=0.5)
rows = [(os.path.basename(c.path), c.count, c.loop_xfade) for c in proj.video.clips if c.enabled]
check("hàng loạt: Content → Loop1 ×60 → Loop2 ×60 → Loop3 ×60, loop nào cũng có Nối loop",
      [r[:2] for r in rows] == [("Content.mp4", 1), ("Loop1.mp4", 60), ("Loop2.mp4", 60), ("Loop3.mp4", 60)]
      and all(r[2] == 1.0 for r in rows[1:]), str(rows))
from loopstation.ui.batch_dialog import BatchDialog  # noqa: E402
st.setValue("batch/folder", parent)
st.setValue("batch/preset", SEQUENCE_PRESETS[0]["name"])
tpl.export.output_dir = os.path.join(scratch, "out")
bd = BatchDialog(tpl, st)
bd.show()
wait(2)
check("hộp thoại hàng loạt chọn được cách xếp", bd.preset.currentText() == "Xếp lần lượt: " + SEQUENCE_PRESETS[0]["name"], bd.preset.currentText())
p0 = bd._projects[0]
check("hộp thoại hàng loạt dựng đúng thứ tự", p0 is not None and [os.path.basename(c.path) for c in p0.video.clips
                                                                  if c.enabled][:2] == ["Content.mp4", "Loop1.mp4"])
# "Chỉnh…" một dòng khi đang dùng mẫu lần lượt: mở hộp thoại Xếp lần lượt (không biến thành xen kẽ)
orig_exec = sqd.SequenceDialog.exec


def fake_exec(self):
    self.plays.setText("5")
    self._update()
    self._accept()
    return 1


sqd.SequenceDialog.exec = fake_exec
bd._edit(0)
sqd.SequenceDialog.exec = orig_exec
wait(1)
p0 = bd._projects[0]
rows = [(os.path.basename(c.path), c.count, c.loop_xfade) for c in p0.video.clips if c.enabled]
check("hàng loạt Chỉnh…: vẫn lần lượt, mỗi loop 5 lần, loop nào cũng có Nối loop",
      [r[:2] for r in rows] == [("Content.mp4", 1), ("Loop1.mp4", 5), ("Loop2.mp4", 5), ("Loop3.mp4", 5)]
      and all(r[2] == bd.loop_xf.value() for r in rows[1:]), str(rows))
bd.done(0)
check("không có lỗi ngầm", not errs, errs[0][-1200:] if errs else "")
print("TẤT CẢ OK" if ok else "CÓ LỖI")
sys.exit(0 if ok else 1)
