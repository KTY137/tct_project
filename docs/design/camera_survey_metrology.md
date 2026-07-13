# Camera Survey (mosaic) + Stage Metrology — design note

- **Date:** 2026-07-10
- **Author:** Prometheus (researcher / first-officer), design-first stress test
- **Status:** DESIGN — for Adam/Kaya ratification, then Jonathan builds the analysis
  parts / Abel the routine (acquisition + motion) parts / Noah the views. No app code touched.
- **Question:** Add two user-requested camera features — **(A)** an XY **survey scan**
  that stitches per-point frames into one large surface image by *deterministic*
  placement (stage coords × mm-per-pixel, no feature matching), and **(B)** a
  camera-based **stage repeatability/metrology** test (A↔B↔A returns, sub-pixel
  registration → repeatability/backlash/drift in µm) — without inventing hardware
  commands, without a new heavy dependency, and honest about failure modes.
- **Confidence:** design grounded in repo file:line evidence (primary for this
  codebase). Camera specs = FLIR/Edmund datasheet (secondary, web-aggregated —
  exact-model PDF did not extract). Sub-pixel precision = literature (secondary).

Both features touch `SCAN_DATA_FORMAT.md` (Feature A) and stage-motion safety
(Feature B) — hence design-before-build. **Feature B is already ~70% built** in
`controller/repeatability.py` (see §B.0); this note is mostly about closing its gaps.

---

## 0. Grounding — what exists today (cited)

- **A camera frame is already grabbed per scan point.** `_acquire_core` calls
  `dev.camera.get_frame()` in a bare `try/except` that yields `None` on failure
  (`controller/scan_controller.py:1293-1298`) and stashes it on
  `ScanResult.camera_frame` (`:142`). The plan executor's `AcquireStep` funnels
  into the *same* `_acquire_core` (`:963-968`), which **unconditionally turns the
  laser on and reads the scope** (`:1300-1314`) — there is **no camera-only
  acquire path today**.
- **The writer stores frames at `/camera/frames`** `(N,H,W)`, gzip, chunk
  `(1,H,W)` (one full frame per chunk), gated on
  `save_options.camera_frame AND result.camera_frame is not None`
  (`data/hdf5_writer.py:107-108,143-152`; append helper `:168-187`). Default is
  **off** (`data/save_options.py:22`).
- **Two silent-skip gaps (critical for A):** a point whose grab failed
  (`camera_frame is None`) is **not appended** (`hdf5_writer.py:107`), and a frame
  whose shape ≠ the first frame's is **silently dropped** (`:150-151`). Either makes
  `frames` **shorter than `points/x_mm` with no index map** — the same honesty gap
  the waveform work found (`docs/design/save_policy.md` §0/§2). Deterministic
  stitching needs `frames[i] ↔ point[i]`; today that alignment can silently break.
- **Sub-pixel centroid already exists — device-side, whole-frame.**
  `_fill_beam_stats` computes a first-moment centroid + 2nd-central-moment σ over
  the **entire frame** (`devices/camera_blackfly.py:787-818`); the panel only
  displays `meta.centroid_x/y` (`gui/camera_panel.py:542-545`). Whole-frame moments
  are biased by the vignette/background (see §D) — fine for a bright spot on black,
  unreliable as a metrology reference.
- **Simulated camera:** deterministic **640×480** (not 1920×1200) drifting Gaussian
  with Poisson noise, Mono8/Mono16 (`camera_blackfly.py:824-857`). The beam **drifts
  on its own clock** (`cx = w/2 + 20·sin(0.31·t)`, `:829-830`) — a metrology sim must
  inject a *controllable* shift, not read the free-running sim (see §D).
- **The Planner is the only surface that starts raster/plan scans**
  (`gui/scan_viewer_panel.py:5-11`). Plan vocabulary is a **frozen, fail-closed**
  enum: axes `{STAGE_X,STAGE_Y,STAGE_Z,BIAS_V}`, actions
  `{ACQUIRE_WAVEFORM,SAVE_POINT,WAIT,MANUAL_PAUSE,READ_SLOW_CONTROL}`
  (`controller/scan_plan.py:37-51`) → compiler steps `MoveStep/BiasStep/AcquireStep/…`
  (`controller/plan_compiler.py:48-111`). **No camera-only action exists.**
