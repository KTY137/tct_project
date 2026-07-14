# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit; stage explicit paths; never `-am`.

**Updated: 2026-07-14, SESSION-CRASH RECOVERY. The previous session lost
connection mid-wave; a fresh session recovered from this ledger + git. Branch
`design/glass-wave-1`, HEAD `b99b5a6`. Everything the old ledger listed as
in-flight LANDED before the crash (see git log): runbg-affinity fix `e0a9d91`
+ Mary rider `5576378`, wavegen driver sweep `8e85f2a`, waves 1–3
(`3a6d0ea` stage_view, `2e02b8d` intensity, `5971741` laser). Wave 4
(scan_map_view) was orphaned complete-with-test in the working tree →
verified green (57 targeted) and committed `b99b5a6`. Wave 5 (sequencer,
HAZARD) was orphaned WITHOUT its test → Noah re-dispatched to finish it.
Bench gates stay DETACHED only (schtasks + poller).**

**DRIFT NOTE (RETRACTED):** the recovery session first claimed
`.claude/beat_status.ps1` missing — WRONG (Glob false-negative on the dot
directory; Mamoru standup caught it). The script exists and runs; used from
here on. Lesson: verify "missing file" claims with `ls`, not Glob alone.

## ⚠️ TREE / MACHINE STATE (read before staging ANYTHING)

- `TCT_app/configs/devices.yaml`: CLEAN again as of 2026-07-14 late —
  Kaya reverted his real-hardware flip himself (back to simulation ×6,
  tree == HEAD, nothing was ever staged/committed). If it goes dirty
  again, the old rule stands: NEVER stage it.
- Instruments may still be physically cabled ⇒ agents still never run
  the app locally; targeted headless (offscreen) pytest only; rule 6.

## ✅ LANDED (pre-crash session + recovery session)

- `11407b6` orphaned `scripts/glass_probe.py` · `ab0cbee` wave beat 0
  (panel_kit prune-on-read, Mary APPROVED) · `7b4ea94` + `8e85f2a` wavegen
  freeze class swept across all five VISA drivers (Paul + Mary riders) ·
  `e0a9d91` + `5576378` _run_bg GUI-thread affinity + teardown join (Mary
  reviewed, RISK rider applied).
- **Wave 1/12** `3a6d0ea` stage_view · **2/12** `2e02b8d` intensity ·
  **3/12** `5971741` laser · **4/12** `b99b5a6` scan_map_view (recovered
  from crash-orphaned tree, 57 targeted green, committed by recovery
  session).
- `211618d` rotation bookkeeping.
- ⚠️ Mary review status of waves 1–4: laser beat produced the UNGATED
  'Output on' finding (item 0 below). Non-hazard wave beats batch at the
  wave boundary per review cadence; scan_map (4/12, non-hazard) joins that
  batch.

## 🔥 IN-FLIGHT BEATS (locks)

**🏁 THE WAVE IS COMPLETE — 12/12 landed. HEAD `90a3a23`.**
Boundary machinery in flight (no code beats, no file locks):

**🟢 GATE #3 GREEN on `d073b32`: 2842 passed, 0 failed, 2 skipped,
1 xfailed, 9:36.** The freeze family held against the full suite.

**FREEZE FAMILY CLOSED (3/3):** `99b6f74` (O(1) structural bounds)
landed; **Mary final pass: APPROVED_WITH_RIDERS** — value_count parity
verified as TEXTUAL IDENTITY (same bytes computed, no float regime can
diverge); the oversize-early-return behavior change SIGNED OFF as safe
(independent HV arm gate at scan_controller.py:568; size error blocks
start on every consumer path). Rider (queued, Kiroku writing
TECH_DEBT): per-loop-tolerant structural bound (malformed-YAML shape
only, not GUI-reachable) + oversize diagnostic-collapse hint + the
option-c worker abort.

**Roadmap artifact** built at
`artifacts_claude/roadmap_status_20260714/roadmap_status.html`
(incl. Kaya's "living glass" U1.5 scope addition, also written into
ROADMAP_MASTERPLAN.md U1.5 per his ask). Artifact deploy service 503ing
— page viewable from the repo file; retry publish later.

