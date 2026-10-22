"""Chụp ảnh minh hoạ có đánh số ①②③ cho trang Hướng dẫn trong app (không hiện cửa sổ, dữ liệu riêng).

python tests/make_help_images.py      → loopstation/ui/assets/help/*.png
Toạ độ số lấy từ vị trí thật của từng nút → giao diện đổi thì chạy lại là ảnh khớp.
"""
import os
import sys
import tempfile
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "loopstation" / "ui" / "assets" / "help"
OUT.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="ktls_help_"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
os.environ["KTLS_DATA_DIR"] = str(tmp / "data")
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore", DeprecationWarning)

from PySide6.QtCore import QPoint, QRect, QRectF, QSettings, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication, QGroupBox  # noqa: E402

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
BADGE = QColor("#f59e0b")
MAX_W = 1200


def wait(sec: float) -> None:
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.02)


def rect_in(widget, top) -> QRect:
    p = widget.mapTo(top, QPoint(0, 0))
    return QRect(p, widget.size())


def shoot(top, marks, name: str, crop: QRect | None = None) -> None:
    """marks: [(widget hoặc QRect, số)] — khung viền cam + vòng số ở góc trên trái."""
    img = top.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont("Segoe UI", 11)
    f.setBold(True)
    p.setFont(f)
    for target, num in marks:
        r = target if isinstance(target, QRect) else rect_in(target, top)
        p.setPen(QPen(BADGE, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(r).adjusted(1, 1, -1, -1), 8, 8)
        # vòng số nằm ngoài góc trên trái (không che chữ), nhưng không lọt ra ngoài ảnh
        c = QRectF(max(2, r.left() - 22), max(2, r.top() - 20), 28, 28)
        p.setPen(QPen(QColor("#111827"), 2))
        p.setBrush(BADGE)
        p.drawEllipse(c)
        p.setPen(QColor("#111827"))
        p.drawText(c, Qt.AlignmentFlag.AlignCenter, str(num))
    p.end()
    if crop is not None:
        img = img.copy(crop)
    if img.width() > MAX_W:
        img = img.scaledToWidth(MAX_W, Qt.TransformationMode.SmoothTransformation)
    img.save(str(OUT / f"{name}.png"), "PNG", 80)
    print("  ", name, img.width(), "x", img.height())


win = mw.MainWindow()
win.resize(1440, 900)
win.show()
wait(2)
win._load_initial_project()
wait(1)

# 1) màn hình Bắt đầu
home = win.home
shoot(win, [(home.cards["video_music"], 1), (home.cards["video_only"], 2), (home.cards["music_only"], 3),
            (home.cards["ambient"], 4), (home.cards["batch"], 5), (home.cards["open"], 6)], "home")

# 1b) màn hình chào: cách làm 3 bước + dự án mẫu
from loopstation.ui.welcome import StepCard  # noqa: E402
win.show_welcome()
wait(1.5)
ov = win._welcome
cards_ = [ov.steps_box.itemAt(i).widget() for i in range(ov.steps_box.count())
          if isinstance(ov.steps_box.itemAt(i).widget(), StepCard)]
steps_r = rect_in(cards_[0], win).united(rect_in(cards_[-1], win))
sample_btn = next(b for b in ov.findChildren(type(ov.start_btn)) if b.text().startswith("Mở dự án mẫu"))
shoot(win, [(steps_r, 1), (sample_btn, 2), (ov.start_btn, 3)], "welcome")
ov._finish()
wait(0.8)

# 2) trang Video
p = Project.load(str(ROOT / "Mau-Test" / "Du-an-mau - Loop 70 lan.lsproj"))
p.music.ambient = [AmbientLayer("builtin:rain_light", volume=60)]
win.load_project(p)
win.go_to(0)
wait(3)
vt = win.video_tab
shoot(win, [(vt.toolbar, 1), (vt.list, 2), (vt.interleave_btn, 3), (vt.bulk.parentWidget(), 4),
            (vt.right_tabs, 5), (win.timeline_wrap, 6), (win.guide, 7), (vt.next_btn, 8)], "video")

# 3) hộp thoại Xen kẽ clip nền
from loopstation.ui.interleave_dialog import InterleaveDialog  # noqa: E402
clips = vt.collect().clips
from loopstation.core.probe import probe_many  # noqa: E402
durs = {os.path.normcase(c.path): i.duration for c, i in zip(clips, probe_many([c.path for c in clips])) if i.ok}
dlg = InterleaveDialog(clips, durs, QSettings(ini, QSettings.Format.IniFormat), win)
dlg.resize(1100, 700)
dlg.show()
wait(1.5)
shoot(dlg, [(dlg.preset, 1), (dlg.base, 2), (dlg.base_plays.parentWidget(), 3), (dlg.repeat.parentWidget(), 4),
            (dlg.tree, 5), (dlg.preview, 6), (dlg.ok_btn, 7)], "interleave")
dlg.done(0)

# 4) trang Nhạc + Bảng trộn âm
win.go_to(1)
wait(2)
mt = win.music_tab
win._scroll_to(mt.mixer)
wait(1)
from loopstation.ui.music_tab import COL_VOL  # noqa: E402
hdr = mt.list.header()
vol_r = QRect(mt.list.viewport().mapTo(win, QPoint(hdr.sectionViewportPosition(COL_VOL), 0)),
              mt.list.viewport().size())
vol_r.setWidth(hdr.sectionSize(COL_VOL))
vol_r.moveTop(vol_r.top() - hdr.height())
vol_r.setHeight(vol_r.height() + hdr.height())
shoot(win, [(mt.list, 1), (vol_r, 2), (mt.schedule, 3), (mt.mixer, 4)], "music")
mx = mt.mixer
shoot(mx, [(mx.music.slider, 1), (mx.source.slider, 2)] + [(r.slider, 3) for r in mx._amb_rows[:1]]
      + [(mx.at.parentWidget(), 4), (mx.play_btn, 5)], "mixer")

# 5) tiếng nền
win._scroll_to(mt.g_amb)
wait(0.8)
shoot(mt.g_amb, [(mt.ambient, 1), (mt.a_lib, 2)], "ambient")

# 6) kiểu Chỉ nhạc: độ dài + số bản
win.set_mode("music_only")
win.go_to(1)
wait(2)
win._scroll_to(mt.g_length)
wait(0.8)
shoot(mt.g_length, [(mt.len_mode, 1), (mt.len_target_wrap, 2), (mt.versions.parentWidget(), 3)], "music_only")
win.set_mode("video_music")
wait(1)

# 7) trang Xuất
win.go_to(2)
wait(2.5)
et = win.export_tab
g_out = et.out_dir.parentWidget()
while g_out is not None and not isinstance(g_out, QGroupBox):
    g_out = g_out.parentWidget()
g_queue = et.queue.parentWidget()
shoot(win, [(et.g_video, 1), (et.size_label, 2), (g_out, 3), (et.start_btn, 4), (et.queue_add_btn, 5),
            (g_queue, 6)], "export")

# 8) Xuất hàng loạt
from loopstation.ui.batch_dialog import BatchDialog  # noqa: E402
st = QSettings(ini, QSettings.Format.IniFormat)
st.setValue("batch/folder", str(ROOT / "Mau-Test" / "Hang-loat"))
bd = BatchDialog(win.collect_project(), st, win)
bd.resize(1180, 820)
bd.show()
wait(2.5)
for _ in range(80):  # trình phát bên phải nạp xong video của dòng đầu
    wait(0.25)
    if bd.player_panel.player.state == "paused" and bd.player_panel.view.image is not None:
        break
row0 = bd._play_btns.get(0)
edit0 = bd.tree.itemWidget(bd.tree.topLevelItem(0), 5)
shoot(bd, [(bd.kind_bar, 1), (bd.folder, 2), (bd.len_mode, 3), (bd.preset, 4),
           (bd.vol_music.parentWidget(), 5), (bd.tree, 6)]
      + ([(edit0, 7)] if edit0 else []) + ([(row0, 8)] if row0 else [])
      + [(bd.player_panel, 9), (bd.ok_btn, 10)], "batch")
bd.done(0)

# 8b) Trình phát (luôn hiện bên phải bước Video / Nhạc / Xuất) + dòng thời gian ở đáy
win.go_to(0)
pv = win.viewer
for _ in range(120):  # nạp lịch phát + khung hình đầu
    wait(0.25)
    if pv.player.state == "paused" and pv.view.image is not None:
        break
pv.player.seek(pv.player.total * 0.27)
for _ in range(60):
    wait(0.25)
    if pv.player._seek_to is None and pv.view.image is not None:
        break
wait(1.0)
tlb = win.video_tab.timeline
x = int(tlb._x(tlb.playhead or 0))
head = QRect(tlb.mapTo(win, QPoint(x - 12, 0)), QSize(24, tlb.height()))
shoot(win, [(pv.view, 1), (pv.play_btn, 2), (pv.back_btn, 3), (pv.slider, 4), (head, 5), (pv.quality, 6),
            (pv.full_btn, 7)], "preview")

# 9) Cài đặt (thông số + tăng tốc)
win.go_to(3)
wait(2.5)
sp = win.settings_page
boxes = [b for b in sp.findChildren(QGroupBox) if b.title().startswith(("Thông số", "FFmpeg"))]
shoot(win, [(b, k + 1) for k, b in enumerate(boxes)], "settings")

win._closing = True
win.close()
wait(0.3)
print("Đã lưu ảnh vào", OUT)
