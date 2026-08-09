"""
Custom controls for the settings window.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QPushButton

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
