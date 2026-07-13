# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit; stage explicit paths; never `-am`.

**Updated: 2026-07-13 day shift — Kaya gave the GO ("koch", incl. the
style-beat "mach"). Wave 1 dispatched, 4 beats in flight (see below).
Base: `design/cockpit-v5 @ 3db0bca` = origin; last green bench set
`1e5850c` (1704 passed; 3db0bca/b05ed72 on top are docs-only).**

## 🔥 IN FLIGHT (wave 1, dispatched ~day-shift start)

| Beat | Agent | File locks |
|---|---|---|
| Glass-gap beat (theme-window button bug + barrier diagnosis + alpha-canvas plumbing + renderings) | Noah (ui-ux-dev) | `gui/theme_editor.py`, `gui/settings_window.py`, `gui/backdrop.py`, `gui/style.py`, `tct_gui.py` (backdrop lines), tests, `docs/design/glass_gap_findings.md`, capture output dir |
| Mary review lanes x3 (static-only, no pytest — glass-gap locks dirty) | qa-critic x3 | read-only: Concurrency (b156cdf/87c54fd/31ed97b) · Safety (93756ab/d03b5ff) · GUI/Data (95ac0f0/50961c7/89c624a/54bc4b8/b011599/93ba2a0) |

**Corrected after Mamoru standup caught a stale ledger (rule-4 audit
working as designed; Adam failed rule 1 on three landings):**

- Landed since last table update: `87c54fd` motion kit (**module is
  `gui/motion_kit.py`**, NOT gui/motion.py as the old lock row claimed —
  that path was already taken) + qml specular live-sync; `b011599` four
  theme presets (Glass 1:1/Plasma/Aurora/Spatial Light); `629336c`
  onscreen capture harness (+ first live run:
  `artifacts_claude/ui_onscreen_20260713T125721Z/` — acrylic pixel-equal
  to none at HEAD, barrier photo-confirmed, probe honest-INCONCLUSIVE);
  `87b1ac5` governance ratification; C9 `3f1ba4e`; Kiroku batch 2
  `53402bc`. Lane hardening lives in agent_env
  (381bfaf/f2a4f6c/4da7430); CPython 3.10.11 x64 installed per-user,
  venv migration = quiet boundary AFTER push.
- Bench sophonone: reachable ("up") — gate is possible tonight.
- Mamoru follow-ups: ARCHITECTURE changelog rows missing for 87c54fd +
  b011599 (Kiroku batch 3, dispatched); two stale worktrees
  (`agent-aa19d2caf98c928dd`, `slice1-ui`) → quiet-boundary cleanup.

**v6 glass tokens landed `54bc4b8`** (184 green; light panel deliberately
stays white — ladder-inversion finding documented in-file). Follow-ups
running: qml_theme `_SPECULAR_ALPHA` stale duplicate (motion beat task 0
+ drift guard), design-system §2 numbers (Kiroku), RADIUS-xl-QML gap
(TECH_DEBT row).

**E7c landed `89c624a` — E-TRACK (E1–E7) COMPLETE.** Numbers-only law
held (no controller import; `grid_alignment_suggested(dict)` signal is
the only output — consumer is a later danger-gated beat). vision/ now an
explicit pure-leaf layer with gui→vision allowance. Riders for Kiroku/
Mary batch: overlay uses nominal isotropic px/mm even when affine on
file (numbers untouched, overlay approximated); reference frame 0-vs-
latest is a within-run drift heuristic (operator-selectable reference =
future beat); ARCHITECTURE still missing the vision/ row (E7b gap).

**Kaya 2026-07-13 afternoon: A/B-Artefakt APPROVED ("richtig sexy") —
v6-Glas-Look + Design-Philosophie ratifiziert als Richtung.** Formal
DECISIONS.md row drafted at the day gate (Kaya signs wording). Still
open from the QML memo: (a) boundary ratification text, (b) probe-go
for flipping TCT_QML_SHELL default.

## 🎨 DESIGN DIRECTION (2026-07-13 afternoon, Kaya-driven)

- Kaya dropped 8 visionOS-glassmorphism references in `design_assets/` —
  the v5 north star sharpens toward real glass materials + fluent motion.
