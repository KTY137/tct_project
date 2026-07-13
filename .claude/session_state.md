# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context — and is therefore exactly what a compaction or a killed session
destroys. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit.

Updated: 2026-07-13 ~02:00, **after the session hit its token limit and killed
two agents mid-write.** Read the WARNING section before touching anything.

## HEAD

`design/cockpit-v5 @ df10f8e` (pushed, 189 ahead of main).

## 🚦 HV SAFETY GATE — HALF CLOSED. Do NOT run real HV yet.

- **Paul's half: DONE + COMMITTED (`df10f8e`, 165 tests green).** The HV disable
  write (`:VOLT OFF` / `:OUTP OFF` / `setOutput(False)`) can no longer be skipped
  by a failing ramp or zero-write, in all three real backends. A failed disable
  leaves `_output_on` UNKNOWN, never a false OFF.
- **Noah's half: NOT DONE — ONLY PLANNED (still OPEN).** Noah's beat produced a
  detailed plan, not code — `tct_gui.py` and `gui/bias_panel.py` are UNCHANGED.
  Still open: MAJOR 3 (`_safe_bias_shutdown` in `tct_gui.py:1122` runs ramp +
  output_off in ONE try → split into two, mirror `_bias_failsafe`); MINOR A
  (`bias_panel._derive_hv_state` ~648 ignores `reading.tripped` → a manual-session
  trip shows a healthy SETTLED tile; add a tripped-first branch, `is True`
  discipline, use `getattr(r,"tripped",None)` so the 3-field fake in
  `test_cockpit_batch_b_panels.py` stays green); MINOR B (`_IVWorker.run:102`
  ignores `r.tripped` → IV sweep steps HV through a latched trip). Noah's ready
  implementation plan (new test file `tests/test_bias_trip_visibility.py`,
  8 tests) is in his beat report — RESTART: just dispatch him to execute it.
  ONE OPEN QUESTION Noah flagged for Kaya: his fix also makes the
  previously-silent compliance stop emit a reason notify — keep (honesty gain)
  or scope the notify to the latched-trip case only? Default: keep.
- **Then:** Mary re-reviews BOTH halves as a set (mandatory, safety) → bench
  `-Xdist` → only then is the branch real-HV-ready.

## 🚨 OPEN SAFETY FINDINGS — the branch is NOT bench-trustworthy for real HV

Mary re-reviewed `f4f8e7b` + `c966819` and returned **REQUEST-CHANGES**. Her
BLOCKER (auto-energize on ramp-to-zero) is genuinely CLOSED and independently
verified on all four backends. But she reproduced **three MAJORs that are still
open**, all on the fail-safe path, all of the same shape:

> **The HV DISABLE command can be silently skipped whenever a preceding
> voltage write fails.**

1. `bias_supply_iseg.py:437`, `bias_supply_keithley.py:291`,
   `bias_supply_e4control.py:283` — `output_off()/output_off_ch()` issue the
   cosmetic zero-volt write AND the actual HV-disable write inside ONE `try`,
   with an early `return` on failure. A transient failure of the FIRST write
   suppresses the SECOND: `:VOLT OFF` / `:OUTP OFF` / `setOutput(False)` — the
   single most safety-critical command in the app — is never sent. Paul's own
   comments note dropped frames are "common on the USB-VCP transport".
   *Fix:* the disable write gets its OWN try, never gated on the zero write.
2. `bias_supply_iseg.py:334` `_shutdown_channel` (+ the Keithley/e4control
   twins) — the ramp runs in the SAME try as the `:VOLT 0` / `:VOLT OFF`
   writes, so a raising ramp skips the disable on BOTH retry attempts.
   Reproduced: output ON at −300 V, transport rejects value writes but would
   accept `:VOLT OFF` → disconnect() emits two rejected writes, `:VOLT OFF` is
   NEVER issued, channel left believed-ON, disconnect raises.
   *Fix:* ramp in its own try inside each attempt, or move the OFF writes into
   a `finally`.
3. `tct_gui.py:1112` `_safe_bias_shutdown()` — `ramp_to(0.0)` and
   `output_off()` in the SAME try/except; a raising ramp skips the output-off.
   This falsifies Paul's claim that "every fail-safe caller guards the ramp
   separately". Called from closeEvent, _teardown and the Disconnect button.
   *Fix:* split into two try blocks, exactly like
   `scan_controller._bias_failsafe:1679-1686`.

Plus two MINORs she found in the same pass:
- `gui/bias_panel.py:649` — the HV STATE tile derives its state from
  `reading.compliant` ONLY. During a MANUAL HV session a latched hardware trip
  (arc, external inhibit, current trip) shows a healthy **SETTLED** tile. Abel
  wired the trip into the scan controller; nobody wired it into the operator's
  own HV panel.
