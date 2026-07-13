# Metrology feasibility — error budget, honest verdicts, and what the bench must resolve (B2)

- **Date:** 2026-07-13 · **Author:** Jonathan (data/analysis) · Workstream B2 (roadmap Part V)
- **Inputs:** `docs/research/metrology_mechanics_facts.md` (B1 — external mechanics reality),
  `docs/design/camera_survey_metrology.md` (design note + verified sensor facts), repo code cited
  inline as `path:symbol`.
- **Decision owner:** Kaya. This memo is ergebnisoffen — it ranks what is realistic and what each
  option costs; it does not pre-decide the M2 go/no-go.
- **Companion:** the bench protocol that replaces these priors with OUR numbers is
  `docs/BENCH_CHECKLIST.md` §12 (B3, written the same day). Bench results land in §7 below.

## 0. Read this first — source classes (the loud part)

**Not one micrometre figure in this memo was measured on our bench.** Every number is tagged:

- **[B1]** — prior art / vendor spec / engineering constants from `metrology_mechanics_facts.md`
  (community stepper tests, peer-reviewed printed-stage papers, reticle datasheets, CTE tables).
- **[repo]** — a constant that exists in this repository (config keys, sensor pitch, algorithm class).
- **[derived]** — arithmetic combining the two (e.g. px noise × µm/px).

There are **zero bench-measured numbers in-repo** (B1 header; confirmed — no measurement artifact
or recorded result exists under `docs/` or `artifacts_claude/`). The relay magnification **M is
UNKNOWN** (`docs/design/camera_survey_metrology.md` §0: px_per_mm ≈ 170.6·M, M unmeasured), so every
optics column below is conditional on §12 step 0. Treat this entire budget as a *prediction to be
falsified at the bench*, not a datasheet.

## 1. The three error clusters

### 1a. Mechanics (independent of M) — [B1] unless noted

| Term | Magnitude | Note |
|---|---|---|
| Command quantum X/Y | 12.5 µm | [repo] `configs/devices.yaml` `motor.steps_per_mm.x/y: 80.0` → 1/80 mm; `microsteps: 16` → full-step detent 200 µm; `snap_mode: 'off'` |
| Command quantum Z | 2.5 µm | [repo] `motor.steps_per_mm.z: 400.0`; full step 40 µm |
| Per-full-step tolerance | ±5 % → ±10 µm on the 200 µm detent | random, non-cumulative |
| Microstep load sag | ~20 µm per 15 %-of-holding-torque load; >½ full step under heavy load | microstep positions are *soft* — the carriage sits where load and belt tension balance |
| Belt reversal backlash | up to ~100 µm untensioned; hysteresis grows with travel (<1 µm small moves → ~15 µm @ 1 mm on printed stages) | **no compensation exists in our driver**: [repo] grep `backlash` in `TCT_app/devices/` = zero hits (2026-07-13); the only in-repo backlash code *measures* it (`controller/repeatability.py:_reduce_backlash`) |
| Thermal drift | ~1.3 µm/°C on an aluminium-gantry rig; dominant over hours | lever: warm-up + periodic re-registration |
| Prior-art belt-class bottom line | uni single-digit µm plausible; **bidirectional ±5 µm class at best**, µm–tens-of-µm typical | Sharkey 2016, Wang 2016 |

### 1b. Optics (∝ 1/M) — [repo] sensor, [derived] scaling

IMX249: 5.86 µm pixels, 1920×1200 (`docs/design/camera_survey_metrology.md` §0, datasheet-verified).
Object-plane sampling = 5.86/M µm/px; FOV = 11.25/M × 7.03/M mm:

| | M=0.5 | M=1 | M=2 | M=5 |
|---|---|---|---|---|
| µm per pixel | 11.72 | 5.86 | 2.93 | 1.17 |
| FOV (mm) | 22.5 × 14.1 | 11.3 × 7.0 | 5.6 × 3.5 | 2.25 × 1.41 |

