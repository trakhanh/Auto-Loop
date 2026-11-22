"""Trình tải video bằng yt-dlp: tách link, đọc thông tin (JSON), dựng tham số theo Tuỳ chỉnh, đọc tiến độ, đổi lỗi
thành câu dễ hiểu, chạy tiến trình có thể dừng (dọn file dở). Không phụ thuộc Qt."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Callable

from . import ffmpeg_tools

# ---------- dữ liệu ----------


@dataclass
class Item:
    url: str
    vid: str
    title: str
    platform: str
    duration: float
    thumbnail: str
    uploader: str = ""
    upload_date: str = ""  # "20261120"
    views: int = 0


@dataclass
class Group:
    url: str
    title: str
    count: int
    items: list[Item]


@dataclass
class Progress:
    done: int
    total: int
    speed: float
    eta: int


@dataclass
class Result:
    path: str
    codec: str  # "" = H.264 (mở được mọi phần mềm), khác: "AV1", "VP9"…
    meta: dict = field(default_factory=dict)  # tiêu đề, kênh, link, ngày đăng, mô tả (khi bật "Lưu tiêu đề + mô tả")


class DownloadError(Exception):
    def __init__(self, friendly: str, stderr: str = ""):
        super().__init__(friendly)
        self.friendly = friendly
        self.stderr = stderr


class CancelledError(Exception):
    pass


# ---------- Tuỳ chỉnh ----------
FORMAT_LABELS = (("mp4", "MP4"), ("mkv", "MKV gốc"), ("mp3", "MP3"), ("m4a", "M4A"))
FORMAT_TIPS = {"mp4": "Video MP4 — mở được mọi phần mềm dựng, điện thoại",
               "mkv": "Giữ nguyên định dạng gốc của trang (nét nhất, có thể là AV1 / VP9) — không chuyển mã",
               "mp3": "Chỉ lấy tiếng, file MP3", "m4a": "Chỉ lấy tiếng, file M4A (AAC) — thường không phải chuyển mã"}
AUDIO_Q_LABELS = (("320", "320 kbps"), ("192", "192 kbps"), ("128", "128 kbps"))
MAX_MIN_LABELS = ((0, "Không"), (10, "10 phút"), (30, "30 phút"), (60, "60 phút"))
QUALITY_LABELS = (("best", "Cao nhất"), ("1080", "1080p"), ("720", "720p"), ("480", "480p"))
QUALITIES = {"best": "res,vcodec:h264,acodec:aac", "1080": "res:1080,vcodec:h264,acodec:aac",
             "720": "res:720,vcodec:h264,acodec:aac", "480": "res:480,vcodec:h264,acodec:aac"}
SUBS_LABELS = (("", "Không"), ("file", "Tải kèm file .srt"), ("embed", "Gắn vào video"))
NAME_LABELS = (("platform", "Nền tảng – Tiêu đề"), ("title", "Tiêu đề"), ("date", "Ngày đăng – Tiêu đề"),
               ("uploader", "Kênh – Tiêu đề"), ("index", "Số thứ tự – Tiêu đề"))
NAME_TEMPLATES = {"platform": "%(extractor_key)s - %(title).150B", "title": "%(title).150B",
                  "date": "%(upload_date>%Y-%m-%d)s - %(title).150B", "uploader": "%(uploader).60B - %(title).150B",
                  "index": "%(title).150B"}  # "index": số thứ tự do app ghi vào trước (out_template)
SUBDIR_LABELS = (("", "Không"), ("platform", "Theo nền tảng"), ("uploader", "Theo kênh"))
SUBDIR_PREFIX = {"": "", "platform": "%(extractor_key)s/", "uploader": "%(uploader).60B/"}
CONCURRENT = (1, 2, 3)
RATE_LABELS = (("", "Không giới hạn"), ("5M", "5 MB/s"), ("2M", "2 MB/s"), ("1M", "1 MB/s"))
PAGE_SIZES = (20, 50, 100, 200)
LOGINS = (("", "Không"), ("app", "Trình duyệt trong app"), ("firefox", "Firefox"), ("edge", "Edge"),
          ("chrome", "Chrome"), ("file", "File đăng nhập…"))
SUB_LANGS = "vi.*,en.*"

PROGRESS_PREFIX = "KTLS|"
PP_PREFIX = "KTLS_PP|"
FILE_PREFIX = "KTLS_FILE|"
PROGRESS_TEMPLATE = ("download:KTLS|%(progress.downloaded_bytes)s|%(progress.total_bytes,progress.total_bytes_estimate)s"
                     "|%(progress.speed)s|%(progress.eta)s")
PP_TEMPLATE = "postprocess:KTLS_PP|%(progress.postprocessor)s|%(progress.status)s"
FILE_TEMPLATE = "after_move:KTLS_FILE|%(filepath)s|%(vcodec)s"
META_PREFIX = "KTLS_META|"
META_TEMPLATE = "after_move:KTLS_META|%(.{title,uploader,webpage_url,upload_date,description})j"


def _keys(pairs) -> tuple:
    return tuple(k for k, _ in pairs)


@dataclass
class Options:
    fmt: str = "mp4"
    quality: str = "1080"
    subs: str = ""
    name: str = "platform"
    subdir: str = ""
    concurrent: int = 1
    rate: str = ""
    page: int = 50
    embed: bool = False
    extra: str = ""
    audio_q: str = "320"
    thumb: bool = False
    desc: bool = False
    open_after: bool = False
    max_minutes: int = 0
    h264: bool = True  # MP4: trang chỉ có H.265 / AV1 / VP9 → tải xong tự chuyển sang H.264

    @classmethod
    def from_settings(cls, s) -> "Options":
        d = cls()
        allowed = {"fmt": _keys(FORMAT_LABELS), "quality": tuple(QUALITIES), "subs": _keys(SUBS_LABELS),
                   "name": tuple(NAME_TEMPLATES), "subdir": tuple(SUBDIR_PREFIX), "rate": _keys(RATE_LABELS),
                   "audio_q": _keys(AUDIO_Q_LABELS)}
        out = {}
        for f in fields(cls):
            raw = s.value(f"download/opt/{f.name}", None)
            default = getattr(d, f.name)
            if raw is None:
                out[f.name] = default
            elif f.name in allowed:
                out[f.name] = str(raw) if str(raw) in allowed[f.name] else default
            elif f.name == "concurrent":
                try:
                    out[f.name] = min(max(int(raw), 1), CONCURRENT[-1])
                except (TypeError, ValueError):
                    out[f.name] = default
            elif f.name in ("page", "max_minutes"):
                ok = PAGE_SIZES if f.name == "page" else _keys(MAX_MIN_LABELS)
                try:
                    out[f.name] = int(raw) if int(raw) in ok else default
                except (TypeError, ValueError):
                    out[f.name] = default
            elif f.name in ("embed", "thumb", "desc", "open_after", "h264"):
                out[f.name] = raw is True or str(raw).lower() in ("true", "1")
            else:
                out[f.name] = str(raw)
        return cls(**out)

    def to_settings(self, s) -> None:
        for f in fields(self):
            s.setValue(f"download/opt/{f.name}", getattr(self, f.name))


def _label(pairs, key) -> str:
    return dict(pairs).get(key, key)


def summary(o: Options) -> str:
    """Dòng tóm tắt khi khung Tuỳ chỉnh đang gấp."""
    parts = [o.fmt.upper()]
    if o.fmt in ("mp4", "mkv"):
        parts.append("Cao nhất" if o.quality == "best" else f"{o.quality}p")
    if o.fmt == "mp3":
        parts.append(f"{o.audio_q} kbps")
    parts.append("phụ đề: " + {"": "không", "file": "file .srt", "embed": "gắn vào video"}[o.subs])
    parts.append("tên: " + _label(NAME_LABELS, o.name))
    if o.subdir:
        parts.append("thư mục: " + _label(SUBDIR_LABELS, o.subdir).lower())
    if o.rate:
        parts.append("tối đa " + _label(RATE_LABELS, o.rate))
    parts.append(f"{o.concurrent} video/lần")
    return " · ".join(parts)


def section_tag(section: str) -> str:
    """"60-150" → "1m00-2m30" (dùng trong tên file: không có dấu ':')."""
    return "-".join(f"{int(x) // 60}m{int(x) % 60:02d}" for x in section.split("-"))


def out_template(o: Options, section: str = "", index: int = 0) -> str:
    tail = f" [%(id)s] {section_tag(section)}.%(ext)s" if section else " [%(id)s].%(ext)s"
    head = f"{index:03d} - " if o.name == "index" and index > 0 else ""
    return SUBDIR_PREFIX.get(o.subdir, "") + head + NAME_TEMPLATES.get(o.name, NAME_TEMPLATES["platform"]) + tail


def trim_len(folder: str, o: Options) -> int:
    """Độ dài tối đa của tên file để cả đường dẫn (kể cả thư mục con + đuôi tạm .f137.mp4.part) ≤ 260 ký tự."""
    room = 260 - len(folder) - 1 - (61 if o.subdir else 0) - 20
    return max(40, min(200, room))


def split_extra(text: str) -> list[str]:
    """Tham số thêm do người dùng gõ: tách như dòng lệnh Windows (giữ dấu \\ trong đường dẫn), bỏ cặp nháy bọc ngoài."""
    try:
        toks = shlex.split(text or "", posix=False)
    except ValueError:
        toks = (text or "").split()
    return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in toks]


# ---------- link & thông tin ----------
PLATFORM_NAMES = {"youtube": "YouTube", "bilibili": "Bilibili", "twitter": "X", "facebook": "Facebook",
                  "instagram": "Instagram", "tiktok": "TikTok", "vimeo": "Vimeo", "dailymotion": "Dailymotion",
                  "douyin": "Douyin", "twitch": "Twitch", "reddit": "Reddit"}


def platform_name(key: str) -> str:
    k = (key or "").lower()
    for prefix, name in PLATFORM_NAMES.items():
        if k.startswith(prefix):
            return name
    return key or "Khác"


def split_links(text: str) -> list[str]:
    seen: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.lower().startswith(("http://", "https://")) and s not in seen:
            seen.append(s)
    return seen


def count_non_links(text: str) -> int:
    return sum(1 for line in (text or "").splitlines()
               if line.strip() and not line.strip().lower().startswith(("http://", "https://")))


def _thumb(d: dict) -> str:
    if d.get("thumbnail"):
        return str(d["thumbnail"])
    th = d.get("thumbnails") or []
    return str(th[-1].get("url", "")) if th and isinstance(th[-1], dict) else ""


def _item(d: dict, fallback_url: str, key: str = "") -> Item:
    url = str(d.get("webpage_url") or d.get("url") or fallback_url)
    if not url.lower().startswith("http"):
        url = fallback_url
    try:
        views = int(d.get("view_count") or 0)
    except (TypeError, ValueError):
        views = 0
    return Item(url=url, vid=str(d.get("id") or ""), title=str(d.get("title") or url),
                platform=platform_name(str(d.get("extractor_key") or d.get("ie_key") or key)),
                duration=float(d.get("duration") or 0), thumbnail=_thumb(d),
                uploader=str(d.get("uploader") or d.get("channel") or ""), upload_date=str(d.get("upload_date") or ""),
                views=views)


def parse_info(data: dict, source_url: str) -> Item | Group:
    if data.get("_type") == "playlist":
        entries = [e for e in (data.get("entries") or []) if isinstance(e, dict)]
        key = str(data.get("extractor_key") or "")
        items = [_item(e, str(e.get("url") or ""), key) for e in entries]
        return Group(url=source_url, title=str(data.get("title") or source_url),
                     count=int(data.get("playlist_count") or 0), items=items)  # 0 = chưa biết
    return _item(data, source_url)


_TAB = re.compile(r"/(videos|shorts|streams|live|playlists|releases|podcasts|courses)/?$")


def channel_tab_url(data: dict) -> str | None:
    """Link kênh YouTube "/@ten" trả về các thẻ (Videos / Shorts / Live…) → link thẻ Videos."""
    urls = [str(e.get("url") or e.get("webpage_url") or "") for e in (data.get("entries") or []) if isinstance(e, dict)]
    if not urls or not all(_TAB.search(u) for u in urls):
        return None
    return next((u for u in urls if re.search(r"/videos/?$", u)), None)


# ---------- tham số ----------
def login_args(login: str, cookies_file: str) -> list[str]:
    if login in ("file", "app"):  # app: cookie của trình duyệt trong app (người dùng tự đăng nhập)
        return ["--cookies", cookies_file] if cookies_file else []
    if login in ("firefox", "edge", "chrome"):
        return ["--cookies-from-browser", login]
    return []


def info_args(url: str, start: int, end: int, login: str, cookies_file: str, deno: str) -> list[str]:
    return ["--ignore-config", "--encoding", "utf-8", "-J", "--flat-playlist", "--playlist-start", str(start),
            "--playlist-end", str(end), "--js-runtimes", f"deno:{deno}", *login_args(login, cookies_file), url]


def download_args(url: str, folder: str, opts: Options, login: str, cookies_file: str, ffmpeg: str, deno: str,
                  section: str = "", index: int = 0) -> list[str]:
    a = ["--ignore-config", "--encoding", "utf-8", "--no-playlist", "--newline", "--progress",
         "--windows-filenames", "--trim-filenames", str(trim_len(folder, opts)), "--no-mtime",
         "--ffmpeg-location", ffmpeg, "--js-runtimes", f"deno:{deno}",
         "-P", folder, "-o", out_template(opts, section, index),
         "--progress-template", PROGRESS_TEMPLATE, "--progress-template", PP_TEMPLATE, "--print", FILE_TEMPLATE]
    if opts.fmt in ("mp3", "m4a"):
        a += ["-f", "ba/b", "-x", "--audio-format", opts.fmt,
              "--audio-quality", f"{opts.audio_q}K" if opts.fmt == "mp3" else "0"]
    elif opts.fmt == "mkv":  # giữ định dạng gốc: chỉ chọn theo độ phân giải, không ép H.264
        a += ["-f", "bv*+ba/b", "-S", "res" if opts.quality == "best" else f"res:{opts.quality}",
              "--merge-output-format", "mkv"]
    else:
        a += ["-f", "bv*+ba/b", "-S", QUALITIES.get(opts.quality, QUALITIES["1080"]), "--merge-output-format", "mp4"]
    if opts.subs:
        a += ["--write-subs", "--write-auto-subs", "--sub-langs", SUB_LANGS, "--convert-subs", "srt"]
        if opts.subs == "embed" and opts.fmt == "mp4":
            a.append("--embed-subs")
    if opts.rate:
        a += ["-r", opts.rate]
    if opts.embed:
        a += ["--embed-metadata", "--embed-thumbnail"]
    if opts.thumb:
        a += ["--write-thumbnail", "--convert-thumbnails", "jpg"]
    if opts.desc:
        a += ["--print", META_TEMPLATE]
    if section:
        a += ["--download-sections", f"*{section}", "--force-keyframes-at-cuts"]
    a += login_args(login, cookies_file)
    a += split_extra(opts.extra)
    a.append(url)
    return a


# ---------- đoạn ----------
def _secs(text: str) -> int:
    parts = (text or "").strip().split(":")
    if not parts or len(parts) > 3 or not all(p.strip().isdigit() for p in parts):
        raise ValueError(f"Thời điểm không hợp lệ: {text!r}")
    v = 0
    for p in parts:
        v = v * 60 + int(p)
    return v


def parse_section(text_from: str, text_to: str) -> str:
    a, b = _secs(text_from), _secs(text_to)
    if b <= a:
        raise ValueError("Thời điểm Đến phải sau Từ.")
    return f"{a}-{b}"


def fmt_time(s: int) -> str:
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def section_label(section: str) -> str:
    a, b = (int(x) for x in section.split("-"))
    return f"đoạn {fmt_time(a)}–{fmt_time(b)}"


# ---------- đọc dòng xuất ----------
def _num(x: str) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def parse_progress(line: str) -> Progress | None:
    if not line.startswith(PROGRESS_PREFIX):
        return None
    p = line.strip().split("|")
    if len(p) < 5:
        return None
    return Progress(int(_num(p[1])), int(_num(p[2])), _num(p[3]), int(_num(p[4])))


def parse_file_line(line: str) -> tuple[str, str] | None:
    if not line.startswith(FILE_PREFIX):
        return None
    rest = line.strip()[len(FILE_PREFIX):]
    path, _, codec = rest.rpartition("|")
    return (path, codec) if path else None


def codec_label(vcodec: str) -> str:
    c = (vcodec or "").lower()
    if not c or c == "none" or c.startswith(("avc", "h264")):
        return ""
    if c.startswith(("vp09", "vp9")):
        return "VP9"
    if c.startswith(("vp08", "vp8")):
        return "VP8"
    if c.startswith(("av01", "av1")):
        return "AV1"
    if c.startswith(("hvc1", "hev1", "hevc", "h265")):
        return "H.265"
    return c.split(".")[0].upper()


_BLOCKED = ("http error 403", "403: forbidden", "http error 429", "unable to extract", "unable to download",
            "nsig", "signature extraction", "requested format is not available")


NETWORK_ERROR = "Mất kết nối mạng — đã tạm dừng, kiểm tra mạng rồi bấm Tải đã chọn"
_NETWORK = ("getaddrinfo", "errno 11001", "timed out", "connection reset", "connection aborted", "connection refused",
            "network is unreachable", "no route to host", "temporary failure in name resolution",
            "remote end closed", "failed to resolve", "name or service not known")


def is_network_error(stderr: str) -> bool:
    s = (stderr or "").lower()
    return any(k in s for k in _NETWORK)


def is_blocked_error(stderr: str) -> bool:
    s = (stderr or "").lower()
    return any(k in s for k in _BLOCKED) and not is_network_error(s)


def friendly_error(stderr: str, login: str) -> str:
    s = (stderr or "").lower()
    if "no space left" in s or "errno 28" in s or "not enough space" in s:
        return "Ổ đĩa hết chỗ"
    if "fresh cookies" in s:  # Douyin…: cần cookie trình duyệt (không cần đăng nhập)
        return "Trang cần cookie trình duyệt — mở trang này bằng Firefox một lần, rồi chọn Đăng nhập: Firefox"
    if "cookie" in s and any(k in s for k in ("could not find", "database", "decrypt", "could not copy",
                                              "permission denied", "failed to decrypt", "failed to load")):
        browser = _label(LOGINS, login) if login in ("firefox", "edge", "chrome") else "trình duyệt"
        return f"Không lấy được đăng nhập từ {browser} — thử Firefox hoặc file đăng nhập"
    if any(k in s for k in ("sign in to confirm", "login required", "log in", "login_required",
                            "requires authentication", "you must be logged in", "use --cookies")):
        return "Cần đăng nhập — bấm Đăng nhập trong app (cột Cài đặt tải)"
    if any(k in s for k in ("private video", "video unavailable", "has been removed", "does not exist",
                            "http error 404", "this video is private", "content isn't available")):
        return "Video riêng tư hoặc đã bị xoá"
    if any(k in s for k in ("available in your country", "not available in your country", "geo restrict", "geo-restrict", "geo blocked")):
        return "Bị chặn ở Việt Nam (theo quốc gia)"
    if "unsupported url" in s:
        return "Link này chưa hỗ trợ"
    if is_network_error(s):
        return NETWORK_ERROR
    if is_blocked_error(s):
        return "Trang chặn tải — đang thử cập nhật công cụ"
    return "Lỗi tải (rê chuột vào ⓘ xem chi tiết)"


_SIDECAR = (".part", ".ytdl", ".srt", ".vtt", ".ass", ".jpg", ".jpeg", ".png", ".webp", ".json", ".description",
            ".tmp")


def _is_partial(name: str) -> bool:
    n = name.lower()
    return (n.endswith((".part", ".ytdl")) or ".part-frag" in n or ".temp." in n
            or re.search(r"\.f\d+[\w-]*\.\w+$", n) is not None)


FORMAT_EXTS = {"mp4": (".mp4", ".mov"), "mkv": (".mkv", ".webm", ".mp4"), "mp3": (".mp3",), "m4a": (".m4a",)}


def find_existing(folder: str, vid: str, fmt: str = "mp4") -> Path | None:
    """File đã tải của video `vid` (tên có "[id].") đúng định dạng đang chọn, trong thư mục lưu hoặc một cấp con."""
    base = Path(folder)
    exts = FORMAT_EXTS.get(fmt, FORMAT_EXTS["mp4"])
    if not vid or not base.is_dir():
        return None
    token = f"[{vid}]."
    try:
        level = list(base.iterdir())
        for p in level + [c for d in level if d.is_dir() for c in d.iterdir()]:
            if p.is_file() and token in p.name and p.suffix.lower() in exts and not _is_partial(p.name):
                return p
    except OSError:
        return None
    return None


def _clean_partials(folder: str, vid: str) -> None:
    base = Path(folder)
    if not vid or not base.is_dir():
        return
    token = f"[{vid}]"
    try:
        level = list(base.iterdir())
    except OSError:
        return
    for p in level + [c for d in level if d.is_dir() for c in d.iterdir()]:
        if p.is_file() and token in p.name and _is_partial(p.name):
            try:
                p.unlink()
            except OSError:
                pass


# ---------- chạy tiến trình ----------
TOOL_BLOCKED = "Công cụ tải bị phần mềm diệt virus chặn hoặc đã bị xoá"


def _popen(cmd: list[str]) -> subprocess.Popen:
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")  # đường dẫn có dấu / tiếng Trung
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
                                creationflags=ffmpeg_tools.CREATE_NO_WINDOW)
    except OSError as e:
        raise DownloadError(TOOL_BLOCKED, str(e)) from e
    ffmpeg_tools._attach(proc)
    return proc


def _pump(stream, sink: Callable[[str], None]) -> threading.Thread:
    def run() -> None:
        try:
            for line in stream:
                sink(line.rstrip("\r\n"))
        except (OSError, ValueError):
            pass
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _kill_tree(proc: subprocess.Popen) -> None:
    """Tắt yt-dlp và mọi tiến trình con của nó (ffmpeg ghép / cắt đoạn / tách tiếng)."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10,
                           creationflags=ffmpeg_tools.CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _wait(proc: subprocess.Popen, cancel: threading.Event | None, timeout: float | None) -> None:
    t0 = time.monotonic()
    while proc.poll() is None:
        if (cancel is not None and cancel.is_set()) or (timeout is not None and time.monotonic() - t0 > timeout):
            _kill_tree(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise CancelledError()
        time.sleep(0.1)


def _opt(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1] if flag in args else ""


def _login_of(args: list[str]) -> str:
    if "--cookies" in args:
        return "file"
    return _opt(args, "--cookies-from-browser")


def read_info(exe: list[str], args: list[str], cancel: threading.Event | None = None, timeout: float = 120) -> dict:
    proc = _popen(exe + args)
    out: list[str] = []
    err: list[str] = []
    th = [_pump(proc.stdout, out.append), _pump(proc.stderr, err.append)]
    try:
        _wait(proc, cancel, timeout)
    finally:
        for t in th:
            t.join(timeout=5)
    stderr = "\n".join(err[-40:])
    if proc.returncode != 0:
        raise DownloadError(friendly_error(stderr, _login_of(args)), stderr)
    try:
        return json.loads("\n".join(out))
    except ValueError as e:
        raise DownloadError("Lỗi tải (rê chuột vào ⓘ xem chi tiết)", stderr or str(e)) from e


def run_download(exe: list[str], args: list[str], on_progress: Callable[[Progress], None],
                 on_stage: Callable[[str], None], cancel: threading.Event, login: str = "", vid: str = "") -> Result:
    """Tải một video. Dừng (cancel) → kết thúc tiến trình, xoá mảnh dở của video đó, ném CancelledError."""
    folder = _opt(args, "-P") or "."
    found: dict[str, str] = {"vid": vid}
    result: list[tuple[str, str]] = []
    meta: dict = {}
    err: list[str] = []

    def on_line(line: str) -> None:
        p = parse_progress(line)
        if p is not None:
            on_progress(p)
            return
        f = parse_file_line(line)
        if f is not None:
            result.append(f)
            return
        if line.startswith(META_PREFIX):
            try:
                meta.update(json.loads(line[len(META_PREFIX):]))
            except ValueError:
                pass
            return
        if line.startswith(PP_PREFIX):
            pp = line.split("|")[1] if "|" in line else ""
            on_stage("Đang ghép…" if "merger" in pp.lower() else "Đang xử lý…")
        elif line.startswith("[Merger]"):
            on_stage("Đang ghép…")
        elif line.startswith("[download] Destination:") and not found["vid"]:
            m = re.search(r"\[([^\]\[]+)\]\.[\w.]+$", line)
            if m:
                found["vid"] = m.group(1)

    def on_err(line: str) -> None:
        if line.startswith(PP_PREFIX):
            on_line(line)
        err.append(line)

    proc = _popen(exe + args)
    th = [_pump(proc.stdout, on_line), _pump(proc.stderr, on_err)]
    try:
        _wait(proc, cancel, None)
    except CancelledError:
        for t in th:
            t.join(timeout=5)
        _clean_partials(folder, found["vid"])
        raise
    for t in th:
        t.join(timeout=5)
    stderr = "\n".join(err[-40:])
    if proc.returncode != 0:
        raise DownloadError(friendly_error(stderr, login or _login_of(args)), stderr)
    if result:
        path, vcodec = result[-1]
        return Result(path, codec_label(vcodec), meta)
    fmt = _opt(args, "--audio-format") or "mp4"
    existing = find_existing(folder, found["vid"], fmt)
    if existing is not None:
        return Result(str(existing), "")
    raise DownloadError("Lỗi tải (rê chuột vào ⓘ xem chi tiết)", stderr or "yt-dlp không báo file đã tải.")


# ---------- sau khi tải ----------
def write_meta_txt(media_path: str, meta: dict) -> Path:
    """Ghi "<tên file>.txt" cạnh video: tiêu đề, kênh, ngày đăng, link, mô tả (để đăng lại / tham khảo)."""
    out = Path(media_path).with_suffix(".txt")
    d = str(meta.get("upload_date") or "")
    date_s = f"{d[6:8]}/{d[4:6]}/{d[:4]}" if len(d) == 8 and d.isdigit() else d
    lines = [str(meta.get("title") or ""), ""]
    for label, val in (("Kênh", meta.get("uploader")), ("Ngày đăng", date_s), ("Link", meta.get("webpage_url"))):
        if val:
            lines.append(f"{label}: {val}")
    lines += ["", "Mô tả:", str(meta.get("description") or "(không có)")]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def needs_h264(o: Options, codec: str) -> bool:
    """MP4 + "Luôn ra H.264" mà trang chỉ có H.265 / AV1 / VP9 → cần chuyển mã sau khi tải."""
    return o.fmt == "mp4" and o.h264 and bool(codec)


def convert_to_h264(path: str, encoder: str, cancel: threading.Event,
                    on_progress: Callable[[float], None] | None = None) -> str:
    """Chuyển video sang H.264 (card đồ hoạ nếu có), giữ tiếng; ghi file tạm rồi thay file gốc. Trả về đường dẫn.
    Giải mã bằng card (NVIDIA → CUDA, AMD / Intel → D3D11) nếu bật ô Cài đặt và card đọc được video này. Lỗi ở card
    (giải mã rồi mã hoá) → lần lượt thử lại: giải mã CPU, rồi mã hoá CPU (libx264 nhanh) — không bỏ dở video."""
    from . import encoders, hwdec, probe
    src = Path(path)
    tmp = src.with_name(src.stem + ".h264tmp" + src.suffix)
    dur = probe.probe(str(src)).duration or 0.0
    use_card = ffmpeg_tools.OPTIONS.get("cut_hwdec", "1") == "1"
    hw = hwdec.choose(encoder, str(src), use_card)
    tries = [(encoder, hw)] + ([(encoder, "")] if hw else [])         + ([("libx264", "")] if encoders.is_hardware(encoder) else [])

    def args_for(enc: str, dec: str) -> list[str]:
        venc = encoders.encoder_args(enc, "high", 250)
        if enc == "libx264":  # "slow" của bản xuất dài: chuyển một video 4K mất hàng chục phút
            venc[venc.index("-preset") + 1] = "veryfast"
        return ["-v", "error", *hwdec.args(dec), "-i", str(src), "-map", "0:v:0", "-map", "0:a?", *venc,
                "-pix_fmt", encoders.pix_fmt(enc), "-c:a", "copy", "-movflags", "+faststart", str(tmp)]
    runner = ffmpeg_tools.Runner()
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(0.2):
            if cancel.is_set():
                runner.cancel()
                return
    threading.Thread(target=watch, daemon=True).start()

    def prog(d: dict) -> None:
        if on_progress and dur > 0:
            try:
                on_progress(min(1.0, int(d.get("out_time_us", "0")) / 1e6 / dur))
            except ValueError:
                pass
    try:
        for i, (enc, dec) in enumerate(tries):
            try:
                runner.ffmpeg(args_for(enc, dec), prog)
                break
            except ffmpeg_tools.FFmpegError:
                tmp.unlink(missing_ok=True)
                if cancel.is_set() or i == len(tries) - 1:
                    raise
        if cancel.is_set():
            raise CancelledError()
        os.replace(tmp, src)
        return str(src)
    except BaseException as e:
        tmp.unlink(missing_ok=True)
        if cancel.is_set():
            raise CancelledError() from e
        raise
    finally:
        stop.set()
