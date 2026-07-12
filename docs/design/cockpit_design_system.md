# TCT Cockpit Design System — CANONICAL SPEC (v4)

*Frozen 2026-07-12 after a 7-seat design council (Noah, Jonathan, Abel, Paul,
Prometheus, Codex adversarial, Ollama advisory) and two hard iteration rounds.
The living visual reference is `artifacts_claude/tct_cockpit_design_v4_final.html`
(interactive: run the demo scan, inject a fault, try the two-step arm latch).
This document is the contract; panels that violate it do not merge.
Council sources: `docs/research/cockpit_design_sota.md`,
`docs/design/second_opinion_codex.md`, `docs/design/council/ollama_advisory.md`,
`docs/design/apple_style_ui_audit.md`.*

## 1. The eight laws (non-negotiable)

1. **Quiet nominal.** Grey is the color of "everything is fine" (ISA-101).
   Saturated color only for abnormal / armed / live-dangerous / running.
   Green is spent sparingly; the accent never means "good".
2. **Command classes, not one red.** Red = HV energization, trips, Abort —
   nothing else. Motion commands are **amber-gated**; laser output
   amber/neutral; disconnect grey. A scan start that ramps HV is amber with
   its HV line called out red inside the envelope text.
3. **Numbers are mono, prose is quiet.** Physical quantities: mono, tabular,
   unit subordinated. Labels: tiny tracked mono uppercase (instrument
   engraving). Explanations: sentence-case sans. Never uppercase prose.
4. **Staleness is designed.** No raw `--`. Tiles with nothing to say are
   stale (dim + desaturate) with a caption saying why (not connected / no
   run / value aged Ns). Data ink never silently freezes.
5. **Two-step arm, instant stop.** Danger = a latch: Arm (hold 3 s OR press
   twice — keyboard parity, glove-reliable) rendered over the FULL
   `DangerAction` envelope text (channels, V-range, ramp shape, motion
   bounds), then visible armed state with ~10 s timeout, then Execute.
   Implemented THROUGH `DangerGate` (never around it); separate gates per
   class (HV / motion / laser). Abort and All-HV-off are one instant tap.
6. **Simulation can never pass as real.** Hatched-cyan ring per device,
   persistent ribbon ("Simulation — N of M devices"), watermark on sim
   plots; runtime fallbacks (camera PySpin→sim) flip markers live. Sim never
   borrows green. Sim-marking is cyan's ONLY chrome job (else cyan = data).
7. **The UI never lies about hardware.** Measured vs setpoint labeled apart;
   unknown states say "unknown" (GRBL limit switches; Marlin motion); no
   control implies a capability the driver lacks (the manual laser gets NO
   software emission switch — a state banner instead).
8. **Motion is a scarce signal.** Values update, they don't animate. State
   transitions ease ~200 ms; only live states pulse; one attention pulse per
   new critical alarm; nothing decorative moves. No effects on hot paths.

## 2. Tokens (extend gui/style.py + QML Theme; additive)

Dark: canvas #0A0D13 · panel #121824 · raised #192134 · sunk #0C1019 ·
well #0E1420 · hairline #222B3E / strong #334159 · specular rgba(255,255,255,.045)
· text #E9EDF5 · muted #98A1B5 · faint #5B657A. Accent #5AA9FF (one accent).
Semantic: danger #FF5A61 · armed #FFB84D · good #3DD68C · sim #41D8E4
(hatch pattern, chrome use = sim-marking only). Light theme: see artifact
tokens; both first-class, contrast-checked. Depth = surface ladder +
hairlines + one frosted chrome strip; no drop-shadow soup; nothing
translucent over a plot. Radii 8/12/16.

## 3. Type scale (Codex-calibrated; system sans + mono numerals)

