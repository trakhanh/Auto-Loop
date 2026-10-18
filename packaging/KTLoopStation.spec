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
    hiddenimports=["PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSvg"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "pytest", "unittest", "pydoc", "setuptools", "pip",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation", "PySide6.QtPositioning",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    ],
    noarchive=False,
)
# bỏ các thư viện Qt bị plugin kéo theo nhưng app không dùng (PDF, QML/Quick, bàn phím ảo)
# (Qt6Network giữ lại: Qt6Multimedia — trình phát trong hộp thoại cắt đoạn — cần nó)
DROP = ("qt6pdf", "qpdf", "qt6qml", "qt6quick", "qt6virtualkeyboard", "qtvirtualkeyboard",
        "qopensslbackend", "qcertonlybackend")
a.binaries = [b for b in a.binaries if not any(k in Path(b[0]).name.lower() for k in DROP)]
a.datas = [d for d in a.datas if "translations" not in d[0].replace("\\", "/") or
           any(k in Path(d[0]).name for k in ("_vi", "_en"))]
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
