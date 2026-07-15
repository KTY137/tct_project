"""Shared standing-law assertion helpers for the U1 QML view-model suites
(S2 Ruling Q3): every read-only view-model must expose NO run-control
command surface and own NO timer/thread — the structural read/command
boundary that encodes hardware safety rule 2 (CLAUDE.md).

Underscore-prefixed filename: pytest does not collect this module as tests.
It is imported by the VM suites that assert the pair (``test_run_state_
viewmodel.py``, ``test_scan_map_viewmodel.py``, ``test_scan_viewer_
viewmodel.py``, ``test_sequencer_viewmodel.py``, ``test_scope_viewmodel.py``)
in place of the four near-byte-identical bodies these were consolidated
from (Niwashi proposal P1, risk NONE — test-only).

``assert_no_command_surface`` / ``assert_owns_no_timer_or_thread`` take the
host QObject(s) to check plus, on the surface check, per-file additions via
``extra_names`` / ``extra_attrs`` / ``extra_types``. The BASE sets below are
the common minimum every one of the four original files already checked —
additive only: a file that checked more before (extra command names like
"execute"/"arm", an extra forbidden attr, or extra forbidden types) passes
those in via the ``extra_*`` arguments so it loses nothing by consolidating.
"""
from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QObject, QThread, QTimer

_BASE_COMMAND_NAMES: tuple[str, ...] = ("start", "pause", "resume", "stop", "abort")
_BASE_FORBIDDEN_ATTRS: tuple[str, ...] = (
    "_scanner", "_sm", "_coordinator", "_danger_gate", "_gate",
)
_BASE_FORBIDDEN_TYPES: tuple[str, ...] = (
    "ScanController", "StateMachine", "ScanCoordinator", "DangerGate",
)


def assert_no_command_surface(
    *hosts: QObject,
    extra_names: Iterable[str] = (),
    extra_attrs: Iterable[str] = (),
    extra_types: Iterable[str] = (),
) -> None:
    """Assert none of ``hosts`` expose a run-control callable, hold a
    reference through which QML could issue one, or hold (under any
    attribute name) an instance of a run-control-layer type.

    Each host is a mirror, not a remote: it must be structurally incapable
    of driving hardware, not merely undriven in the current test.
    """
    names = tuple(_BASE_COMMAND_NAMES) + tuple(extra_names)
    attrs = tuple(_BASE_FORBIDDEN_ATTRS) + tuple(extra_attrs)
    types = tuple(_BASE_FORBIDDEN_TYPES) + tuple(extra_types)

    for host in hosts:
        # No start/pause/resume/stop/abort(/...) attribute of any kind.
        for name in names:
            assert not hasattr(host, name), (
                f"{host!r} must expose no {name!r} — it is read-only"
            )

        # No reference to the run-control layer through which a command
        # could reach.
        for attr in attrs:
            assert not hasattr(host, attr), (
                f"{host!r} must hold no {attr!r} — the boundary is structural"
            )

        # Positive: nothing in its instance dict references a controller/
        # state machine/coordinator/gate object by any name.
        for key, val in vars(host).items():
            assert type(val).__name__ not in types, (
                f"{host!r} attribute {key!r} holds a {type(val).__name__} — forbidden"
            )


def assert_owns_no_timer_or_thread(*hosts: QObject) -> None:
    """Assert none of ``hosts`` own a QTimer/QThread child, and none expose
    a self-driven ``start()`` (the single-timer law)."""
    for host in hosts:
        assert host.findChildren(QTimer) == []
        assert host.findChildren(QThread) == []
        assert not hasattr(host, "start")   # no start() -> no self-driven poll loop
