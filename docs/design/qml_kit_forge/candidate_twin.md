# CANDIDATE — TWIN

> **One design, two engines.** The QML kit is a *second renderer* of the already-ratified
> round-03 kit contract — never a second design. If the QML Card and the QWidget Card
> disagree at the TOKEN tier, the QML one is wrong, by definition, and a pixel test says so.

| | |
|---|---|
| **Thesis** | The design authority is the shipped QWidget kit (`gui/panel_kit.py` + round-03 `kit.md`). QML re-renders it, byte-comparably. |
| **Optimizes for** | Zero capability loss, zero drift between shells during the U1–U6 window, reviewability, test portability |
| **Deliberately sacrifices** | QML-native expressiveness: springs, live frost, luminous depth. The visible payoff of the migration is deferred to a later round. |
| **Forged by** | Brokkr, 2026-07-15 (U1.5 lean round, paper only) |

---

## 1. Philosophy in one line

**Parity is the feature.** During the two-shell window the operator must be able to switch
`TCT_SHELL=classic|qml` and see *the same instrument* — same tones, same layout rhythm, same
state language — because a lab instrument that looks different depending on a shell flag is
an instrument whose screenshots, SOPs and operator muscle memory are all wrong half the time.

## 2. Problem solved / why-now

- **Problem:** U2–U5 will port panels one at a time. Without a kit that is *contractually*
  identical to the QWidget kit, every ported panel becomes a small redesign, every Mary
  review becomes a design review, and the app spends months as a patchwork of two languages.
- **Why now:** U1.5 sits before the U2 hero slice precisely so the hero slice implements a
  ratified kit instead of inventing one. Twin is the kit that makes U2 a *port*, not a project.

## 3. Component inventory (1:1 against `gui/panel_kit.py` — zero capability loss)

One QML file per QWidget-kit symbol, same names, same semantics. `import Tct`.

| QML component | QWidget source | notes |
|---|---|---|
| `Card.qml` | `Card` | title/subtitle header + divider + body slot (`default property alias content`); `railAxis` property replaces `set_rail()` |
| `CheckableCard.qml` | `CheckableCard` | header `CheckBox`; unchecking disables the body `Item` (`enabled: false` cascades, exactly the Qt idiom) |
| `CollapsibleCard.qml` | `CollapsibleCard` | disclosure toggle; header trailing slot stays live while collapsed |
| `GlassPane.qml` | `GlassPane` | the shelf slab; ink law §4.1 travels verbatim |
| `Well.qml` | `Well` | opaque always; refuses semantic ink (see §6 laws) |
| `HazardSurface.qml` | `HazardSurface` | opaque always; stripe + 45° hatch painted with `Canvas`/`Shape` (static, repaints only on resize/theme) |
| `MetricTile.qml` | `MetricTile` | **exists** (shipped); this kit adopts it as-is and adds the missing `focus`/LED parity below |
| `MetricGrid.qml` | `MetricGrid` | `GridLayout` arrangement, no painting |
| `StatusPill.qml` | `StatusLamp` + chip idiom (`gui/status_widgets.py`) | glyph + WORD + colour — never colour alone; `chip` fill; the QML twin of `VitalChip` folded into the kit (VitalChip retires into it) |
| `ActionBar.qml` | `ActionBar` | primary/secondary/motion/danger classes; danger sits alone right of a stretch; class = property, colour = token table §5 |
| `SegmentedControl.qml` | `SegmentedControl` | exclusive keys, `selectionChanged(key)`; track = `sunk`, checked segment = `raised` |
| `EmptyState.qml` | `EmptyState` | default + `error` variant with `reason` line + `retrySlot` (caller wires the click — view never retries) |
| `PanelHeader.qml` / `SectionHeader.qml` / `EyebrowTitle.qml` / `FormRow.qml` | the header/caption helpers | mark dot via `axis` token lookup, never a literal |
| `FigureCard.qml` | `FigureCard` | **a frame around a hole** — see coexistence §8; never hosts the plot itself |
| `LivingGround.qml` | `AmbientGround` | same contract (tier-told, FLAT paints nothing) + the Kaya living-glass scope, §7 |

