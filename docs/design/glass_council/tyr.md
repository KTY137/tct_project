# Týr — the test spine for the material system

Glass Council lane: Quality & Reliability. Everything below is designed against
what is actually in the repo today: `gui/backdrop.py`, `gui/style.py`
(`_canvas_fill`, `BACKDROP_CANVAS_ALPHA`, `PANEL_GLASS_ALPHA`, the `glassPane`
registry), `tests/test_backdrop.py` (55+ headless material tests already
landed), `tests/test_theme_editor.py` (canvas guards),
`tests/test_panel_kit_cockpit.py` (glassPane registry),
`TCT_app/scripts/capture_onscreen.py` (read read-only, per the brief), and the
U-track gate text in `docs/ROADMAP_MASTERPLAN.md` (~lines 190/338–346).

## 0. The verdict ladder — say what each rung can and cannot prove

The pixel-equal incident is the case study the whole spine is built around:
every headless assertion was green while the visual was dead, because the QSS
canvas rule and `_prepare_window_canvas` disagreed and no test made them agree.
The spine's one job: **every regression class fails at the cheapest rung that
can catch it, and a green rung N never claims rung N+1 truth.**

| Rung | What it proves | Where it runs | Verdict scope |
|---|---|---|---|
| 0 | Tokens, pure decision functions, persisted settings | headless, per-beat | "the intent is right" |
| 1 | Widget attributes, palettes, QSS text, flag/call ordering | headless, per-beat | "the commands we would issue are right, and they agree with each other" |
| 2 | Recorded DWM calls via monkeypatch seams (IDs, enums, order) | headless, per-beat | "the native API would be driven correctly" |
| 3 | Offscreen alpha-multiplication (margin pixel sampling) | headless, per-beat where cheap | "the alpha channel is actually multiplied against something" — the proven ceiling of offscreen (`glass_gap_findings.md` §4: `#080e1d` vs `#080f1d`) |
| 4 | Onscreen pixel invariants via the capture harness | real desktop session, gated cadence (§2) | "the compositor actually rendered a difference where the design says it must" |
| 5 | Human eyeball | Kaya, `BENCH_CHECKLIST.md` §8 | blur quality, artifacts, taste — never automatable, never skipped at phase gates |

Rung 4 is the only automated rung that can detect the two known silent-failure
modes: DWM returning `S_OK` without compositing (logged as INFO in
`backdrop.apply_backdrop` precisely because no assertion can see it), and the
"alpha hole punched, no material behind" failure. Rung 5 is the only one that
can judge `_CANVAS_MODE` candidate A vs B. Any report that claims "glass works"
must name its rung.

## 1. Headless-assertable bucket (rungs 0–3)

### 1.1 What is already pinned (do not re-author)

`test_backdrop.py` + `test_theme_editor.py` + `test_panel_kit_cockpit.py`
already cover: the support matrix via the injectable `_version_probe` /
`_platform_probe` seams; attribute ordering (ExtendFrame before
SetWindowAttribute; `WA_TranslucentBackground` only after BOTH DWM calls
succeed; fail-safe on nonzero HRESULT and on raise); central-widget
(`#mainShell`) symmetry; kind="none" reset + palette resync + repolish-vs-update
discipline; backdrop-before-opacity apply order; the **opacity pin**
(WS_EX_LAYERED suppression — the regression test for a bug already lived once);
settings round-trip + hostile-persisted-value fail-opaque; fan-out incl.
transient skip; detached-window pickup; `QSurfaceFormat` alpha ≥ 8;
`_canvas_fill` byte-identical-when-off / `rgba()` when active / never touches
panel surfaces; `glassPane` registry lifecycle and its QSS selectors. This is a
good rung-0/1/2 spine. The bucket below is about the **gaps**.

### 1.2 New tests to add (each is headless, each has a named failure it catches)

