# Scan Viewer design review — stress-test before build

*Author: Prometheus (researcher / first-officer). Date: 2026-07-08.
Repo-grounded design review, no external sources. Confidence: repo-primary
(every claim carries a `file:line`); no manufacturer manual needed.*

**Exact question (from Adam):** before retiring `ScanPanel` and building a new
`ScanViewerPanel`, stress-test three user-approved decisions — (1) Planner as the
only scan config/start surface, (2) a separate live `ScanViewerPanel` kept apart
from `AnalysisPanel`, (3) signal glue migrating to a `scan_coordinator`
extraction — and surface capability gaps, open questions, re-wiring risks, and a
build order.

Design under test: `docs/design/cockpit_style_overhaul.md` §1 rules 2/3/5/8 and
Phase 2; companion `docs/design/gui_architecture_plan.md` §3.

---

## a. Verdict per decision

**Decision 1 — Planner is the only config/start surface: ENDORSE with two hard
caveats.** The Planner + `plan_from_config.py` demonstrably reproduce the
quick-raster and voltage-scan the retired form emitted (parity proven by the
converters, `controller/plan_from_config.py:110-225`). But "*only* surface" is
literally false in the current tree and cannot be made true by deleting
`ScanPanel` alone — two live start paths survive it (§b gaps G1, G2), and one
scan kind (Z-focus) has no plan representation at all (§b gap G4). Reframe the
decision as: *retire the ScanPanel widget and the quick-raster `ScanConfig`
start path; the Planner is the only surface for grid/CCE routines* — not "every
run goes through `start_plan`".

**Decision 2 — separate ScanViewerPanel, kept apart from AnalysisPanel:
STRONGLY ENDORSE.** Every stated rationale is repo-true: different data sources
(live `ScanResult` stream accumulated in a dict, `scan_panel.py:263-270`, vs
`AnalysisPanel._load_h5` from an HDF5 file, `analysis_panel.py:222-232`); danger
isolation (Abort is a `dangerBtn`, `scan_panel.py:162-166`, rule 2 forbids it
next to a file browser); hot-path perf (live map repaints per point, rule 3); and
detach (rule 8). The "one shared 2D map widget" clause is the load-bearing part:
there are **three** near-identical map renderers today —
`ScanPanel._redraw_map` (`scan_panel.py:478-488`),
`ScanMapWindow._redraw` (`scan_map_window.py:186-230`),
`AnalysisPanel._replot_map` (`analysis_panel.py:238-280`) — all assembling the
same `xs/ys/arr` grid with subtly different NaN handling. Build the shared widget
first; it de-risks the viewer and pays down real duplication.

**Decision 3 — glue moves to a `scan_coordinator`: ENDORSE, and sequence it
*before* the viewer wiring, not after.** `gui_architecture_plan.md:53-60` already
scopes `gui/scan_coordinator.py` to own `_start_scan` / `_start_z_focus` /
`_start_voltage_scan` / `_on_scan_finished`/`_error` / pause-resume + run-state
gating. Rule 5 (`cockpit_style_overhaul.md:43-47`) forbids growing `tct_gui.py`
with logic. The retirement is a net *shrink* of `tct_gui` (removes the
`_scan_panel` wiring, `tct_gui.py:321-372`), and the `_plan_run_active` dual
dispatch (`tct_gui.py:340-347`, `1117-1145`) collapses when a single viewer
receives *all* runs — but only if the new wiring lands in the coordinator. If the
viewer is wired inline "for now", the God-object grows exactly where the plan
says it must not.

---

## b. Capability gaps: ScanPanel → Planner/Viewer (with evidence)