**Unquantified optics unknowns (flagged, not budgeted):** M itself; relay distortion across the
field (needs a grid target); focus tilt / depth-of-field over the FOV; vignette extent (mitigated in
software by `analysis/image_prep.py:prepare_metrology_roi` — background-subtract + quality score —
but the physical image circle is unmeasured).

### 1c. Algorithm — [repo] implementation class, [B1/lit] precision

- **Today:** `controller/repeatability.py:cross_correlation_shift` — Hann-windowed, phase-only FFT
  correlation with 3-point parabolic sub-pixel peak (`_parabolic_peak`). Literature class
  **~0.05–0.1 px**, with peak-locking bias toward integer pixels (design note §B.1, Foroosh 2002).
- **Upgrade (planned, NOT in repo):** Guizar-Sicairos upsampled matrix-DFT refinement, **~0.01 px**,
  numpy/scipy-only (~40 lines). Confirmed absent: grep `upsample|Guizar|matrix-DFT` over `TCT_app/`
  finds no implementation (2026-07-13) — design §B.1/§E.7 names it as a future beat.
- Registration noise in µm = (px noise) × 5.86/M. The image is the truth sensor; every prior-art
  sub-µm result used exactly this architecture (B1 §4).

## 2. Error budget as f(M)

Measurement classes:
- **(a) Relative in-FOV** — distance/offset between two features (or two frames) with the stage
  parked; registration-limited. Scale term excluded (see footnote 2).
- **(b) Stage-commanded positioning** — open loop: command mm, trust the stage. Camera unused;
  **M-independent by construction**.
- **(c) Camera-corrected positioning** — the M3 north star: camera measures the residual, stage
  makes corrective moves, loop repeats. Two honest sub-numbers: **(c-land)** where the stage
  physically ends up, and **(c-know)** how well the achieved position is *known* afterwards —
  for scan reconstruction, (c-know) is what enters the data.

Per-axis µm, best / expected / worst. Expected = today's code + a warmed-up, lightly loaded,
reasonably tensioned bench. All values [derived] from §1 unless tagged.

| Class · case | M=0.5 | M=1 | M=2 | M=5 | Dominated by |
|---|---|---|---|---|---|
| (a) best (GS upgrade¹) | 0.2 | 0.08 | 0.04 | 0.02 | registration |
| (a) expected (today) | 0.8–1.7 | 0.4–0.8 | 0.2–0.4 | 0.1–0.2 | parabolic peak, 0.05–0.1 px ×√2 |
| (a) worst | ~6 + distortion | ~3 + distortion | ~1.5 + distortion | ~0.6 + distortion | peak-locking/weak texture (~0.5 px), unmeasured distortion |
| (b) best | ±2–5 | ±2–5 | ±2–5 | ±2–5 | uni approach, light load [B1] |
| (b) expected | ±5–15 | ±5–15 | ±5–15 | ±5–15 | per-step tolerance + hysteresis [B1] |
| (b) worst | ±20–100+ | ±20–100+ | ±20–100+ | ±20–100+ | reversal backlash, load sag, cold frame [B1] |
| (c-land) best³ | ±2–3 | ±2–3 | ±2–3 | ±2–3 | soft microstep under light load |
| (c-land) expected | ±6–12 | ±6–12 | ±6–12 | ±6–12 | ½ command quantum (6.3 µm) + microstep softness |
| (c-land) worst | ±15–25 | ±15–25 | ±15–25 | ±15–25 | ~20 µm load sag, backlash-stalled corrections |
| (c-know) best¹ | 0.2 | 0.1 | 0.05 | 0.03 | GS registration + drift-nulling |
| (c-know) expected | 0.7–1.3 | 0.3–0.7 | 0.2–0.35 | 0.07–0.15 | parabolic registration |
| (c-know) worst | 4–7 | 2–4 | 1–2 | 0.6–1.2 | vignette residue, drift between reference and measurement |

**Footnotes / assumptions**
1. "Best" rows assume the GS ~0.01 px upgrade, which is a *future beat* (§1c) — today's floor is
   the "expected" row.
