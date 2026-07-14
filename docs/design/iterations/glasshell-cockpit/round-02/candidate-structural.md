# Candidate STRUCTURAL — "The Overlay Cockpit"

> **Philosophy, one line:** *Depth means transience. A surface is glass **exactly** when it is
> temporarily above your work — and never otherwise.*

| | |
|---|---|
| **Round** | 02 · GlassShell cockpit |
| **Forged by** | Brokkr, 2026-07-14 |
| **Optimizes for** | Spatial truth. You can always see *what you are covering up*. Nothing the operator was watching is ever fully hidden by chrome or by a dialog. |
| **Deliberately sacrifices** | CPU (+13 pp resident, up to +39 pp with an overlay open), a uniform look across windows (a detached panel has **no** glass panes — see W2), and code stability (it demands two shipped top-level dialogs become in-window overlays). |
| **Files** | [`candidate-structural.html`](candidate-structural.html) |

---

## 0. The measurement that wrote this candidate

The spike (`bbe3b10`) says: **Qt Quick has no backdrop-filter and cannot have one.** A `MultiEffect`
can only blur what is inside its own scene graph.

The design consequence is not "glass is cheaper than we thought". It is much sharper:

> **An in-scene frosted pane is only *meaningful* if it OVERLAPS other app content.**
> A frosted pane over the window's own alpha hole is *pixel-identical to no pane at all* — measured.

So a "structural glass" cockpit cannot be a cockpit of tiled glass cards. Tiled cards do not overlap
anything; their frost would be a no-op. **Structural glass forces an overlapping cockpit.** That is
the entire reason this candidate looks the way it does, and it is the reason it and AMBIENT are not
reconcilable by a stylesheet: AMBIENT tiles, STRUCTURAL layers.

---

## 1. The depth ladder — five levels, each one a *statement*

The material is not decoration here; each level answers "what is this surface's relationship to your
work?".

| # | Level | Material | Says |
|---|---|---|---|
| 0 | **SUBSTRATE** | The window itself: `bg` @ `MIN_BACKDROP_CANVAS_ALPHA` (0.80) over the DWM material. **Free** — no `MultiEffect`. | "This app is a thing in your room." |
| 1 | **WORKSPACE** | Opaque `canvas`. | "This is the floor. Your work sits here." |
| 2 | **CARD** | Opaque **`card`** (new token, §5). | "This is a panel. It holds values. It is solid because values must never be washed out." |
| 3 | **WELL** | Opaque `well`. | "A reading, or an input. Recessed." |
| 4 | **FLOAT** | `panel` @ `MIN_PANEL_GLASS_ALPHA` (0.50) + `MultiEffect` blur **over levels 1–3**. | "**I am temporarily above your work.** Look — it is still there, under me." |

**Glass appears at exactly one place in the ladder: level 4.** Nothing else in the app is ever
translucent. That is the semantic. A surface being glass is a *fact about its relationship to the
content beneath it*, and it is the only thing glass ever says here.

The three surfaces that are level 4:

- **the SPINE** — the 76 px navigation rail. The workspace runs *under* it and is visible through it.
- **the DRAWER** — the inspector / phase detail, sliding in from the right *over* the panels.
- **the OVERLAY** — trigger dialog, ROI dialog, tab overflow, command palette.

Everything else — vitals, phase rail, every panel, every readout, **every danger control** — is
opaque at every tier.

### Why the SPINE is the one resident piece of glass
Because it is the one piece of chrome that is *permanently in the way*. A 76 px opaque column steals
76 px of workspace forever. A 76 px glass column steals 76 px of *attention* and gives the pixels
back: a plot that extends under the spine is still readable as a shape, so the operator's peripheral
sense of "the trace is still running" survives the chrome. That is a real ergonomic claim and it is
the only justification I will accept for spending 13 pp of an integrated GPU.

---

## 2. CONTENT-AWARE UNDERLAY — the mechanism that makes level 4 legal

