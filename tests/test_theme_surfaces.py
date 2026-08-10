"""Surfaces must be distinguishable from one another, in both themes.

The light theme originally reused the dark theme's values rather than its
relationships, which left inputs and cards at exactly the same colour: a text
field was invisible except for its border. Contrast against text was fine, so
the existing tests passed. These check surface-against-surface instead.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpsmon import theme  # noqa: E402

failures = []


def lum(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a: str, b: str) -> float:
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# A surface sitting inside another needs a visible step. These are modest
# thresholds: enough to see an edge without the interface looking striped.
MIN_STEP = 1.08          # neighbouring surfaces
MIN_HOVER = 1.10         # hover must be noticeable
MIN_TEXT = 4.5           # readable text
MIN_DIM = 3.0            # secondary text

print("=== surface separation ===")
for name, p in theme.THEMES.items():
    print(f"\n--- {name} ---")
    checks = [
        ("window vs card", p.bg, p.card, MIN_STEP),
        ("card vs input", p.card, p.sunk, MIN_STEP),
        ("card vs button", p.card, p.btn, MIN_STEP),
        ("window vs button", p.bg, p.btn, MIN_STEP),
        ("button rest vs hover", p.btn, p.btn_hover, MIN_HOVER),
        ("card vs row hover", p.card, p.hover, MIN_HOVER),
        ("input vs border", p.sunk, p.border, 1.2),
    ]
    for label, a, b, floor in checks:
        r = ratio(a, b)
        ok = r >= floor
        print(f"  {label:<22} {a} / {b}  {r:5.3f}:1  "
              f"(need {floor})  {'OK' if ok else 'TOO CLOSE'}")
        if not ok:
            failures.append(f"{name}: {label} only {r:.3f}:1, need {floor}")

print("\n=== text legibility on every surface it lands on ===")
for name, p in theme.THEMES.items():
    print(f"\n--- {name} ---")
    checks = [
        ("text on window", p.text, p.bg, MIN_TEXT),
        ("text on card", p.text, p.card, MIN_TEXT),
        ("text on input", p.text, p.sunk, MIN_TEXT),
        ("text on button", p.text, p.btn, MIN_TEXT),
        ("text on button hover", p.text, p.btn_hover, MIN_TEXT),
        ("dim on window", p.dim, p.bg, MIN_DIM),
        ("dim on card", p.dim, p.card, MIN_DIM),
        ("on-accent", p.on_accent, p.accent, MIN_TEXT),
    ]
    for label, a, b, floor in checks:
        r = ratio(a, b)
        ok = r >= floor
        print(f"  {label:<22} {r:5.2f}:1  (need {floor})  "
              f"{'OK' if ok else 'LOW'}")
        if not ok:
            failures.append(f"{name}: {label} only {r:.2f}:1, need {floor}")

print("\n=== status colours must be readable too ===")
for name, p in theme.THEMES.items():
    for label, colour in (("good", p.good), ("warn", p.warn), ("bad", p.bad)):
        r = ratio(colour, p.card)
        ok = r >= 3.0
        print(f"  {name:<6} {label:<5} on card  {r:5.2f}:1  "
              f"{'OK' if ok else 'LOW'}")
        if not ok:
            failures.append(f"{name}: {label} on card only {r:.2f}:1")

print("\n=== both themes still define the same rules ===")


def selectors(css: str) -> set[str]:
    return {b.split("{")[0].strip() for b in css.split("}") if "{" in b}


d, l = selectors(theme.stylesheet("dark")), selectors(theme.stylesheet("light"))
print(f"  dark {len(d)} rules, light {len(l)} rules, identical: {d == l}")
if d != l:
    failures.append(f"themes differ in rules: {d ^ l}")

print("\n=== interactive states are actually defined ===")
css = theme.stylesheet("light")
for needle in ("QPushButton:hover", "QPushButton:pressed",
               "QPushButton:disabled", "QPushButton:focus",
               "QLineEdit:hover", "QLineEdit:focus",
               "QListWidget::item:hover"):
    ok = needle in css
    print(f"  {needle:<26} {'OK' if ok else 'MISSING'}")
    if not ok:
        failures.append(f"{needle} has no styling")

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
