"""
Real frame-rate measurement via Intel PresentMon (ETW present-event tracing).

This is the same technique CapFrameX / OCAT use: PresentMon reports one row per
presented frame with its frame time, so FPS, frame-time percentiles and 1% /
0.1% lows are all measured rather than estimated.

Requires Administrator (ETW realtime sessions are privileged).  When PresentMon
cannot start, `available` stays False and the FPS metrics simply do not appear
in the overlay instead of showing a fake number.
"""

from __future__ import annotations

import collections
import os
import statistics
import subprocess
import sys
import threading
import time
from typing import Any

VENDOR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor"
)
PRESENTMON = os.path.join(VENDOR, "PresentMon.exe")

# Averaging window for the FPS / lows figures.
WINDOW_SECONDS = 3.0
# How much history is retained. This must cover the widest graph window the
# overlay might ask for, otherwise the left of the graph is permanently empty.
DEFAULT_RETENTION = 6.0
MAX_RETENTION = 60.0
# A process is considered idle (not the one to report) after this long without
# frames. It is deliberately larger than PresentMon's delivery cadence, which
# was measured at roughly one burst per second with outliers past two.
STALE_SECONDS = 5.0
# How long a stream's HISTORY is kept after it goes idle. Discarding history
# the moment a burst is late forces the graph to regrow from the right edge,
# which looks like the trace being repeatedly cut off on the left.
HISTORY_GRACE = 5.0

CREATE_NO_WINDOW = 0x08000000

SESSION_NAME = "FPSMonitorLive"
# Realtime ETW sessions outlive the process that created them if it is killed
# rather than shut down. An orphaned session keeps hold of the present
# providers, and every later capture then silently returns nothing, so these
# are cleared before starting.
STALE_SESSIONS = (SESSION_NAME, "FPSMonitorDiag")

# The desktop compositor presents constantly and is not what anyone means by
# "FPS"; without excluding it the overlay can report dwm.exe's frame rate.
EXCLUDED_PROCESSES = ("dwm.exe", "explorer.exe", "ApplicationFrameHost.exe")


