# Run-state facade — one GUI-agnostic read surface for scan/run state

*Author: Abel, 2026-07-11. Scoped to the QML-hybrid slice-1 build
(`docs/DECISIONS.md` 2026-07-11 rows: **QML hybrid frontend** + **3-layer
law**). Companion to
[`gui_architecture_plan.md`](gui_architecture_plan.md) (§3 anti-God-object /
coordinator extraction) and the slice-2a QML shell
(`gui/qml_shell.py`, `gui/scope_viewmodel.py`). No hardware behavior — a
**read-only** view of state the app already owns.*

## 0. Verdict

Build a small, purely-fed **`RunStateViewModel`** (a `QObject` with
`Q_PROPERTY` reads + one `changed` NOTIFY) that mirrors already-cached
scan/run state. It is the middle layer of the 3-layer law: **QML view →
this view-model → the existing Qt/business layer** (`ScanController`,
`StateMachine`, `ScanCoordinator`). The QML Scan Viewer binds *only* to this
object's properties, so QML never reaches into `ScanController` or the state
machine. It is the exact sibling of `ScopeViewModel` — same construction,
same feed discipline, same teardown slot — extended to run state.

The single most important property of the design: **the view-model holds no
reference to `ScanController` or `StateMachine`.** It is *fed* values; it
cannot *reach* anything. That is what structurally guarantees the read/command
boundary in §1 — QML physically has no path from `runState` to a run-control
command.

## 1. Scope and the command boundary (non-negotiable)

| | In scope (READ) | Out of scope (COMMAND) |
|---|---|---|
| What | machine state, running/paused/terminal flags, progress (done/total/fraction), current point, ETA, elapsed, last error text, run metadata (scan type, HDF5 run path) | start / pause / resume / stop / abort |
| Where it lives | `RunStateViewModel` (this doc) | `ScanCoordinator` + `DangerGate`, on the existing confirmed/danger-gated paths (safety rule 2) |

**Boundary rule (safety-critical, encoded as a test — §7):** the view-model
exposes **zero** methods that start, pause, stop, or abort a run, and holds
**zero** references (`_scanner`, `_sm`, `_coordinator`) through which QML could
issue one. Run control stays exactly where it is: the Scan Planner arms/starts
(HV-arm latch + `DangerGate`), the Scan Viewer's Pause/Abort emit to
`ScanCoordinator`. This facade is a mirror, not a remote. The pill for QML: *if
you want to change the run, you emit a signal a Python coordinator handles; the
view-model can only tell you what the run is doing.*

## 2. API sketch

New module `gui/run_state_viewmodel.py` (sibling of `gui/scope_viewmodel.py`).

```python
class RunStateViewModel(QObject):
    """Read-only Qt-property mirror of scan/run state for the QML Scan Viewer.

    Fed on the GUI thread only — never performs I/O, owns no thread, owns no
    timer, and holds NO ScanController/StateMachine reference (the command
    boundary is structural). Poll-fed for machine state + run metadata;
    signal-fed (existing GUI-thread coordinator signals) for progress / point /
    error. ETA/elapsed are pure presentation derivations of received data — no
    run-control policy lives here.
    """
    changed = Signal()

    def __init__(self, parent=None, *, clock=time.monotonic):
        super().__init__(parent)
        self._clock = clock            # injectable for deterministic tests
        self._state_name = "DISCONNECTED"
        self._running = self._paused = self._terminal = False
        self._active  = False          # a run is in progress (running or paused)
        self._done = self._total = 0
        self._point = None             # last ScanPoint (or None)
        self._error_text = ""
        self._scan_type = ""
        self._run_path  = ""
        self._t0 = None                # monotonic start (set on on_scan_started)
        self._elapsed_frozen = None    # elapsed captured at finish

    # ---- POLL feed (1 Hz, GUI thread — plain method, NOT a @Slot) --------
    def update(self, *, state=None, scan_type=None, run_path=None):
        """Snapshot machine state + run metadata from the composition root's
        cached-state poll. Mirrors ScopeViewModel.update: kwargs are already-read
        values (no I/O). state is an AppState; scan_type/run_path are strings."""

    # ---- SIGNAL feed (existing coordinator signals, GUI thread) ----------
    def on_scan_started(self):            # ← ScanCoordinator.scan_started
    def on_progress(self, done, total):   # ← ScanCoordinator.progress
    def on_point_done(self, result):      # ← ScanCoordinator.point_done
    def on_scan_finished(self):           # ← ScanCoordinator.scan_finished
    def on_error(self, title, message):   # ← ScanCoordinator.error_dialog
```

