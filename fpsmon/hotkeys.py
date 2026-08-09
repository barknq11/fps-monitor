"""
Global hotkeys.

Two mechanisms exist on Windows and only one of them is dependable here:

* A WH_KEYBOARD_LL hook (what the `keyboard` package uses).  It needs the
  process to be attached to the interactive window station and it competes with
  anti-cheat drivers, so in practice it can silently receive nothing at all.
* RegisterHotKey(), which asks the OS to reserve the combination and posts
  WM_HOTKEY to our thread's message queue.  Qt already pumps that queue, so a
  QAbstractNativeEventFilter picks the message up on the GUI thread -- no extra
  thread, no hook, and no interference with the game's own input.

RegisterHotKey is therefore the primary path; the `keyboard` package is kept as
a fallback for combinations Windows refuses to reserve.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

_IS_WIN = sys.platform == "win32"

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_MODIFIERS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "super": MOD_WIN, "cmd": MOD_WIN,
}

_NAMED_KEYS = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B,
    "escape": 0x1B, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21,
    "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "printscreen": 0x2C, "scrolllock": 0x91, "pause": 0x13,
    "numlock": 0x90, "capslock": 0x14,
    "add": 0x6B, "subtract": 0x6D, "multiply": 0x6A, "divide": 0x6F,
    "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC, "`": 0xC0,
}


def parse_combo(combo: str) -> tuple[int, int] | None:
    """'ctrl+alt+f' -> (modifier mask, virtual key code)."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    key: str | None = None
    for part in parts:
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        else:
            key = part
    if key is None:
        return None
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    else:
        return None
    return mods, vk


class _NativeFilter(QAbstractNativeEventFilter):
    """Catches WM_HOTKEY off the Qt event loop (already the GUI thread)."""

    def __init__(self, owner: "HotkeyManager"):
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        try:
            if event_type == b"windows_generic_MSG":
                msg = ctypes.cast(
                    int(message), ctypes.POINTER(wintypes.MSG)
                ).contents
                if msg.message == WM_HOTKEY:
                    self.owner._on_wm_hotkey(int(msg.wParam))
        except Exception:
            pass
        return False, 0


class HotkeyManager(QObject):
    """Registers global hotkeys and invokes actions on the GUI thread."""

    # emitted from the `keyboard` fallback thread; queued to the GUI thread
    _fallback_fired = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._actions: dict[str, Callable[[], None]] = {}
        self._bindings: dict[str, str] = {}
        self._ids: dict[int, str] = {}      # hotkey id -> action
        self._next_id = 0xB000
        self._fallback_actions: set[str] = set()
        self.errors: dict[str, str] = {}
        self.method: dict[str, str] = {}    # action -> "winapi" | "hook"

        self._fallback_fired.connect(self._dispatch)

        self._filter = None
        if _IS_WIN:
            from PySide6.QtCore import QCoreApplication

            self._filter = _NativeFilter(self)
            app = QCoreApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self._filter)

    # ------------------------------------------------------------------
    def set_action(self, name: str, fn: Callable[[], None]) -> None:
        self._actions[name] = fn

    def _dispatch(self, name: str) -> None:
        fn = self._actions.get(name)
        if fn is not None:
            fn()

    def _on_wm_hotkey(self, hotkey_id: int) -> None:
        action = self._ids.get(hotkey_id)
        if action:
            self._dispatch(action)

    # ------------------------------------------------------------------
    def apply(self, bindings: dict[str, str]) -> None:
        cleaned = {
            a: (c or "").strip().lower()
            for a, c in bindings.items()
            if (c or "").strip()
        }
        if cleaned == self._bindings:
            return
        self._unregister_all()
        self._bindings = cleaned
        self.errors = {}
        self.method = {}
        if not _IS_WIN:
            return

        user32 = ctypes.windll.user32
        seen: dict[str, str] = {}
        needs_fallback: dict[str, str] = {}

        for action, combo in cleaned.items():
            if combo in seen:
                self.errors[action] = f"'{combo}' already used by {seen[combo]}"
                continue
            parsed = parse_combo(combo)
            if parsed is None:
                self.errors[action] = f"'{combo}' is not a valid combination"
                continue
            mods, vk = parsed
            hid = self._next_id
            self._next_id += 1
            ok = user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk)
            if ok:
                self._ids[hid] = action
                self.method[action] = "winapi"
                seen[combo] = action
            else:
                # usually ERROR_HOTKEY_ALREADY_REGISTERED (another app owns it)
                needs_fallback[action] = combo
                seen[combo] = action

        if needs_fallback:
            self._register_fallback(needs_fallback)

    def _register_fallback(self, bindings: dict[str, str]) -> None:
        try:
            import keyboard
        except Exception as exc:
            for action, combo in bindings.items():
                self.errors[action] = (
                    f"'{combo}' is already taken by another program "
                    f"(fallback unavailable: {exc})"
                )
            return
        for action, combo in bindings.items():
            try:
                keyboard.add_hotkey(
                    combo,
                    lambda a=action: self._fallback_fired.emit(a),
                    suppress=False,
                )
                self._fallback_actions.add(action)
                self.method[action] = "hook"
            except Exception as exc:
                self.errors[action] = f"'{combo}' could not be registered: {exc}"

    # ------------------------------------------------------------------
    def _unregister_all(self) -> None:
        if _IS_WIN:
            user32 = ctypes.windll.user32
            for hid in list(self._ids):
                try:
                    user32.UnregisterHotKey(None, hid)
                except Exception:
                    pass
        self._ids.clear()
        if self._fallback_actions:
            try:
                import keyboard

                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
            self._fallback_actions.clear()

    def stop(self) -> None:
        self._unregister_all()
        self._bindings = {}

    # ------------------------------------------------------------------
    def status(self) -> str:
        n = len(self._ids) + len(self._fallback_actions)
        if self.errors:
            problems = "; ".join(f"{a}: {m}" for a, m in self.errors.items())
            return f"{n} hotkeys active, problems -> {problems}"
        if n == 0:
            return "no hotkeys registered"
        return f"{n} hotkey{'s' if n != 1 else ''} active"
