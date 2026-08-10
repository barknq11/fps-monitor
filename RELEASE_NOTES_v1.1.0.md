## New

**Benchmark results page** — past runs are now listed in the app with their
numbers, and you can select two to compare them side by side. The change column
is coloured by whether it's actually an improvement.

**Per-game profiles** — a profile can claim executables (Profiles → *Use this
profile automatically*). When that game starts the overlay switches to it, and
when the game closes it hands back to whatever you had selected.

**Live overlay preview** — the Appearance and Graph pages show a working
overlay with a running frame-time graph, so you can see colour, font and layout
changes without alt-tabbing into a game.

**FPS in the tray icon** — the current frame rate is drawn into the tray icon
itself, falling back to GPU load when no game is running. Can be turned off.

**Hotkey capture** — click a hotkey and press the combination instead of typing
`ctrl+alt+f` into a text box. Esc cancels, Backspace clears, and binding two
actions to the same keys now warns instead of one of them silently not working.

**Search box for metrics** — filters the list as you type and hides groups with
no matches.

**Update check** — optionally asks GitHub whether a newer release exists. It
never downloads anything, sends nothing about your machine, and can be switched
off in Settings → Behaviour.

**Multi-GPU selector** — choose which GPU to report on machines with more than
one, such as laptops with integrated and discrete graphics. Previously it used
whichever the sensor library listed first, which on a laptop is often the idle
one.

**Battery metrics** — charge, time remaining and mains status, for laptops.

**Reset options** — reset a single profile to defaults, or restore the built-in
presets without touching profiles you created.

## Fixed

**The overlay was misplaced on scaled displays.** If your Windows scaling is
above 100% (125%, 150% and so on), the overlay anchored to a windowed game
landed offset from the game window — 75px across and 50px down at 125%. Windows
reports window positions in real pixels while Qt places things in scaled ones,
and the two weren't being converted. Fullscreen games were unaffected.

**Benchmark 1% and 0.1% lows were wrong.** They were calculated from the
on-screen sample stream rather than from individual frames, which averaged the
stutter away. On a test run the reported 1% low was 101 FPS where the true
figure was 21.9. Every frame of a run is now captured and the lows use the
standard definition — the mean frame rate of the slowest 1% / 0.1% of frames,
matching what CapFrameX and Afterburner report.

⚠️ **This means benchmark numbers from earlier versions were optimistic and
should not be compared against numbers from this one.** Runs recorded before
this release show no lows at all, since the frame data wasn't kept.

**Crashes were silent.** The app is a windowed program with no console, so
error output went nowhere. Problems are now written to `logs\error.log` — including
failures on background threads — with a one-time tray notice. If something goes
wrong, that file is what to attach to a bug report.

**Leftover PresentMon processes.** If the app was killed rather than closed, a
PresentMon process could survive and hold its trace session open, which made FPS
show `--` on the next launch. `Fix FPS (clear stuck session).bat` now clears
those processes as well as the sessions.

**Settings window size and position** are remembered, and ignored if the monitor
they were on is no longer connected.

## Notes

- Windows will ask for Administrator. This is required to measure frame times
  (PresentMon opens a trace session) and to read CPU temperature. Everything
  else works without it.
- SmartScreen may warn about an unsigned app — **More info → Run anyway**, or
  verify the download against the SHA-256 below.
- Multi-GPU and battery support could not be tested on real hardware (the
  development machine has one GPU and no battery). If either misbehaves, please
  open an issue.
- Settings live next to the exe, so upgrading means extracting over the old
  folder or copying `profiles\` and `state.json` across.

**SHA-256** of `FPS-Monitor-v1.1.0-win64.zip`:

```
579D62454A24015F2AF47C9CD42890EC37420DF111468851E245F748E63DECDA
```
