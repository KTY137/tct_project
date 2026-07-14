# GlassShell cockpit — Round 03

| | |
|---|---|
| **Topic** | Candidate C's spirit, built on **our own glass** — app-owned frost over an app-owned ground |
| **Forged by** | Brokkr, 2026-07-14 |
| **Status** | Awaiting the attack pass (Loki / Baldr / Mary), then Kaya |
| **Kaya's order** | *"unser eigenes Glass wäre robuster … näher an den Designs"* · *"Kandidat C ist am besten"* · *"lass den Schmied jedes Panel nach Kandidat Cs philosophy designen"* · *"auch wenn wir Regeln biegen und brechen müssen"* |
| **The inversion** | **We render the glass. The OS is the garnish.** In-scene frost over app content — measured clean at 59–60 fps (`bbe3b10`) — and the bake makes the steady-state cockpit **+0 pp**. |

## Open these — in this order

1. **[`kit.html`](kit.html)** + **[`kit.md`](kit.md)** — THE GLASS KIT. The component language, its
   alphas, its blur radii, and a contrast meter that **scans all 24 legal states on load**. Build this first.
2. **[`panel-bias.html`](panel-bias.html)** + **[`.md`](panel-bias.md)** — the hazard panel. Glass around an opaque stone.
3. **[`panel-scope.html`](panel-scope.html)** + **[`.md`](panel-scope.md)** — the live-plot panel. Glass beside an island, never on it.
4. **[`panel-analysis.html`](panel-analysis.html)** + **[`.md`](panel-analysis.md)** — 2203 lines. The language survives complexity.

Every HTML is self-contained, double-clickable, and carries **Theme × Tier × Garnish × Desktop**
switches. **They run their own switches on themselves** — round 01's sin (shipping alphas below the
repo's `MIN_PANEL_GLASS_ALPHA` floor, hero text at 1.04 : 1) does not repeat.

---

## 1. What changed from round 02 — the corpse round 02 left, and why this is not it

Round 02 killed glass for a *derived* reason: an in-scene pane has nothing to blur because the
workspace is a QWidget tree DWM never frosts. **Kaya refuted it in one sentence: your own mockups never
used DWM glass — CSS `backdrop-filter` blurs the app's own content.** The look he wants was always
app-owned glass over an app-owned ground.

| | **Round 02 (AMBIENT won-ish)** | **Round 03 (this)** |
|---|---|---|
| Where the glass is | The DWM window gutter. That is all. | **App-owned ground → shelf → card**, everywhere. |
| Glass over app content | Never — "an in-scene pane blurs nothing" | **Always** — the pane blurs the ground beneath it, in-page. |
| The backdrop a card composites against | The desktop (unbounded → 4 tokens failed AA on glass) | **A token we own, band-limited to ΔL\* 4** → every ink passes. |
| CPU | +0 (no glass) / +13–26 (STRUCTURAL) | **+0 resident** (the bake); +13 only for one transient overlay. |
| Depth mechanism | tone + border (RDP-survivable) | **edges first** (free, survivable) + **baked frost** (the reward). |
| FLAT cost | AMBIENT *is* the FLAT design | **Nothing lost** — FLAT and SCENE are the same tones ± ΔL\* 1.0. |
| The look Kaya asked for | Refused ("did not do the visionOS move") | **Delivered** — content seen through chrome, on our terms. |

**Round 02's `card` token survives and is load-bearing here too** (dark `canvas→panel` is ΔL\* 1.46 —
invisible). Round 03 adds one more (`shelf`) and inherits `hairline_strong`-as-mandatory-outline. The
big new idea is the **GROUND BAND LAW** (§1.1 of the kit): bounding the ground to ΔL\* 4.0 is what makes
contrast-on-glass *computable* — the thing round 01 got fatally wrong and round 02 could only bound by
retreating to opacity.

---

## 2. Contrast at the floor — both themes, worst legal ground

The design **is** the worst legal case: every alpha at or above the ratified floors
(`MIN_BACKDROP_CANVAS_ALPHA 0.80`, `MIN_PANEL_GLASS_ALPHA 0.50`), computed against the worst legal
*opaque* ground. **The desktop cannot reach a card** — the shipped underlay law paints panels opaque
over any DWM material, so garnish and desktop are provably irrelevant to card/shelf contrast (toggle
them in `kit.html`; the numbers do not move). Model calibrated to six numbers the repo states about
itself (see kit §6).

### 2.1 On a glass CARD (SCENE tier) — the workhorse surface

| ink | DARK | LIGHT | AA |
|---|---|---|---|
| `text` | 13.88 | 16.66 | ✓ |
| `muted` | 6.28 | 6.35 | ✓ |
| `good` | 8.63 | 5.40 | ✓ |
| `armed`/`warn` | 9.46 | 5.50 | ✓ |
| `danger`/`crit` | **5.32** ← thinnest legal | 6.08 | ✓ |
| `accent` | 6.65 | 5.45 | ✓ |
| `sim` | 9.37 | 5.67 | ✓ |
| `faint` | 2.80 | 2.61 | ✗ retired for text (repo law) |

