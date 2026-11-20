"""yt-dlp giả cho test (không mạng). FAKE_YTDLP_MODE: info | info_playlist | ok | fail_login | hang.
FAKE_YTDLP_MARK: nếu có, mỗi lần chạy ghi thêm một dòng vào file đó."""
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if "--encoding" in args:  # như yt-dlp: --encoding ép mã hoá đầu ra
    sys.stdout.reconfigure(encoding=args[args.index("--encoding") + 1])
else:  # như yt-dlp khi đầu ra là ống: mã hoá mặc định của Windows, ký tự không mã hoá được bị bỏ
    sys.stdout.reconfigure(errors="ignore")
mode = os.environ.get("FAKE_YTDLP_MODE", "ok")
mark = os.environ.get("FAKE_YTDLP_MARK")
if mark:
    with open(mark, "a", encoding="utf-8") as f:
        f.write(" ".join(args) + "\n")
url = args[-1] if args else ""
vid = url.rstrip("/").rsplit("/", 1)[-1] or "abc"


def opt(flag, default=""):
    return args[args.index(flag) + 1] if flag in args else default


if "-J" in args:
    if mode == "fail_login":
        sys.stderr.write("ERROR: [instagram] x: login required\n")
        sys.exit(1)
    if mode == "info_playlist" or "list" in url or "@" in url:
        start, end = int(opt("--playlist-start", "1")), int(opt("--playlist-end", "50"))
        total = 120
        entries = [{"id": f"{vid}{i}", "title": f"Video {i}", "url": f"https://y/{vid}{i}", "ie_key": "Youtube",
                    "duration": 30 + i} for i in range(start, min(end, total) + 1)]
        data = {"_type": "playlist", "title": "Danh sách " + vid, "playlist_count": total,
                "extractor_key": "YoutubeTab", "webpage_url": url, "entries": entries}
        if os.environ.get("FAKE_YTDLP_NOCOUNT"):
            del data["playlist_count"]
        print(json.dumps(data))
    else:
        print(json.dumps({"id": vid, "title": "Demo " + vid, "extractor_key": "Youtube", "duration": 42.0,
                          "thumbnail": "", "webpage_url": url}))
    sys.exit(0)

folder = Path(opt("-P", "."))
folder.mkdir(parents=True, exist_ok=True)
title = os.environ.get("FAKE_YTDLP_TITLE", "Demo")
name = f"YouTube - {title} [{vid}].mp4"
if mode == "fail_net":
    sys.stderr.write("ERROR: [youtube] x: Unable to download webpage: <urlopen error [Errno 11001] "
                     "getaddrinfo failed>\n")
    sys.exit(1)
if mode == "hang_child":  # như ffmpeg do yt-dlp mở: tiến trình con phải bị tắt theo khi Dừng
    import subprocess
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(os.environ["FAKE_YTDLP_CHILDPID"]).write_text(str(child.pid))
    print("KTLS|1|100|1.0|10", flush=True)
    time.sleep(60)
    sys.exit(0)
if mode == "fail_login":
    sys.stderr.write("ERROR: [instagram] x: login required\n")
    sys.exit(1)
if mode == "hang":
    (folder / (name + ".part")).write_bytes(b"x")
    print(f"[download] Destination: {folder / name}", flush=True)
    print("KTLS|1|100|1.0|10", flush=True)
    time.sleep(60)
    sys.exit(0)
print(f"[download] Destination: {folder / name}", flush=True)
for done in (10, 50, 100):
    print(f"KTLS|{done}|100|1000.0|1", flush=True)
    time.sleep(0.05)
sys.stderr.write("KTLS_PP|Merger|started\n")  # yt-dlp (--print → im lặng) in mẫu postprocess ra stderr
sys.stderr.flush()
time.sleep(0.1)
(folder / name).write_bytes(b"video")
print(f"KTLS_FILE|{folder / name}|avc1.640028", flush=True)