- **Motion is danger-gated.** The executor asks a `DangerGate.confirm(DangerAction)`
  — `kind ∈ {"move","hv_ramp","scan_start"}` (`controller/danger_gate.py:23-47`) —
  **once per run** for stage motion (`scan_controller.py:930-937`). Any new routine
  must ride this same path (rule 2).
- **Deterministic-placement analog already in-repo:** `points_to_grid` bins
  scattered `(x,y,value)` onto a regular grid and **counts `n_missing`/`n_nan_values`
  separately** (`analysis/scan_grid.py:101-188`). Feature A is the *image* analog:
  tile pixel offset = `(stage − origin) · px_per_mm`.

**Camera sensor (verified today):** BFLY-U3-23S6M-C = Sony **IMX249**, **global
shutter** progressive CMOS, 1920×1200, **5.86 µm** square pixels, 1/1.2", C-mount,
**10/12-bit ADC** (Mono16 = 12-bit zero-padded, matching `camera_blackfly.py:5`).
Object-plane sampling at magnification `M` = `5.86/M` µm/px ⇒ `px_per_mm ≈ 170.6·M`.

---

## A. Feature A — Survey scan (mosaic stitching)

### A.1 Acquisition path — a camera-only "survey" acquire
`_acquire_core` always fires the laser + scope (`scan_controller.py:1300-1314`), so a
survey cannot reuse `ACQUIRE_WAVEFORM` as-is. Two options (**ratify §F-1**):
- **(a) New `ACQUIRE_CAMERA` action + `AcquireCameraStep`** that grabs a frame and
  skips laser/scope. Cleanest and matches the frozen-vocabulary ethos
  (`scan_plan.py:14-16,45-51`); touches the enum + compiler + executor + validator
  (**Abel**). *Recommended.*
- **(b) A `camera_only: bool` param** on `ACQUIRE_WAVEFORM` that `_acquire_core`
  honours (skip laser/scope, still grab). Smaller, but overloads one action.

Either way the survey is a **Planner preset**: `LoopBlock(STAGE_X) → LoopBlock(STAGE_Y)
→ ACQUIRE_CAMERA → SAVE_POINT`, `snake=True`, ROI-cropped, Mono8. It inherits the
per-run motion confirm (`scan_controller.py:930-937`) for free — **safe by
construction, no bespoke gate.** This is the acquisition-level extension of the
save-policy theme (`docs/design/save_policy.md` T4.5): that note lets you *store*
fewer waveforms; a survey run *acquires none at all* (laser off) — a distinct new mode.

### A.2 Stitcher — placement, overlap, blending
Deterministic placement (no feature matching): each tile's top-left pixel =
`round((stage − origin) · A)` where `A` is the **stage→pixel affine** (§C), not a
scalar (the camera need not be axis-aligned to the stage). Then:
- **Vignette is the real enemy, not seams.** The relay image circle < sensor ⇒ dark
  corners. Edge-to-edge tiles show a *grid of dark rings*. Fix, in order:
  1. **Flat-field correct** each tile: `tile / flat`, where `flat` = a normalised
     bright-uniform reference (or a median stack of many survey frames). Removes the
     multiplicative vignette so even zero-overlap tiles blend.
  2. **Modest overlap (20–40%) + radial feather** blend: weight each pixel by a
     cosine/ distance-from-tile-centre window, which *also* down-weights the
     vignetted rim. Overlap is set by choosing `step_mm` so the *valid* (in-circle)
     tile width exceeds the step.
- **v1 recommendation:** flat-field + ~25% overlap + radial feather. Mask everything
  outside the fitted image circle to NaN before placement (so it never contaminates
  a blend).

