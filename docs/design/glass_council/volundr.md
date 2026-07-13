# Völundr — the material system as a SEED CONTRACT

Glass Council lane deliverable. Völundr (NorthStar LabControl smith,
contract-only). `project_tct` is READ-ONLY under my charter; this single
file is the council-brief-authorized exception, and it changes no code.

My lane is not the mechanism (Noah's crew owns which DWM/scenegraph API
produces the visual). My lane is what the **platform seed must freeze**
so that LabControl — and every future tenant that initializes from
`v1.0-platform-seed` — inherits ONE coherent material system instead of
forking a look. A material system that ships as ad-hoc styling gets
forked; one that ships as a frozen token vocabulary plus invariants gets
inherited. Everything below is written to be pasted into
`PLATFORM_SEED.md` (roadmap PART III) as the material-contract section,
alongside my existing 14-item contract-notes list.

Grounding read before writing: `gui/style.py` (SAFETY_TOKENS at
:1791, `_OVERRIDE_FANOUT`, `_GLASS_BLEND_ALPHAS`, PANEL_GLASS_ALPHA,
BACKDROP_CANVAS_ALPHA), `gui/qml_theme.py` (Theme singleton, TOKEN_MAP),
`gui/panel_kit.py` glassPane tests (`tests/test_panel_kit_cockpit.py`,
`tests/test_theme_editor.py`), `docs/SAFETY_NORMATIVE_TESTS.md` (the
v0.2 `test_theme_editor.py` promotion row), `docs/ROADMAP_MASTERPLAN.md`
(U0–U6, seed hand-off), `docs/design/glass_gap_findings.md`.

---

## 1. The shape of the promise: names and semantics, never values or mechanism

