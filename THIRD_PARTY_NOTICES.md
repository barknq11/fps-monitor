# Third-party notices

FPS Monitor bundles the following components. Their licence terms apply to
those components, not to this project as a whole.

## LibreHardwareMonitorLib  (`vendor/LibreHardwareMonitorLib.dll`)

Mozilla Public License 2.0 — https://github.com/LibreHardwareMonitor/LibreHardwareMonitor

MPL-2.0 is a file-level copyleft licence. The DLL may be redistributed inside a
larger work, **but its source must remain available** and this notice must be
kept. Source: the project URL above, or on request.

## HidSharp  (`vendor/HidSharp.dll`)

Apache License 2.0 — https://www.zer7.com/software/hidsharp

A dependency of LibreHardwareMonitorLib.

## Intel PresentMon  (`vendor/PresentMon.exe`)

MIT License, Copyright (c) Intel Corporation —
https://github.com/GameTechDev/PresentMon

Used unmodified to measure present-to-present frame times.

## RivaTuner Statistics Server

**Not bundled.** FPS Monitor talks to an existing RTSS installation through its
public profile API if one is present. RTSS is by Alexey Nicolaychuk (Unwinder)
and must be obtained from its own distributor. The app is fully functional
without it.

## Python runtime and packages

PySide6 (LGPL-3.0), pythonnet (MIT), psutil (BSD-3-Clause), pywin32 (PSF),
keyboard (MIT), Pillow (HPND).

PySide6 is used under the LGPL: it is dynamically linked and unmodified, and
users are free to replace it with their own build.