### 2.2 On the SHELF (chrome + labels only — `text`/`muted` the only legal inks)

| | DARK (SCENE) | LIGHT (SCENE) |
|---|---|---|
| `text` | 14.76 | 15.39 |
| `muted` | 6.68 | **5.86** ← the thinnest shelf number |

### 2.3 FLAT / TOKEN / WINDOW — every surface opaque, identical to the card table ±, desktop-independent.
Nothing to composite; the numbers are the opaque-token numbers, always ≥ the SCENE numbers above.

### 2.4 The two named failures, and the rules that close them

| surface | failing ink | ratio | rule |
|---|---|---|---|
| **light `well`** | good 3.92 · warn 3.97 · accent 3.97 · sim 4.12 · crit 4.41 | ✗ | **§4.4 — a well never carries semantic-coloured text** (this is a bug in the *shipped* app today) |
| **glass over an island** | dark text over camera **3.02** · light muted over PLOT_BG **1.80** | ✗ | **§4.5 — no glass on, over, or touching an island** |

Everything else passes AA at every tier, both themes, worst legal ground. `kit.html` recomputes this
live and prints **`24 legal states — all pass`** on load (the 6 distinct theme×tier cases each stand
for their 4 garnish/desktop corners, which are identical by the underlay law). If it prints a FAIL,
believe the file over this table.

---

## 3. The remaining 10 panels — C's philosophy, the same five surfaces

