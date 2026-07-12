# Codex review - 2026-07-12

Scope: static `git show` / source review of `5730644`, `9b91ed1`,
`c12a6a1`, and `7663d74` on `design/cockpit-v5`. Per D5, no pytest was run.

## Findings ranked by risk

1. SAFETY - `7663d74`: z-focus and voltage scans can run without arming the
   shared run-control UI. `start_scan` emits `scan_started` only after a
   successful controller start (`TCT_app/gui/scan_coordinator.py:254-262`), and
   plan paths do the same (`TCT_app/gui/scan_coordinator.py:341-348`,
   `TCT_app/gui/scan_coordinator.py:370-374`). The fixed z-focus/voltage slots
   only emit a status string after success (`TCT_app/gui/scan_coordinator.py:274-287`,
   `TCT_app/gui/scan_coordinator.py:297-306`). But `TCTMainWindow` wires
   `scan_started` into the Scan Viewer and run-state facade
   (`TCT_app/tct_gui.py:476-489`), and `ScanViewerPanel.on_scan_started`
   enables Pause/Abort (`TCT_app/gui/scan_viewer_panel.py:313-328`). Expected:
   successful z-focus and voltage starts should emit `scan_started` or an
   equivalent run-active signal. Actual: a live motion/HV run can leave the
   central Abort/Pause controls disabled and the run facade idle.

2. SAFETY - `5730644`: the fail-closed controller guard is not atomic outside
   the single-threaded GUI assumption. `_refuse_if_active()` checks state and
   `_thread.is_alive()` (`TCT_app/controller/scan_controller.py:398-414`), then
   each start path transitions/spawns later (`TCT_app/controller/scan_controller.py:416-427`,
   `TCT_app/controller/scan_controller.py:582-594`,
   `TCT_app/controller/scan_controller.py:601-614`). `StateMachine.can()` and
   `transition()` are plain reads/writes with no lock
   (`TCT_app/controller/state_machine.py:50-58`). Expected: the public
   controller start API should serialize `can/refuse/transition/_thread =`.
   Actual: two non-GUI callers racing the controller can both observe no live
   thread before either stores its worker. The GUI path likely avoids this by
   thread affinity, but the controller contract itself does not.

3. DATA/CORRECTNESS - `9b91ed1`: `mm_to_index()` has no non-finite guard, so a
   NaN cut position silently becomes an edge slice. The implementation is
   `np.argmin(np.abs(axis - float(position_mm)))`
   (`TCT_app/analysis/map_slice.py:87-90`). Counter-example: with
   `axis_values=[0.0, 1.0, 2.0]` and `position_mm=float("nan")`, expected is
   `ValueError` or "keep previous cut" because there is no nearest finite
   coordinate; actual NumPy input is `[nan, nan, nan]`, so `argmin` returns
   index `0` and `slice_grid_at_mm()` slices the first row/column. The GUI spin
   box normally prevents this, but the analysis helper is public and HDF5/map
   inputs are not validated for finite coordinates here.

4. CORRECTNESS - `c12a6a1`: loading a settings profile with missing theme keys
   does not fully reset module-global customization. `load_theme_customization()`
   leaves `_glass_amount` unchanged when `theme/glass_amount` is absent
   (`TCT_app/gui/style.py:1684-1689`) and defaults radius loading to the current
   `_radius_scale`, not `"m"` (`TCT_app/gui/style.py:1708`). Expected: loading a
   profile without those keys recreates shipped defaults. Actual: in-process
   profile switches/tests can inherit a previous profile's glass/radius. Normal
   cold start masks this because module globals start at defaults.

## Locked safety tokens

Verdict: no direct override path reaches the locked safety tokens
`danger/armed/sim/error`, including the `crit/warn` aliases.

- `SAFETY_TOKENS` locks `danger`, `armed`, `sim`, `error`, `crit`, and `warn`
  (`TCT_app/gui/style.py:1411-1417`).
- The editable fan-out is only `accent`, `canvas`, `panel`, `well`, `text`,
  `muted`, and `hairline` (`TCT_app/gui/style.py:1426-1435`).
- `apply_theme_overrides()` raises on any safety key
  (`TCT_app/gui/style.py:1532-1536`).
- `sanitize_overrides()` keeps only editable fan-out keys
  (`TCT_app/gui/style.py:1552-1562`), and both QSettings load and preset load
  pass through it (`TCT_app/gui/style.py:1690-1696`,
  `TCT_app/gui/theme_editor.py:82-92`, `TCT_app/gui/theme_editor.py:441-446`).
- Typography/radius helpers only touch font/radius globals
  (`TCT_app/gui/style.py:1570-1639`).
- Glass recompute writes only `chrome`, `strip`, `edge`, and `edge_shade`
  from surface/hairline tokens (`TCT_app/gui/style.py:1489-1498`).

Residual design risk: the editor can still set editable `accent` to red/green,
or set `text` near `panel`, because only hex shape is validated
(`TCT_app/gui/style.py:1537-1543`). That does not mutate locked safety tokens,
but it can weaken the visual hierarchy around them.

## `glass_amount = 0`

At `g=0`, `_glass()` returns the background token unchanged, so `chrome=panel`,
`strip=panel`, and both machined edge tokens collapse to `hairline`
(`TCT_app/gui/style.py:1489-1498`). Default active text remains readable on the
collapsed surfaces: light uses `text=#131A28` / `muted=#525D72` on
`panel=#FFFFFF`; dark uses `text=#E9EDF5` / `muted=#98A1B5` on
`panel=#121824` (`TCT_app/gui/style.py:317-340`,
`TCT_app/gui/style.py:402-415`). `faint` disabled/stale ink is intentionally
below body-text contrast in places, but that is unchanged by glass.

State distinction does not collapse from `g=0`: `good/warn/crit/sim`,
`danger/armed`, and danger buttons keep their original tokens
(`TCT_app/gui/style.py:317-325`, `TCT_app/gui/style.py:402-407`,
`TCT_app/gui/style.py:919-929`). What does collapse is material hierarchy:
chrome/strip are no longer visually different from panel except for borders.

## Map-slice falsification

Concrete counter-example: `slice_grid_at_mm(grid, [0, 1, 2], [0, 1, 2],
"x", float("nan"), 0)` reaches `mm_to_index(y_mm, nan)` and returns index `0`
instead of rejecting the non-finite position (`TCT_app/analysis/map_slice.py:182-198`,
`TCT_app/analysis/map_slice.py:87-90`). Expected: refuse or preserve the last
valid cut; actual: first-column slice with no warning.
