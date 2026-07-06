# Session handoff — resume here

*Written 2026-07-06 (Adam). Read this first on a fresh session, then delete/refresh it when the work below is done.*

## TL;DR state

- **All work is committed to the working tree only** (nothing git-committed unless you did so manually). Full test suite was **153 passing** at last check (`cd TCT_app && .venv\Scripts\python.exe -m pytest tests/ -q`).
- We are mid **Milestone 2** of the GUI roadmap (see `docs/design/gui_architecture_plan.md` and the roadmap artifact "TCT Control — GUI Direction & Roadmap").

## ⚠ First actions on resume

Noah's **design-system foundation (M2.1) is now DONE** — `gui/style.py` has
been evolved, reviewed by Mary, and integrated. No recovery needed; the 153 test
suite is passing.

**Next immediate step:** begin **M2.2 — scan routine planner pilot**, the
marquee feature (item 1 in "What's NEXT" below). Noah is ready to build.

## What's DONE (this session)

- **Scope stack fully fixed + live-validated on the bench TBS1052C**: plotting
  (CURVE?-wedge recovery + channel-active precheck), `TRIGger:A:*` tree, HEADer
  OFF, averaging, probe-attenuation/coupling/bandwidth setters, `read_settings`;
  the **YOFF/YZERO positional-preamble bug** (corrupted absolute voltages) fixed
  with a regression test.
- **Disconnect monitoring**: `BaseDevice.is_alive()` + scope `*STB?` heartbeat +
  `DeviceManager.poll_liveness()` + `gui/liveness.py LivenessMonitor`.
- **Wavegen scale/offset root-caused** (it was the scope's 10× probe attenuation,
  not the wavegen — freq is accurate). Added `output_load`/`offset_V` config +
  driver setters + laser-panel controls.
- **Settings window** split into per-device tabs (Noah).
- **Milestone 1 — multi-channel bias + polarity (COMPLETE)**:
  - `BiasChannel` proxy (`devices/bias_channel.py`); channel-aware iseg driver
    (one VISA session, N channels; single-channel path unchanged);
    `DeviceManager.bias_channels` + `refresh_bias_channels()`.
  - iseg **polarity** read/set with HV gating (reversible + output-OFF
    [fail-closed on unknown status] + discharged <0.2%·Vnom + confirm-poll).
  - `gui/multi_bias_panel.py MultiBiasPanel` (per-channel tabs, gated Switch-
    Polarity control shown only on reversible modules, global ALL-OUTPUTS-OFF).
  - Scan configs got optional `bias_channel` (`_resolve_bias`, out-of-range
    refuses to start).
  - Mary reviewed → fixed the MAJOR HV bug (emergency-off must disable output
    even if the ramp raises — fixed in `_do_all_off`, `_do_emergency_off`, and
    scan_controller post-compliance) + 3 regression tests. ARCHITECTURE.md updated.
- **Milestone 2.1 — design-system foundation (COMPLETE)**: `gui/style.py`
  evolved to a token design system: scope-cyan accent (dark `#33c8ff` / light
  `#0d8ba6`); tokens `accent_strong`, `amber`, `good`, `warn`, `crit`;
  spacing/radius/type scales; axis-rail palette (bias/Z/X/Y/laser/delay/hazard)
  + `axis_color(axis,mode)` helper; new `statusChip` + `eyebrow` objectName
  hooks; all 12 legacy objectName hooks preserved; both themes render. Mary
  reviewed → APPROVE-WITH-NITS; 2 nits applied (removed dead `accent_dark`
  palette key; fixed statusChip repaint docstring to unpolish+polish). 2 deferred
  to tech-debt. **153 tests pass**.
- **Crew refinement**: added 3 Haiku agents — **Kiroku** (bookkeeper), **Shiori**
  (librarian/lookup), **Mamoru** (drift watchdog) — plus tiering + a Coffee-Break
  standup protocol in `.claude/AGENT_PROTOCOL.md` and `docs/TECH_DEBT.md`.
- **GUI direction decided**: stay Python/Qt; combine **A (design system) +
  C-first (embed web planner), B (QML) in reserve** → converge to A + one. See
  the roadmap artifact + `docs/design/gui_architecture_plan.md §5`.

