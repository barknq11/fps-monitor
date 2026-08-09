"""Verify the frame-time graph animates smoothly on its own clock."""

import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fpsmon import config  # noqa: E402
from fpsmon.overlay import Overlay  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview")
os.makedirs(OUT, exist_ok=True)

app = QApplication(sys.argv)
config.bootstrap()
failures = []

START = time.monotonic()
random.seed(11)


def live_series(seconds: float):
    """Timestamped frames as PresentMon would deliver them (144 FPS + stutter)."""
    now = time.monotonic()
    out = []
    t = now - seconds
    i = 0
    while t < now:
        ft = 6.94 + 0.45 * math.sin((t - START) * 3.0) + random.uniform(-0.25, 0.25)
        if i % 47 == 0 and i:
            ft += random.uniform(9.0, 22.0)
        out.append((t, ft))
        t += ft / 1000.0
        i += 1
    return out


class CountingOverlay(Overlay):
    """Subclass so the paintEvent override is registered with Qt properly."""

    def __init__(self, profile):
        self.paints = 0
        self.partial = 0
        self.full = 0
        super().__init__(profile)

    def paintEvent(self, event):  # noqa: N802
        self.paints += 1
        gr = self._graph_rect
        if gr is not None and event.rect().top() >= gr[1] - 2:
            self.partial += 1
        else:
            self.full += 1
        super().paintEvent(event)


prof = config.load_profile("MangoHud")
prof["position"] = "custom"
prof["custom_x"], prof["custom_y"] = 60, 60
prof["graph_fps"] = 60
prof["graph_height"] = 70

ov = CountingOverlay(prof)
ov.set_series_provider(live_series)
ov.set_values({
    "fps": 144.0, "frametime": 6.94, "gpu_load": 99.0, "gpu_temp": 71.0,
    "gpu_clock": 2871.0, "gpu_power": 178.0, "cpu_load": 62.0,
    "cpu_temp": 78.0, "cpu_clock": 4125, "vram_used_gb": 8.92, "ram_used": 22.6,
})
ov.show()
app.processEvents()

print("=== graph timer ===")
print(f"  active: {ov._graph_timer.isActive()} | interval: {ov._graph_timer.interval()} ms")
if not ov._graph_timer.isActive():
    failures.append("graph timer is not running")

# ---------------------------------------------------------------- motion
# Freeze the data: with a fixed snapshot, any x movement must come from the
# time-based mapping, which is exactly the smooth-scroll behaviour under test.
print("\n=== trail motion (frozen data) ===")
frozen = live_series(4.0)
mid_ts = frozen[len(frozen) // 2][0]
ov.set_series_provider(lambda _s, f=frozen: f)
ov._series = frozen
gw = ov._graph_rect[2]


def x_of_mid():
    now = time.monotonic()
    return gw * (1.0 - (now - mid_ts) / float(prof["graph_seconds"]))


x0 = x_of_mid()
shots = []


def grab(tag):
    p = os.path.join(OUT, f"graph_anim_{tag}.png")
    ov.grab().save(p)
    shots.append(os.path.basename(p))


for i, d in enumerate((100, 450, 850)):
    QTimer.singleShot(d, lambda t=i: grab(t))

t0 = time.perf_counter()


def finish():
    elapsed = time.perf_counter() - t0
    x1 = x_of_mid()
    moved = x0 - x1
    expected = gw * elapsed / float(prof["graph_seconds"])
    print(f"  a fixed frame moved {moved:.1f}px left over {elapsed:.2f}s")
    print(f"  expected for time-based scrolling: {expected:.1f}px")
    if moved < expected * 0.7:
        failures.append(f"trail is not scrolling with time ({moved:.1f}px)")

    hz = ov.paints / elapsed
    print("\n=== repaints ===")
    print(f"  {ov.paints} paints in {elapsed:.2f}s  ->  {hz:.0f} Hz")
    print(f"  partial (graph strip only): {ov.partial}")
    print(f"  full window repaints:       {ov.full}")
    if hz < 25:
        failures.append(f"graph only reached {hz:.0f} Hz, expected ~60")
    if ov.partial < ov.full:
        failures.append("graph is forcing full-window repaints (expensive)")
    print("\n  frames written:", shots)
    ov.close_hooks()
    app.quit()


QTimer.singleShot(1200, finish)
app.exec()

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
