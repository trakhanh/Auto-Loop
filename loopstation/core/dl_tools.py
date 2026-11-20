"""Công cụ tải video: yt-dlp.exe (kênh nightly) + deno.exe (YouTube cần để giải mã) — cài khi dùng lần đầu, tự cập nhật.

Lấy từ trang phát hành GitHub chính thức, luôn kiểm SHA-256, ghi `.part` rồi đổi tên. Cất ở <thư mục dữ liệu>/tools
nên cập nhật được mà không cần cài lại app (bộ cài app không mang theo công cụ này).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from . import ffmpeg_tools, updater

YTDLP_API = "https://api.github.com/repos/yt-dlp/yt-dlp-nightly-builds/releases/latest"
DENO_API = "https://api.github.com/repos/denoland/deno/releases/latest"
YTDLP_ASSET = "yt-dlp.exe"
DENO_ASSET = "deno-x86_64-pc-windows-msvc.zip"
CHECK_DAYS = {"yt-dlp": 1, "deno": 7}
_UA = "KTLoopStation-Tools"
_lock = threading.Lock()  # một lượt cài / cập nhật một lúc (hai lượt ghi chồng làm hỏng yt-dlp.exe)


@dataclass
class ToolRelease:
    name: str  # "yt-dlp" | "deno"
    version: str
    url: str
    size: int
    sha256: str


def tools_dir() -> Path:
    d = ffmpeg_tools.data_dir() / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ytdlp_path() -> Path:
    return tools_dir() / "yt-dlp.exe"


def deno_path() -> Path:
    return tools_dir() / "deno.exe"


def installed() -> bool:
    return ytdlp_path().is_file() and deno_path().is_file()


def _versions_file() -> Path:
    return tools_dir() / "versions.json"


def versions() -> dict[str, str]:
    try:
        data = json.loads(_versions_file().read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_versions(v: dict[str, str]) -> None:
    f = _versions_file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def mark_checked(name: str, day: date) -> None:
    v = versions()
    v[f"checked_{name}"] = day.isoformat()
    _write_versions(v)


def due(name: str, today: date) -> bool:
    """Đã tới hạn kiểm tra bản mới (yt-dlp mỗi ngày, Deno mỗi 7 ngày)?"""
    last = versions().get(f"checked_{name}", "")
    try:
        return (today - date.fromisoformat(last)).days >= CHECK_DAYS[name]
    except ValueError:
        return True


def _sha_in(text: str, name: str) -> str:
    m = re.search(r"\b([0-9a-fA-F]{64})\s+\*?" + re.escape(name) + r"\s*$", text or "", re.M)
    return m.group(1).lower() if m else ""


def _parse(data: dict, name: str, asset: str, sums_text: str) -> ToolRelease:
    rel = ToolRelease(name, str(data.get("tag_name", "")).lstrip("vV"), "", 0, "")
    for a in data.get("assets") or []:
        if a.get("name") == asset:
            rel.url = str(a.get("browser_download_url") or "")
            rel.size = int(a.get("size") or 0)
            digest = str(a.get("digest") or "")
            rel.sha256 = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else _sha_in(sums_text, asset)
    return rel


def parse_ytdlp_release(data: dict, sums_text: str = "") -> ToolRelease:
    return _parse(data, "yt-dlp", YTDLP_ASSET, sums_text)


def parse_deno_release(data: dict, sha_text: str = "") -> ToolRelease:
    return _parse(data, "deno", DENO_ASSET, sha_text)


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — địa chỉ GitHub cố định
        return r.read()


def _asset_url(data: dict, name: str) -> str:
    for a in data.get("assets") or []:
        if a.get("name") == name:
            return str(a.get("browser_download_url") or "")
    return ""


def fetch_release(name: str, timeout: float = 10.0) -> ToolRelease:
    """Hỏi GitHub bản mới nhất; tài sản không có `digest` thì đọc file tổng SHA đi kèm."""
    api, asset, parse = ((YTDLP_API, YTDLP_ASSET, parse_ytdlp_release) if name == "yt-dlp"
                         else (DENO_API, DENO_ASSET, parse_deno_release))
    data = json.loads(_get(api, timeout).decode("utf-8"))
    rel = parse(data)
    if not rel.sha256:
        sums = _asset_url(data, "SHA2-256SUMS" if name == "yt-dlp" else asset + ".sha256sum")
        if sums.startswith(updater._ALLOWED):
            rel = parse(data, _get(sums, timeout).decode("utf-8", "replace"))
    if not rel.url:
        raise ValueError(f"Bản phát hành {name} không có file cho Windows.")
    return rel


def _download_verified(rel: ToolRelease, out: Path, progress: Callable[[int], None] | None,
                       cancel: threading.Event | None) -> None:
    """Tải `rel` về `out` (qua `.part`); sai link / sai SHA / sai cỡ → ValueError, không để lại file."""
    if not rel.url.startswith(updater._ALLOWED):
        raise ValueError("Link tải công cụ không phải của GitHub.")
    if not rel.sha256:
        raise ValueError(f"Bản {rel.name} không có mã SHA-256 để kiểm tra.")
    part = out.with_name(f"{out.name}.{os.getpid()}-{threading.get_ident()}.part")
    h = hashlib.sha256()
    done = 0
    req = urllib.request.Request(rel.url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:  # noqa: S310
            if not r.geturl().startswith(updater._ALLOWED):
                raise ValueError("Link tải công cụ bị chuyển sang trang lạ.")
            while True:
                if cancel is not None and cancel.is_set():
                    raise updater.CancelledError()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(len(chunk))
        if rel.size and done != rel.size:
            raise ValueError(f"Tải {rel.name} thiếu ({done} / {rel.size} byte) — thử lại.")
        if h.hexdigest() != rel.sha256:
            raise ValueError(f"File {rel.name} tải về không khớp mã SHA-256 — đã huỷ.")
        part.replace(out)
    finally:
        part.unlink(missing_ok=True)


def install(rels: list[ToolRelease], progress: Callable[[int, int], None] | None = None,
            cancel: threading.Event | None = None) -> None:
    """Tải + đặt các công cụ (tiến độ cộng dồn mọi file). Deno: giải nén lấy đúng deno.exe."""
    with _lock:
        _install(rels, progress, cancel)


def _install(rels: list[ToolRelease], progress, cancel) -> None:
    d = tools_dir()
    total = sum(r.size for r in rels)
    got = [0]

    def step(n: int) -> None:
        got[0] += n
        if progress:
            progress(got[0], total)

    for rel in rels:
        if rel.name == "deno":
            z = d / "deno.zip"
            _download_verified(rel, z, step, cancel)
            try:
                with zipfile.ZipFile(z) as zf:
                    member = next((n for n in zf.namelist() if n.rsplit("/", 1)[-1].lower() == "deno.exe"), None)
                    if member is None:
                        raise ValueError("Gói Deno không có deno.exe.")
                    tmp = d / "deno.exe.part"
                    with zf.open(member) as src, open(tmp, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                os.replace(tmp, deno_path())
            finally:
                z.unlink(missing_ok=True)
                (d / "deno.exe.part").unlink(missing_ok=True)
        else:
            _download_verified(rel, ytdlp_path(), step, cancel)
        v = versions()
        v[rel.name] = rel.version
        _write_versions(v)


def update_if_newer(busy: Callable[[], bool], today: date, force: bool = False) -> list[str]:
    """Kiểm tra (theo hạn, hoặc ngay khi force) và thay công cụ đã cài bằng bản mới hơn — chỉ khi không có video nào
    đang tải. Trả về các dòng "yt-dlp 2026.11.19…" đã cập nhật. Lỗi mạng: im lặng, trả []."""
    if not updater.enabled() or not _lock.acquire(blocking=False):
        return []  # đang có lượt cài / cập nhật khác
    try:
        return _update(busy, today, force)
    finally:
        _lock.release()


def _update(busy: Callable[[], bool], today: date, force: bool) -> list[str]:
    done: list[str] = []
    have = {"yt-dlp": ytdlp_path().is_file(), "deno": deno_path().is_file()}
    for name in ("yt-dlp", "deno"):
        if not have[name] or not (force or due(name, today)):
            continue
        try:
            rel = fetch_release(name)
            if updater.is_newer(rel.version, versions().get(name, "0")):
                if busy():
                    continue  # đang tải: để lần sau (không ghi đã kiểm tra)
                _install([rel], None, None)
                done.append(f"{name} {rel.version}")
            mark_checked(name, today)
        except Exception:  # noqa: BLE001 — mạng / GitHub lỗi: thử lại lần sau
            continue
    return done


def uninstall() -> None:
    shutil.rmtree(tools_dir(), ignore_errors=True)
