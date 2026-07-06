# AGENTS.md -- Codex rules for project_tct

This repo is connected to the external `agent_env` harness at
`C:\Users\nukei\Desktop\agent_env`. Use it for Codex/Claude/local-bench
handoffs instead of inventing ad hoc cross-agent messages.

## Route Through The Harness

- For token-safe local delegation, queue work with:

  ```powershell
  python -m agent_env.file_bridge enqueue "<task>" --project project_tct --lane local_only
  ```

- For normal routing when Claude tokens are available, use:

  ```powershell
  python -m agent_env.file_bridge enqueue "<task>" --project project_tct --lane auto
  ```

- The watcher must be running for queued requests to be processed:

  ```powershell
  python -m agent_env.file_bridge watch --project project_tct
  ```

Reports land in `C:\Users\nukei\Desktop\agent_env\inbox\`; queued requests live
in `C:\Users\nukei\Desktop\agent_env\outbox\`; recovery memory is in
`C:\Users\nukei\Desktop\agent_env\memory\todos.local.md`.

## Rules

- Never talk directly to Claude Code or another agent. Use the file bridge.
- Prefer `local_only` while Claude tokens are exhausted.
- Do not run code that can touch real hardware. Tests must stay simulated/headless.
- Treat `TCT_app/devices/`, `TCT_app/controller/`, real instrument configs, and
  lab reference material as protected unless the user explicitly scopes the work.
- Return concise, structured findings with files/tests/risks/todos when acting
  as a specialist.

<!-- AGENT_ENV_ENFORCED:BEGIN -->

## Agent Env Enforcement

This repository is managed by the external `agent_env` harness. When delegating
work, use the harness file bus instead of direct agent-to-agent messages.

- Token-safe local path:

  ```powershell
  python -m agent_env.file_bridge enqueue "<task>" --project project_tct --lane local_only --source codex
  ```

- Normal routed path:

  ```powershell
  python -m agent_env.file_bridge enqueue "<task>" --project project_tct --lane auto --source codex
  ```

- The watcher must be running:

  ```powershell
  python -m agent_env.file_bridge watch --project project_tct
  ```

Rules:
- Prefer `local_only` while Claude tokens are exhausted.
- Do not bypass Ikarus for local/Ollama work.
- Read reports from `C:\Users\nukei\Desktop\agent_env\inbox`.
- Check recovery memory at `C:\Users\nukei\Desktop\agent_env\memory\todos.local.md`.

<!-- AGENT_ENV_ENFORCED:END -->
