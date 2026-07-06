# Claude Agent Protocol

Purpose: keep subagents useful without burning the full parent conversation.

## Invocation Rules

- Adam is the only router. Subagents never talk to each other.
- Invoke one specialist at a time unless the tasks are truly independent.
- Pass only the immediate task, relevant paths, constraints, and short state.
- Do not pass the full user chat history.
- Treat each subagent call as stateless.
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
update the index/changelog in the same task. A health/drift check → **Mamoru**.
None of these run on their own — they are "always on" only because Adam calls them
by default.

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
