# Test bucket map — the [A-green] gate's named artifact

> Gate-enforcement deliverable for `docs/ROADMAP_MASTERPLAN.md`
> §"Gate enforcement (Loki CRITICAL-2 + Mary BLOCKER-2)". This file makes the
> `[A-green]` gate **machine-checkable BEFORE it is first invoked**: it is the
> single source of truth for which test files must survive the capability/QML
> migration byte-identical, and `.claude/check_bucket_a.ps1` parses the Bucket A
> table below to enforce it.

The A/B/C/D classification is the ratified ground truth from the coupling
analysis. Every file listed here was verified to exist in `TCT_app/tests/` on
2026-07-13 (updated 2026-07-13 night) — **no drift, no missing files, nothing invented.** Counts:
**A = 49, B = 21, C = 42, D = 5 (117 total test files).**

| Bucket | Meaning | Migration behavior | Gate |
|---|---|---|---|
| **A** CORE-PURE | GUI-free logic (controller/devices/analysis/data), zero Qt widgets | Survives migration **byte-identical** | `[A-green]`: files unchanged + suite green on every stage |
| **B** CONTRACT | Safety/wiring contracts that pin a boundary; touch Qt but assert a contract | Rehosted GUI-half, contract preserved | Named per-stage contract suites |
| **C** QWIDGET-PINNED | Bound to the classic QWidget panels/theme/shell | Reclaimed to viewmodels (U1) or retired as panels port | Behavior-equal review at reclaim |
| **D** QML/HYBRID | QML shell / viewmodel tests | Grow with the QML branch | Per-panel qml-boot smoke |

---

## Bucket A — CORE-PURE (47 files)

These are the **[A-green] gate**: ~15k LOC of GUI-free logic that must run green
**unmodified** on every capability/QML migration stage. `check_bucket_a.ps1`
parses the table between the two HTML markers below (they are load-bearing —
do not remove them). One file per row; the filename cell is the parse target.

<!-- BUCKET_A_START -->
| # | Test file | Under test (why core-pure) |
|---|---|---|
| 1 | `test_driver_truth.py` | device `*_base.py` ABC driver-contract truth |
| 2 | `test_waveform_generator.py` | wavegen driver + simulated backend |
| 3 | `test_plan_executor.py` | `ScanController` plan execution over sim backends |
| 4 | `test_state_fuzz.py` | `StateMachine` random-walk fuzzer (zero Qt) |
| 5 | `test_mosaic_stitch.py` | analysis mosaic stitching math |
| 6 | `test_reconnect_liveness.py` | device reconnect / stale-green health policy |
| 7 | `test_fault_injection.py` | mid-scan fail-safe (safety rule 5) |
| 8 | `test_fault_injection_legacy.py` | legacy fault-injection fail-safe paths |
| 9 | `test_affine_selfcal.py` | affine self-calibration |
| 10 | `test_trip_detection.py` | HV trip detection failsafe |
| 11 | `test_arm_envelope.py` | `ArmedEnvelope` enumeration / unknown-kind denial |
| 12 | `test_plan_compiler.py` | `plan_compiler` Step emission |
| 13 | `test_plan_parity.py` | plan-vs-legacy execution parity |
| 14 | `test_plan_estimate.py` | `plan_estimate` runtime / point counts |
| 15 | `test_plan_from_config.py` | `plan_from_config` builder |
| 16 | `test_scan_plan_validator.py` | validator fail-closed checks |
| 17 | `test_survey_plan.py` | survey plan geometry |
| 18 | `test_sequencer.py` | sequencer compatibility + queue safety |
| 19 | `test_repeatability_gate.py` | repeatability gating |
| 20 | `test_run_outcome.py` | run outcome / `abort_reason` contract |
| 21 | `test_slow_control_policy.py` | WARN safe-hold / ALARM fail-safe policy |
| 22 | `test_scan_bias_channel.py` | bias channel scan |
| 23 | `test_bias_simulation_mode.py` | bias supply simulation mode |
| 24 | `test_bias_multichannel.py` | bias multichannel |
| 25 | `test_bias_polarity.py` | HV polarity gating |
| 26 | `test_bias_api_guard.py` | `output_on` -> `enable_output` footgun invariant |
| 27 | `test_bias_and_calibration.py` | bias + calibration |
| 28 | `test_config_validator.py` | `config_validator` entries |
| 29 | `test_data_writer.py` | `hdf5_writer` data-format contract |
| 30 | `test_device_manager.py` | `DeviceManager` lifecycle / state gates |
| 31 | `test_state_machine.py` | `StateMachine` lifecycle |
| 32 | `test_metrology_report.py` | metrology report generation |
| 33 | `test_map_slice.py` | map slicing |
| 34 | `test_scan_grid.py` | scan grid geometry |
| 35 | `test_image_prep.py` | image preparation |
| 36 | `test_cce.py` | CCE physics conversion |
| 37 | `test_efield_fit.py` | E-field fit |
| 38 | `test_waveform_analysis.py` | waveform analysis (ToT / charge) |
| 39 | `test_camera_calibration.py` | camera calibration math |
| 40 | `test_sensor_align.py` | sensor pose alignment (vision, headless) |
| 41 | `test_yaml_persist.py` | YAML persistence round-trip |
| 42 | `test_motor_frame_contract.py` | motor frame contract |
| 43 | `test_motor_grbl_mock.py` | GRBL mock driver |
| 44 | `test_oscilloscope_preamble.py` | scope preamble parsing |
| 45 | `test_oscilloscope_robustness.py` | scope robustness |
| 46 | `test_oscilloscope_wedge_recovery.py` | scope CURVE? wedge recovery |
| 47 | `test_camera_blackfly.py` | FLIR Blackfly simulated backend |
| 48 | `test_routine_corpus.py` | routine corpus freeze gate (P2-entry) |
| 49 | `test_capability_model.py` | capability spine data model (D1a, stdlib-only) |
<!-- BUCKET_A_END -->

