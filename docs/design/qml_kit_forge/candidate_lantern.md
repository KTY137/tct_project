# CANDIDATE — LANTERN

> **One material, lit from within.** Every component is the same `Surface` at a different
> rung; depth, focus, and motion are properties of the *material*, not of components. The
> living ground is not a feature bolted behind the panes — it is the light source the whole
> kit is built around.

| | |
|---|---|
| **Thesis** | The design authority is the scene: one material system (rung + baked frost + edge ladder + springs) from which every component is composed. This is the kit that finally renders the `design_assets/` plates. |
| **Optimizes for** | The reference look (Vision Pro dashboard: tones barely apart, depth from edges and light), one implementation of glass instead of sixteen, QML's artifact≈implementation advantage |
| **Deliberately sacrifices** | Visual parity with the classic shell during the U-window; simplicity; it stands on one unspiked mechanism (the frost bake) and says so |
| **Forged by** | Brokkr, 2026-07-15 (U1.5 lean round, paper only) |
| **Revised** | Brokkr, 2026-07-15 — post-attack batched pass, implementing Adam's six rulings (DECISIONS.md 2026-07-15 "Post-attack-pass rulings"; attacks: `attack_loki.md`, `attack_baldr.md`). §10/§12 stand as the forge-time record; the attack files supersede them where they disagree. |

---

## 1. Philosophy in one line

**Components don't own paint; the material does.** In the visionOS plates the cards are a
tone apart and everything that reads as depth is edge + light + frost. Lantern makes that
literal: a single `Surface` primitive resolves fill/frost/edges/shadow/focus/motion from its
`rung`, and all sixteen components are `Surface` + content. Change the material once, the
whole cockpit follows — the exact modularity Vorschrift 2 demanded.

## 2. Problem solved / why-now

