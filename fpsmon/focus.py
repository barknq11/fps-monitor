"""
Foreground-window inspection: what is focused, is it a game, and where is it.

Two things depend on this: showing the overlay only while a game is focused,
and anchoring the overlay inside the game's window when it is not fullscreen.

"Is it a game" cannot be answered by "is it presenting frames" alone --
browsers, video players and even Explorer present through Direct3D. The test
used here is: the focused process is presenting frames AND is not on the
non-game list.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

_IS_WIN = sys.platform == "win32"
if _IS_WIN:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _user32.GetForegroundWindow.restype = ctypes.c_void_p
    _user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    _user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    _user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.POINT)]
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Applications that render through D3D but are obviously not games. Matched
# case-insensitively on the executable name.
NON_GAMES = {
    # browsers
    "chrome.exe", "firefox.exe", "msedge.exe", "brave.exe", "opera.exe",
    "librewolf.exe", "vivaldi.exe", "iexplore.exe", "arc.exe", "zen.exe",
    # shell / system
    "explorer.exe", "dwm.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "applicationframehost.exe", "taskmgr.exe",
    "lockapp.exe", "textinputhost.exe", "systemsettings.exe",
    # chat / media / tools
    "discord.exe", "slack.exe", "teams.exe", "spotify.exe", "vlc.exe",
    "mpv.exe", "kmplayer64x.exe", "obs64.exe", "obs32.exe", "photos.exe",
    "code.exe", "cursor.exe", "devenv.exe", "notepad.exe", "notepad++.exe",
    "windowsterminal.exe", "powershell.exe", "cmd.exe", "wt.exe",
    "claude.exe", "chatgpt.exe", "lmstudio.exe",
    # launchers
    "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "ea.exe",
    "eadesktop.exe", "battle.net.exe", "galaxyclient.exe", "rtss.exe",
    "msiafterburner.exe", "pythonw.exe", "python.exe",
}


@dataclass
class Foreground:
    hwnd: int = 0
    pid: int = 0
    exe: str = ""
    title: str = ""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    fullscreen: bool = False

    @property
    def valid(self) -> bool:
        return self.hwnd != 0 and self.width > 0 and self.height > 0


def _process_name(pid: int) -> str:
    try:
        h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1]
        finally:
            _kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""


def foreground() -> Foreground:
    """Describe the currently focused top-level window."""
    fg = Foreground()
    if not _IS_WIN:
        return fg
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return fg
        fg.hwnd = int(hwnd)

        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        fg.pid = int(pid.value)
        fg.exe = _process_name(fg.pid)

        buf = ctypes.create_unicode_buffer(256)
        _user32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 256)
        fg.title = buf.value

        # Client rect in screen coordinates: this is the actual rendered area,
        # excluding title bar and borders, which is where the overlay belongs.
        rc = wintypes.RECT()
        if _user32.GetClientRect(ctypes.c_void_p(hwnd), ctypes.byref(rc)):
            pt = wintypes.POINT(rc.left, rc.top)
            _user32.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(pt))
            fg.x, fg.y = int(pt.x), int(pt.y)
            fg.width = int(rc.right - rc.left)
            fg.height = int(rc.bottom - rc.top)

        # Fullscreen if the client area covers (near enough) a whole monitor.
        try:
            MONITOR_DEFAULTTONEAREST = 2
            mon = _user32.MonitorFromWindow(
                ctypes.c_void_p(hwnd), MONITOR_DEFAULTTONEAREST
            )

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if _user32.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi)):
                mw = mi.rcMonitor.right - mi.rcMonitor.left
                mh = mi.rcMonitor.bottom - mi.rcMonitor.top
                fg.fullscreen = fg.width >= mw - 2 and fg.height >= mh - 2
        except Exception:
            pass
    except Exception:
        pass
    return fg


def is_game(
    fg: Foreground,
    presenting_pids: set[int],
    blocklist: set[str] | None = None,
    allowlist: set[str] | None = None,
) -> bool:
    """True when the focused window looks like a running game.

    Presenting frames is necessary but nowhere near sufficient -- a browser
    playing video presents continuously -- so the executable is checked against
    a list of known non-games as well.
    """
    if not fg.valid or not fg.pid:
        return False
    exe = (fg.exe or "").lower()
    if allowlist and exe in {a.lower() for a in allowlist}:
        return True
    block = {b.lower() for b in (blocklist if blocklist is not None else NON_GAMES)}
    if exe in block:
        return False
    return fg.pid in presenting_pids


def window_for_pid(pid: int) -> Foreground | None:
    """Largest visible, non-minimised top-level window owned by `pid`.

    Needed because the overlay should track a game that is *running* even when
    the focus is elsewhere -- for instance while you are on a second monitor.
    """
    if not _IS_WIN or not pid:
        return None

    best: Foreground | None = None
    best_area = 0

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p
    )

    def _cb(hwnd, _lparam):
        nonlocal best, best_area
        try:
            if not _user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
                return True
            if _user32.IsIconic(ctypes.c_void_p(hwnd)):
                return True          # minimised: nothing to sit on top of
            wpid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(
                ctypes.c_void_p(hwnd), ctypes.byref(wpid)
            )
            if wpid.value != pid:
                return True
            rc = wintypes.RECT()
            if not _user32.GetClientRect(ctypes.c_void_p(hwnd), ctypes.byref(rc)):
                return True
            w = int(rc.right - rc.left)
            h = int(rc.bottom - rc.top)
            if w < 200 or h < 150:
                return True          # tooltips, splash and helper windows
            area = w * h
            if area <= best_area:
                return True
            pt = wintypes.POINT(rc.left, rc.top)
            _user32.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(pt))
            fg = Foreground(hwnd=int(hwnd), pid=pid, exe=_process_name(pid))
            fg.x, fg.y, fg.width, fg.height = int(pt.x), int(pt.y), w, h
            buf = ctypes.create_unicode_buffer(256)
            _user32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 256)
            fg.title = buf.value
            fg.fullscreen = _covers_monitor(hwnd, w, h)
            best, best_area = fg, area
        except Exception:
            pass
        return True

    try:
        _user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception:
        return None
    return best


def _covers_monitor(hwnd: int, w: int, h: int) -> bool:
    try:
        MONITOR_DEFAULTTONEAREST = 2
        mon = _user32.MonitorFromWindow(
            ctypes.c_void_p(hwnd), MONITOR_DEFAULTTONEAREST
        )

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if _user32.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi)):
            mw = mi.rcMonitor.right - mi.rcMonitor.left
            mh = mi.rcMonitor.bottom - mi.rcMonitor.top
            return w >= mw - 2 and h >= mh - 2
    except Exception:
        pass
    return False


def find_game_window(
    candidates: list[tuple[int, str]],
    blocklist: set[str] | None = None,
    allowlist: set[str] | None = None,
) -> Foreground | None:
    """Pick a running game's window from presenting processes, focus aside.

    `candidates` is [(pid, exe_name)] ordered best-first (most frames first).
    """
    block = {b.lower() for b in (blocklist if blocklist is not None else NON_GAMES)}
    allow = {a.lower() for a in (allowlist or set())}
    for pid, exe in candidates:
        name = (exe or "").lower()
        if name and name not in allow and name in block:
            continue
        win = window_for_pid(pid)
        if win is not None and win.valid:
            return win
    return None


def anchor_rect(
    fg: Foreground, screen_geo: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """Rectangle the overlay should position itself within.

    The game's client area when it is windowed, the whole screen when it is
    fullscreen (or when there is no usable window).
    """
    if fg.valid and not fg.fullscreen:
        return (fg.x, fg.y, fg.width, fg.height)
    return screen_geo