Read-only QML-facing properties (all `@Property(..., notify=changed)`):

| Property | Type | Meaning |
|---|---|---|
| `stateName` | str | `AppState.name` (e.g. `"RUNNING"`) |
| `running` | bool | state is `RUNNING` |
| `paused` | bool | state is `PAUSED` |
| `active` | bool | a run is in progress (running **or** paused) |
| `terminal` | bool | state in `FINISHED`/`ABORTED`/`ERROR` |
| `done` | int | points completed this run |
| `total` | int | total points (0 = unknown/not started) |
| `progressFraction` | float | `done/total`, 0.0 when `total==0` (no div-by-zero) |
| `pointText` | str | `"x=.. y=.. z=.."` current point, `"x=-- y=-- z=--"` when idle |
| `etaText` | str | formatted ETA, `"--"` when not yet estimable |
| `elapsedText` | str | formatted elapsed (frozen at finish) |
| `errorText` | str | last error message, `""` when none |
| `scanType` | str | run kind label (`"xy_scan"`, `"recipe_plan"`, …), `""` when idle |
| `runPath` | str | last-written HDF5 path, `""` when none |
| `statusText` | str | compact one-line summary, e.g. `"Running 128/400"` |

Notes:
- **The `on_*` feeders are plain Python methods, not `@Slot`s** — exactly like
  `ScopeViewModel.update`. They receive coordinator signals over a same-thread
  (direct) connection (PySide6 connects a signal to any callable). Keeping them
  un-decorated means they are not QML-invokable, so QML sees only the property
  reads — reinforcing §1. (Even if they were invokable, they only mutate the
  local mirror; they cannot touch hardware. Making them `@Slot` would be
  acceptable if queued semantics were ever needed, but they must stay
  command-free.)
- **ETA/elapsed** reuse the same arithmetic the classic `ScanViewerPanel`
  already ships (`_compute_eta`/`_format_duration`); centralizing it here is why
  both surfaces can later agree on one number (§8). This is presentation
  derivation of received progress, **not** policy — the facade makes no decision
  that affects the run.

## 3. Data flow (text)

```
  scan worker thread (daemon)                     GUI thread
  ---------------------------                     ----------
  ScanController._run / _run_plan
    ├─ StateMachine.transition(RUNNING/…)  ──┐
    │     (fires state callback here,        │  (1) POLL, 1 Hz — the SHARED
    │      on the worker thread)             │      _light_timer tick
    │                                        │        _collect_shell_state()
    │                                        └──►      reads sm.state + run meta
    │                                                  → bridge.pull()
    │                                                    → runState.update(
    │                                                        state=…, scan_type=…,
    │                                                        run_path=…)
    │
    ├─ on_progress(done,total) ─┐
    ├─ on_point_done(result)    │  _ScanBridge (in ScanCoordinator)
    ├─ on_finished()            ├─ queued Signal ──►  ScanCoordinator re-emits
    └─ on_error(msg)            ┘  (worker→GUI)        progress/point_done/
                                                       scan_started/scan_finished/
                                                       error_dialog  (GUI thread)
                                                         │
                                                (2) SIGNAL push — connect the
                                                    SAME existing signals that
                                                    already feed ScanViewerPanel:
                                                       coord.progress
                                                          → runState.on_progress
                                                       coord.point_done
                                                          → runState.on_point_done
                                                       coord.scan_started/finished
                                                          → runState.on_scan_*
                                                       coord.error_dialog
                                                          → runState.on_error
                                                         │
                                                         ▼
                                              runState.changed  ──►  QML bindings
                                                                     (ScanViewer.qml)
```

Two feed paths, **both on the GUI thread**, both reusing infrastructure that
already exists:

