"""
The on-screen overlay: a frameless, always-on-top, optionally click-through
window that paints the selected metrics and an optional frame-time graph.

Rendering is done manually in paintEvent so text can have a drop shadow and a
rounded translucent backdrop without any window-manager decoration.

Flicker notes
-------------
Layered windows repaint whenever they are resized, moved or re-ordered, so all
three are avoided unless something actually changed:

* z-order is only re-asserted when another window has genuinely covered us;
* the window is only resized when its computed size changes, and value column
  widths are sticky so a number growing a digit does not resize the window;
* the window is only moved when its computed position changes.
"""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from . import metrics as M

# --------------------------------------------------------------------------
# Win32 plumbing used to keep the overlay above game windows.
# --------------------------------------------------------------------------
_IS_WIN = sys.platform == "win32"
if _IS_WIN:
    _user32 = ctypes.windll.user32
    _HWND_TOPMOST = -1
    _SWP_NOSIZE = 0x0001
    _SWP_NOMOVE = 0x0002
    _SWP_NOACTIVATE = 0x0010
    _SWP_NOOWNERZORDER = 0x0200
    _SWP_NOSENDCHANGING = 0x0400
    _GWL_EXSTYLE = -20
    _WS_EX_NOACTIVATE = 0x08000000
    _WS_EX_TOOLWINDOW = 0x00000080
    _WS_EX_TOPMOST = 0x00000008
    _EVENT_SYSTEM_FOREGROUND = 0x0003
    _WINEVENT_OUTOFCONTEXT = 0x0000
    try:
        _get_exstyle = _user32.GetWindowLongPtrW
        _set_exstyle = _user32.SetWindowLongPtrW
        _get_exstyle.restype = ctypes.c_longlong
        _set_exstyle.restype = ctypes.c_longlong
        _get_exstyle.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _set_exstyle.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
    except AttributeError:  # pragma: no cover - 32-bit Python
        _get_exstyle = _user32.GetWindowLongW
        _set_exstyle = _user32.SetWindowLongW
    _GW_HWNDPREV = 3  # the window immediately ABOVE this one in z-order
    _user32.GetTopWindow.restype = ctypes.c_void_p
    _user32.GetTopWindow.argtypes = [ctypes.c_void_p]
    _user32.GetWindow.restype = ctypes.c_void_p
    _user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    _user32.GetForegroundWindow.restype = ctypes.c_void_p
    _WINEVENTPROC = ctypes.WINFUNCTYPE(
        None,
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
        ctypes.c_long, ctypes.c_long, ctypes.c_uint, ctypes.c_uint,
    )


@dataclass
class Line:
    kind: str          # "metric" | "header"
    group: str
    label: str
    value: str
    state: str
    mid: str = ""
    unit: str = ""     # kept separate so it can be drawn in a smaller font


