# GUI style overhaul — "TCT Cockpit"

*Author: Adam, 2026-07-07. Formalizes the Codex-drafted "TCT Cockpit" style
proposal into an actionable, repo-grounded plan after Adam's review. Companion
to [`gui_architecture_plan.md`](gui_architecture_plan.md) (structure /
anti-God-object) and [`remote_control_plan.md`](remote_control_plan.md).
This document is **visual/UX polish only** — no new hardware behavior.*

## 0. Verdict (review outcome)

**Green light, with reconciliation.** The direction is right: move the app off
the prototypical form-look toward a purpose-built lab cockpit — deeper layering,
axis rails, stronger action zones, better readouts — while staying PySide6/Qt
Widgets, simulated, and headless-testable (no Electron/web rewrite).

The one non-negotiable correction to the original draft: **build on the existing
`gui/panel_kit.py` + `gui/style.py` + `gui/status_widgets.py`, do not duplicate
them.** The draft named several "new" components that already have primitives in
the repo; those are *extensions*, not rewrites. The mapping in §2 is the
contract.

## 1. Hard rules (apply to every phase, non-negotiable)

1. **Extend, don't duplicate.** Every new component lands in `gui/panel_kit.py`;
   every color is a `gui/style.py` token. **Zero inline hex** in panel code
   (the only allowed exception is raw image-overlay constants, and those get
   tokenized in the same pass — see §3 Phase 4).
2. **Danger hierarchy stays loud.** HV enable/ramp, motion, homing, scan-start,
   and abort controls must remain the single most visually dominant element on
   any screen they appear on. Decorative glows/accents must never out-shout a
   `dangerBtn`/armed state. One danger visual language across all 12 panels — do
   not invent per-panel danger styling.
3. **No effects on the hot path.** The camera frame view and every pyqtgraph
   plot repaint continuously. **No `QGraphicsDropShadow`/glow/animated
   `QGraphicsEffect`** on those widgets or their containers — it forces
   per-frame recomposition and will tank FPS. Depth on the hot path is *static*
   only: borders, surface-step background, axis rails.
4. **Both themes contrast-checked.** Dark is the visual reference, but every new
   token is defined for **light and dark**, and light must stay WCAG-legible.
   Any panel that caches axis/plot/overlay colors implements
   `refresh_theme(mode)` and re-pulls tokens on theme switch (persisted user
   theme via `QSettings("TCT","TCTSetup")` must keep working).
5. **Don't feed the God-object.** Shell polish (toolbar, status ribbon, tabs)
   must add **no logic** to `tct_gui.py` (already ~870 lines). It stays a
   composition root; any behavior routes through the planned
   `connection_controller` / `scan_coordinator` extractions in
   [`gui_architecture_plan.md`](gui_architecture_plan.md) §3.
6. **Headless & sim-safe.** Every panel must construct and survive a
   `refresh_theme()` under `QT_QPA_PLATFORM=offscreen` with **no hardware**.
   No hardware I/O in constructors (existing safety rule).
7. **Order: Camera → Scan → Analysis.** ~~Quick Scan stays but is visually and
   logically subordinate to the Planner~~ — superseded 2026-07-07 (user
   decision): **ScanPanel is retired entirely**; the Planner is the only scan
   configuration/start surface, and a new **Scan Viewer** becomes the live
   surface (see Phase 2).
8. **Per-panel detach must survive — untouchable capability.** Every panel/tab
   must remain tear-off-able into its own free-floating window (multi-monitor),
   via `gui/detachable_tabs.py: DetachableTabWidget` (double-click a tab **or**
   the ⧉ corner button; re-dock by closing the window), plus the standalone
   `gui/scan_map_window.py`. The draft's "detach affordance less raw" line means
   **restyle the ⧉ button only** (icon + hover/tooltip polish) — it does **not**
   authorize removing, gating, or replacing detach with a fixed single-window
   layout. Any shell-polish change to tabs/docks keeps this behavior and is
   regression-guarded by a headless test that detaches a tab, asserts a floating
   window exists, closes it, and asserts the page re-docks to its slot.

## 2. Component mapping (draft name → repo reality)

The draft's "new" kit is mostly extensions of what exists. Land these in
`gui/panel_kit.py` unless noted.

