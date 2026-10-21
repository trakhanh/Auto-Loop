"""Bộ phát xem trước: dựng khung hình bằng FFmpeg y như lúc xuất (khung hình, crossfade, màu & logo, mờ dần cuối)
nhưng KHÔNG mã hoá — ra thẳng khung hình thô cỡ nhỏ (360p / 540p) để app vẽ lên màn hình.

Mỗi khối của timeline (thân một lần phát / đoạn crossfade) là một lệnh ffmpeg ngắn; luồng nền dựng trước vài giây
khung hình vào hàng đợi. Clip nền lặp 70 lần chỉ phải giải mã một lần: khối đã dựng được giữ trong RAM (LRU).
Thuần Python + ffmpeg, không dùng Qt (giao diện ở ui/preview_player.py)."""
from __future__ import annotations

import bisect
import os
import subprocess
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from fractions import Fraction

from . import ffmpeg_tools as ft
from . import planner, video_build
from .look import from_settings as look_from_settings
from .probe import IMAGE_EXTS

QUALITY = {"fast": 360, "sharp": 540, "hd": 720}  # chiều cao tối đa của khung xem trước
QUEUE_SECONDS = 2.0  # dựng trước bao nhiêu giây hình
CACHE_BYTES = 256 * 1024 * 1024  # RAM tối đa giữ khối đã dựng (clip nền lặp lại không phải giải mã lại)
QUEUE_BYTES = 160 * 1024 * 1024  # hàng đợi khung hình tối đa (720p60 không chiếm vài trăm MB)
CACHE_SEG_MAX = 96 * 1024 * 1024  # khối dài hơn mức này không giữ (clip dài phát một lần)


