"""TCT capability spine (normative spec: ``docs/CAPABILITY_MODEL.md``).

D1a ships the pure data model (:mod:`capabilities.model` — GUI-free,
hardware-free, stdlib-only).  D1b adds ``capabilities/adapters.py`` (the
driver-wrapping ``CapabilityBinding`` runtime handles) and the
``CapabilityRegistry`` reached via ``DeviceManager.capability_registry()``.

Layering laws (spec §2): ``model.py`` imports only the standard library;
``adapters.py`` may import ``devices/*`` and the model, never ``controller/``
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
]
