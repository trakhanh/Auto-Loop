"""Cập nhật trong app: đọc bản mới nhất ở GitHub Releases, tải bộ cài (kiểm tra SHA-256) rồi cài đè."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = "trakhanh/Auto-Loop"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
ASSET = "KTLoopStation-Setup.exe"  # tên cố định, có ở mọi bản phát hành
_ALLOWED = ("https://github.com/", "https://objects.githubusercontent.com/",
            "https://release-assets.githubusercontent.com/")
_UA = "KTLoopStation-Updater"


class CancelledError(Exception):
    pass


@dataclass
class Release:
    version: str  # "1.8.0"
    notes: str  # ghi chú phát hành (markdown)
    page: str  # trang release trên GitHub
    url: str = ""  # link tải bộ cài
    size: int = 0
    sha256: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.7.0' → (1, 7, 0); phần không phải số bị bỏ qua."""
    nums = re.findall(r"\d+", text.split("-")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote: str, local: str) -> bool:
    def pad(v: tuple[int, ...]) -> tuple[int, ...]:
        return v + (0,) * (4 - len(v))
    return pad(parse_version(remote)) > pad(parse_version(local))


def enabled() -> bool:
    """Tắt khi chạy test / không có màn hình (không gọi mạng)."""
    return not (os.environ.get("KTLS_NO_UPDATE") or os.environ.get("QT_QPA_PLATFORM") == "offscreen")


def can_install() -> bool:
    """Chỉ bản đã cài (file .exe) mới tự cài đè được; chạy từ mã nguồn thì mở trang tải."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def _sha_from_notes(notes: str, name: str) -> str:
    m = re.search(r"\b([0-9a-fA-F]{64})\s+\*?" + re.escape(name) + r"\b", notes or "")
    return m.group(1).lower() if m else ""


def parse_release(data: dict) -> Release:
    notes = data.get("body") or ""
    rel = Release(version=str(data.get("tag_name", "")).lstrip("vV"), notes=notes,
                  page=data.get("html_url") or RELEASES_PAGE)
    for a in data.get("assets") or []:
        if a.get("name") == ASSET:
            rel.url = a.get("browser_download_url", "")
            rel.size = int(a.get("size") or 0)
            digest = str(a.get("digest") or "")
            rel.sha256 = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else \
                _sha_from_notes(notes, ASSET)
    return rel


def fetch_latest(timeout: float = 10.0) -> Release:
    req = urllib.request.Request(API_LATEST, headers={"Accept": "application/vnd.github+json", "User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — địa chỉ cố định (https)
        return parse_release(json.loads(r.read().decode("utf-8")))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(rel: Release, dest_dir: Path, progress: Callable[[int, int], None] | None = None,
             cancel: threading.Event | None = None) -> Path:
    """Tải bộ cài về dest_dir; sai SHA-256 / sai cỡ → lỗi và xoá file tải dở."""
    if not rel.url.startswith(_ALLOWED):
        raise ValueError("Link tải không phải của GitHub.")
    if not rel.sha256:
        raise ValueError("Bản phát hành không có mã SHA-256 để kiểm tra — hãy tải tay ở trang Releases.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"KTLoopStation-Setup-{rel.version}.exe"
    if out.is_file() and (not rel.size or out.stat().st_size == rel.size) and file_sha256(out) == rel.sha256:
        return out  # đã tải lần trước (vd lần trước chưa cài vì đang xuất)
    part = out.with_suffix(".part")
    h = hashlib.sha256()
    done = 0
    req = urllib.request.Request(rel.url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:  # noqa: S310
            if not r.geturl().startswith(_ALLOWED):
                raise ValueError("Link tải bị chuyển sang trang lạ.")
            total = int(r.headers.get("Content-Length") or rel.size or 0)
            while True:
                if cancel is not None and cancel.is_set():
                    raise CancelledError()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if rel.size and done != rel.size:
            raise ValueError(f"Tải thiếu ({done} / {rel.size} byte) — thử lại.")
        if h.hexdigest() != rel.sha256:
            raise ValueError("File tải về không khớp mã SHA-256 — đã huỷ, thử lại.")
        part.replace(out)
        return out
    finally:
        part.unlink(missing_ok=True)


def launch_installer(path: Path) -> None:
    """Chạy bộ cài ở chế độ chỉ hiện thanh tiến trình; cài xong bộ cài tự mở lại app (/RELAUNCH=1)."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
                      "/RELAUNCH=1"], close_fds=True, creationflags=flags)


def cleanup(dest_dir: Path, keep: str = "") -> None:
    """Xoá bộ cài cũ đã tải (giữ bản `keep`)."""
    for p in dest_dir.glob("KTLoopStation-Setup-*"):
        if p.name != keep:
            try:
                p.unlink()
            except OSError:
                pass
