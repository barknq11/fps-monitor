"""Startup cost after deferring the slow backends, plus window tracking."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpsmon import focus, sensors  # noqa: E402

failures = []

print("=== sensor backend construction ===")
t0 = time.perf_counter()
s_defer = sensors.SensorBackend(interval=0.5, defer=True)
d_defer = time.perf_counter() - t0
print(f"  deferred:  {d_defer * 1000:7.0f} ms  (was ~3060 ms inline)")
if d_defer > 0.3:
    failures.append(f"deferred construction still costs {d_defer * 1000:.0f}ms")

t0 = time.perf_counter()
s_now = sensors.SensorBackend(interval=0.5, defer=False)
d_now = time.perf_counter() - t0
print(f"  inline:    {d_now * 1000:7.0f} ms  (motherboard+controller now off)")
print(f"  RAM total known immediately: {s_defer.ram_total_gb} GB")
if s_defer.ram_total_gb <= 0:
    failures.append("static info not available before hardware opens")

print("\n  starting deferred backend and waiting for first readings...")
t0 = time.perf_counter()
s_defer.start()
vals = {}
while time.perf_counter() - t0 < 12:
    vals = s_defer.read()
    if vals.get("gpu_temp") or vals.get("cpu_load"):
        break
    time.sleep(0.05)
print(f"  first real reading after {(time.perf_counter() - t0) * 1000:.0f} ms")
print(f"  cpu: {s_defer.cpu_name} | gpu: {s_defer.gpu_name}")
print(f"  sample: gpu_temp={vals.get('gpu_temp')} cpu_load={vals.get('cpu_load')}")
if not (vals.get("gpu_temp") or vals.get("cpu_load")):
    failures.append("deferred backend produced no readings")
s_defer.stop()
s_now.stop()

# ==================================================== window tracking
print("\n=== finding a window for a running process (focus aside) ===")
import psutil  # noqa: E402

target = None
for p in psutil.process_iter(["pid", "name"]):
    if (p.info.get("name") or "").lower() in ("explorer.exe",):
        target = p.info["pid"]
        break
if target:
    win = focus.window_for_pid(target)
    if win:
        print(f"  explorer.exe (pid {target}) -> "
              f"{win.width}x{win.height} at ({win.x},{win.y}) "
              f"fullscreen={win.fullscreen}")
        print(f"  title: {win.title[:60]!r}")
    else:
        print(f"  explorer.exe (pid {target}) has no qualifying window "
              f"(expected if the desktop is the only one)")

print("\n=== game selection ignores non-games ===")
cands = [(111, "chrome.exe"), (222, "dwm.exe"), (333, "steam.exe")]
got = focus.find_game_window(cands)
print(f"  candidates {cands} -> {got}")
if got is not None:
    failures.append("a non-game was picked as the game window")

print("\n=== a real window is found for a real pid ===")
own = os.getpid()
mine = focus.window_for_pid(own)
print(f"  this console process ({own}) -> {mine is not None}")

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
