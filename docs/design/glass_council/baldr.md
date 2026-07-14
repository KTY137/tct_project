# Baldr — The material system as UX (glass council, 2026-07-13 night)

*Lane: what the glass must DELIVER, not which API paints it. Depth hierarchy,
the token contract across classic/QML/seed, the fake-glass ladder, and the
QML material component set. Mechanism forensics (QtAds barrier, DWM flags)
belongs to other council lanes; I take their mechanisms as capability rungs
and design what sits on top. Sources read: `TCT_app/gui/style.py` (v6 pass,
`_GLASS_BLEND_ALPHAS`, `SAFETY_TOKENS`, glass-family presets),
`TCT_app/gui/backdrop.py`, `TCT_app/gui/panel_kit.py` (glassPane registry),
`TCT_app/gui/qml_theme.py`, `docs/design/glass_gap_findings.md`,
`docs/design/cockpit_design_system.md`, `docs/ROADMAP_MASTERPLAN.md` U-track.*

---

## 0. Core principle

**Glass is the costume of chrome, never of data.** Translucency answers
exactly one UX question — *"where am I, and what is transient?"* — and it is
allowed to answer no other. Every live value, every alarm, every danger
control sits on opaque ink at full contrast on **every** rung of the
degradation ladder, and the ladder itself is one token vocabulary resolved
against a capability probe — not three separate looks that happen to rhyme.

The corollary that makes this a *system* rather than a taste: **the fallback
is the same design pre-composited, not a different theme.** style.py already
does this right (`_GLASS_CARD_ALPHA = 0.42` is the artifact's literal
`--card-bg` alpha, `_blend`-composited instead of compositor-blended). That
identity — *one alpha vocabulary, two compositors* — is the single most
valuable property of the current system and the seed must inherit it.

---

## 1. The depth hierarchy — what glass must deliver in a lab cockpit

A cockpit is not a media app. In visionOS, glass exists so windows feel
situated in a room. In a lab cockpit, "the room" is the measurement: the
operator's eye lives on the plot, the HV readout, and the state strip.
Material depth therefore has one job: **push chrome backward so data comes
forward.** Anything that pulls the eye toward the material itself is a
defect.

### The Z-ladder (surface roles, normative)

| Z | Role | Material class | Glass? | Today's tokens |
|---|------|---------------|--------|----------------|
| Z0 | **Canvas** — the window's own unclaimed background | `material.window` | **Yes — the primary glass surface.** Nothing readable ever sits directly on canvas. | `BACKDROP_CANVAS_ALPHA = 0.82` over DWM material (`_canvas_fill`) |
| Z1 | **Chrome** — ribbon, dock tab strips, rail, status-strip frame | `material.chrome` | Yes, with a scrim floor (§1.2) | `chrome`/`strip` pre-blends (0.74/0.55) |
| Z2 | **Panel / Card** — the working surface | `material.panel` | Opt-in only (`glassPane`), only panes carrying no live numeric data | `panel` (v6 pre-blend), `PANEL_GLASS_ALPHA = 0.55` |
| Z3 | **Instrument screen** — plots, camera raster, scan map, waveform | `material.screen` | **Never.** Existing hard rule; `register_glass_pane` already raises on `FigureCard`. | `PLOT_BG`, fixed both themes |
| Z4 | **Readout** — hero value tiles, wells, HV state, position | `material.readout` | Never. Mono ink on opaque well/panel. | `well`/`sunk` v6, `chip` |
| Z5 | **Danger / alarm layer** — DangerGate, Abort, STOP, ARMED chips, trip banners | `material.danger` | **Never — in either direction (§5).** | `danger`/`armed`/`hazard`, locked via `SAFETY_TOKENS` |

Two structural observations this table forces:

1. **The main window has almost no Z0.** The glass-gap findings measured ~0
   exposed canvas pixels behind the packed tab content. Real DWM glass on
   the classic shell is therefore *architecturally* limited to margins, the
   chrome band, and dialogs — no amount of plumbing changes that. The UX
   consequence: on the classic shell, **the glass identity must be carried
   by Z1 chrome and by dialogs/popovers**, not by panels. Chasing per-panel
   DWM translucency on classic is chasing pixels that do not exist.
   *(This is also the honest framing for Kaya: the theme editor "looks like
   glass" because it has margins; the cockpit is dense by design — density
   is the feature, glass fills what density leaves over.)*
