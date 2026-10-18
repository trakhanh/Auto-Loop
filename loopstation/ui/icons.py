"""Hệ thống biểu tượng vector riêng của KT Loop Station: nét mảnh + lớp màu nhạt (hai tông), đồng nhất toàn app."""
from __future__ import annotations

import re

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Các đường nét SVG chuẩn khung nhìn 24x24, stroke-width 2, bo tròn đầu nét
_PATHS: dict[str, str] = {
    "video": (
        '<rect x="2" y="4" width="15" height="16" rx="3"/>'
        '<polygon points="17 9 22 6 22 18 17 15"/>'
    ),
    "film": (
        '<rect x="2" y="3" width="20" height="18" rx="2.5"/>'
        '<line x1="7" y1="3" x2="7" y2="21"/><line x1="17" y1="3" x2="17" y2="21"/>'
        '<line x1="2" y1="12" x2="22" y2="12"/>'
        '<line x1="2" y1="7.5" x2="7" y2="7.5"/><line x1="2" y1="16.5" x2="7" y2="16.5"/>'
        '<line x1="17" y1="7.5" x2="22" y2="7.5"/><line x1="17" y1="16.5" x2="22" y2="16.5"/>'
    ),
    "music": (
        '<path d="M9 18V5l12-2v13"/>'
        '<circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>'
    ),
    "video_music": (
        '<rect x="2" y="5" width="11" height="12" rx="2"/>'
        '<path d="M16 17V6l6-1.5v11"/>'
        '<circle cx="14.5" cy="17" r="2"/><circle cx="20.5" cy="15.5" r="2"/>'
    ),
    "export": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="17 8 12 3 7 8"/>'
        '<line x1="12" y1="3" x2="12" y2="15"/>'
    ),
    "settings": (
        '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/>'
        '<line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/>'
        '<line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/>'
        '<line x1="1" y1="14" x2="7" y2="14"/>'
        '<line x1="9" y1="8" x2="15" y2="8"/>'
        '<line x1="17" y1="16" x2="23" y2="16"/>'
    ),
    "help": (
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
        '<line x1="12" y1="17" x2="12.01" y2="17"/>'
    ),
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "file_plus": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
        '<line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/>'
    ),
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    "save": (
        '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
        '<polyline points="17 21 17 13 7 13 7 21"/>'
        '<polyline points="7 3 7 8 15 8"/>'
    ),
    "save_as": (
        '<rect x="8" y="8" width="13" height="13" rx="2"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
    ),
    "trash": (
        '<polyline points="3 6 5 6 21 6"/>'
        '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6z"/>'
        '<path d="M10 11v6"/><path d="M14 11v6"/>'
        '<path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>'
    ),
    "up": '<polyline points="18 15 12 9 6 15"/>',
    "down": '<polyline points="6 9 12 15 18 9"/>',
    "arrow_right": '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="13 6 19 12 13 18"/>',
    "arrow_left": '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="11 18 5 12 11 6"/>',
    "shuffle": (
        '<polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/>'
        '<polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/>'
        '<line x1="4" y1="4" x2="9" y2="9"/>'
    ),
    "sort": (
        '<line x1="4" y1="6" x2="13" y2="6"/>'
        '<line x1="4" y1="12" x2="11" y2="12"/>'
        '<line x1="4" y1="18" x2="9" y2="18"/>'
        '<polyline points="15 15 18 18 21 15"/>'
        '<line x1="18" y1="6" x2="18" y2="18"/>'
    ),
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "play": '<polygon points="6 4 20 12 6 20 6 4"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
    "volume_x": '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/>'
                '<line x1="17" y1="9" x2="23" y2="15"/>',
    "mark_in": '<line x1="6" y1="4" x2="6" y2="20"/><polyline points="10 8 14 12 10 16"/><line x1="14" y1="12" x2="20" y2="12"/>',
    "mark_out": '<line x1="18" y1="4" x2="18" y2="20"/><polyline points="14 8 10 12 14 16"/><line x1="4" y1="12" x2="10" y2="12"/>',
    "repeat": '<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/>'
              '<polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>',
    "timeline": (
        '<rect x="3" y="4" width="18" height="6" rx="1.5"/>'
        '<rect x="3" y="14" width="12" height="6" rx="1.5"/>'
        '<line x1="18" y1="14" x2="18" y2="20"/>'
    ),
    "volume": (
        '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>'
        '<path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>'
        '<path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>'
    ),
    "image": (
        '<rect x="3" y="3" width="18" height="18" rx="2.5"/>'
        '<circle cx="8.5" cy="8.5" r="1.5"/>'
        '<polyline points="21 15 16 10 5 21"/>'
    ),
    "refresh": (
        '<polyline points="23 4 23 10 17 10"/>'
        '<polyline points="1 20 1 14 7 14"/>'
        '<path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>'
    ),
    "chip": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/>'
            '<path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>',
    "sliders": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "queue": (
        '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>'
        '<line x1="8" y1="18" x2="21" y2="18"/>'
        '<line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/>'
        '<line x1="3" y1="18" x2="3.01" y2="18"/>'
    ),
    "terminal": '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    "waves": (
        '<path d="M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/>'
        '<path d="M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/>'
        '<path d="M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/>'
    ),
    "pin": '<line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/>',
    "home": '<path d="M4 10.4 12 4l8 6.4V19.5a1.5 1.5 0 0 1-1.5 1.5H15v-6H9v6H5.5A1.5 1.5 0 0 1 4 19.5z"/>',
    "search": '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "undo": '<polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/>'
            '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "scissors": (
        '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/>'
        '<line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/>'
        '<line x1="8.12" y1="8.12" x2="12" y2="12"/>'
    ),
    "eye": (
        '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
}

