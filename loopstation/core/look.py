"""Màu & Logo: chỉnh màu theo bộ lọc dựng sẵn (có cường độ) + đóng logo / khung PNG trong suốt lên hình.

Áp ngay khi mã hoá từng khối video, nên không làm mất tốc độ xuất (mỗi clip vẫn chỉ mã hoá một lần).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .audio_build import escape_filter_value

# tên hiển thị, chuỗi filter ffmpeg
COLOR_PRESETS = {
    "none": ("Không chỉnh màu", ""),
    "warm": ("Ấm nắng chiều",
             "colorbalance=rs=0.10:gs=0.03:bs=-0.10:rm=0.08:gm=0.02:bm=-0.08:rh=0.05:bh=-0.05,eq=saturation=1.08"),
    "cool": ("Lạnh xanh đêm",
             "colorbalance=rs=-0.08:bs=0.12:rm=-0.06:bm=0.10:rh=-0.03:bh=0.05,eq=saturation=0.95:brightness=-0.02"),
    "vintage": ("Vintage phim cũ", "curves=preset=vintage,eq=saturation=0.85:contrast=0.95"),
    "bw": ("Đen trắng", "hue=s=0,eq=contrast=1.10"),
    "vivid": ("Rực rỡ", "eq=saturation=1.35:contrast=1.06"),
    "teal_orange": ("Điện ảnh Teal & Orange",
                    "colorbalance=rs=-0.12:gs=0.02:bs=0.10:rm=0.02:bm=-0.02:rh=0.12:gh=0.02:bh=-0.12,"
                    "eq=contrast=1.06:saturation=1.10"),
}

LOGO_POS = {
    "top_right": "Góc trên phải",
    "top_left": "Góc trên trái",
    "bottom_right": "Góc dưới phải",
    "bottom_left": "Góc dưới trái",
    "center": "Chính giữa",
    "frame": "Phủ cả khung hình (khung viền, banner)",
}


@dataclass(frozen=True)
class Look:
    color: str = "none"
    strength: int = 100  # % mức áp bộ lọc màu
    logo: str = ""  # đường dẫn PNG (trong suốt)
    logo_opacity: int = 100  # %
    logo_pos: str = "top_right"
    logo_size: int = 14  # % chiều rộng khung hình (bỏ qua khi "frame")

    @property
    def has_color(self) -> bool:
        return self.color in COLOR_PRESETS and self.color != "none" and self.strength > 0

    @property
    def has_logo(self) -> bool:
        return bool(self.logo) and os.path.isfile(self.logo) and self.logo_opacity > 0

    @property
    def active(self) -> bool:
        return self.has_color or self.has_logo

    def key(self) -> str:
        """Phần khoá bộ nhớ đệm: đổi màu / logo (kể cả sửa file logo) thì mã hoá lại."""
        parts = []
        if self.has_color:
            parts.append(f"c2:{self.color}:{self.strength}")  # c2: bản sửa cường độ (khối cũ c: bị ngược)
        if self.has_logo:
            st = os.stat(self.logo)
            parts.append(f"l:{os.path.normcase(os.path.abspath(self.logo))}:{st.st_size}:{st.st_mtime_ns}:"
                         f"{self.logo_opacity}:{self.logo_pos}:{self.logo_size}")
        return "|".join(parts)


def from_settings(vs) -> Look | None:
    look = Look(color=vs.color_preset, strength=vs.color_strength, logo=vs.logo, logo_opacity=vs.logo_opacity,
                logo_pos=vs.logo_pos, logo_size=vs.logo_size)
    return look if look.active else None


def graph(look: Look, inp: str, out: str, w: int, h: int, tag: str = "") -> str:
    """Đoạn filtergraph: [inp] → chỉnh màu → đóng logo → [out]."""
    t = tag or "lk"
    lines = []
    cur = inp
    if look.has_color:
        chain = COLOR_PRESETS[look.color][1]
        if look.strength >= 100:
            lines.append(f"[{cur}]{chain}[{t}c]")
        else:  # trộn với hình gốc theo cường độ
            k = look.strength / 100
            lines.append(f"[{cur}]format=gbrp,split=2[{t}o][{t}g0]")
            lines.append(f"[{t}g0]{chain},format=gbrp[{t}g]")
            # blend normal = lớp trên × k + lớp dưới × (1 − k) → lớp trên phải là hình đã chỉnh màu
            lines.append(f"[{t}g][{t}o]blend=all_mode=normal:all_opacity={k:.3f}[{t}c]")
        cur = f"{t}c"
    if look.has_logo:
        src = escape_filter_value(look.logo.replace("\\", "/"))
        if look.logo_pos == "frame":
            size = f"scale={w}:{h}"
            xy = "x=0:y=0"
        else:
            lw = max(8, int(w * look.logo_size / 100) // 2 * 2)
            size = f"scale={lw}:-1"
            m = int(min(w, h) * 0.035)
            xy = {"top_left": f"x={m}:y={m}", "top_right": f"x=W-w-{m}:y={m}",
                  "bottom_left": f"x={m}:y=H-h-{m}", "bottom_right": f"x=W-w-{m}:y=H-h-{m}",
                  "center": "x=(W-w)/2:y=(H-h)/2"}.get(look.logo_pos, f"x=W-w-{m}:y={m}")
        lines.append(f"movie=filename={src},format=rgba,{size},"
                     f"colorchannelmixer=aa={look.logo_opacity / 100:.3f}[{t}l]")
        lines.append(f"[{cur}][{t}l]overlay={xy}:eof_action=repeat:format=auto[{t}lo]")
        cur = f"{t}lo"
    lines.append(f"[{cur}]null[{out}]")
    return ";".join(lines)


def preview_frame(path: str, is_image: bool, at: float, w: int, h: int, fit: str, look: Look | None,
                  out: str, timeout: float = 30) -> bool:
    """Ảnh xem trước một khung hình (đã chỉnh màu + logo) ở kích thước nhỏ w×h. Trả về True nếu tạo được."""
    from . import ffmpeg_tools as ft
    from .video_build import color_fix, fit_chain, tone_chain
    tone = "" if is_image else tone_chain(path).rstrip(",")
    chain = (f"[0:v]{'' if is_image else color_fix(path)}{fit_chain(fit, w, h)}"
             f"{',' + tone if tone else ''}[pre]")  # màu giống hệt lúc xuất (kể cả HDR → SDR)
    if look is not None and look.active:
        chain += ";" + graph(look, "pre", "lk", w, h, "pv")
        label = "[lk]"
    else:
        label = "[pre]"
    seek = [] if is_image else ["-ss", f"{max(0.0, at):.3f}"]
    r = ft.run([ft.ffmpeg(), "-v", "error", "-y", *seek, "-i", path, "-frames:v", "1", "-filter_complex", chain,
                "-map", label, out], timeout=timeout)
    return r.returncode == 0 and os.path.isfile(out)
