# Brokkr — the forge: three glass architectures for the TCT cockpit

Glass Council, 2026-07-13 night. Forged against `BRIEF.md`; read before forging:
`TCT_app/gui/backdrop.py`, `TCT_app/gui/style.py` (canvas fill, glassPane
registry, opacity pin), `docs/design/glass_gap_findings.md`,
`TCT_app/gui/qml/Shell.qml`, `TCT_app/gui/qml_shell.py`, `TCT_app/main.py`
(alpha surface format + OpenGL RHI pin), `TCT_app/scripts/capture_onscreen.py`.
project_tct code untouched — this file is the only deliverable.

Three candidates, three different bets. Not three intensities of one idea:
if the same attack kills two of them, I forged badly. Each is committed
fully across all three horizons (classic QWidget today / full QML shell /
seed contract), each carries its mechanism, its QtAds+GL survival story,
its degradation ladder, its cost, its test hook, and at least three honest
weaknesses. The attack pass gets no hidden flaws to miss.

---

## The one structural truth (shared input, not a candidate)

A compositor material is visible at exactly the pixels where the **final
composited surface alpha** says "let the material through." There are only
three places that truth can live, and each is a candidate:

- **A** — it lives in the **OS compositor**, end to end: every layer of the
  widget stack must carry alpha down to DWM, per pixel, everywhere glass is
  wanted.
- **B** — it lives **where each shell can honestly deliver it**: window-level
  only on the classic QWidget shell (that is all it can carry robustly), full
  scenegraph alpha in the QML shell (one GL surface, trivially), unified by
  one token contract.
- **C** — it lives **in our own raster**: we composite the "behind the
  window" image ourselves and never ask DWM for anything. Deterministic
  everywhere DWM is flaky or absent.

Shared diagnosis input the crew's evidence points at (all three candidates
must own these; none may rediscover them):

1. **Tonight's WHITE window is almost certainly the dark-mode flag, not the
   backdrop chain.** `gui/backdrop.py` sets attribute 38
   (`DWMWA_SYSTEMBACKDROP_TYPE`) but never attribute **20**
   (`DWMWA_USE_IMMERSIVE_DARK_MODE`). Mica's tint follows the window's
   immersive-dark flag; without it, a dark-themed app over Mica renders the
   material in **light** tone → a "completely white" backdrop region, incl.
   the simple theme-settings window. Any DWM-using candidate must set 20
   alongside 38 and **re-assert both** on theme toggle, on
   `WM_SETTINGCHANGE`/`WM_DWMCOLORIZATIONCOLORCHANGED`, and on **HWND
   recreation** (Qt recreates native windows on some reparent/screen-change
   paths; DWM attributes are per-HWND and silently vanish — hook
   `QEvent.WinIdChange`).
2. `WS_EX_LAYERED` (any `setWindowOpacity < 1.0`) suppresses the material
   outright — already discovered, pinned in `apply_window_opacity`.
   Constraint inherited by every DWM candidate.
3. The pre-fix pixel-equal result was the opaque QSS canvas
   (`glass_gap_findings.md` §2); the **post-fix** near-zero delta is layout:
   the packed shell exposes ~0 canvas pixels. Meaning: **plumbing fixes alone
   can never produce the visionOS look on the classic shell — some layer that
   currently paints opaque must be re-declared as glass zone.** That
   re-declaration is where the three candidates diverge.
4. GL islands (Motor-Stage `GLViewWidget`, the chrome `QQuickWidget`) put the
   whole classic window on the RHI-composited flush path; camera view and
   pyqtgraph plots are raster QWidgets. Every candidate must state what
   happens at those rects.

---

## Candidate A — "One Sheet of Glass" (window-level DWM material, punched translucent zones through the whole stack)

**Philosophy (one line):** the OS compositor is the only party that can make
*real* glass, so the entire widget stack — QtAds included — is disciplined
into carrying per-pixel alpha down to it; authenticity over robustness.

**Optimizes for:** maximum-fidelity visionOS look on the primary bench
machine (Win11 22H2+, GPU, local session). The real desktop, really blurred,
in real time, behind declared zones of a full cockpit.

### Mechanism

