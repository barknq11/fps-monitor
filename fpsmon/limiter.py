"""
Frame-rate limiting.

Two mechanisms, both optional -- the app works fine with neither:

1. RivaTuner Statistics Server, through its own profile API
   (RTSSHooks64.dll). This is the reliable route: RTSS keeps profiles in
   memory, so editing its .cfg files on disk does nothing and gets
   overwritten later. Measured on a real install: a profile read 60 through
   the API while the file on disk said 0.

2. The GPU driver's own limiter (AMD Radeon Max FPS / Chill, NVIDIA Max Frame
   Rate). Nothing to install, works everywhere, but it cannot be set
   programmatically in a supported way -- so the app opens the right control
   panel and explains what to change.

Capping another process's frame rate requires code inside its render loop,
which is why there is no third option: anything else would mean injecting a
DLL into the game, and that risks anti-cheat bans.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass, field

CREATE_NO_WINDOW = 0x08000000

RTSS_DIRS = [
    r"C:\Program Files (x86)\RivaTuner Statistics Server",
    r"C:\Program Files\RivaTuner Statistics Server",
]

#: RTSS profile property holding the frame cap (0 = unlimited)
PROP_LIMIT = b"FramerateLimit"
PROP_DENOM = b"FramerateLimitDenominator"


def find_rtss_dir() -> str | None:
    for d in RTSS_DIRS:
        if os.path.isfile(os.path.join(d, "RTSSHooks64.dll")):
            return d
    try:
        import psutil

        for p in psutil.process_iter(["name", "exe"]):
            if (p.info.get("name") or "").lower() == "rtss.exe":
                exe = p.info.get("exe")
                if exe and os.path.isfile(
                    os.path.join(os.path.dirname(exe), "RTSSHooks64.dll")
                ):
                    return os.path.dirname(exe)
    except Exception:
        pass
    return None


def rtss_running() -> bool:
    try:
        import psutil

        return any(
            (p.info.get("name") or "").lower() == "rtss.exe"
            for p in psutil.process_iter(["name"])
        )
    except Exception:
        return False


@dataclass
class LimiterStatus:
    available: bool = False
    running: bool = False
    profile: str = ""
    limit: int = 0
    ok: bool = True
    message: str = ""
    notes: list[str] = field(default_factory=list)
    elevated: bool = False


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def profiles_writable(rtss_dir: str | None) -> bool:
    """RTSS profiles live under Program Files, so saving needs elevation.

    Measured: SetProfileProperty succeeds in memory without elevation, but
    SaveProfile silently fails, so the limit reverts on the next read. This
    is checked directly rather than inferred.
    """
    if not rtss_dir:
        return False
    d = os.path.join(rtss_dir, "Profiles")
    probe = os.path.join(d, "__fpsmon_write_test.tmp")
    try:
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except Exception:
        return False


class RTSSProfiles:
    """Thin wrapper over the RTSS profile API."""

    def __init__(self) -> None:
        self.dir = find_rtss_dir()
        self._lib = None
        self.error: str | None = None
        if not self.dir:
            self.error = "RivaTuner Statistics Server was not found."
            return
        name = "RTSSHooks64.dll" if sys.maxsize > 2**32 else "RTSSHooks.dll"
        path = os.path.join(self.dir, name)
        try:
            lib = ctypes.WinDLL(path)
            lib.LoadProfile.argtypes = [ctypes.c_char_p]
            lib.LoadProfile.restype = None
            lib.SaveProfile.argtypes = [ctypes.c_char_p]
            lib.SaveProfile.restype = None
            lib.GetProfileProperty.argtypes = [
                ctypes.c_char_p, ctypes.c_void_p, wintypes.DWORD
            ]
            lib.GetProfileProperty.restype = wintypes.BOOL
            lib.SetProfileProperty.argtypes = [
                ctypes.c_char_p, ctypes.c_void_p, wintypes.DWORD
            ]
            lib.SetProfileProperty.restype = wintypes.BOOL
            lib.UpdateProfiles.argtypes = []
            lib.UpdateProfiles.restype = None
            self._lib = lib
        except Exception as exc:
            self.error = f"Could not load {name}: {exc}"

    @property
    def available(self) -> bool:
        return self._lib is not None

    @staticmethod
    def _encode(profile: str | None) -> bytes:
        """'' / None means the Global profile."""
        return (profile or "").encode("ascii", "replace")

    def get_limit(self, profile: str | None) -> int | None:
        if not self._lib:
            return None
        try:
            self._lib.LoadProfile(self._encode(profile))
            val = wintypes.DWORD(0)
            ok = self._lib.GetProfileProperty(
                PROP_LIMIT, ctypes.byref(val), ctypes.sizeof(val)
            )
            return int(val.value) if ok else None
        except Exception:
            return None

    def set_limit(self, profile: str | None, fps: int) -> bool:
        """Set the cap and make RTSS apply it immediately."""
        if not self._lib:
            return False
        try:
            name = self._encode(profile)
            self._lib.LoadProfile(name)
            val = wintypes.DWORD(max(0, min(int(fps), 1000)))
            if not self._lib.SetProfileProperty(
                PROP_LIMIT, ctypes.byref(val), ctypes.sizeof(val)
            ):
                return False
            # a denominator of 0 would make the limit meaningless
            den = wintypes.DWORD(0)
            if self._lib.GetProfileProperty(
                PROP_DENOM, ctypes.byref(den), ctypes.sizeof(den)
            ) and den.value == 0:
                one = wintypes.DWORD(1)
                self._lib.SetProfileProperty(
                    PROP_DENOM, ctypes.byref(one), ctypes.sizeof(one)
                )
            self._lib.SaveProfile(name)
            self._lib.UpdateProfiles()      # applies live, no restart
            return True
        except Exception:
            return False


class FpsLimiter:
    """Frame cap via RTSS when present, with driver guidance as the fallback."""

    def __init__(self) -> None:
        self.api = RTSSProfiles()
        self.dir = self.api.dir

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self.api.available

    @staticmethod
    def profile_name(exe: str | None) -> str:
        """RTSS profiles are keyed by executable name; '' is Global."""
        if not exe:
            return ""
        name = os.path.basename(exe)
        if name.lower().endswith(".cfg"):
            name = name[:-4]
        return name

    def profiles_dir(self) -> str | None:
        d = os.path.join(self.dir, "Profiles") if self.dir else None
        return d if d and os.path.isdir(d) else None

    def has_own_profile(self, exe: str | None) -> bool:
        d = self.profiles_dir()
        if not d or not exe:
            return False
        return os.path.exists(os.path.join(d, f"{self.profile_name(exe)}.cfg"))

    # ------------------------------------------------------------------
    def status(self, exe: str | None) -> LimiterStatus:
        st = LimiterStatus(available=self.available, running=rtss_running())
        st.profile = self.profile_name(exe) or "Global"
        st.elevated = is_elevated()
        if not self.available:
            st.ok = False
            st.message = self.api.error or "RTSS not available."
            return st
        if not st.running:
            st.ok = False
            st.message = "RTSS is not running - start it to apply limits."
            return st
        val = self.get_limit(exe)
        st.limit = val or 0
        if val is None:
            st.ok = False
            st.message = "RTSS did not return a limit for this profile."
        else:
            st.message = f"{st.profile}: " + (
                f"{val} FPS" if val else "unlimited"
            )
        self._add_notes(st, exe)
        return st

    def get_limit(self, exe: str | None) -> int | None:
        return self.api.get_limit(self.profile_name(exe))

    def set_limit(self, exe: str | None, fps: int) -> LimiterStatus:
        st = LimiterStatus(available=self.available, running=rtss_running())
        st.profile = self.profile_name(exe) or "Global"
        if not self.available:
            st.ok = False
            st.message = self.api.error or "RTSS not available."
            return st
        if not st.running:
            st.ok = False
            st.message = (
                "RTSS is not running. Start RivaTuner Statistics Server first "
                "- it is what actually applies the cap."
            )
            return st

        st.elevated = is_elevated()
        if not profiles_writable(self.dir):
            st.ok = False
            st.message = (
                "Cannot save: RTSS keeps its profiles under Program Files and "
                "they are not writable. Run FPS Monitor as Administrator "
                "(the launcher normally asks) and try again."
            )
            return st

        if not self.api.set_limit(self.profile_name(exe), fps):
            st.ok = False
            st.message = "RTSS rejected the change."
            return st

        readback = self.get_limit(exe)
        st.limit = readback or 0
        if readback != max(0, int(fps)):
            st.ok = False
            st.message = (
                f"Wrote {fps} but RTSS reports {readback}. The profile may be "
                f"locked or managed elsewhere."
            )
        else:
            st.message = (
                f"{st.profile}: " + (f"limited to {fps} FPS" if fps
                                     else "limit removed")
            )
        self._add_notes(st, exe)
        return st

    def _add_notes(self, st: LimiterStatus, exe: str | None) -> None:
        name = self.profile_name(exe)
        if not name and exe is None:
            # Global: warn about games that override it
            d = self.profiles_dir()
            if d:
                overriding = []
                for f in os.listdir(d):
                    if not f.lower().endswith(".cfg"):
                        continue
                    own = self.api.get_limit(f[:-4])
                    if own not in (None, st.limit):
                        overriding.append(f[:-4])
                if overriding:
                    st.notes.append(
                        "These games have their own profile and ignore Global: "
                        + ", ".join(sorted(overriding)[:6])
                        + ("..." if len(overriding) > 6 else "")
                    )
        if 0 < st.limit < 10:
            st.notes.append(
                f"{st.profile} is capped at {st.limit} FPS, which is unusually "
                f"low and looks accidental."
            )


# ======================================================================
# Driver-level limiter (no third-party software at all)
# ======================================================================

def gpu_vendor(gpu_name: str) -> str:
    n = (gpu_name or "").lower()
    if "nvidia" in n or "geforce" in n or "rtx" in n or "gtx" in n:
        return "nvidia"
    if "amd" in n or "radeon" in n:
        return "amd"
    if "intel" in n or "arc" in n:
        return "intel"
    return "unknown"


DRIVER_HINTS = {
    "amd": (
        "AMD Software: Adrenalin Edition -> Gaming -> Graphics -> "
        "Advanced -> \"Max FPS\" (or Radeon Chill for a min/max range). "
        "Set it globally or per game."
    ),
    "nvidia": (
        "NVIDIA Control Panel -> Manage 3D settings -> \"Max Frame Rate\". "
        "Available globally or per program."
    ),
    "intel": (
        "Intel Graphics Software -> Graphics -> Global/Per-app settings. "
        "Frame rate limiting is not offered on all Intel drivers."
    ),
    "unknown": "Check your GPU driver's control panel for a frame rate limit.",
}

DRIVER_APPS = {
    "amd": [
        r"C:\Program Files\AMD\CNext\CNext\RadeonSoftware.exe",
        r"C:\Program Files\AMD\CNext\CNext\cncmd.exe",
    ],
    "nvidia": [
        r"C:\Program Files\NVIDIA Corporation\Control Panel Client\nvcplui.exe",
        r"C:\Windows\System32\nvcplui.exe",
    ],
    # Intel Graphics Software ships as a Store app with no fixed exe path, so
    # there is nothing dependable to launch. Better to say so than to open the
    # wrong program.
    "intel": [],
}


def driver_panel_path(vendor: str) -> str | None:
    for p in DRIVER_APPS.get(vendor, []):
        if os.path.exists(p):
            return p
    return None


def open_driver_panel(vendor: str) -> tuple[bool, str]:
    """Launch the vendor control panel so the user can set the cap there."""
    path = driver_panel_path(vendor)
    if path:
        try:
            subprocess.Popen([path], creationflags=CREATE_NO_WINDOW)
            return True, f"Opened {os.path.basename(path)}."
        except Exception as exc:
            return False, f"Could not launch {os.path.basename(path)}: {exc}"
    # Adrenalin is also reachable through its shell protocol
    if vendor == "nvidia":
        try:
            os.startfile("nvidia-control-panel:")  # noqa: S606
            return True, "Opened the NVIDIA Control Panel."
        except Exception:
            pass
    return False, (
        "The driver control panel was not found. Open it from the desktop "
        "right-click menu or the Start menu."
    )
