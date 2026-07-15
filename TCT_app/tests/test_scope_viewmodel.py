"""Direct unit tests for ``gui.scope_viewmodel.ScopeViewModel`` (slice 2a —
retro nit: this seam was previously only exercised indirectly through
``_ShellBridge.pull()`` in ``tests/test_qml_shell.py``).

Pure Qt-property mapping: ``update()`` takes already-cached flags/strings (no
I/O, no hardware) and mirrors them onto NOTIFY-able properties the QML rail
binds to. Headless, no QQuickWidget/QML engine needed — a bare ``QObject``
subtype only needs a ``QCoreApplication`` instance to exist.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from gui.scope_viewmodel import ScopeViewModel
from tests._viewmodel_standing_law import (
    assert_no_command_surface,
    assert_owns_no_timer_or_thread,
)


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def test_defaults_before_any_update():
    _app()
    vm = ScopeViewModel()
    assert vm.connected is False
    assert vm.simulated is False
    assert vm.acquiring is False
    assert vm.statusText == "Scope offline"
    assert vm.rateText == ""


def test_update_maps_every_flag_and_status_text():
    _app()
    vm = ScopeViewModel()
    vm.update(connected=True, simulated=True, acquiring=True,
              status="Scope live", rate="10 Hz")
    assert vm.connected is True
    assert vm.simulated is True
    assert vm.acquiring is True
    assert vm.statusText == "Scope live"
    assert vm.rateText == "10 Hz"


def test_update_coerces_truthy_and_falsy_flags_to_bool():
    """The composition root's cached-state dict passes plain Python values
    (e.g. from ``getattr(scope, "connected", False)``); update() must not
    trip on a non-bool truthy/falsy value making it through."""
    _app()
    vm = ScopeViewModel()
    vm.update(connected=1, simulated=0, acquiring="yes")
    assert vm.connected is True
    assert vm.simulated is False
    assert vm.acquiring is True


def test_update_omitted_status_and_rate_keep_previous_text():
    """status/rate default to None (not provided every call) — a call that
    omits them must not blank out the last-known text."""
    _app()
    vm = ScopeViewModel()
    vm.update(connected=True, status="Scope ready", rate="5 Hz")
    assert vm.statusText == "Scope ready"
    assert vm.rateText == "5 Hz"

    # A later update that only flips a flag (status/rate omitted) preserves
    # the previously-set text rather than resetting it.
    vm.update(connected=True, acquiring=True)
    assert vm.statusText == "Scope ready"
    assert vm.rateText == "5 Hz"
    assert vm.acquiring is True


def test_update_emits_changed_notify_signal():
    _app()
    vm = ScopeViewModel()
    fired = {"n": 0}
    vm.changed.connect(lambda: fired.__setitem__("n", fired["n"] + 1))
    vm.update(connected=True, status="Scope live")
    assert fired["n"] == 1
    vm.update(connected=False, status="Scope offline")
    assert fired["n"] == 2


def test_default_construction_no_parent_does_not_raise():
    """Matches how the composition root constructs it (gui/tct_gui.py's QML
    branch: ``ScopeViewModel()``, no parent — kept alive by the caller's
    attribute, not Qt ownership)."""
    _app()
    vm = ScopeViewModel(parent=None)
    assert isinstance(vm, ScopeViewModel)


# --------------------------------------------------------------------------- #
# SAFETY-CRITICAL standing law (S2 Ruling Q3): no command surface, no upward   #
# reference, no owned timer/thread — the pair every U1/QML view-model suite   #
# carries (this file was previously missing it; backfilled per Niwashi P1).    #
# ``ScopeViewModel`` has no per-file extras: its only state is the connected/  #
# simulated/acquiring flags and the status/rate text, so the base sets alone  #
# fully cover it.                                                              #
# --------------------------------------------------------------------------- #
def test_read_only_no_command_surface():
    """The scope facade is a mirror of already-cached poll state, not a
    remote. It must expose NO run-control callable and hold NO reference
    through which QML could issue one — the structural read/command
    boundary that encodes hardware safety rule 2."""
    _app()
    vm = ScopeViewModel()
    assert_no_command_surface(vm)


def test_owns_no_timer_no_thread():
    _app()
    vm = ScopeViewModel()
    assert_owns_no_timer_or_thread(vm)
