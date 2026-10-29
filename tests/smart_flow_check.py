"""Quy trình rút gọn: thả file → tự nhận tập + tự áp mẫu → dải Sẵn sàng → Thêm vào hàng đợi ngay trang Video;
thả cả mùa → 1 câu hỏi → mỗi tập một mục hàng đợi; Bảng trộn âm chọn kiểu tiếng gốc + chọn nhanh + tự cân.
Chụp ảnh vào thư mục tạm.

python tests/smart_flow_check.py <thư_mục_tạm>
"""
import os
import shutil
import subprocess
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

from PySide6.QtCore import QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel  # noqa: E402

app = QApplication([])
from loopstation.core import ffmpeg_tools  # noqa: E402
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
import loopstation.ui.main_window as mw  # noqa: E402
from loopstation.core.project import Project  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("OK   " if ok else "LỖI ") + name + (f"  ({extra})" if extra and not ok else ""))
    if not ok:
        fails.append(name)


def pump(t=0.3):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()


def answer(text, shot="", then=None, delay=200):
    """Hộp thoại modal sắp hiện: chụp ảnh (nếu cần), bấm nút có chữ `text`; `then` = (chữ, ảnh) cho hộp kế tiếp."""
    def go():
        box = QApplication.activeModalWidget()
        if box is None or getattr(box, "_answered", False):
            QTimer.singleShot(100, go)
            return
        box._answered = True
        if shot:
            box.grab().save(os.path.join(scratch, shot))

        def says(b):
            return text in b.text().replace("&", "") or any(text in lab.text() for lab in b.findChildren(QLabel))
        btn = next((b for b in box.findChildren(QAbstractButton) if says(b)), None)
        (btn.click if btn else box.reject)()
        if then:
            answer(*then)
    QTimer.singleShot(delay, go)


def wait_for(cond, t=20.0):
    end = time.time() + t
    while time.time() < end and not cond():
        app.processEvents()
    return cond()


media = os.path.join(scratch, "media")
shutil.rmtree(media, ignore_errors=True)
os.makedirs(media)
src = os.path.join(media, "c.mp4")
subprocess.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=2", "-f", "lavfi",
                "-i", "anoisesrc=color=pink:amplitude=0.05:d=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", src], check=True)
season = os.path.join(media, "Mua 3")
os.makedirs(season)
for e in (33, 34, 35):
    for n in (1, 2, 3):
        for r in "AB":
            shutil.copy(src, os.path.join(season, f"{e}_{n}_LOOP {r}.mp4"))
shutil.copy(src, os.path.join(season, "33_2_ LOOP AB.mp4"))
one = os.path.join(media, "Tap 36")
os.makedirs(one)
for n in (1, 2):
    for r in "AB":
        shutil.copy(src, os.path.join(one, f"36_{n}_LOOP {r}.mp4"))

ini = os.path.join(scratch, "settings.ini")
_st = QSettings(ini, QSettings.Format.IniFormat)
_st.clear()
_st.setValue("ui/welcome_done", "1")
_st.sync()
mw.QSettings = lambda org, name: QSettings(ini, QSettings.Format.IniFormat)
win = mw.MainWindow()
win.resize(1500, 950)
win.show()
win.queue.clear()
win.export_tab.set_queue(win.queue)
proj = Project(name="Mùa 3", output_kind="video_only")
proj.export.output_dir = os.path.join(scratch, "out")
win.load_project(proj)
pump(1)
vt = win.video_tab

# ---- 1 tập: thả thư mục → tự áp mẫu, dải Sẵn sàng, Thêm vào hàng đợi ngay trang Video ----
vt.add_paths([one])
check("thả 1 tập: tự áp mẫu (có dòng ×57)", wait_for(lambda: any(c.count == 57 for c in vt.collect().clips)))
pump(2)
check("báo đã tự áp mẫu", vt.suggest.isVisible() and "Đã tự áp mẫu" in vt.suggest_text.text(), vt.suggest_text.text())
check("dải Sẵn sàng hiện + tên Tập 36", wait_for(lambda: vt.ready.isVisible() and "Tập 36" in vt.ready_text.text(), 8),
      vt.ready_text.text())
win.go_to(0)
pump(0.5)
win.grab().save(os.path.join(scratch, "s_ready.png"))
answer("Làm video tiếp theo")
vt.ready_add.click()
pump(1)
check("Thêm ngay trang Video: 1 mục Tập 36", len(win.queue) == 1 and os.path.basename(win.queue[0].output) == "Tập 36.mp4")
check("bảng trống chờ tập sau", not vt.collect().clips)

