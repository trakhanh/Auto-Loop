"""Kiểm thử các lỗi phần lõi tìm thấy khi audit bản 1.8.8 (sửa ở 1.8.9)."""
import json
import os
import random
import shutil
import stat
import subprocess
from collections import namedtuple
from fractions import Fraction

import pytest

from loopstation.core import audio_build, ffmpeg_tools as ft, probe, profiles, render, video_build
from loopstation.core.project import AmbientLayer, ClipItem, Project


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setitem(ft.OPTIONS, "cache_dir", "")


def _ff(*args):
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", *args], check=True)


def _audio(path, corrupt=False, d=10):
    _ff("-f", "lavfi", "-i", f"anoisesrc=color=pink:d={d}:seed=7", "-c:a", "aac", "-b:a", "192k", str(path))
    if corrupt:  # rải byte hỏng giữa phần âm thanh (như file tải về bị lỗi)
        b = bytearray(path.read_bytes())
        rnd = random.Random(3)
        for _ in range(300):
            i = rnd.randint(len(b) // 3, len(b) * 2 // 3)
            b[i] = rnd.randint(0, 255)
        path.write_bytes(bytes(b))


# ---------- 1. clip cắt bằng -ss -c copy (edit list) ----------
def test_frames_at_respects_mp4_edit_list(tmp_path):
    src, cut = tmp_path / "goc.mp4", tmp_path / "cat.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=s=160x120:r=30:d=8", "-c:v", "libx264", "-g", "60", str(src))
    _ff("-ss", "1.5", "-i", str(src), "-c", "copy", str(cut))
    info = probe.probe(str(cut))
    decoded = subprocess.run([ft.ffprobe(), "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                              "stream=nb_read_frames", "-of", "csv=p=0", str(cut)],
                             capture_output=True, text=True).stdout.strip()
    assert probe.frames_at(info, Fraction(30)) == int(decoded)  # không đệm frame đóng băng ở cuối mỗi vòng
    assert probe.frames_at(probe.probe(str(src)), Fraction(30)) == 240


def test_frames_at_keeps_nb_frames_when_close():
    info = probe.MediaInfo("x.mp4", duration=8.0, has_video=True, fps=Fraction(30), nb_frames=241)
    assert probe.frames_at(info, Fraction(30)) == 241  # lệch ≤ 1 frame (làm tròn thời lượng): tin nb_frames
    info.nb_frames = 300
    assert probe.frames_at(info, Fraction(30)) == 240


# ---------- 2. hồ sơ kênh giữ tiếng nền dựng sẵn ----------
def test_profile_keeps_builtin_ambient(tmp_path):
    real = tmp_path / "mua.m4a"
    real.write_bytes(b"x")
    p = Project()
    p.music.ambient = [AmbientLayer("builtin:rain_heavy", True, 40), AmbientLayer(str(real), False, 70),
                       AmbientLayer(str(tmp_path / "mat.m4a"), True, 50)]
    q, _ = profiles.apply(profiles.capture("Kênh A", p), Project())
    assert [(a.path, a.enabled, a.volume) for a in q.music.ambient] == [
        ("builtin:rain_heavy", True, 40), (str(real), False, 70)]


# ---------- 3. dọn bộ nhớ đệm đo đúng ổ chứa bộ nhớ đệm ----------
def test_prune_cache_measures_cache_drive(tmp_path, monkeypatch):
    cache = tmp_path / "o_D"
    monkeypatch.setitem(ft.OPTIONS, "cache_dir", str(cache))
    for part in ("blocks", "cleanaudio", "ambient"):
        for i in range(2):
            (ft.cache_dir(part) / f"{part}{i}.bin").write_bytes(b"x" * 1000)
    du = namedtuple("du", "total used free")

    def fake(path):  # ổ bộ nhớ đệm gần đầy, ổ dữ liệu còn rộng
        return du(100, 100, 10) if str(path).startswith(str(cache)) else du(10 ** 12, 0, 10 ** 12)

    monkeypatch.setattr(ft.shutil, "disk_usage", fake)
    assert ft.prune_cache(need_free=10 ** 9) == 6000
    for part in ("blocks", "cleanaudio", "ambient"):
        assert not list(ft.cache_dir(part).iterdir())


# ---------- 4. lượt ghép hỏng: chỉ đánh dấu đúng bài hỏng ----------
def test_force_marks_only_failing_file(tmp_path):
    good, bad = tmp_path / "lanh.m4a", tmp_path / "hong.m4a"
    _audio(good)
    _audio(bad, corrupt=True)
    # giả lập kiểm tra nhanh bỏ sót: sổ ghi "lành" cho cả hai
    ft.data_dir()
    audio_build._check_db_path().write_text(json.dumps({audio_build._file_id(str(p)): False for p in (good, bad)}),
                                            encoding="utf-8")
    r = ft.Runner()
    out = audio_build.usable_paths(r, {0: str(good), 1: str(bad)}, force=True)
    assert out[0] == str(good) and out[1].endswith(".flac")
    assert audio_build.is_damaged(r, str(bad)) and not audio_build.is_damaged(r, str(good))


def test_force_without_culprit_cleans_all_this_time_only(tmp_path):
    a, b = tmp_path / "a.m4a", tmp_path / "b.m4a"
    _audio(a)
    _audio(b)
    r = ft.Runner()
    logs = []
    out = audio_build.usable_paths(r, {0: str(a), 1: str(b)}, logs.append, force=True)
    assert all(p.endswith(".flac") for p in out.values())  # lượt này: bản sạch cho mọi bài
    assert any("Không xác định" in s for s in logs)
    assert not audio_build.is_damaged(r, str(a)) and not audio_build.is_damaged(r, str(b))  # không nhớ "hỏng"
    assert audio_build.usable_paths(r, {0: str(a)}) == {0: str(a)}


# ---------- 5. bộ nhớ đệm độ to ghi không được thì bỏ qua ----------
def test_measure_loudness_survives_readonly_cache(tmp_path):
    song = tmp_path / "bai.m4a"
    _audio(song, d=4)
    lj = ft.data_dir() / "loudness.json"
    lj.write_text("{}", encoding="utf-8")
    os.chmod(lj, stat.S_IREAD)
    try:
        assert audio_build.measure_loudness(ft.Runner(), str(song)) is not None
    finally:
        os.chmod(lj, stat.S_IWRITE | stat.S_IREAD)
    assert not list(ft.data_dir().glob("*.tmp"))
    assert audio_build.measure_loudness(ft.Runner(), str(song)) is not None
    assert json.loads(lj.read_text(encoding="utf-8"))  # ghi được lại thì lưu như thường


# ---------- 6. lỗi card không do giới hạn phiên: không bớt số phiên ----------
_8K = ("[h264_nvenc @ 0] No capable devices found\n[enc:h264_nvenc] Error while opening encoder - maybe incorrect "
       "parameters such as bit_rate, rate, width or height.\nTask finished with error code: -22 (Invalid argument)")
_LIMIT = "[h264_nvenc @ 0] OpenEncodeSessionEx failed: out of memory (10)\n[h264_nvenc @ 0] No capable devices found"


class _Stop(Exception):
    pass


def _gpu_render(tmp_path, monkeypatch, stderr):
    clip = tmp_path / "clip.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=s=160x120:r=30:d=2", "-c:v", "libx264", str(clip))
    p = Project(name="GPU")
    p.video.clips = [ClipItem(str(clip), count=2)]
    seen = []

    def fake(self, segs, paths, tl, encoder):
        seen.append(encoder)
        if len(seen) == 1:
            raise ft.FFmpegError("ffmpeg lỗi", stderr)
        raise _Stop()

    monkeypatch.setattr(render.RenderJob, "_encode_blocks", fake)
    render._GPU_JOBS.clear()
    avail = {"h264": ["nvidia", "cpu"], "hevc": ["nvidia", "cpu"], "audio": []}
    with pytest.raises(_Stop):
        render.RenderJob(p, avail, str(tmp_path / "ra.mp4")).run()
    return seen


