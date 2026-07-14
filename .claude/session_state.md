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

(none — every dispatched beat landed; agents are DEAD, do not
SendMessage them. Landed this session on `ui-qml-migration`:
`2a2cb38` forge · `bb44801` LANTERN ratification + panel-scoped
auto-calm · `e875571` Codex C12 · `2a5e67e` U0 probe script ·
`4c5de40` frost-bake spike.)

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

## 🔴 U0b BENCH RUN — RUN 2 FINDING (disconnected session ⇒ software GL)

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

- Working branch: `ui-qml-migration` @ `cf6dd58` (== main == origin/main).
- Tag `polish-freeze` → `45781fa` (annotated; U-track entry gate + seed
  baseline ancestor).
