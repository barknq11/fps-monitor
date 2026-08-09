"""
Benchmark recorder: writes a per-sample CSV plus a summary of a run.
"""

from __future__ import annotations

import csv
import os
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from . import config

# columns recorded for every run regardless of overlay configuration
COLUMNS = [
    "elapsed_s", "app", "fps", "fps_1low", "fps_01low", "frametime",
    "frametime_max", "gpu_load", "gpu_temp", "gpu_hotspot", "gpu_clock",
    "gpu_power", "gpu_fan_rpm", "vram_used", "vram_used_gb",
    "cpu_load", "cpu_load_max",
    "cpu_temp", "cpu_clock", "cpu_power", "ram_load", "ram_used",
]


@dataclass
class Run:
    """A past benchmark, read back from its CSV."""

    path: str
    name: str = ""
    app: str = "unknown"
    when: str = ""
    summary: dict[str, Any] = field(default_factory=dict)

    def value(self, key: str) -> float | None:
        v = self.summary.get(key)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


def _parse_summary(path: str) -> dict[str, Any]:
    """Read the '# key,value' block appended when the run finished."""
    out: dict[str, Any] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.startswith("#"):
                    continue
                body = line[1:].strip()
                if not body or body == "summary":
                    continue
                key, _, val = body.partition(",")
                out[key.strip()] = val.strip()
    except Exception:
        pass
    return out


def load_runs(limit: int = 200) -> list[Run]:
    """Every recorded benchmark, newest first."""
    runs: list[Run] = []
    try:
        names = [
            f for f in os.listdir(config.LOG_DIR)
            if f.startswith("bench_") and f.lower().endswith(".csv")
        ]
    except Exception:
        return runs

    for fname in names:
        path = os.path.join(config.LOG_DIR, fname)
        summary = _parse_summary(path)
        stem = fname[len("bench_"):-len(".csv")]
        app, _, stamp = stem.rpartition("_")
        # the timestamp is date_time, so split one more time
        if "_" in app and not stamp.count("-"):
            app, _, stamp = stem.rpartition("_")
        parts = stem.split("_")
        when = "_".join(parts[-2:]) if len(parts) >= 2 else ""
        app_name = summary.get("app") or "_".join(parts[:-2]) or "unknown"
        runs.append(Run(
            path=path,
            name=fname,
            app=app_name,
            when=when.replace("_", " "),
            summary=summary,
        ))
    runs.sort(key=lambda r: os.path.getmtime(r.path), reverse=True)
    return runs[:limit]


def delete_run(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except Exception:
        return False


#: what a results table shows, in order
REPORT_ROWS = [
    ("fps_avg_frames", "Average FPS", "", True),
    ("fps_1low", "1% low", "", True),
    ("fps_01low", "0.1% low", "", True),
    ("fps_avg", "Average FPS (sampled)", "", True),
    ("frametime_avg", "Frame time avg", "ms", False),
    ("frametime_p99", "Frame time p99", "ms", False),
    ("frametime_max", "Frame time worst", "ms", False),
    ("stutter_pct", "Stutter", "%", False),
    ("gpu_load_avg", "GPU load avg", "%", True),
    ("gpu_temp_max", "GPU temp max", "C", False),
    ("gpu_power_avg", "GPU power avg", "W", False),
    ("cpu_load_avg", "CPU load avg", "%", False),
    ("cpu_temp_max", "CPU temp max", "C", False),
    ("duration_s", "Duration", "s", False),
    ("frames", "Frames captured", "", True),
]


class BenchmarkRecorder:
    def __init__(self) -> None:
        self.active = False
        self.path: str | None = None
        self._fh = None
        self._writer: csv.DictWriter | None = None
        self._t0 = 0.0
        self._samples: list[dict[str, Any]] = []
        self._frametimes: list[float] = []
        self.app_name = "unknown"

    def start(self, app_hint: str = "") -> str:
        if self.active:
            return self.path or ""
        os.makedirs(config.LOG_DIR, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        tag = "".join(c for c in app_hint if c.isalnum() or c in "-_") or "run"
        self.path = os.path.join(config.LOG_DIR, f"bench_{tag}_{stamp}.csv")
        self._fh = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=COLUMNS, extrasaction="ignore")
        self._writer.writeheader()
        self._t0 = time.perf_counter()
        self._samples = []
        self.app_name = app_hint or "unknown"
        self.active = True
        return self.path

    def sample(self, values: dict[str, Any]) -> None:
        if not self.active or self._writer is None:
            return
        row = {k: values.get(k) for k in COLUMNS}
        row["elapsed_s"] = round(time.perf_counter() - self._t0, 3)
        if values.get("app"):
            self.app_name = str(values["app"])
            row["app"] = self.app_name
        try:
            self._writer.writerow(row)
            self._samples.append(row)
        except Exception:
            pass

    def stop(self) -> dict[str, Any]:
        if not self.active:
            return {}
        self.active = False
        summary = self._summarise()
        try:
            if self._fh:
                self._fh.write("\n")
                self._fh.write("# summary\n")
                for k, v in summary.items():
                    self._fh.write(f"# {k},{v}\n")
                self._fh.close()
        except Exception:
            pass
        self._fh = None
        self._writer = None
        return summary

    def set_frametimes(self, frametimes: list[float]) -> None:
        """Raw frame times for the whole run, used for the percentile lows."""
        self._frametimes = [f for f in frametimes if f > 0]

    @staticmethod
    def _lows(frametimes: list[float]) -> dict[str, Any]:
        """True 1% and 0.1% lows: the mean FPS of the slowest N% of frames.

        Computing these from the 2 Hz sample stream instead would make the
        "1% low" of a one minute run the single worst three second average,
        which is a far weaker statistic than the one people compare.
        """
        n = len(frametimes)
        if n < 20:
            return {}
        worst = sorted(frametimes, reverse=True)
        out: dict[str, Any] = {"frames": n}
        for label, frac in (("fps_1low", 0.01), ("fps_01low", 0.001)):
            k = max(1, int(n * frac))
            out[label] = round(1000.0 / statistics.fmean(worst[:k]), 2)
        out["fps_avg_frames"] = round(1000.0 / statistics.fmean(frametimes), 2)
        out["frametime_p99"] = round(worst[max(0, n // 100)], 2)
        out["frametime_max"] = round(worst[0], 2)
        med = statistics.median(frametimes)
        spike = max(med * 1.8, med + 5.0)
        out["stutter_pct"] = round(
            100.0 * sum(1 for f in frametimes if f > spike) / n, 2
        )
        return out

    def _summarise(self) -> dict[str, Any]:
        if not self._samples:
            return {"samples": 0}
        out: dict[str, Any] = {
            "app": self.app_name,
            "duration_s": self._samples[-1]["elapsed_s"],
            "samples": len(self._samples),
        }
        for key in ("fps", "gpu_load", "gpu_temp", "gpu_power", "cpu_load",
                    "cpu_temp", "frametime"):
            vals = [
                float(s[key]) for s in self._samples
                if s.get(key) is not None and str(s[key]) != ""
            ]
            if not vals:
                continue
            out[f"{key}_avg"] = round(statistics.fmean(vals), 2)
            out[f"{key}_min"] = round(min(vals), 2)
            out[f"{key}_max"] = round(max(vals), 2)
        # Percentile lows come from every frame of the run when available.
        out.update(self._lows(getattr(self, "_frametimes", [])))
        return out