A frosted pane over unbounded content is an accessibility catastrophe, and I have the number:

> A **dark** `panel` pane at the 0.50 floor over a **bright camera frame** composites to ≈ `#868891`.
> Dark `text` on it: **3.02:1 — FAILS AA.**
> A **light** pane at the floor over the plot canvas (`PLOT_BG`): `muted` = **1.80:1 — invisible.**

And a frosted pane over a plot or the camera is also exactly the +13 pp we are forbidden to spend on
hot-path islands.

So level 4 carries a mechanism, not a promise:

```
A level-4 pane resolves its own backing every time its geometry or the layout changes:

    if  pane.rect  intersects  any  registered HOT-PATH ISLAND (plot | camera | video)
        -> the pane paints its OPAQUE `card` pre-blend. No MultiEffect. No blur. No alpha.
    else
        -> the pane frosts, sourcing ONLY level 1-3 surfaces (canvas / card / well),
           whose colours are TOKENS, therefore BOUNDED, therefore PROVABLE.
```

This is the underlay law (`gui/backdrop.py`) extended one level inward, and it is cheap: a rectangle
intersection against a registry that already exists in spirit
(`panel_kit.register_glass_pane()` already *refuses* a plot container — this is the same idea,
enforced at layout time instead of registration time).

It gives three things at once:
1. **Contrast becomes provable.** A frosted pane's backdrop is drawn from a finite set of tokens, so
   its worst case is a table, not a hope (§4).
2. **The CPU rule is enforced structurally**, not by discipline. You *cannot* accidentally frost a
   plot; the pane refuses.
3. It degrades in the safe direction: unsure → opaque.

**It also carries no hazard information** — the underlay flips on *geometry*, never on state. A pane
going opaque means "a plot moved under me", never "something is wrong". (Constitutional law 1.)

---

## 3. Screen model

```
┌──────────────────────────────────────────────────────────────────────────┐  window: bg @ .80
│  TCT Setup Control                                            – □ ×      │  over the DWM material
├──────────────────────────────────────────────────────────────────────────┤  (level 0, free)
│  ▣ VITALS — 6 cells, OPAQUE at every tier, never clipped, never scrolled │  84 px
│  HV · LEAKAGE · COMPLIANCE · MOTION · LASER · SCAN                       │
├──────────────────────────────────────────────────────────────────────────┤
│  PHASE  ● Idle ─ ○ Armed ─ ○ Homing ─ ○ Scanning ─ ○ Settling ─ ○ Done   │  34 px, opaque
├────────┬─────────────────────────────────────────────────────────────────┤
│▓SPINE▓ │                                                                 │
│▓glass▓ │      THE WORKSPACE — opaque `canvas`                            │
│▓level▓ │      panels are opaque `card`s; plots/camera are islands        │
│▓  4  ▓ │      ← the workspace extends UNDER the spine →                  │
│▓ 76px▓ │                                                                 │
│▓      ▓ │                                       ┌────────────────────┐   │
│▓ ···· ▓ │                                       │▓ DRAWER (level 4) ▓│   │
│▓devices▓│                                       │▓ frosts the panels▓│   │
└────────┴───────────────────────────────────────┴────────────────────┴────┘
```

### The vitals strip (shared with AMBIENT — this is inherited law, plus a bug fix)
Six cells. **Leakage current and compliance are back** (`_chip_bias_i`, `_chip_bias_comp` — they
exist in the classic strip and were dropped on the way into `ScanStatusStrip.qml`, which ships four
tiles: State / HV / Progress / Position).

| Cell | Value | Caption | Hazard? |
|---|---|---|---|
| **HV** | `+412.0 V` | `output ON` + a filled lamp | yes |
| **LEAKAGE** | `1.84 µA` | 60 s sparkline, `↑ rising` | yes |
| **COMPLIANCE** | `OK` / `IN COMPLIANCE` | `limit 5.0 µA` | yes |
| **MOTION** | `X 12.40  Y 8.10  Z 2.05` | `homed · idle` | yes |
| **LASER** | `TRIG ON` | `1 kHz · ext` | yes |
| **SCAN** | `RUNNING 412/900` | `ETA 4 m 12 s` + meter | no |

