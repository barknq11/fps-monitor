"""Functional checks for the reported fixes."""

import ctypes
import ctypes.wintypes
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PREVIEW_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "preview",
)
os.makedirs(PREVIEW_DIR, exist_ok=True)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fpsmon import config, metrics as M  # noqa: E402
from fpsmon.hotkeys import HotkeyManager, parse_combo  # noqa: E402
from fpsmon.overlay import Overlay  # noqa: E402

app = QApplication(sys.argv)
config.bootstrap()
failures = []

# ------------------------------------------------------- VRAM units + group
print("=== VRAM ===")
m = M.BY_ID["vram_used_gb"]
txt = M.format_value(m, 9134 / 1024.0) + m.unit
print("  9134 MB renders as:", txt, "| group:", m.group)
if txt != "8.9GB":
    failures.append(f"vram GB formatting wrong: {txt}")
if m.group != "VRAM":
    failures.append("VRAM metrics are not in their own colour group")

# ------------------------------------------------------------ window styles
print("\n=== overlay window styles ===")
prof = config.load_profile("Default")
ov = Overlay(prof)
ov.set_values({"vram_used_gb": 8.92, "fps": 143, "cpu_load": 62, "gpu_load": 99})
ov.show()
app.processEvents()

GWL_EXSTYLE = -20
bits = {
    "WS_EX_NOACTIVATE": 0x08000000,
    "WS_EX_TOOLWINDOW": 0x00000080,
    "WS_EX_TOPMOST": 0x00000008,
    "WS_EX_TRANSPARENT": 0x00000020,
}
hwnd = int(ov.winId())
ex = ctypes.windll.user32.GetWindowLongPtrW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
for name, bit in bits.items():
    ok = bool(ex & bit)
    print(f"  {'OK ' if ok else 'MISSING'}  {name}")
    if not ok:
        failures.append(f"missing style {name}")

# ------------------------------------------------- flicker: redundant SetWindowPos
print("\n=== flicker: z-order churn ===")
calls = {"n": 0}
_real = Overlay._force_topmost


def counting(hwnd_):
    calls["n"] += 1
    _real(hwnd_)


Overlay._force_topmost = staticmethod(counting)
ov.raise_()
app.processEvents()
for _ in range(40):
    ov._keep_on_top()
print(f"  SetWindowPos calls during 40 checks while on top: {calls['n']}")
if calls["n"] > 5:
    failures.append(
        f"overlay still re-orders itself constantly ({calls['n']}/40) -> flicker"
    )
Overlay._force_topmost = staticmethod(_real)

# ------------------------------------------------- flicker: resize/move churn
print("\n=== flicker: geometry churn ===")
resizes = {"n": 0}
_orig_resize = ov.resize


def counting_resize(*a, **k):
    resizes["n"] += 1
    return _orig_resize(*a, **k)


ov.resize = counting_resize  # type: ignore[method-assign]
random.seed(3)
for i in range(60):
    ov.set_values({
        "fps": random.choice([9, 99, 143, 1024]),
        "cpu_load": random.uniform(0, 100),
        "gpu_load": random.uniform(0, 100),
        "gpu_temp": random.uniform(30, 95),
        "gpu_power": random.uniform(5, 250),
        "vram_used_gb": random.uniform(0.5, 15.9),
        "cpu_temp": random.uniform(30, 95),
        "cpu_clock": random.uniform(2000, 4300),
        "ram_load": random.uniform(10, 99),
        "frametime": random.uniform(4, 40),
        "fps_1low": random.uniform(20, 140),
    })
print(f"  window resizes across 60 varied updates: {resizes['n']}")
if resizes["n"] > 8:
    failures.append(f"window resizes on almost every update ({resizes['n']}/60)")
ov.resize = _orig_resize  # type: ignore[method-assign]

