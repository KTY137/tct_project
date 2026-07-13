# TCT cockpit-v5 — crew orchestration plan & session-restart handoff

## Context

This is the handoff for restarting the Adam-orchestrated session on the TCT
lab-control app. The current session ran a full night shift, then **hit its
token limit and killed two agents mid-write**; this session recovered them and
must now (a) close an open **HV safety gate** Mary found, (b) re-verify the
branch on the bench, and (c) work the remaining backlog. The plan is organized
so a fresh Adam can execute it top-to-bottom without re-deriving state.

- **Branch:** `design/cockpit-v5` — HEAD `f6e23c4`, pushed, **188 commits ahead
  of `main`**. Do NOT merge to main until the HV safety gate below is closed and
  the bench is green as a set.
- **Authoritative state files (read these first, in order):**
  `.claude/session_state.md` (file locks, landed commits, open findings,
  dirty-tree provenance) → `docs/TECH_DEBT.md` (full backlog, ranked) →
  `docs/NIGHT_SHIFT_20260712.md` (the giga-list) → `docs/design/feature_requests_v5.md`.
- **Golden rules (from `CLAUDE.md` "Session hygiene"):** update
  `.claude/session_state.md` on every dispatch/landing; run
  `.claude/beat_status.ps1` before every commit; stage **explicit paths only,
  never `-am`** (it sweeps another beat's in-flight work); never claim
  "landed / tests pass" without seeing it in `git log` / real output.
- **Test-lane policy (Kaya, ratified):** full suites + UI monkey
  (`test_ui_monkey.py`) + state fuzzer (`test_state_fuzz.py`) go to **sophonone**
  via `agent_env\bench_run.ps1 -Xdist`; per-beat work stays local + targeted.
- **venv invocation that WORKS** (Codex's "venv broken" was a wrong cwd): from
  `TCT_app/`, `$env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONPATH="C:\Users\nukei\Desktop\project_tct\TCT_app"; .\.venv\Scripts\python.exe -m pytest <targeted files> -q`.

### In flight at handoff (RECONCILE FIRST — check `git log` + task notifications)

Two beats were dispatched just before plan mode:
- **Paul — DONE + VERIFIED, UNCOMMITTED (plan mode blocked the commit).** MAJORs
  1 & 2 closed: `output_off`/`output_off_ch` disable now has its own `try`
  (never gated behind the cosmetic zero write); `_shutdown_channel`/`_output`
  isolates ramp/park/disable per attempt so the disable is attempted even when
  the ramp raises; a failed disable leaves `_output_on` UNKNOWN (never a false
  OFF). **165 targeted tests passed.** RESTART ACTION: just commit — do NOT
  re-run/re-do. Scoped paths: `devices/bias_supply_{iseg,keithley,e4control}.py`
  + `tests/test_driver_truth.py` ONLY (tree is dirty from Noah's live beat).
  Message: `fix(safety): the HV disable write must never be skipped by a failed
  ramp or zero-write`.
- **Paul — NOW COMMITTED as `df10f8e`** (HEAD). Wave 0 Paul-half is closed.
- **Noah — NOT DONE, ONLY PLANNED (still OPEN).** His beat produced a detailed
  implementation plan, not code — `tct_gui.py`/`gui/bias_panel.py` are UNCHANGED.
  RESTART ACTION: dispatch Noah to EXECUTE his plan (do not re-plan):
  MAJOR 3 = split `_safe_bias_shutdown` (`tct_gui.py:1122`) into two try blocks
  like `_bias_failsafe`; MINOR A = tripped-first branch in
  `bias_panel._derive_hv_state` (~648) using `getattr(r,"tripped",None) is True`
  (keeps the 3-field fake in `test_cockpit_batch_b_panels.py` green); MINOR B =
  `_IVWorker.run:102` breaks on `r.tripped is True`; new test file
  `tests/test_bias_trip_visibility.py` (8 tests). **Kaya decision Noah flagged:**
  his fix also makes the previously-silent compliance stop emit a reason notify —
  keep (default, honesty gain) or scope the notify to the latched-trip case only?

After Noah's half is committed and the tree is clean, run
`.claude/beat_status.ps1`, then proceed to Wave 0 step 2 (Mary re-review of BOTH
halves as a set).

### Recovered + committed this session (do NOT redo)

`22519fb` run-outcome in HDF5 (a trip-aborted run is no longer byte-identical
to a clean one; `outcome` defaults to `unknown`, never `finished`) ·
`ef79ac3` theme round-2 (real `setWindowOpacity` slider, 0.80 safety floor,
5 presets, Glass→"Surface tint") · `f6e23c4` Codex object-plane camera
calibration (pure numpy, printable target PDF).

---

## Wave 0 — CLOSE THE HV SAFETY GATE (blocks real-hardware use)

Mary's re-review of the driver batch: the auto-energize BLOCKER is closed, but
the **HV disable command can still be skipped whenever a preceding voltage
write fails**. This is the only thing standing between the branch and a real-HV
bench run. Paul + Noah beats (above) address it. On restart:

1. Confirm both landed and are green (targeted: `test_driver_truth.py`,
   `test_bias*.py`).
2. **Mary re-reviews the closure** (safety class, mandatory) — she must confirm
   `output_off`/`_shutdown_*`/`_safe_bias_shutdown` can never skip the disable,
   on every fail-safe path (ALARM fail-safe, EMERGENCY-OFF, ALL-OFF, app close).
3. Only when Mary signs off: **bench `-Xdist`** on the whole set
   (`agent_env\bench_run.ps1 -Branch design/cockpit-v5 -Xdist`). Last green as a
   set was `d091702` (1192 passed, 42 s); ~12 commits have landed since.

---

## Wave 1 — structural correctness (do before `-n auto` is the bench default)

- **StateMachine.transition() race** (`controller/state_machine.py:53`, Abel):
  unlocked check-then-act, called from GUI + worker threads. The parallel lane
  SURFACES it (~4/6 runs mislabel a terminal state — a clean run reported
  ABORTED). This is a **reporting defect, not a flake** — fix the race (lock or
  an SM-level invariant), do NOT quarantine
  `test_fault_injection_legacy::test_voltage_scan_compliance_trip_failsafe`.
- **`BiasChannel.output_on` footgun** (`devices/bias_supply_base.py`, Paul): it
  is a METHOD that switches HV ON, so `if bias.output_on:` is always truthy AND
  one typo from energizing. Rename (`enable_output()` / add `is_output_on`
  property) + a guard test/grep so the truthiness trap is unwritable.
- **QSettings isolation is structural, not a shim** (`gui/app_settings.py` new,
  Noah): the app names `QSettings("TCT","TCTSetup")` in ~6 places; until
  `2d4684b` the test suite wrote the developer's REAL registry. Route every
  consumer through one accessor. Add `pytest-xdist` to `TCT_app/requirements.txt`.
- **Shared worker-lifecycle primitive** (`gui/*.py`, ~22-25 sites, Noah, opus):
  hand-rolled `moveToThread`+`QThread`+`quit()`+`wait()` with divergent magic
  timeouts (motor_panel: 2000 ms vs 3000 ms for the same thread). Extract one
  tested `WorkerThread` helper; retire the recurring teardown/connection-order
  bug class. Fold in `status_widgets.py:333` `flash_button` unowned-timer fix.

---

## Wave 2 — data & analysis honesty (Jonathan)

- **Silent camera-frame drops** (`data/hdf5_writer.py:143-152`):
  `_save_camera_frame` `return`s on shape mismatch with no log/counter/attr, and
  a later `ds.resize()` zero-backfills the gap — indistinguishable from a real
  dark frame. Count + record dropped frames (a `frame_point_index` /
  `n_frames_omitted` attr); pairs naturally with the run-outcome contract just
  landed. Also add `frame_point_index` + `px_per_mm`/affine attrs the mosaic and
  metrology roadmap need.
- **V_dep fit quality** (`analysis/efield_analysis.py:190-241`,
  `gui/analysis_panel.py:886-904`): the depletion-voltage "estimate" is a bare
  2-point threshold crossing with no fit quality / bracket count / ambiguity
  flag, printed as authoritative; CCE ratios carry zero uncertainty. The v5
  Analysis artifact PROMISES fit-quality tiles — implement them.
- **Reference-channel baseline** (`devices/intensity_scope_ch.py`,
  `intensity_simulated.py`): ref amplitude/charge skip baseline subtraction
  while the DUT path baseline-corrects — a DC offset silently biases every saved
  `dut_charge_norm`. Move the named formula into `analysis/`, have both channels
  call it, and inject a baseline in the simulated backend so the suite can catch
  regressions. (Original Kings-retro RISK; still open.)

---

## Wave 3 — W1 taxonomy color sweep (Noah + Paul, per the D4 census)

Ground truth already produced: `docs/design/state_color_census.md` (Codex D4)
maps every state-color use to Paul's 9-rung ladder with file:line. Sweep:
- red-misuse → neutral/UNKNOWN (camera offline, output-unknown, MOVE STAGE row);
- green-on-nominal removals (connect/saved/valid/load);
- kill-switch escalation (ghost→outline→filled-red-with-volts);
- Monitor "All nominal" gated on ≥1 real reading;
- Z-focus "Find focus" button gets the motion class (it starts real motion but
  carries `state="primary"`).
Each batch: Mamoru pre-run → Mary review → `scripts/capture_panels.py` rerun →
Adam eyeballs the diff against `docs/design/feinschliff_gap_notes_adam.md`.

---

## Wave 4 — performance & camera panel (Noah)

- **scan_map_view redraw throttle** (`gui/scan_map_view.py:254-262,378-438`):
  `update_point()` rebuilds the FULL grid + `setImage` on EVERY point — cost
  grows with n, stutters the GUI thread on multi-thousand-point routines. Add
  incremental update / debounce. DAQ-latency-adjacent; do before giga-scans.
- **Camera Mono16 + binning** (`gui/camera_panel.py:476-479`): Mono16 display
  `>>4` + uint8 cast aliases (Kaya's "aliasing"); `set_binning()` never sets
  Sum/Average + no post-binning rescale (Kaya's "white screen at binning 2/4").

---

## Wave 5 — camera-metrology roadmap (Jonathan + Paul + Abel, staged)

Foundation is landed (`analysis/camera_calibration.py` affine + distortion
residuals, pure numpy; `analysis/mosaic_stitch.py`; `controller/repeatability.py`
phase-correlation; printable target `artifacts_codex/…v1.pdf`). Design in
`docs/design/camera_survey_metrology.md` + `docs/research/camera_optics_setup.md`.
Remaining, in order — **each stays pure-math/analysis until the very last step**:
1. Frame preprocessing for changing light (`prepare_metrology_roi`: ROI, dark/flat,
   local normalization, high-pass, saturated-pixel mask, correlation quality score).
2. 2D affine stage→camera self-calibration wired to real captures (not scalar px/mm).
3. Distortion validation report (residual vectors px + µm) as a preflight artifact.
4. **Closed-loop correction (LAST, safety-critical):** bounded P-controller —
   max-correction clamp, soft-limit check, **DangerGate-gated**, abort path, no
   silent motion. Integrates as a **Scan-Sequencer preflight step**, never inside
   the inner acquisition loop. Mandatory Mary review; Claude never drives real
   motors. Paper target is a smoke test only — final 2 µm truth needs a
   glass/chrome slide.

---

## Parked — needs Kaya (decisions only he can make)

- **v5 design ratification** (14 artifacts live) → unlocks W3 chrome collapse,
  W4 full panel recompositions, FormSheet rollout.
- **Sequencer envelope semantics**: one combined envelope per queue (Abel
  recommends) vs re-arm per routine (`feature_requests_v5.md` §7).
- **Slow-control UNAVAILABLE escalation** policy: a dead sensor safe-holds once,
  then is silently unmonitored — needs a re-alert/timeout rule to ratify.
- Ollama watcher restart with GPU env · command-palette allow-list · hover/lag
  verdict on the real display · target metrology precision goal (2 µm?).

---

## Crew routing (owners)

| Lane | Owner | Domain |
|------|-------|--------|
| devices/, HV, motion, drivers, SCPI | **Paul** (opus) | Wave 0, 1 (footgun), 5 |
| controller/, state machine, scan/run control | **Abel** (opus) | Wave 0 review-fixes, 1 (SM race) |
| gui/, tct_gui, theme, panels, threads | **Noah** (opus for safety/threads) | Wave 0, 1, 3, 4 |
| data/, analysis/, HDF5, physics | **Jonathan** | Wave 2, 5 |
| adversarial review (mandatory on safety) | **Mary** | every safety beat |
| repo bookkeeping / ledgers | **Kiroku** (haiku) | after each landing |
| drift sweeps + test suite | **Mamoru** (haiku) | pre-review gates |
| external research | **Prometheus** | metrology optics, SCPI manuals |

Discipline: one beat = one scoped commit; safety-critical (devices/, HV, motion,
scan logic) ALWAYS gets Mary; free lanes (Codex/Ollama via Daedalus) never idle.

---

## Verification

- **Per beat (local, targeted):** the venv invocation in Context above, only the
  test files the beat touches.
- **Per wave / before any merge (bench):**
  `powershell -File C:\Users\nukei\Desktop\agent_env\bench_run.ps1 -Branch design/cockpit-v5 -Xdist`
  — must be green as a set (target ≥ the last-known 1192 passed). If the bench is
  down, SAY SO; never pass a laptop run off as a green baseline.
- **Done-definition for real-HV readiness:** Wave 0 closed + Mary sign-off +
  one green bench `-Xdist` run on that HEAD.
