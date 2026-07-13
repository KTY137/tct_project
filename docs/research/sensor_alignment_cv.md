---
topic: Sensor-orientation ("bonding-machine style") alignment on a stitched camera mosaic
date: 2026-07-13
author: Prometheus (researcher)
status: complete — gates implementation beat E7x
question: >
  Pin an OpenCV wheel compatible with our cp310 / numpy<2 stack that has the
  modern cv2.aruco API; recommend an ArUco fiducial + a rotation-robust
  detection/pose ladder to recover a sensor origin + rotation to <0.05 deg.
confidence: mixed — pin & ArUco API = official docs; marker/lighting sizing = secondary
---

## TL;DR

- **Pin:** `opencv-python-headless==4.9.0.80` (OpenCV 4.9.0). Ships a single
  `cp37-abi3-win_amd64.whl` that runs on CPython 3.10; wheel metadata is
  `numpy>=1.21.2` (no upper cap, no forced numpy 2) and it is **built against
  numpy 1.x** — the last release before opencv shipped numpy-2-built wheels, so
  it carries **zero numpy-2 ABI risk** against our pinned numpy 1.26.x. It has
  the modern `cv2.aruco.ArucoDetector` API and `cv2.aruco` lives in **base**
  opencv (moved to `objdetect` in 4.7) — we do **not** need opencv-contrib.
- **Dictionary:** `cv2.aruco.DICT_4X4_50`. Smallest predefined dict → highest
  inter-marker distance and fewest bits to extract at small pixel sizes = most
  robust; 50 IDs is far more than a handful of bench fiducials need.
- **Approach ladder** (origin + rotation): (1) ArUco fiducial(s) on the mount →
  refined corners → `estimateAffinePartial2D` / umeyama for a direct 4-DOF pose;
  (2) fallback for the bare rectangular die → `findContours` + `minAreaRect`
  (center + angle directly); (3) last resort → rotate-template search
  (`matchTemplate`, `TM_CCOEFF_NORMED`) or log-polar / Fourier–Mellin phase
  correlation for coarse rotation+scale, then refine.
- **Red flags:** aruco API **breaks between 4.6 and 4.7** (`Dictionary_get` /
  `DetectorParameters_create` removed → `getPredefinedDictionary` /
  `DetectorParameters()` / `ArucoDetector`) — write against 4.7+ only. Avoid
  `>=4.12.x`: numpy dependency rules changed there (py3.9+ wheels built with
  numpy 2.x) and an upper `numpy<2.3.0` cap appears — re-verify metadata before
  any bump. `matchTemplate` is **not** rotation-invariant.

## 1. OpenCV pin (cp310 / win_amd64 / numpy<2 / modern aruco)

- **abi3 wheels:** opencv-python-headless publishes one `cp37-abi3` wheel per
  platform. `opencv_python_headless-4.9.0.80-cp37-abi3-win_amd64.whl` is
  forward-compatible with CPython 3.10 on Win64 — there is no cp310-specific
  wheel and none is needed. [PyPI files, accessed 2026-07-13]
- **numpy metadata (identical for 4.9.0.80 / 4.10.0.84 / 4.11.0.86):**
  `numpy>=1.21.2 ; python_version >= "3.10"`. It is a **lower bound only** — it
  neither caps at `<2` nor forces `>=2`, so numpy 1.26.x satisfies all three.
  [PyPI JSON requires_dist, accessed 2026-07-13]
- **Why the build ABI decides it:** numpy's own policy is asymmetric — a binary
  **built against numpy 2.x runs on numpy 1.x**, but a binary **built against
  numpy 1.x will NOT run on numpy 2.0**. So (a) any numpy-1-built cv2 is safe on
  our pinned 1.26.x, and (b) numpy-2-built cv2 (>=4.10.0.84) is *also* backward-
  compatible to 1.21.2+. We choose **4.9.0.80** anyway because it is the last
  purely numpy-1-built release (numpy-2 prebuilt wheels for py3.9+ started at
  4.10.0.84, "experimental" at 4.10.0.82) — the maximally conservative choice for
  a codebase whose whole numpy<2 pin exists to protect the PySpin 1.x C-ABI.
  [numpy 2.0 migration / depending_on_numpy, accessed 2026-07-13; opencv-python
  release notes 4.10.0.82/4.10.0.84/4.12.0.88]
