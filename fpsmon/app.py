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

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import (
    QAction, QColor, QGuiApplication, QIcon, QPainter, QPixmap,
)
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import (
    bench, config, focus, fps, limiter as limiter_mod, metrics as M, paths,
    sensors,
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


class FPSMonitorApp:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        config.bootstrap()

        state = config.load_state()
        self.profile_name = state.get("active_profile", "Default")
        self.profile = config.load_profile(self.profile_name)

        # Both backends open slowly (LibreHardwareMonitor ~2s, PresentMon spawns
        # a process and clears stale ETW sessions), so neither blocks the window
        # from appearing - they initialise on their own threads.
        self.sensors = sensors.SensorBackend(
            interval=float(self.profile["update_interval"]), defer=True
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

        self.overlay = Overlay(self.profile)
        # The graph pulls its own data at its own frame rate.
        self.overlay.set_series_provider(self.fps.frametime_series)
        self._sync_retention()
        if self.profile.get("visible", True):
            self.overlay.show()

        self.settings = SettingsWindow(self.profile, self.status_text)
        self.settings.changed.connect(self.on_profile_changed)
        self.settings.profile_switched.connect(self.switch_profile)
        self.settings.benchmark_toggled.connect(self.toggle_benchmark)
        self.settings.limit_requested.connect(self.apply_fps_limit)
        self.settings.limit_refresh_requested.connect(self.refresh_limiter)
        self.settings.driver_panel_requested.connect(self.open_driver_panel)
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
        self.timer.start(int(float(self.profile["update_interval"]) * 1000))

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

        mode = p.get("visibility_mode", "game_running")
        if p.get("only_in_game", False) and mode == "always":
            mode = "rendering"          # honour the legacy option

        fg = focus.foreground()
        self.last_foreground = fg
        pids = self.fps.presenting_pids()
        blocked = set(focus.NON_GAMES) | {
            s.lower() for s in p.get("extra_non_games", [])
        }
        allowed = {s.lower() for s in p.get("extra_games", [])}
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
            self.last_game_exe = game_win.exe

        if mode == "always":
            show = True
        elif mode == "rendering":
            show = bool(values.get("fps")) or bool(pids)
        elif mode == "game":
            show = focused_game
        else:                            # "game_running"
            show = game_win is not None

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
            summary = self.recorder.stop()
            path = self.recorder.path or ""
            msg = ", ".join(f"{k}={v}" for k, v in list(summary.items())[:6])
            self.settings.set_benchmark_active(False, f"Saved {path}\n{msg}")
            self.tray.showMessage(
                APP_NAME, f"Benchmark saved\n{os.path.basename(path)}\n{msg}",
                QSystemTrayIcon.MessageIcon.Information, 6000,
            )
        else:
            app_hint = str(self.last_values.get("app", "")) if hasattr(self, "last_values") else ""
            app_hint = app_hint.replace(".exe", "")
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
        self.timer.setInterval(int(float(self.profile["update_interval"]) * 1000))
        self.sensors.interval = float(self.profile["update_interval"])
        self._sync_retention()
        self.register_hotkeys()
        self._refresh_profiles_menu()
        config.save_state({"active_profile": name})
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
        self.timer.setInterval(int(float(profile["update_interval"]) * 1000))
        self.sensors.interval = float(profile["update_interval"])
        self._sync_retention()
        self.register_hotkeys()

    # ------------------------------------------------------------ hotkeys
    def register_hotkeys(self) -> None:
        self.hotkeys.apply({
            "toggle": self.profile.get("hotkey_toggle", ""),
            "benchmark": self.profile.get("hotkey_benchmark", ""),
            "settings": self.profile.get("hotkey_settings", ""),
            "profile": self.profile.get("hotkey_cycle_profile", ""),
        })

    # ------------------------------------------------------------ main loop
    def tick(self) -> None:
        try:
            values: dict[str, Any] = self.sensors.read()
            values.update(self.fps.read())
            self.last_values = values

            self._apply_visibility_and_anchor(values)
            self.overlay.set_values(values)

            if self.recorder.active:
                self.recorder.sample(values)

            if self.settings.isVisible():
                self.settings.set_status(self.status_text())

            f = values.get("fps")
            self.tray.setToolTip(
                f"{APP_NAME} - {f:.0f} FPS" if f else
                f"{APP_NAME} - GPU {values.get('gpu_load', 0):.0f}%"
            )
        except Exception:
            traceback.print_exc()

    # ------------------------------------------------------------ shutdown
    def quit(self) -> None:
        try:
            self.profile["visible"] = self.overlay.isVisible()
            config.save_profile(self.profile)
            config.save_state({"active_profile": self.profile_name})
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
