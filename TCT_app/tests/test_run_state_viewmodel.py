"""Direct unit tests for ``gui.run_state_viewmodel.RunStateViewModel`` (QML-
hybrid slice 1 — the read-only run/scan-state facade, sibling of
``ScopeViewModel``; design: ``docs/design/run_state_facade.md``).

Pure Qt-property mapping: the poll feeder ``update()`` and the coordinator
feeders ``on_*`` take already-owned values (no I/O, no hardware) and mirror them
onto NOTIFY-able properties the QML Scan Viewer binds to. Headless, no QML
engine — a bare ``QObject`` subtype only needs a ``QCoreApplication``.

Includes the safety-critical boundary test (``test_read_only_no_command_
surface``): the view-model exposes NO run-control callable and holds NO
ScanController/StateMachine/coordinator reference — the structural read/command
boundary that encodes hardware safety rule 2.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from controller.scan_controller import ScanPoint, ScanResult
from controller.state_machine import AppState
from gui.run_state_viewmodel import RunStateViewModel


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def _result(x=1.0, y=2.0, z=3.0, index=0) -> ScanResult:
    """A minimal ScanResult carrying a ScanPoint (the only field the facade
    reads)."""
    return ScanResult(
        point=ScanPoint(x_mm=x, y_mm=y, z_mm=z, index=index),
        timestamp=0.0,
        ref_amplitude_V=0.0,
        ref_charge_pC=0.0,
        dut_amplitude_V=0.0,
        dut_charge_pC=0.0,
        dut_charge_norm=0.0,
        baseline_rms_V=0.0,
    )


# --------------------------------------------------------------------------- #
# 1. Defaults                                                                   #
# --------------------------------------------------------------------------- #
def test_defaults_before_any_feed():
    _app()
    vm = RunStateViewModel()
    assert vm.stateName == "DISCONNECTED"
    assert vm.running is False
    assert vm.paused is False
    assert vm.active is False
    assert vm.terminal is False
    assert vm.done == 0
    assert vm.total == 0
    assert vm.progressFraction == 0.0
    assert vm.pointText == "x=-- y=-- z=--"
    assert vm.etaText == "--"
    assert vm.errorText == ""
    assert vm.runPath == ""
    assert vm.scanType == ""


# --------------------------------------------------------------------------- #
# 2. Machine-state mapping + derived flags                                      #
# --------------------------------------------------------------------------- #
def test_update_sets_state_and_derived_flags():
    _app()
    vm = RunStateViewModel()

    vm.update(state=AppState.RUNNING)
    assert vm.stateName == "RUNNING"
    assert vm.running is True
    assert vm.active is True
    assert vm.paused is False
    assert vm.terminal is False

    vm.update(state=AppState.PAUSED)
    assert vm.paused is True
    assert vm.active is True
    assert vm.running is False
    assert vm.terminal is False

    vm.update(state=AppState.FINISHED)
    assert vm.terminal is True
    assert vm.running is False
    assert vm.active is False


def test_update_terminal_states_all_flag_terminal():
    _app()
    vm = RunStateViewModel()
    for st in (AppState.FINISHED, AppState.ABORTED, AppState.ERROR):
        vm.update(state=st)
        assert vm.terminal is True, st
        assert vm.active is False, st


# --------------------------------------------------------------------------- #
# 3. Run start resets and activates                                             #
# --------------------------------------------------------------------------- #
def test_on_scan_started_resets_and_activates():
    _app()
    vm = RunStateViewModel()
    vm.on_progress(5, 20)
    vm.on_point_done(_result())
    vm.on_error("Scan Error", "boom")

    vm.on_scan_started()
    assert vm.done == 0
    assert vm.total == 0
    assert vm.errorText == ""
    assert vm.pointText == "x=-- y=-- z=--"
    assert vm.active is True


# --------------------------------------------------------------------------- #
# 4/5. Progress counts, fraction, zero-total safety                             #
# --------------------------------------------------------------------------- #
def test_on_progress_counts_and_fraction():
    _app()
    vm = RunStateViewModel()
    vm.on_progress(3, 12)
    assert vm.done == 3
    assert vm.total == 12
    assert vm.progressFraction == 0.25
    assert "3/12" in vm.statusText


def test_on_progress_zero_total_no_divzero():
    _app()
    vm = RunStateViewModel()
    vm.on_progress(0, 0)      # must not raise
    assert vm.progressFraction == 0.0
    assert vm.etaText == "--"


# --------------------------------------------------------------------------- #
# 6. ETA is rate-derived (Adam's Q1 ruling, docs/design/u1_staging.md §4.3/§8, #
#    2026-07-15 — supersedes the letter of the 2026-07-11 placeholder ruling,  #
#    which this file's ``test_eta_text_stable_placeholder_not_derived`` used   #
#    to pin; that test's premise is what the Q1 ack changes, so it is updated  #
#    here rather than left red — see the U1.2 beat report for the deviation    #
#    note.)                                                                    #
# --------------------------------------------------------------------------- #
def test_eta_computed_with_injected_clock():
    """Design-doc test 6 (``docs/design/run_state_facade.md`` §7), now the
    canonical behavior: a fake clock makes the rate-derived ETA deterministic
    — matches ``ScanViewerPanel``'s own former ``_compute_eta``/
    ``_format_duration`` arithmetic 1:1 (ported, not re-derived)."""
    _app()
    clock = {"t": 100.0}
    vm = RunStateViewModel(clock=lambda: clock["t"])
    vm.on_scan_started()
    clock["t"] = 110.0          # 10 s elapsed
    vm.on_progress(4, 20)       # rate = 0.4/s, remaining = 16 -> 40 s
    assert vm.etaText == "40 s"


def test_eta_dashes_before_elapsed_time():
    """``on_progress`` reported before ``on_scan_started`` (no t0 yet) must
    degrade gracefully — mirrors the reclaimed
    ``test_progress_before_any_elapsed_time_reports_eta_dashes`` scan-viewer
    behavior, now provable directly against the one ETA derivation."""
    _app()
    vm = RunStateViewModel()
    vm.on_progress(1, 4)
    assert vm.etaText == "--"


# --------------------------------------------------------------------------- #
# 7. Current point text                                                         #
# --------------------------------------------------------------------------- #
def test_on_point_done_sets_point_text():
    _app()
    vm = RunStateViewModel()
    vm.on_point_done(_result(x=1.0, y=2.0, z=3.0))
    assert vm.pointText == "x=1.000 y=2.000 z=3.000"


# --------------------------------------------------------------------------- #
# 8. Error text                                                                 #
# --------------------------------------------------------------------------- #
def test_on_error_sets_error_text():
    _app()
    vm = RunStateViewModel()
    vm.on_error("Scan Error", "boom")
    assert vm.errorText == "boom"


# --------------------------------------------------------------------------- #
# 9. Finish keeps data, clears active, freezes elapsed                          #
# --------------------------------------------------------------------------- #
def test_on_scan_finished_keeps_data_clears_active():
    _app()
    clock = {"t": 0.0}
    vm = RunStateViewModel(clock=lambda: clock["t"])
    vm.on_scan_started()          # t0 = 0
    vm.on_progress(12, 12)
    clock["t"] = 42.0
    vm.on_scan_finished()         # freeze elapsed at 42 s
    assert vm.active is False
    assert vm.done == 12          # final counts retained
    assert vm.total == 12
    frozen = vm.elapsedText
    assert frozen == "42 s"
    # Elapsed stays frozen even as the clock keeps advancing post-finish.
    clock["t"] = 999.0
    assert vm.elapsedText == frozen


def test_elapsed_advances_with_clock_while_running():
    _app()
    clock = {"t": 5.0}
    vm = RunStateViewModel(clock=lambda: clock["t"])
    vm.on_scan_started()          # t0 = 5
    clock["t"] = 95.0             # 90 s later
    assert vm.elapsedText == "1.5 min"


# --------------------------------------------------------------------------- #
# 10. Run metadata                                                              #
# --------------------------------------------------------------------------- #
def test_run_metadata_exposed():
    _app()
    vm = RunStateViewModel()
    vm.update(scan_type="xy_scan", run_path="/x/run.h5")
    assert vm.scanType == "xy_scan"
    assert vm.runPath == "/x/run.h5"


def test_update_omitted_metadata_keeps_previous():
    _app()
    vm = RunStateViewModel()
    vm.update(scan_type="recipe_plan", run_path="/a.h5")
    vm.update(state=AppState.RUNNING)   # metadata omitted
    assert vm.scanType == "recipe_plan"
    assert vm.runPath == "/a.h5"


# --------------------------------------------------------------------------- #
# 11. NOTIFY fires per feed                                                      #
# --------------------------------------------------------------------------- #
def test_changed_notify_fires_per_feed():
    _app()
    vm = RunStateViewModel()
    fired = {"n": 0}
    vm.changed.connect(lambda: fired.__setitem__("n", fired["n"] + 1))
    vm.update(state=AppState.RUNNING)
    vm.on_scan_started()
    vm.on_progress(1, 4)
    vm.on_point_done(_result())
    vm.on_error("t", "m")
    vm.on_scan_finished()
    assert fired["n"] == 6


# --------------------------------------------------------------------------- #
# 12. Strict-bool / int coercion                                                #
# --------------------------------------------------------------------------- #
def test_coerces_truthy_falsy_and_int():
    _app()
    vm = RunStateViewModel()
    vm.update(state=AppState.RUNNING)
    assert vm.running is True and vm.active is True and vm.terminal is False
    vm.update(state=AppState.CONNECTED)
    assert vm.running is False and vm.active is False
    # Non-int progress values coerce to int; fraction is a float.
    vm.on_progress("6", "24")
    assert vm.done == 6 and vm.total == 24
    assert isinstance(vm.progressFraction, float)
    assert vm.progressFraction == 0.25


# --------------------------------------------------------------------------- #
# 13. Default construction (how the composition root builds it)                  #
# --------------------------------------------------------------------------- #
def test_default_construction_no_parent_does_not_raise():
    _app()
    vm = RunStateViewModel(parent=None)
    assert isinstance(vm, RunStateViewModel)


# --------------------------------------------------------------------------- #
# 14. SAFETY-CRITICAL: no command surface, no upward reference (§1 boundary)     #
# --------------------------------------------------------------------------- #
def test_read_only_no_command_surface():
    """The facade is a mirror, not a remote. It must expose NO run-control
    callable and hold NO reference through which QML could issue one — the
    structural read/command boundary that encodes hardware safety rule 2."""
    _app()
    vm = RunStateViewModel()

    # No start/pause/resume/stop/abort attribute of any kind.
    for name in ("start", "pause", "resume", "stop", "abort"):
        assert not hasattr(vm, name), (
            f"run-state facade must expose no '{name}' — it is read-only"
        )

    # No reference to the run-control layer through which a command could reach.
    for attr in ("_scanner", "_sm", "_coordinator", "_danger_gate", "_gate"):
        assert not hasattr(vm, attr), (
            f"run-state facade must hold no '{attr}' — the boundary is structural"
        )

    # Positive: nothing in its instance dict references a controller/state
    # machine / coordinator / danger-gate object by any name.
    forbidden_types = ("ScanController", "StateMachine", "ScanCoordinator", "DangerGate")
    for key, val in vars(vm).items():
        assert type(val).__name__ not in forbidden_types, (
            f"attribute {key!r} holds a {type(val).__name__} — forbidden"
        )


# --------------------------------------------------------------------------- #
# 15. Owns no timer / no thread (single-timer law)                              #
# --------------------------------------------------------------------------- #
def test_owns_no_timer_no_thread():
    from PySide6.QtCore import QThread, QTimer

    _app()
    vm = RunStateViewModel()
    assert vm.findChildren(QTimer) == []
    assert vm.findChildren(QThread) == []
    assert not hasattr(vm, "start")   # no start() → no self-driven poll loop
