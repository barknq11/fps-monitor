"""Version comparison, update check, per-game profiles and error logging."""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpsmon import __version__, config, errors, updates  # noqa: E402

failures = []

# ==================================================== version comparison
print(f"=== version handling (app reports {__version__}) ===")
CASES = [
    ("1.1.0", "1.0.0", True,  "patch/minor bump is newer"),
    ("v1.1.0", "1.1.0", False, "same version, v prefix ignored"),
    ("1.0.0", "1.1.0", False, "older release is not an update"),
    ("2.0.0", "1.9.9", True,  "major bump"),
    ("1.1", "1.1.0", False,  "1.1 and 1.1.0 are the same"),
    ("1.1.1", "1.1", True,   "1.1.1 beats 1.1"),
    ("1.10.0", "1.9.0", True, "10 sorts above 9, not below"),
    ("garbage", "1.0.0", False, "unparseable tags never trigger an update"),
]
for cand, cur, expect, why in CASES:
    got = updates.is_newer(cand, cur)
    ok = got == expect
    print(f"  {cand:>9} vs {cur:<8} -> {str(got):<5} {'OK' if ok else 'BAD'}   {why}")
    if not ok:
        failures.append(f"is_newer({cand},{cur}) was {got}")

print(f"\n  parse_version('v2.3.4') = {updates.parse_version('v2.3.4')}")

# ==================================================== live check
print("\n=== live check against GitHub ===")
rel = updates.latest_release()
if rel is None:
    print("  no release info (offline or rate limited) - handled without error")
else:
    print(f"  latest published: {rel.tag}  {rel.url}")
    print(f"  newer than us:    {updates.is_newer(rel.version, __version__)}")

print("  a bad repo must fail quietly, not raise:")
bad = updates.latest_release("barknq11/definitely-not-a-real-repo-xyz")
print(f"    -> {bad}")
if bad is not None:
    failures.append("a nonexistent repo returned something")

# ==================================================== per-game profiles
print("\n=== per-game profile matching ===")
config.bootstrap()
test_name = "AutoSwitchTest"
prof = config.new_profile(test_name)
prof["auto_for"] = ["cs2.exe", "EldenRing.exe"]
config.save_profile(prof)

for exe, expect in (
    ("cs2.exe", test_name),
    ("CS2.EXE", test_name),
    (r"D:\Games\cs2.exe", test_name),
    ("eldenring.exe", test_name),
    ("notagame.exe", None),
    ("", None),
):
    got = config.profile_for_executable(exe)
    ok = got == expect
    print(f"  {str(exe):<26} -> {str(got):<18} {'OK' if ok else 'BAD'}")
    if not ok:
        failures.append(f"profile_for_executable({exe!r}) = {got!r}")

print("\n  profiles with no auto_for never claim a game:")
plain = config.load_profile("Default")
print(f"    Default auto_for = {plain.get('auto_for')}")
if plain.get("auto_for"):
    failures.append("the Default profile claims games out of the box")

os.remove(config.profile_path(test_name))

# ==================================================== error logging
print("\n=== error logging ===")
path = errors.log_path()
before = os.path.getsize(path) if os.path.exists(path) else 0
print(f"  log: {path}")

heard = []
errors.add_listener(lambda s: heard.append(s))
errors.install()


def boom():
    raise ValueError("deliberate test failure, not a real problem")


try:
    boom()
except Exception as exc:
    errors.report("test harness", exc)

time.sleep(0.2)
after = os.path.getsize(path) if os.path.exists(path) else 0
print(f"  file grew: {before} -> {after} bytes")
print(f"  listener heard: {heard[-1] if heard else '(nothing)'}")
if after <= before:
    failures.append("nothing was written to the error log")
if not heard:
    failures.append("listeners were not notified")
if "deliberate test failure" not in errors.last_error():
    failures.append(f"last_error is {errors.last_error()!r}")

print("\n  an exception on a background thread is captured too:")
count_before = len(heard)


def thread_boom():
    raise RuntimeError("failure inside a worker thread")


t = threading.Thread(target=thread_boom, name="test-worker")
t.start()
t.join()
time.sleep(0.3)
print(f"    listener fired again: {len(heard) > count_before}")
print(f"    latest: {errors.last_error()}")
if len(heard) <= count_before:
    failures.append("a thread exception was not logged")

with open(path, encoding="utf-8", errors="replace") as fh:
    tail = fh.read()[-800:]
print("\n  tail of the log:")
for line in tail.strip().splitlines()[-6:]:
    print(f"    {line[:100]}")

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
