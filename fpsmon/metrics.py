"""
Metric registry: the single source of truth for what the overlay can display.

Each metric declares how to label it, how to format its value, its unit, and
optional warning/critical thresholds used for colour coding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Metric:
    id: str
    label: str  # short label shown in the overlay
    long_label: str  # descriptive name shown in the settings UI
    unit: str
    group: str  # FPS / CPU / GPU / RAM
    fmt: Callable[[Any], str]
    warn: float | None = None  # value at which the number turns amber
    crit: float | None = None  # value at which it turns red
    higher_is_worse: bool = True


def _i(v: Any) -> str:  # integer
    return f"{float(v):.0f}"


def _1(v: Any) -> str:  # one decimal
    return f"{float(v):.1f}"


def _2(v: Any) -> str:
    return f"{float(v):.2f}"


def _ghz(v: Any) -> str:
    return f"{float(v) / 1000:.2f}"


METRICS: list[Metric] = [
    # ---- FPS -------------------------------------------------------------
    Metric("fps", "FPS", "Frames per second", "", "FPS", _i,
           warn=45, crit=30, higher_is_worse=False),
    Metric("fps_1low", "1% LOW", "1% low FPS", "", "FPS", _i,
           warn=40, crit=25, higher_is_worse=False),
    Metric("fps_01low", "0.1% LOW", "0.1% low FPS", "", "FPS", _i,
           warn=30, crit=20, higher_is_worse=False),
    Metric("frametime", "FRAME", "Frame time", "ms", "FPS", _2, warn=22, crit=33),
    Metric("frametime_max", "MAX FT", "Worst frame time in window", "ms", "FPS", _2,
           warn=33, crit=50),
    Metric("frametime_med", "MED FT", "Median frame time", "ms", "FPS", _2,
           warn=22, crit=33),
    Metric("frametime_jitter", "JITTER", "Frame-to-frame variation", "ms", "FPS",
           _2, warn=2.0, crit=5.0),
    Metric("stutter_pct", "STUTTER", "Frames over 1.5x median", "%", "FPS", _1,
           warn=2.0, crit=6.0),
    Metric("app", "APP", "Measured application", "", "FPS", str),
    # ---- CPU -------------------------------------------------------------
    Metric("cpu_load", "CPU", "CPU total usage", "%", "CPU", _i, warn=85, crit=95),
    Metric("cpu_load_max", "CPU MAX", "Busiest core usage", "%", "CPU", _i,
           warn=90, crit=99),
    Metric("cpu_temp", "CPU T", "CPU temperature", "°C", "CPU", _i,
           warn=75, crit=90),
    Metric("cpu_clock", "CPU CLK", "CPU peak core clock", "GHz", "CPU", _ghz),
    Metric("cpu_clock_avg", "CPU AVG CLK", "CPU average core clock", "GHz", "CPU", _ghz),
    Metric("cpu_power", "CPU W", "CPU package power", "W", "CPU", _i,
           warn=110, crit=140),
    Metric("cpu_volt", "CPU V", "CPU core voltage", "V", "CPU", _2),
    # ---- GPU -------------------------------------------------------------
    Metric("gpu_load", "GPU", "GPU core usage", "%", "GPU", _i, warn=98, crit=100),
    Metric("gpu_temp", "GPU T", "GPU core temperature", "°C", "GPU", _i,
           warn=80, crit=90),
    Metric("gpu_hotspot", "GPU HOT", "GPU hot spot temperature", "°C", "GPU", _i,
           warn=95, crit=105),
    Metric("gpu_mem_temp", "VRAM T", "GPU memory temperature", "°C", "GPU", _i,
           warn=90, crit=100),
    Metric("gpu_clock", "GPU CLK", "GPU core clock", "MHz", "GPU", _i),
    Metric("gpu_mem_clock", "MEM CLK", "GPU memory clock", "MHz", "GPU", _i),
    Metric("gpu_power", "GPU W", "GPU package power", "W", "GPU", _i,
           warn=200, crit=280),
    Metric("gpu_fan_rpm", "FAN", "GPU fan speed", "RPM", "GPU", _i),
    Metric("gpu_fan_pct", "FAN %", "GPU fan duty cycle", "%", "GPU", _i),
    Metric("gpu_volt", "GPU V", "GPU core voltage", "V", "GPU", _2),
    # ---- VRAM (own group so it can be coloured separately) ---------------
    Metric("vram_used_gb", "VRAM", "VRAM used (GB)", "GB", "VRAM", _1),
    Metric("vram_total_gb", "VRAM TOT", "VRAM total (GB)", "GB", "VRAM", _1),
    Metric("vram_free_gb", "VRAM FREE", "VRAM free (GB)", "GB", "VRAM", _1,
           higher_is_worse=False, warn=1.5, crit=0.6),
    Metric("vram_used", "VRAM", "VRAM used (MB)", "MB", "VRAM", _i),
    Metric("vram_pct", "VRAM %", "VRAM used", "%", "VRAM", _i, warn=90, crit=97),
    Metric("gpu_mem_load", "MEM CTRL", "Memory controller load", "%", "GPU", _i),
    # ---- RAM -------------------------------------------------------------
    Metric("ram_load", "RAM", "System RAM usage", "%", "RAM", _i, warn=85, crit=95),
    Metric("ram_used", "RAM USED", "System RAM used", "GB", "RAM", _1),
    Metric("ram_free", "RAM FREE", "System RAM available", "GB", "RAM", _1,
           higher_is_worse=False, warn=4, crit=2),
    # ---- battery (laptops; absent on desktops) ---------------------------
    Metric("batt_pct", "BATT", "Battery charge", "%", "BATTERY", _i,
           higher_is_worse=False, warn=25, crit=10),
    Metric("batt_minutes", "BATT LEFT", "Battery time remaining", "min",
           "BATTERY", _i, higher_is_worse=False, warn=30, crit=10),
    Metric("batt_plugged", "AC", "On mains power (1 = yes)", "", "BATTERY", _i),
]

BY_ID: dict[str, Metric] = {m.id: m for m in METRICS}
GROUPS: list[str] = ["FPS", "CPU", "GPU", "VRAM", "RAM", "BATTERY"]


def format_value(metric: Metric, value: Any) -> str:
    try:
        return metric.fmt(value)
    except Exception:
        return "--"


def state_for(metric: Metric, value: Any) -> str:
    """Return 'ok' | 'warn' | 'crit' for threshold colouring."""
    if metric.warn is None or value is None:
        return "ok"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "ok"
    if metric.higher_is_worse:
        if metric.crit is not None and v >= metric.crit:
            return "crit"
        if v >= metric.warn:
            return "warn"
    else:
        if metric.crit is not None and v <= metric.crit:
            return "crit"
        if v <= metric.warn:
            return "warn"
    return "ok"
