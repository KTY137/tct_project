# PANEL — SCOPE (the live-plot panel)

> **What it proves:** glass sits *beside* a hot-path island, never on it. The trace is an opaque
> instrument screen sunk into the glass; the controls are glass cards around it. There is a hard,
> measured, non-negotiable gutter between the two.

Open [`panel-scope.html`](panel-scope.html). There is a switch labelled **"glass the trace"** — it is
disabled, and the label says why. That disabled switch is the whole point of this panel.

---

## 1. The panel today (ground truth, `gui/oscilloscope_panel.py`, `dark/03_oscilloscope.png`)

A big **LIVE TRACE** pyqtgraph plot on the left (~65 % width), and a right rail of controls: a
`SCOPE OFFLINE` chip, a `TRIG` well, two **channel cards** (CH1 REFERENCE / CH2 DUT with colour dot,
role combo, live readout), a `DUT ANALYSIS` block (Amplitude / Charge / Timing sub-tabs), and a
`MEASUREMENTS` table. Along the bottom: Single / Live / Avg / Cursor / Export CSV / Test / List VISA.

## 2. The design — the island is the hero, the glass is its frame

### 2.1 The split
Panel = one **shelf**. On it: the **island** (the trace) on the left, and a right rail of **glass
cards** for the controls. The island is a `FigureCard` whose body is the plot — but the body itself is
**opaque `PLOT_BG` (`#0a0b0d`), every tier**, with a `hairline_strong` outline and an `edge_shade`
inner top so it reads as an instrument screen recessed into the glass. It looks like the visionOS
"screen embedded in a frosted frame" without a single pixel of glass on the data.

### 2.2 THE GUTTER LAW, applied
> No glass surface may overlap, overhang, or cast a shadow onto the island. A ≥ `SPACE_MD` (12 px)
> gutter separates the island from every card.

This is not conservatism — it is two measured facts pointing the same way:
- A blurred pane over a bright camera/trace frame measures dark `text` at **3.02 : 1** — an AA failure,
  because the backdrop is now unbounded (an island is not a band-limited ground).
- A live blur over the trace costs **+13 pp CPU on an iGPU, while a beam is on.**

So the trace has a moat. The channel cards, the trigger well, the measurements table all live to the
right of it, on glass, never over it.

### 2.3 The channel cards
CH1 / CH2 become proper **glass cards** with the axis colour as a left rail (REFERENCE / DUT), the
role as a `SegmentedControl`, and the live readout in an **opaque well** (a value — never on glass).
The colour dot stays, but role is *also* the word "REFERENCE"/"DUT" and *also* the rail position — state
is never colour alone.

### 2.4 The DUT analysis + measurements
A glass card with `SegmentedControl` (Amplitude / Charge / Timing) over a **well** holding the readout
rows. The measurements table is a card whose rows are `well`-toned zebra stripes; each value is
`text`-inked (a measurement is a value, so it lives in a well and takes no semantic colour — §4.4 of the
kit closes the light-theme hole here automatically).

### 2.5 The action bar
Single / Live / Avg / Cursor / Export / Test sit in an `ActionBar` of `raised` buttons docked to the
shelf below the island — off the glass-vs-island boundary entirely.

## 3. Justification

**Problem solved.** Today's scope is dense and grey; the trace and its controls read as one undivided
slab of dark widgets. This design makes the trace unmistakably *the instrument* — a black screen in a
lit frame — and demotes the controls to the frame around it. That is exactly the visionOS reference
move (screen-in-frame), achieved without ever risking the one surface that must never blur.

**Alternatives considered within this candidate.**
- *A faint glass vignette at the trace's edge for "depth".* Rejected outright: any alpha over the plot
  is the 3.02 : 1 failure and the 13 pp tax. The `edge_shade` inner-top cue gives the recessed look for
  free, opaquely.
- *Float the channel cards partially over the trace's dead corners (like the visionOS controls
  overlapping the video).* Rejected: "dead corner" is a lie the moment the trace autoscales into it.
  The gutter is unconditional.
- *One combined channel card instead of two.* Rejected: two DUT/REFERENCE roles want two rails; merging
  them loses the axis-colour identity that makes the trace legible at a glance.

**Safety implications.** The trace is a hot-path island: opaque, every tier, never blurred, never
overlapped. During a scan the panel's glass never contends with acquisition (the bake is static; the
one live pane in the budget is forbidden here anyway). No hazard on this panel, but the discipline that
keeps the trace legible across the room is the same law that protects the beam-on cockpit.

**Operational implications.** No new state. Re-skin of the existing widget tree. The pyqtgraph plot is
unchanged; only its container gains the island framing.

**Why now.** This panel is the reason "no glass on islands" is a kit law and not a footnote. Building it
proves the language can produce a beautiful live-plot panel while touching zero data pixels.

## 4. Weaknesses (attack these)

1. **The 12 px gutter costs real estate on a 1536-wide screen, permanently.** The trace is the thing an
   operator stares at; every pixel of moat is a pixel not showing signal. On a small window the gutter +
   the right rail may squeeze the trace below a usable width, and I have not defined a responsive rule
   for when the rail should collapse under the island instead of beside it.
2. **The "screen in a frame" look is only as good as the frame's contrast, and the frame is glass.** In
   the light theme, a near-white glass card beside a near-black island is a huge contrast jump — which
   is dramatic, but it also means the light-theme scope has the most jarring internal contrast of any
   panel. Some operators will find it harsh. I am asserting "dramatic = good" without evidence.
3. **The channel cards' live readout updates continuously — and it lives in a well on a glass card.**
   The well is opaque so the *value* is fine, but the well sits on a card that, at SCENE, is
   re-sampling the ground frost. The frost is static so there is no per-frame cost, but if a future
   build ever makes the ground animate (it must not — §1.2), this becomes a live-blur-beside-a-fast-
   readout problem. The safety of this panel depends on a ground law being honoured elsewhere.
4. **I kept two channel cards, but the scope supports more channels on some backends.** Three or four
   channel cards plus the DUT analysis card plus measurements will overflow the right rail, and I have
   not designed the scroll/collapse behaviour for the N-channel case — the same "it clips at default
   width" bug round 02 found in the vitals strip could reappear here.
</content>
