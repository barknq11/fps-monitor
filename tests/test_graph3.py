"""Reproduce PresentMon's burst-buffered delivery and verify the timeline fix."""

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from fpsmon import config, fps as fpsmod  # noqa: E402
from fpsmon.overlay import Overlay  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview")
os.makedirs(OUT, exist_ok=True)
app = QApplication(sys.argv)
config.bootstrap()
failures = []

GW = 222          # graph width in px for the MangoHud panel
WINDOW = 4.0


def build_stream(target_fps: float, seconds: float, burst_rows: int = 30):
    """Feed frames the way the parser really receives them: in bursts.

    PresentMon's stdout is block buffered through the pipe, so ~30 CSV rows
    arrive at the same instant roughly once a second.
    """
    st = fpsmod._Stream("game.exe", 1, WINDOW + 1.5)
    ft = 1000.0 / target_fps
    n = int(target_fps * seconds)
    random.seed(4)
    # simulate: build all frames, then deliver them in bursts, stamping
    # arrival time as the parser would
    now = time.monotonic()
    pending = []
    for i in range(n):
        pending.append(ft + random.uniform(-0.4, 0.4))
    # deliver oldest-first, one burst per burst_rows frames
    delivered = 0
    while delivered < len(pending):
        chunk = pending[delivered:delivered + burst_rows]
        # this whole chunk lands at one arrival instant
        arrival = now - (len(pending) - delivered) * ft / 1000.0
        for f in chunk:
            st.times.append((arrival, f))
        delivered += len(chunk)
    return st


print("=== how bursty delivery looked BEFORE the fix ===")
st = build_stream(30.0, 4.0)
raw = [(ts, ft) for ts, ft in st.times]
distinct_old = len({round(ts, 4) for ts, _ in raw})
print(f"  {len(raw)} frames arrived at only {distinct_old} distinct timestamps")
print(f"  -> the old graph could draw at most {distinct_old} vertices (hinges)")

print("\n=== after the fix: reconstructed presentation timeline ===")
series = st.series(WINDOW)
distinct_new = len({round(ts, 4) for ts, _ in series})
span = series[-1][0] - series[0][0]
print(f"  {len(series)} frames at {distinct_new} distinct timestamps")
print(f"  spanning {span:.2f}s of the {WINDOW:.1f}s window")
if distinct_new < len(series) * 0.95:
    failures.append("timestamps are still collapsing into bursts")
if span < WINDOW * 0.9:
    failures.append(f"reconstructed span only {span:.2f}s")

# spacing should be even, matching the real frame interval
gaps = [series[i][0] - series[i - 1][0] for i in range(1, len(series))]
worst = max(abs(g - 1 / 30.0) for g in gaps)
print(f"  max deviation from an even 33.3ms cadence: {worst * 1000:.2f}ms")
if worst > 0.005:
    failures.append("reconstructed cadence is uneven")

# ---------------------------------------------------------------- rendering
print("\n=== rendering: vertices and edge-to-edge coverage ===")
prof = config.load_profile("MangoHud")
prof["position"] = "custom"
prof["custom_x"], prof["custom_y"] = 60, 60
prof["graph_height"] = 70

ov = Overlay(prof)
ov.set_values({"fps": 30.0, "frametime": 33.34, "gpu_load": 22.0,
               "gpu_temp": 47.0, "gpu_clock": 1858.0, "gpu_power": 43.0,
               "cpu_load": 15.0, "cpu_temp": 59.0, "cpu_clock": 3800,
               "vram_used_gb": 6.7, "ram_used": 20.3})
ov._series = series
ov.set_series_provider(lambda _s, d=series: d)
ov.show()
app.processEvents()

gw = ov._graph_rect[2]
pts = ov._graph_points(gw, WINDOW)
xs = [x for x, _ in pts]
print(f"  vertices drawn: {len(pts)}  (was ~{distinct_old})")
print(f"  x range: {min(xs):.1f} .. {max(xs):.1f}  (graph is 0..{gw})")
if len(pts) < 60:
    failures.append(f"only {len(pts)} vertices -> still hinged")
if max(xs) < gw - 0.5:
    failures.append(f"trace stops at x={max(xs):.1f} instead of the right edge")

for _ in range(120):
    ov._tick_graph()
    app.processEvents()
ov.grab().save(os.path.join(OUT, "graph_v3_locked30.png"))

# ------------------------------------------------- 74 FPS case from screenshot 2
st2 = build_stream(74.0, 4.0)
s2 = st2.series(WINDOW)
ov.set_values({"fps": 74.0, "frametime": 13.57, "gpu_load": 79.0,
               "gpu_temp": 47.0, "gpu_clock": 1814.0, "gpu_power": 65.0,
               "cpu_load": 45.0, "cpu_temp": 63.0, "cpu_clock": 3800,
               "vram_used_gb": 6.8, "ram_used": 20.3})
ov._series = s2
ov.set_series_provider(lambda _s, d=s2: d)
for _ in range(200):
    ov._tick_graph()
    app.processEvents()
vals = [ft for _t, ft in s2]
med = sorted(vals)[len(vals) // 2]
thresh = max(med * prof.get("graph_spike_mult", 1.8),
             med + prof.get("graph_spike_floor_ms", 5.0))
reds = sum(1 for v in vals if v > thresh)
print(f"\n  74 FPS locked: median {med:.2f}ms, threshold {thresh:.2f}ms, "
      f"red markers: {reds}")
if reds:
    failures.append(f"{reds} false stutter markers on a locked 74 FPS stream")
ov.grab().save(os.path.join(OUT, "graph_v3_locked74.png"))

ov.close_hooks()
print("\n  wrote graph_v3_locked30.png and graph_v3_locked74.png")
print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
