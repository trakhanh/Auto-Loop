"""Cửa sổ Xem trước: phát video thành phẩm ngay trong app (hình + nhạc + tiếng gốc + tiếng nền), tua tới bất kỳ
chỗ nào, không phải xuất file.

- Hình: core.preview_engine dựng khung hình y như lúc xuất (khung hình, crossfade, màu & logo) nhưng không mã hoá.
- Tiếng: dựng nối tiếp từng đoạn ~20 giây ở nền (core.audio_preview), app tự hoà các kênh khi phát → kéo thanh
  âm lượng ở Bảng trộn âm là nghe đổi ngay.
- Đồng bộ: đồng hồ theo tiếng đã ra loa; hình chưa kịp thì tạm dừng tiếng chờ (không lệch tiếng / hình)."""
from __future__ import annotations

import shutil
import threading
import time
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

from PySide6.QtCore import QElapsedTimer, QIODevice, QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen,
                           QShortcut)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ..core import audio_preview, preview_engine, timeline
from ..core import ffmpeg_tools as ft
from . import icons, theme
from .live_mix import BUFFER_MS, CHUNK, FRAME, LIMIT, RATE, WIDTH, read_pcm, retire

BPS = RATE * FRAME  # byte âm thanh mỗi giây
FIRST_CHUNK, NEXT_CHUNK, AHEAD = 4.0, 20.0, 12.0  # giây: đoạn tiếng đầu ngắn cho nhanh, sau đó dựng trước ~12 s
QUALITIES = [("auto", "Tự động"), ("fast", "360p — mượt"), ("sharp", "540p — nét"), ("hd", "720p — nét nhất")]


def fmt_time(sec: float) -> str:
    s = max(0, int(sec))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def project_signature(proj) -> str:
    """Dấu của dự án để biết có phải dựng lại bản xem trước không. Âm lượng ở Bảng trộn âm không tính:
    phần đó đổi ngay lúc phát, không dựng lại."""
    import copy
    import json
    p = copy.deepcopy(proj)
    p.video.music_volume = p.video.source_volume = 100
    for a in p.music.ambient:
        a.volume = 100
    p.name = ""
    return json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False, default=str)


def project_gains(project) -> dict[str, float]:
    """Âm lượng các kênh theo dự án (giống Bảng trộn âm)."""
    v = project.video
    g = {"music": v.music_volume / 100, "source": v.source_volume / 100}
    for k, a in enumerate(project.music.ambient):
        g[f"amb:{k}"] = a.volume / 100 if a.enabled else 0.0
    return g


# ======================= tiếng =======================

class StreamMixer:
    """Như live_mix.Mixer nhưng nối thêm được từng đoạn khi đang phát."""

    def __init__(self, gains: dict[str, float]):
        self.gains = dict(gains)
        self.master = 1.0  # nút tắt tiếng của trình phát (không đổi âm lượng của dự án)
        self.stems: dict[str, bytearray] = {}
        self.pos = 0
        self.ended = False
        self._lim = 1.0
        self._lock = threading.Lock()

    @property
    def length(self) -> int:
        return min((len(b) for b in self.stems.values()), default=0) // FRAME * FRAME

    def append(self, chunk: dict[str, bytes], seconds: float) -> None:
        n = int(round(seconds * RATE)) * FRAME
        with self._lock:
            base = self.length if self.stems else 0
            for key, data in chunk.items():
                if key not in self.stems:
                    self.stems[key] = bytearray(base)  # kênh mới giữa chừng: phần trước im lặng
                part = data[:n] + bytes(max(0, n - len(data)))
                self.stems[key] += part
            for key, arr in self.stems.items():
                if key not in chunk:
                    arr += bytes(n)
            if self.pos > 32 * BPS:  # bỏ phần đã phát (giữ RAM nhỏ khi xem lâu)
                drop = self.pos
                for arr in self.stems.values():
                    del arr[:drop]
                self.pos = 0

    def ahead(self) -> float:
        """Còn bao nhiêu giây tiếng chưa đưa ra loa."""
        return (self.length - self.pos) / BPS

    def mix(self, n: int) -> bytes:
        with self._lock:
            n = min(n, self.length - self.pos) // FRAME * FRAME
            if n <= 0:
                return b""
            acc = None
            for key, data in self.stems.items():
                g = self.gains.get(key, 1.0) * 0.5 * self.master
                if g <= 0:
                    continue
                part = audioop.mul(bytes(data[self.pos:self.pos + n]), WIDTH, g)
                acc = part if acc is None else audioop.add(acc, part, WIDTH)
            self.pos += n
        if acc is None:
            return bytes(n)
        peak = audioop.max(acc, WIDTH) * 2
        want = min(1.0, LIMIT / peak) if peak else 1.0
        self._lim = want if want < self._lim else min(want, self._lim + 0.02)
        return audioop.mul(acc, WIDTH, 2 * self._lim)


class _Device(QIODevice):
    def __init__(self, owner: "AudioStream"):
        super().__init__()
        self.owner = owner

    def readData(self, maxlen):  # noqa: N802
        return self.owner._read(maxlen) if self.owner is not None else b""

    def writeData(self, data):  # noqa: N802
        return 0

    def bytesAvailable(self) -> int:  # noqa: N802
        return (CHUNK if self.owner is not None else 0) + super().bytesAvailable()

    def isSequential(self) -> bool:  # noqa: N802
        return True


