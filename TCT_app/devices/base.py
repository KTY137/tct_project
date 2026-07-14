import contextlib
import logging
import threading
import warnings
from abc import ABC, abstractmethod


class DeviceError(Exception):
    """Raised when a device operation fails."""


class GuardedExchangeWarning(UserWarning):
    """Emitted (Stage G0, WARNING mode) when a driver overrides a public
    exchange method that a base class has taken OWNERSHIP of as a guarded
    template method.

    In G0 no base owns any such method yet — the current drivers are all
    unconverted, which is the expected and legal state until G1/G2 — so this
    warning does not fire for any driver on disk today.  At Stage G4 the
    detector flips per family from *warning* to *raising* (``TypeError`` at
    class-definition time).  See the guarded-exchange staging in
    ``docs/design/guarded_exchange.md`` §5-§6.
    """


# --------------------------------------------------------------------------- #
# Guarded-exchange override detector (Stage G0 — WARNING mode).                #
#                                                                              #
# Structural transport serialisation for the device layer, staged non-breaking #
# per docs/design/guarded_exchange.md.  G0 is ADDITIVE ONLY: the machinery     #
# below changes no device behaviour and (by construction) warns zero times for #
# the unconverted drivers on disk.                                             #
# --------------------------------------------------------------------------- #

# Detector mode.  ``"warn"`` for stages G0..G3 (record + warn on an override of
# a base-OWNED guarded method); flipped to ``"raise"`` per family at G4, once
# every in-tree backend of that family is converted.  A module-level flag (not
# per-class) so the G4 flip is a one-line change and tests can exercise both
# modes around a try/finally.
GUARDED_EXCHANGE_MODE = "warn"

# The public exchange methods the guarded-exchange track governs, read from the
# per-device mapping tables in docs/design/guarded_exchange.md §4.  Overriding
# one of these is the NORMAL, LEGAL state of an unconverted driver in G0..G3 —
# it is RECORDED for migration visibility (which classes still carry their own
# public exchange body, i.e. still need converting) but NEVER warned about on
# its own.  Two families of method are deliberately EXCLUDED:
#   * ``stop`` (T2) — a LAW, not a template: a stop / abort / fail-safe path
#     must NEVER be routed through a lock-taking helper, so a driver overriding
#     ``stop`` must never be flagged (see ``_guarded_exchange`` for why there is
#     no T2 base helper at all).
#   * ``is_alive`` (T3) — a non-contending liveness probe drivers are meant to
#     override with a try-acquire; ``_probe_exchange`` is offered but not owned.
GUARDED_EXCHANGE_CANDIDATES = frozenset({
    # motors — docs/design/guarded_exchange.md §4.1
    "get_position", "is_moving", "at_limit_switch",
    "move_to", "move_relative", "home", "zero_position", "test_connection",
    # bias supplies — §4.2 (zero-arg + channel-aware surfaces)
    "set_voltage", "set_voltage_ch", "set_compliance", "set_compliance_ch",
    "enable_output", "output_on_ch", "output_off", "output_off_ch",
    "read", "read_ch", "ramp_to", "ramp_to_ch",
    "set_polarity", "set_polarity_ch",
    # scope / wavegen / camera — §4.3-4.5 (folded in at D2/G3)
    "acquire", "read_channel", "get_frame", "get_frame_with_meta",
})

# ``class -> frozenset(candidate method names defined in that class body)``.
# Populated by ``BaseDevice.__init_subclass__``.  This is the Stage-G0
# detector's real deliverable: a migration worklist, not state any runtime
# behaviour depends on.
_guarded_override_registry: "dict[type, frozenset[str]]" = {}


def guarded_exchange_registry() -> "dict[str, frozenset[str]]":
    """Read-only snapshot of the override registry, keyed by class qualname.

    ``{class_qualname: {overridden guarded-exchange method names}}`` — the
    catalogue of which classes still carry their own public exchange body (are
    not yet converted to the guarded base template).  G4 consults it to confirm
    a family is fully converted before flipping :data:`GUARDED_EXCHANGE_MODE`
    to ``"raise"``.
    """
    return {cls.__qualname__: names
            for cls, names in _guarded_override_registry.items()}