- **Problem:** the ratified direction is *owned glass* ("we render the glass; the OS is the
  garnish", DECISIONS 2026-07-14) and candidate-C's language ("glass cards, real
  translucency, structural depth") — but the shipped QWidget kit can only *approximate* it
  (QSS has no real alpha compositing, no inset shadows, no frost). The QML shell is the first
  renderer that can implement the ratified look natively. Building the QML kit as another
  approximation wastes the one chance the U-track was created to take.
- **Why now:** U2 (hero slice) implements this kit as reference. If the material system is
  not specified now, U2 improvises it and every later panel inherits the improvisation.

## 3. The material core

### 3.1 `Surface` — the one primitive

```qml
Surface {                       // conceptual API, spec-level
    rung: Surface.Card          // Shelf | Card | Tile | Well | Island | Hazard
    interactive: true           // enables hover/press/focus material responses
    // content slot(s)
}
```

Resolution per rung (all values from `Theme.*`; SCENE column only when the told tier is
SCENE — FLAT/TOKEN render the opaque rung token, per the round-03 tier-invariance rule):

| rung | FLAT/TOKEN fill | SCENE fill (one rung up @ alpha) | frost | edges | shadow |
|---|---|---|---|---|---|
| Shelf | `shelf` | `card` @ `glassPaneAlpha` | sampled, deep (blurPane) | `hairlineStrong` + `specular` | `shPane` |
| Card | `card` | `raised` @ `glassCardAlpha` | sampled, shallow (blurCard) | `hairlineStrong` + `specular` | `shCard` |
| Tile | `raised` | `raised` (opaque, always) | none | `specular` | contact only |
| Well | `well` | `well` (opaque, always) | none | `edgeShade` | none |
| Island | `plotBg` | `plotBg` (opaque, always) | none | `hairlineStrong` + `edgeShade` | none — and none may fall on it |
| Hazard | `panel` | `panel` (opaque, always) | **refused** | `hairlineStrong` + stripe + hatch | none |

`Surface` **throws at construction** on `rung: Hazard` with any glass/frost/shadow-response
flag — the QML twin of `register_glass_pane`'s refusal. Hazard and Well have no SCENE form
at all: the material system cannot express a translucent hazard even by bug.

### 3.2 The frost bake — one blur, every pane (the load-bearing mechanism)

- The living ground (§7) renders into a `ShaderEffectSource`; **one** blur pass produces the
  FROST texture (this is the only `MultiEffect` in the entire application, and it runs on
  the *source*, never per pane).
- Every Shelf/Card at SCENE samples FROST at its own scene rect (`ShaderEffect` +
  `sourceRect`), tints with its rung fill at its rung alpha, then draws its edges. Panes are
  ~free samplers; cost scales with ground *changes*, not with pane count.
- Re-bake cadence is bounded and state-driven: ground static → 0 Hz (a still cockpit costs
  nothing); living ground "subtle" → 6 Hz; "full" → 12 Hz. **During a scan the bake keeps
  running at the idle rate** — the ratified calm is panel-scoped (kit.md §1.2; DECISIONS
  2026-07-15), so the room keeps flowing and the one shared bake must keep serving it; only
  the run-owning pane freezes its own sampler (§7). *(Reconciled 2026-07-15, Loki BLOCKER-1:
  this bullet previously said "scan RUNNING → 0 Hz", which described the pre-ratification
  global calm and is retired.)*
- This is kit.md §5 and `glass_env.py`'s own SCENE docstring ("baked, position-sampled
  frost"), realized QML-natively. **Measurement A — the frost-bake spike — ran 2026-07-15
  on the lab iGPU and the O(1)-in-panes premise HELD** (min QML fps 59.98, island ≥ 30.31 Hz,
  stable through 8 panes @ 12 Hz; `attack_loki.md`, concessions). What A did *not* measure
  is the bake running through a real acquisition load — **measurement B, the
  acquisition-headroom spike (§7), is the U2 entry gate.**

### 3.3 The edge ladder, finally composited honestly

QSS approximated the machined edge with `border-top-color`; the scene does it for real:
`specular` as a true alpha line, `edgeShade` as a real inner gradient, and the round-03
shadow ladder as **new Theme constants** (named, derived — kit.md §8): `shadowInk`,
`shadowA..D` → assembled as `shCard`/`shPane`/`shFloat`. Shadows are pre-rendered 9-patch
`BorderImage`s (no live drop-shadow effect anywhere — effects budget stays spent on the one
frost blur).

## 4. Component inventory

Same capability set as `gui/panel_kit.py` — zero loss — but every component is `Surface` +
content, and its states are *material responses* (§5):

Pane/Shelf, Card, CheckableCard, CollapsibleCard, MetricTile, MetricGrid, StatusPill,
ActionBar (primary/secondary/motion/danger classes), SegmentedControl (track = Well rung,
thumb = Tile rung), Well, EmptyState (+error variant), PanelHeader/SectionHeader/Eyebrow/
FormRow, FigureCard (= Island rung frame around the reserved hole), HazardSurface (= Hazard
rung + stripe/hatch/word/glyph channels), LivingGround.

## 5. Interaction states — material responses, one definition

Defined ONCE on `Surface` (interactive rungs only); components inherit. Every response
keeps a non-material channel too (ring shape, ink change, word) — state never rides the
material alone, because FLAT has no material.

| state | material response (SCENE) | tier-independent channel (survives FLAT) |
|---|---|---|
| idle | rung resolution §3.1 | — |
| hover | shadow one step up (`shCard`→`shPane` scale) + `specular` brightens one step | border → `hairlineStrong` |
| focus | **luminous ring**: 2 px `accent` ring + 8 px soft halo (pre-rendered `BorderImage`, not an effect). **Offset convention (DECISIONS ruling 3): the ring is drawn entirely OUTSIDE the component's fill boundary**, at `focusRingOffsetPx` beyond the edge, so it always reads against the *surrounding* rung surface — accent-ring-on-accent-fill is a non-case by construction (§6) | the 2 px ring itself — ≥3:1 non-text contrast against every rung composite, enforced by the standing `ring_contrast_scan` check landing in `kit_contrast_check.py` (walks every rung's SCENE+TOKEN composite AND every interactive fill token; the forge-time "audited" claim was unbacked — attack_baldr.md BLOCKER-2) |
| pressed | shadow one step down, fill → `pressed` | fill token change |
| disabled | frost sampling OFF (pane goes opaque `disabled_bg`) | ink → `muted` |
| danger | none — the material is DEAD on hazard rungs: no hover lift, no frost, no halo. **The focus RING is not material and is ALWAYS present on hazard rungs; only the halo never appears there** (DECISIONS ruling 4) | `danger_fill`/`on_danger` + stripe/hatch/word/glyph + the focus ring |
| running | ground calms behind the run-owning pane only; room-wide effective speed clamps to ≤ 1.0× (§7); live lamps pulse (same 1200 ms law as the classic shell) | run chip word + colour |
| stale / sim (modifiers) | none — **staleness is ink-only, never an opacity dim** (DECISIONS ruling 2: the shipped `MetricTile.qml` 0.6 dim measured every semantic ink below AA and is retired; any opacity cascade over semantic ink caps at ≥ 0.94 dark / ≥ 0.91 light — attack_baldr.md BLOCKER-1; kit.md §4.3) | ink `muted` + caption / `sim` ink + WORD |

