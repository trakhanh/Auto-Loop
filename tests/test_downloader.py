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
    assert dl.find_existing(str(tmp_path), "k2", "mp3") == sub / "c [k2].mp3"  # theo định dạng (soát cuối I5)
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


# ---------- soát cuối (review) ----------
def test_unicode_path_reported(tmp_path, mode, monkeypatch):
    """I1: tên có dấu / tiếng Trung — đường dẫn yt-dlp báo về phải đúng (yt-dlp mặc định in theo mã ANSI)."""
    mode("ok")
    monkeypatch.setenv("FAKE_YTDLP_TITLE", "Mưa rừng 中文")
    res = dl.run_download(FAKE, args_for_dir(tmp_path, "https://y/u1"), lambda p: None, lambda s: None,
                          threading.Event())
    assert Path(res.path).is_file() and "Mưa rừng 中文" in res.path
    a = args_for()
    assert pair(a, "--encoding") == "utf-8" and "--ignore-config" in a  # M2: bỏ qua file cấu hình riêng
    i = dl.info_args("https://y/x", 1, 50, "", "", "deno")
    assert pair(i, "--encoding") == "utf-8" and "--ignore-config" in i


def _alive(pid: int) -> bool:
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return code.value == 259  # STILL_ACTIVE


@pytest.mark.skipif(os.name != "nt", reason="Windows")
def test_cancel_kills_child_processes(tmp_path, mode, monkeypatch):
    """I2: Dừng phải tắt cả tiến trình con (ffmpeg do yt-dlp mở), không chỉ yt-dlp."""
    mode("hang_child")
    pidf = tmp_path / "child.pid"
    monkeypatch.setenv("FAKE_YTDLP_CHILDPID", str(pidf))
    cancel = threading.Event()
    threading.Timer(1.5, cancel.set).start()
    with pytest.raises(dl.CancelledError):
        dl.run_download(FAKE, args_for_dir(tmp_path / "o"), lambda p: None, lambda s: None, cancel)
    pid = int(pidf.read_text())
    t = time.time()
    while _alive(pid) and time.time() - t < 3:
        time.sleep(0.1)
    assert not _alive(pid)


def test_find_existing_respects_format(tmp_path):
    """I5: đã có MP4 không có nghĩa đã có MP3; nguồn .webm dở của lần tách tiếng không tính."""
    (tmp_path / "YouTube - a [f1].mp4").write_bytes(b"1")
    (tmp_path / "YouTube - b [f2].webm").write_bytes(b"1")
    assert dl.find_existing(str(tmp_path), "f1", "mp4") is not None
    assert dl.find_existing(str(tmp_path), "f1", "mp3") is None
    assert dl.find_existing(str(tmp_path), "f2", "mp3") is None
    (tmp_path / "YouTube - a [f1].mp3").write_bytes(b"1")
    assert dl.find_existing(str(tmp_path), "f1", "mp3").suffix == ".mp3"


def test_section_has_own_name():
    """I5: tải đoạn có tên riêng — không trùng / không bị nhận là bản tải cả video."""
    tpl = pair(args_for(section="60-150"), "-o")
    assert tpl.endswith(" [%(id)s] 1m00-2m30.%(ext)s")
    assert pair(args_for(), "-o").endswith(" [%(id)s].%(ext)s")


def test_playlist_without_count_is_unknown():
    """I6: kênh YouTube đọc lười không có playlist_count → số video chưa biết (0), không lấy số đã đọc."""
    g = dl.parse_info({"_type": "playlist", "title": "K", "entries": [{"id": "a", "url": "https://y/a"}]}, "u")
    assert g.count == 0


def test_network_error_friendly():
    """I7: mất mạng không bị báo nhầm là 'trang chặn tải'."""
    m = dl.friendly_error("ERROR: Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>", "")
    assert m == dl.NETWORK_ERROR and not dl.is_blocked_error(
        "Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>")
    assert dl.friendly_error("ERROR: Read timed out.", "") == dl.NETWORK_ERROR


