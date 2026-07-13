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

## ✅ HV SAFETY GATE — CLOSED 2026-07-13. Branch is REAL-HV-READY at `88907a4`.

- **Mary 0.2 verdict: APPROVE** on `df10f8e` + `0f1c012` as a set. Seven
  fail-safe paths traced, disable not skippable on any (ALARM failsafe,
  emergency-off, all-off, closeEvent/_teardown, disconnect+reload, scan-abort,
  driver `_shutdown_*`); 145 targeted tests green in her pass. Non-blocking
  follow-ups: (a) one-poll trip-detection lag in `_IVWorker` (low-risk, latched
  supply rejects re-enable); (b) PRE-EXISTING `bias_panel.py:855`
  `finished→setEnabled` lambda runs on worker thread — fold into the Wave-1
  WorkerThread trailing batch; (c) NIT e4control disconnect state cosmetics.
- **0.3 bench `-Xdist` GREEN: 1349 passed, 1 xfailed, 38.51 s** on the
  `88907a4` set (target was ≥1192). Output seen by Adam in the bench log.
  Branch pushed: `origin/design/cockpit-v5 @ 88907a4`.
- Real-HV readiness applies to the VERIFIED set `88907a4`; later commits need
  the next per-wave bench run before any real-HV session on them.

## IN-FLIGHT BEATS (file locks — never stage a CLAIMED path)

PHASE 1 CLOSED 2026-07-13: `26bcf95` + `034c176` landed, Mary APPROVE (2 NITs,
no code changes), bench GREEN **1372 passed** @ `ee9f48d`, pushed. FOUR FEATURE
LANES NOW OPEN (first beats dispatched):

| Beat | Agent | CLAIMED paths |
|---|---|---|
| B2 capture_photo block | Abel (opus) | `TCT_app/controller/scan_plan.py`, `plan_compiler.py`, `scan_plan_validator.py`, `plan_estimate.py`, `scan_controller.py` (dispatch), tests: plan_compiler/validator/executor |
| D3 analysis fit-quality tiles | Jonathan | `TCT_app/gui/analysis_panel.py`, `TCT_app/tests/test_analysis_panel_load_run.py` |
| A4 SequenceCoordinator (Mary fwd-reqs baked in) | Noah (opus) | `TCT_app/gui/sequence_coordinator.py` (new), `TCT_app/tests/test_sequence_coordinator.py` (new) |
| C3-mini hygiene (hex→token + dialog construction-apply) | Noah (2nd) | `TCT_app/gui/settings_window.py`, `TCT_app/gui/theme_editor.py` (construction only), `TCT_app/tests/test_theme_editor.py`, `TCT_app/tests/test_no_inline_hex_gui.py` |
| Bookkeeping batch 2 | Kiroku | `docs/ARCHITECTURE.md`, `docs/TECH_DEBT.md`, `docs/BENCH_CHECKLIST.md`, `docs/config_keys.md`, research index |
| Codex style audit (Kaya request) | Codex lane | `docs/design/codex_style_audit_20260713.md` |

C2 LANDED `c66ee05` (backdrop settings/fan-out, 124+135 green; eyeball
checklist → BENCH_CHECKLIST via Kiroku batch 2). NOTE for C3-mini vs A4:
both are Noah-persona instances on DISJOINT files — C3-mini touches
theme_editor.py construction only; A4 does not touch theme files.

## ⚠️ MARY TRACK-A VERDICT: REQUEST-CHANGES (2026-07-13, on f83b184+e2ba013+ba6128b)

Core is sound: NO union authority leak (gate is thread-local to _run_plan;
manual panels use the separate QtDangerGate); fail-closed matrix holds;
timeout_s=None accepted (monotonic clock). But:
- **MAJOR (A3.1, Abel, AFTER B2 lands — same file):** `park_safe()`
  hardcodes the PRIMARY bias channel (`scan_controller.py:647`); a sequence
  armed on a non-primary channel parks the wrong one. Fix: iterate
  `self._dev.bias_channels` (idempotent on idle channels) or pass the armed
  channel. Add non-primary test.
- **MINOR (A3.1):** raising PreflightHook strands entry in PREFLIGHT
  (`sequencer.py:184`) → engine converts hook exceptions to FAILED + halt.
- **MINOR (A3.1):** `record_outcome("unknown")` raises; writer can persist
  "unknown" (crashed run) → ANY word except literal "finished" must halt.
- NIT for A4: entries must be built from DEEP-COPIED/serialized plans
  (in-memory ScanPlan is mutable by reference).