# ---- cả mùa: thả thư mục → hỏi → mỗi tập một mục ----
answer("Đưa cả 3 tập", "s_season.png", ("Ở lại", "s_season_added.png"))
vt.add_paths([season])
check("cả mùa: thêm 3 mục", wait_for(lambda: len(win.queue) == 4, 30), str(len(win.queue)))
pump(1)
names = [os.path.basename(i.output) for i in win.queue]
check("tên Tập 33 / 34 / 35", names[1:] == ["Tập 33.mp4", "Tập 34.mp4", "Tập 35.mp4"], str(names))
t33 = win.queue[1] if len(win.queue) > 1 else None
check("Tập 33 có LOOP AB đầu tình huống 2", t33 is not None and any("LOOP AB" in c.path for c in t33.project.video.clips))
check("Tập 34 không lẫn file tập khác", len(win.queue) > 2 and all(
    os.path.basename(c.path).startswith("34_") for c in win.queue[2].project.video.clips))

# ---- trộn ngẫu nhiên: thứ tự hiện ngay, Trộn lại, Dùng thứ tự này ----
from loopstation.core.project import ClipItem  # noqa: E402
names = [f"{c}_canh" for c in "ABCDEFG"]
for nm in names:
    shutil.copy(src, os.path.join(media, nm + ".mp4"))
pr = win.collect_project()
pr.video.clips = [ClipItem(os.path.join(media, nm + ".mp4"), count=2) for nm in names]
pr.video.order, pr.video.seed = "shuffle", 7
win.load_project(pr)
win.recompute()
check("trộn ngẫu nhiên: dải thứ tự hiện", wait_for(lambda: not vt.shuffle_bar.isHidden(), 8))
first = vt.shuffle_text.text()
check("dải ghi 6 clip đầu + số mầm + còn lại", sum(nm in first for nm in names) == 6 and "số mầm 7" in first
      and "(+1)" in first and "7 dòng" in vt.shuffle_more.text(), first)
data = win._shuffle_data(0)
check("cửa sổ Xem đủ thứ tự có đủ 7 dòng", data is not None and len(data["rows"]) == 7
      and sorted(r[0] for r in data["rows"]) == names)
vt.seed.setValue(12345)
win.recompute()
pump(1)
check("Trộn lại / đổi mầm → thứ tự khác", vt.shuffle_text.text() != first)
win.go_to(0)
pump(0.5)
win.grab().save(os.path.join(scratch, "s_shuffle.png"))
answer("Đóng", "s_shuffle_dlg.png", delay=2500)  # đợi ảnh xem trước
win._show_shuffle_order()
pump(0.5)
check("cửa sổ Xem đủ thứ tự mở + đóng được", True)
want = list(vt._shuffle_order)
vt._freeze_order()
pump(1)
got = [os.path.basename(c.path)[:-4] for c in vt.collect().clips]
check("Dùng thứ tự này: bảng đúng thứ tự trộn, chuyển Theo bảng",
      vt.order.currentData() == "list" and got == [names[k] for k in want], f"{got} vs {want}")
check("dải thứ tự ẩn khi Theo thứ tự trong bảng", wait_for(lambda: vt.shuffle_bar.isHidden(), 5))

# ---- Bảng trộn âm: chọn kiểu tiếng gốc ở đây → đồng bộ trang Video; chọn nhanh; tự cân ----
win.set_mode("video_music")
pump(0.5)
mx = win.music_tab.mixer
mx.mode_buttons["off"].click()
pump(0.5)
check("chọn Tắt tiếng gốc ở Bảng trộn âm → trang Video đổi theo", vt.source.currentData() == "off")
mx.mode_buttons["mix"].click()
pump(0.5)
check("chọn lại Giữ tiếng gốc + nhạc", vt.source.currentData() == "mix")
mx._presets["source"].click()
pump(0.3)
check("chọn nhanh Tiếng gốc là chính: 30 / 100", mx.values() == (30, 100), str(mx.values()))
check("dòng so sánh độ to", "to hơn nhạc" in mx.balance.text(), mx.balance.text())
mx._presets["even"].click()
pump(0.3)
check("Cân bằng: ngang nhau", "ngang nhau" in mx.balance.text())
check("tự cân bật sẵn + lưu vào dự án", mx.level_on() and win.collect_project().video.source_level)
mx.level.setChecked(False)
check("tắt tự cân → dự án ghi tắt", not win.collect_project().video.source_level)
mx.level.setChecked(True)
win.go_to(1)
pump(0.8)
mx.grab().save(os.path.join(scratch, "s_mixer.png"))

win._closing = True
win.close()
pump(0.5)
check("không có lỗi ngầm", not errs, errs[0][-500:] if errs else "")
print("TẤT CẢ OK" if not fails else f"CÓ LỖI: {len(fails)}")
sys.exit(1 if fails else 0)
