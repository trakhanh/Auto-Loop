"""Kiểm tra cửa sổ Xem trước (phát video trong app): phát, đồng bộ hình / tiếng, tua, tạm dừng, đổi âm lượng khi
đang phát, sửa dự án khi đang xem, bấm dòng thời gian để tua, Chỉ nhạc. Không hiện cửa sổ, dữ liệu riêng.

python tests/preview_check.py <thư_mục_tạm>
"""
import os
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
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
from loopstation.core.project import Project  # noqa: E402
from loopstation.ui import main_window as mw  # noqa: E402

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
        time.sleep(0.005)
    return bool(cond and cond())


from PySide6.QtCore import QSettings as _QS  # noqa: E402
from loopstation.ui.theme import APP_NAME as _APP, SETTINGS_ORG as _ORG  # noqa: E402
_QS(_ORG, _APP).setValue("ui/welcome_done", "1")  # màn hình chào: kiểm tra riêng ở look_check
win = mw.MainWindow()
win.resize(1440, 900)
win.show()
wait(1)
win._load_initial_project()
win.load_project(Project.load(os.path.join(ROOT, "Mau-Test", "Du-an-mau - Loop 70 lan.lsproj")))
wait(0.5)

frames = []
win.go_to(0)
pv = win.viewer
pl = pv.player
pl.frameReady.connect(lambda img: frames.append((time.time(), img.width(), img.height())))
pv.quality.setCurrentIndex(pv.quality.findData("fast"))  # 360p cho các phép đo bên dưới (Tự động kiểm tra sau)
check("trình phát luôn hiện ở bước Video (không cần bấm nút)", pv.isVisible() and not hasattr(win, "preview_btn"))
check("nạp xong lịch phát + hiện khung hình đầu", wait(30, lambda: pl.state == "paused" and frames),
      f"state={pl.state} frames={len(frames)}")
check("thanh tua đúng tổng thời lượng", abs(pv.slider.maximum() / 10 - pl.total) < 0.2, f"{pl.total:.1f}s")
check("khung xem trước 360p giữ tỉ lệ", frames and frames[-1][2] == 360 and frames[-1][1] == 640, str(frames[-1:]))
check("dòng thời gian cho bấm để tua", win.video_tab.timeline.seek_enabled)

# ---- phát (âm lượng 0% / 1%: kiểm tra không làm ồn loa của máy) ----
mx = win.music_tab.mixer
for sl in (mx.music, mx.source, *mx._amb_rows):
    sl.spin.setValue(0)
wait(0.3)
frames.clear()
t0 = time.time()
pl.play()
check("bắt đầu phát", wait(40, lambda: pl.state == "playing"), f"{pl.state} sau {time.time() - t0:.1f}s")
start_delay = time.time() - t0
audio = not pl.audio.disabled
print(f"     (bắt đầu sau {start_delay:.2f}s, có tiếng: {audio})")
p0, w0 = pl._now(), time.time()
wait(3)
p1, w1 = pl._now(), time.time()
check("thời gian chạy đúng nhịp thật (±15%)", abs((p1 - p0) - (w1 - w0)) < 0.15 * (w1 - w0) + 0.2,
      f"video {p1 - p0:.2f}s / thật {w1 - w0:.2f}s")
n = sum(1 for t, *_ in frames if t >= w0)
fps = float(pl.sch.fps)
check("hình chạy mượt (≥ 80% số khung)", n >= 0.8 * fps * (w1 - w0), f"{n} khung / {fps * (w1 - w0):.0f}")
check("hình khớp tiếng (khung đang hiện ~ đồng hồ)", abs(pl._shown / fps - pl._now()) < 0.25,
      f"khung {pl._shown / fps:.2f}s, đồng hồ {pl._now():.2f}s")
check("vạch trên dòng thời gian chạy theo", win.video_tab.timeline.playhead is not None
      and abs(win.video_tab.timeline.playhead - pl._now()) < 0.5)

# ---- đổi âm lượng khi đang phát: không dựng lại ----
if audio:
    gen = pl._gen
    win.music_tab.mixer.music.spin.setValue(1)
    wait(1.2)
    check("kéo âm lượng Nhạc → đổi ngay, không dựng lại", pl.audio.mixer is not None
          and abs(pl.audio.mixer.gains.get("music", 0) - 0.01) < 1e-6 and pl._gen == gen and pl.state == "playing",
          str(pl.audio.mixer.gains if pl.audio.mixer else None))

