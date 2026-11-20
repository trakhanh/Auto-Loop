"""Chạy trong tiến trình riêng (QtWebEngine cần AA_ShareOpenGLContexts trước khi tạo QApplication).
    python tests/web_grab_probe.py <file.html> <verify_after> <give_up>
In ra một dòng JSON: {"grabbed": {...}} hoặc {"failed": "..."}."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, Qt, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
app = QApplication([])
from loopstation.ui.web_grab import WebGrabber  # noqa: E402

store = Path(tempfile.mkdtemp(prefix="ktls_web_"))
if len(sys.argv) > 4 and sys.argv[4] == "cookies":  # nạp trang (đặt cookie) trong hồ sơ app rồi đọc lại cookie
    from PySide6.QtWebEngineCore import QWebEnginePage
    from loopstation.ui.web_grab import app_profile, collect_cookies
    prof = app_profile(Path(tempfile.mkdtemp(prefix="ktls_web_")))
    pg = QWebEnginePage(prof)
    loaded = []
    pg.loadFinished.connect(lambda ok: loaded.append(ok))
    pg.load(QUrl(sys.argv[1]))
    t = time.time()
    while not loaded and time.time() - t < 30:
        app.processEvents()
        time.sleep(0.02)
    got = []
    collect_cookies(prof, got.append)
    t = time.time()
    while not got and time.time() - t < 10:
        app.processEvents()
        time.sleep(0.02)
    print(json.dumps({"cookies": got[0] if got else None}, ensure_ascii=False))
    sys.exit(0)
show = len(sys.argv) > 4 and sys.argv[4] == "verify"
g = WebGrabber(storage=store, verify_after=float(sys.argv[2]), give_up=float(sys.argv[3]), show_verify=show,
               poll_ms=300)
out = {}
if show:
    g.verifying.connect(lambda link: out.setdefault("verifying", True) and None)
g.grabbed.connect(lambda link, d: out.update(grabbed=d))
g.failed.connect(lambda link, msg: out.update(failed=msg))
g.grab(QUrl.fromLocalFile(sys.argv[1]).toString())
t = time.time()
while not ("grabbed" in out or "failed" in out) and time.time() - t < 60:
    app.processEvents()
    time.sleep(0.02)
g.shutdown()
print(json.dumps(out, ensure_ascii=False))
