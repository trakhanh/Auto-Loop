"""Bảng trộn âm: một chỗ chỉnh âm lượng cho mọi chế độ (nhạc, tiếng gốc clip, từng lớp tiếng nền) + nghe thử 20 giây."""
from __future__ import annotations

from PySide6.QtCore import QRegularExpression, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ..core.project import format_hms, parse_hms
from . import icons, theme
from . import widgets as w

MAX_PCT = 200


class _Channel:
    """Một dòng: tên · thanh trượt · ô % · (ghi chú khi không dùng được)."""

    def __init__(self, grid: QGridLayout, row: int, icon: str, color: str, name: str, tip: str):
        self.icon = QLabel()
        icons.bind(self.icon, icon, 15, color)
        self.name = QLabel(name)
        self.name.setToolTip(tip)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, MAX_PCT)
        self.slider.setPageStep(10)
        self.slider.setToolTip(tip + "\n100% = giữ nguyên · bấm đúp tên để về 100%")
        self.spin = QSpinBox()
        self.spin.setRange(0, MAX_PCT)
        self.spin.setSuffix(" %")
        self.spin.setMinimumWidth(78)
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        self.note = w.muted("")
        self.note.setWordWrap(True)
        self.note.hide()
        self.name.mouseDoubleClickEvent = lambda _e: self.spin.setValue(100)
        self.name.setWordWrap(True)  # tên lớp dài không làm bảng tràn ngang cột phải
        self.name.setMinimumWidth(40)
        # 3 dòng: [biểu tượng] tên ............ [ô %] / thanh trượt rộng / ghi chú khi bị khoá
        grid.addWidget(self.icon, row, 0)
        grid.addWidget(self.name, row, 1)
        grid.addWidget(self.spin, row, 2)
        grid.addWidget(self.slider, row + 1, 1, 1, 2)
        grid.addWidget(self.note, row + 2, 1, 1, 2)
        self.widgets = (self.icon, self.name, self.slider, self.spin, self.note)

    def set_value(self, v: int) -> None:
        self.spin.blockSignals(True)
        self.slider.blockSignals(True)
        self.spin.setValue(int(v))
        self.slider.setValue(int(v))
        self.spin.blockSignals(False)
        self.slider.blockSignals(False)

    def set_usable(self, on: bool, why: str = "") -> None:
        for wd in (self.name, self.slider, self.spin, self.icon):
            wd.setEnabled(on)
        self.note.setText(why)
        self.note.setVisible(bool(why) and not on)

    def set_visible(self, on: bool) -> None:
        for wd in self.widgets:
            wd.setVisible(on and (wd is not self.note or bool(self.note.text()) and not self.slider.isEnabled()))

    def remove(self) -> None:
        for wd in self.widgets:
            wd.setParent(None)
            wd.deleteLater()


