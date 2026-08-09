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
)

LIGHT = Palette(
    name="light",
    bg="#f4f6f9",
    sunk="#ffffff",
    card="#ffffff",
    hover="#e9edf3",
    border="#d3dae3",
    text="#1a1f26",
    dim="#5f6b7a",
    accent="#2f6fe4",
    accent_dim="#2559b8",
    on_accent="#ffffff",
    good="#1e9e5a",
    warn="#b57d00",
    bad="#d13438",
    handle="#2f6fe4",
)

THEMES = {"dark": DARK, "light": LIGHT}


def build(p: Palette) -> str:
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
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QFontComboBox:focus {{
    border: 1px solid {p.accent};
}}
QComboBox::drop-down, QFontComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {p.card};
    color: {p.text};
    border: 1px solid {p.border};
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
    outline: 0;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 16px;
    border: none;
    background: transparent;
}}

/* ---------- buttons ---------- */
QPushButton {{
    background: {p.hover};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 7px 14px;
    font-weight: 600;
    color: {p.text};
}}
QPushButton:hover {{ border-color: {p.accent}; }}
QPushButton:pressed {{ background: {p.border}; }}
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
