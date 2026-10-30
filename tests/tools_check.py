"""Kiểm tra 1.8.6: nơi đặt bộ nhớ đệm + cảnh báo ổ đầy, hồ sơ kênh, xuất / nhập mẫu ra file, hàng đợi báo giờ xong
+ tạm dừng / chạy tiếp + thông báo. Chụp ảnh vào thư mục tạm.

python tests/tools_check.py <thư_mục_tạm>
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
from PySide6.QtWidgets import QAbstractButton, QApplication, QFileDialog, QInputDialog, QLabel  # noqa: E402

app = QApplication([])
from loopstation.core import ffmpeg_tools as ft  # noqa: E402
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
import loopstation.ui.main_window as mw  # noqa: E402
from loopstation.core.project import ClipItem, MusicTrack, Project  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("OK   " if ok else "LỖI ") + name + (f"  ({extra})" if extra and not ok else ""))
    if not ok:
        fails.append(name)


def pump(t=0.3):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()


def wait_for(cond, t=60.0):
    end = time.time() + t
    while time.time() < end and not cond():
        app.processEvents()
    return cond()


def answer(text, shot="", delay=200):
    def go():
        box = QApplication.activeModalWidget()
        if box is None or getattr(box, "_answered", False):
            QTimer.singleShot(100, go)
            return
        box._answered = True
        if shot:
            box.grab().save(os.path.join(scratch, shot))
        btn = next((b for b in box.findChildren(QAbstractButton)
                    if text in b.text().replace("&", "") or any(text in x.text() for x in b.findChildren(QLabel))), None)
        (btn.click if btn else box.reject)()
    QTimer.singleShot(delay, go)


media = os.path.join(scratch, "media")
shutil.rmtree(media, ignore_errors=True)
os.makedirs(os.path.join(media, "nhac"))
src = os.path.join(media, "c.mp4")
subprocess.run([ft.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=2", "-f", "lavfi",
                "-i", "sine=d=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", src], check=True)
for nm in ("intro", "outro", "1_LOOP A", "1_LOOP B"):
    shutil.copy(src, os.path.join(media, nm + ".mp4"))
for k in range(3):
    subprocess.run([ft.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={300 + k * 100}:d=3",
                    os.path.join(media, "nhac", f"bai {k + 1}.mp3")], check=True)

ini = os.path.join(scratch, "settings.ini")
st = QSettings(ini, QSettings.Format.IniFormat)
st.clear()
st.setValue("ui/welcome_done", "1")
st.sync()
mw.QSettings = lambda o, n: QSettings(ini, QSettings.Format.IniFormat)
mw.MainWindow._confirm_sample_bookends = lambda self: True
notices = []
mw.MainWindow._windows_notice = lambda self, t, x: notices.append((t, x))
win = mw.MainWindow()
win.resize(1500, 950)
win.show()
win.queue.clear()
win.export_tab.set_queue(win.queue)
pump(1)
sp = win.settings_page

# ---- 2. bộ nhớ đệm: đổi chỗ + cảnh báo ổ đầy ----
new_cache = os.path.join(scratch, "cache-moi")
answer("giữ chỗ cũ")
sp._set_cache_dir(new_cache)
pump(0.5)
check("đổi nơi lưu bộ nhớ đệm", os.path.normcase(str(ft.cache_root())) == os.path.normcase(new_cache)
      and st.value("pref/cache_dir") == new_cache and "cache-moi" in sp.cache_where.toolTip() + sp.cache_where.text(),
      f"{ft.cache_root()} · {st.value('pref/cache_dir')}")
real_free = ft.disk_free
ft.disk_free = lambda p: 2 * 1024 ** 3
win._check_disk()
pump(0.3)
check("ổ còn 2 GB → dải cảnh báo hiện", not win.disk_banner.isHidden() and "2.0 GB" in win.disk_text.text(),
      win.disk_text.text())
win.go_to(3)
pump(0.5)
win.grab().save(os.path.join(scratch, "t_disk.png"))
ft.disk_free = real_free
win._check_disk()
check("đủ chỗ → dải cảnh báo ẩn", win.disk_banner.isHidden())
answer("giữ chỗ cũ")
sp._set_cache_dir("")
pump(0.3)
check("về mặc định", "cache-moi" not in str(ft.cache_root()))

# ---- 3. hồ sơ kênh ----
p = Project(name="Kênh A", output_kind="video_music")
p.video.clips = [ClipItem(os.path.join(media, "1_LOOP B.mp4")), ClipItem(os.path.join(media, "1_LOOP A.mp4"), count=3)]
p.video.intro, p.video.outro = os.path.join(media, "intro.mp4"), os.path.join(media, "outro.mp4")
p.music.tracks = [MusicTrack(os.path.join(media, "nhac", f"bai {k + 1}.mp3")) for k in range(2)]
p.export.output_dir = os.path.join(scratch, "out-kenh-a")
os.makedirs(p.export.output_dir, exist_ok=True)
p.export.resolution = "720p"
win.load_project(p)
pump(1)
QInputDialog.getText = staticmethod(lambda *a, **k: ("Kênh Mưa Đêm", True))
win._new_profile()
check("lưu hồ sơ kênh + nút Kênh đổi tên", "Kênh Mưa Đêm" in win.profile_btn.text())
q = win.collect_project()
q.video.intro = q.video.outro = ""
q.music.tracks = []
q.export.output_dir, q.export.resolution = "", "1080p"
win.load_project(q)
pump(0.5)
from loopstation.ui.share_io import read_profiles  # noqa: E402
prof = read_profiles(st)[0]
win._apply_profile(prof)
pump(1)
r = win.collect_project()
check("áp hồ sơ: intro / outro / nơi lưu / độ phân giải quay lại",
      r.video.intro.endswith("intro.mp4") and r.video.outro.endswith("outro.mp4")
      and r.export.output_dir.endswith("out-kenh-a") and r.export.resolution == "720p")
check("áp hồ sơ: lấy cả bài mới thêm vào thư mục nhạc (3 bài)", len(r.music.tracks) == 3, str(len(r.music.tracks)))
check("áp hồ sơ: bảng clip giữ nguyên", [c.count for c in r.video.clips] == [1, 3])
from loopstation.ui.profiles_dialog import ProfileDialog  # noqa: E402
dlg = ProfileDialog(st, win._capture_profile, win._apply_profile, "Kênh Mưa Đêm", win)
dlg.resize(760, 520)
dlg.show()
pump(0.6)
dlg.grab().save(os.path.join(scratch, "t_profiles.png"))
dlg.reject()

# ---- 4. xuất / nhập mẫu + hồ sơ ra file ----
from loopstation.ui import share_io  # noqa: E402
from loopstation.ui.interleave_dialog import save_table_presets, table_presets  # noqa: E402
from loopstation.core import table_preset as tp  # noqa: E402
save_table_presets(st, [{"name": "Mẫu của tôi", "rows": tp.from_clips(p.video.clips)}])
path = os.path.join(scratch, "chia-se.ktls")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (path, ""))
answer("OK")
share_io.export_file(win, st)
check("xuất ra file .ktls", os.path.isfile(path))
st.remove("table/presets")
st.remove("profiles/list")
answer("OK")
share_io.import_file(win, st, path)
check("nhập lại: có mẫu + hồ sơ", [x["name"] for x in table_presets(st)] == ["Mẫu của tôi"]
      and [x["name"] for x in read_profiles(st)] == ["Kênh Mưa Đêm"])
answer("Giữ cả hai", "", 200)
QTimer.singleShot(1500, lambda: answer("OK"))
share_io.import_file(win, st, path)
pump(0.5)
names = sorted(x["name"] for x in table_presets(st))
check("nhập trùng tên → giữ cả hai", names == ["Mẫu của tôi", "Mẫu của tôi (nhập)"], str(names))

# ---- 5. hàng đợi: giờ xong, tạm dừng, chạy tiếp, thông báo ----
v = Project(name="q", output_kind="video_only")
v.video.clips = [ClipItem(src, count=2)]
v.export.output_dir = os.path.join(scratch, "out-q")
v.export.encoder = "cpu"
win.load_project(v)
pump(1)
st.setValue("perf/ratio", 0.5)
from loopstation.core import render_queue as rq  # noqa: E402
for k in range(3):
    pk = win.collect_project()
    pk.export.filename = f"video {k + 1}"
    win.queue.append(rq.QueueItem(project=pk, output=os.path.join(v.export.output_dir, f"video {k + 1}.mp4"),
                                  kind="video", summary="thử", seconds=600))
win.export_tab.set_queue(win.queue)
win._save_queue()
pump(0.3)
eta = win.export_tab.q_eta.text()
check("giờ xong: còn 3 video · ~15 phút · xong khoảng", "3 video" in eta and "~15 phút" in eta and "xong khoảng" in eta,
      eta)
check("mỗi mục ghi ước tính", "~5 phút" in win.export_tab.queue.topLevelItem(0).text(3))
win.go_to(2)
pump(0.5)
win.export_tab.q_eta.parentWidget().grab().save(os.path.join(scratch, "t_queue.png"))
for it in win.queue:
    it.seconds = 40  # (video thử thật chỉ 4 giây; > 30 giây để app đo tốc độ)
win.run_queue()
pump(0.3)
check("nút Tạm dừng hiện khi chạy hàng đợi", win.export_tab.q_pause_btn.isVisibleTo(win.export_tab))
win.export_tab.q_pause_btn.click()
check("chạy 1 video rồi dừng, còn 2 chờ",
      wait_for(lambda: not win._queue_running and win.job is None, 120)
      and [i.status for i in win.queue] == ["done", "pending", "pending"], str([i.status for i in win.queue]))
answer("OK", delay=500)
win.run_queue()
check("Chạy tiếp → xong cả 3", wait_for(lambda: all(i.status == "done" for i in win.queue) and win.job is None, 180))
pump(1.5)
check("thông báo Windows khi xong", any("Hàng đợi xong" in t for t, _x in notices), str(notices))
check("đã đo tốc độ máy", float(st.value("perf/ratio", 0)) != 0.5)

win._closing = True
win.close()
pump(0.3)
check("không có lỗi ngầm", not errs, errs[0][-500:] if errs else "")
print("TẤT CẢ OK" if not fails else f"CÓ LỖI: {len(fails)}")
sys.exit(1 if fails else 0)
