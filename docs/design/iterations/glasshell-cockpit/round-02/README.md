# GlassShell cockpit — Round 02

| | |
|---|---|
| **Topic** | The GlassShell cockpit — **the depth question**: does the material carry hierarchy, or does tone? |
| **Forged by** | Brokkr, 2026-07-14 |
| **Status** | Awaiting the attack pass (Loki / Baldr / Mary), then Kaya |
| **Inherited as law** (not re-litigated) | B killed · C killed as winner, ladder salvaged · A survives revised (spine, phase rail, vitals) · **armed rail rejected** · danger is **panel-owned** (RATIFIED) · detachable panels are **permanent**, `detachable_tabs.py` stays the engine (RATIFIED) |
| **Measured ground truth used** | `bbe3b10` — Qt Quick has **no** backdrop-filter; DWM frosts the window over the desktop for free; in-scene `MultiEffect` frosts panes over **app content** at 59–60 fps for **~+13 pp CPU each**; no glass on hot-path islands; no glass on hazard surfaces |

## Open these

| Candidate | Philosophy | Files |
|---|---|---|
| **STRUCTURAL** · The Overlay Cockpit | Depth means **transience**. A surface is glass exactly when it is temporarily above your work — and never otherwise. | [`candidate-structural.html`](candidate-structural.html) · [`.md`](candidate-structural.md) |
| **AMBIENT** · The Tiled Cockpit | The **window** is glass; the **instrument** is not. Structure is carried by tone, border and elevation — the three things that survive RDP. | [`candidate-ambient.html`](candidate-ambient.html) · [`.md`](candidate-ambient.md) |

Both HTML files are self-contained and double-clickable, and each carries **Theme × Tier × Desktop**
switches plus a **live contrast meter** that composites the current state and prints PASS/FAIL.
**Round 01 shipped that switch and did not run it. These run themselves.** Each also carries one
switch that is really an argument:

- **STRUCTURAL → "Underlay probe"** slides a plot under the spine. Watch the spine refuse to frost a
  hot-path island and pop to opaque. That is the mechanism *and* its flicker weakness, in one click.
- **AMBIENT → "Ladder probe"** swaps the card body back to the **shipped `panel`** token. In dark, at
  FLAT, **the cards disappear.** That is why the new `card` token exists.

---

## 1. The fork, and why it is real

The measurement made the depth question concrete, and it also made it **non-cosmetic**:

> **An in-scene frosted pane is only *meaningful* if it OVERLAPS other app content.** A `MultiEffect`
> pane over the window's alpha hole is pixel-identical to no pane at all — measured.

So "structural glass" is not "glass cards". Glass cards tile; tiles overlap nothing; their frost is a
**no-op**. Structural glass *forces an overlapping cockpit*. Which means:

| | **STRUCTURAL** | **AMBIENT** |
|---|---|---|
| **Layout** | **Overlapping.** The spine floats over the workspace; the drawer covers the panels. | **Tiled.** The spine is a grid track; the drawer is a grid track. Nothing ever overlaps. |
| **Where the glass is** | 2 in-scene panes (spine, drawer) + the DWM window | **The DWM window. That is all.** |
| **`MultiEffect` panes** | 1 resident, 2 with the drawer out, capped at 2 | **0. Ever. Any window, any tier.** |
| **CPU** | **+13 pp** resident · **+26 pp** with the drawer out | **+0 pp** |
| **Text on glass** | Yes — restricted to `text` + `muted` by law (§3) | **Never. Not one pixel.** |
| **What FLAT costs it** | Its entire idea. At FLAT, STRUCTURAL *is* AMBIENT. | **Nothing.** FLAT is the design with the gutters filled in. |
| **Depth language exceptions** | **4** (detached panel, device manager, trigger dialog, ROI dialog — all separate HWNDs, none can frost the parent) | **0** (its language is about *windows*; all four *are* windows) |
| **Code beyond re-layout** | Content-aware underlay + convert 2 dialogs to in-window overlays | The new `card` token |
| **Opening the drawer mid-run** | Covers a panel. Nothing resizes. | **Re-lays the workspace. The plot resizes, mid-run.** |

