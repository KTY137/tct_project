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

## capabilities/ (D1a — pure-data model)

- `model.py` — Capability spine data model: `CapabilityDescriptor` (frozen enumerated specification of device/system capabilities), `HVSource`, `Motion3D`, `FrameSource`, `ReadableChannel`, `SafetyClass`, `Operation`, `ReadbackPolicy`, and supporting aliases (`SLOW_CONTROL_CHANNEL_ALIASES`, capability ID pattern). **Stdlib-only by law** (§2.1 of CAPABILITY_MODEL.md); no Qt, no hardware I/O. Normative spec: `docs/CAPABILITY_MODEL.md` v1.0-rc. Adapters (builder from `devices.yaml` + runtime registry) in progress (D1b).

## controller/

- `state_machine.py` — `AppState` enum and validated transitions:
  `DISCONNECTED → CONNECTED → HOMED → CONFIGURED → READY → RUNNING →
  {PAUSED, FINISHED, ERROR, ABORTED}`; `PAUSED → {RUNNING, ABORTED}`; terminal
  states fall back to `CONFIGURED`. **Every state may reset to `DISCONNECTED`**
  (universal recovery, incl. crashed scans). Invalid transitions raise
  `ValueError`; observers register callbacks. `transition()` is thread-safe
  (protected by RLock); callbacks are invoked outside the lock. A ValueError
  on a race is a documented contract.
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
  Public seam `park_safe()` halts motion, discharges HV (primary channel only),
  and resets state for recovery. Design-system law 5: `execute_plan(plan, gate)`
  slot accepts a `DangerGate` and runs it; `slow_control_manager` feeds channel
  WARN/ALARM thresholds into per-point analysis status (scan continues; warnings
  are advisory). `_move_action` and `_acquire_core` (shared by estimate + executor)
  ensure derived HV/motion bounds for the `ArmedEnvelope` are byte-for-byte identical
  to live execution. Public seam `park_safe()` halts motion on all axes, discharges
  HV (primary channel only), and resets state for recovery.
- `danger_gate.py` — danger action protocol and authorization gates. `DangerAction`
  dataclass (action kind, `requires_confirm: bool`); `DangerGate` protocol (async
  request/confirm workflow). `AutoConfirmGate` (auto-approves in simulation);
  `DenyAllGate` (always refuses); `QtDangerGate` (worker→GUI bridge, timeout
  fail-closed). Used by executor step 2 to gate HV ramps and moves.
- `arm_envelope.py` — pure, hardware-free arm-envelope model (design-system law 5).
  `ArmedEnvelope` (frozen, enumerated authorization: bias channels, HV min/max V,
  ramp shape, per-axis motion bounds, human-readable summary, `routine_names` for
  multi-routine execution tracking). `derive_envelope` / `envelope_from_plan`
  (build from compiled plan, reusing executor's exact seams so armed bounds match
  execution; supports combined queue envelope for sequenced routines).
  `ArmedEnvelopeGate` (DangerGate impl: auto-approves any live DangerAction
  provably inside envelope, denies outside or after expiry; fail-closed, no side effects).
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
- `survey_plan.py` (NEW) — Survey preset builder. `SurveyPlan` (snake-pattern raster
  of move+capture_photo planner steps; geometry specified in `plan.safety['survey']`
  dict with grid bounds and spacing). Used by planner presets to auto-generate
  capture sequences for mosaic assembly.
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
- `sequencer.py` — Pure queue engine for executing scan plan steps. `SequenceRunner`
  (executes compiled `Step` list, no hardware I/O, no Qt dependencies, fail-closed
  halt on error). `PreflightHook` seam for custom pre-execution logic. YAML-serializable
  plan persistence and recovery. Used by executor/planner for deterministic step replay.
  `assert_sequencer_compatible(plan)` blacklist vets plans; `record_outcome(step, result)`
  only advances the sequence on FINISHED outcomes.
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

**Guarded-exchange helpers (G0, 2026-07-13):**
- `_guarded_exchange(transport_lock, primitive) -> T` (T1 single-exchange helper): acquires the lock, runs exactly one primitive, releases, returns result. Recorder pattern — lock ownership recorded at call time.
- `_guarded_group(transport_lock, fn) -> T` (T1g bounded-group helper): acquires the lock once, runs `fn()` (which may do N things), releases, returns result. Exclusive for the duration.
- `_probe_exchange(transport_lock, primitive, default) -> T` (T3 non-blocking helper): returns `default` (busy sentinel) WITHOUT blocking if transport is held elsewhere; runs `primitive()` under lock when free.
- Re-entrancy via RLock: a T1 exchange inside a held reservation works (same thread, recursive acquire).
- `__init_subclass__` override detector REGISTERS current unconverted drivers (legal until G1/G2), warns on synthetic overrides (a base that OWNS a guarded method).
- Design: `docs/design/guarded_exchange.md` §3/§5-§6; contracts in Bucket B test `tests/test_guarded_exchange_base.py` (identity, no-interleaving, re-entrancy, non-vacuous registry).

