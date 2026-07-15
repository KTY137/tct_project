# U1 staging — viewmodel-first test reclaim (C→B), before any porting

| | |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-15 |
| **Status** | Staging design for dispatch (architecture beat, Fable) — awaiting Adam's dispatch + the two acks in §8 |
| **Stage** | `docs/ROADMAP_MASTERPLAN.md` Part II §UI, **U1** (branch `ui-qml-migration`) |
| **Terrain map** | `docs/CODEX_QUEUE.md` §C12 (per-test portability tables, 2026-07-15) |
| **Boundary law** | `docs/design/run_state_facade.md` §1 — a viewmodel holds NO controller reference and NO start/stop callables |
| **Safety carve-outs** | `docs/SAFETY_NORMATIVE_TESTS.md` (S2, Mary-ratified v0.2) — see §1.3 |

U1 converts the four big C-bucket GUI suites into viewmodel suites **before any
QML is written**: the logic that the (a)-class tests pin moves out of the
widgets into per-panel viewmodels, the panels become thin delegates over those
viewmodels, and the tests are rewritten to construct the VM instead of the
widget. U1 is **paint-free**: no QML files, no new visuals, no Surface/kit
work, no layout changes. The classic shell keeps working after every beat
because the widgets delegate — they do not fork.

C12 ground truth (portable-to-VM / total): planner **36/67** (deferred, §4.5),
scan_map **17/32**, scan_viewer **15/40**, sequencer **6/17**. Immediate
reclaim in wave 1: **38 tests** (17+15+6); planner's 36 follow as the U1 tail
once AxisSpec is on the branch.

---

## 1. Standing rules for every U1 beat

### 1.1 The extraction pattern (extract, don't duplicate)

Each slice performs the same four moves, in one beat:

1. **Extract** the state/derivation logic the (a)-class tests pin into a new
   `gui/*_viewmodel.py` QObject (Q_PROPERTY reads + one `changed` NOTIFY —
   the exact `RunStateViewModel`/`ScopeViewModel` house pattern).
2. **Delegate**: the panel keeps its public API and signal surface
   byte-compatible, constructs the VM internally (`self._vm = …`), forwards
   its existing `on_*` feeds into the VM, and repaints off `vm.changed`. No
   duplicated logic survives — the panel reads the VM's properties.
3. **Reclaim**: the (a)-class tests move into a new `tests/test_*_viewmodel.py`
   that constructs the VM directly (offscreen `QCoreApplication`, no widget).
   The assertions survive; only the host changes. The (b)-class residue stays
   in the old file, **byte-untouched and green** — that residue passing against
   the now-delegating widget is the fidelity proof of the extraction.
4. **Replicate the standing law** (S2 Ruling Q3): every new VM suite carries
   its own `test_read_only_no_command_surface` (no `start`/`pause`/`resume`/
   `stop`/`abort`/`execute`/`arm` attribute; no `_scanner`/`_sm`/
   `_coordinator`/`_scan` reference) and `test_owns_no_timer_no_thread`,
   modeled 1:1 on `tests/test_run_state_viewmodel.py`. These are what the
   per-panel U-stage gate later checks.

**VM lifetime (two-step plan):** in U1 every new VM is **panel-constructed**
(the panel builds and owns its VM). This keeps `tct_gui.py` out of every U1
lock list, preserves the classic wiring surface that (b)-class tests pin
(e.g. `test_public_api_surface_unchanged`), and keeps the composition root
untouched. At each panel's port stage (U2–U5) the VM's construction moves to
the composition root and is registered as a QML context property — the VM API
designed here must not assume a widget parent (parent stays optional,
default `None`, as in both existing VMs).

### 1.2 What a U1 viewmodel may and may not hold

- **Never** (constraint, structural, test-encoded): a reference to
  `ScanController`, `StateMachine`, `ScanCoordinator`,
  `SequenceCoordinator`, a `DangerGate`, or any callable that starts, stops,
  pauses, resumes, aborts, arms, or homes anything. Command/danger surfaces
  (buttons, latches, gate calls, `*_requested` signals) stay in the
  panel/host.
