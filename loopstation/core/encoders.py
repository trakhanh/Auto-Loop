"""Nhận diện encoder GPU/CPU, preset xuất và tham số chất lượng."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import ffmpeg_tools as ft

VENDORS = ["nvidia", "intel", "amd", "cpu"]
VENDOR_LABELS = {
    "auto": "Tự động (ưu tiên GPU)",
    "nvidia": "NVIDIA (NVENC)",
    "intel": "Intel (Quick Sync)",
    "amd": "AMD (AMF)",
    "cpu": "CPU (chậm hơn, luôn chạy được)",
}

ENCODERS = {
    "h264": {"nvidia": "h264_nvenc", "intel": "h264_qsv", "amd": "h264_amf", "cpu": "libx264"},
    "hevc": {"nvidia": "hevc_nvenc", "intel": "hevc_qsv", "amd": "hevc_amf", "cpu": "libx265"},
}

QUALITY_LABELS = {"saving": "Tiết kiệm dung lượng (nhẹ nhất)", "balanced": "Cân bằng", "high": "Cao",
                  "very_high": "Rất cao"}
QUALITY_INDEX = {k: i for i, k in enumerate(QUALITY_LABELS)}


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    codec: str
    container: str = "mp4"


# giữ khoá cũ để mở được dự án đã lưu
PRESETS = {
    p.key: p
    for p in [
        Preset("youtube_1080p_h264", "H.264 — tương thích nhất (YouTube, mọi máy)", "h264"),
        Preset("youtube_1080p_hevc", "H.265/HEVC — file nhẹ hơn ~40%", "hevc"),
    ]
}

# (nhãn, rộng, cao); "source" = theo clip video đầu tiên
RESOLUTIONS = {
    "source": ("Theo clip đầu tiên", 0, 0),
    "720p": ("720p — 1280×720", 1280, 720),
    "1080p": ("1080p — 1920×1080 (mặc định)", 1920, 1080),
    "1440p": ("2K — 2560×1440", 2560, 1440),
    "4k": ("4K — 3840×2160", 3840, 2160),
    "vertical": ("Dọc 9:16 — 1080×1920 (Shorts/TikTok)", 1080, 1920),
    "square": ("Vuông 1:1 — 1080×1080", 1080, 1080),
}

def res_name(w: int, h: int) -> str:
    name = {(3840, 2160): "4K", (2560, 1440): "2K", (1920, 1080): "1080p", (1280, 720): "720p"}.get((max(w, h), min(w, h)))
    return (f"{name} dọc" if h > w else name) if name else f"{w}×{h}"


def res_key(w: int, h: int) -> str:
    """Khoá RESOLUTIONS đúng bằng w×h; không có thì "source" (theo clip đầu tiên)."""
    for k, (_, rw, rh) in RESOLUTIONS.items():
        if (rw, rh) == (w, h):
            return k
    return "source"


def output_advice(src_w: int, src_h: int, src_fps: float, out_w: int, out_h: int, out_fps: float) -> tuple[str, str, bool]:
    """Gợi ý ngay dưới ô Độ phân giải: (chữ, tone "warn"/"success"/"", có nên bấm "Theo clip gốc").
    Đổi độ phân giải / fps là làm lại từng khung: phóng to không nét hơn, tăng fps chỉ lặp khung."""
    if min(src_w, src_h) <= 0 or min(out_w, out_h) <= 0:
        return "", "", False
    src, out = res_name(src_w, src_h), res_name(out_w, out_h)
    r = min(out_w, out_h) / min(src_w, src_h)
    parts, warn = [], False
    if r > 1.15:
        parts.append(f"Clip gốc {src}: xuất {out} <b>không nét hơn</b>, file nặng gấp ~{out_w * out_h / (src_w * src_h):.1f} lần")
        warn = True
    elif r < 0.87:
        parts.append(f"Clip gốc {src}, thu nhỏ còn {out}: file nhẹ hơn, vẫn nét")
    else:
        parts.append(f"✓ Bằng clip gốc ({src}): giữ nguyên độ nét")
    fps_off = False
    if src_fps > 0 and out_fps > src_fps + 0.5:
        parts.append(f"{out_fps:g} fps chỉ lặp khung của clip {src_fps:g} fps, <b>không mượt hơn</b>")
        warn = fps_off = True
    elif src_fps > 0 and out_fps < src_fps - 0.5:
        parts.append(f"{src_fps:g} → {out_fps:g} fps: bỏ bớt khung, chuyển động kém mượt hơn chút")
        warn = fps_off = True
    same = 0.87 <= r <= 1.15 and not fps_off
    return " · ".join(parts) + ".", "warn" if warn else ("success" if same else ""), not same


FPS_CHOICES = {"source": "Theo clip chính (phát lâu nhất)", "24": "24", "25": "25", "30": "30", "50": "50", "60": "60"}


AUDIO_LABELS = {
    "fast": "AAC 192 kbps — nhanh (khuyên dùng)",
    "max": "AAC 320 kbps — chậm hơn khoảng 10 lần",
}


@dataclass(frozen=True)
class AudioFormat:
    key: str
    label: str
    ext: str
    codec: tuple[str, ...]

    def args(self, available: dict[str, list[str]]) -> list[str]:
        if self.key == "m4a":
            return audio_args("fast", available)
        return list(self.codec)


AUDIO_FORMATS = {
    f.key: f
    for f in [
        AudioFormat("mp3_320", "MP3 320 kbps", ".mp3", ("-c:a", "libmp3lame", "-b:a", "320k")),
        AudioFormat("mp3_192", "MP3 192 kbps (nhẹ)", ".mp3", ("-c:a", "libmp3lame", "-b:a", "192k")),
        AudioFormat("m4a", "M4A — AAC 192 kbps", ".m4a", ()),
        AudioFormat("flac", "FLAC — không mất chất lượng", ".flac", ("-c:a", "flac")),
        AudioFormat("wav", "WAV 16-bit — không nén", ".wav", ("-c:a", "pcm_s16le", "-rf64", "auto")),
    ]
}


def audio_args(choice: str, available: dict[str, list[str]]) -> list[str]:
    """`aac_mf` (Media Foundation của Windows) nhanh hơn AAC tích hợp của ffmpeg rất nhiều."""
    if choice == "max":
        return ["-c:a", "aac", "-b:a", "320k"]
    if "mf" in available.get("audio", []):
        return ["-c:a", "aac_mf", "-b:a", "192k"]
    return ["-c:a", "aac", "-aac_coder", "fast", "-b:a", "192k"]


_TEST_CACHE: dict[str, bool] = {}


def clear_cache() -> None:
    _TEST_CACHE.clear()


def _test_audio_mf() -> bool:
    if "aac_mf" in _TEST_CACHE:
        return _TEST_CACHE["aac_mf"]
    try:
        r = ft.run([ft.ffmpeg(), "-hide_banner", "-v", "error", "-f", "lavfi",
                    "-i", "anullsrc=r=48000:cl=stereo", "-t", "0.3",
                    "-c:a", "aac_mf", "-b:a", "192k", "-f", "null", "-"], timeout=15)
        ok = r.returncode == 0
    except Exception:  # noqa: BLE001
        ok = False
    _TEST_CACHE["aac_mf"] = ok
    return ok


def _test(encoder: str) -> bool:
    if encoder in _TEST_CACHE:
        return _TEST_CACHE[encoder]
    pix = "nv12" if encoder.endswith("_qsv") else "yuv420p"
    try:
        r = ft.run([ft.ffmpeg(), "-hide_banner", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=black:s=640x360:r=24:d=0.3", "-pix_fmt", pix,
                    "-c:v", encoder, "-f", "null", "-"], timeout=15)
        ok = r.returncode == 0
    except Exception:  # noqa: BLE001
        ok = False
    _TEST_CACHE[encoder] = ok
    return ok


def detect() -> dict[str, list[str]]:
    """Trả về {codec: [vendor chạy được, theo thứ tự ưu tiên]}. CPU luôn có."""
    jobs = [(codec, vendor, enc) for codec, m in ENCODERS.items()
            for vendor, enc in m.items() if vendor != "cpu"]
    with ThreadPoolExecutor(max_workers=4) as ex:
        mf = ex.submit(_test_audio_mf)
        results = list(ex.map(lambda j: _test(j[2]), jobs))
    out: dict[str, list[str]] = {c: [] for c in ENCODERS}
    for (codec, vendor, _), ok in zip(jobs, results):
        if ok:
            out[codec].append(vendor)
    for codec in out:
        out[codec].sort(key=VENDORS.index)
        out[codec].append("cpu")
    out["audio"] = ["mf"] if mf.result() else []
    return out


def pick(codec: str, choice: str, available: dict[str, list[str]]) -> str:
    """Chọn tên encoder ffmpeg theo lựa chọn người dùng."""
    vendors = available.get(codec, ["cpu"])
    if choice == "auto" or choice not in vendors:
        choice = vendors[0]
    return ENCODERS[codec][choice]


def is_hardware(encoder: str) -> bool:
    return not encoder.startswith("lib")


def pix_fmt(encoder: str) -> str:
    return "nv12" if encoder.endswith("_qsv") else "yuv420p"


def encoder_args(encoder: str, quality: str, gop: int, maxrate_kbps: int = 0, strict: bool = False) -> list[str]:
    """Tham số mã hoá theo mức chất lượng. `maxrate_kbps` > 0: chặn bitrate đỉnh (giới hạn dung lượng).
    `strict`: giới hạn cứng do người dùng đặt (Mbps / GB) — NVENC chuyển sang VBR theo bitrate, vì kiểu theo
    chất lượng (cq) của NVENC vượt trần 20–50% khi video ghép từ nhiều khối ngắn."""
    q = QUALITY_INDEX.get(quality, 2)
    common = ["-c:v", encoder, "-g", str(gop)]
    cap = []
    if maxrate_kbps > 0:
        cap = ["-maxrate", f"{maxrate_kbps}k", "-bufsize", f"{maxrate_kbps * 2}k"]
    if encoder == "libx264":
        return common + ["-preset", ["medium", "medium", "slow", "slow"][q], "-crf", ["24", "21", "18", "16"][q],
                         "-profile:v", "high", *cap]
    if encoder == "libx265":
        return common + ["-preset", "medium", "-crf", ["26", "23", "20", "18"][q],
                         "-x265-params", "log-level=error", *cap]
    if encoder in ("h264_nvenc", "hevc_nvenc") and maxrate_kbps > 0 and strict:
        return common + ["-preset", ["p5", "p5", "p6", "p7"][q], "-tune", "hq", "-rc", "vbr",
                         "-b:v", f"{maxrate_kbps * 8 // 10}k", "-maxrate", f"{maxrate_kbps}k",
                         "-bufsize", f"{maxrate_kbps}k", "-spatial-aq", "1",
                         "-profile:v", "high" if encoder == "h264_nvenc" else "main"]
    if encoder == "h264_nvenc":
        return common + ["-preset", ["p5", "p5", "p6", "p7"][q], "-tune", "hq", "-rc", "vbr",
                         "-cq", ["26", "23", "20", "18"][q], "-b:v", "0", "-spatial-aq", "1",
                         "-profile:v", "high", *cap]
    if encoder == "hevc_nvenc":
        return common + ["-preset", ["p5", "p5", "p6", "p7"][q], "-tune", "hq", "-rc", "vbr",
                         "-cq", ["28", "25", "22", "20"][q], "-b:v", "0", "-spatial-aq", "1",
                         "-profile:v", "main", *cap]
    if encoder in ("h264_qsv", "hevc_qsv"):
        preset = ["medium", "medium", "slow", "veryslow"][q]
        if maxrate_kbps > 0:  # ICQ không nhận maxrate → dùng VBR có trần
            return common + ["-preset", preset, "-b:v", f"{maxrate_kbps * 7 // 10}k", *cap]
        base = [26, 23, 20, 18] if encoder == "h264_qsv" else [28, 25, 22, 20]
        return common + ["-preset", preset, "-global_quality", str(base[q])]
    if encoder in ("h264_amf", "hevc_amf"):
        if maxrate_kbps > 0:
            return common + ["-quality", "quality", "-rc", "vbr_peak", "-b:v", f"{maxrate_kbps * 7 // 10}k", *cap]
        base = [25, 22, 19, 17] if encoder == "h264_amf" else [27, 24, 21, 19]
        return common + ["-quality", "quality", "-rc", "cqp",
                         "-qp_i", str(base[q]), "-qp_p", str(base[q] + 2)]
    return common + cap


# ---------- giới hạn bitrate / dung lượng ----------
BITRATE_CAPS = {
    "off": "Tự động theo Chất lượng hình ảnh (không chặn)",
    "youtube": "Mức YouTube khuyên dùng",
    "mbps": "Tự đặt bitrate",
    "size": "Theo dung lượng file tối đa (GB)",
}
MB_PER_HOUR_PER_MBPS = 450  # 1 Mbps × 3600 giây = 3600 Mb = 450 MB


def youtube_mbps(w: int, h: int, fps: float) -> float:
    """Bitrate YouTube khuyến nghị cho video SDR (Mbps)."""
    px = max(w, h) * min(w, h)
    hi = fps > 31
    if px >= 3840 * 2160 * 0.9:
        return 66.0 if hi else 44.0
    if px >= 2560 * 1440 * 0.9:
        return 24.0 if hi else 16.0
    if px >= 1920 * 1080 * 0.9:
        return 12.0 if hi else 8.0
    if px >= 1280 * 720 * 0.9:
        return 7.5 if hi else 5.0
    return 4.0 if hi else 2.5


BLOCK_BURST_S = 0.3  # x264/x265: mỗi khối mã hoá riêng "vượt" khoảng 0,3 giây bitrate ở đầu (bộ đệm VBV đầy sẵn)


def cap_blocks(encoder: str, n_blocks: int) -> int:
    """Số khối dùng để giảm trần: chỉ x264/x265 (GPU ở giới hạn cứng đã dùng VBR theo bitrate, không vượt)."""
    return n_blocks if not is_hardware(encoder) else 0


def block_factor(cap: str, total: float, n_blocks: int) -> float:
    """Hệ số giảm trần bitrate để TỔNG file không vượt mức đặt: video ghép từ nhiều khối ngắn (thân clip + đoạn
    crossfade), mỗi khối bắt đầu bằng khung gốc được phép vượt trần một chút. Chỉ áp cho mức tự đặt / theo dung lượng."""
    if cap not in ("mbps", "size") or total <= 0 or n_blocks <= 0:
        return 1.0
    return max(0.5, total / (total + BLOCK_BURST_S * n_blocks))


def maxrate_kbps(cap: str, value: float, w: int, h: int, fps: float, total: float, audio_kbps: int = 192,
                 n_blocks: int = 0) -> int:
    """Trần bitrate hình (kbps) theo lựa chọn giới hạn; 0 = không giới hạn."""
    if cap == "youtube":
        return int(youtube_mbps(w, h, fps) * 1000)
    k = block_factor(cap, total, n_blocks)
    if cap == "mbps" and value > 0:
        return max(300, int(value * 1000 * k))
    if cap == "size" and value > 0 and total > 0:
        bits = value * 1024 ** 3 * 8 * 0.97  # chừa 3% cho phần khung chứa mp4
        return max(300, int((bits / total / 1000 - audio_kbps) * k))
    return 0
