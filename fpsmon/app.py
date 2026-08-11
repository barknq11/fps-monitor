"""
FPS Monitor - main application.

Ties together the sensor backend, PresentMon FPS backend, the overlay, the
settings window, global hotkeys, the tray icon and benchmark logging.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import traceback
from typing import Any

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction, QColor, QGuiApplication, QIcon, QPainter, QPixmap,
)
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import (
    __version__, bench, config, errors, focus, fps, limiter as limiter_mod,
    metrics as M, paths, sensors, shortcuts, updates,
)
from .hotkeys import HotkeyManager
from .limiter import FpsLimiter
from .overlay import Overlay
from .settings_ui import SettingsWindow

APP_NAME = "FPS Monitor"


ASSETS = paths.resource("assets")


def app_icon() -> QIcon:
    """The app logo, falling back to a drawn placeholder if it is missing."""
    for name in ("icon.ico", "logo.png", "logo_64.png"):
        path = os.path.join(ASSETS, name)
        if os.path.exists(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon

    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#101418"))
    p.setPen(QColor("#00FF66"))
    p.drawRoundedRect(2, 2, 60, 60, 12, 12)
    f = p.font(); f.setBold(True); f.setPointSize(22)
    p.setFont(f)
    p.setPen(QColor("#00FF66"))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "FPS")
    p.end()
    return QIcon(pm)


# kept for callers that used the old name
_make_icon = app_icon


def number_icon(value: str, colour: str = "#e6e9ef") -> QIcon:
    """Render a short number as a tray icon.

    A 16px tray icon cannot show a logo and a number legibly at once, so
    while something is being measured the number replaces the logo entirely,
    the way Afterburner does it. Drawn at 64px and scaled by Windows.
    """
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(10, 12, 16, 210))
    p.drawRoundedRect(0, 0, 64, 64, 12, 12)

    f = p.font()
    f.setBold(True)
    # three digits need to be smaller than two to stay inside the icon
    f.setPointSize(34 if len(value) <= 2 else 26 if len(value) == 3 else 20)
    p.setFont(f)
    p.setPen(QColor(colour))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, value)
    p.end()
    return QIcon(pm)


class _Bridge(QObject):
    """Carries results from worker threads back onto the GUI thread.

    Qt queues a signal emitted from another thread, which is the only safe
    way to touch widgets from background work.
    """

    update_result = Signal(object, bool)


class FPSMonitorApp:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        config.bootstrap()

        state = config.load_state()
        self.profile_name = state.get("active_profile", "Default")
        self.profile = config.load_profile(self.profile_name)
        # Hotkeys, poll rate and visibility belong to the app, not to a look,
        # so switching profiles cannot change them.
        self.app_settings = config.load_app_settings()

        # Both backends open slowly (LibreHardwareMonitor ~2s, PresentMon spawns
        # a process and clears stale ETW sessions), so neither blocks the window
        # from appearing - they initialise on their own threads.
        self.sensors = sensors.SensorBackend(
            interval=float(self.app_settings["update_interval"]), defer=True
        )
        self.sensors.start()

        self.fps = fps.FPSBackend()
        self.fps_ok = True
        threading.Thread(
            target=self._start_fps_backend, daemon=True, name="fpsmon-fps-init"
        ).start()

        self.recorder = bench.BenchmarkRecorder()
        self.limiter = FpsLimiter()
        self.last_foreground = focus.Foreground()
        self.last_game_exe = ""
        self._hardware_published = False
        #: profile chosen by hand, restored when an auto-switched game exits
        self._manual_profile: str | None = None
        self._tray_text = ""
        self._bridge = _Bridge()
        self._bridge.update_result.connect(self._on_update_result)
        self._update_result = self._bridge.update_result

        self.overlay = Overlay(self.profile)
        # The graph pulls its own data at its own frame rate.
        self.overlay.set_series_provider(self.fps.frametime_series)
        self._sync_retention()
        if self.profile.get("visible", True):
            self.overlay.show()

        self.settings = SettingsWindow(
            self.profile, self.status_text, self.app_settings
        )
        self.settings.changed.connect(self.on_profile_changed)
        self.settings.app_changed.connect(self.on_app_settings_changed)
        self.settings.profile_switched.connect(self.switch_profile)
        self.settings.benchmark_toggled.connect(self.toggle_benchmark)
        self.settings.limit_requested.connect(self.apply_fps_limit)
        self.settings.limit_refresh_requested.connect(self.refresh_limiter)
        self.settings.driver_panel_requested.connect(self.open_driver_panel)
        self.settings.theme_changed.connect(self.on_theme_changed)
        self.settings.gpu_selected.connect(self.on_gpu_selected)
        self.settings.open_logs_requested.connect(self._open_logs)
        self.settings.update_check_requested.connect(
            lambda: self.check_for_updates(manual=True)
        )
        self.settings.set_version(f"{__version__}")
        self.settings.refresh_runs()
        if self.app_settings.get("check_updates", True):
            QTimer.singleShot(3000, lambda: self.check_for_updates())
        self.settings.shortcut_requested.connect(self.on_shortcut_requested)
        # theme is an app preference, not part of an overlay profile
        self.settings.set_theme(state.get("theme", "dark"))
        self.settings.set_shortcut_status(shortcuts.status())
        self.settings.restore_geometry(state.get("settings_geometry"))
        self.settings.set_status(self.status_text())

        icon = app_icon()
        self.settings.setWindowIcon(icon)
        qapp.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon)
        self.tray.setToolTip(APP_NAME)
        self._build_tray_menu()
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(int(float(self.app_settings["update_interval"]) * 1000))

        # Surface problems instead of letting them vanish into a missing
        # console, but only once per session so a repeating fault cannot
        # spam notifications during a game.
        self._error_notified = False
        errors.add_listener(self._on_error_logged)

        self.hotkeys = HotkeyManager()
        self.hotkeys.set_action("toggle", self.toggle_overlay)
        self.hotkeys.set_action("benchmark", self.toggle_benchmark)
        self.hotkeys.set_action("settings", self.show_settings)
        self.hotkeys.set_action("profile", self.cycle_profile)
        self.register_hotkeys()

        # PresentMon starts on a background thread, so report a failure once
        # it has actually had a chance to fail.
        QTimer.singleShot(6000, self._warn_if_fps_unavailable)

    def _warn_if_fps_unavailable(self) -> None:
        if self.fps_ok and self.fps.error is None:
            return
        self.tray.showMessage(
            APP_NAME,
            "FPS measurement is off: " + (
                self.fps.error
                or "PresentMon could not start. Run as Administrator for FPS."
            ),
            QSystemTrayIcon.MessageIcon.Warning,
            6000,
        )

    def _start_fps_backend(self) -> None:
        try:
            self.fps_ok = self.fps.start()
            self._sync_retention()
        except Exception:
            self.fps_ok = False

    def _apply_visibility_and_anchor(self, values: dict[str, Any]) -> None:
        """Show the overlay only where it is wanted, and put it on the game."""
        p = self.profile
        if not p.get("visible", True):
            self.overlay.setVisible(False)
            return

        a = self.app_settings
        mode = a.get("visibility_mode", "game_running")
        if p.get("only_in_game", False) and mode == "always":
            mode = "rendering"          # honour the legacy option

        fg = focus.foreground()
        self.last_foreground = fg
        pids = self.fps.presenting_pids()
        blocked = set(focus.NON_GAMES) | {
            s.lower() for s in a.get("extra_non_games", [])
        }
        allowed = {s.lower() for s in a.get("extra_games", [])}
        focused_game = focus.is_game(fg, pids, blocked, allowed)

        # The game's own window, whether or not it currently has focus. This
        # is what lets the overlay stay on a windowed game while you work on
        # another monitor.
        game_win = None
        if mode in ("game_running", "game"):
            if focused_game:
                game_win = fg
            elif mode == "game_running":
                game_win = focus.find_game_window(
                    self.fps.candidates(), blocked, allowed
                )
        if game_win is not None and game_win.exe:
            if game_win.exe != self.last_game_exe:
                self.last_game_exe = game_win.exe
                self._auto_switch_profile(game_win.exe)
            self.last_game_exe = game_win.exe

        if mode == "always":
            show = True
        elif mode == "rendering":
            show = bool(values.get("fps")) or bool(pids)
        elif mode == "game":
            show = focused_game
        else:                            # "game_running"
            show = game_win is not None

        if game_win is None and self.last_game_exe:
            # the game closed: hand the profile back to whatever was chosen
            self.last_game_exe = ""
            self._restore_manual_profile()

        if show and game_win is not None and p.get("anchor_to_window", True):
            screens = QGuiApplication.screens()
            idx = max(0, min(int(p.get("monitor", 0)), len(screens) - 1))
            g = screens[idx].geometry() if screens else None
            screen_geo = (
                (g.left(), g.top(), g.width(), g.height()) if g else (0, 0, 1920, 1080)
            )
            self.overlay.set_anchor_rect(focus.anchor_rect(game_win, screen_geo))
        else:
            self.overlay.set_anchor_rect(None)

        if self.overlay.isVisible() != show:
            self.overlay.setVisible(show)

    def _auto_switch_profile(self, exe: str) -> None:
        """Adopt a profile that claims this game, if one does.

        The profile the user picked by hand is remembered, so quitting the
        game returns to it rather than leaving the game's layout behind.
        """
        try:
            wanted = config.profile_for_executable(exe)
        except Exception:
            return
        if wanted and wanted != self.profile_name:
            if self._manual_profile is None:
                self._manual_profile = self.profile_name
            self.switch_profile(wanted)
            self.tray.showMessage(
                APP_NAME, f"{exe}: switched to the \"{wanted}\" profile",
                QSystemTrayIcon.MessageIcon.Information, 3500,
            )

    def _restore_manual_profile(self) -> None:
        if self._manual_profile and self._manual_profile != self.profile_name:
            back = self._manual_profile
            self._manual_profile = None
            self.switch_profile(back)
        else:
            self._manual_profile = None

    def _sync_retention(self) -> None:
        """Keep enough frame history to fill the whole graph width."""
        try:
            # The overlay requests window + lag (capped at 2s) + 0.5s, so the
            # backend has to hold at least that much or the left of the graph
            # runs dry again.
            self.fps.set_retention(
                float(self.profile.get("graph_seconds", 4.0)) + 4.0
            )
        except Exception:
            pass

    # ------------------------------------------------------------ status
    def status_text(self) -> str:
        bits = [f"CPU: {self.sensors.cpu_name}", f"GPU: {self.sensors.gpu_name}"]
        if not self.sensors.available:
            bits.append(f"sensors unavailable ({sensors.LOAD_ERROR})")
        if not self.sensors.elevated:
            bits.append("not elevated - CPU temp/clock/power hidden")
        if not self.fps_ok:
            bits.append(f"FPS off ({self.fps.error or 'needs Administrator'})")
        elif not self.fps.available:
            bits.append("FPS: waiting for a game to present frames")
        if getattr(self, "hotkeys", None) is not None:
            bits.append(self.hotkeys.status())
        return "  |  ".join(bits)

    # ------------------------------------------------------------ tray
    def _build_tray_menu(self) -> None:
        menu = QMenu()
        a_settings = QAction("Settings...", menu)
        a_settings.triggered.connect(self.show_settings)
        menu.addAction(a_settings)

        a_toggle = QAction("Show / hide overlay", menu)
        a_toggle.triggered.connect(self.toggle_overlay)
        menu.addAction(a_toggle)

        self.profiles_menu = QMenu("Profile", menu)
        menu.addMenu(self.profiles_menu)
        self._refresh_profiles_menu()

        a_bench = QAction("Start / stop benchmark", menu)
        a_bench.triggered.connect(self.toggle_benchmark)
        menu.addAction(a_bench)

        a_logs = QAction("Open logs folder", menu)
        a_logs.triggered.connect(
            lambda: os.startfile(config.LOG_DIR)  # noqa: S606
            if os.path.isdir(config.LOG_DIR) else None
        )
        menu.addAction(a_logs)

        menu.addSeparator()
        a_quit = QAction("Quit", menu)
        a_quit.triggered.connect(self.quit)
        menu.addAction(a_quit)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)

    def _refresh_profiles_menu(self) -> None:
        self.profiles_menu.clear()
        for name in config.list_profiles():
            act = QAction(name, self.profiles_menu)
            act.setCheckable(True)
            act.setChecked(name == self.profile_name)
            act.triggered.connect(lambda _=False, n=name: self.switch_profile(n))
            self.profiles_menu.addAction(act)

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_settings()

    # ------------------------------------------------------------ actions
    def show_settings(self) -> None:
        self.settings.load_from_profile(self.profile)
        self.settings.set_status(self.status_text())
        self.refresh_limiter()
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def toggle_overlay(self) -> None:
        vis = not self.overlay.isVisible()
        self.overlay.setVisible(vis)
        self.profile["visible"] = vis

    def toggle_benchmark(self) -> None:
        if self.recorder.active:
            # Percentile lows come from every frame of the run, not from the
            # 2 Hz sample stream, so hand the captured frame times over first.
            target = self.last_game_exe
            frames = self.fps.end_capture()
            if frames:
                pids = {
                    p for p, _ in frames
                } if not target else None
                fts = [ft for _pid, ft in frames]
                self.recorder.set_frametimes(fts)
            summary = self.recorder.stop()
            path = self.recorder.path or ""
            headline = []
            for k in ("fps_avg_frames", "fps_1low", "fps_01low"):
                if k in summary:
                    headline.append(f"{k}={summary[k]}")
            msg = ", ".join(headline or
                            [f"{k}={v}" for k, v in list(summary.items())[:4]])
            self.settings.set_benchmark_active(False, f"Saved {path}\n{msg}")
            try:
                self.settings.refresh_runs()
            except Exception:
                pass
            self.tray.showMessage(
                APP_NAME, f"Benchmark saved\n{os.path.basename(path)}\n{msg}",
                QSystemTrayIcon.MessageIcon.Information, 6000,
            )
        else:
            app_hint = str(self.last_values.get("app", "")) if hasattr(self, "last_values") else ""
            app_hint = app_hint.replace(".exe", "")
            self.fps.begin_capture()
            path = self.recorder.start(app_hint)
            self.settings.set_benchmark_active(True, f"Recording to {path}")
            self.tray.showMessage(
                APP_NAME, "Benchmark recording started",
                QSystemTrayIcon.MessageIcon.Information, 3000,
            )

    # ------------------------------------------------------------ limiter
    def _limit_exe(self, target: str) -> str | None:
        """Which executable the limit applies to (None = RTSS Global).

        Deliberately NOT the current foreground window: clicking Apply puts
        focus on this settings window, so using the foreground would target
        pythonw.exe and silently write a useless profile. The last seen game
        is remembered instead.
        """
        if target == "global":
            return None
        exe = getattr(self, "last_game_exe", "") or ""
        if not exe:
            fg_exe = (getattr(self.last_foreground, "exe", "") or "").lower()
            if fg_exe and fg_exe not in focus.NON_GAMES:
                exe = fg_exe
        if not exe:
            app = self.last_values.get("app") if hasattr(self, "last_values") else None
            exe = str(app) if app else ""
        return exe or None

    def apply_fps_limit(self, target: str, fps: int) -> None:
        exe = self._limit_exe(target)
        if target == "game" and not exe:
            self.settings.set_limiter_status(
                "No game is focused, so there is no per-game profile to write. "
                "Focus the game first, or apply to the Global profile."
            )
            return
        st = self.limiter.set_limit(exe, fps)
        text = self._limiter_text(st)
        # RTSS gives a per-game profile priority over Global, so a Global
        # limit silently does nothing for a game that already has its own.
        if target == "global" and self.last_game_exe:
            own = self.limiter.profile_path(self.last_game_exe)
            if own and os.path.exists(own):
                own_limit = self.limiter.read_limit(self.last_game_exe)
                text += (
                    f"    NOTE: {self.last_game_exe} has its own RTSS profile "
                    f"(limit {own_limit if own_limit > 0 else 'unlimited'}), "
                    f"which overrides Global. Apply to the game instead."
                )
        self.settings.set_limiter_status(text, st.limit)
        self.tray.showMessage(
            APP_NAME, st.message or "Limit updated",
            QSystemTrayIcon.MessageIcon.Information, 4000,
        )

    def refresh_limiter(self) -> None:
        target = "game"
        try:
            target = self.settings.limit_target.currentData()
        except Exception:
            pass
        exe = self._limit_exe(target)
        st = self.limiter.status(exe)
        self.settings.set_limiter_status(self._limiter_text(st), st.limit)
        vendor = limiter_mod.gpu_vendor(self.sensors.gpu_name)
        panel = limiter_mod.driver_panel_path(vendor)
        self.settings.set_driver_hint(
            limiter_mod.DRIVER_HINTS.get(vendor, "")
            + ("" if panel else "\n\nThe control panel was not found on this PC.")
        )

    def _save_state(self, **changes: Any) -> None:
        """Merge into state.json rather than replacing it, so saving the
        active profile does not discard the theme and vice versa."""
        state = config.load_state()
        state.update(changes)
        config.save_state(state)

    def on_theme_changed(self, name: str) -> None:
        self._save_state(theme=name)

    def _update_tray(self, values: dict[str, Any]) -> None:
        """Show the live figure in the tray icon itself.

        Redrawn only when the displayed number changes: repainting a pixmap
        and handing it to the shell twice a second regardless would be waste
        for no visible difference.
        """
        fps = values.get("fps")
        gpu = values.get("gpu_load")
        if fps:
            text, tip = f"{fps:.0f}", f"{APP_NAME} - {fps:.0f} FPS"
            colour = "#3ddc84"
        elif gpu is not None:
            text, tip = f"{gpu:.0f}", f"{APP_NAME} - GPU {gpu:.0f}% (no game)"
            colour = "#7ed0ff"
        else:
            text, tip, colour = "", f"{APP_NAME} - starting", ""

        self.tray.setToolTip(tip)
        if not self.app_settings.get("tray_shows_value", True):
            if self._tray_text != "__logo__":
                self._tray_text = "__logo__"
                self.tray.setIcon(app_icon())
            return
        if text != self._tray_text:
            self._tray_text = text
            self.tray.setIcon(number_icon(text, colour) if text else app_icon())

    def _on_error_logged(self, summary: str) -> None:
        if self._error_notified:
            return
        self._error_notified = True
        try:
            self.tray.showMessage(
                APP_NAME,
                f"Something went wrong and was written to the log.\n{summary}",
                QSystemTrayIcon.MessageIcon.Warning, 7000,
            )
        except Exception:
            pass

    # ------------------------------------------------------------ updates
    def check_for_updates(self, manual: bool = False) -> None:
        """Look for a newer release without blocking the UI.

        Network work happens on a worker thread; the result is handed back
        through a queued signal so the widgets are only touched on the GUI
        thread.
        """
        if manual:
            self.settings.set_update_status("Checking...")

        def work() -> None:
            try:
                rel = updates.check()
            except Exception:
                rel = None
            self._update_result.emit(rel, manual)

        threading.Thread(target=work, daemon=True,
                         name="fpsmon-update-check").start()

    def _on_update_result(self, rel, manual: bool) -> None:
        if rel is None:
            if manual:
                self.settings.set_update_status(
                    f"You are on the latest version ({__version__}), or the "
                    f"check could not reach GitHub."
                )
            return
        msg = f"Version {rel.version} is available (you have {__version__})."
        self.settings.set_update_status(
            f'{msg} <a href="{rel.url}">Open the release page</a>'
        )
        self.tray.showMessage(
            APP_NAME, msg + "\nSee Settings for the link.",
            QSystemTrayIcon.MessageIcon.Information, 8000,
        )

    def _open_logs(self) -> None:
        try:
            os.makedirs(config.LOG_DIR, exist_ok=True)
            os.startfile(config.LOG_DIR)  # noqa: S606
        except Exception:
            pass

    def on_gpu_selected(self, index) -> None:
        self.sensors.set_gpu(index)
        self._save_state(gpu_index=index)
        self.settings.set_status(self.status_text())

    def on_shortcut_requested(self, create: bool) -> None:
        ok, msg = shortcuts.create() if create else shortcuts.remove()
        self.settings.set_shortcut_status(f"{shortcuts.status()}\n{msg}")
        self.tray.showMessage(
            APP_NAME, msg,
            QSystemTrayIcon.MessageIcon.Information
            if ok else QSystemTrayIcon.MessageIcon.Warning,
            5000,
        )

    def open_driver_panel(self) -> None:
        vendor = limiter_mod.gpu_vendor(self.sensors.gpu_name)
        ok, msg = limiter_mod.open_driver_panel(vendor)
        self.settings.set_driver_hint(
            f"{limiter_mod.DRIVER_HINTS.get(vendor, '')}\n\n{msg}"
        )

    def _limiter_text(self, st) -> str:
        if not st.available:
            return (
                "RivaTuner Statistics Server was not found. It is optional - "
                "use your GPU driver's own frame limiter below instead."
            )
        bits = ["RTSS running" if st.running else "RTSS is NOT running"]
        bits.append(f"profile: {st.profile or 'Global'}")
        bits.append("limit: " + (f"{st.limit} FPS" if st.limit else "unlimited"))
        if not st.elevated:
            bits.append("NOT elevated - RTSS profiles cannot be saved")
        text = "  |  ".join(bits)
        if st.message:
            text += f"\n{st.message}"
        for n in getattr(st, "notes", []):
            text += f"\n• {n}"
        return text

    def switch_profile(self, name: str) -> None:
        self.profile_name = name
        self.profile = config.load_profile(name)
        self.overlay.apply_profile(self.profile)
        self.overlay.setVisible(bool(self.profile.get("visible", True)))
        self.settings.load_from_profile(self.profile)
        self._sync_retention()
        self._refresh_profiles_menu()
        self._save_state(active_profile=name)
        self.settings.set_status(f"Profile '{name}' loaded.  " + self.status_text())

    def cycle_profile(self) -> None:
        names = config.list_profiles()
        if not names:
            return
        try:
            i = names.index(self.profile_name)
        except ValueError:
            i = -1
        self.switch_profile(names[(i + 1) % len(names)])

    def on_profile_changed(self, profile: dict[str, Any]) -> None:
        self.profile = profile
        self.overlay.apply_profile(profile)
        self._sync_retention()

    def on_app_settings_changed(self, app: dict[str, Any]) -> None:
        """App-wide settings changed: these apply regardless of profile."""
        self.app_settings = app
        self.timer.setInterval(int(float(app["update_interval"]) * 1000))
        self.sensors.interval = float(app["update_interval"])
        self.register_hotkeys()

    # ------------------------------------------------------------ hotkeys
    def register_hotkeys(self) -> None:
        a = self.app_settings
        self.hotkeys.apply({
            "toggle": a.get("hotkey_toggle", ""),
            "benchmark": a.get("hotkey_benchmark", ""),
            "settings": a.get("hotkey_settings", ""),
            "profile": a.get("hotkey_cycle_profile", ""),
        })

    # ------------------------------------------------------------ main loop
    def tick(self) -> None:
        try:
            values: dict[str, Any] = self.sensors.read()
            values.update(self.fps.read())
            self.last_values = values

            # The sensor backend opens on its own thread, so the hardware list
            # is not known at startup; fill the picker in once it arrives.
            if self.sensors.ready and not self._hardware_published:
                self._hardware_published = True
                saved = config.load_state().get("gpu_index")
                if saved is not None:
                    self.sensors.set_gpu(saved)
                self.settings.set_hardware(
                    self.sensors.gpus, self.sensors.gpu_index,
                    self.sensors.has_battery,
                )

            self._apply_visibility_and_anchor(values)
            self.overlay.set_values(values)

            if self.recorder.active:
                self.recorder.sample(values)

            if self.settings.isVisible():
                self.settings.set_status(self.status_text())

            self._update_tray(values)
        except Exception as exc:
            # printing was pointless: a packaged build has no console
            errors.report("update loop", exc)

    # ------------------------------------------------------------ shutdown
    def quit(self) -> None:
        try:
            self.profile["visible"] = self.overlay.isVisible()
            config.save_profile(self.profile)
            self._save_state(
                active_profile=self.profile_name,
                settings_geometry=self.settings.geometry_dict(),
            )
        except Exception:
            pass
        if self.recorder.active:
            self.recorder.stop()
        self.fps.stop()
        self.sensors.stop()
        self.hotkeys.stop()
        self.overlay.close_hooks()
        self.tray.hide()
        self.qapp.quit()


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    errors.install()
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setApplicationName(APP_NAME)
    # Give Windows an explicit AppUserModelID, otherwise the taskbar groups us
    # under python.exe and shows the Python icon instead of ours.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "FPSMonitor.Overlay.1"
        )
    except Exception:
        pass
    qapp.setWindowIcon(app_icon())

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.warning(None, APP_NAME, "No system tray available.")

    app = FPSMonitorApp(qapp)
    app.show_settings()
    return qapp.exec()
