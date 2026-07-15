# LOKI ATTACK PASS — candidate LANTERN (ratified 2026-07-15)

*Transcribed by Adam from Loki's report (Loki is read-only); content verbatim.*

**verdict:** `REVISE — sound with 2 riders; needs a spec reconciliation + one
measurement before U2 commits.` The frost-bake premise survived the attack I
most expected to land. But the ratified **panel-scoped calm refinement
contradicts the load-bearing perf claim in the spec it was bolted onto**, and
the spike measured a world that no longer describes acquisition. Both are
paper/one-spike fixes, not a kill. Lantern stands.

## findings (ranked)

**BLOCKER-1 — The spec's acquisition perf guarantee is now false, and
unreconciled with the ratification it carries.**
`candidate_lantern.md` §3.2 states re-bake cadence *"scan RUNNING → 0 Hz (§7)"*
and §7 states *"RUNNING → … the bake freezes … zero material cost during
acquisition, SYNTHESIS §4.3 honored by the same mechanism."* Both describe
**global** calm. But Kaya's ratified refinement (`DECISIONS.md` 2026-07-15;
`kit.md` §1.2, amended today) is **panel-scoped**: the rest of the room keeps
flowing during a run. So during a scan the single shared ground keeps animating
everywhere except one region → the one shared `MultiEffect` bake **cannot** be
at 0 Hz; it must keep baking at 6–12 Hz to render the flowing room.
Concrete failure: U2 implements §7 verbatim → the whole cockpit freezes on
RUNNING, contradicting Kaya's explicit "the rest keeps flowing." OR U2 keeps
the bake running (correct per §1.2) → the "zero material cost during
acquisition / SYNTHESIS §4.3 honored" guarantee is silently void, and a
standing ~0.5-core ground+bake cost (baseline 53.54% of one core with the
ground alone) now runs *on top of a live scan* on the CPU-bound i7-10510U.
**Fix before U2: rewrite §3.2/§7 to the true behavior (bake runs at the idle
rate during a scan; only the run-owning pane calms) — paper, zero code, but it
must precede the U2 architecture commit.**

**MAJOR-2 — Panel-scoped calm's actual mechanism is hand-waved, and the only
cheap way to express it introduces an unmeasured seam.**
In the bake-once architecture (§3.2: one ground, one bake, N crop-samplers of
one shared texture), stilling *one region while the rest flows* is expressible
only two ways: (a) the running pane stops calling `scheduleUpdate()` on its own
`ShaderEffectSource`, holding a stale crop — cheap, O(1)-preserving, but the
frozen crop is a snapshot of the ground at T₀ while the surrounding live ground
drifts up to ~8% of the viewport over `groundFlowPeriodS` (90 s), producing a
phase/seam discontinuity at the running panel's edge that grows over the run;
or (b) give the running panel its own frozen ground+bake layer — which
reintroduces the per-pane bake cost the architecture forbids (§10;
`GLASS_LIVE_PANE_BUDGET = 1`). The spec names neither. The spike has **no
pixel diff** (`bakeCount` proves the bake *fires*, not that the crop is
correctly positioned or that the freeze-seam is acceptable). Name mechanism
(a) in the spec; the seam is Baldr's visual call.

**MAJOR-3 — The spike is a GUI-only microbenchmark with a spare CPU; the real
acquisition load was entirely absent, and the island count was 1 (app has up
to 9).** During a real scan the CPU-bound laptop is *also* polling devices,
sequencing the scan, and writing HDF5 — and per BLOCKER-1 the 6–12 Hz bake now
runs *through* that. Required follow-up ("measurement B"): 6–12 Hz bake +
living ground = `full`, running *during a live simulated scan* (sim
`DeviceManager` + scan controller + HDF5 writer + scan-plot island live), on
the CPU-bound laptop. Assert the scan plot holds rate and DAQ cadence doesn't
jitter.

