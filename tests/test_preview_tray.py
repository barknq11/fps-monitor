"""Live overlay preview and the numeric tray icon."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PREVIEW_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview"
)
os.makedirs(PREVIEW_DIR, exist_ok=True)

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from fpsmon import config  # noqa: E402
from fpsmon.app import app_icon, number_icon  # noqa: E402
from fpsmon.overlay import Overlay  # noqa: E402
from fpsmon.settings_ui import SettingsWindow  # noqa: E402
from fpsmon.widgets import OverlayPreview  # noqa: E402

app = QApplication(sys.argv)
config.bootstrap()
failures = []

# ============================================== embedded overlay
print("=== embedded overlay is a child widget, not a window ===")
prof = config.load_profile("MangoHud")
# parented, exactly as OverlayPreview builds it - an unparented widget is a
# window by definition, so testing it without a parent proves nothing
host = QWidget()
emb = Overlay(prof, parent=host, embedded=True)
top = Overlay(prof)
print(f"  embedded.isWindow(): {emb.isWindow()}   (should be False)")
print(f"  top-level.isWindow(): {top.isWindow()}  (should be True)")
if emb.isWindow():
    failures.append("the embedded overlay is still a top-level window")
if not top.isWindow():
    failures.append("the real overlay stopped being a window")

print(f"  embedded installed a foreground hook: "
      f"{getattr(emb, '_winevent_hook', None) is not None}")
if getattr(emb, "_winevent_hook", None) is not None:
    failures.append("the preview installed a system-wide window hook")
print(f"  embedded has a raise timer: {hasattr(emb, '_raise_timer')}")
if hasattr(emb, "_raise_timer"):
    failures.append("the preview is competing for z-order")

emb.set_values(OverlayPreview.SAMPLE)
app.processEvents()
print(f"  it still lays out and sizes itself: {emb.width()}x{emb.height()}")
if emb.width() < 40 or emb.height() < 20:
    failures.append("the embedded overlay did not lay out")
top.close_hooks()

# ============================================== preview widget
print("\n=== preview widget ===")
pv = OverlayPreview(config.load_profile("Default"))
app.processEvents()
print(f"  size: {pv.overlay.width()}x{pv.overlay.height()}")

series = pv._fake_series(4.0)
print(f"  synthetic stream: {len(series)} frames over 4s")
if len(series) < 100:
    failures.append(f"only {len(series)} sample frames, graph will look sparse")
fts = [ft for _t, ft in series]
print(f"  frame times {min(fts):.2f}..{max(fts):.2f} ms "
      f"(includes deliberate hitches)")
if max(fts) < 12:
    failures.append("the sample stream has no hitches, so spikes never show")

before = (pv.overlay.width(), pv.overlay.height())
big = config.load_profile("Full telemetry")
pv.refresh(big)
app.processEvents()
after = (pv.overlay.width(), pv.overlay.height())
print(f"  switching profile resizes the preview: {before} -> {after}")
if before == after:
    failures.append("the preview did not react to a profile change")
pv.stop()

# ============================================== in the settings window
print("\n=== previews inside Settings ===")
w = SettingsWindow(config.load_profile("MangoHud"), lambda: "status")
w.resize(1000, 760)
w.show()
app.processEvents()
print(f"  preview strips created: {len(w._previews)}")
if len(w._previews) != 2:
    failures.append(f"expected a preview on 2 pages, got {len(w._previews)}")

import time  # noqa: E402

for name in ("Appearance", "Graph"):
    idx = next(i for i in range(w.nav.count()) if w.nav.item(i).text() == name)
    w.nav.setCurrentRow(idx)
    # let the graph clock run: it renders behind real time by a measured
    # delay, so a single processEvents leaves it with nothing to draw
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    w.grab().save(os.path.join(PREVIEW_DIR, f"preview_{name.lower()}.png"))
    print(f"  captured {name} page")

# the preview graph must actually have data, not sit on "waiting for frames"
gp = w._previews[1].overlay
if gp._graph_rect:
    pts = gp._graph_points(gp._graph_rect[2], 4.0)
    print(f"  preview graph points: {len(pts)}")
    if len(pts) < 20:
        failures.append(
            f"the preview graph only has {len(pts)} points, so it shows "
            f"'waiting for frames' instead of animating"
        )
else:
    print("  graph disabled in this profile, nothing to check")

# a settings change must reach the preview
w.nav.setCurrentRow(
    next(i for i in range(w.nav.count()) if w.nav.item(i).text() == "Appearance")
)
app.processEvents()
old = w._previews[0].overlay.profile.get("font_size")
w.font_size.setValue(int(old) + 8)
app.processEvents()
new = w._previews[0].overlay.profile.get("font_size")
print(f"  font size {old} -> {new} propagated to the preview: {old != new}")
if old == new:
    failures.append("changing a setting did not update the preview")

# ============================================== tray icon
print("\n=== tray icon ===")
for value in ("7", "60", "144", "1000", ""):
    icon = number_icon(value) if value else app_icon()
    sizes = icon.availableSizes()
    pm = icon.pixmap(16, 16)
    label = value or "(logo fallback)"
    print(f"  {label:<16} null={icon.isNull()}  16px pixmap: "
          f"{pm.width()}x{pm.height()}")
    if icon.isNull() or pm.isNull():
        failures.append(f"tray icon for {label} is empty")

# the digits must actually be painted, not just a background
img = number_icon("144").pixmap(64, 64).toImage()
colours = {img.pixelColor(x, y).name()
           for x in range(0, 64, 4) for y in range(0, 64, 4)}
print(f"  distinct colours in a rendered '144': {len(colours)}")
if len(colours) < 3:
    failures.append("the tray number does not appear to have been drawn")

strip = number_icon("144", "#3ddc84").pixmap(64, 64)
strip.save(os.path.join(PREVIEW_DIR, "tray_144.png"))
number_icon("96", "#7ed0ff").pixmap(64, 64).save(
    os.path.join(PREVIEW_DIR, "tray_96.png")
)
print("  wrote preview/tray_144.png and tray_96.png")

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