- `gui/bias_panel.py:102` — the panel's own IV-sweep worker breaks on
  `r.compliant` but ignores `r.tripped`: on an iseg it keeps stepping HV and
  emitting points straight through a latched trip. (Same bug Abel fixed in
  `_run_voltage_scan`, in a second unflagged place.)

Her verdict, verbatim: *"close those three small fixes and this branch is
bench-ready for real HV."* Owners: Paul (1, 2), Noah (3, + the two bias_panel
MINORs).

## ⚠️ DIRTY TREE — two agents were killed mid-write; VERIFY, do not trust

The session hit its token limit and terminated two agents while they were
writing. Their partial work is on disk, **unverified and uncommitted**. Do NOT
commit any of it without reading the diff and running its tests.

| Dirty paths | Whose | State at death |
|---|---|---|
| `data/hdf5_writer.py`, `SCAN_DATA_FORMAT.md`, `controller/scan_controller.py`, `gui/analysis_panel.py`, `tests/test_run_outcome.py` (new) | **Jonathan** — run-outcome in HDF5 (a trip-aborted run was byte-identical to a clean short one) | killed at "Now let's update SCAN_DATA_FORMAT.md" — probably near-complete, tests unrun |
| `gui/style.py`, `gui/theme_editor.py`, `tct_gui.py`, `gui/detachable_tabs.py`, `tests/test_theme_editor.py` | **Noah** — theme round 2 (real window-opacity slider 0.80–1.00, rename Glass→Surface tint, 5 built-in presets) | killed mid-verification; his first two commits DID land (see below) |
| `analysis/camera_calibration.py`, `tests/test_camera_calibration.py`, `artifacts_codex/` (new) | **Codex** (Kaya's parallel session) | complete; 12 tests pass. Pure-numpy affine + distortion calibration, printable metrology target PDF. No conflict with the above. |

## LANDED tonight (all pushed)

`5730644` four-start-path guard · `9b91ed1` 1D slicer · `c12a6a1` theme editor ·
`7663d74` coordinator fail-closed · `8d302fc` mosaic stitch math · `e3d323f`
docs/bench-checklist · `5e70b10` UI monkey harness · `7892a26` slicer
stale-run provenance fix · `a4d05f6` **HV ramp behind DangerGate** · `f2b9acc`
RATIFIED jog-ungated · `3f6e2b7` z-focus/voltage arm Pause+Abort · `81d1f6a`
orchestrator ledger · `99c527e` session-hygiene rules · `bf9e009` **motion
DangerGate** · `b4896d3` test-lane policy · `2d4684b` **xdist isolation leak
killed (tests were writing the REAL registry)** · `9c207a1` **classic loops had
NO slow-control interlock** · `c269e93` driver-truth batch · `56da3da`+`d091702`
stale-pin fixes · `c1346c7` **trip wired into the viewer** · `c966819`
**latched trip aborts the scan** · `b958bc4` **black box behind every label
killed** · `b7e9b6b` debt · `f4f8e7b` **ramp-to-zero never energizes**

## BENCH

Last verified green: **`d091702`, 1192 passed, 42 s parallel** (`-n auto`).
Five commits have landed SINCE that run (`c1346c7`, `c966819`, `b958bc4`,
`b7e9b6b`, `f4f8e7b`) and are **not yet bench-verified as a set**. First action
after the tree is clean:
`powershell -File C:\Users\nukei\Desktop\agent_env\bench_run.ps1 -Branch design/cockpit-v5 -Xdist`

## NEXT BEATS (queued)

1. **Mary's three MAJORs above** — the HV disable must never be skippable.
   This gates real-hardware use. Do this first.
2. **StateMachine.transition() is unlocked check-then-act** — the parallel lane
   surfaces it (~4/6 runs mislabel a terminal state). A REPORTING defect, not a
   flake; do not quarantine the test. Must land before `-n auto` becomes the
   bench default. *Owner: Abel.*
3. `gui/app_settings.py` accessor so QSettings isolation is structural, not a
   conftest shim (the app names `QSettings("TCT","TCTSetup")` in ~6 places).
   *Owner: Noah.*
4. `BiasChannel.output_on` is a METHOD that switches HV ON — a bound method is
   always truthy, so `if bias.output_on:` is both wrong and one typo from
   energizing the supply. Rename + guard test. *Owner: Paul.*
5. Finish/verify the two killed beats (see DIRTY TREE).

## PARKED — needs Kaya

v5 ratification (14 artifacts) · sequencer envelope semantics · Ollama watcher
restart with GPU env · command-palette allow-list · hover/lag verdict on the
real display · the camera-metrology roadmap Codex started (affine + distortion
calibration is built; closed-loop correction is NOT, and must be
DangerGate-gated + bounded before it ever commands a motor).
