# CANDIDATE — LEDGER

> **A kit you can enumerate.** Every visible property of every component in every state is a
> row in one machine-readable style table. If it is not in the table, it does not render;
> if it is in the table, a test has walked it. The design system *is* its own audit.

| | |
|---|---|
| **Thesis** | The design authority is a data contract: one central `(role, rung, state) → paint/motion` table, resolved through a `KitStyle` singleton beside `Theme`. Components are thin projections of the table. |
| **Optimizes for** | Verifiability (contrast, motion, reachability audited by enumeration, not by vigilance), single-point governance, the S2 QML-walker synergy, drift-impossibility |
| **Deliberately sacrifices** | Local readability, per-component flourish, designer ergonomics — everything must be expressible as table cells or it does not exist |
| **Forged by** | Brokkr, 2026-07-15 (U1.5 lean round, paper only) |

---

## 1. Philosophy in one line

**This project's design failures were never taste failures — they were enumeration
failures.** Round 01 shipped 1.04:1 hero text because a switch existed that nobody ran; the
dark Abort label shipped at 3.05:1 because the QSS said the quiet word "white" instead of a
token; `faint` was text for months because no test walked every ink×surface pair. Ledger
makes the entire kit a finite, walkable table so that class of bug is structurally
impossible — the suite renders every cell, every theme, every tier, over the worst legal
ground, on every commit.

## 2. Problem solved / why-now

- **Problem:** the QWidget kit's laws live in five places (style.py comments, kit.md prose,
  QSS selectors, panel_kit docstrings, tests) and stay true only because Baldr keeps
  re-measuring them by hand. The QML migration will re-scatter them into QML bindings —
  sixteen more files where a hand-typed `Font.DemiBold` or a stray `0.6` opacity can hide
  (both exist in the shipped `MetricTile.qml` today).
- **Why now:** U1.5 is the last moment the state vocabulary can be fixed *before* sixteen
  components and thirteen panels bake it in. S2's normative-test manifest needs a QML-item
  walker anyway; Ledger gives the walker its map for free.

## 3. The contract core

### 3.1 The table

A declarative dict in `gui/style.py`-land (spec-level shape):

```python
KIT = {
  ("card",       "idle"):     Cell(fill="card",  glass=("raised", "glassCardAlpha"),
                                   border="hairlineStrong", edgeTop="specular",
                                   ink="text", radius="radiusXl"),
  ("card",       "hover"):    Cell(border="hairlineStrong", ...),          # deltas only
  ("actiondanger","idle"):    Cell(fill="danger_fill", ink="on_danger", LOCKED=True),
  ("well",       "*"):        Cell(fill="well", glass=None, semantic_ink=FORBIDDEN),
  ("hazard",     "*"):        Cell(fill="panel", glass=None, LOCKED=True, ...),
  ...
}
MOTION = {
  ("segmented.thumb", "idle→checked"): Edge(prop="x", curve="spring(3.0,0.32)"),
  ("*",               "*→disabled"):   Edge(prop="ink", ms="transitionMs"),
  ("lamp",            "running"):      Loop(prop="opacity", lo=0.55, ms=1200),
  ("ground",          "*→calm"):       Edge(prop="amplitude", ms=1200),
}
```

Every value is a **token name**, never a literal (the no-inline-hex law extends to
no-inline-anything: hex, alpha, duration, radius — lint-enforced for the table AND for QML
files). Exposed to QML as a `KitStyle` singleton whose `resolve(role, state)` returns a
cached grouped object (one QObject per (role,state) cell, built once, NOTIFY on theme swap
— **never** a per-frame Python round-trip; resolution happens on state *edges* only).

### 3.2 The state vocabulary — one enum, one precedence, defined once

`idle · hover · focus · pressed · disabled · danger · armed · running` + modifiers
`stale · sim` (modifiers compose onto any state; they alter ink/caption cells only).

Precedence is a table property, not component logic:
`danger > disabled > pressed > focus > hover > idle`, `running` composes on lamps/ground
only. A component cannot invent a state; it can only *be in* one. The walker enumerates
role × state and asserts: every cell resolves, every ink×fill pair passes AA over the worst
legal ground, every interactive role has a focus cell whose ring contrast ≥ 3:1.

### 3.3 LOCKED rows — the safety constitution, in data

Rows marked `LOCKED` — `(hazard, *)`, `(actiondanger, *)`, `(actionmotion, *)`, the well
semantic-ink FORBIDDEN flag, the island no-glass flag — are pinned **byte-for-byte** by a
test against the shipped safety tokens (`danger_fill`/`on_danger`/`on_armed`). Editing a
LOCKED row requires editing the pinned test in the same commit — the PROTECTED-region
mechanism, mechanized. A refactor of the table cannot silently restyle the Abort button.

