from PySide6.QtGui import QColor, QImage

from loopstation.ui.trim_dialog import similarity


def _img(color: str, w: int = 320, h: int = 180) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


def test_similarity_scale():
    assert similarity(_img("#808080"), _img("#808080")) > 99.9
    assert similarity(_img("#000000"), _img("#ffffff")) == 0.0
    near = similarity(_img("#808080"), _img("#8a8a8a"))  # lệch rất nhẹ (~4%)
    assert 80 < near < 99
    assert similarity(QImage(), _img("#000000")) == 0.0
