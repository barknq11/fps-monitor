"""
Themes for the control panel.

The stylesheet is generated from a palette rather than written out per theme,
so light and dark cannot drift apart: adding a rule once covers both.

This styles the settings window only. The overlay's own colours are part of
each profile, because what reads well over a game is a separate question from
what reads well in a window.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str          # window
    sunk: str        # sidebar, inputs
    card: str        # group boxes
    hover: str
    border: str
    text: str
    dim: str         # secondary text
    accent: str
    accent_dim: str
    on_accent: str   # text on an accent background
    good: str
    warn: str
    bad: str
    handle: str      # slider knob, scrollbar
    # Buttons need their own surfaces. Using the hover colour as the resting
    # fill left nothing for hover to change except the border, which is why
    # the interface felt inert.
    btn: str = ""
    btn_hover: str = ""

    def __post_init__(self):
        if not self.btn:
            object.__setattr__(self, "btn", self.hover)
        if not self.btn_hover:
            object.__setattr__(self, "btn_hover", self.border)


DARK = Palette(
    name="dark",
    bg="#14171c",
    sunk="#0f1216",
    card="#1b1f26",
    hover="#222833",
    border="#2a3038",
    text="#e6e9ef",
    dim="#8b93a1",
    # #4c8dff looked better but gave white-on-accent only 3.2:1, under the
    # 4.5:1 needed for readable text. This measures 4.65:1.
    accent="#2f6fe4",
    accent_dim="#2559b8",
    on_accent="#ffffff",
    good="#3ddc84",
    warn="#ffc400",
    bad="#ff4d4f",
    handle="#ffffff",
    btn="#272f3b",
    btn_hover="#343f4e",
)

# A light theme cannot be the dark one with the numbers flipped. In dark,
# "recessed" reads as darker than its container; copying that literally made
# inputs pure white on white cards, so a text field was invisible except for
# its border. Here cards are the lightest surface and everything set into
# them is progressively greyer, which is how depth reads on a light UI.
LIGHT = Palette(
    name="light",
    bg="#eef1f6",          # window: clearly darker than a card
    sunk="#eff2f7",        # inputs: set into the card, not level with it
    card="#ffffff",        # raised surface, the lightest thing on screen
    hover="#dfe5ee",       # obvious against both the window and a card
    border="#c3ccd9",      # strong enough to define a field on its own
    text="#171c24",
    dim="#5a6675",
    accent="#2f6fe4",
    accent_dim="#2559b8",
    on_accent="#ffffff",
    good="#1a8a4f",
    warn="#a06a00",
    bad="#c62828",
    handle="#ffffff",
    # distinct from BOTH the white card and the window, because buttons
    # appear on each
    btn="#dde4ef",
    btn_hover="#c9d5e8",
)

THEMES = {"dark": DARK, "light": LIGHT}


def _glyphs(name: str) -> dict[str, str]:
    """Absolute, QSS-safe paths to the arrow images for a theme."""
    from .paths import resource

    out = {}
    for key in ("chevron", "up", "down"):
        p = resource("assets", "ui", f"{key}_{name}.png")
        # Qt stylesheets want forward slashes, and the path may contain spaces
        out[key] = p.replace("\\", "/")
    return out


def build(p: Palette) -> str:
    g = _glyphs(p.name)
    return f"""
QWidget {{
    background: {p.bg};
    color: {p.text};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}

/* labels must not paint their own panel colour inside cards */
QLabel, QCheckBox {{ background: transparent; }}

/* ---------- sidebar ---------- */
QWidget#Side {{
    background: {p.sunk};
    border-right: 1px solid {p.border};
}}
QWidget#Brand {{
    background: transparent;
    border-bottom: 1px solid {p.border};
}}
QLabel#BrandName {{
    font-size: 15px;
    font-weight: 700;
    color: {p.text};
}}
QListWidget#Nav {{
    background: {p.sunk};
    border: none;
    outline: 0;
    padding: 10px 8px;
}}
QListWidget#Nav::item {{
    padding: 10px 14px;
    margin: 2px 4px;
    border-radius: 8px;
    color: {p.dim};
}}
QListWidget#Nav::item:hover {{
    background: {p.hover};
    color: {p.text};
}}
QListWidget#Nav::item:selected {{
    background: {p.accent};
    color: {p.on_accent};
    font-weight: 600;
}}

/* ---------- theme toggle ---------- */
QPushButton#ThemeToggle {{
    background: transparent;
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 5px 10px;
    color: {p.dim};
    font-weight: 600;
    text-align: left;
}}
QPushButton#ThemeToggle:hover {{
    background: {p.hover};
    color: {p.text};
    border-color: {p.accent};
}}

