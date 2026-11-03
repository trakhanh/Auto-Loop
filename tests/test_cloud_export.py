"""1.8.11 — thư mục lưu trên Google Drive / OneDrive: xuất ra máy trước rồi chép thẳng một lượt sang (Drive chỉ tải lên
file đã hoàn chỉnh); chép lỗi thì không mất video."""
import os
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from loopstation.core import cloud, ffmpeg_tools as ft, render  # noqa: E402


@pytest.mark.parametrize("path, want", [
    (r"G:\Shared drives\DỰ ÁN WHITENOISE\VIDEO FINAL", "Google Drive"),
    (r"G:\My Drive\Xuat", "Google Drive"),
    (r"G:\Bộ nhớ dùng chung\Kênh A", "Google Drive"),
    (r"C:\Users\nv\My Drive\Video", "Google Drive"),
    (r"D:\Video xuat", ""),
    (r"E:\Du an\Drive cu", ""),
    ("", ""),
])
def test_provider_by_path(path, want, monkeypatch):
    monkeypatch.setattr(cloud, "_volume_label", lambda root: "")
    for var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        monkeypatch.delenv(var, raising=False)
    assert cloud.provider(path) == want


def test_provider_by_volume_label_and_onedrive(monkeypatch):
    monkeypatch.setattr(cloud, "_volume_label", lambda root: "Google Drive" if root.lower().startswith("h:") else "")
    assert cloud.provider(r"H:\Kho\Video") == "Google Drive"  # ổ Drive đặt chữ khác, thư mục con lạ
    monkeypatch.setenv("OneDrive", r"C:\Users\nv\OneDrive")
    assert cloud.provider(r"C:\Users\nv\OneDrive\Video\a") == "OneDrive"
    assert cloud.provider(r"C:\Users\nv\OneDriveCu\a") == ""


def _clip(path):
    subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=3", "-c:v",
                    "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


def _job(tmp_path, out_dir, kind="video"):
    from loopstation.core.project import ClipItem, MusicTrack, Project
    p = Project(name="drive", output_kind="video_only" if kind == "video" else "music_only")
    if kind == "video":
        clip = tmp_path / "clip.mp4"
        _clip(clip)
        p.video.clips = [ClipItem(str(clip), count=2)]
        p.video.source_audio = "off"
        p.export.encoder = "cpu"
        out = out_dir / "ra.mp4"
    else:
        song = tmp_path / "song.m4a"
        subprocess.run([ft.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:d=8", "-c:a", "aac",
                        str(song)], check=True)
        p.music.tracks = [MusicTrack(str(song))]
        out = out_dir / "nhac.mp3"
    logs = []
    job = render.RenderJob(p, {"h264": ["cpu"]}, str(out), on_log=logs.append, audio_only=kind != "video")
    return job, logs


@pytest.fixture()
def drive(tmp_path, monkeypatch):
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    d = tmp_path / "G" / "Shared drives" / "VIDEO FINAL"
    real = cloud.provider
    monkeypatch.setattr(cloud, "provider", lambda p: "Google Drive" if str(d) in str(p) else real(p))
    return d


@pytest.mark.parametrize("kind", ["video", "audio"])
def test_render_to_drive_goes_through_local_stage(tmp_path, drive, kind):
    job, logs = _job(tmp_path, drive, kind)
    seen = []
    orig = job.runner.ffmpeg

    def spy(args, *a, **k):
        seen.append(args[-1])
        return orig(args, *a, **k)
    job.runner.ffmpeg = spy
    out = job.run()
    assert out.parent == drive and out.is_file() and out.stat().st_size > 0
    stage = ft.cache_dir("xuat-tam")
    assert any(str(stage) in str(x) and ".dang-xuat" in str(x) for x in seen)  # ghép ra máy, không ghi thẳng lên Drive
    assert not any(".dang-xuat" in str(x) and str(drive) in str(x) for x in seen)
    assert list(stage.iterdir()) == []  # chép xong thì xoá bản ở máy
    assert sorted(p.name for p in drive.iterdir() if ".dang-" in p.name) == []
    assert any("Đã chép lên Google Drive" in line for line in logs)


def test_copy_failure_keeps_video(tmp_path, drive, monkeypatch):
    monkeypatch.setattr(render.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    real_open = open

    class Broken:
        def __init__(self, f):
            self.f = f

        def write(self, b):
            raise OSError(5, "Drive mất kết nối")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()

    def fake_open(path, mode="r", *a, **k):
        f = real_open(path, mode, *a, **k)
        return Broken(f) if "w" in mode and str(drive) in str(path) else f
    monkeypatch.setattr(render, "open", fake_open, raising=False)
    job, logs = _job(tmp_path, drive)
    out = job.run()
    assert out.is_file() and out.stat().st_size > 0  # video không mất
    assert "chưa chép lên Drive" in str(out)
    assert not (drive / "ra.mp4").exists()  # không để lại bản chép dở trên Drive
    assert any("không chép được lên Google Drive" in line for line in logs)


def test_export_tab_note_and_free_space(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from loopstation.ui import export_tab
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    _app = QApplication.instance() or QApplication([])
    tab = export_tab.ExportTab(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    tab.out_dir.setText(r"G:\Shared drives\VIDEO FINAL")
    assert not tab.cloud_note.isHidden() and "Google Drive" in tab.cloud_note.text()
    assert tab._space_dir() == str(ft.cache_root())  # chỗ trống tính theo ổ máy nơi xuất tạm
    tab.out_dir.setText(str(tmp_path))
    assert tab.cloud_note.isHidden() and tab._space_dir() == str(tmp_path)


def test_option_off_writes_straight_to_drive(tmp_path, drive, monkeypatch):
    """Tuỳ chọn ở Cài đặt (mỗi người tự chọn): tắt thì ghi thẳng vào thư mục Drive như thư mục thường."""
    monkeypatch.setitem(ft.OPTIONS, "cloud_stage", "")
    job, logs = _job(tmp_path, drive)
    seen = []
    orig = job.runner.ffmpeg

    def spy(args, *a, **k):
        seen.append(args[-1])
        return orig(args, *a, **k)
    job.runner.ffmpeg = spy
    out = job.run()
    assert out.parent == drive and out.is_file()
    assert any(".dang-xuat" in str(x) and str(drive) in str(x) for x in seen)
    assert any("ghi thẳng" in line for line in logs)


def test_export_tab_note_when_option_off(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from loopstation.ui import export_tab
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setitem(ft.OPTIONS, "cloud_stage", "")
    _app = QApplication.instance() or QApplication([])
    tab = export_tab.ExportTab(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    tab.out_dir.setText(r"G:\My Drive\Xuat")
    assert not tab.cloud_note.isHidden() and "ghi thẳng" in tab.cloud_note.text()
    assert tab._space_dir() == r"G:\My Drive\Xuat"