- **aruco availability:** the aruco module was moved from opencv_contrib into the
  main `objdetect` module in **OpenCV 4.7.0** (PR #22368). base
  opencv-python-headless 4.7+ therefore exposes `cv2.aruco.ArucoDetector`.
  4.9.0.80 = OpenCV 4.9.0 ✓. [opencv.org 4.7.0 notes; docs.opencv.org 4.8 aruco]
- **Release dates (context):** 4.9.0.80 = 2023-12-31; 4.10.0.84 = 2024-06-17.
- **Acceptable alternatives** if a newer bugfix is ever needed: 4.10.0.84 or
  4.11.0.86 keep the permissive `numpy>=1.21.2` metadata and per numpy's ABI
  policy import fine under numpy 1.26 — but they are numpy-2-built, a small extra
  risk 4.9.0.80 does not have. Do not go `>=4.12` without re-checking metadata.
- **Integration note (matches our constraints):** keep cv2 out of the numpy-pure
  `analysis/` layer, lazy-import inside the alignment module, and use the
  **headless** wheel (the GUI/full wheel bundles its own Qt plugins that clash
  with PySide6).

## 2. ArUco dictionary + physical marker

- **Dictionary — `DICT_4X4_50`.** OpenCV guidance: "choose the smallest
  [dictionary] that fits your application"; "the smaller the dictionary, the
  higher the inter-marker distance," and "smaller dictionary sizes and larger
  marker sizes increase the inter-marker distance." A 4x4 marker has the fewest
  bits to extract, so it stays detectable at fewer pixels. Use 5X5 only if you
  need many IDs or extra per-marker error correction and can afford more pixels.
  [docs.opencv.org tutorial_aruco_detection, accessed 2026-07-13]
- **Quiet zone / border.** Keep a white quiet zone around the black border;
  ArUco's own generator adds it (`markerBorderBits`). The FAQ warns to "avoid
  narrow borders around the ArUco marker (5% or less of the marker perimeter)."
  Print with a quiet zone ≥ 1 marker module on every side. [aruco FAQ]
- **Pixel budget for sub-pixel corners.** A `DICT_4X4_50` marker is 6 modules
  across (4 data + 1 border each side). Rule of thumb: ≥ ~4–5 px/module for
  detection (≈ 25–30 px marker minimum), but for reliable `cornerSubPix`
  refinement aim for the marker to span **~100–200 px** in the image. Corner
  refinement is off by default and set via `CORNER_REFINE_SUBPIX` (or
  `_CONTOUR` / `_APRILTAG`); enable it — it is the accuracy lever for pose.
  [aruco tutorial/FAQ; secondary for the px figures]
- **Physical size formula.** With object-plane scale `px_per_mm ≈ 170.6·M`
  (M = unknown relay magnification): `marker_mm = target_px / (170.6·M)`. Pick
  target_px ≈ 150; solve once M is measured on the bench (open question below).
- **Material / lighting (laser lab, secondary source).** Print on **matte**
  (non-glossy) stock — gloss + the polished metal mount/bond wires cause specular
  glare that destroys corner localization; prefer diffuse / off-axis
  illumination. The BFLY-U3-23S6M (Sony IMX249, mono) is a silicon sensor with
  residual **near-IR sensitivity**, so scattered laser light (esp. shorter-IR;
  1064 nm QE is low but nonzero) can bloom the image — consider an IR-cut /
  band filter *for the alignment frame* if the laser is on, but that is a bench
  trade-off (the same camera may need laser light for other tasks).

## 3. Rotation-robust detection ladder (classical, no CNN)

Target is origin + rotation to **<0.05 deg**; fiducials are the only path that
comfortably reaches it, so prefer them. Ordered by robustness/accuracy:

- **(1) ArUco fiducial (preferred).** Detect marker(s), refine corners, solve a
  2D rigid/similarity pose (§4). Direct, sub-pixel, no template needed. For
  <0.05 deg use a **long baseline** — one large marker OR two markers spread
  across the mosaic (see accuracy note in §4).
- **(2) Contour fit for the bare rectangular die.** Threshold/edge →
  `findContours` → filter by area/aspect → `cv2.minAreaRect` returns center +
  angle directly. For a clean rectangular silicon sensor this **beats template
  matching** (a rectangle has no rotation-unique texture; minAreaRect is
  purpose-built). Angle accuracy is edge-quantization limited (~0.1–0.5 deg
  typical) — good for coarse lock, then refine on the fiducial for <0.05 deg.
- **(3) Rotation search / Fourier–Mellin (last resort, no fiducial, textured).**
  `matchTemplate` is **not** rotation-invariant: rotate the template over the
  expected angle range, run `TM_CCOEFF_NORMED`, take the peak, interpolate
  (parabolic sub-pixel) both in xy and in angle. Or use log-polar
  (`cv2.warpPolar`) + phase correlation (Fourier–Mellin): rotation → shift in θ,
  scale → shift in ρ, recovered translation-invariantly, then a second phase
  correlation for xy. Angle resolution is bounded by the angular step / peak
  interpolation. [OpenCV template-matching tutorial; Fourier–Mellin refs below]

## 4. Pose from fiducials (2D rigid / similarity)

- **`cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC)`** estimates a
  4-DOF partial-affine (rotation θ, single uniform scale s, translation tx,ty)
  and returns a 2x3 matrix M plus an inliers mask. Methods: RANSAC (default) or
  LMEDS. For a pure similarity M = s·[[cosθ, −sinθ],[sinθ, cosθ] | t], so:
  `s = hypot(M[0,0], M[1,0])`, `theta = atan2(M[1,0], M[0,0])`. Feed it **all**
  refined corners of all detected markers (≥2 point pairs required; ≥8 for a
  stable RANSAC). If scale is known/fixed (calibrated px_per_mm), a Kabsch /
  Umeyama least-squares fit (numpy SVD) is an alternative that constrains s=1 and
  gives an analytically optimal rigid θ,t. [mexopencv / OpenCV calib3d;
  accessed 2026-07-13]
- **Accuracy expectation.** Corner-localization noise σ≈0.05–0.1 px over a
  baseline of B px gives angular σ ≈ σ_corner / B rad. To hit <0.05 deg
  (≈8.7e-4 rad) you need B ≳ 0.1/8.7e-4 ≈ **~115 px minimum** between the two
  farthest corners used, and comfortably more with sub-pixel refinement and
  many corners averaged. Achieve it with a large marker or two well-separated
  markers on the mosaic — a single small marker will not.

## Open questions for the bench

- **M (relay magnification)** is unknown → fixes both `px_per_mm` and the
  printed marker size. Measure it (calibration target) before printing fiducials.
  Cross-ref `docs/research/camera_optics_setup.md`.
- **Laser on/off during alignment?** Decides whether an IR-cut/band filter is
  needed and whether glare mitigation (matte marker, diffuse light) suffices.
- **Mount reflectivity / illumination geometry** — verify markers detect without
  specular washout on the real polished mount before committing a print.
- **Confirm on the actual venv:** `pip install opencv-python-headless==4.9.0.80`
  then `import numpy, cv2; cv2.aruco.ArucoDetector` under the pinned numpy 1.26.x
  (Claude must not run hardware; this import check is simulation-safe).

## Sources (accessed 2026-07-13)

- opencv-python releases / numpy dependency notes — https://github.com/opencv/opencv-python/releases
- PyPI opencv-python-headless 4.9.0.80 (files, cp37-abi3 wheels) — https://pypi.org/project/opencv-python-headless/4.9.0.80/#files
- PyPI JSON requires_dist (4.9.0.80 / 4.10.0.84 / 4.11.0.86) — https://pypi.org/pypi/opencv-python-headless/4.11.0.86/json
- numpy 2.0 migration guide (ABI break) — https://numpy.org/doc/stable/numpy_2_0_migration_guide.html
- numpy "depending on numpy" ABI handling (2.x-built runs on 1.x, 1.x-built does not run on 2.0) — https://numpy.org/doc/stable/dev/depending_on_numpy.html
- OpenCV 4.7.0 release (aruco → objdetect) — https://opencv.org/opencv-4-7-0/ ; PR #22368 — https://github.com/opencv/opencv/pull/22368
- aruco module moved to objdetect — https://docs.opencv.org/4.8.0/d9/d6a/group__aruco.html
- ArUco detection tutorial (dictionary choice, corner refinement) — https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html
- ArUco FAQ (borders, difficult imaging) — https://docs.opencv.org/4.x/d1/dcb/tutorial_aruco_faq.html
- estimateAffinePartial2D (4-DOF, RANSAC/LMEDS, 2x3 M) — https://amroamroamro.github.io/mexopencv/matlab/cv.estimateAffinePartial2D.html
- Log-polar / Fourier–Mellin registration — https://github.com/Smorodov/LogPolarFFTTemplateMatcher ; skimage example — https://scikit-image.org/docs/stable/auto_examples/registration/plot_register_rotation.html