def preview_size(width: int, height: int, max_h: int) -> tuple[int, int]:
    """Cỡ khung xem trước: giữ tỉ lệ của video xuất, cao tối đa `max_h` (dọc 9:16 thì rộng tối đa `max_h`)."""
    k = min(1.0, max_h / min(width, height))
    w = max(16, int(width * k) // 4 * 4)  # chia hết cho 4: mỗi dòng ảnh RGB khớp bộ nhớ, không phải đệm
    h = max(16, int(height * k) // 2 * 2)
    return w, h


@dataclass
class Schedule:
    """Lịch phát hình của bản xem trước: các khối theo thứ tự + frame bắt đầu của từng khối."""
    segs: list[planner.Segment]
    starts: list[int]
    total_frames: int
    fps: Fraction
    paths: dict[int, str]
    offsets: dict[int, int]
    fit: str
    fade_out: float
    look: object
    look_bookends: bool
    width: int
    height: int
    is_image: dict[int, bool] = field(default_factory=dict)
    token: str = ""  # dấu của mọi thứ ảnh hưởng tới hình (file, cắt, khung, màu & logo, cỡ, fps) — khoá bộ nhớ đệm

    def cache_key(self, seg: planner.Segment):
        """Khoá bộ nhớ đệm của một khối: đổi màu / logo / cắt / thứ tự clip / cỡ khung → khoá khác (không dùng hình cũ)."""
        return (self.token, seg)

    def queue_capacity(self) -> int:
        return max(4, min(int(float(self.fps) * QUEUE_SECONDS), QUEUE_BYTES // max(1, self.frame_bytes)))

    @property
    def frame_bytes(self) -> int:
        return self.width * self.height * 3

    @property
    def total(self) -> float:
        return float(Fraction(self.total_frames) / self.fps)

    def seg_at(self, frame: int) -> tuple[int, int]:
        """(chỉ số khối, số frame tính từ đầu khối) tại frame `frame` của video."""
        frame = max(0, min(frame, self.total_frames - 1))
        k = bisect.bisect_right(self.starts, frame) - 1
        return k, frame - self.starts[k]


def make_schedule(project, tl, max_h: int = 360) -> Schedule | None:
    """Từ timeline đã tính (timeline.build). None nếu không có hình (kiểu Chỉ nhạc / lỗi)."""
    if tl is None or not tl.ok or tl.video is None or tl.video.error:
        return None
    segs = planner.segments(tl.video, tl.frames)
    if not segs:
        return None
    starts, pos = [], 0
    for seg in segs:
        starts.append(pos)
        pos += seg.frames
    w, h = preview_size(tl.width, tl.height, max_h)
    vs = project.video
    paths = {k: inf.path for k, inf in tl.clip_infos.items()}
    look = look_from_settings(vs)
    ids = []
    for k in sorted(paths):
        try:
            st = os.stat(paths[k])
            ids.append(f"{k}:{os.path.normcase(paths[k])}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            ids.append(f"{k}:{paths[k]}")
    token = "|".join([*ids, repr(sorted(tl.offsets.items())), f"{w}x{h}", vs.fit, f"{vs.fade_out:.3f}", str(tl.fps),
                      look.key() if look is not None else "", str(vs.look_bookends)])
    return Schedule(segs=segs, starts=starts, total_frames=pos, fps=tl.fps, paths=paths, offsets=dict(tl.offsets),
                    fit=vs.fit, fade_out=vs.fade_out, look=look, look_bookends=vs.look_bookends,
                    width=w, height=h,
                    is_image={k: inf.is_image or inf.path.lower().endswith(tuple(IMAGE_EXTS))
                              for k, inf in tl.clip_infos.items()},
                    token=token)


def segment_args(sch: Schedule, idx: int, skip: int) -> list[str]:
    """Lệnh ffmpeg dựng khối `idx` (bỏ `skip` frame đầu) ra khung hình RGB thô qua stdout."""
    seg = sch.segs[idx]
    fps = sch.fps
    look, side = video_build.segment_look(seg, sch.look, sch.look_bookends)
    fade = min(sch.fade_out, video_build.seconds(seg.frames, fps)) if seg.fade else 0.0
    off_a = sch.offsets.get(seg.clip, 0)
    off_b = sch.offsets.get(seg.clip_b, 0) if seg.kind == "xfade" else 0
    seek_a = 0
    inputs = []
    if seg.kind == "body" and not sch.is_image.get(seg.clip):
        seek_a = seg.start + off_a + skip  # tua thẳng tới chỗ cần ở đầu vào: không giải mã lại từ đầu clip dài
        if seek_a:
            inputs += ["-ss", f"{float(Fraction(seek_a) / fps):.6f}"]
    inputs += video_build._input(sch.paths[seg.clip], fps)
    if seg.kind == "xfade":
        inputs += video_build._input(sch.paths[seg.clip_b], fps)
    graph = video_build.segment_graph(seg, sch.paths, fps, sch.width, sch.height, sch.fit, "rgb24", fade,
                                      off_a, off_b, look, side, skip=skip, seek_a=seek_a)
    return ["-v", "error", "-nostdin", *inputs, "-filter_complex", graph, "-map", "[v]",
            "-frames:v", str(seg.frames - skip), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]


class FrameCache:
    """Khối đã dựng (danh sách khung hình) giữ trong RAM, bỏ khối lâu không dùng khi quá `limit` byte."""

    def __init__(self, limit: int = CACHE_BYTES):
        self.limit = limit
        self._d: OrderedDict = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            v = self._d.get(key)
            if v is not None:
                self._d.move_to_end(key)
            return v

    def put(self, key, frames: list[bytes]) -> None:
        size = sum(len(f) for f in frames)
        if size > CACHE_SEG_MAX or size > self.limit:
            return
        with self._lock:
            if key in self._d:
                return
            self._d[key] = frames
            self._size += size
            while self._size > self.limit and self._d:
                _k, old = self._d.popitem(last=False)
                self._size -= sum(len(f) for f in old)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
            self._size = 0


class FrameQueue:
    """Hàng đợi khung hình (frame số mấy của video, dữ liệu RGB). Luồng dựng chờ khi đầy."""

    def __init__(self, capacity: int):
        self.capacity = max(2, capacity)
        self._q: deque = deque()
        self._cv = threading.Condition()
        self.finished = False  # đã dựng tới cuối video (hoặc đủ số frame yêu cầu)
        self.error = ""
        self.closed = False

    def put(self, index: int, data: bytes) -> bool:
        with self._cv:
            while len(self._q) >= self.capacity and not self.closed:
                self._cv.wait(0.2)
            if self.closed:
                return False
            self._q.append((index, data))
            return True

    def finish(self, error: str = "") -> None:
        with self._cv:
            self.finished = True
            self.error = error
            self._cv.notify_all()

    def close(self) -> None:
        with self._cv:
            self.closed = True
            self._q.clear()
            self._cv.notify_all()

    def __len__(self) -> int:
        return len(self._q)

    def next_index(self) -> int | None:
        with self._cv:
            return self._q[0][0] if self._q else None

    def take_until(self, frame: int):
        """Lấy khung hình mới nhất có số ≤ `frame` (bỏ các khung cũ hơn — máy chậm thì bỏ bớt khung cho kịp)."""
        got = None
        with self._cv:
            while self._q and self._q[0][0] <= frame:
                got = self._q.popleft()
            if got is not None:
                self._cv.notify_all()
        return got


class FrameProducer(threading.Thread):
    """Dựng khung hình từ frame `start` trở đi vào `queue`. `count`: chỉ dựng bấy nhiêu frame (ví dụ 1 khi tua)."""

    def __init__(self, sch: Schedule, start: int, queue: FrameQueue, cache: FrameCache | None = None,
                 count: int | None = None):
        super().__init__(daemon=True)
        self.sch, self.start_frame, self.queue, self.cache, self.count = sch, start, queue, cache, count
        self._halt = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def stop(self) -> None:
        self._halt.set()
        self.queue.close()
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.kill()
                except OSError:
                    pass

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            self.queue.finish(str(e))
            return
        self.queue.finish()

    def _run(self) -> None:
        sch = self.sch
        fb = sch.frame_bytes
        left = self.count
        idx, skip = sch.seg_at(self.start_frame)
        frame_no = sch.starts[idx] + skip
        while idx < len(sch.segs) and not self._halt.is_set():
            seg = sch.segs[idx]
            want = seg.frames - skip
            if left is not None:
                want = min(want, left)
            frames = self.cache.get(sch.cache_key(seg)) if self.cache is not None else None
            if frames is not None and (not frames or len(frames[0]) != fb):
                frames = None  # khác cỡ khung (đổi chất lượng / độ phân giải): dựng lại
            if frames is not None:
                for k in range(skip, skip + want):
                    if not self.queue.put(frame_no, frames[min(k, len(frames) - 1)]):
                        return
                    frame_no += 1
            else:
                keep = [] if (self.cache is not None and skip == 0 and want == seg.frames
                              and seg.frames * fb <= CACHE_SEG_MAX) else None
                got = self._decode(idx, skip, want, frame_no, keep)
                if got < 0:
                    return
                frame_no += want
                if keep is not None and len(keep) == seg.frames:
                    self.cache.put(sch.cache_key(seg), keep)
            if left is not None:
                left -= want
                if left <= 0:
                    return
            idx += 1
            skip = 0

    def _decode(self, idx: int, skip: int, want: int, frame_no: int, keep: list | None) -> int:
        """Chạy ffmpeg cho một khối, đẩy `want` khung hình vào hàng đợi. Trả về -1 nếu bị dừng giữa chừng."""
        fb = self.sch.frame_bytes
        cmd = [ft.ffmpeg(), "-hide_banner", *segment_args(self.sch, idx, skip)]
        if want < self.sch.segs[idx].frames - skip:  # chỉ cần vài frame (tua): dừng sớm
            i = cmd.index("-frames:v")
            cmd[i + 1] = str(want)
        with self._lock:
            if self._halt.is_set():
                return -1
            proc = self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                 stdin=subprocess.DEVNULL, creationflags=ft.CREATE_NO_WINDOW,
                                                 bufsize=fb * 4)
            ft._attach(proc)
        err: list[bytes] = []
        t = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
        t.start()
        last = None
        n = 0
        try:
            while n < want:
                data = proc.stdout.read(fb)
                if not data or len(data) < fb:
                    break
                last = data
                if keep is not None:
                    keep.append(data)
                if not self.queue.put(frame_no + n, data):
                    return -1
                n += 1
        finally:
            try:
                proc.stdout.close()
            except OSError:
                pass
            if proc.poll() is None and (self._halt.is_set() or n >= want):
                try:
                    proc.kill()
                except OSError:
                    pass
            proc.wait()
            t.join(2)
            with self._lock:
                self._proc = None
        if self._halt.is_set():
            return -1
        if n == 0:
            msg = b"".join(err).decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError("Không dựng được hình xem trước: " + (msg[-1] if msg else "ffmpeg lỗi"))
        while n < want:  # clip ngắn hơn dự kiến vài frame: giữ khung cuối cho đúng thời gian
            if keep is not None:
                keep.append(last)
            if not self.queue.put(frame_no + n, last):
                return -1
            n += 1
        return n
