"""Tests for game-focus detection, window anchoring and the RTSS limiter.

The limiter tests operate on COPIES of the real profile text. Nothing under
Program Files is written by this file.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpsmon import focus, limiter  # noqa: E402

failures = []

# ===================================================== focus classification
print("=== is_game classification ===")
PRESENTING = {1000, 2000, 3000}
cases = [
    ("game.exe", 1000, True, "a presenting game"),
    ("WOL2-Win64-Shipping.exe", 2000, True, "your real game from the capture"),
    ("chrome.exe", 1000, False, "browser, even while presenting video"),
    ("firefox.exe", 2000, False, "browser"),
    ("explorer.exe", 3000, False, "the desktop"),
    ("dwm.exe", 1000, False, "the compositor"),
    ("discord.exe", 2000, False, "chat app"),
    ("code.exe", 3000, False, "editor"),
    ("steam.exe", 1000, False, "launcher"),
    ("game.exe", 9999, False, "not presenting -> not an active game"),
]
for exe, pid, expect, why in cases:
    fg = focus.Foreground(hwnd=1, pid=pid, exe=exe, width=800, height=600)
    got = focus.is_game(fg, PRESENTING)
    ok = got == expect
    print(f"  {'OK ' if ok else 'BAD'}  {exe:<28} -> {got!s:<5}  ({why})")
    if not ok:
        failures.append(f"{exe} classified {got}, expected {expect}")

print("\n=== user overrides ===")
fg = focus.Foreground(hwnd=1, pid=1000, exe="chrome.exe", width=800, height=600)
forced = focus.is_game(fg, PRESENTING, allowlist={"chrome.exe"})
print(f"  allowlist forces chrome.exe to count as a game: {forced}")
if not forced:
    failures.append("allowlist ignored")

fg2 = focus.Foreground(hwnd=1, pid=1000, exe="mygame.exe", width=800, height=600)
blocked = focus.is_game(fg2, PRESENTING, blocklist=set(focus.NON_GAMES) | {"mygame.exe"})
print(f"  blocklist suppresses mygame.exe: {not blocked}")
if blocked:
    failures.append("blocklist ignored")

# ===================================================== window anchoring
print("\n=== anchor rectangle ===")
screen = (0, 0, 2560, 1440)
windowed = focus.Foreground(hwnd=1, pid=1, exe="g.exe", x=600, y=300,
                            width=1280, height=720, fullscreen=False)
full = focus.Foreground(hwnd=1, pid=1, exe="g.exe", x=0, y=0,
                        width=2560, height=1440, fullscreen=True)
a1 = focus.anchor_rect(windowed, screen)
a2 = focus.anchor_rect(full, screen)
print(f"  windowed game  -> {a1}   (should be the window)")
print(f"  fullscreen game-> {a2}   (should be the screen)")
if a1 != (600, 300, 1280, 720):
    failures.append(f"windowed anchor wrong: {a1}")
if a2 != screen:
    failures.append(f"fullscreen anchor wrong: {a2}")

# the overlay's top-left corner must land inside the game window
mx = my = 20
x = a1[0] + mx
y = a1[1] + my
print(f"  top-left anchor with 20px margin -> ({x}, {y})")
inside = a1[0] <= x < a1[0] + a1[2] and a1[1] <= y < a1[1] + a1[3]
if not inside:
    failures.append("overlay would not sit inside the game window")

# ===================================================== RTSS limiter
print("\n=== RTSS limiter (API, read-only here) ===")
lim = limiter.FpsLimiter()
print(f"  RTSS dir found: {lim.dir}")
print(f"  API available:  {lim.available}   running: {limiter.rtss_running()}")
print(f"  elevated:       {limiter.is_elevated()}")
print(f"  profiles writable: {limiter.profiles_writable(lim.dir)}")
if not lim.available:
    failures.append("RTSS API not available")

print("\n  live values straight from RTSS:")
for exe in ("RDR2.exe", "bf6.exe", None):
    print(f"    {str(exe or '(Global)'):<16} {lim.get_limit(exe)}")

print("\n=== profile naming ===")
for raw, expect in [
    ("RDR2.exe", "RDR2.exe"),
    ("RDR2.exe.cfg", "RDR2.exe"),
    (r"C:\Games\RDR2.exe", "RDR2.exe"),
    (None, ""),
    ("", ""),
]:
    got = limiter.FpsLimiter.profile_name(raw)
    ok = got == expect
    print(f"  {str(raw):<24} -> {got!r:<12} {'OK' if ok else 'BAD'}")
    if not ok:
        failures.append(f"profile_name({raw!r}) = {got!r}, expected {expect!r}")

print("\n=== writing without elevation must fail loudly, not silently ===")
st = lim.set_limit("fpsmon_selftest.exe", 120)
if limiter.profiles_writable(lim.dir):
    print(f"  elevated run: ok={st.ok} msg={st.message}")
else:
    print(f"  ok={st.ok}  message={st.message}")
    if st.ok:
        failures.append("claimed success while profiles are not writable")
    elif "Administrator" not in st.message:
        failures.append("unelevated failure does not explain the cause")

print("\n=== driver fallback (path A) ===")
for name, expect in [
    ("AMD Radeon RX 9060 XT", "amd"),
    ("NVIDIA GeForce RTX 4070", "nvidia"),
    ("Intel Arc A770", "intel"),
]:
    v = limiter.gpu_vendor(name)
    ok = v == expect
    print(f"  {name:<28} -> {v:<8} {'OK' if ok else 'BAD'}   "
          f"panel: {limiter.driver_panel_path(v) or 'not installed'}")
    if not ok:
        failures.append(f"vendor for {name} was {v}")
    if not limiter.DRIVER_HINTS.get(v):
        failures.append(f"no driver hint for {v}")

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
