"""API-shape guard for the bias-supply output control (Beat 1.2).

Rationale — the ``output_on`` footgun that this file exists to keep buried:
``BiasChannel.output_on`` (and the same name on every bias backend) used to be a
*method* that switches HV ON.  A bound method is always truthy, so a mistyped
state check ``if bias.output_on:`` silently read as "always on" AND was a single
missing ``()`` away from energizing a real supply.

The dangerous switch-ON action is now :meth:`enable_output`, and the *believed*
state is the read-only :attr:`is_output_on` property.  No attribute named
``output_on`` may exist on any bias class, so a stale ``bias.output_on`` now
raises ``AttributeError`` instead of quietly evaluating true.

Every check here is hardware-safe: real backend classes are only *inspected*
(never instantiated / no I/O), and the only objects constructed are the
simulated backend and a proxy over it.
"""
from __future__ import annotations

import pytest

from devices.bias_supply_base import BiasSupplyBase
from devices.bias_channel import BiasChannel
from devices.bias_supply_simulated import SimulatedBiasSupply
from devices.bias_supply_iseg import IsegBiasSupply
from devices.bias_supply_keithley import KeithleyBiasSupply
from devices.bias_supply_e4control import E4ControlBiasSupply


# Every class that exposes the bias output API: the abstract base, the proxy,
# and all concrete backends (real + simulated).  Real backends are only
# inspected as class objects below — never constructed — so no transport opens.
ALL_BIAS_CLASSES = [
    BiasSupplyBase,
    BiasChannel,
    SimulatedBiasSupply,
    IsegBiasSupply,
    KeithleyBiasSupply,
    E4ControlBiasSupply,
]


# (a) The trap name is gone from every class in the hierarchy.
@pytest.mark.parametrize("cls", ALL_BIAS_CLASSES, ids=lambda c: c.__name__)
def test_no_output_on_attribute(cls):
    """No bias class may carry an attribute named exactly ``output_on``.

    ``hasattr`` walks the full MRO, so this also rejects re-introducing it on a
    parent.  (The channel-explicit ``output_on_ch`` / ``output_is_on_ch`` are
    deliberately *different* names and stay.)
    """
    assert not hasattr(cls, "output_on"), (
        f"{cls.__name__}.output_on exists again — the always-truthy HV footgun "
        "is back; the switch-ON action must be named enable_output()."
    )


# (c) The dangerous action exists and is callable everywhere.
@pytest.mark.parametrize("cls", ALL_BIAS_CLASSES, ids=lambda c: c.__name__)
def test_enable_output_is_callable(cls):
    fn = getattr(cls, "enable_output", None)
    assert fn is not None, f"{cls.__name__} lost its enable_output action"
    assert callable(fn), f"{cls.__name__}.enable_output must be callable"


# (b) is_output_on is a read-only property on every class.
@pytest.mark.parametrize("cls", ALL_BIAS_CLASSES, ids=lambda c: c.__name__)
def test_is_output_on_is_a_property(cls):
    attr = getattr(cls, "is_output_on", None)
    assert isinstance(attr, property), (
        f"{cls.__name__}.is_output_on must be a property (a state query), "
        "not a method or plain attribute"
    )
    # Read-only: a getter-only property has no setter.
    assert attr.fset is None, (
        f"{cls.__name__}.is_output_on must be read-only — believed output state "
        "is never assigned through this surface"
    )


# (b, cont.) Assigning the property raises on a real (simulated) instance.
def test_is_output_on_assignment_raises_on_simulated():
    sup = SimulatedBiasSupply()
    with pytest.raises(AttributeError):
        sup.is_output_on = True          # type: ignore[misc]

    ch = BiasChannel(SimulatedBiasSupply(), 0)
    with pytest.raises(AttributeError):
        ch.is_output_on = True           # type: ignore[misc]


# (d) The truthiness tripwire: reading the old name is a hard error, never a
#     silently-truthy bound method, on a live simulated backend and its proxy.
def test_stale_output_on_read_raises_attributeerror():
    sup = SimulatedBiasSupply()
    with pytest.raises(AttributeError):
        _ = sup.output_on                # would have been an always-True method

    ch = BiasChannel(SimulatedBiasSupply(), 0)
    with pytest.raises(AttributeError):
        _ = ch.output_on


# Sanity: the believed-state property is honest bool and tracks enable_output /
# output_off on the simulated backend (no HV, no I/O).
def test_is_output_on_tracks_believed_state():
    sup = SimulatedBiasSupply()
    sup.connect()
    assert sup.is_output_on is False     # fresh + connected: driver believes OFF
    sup.enable_output()
    assert sup.is_output_on is True
    sup.output_off()
    assert sup.is_output_on is False

    ch = BiasChannel(sup, 0)
    assert ch.is_output_on is False
    ch.enable_output()
    assert ch.is_output_on is True
