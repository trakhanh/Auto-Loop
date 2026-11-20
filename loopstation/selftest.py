"""Tự kiểm tra bản cài (KTLoopStation.exe --selftest <file báo cáo>): FFmpeg, encoder GPU, trình phát video, xuất thử.

Dùng sau khi đóng gói để chắc chắn bản .exe chạy đủ chức năng trên máy, không cần bấm tay.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication


def run(win, report_path: str) -> None:
    out: dict = {"ok": False}
    app = QApplication.instance()

    def pump(sec: float) -> None:
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    try:
        from .core import encoders, ffmpeg_tools as ft
        from .core.project import ClipItem, Project
        from .core.render import RenderJob
        out["ffmpeg"] = ft.ffmpeg()
        out["ffprobe"] = ft.ffprobe()
        tmp = Path(tempfile.mkdtemp(prefix="ktls_selftest_"))
        clip = tmp / "clip.mp4"
        r = ft.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=2",
                    "-f", "lavfi", "-i", "sine=d=2", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(clip)],
                   timeout=60)
        out["make_clip"] = r.returncode == 0
        available = encoders.detect()
        out["encoders"] = available
        # trình phát video nhúng (Qt Multimedia + plugin ffmpeg)
        from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
        player = QMediaPlayer()
        sink = QVideoSink()
        frames = []
        sink.videoFrameChanged.connect(lambda f: frames.append(1))
        player.setVideoSink(sink)
        player.setSource(QUrl.fromLocalFile(str(clip)))
        player.play()
        pump(2.0)
        out["player_frames"] = len(frames)
        out["player_error"] = player.errorString()
        player.stop()
        # xuất thử: clip ×3 + crossfade, dùng encoder tự chọn (GPU nếu có)
        p = Project(name="selftest")
        p.video.clips = [ClipItem(str(clip), count=3, min=3, max=3, loop_xfade=0.5)]
        p.export.output_dir = str(tmp)
        p.export.markers = True
        res = RenderJob(p, available, str(tmp / "out" / "out.mp4")).run()
        out["render"] = str(res)
        out["render_size"] = Path(res).stat().st_size
        out["marker_files"] = sorted(x.name for x in Path(res).parent.iterdir())
        # lọc tạp âm (cần numpy trong bản đóng gói): tiếng của clip thử → bản đã lọc, đúng độ dài
        from .core import denoise
        cleaned = denoise.denoised_copy(ft.Runner(), str(clip), "medium")
        out["denoise"] = Path(cleaned).stat().st_size if Path(cleaned).is_file() else 0
        # trình duyệt trong app (tải Douyin): QtWebEngine phải có đủ trong bản đóng gói
        from .ui.web_grab import WebGrabber
        page = tmp / "video" / "7000000000000000002.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text('<html><head><meta charset="utf-8"><title>Selftest - 抖音</title></head><body>'
                        '<video src="https://example.com/selftest.mp4"></video></body></html>', encoding="utf-8")
        grabbed: dict = {}
        g = WebGrabber(storage=tmp / "web", verify_after=40, give_up=45, show_verify=False, poll_ms=400)
        g.grabbed.connect(lambda _l, d: grabbed.update(d))
        g.failed.connect(lambda _l, m: grabbed.update(error=m))
        g.grab(QUrl.fromLocalFile(str(page)).toString())
        end = time.monotonic() + 50
        while not grabbed and time.monotonic() < end:
            pump(0.2)
        g.shutdown()
        out["webengine"] = grabbed.get("title", "") == "Selftest" and bool(grabbed.get("srcs"))
        out["webengine_detail"] = grabbed.get("error", "")
        out["ok"] = bool(out["make_clip"] and out["player_frames"] > 0 and out["render_size"] > 0
                         and out["denoise"] > 0 and out["webengine"])
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:  # noqa: BLE001
        out["error"] = traceback.format_exc()
    Path(report_path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    QTimer.singleShot(0, app.quit)
