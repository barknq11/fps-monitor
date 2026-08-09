# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build for FPS Monitor (one-folder).

One-folder rather than one-file on purpose: a one-file build unpacks itself
to a temp directory on every launch, which would add seconds to a startup we
deliberately got down to ~1.1s, and it trips antivirus heuristics more often.
"""

import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.getcwd())

# A console build with no elevation manifest, used to verify the bundle can
# be launched and can find its resources. The real build cannot be started
# without a UAC prompt, which makes automated checking impossible.
SELFTEST = os.environ.get("FPSMON_SELFTEST") == "1"
APP_NAME = "FPS Monitor selftest" if SELFTEST else "FPS Monitor"

# pythonnet and clr_loader carry managed DLLs and a deps.json that must ship
# alongside the app, and their own hidden imports.
datas, binaries, hiddenimports = [], [], []
for pkg in ("pythonnet", "clr_loader"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Our own resources. The tuple is (source, destination-inside-bundle).
datas += [
    (os.path.join(ROOT, "vendor"), "vendor"),
    (os.path.join(ROOT, "assets"), "assets"),
    (os.path.join(ROOT, "THIRD_PARTY_NOTICES.md"), "."),
    (os.path.join(ROOT, "LICENSE"), "."),
]

hiddenimports += [
    "clr", "keyboard", "psutil",
    "win32api", "win32gui", "win32process", "win32con",
]

# Qt modules this app never touches. Dropping them saves well over 100 MB.
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtQuick",
    "PySide6.QtQuick3D", "PySide6.QtQuickWidgets", "PySide6.QtQml",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSerialPort", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtStateMachine", "PySide6.QtSvgWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "tkinter", "unittest", "pydoc", "doctest", "test",
    "matplotlib", "numpy", "pandas", "IPython", "notebook",
]

a = Analysis(
    ["run.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX-packed binaries are a big AV false-positive source
    console=SELFTEST,          # GUI app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows elevates before the process starts, which is required for
    # PresentMon's ETW session and LibreHardwareMonitor's ring0 driver.
    uac_admin=not SELFTEST,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
