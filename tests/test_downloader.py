"""Trình tải video: tách link, đọc thông tin yt-dlp, dựng tham số theo Tuỳ chỉnh, tiến độ, lỗi dễ hiểu, chạy tiến trình."""
import os
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loopstation.core import downloader as dl  # noqa: E402
from loopstation.core.downloader import Options  # noqa: E402


def args_for(**kw):
    login = kw.pop("login", "")
    cookies = kw.pop("cookies_file", "")
    section = kw.pop("section", "")
    return dl.download_args("https://y/x1", "D:/out", Options(**kw), login, cookies, "C:/bin/ffmpeg.exe",
                            "C:/t/deno.exe", section)


def pair(args, flag):
    i = args.index(flag)
    return args[i + 1]


def test_split_links():
    lines = "https://a\n  \nfoo\nhttps://a\nhttp://b\n"
    assert dl.split_links(lines) == ["https://a", "http://b"]
    assert dl.count_non_links(lines) == 1


def test_parse_single_video():
    it = dl.parse_info({"id": "x1", "title": "T", "extractor_key": "Youtube", "duration": 12.5,
                        "thumbnail": "https://i/x.jpg", "webpage_url": "https://y/x1"}, "https://y/x1")
    assert it == dl.Item(url="https://y/x1", vid="x1", title="T", platform="YouTube", duration=12.5,
                         thumbnail="https://i/x.jpg")


def test_parse_playlist_group():
    data = {"_type": "playlist", "title": "Kênh XYZ", "playlist_count": 248, "extractor_key": "YoutubeTab",
            "webpage_url": "https://y/@xyz/videos",
            "entries": [{"id": f"v{i}", "title": f"V{i}", "url": f"https://y/v{i}", "ie_key": "Youtube",
                         "duration": 60, "thumbnails": [{"url": f"https://i/{i}.jpg"}]} for i in range(3)]}
    g = dl.parse_info(data, "https://y/@xyz")
    assert isinstance(g, dl.Group) and g.count == 248 and len(g.items) == 3
    assert g.items[1].vid == "v1" and g.items[1].platform == "YouTube" and g.items[1].thumbnail == "https://i/1.jpg"
    assert g.url == "https://y/@xyz"


def test_channel_tab_url():
    tabs = {"_type": "playlist", "entries": [{"url": "https://www.youtube.com/@abc/videos"},
                                             {"url": "https://www.youtube.com/@abc/shorts"}]}
    assert dl.channel_tab_url(tabs) == "https://www.youtube.com/@abc/videos"
    normal = {"_type": "playlist", "entries": [{"url": "https://y/v1"}]}
    assert dl.channel_tab_url(normal) is None


def test_download_args_quality_login():
    assert pair(args_for(quality="1080"), "-S") == "res:1080,vcodec:h264,acodec:aac"
    assert pair(args_for(quality="best"), "-S") == "res,vcodec:h264,acodec:aac"
    assert pair(args_for(quality="480"), "-S") == "res:480,vcodec:h264,acodec:aac"
    assert pair(args_for(login="firefox"), "--cookies-from-browser") == "firefox"
    assert pair(args_for(login="file", cookies_file="C:/c.txt"), "--cookies") == "C:/c.txt"
    a = args_for()
    assert "--cookies" not in a and "--cookies-from-browser" not in a
    assert pair(a, "--merge-output-format") == "mp4" and pair(a, "-f") == "bv*+ba/b"
    assert pair(a, "--ffmpeg-location") == "C:/bin/ffmpeg.exe" and pair(a, "--js-runtimes") == "deno:C:/t/deno.exe"
    assert "--no-playlist" in a and a[-1] == "https://y/x1" and pair(a, "-P") == "D:/out"


def test_download_args_filename_safe():
    a = args_for()
    assert "--windows-filenames" in a
    tpl = pair(a, "-o")
    assert ".150B" in tpl and tpl.endswith(" [%(id)s].%(ext)s")


