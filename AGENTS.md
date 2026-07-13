# AGENTS.md -- Codex rules for project_tct

This repo is connected to the external **Daedalus** harness (renamed from
`agent_env` 2026-07-11; the folder is still `C:\Users\nukei\Desktop\agent_env`,
the Python package is now `daedalus`). Use it for Codex/Claude/local-bench
handoffs instead of inventing ad hoc cross-agent messages.

## Your work queue

**Check `docs/CODEX_QUEUE.md` first** — Adam (the Claude orchestrator)
maintains stateless task briefs for Codex there, with per-task constraints,
verification commands, and handback rules. Work it top-to-bottom unless Kaya
scopes otherwise. Leave results uncommitted; Adam reviews (qa-critic gate)
and commits.

## Route Through The Harness

- For token-safe local delegation, queue work with:

  ```powershell
  python -m daedalus.file_bridge enqueue "<task>" --project project_tct --lane local_only
  ```

- For normal routing when Claude tokens are available, use:

  ```powershell
  python -m daedalus.file_bridge enqueue "<task>" --project project_tct --lane auto
  ```

- The watcher must be running for queued requests to be processed:

  ```powershell
  python -m daedalus.file_bridge watch --project project_tct
  ```

Reports land in `C:\Users\nukei\Desktop\agent_env\inbox\`; queued requests live
in `C:\Users\nukei\Desktop\agent_env\outbox\`; recovery memory is in
`C:\Users\nukei\Desktop\agent_env\memory\todos.local.md`.

## Rules

- Never talk directly to Claude Code or another agent. Use the file bridge.
- Prefer `local_only` while Claude tokens are exhausted. Note (2026-07-11):
  the local Ollama lane is CPU-bound on this laptop — only SMALL single-file
  mechanical tasks belong there; medium tasks come to Codex via the queue.
- Do not run code that can touch real hardware. Tests must stay simulated/headless.
- Treat `TCT_app/devices/`, `TCT_app/controller/`, real instrument configs, and
  lab reference material as protected unless the user explicitly scopes the work.
- Return concise, structured findings with files/tests/risks/todos when acting
  as a specialist.

<!-- AGENT_ENV_ENFORCED:BEGIN -->

## Daedalus Enforcement (harness renamed from agent_env, 2026-07-11)

This repository is managed by the external Daedalus harness. When delegating
work, use the harness file bus instead of direct agent-to-agent messages.

- Token-safe local path:

  ```powershell
  python -m daedalus.file_bridge enqueue "<task>" --project project_tct --lane local_only --source codex
  ```

- Normal routed path:

  ```powershell
  python -m daedalus.file_bridge enqueue "<task>" --project project_tct --lane auto --source codex
  ```

- The watcher must be running:

  ```powershell
  python -m daedalus.file_bridge watch --project project_tct
  ```

Rules:
- Prefer `local_only` while Claude tokens are exhausted.
- Do not bypass Ikarus for local/Ollama work.
- Read reports from `C:\Users\nukei\Desktop\agent_env\inbox`.
- Check recovery memory at `C:\Users\nukei\Desktop\agent_env\memory\todos.local.md`.

<!-- AGENT_ENV_ENFORCED:END -->
