# Council v5 — Jonathan's seat (data-facing panels)

Scope: Oscilloscope, Reference Monitor, Monitor (slow control), Analysis,
Scan Viewer (map/plot aspects). Grounded in `intensity_panel.py`,
`monitor_panel.py`, `analysis_panel.py`, `scan_map_view.py`,
`scope_panel.py`, `SCAN_DATA_FORMAT.md`, `analysis/charge_calibration.py`,
`analysis/cce.py`, `analysis/efield_analysis.py`.

## 1. Per-panel positions

**Oscilloscope.** Ratify Codex move #4 (trace as workspace, translucent
channel side rail) with one correction: the measurements drawer must NOT
default closed — default state follows acquisition state (open while
LIVE/SINGLE running, collapsed when idle/offline). A physicist tuning
alignment watches amplitude+charge trend point-to-point in real time; a
closed-by-default drawer hides exactly the numbers a live run needs.
Design system §7's 4 tiles (Amplitude/Rise/Charge/Drift time) sit as a slim
strip pinned to the plot's glass **header**, never floating over the grid —
tiles must not occlude trace pixels. Cursor/crosshair readout stays an
opaque chip (exact-value reads, not a wash). Fix the audit's rail-overflow
bug with enforced min-width + elide, not shrink-to-clip.

**Reference Monitor.** `intensity_panel.py` already ships design system §7
almost verbatim (2 tiles + 1 chip + waveform hero) — ratify as-is; the
audit's gaps (heavy tile slabs, double GroupBox frame) are Noah's chrome,
not a data-shape problem. Resist scope creep: no third tile. One fix that
IS mine — the Amplitude tile's charge caption prints raw pC
(`f"{charge_pC:.3f} pC"`), which renders `0.004 pC` for a typical sub-pC
signal. Switch to fC display (see §4).

**Monitor (slow control).** Ratify Codex move #10 + design system §7 (4
alarm tiles up top, table demoted, per-row staleness). Reject the current
`"All nominal"` chip firing with zero readings on file (Adam's law-8 flag,
confirmed in `monitor_panel.py`) — gate it on every configured channel
having ≥1 real (non-NaN) reading; otherwise show "No data" (neutral). The
4× "NO READING YET" pattern is **not** noise to collapse like Scan
Viewer's — temperature/humidity/bias/leakage are independent physical
channels that arrive on independent schedules, so per-tile staleness is
honest. Fix is visual (dim slots, not 4 loud slabs), not structural.

**Analysis.** `analysis_panel.py` already implements the Finder/Preview
shape (recent-runs list, run-header bar, stacked map/CCE modes) — ratify as
shipped. The audit's 4 chips (file/dataset/map/export) are facets of ONE
loaded-run state, not independent alarms — collapse to a single status line
in the run-header bar (`run_00042 · 2401 pts · map: dut_charge_pC ·
exported: no`). Map mode reuses `ScanMapView` (viridis/NaN/colorbar) —
correct, no change. CCE mode must surface the calibration record's fit
quality + validity range alongside the depletion-voltage line per the
non-negotiable calibration rule — flagging for verification, not asserting
done (`efield_analysis.estimate_depletion_voltage` return needs a check).

**Scan Viewer.** Audit: "closest to v5 already," and the map/NaN/colorbar
plumbing in `scan_map_view.py` (viridis, NaN-intact grid, freeze-levels,
unit-bound colorbar) is already correct — ratify unchanged. Codex move #6
("overlaid run HUD for progress/ETA/point/elapsed") — **partial reject,
see §1a below.** The 4× "NO RUN YET" repetition here SHOULD collapse to one
empty state (unlike Monitor): progress/ETA/point/charge are facets of one
absent run, not independent channels — audit already notes the icon+text
empty state exists; ratify, don't fragment it. Add one thing Codex missed:
a live current-point charge readout in the HUD cluster so an operator can
catch a dead channel mid-run without switching to the Oscilloscope tab.

### 1a. Rejected Codex move — translucent HUD over the map

Codex move #6 says "float a run HUD over the map." I rule this unsafe as
stated. Viridis is read by exact hue/luminance; any translucency laid over
the *image data pixels* shifts perceived color and breaks charge/CCE
legibility mid-run — this is the one place in the whole app translucency
must not go, even "tiny and static" per the strategy doc's own hot-path
rule (the doc says no translucency on scan maps, then move #6 contradicts
it). Safe placement: an opaque chip cluster pinned in the map's non-data
margin (glass header strip / corner letterbox outside the image bounds),
never a semi-transparent layer spanning the plotted grid.

