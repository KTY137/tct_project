# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit; stage explicit paths; never `-am`.

**Updated: 2026-07-14 evening — THE GATE IS GREEN at `f7a1a3e` (2685 passed, 0 failed). The branch waits on Kaya: card-token veto, pilot PNGs, merge decision. Both interrupted beats from the morning landed and are committed.**

## HEAD / TRUTH

- Local `design/cockpit-v5 @ c9615c1`. **NOT pushed, NOT merged — GATE GREEN, Kaya's call.**
  Nothing touched real hardware. The branch is Kaya's to review.
- **origin/main @ `a7dca3f` = THE TRUNK** (unchanged).
- **Night briefing (open this first):**
  https://claude.ai/code/artifact/8dfa85d2-692f-4603-b69f-4087d31b9d9f
  (copy in `artifacts_claude/nachtschicht_20260714/`)

## ▶ RUN THIS FIRST (his ask: "grob die full qml migration mit glass shell sehen")

```
cd TCT_app
.venv/Scripts/python.exe scripts/glass_shell_preview.py --dark
```

A REAL translucent QQuickWindow, real DWM acrylic, a REAL BiasPanel island on a
simulated supply, real detach, leakage+compliance restored. Everything unwired
wears a visible STUB badge. `--probe` prints the measurement and exits.

**And in the shipped app: Theme editor → Material → Acrylic.** His persisted
`theme/window_backdrop` is `none`, and until `636ce78` turning it on did
nothing. That is very likely the whole story of "I never see glass".

## 🔑 THE DECISION WAITING FOR HIM

**Does SCENE earn its keep?** The spike proved in-scene MultiEffect works (60 fps,
0 crashes / 80 launches) — and Loki then asked what, in THIS app, it is
architecturally *permitted* to blur. Answer: **nothing.** The workspace is a
QWidget tree; the chrome is a non-interop QQuickWidget island (different scene
graph). The 9 pyqtgraph/GL islands **never migrate** (ratified) and paint OVER the
QML scene via airspace, not under it. What a legal pane could still frost —
`canvas`/`card`/`well` — are flat colour fields, whose blur is themselves.

⇒ **The free DWM window material is the entire realized return of the glass
programme.** AMBIENT (0 pp CPU) vs STRUCTURAL (+13 pp/pane, needs THREE ratified
reversals and a rewrite of the 9 plots on a scene-graph API our own spike saw
segfault in ~50 % of Python runs). Loki: ≥10× beats, unbounded risk, in exchange
for blurred card borders.

## ✅ THE NIGHT — 21 commits (`a7dca3f..37cead3`)

**The glass chain — why he never saw it. FOUR independent causes, all now fixed:**

1. `636ce78` the QSS was **never rebuilt** on a live backdrop change: the window
   got the glass *property* with no *rule* behind it. (The probe script hand-added
   `apply_theme()` — which is why the probe measured glass and Kaya did not.)
2. `636ce78` windows were **born without an alpha surface** in the shipped default.
3. `4e54784` the **DEFAULT QML shell painted an opaque lid** over a healthy
   material: chrome island **0.00 % → 96.01 %** backdrop-tracking pixels; whole
   window 0.65 % → 28.27 %. TWO painters (an opaque `setClearColor` **and** four
   opaque QML fills) — fixing either alone measures as a no-op.
4. His persisted `theme/window_backdrop` is **`none`**.

**The rest:** `58df585` Odin crew ported (Brokkr/Loki/Baldr) · `801f2ab` the glass
contract (FLAT<TOKEN<WINDOW<SCENE<COMPOSED, 6912-env matrix) · `b702a85` round 01 ·
`beddc37` verdict + 2 ratifications · `8299381` **the alarm with no home** ·
`bbe3b10` the shader ban is unearned — but Qt **cannot** blur behind a window ·
`c071f28` QML live-preview · `f9a73bc` round 02 · `c37cac8` **the elevation ladder
does not exist** (dark canvas→panel ΔL* 1.46; light is inverted) · `1d9eee1` the
GlassShell skeleton (measures its own glass) · `4ca8331` **71 WCAG failures, and
the cause was not the colours** (19 QSS blocks painted ink on an rgba wash of
itself) · `82ddd2f` **the minimize blocker does not exist** ([84,84,84] is DWM's
inactive-window fallback) · `9e525f5` Mary's review booked · `f934e65` **G-B2b —
the contract wired to reality** (the RDP ceiling had NEVER fired) · `cf18550`
**50 black icons** killed at the root · `37cead3` the activation scan gate.

