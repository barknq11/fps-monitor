"""Run every test suite and summarise. Usage: python tests\\run_all.py"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SUITES = [
    ("startup + window tracking", "test_startup.py"),
    ("focus, limiter, driver", "test_focus_limiter.py"),
    ("frame timeline backend", "test_fps_backend.py"),
    ("graph animation + cost", "test_graph.py"),
    ("graph scale + stutter", "test_graph2.py"),
    ("burst delivery", "test_graph3.py"),
    ("graph smoothness", "test_smooth.py"),
    ("history coverage", "test_coverage.py"),
    ("overlay, hotkeys, sensors", "test_fixes.py"),
    ("themes + Start Menu", "test_theme_shortcut.py"),
    ("DPI coordinate handling", "test_dpi.py"),
    ("GPU selection + battery", "test_hardware.py"),
]

results = []
for label, name in SUITES:
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        results.append((label, name, None, 0.0, "missing"))
        continue
    t0 = time.perf_counter()
    p = subprocess.run(
        [sys.executable, path], capture_output=True, text=True, cwd=ROOT
    )
    dt = time.perf_counter() - t0
    tail = ""
    for line in reversed(p.stdout.splitlines()):
        if "FAIL" in line:
            tail = line.strip()
            break
    results.append((label, name, p.returncode == 0, dt, tail))
    print(f"{'PASS' if p.returncode == 0 else 'FAIL'}  {label:<28} "
          f"{dt:5.1f}s  {tail}")

print("\n" + "=" * 60)
failed = [r for r in results if r[2] is not True]
print(f"{len(results) - len(failed)}/{len(results)} suites passed")
for label, name, ok, _dt, tail in failed:
    print(f"  {name}: {tail or 'see output'}")
raise SystemExit(1 if failed else 0)
