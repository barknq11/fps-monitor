<p align="center">
  <img src="assets/logo.png" width="140" alt="FPS Monitor">
</p>

<h1 align="center">FPS Monitor</h1>

<p align="center">
  A customisable FPS, GPU and CPU overlay for Windows.
</p>

---

Shows your frame rate, hardware sensors and a live frame-time graph on top of
your game. Frame times come from Intel PresentMon and sensors from
LibreHardwareMonitor, so the numbers are measured rather than estimated.

## Features

- **Real frame times** — FPS, frame time, 1% and 0.1% lows, per game.
- **Frame-time graph** — animated, scrolling, with stutter spikes marked.
  A flat line means smooth output; spikes are the hitches an average hides.
- **Hardware sensors** — GPU and CPU load, temperature, clocks, power, fan
  speed, VRAM and RAM. Around 30 metrics, pick whichever you want.
- **Fully customisable** — fonts, colours, opacity, layout, position, and
  saved profiles. Presets included for MangoHud and RivaTuner styles.
- **Follows your game** — appears when a game is running, sits on the game's
  window when it's windowed, and stays out of the way otherwise.
- **Benchmark logging** — record a run to CSV with a hotkey.
- **Optional FPS limiter** — through RivaTuner if you have it, or a shortcut
  to your GPU driver's own limiter if you don't.

## Install

Download the latest zip from [Releases](../../releases), extract it anywhere,
and run `FPS Monitor.exe`.

Nothing else to install. Settings live next to the exe, so deleting the folder
removes it completely.

Windows will ask for Administrator. This is needed to read frame times
(PresentMon opens an ETW trace session) and CPU temperature (a kernel driver).
Everything else works without it.

> Windows SmartScreen may warn about an unsigned app. Click **More info →
> Run anyway**, or verify the download against the SHA-256 published with each
> release.

## Usage

| Hotkey | Action |
|---|---|
| `Ctrl+Alt+F` | Show / hide the overlay |
| `Ctrl+Alt+B` | Start / stop benchmark recording |
| `Ctrl+Alt+S` | Open settings |
| `Ctrl+Alt+P` | Next profile |

All four are configurable. The tray icon has the same actions plus a profile
switcher.

Settings → Behaviour → **Add to Start Menu** makes the app findable from
Windows Search.

### A note on fullscreen

The overlay is a normal always-on-top window, so it appears over
**borderless** and **windowed** games — which is how most games run. It cannot
draw inside a game using **exclusive fullscreen**; no external window can,
without injecting code into the game. Switch the game to borderless if you
need the overlay there.

## FPS limiter

Limiting frame rate requires code inside the game's own render loop, so this
app does not do it directly — injecting into games is how anti-cheat bans
happen. Two options instead, both optional:

- **RivaTuner Statistics Server**, if installed. Settings → FPS limiter sets
  the cap through RTSS's own profile API and it applies immediately.
- **Your GPU driver.** AMD Software → Gaming → Max FPS, or NVIDIA Control
  Panel → Manage 3D settings → Max Frame Rate. No extra software at all.

## Running from source

```
pip install -r requirements.txt
python run.py
```

Python 3.11+ on Windows. `FPS Monitor.bat` launches it without a console.

Tests:

```
python tests\run_all.py
```

## Building

```
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

Produces `dist\FPS Monitor\`, a zip, and a SHA-256 file. It's a one-folder
build rather than one-file, which keeps startup fast and avoids some antivirus
false positives.

## Built with

[Intel PresentMon](https://github.com/GameTechDev/PresentMon) for frame times,
[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)
for sensors, and [PySide6](https://doc.qt.io/qtforpython-6/) for the interface.
See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Licence

MIT — see [LICENSE](LICENSE).
