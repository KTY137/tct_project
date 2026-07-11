# TCT App — Architecture Bookkeep

**This is the crew's shared architecture reference.** Owner: `docs-dev` (Samantha).
Every agent consults this file before working on an unfamiliar module. Whenever a
change adds/removes/renames a module, class, signal, config key, or data group,
the change is not finished until this file is updated (delegate to Samantha).
Entries must describe what the code *actually does* — verify against the source,
never document intentions. Add a line to the **Changelog section at the bottom** (see **Why decisions** below) for every
update.

**Why decisions live in `docs/DECISIONS.md`:** The changelog below tracks *structural changes* to the codebase (new files, module renames, API additions). For the *rationale* behind technology choices and design decisions (why PySide6 not PyQt6, why static IPs not DHCP, etc.), consult `docs/DECISIONS.md` — a lightweight ADR table that links each decision to its supporting research and affected code.

App root: `TCT_app/` — all paths below are relative to it.

## Big picture

```
configs/devices.yaml ──► controller/config_validator ──► controller/device_manager
                                                              │ owns all device instances
        GUI (PySide6, main thread)                            ▼
  tct_gui.TCTMainWindow ◄── signals/callbacks ──► controller/scan_controller (worker thread)
  │  gui/* panels (abstract interfaces only)         │ move→settle→image→trigger→acquire
  │  gui/status_bus, _QtLogHandler log bridge        │ →analyse→save→update map
  ▼                                                  ▼
controller/state_machine (AppState)            data/hdf5_writer ──► runs/run_XXXXX/waveforms.h5
                                               data/influx_writer (slow control → InfluxDB)
```

Core design rules (verified in code):
- **Three-layer invariant** (2026-07-11): **UI (layer 1) → backend (layer 2) → drivers (layer 3)**. Layers point **down only**; **no compute or blocking I/O executes on the GUI thread**. Layer 1 (GUI: `gui/*`, new QML) renders state and forwards intent; may depend on backend view-model interfaces (properties/signals/slots) only, never physics/estimation inline. Layer 2 (backend: `controller/`, `analysis/`, `data/`) owns all compute and state orchestration; long work runs in workers (QThread/QThreadPool) and returns via queued signals. Layer 3 (drivers: `devices/*`) owns hardware I/O; simulation backends mandatory. Enforcement: static `import-linter` layer contracts + dynamic GUI-thread watchdog test (`tests/test_gui_thread_watchdog.py`). Allowed edge: gui→analysis for offline analysis (4 consumers: analysis_panel, calibration_panel, scope_panel, scan_map_view) — governed by watchdog, not import rules. Detail: `docs/research/qml_hybrid_architecture.md` §9.
- GUI panels and scan logic reference **only abstract device interfaces**
  (`*_base.py`); concrete drivers are chosen by `device_manager` from
  `devices.yaml`. Hardware swaps need no UI/scan-code changes.
- Every device family has a `simulated` backend; the whole app runs with zero
  hardware.
- `devices/base.py:BaseDevice` gives every driver a `simulation` flag, a
  `connected` property, and an **`io_lock` (re-entrant)** that serialises hardware
  I/O — GUI pollers and the scan thread share one VISA/serial session per device.
- `BaseDevice.is_alive()` is a cheap link probe swept every 3 s by
  `gui/liveness.LivenessMonitor` (via `controller/device_manager.poll_liveness()`)
  so a yanked cable or powered-off instrument flips `connected` to `False`
  within seconds instead of staying green forever. Default trusts the
  `connected` flag; overrides must verify the physical link, set
  `_connected = False` on failure, use a **non-blocking** `io_lock` acquire
  (skip the probe if the device is mid-conversation), and never change
  instrument state.

## Entry point

- `main.py` — logging setup, `QApplication`, applies saved theme
  (`QSettings("TCT", "TCTSetup")`), builds
  `TCTMainWindow(config_path="configs/devices.yaml")`.
- `tct_gui.py` — `TCTMainWindow`: assembles all panels into detachable tabs
  (`gui/detachable_tabs.DetachableTabWidget`), builds a `gui/scan_coordinator.ScanCoordinator`
  (the composition root for scan run-control logic, moved out of `TCTMainWindow`
  proper in S2a), wires panel signals to coordinator methods, owns the `StateMachine`.
  `_QtLogHandler`/`_LogBridge` forward log records onto the main thread via a Qt signal
  (thread-safe in-app log view). Also owns a `gui.liveness.LivenessMonitor` on its own
  `QThread` (created in `_build_central`, stopped in `_teardown_panels`), which sweeps
  `DeviceManager.poll_liveness()` every 3 s and emits `device_lost(name)` on a
  connected→lost transition; `_on_device_lost` turns that into a status-bus
  warning even when no device window is open. S2c updates: "Scan" tab replaced
  by "Scan Viewer" (ScanViewerPanel), ScanPanel and ScanMapWindow retired,
  motor `set_as_scan_start` → planner `set_position_from_motor`, new
  `_publish_last_run_path()` and `_open_in_analysis(path)` slots for Analysis handoff.

## controller/

- `state_machine.py` — `AppState` enum and validated transitions:
  `DISCONNECTED → CONNECTED → HOMED → CONFIGURED → READY → RUNNING →
  {PAUSED, FINISHED, ERROR, ABORTED}`; `PAUSED → {RUNNING, ABORTED}`; terminal
  states fall back to `CONFIGURED`. **Every state may reset to `DISCONNECTED`**
  (universal recovery, incl. crashed scans). Invalid transitions raise
  `ValueError`; observers register callbacks.
- `scan_controller.py` — `ScanController` drives the scan loop
  (move → settle → image → trigger → acquire → analyse → save → update map) on a
  worker thread (`threading`). Scan types as dataclass configs:
  - `ScanConfig` — XY raster (start/stop/step per axis, fixed Z, `n_averages`,
    `settle_time_s`).
  - `ZFocusScanConfig` — focal calibration; `mode="amplitude"` (legacy, max DUT
    amplitude) or `mode="edge_scan"` (recommended: max spatial gradient |dQ/dx|
    across a metal/silicon edge per Z step).
  - `VoltageScanConfig` — IV / bias sweeps.

  Both `ScanConfig` and `VoltageScanConfig` carry an optional `bias_channel:
  int | None` field (default `None` = the primary channel, i.e. unchanged
  historic behaviour). `ScanController._resolve_bias(cfg)` resolves it to a
  `devices.bias_channel.BiasChannel` **before** any state change or hardware
  action: `None` returns `self._dev.bias_supply` (the primary proxy); an
  explicit `int` indexes `self._dev.bias_channels`. A non-integer or
  out-of-range index raises `ValueError` and the scan refuses to start —
  channel selection is never allowed to silently fall back to another
  channel. `start()` and `start_voltage_scan()` both call `_resolve_bias`
  up front and pass the resolved `BiasChannel` into the scan thread
  (`_run`/`_run_voltage_scan`). P2.2 step 2 added plan executor:
  `arm_hv()` latch, `start_plan()`/`_run_plan()` entry points, shared helpers
  (`_acquire_core`/`_check_compliance`/`_bias_failsafe`/`_reassert_bias`/
  `_command_move`/`_motor_stop_safe`), fail-safe hardening (motor.stop() in
  all five run-path finallys, isolated try-blocks in vscan finally, refused
  starts clear `_hv_armed`, trailing ManualPause finishes cleanly, `resume()`
  no-op unless PAUSED, HV re-assertion on resume). S2c: `start_plan()`
  now emits `scan_started` on success (plan runs drive the viewer cockpit);
  `start()` / `start_voltage_scan()` retained for API stability but have no
  GUI callers since ScanPanel retirement. Read-only property `last_run_path: Path | None`
  (thread-safe, set after HDF5 write completes) allows the GUI to link to the just-written run file.
