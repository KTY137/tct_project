# Planner routines v2 — enrichment proposal (Workstream C1)

> Status: **PROPOSAL ONLY** (Kaya's binding decision — zero implementation this
> round). Author: Abel. Date: 2026-07-13. Feeds the P-track staging in
> `docs/ROADMAP_MASTERPLAN.md` Part II. Citations are file:symbol (lines rot).

## 1. Headline — the inert wavegen and the documented extension seam

The plan grammar already *carries* wavegen settings but the executor never
*applies* them: `scan_plan_validator._KNOWN_ACTION_PARAMS` admits a `wavegen`
key on `ACQUIRE_WAVEFORM`, `plan_compiler.AcquireStep` copies the action params
verbatim, and then `ScanController._run_plan`'s AcquireStep branch calls
`_acquire_core(point, step.n_averages, bias)` — `step.params` is dropped on the
floor. A routine that "sweeps duty cycle" today validates, compiles, estimates
and runs while the generator never changes. That is the honesty gap the roadmap
already schedules: **P0'** applies `params['wavegen']` per-point directly (with
a per-point command trace), **P1** re-lands it as the capability pilot
(equality-gated, EMITTING class, recorded in `swept/` per DA1), **P2** freezes
`scan_plan.Axis` as the v1 grammar behind an `AxisSpec` table, and **P3** opens
registry-backed NEW axes with a versioned plan JSON. This proposal does not
re-propose duty cycle; it enumerates what should ride the same seam *after*
P0'/P1, so Kaya can pick the post-P1 implementation wave. The seam every
candidate must traverse, end to end:
`Axis` enum (`scan_plan.Axis`, 4 members) or action params → `AxisSpec` (P2/P3)
→ compiled `Step` (`plan_compiler`) → executor dispatch (`_run_plan`) →
validator limits (`scan_plan_validator.PlanLimits`) → palette/panel
(`gui/planner_panel._PaletteList`) → per-point provenance
(`swept/{capability_id}` per DA1; today only e.g. `hdf5_writer.save_point`'s
`bias/voltage_V`). A candidate that cannot name its row in *every* column of
that pipeline is not ready to implement.

Validator gap worth closing inside P0' itself: only the OUTER `"wavegen"` key
is known — the dict's *contents* are never key-checked or range-checked
(`_check_action_params` walks `params`, not `params["wavegen"]`). A typo like
`dutycycle` inside the dict validates green and silently does nothing even
after P0'. P0' should add a nested known-key set + range checks.

## 2. Candidate loop axes / plan-reachable settings

Per candidate: what it sweeps · device call existing today · safety class +
gate routing (per-operation model, roadmap Codex MAJOR-1) · validator limits ·
provenance column · sequencer compatibility · effort (S/M/L).

### C1 — wavegen frequency (laser repetition rate) — NEW LOOP AXIS
- **Sweeps:** laser trigger repetition rate → rep-rate dependence of collected
  charge (pile-up, polarization/trapping refill, DUT self-heating). Genuinely
  new physics reach for scan-TCT; nothing on the bench measures this today.
- **Device call:** `WaveformGenerator.set_frequency` (exists, SCPI sourced).
- **Safety:** EMITTING display tier; the SET itself is passive — the executor's
  emission window is `output_on()`..`output_off()` inside `_acquire_core`, and
  a per-point set lands between windows (output off). Gate routing: `set` =
  validator caps + envelope enumeration; `start` (emission) stays under the
  existing scan-start confirmation. No per-point live gate (see §4).
