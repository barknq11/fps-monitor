"""Physical/logical coordinate conversion for window anchoring.

Round trip: place a Qt window at a known LOGICAL position, read its rect back
through Win32 (PHYSICAL), convert, and check the original position is
recovered. If the conversion is missing or wrong the error equals the display
scaling factor, which is what put the overlay a quarter of a screen away from
windowed games.
"""

import ctypes
import os
import sys
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from fpsmon import focus  # noqa: E402

app = QApplication(sys.argv)
failures = []

print("=== displays ===")
scaled = False
for i, s in enumerate(QGuiApplication.screens()):
    g = s.geometry()
    dpr = s.devicePixelRatio()
    scaled |= dpr != 1.0
    print(f"  {s.name():<14} logical {g.width()}x{g.height()} at "
          f"({g.x()},{g.y()})  scale {dpr:g}x")
print(f"  any scaled display: {scaled}")

# ------------------------------------------------------------------ round trip
print("\n=== round trip: logical -> physical -> logical ===")
user32 = ctypes.windll.user32

results = []
for want_x, want_y, want_w, want_h in (
    (300, 200, 640, 480),
    (120, 90, 800, 600),
):
    w = QWidget()
    w.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    w.resize(want_w, want_h)
    w.move(want_x, want_y)
    w.show()
    app.processEvents()

    hwnd = int(w.winId())
    rc = wintypes.RECT()
    user32.GetClientRect(ctypes.c_void_p(hwnd), ctypes.byref(rc))
    pt = wintypes.POINT(rc.left, rc.top)
    user32.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(pt))

    fg = focus.Foreground(hwnd=hwnd, pid=os.getpid(), exe="test.exe")
    fg.x, fg.y = int(pt.x), int(pt.y)
    fg.width = int(rc.right - rc.left)
    fg.height = int(rc.bottom - rc.top)

    got = focus.to_logical(fg)
    print(f"\n  asked Qt for      ({want_x},{want_y}) {want_w}x{want_h}")
    print(f"  Win32 reports     ({fg.x},{fg.y}) {fg.width}x{fg.height}   <- physical")
    print(f"  converted back    {got}")

    dx, dy = abs(got[0] - want_x), abs(got[1] - want_y)
    dw, dh = abs(got[2] - want_w), abs(got[3] - want_h)
    print(f"  error             x{dx} y{dy} w{dw} h{dh} px")
    results.append((dx, dy, dw, dh))
    if max(dx, dy) > 2:
        failures.append(f"position off by ({dx},{dy}) px after conversion")
    if max(dw, dh) > 2:
        failures.append(f"size off by ({dw},{dh}) px after conversion")

    # what the old code would have done: use the physical rect directly
    raw_dx, raw_dy = abs(fg.x - want_x), abs(fg.y - want_y)
    print(f"  without converting, the overlay would land {raw_dx},{raw_dy} px "
          f"from the window")
    w.close()

# ------------------------------------------------------- anchor_rect is logical
print("\n=== anchor_rect returns logical coordinates ===")
screen = QGuiApplication.primaryScreen().geometry()
screen_geo = (screen.x(), screen.y(), screen.width(), screen.height())

# a real window, so the windowed branch is genuinely exercised
probe = QWidget()
probe.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
probe.resize(700, 500)
probe.move(250, 150)
probe.show()
app.processEvents()
phwnd = int(probe.winId())
rc = wintypes.RECT()
user32.GetClientRect(ctypes.c_void_p(phwnd), ctypes.byref(rc))
pt = wintypes.POINT(rc.left, rc.top)
user32.ClientToScreen(ctypes.c_void_p(phwnd), ctypes.byref(pt))
windowed = focus.Foreground(hwnd=phwnd, pid=os.getpid(), exe="g.exe")
windowed.x, windowed.y = int(pt.x), int(pt.y)
windowed.width = int(rc.right - rc.left)
windowed.height = int(rc.bottom - rc.top)

got_win = focus.anchor_rect(windowed, screen_geo)
print(f"  windowed  -> {got_win}  (window is at logical 250,150 700x500)")
if abs(got_win[0] - 250) > 2 or abs(got_win[1] - 150) > 2:
    failures.append(f"windowed anchor {got_win} is not the window's logical rect")
if got_win == screen_geo:
    failures.append("windowed anchor fell back to the screen")
probe.close()

full = focus.Foreground(hwnd=0, pid=1, exe="g.exe", x=0, y=0,
                        width=9999, height=9999, fullscreen=True)
got_full = focus.anchor_rect(full, screen_geo)
print(f"  fullscreen         -> {got_full}  (should be the Qt screen)")
if got_full != screen_geo:
    failures.append("fullscreen anchor is not the Qt screen rect")

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
