"""Reproduce the three reported graph problems and verify the fixes."""

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

# =========================================================== 1) cut-off graph
print("=== 1) history must cover the graph window ===")
be = fpsmod.FPSBackend()
be.set_retention(4.0 + 1.5)
st = fpsmod._Stream("game.exe", 123, be._retention)
be._streams[123] = st

# 110 FPS locked, 6 seconds of it
now = time.monotonic()
t = now - 6.0
random.seed(5)
i = 0
while t < now:
    # Locked 110 FPS as it really looks: normal jitter plus the occasional
    # slightly late frame that is invisible to the eye.
    ft = 9.09 + random.uniform(-1.6, 1.6)
    if i % 37 == 0:
        ft = 9.09 + random.uniform(3.0, 5.2)   # 12-14ms: still imperceptible
    st.times.append((t, ft))
    t += ft / 1000.0
    i += 1
oldest_age = now - st.times[0][0]
series = st.series(4.0)
span = (series[-1][0] - series[0][0]) if series else 0
print(f"  retention: {st.retention:.1f}s | oldest sample age: {oldest_age:.1f}s")
print(f"  series(4.0) spans {span:.2f}s of a 4.0s window ({len(series)} frames)")
if span < 3.8:
    failures.append(f"graph window is only {span:.2f}s of data -> cut off")

# =============================================== 2) false spikes when locked
print("\n=== 2) locked framerate must not be flagged as stutter ===")
prof = config.load_profile("MangoHud")
prof["position"] = "custom"
prof["custom_x"], prof["custom_y"] = 60, 60
prof["graph_height"] = 70

vals = [ft for _t, ft in series]
med = sorted(vals)[len(vals) // 2]
old_thresh = med * 1.5
new_thresh = max(
    med * float(prof.get("graph_spike_mult", 1.8)),
    med + float(prof.get("graph_spike_floor_ms", 5.0)),
)
old_hits = sum(1 for v in vals if v > old_thresh)
new_hits = sum(1 for v in vals if v > new_thresh)
print(f"  median {med:.2f}ms")
print(f"  old rule (>{old_thresh:.2f}ms): {old_hits} frames flagged")
print(f"  new rule (>{new_thresh:.2f}ms): {new_hits} frames flagged")
if new_hits != 0:
    failures.append(f"locked framerate still flags {new_hits} false stutters")

# a REAL stutter must still be caught
real = list(vals)
real[len(real) // 2] = 48.0
if not any(v > new_thresh for v in real):
    failures.append("a genuine 48ms hitch is no longer detected")
else:
    print("  a genuine 48ms hitch is still detected: yes")

# ====================================================== 3) scale readability
print("\n=== 3) one hitch must not squash the baseline ===")
ov = Overlay(prof)
ov.set_values({"fps": 110.0, "frametime": 9.14, "gpu_load": 85.0,
               "gpu_temp": 47.0, "gpu_clock": 1847.0, "gpu_power": 70.0,
               "cpu_load": 46.0, "cpu_temp": 65.0, "cpu_clock": 3800,
               "vram_used_gb": 6.6, "ram_used": 19.5})
spiky = [(ts, ft) for ts, ft in series]
spiky[len(spiky) // 2] = (spiky[len(spiky) // 2][0], 47.0)
ov._series = spiky
ov.set_series_provider(lambda _s, d=spiky: d)
ov.show()
app.processEvents()

# settle the eased scale
for _ in range(200):
    ov._paint_graph_scale_probe = None
    ov._tick_graph()
    app.processEvents()
top = getattr(ov, "_graph_scale", 0)
baseline_frac = med / top
print(f"  auto scale settled at {top:.1f}ms (old rule would give {47.0 * 1.15:.1f}ms)")
print(f"  9.09ms baseline sits at {baseline_frac * 100:.0f}% of graph height")
if baseline_frac < 0.25:
    failures.append(
        f"baseline still squashed at {baseline_frac * 100:.0f}% of height"
    )

ov.grab().save(os.path.join(OUT, "graph_fixed_locked110.png"))

# ---- and with genuine stutter -------------------------------------------
rough = []
random.seed(9)
t = now - 4.0
i = 0
while t < now:
    ft = 9.09 + random.uniform(-0.3, 0.3)
    if i in (120, 260):
        ft = random.uniform(28.0, 45.0)
    rough.append((t, ft))
    t += ft / 1000.0
    i += 1
ov._series = rough
ov.set_series_provider(lambda _s, d=rough: d)
for _ in range(200):
    ov._tick_graph()
    app.processEvents()
ov.grab().save(os.path.join(OUT, "graph_fixed_with_stutter.png"))
print("\n  wrote graph_fixed_locked110.png and graph_fixed_with_stutter.png")

ov.close_hooks()
print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
