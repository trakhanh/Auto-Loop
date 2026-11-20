"""Douyin qua trình duyệt trong app (yt-dlp hiện không tải được Douyin — 403 kể cả khi có cookie).

Trình duyệt ẩn (ui/web_grab.py) mở trang video, đọc link file trong thẻ <video>; module này lo phần không cần Qt:
nhận link, mã video, tên file, chọn link, tải trực tiếp có tiến độ / dừng được."""
from __future__ import annotations

import re
import shutil
import threading
import time
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
  // trang đang hỏi xác minh (khung captcha / trang verify) → app mở cửa sổ cho người dùng tự làm
  const verify = !!document.querySelector('#captcha_container, .captcha_verify_container, [id*="captcha"], ' +
                                          '[class*="captcha"], iframe[src*="verify"], iframe[src*="captcha"]')
                 || /verify|captcha/i.test(location.href) || /验证/.test(document.title || '');
  return JSON.stringify({title: document.title || meta('description'), srcs: srcs.filter(Boolean),
                         duration: v && isFinite(v.duration) ? v.duration : 0, poster: v ? (v.poster || '') : '',
                         author: author, url: location.href, ua: navigator.userAgent, verify: verify});
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
            "ua": str(data.get("ua") or ""), "url": url, "verify": bool(data.get("verify"))}


MEDIA_TTL = 30 * 60  # link file video Douyin có hạn: dùng lại link lấy lúc Đọc link trong 30 phút


def media_fresh(at: float, now: float | None = None) -> bool:
    return at > 0 and ((now if now is not None else time.time()) - at) < MEDIA_TTL


def out_name(title: str, vid: str, o: Options, index: int = 0, folder: str = "") -> str:
    """Tên file theo Tuỳ chỉnh "Tên file" (Douyin không có ngày đăng / kênh chắc chắn → dùng tiêu đề)."""
    t = _BAD.sub(" ", title or "").strip().strip(".") or "Douyin"
    t = re.sub(r"\s{2,}", " ", t)
    head = f"{index:03d} - " if o.name == "index" and index > 0 else ("Douyin - " if o.name == "platform" else "")
    tail = f" [{vid}].mp4"
    room = min(150, trim_len(folder or "D:/", o)) - len(head) - len(tail)
    return head + t[:max(10, room)].rstrip(" .") + tail


PARALLEL_MIN = 8 << 20  # file từ 8 MB trở lên: tải nhiều phần song song


def _req(url: str, ua: str, rng: str = "") -> urllib.request.Request:
    h = {"User-Agent": ua or "Mozilla/5.0", "Referer": REFERER}
    if rng:
        h["Range"] = rng
    return urllib.request.Request(url, headers=h)


def _probe_size(url: str, ua: str) -> int:
    """Tổng dung lượng nếu máy chủ cho tải theo khoảng (Range), không thì 0."""
    try:
        with urllib.request.urlopen(_req(url, ua, "bytes=0-0"), timeout=20) as r:  # noqa: S310
            cr = str(r.headers.get("Content-Range") or "")
            if getattr(r, "status", 200) == 206 and "/" in cr:
                return int(cr.rsplit("/", 1)[1])
    except (OSError, ValueError):
        return 0
    return 0


def _stream(url: str, ua: str, rng: str, f, cancel: threading.Event, step: Callable[[int], None],
            on_total: Callable[[int], None] | None = None) -> int:
    got = 0
    with urllib.request.urlopen(_req(url, ua, rng), timeout=30) as r:  # noqa: S310 — chỉ http(s)
        if on_total is not None:
            on_total(int(r.headers.get("Content-Length") or 0))
        while True:
            if cancel.is_set():
                raise CancelledError()
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            step(len(chunk))
    return got


def download(url: str, out: Path, ua: str, on_progress: Callable[[int, int], None] | None,
             cancel: threading.Event, parts: int = 4) -> Path:
    """Tải link video (User-Agent của trình duyệt + Referer douyin.com) về `out` qua file `.part`. File lớn và máy chủ
    cho tải theo khoảng → chia `parts` phần tải song song (nhanh hơn rõ trên mạng văn phòng)."""
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Link video Douyin không hợp lệ.")
    out = Path(out)
    part = out.with_name(out.name + ".part")
    total = _probe_size(url, ua) if parts > 1 else 0
    lock = threading.Lock()
    tot = [total]
    done = [0]

    def step(n: int) -> None:
        with lock:
            done[0] += n
            d = done[0]
        if on_progress:
            on_progress(d, tot[0])

    pieces: list[Path] = []
    try:
        if total >= PARALLEL_MIN:
            size = -(-total // parts)
            ranges = [(i * size, min(total, (i + 1) * size) - 1) for i in range(parts) if i * size < total]
            pieces = [out.with_name(f"{out.name}.p{i}") for i in range(len(ranges))]
            errs: list[BaseException] = []

            def get(i: int, a: int, b: int) -> None:
                try:
                    with open(pieces[i], "wb") as f:
                        if _stream(url, ua, f"bytes={a}-{b}", f, cancel, step) != b - a + 1:
                            raise ValueError("Tải thiếu một phần — thử lại.")
                except BaseException as e:  # noqa: BLE001
                    errs.append(e)
                    cancel_local.set()
            cancel_local = threading.Event()
            th = [threading.Thread(target=get, args=(i, a, b), daemon=True) for i, (a, b) in enumerate(ranges)]
            for t in th:
                t.start()
            for t in th:
                while t.is_alive():
                    t.join(0.2)
                    if cancel.is_set() or cancel_local.is_set():
                        break
            for t in th:
                t.join(5)
            if cancel.is_set():
                raise CancelledError()
            if errs:
                raise errs[0]
            with open(part, "wb") as f:
                for pc in pieces:
                    with open(pc, "rb") as src:
                        shutil.copyfileobj(src, f, 1 << 20)
        else:
            with open(part, "wb") as f:
                _stream(url, ua, "", f, cancel, step, lambda n: tot.__setitem__(0, tot[0] or n))
        if done[0] == 0:
            raise ValueError("Douyin trả về file rỗng — thử lại.")
        part.replace(out)
        return out
    finally:
        part.unlink(missing_ok=True)
        for pc in pieces:
            pc.unlink(missing_ok=True)