- `danger_gate.py` — danger action protocol and authorization gates. `DangerAction`
  dataclass (action kind, `requires_confirm: bool`); `DangerGate` protocol (async
  request/confirm workflow). `AutoConfirmGate` (auto-approves in simulation);
  `DenyAllGate` (always refuses); `QtDangerGate` (worker→GUI bridge, timeout
  fail-closed). Used by executor step 2 to gate HV ramps and moves.
- `scan_plan.py` — `ScanPlan` tree dataclass: fail-closed nested parameter loops
  (Axis, Bias, Delay loops), action leaves (Move, Settle, Acquire, Extract, Save),
  guard nodes, and danger nodes. YAML round-trip via `load()`/`save()`;
  `iter_leaf_contexts()` yields leaf scan points. `LeafMeta` carries effective
  `n_averages`/`settle_s` (action params > nearest enclosing loop > defaults);
  `iter_leaf_contexts_ex()` yields `(coords, action, meta)` tuples. `BiasStep` 
  (compiled from Bias loop) carries optional `ramp_step_V` / `ramp_delay_s` fields
  (step size + per-step delay during ramp; sourced from device config defaults,
  loop overrides, or per-action overrides; unifies the e4control + native driver 
  ramp-shaping parameters).
- `scan_plan_validator.py` — pure fail-closed plan pre-flight:
  `validate_plan(plan, PlanLimits) -> list[PlanIssue]`. Checks stage limits, HV
  range, `max_points` cap, and (fail-closed) requires any bias-driving plan to
  declare `safety.require_hv_confirmation: True`; never raises (`(plan.safety or {})`
  guard).
- `plan_compiler.py` — pure tree → ordered steps compiler:
  `compile_plan(plan) -> list[Step]`. Contracts: `MoveStep.x/y/z_mm: float|None`
  where **None = "do not command this axis"** (undriven axes never fabricated as
  0.0); MoveStep emitted only when a driven axis changes; `BiasStep` only on bias
  change (dedup); step order per leaf = Bias → Move → settle `WaitStep` → action;
  `MoveStep`/`BiasStep` carry `requires_confirm` + `danger_kind` ("move"/"hv_ramp").
  No execution/threads — executor lands in step 2.
- `plan_estimate.py` — plan estimation: `estimate_plan(plan, Timing, Sizing) ->
  PlanEstimate` (points, runtime, data bytes, per-axis travel, HV range). Walks
  compiled plan output; settle comes ONLY from emitted WaitSteps (`Timing` no
  longer has `settle_s` — plan is the single source of truth). S1 (2026-07-08):
  now models per-`BiasStep` ramp shaping via `ceil(|dV|/step)*delay` for accurate
  ramp-duration ETA (sourced from device config defaults, loop overrides, or
  per-action overrides in `BiasStep.ramp_step_V` / `ramp_delay_s` fields).
- `device_manager.py` — owns all device instances; single
  connect/disconnect/status interface for the GUI. Backend registries map
  `devices.yaml` keys to classes: `MOTOR_BACKENDS` (`pi`, `grbl`, `simulated`),
  `INTENSITY_BACKENDS` (`scope_channel`, `simulated`), etc. `_APP_ROOT` anchors
  relative output paths to `TCT_app/` regardless of launch cwd. New driver =
  new registry entry. Reads `oscilloscope.n_channels` from `devices.yaml` and
  passes it to `Oscilloscope`. `poll_liveness()` calls `BaseDevice.is_alive()`
  on every `named_devices()` entry and never raises — the sole client is
  `gui.liveness.LivenessMonitor`.
  `self.bias_supply` is a `devices.bias_channel.BiasChannel` bound to the
  **primary** channel (index from the bias driver's `channel:` config key;
  `0` by default) — a stable object, so `named_devices()`, liveness, and the
  scan controller's default (`bias_channel=None`) path are unchanged.
  `self.bias_channels: list[BiasChannel]` holds one `BiasChannel` per HV
  channel the driver reports; `refresh_bias_channels()` queries the shared
  driver's `channel_count()` (needs a live link; returns `1` in simulation
  or on error, never raises) and rebuilds the list, reusing the existing
  primary-channel proxy object at its index. `connect_all()` calls
  `refresh_bias_channels()` itself, right after the bias driver connects
  (before the intensity monitor and slow-control channels), so
  `bias_channels` reflects the real channel count by the time it returns.
- `slow_control_manager.py` — environment/slow-control channels; feeds
  `data/influx_writer` and the HDF5 `slow_control` group.
- `config_validator.py` — validates `devices.yaml` before use. `_KNOWN_KEYS`
  checks all 11 sections: motor_stage, intensity_monitor, oscilloscope, bias_supply,
  waveform_generator, camera, laser, slow_control, influx, output, charge_calibration
  (unknown keys → WARNING; silent typos never escape). Phase 3: oscilloscope
  `n_channels` must be a whole number in range 1..8, else validation fails (clamped
  to *IDN?-detected capability at runtime).
- `yaml_persist.py` — comment-preserving persistence for `configs/devices.yaml`.
  Walks YAML *source text* with an indentation stack and rewrites only the value
  half of lines whose key path matches a caller-supplied update; every other line
  (comments, blank lines, unrelated sections) passes through byte-for-byte unchanged.
  Public API: `merge_yaml_text(text, updates) -> str`, `update_yaml_file(path, updates)`.
  Fixes the historical round-trip bug where `yaml.safe_load → yaml.dump` silently
  stripped all comments. Used by settings windows (scope_panel, settings_window).
- `repeatability.py` — stage repeatability measurement logic.

## devices/ (one family = base + backends)

| Family | Base | Backends |
|---|---|---|
| Motor stage | `motor_base.py` (`MotorStageBase`, `SoftwareLimits`, `limits_user_frame()`) | `motor_grbl.py`, `motor_pi.py`, `motor_simulated.py` (+ `printer_presets.py`) |
| Bias supply (HV) | `bias_supply_base.py` (`BiasSupplyBase`) | `bias_supply_iseg.py`, `bias_supply_keithley.py`, `bias_supply_e4control.py`, `bias_supply_simulated.py` |
| Bias channel (proxy) | — | `bias_channel.py` (`BiasChannel` — binds one `(driver, channel_index)` pair; see below) |
| Oscilloscope | — | `oscilloscope.py` (VISA), `oscilloscope_drs4.py` (PSI DRS4 eval board), `oscilloscope_tek_fastframe.py` (Tektronix MSO5204B FastFrame — currently non-functional, see Known constraints) |
| Intensity monitor | `intensity_base.py` | `intensity_scope_ch.py`, `intensity_simulated.py` |
| Slow control | `slow_control_base.py` | `slow_control_simulated.py` |
| Waveform generator | — | `waveform_generator.py` (VISA Rigol DG4162); `is_alive()` (*STB? heartbeat), `_teardown_session()` (close/null VISA + RM) |
| Other | `camera_blackfly.py` (FLIR PySpin, `is_alive()` via PySpin `IsValid`, `_release_hw()` balanced PySpin acquire/release), `laser_manual.py` (metadata-only laser record) | |

All inherit `base.py:BaseDevice` (`DeviceError`, `io_lock`, `simulation`,
`is_alive()`, abstract `connect()`/`disconnect()`).

**Motor frame contract (2026-07-11):**
- `MotorStageBase.limits_user_frame() -> SoftwareLimits | None` (motor_base.py:210–234):
  Soft limits expressed in the *same* frame `get_position()` / `move_to()` speak to
  the rest of the app. Single source of truth for the planner + validator. A backend
  whose user frame IS its machine frame (SimulatedMotorStage, PIMotorStage) returns
  `self.limits` unchanged. A backend that maintains a software display offset
  (GRBLMotorStage, whose `zero_position` shifts the origin without touching the
  controller) overrides to translate the machine-frame `self.limits` into the
  current user frame. Callers rebuild `PlanLimits` from THIS (not `self.limits`)
  and refresh whenever the offset changes (after home / zero).
