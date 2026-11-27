"""Quy trình hàng đợi: tên file tự gợi ý "Tập 33", thêm → hộp đặt tên → hộp "bước tiếp theo" → Video mới bảng trống,
báo thêm trùng, Sửa mục này → Cập nhật đúng mục, chi tiết mục; Trộn bản mới giữ nguyên clip (clip ghim giữ chỗ), thêm
nhiều bản trộn một lượt, đổi tên mục. Chụp ảnh trang Xuất + hộp thoại vào thư mục tạm.

python tests/queue_flow_check.py <thư_mục_tạm>
"""
import os
import shutil
import subprocess
import sys
import time
import traceback
import warnings
from pathlib import Path

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
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QLineEdit, QSpinBox  # noqa: E402

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


seen_names = []  # chữ điền sẵn trong hộp đặt tên, theo thứ tự hiện


def answers(*steps):
    """Nhiều hộp thoại modal nối nhau: mỗi bước (chữ trên nút, ảnh chụp, điền) — `điền` là chữ cho ô tên hoặc số cho ô
    số bản. Hộp có ô tên thì ghi lại tên gợi ý vào `seen_names`."""
    todo = list(steps)

    def go(prev=None):
        if not todo:
            return
        box = QApplication.activeModalWidget()
        if box is None or box is prev:
            QTimer.singleShot(100, lambda: go(prev))
            return
        text, shot, fill = (list(todo.pop(0)) + [None, None])[:3]
        edits = [e for e in box.findChildren(QLineEdit) if not isinstance(e.parent(), QSpinBox)]  # bỏ ô chữ của ô số
        if edits:
            seen_names.append(edits[0].text())
        if isinstance(fill, str) and edits:
            edits[0].setText(fill)
        spins = box.findChildren(QSpinBox)
        if isinstance(fill, int) and spins:
            spins[0].setValue(fill)
        if shot:
            box.grab().save(os.path.join(scratch, shot))

        def says(b):
            return text in b.text().replace("&", "") or any(text in lab.text() for lab in b.findChildren(QLabel))
        btn = next((b for b in box.findChildren(QAbstractButton) if says(b)), None)
        print(f"     [hộp “{box.windowTitle()}”] → {text if btn else 'không thấy nút, đóng'}")
        (btn.click if btn else box.reject)()
        QTimer.singleShot(150, lambda: go(box))
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

answers(("Thêm vào hàng đợi", "q_name.png"), ("Video mới", "q_added.png"))
win.add_to_queue("video")
pump(0.8)
check("thêm 1 mục", len(win.queue) == 1)
it = win.queue[0] if win.queue else None
check("tóm tắt có tập + tình huống + số dòng", it is not None and "Tập 33" in it.summary
      and "tình huống 1 → 2" in it.summary and "4 dòng" in it.summary, it.summary if it else "")
check("tên file đầu ra là Tập 33", it is not None and os.path.basename(it.output) == "Tập 33.mp4",
      it.output if it else "")
check("hộp đặt tên gợi ý Tập 33", seen_names[:1] == ["Tập 33"], str(seen_names))
check("Video mới, bảng trống: bảng trống, tên trống", not win.video_tab.collect().clips
      and win.export_tab.filename.text() == "")

proj2 = win.collect_project()
proj2.video.clips = table(34)
win.load_project(proj2)
win.recompute()
pump(1.5)
check("tập 34 gợi ý Tập 34", win.export_tab.filename.text() == "Tập 34", win.export_tab.filename.text())
answers(("Thêm vào hàng đợi",), ("Ở lại",))
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

# ---- Trộn bản mới giữ nguyên clip: 8 clip trộn ngẫu nhiên, clip thứ 3 ghim ----
from loopstation.core import planner, timeline  # noqa: E402
win.queue.clear()
win.export_tab.set_queue(win.queue)
mix = Project(name="Trộn", output_kind="video_only")
mix.video.clips = [ClipItem(os.path.join(media, f"{e}_{n}_LOOP {r}.mp4")) for e in (33, 34) for n in (1, 2) for r in "AB"]
mix.video.order, mix.video.seed = "shuffle", 11
mix.export.output_dir = os.path.join(scratch, "out_mix")
win.load_project(mix)
win.recompute()
pump(1.5)
vt = win.video_tab
seen_names.clear()
vt._toggle_pin(vt.list.items()[2])
pump(0.5)
sub = vt.list.items()[2].data(0, mw.w.ROLE_SUB) or ""
check("dòng ghim ghi vị trí 3", "Ghim · vị trí 3" in sub, sub)
check("ghim vào dự án", [c.pinned for c in win.collect_project().video.clips] == [False, False, True] + [False] * 5)
answers(("Huỷ",))
win.add_to_queue("video")
pump(0.8)
check("huỷ hộp tên: không thêm", len(win.queue) == 0, str(len(win.queue)))
answers(("Thêm vào hàng đợi",), ("Trộn bản mới", "q_remix_dialog.png"))
win.add_to_queue("video")
pump(1.5)
check("tên gợi ý khi trống là Bản trộn 1", seen_names[-1:] == ["Bản trộn 1"], str(seen_names))
check("mục 1 tên Bản trộn 1", len(win.queue) == 1 and Path(win.queue[0].output).stem == "Bản trộn 1",
      [i.output for i in win.queue])