- **A/B decision artifact built & published:** Bias panel, v5 Slate vs
  v6 Glass, live toggle + state ladder demo —
  https://claude.ai/code/artifact/320e0704-fef9-4142-8524-a9fb56bd9070
  (source: `artifacts_claude/tct_bias_glass_ab.html`). Awaiting Kaya.
- **Prometheus verdict on "QML-Hybrid als Standard"**
  (`docs/research/qml_hybrid_standard_decision.md`): PROBE-FIRST, refined.
  Ratify the BOUNDARY now (QML = shell chrome + ornaments; QWidgets = all
  13 panels + every safety control, single-impl; per-panel migration
  REJECTED); gate flipping `TCT_QML_SHELL` default on ONE decisive probe
  on the real laptop (RHI/GLViewWidget coexistence, detach, <5% idle CPU,
  RDP session). **No live MultiEffect/ShaderEffect glass as standard** —
  doesn't render on software/RDP path; ship the look via color-mix +
  DWM backdrop (slice already does this). Classic shell = frozen
  functional fallback (RDP/QML-load-failure), NOT a design target —
  that ends the double-design cost (W3 paid twice: style.py + Shell.qml).
- DECISIONS.md entries await Kaya's ratification (PROTECTED — Adam drafts,
  Kaya approves).

## ✅ Landed this day shift

- `93756ab` E3 Mary-riders (Paul): `should_stop` polled before every
  staircase move; degenerate-fit ValueError converted to affine=None+notes
  (leak past confirmed gate closed); caller contract in docstring.
  17/17 targeted. **Unblocks calibrate_affine GUI wiring.**
- `449a96e` E5 metrology report (Jonathan): `scripts/metrology_report.py`
  `write_report(...)` self-contained HTML + SVG quiver, 9 tests.
- `d94ad3e` S1 style-token beat (Noah): audit items 1/2/4/5, 59/59
  targeted. Item-2 widening to same-hex sibling aliases + dark-hairline
  anchor drift noted in commit — for the Mary batch / capture diff.
- `93ba2a0` C7 QSettings accessor (Codex lane): 13 call sites migrated,
  guard test; Adam ran the verification (6 passed) since the Codex
  sandbox cannot launch the venv. `gui/style.py` allowlisted (was under
  style-beat lock) — **follow-up: migrate style.py's theme/* persistence
  lines onto the accessor now that both locks are free.**
- `95ac0f0` E6b part 1 (Jonathan): `camera/frame_pos_mm` (M,3) NaN-honest,
  CAPTURE_PHOTO format-doc subsection, 15+4 targeted green.
- `31ed97b` C8 scan-map redraw throttle (Codex lane): ~15 Hz coalescing,
  flush-on-read/terminal paths; Adam ran verification (32 green) + fixed
  one stale direct-`_hist_axis` test. Mary flag: flush-on-cursor-hover
  partially bypasses the throttle during live scans (deliberate).
- `50961c7` E6b part 2 Survey view (Jonathan): mosaic in analysis panel,
  mm axes, NaN gaps visible, uncalibrated notice; 61+181 green.
  **Gap found: `set_camera_calibration` has NO writer call site yet** —
  calibrate_affine→writer wiring is a queued follow-up.
- `b156cdf` WorkerThread primitive batch 1 (Noah, opus): GUI-thread
  teardown by construction, ShutdownKind ABANDON/MUST_COMPLETE (loud
  orphans), reaping shiboken-verified; bias_panel migrated (riders a-c;
  d was already fixed in 2d4684b). 13+21+137 green, 2x20 flake clean.
  Batch 2 (~8 sibling workers incl. long-lived pollers — may need a
  poller variant) AFTER Mary review.
- **Process slip (Adam):** chained two here-string commits in one
  PowerShell call → first commit's files silently swept into the second
  (`cc168ac`, now excised via soft-reset + re-commit as 50961c7/b156cdf).
  Rule: ONE here-string commit per shell call, verify `git log --stat`
  after every multi-beat landing.

**For the end-of-day Mary batch (riders/flags from the beats):**
- Paul: residual garbage-affine path NOT closed (zero-motion textured
  frames passing quality gate ⇒ finite near-singular fit, no raise) —
  needs singularity/scale sanity check; Mary to judge follow-up rider.