- **Never**: an owned QTimer or thread. Async machinery lives in a *service*
  object owned by the host (§4.5's `PlanEstimateService`); the VM only
  receives results.
- **Fine**: plain data (ScanPlan snapshots, `SequenceEntry` lists, points
  dicts, numpy grids), pure derivations, semantic *token names* as strings
  (`"busy"`, `"crit"` — semantics, not paint), non-hardware file I/O that a
  test pins as data behavior (queue YAML save/load, CSV export), and
  references to *other viewmodels* (composition — a VM reaching a VM can
  still reach no hardware).
- **Fed, never fetching**: mutation happens only via `update(...)`/`on_*`
  plain-method feeds called on the GUI thread by the host (coordinator
  signals connect **to** the VM's methods; the VM never connects itself to
  anything it would have to hold a reference to).

### 1.3 Untouchable in U1 (S2 carve-outs — hard constraint)

No U1 beat edits these tests or the code paths they pin:

- Every **(c)-class** test in the C12 tables: the sequencer's 10 (locks,
  modal shims, manual-pause fail-safe, abort routing, composition-root
  wiring guard) and the planner's 10.
- The **QtDangerGate cluster** in `tests/test_planner_panel.py` — **9 tests
  at HEAD** (C12 recount; S2 Ruling Q4 says "5-test cluster" — the cluster
  grew; see beat U1.0 and open question Q3).
- `test_arm_confirmation_uses_live_plan_bias_range_not_stale_estimate`
  (HV confirmation wording).
- The S2-manifest-listed sequencer (c) subset and the `tct_gui`
  `_on_sequence_active` wiring they pin (§5.4 spells out how the sequencer
  slice routes around them).

One deliberate exception, mandated by S2 itself: the manifest's
`test_sequencer_panel.py` row **orders** that
`test_arm_text_contains_every_routine_hv_and_travel` and
`test_queue_edit_rederives_envelope_no_stale` (both (a)-class) "must be
reclaimed into the U1 sequencer viewmodel suite, not dropped" — their
assertions move host, never weaken, and the manifest is updated in the same
beat (maintenance rule).

### 1.4 Runnable after every beat

`.\run.ps1` boots the classic shell in simulation after every beat (the
panels delegate; nothing forks). The existing QML-shell suites
(`test_qml_shell.py`, `test_qml_scan_status.py`, `test_run_state_viewmodel.py`,
`test_scope_viewmodel.py`) stay green — U1 adds siblings, it does not rewire
the QML chrome.

---

## 2. Placement decision (constraint 6): flat `gui/*_viewmodel.py`, no package

**Decision: follow the flat precedent.** New files are
`gui/scan_map_viewmodel.py`, `gui/scan_viewer_viewmodel.py`,
`gui/sequencer_viewmodel.py`, and (deferred) `gui/planner_viewmodel.py` —
siblings of the two VMs that already exist flat in `gui/`
(`run_state_viewmodel.py`, `scope_viewmodel.py`).

Justification: a `gui/viewmodels/` package would either strand the two
existing VMs outside it (a permanent two-convention split) or force moving
`run_state_viewmodel.py` — a module the S2 manifest names by path as the
standing-law **template row** and that `qml_shell`/`tct_gui` wiring imports;
churning a ratified safety-document reference for taste fails the
consistency test the brief sets. The end-state count is ~10 `*_viewmodel.py`
files in a directory of ~40 — the `_viewmodel` suffix already groups them
lexically, and the U2+ panel-VM-island pattern needs exactly one predictable
name per panel, which the suffix delivers. Verified before this decision:
nothing imports a module named `viewmodels`, and all candidate paths are
free. (If a later epoch wants the package, it is a mechanical `git mv` +
import sweep — cheap then, disruptive now.)

Test naming follows the same precedent: `tests/test_<panel>_viewmodel.py`
mirrors `tests/test_run_state_viewmodel.py`.

---

## 3. Slice list, dependency order, parallelism map

