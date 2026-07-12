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

## 1b. Theme editor round 2 — Kaya, 2026-07-13 (QUEUED, Noah)

Live feedback after using it: "ich will mehr theme presets" + "können wir das
Fenster leicht transparent machen, also dafür auch nen Regler? irgendwie
funkt das opaque teil net so."

**Diagnosis (honest):** the glass slider is NOT weak — it is doing exactly
what it can. QSS has no backdrop blur, so "glass" is a pre-blend of three
surface tokens (chrome/strip/edge) toward `panel`. Moving it changes how
much two greys differ. It can never make the window see-through, which is
what the word promises. The knob Kaya actually wants is a different one.

**Build:**
1. **Window opacity slider** — `QMainWindow.setWindowOpacity(x)`: REAL
   compositor translucency (DWM does it natively on Win11), the whole window
   incl. content. Range **0.80 … 1.00**, default 1.00, step 0.01, persisted
   under `theme/window_opacity`. **Floor is a safety clamp, not taste**: an
   HV-live chip and an abort button must stay legible at every reachable
   setting; do not expose a value that makes the cockpit ghostly. Applies to
   the main window; detached panels inherit it.
2. **Rename the existing knob** so it stops over-promising: "Glass" →
   **"Surface tint"** (or "Material depth"), with a one-line hint in the
   dialog: *"Qt cannot blur behind a window — this tints the chrome
   surfaces. For see-through, use Window opacity."* Honesty over marketing
   (law 8 applies to our own UI copy too).
3. **More built-in presets** (5, all law-safe — safety palette stays locked):
   Cockpit Dark (default) · Graphite · Deep Violet · Lab Light · Paper.
   Token sets already designed and eyeball-checked in
   `artifacts_claude/v5/src/themes.body.html` (the playground's `P` map) —
   port them; do not invent new ones.
4. Tests: opacity clamped to [0.80, 1.00] (a persisted 0.2 from a hand-edited
   QSettings must be clamped, not obeyed); every built-in preset round-trips
   and none of them can touch a locked safety token; renamed slider still
   drives the same pre-blend.

**File conflict note:** touches `gui/style.py`, `gui/theme_editor.py`,
`tct_gui.py` — must NOT run concurrently with any other beat holding those.

## 1c. The black box behind every label — ROOT-CAUSED (Kaya, 2026-07-13)

Kaya: "Siehst du diese schwarze Box um den Text? Das haben wir an ganz vielen
Stellen und ich glaube das zerstört einen großen Teil der Aesthetics."

**Root cause (proven, not guessed)** — `gui/style.py:529`:

```
QMainWindow, QDialog, QWidget { background: {p['bg']}; }
```

A bare `QWidget` type selector. Qt QSS type selectors match SUBCLASSES, and
`QLabel` is a QWidget — so every label gets `background: bg` (#0A0D13, the
near-black canvas). Once a stylesheet sets a background, Qt turns on
`WA_StyledBackground` and the label actually PAINTS it. Invisible on the
canvas itself; a black slab on every card/panel (#121824). Same defect is
inherited by other text widgets (check QCheckBox / QRadioButton).

Measured (offscreen probe, label on a panel-coloured card):

| | pixel behind the text |
|---|---|
| as shipped | `#0a0d13` (canvas) -> box |
| + `QLabel { background: transparent; }` | `#121824` (the card) -> gone |
| StatusChip with the fix | `#192134` -> chips KEEP their background (ID selector wins) |

**Fix, two stages:**
1. **Surgical (do first):** `QLabel, QCheckBox, QRadioButton { background: transparent; }`
   — sweep for every text-ish widget with the same inheritance. Chips, marks
   and pills are unaffected (ID/class selectors are more specific).
2. **Proper (do after, verified with panel captures):** drop `QWidget` from the
   bare background rule entirely; paint only the top-level shells
   (`QMainWindow`, `QDialog`, `QWidget#mainShell`) and let children inherit.
   This is the Qt-textbook fix; it is riskier because some containers may rely
   on the blanket rule — hence captures before/after, not a blind edit.

Guard test: assert no plain QLabel on a Card paints a colour different from
its parent surface (the probe in this entry is directly reusable).

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