def _owned_guarded_methods(cls: type) -> "frozenset[str]":
    """Union of the guarded methods every *base* of *cls* has declared it OWNS.

    A base declares ownership via its OWN ``_guarded_owned_methods`` frozenset
    (each base's own declaration only — read from ``vars(base)``, never the
    inherited/accumulated value).  Empty for every class today because no family
    base has converted yet; a family base populates it in G1/G2 when it takes
    over the public method as a guarded template.
    """
    owned: set[str] = set()
    for base in cls.__mro__[1:]:
        owned |= set(vars(base).get("_guarded_owned_methods", ()))
    return frozenset(owned)


def _scan_guarded_overrides(cls: type) -> "frozenset[str]":
    """Register *cls*'s public-exchange-method overrides and enforce the mode.

    Two independent jobs:

    1. **Registration (always).** Record which governed exchange methods *cls*
       defines in its own body (``GUARDED_EXCHANGE_CANDIDATES`` ∩ ``vars(cls)``).
       This is legal for an unconverted driver and is never on its own a reason
       to warn — it only feeds the migration worklist.
    2. **Enforcement (warn now / raise at G4).** If *cls* overrides a method a
       BASE has taken ownership of (``_owned_guarded_methods``), that is the
       violation the track forbids.  No base owns anything in G0, so this fires
       zero times for the current drivers.

    Returns the set of registered (overridden) candidate names, so tests can
    assert non-vacuity.
    """
    own_defined = frozenset(
        name for name, value in vars(cls).items()
        if name in GUARDED_EXCHANGE_CANDIDATES and callable(value)
    )
    if own_defined:
        _guarded_override_registry[cls] = own_defined

    owned_by_bases = _owned_guarded_methods(cls)
    violations = sorted(
        name for name, value in vars(cls).items()
        if name in owned_by_bases and callable(value)
    )
    for name in violations:
        msg = (
            f"{cls.__qualname__} overrides base-owned guarded-exchange method "
            f"{name!r}: the base owns the public method as a guarded template, "
            f"so a converted driver must supply the '_do_*' primitive instead "
            f"of re-defining the public method. "
            f"See docs/design/guarded_exchange.md §5-§6."
        )
        if GUARDED_EXCHANGE_MODE == "raise":
            raise TypeError(msg)
        warnings.warn(msg, GuardedExchangeWarning, stacklevel=3)

    return own_defined


