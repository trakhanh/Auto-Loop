"""Lưu phiên: tự lưu vài giây sau khi đổi + giữ 5 bản lưu dự phòng; app bị tắt ngang → mở lại báo đã khôi phục;
hàng đợi đang chạy mà app tắt ngang → mở lại hỏi chạy tiếp (đếm ngược tự chạy), Để sau thì giữ nguyên hàng đợi;
đóng app đúng cách thì lần sau không báo gì. Chụp ảnh dải báo + hộp hỏi vào thư mục tạm.

python tests/session_check.py <thư_mục_tạm>
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

from PySide6.QtCore import QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel  # noqa: E402

app = QApplication([])
from loopstation.core import ffmpeg_tools, render_queue as rq  # noqa: E402
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
import loopstation.ui.main_window as mw  # noqa: E402
from loopstation.core.project import ClipItem, Project  # noqa: E402
from loopstation.ui.queue_dialogs import ResumeQueueDialog  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("OK   " if ok else "LỖI ") + name + (f"  ({extra})" if extra and not ok else ""))
    if not ok:
        fails.append(name)


def pump(t=0.3):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()


def answer(text, shot="", seen=None):
    """Hộp thoại modal sắp hiện: chụp ảnh (nếu cần), ghi lại chữ trên hộp rồi bấm nút có chữ `text`."""
    def go():
        box = QApplication.activeModalWidget()
        if box is None:
            QTimer.singleShot(100, go)
            return
        if shot:
            box.grab().save(os.path.join(scratch, shot))
        if seen is not None:
            seen.append(" ".join(lab.text() for lab in box.findChildren(QLabel)))

        def says(b):
            return text in b.text().replace("&", "") or any(text in lab.text() for lab in b.findChildren(QLabel))
        btn = next((b for b in box.findChildren(QAbstractButton) if says(b)), None)
        (btn.click if btn else box.reject)()
    QTimer.singleShot(150, go)


data = os.environ["KTLS_DATA_DIR"]
shutil.rmtree(data, ignore_errors=True)
os.makedirs(data)
ini = os.path.join(scratch, "settings.ini")
_st = QSettings(ini, QSettings.Format.IniFormat)
_st.clear()
_st.setValue("ui/welcome_done", "1")
_st.sync()
mw.QSettings = lambda org, name: QSettings(ini, QSettings.Format.IniFormat)
flag = os.path.join(data, mw.SESSION_FLAG)
auto = os.path.join(data, mw.AUTOSAVE)
backups = os.path.join(data, mw.BACKUP_DIR)


def new_window(run_calls=None):
    win = mw.MainWindow()
    if run_calls is not None:
        win.run_queue = lambda only=None: run_calls.append(1)  # không xuất thật — chỉ cần biết có chạy tiếp
    win.resize(1500, 950)
    win.show()
    pump(1)
    return win


def clips(n):
    return [ClipItem(os.path.join(scratch, f"clip{i}.mp4"), count=2) for i in range(n)]


# ---------- 1) tự lưu liên tục ----------
win = new_window([])
check("mở app: tạo cờ phiên đang mở", os.path.isfile(flag))
check("lần đầu mở: không báo khôi phục", win.restore_banner.isHidden())
proj = Project(name="Tự lưu", output_kind="video_only")
proj.video.clips = clips(3)
win.load_project(proj)
win.recompute()
pump(mw.AUTOSAVE_DELAY_MS / 1000 + 1.0)
check("đổi dự án → vài giây sau đã tự lưu", os.path.isfile(auto) and len(Project.load(auto).video.clips) == 3)
first = os.path.getmtime(auto)
pump(mw.AUTOSAVE_DELAY_MS / 1000 + 0.5)
win.recompute()
pump(mw.AUTOSAVE_DELAY_MS / 1000 + 0.5)
check("không đổi gì thì không ghi lại", os.path.getmtime(auto) == first)
for n in range(4, 11):  # 7 lần đổi, mỗi lần cách > 1 giây (tên bản lưu theo giây)
    win._last_backup = 0.0  # giả như đã qua 2 phút
    p = win.collect_project()
    p.video.clips = clips(n)
    win.load_project(p)
    win.recompute()
    pump(mw.AUTOSAVE_DELAY_MS / 1000 + 0.6)
kept = sorted(os.listdir(backups)) if os.path.isdir(backups) else []
check("giữ đúng 5 bản lưu dự phòng gần nhất", len(kept) == mw.BACKUP_KEEP, str(kept))
check("bản lưu dự phòng mới nhất = dự án hiện tại",
      bool(kept) and len(Project.load(os.path.join(backups, kept[-1])).video.clips) == 10)
win._last_backup = time.time()
p = win.collect_project()
p.video.clips = clips(11)
win.load_project(p)
win.recompute()
pump(mw.AUTOSAVE_DELAY_MS / 1000 + 0.6)
check("bản tự lưu luôn mới, bản dự phòng tối đa 2 phút/lần",
      len(Project.load(auto).video.clips) == 11 and sorted(os.listdir(backups)) == kept)

# ---------- 2) app bị tắt ngang lúc hàng đợi đang chạy ----------
q = []
for i in range(3):
    pj = Project(name=f"Tập {i}", output_kind="video_only")
    pj.video.clips = clips(2)
    q.append(rq.QueueItem(pj, os.path.join(scratch, "out", f"Tập {40 + i}.mp4"), summary=f"Tập {40 + i}"))
q[0].status = "done"
q[1].status = "running"  # đang xuất dở thì mất điện
win.queue[:] = q
win._save_queue()
win.settings.setValue("queue/was_running", "running")
win.settings.sync()
win._initial_loaded = False  # "chết" luôn: không đóng, không lưu thêm gì
win._autosave_timer.stop()
win.hide()
check("tắt ngang: cờ phiên vẫn còn", os.path.isfile(flag))

runs, seen = [], []
answer("Chạy tiếp ngay", "resume_dialog.png", seen)
win2 = new_window(runs)
win2._on_encoders(dict(win2.export_tab.available) if hasattr(win2.export_tab, "available") else {})
pump(3.5)
check("mở lại: báo đã khôi phục dự án", not win2.restore_banner.isHidden()
      and "tắt đột ngột" in win2.restore_text.text(), win2.restore_text.text())
win2.restore_banner.grab().save(os.path.join(scratch, "restore_banner.png"))
check("mở lại: dự án = bản tự lưu", len(win2.collect_project().video.clips) == 11)
check("hỏi chạy tiếp, nói còn 2 video", bool(seen) and "2 video" in seen[0] and "Tập 41" in seen[0],
      seen[0] if seen else "không thấy hộp")
check("bấm Chạy tiếp ngay → chạy hàng đợi", runs == [1], str(runs))
check("mục đang xuất dở trở lại chờ", [i.status for i in win2.queue] == ["done", "pending", "pending"],
      str([i.status for i in win2.queue]))
check("đã hỏi thì xoá cờ hàng đợi", str(win2.settings.value("queue/was_running", "")) == "")
win2._on_encoders({})
pump(2)
check("tìm lại card đồ hoạ không hỏi lần 2", runs == [1])

# ---------- 3) đếm ngược tự chạy ----------
t0 = time.time()
dlg = ResumeQueueDialog(["Tập 41", "Tập 42"], 2)
check("hộp hỏi hiện đếm ngược", "2 giây" in dlg.count.text(), dlg.count.text())
dlg.exec()
check("hết giờ tự chạy tiếp", dlg.run and 1.5 < time.time() - t0 < 4, f"{time.time() - t0:.1f}s")

# ---------- 4) đóng đúng cách → lần sau không báo; Để sau → giữ hàng đợi ----------
win2.close()
pump(0.5)
check("đóng đúng cách: xoá cờ phiên", not os.path.isfile(flag))
win2.settings.setValue("queue/was_running", "running")  # giả: đang chạy thì máy tự khởi động lại
win2.settings.sync()
open(flag, "w").write("x")
runs3, seen3 = [], []
answer("Để sau", "", seen3)
win3 = new_window(runs3)
win3._on_encoders({})
pump(3)
check("Để sau: không chạy, hàng đợi giữ nguyên", runs3 == [] and bool(seen3)
      and [i.status for i in win3.queue].count("pending") == 2)
win3.close()
pump(0.5)
runs4 = []
win4 = new_window(runs4)
win4._on_encoders({})
pump(3)
check("lần mở sau đóng đúng cách: không báo khôi phục", win4.restore_banner.isHidden())
check("không hỏi chạy tiếp nữa", QApplication.activeModalWidget() is None and runs4 == [])
win4.close()
pump(0.3)

check("không lỗi ngầm", not errs, "\n".join(errs)[:1500])
print("TẤT CẢ OK" if not fails else f"{len(fails)} LỖI: {fails}")
sys.exit(1 if fails else 0)
