# Design notes

Design plans, council seats, and campaign artifacts for architecture- and
UI-scale decisions — written by Adam, Prometheus (`researcher`), Abel, or an
external council seat (Codex/Ollama advisory lanes), for Kaya to ratify.
Distinct from `docs/research/` (external reference material, owned by
Prometheus) and from `docs/DECISIONS.md` (the one-line ADR ledger of what was
actually ratified, owned by Kiroku).

Conventions:
- One document per proposal / council seat / audit. Paths are relative to
  `docs/design/`.
- The **canonical, currently-binding** spec is `cockpit_design_system.md`
  (v4) — panel work that contradicts its 8 laws does not merge. Everything
  below marked **ACTIVE (v5 campaign)** is live follow-on work building on
  that frozen v4 contract, not a competing spec.
- Design docs unrelated to the cockpit-visual track (remote control, save
  policy, camera survey) are proposals in their own right; see their own
  `Status:` line for ratification state.

## Index of design documents

| Date | File | Status | Notes |
|---|---|---|---|
| 2026-07-12 | `cockpit_design_system.md` | CANONICAL v4 (frozen) | The contract — panels that violate the 8 laws do not merge; ratified after a 7-seat design council + two iteration rounds. |
| 2026-07-12 | `second_opinion_codex.md` | REFERENCE (v4 council source) | Codex adversarial review of the pre-v4 design draft (v2 HTML artifact); cited as a source in `cockpit_design_system.md`'s header. |
| 2026-07-12 | `council/ollama_advisory.md` | REFERENCE (v4 council source) | GPU-lane Ollama advisory seat (colorblind pairing, hold-to-arm timing, glove hit-targets, animation discipline); cited as a source in `cockpit_design_system.md`'s header. |
| 2026-07-12 | `council_v5_codex.md` | ACTIVE (v5 campaign) | Codex council seat: shell/material translation losses + per-panel v5 moves + translucency strategy. |
| 2026-07-12 | `council_v5_noah.md` | ACTIVE (v5 campaign) | Noah council seat: chrome collapse (one band + one strip), settings-row control grammar, offline-state pattern, Qt feasibility. |
| 2026-07-12 | `council_v5_jonathan.md` | ACTIVE (v5 campaign) | Jonathan council seat: data-facing panels (scope/monitor/analysis/scan-viewer) — data-ink rulings, fC display fix, rejects a translucent map HUD. |
| 2026-07-12 | `council_v5_paul.md` | ACTIVE (v5 campaign) | Paul council seat: the canonical 9-rung hardware-state taxonomy (OFFLINE…TRIPPED) feeding every chip/dot/banner. |
| 2026-07-12 | `council_v5_abel.md` | ACTIVE (v5 campaign) | Abel council seat: run-control grammar (Planner recipe rows, Viewer run-HUD single-source ruling, command-palette safety filter). |
| 2026-07-12 | `feinschliff_gap_notes_adam.md` | ACTIVE (v5 campaign) | Adam's own panel-by-panel screenshot review against the v5 bar (capture set `ui_audit_20260712T184707Z`); feeds the v5 fix list directly. |
| 2026-07-12 | `panel_inventory_v5.md` | ACTIVE (v5 campaign) | Source-level QWidget composition inventory (frame counts, hero region, recomposition friction) per panel — the v5 recomposition baseline. |
| 2026-07-12 | `feature_requests_v5.md` | ACTIVE (v5 campaign) | Feinschliff-session feature backlog: theme editor (in flight), QML-shell-default flip (ratified), sensor mosaic, 1D slicer, planner blocks, sequencer (one open safety question). |
| 2026-07-12 | `state_color_census.md` | ACTIVE (v5 campaign) | D4 static census of every status/state color use in `gui/` against Paul's 9-rung ladder (Codex lane; ground truth for the W1 taxonomy sweep). |
| 2026-07-12 | `drafts/qml/MetricTile.draft.qml` | DRAFT (unmerged) | Ollama GPU-lane QML draft — Adam's review calls it "the agreed starting point for the Scan Viewer slice tiles" but not runnable as drafted (5 defects listed); not yet landed in the real `gui/qml/MetricTile.qml`. |
| 2026-07-11 | `apple_style_ui_audit.md` | REFERENCE (v4 council source) | Screenshot-grounded Apple-style audit of the pre-v5 build (offscreen captures, dark+light contact sheets); cited as a source in `cockpit_design_system.md`'s header. |
| 2026-07-11 | `run_state_facade.md` | IMPLEMENTED (2026-07-11) | `RunStateViewModel` read-only facade design (Abel); built the same day (commit `713eeae`, `gui/run_state_viewmodel.py`) — the QML-hybrid architecture track, separate from the visual v4/v5 campaign. |
| 2026-07-10 | `camera_survey_metrology.md` | DESIGN (pending ratification) | Camera-survey mosaic + stage-repeatability metrology proposal (Prometheus); referenced by `feature_requests_v5.md` §3 ("Sensor mosaic") but not yet built. |
| 2026-07-08 | `save_policy.md` | DESIGN (pending ratification) | Modular/pluggable HDF5 save-policy proposal (Prometheus) — store derived scalars only, ~10x smaller files; a format-contract change, not yet ratified or built. |
| 2026-07-07 | `cockpit_style_overhaul.md` | SUPERSEDED by v4 spec | Adam's pre-council "TCT Cockpit" visual/UX-polish plan (formalized from a Codex draft) — superseded wholesale by the ratified v4 canonical spec after the 7-seat design council. |
| 2026-07-06 | `gui_architecture_plan.md` | SUPERSEDED by v4 spec | Pre-council settings/Device-Manager/anti-God-object notes; its central QWebEngineView-embedded-planner direction was overridden by the native-QTreeWidget planner decision (2026-07-07, "embed shelved"), and its panel-shape guidance is now covered by the ratified v4 spec. |
| 2026-07-04 | `remote_control_plan.md` | PROPOSAL (unimplemented) | Master/slave remote-control architecture (Abel) — lab machine stays sole hardware owner, home side gets low-bandwidth telemetry only; design-only, nothing built. |

Maintained by Samantha (`docs-dev`); update the Status/Notes columns whenever
a design doc is added, ratified, or superseded.
