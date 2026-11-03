"""Kiểm thử các lỗi ở phần sửa bảng (trang Video / Nhạc) tìm thấy khi audit bản 1.8.8 (sửa ở 1.8.9).

Chạy không cửa sổ (offscreen), dữ liệu + cài đặt vào thư mục tạm — không đụng dữ liệu thật của app."""
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VIDEO = sorted((ROOT / "Mau-Test" / "Video").glob("*.mp4"))
MUSIC = sorted((ROOT / "Mau-Test" / "Nhac").glob("*.mp3"))
need_media = pytest.mark.skipif(len(VIDEO) < 3 or len(MUSIC) < 2, reason="thiếu Mau-Test/")
# giữ sống các cửa sổ thử: widget con của cửa sổ đã xoá mà vỏ Python còn sống sẽ làm theme.apply ở bài test sau lỗi
_KEEP: list = []


@pytest.fixture(scope="module")
def env():
    mp = pytest.MonkeyPatch()
    scratch = tempfile.mkdtemp(prefix="ktls_audit189_")
    mp.setenv("QT_QPA_PLATFORM", "offscreen")
    mp.setenv("KTLS_DATA_DIR", os.path.join(scratch, "data"))
    mp.setenv("KTLS_SETTINGS_ORG", "KTLoopStation-Test")
    mp.setenv("KTLS_NO_UPDATE", "1")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    from loopstation.ui import theme
    theme.apply(app, 10)
    # hộp thoại báo lỗi không được chặn bài test
    mp.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    mp.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    settings = QSettings(os.path.join(scratch, "s.ini"), QSettings.Format.IniFormat)
    yield app, settings, Path(scratch)
    mp.undo()
    shutil.rmtree(scratch, ignore_errors=True)


def pump(app, sec: float = 0.0, cond=None) -> bool:
    t = time.time()
    while True:
        app.processEvents()
        if cond is not None and cond():
            return True
        if time.time() - t >= sec:
            return bool(cond and cond())
        time.sleep(0.01)


