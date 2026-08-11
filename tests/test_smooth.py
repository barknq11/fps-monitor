"""Measure frame-to-frame smoothness of the graph under bursty delivery."""

import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from fpsmon import config  # noqa: E402
from fpsmon.overlay import Overlay  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview")
os.makedirs(OUT, exist_ok=True)
app = QApplication(sys.argv)
config.bootstrap()
failures = []

WINDOW = 4.0
FT = 8.33          # 120 FPS, as in the screenshots
BURST = 1.0        # PresentMon delivers ~once a second

random.seed(2)
START = time.monotonic()
_state = {"released_until": START}


def bursty_series(seconds: float):
    """Frames exist continuously, but only become VISIBLE once per second.

    Returns EXACTLY the requested duration -- a provider that quietly returns
    more than asked for hides the caller under-requesting, which is precisely
    the bug that left the left half of the graph empty.
    """
    now = time.monotonic()
    # release a new burst every BURST seconds
    while _state["released_until"] + BURST <= now:
        _state["released_until"] += BURST
    visible_end = _state["released_until"]

    out = []
    t = visible_end - seconds
    i = 0
    while t < visible_end:
        ft = FT + random.uniform(-0.3, 0.3)
        if i % 400 == 399:
            ft += random.uniform(12.0, 30.0)      # occasional real hitch
        out.append((t, ft))
        t += ft / 1000.0
        i += 1
    return out


prof = config.load_profile("MangoHud")
prof["position"] = "custom"
prof["custom_x"], prof["custom_y"] = 60, 60
prof["graph_height"] = 70
prof["graph_fps"] = 60

ov = Overlay(prof)
ov.set_series_provider(bursty_series)
ov.set_values({"fps": 120.0, "frametime": 8.33, "gpu_load": 77.0,
               "gpu_temp": 47.0, "gpu_clock": 1817.0, "gpu_power": 64.0,
               "cpu_load": 45.0, "cpu_temp": 68.0, "cpu_clock": 3800,
               "vram_used_gb": 6.8, "ram_used": 21.6})
ov.show()
app.processEvents()

gw = ov._graph_rect[2]

# let the lag estimator settle
t_end = time.monotonic() + 2.5
while time.monotonic() < t_end:
    ov._tick_graph()
    app.processEvents()
    time.sleep(0.004)

print("=== presentation delay ===")
print(f"  settled lag: {ov._lag * 1000:.0f}ms  (delivery cadence {BURST * 1000:.0f}ms)")
if ov._lag < BURST * 0.5:
    failures.append(f"lag {ov._lag:.2f}s too small to cover {BURST:.2f}s bursts")

