"""Rà soát card đồ hoạ NVIDIA + AMD ngoài trang Cắt video: giải mã bằng card khi xuất video (CUDA / D3D11), lùi về CPU
khi card không giải mã được, ô Cài đặt, chuyển H.264 ở trang Tải video lùi về CPU khi card mã hoá lỗi.
Dữ liệu + cài đặt vào thư mục tạm."""
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def env():
    mp = pytest.MonkeyPatch()
    scratch = Path(tempfile.mkdtemp(prefix="ktls_gpu_"))
    mp.setenv("QT_QPA_PLATFORM", "offscreen")
    mp.setenv("KTLS_DATA_DIR", str(scratch / "data"))
    mp.setenv("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
    mp.setenv("KTLS_NO_UPDATE", "1")
    yield scratch
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def _ff(*args):
    from loopstation.core import ffmpeg_tools as ft
    r = ft.run([ft.ffmpeg(), "-v", "error", "-y", *args])
    assert r.returncode == 0, r.stderr


# ---------- chọn cách giải mã khi xuất video (ô "Giải mã video nguồn bằng GPU") ----------
def test_export_choice():
    from loopstation.core import hwdec
    both = SimpleNamespace(cuda_decode=True, d3d11_decode=True)
    amd = SimpleNamespace(cuda_decode=False, d3d11_decode=True)
    none = SimpleNamespace(cuda_decode=False, d3d11_decode=False)
    assert hwdec.export_choice(both, True) == "cuda"
    assert hwdec.export_choice(amd, True) == "d3d11va"  # máy AMD / Intel: D3D11
    assert hwdec.export_choice(none, True) == ""
    assert hwdec.export_choice(both, False) == ""  # ô Cài đặt tắt
    assert hwdec.export_choice(None, True) == ""  # chưa dò xong phần cứng


def test_gather_accel_reports_d3d11(env, monkeypatch):
    from loopstation.core import hwdec, sysinfo
    monkeypatch.setattr(hwdec, "works", lambda hw, src: hw == "d3d11va")
    info = sysinfo.gather_accel()
    assert info.d3d11_decode == ("d3d11va" in info.hwaccels)


# ---------- xuất video: card không giải mã được → tắt giải mã card, GIỮ card mã hoá ----------
class _Stop(Exception):
    pass


def test_render_hwdec_failure_keeps_gpu_encoder(env, tmp_path, monkeypatch):
    from loopstation.core import ffmpeg_tools as ft, render
    from loopstation.core.project import ClipItem, Project
    clip = tmp_path / "clip.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=s=160x120:r=30:d=2", "-c:v", "libx264", str(clip))
    p = Project(name="GPU")
    p.video.clips = [ClipItem(str(clip), count=2)]
    seen = []

    def fake(self, segs, paths, tl, encoder):
        seen.append((encoder, ft.OPTIONS.get("hwdec")))
        if len(seen) == 1:
            raise ft.FFmpegError("ffmpeg lỗi", "[h264 @ 0] Failed setup for format d3d11: hwaccel initialisation "
                                              "returned error.\nError while decoding stream #0:0: Invalid argument")
        raise _Stop()
    monkeypatch.setattr(render.RenderJob, "_encode_blocks", fake)
    monkeypatch.setitem(ft.OPTIONS, "hwdec", "d3d11va")
    render._GPU_JOBS.clear()
    avail = {"h264": ["amd", "cpu"], "hevc": ["amd", "cpu"], "audio": []}
    with pytest.raises(_Stop):
        render.RenderJob(p, avail, str(tmp_path / "ra.mp4")).run()
    assert seen[0] == ("h264_amf", "d3d11va")
    assert seen[1] == ("h264_amf", "")  # chỉ bỏ giải mã bằng card, vẫn mã hoá bằng card AMD
    assert render._GPU_JOBS == {}


