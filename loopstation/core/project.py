"""Mô hình dữ liệu project và đọc/ghi file .lsproj (JSON)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_VERSION = 1
PROJECT_EXT = ".lsproj"


SAMPLE_DIR = "mau-test"  # bộ mẫu cài kèm app để tập dùng (Intro / Outro mẫu có chữ "KT Loop Station")


def is_sample_file(path: str) -> bool:
    """File nằm trong bộ mẫu Mau-Test — dùng để nhắc khi lỡ để intro / outro mẫu trong video thật."""
    parts = [x.lower() for x in path.replace("\\", "/").split("/")]
    return SAMPLE_DIR in parts[:-1]


@dataclass
class ClipItem:
    path: str
    enabled: bool = True
    plays_mode: str = "fixed"  # fixed | random | duration (loop cho đủ play_seconds)
    count: int = 1
    min: int = 1
    max: int = 1
    stretch: bool = False
    loop_xfade: float = 0.0  # crossfade giữa các lần loop của clip này (0 = cắt thẳng)
    next_xfade: float = 0.0  # crossfade sang clip kế tiếp
    play_seconds: float = 0.0  # kiểu "duration": loop clip này cho đủ bao nhiêu giây (ví dụ 600 = 10 phút)
    trim_start: float = 0.0  # bỏ bao nhiêu giây ở đầu clip (chỉ lấy đoạn giữa)
    trim_end: float = 0.0  # bỏ bao nhiêu giây ở cuối clip


@dataclass
class AmbientLayer:
    path: str
    enabled: bool = True
    volume: int = 50  # %


@dataclass
class VideoSettings:
    clips: list[ClipItem] = field(default_factory=list)
    order: str = "list"  # list | shuffle
    seed: int = 1
    length_mode: str = "manual"  # manual | target | music
    target_duration: float = 3 * 3600.0
    fill: str = "repeat_sequence"  # repeat_sequence | stretch_marked
    reshuffle_each_round: bool = True
    exact_end: bool = True
    fade_out: float = 3.0
    fit: str = "letterbox"  # letterbox | blur | crop | stretch
    image_duration: float = 8.0  # mỗi ảnh tĩnh hiển thị bao nhiêu giây (một lần phát)
    source_audio: str = "mix"  # off | only | mix — mặc định giữ tiếng gốc clip (trộn với nhạc nếu có)
    source_volume: int = 100
    music_volume: int = 100
    source_level: bool = True  # tự cân độ to tiếng gốc từng clip về cùng mức với nhạc → 100% + 100% = nghe ngang nhau
    intro: str = ""
    intro_xfade: float = 0.0  # crossfade từ intro sang clip đầu
    outro: str = ""
    outro_xfade: float = 0.0  # crossfade từ clip cuối sang outro
    bookend_audio: bool = True  # giữ tiếng gốc của intro/outro
    # màu & logo (core.look)
    color_preset: str = "none"  # none | warm | cool | vintage | bw | vivid | teal_orange
    color_strength: int = 100  # %
    logo: str = ""  # PNG trong suốt: logo góc / khung viền / banner
    logo_opacity: int = 100  # %
    logo_pos: str = "top_right"  # top_left | top_right | bottom_left | bottom_right | center | frame
    logo_size: int = 14  # % chiều rộng khung hình
    look_bookends: bool = False  # áp màu & logo cả lên Intro/Outro


@dataclass
class MusicTrack:
    path: str
    enabled: bool = True
    plays: int = 1
    pinned: bool = False  # bài ghim: luôn có trong file (mọi bản), đặt theo MusicSettings.pin_pos
    volume: int = 100  # % âm lượng riêng của bài (sau khi chuẩn hoá LUFS); 100 = giữ nguyên


@dataclass
class MusicSettings:
    tracks: list[MusicTrack] = field(default_factory=list)
    order: str = "list"  # list | shuffle | shuffle_no_repeat
    seed: int = 1
    crossfade: float = 3.0
    gap: float = 0.0
    fade_in: float = 2.0
    fade_out: float = 5.0
    loudness_enabled: bool = True
    lufs: float = -14.0
    ambient: list[AmbientLayer] = field(default_factory=list)
    # xuất riêng nhạc (không hình)
    export_mode: str = "target"  # target (thời lượng) | rounds (số lượt playlist)
    export_target: float = 3600.0
    export_rounds: int = 2
    export_format: str = "mp3_320"
    versions: int = 1  # kiểu Chỉ nhạc: xuất bao nhiêu bản, mỗi bản một thứ tự phát khác nhau
    pin_pos: str = "first"  # bài ghim: first (mở đầu file) | random (vị trí ngẫu nhiên nhưng chắc chắn có)


@dataclass
class ExportSettings:
    preset: str = "youtube_1080p_h264"  # chỉ quyết định codec (H.264 / HEVC)
    resolution: str = "1080p"  # khoá trong encoders.RESOLUTIONS
    fps: str = "source"  # source | 24 | 25 | 30 | 50 | 60
    encoder: str = "auto"  # auto | nvidia | intel | amd | cpu
    quality: str = "high"  # saving | balanced | high | very_high
    audio: str = "fast"  # fast (AAC 192k) | max (AAC 320k)
    output_dir: str = ""
    filename: str = ""
    tracklist: bool = True
    save_project_copy: bool = True
    bitrate_cap: str = "off"  # off | youtube | mbps | size (encoders.BITRATE_CAPS)
    cap_mbps: float = 8.0  # kiểu "mbps": bitrate hình tối đa
    cap_gb: float = 10.0  # kiểu "size": dung lượng file tối đa
    own_folder: bool = True  # mỗi lần xuất tạo một thư mục riêng chứa video + file kèm
    markers: bool = True  # xuất kèm file mốc thời gian (đoạn loop / đoạn thường) cho editor


OUTPUT_KINDS = ("video_music", "video_only", "music_only")


@dataclass
class Project:
    name: str = "Dự án mới"
    # (không lưu) lưu ý khi mở dự án, ví dụ thời lượng vô lý đã được tự đưa về mức tối đa
    notes: list = field(default_factory=list, compare=False, repr=False)
    output_kind: str = "video_music"  # video_music | video_only | music_only
    video: VideoSettings = field(default_factory=VideoSettings)
    music: MusicSettings = field(default_factory=MusicSettings)
    export: ExportSettings = field(default_factory=ExportSettings)

    # ---------- đọc / ghi ----------
    def to_dict(self, base_dir: str | None = None) -> dict:
        abs_paths: dict[str, str] = {}

        def p(path: str) -> str:
            stored = _to_stored_path(path, base_dir)
            if path and stored != path.replace("\\", "/") and not path.startswith("builtin:"):
                abs_paths[stored] = os.path.abspath(path).replace("\\", "/")  # dự phòng khi chỉ di chuyển file dự án
            return stored

        v, m, e = self.video, self.music, self.export
        data = self._to_dict(p, base_dir)
        if abs_paths:
            data["abs_paths"] = abs_paths
        return data

    def _to_dict(self, p, base_dir: str | None) -> dict:
        v, m, e = self.video, self.music, self.export
        return {
            "version": PROJECT_VERSION,
            "name": self.name,
            "output_kind": self.output_kind,
            "video": {
                "order": v.order,
                "seed": v.seed,
                "length_mode": v.length_mode,
                "target_duration": format_hms(v.target_duration),
                "fill": v.fill,
                "reshuffle_each_round": v.reshuffle_each_round,
                "exact_end": v.exact_end,
                "fade_out": v.fade_out,
                "fit": v.fit,
                "image_duration": v.image_duration,
                "source_audio": v.source_audio,
                "source_volume": v.source_volume,
                "music_volume": v.music_volume,
                "source_level": v.source_level,
                "intro": {"path": p(v.intro) if v.intro else "", "crossfade": v.intro_xfade},
                "outro": {"path": p(v.outro) if v.outro else "", "crossfade": v.outro_xfade},
                "bookend_audio": v.bookend_audio,
                "look": {"color": v.color_preset, "strength": v.color_strength,
                         "logo": p(v.logo) if v.logo else "", "logo_opacity": v.logo_opacity,
                         "logo_pos": v.logo_pos, "logo_size": v.logo_size, "bookends": v.look_bookends},
                "clips": [
                    {
                        "path": p(c.path),
                        "enabled": c.enabled,
                        "plays": (
                            {"mode": "fixed", "count": c.count} if c.plays_mode == "fixed"
                            else {"mode": "duration", "seconds": c.play_seconds} if c.plays_mode == "duration"
                            else {"mode": "random", "min": c.min, "max": c.max}
                        ),
                        "stretch": c.stretch,
                        "loop_crossfade": c.loop_xfade,
                        "next_crossfade": c.next_xfade,
                        "trim": {"start": c.trim_start, "end": c.trim_end},
                    }
                    for c in v.clips
                ],
            },
            "music": {
                "order": m.order,
                "versions": m.versions,
                "pin_pos": m.pin_pos,
                "seed": m.seed,
                "crossfade": m.crossfade,
                "gap": m.gap,
                "fade_in": m.fade_in,
                "fade_out": m.fade_out,
                "loudness": {"enabled": m.loudness_enabled, "lufs": m.lufs},
                "tracks": [
                    {"path": p(t.path), "enabled": t.enabled, "plays": t.plays,
                     **({"pinned": True} if t.pinned else {}),
                     **({"volume": t.volume} if t.volume != 100 else {})}
                    for t in m.tracks
                ],
                "audio_export": {"mode": m.export_mode, "target": format_hms(m.export_target),
                                 "rounds": m.export_rounds, "format": m.export_format},
                "ambient": [
                    {"path": p(a.path), "enabled": a.enabled, "volume": a.volume}
                    for a in m.ambient
                ],
            },
            "export": {
                "preset": e.preset,
                "resolution": e.resolution,
                "fps": e.fps,
                "encoder": e.encoder,
                "quality": e.quality,
                "audio": e.audio,
                "output_dir": _to_stored_dir(e.output_dir, base_dir),
                "filename": e.filename,
                "tracklist": e.tracklist,
                "save_project_copy": e.save_project_copy,
                "bitrate_cap": e.bitrate_cap,
                "cap_mbps": e.cap_mbps,
                "cap_gb": e.cap_gb,
                "own_folder": e.own_folder,
                "markers": e.markers,
            },
        }

    @classmethod
    def from_dict(cls, d: dict, base_dir: str | None = None) -> "Project":
        abs_paths = d.get("abs_paths") if isinstance(d.get("abs_paths"), dict) else {}

        def p(path: str) -> str:
            real = _from_stored_path(path, base_dir)
            # file dự án bị chuyển sang thư mục khác (media vẫn ở chỗ cũ): đường dẫn tương đối không còn đúng
            if path in abs_paths and not os.path.exists(real) and os.path.exists(abs_paths[path]):
                return str(Path(abs_paths[path]))
            return real

        proj = cls(name=d.get("name", "Dự án"))
        kind = d.get("output_kind", "video_music")
        proj.output_kind = kind if kind in OUTPUT_KINDS else "video_music"
        vd = d.get("video", {})
        v = proj.video
        v.order = vd.get("order", v.order)
        v.seed = int(vd.get("seed", v.seed))
        v.length_mode = vd.get("length_mode", v.length_mode)
        v.target_duration = parse_hms(str(vd.get("target_duration", format_hms(v.target_duration))))
        if v.target_duration > MAX_DURATION:  # dự án cũ lỡ gõ số quá lớn (ví dụ 16666 giờ) → mở app bị treo
            proj.notes.append(f"Thời lượng video {format_hms(v.target_duration)} quá dài — đã đưa về tối đa "
                              f"{MAX_DURATION // 3600} giờ.")
            v.target_duration = float(MAX_DURATION)
        v.fill = vd.get("fill", v.fill)
        v.reshuffle_each_round = bool(vd.get("reshuffle_each_round", v.reshuffle_each_round))
        v.exact_end = bool(vd.get("exact_end", v.exact_end))
        v.fade_out = float(vd.get("fade_out", v.fade_out))
        v.fit = vd.get("fit", v.fit)
        v.image_duration = float(vd.get("image_duration", v.image_duration))
        v.source_audio = vd.get("source_audio", v.source_audio)
        v.source_volume = int(vd.get("source_volume", v.source_volume))
        v.music_volume = int(vd.get("music_volume", v.music_volume))
        v.source_level = bool(vd.get("source_level", v.source_level))
        for key in ("intro", "outro"):
            bd = vd.get(key) or {}
            setattr(v, key, p(bd["path"]) if bd.get("path") else "")
            setattr(v, f"{key}_xfade", float(bd.get("crossfade", 0.0)))
        v.bookend_audio = bool(vd.get("bookend_audio", v.bookend_audio))
        lk = vd.get("look") or {}
        v.color_preset = str(lk.get("color", v.color_preset))
        v.color_strength = max(0, min(100, int(lk.get("strength", v.color_strength))))
        v.logo = p(lk["logo"]) if lk.get("logo") else ""
        v.logo_opacity = max(0, min(100, int(lk.get("logo_opacity", v.logo_opacity))))
        v.logo_pos = str(lk.get("logo_pos", v.logo_pos))
        v.logo_size = max(2, min(100, int(lk.get("logo_size", v.logo_size))))
        v.look_bookends = bool(lk.get("bookends", v.look_bookends))
        for cd in vd.get("clips", []):
            plays = cd.get("plays", {"mode": "fixed", "count": 1})
            c = ClipItem(path=p(cd["path"]), enabled=bool(cd.get("enabled", True)),
                         stretch=bool(cd.get("stretch", False)),
                         loop_xfade=float(cd.get("loop_crossfade", 0.0)),
                         next_xfade=float(cd.get("next_crossfade", 0.0)),
                         trim_start=max(0.0, float((cd.get("trim") or {}).get("start", 0.0))),
                         trim_end=max(0.0, float((cd.get("trim") or {}).get("end", 0.0))))
            if plays.get("mode") == "random":
                c.plays_mode = "random"
                c.min = int(plays.get("min", 1))
                c.max = int(plays.get("max", c.min))
            elif plays.get("mode") == "duration":
                c.plays_mode = "duration"
                c.play_seconds = max(0.0, float(plays.get("seconds", 0)))
                c.count = c.min = c.max = 1 if c.play_seconds > 0 else 0  # số lần thật được tính khi dựng timeline
            else:
                c.count = int(plays.get("count", 1))
            v.clips.append(c)

        md = d.get("music", {})
        m = proj.music
        m.order = md.get("order", m.order)
        m.seed = int(md.get("seed", m.seed))
        m.versions = max(1, min(99, int(md.get("versions", m.versions))))
        m.pin_pos = md.get("pin_pos", m.pin_pos) if md.get("pin_pos") in ("first", "random") else m.pin_pos
        m.crossfade = float(md.get("crossfade", m.crossfade))
        m.gap = float(md.get("gap", m.gap))
        m.fade_in = float(md.get("fade_in", m.fade_in))
        m.fade_out = float(md.get("fade_out", m.fade_out))
        ld = md.get("loudness", {})
        m.loudness_enabled = bool(ld.get("enabled", m.loudness_enabled))
        m.lufs = float(ld.get("lufs", m.lufs))
        for td in md.get("tracks", []):
            m.tracks.append(MusicTrack(path=p(td["path"]), enabled=bool(td.get("enabled", True)),
                                       plays=int(td.get("plays", 1)), pinned=bool(td.get("pinned", False)),
                                       volume=max(0, min(200, int(td.get("volume", 100))))))
        ae = md.get("audio_export", {})
        m.export_mode = ae.get("mode", m.export_mode)
        m.export_target = parse_hms(str(ae.get("target", format_hms(m.export_target))))
        if m.export_target > MAX_DURATION:
            proj.notes.append(f"Độ dài file nhạc {format_hms(m.export_target)} quá dài — đã đưa về tối đa "
                              f"{MAX_DURATION // 3600} giờ.")
            m.export_target = float(MAX_DURATION)
        m.export_rounds = max(1, min(999, int(ae.get("rounds", m.export_rounds))))
        m.export_format = ae.get("format", m.export_format)
        for ad in md.get("ambient", []):
            m.ambient.append(AmbientLayer(path=p(ad["path"]), enabled=bool(ad.get("enabled", True)),
                                          volume=int(ad.get("volume", 50))))

        ed = d.get("export", {})
        e = proj.export
        for key in ("preset", "resolution", "fps", "encoder", "quality", "audio", "output_dir", "filename"):
            if key in ed:
                setattr(e, key, ed[key])
        if e.output_dir and base_dir and not os.path.isabs(e.output_dir):  # thư mục xuất nằm trong thư mục dự án
            e.output_dir = str(Path(os.path.normpath(os.path.join(base_dir, e.output_dir))))
        e.tracklist = bool(ed.get("tracklist", e.tracklist))
        e.save_project_copy = bool(ed.get("save_project_copy", e.save_project_copy))
        e.bitrate_cap = str(ed.get("bitrate_cap", e.bitrate_cap))
        e.cap_mbps = max(0.5, float(ed.get("cap_mbps", e.cap_mbps)))
        e.cap_gb = max(0.1, float(ed.get("cap_gb", e.cap_gb)))
        e.own_folder = bool(ed.get("own_folder", e.own_folder))
        e.markers = bool(ed.get("markers", e.markers))
        return proj

    def save(self, path: str) -> None:
        base = str(Path(path).resolve().parent)
        data = self.to_dict(base)
        atomic_write(Path(path), json.dumps(data, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: str) -> "Project":
        base = str(Path(path).resolve().parent)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data, base)


MAX_DURATION = 48 * 3600  # video / file nhạc dài tối đa 48 giờ (YouTube nhận tối đa 12 giờ); dài hơn làm app treo
MAX_PLAYS = 99_999  # số lần phát tối đa của một clip


def atomic_write(path: Path, text: str) -> None:
    """Ghi ra file tạm rồi đổi tên: mất điện / đầy ổ giữa chừng không làm hỏng file cũ."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _to_stored_path(path: str, base_dir: str | None) -> str:
    if path.startswith("builtin:"):  # tiếng nền dựng sẵn của app: không phải đường dẫn file
        return path
    if not base_dir:
        return path.replace("\\", "/")
    try:
        if os.path.splitdrive(path)[0].lower() == os.path.splitdrive(base_dir)[0].lower():
            return os.path.relpath(path, base_dir).replace("\\", "/")
    except ValueError:
        pass
    return path.replace("\\", "/")


def _to_stored_dir(path: str, base_dir: str | None) -> str:
    """Thư mục xuất: chỉ lưu tương đối khi nằm TRONG thư mục dự án (mang cả thư mục dự án sang máy khác vẫn đúng);
    thư mục ở chỗ khác (ví dụ D:/Videos) giữ nguyên đường dẫn đầy đủ."""
    if not path or not base_dir:
        return path
    try:
        rel = os.path.relpath(path, base_dir)
    except ValueError:  # khác ổ đĩa
        return path
    if rel == "." or rel.startswith(".."):
        return path
    return rel.replace("\\", "/")


def _from_stored_path(path: str, base_dir: str | None) -> str:
    if path.startswith("builtin:"):
        return path
    if base_dir and not os.path.isabs(path):
        path = os.path.normpath(os.path.join(base_dir, path))
    return str(Path(path))


def format_hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def parse_hms(text: str) -> float:
    parts = [float(x) for x in text.strip().split(":")]
    total = 0.0
    for x in parts:
        total = total * 60 + x
    return total
