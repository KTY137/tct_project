# Candidate AMBIENT — "The Tiled Cockpit"

> **Philosophy, one line:** *The **window** is glass. The **instrument** is not.
> Structure is carried by tone, border and elevation — the three things that survive RDP.*

| | |
|---|---|
| **Round** | 02 · GlassShell cockpit |
| **Forged by** | Brokkr, 2026-07-14 |
| **Optimizes for** | Legibility that does not move. The cockpit at the FLAT tier and the cockpit at the SCENE tier are **the same picture** — same tones, same layout, same contrast, to the pixel. Only the gutter changes. |
| **Deliberately sacrifices** | The visionOS signature. You will never see your work through your chrome. Depth is subtle, and a reviewer looking for "wow" will not find it here. |
| **Files** | [`candidate-ambient.html`](candidate-ambient.html) |

---

## 0. The argument

Three measured facts, and the design falls out of them.

1. **DWM frosts the window over the desktop, live, and it is free.** (Spike finding 2.)
2. **An in-scene `MultiEffect` costs ~13 pp of CPU on an integrated GPU** — per pane, per frame,
   including while a scan is running. (Spike finding 4.)
3. **Translucency is where contrast dies.** At the ratified floors, in light theme over a dark
   desktop, a glass pane fails AA-as-text for `good` (4.14), `warn` (4.19), `sim` (4.34), `accent`
   (3.88) and `faint` (2.01). Only `text`, `muted` and `crit` survive. (My table, §4 — and it
   confirms Baldr.)

AMBIENT's answer: **take fact 1, refuse fact 2, and make fact 3 irrelevant by never putting a single
pixel of text on glass.**

> **The AMBIENT invariant, and it is the whole candidate:**
> **Zero `MultiEffect` panes. Ever. In any window. At any tier.**
> The only translucent surface in the entire application is the window's own unclaimed background —
> the gutters between cards, the margin at the edge, the rounded corners. **Nothing that carries
> information ever sits on it.**

The consequence is the thing worth having: **the FLAT tier is not a degradation, it is the design
with the gutters filled in.** No layout shifts. No tone shifts. No contrast shifts. Nothing is lost
when the glass goes, because nothing was ever *on* the glass. An operator who moves from the lab
workstation to an RDP session sees the same instrument, and the glass tier stops being a thing they
have to think about.

---

## 1. Depth without translucency — the three-tone ladder, made to actually work

This is the ladder round 01 salvaged from candidate C. **I measured it, and in the dark theme it does
not exist.**

| ladder step | DARK (shipped tokens) | LIGHT (shipped tokens) |
|---|---|---|
| `canvas` → `panel` (container → card) | **1.03 : 1** · ΔL\* **1.47** | 1.20 : 1 · ΔL\* 7.11 |
| `panel` → `well` (card → well) | **1.05 : 1** · ΔL\* 2.39 | 1.43 : 1 · ΔL\* 13.75 |

