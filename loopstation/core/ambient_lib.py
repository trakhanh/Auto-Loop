"""Thư viện tiếng nền dựng sẵn: app tự tổng hợp bằng FFmpeg (không cần file, không tải mạng).

Lưu trong dự án dạng "builtin:<khoá>" (ví dụ builtin:rain_heavy). Lần đầu dùng app tạo một đoạn 2 phút âm thanh nổi,
cân âm lượng về cùng một mức rồi lưu bộ nhớ đệm; mở dự án trên máy khác thì app tự tạo lại.
Khi phát, đoạn này được hoà mượt chỗ lặp (audio_build.seamless_loop) nên lặp hàng giờ không nghe khựng.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import ffmpeg_tools as ft

PREFIX = "builtin:"
VERSION = "1"  # đổi công thức âm → tăng để tạo lại
DURATION = 120.0
TARGET_LUFS = -24.0  # mức chung của mọi âm (rồi chỉnh % từng lớp trong app)
SR = 48000


def _n(color: str, amp: float, seed: int, density: float | None = None) -> str:
    d = f":density={density}" if density is not None else ""
    return f"anoisesrc=r={SR}:c={color}:a={amp}:s={seed}{d}"


def _vol(expr: str) -> str:
    return f"volume='{expr}':eval=frame"


# Mỗi công thức tạo một kênh (mono) từ hạt giống `s`; trái / phải dùng hạt giống khác nhau → âm thanh nổi rộng.
def _white(s: int, ph: float) -> str:
    return f"{_n('white', 0.5, s)},highpass=f=30,lowpass=f=16000"


def _pink(s: int, ph: float) -> str:
    return f"{_n('pink', 0.6, s)},highpass=f=25"


def _brown(s: int, ph: float) -> str:
    return f"{_n('brown', 0.8, s)},highpass=f=25"


def _rain_heavy(s: int, ph: float) -> str:
    hiss = f"{_n('pink', 0.6, s)},highpass=f=300,lowpass=f=9000"
    drops = f"{_n('velvet', 1.0, s + 11, 0.004)},bandpass=f=3500:width_type=o:w=1.6,volume=7"
    low = f"{_n('brown', 0.5, s + 23)},lowpass=f=180,volume=0.6"
    return f"{hiss}[h{s}];{drops}[d{s}];{low}[l{s}];[h{s}][d{s}][l{s}]amix=inputs=3:normalize=0"


def _rain_light(s: int, ph: float) -> str:
    hiss = f"{_n('pink', 0.22, s)},highpass=f=900,lowpass=f=8000"
    drops = f"{_n('velvet', 1.0, s + 11, 0.0015)},bandpass=f=4500:width_type=o:w=1.2,volume=8"
    plinks = f"{_n('velvet', 1.0, s + 31, 0.0003)},bandpass=f=1800:width_type=o:w=0.7,volume=14"
    return f"{hiss}[h{s}];{drops}[d{s}];{plinks}[p{s}];[h{s}][d{s}][p{s}]amix=inputs=3:normalize=0"


def _waves(s: int, ph: float) -> str:
    swell = f"0.18+0.55*pow(sin(PI*t/8.5+{ph}),4)+0.35*pow(sin(PI*t/13.3+{ph}+1.1),4)"
    foam = f"0.05+0.6*pow(sin(PI*t/8.5+{ph}-0.35),6)+0.3*pow(sin(PI*t/13.3+{ph}+0.8),6)"
    body = f"{_n('brown', 0.9, s)},lowpass=f=900,{_vol(swell)}"
    top = f"{_n('pink', 0.5, s + 7)},highpass=f=1800,lowpass=f=9000,{_vol(foam)}"
    return f"{body}[b{s}];{top}[f{s}];[b{s}][f{s}]amix=inputs=2:normalize=0"


def _wind(s: int, ph: float) -> str:
    gust = f"0.25+0.75*(0.5+0.5*sin(2*PI*t/11+{ph}))*(0.65+0.35*sin(2*PI*t/4.3+{ph}+1))"
    whistle = f"0.1+0.5*pow(0.5+0.5*sin(2*PI*t/17+{ph}+2),3)"
    body = f"{_n('pink', 0.7, s)},lowpass=f=700,highpass=f=40,{_vol(gust)}"
    tone = f"{_n('pink', 0.7, s + 9)},bandpass=f=850:width_type=o:w=0.35,volume=3,{_vol(whistle)}"
    return f"{body}[w{s}];{tone}[t{s}];[w{s}][t{s}]amix=inputs=2:normalize=0"


def _fire(s: int, ph: float) -> str:
    roar = f"{_n('brown', 0.6, s)},lowpass=f=380,highpass=f=35,{_vol(f'0.8+0.2*sin(2*PI*t/6.1+{ph})')}"
    hiss = f"{_n('pink', 0.12, s + 5)},highpass=f=1200,lowpass=f=4500"
    crackle = f"{_n('velvet', 1.0, s + 13, 0.0012)},highpass=f=1300,lowpass=f=7000,volume=5"
    pops = f"{_n('velvet', 1.0, s + 29, 0.00008)},bandpass=f=2400:width_type=o:w=1.2,volume=16"
    return (f"{roar}[r{s}];{hiss}[s{s}];{crackle}[c{s}];{pops}[p{s}];"
            f"[r{s}][s{s}][c{s}][p{s}]amix=inputs=4:normalize=0")


@dataclass(frozen=True)
class Sound:
    key: str
    name: str
    desc: str
    channel: Callable[[int, float], str]


SOUNDS: dict[str, Sound] = {s.key: s for s in [
    Sound("rain_heavy", "Mưa rào", "Mưa nặng hạt đều đều, có tiếng ầm nhẹ phía dưới — ngủ, học tập.", _rain_heavy),
    Sound("rain_light", "Mưa nhẹ hiên nhà", "Mưa lâm râm, giọt nước lách tách rơi trên mái hiên.", _rain_light),
    Sound("waves", "Sóng biển", "Sóng vỗ bờ lên xuống chậm, có tiếng bọt sóng.", _waves),
    Sound("wind", "Gió thổi", "Gió từng cơn mạnh yếu, có tiếng rít nhẹ.", _wind),
    Sound("fire", "Lửa củi", "Lửa cháy âm ỉ, củi nổ lách tách — ấm cúng.", _fire),
    Sound("white", "White noise (ồn trắng)", "Đều mọi tần số, che tiếng ồn xung quanh tốt nhất.", _white),
    Sound("pink", "Pink noise (ồn hồng)", "Dịu hơn ồn trắng, giống tiếng mưa xa / thác nước.", _pink),
    Sound("brown", "Brown noise (ồn nâu)", "Trầm ấm, giống tiếng thác lớn / máy bay — dễ ngủ.", _brown),
]}


def is_builtin(path: str) -> bool:
    return bool(path) and path.startswith(PREFIX)


def key_of(path: str) -> str:
    return path[len(PREFIX):] if is_builtin(path) else ""


def display_name(path: str) -> str:
    s = SOUNDS.get(key_of(path))
    return f"{s.name} (có sẵn)" if s else Path(path).name


def _out(key: str) -> Path:
    return ft.cache_dir("ambientlib") / f"{key}_v{VERSION}.flac"


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def is_ready(key: str) -> bool:
    out = _out(key)
    return out.is_file() and out.stat().st_size > 0


def generate(key: str, runner: ft.Runner | None = None) -> str:
    """Tạo (nếu chưa có) và trả về đường dẫn file FLAC của âm `key`. Hai luồng cùng tạo một âm thì luồng sau chờ."""
    out = _out(key)
    if out.is_file() and out.stat().st_size > 0:
        return str(out)
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        if out.is_file() and out.stat().st_size > 0:
            return str(out)
        return _generate(key, out, runner)


def _generate(key: str, out: Path, runner: ft.Runner | None) -> str:
    sound = SOUNDS[key]
    runner = runner or ft.Runner()
    graph = (f"{sound.channel(101, 0.0)}[L];{sound.channel(202, 0.9)}[R];"
             f"[L][R]join=inputs=2:channel_layout=stereo,atrim=duration={DURATION}")
    tag = f"{os.getpid()}-{threading.get_ident()}"
    raw = out.with_name(f"{out.stem}.{tag}.tmp.wav")
    tmp = out.with_name(f"{out.stem}.{tag}.tmp.flac")
    try:
        runner.ffmpeg(["-v", "error", "-filter_complex", graph + "[o]", "-map", "[o]", "-c:a", "pcm_s24le",
                       "-ar", str(SR), str(raw)])
        from .audio_build import measure_loudness
        lufs = measure_loudness(runner, str(raw))
        gain = max(-30.0, min(30.0, TARGET_LUFS - lufs)) if lufs is not None else 0.0
        runner.ffmpeg(["-v", "error", "-i", str(raw), "-af",
                       f"volume={gain:.2f}dB,alimiter=limit=0.89:level=0,afade=t=in:d=0.02",
                       "-c:a", "flac", "-sample_fmt", "s16", str(tmp)])
        os.replace(tmp, out)
    finally:
        for f in (raw, tmp):
            try:
                f.unlink()
            except OSError:
                pass
    return str(out)


on_ready: Callable[[], None] | None = None  # giao diện gắn vào: tạo xong một âm → tính lại
_pending: set[str] = set()


def ensure_async(key: str) -> bool:
    """True nếu âm đã sẵn sàng. Chưa có thì bắt đầu tạo ở luồng nền (không làm đơ giao diện) và trả về False."""
    if is_ready(key):
        return True
    with _locks_guard:
        if key in _pending:
            return False
        _pending.add(key)

    def work() -> None:
        try:
            generate(key)
        except Exception:  # noqa: BLE001 — lỗi sẽ hiện lại khi tính lần sau (tạo đồng bộ lúc xuất)
            pass
        finally:
            with _locks_guard:
                _pending.discard(key)
            cb = on_ready
            if cb is not None:
                try:
                    cb()
                except Exception:  # noqa: BLE001
                    pass

    threading.Thread(target=work, daemon=True).start()
    return False


def resolve(path: str, runner: ft.Runner | None = None) -> str:
    """Đường dẫn thật để đọc: âm dựng sẵn → file đã tạo (tự tạo nếu chưa có); file thường giữ nguyên."""
    key = key_of(path)
    if key in SOUNDS:
        return generate(key, runner)
    return path