**THEME-EDITOR PAIR LANDED, BOTH MARY-APPROVED:**
- `eaa2425` glass-death fix (Kaya's live bug): root cause was NOT the
  persisted-settings suspect — the Material macro combo desynced after
  a direct Backdrop pick and its activated handler replays a stale
  mapping on same-value reselects. Resync + re-entrancy guard (guard
  cannot latch: set-in-try/clear-in-finally, Mary-verified); 9
  regression tests incl. material-survives-every-other-setting ×6.
- `729841f` opacity clobber (Mary's fix-before-gate-4 ruling): _apply()
  now sources from _draft_window_opacity, not the display-forced
  slider; 85%→Acrylic→Apply→preference intact. 199 targeted green.

**✅ MERGED + PUSHED (Kaya's order 2026-07-15): `main@45781fa`**, gate
#4 evidence in the merge message. **polish-freeze tag MOVED** (Kaya's
order) from the premature a7dca3f to 45781fa, force-pushed, move
documented in the tag annotation. Roadmap artifact (current):
https://claude.ai/code/artifact/fa02f118-9ade-44dc-b58c-6bbd59bcd3f1

**KAYA'S COURSE SETTINGS (2026-07-15, binding):**
- Design programme FROZEN; the full glass/SCENE design round runs
  AFTER the full QML migration (U1.5 stays lean — kit spec only).
- QML migration = "fast DAQ, zero capability loss" (his words) — the
  existing U-track gates already encode this; treat as ratified intent.
- **Glass bugs DEFERRED to post-migration** ("maybe they are gone
  then" — correct: the backdrop/activation plumbing is deleted by U6).
  The second-top-level irrecoverable glass loss: Noah stopped mid-
  trace, findings note pending → TECH_DEBT. Rule of thumb ratified in
  chat: defer what the revamp DELETES, never what it INHERITS
  (safety, controller, state-ownership root causes).

**P0' CORRECTION (Adam desync, caught by Abel):** P0' wavegen
per-point apply was ALREADY LANDED 2026-07-13 (`5c75696` + Mary riders
`ad38db5`, ancestors of main) — per-point apply in scan_controller
:1447, HDF5 wavegen_command_trace, validator key/range checks. Abel
verified conformance vs planner_routines_v2.md §1, 179 green, zero
changes. Adam claimed it unstarted without checking git — session
hygiene rule 4 violation, corrected here. Masterplan Part VI beat #4
is DONE.

**🔁 SESSION RESTART HANDOFF (Kaya restarts for the migration epoch):**

- **LANDED: `856281b` laser 'Output on' DangerGate — Mary: APPROVED,
  clean for its scope** (decline ⇒ zero submissions + honest UI; OFF
  never gated pinned; modal gate blocks double-click; P0'-apply vs
  output_on separation VERIFIED in scan_controller; executor arming is
  authorized-run-scoped, acceptable).
- **🔴 HER BLOCKER (found by the every-submitter grep): SIBLING ungated
  emission in calibration_panel._run_reference** — one click of 'Run
  reference-diode calibration' starts _ReferenceWorker whose run()
  calls waveform_generator.output_on() (calibration_panel.py:85), NO
  confirmation; the panel HAS self._gate (:109) but only uses it for
  motion. **FIX IN FLIGHT (noah-laser-danger-gate resumed):** gate the
  worker START in _run_reference (mirror laser _output_on; fail-safe
  refuse without gate) + tests + the tct_gui construction-order assert
  (her nit). LOCKS: gui/calibration_panel.py, tct_gui.py, calibration
  test file. **RESOLVED: fix landed `978c7d1`, Mary CONFIRMED
  ("EMISSION-SAFETY HOLD RELEASED — both ungated PDL 800 trigger paths
  are now gated"); everything pushed, origin/main == main == 978c7d1.**
  Her final nit (tct_gui assert trivially true, keep as documentation)
  needs no action. Old session's agents are DEAD — do not SendMessage
  them. NOTHING is in flight. The new session starts clean at U0.
- **THE NEW EPOCH: U-track (QML migration) is the priority.** Entry
  point **U0**: cut `ui-qml-migration` at tag `polish-freeze`
  (= main@45781fa, verified) + RHI/GL pin probe on the bench GPU
  (QSG_RHI_BACKEND=opengl, GL_RENDERER == bench GPU, zero
  software-fallback lines, probe log in ledger). Then U1
  (viewmodel-first test reclaim — planner slice waits for trunk-P2).
  Kaya's binding course settings above: lean U1.5, full glass/SCENE
  design round AFTER the migrate, fast DAQ, zero capability loss.
- Tree at handoff: clean except this ledger (commit it). Trunk
  main@856281b pushed? — 45781fa is pushed; 22d2201+856281b are
  LOCAL-ONLY until the laser review clears (push after Mary's
  verdict, per review-then-push discipline).
- Read also: memory tct-current-work.md (rewritten for this handoff),
  TECH_DEBT :185-188 (freeze-family riders + deferred glass bug).

**KAYA LIVE FEEDBACK (2026-07-14 night):** he saw the QML preview's
in-scene blur ("kit panel") and calls it "the most awesome" — the SCENE
appetite is REAL now. Standing Loki verdict (+13pp/pane, 3 reversals,
9-plot rewrite on a segfaulting API) explained to him; his call framed
as a roadmap track needing a Brokkr/Loki round, with the cheap middle
path = QML shell as chrome (SCENE legal there already). NO ratification
yet — awaiting his word.

**Mary on `d073b32`: APPROVED_WITH_RIDERS.** Item 1 resolved fully in
Abel's favor — PlanLimits' docstring already caps total_leaf_visits and
the pre-existing (e) gate already compared visits: "not even a change".
Items 2/3/5 verified clean (only per-leaf iteration was the gated one;
bounded-proof holds on every path incl. the ValueError path; spies are
load-bearing). Item 4 = the pulled-forward beat above. Residual noted:
no general "no sync unbounded walk in a click handler" invariant test.

[LANDED `d073b32` validator walk bound (Abel, resumed instance):
oversize = total_leaf_visits > max_points computed STRUCTURALLY before
the walk (subsumes points gate + catches visits-explosion-with-points-
under); trailing-MANUAL_PAUSE walk skipped on oversize; structural
checks unconditional; remaining walk provably ≤ max_points. 3 new
tests incl. walk-skip spy. 120 targeted green. Residual documented:
ultra-wide single loop slows materialize itself pre-gate (primitive
concern, separate beat).]

[LANDED `44e17d4` estimate cap fix (Abel): estimated=False + None
sentinels above ESTIMATE_MAX_LEAF_VISITS=1M (structural gate, instant);
render shows "—" + warning, never fake 0 s; core traversal untouched.
99 + 68 targeted green. **Mary: APPROVED_WITH_RIDERS — "the bench-gate
red is genuinely dissolved."** Consumer audit CLEAN (only planner_panel
formats the cost fields, both paths guarded).]
[LANDED `0e247d8` her riders: residual DOCUMENTED on the constant
(Adam's ruling: ceiling stays 1M — lowering would deny estimates to
validator-legal plans; option-c cooperative walk abort = the queued
real mitigation) · constant pinned ≤1M by test · PlanEstimate
__post_init__ invariant (estimated ⟺ runtime not None). 100 green.]

**DIAGNOSIS (Abel, CONFIRMED, repro timed):** estimate walk is
O(Π loop-counts), NO cap; 342k visits/s ⇒ monkey's 21⁶ plan ≈250 s ≫
90 s timeout; stuck worker in C-level generator loop never services
quit() ⇒ wait(3000) times out ⇒ QThread destroyed while running =
the 0xC0000005. scan_plan.py + plan_estimate.py have EMPTY diffs vs
merge-base — pre-existing bug, wave only changed the monkey's dice.

**🔴 GATE RESULT (f48f281): RED — EXITCODE 0xC0000005** after 675s at
~91% (everything before the monkey was green dots). Log copied to
%TEMP%\gate_out.txt locally. NOT a wave regression by current evidence
(see diagnosis beat above) — but the gate stays red until fixed;
NO merge. Fix beat after Abel's diagnosis → Mary (concurrency class).

**RIDER BEAT LANDED `b900a80`** (Noah + Adam): census widened to
QListWidget/QListView WITH a QComboBox-popup exemption (the blanket rule
flagged combo popups in laser/calibration — found by probe, fixed);
the widened census then correctly caught planner's registered
_palette_card (hosts a QListWidget) → **Adam's ruling: unregistered**
(rule uniformity > one cosmetic pane; planner is hazard anyway; planner
now registers NOTHING). Device window wired into _toggle_theme fan-out.
Trivially-true asserts dropped. **182 passed** across all wave/rollout/
theme suites. NOTE for Mary's awareness (not re-reviewed: change removes
glass from a hazard panel — safety-positive direction, driven by her own
rider): planner diff is one register call + comment + test asserts.
**DOCS LANDED `f48f281`**: ARCHITECTURE changelog waves 4-12 +
BENCH_CHECKLIST §15.

**BOUNDARY VERDICTS (all in):**

- Wave 12 planner: **Mary APPROVED, zero riders** (keyboard tab-order
  nit only). ALL FOUR hazard beats now clean-approved.
- Non-hazard batch (4·6·8·9·11): **Mary APPROVED_WITH_RIDERS** — every
  flagged judgment call ruled CORRECT (camera info_card = set-once
  device identity, PDL precedent; scope/analysis live-value exclusions
  right). Riders → noah-wave-riders above. Open items for later:
  scope `_lbl_probe_warn` (warn ink) on a registered card — defensible
  per Mary, flag for a uniformity pass; durable live-value-QLabel
  MARKER as kit enhancement (design item, needs an owner decision).
- Mamoru standup: all nine landing claims VERIFIED against git;
  devices.yaml in no wave commit; beat_status.ps1 EXISTS (the ledger's
  "missing" claim was Adam's Glob false-negative — retracted above).
- Kiroku bookkeeping DONE (uncommitted): ARCHITECTURE.md changelog
  waves 4-12 (:647-663) + BENCH_CHECKLIST.md §15 glass-wave visual
  acceptance (:895-996). Commit with the rider beat.

[LANDED wave 12/12: `90a3a23` planner (hazard) — HazardSurface over the
danger aside (latch + Abort), _palette_card kept, per-action gate/
mutation/executor/teardown byte-identical, Abort in no bulk-disable set;
97 targeted green. Mary review in flight above.]

AFTER the three reports: Kiroku bookkeeping rotation (ARCHITECTURE
changelog + wave summary), contact sheet (cross-panel META), detached
bench gate (schtasks + poller) — then the branch is Kaya's to merge.

[LANDED wave 11/12: `34453ab` analysis — zero registrations (plot/data
dense, bias-shaped outcome for content reasons); math/loading/fade_swap
byte-identical; 107 targeted + 28 supplementary green; header/recent-runs
exclusion judgment calls → boundary batch.]
[LANDED wave 9/12: `4b74c1c` scope — chrome registers, live-value cards
out, _TriggerDialog satellite idiom; 45 targeted + 63 supplementary
green; Channels/Measurements exclusion judgment calls → boundary batch.]
[LANDED wave 10/12: `f86675d` motor (hazard) — **Mary: APPROVED, zero
riders.** Hazard invariant verified by construction; STOP live mid-move
(absent from _motion_widgets by design); outside widgets never command
motion. Recurring trivially-true-assertion nit → queued batch chore.]

[LANDED wave 8/12: `4725f64` camera — shelf register=False, 5 chrome
cards in / 4 content cards out, _ROIDialog satellite idiom, worker
untouched; 63 targeted + 159 supplementary green. info_card
registration (laser-PDL precedent) flagged for the wave-boundary batch.
Non-hazard ⇒ joins the boundary Mary batch with waves 4 + 6.]

[LANDED wave 7/12: `18469ca` calibration (hazard) — rollout registrations
kept, opaque HazardSurface on the repeatability section, DangerGate/
homed/workers byte-identical per Noah (Opus). 49 targeted + 37 adjacent
green. **Mary: APPROVED, nits only.** Stop-inside-HazardSurface ruled
SAFE (no opacity/mouse-transparency, stylesheet doesn't cascade, stripe
clipped to 4px left strip; Stop enabled-state driven solely by run
lifecycle). RECURRING NIT (waves 5+7): the "fill unchanged across
set_panel_glass(True)" assertion in both wave hazard tests is trivially
true by construction — batch micro-chore: drop/comment it in
test_wave_sequencer_render.py + test_wave_calibration_render.py, the
registry-absence asserts are the real coverage.]

[LANDED wave 6/12: `dc3592c` device manager window — shelf register=False
as CONTENT consequence (QTableWidget Z4 disqualifier), bulk-actions Card
registers; _run_bg fix untouched, affinity tests green; 25 targeted + 129
supplementary green. Follow-up micro-chore: add the window to
tct_gui._toggle_theme refresh_theme fan-out (out of beat file-scope).
Non-hazard ⇒ joins the wave-boundary Mary batch.]

[LANDED wave 5/12: `bf41854` sequencer (hazard) — crash-orphaned diff
recovered intact, Noah audit no-gaps, 57 targeted green. **Mary: APPROVED,
zero riders** ("I would ship this to a bench with HV cabled"). One nit,
strength-of-proof only: `test_hazard_surface_opaque_fill_survives_panel_
glass_switch` is trivially true (surface never registered ⇒ set_panel_glass
provably no-ops); real invariant held 3 ways (no #hazardSurface glass QSS
variant style.py:1799-1806 · register_glass_pane refuses HazardSurface
panel_kit.py:1295 · instance-sheet pin re-asserted by the theme round-trip
test). → optional micro-chore, not a defect.]

## HEAD / TRUTH

- **main @ `98a66b1` = THE TRUNK** (merged + pushed, Kaya's order).
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

0. **🔴 NEW (wave find, 2026-07-14): the laser 'Output on' button is UNGATED.**
   `armedBtn` in gui/laser_panel.py is the real PDL 800 trigger (wavegen output
   → laser trigger input = emission if the manual box is armed), and
   `_output_on()` submits straight to the VISA worker — no DangerGate, no
   confirm. Every HV-energizing path in bias_panel rides `_confirm_hv`; the
   census classed laser non-hazard, which is why nobody looked. Behavior left
   byte-identical by the wave beat (flagged, not changed). DECISION: should
   laser emission join the rule-2 danger list (confirm dialog / DangerGate like
   HV enable)? If yes → Paul+Noah beat; also reclassify laser as a hazard panel
   (opaque surfaces) and re-run its wave beat's register decisions.

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

1. **Mary review for wave 5 (sequencer, HAZARD)** the moment it lands —
   never batched. Then the wave-boundary batch review for waves 1–4
   (non-hazard).
2. **Remaining simple-panel beats**: device 348 (IS a QMainWindow — extra
   glass surface) · calibration 578 (HAZARD → immediate Mary).
   [DONE: intensity · stage_view · laser · scan_map_view; sequencer in
   flight.] Copy-handoff verbatim from pilot `074943f`:
   shelf + panel_header; `_well()` for inputs; HazardSurface as pure
   parent-frame wrap; kit surfaces into refresh_theme; non-hazard panels
   REGISTER for glass (bias's register=False is bias-specific); dynamic danger
   buttons stay out of ActionBar. Hazard beats → immediate Mary review.
3. **The 5 program beats** (own beat each): planner 2524 · analysis 2203 ·
   scope 1655 (+_TriggerDialog) · motor 1212 (HAZARD) · camera 958 (+_ROIDialog).
4. **Contact sheet** (cross-panel META review) at the wave boundary + bench gate
   (detached schtasks path) before merge.
5. Micro-chore (Noah, any free slot): `scripts/kit_contrast_check.py:188`
   hardcodes is_proposed=True for the dark card token, but `_DARK_CARD` shipped
   (style.py:560, palette :743) — the PROPOSED banner is stale (Mamoru standup
   find, 2026-07-14).
6. A **ΔL\* surface-separation test** — nothing asserts a card is visible against
   its canvas. That is how a 1.03:1 dark ladder shipped.
7. Theme-editor contrast validation on a swatch pick (the preset hatch: hazard
   ink now rides the UNLOCKED `text` token).
8. `statusLamp[unknown]` renders identically to `[neutral]` — an operator cannot
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