2. **QtAds splitter gutters and the dock tab strips are the classic shell's
   real glass real estate.** They are chrome (Z1), they tile the whole
   window between panels, and they currently paint opaque. If the mechanism
   lanes can get the canvas fill to reach them, the cockpit reads as "solid
   instruments floating on a glass deck" — which is exactly the visionOS
   composition (opaque media windows, glass everything-between), and it is
   achievable without ever touching a data surface.

### 1.2 The readability contract (what "non-negotiable" means in numbers)

A glass surface's foreground contrast cannot be validated against the
token's nominal color — behind real glass there could be a white desktop, a
video, anything. So the contract is **worst-case contrast**:

- Text/icons on any glass-class surface (Z0/Z1, opted-in Z2): contrast
  ≥ 4.5:1 computed against **both** extremes (material over pure white AND
  over pure black backdrop). Whichever fails sets the **scrim floor** — the
  minimum effective opacity of that surface, shipped as a token
  (`material.*.scrim_min`), not as taste.
- Mono readout values (Z4): ≥ 7:1, trivially satisfied because Z4 is opaque
  — that is *why* it is opaque.
- Danger fills (Z5): per the existing frozen spec; the material system may
  never re-tint them (already enforced: `SAFETY_TOKENS` frozenset, no
  override path).

The pre-blend rung passes this contract *by construction* (blends resolve
to opaque hex — pure math, testable offscreen). Only the real-glass rung
needs the onscreen pixel harness, and only in Z0/Z1 regions — which is
exactly what `capture_onscreen.py` margin-sampling already measures. The
contract is cheap to enforce precisely because the ladder is honest.

### 1.3 What visionOS gets right — steal / refuse list

**Steal:**
- *Materials as a system-owned layer with roles, not per-widget alpha
  hacks.* An element declares "I am chrome" and the system resolves the
  paint. (That is the token contract in §2.)
- *Opaque media inside glass windows.* visionOS renders video/photo
  surfaces fully opaque inside translucent windows — precision content
  never on glass. Our Z3/Z4 rule is the same law; we can say we match the
  reference *because* of it, not despite it.
- *Depth by layering + specular edge, not shadow soup.* The unified
  `specular`/`edge` token (0.14 dark / 0.92 light) is already this. In QML,
  focus/hover should brighten the rim, never flood the fill (law 8:
  motion/emphasis is scarce).
- *Heaviest material on the most transient surface.* visionOS puts the
  strongest blur on ephemeral UI (menus, popovers). Maps directly:
  Acrylic-class glass for popovers/flyouts/theme dialog, Mica-class calm
  for the standing window. Transience ranking = material weight ranking.
- *The ornament idea* — toolbars float slightly outside the panel bounds on
  their own small glass slab. Adaptable to detached-window rails and the
  future command palette.

**Refuse (safety-critical adaptations):**
- *Vibrancy text.* visionOS text on glass is alpha-blended with what's
  behind it. Never for us: measurement ink is solid `text` token, full
  stop. Vibrancy is for labels at most — and I would not even spend it
  there; two text rendering paths is a maintenance tax with no cockpit
  payoff.
- *Adaptive/semantic re-tinting.* visionOS materials shift light/dark with
  the environment. Our semantic colors (danger red, armed amber, sim cyan)
  are locked constants — an environment-adaptive danger red is a safety
  bug, not a feature.
