# Research notes

Cited reference notes produced by Prometheus, the `researcher` subagent (see
`.claude/agents/researcher.md`): instrument manuals, SCPI/GRBL command references,
library documentation, and physics references.

Conventions:
- One topic per file: `<topic>.md` (e.g. `iseg-shr-scpi.md`, `grbl-1.1-jogging.md`).
- Every note carries a date, the exact question, verbatim command strings, source
  URLs, and a confidence line (`verified in official manual` vs `secondary source`).
- Commands from these notes may only be used on hardware after the confidence line
  says they were verified against the official manual for the exact model.

## Index of research notes

| Date | File | Topic | One-line takeaway |
|---|---|---|---|
| 2026-07-13 | `qml_hybrid_standard_decision.md` | Should the QML-hybrid shell be RATIFIED as STANDARD? | Stress test the go/no-go: v5 cockpit is **opt-in not default** pending probe on CPU-bound i7-10510U over RDP (RHI pinned OpenGL for Stage GLViewWidget coexistence); headless-tested, Mary-reviewed. Decision owner Kaya. |
| 2026-07-13 | `dwm_backdrop_blur_recipe.md` | DWM Mica/Acrylic backdrop blur recipe (Win11) | QDialog shows real acrylic blur; QMainWindow transparent but crisp (no blur) — the Qt limitation. Recipe requires `DwmExtendFrameIntoClientArea(-1,-1,-1,-1)` + `SYSTEMBACKDROP_TYPE=38` + `WA_TranslucentBackground`; blur is a QDialog-only win. |
| 2026-07-13 | `metrology_feasibility.md` | Metrology feasibility memo — error budget & honest verdicts (B2) | Camera-MEASURED metrology realistic class; 2µm relative claim only (never open-loop). Error budget as f(M); bench protocol §12a–d replaces all priors with real numbers. Companion to metrology_mechanics_facts (B1) + BENCH_CHECKLIST §12. |
| 2026-07-13 | `metrology_mechanics_facts.md` | Metrology mechanics — CR-10 stage reality, reticles, prior art (B1) | Microstepping ≠ accuracy; belt ±5µm, leadscrew 2.5/40µm, thermal 1.3µm/°C, ±5% stepper non-cumulative tolerance. Reticle shortlist $17–$955; ISO-230-2-style protocol. 18 sources. Feeds metrology_feasibility (B2). |
| 2026-07-13 | `sensor_alignment_cv.md` | Sensor alignment via computer vision (calibration target stitch) | Camera-DUT geometric alignment: detect fiducial patterns, compute homography matrix, validate distortion model. Feeds camera-survey-metrology feature (mm-per-pixel calibration + stage cross-talk correction). |
| 2026-07-13 | `camera_binning_nodes.md` | FLIR Blackfly Mono16 binning node writeability + Average mode | SN 19112408: Sum-only (no Average in hw); per-node IsWritable check required before writes. DisplayScaling property missing (no on-sensor demosaicing). Binning-2/4 clamp to working mode + display rescale mandatory. |
| 2026-07-12 | `apple_vibrancy_qt_feasibility.md` | Apple vibrancy semantics + Qt glass feasibility (Win11 target) | Verdict adopted for v5: glass = pre-blended QSS tokens (Apple itself degrades to opaque under Reduce Transparency); real blur only as snapshot-once QML on static outer chrome; plots/camera always opaque; DWM Mica skipped; 4.5:1 contrast floor. |
| 2026-07-11 | `qml_hybrid_architecture.md` | QML chrome + pyqtgraph plots hybrid, 3-layer law | QML (QQuickWidget islands) + pyqtgraph sibling QWidgets + DetachableTabWidget unchanged; full-QML rejected (pyqtgraph 0.2–0.4 ms/frame vs QtCharts 4–6 ms + jank); RHI OpenGL; Theme singleton; 3-layer law (UI→backend→drivers, no GUI-thread compute) enforced by static contracts + watchdog test; slice 1 = Scope vertical. |
| 2026-07-10 | `camera_optics_setup.md` | Camera / laser-relay optics — bench findings | BFLY-U3-23S6M-C coaxial beam-monitoring setup (shared laser/camera objective); 5 open bench actions (relay lens engravings, parfocality, height lock, ROI calibration, ROI writeability); known-good settings (Mono8/bin1/13009µs/14dB/gamma1.0/trigger-off); two app-side display bugs (Mono16 banding, binning white-frame). |
| 2026-07-08 | `scan_viewer_design_review.md` | ScanPanel retirement design review | Endorse Planner-only config surface + separate ScanViewerPanel; identify 4 gaps (Z-focus, manual-pause, multi-channel vscan, fast-raster) for Phase 3 planning. |
| 2026-07-07 | `printrun_printcore_motor_eval.md` | Motor backend evaluation | Reject Printrun `printcore` (GPLv3+ copyleft + dependency bloat); hybrid-harden custom GRBL driver with Marlin robustness patterns instead. |
| 2026-07-07 | `bench_lan_dhcp_static.md` | Bench LAN addressing | Choose static IPs (not DHCP-server-on-PC) for 3–5 instrument bench; simpler, deterministic, no rogue-DHCP risk. |
| 2026-07-07 | `pdl800_trigger_wavegen_lan.md` | PDL 800 trigger, DG4162 square, bench LAN | (1) PDL 800 trigger safe for ±2.5 V bipolar square; (2) DG4162: use `:VOLT:HIGH`/`:VOLT:LOW` + `:OUTPut:LOAD 50` to avoid amplitude-halving trap; (3) managed switch drops mDNS — use static IPs or hardcoded VISA strings. |
| 2026-07-06 | `tbs1000c_scpi.md` | Tektronix TBS1052C SCPI (bench scope) | Live-verified on bench TBS1052C: `TRIGger:A:*` trigger tree (not bare `TRIGger:`); ACQuire:NUMAVg accepts 2–256; SELect:CH<x> works; bench unit had Header OFF so driver forces it deterministic. |
| 2026-07-06 | `iseg_polarity_scpi.md` | iseg HV polarity switching | Safe channel polarity reversal: verify OFF (via status bit 3 + discharge < 0.002·V_range); switch via `:CONF:OUTP:POL`; confirm with 0.5 s poll budget (relay settle time UNVERIFIED on real HV). |
| 2026-07-05 | `ui_design.md` | GUI design best practices (PySide6) | Use 8pt spacing grid + 4pt sub-step, consistent type/token scale, axis-rail color palette, dense-panel compound controls; cite Material Design and superqt patterns. |