def test_gpu_capability_error_falls_back_to_cpu_without_throttling(tmp_path, monkeypatch):
    seen = _gpu_render(tmp_path, monkeypatch, _8K)
    try:
        assert seen[0].endswith("_nvenc") and seen[1].startswith("lib")
        assert render._GPU_JOBS == {}  # lần xuất sau vẫn chạy đủ phiên
    finally:
        render._GPU_JOBS.clear()


def test_gpu_session_limit_lowers_jobs(tmp_path, monkeypatch):
    seen = _gpu_render(tmp_path, monkeypatch, _LIMIT)
    try:
        assert seen[0] == seen[1] and seen[1].endswith("_nvenc")
        assert render._GPU_JOBS == {seen[0]: 2}
    finally:
        render._GPU_JOBS.clear()


# ---------- 7. log xuất không tích mãi ----------
def test_render_logs_pruned(tmp_path):
    d = ft.data_dir() / "logs"
    d.mkdir(parents=True)
    for i in range(205):
        (d / f"render_20200101_{i:06d}.log").write_text("x", encoding="utf-8")
    (d / "khac.txt").write_text("x", encoding="utf-8")
    job = render.RenderJob(Project(), {}, str(tmp_path / "x.mp4"))
    job.log("thử")
    newest = job._write_log_file()
    logs = sorted(f.name for f in d.glob("render_*.log"))
    assert len(logs) == render.LOG_KEEP and newest.name in logs
    assert "render_20200101_000000.log" not in logs and (d / "khac.txt").is_file()


# ---------- 8. khối vừa được luồng khác tạo xong ----------
def test_run_cached_uses_existing_block_when_replace_fails(monkeypatch):
    def build(tmp):
        return ["-v", "error", "-f", "lavfi", "-i", "anullsrc", "-t", "0.1", tmp]

    out = ft.cache_dir("blocks") / "dua.wav"

    def busy(src, dst):  # luồng khác ghi xong trước và đang đọc file đích
        out.write_bytes(b"x" * 10)
        raise PermissionError(13, "file đang mở")

    monkeypatch.setattr(video_build.os, "replace", busy)
    assert video_build._run_cached(ft.Runner(), "blocks", "dua", ".wav", build) == out
    assert [f.name for f in out.parent.iterdir()] == ["dua.wav"]  # không để lại file tạm


# ---------- 9. on_progress ném lỗi: không để ffmpeg chạy mồ côi ----------
def test_runner_kills_ffmpeg_when_progress_raises(monkeypatch):
    procs = []
    real = ft._attach
    monkeypatch.setattr(ft, "_attach", lambda p: (procs.append(p), real(p)))
    r = ft.Runner()

    def boom(_):
        raise RuntimeError("giao diện lỗi")

    with pytest.raises(RuntimeError):
        r.ffmpeg(["-re", "-f", "lavfi", "-i", "anullsrc", "-t", "60", "-f", "null", "-"], boom)
    assert procs and procs[0].poll() is not None and not r._procs
