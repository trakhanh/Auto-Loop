"""Màu sau khi ghép phải giữ đúng clip gốc — kể cả clip HDR (điện thoại quay HDR)."""
import subprocess
from fractions import Fraction

import numpy as np
import pytest

from loopstation.core import ffmpeg_tools as ft, probe, video_build as vb
from loopstation.core.planner import Segment

W, H = 320, 180
COLORS = [(200, 40, 40), (40, 180, 60), (40, 70, 200), (230, 200, 60), (128, 128, 128), (225, 170, 140)]


@pytest.fixture()
def media(tmp_path, monkeypatch):
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    img = np.zeros((H, W, 3), np.uint8)
    cw = W // len(COLORS)
    for i, c in enumerate(COLORS):
        img[:, i * cw:(i + 1) * cw] = c
    ref = tmp_path / "ref.rgb"
    ref.write_bytes(img.tobytes())
    src_in = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", "24", "-stream_loop", "47",
              "-i", str(ref)]

    def make(name, vf, tags, enc="libx264"):
        out = tmp_path / name
        q = ["-crf", "4"] + (["-x265-params", "log-level=error"] if enc == "libx265" else [])
        subprocess.run([ft.ffmpeg(), "-v", "error", "-y", *src_in, "-vf", vf, "-c:v", enc, *q, *tags, str(out)],
                       check=True)
        return str(out)

    untagged = ",setparams=color_primaries=unknown:color_trc=unknown:colorspace=unknown"
    return {
        "sdr": make("sdr.mp4", "scale=1280:720,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p" + untagged, []),
        "hlg": make("hlg.mp4", "scale=1280:720,format=gbrp,zscale=tin=iec61966-2-1:min=gbr:pin=bt709:t=arib-std-b67:"
                    "m=bt2020nc:p=bt2020:r=tv:npl=203,format=yuv420p10le",
                    ["-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc"], "libx265"),
    }


def _colors(path):
    raw = subprocess.run([ft.ffmpeg(), "-v", "error", "-i", path, "-frames:v", "1", "-vf",
                          f"scale={W}:{H}:in_color_matrix=bt709:in_range=tv:flags=neighbor,format=rgb24",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    img = np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(float)
    cw = W // len(COLORS)
    return [img[H // 4:3 * H // 4, i * cw + cw // 4:i * cw + 3 * cw // 4].reshape(-1, 3).mean(0) for i in range(len(COLORS))]


def _max_err(path):
    return max(np.abs(m - np.array(c)).max() for m, c in zip(_colors(path), COLORS))


def test_probe_marks_hdr(media):
    hlg, sdr = probe.probe(media["hlg"]), probe.probe(media["sdr"])
    assert hlg.hdr and hlg.wide_gamut
    assert not sdr.hdr and not sdr.wide_gamut
    assert "tonemap" in vb.tone_chain(media["hlg"]) and vb.tone_chain(media["sdr"]) == ""
    assert vb.color_key(media["sdr"]) == [] and vb.color_key(media["sdr"], media["hlg"]) == [vb.TONE_VERSION]


@pytest.mark.parametrize("name", ["sdr", "hlg"])
def test_export_keeps_colors(media, name):
    out = vb.encode_segment(ft.Runner(), Segment("body", 0, 0, 12), {0: media[name]}, Fraction(24), W, H,
                            "letterbox", "libx264", "high")
    assert _max_err(str(out)) <= 16  # trước khi sửa: clip HDR lệch ~90 / 255 (xỉn, tối hẳn)


def test_crossfade_hdr_to_sdr(media):
    seg = Segment("xfade", 0, 0, 12, clip_b=1)
    out = vb.encode_segment(ft.Runner(), seg, {0: media["hlg"], 1: media["sdr"]}, Fraction(24), W, H,
                            "letterbox", "libx264", "high")
    assert _max_err(str(out)) <= 16


def test_output_advice():
    from loopstation.core import encoders as enc
    text, tone, btn = enc.output_advice(1920, 1080, 24, 2560, 1440, 24)
    assert tone == "warn" and btn and "không nét hơn" in text and "1.8" in text
    text, tone, btn = enc.output_advice(1920, 1080, 24, 1920, 1080, 24)
    assert tone == "success" and not btn
    text, tone, btn = enc.output_advice(1920, 1080, 24, 1920, 1080, 60)
    assert tone == "warn" and btn and "không mượt hơn" in text
    text, tone, btn = enc.output_advice(3840, 2160, 30, 1920, 1080, 30)
    assert tone == "" and btn and "vẫn nét" in text
    assert enc.res_key(2560, 1440) == "1440p" and enc.res_key(1080, 1920) == "vertical" and enc.res_key(1916, 1080) == "source"
    assert enc.res_name(1080, 1920) == "1080p dọc" and enc.res_name(1916, 1080) == "1916×1080"
