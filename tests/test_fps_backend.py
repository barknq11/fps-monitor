"""Validate the frame timeline against the REAL PresentMon data captured
in logs/presentmon_diag.txt (CPUStartTime path + dwm exclusion)."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpsmon import fps as fpsmod  # noqa: E402

failures = []

# Real rows taken from the diagnostic report (dwm.exe, CPUStartTime in ms).
REAL = [
    (2.2438, 12.2980),
    (14.5418, 6.3823),
    (20.9241, 9.1787),
    (30.1028, 16.8316),
    (46.9344, 10.5179),
]

print("=== CPUStartTime semantics (from the real capture) ===")
for i in range(len(REAL) - 1):
    delta = REAL[i + 1][0] - REAL[i][0]
    ft = REAL[i][1]
    print(f"  CPUStartTime delta {delta:8.4f}  vs FrameTime {ft:8.4f}"
          f"   match={abs(delta - ft) < 1e-3}")
    if abs(delta - ft) > 1e-3:
        failures.append("CPUStartTime is not in milliseconds after all")

print("\n=== stream using PresentMon timestamps ===")
st = fpsmod._Stream("game.exe", 1, 5.5)
# feed as one burst, exactly as the pipe delivers it
for cpu_ms, ft in REAL:
    st.add(ft, cpu_ms)
series = st.series(5.0)
print(f"  frames: {len(series)}")
gaps = [
    round((series[i][0] - series[i - 1][0]) * 1000, 3)
    for i in range(1, len(series))
]
print(f"  spacing between frames (ms): {gaps}")
expected = [round(REAL[i][1], 3) for i in range(len(REAL) - 1)]
print(f"  expected (the FrameTimes):   {expected}")
if any(abs(a - b) > 0.05 for a, b in zip(gaps, expected)):
    failures.append(f"spacing wrong: {gaps} != {expected}")
if len({round(ts, 6) for ts, _ in series}) != len(series):
    failures.append("frames still collapsed onto shared timestamps")

print("\n=== a whole burst must not collapse ===")
st2 = fpsmod._Stream("game.exe", 2, 5.5)
cpu = 0.0
for i in range(296):          # the largest burst actually observed
    ft = 8.65               # the game's real median from the capture
    cpu += ft
    st2.add(ft, cpu)
s2 = st2.series(5.0)
distinct = len({round(ts, 6) for ts, _ in s2})
span = (s2[-1][0] - s2[0][0]) if s2 else 0
print(f"  296 rows delivered at one instant -> {distinct} distinct timestamps")
print(f"  spanning {span:.2f}s (should be ~{295 * 8.65 / 1000:.2f}s)")
if distinct < len(s2):
    failures.append("burst still collapses")
if abs(span - 295 * 8.65 / 1000) > 0.1:
    failures.append(f"burst span wrong: {span:.2f}s")

print("\n=== dwm.exe must be excluded ===")
print(f"  excluded list: {fpsmod.EXCLUDED_PROCESSES}")
if "dwm.exe" not in [e.lower() for e in fpsmod.EXCLUDED_PROCESSES]:
    failures.append("dwm.exe not excluded -- it out-presents the game")
print("  (capture showed dwm.exe 2062 frames vs the game's 1248, so the")
print("   'busiest process' fallback would have reported dwm's frame rate)")

print("\n=== stale ETW session handling ===")
print(f"  sessions cleaned at startup: {fpsmod.STALE_SESSIONS}")
if "FPSMonitorDiag" not in fpsmod.STALE_SESSIONS:
    failures.append("diagnostic session not cleaned up on start")

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
