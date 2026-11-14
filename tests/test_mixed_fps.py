"""1.9.3 — Content 30 fps xen loop 24 fps: mặc định xuất theo fps cao nhất (content giữ đủ khung, loop chỉ lặp khung).
Trước đây xuất theo clip phát lâu nhất (loop 24 fps) → content mất 1/5 số khung."""
import subprocess

import pytest

from loopstation.core import ffmpeg_tools as ft, timeline
from loopstation.core.project import ClipItem, Project


def _clip(path, fps, secs, src="testsrc2"):
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=s=320x180:r={fps}:d={secs}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


@pytest.fixture()
def clips(tmp_path, monkeypatch):
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    content, loop = tmp_path / "1_Content.mp4", tmp_path / "1_loopA.mp4"
    _clip(content, 30, 3)
    _clip(loop, 24, 2, "testsrc")
    return content, loop


def _project(content, loop, fps="source"):
    p = Project(name="fps", output_kind="video_only")
    p.video.clips = [ClipItem(str(content), count=1), ClipItem(str(loop), count=20)]  # loop phát lâu hơn hẳn
    p.video.source_audio = "off"
    p.export.encoder = "cpu"
    p.export.fps = fps
    return p


def test_default_keeps_all_content_frames(clips):
    tl = timeline.build(_project(*clips))
    assert float(tl.fps) == 30
    assert not any("fps" in w for w in tl.warnings) and any("lặp khung lên 30" in n for n in tl.notes)
    assert tl.frames[0] == 90  # content 3 giây × 30 khung: đủ cả 90 khung


def test_main_option_keeps_old_behaviour_and_warns(clips):
    tl = timeline.build(_project(*clips, fps="main"))
    assert float(tl.fps) == 24
    assert any("bỏ bớt khung" in w and "Giữ đủ khung" in w for w in tl.warnings)


def test_render_content_frames_identical(clips, tmp_path):
    """Xuất thật: mọi khung của content 30 fps có mặt trong video (không bị bỏ), loop lặp khung lên 30."""
    from loopstation.core.render import RenderJob
    content, loop = clips
    out = RenderJob(_project(content, loop), {"h264": ["cpu"]}, str(tmp_path / "ra.mp4")).run()
    probe = subprocess.run([ft.ffprobe(), "-v", "error", "-select_streams", "v", "-count_frames", "-show_entries",
                            "stream=r_frame_rate,nb_read_frames", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout.strip()
    rate, frames = probe.split(",")
    assert rate == "30/1"
    assert int(frames) == 90 + 20 * 60  # 3 s content + 20 lần × 2 s loop, tất cả ở 30 fps

    def md5s(path, n):
        r = subprocess.run([ft.ffmpeg(), "-v", "error", "-i", str(path), "-frames:v", str(n), "-vf", "scale=64:36",
                            "-f", "framemd5", "-"], capture_output=True, text=True).stdout
        return [line.split(",")[-1].strip() for line in r.splitlines() if line and not line.startswith("#")]
    a, b = md5s(content, 90), md5s(out, 90)
    # mã hoá lại nên không trùng byte; so số khung khác nhau liên tiếp: content đủ 90 khung riêng biệt
    assert len(set(b)) >= 88 and len(set(a)) >= 88