## What's NEXT (in order)

1. **M2.2 — scan routine planner pilot** (the marquee feature). Reproduce the
   user's own artifact **1:1**: artifact UUID `654ce683-cb79-4072-9620-a98a6caa9d96`
   ("TCT Scan Routine Planner") — fetch its HTML via WebFetch. It's a **Recipe
   Tree** (nested parameter loops; each axis = one rail color; guard/danger nodes
   with a confirm gate; a sticky "Before you run" panel with Validate/Dry Run/
   Arm HV/Start). Build approach: **embed the HTML in a `QWebEngineView`** (deps
   confirmed present in PySide6 6.11.1 — QtWebEngineWidgets/QtWebChannel/QtQml/
   QtQuickWidgets/QtCharts all import) and drive it via `QWebChannel`; every
   danger confirm + Arm-HV/Start routes into the Python safety-gated controller,
   never JS-side. Full design + axis-rail palette recorded in
   `docs/design/gui_architecture_plan.md §"Scan routine planner"`.
   Routine stages to support: XY(Z) motor raster, per-channel bias sweep,
   z-focus/laser-align, per-point acquisition+save, and laser/wavegen params
   (duty cycle, amplitude, frequency).
   **Integration map (build-ready):**
   - Planner panel registers in `tct_gui.py` `_build_central()` (~L238-317):
     build panel → `_scrollable()` → `self._tabs.addTab(...)`.
   - Safety-gated controller entry points: `ScanController.start(cfg: ScanConfig)`,
     `pause()`, `resume()`, `abort()`, `start_z_focus_scan(cfg, on_point, on_done)`,
     `start_voltage_scan(cfg)`.
   - Recipe shape: `ScanConfig` dataclass (scan_controller.py ~L32-45):
     `x/y_start/stop/step_mm`, `z_mm`, `n_averages`, `settle_time_s`,
     `bias_channel:int|None`.
   - Status back to UI: `gui/status_bus.py` `STATUS.message = Signal(str, str)`.
   - `ScanPanel` signals (scan_panel.py ~L35): `start_requested(ScanConfig)`,
     `abort_requested()`, `pause_requested(bool)`, `z_focus_requested(ZFocusScanConfig)`,
     `vscan_requested(VoltageScanConfig)`.
   - No existing QWebEngineView/QWebChannel in the repo — this is the first;
     all 6 QtWebEngine/QWebChannel/QtQml/QtQuickWidgets/QtCharts modules
     confirmed importable on PySide6 6.11.1.
2. **Fold the axis-rail palette** (bias=amber, Z=violet, X=teal, Y=magenta,
   laser=purple, delay=green) into the design-system tokens so an axis reads the
   same color everywhere (follow-up to Noah after M2.2).

## Open items / tech-debt (see `docs/TECH_DEBT.md`)

- Mary's 3 MINOR M1 findings: disable per-panel controls during global ALL-OFF;
  `_ReadoutPoller`/`_BiasPoller` deleteLater-after-quit leak; dead vscan Start
  button on non-primary bias tabs. (Owner: Noah.)
- **Bench-only (real HV/scope, never run by agents)**: confirm iseg polarity
  relay settle time (`_POL_CONFIRM_BUDGET_S`=0.5 s is a guess) + SCPI token forms
  on the real module; confirm `CH1:PRObe:GAIN?`/`CH1:COUPling?` query forms on
  the TBS1052C.
- `tek_fastframe` backend is non-functional (vendored `dustin_scope` missing);
  motor/bias/camera still use flag-based `is_alive` (only the scope has a probe).

## Key constraints (don't relearn the hard way)

- **PySide6, not PyQt6.** Safety-first: no hardware I/O at import/construct; HV
  ramp / polarity switch / motion / homing / scan-start need explicit confirm;
  agents never drive real HV — simulation + pytest only.
- Bench scope = **Tektronix TBS1052C** (2 ch, no FastFrame). Bench wavegen =
  **Rigol DG4162** (High-Z output; feeds the PDL 800 laser trigger — don't enable
  its output without confirming the laser is safe).
- Run tests from `TCT_app/`: `.venv\Scripts\python.exe -m pytest tests/ -q`.