# Phong cách "hai tông" riêng của KT Loop Station: nét mảnh + lớp màu nhạt tô trong các hình khép kín
# (khung, ô, hình tròn) — khác bộ icon nét đơn thường gặp.
STROKE = 1.75
TONE_OPACITY = 0.30
_CLOSED = re.compile(r"<(rect|circle|ellipse|polygon)\b[^>]*/>|<path\b[^>]*\bd=\"[^\"]*[zZ][^\"]*\"[^>]*/>")


def _tone_layer(body: str) -> str:
    """Chỉ các hình khép kín mới được tô (đường thẳng, mũi tên, nét hở giữ nguyên là nét)."""
    return "".join(m.group(0) for m in _CLOSED.finditer(body))


_ICON_CACHE: dict[tuple[str, str, int], QIcon] = {}
_PIX_CACHE: dict[tuple[str, str, int], QPixmap] = {}


def pixmap(name: str, size: int | str = 16, color: str | int = "#cbd5e1") -> QPixmap:
    if isinstance(size, str):
        size, color = (int(color) if isinstance(color, int) else 16), size
    sz = int(size)
    col = str(color)
    key = (name, col, sz)
    if key in _PIX_CACHE:
        return _PIX_CACHE[key]
    body = _PATHS.get(name, _PATHS["video"])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<g fill="{col}" fill-opacity="{TONE_OPACITY}" stroke="none">{_tone_layer(body)}</g>'
        f'<g fill="none" stroke="{col}" stroke-width="{STROKE}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</g></svg>'
    )
    img = QImage(sz * 2, sz * 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(p, QRectF(0, 0, sz * 2, sz * 2))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(2.0)
    _PIX_CACHE[key] = pm
    return pm


def icon(name: str, size: int | str = 16, color: str = "#cbd5e1", active_color: str = "#ffffff",
         disabled_color: str = "#475166") -> QIcon:
    if isinstance(size, str):
        color = size
        size = 16
    sz = int(size)
    key = (name, f"{color}|{active_color}|{disabled_color}", sz)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    ic = QIcon()
    ic.addPixmap(pixmap(name, sz, color), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(pixmap(name, sz, active_color), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(pixmap(name, sz, active_color), QIcon.Mode.Active, QIcon.State.Off)
    ic.addPixmap(pixmap(name, sz, disabled_color), QIcon.Mode.Disabled, QIcon.State.Off)
    _ICON_CACHE[key] = ic
    return ic


def btn(button, name: str, color: str = "#cbd5e1", size: int = 15):
    """Gắn icon vector cho QPushButton và trả về chính nút đó."""
    button.setIcon(icon(name, size=size, color=color))
    button.setIconSize(QSize(size, size))
    return button
