# Agent Workflow

This repo is the app workspace. The reusable local orchestrator lives outside
the repo at:

```text
C:\Users\nukei\Desktop\agent_env
```

Use `agent_env` for Claude/Codex bridge requests, structured reports, and local
recovery memory.

Important local-only memory files:

```text
C:\Users\nukei\Desktop\agent_env\memory\events.local.jsonl
C:\Users\nukei\Desktop\agent_env\memory\todos.local.md
```

These are ignored by Git and exist so TODOs survive token limits, crashes, and
interrupted agent sessions. Before resuming after an interruption, inspect
`todos.local.md` and the current `git status`.

Standard flow:

1. Work on `root-cleanup`.
2. Keep agent tasks small and stateless.
3. Queue Claude reviews through `agent_env/outbox/*.json` or
   `python -m agent_env.file_bridge enqueue ...`.
4. Read reports from `agent_env/inbox/*.report.json`.
5. Preserve unresolved TODOs in `agent_env` memory before ending a session.