Hit targets: interactive ≥ 36 px, motion/danger class ≥ 44 px. Keyboard: all interactive
surfaces `activeFocusOnTab`; the luminous focus ring is the *same component* everywhere, so
focus visibility is audited once, per rung, not per widget.

## 6. Token binding

Everything through `Theme.*`. Lantern requires the Twin parity-audit exposures
(danger_fill/on_danger/on_armed, chip, edge/edge_shade, pressed/disabled_bg, radius
xl/shelf, font/weight roles, glass alphas, motionEnabled) **plus mints, with derivations**:

| new token | value (derived) | source of derivation |
|---|---|---|
| `shadowInk` | dark `#000000` / light = text hue | kit.md §3.1 (ratified round-03 table) |
| `shadowA..D` | .20/.24/.30/.55 dark · .06/.08/.10/.22 light | kit.md §3.1 |
| `blurPane/blurCard/blurOverlay` | 40 / 16 / 28 px | kit.md §8; shallower = closer |
| `frostRebakeHzSubtle/Full` | 6 / 12 | held by measurement A (2026-07-15 spike: fps 59.98 / island ≥ 30 Hz through 8 panes @ 12 Hz); measurement B (§7) may still lower them |
| `focusHaloAlpha` | 0.35 dark / 0.25 light | smallest alpha where the halo reads on `shelf` yet the 2 px ring alone still carries ≥3:1 (ring is the accessible channel; halo is garnish — it never appears on hazard rungs and never enters a dead zone; §5, §8) |
| `focusRingOffsetPx` | 2 | ruling 3's offset convention: the ring sits outside the fill boundary by its own width — clears the 1 px `hairlineStrong` outline so the ring reads against the surrounding rung, never the component's own fill or edge treatment; matches the shipped QSS precedent (`outline-offset`), so both shells share one convention |
| `groundFlowPeriodS` | 90 s base; **effective period = `groundFlowPeriodS` / speed**, speed ∈ 0.25–2.0× (2.0× ⇒ 45 s — the formula was unstated, Baldr MINOR-2) | slow enough that WCAG 2.3.1/2.3.3 flash/motion thresholds are not approached; run-active clamp in §7 |

All shadow/blur/frost numbers live in `gui/style.py` and surface through Theme — one source
of truth, both engines can read them even though only the QML one renders them.

## 7. Living glass — layer 0 and the light source

The ground **is** the material's input, which is why Lantern treats Kaya's scope addition
as the organizing principle rather than a feature:

- **Look:** two accent washes drifting on slow closed Lissajous paths + a slow specular
  sweep — liquid light behind glass, `full` amplitude ≈ the wash offsets moving ~8% of the
  viewport over `groundFlowPeriodS`; `subtle` = half amplitude, half speed.
- **Setting:** `theme/living_glass ∈ {off, subtle, full}` + speed, persisted. **Default:
  subtle** — Lantern's identity is a living material; off remains one click away and is the
  documented accessibility posture.
- **Band law per frame (constitution-grade):** washes move position, never alpha; summed
  tint ≤ `GROUND_TINT_ALPHA_MAX` (0.07) at every pixel of every frame → the ΔL* 4.0 band
  holds for any frame → every contrast number in kit.md §6 is frame-invariant. A test
  renders N random phases and asserts the band.
- **No semantic tint, ever.** The flow may not change hue toward any state colour.
- **Reduced motion** (`Theme.motionEnabled == false`): static ground, frost still baked once
  — the *look* survives, the *motion* doesn't. FLAT: nothing; TOKEN: static wash.
