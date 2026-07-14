"""TCT capability spine (normative spec: ``docs/CAPABILITY_MODEL.md``).

D1a ships the pure data model (:mod:`capabilities.model` — GUI-free,
hardware-free, stdlib-only).  D1b adds :mod:`capabilities.adapters` (the
driver-wrapping descriptor builders + the ``CapabilityBinding`` runtime
handle) and :mod:`capabilities.registry` (``CapabilityRegistry`` + the §7.2
route table), reached via ``DeviceManager.capability_registry()``.

Layering laws (spec §2, pinned by ``tests/test_layer_contracts.py``):
``model.py`` imports only the standard library; ``adapters.py``/
``registry.py`` may import ``devices/*`` and the model, never ``controller/``
or ``gui/``; ``controller/`` may import ``capabilities/``, never the reverse.
LAW (§2.4): no hardware I/O at import or construction, anywhere in this
package.
"""
from capabilities.model import (
    CAPABILITY_ID_PATTERN,
    MODEL_VERSION,
    SLOW_CONTROL_CHANNEL_ALIASES,
    CapabilityDescriptor,
    FrameSource,
    HVSource,
    Motion3D,
    Operation,
    ReadableChannel,
    ReadbackPolicy,
    SafetyClass,
    SweepableParameter,
    TriggerSource,
    WaveformSource,
    slow_control_capability_id,
)
from capabilities.adapters import (
    WAVEGEN_PLAN_KEYS,
    CapabilityBinding,
    VerifyResult,
    describe_capabilities,
)
from capabilities.registry import (
    CLASS_FLOOR_ROUTES,
    DEPRECATED_ID_ALIASES,
    KNOWN_ROUTES,
    RESERVED_ROUTES,
    ROUTE_DANGER_GATE,
    ROUTE_EMISSION_INTERLOCK,
    ROUTE_HV_LOCK,
    ROUTE_MOTION_ENVELOPE,
    CapabilityRegistry,
    check_v1_laws,
)

__all__ = [
    "CAPABILITY_ID_PATTERN",
    "MODEL_VERSION",
    "SLOW_CONTROL_CHANNEL_ALIASES",
    "CapabilityDescriptor",
    "FrameSource",
    "HVSource",
    "Motion3D",
    "Operation",
    "ReadableChannel",
    "ReadbackPolicy",
    "SafetyClass",
    "SweepableParameter",
    "TriggerSource",
    "WaveformSource",
    "slow_control_capability_id",
    "WAVEGEN_PLAN_KEYS",
    "CapabilityBinding",
    "VerifyResult",
    "describe_capabilities",
    "CLASS_FLOOR_ROUTES",
    "DEPRECATED_ID_ALIASES",
    "KNOWN_ROUTES",
    "RESERVED_ROUTES",
    "ROUTE_DANGER_GATE",
    "ROUTE_EMISSION_INTERLOCK",
    "ROUTE_HV_LOCK",
    "ROUTE_MOTION_ENVELOPE",
    "CapabilityRegistry",
    "check_v1_laws",
]
