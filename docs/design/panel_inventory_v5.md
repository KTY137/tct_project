# Panel Composition Inventory for v5

Date: 2026-07-12

Scope: source-level inventory of the current QWidget cockpit panels. Counts
below include visible containers created by the panel source: `QGroupBox`,
`panel_kit` Card subclasses (`Card`, `FigureCard`, `CheckableCard`,
`CollapsibleCard`), and explicit `QFrame` panes. They exclude private header
and body frames created inside reusable kit widgets, plus plain `QWidget`
wrappers. Dynamic row frames are called out separately.

Shell note: `tct_gui._scrollable()` wraps every main tab panel in one
resizable no-frame `QScrollArea`. The `Scroll` line below reports internal
scroll areas first, then notes the shell wrapper where applicable.

## Motor Stage - `motor_panel.MotorPanel`

- Layout: outer `QVBoxLayout` containing `QSplitter(Qt.Horizontal)`. Left is a
  controls `QWidget` with `QVBoxLayout`; right is a framed stage-view pane.
- Frames: 5 Cards, 4 explicit QFrames in the panel, plus the `StageView`
  internal segmented QFrame. Max framed depth: 3 (`Jog` Card >
  `controlCluster` QFrame > segmented QFrame).
- Scroll: 0 internal, plus 1 shell tab wrapper.
- Hero: `StageView` in the right splitter pane, about 55-60% by
  `split.setSizes([360, 560])`.
- Commands: jog cross, Z jog, step segmented buttons, absolute move, Home,
  Center, Zero Here, full-width STOP, scan-start helper buttons.
- Recomposition friction: fixed splitter seed sizes, `StageView.setMinimumWidth(320)`,
  48 px jog buttons, 44 px STOP height, custom nested jog cluster, many controls
  stacked before the hero.

## Reference Monitor - `intensity_panel.IntensityPanel`

- Layout: `QVBoxLayout`: panel header, two-tile `MetricGrid`, waveform figure,
  command row.
- Frames: 1 FigureCard. Max framed depth: 1.
- Scroll: 0 internal, plus 1 shell tab wrapper.
- Hero: reference waveform `FigureCard`, about 65-70% of the panel height.
- Commands: scale spinbox, Apply scale, Check stability.
- Recomposition friction: simple shape, but commands sit below the plot and
  there is no side inspector; live waveform owns almost all useful area.

## Camera - `camera_panel.CameraPanel`

- Layout: `QVBoxLayout` with header, then `QHBoxLayout` content. Left column
  has status chips, image stack, histogram, stats, metadata, capture actions;
  right column is acquisition and device-control forms.
- Frames: 9 Cards, 1 explicit QFrame temp readout. Max framed depth: 2
  (Frame info Card > temp readout QFrame).
- Scroll: 0 internal, plus 1 shell tab wrapper.
- Hero: live image `QStackedWidget` inside a bare Card, about 45-50% of the
  default panel after histogram/stats/action rows are included.
- Commands: Live/Single/Stop action bar, crosshair/overlay toggles, Save frame,
  Capture/Clear background, Set ROI, exposure/gain/fps Set buttons, trigger
  checkbox.
- Recomposition friction: image label minimum 480x320, hard 3:1 left/right
  layout, many cards under the image, right column is pure forms.

## Oscilloscope - `scope_panel.ScopePanel`

- Layout: `QVBoxLayout`: header, `QSplitter(Qt.Horizontal)` for plot and side
  column, then bottom acquisition row.
- Frames: 6 Cards, 4 dynamic `_ChannelCard` QFrames by default, 1 segmented
  QFrame in the acquisition row. Max framed depth: 2 (`Channels` Card >
  channel QFrames).
- Scroll: 1 internal side-column `QScrollArea` with no frame, plus 1 shell tab
  wrapper.
- Hero: `Live trace` plot Card in the left splitter pane, about 65-70% of the
  working area by `split.setSizes([820, 400])`.
- Commands: trigger settings button, per-channel enable/role cards,
  measurements toggle, display/scale sliders, channel setup form, Live/Single,
  averaging, cursor mode, export, Test, List VISA.