cur = win.collect_project()
check("Trộn bản mới: giữ đủ 8 clip + ghim", len(cur.video.clips) == 8 and cur.video.clips[2].pinned)
check("Trộn bản mới: đổi số mầm", cur.video.seed != 11, str(cur.video.seed))
check("Trộn bản mới: tên Bản trộn 2", win.export_tab.filename.text() == "Bản trộn 2", win.export_tab.filename.text())
answers(("Thêm vào hàng đợi",), ("Thêm nhiều bản", "", 3))
win.add_to_queue("video")
pump(3)
names = [Path(i.output).stem for i in win.queue]
check("thêm bản 2 + 3 bản trộn: tên tự tăng", names == ["Bản trộn 1", "Bản trộn 2", "Bản trộn 3", "Bản trộn 4",
                                                       "Bản trộn 5"], str(names))
check("không bị hỏi trùng (khác số mầm)", len(win.queue) == 5)
seeds = [i.project.video.seed for i in win.queue]
check("mỗi bản một số mầm", len(set(seeds)) == 5, str(seeds))
orders = []
for i in win.queue:
    tl = timeline.build(i.project)
    orders.append([c for c, _n in planner.round_order(tl.video)] if tl.ok and tl.video else [])
check("clip ghim đứng thứ 3 ở mọi bản", all(len(o) == 8 and o[2] == 2 for o in orders), str(orders))
check("các bản khác thứ tự", len({tuple(o) for o in orders}) == 5)
et.queue.clearSelection()
et.queue.topLevelItem(4).setSelected(True)
pump(0.3)
check("chi tiết mục có số mầm + clip ghim", "số mầm" in et.q_detail.text() and "1 clip ghim" in et.q_detail.text(),
      et.q_detail.text()[-300:])
check("nút Đổi tên bật", et.q_rename_btn.isEnabled())
answers(("Đổi tên", "q_rename.png", "Bản đặc biệt"))
et._rename_selected()
pump(0.8)
check("đổi tên mục", Path(win.queue[4].output).stem == "Bản đặc biệt"
      and win.queue[4].project.export.filename == "Bản đặc biệt", win.queue[4].output)
answers(("Đổi tên", "", "Bản trộn 1"), ("OK",))
et._rename_selected()
pump(0.8)
check("đổi trùng tên mục khác bị chặn", Path(win.queue[4].output).stem == "Bản đặc biệt", win.queue[4].output)
win.go_to(2)
pump(0.5)
et.q_detail_box.parentWidget().grab().save(os.path.join(scratch, "q_remix_queue.png"))

# ---- clip mở đầu: đánh dấu 3 clip (A = dòng 5, B = dòng 7, C = dòng 2) → mỗi bản mở đầu một clip ----
vt.list.clearSelection()
rows = vt.list.items()
lead_paths = [rows[k].data(0, mw.w.ROLE_DATA).path for k in (4, 6, 1)]
pin_path = rows[2].data(0, mw.w.ROLE_DATA).path
for k in (4, 6, 1):
    vt._toggle_opener(vt.list.items()[k])
pump(0.5)
sub = vt.list.items()[4].data(0, mw.w.ROLE_SUB) or ""
check("dòng mở đầu ghi Mở đầu · 1/3", "Mở đầu · 1/3" in sub, sub)
win.remix_next()  # bảng đang mở trùng "Bản trộn 2" đã thêm → trộn bản mới: clip mở đầu A lên đầu
pump(1)
c0 = win.collect_project().video.clips[0]
check("Trộn bản mới: clip mở đầu A lên dòng 1 + ghim", c0.path == lead_paths[0] and c0.pinned, Path(c0.path).stem)
before = len(win.queue)
answers(("Thêm vào hàng đợi",), ("Thêm nhiều bản", "q_opener_dialog.png"))
win.add_to_queue("video")
pump(3)
new = win.queue[before:]
check("thêm bản A + 2 bản B, C (số bản gợi ý = clip mở đầu chưa dùng)", len(new) == 3, str(len(new)))
firsts, pins_ok = [], True
for i in new:
    tl = timeline.build(i.project)
    o = [c for c, _n in planner.round_order(tl.video)] if tl.ok and tl.video else []
    firsts.append(i.project.video.clips[o[0]].path if o else "")
    pins_ok = pins_ok and len(o) == 8 and i.project.video.clips[o[2]].path == pin_path
check("mỗi bản mở đầu đúng A, B, C", firsts == lead_paths, str([Path(f).stem for f in firsts]))
check("clip ghim vị trí 3 vẫn giữ chỗ", pins_ok)
check("tóm tắt ghi mở đầu", all("mở đầu" in i.summary for i in new), str([i.summary for i in new]))
win.remix_next()
pump(1)
c0 = win.collect_project().video.clips[0]
check("Trộn bản mới lần nữa: sang clip mở đầu B", c0.path == lead_paths[1] and c0.pinned, Path(c0.path).stem)

win._closing = True
win.close()
pump(0.5)
check("không có lỗi ngầm", not errs, errs[0][-400:] if errs else "")
print("TẤT CẢ OK" if not fails else f"CÓ LỖI: {len(fails)}")
sys.exit(1 if fails else 0)
