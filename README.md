# project_tct

Root repository for the TCT laboratory control project.

The application lives in [`TCT_app/`](TCT_app/). Project-level documentation,
agent setup, and owned source files are versioned from this root so the app and
its operating context move together.

## Layout

| Path | Purpose |
|---|---|
| `TCT_app/` | PySide6 TCT control application |
| `docs/` | Architecture, design, and research notes |
| `.claude/agents/` | Local agent definitions used while developing the app |
| `sources/` | Project-owned source notes and non-sensitive source material |
| `reference/` | Local-only third-party/reference material, ignored by Git |
| `lab_assets/` | Local-only lab photos/manuals/assets, ignored by Git |

See [`docs/REFERENCE_MATERIAL.md`](docs/REFERENCE_MATERIAL.md) before using or
sharing anything from `reference/`, `lab_assets/`, or `sources/git_history/`.

## Development

From `TCT_app/`:

```powershell
.\setup.ps1
.\run.ps1
python -m pytest tests -q
```

The test suite runs against simulated devices and must not require lab hardware.