Nothing new is invented; `PhaseRail`/`ChromeButton`/`StubBadge` (shell chrome) restyle onto
these primitives in U6, not before.

## 4. Interaction states — the mirror matrix

State semantics are the QWidget kit's, expressed as QML property bindings (the shipped
`MetricTile.qml` pattern: declarative bindings, `HoverHandler`, never imperative handlers).

| state | visual (all components) | mechanism |
|---|---|---|
| **idle** | rung fill, `hairline` border, `specular` top edge | static |
| **hover** | `border.color → hairlineStrong` — **border only, no fill change** (the v5 artifact's own `.btn:hover`) | `HoverHandler` binding + `Behavior` |
| **focus** | 2 px `accent` ring drawn *outside* the border at +2 px offset, radius +2 (concentric law) | `activeFocus` binding on a dedicated ring `Rectangle`; every interactive component is `activeFocusOnTab: true` |
| **pressed** | fill → `pressed` token | pressed binding |
| **disabled** | fill → `disabled_bg`, ink → `muted`; never a blanket `opacity` dim on text (AA survives) | `enabled` cascade |
| **danger** | ONLY the ActionBar danger slot (`danger_fill` body, `on_danger` label) and HazardSurface. No other component may show a danger state | class property |
| **running** | only *live* state lamps pulse (StatusPill dot, opacity 1→0.55→1 @ 1200 ms loop — the `gui/motion.py::set_pulse` twin). Nothing else moves while a scan runs | one `SequentialAnimation`, killed when not running |
| **stale** (modifier) | ink → `muted` + explanatory caption; **never a bare `--`**, never a blanket opacity | matches `MetricTile.set_stale` |
| **sim** (modifier) | `sim` ink + the word "SIM"/"SIMULATED" — word + colour, never colour alone | matches law 6 |

Hit targets: every interactive component ≥ **36 px** logical height; motion/danger-class
buttons ≥ **44 px** (gloved hand). Keyboard: Tab order follows visual order; arrow keys move
within `SegmentedControl`; `Esc` never triggers an action.

## 5. Token binding — and the parity audit this candidate exists to force

Everything binds `Theme.*` (`gui/qml_theme.py`). **The audit below is real: these tokens
exist in `gui/style.py` but are NOT yet exposed on the Theme singleton.** Twin's first
implementation beat is closing this table — no component ships against a missing token.

| missing on `Theme` today | style.py source | consumed by |
|---|---|---|
| `dangerFill`, `onDanger`, `onArmed` | `danger_fill`/`on_danger`/`on_armed` | ActionBar danger + motion classes, HazardSurface |
| `errorInk` | `error` | EmptyState error variant |
| `chip` | `chip` | StatusPill resting fill |
| `edge`, `edgeShade` | `edge`/`edge_shade` | Well/island inner top edge |
| `pressed`, `disabledBg`, `hover` | same keys | pressed/disabled states |
| `borderStrong` | `border_strong` | (alias of hairlineStrong — expose or document) |
| `radiusXs`, `radiusXl`, `radiusShelf` | `RADIUS` dict | Card (20), shelf (24), sub-elements (4) |
| `fontRail`, `fontPanelTitle`, `fontBody` + `weightRail/PanelTitle/Body/Value` | `FONT_*_PX`/`WEIGHT_*` role constants | headers, prose, buttons (today QML guesses `Font.DemiBold`) |
| `glassCardAlpha`, `glassPaneAlpha` | `GLASS_CARD_ALPHA_DARK/LIGHT`, pane alpha | SCENE fills §6 |
| `motionEnabled` (bool, NOTIFY) | `gui.app_settings.motion_enabled` | every `Behavior` (reduced-motion, §7) |

New tokens: **none.** Twin's discipline is that it may *expose* existing tokens but may not
*mint* one. (The focus ring uses `accent` — no new colour.)

## 6. Glass, tiers, and the laws (verbatim from round-03, restated as QML obligations)

- **Fill law:** at FLAT/TOKEN a surface paints its own rung token, opaque. At SCENE it paints
  *one rung up, at its rung's alpha* (`Theme.glassCardAlpha` etc.) — translucent `Rectangle`
  fills, composited over the app-owned ground. **Twin ships ZERO blur.** No `MultiEffect`,
  no `ShaderEffect` on any kit component, at any tier. kit.md §5.2 measured that the blur is
  seasoning; Twin serves the meal (edge ladder + tone ladder) and skips the seasoning
  entirely. This is the candidate's most committed — and most attackable — position.
- **Tier plumbing:** the tier is *told* to the kit (one `kitTier` context property set by
  whoever ran `gui/glass_env.py::decide_tier`); no QML item ever probes the environment.
- **Hazard law:** `HazardSurface` is opaque at every tier; carries stripe (colour) + hatch
  (texture) + eyebrow WORD + glyph + position — all five survive FLAT. It renders no state
  from the material. It gates nothing (the panel's `QtDangerGate`/`ArmLatch` QWidgets do).
- **Well law:** opaque always; no semantic-coloured text (light-well AA failure, kit §4.4).
- **Island law:** no kit item with `opacity < 1`, no shadow, no glass may intersect an
  island rect; ≥ `spaceMd` gutter (§8).

## 7. Living glass — a leaf feature, not a foundation

`LivingGround.qml` implements the exact `AmbientGround` contract, plus Kaya's scope:

- **Setting:** `theme/living_glass ∈ {off, subtle, full}` + `theme/living_glass_speed`
  (0.25–2.0×), persisted via the existing QSettings path. **Default: off** — Twin treats
  motion as opt-in decoration.
- **Tier:** FLAT → paints nothing. TOKEN → the static wash only (the `ground_pixmap` look).
  SCENE → the animated flow (a single fragment shader drifting the two accent washes on slow
  closed paths). The glass_env ladder already guarantees the shader never runs on a software
  rasterizer or over RDP (both cap at TOKEN).
- **Band law per frame:** the washes move *position*, never alpha — summed tint alpha stays
  ≤ `GROUND_TINT_ALPHA_MAX` (0.07) at every pixel of every frame, so the ΔL* 4.0 ground band
  (and therefore every contrast number in kit.md §6) holds for ANY frame. Contrast on a
  moving ground stays computable because the movement is inside the band.
- **Reduced motion:** `Theme.motionEnabled == false` → static, regardless of the setting.
- **Auto-calm (Baldr gate):** run state RUNNING → flow amplitude eases to zero over 1500 ms;
  eases back at run end. Wired from the run-state *viewmodel* (`run_state_facade`), never a
  controller reference. **The flow is decoration and must never be read as a run indicator**
  — the run chip is the indicator; docs and the settings tooltip say so explicitly.
- **No semantic tint, ever** (kit §1.2). Note: this section formally amends kit.md §1.2's
  "never animates during a run" to "auto-calms to static during a run" — Kaya's 2026-07-14
  living-glass directive is the newer instruction and this is where it lands.

## 8. Coexistence with the widget islands (the never-migrate list)

- **Islands** (9 pyqtgraph/GL, camera raster QLabel): `FigureCard.qml` draws header +
  `hairlineStrong` outline + `edgeShade` inner top around a **reserved hole**; the island
  widget is positioned into the hole by the Python side (QQuickWidget-beside-widget today;
  `WindowContainer` under a future GlassShell). The kit never parents, paints, or overlaps
  island pixels. Geometry contract: hole rect published as a property; a debug assertion +
  offscreen test walk every kit item and fail if any translucent/shadowed item intersects it.
- **Safety instances** (STOP / ALL-OFF / Abort buttons, `QtDangerGate` modal,
  `ArmLatch`): remain QWidgets, single-implementation. The QML kit provides only the
  *surface* they sit on (an opaque `HazardSurface` region with a reserved hole, same
  mechanism as islands). Emergency shortcuts stay owned by the top-level QWidget path; **no
  kit component may install an application-wide `Shortcut`** (lint rule + the Codex
  BLOCKER-2 merge-gate key-injection test).
- **Focus traversal** crosses the QML/QWidget boundary in visual order — per-panel smoke
  test: Tab from the last QML control reaches the first island/safety widget.
- **Z-order:** safety QWidgets always above kit chrome; asserted at every U-stage gate.

## 9. Motion spec

- **Grammar:** `Behavior` only. Colour/opacity/geometry eases at `Theme.transitionMs`
  (200 ms), easing `OutQuint` (the `gui/motion_kit.py` STANDARD_EASING twin). **No
  `SpringAnimation` anywhere** — springs are personality, and Twin's personality is the
  classic shell's.
- **Loops:** exactly two things may ever loop: the live-state lamp pulse (§4) and the
  LivingGround flow (§7). A motion lint (AST/QML scan) enforces it.
- **Reduced motion:** every duration binds `Theme.motionEnabled ? Theme.transitionMs : 0`.

## 10. Alternatives considered inside this candidate

- *Blur at SCENE for panes only:* rejected — once one component blurs, parity with the
  classic shell is broken and the candidate's one law dies. Blur belongs to a later,
  explicitly divergent round.
- *Auto-generating QML from the QWidget kit:* rejected — a code generator for 16 components
  is more machinery than the components; parity is enforced by pixel tests, not codegen.
- *Golden-pixel gate at every tier:* narrowed to TOKEN only — SCENE fills composite against
  a ground the classic shell doesn't render, so cross-engine pixel equality is only defined
  at the opaque tier.

## 11. Safety & operational implications

- **Safety:** lowest-risk candidate. No new hazard idiom, no new material behaviour, no new
  motion near danger controls. The danger topology (panel owns the action) is untouched; the
  kit adds only *surfaces*. The one new safety-adjacent behaviour — auto-calm — is
  presentation-only and reads run state through the facade VM.
- **Operational:** screenshots, SOPs and operator training survive the whole U-window
  unchanged. Mary reviews diffs against a known contract. The cost: the QML shell delivers
  no visible reason to exist until a later design round — Kaya sees the same cockpit.

## 12. Weaknesses (attack here)

1. **The migration buys nothing visible.** Kaya's round-2 verdict — "verschluckt zu viel
   glass feeling" — was about exactly this kind of restraint. Twin answers "why QML?" with
   test architecture, not with glass. If the U1.5 mandate is "the big design iteration for
   the QML suit", Twin arguably fails the mandate by design.
2. **Pixel parity across engines is a tar pit.** QML text rasterization (scene-graph
   distance-field glyphs) ≠ QSS/QPainter text; anti-aliasing differs per GPU. The TOKEN-tier
   golden-pixel gate will either need generous ΔE tolerances (weakening the law it exists to
   enforce) or become a flaky test the crew learns to ignore.
3. **Parity is hand-maintained, not structural.** Twin *claims* one design, but the QSS and
   the QML bindings are two implementations of it; only the pixel tests notice drift, and
   they only look where someone pointed a capture. Drift WILL land between captures.
4. **Zero blur may be over-committed.** The measured "blur is seasoning" claim (kit §5.2)
   was about a *static* ground; a living ground has structure, and blur over structure does
   read. Twin forbids exactly the combination that might have justified it.
5. **The `Theme` gap table (§5) is load-bearing** — if the exposure beat is skipped, the kit
   silently re-hardcodes weights/radii the way `MetricTile.qml` already guesses
   `Font.DemiBold`, and the one-source-of-truth story quietly dies.
