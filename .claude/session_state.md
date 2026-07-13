# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context — and is therefore exactly what a compaction or a killed session
destroys. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit.

Updated: 2026-07-13, **BIG WAVE session — plan approved by Kaya, execution
started.** Full plan (phases, tracks, beats, verification):
`C:\Users\nukei\.claude\plans\docs-restart-handoff-20260713-md-der-vol-cosmic-tome.md`.
This ledger tracks only LIVE state.

## HEAD

`design/cockpit-v5 @ 1d4c9e5` (pushed, 190 ahead of main). Tree clean except
untracked `artifacts_claude/`. All three killed-beat recoveries are committed
(`22519fb` run-outcome, `ef79ac3` transparency R2, `f6e23c4` camera calib).

## RATIFIED TODAY (Kaya, 2026-07-13, via AskUserQuestion — Kiroku: record in docs/DECISIONS.md)

1. **Sequencer envelope: ONE combined envelope per queue** — max HV, total
   travel, every routine named in arm text, single hold-3s; executor
   re-validates every step at runtime.
2. **IV compliance stop AND latched trip both emit a visible reason.**
3. **Transparency: Win11 acrylic/mica DWM backdrop** (content opaque), opacity
   slider stays independent, ship default "none" until Kaya's eyeball pass.
4. **Order: Wave 0 → SM-race + output_on footgun → feature tracks parallel.**
5. **Stitched-image feature in scope** (survey preset + mosaic view).
6. **Sensor orientation via `opencv-python-headless`** (ArUco fiducials +
   template matching, NO CNN — no dataset, no torch). Lives in NEW
   `TCT_app/vision/` package; `analysis/` layer contract stays numpy-pure;
   lazy import with clean degradation.

## 🚦 HV SAFETY GATE — BOTH halves LANDED, Mary set-review IN FLIGHT

- **Paul: `df10f8e`** (165 targeted green). Disable write can no longer be
  skipped by failed ramp/zero-write, all three real backends; failed disable
  ⇒ `_output_on` UNKNOWN, never false OFF.
- **Noah: `0f1c012`** (beat 0.1, Adam re-ran targeted: 18 passed). Two-try
  `_safe_bias_shutdown`; tripped-first `_derive_hv_state`; `_IVWorker` breaks
  on tripped BEFORE compliant + new `stopped(str)` signal → `notify(...,"warn")`
  with distinct trip/compliance texts (ratified #2); 10 new tests in
  `tests/test_bias_trip_visibility.py`.
- **Now:** 0.2 Mary set-review (`df10f8e` + `0f1c012`, all fail-safe paths) →
  0.3 bench `-Xdist`. **Real HV stays forbidden until 0.3 is green.**

## IN-FLIGHT BEATS (file locks — never stage a CLAIMED path)

| Beat | Agent | CLAIMED paths |
|---|---|---|
| 0.2 HV-gate set-review | Mary (read-only) | none |
| E7a CV compat research | Prometheus | `docs/research/sensor_alignment_cv.md` |

## QUEUE (after 0.2 sign-off)

0.2 Mary set-review → 0.3 bench `-Xdist` → Phase 1 (1.1 Abel SM-transition
lock ∥ 1.2 Paul output_on rename + Codex call-site sweep) → four lanes per the
plan file (A sequencer / B planner+HDF5 / C backdrop / D e-field / E metrology
+ stitch + sensor-align).

## BENCH

Last verified green: **`d091702`, 1192 passed, 42 s (`-n auto`)**. Everything
since is NOT bench-verified as a set. Next bench run = beat 0.3 (after Noah
lands + Mary signs off). Reachability:
`ssh -o BatchMode=yes Administrator@100.119.126.9 echo up`.

## PARKED — needs Kaya

v5 design ratification (14 artifacts) · Ollama watcher restart with GPU env ·
command-palette allow-list · hover/lag verdict on the real display · metrology
precision goal (2 µm? needs glass/chrome slide — paper target is smoke-test
only) · backdrop eyeball checklist (comes with beat C3).
