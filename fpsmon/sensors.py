"""
Hardware sensor backend built on LibreHardwareMonitorLib (via pythonnet).

Produces a flat dict of metric_id -> float/str.  Metric ids are stable strings
so the overlay and config layers never need to know about LHM internals.

Administrator is required for CPU temperature, per-core clocks and CPU power
(they come from a ring0 driver).  Everything else -- including full AMD GPU
telemetry -- works unelevated.
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
from typing import Any

import psutil

from .paths import resource

VENDOR = resource("vendor")

_Computer = None
LOAD_ERROR: str | None = None


def _nan_to_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _load_clr() -> bool:
    """Import LibreHardwareMonitorLib through the .NET Framework runtime."""
    global _Computer, LOAD_ERROR
    if _Computer is not None:
        return True
    try:
        os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")
        import clr  # noqa: F401  (pythonnet)

        if VENDOR not in sys.path:
            sys.path.append(VENDOR)
        clr.AddReference(os.path.join(VENDOR, "LibreHardwareMonitorLib.dll"))
        from LibreHardwareMonitor.Hardware import Computer  # type: ignore

        _Computer = Computer
        return True
    except Exception as exc:  # pragma: no cover - depends on host
        LOAD_ERROR = f"{type(exc).__name__}: {exc}"
        return False


def is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# --------------------------------------------------------------------------
# Sensor lookup tables: (SensorType name, sensor Name) -> metric id
# --------------------------------------------------------------------------

CPU_MAP = {
    ("Load", "CPU Total"): "cpu_load",
    ("Load", "CPU Core Max"): "cpu_load_max",
    ("Temperature", "Core (Tctl/Tdie)"): "cpu_temp",
    ("Temperature", "CPU Package"): "cpu_temp",
    ("Temperature", "Core Average"): "cpu_temp_avg",
    ("Power", "Package"): "cpu_power",
    ("Power", "CPU Package"): "cpu_power",
    ("Voltage", "Core (SVI2 TFN)"): "cpu_volt",
    ("Voltage", "Vcore"): "cpu_volt",
}

GPU_MAP = {
    ("Load", "GPU Core"): "gpu_load",
    ("Load", "D3D 3D"): "gpu_load_d3d",
    ("Load", "GPU Memory"): "gpu_mem_load",
    ("Temperature", "GPU Core"): "gpu_temp",
    ("Temperature", "GPU Hot Spot"): "gpu_hotspot",
    ("Temperature", "GPU Memory"): "gpu_mem_temp",
    ("Clock", "GPU Core"): "gpu_clock",
    ("Clock", "GPU Memory"): "gpu_mem_clock",
    ("Power", "GPU Package"): "gpu_power",
    ("Power", "GPU Power"): "gpu_power",
    ("Fan", "GPU Fan"): "gpu_fan_rpm",
    ("Control", "GPU Fan"): "gpu_fan_pct",
    ("Voltage", "GPU Core"): "gpu_volt",
    ("SmallData", "GPU Memory Used"): "vram_used",
    ("SmallData", "GPU Memory Total"): "vram_total",
    ("SmallData", "D3D Dedicated Memory Used"): "vram_used_d3d",
}

MEM_MAP = {
    ("Data", "Memory Used"): "ram_used",
    ("Data", "Memory Available"): "ram_free",
    ("Load", "Memory"): "ram_load",
}


class SensorBackend:
    """Polls LibreHardwareMonitor on a background thread."""

    def __init__(self, interval: float = 0.5, defer: bool = False):
        """`defer=True` opens the hardware monitor on the polling thread.

        Opening LibreHardwareMonitor takes ~2s even without motherboard and
        controller probing, so doing it inline blocks the window from
        appearing. Deferred, the UI is up immediately and readings fill in.
        """
        self.interval = interval
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._running = False
        self._thread: threading.Thread | None = None
        self._computer = None
        self.cpu_name = "CPU"
        self.gpu_name = "GPU"
        self.available = False
        self.ready = False
        self.elevated = is_admin()
        #: every GPU found, as (index, name); order is LibreHardwareMonitor's
        self.gpus: list[tuple[int, str]] = []
        #: which of them to report. None = the first one found.
        self.gpu_index: int | None = None
        self.has_battery = False

        # psutil static info is cheap and always available
        self.core_count = psutil.cpu_count(logical=False) or 0
        self.thread_count = psutil.cpu_count(logical=True) or 0
        try:
            self.ram_total_gb = round(psutil.virtual_memory().total / (1024**3), 1)
        except Exception:
            self.ram_total_gb = 0.0

        if not defer:
            self._open_hardware()

    def _open_hardware(self) -> None:
        if self._computer is not None:
            return
        if _load_clr():
            try:
                c = _Computer()
                c.IsCpuEnabled = True
                c.IsGpuEnabled = True
                c.IsMemoryEnabled = True
                # Motherboard (Super-I/O) and controller (SMBus fan
                # controllers) probing costs about 0.9s of the 3s Open() and
                # provides nothing this overlay displays.
                c.IsMotherboardEnabled = False
                c.IsStorageEnabled = False
                c.IsControllerEnabled = False
                c.Open()
                self._computer = c
                self.available = True
                gpus = []
                for i, hw in enumerate(c.Hardware):
                    t = str(hw.HardwareType)
                    if t == "Cpu":
                        self.cpu_name = str(hw.Name)
                    elif t.startswith("Gpu"):
                        gpus.append((i, str(hw.Name)))
                self.gpus = gpus
                if gpus:
                    self.gpu_name = self._chosen_gpu_name()
            except Exception as exc:
                globals()["LOAD_ERROR"] = f"open failed: {exc}"
        try:
            self.has_battery = psutil.sensors_battery() is not None
        except Exception:
            self.has_battery = False
        self.ready = True

    def _chosen_gpu_name(self) -> str:
        """Name of the GPU currently being reported."""
        if not self.gpus:
            return "GPU"
        if self.gpu_index is not None:
            for idx, name in self.gpus:
                if idx == self.gpu_index:
                    return name
        return self.gpus[0][1]

    def set_gpu(self, index: int | None) -> None:
        """Choose which GPU to report on a multi-GPU machine.

        Laptops in particular expose both an integrated and a discrete GPU,
        and taking whichever LibreHardwareMonitor happens to list first
        reports the idle one.
        """
        self.gpu_index = index
        self.gpu_name = self._chosen_gpu_name()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="fpsmon-sensors"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._computer is not None:
            try:
                self._computer.Close()
            except Exception:
                pass
            self._computer = None

    def read(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    # -- polling -----------------------------------------------------------
    def _loop(self) -> None:
        # opening the hardware monitor here keeps it off the startup path
        if not self.ready:
            self._open_hardware()
        while self._running:
            t0 = time.perf_counter()
            try:
                snap = self._sample()
                with self._lock:
                    self._data = snap
            except Exception:
                pass
            elapsed = time.perf_counter() - t0
            time.sleep(max(0.05, self.interval - elapsed))

    def _sample(self) -> dict[str, Any]:
        out: dict[str, Any] = {}

        if self._computer is not None:
            want_gpu = self.gpu_index
            if want_gpu is None and self.gpus:
                want_gpu = self.gpus[0][0]
            for i, hw in enumerate(self._computer.Hardware):
                t = str(hw.HardwareType)
                # Skip GPUs other than the selected one, so a laptop's idle
                # integrated chip cannot overwrite the discrete one's readings.
                if t.startswith("Gpu") and want_gpu is not None and i != want_gpu:
                    continue
                try:
                    hw.Update()
                    for sub in hw.SubHardware:
                        sub.Update()
                except Exception:
                    continue
                if t == "Cpu":
                    table, cores = CPU_MAP, True
                elif t.startswith("Gpu"):
                    table, cores = GPU_MAP, False
                elif t == "Memory":
                    table, cores = MEM_MAP, False
                else:
                    continue

                core_loads: list[float] = []
                core_clocks: list[float] = []
                for s in hw.Sensors:
                    key = (str(s.SensorType), str(s.Name))
                    val = _nan_to_none(s.Value)
                    mid = table.get(key)
                    if mid is not None and val is not None:
                        out[mid] = val
                    if cores and val is not None:
                        if key[0] == "Load" and key[1].startswith("CPU Core #"):
                            core_loads.append(val)
                        elif key[0] == "Clock" and key[1].startswith("Core #"):
                            core_clocks.append(val)
                if core_loads:
                    out["cpu_core_loads"] = core_loads
                if core_clocks:
                    out["cpu_clock"] = round(max(core_clocks))
                    out["cpu_clock_avg"] = round(sum(core_clocks) / len(core_clocks))

        # --- psutil fallbacks / supplements --------------------------------
        try:
            if "cpu_load" not in out:
                out["cpu_load"] = psutil.cpu_percent(interval=None)
            if "cpu_core_loads" not in out:
                out["cpu_core_loads"] = psutil.cpu_percent(interval=None, percpu=True)
            if "cpu_clock" not in out:
                f = psutil.cpu_freq()
                if f:
                    out["cpu_clock"] = round(f.current)
            vm = psutil.virtual_memory()
            out.setdefault("ram_used", round(vm.used / (1024**3), 2))
            out.setdefault("ram_free", round(vm.available / (1024**3), 2))
            out.setdefault("ram_load", vm.percent)
            out["ram_total"] = self.ram_total_gb
        except Exception:
            pass

        # --- battery (laptops only) ----------------------------------------
        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                out["batt_pct"] = round(float(batt.percent), 1)
                out["batt_plugged"] = 1.0 if batt.power_plugged else 0.0
                secs = batt.secsleft
                # psutil reports sentinels for "charging" and "unknown"
                if isinstance(secs, int) and secs >= 0:
                    out["batt_minutes"] = round(secs / 60.0)
        except Exception:
            pass

        # --- sanity filtering ----------------------------------------------
        # AMD's driver reports 65535 (and occasionally 65534) as "unsupported"
        # for some counters; those must never reach the overlay.
        for k, v in list(out.items()):
            if isinstance(v, float) and v >= 65534.0:
                out.pop(k, None)
        # percentages must be 0-100
        for k in ("cpu_load", "cpu_load_max", "gpu_load", "gpu_mem_load",
                  "ram_load", "gpu_fan_pct", "vram_pct"):
            v = out.get(k)
            if v is not None and not (0.0 <= float(v) <= 100.0):
                out.pop(k, None)
        # temperatures outside a plausible range mean "no sensor"
        for k in ("cpu_temp", "cpu_temp_avg", "gpu_temp", "gpu_hotspot",
                  "gpu_mem_temp"):
            v = out.get(k)
            if v is not None and not (1.0 <= float(v) <= 130.0):
                out.pop(k, None)

        # derived
        if "vram_used" not in out and "vram_used_d3d" in out:
            out["vram_used"] = out["vram_used_d3d"]
        if "gpu_load" not in out and "gpu_load_d3d" in out:
            out["gpu_load"] = out["gpu_load_d3d"]
        vu, vt = out.get("vram_used"), out.get("vram_total")
        if vu and vt:
            out["vram_pct"] = round(100.0 * vu / vt, 1)
        # GB variants (LHM reports VRAM in MB; 1 GB = 1024 MB here to match
        # how GPU vendors and Task Manager report video memory)
        if vu is not None:
            out["vram_used_gb"] = vu / 1024.0
        if vt is not None:
            out["vram_total_gb"] = vt / 1024.0
        if vu is not None and vt is not None:
            out["vram_free_gb"] = max(0.0, (vt - vu) / 1024.0)
        # CPU package power of exactly 0 W means the ring0 driver is absent
        if out.get("cpu_power") == 0.0:
            out.pop("cpu_power", None)

        out["_ts"] = time.time()
        return out
