"""What the overlay costs while running.

A monitoring tool that eats frames defeats its own purpose. Before caching,
the graph at 60 Hz measured about 42% of one core because the frame data was
re-fetched and the whole path rebuilt on every repaint.
"""

import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psutil  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fpsmon import config  # noqa: E402
from fpsmon.overlay import Overlay  # noqa: E402
from fpsmon.widgets import OverlayPreview  # noqa: E402

app = QApplication(sys.argv)
config.bootstrap()
me = psutil.Process()
cores = psutil.cpu_count(logical=True)
failures = []

start = time.monotonic()
random.seed(5)
fetches = {"n": 0}


def series(seconds):
    """A 144 FPS stream, counting how often the graph asks for data."""
    fetches["n"] += 1
    now = time.monotonic()
    out, t, i = [], now - seconds, 0
    while t < now:
        ft = 6.94 + 0.3 * math.sin((t - start) * 2) + random.uniform(-.2, .2)
        if i % 240 == 239:
            ft += random.uniform(9.0, 20.0)
        out.append((t, ft))
        t += ft / 1000.0
        i += 1
    return out


def measure(label, seconds=6.0):
    me.cpu_percent(None)
    fetches["n"] = 0
    paints = {"n": 0}
    t_end = time.monotonic() + seconds
    while time.monotonic() < t_end:
        app.processEvents()
        paints["n"] += 1
        time.sleep(0.002)
    cpu = me.cpu_percent(None)
    print(f"  {label:<34} {cpu:5.1f}% of one core   "
          f"({cpu / cores:4.2f}% of the CPU)   "
          f"{fetches['n'] / seconds:5.1f} fetches/s")
    return cpu


print(f"machine: {cores} logical cores\n")
print("=== baseline ===")
idle = measure("idle event loop")

prof = config.load_profile("MangoHud")
prof["graph_enabled"] = False
ov = Overlay(prof)
ov.set_values(OverlayPreview.SAMPLE)
ov.show()
app.processEvents()
no_graph = measure("overlay, graph off")

prof2 = config.load_profile("MangoHud")
prof2["graph_enabled"] = True
prof2["graph_fps"] = 60
ov.apply_profile(prof2)
ov.set_series_provider(series)
app.processEvents()
time.sleep(0.5)
graph60 = measure("graph at 60 Hz")

prof3 = dict(prof2)
prof3["graph_fps"] = 30
ov.apply_profile(prof3)
app.processEvents()
graph30 = measure("graph at 30 Hz")

print("\n=== what the graph itself costs ===")
cost60 = graph60 - no_graph
cost30 = graph30 - no_graph
print(f"  60 Hz: {cost60:5.1f}% of a core above the overlay alone")
print(f"  30 Hz: {cost30:5.1f}% of a core above the overlay alone")
print(f"  before caching this was about 40% of a core at 60 Hz")

# CPU sampling varies with what else the machine is doing - running this
# alongside the rest of the suite reads a few points higher than alone - so
# the bar is set to catch a real regression rather than to pin an exact
# figure. Anything near the old ~40% means the caching or decimation broke.
if cost60 > 28:
    failures.append(
        f"graph costs {cost60:.0f}% of a core at 60 Hz, close to the "
        f"pre-optimisation ~40%; caching or decimation has regressed"
    )

print("\n=== data is fetched at the data rate, not the frame rate ===")
print("  (frames arrive in bursts about once a second, so fetching 60x a")
print("   second returned the same answer 59 times)")
per_sec = fetches["n"] / 6.0
if per_sec > 20:
    failures.append(f"still fetching {per_sec:.0f} times a second")

print("\n=== the trail still moves and still has points ===")
gw = ov._graph_rect[2]
first = ov._graph_points(gw, 4.0)
time.sleep(0.35)
app.processEvents()
second = ov._graph_points(gw, 4.0)
print(f"  points: {len(first)} then {len(second)}")
if len(first) < 50:
    failures.append(f"only {len(first)} points, the trail would look sparse")

# force a synchronous paint: a data fetch clears the cache, so reading it
# straight after one would find nothing through no fault of the caching
ov.repaint()
cache = ov._gcache
if cache:
    print(f"  cached path points after decimation: {cache['points']}")
    print(f"  spikes marked: {len(cache['spikes'])}")
    if cache["points"] < 20:
        failures.append("decimation threw away too much")
    if cache["points"] > gw * 2 + 10:
        failures.append(
            f"{cache['points']} points for {gw}px is more detail than a "
            f"1px line can show"
        )
else:
    failures.append("no cache was built")

ov.close_hooks()
print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
