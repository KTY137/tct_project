"""The capability spine's data model (roadmap stage D1a).

Normative spec: ``docs/CAPABILITY_MODEL.md`` v1.0-rc (Mary RATIFY-READY,
Kaya-ratified §14.1(c) + §14.2, 2026-07-13).  Section references below (§n)
point into that document; where this module and the spec disagree, the spec
wins.

What lives here (§3, the F1 data/binding split):

* **Descriptors** — pure data: frozen dataclasses, JSON-safe by construction
  (§4), no callables, no device references.  Descriptors are what the planner
  reads, what the validator checks against, and what provenance serialises.
* **NOT here** — ``CapabilityBinding`` (§6, the runtime setter/getter handle
  holding device references) and the registry/adapters (§11) are D1b, in
  ``capabilities/adapters.py``.  Bindings are never serialised (LAW §3).

Layering (§2.1): this module imports ONLY the standard library.  No Qt, no
numpy, no ``devices/``, no ``controller/``, no ``gui/`` — AST-layer-checkable
in the style of ``tests/test_layer_contracts.py``.

LAW (§2.4): building a descriptor performs ZERO instrument I/O.  Descriptors
are derived from constructor-time driver attributes and config, never from a
live query.  Nothing in this module can talk to hardware by construction —
there is nothing here to talk *with*.

Gate-routing hook points (documented here, implemented in D1b+, §7.2):

* **LAW — max-hazard class:** a capability's ``safety_class`` MUST equal the
  max (§7.1 ordering) of the class of every hazard its driver path can cause.
* **LAW — union routing:** effective routing is the union of the floor routes
  of every hazard class the driver path touches; a capability spanning two
  hazard domains MUST be split in v1.  A D1 registry-wide test asserts no v1
  capability spans domains.
* Neither law is computable from a descriptor alone (they constrain the
  *driver path* a descriptor wraps), so the model documents them and the
  registry/adapters enforce them.  This module builds NO routing.

v2 extensions (§12) — declared, NOT designed; deliberately absent from v1
(each would violate the no-field-without-a-live-consumer rule, §3):

* discrete-valued parameters (enumerated choices, e.g. coupling);
* per-set max-step (a per-transition delta clamp distinct from ``limits``);
* ``ReadableGroup`` — a typed composite read (the ``IntensityReading`` shape);
* coordinated multi-axis motion (a registered vector setpoint;
  ``stage.position`` is REJECTED for v1 — see :class:`Motion3D`, §5.4).

Declaring them here reserves the concepts so nobody wedges them into
``metadata`` (which LAW §7.5 forbids consuming as policy anyway).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import Enum, auto
from typing import Any

__all__ = [
    "MODEL_VERSION",
    "CAPABILITY_ID_PATTERN",
    "SLOW_CONTROL_CHANNEL_ALIASES",
    "slow_control_capability_id",
    "SafetyClass",
    "Operation",
    "ReadbackPolicy",
    "CapabilityDescriptor",
    "SweepableParameter",
    "ReadableChannel",
    "WaveformSource",
    "FrameSource",
    "TriggerSource",
    "HVSource",
    "Motion3D",
]

# Capability-model version string (§4: starts with "1").  Serialised into
# every snapshot() and, via DA1, into the swept/ group attrs (§10).
MODEL_VERSION = "1.0"

# §5.1 grammar, verbatim: lowercase ASCII segments [a-z][a-z0-9_]*, joined by
# single dots, at least two segments.  First segment = domain (v1 vocabulary:
# stage, bias, wavegen, scope, camera, intensity, slow_control — documented,
# not enforced: the grammar is permanent, the domain list grows); last
# segment = parameter.  IDs carry NO unit suffix — the unit lives in the
# descriptor's `unit` field (hence `wavegen.duty_cycle`, unit "%", even
# though the plan-grammar key is `duty_cycle_pct`; the adapter owns that
# mapping via a static table, never string munging).
CAPABILITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

# --------------------------------------------------------------------------- #
# §5.1.1 slow-control config→id alias table (decided, permanent)              #
# --------------------------------------------------------------------------- #

#: PERMANENT static alias table for exactly the four shipped
#: ``configs/devices.yaml`` slow-control channel names (§5.1.1).  The config
#: names violate the §5.1 grammar twice (uppercase, unit suffix in the id) but
#: are user-edited keys feeding connect_all result keys, HDF5/Influx series
#: and GUI labels — renaming them would break bench configs and data
#: continuity for zero benefit, so the mapping is a static table instead.
#: Same machinery as §5.2 deprecation aliases, present from day one; entries
#: are never removed (§5.2 permanence).  Units for the four targets (carried
#: by the D1b-built descriptors, not by this table): temperature "°C",
#: humidity "%RH", bias_voltage "V", leakage_current "nA".
SLOW_CONTROL_CHANNEL_ALIASES: dict[str, str] = {
    "temperature_C": "slow_control.temperature",
    "humidity_pct": "slow_control.humidity",
    "bias_voltage_V": "slow_control.bias_voltage",
    "leakage_current_nA": "slow_control.leakage_current",
}

_SLOW_CONTROL_ALIAS_TARGETS = frozenset(SLOW_CONTROL_CHANNEL_ALIASES.values())
_SLOW_CONTROL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def slow_control_capability_id(name: str) -> str:
    """Map a ``devices.yaml`` slow-control channel ``name`` to its
    ``capability_id`` (§5.1.1) — the ONE mapping the D1b registry uses.

    Fail-closed by construction (§5.1.1 item 3): a name this function cannot
    map raises, it is NEVER silently munged into an id (ids are permanent,
    §5.2; lowercasing could collide two channels onto one id).

    * one of the four grandfathered shipped names → its permanent alias;
    * grammar-conforming (``[a-z][a-z0-9_]*``) → ``slow_control.<name>``,
      unless that id collides with an alias target (e.g. a new channel named
      ``temperature`` while ``temperature_C`` owns
      ``slow_control.temperature`` forever) → ``ValueError``;
    * anything else → ``ValueError``.

    The whole-config collision/charset ERRORs live in
    ``controller/config_validator.py`` (Abel's half, §11.4 item 4); this
    helper is the per-name model-side truth both halves share.
    """
    if not isinstance(name, str):
        raise TypeError(
            f"slow-control channel name must be str, got {type(name).__name__}"
        )
    alias = SLOW_CONTROL_CHANNEL_ALIASES.get(name)
    if alias is not None:
        return alias
    if not _SLOW_CONTROL_NAME_PATTERN.fullmatch(name):  # `$` tolerates "\n"
        raise ValueError(
            f"slow-control channel name {name!r} is neither grammar-conforming"
            " ([a-z][a-z0-9_]*) nor one of the four grandfathered names"
            f" {sorted(SLOW_CONTROL_CHANNEL_ALIASES)}; refusing to munge it"
            " into a permanent capability_id (spec §5.1.1)"
        )
    capability_id = f"slow_control.{name}"
    if capability_id in _SLOW_CONTROL_ALIAS_TARGETS:
        raise ValueError(
            f"slow-control channel name {name!r} maps to {capability_id!r},"
            " which is the permanent alias target of a grandfathered channel"
            " name (spec §5.1.1) — rename the new channel"
        )
    return capability_id


# --------------------------------------------------------------------------- #
# §5 / §7 / §9 enums                                                          #
# --------------------------------------------------------------------------- #


class SafetyClass(Enum):
    """Coarse hazard display tier with the §7.1 TOTAL ORDERING

        BENIGN < MOTION < HV < EMITTING

    Compare with ``>=`` (rich comparisons over a private rank).  The concrete
    rank values are UNSPECIFIED and not part of the contract — only the
    relative order is promised; they MUST be tightened (frozen and
    documented) before any policy surface persists or transmits a numeric
    class.  Serialisation uses member NAMES (§4), which is what makes leaving
    the values loose safe today.

    LAW (§7.1): ``>=`` comparisons are legal ONLY for display/styling
    decisions (danger colouring, confirmation prominence, the §7.4
    disabled-control rule) — NEVER for deriving gate sets.  The §7.2 floor
    table is non-monotone in this ordering (EMITTING has an empty ``SET``
    floor while MOTION and HV do not), so ``safety_class >= X`` cannot be
    trusted to mean "at least as gated".  Gate sets come only from the §7.2
    per-hazard union LAW (registry territory, D1b+).

    LAW (§7.2): ``safety_class`` is the MAXIMUM hazard of every hazard the
    wrapped driver path can cause, not a chosen label — enforced by the D1
    registry-wide no-domain-spanning test, not constructible from a lone
    descriptor.
    """

    # auto() values are an internal rank in declaration order — deliberately
    # undocumented numbers (§7.1: "values unspecified"); never serialised.
    BENIGN = auto()
    MOTION = auto()
    HV = auto()
    EMITTING = auto()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SafetyClass):
            return NotImplemented
        return self.value < other.value

    def __le__(self, other: object) -> bool:
        if not isinstance(other, SafetyClass):
            return NotImplemented
        return self.value <= other.value

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, SafetyClass):
            return NotImplemented
        return self.value > other.value

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, SafetyClass):
            return NotImplemented
        return self.value >= other.value


class Operation(Enum):
    """The per-operation gate-routing axis (§7.2).

    Routing (which gate routes — ``danger_gate`` / ``motion_envelope`` /
    ``hv_lock`` / the RESERVED ``emission_interlock`` — apply to which
    (capability, operation) pair) is the ratified §14.1 option (c) shape:
    class floor plus monotone ADD-ONLY override.  It is registry/executor
    territory (D1b+); the model only names the axis.

    LAW (§7.2): ``STOP`` is never gated — stop/abort/disable MUST NOT require
    confirmation or any gate.  ``READ`` is never gated but respects the
    transport reservation (§6.1).
    """

    READ = auto()
    SET = auto()
    ARM = auto()
    START = auto()
    STOP = auto()


class ReadbackPolicy(Enum):
    """Per-capability read-back declaration (§9).

    * ``NONE`` — ``verify_or_skip()`` always returns ``skipped``; no readback
      datasets are written (§10).
    * ``BEST_EFFORT`` — one read-back attempt inside its own per-command
      reservation; failure degrades to ``failed``, never a raise, never a
      retry storm.

    This enum deliberately has NO ``MANDATORY`` member, and its absence is
    contractual (§9, §15): a mandatory mid-scan query per point would
    interleave with acquisition traffic on shared VISA/serial transports —
    the bench-observed TBS1052C ``CURVE?``-wedge class.  Adding one is a
    constitution-class change requiring Kaya ratification.
    """

    NONE = auto()
    BEST_EFFORT = auto()


# --------------------------------------------------------------------------- #
# §4 JSON-safety machinery (enforced, not advisory)                           #
# --------------------------------------------------------------------------- #

# The recursive value grammar (§4):
#     value := str | int | float | bool | None
#            | tuple[value, ...]
#            | Mapping[str, value]
# Anything else — a callable, an ndarray, a device reference, a *list*, a set
# — raises TypeError at CONSTRUCTION, not at provenance-write time.  An
# unvalidated Mapping[str, Any] would smuggle behaviour past the F1
# data/binding split; we fail closed at the door.


def _is_mapping_shaped(value: tuple) -> bool:
    """True when *value* has the canonical mapping encoding's shape: every
    element is a ``(str, value)`` 2-tuple.  Vacuously true for ``()`` (the
    canonical form of an empty mapping)."""
    return all(
        isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)
        for item in value
    )


def _canonicalise_json(value: Any, path: str) -> Any:
    """Validate *value* against the §4 grammar and return its canonical
    hashable form: mappings become SORTED tuples of ``(key, value)`` pairs
    (nested likewise); scalars and plain tuples pass through.

    ``types.MappingProxyType`` is REJECTED for this role by the spec (§4):
    a frozen dataclass with ``eq=True`` auto-generates ``__hash__``, and
    hashing a ``MappingProxyType`` field raises — the auto-hash trap.  The
    sorted-tuple form keeps the auto-generated ``__hash__`` working and makes
    snapshot ordering deterministic.

    Fail-closed ambiguity rule (forced by the spec's canonical form): a
    user-supplied tuple that is *mapping-shaped* (see
    :func:`_is_mapping_shaped` — e.g. ``(("a", 1),)`` or ``()``) is
    indistinguishable, after canonicalisation, from an encoded mapping — so
    two different inputs would compare equal yet mean different JSON.  Such
    tuples raise ``TypeError`` at construction; pass a mapping (or reshape
    the tuple) to say what you mean.  Rejecting is conservative and can be
    relaxed later; silently mis-rendering provenance could not be.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, tuple):
        if _is_mapping_shaped(value):
            raise TypeError(
                f"{path}: tuple {value!r} is ambiguous with the canonical"
                " mapping encoding (sorted tuple of (str, value) pairs, spec"
                " §4) — pass a mapping, or reshape the tuple"
            )
        return tuple(
            _canonicalise_json(item, f"{path}[{i}]") for i, item in enumerate(value)
        )
    if isinstance(value, Mapping):
        pairs = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"{path}: mapping key {key!r} is not str (spec §4 requires"
                    " string-keyed mappings)"
                )
            pairs.append((key, _canonicalise_json(item, f"{path}[{key!r}]")))
        pairs.sort(key=lambda pair: pair[0])
        return tuple(pairs)
    raise TypeError(
        f"{path}: {type(value).__name__} is not JSON-safe (spec §4 allows"
        " str/int/float/bool/None, tuples of these, and string-keyed mappings"
        " of these; lists must be tuples) — got {!r}".format(value)
    )


