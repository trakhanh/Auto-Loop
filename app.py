"""KT Loop Station — ghép, loop video và nhạc thành video YouTube dài. By Khánh Trà."""
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from loopstation.core import ffmpeg_tools
from loopstation.ui import branding, theme


def _install_error_log() -> None:
    """Lỗi bất ngờ (bản đóng gói không có cửa sổ console): ghi vào loi-ung-dung.log + báo một hộp thoại,
    thay vì im lặng không làm gì."""
    import threading
    import traceback
    from datetime import datetime

    def write(text: str) -> str:
        path = ffmpeg_tools.data_dir() / "loi-ung-dung.log"
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text}")
        except OSError:
            pass
        return str(path)

    shown = []

    def hook(etype, value, tb) -> None:
        text = "".join(traceback.format_exception(etype, value, tb))
        path = write(text)
        if sys.stderr:
            sys.stderr.write(text)
        if QApplication.instance() is not None and not shown:  # chỉ báo 1 lần mỗi phiên, sau đó chỉ ghi nhật ký
            shown.append(1)
            try:
                QMessageBox.warning(None, "Có lỗi bất ngờ",
                                    f"App gặp lỗi nhưng vẫn chạy tiếp được. Nếu thao tác vừa rồi không có tác dụng, "
                                    f"hãy thử lại.\n\nLỗi: {value}\n\nChi tiết đã lưu ở:\n{path}")
            except Exception:  # noqa: BLE001
                pass

    sys.excepthook = hook
    threading.excepthook = lambda a: write("".join(traceback.format_exception(a.exc_type, a.exc_value,
                                                                             a.exc_traceback)))


def main() -> int:
    branding.set_windows_app_id()
    # màn hình 125% / 150%: vẽ đúng tỉ lệ, chữ và icon sắc nét
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(theme.APP_NAME)
    app.setWindowIcon(branding.app_icon())
    prefs = QSettings(theme.SETTINGS_ORG, theme.APP_NAME)
    try:
        font_pt = int(prefs.value("pref/font_pt", 10))
    except (TypeError, ValueError):
        font_pt = 10
    theme.apply(app, font_pt)
    _install_error_log()

    selftest_mode = "--selftest" in sys.argv
    lock = None
    if not selftest_mode:
        # hai cửa sổ app cùng lúc ghi đè hàng đợi / dự án tự lưu của nhau → chỉ cho mở một
        from PySide6.QtCore import QLockFile
        lock = QLockFile(str(ffmpeg_tools.data_dir() / "app.lock"))
        lock.setStaleLockTime(0)  # app trước bị tắt đột ngột: Qt tự nhận khoá cũ (tiến trình không còn) và gỡ
        if not lock.tryLock(200):
            QMessageBox.information(None, theme.APP_NAME,
                                    f"{theme.APP_NAME} đang mở rồi (xem trên thanh tác vụ).\n\n"
                                    "Chỉ mở một cửa sổ để hàng đợi và dự án không bị ghi đè lẫn nhau.")
            return 0

    from loopstation.ui.splash import Splash
    splash = Splash()
    splash.start()

    splash.step("Đang kiểm tra FFmpeg…", 0.2)
    ffmpeg_tools.set_custom_dir(prefs.value("pref/ffmpeg_dir", "") or None)
    try:
        ffmpeg_tools.ffmpeg()
        ffmpeg_tools.ffprobe()
    except FileNotFoundError as e:
        if prefs.value("pref/ffmpeg_dir", ""):  # thư mục tự chọn bị xoá/đổi → quay về tự tìm
            prefs.setValue("pref/ffmpeg_dir", "")
            ffmpeg_tools.set_custom_dir(None)
            try:
                ffmpeg_tools.ffmpeg()
                ffmpeg_tools.ffprobe()
            except FileNotFoundError:
                splash.close()
                QMessageBox.critical(None, "Thiếu FFmpeg", str(e))
                return 1
        else:
            splash.close()
            QMessageBox.critical(None, "Thiếu FFmpeg", str(e))
            return 1

    splash.step("Đang nạp giao diện…", 0.45)
    from loopstation.ui.motion import UiMotion
    from loopstation.ui.main_window import MainWindow
    from loopstation.ui.widgets import WheelGuard
    # thứ tự: bộ lọc cài sau được gọi trước → chặn lăn chuột vào ô chọn trước, rồi mới cuộn mượt
    motion = UiMotion(app)
    app.installEventFilter(motion)
    guard = WheelGuard(app)
    app.installEventFilter(guard)

    splash.step("Đang mở dự án gần nhất…", 0.7)
    win = MainWindow()
    splash.finish(win)
    if selftest_mode:  # kiểm tra bản đóng gói: KTLoopStation.exe --selftest báo-cáo.json
        from PySide6.QtCore import QTimer
        from loopstation import selftest
        report = sys.argv[sys.argv.index("--selftest") + 1] if len(sys.argv) > sys.argv.index("--selftest") + 1 \
            else "selftest.json"
        QTimer.singleShot(1500, lambda: selftest.run(win, report))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
