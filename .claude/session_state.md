# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit; stage explicit paths; never `-am`.

**Updated: 2026-07-14, end of the night shift. Kaya is back ~10:00.**

## HEAD / TRUTH

- Local `design/cockpit-v5 @ 37cead3`. **NOT pushed, NOT merged.** Nothing
  touched real hardware. The branch is Kaya's to review.
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

## 🔴 THE BENCH IS RED — a NATIVE CRASH, and the gate caught it

Full suite at `37cead3` on sophonone: **exit `-1073741819` = `0xC0000005` =
ACCESS VIOLATION.** Not a failed assertion — the process died.

```
gui/status_widgets.py:457   eventFilter      <- _IconThemeWatcher, NEW in cf18550
gui/style.py:3350           apply_theme
tct_gui.py:992              _toggle_theme    <- a REAL user action
tests/test_qml_shell.py:1028
```

`cf18550` (the icon fix) passed **110 targeted tests** and crashes the process on
a **theme toggle** once enough windows have been torn down. Root cause is written
in its own docstring **as a false claim**: *"Filters die with the widget they
watch, so nothing here can touch a half-destroyed QWidget."* `_icon_watcher` is a
module-level singleton with **no parent** — it dies with nothing, and it outlives
the `QApplication` that created it. The sentence that justifies the safety is the
sentence that is not true.

**This is exactly what the wave-boundary bench gate exists for**, and it is the
fourth appearance tonight of the same widget-corpse class (`panel_kit`'s pane
registry, caught independently by three agents).

**DO NOT PUSH OR MERGE `37cead3`.** Fix in flight.

## 🔥 IN FLIGHT

| Beat | Agent | Locks |
|---|---|---|
| **Fix the `_IconThemeWatcher` use-after-free** | Noah (Opus) | `gui/status_widgets.py`, icon tests |

## ⚠️ ADAM'S OWN ERROR, ON THE RECORD

The first bench dispatch **silently did nothing**: Bash ate the backslashes
(`C:UsersnukeiDesktopagent_envbench_run.ps1`) and PowerShell **still returned
exit code 0**. Had I trusted the exit code I would have reported a green full
suite that never ran. Re-dispatched through the PowerShell tool. Session-hygiene
rule 4 earned its keep: *never claim what you have not seen.*

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
