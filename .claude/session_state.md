# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit; stage explicit paths; never `-am`.

**Updated: 2026-07-15 ~12:45 — ALL FOUR morning gates RESOLVED.
① measurement B RAN LIVE and PASSED all 3 assertions
(`artifacts_claude/measurement_b_20260715T102648Z/`; island 30.24 Hz,
DAQ CV 0.084, QML 60.03 fps) — §7.1 thresholds RATIFIED unchanged;
panel-scoped calm ships. ② Q2 = YES (U1 closed; planner tail =
self-gated later beat on AxisSpec). ③ kit spec SIGNED (cf52d21).
④ merge-back AUTHORIZED — executes on bench green: full suite RUNNING
on sophonone at branch HEAD (background task; bundle @ cf52d21;
later commits are docs-only). [A-green] PASS across cf6dd58..HEAD
(52 files, 0 changed). U2 EXECUTION OPEN — Shiori brief-check in
flight, then day-0 overlay micro-spike + U2.1 Surface core dispatch.**

## EPOCH: QML migration (U-track, docs/ROADMAP_MASTERPLAN.md Part II "UI")

Kaya's binding course settings (2026-07-15): design programme FROZEN except
lean U1.5 (kit spec only); full glass/SCENE round AFTER the migration;
"fast DAQ, zero capability loss"; glass bugs deferred to post-migration
(defer what the revamp DELETES, never what it INHERITS).

**Kaya directive (2026-07-15, this session): "den Schmied mit darauf
ansetzen"** → Brokkr joins the migration epoch, scoped strictly to the lean
U1.5 deliverable (QML component-kit spec candidates), NOT the frozen full
design round. Dispatched (see in-flight).

## ✅ U0a — BRANCH CUT (this session)

- **`ui-qml-migration` cut at main `cf6dd58`** (current working branch).
- **Branch-point ruling (Adam, documented judgment):** the masterplan says
  "cut at the polish-freeze tag" (= `45781fa`), but the tag predates two
  Mary-APPROVED rule-2 emission-safety gates on main (`856281b` laser
  'Output on' DangerGate, `978c7d1` calibration reference-diode gate).
  Kaya's ratified rule — defer what the revamp DELETES, never what it
  INHERITS; safety is inherited — means the branch must carry them, so it
  is cut at main `cf6dd58` with `polish-freeze` verified as ancestor
  (`git merge-base --is-ancestor` OK). Delta tag..cf6dd58 is exactly the
  two safety fixes + ledger chores. The U0 gate assertion "the tag
  resolves" is satisfied: tag → `45781fa`, annotated, on trunk.
- main == origin/main == `cf6dd58` (verified this session). Branch push
  waits until U0b evidence is in.

## 🏛️ RATIFIED THIS SESSION (Kaya, 2026-07-15 — full entry in DECISIONS.md)

- **"DO LANTERN"** — candidate LANTERN is the U1.5 QML kit direction.
  Conditions carried: frost-bake spike BEFORE U2 commits (in flight,
  below); Loki/Baldr attack pass against Lantern WITH spike numbers
  (queued after U0); Twin's Theme-gap audit = prerequisite homework;
  Ledger's LOCKED-row idea stays mergeable.
- **kit.md §1.2 amended** (PROTECTED, per-change approval given):
  "never animates during a run" → **auto-calms PER PANEL** — Kaya's
  refinement "auto calm should only then apply to that panel": only the
  ground behind the running panel stills, the room keeps flowing;
  detached panels calm whole. Consequence on the record: the Baldr
  distraction gate is no longer fully satisfied → attack-pass item #1;
  local calm is a redundant run cue, never the only indicator.

## 🌙 OVERNIGHT MANDATE (Kaya, 2026-07-15 night — "koch mal die Nacht weiter")

Kaya sleeps; Adam runs autonomous via /loop (dynamic, task-notification
driven, ScheduleWakeup fallback ~25 min). Directive: maximum migration
progress by morning. HARD LIMITS overnight: **no merge to main** (Q2
unanswered — prepare full gate evidence, merge waits for Kaya) · **no
windowed GUI runs** (measurement B live = Kaya) · safety rules and
review cadence unchanged.

**Overnight queue (work top-down as beats land):**
1. Land wave 1 (U1.1/U1.2/U1.3 in flight) + immediate Mary on U1.3 +
   thematic Mary batch (U1.1+U1.2), commit each after review.
