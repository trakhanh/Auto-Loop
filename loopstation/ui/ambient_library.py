"""Hộp thoại "Thư viện tiếng nền có sẵn": chọn mưa / sóng / gió / lửa / noise, nghe thử, thêm vào dự án."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QSize, Qt, QUrl, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout,
)

from ..core import ambient_lib
from . import icons, theme
from . import widgets as w


class _Bridge(QObject):
    ready = Signal(str, str)  # (khoá, file) — "" nếu lỗi


class AmbientLibraryDialog(QDialog):
    def __init__(self, have: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thư viện tiếng nền có sẵn")
        self.setMinimumSize(680, 520)
        self.result_keys: list[str] = []
        self._player = None
        self._audio = None
        self._playing = ""
        self._bridge = _Bridge()
        self._bridge.ready.connect(self._on_ready)

        intro = QLabel("Âm do app <b>tự tạo</b> — không cần file, không cần mạng, dùng thoải mái cho video đăng YouTube. "
                       "Tick các âm muốn dùng (phối nhiều lớp được, ví dụ <i>Mưa rào + Lửa củi</i>), bấm "
                       "<b>Nghe thử</b> để nghe, rồi <b>Thêm vào dự án</b>. Âm tự lặp liền mạch suốt video / file nhạc.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Âm", "Mô tả"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 250)  # đủ chỗ cho tên dài (ô tick + icon + chữ)
        for key, s in ambient_lib.SOUNDS.items():
            path = ambient_lib.PREFIX + key
            it = QTreeWidgetItem([s.name, s.desc])
            it.setData(0, Qt.ItemDataRole.UserRole, key)
            if path in have:
                it.setText(1, s.desc + "   (đã có trong dự án)")
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                it.setForeground(1, it.foreground(1).color().darker(150))
            else:
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Unchecked)
            it.setIcon(0, icons.icon("waves", 14, "info_text"))
            self.tree.addTopLevelItem(it)
        self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._preview(it))
        self.tree.itemChanged.connect(lambda *_: self._update())

        self.play_btn = QPushButton("Nghe thử")
        self.play_btn.setObjectName("pill")
        self.play_btn.setIcon(icons.icon("play", 13))
        self.play_btn.setIconSize(QSize(13, 13))
        self.play_btn.clicked.connect(lambda: self._preview(self.tree.currentItem()))
        self.status = w.muted("Chọn một dòng rồi bấm Nghe thử (hoặc nhấp đúp).")
        self.volume = QSpinBox()
        self.volume.setRange(1, 200)
        self.volume.setSuffix(" %")
        self.volume.setValue(60)
        self.volume.setToolTip("Âm lượng ban đầu của các lớp thêm vào (sửa lại từng lớp được ở bảng tiếng nền)")
        row = QHBoxLayout()
        row.addWidget(self.play_btn)
        row.addWidget(self.status, 1)
        row.addWidget(QLabel("Âm lượng"))
        row.addWidget(self.volume)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = bb.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setObjectName("accentBtn")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Đóng")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(intro)
        lay.addWidget(self.tree, 1)
        lay.addLayout(row)
        lay.addWidget(bb)
        self._update()

    def _checked(self) -> list[str]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.flags() & Qt.ItemFlag.ItemIsUserCheckable and it.checkState(0) == Qt.CheckState.Checked:
                out.append(it.data(0, Qt.ItemDataRole.UserRole))
        return out

    def _update(self) -> None:
        n = len(self._checked())
        self.ok_btn.setText(f"Thêm {n} âm vào dự án" if n else "Thêm vào dự án")
        self.ok_btn.setEnabled(n > 0)

    # ---------- nghe thử ----------
    def _preview(self, it) -> None:
        if it is None:
            return
        key = it.data(0, Qt.ItemDataRole.UserRole)
        if self._playing == key and self._player is not None:
            self._stop()
            return
        self.status.setText(f"Đang tạo âm “{ambient_lib.SOUNDS[key].name}” (lần đầu mất vài giây)…")
        self.play_btn.setEnabled(False)

        def work():
            try:
                path = ambient_lib.generate(key)
            except Exception:  # noqa: BLE001
                path = ""
            self._bridge.ready.emit(key, path)

        threading.Thread(target=work, daemon=True).start()

    def _on_ready(self, key: str, path: str) -> None:
        self.play_btn.setEnabled(True)
        if not path:
            self.status.setText("<span style='color:" + theme.T["danger_text"] + "'>Không tạo được âm này.</span>")
            return
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            w.open_with_default_app(path)
            return
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._audio.setVolume(0.8)
            self._player.setAudioOutput(self._audio)
            self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()
        self._playing = key
        self.play_btn.setText("Dừng nghe")
        self.play_btn.setIcon(icons.icon("stop", 13))
        self.status.setText(f"Đang phát: <b>{ambient_lib.SOUNDS[key].name}</b> — bấm Dừng nghe hoặc chọn âm khác.")

    def _stop(self) -> None:
        if self._player is not None:
            self._player.stop()
        self._playing = ""
        self.play_btn.setText("Nghe thử")
        self.play_btn.setIcon(icons.icon("play", 13))
        self.status.setText("Đã dừng.")

    def _accept(self) -> None:
        self.result_keys = self._checked()
        self._stop()
        self.accept()

    def reject(self) -> None:  # noqa: D401
        self._stop()
        super().reject()