### A.3 Where the stitcher lives
- **Math → `analysis/survey_stitch.py`** (pure numpy; Jonathan's seat — it also
  touches the format). Signature mirrors `points_to_grid`:
  `stitch(x_mm, y_mm, frames, affine, *, flat=None, feather=True) -> Mosaic`.
- **View → offline.** `AnalysisPanel._load_h5` reads only `points`+`analysis` and has
  **no image reader** (`gui/analysis_panel.py:256-266`; `save_policy.md` §0). Add a
  new **"Survey" view** in AnalysisPanel (or a dedicated page) that calls
  `survey_stitch` — Noah wires, Jonathan supplies math. **Not** the live Scan Viewer
  (that is monitor-only, `scan_viewer_panel.py:5-11`). v1 is **offline-only** (no live
  mosaic).

### A.4 HDF5 impact — reuse `/camera/frames`, add an index map + calibration attrs
Do **not** invent a separate survey layout — reuse `/camera/frames`, but close the
alignment gaps (mirror `save_policy.md` §2 honesty discipline):

| Addition | Type | Why |
|---|---|---|
| `/camera/frame_point_index` | int `(M,)` | maps stored frame row → its point index (M ≤ N). The honest answer to the two silent-skip gaps. Reader gathers by index. |
| `/camera@px_per_mm` / `@affine` | attrs | placement calibration (§C) travels with the data — mosaic is reconstructable offline. |
| `/camera@roi_offset_xy` / `@pixel_format` | attrs | absolute sensor origin of the crop + dtype. |
| `/camera@n_frames_omitted_by_error` | int | count the shape-mismatch / grab-fail drops instead of hiding them. |

`SCAN_DATA_FORMAT.md` gets a "Camera / survey" subsection (Jonathan authors the
contract; Kiroku/Samantha land the prose). **Format-contract change ⇒ ratify names (§F-2).**

### A.5 Memory / size budget — ROI-crop is mandatory at scale
Full frame Mono8 = 1920·1200 = **2.30 MB**/tile (Mono16 = 4.61 MB). gzip per-chunk
(one whole frame) is CPU-bound and runs *on the scan loop* — tens of ms for a
textured 2.3 MB frame, and it compresses a surface poorly (~1.2–1.5×).

| Grid | Full-frame Mono8 (uncompressed) | ROI 500×500 Mono8 |
|---|---|---|
| 20×20 (400) | ~0.9 GB | ~95 MB |
| 50×50 (2500) | ~5.8 GB | ~0.6 GB |

**Recommend: survey uses the queued HW-ROI crop (to the image circle, e.g. 500×500),
Mono8, gzip.** Full-frame surveys past ~20×20 are the real "gzip chokes / disk
blows up" risk; ROI removes it and also drops the vignette rim. (Note the queued
ROI feature is a **prerequisite** for a usable survey — §G.)

---

## B. Feature B — camera-based stage repeatability / metrology

### B.0 What already exists (and its gaps)
`controller/repeatability.py` already implements the core:
- **`cross_correlation_shift(ref,img)`** — windowed (Hann) FFT **phase correlation**
  with **parabolic** sub-pixel peak, phase-only normalisation, wrap-around handling
  (`repeatability.py:39-102`). **numpy-only, no scikit-image** (`:23`).
- **`RepeatabilityTester.run(n, approach_mm, …)`** — A→away→back→A cycles, direction
  cycling `+X,+Y,−X,−Y`, `RepeatabilityResult` with std / peak-to-peak / radial-std
  in px and µm (`:170-248`), and **`calibrate()`** — one known move → px/mm (`:190-213`).

**Gaps to close (this is the actual Feature-B work):**
1. **Bypasses the danger gate** — `run()` calls `move_relative/move_to` **directly**
   (`repeatability.py:238-239`), no `DangerGate.confirm`. Must route through the gate
   (one `DangerAction(kind="move")` per test, like `scan_controller.py:930-937`)
   **before it ever drives real hardware.** *(BLOCKER-class safety gap.)*
