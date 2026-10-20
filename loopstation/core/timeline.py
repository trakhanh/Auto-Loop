"""Gộp project + thông tin media thành timeline hoàn chỉnh (dùng cho cả xem trước và render)."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from fractions import Fraction

from . import planner
from .encoders import RESOLUTIONS
from .probe import MediaInfo, frames_at, probe, probe_many
from .project import MAX_DURATION, Project

COMMON_FPS = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001),
              Fraction(30), Fraction(50), Fraction(60000, 1001), Fraction(60)]


@dataclass
class Timeline:
    fps: Fraction = Fraction(30)
    width: int = 1920
    height: int = 1080
    clip_infos: dict[int, MediaInfo] = field(default_factory=dict)
    frames: dict[int, int] = field(default_factory=dict)
    video: planner.VideoPlan | None = None
    track_infos: dict[int, MediaInfo] = field(default_factory=dict)
    track_durations: dict[int, float] = field(default_factory=dict)
    ambient_infos: dict[int, MediaInfo] = field(default_factory=dict)
    audible: dict[int, bool] = field(default_factory=dict)  # clip nào được giữ tiếng gốc
    offsets: dict[int, int] = field(default_factory=dict)  # số frame bỏ ở đầu mỗi clip (cắt đoạn lấy)
    music_items: list[planner.MusicItem] = field(default_factory=list)
    use_music: bool = False
    use_source: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    audio_total: float | None = None  # chế độ xuất riêng nhạc
    version_seeds: list[int] = field(default_factory=list)  # xuất nhiều bản: hạt giống thứ tự của từng bản

    @property
    def total(self) -> float:
        if self.audio_total is not None:
            return self.audio_total
        return self.video.total_seconds if self.video and not self.video.error else 0.0

    @property
    def has_audio(self) -> bool:
        return self.use_music or self.use_source or bool(self.ambient_infos)

    @property
    def ok(self) -> bool:
        return not self.errors

    def estimate_bytes(self) -> float:
        """Ước tính dung lượng file xuất theo bitrate của clip nguồn (khối được lặp lại nên
        dung lượng tỉ lệ thuận với số lần phát)."""
        if not self.video or self.video.error:
            return 0.0
        total = 0.0
        for clip, n, _ in self.video.all_plays():  # bỏ qua phần chồng crossfade (ước tính)
            info = self.clip_infos[clip]
            try:
                rate = 1.0e6 if info.is_image else os.path.getsize(info.path) / max(info.duration, 0.1)
            except OSError:
                rate = 1.0e6
            total += n * self.frames[clip] / float(self.fps) * rate * 1.3
        return total + 192_000 / 8 * self.total


def snap_fps(fps: Fraction) -> Fraction:
    if fps <= 0:
        return Fraction(30)
    best = min(COMMON_FPS, key=lambda c: abs(float(fps) / float(c) - 1))
    if abs(float(fps) / float(best) - 1) < 0.002:
        return best
    return Fraction(min(60, max(1, round(float(fps)))))


def build(project: Project) -> Timeline:
    tl = Timeline()
    vs, ms, ex = project.video, project.music, project.export

    # ----- clip -----
    # chỉ các clip thực sự được phát (bật và số lần phát > 0)
    used = [i for i, c in enumerate(vs.clips)
            if c.enabled and (c.count > 0 if c.plays_mode == "fixed" else max(c.min, c.max) > 0)]
    infos = probe_many([vs.clips[i].path for i in used])
    for i, info in zip(used, infos):
        if info.ok and info.has_video:
            tl.clip_infos[i] = info
        else:
            name = vs.clips[i].path
            tl.warnings.append(f"Bỏ qua clip lỗi: {name} ({info.error or 'không có hình'})")
    if not tl.clip_infos:
        tl.errors.append("Chưa có clip video hợp lệ nào được bật.")
        return tl
    videos = [tl.clip_infos[k] for k in sorted(tl.clip_infos) if not tl.clip_infos[k].is_image]
    first = videos[0] if videos else None
    if ex.fps != "source":
        tl.fps = Fraction(int(ex.fps))
    else:
        tl.fps = snap_fps(first.fps) if first else Fraction(30)
    _, w, h = RESOLUTIONS.get(ex.resolution, RESOLUTIONS["1080p"])
    if not w:  # theo clip đầu tiên (ảnh nếu không có video)
        ref = first or tl.clip_infos[min(tl.clip_infos)]
        w, h = ref.width // 2 * 2, ref.height // 2 * 2
    tl.width, tl.height = max(2, w), max(2, h)
    for key, path, label in ((planner.INTRO, vs.intro, "intro"), (planner.OUTRO, vs.outro, "outro")):
        if not path:
            continue
        info = probe(path)
        if info.ok and info.has_video:
            tl.clip_infos[key] = info
        else:
            tl.warnings.append(f"Bỏ qua {label} lỗi: {path} ({info.error or 'không có hình'})")
    if any(snap_fps(inf.fps) != tl.fps for inf in tl.clip_infos.values() if not inf.is_image):
        tl.warnings.append(f"Có clip khác {float(tl.fps):g} fps — sẽ được đổi về {float(tl.fps):g} fps.")
    portrait = tl.height > tl.width
    if vs.fit == "letterbox" and any((inf.height > inf.width) != portrait and inf.width != inf.height
                                     for inf in tl.clip_infos.values()):
        tl.warnings.append("Có clip khác hướng khung (ngang/dọc) — nên chọn 'Nền mờ' hoặc "
                           "'Cắt cho đầy khung' thay cho viền đen.")
    if videos and min(tl.width, tl.height) > 1.5 * max(min(i.width, i.height) for i in videos):
        tl.warnings.append(f"Đang phóng to clip lên {tl.width}×{tl.height} — hình không nét hơn, nhưng "
                           "YouTube cấp chất lượng nén tốt hơn cho video 2K/4K.")
    tl.frames = {i: frames_at(inf, tl.fps, vs.image_duration) for i, inf in tl.clip_infos.items()}
    _apply_trims(tl, vs)

    if vs.logo and not os.path.isfile(vs.logo):
        tl.warnings.append(f"Không tìm thấy file logo “{Path(vs.logo).name}” — video sẽ xuất KHÔNG có logo. "
                           "Chọn lại logo ở thẻ Màu & Logo.")

    # ----- tiếng gốc -----
    clips_audible = vs.source_audio in ("only", "mix")
    tl.audible = {k: inf.has_audio and (clips_audible if k >= 0 else vs.bookend_audio)
                  for k, inf in tl.clip_infos.items()}
    tl.use_source = any(tl.audible.values())

    # kiểu "Chỉ video": bỏ playlist nhạc (tiếng nền, tiếng gốc vẫn dùng được)
    _probe_audio(tl, ms, want_music=vs.source_audio != "only" and project.output_kind != "video_only")

    # ----- độ dài -----
    target = None
    if vs.length_mode == "target":
        target = vs.target_duration
        if target <= 0:
            tl.errors.append("Thời lượng mục tiêu phải lớn hơn 0.")
            return tl
    elif vs.length_mode == "music" and project.output_kind != "video_only":
        # (kiểu Chỉ video không có nhạc: độ dài theo số lần phát của clip, như "Thủ công")
        if not tl.use_music:
            tl.errors.append("Chế độ 'Theo nhạc' cần ít nhất một bài nhạc được bật.")
            return tl
        target = planner.first_round_seconds(ms, tl.track_durations)

    if target is not None and target > MAX_DURATION:
        tl.errors.append(f"Thời lượng {_hours(target)} quá dài — tối đa {MAX_DURATION // 3600} giờ.")
        return tl
    vs_plan = _resolve_durations(tl, vs)
    if target is None:  # thủ công: ước độ dài trước khi tính (số lần phát quá lớn làm app treo)
        est = 0
        for i, c in enumerate(vs_plan.clips):
            if c.enabled and i in tl.frames:
                est += (c.max if c.plays_mode == "random" else c.count) * tl.frames[i]
        est_s = est / float(tl.fps) if tl.fps else 0
        if est_s > MAX_DURATION:
            tl.errors.append(f"Video sẽ dài khoảng {_hours(est_s)} — quá dài (tối đa {MAX_DURATION // 3600} giờ). "
                             "Giảm số lần phát của clip.")
            return tl
    tl.video = planner.plan_video(vs_plan, tl.frames, tl.fps, target)
    if tl.video.error:
        tl.errors.append(tl.video.error)
        return tl
    tl.warnings += tl.video.warnings
    if tl.use_music and not tl.errors:
        tl.music_items = planner.plan_music(ms, tl.track_durations, tl.total)
    return tl


def _hours(sec: float) -> str:
    return f"{sec / 3600:,.0f} giờ".replace(",", ".") if sec >= 3600 else f"{sec / 60:.0f} phút"


def _probe_audio(tl: Timeline, ms, want_music: bool) -> None:
    """Đọc lớp tiếng nền và các bài nhạc được bật."""
    import threading
    from . import ambient_lib
    on_ui = threading.current_thread() is threading.main_thread()
    a_used, real = [], []
    for i, a in enumerate(ms.ambient):  # tiếng nền dựng sẵn (builtin:…) → file app tự tạo (tạo nếu chưa có)
        if not (a.enabled and a.volume > 0):
            continue
        key = ambient_lib.key_of(a.path)
        if on_ui and key in ambient_lib.SOUNDS and not ambient_lib.ensure_async(key):
            # luồng giao diện: tạo ở nền vài giây, xong tự tính lại (lúc xuất thật thì tạo trực tiếp)
            tl.warnings.append(f"Đang tạo tiếng nền “{ambient_lib.display_name(a.path)}” (vài giây)…")
            continue
        try:
            real.append(ambient_lib.resolve(a.path))
        except Exception as e:  # noqa: BLE001
            real.append(a.path)
            tl.warnings.append(f"Không tạo được tiếng nền dựng sẵn {a.path}: {e}")
        a_used.append(i)
    for i, info in zip(a_used, probe_many(real)):
        if info.ok and info.has_audio:
            tl.ambient_infos[i] = info
        else:
            tl.warnings.append(f"Bỏ qua lớp tiếng nền lỗi: {ms.ambient[i].path} ({info.error or 'không có tiếng'})")
    t_used = [i for i, t in enumerate(ms.tracks) if t.enabled and t.plays > 0]
    if want_music and t_used:
        for i, info in zip(t_used, probe_many([ms.tracks[i].path for i in t_used])):
            if info.ok and info.has_audio:
                tl.track_infos[i] = info
                tl.track_durations[i] = info.duration
            else:
                tl.warnings.append(f"Bỏ qua bài lỗi: {ms.tracks[i].path} ({info.error or 'không có tiếng'})")
        tl.use_music = bool(tl.track_durations)
        err = planner.validate_music(ms, tl.track_durations)
        if err:
            tl.errors.append(err)


def build_audio(project: Project, version: int = 0) -> Timeline:
    """Timeline cho chế độ xuất riêng nhạc: playlist lặp tới đủ thời lượng (hoặc số lượt).
    `version`: xem bản thứ mấy khi xuất nhiều bản (mỗi bản một thứ tự)."""
    tl = Timeline()
    ms = project.music
    _probe_audio(tl, ms, want_music=True)
    if not tl.use_music and not tl.ambient_infos:
        tl.errors.append("Chưa có bài nhạc hoặc lớp tiếng nền nào được bật.")
        return tl
    if not tl.use_music:  # chỉ tiếng nền (âm thanh môi trường / ASMR): độ dài luôn theo thời lượng
        tl.audio_total = ms.export_target
        if tl.audio_total <= 0:
            tl.errors.append("Thời lượng phải lớn hơn 0.")
        elif tl.audio_total > MAX_DURATION:
            tl.errors.append(f"File sẽ dài {_hours(tl.audio_total)} — quá dài (tối đa {MAX_DURATION // 3600} giờ).")
        return tl
    if ms.export_mode == "rounds":
        tl.audio_total = planner.rounds_seconds(ms, tl.track_durations, max(1, ms.export_rounds))
    else:
        tl.audio_total = ms.export_target
    if tl.audio_total <= 0:
        tl.errors.append("Thời lượng nhạc phải lớn hơn 0.")
        return tl
    if tl.audio_total > MAX_DURATION:
        tl.errors.append(f"File nhạc sẽ dài {_hours(tl.audio_total)} — quá dài (tối đa {MAX_DURATION // 3600} giờ).")
        return tl
    if not tl.errors:
        if ms.versions > 1:
            tl.version_seeds, dup = planner.version_seeds(ms, tl.track_durations, tl.audio_total, ms.versions)
            if dup:
                tl.warnings.append(f"Playlist quá ít bài để {ms.versions} bản có thứ tự khác hẳn nhau — "
                                   "một số bản sẽ giống nhau.")
            ms = planner.music_variant(ms, tl.version_seeds[min(version, ms.versions - 1)])
        tl.music_items = planner.plan_music(ms, tl.track_durations, tl.audio_total)
    return tl


MIN_KEEP = 0.5  # giây tối thiểu còn lại sau khi cắt


def _apply_trims(tl: Timeline, vs) -> None:
    """Chỉ lấy đoạn giữa của clip: bỏ `trim_start` giây đầu và `trim_end` giây cuối."""
    for i, inf in tl.clip_infos.items():
        if i < 0 or inf.is_image:
            continue
        c = vs.clips[i]
        if c.trim_start <= 0 and c.trim_end <= 0:
            continue
        n = tl.frames[i]
        keep_min = max(2, round(MIN_KEEP * tl.fps))
        start = max(0, round(c.trim_start * tl.fps))
        end_cut = max(0, round(c.trim_end * tl.fps))
        if n - start - end_cut < keep_min:
            # cắt quá tay: giữ lại ít nhất MIN_KEEP giây, ưu tiên giữ điểm bắt đầu đã chọn
            start = min(start, max(0, n - keep_min))
            end_cut = max(0, n - start - keep_min)
            tl.warnings.append(f"Cắt đoạn clip {Path(c.path).stem} dài hơn clip — đã tự giữ lại "
                               f"{float(Fraction(n - start - end_cut) / tl.fps):.1f}s.")
        tl.offsets[i] = start
        tl.frames[i] = n - start - end_cut


def loops_for(seconds: float, clip_frames: int, loop_xfade: float, fps: Fraction) -> int:
    """Số lần phát tối thiểu để clip (đã cắt) loop đủ `seconds` giây, có trừ phần chồng crossfade."""
    target = round(seconds * fps)
    if target <= 0:
        return 0
    if target <= clip_frames:
        return 1
    x = min(max(0, round(loop_xfade * fps)), int(planner.MAX_XF_RATIO * clip_frames))
    step = max(1, clip_frames - x)
    return 1 + math.ceil((target - clip_frames) / step)


def _resolve_durations(tl: Timeline, vs):
    """Clip đặt số lần phát theo thời lượng (ví dụ "10p") → đổi thành số lần cố định cho planner."""
    if not any(c.plays_mode == "duration" for c in vs.clips):
        return vs
    clips = list(vs.clips)
    for i, c in enumerate(clips):
        if c.plays_mode == "duration" and i in tl.frames:
            clips[i] = replace(c, plays_mode="fixed", count=loops_for(c.play_seconds, tl.frames[i], c.loop_xfade,
                                                                       tl.fps))
    return replace(vs, clips=clips)