def test_out_template_variants():
    assert dl.out_template(Options()) == "%(extractor_key)s - %(title).150B [%(id)s].%(ext)s"
    assert dl.out_template(Options(name="title")) == "%(title).150B [%(id)s].%(ext)s"
    assert dl.out_template(Options(name="date")).startswith("%(upload_date>%Y-%m-%d)s - ")
    assert dl.out_template(Options(name="uploader", subdir="platform")).startswith("%(extractor_key)s/%(uploader).60B - ")
    assert dl.out_template(Options(subdir="uploader")).startswith("%(uploader).60B/")


def test_options_args_audio_subs_rate_embed_extra():
    a = args_for(fmt="mp3")
    assert "-x" in a and pair(a, "--audio-format") == "mp3" and "-S" not in a and "--merge-output-format" not in a
    a = args_for(subs="file")
    assert "--write-subs" in a and "--write-auto-subs" in a and pair(a, "--sub-langs") == "vi.*,en.*"
    assert pair(a, "--convert-subs") == "srt" and "--embed-subs" not in a
    assert "--embed-subs" in args_for(subs="embed")
    assert pair(args_for(rate="2M"), "-r") == "2M" and "-r" not in args_for()
    a = args_for(embed=True)
    assert "--embed-metadata" in a and "--embed-thumbnail" in a
    a = args_for(extra='--no-part --match-filter "duration < 600"')
    assert a[-4:-1] == ["--no-part", "--match-filter", "duration < 600"]
    a = args_for(section="60-150")
    assert pair(a, "--download-sections") == "*60-150" and "--force-keyframes-at-cuts" in a


def test_parse_section():
    assert dl.parse_section("1:00", "2:30") == "60-150"
    assert dl.parse_section("0:00:05", "1:00:00") == "5-3600"
    for bad in (("2:00", "1:00"), ("x", "1:00"), ("1:00", "1:00")):
        with pytest.raises(ValueError):
            dl.parse_section(*bad)
    assert dl.section_label("60-150") == "đoạn 1:00–2:30"


def test_options_settings_roundtrip():
    class S(dict):
        def value(self, k, d=None):
            return self.get(k, d)

        def setValue(self, k, v):  # noqa: N802
            self[k] = v

    s = S()
    o = Options(fmt="m4a", quality="720", subs="embed", name="date", subdir="uploader", concurrent=3, rate="1M",
                page=100, embed=True, extra="--no-part")
    o.to_settings(s)
    assert s["download/opt/quality"] == "720"
    assert Options.from_settings(s) == o
    assert Options.from_settings(S()) == Options()
    s2 = S({"download/opt/concurrent": "9", "download/opt/quality": "zz", "download/opt/embed": "true"})
    o2 = Options.from_settings(s2)
    assert o2.concurrent == 3 and o2.quality == "1080" and o2.embed is True
    assert dl.summary(Options()) == "MP4 · 1080p · phụ đề: không · tên: Nền tảng – Tiêu đề · 1 video/lần"


def test_parse_progress():
    assert dl.parse_progress("KTLS|1048576|4194304|524288.0|6") == dl.Progress(1048576, 4194304, 524288.0, 6)
    p = dl.parse_progress("KTLS|100|NA|None|NA")
    assert p.total == 0 and p.speed == 0 and p.eta == 0
    assert dl.parse_progress("[download] 5%") is None


def test_parse_file_line_and_codec():
    assert dl.parse_file_line("KTLS_FILE|D:\\v\\TikTok - a [7].mp4|av01.0.08M.08") == \
        ("D:\\v\\TikTok - a [7].mp4", "av01.0.08M.08")
    assert dl.parse_file_line("whatever") is None
    assert dl.codec_label("av01.0.08M.08") == "AV1"
    assert dl.codec_label("vp09.00.40.08") == "VP9" and dl.codec_label("vp9") == "VP9"
    assert dl.codec_label("avc1.640028") == "" and dl.codec_label("h264") == "" and dl.codec_label("none") == ""


