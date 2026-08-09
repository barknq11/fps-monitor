"""
Turn the app logo into a Windows .ico with all the sizes Windows expects.

Drop the logo PNG at assets/logo.png (any square size, 512px or larger is
ideal) and run this. It writes assets/icon.ico, which the app, the taskbar,
the tray and any future .exe all use.

    python tools/make_icon.py [path/to/logo.png]
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
DEFAULT_SRC = os.path.join(ASSETS, "logo.png")
OUT_ICO = os.path.join(ASSETS, "icon.ico")

# Windows picks the closest match from these; 256 is used by large icon views.
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    if not os.path.exists(src):
        print(f"No logo found at: {src}")
        print("Save the logo as assets/logo.png and run this again.")
        return 1

    try:
        from PIL import Image
    except ImportError:
        print("Pillow is required:  python -m pip install Pillow")
        return 1

    os.makedirs(ASSETS, exist_ok=True)
    img = Image.open(src).convert("RGBA")

    # Square it off without distorting: pad the shorter side transparently.
    if img.width != img.height:
        side = max(img.width, img.height)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
        img = canvas

    if src != DEFAULT_SRC:
        img.save(DEFAULT_SRC)
        print(f"copied logo -> {DEFAULT_SRC}")

    # A detailed logo turns to mush at tray size, so the small entries are
    # rendered from a centre crop: the recognisable part fills the pixels
    # instead of the whole frame shrinking into 16x16.
    def cropped(fraction: float) -> "Image.Image":
        side = int(img.width * fraction)
        off = (img.width - side) // 2
        return img.crop((off, off, off + side, off + side))

    tight = cropped(0.66)
    frames = []
    for s in SIZES:
        src = tight if s <= 32 else img
        frames.append(src.resize((s, s), Image.LANCZOS))

    frames[0].save(
        OUT_ICO, format="ICO", sizes=[(s, s) for s in SIZES],
        append_images=frames[1:],
    )
    print(f"wrote {OUT_ICO}")
    print(f"  source {img.width}x{img.height}, embedded sizes: {SIZES}")
    print("  sizes <= 32px use a centre crop so they stay legible")

    # A small PNG is handy for the settings header.
    img.resize((64, 64), Image.LANCZOS).save(
        os.path.join(ASSETS, "logo_64.png")
    )
    print(f"wrote {os.path.join(ASSETS, 'logo_64.png')}")

    # Side-by-side comparison so the small sizes can actually be judged.
    preview_dir = os.path.join(ROOT, "preview")
    os.makedirs(preview_dir, exist_ok=True)
    shown = [16, 24, 32, 48, 64, 128]
    pad, y = 10, 150
    width = sum(s + pad for s in shown) * 2 + pad
    sheet = Image.new("RGBA", (width, y), (27, 31, 36, 255))
    x = pad
    for s in shown:                      # full logo, scaled down
        sheet.paste(img.resize((s, s), Image.LANCZOS), (x, 20), img.resize((s, s), Image.LANCZOS))
        x += s + pad
    x += pad * 2
    for s in shown:                      # centre-cropped
        c = tight.resize((s, s), Image.LANCZOS)
        sheet.paste(c, (x, 20), c)
        x += s + pad
    sheet.save(os.path.join(preview_dir, "icon_sizes.png"))
    print(f"wrote {os.path.join(preview_dir, 'icon_sizes.png')} "
          f"(left: full logo, right: centre crop)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
