"""Dựng các kênh nghe thử (nhạc / tiếng gốc / tiếng nền) ở luồng nền rồi trả về luồng giao diện."""
from __future__ import annotations

import shutil
import threading

from PySide6.QtCore import QObject, Signal

from ..core import audio_preview
from ..core import ffmpeg_tools as ft


class StemsJob(QObject):
    """Mỗi lần start() huỷ lần trước. done(payload, lỗi, tag): payload = (kênh PCM, mốc bắt đầu) hoặc None."""
    done = Signal(object, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._runner: ft.Runner | None = None

    def start(self, project, start: float, tag=None, version: int = 0) -> None:
        self.cancel()
        runner = self._runner = ft.Runner()

        def work():
            from .live_mix import read_pcm
            try:
                st = audio_preview.render_stems(project, start, runner, version)
                try:
                    data = {k: read_pcm(f) for k, f in st.files.items()}
                finally:
                    shutil.rmtree(st.folder, ignore_errors=True)
            except ft.CancelledError:
                return
            except Exception as e:  # noqa: BLE001
                if not runner.cancelled:
                    self._emit(None, str(e), tag)
                return
            if not runner.cancelled:
                self._emit((data, st.start), "", tag)

        threading.Thread(target=work, daemon=True).start()

    def _emit(self, payload, err: str, tag) -> None:
        try:
            self.done.emit(payload, err, tag)
        except RuntimeError:  # hộp thoại đã đóng
            pass

    def cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()
            self._runner = None
