# Codex Council Seat: Cockpit v5

Date: 2026-07-12
Scope: v4 design system, v4 HTML artifact, latest panel audit manifest, and
`TCT_app/gui/style.py` as implemented.

## Verdict

The current implementation has the right vocabulary but not the right material
behavior. It looks like Qt wearing better tokens, while the artifact feels like
one composed app surface. v5 should move from "restyled widgets" to "shell,
canvas, inspector" architecture: fewer frames, fewer native-looking controls,
more controlled material layers, and no translucency on live data surfaces.

## Five Translation Losses

1. Native chrome still wins over the cockpit shell.
   The artifact has one frosted rail, one tab shelf, and one status strip. The
   live screenshots have menu bar, toolbar, device ribbon, tab row, breadcrumb,
   title, and sometimes a status bar before the panel starts. In Qt terms:
   `QMenuBar`/`QToolBar` are still first-class surfaces, so the shell reads as
   stacked desktop chrome. v5 move: promote the QML shell to own navigation,
   global commands, connection state, and panel detach; demote the old toolbar
   to a command palette/debug drawer.

2. QSS approximates material with borders, not depth.
   `style.py` has good tokens (`raised`, `sunk`, `well`, `specular`), but QSS
   can only fake the artifact's inset highlights and shadows with border-top
   colors. The result is many crisp boxes, not soft Apple material. v5 move:
   keep QSS for controls, but put shell chrome and inspectors in QML where
   opacity, layer effects, and real transitions are predictable.

3. GroupBox is the default composition primitive.
   The audit panels are dominated by `QGroupBox`, field rows, and card panes.
   The artifact says hero region plus inspector plus command row; the app often
   says form inside card inside scroll area. v5 move: each panel gets one
   dominant hero canvas and one translucent inspector layer; repeated framed
   groups become drawers, strips, or inline sections.

4. Typography is still over-mono and over-uppercase.
   The token scale is calibrated, but screenshots show prose, form labels, and
   empty-state explanations rendered like instrument engraving. That makes the
   UI feel technical but not premium. v5 move: reserve mono for quantities,
   identifiers, and tiny labels; body, commands, sidebars, and inspector copy
   use system sans with calmer weight and sentence case.

5. Plot widgets become black holes instead of integrated figures.
   `PLOT_BG` is intentionally fixed dark, which is correct for hot data, but
   pyqtgraph canvases consume entire panels with hard rectangular edges. In
   light theme they feel pasted onto the app. v5 move: leave the plot pixels
   opaque, but wrap them in a QML/QWidget host with a glass header/HUD, soft
   outer material, and no nested inner frames.

## Per-Panel v5 Moves

1. Motor Stage: make the 2D/3D stage view the panel hero, full height on the
   right or center, with a translucent targeting HUD for position, limits, and
   click-to-target; jog and absolute move become a compact bottom command tray.

2. Reference Monitor: make the waveform the hero and float two small metric
   capsules over it: amplitude and stability. Scale/check controls become a
   slim inspector strip, not a form above the plot.

3. Camera: turn the image area into a full-bleed camera well. Put Live, Single,
   Stop, saturation, and exposure in a glass overlay rail; move advanced image
   processing into a right inspector sheet that can collapse.

4. Oscilloscope: treat the trace as the workspace. Channels become a translucent
   side rail with color ticks and roles; measurements are a bottom drawer,
   closed by default, instead of a permanent dense right panel.

5. Laser / Trigger: split "manual laser truth" from "wavegen control" with one
   frosted warning banner pinned at top and one clean waveform-generator command
   sheet below. Metadata should look like a record card, not active controls.

6. Scan Viewer: make the map the hero with an overlaid run HUD for progress,
   ETA, point, and elapsed. Z-focus/live-assist becomes a bottom sheet that
   snaps open, keeping the finished map inspectable.

7. Scan Planner: use a Mac-style source list plus canvas plus inspector. Add
   blocks live in a translucent left palette, the recipe tree owns the center,
   and preflight/readiness sits in a right inspector with the arm envelope.

8. Bias Supply: create a safety-dashboard composition: measured voltage and HV
   state as the hero pair, compliance/current as compact side metrics, and the
   DangerGate envelope as a red-accented tray pinned to the bottom.

9. Calibration: reduce to two procedure cards on one glass sheet: Method and
   Repeatability. The method card should feel like a settings pane; the test
   card gets a compact result strip instead of a paragraph-heavy form.

10. Monitor: put four slow-control tiles in a translucent top strip, history
   plot as the hero, and the channel table as a secondary details drawer.
   Staleness should be per-row and visible without coloring nominal data green.

11. Analysis: use a Finder/Preview pattern: recent runs as a left source list,
   current run preview as the hero, and modes in a compact segmented toolbar.
   Empty state should be "pick a run" with recents, not a blank plot slab.

## Translucency Strategy

Use real blur only where the pixels behind it are stable and cheap: QML shell
rail, tab shelf, status strip, detached-panel title bars, side inspectors, and
modal command palettes. Prefer Qt Quick layers/ShaderEffect or platform blur
experiments there; avoid `QGraphicsBlurEffect` on QWidget trees except for
small cached static backgrounds.

Use fake color-mix for QWidget surfaces: cards, chips, buttons, form wells,
status pills, and compatibility panels. `style.py` already pre-blends tokens
because QSS lacks CSS `color-mix`; extend that discipline into named material
roles (`glassChrome`, `glassInspector`, `glassTray`) instead of ad hoc rgba.

Use no translucency on hot paths: pyqtgraph plot canvases, camera frames, scan
maps, stage plots, waveform drawing, and large scrolling tables. These need
opaque pixels, stable contrast, and predictable repaint cost. Put glass around
them as headers/HUDs/drawers, never over the data plane unless the overlay is
tiny and static.

## Three Mac-App Ideas To Steal

1. Xcode-style workspace chrome: navigator on the left, editor/hero canvas in
   the center, inspector on the right, with each panel deciding which columns
   are present. This would make detachable panels and multi-monitor use feel
   intentional instead of like cloned tabs.

2. Spotlight-grade command palette: state-aware commands, panel switching,
   "open last run", "dry run", "export current plot", and safe hardware actions
   only. It removes toolbar clutter while making expert workflows faster.

3. Preview/Finder Quick Look for runs and devices: spacebar or a small preview
   button opens a translucent summary overlay for the selected run, device, or
   alarm without navigating away from the current panel.
