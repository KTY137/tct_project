# Apple-Style Cockpit UI Audit

Date: 2026-07-11
Branch: `design/cockpit-v5`

## Inputs

- Visual reference: `artifacts_claude/tct_polish_preview.html`
- Captures: `artifacts_claude/apple_style_ui_audit_latest/`
- Zip: `artifacts_claude/apple_style_ui_audit_latest.zip`
- Key contact sheets:
  - `artifacts_claude/apple_style_ui_audit_latest/contact_sheet_dark.png`
  - `artifacts_claude/apple_style_ui_audit_latest/contact_sheet_light.png`
  - `artifacts_claude/apple_style_ui_audit_latest/dark/detached_scan_viewer.png`

The screenshots were generated against an all-simulated temporary config under
`QT_QPA_PLATFORM=offscreen`, with persisted user window state disabled. No real
instrument connection was attempted.

## Executive Verdict

The v5 pass improved token consistency and introduced the right vocabulary
(ribbon, chips, tabs, card surfaces, motion affordances), but it did not yet
match the artifact because the composition stayed old-desktop Qt:

- The OS-style menu bar plus toolbar dominates the first viewport.
- The system ribbon is functional but still reads as a row of boxed widgets,
  not a composed translucent rail.
- The tab row is still a small native tab strip rather than a confident pill
  navigation layer with a polished detach affordance.
- Most panels remain dense form pages with full-width fields and many nested
  borders.
- Typography looks too chunky in the captures. Labels and headings feel loud,
  while values and primary surfaces do not breathe enough.
- Empty states are plain text rather than designed states.
- The current implementation copied some artifact colors and tokens, but not
  the artifact's frame: one composed app surface, calm material layers, a
  map-first body, segmented controls, large soft metrics, and restrained action
  hierarchy.

What is good: the app already has strong functional structure, especially the
Planner, Scope, Camera, Motor, and detachable-tab workflow. We should not throw
that away. The best path is a production QWidget frame/composition pass first,
with a small Qt Quick/QML spike as the escape hatch for artifact-level material
and motion fidelity.

## Hard Constraint: Detachable Panels Stay

`DetachableTabWidget` is a product feature, not a styling detail:

- Double-click a tab to detach.
- Corner button detaches the active tab.
- Closing the floating window redocks the panel into its original slot.
- Persisted detached titles restore across app launches.

Any new shell, QML prototype, tab restyle, or panel reflow must prove this
contract with the existing headless detach/redock tests. If a QML route cannot
preserve detachable panels cleanly, it is not the production route.

## Frame-Level Findings

What works:

- The shell has all necessary global actions: connect, disconnect, settings,
  device manager, log, device debug, theme, and app state.
- The ribbon exposes cached state without adding hardware I/O.
- The tab model is already multi-monitor friendly.

Room for improvement:

- Merge toolbar actions into the composed top rail; do not leave the toolbar as
  a separate old Qt strip.
- Keep the menu bar available, but reduce its visual dominance. The cockpit
  frame should start with the app rail, not with menu/toolbar chrome.
- Compress device lights into a compact dot row and move HV, motion, scan, and
  laser into right-weighted status readouts.
- Make the tab row feel like a navigation shelf: larger pill tabs, calmer
  inactive text, active tab as material/tint, icon-only detach button with a
  tooltip.
- Use fewer boxed layers. One outer frame, one top rail, one tab rail, one panel
  body. Avoid stacked card-inside-card-in-groupbox patterns.
- Typography should be more Apple-like: normal body text, medium labels, large
  display values where values matter. Monospace should be reserved for numeric
  readouts and file/data identifiers.

## Panel Audit

