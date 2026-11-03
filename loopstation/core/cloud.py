"""Thư mục đồng bộ đám mây (Google Drive for desktop, OneDrive). Ổ G: của Google Drive là ổ ảo: file ghi vào được giữ
tạm trên ổ C: rồi tải dần lên mạng — ghi thẳng video dài vào đó dễ lỗi ở bước cuối (Drive giữ file đang tải lên nên
không đổi tên / ghi lại phần đầu file được, mạng chập chờn, ổ C: đầy mà app không biết). → Lúc xuất: ghi ra máy trước
rồi chép sang (render.py); lúc chọn thư mục: báo cho người dùng biết (export_tab.py)."""
from __future__ import annotations

import ctypes
import os
from functools import lru_cache

# thư mục gốc của ổ Google Drive (tiếng Anh / tiếng Việt), và tên thư mục khi Drive chạy kiểu "sao chép" (mirror)
_GDRIVE_TOP = {"my drive", "shared drives", "other computers", "drive của tôi", "bộ nhớ dùng chung",
               "ổ đĩa dùng chung", "máy tính khác"}
_GDRIVE_ANY = {"my drive", "drive của tôi", "google drive"}


@lru_cache(maxsize=64)
def _volume_label(root: str) -> str:
    if os.name != "nt":
        return ""
    name = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), name, 261, None, None, None, fs, 261)
    except (AttributeError, OSError):
        return ""
    return name.value if ok else ""


def provider(path: str) -> str:
    """"Google Drive" / "OneDrive" nếu `path` nằm trong thư mục đồng bộ đám mây, không thì chuỗi rỗng."""
    if not path:
        return ""
    p = os.path.normcase(os.path.abspath(path))
    for var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        od = os.environ.get(var)
        if od and (p + os.sep).startswith(os.path.normcase(os.path.abspath(od)).rstrip(os.sep) + os.sep):
            return "OneDrive"
    drive, rest = os.path.splitdrive(p)
    parts = [x.strip().lower() for x in rest.replace("/", os.sep).split(os.sep) if x.strip()]
    if (parts and parts[0] in _GDRIVE_TOP) or any(x in _GDRIVE_ANY for x in parts):
        return "Google Drive"
    if drive and "google drive" in _volume_label(drive + os.sep).lower():
        return "Google Drive"
    return ""
