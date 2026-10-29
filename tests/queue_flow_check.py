"""Quy trình hàng đợi: tên file tự gợi ý "Tập 33", thêm → hộp "bước tiếp theo" → Làm video tiếp theo, báo thêm trùng,
Sửa mục này → Cập nhật đúng mục, chi tiết mục. Chụp ảnh trang Xuất + hộp thoại vào thư mục tạm.

python tests/queue_flow_check.py <thư_mục_tạm>
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
from loopstation.core.project import ClipItem, Project  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("OK   " if ok else "LỖI ") + name + (f"  ({extra})" if extra and not ok else ""))
    if not ok:
        fails.append(name)


def pump(t=0.3):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()


def answer(text, shot=""):
    """Hộp thoại modal sắp hiện: chụp ảnh (nếu cần) rồi bấm nút có chữ `text`."""
    def go():
        box = QApplication.activeModalWidget()
        if box is None:
            QTimer.singleShot(100, go)
            return
        if shot:
            box.grab().save(os.path.join(scratch, shot))
        def says(b):  # nút thường: chữ của nút; nút thẻ (Làm video tiếp theo…): chữ ở nhãn con
            return text in b.text().replace("&", "") or any(text in lab.text() for lab in b.findChildren(QLabel))
        btn = next((b for b in box.findChildren(QAbstractButton) if says(b)), None)
        (btn.click if btn else box.reject)()
    QTimer.singleShot(150, go)


media = os.path.join(scratch, "media")
shutil.rmtree(media, ignore_errors=True)
os.makedirs(media)
src = os.path.join(media, "c.mp4")
subprocess.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", src], check=True)
for e in (33, 34):
    for n in (1, 2):
        for r in "AB":
            shutil.copy(src, os.path.join(media, f"{e}_{n}_LOOP {r}.mp4"))


def table(ep):
    return [ClipItem(os.path.join(media, f"{ep}_{n}_LOOP {r}.mp4"), count=57 if r == "A" else 1)
            for n in (1, 2) for r in "BA"]


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
pump(1)

proj = Project(name="Mùa 3", output_kind="video_only")
proj.video.clips = table(33)
proj.export.output_dir = os.path.join(scratch, "out")
win.load_project(proj)
win.recompute()
pump(1.5)
check("tên file tự gợi ý Tập 33", win.export_tab.filename.text() == "Tập 33", win.export_tab.filename.text())

answer("Làm video tiếp theo", "q_added.png")
win.add_to_queue("video")
pump(0.8)
check("thêm 1 mục", len(win.queue) == 1)
it = win.queue[0] if win.queue else None
check("tóm tắt có tập + tình huống + số dòng", it is not None and "Tập 33" in it.summary
      and "tình huống 1 → 2" in it.summary and "4 dòng" in it.summary, it.summary if it else "")
check("tên file đầu ra là Tập 33", it is not None and os.path.basename(it.output) == "Tập 33.mp4",
      it.output if it else "")
check("Làm video tiếp theo: bảng trống, tên trống", not win.video_tab.collect().clips
      and win.export_tab.filename.text() == "")

proj2 = win.collect_project()
proj2.video.clips = table(34)
win.load_project(proj2)
win.recompute()
pump(1.5)
check("tập 34 gợi ý Tập 34", win.export_tab.filename.text() == "Tập 34", win.export_tab.filename.text())
answer("Ở lại")
win.add_to_queue("video")
pump(0.8)
check("thêm mục thứ 2", len(win.queue) == 2)

answer("No")  # thêm trùng tập 34 → hỏi; chọn Không
win.add_to_queue("video")
pump(0.8)
check("thêm trùng bị hỏi, chọn Không thì không thêm", len(win.queue) == 2, str(len(win.queue)))

et = win.export_tab
et.queue.topLevelItem(0).setSelected(True)
pump(0.3)
check("chi tiết mục có nơi lưu + bảng", "Lưu tại" in et.q_detail.text() and "33_1_LOOP B" in et.q_detail.text())
win.go_to(2)
pump(0.8)
et.q_detail_box.parentWidget().grab().save(os.path.join(scratch, "q_export.png"))

answer("Yes")
et._edit_selected()
pump(1.5)
check("Sửa mục này: nạp lại tập 33", [os.path.basename(c.path) for c in win.video_tab.collect().clips][:1]
      == ["33_1_LOOP B.mp4"])
check("nút Thêm thành Cập nhật", et.queue_add_btn.text().startswith("Cập nhật"), et.queue_add_btn.text())
check("hàng đợi ghi Đang sửa", et.queue.topLevelItem(0).text(3) == "Đang sửa")
check("dải Đang sửa hiện", win.edit_banner.isVisible() and "Tập 33" in win.edit_text.text())
win.go_to(2)
pump(0.5)
win.grab().save(os.path.join(scratch, "q_editing.png"))
et.q_detail_box.parentWidget().grab().save(os.path.join(scratch, "q_editing_queue.png"))
p = win.collect_project()
p.video.clips = p.video.clips[:2]
win.load_project(p, editing=win.queue[0])
win.recompute()
pump(1)
win.add_to_queue("video")
pump(0.8)
check("Cập nhật: vẫn 2 mục, mục 1 còn 2 dòng", len(win.queue) == 2 and "2 dòng" in win.queue[0].summary,
      win.queue[0].summary)
check("Cập nhật: giữ tên Tập 33", os.path.basename(win.queue[0].output) == "Tập 33.mp4", win.queue[0].output)
check("hết chế độ sửa", et.queue_add_btn.text() == "Thêm vào hàng đợi" and win._editing_item is None)
check("dải Đang sửa ẩn sau khi cập nhật", not win.edit_banner.isVisible())
et.queue.clearSelection()
et.queue.topLevelItem(1).setSelected(True)
answer("Yes")
et._edit_selected()
pump(1)
before = (win.queue[1].summary, win.queue[1].output)
win._cancel_edit()
pump(0.3)
check("Huỷ sửa: mục giữ nguyên, dải ẩn, nút về Thêm", (win.queue[1].summary, win.queue[1].output) == before
      and not win.edit_banner.isVisible() and et.queue_add_btn.text() == "Thêm vào hàng đợi")

win._closing = True
win.close()
pump(0.5)
check("không có lỗi ngầm", not errs, errs[0][-400:] if errs else "")
print("TẤT CẢ OK" if not fails else f"CÓ LỖI: {len(fails)}")
sys.exit(1 if fails else 0)