The v6 glass pass deliberately pulled `panel` down toward `canvas` (*"cards recede toward the
canvas"*, `style.py:475`). The side effect: **at FLAT, in the dark theme — the default theme — a card
sits 1.5 ΔL\* above the floor it lies on. That is below the practical JND. Across the room, the
cards are gone.** Candidate C's ladder was praised for surviving the flat tier; in dark it survives
only as a 1 px border. Read that as: the ladder both candidates inherit is broken, and AMBIENT — which
has *nothing else* — cannot ship without fixing it.

(WCAG ratios are the wrong ruler near black: the `+0.05` offset flattens the whole region. So the
ladder is specified in **ΔL\*** — a perceptual step — and only the *ink* is specified in WCAG ratios.)

> ### NEW TOKEN — `card` (both candidates need it; AMBIENT dies without it)
> ```
> DARK:   card = _blend(raised, panel, 0.60)   ->  #151D2D
> LIGHT:  card = panel                          ->  #FFFFFF   (light already works)
> ```
> **Derivation, not taste:** 0.60 is the smallest step from `panel` toward `raised` that gives the
> dark ladder *the same perceptual separation from `canvas` that the light ladder already has*:
> **ΔL\* 7.16 (dark) vs ΔL\* 7.11 (light).** A match, not a preference.
> Ink on it stays AA: `text` 14.37 · `muted` 6.50 · `crit` 5.53 · `good` 8.99 · `warn` 9.81 ·
> `accent` 6.87 · `sim` 9.77. (`faint` 2.88 — still retired for text, exactly as `style.py` says.)

### The full ladder, with the fix

| level | token | DARK | LIGHT | ΔL\* from its parent |
|---|---|---|---|---|
| CONTAINER | `canvas` | `#0A0D13` | `#E6EBF3` | — |
| CARD | **`card`** (new) | `#151D2D` | `#FFFFFF` | **7.16** / **7.11** |
| CONTROL | `raised` | `#1B253A` | `#F8FAFD` | 3.99 / −1.8 (+ border) |
| WELL | `well` | `#070A0F` | `#D4D8E0` | **−8.08** / **−13.75** |

**One rule falls out of the measurement and it must be a lint:** dark `well` (ΔL\* 2.68) is
essentially indistinguishable from dark `canvas` (ΔL\* 3.60) — a gap of **0.92**. So:
> **A `well` may only ever sit on a `card`. Never directly on the `canvas`.** On a card it is a clear
> −8.08 recess; on the canvas it is invisible.

### The other two carriers of depth (both survive FLAT)

- **Outline.** Every card is outlined in **`hairline_strong`**, not `hairline` — promoted, because
  plain `hairline` against a *light glass canvas over a white desktop* measures **1.16:1** and the
  card edge dissolves. `hairline_strong` gives **1.45:1 / ΔL\* 13.6**. Cheap `hairline` is for
  *internal* rules only.
- **Elevation.** A drop shadow (`edge_shade`-derived) + the `specular` top edge. **Both are removed
  at the FLAT tier** — FLAT is *"plain opaque solids, no glass identity"* (`glass_env.py`) — which is
  precisely why the *tone* step and the *outline* have to be sufficient on their own. They are: 7.16
  ΔL\* + a 1.45:1 outline, with no shadow and no specular. **That is the FLAT-first proof.**

---

## 2. Screen model — nothing overlaps, ever

```
┌────────────────────────────────────────────────────────────────────────────┐  window: bg @ .80
│  TCT Setup Control                                              – □ ×      │  over the DWM material
├────────────────────────────────────────────────────────────────────────────┤  — the ONLY glass
│ ▣ VITALS — 6 cells, opaque `card`, never clipped, never scrolled           │  84 px
│ HV · LEAKAGE · COMPLIANCE · MOTION · LASER · SCAN                          │
├────────────────────────────────────────────────────────────────────────────┤
│ PHASE  ● Idle ─ ○ Armed ─ ○ Homing ─ ○ Scanning ─ ○ Settling ─ ○ Done      │  34 px, opaque
├──────┬───────────────────────────────┬─────────────────────────────────────┤
│SPINE │  ┌─────────────┐ ┌──────────┐ │  ┌───────────────────────────────┐  │
│solid │  │ BIAS  card  │ │ MOTION   │ │  │ SCOPE  card                   │  │
│column│  │ ┌─────────┐ │ │  card    │ │  │ ┌───────────────────────────┐ │  │
│ 76px │  │ │DANGER   │ │ │          │ │  │ │ plot island (opaque)      │ │  │
│      │  │ │WELL     │ │ │          │ │  │ └───────────────────────────┘ │  │
│      │  │ └─────────┘ │ │          │ │  └───────────────────────────────┘  │
│      │  └─────────────┘ └──────────┘ │                                     │
│ ···· │        ↑ 8px gutters — THIS is where the glass shows ↑              │
│ 4/6  │                               │  (a real grid TRACK, not an overlay)│
└──────┴───────────────────────────────┴─────────────────────────────────────┘
```

- **The spine is a grid track**, not a floating rail. It has a width; the workspace begins after it.
  Nothing is ever underneath it, so it has nothing to frost, so it is opaque, so it costs nothing.
- **The drawer is a grid track too.** It *pushes*; it never *covers*. Opening the inspector re-lays
  the workspace. You never lose sight of a panel because something floated over it — because nothing
  ever floats.
- **The gutters are the glass.** 8 px between cards, 12 px at the window edge, and the window's
  rounded corners. At SCENE/WINDOW tier the desk shows through them, faintly, at
  `MIN_BACKDROP_CANVAS_ALPHA` = 0.80 (20 % of the desktop, blurred by DWM). At TOKEN/FLAT they are the
  opaque `canvas` token. **That is the entire visual difference between the top of the ladder and the
  bottom of it.**

### The vitals strip (shared with STRUCTURAL — inherited law, plus a bug fix)
Opaque `card`, at every tier. Six cells. **Leakage current and compliance are back** — they exist in
the classic strip (`_chip_bias_i`, `_chip_bias_comp`) and were simply dropped on the way into
`ScanStatusStrip.qml`, which ships four tiles (State / HV / Progress / Position).

| Cell | Value | Caption | Hazard? |
|---|---|---|---|
| **HV** | `+412.0 V` | `output ON` + filled lamp | yes |
| **LEAKAGE** | `1.84 µA` | 60 s sparkline · `▲ rising` | yes |
| **COMPLIANCE** | `OK` / `IN COMPLIANCE` | `limit 5.0 µA` | yes |
| **MOTION** | `X 12.40 Y 8.10 Z 2.05` | `homed · idle` | yes |
| **LASER** | `TRIG ON` | `1 kHz · ext` | yes |
| **SCAN** | `RUNNING 412/900` | `ETA 4 m 12 s` + meter | no |

**The no-clip contract, as a rule a test can hold:**
- A **6-slot CSS-grid**, not a `Row`. Slots are `minmax(156px, 1fr)`.
- 6 × 156 + 5 × 8 = **976 px**; + spine 76 + margins 32 = **1084 px** ≪ the 1536 px default width.
  **One row, always, at the default width.**
- Below 1084 px → 3 × 2. Below 700 px → 2 × 3. **It never scrolls, never elides, never clips.**
  Today's `MOTION`-runs-off-the-right-edge bug is not fixed by adding a scrollbar; it is fixed by
  making overflow *unrepresentable*.
- **A hazard cell may never be the one that degrades.** Under extreme width pressure SCAN drops its
  caption first, then LASER. HV / LEAKAGE / COMPLIANCE / MOTION keep label + value to the last pixel.
- **State is never colour alone.** Every cell carries a glyph (`▲ rising`, `■ limit`, `● live`) *and*
  a word (`ON`, `OK`, `HOMED`). Colour is the third channel.

**Device lamps** (six devices) move to the **spine footer**: a `4/6 connected` chip with six dots,
keyboard-focusable, expanding to a popover. They are a connection census, not a vital — and cramming
them into the vitals row is what made the strip overflow in the first place.

### Danger (ratified: panel-owned)
The Bias card owns HV; the danger well is an opaque inset inside it (`danger_fill` body, `on_danger`
label, `crit` outline), gated by the existing `QtDangerGate` / `ArmLatch`. **The shell displays HV
and cannot enable it.** No mediator, no shell-side trigger, anywhere.

Because AMBIENT has no translucency on any information surface, the danger well is *already*
byte-identical at every tier — there is no special "hazard surfaces stay opaque" carve-out to
remember, because **everything** stays opaque. The law is satisfied structurally rather than by
vigilance.

---

## 3. Contrast — the receipt, and why AMBIENT's is boring

Design alphas sit **at the floors** (`canvas 0.80`; there is no pane alpha, because there are no
panes). I ran the tier switch on myself this time.

### 3.1 The double-underlay law (the thing I got wrong in round 01)
Baldr composited a pane straight onto the desktop and got **2.30:1**. He was right about my HTML and
wrong about the app: the app *always* paints its canvas underneath. That layer, not the alpha, was
what round 01 was missing.

> A translucent surface **never** composites directly against the compositor. Total desktop leakage
> through the AMBIENT canvas at the floor = **20 %**. Through anything else in AMBIENT = **0 %**,
> because there is nothing else.

### 3.2 The table — and this is the whole pitch

`canvas_glass = 0.80·bg + 0.20·desktop` · cards are **opaque**

| ink | on an opaque `card` — DARK | on an opaque `card` — LIGHT | changes with the desktop? | changes with the tier? |
|---|---|---|---|---|
| `text` | **14.37** ✓ | 17.41 ✓ | **no** | **no** |
| `muted` | **6.50** ✓ | 6.63 ✓ | **no** | **no** |
| `good` | **8.99** ✓ | 5.60 ✓ | **no** | **no** |
| `warn` | **9.81** ✓ | 5.68 ✓ | **no** | **no** |
| `crit` | **5.53** ✓ | 6.31 ✓ | **no** | **no** |
| `accent` | **6.87** ✓ | 5.25 ✓ | **no** | **no** |
| `sim` | **9.77** ✓ | 5.88 ✓ | **no** | **no** |
| `on_danger` on `danger_fill` | **4.80** ✓ | 6.31 ✓ | **no** | **no** |
| `faint` | 2.88 ✗ | 2.72 ✗ | no | no | *(retired for text — repo law)* |

**Every information surface in AMBIENT is desktop-independent and tier-independent.** The
worst-case-backdrop column is not a hard case I survived; it is a column that does not apply. The
"worst-case backdrop" table for AMBIENT's text is *the same table as TOKEN*, which the repo already
certifies.

### 3.3 The one place AMBIENT *does* touch glass — and it is non-text
The card **edge** and the card **body** sit against the glass canvas. Nothing else does. WCAG 1.4.11
(3:1) does not strictly govern a decorative container edge, but "can you see the card from across the
room" does — so I measured it anyway, at the floor:

| | DARK / white desk | DARK / black desk | LIGHT / white desk | LIGHT / black desk |
|---|---|---|---|---|
| glass canvas composites to | `#3B3D42` | `#080A0F` | `#EBEFF5` | `#B8BCC2` |
| `card` body vs. it (ΔL\*) | **14.98** | 8.02 | **5.69** | 23.9 |
| `hairline` outline vs. it | 2.31 : 1 | 1.18 : 1 | **1.16 : 1** ✗ | 1.55 : 1 |
| **`hairline_strong` outline vs. it** | 2.13 : 1 | 1.75 : 1 | **1.45 : 1** | 1.31 : 1 |

The worst cell is **light theme over a white desktop**: a white card on a near-white glass canvas.
`hairline` disappears (1.16:1) — this is why `hairline_strong` is promoted to the mandatory card
outline (§1), and it is the one thing in this candidate that a bright desktop can hurt. It hurts a
*border*, not a *readout*.

---

## 4. The other windows — and here AMBIENT costs nothing

Ratified: every detached panel is its own top-level ⇒ its own DWM material ⇒ its own tier.

| window | AMBIENT says | code change |
|---|---|---|
| **A detached panel** (`detachable_tabs.py`) | Its own DWM material on the window; opaque cards inside. **Identical rules to the main window** — a card is a card wherever it lives. | **none** |
| **`device_panel`** (a real `QMainWindow`) | Same. Device rows are `card`s; per-device connect/disconnect stays panel-owned. | **none** |
| **`scope._TriggerDialog`** (floating) | Its own DWM material; opaque cards. **No semantic breaks**, because AMBIENT never promised that glass means "above your work" — it only ever promised that glass means "this is a window". A dialog *is* a window. | **none** |
| **`camera._ROIDialog`** (modal) | Same. | **none** |

**This is AMBIENT's quiet structural win, and it is worth saying plainly:** its depth language is a
statement about *windows*, and every one of these four surfaces genuinely *is* a window. So the
language has zero exceptions and needs zero code changes to `scope_panel.py` or `camera_panel.py`.
STRUCTURAL's language has four exceptions and needs two rewrites.

---

## 5. Justification

- **Problem solved.** The cockpit must be readable at a glance from across the room while a beam is
  on, on whatever machine the operator is sitting at — including RDP, including high contrast,
  including Linux, including a Win10 box. AMBIENT makes that *the same picture on all of them*. It
  also fixes, structurally, the two live bugs: the clipping strip and the missing leakage/compliance
  readouts.
- **Alternatives considered inside this candidate:**
  1. *Let the vitals strip be glass* — rejected on law (no glass on hazard surfaces) **and** on
     measurement: it would put `warn`/`good` text on a translucent surface, which fails AA in light
     theme over a dark desktop (4.19 / 4.14).
  2. *Keep the shipped `panel` token as the card and lean on the border* — rejected on measurement:
     ΔL\* 1.47 in dark. A design whose entire hierarchy is a 1 px line is not glanceable across a
     room; it is a spreadsheet.
  3. *Use `raised` as the card body* (no new token) — rejected: `raised` is already the *control*
     tone, and cards would then be the same tone as the buttons sitting on them. The ladder would
     collapse from three tones to two at the level that matters most.
  4. *Drop the DWM window glass entirely and ship pure TOKEN* — genuinely tempting, and honestly the
     safest thing in the building. Rejected only because the DWM material is **free**, degrades
     perfectly, and is the one thing that makes this look like a 2026 instrument rather than a 2011
     one. It is the *only* aesthetic indulgence in the candidate, and it costs zero CPU and zero
     contrast on any information surface.
- **Safety implications.** The strongest of any candidate in either round: the material cannot encode
  hazard because the material cannot touch anything that carries hazard. Every hazard surface is
  opaque at every tier, byte-identical on RDP and on the full glass build, so the muscle memory that
  makes a danger gesture safe never has to survive an appearance change. Danger is panel-owned; the
  shell has no trigger path.
- **Operational implications.** **Zero** additional CPU. No `MultiEffect` anywhere, so nothing
  contends with acquisition, so the "glass never costs a measurement" rule (SYNTHESIS §4.3) is
  satisfied by construction instead of by budget. No new subsystem. The migration is a re-layout plus
  one palette token.
- **Why now.** Because the spike proved the expensive option is *possible*, which is exactly the
  moment to ask whether it is *worth it* — and because the two live bugs (clipping strip, dropped
  leakage/compliance) need fixing regardless of which candidate wins.

---

## 6. Weaknesses — real ones

1. **It abandons the brief's own reference.** Kaya asked for "match the design_assets like visionOS
   more". The single most recognisable thing in every one of those eight plates is *content seen
   through chrome*. AMBIENT does not do that, anywhere, ever. It takes the *ladder*, the *radii*, the
   *numeric hierarchy* and the *specular edge* from visionOS and refuses its defining move. **A
   reasonable person could look at this and say I did not do the job.**
2. **The depth is honestly quite subtle, and it leans on one number I chose.** ΔL\* 7.16 is a
   *matched* step, not a *proven-across-the-room* step. I matched it to light's existing 7.11 because
   that step ships today and nobody has complained — which is an argument from silence, not from
   measurement. Nobody has viewed either from four metres away on the actual lab monitor, at the
   actual brightness, with the actual overhead lights. **The whole candidate rests on a number that
   has never been tested in the room it is designed for.** Someone should stand up and walk backwards.
3. **The glass is so restrained it may not be worth the tier machinery at all.** If the only thing
   `SCENE`/`WINDOW` buys is a slightly transparent 8 px gutter, then the honest conclusion is that
   `glass_env.py`, `backdrop.py`, the event spine and the whole five-rung ladder exist to deliver an
   effect the operator will never notice. **AMBIENT does not justify the glass programme — it
   quietly indicts it.** That is a legitimate outcome, but Kaya should be told, not discover it in
   six weeks.
4. **`hairline_strong` at 1.45:1 against a bright desktop in light mode is thin.** A white card on a
   near-white glass canvas is held together by one 1 px line at 1.45:1. It is above nothing in
   particular — there is no WCAG floor for a container edge — and if a bench check says the cards
   dissolve on a white desktop, the fix is ugly: either raise `MIN_BACKDROP_CANVAS_ALPHA` in light
   mode (a token change with its own blast radius) or give light cards a shadow that must then
   survive FLAT (it cannot; FLAT has no shadows).
5. **"Nothing overlaps" is a real functional loss and I should not pretend otherwise.** The drawer
   pushes instead of covering, so opening the inspector *re-lays the workspace* — plots resize, the
   camera aspect changes, the operator's spatial memory is disturbed **mid-run**. A floating drawer
   (STRUCTURAL's) disturbs nothing; it just covers. Under a 1536×864 screen this is not a small
   annoyance: there is not enough width for a 320 px drawer *and* two panels, so something has to
   give every single time.
6. **The new `card` token changes the shipped dark palette**, and dark is the default theme. Every
   screenshot, every existing artifact, and the frozen v6 look all shift. If Kaya rejects the token,
   AMBIENT has *nothing* left — no glass, and a 1.03:1 ladder. It is the more fragile candidate in
   exactly one respect: STRUCTURAL degrades to AMBIENT, but **AMBIENT-without-`card` degrades to
   nothing.**
