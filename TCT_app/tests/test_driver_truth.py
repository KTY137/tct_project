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

5. ``ramp_to`` / ``_ramp_channel`` ENABLED the output before walking to the target,
   so every fail-safe "ramp to 0 V, then switch off" path — the slow-control ALARM
   handler, EMERGENCY OFF, ALL-OFF, scan abort, app shutdown — ENERGIZED an idle HV
   channel in order to bring it to zero.  An over-temperature alarm could switch the
   HV on (safety rule 1).

6. ``KeithleyBiasSupply.disconnect()`` was the un-swept twin of (2): ``except: pass``
   around the ramp-down, then an unconditional ``_setpoint_V = 0 / _output_on =
   False`` — a supply that never came down was abandoned energized AND declared safe.

7. The compliance setters recorded the new HV CURRENT LIMIT *before* writing it, so a
   failed write left the driver believing a limit the hardware never took — and the
   scan's trip detection then compares readings against a limit that does not exist.

8. ``compliant`` was inferred from the measured current against that same local limit
   while the iseg module publishes its own authoritative "I am current-controlled" bit.
"""
from __future__ import annotations

import logging

import pytest

from devices.base import DeviceError
from devices.bias_supply_base import BiasReading
from devices.bias_supply_e4control import E4ControlBiasSupply
from devices.bias_supply_iseg import IsegBiasSupply
from devices.bias_supply_keithley import KeithleyBiasSupply
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


# --------------------------------------------------------------------------- #
# Fake sessions for the two remaining HV backends                              #
# --------------------------------------------------------------------------- #

class FakeVisaInst:
    """Stand-in for the pyvisa resource the Keithley driver holds."""

    def __init__(self, fail_writes: bool = False, reply: str = "0.0,1e-9,0,0,0"):
        self.fail_writes = fail_writes
        self.reply = reply
        self.writes: list[str] = []
        self.closed = False
        self.closed_after: list[str] = []

    def write(self, cmd: str) -> None:
        if self.fail_writes:
            raise OSError("VISA write failed: link down")
        self.writes.append(cmd)

    def query(self, cmd: str) -> str:
        return self.reply

    def close(self) -> None:
        self.closed = True
        self.closed_after = list(self.writes)


def _live_keithley(inst: FakeVisaInst) -> KeithleyBiasSupply:
    sup = KeithleyBiasSupply(visa_address="GPIB0::15::INSTR",
                             compliance_A=10e-6, voltage_range_V=1100.0,
                             simulation=False)
    sup._inst = inst
    sup._connected = True
    return sup


class FakeE4Dev:
    """Stand-in for the e4control device object (K2410 & friends)."""

    def __init__(self, fail_writes: bool = False, fail_limit: bool = False):
        self.fail_writes = fail_writes
        self.fail_limit = fail_limit
        self.calls: list[tuple[str, object]] = []
        self.closed = False
        self.closed_after: list[tuple[str, object]] = []
        self.voltage = 0.0

    def setVoltage(self, v: float) -> None:          # noqa: N802 (vendor API)
        if self.fail_writes:
            raise OSError("e4control link down")
        self.voltage = v
        self.calls.append(("setVoltage", v))

    def setOutput(self, on: bool) -> None:           # noqa: N802
        if self.fail_writes:
            raise OSError("e4control link down")
        self.calls.append(("setOutput", bool(on)))

    def setCurrentLimit(self, a: float) -> None:     # noqa: N802
        if self.fail_limit:
            raise OSError("e4control link down")
        self.calls.append(("setCurrentLimit", a))

    def setRampSpeed(self, step: int, delay: float) -> None:   # noqa: N802
        self.calls.append(("setRampSpeed", (step, delay)))

    def rampVoltage(self, v: float) -> None:         # noqa: N802
        if self.fail_writes:
            raise OSError("e4control link down")
        self.voltage = v
        self.calls.append(("rampVoltage", v))

    def getVoltage(self) -> float:                   # noqa: N802
        return self.voltage

    def getCurrent(self) -> float:                   # noqa: N802
        return 1e-9

    def close(self) -> None:
        self.closed = True
        self.closed_after = list(self.calls)


def _live_e4c(dev: FakeE4Dev) -> E4ControlBiasSupply:
    sup = E4ControlBiasSupply(compliance_A=10e-6, simulation=False)
    sup._dev = dev
    sup._connected = True
    return sup


def _enabled(dev: FakeE4Dev) -> bool:
    return ("setOutput", True) in dev.calls


# --------------------------------------------------------------------------- #
# 5. Ramping to ZERO must never energize an idle channel (safety rule 1).      #
#                                                                              #
#    THE defect: ramp_to()/_ramp_channel() switched the output ON before       #
#    walking to the target, so the slow-control ALARM fail-safe, the EMERGENCY  #
#    OFF button and ALL-OFF each ENERGIZED an idle HV channel in order to ramp  #
#    it to zero.  An over-temp alarm could switch the HV on.                    #
# --------------------------------------------------------------------------- #

class TestZeroRampNeverEnergizes:
    """A ramp to 0 V on an OFF channel: no output-on, on ANY backend."""

    def test_simulated_offline_channel_is_not_switched_on(self):
        sup = SimulatedBiasSupply(voltage_range_V=1000.0)
        sup.connect()
        assert sup.output_is_on_ch(0) is False

        sup.ramp_to(0.0, step_V=20.0, delay_s=0.0)   # the fail-safe call

        assert sup.output_is_on_ch(0) is False, "ramp-to-zero ENERGIZED an idle channel"
        assert sup.setpoint_V == 0.0

    def test_simulated_offline_channel_with_a_stale_setpoint_stays_off(self):
        """The dangerous shape: the register holds real HV while the output is off.

        set_voltage() writes the setpoint even with the output OFF, so an idle
        channel can hold a non-zero voltage register.  The old ramp_to() called
        output_on() first — which would have ramped that channel to REAL HV during
        an over-temperature ALARM.
        """
        sup = SimulatedBiasSupply(voltage_range_V=1000.0)
        sup.connect()
        sup.set_voltage(-600.0)                      # output still OFF
        assert sup.output_is_on_ch(0) is False

        sup.ramp_to(0.0, step_V=20.0, delay_s=0.0)

        assert sup.output_is_on_ch(0) is False
        assert sup.setpoint_V == 0.0, "the stale HV setpoint must be parked at zero"
        assert sup.read().voltage_V == pytest.approx(0.0), "no HV may have appeared"

    def test_simulated_secondary_channel_is_not_switched_on(self):
        """ALL-OFF walks every channel to zero — including idle ones."""
        sup = SimulatedBiasSupply(channel_count=2, voltage_range_V=1000.0)
        sup.connect()

        sup.ramp_to_ch(1, 0.0, step_V=20.0, delay_s=0.0)

        assert sup.output_is_on_ch(1) is False
        assert sup.setpoint_V_ch(1) == 0.0

    def test_simulated_nonzero_target_still_enables_the_output(self):
        """Unchanged behaviour: a genuine energize request DOES turn HV on."""
        sup = SimulatedBiasSupply(voltage_range_V=1000.0)
        sup.connect()

        sup.ramp_to(-100.0, step_V=25.0, delay_s=0.0)

        assert sup.output_is_on_ch(0) is True
        assert sup.setpoint_V == pytest.approx(-100.0)

    def test_simulated_zero_ramp_on_a_LIVE_channel_still_walks_it_down(self):
        """The edge Mary named: an ON channel must still ramp down (and stay on
        until the caller switches it off — that pairing is unchanged)."""
        sup = SimulatedBiasSupply(voltage_range_V=1000.0)
        sup.connect()
        sup.ramp_to(-100.0, step_V=25.0, delay_s=0.0)

        sup.ramp_to(0.0, step_V=25.0, delay_s=0.0)

        assert sup.setpoint_V == pytest.approx(0.0)
        assert sup.read().voltage_V == pytest.approx(0.0)   # HV actually came down
        assert sup.output_is_on_ch(0) is True               # caller opens the output
        sup.output_off()
        assert sup.output_is_on_ch(0) is False

    def test_iseg_offline_channel_is_not_switched_on(self):
        inst = FakeIsegInst()
        sup = _live_iseg(inst)
        sup._chs(0)["output_on"] = False
        sup._chs(0)["setpoint_V"] = -300.0          # stale register

        sup.ramp_to(0.0, step_V=20.0, delay_s=0.0)

        assert not any("VOLT ON" in w.upper() for w in inst.writes), \
            "ramp-to-zero must never enable an idle HV channel"
        assert sup._chs(0)["output_on"] is False

    def test_iseg_zero_ramp_parks_the_voltage_register(self):
        """Recording 0 V without writing it would leave the register at -300 V —
        a later, deliberate output_on() would then energize into the stale value."""
        inst = FakeIsegInst()
        sup = _live_iseg(inst)
        sup._chs(0)["setpoint_V"] = -300.0

        sup.ramp_to(0.0, step_V=20.0, delay_s=0.0)

        assert any(w.upper().startswith(":VOLT 0") for w in inst.writes)
        assert sup.setpoint_V == 0.0

    def test_iseg_failed_park_write_does_not_claim_zero(self):
        """Write-then-record: a park that never landed must not be reported as 0 V."""
        inst = FakeIsegInst(fail_writes=True)
        sup = _live_iseg(inst)
        sup._chs(0)["setpoint_V"] = -300.0

        with pytest.raises(Exception):
            sup.ramp_to(0.0, step_V=20.0, delay_s=0.0)

        assert sup.setpoint_V == -300.0, "must not claim a 0 V it never achieved"

    def test_iseg_nonzero_target_still_enables_the_output(self):
        inst = FakeIsegInst()
        sup = _live_iseg(inst)

        sup.ramp_to(-50.0, step_V=25.0, delay_s=0.0)

        assert any("VOLT ON" in w.upper() for w in inst.writes)
        assert sup._chs(0)["output_on"] is True
        assert sup.setpoint_V == pytest.approx(-50.0)

    def test_iseg_secondary_channel_zero_ramp_is_not_an_energize(self):
        inst = FakeIsegInst()
        sup = _live_iseg(inst, channel=0)

        sup.ramp_to_ch(1, 0.0, step_V=20.0, delay_s=0.0)

        assert not any("VOLT ON" in w.upper() for w in inst.writes)
        assert sup.output_is_on_ch(1) is False

    def test_keithley_offline_output_is_not_switched_on(self):
        inst = FakeVisaInst()
        sup = _live_keithley(inst)
        sup._setpoint_V = -300.0                    # stale register, output off

        sup.ramp_to(0.0, step_V=20.0, delay_s=0.0)

        assert not any(":OUTP ON" in w.upper() for w in inst.writes), \
            "ramp-to-zero must never enable an idle HV output"
        assert sup._output_on is False
        assert sup.setpoint_V == 0.0

    def test_keithley_nonzero_target_still_enables_the_output(self):
        inst = FakeVisaInst()
        sup = _live_keithley(inst)

        sup.ramp_to(-50.0, step_V=25.0, delay_s=0.0)

        assert any(":OUTP ON" in w.upper() for w in inst.writes)
        assert sup._output_on is True
        assert sup.setpoint_V == pytest.approx(-50.0)

    def test_e4control_offline_output_is_not_switched_on(self):
        """The e4control backend OVERRIDES ramp_to, so it needs its own guard —
        fixing only the base class would leave this third HV backend energizing."""
        dev = FakeE4Dev()
        sup = _live_e4c(dev)
        sup._setpoint_V = -300.0

        sup.ramp_to(0.0, step_V=20.0, delay_s=0.0)

        assert not _enabled(dev), "ramp-to-zero must never enable an idle HV output"
        assert sup._output_on is False
        assert sup.setpoint_V == 0.0
        assert ("setVoltage", 0.0) in dev.calls      # register parked at zero

    def test_e4control_nonzero_target_still_enables_the_output(self):
        dev = FakeE4Dev()
        sup = _live_e4c(dev)

        sup.ramp_to(-10.0, step_V=5.0, delay_s=0.0)

        assert _enabled(dev)
        assert sup._output_on is True
        assert sup.setpoint_V == pytest.approx(-10.0)


# --------------------------------------------------------------------------- #
# 6. Keithley teardown: as loud as the iseg one.                               #
# --------------------------------------------------------------------------- #

class TestKeithleyDisconnectFailsLoud:
    def test_persistent_rampdown_failure_raises_instead_of_silent_close(self):
        inst = FakeVisaInst(fail_writes=True)
        sup = _live_keithley(inst)
        sup._output_on = True
        sup._setpoint_V = -300.0

        with pytest.raises(DeviceError, match="(?i)ramp-down failed|may still be energized"):
            sup.disconnect()

        assert inst.closed              # link released — but LOUDLY, not silently
        assert sup.connected is False

    def test_failed_teardown_keeps_truthful_state_not_a_fake_zero(self):
        """THE defect: it declared 0 V / output-off after a ramp-down that failed."""
        inst = FakeVisaInst(fail_writes=True)
        sup = _live_keithley(inst)
        sup._output_on = True
        sup._setpoint_V = -300.0

        with pytest.raises(DeviceError):
            sup.disconnect()

        assert sup._output_on is True, "must not claim an OFF it never achieved"
        assert sup._setpoint_V == -300.0

    def test_rampdown_is_retried_once_before_giving_up(self):
        inst = FakeVisaInst()
        sup = _live_keithley(inst)
        sup._output_on = True

        calls = {"n": 0}
        real_write = sup._write

        def flaky(cmd: str) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("dropped frame")
            real_write(cmd)

        sup._write = flaky              # type: ignore[method-assign]
        sup.disconnect()                # retry succeeds -> no raise

        assert sup._output_on is False
        assert inst.closed

    def test_link_is_closed_only_after_the_rampdown_attempt(self):
        inst = FakeVisaInst()
        sup = _live_keithley(inst)
        sup._output_on = True
        sup._setpoint_V = -50.0

        sup.disconnect()

        assert inst.closed
        assert any(":OUTP OFF" in w.upper() for w in inst.closed_after), \
            "session closed before the output was switched off"

    def test_offline_output_is_not_switched_on_just_to_ramp_it_down(self):
        inst = FakeVisaInst()
        sup = _live_keithley(inst)
        sup._output_on = False

        sup.disconnect()

        assert not any(":OUTP ON" in w.upper() for w in inst.writes), \
            "disconnect must never enable HV on an already-off output"

    def test_clean_disconnect_does_not_raise_and_resets_state(self):
        inst = FakeVisaInst()
        sup = _live_keithley(inst)
        sup._output_on = True
        sup._setpoint_V = -20.0

        sup.disconnect()

        assert inst.closed and sup.connected is False
        assert sup._output_on is False and sup._setpoint_V == 0.0

    def test_simulated_keithley_disconnect_is_safe(self):
        sup = KeithleyBiasSupply(simulation=True)
        sup.connect()
        sup.disconnect()                # no session, must not raise
        assert sup.connected is False


class TestKeithleyOutputOffNeverLies:
    def test_failed_output_off_write_does_not_claim_off(self):
        inst = FakeVisaInst(fail_writes=True)
        sup = _live_keithley(inst)
        sup._output_on = True

        sup.output_off()                # fail-safe: must NOT raise

        assert sup._output_on is True, \
            "a failed output-off must not report the output as OFF"


class TestE4ControlDisconnectFailsLoud:
    def test_persistent_rampdown_failure_raises_instead_of_silent_close(self):
        dev = FakeE4Dev(fail_writes=True)
        sup = _live_e4c(dev)
        sup._output_on = True
        sup._setpoint_V = -300.0

        with pytest.raises(DeviceError, match="(?i)ramp-down failed|may still be energized"):
            sup.disconnect()

        assert dev.closed
        assert sup._output_on is True, "must not claim an OFF it never achieved"
        assert sup._setpoint_V == -300.0

    def test_offline_output_is_not_ramped_by_enabling_it(self):
        dev = FakeE4Dev()
        sup = _live_e4c(dev)
        sup._output_on = False

        sup.disconnect()

        assert not _enabled(dev)
        assert ("rampVoltage", 0) not in dev.calls   # nothing to ramp: it was off
        assert dev.closed


# --------------------------------------------------------------------------- #
# 7. The compliance setters write BEFORE they record.                          #
#                                                                              #
#    Compliance is the HV CURRENT LIMIT — the DUT's protection.  A failed write #
#    that still advanced the driver's belief left it reporting e.g. 10 µA while #
#    the hardware kept its old, possibly far higher limit, and the scan's trip   #
#    detection then compared readings against a limit that never existed.        #
# --------------------------------------------------------------------------- #

class TestComplianceSetterWritesBeforeItRecords:
    def test_iseg_failed_compliance_write_leaves_the_old_limit(self):
        inst = FakeIsegInst()
        sup = _live_iseg(inst)
        sup.set_compliance_ch(0, 10e-6)
        assert sup.compliance_A_ch(0) == pytest.approx(10e-6)

        inst.fail_writes = True
        with pytest.raises(Exception):
            sup.set_compliance_ch(0, 1e-3)

        assert sup.compliance_A_ch(0) == pytest.approx(10e-6), \
            "the driver must not believe a current limit the hardware never took"

    def test_iseg_successful_compliance_write_is_recorded(self):
        inst = FakeIsegInst()
        sup = _live_iseg(inst)

        sup.set_compliance_ch(0, 25e-6)

        assert any(":CURR" in w.upper() for w in inst.writes)
        assert sup.compliance_A_ch(0) == pytest.approx(25e-6)

    def test_keithley_failed_compliance_write_leaves_the_old_limit(self):
        inst = FakeVisaInst()
        sup = _live_keithley(inst)
        sup.set_compliance(10e-6)

        inst.fail_writes = True
        with pytest.raises(Exception):
            sup.set_compliance(1e-3)

        assert sup.compliance_A == pytest.approx(10e-6)

    def test_e4control_failed_compliance_write_leaves_the_old_limit(self):
        dev = FakeE4Dev()
        sup = _live_e4c(dev)
        sup.set_compliance(10e-6)

        dev.fail_limit = True
        with pytest.raises(Exception):
            sup.set_compliance(1e-3)

        assert sup.compliance_A == pytest.approx(10e-6)

    def test_iseg_failed_voltage_write_leaves_the_old_setpoint(self):
        """The same discipline on the voltage setter (already fixed — pinned here)."""
        inst = FakeIsegInst()
        sup = _live_iseg(inst)
        sup.set_voltage_ch(0, -100.0)

        inst.fail_writes = True
        with pytest.raises(Exception):
            sup.set_voltage_ch(0, -200.0)

        assert sup.setpoint_V_ch(0) == pytest.approx(-100.0)

    def test_keithley_failed_voltage_write_leaves_the_old_setpoint(self):
        inst = FakeVisaInst()
        sup = _live_keithley(inst)
        sup.set_voltage(-100.0)
        assert sup.setpoint_V == pytest.approx(-100.0)   # the real path records now

        inst.fail_writes = True
        with pytest.raises(Exception):
            sup.set_voltage(-200.0)

        assert sup.setpoint_V == pytest.approx(-100.0)

    def test_e4control_failed_voltage_write_leaves_the_old_setpoint(self):
        dev = FakeE4Dev()
        sup = _live_e4c(dev)
        sup.set_voltage(-100.0)

        dev.fail_writes = True
        with pytest.raises(Exception):
            sup.set_voltage(-200.0)

        assert sup.setpoint_V == pytest.approx(-100.0)


# --------------------------------------------------------------------------- #
# 8. iseg status: the external inhibit is a trip; compliance comes from bit 6.  #
#    Bit map: docs/research/iseg_polarity_scpi.md §6 (cited iseg manual).       #
# --------------------------------------------------------------------------- #

_EXT_INHIBIT   = 0x1000     # bit 12
_CONST_CURRENT = 0x40       # bit  6


class TestIsegStatusDerivedFlags:
    def test_external_inhibit_is_a_trip(self):
        """Bit 12 'Is External Inhibit': the INTERLOCK CHAIN is asserted and the
        module is holding the output off on its own authority — the HV is not
        doing what was asked, which is exactly this driver's trip definition."""
        sup = _live_iseg(FakeIsegInst(status=_EXT_INHIBIT))
        r = sup.read_ch(0)
        assert r.tripped is True
        assert r.status_word == _EXT_INHIBIT

    def test_compliant_comes_from_the_modules_own_const_current_bit(self):
        """The module says 'I am current-controlled' — believe IT, not a guess
        against the driver's local idea of the limit."""
        inst = FakeIsegInst(status=_IS_ON | _CONST_CURRENT,
                            meas_V=-300.0, meas_I=1e-9)   # far below the local limit
        sup = _live_iseg(inst)

        r = sup.read_ch(0)

        assert r.compliant is True
        assert r.tripped is False        # constant-current is not a latched fault

    def test_voltage_controlled_channel_is_not_compliant(self):
        inst = FakeIsegInst(status=_IS_ON | _CONST_VOLTAGE, meas_V=-300.0, meas_I=1e-9)
        sup = _live_iseg(inst)
        assert sup.read_ch(0).compliant is False

    def test_current_at_the_configured_limit_still_trips_compliance(self):
        """The comparison is kept as an OR, never dropped: compliance_A is the
        OPERATOR's DUT-protection limit.  If the current reaches it while the
        module still thinks it is voltage-controlled (its own hardware limit is
        higher), the run must still trip — a missed alarm is the one that burns
        a sensor."""
        inst = FakeIsegInst(status=_IS_ON | _CONST_VOLTAGE,
                            meas_V=-300.0, meas_I=20e-6)   # limit is 10 µA
        sup = _live_iseg(inst)

        assert sup.read_ch(0).compliant is True

    def test_unreadable_status_falls_back_to_the_current_comparison(self):
        class NoStatus(FakeIsegInst):
            def query(self, cmd: str) -> str:
                if ":READ:CHAN:STAT?" in cmd.upper():
                    raise OSError("status query timed out")
                return super().query(cmd)

        over = _live_iseg(NoStatus(meas_I=20e-6))          # above the 10 µA limit
        under = _live_iseg(NoStatus(meas_I=1e-9))

        assert over.read_ch(0).compliant is True
        assert over.read_ch(0).status_word is None
        assert under.read_ch(0).compliant is False

    def test_failed_read_is_never_reported_as_compliant(self):
        """A measurement we could not take (NaN) is unknown, not 'in compliance'."""
        class DeadLink(FakeIsegInst):
            def query(self, cmd: str) -> str:
                raise OSError("link down")

        r = _live_iseg(DeadLink()).read_ch(0)
        assert r.compliant is False
        assert r.tripped is None          # unknown, not a clean bill of health
