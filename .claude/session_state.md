# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit; stage explicit paths; never `-am`.

**Updated: 2026-07-15 — MIGRATION EPOCH OPENED (U-track). The polish epoch
is closed and fully pushed; its record lives in git history of this file
(`git show cf6dd58:.claude/session_state.md`) — not replayed here.**

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

## 🔥 IN-FLIGHT BEATS (locks)

- **noah-frost-spike** (ui-ux-dev instance #2, Sonnet): the LANTERN
  frost-bake spike — bake-once-sample-N mechanism, matrix N∈{2,4,8} ×
  re-bake∈{6,12} Hz + AMBIENT baseline + 30 Hz pyqtgraph island, on the
  laptop iGPU (worst case, deliberate). Verdict criteria: O(1)-in-N
  slope <2pp/pane · QML ≥55 fps · island ≥28 Hz · 0 crashes/20
  launches. LOCKS: `TCT_app/scripts/spikes/lantern_frost_bake_spike.py`
  and `artifacts_claude/lantern_frost_spike_*/`.
- **noah-u0-probe** (ui-ux-dev, Sonnet): U0b RHI/GL pin probe script.
  LOCKS: `TCT_app/scripts/rhi_gl_probe.py` (verified free before
  dispatch). Then Adam runs it on the bench (sophonone, reachability
  verified "up" this session) with `--expect` = bench GPU (RTX 5080);
  pass = opengl backend + GL_RENDERER match + zero software-fallback
  lines; probe log linked here (masterplan U0 pass criterion).
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
- **Codex lane (Kaya's ask, 2026-07-15): task C12** in
  `docs/CODEX_QUEUE.md` — U1 prep survey: classify every test in the four
  U1 target suites (planner_panel / scan_map_view / scan_viewer_panel /
  sequencer_panel) as VM-portable / GUI-half / safety-normative /
  obsolete + name the blocking couplings. Read-only; findings append to
  the queue file. Enqueued as a short pointer (inline briefs bounce on
  the codex lane — harness warned, first enqueue deleted from outbox and
  redone per queue-file protocol). Bridge watcher was DEAD (85865 s
  stale heartbeat); restarted this session, runs in background. Reports
  land in `C:\Users\nukei\Desktop\agent_env\inbox`. LOCKS (soft):
  `docs/CODEX_QUEUE.md` appends.

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

- Working branch: `ui-qml-migration` @ `cf6dd58` (== main == origin/main).
- Tag `polish-freeze` → `45781fa` (annotated; U-track entry gate + seed
  baseline ancestor).
