"""Logo nền tảng (YouTube, TikTok, Bilibili, Facebook, X, Instagram, Douyin) cho trang Tải video."""
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


def test_every_platform_has_a_logo(app):
    from loopstation.ui import brand
    for name in ("YouTube", "TikTok", "Bilibili", "Facebook", "X", "Instagram", "Douyin"):
        pm = brand.pixmap(name, 24)
        assert not pm.isNull() and pm.width() >= 24, name
        img = pm.toImage()
        assert any(img.pixelColor(x, y).alpha() > 0 for x in range(0, 24, 2) for y in range(0, 24, 2)), name
    assert not brand.pixmap("Vimeo", 16).isNull()  # nền tảng khác: biểu tượng chung
    assert brand.SHOWN == ("YouTube", "TikTok", "Douyin", "Bilibili", "Facebook", "X", "Instagram")


def test_logo_colors_come_from_theme(app):
    from loopstation.ui import brand, theme
    assert set(theme.BRAND) >= {"youtube", "tiktok_a", "tiktok_b", "bilibili", "facebook", "x", "instagram", "white"}
    assert theme.BRAND["youtube"] in brand.svg("YouTube")
