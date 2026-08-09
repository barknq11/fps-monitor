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


def main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if "--no-elevate" not in sys.argv and not is_admin():
        return relaunch_elevated()
    from fpsmon.app import main as run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
