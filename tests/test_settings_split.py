"""App-wide settings must survive a profile switch.

Hotkeys, poll rate and visibility used to live inside every profile, so a
per-game profile activating mid-session silently rebound the user's keys.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from fpsmon import config  # noqa: E402
from fpsmon.settings_ui import SettingsWindow  # noqa: E402

app = QApplication(sys.argv)
config.bootstrap()
failures = []

print("=== which settings belong to the app ===")
print(f"  {len(config.APP_KEYS)} keys: {', '.join(config.APP_KEYS)}")
for key in config.APP_KEYS:
    if key not in config.APP_DEFAULTS:
        failures.append(f"{key} has no default")

print("\n=== profiles no longer carry them ===")
prof = config.new_profile("SplitTest")
prof["hotkey_toggle"] = "ctrl+alt+z"
prof["visibility_mode"] = "always"
path = config.save_profile(prof)
with open(path, encoding="utf-8") as fh:
    written = json.load(fh)
leaked = [k for k in config.APP_KEYS if k in written]
print(f"  keys written to the file: {len(written)}")
print(f"  app keys that leaked in:  {leaked or 'none'}")
if leaked:
    failures.append(f"profile file still contains {leaked}")
for k in ("metrics", "font_size", "graph_enabled", "auto_for"):
    if k not in written:
        failures.append(f"profile lost {k}, which it should keep")
print(f"  look settings kept: metrics, font_size, graph_enabled, auto_for")

print("\n=== hotkeys survive a profile switch ===")
saved = config.load_app_settings()
original = dict(saved)
saved["hotkey_toggle"] = "ctrl+alt+j"
saved["update_interval"] = 0.8
config.save_app_settings(saved)

w = SettingsWindow(config.load_profile("Default"), lambda: "s",
                   config.load_app_settings())
print(f"  before switch: {w.app['hotkey_toggle']!r} "
      f"interval={w.app['update_interval']}")
before = w.app["hotkey_toggle"]

# switching profile is what used to clobber them
w.load_from_profile(config.load_profile("MangoHud"))
after = w.app["hotkey_toggle"]
print(f"  after switch:  {after!r} interval={w.app['update_interval']}")
print(f"  hotkey unchanged: {before == after}")
if before != after:
    failures.append(f"switching profile changed the hotkey: {before} -> {after}")
if w.hk_toggle.combo() != "ctrl+alt+j":
    failures.append(
        f"the hotkey widget shows {w.hk_toggle.combo()!r}, not the app setting"
    )

print("\n=== app settings persist on their own ===")
fresh = config.load_app_settings()
print(f"  reloaded: hotkey={fresh['hotkey_toggle']!r} "
      f"interval={fresh['update_interval']}")
if fresh["hotkey_toggle"] != "ctrl+alt+j":
    failures.append("app settings did not round trip through state.json")

print("\n=== upgrading keeps the hotkeys a user had configured ===")
state = config.load_state()
state.pop("app", None)                 # pretend this is an older install
state["active_profile"] = "LegacyTest"
config.save_state(state)
legacy = config.new_profile("LegacyTest")
legacy_path = config.profile_path("LegacyTest")
body = dict(legacy)
body["hotkey_toggle"] = "ctrl+alt+q"   # written the old way, inside the profile
body["update_interval"] = 1.5
with open(legacy_path, "w", encoding="utf-8") as fh:
    json.dump(body, fh, indent=2)

lifted = config.load_app_settings()
print(f"  lifted from the old profile: hotkey={lifted['hotkey_toggle']!r} "
      f"interval={lifted['update_interval']}")
if lifted["hotkey_toggle"] != "ctrl+alt+q":
    failures.append("an upgrading user would lose their hotkey")
if lifted["update_interval"] != 1.5:
    failures.append("an upgrading user would lose their poll rate")

# restore
os.remove(legacy_path)
os.remove(config.profile_path("SplitTest"))
config.save_app_settings(original)
st = config.load_state()
st["active_profile"] = "Default"
config.save_state(st)

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
