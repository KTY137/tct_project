# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit; stage explicit paths; never `-am`.

**Updated: 2026-07-13 ~11:20 — CLEAN RESTART HANDOFF after the big-wave
night shift. ZERO beats in flight. Tree clean (only untracked
`artifacts_claude/`). Kaya is awake and restarting the session.**

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

## Rules pointers (already binding, in CLAUDE.md)

Test economy · test-lane policy (bench for full suites; targeted local) ·
session hygiene 1–4 · free lanes never idle · Codex = queue-file tasks only.
