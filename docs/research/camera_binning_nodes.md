# Camera binning-mode GenICam nodes — BFLY-U3-23S6M (classic Blackfly)

- **Date:** 2026-07-13
- **Author:** Prometheus (researcher)
- **Status:** Resolves the `TODO(manual needed)` in
  `TCT_app/devices/camera_blackfly.py::_set_binning_mode_average` (node names +
  enum spelling). The classic-family *availability* verdict is a strong inference,
  not a directly-read line of the classic manual; final per-unit confirmation
  stays with the existing `TODO(bench)` (SpinView on serial 19112408).
- **Model / version:** FLIR/Teledyne Blackfly **classic** `BFLY-U3-23S6M-C`,
  Sony IMX249, USB3 Vision; Spinnaker SDK / PySpin 3.2.
  **NB: classic Blackfly (BFLY) is a different, older family than Blackfly S
  (BFS).** FLIR documents them separately and their binning feature models
  differ — do not carry BFS behavior over to BFLY.
- **Confidence:** node/enum **spellings = official docs** (GenICam SFNC +
  Spinnaker API); **"Average absent / Sum-only on classic BFLY" = secondary
  source** (inference from FLIR's own family docs + corroboration), pending the
  bench SpinView check.

## Exact question

For the BFLY-U3-23S6M (IMX249, Spinnaker/PySpin 3.2): the exact GenICam node
names and enum-entry spellings for binning-mode control; which SFNC version
introduced `BinningHorizontalMode`/`BinningVerticalMode` + the Sum/Average
entries; whether **this** (classic BFLY) family exposes those nodes or only the
legacy value nodes; and — the key risk — whether Average binning is even
available on classic BFLY, or is it Sum-only in hardware so that "node absent →
skip is the permanent path and display windowing is the real fix."

## TL;DR

- **Node names (both families, GenICam SFNC standard):** mode nodes
  `BinningHorizontalMode`, `BinningVerticalMode`; factor/value nodes
  `BinningHorizontal`, `BinningVertical`.
- **Enum-entry spellings (Spinnaker/PySpin):**
  `BinningVerticalMode_Sum` / `BinningVerticalMode_Average` and
  `BinningHorizontalMode_Sum` / `BinningHorizontalMode_Average`.
  The driver's current `getattr(ps, "BinningVerticalMode_Average")` /
  `"BinningHorizontalMode_Average"` spelling is therefore **correct** for PySpin.
  (GenICam formal enum entries are `Sum` / `Average`; FLIR *prose* calls `Sum`
  "Additive".)
- **On classic BFLY: Average is almost certainly NOT available.** The Sum/Average
  *mode selection* and the ISP-averaging path (`BinningSelector` = All/Sensor/ISP)
  are **Blackfly S features**. Classic BFLY has no ISP and its binning reduction
  is **additive (sum)**. Expect the `BinningVerticalMode`/`BinningHorizontalMode`
  node to be **absent** (or Sum-only) on this unit.
- **Hence the E1 guard (skip a missing node/enum at INFO) is the correct
  PERMANENT behavior** for this camera family — not a temporary workaround. The
  "white frame at binning 2/4" remedy is **display/software-side** (rescale by
  1/n² after summed hardware binning, or software-average downscaling like the
  simulated backend's `_apply_binning`), not a hardware Average mode.

## Findings

**1. GenICam SFNC defines the mode nodes and the Sum/Average entries.**
`BinningHorizontalMode` and `BinningVerticalMode` are standard SFNC features; the
two standardized enum entries are **`Sum`** ("the response from the combined
cells will be added → increased sensitivity") and **`Average`** ("averaged →
increased signal/noise ratio"). They appear in the EMVA SFNC index from at least
**v2.2 (2014-12-17)** through v2.6 (2020-06-25). I could not verify a pre-2.2
"introduced in" version (the EMVA PDF's feature-detail pages did not extract
cleanly via the fetcher, only the index), so the honest statement is
"standard since ≥ v2.2," not a specific first-appearance version.

**2. Spinnaker / PySpin enum-constant spellings (authoritative).**
The Spinnaker C API defines `spinBinningVerticalModeEnums` with constants
`BinningVerticalMode_Sum` and `BinningVerticalMode_Average`
(`spinBinningHorizontalModeEnums` is symmetric), and `spinBinningSelectorEnums`
= `BinningSelector_All | _Sensor | _ISP`. PySpin mirrors these identifiers as
module attributes (`PySpin.BinningVerticalMode_Average`, etc.). This confirms the
driver's spelling exactly.

**3. Sum-vs-Average is a Blackfly S (BFS) capability tied to the ISP.**
FLIR's BFS "Image Format Control" reference exposes `BinningSelector`
(All/Sensor/ISP) and `BinningHorizontalMode`/`BinningVerticalMode` with
Additive/Average, and explicitly states **"some sensors do not support average
binning."** Averaging is performed by the **ISP** (`BinningSelector = ISP`) when
the sensor cannot do it in analog. Binning changes are only allowed while not
streaming.

**4. Classic BFLY is an older doc generation with no ISP binning model.**
FLIR does **not** host the classic BFLY on `softwareservices.flir.com`
(`BFLY-U3-23S6` Image Format Control → **HTTP 404**); classic BFLY is documented
only in the standalone "Blackfly USB3 Technical Reference" (v5.0 / 6.1 / 6.2).
The `BinningSelector`/ISP model is a BFS construct and is absent on classic BFLY.
Historically, classic Point Grey / Blackfly binning was exposed through the
sensor **"Mode" (Format7)**, with "no generalized interface to binning"
(Micro-Manager). Taken together with (3), the classic Blackfly reduction is
additive (sum) and there is no ISP path to offer Average.

**5. Consequence for the observed white frame.**
Classic BFLY 2×2 hardware binning is additive → ~4× counts → pins the
already-bright (saturated laser-spot) pixels white, exactly the bench symptom in
`docs/research/camera_optics_setup.md`. With no hardware Average mode to select,
the mode write is expected to hit an absent/non-writable node and be skipped.
The intensity fix must be software/display-side: rescale after summed binning, or
software-average downscaling (the pattern already present in the simulated
backend's `_apply_binning`).

## Recommendation for the `TODO(manual needed)` marker

**Resolve the spelling part, and rewrite the expectation to "Sum-only on this
family."** The node names (`Binning{Horizontal,Vertical}Mode`) and the PySpin
enum constants (`Binning{Horizontal,Vertical}Mode_Average` / `_Sum`) are now
confirmed from the GenICam SFNC + Spinnaker API — the "confirm the node names and
enum spelling" task is done and the driver's spelling is correct. Replace the
`TODO(manual needed)` line with a one-line comment citing this note stating:
**on classic BFLY (no ISP) Average is not expected — the
`BinningVerticalMode`/`BinningHorizontalMode` node is expected absent/Sum-only,
so the `IsWritable`/absent skip-at-INFO is the permanent path, and the
white-frame fix is a display-side rescale / software-average, not a hardware
mode.** Keep the existing `TODO(bench)` as the final per-unit confirmation
(SpinView node inspection on serial 19112408). (Implementation is Paul's call;
this note does not edit driver code.)

## Sources

- **GenICam SFNC v2.2** (2014-12-17), EMVA — `BinningVerticalMode` /
  `BinningHorizontalMode`; standardized entries `Sum` / `Average`.
  <https://www.emva.org/wp-content/uploads/GenICam_SFNC_2_2.pdf> (accessed
  2026-07-13). *official standard.* (Also listed in the v2.3/v2.5/v2.6 indexes;
  enum descriptions cross-read via search index + FLIR SFNC-derived docs — the
  EMVA PDF's detail pages did not extract cleanly in-tool.)
- **Spinnaker C API** enum reference (JavaCPP-presets mirror auto-generated from
  FLIR's SpinnakerC headers) — `spinBinningVerticalModeEnums`:
  `BinningVerticalMode_Sum`, `BinningVerticalMode_Average`;
  `spinBinningSelectorEnums`: `_All` / `_Sensor` / `_ISP`.
  <http://bytedeco.org/javacpp-presets/spinnaker/apidocs/org/bytedeco/spinnaker/global/Spinnaker_C.spinBinningVerticalModeEnums.html>
  and `...Spinnaker_C.spinBinningSelectorEnums.html` (accessed 2026-07-13).
  *official docs (names generated from Spinnaker headers; third-party host).*
- **FLIR Blackfly S — Image Format Control** (BFS-U3-04S2, BFS-U3-89S6) —
  `BinningSelector` All/Sensor/ISP; `Binning{H,V}Mode` Additive/Average; "some
  sensors do not support average binning"; binning changes only while not
  streaming.
  <https://softwareservices.flir.com/BFS-U3-04S2/latest/Model/public/ImageFormatControl.html>
  ,
  <https://softwareservices.flir.com/BFS-U3-89S6/latest/Model/public/ImageFormatControl.html>
  (accessed 2026-07-13). *official manufacturer docs — Blackfly **S**, not
  classic BFLY.*
- **Classic BFLY absent from the modern doc site:**
  <https://softwareservices.flir.com/BFLY-U3-23S6/latest/Model/public/ImageFormatControl.html>
  → HTTP 404 (accessed 2026-07-13). Classic BFLY is documented only in the
  standalone "Blackfly USB3 Technical Reference" v6.2 (Revised 8/30/2018):
  <https://www.eureca.de/files/pdf/optoelectronics/flir/BFLY-U3-Technical-Reference.pdf>
  (accessed 2026-07-13; the binning section could not be machine-extracted — the
  FLIR PDFs returned only embedded-image metadata via the fetcher). *official
  manual exists but section not machine-readable here → bench/SpinView retained.*
- **Micro-Manager — Point Grey Research** — "Even though some Point Grey cameras
  support binning, there is no generalized interface to binning. Often, you can
  change binning by changing the 'Mode' of the camera."
  <https://micro-manager.org/Point_Grey_Research> (accessed 2026-07-13).
  *secondary source (corroborates classic = Mode/Format7-based, pre-ISP).*
- In-repo prior art: `docs/research/camera_optics_setup.md` (2026-07-10 bench
  note — white-frame-at-binning symptom + Sum-default hypothesis) and
  `TCT_app/devices/camera_blackfly.py` (`set_binning` :475, `_set_binning_mode_average`
  :506, `_apply_binning` :926).

**Bottom line:** spellings confirmed (official docs) — the driver's node/enum
names are right; on classic BFLY-U3-23S6M, Average binning is not expected
(secondary/inference), so the skip-at-INFO guard is the correct *permanent*
behavior and the real fix is display/software intensity handling. Confirm node
presence on serial 19112408 via SpinView per the existing `TODO(bench)`.
