"""
Dark theme for the control panel.

Kept as one stylesheet string so colours can be changed in a single place.
"""

from __future__ import annotations

# palette
BG = "#14171c"          # window
BG_SUNK = "#0f1216"     # sidebar / inputs
CARD = "#1b1f26"        # group boxes
CARD_HOVER = "#222833"
BORDER = "#2a3038"
TEXT = "#e6e9ef"
TEXT_DIM = "#8b93a1"
ACCENT = "#4c8dff"
ACCENT_DIM = "#3a6fd0"
GOOD = "#3ddc84"
WARN = "#ffc400"
BAD = "#ff4d4f"

QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}

/* ---------- sidebar ---------- */
QWidget#Side {{
    background: {BG_SUNK};
    border-right: 1px solid {BORDER};
}}
QWidget#Brand {{
    background: transparent;
    border-bottom: 1px solid {BORDER};
}}
QLabel#BrandName {{
    font-size: 15px;
    font-weight: 700;
    color: {TEXT};
}}
QListWidget#Nav {{
    background: {BG_SUNK};
    border: none;
    outline: 0;
    padding: 10px 8px;
}}
QListWidget#Nav::item {{
    padding: 10px 14px;
    margin: 2px 4px;
    border-radius: 8px;
    color: {TEXT_DIM};
}}
QListWidget#Nav::item:hover {{
    background: {CARD_HOVER};
    color: {TEXT};
}}
QListWidget#Nav::item:selected {{
    background: {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}

/* labels must not paint their own panel colour inside cards */
QLabel, QCheckBox {{ background: transparent; }}

/* ---------- headings ---------- */
QLabel#Title {{
    font-size: 20px;
    font-weight: 700;
    padding: 2px 0 0 0;
}}
QLabel#Subtitle {{
    color: {TEXT_DIM};
    font-size: 12px;
    padding-bottom: 6px;
}}
QLabel#SectionHint {{
    color: {TEXT_DIM};
    font-size: 12px;
}}
QLabel#Status {{
    color: {TEXT_DIM};
    font-size: 12px;
    background: {BG_SUNK};
    border-top: 1px solid {BORDER};
    padding: 8px 14px;
}}

/* ---------- cards ---------- */
QGroupBox {{
    background: {CARD};
    border: 1px solid {BORDER};
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
    color: {TEXT_DIM};
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QFontComboBox {{
    background: {BG_SUNK};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 6px 9px;
    min-height: 20px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QFontComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down, QFontComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
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
    background: {CARD_HOVER};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover {{ background: #29313d; border-color: #38414f; }}
QPushButton:pressed {{ background: #1d232c; }}
QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #ffffff;
}}
QPushButton#Primary:hover {{ background: {ACCENT_DIM}; }}
QPushButton#Danger {{ color: {BAD}; }}

/* ---------- checkboxes ---------- */
QCheckBox {{ spacing: 9px; padding: 3px 0; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border-radius: 5px;
    border: 1px solid {BORDER};
    background: {BG_SUNK};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: none;
}}

/* ---------- sliders ---------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {BORDER};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #ffffff;
    width: 14px; height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}

/* ---------- lists ---------- */
QListWidget {{
    background: {BG_SUNK};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    outline: 0;
}}
QListWidget::item {{
    padding: 5px 7px;
    border-radius: 5px;
}}
QListWidget::item:hover {{ background: {CARD_HOVER}; }}
QListWidget::item:selected {{ background: {ACCENT}; color: #ffffff; }}

/* ---------- scrollbars ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #313a46; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #3d4855; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5px 7px;
    border-radius: 6px;
}}
"""
