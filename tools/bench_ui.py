r"""UI performance benchmark for KT Loop Station (headless, offscreen Qt).

Run:  .venv\Scripts\python.exe tools\bench_ui.py [--out tools\bench_baseline.json] [--n 50] [--idle 5]

Uses the real MainWindow with an isolated data dir + settings (nothing touches the user's data).
Metric "stall" = longest gap between ticks of a 10 ms QTimer on the UI thread (ideal ~10 ms).
Thumbnail cache is cold on every run (fresh data dir), so numbers include ffmpeg time on worker threads.
"""
import argparse
import hashlib
import json
import os
import shutil
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser()
ap.add_argument("--out", default=os.path.join(ROOT, "tools", "bench_baseline.json"))
ap.add_argument("--n", type=int, default=50, help="number of media files to add")
ap.add_argument("--idle", type=float, default=5.0, help="idle seconds")
ap.add_argument("--timeout", type=float, default=180.0)
args = ap.parse_args()

scratch = tempfile.mkdtemp(prefix="ktls_bench_")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["KTLS_DATA_DIR"] = os.path.join(scratch, "data")
sys.dont_write_bytecode = True
sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import theme  # noqa: E402
from loopstation.ui import widgets as w  # noqa: E402
theme.apply(app, 10)
import loopstation.ui.main_window as mw  # noqa: E402

ini = os.path.join(scratch, "settings.ini")
mw.QSettings = lambda org, name: QSettings(ini, QSettings.Format.IniFormat)

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None

now = time.perf_counter
errors: list[str] = []
sys.excepthook = lambda t, v, tb: errors.append(f"{t.__name__}: {v}")


class StallMeter:
    """10 ms QTimer; records the largest gap between ticks."""

    def __init__(self):
        self.t = QTimer()
        self.t.setInterval(10)
        self.t.setTimerType(Qt_Precise)
        self.t.timeout.connect(self._tick)
        self.last = 0.0
        self.gaps: list[float] = []

    def _tick(self):
        n = now()
        self.gaps.append(n - self.last)
        self.last = n

    def start(self):
        self.gaps = []
        self.last = now()
        self.t.start()

    def stop(self):
        self.gaps.append(now() - self.last)  # trailing gap counts (a freeze right at the end)
        self.t.stop()
        g = sorted(self.gaps)
        return {"max_stall_ms": round(g[-1] * 1000, 1),
                "p95_gap_ms": round(g[max(0, int(len(g) * 0.95) - 1)] * 1000, 1),
                "ticks": len(g)}


from PySide6.QtCore import Qt  # noqa: E402
Qt_Precise = Qt.TimerType.PreciseTimer


def wait_until(cond, timeout):
    loop = QEventLoop()
    t0 = now()
    poll = QTimer()
    poll.setInterval(5)

    def chk():
        if cond() or now() - t0 > timeout:
            loop.quit()
    poll.timeout.connect(chk)
    poll.start()
    loop.exec()
    poll.stop()
    return cond()


def sleep_pump(sec):
    loop = QEventLoop()
    QTimer.singleShot(int(sec * 1000), loop.quit)
    loop.exec()


def timed_runs(fn, runs=5, gap=0.2):
    out = []
    for _ in range(runs):
        t = now()
        fn()
        out.append((now() - t) * 1000)
        sleep_pump(gap)
    return out


# ---------- setup ----------
res: dict = {"n_files": args.n, "psutil": psutil is not None, "platform": sys.platform}
win = mw.MainWindow()
win.show()
for _ in range(20):
    app.processEvents()
win._load_initial_project()
sleep_pump(1.5)  # let startup work (encoder detection etc.) settle
vt = win.video_tab

# N distinct paths (links/copies of the sample media) so list/probe/thumb caches are really exercised
src_dir = os.path.join(ROOT, "Mau-Test")
srcs = []
for sub in ("Video", "Anh"):
    d = os.path.join(src_dir, sub)
    srcs += [os.path.join(d, f) for f in sorted(os.listdir(d))]
media_dir = os.path.join(scratch, "media")
os.makedirs(media_dir)
paths = []
for i in range(args.n):
    s = srcs[i % len(srcs)]
    dst = os.path.join(media_dir, f"b{i:03d}_{os.path.basename(s)}".replace(" ", "_"))
    try:
        os.link(s, dst)
    except OSError:
        shutil.copy2(s, dst)
    paths.append(dst)

thumb_times: list[float] = []
vt.thumbs.image.connect(lambda *_: thumb_times.append(now()))

# ---------- (a) add files ----------
probed = {"t": None, "ui_ms": 0.0}
orig_on_probed = vt._on_probed


def wrapped(infos, gen=None):
    t = now()
    orig_on_probed(infos, gen)
    probed["ui_ms"] = (now() - t) * 1000
    probed["t"] = now()


vt._on_probed = wrapped  # add_paths looks self._on_probed up at call time
meter = StallMeter()
meter.start()
t0 = now()
vt.add_paths(paths)
ok_a = wait_until(lambda: probed["t"] is not None, args.timeout)
t_add = (probed["t"] or now()) - t0
a = meter.stop()
rows = vt.list.topLevelItemCount()
res["a_add_files"] = {"total_s": round(t_add, 3), "rows_added": rows,
                      "on_probed_ui_ms": round(probed["ui_ms"], 1), "completed": ok_a, **a}

