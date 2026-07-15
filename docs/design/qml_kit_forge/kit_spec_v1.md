# QML COMPONENT-KIT SPEC — v1 (BINDING)

> **One material, lit from within. Components don't own paint; the material does.**

| | |
|---|---|
| **Status** | **RATIFIED — signed by Kaya 2026-07-15** (DECISIONS entry "U1.5 kit spec v1 signed"); §7.1 thresholds RATIFIED unchanged after the live measurement-B PASS same day (DECISIONS entry "U1 CLOSED, U2 entry gate PAID") — nothing in this spec remains open |
| **Assembled by** | Brokkr, 2026-07-15 (U1.5 kit-spec consolidation beat — consolidation only, zero new design) |
| **Supersedes as the working reference** | nothing is deleted — this document is the single *binding* surface over its sources; the sources remain the lineage record |
| **Sources (ratified truth)** | `docs/design/qml_kit_forge/candidate_lantern.md` (post-revision, c11b580) · `docs/design/iterations/glasshell-cockpit/round-03/kit.md` (ratified kit contract, incl. amended §1.2) · `docs/DECISIONS.md` 2026-07-15 rulings 1–8 · `docs/CODEX_QUEUE.md` §C13 (Theme-bridge audit) · `docs/design/u1_staging.md` §6 · `artifacts_claude/lantern_frost_spike_20260714T233707Z/` (measurement A) · `TCT_app/scripts/spike_measurement_b.py` (measurement-B harness) |
| **Precedence on conflict** | DECISIONS ruling → candidate_lantern (post-revision) → round-03 kit.md. Every conflict resolved under this rule is listed in Appendix B. |
| **Change mechanism** | §8 — amendments land in `docs/DECISIONS.md` first, then here; never the reverse |

**What Kaya signs:** §§1–6 as the binding kit contract for U2 and every later
U-stage, plus the Appendix A bridge table as the U2-entry plumbing contract.
§7 lists the items he explicitly rules on at the gate. Nothing in this document
is new — every clause traces to a ratified source; where sources disagreed, the
precedence rule above decided, on the record (Appendix B).

---

## 1. Scope — what this kit is, and its relationship to the QWidget `panel_kit`

### 1.1 Scope

This spec governs **every QML-rendered surface** built from U2 onward on the
`ui-qml-migration` track: the component kit, its material system, its state
model, its motion, its token bindings, and the laws that bound all four. It
does **not** govern the classic QWidget shell (which remains the functional
fallback, no longer a design target — DECISIONS 2026-07-14/15) and it does not
govern the never-migrates list (§1.4).

### 1.2 What carries over from `TCT_app/gui/panel_kit.py` (capability parity — zero loss)

The QML kit ships the **same capability set** as the QWidget kit. Carried over
unchanged in *meaning* (names, roles, ink laws, hazard channels):

- The component roster (§3) — every `panel_kit` class has a QML counterpart.
- The ink laws (kit.md §7): no value on a pane; no semantic-coloured text in a
  well; a well only ever sits on a card; `faint` is never text.
- The hazard surface's redundant channels: stripe (colour) · 45° hatch
  (texture) · eyebrow word (text) · glyph (shape) · position — all
  tier-independent, all surviving FLAT.