1. **Poll (cached snapshot, 1 Hz):** machine state + run metadata ride the
   existing `_light_timer` via the existing `_collect_shell_state` →
   `_ShellBridge.pull` path — the *same* mechanism that already feeds
   `scope_vm` and the rail's app-state chip. We add one `"run"` key to
   `_collect_shell_state` and one guarded forward in `pull()` (mirroring the
   existing `scope` block). **No new QTimer.**
2. **Signal push (event-driven):** progress / current-point / error arrive on
   the *existing* `ScanCoordinator` signals, which `_ScanBridge` has *already*
   marshaled from the worker thread onto the GUI thread. We connect them to the
   view-model exactly as they are already connected to `ScanViewerPanel`. **No
   new marshaling, no new signals.**

Why split the two: progress/point are event-immediate (responsive cockpit),
while machine state at 1 Hz matches the rail's existing app-chip cadence and
keeps the `sm.state` read in exactly one place. (A pure-poll alternative —
cache progress/point/error on the window and expose them via
`_collect_shell_state` — was rejected: it adds new cached window state, still
needs the same coordinator connections, and makes progress lag up to 1 s.)

## 4. Threading & thread affinity

Standing invariant (do not re-derive): the scan worker is a daemon
`threading.Thread`; `StateMachine` owns lifecycle; worker→GUI hand-off is via
`_ScanBridge`'s queued Qt signals. The facade sits **entirely inside that
invariant**:

- **The view-model is mutated only on the GUI thread.** Path (1) runs inside
  the `_light_timer` timeout (GUI thread). Path (2) runs inside coordinator
  signals that `_ScanBridge` has already delivered onto the GUI thread. **The
  scan worker thread never touches the view-model.** Therefore **no lock is
  needed** in the view-model — identical to `ScopeViewModel`.
- **The one cross-thread read** is `sm.state` inside `_collect_shell_state`
  (GUI thread) while the worker may call `transition()`. This is an atomic
  attribute read of an enum reference in CPython and is already how the rail's
  app chip reads state today (`_collect_shell_state` returns
  `"app": _chip(self._lbl_state)`, and `_lbl_state` is itself driven by the
  GUI-thread-marshaled `_on_state_change`). Worst case the readout is one 1 Hz
  tick stale — acceptable for a status surface, and the same staleness the
  existing rail already tolerates.
- **No new thread, no new timer.** The view-model owns neither (asserted in
  §7, mirroring `test_shell_bridge_owns_no_timer`).

## 5. Teardown

The facade is a plain `QObject` held by a composition-root attribute
`self._run_vm` (like `self._scope_vm`). It owns no timer, no thread, no device
handle, so there is nothing to *stop* — only references to drop, in an order
that guarantees no tick or signal reaches a half-dead object. Fit it into the
existing `_teardown_panels` sequence (`tct_gui.py`) as follows:

1. *(existing)* `_light_timer.timeout.disconnect(bridge.pull)` then
   `self._shell_bridge = None`. Because the machine-state poll rides
   `bridge.pull` (§3 path 1), this **already** severs the facade's poll feed —
   no new disconnect required for path (1).
2. *(existing)* clear the QML chrome source; `self._qml_chrome = None`.
3. **NEW:** `self._run_vm = None`, placed in the **same block that already sets
   `self._scope_vm = None`** (currently `tct_gui.py:1019`). By this point the
   poll is severed (step 1) and the chrome released (step 2), so no further
   `update()` can arrive.
4. *(existing)* `old_central.deleteLater()` tears down the central widget
   (which owns `ScanViewerPanel`); `ScanCoordinator` is reassigned on the next
   `_build_central` (it is unparented, held only by `self._coordinator`, so the
   previous one — and its outgoing connections to the now-dropped `_run_vm` —
   is collected). This is the **exact** lifetime that already governs the
   `coord.progress → ScanViewerPanel.on_progress` connections; the facade's
   path-(2) connections ride the same mechanism and need no special disconnect.
5. *(existing)* stop `_light_timer`, bias poller, liveness monitor;
   `gate.shutdown()` releases any blocked `gate.confirm()` in the scan thread.