## 📐 BALDR'S FLOOR RE-DERIVATION (2026-07-14, report-only — landed in transcript)

Against the OWNED ambient ground (kit §1.1: dark L* ∈ [0, 7.61], light
[88.89, 96.89]), validated against 4 of the kit's own published numbers (≤0.5%):

- **Old `MIN_PANEL_GLASS_ALPHA = 0.50` → new accessibility floor 0.0** for
  pane/shelf/chrome/card under the `{text, muted}` ink law. The opaque
  suppression Kaya dislikes can drop almost entirely. **Light is the binding
  theme** (4.97:1 worst — ~10% margin; dark has 44%): do not ship literal α=0.
- **One real floor: semantic ink on LIGHT glass = α ≥ 0.24** (binding pair:
  `good` at α=0 = 4.21 FAILS; `crit` needs no floor; warn/accent/sim 0.18–0.21).
  Kit ships 0.55/0.86 — 2–3× margin. No kit bugs found.
  **CORRECTION (machine-arbitrated, `28e6dec`):** Adam's earlier check claimed
  this floor dissolves (5.19 at α=0). That was WRONG — he tested only the bright
  edge of the ground band; the dark edge binds for dark inks. Baldr's hand
  arithmetic was right. The arbitration script is
  `TCT_app/scripts/kit_contrast_check.py` — run it, don't re-argue it.
- `MIN_BACKDROP_CANVAS_ALPHA = 0.80` untouched (protects the DWM-garnish edge,
  still facing an unknown desktop). Garnish-on does NOT change interior floors
  IF the "garnish strip never carries text" invariant holds — verify with
  `scripts/glass_probe.py`, currently confirmed only from code comments.
- **NEEDS KAYA:** `GLASS_SAFE_TEXT_TOKENS=(text,muted)` is a ratified/PROTECTED
  law written against the unknown-desktop premise, which has moved. Extending it
  would allow coloured semantic words on own-ground glass cards (dark: any α;
  light: α ≥ 0.23). His call, not ours.
