# -*- mode: python ; coding: utf-8 -*-
# Đóng gói KT Loop Station bằng PyInstaller (dạng thư mục: mở app nhanh, không phải giải nén mỗi lần chạy).
# Chạy qua packaging\build.py — script đó còn chép FFmpeg, bộ mẫu và gọi Inno Setup để tạo bộ cài.
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "loopstation" / "ui" / "assets"), "loopstation/ui/assets")],
    # QtWebEngine: trình duyệt trong app để tải Douyin (yt-dlp không tải được) — kéo theo Qml / Quick / WebChannel…
    hiddenimports=["PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSvg",
                   "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "pytest", "unittest", "pydoc", "setuptools", "pip",
        "yaml", "psutil", "charset_normalizer",
        "PySide6.QtWebEngineQuick", "PySide6.QtWebSockets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.Qt3DCore", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    ],
    noarchive=False,
)
# bỏ các thư viện Qt / OpenGL phần mềm / OpenSSL không dùng (Qt6Network dùng Schannel có sẵn của Windows)
# (Qt6Network giữ lại: Qt6Multimedia — trình phát trong hộp thoại cắt đoạn — cần nó)
# (Qt6Qml / Qt6Quick / Qt6QuickWidgets giữ lại: QtWebEngine — trình duyệt tải Douyin — cần chúng)
DROP = ("qt6pdf", "qpdf", "qt6virtualkeyboard", "qtvirtualkeyboard",
        "qopensslbackend", "qcertonlybackend", "opengl32sw", "libcrypto-3-x64", "libssl-3-x64")
a.binaries = [b for b in a.binaries if not any(k in Path(b[0]).name.lower() for k in DROP)]


def _keep_data(dest: str) -> bool:
    d = dest.replace("\\", "/")
    name = Path(d).name
    if name.endswith(".debug.pak"):  # bản gỡ lỗi của QtWebEngine (~100 MB) — không cần
        return False
    if "qtwebengine_locales" in d:  # chữ giao diện trình duyệt: chỉ tiếng Việt + tiếng Anh
        return name in ("vi.pak", "en-US.pak")
    return "translations" not in d or any(k in name for k in ("_vi", "_en"))


a.datas = [d for d in a.datas if _keep_data(d[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KTLoopStation",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "loopstation" / "ui" / "assets" / "icon.ico"),
    version=str(Path(SPECPATH) / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="KTLoopStation")