| # | Capability (ScanPanel) | Evidence | Lands where? | Gap |
|---|---|---|---|---|
| G1 | Voltage-scan **ramp shaping** (`ramp_step_V=5.0`, `ramp_delay_s=0.1`) | `scan_controller.py:108-109`; converter drops both | Planner BIAS_V loop | **Real loss.** `plan_from_config.py:50-54` states the plan model has *no* per-BiasStep ramp-shaping field; `BiasStep` carries `target_V` only. Retiring the vscan entry removes per-run control of HV ramp rate. HV-safety relevant — route to Paul. |
| G2 | Voltage scan also starts from the **bias panel** | `bias_panel.py:171,567`; `multi_bias_panel.py:42,98`; wired `tct_gui.py:358` | independent of ScanPanel | **Contradicts "only surface".** Deleting ScanPanel does not remove this path. Adam must decide: retire the bias-panel vscan button too, or redirect it to build a plan. |
| G3 | Motor **"Set as Scan Start"** → captures (x,y,z) into the raster origin | `motor_panel.py:119,801-806` → sole consumer `scan_panel.set_start_position` (`tct_gui.py:361-363`, `scan_panel.py:305-309`) | — (no obvious Planner home) | **Orphaned signal.** A plan has no single "start position"; it has per-axis loop start/stop. Needs a decision: drop it, or add a Planner affordance ("set selected loop start = current position"). |
| G4 | **Z-focus** assist (mode, edge/amp params, live Z-vs-amp curve, best-Z) | `scan_panel.py:182-254,311-328`; controller entry `start_z_focus_scan` (`scan_controller.py:440`) | Viewer CheckableCard | Z-focus is **not** expressible as a `ScanPlan` (no z-focus/reduce execution; `LoopBlock.reduce` is "represented, not executed", `scan_plan.py:133`). So its mini-form must live somewhere. Design says viewer. But best-Z formerly wrote back into the raster `spin_z` (`scan_panel.py:328`) — that destination no longer exists (see Q4). |
| G5 | **Live export** of the map (PNG/CSV) during/after a run | only in `ScanMapWindow._export_png/_csv` (`scan_map_window.py:232-267`) + AnalysisPanel | Viewer FigureCard header? | If ScanMapWindow is dropped without folding export into the viewer, live export is a **regression**. |
| G6 | **Param persistence** (JSON, 9 scalars) | `scan_panel.py:415-455` | Planner Save/Load Routine (YAML full plan, `planner_panel.py:424-427`) | Superseded but **format-incompatible**: old `*.json` param files won't load into the Planner. Migrate or drop (Q1). |
| G7 | Quick-raster form + live ETA | `scan_panel.py:55-104,391-413` | Planner loops + `estimate_plan` "Est. runtime" (`planner_panel.py:499-509`) | **Covered, arguably better.** No action. |