- **Validator:** config-declared `[f_min, f_max]` Hz (laser-trigger sane range,
  not the DG4162's 160 MHz ceiling). Interaction warning: frequency changes
  move the pulse-width/duty floor (`set_duty_cycle` docstring, DG4000 manual) —
  WARN when a plan sweeps frequency while carrying fixed duty params.
- **Provenance:** `swept/wavegen.frequency` commanded per point; readback
  best-effort per F2 (driver stores `_frequency`; instrument query exists).
- **Sequencer:** compatible (compiles to a set + existing steps; nothing
  blacklisted by `sequencer.assert_sequencer_compatible`).
- **Effort:** **M** — first true new axis; should BE the P3 registry-axis pilot.

### C2 — wavegen amplitude (and offset) — NEW LOOP AXIS, with a physics caveat
- **Sweeps:** trigger amplitude. Honest caveat (I own this workflow): on the
  current bench the PDL 800 is *triggered*, not modulated — laser power is a
  manual knob (`scan_plan` module docstring: power/delay are MANUAL_PAUSE by
  design). An amplitude sweep near threshold is a **trigger-threshold
  characterization** (useful once, diagnostic), not a power-response curve. It
  becomes a real power axis only if the wavegen ever drives an analog-modulated
  source (LED/diode). Propose it, but marked bench-dependent.
- **Device calls:** `WaveformGenerator.set_amplitude` / `set_offset` /
  `set_levels` (all exist).
- **Safety:** same routing as C1, plus a HARD validator cap: `set_levels`
  already warns above the PDL 800 trigger abs-max (±5 V at the connector); a
  *plan* exceeding the config cap must be an ERROR, not a warning — equipment
  damage is the real hazard here, and it is cappable on paper.
- **Provenance:** `swept/wavegen.amplitude` (+`offset`); readback best-effort.
- **Sequencer:** compatible. **Effort:** **S** incremental once C1's seam exists.
  Offset alone: low value — expose via per-acquire `params["wavegen"]` only.

### C3 — scope hardware averaging — PER-ACQUIRE SETTING first, axis later
- **Sweeps/sets:** scope-side `ACQuire:AVErage` count — distinct from the
  software `n_averages` loop in `_acquire_core` (N × `read_channel` averaged in
  Python). Hardware averaging is ~free wall-clock SNR for overnight maps; as an
  *axis* it characterizes noise floor vs averaging (occasional).
- **Device call:** `Oscilloscope.set_averaging` (exists; Tek-verified).
- **Safety:** BENIGN/passive. BUT: non-Tek vendors **log a warning and leave
  the scope unchanged** (`set_averaging`) — a silent no-op. A plan recording a
  swept value that was never applied is exactly the provenance sin the spine
  ends. Validator needs a capability flag following the
  `PlanLimits.camera_available` pattern (fail-closed default False).
- **Provenance:** `swept/scope.hw_averaging` (query form exists on Tek).
- **Sequencer:** compatible. **Effort:** **S** as a per-acquire param (rides
  P0''s param-apply seam verbatim); **M** as a full axis. Do the S first.

### C4 — camera exposure / gain — CAPTURE_PHOTO PARAMS first, axis later
- **Sweeps/sets:** per-photo exposure/gain — exposure bracketing for survey
  mosaics, anti-saturation for beam-spot metrology (feeds M-track), focus-stack
  quality. Full axis only for a dedicated camera characterization.
- **Device calls:** `CameraBlackfly.set_exposure` / `set_gain` (exist), and
  `get_frame_with_meta` already returns chunk-readback ACTUAL exposure/gain
  (`FrameMeta`) — the rare candidate with real hardware readback for free.
- **Safety:** passive (CAPTURE_PHOTO is deliberately not danger-marked —
  `plan_compiler.CapturePhotoStep` docstring). Validator: exposure/gain ranges
  from config; gated behind existing `camera_available`.
- **Provenance:** extend the `camera/` group per-frame attrs with
  commanded+actual exposure/gain (writer already tags `frame_point_index`).
- **Sequencer:** compatible. **Effort:** **S** (new CAPTURE_PHOTO params:
  `exposure_us`, `gain_db` in `_KNOWN_ACTION_PARAMS`); **M** as an axis.

### C5 — time / stability loop — NEW AXIS SEMANTICS (wall-clock)
- **Sweeps:** elapsed time. `Axis` values become wait-until setpoints
  (`values=[0, 600, 1200, ...]` s): the "move" is an abortable wait to
  `t_start + value`, then children run. Overnight drift runs: laser stability,
  charge vs time at fixed bias, thermal correlation against the slow-control
  snapshot already taken per point (`_acquire_core` → `slow_control`).
- **Device call:** none — `_abortable_sleep` already exists; the new work is
  semantics: pause interaction (recommend: schedule stays wall-clock anchored,
  missed setpoints are SKIPPED and counted, never silently shifted — the
  per-point `ScanResult.timestamp` is already the honest actual), estimate
  support (`plan_estimate` walks the stream; last setpoint = runtime), and a
  validator cap (`max_duration_s`).
- **Safety:** passive itself; the interlock story already holds (slow-control
  policy runs per acquire and per `ReadSlowControlStep`). Recommend a validator
  WARNING when a plan spans hours with no `READ_SLOW_CONTROL` cadence.
- **Sequencer:** compatible and *intended* for it — note the deliberate
  `timeout_s=None` no-expiry default in `arm_envelope.envelope_from_plan`
  (an overnight queue must not have its envelope lapse mid-night); a time-loop
  plan makes that default load-bearing, so the arm summary must show duration.
- **Provenance:** `swept/time.elapsed_s` commanded + existing `timestamp`.
- **Effort:** **M/L** — the only candidate that changes executor semantics.

### C6 — bias dwell/soak refinements — NO GRAMMAR CHANGE (disagreeing with the menu)
The bias axis already carries per-loop `settle_s`, per-step ramp shaping
(`LoopBlock.ramp_step_V/ramp_delay_s` → `BiasStep`, executor `_ramp_bias`), a
per-value `WAIT` child (`plan_from_config.plan_from_voltage_scan_config` emits
exactly this for `hold_delay_s`), and explicit `values` lists for asymmetric
soaks (long first-point soak = `WAIT` before the loop; hysteresis = up-then-down
`values`). Everything genuinely useful is expressible today. Proposal: a
documented pattern page + gallery routines, not new fields. **Effort: S (docs).**

### C7 — REPEAT / statistics axis (crew missed it) — NEW TRIVIAL AXIS
A dimensionless repetition axis (`values=[0..N-1]`, no device call, "move" is a
no-op) to take M *separately saved* points at one coordinate — reproducibility,
jitter distributions, and the natural inner axis for C5 stability runs. Today
this needs the hack of a stage loop with repeated identical values (works —
emit-on-change suppresses the moves — but reads as a lie in the plan tree).
Cheap, pure, and it makes several gallery routines honest. **Effort: S.**

## 3. Routine example gallery (v1 = YAML in `TCT_app/routines/`, existing Save/Load path)

`TCT_app/routines/` does not exist yet; v1 creates it as plain `ScanPlan` YAML
loadable via `PlannerPanel._on_load_routine` → `ScanPlan.load_yaml`. No new UI.
The six "today" routines below are the natural `tests/fixtures/routine_corpus/`
freeze (roadmap P2-entry artifact, ≥5 real plans — marked ⊕).

| # | Routine | Plan-tree sketch (loop nesting → leaves) | Runs today? | Corpus ⊕ |
|---|---|---|---|---|
| R1 | CCE(V) map | bias_V → stage_x → stage_y(snake) → ACQUIRE+SAVE | yes — IS the one built-in (`planner_panel._default_template_plan`) | ⊕ |
| R2 | IV-vs-position | stage_x → stage_y → bias_V → WAIT+ACQUIRE+SAVE | yes | ⊕ |
| R3 | Focus stack | stage_z → CAPTURE_PHOTO (+ optional ACQUIRE+SAVE) | yes | ⊕ |
| R4 | Survey+measure combo | stage_x → stage_y(snake) → CAPTURE_PHOTO+ACQUIRE+SAVE | yes | ⊕ |
| R5 | Depletion-voltage fast-scan | bias_V(coarse, reduce="charge") → ACQUIRE+SAVE | yes | ⊕ |
| R6 | Backlash/repeatability raster | stage_x(values, direction reversals) → ACQUIRE+SAVE | yes | ⊕ |
| R7 | Duty-cycle characterization | bias_V(fixed) → sibling ACQUIREs, each `params["wavegen"]["duty_cycle"]` | post-P0' (params inert today) | joins corpus post-P0'; doubles as the P0'→P1 equality oracle |
| R8 | Overnight stability run | time(interval) → READ_SLOW_CONTROL+ACQUIRE+SAVE | needs C5 (v0 approximation today: repeated-values loop + WAIT) | — |
| R9 | Rep-rate response | wavegen_freq → REPEAT → ACQUIRE+SAVE | needs C1 (+C7) | — |
| R10 | Trigger-threshold scan | wavegen_amplitude → ACQUIRE+SAVE | needs C2; bench-dependent (see C2 caveat) | — |

## 4. Safety review per candidate

**Emission question (C1/C2, and P0' duty):** does changing emission parameters
need an `ArmedEnvelope` extension or a new `emission_interlock` route? My
position: **no new live gate now; extend the envelope's enumeration when the
axes land (P3); reserve `emission_interlock` as the per-operation route name
for the capability layer (P1+), per the roadmap's per-operation routing.**
Argument: the emission EVENT (`output_on`) already fires per-acquire in every
scan today, authorized by the scan-start confirmation (non-negotiable 1) — a
sweep changes emission *parameters*, whose hazards are equipment-bound (PDL
trigger abs-max → hard validator cap, C2) and operator-surprise-bound (laser
firing faster/longer than expected → enumerable at arm time). Both are paper-
cappable; a per-point live gate would be unusable for exactly the reason
`ScanController._move_action` chose one motion confirm per run. Crucially the
interim is already fail-closed: `arm_envelope` recognizes only the `hv_ramp`
and `move` kinds and DENIES any other `DangerAction` kind — so if an
implementer danger-marks wavegen steps early, armed runs *stop*, they do not
sneak through. The P3 change is: envelope gains an emission section (freq/amp
ranges, shown in `summary` at arm time), validator caps from config, executor
stays within — same shape as HV today.

Per candidate: **C1/C2** — EMITTING tier, `set` passive (output off between
acquire windows in `_acquire_core`), routing as above; sequencer-compatible;
for unattended queues the envelope summary must enumerate the emission ranges
over ALL entries (same combined-envelope rule as HV, `sequencer` module
docstring). **C3** — passive; the real risk is the non-Tek silent no-op →
fail-closed availability flag in `PlanLimits` (camera_available pattern), else
recorded sweeps lie. **C4** — passive; ranges from config; chunk readback makes
it the F2 best-effort-readback showcase. **C5** — passive; unattended-first
design; `ManualPauseStep` stays blacklisted
(`sequencer._SEQUENCER_INCOMPATIBLE_STEPS`) so a "change laser power" pause can
never ride an overnight queue; envelope no-expiry default becomes load-bearing
→ arm summary must state total duration; recommend slow-control-cadence
WARNING. **C6/C7** — passive, no new gates.

## 5. Effort classing + recommended pick order

| Cand | What | Effort | Stage it rides | Safety weight |
|---|---|---|---|---|
| C3 | scope hw averaging (per-acquire param) | S | P0' param seam | low (needs availability flag) |
| C7 | REPEAT axis | S | P3 (or enum-freeze exception at P2) | none |
| C4 | camera exposure/gain (CAPTURE_PHOTO params) | S | P0'-style params | low |
| C2 | wavegen amplitude/offset | S (after C1) | P3 | medium (hard cap) |
| C6 | bias dwell patterns (docs) | S | anytime | none |
| C1 | wavegen frequency axis | M | **P3 pilot** | medium (EMITTING enumeration) |
| C5 | time/stability loop | M/L | post-P3 | medium (unattended semantics) |

**Recommended pick order for Kaya (post-P1 wave):**
1. **C3** — smallest step, same seam P0' just built, immediate SNR payoff on
   every overnight map; forces the availability-flag pattern we need anyway.
2. **C1** — the first true new axis and the natural P3 registry pilot; unlocks
   R9 (new physics), drags C2 in nearly free.
3. **C5** — highest-value new *capability* (overnight drift runs, R8) but the
   costliest semantics; schedule after P3 so its axis is registry-born, never
   enum-frozen.
C7 tags along with whichever of P3/C5 lands first (it is an afternoon); C4
rides the M-track survey/metrology beat; C6 is a docs beat for Samantha with
my review. R1–R6 should be authored and frozen as the routine corpus **now** —
they need zero implementation and are the P2 entry artifact.

## Open questions (for Adam/Kaya)

1. C2 hard cap: config key location — per-device (`configs/devices.yaml`
   wavegen section, validated by `config_validator`) or per-plan limits
   (`PlanLimits`)? I lean config→PlanLimits at `start_plan`, same as HV range.
2. C5 pause semantics (skip-and-count vs shift) need a Mary review before
   design freeze — my skip-and-count recommendation trades completeness for
   schedule honesty.
3. Does the P0' beat own the nested `params["wavegen"]` key/range validation
   (§1 gap), or is that a separate S beat? I recommend: P0' owns it — applying
   unvalidated nested params is worse than dropping them.
4. R7-as-oracle: confirm the P1 equality gate consumes the R7 YAML from
   `TCT_app/routines/` (single source), not a test-local copy.