- Recomposition friction: fixed splitter seed sizes, side scroll minimum width
  360, dense controls embedded in a scroll area, two 90 px line edits, plot
  mouse zoom disabled to protect scope divisions.

## Laser / Trigger - `laser_panel.LaserPanel`

- Layout: `QVBoxLayout`: header, status chips, manual-laser banner, waveform
  generator Card, collapsed PDL metadata Card, stretch.
- Frames: 3 Cards. Max framed depth: 1.
- Scroll: 0 internal, plus 1 shell tab wrapper.
- Hero: waveform-generator form Card, roughly half the default panel; there is
  no large plot or visual data surface.
- Commands: Output on/off, Apply settings, Test Connection, List VISA, Save
  metadata, live form edits for frequency/pulse/amplitude/load.
- Recomposition friction: form-first composition, persistent banner above the
  primary controls, collapsed metadata below, no splitter or hero canvas.

## Scan Viewer - `scan_viewer_panel.ScanViewerPanel`

- Layout: `QVBoxLayout`: header, `ScanMapView`, terminal banner, metric grid,
  action bar, collapsible Z-focus card.
- Frames: 2 Card subclasses in the panel (`CollapsibleCard`, Z-focus
  `FigureCard`), 1 internal `ScanMapView` FigureCard, and 3 explicit QFrames.
  Max framed depth: 2 (Z-focus Card > edge/amp frames or Z-focus FigureCard).
- Scroll: 0 internal, plus 1 shell tab wrapper.
- Hero: `ScanMapView` map/empty-state stack, about 55-65% of the panel.
- Commands: map quantity/freeze/export toolbar, Pause, Abort, Open in Analysis,
  Find focus, Apply to Planner, Z-focus form controls.
- Recomposition friction: map minimum height 240, Z-focus plot maximum height
  160, terminal banner/metrics/action/Z-focus stack competes with hero height.

## Scan Planner - `planner_panel.PlannerPanel`

- Layout: `QVBoxLayout`: custom top `QHBoxLayout`, then body `QHBoxLayout`
  with palette pane, recipe-tree pane, and run-readiness aside.
- Frames: 3 fixed QFrame panes (palette, recipe tree, aside), plus dynamic
  QFrame item widgets for loop/action/ghost rows. Max framed depth: 2
  (tree pane > row frame).
- Scroll: 0 internal, plus 1 shell tab wrapper.
- Hero: `_RecipeTree` in the center pane, about 50-60% after 200 px palette
  and 340 px aside are reserved.
- Commands: Save/Load routine, Undo, drag/double-click palette actions, Use
  current position, Use focus Z, context menu, Validate, Dry run, Arm/Start or
  ArmLatch, Abort.
- Recomposition friction: no splitter, palette `setMaximumWidth(200)`, aside
  `setMaximumWidth(340)`, value spins fixed at 76 px, many custom tree row
  frames and inline row styles.

## Bias Supply - `multi_bias_panel.MultiBiasPanel` + `bias_panel.BiasPanel`

- Layout: actual tab root is `MultiBiasPanel`: `QVBoxLayout` with header,
  status row, and `QTabWidget`; each channel tab hosts one `BiasPanel`
  `QVBoxLayout`.
- Frames: wrapper has 0 framed containers. Each `BiasPanel` tab has 4 Card
  subclasses and no explicit QFrames/QGroupBoxes. Max framed depth: 1.
- Scroll: 0 internal, plus 1 shell tab wrapper.
- Hero: wrapper hero is the channel tab widget. Per channel, the voltage/current
  HV-state `MetricGrid` is only about 15-20%; control Cards dominate.
- Commands: global ALL OUTPUTS OFF, per-channel compliance apply, Ramp to
  voltage, Output OFF, Switch polarity, IV scan, bias+waveform scan.
- Recomposition friction: nested tabs inside the main tab, form stack is tall,
  sweep plots are lazy raw pyqtgraph widgets capped at 160 px, no large safety
  dashboard canvas.

