"""Kiểm tra các lỗi trình phát đã sửa sau đợt rà soát: video không tiếng dừng / phát tiếp, chạy tới hết video,
đổi màu không dùng hình cũ trong bộ nhớ đệm, xoá dự án thì không phát lại video cũ, nhấp đúp không bật / dừng,
nhạc nhân bản không phát 2 lần liền khi xáo. Không hiện cửa sổ, dữ liệu riêng, tắt tiếng.

python tests/player_audit_check.py <thư_mục_tạm>
"""
import copy
import os
import random
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
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
theme.apply(app, 10)
from loopstation.core import planner  # noqa: E402
from loopstation.core.project import MusicSettings, MusicTrack, Project  # noqa: E402
from loopstation.ui.preview_player import PreviewPanel  # noqa: E402

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


base = Project.load(os.path.join(ROOT, "Mau-Test", "Du-an-mau - Loop 70 lan.lsproj"))
base.video.length_mode, base.video.target_duration = "target", 30.0

panel = PreviewPanel()
panel.resize(800, 520)
panel.show()
pl = panel.player
pl.set_muted(True)
playing = ("playing", "loading", "buffering")

# ---- 1) video không có tiếng: dừng rồi phát tiếp được ----
silent = copy.deepcopy(base)
silent.music.tracks, silent.music.ambient = [], []
silent.video.source_audio = "off"
silent.video.intro = silent.video.outro = ""
panel.open_project(silent)
check("không tiếng: nạp được", wait(30, lambda: pl.state == "paused"), pl.state)
pl.play()
check("không tiếng: phát (đồng hồ theo giờ máy)", wait(15, lambda: pl.state == "playing") and pl.audio.disabled, pl.state)
wait(1)
pl.pause()
wait(0.3)
pl.play()
check("không tiếng: dừng rồi phát tiếp — không kẹt 'đang tải'", wait(5, lambda: pl.state == "playing"), pl.state)
p0 = pl._now()
wait(1)
check("không tiếng: thời gian vẫn chạy", pl._now() - p0 > 0.7, f"{pl._now() - p0:.2f}")

# ---- 2) chạy tới hết video → trạng thái "hết" (không đứng hình gần cuối) ----
pl.seek(pl.total - 2.5)
check("chạy tới hết video → 'hết'", wait(25, lambda: pl.state == "ended"), f"{pl.state} @ {pl._now():.2f}/{pl.total:.2f}")
with_audio = copy.deepcopy(base)
panel.open_project(with_audio)
wait(30, lambda: pl.state == "paused")
pl.seek(pl.total - 3.0)
wait(0.5)
pl.play()
check("có tiếng: chạy tới hết video → 'hết'", wait(40, lambda: pl.state == "ended"), f"{pl.state} @ {pl._now():.2f}/{pl.total:.2f}")

# ---- 3) đổi màu: không dùng hình cũ trong bộ nhớ đệm ----
frames = []
pl.frameReady.connect(lambda img: frames.append(img))
panel.open_project(copy.deepcopy(base))
wait(30, lambda: pl.state == "paused")
pl.seek(5.0)
wait(10, lambda: pl._seek_to is None and frames)
wait(1)
before = frames[-1].copy()
bw = copy.deepcopy(base)
bw.video.color_preset, bw.video.color_strength = "bw", 100
frames.clear()
panel.open_project(bw)
wait(30, lambda: pl.state == "paused" and frames)
wait(1)
after = frames[-1]
px = [after.pixelColor(x, y) for x in range(20, after.width(), 97) for y in range(20, after.height(), 61)]
gray = all(abs(c.red() - c.green()) <= 6 and abs(c.green() - c.blue()) <= 6 for c in px)
check("đổi sang Đen trắng → hình mới (đen trắng), không lấy hình cũ trong bộ nhớ", gray and after != before)

# ---- 4) nhấp đúp vào hình: toàn màn hình, không bật / dừng phát ----
state0 = pl.state
QTest.mouseDClick(panel.view, Qt.MouseButton.LeftButton, pos=panel.view.rect().center())
wait(0.8)
check("nhấp đúp → toàn màn hình, trạng thái phát không đổi", panel._full is not None and pl.state == state0,
      f"{state0} → {pl.state}")
if panel._full is not None:
    panel._full.close()
    wait(0.3)

# ---- 5) xoá dự án (bảng trống): không phát lại video cũ ----
panel.clear("Kéo thả clip vào trang Video để xem trước")
wait(0.2)
pl.toggle()
pl.seek(3.0)
wait(0.5)
check("bảng trống: Phát / tua không phát lại video cũ", pl.state == "empty" and pl.project is None
      and not panel.play_btn.isEnabled(), pl.state)

# ---- 6) nhạc nhân bản (cùng file 2 dòng) + xáo không lặp liền ----
ms = MusicSettings(tracks=[MusicTrack("a.mp3"), MusicTrack("b.mp3"), MusicTrack("a.mp3"), MusicTrack("c.mp3")],
                   order="shuffle_no_repeat")
bad = 0
for seed in range(40):
    ms.seed = seed
    seq = planner.music_round(ms, random.Random(seed), None)
    paths = [ms.tracks[i].path for i in seq]
    bad += sum(a == b for a, b in zip(paths, paths[1:]))
check("nhạc nhân bản: xáo không lặp liền không phát cùng bài 2 lần liền", bad == 0, f"{bad} chỗ lặp")

panel.shutdown()
check("không có lỗi ngầm", not errs, errs[0][-1200:] if errs else "")
print("TẤT CẢ OK" if ok else "CÓ LỖI")
sys.exit(0 if ok else 1)
