# Loki — the attack pass (glass council round 2)

Loki, Critical Reviewer (NorthStar council, on loan). 2026-07-13 night,
round 2. I read the BRIEF and all eight lane docs, then verified the
load-bearing claims against the repo myself instead of trusting the
council's citations of each other. project_tct read-only; this file is
the only deliverable. Findings ranked CRITICAL / MAJOR / MINOR, each
with a concrete failure case. Where my own confidence is limited, it
says so.

Ground truth I re-verified before attacking (not taken from any lane):

- **QtAds is not instantiated anywhere in `TCT_app/`.** Zero real hits
  for `CDockManager`/QtAds imports in the tree; it exists only in
  `requirements.txt`. Thor is the only lane that checked; the BRIEF's
  "suspected structural barrier: QtAds dock containers" is a phantom
  for the shipped shell.
- `gui/stage_view.py:214` instantiates `gl.GLViewWidget()` (hidden
  QStackedWidget page, live after the first "3D" click).
- `gui/qml_shell.py:417` builds the chrome `QQuickWidget`; opt-in via
  `TCT_QML_SHELL=1`; `docs/DECISIONS.md:194-213` ratifies the QML-chrome
  boundary and gates the **default flip** on the BENCH_CHECKLIST §11
  probe.
- `docs/BENCH_CHECKLIST.md` §11 (the flip probe): R1/R2/F3/F2/R5 —
  RHI coexistence, detach, CPU, RDP, PyInstaller. **No row tests
  whether a DWM material still renders.**
- `docs/design/glass_gap_findings.md` §4: the packed main window
  exposes **~0 canvas pixels**.

---

## 0. Verdicts in one screen

| Target | Verdict |
|---|---|
| Brokkr A ("One Sheet of Glass") | **KILL** on the classic shell — falsified by the council's own mechanics + repo evidence; its QML horizon is just B |
| Brokkr B (split-horizon) | **SURVIVES** — it is the ratified DECISIONS text promoted to architecture — with two forced amendments (§2) |
| Brokkr C ("Forged Glass") | **PARK** — honest only in bundled-source form, i.e. a static skin, not "Mica re-forged"; wallpaper pipeline is under-scoped by an order of magnitude (§4) |
| Merge seam (B contract + C frost + A garnish) | **REJECT the triple** — three mechanisms to maintain where the emergency is one ctypes line; honest merge = B alone, C as a flag-gated QML-era experiment (§2.4) |
| Baldr (material UX) | **REVISE** — Z-ladder and token contract are good; the baked-blur centerpiece is optically a no-op, "dead glass unreachable" is rhetoric, and the alarm-de-glass rule contradicts Volundr (§3) |
| Thor (pipeline ground truth) | **ADOPT** — the one lane that verified the tree — but its verdict must be said at full volume: it falsifies half of a RATIFIED decision (§1) |
| Ymir (degradation ladder) | **REVISE hard** — keep the matrix-as-tests, attr-20, high-contrast, override, log line; cut the L2/L4/L6 runtime-watcher subsystem (§5) |
| Tyr (test spine) | **REVISE light** — keep the taxonomy, the strict-xfail attr-20 test, INV-A/INV-D; kill the QSS-cascade-reimplementing census; rung 4 at gate cadence, not per-beat (§5) |
| Frigg (prior art) | **ADOPT** — cleanest lane in the council; null results stated as findings; VS Code's refusal [S19] is the strongest scope anchor anyone produced |
| Volundr (seed contract) | **ADOPT with nits** — the freeze list is sound; watch constitution creep and the G3-vs-Baldr contradiction (§6) |

---

## 1. CRITICAL — the collision nobody names at full volume

**The RATIFIED architecture and the RATIFIED glass look are mutually
exclusive on the main window, by the council's own mechanics.**

`docs/DECISIONS.md` 2026-07-13, one entry, two clauses, both ratified:

1. "the glass LOOK ships via pre-blended tokens **+ window-level DWM
   backdrop**", and
2. QML is the standard for shell chrome — delivered today as a
   **`QQuickWidget` island** inside the QWidget main window
   (`qml_shell.py:417`), with the default flip gated only on the §11
   probe. (The masterplan's U-track header supersedes the entry's
   long-term direction, but option (a) islands remain the interim
   architecture — risk-register line 422 says "islands per option (a)".)

