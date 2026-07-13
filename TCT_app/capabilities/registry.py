"""Capability registry (roadmap stage D1b, spec §11.2) + the §7.2 route table.

Normative spec: ``docs/CAPABILITY_MODEL.md`` v1.0-rc.  The registry is
ADDITIVE DISCOVERY, not a mandatory indirection: nothing existing migrates to
it; panels, scan controller, and tests keep using ``DeviceManager``
attributes directly, and callers opt in via
``DeviceManager.capability_registry()``.

Built over the EXISTING device instances (the same objects, never copies),
duck-typed so this package never imports ``controller/`` (§2.3).  LAW (§2.4):
building the registry, deriving descriptors, and constructing bindings
perform ZERO instrument I/O.

Fail-closed guarantees enforced at BUILD (and on every re-derivation, §5.5):

* every descriptor's ``transport_id`` resolves in the §6.1 transport map —
  an unmappable id raises ``KeyError`` before any reserve can exist;
* the §7.2 LAWS hold for every published descriptor (:func:`check_v1_laws`):
  ``safety_class`` equals the max hazard of the wrapped device path, and NO
  v1 capability spans hazard domains (a spanning capability must be SPLIT);
* one ``capability_id`` is never published twice (§14.2);
* slow-control names that cannot map to an id raise (§5.1.1 item 3, via the
  adapter's use of ``slow_control_capability_id``).

Routing (§7.2, §14.1 ratified option (c)): class floor + MONOTONE ADD-ONLY
override.  The override channel is a union, so loosening is structurally
impossible; ``STOP`` is never gated (LAW), and ``>=`` on ``SafetyClass``
NEVER derives gate sets — gate sets come only from this table's per-hazard
union.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping

from capabilities.adapters import CapabilityBinding, describe_capabilities
from capabilities.model import (
    CapabilityDescriptor,
    HVSource,
    Operation,
    SafetyClass,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ROUTE_DANGER_GATE",
    "ROUTE_MOTION_ENVELOPE",
    "ROUTE_HV_LOCK",
    "ROUTE_EMISSION_INTERLOCK",
    "KNOWN_ROUTES",
    "RESERVED_ROUTES",
    "CLASS_FLOOR_ROUTES",
    "DEPRECATED_ID_ALIASES",
    "check_v1_laws",
    "CapabilityRegistry",
]

# --------------------------------------------------------------------------- #
# §7.2 gate-route vocabulary (permanent strings)                               #
# --------------------------------------------------------------------------- #

#: ``controller/danger_gate.py::DangerGate`` confirmation modal
#: (GUI: ``gui/qt_danger_gate.py::QtDangerGate``).
ROUTE_DANGER_GATE = "danger_gate"
#: ``devices/motor_base.py::SoftwareLimits.check`` in ``move_to``, pre-flighted
#: by ``PlanLimits`` from ``limits_user_frame()``.
ROUTE_MOTION_ENVELOPE = "motion_envelope"
#: ``BiasSupplyBase.check_voltage_in_range`` + the validator's fail-closed
#: ``safety.require_hv_confirmation`` check + ``DangerAction("hv_ramp")``.
ROUTE_HV_LOCK = "hv_lock"
#: RESERVED (§7.2) — NO implementation exists until P3.  Until then wavegen
#: arming stays hard-coded inside ``ScanController._acquire_core``; this NAME
#: MUST NOT be wired to anything, and generated UI renders an operation whose
#: floor names it as DISABLED (§7.4), never fired ungated, never given an
#: invented stand-in gate.
ROUTE_EMISSION_INTERLOCK = "emission_interlock"

KNOWN_ROUTES = frozenset({
    ROUTE_DANGER_GATE, ROUTE_MOTION_ENVELOPE, ROUTE_HV_LOCK,
    ROUTE_EMISSION_INTERLOCK,
})
RESERVED_ROUTES = frozenset({ROUTE_EMISSION_INTERLOCK})

_NO_ROUTES: frozenset[str] = frozenset()

#: The §7.2 default class-floor route table (v1), keyed [class][operation].
#: LAW: ``STOP`` is never gated — every STOP entry is empty and the override
#: validator refuses a STOP override.  ``READ`` is never gated (it respects
#: the §6.1 transport reservation instead).  NOTE the deliberate
#: NON-MONOTONICITY (§7.1): EMITTING — the highest class — has an EMPTY ``SET``
#: floor (wavegen setters are ungated today and never touch output state,
#: §7.4) while MOTION and HV do not; this is exactly why ``safety_class >= X``
#: must never derive gate sets.  MOTION's contextual ``danger_gate`` on SET
#: (first move / scan start, where the existing executor already confirms) is
#: an executor-side ADD-ONLY override per §14.1(c), not part of the floor.
CLASS_FLOOR_ROUTES: dict[SafetyClass, dict[Operation, frozenset[str]]] = {
    SafetyClass.BENIGN: {op: _NO_ROUTES for op in Operation},
    SafetyClass.MOTION: {
        Operation.READ: _NO_ROUTES,
        Operation.SET: frozenset({ROUTE_MOTION_ENVELOPE}),
        Operation.ARM: frozenset({ROUTE_DANGER_GATE}),
        Operation.START: frozenset({ROUTE_DANGER_GATE}),
        Operation.STOP: _NO_ROUTES,
    },
    SafetyClass.HV: {
        Operation.READ: _NO_ROUTES,
        Operation.SET: frozenset({ROUTE_HV_LOCK, ROUTE_DANGER_GATE}),
        Operation.ARM: frozenset({ROUTE_DANGER_GATE}),
        Operation.START: frozenset({ROUTE_DANGER_GATE}),
        Operation.STOP: _NO_ROUTES,
    },
    SafetyClass.EMITTING: {
        Operation.READ: _NO_ROUTES,
        Operation.SET: _NO_ROUTES,
        Operation.ARM: frozenset({ROUTE_EMISSION_INTERLOCK}),
        Operation.START: frozenset({ROUTE_EMISSION_INTERLOCK}),
        Operation.STOP: _NO_ROUTES,
    },
}

# --------------------------------------------------------------------------- #
# §5.2 deprecation aliases (permanent machinery, empty in v1)                  #
# --------------------------------------------------------------------------- #

#: PERMANENT ``old_id → new_id`` alias table (§5.2).  Both sides resolve
#: forever; resolving a deprecated id is a WARNING, never an ERROR (old plans
#: keep running); deletion of an id or alias does not exist.  Empty in v1 —
#: no id has ever been deprecated — but the machinery is present from day one
#: so the promise is structural, not aspirational.
DEPRECATED_ID_ALIASES: dict[str, str] = {}


# --------------------------------------------------------------------------- #
# §7.2 hazard domains + build-time law checks                                  #
# --------------------------------------------------------------------------- #

# §5.3 device short key → hazard-domain class, derived from the §11.1 adapter
# table (which driver path each capability wraps) + the §7.3 class
# assignments.  This mapping is deliberately INDEPENDENT of the safety_class a
# descriptor declares — that independence is what gives check_v1_laws teeth:
# a mislabelled descriptor cannot satisfy both.
_DEVICE_HAZARD_CLASS: dict[str, SafetyClass] = {
    "motor": SafetyClass.MOTION,
    "bias_supply": SafetyClass.HV,
    "waveform_generator": SafetyClass.EMITTING,
    "scope": SafetyClass.BENIGN,
    "camera": SafetyClass.BENIGN,
    "intensity_monitor": SafetyClass.BENIGN,
}


def _hazard_class_for_device(short_key: str) -> SafetyClass:
    """Hazard-domain class of one §5.3 device short key; fail closed on a key
    outside the vocabulary (never guess a hazard class)."""
    if short_key.startswith("slow_control/"):
        return SafetyClass.BENIGN
    try:
        return _DEVICE_HAZARD_CLASS[short_key]
    except KeyError:
        raise ValueError(
            f"device short key {short_key!r} has no hazard-domain class — not "
            "in the §5.3 vocabulary; refusing to guess (fail closed)"
        ) from None


def _hazard_domains(descriptor: CapabilityDescriptor) -> frozenset[SafetyClass]:
    """Hazard-domain classes the descriptor's wrapped driver path touches:
    the device it drives (``device_id``) and the transport it exercises
    (``transport_id`` — the §6.1 pass-through case)."""
    return frozenset({
        _hazard_class_for_device(descriptor.device_id),
        _hazard_class_for_device(descriptor.transport_id),
    })


def check_v1_laws(descriptor: CapabilityDescriptor) -> None:
    """Enforce the §7.2 build-time LAWS on one descriptor; raise on violation.

    * **No domain spanning (D1 test requirement):** the wrapped driver path
      touches exactly ONE hazard domain — a capability spanning two MUST be
      split into per-domain capabilities in v1 (the union rule is the
      backstop, the split is the requirement).  This is what makes the §7.2
      floor table sufficient for v1 despite its §7.1 non-monotonicity.
    * **Max-hazard class:** ``safety_class`` MUST equal the max (§7.1
      ordering) of the class of every hazard the driver path can cause — for
      a non-spanning v1 capability, exactly that single domain's class, so a
      hypothetical combined move+bias capability declared MOTION (Mary
      BLOCKER-3) fails here.
    """
    domains = _hazard_domains(descriptor)
    if len(domains) != 1:
        raise ValueError(
            f"capability {descriptor.capability_id!r} spans hazard domains "
            f"{sorted(d.name for d in domains)} (device_id="
            f"{descriptor.device_id!r}, transport_id="
            f"{descriptor.transport_id!r}) — v1 capabilities MUST be split "
            "per hazard domain (spec §7.2 LAW)"
        )
    domain_class = max(domains)          # singleton; max() states the LAW
    if descriptor.safety_class is not domain_class:
        raise ValueError(
            f"capability {descriptor.capability_id!r} declares safety_class="
            f"{descriptor.safety_class.name} but its driver path's hazard "
            f"domain is {domain_class.name} — safety_class is the MAXIMUM "
            "hazard, not a chosen label (spec §7.2 LAW)"
        )


def _validate_route_overrides(
    overrides: Mapping[str, Mapping[Operation, frozenset[str]]],
) -> dict[str, dict[Operation, frozenset[str]]]:
    """Validate a §14.1(c) override table: ADD-ONLY by construction (it is
    only ever UNIONED with the floor), route names from the known vocabulary,
    and NEVER a STOP route (LAW §7.2)."""
    validated: dict[str, dict[Operation, frozenset[str]]] = {}
    for capability_id, per_op in overrides.items():
        if not isinstance(capability_id, str):
            raise TypeError(
                f"route-override key must be a capability_id str, got "
                f"{type(capability_id).__name__}"
            )
        table: dict[Operation, frozenset[str]] = {}
        for operation, routes in per_op.items():
            if not isinstance(operation, Operation):
                raise TypeError(
                    f"route-override operation for {capability_id!r} must be "
                    f"an Operation member, got {type(operation).__name__}"
                )
            routes = frozenset(routes)
            unknown = routes - KNOWN_ROUTES
            if unknown:
                raise ValueError(
                    f"route override for ({capability_id!r}, {operation.name}) "
                    f"names unknown route(s) {sorted(unknown)} — the §7.2 "
                    f"vocabulary is {sorted(KNOWN_ROUTES)} (fail closed)"
                )
            if operation is Operation.STOP and routes:
                raise ValueError(
                    f"route override for ({capability_id!r}, STOP) is "
                    "forbidden — LAW §7.2: STOP is never gated; gating a stop "
                    "is a safety inversion"
                )
            table[operation] = routes
        validated[capability_id] = table
    return validated


# --------------------------------------------------------------------------- #
# §11.2 CapabilityRegistry                                                     #
# --------------------------------------------------------------------------- #


class CapabilityRegistry:
    """Discovery + lock resolution over one ``DeviceManager``'s devices (§11.2).

    *device_manager* is duck-typed (attributes ``motor``, ``scope``,
    ``camera``, ``waveform_generator``, ``intensity_monitor``, ``bias_supply``,
    ``bias_channels``, ``slow_control``) — the same live instances, never
    copies.  Construction derives once (fail-closed pass: transport coverage +
    §7.2 laws + duplicate ids) and performs no I/O (LAW §2.4).

    *route_overrides* is the §14.1(c) ADD-ONLY per-(capability, operation)
    override channel — validated at build; empty in v1.
    """

    def __init__(self, device_manager, route_overrides=None) -> None:
        self._dm = device_manager
        self._route_overrides = _validate_route_overrides(route_overrides or {})
        # §6.1 transport map — built ONCE from the DeviceManager attributes
        # (no live query, LAW §2.4).  The lock RESOLVER's single source.
        transports = {
            "motor": device_manager.motor,
            "scope": device_manager.scope,
            "camera": device_manager.camera,
            "waveform_generator": device_manager.waveform_generator,
            "intensity_monitor": device_manager.intensity_monitor,
            # §6.1 (Mary BLOCKER-1 / Codex BLOCKER-A): DeviceManager.bias_supply
            # and every bias_channels entry are BiasChannel PROXIES WITH NO
            # LOCK OF THEIR OWN — their I/O delegates to the one shared
            # BiasSupplyBase, whose per-call lock is the real transport lock.
            # Resolving on the proxy would re-create BLOCKER-1 (a lock nothing
            # acquires).  All HV channels share this one entry = one lock,
            # because they share one physical transport.
            "bias_supply": device_manager.bias_supply.driver,
        }
        for ch in device_manager.slow_control.channels:
            # Each SlowControlChannel is a BaseDevice → carries the default
            # transport_lock accessor (its own io_lock).
            transports[f"slow_control/{ch.name}"] = ch
        self._transports = transports
        self._derive()      # build-time fail-closed pass (§6.1, §7.2, §14.2)

    # -- derivation (§5.5: per call, never cached) ---------------------------#

    def _derive(self) -> dict[str, CapabilityDescriptor]:
        """Re-derive every descriptor from the CURRENT device state and run
        the fail-closed checks.  Called at build and by every ``descriptors()``
        / ``get()`` — consumers MUST NOT cache the results across
        home/zero/reconnect events (§5.5)."""
        table: dict[str, CapabilityDescriptor] = {}
        for descriptor in describe_capabilities(self._dm):
            if not isinstance(descriptor, CapabilityDescriptor):
                raise TypeError(
                    "describe_capabilities produced a non-descriptor: "
                    f"{descriptor!r}"
                )
            if descriptor.transport_id not in self._transports:
                # §6.1: KeyError at registry build / binding construction —
                # fail closed BEFORE any reserve can exist.
                raise KeyError(
                    f"capability {descriptor.capability_id!r} names "
                    f"transport_id {descriptor.transport_id!r}, which is not "
                    "in the §6.1 transport map "
                    f"{sorted(self._transports)} (fail closed)"
                )
            check_v1_laws(descriptor)
            if descriptor.capability_id in table:
                raise ValueError(
                    f"capability_id {descriptor.capability_id!r} published "
                    "twice — one physical parameter is never two "
                    "simultaneously-published ids (spec §14.2)"
                )
            table[descriptor.capability_id] = descriptor
        return table

    # -- §11.2 API ------------------------------------------------------------#

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        """Every published descriptor, RE-DERIVED on each call (§5.5), in
        stable order (sorted by ``capability_id``)."""
        table = self._derive()
        return tuple(table[key] for key in sorted(table))

    def get(self, capability_id: str) -> CapabilityDescriptor:
        """Resolve one id (deprecation aliases included, §5.2); ``KeyError``
        on an unknown id (fail closed)."""
        alias = DEPRECATED_ID_ALIASES.get(capability_id)
        if alias is not None:
            # §5.2 step 2: deprecated ids keep resolving forever; surfaced as
            # a WARNING, never an error (old plans keep running).
            logger.warning(
                "capability_id %r is deprecated — use %r (spec §5.2)",
                capability_id, alias,
            )
            capability_id = alias
        table = self._derive()
        try:
            return table[capability_id]
        except KeyError:
            raise KeyError(
                f"unknown capability_id {capability_id!r} — published ids: "
                f"{sorted(table)} (fail closed)"
            ) from None

    def transport_lock_for(self, transport_id: str):
        """THE §6.1 lock resolver — exactly one API maps a ``transport_id``
        to a lock object: one attribute lookup on one named instance, no
        fallback, no search.  The returned object is ``is``-identical to the
        lock the owning driver's own I/O acquires (``transport_lock``
        accessor contract).  Unknown ids raise ``KeyError`` (fail closed).
        """
        try:
            owner = self._transports[transport_id]
        except KeyError:
            raise KeyError(
                f"unknown transport_id {transport_id!r} — the §6.1 transport "
                f"map holds {sorted(self._transports)} (fail closed)"
            ) from None
        return owner.transport_lock

    def binding(self, capability_id: str) -> CapabilityBinding:
        """Construct the runtime handle (§6).  Performs no I/O and changes no
        instrument state (LAW §6/§15); the binding's lock resolves through
        :meth:`transport_lock_for` — no second resolution path exists."""
        descriptor = self.get(capability_id)
        return CapabilityBinding(
            descriptor=descriptor,
            target=self._target_for(descriptor),
            transport_lock=self.transport_lock_for(descriptor.transport_id),
        )

    # -- §7.2 routing ----------------------------------------------------------#

    def effective_routes(
        self, capability_id: str, operation: Operation,
    ) -> frozenset[str]:
        """The effective gate-route set for one (capability, operation) pair:
        the UNION of the class floors of every hazard domain the driver path
        touches (§7.2 union LAW; a singleton for every v1 capability by the
        no-spanning law), plus any §14.1(c) ADD-ONLY override.  Loosening is
        structurally impossible — overrides are unioned, never subtracted.
        Generated UI (D4b) fires a gate iff this set is non-empty (§7.4).
        """
        if not isinstance(operation, Operation):
            raise TypeError(
                f"operation must be an Operation member, got "
                f"{type(operation).__name__}"
            )
        descriptor = self.get(capability_id)
        routes: set[str] = set()
        for domain in _hazard_domains(descriptor):
            routes |= CLASS_FLOOR_ROUTES[domain][operation]
        routes |= self._route_overrides.get(
            descriptor.capability_id, {},
        ).get(operation, _NO_ROUTES)
        return frozenset(routes)

    # -- internals --------------------------------------------------------------#

    def _target_for(self, descriptor: CapabilityDescriptor):
        """The device object a binding drives, resolved from the SAME
        ``DeviceManager`` instances the transport map was built from."""
        if isinstance(descriptor, HVSource):
            if descriptor.capability_id == "bias.voltage":
                return self._dm.bias_supply          # the primary proxy object
            for ch in self._dm.bias_channels:
                if int(ch.channel) == descriptor.channel:
                    return ch
            raise KeyError(
                f"no BiasChannel with physical index {descriptor.channel!r} "
                f"for {descriptor.capability_id!r} — bias_channels holds "
                f"{[int(c.channel) for c in self._dm.bias_channels]} "
                "(fail closed; refresh_bias_channels() runs on connect)"
            )
        device_id = descriptor.device_id
        if device_id.startswith("slow_control/"):
            try:
                return self._transports[device_id]   # the channel IS the device
            except KeyError:
                raise KeyError(
                    f"unknown slow-control device {device_id!r} (fail closed)"
                ) from None
        targets = {
            "motor": self._dm.motor,
            "scope": self._dm.scope,
            "camera": self._dm.camera,
            "waveform_generator": self._dm.waveform_generator,
            "intensity_monitor": self._dm.intensity_monitor,
        }
        try:
            return targets[device_id]
        except KeyError:
            raise KeyError(
                f"capability {descriptor.capability_id!r} names device_id "
                f"{device_id!r}, outside the §5.3 vocabulary (fail closed)"
            ) from None
