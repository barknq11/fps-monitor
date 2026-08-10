"""
Custom controls for the settings window.
"""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from .hotkeys import parse_combo

# Qt key -> the name used in a combo string. Only keys that RegisterHotKey
# can actually reserve are listed; the rest are rejected on capture.
_NAMED = {
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Print: "printscreen",
    Qt.Key.Key_ScrollLock: "scrolllock",
    Qt.Key.Key_Pause: "pause",
    Qt.Key.Key_NumLock: "numlock",
    Qt.Key.Key_CapsLock: "capslock",
    Qt.Key.Key_Minus: "-",
    Qt.Key.Key_Equal: "=",
    Qt.Key.Key_BracketLeft: "[",
    Qt.Key.Key_BracketRight: "]",
    Qt.Key.Key_Semicolon: ";",
    Qt.Key.Key_Apostrophe: "'",
    Qt.Key.Key_Comma: ",",
    Qt.Key.Key_Period: ".",
    Qt.Key.Key_Slash: "/",
    Qt.Key.Key_Backslash: "\\",
    Qt.Key.Key_QuoteLeft: "`",
}

_MODIFIER_KEYS = {
    Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
    Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
}


def key_event_to_combo(event: QKeyEvent) -> str | None:
    """Turn a key press into a combo string, or None if it is not usable."""
    key = Qt.Key(event.key())
    if key in _MODIFIER_KEYS:
        return None                      # still waiting for the real key

    mods = event.modifiers()
    parts = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        parts.append("ctrl")
    if mods & Qt.KeyboardModifier.AltModifier:
        parts.append("alt")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        parts.append("shift")
    if mods & Qt.KeyboardModifier.MetaModifier:
        parts.append("win")

    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        name = f"f{key - Qt.Key.Key_F1 + 1}"
    elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        name = chr(key - Qt.Key.Key_A + ord("a"))
    elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        name = chr(key - Qt.Key.Key_0 + ord("0"))
    elif key in _NAMED:
        name = _NAMED[key]
    else:
        return None

    parts.append(name)
    return "+".join(parts)


class OverlayPreview(QWidget):
    """Live preview of the overlay, drawn by the real overlay widget.

    Sample readings are plausible rather than real: the settings window is
    not a game, so there are no frames to measure. The frame-time graph is
    fed a synthetic stream so it animates exactly as it would in play.
    """

    SAMPLE = {
        "fps": 144.0, "fps_1low": 118.0, "fps_01low": 96.0,
        "frametime": 6.94, "frametime_max": 14.2, "frametime_med": 6.90,
        "frametime_jitter": 0.42, "stutter_pct": 0.6, "app": "yourgame.exe",
        "cpu_load": 48.0, "cpu_load_max": 71.0, "cpu_temp": 62.0,
        "cpu_clock": 4050, "cpu_clock_avg": 3900, "cpu_power": 74.0,
        "cpu_volt": 1.31,
        "gpu_load": 96.0, "gpu_temp": 67.0, "gpu_hotspot": 82.0,
        "gpu_mem_temp": 70.0, "gpu_clock": 2650.0, "gpu_mem_clock": 2400.0,
        "gpu_power": 165.0, "gpu_fan_rpm": 1520.0, "gpu_fan_pct": 48.0,
        "gpu_volt": 0.95, "gpu_mem_load": 38.0,
        "vram_used": 7400.0, "vram_total": 16304.0, "vram_pct": 45.0,
        "vram_used_gb": 7.2, "vram_total_gb": 15.9, "vram_free_gb": 8.7,
        "ram_load": 58.0, "ram_used": 18.6, "ram_free": 13.3, "ram_total": 31.9,
        "batt_pct": 76.0, "batt_minutes": 154.0, "batt_plugged": 0.0,
    }

    def __init__(self, profile: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("PreviewStrip")
        self.setMinimumHeight(90)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)

        from .overlay import Overlay

        self.overlay = Overlay(profile, parent=self, embedded=True)
        self.overlay.set_series_provider(self._fake_series)
        lay.addWidget(self.overlay, 0, Qt.AlignmentFlag.AlignTop
                      | Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)

        self._t0 = time.monotonic()
        random.seed(11)
        self.refresh(profile)

        # keep the numbers gently moving so colour thresholds are visible
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._nudge)
        self._tick.start(700)

    # ------------------------------------------------------------------
    def _fake_series(self, seconds: float):
        """A believable 144 FPS stream with the occasional hitch."""
        now = time.monotonic()
        out = []
        t = now - seconds
        i = 0
        while t < now:
            ft = 6.94 + 0.35 * math.sin((t - self._t0) * 2.2) \
                + random.uniform(-0.25, 0.25)
            if i % 260 == 259:
                ft += random.uniform(8.0, 18.0)
            out.append((t, ft))
            t += ft / 1000.0
            i += 1
        return out

    def _nudge(self) -> None:
        if self.overlay.height() + 24 > self.minimumHeight():
            margins = self.layout().contentsMargins()
            self.setMinimumHeight(
                self.overlay.height() + margins.top() + margins.bottom()
            )
            self.updateGeometry()
        vals = dict(self.SAMPLE)
        wobble = math.sin((time.monotonic() - self._t0) * 0.9)
        vals["fps"] = round(144 + wobble * 12, 1)
        vals["frametime"] = round(1000.0 / vals["fps"], 2)
        vals["gpu_load"] = round(min(100, 92 + wobble * 6), 1)
        vals["gpu_temp"] = round(67 + wobble * 4, 1)
        vals["cpu_load"] = round(48 + wobble * 9, 1)
        vals["cpu_temp"] = round(62 + wobble * 3, 1)
        self.overlay.set_values(vals)

    def refresh(self, profile: dict) -> None:
        """Re-apply the profile after any settings change."""
        self.overlay.apply_profile(profile)
        self._nudge()
        self.overlay.show()
        # The overlay sizes itself to its content, so the strip has to follow
        # or a tall profile is simply cut off. The settings page scrolls, so
        # growing is fine; silently clipping the preview is not.
        margins = self.layout().contentsMargins()
        self.setMinimumHeight(
            self.overlay.height() + margins.top() + margins.bottom()
        )
        self.updateGeometry()

    def stop(self) -> None:
        self._tick.stop()
        self.overlay.close_hooks()


