"""Logo nền tảng (vẽ lại dạng đơn giản bằng SVG) cho trang Tải video: dòng "Hỗ trợ", cột Nền tảng, màn hình trống.
Màu lấy từ theme.brand_colors() (không ghi mã màu ở đây; chế độ Sáng đổi logo X sang màu đậm)."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import icons, theme

SHOWN = ("YouTube", "TikTok", "Douyin", "Bilibili", "Facebook", "X", "Instagram")
_NOTE = "M13 4v10.2a3.2 3.2 0 1 1-3.2-3.2"
_SVG = {
    "YouTube": ('<rect x="1.5" y="5" width="21" height="14" rx="4.5" fill="{youtube}"/>'
                '<path d="M10 8.8v6.4l5.6-3.2z" fill="{white}"/>'),
    "TikTok": ('<g fill="none" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">'
               f'<path d="{_NOTE}M13 4c.6 2.6 2.6 4.3 5.2 4.4" stroke="{{tiktok_a}}" transform="translate(-1 -.8)"/>'
               f'<path d="{_NOTE}M13 4c.6 2.6 2.6 4.3 5.2 4.4" stroke="{{tiktok_b}}" transform="translate(1 .8)"/>'
               f'<path d="{_NOTE}M13 4c.6 2.6 2.6 4.3 5.2 4.4" stroke="{{white}}"/></g>'),
    "Bilibili": ('<g fill="none" stroke="{bilibili}" stroke-width="2" stroke-linecap="round">'
                 '<rect x="2.5" y="6.5" width="19" height="13.5" rx="3.5"/><path d="M8 3l3 3.2M16 3l-3 3.2"/>'
                 '<path d="M8.5 11.5v2M15.5 11.5v2"/></g>'),
    "Facebook": ('<circle cx="12" cy="12" r="10.5" fill="{facebook}"/>'
                 '<path d="M13.3 22.4v-7.6h2.5l.4-2.9h-2.9v-1.9c0-.8.3-1.4 1.5-1.4h1.5V6c-.3 0-1.2-.1-2.2-.1-2.2 0-3.6 '
                 '1.3-3.6 3.7v2.3H8v2.9h2.5v7.6z" fill="{white}"/>'),
    "X": ('<path d="M4 4h4.6l11.4 16h-4.6z" fill="{x}"/>'
          '<path d="M19.4 4L4.6 20" stroke="{x}" stroke-width="2" stroke-linecap="round"/>'),
    "Instagram": ('<defs><linearGradient id="g" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="{instagram_b}"/>'
                  '<stop offset="1" stop-color="{instagram}"/></linearGradient></defs>'
                  '<g fill="none" stroke="url(#g)" stroke-width="2.2"><rect x="3" y="3" width="18" height="18" rx="5.5"/>'
                  '<circle cx="12" cy="12" r="4.2"/></g><circle cx="17.2" cy="6.8" r="1.3" fill="{instagram}"/>'),
    "_other": ('<g fill="none" stroke="{other}" stroke-width="1.8"><circle cx="12" cy="12" r="9"/>'
               '<path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/></g>'),
}
_SVG["Douyin"] = _SVG["TikTok"]
_cache: dict[tuple[str, int, float], QPixmap] = {}


def svg(platform: str) -> str:
    body = _SVG.get(platform, _SVG["_other"]).format(**theme.brand_colors())
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'


def pixmap(platform: str, size: int, dpr: float = 2.0) -> QPixmap:
    key = (platform, size, dpr, theme.LIGHT)
    if key not in _cache:
        px = int(size * dpr)
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        QSvgRenderer(QByteArray(svg(platform).encode())).render(p, QRectF(0, 0, px, px))
        p.end()
        pm.setDevicePixelRatio(dpr)
        _cache[key] = icons.track_pixmap(pm, lambda: pixmap(platform, size, dpr))
    return _cache[key]


_icons: dict[tuple[str, int, bool], QIcon] = {}


def icon(platform: str, size: int = 16) -> QIcon:
    key = (platform, size, theme.LIGHT)
    if key not in _icons:
        _icons[key] = icons.track_icon(QIcon(pixmap(platform, size)), lambda: icon(platform, size))
    return _icons[key]