Rail/buttons 13 px w560-600 · panel titles 17-20 px w650 (no hero titles in
operational panels) · body 12.5-13 px w400-450 · metric labels mono 10 px
w600 tracking ≤.08em uppercase · primary values mono 24-28 px w600 tabular,
letter-spacing 0 (compact 17-20 px) · units 11-12 px muted. Negative
tracking only on display headings, never body/values. Label ink ≥85%.
Values must ellipsize/fit — a tile can never bleed into a neighbor.

## 4. Data ink (Jonathan's rulings)

- **Viridis** for all single-signed maps (charge/CCE/amplitude/drift);
  diverging (CET-D1-like) ONLY for signed-around-zero data with forced
  symmetric range; warm end must not be confusable with HV red.
- Colorbar always, with unit bound to the selected quantity.
- **Unsampled cells are never data-colored** (hatch/transparent — fixes the
  NaN→vmin bug in `scan_map_view._redraw`). Missing/duplicate counts surfaced.
- Waveforms: integration window as shaded (ideally draggable) band; baseline
  band; onset/CFD ticks; "avg ×N" chip when tiles show means.
- CCE plots label the convention + Q_ref used; depletion-voltage estimate is
  drawn as an annotated line on the curve.
- Monitor history: per-channel units/legend chips (no mixed unlabeled axis);
  NaN gaps for failed polls; per-row staleness (timestamp age).
- Plot chrome: grid alpha ~0.15, mono tick font ~10.5-11 px, ≤6 major ticks,
  crosshair InfiniteLine pair, legends in the FigureCard header.
- Physics copy is sourced from code: 1 MIP ≈ `q_one_mip_pC(thickness)`
  (≈3.6 fC @ 300 µm — never "3.9 pC").

## 5. Run lifecycle as design (Abel's map)

Readiness ladder DISCONNECTED→CONNECTED→HOMED→CONFIGURED→READY must be
legible (say WHY Start is disabled). RUNNING carries a derived phase label
(arming HV / moving / settling / acquiring / saving) — presentation only,
never new AppState members. PAUSED surfaces the manual-pause prompt.
Terminal states differ: FINISHED (good; banner + first-class "Open in
Analysis" + map retained stale) vs ABORTED (neutral crit; fail-safe caption)
vs FAULT/trip (red; errorText SURFACED, not a grey dash). Progress reads
0/N from plan_estimate at scan_started. Status strip hierarchy: State and
HV are the two high-salience tiles; Progress·ETA merged; Position compact;
last-charge lives at the waveform, not the strip.

## 6. Hardware truth (Paul's map)

Rail: per-device dots with ≥4 states (real-connected / simulated-hatched /
disconnected-faint / fault-red); "Connected N/M" chip; every cached truth
gets a staleness cue. Bias hero trio: Voltage·measured (polarity from
readback; setpoint in caption) · Current (compliance % in caption) ·
**HV STATE** (OFF / RAMPING↑↓ / SETTLED / TRIPPED). Failed connects are
designed error states (EmptyState error variant), not message boxes.
Driver backlog implied (Paul + Mary + manuals): HV output-on bit, ramp
state/progress, trip/interlock decode `TODO(manual needed)`; GRBL
state()/alarm + real limit-switch parse; Marlin honest "moving (no
readback)"; scope acquisition_state(); clipping promoted from log to status.

## 7. Panel recipes (not boxes-in-boxes)