class HotkeyEdit(QPushButton):
    """Click, then press the combination you want.

    Typing "ctrl+alt+f" into a text box was the worst input in the app: no
    feedback, easy to typo, and no way to know whether the combination was
    even valid until it silently failed to register.
    """

    changed = Signal(str)

    PROMPT = "Press keys...  (Esc cancels, Backspace clears)"
    EMPTY = "Click to set"

    def __init__(self, combo: str = ""):
        super().__init__()
        self._combo = combo or ""
        self._capturing = False
        self._warning = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.clicked.connect(self._on_click)
        self._refresh()

    # ------------------------------------------------------------------
    def combo(self) -> str:
        return self._combo

    def set_combo(self, combo: str) -> None:
        self._combo = (combo or "").strip().lower()
        self._refresh()

    def set_warning(self, text: str) -> None:
        """Shown as a tooltip and an asterisk, e.g. for a duplicate binding."""
        self._warning = text
        self._refresh()

    # ------------------------------------------------------------------
    def _pretty(self) -> str:
        if not self._combo:
            return self.EMPTY
        nice = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
        parts = [nice.get(p, p.upper()) for p in self._combo.split("+")]
        return " + ".join(parts)

    def _refresh(self) -> None:
        if self._capturing:
            self.setText(self.PROMPT)
            self.setToolTip("Press the combination you want to use")
            return
        text = self._pretty()
        if self._warning:
            text += "   !"
        self.setText(text)
        self.setToolTip(self._warning or "Click to change")

    def _on_click(self) -> None:
        self._capturing = True
        self.setChecked(True)
        self._refresh()
        self.grabKeyboard()

    def _stop(self) -> None:
        self._capturing = False
        self.setChecked(False)
        self.releaseKeyboard()
        self._refresh()

    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if not self._capturing:
            super().keyPressEvent(event)
            return

        key = Qt.Key(event.key())
        if key == Qt.Key.Key_Escape:
            self._stop()
            event.accept()
            return
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and \
                not event.modifiers():
            self._combo = ""
            self._warning = ""
            self._stop()
            self.changed.emit("")
            event.accept()
            return

        combo = key_event_to_combo(event)
        if combo is None:
            event.accept()
            return                       # modifier alone, or an unusable key

        if parse_combo(combo) is None:
            self._warning = f"{combo} cannot be used as a global hotkey"
            self._stop()
            event.accept()
            return

        self._combo = combo
        self._warning = ""
        self._stop()
        self.changed.emit(combo)
        event.accept()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        if self._capturing:
            self._stop()
        super().focusOutEvent(event)
