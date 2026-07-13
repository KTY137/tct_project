# Metrology mechanics facts — CR-10-class stage reality, reticles, prior art

- **Date:** 2026-07-13 · **Author:** Prometheus (researcher) · Workstream B1
- **For:** Jonathan's feasibility memo (`docs/research/metrology_feasibility.md`, B2)
- **Question:** What can an open-loop CR-10S-class printer stage (Marlin 2.1.x) plus
  camera actually achieve as a positioning/scanning metrology instrument, and what does
  a traceable calibration cost? Ground every number in a source; prefer measured data.
- **In-repo facts assumed (trusted, from the brief):** X/Y 80 steps/mm belt ⇒ 12.5 µm
  microstep @ 1/16, 200 µm full-step detent; Z 400 steps/mm leadscrew ⇒ 2.5/40 µm;
  camera IMX249 5.86 µm px, unknown relay M, px_per_mm ≈ 170.6·M; registration = FFT
  phase-corr parabolic peak ~0.05–0.1 px; NO measured bench numbers exist yet.
- **Confidence:** mechanics reality = secondary source (community tests + peer-reviewed
  prior art); reticle specs/prices = official manufacturer docs; CTE = engineering
  standard constants. See per-section tags.

## 1. CR-10-class mechanics — the reality (belt X/Y, leadscrew Z)

**Microstepping is resolution, not accuracy — and it does not hold under load.** This is
the single most important correction for the memo. [secondary]
- Standard hybrid steppers have **±5% non-cumulative** per-full-step position tolerance
  (Geckodrive, Lin Engineering). Microstepping subdivides the *command* but not the
  physical accuracy: "positional error remains the same … full-stepping or 1/32 stepping"
  (Geckodrive). So the 12.5 µm microstep is a **command grid**, not a 12.5 µm accuracy.
- **Incremental (restoring) torque collapses with microstepping.** At 1/16 the per-
  microstep incremental torque is only **≈9.8%** of full-step holding torque; a static
  load equal to **15% of holding torque displaces the shaft 1/10 of a full step** from
  the commanded microstep (Analog Devices / Embedded). For our 200 µm full-step detent,
  1/10 full-step = **~20 µm** of load-dependent sag per 15%-of-holding load.
- **Measured under load:** at 1/16 with a 1000 g·cm load a common A4988/TB6560 driver
  deflected **more than half a full step** (i.e. approaching ~100 µm-scale in our detent
  units) before recovering; loaded shafts wander up to **±2 full-steps** before losing
  steps (Hackaday laser-lever test, 3 drivers). Implication: microstep positions on a
  belt axis are *soft* — the carriage sits where load + belt tension balance, not
  necessarily at the commanded microstep.

**Belt drive adds compliance + backlash on reversal.** [secondary]
- The belt must be stretched by the motor before the load moves; there is a standardized
  compliance (stretch) test for exactly this (RepRap "Belt Compliance Measurement").
- Backlash on GT2 is dominated by tooth-mesh play + tension; "even 0.1 mm (100 µm) of
  backlash produces visible corner artefacts" and is reduced (not eliminated) by higher
  tension (Lazy Automation). Treat direction-reversal error as a **first-class term**.
- Peer-reviewed printed-stepper stages quantify how hysteresis **grows with travel**: a
  3D-printed flexure/stepper stage measured **<1 µm repeatability for small moves rising
  to ~15 µm for a 1 mm move** (Sharkey et al., *Rev. Sci. Instrum.* 87, 025104, 2016);
  another printed motorized stage reported **mean bidirectional repeatability ≈ ±5 µm**
  verified by particle-tracking 6 µm spheres (Wang et al., *Biosens. Bioelectron.*, 2016).
  These are the best public proxies for our belt-axis expectation: **single-digit-µm
  unidirectional repeatability is plausible; bidirectional/backlash is the µm–tens-of-µm
  killer.**

**Leadscrew Z.** Direct-drive leadscrew (our 400 steps/mm, 2.5 µm microstep) has far less
compliance than a belt but still carries stepper ±5% + reversal backlash; Z backlash is a
mechanical-nut property (accept single-µm to tens-of-µm until measured). [secondary]

## 2. Thermal drift

- Frame CTE: **aluminum 6061 ≈ 23.6 ppm/°C**; **steel / steel-cored GT2 belt ≈ 11–13
  ppm/°C** (AmesWeb, ArcusCNC). CR-10-class = mostly steel base frame + **aluminum-
  extrusion gantry**, so the aluminum members dominate optical-axis drift. [official/std]
- **Measured on a near-identical rig:** an aluminum-gantry microscope stage drifts
  **≈1.3 µm per 1 °C** of ambient change; over a 2-hour test *ongoing thermal drift was
  the dominant error source*, and a 20-min A/C-off excursion (~0.4 °C) moved the axis
  ~0.5 µm (Openstage, PLOS One 2014). Expect the same order on our gantry. [secondary]
- Community rule of thumb: printer frames need a **5–10 min (or longer) warm-up/heat-
  soak** before geometry is stable; Z creeps up as the frame warms (Ellis Print Tuning
  Guide). **Lever:** warm-up dwell + a periodic fiducial re-registration to null slow
  drift; a full metrology run should re-home/re-reference on a time or ΔT trigger.

