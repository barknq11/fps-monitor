"""
Crash and error reporting.

A packaged build is windowed, so there is no console: anything printed to
stderr, including tracebacks, goes nowhere. Without this an unhandled
exception on someone else's machine produces silence for them and no report
for us.

Everything is written to logs/error.log, the most recent failure is kept in
memory so the UI can mention it, and Qt's own warnings are captured too.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import threading
import traceback
from typing import Callable

from . import __version__, paths

LOG_NAME = "error.log"
MAX_BYTES = 512 * 1024          # keep the log from growing without bound

_lock = threading.Lock()
_listeners: list[Callable[[str], None]] = []
_last: str = ""


def log_path() -> str:
    return os.path.join(paths.data("logs"), LOG_NAME)


def last_error() -> str:
    return _last


def add_listener(fn: Callable[[str], None]) -> None:
    """Called with a one-line summary whenever something is logged."""
    _listeners.append(fn)


def _trim(path: str) -> None:
    try:
        if os.path.getsize(path) <= MAX_BYTES:
            return
        with open(path, encoding="utf-8", errors="replace") as fh:
            tail = fh.read()[-MAX_BYTES // 2:]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("... earlier entries trimmed ...\n" + tail)
    except Exception:
        pass


def write(kind: str, detail: str) -> None:
    """Append an entry and notify anyone listening."""
    global _last
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = detail.strip().splitlines()[-1] if detail.strip() else kind
    _last = f"{stamp}  {kind}: {summary}"

    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(
                    f"\n{'=' * 70}\n{stamp}  FPS Monitor {__version__}  "
                    f"frozen={paths.FROZEN}\n{kind}\n{'-' * 70}\n{detail}\n"
                )
            _trim(path)
    except Exception:
        pass

    for fn in list(_listeners):
        try:
            fn(_last)
        except Exception:
            pass


def install() -> None:
    """Route unhandled exceptions, thread crashes and Qt messages to the log."""

    def _excepthook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        write(
            f"Unhandled {exc_type.__name__}",
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )

    sys.excepthook = _excepthook

    # Exceptions inside threads do not reach sys.excepthook.
    def _thread_hook(args) -> None:
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
        write(
            f"Unhandled {args.exc_type.__name__} in thread "
            f"{getattr(args.thread, 'name', '?')}",
            "".join(traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback
            )),
        )

    try:
        threading.excepthook = _thread_hook
    except Exception:
        pass

    _install_qt_handler()


def _install_qt_handler() -> None:
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return

    # Qt chatters at debug/info level; only real problems are worth a file.
    interesting = {
        QtMsgType.QtWarningMsg: "Qt warning",
        QtMsgType.QtCriticalMsg: "Qt critical",
        QtMsgType.QtFatalMsg: "Qt fatal",
    }

    def handler(mode, context, message) -> None:
        kind = interesting.get(mode)
        if kind is None:
            return
        where = ""
        try:
            if context.file:
                where = f"\n  at {context.file}:{context.line}"
        except Exception:
            pass
        write(kind, f"{message}{where}")

    try:
        qInstallMessageHandler(handler)
    except Exception:
        pass


def report(where: str, exc: BaseException) -> None:
    """Record a caught exception that would otherwise be swallowed."""
    write(
        f"{type(exc).__name__} in {where}",
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )
