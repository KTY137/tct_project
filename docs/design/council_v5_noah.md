# Noah Council Seat: Cockpit v5 — chrome, grammar, Qt feasibility

Date: 2026-07-12. Inputs: Adam's feinschliff notes, Codex seat, Prometheus
vibrancy research, design system v4 (the 8 laws), live code:
`TCT_app/tct_gui.py`, `gui/qml/Shell.qml`, `gui/panel_kit.py`, `gui/style.py`.

## 1. Chrome collapse: one band + one strip

The QML shell (`TCT_QML_SHELL=1`) already kills the toolbar and ribbon; v5
makes it the DEFAULT and merges its four rows (rail 48 + sim 26 + shelf 44 +
strip ~112 = 204-230px) into two:

- **Band (48px):** brand mark · **tab pills moved up here** (center,
  Flickable) · Connect/Disconnect All · icon cluster (Devices/Settings/Log/
  Debug) · theme toggle. Cheap: Shell.qml's pill Repeater relocates into
  `railRow`; `tabShelf` adapter unchanged; detach ⧉ stays on the active pill
  (overhaul hard rule 8).
- **Strip (~64px):** ONE merged status surface. Today the rail's StatChips
  (HV/Scan/State) duplicate ScanStatusStrip's tiles — merge into: State ·
  HV·measured · Progress·ETA · Position MetricTiles (§5 hierarchy) + the
  device DOT ROW (4-state, tooltips — this is where the old ribbon's dots
  live) + compact Motion/Laser/Scope chips right. All bindings already exist
  in `shell`/`runState`/`scopeVm`; this is QML re-composition, zero Python.
- **Sim ribbon (26px, conditional):** stays as-is — law 6 mandates it; it is
  a safety element, exempt from the row budget, and vanishes when real.

Disposition of every existing surface:
- **QMenuBar: KEEPS its native row** (~24px). It is the keyboard/a11y truth
  (Ctrl+, / Quit / About / checkable Log-Debug) and costs nothing. Merging it
  into a custom titlebar needs a frameless window — the same Qt6
  frameless/translucent swamp Prometheus flagged for Mica. Not worth it.
- **QToolBar: dies** (already hidden in QML mode; every action re-routed —
  `_build_menu_and_toolbar` actions are the single source, rail buttons call
  the SAME handlers). Delete the visible toolbar path once QML is default;
  keep QActions alive for menus + shortcuts.
- **Green CONNECT ALL:** already fixed in Shell.qml (accent-quiet outline;
  law 1). Classic QSS `#connectBtn` green dies with the toolbar.
- **Device ribbon: dies** → dot row in the strip. The classic
  `strip_scroll` QScrollArea (the 1440px overflow bug) goes with it.
- **Breadcrumb "TCT CONTROL · X" eyebrow: dies.** The tab pill already names
  the panel. `panel_header` keeps title + trailing chips; eyebrow slot is
  reserved for real context (e.g. device identity), not app-name echo.
- **QStatusBar "Disconnected": dies as a duplicate.** Repurpose the status
  bar for transient toasts/QAction statusTips only, or hide it.

Cost: cheap-to-medium. All QML-file edits + one default flip in
`tct_gui._build_central` (classic shell stays behind a fallback flag + the
existing fail-safe notify path). Net chrome: 24 + 48 + 64 = ~136px, no
overflow at 1280px (rail fit is already pinned by `test_qml_shell.py`).

## 2. Control grammar: killing the full-width field

The disease: panels drop controls into QFormLayout/VBox, so a QLineEdit for
"1000.00 Hz" spans 1200px. The v5 grammar (macOS System Settings):

- **`settings_row(label, control, unit=None)`** — NEW in `panel_kit.py`:
  sentence-case label left, stretch, **intrinsic-width control right**,
  muted unit label after. Numeric widths from font metrics × content class
  (`_intrinsic_width("−9999.99")` ≈ 9ch), never Expanding. Numeric fields
  right-align text (`Qt.AlignRight`), mono via existing QSS.
- **`FormSheet`** — a Card variant that stacks settings_rows with hairline
  separators and caps content width (~560px `maximumWidth`, left-anchored),
  so a wide window yields margin, not a wider field.