## 3. Calibration reticles (chrome/photolithographic on glass)

Paper prints are NOT traceable (ink dot-gain, substrate instability); a **chrome-on-glass**
target is required for ~µm-level traceable scale. Photolithographic chrome edges resolve
to **~1 µm** (Thorlabs). Pitch guidance for px_per_mm ≈ 170.6·M: FOV(1920 px) ranges
**~22.5 mm @ M=0.5 → ~5.6 mm @ M=2**; a **1 mm scale / 10 µm divisions** spans the whole
M-range (10 µm = 0.85 px @ M=0.5 up to 3.4 px @ M=2 — labeled 100 µm marks stay resolvable
at low M); add a **10 mm / 50 µm** scale for wide-FOV low-M work, and a **grid/checker
distortion target** if lens distortion must be separated from stage error. [official docs]

Shortlist (US prices, 2026):

| Target | Pitch / span | Certified accuracy | Substrate | Price | Note |
|---|---|---|---|---|---|
| AmScope MR095 | 10 µm div / 1 mm | **none stated** (ISO-9001 shop only) | soda-lime | **$17** | cheap FOV check, NOT traceable |
| Thorlabs R1L3S2P | 10 µm div / 1 mm | ~1 µm edge res, no cert | soda-lime chrome | **~$276** (Fisher) | best price for good-M pitch |
| Thorlabs R1L3S1P | 50 µm div / 10 mm | ~1 µm edge res, no cert | soda-lime chrome | ~$275 class | wide-FOV / low-M companion |
| Edmund #16039 Reticle Cal. Stage Micrometer | fine, no cert | uncertified | glass chrome | **$343** | traceable-optional line |
| Edmund #16039 **NIST-cert** version | — | **±3 µm ≤125 mm** (±5 µm ≤300 mm) | glass chrome | **$630** | **traceable ~µm — meets the ~2 µm goal** |
| Edmund #16033 Multi-Grid + NIST | multi-pitch grid | NIST cert | glass chrome | $955 | grid + distortion + traceable |

**Recommendation for the ~2 µm traceable goal:** Edmund NIST-certified stage micrometer
(~$630, ±3 µm certified) is the cheapest path to a *traceable* scale; the ±3 µm cert is
coarser than our 2 µm aspiration, so the reticle certifies the *optical scale*, while the
2 µm claim still hinges on stage repeatability (§1) and sub-pixel registration, not the
reticle alone. A $17–$276 uncertified target is fine for **relative** px/mm and distortion
work today.

## 4. Prior art — camera-over-stepper-stage metrology (claims + how verified)

| Project | Claimed precision | Mechanism | Verification method |
|---|---|---|---|
| Openstage (PLOS One 2014) | uni ≤0.5 µm, **bi ~1.0 µm**, backlash ~0.04 µm (corrected), lin RMS 0.04 µm | 0.9° stepper + **precision micrometers** (not belt) 1/16 | tilted fluorescent slide → sub-pixel image registration; 100× Z-stack repeat |
| OpenFlexure Microscope | **88±6 nm/half-step XY**, 50±2 nm Z; stable few µm over days | monolithic **plastic flexure** + geared stepper | stage-scan vs image tracking; block-stage sub-100 nm fibre align (arXiv 1911.09986) |
| Sharkey flexure stage (RSI 2016) | <1 µm small / **~15 µm @ 1 mm** | one-piece printed flexure | move-and-return, imaged displacement |
| Wang printed motorized stage (2016) | **bi ±5 µm** | printed frame + steppers | particle-tracking 6 µm latex spheres |

**Take-away for the memo:** every sub-µm result used a **backlash-corrected leadscrew/
micrometer or a friction-free flexure**, plus **sub-pixel image registration against a
fixed fiducial** as the actual metrology (the stage is trusted only *after* image
verification). Belt-only printed stages land at **±5 µm-class bidirectional**. Two of them
explicitly used the *camera itself* (registration/particle tracking) as the truth sensor —
which is exactly our FFT-phase-correlation path, and the correct architecture: **the image
measures the stage, not vice-versa**, and Guizar-Sicairos (~0.01 px) upgrades that sensor.

## 5. Repeatability test protocol (ISO 230-2, simplified for an open-loop stage)

Follows ISO 230-2:2014 (machine-tool positioning) reduced for a hobby axis. [official std]
1. **Warm-up** first (§2): dwell until drift < threshold before recording.
2. Pick **≥5 target positions** spread across useful travel (not just endpoints).
3. Approach each target **≥5 times per direction, both directions** (bidirectional).
4. Measure achieved position with the camera+reticle (sub-pixel registration), not the
   commanded value. Per target compute: unidirectional repeatability R↑, R↓ (band half-
   width of achieved positions); **reversal value B = mean(x↑ − x↓)** ⇒ our **backlash**
   estimate; bidirectional repeatability R = spread over both directions.
5. **Backlash staircase:** approach one target from +N steps then −N steps for growing N
   to expose the travel-dependent hysteresis seen in §1 (<1 µm → ~15 µm).
