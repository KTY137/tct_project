# Routine corpus — frozen saved-plan fixtures

**Frozen: 2026-07-13.** These six files are byte-identical copies of
`TCT_app/routines/R1..R6*.yaml` at freeze time. They are the P2-entry artifact
required by `docs/ROADMAP_MASTERPLAN.md` §"Gate enforcement" ("freeze >=5 real
saved plans as `tests/fixtures/routine_corpus/`").

## What this corpus is for

The P-track migrates the plan grammar (`Axis` -> `AxisSpec`, registry-backed
axes, a versioned plan JSON). Risk #6 in the roadmap risk register is "grammar
migration breaks saved routines". This corpus is the evidence base that catches
it: every P-stage replays these plans and asserts they still load and validate
byte-identically (or, where a versioned migration is intentional, the byte-diff
is recorded and Kaya-ratified).

## Freeze invariants (do not re-derive)

- **Predates P2.** This corpus was frozen BEFORE any `AxisSpec`/registry work.
  A P2/P3 change that alters how these plans serialize must show its byte-diff
  in the ledger, never silently rewrite the corpus.
- **Corpus size >= 5 (vacuous-pass forbidden).** The replay gate asserts the
  corpus contains at least five plans before running any comparison, so an empty
  or truncated corpus fails loudly instead of passing vacuously. Six are frozen
  here; five is the floor.
- **Byte-diff results land in the ledger.** Each replay run appends its result
  (corpus size, per-file byte-diff verdict, commit SHA, date) to
  `.claude/session_state.md` / the roadmap ledger — the durable-evidence rule.
- **Today's 4-axis grammar only.** Every plan uses only the four `scan_plan.Axis`
  members (`stage_x`, `stage_y`, `stage_z`, `bias_V`) and the six `ActionType`
  leaves. No invented axes. New candidate axes (wavegen freq/amplitude, time,
  repeat, per-acquire scope/camera params) are documented in
  `docs/design/planner_routines_v2.md` and do NOT appear here until they land.

## Contents (all validate with 0 errors / 0 warnings)

| File | Routine | Plan tree |
|---|---|---|
| `R1_cce_v_map.yaml` | CCE(V) map | `bias_V -> WAIT(bias settle) -> stage_x -> stage_y(snake) -> ACQUIRE+SAVE` — derived from `planner_panel._default_template_plan` plus an explicit post-bias-change settle WAIT (see R1 note) |
| `R2_iv_vs_position.yaml` | IV-vs-position | `stage_x -> stage_y -> bias_V -> WAIT+ACQUIRE+SAVE` |
| `R3_focus_stack.yaml` | Focus stack | `stage_z -> CAPTURE_PHOTO` |
| `R4_survey_measure.yaml` | Survey+measure combo | `stage_x -> stage_y(snake) -> CAPTURE_PHOTO+ACQUIRE+SAVE` |
| `R5_depletion_fast_scan.yaml` | Depletion-voltage fast scan | `bias_V(coarse, reduce="charge") -> WAIT(bias settle) -> ACQUIRE+SAVE` |
| `R6_backlash_raster.yaml` | Backlash/repeatability raster | `stage_x(explicit values, direction reversals) -> ACQUIRE+SAVE` |

R1 note: the on-disk file stores the description em dash as UTF-8 for
readability; under the canonical serializer `ScanPlan.load_yaml(R1).to_yaml()`
differs from the file only by re-escaping that em dash to `—` (verified) —
the WAIT and every loop round-trip byte-identically. R1 is DERIVED from
`_default_template_plan()` but adds an explicit `WAIT seconds: 0.5`
(`reason: bias settle`) as the first child of the bias_V loop, so acquisition
does not begin before the detector settles after each HV step. It therefore no
longer round-trips byte-for-byte to `_default_template_plan().to_yaml()` (the
built-in template lacks that dwell); giving the code template the same
post-bias-change settle is a follow-up in the `gui/planner_panel.py`-owning
beat. R7 (duty-cycle characterization) joins the corpus only after P0' makes
`params["wavegen"]` non-inert — see the C1 proposal.

## How they were authored / validated

Constructed through the real `controller.scan_plan.ScanPlan` schema and saved via
`ScanPlan.save_yaml` (the same serializer `PlannerPanel._on_save_routine` uses),
so they load through the existing Load-routine path
(`PlannerPanel._on_load_routine` -> `ScanPlan.load_yaml`). Each was validated
headless with `controller.scan_plan_validator.validate_plan` against generous
bench-realistic `PlanLimits` (stage +/-25 mm, HV +/-500 V, camera available):
all six return zero ERRORs and zero WARNINGs.
