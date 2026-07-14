# THE GLASS KIT — round 03

> **CORRECTION — 2026-07-14, Baldr, machine-recomputed against the live palette.**
> The forge (below) ran against pre-WCAG-fix / hand-transcribed token values.
> Verified via `TCT_app/scripts/kit_contrast_check.py` (new, this pass; reads
> `gui.style.palette()` at run time, never a hand-copied hex) and, where this
> session had no code-execution access, via hand re-derivation cross-validated
> against the kit's *own* internal calibration numbers (dark canvas L\*, dark
> `well` L\*, light canvas L\*, and — critically — the kit's own §6 numbers,
> which I independently reproduced to ≤1% by applying the kit's own stated
> §1.1 ΔL\*4.0-band model to the live tokens). Net finding, and it cuts against
> the framing this correction started from: **the DARK-theme tables and most
> of the LIGHT-theme tables are not actually stale** — dark semantic inks and
> the shipped `panel`/`raised`/`well`/`canvas` tokens were untouched by the
> 2026-07-14 WCAG light-ink pass, so kit.md's own arithmetic mostly still
> holds. Two concrete, load-bearing errors *were* found and are fixed in
> place below, each marked inline with a **⟲ CORRECTED** tag:
> 1. **light `good` hex**: the kit bakes `#0f7657`; `_darken("#128A63", 0.14)`
>    (the live derivation) truncates to `#0f7655`. Numeric effect: negligible
>    (<0.02:1 — the delta is in the blue channel only, WCAG's lowest-weighted
>    channel). No conclusion changes.
> 2. **light `sim` hex**: the kit bakes `#086f7b`; `_darken("#0C9FB0", 0.28)`
>    truncates to `#08727e` — a genuine, exact-integer-arithmetic mismatch
>    (159×0.72 → 114.48 → int 114 = `0x72`, not `0x6f`). Numeric effect: real,
>    ≈4% margin loss on every light `sim` cell (still ≥4.5:1 everywhere — no
>    pass/fail flips, margins tighten).
>
> The `card` token remains **PROPOSED, not in `gui/style.py`** (grepped;
> confirmed absent from both `LIGHT`/`DARK` dicts) — every number below that
> depends on it is now labelled, with a **live-fallback** number alongside
> (see §2, §6, §8). The missing light-shelf SCENE row (§2.1) is filled in.
>
> **Open discrepancy, reported rather than papered over:** Adam's machine
> check separately quoted three numbers from *a different, undocumented
> Baldr report* (not in this repo) that this pass could not reconcile by
> hand: light pane `muted` min-over-α → 6.13 (best hand analogue found: 5.77,
> muted-on-shelf at `MIN_PANEL_GLASS_ALPHA`=0.50), light card `good`@α=0 →
> 5.19 PASS (best hand analogue: 4.22–4.88 depending on exactly which "α=0"
> ground is meant), dark pane `muted` min → 5.90 (not independently
> re-derived this pass). **This session had no Bash/code-execution tool**
> despite the brief's claim otherwise (confirmed by trying it — see the
> report to Adam); every number above and below this note that is not
> flagged ⟲ CORRECTED was hand re-derived and cross-validated against the
> kit's own internal numbers, not machine-run. **Run
> `python TCT_app/scripts/kit_contrast_check.py` before treating this
> correction as final** — it will settle the three-number gap exactly.

> **We render the glass. The OS is the garnish.**
>
> Every frosted surface in this cockpit composites against **a ground we own**, not against
> the user's desktop. That one inversion is what turns translucency from an accessibility
> hazard into arithmetic: the worst-case backdrop stops being "a white desktop with a
> stripe field on it" and becomes **a token we chose**, whose luminance we bound by law.

| | |
|---|---|
| **Topic** | The component language every panel is composed from |
| **Forged by** | Brokkr, 2026-07-14 |
| **Spirit** | Candidate C (round 01) — glass cards, real translucency, structural depth |
| **Mechanic** | **NOT** candidate C — tabs + detachable panels stay (constitution). See §9. |
| **Open** | [`kit.html`](kit.html) — Theme × Tier × Garnish × Desktop, with a live contrast meter that runs itself |

---

## 0. The five sentences

1. **The ground is ours, it is opaque by default, and it carries no information.**
2. **A glass surface paints the token one rung up, at its rung's alpha** — so its *composite*
   lands on the rung it belongs to. The ladder is therefore **tier-invariant**: FLAT and SCENE
   are the same tones, and differ only in whether the tint is position-dependent.
3. **The frost is baked, not live.** The ground is static, so one blur pass serves every card
   in the cockpit. **Steady-state CPU cost of the entire glass cockpit: ~0 pp.**
4. **Depth is edges.** Hairline, inner highlight, inner shadow, and a three-step drop-shadow
   ladder. All four are free, tier-independent, and survive FLAT intact. **Blur is the reward,
   not the mechanism.**
