# SAFETY_NORMATIVE_TESTS.md — the 1:1-port manifest

| | |
|---|---|
| **Version** | v0.1-draft |
| **Date** | 2026-07-13 |
| **Status** | awaiting Mary ratification (S2 exit) → Kaya (personal gate) |
| **Author** | Abel (acquisition-dev), roadmap stage S2 |
| **Companions** | `docs/ROADMAP_MASTERPLAN.md` §Safety / §UI · `docs/test_bucket_map.md` (bucket ground truth) · future `docs/SAFETY_CONSTITUTION.md` (S0) |

This is the manifest of every **safety-NORMATIVE** test in `TCT_app/tests/`:
the tests that enforce a hardware-safety rule, an interlock, a danger gate, or
a fail-safe path, and therefore must survive the capability/QML migration
**1:1** — the assertion may never weaken, whatever happens to its host file.
Every test name below was verified to exist on disk on 2026-07-13 (grep-able;
symbol-anchored, no line numbers).

## Port dispositions (exactly one per row)

- **byte-identical** — bucket-A file: the file must never change; the
  `[A-green]` gate (`.claude/check_bucket_a.ps1`) enforces it mechanically.
- **GUI-half-rehost** — the logic assertion survives verbatim; the widget half
  is re-hosted against the QML/viewmodel surface (or against a retained
  QWidget safety control from the roadmap's NEVER-migrates list).
- **QML-walker** — the QTest harness retires; the test is rewritten as a
  QML-item walker with the **denial ruleset preserved**.

Safety classes: **MOTION** (stage/homing), **HV** (bias supply), **EMITTING**
(laser trigger / wavegen output), **gate** (confirmation/refusal path),
**fail-safe** (error → hardware-safe + data preserved). Rows may carry more
than one.

"whole-file" rows: every test in the file is normative-or-supporting and the
file ports as a unit. "subset" rows: only the named tests are normative; the
rest of the file is functional regression (still bucket-protected where
applicable).

---

## The manifest

| Test file :: test name (or whole-file) | Safety property enforced | Class | Bucket | Port disposition | Migration notes |
|---|---|---|---|---|---|
| **— Roadmap-required starting set —** | | | | | |
| `test_arm_envelope.py` :: whole-file (24 tests, incl. `test_out_of_range_voltage_denied`, `test_wrong_channel_denied`, `test_out_of_bounds_move_denied`, `test_move_on_unarmed_axis_denied`, `test_unknown_danger_kind_denied`, `test_expiry_denies`, `test_out_of_envelope_bias_run_aborts_failsafe`) | `ArmedEnvelopeGate` is fail-closed: auto-approves only actions provably inside the plan-derived envelope; denies wrong channel, out-of-range V, out-of-bounds/un-armed-axis moves, unknown kinds, and past-expiry; out-of-envelope runs abort with the HV fail-safe end-to-end. | HV / MOTION / gate | A | **byte-identical** | Named by the roadmap as the bucket-A anchor of the S2 set. Sequence-union envelope tests included (`test_sequence_gate_approves_plan2_action_denies_outside_union`). |
| `test_bias_danger_gate.py` :: whole-file (21 tests, incl. `test_manual_ramp_refused_when_gate_declines`, `test_iv_sweep_refused_when_gate_declines`, `test_vscan_refused_when_gate_declines`, `test_polarity_switch_refused_when_gate_declines`, `test_no_gate_refuses_every_hv_path_and_surfaces_it`, `test_output_off_is_not_gated`, `test_all_outputs_off_is_not_gated`, `test_manual_danger_lock_disables_energize_but_keeps_output_off_live`) | Every manual HV path (ramp, IV sweep, V-scan, polarity switch) refuses when the `DangerGate` declines or is absent; **output-off / ALL-OUTPUTS-OFF are never gated and stay live under the manual danger lock** (de-energize must never require confirmation). | HV / gate | B | **GUI-half-rehost** | The gate-declines-refuse logic survives verbatim; the NOT-AUS half (output-off / ALL-OFF buttons) lives on retained QWidget instances per the roadmap NEVER-migrates list (U4: kill switch re-parented, never re-implemented). |
| `test_motor_danger_gate.py` :: whole-file (18 tests, incl. `test_home_refused_when_gate_declines`, `test_move_abs_refused_when_gate_declines`, `test_center_refused_when_gate_declines`, `test_zero_here_refused_when_gate_declines`, `test_no_gate_refuses_the_gated_actions_and_surfaces_it`, `test_jog_is_not_gated_even_under_a_declining_gate`, `test_stop_is_not_gated`, `test_manual_danger_lock_disables_motion_but_keeps_stop_live`) | Every gated motion path (home, absolute move, center, zero-here) refuses on gate decline or missing gate; **STOP is never gated and stays live under the manual danger lock**. | MOTION / gate | B | **GUI-half-rehost** | STOP lives on a retained QWidget instance (NEVER-migrates list; U5 Motor = GL island + STOP re-host). Note: `def test_connection` in this file is a fake-driver API method (19 `def test_` lines, 18 collected tests). |
| `test_bias_kill_switch_escalation.py` :: whole-file (8 tests, incl. `test_kill_switch_escalates_to_danger_when_hv_settled_live`, `test_kill_switch_escalates_on_compliance_trip`, `test_kill_switch_off_failure_stays_escalated_not_reassuring`, `test_multi_bias_all_off_aggregates_worst_channel_state`) | Kill-switch escalation ladder (ghost → neutral → danger) tracks HV truth; a **failed output-off stays escalated** (never paints reassurance over a live channel); multi-bias aggregates the worst channel. | HV / fail-safe | B | **GUI-half-rehost** | Ladder semantics survive 1:1; the button itself is re-parented, never re-implemented (U4 [Mary] gate). |
| `test_arm_latch.py` :: whole-file (20 tests, incl. `test_not_ready_refuses_arm_and_shows_reason`, `test_timeout_disarms`, `test_plan_edit_disarms_latch_and_clears_envelope`, `test_execute_only_fires_when_armed`, `test_running_makes_latch_inert_but_abort_is_never_latched`, `test_coordinator_execute_plan_refused_when_not_ready`) | Hold-to-arm semantics: execute fires only when armed; not-ready refuses; timeout disarms; a plan edit disarms and clears the stale envelope; **Abort is never latched** — it stays a plain immediate action while the latch is inert during a run. | gate / fail-safe | B | **GUI-half-rehost** | Roadmap U5 mandates the "ArmLatch faithful port" with its own [Mary] + this suite 1:1. |
| `test_trip_detection.py` :: whole-file (9 tests, incl. `test_latched_trip_midscan_aborts_and_failsafes`, `test_latched_trip_in_voltage_scan_aborts`, `test_output_dropped_under_us_aborts`, `test_paused_run_aborts_on_latched_trip`, `test_unknown_trip_state_does_not_abort`, `test_bias_hw_fault_truth_table`) | A latched HV trip (or hardware output dropping under us) ABORTS the run with the HV fail-safe — never a green finish, never silent acquisition with HV off; UNKNOWN status is never laundered into "healthy" **and** never aborts a run by itself; paused runs are covered. | HV / fail-safe | A | **byte-identical** | The fail-safe HV-at-zero half of the roadmap pair (with `test_classic_loop_safety.py`). |
| `test_classic_loop_safety.py` :: whole-file (16 tests, incl. `test_warn_during_voltage_scan_safe_holds_with_hv_held`, `test_alarm_during_voltage_scan_failsafe_aborts_with_hv_at_zero`, `test_alarm_during_z_focus_failsafe_aborts_with_hv_at_zero`, `test_compliance_trip_in_voltage_scan_settles_aborted`, `test_abort_during_ramp_does_not_acquire_another_point`, `test_paused_run_at_hv_failsafe_aborts_on_alarm`, `test_paused_run_at_hv_failsafe_aborts_on_compliance_trip`, `test_viewer_paints_fault_not_green_finish_on_trip`) | The classic loops (`_run_voltage_scan`, `_run_z_focus_*`) honor the slow-control interlock (WARN safe-hold with HV held / ALARM fail-safe with HV at zero), settle ABORTED on a compliance trip, stop acquiring immediately on Abort-mid-ramp, and keep the interlock live while PAUSED at HV. | HV / fail-safe | B | **GUI-half-rehost** | Controller-half assertions survive verbatim; only the two viewer-paint tests (`test_viewer_paints_*`) re-host against the ported ScanViewer surface. |
| `test_sequencer.py` :: `test_assert_sequencer_compatible_rejects_manual_pause`, `test_load_rejects_manual_pause_naming_index_and_routine`, `test_sequencerunner_init_rejects_manual_pause_entry` (whole file rides bucket A) | MANUAL_PAUSE can never enter an autonomous sequence via **any of the three entry points** — the compatibility assert, YAML queue load, and `SequenceRunner` construction — each rejection naming index and routine. | gate | A | **byte-identical** | The queue-halt semantics in the same file (`test_bad_outcome_halts_and_skips_remainder`, `test_cancel_mid_queue_cancels_running_and_pending`, `test_preflight_veto_fails_entry_and_halts`) are supporting-normative and port with the file. |
| `test_ui_monkey.py` :: `test_monkey_safe_filter_denies_every_danger_control`, `test_ui_monkey_safe_random_walk` — the DENIAL RULESET | Three-layer proof that random GUI interaction cannot reach motion/HV/emission: (1) `is_monkey_safe` allowlist denies every danger control; (2) `_neutralize_modals` — `QtDangerGate._show_dialog` can only deny, any invocation is a BREACH; (3) controller tripwires on `start_plan` / `start_z_focus_scan` / `start_voltage_scan` / `arm_hv` must never fire; plus per-action invariants (no escaped exception, no modal wedge, `AppState` unchanged). | MOTION / HV / EMITTING / gate | C | **QML-walker** | The QTest harness retires with the classic shell. What ports 1:1 (the ~20% the roadmap names): the denial RULESET of `is_monkey_safe`, the tripwire boundary at the four `ScanController` entry points, the breach accounting, and invariants (a)–(f). U6 gate runs the QML walker with this ruleset preserved. |
| **— The six Mary-bounce additions —** | | | | | |
| `test_fault_injection.py` :: whole-file (8 tests: `test_scope_disconnect_midplan_stage`, `test_scope_disconnect_midplan_bias`, `test_motor_fault_midplan_bias_failsafe`, `test_motor_fault_midmove_halts_stage_plan`, `test_bias_read_failures_deviceerror_plan`, `test_wavegen_output_on_fault_plan`, `test_abort_during_wait_bias_plan`, `test_abort_during_wait_stage_plan`) | Mid-scan fail-safe for the PLAN executor — the direct enforcement of hardware-safety rule 5: on any injected fault the worker thread EXITS, the FSM reaches a terminal state, HV is ramped to 0 + output off, the laser trigger (wavegen) is turned off, the HDF5 writer is closed, and pre-fault data is preserved; abort is honored during long waits. | HV / EMITTING / MOTION / fail-safe | A | **byte-identical** | `test_wavegen_output_on_fault_plan` is also the EMITTING half of the `_acquire_core` output_on fault path (see plan-executor row). |
| `test_fault_injection_legacy.py` :: whole-file (6 tests: `test_scope_disconnect_mid_xy_scan`, `test_xy_scan_compliance_trip_failsafe`, `test_xy_scan_bias_read_failures_deviceerror`, `test_motor_fault_mid_xy_scan`, `test_wavegen_output_on_fault_xy_scan`, `test_voltage_scan_compliance_trip_failsafe`) | The same rule-5 fail-safe contract for the LEGACY paths (`_run` XY raster, `_run_voltage_scan`); pins the fixed green-banner-over-trip bug: a compliance trip settles ABORTED, never FINISHED. | HV / EMITTING / fail-safe | A | **byte-identical** | |
| `test_slow_control_policy.py` :: whole-file (10 tests, incl. `test_warn_pauses_with_prompt_then_resume_finishes`, `test_alarm_aborts_failsafe_preserving_prior_point`, `test_unavailable_sensor_pauses`, `test_no_repause_storm_and_rearm_after_ok`, plus the fail-closed threshold validation family `test_inverted_warn_band_errors` …) | RATIFIED slow-control policy (DECISIONS 2026-07-12 §2): WARN → safe-hold pause, ALARM → full fail-safe abort preserving the prior point, UNAVAILABLE sensor → pause; threshold configuration validates fail-closed. | HV / fail-safe / gate | A | **byte-identical** | |
| `test_bias_api_guard.py` :: whole-file (6 tests: `test_no_output_on_attribute`, `test_enable_output_is_callable`, `test_is_output_on_is_a_property`, `test_is_output_on_assignment_raises_on_simulated`, `test_stale_output_on_read_raises_attributeerror`, `test_is_output_on_tracks_believed_state`) | The `output_on` → `enable_output` footgun invariant: no bias driver exposes a truthy `output_on` attribute that silent-succeeds as an assignment; energizing is only ever the explicit callable. | HV / gate | A | **byte-identical** | |
| `test_bias_trip_visibility.py` :: whole-file (10 tests, incl. `test_derive_tripped_first_wins_over_compliant`, `test_derive_tripped_alone_masks_settled_looking_readback`, `test_ivworker_trip_takes_priority_over_compliance`, `test_ivworker_reasons_are_distinct_and_both_visible`, `test_safe_shutdown_disables_output_even_when_ramp_raises`) | A latched trip WINS over compliance in derived state (a settled-looking readback can never mask it); the IV worker stops on either with distinct visible reasons; `safe_shutdown` disables the output even when the ramp raises. | HV / fail-safe | C | **GUI-half-rehost** | Roadmap explicitly calls the GUI half "a genuine 1:1-port item": derive/worker logic survives verbatim, the visibility half re-hosts against the ported bias surface. |
| `test_reconnect_liveness.py` :: whole-file (16 tests, incl. `test_wavegen_is_alive_flips_connected_false_on_probe_error`, `test_wavegen_is_alive_no_session_fails_safe`, `test_camera_is_alive_no_handle_fails_safe`, `test_poll_liveness_marks_wavegen_and_camera_dead`, `test_wavegen_disconnect_with_raising_output_off_still_closes`) | No stale-green health: `is_alive` fails safe (probe error / missing session / invalid handle → connected False, never a cached green); dirty reconnects tear down prior sessions; disconnect completes teardown even when `output_off` raises. | fail-safe / EMITTING | A | **byte-identical** | |
| `test_bias_polarity.py` :: whole-file (17 tests, incl. `TestSimulatedPolarity::test_switch_refused_when_output_on`, `TestSimulatedPolarity::test_switch_refused_when_not_discharged`, `TestSimulatedPolarity::test_not_reversible_supply_reports_and_refuses`, `TestIsegSimulationSafeDefaults::test_set_polarity_refused_in_sim`) | HV polarity gating: a polarity switch is refused while the output is on or the channel is not discharged; non-reversible supplies report and refuse; sim defaults are safe (no polarity claims). | HV / gate | A | **byte-identical** | Real-iseg relay-level refusals live in `test_bias_multichannel.py` (sweep addition below). |
| **— New since the roadmap text (2026-07-13 evening) —** | | | | | |
| `test_state_fuzz.py` :: `test_start_while_paused_is_refused`, `test_start_z_focus_while_paused_is_refused`, `test_start_voltage_while_paused_is_refused`; plus `test_abort_from_paused_reaches_aborted`, `test_abort_from_running_reaches_aborted`, `test_transition_race_has_exactly_one_winner` (whole file rides bucket A) | Fail-closed guard on ALL THREE scan entry points (`start_plan`, `start_z_focus_scan`, `start_voltage_scan`): each refuses while the FSM is PAUSED (the bug this file found); abort reaches ABORTED from PAUSED and RUNNING; concurrent transitions have exactly one winner (no double-start). | gate / fail-safe | A | **byte-identical** | Judged normative: the six named tests. Judged regression harness (still byte-identical via bucket A): `test_state_fuzz_smoke`, `test_state_fuzz_walks` — the random walks are the *finder*, the named tests are the *law*. Full-suite runs stay on the bench per test-lane policy. |
| `test_plan_executor.py` :: normative subset — P0' EMITTING: `test_wavegen_setter_error_fails_safe_and_preserves_data`; gates/fail-safe: `test_unarmed_bias_plan_refuses`, `test_denied_bias_ramp_fails_safe`, `test_compliance_trip_mid_plan`, `test_validator_error_refuses_before_running`, `test_refused_start_clears_hv_arm`, `test_park_safe_after_finished_leaves_supply_off`, `test_park_safe_output_off_even_if_ramp_raises`, `test_park_safe_never_commands_a_motor_move`, `test_park_safe_parks_all_channels_including_non_primary`, `test_capture_photo_abort_during_settle_stops_clean`, `test_capture_photo_grab_raises_mid_plan_leaves_hv_safe`, `test_danger_gates_are_pure` (whole file rides bucket A) | P0' EMITTING invariant: a wavegen setter raising mid-plan surfaces as ERROR, the *finally* fail-safe issues a DISTINCT `output_off` after the fault (proven via counter-reset guard — the wavegen output is never stranded ON), prior points are preserved, and a non-bias plan never drives the bias channel. Plus: unarmed/denied/invalid plans refuse before touching hardware and clear the HV arm; `park_safe` leaves the supply off (all channels) even when the ramp raises and never commands a motor move. | EMITTING / HV / gate / fail-safe | A | **byte-identical** | The `_acquire_core` output_on→acquire→output_off bracket has **no standalone named test**: it is enforced by the counter-reset guard inside `test_wavegen_setter_error_fails_safe_and_preserves_data` plus the output_on-fault tests in both fault-injection files (drift note vs. the S2 brief wording). Judged NOT normative (behavioral regression, still bucket-A-frozen): `test_wavegen_applied_per_point_in_plan_order`, `test_wavegen_multi_setting_applied_frequency_first`, `test_wavegen_command_trace_written_to_run_metadata` (provenance honesty, owned by the DA-track contract), `test_no_wavegen_params_is_byte_identical`. |
| **— Sweep additions (S2 completeness sweep; Abel judgment, for Mary ratification) —** | | | | | |
| `test_driver_truth.py` :: whole-file (77 tests; key clusters: `TestZeroRampNeverEnergizes`, `TestIsegOutputOffNeverLies` / `TestKeithleyOutputOffNeverLies`, `TestIsegDisableNeverGatedOnValueWrite` (+ Keithley/E4Control twins), `TestIsegDisconnectFailsLoud` / `TestKeithleyDisconnectFailsLoud` / `TestE4ControlDisconnectFailsLoud`, `TestIsegTripBitsAreSurfaced`, `TestZeroDoesNotHome`) | Driver-tier safety truth across all bias backends + GRBL: a zero-ramp never ENERGIZES an off channel; a failed output-off write never claims "off"; the DISABLE is never gated on a rejected value write (de-energize always attempted); disconnect ramps down first, retries once, fails LOUD, and closes the link only after the attempt; trip bits are surfaced and UNKNOWN status is never "healthy"; GRBL zero-here never claims homed and unhomed moves are refused. | HV / MOTION / fail-safe | A | **byte-identical** | Not named in the roadmap S2 clause; caught by the sweep. Arguably the densest safety file in the repo — belongs in the manifest. |
| `test_scan_plan_validator.py` :: whole-file (44 tests, incl. `test_stage_limit_breach_is_error`, `test_bias_out_of_range_is_error`, `test_hv_plan_without_confirmation_is_error`, `test_wavegen_unknown_key_is_error_not_warning`, `test_wavegen_duty_out_of_range_is_error`, `test_capture_photo_default_limits_reject_it`) | Fail-closed plan validation: stage/bias limit breaches and an HV plan without `require_hv_confirmation` are ERRORS (refused before any hardware is touched); the P0' wavegen-params gap is closed — unknown keys and out-of-range duty/frequency are errors, never silently inert. | gate / HV / MOTION / EMITTING | A | **byte-identical** | The validator is the first fail-closed gate every plan passes; P2/P3 (AxisSpec swap) are equality-parallel-gated against exactly this behavior. |
| `test_repeatability_gate.py` :: subset — `test_confirm_requested_before_any_move`, `test_denied_confirmation_performs_no_motion`, `test_no_gate_refuses_and_performs_no_motion`, `test_no_gate_refuses_calibration` (whole file rides bucket A) | The repeatability/calibration tool's motion is danger-gated: confirmation is requested before ANY move, a denial (or missing gate) performs zero motion, and calibration is refused without a gate. | MOTION / gate | A | **byte-identical** | Rest of the file (frame-quality statistics) is functional regression. |
| `test_bias_simulation_mode.py` :: subset — `test_device_manager_iseg_simulation_connects_no_io`, `test_sim_backend_output_off_by_default`, `test_hv_ramp_denied_in_sim_still_fails_safe`, `test_hv_ramp_gate_sees_hv_ramp_action_in_sim` (whole file rides bucket A) | Simulation mode is safety-equivalent: connect performs no I/O (rule 1), the sim supply starts output-off, and a denied HV ramp in sim still runs the fail-safe with the gate seeing the real `hv_ramp` action. | HV / gate | A | **byte-identical** | Guards rule 3: tests must be safe with real hardware attached. |
| `test_bias_multichannel.py` :: subset — `TestRealIsegPolarityGate::test_refuses_when_output_is_on`, `::test_refuses_when_not_discharged`, `::test_refuses_when_status_query_returns_none`, `::test_raises_without_confirm_when_relay_never_moves`, `TestMultiChannelProxy::test_proxy_gate_survives_delegation` (whole file rides bucket A) | Real-iseg polarity relay gating: refuses while output on, not discharged, or status UNKNOWN (fail-closed on unreadable state); raises if the relay never moves; and the danger gate survives multi-channel proxy delegation (no channel is ever un-gated). | HV / gate | A | **byte-identical** | Complements `test_bias_polarity.py` (base/simulated tier). |
| `test_scan_bias_channel.py` :: subset — `TestRefuseToStart::test_out_of_range_raises_and_touches_no_hardware`, `TestRefuseToStart::test_xy_scan_out_of_range_raises_and_does_not_start` (whole file rides bucket A) | Out-of-range channel/scan requests raise BEFORE any hardware is touched — refusal happens at the entry point, not mid-run. | gate | A | **byte-identical** | |
| `test_motor_grbl_mock.py` :: subset — `TestSimulationMode::test_limit_rejection`, `TestSimulationMode::test_move_before_home_raises`, `TestEmergencyStop::test_stop_writes_m410_without_taking_the_lock`, `TestEmergencyStop::test_grbl_stop_sends_jog_cancel`, `TestSoftwareLimitsGuard::test_swapped_bounds_autocorrected_and_warned`, `TestWaitIdleHoldState::test_hold_state_raises_instead_of_spinning` (whole file rides bucket A) | Motion driver interlocks: soft-limit breaches are rejected; moves before homing raise; **emergency STOP writes M410 / GRBL jog-cancel WITHOUT taking the serial lock** (STOP can never queue behind a busy transport); a HOLD state raises instead of spinning forever; swapped soft-limit bounds are auto-corrected loudly. | MOTION / fail-safe / gate | A | **byte-identical** | The lock-free STOP write is the driver-tier twin of "STOP is not gated". |
| `test_waveform_generator.py` :: subset — `test_apply_defaults_never_enables_output`, `test_no_setter_enables_output_as_side_effect`, `test_disconnect_only_disables_a_known_on_output`, `test_connect_state_resolve_is_read_only`, `test_simulation_connect_keeps_output_state_false` (whole file rides bucket A) | EMITTING rule-1 discipline: configuring the wavegen (defaults or any setter) never enables the output as a side effect; connect resolves the armed state READ-only; disconnect disables only a known-on output. | EMITTING / gate | A | **byte-identical** | The laser trigger is driven by this device — "no setter emits" is the emission analogue of "no constructor moves motors". |
| `test_bias_all_off.py` :: whole-file (3 tests: `test_all_off_disables_output_even_when_ramp_raises`, `test_all_off_clean_when_every_channel_ok`, `test_all_off_aggregates_output_off_failure`) | The ALL-OUTPUTS-OFF fail-safe (`MultiBiasPanel._do_all_off`): a ramp failure on one channel never skips that channel's `output_off` and never stops the other channels from shutting down; failures are aggregated, surfaced, and name the channel. | HV / fail-safe | B | **GUI-half-rehost** | `_do_all_off` is a pure `@staticmethod` (no QApplication needed) — the logic ports verbatim; the ALL-OFF control itself is on the NEVER-migrates list. |
| `test_scan_coordinator.py` :: subset — `test_refused_classic_start_warns`, `test_refused_zfocus_and_vscan_warn`, `test_zfocus_start_refused_by_controller_fails_closed`, `test_voltage_start_refused_by_controller_fails_closed`, `test_classic_start_refused_by_controller_fails_closed`, `test_plan_start_not_ready_unarms`, `test_plan_start_exception_unarms`, `test_pause_resume_abort_routing`, `test_arm_hv_routing`, `test_manual_pause_forwarded`, `test_pause_parks_a_live_zfocus_run_then_abort_from_paused`, `test_pause_parks_a_live_voltage_scan_then_abort_from_paused`, `test_aborted_run_ending_while_paused_settles_aborted`, `test_fault_while_paused_still_reports_error` | Run-control gating at the coordinator seam: a controller refusal or raise during start fails CLOSED (cockpit never paints running, HV arm is cleared); pause/resume/abort and arm-HV route to the controller; abort-from-paused parks the run; a fault while PAUSED still surfaces as an error. | gate / fail-safe | B | **GUI-half-rehost** | Coordinator logic is Abel-owned sequencing that happens to live under `gui/`; assertions survive against the run-state facade, widget wiring re-hosts. |
| `test_sequence_coordinator.py` :: subset — `test_gate_abort_maps_state_to_aborted_word`, `test_abort_sequence_mid_run`, `test_abort_idle_between_entries_still_parks_and_emits`, `test_union_gate_is_private_and_passed_only_to_execute_plan`, `test_build_gate_refuses_without_a_loaded_sequence`, `test_engine_raise_fails_closed_without_dangling_active`, `test_execute_plan_refusal_halts_fail_closed`, `test_load_refused_while_active`, `test_arm_refused_when_plan_run_already_active`, `test_arm_refused_without_a_built_gate`, `test_load_rejects_manual_pause_plan_fail_closed` | Sequence-tier gating: abort works mid-run AND idle-between-entries (still parks + emits); the union `ArmedEnvelopeGate` is private and reaches only `execute_plan`; arming refuses without a built gate or while a run is active; an engine raise or an execute refusal halts fail-closed with no dangling active state; MANUAL_PAUSE plans are rejected at coordinator load (the panel-tier fourth entry point behind the `test_sequencer.py` trio). | gate / fail-safe | B | **GUI-half-rehost** | |
| `test_scan_viewer_wiring.py` :: subset — `test_refused_plan_start_does_not_paint_running_cockpit`, `test_raised_plan_start_does_not_paint_running_cockpit`, `test_z_focus_run_arms_pause_abort_and_abort_reaches_the_controller`, `test_voltage_run_arms_pause_abort_and_abort_reaches_the_controller`, `test_refused_zfocus_and_voltage_starts_do_not_arm_run_control`, `test_fault_during_run_paints_the_fault_terminal_not_the_green_banner`, `test_pause_and_abort_round_trip_to_scanner` | Run-control truth in the viewer: Pause/Abort are armed by a real run and **Abort reaches the controller**; refused/raised starts never arm run control or paint a running cockpit; a fault paints the fault terminal, never the green banner. | gate / fail-safe | B | **GUI-half-rehost** | U2 (ScanViewer hero slice) must carry these as its viewmodel-contract suite; per-stage gate: green under `TCT_SHELL=qml`. |
| `test_sequencer_panel.py` :: subset — `test_abort_button_calls_abort_sequence`, `test_arm_text_contains_every_routine_hv_and_travel`, `test_queue_edit_rederives_envelope_no_stale`, `test_on_sequence_active_locks_and_unlocks_manual_danger_panels`, `test_manual_danger_reenables_after_failure_path`, `test_manual_pause_during_sequence_no_dialog_notify_and_abort`, `test_non_sequence_manual_pause_still_shows_dialog_resume_and_abort`, `test_manual_pause_during_real_sequence_aborts_fail_safe_and_parks_hv` | Sequencer panel safety half: the arm text names EVERY routine's HV + travel extremes (informed consent); a queue edit re-derives the envelope (no stale envelope can be armed); sequence-active locks the manual danger panels and re-enables after failure; a MANUAL_PAUSE encountered during a real sequence aborts FAIL-SAFE and parks HV (no interactive dialog inside an autonomous queue). | gate / HV / fail-safe | C | **GUI-half-rehost** | The pause-rejection *logic* is already pinned in bucket A (`test_sequencer.py`); these rows pin the panel-side behavior and must be reclaimed into the U1 sequencer viewmodel suite, not dropped with the widget tests. |
| `test_planner_panel.py` :: QtDangerGate cluster only — `test_qt_danger_gate_confirms_true_on_gui_thread`, `test_qt_danger_gate_denies_false_on_gui_thread`, `test_qt_danger_gate_confirm_from_worker_thread`, `test_qt_danger_gate_timeout_denies`, `test_qt_danger_gate_no_stray_dialog_after_shutdown` | The `QtDangerGate` contract: confirm/deny resolve on the GUI thread, a worker-thread confirm marshals safely, an unanswered dialog **times out to DENY** (fail-closed), and no stray dialog fires after shutdown. | gate / fail-safe | C | **GUI-half-rehost** | The QtDangerGate modal is on the NEVER-migrates list — these assertions survive verbatim against the retained QWidget gate. Recommend carving the cluster out of `test_planner_panel.py` (a U1 reclaim target) into its own file so bucket-C churn cannot touch it (see Open questions). Rest of the file (drag/drop, template plumbing) is not normative. |
| `test_run_outcome.py` :: whole-file (10 tests, incl. `test_writer_closed_without_outcome_reads_unknown_never_finished`, `test_trip_aborted_scan_writes_outcome_aborted_naming_the_trip`, `test_operator_abort_writes_outcome_aborted_with_reason`, `test_set_outcome_rejects_unknown_value`) | Honest terminal truth in the data: a writer closed without an outcome reads UNKNOWN — never FINISHED (a crash can't leave a complete-looking file); trip-aborted runs record ABORTED naming the trip; unknown outcome words are rejected. | fail-safe | A | **byte-identical** | The data-side twin of "trip settles ABORTED"; also the `outcome/abort_reason` contract Völundr froze as the run-completeness signal. |
| `test_state_machine.py` :: subset — `test_cannot_run_before_ready`, `test_pause_resume_abort`, `test_disconnect_reachable_from_everywhere`, `test_error_recovers_to_ready` (whole file rides bucket A) | The lifecycle gate under everything else: RUNNING is unreachable before READY; pause/resume/abort transitions are legal; DISCONNECT (the safe exit) is reachable from every state. | gate | A | **byte-identical** | `StateMachine` owns lifecycle (standing invariant); the fuzzer (`test_state_fuzz.py`) is built on this contract. |
| `test_capture_onscreen_guard.py` :: subset — `test_check_environment_refuses_under_forced_offscreen`, `test_main_refuses_without_list_flag`, `test_assert_all_simulated_accepts_shipped_config`, `test_assert_all_simulated_rejects_real_hardware`, `test_assert_all_simulated_rejects_non_simulated_slow_control_channel` | The onscreen capture tool (which auto-launches the real app) is fenced by rules 3/6: it refuses wrong environments, refuses to run without an explicit flag, and `assert_all_simulated` REFUSES any config with a real-hardware backend or non-simulated slow-control channel. | gate | C | **GUI-half-rehost** | The guard logic is widget-free and survives as-is; "rehost" here means re-pointing the tool at the QML shell when it learns it. Windows-only dev tooling per the portability section. |
| `test_laser_panel_output_state.py` :: subset — `test_armed_chip_tracks_driver_state_not_button`, `test_armed_chip_unknown_when_connected_state_unknown`, `test_armed_chip_neutral_when_not_connected` | Truthful emission-state display: the laser "armed" chip tracks the DRIVER's believed state, never the button that was pressed; UNKNOWN state displays as unknown, disconnected as neutral — no stale-armed and no stale-safe claim. | EMITTING / gate | C | **GUI-half-rehost** | Abel addition beyond the roadmap set (same truth-class as `test_bias_trip_visibility.py`); flagged in Open questions for Mary's explicit in/out call. |

---

## Per-suite prose where the disposition needs justification

- **`test_classic_loop_safety.py` (B, GUI-half-rehost):** 14 of 16 tests drive
  `ScanController` + `DeviceManager` directly and would be bucket-A-shaped if
  the file did not also construct `ScanViewerPanel`/`ScanCoordinator` for the
  two paint tests. The rehost splits naturally: controller assertions survive
  byte-for-byte; only `test_viewer_paints_fault_not_green_finish_on_trip` /
  `test_viewer_still_paints_green_on_a_clean_finish` re-target the ported
  viewer surface.
- **`test_ui_monkey.py` (C, QML-walker):** the NORMATIVE content is not the
  QTest event synthesis (which retires) but the three-layer safety model —
  `is_monkey_safe` (rules incl. text-level denial as the backstop for
  mis-marked buttons), the deny-only `QtDangerGate._show_dialog` patch with
  breach accounting, and the class-level tripwires on
  `start_plan`/`start_z_focus_scan`/`start_voltage_scan`/`arm_hv`. The U6 QML
  walker must re-implement the walk but PRESERVE this ruleset and the
  per-action invariants (a)–(f) verbatim; roadmap U6 gate names this
  explicitly ("monkey QML-walker runs the denial ruleset").
- **`test_planner_panel.py` QtDangerGate cluster (C, GUI-half-rehost):** the
  only normative tests living inside a U1 *reclaim target* file. Since the
  gate widget itself never migrates, the clean move is a mechanical carve-out
  into a dedicated `test_qt_danger_gate.py` BEFORE U1 touches the planner
  suite — proposed as an S2 follow-up beat, not done in this docs-only beat.
- **Danger-gate suites (B):** the *decline-refuses* logic asserts against the
  injected `DangerGate` protocol (pure controller-side contract). What makes
  them B rather than A is the host: panels build the actions and the
  NOT-AUS/STOP/output-off controls live under manual-danger locks. Rehosting
  preserves every refusal assertion; only the widget lookups move.

## Completeness sweep (S2 exit-gate criterion)

Sweep executed 2026-07-13 by Abel:

```sh
rg -i -c "fault|danger|trip|kill|arm|interlock|fail.?safe|NOT.?AUS|abort|refus" TCT_app/tests/
```

Result: hits in **106 files** = 103 of the 109 `test_*.py` files, plus
`conftest.py` and 2 files under `fixtures/routine_corpus/`. The 6 test files
with **zero** hits: `test_bias_and_calibration.py`, `test_camera_calibration.py`,
`test_oscilloscope_preamble.py`, `test_plan_parity.py`, `test_sensor_align.py`,
`test_waveform_analysis.py` (all functional/analysis; no triage required, all
bucket-A-frozen anyway). Every hit-file is either in the manifest above
(36 files) or in the appendix below (67 files + harness/fixtures) — no silent
omissions. Note the pattern over-matches by design (`arm` hits "warm"/"alarm",
`trip` hits "round-trip"/"stitch"); the appendix reasons reflect content, not
hit counts.

## Appendix — Reviewed, NOT normative (67 hit-files)

Each file was triaged; one-clause reason why it is not in the manifest.
"(A)" = bucket-A: frozen byte-identical by the `[A-green]` gate regardless,
just not *safety*-normative.

| File | Reason |
|---|---|
| `test_affine_selfcal.py` | (A) offline affine self-calibration math; no hardware path. |
| `test_analysis_panel_load_run.py` | Offline analysis-panel load contract; reads closed runs only. |
| `test_analysis_panel_motion.py` | "Motion" = UI animation kit, not stage motion. |
| `test_analysis_panel_pose_align.py` | Offline vision pose-align panel; no hardware path. |
| `test_analysis_panel_survey.py` | Offline survey analysis panel; no hardware path. |
| `test_app_settings.py` | QSettings persistence plumbing; no gating. |
| `test_apply_theme_lifetime.py` | Theme-engine object lifetime; no safety assertion. |
| `test_backdrop.py` | DWM backdrop compositor (Windows cosmetics); degrades to no-op. |
| `test_bias_panel_motion.py` | Panel show/hide animation, not HV logic (that lives in the danger-gate/trip suites). |
| `test_camera_blackfly.py` | (A) camera sim-driver functional tests; camera is a BENIGN-class device, liveness fail-safe pinned in `test_reconnect_liveness.py`. |
| `test_camera_panel_worker.py` | Camera panel worker lifecycle/teardown (Qt hygiene, Noah's domain), not an interlock. |
| `test_cce.py` | (A) CCE physics conversion math. |
| `test_cockpit_batch_b_panels.py` | Cockpit panel state/styling; its TRIPPED/kill-switch rows *duplicate* semantics whose canonical enforcement is `test_bias_kill_switch_escalation.py` + `test_bias_trip_visibility.py` (manifest). |
| `test_config_validator.py` | (A) config-schema validation of `devices.yaml` keys; guards config plumbing, not a run-time interlock. |
| `test_data_writer.py` | (A) HDF5 layout per `SCAN_DATA_FORMAT.md` (Jonathan's contract); run-completeness *safety* half is `test_run_outcome.py` (manifest). |
| `test_device_manager.py` | (A) slow-control monitor plumbing config (baseline samples); the lifecycle gates it once had are asserted in `test_state_machine.py`/executor suites. |
| `test_efield_fit.py` | (A) E-field fit math. |
| `test_gui_thread_watchdog.py` | GUI heartbeat under load — responsiveness diagnostic; supports STOP usability but asserts no interlock (promotion candidate, see Open questions). |
| `test_image_prep.py` | (A) image-preparation math. |
| `test_intensity_panel.py` | Intensity display panel; read-only monitor. |
| `test_laser_panel_worker.py` | Laser panel worker lifecycle (Qt hygiene); output-state truth is in the manifest row above. |
| `test_layer_contracts.py` | AST architecture-layer guard; *supports* the no-widgets-in-controller safety law but is itself an architecture contract that must EVOLVE (not freeze) as QML layers appear (promotion candidate, see Open questions). |
| `test_map_slice.py` | (A) analysis map slicing. |
| `test_metrology_report.py` | (A) metrology HTML report generation. |
| `test_monitor_panel.py` | Slow-control DISPLAY honesty (never claims all-nominal before first poll, unknown ≠ neutral); the acting interlock is `test_slow_control_policy.py` (manifest); display half is promotion-candidate. |
| `test_mosaic_stitch.py` | (A) mosaic stitching math ("stitch" hits the sweep lexically). |
| `test_motion.py` | GUI animation helpers (`gui/motion.py`), not stage motion. |
| `test_motion_kit.py` | Animation kit widgets, not stage motion. |
| `test_motor_frame_contract.py` | (A) coordinate-frame bookkeeping contract; hardware limit enforcement is asserted in `test_motor_grbl_mock.py` + validator (manifest). |
| `test_motor_panel_reload.py` | Motor panel rebuild-on-reload wiring; gating pinned in `test_motor_danger_gate.py`. |
| `test_no_inline_hex_gui.py` | Style lint guard (no inline hex colors). |
| `test_oscilloscope_channel_count.py` | Scope channel-count contract; scope is a read-only instrument (BENIGN). |
| `test_oscilloscope_robustness.py` | (A) scope I/O robustness; read-only instrument, no hazard interlock. |
| `test_oscilloscope_wedge_recovery.py` | (A) CURVE?-wedge recovery (device-clear); transport robustness, not a hazard interlock. |
| `test_panel_kit.py` | Panel-kit styling primitives; "danger" here is a STYLE token, not a gate. |
| `test_panel_kit_cockpit.py` | Panel-kit cockpit variant styling. |
| `test_panel_kit_rollout_batch1.py` | Panel-kit rollout mechanics. |
| `test_panel_kit_rollout_batch3.py` | Panel-kit rollout mechanics. |
| `test_plan_compiler.py` | (A) Step-emission correctness; safety is enforced downstream by validator + gates (manifest). |
| `test_plan_estimate.py` | (A) runtime/point-count estimates; advisory only. |
| `test_plan_from_config.py` | (A) plan builder from legacy config; validated by the fail-closed validator. |
| `test_qml_scan_status.py` | QML status DISPLAY strip (bucket D); mirrors run state, commands nothing. |
| `test_qml_shell.py` | QML shell boot / soft-reload survival (bucket D); stability, not interlock. |
| `test_qml_theme_specular_sync.py` | Theme live-sync cosmetics (bucket D). |
| `test_run_bg_busy_feedback.py` | Busy-cursor feedback; UX, no gating. |
| `test_run_state_viewmodel.py` | Bucket-D viewmodel; **`test_read_only_no_command_surface` enforces the QML no-command-surface law** — normative in spirit but none of the three dispositions applies (already QML-side); see Open questions. |
| `test_scan_grid.py` | (A) scan grid geometry math. |
| `test_scan_map_view.py` | Scan-map pyqtgraph display; U1 reclaim target. |
| `test_scan_viewer_panel.py` | Viewer panel display/layout; the safety-relevant wiring is `test_scan_viewer_wiring.py` (manifest). |
| `test_scope_measurements.py` | Scope measurements contract; read-only instrument. |
| `test_scope_panel_yaml_persist.py` | Scope panel YAML persistence. |
| `test_scope_viewmodel.py` | Scope viewmodel display (bucket D). |
| `test_settings_window_panel_kit_rollout.py` | Settings window styling rollout. |
| `test_settings_window_visa_scan.py` | VISA resource *enumeration* UI (read-only listing). |
| `test_settings_window_visa_scan_deadlock.py` | Qt deadlock regression in the VISA scan worker; thread hygiene, not an interlock. |
| `test_settings_window_yaml_persist.py` | Settings persistence round-trip. |
| `test_shell_cockpit_v5.py` | Classic shell composition; retires with the shell swap. |
| `test_stage_view_frame_contract.py` | Stage-VIEW display frame contract (bucket B wiring, geometry only); no gating. |
| `test_status_widgets.py` | Status-bus display widgets. |
| `test_style_hover_hotpath_guard.py` | Style hot-path performance guard. |
| `test_style_no_label_box.py` | Style guard (no label boxes). |
| `test_suite_isolation.py` | Test-harness isolation (QSettings repointing etc.); protects the SUITE, not the instruments. |
| `test_survey_plan.py` | (A) survey plan geometry/execution; abort/fail-safe semantics are pinned in the executor + fault-injection suites (manifest). |
| `test_theme_editor.py` | Theme-editor UI; **except `test_setter_refuses_safety_tokens`** (+ locked-token preset round-trip): safety tokens (danger/armed/sim/error) are locked against edits — a safety-VISIBILITY guard, promotion candidate (see Open questions). |
| `test_theme_fanout_completeness.py` | Theme fan-out completeness (styling). |
| `test_worker_primitive.py` | `WorkerThread` Qt teardown primitive; concurrency hygiene (Noah), not a hardware interlock. |
| `test_yaml_persist.py` | (A) YAML persistence round-trip. |

Harness/fixtures (hit but not test files): `conftest.py` (QSettings isolation +
offscreen platform — protects rule 3 at the harness level, ports with whatever
harness exists), `fixtures/routine_corpus/R1_cce_v_map.yaml` + `README.md`
(P2-entry corpus artifacts, not tests).

## Drift check against the roadmap S2 clause

Every roadmap-named suite exists on disk under the expected name
(shorthand → file): test_arm_envelope → `test_arm_envelope.py`; bias/motor
danger-gate suites → `test_bias_danger_gate.py` / `test_motor_danger_gate.py`;
kill-switch ladder → `test_bias_kill_switch_escalation.py` (stays-escalated =
`test_kill_switch_off_failure_stays_escalated_not_reassuring`); arm_latch →
`test_arm_latch.py` (abort-never-latched =
`test_running_makes_latch_inert_but_abort_is_never_latched`); trip_detection,
classic_loop_safety, sequencer manual_pause trio, ui_monkey, and all six
Mary-bounce additions: **present, no renames, no drift.** One wording-level
drift vs. the S2 *brief*: the "`_acquire_core` output_on/off bracket" has no
standalone named test — it is enforced by the counter-reset guard inside
`test_wavegen_setter_error_fails_safe_and_preserves_data` plus
`test_wavegen_output_on_fault_plan` / `test_wavegen_output_on_fault_xy_scan`.

## Counts (v0.1-draft)

- Manifest files: **36** (byte-identical **21** · GUI-half-rehost **14** ·
  QML-walker **1**); normative tests covered: **~430** (whole-file rows
  counted at their full test count — 323; subset rows at their named tests —
  107).
- Reviewed, NOT normative: **67** hit-files (+ 6 zero-hit files noted, +
  harness/fixtures).

## Open questions (for Mary's ratification pass / Kaya where marked)

1. **Sweep additions beyond the roadmap set** — the entire "Sweep additions"
   block (`test_driver_truth.py`, `test_scan_plan_validator.py`,
   `test_repeatability_gate.py`, `test_bias_simulation_mode.py`,
   `test_bias_multichannel.py`, `test_scan_bias_channel.py`,
   `test_motor_grbl_mock.py`, `test_waveform_generator.py`,
   `test_bias_all_off.py`, `test_scan_coordinator.py`,
   `test_sequence_coordinator.py`, `test_scan_viewer_wiring.py`,
   `test_sequencer_panel.py`, `test_planner_panel.py` gate cluster,
   `test_run_outcome.py`, `test_state_machine.py`,
   `test_capture_onscreen_guard.py`, `test_laser_panel_output_state.py`) is
   Abel judgment, not roadmap text. Mary ratifies in/out per row.
2. **Promotion candidates left in the appendix** (deliberately, to keep the
   manifest an interlock list): `test_layer_contracts.py` (architecture guard
   that must evolve, not freeze), `test_gui_thread_watchdog.py` (a frozen GUI
   thread makes STOP unpressable — is responsiveness a safety property?),
   `test_monitor_panel.py` display-honesty rows, and
   `test_theme_editor.py::test_setter_refuses_safety_tokens` (safety-token
   lock — if in, its QML Theme-singleton analogue becomes a U-stage gate item).
3. **`test_run_state_viewmodel.py::test_read_only_no_command_surface`** (+
   `test_owns_no_timer_no_thread`): enforces that QML viewmodels expose NO
   command surface (no start/stop callables) — normative for the migration's
   safety architecture, but it is already QML-side (bucket D) and none of the
   three dispositions applies. Proposal: it rides bucket D as a standing
   per-panel viewmodel law; needs a ruling on whether the manifest gets a
   fourth disposition ("already-ported / grows with branch") in v0.2.
4. **QtDangerGate carve-out**: move the 5-test gate cluster out of
   `test_planner_panel.py` into a dedicated `test_qt_danger_gate.py` before U1
   reclaims the planner suite (mechanical, zero-logic beat) — else the C-bucket
   reclaim churns a normative cluster. Needs Adam scheduling, no design input.
5. **Disposition granularity inside `test_classic_loop_safety.py`**: whether
   to split the two viewer-paint tests into the U2 viewmodel-contract suite at
   rehost time (recommended) or keep the file whole. Either preserves the
   assertions; flagged so the rehost beat has an explicit instruction.
6. **`test_sequencer_panel.py` manual-danger lock rows**: the lock/unlock
   round-trip is asserted both here and in the two danger-gate suites; at U1
   reclaim these should converge on ONE canonical host (proposal: the
   danger-gate suites) rather than porting the duplication.

---

*Maintenance:* when a normative test is added, renamed, or its host file is
reclaimed/carved out, update this manifest in the same beat (same rule as
`docs/test_bucket_map.md`). Mamoru's standup cross-checks manifest names
against disk; a normative test that disappears from disk without a manifest
edit is a gate failure, not drift.