/* ---------- headings ---------- */
QLabel#Title {{
    font-size: 20px;
    font-weight: 700;
    padding: 2px 0 0 0;
}}
QLabel#Subtitle {{
    color: {p.dim};
    font-size: 12px;
    padding-bottom: 6px;
}}
QLabel#SectionHint {{
    color: {p.dim};
    font-size: 12px;
}}
QLabel#Status {{
    color: {p.dim};
    font-size: 12px;
    background: {p.sunk};
    border-top: 1px solid {p.border};
    padding: 8px 14px;
}}

/* ---------- cards ---------- */
QGroupBox {{
    background: {p.card};
    border: 1px solid {p.border};
    border-radius: 10px;
    margin-top: 16px;
    padding: 14px 14px 10px 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    top: 2px;
    padding: 0 6px;
    color: {p.dim};
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}

/* Preview backdrop: a neutral dark panel regardless of theme, because the
   overlay is designed to sit over game imagery, not over a light UI. */
QWidget#PreviewStrip {{
    background: #0a0c10;
    border: 1px solid {p.border};
    border-radius: 8px;
}}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QFontComboBox {{
    background: {p.sunk};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 6px 9px;
    min-height: 20px;
    color: {p.text};
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover,
QComboBox:hover, QFontComboBox:hover {{
    border-color: {p.dim};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QFontComboBox:focus {{
    border: 1px solid {p.accent};
    background: {p.card};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled {{
    color: {p.dim};
    background: transparent;
}}
/* A dropdown must not look like a text field. It gets a divider and a
   chevron, so the control announces that it opens a list. */
QComboBox, QFontComboBox {{
    padding-right: 30px;
}}
QComboBox::drop-down, QFontComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    border-left: 1px solid {p.border};
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
    background: {p.hover};
}}
QComboBox::drop-down:hover, QFontComboBox::drop-down:hover {{
    background: {p.accent};
}}
QComboBox::down-arrow, QFontComboBox::down-arrow {{
    image: url("{g['chevron']}");
    width: 14px;
    height: 14px;
}}
QComboBox:disabled {{ color: {p.dim}; }}
QComboBox QAbstractItemView {{
    background: {p.card};
    color: {p.text};
    border: 1px solid {p.border};
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
    outline: 0;
}}
/* Number fields get stepper arrows, so they read as "type or nudge a
   value" rather than "pick from a list". */
QSpinBox, QDoubleSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border: none;
    border-top-right-radius: 7px;
    background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border: none;
    border-bottom-right-radius: 7px;
    background: transparent;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {p.hover};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{g['up']}");
    width: 9px; height: 9px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{g['down']}");
    width: 9px; height: 9px;
}}

/* ---------- buttons ---------- */
QPushButton {{
    background: {p.btn};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 7px 14px;
    font-weight: 600;
    color: {p.text};
}}
QPushButton:hover {{
    background: {p.btn_hover};
    border-color: {p.accent};
}}
QPushButton:pressed {{
    background: {p.accent};
    border-color: {p.accent};
    color: {p.on_accent};
}}
QPushButton:disabled {{
    background: transparent;
    color: {p.dim};
    border-color: {p.border};
}}
/* Keyboard users get the same affordance as mouse users. */
QPushButton:focus, QComboBox:focus, QListWidget:focus {{
    border: 1px solid {p.accent};
}}
QPushButton#Primary {{
    background: {p.accent};
    border: 1px solid {p.accent};
    color: {p.on_accent};
}}
QPushButton#Primary:hover {{ background: {p.accent_dim}; }}
QPushButton#Danger {{ color: {p.bad}; }}

/* ---------- checkboxes ---------- */
QCheckBox {{ spacing: 9px; padding: 3px 0; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border-radius: 5px;
    border: 1px solid {p.border};
    background: {p.sunk};
}}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
    image: none;
}}

/* ---------- sliders ---------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {p.border};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {p.accent};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {p.handle};
    border: 1px solid {p.accent};
    width: 14px; height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}

/* ---------- lists ---------- */
QListWidget {{
    background: {p.sunk};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 4px;
    outline: 0;
}}
QListWidget::item {{
    padding: 5px 7px;
    border-radius: 5px;
    color: {p.text};
}}
QListWidget::item:hover {{ background: {p.hover}; }}
QListWidget::item:selected {{ background: {p.accent}; color: {p.on_accent}; }}

/* Check boxes inside a list are drawn by the style, not by QCheckBox, so
   they need their own rule -- without it they were white on white in the
   light theme and effectively invisible. */
QListWidget::indicator {{
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid {p.dim};
    background: {p.sunk};
}}
QListWidget::indicator:hover {{ border-color: {p.accent}; }}
QListWidget::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
}}

/* ---------- scrollbars ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p.border}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.dim}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: {p.card};
    color: {p.text};
    border: 1px solid {p.border};
    padding: 5px 7px;
    border-radius: 6px;
}}
"""


def stylesheet(name: str = "dark") -> str:
    return build(THEMES.get(name, DARK))


# kept so existing imports keep working
QSS = stylesheet("dark")