- *Glass-on-glass stacking.* One level. A popover over the glass canvas is
  fine; a glass card on a glass panel on the glass canvas is mud. The
  resolver should refuse nesting (a `GlassPane` inside a `GlassPane`
  resolves the inner one to `material.panel`'s pre-blend).

---

## 2. The token contract — one vocabulary for classic + QML + seed

### 2.1 Principle: descriptors resolve, widgets never probe

Today three parties each half-know about glass: `style.py` (QSS text),
`backdrop.py` (DWM attach), `panel_kit` (opt-in registry). The contract
that spans classic/QML/seed is a **material descriptor per surface role**
that resolves to concrete paint through a single capability probe:

```
resolve(role, rung) -> paint
  rung ∈ { R3 real-glass, R2 window-glass-only, R1 preblend, R0 flat }
```

`style.py` stays the single source of truth (it already is: QSS builder,
`palette()`, and `qml_theme.Theme`'s `@Property` getters all read the same
dicts). The descriptor layer is additive vocabulary, not a rewrite.

### 2.2 The vocabulary (existing tokens slot in; new ones marked ★)

| Token | Meaning | Classic (QSS) | QML | Seed export |
|---|---|---|---|---|
| `bd.kind` | window backdrop material | `_window_backdrop` ("none"/"mica"/"acrylic") | same setting | enum + "in-scene" (§4) |
| `bd.canvas_alpha` | how much canvas fill lets backdrop through | `BACKDROP_CANVAS_ALPHA = 0.82` | canvas Rectangle alpha | number |
| `glass.panel_alpha` | opted-in pane tint over backdrop | `PANEL_GLASS_ALPHA = 0.55` (placeholder, Kaya tunes live) | GlassPane tint alpha | number |
| ★ `glass.chrome_alpha` | Z1 chrome translucency (QML shell; classic approximates with `chrome` pre-blend) | n/a (pre-blend) | ChromeBar alpha | number |
| ★ `glass.blur_px` | blur radius of the glass look | n/a (QSS cannot blur) | baked-blur radius (§4) — the reference artifact uses 26px | number |
| ★ `glass.scrim_min` | worst-case-contrast opacity floor per glass role | clamp in resolver | clamp in GlassPane | number, per role |
| `glass.amount` (`g`) | the ONE user dial scaling the whole fake ladder | `_GLASS_BLEND_ALPHAS` × g (chrome .74 / strip .55 / edge .92·L/.14·D / edge_shade .16/.30) | same scaling on tint/edge strengths | number |
| `specular` / `edge` / `edge_shade` | machined top-light / its sunken inverse | border-top-color approximation | 1px rim Rectangle / gradient | rgba |
| ★ `elev.0..3` | elevation ladder: (surface token, hairline, specular on/off, QML-only shadow) | canvas→panel→raised→(popover) | + layer.enabled soft shadow at elev.3 only | table |
| `hairline` (+ `_GLASS_FAMILY_HAIRLINE_ALPHA = 0.10`) | 1px instrument border — kept crisp on glass **by design** (cockpit, not soft-glass; findings §4 call this delta intentional) | as today | as today | rgba |
| safety: `danger`/`armed`/`sim`/`error`/`crit`/`warn` | LOCKED | `SAFETY_TOKENS`, no override path | Theme properties, same lock | constants, marked immutable |

Plus the two invariants the contract exports as *rules*, not values:

- **I1 — safety-token / glass-role exclusion:** no material descriptor of a
  glass class may reference a safety token, and no safety-token surface may
  resolve to a glass class. Mechanically the same lock as
  `apply_theme_overrides` raising on `SAFETY_TOKENS` — extended one level
  up to roles. Testable with pure token math, no compositor.
- **I2 — byte-identical-when-off:** at `bd.kind == none`, `g == 1.0`
  defaults, and no opt-ins, the resolved paint is byte-identical to the
  shipped theme (already guarded by `tests/test_theme_editor.py`; the
  descriptor layer must keep that guard green untouched).

### 2.3 Seed shape

`PLATFORM_SEED.md`'s material contract = this table + the Z-ladder (§1) +
the rung ladder (§3) as a versioned document, with the numbers exported
from `style.py` (generated, never hand-copied — one source of truth
crossing the repo boundary the same way `qml_theme.py` crosses the
language boundary: by *reading*, not by duplicating). LabControl then
inherits materials the way it inherits the palette: as a contract with
locked safety semantics and a mandatory degradation ladder, not as a
folder of QSS.

---

## 3. The fake-glass ladder — designing the ratified fallback properly

Pre-blended color-mix is ratified as THE fallback. The design failure mode
to avoid is treating it as "the sad path". Designed properly, R1 is not an
apology — it is the same material with the compositing done at
token-resolution time. The rungs:

| Rung | Trigger (probe once at apply-time; re-resolve on change) | What paints |
|---|---|---|
| **R3 real-glass** | Win11 22H2+ · `windows` QPA · compositor transparency ON · not RDP | DWM backdrop + `bd.canvas_alpha` canvas + opted-in `glass.panel_alpha` panes + (QML) chrome glass |
| **R2 window-glass** | R3 minus panel opt-ins (the shipped default posture) | DWM backdrop + canvas alpha; panels pre-blend |
| **R1 preblend** | Win10 · Linux · RDP session · OS "transparency effects" off · battery saver · software rendering | full pre-blend ladder — today's v6 look |
| **R0 flat** | user sets `g = 0` (accessibility / taste) | `chrome`/`strip` collapse to `panel`, edges to `hairline` — already implemented via `g` scaling |

Rules that make the ladder premium rather than merely safe:

1. **Degradation is silent and total.** No mixed states: if the probe says
   R1, *every* role resolves R1. The ugliest possible outcome is an alpha
   canvas blending against DWM's flat fallback fill when the OS kills
   transparency mid-session (battery saver does this) — washed-out contrast
   with zero beauty payoff, the "dead glass" state. The resolver must
   listen for the composition-changed signal and re-resolve; which Win32
   message that is belongs to the mechanism lanes — my requirement is only:
   **the dead-glass state must be unreachable.**
2. **Fake the cues, never the transparency.** Glass reads as glass through
   four cues, and only one of them needs a compositor: (a) something
   varying behind the surface, (b) a specular edge, (c) a material tint
   distinct from flat paint, (d) depth steps. R1 already has (b), (c), (d)
   — `specular`/`edge`, the v6 pre-blends, the elevation ladder. The one
   honest gap is (a):
3. **★ Proposal — the ambient canvas.** The Glass-family presets fake the
   artifact's four radial glows as a *flat* 0.08 wash
   (`_GLASS_FAMILY_AMBIENT_ALPHA`) because a token is one color. But the
   window canvas is the one surface QSS *can* gradient
   (`qlineargradient`), and it is exactly the surface the glow belongs on.
   A two-stop vertical gradient within a few hex units of `canvas` — felt,
   not seen — gives R1 the "lit room" cue at zero hot-path cost (painted
   by the backing store on resize only, never per-frame; law 8 stays
   satisfied because nothing *moves*). This is an additive proposal on top
   of the ratified pre-blend, for Kaya's eyeball A/B — and it doubles as
   the in-scene backdrop for QML glass (§4), which is why I want it as a
   *token-owned* gradient, not a QML-only trick.
4. **Never fake blur.** No dithered gradients pretending to be frosting on
   the classic shell — banding, cost, and it lies. R1's dignity is
   precision: crisp hairlines, machined edges, exact blends. The cockpit
   look already committed to that (intentionally crisp 1px borders vs the
   reference's soft edges — findings §4).
5. **Light theme is specular-first, by evidence.** The v6 pass proved light
   has no panel headroom (white ceiling; any visible blend inverts the
   card/control elevation). So the light ladder carries its glass identity
   in `specular` (0.92), `well` (0.08 ink wash), and chip — codify this as
   a rule of the contract ("dark = material depth, light = toplight"), not
   as an accident of one pass.

---

## 4. The QML material component set (input to U1.5)

QML is where the material system stops being a workaround, **but not
because of DWM** — the strategic move is to stop depending on the desktop
compositor at all:

### 4.1 The centerpiece: in-scene glass with baked blur

Real DWM glass has an unfixable UX flaw for a *cockpit*: what shows
through is the user's desktop — uncontrolled, sometimes white (tonight's
symptom is that failure class), sometimes a distraction. visionOS glass
works because Apple controls the room. **In QML we can own the room:**

- The `Ambient` layer (§3.3's gradient + the artifact's glow composition)
  is app-owned and **static**.
- Therefore its blurred version can be **pre-rendered once** (offline
  asset or startup render — `glass.blur_px` = 26 from the reference), not
  live-filtered. A `GlassPane` is then: the blurred-ambient texture,
  sampled at the pane's scene position, clipped to the pane's radius, plus
  tint (`glass.panel_alpha`), hairline, and specular rim.
- Cost: texture sampling — no live `MultiEffect`/`ShaderEffect` in any hot
  path, so the ratified no-live-shader constraint is *honored*, not
  bent. Panel drag just shifts texture coordinates.
- It degrades perfectly: software path / RDP swaps the texture for the R1
  pre-blend hex — same token, same geometry, one `effectiveMaterial`
  property flip. And it is **identical on Windows and Linux**, which the
  seed's day-0 cross-platform requirement effectively demands — DWM glass
  was never going to exist on AlmaLinux.
- DWM Mica (R3) remains as *window*-level garnish behind everything on
  Win11 — nice where margins exist, never load-bearing again.

This inverts the current architecture's weakest dependency: today the look
depends on what the OS composites behind the window; with in-scene glass
the look is deterministic, pixel-hashable in CI (a blurred static texture
diffs cleanly), and testable in the existing harness without a compositor.

### 4.2 The component set (the panel_kit analogue, per U1.5)

| Component | Material class | Notes |
|---|---|---|
| `Ambient` | — | the room: canvas gradient + glows; theme-driven, static, one per window |
| `GlassPane` | Z1/Z2 glass | baked-blur + tint + hairline + specular rim; refuses nesting (inner resolves to SolidPane); `scrim_min` clamp built in |
| `SolidPane` | Z2 solid | the working card — v6 panel pre-blend; default surface |
| `ScreenPane` | Z3 | opaque instrument screen; hosts the pyqtgraph/GL/camera **islands** (which never migrate); enforces the FigureCard exclusion at the QML level |
| `ReadoutTile` | Z4 | mono value + unit + staleness cue; only ever on Solid/Screen |
| `StatusPill` / `Chip` | Z4 | chip token; opaque |
| `ChromeBar` / `Rail` | Z1 glass | the frosted strip, now genuinely frosted; `glass.chrome_alpha` |
| `Popover` / `Flyout` | Z1 glass, heaviest | transient = heaviest material (visionOS rule); placement must never overlap a danger rect (§5) |
| `Scrim` | — | legibility underlay + modal dimmer; the DangerGate QWidget island always sits *above* any scrim |
| `DangerSurface` | Z5 | fully opaque envelope hosting the re-parented QWidget safety controls (STOP/Abort/ArmLatch); no ambient sampling, hazard hairline; exists so an island is never visually floating on glass |

Motion per law 8: materials never animate their own alpha; springs move
geometry only; focus = specular rim brightening, ~200 ms ease.

---

## 5. Danger and glass — the four hard rules

1. **Danger ink never ON translucency.** `danger`/`armed`/`sim`/`error`
   render only on Z4/Z5 opaque surfaces. Enforced in the resolver exactly
   like today's `SAFETY_TOKENS` override lock — a glass-class descriptor
   referencing a safety token is a raise, not a warning.
2. **Danger controls never BEHIND translucency.** No glass surface may
   z-overlap an armed control, the danger well, or a live alarm banner.
   Popover/Flyout placement treats danger rects as exclusion zones. The
   one modal exception: a full `Scrim` + DangerGate, where the gate is
   topmost and opaque.
3. **Alarms outrank ambiance.** While a trip/critical alarm is latched, the
   window's chrome glass drops one rung (R3→R2: chrome re-resolves to its
   pre-blend). Glass is the costume of calm; when the lab shouts, the
   costume comes off. One eased transition, no pulsing — law 8 compliant,
   and it makes the material system itself carry state honestly instead of
   being decoration that ignores the room's mood.
