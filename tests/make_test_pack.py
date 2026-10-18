"""Tạo bộ mẫu để người dùng thử app: video có chuyển động, 10 bài nhạc lofi tổng hợp (~30 phút),
tiếng nền, intro/outro, ảnh và 2 dự án mẫu.

python tests/make_test_pack.py [thư_mục]   (mặc định: Mau-Test cạnh app.py; cần numpy)
"""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loopstation.core.project import AmbientLayer, ClipItem, MusicTrack, Project  # noqa: E402

FONT = "C\\:/Windows/Fonts/segoeui.ttf"
SR = 44100


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args], check=True)


def title(text: str, size: int, y: str = "(h-text_h)/2") -> str:
    return (f"drawtext=fontfile='{FONT}':text='{text}':fontsize={size}:fontcolor=white@0.85:"
            f"x=(w-text_w)/2:y={y}:shadowcolor=black@0.5:shadowx=3:shadowy=3")


# ---------------- video ----------------
def make_videos(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "24"]
    grad = "gradients=s={s}:r=24:d=8:speed=0.015:nb_colors=4:c0={c0}:c1={c1}:c2={c2}:c3={c3}"
    clips = [
        ("01 Mưa đêm thành phố.mp4", grad.format(s="1920x1080", c0="0x0f0c29", c1="0x302b63", c2="0x24243e",
                                                  c3="0x6a3093"), "Mưa đêm", True),
        ("02 Hoàng hôn.mp4", grad.format(s="1920x1080", c0="0xff7e5f", c1="0xfeb47b", c2="0x86377b",
                                         c3="0x2b1055"), "Hoàng hôn", False),
        ("03 Bầu trời sao.mp4", "life=s=960x540:r=24:mold=0:ratio=0.015:death_color=#070718:"
                                "life_color=#fff6c8,scale=1920:1080:flags=bicubic", "Bầu trời sao", False),
        ("04 Rừng xanh.mp4", "life=s=480x270:r=24:mold=10:ratio=0.12:death_color=#1b4332:"
                             "life_color=#95d5b2,scale=1920:1080:flags=neighbor", "Rừng xanh", True),
        ("05 Biển đêm.mp4", grad.format(s="1920x1080", c0="0x000428", c1="0x004e92", c2="0x1cb5e0",
                                        c3="0x000046"), "Biển đêm", False),
        ("06 Clip dọc 9x16.mp4", grad.format(s="1080x1920", c0="0x8e2de2", c1="0x4a00e0", c2="0xf953c6",
                                             c3="0xb91d73"), "Clip dọc", False),
    ]
    for name, src, label, with_audio in clips:
        args = ["-f", "lavfi", "-i", src, "-t", "8"]
        if with_audio:
            args += ["-f", "lavfi", "-i", "anoisesrc=color=brown:amplitude=0.08:d=8:sample_rate=48000"]
        vf = title(label, 96)
        args += ["-vf", vf, *enc]
        args += ["-c:a", "aac", "-b:a", "128k", "-shortest"] if with_audio else ["-an"]
        ff(*args, str(d / name))
        print("  video:", name)