| Panel | Done well | Needs improvement | Missing or weak controls |
| --- | --- | --- | --- |
| Motor Stage | Strong split between control column and stage visualization. Jog, absolute move, and stage map are understandable. | Too many nested borders; jog cluster feels like terminal chrome; top shell steals vertical space; labels are chunky. | Need a more physical jog controller, clearer "current position" hero readout, and more polished 2D/3D stage toggle. |
| Reference Monitor | Correct skeleton: status/readouts, scale control, big waveform. | Too much vertical fuss before the plot; readouts are small and black-boxy; plot should be the hero. | Stability action and scale should be grouped as a compact inspector, not spread across the full width. |
| Camera | Best macro-layout after Planner/Scope: image hero, right inspector, histogram, beam stats. | Empty image state is plain; acquisition state/start-stop is buried; right inspector feels like a form stack. | Needs designed empty state, clearer live/capture action area, and better beam-stat metric tiles. |
| Oscilloscope | Strong primary plot plus right inspector and bottom action row. | Too many micro-pills; text is too dense; bottom actions need clearer primary/secondary grouping. | Live/single/average/export should be staged as a command bar with one primary action at a time. |
| Laser / Trigger | Good semantic chips and visible output controls. | Full-width form slabs dominate; output state is just one row among many; metadata and waveform controls compete. | Output ON/OFF should be the hero control, with waveform generator as a command panel and laser metadata as compact details. |
| Scan Viewer | Correct workflow: map, progress, ETA, abort, open analysis, Z-focus. Detached behavior works. | This is the biggest artifact mismatch. Map is wide but shallow; Z-focus is a wall of fields; compact map currently hides useful toolbar affordances; metrics are too chunky/black-box. | Quantity, freeze levels, PNG/CSV export should move into a polished map header, not disappear. Z-focus needs compact/collapsible staging with Start and Apply Best Z emphasized. |
| Scan Planner | Most successful panel. Clear left/middle/right layout, danger gating, point estimates, axis rails. | Still dense and text-heavy; global shell hurts it; some pills are too small. | Mainly polish: larger breathing room, refined type, and shell integration. Do not rewrite first. |
| Bias Supply | Safety hierarchy is clear; all-off and output-off are visible. | Panel is mostly full-width fields; red actions dominate correctly but the page lacks a premium safety-dashboard structure. | Needs HV/current/compliance hero readouts, a command well for ramp/output, and a separated danger zone. |
| Calibration | Has the right controls for method and repeatability. | Long explanatory text acts like a header; the panel feels editorial, not procedural. | Needs a settings/procedure layout: method summary, apply/save action, repeatability test card with Run/Stop and results. |
| Monitor | Table plus chart is the right model. | Visually under-designed; no summary dashboard; Start/Poll controls float without a strong grouping. | Add compact environmental tiles, then table/chart, with poll controls as an inspector/action group. |
| Analysis | Good destination concept: run file, modes, map/CCE, exports. | Empty/data states are weak; top file area feels like a form; map canvas is large but not staged like a review workspace. | Should feel like Finder/Preview for scan runs: run header, segmented analysis modes, large map/plot body, quiet export actions. |

## Recommended Direction

### Track A: Production QWidget Frame v6

Do this first because it preserves hardware safety, pyqtgraph/camera hot paths,
and detachable panels.

1. Stabilize current v5 local edits and keep tests green.
2. Introduce a small `gui/shell_chrome.py` helper layer for the app rail and
   tab chrome. Keep `tct_gui.py` as a composition root.
3. Replace the visible toolbar-first composition with:
   - one material app rail containing brand, connect/disconnect, device manager,
     settings, log/debug toggles, and state;
   - one compact cached-status rail for device dots, HV, motion, scan, laser;
   - one pill tab shelf with a polished detach button.
4. Keep `DetachableTabWidget` as the production tab model.
5. Tune typography and spacing globally before per-panel surgery.

This should recover a large part of the artifact feel without a risky UI stack
rewrite.

### Track B: Panel Composition Pass

After Frame v6, reflow panels in priority order:

1. Scan Viewer: make map the hero, restore quantity/freeze/export affordances in
   a polished header, restage Z-focus as a compact live-assist card.
2. Camera: live image hero, empty state, acquisition inspector, better beam
   metrics.
3. Bias and Laser: safety dashboards with explicit command wells.
4. Monitor, Analysis, Calibration: review/settings/procedure layouts.
5. Motor, Reference, Scope: polish existing strong skeletons.

### Track C: Qt Quick/QML Spike

Qt Quick imports are available in the venv, so a better visual system is
technically possible. However, full migration is not the safe first move because
the existing app depends heavily on QWidget panels, pyqtgraph, camera display,
QThread safety, and detachable tab reparenting.

Build a QML spike only as a proof:

- Implement the artifact frame and three representative screens:
  Scan Viewer, Camera or Scope, and Bias.
- Feed simulated view-model data only.
- Screenshot it in dark and light.
- Explicitly test how detach would work in a hybrid shell.

Decision gate:

- If QML clearly beats QWidget and preserves detach, plan an incremental
  view-model migration.
- If QML cannot preserve detach cleanly, keep production on Widgets and port the
  successful QML composition back into QWidget/QSS/custom lightweight widgets.

## Near-Term Definition Of Done

- Contact sheets regenerated after every design pass.
- Full shell capture in light and dark.
- Detached panel capture for at least Scan Viewer and one hardware-control
  panel.
- Existing detach/redock tests remain green.
- No new hardware I/O in constructors, theme toggles, screenshot harnesses, or
  timers.
- No `setGraphicsEffect` on camera or pyqtgraph hot paths.
- No inline GUI hex outside `gui/style.py`.