# ---- tua khi đang phát ----
target = pl.total / 2
pl.seek(target)
t_seek = time.time()
check("tua giữa video khi đang phát", wait(15, lambda: pl._seek_to is None and pl.state == "playing"
                                          and pl._shown >= 0 and abs(pl._now() - target) < 2),
      f"{pl._now():.1f} / {target:.1f}")
print(f"     (phát lại sau khi tua: {time.time() - t_seek:.2f}s)")
wait(1)
check("sau khi tua hình vẫn khớp tiếng", abs(pl._shown / fps - pl._now()) < 0.3,
      f"khung {pl._shown / fps:.2f}s, đồng hồ {pl._now():.2f}s")

# ---- tạm dừng / phát tiếp ----
pv.play_btn.click()
wait(0.3)
a = pl.pos
wait(1)
check("tạm dừng: đứng yên", pl.state == "paused" and abs(pl.pos - a) < 0.01 and "Phát" in pv.play_btn.toolTip())
pv.view.setFocus()
QTest.keyClick(pv.view, Qt.Key.Key_Space)
check("Space: phát tiếp từ chỗ dừng", wait(10, lambda: pl.state == "playing") and abs(pl._now() - a) < 1.0,
      f"{pl._now():.2f} / {a:.2f}")
pl.pause()
wait(0.2)

# ---- tua khi đang dừng: thấy đúng khung hình ----
frames.clear()
pl.seek(60)
check("tua lúc dừng → hiện khung hình mới", wait(10, lambda: bool(frames)) and pl.state == "paused")

# ---- bấm dòng thời gian ----
tlb = win.video_tab.timeline
x = tlb._x(pl.total * 0.25)
y = tlb.TOP_V + 8
QTest.mouseClick(tlb, Qt.MouseButton.LeftButton, pos=QPointF(x, y).toPoint())
wait(0.4)
check("bấm dòng thời gian → nhảy tới đó", abs(pl.pos - pl.total * 0.25) < pl.total * 0.02,
      f"{pl.pos:.1f} / {pl.total * 0.25:.1f}")
# kéo vạch phát trên thước giờ (như CapCut): hình chạy theo khi kéo
frames.clear()
ry = int(tlb._ruler_y()) + 4
QTest.mousePress(tlb, Qt.MouseButton.LeftButton, pos=QPointF(tlb._x(pl.total * 0.3), ry).toPoint())
for k in range(1, 8):
    QTest.mouseMove(tlb, QPointF(tlb._x(pl.total * (0.3 + 0.05 * k)), ry).toPoint())
    wait(0.15)
QTest.mouseRelease(tlb, Qt.MouseButton.LeftButton, pos=QPointF(tlb._x(pl.total * 0.65), ry).toPoint())
wait(0.8)
check("kéo vạch phát → tua theo + hiện hình trong lúc kéo", abs(pl.pos - pl.total * 0.65) < pl.total * 0.02
      and len(frames) >= 3, f"{pl.pos:.1f} / {pl.total * 0.65:.1f}, {len(frames)} khung")

# ---- sửa dự án khi đang xem: tự cập nhật, giữ chỗ ----
before = pl.pos
gen = pl._gen
win._preview_sig = ""  # giả lập dự án vừa đổi (dấu cũ khác dấu hiện tại)
win._preview_timer.start()
check("sửa dự án → bản xem trước tự dựng lại", wait(15, lambda: pl._gen != gen and pl.state == "paused"))
check("dựng lại vẫn giữ chỗ đang xem", abs(pl.pos - before) < 0.5, f"{pl.pos:.1f} / {before:.1f}")

win.grab().save(os.path.join(scratch, "main_with_player.png"))

# ---- chất lượng 540p ----
frames.clear()
pv.quality.setCurrentIndex(pv.quality.findData("sharp"))
check("đổi 540p → khung hình 960×540", wait(20, lambda: frames and frames[-1][2] == 540), str(frames[-1:]))
frames.clear()
pv.quality.setCurrentIndex(pv.quality.findData("auto"))
want_h = 360 if pv.view.height() <= 420 else (540 if pv.view.height() <= 640 else 720)
check("chất lượng Tự động theo cỡ khung xem", wait(20, lambda: frames and frames[-1][2] == want_h),
      f"khung xem cao {pv.view.height()} → {frames[-1:]}")
