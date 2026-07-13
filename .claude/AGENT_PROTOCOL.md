# Claude Agent Protocol

Purpose: keep subagents useful without burning the full parent conversation.

## Invocation Rules

- Adam is the only router. Subagents never talk to each other.
- Invoke one specialist at a time unless the tasks are truly independent.
- Pass only the immediate task, relevant paths, constraints, and short state.
- Do not pass the full user chat history.
- Treat each *new* subagent dispatch as stateless — but **reuse a live instance
  for iterative rounds on the same task** (2026-07-08): a spawned agent keeps
  its context within the session and can be continued with follow-up messages.
  Review→fix→re-verify loops go to the SAME implementer and the SAME reviewer
  (no re-derivation tax, reviewer knows their own findings). Switch back to a
  fresh dispatch when the task/domain changes, when the instance's transcript
  has grown large (a continued agent carries its whole history as cost), or
  when fresh adversarial eyes are the point. Cross-session state lives in repo
  files only (agent defs, registries, DECISIONS.md, ledgers).
- Ask for JSON-style structured reports, not conversational prose.
- Use `docs/ARCHITECTURE.md` as shared memory instead of replaying context.
- For external/manual knowledge, call `researcher` first and pass only the note path.

## Tiering — spend the cheap crew first

Route by cost, not habit. The Haiku trio is cheap and stateless; use it for the
routine work so the senior crew is reserved for judgment.

| Tier | Agents | Use for |
|---|---|---|
| Haiku (cheap, call often) | Kiroku, Shiori, Mamoru | In-repo lookups, bookkeeping/index/changelog upkeep, drift sweeps, running the test suite |
| Sonnet | Noah, Jonathan, Samantha | GUI, analysis/data, prose docs |
| Opus (reserve for judgment) | Paul, Abel, Mary, Prometheus | Drivers/safety, scan logic, adversarial review, external research/architecture advice |

Defaults: a "where/what/which" question → **Shiori** (not a raw grep dump). A
structural change (new module/signal/config key/HDF5 group) → have **Kiroku**
update the index/changelog + registries in the same task. A health/drift check
→ **Mamoru**. None of these run on their own — they are "always on" only
because Adam calls them by default.

## Routing tie-breaks — by responsibility, not directory

(2026-07-08 crew meta-review.) When a task spans seats, split it; don't let the
file's directory pick the owner:

- **Scan run-control logic** (sequencing, run-state gating, pause/abort
  semantics) is **Abel's wherever it lives** — including `tct_gui.py` handlers
  and the future `gui/scan_coordinator.py`. Paired task: Abel authors logic,
  Noah wires widgets. Never author abort/pause-race logic at GUI tier alone.
- **Driver contract vs plumbing:** constructor signature/SCPI behavior = Paul;
  `device_manager.py` wiring + `config_validator.py` entries = Abel. A change
  spanning both gets both seats in the same beat.
- **Physics formulas** (CCE, charge, depletion voltage, calibration math) =
  Jonathan in `analysis/`; GUI panels call, never inline, them (Noah).
- Anything under `data/`, `analysis/`, or touching `SCAN_DATA_FORMAT.md` —
  including config keys consumed by data writers — = Jonathan.
- **Model override:** Noah runs Sonnet by default; for Qt threading, worker
  lifecycle/teardown, or danger-gate/confirmation work, Adam dispatches him
  with `model: opus` (targeted override, not a blanket bump).

## Review briefs (Mary) — pre-scoped, never blind

Sequence for a substantial change: **Mamoru pre-runs the suite** (cheap,
timeout-guarded) → Adam hands Mary a *review brief* → Mary re-runs tests only
to reproduce a specific concern, not to establish a baseline.

```json
{
  "task_id": "review-<short-id>",
  "changed_files": ["paths or `git diff` scope"],
  "pre_run": "Mamoru's result, e.g. '468 passed in 97s' + timings",
  "specific_concerns": ["what Adam wants stress-tested"],
  "scoped_test_cmd": "pytest tests/test_x.py -q for the touched area",
  "base_interfaces": ["matching *_base.py / contract files"],
  "known_flakes": ["timing_sensitive tests to not report as regressions"]
}
```

## Coffee Break / Standup protocol (opt-in cadence)

A periodic, structured retrospective. Purpose: surface drift and tech-debt before
it compounds — a "tired dev team airing gripes," but stateless and token-bounded.

**When** — prefer *boundaries* over a tight clock (token cost is real):
- After a substantial change lands, before a commit/release, or on explicit request.
- Optionally on a schedule via a cloud routine / cron — but only if the user asks
  for it (recurring dispatch spends tokens every fire). Adam must not self-schedule.

**Cheap standup (default, Haiku-only):** Adam dispatches **Mamoru** (drift + test
sweep) and, if bookkeeping lags, **Kiroku** (reconcile the index/ledgers). Adam
consolidates the top items into `docs/TECH_DEBT.md` and reports the headline.

**Full retro (occasional, on request):** Adam additionally asks each relevant
specialist for a *short* gripe report on their own domain (one call each, capped),
using the "standup gripe" shape below. Adam de-duplicates, ranks by risk
(safety/HV/data-loss first), and records them in `docs/TECH_DEBT.md`. Subagents
never see each other's reports — Adam relays.

**Standup gripe report shape:**

```json
{
  "status": "done",
  "domain": "e.g. devices/oscilloscope.py",
  "gripes": [
    {"severity": "BLOCKER | RISK | ANNOYANCE | NIT", "item": "what nags you", "where": "path:line", "suggested_owner": "Paul|Noah|..."}
  ]
}
```

## Standard Task Brief

```json
{
  "task_id": "short-id",
  "objective": "one concrete objective",
  "paths": ["relevant/file.py"],
  "must_read": ["docs/ARCHITECTURE.md"],
  "context": {"only": "facts needed now"},
  "constraints": ["simulation only", "no hardware I/O"],
  "return": "agent_report_v1 JSON only"
}
```

## Standard Report

```json
{
  "status": "done | blocked | needs_review | failed",
  "summary": "max 600 chars",
  "files_changed": [],
  "tests_run": [],
  "risks": [],
  "todos": [],
  "handoff": {}
}
```

Review reports may use:

```json
{
  "status": "done | blocked",
  "findings": [
    {
      "severity": "BLOCKER | BUG | RISK | NIT",
      "file": "path:line",
      "issue": "what is wrong",
      "failure_mode": "how it fails",
      "minimal_fix": "smallest fix"
    }
  ],
  "tests_run": [],
  "residual_risk": []
}
```
