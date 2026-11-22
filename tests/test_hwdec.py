"""Giải mã bằng card đồ hoạ (loopstation/core/hwdec.py): NVIDIA → CUDA, AMD / Intel → D3D11 (chung mọi hãng), thử thật
vài khung trước khi dùng, card không đọc được thì lùi về CPU. Máy kiểm tra: NVIDIA + Intel (không có AMD) — ép D3D11
lên từng card để giả lập đường AMD. Video mẫu tạo bằng FFmpeg trong thư mục tạm."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loopstation.core import hwdec  # noqa: E402


@pytest.fixture(scope="module")
def clips():
    mp = pytest.MonkeyPatch()
    scratch = Path(tempfile.mkdtemp(prefix="ktls_hwdec_"))
    mp.setenv("KTLS_DATA_DIR", str(scratch / "data"))
    mp.setenv("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
    mp.setenv("KTLS_NO_UPDATE", "1")
    from loopstation.core import ffmpeg_tools
    ff = ffmpeg_tools.ffmpeg()
    out = {}
    for name, args in (("h264", ["-c:v", "libx264", "-pix_fmt", "yuv420p"]),
                       ("hevc10", ["-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-x265-params", "log-level=error"]),
                       ("asp", ["-c:v", "mpeg4"])):
        p = scratch / (f"{name}.avi" if name == "asp" else f"{name}.mp4")
        r = ffmpeg_tools.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=2", *args, str(p)])
        assert r.returncode == 0, r.stderr
        out[name] = str(p)
    hwdec.clear_cache()
    yield out
    hwdec.clear_cache()
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def test_candidate_per_card():
    assert hwdec.candidate("h264_nvenc") == "cuda"
    assert hwdec.candidate("hevc_nvenc") == "cuda"
    assert hwdec.candidate("h264_amf") == "d3d11va"
    assert hwdec.candidate("h264_qsv") == "d3d11va"
    assert hwdec.candidate("libx264") == ""  # không có card mã hoá: không đụng card


def test_args():
    assert hwdec.args("") == []
    assert hwdec.args("cuda") == ["-hwaccel", "cuda"]
    assert hwdec.args("d3d11va:1") == ["-hwaccel", "d3d11va", "-hwaccel_device", "1"]  # chọn card thứ 2


def test_label():
    assert "CUDA" in hwdec.label("cuda") and "D3D11" in hwdec.label("d3d11va:1") and hwdec.label("") == "CPU"


def test_unknown_accel_does_not_work(clips):
    assert not hwdec.works("khong-co-that", clips["h264"])


def test_choose_disabled_or_no_card(clips):
    assert hwdec.choose("h264_nvenc", clips["h264"], enabled=False) == ""
    assert hwdec.choose("libx264", clips["h264"]) == ""


def _need(accel, clip):
    if not hwdec.works(accel, clip):
        pytest.skip(f"máy này không giải mã được bằng {accel}")


@pytest.mark.parametrize("accel", ["d3d11va", "d3d11va:1", "cuda"])
def test_real_decode_h264_and_10bit(clips, accel):
    """Card giải mã thật cả H.264 8-bit lẫn HEVC 10-bit (điện thoại hay quay 10-bit)."""
    _need(accel, clips["h264"])
    assert hwdec.works(accel, clips["hevc10"])


def test_d3d11_rejects_codec_card_cannot_decode(clips):
    """MPEG-4 Part 2 (DivX / Xvid cũ): D3D11 không giải mã được → báo False (lùi về CPU), không lặng lẽ dùng CPU."""
    _need("d3d11va", clips["h264"])
    assert not hwdec.works("d3d11va", clips["asp"])
    assert hwdec.choose("h264_amf", clips["asp"]) == ""
    assert hwdec.choose("h264_amf", clips["h264"]) == "d3d11va"


def test_result_cached(clips, monkeypatch):
    hwdec.works("khong-co-that", clips["h264"])
    from loopstation.core import ffmpeg_tools
    monkeypatch.setattr(ffmpeg_tools, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("chạy lại")))
    assert not hwdec.works("khong-co-that", clips["h264"])
    os.utime(clips["h264"])  # file đổi → thử lại
    with pytest.raises(AssertionError):
        hwdec.works("khong-co-that", clips["h264"])
