"""Đăng nhập trong app: cookie của trình duyệt riêng của app → file cookies.txt (định dạng Netscape) cho yt-dlp.

Người dùng tự đăng nhập tài khoản của mình (Bilibili, Facebook, Instagram…) trong cửa sổ trình duyệt của app; app chỉ
chép cookie đó ra file để yt-dlp tải bản chất lượng cao / nội dung cần đăng nhập. File nằm trong thư mục dữ liệu app."""
from __future__ import annotations

import os
from pathlib import Path

from . import ffmpeg_tools

# cookie cho biết đã đăng nhập (để báo "Đã đăng nhập: Bilibili, Instagram")
LOGIN_COOKIES = {"Bilibili": ("bilibili.com", "SESSDATA"), "Facebook": ("facebook.com", "c_user"),
                 "Instagram": ("instagram.com", "sessionid"), "X": ("x.com", "auth_token"),
                 "YouTube": ("youtube.com", "SAPISID"), "TikTok": ("tiktok.com", "sessionid"),
                 "Douyin": ("douyin.com", "sessionid")}
LOGIN_SITES = (("Bilibili", "https://passport.bilibili.com/login"), ("Facebook", "https://www.facebook.com/login"),
               ("Instagram", "https://www.instagram.com/accounts/login/"), ("X", "https://x.com/i/flow/login"),
               ("YouTube", "https://accounts.google.com/ServiceLogin?service=youtube"),
               ("TikTok", "https://www.tiktok.com/login"), ("Douyin", "https://www.douyin.com/"))


def cookie_file() -> Path:
    d = ffmpeg_tools.data_dir() / "web"
    d.mkdir(parents=True, exist_ok=True)
    return d / "cookies.txt"


def _ok(v: str) -> bool:
    return bool(v) and not any(c in v for c in "\t\r\n")


def write(items: list[dict], path: Path) -> Path:
    """Ghi cookie (dict: domain, name, value, path, secure, expires, http_only) ra file Netscape; cùng
    (domain, path, name) thì lấy giá trị sau cùng; bỏ dòng thiếu tên miền / có ký tự tab, xuống dòng."""
    keep: dict[tuple[str, str, str], dict] = {}
    for c in items:
        dom, name, val = str(c.get("domain") or ""), str(c.get("name") or ""), str(c.get("value") or "")
        if not (_ok(dom) and _ok(name)) or any(ch in val for ch in "\t\r\n"):
            continue
        keep[(dom, str(c.get("path") or "/"), name)] = c
    lines = ["# Netscape HTTP Cookie File", "# KT Loop Station — đăng nhập trong app (đừng gửi file này cho ai)"]
    for (dom, pth, name), c in keep.items():
        prefix = "#HttpOnly_" if c.get("http_only") else ""
        lines.append("\t".join([prefix + dom, "TRUE" if dom.startswith(".") else "FALSE", pth,
                                "TRUE" if c.get("secure") else "FALSE", str(int(c.get("expires") or 0)), name,
                                str(c.get("value") or "")]))
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def logged_in(items: list[dict]) -> list[str]:
    """Các trang đã đăng nhập (theo cookie đăng nhập đặc trưng), theo thứ tự LOGIN_COOKIES."""
    have = {(str(c.get("domain") or "").lstrip(".").lower(), str(c.get("name") or "")) for c in items
            if c.get("value")}
    out = []
    for site, (dom, name) in LOGIN_COOKIES.items():
        if any(n == name and (d == dom or d.endswith("." + dom)) for d, n in have):
            out.append(site)
    return out
