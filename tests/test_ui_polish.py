"""Hotkey capture, metric search, reset actions and window geometry."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PREVIEW_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview"
)
os.makedirs(PREVIEW_DIR, exist_ok=True)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fpsmon import config, hotkeys  # noqa: E402
from fpsmon.settings_ui import SettingsWindow  # noqa: E402
from fpsmon.widgets import HotkeyEdit, key_event_to_combo  # noqa: E402

app = QApplication(sys.argv)
config.bootstrap()
failures = []


def press(key, mods=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QKeyEvent.Type.KeyPress, key, mods)


# ================================================== key event -> combo
print("=== capturing key presses ===")
CASES = [
    (Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier
     | Qt.KeyboardModifier.AltModifier, "ctrl+alt+f"),
    (Qt.Key.Key_F9, Qt.KeyboardModifier.ShiftModifier, "shift+f9"),
    (Qt.Key.Key_5, Qt.KeyboardModifier.ControlModifier, "ctrl+5"),
    (Qt.Key.Key_Home, Qt.KeyboardModifier.AltModifier, "alt+home"),
    (Qt.Key.Key_F12, Qt.KeyboardModifier.ControlModifier
     | Qt.KeyboardModifier.ShiftModifier
     | Qt.KeyboardModifier.AltModifier, "ctrl+alt+shift+f12"),
    (Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier, None),
    (Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier, None),
]
for key, mods, expect in CASES:
    got = key_event_to_combo(press(key, mods))
    ok = got == expect
    label = "modifier alone -> ignored" if expect is None else expect
    print(f"  {str(key):<28} -> {str(got):<22} {'OK' if ok else 'BAD'}  ({label})")
    if not ok:
        failures.append(f"{key}: got {got!r}, expected {expect!r}")

print("\n  every captured combo must be registrable:")
for key, mods, expect in CASES:
    if expect is None:
        continue
    parsed = hotkeys.parse_combo(expect)
    print(f"    {expect:<22} parse_combo -> {parsed}")
    if parsed is None:
        failures.append(f"{expect} captured but cannot be registered")

# ================================================== the widget itself
print("\n=== HotkeyEdit behaviour ===")
w = HotkeyEdit("ctrl+alt+f")
print(f"  initial label: {w.text()!r}")
if "Ctrl" not in w.text():
    failures.append("existing combo not shown in a readable form")

got = []
w.changed.connect(lambda c: got.append(c))

w._on_click()
print(f"  after click:   {w.text()!r}")
if not w._capturing:
    failures.append("clicking did not start capture")

w.keyPressEvent(press(Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier
                      | Qt.KeyboardModifier.AltModifier))
print(f"  pressed ctrl+alt+b -> combo={w.combo()!r} label={w.text()!r}")
if w.combo() != "ctrl+alt+b":
    failures.append(f"capture produced {w.combo()!r}")
if got != ["ctrl+alt+b"]:
    failures.append(f"changed emitted {got}")

w._on_click()
w.keyPressEvent(press(Qt.Key.Key_Escape))
print(f"  Esc cancels    -> combo unchanged: {w.combo()!r}")
if w.combo() != "ctrl+alt+b":
    failures.append("Esc did not cancel cleanly")

w._on_click()
w.keyPressEvent(press(Qt.Key.Key_Backspace))
print(f"  Backspace      -> combo cleared: {w.combo()!r}")
if w.combo() != "":
    failures.append("Backspace did not clear the binding")

# ================================================== window integration
print("\n=== settings window ===")
s = SettingsWindow(config.load_profile("Default"), lambda: "status")
s.resize(940, 700)
s.show()
app.processEvents()

print("  duplicate detection:")
s.hk_toggle.set_combo("ctrl+alt+x")
s.hk_bench.set_combo("ctrl+alt+x")
s._on_hotkey_changed()
warned = bool(s.hk_toggle._warning) and bool(s.hk_bench._warning)
print(f"    two actions on ctrl+alt+x -> warned: {warned}")
print(f"    message: {s.hk_bench._warning!r}")
if not warned:
    failures.append("duplicate hotkeys were not flagged")

s.hk_bench.set_combo("ctrl+alt+y")
s._on_hotkey_changed()
print(f"    after changing one -> warnings cleared: "
      f"{not s.hk_toggle._warning and not s.hk_bench._warning}")
if s.hk_toggle._warning or s.hk_bench._warning:
    failures.append("warnings not cleared once the clash was resolved")

print("\n  metric search:")
total = s.metric_list.count()


def visible():
    return sum(
        1 for i in range(s.metric_list.count())
        if not s.metric_list.item(i).isHidden()
    )


s.metric_search.setText("")
app.processEvents()
base = visible()
s.metric_search.setText("temp")
app.processEvents()
after = visible()
print(f"    {total} rows total, {base} visible unfiltered, "
      f"{after} matching 'temp'")
if after >= base or after == 0:
    failures.append(f"search did not filter usefully ({base} -> {after})")

shown_headers = [
    # headers are decorated with box-drawing characters a cp1252 console
    # cannot print, so compare on the plain name
    s.metric_list.item(i).text().strip("- ─").strip()
    for i in range(s.metric_list.count())
    if not s.metric_list.item(i).data(Qt.ItemDataRole.UserRole)
    and not s.metric_list.item(i).isHidden()
]
print(f"    group headers still shown: {shown_headers}")
if "FPS" in shown_headers:
    failures.append("a group with no matching metric is still shown")

s.metric_search.setText("zzzznothing")
app.processEvents()
print(f"    nonsense query -> {visible()} visible (should be 0)")
if visible() != 0:
    failures.append("a nonsense query still shows rows")

s.metric_search.setText("")
app.processEvents()
print(f"    cleared -> {visible()} visible again")
if visible() != base:
    failures.append("clearing the search did not restore the list")

print("\n  geometry round trip:")
s.setGeometry(220, 140, 900, 640)
app.processEvents()
geo = s.geometry_dict()
print(f"    saved:    {geo}")
s2 = SettingsWindow(config.load_profile("Default"), lambda: "status")
s2.restore_geometry(geo)
app.processEvents()
print(f"    restored: {s2.geometry_dict()}")
if s2.geometry_dict() != geo:
    failures.append(f"geometry not restored: {s2.geometry_dict()} != {geo}")

s2.restore_geometry({"x": -99999, "y": -99999, "w": 800, "h": 600})
app.processEvents()
off = s2.geometry_dict()
print(f"    off-screen position ignored -> {off}")
if off["x"] == -99999:
    failures.append("restored a window onto a monitor that does not exist")

s.nav.setCurrentRow(
    next(i for i in range(s.nav.count()) if s.nav.item(i).text() == "Behaviour")
)
app.processEvents()
s.grab().save(os.path.join(PREVIEW_DIR, "ui_hotkeys.png"))
s.nav.setCurrentRow(0)
s.metric_search.setText("gpu")
app.processEvents()
s.grab().save(os.path.join(PREVIEW_DIR, "ui_search.png"))

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
