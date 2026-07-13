# SAFETY_NORMATIVE_TESTS.md — the 1:1-port manifest

| | |
|---|---|
| **Version** | v0.2 |
| **Date** | 2026-07-13 |
| **Status** | Mary-RATIFIED (S2 exit, 14 amendments applied) → awaiting Kaya (personal gate) |
| **Author** | Abel (acquisition-dev), roadmap stage S2; v0.2 amendments per Mary's ratification verdict |
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
- **QML-native / per-panel standing law** — *(new in v0.2; Mary's ruling on
  open Q3)* the test is already QML-side (bucket D), so there is nothing to
  port. The obligation is not *port* but **REPLICATE**: every new panel
  viewmodel must carry the same assertion, and the U-stage per-panel qml-boot
  gate checks exactly that. The named tests are the template the gate holds
  each new viewmodel against.

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
| `test_classic_loop_safety.py` :: whole-file (16 tests, incl. `test_warn_during_voltage_scan_safe_holds_with_hv_held`, `test_alarm_during_voltage_scan_failsafe_aborts_with_hv_at_zero`, `test_alarm_during_z_focus_failsafe_aborts_with_hv_at_zero`, `test_compliance_trip_in_voltage_scan_settles_aborted`, `test_abort_during_ramp_does_not_acquire_another_point`, `test_paused_run_at_hv_failsafe_aborts_on_alarm`, `test_paused_run_at_hv_failsafe_aborts_on_compliance_trip`, `test_viewer_paints_fault_not_green_finish_on_trip`) | The classic loops (`_run_voltage_scan`, `_run_z_focus_*`) honor the slow-control interlock (WARN safe-hold with HV held / ALARM fail-safe with HV at zero), settle ABORTED on a compliance trip, stop acquiring immediately on Abort-mid-ramp, and keep the interlock live while PAUSED at HV. | HV / fail-safe | B | **GUI-half-rehost** | Controller-half assertions survive verbatim; THREE tests construct `ScanViewerPanel` and re-host against the ported viewer surface (named in the per-suite prose below). RULED (Rulings Q5): split at U2 rehost time — the 13-test controller residue becomes Qt-free and is re-classified into bucket A in the same beat. |
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
| `test_plan_executor.py` :: normative subset — P0' EMITTING: `test_wavegen_setter_error_fails_safe_and_preserves_data`, `test_apply_wavegen_non_finite_raises_before_commanding`; gates/fail-safe: `test_unarmed_bias_plan_refuses`, `test_denied_bias_ramp_fails_safe`, `test_compliance_trip_mid_plan`, `test_validator_error_refuses_before_running`, `test_refused_start_clears_hv_arm`, `test_park_safe_after_finished_leaves_supply_off`, `test_park_safe_output_off_even_if_ramp_raises`, `test_park_safe_never_commands_a_motor_move`, `test_park_safe_parks_all_channels_including_non_primary`, `test_capture_photo_abort_during_settle_stops_clean`, `test_capture_photo_grab_raises_mid_plan_leaves_hv_safe`, `test_danger_gates_are_pure` (whole file rides bucket A) | P0' EMITTING invariant: a wavegen setter raising mid-plan surfaces as ERROR, the *finally* fail-safe issues a DISTINCT `output_off` after the fault (proven via counter-reset guard — the wavegen output is never stranded ON), prior points are preserved, and a non-bias plan never drives the bias channel; a non-finite (NaN/inf) wavegen value raises fail-closed BEFORE anything is commanded to the instrument. Plus: unarmed/denied/invalid plans refuse before touching hardware and clear the HV arm; `park_safe` leaves the supply off (all channels) even when the ramp raises and never commands a motor move. | EMITTING / HV / gate / fail-safe | A | **byte-identical** | The `_acquire_core` output_on→acquire→output_off bracket has **no standalone named test**: it is enforced by the counter-reset guard inside `test_wavegen_setter_error_fails_safe_and_preserves_data` plus the output_on-fault tests in both fault-injection files (drift note vs. the S2 brief wording). Judged NOT normative (behavioral regression, still bucket-A-frozen): `test_wavegen_applied_per_point_in_plan_order`, `test_wavegen_multi_setting_applied_frequency_first`, `test_wavegen_command_trace_written_to_run_metadata` (provenance honesty, owned by the DA-track contract), `test_no_wavegen_params_is_byte_identical`. |
| **— Sweep additions (S2 completeness sweep — all 18 RATIFIED IN by Mary, S2 gate; Rulings Q1) —** | | | | | |
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
| `test_sequencer_panel.py` :: subset — `test_abort_button_calls_abort_sequence`, `test_arm_text_contains_every_routine_hv_and_travel`, `test_queue_edit_rederives_envelope_no_stale`, `test_on_sequence_active_locks_and_unlocks_manual_danger_panels`, `test_manual_danger_reenables_after_failure_path`, `test_manual_pause_during_sequence_no_dialog_notify_and_abort`, `test_non_sequence_manual_pause_still_shows_dialog_resume_and_abort`, `test_manual_pause_during_real_sequence_aborts_fail_safe_and_parks_hv` | Sequencer panel safety half: the arm text names EVERY routine's HV + travel extremes (informed consent); a queue edit re-derives the envelope (no stale envelope can be armed); sequence-active locks the manual danger panels and re-enables after failure; a MANUAL_PAUSE encountered during a real sequence aborts FAIL-SAFE and parks HV (no interactive dialog inside an autonomous queue). | gate / HV / fail-safe | C | **GUI-half-rehost** | The pause-rejection *logic* is already pinned in bucket A (`test_sequencer.py`); these rows pin the panel-side behavior and must be reclaimed into the U1 sequencer viewmodel suite, not dropped with the widget tests. NO dedup with the danger-gate suites during U1 (Rulings Q6) — the lock/unlock ROUND-TRIP asserted here is a different thing from refusal-under-declining-gate. |
| `test_planner_panel.py` :: QtDangerGate cluster only — `test_qt_danger_gate_confirms_true_on_gui_thread`, `test_qt_danger_gate_denies_false_on_gui_thread`, `test_qt_danger_gate_confirm_from_worker_thread`, `test_qt_danger_gate_timeout_denies`, `test_qt_danger_gate_no_stray_dialog_after_shutdown` | The `QtDangerGate` contract: confirm/deny resolve on the GUI thread, a worker-thread confirm marshals safely, an unanswered dialog **times out to DENY** (fail-closed), and no stray dialog fires after shutdown. | gate / fail-safe | C | **GUI-half-rehost** | The QtDangerGate modal is on the NEVER-migrates list — these assertions survive verbatim against the retained QWidget gate. RULED (Rulings Q4): carving the cluster into `tests/test_qt_danger_gate.py` is a **PRECONDITION of U1** — U1 may not touch `test_planner_panel.py` until it has left. Rest of the file (drag/drop, template plumbing) is not normative. |
| `test_run_outcome.py` :: whole-file (10 tests, incl. `test_writer_closed_without_outcome_reads_unknown_never_finished`, `test_trip_aborted_scan_writes_outcome_aborted_naming_the_trip`, `test_operator_abort_writes_outcome_aborted_with_reason`, `test_set_outcome_rejects_unknown_value`) | Honest terminal truth in the data: a writer closed without an outcome reads UNKNOWN — never FINISHED (a crash can't leave a complete-looking file); trip-aborted runs record ABORTED naming the trip; unknown outcome words are rejected. | fail-safe | A | **byte-identical** | The data-side twin of "trip settles ABORTED"; also the `outcome/abort_reason` contract Völundr froze as the run-completeness signal. |
| `test_state_machine.py` :: subset — `test_cannot_run_before_ready`, `test_pause_resume_abort`, `test_disconnect_reachable_from_everywhere`, `test_error_recovers_to_ready` (whole file rides bucket A) | The lifecycle gate under everything else: RUNNING is unreachable before READY; pause/resume/abort transitions are legal; DISCONNECT (the safe exit) is reachable from every state. | gate | A | **byte-identical** | `StateMachine` owns lifecycle (standing invariant); the fuzzer (`test_state_fuzz.py`) is built on this contract. |
| `test_capture_onscreen_guard.py` :: subset — `test_check_environment_refuses_under_forced_offscreen`, `test_main_refuses_without_list_flag`, `test_assert_all_simulated_accepts_shipped_config`, `test_assert_all_simulated_rejects_real_hardware`, `test_assert_all_simulated_rejects_non_simulated_slow_control_channel` | The onscreen capture tool (which auto-launches the real app) is fenced by rules 3/6: it refuses wrong environments, refuses to run without an explicit flag, and `assert_all_simulated` REFUSES any config with a real-hardware backend or non-simulated slow-control channel. | gate | C | **GUI-half-rehost** | The guard logic is widget-free and survives as-is; "rehost" here means re-pointing the tool at the QML shell when it learns it. Windows-only dev tooling per the portability section. |
| `test_laser_panel_output_state.py` :: subset — `test_armed_chip_tracks_driver_state_not_button`, `test_armed_chip_unknown_when_connected_state_unknown`, `test_armed_chip_neutral_when_not_connected` | Truthful emission-state display: the laser "armed" chip tracks the DRIVER's believed state, never the button that was pressed; UNKNOWN state displays as unknown, disconnected as neutral — no stale-armed and no stale-safe claim. | EMITTING / gate | C | **GUI-half-rehost** | Abel addition beyond the roadmap set (same truth-class as `test_bias_trip_visibility.py`); ratified IN by Mary (Rulings Q1). |
| **— v0.2 ratification promotions (Mary S2 amendments, 2026-07-13) —** | | | | | |
| `test_plan_compiler.py` :: subset — `test_compiled_params_are_deep_copied_from_live_plan` (whole file rides bucket A) | The TOCTOU guard that makes "safety is enforced downstream by the validator" TRUE: compiled step params are DEEP-copied snapshots of the live plan. Without the deep copy, mutating the plan's nested `wavegen` mapping *after* validation/compile would silently change the values the executor commands to hardware — post-validation mutation reaching the setters unvalidated. | EMITTING / gate | A | **byte-identical** | Rest of the file is Step-emission regression (bucket-A-frozen regardless). Downstream halves of the chain: `test_scan_plan_validator.py` (fail-closed validation) and the `test_plan_executor.py` P0' row. |
| `test_config_validator.py` :: subset — `test_swapped_limits_is_error_naming_axis_and_values`, `test_min_ge_max_is_error`, `test_marlin_with_negative_envelope_is_error`, `test_zero_width_axis_is_error`, `test_bad_compliance_is_error`, `test_wfg_low_ge_high_is_error`, `test_wfg_nan_or_inf_level_is_error` (whole file rides bucket A) | `devices.yaml` IS the calibration of every downstream interlock — a bad config passes every gate with a wrong envelope. Swapped/degenerate stage limits (naming axis and values), a negative Marlin envelope, a zero-width axis, a bad compliance value, and inverted or non-finite wavegen levels are ERRORS, fail-closed at config load. | MOTION / HV / EMITTING / gate | A | **byte-identical** | NOT the whole file — unknown-key warnings and section-coverage checks stay plumbing. The manifest already carries the driver-tier twin: `test_motor_grbl_mock.py::TestSoftwareLimitsGuard`. |
| `test_motor_frame_contract.py` :: whole-file (7 tests, incl. `test_plan_exceeding_real_travel_still_rejected_after_zero`, `test_user_frame_bound_equals_machine_gate_exactly`) | The soft-limit interlock's **frame-equivalence proof**: the driver gates limits in the MACHINE frame, the validator in the USER frame, and Zero-Here shifts between them. The two named tests prove the translation only SHIFTS the envelope, never widens it — the user-frame bound equals the per-move machine gate EXACTLY. A sign/offset error here silently WIDENS the motion envelope while every driver test still passes. | MOTION / gate | A | **byte-identical** | Completes the three-tier limit chain: driver gate (`test_motor_grbl_mock.py`) ↔ this frame equivalence ↔ plan validator (`test_scan_plan_validator.py`). |
| `test_gui_thread_watchdog.py` :: whole-file (`test_gui_heartbeat_survives_heavy_workload`, parametrized ×2 workloads) | **The canonical STOP-reachability host.** A blocked GUI thread is an unpressable STOP: STOP / ALL-OUTPUTS-OFF / Abort are QWidget controls living on the GUI thread (roadmap NEVER-migrates list), so GUI-thread liveness under heavy compute IS a safety property, not a UX nicety. Pins the three-layer law: compute must never block the GUI thread. | gate / fail-safe | B | **GUI-half-rehost** | Also the ONLY test anchor for the roadmap's QML safety-event-authority gate. `test_settings_window_visa_scan_deadlock.py` and `test_worker_primitive.py` stay appendix as thread *hygiene* and reference this row as canonical — the same argument does not re-open at U6. |
| `test_monitor_panel.py` :: subset — `test_construction_never_claims_all_nominal_before_first_poll`, `test_zero_readings_poll_never_claims_all_nominal`, `test_unavailable_reads_unknown_not_neutral`, `test_unavailable_channel_is_distinct_from_aged_value`, `test_alarm_escalates_header_chip`, `test_alarm_still_escalates_when_another_channel_is_unavailable` | Slow-control DISPLAY honesty: the panel never claims all-nominal before the first poll or on zero readings; UNAVAILABLE reads unknown (never neutral) and is distinct from an aged value; an ALARM escalates the header chip even while another channel is unavailable. The chip displays the ALARM→fail-safe interlock itself. | fail-safe / gate | C | **GUI-half-rehost** | Consistency promotion: bias-trip and laser-armed display honesty are already in the manifest; the acting interlock stays `test_slow_control_policy.py` (bucket A). Rest of the file (layout, history plot, theming) is not normative. |
| `test_theme_editor.py` :: subset — `test_setter_refuses_safety_tokens`, `test_no_preset_can_touch_any_locked_safety_token` | The danger/armed/sim/error tokens ARE the operator's hazard channel: the theme setter refuses to override any locked safety token, and no preset — including hostile persisted JSON — can round-trip a locked-token override into the applied palette. | gate | C | **GUI-half-rehost** | Accepted consequence of promotion: the QML Theme-singleton analogue becomes a U-stage gate item. Rest of the file (glass/opacity/preset UX) is not normative; several neighbors (`test_malicious_preset_json_is_rejected_not_laundered`, `test_builtin_presets_carry_no_safety_token`) are supporting. |
| `test_laser_panel_worker.py` :: subset — `test_queued_output_off_rescued_by_teardown_order`, `test_shutdown_bounded_when_write_in_flight` | A queued output-OFF discarded at panel shutdown must still end with the wavegen output OFF (the teardown→`disconnect_all` ordering rescue) — a lost `output_off` strands the laser trigger armed after the panel closes. And `shutdown()` returns within its bound even with a write in flight (a hung teardown blocks the GUI thread — see the STOP-reachability row). | EMITTING / fail-safe | C | **GUI-half-rehost** | The panel-tier half of the already-promoted driver-tier twin (`test_waveform_generator.py::test_disconnect_only_disables_a_known_on_output`, `test_reconnect_liveness.py::test_wavegen_disconnect_with_raising_output_off_still_closes`). Rest of the file is Qt worker hygiene. |
| `test_cockpit_batch_b_panels.py` :: subset — `test_laser_manual_banner_no_emission_switch_pdl_collapsed` | **Denial-by-absence**: the manual-laser card carries NO software emission control (its only button is the metadata save) — the EMITTING analogue of "STOP is never gated" and the direct anchor of the HARD LAW *generation never produces safety controls*. The wavegen keeps its real on/off because that device IS controllable. | EMITTING / gate | C | **GUI-half-rehost** | Single-test promotion; the rest of the file stays appendix (reason reworded there so it no longer swallows this row). |
| `test_run_state_viewmodel.py` :: subset — `test_read_only_no_command_surface`, `test_owns_no_timer_no_thread` | The QML no-command-surface law: a viewmodel exposes NO callable that can start/stop/abort anything (read-only mirror of run state) and owns no timer/thread of its own — safety commands can never grow a QML-side entry point by accretion. | gate | D | **QML-native / per-panel standing law** | The template row for the new fourth disposition (Rulings Q3): every new panel viewmodel must REPLICATE these assertions, and the U-stage per-panel qml-boot gate checks that they exist. |

---

## Per-suite prose where the disposition needs justification

- **`test_classic_loop_safety.py` (B, GUI-half-rehost):** **13 of 16** tests
  drive `ScanController` + `DeviceManager` directly and would be
  bucket-A-shaped if the file did not also construct `ScanViewerPanel` for
  THREE tests — `test_viewer_paints_fault_not_green_finish_on_trip`,
  `test_viewer_still_paints_green_on_a_clean_finish`, and
  `test_progress_tile_is_stale_until_the_first_progress_lands` (the third is
  non-normative but is still a widget test — the split beat must move it too,
  or the residue is not Qt-free). RULED (Rulings Q5): split at U2 rehost time,
  not before; the three viewer tests move into the U2 viewmodel-contract
  suite, and the 13-test controller residue is re-classified into bucket A in
  the same beat (bucket map + this manifest + `check_bucket_a.ps1` together) —
  converting 13 HV fail-safe assertions from a hand-checked suite into
  mechanically-frozen ones.
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
  into a dedicated `tests/test_qt_danger_gate.py`. RULED (Rulings Q4): the
  carve-out is a **PRECONDITION of U1** — U1 may not touch
  `test_planner_panel.py` until the cluster has left — and the carve-out beat
  updates BOTH this manifest and `docs/test_bucket_map.md` (proposed bucket
  for the new file: C, or B if it lands widget-light). Not done in this
  docs-only beat.
- **`test_gui_thread_watchdog.py` (B, GUI-half-rehost) — the canonical
  STOP-reachability host:** the ONE place where "the GUI thread stays alive
  under load" is asserted as a safety property (a blocked GUI thread = an
  unpressable STOP, and STOP/ALL-OFF/Abort are GUI-thread QWidget controls per
  the NEVER-migrates list). Other thread-hygiene suites
  (`test_settings_window_visa_scan_deadlock.py`, `test_worker_primitive.py`)
  deliberately stay appendix and defer to this row — the promotion argument is
  settled here once, not re-run per hygiene file at U6.
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
`conftest.py` and 2 files under `fixtures/routine_corpus/`. The test files
with **zero** hits: `test_bias_and_calibration.py`, `test_camera_calibration.py`,
`test_oscilloscope_preamble.py`, `test_sensor_align.py`,
`test_waveform_analysis.py` (5 files — functional/analysis, no safety surface,
all bucket-A-frozen anyway) plus `test_plan_parity.py`, which v0.1 dismissed
sight-unseen and which v0.2 moves into the appendix with an honest,
content-based reason (Mary amendment 12). Every hit-file is either in the
manifest above (45 files) or in the appendix below (59 hit-files, one of them
dual-listed with a single promoted test in the manifest, + harness/fixtures) —
no silent omissions. Note the pattern over-matches by design (`arm` hits
"warm"/"alarm", `trip` hits "round-trip"/"stitch"); the appendix reasons
reflect content, not hit counts.