| Draft component | Repo reality / action |
|---|---|
| `WorkbenchHeader(eyebrow, title, trailing, mark)` | **Extend existing `panel_header`** — it already does eyebrow+title; formalize the `trailing` slot + optional accent `mark`. Do not add a second header type. |
| `ActionBar(primary, secondary, danger)` | **New thin helper** — a styled `QHBoxLayout` wrapper that places buttons using the *existing* button property variants + `status_widgets.flash_button`/`dangerBtn`. It owns layout, not new button styling. |
| `FigureCard(title, subtitle)` | **New, built on `Card`** — a `Card` that hosts a pyqtgraph `PlotWidget`/image view with a tokenized header and (rule 3) **no** hot-path effects. |
| `MetricTile(label, value, state)` | **Built on existing `readout_cell`** — a single tokenized label/value tile with a `state` (normal/warn/armed) that maps to status colors. |
| `MetricGrid(...)` | **Layout of `MetricTile`s** — a grid arrangement, not a new widget class with its own painting. |
| `CheckableCard` | **`Card` + header checkbox** — enable/disable that greys child content; Z-focus is the first user. |
| `StatusBanner` | **Reuse `status_widgets.StatusChip/StatusPill`** styling at banner scale — one inline notice strip, tokenized. |
| `EmptyState` | **New, trivial** — centered icon + label + hint, for unloaded Analysis / disconnected Camera. |

New `gui/style.py` tokens (define for **both** themes): `panel_2`, `panel_3`,
`sunk`, `border_strong`, `hover`, `active`, plot/grid/overlay colors, and a
**static** `glow_*`/accent set used only for non-hot-path emphasis. Existing
keys stay backward-compatible (additive only).

Button variants become properties on the existing button styling (no new
classes): `primary`, `secondary`, `armed`, `danger`, `ghost`, `busy`.

## 3. Phased rollout

**Phase 0 — kit first (blocking).** Land the `panel_kit`/`style` extensions in
§2 with construction + theme-switch smoke tests, *before* touching panels. This
is what lets every subsequent panel be a thin re-skin.

**Phase 0.5 — parity pass (in flight now).** Bring **CameraPanel** and
**AnalysisPanel** up to parity with the already-migrated panels using the
*current* primitives (before the full cockpit rework), so all 12 panels are
consistent and headless-tested. This is the immediate task dispatched to Noah;
the deeper rework below builds on top of it.

**Phase 1 — CameraPanel (first cockpit target).** Main area as a large
`FigureCard` instrument screen with tokenized overlay colors; right-side
"Acquisition Console" (Exposure/Gain/FPS, Image Processing, Trigger, Camera
Info) as `Card`s; beam-stats/frame-info as a `MetricGrid`; histogram as a
`FigureCard`; top chips as a live ribbon. **Rule 3 applies hard here.**

**Phase 2 — retire ScanPanel, introduce the Scan Viewer.** *(Rescoped
2026-07-07, user decision; stress-tested by Prometheus 2026-07-08 — see
`docs/research/scan_viewer_design_review.md` for verdicts, gap list G1–G6,
re-wiring risks R1–R5, and the 7-step build order. Reframed per that review:
retiring ScanPanel retires the **widget and the quick-raster start path**; the
Planner becomes the only surface for grid/CCE routines, but BiasPanel keeps its
own voltage-scan entry and Z-focus is a live assist that cannot be a ScanPlan.)*

**DONE 2026-07-10:** ScanViewerPanel live cockpit (8312f41), wired via coordinator (884afe8), ScanPanel+ScanMapWindow retired, ScanMapView export+freeze-levels (46ff681), planner Use-current-position (48396c0), suite 657 passed, Mary APPROVE.