- Wanted CI tests (after the bisection releases the tree): render the real
  procedural ground and measure its ΔL* range (does `GROUND_TINT_ALPHA_MAX=0.07`
  really produce ΔL*4.0 in BOTH themes?); kit §2.1 is missing the light-shelf
  SCENE row (inference `panel`@0.55 reproduces kit's own 5.86 within 0.2%).

## ✅ THE GATE IS GREEN — `f7a1a3e`, 2685 passed, 0 failed, 8:48

**The branch is gate-clean for the first time since the wave began.** Detached
Task-Scheduler run on the bench (the only reliable path — use `C:/bench\gate.bat`
via `schtasks /run /tn tct_gate` + the poller; never a live SSH stream).

The road there, kept for the record: run 1-2 died of a REAL native crash (the
icon watcher, then pyqtgraph-in-the-repolish-walk — both fixed); runs 3-5 died of
the Tailscale stream freezing (~25 min) while the suite was CLEAN at 23/83/88%;
the first detached run finished 2590 green + 2 monkey seeds red (the gate WORKED,
the monkey was blind — classification now keys off WIRING, `d13af76`); the second
detached run died at test 17 (`test_ambient_ground` needed a QApplication the
bench's alphabetical order never created — `f7a1a3e`); the third is GREEN.

**Landed on top of the green 21d2b17 base:** kit foundation `88cc542` (card/shelf
tokens, AmbientGround band-clamped to ΔL* 3.58, GlassPane/Card/Well/HazardSurface)
· bias pilot `074943f` (hazard boundary byte-identical, Mary: "I would ship this
to a bench with HV cabled") · monkey wiring-classification `d13af76` · ground perf
`0fde84c` (stall 330→10 ms, cache 1.7 GB→30 MB) · QApplication fix `f7a1a3e`.

## ⏳ WAITING ON KAYA — the branch is his now

1. **The card-token veto:** `artifacts_claude/card_token_delta/` (dark cards rise
   L* 5.07 → 10.76 app-wide; partially reverses his ratified v6 recede pass, done
   on his implement-today order). One look.
2. **The pilot:** `artifacts_claude/pilot_bias/` (both themes) + run the app.
3. **Merge decision** for design/cockpit-v5 → main (gate green, Mary approvals on
   file). Push has NOT happened — nothing has left the machine.
4. Then: the 12-panel wave (handoff in `074943f`), the shadow-ladder spike, the
   semantic-ink-on-glass law extension (measured legal at α ≥ 0.24).

## 🧑‍🔬 NEEDS KAYA (at 10:00)

1. **The SCENE decision** (above). Everything downstream hangs on it.
2. **Chip labels are now neutral ink.** Fill and border keep the hue; the text
   still names the state. Mary's cheaper alternative to the offered "8 more
   tokens": the QML island (the DEFAULT shell) still carries a **saturated 8 px
   state dot** — put that same dot on the classic `StatusChip` and the colour
   carrier is back without hue in the ink. **His eye decides.**
3. **The `card` token.** Fixing the dark ladder partially reverses the v6
   "cards recede toward the canvas" pass — **which he ratified two days ago**.
4. **Is the lab local or on RDP?** RDP caps at TOKEN. The repo cannot answer it;
   now that the probes are wired, `grep "glass: resolve"` on the lab box answers
   it without asking anyone.
5. **Fable quota exhausted** — judgment beats fell back to Opus all night.
6. **Nobody stood four metres back.** Every "glanceable across the room" claim is
   a MODEL, not an observation. Ten minutes with four swatch pairs on the real
   lab monitor ends it.
7. Alt-tab flicker check (`backdrop.CANVAS_FOLLOWS_ACTIVATION = False` is the
   kill switch if it strobes) · the wrapped ribbon at real DPI · icon re-tint
   across a light→dark→light toggle. All three booked in BENCH_CHECKLIST §14.

## NEXT (queue)

1. **Round 03 / the kit** → then ONE pilot panel (**Bias**: hazard surface +
   detached + live readouts) → then the wave. **The kit BEFORE the panels**, or
   13 panels become 13 dialects. Cross-panel META REVIEW at every wave boundary
   (his ask) = the CONTACT SHEET, not a meeting.
2. **`panel_kit.registered_glass_panes()` hands out DEAD C++ objects** after a
   QQuickWidget-heavy teardown. **Confirmed independently by THREE agents.**
   pytest's alphabetical collection order is the only thing hiding it.
3. A **ΔL\* surface-separation test** — nothing asserts a card is visible against
   its canvas. That is how a 1.03:1 dark ladder shipped.
4. Theme-editor contrast validation on a swatch pick (the preset hatch: hazard
   ink now rides the UNLOCKED `text` token).
5. `statusLamp[unknown]` renders identically to `[neutral]` — an operator cannot
   tell "no information" from "idle" (law 7).

## 📋 THE PANEL CENSUS (Shiori) — the wave's foundation

- **Programs wearing a panel costume** (own beat each): `planner` 2524 ·
  `analysis` 2203 · `scope` 1655 · `motor` 1212 · `camera` 958.
- **Simple compositions** (one wave): intensity 224 · device 348 · sequencer 456
  · calibration 578 · scan_map_view 615 · laser 703 · stage_view 255.
- **Hazard surfaces** (opaque at EVERY tier, keep their own gate): bias,
  multi_bias, motor, calibration, planner, sequencer.
- **Three panels own EXTRA top-levels** ⇒ three more glass surfaces:
  `device_panel` IS a QMainWindow · `scope` has a floating `_TriggerDialog` ·
  `camera` has a modal `_ROIDialog`.

## 🚨 RATIFIED THIS NIGHT (Kaya, verbatim in DECISIONS.md)

- **Danger topology:** a dangerous action belongs to the PANEL that owns the
  hardware, NEVER to the shell. The shell may DISPLAY hazard state; it may never
  TRIGGER it. No presentation-layer mediator will be built.
- **Detachable panels are permanent:** `detachable_tabs.py` stays the ENGINE;
  QML is a VIEW over it. Every detached panel is its own top-level ⇒ its own DWM
  material and its own tier.
- **The ShaderEffect/MultiEffect ban is lifted as policy** ("ja heb das verbot
  auf") — then measured, and narrowed: in-scene blur is legal and works, backdrop
  blur is physically impossible in Qt, no effect on hot-path islands (+13 pp CPU).

## ✅ Standing verdicts (do not re-derive)

- HV authorization chain COMPLETE + Mary-APPROVED. Transport serialisation
  complete. D1 capability spine COMPLETE (Mary's D1b riders still open).
- venv = real CPython 3.10.11. Sim bias multi-channel end-to-end.
- Test economy binding · bench full suites only at gates.

## Rules pointers (binding, in CLAUDE.md)

Test economy · bench full suites only · session hygiene 1–4 · free lanes never
idle · Codex = queue-file only · ONE here-string per shell call · verify
`git log --stat` after multi-beat landings.