The seed freezes the material system the same way it freezes
capability_ids and plan-JSON enum aliases (my earlier addenda, roadmap
PART III: *"capability_id strings get the same permanence promise as
enum aliases + a deprecation process"*). Apply the identical permanence
promise to material tokens:

- **A published token NAME is permanent.** Renames happen only by
  alias-forever plus a documented deprecation process (exactly the
  `crit`→`danger`, `warn`→`armed` byte-alias pattern `gui/style.py`
  already lives with — that pattern is the precedent, not a wart).
- **A token's SEMANTICS are permanent.** What `panel` means, what
  `armed` signals, what `glassPane` opts into — frozen. A name is never
  repurposed.
- **Token VALUES are never promised.** Themes retune hexes and alphas
  freely (within mutability class, §2). LabControl binds to tokens,
  never to hexes.
- **The MECHANISM is never promised.** DWM Mica/Acrylic, Qt Quick
  scenegraph alpha, per-item layers, or the pre-blended color-mix
  fallback — all are implementation rungs on the degradation ladder.
  No consumer may detect or depend on which rung is active (§4, G3).
  The platform-level analogue of my "TCT will NEVER guarantee" list
  gains one line: **the platform never guarantees real translucency on
  any host — no information may be encoded in it.**
- Additive evolution only: LabControl and tenants may ADD tokens; they
  may never shadow, repurpose, or locally re-derive an existing name.

Concretely, `PLATFORM_SEED.md` carries a `MATERIAL_TOKENS` table:
`name | tier | semantics | mutability class | QML property name`.
`gui/qml_theme.py`'s `TOKEN_MAP` is the single widget↔QML mapping and
the table's machine twin; the existing drift-guard test that iterates
TOKEN_MAP against both palettes is the enforcement.

## 2. The token tiers and their mutability classes

Three tiers, three mutability classes — the class is part of the frozen
semantics:

| Tier | Tokens (today's names) | Mutability class |
|---|---|---|
| **T1 — safety semantic** | `danger`, `armed`, `sim`, `error` + byte-aliases `crit`, `warn` (the full `SAFETY_TOKENS` frozenset, `gui/style.py:1791`) | **LOCKED.** No override path exists: `apply_theme_overrides` raises, `sanitize_overrides` drops them on any preset-JSON load, no built-in preset carries one. Locking `danger` while leaving `crit` writable would be a bypass (style.py's own comment) — the seed inherits all six names as one indivisible set. |
| **T2 — surface/material semantic** | `canvas`/`bg`, `panel`/`material`, `chrome`, `strip`, `edge`, `well`/`sunk`, `raised`, `field`, `hairline`/`border`, `text`, `muted`, `accent`, … | **Theme-editable** via the fan-out groups (`_OVERRIDE_FANOUT`) — user themes and presets retune these; the group structure (which keys move together) is itself semantics and therefore frozen. |
| **T3 — material mechanism** | `BACKDROP_CANVAS_ALPHA` (≈0.82), `PANEL_GLASS_ALPHA` (≈0.55), `_GLASS_BLEND_ALPHAS` (chrome/strip/edge pre-blends), window backdrop mode (`none|mica|acrylic|…`), window opacity, the `glassPane` property itself | **Mechanism-tunable** — owned by the design system, not by user presets; may be retuned or even retired per platform rung, but their *names and semantics* stay published so tests and the QML side address them stably. |

## 3. The Theme-singleton boundary for QML — one source, read-only crossing

`gui/qml_theme.py` already embodies the right boundary; the seed
freezes it as LAW rather than as one module's good manners:

1. **One source of token values: `gui/style.py`** (in LabControl: the
   platform style module). The QML `Theme` singleton (`import Tct`) is
   a *projection*, never a second store. Code-generated `Tokens.qml`
   stays rejected — that is the drift the module docstring already
   refuses, and the stale-specular incident it records is the evidence.
2. **The crossing is read-only by construction.** `Theme` exposes
   getter-only `Property`s; the sole mutator is `set_theme_mode()`,
   which swaps whole palettes owned by style.py. A QML item physically
   cannot write `Theme.danger`. This is why the S2 v0.2 promotion
   (`docs/SAFETY_NORMATIVE_TESTS.md`, `test_theme_editor.py` row) could
   make **the QML Theme-singleton analogue a U-stage gate item**: the
   lock is structural, so the gate merely proves the structure held.
3. **The safety-token lock has exactly one choke point — style.py.**
   Hostile preset JSON never reaches QML because it is rejected
   upstream (`sanitize_overrides`); QML adds no second validation
   surface to keep honest. The seed states this explicitly so nobody
   "helpfully" adds a QML-side theme store with its own preset loader.
4. **T3 mechanism tokens cross the SAME boundary.** Backdrop mode and
   the glass alphas must become `Theme` properties (names for Noah's
   U1.5 kit spec to ratify — e.g. `Theme.backdropMode`,
   `Theme.panelGlassAlpha`) so QML glass and QWidget glass read one
   dial and a theme toggle NOTIFYs both shells in lockstep. A QML shell
   that hard-codes its own glass alpha has forked the material system
   on day one.
5. Per-engine instances, weak registry, NOTIFY-on-toggle — the existing
   lifecycle pattern is the reference implementation the seed cites.

## 4. Glass × the LOCKED safety tokens — the invariant

The S2 manifest row states the ground truth: *"the danger/armed/sim/
error tokens ARE the operator's hazard channel."* Glass is a second,
decorative channel. The seed invariant keeps them disjoint:

> **INVARIANT (normative, PROTECTED-region class):**
> **Hazard signaling never rides on translucency or material; material
> may never reduce hazard contrast.**

Decomposed into gate-checkable clauses:

- **G1 — deterministic backing.** Every hazard-signaling element
  (danger/armed/error/sim chips, lamps, pills, `#dangerBtn`,
  `[state="danger"|"armed"]` controls, the DangerGate modal, trip
  banners) renders on a surface whose effective background is
  deterministic — an opaque token surface — never on a pane composited
  over live desktop content or app content behind blur. Soft `_rgba`
  tints (hover fills, armed borders) remain legal exactly because they
  sit on such deterministic backings.
- **G2 — glass ineligibility of danger surfaces.**
  `register_glass_pane` already *refuses* plot containers; the seed
  extends the refusal list to any pane hosting a hazard surface (danger
  wells, STOP / ALL-OUTPUTS-OFF / Abort hosts, armed banners, safety
  chips, the kill switch). Refusal is API behavior — the registrar
  raises/declines, same declines-refuse shape as the danger gates —
  not a styling guideline.
- **G3 — material carries zero hazard information.** Toggling backdrop
  `none↔mica↔acrylic`, toggling `glassPane`, or landing on any
  degradation rung (RDP, transparency-off, battery saver, Win10,
  Linux/no-DWM → pre-blended tokens) changes **zero pixels of any
  hazard-signaling element**. An operator screenshot from any rung
  reads identically for hazards. This is a pixel-harness assertion, not
  a review item (§6).
- **G4 — static contrast floor.** Each locked token's signal pairs
  (text-on-surface, border-on-surface) meet a stated minimum (WCAG-
  class: 4.5:1 text, 3:1 non-text) against their *worst-case composite
  background* — and because G1 forces deterministic backing, worst-case
  equals the token surface itself, so this is a static per-theme table
  check, no live capture needed. Every theme preset ships with this
  table green; the theme editor's inability to touch T1 tokens is what
  keeps user themes from breaking it (users can still darken `panel`,
  which is why the pairs are checked against T2 surfaces per-preset).
- **G5 — sim marking survives material.** Law 6 (sim never passes as
  real): the dashed cyan ring is a discrete marker that must never be
  blurred or alpha-faded below recognizability — satisfied structurally
  by G1/G2 (sim chips live on opaque backings), stated separately so a
  future "glass status strip" idea meets it head-on.

## 5. `glassPane` as a contract, not a styling convention

Current semantics (from `gui/panel_kit.py` + its tests) are already
contract-shaped; the seed freezes them:

- **Opt-in, per-instance, default-off — forever.** Opaque is the
  permanent default; glass is requested pane by pane. Never a blanket
  selector (`glass_gap_findings.md` §3 established this and the ratified
  A/B artifact's own footer agrees: window-level real material,
  panel-level pre-blend, real blur only where a future shader path
  earns it).
- **Eligibility is a refusal API.** Registration through
  `register_glass_pane` only; the registrar owns the deny-list (plot/
  camera/readout containers today; hazard surfaces per G2) and refuses
  at registration time. A consumer cannot set the property directly and
  claim ignorance — the property is an *outcome* of registration, not
  an input.
- **The registry is enumerable** (`registered_glass_panes()`), and that
  enumerability is part of the contract: it is what makes G2/G3
  testable (gates iterate the registry; anything glass that is not in
  the registry is a violation findable by a QSS/property sweep).
- **Late registration adopts current state; switch-off clears all** —
  the lifecycle semantics the tests already pin
  (`test_register_glass_pane_after_switch_is_already_on_adopts_it_immediately`
  et al.) are frozen behavior.
- **QML inherits semantics, not mechanism.** A QML pane requests glass
  through the U1.5 component kit, which enforces the same deny-list and
  feeds the same enumerable registry concept. The name `glassPane`, its
  opt-in/refusable/enumerable/default-off semantics, and the deny-list
  categories are the seed promise; dynamic-property-plus-QSS versus
  scenegraph-layer is the free implementation detail.
- **LabControl inherits the registrar.** A connector-era panel that
  wants glass calls the platform registrar and can be refused. No
  tenant gets a private glass path.

## 6. U-track verification — glass regressions die at gates, not eyeballs

The pixel-equal fiasco and tonight's white-barrier are exactly the bug
class that eyeballs miss and gates catch. Per stage, additive to the
standing gate ([A-green] + S2 suites + [Bench] + per-panel qml-boot
smoke):

- **U0 (branch cut + RHI/GL probe):** extend the probe artifact with a
  *material capability probe*: QSurfaceFormat alpha honored (alpha
  channel present), `QSG_INFO=1` shows the pinned opengl backend and
  zero software-fallback lines, and a scenegraph-alpha smoke — a
  translucent QML rect over a known fill, pixel-sampled offscreen, must
  show real alpha multiplication (the one-unit-of-green trick from
  `glass_gap_findings.md` §4 is the precedent and the ceiling of what
  offscreen proves). Establishes the QML shell CAN do in-scene alpha
  before any panel bets on it.
- **U1 (viewmodel reclaim):** the **safety-token lock gate lands here
  as a standing suite** — (a) TOKEN_MAP↔style.py byte-equality for both
  modes including all six T1 keys (drift-guard exists; it becomes
  gate-listed), (b) `Theme` exposes no writable safety property,
  (c) the no-command-surface law rows (`test_run_state_viewmodel.py`,
  disposition D) replicate per new viewmodel. Freeze the T3
  mechanism-token crossing (backdropMode etc.) in the Theme API *now*
  so U2 cannot invent a side channel.
- **U1.5 (kit spec, [Kaya] gate):** the kit spec carries this contract
  verbatim: glassPane semantics + deny-list, invariant G1–G5, and the
  **degradation-ladder map** — which rung uses which mechanism (DWM
  window material / scenegraph per-item alpha / pre-blended tokens) and
  proof each rung is reachable by config, not by luck. Ratification
  includes the G4 static contrast table per shipped preset.
- **U2 (ScanViewer hero):** first pixel gate. Extend the harnesses
  (`scripts/capture_onscreen.py` compositor-true on the bench,
  `capture_panels.py` offscreen for QSS/alpha text-truth) with the A/B
  protocol from `glass_gap_findings.md` §5(c), promoted to assertions:
  `none_*` vs `acrylic_*`/`mica_*` differ **only** in canvas/margin
  regions (the anti-pixel-equal guard — the original bug can never
  silently return), and **hazard-element crops are byte-identical
  across all backdrop modes and glassPane states** (G3 as pixels).
- **U3–U5 (panel waves):** per migrated panel: (a) its glass
  eligibility is declared via the registry and its refusals tested for
  every hazard surface it hosts; (b) its per-panel standing-law suite
  includes the hazard-crop byte-equality for its own safety chips/
  buttons; (c) at U4 Bias and U5 Motor/Planner (kill switch, STOP,
  ArmLatch): an explicit stacking test that the re-parented QWidget
  safety islands are never inside a glass-composited ancestor —
  opaque, on top, unblended, with the documented airspace behavior as
  the reason this must be asserted, not assumed.
- **U6 (shell swap):** full-matrix onscreen capture on the bench across
  the ladder rungs actually exercised — DWM on (mica/acrylic), DWM off
  (transparency disabled), forced fallback (PORT1's Linux offscreen
  twin with the QSG_INFO parser that rejects silent software fallback).
  Assert per rung: hazard crops identical (G3), canvas differs where
  expected, and **dark-mode-flag consistency** (window immersive-dark
  state matches the active theme) so the light-Mica-renders-white
  failure mode is a named regression, not a mystery.
- **Every stage:** the U1 token/lock suite runs on BOTH shells
  (`TCT_SHELL=classic|qml`), offscreen, cheap — the two-shell window is
  exactly when a lock can hold on one shell and silently not exist on
  the other.

## 7. What the seed freezes vs what stays free (the actual contract list)

**FREEZE in `PLATFORM_SEED.md` (this section is the ask):**
1. The `MATERIAL_TOKENS` table: names, semantics, tier, mutability
   class, QML property name (§1–§2).
2. The six-name LOCKED safety set including byte-aliases, indivisible
   (§2 T1).
3. The invariant G1–G5 text — PROTECTED-region class, filed beside the
   safety constitution, editable only with Kaya's per-change approval.
4. `glassPane` semantics: opt-in, per-instance, refusable via
   registrar-owned deny-list, enumerable, default-off (§5).
5. The Theme-singleton boundary law: one value source, read-only
   crossing, single validation choke point, T3 crosses the same way
   (§3).
6. The degradation-ladder REQUIREMENT: every material mechanism ships
   with its named fallback to pre-blended tokens, and no consumer may
   detect the rung (§1, §4 G3).
7. The pixel-gate protocol: hazard-crop invariance + anti-pixel-equal
   margin check as standing assertions (§6).

**NEVER promised (stays free):** token values; the mechanism per
platform/rung; which panes opt in; blur radii and alphas (T3-tunable);
LabControl/tenant token additions (additive only, no shadowing).

---

```json
{
  "agent": "volundr",
  "status": "done",
  "file_written": "docs/design/glass_council/volundr.md",
  "seed_invariants": "Freeze token NAMES+semantics+mutability class (capability_id-grade permanence; values/mechanism never promised); six LOCKED safety tokens indivisible incl. crit/warn aliases; hazard signaling never rides on translucency/material and material never reduces hazard contrast (G1-G5, pixel-gated); glassPane = opt-in refusable enumerable contract; Theme singleton = sole read-only token crossing.",
  "tct_touch": "docs/design/glass_council/volundr.md ONLY (council-brief-authorized deliverable; no code)",
  "deferred": ["post-1.0 LabControl build; U1.5 kit-spec naming of Theme.backdropMode/panelGlassAlpha stays with Noah"]
}
```