6. **30-min drift run:** hold one target, log position vs time/ΔT ⇒ µm/°C and µm/hour.
   Existing repo code covers this: `repeatability.py`, `calibrate_affine`,
   `metrology_report.py` (per roadmap B3 — measure relay M in step 0 first).

## Summary — error source → typical magnitude → our lever

| Error source | Typical magnitude (sourced) | Our lever |
|---|---|---|
| Stepper per-step tolerance | ±5% of full step (±10 µm on 200 µm) | **accept** (random, non-cumulative) |
| Microstep load sag | ~20 µm per 15%-holding load; >½ full-step under heavy load | **measure** under real payload; keep loads light / slow |
| Belt backlash (reversal) | 100 µm-class if untensioned; grows with travel (~15 µm @ 1 mm on printed stages) | **compensate** (extra-step reversal, always approach targets one direction) |
| Belt compliance/stretch | proportional to load & span | **measure**; light payload, good tension |
| Z leadscrew backlash | single-µm–tens-µm (unmeasured) | **measure** + reversal compensation |
| Thermal drift | **~1.3 µm/°C** gantry; dominant over hours | **compensate** (warm-up + periodic re-registration) |
| Registration noise | ~0.05–0.1 px (parabolic) → ×(1/px_per_mm); 0.01 px w/ Guizar-Sicairos | **improve** algorithm; image is the truth sensor |
| Reticle scale error | ±3 µm (Edmund NIST) / uncertified otherwise | **traceable** cert if ≤~µm scale needed |

**Bottom line for B2:** best-case (light load, unidirectional, warmed-up, sub-pixel
registration) is plausibly **low-single-digit µm**; expected/worst case is dominated by
**bidirectional backlash + thermal drift at the µm–tens-of-µm scale**. A traceable ~2 µm
claim requires (a) a chrome-on-glass NIST reticle (~$630), (b) unidirectional approach +
reversal compensation, (c) warm-up/drift nulling, and (d) the image (not the stage) as the
metrology sensor. Numbers are all *prior-art/spec*; none are our-bench-measured — the B3
protocol above closes that gap.

## Sources

- Geckodrive, *Accuracy and Resolution* — https://www.geckodrive.com/support/accuracy-and-resolution/
- Lin Engineering, *Increasing Accuracy in Stepper Motors* — https://www.linengineering.com/news/methods-for-increasing-accuracy-in-stepper-motors
- Analog Devices / Embedded, *Mastering Precision: Microstepping* — https://www.analog.com/en/resources/analog-dialogue/articles/mastering-precision-understanding-microstepping.html
- Hackaday, *How Accurate Is Microstepping Really?* — https://hackaday.com/2016/08/29/how-accurate-is-microstepping-really/
- RepRap, *Belt Compliance Measurement* — https://reprap.org/wiki/Belt_Compliance_Measurement
- Lazy Automation, *GT2 Belts and Pulleys Explained* — https://www.lazy-automation.com/gt2-belts-and-pulleys-explained-how-3d-printer-motion-systems-work
- Campbell, Eifert, Turner, *Openstage*, PLOS One 9(3):e88977 (2014) — https://pmc.ncbi.nlm.nih.gov/articles/PMC3935852/
- OpenFlexure Microscope — https://openflexure.org/projects/microscope/ ; Block Stage (sub-100 nm) arXiv 1911.09986 — https://arxiv.org/pdf/1911.09986
- Sharkey et al., *One-piece 3D-printed flexure translation stage*, Rev. Sci. Instrum. 87, 025104 (2016) — https://pubs.aip.org/aip/rsi/article/87/2/025104/1021864
- Wang et al., printed motorized HCS stage, Biosens. Bioelectron. (2016) — https://www.sciencedirect.com/science/article/pii/S095656631631106X
- Ellis' Print Tuning Guide, *Thermal Drift* — https://ellis3dp.com/Print-Tuning-Guide/articles/troubleshooting/first_layer_squish_consistency_issues/thermal_drift.html
- AmesWeb, *Linear Thermal Expansion Coefficient of Metals* — https://amesweb.info/Materials/Linear-Thermal-Expansion-Coefficient-Metals.aspx
- ArcusCNC, *CTE Aluminum 6061* — https://arcuscnc.com/cte-aluminum-6061/
- Thorlabs, *Stage Micrometers* (R1L3S1P/S2P) — https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=7502 ; R1L3S2P price via Fisher NC1713051 — https://www.fishersci.com/shop/products/NC1713051/NC1713051
- Edmund Optics, *Reticle Calibration Stage Micrometer, NIST traceable* (#16039), *Multi-Grid #16033* — https://www.edmundoptics.com/p/reticle-calibration-stage-micrometer-nist-traceable/16039/ ; category https://www.edmundoptics.com/c/reticles-stage-micrometers/707/
- AmScope MR095 stage micrometer ($17) — https://amscope.com/products/mr095
- ISO 230-2:2014 — https://www.iso.org/standard/55295.html ; field-method summary — https://industrialmonitordirect.com/blogs/knowledgebase/measuring-cnc-axis-positioning-repeatability-iso-230-2-test
