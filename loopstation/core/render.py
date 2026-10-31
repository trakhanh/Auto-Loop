"""Điều phối một lần render: khối video → âm thanh → ghép → tracklist."""
from __future__ import annotations

import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import audio_build, encoders, look as look_mod, markers, planner, timeline, tracklist, video_build
from . import ffmpeg_tools as ft
from .project import Project

# tỉ trọng tiến trình của từng bước
W_VIDEO, W_SRC, W_LOUD, W_MUX = 0.30, 0.05, 0.10, 0.55
FASTSTART_MAX = 3 * 3600


class RenderError(RuntimeError):
    pass


# dấu hiệu lỗi do card đồ hoạ / driver (đáng thử lại bằng CPU); lỗi khác (clip hỏng, ổ đầy…) thì báo luôn
_HW_ERRORS = ("nvenc", "_qsv", "qsv", "_amf", "amf ", "amf:", "mfx", "cuda", "openencodesession", "could not open encoder",
              "error while opening encoder", "no capable devices", "capable device", "hwaccel", "hw_frames",
              "generic error in an external library", "error initializing output stream", "incorrect parameters",
              "d3d11", "dxva", "driver", "device creation", "unsupported device", "invalid argument")


def _is_encoder_failure(e: ft.FFmpegError) -> bool:
    text = (e.stderr or str(e)).lower()
    if "no space left" in text or "disk full" in text:
        return False
    return any(k in text for k in _HW_ERRORS)


def _disk_full(e: BaseException) -> bool:
    text = (getattr(e, "stderr", "") or str(e)).lower()
    return "no space left" in text or "disk full" in text or "errno 28" in text or "winerror 112" in text


def _finalize(partial: Path, output: Path, log) -> Path:
    """Đổi tên file đang xuất thành file chính. File đích đang mở (VLC, Films & TV) hoặc bị phần mềm diệt virus /
    đồng bộ giữ: thử lại vài lần, vẫn không được thì lưu sang tên khác — KHÔNG bao giờ xoá file đã xuất xong."""
    for k in range(5):  # ~5 giây
        try:
            os.replace(partial, output)
            return output
        except OSError:
            time.sleep(0.5 + k * 0.25)
    for n in range(1, 100):
        alt = output.with_name(f"{output.stem}_moi{'' if n == 1 else n}{output.suffix}")
        if alt.exists():
            continue
        try:
            os.replace(partial, alt)
            log(f"Cảnh báo: không ghi đè được {output.name} (file đang mở ở chương trình khác?) — "
                f"đã lưu thành {alt.name}.")
            return alt
        except OSError:
            break
    log(f"Cảnh báo: không đổi tên được file — video đầy đủ đang nằm ở {partial}")
    return partial


