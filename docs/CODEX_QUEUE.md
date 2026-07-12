# Codex work queue — project_tct

Maintained by Adam (Claude orchestrator). Each task is a **stateless, complete
brief**: everything Codex needs is in the task text. Work top-to-bottom unless
Kaya says otherwise. When done, follow the **Handback** rules at the bottom.

Ground rules (in addition to AGENTS.md):
- PySide6, never PyQt6. Tests run headless: `$env:QT_QPA_PLATFORM='offscreen'`,
  venv python `TCT_app\.venv\Scripts\python.exe`, from `TCT_app\`.
- **No git commits** — leave changes in the working tree; Adam reviews
  (qa-critic gate) and commits.
- If a target file has unexpected uncommitted changes, STOP and report —
  another agent may be mid-flight.
- No inline hex colors outside `gui/style.py` (guard test
  `tests/test_no_inline_hex_gui.py` enforces this).

---

## C1 — Retitle stale panel-kit rollout test names (wording only)

**Status: DONE — Retitled stale rollout wording; pytest blocked by broken venv interpreter.** · Effort: S · Source: docs/TECH_DEBT.md NIT (2026-07-07)

The batch1/batch2 panel-kit rollout test files contain test names and
docstrings that are stale in WORDING only — e.g.
`test_camera_panel_still_constructs_untouched` describes a pre-migration state
(camera/analysis panels migrated to panel_kit in batch3 on 2026-07-07). The
tests still pass and their logic is correct.

- Files: `TCT_app/tests/` — locate via `test_panel_kit_rollout*` /
  batch1/batch2 naming; confirm against the TECH_DEBT entry.
- Task: rename tests + rewrite docstrings to describe what each test actually
  asserts TODAY. **Wording-only refactor: zero changes to assertions, imports,
  fixtures, or behavior.**
- Verify: run the touched test files headless — same pass count as before.

**Codex findings (2026-07-11):**
- Files touched: `TCT_app/tests/test_panel_kit_rollout_batch1.py`, `TCT_app/tests/test_panel_kit_rollout_batch3.py`, `TCT_app/tests/test_settings_window_panel_kit_rollout.py`, `docs/CODEX_QUEUE.md`.
- Wording-only retitles: stale "untouched"/"un-migrated" rollout wording now describes current no-bleed checks and the completed batch3 camera/analysis migration; assertions, imports, fixtures, and test bodies were left unchanged.
- Verification attempted from `TCT_app` with `QT_QPA_PLATFORM=offscreen` and `.\.venv\Scripts\python.exe -m pytest tests/test_panel_kit_rollout_batch1.py tests/test_panel_kit_rollout_batch3.py tests/test_settings_window_panel_kit_rollout.py` before and after edits. Both attempts failed before collection because `.venv\pyvenv.cfg` points to missing `C:\Users\nukei\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\python.exe`; pass count could not be measured locally. Static test function count remains 31.
- Risk: runtime verification remains blocked until the venv/base interpreter is repaired.

## C2 — Calibration panel: theme-responsive status labels

**Status: DONE — Live theme labels wired; pytest blocked by broken venv interpreter.** · Effort: S-M · Source: docs/TECH_DEBT.md NIT (2026-07-10)

`TCT_app/gui/calibration_panel.py` has two status labels styled with static
LIGHT-palette tokens; they do not refresh when the theme toggles (every other
panel refreshes via the house pattern).

- Task: restyle the two labels through the live theme path — tokens from
  `gui/style.py` only, follow the refresh pattern used by other panels (see
  how e.g. scan_viewer_panel or camera_panel re-applies palette on theme
  change; `tests/test_apply_theme_lifetime.py` shows the contract).
- Do NOT touch the repeatability/run-control logic in that file (known
  DangerGate BLOCKER lives there — separate protected beat).
- Verify headless: `tests/test_no_inline_hex_gui.py`,
  `tests/test_apply_theme_lifetime.py`, plus any calibration panel tests.

**Codex findings (2026-07-11):**
- Files touched: `TCT_app/gui/calibration_panel.py`, `TCT_app/tct_gui.py`, `TCT_app/tests/test_no_inline_hex_gui.py`, `docs/CODEX_QUEUE.md`.
- `CalibrationPanel` now reads the saved theme mode, resolves `_current` and `_rep_progress` through `gui.style.palette()`, exposes `refresh_theme()`, and is included in `tct_gui._toggle_theme()`'s live refresh list.
- Regression coverage updated so `test_calibration_panel_construct_and_theme_switch` exercises dark and light `refresh_theme()` paths.
- Verification attempted from `TCT_app` with `QT_QPA_PLATFORM=offscreen` and `.\.venv\Scripts\python.exe -m pytest tests/test_no_inline_hex_gui.py tests/test_apply_theme_lifetime.py`; it failed before pytest launched because `.venv\pyvenv.cfg` points to missing `C:\Users\nukei\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\python.exe`.
- Static checks completed: `git diff --check` passed; `rg -n "LIGHT\[|DARK\[|#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3}" TCT_app/gui/calibration_panel.py -S` found no stale fixed palette/inline hex usage in the target file.
- Risk: runtime pytest verification remains blocked until the local venv/base interpreter is repaired.

---

## Handback

For each finished task: (1) set its Status line to `DONE — <one-line summary>`
in this file, (2) leave a structured findings block (files touched, tests run
with counts, risks) either appended under the task or as a report via the
Daedalus bridge (`python -m daedalus.file_bridge enqueue ... --source codex`),
(3) leave the working tree uncommitted for Adam's review.

## C3 — Theme fan-out completeness guard test

**Status: DONE — Added fan-out guard; pytest blocked by interpreter launch failure.** · Effort: S · Source: Adam (live bug class from C2, 2026-07-12)

Bug class: a panel gains `refresh_theme()` but is forgotten in
`TCTMainWindow`'s fan-out tuple (`tct_gui.py` ~line 640-656), so it silently
never re-themes. C2 fixed one instance; this test makes the class impossible.

- Task: write `TCT_app/tests/test_theme_fanout_completeness.py`: construct
  `TCTMainWindow` headless against the simulated config (see how
  `tests/test_apply_theme_lifetime.py` builds the window), then (a) collect
  every attribute on the window that is a QWidget with a callable
  `refresh_theme`; (b) spy each one's `refresh_theme`, trigger the window's
  theme-toggle path once, assert every spy fired. One test function plus
  helpers, deterministic, offscreen, no hardware.
- Note: the sandbox may fail to LAUNCH the venv interpreter (see C1/C2
  findings) — if pytest cannot run, verify by `--collect-only` semantics
  review and say so explicitly in findings; Adam runs the suite after.
- Verify (if runnable): the new file + `tests/test_apply_theme_lifetime.py`.

**Codex findings (2026-07-12):**
- Files touched: `TCT_app/tests/test_theme_fanout_completeness.py`, `docs/CODEX_QUEUE.md`.
- Added a headless guard test that constructs `TCTMainWindow` with a temp all-simulated config, discovers window attributes that are `QWidget`s with callable `refresh_theme`, spies each discovered method, toggles the theme once, and asserts no refreshable panel was missed. The test includes a `_calib_panel` sanity assertion so the C2 bug class stays covered.
- Verification: `git diff --check` passed. Requested pytest command from `TCT_app` with `QT_QPA_PLATFORM=offscreen` and `.\.venv\Scripts\python.exe -m pytest tests/test_theme_fanout_completeness.py tests/test_apply_theme_lifetime.py` executed 0 tests because the venv launcher failed before process start: `.venv\pyvenv.cfg` still points at missing `C:\Users\nukei\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\python.exe`. A bare `python -m py_compile TCT_app\tests\test_theme_fanout_completeness.py` also failed before launch with the local `python.exe` session error.
- Static review: the test uses only simulated backends, does not touch protected hardware paths, and matches the requested collect/spy/toggle/assert semantics.
- Risk: runtime pytest verification remains blocked until the local Python/venv interpreter is repaired.

## D1 — Adversarial second opinion: cockpit design-language draft

**Status: DONE — Wrote adversarial cockpit design second opinion.** · Effort: S · Source: Adam/Kaya design council (2026-07-12)

Read the full HTML source of `artifacts_claude/tct_cockpit_design_v2.html`
(design tokens, type rules, MetricTile, chips, danger wells, hold-to-arm,
panel mockups) plus `docs/design/apple_style_ui_audit.md` for context.
Target: highly polished Apple-style instrument cockpit; hard rules: one
accent, red exclusively for HV/abort, danger controls loudest, mono
numerals, both themes, detachable panels stay.

- Task: write `docs/design/second_opinion_codex.md` (create it, max ~120
  lines, structured):
  1. The 5 weakest design decisions in the draft + concrete better
     alternatives.
  2. Honest verdict on hold-to-arm (gloves/one-handed bench operation).
  3. 3 ideas the draft is missing entirely (command palette? toast
     discipline? multi-monitor detach aesthetics? density modes?).
  4. Typography nitpick: system sans + mono numerals — argue, name exact
     sizes/weights if you disagree.
- No app code changes. No commit. Set D1 DONE with findings per Handback.

**Codex findings (2026-07-12):**
- Files touched: `docs/design/second_opinion_codex.md`, `docs/CODEX_QUEUE.md`.
- Created a structured second-opinion critique covering the five weakest draft design decisions with alternatives, a bench-operation verdict on hold-to-arm, three missing product/design ideas, and exact typography recommendations.
- Verification: read all 828 lines of `artifacts_claude/tct_cockpit_design_v2.html` in chunks plus `docs/design/apple_style_ui_audit.md`; `git diff --check` passed. No pytest was run because D1 is documentation-only and requests no app code changes.
- Risk: visual critique is source/audit based; no rendered browser screenshot pass was performed for the draft HTML.

## C4 — stage_view: theme from tokens, not hardcoded dark

**Status: DONE — Stage view now follows live theme tokens; pytest blocked by broken venv interpreter.** · Effort: S · Source: render audit 2026-07-12 (design roadmap D2 fix-it)

`TCT_app/gui/stage_view.py` hardcodes `_theme_mode = "dark"` (~line 107), so
the Motor panel's 2D/3D stage plot stays a black canvas in the light theme.
Design law: both themes from tokens (`gui/style.py`), every color-caching
widget implements `refresh_theme(mode)`.

- Task: make stage_view read the active theme like other panels do (see how
  scan_map_view or scope_panel pull palette + implement `refresh_theme`);
  re-pull plot background/grid/marker colors from style tokens on theme
  switch; keep the existing MotorPanel wiring working (add the panel's
  refresh_theme fan-out hook if stage_view needs it — check
  `tests/test_theme_fanout_completeness.py` still passes).
- No hardware/motion code changes. Verify headless: that fan-out test +
  tests/test_no_inline_hex_gui.py + a Motor panel construct smoke.
- Do NOT commit; set C4 DONE with findings per Handback.

**Codex findings (2026-07-12):**
- Files touched: `TCT_app/gui/stage_view.py`, `TCT_app/gui/motor_panel.py`, `TCT_app/tests/test_no_inline_hex_gui.py`, `docs/CODEX_QUEUE.md`.
- `StageView`, `StageView2D`, and `StageView3D` now read the active theme from `QSettings` unless a parent supplies one, resolve background/grid/axis/marker/envelope/scan/laser colors through `gui.style.palette()`, and expose `refresh_theme(mode)` fan-out.
- `MotorPanel` now constructs `StageView` with its current theme mode and forwards `MotorPanel.refresh_theme()` into the stage view, so the existing main-window fan-out remains sufficient.
- Added a headless regression assertion in `tests/test_no_inline_hex_gui.py` that checks MotorPanel propagates light/dark refreshes to StageView and that the 2D plot background uses the `sunk` token for each theme.
- Verification: `git diff --check` passed; static `rg` confirmed no hardcoded `_C_*`, plot constants, or inline hex colors remain in `TCT_app/gui/stage_view.py`. Requested pytest command from `TCT_app` with `QT_QPA_PLATFORM=offscreen` and `.\.venv\Scripts\python.exe -m pytest tests/test_theme_fanout_completeness.py tests/test_no_inline_hex_gui.py tests/test_panel_kit_rollout_batch1.py::test_motor_panel_constructs_both_themes` executed 0 tests because the venv launcher failed before process start: `.venv\pyvenv.cfg` still points to missing `C:\Users\nukei\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\python.exe`.
- Risk: runtime pytest verification remains blocked until the local Python/venv interpreter is repaired.

## C5 — Update 2 migration-invalidated kit tests to the D0 contract

**Status: SKIP — D0 contract not present on this branch.** · Effort: S · Source: D0/D1 migration (2026-07-12)

Design-system D0 (commit 0f0157f on the qml-hybrid-slice1 branch — but DO
THE WORK HERE ON THIS BRANCH ONLY IF the failing tests exist here too;
otherwise report SKIP) deliberately changed MetricTile state styling from
accent-border/side-bar to value-ink-only, and remapped quiet-nominal states.
Two tests still assert the removed design and fail:
`tests/test_panel_kit_cockpit.py` and `tests/test_shell_cockpit_v5.py`
(armed-border / token assertions).

- Task: update ONLY the stale assertions to the new contract (value-ink
  state coloring; states {normal,good,warn,crit,armed,sim}; connected/ok =
  neutral not green). Do not weaken unrelated assertions; do not touch
  gui/ code. Run just those two files headless; both must pass.
- Do NOT commit; set C5 DONE with findings per Handback.

**Codex findings (2026-07-12):**
- Files touched: `docs/CODEX_QUEUE.md` only.
- Static branch check found the target tests present, but this branch still has the pre-D0 implementation: `gui/panel_kit.py` still gives `MetricTile("armed")` an instance border via `glow_color("armed")`, and `gui/status_widgets.py` still maps `connected`/`ok` to `good`. Updating only the tests to D0 value-ink/quiet-nominal expectations would make them contradict current `gui/` code, and C5 explicitly forbids `gui/` edits.
- Verification attempted from `TCT_app` with `QT_QPA_PLATFORM=offscreen` and `.\.venv\Scripts\python.exe -m pytest tests/test_panel_kit_cockpit.py tests/test_shell_cockpit_v5.py`; it failed before pytest launched because `.venv\pyvenv.cfg` points to missing `C:\Users\nukei\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\python.exe`.
- Risk: if D0 is later merged onto this branch, this C5 should be reopened and the two stale assertions updated then.

## C6 — Calibration panel: add the standard panel header (missing)

**Status: DONE — Added standard header and guarded body intro; pytest blocked by broken venv interpreter.** · Effort: S · Source: render audit + design spec §7 (2026-07-12)

`TCT_app/gui/calibration_panel.py` is the ONLY panel missing the standard
eyebrow+title header every other panel has (e.g. "TCT CONTROL · MOTOR
STAGE" / title) — it opens directly with prose. Also its intro paragraph
must become ONE sentence-case line (it currently renders as shouty
uppercase prose via the mono label role).

- Task: add the standard header using the EXISTING `panel_header` /
  header pattern from gui/panel_kit.py exactly as other panels use it
  (copy the Motor or Monitor panel's usage); eyebrow "TCT Control ·
  Calibration" equivalent, title "Calibration". Reduce the intro paragraph
  to one short sentence-case line using the normal body label style (NOT
  the mono/uppercase role). Do not touch method/repeatability logic.
- Verify headless: calibration tests + tests/test_no_inline_hex_gui.py.
- Do NOT commit; set C6 DONE with findings per Handback.

**Codex findings (2026-07-12):**
- Files touched: `TCT_app/gui/calibration_panel.py`, `TCT_app/tests/test_no_inline_hex_gui.py`, `docs/CODEX_QUEUE.md`.
- `CalibrationPanel` now uses the shared `panel_header("TCT Control · Calibration", "Calibration")` at the top of the panel, matching the existing panel-kit pattern, and the opening prose is reduced to one short sentence-case body label. Calibration method and repeatability logic were not touched.
- Added a focused assertion to `test_calibration_panel_construct_and_theme_switch` that guards the header eyebrow/title and confirms the intro label remains a normal body label rather than a mono/styled caption.
- Verification: `git diff --check` passed; static `rg -n "#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3}|LIGHT\[|DARK\[" TCT_app/gui/calibration_panel.py -S` found no inline hex or fixed LIGHT/DARK palette usage. Requested pytest from `TCT_app` with `QT_QPA_PLATFORM=offscreen` and `.\.venv\Scripts\python.exe -m pytest tests/test_bias_and_calibration.py tests/test_no_inline_hex_gui.py` executed 0 tests because the venv launcher failed before process start: it still tries to use missing `C:\Users\nukei\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\python.exe`.
- Risk: runtime pytest verification remains blocked until the local Python/venv interpreter is repaired.

## D2 — Design v5 council seat: per-panel "sleek/translucent Apple" proposals

**Status: DONE — Wrote v5 sleek/translucent council proposals.** · Effort: M · Source: Kaya directive 2026-07-12 evening

Kaya rejected the current live look. New north star: SLEEK, subtle
translucency, genuine Apple-app feel — ambitious, not incremental. Your D1
critique shaped v4; now be the adversarial designer for v5.

- Read: docs/design/cockpit_design_system.md (v4 baseline),
  artifacts_claude/tct_cockpit_design_v4_final.html (source), the freshest
  artifacts_claude/ui_audit_*/manifest.txt + gui/style.py as-implemented.
  You may run scripts/capture_panels.py (headless) if useful.
- Write docs/design/council_v5_codex.md (~150 lines max), structured:
  1. WHY the current implementation reads less premium than the artifact
     (name the 5 biggest translation losses, Qt-specific).
  2. Per panel (all 11): ONE concrete v5 move each toward sleek/translucent
     (composition or material, not color-swaps).
  3. Translucency strategy for Qt/QML: where REAL blur is worth it vs
     color-mix fake vs none (perf-honest — no effects on plot hot paths).
  4. 3 ambitious ideas v5 should steal from the best Mac apps.
- No app-code edits. No commit. Set D2 DONE with findings per Handback.

**Codex findings (2026-07-12):**
- Files touched: `docs/design/council_v5_codex.md`, `docs/CODEX_QUEUE.md`.
- Created a structured v5 council memo covering five Qt-specific translation losses, one concrete composition/material move for each of the 11 audited panels, a perf-honest Qt/QML translucency strategy, and three Mac-app interaction ideas.
- Verification: read `docs/design/cockpit_design_system.md`, `artifacts_claude/tct_cockpit_design_v4_final.html` source, `artifacts_claude/ui_audit_20260711_005405/manifest.txt`, and `TCT_app/gui/style.py`; visually inspected the latest audit captures for all listed light panels plus representative dark/detached captures. `git diff --check` passed. No pytest was run because D2 is documentation-only and requests no app-code edits.
- Risk: critique is source/audit based; no new capture run was performed.

## D3 — Panel composition inventory (ground truth for v5 redesign)

**Status: DONE — Wrote panel composition inventory for v5.** · Effort: M · Source: Adam, Operation Feinschliff 2026-07-12

The v5 redesign (see docs/design/council_v5_codex.md — your D2 seat) needs a
mechanical ground-truth inventory of how each panel is ACTUALLY composed
today, so per-panel redesign artifacts don't guess.

- Read-only with respect to app code. Write ONE file:
  docs/design/panel_inventory_v5.md
- For each of these gui/ panels — motor_panel, reference_monitor_panel (or
  its actual module name; locate it), camera_panel, scope_panel, laser_panel,
  scan_viewer, scan_planner (planner panel module), bias_panel, calibration_panel,
  monitor_panel, analysis_panel, plus settings_window and device manager dialog —
  report, tersely (table or compact list per panel):
  1. Top-level layout type + orientation (e.g. QVBoxLayout > QSplitter(H)).
  2. Count of QGroupBox / panel_kit Card / QFrame containers, and max nesting
     depth of framed containers.
  3. Scroll areas (how many, wrapping what).
  4. The panel's "hero" candidate (largest single widget: plot/camera/tree/…)
     and roughly what fraction of the panel it occupies in the default layout.
  5. Command surfaces: rows of QPushButtons, toolbars, arm/danger controls.
  6. Anything that would fight a hero+inspector recomposition (hard-coded
     minimum sizes, fixed splitter ratios, deeply nested forms).
- No opinions needed (D2 covered that) — this is a measurement pass.
- No app-code edits. No commit. Set D3 DONE with findings per Handback.

**Codex findings (2026-07-12):**
- Files touched: `docs/design/panel_inventory_v5.md`, `docs/CODEX_QUEUE.md`.
- Created a source-level inventory for the 11 main tabs plus `SettingsWindow` and `DeviceManagerWindow`, including actual module resolution for Reference Monitor (`gui/intensity_panel.py`), top-level layout shape, framed-container counts/depth, scroll areas, hero candidates, command surfaces, and recomposition friction.
- Verification: read `docs/design/council_v5_codex.md`, `TCT_app/tct_gui.py`, `TCT_app/gui/panel_kit.py`, `TCT_app/gui/scan_map_view.py`, `TCT_app/gui/stage_view.py`, and the target panel/dialog modules; `git diff --check` passed. No pytest was run because D3 is documentation-only and app code is read-only for this task.
- Risk: counts are static source-level measurements; no new rendered layout screenshots or runtime widget-tree introspection were performed.

## D4 — State-color usage census (ground truth for wave W1 taxonomy sweep)

**Status: DONE — Wrote state-color census for W1.** · Effort: M · Source: Adam, Feinschliff 2026-07-12 night

Wave W1 will sweep every panel onto the ratified 9-rung hardware state
ladder (docs/design/council_v5_paul.md §1). Before anyone edits, we need a
mechanical census of TODAY's state-color usage.

- Read-only wrt app code. Write ONE file: docs/design/state_color_census.md
- For each file in TCT_app/gui/ (panels + panel_kit + style consumers):
  list every use of status/state color: palette keys danger/armed/sim/error,
  token roles that carry color (chips, dots, banners, button variants), and
  any green-ish styling (search for "green", ok-state styling, success
  variants). For each hit: file:line, the widget/state it colors, and which
  ladder rung it SHOULD map to (OFFLINE/CONNECTING/SIM/IDLE/ACTIVE-motion/
  ACTIVE-HV/ACTIVE-benign/UNKNOWN/TRIPPED) or "command-class, not state".
- Flag directly (top section, ranked): every place red is used for a
  non-HV/non-abort state, every green-on-nominal, every unknown-state
  rendered as a confident fill.
- Table form, terse. No opinions beyond the rung mapping, no app-code edits.
- No commit. Set D4 DONE with findings per Handback.

**Codex findings (2026-07-12):**
- Files touched: `docs/design/state_color_census.md`, `docs/CODEX_QUEUE.md`.
- Created the D4 static census for `TCT_app/gui/`, with a ranked top section for green-on-nominal, non-HV/non-abort red, confident UNKNOWN fills, ACTIVE-HV amber carryover, and solid SIM dots, followed by terse per-file tables mapping current status/state color uses to the W1 ladder or command-class/not-state.
- Verification: read `docs/design/council_v5_paul.md` section 1 and statically searched/inspected `TCT_app/gui/` Python + QML sources for status chips, lamps, pills, MetricTiles, button states, palette safety tokens, green/red/sim/error tokens, and inline status styling; `git diff --check` passed. No pytest was run because D4 is documentation-only and app code is read-only for this task.
- Risk: census is source-level only; no runtime widget-tree introspection or rendered screenshot pass was performed.

## D5 — Adversarial second opinion on tonight's landed commits

**Status: DONE — Wrote adversarial static review of landed commits.** · Effort: M · Source: Adam, night shift 2026-07-12

READ-ONLY review. **Do not run pytest** (other lanes hold the test runner
tonight) and do not edit app code — static reading only.

Review these four commits on branch design/cockpit-v5 (use `git show`):
- `5730644` fix(safety): fail-closed start guard on all four scan entry points
- `9b91ed1` feat(analysis): 1D map slicer (analysis/map_slice.py + analysis_panel)
- `c12a6a1` feat(gui): theme editor (gui/theme_editor.py + style.py override layer)
- `7663d74` fix(gui): z-focus/voltage coordinator slots fail closed

Write ONE file: `docs/design/codex_review_20260712.md` (~120 lines max):
1. Per commit: the strongest concrete defect or risk you can find that the
   crew's own review would plausibly MISS (be adversarial; "looks fine" is a
   valid verdict only after you name what you checked and why it holds).
   Cite file:line. Rank by risk (safety > data > correctness > style).
2. Cross-cutting: does the theme editor's override layer have any path that
   could reach the LOCKED safety tokens (danger/armed/sim/error) — via preset
   JSON, QSettings, typography/radius helpers, or the glass blend? Trace it
   and say yes/no with evidence.
3. Does `glass_amount = 0` (fully opaque) leave any surface unreadable
   (text-on-background contrast below ~4.5:1) or any state indistinguishable?
   Reason from the token math in `gui/style.py`, not from a screenshot.
4. Anything in `map_slice.py` NaN/edge math you can falsify with a concrete
   counter-example (state inputs + expected vs actual).

No app-code edits. No commit. Set D5 DONE with findings per Handback.

**Codex findings (2026-07-12):**
- Files touched: `docs/design/codex_review_20260712.md`, `docs/CODEX_QUEUE.md`.
- Wrote the requested static review covering the four named commits, with the highest-risk finding on z-focus/voltage starts not emitting the shared `scan_started` fan-out, plus controller atomicity, map-slice NaN handling, and theme customization persistence risks.
- Cross-cutting trace concluded there is no direct override path to locked safety tokens (`danger`/`armed`/`sim`/`error`, including `crit`/`warn` aliases) through preset JSON, QSettings, typography/radius helpers, or glass blending; residual design risk is unrestricted editable accent/text colors, not safety-token mutation.
- Verification: read the relevant `git show` diffs and current source with line numbers for `scan_controller.py`, `scan_coordinator.py`, `scan_viewer_panel.py`, `tct_gui.py`, `analysis/map_slice.py`, `analysis_panel.py`, `style.py`, `theme_editor.py`, `qml_theme.py`, and targeted tests. `git diff --check` passed. Per D5 instruction, pytest was not run.
- Risk: review is static-only; no runtime reproduction or screenshot/contrast measurement pass was performed.
