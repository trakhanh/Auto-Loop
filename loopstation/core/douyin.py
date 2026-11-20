"""Douyin qua trình duyệt trong app (yt-dlp hiện không tải được Douyin — 403 kể cả khi có cookie).

Trình duyệt ẩn (ui/web_grab.py) mở trang video, đọc link file trong thẻ <video>; module này lo phần không cần Qt:
nhận link, mã video, tên file, chọn link, tải trực tiếp có tiến độ / dừng được."""
from __future__ import annotations

import re
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .downloader import CancelledError, Options, trim_len

REFERER = "https://www.douyin.com/"
_HOSTS = ("douyin.com", "iesdouyin.com")
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')

# chạy trong trang: tiêu đề, link video, thời lượng, ảnh bìa, tên kênh
JS_GRAB = """(() => {
  const v = document.querySelector('video');
  const srcs = v ? [v.currentSrc, v.src, ...Array.from(v.querySelectorAll('source')).map(s => s.src)] : [];
  const meta = n => (document.querySelector(`meta[name="${n}"]`) || {}).content || '';
  const author = (document.querySelector('[data-e2e="user-info"] [data-e2e="user-name"], [data-e2e="video-author-name"]')
                  || {}).textContent || meta('author') || '';
  return JSON.stringify({title: document.title || meta('description'), srcs: srcs.filter(Boolean),
                         duration: v && isFinite(v.duration) ? v.duration : 0, poster: v ? (v.poster || '') : '',
                         author: author, url: location.href, ua: navigator.userAgent});
})()"""


def is_douyin(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _HOSTS)


def video_id(url: str) -> str:
    """Mã video từ link đầy đủ (/video/<id>, /note/<id>, ?modal_id=<id>); link rút gọn v.douyin.com → ""."""
    m = re.search(r"/(?:video|note)/(\d+)", url) or re.search(r"[?&]modal_id=(\d+)", url)
    return m.group(1) if m else ""


def is_user_page(url: str) -> bool:
    return "/user/" in urllib.parse.urlsplit(url).path


def canonical_url(vid: str) -> str:
    return f"https://www.douyin.com/video/{vid}"


def parse_grab(data: dict, page_url: str) -> dict:
    """Chuẩn hoá kết quả JS_GRAB: bỏ đuôi " - 抖音", lọc link http(s) không trùng, lấy mã video."""
    title = re.sub(r"\s*[-–|]\s*抖音.*$", "", str(data.get("title") or "")).strip()
    srcs: list[str] = []
    for s in data.get("srcs") or []:
        if isinstance(s, str) and s.lower().startswith(("http://", "https://")) and s not in srcs:
            srcs.append(s)
    url = str(data.get("url") or page_url)
    try:
        dur = float(data.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    return {"title": title, "srcs": srcs, "duration": dur, "poster": str(data.get("poster") or ""),
            "author": str(data.get("author") or "").strip(), "vid": video_id(url) or video_id(page_url),
            "ua": str(data.get("ua") or ""), "url": url}


def out_name(title: str, vid: str, o: Options, index: int = 0, folder: str = "") -> str:
    """Tên file theo Tuỳ chỉnh "Tên file" (Douyin không có ngày đăng / kênh chắc chắn → dùng tiêu đề)."""
    t = _BAD.sub(" ", title or "").strip().strip(".") or "Douyin"
    t = re.sub(r"\s{2,}", " ", t)
    head = f"{index:03d} - " if o.name == "index" and index > 0 else ("Douyin - " if o.name == "platform" else "")
    tail = f" [{vid}].mp4"
    room = min(150, trim_len(folder or "D:/", o)) - len(head) - len(tail)
    return head + t[:max(10, room)].rstrip(" .") + tail


def download(url: str, out: Path, ua: str, on_progress: Callable[[int, int], None] | None,
             cancel: threading.Event) -> Path:
    """Tải link video (User-Agent của trình duyệt + Referer douyin.com) về `out` qua file `.part`."""
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Link video Douyin không hợp lệ.")
    out = Path(out)
    part = out.with_name(out.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": ua or "Mozilla/5.0", "Referer": REFERER})
    done = 0
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:  # noqa: S310 — chỉ http(s)
            total = int(r.headers.get("Content-Length") or 0)
            while True:
                if cancel.is_set():
                    raise CancelledError()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
        if done == 0:
            raise ValueError("Douyin trả về file rỗng — thử lại.")
        part.replace(out)
        return out
    finally:
        part.unlink(missing_ok=True)