- `gui/motor_panel.py:MotorPanel.origin_changed` (Signal, motor_panel.py:124): emitted
  after home or zero-position succeeds. Wired to `TCTMainWindow._refresh_plan_limits()`
  (tct_gui.py:472) so the planner's user-frame soft-limit gate tracks the new origin
  and never validates against stale bounds — fixes the "Zero Here → planner rejects
  the plan on soft limits" bug (2f91e00, 2026-07-11).

**Multi-channel bias + polarity (verified in code):**
- `bias_channel.py:BiasChannel` binds one `(driver, channel_index)` pair and
  presents the full `BiasSupplyBase`-shaped API the GUI and scan controller
  already use — `set_voltage`/`set_compliance`/`output_on`/`output_off`/
  `read`/`ramp_to`/`get_polarity`/`set_polarity`/`supports_polarity_switch`/
  `channel_count`/`is_alive`, plus `setpoint_V`/`compliance_A`/
  `voltage_range_V`/`connected`/`.channel`/`.driver` — by delegating every
  call to the shared driver's channel-aware `*_ch` methods for `self.channel`.
  It performs **no hardware I/O of its own and keeps no independent state**;
  every safety gate (compliance-before-output, discharge-before-polarity,
  voltage-range clamp, confirm-after-switch) lives in the driver, so a
  primary-channel proxy is byte-for-byte equivalent to using the bare driver
  directly. `channel_count()` on a `BiasChannel` always returns `1` (it is a
  single-channel view); `connect()`/`disconnect()` delegate to the shared
  driver, but only the primary-channel proxy is registered in
  `DeviceManager.named_devices()`/`connect_all()`, so the driver's
  transport connects/disconnects exactly once even though several proxies
  share it. One VISA/serial session therefore serves all `N` channels.
- `bias_supply_base.py:BiasSupplyBase` adds an optional polarity/multi-channel
  API with safe single-channel defaults so every existing backend keeps
  working unchanged: `supports_polarity_switch()` (default `False`),
  `get_polarity()` (default `None`), `set_polarity(polarity)` (default
  raises `DeviceError` — fixed-polarity backends refuse), `channel_count()`
  (default `1`). A parallel channel-aware `*_ch` method set
  (`set_voltage_ch`/`set_compliance_ch`/`output_on_ch`/`output_off_ch`/
  `read_ch`/`ramp_to_ch`/`get_polarity_ch`/`set_polarity_ch`/
  `supports_polarity_switch_ch`/`setpoint_V_ch`/`compliance_A_ch`/
  `output_is_on_ch`) takes an explicit channel index; the base defaults
  ignore the index and delegate to the zero-arg methods, so a single-channel
  backend needs no changes. `_ramp_channel()` is a generic per-channel ramp
  (mirrors `ramp_to()`) that genuine multi-channel backends can reuse by
  overriding only the `*_ch` primitives. `normalize_polarity()` normalises
  `'p'/'pos'/'positive'/'+'` and `'n'/'neg'/'negative'/'-'` (case-insensitive)
  to iseg's canonical `'p'`/`'n'`, raising `DeviceError` on anything else so a
  typo can never reach an HV supply. `set_polarity` is a **DANGEROUS
  action** (throws an HV relay) — the docstring requires the same gating as
  an HV ramp: caller/GUI confirmation, plus the concrete implementation must
  verify OFF-and-discharged and refuse rather than force the relay.
- `bias_supply_iseg.py:IsegBiasSupply` is channel-aware: one VISA/serial
  session serves every HV channel on the module. Per-channel state
  (`setpoint_V`/`output_on`/`compliance_A`) lives in `self._ch_state[channel]`
  (created on first use); the base class's scalar state
  (`_setpoint_V`/`_output_on`/`_compliance_A`) is a property view of the
  **primary** channel (`self._ch`, from `devices.yaml: bias_supply.channel`),
  so the pre-existing single-channel path (`ramp_to`, `disconnect`,
  `setpoint_V`, …) is byte-for-byte unchanged. The zero-arg
  `set_voltage`/`set_compliance`/`output_on`/`output_off`/`read` are thin
  wrappers bound to `self._ch`. `channel_count()` queries
  `:READ:MODULE:CHANNELNUMBER?` (falls back to `1` in simulation, with no
  session, or on any error). `disconnect()` also ramps-to-0/switches-off any
  *other* channel this driver has touched (`self._ch_state` keys other than
  the primary), so a multi-channel session never leaves a secondary channel
  biased on teardown; single-channel use never populates those entries, so
  this is a no-op there.
  `set_polarity_ch(channel, polarity)` is gated per
  `docs/research/iseg_polarity_scpi.md` §3 — **verified only against that
  research note plus simulation, not yet on real HV**: (a)
  `supports_polarity_switch_ch()` (`:CONF:OUTP:POL:LIST?` reports both `'p'`
  and `'n'`, read-only, no HV action), (b) output confirmed OFF via both the
  local flag AND the channel status word (`:READ:CHAN:STAT? (@ch)`, bit 3 =
  "Is On") — a status query that fails (e.g. USB-VCP timeout) is treated as
  **unknown, not OFF**, and the switch is refused (fail-closed), (c)
  `|V_meas| < 0.002·voltage_range_V` via `:MEAS:VOLT?` (the discharge
  precondition; `voltage_range_V` must be configured or the switch is
  refused). All three checks and the switch itself run under one `io_lock`
  acquisition so no other thread can enable the output or start a ramp
  mid-gate. On success, `:CONF:OUTP:POL <p|n>,(@ch)` is written and then
  polled back (`:CONF:OUTP:POL?`) for up to `_POL_CONFIRM_BUDGET_S = 0.5 s`
  (`_POL_POLL_INTERVAL_S = 0.05 s`) to confirm the relay actually moved
  before returning; the relay settle time itself is undocumented by iseg, so
  this 0.5 s budget is **UNVERIFIED on real HV** — a confirm timeout raises
  and explicitly does not proceed to ramp.

**Bench fact:** the lab oscilloscope is a Tektronix **TBS1052C** (2 channels,
no FastFrame support), driven by the default `oscilloscope.py` VISA backend
(`devices.yaml: oscilloscope.n_channels: 2`).

`oscilloscope.py` invariants (verified in code):
- Tektronix trigger config (`configure_tct_trigger`) uses the `TRIGger:A:*`
  tree; the old bare `TRIGger:MODE/SOURce/LEVel/SLOPe` forms are rejected as
  "Undefined header" on the TBS1000C family.
- `read_channel()` pre-checks `SELect:CH<x>?` and raises `DeviceError` fast
  when the channel display is off — `CURVE?` on an inactive source times out
  and wedges the scope's output queue instead of failing cleanly.
- `_recover_session()` issues a VISA device-clear (`instr.clear()`) after any
  failed query so one bad reply can't garble the ones that follow.
- `_check_scpi_errors()` drains `*ESR?`/`ALLEv?` after config writes so a
  silently-rejected command is logged instead of vanishing.
- `set_averaging()` (`ACQuire:MODe` / `ACQuire:NUMAVg`) and
  `set_channel_display()` (`SELect:CH<x> ON|OFF`) are public control methods
  backing the scope panel's averaging combo and channel toggles.
- `n_channels` comes from `devices.yaml: oscilloscope.n_channels`, else a
  `*IDN?` heuristic (`tek_channel_count_from_idn` — last digit of the Tek
  model number); `gui/scope_panel.py` builds its channel cards from it.
- `is_alive()` = a `*STB?` heartbeat (see Big picture / `is_alive()` contract).

