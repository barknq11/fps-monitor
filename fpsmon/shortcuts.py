"""
Start Menu integration.

Windows Search indexes the Start Menu, so a .lnk placed there is what makes
the app findable by typing its name. The shortcut goes in the *per-user*
Start Menu, which needs no elevation and does not touch other accounts.

Creating the .lnk is done through the shell's IShellLink COM interface. The
pywin32 route is tried first and a PowerShell one-liner is the fallback,
because COM registration is the sort of thing that works from source and then
quietly fails inside a frozen build.
"""

from __future__ import annotations

import os
import subprocess
import sys

APP_NAME = "FPS Monitor"
CREATE_NO_WINDOW = 0x08000000


def start_menu_dir() -> str:
    return os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "Microsoft", "Windows", "Start Menu", "Programs",
    )


def shortcut_path() -> str:
    return os.path.join(start_menu_dir(), f"{APP_NAME}.lnk")


def target() -> tuple[str, str, str]:
    """(program, arguments, working directory) for the shortcut."""
    if getattr(sys, "frozen", False):
        return sys.executable, "", os.path.dirname(sys.executable)
    # running from source: point at pythonw so no console window appears
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    return exe, f'"{os.path.join(root, "run.py")}"', root


def icon_path() -> str:
    from .paths import resource

    ico = resource("assets", "icon.ico")
    return ico if os.path.exists(ico) else ""


def exists() -> bool:
    return os.path.exists(shortcut_path())


# ----------------------------------------------------------------- create
def _create_pywin32(link: str, prog: str, args: str, cwd: str, ico: str) -> bool:
    try:
        import pythoncom
        from win32com.client import Dispatch

        pythoncom.CoInitialize()
        try:
            sc = Dispatch("WScript.Shell").CreateShortCut(link)
            sc.TargetPath = prog
            sc.Arguments = args
            sc.WorkingDirectory = cwd
            sc.Description = "FPS, GPU and CPU overlay"
            if ico:
                sc.IconLocation = ico
            sc.save()
        finally:
            pythoncom.CoUninitialize()
        return os.path.exists(link)
    except Exception:
        return False


def _create_powershell(link: str, prog: str, args: str, cwd: str, ico: str) -> bool:
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath='{prog}';"
        "$s.Arguments='{args}';"
        "$s.WorkingDirectory='{cwd}';"
        "$s.Description='FPS, GPU and CPU overlay';"
        "{icon}"
        "$s.Save()"
    ).format(
        link=link.replace("'", "''"),
        prog=prog.replace("'", "''"),
        args=args.replace("'", "''"),
        cwd=cwd.replace("'", "''"),
        icon=f"$s.IconLocation='{ico}';" if ico else "",
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=25,
            creationflags=CREATE_NO_WINDOW,
        )
        return os.path.exists(link)
    except Exception:
        return False


def create() -> tuple[bool, str]:
    """Add the app to the Start Menu. Returns (ok, message)."""
    if sys.platform != "win32":
        return False, "Start Menu shortcuts are Windows-only."
    try:
        os.makedirs(start_menu_dir(), exist_ok=True)
    except Exception as exc:
        return False, f"Could not open the Start Menu folder: {exc}"

    link = shortcut_path()
    prog, args, cwd = target()
    ico = icon_path()

    if _create_pywin32(link, prog, args, cwd, ico) or \
            _create_powershell(link, prog, args, cwd, ico):
        return True, (
            f"Added to the Start Menu. Press the Windows key and type "
            f"\"{APP_NAME}\". Search may take a few seconds to index it."
        )
    return False, "Could not create the shortcut."


def remove() -> tuple[bool, str]:
    link = shortcut_path()
    if not os.path.exists(link):
        return True, "No Start Menu shortcut to remove."
    try:
        os.remove(link)
        return True, "Removed from the Start Menu."
    except Exception as exc:
        return False, f"Could not remove the shortcut: {exc}"


def status() -> str:
    if exists():
        return f"In the Start Menu: {shortcut_path()}"
    return "Not in the Start Menu, so Windows Search will not find it."
