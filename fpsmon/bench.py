"""
Benchmark recorder: writes a per-sample CSV plus a summary of a run.
"""

from __future__ import annotations

import csv
import os
import statistics
import time
from typing import Any

from . import config, metrics as M

# columns recorded for every run regardless of overlay configuration
COLUMNS = [
    "elapsed_s", "app", "fps", "fps_1low", "fps_01low", "frametime",
    "frametime_max", "gpu_load", "gpu_temp", "gpu_hotspot", "gpu_clock",
    "gpu_power", "gpu_fan_rpm", "vram_used", "vram_used_gb",
    "cpu_load", "cpu_load_max",
    "cpu_temp", "cpu_clock", "cpu_power", "ram_load", "ram_used",
]


class BenchmarkRecorder:
    def __init__(self) -> None:
        self.active = False
        self.path: str | None = None
        self._fh = None
        self._writer: csv.DictWriter | None = None
        self._t0 = 0.0
        self._samples: list[dict[str, Any]] = []
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
        fps_vals = [
            float(s["fps"]) for s in self._samples
            if s.get("fps") is not None and str(s["fps"]) != ""
        ]
        if len(fps_vals) >= 10:
            srt = sorted(fps_vals)
            out["fps_p1"] = round(srt[max(0, len(srt) // 100)], 2)
            out["fps_p5"] = round(srt[max(0, len(srt) // 20)], 2)
        return out