2. Class (a) additionally carries a multiplicative **scale error × distance**: with M unmeasured the
   absolute scale is simply unknown; after the §12 step-2 staircase it is tied to the stage's own
   steps/mm truth (~0.5–1 % honesty class [derived]); a chrome reticle brings it to ~0.1 % class
   (uncertified) or ±3 µm absolute (NIST cert) [B1 §3]. Example: 1 % of a 5 mm in-FOV distance
   = 50 µm — for distances, the reticle matters more than the correlator.
3. (c-land) is mechanically floored, hence M-independent in practice: registration (≤1.2 µm even at
   M=0.5) is far below the 12.5 µm X/Y command grid. Best case assumes targets commensurate with the
   12.5 µm grid (e.g. 0.1 mm scan steps = 8 microsteps exactly); arbitrary targets pay ±6.3 µm
   quantization. Z's 2.5 µm grid is finer, but Z nut backlash is unmeasured [B1 §1].
4. Drift is excluded for measurements completed in minutes; add ~1.3 µm/°C [B1 §2] for long series
   (quantified for OUR frame by §12 step 3).

**Headline at M=1 (expected, per axis):** in-FOV relative ≈ **0.4–0.8 µm**; stage-commanded ≈
**±5–15 µm**; camera-corrected ≈ **±6–12 µm landed**, known afterwards to **0.3–0.7 µm**.

## 3. Honest verdicts (Kaya decides; nothing here is a commitment)

- **V1 — realistic WITHOUT hardware changes (the strong result):** camera-*measured* metrology.
  In-FOV relative measurement and camera-corrected coordinate *knowledge* at the **sub-µm class for
  M ≥ 1** with today's code; landing accuracy ~±10 µm class. The camera measures the stage, never
  vice-versa (B1 §4 take-away). Everything here is bench-unverified until §12 runs.
- **V2 — stage-only positioning:** **±5 µm class at best** (unidirectional, warm, light load — the
  best published belt-stage results [B1 §1/§4]), realistically ±5–15 µm, and tens of µm the moment
  direction reversals, payload, or a cold frame enter. Load- and thermal-dependent; never
  certifiable from commanded coordinates alone because the stage is open-loop
  (`controller/repeatability.py` module docstring states exactly this).
- **V3 — what the "2 µm" aspiration actually requires:** it is reachable only as a *measurement*
  claim — (i) the GS ~0.01 px registration upgrade (needs beat), (ii) the camera-corrected loop
  with (c-know) bookkeeping in the data path, (iii) thermal discipline: warm-up + re-registration
  cadence set by the §12 step-3 drift numbers, (iv) a reticle **for SCALE only**, not certification
  theatre. And say it plainly: the cheapest *traceable* reticle cert is **±3 µm** (Edmund NIST
  [B1 §3]) — so "2 µm traceable absolute" is **not purchasable at $630**; the defensible claim is
  "**≤2 µm relative / repeatability, on a scale traceable to ±3 µm**".
- **V4 — what 2 µm can NEVER mean on this machine:** open-loop *commanded* accuracy. The X/Y command
  grid is 12.5 µm [repo], microstep positions sag ~20 µm under 15 %-of-holding load [B1], and belt
  reversal backlash is uncompensated [repo]. No software change alters this; only closing the loop
  through the camera does.

## 4. Shopping list tiers (from B1 §3)

| Tier | Item | Price | Buys | Does NOT buy |
|---|---|---|---|---|
| Sanity | AmScope MR095 (10 µm div / 1 mm) | **$17** | §12 step-0 M measurement; rough px/mm; a textured, focusable target | any stated accuracy; traceability; distortion mapping |
| Working | Thorlabs R1L3S2P (10 µm / 1 mm) [+ R1L3S1P 50 µm / 10 mm for low M] | **~$276** [+~$275] | chrome ~1 µm edges → ~0.1 %-class relative scale; clean sub-pixel registration target across M range | a certificate — accuracy is plausible, not provable |
| Traceable | Edmund #16039 NIST-cert stage micrometer | **$630** | **±3 µm certified** scale ≤125 mm — the only path to defensible absolute µm | anything better than ±3 µm; the stage itself; distortion grid (#16033 multi-grid + NIST = $955 if that is wanted too) |

