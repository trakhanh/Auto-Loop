"""Xuất / nhập mẫu xếp clip và hồ sơ kênh ra một file (.ktls) — tạo một lần, gửi cả phòng dùng chung."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from .interleave_dialog import PRESET_KEY, save_table_presets, table_presets

PROFILE_KEY = "profiles/list"
EXT = ".ktls"
KINDS = {"table": "mẫu bảng clip", "interleave": "mẫu xen kẽ", "profiles": "hồ sơ kênh"}


def read_profiles(settings: QSettings) -> list[dict]:
    try:
        data = json.loads(settings.value(PROFILE_KEY, "[]") or "[]")
    except (TypeError, ValueError):
        return []
    return [p for p in data if isinstance(p, dict) and p.get("name")]


def write_profiles(settings: QSettings, profiles: list[dict]) -> None:
    settings.setValue(PROFILE_KEY, json.dumps(profiles, ensure_ascii=False))


def _interleave(settings: QSettings) -> list[dict]:
    try:
        data = json.loads(settings.value(PRESET_KEY, "[]") or "[]")
    except (TypeError, ValueError):
        return []
    return [p for p in data if isinstance(p, dict) and p.get("name")]


def export_file(parent: QWidget, settings: QSettings, what: tuple[str, ...] = ("table", "interleave", "profiles"),
                start: str = "") -> str:
    """Ghi mẫu / hồ sơ của máy này ra file .ktls. Trả về đường dẫn (rỗng nếu huỷ / không có gì để xuất)."""
    data = {"app": "KT Loop Station", "kind": "ktls-share", "version": 1}
    if "table" in what:
        data["table"] = [{"name": p["name"], "rows": p["rows"]} for p in table_presets(settings)]
    if "interleave" in what:
        data["interleave"] = _interleave(settings)
    if "profiles" in what:
        data["profiles"] = read_profiles(settings)
    counts = {k: len(data.get(k, [])) for k in KINDS}
    if not any(counts.values()):
        QMessageBox.information(parent, "Chưa có gì để xuất", "Máy này chưa có mẫu / hồ sơ nào do bạn tạo "
                                "(mẫu có sẵn của app thì máy nào cài cũng có).")
        return ""
    path, _ = QFileDialog.getSaveFileName(parent, "Xuất mẫu & hồ sơ ra file", os.path.join(start, "mau-KT-Loop-Station"
                                                                                           + EXT),
                                          f"Mẫu KT Loop Station (*{EXT})")
    if not path:
        return ""
    if not path.lower().endswith(EXT):
        path += EXT
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    parts = ", ".join(f"{n} {KINDS[k]}" for k, n in counts.items() if n)
    QMessageBox.information(parent, "Đã xuất", f"Đã lưu {parts} vào:\n{path}\n\nGửi file này cho máy khác → "
                            "Thư viện mẫu (hoặc Hồ sơ kênh) → Nhập từ file.")
    return path


def import_file(parent: QWidget, settings: QSettings, path: str = "") -> dict[str, int]:
    """Đọc file .ktls rồi gộp vào máy này. Trùng tên: hỏi một lần — ghi đè hay giữ cả hai (thêm “(nhập)”).
    Trả về số mục đã thêm theo loại."""
    if not path:
        path, _ = QFileDialog.getOpenFileName(parent, "Nhập mẫu & hồ sơ từ file", "", f"Mẫu KT Loop Station (*{EXT})")
        if not path:
            return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("kind") != "ktls-share":
            raise ValueError("không phải file mẫu của KT Loop Station")
    except (OSError, ValueError) as e:
        QMessageBox.warning(parent, "Không đọc được file", f"{path}\n\n{e}")
        return {}
    current = {"table": [{"name": p["name"], "rows": p["rows"]} for p in table_presets(settings)],
               "interleave": _interleave(settings), "profiles": read_profiles(settings)}
    incoming = {k: [p for p in (data.get(k) or []) if isinstance(p, dict) and p.get("name")] for k in KINDS}
    clashes = [p["name"] for k in KINDS for p in incoming[k] if any(c["name"] == p["name"] for c in current[k])]
    overwrite = False
    if clashes:
        box = QMessageBox(parent)
        box.setWindowTitle("Trùng tên")
        box.setText(f"{len(clashes)} mục đã có tên giống trên máy này: {', '.join(clashes[:5])}"
                    + ("…" if len(clashes) > 5 else ""))
        ow = box.addButton("Ghi đè bằng bản trong file", box.ButtonRole.AcceptRole)
        both = box.addButton("Giữ cả hai (thêm “(nhập)”)", box.ButtonRole.ActionRole)
        box.addButton("Huỷ", box.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() not in (ow, both):
            return {}
        overwrite = box.clickedButton() is ow
    added: dict[str, int] = {}
    for k in KINDS:
        merged = list(current[k])
        for p in incoming[k]:
            names = {c["name"] for c in merged}
            if p["name"] in names:
                if overwrite:
                    merged = [c for c in merged if c["name"] != p["name"]]
                else:
                    base, n = f"{p['name']} (nhập)", 2
                    name = base
                    while name in names:
                        name, n = f"{base} {n}", n + 1
                    p = dict(p, name=name)
            merged.append(p)
            added[k] = added.get(k, 0) + 1
        if k == "table":
            save_table_presets(settings, merged)
        elif k == "interleave":
            settings.setValue(PRESET_KEY, json.dumps(merged, ensure_ascii=False))
        else:
            write_profiles(settings, merged)
    parts = ", ".join(f"{n} {KINDS[k]}" for k, n in added.items() if n) or "không có mục nào"
    QMessageBox.information(parent, "Đã nhập", f"Đã nhập {parts} từ:\n{os.path.basename(path)}")
    return added
