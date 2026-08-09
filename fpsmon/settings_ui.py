"""
Control panel: everything the user can customise, in one window.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import config, metrics as M, theme

POSITIONS = [
    ("Top left", "top_left"),
    ("Top center", "top_center"),
    ("Top right", "top_right"),
    ("Bottom left", "bottom_left"),
    ("Bottom right", "bottom_right"),
    ("Custom (drag)", "custom"),
]
LAYOUTS = [("Rows", "rows"), ("Columns", "columns"), ("Single line", "compact")]

from .paths import resource

ASSETS = resource("assets")


def _logo_pixmap(size: int):
    """Scaled app logo, or None when the logo has not been added yet."""
    for name in ("logo.png", "logo_64.png", "icon.ico"):
        path = os.path.join(ASSETS, name)
        if os.path.exists(path):
            pm = QPixmap(path)
            if not pm.isNull():
                return pm.scaled(
                    size, size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
    return None


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, color: str):
        super().__init__()
        self.setFixedSize(64, 24)
        self._color = color
        self._refresh()
        self.clicked.connect(self._pick)

    def _refresh(self) -> None:
        self.setStyleSheet(
            f"background-color:{self._color}; border:1px solid #555; border-radius:3px;"
        )
        self.setToolTip(self._color)

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = color
        self._refresh()

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "Pick a colour")
        if c.isValid():
            self._color = c.name().upper()
            self._refresh()
            self.changed.emit(self._color)


class SettingsWindow(QWidget):
    """Emits `changed` with the live profile whenever anything is edited."""

    changed = Signal(dict)
    profile_switched = Signal(str)
    benchmark_toggled = Signal()
    limit_requested = Signal(str, int)   # target ("game"|"global"), fps
    limit_refresh_requested = Signal()
    driver_panel_requested = Signal()

    def __init__(self, profile: dict[str, Any], status_provider: Callable[[], str]):
        super().__init__()
        self.profile = profile
        self.status_provider = status_provider
        self._loading = False
        self.setWindowTitle("FPS Monitor")
        self.resize(940, 700)
        self.setStyleSheet(theme.QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        # ---- sidebar -----------------------------------------------------
        side = QWidget()
        side.setObjectName("Side")
        side.setFixedWidth(190)
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 0, 0, 0)
        side_lay.setSpacing(0)

        brand = QWidget()
        brand.setObjectName("Brand")
        brand_lay = QHBoxLayout(brand)
        brand_lay.setContentsMargins(16, 16, 12, 10)
        brand_lay.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("BrandLogo")
        pm = _logo_pixmap(28)
        if pm is not None:
            logo.setPixmap(pm)
            brand_lay.addWidget(logo)
        name = QLabel("FPS Monitor")
        name.setObjectName("BrandName")
        brand_lay.addWidget(name)
        brand_lay.addStretch(1)
        side_lay.addWidget(brand)

        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        side_lay.addWidget(self.nav, 1)
        body.addWidget(side)

        # ---- content -----------------------------------------------------
        right = QVBoxLayout()
        right.setContentsMargins(22, 18, 22, 12)
        right.setSpacing(4)
        body.addLayout(right, 1)

        self.page_title = QLabel("")
        self.page_title.setObjectName("Title")
        self.page_subtitle = QLabel("")
        self.page_subtitle.setObjectName("Subtitle")
        self.page_subtitle.setWordWrap(True)
        right.addWidget(self.page_title)
        right.addWidget(self.page_subtitle)

        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)

        self._pages: list[tuple[str, str]] = []
        self._add_page("Metrics", "Choose what appears on screen, and in what order.",
                       self._build_metrics_tab())
        self._add_page("Appearance", "Fonts, colours, spacing and layout.",
                       self._build_appearance_tab())
        self._add_page("Graph", "The frame-time graph and how it animates.",
                       self._build_graph_tab())
        self._add_page("Position", "Where the overlay sits, and what it follows.",
                       self._build_position_tab())
        self._add_page("Behaviour", "When the overlay shows, hotkeys, benchmarks.",
                       self._build_behaviour_tab())
        self._add_page("FPS limiter", "Cap the frame rate through RivaTuner.",
                       self._build_limiter_tab())
        self._add_page("Profiles", "Save and switch complete configurations.",
                       self._build_profiles_tab())

        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.setCurrentRow(0)

        self.status = QLabel("")
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.load_from_profile(profile)

    # ------------------------------------------------------------- layout
    def _add_page(self, name: str, subtitle: str, widget: QWidget) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.stack.addWidget(scroll)
        self.nav.addItem(QListWidgetItem(name))
        self._pages.append((name, subtitle))

    def _on_nav(self, row: int) -> None:
        if 0 <= row < len(self._pages):
            self.stack.setCurrentIndex(row)
            name, subtitle = self._pages[row]
            self.page_title.setText(name)
            self.page_subtitle.setText(subtitle)

    # ------------------------------------------------------------------ tabs
    def _build_metrics_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(
            "Tick what you want on screen. Drag items in the right list to reorder."
        ))

        cols = QHBoxLayout()
        lay.addLayout(cols, 1)

        # available metrics, grouped
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Available</b>"))
        self.metric_list = QListWidget()
        self.metric_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for group in M.GROUPS:
            head = QListWidgetItem(f"── {group} ──")
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            f = head.font(); f.setBold(True); head.setFont(f)
            self.metric_list.addItem(head)
            for metric in M.METRICS:
                if metric.group != group:
                    continue
                item = QListWidgetItem(f"{metric.long_label}"
                                       + (f"  ({metric.unit})" if metric.unit else ""))
                item.setData(Qt.ItemDataRole.UserRole, metric.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.metric_list.addItem(item)
        self.metric_list.itemChanged.connect(self._on_metric_toggled)
        left.addWidget(self.metric_list)
        cols.addLayout(left, 3)

        # chosen order
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Shown, in order</b>"))
        self.order_list = QListWidget()
        self.order_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.order_list.model().rowsMoved.connect(lambda *_: self._push())
        right.addWidget(self.order_list)
        btns = QHBoxLayout()
        up = QPushButton("Move up"); down = QPushButton("Move down")
        rem = QPushButton("Remove")
        up.clicked.connect(lambda: self._move_selected(-1))
        down.clicked.connect(lambda: self._move_selected(1))
        rem.clicked.connect(self._remove_selected)
        for b in (up, down, rem):
            btns.addWidget(b)
        right.addLayout(btns)
        cols.addLayout(right, 2)
        return w

    def _build_appearance_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        gb_font = QGroupBox("Text")
        f = QFormLayout(gb_font)
        self.font_family = QFontComboBox()
        self.font_family.currentFontChanged.connect(lambda *_: self._push())
        f.addRow("Font", self.font_family)
        self.font_size = QSpinBox(); self.font_size.setRange(7, 96)
        self.font_size.valueChanged.connect(lambda *_: self._push())
        f.addRow("Size", self.font_size)
        self.font_bold = QCheckBox("Bold")
        self.font_bold.toggled.connect(lambda *_: self._push())
        f.addRow("", self.font_bold)
        self.shadow = QCheckBox("Drop shadow (improves readability on bright scenes)")
        self.shadow.toggled.connect(lambda *_: self._push())
        f.addRow("", self.shadow)
        outer.addWidget(gb_font)

        gb_col = QGroupBox("Colours")
        c = QFormLayout(gb_col)
        self.text_color = ColorButton("#00FF66")
        self.label_color = ColorButton("#9FEFC0")
        self.warn_color = ColorButton("#FFC400")
        self.crit_color = ColorButton("#FF3B30")
        self.bg_color = ColorButton("#000000")
        for name, btn in (
            ("Values", self.text_color), ("Labels", self.label_color),
            ("Warning", self.warn_color), ("Critical", self.crit_color),
            ("Background", self.bg_color),
        ):
            btn.changed.connect(lambda *_: self._push())
            c.addRow(name, btn)
        self.color_thresholds = QCheckBox(
            "Colour values by temperature / load thresholds"
        )
        self.color_thresholds.toggled.connect(lambda *_: self._push())
        c.addRow("", self.color_thresholds)
        outer.addWidget(gb_col)

        gb_op = QGroupBox("Opacity and spacing")
        o = QFormLayout(gb_op)
        self.bg_opacity = self._slider(0, 100)
        o.addRow("Background opacity", self.bg_opacity)
        self.text_opacity = self._slider(20, 100)
        o.addRow("Text opacity", self.text_opacity)
        self.padding = QSpinBox(); self.padding.setRange(0, 60)
        self.padding.valueChanged.connect(lambda *_: self._push())
        o.addRow("Padding", self.padding)
        self.line_spacing = QSpinBox(); self.line_spacing.setRange(-4, 30)
        self.line_spacing.valueChanged.connect(lambda *_: self._push())
        o.addRow("Line spacing", self.line_spacing)
        self.corner_radius = QSpinBox(); self.corner_radius.setRange(0, 30)
        self.corner_radius.valueChanged.connect(lambda *_: self._push())
        o.addRow("Corner radius", self.corner_radius)
        outer.addWidget(gb_op)

        gb_lay = QGroupBox("Layout")
        l = QFormLayout(gb_lay)
        self.layout_box = QComboBox()
        for label, val in LAYOUTS:
            self.layout_box.addItem(label, val)
        self.layout_box.currentIndexChanged.connect(lambda *_: self._push())
        l.addRow("Arrangement", self.layout_box)
        self.columns = QSpinBox(); self.columns.setRange(1, 4)
        self.columns.valueChanged.connect(lambda *_: self._push())
        l.addRow("Columns", self.columns)
        self.show_labels = QCheckBox("Show labels")
        self.show_units = QCheckBox("Show units")
        self.show_group_headers = QCheckBox("Show group headers (FPS / CPU / GPU)")
        self.align_values = QCheckBox("Align numbers in a column")
        self.separate_units = QCheckBox(
            "Units in smaller text after the value (RivaTuner style)"
        )
        for cb in (self.show_labels, self.show_units,
                   self.show_group_headers, self.align_values,
                   self.separate_units):
            cb.toggled.connect(lambda *_: self._push())
            l.addRow("", cb)
        self.unit_size_pct = QSpinBox()
        self.unit_size_pct.setRange(30, 150)
        self.unit_size_pct.setSuffix(" % of value size")
        self.unit_size_pct.valueChanged.connect(lambda *_: self._push())
        l.addRow("Unit size", self.unit_size_pct)
        outer.addWidget(gb_lay)
        outer.addStretch(1)
        return w

    def _build_graph_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        intro = QLabel(
            "The graph plots <b>frame time</b>, one point per presented frame. "
            "A flat line means smooth output; tall isolated spikes are the "
            "micro-stutters that an averaged FPS counter hides. Spikes above "
            "1.5x the median are highlighted."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        gb = QGroupBox("Frame-time graph")
        f = QFormLayout(gb)
        self.graph_enabled = QCheckBox("Show the frame-time graph")
        self.graph_enabled.toggled.connect(lambda *_: self._push())
        f.addRow("", self.graph_enabled)

        self.graph_seconds = QDoubleSpinBox()
        self.graph_seconds.setRange(1.0, 30.0)
        self.graph_seconds.setSingleStep(0.5)
        self.graph_seconds.setSuffix(" s")
        self.graph_seconds.valueChanged.connect(lambda *_: self._push())
        f.addRow("Time window", self.graph_seconds)

        self.graph_height = QSpinBox(); self.graph_height.setRange(16, 240)
        self.graph_height.valueChanged.connect(lambda *_: self._push())
        f.addRow("Height", self.graph_height)

        self.graph_width = QSpinBox(); self.graph_width.setRange(0, 1200)
        self.graph_width.setSpecialValueText("match text width")
        self.graph_width.valueChanged.connect(lambda *_: self._push())
        f.addRow("Width", self.graph_width)

        self.graph_style = QComboBox()
        self.graph_style.addItem("Line", "line")
        self.graph_style.addItem("Bars", "bars")
        self.graph_style.currentIndexChanged.connect(lambda *_: self._push())
        f.addRow("Style", self.graph_style)

        self.graph_max_ms = QDoubleSpinBox()
        self.graph_max_ms.setRange(0.0, 200.0)
        self.graph_max_ms.setSingleStep(5.0)
        self.graph_max_ms.setSpecialValueText("auto")
        self.graph_max_ms.setSuffix(" ms")
        self.graph_max_ms.valueChanged.connect(lambda *_: self._push())
        f.addRow("Vertical scale", self.graph_max_ms)

        self.graph_color = ColorButton("#00FF66")
        self.graph_spike_color = ColorButton("#FF3B30")
        for name, btn in (("Line colour", self.graph_color),
                          ("Stutter spike colour", self.graph_spike_color)):
            btn.changed.connect(lambda *_: self._push())
            f.addRow(name, btn)

        self.graph_bg_opacity = self._slider(0, 100)
        f.addRow("Graph background", self.graph_bg_opacity)

        self.graph_spike_mult = QDoubleSpinBox()
        self.graph_spike_mult.setRange(1.1, 5.0)
        self.graph_spike_mult.setSingleStep(0.1)
        self.graph_spike_mult.setPrefix("over ")
        self.graph_spike_mult.setSuffix("x median")
        self.graph_spike_mult.valueChanged.connect(lambda *_: self._push())
        f.addRow("Stutter threshold", self.graph_spike_mult)

        self.graph_spike_floor = QDoubleSpinBox()
        self.graph_spike_floor.setRange(0.0, 30.0)
        self.graph_spike_floor.setSingleStep(0.5)
        self.graph_spike_floor.setSuffix(" ms")
        self.graph_spike_floor.valueChanged.connect(lambda *_: self._push())
        f.addRow("  and at least", self.graph_spike_floor)

        hint = QLabel(
            "A frame must be worse on BOTH counts to be marked as stutter. "
            "The absolute figure is what stops a locked framerate from "
            "flagging normal sub-millisecond jitter. Raise it if you still see "
            "spikes during smooth gameplay."
        )
        hint.setWordWrap(True); hint.setStyleSheet("color:#888;")
        f.addRow("", hint)

        self.graph_guides = QCheckBox("Draw 60 FPS (16.7ms) and 30 FPS (33.3ms) guides")
        self.graph_show_spikes = QCheckBox("Mark stutter spikes")
        for cb in (self.graph_guides, self.graph_show_spikes):
            cb.toggled.connect(lambda *_: self._push())
            f.addRow("", cb)

        self.graph_title = QLineEdit()
        self.graph_title.setPlaceholderText("e.g. Frametime (blank for none)")
        self.graph_title.editingFinished.connect(self._push)
        f.addRow("Caption", self.graph_title)

        self.graph_scale_pos = QComboBox()
        for label, val in (("Left, inside the plot", "left"),
                           ("Right, in its own gutter", "right"),
                           ("Hidden", "none")):
            self.graph_scale_pos.addItem(label, val)
        self.graph_scale_pos.currentIndexChanged.connect(lambda *_: self._push())
        f.addRow("Scale label", self.graph_scale_pos)
        outer.addWidget(gb)

        gb3 = QGroupBox("Animation")
        f3 = QFormLayout(gb3)
        self.graph_fps = QComboBox()
        for label, val in (("15 FPS (lowest cost)", 15), ("30 FPS", 30),
                           ("60 FPS (smooth)", 60), ("120 FPS (smoothest)", 120)):
            self.graph_fps.addItem(label, val)
        self.graph_fps.currentIndexChanged.connect(lambda *_: self._push())
        f3.addRow("Redraw rate", self.graph_fps)

        self.graph_line_width = QSpinBox(); self.graph_line_width.setRange(1, 6)
        self.graph_line_width.valueChanged.connect(lambda *_: self._push())
        f3.addRow("Line thickness", self.graph_line_width)

        self.graph_fill = QCheckBox("Gradient fill under the curve")
        self.graph_trail = QCheckBox("Fade the tail of the trail out")
        for cb in (self.graph_fill, self.graph_trail):
            cb.toggled.connect(lambda *_: self._push())
            f3.addRow("", cb)

        note = QLabel(
            "The graph animates on its own clock, so it stays smooth no matter "
            "how slowly the sensors are polled. Only the graph strip is "
            "repainted, so 60 FPS costs very little."
        )
        note.setWordWrap(True); note.setStyleSheet("color:#888;")
        f3.addRow("", note)
        outer.addWidget(gb3)

        gb2 = QGroupBox("MangoHud-style group colours")
        f2 = QFormLayout(gb2)
        self.use_group_colors = QCheckBox(
            "Colour each label by its group instead of one label colour"
        )
        self.use_group_colors.toggled.connect(lambda *_: self._push())
        f2.addRow("", self.use_group_colors)
        self.group_color_btns: dict[str, ColorButton] = {}
        for group in M.GROUPS:
            btn = ColorButton("#FFFFFF")
            btn.changed.connect(lambda *_: self._push())
            self.group_color_btns[group] = btn
            f2.addRow(group, btn)
        outer.addWidget(gb2)
        outer.addStretch(1)
        return w

    def _build_position_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.position = QComboBox()
        for label, val in POSITIONS:
            self.position.addItem(label, val)
        self.position.currentIndexChanged.connect(lambda *_: self._push())
        f.addRow("Anchor", self.position)

        self.monitor = QSpinBox(); self.monitor.setRange(0, 7)
        self.monitor.valueChanged.connect(lambda *_: self._push())
        f.addRow("Monitor index", self.monitor)

        self.margin_x = QSpinBox(); self.margin_x.setRange(0, 2000)
        self.margin_y = QSpinBox(); self.margin_y.setRange(0, 2000)
        for sb in (self.margin_x, self.margin_y):
            sb.valueChanged.connect(lambda *_: self._push())
        f.addRow("Margin X", self.margin_x)
        f.addRow("Margin Y", self.margin_y)

        self.anchor_to_window = QCheckBox(
            "Follow the game's window when it is not fullscreen"
        )
        self.anchor_to_window.toggled.connect(lambda *_: self._push())
        f.addRow("", self.anchor_to_window)

        anote = QLabel(
            "With this on, the anchor above is a corner of the game's window "
            "rather than the screen, so a windowed game keeps the overlay on "
            "top of it as you move or resize. Fullscreen games fall back to "
            "the screen corner."
        )
        anote.setWordWrap(True)
        anote.setObjectName("SectionHint")
        f.addRow("", anote)

        self.locked = QCheckBox("Locked (click-through). Untick to drag the overlay.")
        self.locked.toggled.connect(lambda *_: self._push())
        f.addRow("", self.locked)

        note = QLabel(
            "While unlocked the overlay accepts the mouse, so you can drag it "
            "anywhere. Tick Locked again to make it click-through for gaming."
        )
        note.setWordWrap(True); note.setStyleSheet("color:#888;")
        f.addRow("", note)
        return w

    def _build_behaviour_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        gb0 = QGroupBox("When to show the overlay")
        f0 = QFormLayout(gb0)
        self.visibility_mode = QComboBox()
        self.visibility_mode.addItem(
            "While a game is running (even if not focused)", "game_running"
        )
        self.visibility_mode.addItem("Only while the game has focus", "game")
        self.visibility_mode.addItem("Whenever anything is rendering", "rendering")
        self.visibility_mode.addItem("Always", "always")
        self.visibility_mode.currentIndexChanged.connect(lambda *_: self._push())
        f0.addRow("Show", self.visibility_mode)

        hint0 = QLabel(
            "A focused window counts as a game when it is presenting frames "
            "and is not a browser, the desktop, or another known non-game. "
            "Browsers present frames constantly, so presenting alone is not "
            "enough to tell them apart."
        )
        hint0.setWordWrap(True)
        hint0.setObjectName("SectionHint")
        f0.addRow("", hint0)

        self.extra_games = QLineEdit()
        self.extra_games.setPlaceholderText("mygame.exe, another.exe")
        self.extra_games.editingFinished.connect(self._push)
        f0.addRow("Always treat as games", self.extra_games)

        self.extra_non_games = QLineEdit()
        self.extra_non_games.setPlaceholderText("someapp.exe")
        self.extra_non_games.editingFinished.connect(self._push)
        f0.addRow("Never treat as games", self.extra_non_games)
        outer.addWidget(gb0)

        gb = QGroupBox("Updates")
        f = QFormLayout(gb)
        self.update_interval = QDoubleSpinBox()
        self.update_interval.setRange(0.1, 5.0)
        self.update_interval.setSingleStep(0.1)
        self.update_interval.setSuffix(" s")
        self.update_interval.valueChanged.connect(lambda *_: self._push())
        f.addRow("Refresh every", self.update_interval)
        self.only_in_game = QCheckBox(
            "Legacy: hide unless something is rendering"
        )
        self.only_in_game.toggled.connect(lambda *_: self._push())
        f.addRow("", self.only_in_game)
        outer.addWidget(gb)

        gb2 = QGroupBox("Hotkeys (global)")
        f2 = QFormLayout(gb2)
        self.hk_toggle = QLineEdit()
        self.hk_bench = QLineEdit()
        self.hk_settings = QLineEdit()
        self.hk_profile = QLineEdit()
        for name, le in (
            ("Show / hide overlay", self.hk_toggle),
            ("Start / stop benchmark", self.hk_bench),
            ("Open settings", self.hk_settings),
            ("Next profile", self.hk_profile),
        ):
            le.setPlaceholderText("e.g. ctrl+alt+f")
            le.editingFinished.connect(self._push)
            f2.addRow(name, le)
        hint = QLabel("Format: modifiers joined with +, e.g. ctrl+shift+f9. "
                      "Changes apply immediately.")
        hint.setWordWrap(True); hint.setStyleSheet("color:#888;")
        f2.addRow("", hint)
        outer.addWidget(gb2)

        gb3 = QGroupBox("Benchmark")
        f3 = QVBoxLayout(gb3)
        self.bench_btn = QPushButton("Start benchmark recording")
        self.bench_btn.clicked.connect(lambda: self.benchmark_toggled.emit())
        f3.addWidget(self.bench_btn)
        self.bench_label = QLabel("CSV logs are written to the logs\\ folder.")
        self.bench_label.setWordWrap(True)
        self.bench_label.setStyleSheet("color:#888;")
        f3.addWidget(self.bench_label)
        outer.addWidget(gb3)
        outer.addStretch(1)
        return w

    def _build_limiter_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        intro = QLabel(
            "Capping frame rate requires code inside the game's own render "
            "loop, so this drives <b>RivaTuner Statistics Server</b> rather "
            "than injecting anything itself. RTSS must be installed and "
            "running; only the frame-rate line of its profile is changed and "
            "a one-time backup is kept."
        )
        intro.setWordWrap(True)
        intro.setObjectName("SectionHint")
        outer.addWidget(intro)

        gb = QGroupBox("Frame rate cap")
        f = QFormLayout(gb)
        self.limit_target = QComboBox()
        self.limit_target.addItem("The focused game", "game")
        self.limit_target.addItem("Everything (RTSS Global profile)", "global")
        f.addRow("Apply to", self.limit_target)

        self.limit_value = QSpinBox()
        self.limit_value.setRange(0, 1000)
        self.limit_value.setSpecialValueText("unlimited")
        self.limit_value.setSuffix(" FPS")
        f.addRow("Limit", self.limit_value)

        row = QHBoxLayout()
        self.limit_apply = QPushButton("Apply limit")
        self.limit_apply.setObjectName("Primary")
        self.limit_clear = QPushButton("Remove limit")
        self.limit_refresh = QPushButton("Refresh")
        for b in (self.limit_apply, self.limit_clear, self.limit_refresh):
            row.addWidget(b)
        row.addStretch(1)
        f.addRow("", row)
        self.limit_apply.clicked.connect(
            lambda: self.limit_requested.emit(
                self.limit_target.currentData(), self.limit_value.value()
            )
        )
        self.limit_clear.clicked.connect(
            lambda: self.limit_requested.emit(self.limit_target.currentData(), 0)
        )
        self.limit_refresh.clicked.connect(self.limit_refresh_requested.emit)
        outer.addWidget(gb)

        self.limit_status = QLabel("")
        self.limit_status.setWordWrap(True)
        self.limit_status.setObjectName("SectionHint")
        outer.addWidget(self.limit_status)

        gb2 = QGroupBox("No third-party software: use the GPU driver")
        f2 = QVBoxLayout(gb2)
        self.driver_hint = QLabel("")
        self.driver_hint.setWordWrap(True)
        self.driver_hint.setObjectName("SectionHint")
        f2.addWidget(self.driver_hint)
        drow = QHBoxLayout()
        self.driver_open = QPushButton("Open driver settings")
        drow.addWidget(self.driver_open)
        drow.addStretch(1)
        f2.addLayout(drow)
        self.driver_open.clicked.connect(self.driver_panel_requested.emit)
        outer.addWidget(gb2)
        outer.addStretch(1)
        return w

    def _build_profiles_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Profiles store the complete overlay configuration."))
        self.profile_list = QListWidget()
        self.profile_list.itemDoubleClicked.connect(
            lambda it: self.profile_switched.emit(it.text())
        )
        lay.addWidget(self.profile_list, 1)
        row = QHBoxLayout()
        b_load = QPushButton("Load")
        b_save = QPushButton("Save current")
        b_new = QPushButton("Save as...")
        b_del = QPushButton("Delete")
        b_load.clicked.connect(self._load_selected_profile)
        b_save.clicked.connect(self._save_current_profile)
        b_new.clicked.connect(self._save_as_profile)
        b_del.clicked.connect(self._delete_profile)
        for b in (b_load, b_save, b_new, b_del):
            row.addWidget(b)
        lay.addLayout(row)
        self.refresh_profiles()
        return w

    # ------------------------------------------------------------- helpers
    def _slider(self, lo: int, hi: int) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.valueChanged.connect(lambda *_: self._push())
        return s

    def _move_selected(self, delta: int) -> None:
        row = self.order_list.currentRow()
        new = row + delta
        if row < 0 or new < 0 or new >= self.order_list.count():
            return
        item = self.order_list.takeItem(row)
        self.order_list.insertItem(new, item)
        self.order_list.setCurrentRow(new)
        self._push()

    def _remove_selected(self) -> None:
        row = self.order_list.currentRow()
        if row < 0:
            return
        item = self.order_list.takeItem(row)
        mid = item.data(Qt.ItemDataRole.UserRole)
        self._loading = True
        for i in range(self.metric_list.count()):
            it = self.metric_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == mid:
                it.setCheckState(Qt.CheckState.Unchecked)
        self._loading = False
        self._push()

    def _on_metric_toggled(self, item: QListWidgetItem) -> None:
        if self._loading:
            return
        mid = item.data(Qt.ItemDataRole.UserRole)
        if not mid:
            return
        present = [
            self.order_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.order_list.count())
        ]
        if item.checkState() == Qt.CheckState.Checked and mid not in present:
            self._add_order_item(mid)
        elif item.checkState() == Qt.CheckState.Unchecked and mid in present:
            self.order_list.takeItem(present.index(mid))
        self._push()

    def _add_order_item(self, mid: str) -> None:
        metric = M.BY_ID.get(mid)
        if metric is None:
            return
        it = QListWidgetItem(f"{metric.label}   —   {metric.long_label}")
        it.setData(Qt.ItemDataRole.UserRole, mid)
        self.order_list.addItem(it)

    # ------------------------------------------------------- profile <-> ui
    def load_from_profile(self, profile: dict[str, Any]) -> None:
        self._loading = True
        self.profile = profile
        p = profile

        chosen = [m for m in p["metrics"] if m in M.BY_ID]
        self.order_list.clear()
        for mid in chosen:
            self._add_order_item(mid)
        for i in range(self.metric_list.count()):
            it = self.metric_list.item(i)
            mid = it.data(Qt.ItemDataRole.UserRole)
            if mid:
                it.setCheckState(
                    Qt.CheckState.Checked if mid in chosen else Qt.CheckState.Unchecked
                )

        self.font_family.setCurrentFont(QFont(p["font_family"]))
        self.font_size.setValue(int(p["font_size"]))
        self.font_bold.setChecked(bool(p["font_bold"]))
        self.shadow.setChecked(bool(p["shadow"]))
        self.text_color.set_color(p["text_color"])
        self.label_color.set_color(p["label_color"])
        self.warn_color.set_color(p["warn_color"])
        self.crit_color.set_color(p["crit_color"])
        self.bg_color.set_color(p["bg_color"])
        self.color_thresholds.setChecked(bool(p["color_thresholds"]))
        self.bg_opacity.setValue(int(p["bg_opacity"]))
        self.text_opacity.setValue(int(p["text_opacity"]))
        self.padding.setValue(int(p["padding"]))
        self.line_spacing.setValue(int(p["line_spacing"]))
        self.corner_radius.setValue(int(p["corner_radius"]))
        self._set_combo(self.layout_box, p["layout"])
        self.columns.setValue(int(p["columns"]))
        self.show_labels.setChecked(bool(p["show_labels"]))
        self.show_units.setChecked(bool(p["show_units"]))
        self.show_group_headers.setChecked(bool(p["show_group_headers"]))
        self.align_values.setChecked(bool(p["align_values"]))
        self.graph_enabled.setChecked(bool(p.get("graph_enabled", False)))
        self.graph_seconds.setValue(float(p.get("graph_seconds", 4.0)))
        self.graph_height.setValue(int(p.get("graph_height", 46)))
        self.graph_width.setValue(int(p.get("graph_width", 0)))
        self._set_combo(self.graph_style, p.get("graph_style", "line"))
        self.graph_max_ms.setValue(float(p.get("graph_max_ms", 0.0)))
        self.graph_color.set_color(p.get("graph_color", "#00FF66"))
        self.graph_spike_color.set_color(p.get("graph_spike_color", "#FF3B30"))
        self.graph_bg_opacity.setValue(int(p.get("graph_bg_opacity", 25)))
        self.graph_guides.setChecked(bool(p.get("graph_guides", True)))
        self.graph_show_spikes.setChecked(bool(p.get("graph_show_spikes", True)))
        self.graph_title.setText(str(p.get("graph_title", "")))
        self._set_combo(self.graph_scale_pos, p.get("graph_scale_pos", "left"))
        self.separate_units.setChecked(bool(p.get("separate_units", False)))
        self.unit_size_pct.setValue(int(p.get("unit_size_pct", 70)))
        self._set_combo(self.graph_fps, int(p.get("graph_fps", 60)))
        self.graph_line_width.setValue(int(p.get("graph_line_width", 2)))
        self.graph_fill.setChecked(bool(p.get("graph_fill", True)))
        self.graph_trail.setChecked(bool(p.get("graph_trail", True)))
        self.graph_spike_mult.setValue(float(p.get("graph_spike_mult", 1.8)))
        self.graph_spike_floor.setValue(float(p.get("graph_spike_floor_ms", 5.0)))
        self.use_group_colors.setChecked(bool(p.get("use_group_colors", False)))
        gcolors = p.get("group_colors") or {}
        for group, btn in self.group_color_btns.items():
            btn.set_color(gcolors.get(group, "#FFFFFF"))
        self._set_combo(self.position, p["position"])
        self.monitor.setValue(int(p["monitor"]))
        self.margin_x.setValue(int(p["margin_x"]))
        self.margin_y.setValue(int(p["margin_y"]))
        self.locked.setChecked(bool(p["locked"]))
        self.update_interval.setValue(float(p["update_interval"]))
        self.only_in_game.setChecked(bool(p["only_in_game"]))
        self._set_combo(
            self.visibility_mode, p.get("visibility_mode", "game_running")
        )
        self.anchor_to_window.setChecked(bool(p.get("anchor_to_window", True)))
        self.extra_games.setText(", ".join(p.get("extra_games", [])))
        self.extra_non_games.setText(", ".join(p.get("extra_non_games", [])))
        self.hk_toggle.setText(p["hotkey_toggle"])
        self.hk_bench.setText(p["hotkey_benchmark"])
        self.hk_settings.setText(p["hotkey_settings"])
        self.hk_profile.setText(p["hotkey_cycle_profile"])
        self._loading = False

    @staticmethod
    def _set_combo(box: QComboBox, value: str) -> None:
        idx = box.findData(value)
        box.setCurrentIndex(idx if idx >= 0 else 0)

    def _push(self) -> None:
        if self._loading:
            return
        p = self.profile
        p["metrics"] = [
            self.order_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.order_list.count())
        ]
        p["font_family"] = self.font_family.currentFont().family()
        p["font_size"] = self.font_size.value()
        p["font_bold"] = self.font_bold.isChecked()
        p["shadow"] = self.shadow.isChecked()
        p["text_color"] = self.text_color.color()
        p["label_color"] = self.label_color.color()
        p["warn_color"] = self.warn_color.color()
        p["crit_color"] = self.crit_color.color()
        p["bg_color"] = self.bg_color.color()
        p["color_thresholds"] = self.color_thresholds.isChecked()
        p["bg_opacity"] = self.bg_opacity.value()
        p["text_opacity"] = self.text_opacity.value()
        p["padding"] = self.padding.value()
        p["line_spacing"] = self.line_spacing.value()
        p["corner_radius"] = self.corner_radius.value()
        p["layout"] = self.layout_box.currentData()
        p["columns"] = self.columns.value()
        p["show_labels"] = self.show_labels.isChecked()
        p["show_units"] = self.show_units.isChecked()
        p["show_group_headers"] = self.show_group_headers.isChecked()
        p["align_values"] = self.align_values.isChecked()
        p["graph_enabled"] = self.graph_enabled.isChecked()
        p["graph_seconds"] = self.graph_seconds.value()
        p["graph_height"] = self.graph_height.value()
        p["graph_width"] = self.graph_width.value()
        p["graph_style"] = self.graph_style.currentData()
        p["graph_max_ms"] = self.graph_max_ms.value()
        p["graph_color"] = self.graph_color.color()
        p["graph_spike_color"] = self.graph_spike_color.color()
        p["graph_bg_opacity"] = self.graph_bg_opacity.value()
        p["graph_guides"] = self.graph_guides.isChecked()
        p["graph_show_spikes"] = self.graph_show_spikes.isChecked()
        p["graph_title"] = self.graph_title.text().strip()
        p["graph_scale_pos"] = self.graph_scale_pos.currentData()
        p["separate_units"] = self.separate_units.isChecked()
        p["unit_size_pct"] = self.unit_size_pct.value()
        p["graph_fps"] = self.graph_fps.currentData()
        p["graph_line_width"] = self.graph_line_width.value()
        p["graph_fill"] = self.graph_fill.isChecked()
        p["graph_trail"] = self.graph_trail.isChecked()
        p["graph_spike_mult"] = self.graph_spike_mult.value()
        p["graph_spike_floor_ms"] = self.graph_spike_floor.value()
        p["use_group_colors"] = self.use_group_colors.isChecked()
        p["group_colors"] = {
            g: b.color() for g, b in self.group_color_btns.items()
        }
        p["position"] = self.position.currentData()
        p["monitor"] = self.monitor.value()
        p["margin_x"] = self.margin_x.value()
        p["margin_y"] = self.margin_y.value()
        p["locked"] = self.locked.isChecked()
        p["update_interval"] = self.update_interval.value()
        p["only_in_game"] = self.only_in_game.isChecked()
        p["visibility_mode"] = self.visibility_mode.currentData()
        p["anchor_to_window"] = self.anchor_to_window.isChecked()

        def _split(text: str) -> list[str]:
            return [s.strip() for s in text.replace(";", ",").split(",") if s.strip()]

        p["extra_games"] = _split(self.extra_games.text())
        p["extra_non_games"] = _split(self.extra_non_games.text())
        p["hotkey_toggle"] = self.hk_toggle.text().strip().lower()
        p["hotkey_benchmark"] = self.hk_bench.text().strip().lower()
        p["hotkey_settings"] = self.hk_settings.text().strip().lower()
        p["hotkey_cycle_profile"] = self.hk_profile.text().strip().lower()
        self.changed.emit(p)

    # ------------------------------------------------------------- profiles
    def refresh_profiles(self) -> None:
        self.profile_list.clear()
        for name in config.list_profiles():
            self.profile_list.addItem(name)

    def _load_selected_profile(self) -> None:
        it = self.profile_list.currentItem()
        if it:
            self.profile_switched.emit(it.text())

    def _save_current_profile(self) -> None:
        path = config.save_profile(self.profile)
        self.refresh_profiles()
        self.set_status(f"Saved {path}")

    def _save_as_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Save profile as", "Profile name:")
        if ok and name.strip():
            self.profile["name"] = name.strip()
            config.save_profile(self.profile)
            self.refresh_profiles()
            self.set_status(f"Saved profile '{name.strip()}'")

    def _delete_profile(self) -> None:
        import os

        it = self.profile_list.currentItem()
        if not it:
            return
        name = it.text()
        if QMessageBox.question(self, "Delete profile", f"Delete '{name}'?") != \
                QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(config.profile_path(name))
        except Exception as exc:
            self.set_status(f"Could not delete: {exc}")
        self.refresh_profiles()

    # --------------------------------------------------------------- status
    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_limiter_status(self, text: str, limit: int | None = None) -> None:
        self.limit_status.setText(text)
        if limit is not None:
            self._loading = True
            self.limit_value.setValue(int(limit))
            self._loading = False

    def set_driver_hint(self, text: str) -> None:
        self.driver_hint.setText(text)

    def set_benchmark_active(self, active: bool, info: str = "") -> None:
        self.bench_btn.setText(
            "Stop benchmark recording" if active else "Start benchmark recording"
        )
        if info:
            self.bench_label.setText(info)