class AudioStream(QObject):
    """Tiếng của bản xem trước, phát liên tục từ mốc `start`. Không có tiếng nào → `failed`."""
    ready = Signal()
    failed = Signal(str)
    _chunk = Signal(int, object, float, float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chunk.connect(self._on_chunk)
        self._gen = 0
        self.mixer: StreamMixer | None = None
        self._sink = None
        self._dev = None
        self._fmt = None
        self._runner: ft.Runner | None = None
        self._busy = False
        self.has_data = False
        self.disabled = False
        self.t0 = 0.0
        self._next = 0.0
        self.total = 0.0
        self._silence = 0  # byte im lặng đã chèn khi tiếng chưa dựng kịp (không tính vào thời gian)
        self._last = 0.0

    def available(self) -> bool:
        try:
            from PySide6.QtMultimedia import QAudioFormat, QMediaDevices
        except ImportError:
            return False
        fmt = QAudioFormat()
        fmt.setSampleRate(RATE)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        dev = QMediaDevices.defaultAudioOutput()
        if dev.isNull() or not dev.isFormatSupported(fmt):
            return False
        self._fmt = fmt
        return True

    def start(self, project, start: float, total: float, gains: dict[str, float], version: int = 0) -> None:
        self.stop()
        self._gen += 1
        self.version = version
        self.project, self.t0, self._next, self.total = project, start, start, total
        self.mixer = StreamMixer(gains)
        self.has_data = self.disabled = False
        self._silence, self._last = 0, start
        if not self.available():
            self.disabled = True
            self.failed.emit("Máy không phát được âm thanh — chỉ xem hình.")
            return
        self._request(FIRST_CHUNK)

    def _request(self, seconds: float) -> None:
        if self._busy or self.disabled or self.mixer is None or self.mixer.ended:
            return
        if self._next >= self.total - 0.02:
            self.mixer.ended = True
            return
        self._busy = True
        gen, project, start = self._gen, self.project, self._next
        sec = min(seconds, self.total - start)
        if self.total - start - sec < 1.0:  # phần lẻ < 1 giây cuối: gộp luôn vào đoạn này (ffmpeg không dựng đoạn quá ngắn)
            sec = self.total - start
        version = getattr(self, "version", 0)
        runner = self._runner = ft.Runner()

        def work():
            try:
                st = audio_preview.render_stems(project, start, runner, version=version, seconds=sec)
                try:
                    data = {k: read_pcm(f) for k, f in st.files.items()}
                finally:
                    shutil.rmtree(st.folder, ignore_errors=True)
            except ft.CancelledError:
                return
            except Exception as e:  # noqa: BLE001
                self._emit(gen, None, start, sec, str(e))
                return
            self._emit(gen, data, st.start, st.seconds, "")

        threading.Thread(target=work, daemon=True).start()

    def _emit(self, *args) -> None:
        try:
            self._chunk.emit(*args)
        except RuntimeError:
            pass

    def _on_chunk(self, gen: int, data, start: float, seconds: float, err: str) -> None:
        if gen != self._gen or self.mixer is None:
            return
        self._busy = False
        if err or data is None:
            if not self.has_data:
                self.disabled = True
                self.failed.emit(err.strip().splitlines()[-1] if err else "Không dựng được âm thanh")
            else:
                self.mixer.ended = True  # lỗi giữa chừng: phát hết phần đã có
            return
        if not self.has_data:
            self.t0 = self._last = start  # sát cuối video ffmpeg lùi mốc bắt đầu một chút: đồng hồ theo mốc thật
        self.mixer.append(data, seconds)
        self._next = start + seconds
        if self._next >= self.total - 0.02:
            self.mixer.ended = True
        if not self.has_data:
            self.has_data = True
            self.ready.emit()

    def tick(self) -> None:
        """Gọi đều đặn: dựng trước đoạn kế khi phần chưa phát còn ít."""
        m = self.mixer
        if m is not None and not m.ended and not self._busy and not self.disabled and m.ahead() < AHEAD:
            self._request(NEXT_CHUNK)

    def starving(self) -> bool:
        m = self.mixer
        return not self.disabled and m is not None and not m.ended and m.ahead() <= 0.05

    def finished_playing(self) -> bool:
        """Đã phát ra loa hết phần tiếng (cuối video, hoặc dừng vì lỗi giữa chừng)."""
        m = self.mixer
        return not self.disabled and m is not None and m.ended and m.ahead() <= 0

    def begin(self) -> None:
        from PySide6.QtMultimedia import QAudioSink, QMediaDevices
        if self.disabled or self._sink is not None:
            return
        self._sink = QAudioSink(QMediaDevices.defaultAudioOutput(), self._fmt, self)
        self._sink.setBufferSize(BPS * BUFFER_MS // 1000)
        self._dev = _Device(self)
        self._dev.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink.start(self._dev)

    def suspend(self) -> None:
        if self._sink is not None:
            self._sink.suspend()

    def resume(self) -> None:
        if self._sink is not None:
            self._sink.resume()

    def position(self) -> float:
        """Giây của video đang ra loa (không tính phần im lặng chèn khi tiếng chưa kịp)."""
        if self._sink is None:
            return self._last
        pos = self.t0 + self._sink.processedUSecs() / 1e6 - self._silence / BPS
        self._last = max(self._last, pos)  # không lùi
        return self._last

    def set_gain(self, key: str, gain: float) -> None:
        if self.mixer is not None:
            self.mixer.gains[key] = gain

    def _read(self, maxlen: int) -> bytes:
        m = self.mixer
        if m is None:
            return b""
        data = m.mix(min(maxlen, CHUNK))
        if data:
            return data
        if m.ended:
            return b""
        n = min(maxlen, CHUNK) // FRAME * FRAME  # tiếng chưa dựng kịp: im lặng, đồng hồ đứng chờ
        self._silence += n
        return bytes(n)

    def stop(self) -> None:
        self._gen += 1
        self._busy = False
        if self._runner is not None:
            self._runner.cancel()
            self._runner = None
        sink, self._sink = self._sink, None
        dev, self._dev = self._dev, None
        retire(sink, dev)  # đóng nguồn tiếng sau khi bộ phát đã dừng (không hiện cảnh báo QIODevice)
        self.mixer = None


# ======================= bộ phát =======================

class PreviewPlayer(QObject):
    """Ghép hình + tiếng. Trạng thái: empty · loading · paused · playing · buffering · ended."""
    frameReady = Signal(QImage)
    positionChanged = Signal(float)
    stateChanged = Signal(str)
    message = Signal(str)
    loaded = Signal(float)  # tổng thời lượng
    _built = Signal(int, object, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._built.connect(self._on_built)
        self.audio = AudioStream(self)
        self.audio.ready.connect(self._check_ready)
        self.audio.failed.connect(self._on_audio_failed)
        self.cache = preview_engine.FrameCache()
        self.project = None
        self.tl = None
        self.sch: preview_engine.Schedule | None = None
        self.total = 0.0
        self.pos = 0.0
        self.state = "empty"
        self.quality = "auto"
        self.view_height = lambda: 360  # cỡ khung xem (điểm ảnh thật) — chất lượng "Tự động" chọn theo đó
        self.muted = False
        self.version = 0  # Chỉ nhạc nhiều bản: đang nghe bản nào
        self._reloading = False  # đang tính lại lịch phát (dự án vừa đổi): tua chỉ ghi nhớ chỗ, chưa dựng
        self._warm_runner: ft.Runner | None = None
        self.gains: dict[str, float] = {}
        self._gen = 0
        self._queue: preview_engine.FrameQueue | None = None
        self._producer: preview_engine.FrameProducer | None = None
        self._still: tuple | None = None  # (producer, queue) khung hình tĩnh khi tua lúc đang dừng
        self._want_play = False
        self._seek_to: float | None = None  # mốc vừa tua, chờ áp dụng (đồng hồ phát không được ghi đè)
        self._still_pending: float | None = None  # chỗ cần hiện tiếp khi khung tĩnh đang dựng xong
        self._clock = QElapsedTimer()
        self._clock_base = 0.0
        self._audio_clock = False
        self._shown = -1
        self._last_emit = 0.0
        self._load_t, self._slow_note = 0.0, False
        self._tick = QTimer(self)
        self._tick.setTimerType(Qt.TimerType.PreciseTimer)
        self._tick.setInterval(8)
        self._tick.timeout.connect(self._on_tick)
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(90)
        self._seek_timer.timeout.connect(self._apply_seek)

    # ---------- dự án ----------
    def set_project(self, project, gains: dict[str, float] | None = None, version: int = 0) -> None:
        """Nạp (hoặc nạp lại khi dự án đổi) — giữ nguyên chỗ đang xem; đang phát thì phát tiếp từ chỗ đó."""
        self._gen += 1
        gen = self._gen
        self.project = project
        self.version = version
        self._reloading = True
        self.gains = dict(gains or project_gains(project))
        resume = self.state in ("playing", "loading", "buffering") or self._want_play
        self._halt()
        self._want_play = resume
        self._set_state("loading")
        self.message.emit("Đang tính lịch phát…")
        max_h = self._max_h()

        def work():
            try:
                music_only = project.output_kind == "music_only"
                tl = timeline.build_audio(project, version) if music_only else timeline.build(project)
                if not tl.ok:
                    raise RuntimeError("\n".join(tl.errors))
                sch = None if music_only else preview_engine.make_schedule(project, tl, max_h)
                if not music_only and sch is None:
                    raise RuntimeError("Chưa có hình để xem.")
                try:
                    self._built.emit(gen, tl, sch, "")
                except RuntimeError:
                    pass
            except Exception as e:  # noqa: BLE001
                try:
                    self._built.emit(gen, None, None, str(e))
                except RuntimeError:
                    pass

        threading.Thread(target=work, daemon=True).start()

    def _on_built(self, gen: int, tl, sch, err: str) -> None:
        if gen != self._gen:
            return
        self._reloading = False
        self._halt()  # bỏ mọi thứ còn dựng theo lịch phát cũ (ví dụ tua lúc đang nạp)
        if err:
            self.tl, self.sch, self.total = None, None, 0.0
            self._set_state("empty")
            self.message.emit(err.strip().splitlines()[0] if err.strip() else "Chưa xem được")
            self.loaded.emit(0.0)
            return
        self.tl, self.sch = tl, sch
        self.total = tl.total
        self.pos = min(self.pos, max(0.0, self.total - 0.05))
        self.loaded.emit(self.total)
        self.positionChanged.emit(self.pos)
        if self._want_play:
            self._start_at(self.pos)
        else:
            self._set_state("paused")
            self.message.emit("" if sch else "Chỉ nhạc — bấm Phát để nghe")
            self._show_still(self.pos)
            self._warm_audio(gen)

    def _warm_audio(self, gen: int) -> None:
        """Dựng thử 1 giây tiếng ở nền ngay khi nạp: lần đầu app phải đo độ to các bài, tạo bản lặp tiếng nền…
        (mất vài giây) — làm trước lúc người dùng còn đang xem hình thì bấm Phát là chạy ngay."""
        project, start, version = self.project, self.pos, self.version
        if self._warm_runner is not None:
            self._warm_runner.cancel()  # sửa liên tục lúc đang dừng: không chồng nhiều lần làm nóng
        runner = self._warm_runner = ft.Runner()

        def work():
            if gen != self._gen:
                return
            try:
                st = audio_preview.render_stems(project, start, runner, version=version, seconds=1.0)
                shutil.rmtree(st.folder, ignore_errors=True)
            except Exception:  # noqa: BLE001 — chỉ là làm nóng bộ nhớ đệm
                pass

        threading.Thread(target=work, daemon=True).start()

    def _max_h(self) -> int:
        if self.quality in preview_engine.QUALITY:
            return preview_engine.QUALITY[self.quality]
        h = self.view_height()  # tự động: không dựng nét hơn khung xem đang hiện (máy đỡ nặng, phát mượt)
        return 360 if h <= 420 else (540 if h <= 640 else 720)

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        if self.audio.mixer is not None:
            self.audio.mixer.master = 0.0 if muted else 1.0

    def set_quality(self, key: str) -> None:
        if key != self.quality:
            self.quality = key
            self.cache.clear()
            if self.project is not None:
                self.set_project(self.project, self.gains)

    def set_gain(self, key: str, gain: float) -> None:
        self.gains[key] = gain
        self.audio.set_gain(key, gain)

    def set_gains(self, gains: dict[str, float]) -> None:
        for k, v in gains.items():
            self.set_gain(k, v)

    # ---------- điều khiển ----------
    def toggle(self) -> None:
        if self.state in ("playing", "loading", "buffering"):
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        if self.project is None:
            return  # chưa có gì để phát (ví dụ bảng clip trống)
        if self.tl is None or self._reloading:
            self._want_play = True  # đang tính lịch phát (dự án mới / vừa đổi): phát ngay khi xong
            return
        if self.state in ("playing", "buffering"):
            return
        if self.state == "paused" and self._producer is not None and self._queue is not None:
            self._resume()  # dừng tạm rồi phát tiếp: không dựng lại
            return
        if self.pos >= self.total - 0.05:
            self.pos = 0.0
        self._start_at(self.pos)

    def pause(self) -> None:
        self._want_play = False
        if self.state not in ("playing", "buffering", "loading"):
            return
        if self.state == "loading":
            self._halt()
            self._set_state("paused")
            self.message.emit("")
            return
        self.pos = self._now()
        self.audio.suspend()
        self._tick.stop()
        self._set_state("paused")
        self.message.emit("")
        self.positionChanged.emit(self.pos)

    def seek(self, t: float) -> None:
        """Tua tới giây `t` (gọi liên tục khi kéo thanh: chỉ áp dụng lần cuối sau ~0,1 giây)."""
        self.pos = self._seek_to = max(0.0, min(t, max(0.0, self.total - 0.05)))
        self.positionChanged.emit(self.pos)
        if self.state in ("playing", "loading", "buffering") or not self._seek_timer.isActive():
            # đang phát: chờ thả tay mới phát lại (khỏi dựng lại liên tục); đang dừng: cứ ~0,1 giây hiện một khung
            # hình theo chỗ đang kéo (kéo vạch phát là thấy hình chạy theo, như CapCut)
            self._seek_timer.start()

    def step(self, dt: float) -> None:
        self.seek((self._now() if self.state == "playing" else self.pos) + dt)

    def _apply_seek(self) -> None:
        if self._seek_to is not None:
            self.pos, self._seek_to = self._seek_to, None
        if self.tl is None or self._reloading:
            return  # đang tính lại lịch phát: chỉ nhớ chỗ, nạp xong sẽ dựng đúng chỗ này
        if self.state in ("playing", "buffering", "loading"):
            self._start_at(self.pos)
        else:
            # đang dừng: bỏ phần đã dựng sẵn để phát tiếp (chỗ cũ), giữ khung tĩnh đang dựng dở
            if self._producer is not None:
                self._producer.stop()
            self._producer = self._queue = None
            self.audio.stop()
            self._tick.stop()
            self._set_state("paused")
            self._show_still(self.pos)

    def stop(self) -> None:
        """Dừng hẳn và quên dự án (bảng clip trống / đóng): Space hay bấm Phát không phát lại video cũ."""
        self._want_play = False
        self._reloading = False
        self._gen += 1
        self._halt()
        if self._warm_runner is not None:
            self._warm_runner.cancel()
            self._warm_runner = None
        self.project = self.tl = self.sch = None
        self.total = self.pos = 0.0
        self._set_state("empty")

    # ---------- bên trong ----------
    def _set_state(self, s: str) -> None:
        if s != self.state:
            self.state = s
            self.stateChanged.emit(s)

    def _halt(self) -> None:
        self._tick.stop()
        self._seek_timer.stop()
        for prod in (self._producer, self._still[0] if self._still else None):
            if prod is not None:
                prod.stop()
        self._producer = self._queue = self._still = None
        self.audio.stop()

    def _start_at(self, t: float) -> None:
        self._halt()
        self.pos = t
        self._shown = -1
        self._audio_clock = False
        if self.sch is not None:
            fps = float(self.sch.fps)
            self._queue = preview_engine.FrameQueue(self.sch.queue_capacity())
            self._producer = preview_engine.FrameProducer(self.sch, int(t * fps), self._queue, self.cache)
            self._producer.start()
        self._set_state("loading")
        self.message.emit("Đang chuẩn bị…")
        self._load_t, self._slow_note = time.monotonic(), False
        self._tick.start()
        self.audio.start(self.project, t, self.total, self.gains, self.version)
        if self.audio.mixer is not None:
            self.audio.mixer.master = 0.0 if self.muted else 1.0

    def _on_audio_failed(self, msg: str) -> None:
        if self.sch is None:  # Chỉ nhạc mà không có tiếng: không có gì để phát
            self._halt()
            self._set_state("paused")
            self.message.emit(msg)
            return
        self._check_ready()

    def _video_ready(self) -> bool:
        if self.sch is None:
            return True
        q = self._queue
        if q is None:
            return False
        if q.error:
            return True
        return q.finished or len(q) >= min(q.capacity, max(2, int(float(self.sch.fps) * 0.4)))

    def _audio_ready(self) -> bool:
        return self.audio.disabled or self.audio.has_data

    def _check_ready(self) -> None:
        if self.state != "loading" or not (self._video_ready() and self._audio_ready()):
            return
        if self._queue is not None and self._queue.error:
            self._fail(self._queue.error)
            return
        self._audio_clock = not self.audio.disabled
        if self._audio_clock:
            self.audio.begin()
        else:
            self._clock_base = self.pos
            self._clock.start()
        self._set_state("playing")
        self.message.emit("")

    def _resume(self) -> None:
        self._set_state("buffering")
        self._tick.start()

    def _now(self) -> float:
        if self._seek_to is not None:
            return self._seek_to
        if self.state == "paused" or self.state == "loading":
            return self.pos
        if self._audio_clock:
            return self.audio.position()
        return self._clock_base + self._clock.elapsed() / 1000

    def _fail(self, msg: str) -> None:
        self._want_play = False
        self._halt()
        self._set_state("paused")
        self.message.emit(msg.strip().splitlines()[-1] if msg.strip() else "Lỗi xem trước")

    def _on_tick(self) -> None:
        self.audio.tick()
        if self.state == "loading":
            self._check_ready()
            if self.state == "loading" and self._video_ready() and not self._audio_ready():
                waited = time.monotonic() - self._load_t
                if waited > 1.5 and not self._slow_note:
                    self._slow_note = True
                    self.message.emit("Đang chuẩn bị tiếng — lần đầu mất vài giây")
            return
        q = self._queue
        if self.state == "buffering":
            if self._video_ready() and not self.audio.starving():
                if self._audio_clock:
                    self.audio.resume()
                else:
                    self._clock_base = self.pos
                    self._clock.start()
                self._set_state("playing")
                self.message.emit("")
            return
        if self.state != "playing":
            return
        t = self._now()
        if self.sch is not None and q is not None:
            if q.error:
                self._fail(q.error)
                return
            target = int(t * float(self.sch.fps))
            item = q.take_until(target)
            if item is not None:
                self._emit_frame(item)
            elif not q.finished and len(q) == 0 and target > self._shown + 1:
                # hình chưa kịp: tạm dừng tiếng chờ hình (không lệch tiếng / hình)
                self.pos = t
                if self._audio_clock:
                    self.audio.suspend()
                self._set_state("buffering")
                self.message.emit("Đang tải hình…")
                return
        if self._audio_clock and self.audio.starving() and self.audio.mixer is not None:
            if time.monotonic() - self._last_emit > 0.5:
                self.message.emit("Đang tải tiếng…")
        if t >= self.total - 0.03 or (self._audio_clock and self.audio.finished_playing()):
            # hết video (hoặc tiếng đã phát hết — đồng hồ theo tiếng không chạy nữa): về trạng thái "hết"
            self.pos = self.total
            self._want_play = False
            self._halt()
            self._set_state("ended")
            self.positionChanged.emit(self.pos)
            return
        now = time.monotonic()
        if now - self._last_emit > 0.033 and self._seek_to is None:  # ~30 lần/giây: vạch phát chạy mượt
            self._last_emit = now
            self.pos = t
            self.positionChanged.emit(t)

    def _emit_frame(self, item) -> None:
        idx, data = item
        self._shown = idx
        sch = self.sch
        img = QImage(data, sch.width, sch.height, sch.width * 3, QImage.Format.Format_RGB888).copy()
        self.frameReady.emit(img)

    def _show_still(self, t: float) -> None:
        """Lúc đang dừng: dựng đúng một khung hình tại `t` để xem (kéo thanh tua là thấy hình)."""
        if self.sch is None:
            return
        if self._still is not None:
            prod, q0 = self._still
            if prod.is_alive() and not q0.finished:
                # đang dựng khung trước (kéo vạch phát liên tục): làm xong khung đó rồi dựng ngay chỗ mới nhất,
                # không huỷ giữa chừng (huỷ liên tục thì suốt lúc kéo không hiện được khung nào)
                self._still_pending = t
                return
            prod.stop()
        self._still_pending = None
        q = preview_engine.FrameQueue(2)
        prod = preview_engine.FrameProducer(self.sch, int(t * float(self.sch.fps)), q, self.cache, count=1)
        prod.start()
        self._still = (prod, q)
        poll = QTimer(self)
        poll.setInterval(15)
        started = time.monotonic()

        def check():
            if self._still is None or self._still[1] is not q:
                poll.stop()
                poll.deleteLater()
                return
            item = q.take_until(10 ** 12)
            if item is not None or q.finished or time.monotonic() - started > 20:
                poll.stop()
                poll.deleteLater()
                if item is None and not q.finished:  # ffmpeg treo > 20 giây: bỏ hẳn để lần tua sau còn hiện hình
                    prod.stop()
                    if self._still is not None and self._still[1] is q:
                        self._still = None
                if item is not None:
                    self._emit_frame(item)
                elif q.error:
                    self.message.emit(q.error)
                nxt, self._still_pending = self._still_pending, None
                if nxt is not None and self.state in ("paused", "ended"):
                    self._still = None
                    self._show_still(nxt)

        poll.timeout.connect(check)
        poll.start()


# ======================= giao diện =======================



def fmt_tc(sec: float, fps: float) -> str:
    """Mã thời gian kiểu CapCut / Premiere: giờ:phút:giây:khung."""
    sec = max(0.0, sec)
    s = int(sec)
    f = int(round((sec - s) * fps)) if fps else 0
    if fps and f >= round(fps):
        s, f = s + 1, 0
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}:{f:02d}"


class SeekBar(QWidget):
    """Thanh tua kiểu YouTube / CapCut: dày lên khi rê chuột, bong bóng giờ tại chỗ rê, vạch mốc đổi bài nhạc,
    kéo là tua liên tục (đang dừng thì hình chạy theo)."""
    seekRequested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.total = 0.0
        self.pos = 0.0
        self.marks: list[float] = []
        self._hover: float | None = None
        self._drag = False
        self.setToolTip("Kéo hoặc bấm để tua tới bất kỳ chỗ nào")

    # tương thích QSlider (bài kiểm tra / mã cũ)
    def maximum(self) -> int:
        return int(self.total * 10)

    def isSliderDown(self) -> bool:  # noqa: N802
        return self._drag

    def set_total(self, total: float) -> None:
        self.total = max(0.0, total)
        self.update()

    def set_position(self, t: float) -> None:
        if not self._drag:
            self.pos = t
            self.update()

    def set_marks(self, marks: list[float]) -> None:
        self.marks = marks
        self.update()

    def _track(self) -> QRectF:
        return QRectF(8, 22, max(1.0, self.width() - 16), 4)

    def _t_at(self, x: float) -> float:
        r = self._track()
        return max(0.0, min(1.0, (x - r.left()) / r.width())) * self.total

    def _x_at(self, t: float) -> float:
        r = self._track()
        return r.left() + (t / self.total if self.total else 0) * r.width()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.total:
            self._drag = True
            self.pos = self._t_at(e.position().x())
            self.seekRequested.emit(self.pos)
            self.update()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self.total:
            return
        self._hover = self._t_at(e.position().x())
        if self._drag:
            self.pos = self._hover
            self.seekRequested.emit(self.pos)
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._drag:
            self._drag = False
            self.seekRequested.emit(self.pos)
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = None
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hot = self._hover is not None or self._drag
        r = self._track()
        if hot:
            r = r.adjusted(0, -1.5, 0, 1.5)
        rad = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#232838"))
        p.drawRoundedRect(r, rad, rad)
        if self.total:
            if self._hover is not None and not self._drag:  # phần đang rê chuột (sáng nhẹ)
                hx = self._x_at(self._hover)
                p.setBrush(QColor(255, 255, 255, 28))
                p.drawRoundedRect(QRectF(r.left(), r.top(), max(0.0, hx - r.left()), r.height()), rad, rad)
            x = self._x_at(self.pos)
            g = QLinearGradient(r.left(), 0, r.right(), 0)
            g.setColorAt(0, theme.qcolor("accent"))
            g.setColorAt(1, theme.qcolor("accent2"))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(r.left(), r.top(), max(0.0, x - r.left()), r.height()), rad, rad)
            p.setBrush(QColor(255, 255, 255, 55 if not hot else 90))  # mốc đổi bài nhạc (mờ, chỉ rõ khi rê chuột)
            for m in self.marks:
                mx = self._x_at(m)
                p.drawRect(QRectF(mx - 0.5, r.top(), 1.0, r.height()))
            kr = 7 if hot else 5
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPointF(x, r.center().y()), kr, kr)
            if self._hover is not None:  # bong bóng giờ
                txt = fmt_time(self._hover)
                f = QFont(self.font())
                f.setPointSizeF(max(7.5, f.pointSizeF() - 1))
                f.setBold(True)
                p.setFont(f)
                tw = p.fontMetrics().horizontalAdvance(txt) + 14
                bx = max(0.0, min(self.width() - tw, self._x_at(self._hover) - tw / 2))
                p.setBrush(QColor(15, 18, 28, 235))
                p.setPen(QPen(QColor("#343e58"), 1))
                p.drawRoundedRect(QRectF(bx, 1, tw, 17), 6, 6)
                p.setPen(QColor("#eef1f8"))
                p.drawText(QRectF(bx, 1, tw, 17), Qt.AlignmentFlag.AlignCenter, txt)