## Calibration - `calibration_panel.CalibrationPanel`

- Layout: `QVBoxLayout`: panel header, intro, chip row, four form groups,
  save/status/current labels, stretch.
- Frames: 4 QGroupBoxes, 0 Cards, 0 explicit QFrames. Max framed depth: 1.
- Scroll: 0 internal, plus 1 shell tab wrapper.
- Hero: no true hero; the repeatability group is the largest single block,
  roughly 30-35% when expanded with result/progress labels.
- Commands: Run reference-diode calibration, Apply and Save, Run Repeatability
  Test, Stop.
- Recomposition friction: old `QGroupBox` stack, long repeatability prose,
  method-specific groups show/hide, no split between procedure and inspector.

## Monitor - `monitor_panel.MonitorPanel`

- Layout: `QVBoxLayout`: header with alarm chip, four headline tiles, polling
  toolbar, `QSplitter(Qt.Vertical)` for table and history plot.
- Frames: 2 Cards (`All channels`, `History` FigureCard/Card). Max framed
  depth: 1.
- Scroll: 0 internal, plus 1 shell tab wrapper.
- Hero: table and history plot split the body roughly evenly by
  `splitter.setSizes([250, 250])`; no single dominant hero.
- Commands: polling interval spinbox, Start toggle, table row selection.
- Recomposition friction: vertical splitter makes table and plot compete,
  equal seed sizes, details table is always first-class instead of a drawer.

## Analysis - `analysis_panel.AnalysisPanel`

- Layout: `QVBoxLayout`: header, compact file/status Card, `QStackedWidget`
  for recent-runs page vs loaded-analysis page. Loaded page has a segmented
  mode row and another stack for map vs CCE.
- Frames: 3 Cards across states (header Card, Recent runs Card, CCE
  FigureCard), plus `ScanMapView` internal FigureCard in map mode and 1
  segmented QFrame. Max framed depth: 1.
- Scroll: 0 internal, plus 1 shell tab wrapper.
- Hero: recent-runs list when empty, or ScanMapView/CCE plot when loaded;
  about 70% of the panel below the header card.
- Commands: Browse, recent-run click, 2D map/CCE segmented switch, map exports,
  Export all arrays, Plot CCE vs bias, Export CCE CSV.
- Recomposition friction: nested stacks hide alternate heroes, header chip row
  can crowd, Finder-style source list and preview are not simultaneous.

## Settings - `settings_window.SettingsWindow`

- Layout: `QDialog` with `QVBoxLayout`: panel header, path row, state chip row,
  `QTabWidget`, info label, button row. Six device tabs are scroll areas; Full
  YAML is a Card-wrapped editor page.
- Frames: 7 Cards total (6 device section Cards plus YAML Card), 0 QGroupBoxes,
  0 explicit QFrames. Max framed depth: 1.
- Scroll: 6 internal `QScrollArea` device tabs; Full YAML has no scroll wrapper.
- Hero: active tab content; either one form Card in a scroll area or the YAML
  editor Card. The tab widget occupies most of the dialog.
- Commands: Reload from File, Save, Close, Browse data directory, VISA picker
  scan buttons inside address pickers.
- Recomposition friction: fixed initial size 820x680, tab-per-device form
  model, backend subforms show/hide inside one Card, YAML editor uses no-wrap,
  section widgets rebuild when returning from Full YAML.

## Device Manager - `device_panel.DeviceManagerWindow`

- Layout: `QMainWindow` with central `QWidget` `QVBoxLayout`: Hardware Devices
  Card and bottom command row.
- Frames: 1 Card, 0 QGroupBoxes, 0 explicit QFrames. Max framed depth: 1.
- Scroll: 0 internal.
- Hero: device table inside the Card, about 70-75% of the window.
- Commands: per-row Connect/Disconnect buttons, Connect All, Disconnect All.
- Recomposition friction: fixed initial size 620x380, table cells contain live
  widgets/buttons, columns mix stretch and resize-to-contents, no standard
  panel header.