**(a) The material matrix as a property test, not spot checks.**
Parametrize (backdrop kind × theme × preset) — single source of truth
`backdrop.BACKDROP_KINDS` × the preset registry — and assert the full QSS
contract for each cell: canvas fill equals `p['bg']` iff kind=="none", else
`rgba(bg, BACKDROP_CANVAS_ALPHA)`; the rgba components parse back to the
palette hex and the token float; panel/readout selectors stay flat hex in every
cell. Today only dark + spot checks are pinned. Generated coverage over an
enumerable space is the rule (my invariants), and it makes "a new preset forgot
the material contract" impossible to land silently.

**(b) The opaque-ancestor census — the structural test for "the barrier".**
The root cause of the pixel-equal verdict was an opaque painter sitting on the
canvas path that no test enumerated. That is attribute/QSS/palette state —
assertable offscreen. Build the real `TCTMainWindow` (the suite already does),
walk the widget chain from the top-level to each registered glass surface
(exposed canvas; each `glassPane` registrant), and for every widget on the
path record the triple (`autoFillBackground`, effective QSS
`background`-painting rule, palette `Window` role). Assert the path contains
**zero opaque painters not on an explicit allowlist** while a material is
active (probes forced supported, DWM seams stubbed). This is where **QtAds dock
containers** — the brief's suspect #1 — get caught headless forever: the day a
QtAds container (or any future wrapper) starts painting an opaque background on
the canvas path, this test names the widget, before anyone captures a pixel.
The allowlist is the honest register of what deliberately blocks glass
(plots, camera raster, cards without `glassPane`).

**(c) The two-code-paths-agree test (the actual bug, generalized).**
The QSS canvas rule and `gui.backdrop._prepare_window_canvas` were two
independent opinions about the same pixels. Pin their agreement directly: for
every state in {none, mica, acrylic} × {applied, reset}, assert
(`WA_TranslucentBackground` state, palette Window role, `_canvas_fill` output)
form one of the *legal triples* — translucent attr + transparent palette +
rgba fill, or opaque attr + theme palette + hex fill — and nothing mixed.
A mixed triple is exactly the July-13 bug class.

**(d) `_CANVAS_MODE` candidate B is currently untested.**
Every attribute test runs candidate A ("translucent_attr"). Parametrize
`_set_canvas_translucent` over both modes (monkeypatch the module constant):
mode B must toggle `WA_NoSystemBackground` and must NOT touch
`WA_TranslucentBackground`/palette; symmetry on clear. Which mode *renders*
correctly stays rung 5 (module docstring says so, correctly) — but "flipping
the constant doesn't half-apply state" is rung 1 and free.

**(e) DWMWA_USE_IMMERSIVE_DARK_MODE — pin it test-first. FINDING: absent.**
Grep-verified today: attribute 20 is set **nowhere in TCT_app**. Mica's tint
follows this per-window flag; without it a dark-themed app gets light-mode
Mica — visually "everything white", the brief's symptom 2 / suspect 2. The
spine reserves the contract now, as `xfail(strict=True)` until the owning crew
lands the call: on every material apply AND on every theme toggle while a
material is active, the recorded DWM calls include
(`set_attr`, 20, 1 if dark else 0), issued in the same batch as attribute 38
(never left to a later repaint). Strict-xfail means the suite flips loudly to
green the day it is implemented, and can never silently regress after.

**(f) Offscreen alpha-multiplication smoke (rung 3, promote from anecdote to
test).** The findings doc proved a one-green-unit delta by hand-sampling a
theme-editor margin pixel. Make it a test: render a small real dialog
offscreen with backdrop forced active vs none, `grab()` it, sample the
declared margin region, assert the two grabs are NOT byte-identical there and
the delta direction/magnitude is consistent with `BACKDROP_CANVAS_ALPHA`
blending against the backing store (tolerance ±2/255 per channel). Content
regions must remain byte-identical. This is the last rung headless can reach —
label it in the test docstring so nobody upgrades its verdict.

**(g) Token schema guard for the seed.** `BACKDROP_CANVAS_ALPHA`,
`PANEL_GLASS_ALPHA`, and every future material token: assert domain
(0.0 < α ≤ 1.0), that QSS embeds exactly these values (no drifted literals),
and — once the QML U-track starts — the parity test in §4(a). One test,
reflection-driven (the `capture_onscreen.snapshot_settings` idiom: enumerate
by suffix, never hand-list).