- Jonathan: rotation/shear decomposition is a local convention; quiver
  base points are synthetic index grid (no absolute positions stored).
- Lesson (Adam's brief bug): told Jonathan to re-run test_affine_selfcal.py
  while Paul held its lock ⇒ transient false failure. Briefs must scope
  verification runs to the beat's OWN files only.

**Day-shift validation policy (Kaya):** testing/validation batched at the END
of the strand, not per-beat — targeted agent-run tests stay in-beat (one
execution per truth), but Mary review set + `capture_panels.py` diff + the
ONE bench full-suite gate happen after the implementation wave lands.

## HEAD / TRUTH

- `design/cockpit-v5 @ 3db0bca` = origin (everything pushed; 46 commits this
  session). **Last green bench set: `1e5850c` — 1704 passed, 1 xfailed,
  37 s** (`3db0bca`/`b05ed72` on top are docs-only). Suite grew 1372→1704
  tonight.
- **Night summary + verification: `docs/NIGHT_REPORT_20260713.md`** (28+
  feature/fix beats; Sequencer A1–A5.2b COMPLETE, Mary CLOSED; Tracks B/C/D
  complete; E-track through E4+E6a; Mamoru audit: all claims git-verified).
- Approved big-wave plan (context for everything below):
  `C:\Users\nukei\.claude\plans\docs-restart-handoff-20260713-md-der-vol-cosmic-tome.md`.
- Session-only artifacts of the old session that DIE with it: the three
  one-shot crons and the Daedalus watcher background shell. **If the Codex
  lane is needed: restart `python -m daedalus.file_bridge watch --project
  project_tct` from `agent_env\`** (queue-file protocol! Inline objectives
  bounce — brief goes into `docs/CODEX_QUEUE.md` first, then enqueue a
  pointer).

## ✅ Standing verdicts (do not re-derive)

- HV gate CLOSED (`df10f8e`+`0f1c012`, Mary APPROVE, bench green).
- Sequencer feature safety-signed: Mary CLOSED after A5.1 (surgical locks —
  NOT-AUS always live) + A5.2a/b (`manual_pause` can never enter a queue).
- Teardown-race fix `41a8ab2` Mary APPROVE (mechanism empirically probed).
- E3 `calibrate_affine` Mary APPROVE (gate/motion; riders below BEFORE any
  GUI wiring).
- Mamoru suite audit: suite is CLEAN, no cleanup beat (994→1704 tests are
  layered defense, not bloat).
- Test economy binding (CLAUDE.md): agent output tail = verification; Adam
  re-runs only on inconsistency/out-of-scope/one reconciliation pass; bench
  at gates only; never test into another beat's file locks.

## 📋 DAY-SHIFT QUEUE (ready to dispatch, in recommended order)

1. **Style-Token-Beat (Noah, sonnet, small) — AWAITING KAYA's "mach":**
   Codex audit items 1+2+4+5 (`docs/design/codex_style_audit_20260713.md`
   has exact style.py anchors + proposed values: label 10→11px/tracking 0,
   surface-ladder tokens, secondary-button density, table row grammar).
   Verify: theme/hex/panel tests + `scripts/capture_panels.py` diff.
2. **E5 metrology report artifact (Jonathan):** new
   `scripts/metrology_report.py` `write_report(cal, path)` → self-contained
   HTML, inline-SVG residual quiver (px+µm), PASS/FAIL vs tolerance_um;
   consumes `StageCameraCal`/`AffineFit` + E4 `place_tiles` diagnostics
   (`n_clamped`, `mean_abs_offset_px`). Snapshot-testable headless.
3. **E6b mosaic view (Jonathan):** FIRST a data-lane decision he owns:
   writer-side `camera/frame_pos_mm` (extend `save_camera_frame(frame,
   pos_mm=None)`; SCAN_DATA_FORMAT update — also still missing its
   CAPTURE_PHOTO subsection). THEN the Survey page in `gui/analysis_panel.py`:
   run HDF5 → frames + frame_point_index + `safety['survey']` geometry →
   `place_tiles(affine=…, refine=…, return_diagnostics=True)` → pyqtgraph
   with mm axes; omitted frames = visible gaps.
4. **E7b sensor pose (Jonathan):** `pip install
   opencv-python-headless==4.9.0.80` + requirements.txt (ratified; research
   `docs/research/sensor_alignment_cv.md`: DICT_4X4_50, pose ladder, <0.05°
   needs ~115 px corner baseline). NEW package `TCT_app/vision/sensor_align.py`
   (lazy import, clean degradation; analysis/ layer contract untouched).
   THEN **E7c align UI (Noah):** pose overlay on the mosaic + "align scan
   grid" button — numbers only, never motion.
5. **WorkerThread primitive (Noah, opus):** the debt class that caused the
   night's only bench red. Fold in Mary's riders: `bias_panel.py:876` IV
   lambda (cross-thread setEnabled), `shutdown()` wait(2000) can abandon a
   still-ramping worker on REAL hardware, stopped parented QThreads
   accumulate, ~8 sibling workers, `flash_button` unowned timer
   (status_widgets:333). TECH_DEBT rows exist.
6. **Mary's E3 riders (Paul/Noah, BEFORE calibrate_affine gets a GUI
   button):** `should_stop` param mirroring `run()`; callers must branch on
   `cal.affine is None` + surface `cal.notes`.
7. **W3 batches 2/3 (Noah+Paul):** green-on-nominal removals, kill-switch
   escalation (ghost→outline→filled-red-with-volts), Monitor "All nominal"
   gated on ≥1 real reading, Z-focus "Find focus" motion class — per
   `docs/design/state_color_census.md`; then `capture_panels.py` rerun gate.
8. **Wave-1/4 rest:** `gui/app_settings.py` QSettings accessor (Noah/Codex);
   `scan_map_view.py` redraw throttle (before giga-scans).
9. **Kiroku batch:** TECH_DEBT riders (teardown follow-ups; :855→:876 ref
   fix; Codex-sandbox venv anomaly item; motor-utility-buttons NIT), research
   index, and an ACCURACY audit of the batch-2 changelog lines (the final-
   sweep lines were confabulated and got a truth pass — batch-2 lines were
   only hash-checked. Lesson: Haiku changelog text needs text-vs-commit
   verification).
10. **Codex-lane venv investigation (small):** Codex sandbox cannot launch
    `.venv` (pyvenv.cfg → missing WindowsApps python) though our own runs
    are fine — recurring in C1/C2/C3/S1 findings.

## 🧑‍🔬 NEEDS KAYA (decisions/eyeballs only he can do)

- Backdrop eyeball run: `BENCH_CHECKLIST.md` §8 (Mica/Acrylic real display,
  `_CANVAS_MODE` A/B in `gui/backdrop.py`, opacity×backdrop, DPI/detached).
- Bench hardware checks: §9 SpinView Binning*Mode on SN 19112408; §10 ref
  baseline window pulse-free at real timebase.
- "mach" for the style-token beat (queue #1).
- Parked from before: v5 design ratification (14 artifacts) ·
  slow-control UNAVAILABLE re-alert policy · metrology precision target
  (2 µm? needs glass/chrome slide) · Ollama watcher restart with GPU env.
- NEW from E7b (`cdc3f8a`): bench-side sensor-pose prerequisites — measure
  relay magnification M and print/validate a physical DICT_4X4_50 marker
  per `docs/research/sensor_alignment_cv.md` sizing formula (needed before
  E7c is usable on real hardware; E7c software work is not blocked).
- NEW from lane hardening (agent_env 381bfaf/f2a4f6c/4da7430): the laptop
  has NO non-Store Python — install python.org CPython 3.10 x64 (step 0),
  then run `agent_env\tools\recreate_tct_venv.ps1` (dry-run first) at a
  QUIET boundary to unblock Codex-lane pytest. Lane ops for Adam:
  `python -m daedalus.file_bridge status --project project_tct` after
  every enqueue (+ `mark-read` after reading; baselined 28→0 unread);
  file-watch `inbox\LATEST.log`; heartbeat/doctor active after the next
  watcher restart. Known open: no duplicate-watcher lock, no auto-restart
  (Scheduled Task would be the real fix), claude-lane 300s default.

## Rules pointers (already binding, in CLAUDE.md)

Test economy · test-lane policy (bench for full suites; targeted local) ·
session hygiene 1–4 · free lanes never idle · Codex = queue-file tasks only.
