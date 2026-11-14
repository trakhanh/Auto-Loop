"""Chạy "Tạo bản lặp xuôi–ngược" cho một hoặc nhiều clip: hộp tiến trình có nút Huỷ, làm ở luồng nền."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, Qt, Signal
from PySide6.QtWidgets import QProgressDialog, QWidget

from ..core import boomerang, ffmpeg_tools
from ..core.probe import MediaInfo, probe


class _Bridge(QObject):
    step = Signal(float, str)
    done = Signal()


def job_key(path: str, trim_start: float, trim_end: float) -> tuple:
    return os.path.normcase(path), round(trim_start, 3), round(trim_end, 3)


def make_all(parent: QWidget, jobs: list[tuple[str, float, float]]):
    """`jobs`: [(đường dẫn, bỏ đầu, bỏ cuối)] → (kết quả [(job_key, file mới, MediaInfo)], lỗi [chữ], đã huỷ?)."""
    uniq = list({job_key(*j): j for j in jobs}.values())
    n = len(uniq)
    dlg = QProgressDialog("Đang tạo bản lặp xuôi–ngược…", "Huỷ", 0, 1000, parent)
    dlg.setWindowTitle("Lặp xuôi–ngược")
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.setMinimumWidth(460)
    runner = ffmpeg_tools.Runner()
    bridge = _Bridge()
    results: list[tuple[tuple, str, MediaInfo]] = []
    errors: list[str] = []
    loop = QEventLoop()

    def on_step(frac: float, text: str) -> None:
        dlg.setValue(int(frac * 1000))
        if text:
            dlg.setLabelText(text)

    bridge.step.connect(on_step)
    bridge.done.connect(loop.quit)
    dlg.canceled.connect(runner.cancel)

    def work() -> None:
        for i, (path, a, b) in enumerate(uniq):
            try:
                out = boomerang.output_path(path)
                bridge.step.emit(i / n, f"Đang tạo {i + 1}/{n}: {Path(path).name}\n→ {out.name} (lưu cạnh file gốc)")
                boomerang.make(runner, path, out, a, b, lambda f, i=i: bridge.step.emit((i + f) / n, ""))
                results.append((job_key(path, a, b), str(out), probe(str(out))))
            except ffmpeg_tools.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                errors.append(f"{Path(path).name}: {str(e).strip().splitlines()[-1] if str(e).strip() else e}"[:300])
        bridge.done.emit()

    threading.Thread(target=work, daemon=True).start()
    dlg.show()
    loop.exec()
    cancelled = runner.cancelled
    dlg.close()
    dlg.deleteLater()
    return results, errors, cancelled