### The exact [A-green] run command

From `TCT_app\` (PowerShell), the canonical Bucket-A run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe -m pytest tests/test_driver_truth.py tests/test_waveform_generator.py tests/test_plan_executor.py tests/test_state_fuzz.py tests/test_mosaic_stitch.py tests/test_reconnect_liveness.py tests/test_fault_injection.py tests/test_fault_injection_legacy.py tests/test_affine_selfcal.py tests/test_trip_detection.py tests/test_arm_envelope.py tests/test_plan_compiler.py tests/test_plan_parity.py tests/test_plan_estimate.py tests/test_plan_from_config.py tests/test_scan_plan_validator.py tests/test_survey_plan.py tests/test_sequencer.py tests/test_repeatability_gate.py tests/test_run_outcome.py tests/test_slow_control_policy.py tests/test_scan_bias_channel.py tests/test_bias_simulation_mode.py tests/test_bias_multichannel.py tests/test_bias_polarity.py tests/test_bias_api_guard.py tests/test_bias_and_calibration.py tests/test_config_validator.py tests/test_data_writer.py tests/test_device_manager.py tests/test_state_machine.py tests/test_metrology_report.py tests/test_map_slice.py tests/test_scan_grid.py tests/test_image_prep.py tests/test_cce.py tests/test_efield_fit.py tests/test_waveform_analysis.py tests/test_camera_calibration.py tests/test_sensor_align.py tests/test_yaml_persist.py tests/test_motor_frame_contract.py tests/test_motor_grbl_mock.py tests/test_oscilloscope_preamble.py tests/test_oscilloscope_robustness.py tests/test_oscilloscope_wedge_recovery.py tests/test_camera_blackfly.py -q
```

The bash/CI twin (from `TCT_app/`):
`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest <same 47 files> -q`.

### Target branch and where the green tail is recorded

