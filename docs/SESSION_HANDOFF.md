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
- **Phase 2.2 step 1 (planner pure modules)** — `scan_plan_validator.py` +
  `plan_compiler.py` + `plan_estimate.py`, 51 tests. Mary CHANGES-REQUIRED →
  4/4 findings fixed + independently probe-verified. Suite **218 passed**.
- **Phase 3 kickoff** — `config_validator` now covers all 11 `devices.yaml`
  sections (14 tests). Mary-approved.
- **P2.2 steps 2+3 (executor & planner, complete):** `controller/danger_gate.py`
  (DangerAction/DangerGate protocol, AutoConfirmGate/DenyAllGate/QtDangerGate);
  `ScanController.arm_hv()` latch, `start_plan()`/`_run_plan()` with shared
  fail-safe helpers, motor.stop() in all finallys, HV re-assertion on resume.
  Fault-injection suite (`test_fault_injection.py` + `test_fault_injection_legacy.py`)
  proves safety under disconnect/HV-trip/motor-fault/abort. `gui/planner_panel.py`
  v2 (Recipe-Tree, drag-drop palette, movable nodes, right-click ops, 20-deep undo,
  live estimate); `gui/qt_danger_gate.py` (worker→GUI confirm bridge, timeout
  fail-closed); `gui/status_widgets.py` (StatusChip/StatusPill/flash_button).
  `Oscilloscope.n_channels` modular (config-settable, *IDN?-clamped, validator
  checks 1..8); `ScopePanel.rebuild_channels()` at connect. Design-system tokens
  rolled across all panels. **4-commit checkpoint on experimental-wip. Suite 293
  passed.**
- **GUI improvement: panel_kit composition layer + batch-1 rollout (2026-07-07):**
  New `gui/panel_kit.py` (Card: title/subtitle, header, per-card `set_rail(axis, mode)` with
  dynamic railAxis; composition primitives panel_header, eyebrow_title, section_header,
  readout_cell, form_row, axis_rail_css; QSS hooks). Pilot scope_panel + laser_panel rebuilt
  on panel_kit (Mary APPROVE-WITH-NITS; nits fixed: rail scoping, docstrings; scope fixed
  pre-existing chip-overflow). Batch-1 rollout: motor, bias (4/6 boxes; 2 CHECKABLE stay native),
  multi_bias, intensity, monitor, device_panel (hardcoded colors → tokens, +11 tests).
  QtDangerGate stray-dialog BUG fixed (+3 regression tests); honest plan-run terminal status;
  native-planner decision (embed shelved). **9 of 12 core panels on the new level; suite 321 passed.
  Commits: e422ae7, 8c3d9fb, 6b970ac (rollout), 5193968 (gate fix), 5572d35 (native decision).
  12 unpushed commits remain on experimental-wip.**

## What's NEXT (in order)

**(a) USER DECISIONS pending:** Confirm three design choices before batch-2 rollout:
  1. **Axis semantics**: drift/rise/CFD naming — should CFD always green=delay (earliest timing) or is there a toggle/context?
  2. **scan_panel fate**: style as-is (dual-channel raster) or fold into planner-driven workflow?
  3. **Batch-2 panel order**: camera vs. settings window — each should own its session; confirm priority.

**(b) Batch-2 rollout** (after decisions above): remaining 3 core panels (scan_panel, camera_panel, analysis_panel) + consistency pass (legacy panel checks in style.py/QSS). Target suite 330+.

**(c) Push unpushed commits**: 12 commits remain on experimental-wip; push to main when user confirms decisions.

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

**Note:** `docs/ROADMAP.md` is the strategic map (phases, north star, ordering rationale); this handoff is the tactical resume point (immediate next steps, what broke, where we left the code).

## Key constraints (don't relearn the hard way)

- **PySide6, not PyQt6.** Safety-first: no hardware I/O at import/construct; HV
  ramp / polarity switch / motion / homing / scan-start need explicit confirm;
  agents never drive real HV — simulation + pytest only.
- Bench scope = **Tektronix TBS1052C** (2 ch, no FastFrame). Bench wavegen =
  **Rigol DG4162** (High-Z output; feeds the PDL 800 laser trigger — don't enable
  its output without confirming the laser is safe).
- Run tests from `TCT_app/`: `.venv\Scripts\python.exe -m pytest tests/ -q`.
