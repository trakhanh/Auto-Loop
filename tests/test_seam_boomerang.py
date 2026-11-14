"""1.9.6 — ý lấy từ ffmpeg-skill: lặp xuôi–ngược (boomerang), đo chỗ nối khi lặp (đề xuất hoà / xuôi–ngược), không
kéo to tiếng gần như im lặng. Chạy không cửa sổ, dữ liệu + cài đặt vào thư mục tạm."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_KEEP: list = []


def _make(path: Path, src: str, secs: float, fps: int = 24, audio: bool = True) -> Path:
    from loopstation.core import ffmpeg_tools as ft
    args = [ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=s=320x180:r={fps}:d={secs}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=f=440:d={secs}", "-c:a", "aac", "-shortest"]
    subprocess.run(args + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", str(fps * 2), str(path)], check=True)
    return path


def _gray(path: Path) -> np.ndarray:
    from loopstation.core import ffmpeg_tools as ft
    r = subprocess.run([ft.ffmpeg(), "-v", "error", "-i", str(path), "-vf", "scale=64:36,format=gray", "-f", "rawvideo",
                        "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(-1, 36, 64).astype(int)


@pytest.fixture(scope="module")
def media():
    mp = pytest.MonkeyPatch()
    scratch = Path(tempfile.mkdtemp(prefix="ktls_seam_"))
    mp.setenv("KTLS_DATA_DIR", str(scratch / "data"))
    moving = _make(scratch / "khoi.mp4", "testsrc2", 3)
    still = _make(scratch / "tinh.mp4", "smptebars", 3, audio=False)
    yield scratch, moving, still
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


# ---------- lặp xuôi–ngược ----------
def test_plan_chunks_cover_reverse_part():
    from loopstation.core import boomerang
    chunks = boomerang.plan_chunks(54, 24)
    frames = [f for s, e in chunks for f in range(e - 1, s - 1, -1)]
    assert frames == list(range(52, 0, -1))  # N-2 … 1: hai khung đầu / cuối không lặp lại
    assert boomerang.chunk_frames(3840, 2160, 60) < 60  # 4K: khúc ngắn hơn 1 giây để không ngốn RAM
    assert boomerang.chunk_frames(320, 180, 24) == 24


def test_boomerang_frame_order_and_audio(media):
    from loopstation.core import boomerang, ffmpeg_tools as ft, probe
    scratch, moving, _still = media
    out = boomerang.make(ft.Runner(), str(moving), boomerang.output_path(str(moving)), 0.5, 0.25)
    assert out.name == "khoi_XuoiNguoc.mp4" and boomerang.output_path(str(moving)).name == "khoi_XuoiNguoc2.mp4"
    a, b = _gray(moving), _gray(out)
    n = int((3 - 0.75) * 24)
    assert len(b) == 2 * n - 2
    off = 12  # bỏ 0.5 s đầu = 12 khung
    assert max(np.abs(b[i] - a[off + i]).mean() for i in range(n)) < 1.5
    assert max(np.abs(b[n + j] - a[off + n - 2 - j]).mean() for j in range(n - 2)) < 1.5
    info = probe.probe(str(out))
    assert info.has_audio and abs(info.duration - (2 * n - 2) / 24) < 0.05


def test_boomerang_refuses_tiny_clip(media):
    from loopstation.core import boomerang, ffmpeg_tools as ft
    scratch, moving, _still = media
    with pytest.raises(ValueError):
        boomerang.make(ft.Runner(), str(moving), scratch / "x.mp4", 1.45, 1.45)


# ---------- đo chỗ nối ----------
def test_seam_detects_jump(media):
    from loopstation.core import boomerang, ffmpeg_tools as ft, probe, seam
    scratch, moving, still = media
    i = probe.probe(str(moving))
    assert seam.measure(str(moving), i.duration, float(i.fps)).jumpy  # hình chạy: khung cuối khác hẳn khung đầu
    i = probe.probe(str(still))
    assert not seam.measure(str(still), i.duration, float(i.fps)).jumpy  # hình đứng yên: không giật
    b = boomerang.make(ft.Runner(), str(moving), scratch / "b.mp4")
    i = probe.probe(str(b))
    assert not seam.measure(str(b), i.duration, float(i.fps)).jumpy  # bản xuôi–ngược: nối khớp
    assert seam.judge(10, 2) and not seam.judge(3, 0.1) and not seam.judge(10, 5)


# ---------- không kéo to tiếng gần như im lặng ----------
def test_quiet_audio_not_boosted():
    from loopstation.core import audio_build as ab
    assert ab.level_gain(-14, -45, 15) == 0.0  # gió / tiếng phòng: giữ nguyên
    assert ab.level_gain(-14, -30, 15) == 15.0  # nhỏ nhưng có nội dung: vẫn kéo (tối đa 15 dB)
    assert ab.level_gain(-14, -8, 15) == -6.0
    assert ab.level_gain(-50, -45, 15) == -5.0  # đích còn nhỏ hơn: vẫn được giảm
    assert "im lặng" in ab.quiet_note(-14, -45) and ab.quiet_note(-14, -20) == ""


# ---------- giao diện: dải gợi ý + hoà 1 s + xuôi–ngược thay dòng ----------
@pytest.fixture(scope="module")
def ui(media):
    mp = pytest.MonkeyPatch()
    scratch = media[0]
    mp.setenv("QT_QPA_PLATFORM", "offscreen")
    mp.setenv("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
    mp.setenv("KTLS_NO_UPDATE", "1")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    from loopstation.ui import theme
    theme.apply(app, 10)
    mp.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    mp.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    settings = QSettings(str(scratch / "s.ini"), QSettings.Format.IniFormat)
    yield app, settings
    mp.undo()


def _pump(app, sec, cond):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_seam_bar_suggests_and_fixes(media, ui):
    from loopstation.core.project import ClipItem, VideoSettings
    from loopstation.ui import video_tab as vt
    app, settings = ui
    scratch, moving, still = media
    tab = vt.VideoTab(settings)
    _KEEP.append(tab)
    tab.resize(1300, 800)
    tab.show()
    tab.load(VideoSettings(clips=[ClipItem(str(moving), count=5), ClipItem(str(still), count=5),
                                  ClipItem(str(moving), count=1)]))
    assert _pump(app, 20, lambda: tab.seam_bar.isVisible() and tab._seam_rows)
    assert [tab.list.indexOfTopLevelItem(it) for it in tab._seam_rows] == [0]  # chỉ clip lặp và bị giật
    assert "khoi" in tab.seam_text.text() and "Đề xuất" in tab.seam_text.text()
    assert "giật" in tab.list.topLevelItem(0).toolTip(vt.COL_LOOPXF)
    tab._seam_fix_xfade()
    assert tab.list.topLevelItem(0).data(0, vt.w.ROLE_DATA).loop_xfade == 1.0
    assert _pump(app, 2, lambda: not tab.seam_bar.isVisible())
    tab.undo()
    assert tab.list.topLevelItem(0).data(0, vt.w.ROLE_DATA).loop_xfade == 0.0
    assert _pump(app, 5, lambda: tab.seam_bar.isVisible())
    # xuôi–ngược: dòng dùng file mới (cạnh file gốc), hết giật; Ctrl+Z quay lại file cũ
    tab._boomerang_rows(None, list(tab._seam_rows))
    c = tab.list.topLevelItem(0).data(0, vt.w.ROLE_DATA)
    assert Path(c.path).name.startswith("khoi_XuoiNguoc") and Path(c.path).parent == moving.parent
    assert tab.list.topLevelItem(2).data(0, vt.w.ROLE_DATA).path == str(moving)  # dòng phát 1 lần cùng file: giữ nguyên
    assert _pump(app, 20, lambda: not tab.seam_bar.isVisible())
    tab.undo()
    assert tab.list.topLevelItem(0).data(0, vt.w.ROLE_DATA).path == str(moving)