### 1.3 Bucket mechanics

Mark all of the above plus the existing material tests
`@pytest.mark.material_contract`. The bucket gets a row in the Pre-D1
`docs/test_bucket_map.md` with its exact run command
(`QT_QPA_PLATFORM=offscreen pytest -m material_contract -q`). It is a
**per-beat gate for any diff touching** `gui/backdrop.py`, `gui/style.py`
canvas/token regions, `gui/panel_kit.py`, QtAds container styling, or
`main.py`'s surface-format hook — cheap enough (<20 s) to demand
unconditionally. It rides bucket-A rules at U-stage gates (green unmodified).

## 2. The onscreen pixel harness as a regression gate (rung 4)

### 2.1 What to diff — invariants within one run, not golden images of glass

Mica samples the desktop wallpaper; Acrylic samples whatever is behind the
window. A golden PNG of a material scenario therefore bakes in wallpaper,
accent color, DPI, and Windows build — it would rot on every host change and
train people to bless diffs. **Do not golden-image the material scenarios.**
Instead the gate asserts *relations between captures of the same run*
(hermetic against wallpaper/host):

- **INV-A (the pixel-equal verdict, inverted — the headline regression test):**
  `none_*.png` vs `acrylic_*.png` / `mica_*.png` must **differ** in the
  declared exposed-canvas regions (fraction of pixels with channel-delta ≥ 4
  must exceed 1%), and must be **near-equal** in content regions (plots,
  camera, readouts: ≤ 0.1% of pixels with delta ≥ 8) — the "content stays
  opaque" design law, expressed in pixels. INV-A failing on the equal side is
  exactly the 2026-07-13 afternoon bug; failing on the content side is a
  translucency leak into a live readout — both are one-line verdicts.
- **INV-B:** `mica_*` vs `acrylic_*` differ from each other in exposed-canvas
  regions (distinct materials actually selected — catches a mapping bug where
  both kinds land on the same DWMSBT value).
- **INV-C (flash guard):** in each 3-frame transition burst, every frame's
  mean luminance lies within [min, max] of the two endpoint scenarios' canvas
  regions ± margin — no white/black flash frame (the A1/A4 checklist items,
  automated).
- **INV-D (the "white Mica" tripwire):** dark theme + material active →
  exposed-canvas mean luminance below a generous threshold (e.g. < 100/255).
  Wallpaper-tolerant by construction on a dark-ish desktop; combined with
  §1.2(e) it catches the lost immersive-dark-flag class at two rungs.
- **Golden images only for the token-fallback look** (`none_*` scenarios and
  the classic opaque shell): those are compositor-independent and may be
  golden-diffed per host fingerprint, threshold near-zero.

**Region masks are not hand-drawn.** At capture time the harness already owns
the live window; it should emit, per scenario, the exposed-canvas rects
(window frame minus the central-content geometry) and content rects into the
manifest. The diff step consumes manifest + PNGs and is a pure, headless,
CI-safe script — only the *capture* needs a desktop.

### 2.2 Verdict artifact

Next to `manifest.txt`: `verdict.json` — per-invariant PASS/FAIL with the
measured numbers, plus environment fingerprint (Windows build, DPI, capture
method + probe evidence — already emitted — extended with the
`HKCU ... \Personalize\EnableTransparency` value, accent color, and a
wallpaper hash so a drifting verdict is *explainable*). The ledger gets the
verdict line + artifact path, same durable-evidence pattern as [Mary]/[Kaya]
sign-offs. A capture run without a verdict.json is an eyeball session, not a
gate.

### 2.3 When it runs — honest cadence

The harness refuses headless **by design**; a real DWM verdict needs an
*interactive desktop session*. An SSH service session on the bench does not
composite — so "run it on sophonone via ssh" is not a thing today. Cadence:

1. **Per material-affecting beat** (same trigger list as §1.3): manual run by
   Kaya/Adam on the real desktop, < 90 s, verdict.json to the ledger. This is
   the review-brief line item, not optional garnish: rungs 0–3 green without a
   rung-4 verdict is precisely the state that shipped the pixel-equal bug.
