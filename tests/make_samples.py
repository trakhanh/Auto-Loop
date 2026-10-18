"""Tạo clip và nhạc giả để thử app: python tests/make_samples.py [thư_mục_đích]"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FONT = "C\\:/Windows/Fonts/arial.ttf"


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args], check=True)


def clip(out: Path, label: str, color: str, w: int, h: int, fps: int, dur: float, audio_hz: int | None):
    vf = (f"drawtext=fontfile='{FONT}':text='{label}':fontsize={h // 5}:fontcolor=white:"
          f"x=(w-text_w)/2:y=(h-text_h)/2-{h // 10},"
          f"drawtext=fontfile='{FONT}':text='%{{pts\\:hms}}':fontsize={h // 12}:fontcolor=yellow:"
          f"x=(w-text_w)/2:y=h*0.7,"
          f"drawbox=x='(w-{h // 8})*t/{dur}':y=h-{h // 8}:w={h // 8}:h={h // 8}:color=white:t=fill")
    args = ["-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}:d={dur}"]
    if audio_hz:
        args += ["-f", "lavfi", "-i", f"sine=f={audio_hz}:d={dur}:sample_rate=48000"]
    args += ["-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast"]
    args += ["-c:a", "aac", "-shortest"] if audio_hz else ["-an"]
    ff(*args, str(out))


def track(out: Path, freq: int, dur: float, volume_db: float, codec: list[str]):
    expr = f"sine=f={freq}:d={dur}:sample_rate=44100"
    ff("-f", "lavfi", "-i", expr, "-af", f"volume={volume_db}dB,pan=stereo|c0=c0|c1=c0",
       *codec, str(out))


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "samples"
    clips, music = root / "clips", root / "music"
    clips.mkdir(parents=True, exist_ok=True)
    music.mkdir(parents=True, exist_ok=True)
    spec = [
        ("V1", "navy", 1920, 1080, 24, 8, None),
        ("V2", "darkgreen", 1920, 1080, 24, 8, 440),
        ("V3 720p 30fps", "maroon", 1280, 720, 30, 6, None),
        ("V4", "purple", 1920, 1080, 24, 8, 660),
        ("V5 doc 9x16", "teal", 1080, 1920, 24, 10, None),
        ("V6", "darkorange", 1920, 1080, 24, 8, None),
    ]
    for i, (label, color, w, h, fps, dur, hz) in enumerate(spec, 1):
        clip(clips / f"Video {i}.mp4", label, color, w, h, fps, dur, hz)
        print("clip", i)
    extra = root / "extra"
    extra.mkdir(exist_ok=True)
    clip(extra / "Intro.mp4", "INTRO", "black", 1920, 1080, 24, 5, 880)
    clip(extra / "Outro.mp4", "OUTRO", "dimgray", 1920, 1080, 24, 4, 990)
    ff("-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.3:d=12:sample_rate=48000",
       "-af", "lowpass=f=3000,pan=stereo|c0=c0|c1=c0", str(extra / "Mưa (tiếng nền).wav"))
    ff("-f", "lavfi", "-i", "testsrc2=s=1600x1200:d=1", "-frames:v", "1", str(extra / "Ảnh 4x3.png"))
    print("intro/outro/tiếng nền/ảnh")
    mp3 = ["-c:a", "libmp3lame", "-b:a", "192k"]
    track(music / "Bài 01 - Mưa đêm.mp3", 220, 40, -6, mp3)
    track(music / "Bài 02 - Rock, n' roll.mp3", 330, 30, -20, mp3)
    track(music / "Bài 03 [Lofi].mp3", 440, 35, -10, mp3)
    track(music / "Bài 04 - Cà phê sáng.m4a", 550, 25, -3, ["-c:a", "aac", "-b:a", "192k"])
    print("xong:", root)


if __name__ == "__main__":
    main()