- **Auto-calm — PANEL-SCOPED (ratified refinement; kit.md §1.2, DECISIONS 2026-07-15):**
  RUNNING → the ground stills **behind the panel that owns the run only**: its wash
  amplitude eases to 0 over 1200 ms and the pane **stops scheduling its own
  `ShaderEffectSource` update — mechanism (a) — holding a stale crop** of the shared FROST
  texture. The rest of the room keeps flowing, and the shared bake keeps running at the
  idle rate (6/12 Hz per setting, §3.2). A detached panel is its own top-level with its own
  ground and calms whole. Which panel "owns the run" resolves through `run_state_facade`
  only.
- **The stale-crop drift seam, named (Loki MAJOR-2):** the frozen crop is a snapshot of the
  ground at T₀ while the surrounding live ground drifts up to ~8% of the viewport over
  `groundFlowPeriodS` — a phase discontinuity at the run-owning pane's edge that grows over
  the run. Its visual acceptability is an **open item for the U2 reference-implementation
  review** (it needs rendered pixels, not prose); if it fails that review, the candidate
  fallback is easing the *neighbouring* washes toward a shared static phase around the calm
  region, at re-measured cost.
- **Run-active speed clamp (law, DECISIONS ruling 1 — sits alongside reduced-motion):**
  whenever ANY run is active anywhere in the app, the living-glass **effective speed clamps
  to ≤ 1.0× app-wide**; the persisted 0.25–2.0× range applies in full only while the whole
  app is idle. The room keeps flowing — panel-scoped calm stands — but it can never reach
  its fastest drift while a beam is on: the un-clamped worst case was full × 2.0× ≈ 8% of
  the viewport per 45 s in panels the operator watches during the same acquisition
  (attack_baldr.md, MAJOR). Precedence: reduced-motion (static) → run-active clamp (≤ 1.0×)
  → persisted setting.
- **The honest standing-cost statement (retires the forge-time claim):** this spec
  previously promised "zero material cost during acquisition / SYNTHESIS §4.3 honored by
  the same mechanism". That described the pre-ratification *global* calm and is **RETIRED**
  (Loki BLOCKER-1). True behavior during a scan: the idle-rate bake + living ground keep
  running (ground alone measured ≈ 53.5% of one core baseline on the lab i7-10510U; bake
  O(1) in pane count — measurement A, 2026-07-15). **Measurement B — the
  acquisition-headroom spike — is the U2 entry gate:** idle-rate bake + living ground at
  `full`, running through a live *simulated* scan (sim DeviceManager + scan controller +
  HDF5 writer + a 30 Hz plot island) on the lab laptop, asserting the plot holds rate and
  DAQ cadence does not jitter. If B fails, the fallback is run-active global calm (bake →
  0 Hz app-wide), which returns the panel-scope refinement to Kaya with the numbers.
- **Run-cue note (supersedes the forge-time anti-inference note):** *whole-app* stillness
  stays deliberately ambiguous (calm is also entered on reduced-motion and `off`). A
  *locally*-calm pane in a flowing room does correlate with the run — permitted as a
  **redundant** cue and never the only one (kit.md §1.2): the run chip stays the indicator;
  state never by motion alone.

## 8. Coexistence with the widget islands

- Islands and safety instances: identical hole-and-frame mechanism as candidate Twin §8
  (reserved rects, kit draws frames only, never overlaps; emergency shortcuts stay on the
  top-level QWidget path; no app-wide `Shortcut` in kit code; z-order + key-injection gates
  per Codex BLOCKER-2).
- **Lantern adds a hard material law:** island and hazard rects are registered with the
  frost system as **dead zones** — no pane may extend translucent pixels within `spaceMd`
  of them by ANY of the kit's three translucent-pixel mechanisms: **{sample, shadow, halo}**
  (frost sampling §3.2 · the 9-patch shadow ladder §3.3 · the focus halo §5 — enumeration
  extended 2026-07-15, DECISIONS ruling 5; the halo was the unnamed third channel,
  attack_baldr.md MAJOR). This is a *runtime geometric assertion* in debug builds and an
  offscreen test (walk all Surfaces × all holes × all three mechanisms), not a convention.
  The §3.1 "no shadow onto an island" law becomes checkable.