`waveform_generator.py` (Rigol DG4162) facts:
- `prime_pyvisa() -> bool` (main-thread warm-up helper called early in GUI startup and before the settings scan QThread spins up): primes PyVISA's ctypes DLL loader to avoid access-violation on first import off a background thread (Windows-specific).
- `WaveformGenerator.connect()` queries `:OUTPut{ch}:STATe?` (manual-sourced from DG4000 Programming Manual, returns `ON`/`OFF`) and resolves the `armed` tri-state indicator from unknown → real `True`/`False` (defensive parse: accepts `ON`/`1` → True, `OFF`/`0` → False, case-insensitive, whitespace stripped).
- `is_alive()` = a `*STB?` heartbeat (Status Byte query, non-blocking, fast, never raises; verifies device link; see Big picture / `is_alive()` contract). New post-liveness-round, verified in simulation.
- `_teardown_session()` (called on `disconnect()`) closes and nulls `_instr` VISA instrument session + previously-leaked `_rm` resource manager; idempotent after dirty death (earlier root cause of Kaya's bench freeze bug).
- Optional config fields `level_low_V` / `level_high_V` (unipolar 0→+V trigger path; mutually required, default omitted = bipolar mode). Validated in `config_validator` (both-or-neither, numeric, low < high).

## gui/ (PySide6 — never PyQt6)

**QML-hybrid components (opt-in, 2026-07-11 slice 1, 2a: unified polling):**

- `qml_theme.py` — Theme QML singleton, fed from `style.py` token design system; NOTIFY fires on theme switch.
- `qml_shell.py` — QML-hybrid shell host: `_ShellBridge` (QObject, tab index / live device state), `_TabShelfAdapter` (tab shelf ↔ classic tabs sync), QQuickWidget RHI pinned to OpenGL. Opt-in via `TCT_QML_SHELL=1` env flag; classic shell byte-identical when flag unset. **Slice 2a:** `_ShellBridge.pull()` rides `TCTMainWindow._light_timer.timeout` (1 Hz), no second timer of its own — unified polling cadence.
- `scope_viewmodel.py` — Read-only scope-status mirror for QML binding (rateText stubbed empty; TODO: drive from scope reader cadence).
- `run_state_viewmodel.py` — Read-only run-state facade (2026-07-11 slice 1, commit 713eeae): `RunStateViewModel` exposes current step index, total steps, run-state enum, pause/resume/abort affordances via no-controller-refs `changed` notifier, fed by shared 1 Hz `_light_timer` + coordinator signals. Exposed to QML as `'runState'` context property (only notifies via `changed`, no direct signal binding). Built before `CalibrationPanel` in `_build_central()`. Teardown in viewmodel-release block ensures Qt lifecycle safety.
- `qml/Shell.qml` — QML-hybrid chrome: rail (Devices/Settings/Log/Debug chips + app-state readout, icon buttons compress without Flickable) + pill tab shelf (syncs DetachableTabWidget index).
- **Invariants:** Classic DetachableTabWidget is the sole tab/detach engine—QML shelf is a *view*; pyqtgraph plots are NEVER inside QQuickWidget; style.py remains the single token source (Theme singleton mirrors it); soft-reload (production config reload) releases old QML engine before building new one.

**Core panels & support (all on `panel_kit` Cards):**

Panels: `motor_panel`, `bias_panel`, `multi_bias_panel`, `scope_panel`,
`laser_panel`, `intensity_panel`, `camera_panel`,
`monitor_panel`, `analysis_panel`, `calibration_panel`, `device_panel`
(`DeviceManagerWindow`, `device_state`), `settings_window` (owns a `_VisaRescanWorker` scan + a `_ScanReaper` GUI-thread-affine strong owner of the old background scan worker for deadlock-safe teardown — see VISA-scan deadlock postmortem in `docs/DECISIONS.md`), `planner_panel`
(Recipe-Tree QTreeWidget, editable loop rows, live estimate, validate/dry-run/
arm/start latch chain; v2: drag-drop palette, movable nodes, right-click ops,
20-deep undo; G4: gained `set_focus_z(z_mm)` slot that writes selected STAGE_Z loop's start spinbox, staging-only, wired from ScanViewerPanel's "Use Focus Z" button; 2026-07-11: off-thread estimate via persistent `_EstimateWorker` (QObject on dedicated QThread), streaming `estimate_plan` calls), `scan_viewer_panel` (S2b+S2c+G4: live scan monitor & cockpit —
shared ScanMapView, MetricGrid progress/ETA/point/elapsed, Pause/Abort ActionBar,
Z-focus CheckableCard, EmptyState until first run, "Open in Analysis" handoff;
G4: added best_z_apply_requested(float) signal + "Apply to Planner" button (gated: enabled only after Z-focus completes);
signals out: pause_requested, abort_requested, z_focus_requested, best_z_apply_requested, open_in_analysis_requested;
slots in: set_last_run_path, refresh_theme). **All 12 core panels built on `panel_kit` Cards** (batch-1: motor/bias/multi_bias/intensity/monitor/device, batch-2: scope/laser, batch-3: camera/analysis). Support: `panel_kit.py`
(Card composition: title/subtitle, header, per-card `set_rail(axis, mode)` with
dynamic railAxis property; panel_header, eyebrow_title, section_header,
readout_cell, form_row, axis_rail_css; QSS hooks cardHeader/cardTitle/
cardSubtitle in style.py; cockpit-kit components: FigureCard, MetricTile, MetricGrid, ActionBar, CheckableCard, EmptyState, ReadoutCell); `style.py` gained SIM_PURPLE (#8e44ad) + ERROR_ORANGE (#e67e22) constants (T3 palette expansion), `status_bus.py` (cross-panel status),
`status_widgets.py` (StatusChip, StatusPill, flash_button design-system tokens),
`scan_map_view.py` (S1: shared 2-D scan-map widget — FigureCard + pyqtgraph ImageView,
`analysis.scan_grid`-driven, quantity selector, autoscale colorbar, cursor readout,
live `update_point()` + batch `set_points()`; PNG/CSV export via toolbuttons,
freeze-levels toggle for colorbar min/max lock; embedded by `scan_map_window` and `ScanViewerPanel`), `scan_map_window.py` (live scan map window, re-fed by shared ScanMapView), `scan_coordinator.py` (S2a: `ScanCoordinator` QObject,
extracts scan run-control from `TCTMainWindow`; owns `_ScanBridge`, `ScanController`
handle; dispatches start/abort/pause/z-focus/vscan/arm-hv/start-plan with plan-vs-classic
dual-dispatch; `start_plan` emits `scan_started` on success; signals: `point_done`, `progress`, `scan_started`, `scan_finished`,
`z_focus_pt`, `z_focus_done`, `vscan_point`, `plan_progress`, `plan_error`,
`plan_finished`, `plan_running`, `hv_armed`, `manual_pause`, `warn_dialog`, `error_dialog`,
`status_message`), `stage_view.py` (3D GL stage view),
`scope_measurements.py`, `detachable_tabs.py`, `style.py` (token design system:
scope-cyan accent, tokens for UI states, spacing/radius/type scales, axis-rail
palette, `axis_color()` helper, `statusChip`/`statusPill`/`eyebrow` objectName
hooks), `qt_danger_gate.py` (`QtDangerGate`: worker→GUI confirm bridge, timeout
fail-closed), `liveness.py` (`LivenessMonitor` — background device-liveness
sweep, owned by `TCTMainWindow`, see Big picture and Entry point).
Long-running work never runs on the main thread; log records cross threads via
the `_LogBridge` signal.

`scope_panel.py`'s `_ScopeReader.read_once` now reads each enabled channel
independently and reports per-channel errors, so one dead channel (display
off, timeout) no longer blanks the channels that read fine. Channel-card
toggles drive `SELect:CH<x>` on the instrument, gated on the panel's "Drive
scope" switch. The acquire row's averaging combo drives
`Oscilloscope.set_averaging()` (`ACQuire:NUMAVg`). Phase 3: `rebuild_channels()`
dynamically rebuilds the channel cards from `Oscilloscope.n_channels` at
connect time (modular channel count per oscilloscope backend; DRS4/FastFrame
declare 4, TBS1052C defaults to 2, heuristic from *IDN? as fallback).

`analysis_panel.py` (S1+S2a: gained public `load_run(path: str) -> bool` for
programmatic HDF5 load; `_open_file()` routes through it; analysis plots rebuilt
on `points_to_grid`, CCE via `analysis.cce`; panel built on panel_kit in batch-3
rollout).

`multi_bias_panel.py:MultiBiasPanel` (`QWidget`, replaces the old
single-`BiasPanel` top-level widget in `tct_gui.py`) presents one
`gui/bias_panel.py:BiasPanel` per HV channel inside a `QTabWidget`
(`CH<n>` tabs), built from `DeviceManager.bias_channels`. Constructing it
performs **no hardware I/O** — each tab's `BiasPanel` only polls once its
channel reports `connected`. `rebuild(channels)` is called from
`tct_gui.py` after `connect_all()` (which runs `refresh_bias_channels()`)
to rebuild the tabs from the driver's real channel count; it no-ops when
the channel set is unchanged so a same-shape reconnect keeps the existing
panels (and their plot state). Only the primary channel's tab
(`panels[0]`) owns the bias+waveform scan controls, since the scan
controller is bound to the primary supply by default — its
`vscan_requested` signal is the only one re-emitted through
`MultiBiasPanel.vscan_requested`. A prominent **"⏹ ALL OUTPUTS OFF"**
button above the tabs ramps every *connected* channel to 0 V and disables
its output, off the GUI thread (`_SupplyCallWorker`, mirroring `BiasPanel`'s
pattern); it is fail-safe — it keeps switching off the remaining channels
even if one errors, then reports the aggregated failure via
`gui/status_bus.notify`. `shutdown()` stops the ALL-OFF worker thread and
every per-panel poll thread before the widget is discarded.

`bias_panel.py:BiasPanel` gained a **Polarity** group: a read-only
polarity indicator (`+`/`−`/`—` for unknown) and a **"⇄ Switch Polarity"**
button (`dangerBtn` styling) that is only shown when the bound channel
reports `supports_polarity_switch()` — fixed-polarity channels never see
the control. Switching polarity is treated exactly like an HV ramp: the
button requires an explicit confirmation dialog naming the channel and the
`current → target` polarity, then runs `supply.set_polarity(target)`
off the GUI thread via the existing `_SupplyCallWorker`/`QThread` pattern
(never on the GUI thread — instrument I/O blocks). The panel's own
`_ReadoutPoller` (`QObject`, moved to a dedicated `QThread`, `_POLL_MS =
500`) polls both `read()` and `get_polarity()`/`supports_polarity_switch()`
every 500 ms and touches no hardware until the channel reports `connected`.

## data/

- `hdf5_writer.py` — `HDF5Writer`: incremental single-file writer,
  `runs/run_XXXXX/waveforms.h5`. Group selection via `save_options.SaveOptions`;
  `waveforms` + `positions` mandatory, `timestamp`/`analysis`/`bias`/
  `slow_control`/`camera_frame`/`run_metadata` optional. `/run_info` attrs hold
  scan config, `devices.yaml` snapshot (Influx token redacted), calibration,
  software limits, timestamps. Extensible datasets, gzip, chunk 64.
  **Full contract: `TCT_app/SCAN_DATA_FORMAT.md`** — the
  authoritative data-format doc; keep both in sync.
- `influx_writer.py` — optional slow-control sink to InfluxDB.
- `save_options.py` — which HDF5 groups are written; editable in Settings GUI.

## analysis/

`waveform_analysis.py` (`analyse_waveform`, `WaveformResult` — amplitude, charge,
baseline RMS, drift/rise/CFD/onset times), `charge_calibration.py`
(`ChargeCalibration`), `laser_normalization.py` (`normalise`),
`efield_analysis.py` (`reconstruct_efield`, `compute_cce` — auto-reference
bias-scan CCE, `estimate_depletion_voltage`).

- `scan_grid.py` — `points_to_grid(x_mm, y_mm, values, *, decimals=6) ->
  ScanGridResult`: the one canonical scattered-points → regular 2-D grid
  reconstruction (replaces three near-identical inline implementations that
  used to live in `gui/scan_panel.py`, `gui/scan_map_window.py`,
  `gui/analysis_panel.py`). Grid convention `grid[i, j] <-> (x_mm[i],
  y_mm[j])`; unsampled cells are NaN and counted (`n_missing`), never
  dropped; NaN *values* in the input are counted separately
  (`n_nan_values`); duplicate points at the same rounded coordinate use
  last-value-wins (`n_duplicate_points`), matching the live-view semantics
  every prior renderer already relied on. `grid_extent(result)` derives the
  `(pos, scale)` pair pyqtgraph's `ImageView` wants. Currently wired into
  `gui/analysis_panel.py::_replot_map`; `scan_panel.py` / `scan_map_window.py`
  still have their own copies pending the shared map-widget build (tracked
  in `docs/research/scan_viewer_design_review.md`).
- `cce.py` — `cce_vs_reference(charges_pC, reference_charge_pC, *,
  min_reference_pC=1e-12) -> ndarray`: `|Q| / |Q_ref|` against an
  operator-supplied reference charge (the Analysis panel's "Q_ref (full
  depletion)" spin box), replacing an inline calculation that used to live
  in `gui/analysis_panel.py`. Deliberately a different zero-reference policy
  than `efield_analysis.compute_cce` (epsilon-clamp vs. NaN) — see the
  module docstring for why. Wired into `AnalysisPanel._plot_cce` /
  `_export_cce_csv`.

## configs/ and tests/

- `configs/devices.yaml` — single config source: backend selection per device,
  connection parameters, `output.data_dir`, `output.save` toggles, calibration,
  software limits. Validated by `config_validator`.
- `pytest.ini` — pytest configuration (timeout=60s per test, preventing hangs on
  unresponsive mock transports; faulthandler_timeout=90s because pytest-timeout's killer thread is itself GIL-starved when a worker thread holds the GIL indefinitely — see VISA-scan deadlock postmortem in `docs/DECISIONS.md`).
- `tests/conftest.py` — shared pytest fixtures; T6 (2026-07-10): added autouse fixture that drains Qt's DeferredDelete queue after every test, curing accumulation hang (suite wedged in pyqtgraph grab() past ~450 GUI tests).
- `tests/` — pytest, headless, simulated backends only: state machine, config
  validator, GRBL mock, scope preamble, waveform analysis, bias & calibration.

## Local-only reference material

- `reference/` — local-only reference material, intentionally ignored by Git
  (`Printrun`, `e4control`, Dustin oscilloscope scripts, Spinnaker SDK).
- `lab_assets/` — local-only lab photos and source/manual PDFs, intentionally
  ignored by Git.
- `sources/git_history/` — local recovery bundles for the old nested repos,
  intentionally ignored by Git.
- `TCT_app/devices/bias_supply_e4control.py` can import from a local
  `reference/e4control` checkout at connect time. Keep that dependency optional
  so simulation and tests work without local reference material.

Details: `docs/REFERENCE_MATERIAL.md`.

## Known constraints

- numpy pinned `<2` (PySpin 3.2 wheel, numpy 1.x C-ABI). 64-bit CPython 3.10
  required for real-camera use.
- Real hardware extras not on PyPI: FLIR Spinnaker SDK runtime, PSI DRS4 driver.
- `oscilloscope_tek_fastframe.py` (Tektronix MSO5204B FastFrame backend) is
  currently non-functional: it imports the vendored `dustin_scope` package
  from `TCT_app/vendor/dustin_scope/`, which is absent from this checkout.
  The bench scope is a TBS1052C (2 channels, no FastFrame), which uses the
  default `oscilloscope.py` VISA backend instead — `tek_fastframe` targets a
  different instrument than what's on the bench.

## TODO (Samantha: verify and deepen)

- [ ] Thread inventory: exact threads at runtime (GUI, scan worker, pollers,
      slow-control) and which objects live where.
- [ ] Confirm full backend registry list in device_manager (scope/camera/bias
      registries beyond MOTOR/INTENSITY).

## Maintained Lookup Registries

The following files are autogenerated/maintained registries for fast O(1) lookups:
- `docs/signal_registry.md` — All Qt signals across GUI and controller: name, signature, definition site, connection targets.
- `docs/config_keys.md` — All `devices.yaml` configuration keys by section: name, type, defaults, validator, consumer.

Maintained by Kiroku; drift-checked by Mamoru on every change.

## Changelog

- 2026-07-11 — **VISA-scan deadlock postmortem & worker safety hardening (commits 4d887b4 + 97c07f4).** GIL-vs-Qt-mutex ABBA deadlock: worker GC-refcount reaching zero on non-owning thread → `_ScanReaper` pattern (GUI-thread-affine strong owner prevents GC on background thread). QueuedConnection audit for all cross-thread slots. pytest.ini faulthandler_timeout=90 added (pytest-timeout killer thread GIL-starved). Detailed analysis in `docs/DECISIONS.md`. +2 regression tests (deadlock-free full-suite smoke; worker teardown safe).

- 2026-07-11 — **Codex-lane C1: panel-kit rollout test retitles (57e053a).** Batch1/batch2 test names now use current naming (camera/analysis panels migrated in batch3 on 2026-07-07). No functional change.

- 2026-07-11 — **Planner estimate off-thread (7903ffe).** Last sync `estimate_plan()` call sites (drag delta-preview, ungated `_safe_estimate`) moved to persistent `_EstimateWorker` (QThread). `_CandidatePreview` structural counts for large drag candidates. Watchdog test `tests/test_gui_thread_watchdog.py` full coverage.

- 2026-07-11 — **Plan estimate/compile parity tested (adff735).** NEW `tests/test_plan_parity.py` property tests: compiled plan step count == estimate cost. Bias/move/settle emission-rule parity verified via shared leaf walker.

- 2026-07-11 — **RepeatabilityTester now requires DangerGate (33d1664).** `controller/repeatability.py` gates motion via DangerGate; `gui/calibration_panel.py` passes gate instance. CalibrationPanel builds gate before construction. No danger until user explicitly confirms. Closes BLOCKER.

- 2026-07-11 — **Atomic devices.yaml writes via comment-preserving yaml_persist (d810c55).** NEW `controller/yaml_persist.py`: line-level surgical YAML editor (indentation stack, key-path matching, value replacement only). scope_panel/settings_window route through `merge_yaml_text` / `update_yaml_file` instead of `yaml.safe_load → yaml.dump` round-trip that stripped comments. Bias supply `simulation` key added to validator (legacy support kept).

- 2026-07-11 — **RunStateViewModel read-only facade for QML binding (713eeae).** NEW `gui/run_state_viewmodel.py`: `RunStateViewModel` (no controller refs; 3-layer law). Exposes step index/total, run-state enum via `changed` notifier, fed by shared 1 Hz `_light_timer` + coordinator signals. Exposed to QML as `'runState'` context property. Built before CalibrationPanel; teardown in viewmodel-release block.

- 2026-07-11 — **2f91e00 (fix):** Motor user-frame validation. `motor_base.py` adds `limits_user_frame()` contract (user frame ≠ machine frame for GRBLMotorStage's zero_position offset). `MotorPanel.origin_changed` signal emitted after home/zero; wired to `TCTMainWindow._refresh_plan_limits()` so planner's soft-limit gate tracks the new origin — fixes "Zero Here → plan rejected on stale bounds" bug. +2 integration tests (plan gate after zero).

- 2026-07-11 — **c86e21a (feat/fix):** Bias-supply simulation mode + comment-preserving YAML writes. NEW `controller/yaml_persist.py` (comment-preserving line-level surgical editor; public `merge_yaml_text` / `update_yaml_file` API). scope_panel/settings_window now route through it instead of `yaml.safe_load → yaml.dump` round-trip that stripped all comments. Bias supply `simulation` key added to config_validator known-keys list (backend='simulated' preferred; legacy key supported).

- 2026-07-11 — **4eb7f14 (feat):** Slice 2a unified polling & QML rail composition. `qml_shell.py` `_ShellBridge.pull()` now rides `TCTMainWindow._light_timer.timeout` (1 Hz cadence), no second timer of its own. `qml/Shell.qml` rail compressed without Flickable via icon buttons/overflow menu — content fits in ~1400px viewport.

- 2026-07-11 — **7393c3d (merge):** experimental/qml-hybrid-slice1 → design/cockpit-v5. Merge commit; slice 1 + slice 2a work lands together. NEW `gui/qml_theme.py` (Theme singleton fed from style.py, NOTIFY on switch), `gui/qml_shell.py` (_ShellBridge + _TabShelfAdapter, QQuickWidget chrome), `gui/scope_viewmodel.py` (read-only scope mirror), `gui/qml/Shell.qml` (rail + pill shelf). Opt-in `TCT_QML_SHELL=1`; classic shell unchanged when flag unset. main.py OpenGL RHI pin; tct_gui opt-in branch + hardened soft-reload. NEW test `tests/test_qml_shell.py` (11 tests). Suite 742; Mary APPROVE_WITH_NITS (all nits fixed).

- 2026-07-11 — **QML-hybrid slice 1 landed (experimental/qml-hybrid-slice1 @ 0f90573).** NEW `gui/qml_theme.py` (Theme singleton fed from style.py, NOTIFY on switch), `gui/qml_shell.py` (_ShellBridge + _TabShelfAdapter, QQuickWidget chrome), `gui/scope_viewmodel.py` (read-only scope mirror), `gui/qml/Shell.qml` (rail + pill shelf). Opt-in `TCT_QML_SHELL=1`; classic shell unchanged when flag unset. main.py OpenGL RHI pin; tct_gui opt-in branch + hardened soft-reload. NEW test `tests/test_qml_shell.py` (11 tests: default-classic boot, QML-boot smoke, detach/redock, rail reachability, fail-safe fallback, soft-reload engine cleanup, Theme singleton sync, tab-shelf sync, QML no-hex rule). Suite 742; Mary APPROVE_WITH_NITS (2 RISKs + NIT, all fixed).

- 2026-07-11 — **3-layer-law enforcement + planner estimate off-thread (design/cockpit-v5 @ e85a94c).** planner_panel.py now off-threads estimate via persistent `_EstimateWorker` (QThread); controller/plan_estimate.py streaming ready. NEW `tests/test_gui_thread_watchdog.py` (dynamic enforcement: GUI 10 ms heartbeat + heavy workload, asserts 35 ms max stall; proves old sync path would have failed ~1.31 s) + `tests/test_layer_contracts.py` (static AST import scan: layer rank matrix, UI→backend→drivers down-only, no compute/blocking I/O on GUI thread; catching "wrong layer" violations; dynamic half catches "right layer, wrong thread"). Enforcement detail in `docs/research/qml_hybrid_architecture.md` §9. Suite 731; Mary APPROVE.

- 2026-07-11 — **Architecture decisions: QML hybrid frontend + 3-layer law (ratified).** Two decisions logged in `docs/DECISIONS.md`: (1) **QML hybrid frontend** — QML chrome (QQuickWidget islands) + pyqtgraph for all real-time plots as sibling QWidgets + existing DetachableTabWidget unchanged; full-QML migration rejected (measured: pyqtgraph 0.2–0.4 ms/frame vs QtCharts 4–6 ms + jank); RHI pinned to OpenGL; Theme QObject singleton from gui/style.py; slice 1 = Scope vertical (assessment: `docs/research/qml_hybrid_architecture.md` §1–7, spike on experimental/qml-shell-spike). (2) **3-layer law** — UI→backend→drivers, down-only; no compute/blocking I/O on GUI thread; enforcement: static import-linter contracts + dynamic watchdog test; allowed edge: gui→analysis for offline (governed by watchdog, detail in §9). Core design rules updated; new registry pointer added to qml_hybrid_architecture.md.

- 2026-07-10 — **G4 scan-viewer integration (best_z_apply → planner).** ScanViewerPanel gained `best_z_apply_requested(float)` signal + "Apply to Planner" button (gated: enabled only after Z-focus completes); PlannerPanel gained `set_focus_z(z_mm)` slot that writes selected STAGE_Z loop's start spinbox (staging-only, never moves motor). tct_gui wires viewer→planner. Signal registry updated; ARCHITECTURE.md scan_viewer_panel + planner_panel entries updated.

- 2026-07-10 — **T3 partial hex sweep + style constants.** gui scope_measurements/calibration_panel/laser_panel/scope_panel/device_panel now token-only; style.py gained SIM_PURPLE (#8e44ad) + ERROR_ORANGE (#e67e22). NEW guard test tests/test_no_inline_hex_gui.py enforces no inline hex in gui/ (allowlist _PENDING_SWEEP: motor_panel.py 1 hex, settings_window.py 6 hex — follow-up pass).

- 2026-07-10 — **Driver reconnect/liveness hardening.** WaveformGenerator: `is_alive()` (*STB? heartbeat) + `_teardown_session()` (close+null _instr and RM, idempotent after dirty death). BlackflyCamera: `is_alive()` (PySpin IsValid) + `_release_hw()` (balanced acquire/release). Both `connect()` idempotent after dirty death. NEW tests/test_reconnect_liveness.py (15 tests). Root cause of Kaya's bench "freezes after disconnect; reconnect only works after app restart" — fixed.

- 2026-07-10 — **T6 pyqtgraph accumulation hang — FIXED.** tests/conftest.py autouse fixture drains Qt DeferredDelete after every test — cured suite wedge past ~450 GUI tests (pyqtgraph grab() accumulation). Suite now 690 passed clean.

- 2026-07-10 — **S2b+S2c module retirement and ScanViewerPanel wiring.** S2b (8312f41): new `gui/scan_viewer_panel.py` (live scan monitor, ScanMapView+MetricGrid+ActionBar, Z-focus CheckableCard, EmptyState, 32 tests). S2c (46ff681, 48396c0, 884afe8): ScanMapView export+freeze-levels, PlannerPanel.set_position_from_motor slot, ScanPanel+ScanMapWindow retired, ScanViewerPanel wired via coordinator (mirror scanner signals 1:1, cockpit pause/abort/z-focus), tct_gui Scan Viewer tab, _publish_last_run_path/_open_in_analysis slots, motor set_as_scan_start → planner set_position_from_motor, coordinator start_plan emits scan_started on success. Module index: removed scan_panel.py + scan_map_window.py entries, added scan_viewer_panel.py, updated scan_map_view.py (export+freeze), scan_coordinator (scan_started), tct_gui (new slots, tab name). Suite 657 passed; Mary APPROVE.

- 2026-07-08 — **S1+S2a module additions and signal registry.** Module index: `gui/scan_map_view.py` (NEW, S1: shared 2-D scan-map widget, FigureCard+pyqtgraph ImageView, quantity selector, autoscale colorbar, cursor readout, live/batch point updates); `gui/scan_coordinator.py` (NEW, S2a: run-control extraction from TCTMainWindow, behavior-preserving); updated `tct_gui.py` note (composition root, signals wired to coordinator methods); updated `controller/plan_estimate.py` (S1: per-BiasStep ramp-duration ETA); updated `gui/analysis_panel.py` (public `load_run(path)->bool` seam). Signal registry: added all 15 ScanCoordinator signals (point_done, progress, scan_started, scan_finished, z_focus_pt, z_focus_done, vscan_point, plan_progress, plan_error, plan_finished, plan_running, hv_armed, manual_pause, warn_dialog, error_dialog, status_message).

- 2026-07-08 — **Bookkeeping post-commit d990d4d: S0 (viewer-prereqs) round landed.** Updated `docs/TECH_DEBT.md`: resolved row 36 (wavegen armed `:OUTPut{ch}:STATe?` query, manual-sourced, implemented in connect(), +17 tests, closes `TODO(manual needed)`); added resolved row for PyVISA AV fix (main-thread prime_pyvisa() warm-up + test stubs + style.py apply_theme walk removal, Paul/Noah, +3 regression tests). Updated `docs/BENCH_CHECKLIST.md`: §3a/3b (DG4162 load/state queries with firmware version + manual citations + readback format), §4a (TBS1052C probes upgraded from unverified to manual-cited 077-1691). Added panel_kit.py section to `docs/signal_registry.md` (CheckableCard.toggled). Updated `docs/ARCHITECTURE.md`: devices section (waveform_generator row), waveform_generator.py facts (prime_pyvisa, armed-state query, unipolar config), gui section (all 12 panels on panel_kit, cockpit-kit batch3 components), scan_controller.py (last_run_path property), scan_plan.py (BiasStep ramp fields), configs/tests section (pytest.ini). Appending S0 completion to `docs/OVERNIGHT_LOG.md`.

- 2026-07-08 — **Crew meta-review bookkeeping: bench-checklist, decision ADR, and research index.** Created `docs/BENCH_CHECKLIST.md` (single human-runnable bench-verification list: 5 sections grouping TP-Link switch, PC NIC, DG4162 wavegen, TBS1052C scope, iseg HV; each with: what to do, expected result, which file/assumption it closes; HV items gated on explicit user go; safety notes on wavegen output + probe load). Created `docs/DECISIONS.md` (lightweight ADR ledger: date | decision | rationale | affected | status; 8 seed rows from known history: PySide6, numpy<2, printcore no-go, static IPs, ScanPanel retirement, quick-scan JSON drop, crew complete). Added index table to `docs/research/README.md` (7 research notes: date | file | topic | one-line takeaway; links to external research and live-verified findings). Updated `docs/ARCHITECTURE.md` header to point to changelog location and DECISIONS.md for "why" ledger. (Crew meta-review follow-up per user 2026-07-08.)

- 2026-07-08 — **Maintained registries created: signal and config-key lookup tables.** New `docs/signal_registry.md` (all 73 signal definitions across `gui/*.py`, `tct_gui.py`, `status_bus.py` with connection targets) and `docs/config_keys.md` (all 140+ config keys from `devices.yaml` by section, with type/default/validator/consumer cross-reference). Both are mechanical O(1) lookups for answering "where is signal/key X" and "what calls it"; maintained on every structural change.

- 2026-07-08 — **Bench documentation: static-IP approach formalized.** New `docs/BENCH_SETUP.md` (operational how-to: instrument LAN topology table, PC static-IP restore commands, DG4162 front-panel steps, FLIR camera SDK/USB-3 requirements, waveform-generator auto-enable safety, link-troubleshooting reference). Resolves the `docs/TECH_DEBT.md` NOTE from 2026-07-07. Cross-links added to `TCT_app/README.md`. Two follow-up bench-verification TODOs logged.

- 2026-07-07 — **Panel-kit batch3 completion: camera/analysis panels (last 2/12) to design system; waveform-generator unipolar-rails config; cockpit-style overhaul design doc.** `gui/camera_panel.py` and `gui/analysis_panel.py` rebuilt on panel_kit; both added to `tct_gui._toggle_theme()` live-refresh. New test file `test_panel_kit_rollout_batch3.py` covers batch3 constructor assertions. All 12 core panels now on consistent design system. `waveform_generator` config gains optional `level_low_V`/`level_high_V` (unipolar 0→+V, opt-in, default bipolar); validated in `config_validator.py` (both-or-neither, numeric, low<high); documented in `devices.yaml`. New design doc `docs/design/cockpit_style_overhaul.md` — "TCT Cockpit" GUI style overhaul plan (formalized from Codex draft + Adam review); records 2026-07-07 user decision: **ScanPanel will be RETIRED** (Planner is the only scan config/start surface); new ScanViewerPanel (live run monitor) is planned.

- 2026-07-07 — **Real-hardware bench bring-up: PySpin + camera GenTL-auto-locate/binning fixes; Marlin M114 stale-position + motor panel-freeze fixes; DG4162 moved to static LAN (192.168.0.10) — camera/motor/wavegen all real-verified. Suite 445.** `camera_blackfly.py` auto-locates FLIR GenTL producer (FLIR_GENTL64_CTI_VS140), guards binning writes (IsWritable); 64-bit Spinnaker SDK + direct USB-3 required. `motor_grbl.py:_marlin_get_position()` now retries/skips echo on ADVANCED_OK 'ok P.. B..' suffix, raises on failure. `motor_panel` reload no longer freezes (QThread parenting fixed). `SoftwareLimits`/`config_validator` reject swapped envelope. `waveform_generator.py` driver verified on static instrument LAN (192.168.0.10/24, isolated). HV/laser deliberately left OFF (not yet bench-verified per user request).

- 2026-07-07 — **GUI improvement: panel_kit composition layer + pilot (scope/laser) + batch-1 rollout (motor/bias/intensity/monitor/devices); QtDangerGate stray-dialog fix; native planner locked (embed shelved); suite 321.** New `gui/panel_kit.py` (Card: title/subtitle, header, per-card `set_rail(axis, mode)` with dynamic railAxis; panel_header, eyebrow_title, section_header, readout_cell, form_row, axis_rail_css; QSS hooks cardHeader/cardTitle/cardSubtitle). Pilot scope_panel + laser_panel rebuilt on panel_kit (Mary APPROVE-WITH-NITS; nits fixed: rail scoping, docstrings). Scope fixed pre-existing chip-overflow clipping DUT-analysis readouts. Batch-1 rollout: motor, bias (4/6 boxes; 2 CHECKABLE groupboxes stay native QGroupBox), multi_bias, intensity, monitor, device_panel (hardcoded colors → tokens, +11 tests). QtDangerGate stray-dialog BUG fixed (+3 regression tests); honest plan-run terminal status; native-planner decision (embed shelved). tct_gui theme-refresh tuple: motor, bias, planner, scope, laser, monitor.

- 2026-07-07 — **P2.2 executor & planner (steps 2+3), fault injection, scope modularity, design-system rollout:** `controller/danger_gate.py` (DangerAction/DangerGate protocol, AutoConfirmGate/DenyAllGate/QtDangerGate); `ScanController.arm_hv()` latch, `start_plan()`/`_run_plan()` with shared fail-safe helpers, motor.stop() in all finallys, HV re-assertion on resume; `tests/test_fault_injection.py` + `test_fault_injection_legacy.py` prove safety under disconnect/HV-trip/motor-fault/abort; `gui/planner_panel.py` v2 (Recipe-Tree, drag-drop, movable nodes, 20-deep undo, live estimate); `gui/qt_danger_gate.py` (worker→GUI confirm bridge); `gui/status_widgets.py` (StatusChip/StatusPill/flash_button); `Oscilloscope.n_channels` modular (config-settable, *IDN?-clamped, validator checks 1..8); `ScopePanel.rebuild_channels()` at connect; design-system tokens rolled across all panels. Suite **293 passed**.

- 2026-07-06 — **M2.1 design-system foundation:** `gui/style.py` evolved to a
  token design system (scope-cyan accent `#33c8ff` dark / `#0d8ba6` light;
  tokens `accent_strong`/`amber`/`good`/`warn`/`crit`; spacing/radius/type
  scales; axis-rail palette for bias/Z/X/Y/laser/delay/hazard; `axis_color()`
  helper; new `statusChip` + `eyebrow` objectName hooks; all 12 legacy hooks
  preserved). Both themes render; 153 tests pass.

- 2026-07-06 — Documented the multi-channel bias + polarity + per-channel
  scan work: new `devices/bias_channel.py:BiasChannel` proxy (one VISA/serial
  session serves N channels, no I/O or state of its own); the
  polarity/multi-channel API added to `devices/bias_supply_base.py`
  (`supports_polarity_switch`/`get_polarity`/`set_polarity` [DANGEROUS]/
  `channel_count`, safe single-channel defaults, `normalize_polarity`,
  `_ramp_channel`); `devices/bias_supply_iseg.py`'s channel-aware `*_ch`
  methods, per-channel state dict, and gated `set_polarity_ch` (reversible +
  output-OFF fail-closed + discharged + confirm-poll — SCPI and the 0.5 s
  relay-settle budget verified only against `docs/research/iseg_polarity_scpi.md`
  and simulation, **not yet on real HV**); `controller/device_manager.py`'s
  `self.bias_supply` (now a primary-channel `BiasChannel`, stable object) and
  new `self.bias_channels` list + `refresh_bias_channels()` (auto-called at
  the end of `connect_all()`); the new `gui/multi_bias_panel.py:MultiBiasPanel`
  (one `BiasPanel` tab per channel, global ALL-OUTPUTS-OFF) and `BiasPanel`'s
  new Polarity group (gated Switch-Polarity button, per-panel
  `_ReadoutPoller` thread); and `controller/scan_controller.py`'s optional
  `bias_channel` field on `ScanConfig`/`VoltageScanConfig` plus
  `ScanController._resolve_bias(cfg)`, which validates the index and refuses
  to start on an out-of-range channel.

- 2026-07-07 — **Phase 2.2 step 1 + Phase 3 kickoff:** Documented three new pure planner modules (`controller/scan_plan_validator.py`, `plan_compiler.py`, `plan_estimate.py`; 51 tests total) and updated `scan_plan.py` (new `LeafMeta` + `iter_leaf_contexts_ex()`) and `config_validator.py` (now covers 11 `devices.yaml` sections; 14 tests). Mary review CHANGES-REQUIRED → all 4 findings fixed (MoveStep None-axis contract, loop n_averages/settle propagation, module rename, safety-None guard) + independently probe-verified. Suite **218 passed**.

- 2026-07-06 — Added `gui/liveness.py:LivenessMonitor` (background-thread
  device-liveness sweep, owned by `TCTMainWindow`) and the
  `devices/base.py:BaseDevice.is_alive()` contract it polls via
  `controller/device_manager.poll_liveness()`. Documented `oscilloscope.py`
  invariants added for the TBS1052C (bench oscilloscope; `TRIGger:A:*` trigger
  tree, `SELect:CH<x>?` pre-check in `read_channel()`, `_recover_session()`
  device-clear, `_check_scpi_errors()`, new `set_averaging()` /
  `set_channel_display()`, `n_channels` sourcing, `*STB?` liveness) and the
  matching `gui/scope_panel.py` per-channel fault isolation, channel-toggle
  SCPI drive, and averaging combo. Recorded that `oscilloscope_tek_fastframe.py`
  is currently non-functional (vendored `dustin_scope` missing from
  `TCT_app/vendor/`) and targets the MSO5204B, not the bench TBS1052C.

- 2026-07-05 - Restored the missing `TCT_app/data/` package used by
  `device_manager` and `scan_controller`; added smoke coverage for the HDF5
  writer and disabled Influx sink.

- 2026-07-05 — Flattened project layout around the app: app root moved to
  `TCT_app/`; reference material moved to `reference/`; lab images/manuals moved
  to `lab_assets/`.
- 2026-07-05 — Marked third-party and lab reference folders as local-only ignored
  material; documented the clean-root policy in `docs/REFERENCE_MATERIAL.md`.
- 2026-07-04 — Initial bookkeep created from source inspection (main, tct_gui,
  state_machine, scan_controller, device_manager, base device, hdf5_writer,
  SCAN_DATA_FORMAT.md). Some sections marked TODO for deepening.