**The no-clip contract, as a rule a test can hold:**
- The strip is a **6-slot grid**, not a `Row`. Slots are `minmax(156px, 1fr)`.
- 6 × 156 + 5 × 8 = **976 px**; + spine 76 + margins 32 = 1084 px. The app's default width is
  1536 px. **One row, always, at the default width.**
- Below 1084 px it reflows 3 × 2. Below 700 px, 2 × 3. **It never scrolls, never elides, never
  clips.** No item can leave the viewport, so no scroll affordance is needed — the bug today
  (`MOTION` running off the right edge) is not fixed by adding a scrollbar, it is fixed by making
  overflow *unrepresentable*.
- **A hazard cell may never be the one that degrades.** If a width is so small that a cell must drop
  its caption, SCAN drops first, then LASER. HV / LEAKAGE / COMPLIANCE / MOTION keep label + value
  down to the last pixel.

**State is never colour alone:** every cell carries a glyph (`▲` rising, `■` compliance limit hit,
`●` live) *and* a word (`ON`, `OK`, `HOMED`). The colour is the third channel, not the first.

**The device lamps** (six devices) move to the **spine footer** — a `4/6 connected` chip with six
dots, keyboard-focusable, expanding to a popover. They are a connection census, not a vital; putting
them in the vitals grid is what forced the strip to overflow in the first place.

### The workspace
Panels tile. Each is an opaque `card` with a `hairline_strong` outline. Hot-path islands (the scope
trace, the camera frame) are full-bleed opaque children of their card and are **registered** as
islands, so no level-4 pane will ever frost them.

### Danger (ratified: panel-owned)
The Bias card owns HV. Its ramp controls live in an opaque **danger well** inside the card:
`danger_fill` body, `on_danger` label, a `crit` outline, and the existing `QtDangerGate` /
`ArmLatch` ceremony untouched. **The shell shows HV; the shell cannot enable HV.** There is no
shell-side control anywhere in this candidate, and no mediator object.

---

## 4. Contrast at the FLOOR — the receipt I did not produce last round

Design alphas are set **at the floors** (`canvas 0.80`, `pane 0.50`) deliberately: there is then no
gap between what I show and what I measure. The worst case *is* the shipped case.

### 4.1 THE DOUBLE-UNDERLAY LAW (this is what I got wrong in round 01)

Baldr's 2.30:1 was real, and it was **correct for the model my own HTML implemented**: a pane painted
straight onto the desktop. It is not correct for the app, and the difference is not the alpha — it is
a missing layer.

> **A translucent pane may NEVER composite directly against the compositor.** There is always a
> canvas layer at ≥ `MIN_BACKDROP_CANVAS_ALPHA` between the desktop and any pane.
> Desktop leakage through a level-4 pane at the floors = `(1−0.80) × (1−0.50)` = **10 %**.

| model | pane over white desktop | dark `text` | dark `muted` |
|---|---|---|---|
| **round-01 (mine, broken)** — pane @ .42 straight onto the desktop, 58 % leakage | `#999b9f` | **2.30** ✗ | **1.04** ✗ |
| **round-02 (the law)** — pane @ .50 over canvas @ .80, 10 % leakage | `#24272E` | **12.75** ✓ | **5.77** ✓ |

The fix was never a higher alpha. It was a *layer*. Both are now floors, and both are enforced.

### 4.2 The table — level-4 pane, at the floors, worst desktop of {white, black}

`pane = 0.50·panel + 0.50·(0.80·bg + 0.20·desktop)`

