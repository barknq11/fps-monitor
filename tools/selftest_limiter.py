"""
Elevated self-test for the RTSS frame limiter.

Confirms the whole path works: set a cap, save it, read it back from a fresh
load, and restore the original. Uses a throwaway profile name that no game
uses, so no real game settings are touched.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fpsmon import limiter  # noqa: E402

SCRATCH = "fpsmon_selftest.exe"


def main() -> int:
    lim = limiter.FpsLimiter()
    print("RTSS frame limiter self-test")
    print("=" * 58)
    print(f"elevated:          {limiter.is_elevated()}")
    print(f"RTSS folder:       {lim.dir}")
    print(f"API loaded:        {lim.available}  {lim.api.error or ''}")
    print(f"RTSS running:      {limiter.rtss_running()}")
    print(f"profiles writable: {limiter.profiles_writable(lim.dir)}")
    print()

    if not lim.available:
        print("FAIL: RTSS API not available.")
        return 1
    if not limiter.rtss_running():
        print("FAIL: RTSS is not running. Start it and run this again.")
        return 1
    if not limiter.profiles_writable(lim.dir):
        print("FAIL: RTSS profiles are not writable.")
        print("      Run this as Administrator (right-click -> Run as admin).")
        return 1

    print("--- real profiles (read only) ---")
    d = lim.profiles_dir()
    if d:
        for f in sorted(os.listdir(d))[:8]:
            if f.lower().endswith(".cfg"):
                name = f[:-4]
                print(f"  {name:<34} {lim.get_limit(name)}")
    print(f"  {'(Global)':<34} {lim.get_limit(None)}")

    print(f"\n--- round trip on {SCRATCH} ---")
    original = lim.get_limit(SCRATCH)
    print(f"  original: {original}")
    failures = []
    for target in (144, 60, 30, 0):
        st = lim.set_limit(SCRATCH, target)
        got = lim.get_limit(SCRATCH)
        ok = (got == target) and st.ok
        print(f"  set {target:>4} -> {str(got):<5} {'OK' if ok else 'FAILED'}"
              f"   {st.message}")
        if not ok:
            failures.append(target)

    lim.set_limit(SCRATCH, original if original is not None else 0)
    print(f"  restored: {lim.get_limit(SCRATCH)}")

    scratch_cfg = os.path.join(d, f"{SCRATCH}.cfg") if d else None
    if scratch_cfg and os.path.exists(scratch_cfg):
        try:
            os.remove(scratch_cfg)
            print(f"  removed the scratch profile {os.path.basename(scratch_cfg)}")
        except Exception as exc:
            print(f"  could not remove scratch profile: {exc}")

    print("\n" + "=" * 58)
    if failures:
        print(f"FAILED for: {failures}")
        return 1
    print("PASS - the limiter works. Set a cap from the FPS limiter page.")
    return 0


if __name__ == "__main__":
    rc = main()
    input("\nPress Enter to close...")
    raise SystemExit(rc)