# ---------- (c) thumbnails (async, cold cache) ----------
meter.start()
t1 = now()
ok_c = wait_until(lambda: len(thumb_times) >= rows, args.timeout)
t_thumb = (thumb_times[-1] - t1) if thumb_times else 0.0
c = meter.stop()
icons = sum(1 for it in vt.list.items() if not it.icon(0).isNull())
res["c_thumbnails_async"] = {"total_s": round(max(t_thumb, 0), 3), "thumbs_received": len(thumb_times),
                             "rows_with_icon": icons, "completed": ok_c, **c}

# (c2) synchronous cost of _on_thumb itself (thumb files are cached on disk now)
cache = os.path.join(scratch, "data", "cache", "thumbs")
calls = []
meter.start()
for it in list(vt.list.items()):
    p = it.data(0, w.ROLE_DATA).path
    st = os.stat(p)
    key = hashlib.sha1(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8")).hexdigest()[:20]
    f = os.path.join(cache, key + ".jpg")
    if os.path.isfile(f):
        from PySide6.QtGui import QImage
        img = QImage(f)  # decoded in the worker in the app; here outside the timed section
        vt._thumb_waiting.setdefault(p, []).append(it)
        t = now()
        vt._on_thumb(p, img)
        calls.append((now() - t) * 1000)
m = meter.stop()
res["c2_on_thumb_sync"] = {"calls": len(calls), "total_ms": round(sum(calls), 1),
                           "mean_ms": round(statistics.mean(calls), 2) if calls else None,
                           "max_call_ms": round(max(calls), 1) if calls else None, **m}

# ---------- (b) recompute ----------
sleep_pump(1.0)
meter.start()
times = timed_runs(win.recompute)
b = meter.stop()
t = now()
win._recompute_core()
core_ms = (now() - t) * 1000
t = now()
win.collect_project()
collect_ms = (now() - t) * 1000
res["b_recompute"] = {"project": f"{rows} clips", "recompute_ms_runs": [round(x, 1) for x in times],
                      "recompute_ms_median": round(statistics.median(times), 1),
                      "recompute_ms_max": round(max(times), 1),
                      "recompute_core_ms": round(core_ms, 1), "collect_project_ms": round(collect_ms, 1),
                      "max_stall_ms_incl_pumps": b["max_stall_ms"]}

# (b2) recompute on the big sample project
win.open_project_path(os.path.join(src_dir, "Du-an-mau - Loop 70 lan.lsproj"))
sleep_pump(1.0)
times2 = timed_runs(win.recompute)
res["b2_recompute_loop70_project"] = {"recompute_ms_runs": [round(x, 1) for x in times2],
                                      "recompute_ms_median": round(statistics.median(times2), 1),
                                      "recompute_ms_max": round(max(times2), 1)}

# ---------- (d) idle CPU ----------
sleep_pump(2.0)  # let background work from loading finish
proc = psutil.Process() if psutil else None
if proc:
    proc.cpu_percent(None)
c_start, w_start = time.process_time(), now()
meter.start()
sleep_pump(args.idle)
wall = now() - w_start
cpu = time.process_time() - c_start
idle_m = meter.stop()
ncpu = os.cpu_count() or 1
d = {"seconds": round(wall, 2), "cpu_percent_of_one_core": round(100 * cpu / wall, 2),
     "cpu_percent_of_machine": round(100 * cpu / wall / ncpu, 2),
     "method": "time.process_time (all threads of this process; child ffmpeg not counted)", **idle_m}
if proc:
    d["psutil_cpu_percent"] = proc.cpu_percent(None)
    d["method"] = "process_time + psutil"
res["d_idle"] = d

res["errors"] = errors
res["python"] = sys.version.split()[0]

try:
    win.close()
    vt.thumbs.shutdown()
except Exception:  # noqa: BLE001
    pass
shutil.rmtree(scratch, ignore_errors=True)

os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
with open(args.out, "w", encoding="utf-8") as f:
    json.dump(res, f, indent=2, ensure_ascii=False)

A, C, C2, B, B2 = (res["a_add_files"], res["c_thumbnails_async"], res["c2_on_thumb_sync"],
                   res["b_recompute"], res["b2_recompute_loop70_project"])
table = [
    ("a  add files", f"{A['total_s']} s", f"{A['max_stall_ms']} ms", f"{A['rows_added']} rows; on_probed UI {A['on_probed_ui_ms']} ms"),
    ("c  thumbs async (cold)", f"{C['total_s']} s", f"{C['max_stall_ms']} ms", f"{C['thumbs_received']} thumbs"),
    ("c2 _on_thumb sync xN", f"{C2['total_ms']} ms", f"{C2['max_stall_ms']} ms", f"max call {C2['max_call_ms']} ms"),
    ("b  recompute (N clips)", f"median {B['recompute_ms_median']} ms", f"max {B['recompute_ms_max']} ms", f"core {B['recompute_core_ms']} ms"),
    ("b2 recompute (loop70)", f"median {B2['recompute_ms_median']} ms", f"max {B2['recompute_ms_max']} ms", ""),
    ("d  idle CPU", f"{d['cpu_percent_of_one_core']} % of 1 core", f"{d['max_stall_ms']} ms", f"{d['seconds']} s window"),
]
print(f"\n{'metric':<26}{'time/value':<28}{'max UI stall':<16}notes")
for r in table:
    print(f"{r[0]:<26}{r[1]:<28}{r[2]:<16}{r[3]}")
if errors:
    print("\nERRORS:", *errors, sep="\n  ")
print(f"\nJSON saved to {args.out}")
sys.stdout.flush()
os._exit(0)
