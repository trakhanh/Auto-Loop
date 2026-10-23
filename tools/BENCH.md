# UI benchmark (baseline before performance refactor)

Run (from `E:\LoopStation`, ~25 s, offscreen Qt, isolated data dir + settings, cold thumbnail cache):

    .venv\Scripts\python.exe tools\bench_ui.py [--out tools\bench_after.json] [--n 50] [--idle 5]

Default output is `tools\bench_baseline.json`; pass `--out` to keep an "after" file and compare.
"max UI stall" = longest gap between ticks of a 10 ms QTimer on the UI thread (ideal ~10 ms).
psutil is not installed in the venv, so idle CPU uses `time.process_time` (all threads of the app process, ffmpeg children excluded).

## Baseline (branch ui-overhaul, 50 files, 2 runs; stalls vary run to run)

| Metric | Value | Max UI stall |
|---|---|---|
| a. Add 50 files (probe + rows) | 0.8-1.1 s | 33-105 ms |
| c. Thumbnails async, cold cache (50) | 5.0-5.5 s | 80-113 ms |
| c2. `_on_thumb` x50 synchronous | 5-17 ms total (max call 2 ms) | 9-23 ms |
| b. `recompute()` with 50 clips | median 9 ms (core 6-7 ms) | 14-32 ms |
| b2. `recompute()` Loop-70 sample project | median 9 ms | 10-19 ms |
| d. Idle CPU, window shown, 5 s | **52-60 % of one core** | 23 ms |

Observation: idle CPU is high even with nothing happening (also measured with an empty project, 39-63 %). Likely timers/animations/repaints; worth profiling first.

## Limitations
- Offscreen platform: no real painting/compositor cost, so paint-heavy stalls and idle CPU may differ on a real display.
- Sample clips are tiny (8 s), so recompute is fast; FFmpeg-bound work runs in worker threads and is not counted as stall.
- Thumb "total" time includes ffmpeg process spawn on 2 worker threads.
- Related smoke check: `.venv\Scripts\python.exe tests\ui_smoke.py <scratch_dir>` (56 page switches, 0 hidden errors at baseline).