2. Wave boundary: Mamoru standup (claims-vs-git + locks) + Kiroku batch.
   **Kiroku batch spec is Mary's verbatim counts_recompute_instruction
   (her U1.0 review JSON, on file in this ledger's git history):**
   manifest §Counts ~461→~465 (subset 129→133), row bucket cell C→B,
   'Manifest files: 45' UNCHANGED, behavior split UNCHANGED; bucket_map
   totals → A49/B22/C42/D5=118 (revert C bump, take B 21→22), move the
   test_qt_danger_gate.py row C→B, fix stale A-header 47→49; do NOT
   touch the §Counts bottom coverage line (own reconciliation beat,
   with C14's table). Plus: trim test_planner_panel.py stale docstring
   (Mary NIT), ARCHITECTURE.md changelog, research index.
   ⚠ WAITS for abel-u13 to release SAFETY_NORMATIVE_TESTS.md.
   **U1.0 REVIEW VERDICT (mary-u10 DONE): APPROVED_WITH_NITS; Q3
   RATIFIED at 9; bucket ruled B.**
3. U1 gate evidence: [A-green] + S2 targeted suites local + bench full
   suite (`bench_run.ps1 -Branch ui-qml-migration`; ssh reachability
   check first; if bench down, SAY SO in the ledger, never substitute).
4. Theme-bridge beat (C13's 42 exposures → TOKEN_MAP + style.py
   constants + 2 app_settings keys + retire QML hardcode guesses) —
   Noah; token law is Adam-delegated, shadow ladder has Kaya's nod.
5. U1.5 kit-spec consolidation (Brokkr, Fable): assemble the binding
   QML component-kit spec from candidate_lantern + round-03/kit.md +
   rulings 1–7 into ONE document staged for Kaya's [Kaya] gate.
6. If queue empty: free-lane chores (Codex second-opinion on wave-1
   diffs; NEVER idle), TECH_DEBT sweep via Mamoru.

**Kaya wakes ~09:00 — a readable morning report (plain language, he
asked for that register) must be the loop's standing deliverable, ready
whenever the wake happens.**

**Kaya's morning checklist (write into the morning report):**
① measurement B (45 s, README in measurement_b_prep_20260715T004557Z)
② Q2 yes/no (close U1 after wave 1, planner tail later — recommended)
③ [Kaya] gate on the U1.5 kit spec (staged overnight)
④ merge-back decision once ①–③ done. HONESTY LINE: U2+ entry is
structurally gated on ① and ③ plus AxisSpec (trunk-P2) for U1.4 — "die
Migration fertig bis morgen" is not reachable; the reachable maximum is
U1 gate-ready + U2 unblocked-except-Kaya-items. Say this plainly.

## 🔥 IN-FLIGHT BEATS (locks) — FULL THROTTLE (Kaya directive, new session 2026-07-15)

Restart happened at the planned boundary; fresh session picked up the
handoff. Kaya: "run all agents in parallel full throttle" → maximum
non-conflicting parallelism dispatched:

- **Codex C14** (free lane, enqueued 20260715T010507Z) — bucket-map
  completeness re-enumeration (Mary RISK: 152 files on disk vs 118
  mapped, 34-file pre-existing gap). Advisory table only; Kiroku
  executes the map fix at the boundary with C14 as input.
- ✅ **U1.3 LANDED `a5bacf2`** — sequencer split per §5: read-only
  QueueVM (no coordinator/gate/callable/notify/timer), panel = retained
  command/safety host, 6 reclaims, 10 (c) byte-untouched (numstat
  0-added proof), 41+14 green. Two deviations for Mary to ratify
  (envelope_html kept byte-stable for the pinned (b) test;
  _on_active trimmed to gating-only). VM-suite conftest caveat: run
  alongside a widget suite, not solo (house pattern). Manifest lock
  RELEASED → Kiroku batch unblocked at boundary.
- ✅ **mary-u13 DONE: U1.3 APPROVED** (clean, no nits) — safety
  boundary structurally verified (VM imports no coordinator/gate/
  callable/notify/timer; standing-law pair real); both deviations
  RATIFIED (envelope_html bounded one-directional; _on_active trim is
  actually spec-conformant). Residual notes: VM suites must co-run
  AFTER a widget suite (pre-existing house pattern, bench alphabetical
  order unaffected); vm.envelopeSummary production-dead until the QML
  port binds it (intentional §5.2).
- **kiroku-w1** (background) — boundary bookkeeping batch. LOCKS:
  docs/SAFETY_NORMATIVE_TESTS.md (§Counts + bucket cell) ·
  docs/test_bucket_map.md · TCT_app/tests/test_planner_panel.py
  (docstring only) · docs/ARCHITECTURE.md.
- ✅ **U1.1 LANDED `a88b823`** — 17 reclaims + standing-law pair (20
  tests in new suite), residue 15 byte-untouched (diff shows deletions
  only), 136-test consumer sweep green, import-boot chain intact.
  Deviations (accepted): snake_case value_at/cursor_text; empty section
  headers removed with fully-reclaimed sections. → Mary thematic batch
  with U1.2.
- ✅ **U1.2 LANDED `62cec74`** — 15 reclaims + 2 (d) retired (panel
  40→23), Q1 executed (ONE ETA derivation in RunStateViewModel).
  Byte-proof method: ran unmodified 40 against the refactored panel
  BEFORE trimming (all green). Deviations for Mary-wave1 to ratify:
  (1) openInAnalysisEligible = NOT run.active statt run.terminal
  (terminal nur vom 1 Hz-Poll gefüttert, den ein panel-owned VM in U1
  nie sieht); (2) ETA-Placeholder-Test per Q1 notwendig umgeschrieben.
  ⚠ FLAGGED: test_qml_shell.py hängt am theme-toggle-island-Test (auch
  "solo", aber unter Parallellast) → **RECONCILIATION RUN pending: ONE
  quiet-machine run of test_qml_shell.py when no agent is testing**
  (before the bench gate; if it still hangs quiet, it's real and goes
  to Noah).
- ✅ **mary-wave1 DONE: U1.1 APPROVE + U1.2 APPROVE.** Deviation (d)
  RATIFIED — and upgraded: NOT-active is the FAITHFUL reclaim (legacy
  panel gated on `not _run_active`; §4.3's `terminal` wording would
  have CHANGED behavior — spec letter drifts, implementer was right).
  ONE ETA derivation confirmed by grep. Residue proofs verified
  (U1.2's 42 added lines are comment-only move markers — cosmetic
  gloss on "byte-untouched", accepted). RISK finding → conftest
  micro-beat below.
- ✅ **mamoru-w1 DONE: standup PASS all 5** (claims-vs-git, lock/tree
  clean, AxisSpec gate closed, reclaim counts exact, import probes
  clean). Only drift: ledger HEAD line (fixed same tick).
- ✅ **kiroku-w1 DONE** — counts per Mary's rulings + full wave-1
  reclassification (his correct escalation: my brief's 118-numbers
  were pre-wave-1; staging doc §3 governs): **bucket_map now
  A49/B25/C39/D8 = 121** (4 C→B, 3 new D rows), manifest ~465/133,
  planner docstring trimmed, ARCHITECTURE.md indexed 3 new VMs + 4
  changelog lines. Committed below.
- ✅ **noah-conftest DONE, landed `9982ce7`** — ruling 9 executed:
  session-scoped offscreen QApplication fixture + isinstance reaper
  guard; grep found zero conflicting tests (subprocess-based
  no_immortal_panels unaffected); ALL verification green incl. the
  previously-crashing VM-first order (41 passed, exit 0). §7.4a
  amended + DECISIONS ruling 9 in the same commit. Morning Mary batch:
  give the conftest diff a light look (test-infra, broad blast
  radius, verification pasted).
- ✅ **noah-p1 DONE, landed `2c01e38`** — standing-law consolidation:
  names + per-file coverage EXACTLY preserved (evidence table in
  report; sequencer's 2 extra forbidden types kept via extra_types),
  ScopeViewModel gap backfilled, 76/76 green ×2, negative-proof run.
  Honest delta: net +47 LOC (Niwashi estimated −60; helper + backfill
  weigh more) — value = ONE source for the safety-boundary encoding.
  Morning Mary batch: include (test-only, S2-adjacent encoding).
  NOTE for the RUNNING BENCH SUITE: it snapshot-bundled @ 40beaa3,
  BEFORE this commit — the bench evidence covers the pre-P1 tree;
  P1's own 76/76 tail is its verification (test economy).
- **brokkr-u15** (Fable, background) — U1.5 kit-spec CONSOLIDATION
  (frozen programme, lean deliverable): one binding doc for Kaya's
  morning [Kaya] gate from lantern+kit.md+rulings 1–8+C13 bridge
  table+seam. LOCK: docs/design/qml_kit_forge/kit_spec_v1.md (new).
  DECISIONS wins conflicts; no new design decisions.
- QUEUED after conftest-fix + reconciliation land (test-lane serialized):
  Theme-bridge beat (Noah; gui/qml_theme.py + style.py constants +
  2 app_settings keys + retire QML guesses; C13 table = the spec),
  then bench full suite (gate evidence incl. the conftest fix), then
  U2 implementation plan on paper (Fable architect).
- ✅ **noah-hang DONE, fix landed `40beaa3`** — verdict: STALL not
  wedge (test completes 48.9 s solo; ~4 real dark↔light toggles ×
  full-app QSS re-polish over ~3400 widgets; test born slow in
  4e54784 on 07-14; wave-1 innocence VERIFIED). Marker fix
  slow+timeout(180) per house precedent. CRITICAL catch: without it,
  the 60 s thread-timeout os._exit would have ABORTED the whole bench
  run. Bench-log reading note: faulthandler dumps a traceback at 90 s
  on this test — noise, not failure. Morning list: (a) durable test
  restructure (toggle once per mode, flip glass via bridge.pull);
  (b) ~95-widget/toggle leak in refresh_theme/apply_window_backdrop
  path → TECH_DEBT candidate, owner Noah.
## 🟢 U1 (wave 1) GATE EVIDENCE COMPLETE (masterplan format)

- **gate-id:** U1 wave-1 (viewmodel-first test reclaim; planner tail
  U1.4 excluded per Q2 proposal, HELD for AxisSpec) · **commits:**
  8166752 · a88b823 · a5bacf2 · 62cec74 (+ infra 9982ce7, 40beaa3,
  2c01e38) · **verdict:** PASS pending Kaya Q2 confirm for merge-back ·
  **date:** 2026-07-16 (night).
- **[Bench]: SUITE GREEN — 2876 passed, 2 skipped, 1 xfailed,
  604 s — @ 40beaa3 on sophonone** (bundle sync log + summary in task
  output; slow-marker held, no faulthandler abort).
- [A-green] PASS (re-run over 8166752; nothing since touches bucket A).
- S2 normative suites green inside the full run; safety-class beats
  U1.0/U1.3 Mary-APPROVED at landing; U1.1/U1.2 thematic APPROVED.
- VM headless smoke: 5 VM suites solo green post-conftest-hardening
  (ruling 9); test_qml_shell.py green (island test 49 s under its
  180 s budget).
- Reclaim accounting: 38 C→B/D + 2 (d) retired; bucket_map
  A49/B25/C39/D8=121; manifest ~465/133 (Kiroku b027711).
- Mamoru standup PASS (all 5 tasks).
- **NOT done overnight by design:** merge-back to main (Kaya Q2 + gate
  ④), U1.4 planner tail (AxisSpec), measurement B (operator).
- ✅ **u2-architect DONE, landed `81c56fe`** — u2_hero_plan.md: day-0
  overlay micro-spike (the ONE unmeasured mechanic) + U2.1–U2.7 with
  locks/exit criteria; single-construction-site command strip keeps
  test_scan_viewer_wiring.py byte-stable through the face flip.
  Adam confirmations given: ruling-8 platform/panel LOC split ✓;
  VM-naming-vs-abort-matcher deferred to U2.3 dispatch by design.
  KAYA at sign-off: face-flip ruling (architect recommends flip).
- ✅ **noah-bridge DONE, landed `616cec8`** — 42/42 exposures (16 new
  style.py constants, 2 living-glass settings, TOKEN_MAP, C13 guess
  retirement), 300+ tests green across 6 runs, QML compile checks
  clean. **Noah caught a brief bug: my brief said living_glass
  default=off, ratified spec says SUBTLE — spec won (correct).**
  Kaya FYI (may overrule to off). Intentional kit-unification visual
  deltas listed in beat report (ChromeButton primary loses extra
  bold; chip fills unify; crit→error on fault paths). 2 GlassShell
  text sites deliberately NOT retired (would be redesign) → U2
  reference review.
- ✅ **Codex C14 DONE, committed `3669222`** — 34 unmapped files
  enumerated w/ bucket proposals + evidence; 3 proposed for bucket A
  (byte-freeze consequence!) → Mary ratifies before Kiroku executes.
- ✅ **mary-morning DONE: APPROVE ×3** (conftest 9982ce7, P1 2c01e38,
  bridge 616cec8 — 42-count verified against Appendix A, style.py
  additive-proven, subtle-default confirmed against spec+DECISIONS,
  crit→error recolour ruled a hazard-hierarchy STRENGTHENING). 2
  residual NITs tracked: (i) livingGlass*/motionEnabled notify only
  fires on theme toggle — fix when a runtime settings control lands;
  (ii) ALL_42 is hand-maintained — optional introspection guard when
  the kit grows. **Bucket-A ruling: capability_registry +
  device_connect_lifecycle + plan_estimate_cap INTO A; glass_env
  DEMOTED to B** (design-active gui/ policy module — byte-freeze
  would fight kit evolution). C14 otherwise trustworthy.
- ✅ **kiroku-final DONE, landed `101e914`** — 156/156 disk files
  mapped (A52/B28/C65/D11), Mary bucket-A ruling applied (3 in,
  glass_env demoted B), manifest coverage line fixed, checker verified
  parse-based (52 files, PASS). ALL LOCKS RELEASED — no beats in
  flight.
- ✅ MORNING REPORT delivered (Kaya awake midday 07-15).
- 🏛️ **CHECKLIST ③ DONE: kit_spec_v1 SIGNED by Kaya** ("I approve the
  kit spec from the smith") — DECISIONS entry "U1.5 kit spec v1
  signed" logged, spec Status line flipped to RATIFIED (cf52d21).
- 🏛️ **①②④ RESOLVED same session** — DECISIONS entry "U1 CLOSED, U2
  entry gate PAID": measurement B PASS (thresholds ratified unchanged,
  panel-scoped calm ships), Q2=YES (U1 closed, planner tail self-gated
  on AxisSpec), merge-back authorized-on-bench-green.

## 🔥 IN-FLIGHT NOW (U2 day 0, 2026-07-15 ~13:00)

- ✅ **bench full suite GREEN @ bundle cf52d21: 2886 passed, 2
  skipped, 1 xfailed, 625 s** (sophonone; +10 tests vs prior run =
  P1 backfill et al.).
- ✅ **MERGE-BACK EXECUTED: main @ `ee1f476`** (--no-ff merge of
  branch @ bae03e0, PUSHED to origin/main). Done in a throwaway git
  worktree so the working tree never switched branches under the two
  live Noah beats (lesson: never checkout under in-flight locks).
  **U1 IS FORMALLY CLOSED AND ON MAIN.** Branch `ui-qml-migration`
  continues as the U2 working branch.
- ✅ **noah-spike-overlay DONE (harness), landed `7f7af57`** — spike
  built + offscreen smoke PASS exit 0 (hole-rect→island geometry 1:1
  at logical px, no DPR math; zero device imports grep-verified);
  Noah declined the WINDOWED run (his allowlist = tests/offscreen) →
  **numbers PENDING: Adam runs it windowed on a QUIET machine after
  noah-u21 lands** (bare-probe ratified exception, measurement-A
  precedent). Honest caveats on record: gated island_feed_hz = the
  30 Hz drive timer (ScanMapView coalesces paint ~15 Hz by design ⇒
  overlay repaint stress GENTLER than A/B worst case); storm probes
  comparative, not gated. U2.4 design intel already extracted:
  reposition must hang off QML rect-changed via 0-timer (resizeEvent
  alone insufficient); raster-over-texture sibling stacking clean;
  watch for 1-frame island-lag flicker on resize. Optional Kaya
  eyeball: `--hold 25` (seam check on the real 2.5-DPR panel).
- ⚠️ **KAYA OPERATOR OBSERVATION (2026-07-15, eyeball run, NO report
  on disk — likely --hold mode):** "background animations am ruckeln"
  — explicitly NOT the scan plot. Confounds at observation time:
  (1) noah-u21 was mid-beat on the same laptop (machine NOT quiet);
  (2) spike runs living ground at FULL amplitude (worst case; shipped
  default is subtle); (3) the frost bake steps at 12 Hz BY DESIGN —
  content seen through frost updates 12×/s even at 60 fps scene rate.
  DIAGNOSIS PLAN: quiet measured run (Adam, post-U2.1) separates the
  cases — qml_fps ≈60 + still-visible stepping ⇒ bake-cadence
  perceptual question (design item → Baldr/Kaya, cadence ladder is a
  tunable spec parameter); qml_fps low ⇒ real frame drops (perf
  problem, U2.4 gate risk). Do NOT redesign before the numbers.
- ✅ **noah-u21 DONE, landed `1ab0085`** — U2.1 Surface + material
  core, ALL exit criteria green (kit suite 27, contrast check exit 0
  ring-vs-surround all rungs both themes, inline-hex +85/-0 additive,
  MultiEffect budget = exactly 1, combined targeted 88 passed).
  Frozen API for U2.2 in his report (Surface rung enum, KitEnv
  singleton, calm = ONE switch panel-default). 2 reconciliation flags:
  (i) edgeShade needs bridge edgeShadeAlpha for the true gradient
  (legal fallback shipped) → bridge micro-beat, queued; (ii) spec §2.2
  per-rung frost depths (40/16) vs §2.4 one-blur law — shipped ONE
  40px bake both rungs sample; needs an Adam budget ruling → with the
  U2.1–U2.3 Mary batch. Mary: thematic batch U2.1+U2.2+U2.3 (plan §gate
  line 6).
- 🚨 **OVERLAY SPIKE MEASURED (Adam, quiet machine): FAIL — and it
  VALIDATES Kaya's ruckeln observation as REAL.** `9efa5ce` artifacts
  island_overlay_spike_20260715T111751Z: scene 60→23 Hz with raster
  island in same top-level; island feed 30→16 Hz; map repaint ~6 Hz;
  CPU 23→80% one core. CONTROL (frost+ground alone) = clean 60 fps @
  23% ⇒ material innocent, bake cadence innocent; the raster-sibling-
  over-QQuickWidget composition is the killer (mechanism reads as
  full-backing-store recomposition per island tick, GUI-thread
  CPU-bound; storm_suspected=False). **U2.4 host code does NOT start
  on these numbers** (plan's own stop rule).
- ✅ **noah-spike-mitigation DONE, landed `ce46074`** — 9-cell matrix
  (--cells), smoke 9/9; qml_fps probe fixed (afterFrameEnd; frameSwapped
  never fires on the QQuickWidget FBO path); diagnostics
  verdict-prefixed. One API-error mid-flight, resumed from transcript,
  no loss. U2.4 DECISION TABLE in his beat report (this ledger's git
  history): M1/M2 pass ⇒ IslandHost adds opaque flags, architecture
  stands · only combined ⇒ both flag sets hard requirement · only M3
  scales ⇒ blit-area-bound, architect escalation · only M4 recovers ⇒
  island-rate-paced, throttle-or-pivot · M5-only ⇒ render-loop
  follow-up spike · ALL fail ⇒ one-window hole-and-frame not viable on
  this hardware class, design-level pivot (separate windows).
  **NEXT: Adam runs `--cells all` windowed on quiet machine ONCE
  noah-u22 lands** (~6-8 min, 2 passes/cell).
- **noah-u22** (sonnet, background) — U2.2 components (ScanViewer
  subset; independent of island mechanics). LOCKS: gui/qml/kit/*.qml
  NEW component files only (U2.1 files FROZEN) ·
  gui/qml/ScanStatusStrip.qml · tests/test_qml_kit_components.py
  (new) · tests/test_qml_scan_status.py (additive).
- ✅ **BENCH-GATE LFS RISK RESOLVED (Adam, harness infra):**
  bench_run.ps1 gained step [3b] — ships ONLY the LFS objects for
  files under TCT_app/ (32 KB, never the 1.9 GB store) as a tar
  extracted into the bench repo's .git, then `git lfs checkout
  TCT_app` (offline smudge, no credentials) + laptop-side
  pointer-verification that FAILS the sync if any TCT_app LFS file
  stays a pointer. **Proven end-to-end:** -SyncOnly run → "LFS OK: 12
  TCT_app files smudged"; bench PNG byte-size verified 2507 (was a
  129-byte pointer). Two cmd-over-ssh traps documented in the script:
  `if not exist X mkdir X & rest` groups `rest` INTO the if-body;
  bench git-lfs rejects `-- <path>` as a bad ref. Local hygiene:
  `184852e` (.gitattributes -text restated; blobs pointer-clean; LFS
  objects confirmed pushed).
- **After U2.1 lands:** immediate-ish Mary look is NOT required (not
  safety-class) → thematic batch with U2.2+U2.3 per plan §gate line 6;
  U2.2 (components, Noah sonnet) dispatches on U2.1's frozen API.
- **PUSHED:** origin @ cf52d21 before this commit.

## 🌱 NIWASHI CREATED (Kaya-directed, 2026-07-15 night)

New agent seat `.claude/agents/niwashi.md` + CLAUDE.md table row:
read-only structure distiller (Sonnet), TCT_app/** code only, proposes
rot findings + distillation/synthesis proposals with named
test-thermometer; never edits, instruction layer out of scope,
SAFETY-CLASS proposals gated Mary+Kaya. Feeds the ruling-8
distillation-balance gate. First dispatch: at this wave boundary,
after Mamoru returns (avoid duplicate sweeps).

## 🌱 NIWASHI SWEEP 1 DONE — 4 proposals, Adam's routing

- Wave-1 area: CLEAN (no leftover scaffolding, no dead imports — the
  extraction discipline held). Sequencer/DangerGate safety paths read,
  zero SAFETY-CLASS proposals.
- **P1 (synth, risk NONE, net ≈ −60 LOC): standing-law test pair →
  shared helpers** (tests/_viewmodel_standing_law.py), keeps test
  names, **backfills the ScopeViewModel coverage gap** (only VM
  without the pair!). → EXECUTE OVERNIGHT (Noah beat) AFTER
  noah-conftest lands (same suites involved).
- **P2 (distill, LOW, 19 identical 2-line sites in 17 files):
  resolve_theme_mode helper in style.py + the disclosed None-branch
  unit test.** → Codex lane after C14 returns (mechanical, non-safety).
- **P3 (distill, LOW, tiny): _zf_z_data/_zf_a_data shadow copies in
  scan_viewer_panel → read VM directly** (3 test lines edited). →
  morning list (batch with next scan-viewer touch).
- **P4 (rot flag, audit-first): thread-teardown idiom ×21 across 14
  panels; motor_panel documents an ordering-sensitive historical bug —
  NOT batch-mergeable.** → morning list; per-panel, Noah-class, never
  free-lane.

## 🎯 KAYA'S PARTING DIRECTIVE (verbatim intent, before sleep #2)

"Full QML+MVVM+TrueGlassShell am Morgen steht immernoch." Bounded
interpretation ON RECORD (gates are ratified; a stretch goal does not
override them): maximize toward that target WITHOUT crossing [Kaya]
gates, Mary reviews, bench gates, safety rules, or merge-to-main.
Concretely added to the queue: **U2 implementation plan ON PAPER**
(Fable architect, against the staged U1.5 kit spec + Lantern) so the
hero slice can start the minute Kaya's morning gates (measurement B,
U1.5 sign-off) click. Code for U2 is NOT written overnight — the entry
gate is his, and that is exactly what makes the plan trustworthy.

## ✅ U1 STAGING DESIGN LANDED (u1-architect, Fable, this session)

- `docs/design/u1_staging.md` (566 lines, uncommitted until first-beat
  landing review). 5 beats: U1.0 carve-out → wave 1 (U1.1‖U1.2‖U1.3,
  38 reclaims) → boundary (Mamoru+Kiroku+Mary batch) → gate §7 →
  merge-back; U1.4 planner (36) designed but DO-NOT-DISPATCH until
  AxisSpec importable on branch. Placement ruling: flat
  gui/*_viewmodel.py (package would strand the S2-named
  run_state_viewmodel.py). Sequencer split: SequencerQueueViewModel
  (read-only, fed) + panel stays command/safety host. Run-owner seam =
  ruling 7 convention pinned. **OPEN: Q2 to Kaya** (close U1/merge
  back after wave 1, planner tail self-gated later — recommended) ·
  Q3 to Mary at U1.0 review.
- (U1.4 planner: HELD for AxisSpec on branch.)

## ✅ U1.0 LANDED — commit `8166752` ([A-green] PASS re-run over it)

- Pure move verified by implementer byte-compare (host diff 202 del /
  0 ins; 9 signatures identical). New file 9 passed / host 58 passed
  (output tails = verification). Judgment call flagged to Mary: 2 dead
  single-symbol imports (DangerAction, QtDangerGate) removed from host.
  Manifest Q4 row rehosted 5+4=9 with inline Q3 flag; aggregate Counts
  section deliberately NOT recomputed (waits for Mary's Q3 ruling, then
  Kiroku). Bucket-map: new row C-proposed, count 117→118.

## ✅ LANDED THIS SESSION (besides U1 staging design)

- **noah-measb DONE** — measurement-B harness built, offscreen smoke
  PASS exit 0 (sim guard proven: trips on non-sim device, refuses
  headless with exit 3; sim scan + HDF5-to-temp + 30 Hz island + QML
  parse all exercised). `TCT_app/scripts/spike_measurement_b.py` +
  bundle `artifacts_claude/measurement_b_prep_20260715T004557Z/`
  (README = launch instructions). **WINDOWED LIVE RUN = OPERATOR
  (Kaya)**: `cd TCT_app; .venv\Scripts\python.exe
  scripts\spike_measurement_b.py` on the laptop, ~40–55 s, verdict
  block + spike_report.json. NOTE: §7 named assertions but not
  thresholds — harness carries PROPOSED floors (island 28 Hz, qml 55
  fps, retention 0.90/0.80, jitter CV rule) as named constants;
  ratify against the live numbers before treating as the U2 gate.
- **Codex C13 DONE** (free lane, Adam-reviewed) — Theme-gap audit:
  **42 missing Lantern bridge exposures** (evidence table with
  file:line in docs/CODEX_QUEUE.md §C13). U2 cost line: ONE focused
  front-loaded bridge beat (TOKEN_MAP + style.py constants + 2
  app_settings keys + retire QML hardcode guesses) BEFORE the first
  Surface, else the Surface becomes the source of truth. Path note:
  the kit contract is `docs/design/iterations/glasshell-cockpit/
  round-03/kit.md` (qml_kit_forge/kit.md does not exist — brief slip,
  Codex adapted correctly).

## ✅ MARY BATCH DONE (this session): 6452da3 APPROVED_WITH_NITS

- Item 1: stale treatment verified genuinely ink-only (no live
  opacity/blur binding), STALE marker unconditional incl. compact mode,
  ring_vs_own_fill computes the correct own-fill pairing and is clearly
  report-only (no exit code). 3 NITs, no action required. Optional test
  chore (backlog, not queued): assert value-ink swaps to muted + pin
  the literal 'STALE' string.
- Item 2 (Loki routing note): RESOLVED as routing, no hole. **Adam
  ruling 7 (delegated design authority, post-hoc log due in
  DECISIONS.md): run-ownership = the top-level currently hosting the
  ScanViewer/ScanStatusStrip, gated by facade.active — NOT the arming
  panel** (survives Planner-close-mid-run + detached viewer; app is
  single-run by construction so `active` suffices). Sequencer runs stay
  ScanViewer-scoped; future extension seam = read-only run-source
  STRING on the facade, never a controller ref. **Queued spec chore:**
  amend lantern §7 "resolves through run_state_facade only" wording to
  name the ScanViewer-host convention (batch with next spec pass +
  DECISIONS ruling-7 entry). Fallback note: under ruling-1's global-calm
  fallback the whole question is moot.

## ✅ ATTACK-FIX CYCLE CLOSED (2026-07-15, all on `ui-qml-migration`)

- `c11b580` **Brokkr revision** — all six rulings are spec text now.
  Notable: outside-offset ring convention (`focusRingOffsetPx=2`,
  accent-on-accent structurally unreachable, matches QSS
  outline-offset → ONE convention across both shells); zero-cost
  claim RETIRED with measurement B written in as U2 entry gate incl.
  failure fallback (run-active global calm, back to Kaya with
  numbers); kit.md touched in exactly 3 permitted spots; my ruling-5
  location slip corrected (enumeration = lantern §8 + kit.md §7 law 4).
- `6452da3` **Noah fix** — MetricTile stale dim retired (ink-only +
  unconditional STALE marker, covers compact-mode caption gap);
  ring_vs_surround PASS all rungs both themes; ring_vs_own_fill
  report-only (reproduces Baldr's hand numbers exactly, incl. 1.00:1
  accent-on-accent). 13 + 97 targeted green (his output tail = the
  verification, test economy).
- Earlier same session: `2a2cb38` forge · `bb44801` LANTERN + panel-
  scoped calm · `e875571` C12 · `2a5e67e` probe · `4c5de40` spike ·
  `9187d9b` U0 GREEN · `db5f0fe` Loki verdict · `b23bae8` design
  delegation · `cbda3b0` attack reports + six rulings. Mamoru standup:
  ALL 7 CLAIMS VERIFIED.

## 🔁 RESTART HANDOFF (U0 closed, attack cycle closed — U1 is next)

1. **Next beat: U1 staging design** — an architecture beat (**Fable**,
   per the architecture-agents rule). Input: Codex C12 portability map
   (under the C12 brief in docs/CODEX_QUEUE.md): planner 36/67 (waits
   for trunk-P2 AxisSpec — do NOT start planner slice), scan_map 17/32,
   scan_viewer 15/40, sequencer 6/17 (needs read-only queue/run VM +
   retained command/safety host — the one real design question).
   run_state_facade boundary: VM holds no controller ref, no start/stop
   callables. 9-test DangerGate cluster in planner = S2 carve-out,
   untouchable in U1.
2. **Queued at U2 entry: measurement B** (acquisition-headroom spike —
   protocol now written INTO candidate_lantern.md §7 by the revision).
3. **Queued for Mary (thematic batch, non-hazard):** `6452da3`
   (MetricTile + check) + a look at the panel-scoped-calm routing note
   from Loki (facade must resolve WHICH panel owns the run — routing,
   not a hole).
4. **Standing:** design delegation ACTIVE (DECISIONS 2026-07-15) —
   token law + design changes = Adam, post-hoc logging; safety
   carve-outs explicit. Kaya may still overrule the run-active speed
   clamp (Baldr's panel-scope challenge is verbatim in
   attack_baldr.md).
5. Bench-gate constraint (learned at U0): connected session required
   for hardware GL; task `tct_rhi_probe` + `C:\bench\rhi_probe.bat`
   exist and are reusable; TreeMap in bench_run.ps1 covers main +
   ui-qml-migration.

## 🛡️ BALDR VERDICT on LANTERN (2026-07-15): fixable, no redesign

Full audit `docs/design/qml_kit_forge/attack_baldr.md`. Material
system / tier-invariance / chip law: SOUND. Findings → Adam's rulings
1–5 in DECISIONS.md (run-active speed clamp ≤1.0×; stale=ink-only —
MetricTile 0.6 dim is a MEASURED shipped AA failure, crit 2.59 dark /
warn 2.52 light; ring-vs-own-fill check was MISSING, accent-on-accent
1.00–1.37:1; hazard-rung focus = ring always, halo never; dead-zone law
gains 'halo'). His panel-scope challenge (adjacent panels are watched
during the same run) is on record verbatim for Kaya; clamp adopted as
the narrowest fix, ships unless overruled.

## ⚔️ LOKI VERDICT on LANTERN (2026-07-15): REVISE — sound, 2 riders

**"The frost-bake premise survived the attack I most expected to
land"** — O(1) evidence real (fps/island-rate held to 8 panes @ 12 Hz;
the CPU-slope number is noise, don't quote it as a constant). Safety
posture intact. Stability credible. BUT:

- **BLOCKER-1 (spec contradiction CREATED BY the panel-scope
  ratification):** candidate_lantern §3.2/§7 still say "RUNNING → bake
  0 Hz / zero material cost during acquisition (SYNTHESIS §4.3)". With
  panel-scoped calm the room KEEPS FLOWING during a scan ⇒ the shared
  bake CANNOT stop ⇒ that guarantee is silently void — ~0.5 core of
  ground+bake now runs ON TOP of live acquisition on the CPU-bound
  laptop. **Fix = paper reconciliation of §3.2/§7 BEFORE U2** (bake
  runs at idle rate during scans; only the run-owning pane calms).
- **MAJOR-2:** panel-scoped calm mechanism is hand-waved; the only
  O(1)-preserving mechanism is (a) the running pane stops scheduling
  its OWN sampler (stale crop) ⇒ a slow drift seam at the panel edge
  over a 90 s flow period — must be NAMED in the spec; seam
  acceptability = Baldr's call.
- **MAJOR-3 (the REQUIRED follow-up measurement, "measurement B"):**
  the spike had no acquisition load (no DeviceManager/controller/HDF5,
  1 island vs up to 9). Before U2: re-run bake+full ground DURING a
  live SIMULATED scan (sim devices + controller + HDF5 + live scan
  plot) on the laptop; assert plot rate + DAQ cadence.
- MINOR-5: shadow-token family (`shadowInk`, `shadowA..D`) needs
  Kaya's explicit token-law nod — NOT covered by "DO LANTERN".
- MINOR-6: the Theme bridge is ~40 unbuilt token exposures — a real
  front-loaded cost line before U2's first Surface, not a footnote.
- MINOR-7: accelerated-RDP edge passes `_scene_capable`'s tier gate
  (low priority, bench used connected).
- Note for Mary (routing, not a hole): the facade must resolve WHICH
  panel owns the run for panel-scoped calm.
- Cost honesty for the U2 plan: **~3× a naive port across U2–U6**,
  breaking even after U6 — carry that number, not "one glass instead
  of sixteen" (that's the steady state).

**Fix path (after Baldr lands, ONE Brokkr revision pass batches both
attack results):** reconcile §3.2/§7 + name mechanism (a) + shadow-nod
question to Kaya. Measurement B queued as U2-entry requirement (not a
U1 blocker — U1 is viewmodels, paint-free).

- ✅ LANDED **noah-frost-spike** `4c5de40`: **🎯 PASS on ALL 4 criteria —
  Lantern's entry ticket is PAID.** Worst-case Intel UHD iGPU, single
  process WITH a live 30 Hz pyqtgraph island: CPU slope **0.89–1.37
  pp/pane** (criterion <2; live per-pane blur was +13), QML 60 fps every
  cell, island 30.3 Hz every cell, 20/20 stable at 8 panes/12 Hz.
  Mechanism: `layer.live:false` + timed `scheduleUpdate()` = ONE blur
  pass; panes are crop-blit `ShaderEffectSource` samplers; bakeCount
  telemetry confirmed commanded bake rates. Honest caveats (report:
  `artifacts_claude/lantern_frost_spike_20260714T233707Z/`): single 10 s
  sample per cell (cell noise ≈ effect size; fit clears anyway), no
  pixel-correctness diff (`--hold` eyeball mode exists, unexercised),
  iGPU only, auto-calm/full-amplitude/reduced-motion untested. **Loki
  gets these numbers for the attack pass.**
- ✅ LANDED **noah-u0-probe** `2a5e67e`: local smoke PASS exit 0
  (GL_RENDERER='Intel(R) UHD Graphics'; --expect mismatch correctly
  exits 2). Teardown deadlock found+fixed (message handler restored
  pre-quit; render-thread log vs GIL at join) + out-of-process hard
  watchdog — the probe cannot hang a gate. Bench RUN still open ↓.
- ✅ LANDED **brokkr-u15-kit** (Fable): THREE candidates in
  `docs/design/qml_kit_forge/` — **TWIN** (QML as second renderer of the
  ratified panel_kit contract; parity is the feature; zero blur) ·
  **LANTERN** (one `Surface` material: rung + baked position-sampled
  frost + edge ladder + springs; living ground as foundation) ·
  **LEDGER** (machine-readable `(role,state)→paint/motion` table with
  LOCKED safety rows; components are projections; self-auditing).
  Differentiation axis: where design authority lives (shipped QWidget
  contract / scene material / data contract). Attack pass targets are
  pre-mapped in `00_comparison.md` §3 (Loki: Lantern's unspiked frost
  bake — demand a bench-iGPU spike before U2; Baldr: calm-on-RUNNING as
  run-state side channel, focus-ring contrast on composited fills).
  Cross-candidate FACTS regardless of pick: `gui/qml_theme.py` TOKEN_MAP
  is missing danger_fill/on_danger/error/chip/edge/pressed/radius/font-
  role tokens + a motionEnabled bridge (shipped QML already guesses,
  e.g. Font.DemiBold in MetricTile.qml); all three amend kit.md §1.2 to
  "auto-calms to static during a run" per Kaya's living-glass directive
  (flagged in each candidate — needs his nod at the [Kaya] gate);
  washes move POSITION never alpha ⇒ tint ≤0.07 holds per frame (what
  makes living glass legal); glass_env's tier ladder already gates the
  shader path (software/RDP cap at TOKEN). Open questions for Kaya
  listed in 00_comparison. Loki+Baldr attack pass: QUEUED (after U0
  lands — migration mechanics stay the priority).
- ✅ LANDED **Codex C12** `e875571` (verification real: 156 collected,
  full offscreen run 156 passed / 72 s): planner **36/67**
  VM-reclaimable (9-test DangerGate cluster = hard S2 carve-out) ·
  scan_map **17/32** · scan_viewer **15/40** · sequencer only **6/17**
  (panel holds a live SequenceCoordinator + command callables ⇒ U1
  needs a read-only queue/run VM + retained command/safety host, not a
  direct port). Zero QTest key/mouse synthesis in all four suites —
  couplings are structural. Full tables under the C12 brief in
  `docs/CODEX_QUEUE.md`. (Protocol note kept: codex lane = queue-file
  briefs only; bridge watcher was DEAD 85865 s, restarted this session.)

## 🟢 U0 COMPLETE — GATE EVIDENCE (masterplan format)

- **gate-id:** U0 (branch cut + RHI/GL pin probe) · **commit reviewed:**
  probe `2a5e67e` on `ui-qml-migration` (cut at main `cf6dd58`,
  polish-freeze ancestor verified) · **verdict:** PASS ·
  **date:** 2026-07-15.
- **Run 3 (RDP-connected session, task tct_rhi_probe): PASS exit 0 —
  QSG_RHI_BACKEND='opengl' · graphicsApi='OpenGL' ·
  GL_RENDERER='NVIDIA GeForce RTX 5080/PCIe/SSE2' · 0 software-fallback
  markers across 454 lines · --expect 5080 FOUND.**
- **Artifact:** `artifacts_claude/u0_rhi_probe_20260715/
  rhi_probe_u0_bench_log.txt` (full 504-line capture, verdict block at
  top; committed with this ledger).
- **Standing bench-gate constraints learned by runs 1–3 (re-assert at
  every per-stage [Bench] per masterplan):** ssh = session 0 = llvmpipe;
  disconnected session = Qt opengl32sw fallback; **RDP-CONNECTED session
  = real hardware GL on this driver (610.47)** — so gates need a
  connected session, physical console NOT required. Run mechanism:
  task `tct_rhi_probe` (interactive, Kaya-created), bat at
  `C:\bench\rhi_probe.bat`, logs at `C:\bench\rhi_probe_u0*.log`.

## (superseded) run-2 finding — kept for the record

- Kaya created+ran the interactive task himself (schtasks output
  ERFOLGREICH ×2). **Run 2 result: frame RENDERED (progress vs ssh) but
  renderer = llvmpipe again — this time via Qt's bundled software
  fallback `opengl32sw.dll` (fingerprint: Gallium 0.4 llvmpipe,
  Mesa 11.2.2, LLVM 3.6). RC=2, probe FAILED correctly.**
- Root cause CONFIRMED by paired checks: session 3 is DISCONNECTED
  (quser: "Getr.", 12 h idle) while the GPU is healthy (nvidia-smi:
  RTX 5080, driver 610.47). A disconnected session gets no hardware GL
  context from the NVIDIA ICD; Qt silently swaps in opengl32sw.
- **U-track consequence (a REAL U0 find, exactly what the gate is
  for): every per-stage bench QML gate silently tests SOFTWARE
  rendering unless the bench session is CONNECTED** (RDP attached or
  physical console). Booked for the masterplan's per-stage [Bench]
  threshold note. If even a connected RDP session caps GL (classic RDP
  driver behavior; modern NVIDIA may allow it), the fallback options
  are physical-console gates or a re-ratified D3D11 criterion — decide
  on evidence when Kaya connects.
- NEXT: Kaya RDPs into sophonone (or logs in at the console) → re-run
  `tct_rhi_probe` → poll logs. Expected PASS only with a connected
  session.

## (superseded) U0b first block — schtasks permission (RESOLVED by Kaya running it himself)

- Branch synced to bench @ `2a5e67e` (`bench_run.ps1 -SyncOnly`;
  TreeMap extended: main + ui-qml-migration → C:\bench\project_tct).
- **Plain-SSH attempt measured and documented (the probe FAILED
  correctly):** ssh lands in session 0 (no desktop) ⇒ Qt fell back to
  llvmpipe (Gallium/VMware line), 0 frames, watchdog fired. Log:
  `C:\bench\rhi_probe_u0.log` on the bench. Transport artifact, NOT a
  GPU verdict — the RTX 5080 lives in the interactive session.
- Correct path = the ratified detached one (interactive schtasks like
  tct_gate; Anmeldemodus "Nur interaktiv" confirmed on tct_gate; bat
  already SHIPPED to `C:\bench\rhi_probe.bat`), but **`schtasks /create`
  over ssh is DENIED by the permission classifier** (twice, incl. as a
  single command). Adam stopped per denial protocol. Kaya options:
  1. Run once from any shell:
     `ssh Administrator@100.119.126.9 "schtasks /create /tn
     tct_rhi_probe /tr C:\bench\rhi_probe.bat /sc once /st 23:58 /it /f
     & schtasks /run /tn tct_rhi_probe"` — then Adam polls
     `C:\bench\rhi_probe_u0_stdout.log` + `rhi_probe_u0.log`.
  2. Add a permission rule allowing schtasks-over-ssh to the bench.
  3. Run `C:\bench\rhi_probe.bat` directly at the bench console.
  Expected PASS: GL_RENDERER contains "5080", zero fallback markers,
  exit 0 — that log completes U0 and releases the branch push.

## NEXT (queue)

1. U0b: bench probe run → log artifact → link here → commit probe script
   and ledger → push `ui-qml-migration`.
2. U1 viewmodel-first test reclaim (C→B) — planner slice WAITS for
   trunk-P2 (AxisSpec); other slices are P-track-independent. Needs a
   staging design: dispatch order per masterplan U1 list.
3. Brokkr candidates land → Loki + Baldr attack pass → council round →
   [Kaya] gate on the kit spec (U1.5, after U1 formally).
4. Standing gate every U-stage: [A-green] + S2 normative suites + [Bench]
   before merge-back + per-panel TCT_SHELL=qml offscreen smoke.

## ⚠️ STANDING RULES CARRIED FORWARD

- Instruments may be physically cabled ⇒ agents never run the APP
  locally; targeted headless pytest only; bare no-device-import probe
  scripts (spike class) are the ratified exception. Safety rule 6.
- `TCT_app/configs/devices.yaml`: if it goes dirty, NEVER stage it.
- Test economy binding · bench full suites only at gates, one at a time ·
  session hygiene 1–4 · free lanes never idle · review-then-push.
- NEVER migrates to QML (ratified): QtDangerGate modal, 9 pyqtgraph/GL
  islands, camera raster QLabel, STOP/ALL-OFF/Abort QWidgets, any second
  implementation of a safety control.
- TECH_DEBT :185-188 — freeze-family riders + the deferred glass bug
  (post-migration; U6 deletes the backdrop/activation plumbing).

## HEAD / TRUTH

- Working branch: `ui-qml-migration` @ `101e914` == origin (pushed;
  ratification commit for checklist ③ lands on top). Cut from main
  `cf6dd58`. Mamoru wave-1 standup: PASS all 5 tasks.
- Tag `polish-freeze` → `45781fa` (annotated; U-track entry gate + seed
  baseline ancestor).