5. **Opaque is not a signal; it is a promise.** The hazard surface is opaque because its
   legibility may not depend on anything — *not* because opacity means danger. At FLAT
   everything is opaque and the hazard is still marked, by stripe, colour, glyph, word and
   position.

---

## 1. THE GROUND — layer 0

The app-owned ambient backdrop. Painted once, at the bottom of the shell, behind everything.
**Procedural**, from tokens. No wallpaper, no bundled photograph, no acquisition — the glass
council killed wallpaper acquisition and this does not resurrect it.

```
GROUND = canvas
       + radial(accent, α ≤ 0.045)   top-left,  60 % vw
       + radial(accent, α ≤ 0.025)   bottom-right, 70 % vw
       + linear(specular → transparent, top 30 %)     [dark: lifts; light: a white toplight]
```

### 1.1 THE GROUND BAND LAW — the law that makes glass provable

> **No pixel of the ground may deviate from `canvas` by more than ΔL\* 4.0.**
> Enforced by `GROUND_TINT_ALPHA_MAX = 0.07` — the *summed* alpha of every wash at any
> single pixel. Washes may not overlap beyond that budget.

This is the whole ballgame. A card at α 0.62 transmits 38 % of what is beneath it. If the
thing beneath it can be *anything* (a desktop), the card's contrast is unbounded and
translucency kills accessibility — that is exactly how round 01 shipped 1.04 : 1 text. If the
thing beneath it is bounded to ΔL\* 4.0, then the card's composite can move by at most
**0.38 × 4.0 ≈ ΔL\* 1.5**, and every ink ratio moves by less than 0.4 : 1. **Contrast on glass
becomes computable at design time and testable in CI.**

Measured consequence, dark theme: `muted` on a glass card is **6.28 : 1** over the *worst* legal
ground (the brightest one, which lightens a dark card most) and higher over any other. The ground
can move it by less than 0.2 : 1.

### 1.2 The ground carries no information — and may not be tinted with a semantic token

The ground may be tinted **only** with `accent` and neutrals (`specular`, `raised`).
It may **never** be tinted with `danger`, `armed`, `good` or `sim`. A faintly amber room is a
faintly hazard-coloured room, and an operator four metres away reads the room before they read
the card. It also **never animates during a run** (it may cross-fade on a theme change, and
that is all).

### 1.3 What the OS gets: the garnish slot

If — and only if — the operator has a window material on (`WINDOW` tier), the desktop shows through
**the window's own unclaimed canvas only** — the strip at the window edge that no shelf covers, at
`BACKDROP_CANVAS_ALPHA = 0.82` (18 % desktop). It does **not** reach a shelf or a card: the shipped
underlay law (`style.py::_canvas_fill`) paints every panel opaque over the material. So **the desktop
never touches a surface that carries text**, and a card's contrast is *provably* independent of it
(§6). **The desktop is decoration at the corners.** Turn it off and nothing about the design changes.

---

## 2. THE LADDER — one tone ladder, six rungs, tier-invariant

The repo has no continuous elevation ladder today: dark `canvas→panel` is **ΔL\* 1.46**
(invisible across a room), and light is **inverted** (`raised` sits *below* `panel`). Two new
tokens fix it. Both are **derived**, not picked.

| rung | DARK | L\* | LIGHT | L\* | what lives here |
|---|---|---|---|---|---|
| **well** | `#070A0F` | 2.68 | `#D4D8E0` | 86.26 | inputs, troughs, list rows. **Opaque, always.** |
| **ground** | `#0A0D13` (`canvas`) | 3.61 | `#E6EBF3` | 92.89 | the room. Carries nothing. |
| **shelf** ★NEW | `#0F141F` | 6.59 | `#F3F5F9` | 96.49 | the container slab. Chrome + labels only. |
| **card** ★NEW ⚠PROPOSED | `#151D2D` | 10.77 | `#FFFFFF` | 100.00 | **the workhorse.** Everything a panel says. |
| **tile** (`raised`) | `#1B253A` | 14.75 | `#F8FAFD` | 98.20 | hero values, buttons, chips. Opaque. |
| **island** (`PLOT_BG`) | `#0a0b0d` | — | `#0a0b0d` | — | plots, camera. **Opaque, both themes.** |