**MAJOR-4 — The (a) CPU-slope PASS is within noise; the O(1) claim rests on
(b)/(c), not (a).** Baseline (0 panes, no bake) = 53.54%; `panes2_hz6` =
47.63% — lower than baseline; scatter (~6–8 pp) exceeds the fitted slope
(0.89–1.37 pp/pane), single 10 s sample, n=3 per fit. Do not quote
"1.366 pp/pane" as a measured constant. The fps/island-rate evidence is what
demonstrates the O(1) architecture (see concessions).

**MINOR-5 — Lantern mints a token family (shadow ladder) the ratification did
not approve.** [RESOLVED 2026-07-15: Kaya delegated token law to Adam; Adam
approved the shadow family — DECISIONS.md.]

**MINOR-6 — The Theme bridge Lantern stands on is ~40 unbuilt exposures, not a
footnote.** `qml_theme.py` TOKEN_MAP exposes ~28 colour tokens; Lantern needs
`pressed`, `disabled_bg`, `edge`, `edge_shade`, `chip`, `on_danger`,
`on_armed`, `danger_fill`, `plotBg`, `radiusXl/Shelf`, `motionEnabled`, glass
alphas, font/weight roles, plus the minted `blurPane/Card/Overlay`,
`frostRebakeHzSubtle/Full`, `focusHaloAlpha`, `groundFlowPeriodS`, shadow
ladder. Front-loaded, uncapped work before U2's first `Surface` renders —
belongs in the cost line.

**MINOR-7 — One RDP path the tier system doesn't catch.** `_scene_capable`
refuses SCENE on software rasterizers and non-opengl Windows RHI, but a
GPU-passthrough RDP session reporting `opengl` passes the gate and would run
the bake over the wire at unmeasured throughput. Low priority.

**Note for Mary (routing, not a safety hole):** panel-scoped calm needs the
run_state facade to resolve *which* panel owns the run.

## conceded (what survived)

- **The frost-bake O(1)-in-panes premise SURVIVED.** min_qml_fps = 59.98 and
  min_island_hz = 30.31 held across every cell up to 8 panes @ 12 Hz — the
  framerate evidence demonstrates the bake gates on the timer, not pane count.
  bakeCount telemetry confirms exact timer rates. This is the single result
  the round needed, and it is real.
- RHI mismatch — withdrawn (app pins OpenGL too; `qml_shell.py:78`,
  `glass_env.py:52`).
- RDP/software demo-machine failure — handled by construction
  (`_scene_capable` caps at TOKEN), except MINOR-7's edge.
- Wash period 7–11 s vs 90 s — perf-neutral (bake cost fixed by timer);
  shorter period is the harder case. Conceded.
- Stability: 20/20 clean cold launches at the busiest cell, credible
  (MultiEffect is built-in C++, no Python scene-graph items).
- Safety posture: hazard-as-dead-zone-by-construction, tier-independent hazard
  channels, island dead-zone assertion, facade-only run-state reads — none
  weakened.

## required before U2

- **(A) Paper reconciliation** of §3.2/§7 (bake at idle rate during scans;
  only the run-owning pane freezes its own sampler; mechanism (a) named).
- **(B) Acquisition-headroom spike** (see MAJOR-3).

Nice-to-have (not U2 blockers): (C) 2–3 simultaneous live islands; (D) one
screenshot pixel-diff (crop correctness + freeze-seam); (E) a second host.

## cost_reality_check (two-shell across U2–U6)

"One implementation of glass instead of sixteen" is the U6+ steady-state
number. During U2–U6: ~40-exposure Theme bridge front-loaded; a new material
runtime raising Mary's review floor per migrated panel; every theme/token
change verified in both shells until U6; two screenshot sets per panel;
which-shell bug-triage ambiguity. Honest booking: **~3× a naive QWidget→QML
port across the U-window, breaking even only after U6 closes.** The ratified
trade — but the U2 plan carries the 3× number.
