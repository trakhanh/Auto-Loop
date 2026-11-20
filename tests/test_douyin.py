"""Douyin qua trình duyệt trong app: nhận link, mã video, tên file, chọn link video, tải trực tiếp (không mạng thật)."""
import io
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loopstation.core import douyin  # noqa: E402
from loopstation.core.downloader import CancelledError, Options  # noqa: E402


def test_is_douyin():
    assert douyin.is_douyin("https://www.douyin.com/video/7445552550692031763")
    assert douyin.is_douyin("https://v.douyin.com/iAbCdEf/")
    assert douyin.is_douyin("https://www.iesdouyin.com/share/video/744/")
    assert not douyin.is_douyin("https://www.tiktok.com/@a/video/1")
    assert not douyin.is_douyin("https://notdouyin.com.evil.io/video/1")


def test_video_id():
    assert douyin.video_id("https://www.douyin.com/video/7445552550692031763?x=1") == "7445552550692031763"
    assert douyin.video_id("https://www.douyin.com/discover?modal_id=7435592199800212786") == "7435592199800212786"
    assert douyin.video_id("https://www.douyin.com/note/7400000000000000001") == "7400000000000000001"
    assert douyin.video_id("https://v.douyin.com/iAbCdEf/") == ""
    assert douyin.is_user_page("https://www.douyin.com/user/MS4wLjABAAAA")
    assert not douyin.is_user_page("https://www.douyin.com/video/1")


def test_canonical_url():
    assert douyin.canonical_url("744") == "https://www.douyin.com/video/744"


def test_out_name_sanitized_and_trimmed():
    n = douyin.out_name('Mưa <rừng>: "đẹp"? | 3/4 *', "744", Options())
    assert n.startswith("Douyin - Mưa") and n.endswith(" [744].mp4")
    assert not any(ch in n for ch in '<>:"/\\|?*')
    assert douyin.out_name("A", "1", Options(name="title")) == "A [1].mp4"
    assert douyin.out_name("A", "1", Options(name="index"), index=3) == "003 - A [1].mp4"
    long = douyin.out_name("字" * 400, "1", Options(), folder="D:/" + "a" * 100)
    assert len(long) <= 160 and long.endswith(" [1].mp4")
    assert douyin.out_name("   ", "9", Options()).endswith("[9].mp4")


def test_parse_grab():
    g = douyin.parse_grab({"title": "Bài A - 抖音", "srcs": ["", "blob:x", "https://v.zjcdn.com/a", "https://v.zjcdn.com/a",
                                                          "https://v2/b"], "duration": 61.5, "poster": "https://p/c.jpg",
                           "author": " Kênh B "}, "https://www.douyin.com/video/744")
    assert g["title"] == "Bài A" and g["srcs"] == ["https://v.zjcdn.com/a", "https://v2/b"]
    assert g["duration"] == 61.5 and g["poster"] == "https://p/c.jpg" and g["author"] == "Kênh B" and g["vid"] == "744"


class Resp(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_download_progress_and_headers(tmp_path, monkeypatch):
    seen = {}

    def fake(req, timeout=None):
        seen.update(dict(req.header_items()))
        return Resp(b"x" * (3 << 20), req.full_url)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    prog = []
    out = douyin.download("https://v.zjcdn.com/a", tmp_path / "v.mp4", "UA-1", lambda d, t: prog.append((d, t)),
                          threading.Event())
    assert out.stat().st_size == 3 << 20 and prog[-1] == (3 << 20, 3 << 20)
    assert seen.get("Referer") == "https://www.douyin.com/" and seen.get("User-agent") == "UA-1"
    assert not list(tmp_path.glob("*.part"))


def test_download_cancel_cleans(tmp_path, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: Resp(b"x" * (5 << 20), req.full_url))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CancelledError):
        douyin.download("https://v/a", tmp_path / "v.mp4", "UA", None, cancel)
    assert not list(tmp_path.iterdir())


def test_download_rejects_non_http(tmp_path):
    with pytest.raises(ValueError):
        douyin.download("file:///C:/Windows/win.ini", tmp_path / "v.mp4", "UA", None, threading.Event())


def test_parse_grab_verify_flag():
    """Trang hiện khung xác minh (captcha) → báo để mở cửa sổ ngay, khỏi chờ."""
    assert douyin.parse_grab({"title": "x", "srcs": [], "verify": True}, "https://www.douyin.com/video/1")["verify"]
    assert not douyin.parse_grab({"title": "x", "srcs": []}, "https://www.douyin.com/video/1")["verify"]
    assert "captcha" in douyin.JS_GRAB and "verify" in douyin.JS_GRAB


def test_media_fresh():
    """Link video lấy lúc Đọc link dùng lại khi tải nếu còn mới (đỡ mở trang Douyin lần nữa)."""
    assert douyin.media_fresh(1000.0, now=1000.0 + 29 * 60)
    assert not douyin.media_fresh(1000.0, now=1000.0 + 31 * 60)
    assert not douyin.media_fresh(0.0, now=5.0)


class RangeResp(Resp):
    def __init__(self, data, url, status):
        super().__init__(data, url)
        self.status = status


def _range_server(monkeypatch, data: bytes, ranges: bool = True):
    calls = []

    def fake(req, timeout=None):
        h = dict(req.header_items())
        rng = h.get("Range")
        calls.append(rng)
        if ranges and rng:
            a, b = rng.split("=")[1].split("-")
            a, b = int(a), (int(b) if b else len(data) - 1)
            r = RangeResp(data[a:b + 1], req.full_url, 206)
            r.headers["Content-Range"] = f"bytes {a}-{b}/{len(data)}"
            return r
        return RangeResp(data, req.full_url, 200)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls


def test_download_parallel_ranges(tmp_path, monkeypatch):
    data = bytes(range(256)) * (48 << 10)  # 12 MB
    calls = _range_server(monkeypatch, data)
    out = douyin.download("https://v/a", tmp_path / "v.mp4", "UA", None, threading.Event(), parts=4)
    assert out.read_bytes() == data
    assert sum(1 for c in calls if c and c != "bytes=0-0") >= 4
    assert sorted(p.name for p in tmp_path.iterdir()) == ["v.mp4"]


def test_download_no_range_support_falls_back(tmp_path, monkeypatch):
    data = b"y" * (10 << 20)
    _range_server(monkeypatch, data, ranges=False)
    out = douyin.download("https://v/a", tmp_path / "v.mp4", "UA", None, threading.Event(), parts=4)
    assert out.read_bytes() == data


def test_parse_grab_drops_page_assets():
    """Thử thật link 7707598997954874674: trang có một <video> là file tĩnh của Douyin (douyinstatic.com) hiện trước
    video thật → app tải nhầm. Bỏ file tĩnh; link /aweme/v1/play/ (cần cookie trình duyệt) xếp sau link CDN."""
    g = douyin.parse_grab({"title": "A", "srcs": [
        "https://lf-douyin-pc-web.douyinstatic.com/obj/douyin-pc-web/intro.mp4",
        "https://www.douyin.com/aweme/v1/play/?aid=6383&video_id=x",
        "https://v5-hl-mly-ov.zjcdn.com/abc/video/tos/x"]}, "https://www.douyin.com/video/1")
    assert g["srcs"] == ["https://v5-hl-mly-ov.zjcdn.com/abc/video/tos/x",
                         "https://www.douyin.com/aweme/v1/play/?aid=6383&video_id=x"]
    assert "video-detail" in douyin.JS_GRAB and "player-container" in douyin.JS_GRAB
