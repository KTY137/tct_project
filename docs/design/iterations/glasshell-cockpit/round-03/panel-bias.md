# PANEL — BIAS (the hazard panel)

> **What it proves:** glass can be beautiful *around* a danger surface that is a stone. The HV
> controls do not become glass, do not soften, do not move, and do not depend on the tier. The
> glass is the room they sit in.

Open [`panel-bias.html`](panel-bias.html). Switch to **FLAT** and watch the HV surface not change.
Switch **Garnish → DWM on / Desktop → worst** and watch the live-voltage tile stay a stone.

---

## 1. The panel today (ground truth, `gui/bias_panel.py`)

A `QVBoxLayout` of: a connection chip; a **hero trio** (`MetricGrid(columns=3)` — Voltage measured /
Current / HV state); a `Card("Compliance")`; a `Card("Bias voltage")` with the ramp controls and the
`killSwitchBtn`; a `Card("Polarity")` with a `dangerBtn`; and a collapsed `CheckableCard` of advanced
sweeps that build their pyqtgraph plots lazily on first expand. The kill switch already escalates its
chrome with real HV energy (ghost → neutral → filled red) — that logic is good and I keep it.

## 2. The design — C's language, applied

### 2.1 The shell
The panel is one **shelf** (`shelf` token, blur 40, `hairline_strong` outline). On it sit the cards.
The shelf carries the panel eyebrow (`TCT CONTROL · HIGH VOLTAGE`), the title, and the connection
chip — chrome and labels, nothing else. This is the "container slab" from the Vision Pro plate.

### 2.2 The hero trio is where the danger lives, and it is a HazardSurface — not three glass tiles
This is the sharpest divergence from a naive reading of C. C would make the hero trio three floating
glass tiles. **A live HV voltage may not float on glass.** So the trio is wrapped in a single
**HazardSurface**: opaque `panel`, `backdrop-filter:none`, a 4 px `danger` stripe **with the 45° hatch
texture** down its left edge. Inside it, three **opaque tiles**:

- **Voltage · measured** — `FONT_VALUE_PX` mono, sign from the readback. Crit-inked only on a real
  over-limit; otherwise `text`.
- **Current** — with the compliance limit as its unit-line caption.
- **HV state** — the derived state as **glyph + WORD + colour** (`OFF` / `RAMPING` / `LIVE` / `TRIP`),
  never colour alone.

The hatch is the move that earns its place: on a monochrome projector or in greyscale, the stripe's
*colour* is gone but its *texture* is not. Four channels (stripe, hatch, word, glyph) plus position.

### 2.3 Compliance and ramp — cards, but the actions live in wells that never glass
`Card("Compliance")` and `Card("Bias voltage")` are ordinary glass cards. But every **input** (the
`QDoubleSpinBox`es for compliance, target, step, delay) is an **opaque `well`**, on the card, with the
`edge_shade` inner-top cue so it reads as recessed. **A value being typed is never on glass.** The
`▶ Ramp to voltage` and the `killSwitchBtn` sit in an `ActionBar` on the card; the kill switch keeps its
energy-escalating chrome and, when live, becomes the opaque `danger_fill` body with the `on_danger`
label (4.80 : 1, already in the palette).

### 2.4 The two dangerous actions keep their ceremony
Ramp and polarity-switch are dangerous (law 5). The **ArmLatch** (`gui/arm_latch.py`, unchanged) is the
danger well: Arm (hold 3 s / press twice) → Execute (danger red, revealed only while armed) → 10 s
auto-disarm, with the `ArmedEnvelope` printed in mono at the bottom of the HazardSurface, always. The
polarity switch stays a `dangerBtn`, visible only when the supply reports the channel reversible, and
gated the same way. **I redesigned the room; I did not touch the ceremony.**

## 3. Justification

**Problem solved.** The shipped bias panel is legible but flat — a stack of near-identical grey cards
(see `dark/07_bias_supply.png`); nothing tells the eye that the hero trio is the thing that can hurt a
sensor. This design makes the hazard surface *materially different from everything around it* — it is
the one opaque stone in a glass room — which is a stronger, tier-invariant signal than any colour.

**Alternatives considered within this candidate.**
- *Glass tiles for the hero trio, opaque only for the "state" tile.* Rejected: a live voltage is a
  hazard value; all three tiles carry the physics that matters. Half-glass is a mixed message.
- *Put the HazardSurface stripe on the shelf instead of the surface.* Rejected: danger belongs to the
  panel's danger *surface*, not the panel's chrome — and never to the shell (Kaya, ratified).
- *Drop the hatch, keep only colour + word.* Rejected: the hatch is the cheapest possible fourth
  channel and it is the one that survives a failed projector bulb. It costs one CSS gradient.

**Safety implications.** The HazardSurface is opaque at FLAT, TOKEN and SCENE — identical pixels. No
glass alpha, no blur, no material touches it. The kill switch is always present and never in the shell.
State is never colour alone. The live voltage never composites against anything. At the FLAT tier —
the whole RDP/high-contrast fleet — the panel loses its glass and loses *nothing that matters*.

**Operational implications.** No new persisted state, no layout engine, no migration. The panel is the
same widget tree with kit surfaces swapped in. The lazy sweep-plot teardown fix stays exactly as is.

**Why now.** The kit's `card`/`shelf` tokens and the HazardSurface primitive make this a re-skin, not a
rewrite. It is the smallest panel that exercises every hard rule at once.

## 4. Weaknesses (attack these)

1. **The hero trio is now visually heavier than everything else on the panel, permanently.** In a
   glass room, the one opaque slab dominates — which is *correct* for HV, but it means the compliance
   and ramp cards recede, and compliance is itself safety-relevant. I am betting that "the value that
   can hurt you is loudest" is the right hierarchy; a reasonable person could argue compliance deserves
   equal weight and I demoted it to a glass card.
2. **The hatch texture is decorative until it is not.** On a normal colour monitor nobody reads the
   hatch; it earns its cost only in the greyscale/failed-projector edge case, which may never occur in
   this lab. It is cheap, but it is complexity I am adding for a case I have not observed.
3. **`killSwitchBtn` on a glass card, when idle, sits at neutral-outline chrome against a translucent
   surface.** Its "nothing to kill yet" state has the least contrast of any control on the panel, and a
   glass card behind it makes that outline thinner than on today's opaque card. I have not measured the
   idle kill-switch outline against the worst legal card composite; it could be the panel's weakest
   contrast moment and I am flagging it rather than hiding it.
4. **A detached bias panel gets its own ground** (§10.4 of the kit) — so a torn-off HV panel looks
   subtly different from the docked one, and HV is exactly the panel an operator is most likely to tear
   off onto a second monitor. The HazardSurface is identical either way (opaque), so nothing unsafe
   follows — but the *room* around it shifts, and that is a seam in the language at the worst place.
</content>