4. **The opacity floor stays sovereign.** `MIN_WINDOW_OPACITY = 0.80` is a
   safety clamp and the model for every new glass token: each alpha in §2
   ships with a clamped legal range (`glass.scrim_min` being the general
   form), loaded-value-sanitized like the existing QSettings clamp — a
   hand-edited settings file can never produce a ghost cockpit.

---

## 6. Verification (pixel harness hooks — brief; details are Mamoru/Mary land)

- **R1 and R0 are pure math** — worst-case contrast (§1.2), invariants I1/
  I2, and rung resolution are computable offscreen; extend the existing
  byte-identical guards in `tests/test_theme_editor.py` style.
- **R2/R3 need onscreen only at Z0/Z1** — `capture_onscreen.py` margin
  sampling, as the findings already established (`none_*` vs `acrylic_*`
  differing only in margin regions is the *correct* expectation).
- **QML baked-blur is an image** — pixel-hash the blurred ambient asset in
  CI; a material regression diffs as a texture diff, no compositor needed.

---

## 7. Honest summary for the council verdict

Real per-pixel DWM glass through the full QtAds cockpit is **not the right
goal even if a mechanism lane gets it working** — the dense classic shell
exposes ~0 canvas pixels where it would show, and DWM glass structurally
cannot exist on the seed's Linux targets or survive RDP. The effective
solution is: **classic shell = window-level material + glass chrome/dialogs
+ the properly-designed R1 pre-blend ladder (with the ambient-canvas cue
added); QML shell = app-owned in-scene glass with baked blur, deterministic
on every platform; both driven by one material-descriptor token contract
with locked danger semantics — and that contract, not any Windows API, is
what the seed inherits.**

*— Baldr*
