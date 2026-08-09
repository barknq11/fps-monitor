"""
Entry point.  Re-launches itself elevated so PresentMon (ETW) and the
LibreHardwareMonitor ring0 driver can provide FPS and CPU temperature.

Pass --no-elevate to skip the UAC prompt (sensors still work, FPS will not).
"""

from __future__ import annotations

import ctypes
import os
import sys


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_elevated() -> int:
    params = " ".join(f'"{a}"' for a in sys.argv)
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, os.path.dirname(os.path.abspath(__file__)), 1
    )
    return 0 if rc > 32 else 1


def selftest() -> int:
    """Verify a packaged build can find everything it needs. --selftest"""
    from fpsmon import paths

    ok = True
    print("FPS Monitor self-test")
    print("=" * 52)
    print(f"frozen:       {paths.FROZEN}")
    print(f"executable:   {sys.executable}")
    print(f"resource dir: {paths.resource_dir()}")
    print(f"data dir:     {paths.data_dir()}")
    print(f"elevated:     {is_admin()}")

    print("\nbundled resources:")
    for rel in (
        os.path.join("vendor", "PresentMon.exe"),
        os.path.join("vendor", "LibreHardwareMonitorLib.dll"),
        os.path.join("vendor", "HidSharp.dll"),
        os.path.join("assets", "icon.ico"),
    ):
        p = paths.resource(rel)
        exists = os.path.exists(p)
        ok &= exists
        print(f"  {'ok ' if exists else 'MISSING'}  {rel}")

    print("\nimports:")
    for label, fn in (
        ("PySide6", lambda: __import__("PySide6.QtWidgets")),
        ("psutil", lambda: __import__("psutil")),
        ("keyboard", lambda: __import__("keyboard")),
        ("win32gui", lambda: __import__("win32gui")),
    ):
        try:
            fn()
            print(f"  ok       {label}")
        except Exception as exc:
            ok = False
            print(f"  FAILED   {label}: {exc}")

    print("\n.NET / LibreHardwareMonitor (the risky part when frozen):")
    try:
        from fpsmon import sensors

        loaded = sensors._load_clr()
        print(f"  clr + LHM DLL loaded: {loaded}  {sensors.LOAD_ERROR or ''}")
        ok &= bool(loaded)
        if loaded:
            b = sensors.SensorBackend(defer=False)
            print(f"  hardware opened: {b.available}")
            print(f"  cpu: {b.cpu_name}")
            print(f"  gpu: {b.gpu_name}")
            ok &= b.available
            b.stop()
    except Exception as exc:
        ok = False
        print(f"  FAILED: {type(exc).__name__}: {exc}")

    print("\nwritable data folder:")
    try:
        from fpsmon import config

        config.bootstrap()
        print(f"  profiles created: {len(config.list_profiles())} in "
              f"{config.PROFILE_DIR}")
        ok &= len(config.list_profiles()) > 0
    except Exception as exc:
        ok = False
        print(f"  FAILED: {exc}")

    print("\n" + "=" * 52)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if "--selftest" in sys.argv:
        return selftest()
    if "--no-elevate" not in sys.argv and not is_admin():
        return relaunch_elevated()
    from fpsmon.app import main as run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