def test_trim_filenames_by_folder():
    """I8: thư mục sâu + thư mục con theo kênh → cắt tên file để đường dẫn không quá 260 ký tự."""
    short = int(pair(args_for(), "--trim-filenames"))
    long_folder = "D:/" + "a" * 120
    a = dl.download_args("https://y/x", long_folder, Options(subdir="uploader", name="uploader"), "", "", "f", "d")
    n = int(pair(a, "--trim-filenames"))
    assert n < short and len(long_folder) + 61 + n + 20 <= 260 and n >= 40


# ---------- 2c: tuỳ chọn mới + luôn ra H.264 ----------
def test_mkv_args():
    a = args_for(fmt="mkv", quality="1080")
    assert pair(a, "--merge-output-format") == "mkv" and pair(a, "-S") == "res:1080"


def test_audio_quality_arg():
    assert pair(args_for(fmt="mp3", audio_q="192"), "--audio-quality") == "192K"
    assert pair(args_for(fmt="mp3"), "--audio-quality") == "320K"


def test_thumb_and_desc_args():
    a = args_for(thumb=True, desc=True)
    assert "--write-thumbnail" in a and pair(a, "--convert-thumbnails") == "jpg"
    assert any(x.startswith("after_move:KTLS_META|") for x in a)
    a = args_for()
    assert "--write-thumbnail" not in a and not any(x.startswith("after_move:KTLS_META|") for x in a)


def test_out_template_index():
    assert dl.out_template(Options(name="index"), index=7) == "007 - %(title).150B [%(id)s].%(ext)s"
    assert dl.out_template(Options(name="index")) == "%(title).150B [%(id)s].%(ext)s"  # video lẻ: không số
    a = dl.download_args("https://y/x", "D:/o", Options(name="index"), "", "", "f", "d", index=12)
    assert pair(a, "-o").startswith("012 - ")


def test_run_download_meta_and_txt(tmp_path, mode, monkeypatch):
    mode("ok")
    monkeypatch.setenv("FAKE_YTDLP_TITLE", "Mưa")
    a = dl.download_args("https://y/m1", str(tmp_path), Options(desc=True), "", "", "f", "d")
    res = dl.run_download(FAKE, a, lambda p: None, lambda s: None, threading.Event())
    assert res.meta["title"] == "Mưa" and "mô tả" in res.meta["description"]
    txt = dl.write_meta_txt(res.path, res.meta)
    body = txt.read_text(encoding="utf-8")
    assert txt.suffix == ".txt" and Path(res.path).stem == txt.stem
    assert "Mưa" in body and "mô tả" in body and "https://y/m1" in body


def test_needs_h264():
    assert dl.needs_h264(Options(), "H.265") and dl.needs_h264(Options(), "AV1")
    assert not dl.needs_h264(Options(), "")
    assert not dl.needs_h264(Options(h264=False), "H.265")
    assert not dl.needs_h264(Options(fmt="mkv"), "AV1") and not dl.needs_h264(Options(fmt="mp3"), "H.265")


def test_convert_to_h264_real_ffmpeg(tmp_path):
    """Trang chỉ có H.265 → tải xong tự chuyển sang H.264 (mở được mọi phần mềm). Dùng ffmpeg thật."""
    from loopstation.core import ffmpeg_tools
    src = tmp_path / "YouTube - a [h1].mp4"
    ffmpeg_tools.run([ffmpeg_tools.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=1",
                      "-f", "lavfi", "-i", "sine=duration=1", "-c:v", "libx265", "-x265-params", "log-level=error",
                      "-c:a", "aac", "-shortest", str(src)])
    assert src.is_file()
    out = dl.convert_to_h264(str(src), "libx264", threading.Event())
    codec = ffmpeg_tools.run([ffmpeg_tools.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=codec_name", "-of", "csv=p=0", out]).stdout.strip()
    assert out == str(src) and codec == "h264"
    assert not list(tmp_path.glob("*.h264tmp*"))
