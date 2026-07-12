# Feature requests — Kaya, 2026-07-12 (Feinschliff session)

Status ledger for the feature burst during the v5 design campaign. Design
artifacts live in `artifacts_claude/v5/`; implementation follows the wave
plan after v5 ratification unless marked "in flight".

Terminology (ratified same session): XY map routines are **scan-TCT**, not
edge-TCT. Edge-TCT is a possible future mode — never label current routines
edge-TCT.

## 1. Theme editor — IN FLIGHT (Noah)

Kaya: "theme editor showing me possible themes and making me able to
configure them, like color and fonds" + "make the material also
opaque/glass like? or make it setable."

- In-app: `gui/theme_editor.py` QDialog — presets (Cockpit Dark / Lab Light
  / user presets in QSettings JSON), color swatches for NON-safety tokens,
  sans/mono/hinting/base-size, radius S/M/L, **glass-amount slider**
  parametrizing the chrome/strip/edge pre-blends. Safety palette
  (danger/armed/sim/error) LOCKED — laws 1/2/6, validated on preset load.
- Design twin: interactive artifact `artifacts_claude/v5/themes.html`
  (5 presets, live preview, JSON token export).

## 2. QML shell default — RATIFIED (Kaya): QML default, classic = fallback

Noah W3 beat: flip in `tct_gui._build_central`, classic behind a fallback
flag (+ existing fail-safe notify path), `run.ps1` gets `-Classic`,
retire the visible toolbar path. Dispatch AFTER the theme editor lands
(same files). Guard: `test_qml_shell.py` rail-fit pins.

## 3. Sensor mosaic (image stitching) — DESIGNED (artifact mosaic.html)

Stage raster + camera grab per tile + stitch via px→mm calibration →
high-res sensor image with real mm axes.
- v1: procedure in the Camera panel (pattern: repeatability test) —
  preconditions homed+streaming+px→mm-calibrated, DangerGate on the raster,
  amber motion class, STOP visible. Grid from FOV+overlap; move→settle→grab;
  calibrated placement + linear overlap blend; TIFF/PNG + JSON sidecar
  (positions, exposure, cal id).
- v2: seam refinement via the existing sub-pixel phase correlation.
- Owners: Abel (sequencing) + Paul (camera/motor) + Jonathan (stitch math),
  Mary review mandatory (motion). NOT a free-lane task.

## 4. Analysis 1D slicer — IN FLIGHT (Jonathan)

Draggable linecut across the loaded scan map → profile (value vs mm along
X or Y), ±N-row averaging band, NaN-preserving, CSV export. Pure helper
`analysis/map_slice.py` + pyqtgraph InfiniteLine/LinearRegionItem +
profile plot. It is a scan-TCT linecut (see terminology).

## 5. Planner block: Capture photo — DESIGNED

Camera grab at the current point into HDF5/sidecar (path, position,
exposure). Nominal row class; precondition camera connected. Mosaic
becomes expressible as a planner routine with this block.

## 6. Planner block: Acquire measurements (waveform-discarding) — DESIGNED

Read only scope-computed quantities (amplitude, charge/area, rise, timing)
and discard waveforms — Kaya: scopes support this via SCPI (measurement
subsystem instead of CURVE?).
- Orders-of-magnitude smaller runs; Before-you-run DATA tile shows the
  saving live.
- HDF5: a `measurements` table without the waveform group —
  SCAN_DATA_FORMAT.md extension (Jonathan) BEFORE implementation.
- SCPI: exact command set per scope from the manual —
  `TODO(manual needed)` per safety rule 4 (TBS1052C: MEASUrement subsystem;
  DRS4 eval board: likely host-side computation instead — Paul to verify).

## 7. Scan Sequencer — DESIGNED, ONE OPEN SAFETY QUESTION

Queue of saved routines running unattended (overnight); per-entry
preflight; parks safe between entries.
- **Kaya must rule:** envelope semantics for a sequence —
  (a) ONE combined envelope over the whole queue (max HV, total travel,
  every routine named in the arm text; one hold-3-s for the night), or
  (b) re-arm at every routine boundary (sequencer pauses until confirmed).
  Abel recommends (a) — the same executor re-validation covers it and
  Abort/kill stay one-tap throughout; (b) defeats the unattended purpose.
- UI: sequence list with per-routine state rows (done/running/queued),
  Abort-sequence red-outline; designed in planner.html §Sequencer.