Today's paper-print target is fine for texture and a *first* M estimate (~1 % printer scale
honesty), and for nothing else — paper is explicitly non-traceable (B1 §3).

## 5. Explicit unknowns the §12 bench protocol resolves

1. **M and px_per_mm** (step 0) — unlocks every optics column of §2.
2. **Registration + vibration noise floor** (step 1, zero-excursion run) — the number every other
   result is quadrature-compared against.
3. **Real repeatability under OUR payload** (step 1) — pooled multi-direction scatter today;
   per-direction split needs a small beat (design §B.0-3).
4. **Real per-axis backlash** X/Y (step 2, `calibrate_affine` forward/return →
   `StageCameraCal.backlash_mm`) and its size class vs the 12.5 µm quantum.
5. **Linearity residuals + PASS/FAIL** at a candidate tolerance (step 2, `tolerance_um` gate via
   `analysis/camera_calibration.py:residual_summary`).
6. **Steps/mm truth:** staircase scale (px per *commanded* mm) vs reticle scale (px per *true* mm)
   — their ratio calibrates the belt-pitch/steps-per-mm error itself. Nobody has this number.
7. **Drift on OUR frame** in µm/h and µm/°C (step 3) — sets the re-registration cadence for V3.
8. **Vignette extent and DUT texture adequacy** — does `prepare_metrology_roi`'s quality score stay
   above the 0.2 default gate on our actual surfaces at all?

## 6. What M2 (go/no-go for closed-loop M3) reads from the bench results

M2 should decide from the §7 numbers, not from this memo's priors:

- noise floor (unknown 2) ≤ ~0.1 px equivalent — else the correction loop chases noise;
- measured backlash (unknown 4) bounded and stable — decides whether M3 must impose a
  one-directional approach policy or can correct through reversals;
- correction-loop convergence: iterations needed to land inside a candidate tolerance given the
  measured quantum/softness (c-land row vs reality);
- drift rate (unknown 7) → maximum time between re-registrations during a scan;
- measured M vs DUT geometry: FOV at that M must cover the features M3 wants to servo on;
- the `calibrate_affine ... passes` verdict at the tolerance M3 actually needs.

## 7. Bench results (to be filled by BENCH_CHECKLIST §12 — empty until then, on purpose)

| Quantity | Predicted (§2) | Measured | Date / artifact |
|---|---|---|---|
| M (step 0) | unknown | — | — |
| px_per_mm (step 0) | 170.6·M | — | — |
| Noise floor, px & µm (step 1) | ~0.05–0.1 px | — | — |
| Return scatter std X/Y, µm (step 1) | ±5–15 | — | — |
| Backlash X / Y, µm (step 2) | µm–tens-µm | — | — |
| Affine rms_um / passes (step 2) | — | — | — |
| Drift µm/h, µm/°C (step 3) | ~1.3 µm/°C class | — | — |

## Sources

- `docs/research/metrology_mechanics_facts.md` (B1) — all [B1] figures, with its 18 external sources.
- `docs/design/camera_survey_metrology.md` — sensor verification, algorithm class, design gaps.
- Repo, cited inline: `configs/devices.yaml` (motor block), `controller/repeatability.py`
  (`cross_correlation_shift`, `RepeatabilityTester.run/calibrate/calibrate_affine`,
  `fit_stage_camera_affine`, `StageCameraCal`), `analysis/camera_calibration.py`
  (`fit_affine`, `residual_summary`), `analysis/image_prep.py` (`prepare_metrology_roi`),
  `scripts/metrology_report.py` (`write_report`), `gui/calibration_panel.py` (`_run_repeatability`).
