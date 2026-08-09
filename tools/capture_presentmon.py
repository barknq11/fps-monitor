"""
Diagnostic: measure how PresentMon actually delivers its CSV rows.

Runs PresentMon exactly the way fpsmon/fps.py does, but records the arrival
time of every single row. This answers the question the overlay depends on:
do rows stream out one at a time, or arrive in buffered bursts?

Writes a report to logs/presentmon_diag.txt. Contains no personal data beyond
the names of processes that are currently rendering.
"""

from __future__ import annotations

import collections
import ctypes
import os
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PRESENTMON = os.path.join(ROOT, "vendor", "PresentMon.exe")
LOG_DIR = os.path.join(ROOT, "logs")
REPORT = os.path.join(LOG_DIR, "presentmon_diag.txt")
DURATION = 20.0
CREATE_NO_WINDOW = 0x08000000


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def main() -> int:
    os.makedirs(LOG_DIR, exist_ok=True)
    out = open(REPORT, "w", encoding="utf-8")

    def w(line: str = "") -> None:
        print(line)
        out.write(line + "\n")

    w("PresentMon delivery diagnostic")
    w("=" * 60)
    w(f"elevated: {is_admin()}")
    w(f"presentmon: {PRESENTMON}")
    if not is_admin():
        w("")
        w("NOT ELEVATED -- PresentMon cannot open an ETW session.")
        w("Run 'Diagnose PresentMon.bat' instead so it can request elevation.")
        out.close()
        return 1
    if not os.path.exists(PRESENTMON):
        w("PresentMon.exe missing from vendor/")
        out.close()
        return 1

    cmd = [
        PRESENTMON,
        "--output_stdout",
        "--no_console_stats",
        "--stop_existing_session",
        "--v2_metrics",
        "--session_name", "FPSMonitorDiag",
    ]
    w(f"command: {' '.join(cmd[1:])}")
    w(f"capturing for {DURATION:.0f}s -- have a game running NOW")
    w("")

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, text=True, bufsize=1,
        creationflags=CREATE_NO_WINDOW,
    )

    header: list[str] | None = None
    rows: list[tuple[float, str]] = []   # (arrival monotonic, raw line)
    t0 = time.monotonic()
    try:
        for raw in proc.stdout:  # type: ignore[union-attr]
            now = time.monotonic()
            line = raw.strip()
            if not line:
                continue
            if header is None:
                header = [h.strip() for h in line.split(",")]
                continue
            rows.append((now, line))
            if now - t0 > DURATION:
                break
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        # terminate() kills PresentMon before it can close its realtime ETW
        # session. An orphaned session keeps the present providers and makes
        # every later capture silently return nothing, so always tear it down.
        try:
            subprocess.run(
                ["logman", "stop", "FPSMonitorDiag", "-ets"],
                capture_output=True, timeout=15,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception:
            pass

    if header is None:
        err = ""
        try:
            err = (proc.stderr.read() or "")[:1000]  # type: ignore[union-attr]
        except Exception:
            pass
        w("No CSV header was produced. stderr follows:")
        w(err)
        out.close()
        return 1

    w("--- CSV header -------------------------------------------------")
    for i, h in enumerate(header):
        w(f"  [{i:2d}] {h}")
    low = [h.lower() for h in header]

    def find(*names: str) -> int:
        for nm in names:
            if nm in low:
                return low.index(nm)
        return -1

    i_app = find("application")
    i_pid = find("processid")
    i_ft = find("frametime", "msbetweenpresents")
    i_time = find("cpustarttime", "timeinseconds", "cpustartqpc", "cpustartqpctime")
    w("")
    w(f"  application col: {i_app}   processid col: {i_pid}")
    w(f"  frametime col:   {i_ft}    ({header[i_ft] if i_ft >= 0 else 'NOT FOUND'})")
    w(f"  timestamp col:   {i_time}  "
      f"({header[i_time] if i_time >= 0 else 'NOT FOUND'})")

    w("")
    w("--- delivery timing (THE key question) -------------------------")
    w(f"  rows captured: {len(rows)}")
    if len(rows) < 10:
        w("  too few rows -- was a game actually rendering?")
        out.close()
        return 1

    span = rows[-1][0] - rows[0][0]
    w(f"  wall time spanned: {span:.2f}s")
    w(f"  average row rate:  {len(rows) / max(span, 1e-9):.0f} rows/s")

    # how many rows share an arrival instant?
    buckets = collections.Counter(round(ts, 4) for ts, _ in rows)
    w(f"  distinct arrival timestamps (0.1ms resolution): {len(buckets)}")
    w(f"  rows per arrival instant: max {max(buckets.values())}, "
      f"mean {statistics.fmean(buckets.values()):.1f}")

    gaps = [rows[i][0] - rows[i - 1][0] for i in range(1, len(rows))]
    big = [g for g in gaps if g > 0.01]
    w(f"  gaps > 10ms between consecutive rows: {len(big)}")
    if big:
        w(f"  largest gap: {max(big) * 1000:.1f}ms, "
          f"median large gap: {statistics.median(big) * 1000:.1f}ms")

    burst_sizes = sorted(buckets.values(), reverse=True)[:10]
    w(f"  10 biggest bursts: {burst_sizes}")
    w("")
    if max(buckets.values()) > 3:
        w("  VERDICT: rows ARE delivered in bursts. Arrival time cannot be")
        w("           used to position frames -- the reconstruction in")
        w("           fps.py series() is required and correct.")
    else:
        w("  VERDICT: rows arrive individually. Bursting is NOT the cause;")
        w("           send this report back so the graph can be re-examined.")

    # per-process frame rate sanity check
    w("")
    w("--- processes seen ---------------------------------------------")
    per_pid: dict[str, int] = collections.Counter()
    fts: dict[str, list[float]] = collections.defaultdict(list)
    for _ts, line in rows:
        parts = line.split(",")
        if len(parts) <= max(i_pid, i_ft):
            continue
        key = f"{parts[i_app] if i_app >= 0 else '?'} (pid {parts[i_pid]})"
        per_pid[key] += 1
        try:
            fts[key].append(float(parts[i_ft]))
        except ValueError:
            pass
    for key, n in per_pid.most_common(6):
        vals = fts[key]
        if vals:
            med = statistics.median(vals)
            w(f"  {key}: {n} frames, median {med:.2f}ms "
              f"({1000.0 / med:.0f} FPS), max {max(vals):.1f}ms")

    if i_time >= 0:
        w("")
        w("--- sample of the timestamp column ------------------------------")
        for _ts, line in rows[:5]:
            parts = line.split(",")
            if len(parts) > i_time:
                w(f"  {header[i_time]} = {parts[i_time]}   "
                  f"frametime = {parts[i_ft]}")

    w("")
    w("--- first 3 raw rows -------------------------------------------")
    for _ts, line in rows[:3]:
        w("  " + line[:300])

    w("")
    w(f"report written to: {REPORT}")
    out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