class Overlay(QWidget):
    def __init__(self, profile: dict[str, Any], parent: QWidget | None = None,
                 embedded: bool = False):
        """`embedded=True` makes this a plain child widget for the settings
        preview: same painting and layout code, but no top-level window, no
        click-through, no z-order juggling. Reusing the real renderer means
        the preview cannot drift away from what actually draws on screen."""
        self.embedded = embedded
        if embedded:
            super().__init__(parent)
        else:
            super().__init__(
                None,
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowTransparentForInput,
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.values: dict[str, Any] = {}
        self.history: list[float] = []
        # Returns [(monotonic ts, frametime ms)]; pulled at render rate so the
        # trail scrolls continuously instead of stepping once per sensor tick.
        self._series_provider: Callable[[float], list[tuple[float, float]]] | None = None
        self._series: list[tuple[float, float]] = []
        # Presentation delay ("jitter buffer"): PresentMon delivers about one
        # burst per second, so rendering right up to `now` means the last
        # second is empty and then appears all at once. Drawing slightly in
        # the past means every pixel shown is backed by data that has already
        # arrived, so the trace scrolls seamlessly.
        self._lag = 0.0
        self._lag_samples: list[tuple[float, float]] = []  # (when, observed lag)
        self._last_fetch = 0.0
        self._gcache: dict | None = None
        self._drag_from: QPoint | None = None
        self._lines: list[Line] = []
        self._sticky_w: dict[str, int] = {}
        self._label_w = 0
        self._value_w = 0
        self._line_h = 0
        self._cols = 1
        self._per_col = 1
        self._col_w = 0
        self._compact_text = ""
        self._graph_rect: tuple[int, int, int, int] | None = None
        self._positions: list[tuple[int, int]] = []
        self._anchor: tuple[int, int, int, int] | None = None

        self.profile = profile
        self.apply_profile(profile)

        # Only a real overlay fights for z-order; the preview is a child
        # widget and must not touch window ordering or install hooks.
        self._winevent_hook = None
        self._winevent_proc = None
        if not embedded:
            self._raise_timer = QTimer(self)
            self._raise_timer.timeout.connect(self._keep_on_top)
            self._raise_timer.start(1000)
            self._install_foreground_hook()

        # Dedicated graph clock, decoupled from the sensor poll interval.
        self._graph_timer = QTimer(self)
        self._graph_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._graph_timer.timeout.connect(self._tick_graph)
        self._sync_graph_timer()

    # -- graph animation ---------------------------------------------------
    def set_series_provider(
        self, fn: Callable[[float], list[tuple[float, float]]] | None
    ) -> None:
        self._series_provider = fn

    def _sync_graph_timer(self) -> None:
        p = self.profile
        if p.get("graph_enabled", False) and self.isVisible():
            hz = max(5, min(240, int(p.get("graph_fps", 60))))
            interval = max(4, int(1000 / hz))
            if not self._graph_timer.isActive() or self._graph_timer.interval() != interval:
                self._graph_timer.start(interval)
        elif self._graph_timer.isActive():
            self._graph_timer.stop()

    #: How often new frame data is pulled. Frames arrive in bursts about once
    #: a second, so fetching at the redraw rate meant locking the capture
    #: backend and rebuilding a 700-item list sixty times a second to get the
    #: same answer. Scrolling in between is a pure translation.
    FETCH_INTERVAL = 0.1

    def _tick_graph(self) -> None:
        """Repaint only the graph strip, at the graph's own frame rate."""
        if self._graph_rect is None or not self.isVisible():
            return
        now = time.monotonic()
        if (self._series_provider is not None
                and now - self._last_fetch >= self.FETCH_INTERVAL):
            try:
                # The graph draws behind real time by self._lag, so the window
                # it shows is [now-lag-window, now-lag]. Requesting only
                # `window` seconds returns [now-window, now] and the leftmost
                # `lag` seconds of the graph have no data to draw -- which is
                # why the trace stopped short of the left edge.
                window = float(self.profile.get("graph_seconds", 4.0))
                self._series = self._series_provider(window + self._lag + 0.5)
            except Exception:
                self._series = []
            self._last_fetch = now
            self._update_lag()
            self._gcache = None          # data moved: the path must be rebuilt
        gx, gy, gw, gh = self._graph_rect
        self.update(QRect(gx - 1, gy - 1, gw + 2, gh + 2))

    # -- z-order -----------------------------------------------------------
    def _install_foreground_hook(self) -> None:
        """Restore topmost the moment another window is activated."""
        self._winevent_hook = None
        self._winevent_proc = None
        if not _IS_WIN:
            return

        def _on_foreground(*_args) -> None:
            try:
                self._keep_on_top()
            except Exception:
                pass

        try:
            self._winevent_proc = _WINEVENTPROC(_on_foreground)
            self._winevent_hook = _user32.SetWinEventHook(
                _EVENT_SYSTEM_FOREGROUND, _EVENT_SYSTEM_FOREGROUND, None,
                self._winevent_proc, 0, 0, _WINEVENT_OUTOFCONTEXT,
            )
        except Exception:
            self._winevent_hook = None

    def _apply_native_styles(self) -> None:
        if not _IS_WIN:
            return
        try:
            hwnd = int(self.winId())
            ex = _get_exstyle(ctypes.c_void_p(hwnd), _GWL_EXSTYLE)
            want = ex | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW
            if want != ex:
                _set_exstyle(ctypes.c_void_p(hwnd), _GWL_EXSTYLE, want)
            self._force_topmost(hwnd)
        except Exception:
            pass

    @staticmethod
    def _force_topmost(hwnd: int) -> None:
        _user32.SetWindowPos(
            ctypes.c_void_p(hwnd), ctypes.c_void_p(_HWND_TOPMOST),
            0, 0, 0, 0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
            | _SWP_NOOWNERZORDER | _SWP_NOSENDCHANGING,
        )

    def _keep_on_top(self) -> None:
        """Re-assert topmost ONLY when something is actually above us.

        Calling SetWindowPos unconditionally forces the layered window to
        recomposite, which is what produced a visible flicker on every click.
        """
        if not self.isVisible():
            return
        if not _IS_WIN:
            self.raise_()
            return
        try:
            hwnd = int(self.winId())
            if self._is_above_foreground(hwnd):
                return  # nothing is covering us: leave the window alone
            self._force_topmost(hwnd)
        except Exception:
            pass

    @staticmethod
    def _is_above_foreground(hwnd: int) -> bool:
        """True if our window sits above the active window in z-order.

        Windows keeps every WS_EX_TOPMOST window above every ordinary one, so
        the common case needs no traversal at all: if we are topmost and the
        focused window is not, we are already above it.

        Walking the z-order was the original approach and it was wrong. The
        chain above the focused window is as long as the user's desktop is
        busy -- easily past any sane step limit -- so the walk kept giving up,
        reporting "covered", and re-asserting the z-order on every check. That
        is exactly the constant repositioning this method exists to avoid.
        """
        fg = _user32.GetForegroundWindow()
        if not fg:
            return True
        if int(fg) == hwnd:
            return True

        try:
            ours = _get_exstyle(ctypes.c_void_p(hwnd), _GWL_EXSTYLE)
            theirs = _get_exstyle(ctypes.c_void_p(int(fg)), _GWL_EXSTYLE)
        except Exception:
            return False
        if not (ours & _WS_EX_TOPMOST):
            return False                     # we lost topmost: fix it
        if not (theirs & _WS_EX_TOPMOST):
            return True                      # topmost always wins

        # Both are topmost, so order matters. That set is small and sits at
        # the very top of the z-order, making this walk short.
        w = ctypes.c_void_p(int(fg))
        for _ in range(64):
            nxt = _user32.GetWindow(w, _GW_HWNDPREV)
            if not nxt:
                return False
            if int(nxt) == hwnd:
                return True
            w = ctypes.c_void_p(nxt)
        return False

    # -- configuration -----------------------------------------------------
    def apply_profile(self, profile: dict[str, Any]) -> None:
        self.profile = profile
        font = QFont(profile["font_family"], int(profile["font_size"]))
        font.setBold(bool(profile["font_bold"]))
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.font_main = font
        self.fm = QFontMetrics(font)
        self._sticky_w = {}  # column widths must not survive a font change
        self._set_click_through(
            bool(profile.get("click_through", True))
            and bool(profile.get("locked", True))
        )
        self.relayout()
        if hasattr(self, "_graph_timer"):
            self._sync_graph_timer()

    def _set_click_through(self, enabled: bool) -> None:
        if self.embedded:
            return                        # a child widget has no window flags
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowTransparentForInput
        else:
            flags &= ~Qt.WindowType.WindowTransparentForInput
        if flags == self.windowFlags():
            return
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
        self._apply_native_styles()

    # -- content -----------------------------------------------------------
    def set_values(
        self, values: dict[str, Any], history: list[float] | None = None
    ) -> None:
        self.values = values
        if history is not None:
            self.history = history
        self.relayout()

    def _build_lines(self) -> list[Line]:
        p = self.profile
        show_headers = bool(p.get("show_group_headers", False))
        show_units = bool(p.get("show_units", True))
        separate = bool(p.get("separate_units", False))
        lines: list[Line] = []
        last_group = None
        for mid in p["metrics"]:
            metric = M.BY_ID.get(mid)
            if metric is None:
                continue
            val = self.values.get(mid)
            unit = ""
            if val is None:
                text, state = "--", "ok"
            else:
                text = M.format_value(metric, val)
                state = (
                    M.state_for(metric, val)
                    if p.get("color_thresholds", True) else "ok"
                )
                if show_units and metric.unit:
                    if separate:
                        unit = metric.unit
                    else:
                        text = f"{text}{metric.unit}"
            if show_headers and metric.group != last_group:
                lines.append(Line("header", metric.group, metric.group, "", "ok"))
                last_group = metric.group
            lines.append(
                Line("metric", metric.group, metric.label, text, state, mid, unit)
            )
        return lines

    def _small_font(self) -> QFont:
        f = QFont(self.font_main)
        f.setPointSize(max(7, int(self.profile["font_size"]) - 5))
        f.setBold(False)
        return f

    def _unit_font(self) -> QFont:
        f = QFont(self.font_main)
        pct = max(30, min(150, int(self.profile.get("unit_size_pct", 70))))
        f.setPointSize(max(6, int(int(self.profile["font_size"]) * pct / 100)))
        f.setBold(False)
        return f

    # -- geometry ----------------------------------------------------------
    def relayout(self) -> None:
        p = self.profile
        lines = self._build_lines()
        self._lines = lines
        if not lines and not p.get("graph_enabled", False):
            self._apply_geometry(1, 1)
            self.update()
            return

        pad = int(p["padding"])
        gap = int(p["line_spacing"])
        self._line_h = self.fm.height() + gap
        show_labels = bool(p.get("show_labels", True))

        self.fm_unit = QFontMetrics(self._unit_font())
        label_w = 0
        value_w = 0
        unit_w = 0
        for ln in lines:
            if ln.kind != "metric":
                continue
            if show_labels:
                label_w = max(label_w, self.fm.horizontalAdvance(ln.label + "  "))
            # sticky per-metric width: never shrink while the profile is
            # unchanged, so "99" -> "100" does not resize the whole window
            w = self.fm.horizontalAdvance(ln.value)
            if w > self._sticky_w.get(ln.mid, 0):
                self._sticky_w[ln.mid] = w
            value_w = max(value_w, self._sticky_w.get(ln.mid, w))
            if ln.unit:
                unit_w = max(unit_w, self.fm_unit.horizontalAdvance(" " + ln.unit))
        self._label_w = label_w
        self._value_w = value_w
        self._unit_w = unit_w

        layout = p.get("layout", "rows")
        if layout == "compact":
            parts = [
                (f"{ln.label} {ln.value}" if show_labels else ln.value)
                for ln in lines if ln.kind == "metric"
            ]
            self._compact_text = "   ".join(parts)
            w = max(
                self.fm.horizontalAdvance(self._compact_text) + pad * 2,
                self._sticky_w.get("__compact__", 0),
            )
            self._sticky_w["__compact__"] = w
            text_h = self._line_h
        else:
            self._cols = max(1, int(p.get("columns", 1))) if layout == "columns" else 1
            self._per_col = self._assign_columns(lines, self._cols)
            self._col_w = label_w + value_w + unit_w + 18
            w = self._col_w * self._cols + pad * 2
            text_h = self._per_col * self._line_h

        h = text_h + pad * 2

        # ---- frame-time graph -------------------------------------------
        self._graph_rect = None
        if p.get("graph_enabled", False):
            gh = max(16, int(p.get("graph_height", 46)))
            gw = int(p.get("graph_width", 0)) or int(w - pad * 2)
            w = max(w, gw + pad * 2)
            # RTSS parks the scale to the RIGHT of the plot, not on top of it,
            # so reserve room rather than letting the label overlap the trace.
            self._scale_w = 0
            if p.get("graph_scale_pos", "left") == "right":
                fm_s = QFontMetrics(self._small_font())
                # size for a worst-case label so the plot width never twitches
                self._scale_w = fm_s.horizontalAdvance("199.9 ms") + 6
                gw = max(24, gw - self._scale_w)
            gap_above = 6 if lines else 0
            # a caption above the plot needs its own line of space
            title_h = 0
            if str(p.get("graph_title", "")).strip():
                title_h = QFontMetrics(self._small_font()).height() + 2
            self._graph_title_h = title_h
            self._graph_rect = (
                pad, int(h - pad + gap_above + title_h), gw, gh,
            )
            h = h + gap_above + title_h + gh

        self._apply_geometry(int(w), int(h))
        self.update()

    def _apply_geometry(self, w: int, h: int) -> None:
        """Resize/move only when values actually change (avoids flicker)."""
        if self.width() != w or self.height() != h:
            self.resize(w, h)
            if self.embedded:
                # a child widget is placed by its layout, so it has to ask
                self.setMinimumSize(w, h)
                self.updateGeometry()
        if not self.embedded:
            self._reposition()

    def _assign_columns(self, lines: list[Line], cols: int) -> int:
        per_col = -(-len(lines) // cols) if lines else 1
        while True:
            positions: list[tuple[int, int]] = []
            col = row = 0
            overflow = False
            for ln in lines:
                if ln.kind == "header" and row == per_col - 1 and cols > 1:
                    col += 1
                    row = 0
                if row >= per_col:
                    col += 1
                    row = 0
                if col >= cols:
                    overflow = True
                    break
                positions.append((col, row))
                row += 1
            if not overflow:
                self._positions = positions
                return per_col
            per_col += 1

    def set_anchor_rect(self, rect: tuple[int, int, int, int] | None) -> None:
        """Rectangle to position within: the game's window, or None for screen."""
        if rect != self._anchor:
            self._anchor = rect
            self._reposition()

    def _reposition(self) -> None:
        p = self.profile
        screens = QGuiApplication.screens()
        if not screens:
            return
        idx = max(0, min(int(p.get("monitor", 0)), len(screens) - 1))
        geo = screens[idx].geometry()
        # Anchor inside the focused game's window when it is windowed, so the
        # overlay sits on the game rather than in a screen corner beside it.
        if self._anchor is not None and p.get("anchor_to_window", True):
            ax, ay, aw, ah = self._anchor
        else:
            ax, ay, aw, ah = geo.left(), geo.top(), geo.width(), geo.height()
        left, top, right, bottom = ax, ay, ax + aw, ay + ah

        mx, my = int(p["margin_x"]), int(p["margin_y"])
        pos = p.get("position", "top_left")
        w, h = self.width(), self.height()
        if pos == "top_left":
            x, y = left + mx, top + my
        elif pos == "top_right":
            x, y = right - w - mx, top + my
        elif pos == "bottom_left":
            x, y = left + mx, bottom - h - my
        elif pos == "bottom_right":
            x, y = right - w - mx, bottom - h - my
        elif pos == "top_center":
            x, y = (left + right) // 2 - w // 2, top + my
        else:
            # custom: offset is relative to the anchor so it follows the window
            x = left + int(p.get("custom_x", 40))
            y = top + int(p.get("custom_y", 40))
        x, y = int(x), int(y)
        if self.x() != x or self.y() != y:
            self.move(x, y)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self.embedded:
            self._apply_native_styles()
        self._sync_graph_timer()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        if hasattr(self, "_graph_timer"):
            self._graph_timer.stop()

    def close_hooks(self) -> None:
        if hasattr(self, "_graph_timer"):
            self._graph_timer.stop()
        if _IS_WIN and getattr(self, "_winevent_hook", None):
            try:
                _user32.UnhookWinEvent(self._winevent_hook)
            except Exception:
                pass
            self._winevent_hook = None

    # -- painting ----------------------------------------------------------
    def _label_color_for(self, group: str, base: QColor, alpha: int) -> QColor:
        p = self.profile
        if p.get("use_group_colors", False):
            hexval = (p.get("group_colors") or {}).get(group)
            if hexval:
                c = QColor(hexval)
                c.setAlpha(alpha)
                return c
        return base

    def paintEvent(self, event) -> None:  # noqa: N802
        p = self.profile
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # The widget has WA_NoSystemBackground, so the dirty region is not
        # erased for us. Without this, partial repaints composite each new
        # trail on top of the previous one and the graph turns into a smear of
        # overlapping segments.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(event.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        bg_op = int(p.get("bg_opacity", 45))
        if bg_op > 0:
            bg = QColor(p["bg_color"])
            bg.setAlpha(int(255 * bg_op / 100))
            radius = float(p.get("corner_radius", 8))
            path = QPainterPath()
            path.addRoundedRect(
                QRectF(0, 0, self.width(), self.height()), radius, radius
            )
            painter.fillPath(path, bg)

        painter.setFont(self.font_main)
        alpha = int(255 * int(p.get("text_opacity", 100)) / 100)

        def c(key: str, mult: float = 1.0) -> QColor:
            col = QColor(p[key])
            col.setAlpha(int(alpha * mult))
            return col

        col_value, col_label = c("text_color"), c("label_color")
        state_col = {"ok": col_value, "warn": c("warn_color"), "crit": c("crit_color")}

        # When only the graph strip is dirty (the common case at 60 Hz) the
        # text is left untouched, so animating the graph costs almost nothing.
        # The dirty rect is padded by a pixel for antialiasing, hence the -2.
        if self._graph_rect is not None and event.rect().top() >= self._graph_rect[1] - 2:
            self._paint_graph(painter, alpha)
            painter.end()
            return

        pad = int(p["padding"])
        ascent = self.fm.ascent()
        shadow = bool(p.get("shadow", True))

        def draw(x: int, y: int, text: str, color: QColor) -> None:
            if shadow:
                painter.setPen(QPen(QColor(0, 0, 0, min(210, alpha))))
                painter.drawText(x + 1, y + 1, text)
            painter.setPen(QPen(color))
            painter.drawText(x, y, text)

        if p.get("layout", "rows") == "compact":
            draw(pad, pad + ascent, self._compact_text, col_value)
        else:
            show_labels = bool(p.get("show_labels", True))
            align = bool(p.get("align_values", True))
            for i, ln in enumerate(self._lines):
                if i < len(self._positions):
                    col, row = self._positions[i]
                else:
                    col, row = i // max(1, self._per_col), i % max(1, self._per_col)
                x = pad + col * self._col_w
                y = pad + row * self._line_h + ascent

                if ln.kind == "header":
                    draw(x, y, ln.label,
                         self._label_color_for(ln.group, c("label_color", 0.7), alpha))
                    continue

                if show_labels:
                    draw(x, y, ln.label,
                         self._label_color_for(ln.group, col_label, alpha))
                    vx = x + self._label_w
                else:
                    vx = x
                if align:
                    vx += self._value_w - self.fm.horizontalAdvance(ln.value)
                draw(int(vx), y, ln.value, state_col.get(ln.state, col_value))
                if ln.unit:
                    # unit trails the right-aligned value in a smaller face
                    ux = x + self._label_w + self._value_w + 3
                    painter.setFont(self._unit_font())
                    draw(int(ux), y, ln.unit, c("label_color", 0.85))
                    painter.setFont(self.font_main)

        if self._graph_rect is not None:
            self._paint_graph_title(painter, alpha)
            self._paint_graph(painter, alpha)
        painter.end()

    def _paint_graph_title(self, painter: QPainter, alpha: int) -> None:
        title = str(self.profile.get("graph_title", "")).strip()
        if not title or self._graph_rect is None:
            return
        gx, gy, _gw, _gh = self._graph_rect
        f = self._small_font()
        painter.setFont(f)
        fm = QFontMetrics(f)
        painter.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.55))))
        painter.drawText(gx, gy - getattr(self, "_graph_title_h", 0) + fm.ascent(),
                         title)
        painter.setFont(self.font_main)

    def _update_lag(self) -> None:
        """Track how far behind real time the graph must draw.

        The delay covers how stale the newest frame typically is, so it adapts
        to whatever cadence PresentMon delivers at. Without it the rightmost
        part of the graph is always empty and then fills in a jump when the
        next burst lands.

        Only recalculated when new data arrives; doing it per repaint meant a
        list scan sixty times a second to track a value that changes once.
        """
        now = time.monotonic()
        if not self._series:
            return
        observed = now - self._series[-1][0]
        self._lag_samples.append((now, observed))
        cutoff = now - 3.0
        while self._lag_samples and self._lag_samples[0][0] < cutoff:
            self._lag_samples.pop(0)
        # Worst staleness seen recently, plus headroom: the buffer has to
        # cover the longest gap between deliveries, not the average one.
        target = max(v for _t, v in self._lag_samples) * 1.15 + 0.03
        target = max(0.05, min(target, 2.0))
        # Grow quickly (running dry would stall the trace), shrink slowly.
        k = 0.30 if target > self._lag else 0.06
        self._lag += (target - self._lag) * k

    def _render_clock(self, series: list[tuple[float, float]]) -> float:
        """The time the graph is currently drawing."""
        return time.monotonic() - self._lag

    def _graph_points(
        self, gw: int, window: float
    ) -> list[tuple[float, float]]:
        """Map the timestamped series onto (x offset, ms), newest at the right.

        Position comes from each frame's real timestamp, so between repaints
        the whole trail slides left by exactly the elapsed time -- that is what
        makes the motion continuous rather than a jump per sensor tick.
        """
        series = self._series
        if not series:
            # fall back to the untimed history (used by offline rendering)
            n = len(self.history)
            if n < 2:
                return []
            step = gw / float(n - 1)
            return [(i * step, ms) for i, ms in enumerate(self.history)]

        now = self._render_clock(series)
        pts: list[tuple[float, float]] = []
        for ts, ms in series:
            age = now - ts
            if age < 0:
                continue          # not yet due on the display clock
            if age > window:
                continue
            pts.append((gw * (1.0 - age / window), ms))
        # Only decimate at absurd densities. Binning to integer pixel columns
        # quantises positions in screen space, so as the trail scrolls a spike
        # jumps between adjacent columns and flickers -- it was the last
        # remaining source of visible jitter. Qt draws a few thousand points
        # per frame comfortably, so keep them all.
        if len(pts) > 8000:
            bins: dict[int, float] = {}
            for x, ms in pts:
                k = int(x)
                if ms > bins.get(k, 0.0):
                    bins[k] = ms
            pts = [(float(k), v) for k, v in sorted(bins.items())]
        # (kept for tests and the non-cached path; the live renderer uses
        #  _build_graph_cache, which decimates in time rather than in pixels)

        # Carry the newest frame out to the right edge. PresentMon delivers in
        # bursts, so the last known frame can be a fraction of a second old;
        # without this the trace visibly stops short of "now" between bursts.
        if pts and pts[-1][0] < gw:
            pts.append((float(gw), pts[-1][1]))
        return pts

    def _build_graph_cache(self, gx, gy, gw, gh, window, alpha):
        """Build the trail once per data update instead of once per frame.

        The x axis is time, so between updates scrolling is a pure horizontal
        translation of the same geometry -- there is nothing to recompute.
        Decimation buckets by absolute time rather than by screen column: a
        pixel-column bucket shifts as the trail scrolls, which made spikes
        jump between adjacent columns and flicker.
        """
        p = self.profile
        series = self._series
        render_now = time.monotonic() - self._lag
        pps = gw / window if window else 1.0

        # One bucket per pixel column. A line cannot show two values in the
        # same column, and measurement showed the extra points were most of
        # the drawing cost. Each bucket keeps its worst frame, so decimating
        # never hides a spike.
        bucket = window / max(1.0, float(gw))
        buckets: dict[int, float] = {}
        for ts, ms in series:
            age = render_now - ts
            if age < -0.5 or age > window + 0.5:
                continue
            k = int(ts / bucket)
            if ms > buckets.get(k, 0.0):
                buckets[k] = ms
        if len(buckets) < 2:
            return None

        pts = [(k * bucket, v) for k, v in sorted(buckets.items())]
        values = [v for _t, v in pts]
        ordered = sorted(values)
        med = ordered[len(ordered) // 2]

        fixed = float(p.get("graph_max_ms", 0) or 0)
        if fixed > 0:
            top = fixed
        else:
            p98 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.98))]
            want = max(p98 * 1.35, med * 2.0, 16.7)
            prev = getattr(self, "_graph_scale", want)
            held = getattr(self, "_graph_scale_target", want)
            if want > held * 1.12 or want < held * 0.80:
                held = want
            self._graph_scale_target = held
            # eased at the data rate rather than the frame rate; the step is
            # larger to compensate for running ~6x less often
            top = prev + (held - prev) * (0.25 if held > prev else 0.08)
        top = max(5.0, min(top, 200.0))
        self._graph_scale = top

        def x_of(ts):
            return gx + gw - (render_now - ts) * pps

        def y_of(ms):
            return gy + gh - (min(ms, top) / top) * gh

        path = QPainterPath()
        path.moveTo(x_of(pts[0][0]), y_of(pts[0][1]))
        for ts, ms in pts[1:]:
            path.lineTo(x_of(ts), y_of(ms))
        # Carry the newest value past the right edge so the gap that opens
        # while scrolling between rebuilds is never visible.
        overhang = gx + gw + pps * (self.FETCH_INTERVAL + 0.4)
        path.lineTo(overhang, y_of(pts[-1][1]))

        fill = None
        if p.get("graph_fill", True):
            fill = QPainterPath(path)
            fill.lineTo(overhang, gy + gh)
            fill.lineTo(x_of(pts[0][0]), gy + gh)
            fill.closeSubpath()

        spikes = []
        if p.get("graph_show_spikes", True):
            limit = max(
                med * float(p.get("graph_spike_mult", 1.8)),
                med + float(p.get("graph_spike_floor_ms", 5.0)),
            )
            spikes = [(x_of(ts), y_of(ms)) for ts, ms in pts if ms > limit]

        return {
            "path": path, "fill": fill, "spikes": spikes,
            "top": top, "pps": pps, "t_ref": render_now,
            "gx": gx, "gy": gy, "gw": gw, "gh": gh, "window": window,
            "points": len(pts),
        }

    def _draw_cached_graph(self, painter: QPainter, cache: dict, alpha: int) -> None:
        """Draw the prepared trail, shifted to the current moment.

        Scrolling is the whole of the animation, and scrolling is a
        translation, so nothing here recomputes geometry.
        """
        p = self.profile
        gx, gy, gw, gh = cache["gx"], cache["gy"], cache["gw"], cache["gh"]
        top = cache["top"]

        if p.get("graph_guides", True):
            painter.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.18))))
            for ms in (16.67, 33.33):
                if ms < top:
                    yy = int(gy + gh - (ms / top) * gh)
                    painter.drawLine(gx, yy, gx + gw, yy)

        col_line = QColor(p.get("graph_color", "#00FF66"))
        col_line.setAlpha(alpha)
        col_spike = QColor(p.get("graph_spike_color", "#FF3B30"))
        col_spike.setAlpha(alpha)
        width = max(1, int(p.get("graph_line_width", 2)))

        dx = (time.monotonic() - self._lag - cache["t_ref"]) * cache["pps"]
        painter.save()
        painter.setClipRect(gx, gy, gw, gh)
        painter.translate(-dx, 0)

        if cache["fill"] is not None:
            grad = QLinearGradient(0, gy, 0, gy + gh)
            c0 = QColor(col_line); c0.setAlpha(int(alpha * 0.38))
            c1 = QColor(col_line); c1.setAlpha(0)
            grad.setColorAt(0.0, c0)
            grad.setColorAt(1.0, c1)
            painter.fillPath(cache["fill"], QBrush(grad))

        if p.get("graph_trail", True):
            lg = QLinearGradient(QPointF(gx + dx, 0), QPointF(gx + gw + dx, 0))
            fade0 = QColor(col_line); fade0.setAlpha(int(alpha * 0.55))
            fade1 = QColor(col_line); fade1.setAlpha(int(alpha * 0.80))
            lg.setColorAt(0.0, fade0)
            lg.setColorAt(0.45, fade1)
            lg.setColorAt(1.0, col_line)
            pen = QPen(QBrush(lg), width)
        else:
            pen = QPen(col_line, width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(cache["path"])

        for sx, sy in cache["spikes"]:
            sc = QColor(col_spike)
            if p.get("graph_trail", True) and gw:
                frac = max(0.0, min(1.0, (sx - dx - gx) / gw))
                sc.setAlpha(int(alpha * (0.65 + 0.35 * frac)))
            stem = QColor(sc)
            stem.setAlpha(int(sc.alpha() * 0.45))
            painter.setPen(QPen(stem, 1))
            painter.drawLine(QPointF(sx, sy), QPointF(sx, float(gy + gh)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(sc))
            painter.drawEllipse(QPointF(sx, sy), width * 0.9, width * 0.9)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.restore()

        f = self._small_font()
        painter.setFont(f)
        fm = QFontMetrics(f)
        painter.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.5))))
        label = f"{top:.1f} ms" if top < 100 else f"{top:.0f} ms"
        if p.get("graph_scale_pos", "left") == "right":
            painter.drawText(gx + gw + 6, gy + fm.ascent(), label)
        elif p.get("graph_scale_pos", "left") != "none":
            painter.drawText(gx + 2, gy + fm.ascent(), label)
        painter.setFont(self.font_main)

    def _paint_graph(self, painter: QPainter, alpha: int) -> None:
        """Frame-time graph: one point per presented frame, scrolling in real
        time. Frame time is plotted rather than FPS because stutter shows up as
        spikes that an averaged FPS number hides completely."""
        p = self.profile
        gx, gy, gw, gh = self._graph_rect  # type: ignore[misc]
        window = float(p.get("graph_seconds", 4.0))

        bg_op = int(p.get("graph_bg_opacity", 25))
        if bg_op > 0:
            bg = QColor(p["bg_color"])
            bg.setAlpha(int(255 * bg_op / 100))
            painter.fillRect(gx, gy, gw, gh, bg)

        cache = self._gcache
        if cache is None or (cache["gx"], cache["gy"], cache["gw"], cache["gh"],
                             cache["window"]) != (gx, gy, gw, gh, window):
            cache = self._build_graph_cache(gx, gy, gw, gh, window, alpha)
            self._gcache = cache

        if cache is not None and p.get("graph_style", "line") != "bars":
            self._draw_cached_graph(painter, cache, alpha)
            return

        pts = self._graph_points(gw, window)
        if len(pts) < 2:
            painter.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.25))))
            painter.drawLine(gx, gy + gh - 1, gx + gw, gy + gh - 1)
            f = QFont(self.font_main)
            f.setPointSize(max(7, int(p["font_size"]) - 4))
            f.setBold(False)
            painter.setFont(f)
            painter.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.45))))
            painter.drawText(gx + 4, gy + gh // 2 + 4, "frametime - waiting for frames")
            painter.setFont(self.font_main)
            return

        values = [ms for _x, ms in pts]
        ordered = sorted(values)
        med = ordered[len(ordered) // 2]

        fixed_max = float(p.get("graph_max_ms", 0) or 0)
        if fixed_max > 0:
            top = fixed_max
        else:
            # Scale to the 98th percentile, not the maximum: one 47 ms hitch
            # must not squash a 9 ms baseline into an unreadable flat line at
            # the bottom. Spikes past the top are clipped but still drawn, so
            # nothing is hidden.
            p98 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.98))]
            # med * 2 puts a steady baseline halfway up and makes a doubled
            # frame (the classic dropped-frame case) land exactly at the top.
            want = max(p98 * 1.35, med * 2.0, 16.7)
            prev = getattr(self, "_graph_scale", want)
            held = getattr(self, "_graph_scale_target", want)
            # Dead zone: only accept a new target when it differs materially.
            # Without it the target moved every frame and the whole curve
            # breathed vertically -- the 17ms/39ms swing.
            if want > held * 1.12 or want < held * 0.80:
                held = want
            self._graph_scale_target = held
            # ease slowly; falling back down is slower still so a burst of
            # spikes does not make the graph pump up and down
            top = prev + (held - prev) * (0.05 if held > prev else 0.015)
        top = max(5.0, min(top, 200.0))
        self._graph_scale = top

        def y_for(ms: float) -> float:
            return gy + gh - (min(ms, top) / top) * gh

        if p.get("graph_guides", True):
            painter.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.18))))
            for ms in (16.67, 33.33):
                if ms < top:
                    yy = int(y_for(ms))
                    painter.drawLine(gx, yy, gx + gw, yy)

        # A stutter must be relatively AND absolutely worse than typical.
        # Relative-only (the old med * 1.5) flags harmless jitter on a locked
        # framerate: at 110 FPS a 13.7 ms frame is invisible to the eye but
        # tripped the threshold.
        spike_ms = max(
            med * float(p.get("graph_spike_mult", 1.8)),
            med + float(p.get("graph_spike_floor_ms", 5.0)),
        )
        col_line = QColor(p.get("graph_color", "#00FF66"))
        col_line.setAlpha(alpha)
        col_spike = QColor(p.get("graph_spike_color", "#FF3B30"))
        col_spike.setAlpha(alpha)

        if p.get("graph_style", "line") == "bars":
            painter.setPen(Qt.PenStyle.NoPen)
            bw = max(1.0, gw / max(1, len(pts)))
            for x, ms in pts:
                yy = y_for(ms)
                painter.fillRect(
                    QRectF(gx + x, yy, bw, gy + gh - yy),
                    col_spike if ms > spike_ms else col_line,
                )
        else:
            path = QPainterPath()
            path.moveTo(gx + pts[0][0], y_for(pts[0][1]))
            for x, ms in pts[1:]:
                path.lineTo(gx + x, y_for(ms))

            # Gradient fill under the curve gives the trail its body.
            if p.get("graph_fill", True):
                fill = QPainterPath(path)
                fill.lineTo(gx + pts[-1][0], gy + gh)
                fill.lineTo(gx + pts[0][0], gy + gh)
                fill.closeSubpath()
                grad = QLinearGradient(0, gy, 0, gy + gh)
                c0 = QColor(col_line); c0.setAlpha(int(alpha * 0.38))
                c1 = QColor(col_line); c1.setAlpha(0)
                grad.setColorAt(0.0, c0)
                grad.setColorAt(1.0, c1)
                painter.fillPath(fill, QBrush(grad))

            # A horizontal gradient on the pen fades the oldest part of the
            # trail out, so the line reads as motion rather than a static plot.
            width = max(1, int(p.get("graph_line_width", 2)))
            if p.get("graph_trail", True):
                # The tail dims but never disappears: fading to zero made the
                # line look truncated rather than continuous.
                lg = QLinearGradient(QPointF(gx, 0), QPointF(gx + gw, 0))
                fade0 = QColor(col_line); fade0.setAlpha(int(alpha * 0.55))
                fade1 = QColor(col_line); fade1.setAlpha(int(alpha * 0.80))
                lg.setColorAt(0.0, fade0)
                lg.setColorAt(0.45, fade1)
                lg.setColorAt(1.0, col_line)
                pen = QPen(QBrush(lg), width)
            else:
                pen = QPen(col_line, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawPath(path)

            # Stutter markers: a hairline plus a dot on the peak. The old
            # full-height filled bar read as a solid red block that dominated
            # the strip; this points at the spike without burying the curve.
            trail = bool(p.get("graph_trail", True))
            for x, ms in pts if p.get("graph_show_spikes", True) else ():
                if ms <= spike_ms:
                    continue
                sc = QColor(col_spike)
                if trail and gw > 0:
                    sc.setAlpha(int(alpha * (0.65 + 0.35 * (x / gw))))
                yy = y_for(ms)
                stem = QColor(sc)
                stem.setAlpha(int(sc.alpha() * 0.45))
                painter.setPen(QPen(stem, 1))
                painter.drawLine(
                    QPointF(gx + x, yy), QPointF(gx + x, float(gy + gh))
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(sc))
                painter.drawEllipse(QPointF(gx + x, yy), width * 0.9, width * 0.9)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(Qt.PenStyle.NoPen)
            # Leading dot marks "now" (skipped in the bare RTSS-style look).
            if p.get("graph_show_spikes", True) or p.get("graph_fill", True):
                painter.setBrush(QBrush(col_line))
                lx, lms = pts[-1]
                painter.drawEllipse(
                    QPointF(gx + lx, y_for(lms)), width + 0.8, width + 0.8
                )
                painter.setBrush(Qt.BrushStyle.NoBrush)

        scale_pos = p.get("graph_scale_pos", "left")
        if scale_pos != "none":
            f = self._small_font()
            painter.setFont(f)
            fm = QFontMetrics(f)
            painter.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.5))))
            label = f"{top:.1f} ms" if top < 100 else f"{top:.0f} ms"
            if scale_pos == "right":
                # sits beside the plot in the reserved gutter, never over it
                painter.drawText(gx + gw + 6, gy + fm.ascent(), label)
            else:
                painter.drawText(gx + 2, gy + fm.ascent(), label)
            painter.setFont(self.font_main)

    # -- dragging (only when unlocked) -------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None:
            self._drag_from = None
            self.profile["position"] = "custom"
            # store the offset relative to whatever we are anchored to, so a
            # dragged position keeps following the game window
            if self._anchor is not None and self.profile.get("anchor_to_window", True):
                self.profile["custom_x"] = self.x() - self._anchor[0]
                self.profile["custom_y"] = self.y() - self._anchor[1]
            else:
                screens = QGuiApplication.screens()
                idx = max(0, min(int(self.profile.get("monitor", 0)),
                                 len(screens) - 1))
                geo = screens[idx].geometry() if screens else None
                self.profile["custom_x"] = self.x() - (geo.left() if geo else 0)
                self.profile["custom_y"] = self.y() - (geo.top() if geo else 0)