# ---------- trang Cài đặt ----------
def test_settings_card_decode_boxes(env, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from loopstation.core.sysinfo import AccelInfo
    from loopstation.ui import theme
    from loopstation.ui.settings_page import SettingsPage
    theme.apply(app, 10)
    s = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    page = SettingsPage(s)
    assert page.cut_hwdec.isChecked()  # mặc định bật
    page.cut_hwdec.setChecked(False)
    assert str(s.value("pref/cut_hwdec")).lower() in ("false", "0")
    assert "D3D11" in page.hwdec.text()
    page.set_accel(AccelInfo(ffmpeg_path="x", hwaccels=["d3d11va"], d3d11_decode=True), False)
    assert page.hwdec.isEnabled()  # máy AMD: không có CUDA nhưng có D3D11
    page.set_accel(AccelInfo(ffmpeg_path="x"), False)
    assert not page.hwdec.isEnabled()
    page.close()
    page.deleteLater()


# ---------- Tải video: chuyển H.264 khi card mã hoá lỗi → CPU ----------
def test_convert_to_h264_falls_back_to_cpu(env, tmp_path):
    import threading
    from loopstation.core import downloader, encoders, probe
    if encoders._test("h264_amf"):
        pytest.skip("máy này có card AMD chạy được — không giả lập lỗi được")
    src = tmp_path / "v.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=2", "-c:v", "libx265", "-x265-params", "log-level=error",
        str(src))
    out = downloader.convert_to_h264(str(src), "h264_amf", threading.Event())
    import subprocess
    from loopstation.core import ffmpeg_tools as ft
    codec = subprocess.run([ft.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=codec_name", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    assert codec == "h264" and abs(probe.probe(out).duration - 2.0) < 0.2
    assert not list(tmp_path.glob("*.h264tmp*"))


# ---------- tham số AMF ----------
def test_amf_h264_high_profile_and_bframe_qp():
    from loopstation.core import encoders
    a = encoders.encoder_args("h264_amf", "high", 60)
    assert a[a.index("-profile:v") + 1] == "high"  # như NVENC (AMF mặc định Main: kém nét hơn cùng dung lượng)
    qp_p = int(a[a.index("-qp_p") + 1])
    assert int(a[a.index("-qp_b") + 1]) == qp_p  # driver mới bật khung B: giữ chất lượng như khung P
    h = encoders.encoder_args("hevc_amf", "high", 60)
    assert "-qp_b" not in h and "-profile:v" not in h  # hevc_amf không có khung B / profile High
    capped = encoders.encoder_args("h264_amf", "high", 60, maxrate_kbps=8000)
    assert capped[capped.index("-profile:v") + 1] == "high"


# ---------- xem trước: luôn giải mã CPU (khối ngắn, tua liên tục — khởi động card mỗi khối chỉ chậm thêm) ----------
def test_input_hw_flag(monkeypatch):
    from fractions import Fraction
    from loopstation.core import ffmpeg_tools as ft, video_build
    monkeypatch.setitem(ft.OPTIONS, "hwdec", "d3d11va")
    assert video_build._input("a.mp4", Fraction(30))[:2] == ["-hwaccel", "d3d11va"]  # xuất video: theo Cài đặt
    assert "-hwaccel" not in video_build._input("a.mp4", Fraction(30), hw=False)


def test_preview_never_uses_card_decode(monkeypatch):
    from fractions import Fraction
    from loopstation.core import ffmpeg_tools as ft, preview_engine, video_build
    monkeypatch.setitem(ft.OPTIONS, "hwdec", "cuda")
    monkeypatch.setattr(video_build, "segment_look", lambda *a, **k: (None, None))
    monkeypatch.setattr(video_build, "segment_graph", lambda *a, **k: "[0:v]null[v]")
    seg = SimpleNamespace(kind="body", clip=0, clip_b=None, start=0, frames=10, fade=False)
    sch = SimpleNamespace(segs=[seg], fps=Fraction(30), look=None, look_bookends=False, fade_out=0.0, offsets={},
                          is_image={}, paths={0: "a.mp4"}, width=640, height=360, fit="fill")
    assert "-hwaccel" not in preview_engine.segment_args(sch, 0, 0)
