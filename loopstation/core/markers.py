"""File mốc thời gian cho editor: đoạn nào là LOOP, đoạn nào là cảnh THƯỜNG (chỗ nên thêm sound effect).

Xuất 4 dạng:
- .txt  đọc trực tiếp (tiếng Việt)
- .csv  mở bằng Excel / Google Sheets
- .srt  phụ đề: kéo vào Premiere / CapCut / DaVinci thành một track chữ hiện tên từng đoạn trên timeline
- .edl  marker cho DaVinci Resolve (Timeline → Import → Timeline Markers from EDL)
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from . import planner

EDL_START_HOUR = 1  # DaVinci mặc định timeline bắt đầu ở 01:00:00:00


@dataclass
class Mark:
    start: int  # frame
    end: int  # frame (không gồm)
    clip: int
    name: str
    plays: int
    xfade_next: int = 0  # số frame crossfade sang đoạn sau

    @property
    def kind(self) -> str:
        if self.clip == planner.INTRO:
            return "INTRO"
        if self.clip == planner.OUTRO:
            return "OUTRO"
        return "LOOP" if self.plays > 1 else "THƯỜNG"


def build(tl, clip_names: list[str], intro: str = "", outro: str = "") -> list[Mark]:
    """Gộp các lần phát liên tiếp của cùng một clip thành một đoạn."""
    plan, frames = tl.video, tl.frames
    marks: list[Mark] = []
    pos = 0
    for j, (clip, _rnd) in enumerate(plan.plays):
        f = plan.ends.get(j, frames[clip])
        if clip == planner.INTRO:
            name = Path(intro).name if intro else "Intro"
        elif clip == planner.OUTRO:
            name = Path(outro).name if outro else "Outro"
        else:
            name = clip_names[clip] if 0 <= clip < len(clip_names) else f"Clip {clip + 1}"
        last = marks[-1] if marks else None
        if last and last.clip == clip:
            last.end = pos + f
            last.plays += 1
        else:
            if last:
                last.xfade_next = max(0, last.end - pos)
            marks.append(Mark(pos, pos + f, clip, name, 1))
        if j < len(plan.overlaps):
            pos += f - plan.overlaps[j]
    return marks


# ---------- định dạng thời gian ----------
def _sec(frame: int, fps: Fraction) -> float:
    return float(Fraction(frame) / fps)


def clock(frame: int, fps: Fraction) -> str:
    """HH:MM:SS.mmm"""
    ms = round(_sec(frame, fps) * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def timecode(frame: int, fps: Fraction, hour_offset: int = 0) -> str:
    """HH:MM:SS:FF non-drop: đếm khung theo fps danh nghĩa (29.97 → 30), đúng cách DaVinci / Premiere đọc.
    Không đổi qua giây (29.97 fps sẽ lệch 3,6 giây mỗi giờ)."""
    base = max(1, round(float(fps)))
    f = frame + hour_offset * 3600 * base
    return f"{f // (3600 * base):02d}:{f // (60 * base) % 60:02d}:{f // base % 60:02d}:{f % base:02d}"


def _ms(frame: int, fps: Fraction) -> int:
    return round(_sec(frame, fps) * 1000)


def _dur(frames: int, fps: Fraction) -> str:
    s = _sec(frames, fps)
    if s < 60:
        return f"{s:.1f}s"
    t = int(round(s))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def _label(m: Mark) -> str:
    return f"LOOP ×{m.plays}" if m.kind == "LOOP" else m.kind


# ---------- các định dạng file ----------
def to_txt(marks: list[Mark], fps: Fraction, video_name: str, size: tuple[int, int], total: float) -> str:
    fps_txt = f"{float(fps):g}"
    out = [
        "KT Loop Station — MỐC THỜI GIAN CHO EDITOR",
        f"Video: {video_name} · {size[0]}×{size[1]} · {fps_txt} fps · dài {_dur(round(total * float(fps)), fps)}",
        "Đoạn THƯỜNG (cảnh chèn, phát 1 lần) là chỗ nên thêm sound effect. Đoạn LOOP là phần lặp nền.",
        "Mốc chính xác tới từng khung hình. Hai đoạn có crossfade thì chồng lên nhau đúng bằng thời gian nối.",
        "",
        f"{'STT':<4} {'Bắt đầu':<13} {'Kết thúc':<13} {'Dài':>8}  {'Loại':<10} Clip",
    ]
    for k, m in enumerate(marks, 1):
        xf = f"   (nối {_sec(m.xfade_next, fps):.1f}s sang đoạn sau)" if m.xfade_next else ""
        out.append(f"{k:<4} {clock(m.start, fps):<13} {clock(m.end, fps):<13} {_dur(m.end - m.start, fps):>8}  "
                   f"{_label(m):<10} {m.name}{xf}")
    normal = [m for m in marks if m.kind == "THƯỜNG"]
    if normal:
        out += ["", f"CÁC ĐOẠN THƯỜNG — chỗ thêm sound effect ({len(normal)} đoạn):"]
        for m in normal:
            out.append(f"  {clock(m.start, fps)} → {clock(m.end, fps)}   {m.name}")
    out += ["", "File kèm: .csv (Excel) · .srt (kéo vào Premiere / CapCut / DaVinci thành track chữ) · "
                ".edl (DaVinci: Timeline → Import → Timeline Markers from EDL; timeline bắt đầu 01:00:00:00)."]
    return "\n".join(out) + "\n"


def to_csv(marks: list[Mark], fps: Fraction) -> str:
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["STT", "Loại", "Clip", "Số lần phát", "Bắt đầu", "Kết thúc", "Bắt đầu (timecode)",
                 "Kết thúc (timecode)", "Bắt đầu (ms)", "Kết thúc (ms)", "Dài (ms)",
                 "Crossfade sang đoạn sau (ms)", "Khung bắt đầu", "Khung kết thúc"])
    for k, m in enumerate(marks, 1):
        wr.writerow([k, m.kind, m.name, m.plays, clock(m.start, fps), clock(m.end, fps), timecode(m.start, fps),
                     timecode(m.end, fps), _ms(m.start, fps), _ms(m.end, fps), _ms(m.end - m.start, fps),
                     _ms(m.xfade_next, fps), m.start, m.end])
    return buf.getvalue()


def to_srt(marks: list[Mark], fps: Fraction) -> str:
    def t(frame: int) -> str:
        return clock(frame, fps).replace(".", ",")

    out = []
    for k, m in enumerate(marks, 1):
        tag = "★ THƯỜNG — thêm SFX" if m.kind == "THƯỜNG" else _label(m)
        out += [str(k), f"{t(m.start)} --> {t(m.end)}", f"[{tag}] {m.name}", ""]
    return "\n".join(out)


def to_edl(marks: list[Mark], fps: Fraction, title: str) -> str:
    colors = {"THƯỜNG": "ResolveColorRed", "LOOP": "ResolveColorBlue", "INTRO": "ResolveColorGreen",
              "OUTRO": "ResolveColorGreen"}
    out = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    for k, m in enumerate(marks, 1):
        a = timecode(m.start, fps, EDL_START_HOUR)
        b = timecode(m.start + 1, fps, EDL_START_HOUR)
        dur = max(1, m.end - m.start)  # số khung
        name = f"{_label(m)} - {m.name}".replace("|", "/")
        out += [f"{k:03d}  001      V     C        {a} {b} {a} {b}  ",
                f" |C:{colors.get(m.kind, 'ResolveColorBlue')} |M:{name} |D:{dur}", ""]
    return "\n".join(out)


def write_all(marks: list[Mark], fps: Fraction, video: Path, size: tuple[int, int], total: float) -> list[Path]:
    stem = video.with_suffix("")
    files = {
        Path(f"{stem}_moc-thoi-gian.txt"): (to_txt(marks, fps, video.name, size, total), "utf-8"),
        Path(f"{stem}_moc-thoi-gian.csv"): (to_csv(marks, fps), "utf-8-sig"),  # có BOM để Excel đọc đúng dấu
        Path(f"{stem}_moc-thoi-gian.srt"): (to_srt(marks, fps), "utf-8"),
        Path(f"{stem}_markers-davinci.edl"): (to_edl(marks, fps, video.stem), "utf-8"),
    }
    for p, (text, enc) in files.items():
        p.write_text(text, encoding=enc, newline="" if p.suffix == ".csv" else None)
    return list(files)
