import threading
import time

import pytest

from loopstation.core import encoders, render


def test_parallel_keeps_order_and_runs_together():
    active, peak = [0], [0]
    lock = threading.Lock()

    def work(x):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return x * 10

    steps = []
    assert render._parallel(list(range(8)), work, 3, steps.append) == [x * 10 for x in range(8)]
    assert 2 <= peak[0] <= 3 and steps[0] == 0  # chạy song song, không quá 3 việc cùng lúc
    assert render._parallel([1, 2], lambda x: x + 1, 1) == [2, 3]


def test_parallel_raises_first_error():
    def work(x):
        if x == 2:
            raise ValueError("hỏng")
        return x

    with pytest.raises(ValueError):
        render._parallel(list(range(6)), work, 3)


def test_parallel_jobs_per_encoder():
    assert encoders.parallel_jobs("h264_nvenc") == 3 and encoders.parallel_jobs("hevc_amf") == 3
    assert encoders.parallel_jobs("h264_qsv") == 2 and encoders.parallel_jobs("libx264") in (1, 2)


def test_fast_presets_keep_slow_for_very_high():
    high = encoders.encoder_args("h264_nvenc", "high", 60)
    assert high[high.index("-preset") + 1] == "p4"
    very = encoders.encoder_args("h264_nvenc", "very_high", 60)
    assert very[very.index("-preset") + 1] == "p6"
    amd = encoders.encoder_args("h264_amf", "high", 60)
    assert amd[amd.index("-quality") + 1] == "balanced"


def test_moov_reserve_enough_for_long_video():
    # 3 giờ 60 fps: ~650 nghìn khung hình + ~506 nghìn khung âm thanh → cần ~25 MB, giữ dư
    need = (3 * 3600 * 60 + 3 * 3600 * 48000 / 1024) * 24
    assert render.moov_reserve(3 * 3600, 60) > need


def test_gpu_jobs_remembers_reduced_sessions():
    render._GPU_JOBS.clear()
    assert render.gpu_jobs("h264_nvenc") == 3
    render._GPU_JOBS["h264_nvenc"] = 2  # card từ chối 3 phiên → lần sau dùng 2
    assert render.gpu_jobs("h264_nvenc") == 2 and render.gpu_jobs("h264_amf") == 3
    render._GPU_JOBS.clear()
