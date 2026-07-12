"""Driver-truth regressions: a driver must never claim a state it did not achieve.

Four fail-silent / fail-dishonest defects found in a standup review of the device
layer, pinned here so they cannot come back.  Every test is hardware-safe: fully
simulated stages and fake VISA sessions, no serial/VISA I/O, safe to run with real
instruments physically attached.

1. ``zero_position()`` faked ``_homed = True``.  Zeroing declares a USER ORIGIN; it
   is not a physical homing cycle.  Faking the flag let ``move_to`` issue absolute
   moves against a machine reference that was never established, and check soft
   limits against that same lie.

2. ``IsegBiasSupply.disconnect()`` wrapped the fail-safe ramp-down in
   ``except: pass`` and closed the socket regardless — a supply that refused to
   come down was abandoned ENERGIZED, silently.

3. ``read_ch()`` never read the channel status word, so a LATCHED hardware trip was
   invisible: the module switches the channel off on its own while the driver's
   local ``output_on`` flag stays stale-True.

4. ``set_channel_scale`` / ``set_timebase`` fired Tektronix SCPI at every vendor
   unconditionally (their siblings refuse), and ``read_settings()`` echoed the last
   *requested* v/div back as if it had been read off the instrument.
"""
from __future__ import annotations

import logging

import pytest

from devices.base import DeviceError
from devices.bias_supply_base import BiasReading
from devices.bias_supply_iseg import IsegBiasSupply
from devices.bias_supply_simulated import SimulatedBiasSupply
from devices.motor_base import MotorHomingError, Position, SoftwareLimits
from devices.motor_grbl import GRBLMotorStage
from devices.motor_simulated import SimulatedMotorStage
from devices.oscilloscope import Oscilloscope


# --------------------------------------------------------------------------- #
# 1. Zeroing establishes a user origin — it NEVER fakes machine home.          #
# --------------------------------------------------------------------------- #

_LIMITS = SoftwareLimits(x_min=0, x_max=235, y_min=0, y_max=235, z_min=0, z_max=250)


class TestZeroDoesNotHome:
    """zero_position() must not flip _homed on ANY backend."""

    def test_grbl_zero_on_unhomed_stage_does_not_claim_homed(self):
        m = GRBLMotorStage(simulation=True, home_to_center=False)
        m.limits = _LIMITS
        m.connect()
        assert not m.homed

        m.zero_position()                     # user origin only

        assert not m.homed, "zeroing must NEVER fabricate a homing reference"

    def test_grbl_move_after_unhomed_zero_is_refused(self):
        """The safety consequence: an un-homed zero+move path REFUSES to move."""
        m = GRBLMotorStage(simulation=True, home_to_center=False)
        m.limits = _LIMITS
        m.connect()
        m.zero_position()

        with pytest.raises(MotorHomingError):
            m.move_to(10.0, 10.0, 10.0)
        with pytest.raises(MotorHomingError):
            m.move_relative(1.0, 0.0, 0.0)

    def test_grbl_unhomed_zero_warns_loudly(self, caplog):
        m = GRBLMotorStage(simulation=True, home_to_center=False)
        m.limits = _LIMITS
        m.connect()
        with caplog.at_level(logging.WARNING, logger="GRBLMotorStage"):
            m.zero_position()
        msg = " ".join(r.getMessage() for r in caplog.records)
        assert "UN-HOMED" in msg

    def test_grbl_zero_after_home_keeps_homed_and_sets_origin(self):
        """The real GUI flow — home, drive somewhere, Zero Here — still works."""
        m = GRBLMotorStage(simulation=True, home_to_center=False)
        m.limits = _LIMITS
        m.connect()
        m.home()
        assert m.homed

        m.move_to(10.0, 20.0, 5.0)
        m.zero_position()

        assert m.homed, "a real homing cycle must survive a subsequent zero"
        # The current spot now reads as the origin...
        pos = m.get_position()
        assert (pos.x_mm, pos.y_mm, pos.z_mm) == pytest.approx((0.0, 0.0, 0.0))
        # ...and moves in the new user frame still work.
        m.move_to(1.0, 1.0, 1.0)

    def test_simulated_twin_has_the_same_contract(self):
        """The sim twin must not be more permissive than the real backend."""
        m = SimulatedMotorStage()
        m.connect()
        assert not m.homed

        m.zero_position()
        assert not m.homed

        with pytest.raises(MotorHomingError):
            m.move_to(1.0, 0.0, 0.0)

        m.home()                              # honest homing
        m.zero_position()
        assert m.homed
        m.move_to(1.0, 0.0, 0.0)              # now permitted