class VideoView(QWidget):
    """Khung hình: bo góc, nền tối dịu; đang dừng có nút phát tròn ở giữa; đang tải có vòng xoay.
    Bấm một lần: phát / dừng · nhấp đúp: toàn màn hình."""
    doubleClicked = Signal()
    clicked = Signal()

    def __init__(self, parent=None, bg: str = "#0b0d13", rounded: bool = True):
        super().__init__(parent)
        self.setMinimumSize(240, 135)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # bấm vào khung xem → phím Space điều khiển trình phát
        self.setMouseTracking(True)
        self.bg = QColor(bg)
        self.rounded = rounded
        self.image: QImage | None = None
        self.text = ""
        self.audio_only = False
        self.paused = True
        self.busy = False
        self._busy_shown = False
        self._hover = False
        self._angle = 0
        self._spin = QTimer(self)
        self._spin.setInterval(16)
        self._spin.timeout.connect(self._rotate)
        self._busy_delay = QTimer(self)  # chỉ hiện vòng xoay khi chờ lâu hơn 0,25 giây (không nháy khi sửa nhanh)
        self._busy_delay.setSingleShot(True)
        self._busy_delay.setInterval(250)
        self._busy_delay.timeout.connect(self._show_busy)
        self._click = QTimer(self)  # bấm một lần (đợi xem có phải nhấp đúp không)
        self._click.setSingleShot(True)
        self._click.timeout.connect(self.clicked)

    def set_image(self, img: QImage) -> None:
        self.image = img
        self.update()

    def set_text(self, text: str) -> None:
        self.text = text
        self.update()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.update()

    def set_busy(self, busy: bool) -> None:
        if busy == self.busy:
            return
        self.busy = busy
        if busy:
            self._busy_delay.start()
        else:
            self._busy_delay.stop()
            self._busy_shown = False
            self._spin.stop()
            self.update()

    def _show_busy(self) -> None:
        if self.busy:
            self._busy_shown = True
            self._spin.start()
            self.update()

    def _rotate(self) -> None:
        self._angle = (self._angle + 7) % 360
        self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            if getattr(self, "_after_double", False):  # nhả chuột của lần nhấp đúp: không bật / dừng phát
                self._after_double = False
                return
            self._click.start(QApplication.doubleClickInterval())

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        self._click.stop()
        self._after_double = True
        self.doubleClicked.emit()

    def image_rect(self) -> QRectF:
        if self.image is None:
            return QRectF(self.rect())
        iw, ih = self.image.width(), self.image.height()
        k = min(self.width() / iw, self.height() / ih)
        dw, dh = iw * k, ih * k
        return QRectF((self.width() - dw) / 2, (self.height() - dh) / 2, dw, dh)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), self.bg)
        if self.image is not None and not self.audio_only:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            r = self.image_rect()
            if self.rounded:
                clip = QPainterPath()
                clip.addRoundedRect(r, 8, 8)
                p.save()
                p.setClipPath(clip)
                p.drawImage(r, self.image)
                p.restore()
                p.setPen(QPen(QColor(255, 255, 255, 18), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            else:
                p.drawImage(r, self.image)
        elif self.audio_only:
            pm = icons.pixmap("music", 56, "#3b3f55")
            p.drawPixmap((self.width() - 56) // 2, (self.height() - 56) // 2 - 16, pm)
        c = QPointF(self.width() / 2, self.height() / 2)
        if self._busy_shown:  # vòng xoay chờ
            p.setPen(QPen(QColor(255, 255, 255, 40), 4))
            p.drawEllipse(c, 18, 18)
            pen = QPen(theme.qcolor("accent"), 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(QRectF(c.x() - 18, c.y() - 18, 36, 36), -self._angle * 16, 100 * 16)
        elif self.paused and (self.image is not None or self.audio_only) and not self.text:
            # nút phát tròn ở giữa (bấm vào hình là phát)
            rad = 30 if self._hover else 27
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(10, 12, 20, 150 if self._hover else 115))
            p.drawEllipse(c, rad, rad)
            tri = QPainterPath()
            tri.moveTo(c.x() - 8, c.y() - 12)
            tri.lineTo(c.x() + 13, c.y())
            tri.lineTo(c.x() - 8, c.y() + 12)
            tri.closeSubpath()
            p.fillPath(tri, QColor(255, 255, 255, 235))
        if self.text:
            f = QFont(self.font())
            f.setBold(True)
            p.setFont(f)
            fm = p.fontMetrics()
            tw = min(self.width() - 24, fm.horizontalAdvance(self.text) + 28)
            y = c.y() + (32 if self._busy_shown or self.audio_only else -16)
            r = QRectF((self.width() - tw) / 2, y, tw, 32)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(10, 12, 20, 210))
            p.drawRoundedRect(r, 9, 9)
            p.setPen(QColor("#e5e7f0"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                       fm.elidedText(self.text, Qt.TextElideMode.ElideRight, int(tw) - 20))


class FullscreenView(VideoView):
    """Toàn màn hình: thanh điều khiển nổi ở đáy, tự ẩn sau 2,5 giây không rê chuột.
    Esc / F / nhấp đúp để thoát, Space phát / dừng, ← → tua 5 giây, bấm vào thanh để tua."""
    closed = Signal()

    def __init__(self, panel: "PreviewPanel"):
        super().__init__(None, bg="#000000", rounded=False)
        self.panel = panel
        self.setWindowTitle("Xem trước — toàn màn hình")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.doubleClicked.connect(self.close)
        self.clicked.connect(self.panel.player.toggle)
        self._ui = True
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.setInterval(2500)
        self._hide.timeout.connect(self._hide_ui)
        self._hide.start()

    def _hide_ui(self) -> None:
        if not self.paused:
            self._ui = False
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.update()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self._ui:
            self._ui = True
            self.unsetCursor()
            self.update()
        self._hide.start()

    def _bar(self) -> QRectF:
        return QRectF(32, self.height() - 46, self.width() - 64, 6)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        b = self._bar().adjusted(0, -10, 0, 10)
        if self._ui and b.contains(e.position()) and self.panel.player.total:
            self._click.stop()
            k = (e.position().x() - b.left()) / b.width()
            self.panel.player.seek(max(0.0, min(1.0, k)) * self.panel.player.total)
            self._skip_release = True
            return
        self._skip_release = False

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if getattr(self, "_skip_release", False):
            self._skip_release = False
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        k = e.key()
        if k in (Qt.Key.Key_Escape, Qt.Key.Key_F):
            self.close()
        elif k == Qt.Key.Key_Space:
            self.panel.player.toggle()
        elif k == Qt.Key.Key_Left:
            self.panel.player.step(-5)
        elif k == Qt.Key.Key_Right:
            self.panel.player.step(5)
        else:
            super().keyPressEvent(e)
        self.mouseMoveEvent(None)

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        if not self._ui:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        g = QLinearGradient(0, h - 130, 0, h)
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 190))
        p.fillRect(QRectF(0, h - 130, self.width(), 130), g)
        pl = self.panel.player
        b = self._bar()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRoundedRect(b, 3, 3)
        if pl.total:
            x = b.left() + b.width() * min(1.0, self.panel.shown_pos / pl.total)
            gr = QLinearGradient(b.left(), 0, b.right(), 0)
            gr.setColorAt(0, theme.qcolor("accent"))
            gr.setColorAt(1, theme.qcolor("accent2"))
            p.setBrush(gr)
            p.drawRoundedRect(QRectF(b.left(), b.top(), x - b.left(), b.height()), 3, 3)
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPointF(x, b.center().y()), 7, 7)
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        fps = self.panel._fps()
        p.drawText(QRectF(32, h - 34, 600, 28), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{fmt_tc(self.panel.shown_pos, fps)}  /  {fmt_tc(pl.total, fps)}")
        p.setPen(QColor(255, 255, 255, 150))
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() - 2)
        p.setFont(f)
        p.drawText(QRectF(self.width() - 632, h - 34, 600, 28), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "Space phát / dừng · ← → tua 5 giây · Esc thoát")

    def closeEvent(self, e) -> None:  # noqa: N802
        self.closed.emit()
        super().closeEvent(e)