**Ordering rationale (Abel-owned):** the poll feed must be cut *before* the
reference is dropped (steps 1→3), and the reference must be dropped *before* the
coordinator/central teardown (steps 3→4) so a late queued coordinator signal
never targets a freed object. Because teardown always follows an abort/join
(no run is live during teardown), path (2) is quiescent by step 4 regardless.

> Pairing note (per `.claude/AGENT_PROTOCOL.md` routing tie-breaks): **Abel owns
> this ordering and the read/command boundary; Noah owns the mechanical
> `.connect()`/`.disconnect()` lines, the `runState` context-property
> registration in `build_qml_chrome`, and the QML bindings.**

## 6. Wiring (composition root)

Slice-1 lives entirely in QML mode (the QML Scan Viewer only exists when the
QML shell is built), so mirror the `scope_vm` wiring 1:1:

- **Construct** `self._run_vm = RunStateViewModel()` in the QML branch of
  `_build_central` (next to `ScopeViewModel()`), pass it into
  `build_qml_chrome(...)`, and register it as the `runState` context property
  (sibling of `scopeVm`).
- **Poll feed:** add a `"run"` dict to `_collect_shell_state`
  (`{"state": self._sm.state, "scan_type": <current>, "run_path": <last>}`)
  and one guarded forward in `_ShellBridge.pull` (mirror the `scope` block:
  `if run is not None and self._run_vm is not None: self._run_vm.update(**run)`).
- **Signal feed:** in the coordinator-wiring block (`tct_gui.py` ~414–421) add,
  alongside the existing `coord.* → self._scan_viewer.*` connections:
  `coord.scan_started.connect(self._run_vm.on_scan_started)`,
  `coord.progress.connect(self._run_vm.on_progress)`,
  `coord.point_done.connect(self._run_vm.on_point_done)`,
  `coord.scan_finished.connect(self._run_vm.on_scan_finished)`,
  `coord.error_dialog.connect(self._run_vm.on_error)`.

`run_path` for the poll comes from the existing thread-safe
`ScanController.last_run_path` accessor (already published in `_end_run` before
`on_finished`); `scan_type` can be surfaced by the coordinator/controller
(see §9). The classic `ScanViewerPanel` keeps its current direct signal
consumption in slice 1 — the facade is added *in parallel*, feeding the QML
surface — with convergence deferred (§8).

## 7. Test plan — mirror `tests/test_scope_viewmodel.py`

House pattern: a bare `QObject` subtype needs only a `QCoreApplication`;
`QT_QPA_PLATFORM=offscreen`; assert property mapping + NOTIFY, no QML engine.
New file `tests/test_run_state_viewmodel.py`:

1. `test_defaults_before_any_feed` — fresh VM: `stateName=="DISCONNECTED"`,
   `running/paused/active/terminal` all False, `done==total==0`,
   `progressFraction==0.0`, `pointText=="x=-- y=-- z=--"`, `etaText=="--"`,
   `errorText==""`, `runPath==""`, `scanType==""`.
2. `test_update_sets_state_and_derived_flags` — `update(state=RUNNING)` →
   `stateName=="RUNNING"`, `running`/`active` True, `terminal` False;
   `update(state=PAUSED)` → `paused`/`active` True, `running` False;
   `update(state=FINISHED)` → `terminal` True, `running`/`active` False.
3. `test_on_scan_started_resets_and_activates` — after some progress/error,
   `on_scan_started()` clears `done/total/errorText/pointText` and sets
   `active`.
4. `test_on_progress_counts_and_fraction` — `on_progress(3, 12)` →
   `done==3`, `total==12`, `progressFraction==0.25`, `"3/12" in statusText`.
5. `test_on_progress_zero_total_no_divzero` — `on_progress(0, 0)` →
   `progressFraction==0.0`, `etaText=="--"` (no exception).
6. `test_eta_computed_with_injected_clock` — construct with a fake `clock`,
   `on_scan_started()` then advance the clock and `on_progress(done,total)` →
   `etaText != "--"` and matches the panel's `_format_duration` output (the
   injectable clock is why this is deterministic).
7. `test_on_point_done_sets_point_text` — feed a
   `ScanResult(point=ScanPoint(1,2,3,0), …)` → `pointText=="x=1.000 y=2.000 z=3.000"`.