# --------------------------------------------------------------------------- #
# Fake iseg VISA session                                                       #
# --------------------------------------------------------------------------- #

class FakeIsegInst:
    """Minimal stand-in for the pyvisa resource the iseg driver holds.

    ``status`` is the value ``:READ:CHAN:STAT?`` reports.  ``fail_writes``
    makes every write raise, modelling a dead/refusing link on teardown.
    """

    def __init__(self, status: int = 0, fail_writes: bool = False,
                 meas_V: float = 0.0, meas_I: float = 0.0):
        self.status = status
        self.fail_writes = fail_writes
        self.meas_V = meas_V
        self.meas_I = meas_I
        self.writes: list[str] = []
        self.closed = False
        self.closed_after: list[str] = []      # writes seen at close() time

    def write(self, cmd: str) -> None:
        if self.fail_writes:
            raise OSError("VISA write failed: link down")
        self.writes.append(cmd)

    def query(self, cmd: str) -> str:
        c = cmd.upper()
        if ":READ:CHAN:STAT?" in c:
            return f"{self.status}"
        if ":MEAS:VOLT?" in c:
            return f"{self.meas_V:E}V"
        if ":MEAS:CURR?" in c:
            return f"{self.meas_I:E}A"
        return "0"

    def close(self) -> None:
        self.closed = True
        self.closed_after = list(self.writes)


def _live_iseg(inst: FakeIsegInst, *, channel: int = 0) -> IsegBiasSupply:
    """An iseg driver bound to a fake session, as if connect() had succeeded."""
    sup = IsegBiasSupply(visa_address="TCPIP0::10.0.0.1::10001::SOCKET",
                         channel=channel, voltage_range_V=2000.0, simulation=False)
    sup._inst = inst
    sup._connected = True
    return sup


# --------------------------------------------------------------------------- #
# 2. disconnect(): fail-safe, but never fail-SILENT.                           #
# --------------------------------------------------------------------------- #

class TestIsegDisconnectFailsLoud:
    def test_persistent_rampdown_failure_raises_instead_of_silent_close(self):
        """The defect: ramp-down failed, was swallowed, socket closed anyway."""
        inst = FakeIsegInst(fail_writes=True)
        sup = _live_iseg(inst)
        sup._chs(0)["output_on"] = True
        sup._chs(0)["setpoint_V"] = -300.0

        with pytest.raises(DeviceError, match="(?i)ramp-down failed|may still be energized"):
            sup.disconnect()

        # The link is still released (no leaked handle) — but LOUDLY, not silently.
        assert inst.closed
        assert sup.connected is False

    def test_failed_channel_keeps_truthful_state_not_a_fake_zero(self):
        """A channel we could NOT ramp down must not be recorded as 0 V / off."""
        inst = FakeIsegInst(fail_writes=True)
        sup = _live_iseg(inst)
        sup._chs(0)["output_on"] = True
        sup._chs(0)["setpoint_V"] = -300.0

        with pytest.raises(DeviceError):
            sup.disconnect()

        assert sup._chs(0)["output_on"] is True, \
            "must not claim an OFF it never achieved"
        assert sup._chs(0)["setpoint_V"] == -300.0

    def test_rampdown_is_retried_once_before_giving_up(self):
        """A single dropped frame must not condemn the teardown."""
        inst = FakeIsegInst()
        sup = _live_iseg(inst)
        sup._chs(0)["output_on"] = True

        calls = {"n": 0}
        real_write = sup._write

        def flaky(cmd: str) -> None:
            calls["n"] += 1
            if calls["n"] == 1:               # first write of the teardown fails
                raise OSError("dropped frame")
            real_write(cmd)

        sup._write = flaky                     # type: ignore[method-assign]
        sup.disconnect()                       # retry succeeds -> no raise

        assert sup._chs(0)["output_on"] is False
        assert inst.closed

    def test_link_is_closed_only_after_the_rampdown_attempt(self):
        """Ordering: the HV must be walked down BEFORE the socket goes away."""
        inst = FakeIsegInst()
        sup = _live_iseg(inst)
        sup._chs(0)["output_on"] = True
        sup._chs(0)["setpoint_V"] = -50.0

        sup.disconnect()

        assert inst.closed
        # The off-writes were already on the wire by the time close() ran.
        assert any("VOLT OFF" in w.upper() for w in inst.closed_after), \
            "socket closed before the channel was switched off"

    def test_offline_channel_is_not_switched_on_just_to_ramp_it_down(self):
        """Safety rule 1: teardown must never AUTO-ENABLE HV.

        The base ramp_to() turns the output ON when it is off (to ramp *to* the
        target), so the old disconnect path would enable HV on an idle channel
        just to walk it to zero.
        """
        inst = FakeIsegInst()
        sup = _live_iseg(inst)
        sup._chs(0)["output_on"] = False        # channel is idle

        sup.disconnect()

        assert not any("VOLT ON" in w.upper() for w in inst.writes), \
            "disconnect must never enable HV on an already-off channel"

    def test_every_touched_channel_is_torn_down(self):
        inst = FakeIsegInst()
        sup = _live_iseg(inst, channel=0)
        sup._chs(0)["output_on"] = True
        sup._chs(1)["output_on"] = True         # a secondary channel was used

        sup.disconnect()

        for ch in (0, 1):
            assert sup._chs(ch)["output_on"] is False
            assert any(f"(@{ch})" in w and "VOLT OFF" in w.upper()
                       for w in inst.writes), f"CH{ch} was never switched off"

    def test_clean_disconnect_does_not_raise(self):
        inst = FakeIsegInst()
        sup = _live_iseg(inst)
        sup.disconnect()                        # must be quiet on the happy path
        assert inst.closed and sup.connected is False


