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
