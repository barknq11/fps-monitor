"""Multi-GPU selection and battery metrics.

Neither can be fully verified on this machine: it has one GPU and no battery.
The selection logic is tested against a fake hardware list so the behaviour is
still pinned down, and the real backend is checked for what it does report.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psutil  # noqa: E402

from fpsmon import metrics as M, sensors  # noqa: E402

failures = []

print("=== this machine ===")
b = sensors.SensorBackend(defer=False)
print(f"  GPUs found: {b.gpus}")
print(f"  reporting:  {b.gpu_name}")
print(f"  battery:    {b.has_battery}")
print(f"  psutil says: {psutil.sensors_battery()}")
if not b.gpus:
    failures.append("no GPU enumerated at all")

# ------------------------------------------------------- selection logic
print("\n=== GPU selection (fake two-GPU laptop) ===")
fake = sensors.SensorBackend(defer=True)
fake.gpus = [(1, "Intel UHD Graphics"), (3, "NVIDIA GeForce RTX 4070")]

fake.set_gpu(None)
print(f"  default (None)   -> {fake.gpu_name}")
if fake.gpu_name != "Intel UHD Graphics":
    failures.append("default should be the first enumerated GPU")

fake.set_gpu(3)
print(f"  select index 3   -> {fake.gpu_name}")
if fake.gpu_name != "NVIDIA GeForce RTX 4070":
    failures.append("selecting index 3 did not switch GPU")

fake.set_gpu(99)
print(f"  invalid index 99 -> {fake.gpu_name}  (falls back, does not crash)")
if not fake.gpu_name:
    failures.append("invalid index produced no name")

fake.gpus = []
fake.set_gpu(None)
print(f"  no GPUs at all   -> {fake.gpu_name!r}")
if fake.gpu_name != "GPU":
    failures.append("empty GPU list should give the placeholder name")

# ------------------------------------------------------- battery metrics
print("\n=== battery metrics are registered ===")
for mid in ("batt_pct", "batt_minutes", "batt_plugged"):
    m = M.BY_ID.get(mid)
    ok = m is not None
    print(f"  {mid:<14} {'ok' if ok else 'MISSING':<8} "
          f"group={m.group if m else '-'}  unit={m.unit if m else '-'}")
    if not ok:
        failures.append(f"{mid} not in the metric registry")
    elif m.group != "BATTERY":
        failures.append(f"{mid} is in group {m.group}, expected BATTERY")

if "BATTERY" not in M.GROUPS:
    failures.append("BATTERY missing from the group list")
print(f"  groups: {M.GROUPS}")

print("\n=== battery formatting (simulated laptop values) ===")
for mid, value, expect in (
    ("batt_pct", 87.4, "87"),
    ("batt_minutes", 143.0, "143"),
    ("batt_plugged", 1.0, "1"),
):
    m = M.BY_ID[mid]
    got = M.format_value(m, value)
    state = M.state_for(m, value)
    print(f"  {mid:<14} {value} -> {got!r}{m.unit}  state={state}")
    if got != expect:
        failures.append(f"{mid} formatted {got!r}, expected {expect!r}")

low = M.state_for(M.BY_ID["batt_pct"], 8.0)
print(f"  8% charge -> state {low}  (lower is worse for a battery)")
if low != "crit":
    failures.append(f"8% battery should read critical, got {low}")

print("\n=== live sample: do battery keys appear? ===")
b.start()
import time  # noqa: E402

time.sleep(2.5)
vals = b.read()
present = [k for k in ("batt_pct", "batt_minutes", "batt_plugged") if k in vals]
print(f"  battery keys in the sample: {present or 'none'}")
if b.has_battery and not present:
    failures.append("battery present but no battery keys sampled")
if not b.has_battery and present:
    failures.append("no battery, yet battery keys were emitted")
print(f"  gpu_temp={vals.get('gpu_temp')}  cpu_load={vals.get('cpu_load')}")
b.stop()

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
print("  NOTE: multi-GPU and battery paths are unverified on this hardware")