They cannot be merged by a stylesheet: one *overlaps* and the other *cannot*, and each pays for that
in a different currency (CPU vs. spatial disruption).

---

## 2. THE FINDING THAT SHOULD DECIDE THE ROUND

I measured the "three-tone FLAT ladder" that round 01 salvaged from candidate C — the one thing in
the round that was praised for surviving the tier it promised to survive.

> ### In the dark theme — the default theme — it does not exist.

| ladder step | DARK (shipped) | LIGHT (shipped) |
|---|---|---|
| `canvas` → `panel` (container → card) | **1.03 : 1** · **ΔL\* 1.47** | 1.20 : 1 · ΔL\* 7.11 |
| `panel` → `well` (card → well) | 1.05 : 1 · ΔL\* 2.39 | 1.43 : 1 · ΔL\* 13.75 |
| `canvas` → `well` | 1.02 : 1 · **ΔL\* 0.92** | 1.19 : 1 · ΔL\* 6.64 |

The v6 glass pass pulled `panel` down toward `canvas` **deliberately** ("cards recede toward the
canvas", `style.py:475`). The side effect nobody measured: **at FLAT, in dark, a card sits 1.5 ΔL\*
above the floor it lies on — below the practical JND. Across the room, the cards are invisible.**
C's ladder survives the flat tier only as a 1 px border. Both candidates in this round need this
fixed; **AMBIENT dies without it.**

(WCAG ratios are the wrong ruler down there — the `+0.05` offset flattens the whole near-black
region. Surface separation is reported in **ΔL\***; ink is still reported in WCAG ratios.)

### The one new token — named and derived, per the rules

```
NEW TOKEN  `card`   (the card body of the three-tone ladder)

    DARK   card = _blend(raised, panel, 0.60)   ->  #151D2D
    LIGHT  card = panel                          ->  #FFFFFF   (light already works)
```

**Derivation, not taste:** 0.60 is the smallest step from `panel` toward `raised` that gives the DARK
ladder *the same perceptual separation from `canvas` that the LIGHT ladder already has* —
**ΔL\* 7.16 (dark) vs ΔL\* 7.11 (light)**. It is a *match*. Every ink stays AA on it: `text` 14.37,
`muted` 6.50, `crit` 5.53, `good` 8.99, `warn` 9.81, `accent` 6.87, `sim` 9.77 (`faint` 2.88 — still
retired, exactly as the repo says).

**One promotion, no new value:** `hairline_strong` becomes the **mandatory card outline**. Plain
`hairline` against a light glass canvas over a white desktop measures **1.16 : 1** — the card edge
dissolves. `hairline_strong` gives **1.45 : 1 / ΔL\* 13.6**.

**One non-colour constant (STRUCTURAL only):** `GLASS_PANE_BUDGET = 2` — max live `MultiEffect` panes
per top-level window. Derived from the measured 13 pp: a 26 pp ceiling.

**A lint that falls straight out of the numbers:** dark `well` (ΔL\* 2.68) is indistinguishable from
dark `canvas` (ΔL\* 3.60) — a gap of **0.92**. So: **a `well` may only ever sit on a `card`, never
directly on the `canvas`.**

---

## 3. CONTRAST AT THE FLOOR — the receipt I owed you

### 3.1 First: the law I broke in round 01, stated so it cannot be broken again

Baldr composited my declared alphas and got **dark card text 2.30 : 1**, `muted` **1.04 : 1**. He was
**right about my HTML and wrong about the app** — and the difference is not the alpha. It is a
missing *layer*.

> ### THE DOUBLE-UNDERLAY LAW
> **A translucent pane may NEVER composite directly against the compositor.** There is always a canvas
> layer at ≥ `MIN_BACKDROP_CANVAS_ALPHA` between the desktop and any pane.
> Desktop leakage through a pane at the floors = `(1 − 0.80) × (1 − 0.50)` = **10 %**.

| model | pane over a white desktop | dark `text` | dark `muted` |
|---|---|---|---|
| round-01 (mine, broken): pane @ .42 straight onto the desktop — **58 % leakage** | `#999b9f` | **2.30** ✗ | **1.04** ✗ |
| round-02 (the law): pane @ .50 over canvas @ .80 — **10 % leakage** | `#24272E` | **12.75** ✓ | **5.77** ✓ |

Both alphas now sit **at the ratified floors** (`MIN_BACKDROP_CANVAS_ALPHA = 0.80`,
`MIN_PANEL_GLASS_ALPHA = 0.50`) in both candidates and in both HTML files — **the design *is* the
worst legal case**, so there is no gap left between what I show and what I measure.

### 3.2 The table — token × tier × worst-case desktop × both themes

**Model calibration:** my WCAG chain reproduces **six numbers `style.py` states about itself** exactly
— dark `faint` 3.23 · light `muted` worst-opaque 4.64 · light `crit` white-on-fill 6.31 · dark
`danger_fill` white 4.80 · light `accent` white-on-accent 5.25 · and the repo's own *"4.90 : 1 at the
0.80/0.50 worst corner"*. It is not a guess.

#### TIER = FLAT / TOKEN / WINDOW — every information surface is **opaque**
Identical in **both** candidates, both themes, and **independent of the desktop**. This is AMBIENT's
entire table, at every tier.

| ink | on `card` — DARK | on `card` — LIGHT | AA text |
|---|---|---|---|
| `text` | 14.37 | 17.41 | ✓ |
| `muted` | 6.50 | 6.63 | ✓ |
| `good` | 8.99 | 5.60 | ✓ |
| `warn` | 9.81 | 5.68 | ✓ |
| `crit` | 5.53 | 6.31 | ✓ |
| `accent` | 6.87 | 5.25 | ✓ |
| `sim` | 9.77 | 5.88 | ✓ |
| `on_danger` on `danger_fill` | 4.80 | 6.31 | ✓ |
| `faint` | 2.88 | 2.72 | ✗ — retired for text (repo law) |

#### TIER = SCENE — a level-4 glass pane at the floors (**STRUCTURAL only**)
`pane = 0.50·panel over (0.80·bg over desktop)`

| ink | DARK / **white** desk | DARK / black desk | LIGHT / white desk | LIGHT / **black** desk | verdict |
|---|---|---|---|---|---|
| `text` | **12.75** ✓ | 16.51 ✓ | 16.22 ✓ | **12.86** ✓ | text OK |
| `muted` | **5.77** ✓ | 7.47 ✓ | 6.18 ✓ | **4.90** ✓ | text OK (the repo's certified floor) |
| `crit` | **4.91** ✓ | 6.35 ✓ | 5.88 ✓ | **4.66** ✓ | text OK, thin |
| `good` | 7.97 ✓ | 10.6 ✓ | 5.22 ✓ | **4.14** ✗ | **NON-TEXT ONLY** |
| `warn` | 8.70 ✓ | 11.3 ✓ | 5.29 ✓ | **4.19** ✗ | **NON-TEXT ONLY** |
| `sim` | 8.66 ✓ | 11.3 ✓ | 5.48 ✓ | **4.34** ✗ | **NON-TEXT ONLY** |
| `accent` | 6.09 ✓ | 7.90 ✓ | 4.90 ✓ | **3.88** ✗ | **NON-TEXT ONLY** |
| `faint` | 2.55 ✗ | 3.31 ✗ | 2.54 ✗ | **2.01** ✗ | **FORBIDDEN, even as decoration** |

**Baldr was right, and it is worse than he said.** The repo's scrim contract only ever certified
`muted`. At the floor, **light theme over a dark desktop**, four more tokens fail as text: `good`,
`warn`, `sim`, `accent`. And `faint` lands on exactly the ~2.0 : 1 he measured — below even the 3 : 1
non-text floor, so it is illegal on glass *as a graphic*, not merely as text.

**The law STRUCTURAL takes from this** (and it is what `style.py:856` already says out loud):
> A glass pane carries **chrome and labels only**. Permitted ink: `text` (≥ 12.75) and `muted`
> (≥ 4.90). Semantic colour on glass is **non-text only** (lamp/bar, ≥ 3 : 1). **Every value lives in
> an opaque `well` or on an opaque `card`.**

#### Two more numbers that are load-bearing

| case | result | consequence |
|---|---|---|
| dark glass pane @ .50 over a **bright camera frame** | dark `text` = **3.02 : 1** ✗ | a pane over an unbounded island is an AA failure, not just a CPU bill |
| light glass pane @ .50 over `PLOT_BG` | `muted` = **1.80 : 1** ✗ | "no glass on hot-path islands" is an **accessibility** law as well as a performance one |
| **card edge** on the glass canvas, light theme / white desktop | `hairline` **1.16 : 1** ✗ · `hairline_strong` **1.45 : 1** | why `hairline_strong` is promoted; AMBIENT's thinnest moment |

---

## 4. Two bugs both candidates fix (independent of who wins)

1. **The vitals strip clips.** `MOTION` runs off the right edge at the app's default width with **no
   scroll affordance at all**. Fixed in both by a **6-slot grid** (`minmax(156px, 1fr)`) that reflows
   6 → 3×2 → 2×3 and **never scrolls and never elides**: overflow is made *unrepresentable* rather
   than scrollable. 6 × 156 + 5 × 8 + spine 76 + margins 32 = **1084 px** ≪ the 1536 px default.
   Hazard cells (HV / LEAKAGE / COMPLIANCE / MOTION) never degrade; SCAN drops its caption first.
2. **Leakage current and compliance were dropped.** They exist in the classic strip
   (`tct_gui.py` `_chip_bias_i`, `_chip_bias_comp`) and never made it into `ScanStatusStrip.qml`,
   which ships four tiles (State / HV / Progress / Position). **Both are back**, as hazard vitals,
   with a 60 s leakage sparkline and the compliance limit.

Also in both: the strip **displays** hazard and can never trigger it (no shell-side control anywhere,
no mediator); every hazard surface is **opaque at every tier**; state is **never colour alone**
(glyph + word + colour); the device lamps move out of the vitals row into the spine footer, where
they belong — cramming a 6-device census into the vitals grid is what made the strip overflow in the
first place.

---

## 5. What the attack pass should hit hardest

**STRUCTURAL**
1. **At FLAT it *is* AMBIENT — and FLAT is most of the fleet** (RDP, high contrast, Linux without
   OpenGL, Win10, software rasterizer, operator override). Its entire idea is unavailable exactly
   where the lab probably lives. Worse: **AMBIENT does STRUCTURAL's fallback job better, because
   AMBIENT designed for it first.** Ask whether the lab's normal mode is RDP; if it is, STRUCTURAL is
   a 13 pp tax on a look nobody sees.
2. **The material lies at the window boundary.** Four surfaces (detached panel, device manager,
   trigger dialog, ROI dialog) are separate HWNDs and **cannot** frost the parent — measured. A depth
   language with four exceptions is not a language. Two of them can only be fixed by rewriting
   `scope_panel.py` / `camera_panel.py` into in-window overlays. **Cost this.**
3. **The frosted spine sits beside a live trace, in an operator's periphery, while a beam is on.**
   I have zero evidence it is not distracting. I bet an ergonomic claim I cannot support.
4. **The content-aware underlay has a flicker mode** and makes the material's appearance depend on
   layout. It carries no *hazard* information (the law), but it does carry *some* information — and
   an operator told "the material means nothing" will still notice it and wonder.
5. **There is no composited-contrast test in the suite.** The first person to put a green "READY"
   label on the spine breaks AA (4.14) and nothing catches it. STRUCTURAL must not ship without that
   test.

**AMBIENT**
1. **It refuses the brief's own reference.** Kaya asked to "match the design_assets like visionOS
   more"; the defining move of all eight plates is *content seen through chrome*, and AMBIENT does not
   do it anywhere. A reasonable person can say I did not do the job.
2. **ΔL\* 7.16 is a *matched* step, not a *tested* one.** I matched it to light's existing 7.11
   because that ships and nobody complained — an argument from silence. **Nobody has stood four metres
   back from the actual lab monitor.** The across-the-room constraint is the one this candidate rests
   on and the one it has not tested. *Someone should walk backwards.*
3. **It quietly indicts the whole glass programme.** If SCENE/WINDOW buys nothing but a faintly
   transparent 8 px gutter, then `glass_env.py`, `backdrop.py`, the event spine and the five-rung
   ladder exist to deliver an effect the operator never notices. That may be the true answer — but it
   should be said out loud, not discovered in six weeks.
4. **"Nothing overlaps" is a functional loss.** The drawer *pushes*: opening the inspector re-lays the
   workspace and **resizes the plot mid-run**. On a 1536×864 screen there is no room for a 284 px
   drawer *and* two panels — something gives, every time.
5. **`hairline_strong` at 1.45 : 1** is all that holds a white card together on a near-white glass
   canvas. There is no WCAG floor for a container edge, so no test will catch it; only eyes will.

**Both**
- **The new `card` token changes the shipped dark palette**, and dark is the default. Every
  screenshot and the frozen v6 look shift. If Kaya rejects it: STRUCTURAL degrades to AMBIENT, but
  **AMBIENT-without-`card` degrades to nothing** (a 1.03 : 1 ladder and no glass).
- **I have not verified the ΔL\* JND claim against a real monitor at a real distance.** Every "across
  the room" statement in this round is a model, not an observation.

---

## 6. Open questions for Kaya

1. **Is the lab's normal operating mode local, or RDP?** This single fact decides the round. RDP caps
   at `TOKEN` — STRUCTURAL's glass never renders there, and it becomes a 13 pp CPU tax for a look the
   operator never sees. *(Round 01's highest-value question was "does the operator watch several
   things at once"; shipped code answered it. This is round 02's equivalent, and the repo cannot
   answer it.)*
2. **May I change the shipped dark palette?** The new `card` token is not optional for either
   candidate, and it moves the v6 "cards recede toward the canvas" look that was ratified two days
   ago. It is a deliberate partial reversal of the v6 glass pass — **in the dark theme only, and only
   for the card body.** Yes or no decides whether this round has a winner at all.
3. **Will you accept a floating drawer that covers a panel, or must nothing ever overlap?** This is
   the fork, restated as an operational question. A covering drawer keeps the plot's geometry stable
   mid-run; a pushing drawer never hides anything. Both are defensible; only you know which one an
   operator would curse at 2 a.m.
4. **Is 13 pp of an integrated GPU acceptable *during a scan*?** `plan_transition` already defers
   *upgrades* to scan-idle, so the frost never *appears* mid-run — but a frost already running keeps
   costing through the whole run. If the answer is no, STRUCTURAL is dead on the spot.
5. **May STRUCTURAL rewrite `_TriggerDialog` and `_ROIDialog` into in-window overlays?** Without it,
   STRUCTURAL's depth language has four exceptions and is arguably not a language. With it, the round
   costs two panel rewrites and changes their modality behaviour.
6. **Should a composited-contrast test land regardless of the winner?** The suite has none today —
   which is precisely why round 01's alphas shipped, and why `good`/`warn`/`sim`/`accent`-on-glass
   have never been checked by anything but Baldr and me, by hand.