- Window level: exactly today's `gui/backdrop.py` chain
  (`DwmExtendFrameIntoClientArea(-1,-1,-1,-1)` + `DWMWA_SYSTEMBACKDROP_TYPE`)
  **plus** the missing `DWMWA_USE_IMMERSIVE_DARK_MODE` (shared input #1) and
  a re-assert hook on WinIdChange/theme/`WM_SETTINGCHANGE`.
- The Qt side is the hard part and the actual design: Qt paints the whole
  window into **one ARGB backing store**; DWM shows material at any pixel
  whose final alpha < 255. "Punching a zone" therefore means: **every widget
  that paints over that zone must paint rgba, not hex** — one opaque
  ancestor or child fill anywhere in the z-order re-seals the hole. So the
  candidate defines a **glass-zone paint law**:
  - a *zone registry* (extending the existing `glassPane` dynamic-property
    registry in `gui/style.py`) declares which regions are glass: window
    canvas, dock-area gaps, splitter handles, tab bars, title bars, and
    opted-in panes at `PANEL_GLASS_ALPHA`;
  - `build_qss` emits rgba for **every** selector in the paint chain of a
    declared zone. For the QtAds cockpit that chain is:
    `ads--CDockContainerWidget`, `ads--CDockAreaWidget`, `ads--CDockWidget`,
    `ads--CDockAreaTitleBar`, `ads--CDockWidgetTab`, `ads--CDockSplitter`,
    `ads--CFloatingDockContainer`. **Known trap:** ADS applies its own
    bundled default stylesheet (`:/ads/stylesheets/default.css`) directly on
    the dock manager at construction — a widget-level stylesheet outranks
    the app stylesheet, so the app QSS never reaches those backgrounds. This
    is the prime suspect for the "opaque barrier the canvas rules never
    reach" in the brief. Fix: `CDockManager.setStyleSheet("")` (or our own
    replacement) immediately after construction, then style via app QSS.
  - floating docks / detached windows are separate top-levels: each gets its
    own backdrop attach (the existing `apply_window_backdrop` fan-out
    pattern already does this for `_DetachedWindow` — extend to
    `CFloatingDockContainer`).
