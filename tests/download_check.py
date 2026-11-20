"""Kiểm tra TAY trang Tải video với mạng thật (pytest không gom file này).

    .venv\\Scripts\\python.exe tests\\download_check.py [link ...]

Cài yt-dlp + Deno vào thư mục dữ liệu TẠM (không đụng dữ liệu thật của app), rồi đọc + tải từng link ở 720p vào
thư mục tạm, in OK / LỖI theo nền tảng, xong xoá thư mục tạm. Không truyền link thì dùng danh sách LINKS bên dưới
(người chạy tự điền một video ngắn công khai mỗi nền tảng; để trống thì bỏ qua nền tảng đó).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LINKS = {
    "YouTube": "",
    "TikTok": "",
    "Bilibili": "",
    "X": "",
    "Facebook": "",
    "Instagram": "",
}


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="ktls_dlcheck_"))
    os.environ["KTLS_DATA_DIR"] = str(scratch / "data")
    os.environ["KTLS_SETTINGS_ORG"] = "KTLoopStation-Test"
    os.environ.pop("KTLS_NO_UPDATE", None)
    from loopstation.core import dl_tools, downloader, ffmpeg_tools
    links = sys.argv[1:] or [u for u in LINKS.values() if u]
    if not links:
        print("Chưa có link nào — truyền link trên dòng lệnh hoặc điền LINKS.")
        return 2
    try:
        print("Cài công cụ tải vào thư mục tạm…")
        dl_tools.install([dl_tools.fetch_release("yt-dlp"), dl_tools.fetch_release("deno")])
        print("  ", dl_tools.versions())
        exe, deno = [str(dl_tools.ytdlp_path())], str(dl_tools.deno_path())
        out = scratch / "out"
        bad = 0
        for url in links:
            try:
                data = downloader.read_info(exe, downloader.info_args(url, 1, 5, "", "", deno))
                info = downloader.parse_info(data, url)
                item = info.items[0] if isinstance(info, downloader.Group) else info
                args = downloader.download_args(item.url, str(out), downloader.Options(quality="720"), "", "",
                                                ffmpeg_tools.ffmpeg(), deno)
                res = downloader.run_download(exe, args, lambda p: None, lambda s: None, threading.Event(),
                                              vid=item.vid)
                size = Path(res.path).stat().st_size / (1 << 20)
                print(f"OK   {item.platform:10} {item.title[:50]}  ({size:.1f} MB{', ' + res.codec if res.codec else ''})")
            except downloader.DownloadError as e:
                bad += 1
                print(f"LỖI  {url}: {e.friendly}\n     {e.stderr.strip().splitlines()[-1] if e.stderr.strip() else ''}")
        return 1 if bad else 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