| Beat | Name | Owner (model) | Blocks / blocked by | Reclaims |
|---|---|---|---|---|
| **U1.0** | QtDangerGate carve-out (S2 Ruling Q4 precondition) | Noah (**opus** — danger-gate work per the standing override) | Blocks U1.3 (manifest lock) and U1.4 (same test file). Runs first, solo. | 0 (byte-preserving move) |
| **U1.1** | Scan-map VM (`ScanMapViewModel`) | Jonathan (sonnet) | none | 17 |
| **U1.2** | Scan-viewer VM (`ScanViewerViewModel`) | Noah (sonnet — no threading/danger content) | none | 15 (+2 (d) retired) |
| **U1.3** | Sequencer VM/host split (`SequencerQueueViewModel`) | Abel (opus) | after U1.0 (shared `SAFETY_NORMATIVE_TESTS.md` lock) | 6 |
| **U1.4** | Planner VM + estimate service | Noah (**opus** — QThread worker lifecycle) | **DO-NOT-DISPATCH until AxisSpec (trunk-P2) is importable on this branch**; also after U1.0 | 36 |

**Dispatch shape:**

```
U1.0  (solo, small, immediate Mary review — safety-manifest beat)
  └─► wave 1:  U1.1 ║ U1.2 ║ U1.3   (three agents in parallel, zero lock overlap)
        └─► wave-boundary: Mamoru standup + Kiroku batch (bucket map C→B,
            ARCHITECTURE.md, ledger) + thematic Mary batch (U1.1+U1.2;
            U1.3 gets its immediate review at landing)
              └─► U1 stage exit gate (§7) → merge-back
U1.4  (tail; dispatch gate = AxisSpec on branch; own mini-gate, §4.5)
```

**Per-slice file locks (complete; nothing else may be written):**

| Beat | Lock list |
|---|---|
| U1.0 | `TCT_app/tests/test_planner_panel.py` · `TCT_app/tests/test_qt_danger_gate.py` (new) · `docs/SAFETY_NORMATIVE_TESTS.md` · `docs/test_bucket_map.md` |
| U1.1 | `TCT_app/gui/scan_map_viewmodel.py` (new) · `TCT_app/gui/scan_map_view.py` · `TCT_app/tests/test_scan_map_viewmodel.py` (new) · `TCT_app/tests/test_scan_map_view.py` |
| U1.2 | `TCT_app/gui/scan_viewer_viewmodel.py` (new) · `TCT_app/gui/scan_viewer_panel.py` · `TCT_app/gui/run_state_viewmodel.py` (only if Q1 acked) · `TCT_app/tests/test_scan_viewer_viewmodel.py` (new) · `TCT_app/tests/test_scan_viewer_panel.py` · `TCT_app/tests/test_run_state_viewmodel.py` (additive only, if Q1 acked) |
| U1.3 | `TCT_app/gui/sequencer_viewmodel.py` (new) · `TCT_app/gui/sequencer_panel.py` · `TCT_app/tests/test_sequencer_viewmodel.py` (new) · `TCT_app/tests/test_sequencer_panel.py` · `docs/SAFETY_NORMATIVE_TESTS.md` (two-row host update, after U1.0 releases it) |
| U1.4 | `TCT_app/gui/planner_viewmodel.py` (new) · `TCT_app/gui/plan_estimate_service.py` (new) · `TCT_app/gui/planner_panel.py` · `TCT_app/tests/test_planner_viewmodel.py` (new) · `TCT_app/tests/test_plan_estimate_service.py` (new) · `TCT_app/tests/test_planner_panel.py` |

U1.1/U1.2/U1.3 are pairwise disjoint — genuine three-way parallelism.
`docs/test_bucket_map.md` reclassification (four suites C→B, new VM suites →
bucket D) is **deliberately pulled out of the code slices** into the Kiroku
wave-boundary batch, so the doc file creates no cross-slice lock (only U1.0
touches it in-beat, because Ruling Q4 explicitly requires that).

---

## 4. Per-slice design

### 4.1 U1.0 — QtDangerGate carve-out (precondition, mechanical)

S2 Ruling Q4, executed: move the QtDangerGate cluster out of
`tests/test_planner_panel.py` into a new `tests/test_qt_danger_gate.py`,
**byte-preserving every assertion** (imports/fixtures adjusted only). The
cluster at HEAD is **9 tests** (`test_qt_danger_gate_confirms_true_on_gui_thread`,
`…denies_false_on_gui_thread`, `…confirm_from_worker_thread`,
`…timeout_denies`, `…no_stray_dialog_after_shutdown`,
`…timeout_then_pump_shows_no_stray_dialog`,
`…dialog_exception_releases_worker_as_deny`,
`…shutdown_denies_pending_and_future`,
`…abort_denies_pending_but_stays_usable`) — four more than the manifest row
names; all 9 move together (the 5 named rows are normative, the other 4 ride
as supporting, exactly as "whole file rides bucket A" rows do). Same beat, per
the ruling: update the manifest row's host file + counts and give the new file
its bucket in `docs/test_bucket_map.md` (proposed **C**, or B if it lands
widget-light — Mary decides at her immediate review). No production code
changes; `gui/qt_danger_gate.py` untouched.