pv.quality.setCurrentIndex(pv.quality.findData("fast"))
wait(0.5)
# tắt tiếng trình phát: chỉ tắt ở trình phát, không đổi âm lượng của dự án
pv.mute_btn.click()
check("nút tắt tiếng", pl.muted and win.collect_project().video.music_volume == win.music_tab.mixer.values()[0])
pv.mute_btn.click()
# bấm vào khung hình: phát / dừng
QTest.mouseClick(pv.view, Qt.MouseButton.LeftButton, pos=pv.view.rect().center())
check("bấm vào khung hình → phát", wait(15, lambda: pl.state in ("playing", "loading", "buffering")), pl.state)
QTest.mouseClick(pv.view, Qt.MouseButton.LeftButton, pos=pv.view.rect().center())
check("bấm lần nữa → dừng", wait(3, lambda: pl.state == "paused"), pl.state)
# toàn màn hình
pv.toggle_fullscreen()
wait(0.5)
fs = pv._full
check("toàn màn hình mở + có hình", fs is not None and fs.isVisible() and fs.image is not None)
QTest.keyClick(fs, Qt.Key.Key_Escape)
wait(0.5)
check("Esc thoát toàn màn hình", pv._full is None)

# ---- sang trang khác (Cài đặt) khi đang phát → dừng, trình phát ẩn ----
pl.play()
wait(10, lambda: pl.state == "playing")
win.go_to(3)
wait(0.5)
check("sang trang Cài đặt → trình phát ẩn và dừng phát", not pv.isVisible() and pl.state == "paused", pl.state)
win.go_to(0)
wait(0.5)
check("quay lại bước Video → trình phát hiện lại", pv.isVisible())

# ---- Chỉ nhạc ----
win.set_mode("music_only")
wait(1)
win.go_to(1)
check("Chỉ nhạc: nạp được", wait(30, lambda: pl.state == "paused" and pv.view.audio_only), pl.state)
check("Chỉ nhạc: khung xem hiện biểu tượng nhạc", pv.view.audio_only)
if audio:
    pl.play()
    check("Chỉ nhạc: phát được", wait(40, lambda: pl.state == "playing"), pl.state)
    q0 = pl._now()
    wait(1.5)
    check("Chỉ nhạc: thời gian chạy", pl._now() - q0 > 1.0, f"{pl._now() - q0:.2f}")
    pl.pause()
wait(0.3)

# ---- Xuất hàng loạt: chuột phải một dòng → Xem trước video này ----
from PySide6.QtCore import QSettings  # noqa: E402
from loopstation.ui.batch_dialog import BatchDialog  # noqa: E402
win.set_mode("video_music")
wait(0.5)
st = QSettings(os.path.join(scratch, "b.ini"), QSettings.Format.IniFormat)
st.setValue("batch/folder", os.path.join(ROOT, "Mau-Test", "Hang-loat"))
tpl = win.collect_project()
tpl.export.output_dir = os.path.join(scratch, "out")
bd = BatchDialog(tpl, st)
bd.show()
wait(1.5)
bd._watch(1)
bp = bd.player_panel
check("hàng loạt: trình phát nhúng hiện đúng video của dòng", bp.isVisible()
      and bd.jobs[1].name.upper() in bp.title.text(), bp.title.text())
check("hàng loạt: phát được", wait(30, lambda: bp.player.state == "playing"), bp.player.state)
bd.tree.setFocus()
QTest.keyClick(bd.tree, Qt.Key.Key_Space)
check("hàng loạt: Space ở danh sách → dừng (không bỏ tick dòng)", wait(3, lambda: bp.player.state == "paused")
      and bd.tree.topLevelItem(1).checkState(0) == Qt.CheckState.Checked, bp.player.state)
bd.done(0)
wait(0.3)
check("đóng hộp thoại hàng loạt → dừng hẳn trình phát", bp.player.state == "empty")
check("không có lỗi ngầm", not errs, errs[0][-1200:] if errs else "")
print("TẤT CẢ OK" if ok else "CÓ LỖI")
sys.exit(0 if ok else 1)