class TestIsegOutputOffNeverLies:
    def test_failed_output_off_write_does_not_claim_off(self):
        """output_off stays non-raising (abort paths rely on it) — but a failed
        write must not silently clear the local ON flag."""
        inst = FakeIsegInst(fail_writes=True)
        sup = _live_iseg(inst)
        sup._chs(0)["output_on"] = True

        sup.output_off_ch(0)                    # fail-safe: must NOT raise

        assert sup._chs(0)["output_on"] is True, \
            "a failed output-off must not report the channel as OFF"


class TestSimulatedTwinTeardown:
    def test_sim_disconnect_ramps_down_and_switches_off(self):
        sup = SimulatedBiasSupply(voltage_range_V=1000.0)
        sup.connect()
        sup.ramp_to(-100.0, step_V=25.0, delay_s=0.0)
        assert sup.output_is_on_ch(0) is True

        sup.disconnect()

        assert sup.output_is_on_ch(0) is False
        assert sup.setpoint_V == 0.0
        assert sup.connected is False

    def test_sim_disconnect_on_never_connected_supply_is_safe(self):
        SimulatedBiasSupply().disconnect()      # must not raise


# --------------------------------------------------------------------------- #
# 3. read_ch() surfaces the channel status word / latched trips.               #
#    Bit map: docs/research/iseg_polarity_scpi.md §6 (cited iseg manual).      #
# --------------------------------------------------------------------------- #

_IS_ON          = 0x8       # bit 3
_CONST_VOLTAGE  = 0x80      # bit 7
_CURRENT_TRIP   = 0x2000    # bit 13
_ARC_ERROR      = 0x200     # bit 9
_EMERGENCY_OFF  = 0x20      # bit 5


class TestIsegTripBitsAreSurfaced:
    def test_healthy_channel_reports_no_trip_and_hardware_on(self):
        # 152 = bits 7+4+3 — the worked example from the cited manual table.
        inst = FakeIsegInst(status=_IS_ON | _CONST_VOLTAGE | 0x10, meas_V=-300.0)
        sup = _live_iseg(inst)
        sup._chs(0)["output_on"] = True

        r = sup.read_ch(0)

        assert isinstance(r, BiasReading)
        assert r.status_word == 152
        assert r.tripped is False
        assert r.output_on_hw is True

    def test_latched_current_trip_is_visible_on_the_reading(self):
        """THE defect: the module tripped off, the driver kept believing HV was on."""
        inst = FakeIsegInst(status=_CURRENT_TRIP, meas_V=0.0)
        sup = _live_iseg(inst)
        sup._chs(0)["output_on"] = True          # stale-True local flag

        r = sup.read_ch(0)

        assert r.tripped is True
        assert r.output_on_hw is False           # hardware says OFF...
        assert sup._chs(0)["output_on"] is True  # ...while the local flag lied
        assert r.status_word == _CURRENT_TRIP

    @pytest.mark.parametrize("bit", [_CURRENT_TRIP, _ARC_ERROR, _EMERGENCY_OFF])
    def test_each_cited_protective_fault_bit_trips(self, bit):
        sup = _live_iseg(FakeIsegInst(status=bit))
        assert sup.read_ch(0).tripped is True

    def test_transient_arc_bit_alone_is_not_escalated_to_a_trip(self):
        """Bit 1 'Is Arc' is a transient detection, not a latched fault — it is
        left in the raw word rather than being invented into a trip."""
        sup = _live_iseg(FakeIsegInst(status=0x2 | _IS_ON))
        r = sup.read_ch(0)
        assert r.tripped is False
        assert r.status_word == (0x2 | _IS_ON)   # still visible to the caller

    def test_unreadable_status_is_unknown_not_healthy(self):
        """A status word we could not read must NOT be reported as 'no trip'."""
        class NoStatus(FakeIsegInst):
            def query(self, cmd: str) -> str:
                if ":READ:CHAN:STAT?" in cmd.upper():
                    raise OSError("status query timed out")
                return super().query(cmd)

        sup = _live_iseg(NoStatus())
        r = sup.read_ch(0)

        assert r.tripped is None, "unknown must not be conflated with healthy"
        assert r.output_on_hw is None
        assert r.status_word is None
        # The V/I read itself still succeeded — a status hiccup must not break it.
        assert r.voltage_V == pytest.approx(0.0)

    def test_read_routes_through_read_ch_so_the_primary_channel_is_covered(self):
        sup = _live_iseg(FakeIsegInst(status=_CURRENT_TRIP))
        assert sup.read().tripped is True

    def test_reading_defaults_keep_other_backends_working(self):
        """The three new fields are additive: a 3-arg construction still works."""
        r = BiasReading(voltage_V=-1.0, current_A=1e-9, compliant=False)
        assert r.status_word is None and r.tripped is None and r.output_on_hw is None


