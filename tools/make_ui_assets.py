"""
Generate the small UI glyphs the stylesheet needs.

Qt stylesheets cannot draw a chevron, and overriding ::drop-down removes the
native one, which left dropdowns looking exactly like text fields. These are
tiny PNGs referenced from the stylesheet, one set per theme so the arrow
contrasts with its background.

    python tools/make_ui_assets.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "ui")

# arrow colour per theme: muted, but clearly visible against the input
COLOURS = {"dark": (139, 147, 161, 255), "light": (95, 107, 122, 255)}
SCALE = 4  # draw large, downsample: cheap antialiasing


def chevron(colour, size=14, thickness=2):
    s = size * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = s * 0.26
    mid = s / 2
    d.line(
        [(pad, mid - s * 0.12), (mid, mid + s * 0.16),
         (s - pad, mid - s * 0.12)],
        fill=colour, width=thickness * SCALE, joint="curve",
    )
    return img.resize((size, size), Image.LANCZOS)


def triangle(colour, size=9, up=False):
    s = size * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = s * 0.22
    if up:
        pts = [(m, s - m), (s - m, s - m), (s / 2, m)]
    else:
        pts = [(m, m), (s - m, m), (s / 2, s - m)]
    d.polygon(pts, fill=colour)
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    written = []
    for theme, colour in COLOURS.items():
        for name, img in (
            (f"chevron_{theme}.png", chevron(colour)),
            (f"up_{theme}.png", triangle(colour, up=True)),
            (f"down_{theme}.png", triangle(colour, up=False)),
        ):
            p = os.path.join(OUT, name)
            img.save(p)
            written.append(os.path.relpath(p, ROOT))
    for w in written:
        print(f"wrote {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