**Feasibility confirmation (the viewer's core is buildable):** a *plan* run fires
the exact callbacks the viewer needs — `on_point_done(ScanResult)` on every
SaveStep and `on_progress(saved, total)` (`scan_controller.py:929-932`), with the
`ScanResult.point` taken from live motor position (`:917-919`). So one viewer can
render the live map + progress/ETA for both classic and plan runs. Note that
today `on_point_done` is wired *unconditionally* to `scan_panel`
(`tct_gui.py:321`) while planner progress is `_plan_run_active`-gated
(`tct_gui.py:340-342`) and the planner panel renders **no** live map — meaning a
plan run's live map currently surfaces on the *retired* ScanPanel. Repointing all
run signals to one viewer removes that split.

---

## c. Open questions Adam must answer before build

- **Q1 — param persistence home.** Drop the JSON param format, or add a one-shot
  importer that converts old `*.json` → a plan? Routine YAML (`planner_panel`
  Save/Load) subsumes it going forward.
- **Q2 — fate of `scan_map_window.py`.** It overlaps the viewer's live FigureCard
  heavily, but uniquely offers a map-only big pop-out with manual levels +
  PNG/CSV export (`scan_map_window.py:100-113,232-267`). Options: (a) delete and
  rely on rule-8 detach of the whole viewer (loses map-only export unless folded
  into the viewer, see G5); (b) keep it as the viewer's detached map form,
  rebuilt on the shared map widget. Recommend (b)-lite: rebuild on the shared
  widget, fold export into the viewer header, keep the pop-out only if operators
  actually want a map-only window.
- **Q3 — viewer with no run: EmptyState + persistence.** Show `EmptyState`
  ("No run in progress — configure and start a routine in the Scan Planner")
  until a run starts (kit component per `cockpit_style_overhaul.md:81`). Decide
  whether the *last finished* run's map stays on screen after `on_finished`
  (needed so "Open in Analysis" has something to hand off) or clears immediately.
  Recommend: persist until the next run starts or the user clears.
- **Q4 — best-Z destination.** With no raster `spin_z`, where does a found focus
  go? Options: readout-only; inject into the Planner's STAGE_Z loop; or move the
  motor to best-Z. Must be decided with G4.
- **Q5 — Z-focus: viewer vs motor panel.** Viewer is defensible (it's a live
  acquisition run with its own plot, and the viewer already owns pause/abort). But
  it makes the viewer a *start* surface for one scan kind, softening Decision 1.
  Motor panel is the alternative (z-focus is alignment). Recommend viewer, but
  resolve Q4 in the same decision.
- **Q6 — "Open in Analysis" seams (two missing).** (i) `AnalysisPanel` has **no**
  public load method — only `_open_file` via dialog (`analysis_panel.py:197-220`);
  add `load_run(path)` and have `_open_file` call it. (ii) The viewer must learn
  the just-written HDF5 path — `ScanController._begin_run/_end_run`
  (`scan_controller.py:229-247`) create the run dir but `on_finished` carries no
  path. Add an `on_run_saved(path)` callback or a `last_run_path` accessor.

---

## d. Re-wiring risks in `tct_gui` w.r.t. rule 5 (composition root)

- **R1 — inline wiring grows the God-object.** `_build_central` is already
  ~200 lines and holds `if`-bearing handlers the plan wants out
  (`_on_plan_maybe_finished` `:1117`, `_on_plan_manual_pause` `:1133`). Viewer
  gating + z-focus + open-in-analysis + run-path plumbing must land in
  `scan_coordinator`, not here. Pure `x.signal.connect(y.slot)` may stay in the
  root; anything with a branch may not (`gui_architecture_plan.md:53-70`).
- **R2 — theme caching.** The viewer caches pyqtgraph pens/axis colors, so it
  must implement `refresh_theme(mode)` and be added to the `_toggle_theme` panel
  loop (`tct_gui.py:592-600`). ScanPanel is *not* in that loop today (it uses
  default pens); the viewer must be (rule 4, `cockpit_style_overhaul.md:38-42`).
- **R3 — teardown.** Keep the viewer thread-free (it only consumes queued bridge
  signals). If it stays thread-free it needs no `shutdown()`; if it ever grows a
  timer/thread it must join `_teardown_panels` (`tct_gui.py:802-808`). Prefer
  thread-free.
- **R4 — abort reachability while detached (rule 8).** Abort lives in the
  viewer's ActionBar, so it travels with a detached window — good. Two edge cases:
  (i) the danger-confirm dialog is parented to the **main** window
  (`tct_gui.py:243`, `qt_danger_gate.py:135-153`), so an HV-ramp confirm during a
  plan pops on monitor 1 while the operator watches the viewer on monitor 2 —
  minor safety/UX smell; consider parenting confirms to the active run surface.
  (ii) Closing the detached viewer mid-run must **re-dock** (rule 8), not destroy
  the panel or drop bridge connections — verify `DetachableTabWidget` re-parents
  rather than deletes, and that the viewer's close/detach path never calls
  `abort()`.
- **R5 — signal repoint is safe but must be complete.** `_ScanBridge`
  connections to `_scan_panel` (`tct_gui.py:321-322,368-369`) repoint to the
  viewer; the motor `set_as_scan_start` (G3) and bias-panel `vscan_requested`
  (G2) must be redirected/resolved in the *same* patch or they dangle.

---

## e. Recommended build order

1. **Kit prerequisites (Phase 0, blocking):** `FigureCard`, `MetricTile`/
   `MetricGrid`, `ActionBar`, `CheckableCard`, `EmptyState` in `panel_kit.py`
   with headless construct + theme-switch smoke tests
   (`cockpit_style_overhaul.md:93-95`).
2. **Shared 2D map widget:** extract the one renderer from the three duplicates
   (§a) into the kit; unit-test headless. De-risks steps 5–6.
3. **Non-UI seams for the handoff (small, testable):** (a)
   `AnalysisPanel.load_run(path)`; (b) a run-path signal/accessor on
   `ScanController`. No widgets — safe, reviewable alone (Q6).
4. **Extract `gui/scan_coordinator.py`** *while ScanPanel still exists* — a
   behavior-preserving move of the existing scan glue + `_plan_run_active`
   gating out of `tct_gui`. App stays runnable; review by Mary
   (`gui_architecture_plan.md:53-60,72-73`).
5. **Build `ScanViewerPanel`** on the shared widget: live map FigureCard,
   MetricGrid progress/ETA, ActionBar with loud Abort (rule 2), Z-focus
   CheckableCard, EmptyState (Q3), "Open in Analysis". Add `refresh_theme`. Tests:
   headless construct, theme switch, and a rule-8 detach/re-dock regression.
   Wire through the coordinator (R1).
6. **Retire ScanPanel** only after G2/G3 are resolved and the run signals are
   repointed (R5): remove the tab + `_scan_panel` wiring, decide `scan_map_window`
   (Q2). Have Kiroku update `docs/ARCHITECTURE.md`.
7. **Close the parity gaps per Adam's answers:** best-Z destination (Q4/G4),
   bias ramp-shaping (G1 → Paul), bias-panel vscan redirect (G2), param-file
   migration (G6/Q1), live export (G5).

---

## Sources (repo-primary; `file:line`)

- `docs/design/cockpit_style_overhaul.md` §1 rules 2/3/5/8, Phase 2 (lines 24-65, 109-132)
- `docs/design/gui_architecture_plan.md` §3 (lines 44-73)
- `TCT_app/gui/scan_panel.py` (36-43, 162-166, 263-328, 391-455, 478-488)
- `TCT_app/gui/planner_panel.py` (335-362, 424-427, 499-544)
- `TCT_app/controller/scan_plan.py` (117-171 `LoopBlock`, 133 `reduce`)
- `TCT_app/controller/plan_from_config.py` (24-55, 110-225)
- `TCT_app/controller/scan_controller.py` (40-153 configs/ScanResult, 229-247, 440, 837-1002 `_run_plan`, 917-932 callbacks)
- `TCT_app/tct_gui.py` (242-243, 321-372, 358, 592-600, 802-808, 1070-1145)
- `TCT_app/gui/scan_map_window.py` (100-113, 186-267)
- `TCT_app/gui/analysis_panel.py` (197-232, 238-280)
- `TCT_app/gui/qt_danger_gate.py` (135-153)
- `TCT_app/gui/motor_panel.py` (119, 801-806); `TCT_app/gui/bias_panel.py` (171, 567); `TCT_app/gui/multi_bias_panel.py` (42, 98)
