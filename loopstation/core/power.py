"""Giữ máy không tự ngủ trong lúc xuất (Windows), để hàng đợi chạy qua đêm không bị dừng giữa chừng.

Chỉ chặn máy NGỦ; màn hình vẫn được tắt theo cài đặt Windows như bình thường. Xuất xong (hoặc huỷ) thì trả lại.
"""
from __future__ import annotations

import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040

_active = False


def keep_awake(on: bool) -> bool:
    """Bật / tắt chế độ giữ máy thức. Gọi từ luồng giao diện (Windows gắn trạng thái này với luồng gọi)."""
    global _active
    if sys.platform != "win32" or on == _active:
        return False
    try:
        import ctypes
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED if on else 0)
        ok = bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
        if not ok and on:  # máy không hỗ trợ "away mode" → chỉ giữ hệ thống thức
            ok = bool(ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
    except Exception:  # noqa: BLE001
        return False
    if ok:
        _active = on
    return ok


def is_active() -> bool:
    return _active