Exit: 9 tests collected and green in the new file; `test_planner_panel.py`
collects 58 and stays green; both docs updated; **immediate** Mary review
(safety-class beat); diff shows zero assertion changes.

### 4.2 U1.1 — Scan-map VM (Jonathan)

**New:** `gui/scan_map_viewmodel.py` — `class ScanMapViewModel(QObject)`.
Owns everything the C12 (a) rows pin: the points store
(`update_point`/`set_points` normalization incl. plain-dict values,
last-write-wins revisit, rounding-collision + duplicate/missing accounting),
quantity selection (`QUANTITIES`/`QUANTITY_UNITS` move here or are imported
from here), grid derivation via the existing
`analysis.scan_grid.points_to_grid`/`grid_extent` (the math stays in
`analysis/` — the VM composes it), NaN semantics (missing cells NaN,
finite-range levels for autoscale), cursor-readout derivation
(`valueAt(x,y)` + formatted text incl. empty-state and out-of-bounds dashes),
and CSV export (`csv_rows()` + `write_csv(path)` — data contract, selected
quantity, header-only-when-empty).

**`gui/scan_map_view.py`** becomes a delegate: keeps the pyqtgraph
ImageView/histogram, redraw timer + coalescing, freeze-levels toolbar, PNG
export, placeholder stack, theme — all (b) territory — and reads
grid/levels/readout from the VM. Public accessors (`points`, `point_count`,
`duplicate_count`, `grid_result`, `current_quantity`) forward to the VM.

**Reclaims (17, per C12 table):** the schema contract, the five
update/batch-load model tests, the three cursor-readout tests, quantity
switch, rounding/collisions, NaN autoscale, three CSV tests, counts
surfaced. All land in `tests/test_scan_map_viewmodel.py` + the two
standing-law tests. The 15 (b) tests stay in `test_scan_map_view.py`
byte-untouched.

Exit: new suite green offscreen; `test_scan_map_view.py` residue green
unmodified; standing-law pair present; app boots in sim.

### 4.3 U1.2 — Scan-viewer VM (Noah)

**New:** `gui/scan_viewer_viewmodel.py` — `class ScanViewerViewModel(QObject)`,
which **composes** the existing facade rather than re-deriving run state:

```python
class ScanViewerViewModel(QObject):
    changed = Signal()
    def __init__(self, parent=None, *, clock=time.monotonic):
        self.run = RunStateViewModel(parent=self, clock=clock)  # sub-VM, one truth
        ...
```

`run` is exposed as a constant Property so U2's `ScanViewer.qml` binds
`viewer.run.progressFraction` etc. — run-state derivation logic exists in
exactly one class. The viewer VM itself adds only the viewer-specific state
the C12 (a) rows pin: progress-tile staleness (armed-but-stale until first
progress), current-position text, manual-pause warn state, the z-focus curve
data model (point accumulation, reset-on-start, best-Z summary/header-chip
text), open-in-analysis eligibility (`terminal AND runPath` — including
path-set-after-finish), and run-path invalidation on new run. Feeds are the
same coordinator-signal forwards the panel already receives
(`on_scan_started/on_progress/on_point_done/on_scan_finished/on_error`
forwarded into `self.run` plus viewer-local handlers; `set_current_position`,
`set_last_run_path`, `on_manual_pause`, `on_z_focus_pt`, `on_z_focus_done`
feed the viewer half).