def _from_canonical(value: Any) -> Any:
    """Strict inverse of :func:`_canonicalise_json`'s mapping encoding, back
    to mappings/tuples — so ``dataclasses.replace()`` (which re-feeds the
    stored canonical ``metadata`` through ``__init__``) round-trips."""
    if isinstance(value, tuple):
        if _is_mapping_shaped(value):
            return {key: _from_canonical(item) for key, item in value}
        return tuple(_from_canonical(item) for item in value)
    return value


def _decode_canonical(value: Any) -> Any:
    """Render a canonical value as plain JSON types for :meth:`snapshot`:
    mapping-shaped tuples become dicts, plain tuples become lists, scalars
    pass through.  Unambiguous because mapping-shaped user tuples were
    rejected at construction (see :func:`_canonicalise_json`)."""
    if isinstance(value, tuple):
        if _is_mapping_shaped(value):
            return {key: _decode_canonical(item) for key, item in value}
        return [_decode_canonical(item) for item in value]
    return value


def _is_real_number(value: Any) -> bool:
    """True for int/float but NOT bool (bool is an int subclass; ``True`` as
    a limit/settle/resolution is a bug, not a number)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# --------------------------------------------------------------------------- #
# §5 the type family                                                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CapabilityDescriptor:
    """Pure-data description of one capability (§3, §5) — what the planner
    reads, the validator checks against, and provenance serialises.

    LAW (§3): ``snapshot()`` is what data-provenance writes (into
    ``scan_config`` / the ``swept/`` attrs, §10) — never a binding, never
    anything derived from one.

    Descriptors are immutable VALUE SNAPSHOTS (§5.5): some sources of truth
    move at runtime (the GRBL user-frame offset shifts ``limits_user_frame()``
    after home/zero), so the D1b registry re-derives descriptors per call and
    consumers MUST NOT cache them across home/zero/reconnect events.  The
    driver-internal runtime gates stay authoritative regardless of descriptor
    staleness — the capability layer adds pre-flight checks, it never weakens
    a driver gate.

    Rule of economy (§3): no field without a live consumer — the consumer
    table lives in spec §5; adding a field without one is a review-blocking
    defect.

    Fields:

    * ``capability_id`` — §5.1 grammar (``CAPABILITY_ID_PATTERN``), enforced
      here at construction.  LAW (§5.2): a published id carries the same
      permanence promise as the plan-JSON ``Axis`` aliases — never renamed,
      never reused with a different meaning, never removed; evolution only
      via the registry's permanent ``old_id → new_id`` alias table (D1b).
    * ``device_id`` — IDENTITY: the ``DeviceManager`` short key (§5.3
      vocabulary: ``motor``, ``scope``, ``bias_supply``, ``intensity_monitor``,
      ``camera``, ``waveform_generator``, plus ``slow_control/<name>``).
      Identity/provenance only — NEVER the lock key (§6.1).  Published
      values inherit §5.2 permanence.
    * ``transport_id`` — LOCK OWNER: whose ``transport_lock`` a reservation
      takes (§6.1); same §5.3 vocabulary; usually ``== device_id``, differs
      for pass-through devices (``ScopeChannelMonitor`` reads through the
      scope: ``device_id="intensity_monitor"``, ``transport_id="scope"``).
      Grouped reservations sort by ``transport_id`` (deadlock ordering).
    * ``label`` — human-readable, for UI/planner pickers (D4b form).
    * ``safety_class`` — §7 coarse tier; see :class:`SafetyClass` for the
      max-hazard LAW and the ``>=``-derivation ban.
    * ``metadata`` — JSON-safe provenance bag, validated and canonicalised
      at construction (§4).  LAW (§7.5): NEVER policy input — no safety
      decision, gate routing, limit, or validator behaviour may read it;
      policy fields must be first-class typed fields with named consumers.
    """

    capability_id: str
    device_id: str
    transport_id: str
    label: str
    safety_class: SafetyClass
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in ("capability_id", "device_id", "transport_id", "label"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(
                    f"{name} must be str, got {type(value).__name__}"
                )
        # fullmatch, not match: Python's `$` tolerates one trailing newline,
        # which would let "stage.x\n" become a permanent id.
        if not CAPABILITY_ID_PATTERN.fullmatch(self.capability_id):
            raise ValueError(
                f"capability_id {self.capability_id!r} violates the §5.1"
                " grammar ^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$"
                " (lowercase dotted segments, at least two)"
            )
        if not self.device_id:
            raise ValueError("device_id must be a non-empty §5.3 short key")
        if not self.transport_id:
            raise ValueError("transport_id must be a non-empty §5.3 short key")
        if not isinstance(self.safety_class, SafetyClass):
            raise TypeError(
                "safety_class must be a SafetyClass member, got"
                f" {type(self.safety_class).__name__}"
            )
        metadata = self.metadata
        if isinstance(metadata, tuple) and _is_mapping_shaped(metadata):
            # dataclasses.replace() re-feeds the stored canonical form.
            metadata = _from_canonical(metadata)
        if not isinstance(metadata, Mapping):
            raise TypeError(
                "metadata must be a string-keyed mapping (spec §4), got"
                f" {type(self.metadata).__name__}"
            )
        object.__setattr__(
            self, "metadata", _canonicalise_json(metadata, "metadata")
        )

    def snapshot(self) -> dict:
        """The JSON-safe provenance dict (§4): every descriptor field, plus
        ``"type"`` (concrete class name) and ``"model_version"``.

        ``json.dumps(descriptor.snapshot())`` succeeds with NO custom encoder:
        enums render as member NAMES (never ordinals — the ranks are
        deliberately unspecified, §7.1), the canonical ``metadata`` re-renders
        as plain dicts, and remaining tuples serialise natively.

        LAW (§3): this — never a binding — is what provenance writes into
        ``scan_config`` / the ``swept/`` attrs (§10).
        """
        snap: dict[str, Any] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name == "metadata":
                value = _decode_canonical(value)
            elif isinstance(value, Enum):
                value = value.name
            snap[field.name] = value
        snap["type"] = type(self).__name__
        snap["model_version"] = MODEL_VERSION
        return snap


@dataclass(frozen=True)
class SweepableParameter(CapabilityDescriptor):
    """A continuously settable scalar parameter (§5) — v1 is continuous-only
    (discrete-valued parameters are a declared v2 extension, §12).

    Fields (consumers per spec §5 table):

    * ``unit`` — display/provenance unit, e.g. ``"V"``, ``"mm"``, ``"%"``
      (D4b spinbox suffix; ``swept/`` attr).
    * ``limits`` — inclusive ``(lo, hi)``; ``None`` = no static limit (D4b
      clamps; P2 validator range checks).  ``None`` is CONSTRUCTIBLE at any
      safety class — the §7.4 rule that a generated control for
      ``safety_class >= MOTION`` with ``limits=None`` renders DISABLED is a
      UI-side render law, not a model refusal (``BiasSupplyBase.
      voltage_range_V`` is optional, so an HVSource with ``limits=None`` is
      real).  For stage axes, limits derive from the USER-FRAME envelope
      (``MotorStageBase.limits_user_frame()``), re-derived after home/zero —
      adapter duty, §5.4/§5.5.
    * ``resolution`` — smallest meaningful increment; ``None`` = unknown
      (D4b spinbox step default).
    * ``settle_s`` — descriptor DEFAULT settle; the plan wins (§8):
      ``effective_settle = plan_resolved if plan_resolved > 0.0 else
      descriptor.settle_s``.  Known v1 wrinkle (documented, not silently
      resolved): 0.0 doubles as the plan grammar's unset sentinel, so a plan
      cannot express "explicitly zero settle" over a positive descriptor
      default — a P2/AxisSpec grammar limitation, not a model change.
    * ``readback`` — §9 policy; drives the binding's ``verify_or_skip`` and
      the ``swept/`` readback datasets (§10).
    """

    unit: str
    limits: tuple[float, float] | None
    resolution: float | None
    settle_s: float = 0.0
    readback: ReadbackPolicy = ReadbackPolicy.NONE

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.unit, str):
            raise TypeError(f"unit must be str, got {type(self.unit).__name__}")
        if self.limits is not None:
            if not (
                isinstance(self.limits, tuple)
                and len(self.limits) == 2
                and all(_is_real_number(bound) for bound in self.limits)
            ):
                raise TypeError(
                    "limits must be None or an inclusive (lo, hi) tuple of"
                    f" two real numbers (spec §5), got {self.limits!r}"
                )
            lo, hi = self.limits
            if not lo <= hi:  # also False (→ raise) when either bound is NaN
                raise ValueError(
                    f"limits (lo, hi) must satisfy lo <= hi, got {self.limits!r}"
                )
        if self.resolution is not None:
            if not _is_real_number(self.resolution):
                raise TypeError(
                    "resolution must be None or a real number, got"
                    f" {type(self.resolution).__name__}"
                )
            if not self.resolution > 0:  # also catches NaN
                raise ValueError(
                    "resolution is the smallest meaningful increment and must"
                    f" be > 0 (or None = unknown), got {self.resolution!r}"
                )
        if not _is_real_number(self.settle_s):
            raise TypeError(
                f"settle_s must be a real number, got {type(self.settle_s).__name__}"
            )
        if not self.settle_s >= 0:  # also catches NaN
            raise ValueError(f"settle_s must be >= 0, got {self.settle_s!r}")
        if not isinstance(self.readback, ReadbackPolicy):
            raise TypeError(
                "readback must be a ReadbackPolicy member, got"
                f" {type(self.readback).__name__}"
            )


@dataclass(frozen=True)
class ReadableChannel(CapabilityDescriptor):
    """A read-only SINGLE scalar quantity with one honest ``unit`` (§5.4) —
    never a composite squeezed into one number.

    That is why intensity publishes TWO channels (§5.4):
    ``intensity.amplitude`` (unit "V") and ``intensity.charge`` (unit "pC")
    instead of one dishonest ``intensity.reading`` — the composite
    ``IntensityReading`` (waveform arrays, ``saturated`` flag) stays on the
    driver surface; a typed composite ``ReadableGroup`` is a declared v2
    extension (§12).  READ is never gated but respects the transport
    reservation (§6.1, §7.2).
    """

    unit: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.unit, str):
            raise TypeError(f"unit must be str, got {type(self.unit).__name__}")


@dataclass(frozen=True)
class WaveformSource(CapabilityDescriptor):
    """A waveform producer (§5), e.g. ``scope.waveform`` — a READ-operation
    producer whose binding exposes acquisition, not setting (§5.4).

    ``channels`` holds the channel labels, e.g. ``("ref_ch1", "dut_ch2")``
    (consumer: DA1 ``swept/``-adjacent provenance; scope adapter surface).
    """

    channels: tuple[str, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (
            isinstance(self.channels, tuple)
            and all(isinstance(channel, str) for channel in self.channels)
        ):
            raise TypeError(
                f"channels must be a tuple of str labels, got {self.channels!r}"
            )


@dataclass(frozen=True)
class FrameSource(CapabilityDescriptor):
    """A 2-D frame producer (§5), e.g. ``camera.frame``; frame shape is
    runtime information, deliberately not a descriptor field (§3 rule of
    economy).  READ-operation producer (§5.4)."""


@dataclass(frozen=True)
class TriggerSource(CapabilityDescriptor):
    """An armable output (§5.4), e.g. ``wavegen.output`` wrapping
    ``WaveformGenerator.output_on`` / ``output_off``.

    Arming is an ARM operation (§7.3 route: the RESERVED
    ``emission_interlock`` — hard-coded inside ``ScanController._acquire_core``
    until P3; the reserved route name MUST NOT be wired to anything before
    then, §7.2) and NEVER happens implicitly: no auto-arm on connect, on
    registry build, or on binding construction (LAW §6, §15).
    """


@dataclass(frozen=True)
class HVSource(SweepableParameter):
    """A high-voltage bias setpoint (§5) — ``bias.voltage`` (the
    primary-HV-channel ROLE, §14.2) or ``bias.ch{n}.voltage`` (PHYSICAL
    channel *n*).  ``safety_class`` is ``HV`` for every v1 instance (§7.3).

    LAW (§5.4) — **HVSource has NO kill.**  Neither this descriptor nor its
    binding exposes a kill/NOT-AUS/emergency-off surface; kill stays on the
    single existing safety path (the STOP/ALL-OFF QWidget instances and the
    driver fail-safe paths).  Polarity SWITCHING (a DANGEROUS relay action)
    is likewise not a capability in v1 — panel-only, gate-confirmed; the
    ``polarity`` field here is descriptive only.

    Binding-side notes (D1b hooks, documented here because the fields imply
    them): ``apply`` for an HVSource MUST route through the shaped-ramp path
    (``BiasSupplyBase.ramp_to`` semantics — never a direct ``set_voltage``
    jump) and accepts the plan-vocabulary shaping keys ``"ramp_step_V"`` /
    ``"ramp_delay_s"`` (§6, Mary BUG-4).

    Fields:

    * ``polarity`` — ``'p'``/``'n'`` as normalised by
      ``devices/bias_supply_base.py::normalize_polarity``; ``None`` =
      unknown/fixed.  Descriptive only (§5.4).
    * ``channel`` — resolved PHYSICAL ``BiasChannel`` index
      (``devices/bias_channel.py::BiasChannel.channel``); ``None`` = the
      driver has no channel concept.  Provenance disambiguation (§14.2,
      ``swept/`` ``channel`` attr §10) — never policy.  ``bias.voltage`` is
      deliberately NOT an alias for channel 0: the primary's physical index
      is config-chosen, and this field is what keeps provenance honest per
      run.  All ``bias.*`` capabilities share ``transport_id="bias_supply"``
      — one physical transport, one lock (§6.1, §14.2).
    """

    polarity: str | None = None
    channel: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.polarity is not None:
            if not isinstance(self.polarity, str):
                raise TypeError(
                    "polarity must be None or str, got"
                    f" {type(self.polarity).__name__}"
                )
            if self.polarity not in ("p", "n"):
                raise ValueError(
                    "polarity must be 'p', 'n' (normalize_polarity vocabulary,"
                    f" spec §5) or None, got {self.polarity!r}"
                )
        if self.channel is not None:
            if not isinstance(self.channel, int) or isinstance(self.channel, bool):
                raise TypeError(
                    f"channel must be None or int, got {type(self.channel).__name__}"
                )
            if self.channel < 0:
                raise ValueError(
                    "channel is a 0-based physical BiasChannel index (§14.2),"
                    f" got {self.channel!r}"
                )


# NOT a CapabilityDescriptor (§5.4, Codex MAJOR-D): a non-registered grouping
# helper.  It has no capability_id BY CONSTRUCTION and can never be registered
# (registration is keyed by capability_id) or snapshot into provenance — the
# registered, classed, serialised capabilities are its axes.
@dataclass(frozen=True)
class Motion3D:
    """Non-registered stage-envelope helper (§5.4) — deliberately NOT a
    :class:`CapabilityDescriptor`.

    Aggregates the per-axis registered ``stage.x/y/z``
    :class:`SweepableParameter` descriptors (unit ``"mm"``) so the registry
    builder and planner can treat the stage as one envelope.  It has no
    ``capability_id`` (so it CANNOT be registered), no ``snapshot()`` (so it
    is never provenance), and carries no safety class of its own — its axes
    are the classed capabilities.

    Why not a registered ``stage.position`` (§5.4, recorded so it is not
    re-proposed without a consumer): a binding drives exactly one capability
    and each axis already is one — a registered 3-vector twin would publish
    the same MOTION hazard path twice for zero new ability; no consumer for a
    vector setpoint exists (plan ``Axis`` / P3 ``AxisSpec`` are per-axis);
    and a descriptor field holding descriptors would violate §4's field
    restriction anyway.  Coordinated multi-axis motion is a declared v2
    extension (§12).
    """

    axes: tuple[SweepableParameter, ...]

    def __post_init__(self) -> None:
        if not (
            isinstance(self.axes, tuple)
            and all(isinstance(axis, SweepableParameter) for axis in self.axes)
        ):
            raise TypeError(
                "axes must be a tuple of SweepableParameter descriptors"
                f" (the registered stage.x/y/z, spec §5.4), got {self.axes!r}"
            )