- **Trunk = `main @ a7dca3f` (Phase 0.5 executed, 2026-07-13, merge bench-green with `polish-freeze` tag).** The live codebase is now on `main`. `design/cockpit-v5` retires after in-flight work lands (D1b adapters/registry, gate #4 bench run).
- **The green tail is recorded in `.claude/session_state.md`** (the beat
  ledger — the "HEAD / TRUTH" section carries the last green bench set + pass
  count). Each `[A-green]` invocation appends its pytest output tail (pass
  count + duration + reviewed SHA) there; Mamoru audits its presence at phase
  gates.

### Machine-checkable diff gate

`.claude/check_bucket_a.ps1` reads the Bucket A file list **from the table
above** (parsing between the `BUCKET_A_START`/`BUCKET_A_END` markers — no
duplicated list) and asserts
`git diff --name-only <base>..HEAD -- <Bucket-A paths>` is **EMPTY**, exiting 1
with the offending files otherwise. `.claude/beat_status.ps1` reminds you to run
it before roadmap-stage commits, and Mamoru standups check it. A vacuous pass is
guarded: if the parse yields zero files, the script errors instead of passing.

---

## Bucket B — CONTRACT (20 files)

Safety / wiring contracts. They touch Qt but assert a boundary that must survive
the migration; the GUI half is rehosted, the contract is preserved (many map 1:1
into `SAFETY_NORMATIVE_TESTS.md`).

| # | Test file | Contract pinned |
|---|---|---|
| 1 | `test_bias_danger_gate.py` | bias `DangerGate` decline/refuse |
| 2 | `test_motor_danger_gate.py` | motor `DangerGate` decline/refuse |
| 3 | `test_bias_kill_switch_escalation.py` | kill-switch escalation ladder (+ stays-escalated) |
| 4 | `test_classic_loop_safety.py` | classic loop failsafe (HV-at-zero) |
| 5 | `test_scan_coordinator.py` | scan-coordinator sequencing / run-state gating |
| 6 | `test_sequence_coordinator.py` | sequence-coordinator gating |
| 7 | `test_arm_latch.py` | arm latch — abort never latched |
| 8 | `test_scan_viewer_wiring.py` | scan-viewer wiring contract |
| 9 | `test_stage_view_frame_contract.py` | stage-view frame contract |
| 10 | `test_analysis_panel_load_run.py` | analysis-panel load-run contract |
| 11 | `test_analysis_panel_survey.py` | analysis-panel survey contract |
| 12 | `test_analysis_panel_pose_align.py` | analysis-panel pose-align contract |
| 13 | `test_scope_measurements.py` | scope measurements contract |
| 14 | `test_oscilloscope_channel_count.py` | scope channel-count contract |
| 15 | `test_layer_contracts.py` | architecture layer contracts (AST) |
| 16 | `test_gui_thread_watchdog.py` | GUI-thread watchdog |
| 17 | `test_run_bg_busy_feedback.py` | run background busy feedback |
| 18 | `test_bias_all_off.py` | bias all-off contract |
| 19 | `test_motor_transport_lock.py` | motor transport-lock contract (GRBL + PI serialization) |
| 20 | `test_drs4_lock.py` | DRS4 board-transport lock contract |
| 21 | `test_guarded_exchange_base.py` | guarded-exchange base machinery (G0, devices/base.py) |

---

## Bucket C — QWIDGET-PINNED (42 files)

Enumerated from disk = every remaining `tests/test_*.py` not in A/B/D. Bound to
the classic QWidget panels / theme engine / shell; U1 reclaims the high-value
third into viewmodel contract tests, the rest retire or port as panels migrate.

| # | Test file | Pinned to |
|---|---|---|
| 1 | `test_analysis_panel_motion.py` | analysis panel (widget) |
| 2 | `test_app_settings.py` | app settings / QSettings shell |
| 3 | `test_apply_theme_lifetime.py` | theme engine lifetime |
| 4 | `test_backdrop.py` | DWM backdrop compositor |
| 5 | `test_bias_panel_motion.py` | bias panel (widget) |
| 6 | `test_bias_trip_visibility.py` | bias-panel latched-trip visibility (S2 GUI-half port) |
| 7 | `test_camera_panel_worker.py` | camera panel worker |
| 8 | `test_capture_onscreen_guard.py` | onscreen-capture guard |
| 9 | `test_cockpit_batch_b_panels.py` | cockpit batch-B panels |
| 10 | `test_intensity_panel.py` | intensity panel |
| 11 | `test_laser_panel_output_state.py` | laser panel output state |
| 12 | `test_laser_panel_worker.py` | laser panel worker |
| 13 | `test_monitor_panel.py` | monitor panel |
| 14 | `test_motion.py` | motion helpers (widget-side) |
| 15 | `test_motion_kit.py` | motion kit widgets |
| 16 | `test_motor_panel_reload.py` | motor panel reload |
| 17 | `test_no_inline_hex_gui.py` | GUI no-inline-hex style guard |
| 18 | `test_panel_kit.py` | panel kit primitives |
| 19 | `test_panel_kit_cockpit.py` | panel kit cockpit variant |
| 20 | `test_panel_kit_rollout_batch1.py` | panel kit rollout batch 1 |
| 21 | `test_panel_kit_rollout_batch3.py` | panel kit rollout batch 3 |
| 22 | `test_planner_panel.py` | planner panel (drag&drop tree) — U1 reclaim target |
| 23 | `test_scan_map_view.py` | scan-map view (pyqtgraph) — U1 reclaim target |
| 24 | `test_scan_viewer_panel.py` | scan-viewer panel — U1 reclaim target |
| 25 | `test_scope_panel_yaml_persist.py` | scope panel YAML persistence |
| 26 | `test_sequencer_panel.py` | sequencer panel — U1 reclaim target |
| 27 | `test_settings_window_panel_kit_rollout.py` | settings window panel-kit rollout |
| 28 | `test_settings_window_visa_scan.py` | settings window VISA scan |
| 29 | `test_settings_window_visa_scan_deadlock.py` | settings window VISA-scan deadlock |
| 30 | `test_settings_window_yaml_persist.py` | settings window YAML persistence |
| 31 | `test_shell_cockpit_v5.py` | cockpit-v5 shell composition |
| 32 | `test_status_widgets.py` | status widgets / status bus UI |
| 33 | `test_style_hover_hotpath_guard.py` | style hover hot-path guard |
| 34 | `test_style_no_label_box.py` | style no-label-box guard |
| 35 | `test_suite_isolation.py` | test-suite isolation harness |
| 36 | `test_theme_editor.py` | theme editor |
| 37 | `test_theme_fanout_completeness.py` | theme fan-out completeness |
| 38 | `test_ui_monkey.py` | UI monkey denial ruleset (QTest harness; ~20% portable to QML walker) |
| 39 | `test_worker_primitive.py` | `WorkerThread` primitive (Qt teardown) |
| 40 | `test_bias_section_sim_channel_count.py` | bias settings widget sim-channel config |
| 41 | `test_no_render_to_texture_children_in_gui.py` | RTT-widget child tree guard (AST + dynamic) |
| 42 | `test_panel_glass_rollout.py` | glass Z-ladder role census + hazard-exclusion gates (builds real panels) |

---

## Bucket D — QML / HYBRID (5 files)

QML shell + viewmodel tests. These grow with the `ui-qml-migration` branch and
get the per-panel qml-boot smoke gate.

| # | Test file | Under test |
|---|---|---|
| 1 | `test_qml_shell.py` | QML shell boot / soft-reload survival |
| 2 | `test_qml_scan_status.py` | QML scan-status surface |
| 3 | `test_qml_theme_specular_sync.py` | QML theme specular live-sync |
| 4 | `test_run_state_viewmodel.py` | run-state viewmodel (no controller ref) |
| 5 | `test_scope_viewmodel.py` | scope viewmodel |

---

## Maintenance

When a test file is added, moved, or reclassified, update this map in the same
beat and re-run `check_bucket_a.ps1` (a new Bucket-A file must be added between
the markers, not left implicit). Mamoru's drift sweep cross-checks the disk
`tests/` listing against these four tables; a file present on disk but absent
from all four buckets is drift and must be triaged into a bucket.