## 4. Component inventory

Same capability set as `gui/panel_kit.py`, zero loss. Components are thin (target ≤ ~100
lines each): geometry + content + `KitStyle.resolve(role, state)`. Roles:

`pane · card · cardCheckable · cardCollapsible · tile (MetricTile) · metricGrid ·
statusPill · actionPrimary/Secondary/Motion/Danger (ActionBar slots) · segmented (track/
thumb/segment) · well · emptyState (+error variant) · headerPanel/Section/Eyebrow/formRow ·
islandFrame (FigureCard) · hazard · ground`

Two paints the table schema explicitly carries as *named primitives* rather than free
drawing (because they are the two known schema-benders — see weakness 1):
`stripe_hatch` (the hazard 4 px stripe + 45° hatch texture channel) and `meter`
(the MetricTile progress bar: track/fill token pair + fraction clamp).

## 5. Interaction states — the matrix IS the spec

The per-component state matrix is not prose in this candidate; it is the table itself. The
spec commits the *shape*: every interactive role MUST have `idle/hover/focus/pressed/
disabled` cells; `danger` cells exist ONLY for `actionDanger` and `hazard`; `running` cells
exist ONLY for `lamp` (in statusPill/tile) and `ground`. A role with a missing mandatory
cell fails the suite — a component cannot ship half-styled.

Non-negotiable channel rules carried as cell flags: state never by colour alone (every
semantic cell also names a `word` or `glyph` channel), focus always a geometric ring cell,
disabled ink stays ≥ WCAG-exempt-but-measured (recorded in the audit output either way).
Hit targets are table constants: `hitMin` 36 px, `hitDanger` 44 px — the walker measures
real item heights against them.

## 6. Token binding

The table is *made of* token names; `KitStyle` resolves them through `Theme` at the same
source (`gui/style.py` palettes). Requires the same Theme exposure audit as candidate Twin
§5 (danger_fill/on_danger/on_armed, chip, edge/edge_shade, pressed/disabled_bg, radius
xl/shelf, font/weight roles, glass alphas, motionEnabled). Mints **no colour tokens**; mints
two structural constants: `hitMin`/`hitDanger` (above), and whatever the living-glass row
needs (§7) — each derived, each a table cell.

## 7. Living glass — a row in the ledger, calmed by the same pipeline as everything else

The ground is role `ground` with states `off · subtle · full` and modifier `calm`:

- **Cells:** `(ground, subtle)` = wash amplitude 0.5×, period `groundFlowPeriodS` × speed;
  `(ground, full)` = 1.0×; `(ground, off)` = static wash; every cell carries
  `tintAlphaMax = GROUND_TINT_ALPHA_MAX` (0.07) as a *verified* property — the frame-band
  test renders random phases per cell and asserts the ΔL* 4.0 band.
- **Calm** is a modifier applied by the same precedence pipeline every component uses:
  RUNNING (from `run_state_facade`) ⇒ `calm` composes onto any ground state ⇒ amplitude
  edge `*→calm` (1200 ms, in MOTION). Reduced motion (`Theme.motionEnabled == false`) ⇒
  ground resolves as `off`-static regardless of setting. Tier: FLAT → no ground item;
  TOKEN → static wash; SCENE → animated (the glass_env ladder already keeps the shader off
  software rasterizers and RDP).
- **Setting:** `theme/living_glass` {off, subtle, full} + `theme/living_glass_speed`
  (0.25–2.0×) persisted; **default: subtle**, because in Ledger the default is whatever the
  audit proves safe, and the band test is that proof. Speed is the one continuous parameter
  outside the table (clamped by the same floor/ceiling idiom as glass alphas).
- **The audit dividend:** "does living glass ever break a contrast number?" is not a review
  question — it is a failing test, or it is true.

## 8. Glass & tiers

Glass is data: each rung's cell carries `(glassFill, glassAlpha)` or `glass=None`
(opaque-always: tile/well/island/hazard — the latter two LOCKED). Blur is a cell field too,
**default 0 everywhere**: Ledger ships edges-and-alpha glass, and if the Lantern-style
frost bake is ever spiked green, turning it on is a table edit (`blur: "blurCard"`) that
no component file has to see. The tier is told to `KitStyle` once (same `kitTier` context
as the other candidates); FLAT/TOKEN resolution drops the glass field and uses the opaque
fill — tier-invariance is a resolution rule, applied in one function, tested once.

## 9. Coexistence with the widget islands

