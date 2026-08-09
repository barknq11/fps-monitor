"""Benchmark recording, true percentile lows, and the results view."""

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PREVIEW_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview"
)
os.makedirs(PREVIEW_DIR, exist_ok=True)

from PySide6.QtWidgets import QApplication  # noqa: E402

from fpsmon import bench, config, fps as fpsmod  # noqa: E402
from fpsmon.settings_ui import SettingsWindow  # noqa: E402

app = QApplication(sys.argv)
config.bootstrap()
failures = []

# ================================================ true lows vs sampled lows
print("=== percentile lows: frames vs 2 Hz samples ===")
random.seed(4)
# 60 s at 120 FPS, with 1% of frames badly late
frametimes = []
for i in range(7200):
    ft = 8.33 + random.uniform(-0.3, 0.3)
    if random.random() < 0.01:
        ft = random.uniform(30.0, 60.0)
    frametimes.append(ft)

lows = bench.BenchmarkRecorder._lows(frametimes)
print(f"  frames captured: {lows['frames']}")
print(f"  average FPS:     {lows['fps_avg_frames']}")
print(f"  1% low:          {lows['fps_1low']}")
print(f"  0.1% low:        {lows['fps_01low']}")
print(f"  worst frame:     {lows['frametime_max']} ms")
print(f"  stutter:         {lows['stutter_pct']}%")

if not (lows["fps_01low"] <= lows["fps_1low"] <= lows["fps_avg_frames"]):
    failures.append("lows are not ordered 0.1% <= 1% <= average")
if lows["fps_1low"] > 60:
    failures.append(f"1% low of {lows['fps_1low']} ignores the slow frames")

# what the old sampled approach would have produced
samples = []
step = len(frametimes) // 120          # ~0.5 s of frames per sample
for i in range(0, len(frametimes) - step, step):
    window = frametimes[i:i + step]
    samples.append(1000.0 / (sum(window) / len(window)))
srt = sorted(samples)
old_p1 = srt[max(0, len(srt) // 100)]
print(f"\n  old method (1st percentile of {len(samples)} samples): {old_p1:.1f}")
print(f"  new method (mean of the slowest 1% of frames):    "
      f"{lows['fps_1low']:.1f}")
print("  the sampled figure averages the stutter away, which is why it")
print("  reported a far healthier number than the run actually delivered")
if old_p1 <= lows["fps_1low"]:
    failures.append("expected the sampled method to overstate the 1% low")

print("\n=== not enough frames is reported honestly ===")
print(f"  10 frames -> {bench.BenchmarkRecorder._lows([8.0] * 10)}")
if bench.BenchmarkRecorder._lows([8.0] * 10):
    failures.append("computed lows from a sample too small to mean anything")

# ================================================ record a run end to end
print("\n=== recording a run ===")
rec = bench.BenchmarkRecorder()
path = rec.start("TestGame")
print(f"  writing {os.path.basename(path)}")
for i in range(40):
    rec.sample({
        "fps": 118 + random.uniform(-4, 4),
        "frametime": 8.4, "gpu_load": 97.0, "gpu_temp": 70 + i * 0.1,
        "gpu_power": 180.0, "cpu_load": 42.0, "cpu_temp": 61.0,
        "vram_used_gb": 8.1, "ram_used": 20.0, "app": "TestGame.exe",
    })
rec.set_frametimes(frametimes)
summary = rec.stop()
print(f"  summary keys: {sorted(summary)[:8]}...")
for key in ("fps_1low", "fps_01low", "fps_avg_frames", "frames"):
    if key not in summary:
        failures.append(f"summary is missing {key}")
print(f"  1% low in summary: {summary.get('fps_1low')}")

# ================================================ read it back
print("\n=== reading runs back ===")
runs = bench.load_runs()
print(f"  found {len(runs)} run(s)")
mine = next((r for r in runs if r.path == path), None)
if mine is None:
    failures.append("the run just written was not found by load_runs")
else:
    print(f"  app={mine.app!r} when={mine.when!r}")
    print(f"  parsed 1% low: {mine.value('fps_1low')}")
    if mine.value("fps_1low") != summary.get("fps_1low"):
        failures.append("summary did not survive the round trip through CSV")
    if mine.value("nonexistent") is not None:
        failures.append("missing keys should read as None")

# ================================================ the results view
print("\n=== results page ===")
w = SettingsWindow(config.load_profile("Default"), lambda: "status")
w.resize(1000, 700)
w.show()
w.refresh_runs()
app.processEvents()
print(f"  runs listed: {w.run_list.count()}")
if w.run_list.count() != len(runs):
    failures.append("the list does not match what load_runs returned")

if w.run_list.count() >= 1:
    w.run_list.setCurrentRow(0)
    app.processEvents()
    print(f"  single run  -> {w.run_table.rowCount()} rows, "
          f"{w.run_table.columnCount()} columns")
    if w.run_table.columnCount() != 2:
        failures.append("a single run should show two columns")

if w.run_list.count() >= 2:
    w.run_list.item(0).setSelected(True)
    w.run_list.item(1).setSelected(True)
    app.processEvents()
    print(f"  two runs    -> {w.run_table.rowCount()} rows, "
          f"{w.run_table.columnCount()} columns (adds a change column)")
    if w.run_table.columnCount() != 4:
        failures.append("comparing two runs should add a change column")
    hdr = [w.run_table.horizontalHeaderItem(i).text()
           for i in range(w.run_table.columnCount())]
    print(f"  headers: {hdr}")
    if hdr[-1] != "Change":
        failures.append(f"last column is {hdr[-1]!r}, expected 'Change'")
else:
    print("  only one run present, comparison view not exercised")

bench_page = next(
    (i for i in range(w.nav.count()) if w.nav.item(i).text() == "Benchmarks"), 0
)
w.nav.setCurrentRow(bench_page)
app.processEvents()
w.grab().save(os.path.join(PREVIEW_DIR, "ui_benchmarks.png"))
print(f"  wrote preview/ui_benchmarks.png")

# clean up only the run this test made
bench.delete_run(path)
print(f"  removed the test run: {not os.path.exists(path)}")

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