def make_bookends(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    enc = ["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "24"]
    sting = "aevalsrc=0.3*sin(2*PI*523*t)*exp(-2*t)+0.2*sin(2*PI*784*t)*exp(-2*t):s=48000:d=5"
    ff("-f", "lavfi", "-i", "color=c=0x0f1117:s=1920x1080:r=24:d=5", "-f", "lavfi", "-i", sting,
       "-vf", f"{title('KT Loop Station', 120)},{title('By Khánh Trà', 48, '(h/2)+90')},fade=in:d=1",
       *enc, "-c:a", "aac", "-shortest", str(d / "Intro.mp4"))
    ff("-f", "lavfi", "-i", "color=c=0x0f1117:s=1920x1080:r=24:d=5",
       "-vf", f"{title('Cảm ơn đã xem!', 110)},fade=out:st=4:d=1", *enc, "-an", str(d / "Outro.mp4"))
    print("  intro/outro")


def make_images(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    ff("-f", "lavfi", "-i", "gradients=s=1600x1200:c0=0x355c7d:c1=0x6c5b7b:c2=0xc06c84:nb_colors=3:d=1",
       "-vf", title("Ảnh tĩnh 4x3", 90), "-frames:v", "1", str(d / "Ảnh 4x3.png"))
    ff("-f", "lavfi", "-i", "gradients=s=1920x1080:c0=0x134e5e:c1=0x71b280:nb_colors=2:d=1",
       "-vf", title("Ảnh nền 16x9", 90), "-frames:v", "1", "-q:v", "3", str(d / "Ảnh nền 16x9.jpg"))
    print("  ảnh")


# ---------------- âm thanh ----------------
def write_mp3(path: Path, stereo: np.ndarray, bitrate: str = "192k", af: str = "anull") -> None:
    wav = path.with_suffix(".tmp.wav")
    data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
    ff("-i", str(wav), "-af", af, "-c:a", "libmp3lame", "-b:a", bitrate, str(path))
    wav.unlink()


def song(seed: int, seconds: float, bpm: float, root_hz: float, minor: bool) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    beat = 60 / bpm
    bar = beat * 4
    third = 2 ** (3 / 12) if minor else 2 ** (4 / 12)
    # vòng hợp âm I–vi–IV–V (hoặc i–VI–III–VII khi giọng thứ), mỗi hợp âm 2 ô nhịp
    prog = [0, 9, 5, 7] if not minor else [0, 8, 3, 10]
    out = np.zeros(n)
    chord_len = bar * 2
    idx = (t // chord_len).astype(int) % 4
    pos = (t % chord_len) / chord_len
    env = np.minimum(1, pos * 8) * np.minimum(1, (1 - pos) * 6)
    for k in range(4):
        mask = idx == k
        f0 = root_hz * 2 ** (prog[k] / 12)
        tt = t[mask]
        for ratio, amp in ((1, 0.20), (third, 0.14), (2 ** (7 / 12), 0.14), (2, 0.06)):
            for det in (-0.6, 0.6):  # hơi lệch tần để pad dày hơn
                out[mask] += amp * np.sin(2 * np.pi * (f0 * ratio + det) * tt)
        out[mask] += 0.22 * np.sin(2 * np.pi * f0 / 2 * tt)  # bass
        out[mask] *= env[mask]
    # trống: kick ở phách 1 và 3, snare ở 2 và 4, hi-hat mỗi nửa phách
    bt = t % beat
    beat_no = (t // beat).astype(int) % 4
    kick = np.sin(2 * np.pi * (55 + 90 * np.exp(-bt * 30)) * bt) * np.exp(-bt * 9)
    out += 0.55 * kick * np.isin(beat_no, [0, 2])
    noise = rng.standard_normal(n)
    out += 0.18 * noise * np.exp(-bt * 22) * np.isin(beat_no, [1, 3])
    ht = t % (beat / 2)
    out += 0.05 * noise * np.exp(-ht * 90)
    # tiếng đĩa than
    crackle = (rng.random(n) > 0.9993) * rng.standard_normal(n) * 0.25 + rng.standard_normal(n) * 0.004
    out += crackle
    fade = int(2 * SR)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    out /= np.max(np.abs(out)) * 1.15
    vol = [1.0, 0.45, 0.8, 0.6, 1.0, 0.35, 0.9, 0.7, 0.55, 1.0][seed % 10]  # độ to khác nhau để thử chuẩn hoá
    left = out * vol
    right = np.roll(out, int(0.012 * SR)) * vol  # lệch nhẹ cho rộng stereo
    return np.stack([left, right], axis=1)


SONGS = [
    ("01 - Mưa Trên Phố Cũ", 72, 220.0, True, 186),
    ("02 - Cà Phê Sáng", 84, 261.6, False, 172),
    ("03 - Đêm Không Ngủ", 68, 196.0, True, 195),
    ("04 - Gió Mùa Thu", 78, 293.7, False, 168),
    ("05 - Thư Viện Yên Tĩnh", 70, 233.1, True, 181),
    ("06 - Chuyến Tàu Muộn", 88, 246.9, False, 176),
    ("07 - Mây Trôi", 74, 207.7, True, 190),
    ("08 - Phòng Trọ Nhỏ", 80, 277.2, False, 170),
    ("09 - Ánh Đèn Vàng", 66, 185.0, True, 198),
    ("10 - Hẹn Mai Gặp Lại", 76, 220.0, False, 164),
]


def make_music(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    for i, (name, bpm, root, minor, secs) in enumerate(SONGS):
        out = d / f"{name}.mp3"
        if not out.exists():
            # lọc thấp cho tiếng ấm kiểu lofi, rồi chuẩn đỉnh
            write_mp3(out, song(i, secs, bpm, root, minor), af=f"lowpass=f={2600 + i * 40},volume=1.6,alimiter=limit=0.95")
        print("  nhạc:", out.name)


def make_ambient(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    n = 30 * SR
    rain = rng.standard_normal(n) * 0.3 + (rng.random(n) > 0.9985) * rng.standard_normal(n) * 0.8
    rain /= np.max(np.abs(rain)) * 1.3
    write_mp3(d / "Mưa rơi.mp3", np.stack([rain, np.roll(rain, 997)], axis=1),
              af="lowpass=f=3500,highpass=f=200,volume=2.5,alimiter=limit=0.9")
    crack = (rng.random(n) > 0.9992) * rng.standard_normal(n)
    hum = rng.standard_normal(n) * 0.5
    fire = hum + crack * 3
    fire /= np.max(np.abs(fire)) * 1.3
    write_mp3(d / "Lửa trại.mp3", np.stack([fire, np.roll(fire, 1501)], axis=1),
              af="lowpass=f=900,highpass=f=40,volume=3,alimiter=limit=0.9")
    print("  tiếng nền")


# ---------------- dự án mẫu ----------------
def make_projects(root: Path) -> None:
    v = sorted((root / "Video").glob("*.mp4"))
    music = sorted((root / "Nhac").glob("*.mp3"))
    out_dir = root / "Xuat"
    out_dir.mkdir(exist_ok=True)

    # Dự án 1: đúng ví dụ của người dùng — V1 ×70, V2 ×1, V3 ×1, V4 ×70, V5 ×1, V6 ×70
    p = Project(name="Mẫu - Loop 70 lần")
    for path, n in zip(v, [70, 1, 1, 70, 1, 70]):
        p.video.clips.append(ClipItem(path=str(path), count=n, loop_xfade=1.0, next_xfade=1.5))
    p.video.intro, p.video.intro_xfade = str(root / "Intro-Outro" / "Intro.mp4"), 1.0
    p.video.outro, p.video.outro_xfade = str(root / "Intro-Outro" / "Outro.mp4"), 1.0
    p.video.fit = "blur"
    p.music.tracks = [MusicTrack(path=str(m)) for m in music]
    p.music.order = "shuffle_no_repeat"
    p.music.ambient = [AmbientLayer(path=str(root / "Tieng-nen" / "Mưa rơi.mp3"), volume=35)]
    p.export.output_dir = str(out_dir)
    p.save(str(root / "Du-an-mau - Loop 70 lan.lsproj"))

    # Dự án 2: video 3 tiếng, lặp cả chuỗi, có ảnh tĩnh
    q = Project(name="Mẫu - 3 tiếng lặp chuỗi")
    q.video.clips = [ClipItem(path=str(path), count=3, loop_xfade=1.0, next_xfade=1.0) for path in v[:5]]
    q.video.clips.insert(2, ClipItem(path=str(root / "Anh" / "Ảnh nền 16x9.jpg"), count=1, next_xfade=1.0))
    q.video.order, q.video.length_mode, q.video.target_duration = "shuffle", "target", 3 * 3600
    q.video.fill = "repeat_sequence"
    q.music.tracks = [MusicTrack(path=str(m)) for m in music]
    q.music.order = "shuffle_no_repeat"
    q.music.ambient = [AmbientLayer(path=str(root / "Tieng-nen" / "Lửa trại.mp3"), volume=25)]
    q.music.export_target = 3600
    q.export.output_dir = str(out_dir)
    q.save(str(root / "Du-an-mau - 3 tieng.lsproj"))
    print("  dự án mẫu")


BATCH_GUIDE = """THƯ MỤC MẪU: XUẤT HÀNG LOẠT THEO THƯ MỤC
=========================================

Mỗi thư mục con trong thư mục này = MỘT video:

  Video 01 - Mua dem\\      loop_mua-dem.mp4  (clip nền: tên có chữ "loop")
                            2_hoang-hon.mp4    (cảnh chèn: xếp theo số đầu tên 2_, 3_ …)
                            3_bau-troi-sao.mp4
                            → không có nhạc riêng: dùng playlist của dự án đang mở

  Video 02 - Rung xanh\\    loop_rung-xanh.mp4, 2_bien-dem.mp4, 3_mua-dem.mp4
                            Nhac\\ (3 bài)    → video này dùng nhạc riêng trong thư mục Nhac

  Video 03 - Clip doc\\     loop_clip-doc.mp4 (clip dọc 9:16), 2_hoang-hon.mp4

  _ghi-chu\\               thư mục bắt đầu bằng "_" được bỏ qua (để đồ dùng chung, ghi chú…)

CÁCH THỬ
  1. Mở dự án mẫu "Du-an-mau - Loop 70 lan" (làm KHUÔN: cấu hình xuất, intro/outro, tiếng nền,
     playlist chung… đều lấy từ dự án đang mở).
  2. Thanh bên trái → "Xuất hàng loạt…" (hoặc trang Xuất → "Hàng loạt từ thư mục…").
  3. Bấm "Thư mục mẫu" (hoặc chọn thư mục này), chọn mẫu xếp clip, ví dụ "Nền ×70 xen từng cảnh".
  4. Xem bảng: mỗi dòng là một video, có clip nền, số clip, nhạc, thời lượng.
  5. Bấm "Thêm 3 video vào hàng đợi" → app xuất lần lượt, mỗi video một thư mục riêng.

Với công việc thật: mỗi lần tải clip Google Flow về, để vào một thư mục con theo kiểu trên
(clip nền đặt tên có chữ loop, cảnh chèn đánh số 2_, 3_ …), rồi chạy hàng loạt một lần.
"""


def make_batch_folder(root: Path) -> None:
    """Thư mục mẫu cho "Xuất hàng loạt": 3 thư mục con = 3 video (chép lại từ video/nhạc mẫu)."""
    import shutil
    vid, mus = root / "Video", root / "Nhac"
    v = sorted(vid.glob("*.mp4"))
    songs = sorted(mus.glob("*.mp3"))
    d = root / "Hang-loat"
    shutil.rmtree(d, ignore_errors=True)
    plan = {
        "Video 01 - Mua dem": [("loop_mua-dem.mp4", v[0]), ("2_hoang-hon.mp4", v[1]), ("3_bau-troi-sao.mp4", v[2])],
        "Video 02 - Rung xanh": [("loop_rung-xanh.mp4", v[3]), ("2_bien-dem.mp4", v[4]), ("3_mua-dem.mp4", v[0])],
        "Video 03 - Clip doc": [("loop_clip-doc.mp4", v[5]), ("2_hoang-hon.mp4", v[1])],
    }
    for folder, files in plan.items():
        (d / folder).mkdir(parents=True)
        for name, src in files:
            shutil.copy2(src, d / folder / name)
    (d / "Video 02 - Rung xanh" / "Nhac").mkdir()
    for s in songs[3:6]:
        shutil.copy2(s, d / "Video 02 - Rung xanh" / "Nhac" / s.name)
    (d / "_ghi-chu").mkdir()
    (d / "_ghi-chu" / "doc-toi.txt").write_text("Thư mục bắt đầu bằng _ không được tính là video.\n",
                                                encoding="utf-8")
    (d / "HUONG-DAN.txt").write_text(BATCH_GUIDE, encoding="utf-8")


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "Mau-Test"
    print("Tạo bộ mẫu tại", root)
    make_videos(root / "Video")
    make_bookends(root / "Intro-Outro")
    make_images(root / "Anh")
    make_ambient(root / "Tieng-nen")
    make_music(root / "Nhac")
    make_projects(root)
    make_batch_folder(root)
    print("Xong.")


if __name__ == "__main__":
    main()
