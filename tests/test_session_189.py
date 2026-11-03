"""1.8.9 — giữ bản tự lưu theo tầng (5 bản mới nhất + 1 bản / giờ + 1 bản / ngày); file mẫu .ktls hỏng / không ghi được."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from loopstation.ui import main_window as mw, share_io  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _names(stamps):
    return [Path(f"tu-luu_{t:%Y%m%d_%H%M%S}.lsproj") for t in sorted(stamps)]


def test_backups_keep_recent_hourly_daily():
    now = datetime(2026, 11, 3, 18, 0, 0)
    # 3 giờ sửa liên tục (mỗi 2 phút một bản) + mỗi ngày trước đó một buổi
    stamps = [now - timedelta(minutes=2 * i) for i in range(90)]
    stamps += [now - timedelta(days=d, hours=1) for d in range(1, 12)]
    files = _names(stamps)
    drop = set(mw.backups_to_drop(files))
    kept = [f for f in files if f not in drop]
    assert files[-mw.BACKUP_KEEP:] == kept[-mw.BACKUP_KEEP:]  # 5 bản mới nhất luôn giữ
    today = {f.stem[7:18] for f in kept if f.stem.startswith("tu-luu_20261103")}
    assert today >= {"20261103_15", "20261103_16", "20261103_17", "20261103_18"}  # mỗi giờ còn một bản
    days = {f.stem[7:15] for f in kept}
    assert len(days) == mw.BACKUP_DAYS  # chỉ trong 7 ngày trước bản mới nhất; cũ hơn thì bỏ
    assert len(kept) <= mw.BACKUP_KEEP + mw.BACKUP_HOURS + mw.BACKUP_DAYS


def test_backups_few_files_keep_all():
    files = _names([datetime(2026, 11, 3, 9, 0) + timedelta(minutes=3 * i) for i in range(4)])
    assert mw.backups_to_drop(files) == []


def test_share_import_skips_table_without_rows(tmp_path, monkeypatch):
    ini = tmp_path / "s.ini"
    st = QSettings(str(ini), QSettings.Format.IniFormat)
    path = tmp_path / "mau.ktls"
    path.write_text(json.dumps({"kind": "ktls-share", "table": [{"name": "Hỏng"}, {"name": "Lành", "rows": []}]}),
                    encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    got = share_io.import_file(None, st, str(path))  # trước đây: KeyError 'rows' → hộp lỗi bất ngờ, không nhập gì
    assert got.get("table") == 1


def test_share_export_unwritable_folder(tmp_path, monkeypatch):
    ini = tmp_path / "s.ini"
    st = QSettings(str(ini), QSettings.Format.IniFormat)
    bad = tmp_path / "khong-co" / "x.ktls"  # thư mục không tồn tại → OSError khi ghi
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(bad), ""))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(share_io, "_interleave", lambda s: [{"name": "A", "base": "x"}])
    assert share_io.export_file(None, st, start=str(tmp_path)) == ""
    assert warned