2. **Per U-stage merge-back and at v6/glass phase gates:** mandatory, listed
   beside [Bench] in the gate line; U-stage runs capture the qml shell too
   (§4(e)).
3. **Bench automation as a follow-up spike, not a promise:** sophonone *could*
   run it via an autologon interactive console session + scheduled task
   (`schtasks` interactive), making rung 4 semi-automatic at gates. Until that
   spike proves out with a CONFIRMED capture-method probe verdict, the gate is
   a desktop-session gate and the plan says so — never silently substitute an
   offscreen run (the harness refuses anyway; the *process* must refuse too).
4. **Environment-config rows (§3.3) reuse the same harness** — one tool, one
   verdict format, every rung-4 fact in one artifact shape.

## 3. Environment-matrix smoke — testing Ymir's ladder without six machines

### 3.1 The architectural demand I levy on the ladder (contract, since Ymir's
doc does not exist yet as I write)

The ladder must be built as **pure decision core + injectable probe layer** —
exactly the pattern `backdrop.py` already established with `_version_probe` /
`_platform_probe` and that `test_backdrop.py` exploits. Concretely:
`detect_environment() -> EnvReport` (a frozen dataclass of primitives:
platform, build, qt_platform, is_rdp, transparency_enabled, battery_saver,
high_contrast, gpu_class, ...) assembled from one small probe function per
field, and `select_tier(EnvReport) -> MaterialTier` as a **pure function with
no OS calls**. If the ladder is not shaped like this, it is not testable
without six machines, and the council should bounce it. Ymir: this is the one
thing I need from you.

### 3.2 The matrix, headless (rung 0 — milliseconds per case)

- **Cartesian property test** over probe values: build ∈ {0, 19045, 22000,
  22621, 26100} × qt_platform ∈ {windows, offscreen, xcb, wayland, minimal} ×
  is_rdp ∈ {F,T} × transparency ∈ {T,F} × battery_saver ∈ {F,T} ×
  high_contrast ∈ {F,T} × gpu ∈ {hw, software}. That is ~2000 cases; assert
  **invariants**, not a hand-written expectation per cell:
  - *Totality:* every combination maps to a defined tier, never raises.
  - *Monotonicity:* removing any capability (flip one field toward "less")
    never raises the tier — a degradation ladder that can climb on loss of
    capability is broken by definition.
  - *Fail-safe:* any probe error value (0, "", unknown enum) resolves to a
    tier ≤ the tier of the corresponding known-good value — unknown never
    means "assume glass".
  - *Determinism:* same report, same tier, twice.
- **Golden table for the ~10 named scenarios** (Win11 desktop / Win11 RDP /
  Win11 transparency-off / Win11 battery-saver / Win11 high-contrast / Win10 /
  Linux X11 / Linux Wayland / offscreen CI / software-GL): exact expected tier
  each, as a table-driven test that doubles as the ladder's documentation.
- **Live-demotion smoke:** transparency toggled / RDP connect mid-session →
  the re-evaluation path (WM_SETTINGCHANGE or polled) demotes the live tier
  without restart: fake the probe flip, assert the tier signal fires and the
  material is reset fail-safe (reuses the existing `apply_backdrop(w, "none")`
  reset contract and its tests).
- **Probe-reality contract tests:** each probe function additionally gets ONE
  test that calls it *for real on the current host* and asserts only the
  **type/domain** of the result (never the value) — so a Windows API rename or
  a registry-key move breaks loudly in the suite instead of silently returning
  a default that the fail-safe invariant then hides forever.

### 3.3 The real-hardware rungs Kaya can actually produce (no machine farm)

Config rows achievable with the two machines that exist, each a
`BENCH_CHECKLIST.md` row + one onscreen-harness run (§2) as evidence:
RDP from the PC into the laptop (real `SM_REMOTESESSION=1` — the single most
important degradation case per the brief's honesty rule); Settings →
transparency effects OFF; battery saver ON (laptop on battery); offscreen
(free — the entire suite). Win10 has no representative machine: it is covered
headless by the build-number matrix plus the existing hard rule that
`< 22621` never calls DWM (`test_unsupported_old_build` and friends) — state
in the checklist that Win10 is *simulated* coverage, per the never-claim rule.
Linux tiers ride PORT1's existing gate (Xvfb/EGL/Mesa + QSG_INFO parser,
roadmap Portability section) — the "no DWM at all" tier is exercised by every
Linux CI run by construction.

