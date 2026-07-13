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

| Beat | Agent | CLAIMED paths |
|---|---|---|
| Phase-1 batch review (26bcf95+034c176) | Mary (read-only) | none |
| Post-Phase-1 docs sweep | Kiroku | `docs/ARCHITECTURE.md`, `docs/TECH_DEBT.md`, `docs/RESTART_HANDOFF_20260713.md`, `docs/DECISIONS.md` (status line of today's order entry only) |
| Codex style audit (Kaya request) | Codex lane (watcher bff72hs4q running) | `docs/design/codex_style_audit_20260713.md` |

LESSON (2026-07-13): while a beat holds `devices/` locks, do NOT run
cross-cutting targeted suites — Adam raced Paul's half-written rename
(abstract `enable_output` broke DeviceManager fixtures transiently). Verify
lock-holder-independent tests only, or wait for the landing.

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