- **FORWARD REQUIREMENTS for A4/A5 (Noah briefs, verbatim):** (1) never
  wire the union ArmedEnvelopeGate into any manual panel — manual stays on
  the per-action QtDangerGate; (2) manual danger controls (HV ramp, IV,
  jog) must be DISABLED while a sequence runs (panels bypass
  _refuse_if_active by talking to devices directly).
| C2 backdrop settings/fan-out | Noah | `TCT_app/gui/style.py`, `TCT_app/gui/theme_editor.py`, `TCT_app/tct_gui.py`, `TCT_app/gui/detachable_tabs.py`, `TCT_app/tests/test_backdrop.py`, `TCT_app/tests/test_theme_editor.py` |
| Codex style audit (Kaya request) | Codex lane (watcher bff72hs4q running) | `docs/design/codex_style_audit_20260713.md` |

Mamoru test-suite audit VERDICT (2026-07-13): suite is clean — 994 tests, no
duplicates (overlaps = layered defense, KEEP), no stale scaffold, no cost
outliers. NO cleanup beat needed. One hygiene rider for Noah: inline hex
`#c0392b` in `gui/settings_window.py:1699` → style token (fold into C3).
Marker proposal (@hardware_safety etc.) deferred to a future architecture
beat. --durations pass at a future bench gate remains nice-to-have.

RIDERS pending (fold into owners' next beats, do not lose):
- ~~Paul: camera_blackfly TODO rewrite~~ DONE inline by Adam (`00abe9c`,
  comment-only).
- Abel (after A3.1): baseline_samples plumbing — option (b) per Paul's D4
  handoff: reuse existing `analysis.baseline_samples` config value when
  constructing ScopeChannelMonitor in device_manager (no new key); no
  validator change needed then. Files: controller/device_manager.py (+ test).
- Noah C3: settings_window.py:1699 hex → style token.
- Kiroku batch: research index (+2 notes), TECH_DEBT camera row close + D4
  Kings-retro RISK close, BENCH_CHECKLIST TODO(bench) items (binning SpinView,
  ref-window pulse-free), ARCHITECTURE for sequencer.py/backdrop.py/
  waveform_analysis.correct_baseline + intensity_base mirror.

Lane landings so far: `f83b184` A1 · `e2ba013` A2 · `ba6128b` A3 (Track-A
set complete, Mary batch review IN FLIGHT) · `06de0dc` B1 · `df43ca9` C1 ·
`f1e1712` E1 · `95b27c7` D1 · `a99829e` CLAUDE.md test-economy rules.

## 🌙 NIGHT MANDATE (Kaya, 2026-07-13 ~04:10, asleep until ~10:00)

Push through the approved plan autonomously; if the queue empties, continue
with the trailing batches (Wave-3 color sweep per state_color_census, scan_map
throttle, app_settings accessor, WorkerThread primitive) — stay within the
ratified backlog, invent no new scope. At the end: VERIFY all features against
the plan file (git log is the only truth), Mamoru audits the claims, final
bench gate + push, report in docs/NIGHT_REPORT_20260713.md + summary message.
Session-only crons armed: checkpoints 06:17 + 08:23, report job 09:53.

LESSON (2026-07-13): while a beat holds `devices/` locks, do NOT run
cross-cutting targeted suites — Adam raced Paul's half-written rename
(abstract `enable_output` broke DeviceManager fixtures transiently). Verify
lock-holder-independent tests only, or wait for the landing.

TEST ECONOMY (Kaya, 2026-07-13 — "we test too much"): the implementing
agent's pasted pytest output tail IS the verification. Adam re-runs ONLY on
(a) report/diff inconsistency, (b) out-of-scope diff, or (c) one combined
reconciliation run after several beats touched the same area. Mary re-runs
only to reproduce a concern. Bench only at phase/track gates + pre-merge.

NOTE deviation from plan (Adam, justified): 1.2 call-site sweep NOT sent to
Codex — an HV-enable rename is safety-class; lane rule "safety stays with the
Claude crew" wins. Paul does the whole beat.

LANDED this session: `0f1c012` Wave-0 GUI half (Noah) · `f57c00e` E7a research
note (pin `opencv-python-headless==4.9.0.80`, DICT_4X4_50, pose ladder) ·
`88907a4` six ratified decisions in docs/DECISIONS.md (Kiroku, append-only
verified) · `26bcf95` SM transition race fix (Abel, beat 1.1 — pure-SM tests
16 passed; device-dependent fuzz/executor re-run pending after 1.2 lands).

## QUEUE

0.3 green + 1.1/1.2 landed + Mary batch-review on 1.1+1.2 → open the four
feature lanes per the plan file (A sequencer / B planner+HDF5 / C backdrop /
D e-field / E metrology + stitch + sensor-align). Push branch after bench
green.

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