def test_friendly_error():
    assert "Cần đăng nhập" in dl.friendly_error("ERROR: Sign in to confirm you're not a bot", "")
    assert "Cần đăng nhập" in dl.friendly_error("ERROR: [instagram] x: login required", "")
    assert dl.friendly_error("ERROR: Private video", "") == "Video riêng tư hoặc đã bị xoá"
    assert dl.friendly_error("ERROR: Video unavailable", "") == "Video riêng tư hoặc đã bị xoá"
    assert dl.friendly_error("ERROR: Unsupported URL: https://x", "") == "Link này chưa hỗ trợ"
    m = dl.friendly_error("ERROR: could not find chrome cookies database", "chrome")
    assert "Chrome" in m and "Firefox" in m
    assert dl.friendly_error("OSError: [Errno 28] No space left on device", "") == "Ổ đĩa hết chỗ"
    assert "Trang chặn tải" in dl.friendly_error("ERROR: unable to download video data: HTTP Error 403: Forbidden", "")
    assert "quốc gia" in dl.friendly_error("ERROR: The uploader has not made this video available in your country", "")
    assert dl.friendly_error("ERROR: something odd", "").startswith("Lỗi tải")


def test_is_blocked_error():
    assert dl.is_blocked_error("HTTP Error 403: Forbidden")
    assert not dl.is_blocked_error("Private video")


def test_find_existing(tmp_path):
    (tmp_path / "TikTok - a [7].mp4").write_bytes(b"1")
    (tmp_path / "YouTube - b [9].mp4.part").write_bytes(b"1")
    sub = tmp_path / "Kenh"
    sub.mkdir()
    (sub / "c [k2].mp3").write_bytes(b"1")
    assert dl.find_existing(str(tmp_path), "7") == tmp_path / "TikTok - a [7].mp4"
    assert dl.find_existing(str(tmp_path), "9") is None
    assert dl.find_existing(str(tmp_path), "k2") == sub / "c [k2].mp3"
    assert dl.find_existing(str(tmp_path / "khong-co"), "7") is None


# ---------- chạy tiến trình (yt-dlp giả) ----------
FAKE = [sys.executable, str(ROOT / "tests" / "fake_ytdlp.py")]


@pytest.fixture
def mode(monkeypatch):
    def set_mode(m):
        monkeypatch.setenv("FAKE_YTDLP_MODE", m)
    return set_mode


def test_run_download_ok(tmp_path, mode):
    mode("ok")
    prog, stages = [], []
    res = dl.run_download(FAKE, args_for_dir(tmp_path), prog.append, stages.append, threading.Event())
    assert len(prog) >= 3 and "Đang ghép…" in stages
    assert Path(res.path).is_file() and res.codec == ""


def args_for_dir(folder: Path, url="https://y/abc"):
    return dl.download_args(url, str(folder), Options(), "", "", "ffmpeg", "deno")


def test_run_download_login_error(tmp_path, mode):
    mode("fail_login")
    with pytest.raises(dl.DownloadError) as ei:
        dl.run_download(FAKE, args_for_dir(tmp_path), lambda p: None, lambda s: None, threading.Event())
    assert "Cần đăng nhập" in ei.value.friendly and "login required" in ei.value.stderr


def test_cancel_kills_and_cleans(tmp_path, mode):
    mode("hang")
    cancel = threading.Event()
    threading.Timer(0.8, cancel.set).start()
    t0 = time.monotonic()
    with pytest.raises(dl.CancelledError):
        dl.run_download(FAKE, args_for_dir(tmp_path), lambda p: None, lambda s: None, cancel)
    assert time.monotonic() - t0 < 5
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_read_info_playlist(mode):
    mode("info_playlist")
    data = dl.read_info(FAKE, dl.info_args("https://y/list", 1, 50, "", "", "deno"))
    assert data["_type"] == "playlist"


def test_missing_exe_friendly(tmp_path):
    with pytest.raises(dl.DownloadError) as ei:
        dl.read_info([str(tmp_path / "khong-co.exe")], ["-J", "https://y/x"])
    assert "diệt virus" in ei.value.friendly