class MixerPanel(QGroupBox):
    changed = Signal()  # một thanh âm lượng bất kỳ đổi (nhạc / tiếng gốc / tiếng nền)
    ambientVolumeChanged = Signal(int, int)  # (dòng trong bảng tiếng nền, %)
    previewRequested = Signal(float)  # nghe thử từ giây thứ …
    playbackStopped = Signal()  # nghe xong / bấm dừng

    def __init__(self, parent=None, hints: bool = True):
        super().__init__("Bảng trộn âm (âm lượng)", parent)
        self._total = 0.0
        self._changes: list[float] = []
        self._player = None
        self._audio = None
        self._last_start = 0.0
        self._resume_ms = 0
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.addWidget(w.muted("Chỉnh độ to của từng nguồn âm trong file xuất. <b>100%</b> = giữ nguyên. "
                              "Muốn tiếng nền nổi hơn nhạc: <b>giảm Nhạc</b> (50–70%) thay vì đẩy nền quá 150%."))
        self._hints = hints
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(4)
        self.grid.setColumnStretch(1, 1)
        lay.addLayout(self.grid)
        self.music = _Channel(self.grid, 0, "music", "accent_text", "Nhạc (playlist)",
                              "Âm lượng chung của cả playlist (sau khi chuẩn hoá LUFS)")
        self.source = _Channel(self.grid, 3, "film", "info_text", "Tiếng gốc clip",
                               "Tiếng có sẵn trong các clip video (kể cả Intro / Outro nếu giữ tiếng)")
        for ch in (self.music, self.source):
            ch.spin.valueChanged.connect(lambda *_: None if self._loading else self._value_changed())
        self._amb_title = QLabel("TIẾNG NỀN")
        self._amb_title.setObjectName("metricTitle")
        self._amb_title.setContentsMargins(0, 8, 0, 0)
        self.grid.addWidget(self._amb_title, 6, 0, 1, 3)
        self._amb_rows: list[_Channel] = []
        self._amb_empty = w.muted("Chưa có lớp tiếng nền — thêm ở thẻ <b>Lớp tiếng nền</b> bên dưới." if hints
                                  else "Dự án không có lớp tiếng nền.")
        self.grid.addWidget(self._amb_empty, 7, 0, 1, 3)
        if hints:
            lay.addWidget(w.muted("Âm lượng <b>riêng từng bài</b>: bấm đúp cột <i>Âm lượng %</i> trong playlist "
                                  "(hoặc chuột phải bài → Đặt âm lượng)."))

        # ----- nghe thử -----
        self.at = w.DurationEdit(0, allow_zero=True)
        self.at.setToolTip("Nghe từ mốc nào trên video / file nhạc. " + w.DurationEdit.HELP)
        prow_box = QWidget()
        prow = w.FlowLayout(prow_box, spacing=5)
        prow.addWidget(QLabel("Nghe từ"))
        prow.addWidget(self.at)
        self._quick = {}
        for key, text, tip in (("start", "Đầu", "Từ đầu file"), ("mid", "Giữa", "Đoạn giữa file"),
                               ("change", "Chỗ đổi bài", "Chỗ chuyển giữa 2 bài nhạc đầu tiên (nghe crossfade)"),
                               ("end", "Cuối", "20 giây cuối (nghe đoạn nhỏ dần)")):
            b = QPushButton(text)
            b.setObjectName("pill")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self._quick_pos(k))
            prow.addWidget(b)
            self._quick[key] = b
        lay.addWidget(prow_box)
        brow = QHBoxLayout()
        self.play_btn = QPushButton("Nghe thử 20 giây")
        self.play_btn.setObjectName("accentBtn")
        self.play_btn.setIcon(icons.icon("play", 13, "accent_text"))
        theme.on_change(self.play_btn, lambda btn: btn.setIcon(icons.icon(btn.property("icon_name") or "play", 13, "accent_text")))
        self.play_btn.setIconSize(QSize(13, 13))
        self.play_btn.setToolTip("Trộn nhanh 20 giây đúng như khi xuất (nhạc + tiếng gốc + tiếng nền) rồi phát trong app")
        self.play_btn.clicked.connect(self._toggle_play)
        brow.addWidget(self.play_btn)
        self.status = w.muted("")
        self.status.setWordWrap(True)
        brow.addWidget(self.status, 1)
        lay.addLayout(brow)

        self._tick = QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._update_status)
        self._busy = False
        self._stale = ""
        from .live_mix import LivePlayer
        self.live = LivePlayer(self)  # tự hoà các kênh khi phát → kéo thanh là nghe khác ngay
        self.live.finished.connect(self._on_finished)
        self._fb_stems: dict[str, bytes] | None = None  # dự phòng: máy không phát trực tiếp được
        self._fb_n = 0
        self._fb_timer = QTimer(self)
        self._fb_timer.setSingleShot(True)
        self._fb_timer.setInterval(300)
        self._fb_timer.timeout.connect(self._fallback_remix)

    # ---------- giá trị ----------
    def set_values(self, music: int, source: int) -> None:
        self._loading = True
        self.music.set_value(music)
        self.source.set_value(source)
        self._loading = False

    def values(self) -> tuple[int, int]:
        return self.music.spin.value(), self.source.spin.value()

    def gains(self) -> dict[str, float]:
        """Hệ số âm lượng theo kênh nghe thử (amb:k = lớp thứ k trong bảng tiếng nền)."""
        g = {"music": self.music.spin.value() / 100, "source": self.source.spin.value() / 100}
        for k, ch in enumerate(self._amb_rows):
            g[f"amb:{k}"] = ch.spin.value() / 100
        return g

    def ambient_values(self) -> list[int]:
        return [ch.spin.value() for ch in self._amb_rows]

    def _apply_gains(self) -> None:
        if self.live.is_playing():
            for k, v in self.gains().items():
                self.live.set_gain(k, v)
        elif self._fb_stems is not None and self.is_playing():
            self._fb_timer.start()

    def _value_changed(self) -> None:
        self._apply_gains()
        self.changed.emit()

    def set_ambient(self, layers: list[tuple[str, int, bool]]) -> None:
        """layers: (tên, %, bật) theo thứ tự bảng tiếng nền."""
        if [r.name.text() for r in self._amb_rows] != [n for n, _v, _on in layers]:
            for r in self._amb_rows:
                r.remove()
            self._amb_rows = []
            for k, (name, _v, _on) in enumerate(layers):
                ch = _Channel(self.grid, 8 + 3 * k, "waves", "info_text", name, f"Âm lượng lớp tiếng nền “{name}”")
                ch.spin.valueChanged.connect(lambda v, i=k: None if self._loading else self._amb_changed(i, v))
                self._amb_rows.append(ch)
        self._loading = True
        for ch, (_n, vol, on) in zip(self._amb_rows, layers):
            ch.set_value(vol)
            ch.set_usable(on, "Lớp này đang tắt (bỏ tick trong bảng tiếng nền)")
        self._loading = False
        self._amb_empty.setVisible(not layers)

    def _amb_changed(self, row: int, vol: int) -> None:
        self._apply_gains()
        self.ambientVolumeChanged.emit(row, vol)
        self.changed.emit()

    def set_state(self, mode: str, source_audio: str, bookend_audio: bool) -> None:
        """Bật / khoá từng dòng theo kiểu sản phẩm (ghi rõ lý do khi khoá)."""
        if mode == "music_only":
            self.music.set_usable(True)
        elif mode == "video_only":
            self.music.set_usable(False, "Kiểu Chỉ video không dùng playlist nhạc.")
        elif source_audio == "only":
            self.music.set_usable(False, "Đang chọn “Chỉ tiếng gốc clip” (trang Video → Khung & Tiếng).")
        else:
            self.music.set_usable(True)
        show_src = mode != "music_only"
        if show_src:
            if source_audio == "off" and not bookend_audio:
                self.source.set_usable(False, "Tiếng gốc clip đang tắt (trang Video → Khung & Tiếng).")
            else:
                self.source.set_usable(True)
        self.source.set_visible(show_src)

    def set_timeline(self, total: float, changes: list[float]) -> None:
        self._total, self._changes = max(0.0, total), changes
        self._quick["change"].setEnabled(bool(changes))
        for k in ("mid", "end"):
            self._quick[k].setEnabled(total > 25)

    def _quick_pos(self, key: str) -> None:
        t = {"start": 0.0, "mid": self._total / 2, "end": max(0.0, self._total - 20),
             "change": max(0.0, (self._changes[0] if self._changes else 0) - 8)}[key]
        self.at.set_seconds(t)

    def start_seconds(self) -> float:
        self.at._commit()  # đang gõ dở rồi bấm Nghe luôn: lấy giá trị vừa gõ
        return self.at.seconds()

    # ---------- nghe thử ----------
    def is_playing(self) -> bool:
        if self.live.is_playing():
            return True
        if self._player is None:
            return False
        from PySide6.QtMultimedia import QMediaPlayer
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def _toggle_play(self) -> None:
        if self._busy:
            return
        if self.is_playing():
            self.stop()
            return
        self._last_start = self.start_seconds()
        self.previewRequested.emit(self._last_start)

    def set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        if busy:
            self.play_btn.setText("Đang chuẩn bị…")
            self.play_btn.setEnabled(False)
            self.status.setText(text or "Đang tách nhạc / tiếng gốc / tiếng nền thành từng kênh (lần đầu đo độ to "
                                        "các bài nên lâu hơn một chút)…")
        else:
            self.play_btn.setEnabled(True)
            self._set_play_text()

    def _set_play_text(self) -> None:
        playing = self.is_playing()
        self.play_btn.setText("Dừng nghe" if playing else "Nghe thử 20 giây")
        self.play_btn.setProperty("icon_name", "stop" if playing else "play")  # read back when the palette changes
        self.play_btn.setIcon(icons.icon("stop" if playing else "play", 13, "accent_text"))

    def play_stems(self, stems: dict[str, bytes], start: float) -> None:
        """Phát các kênh riêng; âm lượng lấy từ các thanh và đổi được ngay trong lúc nghe."""
        self.stop(quiet=True)
        self._last_start, self._stale = start, ""
        if self.live.available():
            self.live.play(stems, self.gains())
        else:
            self._fb_stems = stems
            self._fallback_play(0)
        self._tick.start()
        self.set_busy(False)
        self._update_status()

    # dự phòng: hoà sẵn cả 20 giây trong app (vài phần trăm giây) rồi phát bằng trình phát thường
    def _fallback_play(self, pos_ms: int) -> None:
        import wave
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from ..core import ffmpeg_tools as ft
        from .live_mix import CH, RATE, WIDTH, Mixer
        data = Mixer(self._fb_stems, self.gains()).mix_all()
        self._fb_n += 1
        path = ft.preview_dir() / f"nghe-thu_tron{self._fb_n % 2}.wav"  # 2 file luân phiên (file kia đang mở)
        with wave.open(str(path), "wb") as f:
            f.setnchannels(CH)
            f.setsampwidth(WIDTH)
            f.setframerate(RATE)
            f.writeframes(data)
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
            self._player.mediaStatusChanged.connect(self._on_media)
            self._player.playbackStateChanged.connect(lambda *_: self._set_play_text())
        self._pending_seek = pos_ms
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    def _fallback_remix(self) -> None:
        if self._player is not None and self.is_playing() and self._fb_stems is not None:
            self._fallback_play(self._player.position())

    def _on_media(self, status) -> None:
        from PySide6.QtMultimedia import QMediaPlayer
        seek = getattr(self, "_pending_seek", 0)
        if seek and status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self._pending_seek = 0
            self._player.setPosition(seek)
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._on_finished()

    def position(self) -> float:
        if self.live.is_playing():
            return self.live.position()
        return self._player.position() / 1000 if self._player is not None else 0.0

    def mark_stale(self, text: str) -> None:
        """Đổi thứ không chỉnh trực tiếp được khi đang nghe (playlist, âm lượng từng bài…) → nhắc nghe lại."""
        if self.is_playing():
            self._stale = text

    def _update_status(self) -> None:
        if not self.is_playing():
            return
        pos = min(20.0, self.position())
        msg = (f"Đang nghe {format_hms(self._last_start + pos)} ({int(pos)}/20 giây) — kéo thanh âm lượng là "
               "nghe thay đổi ngay.")
        if self._stale:
            msg += f"<br><span style='color:{theme.T['warn_text']}'>{self._stale}</span>"
        self.status.setText(msg)

    def _on_finished(self) -> None:
        self._tick.stop()
        self._set_play_text()
        self.status.setText("Đã nghe hết 20 giây. Bấm nghe lại, hoặc đổi mốc “Nghe từ”.")
        self.playbackStopped.emit()

    def show_error(self, text: str) -> None:
        self.set_busy(False)
        self.status.setText(f"<span style='color:{theme.T['danger_text']}'>{text}</span>")

    def stop(self, quiet: bool = False) -> None:
        was = self.is_playing()
        self.live.stop()
        self._fb_timer.stop()
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())  # nhả file để lần sau xoá được
        self._tick.stop()
        self._set_play_text()
        if not quiet:
            self.status.setText("")
            if was:
                self.playbackStopped.emit()