Identical baseline to candidate Twin §8 (holes + frames, kit never overlaps island pixels,
emergency shortcuts stay on the top-level QWidget path, no app-wide `Shortcut` in kit code,
z-order + key-injection merge gates per Codex BLOCKER-2). Ledger adds:

- Island and hazard hole rects are **registered in the same table runtime** (`KitStyle.
  holes`), so the geometric law — no translucent/shadowed/looping item intersects a hole,
  ≥ `spaceMd` gutter — is walked by the same enumerator that walks states. One walker, all
  laws.
- The S2 monkey rewrite ("QML-item walker runs the denial ruleset") consumes `KitStyle`'s
  role registry directly: every interactive role is discoverable by name, every danger role
  is known to be a QWidget hole — the walker can *prove* no QML item accepts a dangerous
  click, instead of sampling for one.

## 10. Motion spec

All motion is edges in `MOTION` (§3.1): property, from→to, duration/curve — durations are
token names (`transitionMs`, `motionTap` 120, `motionUnfold` 280), curves are named
(`outQuint`, `spring(k,d)` allowed for geometry). The motion linter asserts: **nothing loops
except `(lamp, running)` and `(ground, subtle|full)`**; every edge duration ≤ 400 ms; every
edge collapses to 0 (or a ≤100 ms opacity fade) when `motionEnabled` is false. "Auto-calms
while RUNNING" is a table row, not scattered ifs — and it is *therefore testable*: assert
resolve(ground, full, running=True).amplitude == 0.

## 11. Alternatives considered inside this candidate

- *Table in JSON/YAML instead of Python:* rejected — the table must reference tokens and
  derivation helpers (`_blend`, alphas) at build time; Python-with-lint keeps one source
  language and the no-literal rule enforceable by AST.
- *Per-component QML `states`/`transitions` blocks (idiomatic QML):* rejected as authority —
  kept as *mechanism*: components may implement their cells via QML states, but the values
  those states bind must come from `resolve()`. Idiom stays, authority moves.
- *Extending the table to per-panel layout:* rejected — Ledger governs paint and motion,
  never composition. A layout schema is the candidate-C board mechanic through the back
  door (47–64 beats, one real safety hole; LOCKED decision).

## 12. Safety & operational implications

- **Safety:** the strongest audit story of the three candidates: LOCKED rows mechanize the
  PROTECTED-region rule; the walker proves focus reachability and AA per cell; a restyle
  cannot touch danger paint without failing a pinned test. New risk it introduces: the
  table is a **single point of failure** — a bug in the resolver restyles the whole app at
  once (blast radius bounded by LOCKED pins + the render-every-cell suite, but real).
- **Operational:** designers/agents edit data, not sixteen files; Baldr's audits become CI;
  Mary reviews table diffs (small, semantic) instead of QML diffs (large, visual). Cost:
  contributors must learn the indirection, and quick visual experiments now require a table
  round-trip — the "just try a shadow here" workflow dies (deliberately).

## 13. Weaknesses (attack here)

1. **Schema creep is the death mode.** The two known benders are already visible —
   `stripe_hatch` and `meter` had to become named primitives (§4). The third bender (a
   bespoke paint some panel genuinely needs) either grows the schema again or gets
   implemented outside the table, and the moment one component cheats, the "if it renders,
   it's audited" claim is false and the whole premise quietly dies. Attack with a concrete
   component: the jog pad's decorative crosshair, the planner's drag-ghost, the scope
   trigger marker.
2. **Over-abstraction for a 16-component kit.** The capability spine's own law — "no
   descriptor field without a live consumer" — cuts against building a style compiler for
   one application. If the honest cell count is ~120, a disciplined per-component kit with
   a *walker test* (no central table) might buy 80% of the audit for 20% of the machinery.
3. **Resolution performance is a design commitment, not a given.** The cached
   grouped-object design (§3.1) must actually hold: a naive `resolve()` in a binding means
   Python in the paint path — jank, and on the wrong thread the day someone binds it from
   an island-adjacent item. The spec pins the mechanism, but it is unbuilt and unspiked.
4. **Local readability suffers exactly where debugging happens.** "Why is this border
   grey?" now traverses component → role → precedence → cell → token → palette. Five hops.
   The classic shell's answer was one QSS selector away. Tooling (a `kitstyle dump role
   state` CLI) is specced but is one more thing to build and maintain.
5. **The table tempts governance theater.** LOCKED rows are only as strong as the pinned
   test's coverage; a new row *adjacent* to a locked one (e.g. a new `armed` variant) is
   not locked by default, and the mechanism may create false confidence that "the table is
   safe" as a whole.
