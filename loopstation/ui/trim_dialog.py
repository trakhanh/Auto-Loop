"""Hộp thoại chọn đoạn lấy của clip: xem video trực tiếp, bỏ phần đầu / phần cuối, chỉ dùng đoạn giữa."""
from __future__ import annotations

import hashlib
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QWidget,
)

from ..core import ffmpeg_tools as ft
from . import icons
from . import widgets as w

try:  # trình phát video tích hợp (Qt Multimedia, dùng bộ giải mã FFmpeg đi kèm PySide6)
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    HAS_PLAYER = True
except ImportError:  # pragma: no cover - máy thiếu Qt Multimedia
    HAS_PLAYER = False

MIN_KEEP = 0.5  # giây tối thiểu phải giữ lại (khớp core.timeline.MIN_KEEP)


class RangeBar(QWidget):
    """Thanh thời gian: 2 tay nắm chọn đoạn lấy (phần tím), vạch trắng là vị trí đang phát.
    Kéo tay nắm để đổi đoạn; bấm/kéo chỗ khác để tua video."""
    rangeChanged = Signal(float, float)
    handleMoved = Signal(float)  # thời điểm của tay nắm đang kéo (để video nhảy theo)
    seekRequested = Signal(float)
    dragFinished = Signal()

    def __init__(self, duration: float, parent=None):
        super().__init__(parent)
        self.duration = max(0.1, duration)
        self.start, self.end = 0.0, self.duration
        self.playhead = 0.0
        self._drag: str | None = None
        fm_h = self.fontMetrics().height()
        self.setMinimumHeight(52 + fm_h + 6)  # đủ chỗ cho hàng số giây bên dưới, không bị che
        self.setMouseTracking(True)

    def set_range(self, start: float, end: float) -> None:
        self.start, self.end = start, end
        self.update()

    def set_playhead(self, t: float) -> None:
        self.playhead = t
        self.update()

    def _x(self, t: float) -> float:
        return 14 + (self.width() - 28) * t / self.duration

    def _t(self, x: float) -> float:
        return min(self.duration, max(0.0, (x - 14) / max(1, self.width() - 28) * self.duration))

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        track = QRectF(14, 12, self.width() - 28, 22)
        bg = QPainterPath()
        bg.addRoundedRect(track, 7, 7)
        p.fillPath(bg, QColor("#232838"))
        # phần bị bỏ: kẻ sọc mờ
        p.setPen(QPen(QColor("#323a4f"), 1))
        x = 14.0
        while x < self.width() - 14:
            if not (self._x(self.start) <= x <= self._x(self.end)):
                p.drawLine(QPointF(x, 34), QPointF(x + 8, 12))
            x += 7
        keep = QRectF(self._x(self.start), 12, self._x(self.end) - self._x(self.start), 22)
        kp = QPainterPath()
        kp.addRoundedRect(keep, 6, 6)
        p.fillPath(kp, QColor("#7c5cff"))
        p.setPen(QColor("white"))
        if keep.width() > 80:
            p.drawText(keep, Qt.AlignmentFlag.AlignCenter, f"lấy {self.end - self.start:.1f}s")
        for t in (self.start, self.end):
            hx = self._x(t)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.setBrush(QColor("#c4b5fd"))
            p.drawRoundedRect(QRectF(hx - 6, 6, 12, 34), 4, 4)
        # vị trí đang phát
        px = self._x(self.playhead)
        p.setPen(QPen(QColor("#fcd34d"), 2))
        p.drawLine(QPointF(px, 4), QPointF(px, 42))
        p.setBrush(QColor("#fcd34d"))
        p.drawPolygon([QPointF(px - 5, 2), QPointF(px + 5, 2), QPointF(px, 8)])
        # vạch giây + nhãn (nhãn ở mép được canh vào trong để không bị cắt)
        p.setPen(QColor("#8b93a7"))
        fm = p.fontMetrics()
        y_label = 50
        step = 1 if self.duration <= 15 else 5 if self.duration <= 60 else 10 if self.duration <= 180 else 30
        t, k = 0.0, 0
        while t <= self.duration + 1e-6:
            tx = self._x(t)
            p.drawLine(QPointF(tx, 42), QPointF(tx, 47))
            if k % 2 == 0 or self.duration <= 8:
                text = f"{t:g}s"
                tw = fm.horizontalAdvance(text)
                left = min(max(0.0, tx - tw / 2), self.width() - tw)
                p.drawText(QRectF(left, y_label, tw + 2, fm.height() + 2),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, text)
            t += step
            k += 1

    def mousePressEvent(self, e) -> None:  # noqa: N802
        x = e.position().x()
        if abs(x - self._x(self.start)) <= 10:
            self._drag = "start"
        elif abs(x - self._x(self.end)) <= 10:
            self._drag = "end"
        else:
            self._drag = "seek"
        self._move(self._t(x))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        x = e.position().x()
        if self._drag:
            self._move(self._t(x))
        else:
            near = min(abs(x - self._x(self.start)), abs(x - self._x(self.end))) <= 10
            self.setCursor(Qt.CursorShape.SizeHorCursor if near else Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._drag in ("start", "end"):
            self.dragFinished.emit()
        self._drag = None

    def _move(self, t: float) -> None:
        if self._drag == "seek":
            self.seekRequested.emit(t)
            return
        t = round(t * 10) / 10
        if self._drag == "start":
            self.start = max(0.0, min(t, self.end - MIN_KEEP))
            self.handleMoved.emit(self.start)
        else:
            self.end = min(self.duration, max(t, self.start + MIN_KEEP))
            self.handleMoved.emit(max(self.start, self.end - 0.05))
        self.update()
        self.rangeChanged.emit(self.start, self.end)


class _Grabber(QObject):
    """Lấy 1 khung hình tại thời điểm t (luồng nền, có cache)."""
    ready = Signal(str, str)  # (tag, file ảnh)

    def grab(self, tag: str, path: str, t: float) -> None:
        def work():
            key = hashlib.sha1(f"{path}|{t:.2f}".encode("utf-8")).hexdigest()[:20]
            out = ft.cache_dir("thumbs") / f"trim_{key}.jpg"
            if not out.is_file():
                try:
                    ft.run([ft.ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                            "-vf", "scale=320:-2", "-q:v", "4", str(out)], timeout=30)
                except Exception:  # noqa: BLE001
                    return
            if out.is_file():
                self.ready.emit(tag, str(out))
        threading.Thread(target=work, daemon=True).start()


def _fmt(t: float) -> str:
    return f"{int(t) // 60}:{t % 60:04.1f}"


class TrimDialog(QDialog):
    """Trả về (trim_start, trim_end, áp_dụng_cho_các_dòng_chọn) qua thuộc tính `result_values`."""

    def __init__(self, path: str, duration: float, trim_start: float, trim_end: float,
                 selected_count: int = 1, parent=None):
        super().__init__(parent)
        self.path, self.duration = path, duration
        self.setWindowTitle(f"Chọn đoạn lấy — {Path(path).name}")
        self.resize(1160, 700)
        self.setMinimumSize(900, 600)
        self.result_values: tuple[float, float, bool] | None = None
        self._was_playing = False

        title = QLabel(f"Chọn đoạn lấy — {Path(path).name}")
        title.setObjectName("h2")
        sub = w.muted(f"Clip dài <b>{duration:.1f}s</b>. Kéo <b>2 tay nắm</b> trên thanh thời gian (hoặc nhập số bên phải) "
                      "để bỏ phần đầu và phần cuối. Mỗi lần phát chỉ dùng <b>đoạn tím ở giữa</b>, kể cả khi loop 70 lần.")

        # ================= cột trái: trình phát =================
        left = QVBoxLayout()
        left.setSpacing(8)
        if HAS_PLAYER:
            self.video = QVideoWidget()
            self.video.setMinimumSize(560, 315)
            self.video.setStyleSheet("background: #000;")
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.audio.setVolume(0.5)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video)
            self.player.positionChanged.connect(self._on_position)
            self.player.mediaStatusChanged.connect(self._on_status)
            self.player.playbackStateChanged.connect(self._on_state)
            screen = QFrame()
            screen.setObjectName("playerFrame")
            screen.setStyleSheet("QFrame#playerFrame { background:#000; border:1px solid #2a2f3c; border-radius:10px; }")
            sl = QVBoxLayout(screen)
            sl.setContentsMargins(2, 2, 2, 2)
            sl.addWidget(self.video)
            left.addWidget(screen, 1)
        else:
            self.player = None
            self.video = QLabel("Máy thiếu Qt Multimedia — dùng ảnh khung hình bên phải để chọn đoạn.")
            self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video.setObjectName("muted")
            left.addWidget(self.video, 1)

        self.play_btn = QPushButton()
        self.play_btn.setFixedSize(QSize(44, 36))
        self.play_btn.setIconSize(QSize(18, 18))
        self.play_btn.setToolTip("Phát / Tạm dừng (phím Space)")
        self.play_btn.clicked.connect(self._toggle_play)
        self.time_label = QLabel("0:00.0 / " + _fmt(duration))
        self.time_label.setStyleSheet("font-family: Consolas; color: #e7e9f0;")
        self.loop_cb = QCheckBox("Lặp đoạn đã chọn")
        self.loop_cb.setChecked(True)
        self.loop_cb.setToolTip("Phát đi phát lại đúng đoạn sẽ được dùng, để xem chỗ nối đầu–cuối có mượt không")
        self.mute_btn = QPushButton()
        self.mute_btn.setCheckable(True)
        self.mute_btn.setFixedSize(QSize(36, 36))
        self.mute_btn.setToolTip("Tắt / bật tiếng")
        self.mute_btn.toggled.connect(self._toggle_mute)
        set_in = QPushButton("Đặt điểm đầu tại đây")
        set_in.setIcon(icons.icon("mark_in", 14))
        set_in.setToolTip("Bỏ mọi thứ trước vị trí đang phát (phím I)")
        set_in.clicked.connect(self._mark_in)
        set_out = QPushButton("Đặt điểm cuối tại đây")
        set_out.setIcon(icons.icon("mark_out", 14))
        set_out.setToolTip("Bỏ mọi thứ sau vị trí đang phát (phím O)")
        set_out.clicked.connect(self._mark_out)
        transport = QHBoxLayout()
        transport.setSpacing(8)
        transport.addWidget(self.play_btn)
        transport.addWidget(self.time_label)
        transport.addSpacing(6)
        transport.addWidget(self.loop_cb)
        transport.addWidget(self.mute_btn)
        transport.addStretch(1)
        transport.addWidget(set_in)
        transport.addWidget(set_out)
        for wdg in (self.play_btn, self.loop_cb, self.mute_btn, set_in, set_out):
            wdg.setEnabled(HAS_PLAYER)
        left.addLayout(transport)

        self.bar = RangeBar(duration)
        self.bar.rangeChanged.connect(self._from_bar)
        self.bar.handleMoved.connect(self._scrub)
        self.bar.seekRequested.connect(self._seek)
        self.bar.dragFinished.connect(self._drag_done)
        left.addWidget(self.bar)
        left.addWidget(w.muted("Mẹo: bấm vào thanh để tua · kéo tay nắm để chọn đoạn (video nhảy theo) · "
                               "phím <b>Space</b> phát/dừng, <b>I</b> đặt điểm đầu, <b>O</b> đặt điểm cuối"))

        # ================= cột phải: thông số =================
        def spin() -> QDoubleSpinBox:
            sb = QDoubleSpinBox()
            sb.setRange(0, max(0.0, duration - MIN_KEEP))
            sb.setDecimals(1)
            sb.setSingleStep(0.5)
            sb.setSuffix(" giây")
            return sb

        self.cut_start, self.cut_end = spin(), spin()
        self.keep = QLabel()
        self.keep.setObjectName("chipAccent")
        self.keep.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.img_start, self.img_end = QLabel(), QLabel()
        self.cap_start, self.cap_end = QLabel(), QLabel()
        thumbs = QGridLayout()
        thumbs.setHorizontalSpacing(8)
        for col, (img, cap) in enumerate(((self.img_start, self.cap_start), (self.img_end, self.cap_end))):
            img.setFixedSize(QSize(160, 90))
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img.setStyleSheet("background:#0b0d12; border:1px solid #2a2f3c; border-radius:6px; color:#6b7389;")
            img.setText("…")
            cap.setObjectName("muted")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumbs.addWidget(img, 0, col)
            thumbs.addWidget(cap, 1, col)

        form = QGridLayout()
        form.setVerticalSpacing(8)
        form.addWidget(QLabel("Bỏ đầu"), 0, 0)
        form.addWidget(self.cut_start, 0, 1)
        form.addWidget(QLabel("Bỏ cuối"), 1, 0)
        form.addWidget(self.cut_end, 1, 1)
        form.setColumnStretch(1, 1)

        presets = QGridLayout()
        presets.setSpacing(6)
        for k, (label, a, b) in enumerate((("Lấy toàn bộ", 0, 0), ("Bỏ 0.5s mỗi đầu", 0.5, 0.5),
                                           ("Bỏ 1s mỗi đầu", 1, 1), ("Bỏ 2s mỗi đầu", 2, 2))):
            pb = QPushButton(label)
            pb.setObjectName("pill")
            pb.clicked.connect(lambda _=False, x=a, y=b: self._set(x, y, seek=True))
            presets.addWidget(pb, k // 2, k % 2)
        self.mid_len = QDoubleSpinBox()
        self.mid_len.setRange(MIN_KEEP, max(MIN_KEEP, duration))
        self.mid_len.setDecimals(1)
        self.mid_len.setSuffix(" giây")
        self.mid_len.setValue(max(MIN_KEEP, round(duration * 0.6, 1)))
        mid_btn = QPushButton("Giữ đoạn giữa")
        mid_btn.setObjectName("pill")
        mid_btn.setToolTip("Lấy đúng ở chính giữa clip, dài bằng số giây bên cạnh")
        mid_btn.clicked.connect(self._keep_middle)
        mid = QHBoxLayout()
        mid.addWidget(self.mid_len, 1)
        mid.addWidget(mid_btn)

        self.apply_all = QCheckBox(f"Áp dụng cho cả {selected_count} clip đang chọn")
        self.apply_all.setVisible(selected_count > 1)
        self.apply_all.setChecked(selected_count > 1)

        right_box = QFrame()
        right_box.setObjectName("sideCard")
        right_box.setStyleSheet("QFrame#sideCard { background:#151923; border:1px solid #2a2f3c; border-radius:12px; }")
        right_box.setFixedWidth(360)
        rv = QVBoxLayout(right_box)
        rv.setContentsMargins(14, 12, 14, 12)
        rv.setSpacing(10)
        h_frames = QLabel("Khung hình đầu / cuối được lấy")
        h_frames.setObjectName("h2")
        rv.addWidget(h_frames)
        rv.addLayout(thumbs)
        h_num = QLabel("Cắt chính xác")
        h_num.setObjectName("h2")
        rv.addWidget(h_num)
        rv.addLayout(form)
        rv.addWidget(self.keep)
        h_pre = QLabel("Cắt nhanh")
        h_pre.setObjectName("h2")
        rv.addWidget(h_pre)
        rv.addLayout(presets)
        rv.addLayout(mid)
        rv.addStretch(1)
        rv.addWidget(self.apply_all)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addLayout(left, 1)
        body.addWidget(right_box)

        # ================= nút dưới =================
        ffplay = Path(ft.ffmpeg()).with_name("ffplay.exe")
        ext = QPushButton("Mở cửa sổ xem lớn")
        ext.setObjectName("ghost")
        ext.setToolTip("Phát đúng đoạn đã chọn trong cửa sổ riêng (ffplay)")
        ext.clicked.connect(lambda: self._play_external(ffplay))
        ext.setVisible(ffplay.is_file())
        cancel = QPushButton("Huỷ")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Lưu đoạn cắt")
        ok.setObjectName("accentBtn")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        btns = QHBoxLayout()
        btns.addWidget(ext)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addLayout(body, 1)
        lay.addLayout(btns)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self._toggle_play)
        QShortcut(QKeySequence(Qt.Key.Key_I), self, activated=self._mark_in)
        QShortcut(QKeySequence(Qt.Key.Key_O), self, activated=self._mark_out)

        self._grabber = _Grabber(self)
        self._grabber.ready.connect(self._on_frame)
        self._frame_timer = QTimer(self)
        self._frame_timer.setSingleShot(True)
        self._frame_timer.setInterval(250)
        self._frame_timer.timeout.connect(self._grab_frames)
        self.cut_start.valueChanged.connect(lambda *_: self._set(self.cut_start.value(), self.cut_end.value(),
                                                                 seek=True))
        self.cut_end.valueChanged.connect(lambda *_: self._set(self.cut_start.value(), self.cut_end.value()))
        self._update_buttons(False)
        self._toggle_mute(False)
        self._set(trim_start, trim_end)
        if self.player is not None:
            self.player.setSource(QUrl.fromLocalFile(path))

    # ---------- trình phát ----------
    def _sel(self) -> tuple[float, float]:
        return self.cut_start.value(), self.duration - self.cut_end.value()

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.player.setPosition(int(self._sel()[0] * 1000))
            self.player.play()  # tự phát đoạn đã chọn để xem ngay

    def _on_state(self, state) -> None:
        self._update_buttons(state == QMediaPlayer.PlaybackState.PlayingState)

    def _update_buttons(self, playing: bool) -> None:
        self.play_btn.setIcon(icons.icon("pause" if playing else "play", 18, "#ffffff"))

    def _on_position(self, ms: int) -> None:
        t = ms / 1000
        self.bar.set_playhead(t)
        self.time_label.setText(f"{_fmt(t)} / {_fmt(self.duration)}")
        start, end = self._sel()
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if playing and self.bar._drag is None and t >= end - 0.04:
            if self.loop_cb.isChecked():
                self.player.setPosition(int(start * 1000))
            else:
                self.player.pause()

    def _toggle_play(self) -> None:
        if self.player is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            start, end = self._sel()
            pos = self.player.position() / 1000
            if not (start <= pos < end - 0.05):
                self.player.setPosition(int(start * 1000))
            self.player.play()

    def _toggle_mute(self, muted: bool) -> None:
        if self.player is not None:
            self.audio.setMuted(muted)
        self.mute_btn.setIcon(icons.icon("volume_x" if muted else "volume", 16))

    def _seek(self, t: float) -> None:
        if self.player is not None:
            self.player.setPosition(int(t * 1000))
        self.bar.set_playhead(t)

    def _scrub(self, t: float) -> None:
        """Đang kéo tay nắm: dừng phát và cho video hiện đúng khung hình ở tay nắm."""
        if self.player is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._was_playing = True
            self.player.pause()
        self.player.setPosition(int(t * 1000))

    def _drag_done(self) -> None:
        if self.player is not None and self._was_playing:
            self._was_playing = False
            self.player.setPosition(int(self._sel()[0] * 1000))
            self.player.play()

    def _current(self) -> float:
        return self.player.position() / 1000 if self.player is not None else 0.0

    def _mark_in(self) -> None:
        t = round(self._current(), 1)
        self._set(t, self.cut_end.value())

    def _mark_out(self) -> None:
        t = round(self._current(), 1)
        self._set(self.cut_start.value(), self.duration - t)

    # ---------- đồng bộ giá trị ----------
    def _set(self, a: float, b: float, seek: bool = False) -> None:
        a, b = max(0.0, a), max(0.0, b)
        if self.duration - a - b < MIN_KEEP:  # cắt quá tay → giữ lại tối thiểu
            b = max(0.0, self.duration - a - MIN_KEEP)
            a = min(a, max(0.0, self.duration - b - MIN_KEEP))
        for sb, v in ((self.cut_start, a), (self.cut_end, b)):
            sb.blockSignals(True)
            sb.setValue(v)
            sb.blockSignals(False)
        self._refresh()
        if seek and self.player is not None:
            self.player.setPosition(int(a * 1000))

    def _from_bar(self, start: float, end: float) -> None:
        self._set(start, self.duration - end)

    def _keep_middle(self) -> None:
        keep = min(self.mid_len.value(), self.duration)
        side = max(0.0, (self.duration - keep) / 2)
        self._set(round(side, 2), round(side, 2), seek=True)

    def _refresh(self) -> None:
        start, end = self._sel()
        self.bar.set_range(start, end)
        self.keep.setText(f"Lấy {start:.1f}s → {end:.1f}s  ·  còn {end - start:.1f}s")
        self.cap_start.setText(f"Đầu · {start:.1f}s")
        self.cap_end.setText(f"Cuối · {end:.1f}s")
        self._frame_timer.start()

    def _grab_frames(self) -> None:
        start, end = self._sel()
        self._grabber.grab("start", self.path, start)
        self._grabber.grab("end", self.path, max(start, end - 0.05))

    def _on_frame(self, tag: str, file: str) -> None:
        pm = QPixmap(file)
        if pm.isNull():
            return
        lab = self.img_start if tag == "start" else self.img_end
        lab.setPixmap(pm.scaled(lab.size() - QSize(4, 4), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation))

    def _play_external(self, ffplay: Path) -> None:
        start, end = self._sel()
        subprocess.Popen([str(ffplay), "-hide_banner", "-loglevel", "error", "-autoexit", "-x", "960", "-y", "540",
                          "-window_title", f"Xem thử đoạn lấy — {Path(self.path).name}",
                          "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", self.path],
                         creationflags=ft.CREATE_NO_WINDOW)

    # ---------- đóng ----------
    def _release(self) -> None:
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())  # nhả file để không bị khoá khi xuất

    def _accept(self) -> None:
        self.result_values = (round(self.cut_start.value(), 3), round(self.cut_end.value(), 3),
                              self.apply_all.isChecked())
        self._release()
        self.accept()

    def reject(self) -> None:
        self._release()
        super().reject()

    def closeEvent(self, e) -> None:  # noqa: N802
        self._release()
        super().closeEvent(e)


def trim_text(duration: float, trim_start: float, trim_end: float) -> str:
    if trim_start <= 0 and trim_end <= 0:
        return "Toàn bộ"
    end = max(trim_start + MIN_KEEP, duration - trim_end)
    return f"{trim_start:g}–{end:g}s"