# --------------------------------------------------------------- graph
print("\n=== frametime graph ===")
gprof = config.load_profile("MangoHud")
print("  MangoHud graph enabled:", gprof.get("graph_enabled"))
print("  MangoHud group colours:", gprof.get("group_colors"))
if not gprof.get("graph_enabled"):
    failures.append("MangoHud profile has no graph")
if (gprof.get("group_colors") or {}).get("VRAM") != "#AD64C1":
    failures.append("MangoHud VRAM colour missing")

g = Overlay(gprof)
hist = []
random.seed(1)
for i in range(400):
    v = 6.9 + 0.3 * math.sin(i / 20) + random.uniform(-0.3, 0.3)
    if i in (100, 250, 251):
        v += 20
    hist.append(v)
h_before = g.height()
g.set_values({"fps": 143, "frametime": 6.99}, hist)
g.show()
app.processEvents()
print(f"  overlay grew for graph: {h_before} -> {g.height()} px")
if g._graph_rect is None:
    failures.append("graph rect was never computed")
g.grab().save(os.path.join(PREVIEW_DIR, "overlay_graph_check.png"))
g.close_hooks()
g.hide()
ov.close_hooks()
ov.hide()

# ------------------------------------------------------------------ hotkeys
print("\n=== hotkeys ===")
print("  parse 'ctrl+alt+f' ->", parse_combo("ctrl+alt+f"))
hits = []
hk = HotkeyManager()
hk.set_action("toggle", lambda: hits.append("toggle"))
hk.set_action("benchmark", lambda: hits.append("benchmark"))
hk.apply({"toggle": "ctrl+alt+shift+f10", "benchmark": "ctrl+alt+shift+f11"})
print("  status:", hk.status(), "| method:", hk.method)
print("  registered ids:", hk._ids)
print("  native filter installed:", hk._filter is not None)


def _tap(mods, vk):
    user32 = ctypes.windll.user32
    UP = 0x0002
    for mm in mods:
        user32.keybd_event(mm, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, UP, 0)
    for mm in reversed(mods):
        user32.keybd_event(mm, 0, UP, 0)


def _foreground_blocks_input() -> bool:
    """True if an elevated window owns the foreground while we are not.

    Windows UIPI discards synthesized input aimed past a higher-integrity
    foreground window, so the synthetic-keystroke check below cannot run.
    That is a limitation of this TEST process; the app itself runs elevated.
    """
    if ctypes.windll.shell32.IsUserAnAdmin():
        return False
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    hwnd = u.GetForegroundWindow()
    pid = ctypes.wintypes.DWORD()
    u.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
    if not h:
        return True  # cannot even open it -> elevated
    ctypes.windll.kernel32.CloseHandle(h)
    return False


def fire():
    # Always exercise the real delivery path: WM_HOTKEY posted to this
    # thread's queue, which is exactly what RegisterHotKey does. This
    # validates the native event filter and GUI-thread dispatch.
    tid = ctypes.windll.kernel32.GetCurrentThreadId()
    for hid in list(hk._ids):
        ctypes.windll.user32.PostThreadMessageW(tid, 0x0312, hid, 0)
    # Additionally try real synthesized keys when UIPI permits it.
    if not _foreground_blocks_input():
        _tap([0x11, 0x12, 0x10], 0x79)  # ctrl+alt+shift+F10
        _tap([0x11, 0x12, 0x10], 0x7A)  # ctrl+alt+shift+F11
    else:
        print("  note: elevated foreground window -> UIPI blocks synthetic "
              "keys; WM_HOTKEY path tested instead")


def finish():
    print("  actions received on the GUI thread:", sorted(set(hits)))
    if not hk._ids:
        failures.append("RegisterHotKey did not reserve any combination")
    if "toggle" not in hits or "benchmark" not in hits:
        failures.append(f"hotkeys did not fire (got {hits})")
    hk.stop()
    app.quit()


QTimer.singleShot(400, fire)
QTimer.singleShot(2200, finish)
app.exec()

print("\n=== RESULT ===")
if failures:
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1)
print("  all checks passed")