class BaseDevice(ABC):
    # Public exchange methods THIS class (or a base) OWNS as a guarded template
    # method.  Overriding an owned method is the guarded-exchange violation the
    # detector warns about now and raises on at G4.  Empty on BaseDevice; a
    # family base (MotorStageBase, BiasSupplyBase, …) populates its own copy
    # when it converts in G1/G2.  Left empty EVERYWHERE in G0, so the detector
    # warns zero times for the current drivers.
    _guarded_owned_methods: "frozenset[str]" = frozenset()

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        # Stage G0: record which public exchange methods this subclass still
        # overrides (migration worklist) and, in WARNING mode, flag any override
        # of a BASE-owned guarded method.  Additive: emits nothing for the
        # unconverted drivers on disk today.
        _scan_guarded_overrides(cls)

    def __init__(self, simulation: bool = False):
        self.simulation = simulation
        self._connected = False
        self.logger = logging.getLogger(type(self).__name__)
        # Serialises hardware I/O: GUI pollers and the scan thread share one
        # VISA/serial session per device, and interleaved query/reply pairs
        # garble each other.  Re-entrant so nested driver calls are fine.
        self.io_lock = threading.RLock()

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def transport_lock(self) -> "threading.RLock":
        """The one object a caller must hold for exclusive use of this
        device's transport (serial port, VISA session, SDK handle).

        Hold it to keep a *sequence* of driver calls free of interleaving —
        e.g. a capability reservation, or a query whose reply must not be
        picked up by another thread's read.  Per-exchange serialisation is
        already the driver's own job; this exposes the same lock so an outside
        caller can widen that guarantee without reaching into private state.

        Default: :attr:`io_lock`, which is what every driver's I/O takes.
        A driver that serialises its I/O on a *different* lock MUST override
        this to return that very lock (``GRBLMotorStage`` returns its
        ``_lock``).  A second, parallel lock over one transport is a lie: the
        caller holds one, the driver takes the other, and the exchanges
        interleave exactly as before.

        Contract for overrides:
          * ``is``-identical to the lock the driver's own I/O acquires,
          * re-entrant (a holder may call driver methods that lock again),
          * **never** acquired by an emergency-stop path — a locked ``stop()``
            would be queued behind the very move it must interrupt.
        """
        return self.io_lock

    def is_alive(self) -> bool:
        """Cheap link-liveness check, polled by the DeviceManager monitor.

        Default implementation trusts the ``connected`` flag (for drivers
        without a cheap probe).  Overrides should verify the physical link
        (e.g. an IEEE 488.2 ``*STB?``) and set ``_connected = False`` when it
        is gone, so a yanked cable can never keep showing a green flag.
        Must be fast, must not change instrument state, and must never block
        on the io_lock (skip the probe when the device is mid-conversation).
        """
        return self._connected

    # ------------------------------------------------------------------ #
    # Guarded-exchange tier helpers (Stage G0 — additive; no driver wires  #
    # through them yet, that is G1/G2).  The tiers are defined in           #
    # docs/design/guarded_exchange.md §3.                                   #
    # ------------------------------------------------------------------ #

    def _guarded_exchange(self, fn, *args, **kwargs):
        """T1 — one guarded exchange: run *fn* once under ``transport_lock``.

        The default tier (design note §3, T1): one command/query (or
        query+reply pair) on the transport.  The base takes the transport lock,
        runs exactly this one primitive, and releases before returning.  Run
        every gate (connected / homed / limits / range) and every bit of pure
        computation BEFORE calling this — never hold the transport across
        arithmetic or, ever, user interaction.

        Re-entrant by construction: ``transport_lock`` is an ``RLock``, so a
        caller already holding it — a capability reservation, or an enclosing
        :meth:`_guarded_group` — may call this and re-acquire harmlessly on the
        same thread.

        There is deliberately **NO base helper for a T2 escape** (stop / abort /
        fail-safe), and this docstring is the record of why.  A stop is a LAW,
        not a helper call: no lock, no reservation, and no gate may ever stand
        between the operator and a stop (design note §3, T2).  A base
        ``_escape_exchange`` — even one that only *sometimes* takes the lock (the
        bounded in-band form) — would be exactly the lure that LAW forbids: a
        stop primitive could reach for it and end up queued behind the very move
        it must interrupt.  So no such helper exists.  A stop path is
        hand-written per driver (a real-time out-of-band write, or a
        bounded-acquire-then-send-regardless in-band write) and pinned by that
        driver's own contract test; it must NEVER call :meth:`_guarded_exchange`,
        :meth:`_guarded_group`, or :meth:`_probe_exchange`.
        """
        with self.transport_lock:
            return fn(*args, **kwargs)

    @contextlib.contextmanager
    def _guarded_group(self):
        """T1g — atomic guarded group: hold ``transport_lock`` across a SHORT,
        BOUNDED, indivisible multi-exchange sequence (design note §3, T1g).

        Use for a handful of exchanges that must not be interleaved by another
        thread — the precedent is iseg's polarity switch, which holds the lock
        across status-check → confirm → relay-throw so nothing can energise the
        output between the check and the throw.  Allowed ONLY because it is
        short and bounded; **never** wrap a ramp, a motion wait, a settle loop,
        or any user interaction in it (that is the T4 slicing law — hold the
        lock per step, never across the loop)::

            with self._guarded_group():
                self._do_check_off()
                self._do_confirm()
                self._do_throw_relay()

        Re-entrant like :meth:`_guarded_exchange`; every ``_do_*`` inside the
        block runs under the one held lock.
        """
        with self.transport_lock:
            yield

    def _probe_exchange(self, fn, *, busy_result):
        """T3 — non-contending probe: try-acquire ``transport_lock``; if the
        transport is busy, return *busy_result* immediately instead of blocking
        (design note §3, T3).

        For liveness / health polls that must never stall behind in-flight
        traffic (``is_alive`` and friends).  A busy transport means the device
        is mid-conversation, so the honest fast answer is "presumed alive" —
        the caller supplies that as *busy_result*.  When the lock IS free, *fn*
        runs once under it and its result is returned.

        Contract: *fn* takes no arguments and performs at most one cheap,
        state-preserving exchange; it must not change instrument state.
        """
        if not self.transport_lock.acquire(blocking=False):
            return busy_result
        try:
            return fn()
        finally:
            self.transport_lock.release()

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...
