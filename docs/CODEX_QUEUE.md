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
