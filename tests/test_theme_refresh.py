"""Đổi bộ màu lúc chạy: phần chỉ đọc màu một lần lúc khởi tạo (nền VideoView, biểu tượng) phải đổi theo."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from loopstation.ui import icons, theme
from loopstation.ui.preview_player import VideoView


def test_palette_switch_refreshes_bg_and_icon():
    app = QApplication.instance() or QApplication([])
    start = theme.PALETTE
    try:
        theme.apply(app, theme.FONT_PT, "neon")
        view = VideoView(bg="accent")
        lbl = QLabel()
        icons.bind(lbl, "chip", 14, "accent_text")
        before_bg, before_px = view.bg.name(), lbl.pixmap().toImage()
        assert before_bg == theme.T["accent"]
        theme.apply(app, theme.FONT_PT, "ocean")
        assert view.bg.name() == theme.T["accent"] != before_bg
        assert lbl.pixmap().toImage() != before_px
    finally:
        theme.apply(app, theme.FONT_PT, start)