**Transport-lock contract (2026-07-13):**
- `BaseDevice.transport_lock` (public property, re-entrant RLock): the lock a
  caller must acquire before exclusive transport use (VISA/serial I/O). Every
  driver's own I/O acquires this same lock internally, so concurrent
  pollers and move-logic threads never interleave hardware exchanges. **Stop
  paths are exempt:** emergency stops (motor #24, GRBL real-time byte) take no
  lock and complete immediately. Detailed invariants verified in
  `tests/test_motor_transport_lock.py` (motor drivers) and
  `tests/test_drs4_lock.py` (DRS4 scope). Design: `docs/design/guarded_exchange.md`.

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
  already use — `set_voltage`/`set_compliance`/`enable_output`/`is_output_on`/`output_off`/
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
  `set_voltage`/`set_compliance`/`enable_output`/`output_off`/`read` are thin
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
- `app_settings.py` — Central QSettings accessors for GUI/user preferences (typed helpers for persistent state: theme mode, geometry, active tab, detached titles, planner arm-latch, theme overrides/glass/typography/radius/opacity/backdrop/presets).
- `worker.py` — Owned worker-lifecycle primitive for the GUI (thread management, terminal-signal handling, GUI-thread-safe teardown). Prevents wait-on-self deadlock and stray timer-fires on deleted widgets by construction. `WorkerThread` with `ShutdownKind.ABANDON` vs `MUST_COMPLETE` semantics; ~8 sibling workers pending migration.
- `qml/Shell.qml` — QML-hybrid chrome: rail (Devices/Settings/Log/Debug chips + app-state readout, icon buttons compress without Flickable) + pill tab shelf (syncs DetachableTabWidget index).
- `qml/MetricTile.qml` — Reusable Theme-bound metric tile: title/value/unit/caption/accent/stale/compact modes; pure view, 3-layer law; consumed by ScanStatusStrip.
- `qml/ScanStatusStrip.qml` — Flow of 5 metric tiles (State/Progress/ETA/Elapsed/Scan) bound to the runState context property; pure view, 3-layer law; surfaced as the third chrome strip in Shell.qml. Chrome height increased 96 → 204 px; `qml_shell.py` setFixedHeight(204).
- **Invariants:** Classic DetachableTabWidget is the sole tab/detach engine—QML shelf is a *view*; pyqtgraph plots are NEVER inside QQuickWidget; style.py remains the single token source (Theme singleton mirrors it); soft-reload (production config reload) releases old QML engine before building new one.

**Backdrop & window chrome (Windows 11 DWM):**

- `backdrop.py` (NEW, C1) — Win11 DWM Mica/Acrylic material effects. All ctypes
  calls isolated; fail-safe DWM API version check + capability fallback (mica → acrylic
  → none). Offscreen windows and test environments no-op safely. Persisted via
  QSettings key `theme/window_backdrop` (values: none|mica|acrylic, default none,
  garbage → none). Material is combined with `theme/window_opacity` slider
  (0–100%). C2 integration: `style.py` backdrop trio (compute glass amount from
  opacity, fetch material tokens), `theme_editor.py` combo for preset selection.

**Core panels & support (all on `panel_kit` Cards):**

Panels: `motor_panel`, `bias_panel`, `multi_bias_panel`, `scope_panel`,
`laser_panel`, `intensity_panel`, `camera_panel`,
`monitor_panel`, `analysis_panel`, `calibration_panel`, `device_panel`
(`DeviceManagerWindow`, `device_state`), `settings_window` (owns a `_VisaRescanWorker` scan + a `_ScanReaper` GUI-thread-affine strong owner of the old background scan worker for deadlock-safe teardown — see VISA-scan deadlock postmortem in `docs/DECISIONS.md`), `theme_editor.py` (`ThemeEditorDialog`, View → Theme… —
non-modal preset browser: `Cockpit Dark`/`Lab Light` built-ins + user presets
persisted as QSettings JSON under `theme/presets`; Colors/Typography/Radius
cards plus a Material card whose glass-amount slider live-previews
`style.set_glass_amount()`; all state lives in `style.py`'s override layer
(`apply_theme_overrides`/`set_glass_amount`/`apply_typography`/
`apply_radius_scale`, persisted via `save_theme_customization`/
`load_theme_customization`); Apply emits `applyRequested(mode)`, routed by
`tct_gui._on_theme_editor_apply` through the same repaint path as the
dark-mode toggle; safety palette — danger/armed/sim/error — renders
**locked**, read-only, no color-dialog path (`style.sanitize_overrides` also
strips those keys from any loaded preset JSON, laws 1/2/6)), `planner_panel`
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
`status_message`; new `execute_plan(plan, gate)` slot wires ScanController.execute_plan),
`sequence_coordinator.py` (NEW) — Qt queue driver for plan sequences. `SequenceCoordinator`
coordinates multi-routine sequencing via `start_sequence()` seam; union gate is private to
the coordinator; emits `sequence_active(bool)` contract signal to planner for UX feedback.
Stateless dispatcher that routes sequencer signals (entry_state_changed, sequence_progress,
sequence_finished, sequence_error) to GUI listeners.
`sequencer_panel.py` (NEW) — Operator-facing sequencer UI. Panel that manages queue
display and control; reuses `ArmLatch` component for sequence authorization. Fail-closed
load semantics: validates before accepting new sequence item.
`arm_latch.py` (design-system law 5: `ArmLatch` two-step gesture well — hold-to-arm
or press-twice, ~10 s auto-disarm countdown, instant-stop abort separate; pure view
with no hardware I/O or controller refs; renders envelope summary; signals arm_started/
armed/disarmed/execute_requested; parent panel derives `ArmedEnvelope` and reacts to
signals to build `ArmedEnvelopeGate` and start run), `stage_view.py` (2D stage views: X-Y top + X-Z side + live Z numeric chip in header),
`scope_measurements.py`, `detachable_tabs.py`, `style.py` (token design system:
scope-cyan accent, tokens for UI states, spacing/radius/type scales, axis-rail
palette, `axis_color()` helper, `statusChip`/`statusPill`/`eyebrow` objectName
hooks), `qt_danger_gate.py` (`QtDangerGate`: worker→GUI confirm bridge, timeout
fail-closed), `liveness.py` (`LivenessMonitor` — background device-liveness
sweep, owned by `TCTMainWindow`, see Big picture and Entry point), `motion.py`
(visual-motion helpers for cockpit chrome: `ActivityRing` — QFrame, tiny
QSS-painted activity ring, e.g. `tct_gui`'s shell status-strip `_ring_scan`
toggled active on `AppState.RUNNING`; `PulseController`/`set_pulse(widget,
active, kind=...)` — semantic pulse, `kind` "laser"/"hv"/"scan" today, driving
`tct_gui.py`'s laser/bias-HV/scan status chips and `laser_panel.py`'s output
chip; `flash_property`/`flash_readout` — temporary property flash restored by
a child `QTimer`, used by `scan_viewer_panel.py`; only flips dynamic
properties QSS already paints, no `QGraphicsEffect`, every timer parented to
its widget — law 8), `motion_kit.py` (NEW: fluent animation layer for QWidgets
panels — `fade_swap` QStackedWidget cross-fade, `roll_number` tabular readout
roll, `pulse` one-shot attention pulse; OutQuint easing, global `motion_enabled()`
kill switch via `app_settings`; explicit `_detach()` on finish/cancel prevents
anim↔widget closure cycles; no `QGraphicsEffect`; all helpers parent to their
target WHILE RUNNING and detach when done).
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
  software limits, timestamps. **Camera honesty contract:** (B1) `camera/frame_point_index`
  dataset maps frame to point (no implicit drop on shape mismatch), `camera/frames`
  never zero-padded, `n_frames_omitted` attribute counts silent drops. Extensible
  datasets, gzip, chunk 64. **Full contract: `TCT_app/SCAN_DATA_FORMAT.md`** — the
  authoritative data-format doc; keep both in sync.
- `influx_writer.py` — optional slow-control sink to InfluxDB.
- `save_options.py` — which HDF5 groups are written; editable in Settings GUI.

## analysis/

`waveform_analysis.py` (`analyse_waveform`, `WaveformResult` — amplitude, charge,
baseline RMS, drift/rise/CFD/onset times), `correct_baseline` (canonical baseline
subtraction, mirrored in intensity_base for ref-channel parity — guard test ensures
byte-for-byte equality), `charge_calibration.py` (`ChargeCalibration`),
`laser_normalization.py` (`normalise`), `efield_analysis.py` (`reconstruct_efield`,
`compute_cce` — auto-reference bias-scan CCE, `estimate_depletion_voltage`,
`fit_depletion_voltage` (D1: threshold-crossing fit with quality, replaces bare estimate),
`compute_cce_with_uncertainty` (D2: CCE ratios with confidence bounds)).

## vision/

ArUco fiducial detection and 2D sensor-pose estimation tier-1 layer (tier 2/3 future).
Lazy cv2 import (opencv-python-headless optional); pure leaf with no analysis/device
dependencies. Public seam: `is_available()` probe; user-facing `PoseEstimate` carries
precision-quality metrics (baseline_px, precision_deg, meets_precision_target).
Wired into `gui/analysis_panel.py` (E7c: alignment UI on Survey mode).

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
- `image_prep.py` (NEW) — Metrology preprocessing for stitched-image assembly.
  Handles sensor orientation via ArUco fiducials and classical CV (template matching,
  contours), NaN-fill-before-FFT invariant for frequency-domain alignment. Lazy import
  with clean feature-disabled degradation if `opencv-python-headless` unavailable.

## scripts/

- `capture_onscreen.py` (NEW) — MANUAL-RUN onscreen capture harness for real desktop DWM compositor effects (Mica/Acrylic material visibility). `check_environment()` refuses offscreen/minimal Qt platform or missing primary screen. `--list` dry run. 8-scenario backdrop/preset matrix (none|mica|acrylic × Cockpit Dark|Glass × dark theme) + transition bursts, runtime capture-method self-probe (grabWindow vs GDI BitBlt), settings snapshot/restore via `app_settings` key constants. Never part of test suite; guard test `tests/test_capture_onscreen_guard.py` covers refusal + --list + settings helpers.
- `metrology_report.py` — Self-contained HTML metrology report for stage↔camera calibration (E5). `write_report(cal, path, *, tile_diagnostics=None, tolerance_um=None)` renders calibration summary with inline-SVG residual quiver plot, PASS/FAIL verdict against tolerance, and optional mosaic tile-placement diagnostics. No Qt, stdlib + numpy only. Fully deterministic (fixed-precision formatting, no wall-clock in geometry). Results are offline-browsable HTML files with inlined CSS/SVG.

