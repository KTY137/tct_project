"""Capability adapters + binding runtime (roadmap stage D1b).

Normative spec: ``docs/CAPABILITY_MODEL.md`` v1.0-rc — §6 (binding lifecycle),
§6.1 (transport reservation), §6.2 (reservation vs. fail-safe), §11.1 (adapter
table).  Where this module and the spec disagree, the spec wins.

What lives here (the runtime half of the §3 F1 data/binding split):

* **Adapter functions** — derive pure-data :class:`CapabilityDescriptor`
  snapshots from the EXISTING device objects, changing no driver.  Each
  builder wraps exactly the driver symbols the §11.1 table names — those are
  the proven, gated paths.
* **``describe_capabilities(device_manager)``** — the one entry point the
  registry (``capabilities/registry.py``) derives from.
* **:class:`CapabilityBinding`** — the runtime handle carrying the §6 staged
  lifecycle.  D1b ships the SKELETON: reservation (§6.1), fail-closed
  ``prepare``, honest ``verify_or_skip``, and the ``abort`` fail-safe
  delegation.  ``apply`` / ``wait_settled`` are wired to real setters by the
  P1 pilot (§11.3), not here.

Layering (§2.2): this module MAY import ``devices/*`` and the model.  It MUST
NOT import ``controller/`` or ``gui/`` (pinned by
``tests/test_layer_contracts.py``).

LAW (§2.4): deriving a descriptor, constructing a binding, or building the
registry performs ZERO instrument I/O.  Every value below comes from
constructor-time driver attributes / config state (or pure arithmetic on
them, e.g. ``MotorStageBase.limits_user_frame()``), never from a live query.

Descriptor freshness (§5.5): descriptors are immutable VALUE SNAPSHOTS at
derivation time.  Sources of truth move at runtime (the GRBL user-frame
offset shifts ``limits_user_frame()`` after home/zero), so the registry
re-derives per call and consumers MUST NOT cache descriptors across
home/zero/reconnect events.  Documented, not solved here: the driver-internal
runtime gates stay authoritative regardless of descriptor staleness.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from devices.base import DeviceError
from devices.bias_channel import BiasChannel
from devices.intensity_scope_ch import ScopeChannelMonitor

from capabilities.model import (
    CapabilityDescriptor,
    FrameSource,
    HVSource,
    ReadableChannel,
    ReadbackPolicy,
    SafetyClass,
    SweepableParameter,
    TriggerSource,
    WaveformSource,
    slow_control_capability_id,
)

logger = logging.getLogger(__name__)

__all__ = [
    "WAVEGEN_PLAN_KEYS",
    "VerifyResult",
    "CapabilityBinding",
    "describe_capabilities",
    "motor_descriptors",
    "bias_descriptors",
    "wavegen_descriptors",
    "scope_descriptors",
    "camera_descriptors",
    "intensity_descriptors",
    "slow_control_descriptors",
]

# --------------------------------------------------------------------------- #
# §5.1 static vocabulary tables (never string munging)                         #
# --------------------------------------------------------------------------- #

#: capability_id → plan-grammar key inside ACQUIRE_WAVEFORM's
#: ``params["wavegen"]`` dict (§5.1: ids carry NO unit suffix — the unit lives
#: in the descriptor's ``unit`` field — while the plan grammar keeps its
#: suffixed keys).  This static table IS the §5.1 link between the two
#: vocabularies; ``tests/test_capability_registry.py`` pins its value set
#: equal to ``controller/scan_plan_validator.py::_KNOWN_WAVEGEN_KEYS`` (this
#: module may not import controller/, the test may).  Both sides are
#: permanent vocabulary (§5.2) — entries are never renamed or removed.
WAVEGEN_PLAN_KEYS: dict[str, str] = {
    "wavegen.frequency": "frequency_hz",
    "wavegen.pulse_width": "pulse_width_s",
    "wavegen.duty_cycle": "duty_cycle_pct",
    "wavegen.amplitude": "amplitude_V",
    "wavegen.offset": "offset_V",
}

# (capability_id, label, unit, static limits) for the wavegen sweepables — the
# same setters ScanController._apply_wavegen_settings forwards today (§11.1):
#   wavegen.frequency   -> WaveformGenerator.set_frequency
#   wavegen.pulse_width -> WaveformGenerator.set_pulse_width
#   wavegen.duty_cycle  -> WaveformGenerator.set_duty_cycle
#   wavegen.amplitude   -> WaveformGenerator.set_amplitude
#   wavegen.offset      -> WaveformGenerator.set_offset
# Static limits are only published where the DRIVER itself enforces a static
# bound: set_duty_cycle's broad 0.001–99.999 % sanity clamp (its docstring;
# the instrument enforces the tighter frequency-dependent envelope itself).
# The others have no static driver bound → limits=None (§5: None = no static
# limit; the §7.4 limits-None render rule is D4b's, not a model refusal).
_WAVEGEN_SWEEPABLES: tuple[tuple[str, str, str, tuple[float, float] | None], ...] = (
    ("wavegen.frequency", "Wavegen frequency", "Hz", None),
    ("wavegen.pulse_width", "Wavegen pulse width", "s", None),
    ("wavegen.duty_cycle", "Wavegen duty cycle", "%", (0.001, 99.999)),
    ("wavegen.amplitude", "Wavegen amplitude", "V", None),
    ("wavegen.offset", "Wavegen offset", "V", None),
)

# stage axis table: (capability_id, SoftwareLimits attribute stem, label).
_STAGE_AXES: tuple[tuple[str, str, str], ...] = (
    ("stage.x", "x", "Stage X"),
    ("stage.y", "y", "Stage Y"),
    ("stage.z", "z", "Stage Z"),
)


# --------------------------------------------------------------------------- #
# Per-device descriptor builders (§11.1 adapter table)                         #
# --------------------------------------------------------------------------- #


def motor_descriptors(motor) -> tuple[SweepableParameter, ...]:
    """``stage.x/y/z`` from a ``MotorStageBase`` (§11.1: wraps ``move_to`` /
    ``get_position`` / ``wait_until_ready`` / ``stop``).

    Limits come from :meth:`MotorStageBase.limits_user_frame` — the USER-frame
    envelope, never raw ``self.limits`` (§5.4) — which is pure arithmetic on
    constructor/config state (no I/O, LAW §2.4).  Per that method's docstring
    and §5.5, they MUST be re-derived after home/zero; the registry does so on
    every ``descriptors()`` call.
    """
    lim = motor.limits_user_frame()
    out: list[SweepableParameter] = []
    for capability_id, axis, label in _STAGE_AXES:
        limits: tuple[float, float] | None = None
        if lim is not None:
            limits = (
                float(getattr(lim, f"{axis}_min")),
                float(getattr(lim, f"{axis}_max")),
            )
        out.append(SweepableParameter(
            capability_id=capability_id,
            device_id="motor",
            transport_id="motor",
            label=label,
            safety_class=SafetyClass.MOTION,
            metadata={},
            unit="mm",
            limits=limits,
            resolution=None,        # backend step size is not published in v1
            settle_s=0.0,
            readback=ReadbackPolicy.NONE,
        ))
    return tuple(out)


def _bias_polarity(channel: BiasChannel) -> str | None:
    """Descriptor polarity, derived WITHOUT a live query (LAW §2.4).

    Only the in-class simulation paths are provably I/O-free (``IsegBiasSupply
    .get_polarity_ch`` issues ``:CONF:OUTP:POL?`` on real hardware), so a real
    supply derives ``None`` = unknown/fixed — the honest §5 answer at
    derivation time.  Descriptive only (§5.4); never policy.
    """
    driver = channel.driver
    if not bool(getattr(driver, "simulation", False)):
        return None
    try:
        polarity = channel.get_polarity()
    except Exception:                                    # noqa: BLE001
        return None
    return polarity if polarity in ("p", "n") else None


def _hv_descriptor(channel: BiasChannel, capability_id: str, label: str) -> HVSource:
    rng = channel.voltage_range_V
    limits: tuple[float, float] | None = None
    if rng is not None and abs(float(rng)) > 0:
        # voltage_range_V is the |V| setpoint ceiling BiasSupplyBase
        # .check_voltage_in_range enforces (a limit of 0/None means no clamp).
        bound = abs(float(rng))
        limits = (-bound, bound)
    return HVSource(
        capability_id=capability_id,
        device_id="bias_supply",     # §5.3 short key — identity, never the lock
        transport_id="bias_supply",  # one physical transport, one lock (§14.2)
        label=label,
        safety_class=SafetyClass.HV,
        metadata={},
        unit="V",
        limits=limits,
        resolution=None,
        settle_s=0.0,
        readback=ReadbackPolicy.NONE,
        polarity=_bias_polarity(channel),
        channel=int(channel.channel),
    )


def bias_descriptors(
    primary: BiasChannel, channels: tuple[BiasChannel, ...],
) -> tuple[HVSource, ...]:
    """``bias.voltage`` (primary-channel ROLE) + ``bias.ch{n}.voltage`` per
    non-primary physical channel (§14.2, Kaya-ratified 2026-07-13).

    * ``bias.voltage`` is NOT a channel-0 alias: the primary's physical index
      is config-chosen and rides first-class in ``HVSource.channel``.
    * Physical identity wins the mapping: the primary proxy object (and any
      proxy sharing its physical index) is published ONCE, as ``bias.voltage``
      — one physical channel is never two simultaneously-published ids.
    * All ``bias.*`` capabilities share ``transport_id="bias_supply"`` — the
      one shared driver transport, one lock (§6.1).
    """
    out: list[HVSource] = [
        _hv_descriptor(primary, "bias.voltage",
                       f"Bias voltage (primary, CH{int(primary.channel)})")
    ]
    for ch in channels:
        if ch is primary or int(ch.channel) == int(primary.channel):
            continue                     # §14.2: physical identity wins
        n = int(ch.channel)
        out.append(_hv_descriptor(ch, f"bias.ch{n}.voltage", f"Bias voltage CH{n}"))
    return tuple(out)


def wavegen_descriptors(wavegen) -> tuple[CapabilityDescriptor, ...]:
    """``wavegen.*`` sweepables + the ``wavegen.output`` :class:`TriggerSource`
    (§11.1), all EMITTING (§7.3: the wavegen drives the laser trigger).

    The setters never touch output state (normative, §7.4) — arming is the
    gated operation, and it stays hard-coded in ``ScanController
    ._acquire_core`` until P3 (§7.2 RESERVED ``emission_interlock`` route).
    """
    out: list[CapabilityDescriptor] = []
    for capability_id, label, unit, limits in _WAVEGEN_SWEEPABLES:
        out.append(SweepableParameter(
            capability_id=capability_id,
            device_id="waveform_generator",
            transport_id="waveform_generator",
            label=label,
            safety_class=SafetyClass.EMITTING,
            metadata={},
            unit=unit,
            limits=limits,
            resolution=None,
            settle_s=0.0,
            readback=ReadbackPolicy.NONE,
        ))
    out.append(TriggerSource(
        capability_id="wavegen.output",
        device_id="waveform_generator",
        transport_id="waveform_generator",
        label="Wavegen output (laser trigger)",
        safety_class=SafetyClass.EMITTING,
        metadata={},
    ))
    return tuple(out)


def scope_descriptors(scope) -> tuple[WaveformSource, ...]:
    """``scope.waveform`` (§11.1: wraps ``Oscilloscope.acquire`` /
    ``read_channel``).  Channel labels derive from the constructor-time
    ``n_channels`` attribute (all three scope backends carry it); labels are
    the generic 1-indexed ``ch{i}`` matching ``read_channel``'s convention.
    """
    n = getattr(scope, "n_channels", None)
    channels = tuple(f"ch{i}" for i in range(1, int(n) + 1)) if n else ()
    return (WaveformSource(
        capability_id="scope.waveform",
        device_id="scope",
        transport_id="scope",
        label="Scope waveform",
        safety_class=SafetyClass.BENIGN,
        metadata={},
        channels=channels,
    ),)


def camera_descriptors(camera) -> tuple[FrameSource, ...]:
    """``camera.frame`` (§11.1: wraps ``BlackflyCamera.get_frame`` /
    ``get_frame_with_meta``); frame shape is runtime info, not a field."""
    return (FrameSource(
        capability_id="camera.frame",
        device_id="camera",
        transport_id="camera",
        label="Camera frame",
        safety_class=SafetyClass.BENIGN,
        metadata={},
    ),)


def intensity_descriptors(monitor) -> tuple[ReadableChannel, ...]:
    """TWO honest channels, ``intensity.amplitude`` [V] + ``intensity.charge``
    [pC] (§5.4 — never one dishonest ``intensity.reading``), wrapping the
    proven ``IntensityMonitorBase.get_amplitude`` / ``get_charge``.

    §6.1 pass-through (normative worked example): ``ScopeChannelMonitor``
    reads through ``Oscilloscope.read_channel``, so the real transport lock is
    the SCOPE's — ``device_id="intensity_monitor"`` (honest provenance),
    ``transport_id="scope"`` (honest lock owner).  The ``isinstance`` dispatch
    is exactly what §6.1 licenses the adapter layer to do.
    """
    transport_id = ("scope" if isinstance(monitor, ScopeChannelMonitor)
                    else "intensity_monitor")
    common = dict(
        device_id="intensity_monitor",
        transport_id=transport_id,
        safety_class=SafetyClass.BENIGN,
        metadata={},
    )
    return (
        ReadableChannel(capability_id="intensity.amplitude",
                        label="Laser intensity amplitude", unit="V", **common),
        ReadableChannel(capability_id="intensity.charge",
                        label="Laser intensity charge", unit="pC", **common),
    )


def slow_control_descriptors(slow_control) -> tuple[CapabilityDescriptor, ...]:
    """One ``slow_control.<name>`` :class:`ReadableChannel` per configured
    channel (§11.1: wraps ``SlowControlChannel.read_with_status``).

    Ids come ONLY from :func:`capabilities.model.slow_control_capability_id`
    (§5.1.1) — the four grandfathered names map through the permanent alias
    table; an unmappable name raises ``ValueError`` here, so the registry
    FAILS CLOSED at build (§5.1.1 item 3, §11.4 item 5) instead of ever
    munging a name into a permanent id.  ``device_id``/``transport_id`` use
    the ``slow_control/<name>`` vocabulary (§5.3, the connect_all result
    keys); each channel is its own ``BaseDevice`` and its own transport.
    """
    out: list[CapabilityDescriptor] = []
    for ch in slow_control.channels:
        own = getattr(ch, "describe_capabilities", None)
        if callable(own):                       # §11.1: driver's own wins
            out.extend(own())
            continue
        short_key = f"slow_control/{ch.name}"
        out.append(ReadableChannel(
            capability_id=slow_control_capability_id(ch.name),
            device_id=short_key,
            transport_id=short_key,
            label=f"Slow control: {ch.name}",
            safety_class=SafetyClass.BENIGN,
            metadata={},
            unit=str(ch.unit),
        ))
    return tuple(out)


def _own_or(device, fallback) -> tuple[CapabilityDescriptor, ...]:
    """§11.1: a driver MAY implement ``describe_capabilities()`` directly
    (duck-typed, no new abstract method); it wins over the adapter table and
    is subject to the same no-I/O LAW §2.4."""
    own = getattr(device, "describe_capabilities", None)
    if callable(own):
        return tuple(own())
    return fallback(device)


def describe_capabilities(device_manager) -> tuple[CapabilityDescriptor, ...]:
    """Every v1 descriptor derivable from *device_manager*'s CURRENT device
    instances (§11.1) — pure data, derivation-time snapshots (§5.5), zero
    instrument I/O (LAW §2.4).

    *device_manager* is duck-typed (``controller/`` imports us, never the
    reverse — §2.3): only the documented attributes ``motor``, ``scope``,
    ``camera``, ``waveform_generator``, ``intensity_monitor``, ``bias_supply``,
    ``bias_channels``, ``slow_control`` are read.
    """
    dm = device_manager
    out: list[CapabilityDescriptor] = []
    out.extend(_own_or(dm.motor, motor_descriptors))
    bias_own = getattr(dm.bias_supply.driver, "describe_capabilities", None)
    if callable(bias_own):
        out.extend(bias_own())
    else:
        out.extend(bias_descriptors(dm.bias_supply, tuple(dm.bias_channels)))
    out.extend(_own_or(dm.waveform_generator, wavegen_descriptors))
    out.extend(_own_or(dm.scope, scope_descriptors))
    out.extend(_own_or(dm.camera, camera_descriptors))
    out.extend(_own_or(dm.intensity_monitor, intensity_descriptors))
    out.extend(slow_control_descriptors(dm.slow_control))
    return tuple(out)


# --------------------------------------------------------------------------- #
# §6 CapabilityBinding — staged lifecycle (D1b skeleton)                       #
# --------------------------------------------------------------------------- #


_VERIFY_STATUSES = ("measured", "skipped", "failed")


@dataclass(frozen=True)
class VerifyResult:
    """Result of :meth:`CapabilityBinding.verify_or_skip` (§6, §9).

    ``status`` ∈ {"measured", "skipped", "failed"}; ``value`` is the measured
    read-back or ``None``.  LAW (§9): a COMMANDED value is never labelled
    ``measured`` — ``value`` is only ever a genuine read-back.
    """

    status: str
    value: float | None

    def __post_init__(self) -> None:
        if self.status not in _VERIFY_STATUSES:
            raise ValueError(
                f"VerifyResult.status must be one of {_VERIFY_STATUSES}, "
                f"got {self.status!r}"
            )


class _TransportReservation:
    """Reservation token returned by :meth:`CapabilityBinding.reserve` (§6.1).

    Context manager AND explicit-``release()`` token; releasing twice is a
    no-op (idempotent bookkeeping, §6 ``release``).  It wraps ONE acquired
    hold of the driver's own ``transport_lock`` — never a parallel second
    lock (§6.1).
    """

    __slots__ = ("_lock", "_transport_id", "_released")

    def __init__(self, lock, transport_id: str) -> None:
        # The lock is ALREADY acquired by reserve(); this object only tracks
        # the release side.
        self._lock = lock
        self._transport_id = transport_id
        self._released = False

    @property
    def transport_id(self) -> str:
        return self._transport_id

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        """Drop the hold.  Idempotent; pure bookkeeping (§6 ``release``).

        Marks the token released only AFTER the lock release succeeded: a
        cross-thread release attempt raises ``RuntimeError`` (RLock ownership)
        and MUST leave the token live, so the owning thread's own context
        manager still releases the real hold — never a silently leaked lock.
        """
        if self._released:
            return
        self._lock.release()        # may raise RuntimeError to a non-owner
        self._released = True

    def __enter__(self) -> "_TransportReservation":
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()


class CapabilityBinding:
    """Runtime handle driving exactly ONE capability (§6) — obtained from
    ``CapabilityRegistry.binding()``, never serialised (LAW §3).

    Lifecycle::

        reserve → prepare → apply → wait_settled → verify_or_skip → release | abort

    D1b SKELETON scope: ``reserve``/``release`` (transport reservation, §6.1),
    fail-closed ``prepare``, honest ``verify_or_skip``, and the ``abort``
    fail-safe delegation are functional; ``apply`` and ``wait_settled`` raise
    ``NotImplementedError`` until the P1 pilot wires the real setters (§11.3)
    — no binding is connected to a live setter in this beat.

    LAWS carried by this class (spec §6, §6.2, §15):

    * Constructing or reserving a binding changes NO instrument state — no
      auto-connect, auto-home, auto-HV-enable, and never restoring a previous
      setpoint.
    * **Per-command reservation.**  A reservation covers ONE command exchange
      (or one short atomic multi-set on the same transport).  It is NEVER
      held across ``ramp_to``'s step loop, ``wait_until_ready``-class
      readiness polling, any dwell, or any user interaction (a modal
      confirmation happens BEFORE reserve).  The lifecycle re-reserves per
      exchange — one reservation never spans apply→wait_settled→verify.
    * **STOP/abort/fail-safe are NEVER subject to the reservation** (§6.2):
      :meth:`abort` neither takes nor waits on it.
    * **No second kill path** (§5.4, §6): ``abort`` DELEGATES to the same
      driver methods every existing fail-safe path already uses (the
      ``ScanController._bias_failsafe`` / ``_motor_stop_safe`` discipline);
      the executor's finally-based fail-safe remains the home of the
      fail-safe — ``abort`` is an additional idempotent entry, never a
      replacement, and a clean finish still runs the executor's fail-safe.
    """

    def __init__(self, descriptor: CapabilityDescriptor, target, transport_lock) -> None:
        if not isinstance(descriptor, CapabilityDescriptor):
            raise TypeError(
                f"descriptor must be a CapabilityDescriptor, got "
                f"{type(descriptor).__name__}"
            )
        self._descriptor = descriptor
        self._target = target
        self._transport_lock = transport_lock
        self._reservations: list[_TransportReservation] = []

    # -- identity ---------------------------------------------------------- #

    @property
    def descriptor(self) -> CapabilityDescriptor:
        """The descriptor in effect when this binding was constructed (§5.5:
        provenance snapshots THIS, never the binding — LAW §3)."""
        return self._descriptor

    @property
    def target(self):
        """The device object the binding drives (driver, proxy, or channel)."""
        return self._target

    @property
    def transport_lock(self):
        """The §6.1 reservation unit — ``is``-identical to the lock the owning
        driver's own I/O acquires, resolved through
        ``CapabilityRegistry.transport_lock_for`` at construction (the ONE
        resolver; no second resolution path)."""
        return self._transport_lock

    # -- lifecycle ----------------------------------------------------------#

    def reserve(self, timeout_s: float = 5.0) -> _TransportReservation:
        """Acquire the transport reservation for ONE command exchange (§6.1).

        MUST take a positive timeout (enforced).  Returns a context-manager
        token.  LAW (§6.2): never hold it across a blocking multi-step driver
        loop (ramp/readiness-poll/dwell) or a user-interaction wait.
        """
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) \
                or not timeout_s > 0:
            raise ValueError(
                f"reserve() requires a positive timeout_s (§6.1), got {timeout_s!r}"
            )
        acquired = self._transport_lock.acquire(timeout=float(timeout_s))
        if not acquired:
            raise DeviceError(
                f"transport {self._descriptor.transport_id!r} reservation "
                f"timed out after {timeout_s} s (capability "
                f"{self._descriptor.capability_id!r})"
            )
        token = _TransportReservation(
            self._transport_lock, self._descriptor.transport_id
        )
        self._reservations.append(token)
        return token

    def prepare(self, value) -> float:
        """Validate *value* against descriptor limits AND the driver's own
        runtime gates; fail closed BEFORE anything is sent (§6).  No
        state-changing instrument I/O (read-only/pure checks only).

        Returns the validated float.  Command pre-computation lands with the
        P1 pilot alongside ``apply``.
        """
        d = self._descriptor
        if not isinstance(d, SweepableParameter):
            raise TypeError(
                f"{d.capability_id!r} is not a settable capability "
                "(no SET surface, §5.4)"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(
                f"prepare() value must be a real number, got {type(value).__name__}"
            )
        v = float(value)
        if math.isnan(v):
            raise ValueError("prepare() value must not be NaN")
        if d.limits is not None:
            lo, hi = d.limits
            if not lo <= v <= hi:
                raise ValueError(
                    f"{d.capability_id}: value {v!r} outside descriptor limits "
                    f"[{lo}, {hi}] — refusing before anything is sent (§6)"
                )
        # Driver runtime gates stay AUTHORITATIVE over the (possibly stale)
        # descriptor snapshot (§5.5) — re-check against the live gate state.
        if isinstance(d, HVSource):
            self._target.check_voltage_in_range(v)      # pure check, no I/O
        elif d.capability_id in ("stage.x", "stage.y", "stage.z"):
            axis = d.capability_id.rpartition(".")[2]
            lim = self._target.limits_user_frame()      # pure arithmetic
            if lim is not None:
                lo = float(getattr(lim, f"{axis}_min"))
                hi = float(getattr(lim, f"{axis}_max"))
                if not lo <= v <= hi:
                    raise ValueError(
                        f"{d.capability_id}: value {v!r} outside the CURRENT "
                        f"user-frame envelope [{lo}, {hi}] (§5.5 re-check)"
                    )
        return v

    def apply(self, value, *, shaping=None):
        """P1 pilot territory (§11.3) — NOT wired in D1b.

        Contract it will honour (§6): ``HVSource`` routes through the
        shaped-ramp path (``BiasSupplyBase.ramp_to`` semantics, plan-vocabulary
        shaping keys ``"ramp_step_V"`` / ``"ramp_delay_s"``; missing shaping =
        driver default, byte-identical to ``ScanController._ramp_bias``);
        stage axes route through ``MotorStageBase.move_to``; a capability with
        no shaping semantics raises on ``shaping is not None``.  Entry is the
        DA1 "command-issued" timing event.
        """
        raise NotImplementedError(
            "CapabilityBinding.apply is wired by the P1 pilot (spec §11.3); "
            "D1b ships the lifecycle skeleton only"
        )

    def wait_settled(self, timeout_s: float):
        """P1 pilot territory (§11.3) — NOT wired in D1b.

        Contract it will honour (§6): motion waits on driver readiness
        (``MotorStageBase.wait_until_ready`` semantics) then dwells the
        effective settle (§8, plan wins); LAW — the executor MUST NOT begin an
        acquisition before this returns (the D1-exit delayed-apply test on
        ``SimulatedMotorStage`` lands with the pilot); timeout raises a
        ``DeviceError``-class failure → executor fail-safe (safety rule 5).
        """
        raise NotImplementedError(
            "CapabilityBinding.wait_settled is wired by the P1 pilot (spec "
            "§11.3); D1b ships the lifecycle skeleton only"
        )

    def verify_or_skip(self) -> VerifyResult:
        """Best-effort read-back stage (§9).  Never raises on a mismatch,
        never blocks the run: it records; policy stays with the executor.

        D1b: every v1 descriptor declares ``ReadbackPolicy.NONE``, so this
        honestly returns ``skipped``.  Per-capability readers (one read-back
        inside their own per-command reservation) are wired with the P1
        pilot; until then BEST_EFFORT also degrades to ``skipped`` — a value
        is NEVER fabricated (LAW §9: commanded is never labelled measured).
        """
        d = self._descriptor
        if not isinstance(d, SweepableParameter):
            return VerifyResult(status="skipped", value=None)
        if d.readback is ReadbackPolicy.NONE:
            return VerifyResult(status="skipped", value=None)
        # TODO(P1): BEST_EFFORT readers ride the pilot (§11.3).
        return VerifyResult(status="skipped", value=None)

    def release(self) -> None:
        """Normal terminal (§6): drop any reservation tokens this binding
        still holds.  Pure bookkeeping; touches no instrument state;
        idempotent."""
        while self._reservations:
            token = self._reservations.pop()
            try:
                token.release()
            except RuntimeError:
                # The token belongs to another thread's hold — its own
                # context manager releases it; bookkeeping must not raise.
                logger.debug("release(): token owned by another thread, skipped")

    def abort(self) -> None:
        """Fault terminal (§6): return the capability to a safe idle by
        DELEGATING to the existing driver fail-safe methods.

        LAWS: callable from any stage, idempotent, NEVER raises, NEVER
        subject to the transport reservation (§6.2 — it neither takes nor
        waits on it; motor ``stop()`` is lock-free by driver contract), and
        introduces NO second kill path — the actions below are exactly
        ``ScanController._bias_failsafe`` (ramp to 0 then output-off, SEPARATE
        tries so the safety-critical output-off runs even if the ramp raises)
        and ``_motor_stop_safe`` (best-effort ``stop()``).  The executor's
        finally-based fail-safe remains in charge on every exit path,
        including clean finishes; this is an additional entry to the same
        path, never its new home (§6 LAW).
        """
        d, target = self._descriptor, self._target
        try:
            if isinstance(d, HVSource):
                # Mirror ScanController._bias_failsafe: separate tries, same
                # driver methods, same shape.  A ramp to zero never energises
                # an idle channel (BiasSupplyBase.ramp_to SAFETY docstring).
                try:
                    target.ramp_to(0.0, step_V=20.0, delay_s=0.05)
                except Exception:                        # noqa: BLE001
                    logger.warning("abort(): bias ramp-down failed", exc_info=True)
                try:
                    target.output_off()
                except Exception:                        # noqa: BLE001
                    logger.warning("abort(): bias output-off failed", exc_info=True)
            elif isinstance(d, TriggerSource):
                try:
                    target.output_off()
                except Exception:                        # noqa: BLE001
                    logger.warning("abort(): trigger output-off failed", exc_info=True)
            elif isinstance(d, SweepableParameter) \
                    and d.capability_id.partition(".")[0] == "stage":
                try:
                    target.stop()                        # lock-free by contract
                except Exception:                        # noqa: BLE001
                    logger.warning("abort(): motor stop failed", exc_info=True)
            # READ-operation producers (waveform/frame/readable): no state to
            # return to safe idle.
        finally:
            self.release()
