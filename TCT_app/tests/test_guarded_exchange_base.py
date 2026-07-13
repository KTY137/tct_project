"""Stage-G0 contract for the guarded-exchange base machinery (no hardware, no I/O).

Covers the additive base additions in ``devices/base.py`` described by
``docs/design/guarded_exchange.md`` §3/§5-§6:

  * the T1 helper ``_guarded_exchange`` takes ``transport_lock`` around exactly
    one primitive and releases it (recorder pattern — lock ownership recorded
    AT CALL TIME, as in tests/test_motor_transport_lock.py);
  * the T1g helper ``_guarded_group`` holds the lock across a whole bounded
    group and excludes other threads for its duration;
  * the T3 helper ``_probe_exchange`` returns the busy sentinel WITHOUT blocking
    when the transport is held elsewhere, and runs the primitive under the lock
    when it is free;
  * re-entrancy — a T1 exchange inside a held reservation works (RLock);
  * the ``__init_subclass__`` override detector REGISTERS the current drivers'
    overrides while firing ZERO warnings for them (they are all unconverted,
    which is legal until G1/G2), and it is NON-VACUOUS: a synthetic base that
    OWNS a guarded method makes an overriding subclass warn now / raise at G4.

Nothing here wires an existing driver through the helpers — that is G1/G2.
"""
import threading
import warnings

import pytest

from devices import base as base_mod
from devices.base import (
    BaseDevice,
    GuardedExchangeWarning,
    guarded_exchange_registry,
    _scan_guarded_overrides,
)

# The current, unconverted drivers.  Importing them runs their
# ``__init_subclass__`` at collection time — which must not warn (asserted
# below) and populates the migration registry.
from devices.motor_grbl import GRBLMotorStage
from devices.motor_pi import PIMotorStage
from devices.motor_simulated import SimulatedMotorStage
from devices.bias_supply_simulated import SimulatedBiasSupply
from devices.bias_supply_iseg import IsegBiasSupply
from devices.bias_supply_keithley import KeithleyBiasSupply

CURRENT_DRIVERS = [
    GRBLMotorStage, PIMotorStage, SimulatedMotorStage,
    SimulatedBiasSupply, IsegBiasSupply, KeithleyBiasSupply,
]


def held_by_this_thread(lock) -> bool:
    """True if *lock* (an RLock) is currently owned by the calling thread."""
    is_owned = getattr(lock, "_is_owned", None)
    assert is_owned is not None, "transport_lock must be re-entrant (RLock)"
    return bool(is_owned())


def run_with_timeout(fn, timeout: float = 5.0) -> bool:
    """Run *fn* in a daemon thread; return True if it finished in time."""
    done = threading.Event()
    err: list[BaseException] = []

    def _run():
        try:
            fn()
        except BaseException as exc:      # noqa: BLE001 — surfaced below
            err.append(exc)
        finally:
            done.set()

    threading.Thread(target=_run, daemon=True).start()
    finished = done.wait(timeout)
    if err:
        raise err[0]
    return finished


class _PlainDevice(BaseDevice):
    """Minimal concrete BaseDevice — its transport_lock is the default io_lock."""

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...


class _Recorder:
    """A fake exchange primitive that records lock ownership AT CALL TIME.

    The recorder pattern from tests/test_motor_transport_lock.py's
    ``LockWatchingSerial``: whether the transport lock was held by the calling
    thread is captured at the moment the primitive actually runs — the only
    place a "does it lock?" claim can be checked honestly.
    """

    def __init__(self, dev, ret="R"):
        self._dev = dev
        self._ret = ret
        self.calls = 0
        self.held_at_call: list[bool] = []
        self.args = None
        self.kwargs = None

    def __call__(self, *args, **kwargs):
        self.calls += 1
        self.held_at_call.append(held_by_this_thread(self._dev.transport_lock))
        self.args = args
        self.kwargs = kwargs
        return self._ret


# --------------------------------------------------------------------------- #
# T1 — _guarded_exchange                                                        #
# --------------------------------------------------------------------------- #

class TestGuardedExchangeT1:
    def test_holds_the_lock_around_the_primitive_and_releases_after(self):
        dev = _PlainDevice(simulation=True)
        rec = _Recorder(dev, ret="ok")

        assert not held_by_this_thread(dev.transport_lock)   # free before
        result = dev._guarded_exchange(rec, 1, 2, key="v")

        assert result == "ok"
        assert rec.calls == 1, "primitive never ran — the test would be vacuous"
        assert rec.held_at_call == [True], "lock was not held while the primitive ran"
        assert rec.args == (1, 2) and rec.kwargs == {"key": "v"}, "args not forwarded"
        assert not held_by_this_thread(dev.transport_lock), "lock not released after"

    def test_releases_the_lock_even_when_the_primitive_raises(self):
        dev = _PlainDevice(simulation=True)

        def _boom():
            raise RuntimeError("primitive failed")

        with pytest.raises(RuntimeError):
            dev._guarded_exchange(_boom)
        assert not held_by_this_thread(dev.transport_lock), (
            "lock leaked when the primitive raised — later exchanges would deadlock"
        )

    def test_is_reentrant_inside_a_held_reservation(self):
        """Re-entrancy (RLock): a caller holding transport_lock (a reservation)
        may run a T1 exchange, which re-acquires on the same thread."""
        dev = _PlainDevice(simulation=True)
        rec = _Recorder(dev)

        def _reserve_then_exchange():
            with dev.transport_lock:                     # e.g. a capability reservation
                out = dev._guarded_exchange(rec)          # re-acquires the same RLock
                assert out == "R"
                assert held_by_this_thread(dev.transport_lock)
            assert not held_by_this_thread(dev.transport_lock)

        assert run_with_timeout(_reserve_then_exchange, timeout=5.0), (
            "guarded exchange deadlocked against a held reservation — lock not re-entrant"
        )
        assert rec.held_at_call == [True]                 # ran under the (re-entered) lock


