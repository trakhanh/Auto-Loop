"""Trình duyệt ẩn trong app (QtWebEngine) đọc link video từ trang — chạy trong tiến trình riêng, trang HTML trên máy."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests" / "web_grab_probe.py"
pytest.importorskip("PySide6.QtWebEngineWidgets")


def run_probe(html_file: Path, verify_after="15", give_up="20", mode=""):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(PROBE), str(html_file), verify_after, give_up, mode], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    assert lines, r.stderr[-800:]
    return json.loads(lines[-1])


def test_grabs_video_src_title_poster(tmp_path):
    page = tmp_path / "video" / "7445552550692031763.html"  # đuôi .html: trình duyệt hiểu là trang web
    page.parent.mkdir()
    page.write_text('<html><head><meta charset="utf-8"><title>Bài A - 抖音</title></head><body>'
                    '<video src="https://v.zjcdn.com/abc.mp4" poster="https://p/c.jpg"></video></body></html>',
                    encoding="utf-8")
    out = run_probe(page)
    d = out["grabbed"]
    assert d["title"] == "Bài A" and d["srcs"] == ["https://v.zjcdn.com/abc.mp4"] and d["poster"] == "https://p/c.jpg"
    assert d["vid"] == "7445552550692031763" and "Mozilla" in d["ua"]


def test_gives_up_without_video(tmp_path):
    page = tmp_path / "trong.html"
    page.write_text("<html><title>Xác minh</title><body>verify</body></html>", encoding="utf-8")
    out = run_probe(page, "1", "2")
    assert "Không lấy được video Douyin" in out["failed"]


def test_waits_for_late_title_and_duration(tmp_path):
    """Thử thật Douyin: thẻ <video> có link trước khi trang kịp có tiêu đề → phải chờ tiêu đề (tối đa vài giây)."""
    page = tmp_path / "video" / "7000000000000000001.html"
    page.parent.mkdir()
    page.write_text('<html><head><meta charset="utf-8"><title></title></head><body>'
                    '<video src="https://v.zjcdn.com/late.mp4"></video>'
                    '<script>setTimeout(() => { document.title = "Tiêu đề muộn - 抖音"; }, 1500);</script>'
                    '</body></html>', encoding="utf-8")
    out = run_probe(page, "20", "30")
    assert out["grabbed"]["title"] == "Tiêu đề muộn"


def test_verify_page_opens_window_and_continues_there(tmp_path):
    """Douyin hỏi xác minh: mở cửa sổ NGAY (không chờ hết giờ), trang được mở lại trong cửa sổ đó; người dùng xác minh
    xong (ở đây: video hiện ra sau 2,5 giây) thì lấy được video và đóng cửa sổ."""
    page = tmp_path / "video" / "7000000000000000003.html"
    page.parent.mkdir()
    page.write_text('<html><head><meta charset="utf-8"><title>Xác minh - 抖音</title></head><body>'
                    '<div id="captcha_container">kéo thanh</div><script>setTimeout(() => {'
                    'document.getElementById("captcha_container").remove(); document.title = "Đã qua - 抖音";'
                    'const v = document.createElement("video"); v.src = "https://v.zjcdn.com/ok.mp4";'
                    'document.body.appendChild(v); }, 2500);</script></body></html>', encoding="utf-8")
    out = run_probe(page, "30", "40", "verify")
    assert out.get("verifying") and out["grabbed"]["srcs"] == ["https://v.zjcdn.com/ok.mp4"]
    assert out["grabbed"]["title"] == "Đã qua"


def test_ignores_decoy_video_takes_main_player(tmp_path):
    """Trang Douyin thật: <video> khác (file tĩnh của trang) có trước; video thật nằm trong khung trình phát chính."""
    page = tmp_path / "video" / "7707598997954874674.html"
    page.parent.mkdir()
    page.write_text('<html><head><meta charset="utf-8"><title>Video thật - 抖音</title></head><body data-e2e="root">'
                    '<video src="https://lf-douyin-pc-web.douyinstatic.com/obj/douyin-pc-web/decoy.mp4"></video>'
                    '<div id="main"></div><script>setTimeout(() => { document.getElementById("main").innerHTML ='
                    '\'<div data-e2e="video-detail"><div data-e2e="player-container">'
                    '<video src="https://v.zjcdn.com/main.mp4"></video></div></div>\'; }, 1500);</script></body></html>',
                    encoding="utf-8")
    out = run_probe(page)
    assert out["grabbed"]["srcs"] == ["https://v.zjcdn.com/main.mp4"]


def test_collect_cookies_from_app_profile(tmp_path):
    """Đăng nhập trong app: cookie trang đặt trong hồ sơ trình duyệt của app được đọc ra (để ghi file cho yt-dlp)."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Set-Cookie", "SESSDATA=abc123; Path=/; Max-Age=3600; HttpOnly")
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>ok</body></html>")

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, str(PROBE), f"http://127.0.0.1:{srv.server_port}/", "0", "0", "cookies"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
    finally:
        srv.shutdown()
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    assert lines, r.stderr[-800:]
    items = json.loads(lines[-1])["cookies"]
    c = next(x for x in items if x["name"] == "SESSDATA")
    assert c["value"] == "abc123" and c["http_only"] and c["expires"] > 0 and "127.0.0.1" in c["domain"]