class RenderJob:
    def __init__(
        self,
        project: Project,
        available: dict[str, list[str]],
        output_path: str,
        on_progress: Callable[[float, str], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        audio_only: bool = False,
    ):
        self.audio_only = audio_only
        self.project = project
        self.available = available
        self.output = Path(output_path)
        self.runner = ft.Runner()
        self._on_progress = on_progress or (lambda f, s: None)
        self._on_log = on_log or (lambda s: None)
        self._log_lines: list[str] = []

    # ---------- tiện ích ----------
    def cancel(self) -> None:
        self.runner.cancel()

    def log(self, msg: str) -> None:
        line = f"[{datetime.now():%H:%M:%S}] {msg}"
        self._log_lines.append(line)
        self._on_log(line)

    def progress(self, frac: float, status: str) -> None:
        self._on_progress(max(0.0, min(1.0, frac)), status)

    def _write_log_file(self) -> Path:
        d = ft.data_dir() / "logs"
        d.mkdir(exist_ok=True)
        p = d / f"render_{datetime.now():%Y%m%d_%H%M%S}.log"
        p.write_text("\n".join(self._log_lines), encoding="utf-8")
        return p

    # ---------- chạy ----------
    def run(self) -> Path:
        t0 = time.time()
        try:
            out = self._run_audio() if self.audio_only else self._run()
            self.log(f"Hoàn tất sau {_fmt_dur(time.time() - t0)}: {out}")
            return out
        except ft.CancelledError:
            self.log("Đã huỷ.")
            raise
        except Exception as e:  # noqa: BLE001
            self.log(f"LỖI: {e}")
            if _disk_full(e):
                raise RenderError("Ổ đĩa đã đầy trong lúc xuất. Giải phóng chỗ trống (hoặc bấm Xoá bộ nhớ đệm ở trang "
                                  "Cài đặt) rồi xuất lại.\n\nChi tiết: " + str(e)[-600:]) from e
            raise
        finally:
            try:
                self.log(f"Log: {self._write_log_file()}")
            except OSError:
                pass

    def _run(self) -> Path:
        proj = self.project
        vs, ms, ex = proj.video, proj.music, proj.export
        preset = encoders.PRESETS[ex.preset]

        self.progress(0, "Đang phân tích clip và nhạc…")
        tl = timeline.build(proj)
        for w in tl.warnings:
            self.log(f"Cảnh báo: {w}")
        if not tl.ok:
            raise RenderError("\n".join(tl.errors))
        plan = tl.video
        total = tl.total
        self.log(f"Xuất {tl.width}x{tl.height} @ {float(tl.fps):g} fps, dài {_fmt_dur(total)} "
                 f"({plan.rounds} lượt).")

        out_dir = self.output.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        est = tl.estimate_bytes()
        free = shutil.disk_usage(out_dir).free
        if free < est:
            self.log(f"Cảnh báo: ổ đĩa có thể không đủ chỗ (ước tính {_fmt_size(est)}, "
                     f"còn trống {_fmt_size(free)}). Sẽ kiểm tra lại chính xác sau khi chuẩn hoá clip.")

        # ----- 1. khối video -----
        segs = planner.segments(plan, tl.frames)
        paths = {k: inf.path for k, inf in tl.clip_infos.items()}
        self._check_cache_space(segs, est)
        encoder = encoders.pick(preset.codec, ex.encoder, self.available)
        self.strict_cap = ex.bitrate_cap in ("mbps", "size")

        def cap_for(enc: str) -> int:
            return encoders.maxrate_kbps(ex.bitrate_cap, ex.cap_gb if ex.bitrate_cap == "size" else ex.cap_mbps,
                                         tl.width, tl.height, float(tl.fps), total, 320 if ex.audio == "max" else 192,
                                         encoders.cap_blocks(enc, len(segs)))

        self.maxrate = cap_for(encoder)
        if self.maxrate:
            self.log(f"Giới hạn bitrate hình: tối đa {self.maxrate / 1000:.1f} Mbps "
                     f"({encoders.BITRATE_CAPS.get(ex.bitrate_cap, ex.bitrate_cap)}).")
        blocks = None
        while blocks is None:
            try:
                blocks = self._encode_blocks(segs, paths, tl, encoder)
            except ft.FFmpegError as e:
                if not encoders.is_hardware(encoder) or not _is_encoder_failure(e):
                    raise  # lỗi không do card đồ hoạ (clip hỏng, ổ đầy…): mã hoá lại bằng CPU cũng hỏng y như vậy
                jobs = gpu_jobs(encoder)
                if jobs > 1:
                    # card / driver cũ chỉ cho 2–3 phiên mã hoá cùng lúc: bớt số khối song song, vẫn dùng card
                    # (khối đã xong nằm trong bộ nhớ đệm, không làm lại). Nhớ mức này cho các lần xuất sau.
                    _GPU_JOBS[encoder] = jobs - 1
                    self.log(f"Card đồ hoạ từ chối {jobs} phiên cùng lúc — thử lại với {jobs - 1} phiên.")
                    continue
                self.log(f"Encoder {encoder} lỗi, chuyển sang CPU. Chi tiết:\n{e}")
                encoder = encoders.ENCODERS[preset.codec]["cpu"]
                self.maxrate = cap_for(encoder)

        # ----- 2. tiếng gốc -----
        src_blocks = {}
        if tl.use_source:
            sgains = {}
            if vs.source_level:
                self.progress(W_VIDEO, "Đang đo độ to tiếng gốc…")
                sgains = audio_build.source_gains(self.runner, paths, tl.audible, self.project.music.lufs, self.log)
            uniq = list(dict.fromkeys(segs))
            src_blocks = dict(zip(uniq, _parallel(
                uniq, lambda seg: video_build.source_audio_segment(
                    self.runner, seg, paths, tl.audible, tl.fps, vs.fade_out, tl.offsets, sgains), 4,
                lambda k: self.progress(W_VIDEO + W_SRC * k / len(uniq), "Đang tách tiếng gốc…"))))

        # ----- 3. đo âm lượng nhạc -----
        used_tracks = sorted({it.track for it in tl.music_items})
        gains = self._measure_gains(tl, used_tracks, W_VIDEO + W_SRC, W_LOUD)

        # ----- 4. danh sách ghép + filtergraph -----
        job_dir = ft.cache_dir("jobs") / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        job_dir.mkdir(parents=True)
        vlist = job_dir / "video.ffconcat"
        v_items = [(blocks[seg], video_build.seconds(seg.frames, tl.fps)) for seg in segs]
        video_build.write_concat(vlist, v_items)

        exact = sum(os.path.getsize(p) for p, _ in v_items) + 320_000 / 8 * total
        free = shutil.disk_usage(out_dir).free
        if free < exact * 1.05:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise RenderError(f"Ổ đĩa không đủ chỗ: cần {_fmt_size(exact * 1.05)}, "
                              f"còn trống {_fmt_size(free)}.")
        self.log(f"Dung lượng dự kiến: {_fmt_size(exact)}")

        args = ["-v", "error", "-f", "concat", "-safe", "0", "-i", str(vlist)]
        graph: list[str] = []
        source_label = None
        if tl.use_source:
            alist = job_dir / "source_audio.ffconcat"
            a_items = [(src_blocks[seg], video_build.seconds(seg.frames, tl.fps)) for seg in segs]
            video_build.write_concat(alist, a_items)
            args += ["-f", "concat", "-safe", "0", "-i", str(alist)]
            source_label = "1:a"
        music_label = None
        if tl.use_music and tl.music_items:
            t_paths = {t: tl.track_infos[t].path for t in used_tracks}
            self.progress(W_VIDEO + W_SRC + W_LOUD, "Đang kiểm tra file nhạc…")
            t_paths = audio_build.usable_paths(self.runner, t_paths, self.log)  # bài có đoạn hỏng → bản sạch
            graph += audio_build.music_graph(tl.music_items, t_paths, gains, ms, total)
            music_label = "music"
        ambient_labels = []
        if tl.ambient_infos:
            keys = sorted(tl.ambient_infos)
            lines, ambient_labels = audio_build.ambient_graph(
                self._ambient_paths(tl, keys), [ms.ambient[k].volume for k in keys], total,
                ms.fade_in, ms.fade_out)
            graph += lines
            self.log(f"Lớp tiếng nền: {len(keys)}")
        if music_label or source_label or ambient_labels:
            graph += audio_build.master_graph(music_label, source_label, vs.music_volume,
                                              vs.source_volume, total, ambient_labels)
            gpath = job_dir / "graph.txt"
            gpath.write_text("\n".join(graph), encoding="utf-8")
            args += ["-/filter_complex", str(gpath), "-map", "0:v", "-map", "[aout]",
                     *encoders.audio_args(ex.audio, self.available), "-ar", "48000", "-ac", "2"]
        else:
            args += ["-map", "0:v", "-an"]
        args += ["-c:v", "copy"]
        if preset.codec == "hevc":
            args += ["-tag:v", "hvc1"]
        partial = self.output.with_name(self.output.stem + ".dang-xuat.mp4")
        args += ["-t", f"{total:.6f}"]
        if total <= FASTSTART_MAX:
            # chỉ mục (moov) ở đầu file để xem được ngay trên web. Giữ sẵn chỗ cho nó thay vì +faststart:
            # +faststart ghi lại CẢ file lần nữa (file 4 GB mất thêm 25–50 giây); giữ chỗ thì ghi một lần là xong.
            args += ["-moov_size", str(moov_reserve(total, tl.fps))]
        args += ["-metadata", f"title={proj.name}", "-f", "mp4", str(partial)]

        # ----- 5. ghép -----
        base = W_VIDEO + W_SRC + W_LOUD
        start = time.time()

        def on_mux(block: dict[str, str]) -> None:
            try:
                t = int(block.get("out_time_us", "0")) / 1e6
            except ValueError:
                return
            frac = min(1.0, t / total) if total else 1.0
            if frac >= 0.999:
                self.progress(base + W_MUX * 0.999, "Đang hoàn tất file…")
                return
            elapsed = time.time() - start
            eta = elapsed / frac * (1 - frac) if frac > 0.01 else 0
            self.progress(base + W_MUX * frac,
                          f"Đang ghép video + âm thanh… {_fmt_dur(t)}/{_fmt_dur(total)}"
                          + (f" — còn ~{_fmt_dur(eta)}" if eta else ""))

        self.log("Đang ghép…")
        try:
            self.runner.ffmpeg(args, on_progress=on_mux)
        except BaseException:
            partial.unlink(missing_ok=True)
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        self.output = _finalize(partial, self.output, self.log)
        shutil.rmtree(job_dir, ignore_errors=True)

        # ----- 6. file kèm (lỗi ở đây chỉ cảnh báo: video đã xuất xong) -----
        if ex.tracklist and tl.music_items:
            def write_tracklist() -> None:
                t_paths = {t: tl.track_infos[t].path for t in used_tracks}
                text, warns = tracklist.build(tl.music_items, t_paths, total)
                tpath = self.output.with_name(self.output.stem + "_tracklist.txt")
                tpath.write_text(text, encoding="utf-8")
                self.log(f"Tracklist: {tpath}")
                for w in warns:
                    self.log(f"Cảnh báo tracklist: {w}")
            self._side_file("tracklist", write_tracklist)
        if ex.markers:
            def write_markers() -> None:
                names = [Path(c.path).name for c in vs.clips]
                marks = markers.build(tl, names, vs.intro, vs.outro)
                files = markers.write_all(marks, tl.fps, self.output, (tl.width, tl.height), total)
                n_norm = sum(1 for m in marks if m.kind == "THƯỜNG")
                self.log(f"Mốc thời gian cho editor: {len(marks)} đoạn ({n_norm} đoạn thường) → {files[0].name} "
                         "(+.csv .srt .edl)")
            self._side_file("mốc thời gian", write_markers)
        if ex.save_project_copy:
            self._side_file("bản sao dự án",
                            lambda: proj.save(str(self.output.with_name(self.output.stem + "_project.lsproj"))))
        self.progress(1.0, "Xong!")
        return self.output

    def _ambient_paths(self, tl: timeline.Timeline, keys: list[int]) -> list[str]:
        """Bản lặp liền mạch (hoà đuôi vào đầu) của từng lớp tiếng nền."""
        out = []
        for k in keys:
            info = tl.ambient_infos[k]
            p = audio_build.seamless_loop(self.runner, info.path, info.duration)
            if p != info.path:
                self.log(f"  Tiếng nền {Path(info.path).name}: tạo bản lặp liền mạch")
            out.append(p)
        return out

    def _measure_gains(self, tl: timeline.Timeline, used_tracks: list[int], p0: float, w: float) -> dict:
        if not tl.use_music:
            return {}
        return audio_build.track_gains(
            self.runner, self.project.music, {t: tl.track_infos[t].path for t in used_tracks}, self.log,
            lambda k, n: self.progress(p0 + w * k / max(1, n), f"Đang đo âm lượng nhạc ({k + 1}/{n})…"))

    def _run_audio(self) -> Path:
        """Chế độ xuất riêng nhạc: playlist lặp tới đủ thời lượng, kèm tiếng nền + tracklist."""
        proj = self.project
        ms, ex = proj.music, proj.export
        fmt = encoders.AUDIO_FORMATS[ms.export_format]
        self.progress(0, "Đang phân tích nhạc…")
        tl = timeline.build_audio(proj)
        for w in tl.warnings:
            self.log(f"Cảnh báo: {w}")
        if not tl.ok:
            raise RenderError("\n".join(tl.errors))
        total = tl.total
        self.log(f"Xuất riêng nhạc {fmt.label}, dài {_fmt_dur(total)}, {len(tl.music_items)} lượt bài.")
        self.output.parent.mkdir(parents=True, exist_ok=True)

        used_tracks = sorted({it.track for it in tl.music_items})
        gains = self._measure_gains(tl, used_tracks, 0.0, 0.2)
        t_paths = {t: tl.track_infos[t].path for t in used_tracks}
        t_paths = audio_build.usable_paths(self.runner, t_paths, self.log)  # bài có đoạn hỏng → bản sạch
        # chỉ có tiếng nền (không bài nhạc nào): xuất âm thanh môi trường / ASMR
        graph = audio_build.music_graph(tl.music_items, t_paths, gains, ms, total) if tl.music_items else []
        ambient_labels = []
        if tl.ambient_infos:
            keys = sorted(tl.ambient_infos)
            lines, ambient_labels = audio_build.ambient_graph(
                self._ambient_paths(tl, keys), [ms.ambient[k].volume for k in keys], total,
                ms.fade_in, ms.fade_out)
            graph += lines
            self.log(f"Lớp tiếng nền: {len(keys)}")
        # âm lượng nhạc của Bảng trộn âm (dùng chung mọi chế độ)
        graph += audio_build.master_graph("music" if tl.music_items else None, None, proj.video.music_volume, 0, total,
                                          ambient_labels)
        job_dir = ft.cache_dir("jobs") / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        job_dir.mkdir(parents=True)
        gpath = job_dir / "graph.txt"
        gpath.write_text("\n".join(graph), encoding="utf-8")
        partial = self.output.with_name(self.output.stem + ".dang-xuat" + self.output.suffix)
        args = ["-v", "error", "-/filter_complex", str(gpath), "-map", "[aout]",
                *fmt.args(self.available), "-ar", "48000", "-ac", "2", "-t", f"{total:.6f}",
                "-metadata", f"title={proj.name}", str(partial)]
        start = time.time()

        def on_prog(block: dict[str, str]) -> None:
            try:
                t = int(block.get("out_time_us", "0")) / 1e6
            except ValueError:
                return
            frac = min(1.0, t / total) if total else 1.0
            eta = (time.time() - start) / frac * (1 - frac) if frac > 0.01 else 0
            self.progress(0.2 + 0.8 * frac, f"Đang dựng nhạc… {_fmt_dur(t)}/{_fmt_dur(total)}"
                          + (f" — còn ~{_fmt_dur(eta)}" if eta else ""))

        self.log("Đang dựng nhạc…")
        try:
            self.runner.ffmpeg(args, on_progress=on_prog)
        except BaseException:
            partial.unlink(missing_ok=True)
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        self.output = _finalize(partial, self.output, self.log)
        shutil.rmtree(job_dir, ignore_errors=True)
        if ex.tracklist and tl.music_items:
            def write_tracklist() -> None:
                text, _warns = tracklist.build(tl.music_items, t_paths, total)
                tpath = self.output.with_name(self.output.stem + "_tracklist.txt")
                tpath.write_text(text, encoding="utf-8")
                self.log(f"Tracklist: {tpath}")
            self._side_file("tracklist", write_tracklist)
        self.progress(1.0, "Xong!")
        return self.output

    def _side_file(self, what: str, fn) -> None:
        try:
            fn()
        except OSError as e:
            self.log(f"Cảnh báo: không ghi được file kèm ({what}): {e}. Video vẫn đã xuất xong.")

    def _check_cache_space(self, segs, est: float) -> None:
        """Khối video lưu ở bộ nhớ đệm (ổ của %LOCALAPPDATA%, thường là C:). Thiếu chỗ thì tự xoá khối cũ nhất."""
        uniq = sum(s.frames for s in set(segs))
        allf = sum(s.frames for s in segs) or 1
        need = int(est * uniq / allf * 1.2) + 1024 ** 3
        try:
            free = shutil.disk_usage(ft.cache_dir("blocks")).free
        except OSError:
            return
        if free >= need:
            return
        freed = ft.prune_cache(need_free=need)
        if freed:
            self.log(f"Ổ chứa bộ nhớ đệm sắp đầy — đã tự xoá {_fmt_size(freed)} khối cũ.")
        free = shutil.disk_usage(ft.cache_dir("blocks")).free
        if free < need:
            self.log(f"Cảnh báo: ổ chứa bộ nhớ đệm ({ft.cache_dir('blocks').anchor}) chỉ còn {_fmt_size(free)}, "
                     f"lượt xuất này có thể cần khoảng {_fmt_size(need)}.")

    def _encode_blocks(self, segs, paths, tl: timeline.Timeline, encoder: str) -> dict:
        vs, ex = self.project.video, self.project.export
        uniq = list(dict.fromkeys(segs))
        n_x = sum(1 for s in uniq if s.kind == "xfade")
        look = look_mod.from_settings(vs)
        if look is not None:
            parts = ([f"màu {look_mod.COLOR_PRESETS[look.color][0]} {look.strength}%"] if look.has_color else []) \
                + ([f"logo {Path(look.logo).name} ({look.logo_opacity}%)"] if look.has_logo else [])
            self.log("Màu & Logo: " + ", ".join(parts))
        self.log(f"Encoder: {encoder} — {len(uniq)} khối video khác nhau ({n_x} đoạn crossfade), "
                 f"ghép thành {len(segs)} khối.")
        jobs = gpu_jobs(encoder)
        if jobs > 1 and len(uniq) > 1:
            self.log(f"Chuẩn hoá {jobs} khối cùng lúc")

        def one(seg):
            return video_build.encode_segment(
                self.runner, seg, paths, tl.fps, tl.width, tl.height, vs.fit, encoder, ex.quality,
                vs.fade_out, tl.offsets, getattr(self, "maxrate", 0), look, vs.look_bookends,
                getattr(self, "strict_cap", False))

        def step(done: int) -> None:
            self.progress(W_VIDEO * done / len(uniq), f"Đang chuẩn hoá {done + 1}/{len(uniq)} khối bằng {encoder}"
                          + (f" ({jobs} khối cùng lúc)…" if jobs > 1 else "…"))

        blocks = dict(zip(uniq, _parallel(uniq, one, jobs, step)))
        self.progress(W_VIDEO, "Đã chuẩn hoá xong video.")
        return blocks


_GPU_JOBS: dict[str, int] = {}  # encoder → số phiên song song đã giảm (card từ chối nhiều phiên), nhớ tới khi tắt app


def gpu_jobs(encoder: str) -> int:
    """Số khối chuẩn hoá cùng lúc cho encoder này: mức mặc định, hoặc mức đã giảm sau khi card từ chối."""
    return min(encoders.parallel_jobs(encoder), _GPU_JOBS.get(encoder, 99))


def moov_reserve(total: float, fps) -> int:
    """Byte giữ sẵn ở đầu file cho chỉ mục: mỗi khung hình / khung âm thanh tốn ≤ ~24 byte (kích thước, vị trí, thời
    điểm…) → giữ 40 byte mỗi khung + 512 KB cho chắc (thiếu chỗ là ffmpeg báo lỗi). Thừa vài MB không đáng kể."""
    frames = total * float(fps) + total * 48000 / 1024
    return int(frames * 40) + 512 * 1024


def _parallel(items: list, fn, jobs: int, on_step=None) -> list:
    """Chạy fn(item) cho từng item, tối đa `jobs` việc cùng lúc, trả kết quả đúng thứ tự. Lỗi ở một việc: huỷ các
    việc chưa chạy, đợi việc đang chạy xong rồi báo lỗi đó (để xuất lại bằng CPU nếu card đồ hoạ lỗi)."""
    if jobs <= 1 or len(items) <= 1:
        out = []
        for k, it in enumerate(items):
            if on_step:
                on_step(k)
            out.append(fn(it))
        return out
    from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
    results: list = [None] * len(items)
    done = 0
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = {pool.submit(fn, it): k for k, it in enumerate(items)}
        pending = set(futs)
        if on_step:
            on_step(0)
        while pending:
            finished, pending = wait(pending, return_when=FIRST_EXCEPTION)
            for f in finished:
                if f.exception() is not None:
                    for p in pending:
                        p.cancel()
                    wait(pending)
                    raise f.exception()
                results[futs[f]] = f.result()
                done += 1
            if on_step and done < len(items):
                on_step(done)
    return results


def _fmt_dur(sec: float) -> str:
    s = int(sec)
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def _fmt_size(b: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def output_path(out_dir: str, name: str, own_folder: bool, taken: set[str] | None = None) -> str:
    """Đường dẫn file xuất. own_folder: <thư mục>/<tên>/<tên>.mp4 — mỗi video một thư mục riêng chứa cả file kèm.
    taken (hàng đợi): tự thêm hậu tố _2, _3… khi trùng trên đĩa hoặc trong hàng đợi, không hỏi."""
    p = Path(name)
    stem, ext = p.stem, p.suffix

    def make(s: str) -> Path:
        return Path(out_dir) / s / f"{s}{ext}" if own_folder else Path(out_dir) / f"{s}{ext}"

    if taken is None:
        return str(make(stem))
    cand, n = make(stem), 2
    while str(cand).lower() in taken or cand.exists():
        cand = make(f"{stem}_{n}")
        n += 1
    return str(cand)


def version_outputs(out_dir: str, name: str, ext: str, own_folder: bool, n: int,
                    taken: set[str] | None = None) -> list[str]:
    """Đường dẫn cho n bản nhạc: <tên>_ban-1.mp3 … <tên>_ban-n.mp3, chung một thư mục riêng nếu own_folder.
    Tự thêm hậu tố _2, _3… vào tên (cả thư mục) nếu đã có trên đĩa hoặc trong hàng đợi."""
    taken = taken or set()
    stem, k = strip_ext(name, ext), 1
    while True:
        s = stem if k == 1 else f"{stem}_{k}"
        base = Path(out_dir) / s if own_folder else Path(out_dir)
        outs = [base / f"{s}_ban-{i + 1}{ext}" for i in range(n)]
        if not (own_folder and base.exists()) and not any(o.exists() or str(o).lower() in taken for o in outs):
            return [str(o) for o in outs]
        k += 1


MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg",
              ".opus"}
_BAD_CHARS = set('<>:"/\\|?*')


def strip_ext(name: str, ext: str = "") -> str:
    """Bỏ đuôi file chỉ khi đó thật là đuôi media (“Lofi Vol.1” giữ nguyên, “Lofi.mp3” → “Lofi”)."""
    root, e = os.path.splitext(name)
    return root if e and (e.lower() == ext.lower() or e.lower() in MEDIA_EXTS) else name


def clean_filename(name: str) -> str:
    """Tên file người dùng gõ: bỏ ký tự Windows không cho phép (: ? * " < > | / \\), khoảng trắng / dấu chấm thừa."""
    s = "".join("_" if ch in _BAD_CHARS or ord(ch) < 32 else ch for ch in name).strip().rstrip(". ")
    return s


def default_output_name(project: Project) -> str:
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in project.name).strip() or "video"
    return f"{safe}_{datetime.now():%Y%m%d_%H%M}.mp4"