# --------------------------------------------------------------------------- #
# T1g — _guarded_group                                                          #
# --------------------------------------------------------------------------- #

class TestGuardedGroupT1g:
    def test_holds_the_lock_across_every_exchange_in_the_group(self):
        dev = _PlainDevice(simulation=True)
        r1, r2, r3 = _Recorder(dev), _Recorder(dev), _Recorder(dev)

        with dev._guarded_group():
            r1()
            r2()
            r3()
            assert held_by_this_thread(dev.transport_lock)

        # Every primitive ran (non-vacuity) and every one ran under the held lock.
        assert [r.calls for r in (r1, r2, r3)] == [1, 1, 1]
        assert [r.held_at_call for r in (r1, r2, r3)] == [[True], [True], [True]]
        assert not held_by_this_thread(dev.transport_lock), "group did not release the lock"

    def test_excludes_another_thread_for_the_whole_group(self):
        """The atomic property: while the group is held, no other thread can take
        the transport — so nothing can interleave between the group's exchanges."""
        dev = _PlainDevice(simulation=True)
        foreign_got_lock: list[bool] = []

        def _foreign():
            got = dev.transport_lock.acquire(blocking=False)
            foreign_got_lock.append(got)
            if got:
                dev.transport_lock.release()

        with dev._guarded_group():
            t = threading.Thread(target=_foreign)
            t.start()
            t.join(timeout=2.0)

        assert foreign_got_lock == [False], (
            "another thread acquired the transport mid-group — the group is not atomic"
        )


# --------------------------------------------------------------------------- #
# T3 — _probe_exchange                                                          #
# --------------------------------------------------------------------------- #

class TestProbeExchangeT3:
    def test_runs_the_primitive_under_the_lock_when_free(self):
        dev = _PlainDevice(simulation=True)
        rec = _Recorder(dev, ret="ALIVE")

        out = dev._probe_exchange(rec, busy_result="BUSY")

        assert out == "ALIVE"
        assert rec.calls == 1, "probe never ran the primitive — test is vacuous"
        assert rec.held_at_call == [True], "probe ran the primitive without the lock"
        assert not held_by_this_thread(dev.transport_lock), "probe did not release the lock"

    def test_returns_busy_without_blocking_when_lock_held_elsewhere(self):
        dev = _PlainDevice(simulation=True)
        rec = _Recorder(dev, ret="ALIVE")
        holder_has_lock = threading.Event()
        release = threading.Event()

        def _hold():
            with dev.transport_lock:
                holder_has_lock.set()
                release.wait(timeout=5.0)

        holder = threading.Thread(target=_hold, daemon=True)
        holder.start()
        assert holder_has_lock.wait(timeout=2.0), "holder never took the lock"

        result_box: list[str] = []

        def _probe():
            result_box.append(dev._probe_exchange(rec, busy_result="BUSY"))

        try:
            # If the probe blocked on the busy transport it would never finish
            # (the holder only releases after this returns) — run_with_timeout
            # turns that regression into an assertion instead of a 60 s hang.
            assert run_with_timeout(_probe, timeout=1.0), (
                "probe blocked on a busy transport — T3 must be non-contending"
            )
        finally:
            release.set()
            holder.join(timeout=2.0)

        assert result_box == ["BUSY"], "probe did not report the busy sentinel"
        assert rec.calls == 0, "probe ran the primitive despite a busy transport"


# --------------------------------------------------------------------------- #
# Override detector — REGISTRATION now, warn/raise on base-owned overrides      #
# --------------------------------------------------------------------------- #