- Detached panels (`detachable_tabs.py`, LOCKED): each top-level window owns its own ground
  + frost. A torn-off card therefore samples a *different* ground — the material "lies" at
  the window boundary (round-02's finding, still true). Lantern accepts and documents it:
  same tones (the band law bounds both grounds identically), different frost phase.

## 9. Motion spec — springs as identity

- **Interactive geometry springs:** `SpringAnimation` (spring 3.0, damping 0.32 — named as
  `MOTION_SPRING_UI` in style.py) on: SegmentedControl thumb, CollapsibleCard unfold,
  StatusPill width changes, drawer/overlay entrance. Colour/opacity stay `Behavior` eases at
  `Theme.transitionMs`.
- **Scale:** `motionTap` 120 ms (hover/press), `motionState` 200 ms (= transitionMs, state
  ink/fill), `motionUnfold` 280 ms OutQuint (structural reveals).
- **Reduced motion:** springs collapse to snap; only ≤100 ms opacity crossfades remain.
- **Loop budget:** lamp pulse + living ground. Nothing else may loop (lint, same as Twin).
- **During RUNNING:** springs stay (they respond to *operator* action — motion from user
  interaction is exempt from the distraction gate); ambient motion calms behind the
  run-owning pane and clamps to ≤ 1.0× everywhere else (§7).

## 10. Alternatives considered inside this candidate

- *Live per-pane `MultiEffect` blur instead of the bake:* rejected — measured +13 pp CPU per
  pane on the iGPU (round-02/round-03 numbers); the budget allows one transient pane, which
  Lantern reserves for the modal/overlay case only (`GLASS_LIVE_PANE_BUDGET = 1`, never
  during a scan, never over an island).
- *Real drop-shadow effects instead of 9-patch `BorderImage`s:* rejected — spends the
  effects budget on chrome; pre-rendered shadows are pixel-identical and free.
- *Per-component state styling (no Surface base):* rejected — sixteen hand-made glass
  implementations is how drift and the round-01 1.04:1 class of bug return.
- *Default living-glass = full:* rejected — full is a demo posture; subtle is the identity
  without the fatigue.

## 11. Safety & operational implications

- **Safety:** the hazard rung is a material dead zone by construction (throws, not
  convention); hazard channels are all tier-independent. The risky surface is *indirect*:
  frost/shadow/halo near islands — hence the dead-zone geometry assertions. Auto-calm reads
  run state through the facade VM only. The material never encodes tier or hazard state
  (glass_env laws untouched); the panel-scoped local calm is at most a *redundant* run cue,
  never the only one (kit.md §1.2 — the chip stays the indicator). On hazard rungs the focus
  ring is always present; the halo never (§5, DECISIONS ruling 4).
- **Operational:** the QML shell will visibly diverge from the classic shell from U2 onward.
  That is ratified ("classic is functional fallback, no longer a design target") but it has
  real costs: two sets of screenshots during the window, operator retraining at U6, and
  Mary reviewing a new visual language rather than a port. The payoff is the actual point of
  the migration: the cockpit finally looks like the plates Kaya collected.

## 12. Weaknesses (attack here)

1. **The whole kit stands on the unspiked bake.** ShaderEffectSource + per-pane sourceRect
   sampling + a pyqtgraph island at 30 Hz on the bench iGPU has never been measured. If the
   spike fails, Lantern degrades to "translucent fills + edges" — which is candidate Twin
   with springs, and the round should have picked Twin honestly instead.
2. **Frost re-bake at 6–12 Hz is a standing GPU cost** while living glass is on and no scan
   runs. On the lab laptop's iGPU this may contend with pyqtgraph refresh even *outside*
   acquisition. The auto-calm covers scans, not idle monitoring with live plots.
3. **The window-boundary lie:** detached panels sample a different ground; a card subtly
   changes when torn off. Accepted and documented — but "documented" is what round 02 said,
   and Kaya notices things.
4. **The luminous focus halo flirts with the alarm-adjacent.** An accent glow near a warn
   chip could read as state at a distance. Mitigation: halo alpha is low, hue is `accent`
   only, hazard rungs refuse the halo (dead material) — but this is exactly the class of
   thing Baldr should try to break with a worst-case composition.
5. **Divergence during the U-window is operator-visible** and irreversible panel by panel: a
   half-migrated cockpit is half-Lantern, half-classic — visibly two apps in one window
   until U6 closes. The per-stage merge gates make this months, not days.
6. **Springs + material responses raise the review floor:** every interactive component now
   has animated geometry near real hardware controls; Mary must review motion (timing,
   interruption, teardown of running animations at panel close — the immortal-panel lesson)
   as a first-class concern.
