"""
Danger-confirmation gate for the plan executor.

A tiny, hardware-free, Qt-free seam the executor calls *before* any dangerous
hardware action (HV ramp, first stage move, scan start).  The real GUI supplies
a gate that raises a confirmation dialog on the UI thread; tests and simulation
use :class:`AutoConfirmGate` / :class:`DenyAllGate`.

Design stance (see CLAUDE.md hardware-safety rules): dangerous actions require
*explicit user confirmation*.  The gate is how that confirmation reaches the
otherwise widget-free controller — the executor never imports a widget, it only
asks a :class:`DangerGate` to ``confirm(...)``.  Keeping this pure means the
whole scan/controller layer stays testable headless and safe with real hardware
attached.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class DangerAction:
    """One dangerous action awaiting confirmation.

    ``kind`` is a stable machine tag (``"hv_ramp"`` | ``"move"`` |
    ``"scan_start"``).  ``summary`` is a human sentence carrying the REAL
    numbers (e.g. ``"Ramp CH0 to -300 V"``), so the confirmation the operator
    sees is the exact action about to run — never a generic "are you sure?".
    ``detail`` carries the machine-readable payload (target voltage, axis
    envelope, …) for a richer dialog or a log line.
    """
    kind: str
    summary: str
    detail: dict = field(default_factory=dict)


@runtime_checkable
class DangerGate(Protocol):
    """Something that can confirm (or refuse) a :class:`DangerAction`.

    ``confirm`` returns ``True`` to proceed and ``False`` to refuse.  A refusal
    is a *return value*, not an exception: a normal deny must never raise, so
    the executor can treat it as a clean user-initiated abort.
    """

    def confirm(self, action: DangerAction) -> bool: ...


class AutoConfirmGate:
    """Confirms everything — for simulation and headless tests ONLY.

    NEVER wire this to a run that can reach real hardware: it defeats the entire
    confirmation gate.  It exists so the executor can be exercised end-to-end
    without a human in the loop.
    """

    def confirm(self, action: DangerAction) -> bool:
        return True


class DenyAllGate:
    """Refuses everything — exercises the fail-safe deny path in tests."""

    def confirm(self, action: DangerAction) -> bool:
        return False