class TestOverrideDetectorCurrentDrivers:
    def test_scanning_current_drivers_fires_no_guarded_exchange_warning(self):
        """Re-running the detector on every current driver class emits zero
        guarded-exchange warnings — they are all unconverted, which is legal
        until G1/G2 (no base owns any guarded method yet)."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for cls in CURRENT_DRIVERS:
                _scan_guarded_overrides(cls)

        ge = [w for w in caught if issubclass(w.category, GuardedExchangeWarning)]
        assert ge == [], (
            "current (unconverted) drivers fired guarded-exchange warnings: "
            f"{[str(w.message) for w in ge]}"
        )

    def test_subclassing_and_instantiating_current_drivers_fires_no_warning(self):
        """The note's proof: subclassing / instantiating the existing driver
        classes must not warn — even a fresh subclass that RE-overrides a
        candidate method (legal in G0)."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            class _SubPI(PIMotorStage):
                pass

            class _SubSim(SimulatedMotorStage):
                def move_to(self, x_mm, y_mm, z_mm) -> None:   # re-override: legal in G0
                    ...

            class _SubBias(SimulatedBiasSupply):
                pass

            PIMotorStage(simulation=True)
            SimulatedMotorStage(simulation=True)
            SimulatedBiasSupply(simulation=True)
            GRBLMotorStage(serial_port="MOCK", simulation=True, home_to_center=False)

        ge = [w for w in caught if issubclass(w.category, GuardedExchangeWarning)]
        assert ge == [], (
            f"subclassing/instantiating current drivers warned: "
            f"{[str(w.message) for w in ge]}"
        )

    def test_registry_catalogues_the_current_drivers_overrides(self):
        """REGISTRATION is the G0 detector's real deliverable: the migration
        worklist.  It must be NON-VACUOUS — the concrete drivers appear with
        the real public exchange methods they still carry."""
        reg = guarded_exchange_registry()

        assert "move_to" in reg.get("PIMotorStage", frozenset())
        assert "get_position" in reg.get("PIMotorStage", frozenset())
        assert "move_to" in reg.get("SimulatedMotorStage", frozenset())
        assert "set_voltage" in reg.get("SimulatedBiasSupply", frozenset())
        assert "read" in reg.get("SimulatedBiasSupply", frozenset())
        # stop() is T2 (a LAW) and is deliberately NOT a governed candidate, so
        # a driver overriding stop must never be catalogued as an override.
        assert "stop" not in reg.get("PIMotorStage", frozenset())
        assert "stop" not in reg.get("SimulatedMotorStage", frozenset())


class TestOverrideDetectorNonVacuity:
    """A detector that can never fire proves nothing.  These pin that it DOES
    fire once a base actually OWNS a guarded method (as G1/G2 will declare)."""

    def test_owner_base_itself_is_not_flagged_but_an_overriding_subclass_warns(self):
        # Defining the OWNER base must not warn — it legitimately provides the
        # public template and declares ownership of it.
        with warnings.catch_warnings(record=True) as owner_caught:
            warnings.simplefilter("always")

            class _OwningMotorBase(BaseDevice):
                _guarded_owned_methods = frozenset({"move_to"})

                def connect(self) -> None: ...
                def disconnect(self) -> None: ...
                def move_to(self, x_mm, y_mm, z_mm) -> None:   # the base template
                    ...

        owner_ge = [w for w in owner_caught
                    if issubclass(w.category, GuardedExchangeWarning)]
        assert owner_ge == [], "the owner base was wrongly flagged for defining its own template"

        # A subclass that RE-overrides the base-owned public method IS the
        # violation the detector exists to catch.
        with warnings.catch_warnings(record=True) as sub_caught:
            warnings.simplefilter("always")

            class _UnconvertedMotor(_OwningMotorBase):
                def move_to(self, x_mm, y_mm, z_mm) -> None:   # overrides base-owned
                    ...

        sub_ge = [w for w in sub_caught
                  if issubclass(w.category, GuardedExchangeWarning)]
        assert len(sub_ge) == 1, f"expected exactly one warning, got {len(sub_ge)}"
        msg = str(sub_ge[0].message)
        assert "move_to" in msg and "_UnconvertedMotor" in msg

    def test_g4_flip_makes_the_same_override_raise_at_class_definition_time(
        self, monkeypatch
    ):
        class _OwningBiasBase(BaseDevice):
            _guarded_owned_methods = frozenset({"read"})

            def connect(self) -> None: ...
            def disconnect(self) -> None: ...
            def read(self):   # the base template
                ...

        # Flip the module-level mode as the G4 stage will (per-family), and the
        # override becomes a hard class-definition-time error.
        monkeypatch.setattr(base_mod, "GUARDED_EXCHANGE_MODE", "raise")
        with pytest.raises(TypeError, match="read"):
            class _UnconvertedBias(_OwningBiasBase):
                def read(self):   # overrides base-owned -> raises at G4
                    ...


# --------------------------------------------------------------------------- #
# No T2 base helper exists — the LAW is enforced by SHAPE                        #
# --------------------------------------------------------------------------- #

def test_there_is_deliberately_no_t2_escape_helper_on_the_base():
    """A stop / abort path must never be lured into a lock-taking helper, so the
    base offers NO T2 escape helper for it to reach for (design note §3, T2).
    Only the three non-escape tiers exist."""
    assert hasattr(BaseDevice, "_guarded_exchange")
    assert hasattr(BaseDevice, "_guarded_group")
    assert hasattr(BaseDevice, "_probe_exchange")
    assert not hasattr(BaseDevice, "_escape_exchange"), (
        "an _escape_exchange helper is exactly the T2 lure the design forbids"
    )
