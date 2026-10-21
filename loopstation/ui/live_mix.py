"""Phát bản nghe thử bằng cách tự hoà các kênh (nhạc, tiếng gốc, từng lớp tiếng nền) ngay lúc phát:
kéo thanh âm lượng là nghe khác ngay (trễ ~0,15 giây), không phải trộn lại bằng FFmpeg, không ngắt tiếng.

Hoà bằng audioop (có sẵn trong Python, chạy bằng C nên rất nhẹ). Cuối chuỗi có bộ giới hạn đỉnh giống lúc xuất
(alimiter -1 dB) để nghe đúng độ to thật."""
from __future__ import annotations

import warnings
import wave

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

from PySide6.QtCore import QIODevice, QObject, QTimer, Signal

RATE, CH, WIDTH = 48000, 2, 2
FRAME = CH * WIDTH
LIMIT = int(0.891 * 32767)  # giống alimiter=limit=0.891 lúc xuất
CHUNK = 4800  # 25 ms mỗi lần hoà → âm lượng đổi mượt, không "lạo xạo"
BUFFER_MS = 150


def read_pcm(path) -> bytes:
    with wave.open(str(path), "rb") as f:
        if (f.getframerate(), f.getnchannels(), f.getsampwidth()) != (RATE, CH, WIDTH):
            raise ValueError("định dạng WAV không đúng")
        return f.readframes(f.getnframes())


class Mixer:
    """Hoà các kênh PCM s16 stereo theo hệ số âm lượng (1.0 = 100%, tối đa 2.0)."""

    def __init__(self, stems: dict[str, bytes], gains: dict[str, float]):
        self.stems = stems
        self.gains = dict(gains)
        self.length = min((len(b) for b in stems.values()), default=0) // FRAME * FRAME
        self.pos = 0
        self._lim = 1.0

    def mix(self, n: int) -> bytes:
        n = min(n, self.length - self.pos) // FRAME * FRAME
        if n <= 0:
            return b""
        acc = None
        for key, data in self.stems.items():
            g = self.gains.get(key, 1.0) * 0.5  # hoà ở nửa mức để cộng nhiều kênh không bị tràn
            if g <= 0:
                continue
            part = audioop.mul(data[self.pos:self.pos + n], WIDTH, g)
            acc = part if acc is None else audioop.add(acc, part, WIDTH)
        self.pos += n
        if acc is None:
            return bytes(n)
        peak = audioop.max(acc, WIDTH) * 2
        want = min(1.0, LIMIT / peak) if peak else 1.0
        # giới hạn đỉnh: hạ ngay khi to quá, nhả từ từ (giống alimiter)
        self._lim = want if want < self._lim else min(want, self._lim + 0.02)
        return audioop.mul(acc, WIDTH, 2 * self._lim)

    def mix_all(self) -> bytes:
        self.pos, self._lim = 0, 1.0
        out = []
        while True:
            part = self.mix(CHUNK)
            if not part:
                return b"".join(out)
            out.append(part)


_RETIRED: list = []  # nguồn tiếng đã ngừng dùng, giữ lại tới khi bộ phát âm thanh thật sự dừng


def retire(sink, dev) -> None:
    """Dừng bộ phát âm thanh rồi mới đóng nguồn tiếng. Đóng nguồn ngay (khi Qt — bản dùng FFmpeg — còn đọc thêm
    một nhịp) làm hiện cảnh báo “QIODevice::read: device not open / pullFromQIODeviceToRingbuffer…”."""
    if dev is not None:
        dev.owner = None  # từ giờ chỉ trả "không còn dữ liệu"
    if sink is None:
        if dev is not None:
            dev.close()
        return
    sink.stop()
    if dev is not None:
        _RETIRED.append(dev)

        def done(*_args, d=dev):
            d.close()
            if d in _RETIRED:
                _RETIRED.remove(d)

        sink.destroyed.connect(done)
    sink.deleteLater()


class _Device(QIODevice):
    def __init__(self, owner: "LivePlayer"):
        super().__init__()
        self.owner = owner

    def readData(self, maxlen):  # noqa: N802
        return self.owner._read(maxlen) if self.owner is not None else b""

    def writeData(self, data):  # noqa: N802
        return 0

    def bytesAvailable(self) -> int:  # noqa: N802
        m = self.owner.mixer if self.owner is not None else None
        return (m.length - m.pos if m else 0) + super().bytesAvailable()

    def isSequential(self) -> bool:  # noqa: N802
        return True


class LivePlayer(QObject):
    """Phát trực tiếp qua QAudioSink. `available()` = False (máy không hỗ trợ) thì bảng trộn dùng cách cũ."""
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mixer: Mixer | None = None
        self._sink = None
        self._dev = None
        self._fmt = None
        # kiểm tra đã phát hết chưa (tín hiệu stateChanged của QAudioSink lỗi kiểu dữ liệu trên PySide6 6.11)
        self._watch = QTimer(self)
        self._watch.setInterval(100)
        self._watch.timeout.connect(self._check_end)

    def available(self) -> bool:
        try:
            from PySide6.QtMultimedia import QAudioFormat, QMediaDevices
        except ImportError:
            return False
        fmt = QAudioFormat()
        fmt.setSampleRate(RATE)
        fmt.setChannelCount(CH)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        dev = QMediaDevices.defaultAudioOutput()
        if dev.isNull() or not dev.isFormatSupported(fmt):
            return False
        self._fmt = fmt
        return True

    def play(self, stems: dict[str, bytes], gains: dict[str, float]) -> None:
        from PySide6.QtMultimedia import QAudioSink, QMediaDevices
        self.stop()
        self.mixer = Mixer(stems, gains)
        self._sink = QAudioSink(QMediaDevices.defaultAudioOutput(), self._fmt, self)
        self._sink.setBufferSize(RATE * FRAME * BUFFER_MS // 1000)
        self._dev = _Device(self)
        self._dev.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink.start(self._dev)
        self._watch.start()

    def set_gain(self, key: str, gain: float) -> None:
        if self.mixer is not None:
            self.mixer.gains[key] = gain

    def is_playing(self) -> bool:
        return self._sink is not None

    def position(self) -> float:
        """Giây đã phát ra loa (tính từ đầu bản nghe thử)."""
        if self._sink is None:
            return 0.0
        return self._sink.processedUSecs() / 1e6

    def _read(self, maxlen: int) -> bytes:
        if self.mixer is None:
            return b""
        return self.mixer.mix(min(maxlen, CHUNK))

    def _check_end(self) -> None:
        m = self.mixer
        if self._sink is None or m is None or m.pos < m.length:
            return
        if self.position() >= m.length / (RATE * FRAME) - 0.03:  # phần còn trong bộ đệm đã ra loa hết
            self.stop()
            self.finished.emit()

    def stop(self) -> None:
        self._watch.stop()
        sink, self._sink = self._sink, None
        dev, self._dev = self._dev, None
        retire(sink, dev)