def is_typing(w) -> bool:
    """Đang gõ chữ (ô tên, ô tìm, ô số lần phát đang sửa…) → phím Space là dấu cách, không phải Phát / Dừng."""
    from PySide6.QtWidgets import QAbstractSpinBox, QLineEdit, QPlainTextEdit, QTextEdit
    while w is not None:
        if isinstance(w, QAbstractSpinBox):
            return False  # ô số (giờ / phút / giây, %…): không gõ được dấu cách → Space vẫn là Phát / Dừng
        if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return not w.isReadOnly()
        if isinstance(w, QComboBox):
            return w.isEditable()
        w = w.parentWidget() if isinstance(w, QWidget) else None
    return False


class SpaceToggle(QObject):
    """Phím Space = Phát / Dừng trình phát ở MỌI chỗ trong cửa sổ (như CapCut / Premiere), trừ khi đang gõ chữ.
    Trước đây Space chỉ ăn khi con trỏ nằm trong trình phát; ở bảng clip nó bật / tắt clip, ở nút thì bấm nút đó —
    người dùng tưởng không dừng được video."""

    def __init__(self, window: QWidget, panel_fn):
        super().__init__(window)
        self.window, self.panel_fn = window, panel_fn
        QApplication.instance().installEventFilter(self)

    def _target(self, obj):
        panel = self.panel_fn()
        if panel is None or not panel.isVisible() or not isinstance(obj, QWidget):
            return None
        if obj.window() is not self.window or is_typing(obj):
            return None
        if getattr(self.window, "_welcome", None) is not None:
            return None  # màn hình chào đang mở: Space bấm nút đang chọn như thường
        return panel

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent
        t = ev.type()
        if t not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            return False
        if ev.key() != Qt.Key.Key_Space or ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            return False
        panel = self._target(obj)
        if panel is None:
            return False
        if t == QEvent.Type.ShortcutOverride:
            ev.accept()  # giữ phím cho bước KeyPress bên dưới (không để phím tắt / nút khác giành)
            return True
        if not ev.isAutoRepeat():
            panel.player.toggle()
        return True


