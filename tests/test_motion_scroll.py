"""2.0.3 — lỗi "Internal C++ object (PySide6.QtWidgets.QScrollBar) already deleted" (hộp "Có lỗi bất ngờ"): hoạt ảnh
cuộn mượt vẫn chạy sau khi vùng cuộn bị xoá. Giờ bước cuộn tự dừng khi thanh cuộn đã mất."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_scroll_step_after_bar_deleted(app):
    import shiboken6
    from PySide6.QtCore import QVariantAnimation
    from PySide6.QtWidgets import QScrollBar
    from loopstation.ui import motion
    bar = QScrollBar()
    bar.setRange(0, 100)
    anim = QVariantAnimation(app)
    anim.setDuration(10_000)
    anim.setStartValue(0)
    anim.setEndValue(100)
    anim.start()
    motion._scroll_step(bar, anim, 40)
    assert bar.value() == 40
    shiboken6.delete(bar)  # vùng cuộn bị xoá giữa lúc đang cuộn
    motion._scroll_step(bar, anim, 60)  # trước đây: RuntimeError … already deleted
    assert anim.state() == QVariantAnimation.State.Stopped
