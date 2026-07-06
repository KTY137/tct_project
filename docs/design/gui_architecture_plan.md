# GUI architecture plan — settings revamp & anti-God-object guardrails

*Author: Adam, 2026-07-06. Triggered by user feedback: "device manager and
settings window need a good revamp — too much on one page, disconnects not
monitored"; plus "think about a GUI overhaul so tct_gui does not become a God
object".*

## 1. What was shipped today (2026-07-06)

- **Disconnect monitoring** (the "falsely showing connected" bug):
  - `devices/base.py: BaseDevice.is_alive()` — liveness contract. Default
    trusts the connected flag; drivers with a cheap probe override it and
    flip `_connected = False` when the link is dead (fail-safe display).
  - `devices/oscilloscope.py: Oscilloscope.is_alive()` — IEEE 488.2 `*STB?`
    heartbeat, non-blocking io_lock acquire (never contends with a scan),
    1.5 s probe timeout.
  - `controller/device_manager.py: poll_liveness()` — sweep, never raises.
  - `gui/liveness.py: LivenessMonitor` — 3 s background-thread sweep, emits
    `device_lost(name)`; `tct_gui` connects it to the status bus and the
    lights/Device-Manager table repaint from the corrected flags.
  - **Follow-up for Paul**: implement `is_alive()` for GRBL motor (`?` status
    poll), ISEG bias (documented status query only — HV device, needs manual
    citation), waveform generator (`*STB?` if SCPI-compliant), camera
    (PySpin `IsValid`/`DeviceConnected` node). One driver per task, each
    validated on the bench.

- **Settings window split** (Noah, in flight): per-device tabs instead of
  one scrolled column; YAML editor stays as the last tab. No behavior change.

## 2. Device Manager window — next revamp steps (not yet done)

1. **Row detail expansion**: per-device last-error column (driver already
   logs it; surface the string) + "last seen alive" timestamp from the
   liveness sweeps.
2. **Merge entry points**: the toolbar "Connect All" in the main window and
   the Device Manager buttons duplicate logic (`_run_bg` exists in both
   `tct_gui.py` and `device_panel.py`). Extract one `ConnectionController`
   (see §3) that both UIs call.
3. Keep the window one screen — it is a status/actions table, not a config
   editor. Config belongs to the Settings window; don't merge them.

## 3. Keeping `tct_gui.py` from becoming a God object

`tct_gui.py` is at ~870 lines and owns: panel construction, layout, menus,
theme, log docks, status lights, bias strip, scan start/stop glue,
connect/disconnect orchestration, settings/device windows, config reload,
state-machine sync, and shutdown ordering. That is already too many reasons
to change. Guardrails, in priority order:

1. **Composition root only.** `TCTMainWindow` should *instantiate and wire*,
   never *implement*. Anything with logic beyond `x.signal.connect(y.slot)`
   moves out.
2. **Extract `gui/connection_controller.py`** (first, highest value):
   connect-all / disconnect-all / per-device connect, the `_BgTask` thread
   dance, and busy-state signals. Used by both the toolbar and the Device
   Manager window; kills the duplicated `_run_bg` implementations.
3. **Extract `gui/scan_coordinator.py`**: `_start_scan`, `_start_z_focus`,
   `_start_voltage_scan`, `_on_scan_finished/_error`, pause/resume glue —
   one object owning ScanController↔GUI mediation and run-state gating of
   dangerous buttons.
4. **Extract `gui/shutdown.py`** (or a method object): the ordered teardown
   (panel threads → pollers → liveness → bias-safe-off → disconnect) is
   safety-critical and deserves its own tested unit instead of living in
   `closeEvent`/`_teardown_panels`/`_reload_config` in three variations.
5. **Panels stay device-scoped and bus-decoupled** (already good): a panel
   gets its device(s) + config, talks to the app only via `status_bus` and
   its own signals. Never let a panel import another panel.
6. **Threshold rule of thumb**: when `tct_gui.py` needs a new `_on_*`
   handler that contains an `if`, it goes into a coordinator, not the main
   window. Target: `tct_gui.py` < 500 lines after extractions 2–4.

Sequencing suggestion: 2 → 4 → 3, each as its own reviewed patch (Mary),
each keeping the app runnable in simulation between steps.

## 4. Scope stack notes that affect GUI plans

- The bench scope (Tektronix **TBS1052C**, 2 ch) has **no FastFrame**;
  "FastFrame adjustability" applies only to the `tek_fastframe` backend
  (MSO5204B), whose vendored `dustin_scope` package is currently **missing
  from `TCT_app/vendor/`** — that backend cannot run until it is restored.
  The scope panel instead gained scope-side averaging control
  (`ACQuire:MODe/NUMAVg`), which is what this instrument supports.