| ink | DARK / white desk | DARK / black desk | LIGHT / white desk | LIGHT / black desk | verdict |
|---|---|---|---|---|---|
| `text` | **12.75** ✓ | 16.51 ✓ | 16.22 ✓ | **12.86** ✓ | pass everywhere |
| `muted` | **5.77** ✓ | 7.47 ✓ | 6.18 ✓ | **4.90** ✓ | pass everywhere (the repo's own certified floor) |
| `crit` | **4.91** ✓ | 6.35 ✓ | 5.88 ✓ | **4.66** ✓ | pass, thin |
| `good` | 7.97 ✓ | 10.6 ✓ | 5.22 ✓ | **4.14** ✗ | **FAILS as text** |
| `warn` | 8.70 ✓ | 11.3 ✓ | 5.29 ✓ | **4.19** ✗ | **FAILS as text** |
| `sim` | 8.66 ✓ | 11.3 ✓ | 5.48 ✓ | **4.34** ✗ | **FAILS as text** |
| `accent` | 6.09 ✓ | 7.90 ✓ | 4.90 ✓ | **3.88** ✗ | **FAILS as text** |
| `faint` | 2.55 ✗ | 3.31 ✗ | 2.54 ✗ | **2.01** ✗ | already retired for text |

**Baldr was right and it is worse than he said.** The repo's scrim contract only ever certified
`muted`. At the floor, in **light theme over a dark desktop**, *four more tokens fail as text*:
`good`, `warn`, `sim`, `accent`. And `faint` lands on exactly the ~2.0:1 he measured.

### 4.3 The law this forces on level 4 — and it is the same law style.py already wrote

> **A level-4 (glass) pane carries CHROME and LABELS only. Never a value, never coloured text.**
> - Permitted ink on glass: `text` (≥ 12.75) and `muted` (≥ 4.90). Both pass at the floor, both themes,
>   both desktops.
> - `good`/`warn`/`crit`/`sim`/`accent` on glass are permitted **only as non-text** (a lamp, a bar, a
>   rule): worst is `accent` at 3.88 and `good` at 4.14 — both clear the 3:1 WCAG 1.4.11 non-text
>   floor. **`faint` (2.01) clears nothing and is forbidden on glass even as decoration.**
> - Every **value** lives in an opaque `well` or on an opaque `card`. Always.

This is not a concession — it is what `style.py:856` already says out loud: *"The readouts that MUST
stay legible are opaque regardless — these panes only ever carry chrome/labels, never live values."*
The spine holds nav labels. The drawer holds a title and captions; its values sit in opaque wells
*on* it. Nothing is lost, and the pane's ink is provably legal.

### 4.4 The FLAT tier — where this candidate has to survive without its idea
See §5. At FLAT the level-4 panes go opaque and STRUCTURAL becomes, visually, AMBIENT. That is not a
weakness I am hiding; it is W1.

---

## 5. Tokens — one new token, and it is not optional

I measured the "three-tone FLAT ladder" that round 01 inherited from candidate C. **In the dark
theme it does not exist.**

| ladder step | DARK (shipped) | LIGHT (shipped) |
|---|---|---|
| `canvas` → `panel` | **1.03 : 1** · ΔL\* **1.47** | 1.20 : 1 · ΔL\* 7.11 |
| `panel` → `well` | **1.05 : 1** · ΔL\* 2.39 | 1.43 : 1 · ΔL\* 13.75 |
| `canvas` → `raised` | 1.27 : 1 · ΔL\* 11.15 | 1.15 : 1 · ΔL\* 5.31 |

The v6 glass pass pulled `panel` down toward `canvas` on purpose ("cards recede toward the canvas" —
`style.py:475`). The side effect is that **at the FLAT tier, in the dark theme — the default theme —
a card is 1.5 ΔL\* away from the floor it sits on. That is below the practical JND. Across the room,
at FLAT, in dark, the cards are invisible.** The ladder C was praised for is carried entirely by its
1 px border.

WCAG ratios are the wrong instrument here (near black, the `+0.05` offset flattens everything), so I
report **ΔL\*** — a perceptual step — alongside them.

> ### NEW TOKEN — `card`
> ```
> DARK:   card = _blend(raised, panel, 0.60)   ->  #151D2D
> LIGHT:  card = panel                          ->  #FFFFFF   (the light ladder already works)
> ```
> **Derivation, not taste:** 0.60 is the smallest step from `panel` toward `raised` that gives the
> DARK ladder the *same perceptual separation from `canvas`* that the LIGHT ladder already has:
> **ΔL\* 7.16 (dark) vs ΔL\* 7.11 (light).** It is a *match*, not a preference. Every ink stays AA on
> it (`text` 14.37, `muted` 6.50, `crit` 5.53, `good` 8.99, `warn` 9.81, `accent` 6.87, `sim` 9.77;
> `faint` 2.88 — still retired, as the repo already says).

**Second token change (a promotion, not a new value): `hairline_strong` becomes the mandatory card
outline.** Plain `hairline` against a light glass canvas over a white desktop measures **1.16:1** — the
card edge dissolves. `hairline_strong` gives **1.45:1 / ΔL\* 13.6**. The cheap hairline is for
*internal* rules only.

**A third, non-colour token — the budget:**
> `GLASS_PANE_BUDGET = 2` — the maximum number of live `MultiEffect` panes per top-level window.
> Derived from the measurement: 13 pp each on an integrated GPU ⇒ a 26 pp ceiling, which is the most
> I am willing to spend while a beam is on. The 3rd request (an overlay opening while the drawer is
> out) **evicts the drawer's frost to its opaque underlay** rather than exceeding the budget.

No other new tokens. Every colour in the HTML is one of the above.

---

## 6. The other windows — three more glass surfaces (Shiori's census)

Ratified: every detached panel is its own top-level ⇒ its own DWM material ⇒ its own tier.

| window | STRUCTURAL says |
|---|---|
| **A detached panel** (`detachable_tabs.py`) | Level 0 substrate (its own DWM material) + opaque `card`s. **It has NO spine and NO drawer, therefore ZERO level-4 panes.** A torn-off panel is 0 pp and, visually, *is* the AMBIENT candidate. This is an honest inconsistency (W2). |
| **`device_panel`** (a real `QMainWindow`) | Same: own substrate, opaque cards, no level-4 panes. Its device rows are `card`s; its per-device danger (connect/disconnect) is panel-owned as always. |
| **`scope._TriggerDialog`** (floating, non-modal) | **Here STRUCTURAL breaks its own promise.** It is a separate HWND — an in-scene `MultiEffect` *cannot reach the parent window's content*. A floating dialog can therefore only get **WINDOW-tier DWM glass over the desktop** — i.e. the AMBIENT treatment. STRUCTURAL's semantic ("glass = above your work") is *false* for the one surface most obviously above your work. |
| **`camera._ROIDialog`** (modal) | Same problem, same answer. |

**STRUCTURAL's fix, and its true cost:** convert both dialogs from top-level windows to **in-window
overlays** (level 4), where the semantic holds and the frost is real. That is a change to
`scope_panel.py` and `camera_panel.py`, it changes their focus/modality behaviour, and it is
**scope this candidate cannot hide.** If Kaya refuses it, STRUCTURAL ships with two windows that
lie about its own depth language.

---

## 7. Justification

- **Problem solved.** The current cockpit hides your work behind chrome and dialogs. During a slow HV
  ramp the operator must watch leakage *and* the trace *and* the ramp (round 01 proved they watch
  several things at once — `detachable_tabs.py` is the proof). Every opaque overlay is a moment where
  one of those three goes dark. Level-4 glass means the covered thing is still *there*.
- **Alternatives considered inside this candidate:**
  1. *Glass cards, tiled* — rejected on measurement: they overlap nothing, so the frost is a no-op
     (spike finding 1). This is the alternative most people mean by "structural glass", and it is
     physically empty in Qt Quick.
  2. *Frosted vitals strip* — rejected on law: the vitals carry hazard; no glass on hazard surfaces,
     at any tier.
  3. *Blur the plot behind the spine* — rejected twice: +13 pp on the hot path, and 3.02:1 text over
     a bright camera frame.
  4. *Raise the pane alpha to 0.70 so `good`/`warn` clear AA on glass* — rejected: it makes the
     frost invisible, which means paying 13 pp for nothing. Better to move values off glass entirely.
- **Safety implications.** The material never encodes hazard: level 4 flips to opaque on *geometry*
  only. Every hazard surface (vitals, danger wells, the abort control) is opaque `card`/`danger_fill`
  at **every** tier — byte-identical on RDP and on the full glass build. Danger is panel-owned; the
  shell has no trigger path. The one new safety risk is genuine and is W3: **a frosted spine over a
  live plot is a *distracting* surface in the operator's periphery.**
- **Operational implications.** +13 pp CPU resident on an integrated GPU, +26 pp with the drawer out,
  hard-capped at 26 pp by `GLASS_PANE_BUDGET`. Upgrades already defer to scan-idle
  (`plan_transition`), so the frost never *appears* mid-run — but a frost that is already running
  keeps costing during the run. That is the bill.
- **Why now.** Because the spike just made it possible, and because the alternative (AMBIENT) is a
  strictly cheaper design that we should only reject if depth genuinely buys something. This
  candidate exists to make that trade explicit and to lose it honestly if it must.

---

## 8. Weaknesses — real ones

1. **At the FLAT tier, STRUCTURAL *is* AMBIENT — and that is most of the fleet.** Level-4 panes go
   opaque on RDP, in high contrast, on Linux without OpenGL, on Win10, on a software rasterizer, and
   on any operator override. The entire idea of this candidate is unavailable on every one of those,
   and its whole hierarchy then rests on the same three-tone ladder AMBIENT uses — which means
   **AMBIENT does STRUCTURAL's fallback job better than STRUCTURAL does, because AMBIENT designed
   for it first.** If the lab's normal operating mode is RDP, this candidate is a 13 pp tax for a
   look nobody in the lab ever sees.
2. **The material lies at the window boundary.** "Glass = above your work" is false for the trigger
   dialog, the ROI dialog, the device manager and every detached panel — four of the app's surfaces,
   all of them separate HWNDs, none of which can frost the parent. Fixing two of them is real code
   in `scope_panel.py` / `camera_panel.py`; the other two cannot be fixed at all. **A depth language
   with four exceptions is not a language.**
3. **A frosted spine sits over a live, moving plot — in the operator's periphery, while a beam is
   on.** The spike measured 59–60 fps and 8× edge reduction, so it is *cheap and pretty*. Nobody has
   measured whether it is *distracting*. A shimmering rail beside a trace is exactly the kind of
   thing that survives a design review and fails a night shift. I have no evidence either way, and
   this candidate bets an ergonomic claim I cannot support.
4. **CONTENT-AWARE UNDERLAY is a new mechanism with a flicker mode.** Drag a panel so a plot slides
   under the drawer and the drawer *pops* from frosted to opaque. That transition is a state change
   in the material — and an operator who has been told "the material carries no information" will
   still, correctly, notice it and wonder what it meant. It carries no *hazard* information, which is
   the law; it does carry *some* information, which is uncomfortable.
5. **`good` / `warn` / `sim` / `accent` cannot be text on glass (light theme, dark desktop).** I have
   turned this into a design law (§4.3), but it is a real constraint that the drawer and spine will
   fight for the rest of their lives, and the first person to put a green "READY" label on the spine
   will break AA without any test noticing — because the test suite has no composited-contrast test
   at all. **This candidate needs one written before it ships.**
6. **The `card` token is load-bearing and it is a change to the shipped dark palette.** If Kaya
   rejects it, STRUCTURAL's FLAT tier is a grey soup (1.03:1 cards) and the candidate is dead — not
   degraded, dead. The candidate cannot stand on the tokens as they ship today.