## 2. Empty/offline plot states

Rule of thumb: **the axis frame survives only when the axis represents a
real instrument/config quantity independent of the missing data; it
disappears when the axis range is itself derived from that missing data.**

- **Scope / Reference Monitor** (time/voltage axes = the configured
  timebase and V/div, real whether or not a trace exists): keep the axis
  frame, units, and range at the current scale-dial setting; drop the
  grid, drop the trace; dim canvas to ~40%; center caption "No live trace
  — <reason: not connected / awaiting trigger>". This replaces
  pyqtgraph's default 0–1 autorange fake grid (the literal cause of
  Adam's "0.1–0.9 axes" observation — it's PlotWidget's unset-range
  default, not deliberate).
- **Monitor history** (x = rolling wall-clock window, real and
  channel-independent; y = channel-dependent, not yet fixed): keep the
  time axis, no y-range fabricated; dim + "Waiting for first reading."
  No gridlines beyond the time ticks until a channel is selected and has
  data.
- **Scan Viewer / Analysis map** (x_mm/y_mm range comes FROM the scan
  plan/run — nothing to show before one exists): no axis frame at all;
  icon + "Configure in the Scan Planner" / "Pick a run," matching the
  already-shipped Scan Viewer pattern. Do not invent a placeholder extent.

## 3. Instrument well requirements

- Bezel: hairline + inner shadow per existing tokens, radius matching the
  panel's own radius law (8/12/16) — the well is a nested surface, not a
  separate object.
- Text/ticks resolve against the **fixed-dark** plot tokens
  (`PLOT_BG`/`PLOT_FG`) always, never against light-theme QSS — extend the
  pattern `intensity_panel.py` already documents (no `refresh_theme`
  needed because the canvas is theme-invariant) to every plot panel; this
  is the direct fix for the light-theme "washed out plot titles."
- Colorbar: vertical strip inside the well, own hairline separator from
  the image, unit label bound to the selected quantity — `scan_map_view`
  already does this; make it the canonical pattern for any future 2-D
  plot (e.g. a CCE map).
- HUD chips that must sit on top of a viridis image (point-readout,
  current-position marker) need an **opaque** backing plate, fixed
  dark/light chip tokens — never "blend with background," since viridis
  spans yellow to purple and a translucent chip has no reliable contrast
  floor. Ties directly to the §1a rejection.

## 4. Numbers — metric tiles per panel

Charge in this app is genuinely sub-pC (`q_one_mip_pC(300) ≈ 3.6 fC =
0.0036 pC`) — tiles showing raw pC at 3 decimals read as near-zero. Display
charge tiles in **fC** (×1000, 2 decimals) everywhere a per-point/per-shot
value is shown; keep pC as the stored/HDF5 unit (`SCAN_DATA_FORMAT.md`
already pins this) and only convert at display time. When a calibration is
active, label which value is shown (`dut_charge_cal` vs raw) — law 7.

| Panel | Tile | Unit / precision |
|---|---|---|
| Scope | Amplitude | mV, 2 dp |
| Scope | Rise time | ns, 1 dp |
| Scope | Charge | fC, 2 dp (label raw vs calibrated) |
| Scope | Drift time | ns, 1 dp |
| Ref Monitor | Amplitude | mV, 2 dp (caption: charge fC, 2 dp — fix the `.3f pC` bug) |
| Ref Monitor | Stability | % RMS, 2 dp |
| Monitor | Temperature | °C, 1 dp |
| Monitor | Humidity | %RH, 1 dp |
| Monitor | Bias | V, 1 dp (readback, polarity from sign) |
| Monitor | Leakage | native config unit (nA/µA — never hardcode, read from channel key) |
| Analysis (CCE) | Q_ref, V_depletion | fC / V, 1 dp; fit quality + validity range shown alongside |
| Scan Viewer HUD | Progress · ETA · current-point charge | n/N · mm:ss · fC, 2 dp |

## Summary

Data-facing code is further along than the screenshots suggest —
`scan_map_view.py` and `intensity_panel.py` already ship most of the §4
data-ink law and the §7 recipe. Remaining work is: kill fake pyqtgraph
default axes with a designed empty state per plot type, fix the Monitor
"all nominal with no data" lie, switch charge tiles to fC, and keep any
run-HUD strictly off the map's data pixels.
