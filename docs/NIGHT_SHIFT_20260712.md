# Night shift 2026-07-12 → 13 — the Giga Grand TODO List

Owner: Adam. Mode: autonomous overnight, simulation/tests only (safety rule 6).
Rule of the night: every code beat gets tests + a Mary review (batched);
free lanes never idle; repo files are the shared memory.

Parked-for-Kaya items are at the bottom — nothing in lanes A–F needs a
ruling. In-flight agent files are conflict-locked: no second writer on
`tct_gui.py`, `style.py`, `theme_editor.py` (Noah) or `analysis_panel.py`,
`map_slice.py` (Jonathan) until those land.

## LANE A — Kaya-ratified / explicitly requested features

- [ ] **A1 · Theme editor** (Noah, IN FLIGHT): presets, non-safety color
      swatches, fonts, radius, glass_amount override layer; safety palette
      locked. → commit on completion, Mary review (batch 1).
- [ ] **A2 · QML shell = default** (Noah, AFTER A1 — same files): flip in
      `tct_gui._build_central`, classic behind `-Classic`/env fallback +
      fail-safe notify, retire visible toolbar path, keep QActions for
      menu/shortcuts. Guards: test_qml_shell.py rail pins + new default-flip
      test. Update run.ps1 comment block.
- [ ] **A3 · Analysis 1D slicer** (Jonathan, IN FLIGHT): map_slice.py +
      InfiniteLine/band + profile + CSV. → commit on completion, Mary batch 1.
- [ ] **A4 · Sensor mosaic v1, sim-verified** (multi-beat):
      - A4a Jonathan: `analysis/mosaic_stitch.py` pure math — tile placement
        from stage positions × px→mm cal, linear overlap blend, NaN-safe
        canvas; unit tests with synthetic tiles.
      - A4b Paul: camera+motor sim plumbing — grab-at-position helper against
        SimulatedCamera/SimulatedMotorStage; no real-SCPI paths touched.
      - A4c Abel: procedure runner (move→settle→grab loop) with preconditions
        (homed + streaming + px→mm cal), DangerGate on start, abort/STOP path,
        progress signals; camera_panel "Mosaic" procedure card UI last.
      - Mary review mandatory (motion sequencing). Artifact mockup =
        artifacts_claude/v5/mosaic.html.
- [ ] **A5 · Measurements-only acquisition, foundations**:
      - A5a Jonathan: SCAN_DATA_FORMAT.md extension spec — `measurements`
        table (amplitude, charge, rise, timing + units/attrs), no waveform
        group; writer support behind a plan flag; format-versioned.
      - A5b Abel: planner block "Acquire measurements" (recipe schema +
        validator + executor path in SIM: SimulatedOscilloscope computes
        host-side); Before-you-run DATA tile reflects the saving.
      - A5c Paul: driver interface `read_measurements()` on scope base +
        simulated impl; VISA/TBS + DRS4 real paths = `TODO(manual needed)`
        stubs per rule 4 (TBS1052C MEASUrement subsystem to verify against
        manual; DRS4 likely host-side).
      - Mary review (scan logic + data contract).

## LANE B — W1 taxonomy sweep (fixes violations of the RATIFIED v4 laws)

Ground truth: Codex D4 census (in flight) → docs/design/state_color_census.md.
- [ ] **B1** Noah (after A2): state-ladder roles in style.py/panel_kit —
      StateDot 9-rung variants + UNKNOWN dashed chip variant + tests.
- [ ] **B2** red-misuse fixes: camera offline → OFFLINE neutral (Noah);
      laser OUTPUT-UNKNOWN → UNKNOWN chip (Paul wording, Noah widget);
      planner MOVE STAGE row + confirm pill → amber spine + envelope glyph
      (Abel).
- [ ] **B3** green-on-nominal removals: settings VALID/SAVED, calibration
      SAVED, laser LOAD chip → quiet (Noah).
- [ ] **B4** bias kill-switch escalation ghost→outline→filled-red-with-volts
      (Paul + Noah; DangerGate untouched).
- [ ] **B5** Monitor "All nominal" gated on ≥1 real reading per channel;
      NO-DATA state (Jonathan).
- [ ] **B-gate**: Mamoru pre-run → Mary batch review → capture_panels.py
      rerun → Adam eyeballs the diff vs gap notes.

## LANE C — W2 kit primitives (additive, non-breaking)

- [ ] **C1** StateStack (QStackedLayout offline/live switch) in panel_kit +
      adopt in Camera + RefMon as exemplars; honest empty axes per
      Jonathan's rule (scope/refmon keep axis frame at real scale; no grid).
- [ ] **C2** FormSheet + settings_row + no-Expanding guard test; retrofit
      ONE exemplar (laser_panel) as proof — full rollout waits for v5
      ratification.
- [ ] **C3** instrument well inside FigureCard: PLOT_BG frame, hairline
      bezel, 3px pad, chrome header, wellShade strip — hot-path guard test
      stays green.

## LANE D — robustness / testing

- [ ] **D1** 8 latent sibling panel workers → GUI-side destruction batch
      (defense-in-depth per DECISIONS invariant; blocking quit+wait stays).
      Noah-domain w/ opus, Mary review. Files: individual panel workers only.
- [ ] **D2** UI monkey harness v1: seeded pytest-qt random-interaction
      driver against the sim app (clicks/keys on safe widgets, danger
      controls excluded by design — it must never pass a DangerGate),
      invariants: no crash, no unexpected state transition, teardown clean.
      New files only.
- [ ] **D3** xdist isolation flake (test_bias_panel_danger_and_rail_hooks_
      present + friends) → root-cause, then bench default `-n auto`.
- [ ] **D4** state fuzzer: extend walks to cover z-focus/voltage start paths
      (now guarded) + PAUSED-resume edges as permanent invariants.

## LANE E — free lanes (never idle)

- [ ] **E1** Codex D4 census (IN FLIGHT) → feeds B.
- [ ] **E2** Codex D5: adversarial second-opinion review of tonight's theme
      editor + slicer commits (read-only, queue task).
- [ ] **E3** Codex D6: docstring + test-name hygiene sweep on gui/panel_kit
      (mechanical, wording-only).
- [ ] **E4** Ollama: blocked for advisory (verify-gate design gap, logged);
      revisit when Kaya restarts watcher with GPU env.

## LANE F — housekeeping

- [ ] **F1** capture_panels.py after every visual beat; keep latest set in
      artifacts_claude/ui_audit_*; Adam eyeballs.
- [ ] **F2** Kiroku ledger after each landed beat (cheap, often).
- [ ] **F3** Morning report: full night summary + updated memory handoff +
      TECH_DEBT reconciliation.
- [ ] **F4** Slice-worktree: document sync/retire recommendation (no action).

## PARKED — needs Kaya

- [ ] **P1** v5 ratification → unlocks W3 chrome collapse + W4 full panel
      recompositions + full FormSheet rollout.
- [ ] **P2** Sequencer envelope semantics (combined vs per-routine) →
      implementation.
- [ ] **P3** Watcher restart with GPU env (one-liner in agent_env todos).
- [ ] **P4** Command palette (D6) allow-list confirmation.
- [ ] **P5** Hover/lag verdict on the real display after 2d78f80.

## Coffee Break of Kings — full retro (tonight's opener)

Mamoru sweep + suite · gripe reports from Paul/Abel/Noah/Jonathan/Mary/
Samantha (capped) · Adam consolidates → TECH_DEBT.md · headline in the
morning report.