The three hard ones (bias, scope, analysis) cover every failure mode. The rest fall into two buckets
(Shiori's census, from the brief). Each is composed from the kit; none invents a surface.

| panel | lines | bucket | shell | hazard surface | islands | notes specific to it |
|---|---|---|---|---|---|---|
| **Scan Planner** | 2524 | program | shelf | — | 1 (setup preview) | Recipe-tree as nested **cards** with the axis-rail colours (`AXIS_RAIL`); the tree editor is `well`-rows on a card. Deepest non-analysis nesting. |
| **Motor Stage** | 1212 | program | shelf | **yes — motion** (homing/jog are law-5) | 1 (2D setup view) | The `HazardSurface` here uses the **`armed`** stripe (amber+hatch), not `danger`. Jog pad = opaque `well` grid. Setup view = island. |
| **Camera** | 958 | program | shelf | — | **1 (the live frame — the strictest island)** | The frame is the hottest island in the app: opaque, no glass within 12 px, ROI overlay drawn *in* the island, never as a glass pane over it. |
| **Scan Sequencer** | comp | composition | shelf | inherits scan-start ceremony | — | Step list = `well`-rows on a card; the Start control is the danger ceremony (Arm→Execute), on a `HazardSurface`. |
| **Calibration** | comp | composition | shelf | — | 1 | Card of `well` inputs + one plot island. Straight kit application. |
| **Laser / Trigger** | comp | composition | shelf | **yes — laser enable** | — | Enable is law-2 dangerous → `HazardSurface` + `ArmLatch`. Everything else glass. |
| **Intensity Monitor** | comp | composition | shelf | — | 1 (strip-chart) | Hero tile + one island. The tile is opaque; the strip-chart is an island. |
| **Scan Viewer** (scan_map) | comp | composition | shelf | — | 1 (the map) | Same island framing as analysis's map mode; colorbar is part of the island. |
| **Device Manager** | comp | composition | **own window** | — | — | A separate top-level → its **own ground** (the seam, §10.4). Rows of device cards + `chip` state each. |
| **Stage View** | comp | composition | shelf | — | 1 (2D, RTT-free) | Now 2D-only (`b7f88a3`) → a plain island, no GL child, no path-D concern. |

**The one rule the table encodes:** a panel that *acts on hardware dangerously* (motor, laser,
sequencer-start, bias) carries a `HazardSurface`; every other panel is pure glass + islands. Danger is
always the panel's, never the shell's (Kaya, ratified).

---

## 4. What rules I broke, and why each was a belief not a consequence

**BROKE (beliefs — attack them):**
- *"No live `ShaderEffect`/`MultiEffect` glass."* Kaya lifted it; `bbe3b10` measured it clean at 59–60 fps.
  I go further: the **bake** means we barely need it live at all (+0 pp resident).
- *"Glass is ambient only / panels are opaque cards."* Round 02's corpse. Every panel is glass now,
  except the surfaces the *consequence* rules keep opaque.
- *"The window material is the foundation."* Inverted: **the app-owned ground is the foundation; DWM is
  garnish.** This is why it is identical on Windows, Linux and RDP.
- *v6 "cards recede toward the canvas."* Partially reversed by the `card` token — needs Kaya's nod (§5).

**DID NOT BREAK (consequences — a human is at a probe station):**
- Hazard surfaces opaque at every tier (candidate C already did this byte-for-byte).
- Danger belongs to the panel, never the shell.
- Detachable panels permanent; `detachable_tabs.py` stays the engine.
- WCAG 2.2 AA at every tier, worst case, real numbers (§2).
- No blur over hot-path islands (+13 pp, and 3.02 : 1 — measured).

---

## 5. CPU cost — how many blurred panes × ~13 pp

| state | live blurred panes | cost |
|---|---|---|
| **Cockpit, any panel, any number of cards** | **0** (the bake — one static frost texture, sampled) | **+0 pp** |
| One overlay / drawer / drag-ghost open, idle | 1 (`GLASS_LIVE_PANE_BUDGET = 1`) | +13 pp, transient |
| **Anything during a scan** | **0** (overlays go opaque mid-run) | **+0 pp** |
| Anything over an island | **0** (forbidden) | +0 pp |

Round 02 costed STRUCTURAL at +13 resident / +26 with the drawer. **The bake is cheaper than the OS's
own material** — which is the technical core of *"unser eigenes Glass wäre robuster."*
**Caveat: the bake is unbuilt and unspiked (see §7).**

---

## 6. Cost in beats — honest

| work | beats | note |
|---|---|---|
| `card` + `shelf` tokens, `hairline_strong` promotion, shadow ladder, `RADIUS_SHELF` in `style.py`/`qml_theme.py` | 2 | additive; every panel repaints at once via shared QSS |
| The **bake**: static ground-frost texture + position-sampled QWidget `paintEvent` + QML `ShaderEffectSource` path | **4–6** | **the risk.** Needs a 2 h spike FIRST (§7). |
| `HazardSurface`, `Island`-framing, `Pane`/`shelf` primitives in `gui/panel_kit.py` | 3 | `Card`/`Well`/`Tile`/`ArmLatch` already exist |
| Re-skin the 3 hard panels | 3 | one each |
| Re-skin the remaining 10 | 5 | mechanical once the kit + hard panels land |
| Composited-contrast CI test (the suite has none — it is why round 01 shipped 1.04 : 1) | 1 | non-optional |
| The one vitals-projection (C's mechanic, reduced to a single summary tile per panel) | 1 | optional |
| **Total** | **~19–21** | vs round 02's board-mechanic estimate of **47–64**. Taking C's *language* and leaving C's *mechanic* is where the 30 beats went. |

---

## 7. What the attack pass should hit hardest

1. **The bake is unbuilt and unspiked, and it is the load-bearing claim.** "+0 pp resident" and "our
   glass is cheaper than DWM's" both rest on a position-sampled QWidget `paintEvent` that has never
   run. This project's own rule is *"consensus is not evidence — measure with a spike first."* **Do not
   let this design be built before a 2 h spike proves the QWidget frost-sampling path.** If it fails,
   the fallback is live `MultiEffect` at +13 pp per pane, and the whole cost story changes.
2. **The `card` token reverses a pass Kaya ratified 2 days ago.** Without it the dark ladder is ΔL\* 1.46
   and the cockpit is invisible across the room. With it, every dark screenshot shifts. This is a yes/no
   that decides whether the round has a winner (§ open questions).
3. **The blur does almost nothing (kit §5.2), and I said so.** A band-limited ground survives a blur
   nearly unchanged. If Kaya toggles FLAT↔SCENE and shrugs, he is right, and raising the blur is the
   wrong fix (it pushes against the band law and "instrument, not media player"). **This tension is the
   center of the round and I bounded it rather than resolved it.**
4. **The system floor is dark `crit` on a glass card at 5.32 : 1** (and light `muted` on a shelf at
   5.86) — under 1.0 of margin, riding on the `card`/`shelf` alphas and the light canvas. One careless
   tweak eats it, and **there is no composited-contrast CI test yet** (§6 lists it as non-optional).
5. **The detached-panel seam** (§10.4): a torn-off panel gets its own ground and looks subtly different —
   worst at the bias/HV panel, the one most likely to be torn off.
6. **I still have not stood 4 m back from the lab monitor.** Every "across the room" claim — including
   the ΔL\* 7.16 that justifies `card` — is a model, not an observation.

---

## 8. Open questions for Kaya

1. **May I add the `card` and `shelf` tokens** (partial reversal of the v6 "cards recede" pass, dark
   theme only, card+container bodies only)? **No kit exists without this.**
2. **Spike-first?** Do you want the QWidget baked-frost spike (2 h) before any of this is built, per your
   own 2026-07-14 rule? I strongly recommend yes.
3. **The light theme's glass is quieter than the dark theme's, by arithmetic** (a translucent white card
   cannot reach L\* 100). Is the **dark theme the glass theme**, with light being the flat-but-legible
   fallback? Or must both feel equally glassy (which light physically cannot)?
4. **Is the lab's normal mode local or RDP?** (Round 02's decisive question, still unanswered.) If RDP,
   the whole fleet runs at TOKEN — which here is *fine* (FLAT/TOKEN lose nothing but the position-varying
   tint), unlike round 02 where STRUCTURAL's whole idea evaporated. But it changes whether the bake is
   worth building at all.
5. **The one salvaged C mechanic** — a single optional vitals-projection tile per panel (bias/motor/
   scan/scope), rendered by the status strip. In, or out? It is ~1 beat and needs no layout engine.
6. **Should the composited-contrast CI test land regardless of the winner?** The suite has none; it is
   exactly why round 01's 1.04 : 1 shipped.
</content>