**METHODOLOGY FIX (v0.2, Mary amendment 14):** a file-level `rg -l` sweep is
structurally blind to a normative test sitting inside a file triaged as
non-normative — that blindness is exactly where the v0.2 promotions came from
(deep-copy TOCTOU guard in `test_plan_compiler.py`, the config-validator error
family, the monitor-panel/theme-editor/laser-worker subsets, the
denial-by-absence test in `test_cockpit_batch_b_panels.py`, and a missing name
inside an already-manifest file, `test_plan_executor.py`). Future sweeps MUST
be run at TEST-NAME level and triaged by NAME, not by file, e.g.:

```sh
rg -n "def test_[a-z0-9_]*(refus|deny|never|fail.?safe|not_|off|stop|abort|guard|lock|limit|raise|reject)" TCT_app/tests/
```

The Maintenance section below binds this and extends Mamoru's standup check
accordingly.

## Appendix — Reviewed, NOT normative (60 rows: 59 hit-files + 1 zero-hit file)

Each file was triaged; one-clause reason why it is not in the manifest.
"(A)" = bucket-A: frozen byte-identical by the `[A-green]` gate regardless,
just not *safety*-normative. Files promoted (whole or subset) into the
manifest in v0.2 left this table; `test_cockpit_batch_b_panels.py` alone is
dual-listed (one promoted test in the manifest, rest of the file here, per
Mary amendment 10).

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
| `test_cockpit_batch_b_panels.py` | REST of file only — `test_laser_manual_banner_no_emission_switch_pdl_collapsed` is PROMOTED (manifest, denial-by-absence). The remaining cockpit panel state/styling tests stay out; their TRIPPED/kill-switch rows *duplicate* semantics whose canonical enforcement is `test_bias_kill_switch_escalation.py` + `test_bias_trip_visibility.py` (manifest). |
| `test_data_writer.py` | (A) HDF5 layout per `SCAN_DATA_FORMAT.md` (Jonathan's contract); run-completeness *safety* half is `test_run_outcome.py` (manifest). |
| `test_device_manager.py` | (A) slow-control monitor plumbing config (baseline samples); the lifecycle gates it once had are asserted in `test_state_machine.py`/executor suites. |
| `test_efield_fit.py` | (A) E-field fit math. |
| `test_image_prep.py` | (A) image-preparation math. |
| `test_intensity_panel.py` | Intensity display panel; read-only monitor. |
| `test_layer_contracts.py` | AST architecture-layer guard; *supports* the no-widgets-in-controller safety law but is itself an architecture contract that must EVOLVE (not freeze) as QML layers appear — DEMOTE-CONFIRMED (prophylaxis, not an interlock) **with a rider (Mary amendment 11): the `test_devices_import_nothing_above` / `test_layer_contract_holds` clauses are NON-WEAKENABLE — the layer table may grow, but the assertion that `devices/` and `controller/` import nothing from `gui/` may never be deleted; it is what keeps the fail-safe paths runnable without a live Qt event loop.** |
| `test_map_slice.py` | (A) analysis map slicing. |
| `test_metrology_report.py` | (A) metrology HTML report generation. |
| `test_mosaic_stitch.py` | (A) mosaic stitching math ("stitch" hits the sweep lexically). |
| `test_motion.py` | GUI animation helpers (`gui/motion.py`), not stage motion. |
| `test_motion_kit.py` | Animation kit widgets, not stage motion. |
| `test_motor_panel_reload.py` | Motor panel rebuild-on-reload wiring; gating pinned in `test_motor_danger_gate.py`. |
| `test_no_inline_hex_gui.py` | Style lint guard (no inline hex colors). |
| `test_oscilloscope_channel_count.py` | Scope channel-count contract; scope is a read-only instrument (BENIGN). |
| `test_oscilloscope_robustness.py` | (A) scope I/O robustness; read-only instrument, no hazard interlock. |
| `test_oscilloscope_wedge_recovery.py` | (A) CURVE?-wedge recovery (device-clear); transport robustness, not a hazard interlock. |
| `test_panel_kit.py` | Panel-kit styling primitives; "danger" here is a STYLE token, not a gate. |
| `test_panel_kit_cockpit.py` | Panel-kit cockpit variant styling. |
| `test_panel_kit_rollout_batch1.py` | Panel-kit rollout mechanics. |
| `test_panel_kit_rollout_batch3.py` | Panel-kit rollout mechanics. |
| `test_plan_estimate.py` | (A) runtime/point-count estimates; advisory only. |
| `test_plan_from_config.py` | (A) plan builder from legacy config; validated by the fail-closed validator. |
| `test_plan_parity.py` | (A) plan-vs-legacy execution parity (zero-hit in the lexical sweep; v0.1 dismissed it unread — corrected per Mary amendment 12). Reviewed-NOT-normative because the consent path (arm text) derives from `derive_envelope()` (`controller/arm_envelope.py`) over the COMPILED steps, not from `estimate_plan`; `estimate.hv_range_V` only feeds the planner HV tile. It does contain `test_hv_range_parity` + `test_manual_pause_warning_parity`, which is why it needed reading, not dismissing. |
| `test_qml_scan_status.py` | QML status DISPLAY strip (bucket D); mirrors run state, commands nothing. |
| `test_qml_shell.py` | QML shell boot / soft-reload survival (bucket D); stability, not interlock. |
| `test_qml_theme_specular_sync.py` | Theme live-sync cosmetics (bucket D). |
| `test_run_bg_busy_feedback.py` | Busy-cursor feedback; UX, no gating. |
| `test_scan_grid.py` | (A) scan grid geometry math. |
| `test_scan_map_view.py` | Scan-map pyqtgraph display; U1 reclaim target. |
| `test_scan_viewer_panel.py` | Viewer panel display/layout; the safety-relevant wiring is `test_scan_viewer_wiring.py` (manifest). |
| `test_scope_measurements.py` | Scope measurements contract; read-only instrument. |
| `test_scope_panel_yaml_persist.py` | Scope panel YAML persistence. |
| `test_scope_viewmodel.py` | Scope viewmodel display (bucket D). |
| `test_settings_window_panel_kit_rollout.py` | Settings window styling rollout. |
| `test_settings_window_visa_scan.py` | VISA resource *enumeration* UI (read-only listing). |
| `test_settings_window_visa_scan_deadlock.py` | Qt deadlock regression in the VISA scan worker; thread *hygiene* — the canonical STOP-reachability assertion lives in `test_gui_thread_watchdog.py` (manifest), which this defers to. |
| `test_settings_window_yaml_persist.py` | Settings persistence round-trip. |
| `test_shell_cockpit_v5.py` | Classic shell composition; retires with the shell swap. |
| `test_stage_view_frame_contract.py` | Stage-VIEW display frame contract (bucket B wiring, geometry only); no gating. |
| `test_status_widgets.py` | Status-bus display widgets. |
| `test_style_hover_hotpath_guard.py` | Style hot-path performance guard. |
| `test_style_no_label_box.py` | Style guard (no label boxes). |
| `test_suite_isolation.py` | Test-harness isolation (QSettings repointing etc.); protects the SUITE, not the instruments. |
| `test_survey_plan.py` | (A) survey plan geometry/execution; abort/fail-safe semantics are pinned in the executor + fault-injection suites (manifest). |
| `test_theme_fanout_completeness.py` | Theme fan-out completeness (styling). |
| `test_worker_primitive.py` | `WorkerThread` Qt teardown primitive; concurrency *hygiene* (Noah) — the canonical STOP-reachability assertion lives in `test_gui_thread_watchdog.py` (manifest), which this defers to. |
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

## Counts (v0.2 — recomputed after all 14 amendments)

- Manifest files: **45** (byte-identical **24** · GUI-half-rehost **19** ·
  QML-walker **1** · QML-native / per-panel standing law **1**); normative
  tests covered: **~461** (whole-file rows counted at their full collected
  count — 332, incl. `test_motor_frame_contract.py` = 7 and
  `test_gui_thread_watchdog.py` = 2 parametrized; subset rows at their named
  tests — 129).
- Reviewed, NOT normative: **60** appendix rows = 59 hit-files (one of them,
  `test_cockpit_batch_b_panels.py`, dual-listed with a single promoted test in
  the manifest) + 1 zero-hit file (`test_plan_parity.py`, triaged honestly in
  v0.2); plus 5 zero-hit functional/analysis files noted in the sweep section
  and harness/fixtures.
- Coverage: 45 manifest + 60 appendix − 1 dual-listed + 5 zero-hit =
  **109 test files**, matching the disk count in `docs/test_bucket_map.md`
  (A 47 · B 18 · C 39 · D 5). No file on disk is unaccounted for.

## Rulings (Mary, S2 gate, 2026-07-13)

The v0.1 open questions, as ruled at ratification. The document carries its
own decision history; do not re-litigate these at U-stage time.

1. **Sweep additions (v0.1 Q1): all 18 RATIFIED IN.** The roadmap named a
   STARTING set, not a closed one. The "Sweep additions" block is now
   ratified manifest content, not Abel judgment pending review.
2. **Promotion candidates (v0.1 Q2): ruled per file** — see the v0.2
   promotions block (`test_gui_thread_watchdog.py` in as the canonical
   STOP-reachability host; `test_monitor_panel.py` display-honesty subset in;
   `test_theme_editor.py` safety-token subset in) and the
   `test_layer_contracts.py` appendix rider (demote-confirmed, non-weakenable
   clauses).
3. **Fourth disposition (v0.1 Q3): CREATED** — "QML-native / per-panel
   standing law" (see legend). `test_run_state_viewmodel.py`'s
   `test_read_only_no_command_surface` + `test_owns_no_timer_no_thread` are
   its template row; the obligation is REPLICATE, not port: every new panel
   viewmodel carries the same assertions, checked by the U-stage per-panel
   qml-boot gate.
4. **QtDangerGate carve-out (v0.1 Q4): APPROVED and hardened.** Carving the
   5-test cluster out of `test_planner_panel.py` into
   `tests/test_qt_danger_gate.py` is a **PRECONDITION of U1** — U1 may not
   touch `test_planner_panel.py` until the cluster has left. The carve-out
   beat updates BOTH this manifest and `docs/test_bucket_map.md` in the same
   beat (the new file needs a bucket: proposed C, or B if it lands
   widget-light).
5. **`test_classic_loop_safety.py` split (v0.1 Q5): RULED — split at U2
   rehost time, NOT now.** The 3 viewer tests
   (`test_viewer_paints_fault_not_green_finish_on_trip`,
   `test_viewer_still_paints_green_on_a_clean_finish`,
   `test_progress_tile_is_stale_until_the_first_progress_lands`) move into
   the U2 viewmodel-contract suite; the 13-test controller residue becomes
   Qt-free and MUST be re-classified into bucket A in the same beat (bucket
   map + this manifest + `check_bucket_a.ps1` together) — converting 13 HV
   fail-safe assertions from a hand-checked suite into mechanically-frozen
   ones.
6. **Sequencer-panel / danger-gate convergence (v0.1 Q6): RULED — NO dedup
   during U1.** The suites assert different things: refusal-under-declining-
   gate (danger-gate suites) vs the LOCK/UNLOCK ROUND-TRIP (a failed sequence
   must not leave the operator's manual STOP/output-off panels dead).
   Convergence is permitted only AFTER a replacement suite is green under
   `TCT_SHELL=qml`, and this manifest is edited in that same beat.
7. **Kaya deferrals: none.** The only thing Kaya still owns is the personal
   [Kaya] gate on this amended document.

---

*Maintenance:* when a normative test is added, renamed, or its host file is
reclaimed/carved out, update this manifest in the same beat (same rule as
`docs/test_bucket_map.md`).

*Sweep methodology (BINDING, v0.2 — Mary amendment 14):* completeness sweeps
for this manifest MUST run at **test-name level and be triaged by NAME, not by
file** — a file-level `rg -l` sweep is structurally blind to a normative test
inside a file already triaged as non-normative (the source of every v0.2
promotion). Canonical sweep:

```sh
rg -n "def test_[a-z0-9_]*(refus|deny|never|fail.?safe|not_|off|stop|abort|guard|lock|limit|raise|reject)" TCT_app/tests/
```

*Mamoru standup check (extended in v0.2):* two directions, both gate failures
when unexplained —

1. every test name in the manifest still exists on disk (a normative test
   that disappears without a manifest edit is a gate failure, not drift);
2. **no NEW `def test_*` matching the danger lexicon above exists in a file
   this manifest triaged as non-normative** (or in no file at all). This is
   the drift direction that actually bit: commit `5915aa1` added two
   normative tests ONE COMMIT before the v0.1 manifest and the file-level
   sweep still missed them.
