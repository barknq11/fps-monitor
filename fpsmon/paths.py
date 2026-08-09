"""
Where things live, whether running from source or from a frozen build.

Two different roots are needed and conflating them is the usual cause of a
build that works in development and breaks once packaged:

* resources  - vendor DLLs, PresentMon, icons. Read-only, shipped with the
  app. PyInstaller unpacks these to sys._MEIPASS.
* data       - profiles, logs, state.json. Written at runtime, so it must
  never point inside the bundle (which may be read-only or, for a one-file
  build, a temporary folder wiped on exit).
"""

from __future__ import annotations

import os
import sys

FROZEN = getattr(sys, "frozen", False)


def resource_dir() -> str:
    """Folder holding bundled read-only files."""
    if FROZEN:
        # set by PyInstaller: the temp dir for one-file builds, the
        # _internal folder for one-folder builds
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource(*parts: str) -> str:
    return os.path.join(resource_dir(), *parts)


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except Exception:
        return False


_data_dir: str | None = None


def data_dir() -> str:
    """Folder for files the app writes. Portable when it can be."""
    global _data_dir
    if _data_dir is not None:
        return _data_dir

    if FROZEN:
        # Keep it portable: settings live beside the exe so the whole thing
        # can be moved or deleted as one folder. Fall back to LOCALAPPDATA
        # when installed somewhere unwritable such as Program Files.
        beside = os.path.dirname(sys.executable)
        if _writable(beside):
            _data_dir = beside
        else:
            _data_dir = os.path.join(
                os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                "FPS Monitor",
            )
            os.makedirs(_data_dir, exist_ok=True)
    else:
        _data_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return _data_dir


def data(*parts: str) -> str:
    return os.path.join(data_dir(), *parts)