- Content law unchanged: plots, camera, readouts, danger wells stay opaque
  (design law in `backdrop.py`'s docstring and `Shell.qml:91`). Glass zones
  are chrome and declared idle panes only.

### QtAds / GL-island survival

- QtAds survives **only** via the paint-law + default-stylesheet eviction
  above; it is the highest-maintenance surface of this candidate. Every ADS
  version bump can reintroduce an opaque rule and must re-run the test hook.
- GL islands do **not** carry glass and never will here: a `QOpenGLWidget` /
  `QQuickWidget` writes its rect via RHI texture composition, opaque by
  design. Their rects are declared **opaque islands** in the zone registry —
  glass flows around them, never through. Honesty rule: this matches the
  content law anyway (no translucency over live plots/camera).
- Real risk to bench-verify FIRST (go/no-go gate for this candidate): a
  translucent top-level (`WA_TranslucentBackground`) whose backing store is
  flushed through the RHI path (forced by any GL island being visible) is a
  historically artifact-prone combination (black rects, alpha loss on
  resize). `main.py` already requests an alpha surface format and pins
  OpenGL RHI — necessary but not sufficient. Kaya's eyeball + the pattern
  A/B hook below decide within one bench hour whether A lives or dies.

### Three horizons

- **Classic today:** as above — zone registry + ADS restyle + dark-flag fix.
- **QML shell (U-track):** trivially simpler — the top-level becomes one
  `QQuickWindow` (`color: "transparent"`), DWM attach on its HWND, and the
  scenegraph *is* the single alpha surface; glass zones become plain
  `Rectangle { color: Theme.glass(...) }`. Candidate A's discipline collapses
  into ~50 lines. The QWidget safety/GL islands embedded in the QML shell
  remain opaque islands, same registry semantics.
- **Seed contract:** the zone registry is the contract: a platform app
  declares `material.zones` (canvas / chrome / pane-opt-in / opaque-island)
  and `material.tier` (below); the mechanism (DWM vs scenegraph) is the
  host shell's business, invisible to the app.

### Degradation ladder

| Condition | Behavior |
|---|---|
| Win11 22H2+, local session, transparency on | full material (Mica/Acrylic) in all declared zones |
| Transparency off / battery saver | DWM substitutes its solid fallback brush; zones blend rgba over that — flat but coherent; **also** flip tokens to pre-blend when `SystemParametersInfo`/`UISettings` reports effects-off, so text contrast is guaranteed, not lucky |
| RDP session | same as effects-off (DWM disables materials); detected via `GetSystemMetrics(SM_REMOTESESSION)` → pre-blend tier |
| Win10 / Linux / offscreen | `is_backdrop_supported()` false (already implemented) → byte-identical opaque token look |

### Cost

High and **recurring**: ~3–5 beats to land (ADS stylesheet eviction, zone
registry, dark-flag + re-assert hooks, harness extension), plus a permanent
tax — every new panel/widget must declare its zone behavior, and every ADS
or Qt bump re-runs the gate. This is the candidate you pay maintenance on
forever.

### Test hook

Extend `scripts/capture_onscreen.py` with a **pattern-behind A/B probe**:
the harness spawns its own full-screen high-contrast pattern window BEHIND
the app (Acrylic blurs actual content behind the window, so this is
compositor-true and wallpaper-independent), captures declared glass zones
with pattern-behind vs black-behind, and asserts per-zone pixel deltas above
threshold — material demonstrably live — while opaque islands (plot rects,
camera) assert delta == 0. Offscreen guard tests keep pinning the QSS text
(rgba emitted for every selector in a declared zone's paint chain — extend
`tests/test_theme_editor.py`'s canvas guards to the ADS selectors).

### Justification

- **Problem solved:** the actual ratified design direction, literally — real
  DWM material through the cockpit, not a simulation of it.
- **Alternatives within the candidate:** Mica vs Acrylic per zone (Mica for
  canvas — cheaper, wallpaper-derived; Acrylic only for transient surfaces);
  `_CANVAS_MODE` A/B already built in `backdrop.py`.
- **Security implications:** none beyond ctypes already in `backdrop.py`
  (single-module confinement law preserved).
- **Operational implications:** look varies with the user's wallpaper and OS
  settings; screenshots/bug reports become environment-dependent; the lab's
  RDP sessions see the fallback tier, always.
- **Why now:** the two root causes (attr 20, ADS default stylesheet) are
  finally identified well enough to attack; before this week the crew was
  fighting symptoms.

### Weaknesses (honest)

1. **The RHI-flush gamble.** Translucent top-level + GL islands on the
   widgets path is exactly the combination Qt has historically mishandled.
   If the bench probe shows artifacts, candidate A is dead on the classic
   shell and only its QML horizon survives. It carries a go/no-go gate for a
   reason.
2. **Whack-a-mole fragility.** One future opaque fill anywhere in a zone's
   paint chain silently re-seals the glass. The QSS-text guard catches the
   selectors it knows; it cannot know a *new* widget's selector. The failure
   mode is invisible-until-eyeballed — the exact class of bug that already
   burned this team twice (opaque canvas rule, opacity pin).
3. **Third-party surface.** The ADS bundled stylesheet is not ours; evicting
   it means re-owning ALL dock styling (focus highlighting, drop overlays),
   an unbudgeted style-parity chore, and every ADS release can move the
   ground.
4. **It lies on half the fleet.** RDP, effects-off, Win10, Linux all get the
   fallback tier — the "real glass" is a local-session privilege. If Kaya's
   daily driver is ever remote, A's entire premium evaporates.

---

## Candidate B — "Material lives where the compositor can deliver it" (honest split-horizon: token glass on classic, real glass in QML)

**Philosophy (one line):** stop forcing per-pixel alpha through a widget
stack that structurally hates it; the classic shell gets window-level
material + pre-blended token glass (honest, cheap, robust), and *real*
scenegraph glass is specified where it is native — the QML shell — under one
token vocabulary so the look converges and the code never forks.

**Optimizes for:** zero-regression robustness today + the correct long-term
architecture, at minimum sustained cost. The candidate that treats the brief's
own honesty rule ("if real per-pixel DWM glass through a full QtAds cockpit is
NOT robustly achievable, say so") as the design center.

### Mechanism

- **Classic shell (today):** keep exactly what is already landed and stop
  there — window-level DWM attach (`backdrop.py`) + `_canvas_fill` rgba
  canvas + `glassPane` opt-in — **plus only the two correctness fixes**:
  attr 20 / dark-flag re-assert (shared input #1: fixes tonight's WHITE) and
  the ADS default-stylesheet eviction *limited to dock-area gaps and tab
  strips* (the chrome seams — NOT panel bodies). Everything else that "looks
  like glass" on classic is **pre-blended color-mix tokens**: the existing
  `chrome`/`strip`/`edge` pre-blends, tuned to visually match a
  reference render of the real material. No per-pixel chase through 13
  panels. The classic shell's glass is a *tasteful lie told in tokens*, and
  says so in its docstring.
- **QML shell (U-track, the real implementation):** the top-level
  `QQuickWindow` is created `color: "transparent"` with DWM attach (38+20)
  on its HWND. The scenegraph is ONE alpha surface — no backing-store chain,
  no ADS, no punch discipline. Glass is then plain declarative material:
  `Rectangle { color: Theme.material("pane") }` where the theme singleton
  returns rgba when tier says real, pre-blend hex when tier says fallback.
  Per-item frost *of app content* stays banned over live plots/camera (design
  law) and is unnecessary: the material comes from behind the window, not
  from blurring our own content. No MultiEffect/ShaderEffect anywhere —
  ratified constraint respected structurally, not by code review vigilance.
- **One token vocabulary spanning both** (this is the load-bearing part):
  a `MaterialTier` enum — `REAL_BACKDROP` / `PREBLEND` — resolved by one
  probe (`is_backdrop_supported()` ∧ effects-on ∧ not-RDP ∧ opacity==1.0),
  and material tokens defined **once** as (base-color, alpha,
  pre-blend-result) triples in `style.py`'s palette. The QSS generator
  consumes the triple one way (classic), `gui/qml_theme.py`'s Theme
  singleton the other (QML). A theme designer edits one number; both shells
  and the seed move.

### QtAds / GL-island survival

- Trivially, **by refusing the fight**: on classic, panel bodies and dock
  containers stay opaque token surfaces; only window canvas + seam gaps are
  real-material zones, so ADS's opacity habits are irrelevant except at the
  seams (one bounded eviction). GL islands and camera raster were always
  opaque — under B they are indistinguishable from every other pane, which
  is exactly why B cannot regress them.
- On the QML shell there is no ADS: docking is rebuilt QML-side per U-track,
  and the safety/GL QWidget islands embed as opaque rects in an
  otherwise-alpha scene — the one composition Qt handles well.

### Three horizons

- **Classic today:** ship = landed work + dark-flag fix + seam eviction +
  token triples. Weeks of QtAds spelunking canceled.
- **QML shell:** the *primary* glass implementation, specified now (this
  section is that spec), built in U1–U2 when the shell exists.
- **Seed contract:** LabControl inherits the token-triple vocabulary +
  `MaterialTier` probe + the zone semantics ("canvas / chrome-seam /
  pane-opt-in / opaque-island") — the same contract regardless of which
  shell renders it. The seed never learns what DWM is.

### Degradation ladder

One ladder, resolved at the probe, identical on both shells:

| Condition | Tier | Look |
|---|---|---|
| Win11 22H2+, local, effects on, opacity 1.0 | REAL_BACKDROP | material at canvas/seams (classic) or full scene (QML) |
| RDP / effects-off / battery saver | PREBLEND | pre-blended tokens — the *designed* fallback look, not an accident |
| Win10 / Linux / offscreen / tests | PREBLEND | byte-identical guard preserved |

The ladder is short because the architecture keeps the delta between tiers
small on classic by construction — nothing visually collapses when tier
drops, since panels never depended on the material.

### Cost

Low now, medium later, near-zero recurring: ~1–2 beats today (dark flag,
seam eviction, token triples + probe), ~2–3 beats inside U1–U2 (transparent
QQuickWindow + Theme material binding), and the maintenance tax rounds to
zero because no paint-chain discipline exists to violate.

### Test hook

- Classic, offscreen: the existing byte-identical-when-off guards, extended
  to the token triples (pre-blend hex == documented color-mix of base over
  canvas — a pure-function unit test, no display needed).
- Classic, onscreen: pattern-behind A/B probe (as in candidate A) but
  asserting only canvas + seam zones — a far smaller, stabler assertion set.
- QML shell: same onscreen probe against the QQuickWindow; plus a scenegraph
  grab (`QQuickWindow::grabWindow`) asserting scene alpha < 255 at declared
  material rects — testable without the compositor.

### Justification

- **Problem solved:** the actual current emergency (white window, invisible
  material) *and* the mandate expansion ("wichtig für den seed und die QML
  Migration") — without betting the classic shell's stability on a fight the
  evidence says it loses (`glass_gap_findings.md` §4: ~0 exposed canvas px;
  §3: the source artifact itself specifies fake-glass tokens at panel level).
- **Alternatives within:** seam eviction can be skipped entirely (canvas-only
  material) if ADS resists — the candidate survives intact; Mica vs Acrylic
  choice deferred to the QML shell where it is one property.
- **Security implications:** none new; ctypes stays confined to
  `backdrop.py`.
- **Operational implications:** classic-shell screenshots stay near-
  deterministic (tokens dominate); the two shells look *converged but not
  identical* until U-track lands — a visible, communicable roadmap rather
  than a gap.
- **Why now:** the ratified artifact (`tct_bias_glass_ab.html` footer, cited
  in findings §3) *already prescribed exactly this split* — window-level
  real, panel-level tokens, real blur reserved for the QML path. B is that
  ratified intent, promoted from footnote to architecture.

### Weaknesses (honest)

1. **The classic cockpit never gets the wow.** With panels opaque and ~0
   exposed canvas, the visible glass on today's shell is seams and margins —
   subtle. If Kaya wants the visionOS look on the *classic* shell in visible
   quantity, B's answer is "opt panes into `glassPane` one by one and wait
   for U-track," which may read as under-delivery on the design direction.
2. **Two renderers, one vocabulary — drift risk.** The QSS generator and the
   QML Theme singleton both interpret the token triples; without the
   pre-blend-equivalence unit test being merciless, the shells drift apart
   visually and nobody notices until a side-by-side.
3. **It postpones the hard proof.** The transparent-QQuickWindow + DWM +
   embedded QWidget-island composition is *believed* clean (single GL
   surface) but is not yet bench-proven in THIS app; if it has its own
   artifact class, B's "real glass later" pillar wobbles and the QML spec
   needs the candidate-A gamble resolved anyway — just later, with U-track
   momentum at stake.
4. **Tier probe is coarse.** opacity<1.0 → PREBLEND means the user's window-
   opacity slider silently changes the *material system's* tier — correct
   (WS_EX_LAYERED kills materials anyway) but a support-question generator:
   "glass disappeared" ← "your opacity is 98%." Needs the theme-editor note
   to be loud.

---

## Candidate C — "Forged Glass" (self-composited: the app owns the behind-the-window image and blurs it itself, no DWM)

**Philosophy (one line):** authenticity is the wrong axis — determinism is;
re-implement what Mica actually is (a blurred, tinted wallpaper sample)
inside our own raster pipeline, so the identical glass renders on RDP, Win10,
Linux, battery saver, offscreen CI, and every future seed host, forever.

**Optimizes for:** one code path, one look, pixel-testable headless. The lab
reality: a cockpit runs maximized on a bench monitor — "behind the window"
IS the wallpaper — and Mica itself already samples only the wallpaper, not
live windows. C is Mica, re-forged app-side, portable.

### Mechanism

- **Source acquisition:** on startup and on `WM_SETTINGCHANGE`
  (wallpaper change), read the desktop wallpaper
  (`SystemParametersInfo(SPI_GETDESKWALLPAPER)`; on non-Windows, a bundled
  default "lab slate" image — the seed ships one so the look exists on
  hosts with no queryable wallpaper). Fallback when unreadable: procedural
  gradient from the theme's `bg` token.
- **Offline blur, once:** downscale→stack-blur→upscale (the classic cheap
  Gaussian approximation) at two strengths — `canvasBlur` (~18px-equivalent)
  and `paneBlur` (~26px-equivalent, matching the reference artifact's cited
  blur) — plus the theme tint pre-multiplied in. Runs in a worker thread at
  startup/wallpaper-change only; **never per frame**. Products: two
  screen-sized QPixmaps (~2×32 MB at 4K — measured cost, stated, bounded).
- **Paint:** the window canvas paints its slice of the blurred image at the
  window's screen offset (tracked via move/resizeEvent — no timer), instead
  of a flat hex. A glass pane paints the `paneBlur` image **clipped to its
  own rect at the same screen offset** + its rgba tint → true per-panel
  frosted depth, position-correct parallax as the window moves. Implemented
  as a `QPainter.drawPixmap` in a small `GlassBase` paint hook /
  `QSS border-image` hybrid; ctypes-free, DWM-free, works under any Qt
  platform plugin **including offscreen**.
- **What it never does:** it does not capture other windows or live screen
  content (no `BitBlt` of third-party windows — no privacy or perf trap, and
  no lie that "updates" behind us); it does not blur our OWN live content
  (design law preserved: plots/camera/readouts opaque).

### QtAds / GL-island survival

- **This is where C shines:** there is nothing to punch. Every "glass"
  surface is just a widget painting a raster slice — QtAds containers, tab
  bars, splitters, floating docks (each top-level tracks its own screen
  offset) can all be glass without one line of ADS stylesheet surgery,
  because opacity of intermediate layers is irrelevant: the glass is painted
  ON TOP of whatever is below it in that widget, not composited from behind
  the window. The z-order discipline candidate A dies by simply does not
  exist here.
- GL islands and camera: opaque, untouched, exactly as the law demands. A
  glass pane *around* a plot works because the pane paints its own frost;
  the plot rect just doesn't.

### Three horizons

- **Classic today:** `GlassBase` paint hook + wallpaper pipeline; the
  existing `glassPane` registry becomes the opt-in for the frosted paint
  path instead of an rgba fill. `BACKDROP_CANVAS_ALPHA`/`PANEL_GLASS_ALPHA`
  become tint strengths over the frost — same tuning knobs, real depth.
- **QML shell:** the identical blurred pixmaps are exposed as image
  providers (`image://glass/canvas`, `image://glass/pane`); a glass pane is
  `Image + Rectangle` (tint) — still no ShaderEffect, still
  software-renderer-safe, so it satisfies the ratified no-live-shader
  constraint even in QML. Optionally, on proven-GPU tier only, the QML shell
  may swap the pane image for a real backdrop — C composes with B's QML
  horizon rather than fighting it.
- **Seed contract:** the seed ships the pipeline + a default source image +
  the same token triples (tint/alpha per role). LabControl gets glass **on
  day one on every OS**, no DWM contract at all — the strongest seed story
  of the three candidates.

### Degradation ladder

Nearly flat — that is the whole bet:

| Condition | Behavior |
|---|---|
| Any OS, any session type, effects on/off, RDP | identical frost (raster paint — compositor not consulted) |
| Wallpaper unreadable / none | bundled lab-slate source, identical pipeline |
| Low memory (<200 MB free at pipeline time) | skip pipeline → pre-blend tokens (tier drop, same `MaterialTier` vocabulary as B) |
| Tests / offscreen | **full glass renders and is pixel-assertable** — degradation NOT required |

### Cost

Medium once, low recurring: ~3 beats (pipeline + `GlassBase` + offset
tracking + registry rewire), no third-party surface, no OS-version matrix.
Runtime cost: startup blur ~100–300 ms in a worker; +~64 MB RSS at 4K;
per-frame cost is one pixmap blit per glass surface (raster-cheap, and glass
surfaces are chrome/idle panes, never the 30 Hz plot path).

### Test hook

The unique advantage: **fully offscreen-testable.** `capture_panels.py`
renders the real look headless — pixel-compare glass panes against golden
renders of the bundled source image (deterministic seed asset, no desktop
dependency). The onscreen harness is reduced to a parallax check (window
moved 200 px → frost slice shifts 200 px) instead of being the only place
truth exists. This inverts the current situation where the defining visual
is untestable in CI.

### Justification

- **Problem solved:** the actual failure pattern of this whole saga —
  *every* DWM behavior so far was discovered by eyeball at night (opacity
  pin, white window, pixel-equal toggle) because the mechanism lives outside
  our process. C moves the mechanism inside the process, where the test
  suite lives.
- **Alternatives within:** wallpaper-source vs always-bundled-source (bundled
  = fully deterministic screenshots, chosen for CI; wallpaper = personal,
  chosen for the bench, flag-switchable); stack blur vs box×3 (equal look,
  benchmark decides).
- **Security implications:** reads the wallpaper path only (a user-owned
  asset); never captures screen content of other processes — explicitly
  out of scope to keep this true.
- **Operational implications:** screenshots become deterministic; RDP
  support becomes first-class instead of a fallback tier; +64 MB RSS
  documented in ops notes.
- **Why now:** Mica's own design (wallpaper-derived, static-per-desktop)
  proves the *look* does not require live compositor sampling; and the
  mandate expansion demands something the seed can inherit on hosts where
  DWM does not exist — C is the only candidate whose primary tier exists on
  Linux.

### Weaknesses (honest)

1. **It is a forgery, and forgeries have tells.** No live update of windows
   behind the app (a window dragged behind the cockpit does not show through
   the frost), and if the OS-level Mica sits directly beside it (another
   Win11 app snapped next to ours), tint/blur differences are eyeball-visible.
   Non-maximized multi-window users on Win11 get the weakest illusion
   exactly where candidate A gets its strongest.
2. **Position-tracking edge cases.** Multi-monitor DPI mixes, mid-drag
   repaints, and detached floating docks each need the screen-offset math to
   be right; a bug reads as "the glass slides" — an uncanny artifact worse
   than flat tokens. (Bounded: one function, unit-testable, but it WILL eat
   a debugging evening.)
3. **Memory + startup tax on the laptop.** The bench i7-10510U pays the blur
   at every startup and wallpaper change, and 4K pixmaps ×2 live forever;
   on the CPU-bound laptop this is felt, and "skip pipeline under memory
   pressure" adds a tier flap the user can notice across sessions.
4. **Divergence from the ratified direction's letter.** Kaya ratified "DWM
   materials showing through the app." C delivers the *look* while
   abandoning the *mechanism* — if the council reads the ratification
   literally, C needs Kaya's explicit re-blessing, not just a technical win.

---

## Sharpest differences (for the attack pass)

- **A vs C is a clean bet-inversion:** A maximizes authenticity and pays in
  fragility + environment-dependence; C maximizes determinism and pays in
  honesty-of-mechanism. An attack that kills one strengthens the other —
  they cannot both lose to the same blow.
- **B is not the midpoint** — it is a different axis: *where* the material
  lives (per-shell honesty + token contract) rather than *how* it is made.
  B's kill condition is unique: if the transparent-QQuickWindow composition
  proves artifact-ridden AND the classic seams read as under-delivery, B
  loses both pillars at once — a failure mode neither A nor C shares.
- **Composability, stated for Odin:** B's token-triple/`MaterialTier`
  contract is mechanism-agnostic — it can carry A's zones or C's frost as
  the REAL tier without rework. If the council merges, the natural seam is:
  B's contract + C's renderer as the guaranteed tier + A's DWM path as the
  opportunistic top tier on proven local sessions. But each candidate above
  stands alone; the merge is Odin's call, not pre-softened into any of them.

## One shared correctness rider (whoever wins)

Attr 20 (`DWMWA_USE_IMMERSIVE_DARK_MODE`) + re-assert on
WinIdChange/theme/`WM_SETTINGCHANGE` must land regardless of candidate —
tonight's WHITE window reproduces until it does, even under candidate C
(whose windows would still be DWM-framed). It is a bug fix, not a design
choice; it belongs to the empirical track (Noah), and no candidate above
claims it as its differentiator.