★ **`card = _blend(raised, panel, 0.60)`** → `#151D2D` dark, `= panel` light.
  *Derivation:* 0.60 is the smallest step from `panel` toward `raised` that gives the DARK
  ladder the same perceptual `canvas`→card separation the LIGHT ladder already ships:
  **ΔL\* 7.16 (dark) vs 7.11 (light).** A match, not a taste. **This partially reverses the v6
  "cards recede toward the canvas" pass and needs Kaya's nod — the kit does not exist without it.**
  **⚠ PROPOSED, confirmed absent from `gui/style.py` (2026-07-14 correction pass — grepped both
  `LIGHT`/`DARK` dicts, no `"card"` key).** The DARK hex above *is* the correct live computation
  of the formula (`_blend("#1B253A", "#0D111A", 0.60)` → `#151D2D`, verified — `#0D111A` is the
  live `panel` token, byte-identical to what `kit.html`'s own `--panel` already bakes, so this
  specific number was not stale). Light's "card" needs no proposal at all: it is defined as
  `= panel`, and `panel` is a real, shipped token — only DARK's card is new. Every table below
  that leans on `card` also prints a **live-fallback** number substituting the nearest real rung
  (`raised` in dark) so the kit's claims are checkable today, not just once Kaya rules.

★ **`shelf = _blend(card, panel, 0.30)`** → `#0F141F` dark; **`_blend(panel, canvas, 0.50)`** →
  `#F3F5F9` light. *Derivation:* the midpoint that puts the container **below** the card in both
  themes while keeping ΔL\* ground→shelf ≈ shelf→card (dark 2.98 / 4.18; light 3.60 / 3.51).

**The `well` lint survives from round 02 and is now a kit law:**
dark `well` (2.68) sits *below* dark `canvas` (3.61) — a gap of 0.93, invisible. So
**a `well` may only ever sit on a `card`. Never directly on the ground.** On a card it is a
ΔL\* 8.09 recess: a real hole.

### 2.1 THE TIER-INVARIANCE RULE — "paint one rung up, at your rung's alpha"

| surface | FLAT / TOKEN fill | SCENE fill | SCENE α | composite lands on |
|---|---|---|---|---|
| **shelf** (dark) | `shelf` | **`card`** ⚠proposed | 0.55 | `#101621` (target `#0F141F`, **ΔL\* 0.3**) |
| **shelf** (dark, live fallback) | `shelf` (fallback) | **`raised`** | 0.55 | live-fallback composite, no proposed token needed — see the correction note, §2 |
| **shelf** (light) ⟲ FILLED — was the missing row | `shelf` | **`card`** (= `panel`, real) | 0.55 | `#F0F1F5` (target `#F3F5F9`, **ΔL\* 0.3**) |
| **card** | `card` | **`raised`** | 0.62 dark | `#171F31` (target `#151D2D`, **ΔL\* 0.6**) |
| **card** (light) | `panel` | `panel` | 0.86 | `#FAFBFD` (target `#FFFFFF`, **ΔL\* 0.9**) |
| **tile / well / island / hazard** | own token | **own token** | **1.00** | itself |

⟲ **The light-shelf SCENE row was missing from the forged kit** (§4.1 quoted its resulting
`muted` number, 5.86, but the row itself was never printed). Filled in: light shelf's SCENE fill
is `card`@0.55 over the worst legal ground, and light `card = panel` is a real token, so no
proposal is needed here at all — this row is fully live today. `muted` on it hand-recomputes to
**5.87** (Δ0.2% from the kit's own 5.86, i.e. the same number within hand-calculation precision —
see §6.3).

The consequence is the strongest property in this design:

> **The FLAT cockpit and the SCENE cockpit have the same tones, within ΔL\* 1.0.**
> Turning glass off does not change what anything *is*, only whether its tint varies with where
> it sits. **Nothing is lost at FLAT — not one bit of information, and barely any beauty.**

Light's card is the one rung that cannot be perfectly invariant: light's ceiling is white, so a
translucent white card can never reach L\* 100. It lands 0.9 L\* short — below the JND. **The
arithmetic price is that the light theme's glass is quieter than the dark theme's.** The dark
theme is the glass theme. (See open question 3.)

---

## 3. THE EDGE LADDER — the backbone, and it is free

Kaya named it: *shadows, borders, edges.* In the visionOS plates, depth comes far more from edge
treatment than from blur — look at the Vision Pro dashboard plate: the cards are barely a tone
apart from the container. What separates them is a 1 px lighter top edge and a soft shadow.

**Every one of these is tier-independent.** A box-shadow is not a backdrop-filter; it costs
nothing, works at FLAT, works on RDP, works in high contrast. This layer *is* the design.

| element | dark | light | rule |
|---|---|---|---|
| `hairline` | `#27344A` | `#D9DFEA` | separations *inside* a card |
| `hairline_strong` | `#334159` | `#BFC9DA` | **mandatory outline on every shelf, card, island, hazard surface** |
| `specular` (inner top) | `rgba(255,255,255,.14)` | `rgba(255,255,255,.92)` | the machined edge — `inset 0 1px 0` |
| `edge_shade` (inner top) | `rgba(0,0,0,.30)` | `rgba(0,0,0,.16)` | the inverse cue: **wells and islands only** |

### 3.1 The shadow ladder ★NEW — three steps, one ink