Every panel = hero region + compact inspector + one command row + (if
dangerous) one danger well. Shared rhythm and type, not identical frames.
Per-panel calls (Noah's inventory; full detail in council transcript):
- **Planner** = reference implementation, restyle FIRST. Tree hero (already
  right); axis-rail colors keep semantics, so drop redundant caps.
- **Scan Viewer**: map hero; Z-focus collapsed by default; finished→Analysis
  chain; strip fixes; map toolbar visible even in empty state.
- **Camera**: ADD Live/Single/Stop (real functional gap — no acquisition
  control exists today); saturation shown on the image; designed not-
  streaming/error states.
- **Bias**: safety dashboard (see §6); IV + CCE-vs-V sweeps fold into one
  collapsed "Standalone sweeps (advanced)" card.
- **Laser**: honest banner (law 7); wavegen is the real control; metadata
  demoted.
- **Calibration**: two procedure cards (Method→Apply&Save; Repeatability);
  intro becomes sentence-case one-liner; add standard header (missing).
- **Monitor**: 4 alarm-colored tiles up top; table demoted; staleness per row.
- **Analysis**: recent-runs list as the empty state; run header bar;
  segmented modes.
- **Motor**: position hero + click-to-target on the map; step segmented;
  Move absolute = amber-gated; STOP loudest.
- **Scope**: trace hero; 4 tiles (Amplitude/Rise/Charge/**Drift time**);
  Live/Single/Avg command bar; measurements table collapsible; true
  acquisition-state chip.
- **Reference Monitor**: 15-minute win — 2 tiles + chip + waveform hero.

## 8. Missing-idea backlog (Codex; post-D5)

Command palette (state-aware, safe commands only) · toast/alarm/event
discipline (transient toast vs persistent alarm row vs log-only — HV trips,
aborts, failed connects, finished exports each classified) · detached-window
language (compact rail, theme sync, sim/live inheritance, redock affordance).

## 9. Implementation roadmap (hard-follow; gates)

| Phase | Scope | Gate |
|---|---|---|
| D0 | Token+type pass in style.py/panel_kit/status_widgets/QML Theme: quiet-nominal chips, sentence-case, staleness, sim treatment, command classes | guard tests + Mary |
| D1 | Planner restyled as reference implementation | capture-harness diff + Kaya look |
| D2 | Frame: rail dots (4-state), sim ribbon, readiness ladder, strip hierarchy, MetricTile fit/ellipsize (fixes QML overflow bug), detached-window basics | detach tests green |
| D3 | Scan Viewer + scan_map_view (viridis, NaN honesty, colorbar) + Reference Monitor quick win | Jonathan data-truth review |
| D4 | Bias dashboard + Camera (Live/Single/Stop) + honest Laser (+ Paul driver beats w/ manuals) | Mary safety review |
| D5 | Monitor, Analysis, Calibration, Motor, Scope | capture harness + council spot-checks |
| D6 | Command palette, toast discipline, detached-window polish | UX review |

Fix-it tickets already open: QML MetricTile text overflow (shipped strip),
Calibration missing header, stage_view hardcoded dark theme.

## 10. Modularity charter (Abel's 8 rules — the anti-jungle)

One StateMachine = lifecycle truth (phases are derived labels) · read-only
viewmodel per panel (no controller refs, no command surface) · commands
one-way: panel intent → ScanCoordinator → controller; danger always through
DangerGate with real numbers · one worker→GUI bridge (queued signals only) ·
danger is a seam, not a widget (new danger UIs implement the gate) ·
terminal states preserve data + re-arm (writer flushed, hardware safe,
last_run_path published) · pre-flight synchronous and fail-closed before
RUNNING · no new threads/timers/locks — everything rides the 1 Hz cadence
and existing marshaled signals.

## 11. RATIFIED by Kaya (2026-07-12)

1. **Arm-envelope model**: one two-step latch authorizes a bounded,
   enumerated envelope (executor re-validates every live danger against it;
   no per-BiasStep modals) — vs keeping per-step confirms as
   defense-in-depth. Council recommends the envelope model; Mary must review
   the implementation either way.
2. **Slow-control excursion policy**: temp/humidity/leakage excursions are
   currently recorded but never alarmed mid-run. Should WARN pause and
   ALARM abort? (Safety policy, not UI.)

BOTH RATIFIED 2026-07-12: envelope model adopted (HV approved once per run,
executor re-validates against the armed envelope); WARN = safe-hold pause
(HV held, motion stopped, operator prompt), ALARM = fail-safe abort,
UNAVAILABLE counts as WARN. Mary review mandatory on both implementations.