- The scope panel builds its channel cards from `Oscilloscope.n_channels`
  (config `n_channels` or *IDN? heuristic) — any future multi-scope UI must
  keep deriving UI capacity from the driver, not hardcode CH1–CH4.

## 5. GUI-direction decision (2026-07-06) — combine A + C-first, B in reserve

Verdict after evaluating four options (see the roadmap artifact): **do not
Electron-rewrite**; it would put an IPC boundary through the two crown jewels
(high-rate pyqtgraph waveforms + the QThread/io_lock safety model). Instead:

- **A (Qt Widgets + design system)** is the foundation everywhere — Phase 2.
- **The scan planner is the Phase-3 pilot** for web-grade design, built in ONE
  expressive stack that we then keep. Start with **C (embed the existing React
  planner in a single `QWebEngineView`, bridged via `QWebChannel`)** — reuse,
  not rewrite; it's a non-real-time surface so Chromium latency never touches
  the waveforms. **B (native QML)** is the documented fallback if the embedded-
  web route proves heavy. Converge to A + one; never ship both expressive stacks.

**Environment feasibility (verified 2026-07-06, PySide6 6.11.1 in the venv):**
`QtWebEngineWidgets`, `QtWebChannel`, `QtQml`, `QtQuickWidgets`, and `QtCharts`
all import successfully — so **Option C needs zero new dependencies** and the
Option B fallback is equally available. The C-first planner pilot is buildable
today. (Packaging note for Phase 5: bundling QtWebEngine ships a Chromium
runtime — factor that into the installer size when the pilot is evaluated.)

### Scan routine planner — routine scope (user-confirmed 2026-07-06)

A "routine" the planner composes is an ordered set of stages, each optional:
- **XY(Z) motor raster** — the core spatial TCT map (bounds, step, order).
- **Per-channel bias voltage sweep** — step HV across a range (CCE-vs-V), on a
  chosen `bias_channel` (multi-channel support from M1).
- **Z-focus / laser-alignment step** — focus optimization / alignment as a stage.
- **Per-point acquisition + save** — averages, waveform capture, and the HDF5
  fields written per point (see `SCAN_DATA_FORMAT.md`).
- **Laser / waveform-generator trigger params** — duty cycle, amplitude, and
  frequency as routine parameters (the planner should let these be set/stepped).
Dry-run preview (time estimate, point count, safety pre-checks) before arming.
Save / load / share routines. Built as the C-first pilot (embedded web planner
bridged to Python); the design-system tokens below are the shared visual base.

**Concrete design target (user's own artifact, retrieved 2026-07-06 — copy 1:1).**
Artifact UUID `654ce683-cb79-4072-9620-a98a6caa9d96` ("TCT Scan Routine Planner")
— fetch verbatim via WebFetch when building. It is a **"Recipe Tree"**: a
routine is a nest of parameter loops wrapping measurement actions, drawn as an
indented tree where **each parameter axis owns one signature color** and a
colored left-edge *rail* carries that color down through everything nested in
that loop. Node types:
- **Loop head** — carries the axis identity: mono `LOOP` tag, axis name, the
  swept values as mono chips, and a right-aligned step/point **count** pill, all
  tinted with the axis rail color.
- **Action leaf** — quiet (Move stage, Settle, Acquire DUT/photodiode, Extract,
  Save point) with a mono `meta` note (e.g. "64 avg", "→ HDF5").
- **Guard** — green shield (Preflight, Check leakage current → abort+ramp-down).
- **Danger** — hazard-red left stripe + "⚠ confirm" pill (HV ramp, Move stage,
  homing). Dangerous blocks *always* route through the confirmation gate.
Right rail: a sticky **"Before you run"** panel (Total points, Est. runtime,
Est. data, Stage travel, HV range), a warnings list, and Validate / Dry Run /
**Arm HV** / Start buttons (Start disabled until HV is armed). Plus an axis-color
legend.

Axis-rail palette (to also fold into the design-system tokens so a "bias" control
is amber *everywhere*, "Z" violet, etc.): bias `#C67F14`/dark `#E8A33D`, Z
`#6455C9`/`#8E82EC`, X `#1690A2`/`#36B7C9`, Y `#BB4680`/`#E27AAE`, laser
`#8E4FCE`/`#B482EC`, delay `#2A8C6C`/`#4FBE99`; hazard `#CE3F35`/`#F2635A`. The
artifact ships its own light/dark themes.

**Build approach:** embed the artifact HTML in a `QWebEngineView` for literal
1:1 fidelity (Option C), then make it data-driven — the tree renders from a
routine model bridged over `QWebChannel`, and every dangerous node's confirm gate
+ the "Arm HV / Start" buttons call back into the Python safety-gated controller
(never JS-side hardware). The artifact's own footer names the target
`scan_planner_panel` and even anticipates a native QTreeWidget+QPainter render —
that stays the Option B fallback if the embed proves heavy.