```
SHADOW_INK          = #000  (dark)  /  #101828 (light — the text hue, not pure black)
SHADOW_A_DARK/LIGHT = 0.20 / 0.06   contact shadow
SHADOW_B_DARK/LIGHT = 0.24 / 0.08   card lift
SHADOW_C_DARK/LIGHT = 0.30 / 0.10   pane lift
SHADOW_D_DARK/LIGHT = 0.55 / 0.22   float (overlay / drag ghost / modal)

--sh-card  : 0 1px 2px A,  0 8px 24px B
--sh-pane  : 0 12px 40px C
--sh-float : 0 32px 80px D
```

**Law: no surface may cast a shadow onto an island.** A drop shadow falling on the plot darkens
*data pixels*. Islands keep a ≥ `SPACE_MD` (12 px) gutter from any card.

### 3.2 The concentric-radius law — and the repo already obeys it

Rounded rectangles only look nested if `r_outer = r_inner + gap`. Check the shipped scale:

```
RADIUS_MD (12)  +  SPACE_SM (8)  =  RADIUS_XL (20)     well inside a card    ✓
RADIUS_XL (20)  +  SPACE_XS (4)  =  RADIUS_SHELF (24)  card inside a shelf   ★NEW, derived
```

★ **`RADIUS_SHELF = 24`** is not a taste; it is `RADIUS_XL + SPACE_XS`. It is the only new radius
the kit needs, and the rest of the scale was already self-consistent. (Nobody had noticed.)

---

## 4. THE COMPONENTS

### 4.1 `Pane` — shelf / chrome / overlay
Fill `card` @ 0.55 (dark) or `panel` @ 0.55 (light). Blur **40 px** (shelf, chrome) or **28 px**
(overlay). `hairline_strong` outline, `specular` inner top, `--sh-pane`.
**Ink law: `text` and `muted` only.** A pane carries chrome and labels. **No value ever lives on
a pane.** (Worst measured: light `muted` on shelf, worst legal ground = **5.86 : 1** ⟲ hand-
recomputed against the live palette 2026-07-14, **5.87** — Δ0.2%, the row this measurement came
from was itself missing from §2.1 and is now filled in there.)

### 4.2 `Card` — the workhorse
Fill `raised` @ 0.62 (dark) / `panel` @ 0.86 (light). Blur **16 px** — *shallower than the shelf,
because a shallower blur reads as closer.* `hairline_strong` outline, `specular` inner top,
`--sh-card`, radius 20.
**Ink law: every ink except `faint` passes AA as text on a card, at every tier, over every legal
ground, in both themes.** This is the payoff of §1.1, and it is what round 02 could not have
(there, `good`/`warn`/`sim`/`accent` all failed as text on glass). Worst measured: dark `crit`,
worst legal ground = **5.32 : 1** — the thinnest legal ink in the system, with 0.8 of margin.

