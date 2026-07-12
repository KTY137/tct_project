# Codex Second Opinion: Cockpit Design Language v2

Date: 2026-07-12
Scope: `artifacts_claude/tct_cockpit_design_v2.html` plus the audit notes.

## Verdict

The draft is pointed in the right direction: one composed shell, map-first
scan posture, semantic danger, mono numerals, and detachable panels treated as
product behavior. The weak spots are not taste issues. They are places where
the artifact still risks translating into a prettier version of old desktop
Qt: too many framed surfaces, too much color vocabulary, and safety controls
that look polished before they are ergonomically settled.

## Five Weakest Decisions

1. The palette still has more than one accent.
   The draft says "one accent", but the source defines blue, cyan, green, and
   amber as strong glowing voices. Cyan appears in the brand mark, heat map,
   code text, and soft background, so blue no longer owns the cockpit.
   Better: keep blue as the only accent for selected/navigation/primary work.
   Use neutral ink plus icon/LED state for connected/idle. Reserve amber for
   armed/caution and red for HV/abort only. Move cyan into plot colormaps only,
   with no UI chrome role.

2. The artifact is still a design page wrapped around an app mockup.
   The hero, nav, and explanatory cards make the page persuasive, but they hide
   the hardest production question: what does the first app viewport look like
   with no marketing frame around it?
   Better: produce a shell-only artifact next: app rail, pill shelf, status
   strip, active panel, and one detached panel. No hero, no prose cards. Use
   contact sheets as the deliverable, not a landing page.

3. "Every panel, same language" currently means many small screens in boxes.
   The mockups use `.screen`, `.figure`, `.field`, `.tile`, and `.dangerzone`
   so heavily that the visual lesson may become card-inside-card Qt. The audit
   explicitly calls out nested borders as the current failure mode.
   Better: define panel recipes instead of panel cards: a hero region, a
   compact inspector, a command row, and a danger well. Let panels share rhythm
   and type scale, not identical framed containers.

4. Danger hierarchy is visually loud but semantically leaky.
   Red is used for `Move absolute...`, generic "Arm & start scan", and any
   `.btn.danger`, while the laser output gets an amber danger well and green ON
   button. This weakens the hard rule that red means HV or abort.
   Better: split command classes in the component vocabulary. `AbortButton`
   is instant red. `HvArmCommand` is red gated. `MotionCommand` is amber gated.
   `LaserOutputCommand` is amber/neutral with explicit output state. A scan
   start that ramps HV may contain an HV sub-confirmation, but the primary scan
   action should not borrow abort styling.

5. The status strip is readable, but it is too dominant and too uniform.
   Five large MetricTiles across the top makes every value feel equally
   important. In real runs, HV live, run state, ETA, current point, and last
   charge should not compete at the same visual volume.
   Better: make run state and HV the two high-salience zones. Put progress and
   ETA in a combined tile, position as a compact readout, and last charge near
   the waveform/map context. Staleness is a good idea; apply it by hierarchy,
   not only opacity.

## Hold-To-Arm Verdict

Hold-to-arm is a good visual prototype, not yet a bench-ready interaction.
For mouse use it is deliberate and cancelable. For gloves, touchpads, or
one-handed operation while managing probes, a 900 ms hold can be unreliable:
small pointer drift cancels it, pressure timing is ambiguous, and the fallback
"press twice" exists only under reduced-motion logic in the draft.

Use it only as one input path for HV arming, not as the safety model. The
production DangerGate should support:

- a large target with clear consequence text and live target values;
- keyboard parity for Space/Enter without relying on animation;
- a visible armed latch with timeout and explicit disarm;
- instant single-action abort/off controls that never require holding;
- separate gates for HV, motion, and laser output.

If Kaya wants glove-friendly operation, a two-step "Arm" then "Execute" latch
with a 3-5 second timeout is more reliable than a pure press-and-hold.

## Missing Ideas

1. Command palette and quick switcher.
   The cockpit has many expert workflows: open run, jump to panel, start dry
   run, export current plot, focus camera, show device debug. A command palette
   can expose safe commands with hardware state awareness and make the polished
   shell efficient without adding visible chrome.

2. Toast, alarm, and event discipline.
   The draft shows chips and live state but not notification rules. Define
   which events become transient toasts, which become persistent alarm rows,
   and which only enter the log. HV trips, aborts, failed device connects, and
   completed exports need different lifetimes.

3. Detached panel aesthetics and contracts.
   Detach is named, but detached windows need their own language: compact rail,
   synchronized theme, panel identity, live/simulated state, redock affordance,
   and status inheritance. Multi-monitor lab use will look unfinished if
   detached panels fall back to generic window chrome.

## Typography Nitpick

The principle is right: system sans for interface text, mono numerals for
instrument values. The execution is too display-heavy and over-tracked.

- App rail and buttons: system text 13 px, weight 560-600, line-height 18 px.
- Panel titles: system text 17-20 px, weight 650. Avoid hero-scale titles in
  operational panels.
- Body/helper text: system text 12.5-13 px, weight 400-450, line-height 18 px.
- Metric labels: mono 10 px, weight 600, tracking 0.08em max, uppercase only
  for labels that behave like instrument engraving.
- Primary metric values: mono 24-28 px, weight 600, tabular numerals,
  letter-spacing 0. Compact panel values: 17-20 px.
- Units: system or mono 11-12 px, weight 500, muted; do not let units compete
  with values.

Also remove negative letter spacing from body and mono value rules. It looks
slick in a web artifact, but in a PySide/Windows cockpit it will make dense
technical labels feel cramped.