**ETA/elapsed (pending Q1):** the panel's `_compute_eta`/`_format_duration`
arithmetic moves into `RunStateViewModel` (replacing the `"--"` placeholder
and deleting the panel copy in the same beat) **only if Adam acks Q1**; the
additions to `tests/test_run_state_viewmodel.py` are additive
(`test_eta_computed_with_injected_clock` per the facade doc's own §7 plan).
If Q1 is declined, ETA stays panel-side, its test stays (b), and this slice
reclaims 14 instead of 15.

**`gui/scan_viewer_panel.py`** delegates: buttons/banners/tiles/pyqtgraph
z-focus plot remain, enabled-states and texts read from the VM. Pause/Abort/
z-focus-start/apply-best-z/open-analysis **command signals stay on the
panel** (constraint 3); `test_scan_viewer_wiring.py` (the S2 safety wiring
host) is not in the lock list and is untouched.

**Reclaims (15, per C12 table)** into `tests/test_scan_viewer_viewmodel.py`
+ standing-law pair (asserted on **both** the viewer VM and its `run`
sub-VM). Also retires the 2 (d) duplicates
(`test_scan_viewer_panel_source_has_zero_inline_hex`,
`test_scan_viewer_panel_never_calls_set_graphics_effect`) with a one-line
justification in the diff — global lint coverage exists. The 23 (b) tests
stay byte-untouched.

Exit: new suite green offscreen; residue green unmodified; standing-law
pair present; `test_run_state_viewmodel.py` green (extended only under Q1);
app boots in sim.

### 4.4 U1.3 — Sequencer VM/host split (Abel) — see §5 for the full design

Files: `gui/sequencer_viewmodel.py` (new), `gui/sequencer_panel.py`
(delegate; carve-out-respecting), `tests/test_sequencer_viewmodel.py` (new),
`tests/test_sequencer_panel.py` (move the 6 (a) tests out; (c)+(b) residue
byte-untouched), `docs/SAFETY_NORMATIVE_TESTS.md` (update the host of the
two manifest-listed reclaimed tests — same-beat maintenance rule; requires
U1.0 to have released the file).

Exit: new suite green offscreen; the 10 (c) + 1 (b) residue green
**byte-untouched**; standing-law pair present; manifest updated; app boots
in sim; **immediate** Mary review (safety-adjacent panel).

### 4.5 U1.4 — Planner VM + estimate service (Noah, opus) — **DO-NOT-DISPATCH**

**Dispatch gate:** AxisSpec (trunk-P2) importable on `ui-qml-migration`
(arrives via the weekly trunk→branch flow). `planner_panel.py` hard-codes
`Axis` members in ~15 places; baking the enum into a VM now would churn the
whole slice again when P3 axes flow through. Mamoru's wave-boundary standup
checks the gate; Adam dispatches only after it holds. Designed now so the
beat is brief-ready then:

- **`gui/planner_viewmodel.py`** — `class PlannerViewModel(QObject)`, pure
  (no thread, no timer): the ScanPlan tree model + mutation/decision logic
  (`_plan_drop_decision`, move/duplicate/remove/reorder, palette
  insert/append, self-and-descendant + leaf-target rejection), the undo
  stack + cap, latch-relevant *state* (armed / dry-run-ok flags, structural-
  change and run-end/error invalidation, motor-position / focus-Z stored
  values + eligibility), estimate *state* (latest-wins keying, pending/
  rendered values fed from the service), camera-block validation
  eligibility, and plan-limits helpers. Axis handling written against
  AxisSpec from day one. The ArmLatch widget, QtDangerGate, arm ceremony,
  and the command signals (`start_plan_requested`, `arm_hv_requested`,
  `abort_requested`) stay on the panel (constraint 3).
- **`gui/plan_estimate_service.py`** — `class PlanEstimateService(QObject)`:
  owns the estimate QThread + `_EstimateWorker`, latest-wins coalescing,
  small-plan inline fast path, bounded shutdown. A *service*, not a
  viewmodel — the standing law (VM owns no thread) forces this split; the
  panel owns the service and feeds results into the VM. This is exactly the
  C→B shape the C12 rows demand ("worker lifetime should move to
  VM/service"). Noah runs **opus** here (worker lifecycle/teardown class).
- **Reclaims (36, per C12 table)** into `tests/test_planner_viewmodel.py` +
  `tests/test_plan_estimate_service.py` + standing-law pair. Untouchable
  within the file (per §1.3): the arm-confirmation test and — already gone
  by then — the QtDangerGate cluster (U1.0). The 21 (b) drag-ghost/MIME/
  theme tests stay byte-untouched.

Exit: as §4.2/§4.3, plus its own targeted re-run of
`tests/test_qt_danger_gate.py` and the arm-confirmation test (proof the
carve-outs still pass unedited), plus a Mary review (danger-adjacent panel,
immediate). If U1 has already merged back (Q2), U1.4 repeats the §7 gate for
its own merge.

---

## 5. The sequencer split (constraint 4 — the real design question)

### 5.1 Why it is different

`SequencerPanel` is the only U1 target holding a **live coordinator** and
command callables (`arm_and_start`, `abort_sequence`, `load`, `build_gate`),
and 10 of its 17 tests are safety-normative. A naive "panel→VM" port would
either hand the VM the coordinator (violates the boundary) or gut the safety
host (violates the carve-outs). The split below gives the VM everything
*mirror-shaped* and leaves everything *command-shaped* exactly where the (c)
tests pin it.

### 5.2 The two classes

**`SequencerQueueViewModel`** (new, `gui/sequencer_viewmodel.py`) — the
read-only queue/run mirror **plus the source-queue data model** (queue
editing is data, not command — it arms nothing; the coordinator's own
`load()`-refuses-while-active remains the enforcing gate):

Owns:
- the source queue: `list[SequenceEntry]` (name / plan snapshot /
  source_path) with `add_routine(path)` (ScanPlan.load_yaml, fail-closed
  surfacing via a `load_error = Signal(str)` — no `notify` import),
  `remove(row)`, `move(row, delta)`, `save(path)` / `load(path)` (through
  `controller.sequencer.save_sequence_yaml`/`load_sequence_yaml`;
  loader error leaves the queue untouched — the reclaimed fail-closed test);
  edit methods refuse (no-op + logged) while `active` is mirrored True;
- per-row **live state**: `(state_word, visual_token, message)` rows — the
  `_ENTRY_CHIP` semantic ladder (DONE is quiet neutral never green; FAILED
  is the only crit) moves here as data (token *names*, not paint);
- run mirror: `active` (bool), `done`/`total` + `progressText`,
  `outcomeWord`, `lastError`;
- envelope mirror: `envelopeSummary` (plain str, **fed** by the host after
  `build_gate` — the VM never sees the gate or the coordinator).

Feed surface (plain methods, host-connected):
`on_entry_state(row, state_value, message)`, `on_progress(done, total)`,
`on_finished(word)`, `on_error(reason)`, `on_active(flag)`,
`set_envelope_summary(text)` (empty string = no valid envelope). One
`changed` NOTIFY for property reads plus one `queue_changed` signal (emitted
after any successful queue edit) — the host's cue to re-sync the coordinator.

Holds **no** `SequenceCoordinator`, no gate, no `park_safe`, no callables
into the run stack — standing-law tests replicated verbatim.

**The retained command/safety host is `SequencerPanel` itself** (no new
class in U1). It keeps, byte-stable where (c)-pinned:
- the live `SequenceCoordinator` reference and every command edge:
  `_on_execute → coordinator.arm_and_start()`,
  `_on_abort → coordinator.abort_sequence()`, `coordinator.load(...)`,
  `coordinator.build_gate(channel)` (the gate pair never enters the VM;
  the panel passes only `env.summary` onward);
- the `ArmLatch` (hold-3s ceremony), the `HazardSurface` wrap, the Abort
  button and its enabled-state logic, and `_envelope_html` (danger-red span
  = paint/theming, stays with `palette()`);
- its **own** `self._active` flag fed from `sequence_active` for control
  gating (see §5.4).

At the sequencer's own port stage (post-U1; U4/U5 era) the host shrinks to a
retained QWidget island — working name `SequencerCommandHost`: ArmLatch +
Abort + gate plumbing — while the queue table/chips/progress chrome becomes
QML bound to this VM. U1 designs for that by keeping every VM property
QML-bindable now; it builds none of it.

### 5.3 Signal flow (who connects what — all connections made by the host)

```
SequenceCoordinator ──entry_state_changed──► vm.on_entry_state ─┐
                    ──sequence_progress────► vm.on_progress     │ changed
                    ──sequence_finished────► vm.on_finished     ├──────► panel repaints
                    ──sequence_error───────► vm.on_error        │        (table chips, labels,
                    ──sequence_active──────► vm.on_active       ┘         status chip)
                    ──sequence_active──────► panel._on_active        (UNCHANGED — control
                    ──sequence_error───────► panel notify path        gating + (c)-pinned)

vm ──queue_changed──► panel._sync_coordinator():
        latch.disarm("invalidated")                    (unchanged ordering)
        coordinator.load(vm.named_plans, source_paths=…)
        env, gate = coordinator.build_gate(channel)    (gate stays here)
        vm.set_envelope_summary(env.summary)           (fail-closed: "" + surfaced)
        latch.set_envelope_text(panel._envelope_html_from(vm.envelopeSummary))

panel ArmLatch.execute_requested ──► coordinator.arm_and_start()   (byte-stable)
panel _btn_abort.clicked ─────────► coordinator.abort_sequence()   (byte-stable)
```

### 5.4 Routing around the (c) carve-outs

The 10 (c) tests pin: abort-button → `abort_sequence`;
`TCTMainWindow._on_sequence_active` manual-danger lock/unlock (+ failure
path, + real-panel surgical round-trip); modal-shim suppression;
`sequence_active` wired in `_build_central`; the three manual-pause laws.
None of those paths route through the VM: `tct_gui.py` is not in the lock
list, the panel's `_on_abort`/`_btn_abort` wiring is byte-stable, and the
panel keeps its **own** `_active` flag for `_refresh_controls` (abort/latch
enabled-ness) rather than reading `vm.active`. That duplication of one
boolean is deliberate carve-out discipline: display state (chip text) reads
the VM; **control gating** keeps its pinned private path until the
sequencer's own port stage re-hosts those tests knowingly. The reclaimed
row-state tests keep asserting through coordinator signal round-trips (VM
fed by a real `SequenceCoordinator` + `FakeScanCoordinator` in the new
suite) so the *integration* semantics — not just setter/getter behavior —
stay pinned.

### 5.5 What U1.3 reclaims (the 6, by name)

`test_arm_text_contains_every_routine_hv_and_travel` → asserts
`vm.envelopeSummary` names every routine + max-HV + travel (host feeds it
via the real `build_gate`); `test_queue_edit_rederives_envelope_no_stale` →
edit → `queue_changed` → re-fed summary differs and names the new routine;
`test_rows_track_running_and_done_states` +
`test_rows_track_failed_and_skipped_states` → row `(word, visual)` ladders
through real coordinator advances; `test_save_load_queue_round_trip` +
`test_loader_error_surfaces_and_preserves_queue` → VM persistence contract.
The first two are S2-manifest rows: assertions verbatim, manifest host
column updated in the same beat.

---

## 6. The run-ownership seam (constraint 7) — reserved, not built

Panel-scoped calm (ratified Lantern kit; DECISIONS 2026-07-15) needs to
resolve, post-U1, *which* pane owns the current run. Pinned convention for
this epoch (Adam, from Mary's review, 2026-07-15):

1. **The app is single-run by construction** — one global
   `StateMachine`/`ScanController`/`ScanCoordinator`; the Sequencer drives
   that *same* coordinator through `SequenceCoordinator`. The facade's
   single `active` flag is therefore sufficient; no multi-run resolution is
   ever needed.
2. **Ownership is a convention, not a facade field:** "the run-owning
   panel" = the top-level window currently hosting the ScanViewer (or its
   status strip), gated by `runState.active` — **not** the arming panel
   (Planner/Sequencer). This definition survives Planner-closed-mid-run and
   a detached ScanViewer (which, per Lantern §7, calms whole as its own
   top-level).
3. **Sequencer-driven runs stay ScanViewer-scoped** for calm. If that ever
   changes, the extension point is a **read-only run-source/owner string
   property on `RunStateViewModel`**, fed exactly like `runPath`/`scanType`
   (poll or coordinator signal — never a controller reference). That is the
   named future seam; U1 must not build it.
4. **Spec drift, flagged:** Lantern §7's "ownership resolves through
   `run_state_facade` only" overstates what the facade exposes today; the
   ScanViewer-host convention above is the operative rule, and the §7
   wording amendment is a queued spec chore on Adam's side (not this file,
   not a U1 beat).

U1's only obligation — verified by shape, no code: nothing in this staging
precludes the future string property. `RunStateViewModel` is additively
extensible (one more `str` mirror + feed kwarg, same pattern as `runPath`);
`ScanViewerViewModel` composes rather than forks the facade, so `active`
keeps exactly one home; and no U1 VM caches its own competing notion of
"who owns the run".

---

## 7. U1 stage exit gate (standing per-stage gate, instantiated for a no-QML stage)

Before merge-back to trunk (wave 1 complete; U1.4 handled per Q2):

1. **[A-green]** — `.claude/check_bucket_a.ps1` passes (no bucket-A file
   changed; nothing in U1 touches one).
2. **S2 normative suites green** — targeted run of the manifest files
   touched or neighboring this stage at minimum
   (`test_qt_danger_gate.py` (new host), `test_planner_panel.py`
   (arm-confirmation), `test_sequencer_panel.py` (c) residue,
   `test_scan_viewer_wiring.py`, `test_sequencer.py`,
   `test_sequence_coordinator.py`, `test_scan_coordinator.py`,
   `test_run_state_viewmodel.py`); the bench full suite covers the rest.
3. **Bench full suite** — one run on sophonone
   (`bench_run.ps1 -Branch ui-qml-migration`) before merge-back; if the
   bench is down, that is said explicitly and the merge waits (never a
   silent laptop substitute).
4. **Per-panel qml-offscreen smoke, U1 form** (no QML exists for these
   panels yet — the gate's letter is "the migrated panel boots under
   `TCT_SHELL=qml`"; U1's equivalent): (a) every new VM imports and
   instantiates headless (`QT_QPA_PLATFORM=offscreen`, bare
   `QCoreApplication`) — this is each VM suite's default-construction test,
   named per panel; (b) the existing QML shell still boots offscreen
   (`test_qml_shell.py` green) proving the VM additions broke no context
   wiring; (c) each new VM suite carries the replicated standing-law pair
   (the gate's per-panel check item).
5. **Classic shell boots in simulation** (run.ps1 smoke) — constraint 8.
6. **Reclaim accounting recorded** — 38 tests moved C→B/D (17+15+6), 2 (d)
   retired, residues byte-untouched; `docs/test_bucket_map.md` +
   `docs/ARCHITECTURE.md` updated (Kiroku wave-boundary batch);
   `SAFETY_NORMATIVE_TESTS.md` consistent (U1.0 + U1.3 edits landed).
7. **Mamoru standup** at the wave boundary (claims-vs-git audit +
   lock/tree cross-check + AxisSpec dispatch-gate check for U1.4) —
   standard per the ratified cadence.
8. **Mary**: U1.0 and U1.3 reviewed immediately at landing (safety-class);
   U1.1 + U1.2 as one thematic "viewmodel boundary" batch. Review brief
   concern list: no command surface on any VM, no controller refs, residues
   byte-identical, extraction (not duplication) verified.

---

## 8. Open questions for Adam/Kaya

**Q1 — ETA authority (Adam, one line).** U1.2 wants to move the panel's
rate-based `_compute_eta` into `RunStateViewModel` and delete the panel copy
in the same beat — after which there is exactly ONE derivation, which honors
the intent of the 2026-07-11 placeholder ruling ("no competing estimate")
while superseding its letter ("source from `plan_estimate` when wired"; that
refinement stays queued, unchanged). Ack to proceed; decline ⇒ ETA stays
panel-side, U1.2 reclaims 14, nothing else changes.

**Q2 — U1 closure with the planner tail outstanding (Kaya, gate call).**
Proposal: U1's merge-back gate (§7) runs after wave 1 (3 of 4 suites
reclaimed, 38 tests), and U1.4 lands later as a self-gated tail beat once
AxisSpec arrives — rather than holding the whole stage (and U1.5/U2 behind
it) hostage to trunk-P2. The roadmap already marks the planner slice as the
one P-track-coupled slice; this makes the decoupling explicit. Confirm.

**Q3 — QtDangerGate cluster count drift (Mary, at her U1.0 review).** The
manifest's Ruling Q4 says "5-test cluster"; HEAD has 9 `test_qt_danger_gate_*`
tests. U1.0 moves all 9 (5 normative + 4 supporting) and updates the
manifest counts. Flagged so Mary ratifies the corrected count rather than
discovering it.