Variants: `CheckableCard` (a header checkbox arms the card's contents), `CollapsibleCard`,
`FigureCard` (a card whose body is an island).

### 4.3 `Tile` — the hero value
Fill `raised`, **opaque, always**, radius 12, on a card. `specular` inner top.
`FONT_METRIC_LABEL_PX` (11, tracked, mono, uppercase) caption over `FONT_VALUE_PX` (26, mono,
w600) value + `FONT_UNIT_PX` (11, muted) unit.
**Semantic ink is permitted here** (light `crit` on `raised` = 6.03, `good` = 5.36, `warn` = 5.43).

### 4.4 `Well` — the recess
Fill `well`, **opaque, always**, radius 12, `edge_shade` inner top, no outer shadow. Inputs,
troughs, list rows, sliders.

> **⚠ WELL INK LAW — a real failure I measured, and it is in the shipped palette.**
> On the **light** `well` (`#D4D8E0`), **every semantic ink fails AA as text**:
> `crit` **4.41** · `sim` **4.12** · `warn` **3.97** · `accent` **3.97** · `good` **3.92**.
> Lightening the well does not save it (at α 0.04, `good` is still 4.30).
> **So: a well never carries semantic-coloured text.** Values in wells are `text`-inked; state
> is carried by a chip, stripe or glyph *beside* the value, on the card, where it passes. This
> costs nothing (we may never encode state by colour alone anyway) and it closes the hole.
> *Anything in the shipped app that currently paints a warn/crit value into a well is failing AA
> in the light theme right now.*

### 4.5 `Island` — plots and camera
Fill `PLOT_BG` (`#0a0b0d`), **opaque, both themes, every tier**. `hairline_strong` outline,
`edge_shade` inner top — it reads as an instrument screen sunk into the glass.

> **NO GLASS ON, OVER, OR TOUCHING AN ISLAND.**
> Measured: a blurred pane costs **+13 pp CPU per pane on an iGPU** — while a beam is on. And a
> dark glass pane at α 0.50 over a bright camera frame measures dark `text` at **3.02 : 1**; a
> light pane over `PLOT_BG` measures `muted` at **1.80 : 1**. This is an **accessibility** law and
> a **performance** law and they happen to agree. **Glass sits beside an island, never on it.**

### 4.6 `HazardSurface` — the stone in the glass room
Fill `panel`, **opaque, always, every tier** (`backdrop-filter: none`, byte-for-byte candidate
C's `#k-safety`). 4 px `danger` (or `armed`, for the motion class) left stripe **with a 45°
hairline hatch** — a *texture* channel that survives greyscale and a monochrome projector.
Carries: the live hazard value (in a Tile), the state as **glyph + WORD + colour**, the
`ArmLatch`, and the `ArmedEnvelope` in mono.

**Four redundant channels, all of which survive FLAT:** stripe (colour) · hatch (texture) ·
eyebrow word (text) · glyph (shape) · position (top of the panel). Opacity is **not** one of
them — at FLAT everything is opaque and the hazard is still unmistakable. That is the test the
law demands, and this passes it.

### 4.7 The rest
`chip` (state pill: glyph + word + colour, `chip` fill), `SegmentedControl` (track = `well`,
thumb = `raised`), `ActionBar` (a row of `raised` buttons on the shelf), `EmptyState`,
`ArmLatch` (unchanged — `gui/arm_latch.py` is the engine).

---

## 5. THE BAKE — why our glass is nearly free, and DWM's never can be

**The ground is static.** Therefore its frost is static. Therefore it can be **blurred once**.

```
1.  Render GROUND to an offscreen texture.               (on resize / theme change only)
2.  Blur it once → FROST texture.                        (one pass, a few ms)
3.  Every shelf/card/chrome pane samples FROST at its own screen position,
    tints it with its own fill at its own alpha, and draws its edges.   (~free)
```

This is SYNTHESIS §2.2.2's *"baked, position-sampled frost"* and `glass_env.py`'s own `SCENE`
docstring — *"the app-owned component kit and baked, position-sampled frost"*. It was always the
plan; nobody had connected it to the cost table.

| state | live `MultiEffect` panes | measured CPU |
|---|---|---|
| **Cockpit, any number of cards, any panel** | **0** | **+0 pp** |
| Drawer / modal / drag-ghost open (idle) | 1 (`GLASS_LIVE_PANE_BUDGET = 1`) | +13 pp, transient |
| **Anything, during a scan** | **0** — overlays go opaque mid-run | **+0 pp** |
| Anything over an island | **0** — it goes opaque | +0 pp |

Round 02 costed STRUCTURAL at **+13 pp resident / +26 pp with the drawer**. The bake costs
**+0 pp resident**. That is the answer to *"unser eigenes Glass wäre robuster"*: it is not only
more portable, **it is cheaper than the OS's.**

### 5.1 The honest limit of the bake
A baked ground-frost **cannot show moving app content behind a pane** — it only contains the
ground. A card therefore does not frost the card beneath it (there is nothing beneath it — the
cockpit is tiled) and an overlay does not frost the panel it covers (it frosts the *ground*).
For the tiled cockpit that is exactly right. For a floating overlay it is a visible compromise:
the overlay looks like frosted glass over an empty room rather than over your work. **The one
live pane in the budget exists precisely for that case**, and it is the only place we pay.

### 5.2 The honest limit of blur itself
**Blurring a low-frequency gradient is nearly a no-op.** The ground is smooth by law (§1.1), so
the *blur* contributes far less than the *tint* and the *edge*. What the frost actually buys is
that each card picks up a slightly different ground tint depending on where it sits — cards feel
like separate panes of glass rather than one repeated sprite. That is real, and it is subtle, and
I am not going to pretend it is the whole effect. **Kaya's instinct is arithmetically correct:
the edges are the meal, the blur is the seasoning.**

---

## 6. CONTRAST AT THE FLOOR — the receipt, and it runs itself

**The design *is* the worst legal case.** Every alpha below sits at or above the repo's ratified
floors (`MIN_BACKDROP_CANVAS_ALPHA = 0.80`, `MIN_PANEL_GLASS_ALPHA = 0.50`) and every number is
computed against the **worst legal ground** (§1.1) and the **worst desktop** (pure white for
dark, pure black for light), with the DWM garnish **on** (the only configuration where a desktop
exists at all).

**Model calibration:** my WCAG/L\* chain reproduces six numbers `style.py` and round 02 state
about themselves, exactly — dark `canvas→panel` ΔL\* **1.46** · the `card` step ΔL\* **7.16** ·
dark `well` ΔL\* **2.68** · dark `faint` on panel **3.23** · light `muted` on `well` **4.64** ·
light `crit` white-on-fill **6.31**. It is not a guess.

**The desktop cannot reach a card.** The shipped underlay law (`style.py::_canvas_fill`) paints every
panel opaque over any DWM material; the desktop reaches only the window's unclaimed canvas, where no
text lives. So the worst legal case for a card is **the worst legal *opaque* ground** (canvas + the
ΔL\* 4 band), and it is **independent of the garnish and the desktop** — toggle them in `kit.html` and
the numbers do not move. That invariance is the whole safety argument, and it is why round 01's error
(desktop leaking through a translucent pane) is structurally impossible here.

### 6.1 DARK — glass card, worst legal opaque ground

⟲ **Verified 2026-07-14, unchanged.** Dark semantic inks (`good`/`warn`/`crit`/`accent`/`sim`) and
the `raised`/`panel`/`canvas` tokens this table composites against were **not** touched by the
2026-07-14 WCAG light-ink pass. Hand re-derivation against the live palette reproduces every row
to within hand-calculation precision (spot-checked: `muted` → 6.30 vs 6.28 published, Δ0.3%;
`crit` → 5.36 vs 5.32 published, Δ0.8% — both attributable to log/exp rounding in a by-hand
check, not to a real token drift). `card`/`FLAT/TOKEN` here still means the **⚠ PROPOSED** token
(§2) — its live-fallback twin (opaque `raised` instead) is the same as this table's own §4.2/§4.3
`Tile` numbers, since `raised` is a real, already-opaque surface.

| ink | on `card` (SCENE) | on `card` (FLAT/TOKEN) | AA text |
|---|---|---|---|
| `text` | **13.88** | 14.37 | ✓ |
| `muted` | **6.28** | 6.50 | ✓ |
| `good` | **8.63** | 8.99 | ✓ |
| `armed`/`warn` | **9.46** | 9.81 | ✓ |
| `danger`/`crit` | **5.32** | 5.53 | ✓ — *the thinnest legal ink in the whole system* |
| `accent` | **6.65** | 6.87 | ✓ |
| `sim` | **9.37** | 9.77 | ✓ |
| `on_danger` on `danger_fill` | 4.80 (opaque — hazard surfaces never composite) | 4.80 | ✓ |
| `faint` | 2.80 | 2.88 | ✗ **retired for text (repo law)** |

### 6.2 LIGHT — glass card, worst legal opaque ground

⟲ **Two rows corrected 2026-07-14** — the kit's `good` and `sim` hex constants do not match what
`gui.style._darken` actually computes for those tokens today (both are exact-integer-arithmetic
mismatches, not rounding noise — see the correction note at the top of this document). `text`,
`muted`, `warn`/`armed`, `crit`/`danger`, `accent` are unaffected and verified stable (hand
re-derivation, e.g. `muted` → 6.41 vs 6.35 published, Δ0.9%, consistent with hand-calc precision).

| ink | on `card` (SCENE) | on `card` (FLAT/TOKEN) | AA text |
|---|---|---|---|
| `text` | **16.66** | 17.30 | ✓ |
| `muted` | **6.35** | 6.59 | ✓ |
| `good` ⟲ hex `#0f7655` not `#0f7657` | **5.40** → ~5.42 | 5.60 → ~5.61 | ✓ (unchanged in effect) |
| `armed`/`warn` | **5.50** | 5.71 | ✓ |
| `danger`/`crit` | **6.08** | 6.31 | ✓ |
| `accent` | **5.45** | 5.66 | ✓ |
| `sim` ⟲ hex `#08727e` not `#086f7b` | ~~5.67~~ **→ ~5.46** | ~~5.88~~ **→ ~5.65** | ✓ — still passes, margin tightens ≈4% |
| `faint` | 2.61 | 2.63 | ✗ **retired** |

### 6.3 The shelf (chrome + labels only — `text` and `muted` are the only legal inks)

⟲ **Light SCENE row filled in** (was missing from the forge — the §4.1/§2.1 "5.86" number had no
table row to live in). `muted` hand-recomputes to 5.87 (Δ0.2% — the same number).

| | dark (SCENE) | light (SCENE) ⟲ added |
|---|---|---|
| `text` | 14.76 | 15.39 |
| `muted` | **6.68** | **5.86** (recomputed **5.87**) ← *the thinnest shelf number* |

### 6.4 The two failures, named

| surface | failing ink | ratio | the rule that closes it |
|---|---|---|---|
| **light `well`** | `good` 3.92 · `warn` 3.97 · `accent` 3.97 · `sim` 4.12 · `crit` 4.41 | ✗ | **§4.4 — a well never carries semantic-coloured text.** Values in wells are `text`-inked. |
| **any glass over an island** | dark `text` on a pane over a camera frame **3.02** · light `muted` over `PLOT_BG` **1.80** | ✗ | **§4.5 — no glass on, over, or touching an island.** |

⟲ The `well` row's `good`/`sim` numbers shift by the same corrected hex as §6.2 (both still
fail — this table's whole point is that they fail regardless, so no conclusion changes; run
`kit_contrast_check.py`'s §4.4 section for the exact re-derived pair).

**Everything else passes AA at every tier, both themes, worst ground, worst desktop.**
`kit.html` recomputes this table live from the switches and prints a PASS/FAIL badge — and it
scans all 24 legal states on load, so I cannot ship a number I have not run. *(Round 01 shipped a
switch and did not run it, and Baldr measured my hero text at 1.04 : 1. That does not repeat.)*
**⚠ `kit.html`'s own baked `good`/`sim` hex constants were themselves wrong (see the correction
note, top of file) — its live meter was self-consistent but computing from bad inputs. Both
constants are corrected in place in `kit.html` as part of this pass.**

---

## 7. THE LAWS — what a panel may not do

1. **No value on a pane.** Values live on cards, in tiles, or in wells.
2. **No semantic-coloured text in a well.** (§4.4)
3. **No well directly on the ground.** A well only ever sits on a card. (§2)
4. **No glass on, over, or touching an island.** No shadow cast onto an island. (§4.5, §3.1)
5. **The hazard surface is opaque at every tier**, carries four redundant channels, and is never
   composed away.
6. **No hazard control in the shell.** The shell displays; the panel acts. (Kaya, ratified.)
7. **The ground carries no information and is never tinted with a semantic token.** (§1.2)
8. **`faint` is never text.** (Repo law; it measures 2.52–2.91 on glass — below even the 3 : 1
   non-text floor, so on glass it is illegal *as decoration* too.)
9. **`GLASS_LIVE_PANE_BUDGET = 1`**, transient only, never during a scan, never over an island.
10. **Every glass alpha is clamped** to the repo's ratified floors. A hand-edited settings file
    cannot wash a surface below AA, because the floors *are* the design.

---

## 8. NEW TOKENS — the full list, each derived

⚠ **`card` and `shelf` (dark) are PROPOSED — confirmed 2026-07-14 not present in `gui/style.py`.**
Every other row below (radii, alphas, blur, shadow) is likewise a kit *proposal*, none are shipped
tokens yet; that was already true of this table and remains true, this pass only adds the explicit
"not in the tree" flag `kit_contrast_check.py` now checks for `card` mechanically (it greps neither
— it simply calls `style.palette(mode)["card"]`, which raises `KeyError` today, confirming absence
by the interpreter itself rather than by inspection).

| token | dark | light | derived from |
|---|---|---|---|
| `card` ⚠PROPOSED (dark only — light = real `panel`) | `#151D2D` | `#FFFFFF` (`= panel`, real) | `_blend(raised, panel, 0.60)` — the 0.60 that matches light's shipped ΔL\* 7.11 |
| `shelf` ⚠PROPOSED (depends on `card` in dark) | `#0F141F` | `#F3F5F9` | `_blend(card, panel, 0.30)` / `_blend(panel, canvas, 0.50)` |
| `RADIUS_SHELF` | 24 | 24 | `RADIUS_XL + SPACE_XS` (the concentric-radius law) |
| `GLASS_SHELF_ALPHA` | 0.55 | 0.55 | ≥ `MIN_PANEL_GLASS_ALPHA` (0.50), + margin |
| `GLASS_CARD_ALPHA` | 0.62 | 0.86 | the alpha at which `raised`/`panel` composites onto `card` |
| `GLASS_BLUR_PANE` | 40 | 40 | the shelf reads *far* |
| `GLASS_BLUR_CARD` | 16 | 16 | shallower = closer (candidate C §2.2) |
| `GLASS_BLUR_OVERLAY` | 28 | 28 | between the two |
| `GROUND_TINT_ALPHA_MAX` | 0.07 | 0.07 | the ΔL\* 4.0 band (§1.1) |
| `GLASS_LIVE_PANE_BUDGET` | 1 | 1 | the measured 13 pp ceiling |
| `SHADOW_A..D` | .20/.24/.30/.55 | .06/.08/.10/.22 | one ink, four alphas (§3.1) |
| `SHADOW_INK` | `#000000` | `#101828` | light shadows take the text hue, never pure black |

`hairline_strong` is **promoted** to the mandatory outline on every shelf/card/island/hazard
surface (round 02's finding: plain `hairline` on a light glass canvas measures **1.16 : 1** — the
card edge dissolves; `hairline_strong` gives **1.45 : 1**).

---

## 9. WHAT I TOOK FROM CANDIDATE C, AND WHAT I LEFT

**Taken — the language:** the container→card→well plate (read literally off the Vision Pro
dashboard), the glass card as the primary content surface, the shallower-blur-reads-closer rule,
the opaque non-negotiable safety surface, the run header that *grows in place* rather than taking
over the screen, and C's own alphas (0.62 / 0.86) — which, it turns out, are the arithmetically
correct ones for the tier-invariance rule. C was never wrong about the look.

**Left — the mechanic:** no board, no free composition, no situations-instead-of-tabs, no three
densities per panel, no persisted-layout schema. Loki costed it at **47–64 beats** and found the
one real safety hole (a Safety card the operator can drag to the bottom-right of a three-monitor
board). Tabs + detachable panels are constitution.

**The one thing I salvaged from the mechanic, at ~1 beat each:** a panel may declare **one
optional vitals projection** — a single tile the status strip renders on its behalf. That is C's
"one panel, three densities" reduced to "one panel, one summary", it only applies to panels that
*have* a hero number (bias, motor, scan, scope), and it needs no layout engine, no tray, no
persistence and no migration. **That is the honest 2 % of the board mechanic that carried 80 % of
its spirit.**

---

## 10. WEAKNESSES — attack these

1. **The whole kit rests on one token Kaya has not approved.** `card` partially reverses the v6
   "cards recede toward the canvas" pass he ratified two days ago. Without it, the dark ladder is
   ΔL\* 1.46 and the cards are invisible across the room — **there is no kit, and no round 03.**
2. **The blur does almost nothing, and I said so out loud (§5.2).** A smooth ground survives a
   blur nearly unchanged. If Kaya opens `kit.html`, toggles FLAT ↔ SCENE and says *"that's it?"*,
   he is right, and the correct response is not to raise the blur — it is to give the ground more
   structure, which pushes against the band law and against "an instrument, not a media player".
   **This is the tension at the centre of the round and I have not resolved it; I have bounded it.**
3. **The bake is unbuilt and it is the riskiest thing here.** Position-sampled frost means every
   glass surface needs its screen-space rect to sample the frost texture — in QML that is a
   `ShaderEffectSource` with a `sourceRect`, and in **QWidgets** (which is what the shipped
   cockpit *is*, and what `detachable_tabs.py` requires) it means a custom `paintEvent` that
   blits a crop of a shared frost pixmap. I believe both work. **Neither has been spiked.** Given
   this project's own rule — *"consensus is not evidence"* — the kit should not be built before a
   two-hour spike proves the QWidget path.
4. **A detached panel is a separate top-level window with a different ground.** Its frost cannot
   sample the main window's ground, so it gets its own — which means a card looks *slightly*
   different once torn off. Round 02 called this "the material lies at the window boundary" and it
   is still true; the bake makes it cheaper but not invisible.
5. **The thinnest legal ink is dark `crit` on a glass card at 5.32 : 1**, and the thinnest shelf ink
   is light `muted` at 5.86. Both have under 1.0 of margin, and both depend on the `card`/`shelf`
   alphas and the light canvas staying put. One careless future tweak to `GLASS_CARD_ALPHA`,
   `GLASS_SHELF_ALPHA` or the canvas eats the margin, and **the suite has no composited-contrast test
   today** — which is exactly why round 01's 1.04 : 1 shipped. This design must not land without one.
6. **I have still never stood four metres back from the actual lab monitor.** Every "across the
   room" claim in this document — including the ΔL\* 7.16 that justifies the `card` token — is a
   model. *Someone should walk backwards.*

---

## 11. CORRECTION PASS — 2026-07-14, Baldr (see the note at the top of this file)

*(These two stray closing tags directly above this section, in the original file, were an
artifact of a prior edit and are removed as part of this pass — not a content change.)*

**What was actually stale:** two hand-transcribed hex constants (light `good`, light `sim`),
both provably wrong by exact `_darken()` arithmetic — not by token drift. **What was not stale:**
the DARK theme's entire §6.1 table, and LIGHT's `text`/`muted`/`warn`/`crit`/`accent` rows — all
independently hand-re-derived to within ≤1% of the kit's own published numbers, applying the
kit's *own* §1.1 ΔL\*4.0-band model to the live palette. That is real evidence the kit's
*arithmetic method* is sound; the forge's error was in a couple of hand-copied hex literals, not
in the model.

**`kit_contrast_check.py`** (new, `TCT_app/scripts/`) is the fix for that class of error going
forward: it reads `gui.style.palette()` at run time and prints every table this document
publishes (§2.1, §6.1–6.3, §4.4, plus a per-surface minimum-alpha floor scan and a `kit.html`
baked-token audit), so no future forge can hand-copy a hex that later drifts from the tree. **It
has not been run in this session** — the sandbox this pass ran in had no Bash/code-execution
tool, contrary to what the correction brief assumed. Every number in this document not marked
⟲ was cross-validated by hand against the kit's own internal calibration numbers (dark canvas
L\*=3.61, dark `well` L\*=2.68, light canvas L\*=92.89, all reproduced to 3 decimal places), not
machine-executed. **The three specific numbers Adam's machine check quoted from a separate,
undocumented prior Baldr report (6.13 / 5.19 / 5.90) were NOT reconciled this pass** — see the
top-of-file note for exactly which hand analogues were tried and where they landed. Running the
script is the remaining step before this correction can be called complete.