- The elevation ladder and its tokens (§2.2) — `card`/`shelf`/`RADIUS_SHELF`
  are **shipped** in `gui/style.py` and exposed by the Theme bridge (see
  Appendix B, note 2 — kit.md's ⚠PROPOSED flags are superseded by the tree).
- The glass-tier contract of `TCT_app/gui/glass_env.py` (`FLAT < TOKEN <
  WINDOW < SCENE`; `SAFE_FLOOR = TOKEN`): the material never encodes tier or
  hazard; every component is fully usable and legible at FLAT with zero
  information loss (tier-invariance rule, §2.3).
- `gui/arm_latch.py` and `gui/qt_danger_gate.py` as the ceremony engines —
  referenced, never re-implemented (§1.4).

### 1.3 What is QML-native (does not exist, and will not be back-ported, in the QWidget kit)

- The **`Surface` primitive** (§2.1) — one material, all components compose it.
- The **frost bake**: one `ShaderEffectSource` + one blur pass on the living
  ground; per-pane `sourceRect` crop-sampling (§2.4).
- The **living ground** as layer 0 and the frost source (§5.3).
- **Springs** as interaction identity (§5.1).
- The **luminous focus ring + halo** (§4.1) and the pre-rendered 9-patch
  shadow ladder (§2.5).

The classic shell keeps its QSS approximations; divergence during U1–U6 is
ratified ("classic = fallback, not design target", DECISIONS 2026-07-15).

### 1.4 Safety carve-outs — restated verbatim (constitution; NOT signed away by this spec)

From `docs/ROADMAP_MASTERPLAN.md` Part II §UI (PROTECTED):

> **NEVER migrates:** QtDangerGate modal, the 9 pyqtgraph/GL islands,
> camera raster QLabel, STOP/ALL-OFF/Abort QWidget instances, any
> second implementation of a safety control.

From `docs/DECISIONS.md` 2026-07-15 (delegation carve-outs, PROTECTED):

> Hardware safety rules 1–6 and every safety sub-clause of ratified entries
> (hazard-surface opacity, danger topology, the never-migrates list) remain
> PROTECTED and personal to Kaya — design authority is not safety authority.

Standing consequences inside this kit: hazard surfaces are opaque at every
tier; the shell displays, the panel acts (no hazard control in the shell);
emergency shortcuts stay on the top-level QWidget path; the kit draws *frames*
around island holes, never content into them.

### 1.5 Stage-gate context (ruling 8)

Every U2+ stage gate reports net LOC and an explicit delete list; a stage that
only adds does not pass. Deliberately retained code (safety controls, GL
islands, the never-migrates list) is ratified essence, never residue. U1 is
exempt. (DECISIONS 2026-07-15 night, ruling 8.)

---

## 2. The material system — `Surface`, the rung ladder, and the state table

### 2.1 `Surface` — the one primitive

```qml
Surface {                       // conceptual API, spec-level
    rung: Surface.Card          // Shelf | Card | Tile | Well | Island | Hazard
    interactive: true           // enables hover/press/focus material responses
    // content slot(s)
}
```

A single `Surface` resolves fill/frost/edges/shadow/focus/motion from its
`rung`; all components are `Surface` + content. Change the material once, the
whole cockpit follows. `Surface` **throws at construction** on `rung: Hazard`
with any glass/frost/shadow-response flag — the QML twin of
`register_glass_pane`'s refusal. Hazard and Well have no SCENE form at all.

### 2.2 The rung ladder (per-rung resolution; all values via `Theme.*`)

| rung | FLAT/TOKEN fill | SCENE fill (one rung up @ alpha) | frost | edges | shadow |
|---|---|---|---|---|---|
| Shelf | `shelf` | `card` @ `glassPaneAlpha` | sampled, deep (`blurPane` 40) | `hairlineStrong` + `specular` | `shPane` |
| Card | `card` | `raised` @ `glassCardAlpha` | sampled from the SHARED pane-depth bake (ruling 10: one blur, ever; `blurCard` 16 = reserved tuning token, unconsumed) | `hairlineStrong` + `specular` | `shCard` |
| Tile | `raised` | `raised` (opaque, always) | none | `specular` | contact only |
| Well | `well` | `well` (opaque, always) | none | `edgeShade` | none |
| Island | `plotBg` | `plotBg` (opaque, always) | none | `hairlineStrong` + `edgeShade` | none — and none may fall on it |
| Hazard | `panel` | `panel` (opaque, always) | **refused** | `hairlineStrong` + stripe + hatch | none |

Ladder tone values, both themes, and their derivations: round-03 kit.md §2
(`card = _blend(raised, panel, 0.60)` dark / `= panel` light;
`shelf = _blend(card, panel, 0.30)` dark / `_blend(panel, canvas, 0.50)` light).
Both tokens are **shipped** in `gui/style.py` (Appendix B, note 2).
Well lint (kit law): dark `well` sits below dark `canvas` — **a well only ever
sits on a card, never directly on the ground.**

### 2.3 Tier invariance — "paint one rung up, at your rung's alpha"

A glass surface paints the token one rung up, at its rung's alpha, so its
*composite* lands on the rung it belongs to. **The FLAT cockpit and the SCENE
cockpit have the same tones within ΔL\* 1.0; turning glass off changes nothing
that anything *is*.** FLAT/TOKEN render the opaque rung token. The full
per-tier fill table and composite arithmetic: kit.md §2.1. The contrast
receipts at the worst legal ground: kit.md §6 (machine-checkable via
`TCT_app/scripts/kit_contrast_check.py`).

### 2.4 The frost bake — one blur, every pane (the load-bearing mechanism)

- The living ground renders into a `ShaderEffectSource`; **one** blur pass
  produces the FROST texture — the only `MultiEffect` in the application, run
  on the *source*, never per pane.
- Every Shelf/Card at SCENE samples FROST at its own scene rect
  (`ShaderEffect` + `sourceRect`), tints with its rung fill at its rung alpha,
  then draws its edges. Panes are ~free samplers; cost scales with ground
  *changes*, not pane count.
- Re-bake cadence is bounded and state-driven: ground static → 0 Hz; living
  ground `subtle` → 6 Hz; `full` → 12 Hz. **During a scan the bake keeps
  running at the idle rate** — the ratified calm is panel-scoped (§5.4), the
  room keeps flowing, and only the run-owning pane freezes its own sampler.
- **Measurement A (2026-07-15, lab iGPU) HELD:** O(1) in pane count — min QML
  fps 59.98, island ≥ 30.31 Hz, CPU slope ≤ 1.37 pp/pane, stable through
  8 panes @ 12 Hz, 0/20 crashes
  (`artifacts_claude/lantern_frost_spike_20260714T233707Z/spike_report.json`).
- **Measurement B — acquisition headroom — is the U2 entry gate** (§7.1).
- **Honest standing-cost statement (Loki BLOCKER-1, reconciled):** the
  forge-time "zero material cost during acquisition" claim is RETIRED. During
  a scan, the idle-rate bake + living ground keep running (ground alone
  measured ≈ 53.5% of one core baseline on the lab i7-10510U).
- `GLASS_LIVE_PANE_BUDGET = 1`: one live `MultiEffect` pane, transient only
  (modal/overlay), never during a scan, never over an island.

### 2.5 The edge and shadow ladders

`specular` as a true alpha line, `edgeShade` as a real inner gradient,
`hairlineStrong` as the mandatory outline on every shelf/card/island/hazard
surface. Shadows are the round-03 ladder — `shadowInk`, `shadowA..D`,
assembled as `shCard`/`shPane`/`shFloat` — **APPROVED for promotion** into
`gui/style.py` + the Theme bridge (DECISIONS 2026-07-15, delegation entry);
they land in the U2-entry bridge beat (§6). Shadows render as pre-rendered
9-patch `BorderImage`s — no live drop-shadow effect anywhere. **Law: no
surface may cast a shadow onto an island** (subsumed by the dead-zone law,
§4.4). Concentric radii: `RADIUS_MD(12) + SPACE_SM(8) = RADIUS_XL(20)`;
`RADIUS_XL(20) + SPACE_XS(4) = RADIUS_SHELF(24)` (shipped).

### 2.6 The state table — material responses, defined ONCE on `Surface`

Interactive rungs only; components inherit. Every response keeps a
non-material channel — state never rides the material alone, because FLAT has
no material.

| state | material response (SCENE) | tier-independent channel (survives FLAT) |
|---|---|---|
| idle | rung resolution §2.2 | — |
| hover | shadow one step up + `specular` brightens one step | border → `hairlineStrong` |
| focus | **luminous ring**: 2 px `accent` ring + 8 px soft halo (pre-rendered `BorderImage`, not an effect), drawn entirely **outside** the fill boundary at `focusRingOffsetPx` (§4.1) | the 2 px ring itself — ≥3:1 non-text contrast against every rung composite, enforced by the standing `ring_contrast_scan` check (§4.2) |
| pressed | shadow one step down, fill → `pressed` | fill token change |
| disabled | frost sampling OFF (pane goes opaque `disabled_bg`) | ink → `muted` |
| danger | none — the material is DEAD on hazard rungs: no hover lift, no frost, no halo. **The focus RING is not material and is ALWAYS present on hazard rungs; only the halo never appears there** (ruling 4) | `danger_fill`/`on_danger` + stripe/hatch/word/glyph + the focus ring |
| running | ground calms behind the run-owning pane only (§5.4); room-wide effective speed clamps to ≤ 1.0× (ruling 1); live lamps pulse (1200 ms law, same as classic) | run chip word + colour |
| stale / sim (modifiers) | none — **staleness is ink-only, never an opacity dim** (ruling 2). Any opacity cascade over semantic ink caps at ≥ 0.94 dark / ≥ 0.91 light (measured legal ceiling); a dim that wants to read as "stale" dims chrome only (fill/border), never a node text inherits opacity from. The shipped `MetricTile.qml` 0.6 dim is retired | ink `muted` + caption / `sim` ink + WORD |

Hit targets: interactive ≥ 36 px; motion/danger class ≥ 44 px. Keyboard: all
interactive surfaces `activeFocusOnTab`; the focus ring is the same component
everywhere — focus visibility is audited once per rung, not per widget.

---

## 3. Component inventory — (role, state) → paint/motion obligations

Same capability set as `gui/panel_kit.py`, zero loss. Every component is
`Surface` + content; its states are §2.6 material responses. Per-component
obligations:

| component | rung | paint obligations | motion obligations |
|---|---|---|---|
| **Pane / Shelf** | Shelf | ink law: `text`/`muted` ONLY — no value ever lives on a pane; `hairlineStrong` outline, `specular`, `shPane` | none beyond §2.6 |
| **Card** | Card | the workhorse; every ink except `faint` passes AA at every tier over every legal ground (kit.md §6 receipt); radius `radiusXl` | hover/press per §2.6 |
| **CheckableCard** | Card | header checkbox arms the card's contents; disabled body per §2.6 disabled | state ink at `motionState` |
| **CollapsibleCard** | Card | as Card | unfold = `motionUnfold` (280 ms OutQuint) / spring; collapses to snap under reduced motion |
| **MetricTile** | Tile | opaque, always; `FONT_METRIC_LABEL_PX` caption (11, tracked, mono, uppercase) over `FONT_VALUE_PX` value (26, mono, w600) + `FONT_UNIT_PX` unit (11, muted); **semantic ink permitted here**; stale = ink-only + unconditional STALE marker (ruling 2) | value changes ease at `motionState`; no geometry motion |
| **MetricGrid** | (layout) | lays out Tiles; owns no paint | none |
| **StatusPill** (chip) | Tile-class | glyph + WORD + colour, `chip` fill — never colour alone | width change springs (`motionSpringUi`) |
| **ActionBar** | (layout on Shelf) | classes primary/secondary/motion/danger; **danger sits alone**, fills `dangerFill`/`onDanger`; motion class ≥ 44 px targets | press at `motionTap` (120 ms) |
| **SegmentedControl** | track = Well, thumb = Tile | track opaque `well` + `edgeShade`; thumb opaque `raised` | thumb slide = `motionSpringUi` (spring 3.0, damping 0.32) |
| **Well** | Well | opaque, always; radius 12; `edgeShade`; **no semantic-coloured text** — values `text`-inked, state carried by chip/stripe/glyph beside the value on the card; only ever on a Card | none |
| **EmptyState** (+error) | on Card | body prose `fontBody`; error variant uses `error` token + word + glyph | entrance ≤ 100 ms crossfade only |
| **PanelHeader / SectionHeader / Eyebrow / FormRow** | (typography) | `fontPanelTitle`/`weightPanelTitle`, eyebrow tracked-caps, `fontBody`/`weightBody` | none |
| **FigureCard** | Island frame | Card frame around the reserved island hole; the kit draws the frame ONLY — never content into the hole; `edgeShade` inner top on the island rim | none; nothing animates adjacent to a hole |
| **HazardSurface** | Hazard | opaque `panel` at every tier; 4 px `danger` (or `armed`, motion class) left stripe + 45° hairline hatch; state as glyph + WORD + colour; hosts the live hazard value (Tile), the `ArmLatch`, the `ArmedEnvelope` in mono. Material DEAD (§2.6 danger); focus ring always, halo never (ruling 4) | none — no lift, no springs, no ambient |
| **LivingGround** | layer 0 | §5.3 — band law, no semantic tint, ever | §5.3–5.4 |

The `ArmLatch` (hold-3s ceremony) and `QtDangerGate` are engines this kit
*hosts*, never re-implements (§1.4).

---

## 4. Focus and contrast laws

### 4.1 The outside-offset focus-ring convention (ruling 3)

The 2 px `accent` focus ring is drawn **entirely outside the component's fill
boundary**, at `focusRingOffsetPx = 2` beyond the edge — clearing the 1 px
`hairlineStrong` outline so the ring always reads against the *surrounding*
rung surface, never the component's own fill or edge treatment.
Accent-ring-on-accent-fill is a non-case **by construction**. This matches the
shipped QSS `outline-offset` precedent: both shells share one convention.
The 8 px soft halo (`focusHaloAlpha` 0.35 dark / 0.25 light) is garnish — the
ring alone is the accessible channel.

### 4.2 The ring-vs-own-fill standing check (ruling 3)

`TCT_app/scripts/kit_contrast_check.py` carries a standing
`ring_contrast_scan`: the ring must hold **≥ 3:1 non-text contrast** against
every rung's SCENE and TOKEN composite AND every interactive fill token. A
spec claim of "audited" without this scan is inadmissible (the forge-time
claim was unbacked — attack_baldr BLOCKER-2).

### 4.3 Hazard focus (ruling 4)

On hazard rungs the focus **ring is ALWAYS present**, at every tier — it is an
accessibility primitive, not part of the glass material. The decorative
**halo never appears** on hazard rungs. "The material is dead on hazard"
kills lift, frost and halo — never the ring. Focus visibility on the
highest-stakes controls is non-negotiable.

### 4.4 The dead-zone law, three mechanisms (ruling 5)

Island and hazard rects are registered with the frost system as **dead
zones**: no pane may extend translucent pixels within `spaceMd` (12 px) of
them by ANY of the kit's three translucent-pixel mechanisms —
**{sample, shadow, halo}** (frost sampling §2.4 · the 9-patch shadow ladder
§2.5 · the focus halo §4.1). Enforced as a *runtime geometric assertion* in
debug builds plus an offscreen test walking all Surfaces × all holes × all
three mechanisms — a checkable law, not a convention.

### 4.5 Contrast floors and receipts

- WCAG 2.2 AA for all text and state indication at **every** tier, computed
  against the **worst legal ground** (the ΔL\* 4.0 band, §5.3) — the receipt
  tables and their two named failures (light-well semantic ink; glass over an
  island) live in kit.md §6 and are enforced by the ink laws (§3).
- Glass alphas are clamped to the ratified floors
  (`MIN_BACKDROP_CANVAS_ALPHA = 0.80`, `MIN_PANEL_GLASS_ALPHA = 0.50`); a
  hand-edited settings file cannot wash a surface below AA.
- `faint` is never text (repo law; on glass it is illegal as decoration too).
- Never state by colour alone; never hazard by material, tier, or motion.

---

## 5. Motion, reduced motion, and the auto-calm law

### 5.1 Motion scale (springs as identity)

- **Interactive geometry springs:** `SpringAnimation` (spring 3.0,
  damping 0.32 — `MOTION_SPRING_UI` in style.py) on: SegmentedControl thumb,
  CollapsibleCard unfold, StatusPill width, drawer/overlay entrance.
  Colour/opacity stay `Behavior` eases at `Theme.transitionMs`.
- **Scale:** `motionTap` 120 ms (hover/press) · `motionState` 200 ms
  (= `transitionMs`, state ink/fill) · `motionUnfold` 280 ms OutQuint
  (structural reveals).
- **Loop budget:** lamp pulse (1200 ms law) + living ground. Nothing else may
  loop (lint-enforced).

### 5.2 Reduced motion

`Theme.motionEnabled == false`: springs collapse to snap; only ≤ 100 ms
opacity crossfades remain; the ground goes static, frost baked once — the
*look* survives, the *motion* doesn't. FLAT: nothing; TOKEN: static wash.

### 5.3 The living ground (layer 0, the frost source)

- **Look:** two accent washes drifting on slow closed Lissajous paths + a slow
  specular sweep; `full` ≈ wash offsets moving ~8% of the viewport over
  `groundFlowPeriodS` (90 s base; effective period = `groundFlowPeriodS` /
  speed, speed ∈ 0.25–2.0×); `subtle` = half amplitude, half speed.
- **Setting:** `theme/living_glass ∈ {off, subtle, full}` + speed, persisted.
  **Default: subtle**; `off` is one click away and is the documented
  accessibility posture.
- **Band law per frame (constitution-grade):** washes move position, never
  alpha; summed tint ≤ `GROUND_TINT_ALPHA_MAX` (0.07) at every pixel of every
  frame → the ΔL\* 4.0 band holds for any frame → every kit.md §6 contrast
  number is frame-invariant. A test renders N random phases and asserts the
  band.
- **No semantic tint, ever** — the ground is tinted only with `accent` and
  neutrals; never `danger`, `armed`, `good` or `sim`; the flow may not change
  hue toward any state colour. The ground carries no information.

### 5.4 Auto-calm — panel-scoped, with the run-active clamp

- **Panel-scoped calm (ratified; kit.md §1.2 as amended):** the moment a scan
  enters RUNNING, the ground stills **behind the panel that owns the run
  only** — its wash amplitude eases to 0 over 1200 ms and the pane stops
  scheduling its own `ShaderEffectSource` update (mechanism (a)), holding a
  stale crop of the shared FROST texture. The rest of the room keeps flowing;
  the shared bake keeps running at the idle rate (6/12 Hz per setting). A
  detached panel is its own top-level with its own ground and calms whole.
  Flow resumes when the run ends.
- **Run-ownership convention (ruling 7 — this wording is the operative rule;
  it supersedes candidate_lantern §7's "resolves through `run_state_facade`
  only", which overstated the facade):** the app is single-run by
  construction (one global StateMachine/ScanController/ScanCoordinator; the
  Sequencer drives that same coordinator), so the facade's single `active`
  flag suffices. **"The run-owning panel" = the top-level currently hosting
  the ScanViewer/ScanStatusStrip, gated by `facade.active`** — explicitly NOT
  the arming panel (Planner or Sequencer). The definition survives
  Planner-close-mid-run and the detached ScanViewer (which calms whole).
  Sequencer-driven runs stay ScanViewer-scoped. If that ever changes, the
  extension seam is a read-only run-source/owner STRING on the facade, fed
  like `runPath`/`scanType` — never a controller reference (the read/command
  boundary is untouched). U1 staging pins this seam as reserved-not-built
  (`docs/design/u1_staging.md` §6); no U1 VM may cache a competing notion of
  run ownership.
- **Run-active speed clamp (ruling 1 — law, alongside reduced-motion):**
  whenever ANY run is active anywhere in the app, the living-glass effective
  speed clamps to **≤ 1.0× app-wide**; the persisted 0.25–2.0× range applies
  in full only while the whole app is idle. The room keeps flowing — the
  panel-scoped calm stands — but never at its fastest drift while a beam is
  on. **Precedence: reduced-motion (static) → run-active clamp (≤ 1.0×) →
  persisted setting.**
- **Run-cue law:** a locally-calm pane in a flowing room correlates with the
  run — permitted as a **redundant** cue, never the only one. The run chip
  stays the indicator; state never by motion alone.
- **During RUNNING, springs stay** — they respond to *operator* action;
  motion from user interaction is exempt from the distraction gate.
- **The stale-crop drift seam (named, tracked):** the frozen crop is a
  snapshot at T₀ while the surrounding ground drifts — a phase discontinuity
  at the run-owning pane's edge that grows over the run. Visual acceptability
  is an open item for the **U2 reference-implementation review** (rendered
  pixels, not prose); fallback if it fails: ease the *neighbouring* washes
  toward a shared static phase around the calm region, at re-measured cost.
- **Window-boundary caveat (accepted, documented):** a detached panel samples
  a *different* ground — same tones (the band law bounds both grounds
  identically), different frost phase.

---

## 6. The Theme-bridge contract — the U2-entry plumbing beat

**Everything through `Theme.*`; no inline hex, ever** (enforced by
`tests/test_no_inline_hex_gui.py`). The C13 audit (`docs/CODEX_QUEUE.md` §C13,
2026-07-15) enumerated **42 missing Lantern exposures** in
`TCT_app/gui/qml_theme.py` `TOKEN_MAP`; the full table with per-token
QWidget-side sources, spec consumers, and shipped-QML hardcoded guesses is
condensed as **Appendix A** and is part of what this signature covers.

**Contract:** before the first `Surface` lands in U2, ONE focused front-loaded
bridge beat (i) adds the 42 `Theme.*` properties, (ii) promotes the new
shadow/blur/frost/focus/motion constants into `gui/style.py` (shadow family
already APPROVED, §2.5), (iii) adds the two living-glass settings to
`gui/app_settings.py`, and (iv) updates QML bindings/tests so no component
guesses with `Theme.crit`, `Theme.sunk`, `Font.DemiBold`, generic radii, or
raw durations. Otherwise Lantern's first `Surface` becomes the source of
truth instead of a renderer of it. All shadow/blur/frost numbers live in
`gui/style.py` and surface through Theme — one source of truth both engines
read, even though only the QML engine renders them.

---

## 7. Open items Kaya explicitly decides at the gate

### 7.1 Measurement-B thresholds — ratify or tune (THE gate decision)

> **DECIDED 2026-07-15 (DECISIONS entry "U1 CLOSED, U2 entry gate
> PAID"): measurement B ran live and PASSED all three assertions
> (artifacts `artifacts_claude/measurement_b_20260715T102648Z/`); the
> PROPOSED thresholds below are RATIFIED unchanged as the binding
> numbers. Panel-scoped calm ships; global calm stays the encoded
> fallback. The table below is kept as the normative record.**

Measurement B (acquisition headroom) is the **U2 entry gate**: idle-rate bake
+ living ground at `full`, running through a live *simulated* scan (sim
DeviceManager + scan controller + HDF5 writer + a 30 Hz plot island) on the
lab laptop. Harness exists: `TCT_app/scripts/spike_measurement_b.py`
(sim-only by construction AND by guard; the windowed run is **operator-only**).
The assertions are ratified in kind ("the plot holds rate, DAQ cadence does
not jitter" — candidate_lantern §7); **the numeric thresholds are PROPOSED,
not ratified — the live operator run tunes them from printed numbers before
the gate binds:**

| assertion | PROPOSED threshold (inherited from measurement A where applicable) |
|---|---|
| P1 — plot holds rate | loaded island ≥ **28.0 Hz** AND ≥ **0.90 ×** baseline |
| P2 — DAQ does not jitter | loaded point-rate ≥ **0.80 ×** baseline AND inter-point CV ≤ max(baseline CV × **1.5**, **0.50**) |
| P3 — frost scene renders | loaded QML fps ≥ **55.0** |

**If B fails, the ratified fallback is run-active GLOBAL calm** (bake → 0 Hz
app-wide), which returns the panel-scope refinement to Kaya with the numbers
(and moots the ownership resolution, ruling 7).

### 7.2 On the record for the gate (decided elsewhere, not re-opened here)

- **Stale-crop seam acceptability** — decided at the U2
  reference-implementation review with rendered pixels (§5.4), not at this
  gate. Listed so the signature is informed.
- **Baldr's verbatim challenge to panel-scoped calm** is ON RECORD in
  `attack_baldr.md`; ruling 1's clamp is the narrowest fix and ships unless
  Kaya overrules (his prerogative under delegation carve-out 2).
- **The 4-metre validation** ("someone should walk backwards", kit.md
  weakness 6) — an operator/bench chore against the real lab monitor, still
  outstanding; not a design decision.

Nothing else in this spec is unratified: every other clause traces to a
DECISIONS entry, the post-revision candidate, or the ratified kit contract.

---

## 8. Amendment log and change mechanism

- **This document changes only through `docs/DECISIONS.md`:** a ruling (Adam,
  under the delegated design authority, post-hoc logged) or a Kaya
  ratification lands there first; this spec is then amended citing the entry.
  PROTECTED regions (§1.4) additionally require Kaya's explicit per-change
  approval — always.
- **Reversal boundary:** implementing and evolving the ratified direction is
  delegated; dropping LANTERN, un-ratifying panel-scoped calm, or touching any
  safety clause goes back to Kaya (DECISIONS 2026-07-15, delegation entry).
- **Lineage is append-only:** the source documents (§ header table) are the
  history and are never edited to match this spec retroactively — except the
  one queued chore already ruled: candidate_lantern §7's ownership wording
  amendment per ruling 7 (this spec, §5.4, already carries the corrected
  text).

| date | change | authority |
|---|---|---|
| 2026-07-15 | v1 consolidated from ratified sources; conflicts resolved per the precedence rule (Appendix B) | U1.5 beat, Brokkr; signature pending [Kaya] |

---

## Appendix A — The Theme-bridge table (C13, condensed faithfully; 42 exposures)

Grouping and counts are C13's own; per-token file:line evidence of shipped-QML
hardcoded guesses lives in `docs/CODEX_QUEUE.md` §C13 and is not repeated
here. "Source" = QWidget-side source of truth.

**A.1 — Palette/geometry exposures with a shipped QWidget source (13):**

| Theme exposure | source (`gui/style.py` unless noted) | spec consumers |
|---|---|---|
| `dangerFill` | `palette()["danger_fill"]` | ActionBar danger, HazardSurface |
| `onDanger` | `palette()["on_danger"]` | danger button/hazard labels |
| `onArmed` | `palette()["on_armed"]` | motion/armed filled controls |
| `error` | `palette()["error"]` | EmptyState error, device hard-error |
| `chip` | `palette()["chip"]` | StatusPill/chips |
| `edge` | `palette()["edge"]` | Surface specular/raised top edge |
| `edgeShade` | `palette()["edge_shade"]` | Well/Island inner top shade |
| `pressed` | `palette()["pressed"]` | pressed fill (§2.6) |
| `disabledBg` | `palette()["disabled_bg"]` | disabled Surface fill (§2.6) |
| `glassPaneAlpha` | `PANEL_GLASS_ALPHA` + clamp | Shelf/Pane SCENE tint |
| `glassCardAlpha` | `GLASS_CARD_ALPHA_DARK/LIGHT` | Card SCENE tint |
| `radiusXl` | `RADIUS["xl"]` | Card, HazardSurface |
| `radiusShelf` | `RADIUS["shelf"]` | Shelf/Pane outer radius |

**A.2 — Typography roles (9):** `fontRail`, `fontPanelTitle`, `fontBody`,
`weightRail`, `weightPanelTitle`, `weightBody`, `weightMetricLabel`,
`weightValue`, `weightUnit` — each from its named `FONT_*`/`WEIGHT_*`
constant in `gui/style.py`; consumers per §3 typography rows. Shipped QML
currently guesses most of these (`Font.DemiBold`, `font.bold`, generic sizes).

**A.3 — Motion & living-glass (6):** `motionEnabled`
(`app_settings.motion_enabled()`), `livingGlassMode` + `livingGlassSpeed`
(NEW settings, `theme/living_glass*`), `motionTap` (120 ms), `motionUnfold`
(280 ms), `motionSpringUi` (`MOTION_SPRING_UI`: spring 3.0, damping 0.32).
(`motionState` needs no new exposure — it IS `transitionMs`, already bridged.)

**A.4 — Shadow ladder (5, APPROVED §2.5):** `shadowInk` (dark `#000000` /
light = text hue), `shadowA..D` (.20/.24/.30/.55 dark · .06/.08/.10/.22
light) → assembled `shCard`/`shPane`/`shFloat`.

**A.5 — Frost & focus & ground (9):** `blurPane` 40 / `blurCard` 16 /
`blurOverlay` 28 px · `frostRebakeHzSubtle` 6 / `frostRebakeHzFull` 12 (held
by measurement A; measurement B may lower) · `focusHaloAlpha` 0.35 dark /
0.25 light · `focusRingOffsetPx` 2 · `groundFlowPeriodS` 90 s ·
`groundTintAlphaMax` (= `GROUND_TINT_ALPHA_MAX` 0.07, shipped).

Already covered today (not counted): base rungs `card`/`shelf`/`well`/
`raised`, core inks, `danger`/`armed` aliases, spacing, metric font sizes,
`monoFamily`, `transitionMs`, `specular`, plot constants.

---

## Appendix B — Reconciliation notes (conflicts found and resolved, per the precedence rule)

1. **candidate_lantern §7 ownership wording vs ruling 7.** The candidate says
   run ownership "resolves through `run_state_facade` only"; ruling 7 found
   this overstates the facade and pinned the **ScanViewer-host convention**
   (§5.4). *Resolution: DECISIONS wins.* This spec carries the corrected text;
   the source-file amendment is the separately queued chore named in ruling 7
   consequence (a) — candidate_lantern.md is deliberately NOT edited by this
   beat.
2. **kit.md "⚠ PROPOSED, not in `gui/style.py`" for `card`/`shelf` vs the
   tree.** Verified against HEAD this beat: `card`/`shelf` are **shipped** in
   both `LIGHT`/`DARK` dicts (`gui/style.py` — light ~L605, dark ~L743),
   `RADIUS_SHELF` is in the `RADIUS` map (~L108), and the bridge exposes
   `card`/`shelf` (`gui/qml_theme.py` TOKEN_MAP L118–119). kit.md's flags
   (written 2026-07-14, before promotion) are stale against the tree; C13's
   coverage statement is current. *Resolution: the tree + C13 win; no design
   content changes — the PROPOSED token was adopted as specified.*
3. **kit.md §5 cost claims ("steady-state ~0 pp", "blurred once, on
   resize/theme change only", "anything during a scan: +0 pp") vs the living
   ground.** Those claims described the pre-living-glass STATIC ground.
   Kaya's living-glass directive + the panel-scoped-calm ratification make
   the ground animate, so the bake re-runs at 6/12 Hz and a standing cost
   exists (measured, §2.4) — exactly Loki BLOCKER-1, already reconciled into
   candidate_lantern post-revision. *Resolution: candidate_lantern
   (post-revision) wins; kit.md §5's table remains true only for
   `living_glass = off` / reduced-motion.* What survives unconditionally:
   one blur pass on the source, never per pane; `GLASS_LIVE_PANE_BUDGET = 1`,
   transient, never during a scan, never over an island.
4. **kit.md §1.2 "Peripheral motion during a live run is booked for the
   attack pass" vs rulings.** The attack ran; ruling 1 answered it (run-active
   ≤ 1.0× clamp). *Resolution: DECISIONS wins; the booking is discharged and
   the clamp is law (§5.4).*
5. **Shadow-family status.** DECISIONS approves promotion; the tokens are not
   yet in `gui/style.py` (verified this beat — no `shadow_ink`/`SHADOW_A`
   match). Not a conflict, but stated precisely so the signature is not read
   as "already landed": **approved, lands in the U2-entry bridge beat**
   (§2.5, §6, A.4).
6. **kit.md §7 law 4 / candidate_lantern §8 dead-zone enumeration** — both
   already carry the {sample, shadow, halo} extension after the ruling-5
   location correction (the enumeration lives in candidate_lantern §8 and
   kit.md §7 law 4, not "kit.md §8" as the DECISIONS entry first said). No
   residual conflict; noted because the DECISIONS text self-corrects inline.
7. **Path note (Loki/C13 both hit this):** briefs elsewhere reference
   `docs/design/qml_kit_forge/kit.md` — that path does not exist; the real
   kit contract is `docs/design/iterations/glasshell-cockpit/round-03/kit.md`.
   This spec cites only the real path.