def _stop_trace_session(name: str) -> bool:
    """Best-effort teardown of a leftover realtime ETW session."""
    try:
        r = subprocess.run(
            ["logman", "stop", name, "-ets"],
            capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except Exception:
        return False


def _foreground_pid() -> int | None:
    try:
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        return win32process.GetWindowThreadProcessId(hwnd)[1]
    except Exception:
        return None


class _Stream:
    """Rolling frame-time window for a single presenting process."""

    __slots__ = (
        "name", "pid", "times", "last_seen", "retention", "_pm_base", "_has_pm",
    )

    def __init__(self, name: str, pid: int, retention: float = DEFAULT_RETENTION):
        self.name = name
        self.pid = pid
        self.retention = retention
        # monotonic time corresponding to PresentMon's CPUStartTime == 0
        self._pm_base: float | None = None
        self._has_pm = False
        # 60 s of headroom at 1000 FPS; the time-based purge below is what
        # actually bounds this in practice.
        self.times: collections.deque[tuple[float, float]] = collections.deque(
            maxlen=60000
        )  # (monotonic_ts, frametime_ms)
        self.last_seen = time.monotonic()

    def add(self, frametime_ms: float, pm_time_ms: float | None = None) -> None:
        """Record a frame.

        PresentMon writes to a pipe, so its stdout is block buffered: measured
        on this machine, 3310 rows arrived at just 25 distinct instants, up to
        296 rows at once, about one burst per second. Arrival time is therefore
        useless for positioning frames.

        The stored key is PresentMon's own CPUStartTime (seconds) when it is
        available, otherwise the arrival time. It is deliberately NOT converted
        to the monotonic clock here: within a burst the anchor is still
        settling, and converting early would squash the whole burst onto the
        arrival instant. series() does the conversion once the anchor is known.
        """
        now = time.monotonic()
        self.last_seen = now
        if pm_time_ms is not None:
            t = pm_time_ms / 1000.0
            self._has_pm = True
            # The base is the monotonic time at which CPUStartTime was zero.
            # Rows in a burst share an arrival, so the SMALLEST (now - t) --
            # i.e. the newest frame in the burst -- is the honest estimate.
            est = now - t
            if self._pm_base is None or est < self._pm_base:
                self._pm_base = est
            elif est - self._pm_base > 2.0:
                # Only re-anchor on a real discontinuity (capture restarted,
                # long stall). A continuous per-frame correction was running
                # at ~120 Hz and slid every point sideways a little on every
                # frame, which showed up as the graph jittering horizontally.
                self._pm_base = est
            key = t
            cutoff = (now - self._pm_base) - self.retention - 1.0
        else:
            key = now
            cutoff = now - self.retention - 1.0
        self.times.append((key, frametime_ms))
        while self.times and self.times[0][0] < cutoff:
            self.times.popleft()

    def recent(self, seconds: float) -> list[float]:
        """Frame times from the last `seconds`, oldest first."""
        return [ft for _ts, ft in self.series(seconds)]

    def series(self, seconds: float) -> list[tuple[float, float]]:
        """(presentation timestamp, frame time ms) pairs for the last `seconds`.

        Presentation times are reconstructed rather than taken from arrival
        time: the newest frame is anchored to when its row arrived, and each
        earlier frame is placed by walking backwards through the measured frame
        intervals. Frame time IS the gap between presents, so this rebuilds the
        true timeline exactly, and it is immune to however PresentMon happens
        to buffer its output.
        """
        if not self.times:
            return []
        if self._has_pm and self._pm_base is not None:
            # Convert PresentMon's clock to monotonic now that the anchor has
            # settled. Spacing comes straight from CPUStartTime, which the
            # capture confirmed advances by exactly one FrameTime per frame.
            base = self._pm_base
            cutoff = self.times[-1][0] - seconds
            return [
                (base + k, ft)
                for k, ft in self.times
                if k >= cutoff and ft > 0
            ]

        anchor = self.times[-1][0]
        cutoff = anchor - seconds
        out: list[tuple[float, float]] = []
        t = anchor
        for _arrival, ft in reversed(self.times):
            if ft <= 0:
                continue
            out.append((t, ft))
            t -= ft / 1000.0
            if t < cutoff:
                break
        out.reverse()
        return out

    def stats(self) -> dict[str, Any]:
        # Uses the reconstructed timeline too, so a buffered burst cannot
        # skew the averaging window.
        vals = self.recent(WINDOW_SECONDS)
        if len(vals) < 2:
            return {}
        vals_sorted = sorted(vals, reverse=True)  # slowest frames first
        n = len(vals_sorted)
        mean_ft = statistics.fmean(vals)
        out = {
            "fps": round(1000.0 / mean_ft, 1),
            "frametime": round(mean_ft, 2),
            "frametime_max": round(vals_sorted[0], 2),
            "app": self.name,
        }
        # 1% low  = average FPS of the slowest 1% of frames
        k1 = max(1, n // 100)
        out["fps_1low"] = round(1000.0 / statistics.fmean(vals_sorted[:k1]), 1)
        k01 = max(1, n // 1000)
        out["fps_01low"] = round(1000.0 / statistics.fmean(vals_sorted[:k01]), 1)

        # --- smoothness ---------------------------------------------------
        # Micro-stutter is better described by frame-to-frame *variation* than
        # by average FPS: a run can average 144 FPS and still feel bad if
        # individual frames keep overshooting their neighbours.
        med = statistics.median(vals)
        out["frametime_med"] = round(med, 2)
        if med > 0:
            spikes = sum(1 for v in vals if v > med * 1.5)
            out["stutter_pct"] = round(100.0 * spikes / n, 1)
        # mean absolute consecutive difference ("jitter")
        if n >= 3:
            diffs = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
            out["frametime_jitter"] = round(statistics.fmean(diffs), 2)
        return out


class FPSBackend:
    """Runs PresentMon and exposes stats for the focused (or busiest) app."""

    def __init__(self) -> None:
        self.available = False
        self.error: str | None = None
        self._proc: subprocess.Popen[str] | None = None
        self._streams: dict[int, _Stream] = {}
        self._lock = threading.Lock()
        self._running = False
        self._threads: list[threading.Thread] = []
        self._locked_pid: int | None = None  # user-pinned target
        self._retention = DEFAULT_RETENTION
        self.recovered_session: str | None = None
        self.uses_pm_timestamps = False

    def set_retention(self, seconds: float) -> None:
        """Keep at least `seconds` of frame history (for the graph window)."""
        seconds = max(WINDOW_SECONDS, min(float(seconds), MAX_RETENTION))
        self._retention = seconds
        with self._lock:
            for st in self._streams.values():
                st.retention = seconds

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> bool:
        if self._running:
            return self.available
        if not os.path.exists(PRESENTMON):
            self.error = "PresentMon.exe not found in vendor/"
            return False

        # Clear any session orphaned by a previous crash or by the diagnostic
        # tool. Without this the capture starts but never receives a frame.
        for name in STALE_SESSIONS:
            if _stop_trace_session(name):
                self.recovered_session = name

        cmd = [
            PRESENTMON,
            "--output_stdout",
            "--no_console_stats",
            "--stop_existing_session",
            "--v2_metrics",
            "--session_name",
            SESSION_NAME,
        ]
        for name in EXCLUDED_PROCESSES:
            cmd += ["--exclude", name]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:
            self.error = f"could not launch PresentMon: {exc}"
            return False

        self._running = True
        for target, name in (
            (self._read_stdout, "fpsmon-presentmon"),
            (self._read_stderr, "fpsmon-presentmon-err"),
            (self._reap, "fpsmon-presentmon-gc"),
        ):
            t = threading.Thread(target=target, daemon=True, name=name)
            t.start()
            self._threads.append(t)
        return True

    def stop(self) -> None:
        self._running = False
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        # terminate() does not let PresentMon close its realtime ETW session,
        # so tear it down explicitly. Leaving it running silently breaks every
        # later capture.
        _stop_trace_session(SESSION_NAME)
        self.available = False

    # -- pinning -----------------------------------------------------------
    def lock_to(self, pid: int | None) -> None:
        """Pin measurement to one process id (None = auto-follow foreground)."""
        self._locked_pid = pid

    def presenting_pids(self) -> set[int]:
        """Process ids that have presented a frame recently."""
        now = time.monotonic()
        with self._lock:
            return {
                p for p, s in self._streams.items()
                if now - s.last_seen <= STALE_SECONDS
            }

    def candidates(self) -> list[tuple[int, str]]:
        """Presenting processes as (pid, exe), busiest first."""
        now = time.monotonic()
        with self._lock:
            live = [
                s for s in self._streams.values()
                if now - s.last_seen <= STALE_SECONDS
            ]
            live.sort(key=lambda s: len(s.times), reverse=True)
            return [(s.pid, s.name) for s in live]

    def targets(self) -> list[tuple[int, str]]:
        with self._lock:
            return sorted(
                ((s.pid, s.name) for s in self._streams.values()), key=lambda x: x[1]
            )

    # -- reading -----------------------------------------------------------
    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            line = line.strip()
            if line and self.error is None and not self.available:
                self.error = line[:200]

    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        header: list[str] | None = None
        i_app = i_pid = i_ft = i_time = -1
        for raw in proc.stdout:
            if not self._running:
                break
            line = raw.strip()
            if not line:
                continue
            if header is None:
                header = [h.strip() for h in line.split(",")]
                low = [h.lower() for h in header]

                def find(*names: str) -> int:
                    for nm in names:
                        if nm in low:
                            return low.index(nm)
                    return -1

                i_app = find("application")
                i_pid = find("processid")
                i_ft = find("frametime", "msbetweenpresents")
                # CPUStartTime is PresentMon's own per-frame clock. Confirmed
                # on this build: consecutive values differ by exactly the
                # FrameTime of the earlier frame, i.e. it is in milliseconds.
                # Using it beats reconstructing the timeline because it stays
                # correct even if rows are dropped.
                i_time = find("cpustarttime", "timeinseconds")
                if i_ft < 0 or i_pid < 0:
                    self.error = f"unexpected PresentMon header: {line[:160]}"
                    return
                self.uses_pm_timestamps = i_time >= 0
                self.available = True
                self.error = None
                continue

            parts = line.split(",")
            if len(parts) <= max(i_pid, i_ft):
                continue
            try:
                pid = int(parts[i_pid])
                ft = float(parts[i_ft])
            except ValueError:
                continue
            if ft <= 0 or ft > 2000:  # ignore absurd frames (alt-tab, load screens)
                continue
            pm_time = None
            if i_time >= 0 and len(parts) > i_time:
                try:
                    pm_time = float(parts[i_time])
                except ValueError:
                    pm_time = None
            name = parts[i_app] if i_app >= 0 else str(pid)
            if name.lower() in {e.lower() for e in EXCLUDED_PROCESSES}:
                continue
            with self._lock:
                st = self._streams.get(pid)
                if st is None:
                    st = _Stream(name, pid, self._retention)
                    self._streams[pid] = st
                st.add(ft, pm_time)

    def _reap(self) -> None:
        """Forget processes that are long gone.

        Only once their history has aged out entirely -- an idle stream is
        still the right thing to draw, and deleting it mid-graph wipes the
        trace.
        """
        while self._running:
            time.sleep(1.0)
            now = time.monotonic()
            with self._lock:
                limit = self._retention + HISTORY_GRACE
                dead = [
                    p
                    for p, s in self._streams.items()
                    if now - s.last_seen > limit
                ]
                for p in dead:
                    self._streams.pop(p, None)

    # -- output ------------------------------------------------------------
    def _active_stream(self) -> _Stream | None:
        if not self._streams:
            return None
        if self._locked_pid is not None:
            return self._streams.get(self._locked_pid)
        fg = _foreground_pid()
        if fg is not None and fg in self._streams:
            return self._streams[fg]
        # Prefer a stream that is still actively presenting; fall back to the
        # idle ones only if nothing is live, so a retained-but-finished stream
        # cannot outrank the running game just by holding more history.
        now = time.monotonic()
        live = [
            s for s in self._streams.values() if now - s.last_seen <= STALE_SECONDS
        ]
        pool = live or list(self._streams.values())
        return max(pool, key=lambda s: len(s.times))

    def read(self) -> dict[str, Any]:
        with self._lock:
            st = self._active_stream()
            return st.stats() if st else {}

    def frametime_history(self, seconds: float = 5.0) -> list[float]:
        """Recent frame times for the active app, oldest first."""
        with self._lock:
            st = self._active_stream()
            return st.recent(seconds) if st else []

    def frametime_series(self, seconds: float = 5.0) -> list[tuple[float, float]]:
        """Timestamped frame times for the active app. Called at render rate."""
        with self._lock:
            st = self._active_stream()
            return st.series(seconds) if st else []
