"""Đo âm lượng, dựng filtergraph cho nhạc (crossfade, lặp, fade) và trộn âm gốc."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from pathlib import Path

from . import ffmpeg_tools as ft
from .planner import MusicItem
from .project import MusicSettings, atomic_write

_lock = threading.RLock()
_db_mem: dict[str, tuple[tuple[int, int, int], dict]] = {}


def _peek_json_cached(p: Path) -> dict:
    """Đọc JSON có bộ nhớ đệm RAM theo (mtime_ns, ctime_ns, size) — tự đọc lại khi file trên đĩa đổi hoặc xoá."""
    key = os.path.normcase(str(p))
    try:
        st = p.stat()
    except OSError:
        with _lock:
            _db_mem.pop(key, None)
        return {}
    sig = (st.st_mtime_ns, st.st_ctime_ns, st.st_size)
    with _lock:
        hit = _db_mem.get(key)
        if hit is not None and hit[0] == sig:
            return hit[1]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    with _lock:
        _db_mem[key] = (sig, data)
        return data


def _write_json_cached(p: Path, db: dict) -> None:
    """Ghi JSON nguyên tử và cập nhật ngay bộ nhớ đệm RAM (gọi khi đang giữ `_lock`)."""
    snap = dict(db)
    atomic_write(p, json.dumps(snap, ensure_ascii=False))
    key = os.path.normcase(str(p))
    try:
        st = p.stat()
        _db_mem[key] = ((st.st_mtime_ns, st.st_ctime_ns, st.st_size), snap)
    except OSError:
        _db_mem.pop(key, None)


def _loudness_db() -> dict:
    return dict(_peek_json_cached(ft.data_dir() / "loudness.json"))


def _file_id(path: str) -> str:
    st = os.stat(path)
    return f"{os.path.normcase(os.path.abspath(path))}:{st.st_size}:{st.st_mtime_ns}"


def cached_loudness(path: str) -> float | None:
    db = _peek_json_cached(ft.data_dir() / "loudness.json")
    if not db:
        return None
    try:
        return db.get(_file_id(path))
    except OSError:
        return None


def cached_loudnesses(paths) -> dict[str, float | None]:
    """Đọc LUFS đã lưu cho nhiều file cùng lúc (chỉ kiểm tra `loudness.json` đúng 1 lần)."""
    if not paths:
        return {}
    db = _peek_json_cached(ft.data_dir() / "loudness.json")
    if not db:
        return {p: None for p in paths}
    out: dict[str, float | None] = {}
    for p in paths:
        if p in out:
            continue
        try:
            out[p] = db.get(_file_id(p))
        except OSError:
            out[p] = None
    return out


# ----- file nhạc có đoạn hỏng -----
# Nhạc được đọc bằng bộ lọc amovie: gặp một gói dữ liệu hỏng (vd "[aac] Pulse data corrupt or invalid") là CẢ lượt xuất
# dừng (ffmpeg lỗi mã 3199971767), trong khi đọc kiểu "-i" thì ffmpeg chỉ bỏ qua đoạn hỏng. → Kiểm tra từng bài một lần
# (nhớ theo file), bài hỏng thì tạo bản sạch (FLAC, đã bỏ đoạn hỏng) trong bộ nhớ đệm rồi ghép bằng bản đó.
_DAMAGE_HINTS = ("invalid data", "corrupt", "error", "exhausted", "concealing", "decode")


def _check_db_path() -> Path:
    # v2: kiểm tra mọi luồng âm thanh (bản 1.8.7 chỉ kiểm tra luồng đầu → sổ cũ có thể ghi "lành" sai, bỏ đi)
    return ft.data_dir() / "audiocheck2.json"


def is_damaged(runner: ft.Runner, path: str) -> bool:
    """Giải mã thử cả bài (nhanh: vài giây cho 1 giờ nhạc); có báo lỗi giải mã → bài có đoạn hỏng. Nhớ kết quả."""
    try:
        fid = _file_id(path)
    except OSError:
        return False
    db = _peek_json_cached(_check_db_path())
    if fid in db:
        return bool(db[fid])
    try:
        # mọi luồng âm thanh: file tải về có thể có 2 luồng, ghép nhạc (amovie) lấy luồng "tốt nhất" chứ không phải
        # luồng đầu — chỉ kiểm tra luồng đầu là bỏ sót đúng luồng sẽ dùng
        err = runner.ffmpeg(["-v", "error", "-i", path, "-vn", "-map", "0:a", "-f", "null", "-"])
    except ft.FFmpegError as e:
        err = e.stderr or str(e)
    bad = any(h in err.lower() for h in _DAMAGE_HINTS)
    _remember(fid, bad)
    return bad


def mark_damaged(path: str) -> None:
    """Bài lọt qua bước kiểm tra nhanh nhưng làm hỏng lượt ghép: nhớ là "hỏng" để các lần sau dùng bản sạch ngay."""
    try:
        _remember(_file_id(path), True)
    except OSError:
        pass


def _remember(fid: str, bad: bool) -> None:
    p = _check_db_path()
    with _lock:
        db = dict(_peek_json_cached(p))
        db[fid] = bad
        try:
            _write_json_cached(p, db)
        except OSError:
            pass


def clean_copy(runner: ft.Runner, path: str) -> str:
    """Bản sạch của bài có đoạn hỏng: giải mã bỏ qua lỗi → FLAC trong bộ nhớ đệm (giữ nguyên chất lượng)."""
    import hashlib
    key = hashlib.sha1(f"v2|{_file_id(path)}".encode("utf-8")).hexdigest()[:20]  # v2: đúng luồng amovie dùng
    out = ft.cache_dir("cleanaudio") / f"{key}.flac"
    if out.is_file() and out.stat().st_size > 0:
        return str(out)
    tmp = out.with_name(f"{key}.{os.getpid()}-{threading.get_ident()}.tmp.flac")
    total = _seconds(Path(path))
    keep = ["-t", f"{total:.3f}"] if total else []  # mốc giờ rác có thể làm phần lấp im lặng dài quá bài gốc
    try:
        try:
            # không -map: ffmpeg tự chọn luồng âm thanh tốt nhất — cùng luồng mà amovie dùng khi ghép.
            # aresample async: chỗ gói hỏng bị bỏ thì lấp bằng im lặng → bài giữ đúng độ dài, nhạc phía sau không bị
            # dồn sớm (trước đây bản sạch có thể ngắn hơn bài gốc cả chục giây)
            runner.ffmpeg(["-v", "error", "-err_detect", "ignore_err", "-i", path, "-vn", "-sn", "-dn",
                           "-af", "aresample=async=1:first_pts=0", *keep, "-c:a", "flac", str(tmp)])
        except ft.FFmpegError:
            tmp.unlink(missing_ok=True)
            _decode_skipping(runner, path, tmp, total)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    try:
        os.replace(tmp, out)
    except OSError:
        # luồng khác vừa tạo xong cùng bản sạch (file đích đang bị đọc → không ghi đè được): dùng bản đó
        tmp.unlink(missing_ok=True)
        if out.is_file() and out.stat().st_size > 0:
            return str(out)
        raise
    return str(out)


CLEAN_FMT = "aresample=48000,aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo"
MAX_PIECES = 400  # bài hỏng ở quá nhiều chỗ thì thôi (báo lỗi), không chạy mãi


def _seconds(path: Path) -> float:
    try:
        out = subprocess.run([ft.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              str(path)], capture_output=True, text=True, timeout=60,
                             creationflags=ft.CREATE_NO_WINDOW).stdout
        return max(0.0, float(out.strip() or 0))
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _decode_skipping(runner: ft.Runner, path: str, out: Path, total: float = 0.0) -> None:
    """Bản sạch cho file hỏng nặng. Gói dữ liệu rác có thể giải ra âm thanh "37 kênh" → ffmpeg dừng cả lệnh
    ("Rematrix is needed…", "Error reinitializing filters"), -err_detect ignore_err cũng không cứu được. Ở đây giải mã
    từng đoạn: dừng ở đâu thì chèn khoảng im lặng (0,25 giây; vẫn hỏng thì 0,5 → 1 → … → 8 giây) rồi đọc tiếp từ sau
    chỗ đó — bài giữ đúng độ dài (`total` giây) nên nhạc không lệch giờ."""
    parts: list[Path] = []
    lst = out.with_name(out.stem + ".txt")
    start, skip = 0.0, 0.25
    try:
        for n in range(MAX_PIECES):
            if total and start >= total - 0.05:  # hỏng tới tận cuối bài: đọc tới đây là xong
                break
            piece = out.with_name(f"{out.stem}.p{n}.flac")
            seek = ["-ss", f"{start:.3f}"] if start > 0 else []
            try:
                runner.ffmpeg(["-v", "error", "-err_detect", "ignore_err", *seek, "-i", path, "-vn", "-sn", "-dn",
                               "-af", CLEAN_FMT, "-c:a", "flac", str(piece)])
                ok = True
            except ft.FFmpegError:
                ok = False  # ffmpeg vẫn đóng file đúng cách: phần đã giải mã trước chỗ hỏng dùng được
            got = _seconds(piece) if piece.is_file() else 0.0
            if got > 0:
                parts.append(piece)
            else:
                piece.unlink(missing_ok=True)
            if ok:
                break
            gap = out.with_name(f"{out.stem}.g{n}.flac")
            runner.ffmpeg(["-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{skip:.3f}",
                           "-af", CLEAN_FMT, "-c:a", "flac", str(gap)])
            parts.append(gap)
            start += got + skip
            skip = 0.25 if got >= 1.0 else min(skip * 2, 8.0)
        else:
            raise ft.FFmpegError(f"{Path(path).name} hỏng ở quá nhiều chỗ — không tạo được bản sạch.")
        lst.write_text("\n".join("file '" + str(p).replace("\\", "/").replace("'", "'\\''") + "'" for p in parts),
                       encoding="utf-8")
        fit = ["-af", "apad", "-t", f"{total:.3f}"] if total else []  # đúng độ dài bài gốc
        runner.ffmpeg(["-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), *fit, "-c:a", "flac", str(out)])
    finally:
        for p in parts:
            p.unlink(missing_ok=True)
        lst.unlink(missing_ok=True)


def fails_in_graph(runner: ft.Runner, path: str) -> bool:
    """Đọc thử cả bài đúng như lúc ghép (bộ lọc amovie, luồng âm thanh "tốt nhất"): gói hỏng làm lượt ghép dừng
    thì ở đây cũng dừng. Chậm hơn kiểm tra nhanh một chút — chỉ dùng khi lượt ghép đã hỏng mà chưa rõ bài nào."""
    src = escape_filter_value(path.replace("\\", "/"))
    try:
        runner.ffmpeg(["-v", "error", "-filter_complex", f"amovie=filename={src}[o]", "-map", "[o]", "-f", "null", "-"])
    except ft.FFmpegError:
        return True
    return False


def usable_paths(runner: ft.Runner, paths: dict[int, str], log=None, force: bool = False) -> dict[int, str]:
    """Đường dẫn để ghép nhạc / tiếng nền: file nào có đoạn hỏng thì thay bằng bản sạch (kiểm tra 4 file cùng lúc).
    `force`: lượt ghép trước vẫn hỏng vì một file lọt kiểm tra → đọc thử từng file đúng như lúc ghép, file nào hỏng
    thì nhớ là hỏng + dùng bản sạch. Không tìm ra file nào → dùng bản sạch cho TẤT CẢ, nhưng chỉ trong lượt này
    (không ghi "hỏng" cho bài lành)."""
    from concurrent.futures import ThreadPoolExecutor
    files = list(dict.fromkeys(paths.values()))
    every = False
    if force:
        with ThreadPoolExecutor(max_workers=4) as pool:
            culprit = dict(zip(files, pool.map(lambda p: fails_in_graph(runner, p), files)))
        for p in files:
            if culprit[p]:
                mark_damaged(p)
        every = not any(culprit.values())
        if every and log and files:
            log("  Không xác định được bài nào bị hỏng — lượt này dùng bản sạch cho mọi bài.")
    with ThreadPoolExecutor(max_workers=4) as pool:
        damaged = dict(zip(files, pool.map(lambda p: every or is_damaged(runner, p), files)))
    fixed: dict[str, str] = {}
    for p in files:
        if damaged[p]:
            fixed[p] = clean_copy(runner, p)
            if log and not every:
                log(f"  {Path(p).name} có đoạn bị hỏng — đã tự tạo bản sạch (bỏ đoạn hỏng) để ghép.")
    return {k: fixed.get(p, p) for k, p in paths.items()}


def is_decode_failure(err: BaseException) -> bool:
    """Lượt ghép hỏng vì đọc file âm thanh trong filtergraph (amovie) gặp gói dữ liệu hỏng
    — "[aac] Pulse data corrupt…", "Error requesting a frame from the filtergraph: Invalid data found…"."""
    s = (getattr(err, "stderr", "") or str(err)).lower()
    if "error reinitializing filters" in s or "rematrix is needed" in s:  # gói rác giải ra "37 kênh" giữa bài
        return True
    return "filtergraph" in s and any(h in s for h in ("invalid data", "corrupt", "decod"))


def volume_db(pct: int) -> float:
    """% âm lượng (100 = giữ nguyên) → dB. 0% = tắt hẳn."""
    import math
    return -90.0 if pct <= 0 else 20 * math.log10(pct / 100)


def track_gains(runner: ft.Runner, ms: MusicSettings, paths: dict[int, str], log=None, on_step=None) -> dict[int, float]:
    """Độ khuếch đại (dB) cho từng bài đang dùng: chuẩn hoá về mức LUFS đích (nếu bật) + âm lượng riêng của bài."""
    from concurrent.futures import ThreadPoolExecutor
    gains: dict[int, float] = {}
    tracks = sorted(paths)
    measured: dict[tuple[str, str], tuple[float | None, list[str]]] = {}
    use_map: dict[int, tuple[str, str]] = {}
    if ms.loudness_enabled and tracks:
        use = usable_paths(runner, paths)  # bài hỏng: đo trên bản sạch (dùng lại lúc ghép)
        use_map = {t: (paths[t], use[t]) for t in tracks}
        uniq = list(dict.fromkeys(use_map.values()))
        done_n = 0
        step_lock = threading.Lock()

        def measure_one(pair: tuple[str, str]):
            nonlocal done_n
            orig, u = pair
            notes: list[str] = []
            with step_lock:
                idx = done_n
                done_n += 1
            if on_step:
                on_step(idx, len(uniq))
            val = loudness_or_none(runner, orig, u, notes.append if log else None)
            return pair, (val, notes)

        if len(uniq) >= 2:
            with ThreadPoolExecutor(max_workers=min(4, len(uniq))) as pool:
                measured = dict(pool.map(measure_one, uniq))
        else:
            measured = dict(measure_one(p) for p in uniq)
    logged_notes: set[tuple[str, str]] = set()
    for t in tracks:
        if ms.loudness_enabled:
            pair = use_map[t]
            lufs, notes = measured[pair]
            if log and pair not in logged_notes:
                logged_notes.add(pair)
                for msg in notes:
                    log(msg)
            if lufs is not None:
                gains[t] = max(-20.0, min(20.0, ms.lufs - lufs))
                if log:
                    log(f"  {Path(paths[t]).name}: {lufs:.1f} LUFS → {gains[t]:+.1f} dB")
        vol = ms.tracks[t].volume if 0 <= t < len(ms.tracks) else 100
        if vol != 100:
            gains[t] = gains.get(t, 0.0) + volume_db(vol)
            if log:
                log(f"  {Path(paths[t]).name}: âm lượng riêng {vol}% ({volume_db(vol):+.1f} dB)")
    return gains


SOURCE_GAIN_MAX = 15.0  # tiếng gốc: cân tối đa ±15 dB (clip gần như im lặng thì để nguyên, không kéo ồn nền lên)


def source_gains(runner: ft.Runner, paths: dict[int, str], audible: dict[int, bool], target: float,
                 log=None) -> dict[int, float]:
    """Tự cân tiếng gốc: dB cho từng clip có tiếng để clip nào cũng to bằng mức LUFS đích (cùng mức với nhạc).
    Nhờ vậy 100% tiếng gốc + 100% nhạc nghe ngang nhau, clip to / nhỏ khác nhau không còn chênh."""
    from concurrent.futures import ThreadPoolExecutor
    gains: dict[int, float] = {}
    files = list(dict.fromkeys(p for k, p in sorted(paths.items()) if audible.get(k)))
    with ThreadPoolExecutor(max_workers=4) as pool:  # đo 4 clip cùng lúc (40–50 clip: nhanh gấp ~3 lần)
        seen = dict(zip(files, pool.map(lambda p: loudness_or_none(runner, p, p, log), files)))
    for path in files:
        if log and seen[path] is not None:
            g = max(-SOURCE_GAIN_MAX, min(SOURCE_GAIN_MAX, target - seen[path]))
            log(f"  Tiếng gốc {Path(path).name}: {seen[path]:.1f} LUFS → {g:+.1f} dB")
    for k, path in sorted(paths.items()):
        if not audible.get(k):
            continue
        lufs = seen[path]
        if lufs is not None:
            gains[k] = max(-SOURCE_GAIN_MAX, min(SOURCE_GAIN_MAX, target - lufs))
    return gains


def loudness_or_none(runner: ft.Runner, path: str, use: str, log=None) -> float | None:
    """Đo độ to `use` (bản sạch nếu `path` hỏng). Đo không được — file hỏng nặng làm ffmpeg dừng giữa chừng — thì
    tạo bản sạch rồi đo lại; vẫn không được thì bỏ qua bước cân (giữ nguyên âm lượng), không làm dừng lượt xuất."""
    try:
        return measure_loudness(runner, use)
    except ft.FFmpegError:
        pass
    try:
        mark_damaged(path)
        return measure_loudness(runner, clean_copy(runner, path))
    except ft.FFmpegError:
        if log:
            log(f"  {Path(path).name}: không đo được độ to (file hỏng nặng) — giữ nguyên âm lượng.")
        return None


def measure_loudness(runner: ft.Runner, path: str) -> float | None:
    """Độ to tích hợp (LUFS) của bài. Có cache trên đĩa."""
    cached = cached_loudness(path)
    if cached is not None:
        return cached
    stderr = runner.ffmpeg(["-v", "info", "-i", path, "-vn", "-af",
                            "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr)
    if not m:
        return None
    try:
        value = float(json.loads(m.group(0))["input_i"])
    except (ValueError, KeyError):
        return None
    if value < -70 or value > 0:  # bài gần như im lặng / số vô lý (đo phải đoạn dữ liệu rác)
        return None
    with _lock:
        try:  # chỉ là bộ nhớ đệm: ghi không được (ổ đầy / file khoá) thì thôi, không làm hỏng lượt xuất
            p = ft.data_dir() / "loudness.json"
            db = dict(_peek_json_cached(p))
            db[_file_id(path)] = value
            _write_json_cached(p, db)
        except OSError:
            pass
    return value


def escape_filter_value(value: str) -> str:
    """Escape một giá trị option nằm trong filtergraph (2 cấp: option rồi graph)."""
    level1 = re.sub(r"([\\':])", r"\\\1", value)
    return re.sub(r"([\\'\[\],;])", r"\\\1", level1)


MUSIC_DIRECT_MAX = 32  # lịch phát dài hơn mức này thì dựng sẵn khối FLAC rồi nối tuần tự, tránh mở hàng trăm amovie cùng lúc
MUSIC_BLK_VERSION = "mb1"


def _music_block(runner: ft.Runner, path: str, gain_db: float, duration: float,
                 fade_in: float, fade_out: float, pad_gap: float) -> Path:
    """Một lượt phát bài nhạc đã áp sẵn âm lượng, fade đầu/cuối, đệm lặng (FLAC 48 kHz stereo s16 trong bộ nhớ đệm)."""
    import hashlib
    fid = _file_id(path)
    key = hashlib.sha1(
        f"{MUSIC_BLK_VERSION}|{fid}|{gain_db:.2f}|{duration:.6f}|{fade_in:.3f}|{fade_out:.3f}|{pad_gap:.3f}"
        .encode("utf-8")
    ).hexdigest()[:24]
    out = ft.cache_dir("musicblk") / f"{key}.flac"
    if out.is_file() and out.stat().st_size > 0:
        try:
            os.utime(out)
        except OSError:
            pass
        return out
    src = escape_filter_value(path.replace("\\", "/"))
    chain = (f"amovie=filename={src},asetpts=PTS-STARTPTS,aresample=48000,"
             f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
             f"volume={gain_db:.2f}dB,"
             f"apad=whole_dur={duration:.6f},atrim=end={duration:.6f}")
    if fade_in > 0:
        chain += f",afade=t=in:d={fade_in:.3f}:curve=tri"
    if fade_out > 0:
        chain += f",afade=t=out:st={max(0.0, duration - fade_out):.6f}:d={fade_out:.3f}:curve=tri"
    if pad_gap > 0:
        chain += f",apad=pad_dur={pad_gap:.3f}"
    chain += ",aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo[o]"
    tmp = out.with_name(f"{key}.{os.getpid()}-{threading.get_ident()}.tmp.flac")
    try:
        runner.ffmpeg(["-v", "error", "-filter_complex", chain, "-map", "[o]",
                       "-c:a", "flac", "-compression_level", "1", str(tmp)])
        try:
            os.replace(tmp, out)
        except OSError:
            tmp.unlink(missing_ok=True)
            if out.is_file() and out.stat().st_size > 0:
                return out
            raise
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return out


def _silence_block(runner: ft.Runner, duration: float) -> Path:
    """Khối im lặng dài `duration` giây (FLAC 48 kHz stereo s16, vài KB) để chèn khoảng chờ trên làn crossfade."""
    import hashlib
    key = hashlib.sha1(f"{MUSIC_BLK_VERSION}|sil|{duration:.6f}".encode("utf-8")).hexdigest()[:24]
    out = ft.cache_dir("musicblk") / f"{key}.flac"
    if out.is_file() and out.stat().st_size > 0:
        return out
    tmp = out.with_name(f"{key}.{os.getpid()}-{threading.get_ident()}.tmp.flac")
    try:
        runner.ffmpeg(["-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{duration:.6f}",
                       "-af", CLEAN_FMT, "-c:a", "flac", "-compression_level", "1", str(tmp)])
        try:
            os.replace(tmp, out)
        except OSError:
            tmp.unlink(missing_ok=True)
            if out.is_file() and out.stat().st_size > 0:
                return out
            raise
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return out


def music_concat_graph(
    runner: ft.Runner,
    items: list[MusicItem],
    paths: dict[int, str],
    gains_db: dict[int, float],
    ms: MusicSettings,
    total: float,
    job_dir: Path,
    input_idx: int,
    out_label: str = "music",
) -> tuple[list[str], list[str]]:
    """Dành cho lịch phát dài (> `MUSIC_DIRECT_MAX` lượt): mã hoá từng khối bài duy nhất 1 lần ra FLAC rồi nối bằng
    1–2 luồng `-f concat` tuần tự thay vì mở đồng thời hàng trăm bộ giải mã `amovie=` trong một lệnh ffmpeg."""
    from concurrent.futures import ThreadPoolExecutor
    from . import video_build

    xf = ms.crossfade if ms.crossfade > 0 else 0.0
    n = len(items)
    specs = []
    for k, it in enumerate(items):
        fi = xf if (xf > 0 and k > 0) else 0.0
        fo = xf if (xf > 0 and k < n - 1) else 0.0
        pad = ms.gap if (xf == 0 and ms.gap > 0 and k < n - 1) else 0.0
        gdb = round(gains_db.get(it.track, 0.0), 2)
        specs.append((paths[it.track], gdb, round(it.duration, 6), round(fi, 3), round(fo, 3), round(pad, 3)))
    uniq_specs = list(dict.fromkeys(specs))
    if len(uniq_specs) >= 2:
        with ThreadPoolExecutor(max_workers=min(4, len(uniq_specs))) as pool:
            blk_map = dict(zip(uniq_specs, pool.map(lambda s: _music_block(runner, *s), uniq_specs)))
    else:
        blk_map = {s: _music_block(runner, *s) for s in uniq_specs}

    inputs: list[str] = []
    lines: list[str] = []
    if xf > 0 and n > 1:
        gap_durs: list[float] = []
        lane_rows: list[list[tuple[str, float | int]]] = [[], []]
        for lane in (0, 1):
            pos = 0.0
            for k in range(lane, n, 2):
                it = items[k]
                gap = round(it.start - pos, 6)
                if gap > 1e-4:
                    gap_durs.append(gap)
                    lane_rows[lane].append(("gap", gap))
                lane_rows[lane].append(("blk", k))
                pos = it.start + it.duration
        uniq_gaps = list(dict.fromkeys(gap_durs))
        if len(uniq_gaps) >= 2:
            with ThreadPoolExecutor(max_workers=min(4, len(uniq_gaps))) as pool:
                sil_map = dict(zip(uniq_gaps, pool.map(lambda d: _silence_block(runner, d), uniq_gaps)))
        else:
            sil_map = {d: _silence_block(runner, d) for d in uniq_gaps}
        for lane in (0, 1):
            cpath = job_dir / f"music_lane{lane}.ffconcat"
            citems = [(sil_map[float(val)], float(val)) if kind == "gap"
                      else (blk_map[specs[int(val)]], items[int(val)].duration)
                      for kind, val in lane_rows[lane]]
            video_build.write_concat(cpath, citems)
            inputs += ["-f", "concat", "-safe", "0", "-i", str(cpath)]
            lines.append(f"[{input_idx + lane}:a]aresample=48000:async=1,"
                         f"aformat=sample_fmts=fltp:channel_layouts=stereo[lane{lane}];")
        lines.append("[lane0][lane1]amix=inputs=2:normalize=0:duration=longest[xc];")
        last = "xc"
    else:
        cpath = job_dir / "music_lane0.ffconcat"
        citems = [(blk_map[specs[k]], items[k].duration + specs[k][5]) for k in range(n)]
        video_build.write_concat(cpath, citems)
        inputs += ["-f", "concat", "-safe", "0", "-i", str(cpath)]
        lines.append(f"[{input_idx}:a]aresample=48000:async=1,"
                     f"aformat=sample_fmts=fltp:channel_layouts=stereo[xc];")
        last = "xc"
    tail = f"[{last}]apad,atrim=end={total:.6f}"
    if ms.fade_in > 0:
        tail += f",afade=t=in:d={min(ms.fade_in, total):.3f}"
    if ms.fade_out > 0:
        fo = min(ms.fade_out, total)
        tail += f",afade=t=out:st={total - fo:.6f}:d={fo:.3f}"
    lines.append(f"{tail}[{out_label}];")
    return inputs, lines


def music_graph(
    items: list[MusicItem],
    paths: dict[int, str],
    gains_db: dict[int, float],
    ms: MusicSettings,
    total: float,
    out_label: str = "music",
) -> list[str]:
    """Các dòng filtergraph tạo nhãn [out_label] dài đúng `total` giây."""
    lines = []
    xf = ms.crossfade if ms.crossfade > 0 else 0.0
    n = len(items)
    for k, it in enumerate(items):
        src = escape_filter_value(paths[it.track].replace("\\", "/"))
        chain = (f"amovie=filename={src},asetpts=PTS-STARTPTS,aresample=48000,"
                 f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                 f"volume={gains_db.get(it.track, 0.0):.2f}dB,"
                 # MP3 VBR thiếu header / AAC thô: ffprobe đoán dài hơn thực tế → đệm im lặng cho đúng độ dài
                 # đã lên lịch, để bài sau không bị lệch (không có khoảng lặng giữa chừng / 2 bài chồng nhau)
                 f"apad=whole_dur={it.duration:.6f},atrim=end={it.duration:.6f}")
        if xf > 0 and k > 0:
            chain += f",afade=t=in:d={xf:.3f}:curve=tri"
        if xf > 0 and k < n - 1:
            chain += f",afade=t=out:st={it.duration - xf:.6f}:d={xf:.3f}:curve=tri"
        if xf == 0 and ms.gap > 0 and k < n - 1:
            chain += f",apad=pad_dur={ms.gap:.3f}"
        lines.append(f"{chain}[m{k}];")
    if n == 1:
        last = "m0"
    elif xf > 0:
        # Crossfade bằng 2 "làn": bài chẵn ở làn A, bài lẻ ở làn B, đệm khoảng lặng cho đúng
        # vị trí rồi trộn 2 làn. Chi phí tuyến tính, không bị chậm dần như chuỗi acrossfade.
        for lane in (0, 1):
            parts, pos = [], 0.0
            for k in range(lane, n, 2):
                it = items[k]
                if it.start - pos > 1e-4:
                    lab = f"z{k}"
                    lines.append(f"aevalsrc=exprs=0|0:s=48000:d={it.start - pos:.6f},"
                                 f"aformat=sample_fmts=fltp:channel_layouts=stereo[{lab}];")
                    parts.append(f"[{lab}]")
                parts.append(f"[m{k}]")
                pos = it.start + it.duration
            lines.append("".join(parts) + f"concat=n={len(parts)}:v=0:a=1[lane{lane}];")
        lines.append("[lane0][lane1]amix=inputs=2:normalize=0:duration=longest[xc];")
        last = "xc"
    else:
        lines.append("".join(f"[m{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1[xc];")
        last = "xc"
    tail = f"[{last}]apad,atrim=end={total:.6f}"
    if ms.fade_in > 0:
        tail += f",afade=t=in:d={min(ms.fade_in, total):.3f}"
    if ms.fade_out > 0:
        fo = min(ms.fade_out, total)
        tail += f",afade=t=out:st={total - fo:.6f}:d={fo:.3f}"
    lines.append(f"{tail}[{out_label}];")
    return lines


def seamless_loop(runner: ft.Runner, path: str, duration: float) -> str:
    """Bản lặp liền mạch của một lớp tiếng nền: đoạn cuối hoà dần vào đoạn đầu (equal-power), nên khi lặp lại
    không còn tiếng "khựng" ở chỗ nối. Lưu bộ nhớ đệm (FLAC) theo file + độ dài."""
    if duration < 1.0:
        return path
    x = min(3.0, duration * 0.2)
    st = os.stat(path)
    import hashlib
    key = hashlib.sha1(f"loop2|{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{st.st_mtime_ns}|{duration:.3f}"
                       .encode("utf-8")).hexdigest()[:24]
    out = ft.cache_dir("ambient") / f"{key}.flac"
    if out.is_file() and out.stat().st_size > 0:
        return str(out)
    d = duration
    graph = (f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=3[a][b][c];"
             f"[a]atrim=start={x:.6f}:end={d - x:.6f},asetpts=PTS-STARTPTS[mid];"
             f"[b]atrim=start={d - x:.6f}:end={d:.6f},asetpts=PTS-STARTPTS,afade=t=out:d={x:.6f}:curve=qsin[tail];"
             f"[c]atrim=start=0:end={x:.6f},asetpts=PTS-STARTPTS,afade=t=in:d={x:.6f}:curve=qsin[head];"
             f"[tail][head]amix=inputs=2:normalize=0:duration=longest[x];"
             f"[mid][x]concat=n=2:v=0:a=1[out]")
    tmp = out.with_name(f"{key}.{os.getpid()}-{threading.get_ident()}.tmp.flac")
    try:
        runner.ffmpeg(["-v", "error", "-i", path, "-filter_complex", graph, "-map", "[out]", "-c:a", "flac",
                       str(tmp)])
        os.replace(tmp, out)
    except ft.CancelledError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception:  # noqa: BLE001 — không tạo được thì dùng file gốc (lặp thẳng)
        tmp.unlink(missing_ok=True)
        return path
    return str(out)


def ambient_graph(paths: list[str], volumes: list[int], total: float, fade_in: float = 0.0,
                  fade_out: float = 0.0, offsets: list[float] | None = None) -> tuple[list[str], list[str]]:
    """Mỗi lớp tiếng nền tự lặp vô hạn rồi cắt đúng `total` giây. Trả về (dòng graph, nhãn).
    `offsets`: bắt đầu từ giây thứ mấy của vòng lặp (nghe thử / xem trước giữa video: nghe đúng như bản xuất)."""
    lines, labels = [], []
    for k, (path, vol) in enumerate(zip(paths, volumes)):
        src = escape_filter_value(path.replace("\\", "/"))
        off = (offsets[k] if offsets and k < len(offsets) else 0.0) or 0.0
        cut = (f"atrim=start={off:.6f}:end={off + total:.6f},asetpts=PTS-STARTPTS" if off > 0
               else f"atrim=end={total:.6f}")
        lines.append(f"amovie=filename={src}:loop=0,asetpts=N/SR/TB,aresample=48000,"
                     f"aformat=sample_fmts=fltp:channel_layouts=stereo,volume={vol / 100:.3f},"
                     f"{cut}{_fades(fade_in, fade_out, total)}[amb{k}];")
        labels.append(f"amb{k}")
    return lines, labels


def _fades(fade_in: float, fade_out: float, total: float) -> str:
    out = ""
    if fade_in > 0:
        out += f",afade=t=in:d={min(fade_in, total):.3f}"
    if fade_out > 0:
        fo = min(fade_out, total)
        out += f",afade=t=out:st={total - fo:.6f}:d={fo:.3f}"
    return out


def master_graph(
    music_label: str | None,
    source_label: str | None,
    music_volume: int,
    source_volume: int,
    total: float,
    ambient_labels: list[str] | None = None,
) -> list[str]:
    """Trộn nhạc + tiếng gốc + tiếng nền, chống vỡ tiếng, ra nhãn [aout]."""
    parts = []
    inputs = []
    if music_label:
        parts.append(f"[{music_label}]volume={music_volume / 100:.3f}[mv];")
        inputs.append("[mv]")
    if source_label:
        parts.append(f"[{source_label}]aresample=48000:async=1,apad,atrim=end={total:.6f},"
                     f"volume={source_volume / 100:.3f}[sv];")
        inputs.append("[sv]")
    inputs += [f"[{lab}]" for lab in ambient_labels or []]
    if len(inputs) > 1:
        parts.append(f"{''.join(inputs)}amix=inputs={len(inputs)}:normalize=0:duration=longest[mx];")
        src = "[mx]"
    else:
        src = inputs[0]
    parts.append(f"{src}apad,alimiter=limit=0.891:level=0:latency=1,atrim=end={total:.6f}[aout]")
    return parts
