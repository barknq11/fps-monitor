"""Render the overlay and settings window offscreen to PNG for visual check."""

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fpsmon import config  # noqa: E402
from fpsmon.overlay import Overlay  # noqa: E402
from fpsmon.settings_ui import SettingsWindow  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview")
os.makedirs(OUT, exist_ok=True)

FAKE = {
    "fps": 143.0, "fps_1low": 96.0, "fps_01low": 71.0,
    "frametime": 6.99, "frametime_max": 18.4, "frametime_med": 6.80,
    "frametime_jitter": 0.62, "stutter_pct": 1.8, "app": "cs2.exe",
    "cpu_load": 62.0, "cpu_load_max": 94.0, "cpu_temp": 78.0,
    "cpu_clock": 4125, "cpu_clock_avg": 3980, "cpu_power": 88.0, "cpu_volt": 1.38,
    "gpu_load": 99.0, "gpu_temp": 71.0, "gpu_hotspot": 91.0, "gpu_mem_temp": 74.0,
    "gpu_clock": 2871.0, "gpu_mem_clock": 2518.0, "gpu_power": 178.0,
    "gpu_fan_rpm": 1840.0, "gpu_fan_pct": 62.0, "gpu_volt": 1.05,
    "vram_used": 9134.0, "vram_total": 16304.0, "vram_pct": 56.0,
    "vram_used_gb": 8.92, "vram_total_gb": 15.92, "vram_free_gb": 7.00,
    "gpu_mem_load": 44.0,
    "ram_load": 71.0, "ram_used": 22.6, "ram_free": 9.3, "ram_total": 31.9,
}


def fake_frametimes(n: int = 400) -> list[float]:
    """A realistic 7ms baseline with drift plus a few stutter spikes."""
    random.seed(7)
    out = []
    for i in range(n):
        base = 6.9 + 0.35 * math.sin(i / 22.0) + random.uniform(-0.35, 0.35)
        if i in (90, 91, 210, 300, 301, 302):
            base += random.uniform(9.0, 26.0)   # micro-stutter
        out.append(round(base, 3))
    return out


app = QApplication(sys.argv)
config.bootstrap()
history = fake_frametimes()

for name in config.list_profiles():
    prof = config.load_profile(name)
    prof["position"] = "custom"
    prof["custom_x"], prof["custom_y"] = 60, 60
    ov = Overlay(prof)
    ov.set_values(FAKE, history)
    ov.show()
    app.processEvents()
    path = os.path.join(OUT, f"overlay_{name.replace(' ', '_')}.png")
    # Composite over a dark backdrop: profiles with a transparent background
    # are invisible against the raw grab, which is not how they look in game.
    shot = ov.grab()
    canvas = QPixmap(shot.width() + 24, shot.height() + 24)
    canvas.fill(QColor("#1b1f24"))
    pnt = QPainter(canvas)
    pnt.drawPixmap(QPoint(12, 12), shot)
    pnt.end()
    canvas.save(path)
    print(f"{name:<22} {ov.width()}x{ov.height()}  graph={prof.get('graph_enabled')}")
    ov.close_hooks()
    ov.hide()

s = SettingsWindow(config.load_profile("Default"), lambda: "status line")
s.resize(780, 700)
s.show()
app.processEvents()
for i in range(s.nav.count()):
    s.nav.setCurrentRow(i)
    app.processEvents()
    name = s.nav.item(i).text().lower().replace(" ", "_")
    s.grab().save(os.path.join(OUT, f"settings_{i}_{name}.png"))
print("done")