# --------------------------------------------------------------------------- #
# 4. Scope: vendor guards on the scale/timebase setters + no readback lie.     #
# --------------------------------------------------------------------------- #

class TestScopeVendorGuards:
    @pytest.mark.parametrize("vendor", ["keysight", "rigol", "lecroy"])
    def test_set_channel_scale_refuses_unverified_vendor(self, vendor):
        scope = Oscilloscope(vendor=vendor, simulation=False)
        scope._connected = True
        with pytest.raises(DeviceError, match="not implemented for vendor"):
            scope.set_channel_scale(1, 0.05)

    @pytest.mark.parametrize("vendor", ["keysight", "rigol", "lecroy"])
    def test_set_timebase_refuses_unverified_vendor(self, vendor):
        scope = Oscilloscope(vendor=vendor, simulation=False)
        scope._connected = True
        with pytest.raises(DeviceError, match="not implemented for vendor"):
            scope.set_timebase(1e-9)

    def test_tektronix_still_writes_the_verified_scpi(self):
        scope = Oscilloscope(vendor="tektronix", simulation=False)
        sent: list[str] = []

        class _Instr:
            def write(self, cmd):
                sent.append(cmd)

            def query(self, cmd):
                return "0"

        scope._instr = _Instr()
        scope._connected = True

        scope.set_channel_scale(2, 0.05)
        scope.set_timebase(4e-7)

        assert any("CH2:SCAle 0.05" in c for c in sent)
        assert any("HORizontal:SCAle 4e-07" in c for c in sent)

    def test_simulation_never_raises_for_any_vendor(self):
        for vendor in ("tektronix", "keysight", "rigol", "lecroy"):
            scope = Oscilloscope(vendor=vendor, simulation=True)
            scope.set_channel_scale(1, 0.05)     # records sim state, no I/O
            scope.set_timebase(1e-9)


class TestScopeReadbackIsNotAnEcho:
    def test_disconnected_real_scope_does_not_echo_the_request_as_a_readback(self):
        """The lie: a requested v/div came back out of read_settings() as though
        it had been read off the instrument, even though nothing was ever sent."""
        scope = Oscilloscope(vendor="tektronix", simulation=False)
        scope._connected = True
        scope._instr = None                      # no session: writes go nowhere

        # A real backend never records _last_vdiv/_last_tdiv at all...
        assert scope.read_settings() == {}
        assert getattr(scope, "_last_vdiv", None) is None
        assert getattr(scope, "_last_tdiv", None) is None

    def test_simulated_scope_still_round_trips_its_own_state(self):
        """In simulation the scope's state IS what was set — that is a truthful
        readback for a simulated instrument, and the panel relies on it."""
        scope = Oscilloscope(vendor="tektronix", simulation=True)
        assert scope.read_settings() == {}       # nothing set yet

        scope.set_timebase(4e-7)
        scope.set_channel_scale(1, 0.05)

        out = scope.read_settings()
        assert out["tdiv"] == pytest.approx(4e-7)
        assert out["vdiv"] == pytest.approx(0.05)