2. **1 frame per stop** (`:240`) — conflates stage error with vibration. Add
   **N frames/stop + averaging** (vibration ↓ as 1/√N).
3. **Direction-pooled scatter** (`:242`) hides backlash — must **group by approach
   direction** and report the between-direction mean offset as backlash.
4. **`calibrate()` is a single move**, not a staircase with a fit + residuals (§C).
5. **Whole-frame correlation** — with a static vignette, the bright rim correlates at
   zero shift and **biases the peak toward (0,0)** (under-reports motion). Must window
   to a **textured DUT ROI**, excluding the vignette (§D).
6. **No test exists** (`tests/test_repeatability*` absent) — the engine ships
   unverified; a sim test is part of the build (§E).

### B.1 Registration algorithm + expected precision
Keep the numpy/scipy-only phase-correlation (no new dependency; scikit-image is
**not** in `TCT_app/requirements.txt` and the module deliberately avoids it,
`repeatability.py:23`). Precision:
- **Parabolic peak (current):** typically **~0.05–0.1 px**, with a known
  **peak/pixel-locking** systematic bias toward integer pixels (Foroosh 2002; aliased-
  imagery analyses). Good enough for a scatter *metric*, weak for absolute sub-µm.
- **Upgrade path (metrology-grade):** **upsampled matrix-multiply DFT**
  (Guizar-Sicairos 2008) refines the peak to **~0.01 px** (0.001 px at upsample 100).
  This is exactly what `skimage.registration.phase_cross_correlation` does — but it is
  **~40 lines of numpy/scipy** (FFT for the coarse peak, matrix-DFT upsampling in a
  small neighbourhood), so we get metrology precision **without** adding scikit-image.
- In µm: `0.05 px → 5.86·0.05/M µm` ⇒ ~0.29 µm at M=1, ~0.06 µm at M=5. **Precision is
  meaningless until `px_per_mm` is measured** — hence §C is the shared foundation.

### B.2 What it can / cannot attribute (the honest part)
The camera measures the **relative DUT↔camera image shift** after a commanded return.
That convolves: stage positioning error + tower/optics vibration + mount/thermal
creep + camera/registration noise. Separation protocol:

| To isolate | Protocol |
|---|---|
| **Registration + vibration noise floor** | N frames at **one stop, no move** → this scatter is the pure floor; subtract in quadrature from the move scatter. |
| **Vibration vs stage** | Compare single-frame vs N-frame-averaged scatter (averaging kills random vibration ∝ 1/√N; residual = stage + creep). |
| **Backlash** | Group by approach direction; the mean offset between "+approach" and "−approach" families **is** the backlash. |
| **Drift / creep** | Plot shift vs cycle index / wall-clock; a monotonic trend = thermal/mechanical creep, distinct from random repeatability. |

**Cannot** separate *stage-frame* vibration from *optics-tower* vibration — both move
the image identically. Doing so needs a **second reference fiducial** rigidly tied to
one body. State this limit in the report; do not imply the number is "the stage".

### B.3 Where it lives + safety
- **A dedicated "Stage Metrology" tool page**, reusing `repeatability.py`, **not** a
  Planner recipe. The plan vocabulary (`scan_plan.py:37-51`) has no return-to-target
  or register primitive, and plans *save points*; forcing A↔B↔A in there is awkward.
- **Safety = normal danger-gated motion.** Route all moves through the same
  `DangerGate.confirm(DangerAction(kind="move", …))` (`danger_gate.py:23-47`) as the
  executor. One confirm per test run (matching `scan_controller.py:930-937`). This is
  the fix for gap B.0-1.

---

## C. Shared foundation — stage→camera **affine** calibration (build first)
Both features need to convert commanded mm → sensor px. A **scalar px/mm is wrong** if
the camera axes are rotated/sheared vs the stage axes (they generally are). Measure a
**2-D affine** `A` (scale_x, scale_y, rotation, ±shear):
- **Commanded staircase:** step the stage in K equal increments across the ROI on
  each axis, **both directions**; register each frame vs the reference
  (`cross_correlation_shift`); **fit** `pixel = A·mm + b`. Extends `calibrate()`
  (`repeatability.py:190-213`) from one move to a fit.