def flush_deletes(app) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def fresh_copies(folder: Path, src: list[Path], n: int, ext: str) -> list[str]:
    """Bản sao tên mới (chưa có trong bộ nhớ đệm probe) → lượt đọc chạy thật, lâu đủ để thả chồng."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for k in range(n):
        p = folder / f"t{k:02d}_{os.urandom(3).hex()}{ext}"
        shutil.copy(src[k % len(src)], p)
        out.append(str(p))
    return out


def video_tab(env, clips=None):
    from loopstation.core.project import ClipItem, VideoSettings
    from loopstation.ui import video_tab as vt
    app, settings, _ = env
    tab = vt.VideoTab(settings)
    if clips:
        tab.load(VideoSettings(clips=[ClipItem(str(p), count=5) for p in clips]))
    tab.resize(1300, 800)
    return tab


# ---------- 1. thả chồng khi đang đọc: không mất lượt nào ----------
@need_media
def test_overlapping_drops_all_land_video(env):
    app, _s, scratch = env
    tab = video_tab(env)
    files = fresh_copies(scratch / "v1", VIDEO, 8, ".mp4")
    calls = []
    real = tab._on_probed
    tab._on_probed = lambda infos, gen=None: (calls.append(threading.current_thread() is threading.main_thread()),
                                             real(infos, gen))
    tab.add_paths(files[:6])
    pump(app, 0.02)
    tab.add_paths(files[6:])
    tab.add_paths(files[:2])  # thả lại file đang đọc dở: không thêm trùng
    assert pump(app, 30, lambda: tab.list.topLevelItemCount() >= 8 and not tab._probe.busy())
    pump(app, 0.3)
    assert tab.list.topLevelItemCount() == 8
    assert calls and all(calls)  # kết quả về luồng giao diện
    flush_deletes(app)
    from loopstation.ui import widgets as w
    assert not tab._probe.findChildren(w.Prober)  # Prober xong việc được dọn


@need_media
def test_overlapping_drops_all_land_music(env):
    from loopstation.ui import music_tab as mt
    app, settings, scratch = env
    tab = mt.MusicTab(settings)
    files = fresh_copies(scratch / "m1", MUSIC, 8, ".mp3")
    tab.add_paths(files[:6])
    pump(app, 0.02)
    tab.add_paths(files[6:])
    assert pump(app, 30, lambda: tab.list.topLevelItemCount() >= 8 and not tab._probe.busy())
    pump(app, 0.3)
    assert tab.list.topLevelItemCount() == 8


# ---------- 2 + 3. hộp thoại Đoạn lấy: được dọn, và báo trước khi mở ----------
@need_media
def test_trim_dialog_deleted_and_signal_emitted(env, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from loopstation.ui import trim_dialog as td
    app = env[0]
    tab = video_tab(env, VIDEO[:2])
    monkeypatch.setattr(td.TrimDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    got = []
    tab.media_dialog_opening.connect(lambda: got.append(1))
    it = tab.list.topLevelItem(0)
    for _ in range(3):
        tab._open_trim(it)
    flush_deletes(app)
    assert len(got) == 3
    assert not tab.findChildren(td.TrimDialog)
    from loopstation.ui import theme
    theme.apply(app, 10)  # đổi bộ màu sau khi hộp thoại đã xoá: không gọi vào widget đã xoá


# ---------- 4. Ctrl+Z ở mọi chỗ của trang Video (trừ ô đang gõ) ----------
@need_media
def test_undo_shortcut_works_outside_tab(env):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget
    app = env[0]
    host = QWidget()
    _KEEP.append(host)
    lay = QHBoxLayout(host)
    tab = video_tab(env, VIDEO[:3])
    outside = QPushButton("player")  # đứng thay trình phát / dòng thời gian: nằm ngoài VideoTab
    outside.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    lay.addWidget(tab)
    lay.addWidget(outside)
    host.resize(1500, 800)
    host.show()
    host.activateWindow()
    pump(app, 0.2)
    tab.list.topLevelItem(0).setSelected(True)
    tab.list.remove_selected()
    assert tab.list.topLevelItemCount() == 2
    outside.setFocus()
    pump(app, 0.05)
    QTest.keyClick(outside, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    pump(app, 0.05)
    assert tab.list.topLevelItemCount() == 3  # Ctrl+Z khi đang bấm ở ngoài bảng vẫn hoàn tác

    # đang gõ trong ô chữ: Ctrl+Z là hoàn tác chữ, không đụng bảng
    tab.list.topLevelItem(0).setSelected(True)
    tab.list.remove_selected()
    edit = QLineEdit()
    lay.addWidget(edit)
    edit.setFocus()
    pump(app, 0.05)
    QTest.keyClicks(edit, "abc")
    QTest.keyClick(edit, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    pump(app, 0.05)
    assert tab.list.topLevelItemCount() == 2
    tab._undo_key()  # gọi trực tiếp khi ô chữ đang giữ focus: cũng bỏ qua
    assert tab.list.topLevelItemCount() == 2

    # trang Video không hiện: không làm gì
    edit.clearFocus()
    outside.setFocus()
    tab.hide()
    tab._undo_key()
    assert tab.list.topLevelItemCount() == 2
    host.close()


# ---------- 5. thao tác trọn vẹn là một bước Hoàn tác riêng ----------
@need_media
def test_discrete_actions_not_merged(env):
    app = env[0]
    tab = video_tab(env, VIDEO[:3])
    lst = tab.list
    lst.setCurrentItem(lst.topLevelItem(0))
    lst.topLevelItem(0).setSelected(True)
    tab._copy_rows()
    tab._paste_rows()
    assert lst.topLevelItemCount() == 4
    tab._duplicate_selected()  # liền tay (< 250 ms)
    assert lst.topLevelItemCount() == 5
    lst.clearSelection()
    lst.topLevelItem(0).setSelected(True)
    lst.remove_selected()
    assert lst.topLevelItemCount() == 4
    lst.clearSelection()
    lst.topLevelItem(3).setSelected(True)
    lst.move_selected(-1)  # đổi thứ tự
    tab.undo()  # bỏ đổi thứ tự
    assert lst.topLevelItemCount() == 4
    tab.undo()  # bỏ xoá
    assert lst.topLevelItemCount() == 5
    tab.undo()  # bỏ nhân bản
    assert lst.topLevelItemCount() == 4
    tab.undo()  # bỏ dán
    assert lst.topLevelItemCount() == 3


@need_media
def test_typing_edit_kept_separate_from_next_action(env):
    from loopstation.ui import video_tab as vt
    app = env[0]
    tab = video_tab(env, VIDEO[:3])
    lst = tab.list
    lst.topLevelItem(1).setText(vt.COL_PLAYS, "9")  # như gõ vào ô (đang chờ 250 ms)
    lst.topLevelItem(0).setSelected(True)
    tab._duplicate_selected()  # chưa hết 250 ms
    assert lst.topLevelItemCount() == 4
    tab.undo()
    assert lst.topLevelItemCount() == 3 and lst.topLevelItem(1).text(vt.COL_PLAYS) == "9"
    tab.undo()
    assert lst.topLevelItem(1).text(vt.COL_PLAYS) == "5"


# ---------- 10. Hoàn tác không đọc lại file đã có ----------
@need_media
def test_undo_reuses_media_info(env, monkeypatch):
    from loopstation.ui import widgets as w
    tab = video_tab(env, VIDEO[:3])
    probed = []
    real = w.probe.probe_many
    monkeypatch.setattr(w.probe, "probe_many", lambda paths: (probed.append(list(paths)), real(paths))[1])
    tab.list.topLevelItem(0).setSelected(True)
    tab.list.remove_selected()
    tab.undo()  # dòng 0 không còn trong bảng → chỉ đọc lại đúng file đó
    assert tab.list.topLevelItemCount() == 3
    assert probed == [[str(VIDEO[0])]]
    tab.list.topLevelItem(0).setSelected(True)
    tab._duplicate_selected()
    probed.clear()
    tab.undo()
    assert probed == []


# ---------- 6. Chỉ video: Bảng trộn âm hiện đúng ô "Chỉ tiếng gốc" ----------
@need_media
def test_video_only_mixer_source_mode(env):
    from loopstation.ui.mixer_panel import MixerPanel
    app = env[0]
    tab = video_tab(env, VIDEO[:2])
    mx = MixerPanel()

    def set_source_mode(mode):  # như MainWindow._set_source_mode
        i = tab.source.findData(mode)
        if i >= 0 and tab.source.model().item(i).isEnabled():
            tab.source.setCurrentIndex(i)

    def recompute(mode):  # như MainWindow._recompute_core
        mx.set_state(mode, tab.collect().source_audio, False)

    def checked():
        return [k for k, b in mx.mode_buttons.items() if b.isChecked()]

    mx.sourceModeChanged.connect(set_source_mode)
    tab.source.setCurrentIndex(tab.source.findData("mix"))
    tab.set_mode("video_only")
    recompute("video_only")
    assert tab.source.currentData() == "only" and checked() == ["only"]
    assert not mx.mode_buttons["mix"].isEnabled()
    mx.mode_buttons["only"].click()
    recompute("video_only")
    assert checked() == ["only"]  # không bật ngược về "trộn"
    tab.set_mode("video_music")
    recompute("video_music")
    assert tab.source.currentData() == "mix" and checked() == ["mix"]  # quay lại: vẫn nhớ "trộn nhạc"

    # tự chọn khác ở kiểu Chỉ video → giữ lựa chọn đó
    tab.set_mode("video_only")
    mx.mode_buttons["off"].click()
    recompute("video_only")
    assert checked() == ["off"] and tab.collect().source_audio == "off"
    mx.mode_buttons["only"].click()
    recompute("video_only")
    assert checked() == ["only"] and tab.collect().source_audio == "only"
    tab.set_mode("video_music")
    assert tab.source.currentData() == "only"


# ---------- 7. lý do đúng khi thả không thêm được gì ----------
def test_drop_messages(env, tmp_path):
    from loopstation.ui import music_tab as mt
    app, settings, _ = env
    tab = video_tab(env)
    note = tmp_path / "note.txt"
    note.write_text("x")
    tab.add_paths([str(note)])
    assert "Không có file video / ảnh" in tab.status.toolTip() + tab.status.text()
    sub = tmp_path / "goc" / "con"
    sub.mkdir(parents=True)
    if VIDEO:
        shutil.copy(VIDEO[0], sub / "a.mp4")
    tab.toolbar.recursive.setChecked(False)
    tab.add_paths([str(tmp_path / "goc")])
    msg = tab.status.toolTip() + tab.status.text()
    assert "Cả thư mục con" in msg and "đã có" not in msg
    m = mt.MusicTab(settings)
    m.toolbar.recursive.setChecked(False)
    m.add_paths([str(tmp_path / "goc")])
    assert "Cả thư mục con" in m.status.toolTip() + m.status.text()


@need_media
def test_drop_message_already_in_table(env):
    tab = video_tab(env, VIDEO[:1])
    tab.add_paths([str(VIDEO[0])])
    assert "đã có trong bảng" in tab.status.toolTip() + tab.status.text()


# ---------- 8. Xoá tất cả: hỏi lại, đang tìm thì chỉ xoá dòng đang hiện ----------
@need_media
def test_clear_all_confirms_and_respects_filter(env, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    tab = video_tab(env, VIDEO[:4])
    lst, bar = tab.list, tab.toolbar
    asked = []
    answer = [QMessageBox.StandardButton.No]
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda _p, _t, text, *a, **k: (asked.append(text), answer[0])[1]))
    bar._clear_all()
    assert asked and lst.topLevelItemCount() == 4  # bấm Không: giữ nguyên
    keep = VIDEO[0].stem.split()[0]  # "01"
    bar.search.setText(keep)
    shown = len(lst.visible_items())
    assert 0 < shown < 4
    answer[0] = QMessageBox.StandardButton.Yes
    bar._clear_all()
    assert f"Xoá {shown} dòng đang hiện" in asked[-1]
    assert lst.topLevelItemCount() == 4 - shown  # dòng bị ẩn vì không khớp vẫn còn
    bar.search.clear()
    bar._clear_all()
    assert lst.topLevelItemCount() == 0
    tab.undo()  # trang Video: hoàn tác được
    assert lst.topLevelItemCount() == 4 - shown


# ---------- 9. cắt đoạn áp cho nhiều clip: kẹp theo độ dài từng clip ----------
def test_clamp_trim_matches_core():
    from loopstation.ui.trim_dialog import MIN_KEEP, clamp_trim, trim_text
    from loopstation.core import timeline
    assert MIN_KEEP == timeline.MIN_KEEP
    assert clamp_trim(8.0, 7.8, 0.0) == (7.5, 0.0)
    assert clamp_trim(8.0, 2.0, 7.0) == (2.0, 5.5)
    assert clamp_trim(20.0, 2.0, 3.0) == (2.0, 3.0)
    assert clamp_trim(0.3, 1.0, 1.0) == (0.0, 0.0)
    assert trim_text(8.0, 7.8, 0.0) == "7.5–8s"
    assert trim_text(8.0, 0.0, 9.0) == "0–0.5s"
    assert trim_text(20.0, 2.0, 3.0) == "2–17s"
    assert trim_text(8.0, 0.0, 0.0) == "Toàn bộ"


@need_media
def test_set_trim_clamps_per_clip(env):
    from loopstation.ui import video_tab as vt
    from loopstation.ui import widgets as w
    tab = video_tab(env, VIDEO[:3])
    items = tab.list.items()
    durs = [it.data(0, w.ROLE_INFO).duration for it in items]
    a = max(durs) - 0.2
    tab._set_trim(items, a, 0.0)
    for it, d in zip(items, durs):
        c = it.data(0, w.ROLE_DATA)
        assert d - c.trim_start - c.trim_end >= 0.5 - 1e-6
        lo, hi = it.text(vt.COL_TRIM).rstrip("s").split("–")
        assert float(hi) <= d + 1e-6