- **ScanPanel dies.** Its five responsibilities are re-homed, not lost:
  quick-raster form → gone (Planner covers it, proven via `plan_from_config`);
  voltage-scan entry → Planner + the surviving BiasPanel path (gap G2: retire
  or redirect ScanPanel's own vscan form only); live map / progress / ETA,
  Pause/Abort run control, and the Z-focus assist → the new **ScanViewerPanel**.
- **Safety precondition (G1, Paul/Abel, blocking):** the plan model has no
  per-BiasStep ramp shaping (`ramp_step_V`/`ramp_delay_s` exist only in the
  legacy `VoltageScanConfig` path). That gets added to the plan model **before**
  the legacy vscan path retires — HV must never step unshaped.
- **Decided 2026-07-08 (user):** `scan_map_window.py` **stays** as the
  standalone map-only window, re-fed by the shared map widget (multi-monitor:
  pure map on one screen, viewer elsewhere). Old quick-scan **param JSONs are
  dropped** (no migration) — scans persist as Planner recipes; remove the
  Save/Load JSON affordance with the panel.
- **Decided 2026-07-08 (Adam):** viewer gets an `EmptyState` when no scan runs
  and keeps the last finished run's map displayed (with a finished banner) for
  handoff; new seams `AnalysisPanel.load_run(path)` + run-path on scan finish
  are built for the "Open in Analysis" button; motor "Set as Scan Start"
  (gap G3) is re-pointed at the Planner; best-Z result offers an
  "apply to planner Z" action (G4); the live map's PNG/CSV export moves into
  the shared map widget so nothing regresses (G5).
- **ScanViewerPanel = the live acquisition surface** (run monitor): live map as
  a `FigureCard` (hot path — rule 3), progress/ETA/current-point as a
  `MetricGrid`, Pause/**Abort** in a fixed `ActionBar` (rule 2 — loudest thing
  on the screen), Z-focus as a `CheckableCard` with its live Z-vs-amplitude
  curve, and a post-run **"Open in Analysis"** handoff button that loads the
  just-written HDF5 into AnalysisPanel.
- **Kept separate from AnalysisPanel — deliberately.** Different data sources
  (live ScanController stream vs loaded HDF5 — never let the user wonder
  "am I watching live?"), danger-control clarity (Abort never sits next to a
  file browser), hot-path perf isolation, and the detach workflow (rule 8:
  float the live viewer on one monitor while reviewing runs on another).
- **Shared component:** one 2D map-rendering widget used by both the viewer
  (live) and AnalysisPanel (review) — built once in the kit.
- Signal re-wiring in `tct_gui` follows rule 5 (composition root only); the
  existing `start/abort/pause/z_focus/vscan_requested` glue moves to the
  planned `scan_coordinator` extraction — which lands **before** the viewer is
  built (while ScanPanel still exists, behavior-preserving, Mary-reviewed), so
  the viewer wires into the coordinator from day one. The viewer registers in
  `tct_gui._toggle_theme` and implements `refresh_theme(mode)` (it caches
  pens); it stays thread-free.

**Phase 3 — AnalysisPanel as a run-review surface.** File loader as a top-level
run header with dataset/status chips (or `EmptyState` when nothing loaded);
2D map + CCE as `FigureCard`s with export/quantity controls in the card headers;
Vdep / map min-max / dataset count / export-readiness as `MetricTile`s.

**Phase 4 — consistency sweep.** Migrate CalibrationPanel + Bias remnants from
`QGroupBox` to `Card`/`CheckableCard`; tokenize `scope_measurements.py`
(hardcoded cyan → readout tokens; already logged in `docs/TECH_DEBT.md`); give
every panel that caches colors a `refresh_theme(mode)`; purge remaining legacy
hex from GUI code.

**App-shell polish** (spread across phases, under rule 5): unify the toolbar on
qtawesome/mdi icons; reshape the status strip into a grouped "system ribbon"
(Connection · HV · Motion · Scan · Simulation); tabs get icon+label with a
stronger active state; Log/Device-Debug docks lose the raw-debug-window look.

## 4. Definition of done (per phase)

- All new/changed panels construct + `refresh_theme("light"/"dark")` under
  `QT_QPA_PLATFORM=offscreen` with no hardware attached.
- No inline hex introduced; new tokens exist in both themes.
- No `QGraphicsEffect` on any pyqtgraph/camera widget (grep clean).
- Danger controls remain the dominant element on their screen (visual review
  by Mary).
- `python -m pytest tests/ -q` stays green; `tct_gui.py` line count does not
  grow with logic (composition-root only).

## 5. Non-goals

- No web/Electron rewrite; no change to the scan/data contracts
  (`SCAN_DATA_FORMAT.md`).
- No new hardware commands or behavior — this is chrome, not control.
- No merge of Settings and Device-Manager windows (see
  `gui_architecture_plan.md` §2.3).
- **Not** a move to a fixed single-window layout. Per-panel tear-off into
  separate floating windows (`DetachableTabWidget`) is a kept capability, not a
  candidate for removal (see rule 8).
