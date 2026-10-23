"""Logo và icon của KT Loop Station (vẽ từ assets/logo.svg)."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def assets_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):  # bản đóng gói PyInstaller
        return Path(sys._MEIPASS) / "loopstation" / "ui" / "assets"
    return Path(__file__).resolve().parent / "assets"


def logo_svg() -> str:
    return str(assets_dir() / "logo.svg")


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    QSvgRenderer(logo_svg()).render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def pixmap(size: int, ratio: float = 1.0) -> QPixmap:
    pm = QPixmap.fromImage(render(int(size * ratio)))
    pm.setDevicePixelRatio(ratio)
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for s in ICON_SIZES:
        icon.addPixmap(QPixmap.fromImage(render(s)))
    return icon


def _png_bytes(img: QImage) -> bytes:
    buf = QByteArray()
    dev = QBuffer(buf)
    dev.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(dev, "PNG")
    return bytes(buf.data())


def write_ico(path: str, sizes=ICON_SIZES) -> None:
    """File .ico nhiều kích thước (mỗi ảnh lưu dạng PNG — Windows Vista trở lên đều đọc được)."""
    blobs = [(s, _png_bytes(render(s))) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries, data = b"", b""
    for s, png in blobs:
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    Path(path).write_bytes(header + entries + data)


def set_windows_app_id() -> None:
    """Để thanh tác vụ Windows hiện icon của app thay vì icon Python, đồng thời tắt QuickEdit trên cửa sổ console
    để bấm chuột vào PowerShell/CMD không làm treo tiến trình giao diện."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KhanhTra.KTLoopStation")
            k32 = ctypes.windll.kernel32
            h_in = k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
            mode = ctypes.c_uint32()
            if h_in and k32.GetConsoleMode(h_in, ctypes.byref(mode)):
                # Tắt ENABLE_QUICK_EDIT_MODE (0x0040), giữ ENABLE_EXTENDED_FLAGS (0x0080)
                k32.SetConsoleMode(h_in, (mode.value & ~0x0040) | 0x0080)
        except Exception:  # noqa: BLE001
            pass


def apply_window_frame(widget) -> None:
    """Đồng bộ thanh tiêu đề và viền cửa sổ Windows 10/11 sang tông tối, ánh màu chủ đạo đang chọn."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1)
        # DWMWA_USE_IMMERSIVE_DARK_MODE (20, dự phòng 19 cho Windows 10 cũ)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
        dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(dark), ctypes.sizeof(dark))
        # DWMWA_WINDOW_CORNER_PREFERENCE (33) = DWMWCP_ROUND (2)
        corner = ctypes.c_int(2)
        dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
        # viền + thanh tiêu đề theo bộ màu đang chọn (COLORREF = 0x00BBGGRR)
        from . import theme

        def colorref(hex_color: str) -> ctypes.c_uint32:
            c = theme.QColor(hex_color)
            return ctypes.c_uint32(c.red() | (c.green() << 8) | (c.blue() << 16))

        border_col = colorref(theme.mix(theme.T["line_strong"], theme.T["accent"], 0.35))
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border_col), ctypes.sizeof(border_col))
        cap_col = colorref(theme.mix(theme.T["bg"], theme.T["accent"], 0.06))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cap_col), ctypes.sizeof(cap_col))
        # DWMWA_TEXT_COLOR (36) = COLORREF 0x00BBGGRR
        txt_col = colorref(theme.T["text"])
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(txt_col), ctypes.sizeof(txt_col))
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    # python -m loopstation.ui.branding  → xuất icon.ico + logo.png để đóng gói / tài liệu
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication(sys.argv)
    out = assets_dir()
    write_ico(str(out / "icon.ico"))
    render(512).save(str(out / "logo-512.png"))
    print("Đã xuất:", out / "icon.ico", out / "logo-512.png")
