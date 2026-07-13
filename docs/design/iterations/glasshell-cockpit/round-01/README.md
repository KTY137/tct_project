# GlassShell cockpit — Round 01

| | |
|---|---|
| **Topic** | The GlassShell cockpit: information architecture + panel layout + the visionOS-grade look |
| **Commission** | Kaya, verbatim: *"iterate our design, our panel layout, everything to better user accessibility and match the design_assets like VisionOS more."* |
| **Forged by** | Brokkr (design forge), 2026-07-14 |
| **Status** | Awaiting the attack pass (Loki / Baldr / Mary), then Kaya's eyes |
| **Ground truth read** | `artifacts_claude/ui_onscreen_20260713T202649Z/` (real screenshots), `design_assets/` (8 reference plates), `TCT_app/gui/style.py` + `qml_theme.py` (tokens), `gui/arm_latch.py` + `qt_danger_gate.py` (danger machinery), `docs/design/glass_council/SYNTHESIS.md` (incl. the 2026-07-14 measured-correction banner) |

## Open these

| Candidate | Philosophy | Files |
|---|---|---|
| **A · INSTRUMENT** | The cockpit is an instrument face. Depth is **structural** — four fixed layers, each meaning something, none ever moving. | [`candidate-instrument.html`](candidate-instrument.html) · [`.md`](candidate-instrument.md) |
| **B · STAGE** | You are doing exactly one thing. Show **that**, full-bleed; summon the chrome; make danger a **ceremony that takes the stage away**. | [`candidate-stage.html`](candidate-stage.html) · [`.md`](candidate-stage.md) |
| **C · BOARD** | The app stops guessing the workflow. It ships **situations**, not tabs, and the operator composes the cockpit — except the one card they cannot evict. | [`candidate-board.html`](candidate-board.html) · [`.md`](candidate-board.md) |

Every HTML file is self-contained and double-clickable, and carries three switches:
**Theme** (light/dark) · **Tier** (real glass / token / flat) · **Backdrop** (desk / lab light /
**worst case**). The tier switch is the important one — it is how you check the hard constraint
that nothing is lost when the glass degrades. The worst-case backdrop is a 100 %-contrast
black/white stripe field: the pathological case for translucency.

## What materially differs

These are not three stylesheets. They disagree about four things, and the disagreements are the
point:

| | **A · Instrument** | **B · Stage** | **C · Board** |
|---|---|---|---|
| **How much chrome survives** | One 88 px vitals bar + a 78 px phase rail. Fixed, permanent. | A 38 px ribbon. Everything else is summoned. | A floating rail capsule. The board *is* the app. |
| **Dashboard vs one task** | Dashboard: panels are cards on a stage, vitals always resident. | One task, full-bleed; the other eleven are 15 px stubs. | User-composed dashboard; three densities per panel. |
| **Is depth structural or ambient?** | **Structural** — 4 layers that carry meaning. | **Ambient** — 2 levels; glass says "this is temporarily on top". | **Structural** — a strict 3-step ladder (container → card → well). |
| **Where danger lives** | An **always-visible armed rail**, same three pixels forever. Safety by position. | A **summoned ceremony** — envelope + 3 acknowledgements + 2 s hold. Nothing dangerous is one click from rest. | A **pinned, non-evictable card**. Movable, never removable. |
| **What a running scan does** | Fills the Scan vital; the rest of the cockpit is unchanged. | **Takes over** — the run becomes the stage. | **Grows a header in place** — the operator's layout is preserved, running or not. |

If you can imagine reconciling two of them by editing CSS, I forged one candidate twice. I do not
believe you can: A's armed rail and B's ceremony are opposite answers to *"may a dangerous control
be visible at rest?"*, and C's answer to *"who decides the layout?"* is one neither A nor B can
give.

## Two things I found in the ground truth that are not design opinions

Both are visible in the committed screenshots and both are **bugs the current cockpit has today**,
independent of which candidate wins:

1. **The status island clips.** In `acrylic_glass_A_dark.png` and `acrylic_lablight_A_light.png`
   the `MOTION` group runs off the right edge — "Motion" is cut in half at the app's own default
   width.
2. **Light mode is broken, and the token set has a live WCAG failure.**
   - In the light screenshot the jog-arrow glyphs vanish (white-on-white), the "Test connection"
     plug icon disappears, and the plot titles ghost out grey-on-grey.
   - Measured: light `crit` `#DE434B` gives **4.19:1** on `panel` and **3.50:1** on `canvas` —
     **both fail WCAG AA for text**, and white ink on a `#DE434B` fill is also only 4.19:1. Dark
     `faint` `#5B657A` is **3.2:1** on `panel` — legal only as large text or non-text, but used
     today for small captions.
   - **Proposed fix (all three candidates depend on it):** a new token
     `crit_ink_light = #C22A33` (= `WARN_RED_LIGHT` darkened ≈ 22 %) → **5.7:1** on panel,
     **4.8:1** on canvas, **5.7:1** for white ink on the fill. `crit` survives as the graphic/
     non-text token.

## The one law all three share

**The hazard surface is tier-invariant.** Every dangerous control — A's armed rail, B's ceremony
slab, C's Safety card — is painted with the opaque `panel` **token**, never a material, at every
tier. On RDP, in high contrast, on the full glass build, the danger surface is byte-identical.
Glass is a finish; it never touches the part of the UI that can hurt someone.

This is the design-side reading of the constitutional rule that *the material carries no hazard
information*. The rule says glass must not **encode** hazard. I go one step further and say glass
must not **touch** it — because a hazard control whose appearance varies by environment corrodes
the muscle memory that makes it safe, even when it encodes nothing.

## What the attack pass should hit hardest

- **A:** the permanent chrome tax with no answer for the boring-vitals case; the five vitals are a
  guess; three dangerous controls permanently visible and clickable (fatal if the lab has a touch
  monitor); 12 labels do not fit a 78 px rail.
- **B:** the whole thing rests on *"the operator does one thing at a time"* — an assumption I never
  verified. If a slow HV ramp requires watching leakage **and** the trace **and** the ramp at once,
  this candidate obstructs safety monitoring and is dead. Also: the 38 px ribbon arguably **fails
  the across-the-room constraint outright**.
- **C:** cost (a new subsystem, not a rearrangement); "three densities per panel" is uncosted and
  probably false for 3–4 panels; the Safety card is non-evictable but *not* pinned to the first
  screenful — so it is less safe than A while claiming parity; and the candidate arguably
  **abdicates** the composition problem back to the user.

## Open questions for Kaya

1. **Does a TCT operator watch several things at once, or one?** This single fact decides between
   B and (A, C), and I could not answer it from the repo. It is the highest-value question in the
   round.
2. **Are the five vitals right?** I chose Bias / Leakage / Stage / Laser / Scan by reasoning about
   hazard. Is leakage current a *vital* (resident) or a *diagnostic* (checked deliberately)?
   Should temp/humidity be up there instead?
3. **Is there a touchscreen in the lab?** If yes, candidate A's always-clickable armed rail has a
   sleeve-brush failure mode and needs rework.
4. **How much migration budget does this get?** A and B are re-arrangements; C is a new subsystem.
   That may decide it before any design argument does.
5. **May I fix the light-mode `crit` token now** (it is a live AA failure), independently of which
   candidate wins?
