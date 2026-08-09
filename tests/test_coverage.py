"""Why does the trace not reach the left edge?

Simulates the real pipeline: bursty delivery at 69 FPS with occasional slow
bursts, then measures how much of the graph window is actually covered.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpsmon import fps as fpsmod  # noqa: E402

WINDOW = 4.0
LAG = 1.17          # measured presentation delay
FT = 14.41          # 69 FPS, from the screenshot
RETENTION = WINDOW + 3.0

failures = []

print(f"graph window {WINDOW}s + render lag {LAG}s -> needs "
      f"{WINDOW + LAG:.2f}s of history")
print(f"retention configured: {RETENTION}s")
print(f"stream treated as idle after {fpsmod.STALE_SECONDS}s of silence")
print(f"history discarded only after "
      f"{RETENTION + fpsmod.HISTORY_GRACE}s of silence\n")

be = fpsmod.FPSBackend()
be.set_retention(RETENTION)

# --- simulate 30 s of bursty delivery -------------------------------------
sim_now = time.monotonic()
pm_clock = 0.0
next_burst = 0.0
burst_gaps = []
coverage = []
recreated = 0

st = None
pid = 4242
last_seen_sim = sim_now

BURSTS = [1.0] * 8 + [2.4] + [1.0] * 8 + [2.6] + [1.0] * 8  # two slow bursts

t = 0.0
for gap in BURSTS:
    # frames that occurred during this gap
    n = int(gap * 1000 / FT)
    t += gap
    arrival = sim_now + t

    # --- reaper: this is what the real backend does every second ----------
    reap_after = RETENTION + fpsmod.HISTORY_GRACE
    if st is not None and (arrival - last_seen_sim) > reap_after:
        st = None
        recreated += 1

    if st is None:
        st = fpsmod._Stream("game.exe", pid, RETENTION)

    for _ in range(n):
        pm_clock += FT
        # emulate _Stream.add with a controlled 'now'
        st.last_seen = arrival
        tt = pm_clock / 1000.0
        est = arrival - tt
        if st._pm_base is None or est < st._pm_base:
            st._pm_base = est
        elif est - st._pm_base > 2.0:
            st._pm_base = est
        st._has_pm = True
        st.times.append((tt, FT))
        cutoff = (arrival - st._pm_base) - st.retention - 1.0
        while st.times and st.times[0][0] < cutoff:
            st.times.popleft()
    last_seen_sim = arrival
    burst_gaps.append(gap)

    # --- how much of the window is covered right now? ---------------------
    base = st._pm_base
    newest = base + st.times[-1][0]
    oldest = base + st.times[0][0]
    render_now = arrival - LAG
    # visible span: how far left of render_now does data reach?
    covered = min(render_now - oldest, WINDOW)
    covered = max(covered, 0.0)
    coverage.append((round(t, 2), round(covered, 2), len(st.times)))

print("time   covered/4.00s   frames held")
for tt, cov, n in coverage:
    bar = "#" * int(cov / WINDOW * 30)
    flag = "  <-- SHORT" if cov < WINDOW - 0.15 else ""
    print(f"{tt:5.1f}s   {cov:4.2f}s  {n:5d}  |{bar:<30}|{flag}")

# The first few seconds legitimately have no history yet; judge steady state.
warmup = WINDOW + LAG
steady = [c for t_, c, _n in coverage if t_ >= warmup]
worst = min(steady) if steady else 0.0
print(f"\nstreams destroyed and rebuilt by the reaper: {recreated}")
print(f"worst coverage after {warmup:.1f}s warm-up: {worst:.2f}s of the "
      f"{WINDOW:.2f}s window ({worst / WINDOW * 100:.0f}%)")

if recreated:
    failures.append(
        f"reaper destroyed the stream {recreated}x -- history is lost and the "
        f"graph has to regrow from the right edge"
    )
if worst < WINDOW - 0.15:
    failures.append(f"window only {worst:.2f}s covered, so the left is empty")

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