- **Fit by-products = the metrology report:** slope = `px_per_mm` per axis; **residuals
  = linearity error**; **forward−return offset at each commanded position = backlash**.
- **Math → `analysis/` (pure, unit-testable); motion → controller (danger-gated).**
- Output feeds A (`@affine` placement, §A.4) and B (µm conversion). **Build once, first.**

---

## D. Stress-test — silent failure modes, format impact, sim vs bench

**Silent failure modes (both):**
- **[A, TOP] frame↔point misalignment** from the two silent skips
  (`hdf5_writer.py:107,150-151`) → tiles placed at wrong coords → a *plausible-looking
  but wrong* mosaic, no error. Closed by `frame_point_index` (§A.4).
- **[A] serpentine backlash shear** — deterministic placement uses *commanded* coords;
  stage backlash offsets alternate `snake` rows, appearing as seam misregistration.
  Deterministic-only v1 accepts this; §C quantifies it so the user knows the seam budget.
- **[A] camera rotation** vs stage → a scalar px/mm shears the whole mosaic. Closed by
  the affine (§C). **Do not ship scalar-only placement.**
- **[A] vignette poisoning blends / centroids** → mask to the fitted image circle first.
- **[B] static vignette pins the correlation to (0,0)** (§B.0-5) → window to a textured
  DUT ROI.
- **[B] peak-locking** of parabolic sub-pixel biases small shifts → upsampled DFT (§B.1).
- **[B] wrap-around aliasing** if a move exceeds ±½-frame — already warned in
  `calibrate()` (`repeatability.py:202-209`); keep staircase steps small.
- **[B] featureless DUT** → no correlation peak → garbage. Needs texture / a printed
  fiducial (the module already assumes "µm line strips / calibration bar",
  `repeatability.py:6-9`).
- **[B] thermal creep** mis-read as poor repeatability → the drift-vs-time plot (§B.2).

**Sim-testable at home (simulated devices, no hardware):** the stitch placement math
(feed synthetic tiles at known offsets, assert reconstruction); the affine fit +
residual math; the `frame_point_index` writer change + honesty counts; the survey
Planner preset *compiles*; the danger-gate wiring (simulated motor+camera). **Caveat:**
the sim camera is **640×480 and self-drifts** (`camera_blackfly.py:824,829-830`) — a
metrology sim must use a **mock camera that shifts by a commanded amount**, else it
measures the sim's own drift. **Bench-only:** true `px_per_mm`/affine/`M`, the relay
focal lengths, real vignette/image-circle, flat-field reference, whether the DUT has
enough texture, real repeatability/backlash/vibration, and the HW-ROI landing.

---

## E. Recommended build order (small increments; owner)

**Shared first:**
1. **C — affine calibration math** (`analysis/`, pure, unit-tested on synthetic shifts) — **Jonathan**.

**Feature A:**
2. `analysis/survey_stitch.py` — deterministic placement + flat-field + radial feather;
   tested on synthetic tiles with known offsets — **Jonathan**.
3. HDF5 honesty: `/camera/frame_point_index` + `@affine/@px_per_mm/@roi_offset/@pixel_format`
   + close the two silent skips with a counter; `SCAN_DATA_FORMAT.md` — **Jonathan** (+Kiroku/Samantha prose).
4. Camera-only acquire (`ACQUIRE_CAMERA` step, §A.1) + a "Survey" Planner preset,
   danger-gated via existing move confirm — **Abel** (Noah wires the preset form).
5. Offline "Survey" view in AnalysisPanel calling `survey_stitch` — **Noah** (math from Jonathan).

**Feature B:**
6. Route `RepeatabilityTester` motion through `DangerGate`; add N-frames/stop averaging,
   per-direction grouping, and a no-move noise-floor stop; add the missing sim test — **Abel**.
