"""Đổi bộ màu lúc chạy: phần chỉ đọc màu một lần lúc khởi tạo (nền VideoView, biểu tượng) phải đổi theo."""
import contextlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from loopstation.ui import icons, theme
from loopstation.ui.preview_player import VideoView


def test_palette_switch_refreshes_bg_and_icon():
    app = QApplication.instance() or QApplication([])
    start = theme.PALETTE
    try:
        theme.apply(app, theme.FONT_PT, "neon")
        view = VideoView(bg="accent")
        lbl = QLabel()
        icons.bind(lbl, "chip", 14, "accent_text")
        before_bg, before_px = view.bg.name(), lbl.pixmap().toImage()
        assert before_bg == theme.T["accent"]
        theme.apply(app, theme.FONT_PT, "ocean")
        assert view.bg.name() == theme.T["accent"] != before_bg
        assert lbl.pixmap().toImage() != before_px
    finally:
        theme.apply(app, theme.FONT_PT, start)


@contextlib.contextmanager
def _text2_changed():
    old = theme.T["text_2"]
    theme.T["text_2"] = "#ff00ff"
    theme.notify_change()
    try:
        yield
    finally:
        theme.T["text_2"] = old
        theme.notify_change()


def test_batch_dialog_follows_palette(tmp_path):
    from PySide6.QtCore import QSettings

    from loopstation.core.project import Project
    from loopstation.ui.batch_dialog import C_NOTE, BatchDialog

    app = QApplication.instance() or QApplication([])
    start = theme.PALETTE
    try:
        theme.apply(app, theme.FONT_PT, "neon")
        dlg = BatchDialog(Project(name="t"), QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
        btn = next(iter(dlg.kind_buttons.values()))
        before_icon, before_card = btn.icon().pixmap(14, 14).toImage(), dlg.card_text.text()
        with _text2_changed():  # text_2 is the same in every palette, so recolour it explicitly
            assert btn.icon().pixmap(14, 14).toImage() != before_icon
            assert dlg.sample.icon().pixmap(14, 14).toImage() != before_icon
        # one fake row: its note colour must follow the palette
        from PySide6.QtWidgets import QTreeWidgetItem
        it = QTreeWidgetItem(["x"] * 6)
        it.setForeground(C_NOTE, theme.qcolor("accent_text"))
        dlg._note_tones.append((it, "accent_text"))
        before_fg = it.foreground(C_NOTE).color().name()
        theme.apply(app, theme.FONT_PT, "ocean")
        assert dlg.card_text.text() != before_card  # accent-coloured file names
        assert it.foreground(C_NOTE).color().name() == theme.T["accent_text"] != before_fg
    finally:
        theme.apply(app, theme.FONT_PT, start)


def test_interleave_dialog_follows_palette(tmp_path):
    from PySide6.QtCore import QSettings

    from loopstation.core.project import ClipItem
    from loopstation.ui.interleave_dialog import InterleaveDialog

    app = QApplication.instance() or QApplication([])
    start = theme.PALETTE
    try:
        theme.apply(app, theme.FONT_PT, "neon")
        clips = [ClipItem(path=str(tmp_path / "loop_a.mp4"), count=2), ClipItem(path=str(tmp_path / "b.mp4"))]
        durs = {str(c.path).lower(): 8.0 for c in clips}
        dlg = InterleaveDialog(clips, durs, QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
        assert dlg.preview.count() > 0
        before = [dlg.preview.item(k).foreground().color().name() for k in range(dlg.preview.count())]
        tool_btn = next(b for b in dlg.findChildren(type(dlg.ok_btn)) if b.objectName() == "ghost" and not b.icon().isNull())
        before_icon = tool_btn.icon().pixmap(14, 14).toImage()
        theme.apply(app, theme.FONT_PT, "ocean")
        after = [dlg.preview.item(k).foreground().color().name() for k in range(dlg.preview.count())]
        assert after != before
        with _text2_changed():
            assert tool_btn.icon().pixmap(14, 14).toImage() != before_icon
    finally:
        theme.apply(app, theme.FONT_PT, start)


def test_mixer_and_trim_play_icons_follow_palette(tmp_path):
    from loopstation.ui.mixer_panel import MixerPanel
    from loopstation.ui.trim_dialog import TrimDialog

    app = QApplication.instance() or QApplication([])
    start = theme.PALETTE
    try:
        theme.apply(app, theme.FONT_PT, "neon")
        mixer = MixerPanel()
        trim = TrimDialog(str(tmp_path / "x.mp4"), 10.0, 0.0, 0.0)
        before = [b.icon().pixmap(13, 13).toImage() for b in (mixer.play_btn, trim.play_btn)]
        mute_before = trim.mute_btn.icon().pixmap(13, 13).toImage()
        theme.apply(app, theme.FONT_PT, "ocean")  # play buttons use accent_text
        after = [b.icon().pixmap(13, 13).toImage() for b in (mixer.play_btn, trim.play_btn)]
        for b, a in zip(before, after):
            assert b != a
        with _text2_changed():  # mute icon uses text_2
            assert trim.mute_btn.icon().pixmap(13, 13).toImage() != mute_before
    finally:
        theme.apply(app, theme.FONT_PT, start)