# ---- measure motion: track the newest point and the scale, frame by frame
print("\n=== frame-to-frame motion over 3 seconds ===")
right_edge = []
scales = []
samples = []
t_end = time.monotonic() + 3.0
last = None
while time.monotonic() < t_end:
    ov._tick_graph()
    app.processEvents()
    pts = ov._graph_points(gw, WINDOW)
    if len(pts) > 5:
        # x of the newest point: should sit at the right edge, always
        right_edge.append(pts[-1][0])
        scales.append(getattr(ov, "_graph_scale", 0))
        # how far a mid-trail point travels between consecutive renders
        mid = pts[len(pts) // 2]
        if last is not None:
            samples.append(abs(mid[1] - last))
        last = mid[1]
    time.sleep(0.004)

gap = gw - min(right_edge)
print(f"  newest point x: min {min(right_edge):.1f}, max {max(right_edge):.1f} "
      f"(graph width {gw})")
print(f"  worst gap at the right edge: {gap:.1f}px")
if gap > 6:
    failures.append(f"right edge empties by {gap:.1f}px between bursts (pop)")

# ---- the LEFT edge must be reached too -----------------------------------
print("\n=== left edge coverage ===")
left = []
t_end = time.monotonic() + 2.0
while time.monotonic() < t_end:
    ov._tick_graph()
    app.processEvents()
    pts = ov._graph_points(gw, WINDOW)
    if len(pts) > 5:
        left.append(min(x for x, _ in pts))
    time.sleep(0.006)
worst_left = max(left)
print(f"  leftmost drawn x: best {min(left):.1f}, worst {worst_left:.1f} "
      f"(0 = left edge, graph width {gw})")
print(f"  window actually covered: "
      f"{(gw - worst_left) / gw * 100:.0f}%")
if worst_left > gw * 0.08:
    failures.append(
        f"trace starts at x={worst_left:.0f} of {gw}: the left "
        f"{worst_left / gw * 100:.0f}% of the graph is empty"
    )

s_min, s_max = min(scales), max(scales)
drift = (s_max - s_min) / max(s_min, 1e-6) * 100
print(f"\n  vertical scale: {s_min:.1f}ms .. {s_max:.1f}ms  ({drift:.1f}% drift)")
if drift > 20:
    failures.append(f"scale still breathing by {drift:.0f}%")

print(f"\n  renders sampled: {len(right_edge)}")

# ---- a burst boundary must not teleport the trail --------------------------
print("\n=== continuity across a burst boundary ===")
print("  (a seamless trail is the PREVIOUS trail translated left; any extra")
print("   change means data appeared or shifted, i.e. a visible pop)")


def val_at(pp, xq):
    best = min(pp, key=lambda q: abs(q[0] - xq))
    return best[1]


prev_pts = None
prev_t = None
residuals = []
t_end = time.monotonic() + 3.0
while time.monotonic() < t_end:
    ov._tick_graph()
    app.processEvents()
    tnow = time.monotonic()
    pts = ov._graph_points(gw, WINDOW)
    if prev_pts and len(pts) > 20 and len(prev_pts) > 20:
        dx = gw * (tnow - prev_t) / WINDOW      # how far it should have moved
        for frac in (0.3, 0.5, 0.7):
            x = gw * frac
            a, b = val_at(pts, x), val_at(prev_pts, x + dx)
            # Skip probes sitting on a stutter spike: the curve is near
            # vertical there, so nearest-point matching across the shifted x
            # is meaningless. Smoothness of the baseline is what is measured.
            if max(a, b) > FT * 1.8:
                continue
            residuals.append(abs(a - b))
    prev_pts, prev_t = pts, tnow
    time.sleep(0.008)

if residuals:
    residuals.sort()
    med = residuals[len(residuals) // 2]
    p99 = residuals[int(len(residuals) * 0.99)]
    print(f"  residual after removing the scroll: median {med:.3f}ms, "
          f"p99 {p99:.3f}ms, worst {residuals[-1]:.3f}ms")
    if p99 > 3.0:
        failures.append(f"trail is not a pure translation (p99 {p99:.2f}ms)")

ov.grab().save(os.path.join(OUT, "graph_seamless.png"))

# ---- prove this test would catch the bug it was written for ---------------
print("\n=== regression guard: re-introduce the old under-request ===")


class UnderRequesting(Overlay):
    """Asks for only `window` seconds, ignoring the render lag (the old bug)."""

    def _tick_graph(self):
        if self._graph_rect is None or not self.isVisible():
            return
        if self._series_provider is not None:
            self._series = self._series_provider(
                float(self.profile.get("graph_seconds", 4.0))
            )
            # The real tick maintains the presentation delay. Without it the
            # render clock never falls behind, so the missing-left-edge bug
            # cannot appear and the guard proves nothing.
            self._update_lag()
            self._gcache = None
        gx, gy, gwv, gh = self._graph_rect
        self.update(gx - 1, gy - 1, gwv + 2, gh + 2)


bad = UnderRequesting(prof)
bad.set_series_provider(bursty_series)
bad.set_values({"fps": 120.0, "frametime": 8.33})
bad.show()
app.processEvents()
t_end = time.monotonic() + 2.5
bad_left = []
while time.monotonic() < t_end:
    bad._tick_graph()
    app.processEvents()
    pts = bad._graph_points(bad._graph_rect[2], WINDOW)
    if len(pts) > 5:
        bad_left.append(min(x for x, _ in pts))
    time.sleep(0.006)
bad_worst = max(bad_left) if bad_left else 0
bw = bad._graph_rect[2]
print(f"  with the old behaviour the trace starts at x={bad_worst:.0f}/{bw} "
      f"-> left {bad_worst / bw * 100:.0f}% empty")
if bad_worst <= bw * 0.08:
    failures.append(
        "the regression guard did NOT reproduce the bug, so this test cannot "
        "prove the fix works"
    )
bad.close_hooks()
bad.hide()

ov.close_hooks()

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