7. Optional upsampled-DFT refinement in `cross_correlation_shift` (numpy/scipy only) — **Jonathan**.
8. "Stage Metrology" tool page (calibrate staircase + repeatability run + px/µm report),
   danger-gated — **Noah** (engine from Abel/Jonathan).

### Explicitly OUT of scope for v1
- Feature-matching / SIFT / optical-flow / phase-only *global* registration stitching
  (deterministic placement only).
- **Live/online** mosaic during the scan (offline reconstruction only).
- Z / focus survey, auto-focus (XY only).
- Full 6-DOF stage error mapping or interferometer-grade metrology.
- Attributing tower-vs-stage vibration without a second fiducial (§B.2).
- Adding **scikit-image / OpenCV**, or bumping numpy ≥2 (PySpin ABI pin).
- Photometric / absolute-intensity calibration of the mosaic.
- Replacing the device-side centroid (`camera_blackfly.py:787-818`).

---

## Top decisions Adam/Kaya must ratify
1. **Camera-only acquisition mechanism:** new `ACQUIRE_CAMERA` action/step (clean,
   touches the frozen vocabulary) **vs** a `camera_only` flag on `ACQUIRE_WAVEFORM`
   (smaller, overloads it). *Recommend the new action.*
2. **HDF5 for A = reuse `/camera/frames` + add `frame_point_index` + calibration attrs
   + close the two silent skips with a counter.** This is a `SCAN_DATA_FORMAT.md`
   contract change — ratify the dataset/attr names now (they become the contract).
3. **Feature B = dedicated danger-gated tool page** (not a Planner recipe), reusing
   `repeatability.py`, **with its motion re-routed through `DangerGate`** — confirm the
   current direct-move bypass (`repeatability.py:238-239`) is fixed before real hardware.
4. **Stage→camera calibration is a 2-D affine** (scale + rotation + optional shear),
   not a scalar px/mm — the shared foundation of A and B. Confirm we invest here.
5. **Registration precision target:** stay numpy/scipy-only; accept parabolic
   (~0.05–0.1 px) for v1 **or** add the upsampled-DFT refinement (~0.01 px) now. No
   scikit-image either way.

---

## Bench-measurement prerequisites (for Kiroku to harvest into BENCH_CHECKLIST.md)
1. **Read the two relay-lens focal lengths off the cage rings** (the two cage-ring
   relay lenses in the coaxial column). Needed to compute nominal magnification `M`
   and to sanity-check the measured `px_per_mm` (`≈ 170.6·M`).
2. **Once the HW-ROI crop feature lands, run the pixel-scale/affine staircase
   calibration once** (both stage axes, both directions) on a textured target to
   obtain `px_per_mm`, camera rotation, linearity residuals, and backlash — the shared
   foundation for both the survey mosaic (placement) and the metrology test (µm).

---

## Sources
- FLIR Blackfly BFLY-U3-23S6M-C (Sony IMX249, global shutter, 5.86 µm, 1920×1200,
  1/1.2", 10/12-bit) — [Edmund Optics product page](https://www.edmundoptics.com/p/bfly-u3-23s6m-c-usb-30-blackfly-monochrome-camera/3129),
  [FLIR sensor spec page](https://softwareservices.flir.com/BFS-U3-23S6/latest/Model/spec.html).
- Guizar-Sicairos, Thurman & Fienup, "Efficient subpixel image registration
  algorithms," Opt. Lett. 33, 156 (2008) — upsampled matrix-DFT phase correlation,
  as implemented by [skimage.registration.phase_cross_correlation](https://scikit-image.org/docs/stable/auto_examples/registration/plot_register_translation.html).
- Foroosh, Zerubia & Berthod, "Extension of phase correlation to subpixel
  registration," IEEE TIP 11(3), 2002 — parabolic sub-pixel + peak/pixel-locking bias
  ([overview](https://www.researchgate.net/publication/5606817_Extension_of_phase_correlation_to_subpixel_registration)).
- Repo (primary for this codebase): cited inline as `path:line`.
</content>
</invoke>
