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

**Status: OPEN** · Effort: S · Source: docs/TECH_DEBT.md NIT (2026-07-07)

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

## C2 — Calibration panel: theme-responsive status labels

**Status: OPEN** · Effort: S-M · Source: docs/TECH_DEBT.md NIT (2026-07-10)

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

---

## Handback

For each finished task: (1) set its Status line to `DONE — <one-line summary>`
in this file, (2) leave a structured findings block (files touched, tests run
with counts, risks) either appended under the task or as a report via the
Daedalus bridge (`python -m daedalus.file_bridge enqueue ... --source codex`),
(3) leave the working tree uncommitted for Adam's review.