## configs/ and tests/

- `configs/devices.yaml` — single config source: backend selection per device,
  connection parameters, `output.data_dir`, `output.save` toggles, calibration,
  software limits. Validated by `config_validator`.
- `pytest.ini` — pytest configuration (timeout=60s per test, preventing hangs on
  unresponsive mock transports; faulthandler_timeout=90s because pytest-timeout's killer thread is itself GIL-starved when a worker thread holds the GIL indefinitely — see VISA-scan deadlock postmortem in `docs/DECISIONS.md`).
- `routines/` — Frozen example scan plans (R1–R6 YAML files): reference routines for planner Save/Load testing and documentation. Byte-identical across all runs; loaded via `ScanPlan.load()` / `controller.plan_from_config`.
- `tests/conftest.py` — shared pytest fixtures; T6 (2026-07-10): added autouse fixture that drains Qt's DeferredDelete queue after every test, curing accumulation hang (suite wedged in pyqtgraph grab() past ~450 GUI tests).
- `tests/fixtures/routine_corpus/` — Frozen test corpus: byte-identical routine YAML snapshots (R1–R6) + README; consumed by P2 replay-gate fixtures for deterministic regression testing (assert corpus size ≥5, byte-diff on changes).
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

- 2026-07-14 — **feat(controller): glass_probe.py instrument scan/diagnostic utility (11407b6).** Scripted open-timeout + io_lock probe for every VISA/serial device; fail-fast verification (names + SCPI ID queries) without operator GUI intervention; parametric timeout sweep output. One-shot diagnostic harness.

- 2026-07-14 — **refactor(controller): panel_kit registry prune-on-read + async UI-thread gate (ab0cbee).** glassPane registry now self-cleans dead C++ wrappers on each read query (GUI thread only). Safe for dynamic panel add/remove without stale references. Eliminates prune-on-close call.

- 2026-07-14 — **fix(devices): open_timeout bounds all VISA/serial open calls; fail-safe on timeout (7b4ea94, 8e85f2a).** WaveformGenerator (DG4162 open_timeout 5 s default), OscilloscopeVISA, BiasSupplyISEG, BiasSupplyKeithley, oscilloscope_drs4 all now use bounded open() with explicit timeout. Connect-phase timeout no longer drifts to minutes on powered-off instruments. Fail-safe: on open failure, `_teardown_session()` immediately closes/nulls VISA handles + RM; io_lock-guarded close chain prevents reentrant use of dead sessions. E2E integration test: reconnect stress (Disconnect All/Connect All cycles with liveness monitoring) now crash-free.

- 2026-07-14 — **fix(controller): _run_bg completion now bound-method + QueuedConnection delivery (e0a9d91).** ScanController._run_bg workers complete on the main thread via bound method + QueuedConnection to _on_run_bg_done (not QThread.finished signal). Eliminates cross-thread race on worker teardown + result delivery. GUI-thread-affine result handling; app quit+wait semantics unchanged.

- 2026-07-14 — **fix(gui): main-window bg-thread (liveness monitor) now joins on teardown (5576378).** TCTMainWindow._teardown_panels() explicit `liveness_thread.quit(); liveness_thread.wait()` before widget close. Eliminates background thread lingering past app shutdown.

- 2026-07-14 — **feat(gui): wave 1-3 stage_view/intensity/laser panels onto glass kit (3a6d0ea, 2e02b8d, 5971741).** PanelKit adoption: `stage_view.py` (2D X-Y top/X-Z side), `intensity_panel.py`, `laser_panel.py` now render on panel_kit Cards; `_toggle_theme()` includes all three; glass registry + PANEL_GLASS_ALPHA tuning per Z-ladder.

- 2026-07-14 — **fix(gui): ribbon wrap + theme icons + status-chip ink retune (4ca8331).** NEW `gui/flow_layout.py` wrapping QLayout (heightForWidth, replaces silent QScrollArea clipping). Icon buttons now re-tint live on theme toggle (frozen pixmap bug fixed). NEW palette tokens: `danger_fill`, `on_danger`, `on_armed`, `plot_accent`; `SAFETY_TOKENS` widened (locked danger/armed/sim/error + aliases). Every hazard chip label now uses neutral `text` ink; hue lives in fill+border. NEW `_ShellBridge` property pairs: `hvCurrentText`/`hvCurrentState`, `hvComplianceText`/`hvComplianceState` (leakage + compliance restored to QML island). Mary: APPROVE-WITH-NITS (shippable to bench). Bench-gate: 14a ribbon wrap / 14b icon retinting / 14c chip look verification at real DPI (Kaya's eye on saturated-dot callback).

- 2026-07-13 (night) — **feat(glass): run.ps1 defaults to QML shell (76c2370).**

- 2026-07-13 (night) — **docs(glass): glass council findings + synthesis (2525285).**

- 2026-07-13 (night) — **feat(design): 3D GL stage view removed; classic cockpit RTT-free (b7f88a3).**

- 2026-07-13 (night) — **feat(glass): panel glass rollout per Z-ladder + Kaya's Material menu (7df2537).** Canvas_alpha (≥0.80), panel_glass_alpha (≥0.50), glass_tier (auto|mica|acrylic|token|flat) QSettings keys. Mode selector + 2 clamped alpha sliders in theme-editor. Bias/monitor deliberately register zero glass panes.

- 2026-07-13 (night) — **fix(glass): Mica composed LIGHT because DWMWA_USE_IMMERSIVE_DARK_MODE never set (2cf720b).** Qt had been setting it implicitly via stylesheet repolish; the perf skip unmasked it.

- 2026-07-13 — **feat(gates): Bucket-map documentation and frozen routine corpus (7272233).** NEW `docs/test_bucket_map.md` (A=47/B=18/C=39/D=5 test distribution). NEW `.claude/check_bucket_a.ps1` ([A-green] machine check). Frozen routine corpus: `TCT_app/routines/` (R1–R6 example scan plans, loadable via planner Save/Load), `TCT_app/tests/fixtures/routine_corpus/` (P2 replay-gate corpus, byte-identical for regression).

- 2026-07-13 — **feat(controller): P0' — Wavegen command tracing and run metadata (5c75696).** `ScanController._apply_wavegen_settings` per-point wavegen parameter application before `_acquire_core`. NEW `/run_info` attr `wavegen_command_trace` (commanded-only JSON trace). NEW `HDF5Writer.set_run_metadata(key, value)` for extensible run-level metadata. Validator gains `_KNOWN_WAVEGEN_KEYS` (unknown nested key = ERROR). EMITTING semantics unchanged.

- 2026-07-13 — **fix(tests): conftest pytest_sessionfinish cooperative QThread reaper (031bc53).** Permanent leak guard: app-parented QThreads (planner estimator, VISA scan, liveness monitor) now quit+wait on `pytest_sessionfinish`, never terminate (Qt6 abort-at-exit fix). Opt-out via `TCT_ALLOW_LEAKED_THREADS=1`. Root cause: app-parented QThread lifecycle → Qt6 aborts on exit; xdist masked the issue by running each worker on a dedicated process. 31 regression tests added.

- 2026-07-13 — **docs(gui): _reassert_window_palette docstring updated for identical-QSS guard (4433ebb).** Clarified DWM material + opacity interaction (no redundant repolish when QSS is unchanged across themes).

- 2026-07-13 — **perf(gui): apply_theme skips setStyleSheet when QSS unchanged (26538a4).** O(n²) repolish hang during soft-reload eliminated: dynamic QSS text hashing detects identical sheets and skips redundant `setStyleSheet()` calls. Fixes 5–30 s hang on repeated theme toggles in QML mode.

- 2026-07-13 — **gui/style.py + backdrop: theme-toggle repaint fix under active DWM material (9cdc970).** window.update() symmetric to the none-path repolish; canvas rule becomes rgba(bg,0.82) passthrough when a backdrop is active, byte-identical when none; docs/design/glass_gap_findings.md added.

- 2026-07-13 — **gui/monitor_panel.py: banner worst-computation now uses local _BANNER_SEVERITY (1af0325).** OK<WARN<UNAVAILABLE<ALARM — a hard alarm can no longer be masked by a concurrent UNAVAILABLE channel; headline carries "Alarm · N unavailable".

- 2026-07-13 — **gui/motion_kit.py + bias_panel + qml_theme: Mary-A riders (f7fcc65).** roll_number gates on the rendered string (HV readout no longer rolls on noise), destroy guard (target.destroyed → stop+detach, defensive hardening with wiring tests), public cancel_roll/cancel_pulse/cancel_all + shutdown quiesce, specular getter warns+falls back to 0.1 instead of raising in a QML binding.

- 2026-07-13 — **Real DWM glass: WA_TranslucentBackground extended to centralWidget (7cb2bd3).** Default QSurfaceFormat alpha=8 before QApplication, effective opacity pinned 1.0 while a backdrop is active (stored pref kept; slider clamped+noted), backdrop/opacity/panel-glass auto-apply+auto-persist, glassPane opt-in registry (theme-editor cards only tonight; FigureCard refused), PANEL_GLASS_ALPHA=0.55 + BACKDROP_CANVAS_ALPHA=0.82 placeholders for live tuning, surface-tint tooltip.

- 2026-07-13 — **docs/CODEX_QUEUE.md: C9 findings (3f1ba4e).** Sandbox venv failure root-caused to WindowsApps store-alias base interpreter; fix = recreate venv from non-Store CPython 3.10.

- 2026-07-13 — **CLAUDE.md + DECISIONS.md: orchestration upgrade ratified (87b1ac5).** Per-beat Mary for safety class, Shiori brief-checks, judgment-beat Opus override, report caps 1200, free lanes as parallel value superseding free-lane-first.

- 2026-07-13 — **NEW TCT_app/scripts/capture_onscreen.py (629336c).** Manual-run onscreen capture harness (real desktop only, refuses offscreen) — 8-scenario backdrop/preset matrix + transition bursts, runtime capture-method self-probe (grabWindow vs GDI BitBlt), settings snapshot/restore from app_settings key constants; guard test file tests/test_capture_onscreen_guard.py.

- 2026-07-13 — **gui/style.py BUILTIN_PRESETS grows 4 (b011599).** Now 9 total: Glass (1:1 from artifact: 0.42/0.55 alpha recipes + text/muted/accent literals), Plasma (violet ambient), Aurora (teal rotated -25deg off SIM cyan, distinctness test-pinned), Spatial Light (light frosted, panel stays #FFFFFF per ladder-inversion rule); computed WCAG contrast asserted per preset; locked safety tokens preset-unreachable (guard).

- 2026-07-13 — **NEW gui/motion_kit.py (87c54fd).** SIBLING of pre-existing gui/motion.py property-flip system: fade_swap (QStackedWidget cross-fade), roll_number (readout roll, tabular), pulse; OutQuint easing, global motion_enabled() kill switch via gui/app_settings (new key); explicit _detach() on every finish/cancel path fixes found access-violation class (anim↔widget closure cycle + DeleteWhenStopped vs Python cyclic GC); gui/qml_theme.py specular alphas now parsed live from gui.style LIGHT/DARK (cached table removed) + drift-guard test; consumers: analysis_panel mode switch, bias_panel voltage tile (display only).

- 2026-07-13 — **gui: state-color W3 batch 2/3 (d03b5ff).** Cockpit v5 design colors deployed: green-on-nominal removed (device_panel chip, Shell.qml dots, connect/disconnect chrome); bias/multi_bias kill-switch escalation ghost/neutral/danger via dynamic killSwitchBtn state + kill_switch_state_changed aggregation; Monitor "All nominal" gated on >=1 reading; Find-focus button reclassified as motion-command class.

- 2026-07-13 — **DECISIONS: v6 glass direction + QML-hybrid boundary ratified (fbcc185).** Artifact A/B committed (artifacts_claude/tct_bias_glass_ab.html). QML-hybrid boundary: QML=shell/ornaments + QWidgets=panels/safety single-impl; no live shader glass; classic shell frozen fallback (TCT_QML_SHELL default probe-gated). Prometheus memo: `docs/research/qml_hybrid_standard_decision.md`.

- 2026-07-13 — **E7c: sensor-pose align UI on Survey mode (89c624a).** `gui/analysis_panel.py` NEW: vision-gated detect button, mm-space pose overlay, 4 pose MetricTiles + precision chip, "Align scan grid" emits grid_alignment_suggested(dict) — numbers only, no motion/controller. vision/ added to layer contract as pure leaf with explicit gui→vision allowance. E-track E1-E7 complete.

- 2026-07-13 — **gui/style.py: v6 glass tokens (54bc4b8).** Dark specular 0.045→0.14, panel #121824→#0d111a (blend formulas, artifact-sourced), well/sunk collapsed #070a0f, NEW "chip" key, RADIUS_XL=20 on card surfaces; light panel stays #FFFFFF, light v6 via well/sunk/chip/specular 0.92.

- 2026-07-13 — **E5: Metrology report (449a96e).** NEW `scripts/metrology_report.py`: `write_report(cal, path, *, tile_diagnostics=None, tolerance_um=None)` → self-contained HTML calibration report (inline-SVG residual quiver px+µm, PASS/FAIL vs tolerance_um, place_tiles diagnostics section). Deterministic output (no randomness, no wall-clock in geometry). No Qt, no external assets — fully offline-browsable.

- 2026-07-13 — **E4: Affine calibration gate and degenerate handling (93756ab).** `controller/repeatability.py` `calibrate_affine`: cooperative `should_stop` polled before every staircase move; degenerate-fit ValueError now returns `affine=None+notes` instead of raising past the confirmed gate; docstring pins the caller contract (branch on `cal.affine is None`, surface `cal.notes` to operator).

- 2026-07-13 — **S2d: GUI style token retune — Codex S1 (d94ad3e).** `gui/style.py` token retune (items 1/2/4/5): metric labels 11px/tracking 0; surface-ladder retune light+dark; denser secondary buttons with primary/motion/danger pinned at old affordance; header/tree row grammar.

- 2026-07-13 — **S2c: App-settings central QSettings accessor (93ba2a0).** NEW `gui/app_settings.py`: central owner of `QSettings("TCT","TCTSetup")` with typed helpers; 13 call sites in gui/, main.py, tct_gui.py migrated; guard test blocks direct construction (gui/style.py allowlisted, follow-up pending). Resolves row 107 RISK (test-suite was writing to DEVELOPER'S REAL registry).

- 2026-07-13 — **E6b: Per-frame stage position record (95ac0f0).** `data/hdf5_writer.py` NEW `camera/frame_pos_mm` (M,3 f8) per-frame stage positions, lockstep with frames/frame_point_index, NaN row when unknown (never fabricated zeros); `scan_controller` CAPTURE_PHOTO passes `motor.get_position()`; `SCAN_DATA_FORMAT.md` gains `frame_pos_mm` entry + CAPTURE_PHOTO subsection.

- 2026-07-13 — **S2b: Live-update redraw throttle (31ed97b).** `gui/scan_map_view.py` live `update_point` redraws coalesced to ~15 Hz single-shot QTimer; read accessors and terminal paths (scan finish/error, hide/close, export) flush immediately. Closes row 88 ANNOYANCE (full-grid rebuild on EVERY point).

- 2026-07-13 — **E6a: Survey mode mosaic via frame positions (50961c7).** `gui/analysis_panel.py` NEW "Survey" mode — mosaic via `analysis.mosaic_stitch.place_tiles` with mm axes; position ladder `camera/frame_pos_mm` → safety-survey geometry; NaN-position frames render as visible gaps; uncalibrated runs get nominal placement + visible notice; diagnostics MetricGrid row.

- 2026-07-13 — **D0: WorkerThread primitive — GUI-safe teardown by construction (b156cdf).** NEW `gui/worker.py`: `WorkerThread` (terminal signal to bound method, teardown queued to GUI thread by construction; no wait-on-self; GUI-side reaping; ShutdownKind.ABANDON vs MUST_COMPLETE with timeout=loud orphaned+ERROR, never silent). Bias_panel IV-sweep + supply-call workers migrated. Closes row 89 ANNOYANCE (shared worker-lifecycle primitive); ~8 sibling workers (incl. long-lived pollers, may need variant) remain, gated Mary review.

- 2026-07-13 — **E3: Stage↔camera affine self-calibration (fb7ee7c).** `controller/repeatability.py`: pure `plan_affine_staircase` (forward+return per axis ⇒ per-axis backlash observable) + `fit_stage_camera_affine → StageCameraCal`; `RepeatabilityTester.calibrate_affine` — ONE DangerGate confirm for the whole staircase, denial ⇒ no-data result and zero motion (spy-pinned). Neighbor-chained shift tracking; low-quality frames excluded and bridged. Mary APPROVE (gate/motion).

- 2026-07-13 — **E6a: Survey plan builder (d2050e3).** NEW `controller/survey_plan.py` `plan_survey()`: snake raster of MOVE+CAPTURE_PHOTO tiles from `mosaic_stitch.plan_grid` centres; camera-only, fails validation without a camera; survey geometry rides namespaced in `plan.safety['survey']` and round-trips YAML.

- 2026-07-13 — **E2: Metrology frame preprocessing (b5b8051).** NEW `analysis/image_prep.py` `prepare_metrology_roi → PreparedROI` (ROI crop y0,x0,h,w fail-closed; dark/flat; saturation mask on the RAW crop; FFT high-pass; local normalization; quality 0-1). Invalid pixels are mean-filled BEFORE the global FFT blur (one NaN calibration pixel would otherwise NaN-poison the whole frame — test-pinned). `RepeatabilityTester._grab` now preprocesses every frame; `run()` gains `quality_min` with flagged exclusion. Also: B2's writer deviation reviewed + APPROVED (both probe claims reproduced).

- 2026-07-13 — **A5.2b: Sequence pause-dialog guard (6e691fd).** `tct_gui._on_plan_manual_pause` short-circuits while `_sequence_active`: no QMessageBox is constructed; reason → `notify()` + warning log, and the sequence coordinator auto-aborts (cancel queue, abort run, park HV). Non-sequence behavior byte-identical. Integration test ends ABORTED with bias output off.

- 2026-07-13 — **A5.2a: Sequencer-compatibility gate (88f500f).** NEW `controller/sequencer.assert_sequencer_compatible(plan)` — compiles with the executor's own `compile_plan` and rejects blacklisted steps (first entry: `ManualPauseStep`, mid-plan AND trailing — a human-gated pause would wedge an unattended night holding HV, or silently promote PAUSED→FINISHED). Gated at all three entry points: `load_sequence_yaml` (names index+routine), `SequenceRunner.__init__`, `SequenceCoordinator.load` (coordinator stays fully idle on rejection).

- 2026-07-13 — **A5.1: Surgical manual-danger locks (7061e97).** `set_manual_danger_locked(bool)` on MultiBiasPanel (forwards per channel), BiasPanel, MotorPanel: energize/motion-START controls lock during a sequence; per-channel Output OFF, global ALL OUTPUTS OFF and motor STOP stay live AND functional (qtbot-clicked during lock, device call spied — design law 5). Lock composes with the panels' own busy/connection enable logic; replaces A5's container-level `setEnabled`.

- 2026-07-13 — **A5: SequencerPanel + capture_photo palette (1ca5677).** NEW `gui/sequencer_panel.py`: queue table with ladder-correct StatusChips, add/remove/reorder, fail-closed save/load, combined-envelope summary over the hold-3s `ArmLatch`, red-outline Abort. Wired in `tct_gui` (real `park_safe` injected; union gate read-and-discarded — never stored on the panel). Modal error/warn shims rerouted to notify+log while a sequence runs. Rider: planner CAPTURE_PHOTO palette block + `PlanLimits.camera_available` wired from camera-config presence in both construction sites.

- 2026-07-13 — **A4: SequenceCoordinator (c1fc0c2).** NEW `gui/sequence_coordinator.py` (QObject): advances the queue off ScanCoordinator's thread-marshalled `plan_finished`/`plan_error`, mapping the settled state machine to outcome words (ABORTED→"aborted"); FSM recovery CONFIGURED→READY between entries; deep-copied plan snapshots; injectable `park_safe` between entries and at terminals; `sequence_active(bool)` is the manual-lock contract; no failure path leaves it dangling.

- 2026-07-13 — **C3-mini: Hex token + dialog construction-apply (d100650).** `settings_window` parse-error border now uses the `crit` token; the no-inline-hex guard's `_PENDING_SWEEP` became a per-VALUE allowlist (regressions of fixed literals now fail the scan). SettingsWindow and ThemeEditorDialog apply current backdrop+opacity at their own construction (mirrors `_DetachedWindow`).

- 2026-07-13 — **C2: Backdrop settings + fan-out (c66ee05).** `style.py` mirrors the opacity trio: `set/get/apply_window_backdrop(_to)`, QSettings `theme/window_backdrop` (none|mica|acrylic, default none, garbage→none). Apply-order contract: backdrop first, then `setWindowOpacity`. Theme-editor Backdrop combo with live preview, disabled+tooltip when unsupported. Reset to "none" re-applies the theme palette + repolish — deliberately NOT `setPalette(app.palette())`, which would set `WA_SetPalette` and permanently detach the window from app-palette tracking.

- 2026-07-13 — **B2: capture_photo end-to-end (f3b0457).** `ActionType.CAPTURE_PHOTO` → `CapturePhotoStep` (passive, not danger-marked) → validator gate `PlanLimits.camera_available` (default False, fail-closed) → estimator cost → `_run_plan` dispatch (abortable settle → `camera.get_frame()` → writer). NEW additive `HDF5Writer.save_camera_frame(frame)` — probe-proven necessity: a photo-only result through `save_point` crashes on the 2nd frame (zero-size chunk) and zero-backfill-desyncs mixed plans. Writes ONLY /camera tagged with the current point index; never advances `_n_points`. Jonathan sign-off in b5b8051.

- 2026-07-13 — **B1: HDF5 camera honesty (06de0dc).** NEW `camera/frame_point_index` (grows only on real writes; `frames[k] ↔ points[frame_point_index[k]]`), every drop counted+logged (`n_frames_omitted` attr always written when the group exists), zero-backfill removed — a dropped frame can no longer masquerade as a dark frame. NEW `set_camera_calibration(px_per_mm, affine)` camera-group attrs.

- 2026-07-13 — **A3.1: park_safe all channels + engine halt semantics (7b32dc3).** `park_safe()` now runs the connected-gated two-try `_bias_failsafe` on EVERY `bias_channels` entry (a sequence armed on a non-primary channel is no longer parked on the wrong one) + `_motor_stop_safe`; no motion, never raises. Engine: a RAISING PreflightHook → entry FAILED + fail-closed halt; `record_outcome` accepts any word but ONLY the literal "finished" advances — aborted/error/the HDF5 crash sentinel "unknown"/gibberish all halt. Closes Mary's Track-A REQUEST-CHANGES.

- 2026-07-13 — **D3: Fit-quality tiles in the CCE view (419a0a0).** `gui/analysis_panel.py`: MetricGrid row V_dep±σ · Quality (0.7/0.4 bands, "ok" renders quiet normal, not green) · Flags (AMBIGUOUS/NON-MONOTONIC) · Ref-σ with the reference-scatter-only caveat VISIBLE. cce±σ error bars + shaded depletion bracket on the plot. The whole-block `try/except: pass` replaced by structured, logged degradation. Track D complete.

- 2026-07-13 — **D4 rider: baseline_samples wiring (a9ec103).** `device_manager` passes the existing `analysis.baseline_samples` config value into every `ScopeChannelMonitor` construction (no new config key; default 20 unchanged).

- 2026-07-13 — **D4: Reference-channel baseline subtraction (00d53bc).** NEW canonical `analysis/waveform_analysis.correct_baseline()`; `analyse_waveform` (DUT) routes through it bit-identically; `devices/intensity_base.py` carries a byte-for-byte mirror pinned equal by test (layer contract bans devices→analysis imports). REF path now baseline-corrects; the simulated backend injects a nonzero DC ref offset by default so this bug class stays permanently test-visible. Closes the Kings-retro RISK. Companion `00abe9c`: binning-mode comment resolved — classic BFLY is hardware Sum-only (research f284d06), skip-at-INFO is the permanent path.

- 2026-07-13 — **D2: CCE uncertainty (a3449be).** NEW `compute_cce_with_uncertainty(charges_pC, q_ref_pC, charge_sigma_pC=0) → CCEResult` — first-order ratio propagation of reference-channel scatter; honesty flag `q_term_included=False` states that per-point charge repeats are not stored today (sigma is ref-scatter-only, never fake precision). `compute_cce`/`cce_vs_reference` byte-unchanged (bit-exact equivalence test).

- 2026-07-13 — **Wave-0 GUI half: latched trips visible (0f1c012).** `_safe_bias_shutdown` split into two try blocks (a raising ramp can never skip `output_off`); `bias_panel._derive_hv_state` gained a tripped-FIRST branch (`getattr(r,"tripped",None) is True`); `_IVWorker` breaks on a latched trip BEFORE compliance and emits `stopped(str)` → `notify` with distinct trip/compliance reasons. Closed the HV safety gate together with df10f8e (Mary APPROVE, bench 1349 green).

- 2026-07-13 — **D1: Depletion voltage fit (95b27c7).** NEW `analysis/efield_analysis.DepletionFitResult` + `fit_depletion_voltage(v_bias, charge, threshold)` (2-point threshold crossing + quality metrics). Replaces bare estimate in `estimate_depletion_voltage`; fit-quality flag enables GUI conditional rendering. Closes RISK row 87 (Kings retro).

- 2026-07-13 — **E1: Camera Mono16 autoscale + binning Average attempt (f1e1712 + 00abe9c).** `gui/camera_panel.py` Mono16 display autoscale (no uint8 wrap/alias); `set_binning()` now attempts Average mode per BFLY capability (`IsWritable` check). Classic BFLY SN 19112408 reports Sum-only (comment added, permanent skip-at-INFO). Closes RISK row 48 (Kings retro: display truncation-wrap + binning white-screen).

- 2026-07-13 — **C2: Backdrop trio integration (c66ee05).** `style.py` backdrop trio (material + opacity → glass-amount tokens); `theme_editor.py` backend combo for preset selection; QSettings key `theme/window_backdrop` (none|mica|acrylic, default none, garbage→none). Persisted with `theme/window_opacity` slider. C1+C2 form complete backdrop feature.

- 2026-07-13 — **C1: Win11 DWM Mica/Acrylic material (df43ca9).** NEW `gui/backdrop.py` (DWM capability API, all ctypes isolated, fail-safe version check + fallback, offscreen/test no-op). Material applied via QSS stylesheet + DWM calls. Persisted via QSettings key `theme/window_backdrop` (none|mica|acrylic, default none, garbage→none). Closes BLOCKER (pre-v5 ratification requirement).

- 2026-07-13 — **B1: HDF5 camera honesty (06de0dc).** `data/hdf5_writer.py` NEW `camera/frame_point_index` dataset (frame→point map), `n_frames_omitted` attribute (count of silently-dropped shape-mismatched frames). `camera/frames` never zero-padded. Fixes RISK row 47 + 86 (Kings retro: silent camera-frame drops, untracked data gap).

- 2026-07-13 — **A3: ScanController.park_safe() public seam (ba6128b).** Public API for safe shutdown: halts motion, discharges HV (primary channel only), resets state. Complements the executor's _bias_failsafe; callable from GUI danger-gate handlers. Controller-tier recovery seam.

- 2026-07-13 — **A2: SequenceRunner queue engine (e2ba013).** NEW `controller/sequencer.py` (pure plan-step executor, no hardware I/O, no Qt, fail-closed halt on error). `SequenceRunner` processes compiled `Step` list; `PreflightHook` seam for custom pre-execution; YAML-serializable persistence. Decoupled from executor logic for reusability + testability. Closes design-law 5 (deterministic step replay).

- 2026-07-13 — **A1: Combined-queue envelope (f83b184).** `controller/arm_envelope.py` `ArmedEnvelope.routine_names: list[str]` field (multi-routine tracking). `envelope_from_plan` now builds combined queue envelope from plans that use sequencer. Design-law 5 update: unified envelope scope for multi-routine scans.

- 2026-07-13 — **StateMachine.transition() now atomic under RLock (26bcf95).** check-then-act race fixed: transition is now protected by RLock; callbacks invoked outside lock; ValueError-on-race is documented contract. Eliminates the reported terminal-state mislabel under xdist contention.

- 2026-07-13 — **BiasChannel.output_on() renamed to enable_output(); read-only is_output_on property added (034c176).** Closes the API footgun: `if bias.output_on:` was always true (bound method); now truthiness trap is unwritable. Guard test `test_bias_api_guard.py` prevents regression.

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
- 2026-07-12 — **7ac5304 (fix): VISA deadlock head #2 — worker.deleteLater on worker thread.** Extended `_ScanReaper` pattern: `_reap()` DirectConnection re-homes finished worker to GUI thread via `moveToThread(app.thread())` before `deleteLater()` to prevent `~QObject` (Shiboken GIL re-entry + connection-pool mutex) from running off worker thread. CONNECTION ORDER on thread.finished is load-bearing: DirectConnection re-home MUST be wired BEFORE queued _reap in track(). Invariant recorded: **panel worker teardown MUST remain blocking quit()+wait() on GUI thread** (parks GUI thread with GIL released, preventing ABBA); do NOT convert panel workers to async/non-waiting teardown without moving destruction GUI-side first.

- 2026-07-12 — **a69af95 (fix): finished-slot ordering.** Confirmed DirectConnection re-home on thread.finished must precede the queued _reap slot; ordering enforced by connection sequence in track(). Mary review validated the dependency.

- 2026-07-12 — **e45496d (feat): first QML cockpit panel — ScanStatusStrip.** NEW `gui/qml/MetricTile.qml` (Theme-bound reusable tile: title/value/unit/caption/accent/stale/compact) and `gui/qml/ScanStatusStrip.qml` (Flow of 5 tiles: State/Progress/ETA/Elapsed/Scan; bound to runState context property, pure view, 3-layer law). Integrated into Shell.qml as third chrome strip; chrome height 96 → 204 px, `qml_shell.py` setFixedHeight(204).

- 2026-07-12 — **f8f6a00 (feat):** Design-system law 5 arm-envelope model. NEW `controller/arm_envelope.py`: `ArmedEnvelope` (frozen enumerated authorization: bias channels, HV min/max, ramp shape, motion bounds, human-readable summary); `derive_envelope`/`envelope_from_plan` (build from compiled plan, byte-identical to executor's seams); `ArmedEnvelopeGate` (DangerGate: auto-approve in-envelope actions, fail-closed deny outside/expired). `config_validator` checks slow_control channel warn/alarm thresholds (low ≤ high). `scan_controller.execute_plan(plan, gate)` new slot; slow_control feeds per-point WARN/ALARM status; `_move_action` and `_acquire_core` ensure derived bounds match execution.

- 2026-07-12 — **0f0157f (feat):** D0 design-system tokens (quiet-nominal, type, render). `style.py`/`panel_kit.py`/`status_widgets.py`/`qml_theme.py` updated with new palette and constants (SIM_PURPLE, ERROR_ORANGE). Type scale enhancements for compact/expanded rendering modes.

- 2026-07-12 — **7cf18ed (refactor):** D1 Planner reference and cosmetic restyle. PlannerPanel cosmetic updates for consistency with design system. No functional change.

- 2026-07-12 — **4498040+eafff38 (feat):** Design-system law 5 arm-latch widget. NEW `gui/arm_latch.py`: `ArmLatch` two-step gesture well (hold-3s or press-twice, ~10s auto-disarm, instant-stop abort separate). Pure view: no hardware I/O, no controller refs, renders envelope summary. Signals: arm_started, armed, disarmed, execute_requested. `PlannerPanel.execute_plan_requested(plan, gate)` signal; `ScanCoordinator.execute_plan` slot. QSettings key 'planner/arm_latch' (persist armed state). 30s envelope freshness window in tct_gui.

- 2026-07-12 — **9fe849a+0d21c1c (refactor):** Stage-view theme tokens + motor panel wiring. `stage_view.py` tokens-only (no inline hex). Motor panel wiring updates for law-5 compliance.

- 2026-07-12 — **76f86ef+1479554 (test):** Migration-invalidated tests updated. Test suite updated post-migration; all previously-passing tests restored.

- 2026-07-12 — **8a2ee7d/3235347 (docs):** V5 artifact suite in `artifacts_claude/v5/` (overview + 11 panels + theme playground + mosaic with build.py assembler) + `docs/design/feature_requests_v5.md` backlog. Council decision evidence.

- 2026-07-12 — **10237fb/af58400 (docs):** V5 council seats complete: Codex/Noah/Jonathan/Paul/Abel + Adam gap notes + `docs/design/panel_inventory_v5.md` + `docs/research/apple_vibrancy_qt_feasibility.md` research note.

- 2026-07-12 — **5730644 (fix/safety):** `ScanController._refuse_if_active()` fail-closed guard on all four start entry points (start/start_plan/start_z_focus_scan/start_voltage_scan); `scan_coordinator.start_scan` now surfaces RuntimeError on rejection.

- 2026-07-13 — **84d3a1f (docs): Kaya-approved master roadmap into the repo.** NEW `docs/ROADMAP_MASTERPLAN.md` (capability spine, 8-domain staged roadmap, seed strategy). CLAUDE.md Fable-tier governance (judgment beats Opus→Fable; architecture agents always Fable); `docs/CODEX_QUEUE.md` S2 route. Roadmap ratifies v5 cockpit shell + metrology + survey + affine-placement gates.

- 2026-07-13 — **d0f650f (docs): Codex bounce R1 integrated into the roadmap.** CapabilityBinding staged lifecycle + transport reservation, per-U-stage QML safety event-authority gate, P0' per-point oracle, per-point timing + atomic completion marker, dual-shell QSettings namespacing, PORT1 M/L, D1a/D1b split; 2 items ⚑-flagged for Kaya decision.

- 2026-07-13 — **a028c87 (docs): Codex bounce R2 cleanup pass.** 5 text reconciliations; finalization protocol COMPLETE; both ⚑ items reclassified as forced (Kaya chooses shape, not whether).

- 2026-07-13 — **327026d (docs/research): B1 metrology mechanics facts.** Printer-stage reality: microstep sag under load, belt ±5µm, thermal 1.3µm/°C; reticle shortlist $17–$955; ISO-230-2-style protocol; 18 sources. Feeds `metrology_feasibility.md` (B2).

- 2026-07-13 — **f6c569f (docs/design): C1 planner_routines_v2.md proposal.** 7 candidate axes incl. crew-missed REPEAT; 10-routine gallery, R1–R6 = P2 corpus fixtures at zero implementation; found the nested params['wavegen'] validation gap → P0' scope amended in the roadmap.

- 2026-07-13 — **efad307 (docs): PLATFORM_SEED.md v0.1.0-draft.** Mamoru-verified lift manifest, 22 claims verified + 4 count fixes; §6 flags remote_control_plan.md "Trusted-operator" tension with safety-is-local — remote ruled OUT of the seed pending Kaya/Mary.

- 2026-07-13 — **1927377 (docs/research): B2 metrology_feasibility.md + B3 BENCH_CHECKLIST §12 protocol.** Error budget as f(M); verdict: camera-MEASURED metrology is the realistic class; 2µm only as relative claim, never open-loop. §12a–d protocol (mechanics reality → reticle shortlist, calibration workflow, repeatability stats, drift series). Adopted orphaned `dwm_backdrop_blur_recipe.md` (Prometheus, was never staged with the Echtglas beat).

- 2026-07-13 — **7a55d03 (fix/safety): PI lock-free emergency stop (#24).** PI C-663 StopAll/#24 refined: one-character real-time byte takes no io_lock (no lock acquisition overhead). Complements guarded_exchange transport-lock invariants (commit 4a89647 below). Tests: `tests/test_motor_transport_lock.py` contract 3 (STOP never queued). Research: `docs/research/pi_gcs_stop_semantics.md`.

- 2026-07-13 — **3930f58 (fix/safety): DRS4 board-transport lock.** DRS4 evaluation board SDK handle shared by scan acquisition + scope monitor is now exclusively serialized by BaseDevice.io_lock (re-entrant RLock). Previously unguarded—monitor read could land inside acquirer's domino exchange. Same bug class as pre-fix PIMotorStage. NEW test `tests/test_drs4_lock.py` (identity, no-interleaving, vacuity assertions); Bucket B contract test.

- 2026-07-13 — **c52691f (fix): settings sim-frame display + to_dict round-trip.** `_BiasSection` gains simulated-backend UI frame (sim_channel_count spinbox + sim_channel spinbox, auto-clamped); to_dict now emits complete config dict (was silently dropping sim_channel_count/channel on save). NEW test `tests/test_bias_section_sim_channel_count.py` (load/round-trip/silent-drop regression). Closes RISK row 1 + 12 (Kings retro: GUI setting inaccessible, config-eating bug).

- 2026-07-13 — **7616692 (perf): motor panel cached _last_pos.** MotorPanel._poll_position now caches last-read position + timestamp; unchanged position skips UI rebuild (eliminates stutter during jogs). No functional change; QThread poller pattern unchanged.

- 2026-07-13 — **b323bb4 + 10b8c6c (docs/research): PI GCS stop semantics + SCPI discovery notes.** NEW `docs/research/pi_gcs_stop_semantics.md` (GCS 2.0 StopAll/#24 is lock-free, single-character real-time byte, completes in one exchange, verified against GCS reference manual). NEW `docs/research/scpi_capability_discovery.md` (VISA/SCPI capability query patterns for oscilloscope channel count, averaging limits, trigger modes; live-verified on TBS1052C; sourced from manual 077-1691).

- 2026-07-13 — **b3d0827 (docs/design): guarded_exchange pattern.** NEW `docs/design/guarded_exchange.md` (three-property invariant: identity, no-interleaving, stop-exempt; applied to GRBL RLock io_lock + PI pi_serialisation lock + DRS4 board io_lock). Design note documents the transport-lock contract pinned by tests/test_motor_transport_lock.py, test_drs4_lock.py.

- 2026-07-13 — **a75dfba (feat): bias_supply.sim_channel_count config key.** NEW config key `bias_supply.sim_channel_count` (int 1..16, optional, default 1, SIMULATION-ONLY — warning+ignored on real backends). `bias_supply.channel` [primary index] must be < sim_channel_count for simulated backend, validated by `config_validator`. Addresses "can't set multi-channel sim mode" gap. Added to `docs/config_keys.md`; settings UI frame added in c52691f.

- 2026-07-13 — **fbf94d8 (fix/safety): PI disconnect stops first.** PIMotorStage.disconnect() now calls stop() before close (same pattern as GRBLMotorStage). Ensures no motion persists if connection is yanked mid-move. Closes "dirty disconnect" hazard class.

- 2026-07-13 — **4a89647 (fix/safety): transport locks — BaseDevice.transport_lock public API.** NEW `BaseDevice.transport_lock` property (public, re-entrant RLock) that callers acquire before exclusive transport use; stop paths exempt. GRBL uses device.transport_lock (same RLock its io_lock acquires). PI introduces pi_serialisation RLock (device.transport_lock as public seam). All drivers now follow: one transport lock per device, no interleaving with concurrent I/O, stop is lock-free. Tests: `tests/test_motor_transport_lock.py` (identity, no-interleaving, STOP-never-queued contracts). Closes RISK row 4 (Kings retro: latent PIMotorStage/poller race).

- 2026-07-13 — **4f10253 (feat): per-leaf snapshot memo + routine corpus gate test.** ScanPlan.compiler now deep-copies params dict for each leaf context (ensures `params['bias']` mutations in one step don't leak to sibling steps). Compiler generates immutable-intent memo. NEW test `tests/test_routine_corpus.py` (Bucket A gate: ≥5 saved routines byte-identical, ScanPlan.load_yaml validates, 0 ERROR/0 WARNING under bench-realistic limits). Closes ROADMAP risk #6 (plan-grammar migration / corpus drift).

- 2026-07-13 — **f23f73a (docs): CAPABILITY_MODEL v0.3 finalization.** Capability model finalized per Kaya's rulings: option (c) class-floor + monotone override (safety-routing), multi-channel HV naming `bias.ch{n}.voltage`, per-channel ID tracking. Ready for P0' bootstrap.

- 2026-07-13 — **f84f1e0 (docs): CAPABILITY_MODEL v0.2 (Kaya ratified).** Capability binding design locked: two-step authorization (plan-compile arm envelope + runtime re-validate); per-domain class assignments (motion/HV/imaging/metrology/control); safety-routing shape decision owner Kaya per DECISIONS.md entry.

- 2026-07-13 — **b040753 (docs): S2 manifest v0.2 Mary-ratified.** S2 (ScanViewerPanel integration + design-system rollout) specification v0.2 approved and landed. Complete feature map + acceptance gates + integration touchpoints. Gates on lab verification (BENCH_CHECKLIST §6a–c).

- 2026-07-13 — **3c6bb48 (test): template parity + guard test.** NEW `tests/test_template_parity.py` (WaveformTemplate JSON parity check). Template-change guard ensures no silent schema drifts. Part of WaveformGenerator feature hardening.

- 2026-07-13 — **5915aa1 (fix/safety): C10 fixes — deep-copy params, non-finite fail-closed, bias-settle dwell.** (1) ScanPlan.compiler deep-copies params per leaf (4f10253 below, separate commit for isolation). (2) HDF5 serialization raises on non-finite values (NaN/Inf → JSON-incompatible; fail-closed instead of silent nan=True allow). (3) Bias settle time now respects config dwell override (was hardcoded 0.2 s). Closes C10 wave acceptance gates.

- 2026-07-13 — **54baf62 (docs): CAPABILITY_MODEL v1.0-rc.** Capability model finalized per Kaya-approved roadmap (ROADMAP_MASTERPLAN.md). Normative spec ready for P0' bootstrap and D1a implementation.

- 2026-07-13 — **9ba1aaf (docs): MIT LICENSE + seed clause.** Project license added; PLATFORM_SEED.md v0.1.0-draft with Mamoru verification (22 verified claims, 4 count fixes). Safety-routing shape and trusted-operator contradiction pending Kaya decision.

- 2026-07-13 — **a7dca3f (chore): Phase 0.5 merge — main = trunk (polish-freeze tag).** `design/cockpit-v5 → main` merge executed; bench-green evidence in merge message (1870 passed, 2 skipped, 1 xfailed, 24:31, exit 0). Live codebase now at `main @ a7dca3f`; `design/cockpit-v5` retires after in-flight work (D1b adapters/registry, gate #4) lands. Kaya ratified 5 decisions on 2026-07-13 (DECISIONS.md records them).

- 2026-07-13 — **b77d92c (feat): G0 guarded-exchange base machinery in devices/base.py.** NEW `_guarded_exchange` (T1 single-primitive), `_guarded_group` (T1g bounded group), `_probe_exchange` (T3 non-blocking busy sentinel). No T2 helper permitted (law of least surprise). Re-entrancy via RLock. `__init_subclass__` override detector REGISTERS unconverted drivers (legal until G1/G2), warns on synthetic overrides. NEW Bucket B contract test `tests/test_guarded_exchange_base.py` (identity, no-interleaving, re-entrancy, non-vacuous registry). Design: `docs/design/guarded_exchange.md` §3/§5-§6.

- 2026-07-13 — **208207e (feat): NEW package TCT_app/capabilities/ — pure-data model (D1a).** NEW `capabilities/model.py` (stdlib-only, zero Qt, frozen dataclasses: CapabilityDescriptor, HVSource, Motion3D, FrameSource, ReadableChannel, SafetyClass, Operation, ReadbackPolicy). Normative spec: `docs/CAPABILITY_MODEL.md` v1.0-rc. NEW Bucket A test `tests/test_capability_model.py` (111 tests: model struct, version, aliases, purity contract, AST layer check). Adapters + registry in progress (D1b).

- 2026-07-13 — **4bb82d7 (feat): arm→start bound (180 s) live in production.** `ArmedEnvelopeGate.is_expired()` now checks monotonic timestamp (expiry_seconds =~ 180 on derivation). Three distinguishable deny reasons: expired, outside bounds, never armed. Plumbed in `ScanController.start_plan()` pre-flight check; fail-closed, surfaces loud denial message to operator.

- 2026-07-13 — **665319e (fix/safety): armed-envelope expiry bounds arm→start.** Per-ramp clock removed from gate logic (was stale on per-confirm re-eval). Expiry bounds the human intent (derivation→authorization window ~30 s ArmLatch countdown + 180 s arm→start). Three distinguishable deny messages: expired, out-of-bounds, not-armed. Tests: `tests/test_arm_envelope.py` §expiry paths + `tests/test_plan_executor.py` gate pre-flight + `tests/test_sequence_coordinator.py` per-entry re-arm. Closes Kings retro D2 (stale envelope expiry unplumbed).

- 2026-07-04 — Initial bookkeep created from source inspection (main, tct_gui,
  state_machine, scan_controller, device_manager, base device, hdf5_writer,
  SCAN_DATA_FORMAT.md). Some sections marked TODO for deepening.