class PreviewPanel(QFrame):
    """Trình phát xem trước kiểu CapCut / Premiere, nhúng ngay trong cửa sổ chính (luôn hiện), dùng chung với
    dòng thời gian bên dưới."""
    positionChanged = Signal(float)

    def __init__(self, settings=None, parent=None, title: str = "TRÌNH PHÁT"):
        super().__init__(parent)
        self.setObjectName("playerPanel")
        self.settings = settings
        self.player = PreviewPlayer(self)
        self.view = VideoView()
        self.shown_pos = 0.0
        self._full: FullscreenView | None = None
        self.player.view_height = lambda: int(self.view.height() * max(1.0, self.view.devicePixelRatioF()))
        self.player.frameReady.connect(self._on_frame)
        self.player.message.connect(self._on_message)
        self.player.stateChanged.connect(self._on_state)
        self.player.positionChanged.connect(self._on_pos)
        self.player.loaded.connect(self._on_loaded)
        self.view.doubleClicked.connect(self.toggle_fullscreen)
        self.view.clicked.connect(self.player.toggle)

        self.title = QLabel(title)
        self.title.setObjectName("playerTitle")
        self.info = QLabel("")
        self.info.setObjectName("playerInfo")
        self.quality = QComboBox()
        self.quality.setObjectName("playerCombo")
        for k, txt in QUALITIES:
            self.quality.addItem(txt, k)
        self.quality.setToolTip("Chất lượng hình xem trước (không ảnh hưởng bản xuất). Tự động: theo cỡ khung xem.\n"
                                "Máy yếu chọn 360p cho mượt.")
        saved = settings.value("preview/quality2", "auto") if settings is not None else "auto"
        self.quality.setCurrentIndex(max(0, self.quality.findData(saved)))
        self.player.quality = self.quality.currentData()
        self.quality.currentIndexChanged.connect(self._quality_changed)
        top = QHBoxLayout()
        top.setContentsMargins(14, 10, 10, 6)
        top.setSpacing(8)
        top.addWidget(self.title)
        top.addWidget(self.info)
        top.addStretch(1)
        top.addWidget(self.quality)

        self.slider = SeekBar()
        self.slider.seekRequested.connect(self.player.seek)

        self.tc = QLabel("00:00:00:00")
        self.tc.setObjectName("playerTime")
        self.tc_total = QLabel(" / 00:00:00:00")
        self.tc_total.setObjectName("playerTimeTotal")
        self.home_btn = self._btn("to_start", "", "Về đầu video (Home)", lambda: self.player.seek(0))
        self.back_btn = self._btn("replay10", "10", "Lùi 10 giây (←: 5 giây)", lambda: self.player.step(-10))
        self.play_btn = self._btn("play", "", "Phát (Space)", self.player.toggle, big=True)
        from . import effects
        self._play_glow = effects.Glow(self.play_btn, idle=0.35, blur=26, offset_y=3, alpha=160)
        self.fwd_btn = self._btn("forward10", "10", "Tới 10 giây (→: 5 giây)", lambda: self.player.step(10))
        self.mute_btn = self._btn("volume", "", "Tắt tiếng trình phát (không đổi âm lượng của dự án)", self._toggle_mute)
        self.full_btn = self._btn("fullscreen", "", "Toàn màn hình (nhấp đúp vào hình) — Esc để thoát",
                                  self.toggle_fullscreen)
        left = QHBoxLayout()
        left.setSpacing(0)
        left.addWidget(self.tc)
        left.addWidget(self.tc_total)
        left.addStretch(1)
        mid = QHBoxLayout()
        mid.setSpacing(6)
        for b in (self.home_btn, self.back_btn, self.play_btn, self.fwd_btn):
            mid.addWidget(b)
        right = QHBoxLayout()
        right.setSpacing(2)
        right.addStretch(1)
        right.addWidget(self.mute_btn)
        right.addWidget(self.full_btn)
        # thanh điều khiển: rộng thì 1 hàng [giờ | nút phát | loa, toàn màn hình], hẹp thì 2 hàng (không đè nhau)
        from PySide6.QtWidgets import QGridLayout
        self.bar = bar = QGridLayout()
        bar.setContentsMargins(14, 0, 10, 10)
        bar.setHorizontalSpacing(8)
        bar.setVerticalSpacing(4)
        self._lw, self._mw, self._rw = QWidget(), QWidget(), QWidget()
        self._lw.setLayout(left)
        self._mw.setLayout(mid)
        self._rw.setLayout(right)
        for lay_ in (left, mid, right):
            lay_.setContentsMargins(0, 0, 0, 0)
        self._narrow = None
        self._short_tc = False
        self._arrange()

        frame = QVBoxLayout()
        frame.setContentsMargins(10, 0, 10, 0)
        frame.addWidget(self.view, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addLayout(frame, 1)
        sl = QHBoxLayout()
        sl.setContentsMargins(10, 2, 10, 0)
        sl.addWidget(self.slider)
        lay.addLayout(sl)
        lay.addLayout(bar)

        # Space: xem SpaceToggle (cả cửa sổ). ← → Home: khi đang bấm vào trình phát (bảng clip dùng mũi tên để chọn dòng)
        for key, fn in ((Qt.Key.Key_Left, lambda: self.player.step(-5)),
                        (Qt.Key.Key_Right, lambda: self.player.step(5)), (Qt.Key.Key_Home, lambda: self.player.seek(0))):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self._on_state("empty")

    def _arrange(self) -> None:
        """Đặt lại thanh điều khiển theo bề rộng: đủ chỗ thì 1 hàng (cụm nút phát ở giữa), hẹp thì 2 hàng."""
        side = max(self._lw.sizeHint().width(), self._rw.sizeHint().width())
        narrow = self.width() < self._mw.sizeHint().width() + 2 * side + 40
        short = self.width() < 360  # rất hẹp: giờ không có số khung (00:06:44)
        if short != self._short_tc:
            self._short_tc = short
            self._on_loaded(self.player.total)
            self._on_pos(self.shown_pos)
        if narrow == self._narrow:
            return
        self._narrow = narrow
        for wd in (self._lw, self._mw, self._rw):
            self.bar.removeWidget(wd)
        for c in range(3):
            self.bar.setColumnStretch(c, 0)
        if narrow:
            self.bar.addWidget(self._lw, 0, 0)
            self.bar.addWidget(self._rw, 0, 2)
            self.bar.addWidget(self._mw, 1, 0, 1, 3, Qt.AlignmentFlag.AlignHCenter)
            self.bar.setColumnStretch(1, 1)
        else:
            self.bar.addWidget(self._lw, 0, 0)
            self.bar.addWidget(self._mw, 0, 1, Qt.AlignmentFlag.AlignHCenter)
            self.bar.addWidget(self._rw, 0, 2)
            self.bar.setColumnStretch(0, 1)  # hai bên giãn bằng nhau → cụm nút phát nằm đúng giữa
            self.bar.setColumnStretch(2, 1)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if hasattr(self, "bar"):
            self._arrange()

    def _tc(self, t: float) -> str:
        return fmt_tc(t, self._fps()) if not getattr(self, "_short_tc", False) else fmt_time(t)

    def _btn(self, icon: str, text: str, tip: str, fn, big: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("playerPlay" if big else "playerBtn")
        if icon:
            n = 20 if big else 16
            b.setIcon(icons.icon(icon, n, "#e5e7f0"))
            b.setIconSize(QSize(n, n))
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Space không "bấm" nhầm nút đang được chọn
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(fn)
        if text and not big:
            b.setMinimumWidth(b.sizeHint().width() + 6)  # khung hẹp: chữ "10" không bị cắt
        return b

    # ---------- dữ liệu ----------
    def open_project(self, project, gains: dict[str, float] | None = None, version: int = 0) -> None:
        self.view.audio_only = project.output_kind == "music_only"
        if self.view.audio_only:
            self.view.image = None
        self.player.set_project(project, gains, version)

    def clear(self, text: str) -> None:
        self.player.stop()
        self.player.cache.clear()  # trả RAM
        self.view.image = None
        self.view.audio_only = False
        self.view.set_busy(False)
        self.view.set_text(text)
        self.info.setText("")
        self._on_loaded(0.0)
        self._on_pos(0.0)

    def _toggle_mute(self) -> None:
        m = not self.player.muted
        self.player.set_muted(m)
        self.mute_btn.setIcon(icons.icon("volume_x" if m else "volume", 16, "#f59e0b" if m else "#e5e7f0"))
        self.mute_btn.setToolTip("Bật lại tiếng trình phát" if m else
                                 "Tắt tiếng trình phát (không đổi âm lượng của dự án)")

    def toggle_fullscreen(self) -> None:
        if self._full is not None:
            self._full.close()
            return
        f = self._full = FullscreenView(self)
        f.audio_only, f.image, f.text, f.paused = self.view.audio_only, self.view.image, self.view.text, self.view.paused
        f.closed.connect(self._full_closed)
        f.showFullScreen()
        f.activateWindow()
        f.setFocus()

    def _full_closed(self) -> None:
        f, self._full = self._full, None
        if f is not None:
            f.deleteLater()

    def _on_frame(self, img: QImage) -> None:
        self.view.set_image(img)
        if self._full is not None:
            self._full.set_image(img)

    def _on_message(self, text: str) -> None:
        # "Đang tính / chuẩn bị…" chỉ là trạng thái chờ → để vòng xoay lo; chỉ hiện chữ khi là thông báo thật
        busy_words = ("Đang tính", "Đang chuẩn bị…", "Đang tải hình")
        show = "" if any(text.startswith(w) for w in busy_words) else text
        self.view.set_text(show)
        if self._full is not None:
            self._full.set_text(show)

    def _quality_changed(self) -> None:
        key = self.quality.currentData()
        if self.settings is not None:
            self.settings.setValue("preview/quality2", key)
        self.player.set_quality(key)

    def _fps(self) -> float:
        sch = self.player.sch
        return float(sch.fps) if sch is not None else 30.0

    def _on_loaded(self, total: float) -> None:
        self.slider.set_total(total)
        tl = self.player.tl
        self.slider.set_marks([it.start for it in tl.music_items[1:]] if tl is not None and total else [])
        self.tc_total.setText(" / " + self._tc(total))
        if tl is not None and total:
            if self.player.sch is not None:
                self.info.setText(f"{tl.width}×{tl.height} · {float(tl.fps):g} fps")
            else:
                self.info.setText("Chỉ nhạc")
        else:
            self.info.setText("")

    def _on_pos(self, t: float) -> None:
        self.shown_pos = t
        self.tc.setText(self._tc(t))
        self.slider.set_position(t)
        if self._full is not None:
            self._full.update()
        self.positionChanged.emit(t)

    def _on_state(self, s: str) -> None:
        playing = s in ("playing", "loading", "buffering")
        self.play_btn.setIcon(icons.icon("pause" if playing else "play", 20, "#ffffff"))
        self.play_btn.setToolTip("Dừng (Space)" if playing else "Phát (Space)")
        on = s != "empty" or self.player.project is not None
        for b in (self.play_btn, self.back_btn, self.fwd_btn, self.home_btn, self.full_btn, self.mute_btn):
            b.setEnabled(on)
        busy = s in ("loading", "buffering")
        self.view.set_busy(busy)
        self.view.set_paused(not playing)
        if self._full is not None:
            self._full.set_busy(busy)
            self._full.set_paused(not playing)

    def is_playing(self) -> bool:
        return self.player.state in ("playing", "loading", "buffering")

    def shutdown(self) -> None:
        if self._full is not None:
            self._full.close()
        self.player.stop()
        self.player.cache.clear()


class PreviewWindow(QWidget):
    """Trình phát trong cửa sổ riêng (dùng cho hộp thoại Xuất hàng loạt)."""
    positionChanged = Signal(float)
    closed = Signal()

    def __init__(self, settings=None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.settings = settings
        self.setWindowTitle("Xem trước")
        self.setMinimumSize(560, 400)
        self.panel = PreviewPanel(settings, self)
        self.player = self.panel.player
        self.view = self.panel.view
        self.play_btn = self.panel.play_btn
        self.quality = self.panel.quality
        self.slider = self.panel.slider
        self.panel.positionChanged.connect(self.positionChanged)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.panel)
        self._space = SpaceToggle(self, lambda: self.panel)
        geo = settings.value("preview/geometry") if settings is not None else None
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(900, 600)

    def open_project(self, project, gains: dict[str, float] | None = None, title: str = "") -> None:
        self.setWindowTitle(f"Xem trước — {title or project.name}")
        self.panel.title.setText((title or project.name).upper())
        self.panel.open_project(project, gains)
        self.panel.view.setFocus()

    def closeEvent(self, e) -> None:  # noqa: N802
        if self.settings is not None:
            self.settings.setValue("preview/geometry", self.saveGeometry())
        self.panel.shutdown()
        self.closed.emit()
        super().closeEvent(e)