- Retrofit ONCE: both land in panel_kit; panels swap `form.addRow(...)` for
  `sheet.add_row(...)` mechanically during their D-phase. `form_row`
  (caption-over-control) stays for command trays (jog/absolute-move); the
  horizontal settings_row is for configuration panes. One guard test:
  no `QSizePolicy.Expanding` line-edits inside a FormSheet.

## 3. Offline/empty states: one pattern, panel-level

Replace N-per-widget "NO X YET" capsules and fake empty axes with ONE switch:

- **`StateStack`** — NEW thin panel_kit wrapper: a `QStackedLayout` holding
  page 0 = live content (hero + tiles), page 1 = the existing `EmptyState`
  (icon + one sentence + hint/retry) centered on a `well`-token canvas.
  `set_offline(reason)` / `set_live()` flips pages; tiles never render
  placeholders because they are simply not shown.
- Kills: RefMon/Scope/Monitor fake 0.1-0.9 axes (plot page hidden, not drawn
  with fake data — law 7 adjacent), Camera's 7 "NO FRAME YET" capsules,
  Analysis's 4 grey chips, Monitor's "ALL NOMINAL"-with-no-data (offline page
  states "No readings yet"), Scan Viewer's 4× "NO RUN YET" (its designed
  empty state becomes the shared component). Cost: near-zero — QStackedLayout
  swap, no repaint burden, EmptyState already themed + error-variant capable.

## 4. Instrument well (light-theme dark plots)

Build ONCE inside `FigureCard` (every dark plot already passes through it):

- Outer `QFrame#instrumentWell`: `background: PLOT_BG`, uniform 1px
  `hairlineStrong` border, `border-radius: 10px`, **3px padding** — the plot
  stays a square opaque widget inside; the padding lets the dark well round
  the corners visually without clipping/repainting pyqtgraph.
- **Glass header:** the Card header row gets `background: chrome` token +
  bottom hairline (pre-blended fake glass per Prometheus §4.1 — no blur).
- **Inner shadow, faked static:** a 3px flat QWidget strip under the header
  colored `_blend("#000000", PLOT_BG, 0.35)` (new `wellShade` token). NOT a
  per-side border on the well — `test_style_hover_hotpath_guard.py` bans
  per-side border colors on plot containers (four-edge paint path), and rule
  3 bans effects. Flat sibling widgets cost nothing per frame.
- Same treatment fixes the motor position readout only if it STAYS a plot;
  Adam is right that the non-plot readout should instead follow panel
  surface tokens (separate one-line fix in motor_panel).

## 5. Motion & hover

Worth it (all chrome-only, token-only, ~200ms — law 8): pill/ShellButton
hover wash (shipped, pinned by `test_style_hover_hotpath_guard.py`);
settings_row hover wash in FormSheet; bottom-sheet snap (Z-focus,
measurements drawer) via one QPropertyAnimation on `maximumHeight`
(OutCubic) in `CollapsibleCard`; arm-latch hold-progress (already a designed
state). Hard boundaries: no `QGraphicsEffect` ever on FigureCard/camera/map
(pinned headless: `card.graphicsEffect() is None`); no `Behavior on` bound
to live data values (values update, they don't animate); no animated opacity
over any plot; one attention pulse per new critical alarm, nothing else
loops.

## 6. Verdict on Codex's 3 Mac ideas

1. **Xcode workspace chrome:** KEEP as a composition convention per panel
   (Planner proves it) — but NO new docking framework; DetachableTabWidget
   stays the engine (hard rule 8). Defer any nav-column shell to post-D6.
2. **Command palette:** KEEP, D6 as roadmapped — cheap (frameless QDialog +
   QListView + fuzzy filter), state-aware, safe/read commands only; anything
   dangerous routes to the panel's DangerGate, never executes from the
   palette.
3. **Quick Look overlay:** DEFER past D6 — needs a run-summary model that
   doesn't exist yet; ship Analysis recents (D5) first, then reuse its
   preview as the overlay body. Not a v5 gate.