8. `test_on_error_sets_error_text` — `on_error("Scan Error", "boom")` →
   `errorText=="boom"`.
9. `test_on_scan_finished_keeps_data_clears_active` — after progress+finish:
   `active` False but `done/total` retained (finished cockpit still shows the
   last counts) and `elapsedText` frozen.
10. `test_run_metadata_exposed` — `update(scan_type="xy_scan",
    run_path="/x/run.h5")` → `scanType`/`runPath` reflect them.
11. `test_changed_notify_fires_per_feed` — connect `changed`; assert it
    increments on each `update`/`on_*` call (mirror
    `test_update_emits_changed_notify_signal`).
12. `test_coerces_truthy_falsy` — feed non-bool truthy/falsy where relevant;
    flags come out strict `bool` (mirror ScopeViewModel's coercion test).
13. `test_default_construction_no_parent_does_not_raise` — `RunStateViewModel(
    parent=None)` (how the composition root builds it).
14. **`test_read_only_no_command_surface` (safety-critical, §1):** assert the
    VM exposes **no** `start`/`pause`/`resume`/`stop`/`abort` attribute AND
    holds **no** `_scanner`/`_sm`/`_coordinator` reference — the structural
    read/command boundary. This is the test that encodes the safety rule.
15. `test_owns_no_timer_no_thread` — `vm.findChildren(QTimer)==[]` and no
    `QThread` (mirror `test_shell_bridge_owns_no_timer`).

Integration (extend `tests/test_qml_shell.py`, optional for slice 1): assert
`build_qml_chrome` registers the `runState` context property, and that one
`win._light_timer.timeout.emit()` tick refreshes `run_vm.stateName` after a
`_on_state_change` (mirror `test_shell_bridge_pulled_by_shared_light_timer`).

## 8. Deliberately deferred (slice 1 is ONE consumer: the QML Scan Viewer)

- **Classic-panel convergence.** `ScanViewerPanel` keeps consuming the
  coordinator signals directly for now. The facade is designed to serve it
  (its properties are exactly the panel's fields), so a later slice can point
  the classic panel at `runState` too — *one* read truth for both surfaces —
  without changing this API.
- **Live acquisition-rate / per-point telemetry** beyond current point +
  progress (leave to the scope/DAQ slice, like `ScopeViewModel.rateText`).
- **ETA from the core plan model.** ETA is derived here from observed rate; a
  later refinement can source it from the core-owned `plan_estimate.py` so the
  Planner's pre-run estimate and the live ETA agree (§9).
- **Voltage/Z-focus specifics** (IV points, best-Z) stay on their existing
  panel signals; the facade tracks generic run state, not per-mode plots.
- **Zero-latency terminal state** via reusing `_state_changed_sig` instead of
  the 1 Hz poll (§9) — not needed for a status readout in slice 1.

## 9. Open questions (need Adam/Kaya input)

1. **`scan_type` source.** `ScanController._begin_run` knows the scan type
   (`"xy_scan"`, `"recipe_plan"`, `"voltage_scan"`, …) but does not expose it
   as a pollable attribute or a signal. Cheapest: add a thread-safe
   `ScanController.current_scan_type` accessor (sibling of `last_run_path`) for
   the poll. Acceptable, or should `scan_type` ride an existing signal instead?
   (Owner overlap: controller accessor = Abel; wiring = Noah.)
2. **Machine-state feed: poll vs. reuse `_state_changed_sig`.** Slice 1 poll-
   feeds `stateName` at 1 Hz (consistent with the rail app chip). Reusing the
   existing GUI-thread `_state_changed_sig` would make terminal transitions
   zero-latency at the cost of coupling the facade to a window-private signal.
   Keep 1 Hz for slice 1, or adopt the signal now?
3. **ETA authority.** Derive live ETA in the facade (this doc) or source it
   from `plan_estimate.py` so live ETA == the Planner's pre-run estimate?
   Deferring per §8, but flag it so the two don't diverge by accident.
4. **`errorText` from `error_dialog` also carries "Plan refused" (a non-run
   pre-flight refusal).** That is arguably still run-state-relevant, but if a
   cleaner "last run error only" is wanted, the coordinator would need a
   dedicated run-error signal. Fine as-is for slice 1?