## 4. The U-track per-stage qml-boot gate — material assertions

The roadmap gate (ROADMAP_MASTERPLAN.md ~338–346) already demands: boots under
`TCT_SHELL=qml` offscreen + viewmodel-contract suite green + [A-green] +
[Bench]. Add a **material clause** per U-stage:

- **(a) Token parity, generated:** one test enumerates the material tokens on
  the Python side (reflection, §1.2(g)) and reads the same names through the
  QML-exposed theme singleton/context property; values must be equal. Never a
  hand-copied constant in QML — the parity test makes the "one token
  vocabulary spanning both shells" mandate (the brief's mandate expansion)
  machine-checked at every stage instead of aspirational.
- **(b) Fallback-tier boot is the smoke, by construction:** qml-boot runs
  offscreen, so the scene necessarily boots in the token-fallback tier. Assert
  it *says so*: scene root exposes `materialTier` and it reads "fallback"
  offscreen — a shell that cannot report its tier cannot be gated. Assert the
  fallback visuals come from the pre-blended tokens (item property spot checks
  against §(a)'s values).
- **(c) The ratified shader ban, as an object-tree walk:** the constraint "no
  live MultiEffect/ShaderEffect glass" is currently prose. The gate walks the
  instantiated QML object tree and asserts **zero instances** of
  MultiEffect/ShaderEffect (and `layer.effect` users) — full stop, until Kaya
  re-ratifies. If a future ratification allows them on the hw tier, the test
  becomes tier-conditional; the offscreen gate still proves the fallback path
  instantiates none (that is exactly the "must degrade on software/RDP" rule).
- **(d) Opacity law for islands:** for each QWidget safety/GL island embedded
  in the stage's panel: no `WA_TranslucentBackground` on the island container,
  and any QML item whose geometry overlaps an island rect has opacity 1.0 and
  `layer.enabled == false` — "content stays opaque" ported to the scenegraph,
  as assertions, per stage, so U4/U5 (camera, scope, motor) inherit it
  automatically rather than by review vigilance.
- **(e) Material settings round-trip:** extend the gate's existing
  dirty-settings round-trip with the material keys: classic writes
  backdrop=acrylic → qml boots, reports requested="acrylic",
  resolved-tier="fallback" (offscreen) — and the hostile-value case (mirror of
  `test_hostile_persisted_backdrop_is_dropped_to_none_not_obeyed`) resolves to
  fallback, never a crash, never obeyed.
- **(f) The rung-4 line:** the per-stage [Bench] run on the real GPU includes
  one onscreen-harness capture of the stage's hero window under the qml shell,
  verdicts INV-A/B/D (§2.1), artifact in the ledger. QML is where real glass
  gets *easier* (scenegraph alpha) — which means it is also where a silent
  regression to fake-glass-only would go unnoticed longest without a pixel
  gate.

## 5. Summary of demands on the other lanes

- **Ymir:** ship the ladder as pure core + injectable probes (§3.1) or it is
  untestable; expose `EnvReport` as a frozen dataclass of primitives.
- **Whoever owns the mechanism:** every new native call goes behind a
  monkeypatchable seam like `_dwm_set_window_attribute` (this is why 55 tests
  exist at all); DWMWA_USE_IMMERSIVE_DARK_MODE (attr 20) is missing today —
  §1.2(e) pins it test-first, strict-xfail.
- **QML shell (U-track):** scene root must report `materialTier`; theme
  singleton must be generated from the Python tokens, not transcribed.
- **Adam/process:** rung-4 verdict.json is a ledger artifact class; "glass
  works" claims without a named rung get bounced — that is the never-claim
  rule applied to pixels.

— Týr. The hand goes in the wolf's mouth so the binding holds: the eyeball
work Kaya must personally do (rung 5, per material beat) is the honest price
of a compositor we cannot see headless; everything cheaper than that, the
suite holds.
