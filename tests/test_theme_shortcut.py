"""Theme switching and Start Menu integration."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PREVIEW_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview"
)
os.makedirs(PREVIEW_DIR, exist_ok=True)

from PySide6.QtWidgets import QApplication  # noqa: E402

from fpsmon import config, shortcuts, theme  # noqa: E402
from fpsmon.settings_ui import SettingsWindow  # noqa: E402

app = QApplication(sys.argv)
config.bootstrap()
failures = []

# ============================================================ theme
print("=== palettes ===")
for name, pal in theme.THEMES.items():
    css = theme.stylesheet(name)
    print(f"  {name:<6} bg={pal.bg} text={pal.text} accent={pal.accent} "
          f"({len(css)} chars of QSS)")
    if pal.bg == pal.text:
        failures.append(f"{name}: background and text are the same colour")
    if "{" in css.replace("{{", "").replace("}}", "") and "}}" in css:
        pass  # formatted already

# both themes must define every rule: compare the selector sets
def selectors(css: str) -> set[str]:
    out = set()
    for block in css.split("}"):
        if "{" in block:
            out.add(block.split("{")[0].strip())
    return out


d, l = selectors(theme.stylesheet("dark")), selectors(theme.stylesheet("light"))
print(f"\n  dark rules: {len(d)}, light rules: {len(l)}")
if d != l:
    failures.append(f"themes differ in rules: {d ^ l}")
else:
    print("  both themes cover exactly the same rules")

print("\n=== dropdown / number field glyphs ===")
from fpsmon.paths import resource  # noqa: E402

for name in theme.THEMES:
    css = theme.stylesheet(name)
    for key in ("chevron", "up", "down"):
        path = resource("assets", "ui", f"{key}_{name}.png")
        exists = os.path.exists(path)
        referenced = path.replace("\\", "/") in css
        print(f"  {name:<6} {key:<8} file={'ok' if exists else 'MISSING':<7} "
              f"referenced in QSS={referenced}")
        if not exists:
            failures.append(f"{name}/{key}: glyph missing")
        if not referenced:
            failures.append(f"{name}/{key}: not referenced by the stylesheet")
    # a combo must be visually distinguishable from a spin box
    if "QComboBox::down-arrow" not in css:
        failures.append(f"{name}: dropdowns have no arrow")
    if "QSpinBox::up-arrow" not in css:
        failures.append(f"{name}: number fields have no stepper arrows")

print("\n=== contrast sanity (text vs background) ===")


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


for name, pal in theme.THEMES.items():
    for label, fg, bg in (
        ("text on window", pal.text, pal.bg),
        ("dim on window", pal.dim, pal.bg),
        ("text on card", pal.text, pal.card),
        ("on-accent", pal.on_accent, pal.accent),
    ):
        r = ratio(fg, bg)
        ok = r >= 4.5 if "dim" not in label else r >= 3.0
        print(f"  {name:<6} {label:<16} {r:5.2f}:1  {'OK' if ok else 'LOW'}")
        if not ok:
            failures.append(f"{name} {label} contrast only {r:.2f}:1")

# ============================================================ window
print("\n=== settings window renders in both themes ===")
w = SettingsWindow(config.load_profile("Default"), lambda: "status")
w.resize(940, 700)
w.show()
app.processEvents()
# the Graph page mixes dropdowns, number fields, colours and sliders, so it
# is the page worth capturing for a visual check
graph_page = next(
    (i for i in range(w.nav.count()) if w.nav.item(i).text() == "Graph"), 0
)
for name in ("dark", "light"):
    w.set_theme(name)
    w.nav.setCurrentRow(graph_page)
    app.processEvents()
    w.grab().save(os.path.join(PREVIEW_DIR, f"theme_{name}.png"))
    print(f"  {name}: applied, toggle reads {w.theme_toggle.text()!r}")
    if w.theme_name != name:
        failures.append(f"set_theme({name}) did not stick")

got = []
w.theme_changed.connect(lambda n: got.append(n))
w.set_theme("dark")
w._toggle_theme()
print(f"  toggling emitted: {got} (now {w.theme_name})")
if got != ["light"]:
    failures.append(f"toggle emitted {got}, expected ['light']")

# ============================================================ shortcut
print("\n=== Start Menu shortcut ===")
print(f"  folder:   {shortcuts.start_menu_dir()}")
print(f"  link:     {shortcuts.shortcut_path()}")
prog, args, cwd = shortcuts.target()
print(f"  target:   {prog}")
print(f"  args:     {args}")
print(f"  workdir:  {cwd}")
print(f"  icon:     {shortcuts.icon_path() or '(none)'}")
if not os.path.isdir(shortcuts.start_menu_dir()):
    failures.append("Start Menu folder does not exist")
if not os.path.exists(prog):
    failures.append(f"shortcut target does not exist: {prog}")

was_there = shortcuts.exists()
print(f"\n  existed before: {was_there}")
ok, msg = shortcuts.create()
print(f"  create -> {ok}: {msg}")
if not ok or not shortcuts.exists():
    failures.append("shortcut was not created")
else:
    size = os.path.getsize(shortcuts.shortcut_path())
    print(f"  .lnk written, {size} bytes")

if not was_there:
    ok2, msg2 = shortcuts.remove()
    print(f"  cleaned up -> {ok2}: {msg2}")
    if shortcuts.exists():
        failures.append("shortcut could not be removed")
else:
    print("  left in place (it was already there before this test)")

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
