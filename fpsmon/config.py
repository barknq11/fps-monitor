"""
Profile / configuration handling.  Everything the user can customise lives in a
single JSON profile so layouts can be swapped instantly and shared as files.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any

from .paths import data, data_dir

# These are written at runtime, so they live in the data folder rather than
# inside the bundle (which is read-only, and temporary for one-file builds).
ROOT = data_dir()
PROFILE_DIR = data("profiles")
LOG_DIR = data("logs")
STATE_FILE = data("state.json")

# Bumped when metric ids change. Profiles carrying the current schema are
# never migrated, so a preset can deliberately use a metric that an older
# profile would have been migrated away from (e.g. VRAM in MB).
SCHEMA = 2

DEFAULT_PROFILE: dict[str, Any] = {
    "name": "Default",
    "schema": SCHEMA,
    # which metrics are shown, in order
    "metrics": [
        "fps",
        "fps_1low",
        "frametime",
        "gpu_load",
        "gpu_temp",
        "gpu_power",
        "vram_used_gb",
        "cpu_load",
        "cpu_temp",
        "cpu_clock",
        "ram_load",
    ],
    "layout": "rows",          # rows | columns | compact
    "columns": 1,              # used when layout == "columns"
    "show_labels": True,
    "show_units": True,
    "show_group_headers": False,
    "align_values": True,      # pad values so numbers line up
    # appearance
    "font_family": "Consolas",
    "font_size": 16,
    "font_bold": True,
    "text_color": "#00FF66",
    "label_color": "#9FEFC0",
    "warn_color": "#FFC400",
    "crit_color": "#FF3B30",
    "bg_color": "#000000",
    "bg_opacity": 45,          # 0-100, 0 = fully transparent background
    "text_opacity": 100,
    "shadow": True,
    "padding": 10,
    "line_spacing": 2,
    "corner_radius": 8,
    "color_thresholds": True,
    # per-group label colours (MangoHud-style). Ignored unless enabled.
    "use_group_colors": False,
    "group_colors": {
        "FPS": "#EB5B5B",
        "CPU": "#2E97CB",
        "GPU": "#2E9762",
        "VRAM": "#AD64C1",
        "RAM": "#C26693",
        "BATTERY": "#E8B84B",
    },
    # frame-time graph
    "graph_enabled": False,
    "graph_seconds": 4.0,
    "graph_height": 46,
    "graph_width": 0,          # 0 = match the text block width
    "graph_color": "#00FF66",
    "graph_spike_color": "#FF3B30",
    "graph_bg_opacity": 25,
    "graph_max_ms": 0.0,       # 0 = auto-scale
    "graph_guides": True,      # draw 16.7 / 33.3 ms reference lines
    "graph_style": "line",     # line | bars
    "graph_fps": 60,           # graph redraw rate, independent of sensor polling
    "graph_line_width": 2,
    "graph_fill": True,        # gradient fill under the curve
    "graph_trail": True,       # fade the oldest part of the trail out
    # A frame is only called a stutter if it is BOTH this much worse than the
    # median AND at least graph_spike_floor_ms worse in absolute terms. The
    # absolute term is what stops a locked framerate from flagging normal
    # sub-millisecond jitter as stutter.
    "graph_spike_mult": 1.8,
    "graph_spike_floor_ms": 5.0,
    "graph_show_spikes": True,
    "graph_title": "",          # caption above the graph, e.g. "Frametime"
    "graph_scale_pos": "left",  # left | right | none
    # RTSS-style value/unit typography
    "separate_units": False,    # draw the unit after the value, not glued on
    "unit_size_pct": 70,        # unit font size relative to the value font
    # placement
    "position": "top_left",    # top_left|top_right|bottom_left|bottom_right|custom
    "margin_x": 20,
    "margin_y": 20,
    "custom_x": 40,
    "custom_y": 40,
    "monitor": 0,
    "click_through": True,
    "locked": True,            # when False the overlay can be dragged
    # behaviour
    "update_interval": 0.5,
    "only_in_game": False,     # legacy; superseded by visibility_mode
    # always        -> overlay is always shown
    # game_running  -> whenever a game is running with a visible window, even
    #                  if you are working on another monitor (default)
    # game          -> only while the game actually has focus
    # rendering     -> whenever anything is presenting frames
    "visibility_mode": "game_running",
    # follow the focused game's window when it is not fullscreen
    "anchor_to_window": True,
    "check_updates": True,     # ask GitHub for a newer release at startup
    # show the live figure in the tray icon instead of the logo
    "tray_shows_value": True,
    # Executables that should switch to this profile automatically, e.g.
    # ["cs2.exe"]. First match wins; profiles with no entries never
    # auto-activate.
    "auto_for": [],
    "extra_non_games": [],     # user additions to the non-game list
    "extra_games": [],         # force these executables to count as games
    "visible": True,
    # hotkeys
    "hotkey_toggle": "ctrl+alt+f",
    "hotkey_benchmark": "ctrl+alt+b",
    "hotkey_settings": "ctrl+alt+s",
    "hotkey_cycle_profile": "ctrl+alt+p",
}

# ---------------------------------------------------------------------------
# Settings that belong to the application, not to a look.
#
# These used to live inside every profile, which meant a profile switching
# automatically when a game started silently changed the user's hotkeys. A
# profile should describe how the overlay looks; how the app behaves is a
# separate thing that must stay put.
# ---------------------------------------------------------------------------
APP_KEYS = (
    "hotkey_toggle",
    "hotkey_benchmark",
    "hotkey_settings",
    "hotkey_cycle_profile",
    "check_updates",
    "tray_shows_value",
    "visibility_mode",
    "extra_games",
    "extra_non_games",
    "update_interval",
)

APP_DEFAULTS: dict[str, Any] = {
    "hotkey_toggle": "ctrl+alt+f",
    "hotkey_benchmark": "ctrl+alt+b",
    "hotkey_settings": "ctrl+alt+s",
    "hotkey_cycle_profile": "ctrl+alt+p",
    "check_updates": True,
    "tray_shows_value": True,
    "visibility_mode": "game_running",
    "extra_games": [],
    "extra_non_games": [],
    "update_interval": 0.5,
}


def load_app_settings() -> dict[str, Any]:
    """App-wide settings, with a one-time lift out of the active profile.

    Users upgrading from a version that stored these per profile keep the
    hotkeys they had configured rather than silently reverting to defaults.
    """
    state = load_state()
    app = copy.deepcopy(APP_DEFAULTS)
    stored = state.get("app")
    if isinstance(stored, dict):
        app.update({k: v for k, v in stored.items() if k in APP_DEFAULTS})
        return app

    name = state.get("active_profile", "Default")
    try:
        with open(profile_path(name), encoding="utf-8") as fh:
            old = json.load(fh)
        for key in APP_KEYS:
            if key in old:
                app[key] = old[key]
    except Exception:
        pass
    save_app_settings(app)
    return app


def save_app_settings(app: dict[str, Any]) -> None:
    state = load_state()
    state["app"] = {k: app.get(k, APP_DEFAULTS[k]) for k in APP_DEFAULTS}
    save_state(state)


PRESETS: dict[str, dict[str, Any]] = {
    "Minimal FPS": {
        "metrics": ["fps"],
        "font_size": 28,
        "show_labels": False,
        "bg_opacity": 0,
        "text_color": "#00FF66",
        "position": "top_left",
    },
    "Afterburner style": {
        "metrics": [
            "fps", "frametime", "gpu_load", "gpu_temp", "gpu_clock",
            "vram_used_gb", "cpu_load", "cpu_temp", "cpu_clock", "ram_used",
        ],
        "font_family": "Consolas",
        "font_size": 15,
        "show_labels": True,
        "show_units": True,
        "bg_opacity": 0,
        "text_color": "#F2F2F2",
        "label_color": "#7ED0FF",
        "shadow": True,
        "position": "top_left",
    },
    "Full telemetry": {
        "metrics": [
            "fps", "fps_1low", "fps_01low", "frametime",
            "gpu_load", "gpu_temp", "gpu_hotspot", "gpu_clock", "gpu_mem_clock",
            "gpu_power", "gpu_fan_rpm", "vram_used_gb", "vram_pct",
            "cpu_load", "cpu_load_max", "cpu_temp", "cpu_clock", "cpu_power",
            "ram_load", "ram_used",
        ],
        "font_size": 13,
        "layout": "columns",
        "columns": 2,
        "show_group_headers": True,
        "bg_opacity": 60,
        "position": "top_right",
    },
    "MangoHud": {
        # Mirrors MangoHud's default look: dark translucent panel, white
        # values, per-group coloured labels, frame-time graph underneath.
        "metrics": [
            "gpu_load", "gpu_temp", "gpu_clock", "gpu_power",
            "cpu_load", "cpu_temp", "cpu_clock",
            "vram_used_gb", "ram_used",
            "fps", "frametime",
        ],
        "font_family": "Segoe UI",
        "font_size": 15,
        "font_bold": True,
        "show_labels": True,
        "show_units": True,
        "show_group_headers": False,
        "align_values": True,
        "text_color": "#FFFFFF",
        "label_color": "#FFFFFF",
        "bg_color": "#020202",
        "bg_opacity": 50,
        "corner_radius": 0,
        "padding": 8,
        "line_spacing": 1,
        "shadow": False,
        "color_thresholds": False,
        "use_group_colors": True,
        "group_colors": {
            "FPS": "#EB5B5B",
            "CPU": "#2E97CB",
            "GPU": "#2E9762",
            "VRAM": "#AD64C1",
            "RAM": "#C26693",
            "BATTERY": "#E8B84B",
        },
        "graph_enabled": True,
        "graph_seconds": 4.0,
        "graph_height": 44,
        "graph_color": "#00FF00",
        "graph_spike_color": "#EB5B5B",
        "graph_bg_opacity": 0,
        "graph_guides": True,
        "position": "top_left",
    },
    "RTSS Afterburner": {
        # Mirrors the RivaTuner on-screen display: coloured labels, orange
        # right-aligned values with small units, and a bare hairline frametime
        # graph on a fixed 16.7ms (60 FPS) scale.
        "metrics": [
            "gpu_temp", "gpu_load", "vram_used",
            "cpu_temp", "cpu_load", "ram_used",
            "fps", "fps_1low", "fps_01low",
        ],
        "font_family": "Consolas",
        "font_size": 16,
        "font_bold": True,
        "show_labels": True,
        "show_units": True,
        "align_values": True,
        "separate_units": True,
        "unit_size_pct": 65,
        "text_color": "#F5A623",       # RTSS orange values
        "label_color": "#E8E8E8",
        "bg_color": "#000000",
        "bg_opacity": 0,
        "shadow": True,
        "padding": 8,
        "line_spacing": 2,
        "corner_radius": 0,
        "color_thresholds": False,
        "use_group_colors": True,
        "group_colors": {
            "FPS": "#E8E8E8",
            "CPU": "#4FC3F7",
            "GPU": "#7CDB5A",
            "VRAM": "#7CDB5A",
            "RAM": "#4FC3F7",
        },
        "graph_enabled": True,
        "graph_seconds": 6.0,
        "graph_height": 40,
        "graph_max_ms": 16.7,          # fixed scale, like RTSS
        "graph_color": "#E8E8E8",
        "graph_bg_opacity": 0,
        "graph_guides": False,
        "graph_fill": False,
        "graph_trail": False,
        "graph_line_width": 1,
        "graph_show_spikes": False,
        "graph_title": "Frametime",
        "graph_scale_pos": "right",
        "position": "top_left",
    },
    "Frametime analysis": {
        "metrics": [
            "fps", "fps_1low", "fps_01low", "frametime", "frametime_med",
            "frametime_jitter", "stutter_pct", "frametime_max",
            "gpu_load", "cpu_load_max",
        ],
        "font_size": 14,
        "bg_opacity": 65,
        "graph_enabled": True,
        "graph_seconds": 6.0,
        "graph_height": 70,
        "graph_guides": True,
        "position": "top_right",
    },
    "Benchmark bar": {
        "metrics": ["fps", "fps_1low", "fps_01low", "frametime_max", "gpu_load", "cpu_load"],
        "layout": "compact",
        "font_size": 16,
        "bg_opacity": 70,
        "position": "top_left",
    },
}


# Metric ids renamed between versions: old id -> new id.
MIGRATIONS: dict[str, str] = {
    "vram_used": "vram_used_gb",
}


def _migrate(profile: dict[str, Any], stored_schema: int) -> dict[str, Any]:
    if stored_schema >= SCHEMA:
        return profile          # already current: leave the metric list alone
    out: list[str] = []
    for mid in profile.get("metrics", []):
        mid = MIGRATIONS.get(mid, mid)
        if mid not in out:
            out.append(mid)
    profile["metrics"] = out
    profile["schema"] = SCHEMA
    return profile


def _ensure_dirs() -> None:
    os.makedirs(PROFILE_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)


def new_profile(name: str = "Default", base: dict[str, Any] | None = None) -> dict[str, Any]:
    p = copy.deepcopy(DEFAULT_PROFILE)
    if base:
        p.update(copy.deepcopy(base))
    p["name"] = name
    return p


def profile_path(name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in " -_").strip() or "profile"
    return os.path.join(PROFILE_DIR, f"{safe}.json")


def list_profiles() -> list[str]:
    _ensure_dirs()
    names = []
    for f in sorted(os.listdir(PROFILE_DIR)):
        if f.lower().endswith(".json"):
            names.append(os.path.splitext(f)[0])
    return names


def save_profile(profile: dict[str, Any]) -> str:
    """Write a profile, leaving out anything that is an app-wide setting.

    Keeping hotkeys out of the file is what stops a profile switch from
    changing them.
    """
    _ensure_dirs()
    path = profile_path(profile.get("name", "Default"))
    body = {k: v for k, v in profile.items() if k not in APP_KEYS}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=2)
    return path


def load_profile(name: str) -> dict[str, Any]:
    path = profile_path(name)
    if not os.path.exists(path):
        return new_profile(name)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return new_profile(name)
    merged = copy.deepcopy(DEFAULT_PROFILE)
    merged.update(data)
    # Keep the name the user typed. The filename is a sanitised version of it,
    # so overwriting name with the filename would silently rename profiles
    # containing punctuation (e.g. "new +++" -> "new").
    if not str(data.get("name", "")).strip():
        merged["name"] = name
    return _migrate(merged, int(data.get("schema", 0)))


def bootstrap() -> None:
    """Create the default + preset profiles, and add any new presets that
    shipped in a later version without touching the user's own profiles."""
    _ensure_dirs()
    existing = set(list_profiles())
    if not existing:
        save_profile(new_profile("Default"))
    for name, patch in PRESETS.items():
        if not os.path.exists(profile_path(name)):
            save_profile(new_profile(name, patch))


def profile_for_executable(exe: str) -> str | None:
    """Which saved profile claims this game, if any.

    Scanning the profile files rather than keeping an index means a profile
    copied in by hand is picked up without any extra bookkeeping.
    """
    if not exe:
        return None
    want = os.path.basename(exe).lower()
    for name in list_profiles():
        try:
            with open(profile_path(name), encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        for pattern in data.get("auto_for") or []:
            if str(pattern).strip().lower() == want:
                return name
    return None


def restore_presets() -> list[str]:
    """Re-create the built-in profiles, overwriting edited copies.

    Profiles the user created are untouched: only names that appear in
    PRESETS (plus Default) are rewritten.
    """
    _ensure_dirs()
    done = []
    for name, patch in {"Default": {}, **PRESETS}.items():
        save_profile(new_profile(name, patch or None))
        done.append(name)
    return done


def load_state() -> dict[str, Any]:
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
    except Exception:
        pass