Thor's flush-path table (path D, `[qt-src]` with an in-repo empirical
anchor: the GL-free dialog blurs, the GL-hosting main window measured
pixel-equal) says: **any render-to-texture child — the chrome
QQuickWidget from launch, or the Motor tab's GLViewWidget after one
"3D" click — flips the entire top-level onto the GPU-compose flush
path, where per-pixel alpha never reaches DWM.** Window-level DWM
backdrop on the main window is then dead, not degraded — dead. Clause 1
and clause 2 cannot both be true of the same HWND.

**Concrete failure case, already loaded and cocked:** the §11 flip
probe checks RHI coexistence, detach, CPU, RDP, and PyInstaller — and
never once looks at a material. The probe goes green, `TCT_QML_SHELL`
flips to default, main-window glass dies silently from launch, and in
three weeks someone burns another night on a "backdrop stopped working"
mystery with a commit trail that says everything passed. That is
tonight's incident, pre-scheduled.

**What it forces (pick, explicitly, in DECISIONS — not in a lane doc):**

- **(i) Restate the classic-shell design honestly:** the main cockpit
  window is the **R1 pre-blended look by construction** for the entire
  option-(a) era — not as a degradation rung but as its design. Real
  DWM material lives only on RTT-free satellite top-levels: dialogs,
  the theme editor, detached non-GL tabs, future floating docks
  (Ratatoskr §3.3 is the honest form of this — "glass satellites,
  opaque cockpit" — and it works today with zero new mechanism). Every
  council lane that says "window-level material on classic" (Brokkr B's
  classic tier, Baldr's Z0/Z1, Ymir's T0) must be read with "…on
  satellite windows" appended.
- **(ii) Add a material row to the §11 probe** ("with acrylic active,
  do dialog margins still frost after the flip? does anyone expect
  main-window frost? state the expected answer: NO"). One row, and the
  pre-scheduled night is cancelled.
- **(iii) The only road to real glass on the cockpit itself is the
  U-track final state: a real `QQuickWindow` shell.** Which drags in
  MAJOR-1 below — that road has its own unpriced toll booth.

Also file under this heading: **the GLViewWidget makes the barrier
time-dependent even without QML chrome.** Raster path at launch, path D
after the first 3D click, back to raster if the Motor tab is detached.
"It worked earlier, white/dead later, no commit changed" — the BRIEF's
symptom 3 has a mechanical explanation that involves zero regressions.
Thor's detach experiment (§3.3-3) is a 30-second falsifier and should
run before any candidate is funded.

---

## 2. Brokkr's three candidates and the merge seam

### 2.1 Candidate A — KILL (CRITICAL)

A is forged well and dies anyway, for three independent reasons:

1. **Its go/no-go gate is already answered.** A carries "bench-verify
   the RHI-flush gamble FIRST" as its live-or-die condition. The
   repo already contains the answer: the GL-hosting main window
   measured pixel-equal while the GL-free dialog blurred — same
   recipe, opposite result, exactly path D's prediction. A's gate is
   not "unknown, needs one bench hour"; it is failed on the evidence
   the council already holds. Betting 3–5 beats plus a permanent
   whack-a-mole tax on re-running a failed experiment is not a
   candidate, it is a hope.
2. **Its forensic centerpiece attacks a library that is not in the
   tree.** A names the ADS bundled stylesheet "the prime suspect for
   the opaque barrier the brief describes." QtAds is not instantiated
   anywhere in `TCT_app` — it cannot be the suspect for *any* observed
   symptom. The eviction analysis is correct **as forward-design** for
   the future dock cockpit (keep it, it will save someone a day), but
   A sold it as case forensics, and that is the brief's false premise
   propagating unexamined.
3. **The prize is ~0 pixels.** glass_gap_findings §4: the packed shell
   exposes approximately no canvas. A's entire discipline — zone
   registry, paint-chain law, ADS restyle, per-selector QSS guards —
   buys per-pixel alpha at pixels that do not exist, on a window that
   cannot deliver alpha to DWM anyway (reason 1). Maximum machinery,
   minimum photons.

What survives of A: the attr-20 + re-assert rider (already declared a
shared bug fix, not A's differentiator) and the pattern-behind A/B
harness idea (good; Tyr should own it). Both are inside B already.

### 2.2 Candidate B — SURVIVES, with two forced amendments

B wins because it is the only candidate that is *already ratified* —
the DECISIONS entry and the A/B artifact footer prescribed exactly this
split before the council convened. Cheapest, aligned, honest. But:

- **MAJOR — B's classic tier overstates what "today" delivers.** "Keep
  window-level DWM attach + canvas fill" is dead on the main window per
  §1 the moment the chrome island or the 3D view is live. B-classic
  must be restated as: pre-blend cockpit by construction + real
  material on satellites/dialogs. As written, B still promises a
  main-window material that the ratified shell direction forbids.
- **MAJOR — B's QML pillar has an unpriced load-bearing dependency.**
  "Real glass is free in a QQuickWindow" rides Thor's `[inferred]`
  D3D-RHI DirectComposition path — while the shipped shell **pins the
  Quick RHI to OpenGL** (`qml_shell.py:66-76`) precisely so the chrome
  and the GLViewWidget can coexist. Thor names the tension and then
  everyone files past it: translucent Quick top-levels are the D3D
  path; an OpenGL-pinned Quick window lands on WGL surfaces where
  translucency is the old fragile story. So B's "real glass later"
  requires either dropping the pin (breaks GL-island coexistence),
  replacing pyqtgraph GL islands, or window-containing them — none of
  which is designed or budgeted anywhere in the council. B's own
  weakness 3 ("it postpones the hard proof") is not a weakness note,
  it is the pillar. **Demand: the transparent-QQuickWindow + DWM +
  embedded-island + D3D-RHI spike moves into the U0 probe, before the
  shell bet — not discovered at U6 with track momentum at stake.**

### 2.3 Candidate C — PARK (see §4 for the wallpaper autopsy)

C's determinism argument is real and its QtAds story is genuinely
elegant (nothing to punch). It parks anyway: its guaranteed tier is
either (a) the wallpaper pipeline — under-scoped by an order of
magnitude, §4 — or (b) the bundled lab-slate source, which is honest
but is then **a static skin texture**, not "Mica re-forged", and should
be sold to Kaya as exactly that. C's own weakness 4 concedes it needs
explicit re-blessing against the ratified "DWM materials showing
through" letter. A candidate that needs both a re-ratification and a
subsystem nobody budgeted, to deliver a look the R1 pre-blend already
approximates, is a v2 experiment, not a council winner.

### 2.4 The merge seam — REJECT the triple

"B's contract + C's frost as guaranteed tier + A's DWM as opportunistic
top tier" is the council's most seductive sentence and its worst deal:

- **It is three mechanisms under one vocabulary** — DWM attach +
  re-assert machinery, C's wallpaper/blur/offset pipeline, and the
  pre-blend floor (still needed below C for the memory-pressure rung).
  Each candidate priced itself standalone; the merge is the *sum plus
  integration*, call it 8–12 beats plus two permanent maintenance
  surfaces, carried by one physicist + AI, for chrome.
- **"A's garnish" is flattery for a corpse.** Window-level DWM attach
  on capable windows *is B's classic mechanism*. Naming it "A" in the
  merge makes a killed candidate look like a contributor and invites
  someone to resurrect A's zone-registry discipline along with it.
- **C-as-guaranteed-tier quietly makes the forged frost the fleet's
  daily look** (Ymir's own Horizon 1: typical lab deployment lands on
  the fallback tier more often than not). Kaya ratified DWM materials;
  nobody ratified "the default look is a synthetic wallpaper blur."
  That is a design decision smuggled in through a merge clause.

Honest merge: **B alone**, with C's image-provider idea parked as a
flag-gated QML-era experiment (`image://glass/...` behind a default-off
setting) if and when U-track exists and Kaya blesses the mechanism
swap. Brokkr's contract point stands — B's token triples carry either
renderer without rework — which is precisely why nothing forces the
council to buy the renderer *now*.

---

## 3. Baldr — the in-scene glass and the "dead glass" claim

First, a premise correction the round-2 brief itself needs: **Baldr
captures no wallpaper.** Baldr §4.1 explicitly builds the glass from an
*app-owned* Ambient layer (canvas gradient + glows); it never reads the
desktop. The wallpaper-capture design lives in Brokkr C (and, as prior
art, Frigg's FluentUI finding [S32/S33]). Attacks on "Baldr's wallpaper
assumption" are aimed at the wrong lane — permissions, wallpaper
changes, and privacy are C's problems (§4). Baldr's problems are
different and worse:

- **MAJOR — the baked blur does no optical work.** The Ambient is a
  two-stop vertical gradient plus four radial glows: smooth,
  low-frequency content. Gaussian-class blur of low-frequency content
  is a near-identity — blur of a linear gradient *is* that gradient
  (exactly, away from edges); blur of a soft radial glow is a very
  slightly softer glow. So `GlassPane` = "blurred-ambient texture,
  sampled at pane position, plus tint" renders, to the eye,
  approximately what "ambient texture plus tint" renders — which is
  approximately what the R1 pre-blend over Baldr's own proposed
  ambient-canvas gradient (§3.3) already renders. The one honest cue
  the centerpiece adds is **position-sampling** (the glow shifts
  behind a dragged pane). Frost — the thing "baked blur" is named for
  — needs high-frequency content behind the pane, and Baldr's room has
  none by design. Failure case: the U1.5 kit ships, Kaya drags a
  GlassPane across the ambient, sees a tinted rectangle with a faint
  parallax glow, and asks what the blur pipeline was for. **Fix: drop
  the blur, ship "position-sampled ambient" honestly (cheaper, same
  look), or ratify giving the ambient visible texture/grain — a taste
  decision that belongs to Kaya, not to a pipeline default.**
- **MAJOR — "the dead-glass state must be unreachable" is rhetoric,
  not a requirement.** (a) It is levied on other lanes with no
  mechanism: between the OS killing transparency and *any* app-side
  event arriving, the dead frame is on screen. The honest form is a
  latency bound ("re-resolve within one event-loop turn of the
  composition-changed message, ≤200 ms"), never "unreachable". (b) The
  council's own substrate lane contradicts it by design: Ymir §5
  freezes tier transitions mid-scan — queued, not applied — so
  non-white dead glass persists for the full duration of a run, hours,
  on exactly the machine that matters. Two lanes shipped normative
  texts that cannot both hold; the merge owner must pick (I'd pick
  Ymir's, weakened per §5 below). (c) With attr 20 asserted, the dead
  state is a `#202020`-class plate under a 0.82 dark canvas — a few
  RGB units off the token look. The requirement defends a failure mode
  that mostly stops existing once the actual bug is fixed.
- **MINOR — kill the alarm-de-glass rule (§5.3).** "While a trip alarm
  is latched, chrome drops one rung" encodes hazard state *into the
  material system* — directly against Volundr §1 ("the platform never
  guarantees real translucency … no information may be encoded in it")
  and the spirit of G3. Worse, the cue exists only on T0 machines: an
  operator who learns "frost off = tripped" on the bench reads a
  permanently-frostless RDP session as a standing alarm. A state cue
  that exists on some fleet machines and not others is dishonest state
  — my 05-law lane, and it's a violation. Alarms have a channel;
  ambiance is not it.

The rest of Baldr — the Z-ladder, the worst-case-contrast scrim floor,
the no-glass-on-glass resolver rule, light-theme-is-specular-first,
"never fake blur on classic" — is the best pure-design thinking in the
council. Adopt it. It survives entirely intact with the centerpiece
deflated to position-sampling.

---

## 4. The wallpaper capture (Brokkr C) — the autopsy the prompt asked for

- **Permissions: a non-issue, and I'll say so honestly.**
  `SystemParametersInfo(SPI_GETDESKWALLPAPER)` is a user-session
  parameter read; no elevation, no capture consent, no API gate. Anyone
  attacking C on "permissions" is attacking air.
- **Privacy: minor, but nonzero and unpriced.** It reads the user's own
  wallpaper — fine. The leak is operational: wallpaper-derived pixels
  land in bug-report screenshots, golden captures, and shared
  artifacts. C's own "bundled source for CI, wallpaper for the bench"
  split handles it; just write it down as the reason.
- **MAJOR — multi-monitor and the rendering model are where it dies.**
  `SPI_GETDESKWALLPAPER` returns **one path**; Windows 8+ supports
  per-monitor wallpapers (`IDesktopWallpaper`), so on a two-monitor
  bench with distinct wallpapers, C frosts monitor B with monitor A's
  image. And "position-correct parallax" requires mapping window screen
  coordinates onto the wallpaper *as the desktop renders it*: fit /
  fill / stretch / tile / span modes (registry `WallpaperStyle` /
  `TileWallpaper`), per-monitor target rects, mixed DPI. That is a
  re-implementation of the desktop wallpaper renderer. Brokkr prices it
  as "one function… WILL eat a debugging evening." It is a subsystem,
  and its failure mode is the one C itself names as worse than flat
  tokens: the glass *slides*.
- **MAJOR — wallpaper changes are not reliably observable.** A manual
  wallpaper set broadcasts `WM_SETTINGCHANGE`; **slideshow rotation is
  notoriously unreliable at broadcasting it** (community practice polls
  the `TranscodedWallpaper` file's mtime), Spotlight rotates on its own
  schedule, and solid-color desktops return no usable path at all.
  Failure case: slideshow rotates, the frost keeps showing the previous
  wallpaper — a *stale forgery*, the exact tell C's honesty section
  promised to avoid, now sitting on screen for minutes at a time.
- Net: C's deterministic core (bundled source, offscreen-testable,
  RDP-first-class) is real and worth parking for the QML era. The
  wallpaper mode should be demoted from "source acquisition" to
  "best-effort garnish, primary-monitor-only, static-wallpaper-only,
  off by default" — or cut.

---

## 5. Ymir's 7 rungs + Tyr's 6 rungs — how much ladder does a margin need?

### 5.1 Ymir — REVISE hard (MAJOR)

The question the ladder never asks itself: **what is the blast radius
of being wrong?** Run the numbers the council already produced:

- Ratatoskr's kill matrix: every policy fallback (RDP, battery saver,
  transparency-off, HC aside) lands on a **solid plate whose tint
  follows flag 20**. Dark theme + flag asserted = `#202020`-class
  plate.
- The canvas composites `rgba(bg, 0.82)` over that plate. Delta versus
  the pure token look: a few RGB units.
- Where? At margins the findings doc measured as **~0 px** on the
  cockpit (and per §1, the cockpit window shows no material anyway).

So L2 (session watcher + `WTSRegisterSessionNotification`), L4 (power
broadcasts), L6 (a runtime BitBlt probe that **toggles attr 38 on live
windows** — a flicker vector by construction, and a false-verdict
generator under Acrylic when anything animates behind the window), the
`GlassWatcher` native-event filter, 60-second upgrade hysteresis, and
the scan-freeze queueing policy — that whole subsystem exists to
correct a few-RGB-unit cosmetic delta on satellite-window margins. The
defended harm is smaller than the defense's own failure modes: new
global machinery in the GUI process, running during measurements,
poking DWM attributes on a schedule. Ymir's north star is right ("the
2am operator must never see a broken window") — but the thing that
makes windows *broken*-white is flag 20, and the thing that makes every
fallback benign is I3 (opaque-by-construction tokens). Both are one
beat. The ladder's expensive rungs then guard nothing an operator can
see.

The pixel-equal incident does not justify L6 either: that was a
**design-time discovery failure** (no gate looked at pixels), and its
correct home is the capture harness at gate cadence — Tyr rung 4 —
not a live watchdog inside a lab instrument's GUI process.

**Minimum honest subset of Ymir (keep):** L0+L1 (already exist in
`backdrop.py`); L3's high-contrast check → flat, re-checked on
`WM_THEMECHANGED` (accessibility is the one non-cosmetic stake in the
whole ladder); the attr-20 assert + re-assert on theme toggle and
`WinIdChange` (I2 — the actual fix); the operator override
(`theme/glass_tier=auto|real|token|flat`) as the answer to every
detection lie; the one-line truth log (I5). **Keep the §2 environment
matrix and `decide_tier` as a pure function with the parametrized
offscreen test** — as *documentation and tests*, they are nearly free
and Tyr's §3 demands exactly that shape. **Cut:** L2, L4, L6, the
GlassWatcher event filter, hysteresis, scan-freeze queueing. If a
session change flips the material to its solid fallback, the design
rule "fallback looks intentional without detection" — which B/T1
already guarantees by construction — means nobody needed to be told.

### 5.2 Tyr — REVISE light

Tyr is mostly discipline, not machinery — rungs 0–3 are headless,
cheap, and largely already landed (55 tests), and the "a green rung N
never claims rung N+1 truth" law plus the strict-xfail attr-20 test
(§1.2e) are the two best process ideas in the council. Keep also: the
matrix property test, INV-A/INV-D, and the refusal to golden-image
materials. Three over-reaches:

- **MAJOR — the opaque-ancestor census (§1.2b) requires a second
  stylesheet engine.** "For every widget on the path record … the
  effective QSS background-painting rule" — Qt does not expose
  effective-rule resolution; the test would parse and cascade QSS
  itself, i.e. reimplement the style engine's semantics, and then
  drift from them (widget-sheet-beats-app-sheet, pseudo-states,
  specificity). A census that resolves QSS differently from Qt is
  false confidence with a green checkmark — the exact bug class it
  was designed to catch, one meta-level up. Replace with what is
  actually assertable: the fixed, named list of canvas-path widgets
  gets attribute/palette/autoFill assertions (that is §1.2c, which is
  good), plus the existing QSS-*text* guards extended to any future
  ADS selectors. An allowlist of painters you can honestly enumerate
  beats a cascade you can't honestly resolve.
- **MINOR — INV-C (3-frame flash guard)** depends on capture timing on
  a live desktop; it will flake, get threshold-loosened twice, and then
  assert nothing. Garnish; cut or demote to eyeball-notes.
- **MINOR — cadence honesty.** Rung 4 "per material-affecting beat,
  manual run by Kaya/Adam" plus rung 5 eyeball per material beat is a
  human-in-the-loop tax on every diff that touches `style.py`'s canvas
  region. It will be skipped under schedule pressure, and then the
  ledger will say it wasn't (that is how per-beat manual gates die
  everywhere). The honest cadence is the one Tyr's own item 2 half
  admits: rung 4 + 5 at wave boundaries and phase gates, per-beat only
  for diffs that touch `backdrop.py`/DWM code specifically.

### 5.3 The combined minimum honest ladder (what I would actually fund)

1. attr-20 assert + re-assert (theme toggle, `WinIdChange`,
   `WM_SETTINGCHANGE`) + Tyr's strict-xfail test flipping green — **the
   bug fix.** [1 beat, Noah's track]
2. High-contrast → flat; operator override; one-line truth log.
   [same beat or its rider]
3. `decide_tier` pure function (4 inputs: platform, build, HC,
   override) + parametrized matrix test. [cheap]
4. Harness: INV-A + INV-D + Frigg's lifecycle frames (first-show,
   resize, minimize-restore — prior art says that is where materials
   die), run at wave/phase gates with `verdict.json`. [1 beat]
5. Everything else in both ladders: parked until a failure an operator
   can actually see justifies it.

---

## 6. Cross-lane contradictions the merge owner must resolve

1. **Baldr "dead glass unreachable" vs Ymir scan-freeze** (§3) — pick
   Ymir's, restated as a latency bound with the mid-scan exception.
2. **Baldr §5.3 alarm-de-glass vs Volundr §1/G3** (§3) — kill Baldr's
   rule; Volundr's invariant is the constitution-grade one.
3. **Four tier vocabularies in one night:** Ymir `T0/T1/T2`, Baldr
   `R0–R3` (four rungs, includes an R2 Ymir doesn't have), Brokkr-B
   `REAL_BACKDROP/PREBLEND` (two), Tyr's rungs 0–5 (a *test* ladder,
   different axis, overlapping words). If the seed inherits more than
   ONE enum, LabControl forks the material system in its first week by
   picking the wrong doc. The merge owner publishes one enum and a
   mapping table; the other three vocabularies get deprecation lines.
4. **The BRIEF itself planted the QtAds phantom** and six of eight
   lanes repeated it uninspected (Thor checked; Frigg's null-result
   search was external, not in-tree). Process note for round 3: a
   brief's "what the crew already knows" section is claims, not facts
   — Shiori-check it before eight expensive lanes cite it as ground
   truth.
5. **Volundr nit:** G1–G5 as PROTECTED-region text is right for G1–G3;
   G4's numeric contrast floors and G5's phrasing are design-spec
   material, not constitution material — the PROTECTED region should
   grow by invariants, not by tables, or every retune needs Kaya's
   per-change sign-off forever (constitution creep cuts both ways).

---

## 7. Scope realism — the council's bill vs. the actual emergency

Naively adopted, the eight lanes sum to: a candidate build-out (A: 3–5
beats + permanent tax, or the merge triple: 8–12), Ymir's watcher
subsystem (2–3), Tyr's new test families + verdict plumbing (2–3),
Baldr's QML component set + ambient work (U1.5-era, 2+), Volundr's seed
sections and per-U-stage gate additions. Call it **12–18 beats of glass
work plus two permanent maintenance surfaces** — for chrome, on a lab
instrument, carried by one physicist + AI, while the *actual emergency
in the BRIEF* is a missing one-line DWM attribute and a design text
that promises a material the ratified shell architecture cannot
deliver.

The minimum honest program (everything above condensed):

1. **attr-20 fix + re-assert + strict-xfail test** — cancels tonight's
   white. [1 beat]
2. **Name the collision in DECISIONS** (§1): main cockpit = R1
   pre-blend by construction in the option-(a) era; real material on
   RTT-free satellites; material row added to the §11 flip probe.
   [doc + 1 probe row]
3. **B's token triples + ONE tier enum**, values in `style.py`,
   `decide_tier` pure + tested. [1 beat]
4. **Harness invariants at gate cadence** (INV-A, INV-D, lifecycle
   frames, verdict.json). [1 beat]
5. **U0 probe gains the transparent-QQuickWindow + D3D-RHI + embedded
   island spike** — B's QML pillar proven before the shell bet, and
   the GL-island coexistence question answered while it is still
   cheap. [rides U0]

Five items. Everything else the council forged tonight is either
already inside these five, parked pending a real QML shell, or
machinery in search of a failure mode.

---

## 8. What I checked

- All 9 files in `docs/design/glass_council/` (BRIEF + 8 lanes), full
  reads.
- Repo verification: QtAds instantiation grep (absent from `TCT_app`);
  `gui/stage_view.py:214` (GLViewWidget); `gui/qml_shell.py:417` +
  RHI-pin docstring at :22-24, :66 (QQuickWidget chrome, OpenGL pin);
  `tct_gui.py:420,444` (`TCT_QML_SHELL` opt-in);
  `docs/DECISIONS.md:194-213` (ratified boundary + probe-gated flip +
  "window-level DWM backdrop" clause); `docs/ROADMAP_MASTERPLAN.md:422`
  ("islands per option (a)"); `docs/BENCH_CHECKLIST.md` §11 (flip probe
  rows — no material check); `docs/design/glass_gap_findings.md`
  (~0 exposed canvas px, §4).
- Confidence caveat, stated per my own rules: the path-D mechanics are
  Thor's `[qt-src]`-grade claim, not mine; I verified the in-repo
  anchors (GL child exists, dialog-vs-main-window asymmetry is
  documented) but did not read Qt source tonight. If path D is wrong,
  §1 and the A-kill soften to "run Thor's 30-second detach experiment
  first" — which I demand anyway. Everything else stands on repo text
  I opened myself.

```json
{
  "agent": "loki",
  "subject": "glass council round 2 — attack pass",
  "findings": [
    {"severity": "CRITICAL", "claim": "RATIFIED decision is self-contradictory: 'window-level DWM backdrop' and QQuickWidget-chrome/GL-island architecture are mutually exclusive on the main window (path D)", "failure": "BENCH_CHECKLIST §11 flip probe has no material row; flip lands green, main-window glass dies silently, next white-window night is pre-scheduled", "fix_owner": "adam/kaya (DECISIONS restatement) + noah (probe row)"},
    {"severity": "CRITICAL", "claim": "Brokkr A is dead on classic: its go/no-go is already answered by in-repo evidence, its prime suspect (QtAds stylesheet) is not instantiated in the tree, and its prize is ~0 exposed canvas px", "failure": "3-5 beats + permanent paint-chain tax spent re-running a failed experiment", "fix_owner": "brokkr (kill A; fold riders into B)"},
    {"severity": "MAJOR", "claim": "B's QML pillar silently requires the D3D RHI while the shell pins OpenGL for GLViewWidget coexistence — unpriced, unproven", "failure": "U-track reaches shell swap and discovers translucent-window glass needs replacing/re-hosting every GL island", "fix_owner": "thor/noah (U0 spike)"},
    {"severity": "MAJOR", "claim": "Baldr's baked blur of a smooth app-owned ambient is optically a near-identity; the centerpiece delivers position-sampling, not frost", "failure": "U1.5 kit ships a blur pipeline whose output is indistinguishable from a tinted rectangle", "fix_owner": "baldr (drop blur or ratify textured ambient with Kaya)"},
    {"severity": "MAJOR", "claim": "'Dead glass must be unreachable' is unfalsifiable and contradicted by Ymir's scan-freeze (dead glass persists a full run by design)", "failure": "two normative texts conflict at merge; the claim can never be tested", "fix_owner": "baldr+ymir (latency bound with mid-scan exception)"},
    {"severity": "MAJOR", "claim": "Brokkr C's wallpaper pipeline is a desktop-renderer reimplementation: one path for per-monitor wallpapers, fit/span/tile modes, unreliable slideshow change events", "failure": "frost shows wrong monitor's image / goes stale mid-slideshow — the 'glass slides' tell C itself calls worse than flat tokens", "fix_owner": "brokkr (demote wallpaper mode; bundled source = honest static skin)"},
    {"severity": "MAJOR", "claim": "Ymir's L2/L4/L6 watcher subsystem defends a few-RGB-unit cosmetic delta (post-attr-20, all fallbacks are dark plates) with runtime attribute-toggling probes inside a lab GUI", "failure": "flicker vector + false verdicts under Acrylic; machinery's failure modes exceed defended harm", "fix_owner": "ymir (cut to attr-20 + HC + override + log + pure decide_tier)"},
    {"severity": "MAJOR", "claim": "Tyr's opaque-ancestor census requires reimplementing QSS cascade resolution in the test suite", "failure": "census resolves styles differently from Qt and green-lights the exact bug class it hunts", "fix_owner": "tyr (fixed-list attribute assertions + QSS-text guards instead)"},
    {"severity": "MINOR", "claim": "Baldr's alarm-de-glass rule encodes hazard state into material, contradicting Volundr G3, and the cue exists only on T0 machines", "failure": "operator reads permanently-frostless RDP session as a standing alarm", "fix_owner": "baldr (delete rule)"},
    {"severity": "MINOR", "claim": "Four incompatible tier vocabularies (T0-T2 / R0-R3 / REAL-PREBLEND / rungs 0-5) shipped in one night", "failure": "seed inherits Babel; LabControl forks by picking the wrong doc", "fix_owner": "merge owner (one enum + mapping table)"},
    {"severity": "MINOR", "claim": "The BRIEF's QtAds suspect was a phantom and six lanes repeated it unverified", "failure": "council round anchored on a false premise; only Thor checked the tree", "fix_owner": "adam (Shiori-check brief claims before round 3)"}
  ],
  "what_i_checked": ["all 8 lane docs + BRIEF, full reads", "QtAds instantiation grep (absent)", "stage_view.py:214 GLViewWidget", "qml_shell.py:417 QQuickWidget + OpenGL RHI pin", "tct_gui.py TCT_QML_SHELL gating", "DECISIONS.md ratified boundary text", "ROADMAP_MASTERPLAN.md:422 option (a)", "BENCH_CHECKLIST.md §11 probe rows (no material check)", "glass_gap_findings.md ~0 canvas px"],
  "verdict": "revise"
}
```

*— Loki. The idea wasn't tired everywhere — B and Frigg earn their
keep, Thor did the only real detective work — but half this council
forged armor for a knight who is, per the council's own coroner,
already dead on the main window. Fix the one-line bug, name the
collision, ship the honest pre-blend, and prove the QQuickWindow path
before betting the U-track on it.*
