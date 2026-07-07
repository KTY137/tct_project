"""Headless regression tests for the waveform-generator driver (2026-07-07).

Bench symptom: settings set in the Laser panel "couldn't pass properly" to the
wavegen, and the armed indicator "was always just a flag".  These tests pin
the driver contract that the fixes rely on, without touching hardware:

  * applying settings (the connect-time _apply_defaults path) NEVER enables the
    output — connecting must not arm the PDL 800 laser trigger (safety);
  * offset_V and output_load actually reach the instrument (the bipolar-square
    / wrong-amplitude hazard is a *default value*, not a broken command path);
  * setters reach the instrument when connected, and silently STAGE (no raise,
    value cached for apply-on-connect) when there is no session — which is the
    root of the "settings couldn't pass" report when the wavegen was offline;
  * output_is_on is an honest tri-state (None unknown / False off / True on)
    that flips only on the output_on/output_off commands.
"""
import logging

import pytest

from devices.waveform_generator import WaveformGenerator


def _trailing_float(cmd: str) -> float | None:
    """The trailing numeric argument of a SCPI write, or None (e.g. FUNC PULSe)."""
    try:
        return float(cmd.split()[-1])
    except (ValueError, IndexError):
        return None


class FakeWfgInstr:
    """Minimal pyvisa-resource stand-in: records writes, scripts queries.

    Answers the queries the driver now issues:
      * ``*IDN?``            → a DG4162 identity string;
      * ``:FUNCtion?``       → the active function (``function``, default PULSE;
        also tracked from any ``FUNCtion PULSe/SQUare`` write);
      * ``…:DCYCle?``        → ``duty_readback`` if set (simulate an instrument
        clamp), else the last duty written (echo);
      * ``…:WIDTh?``         → ``width_readback`` if set, else the last width
        written (echo).
    """

    def __init__(self, function: str = "PULSE",
                 duty_readback: float | None = None,
                 width_readback: float | None = None) -> None:
        self.timeout = 5000
        self.writes: list[str] = []
        self.function = function
        self.duty_readback = duty_readback
        self.width_readback = width_readback
        self._last_duty: float | None = None
        self._last_width: float | None = None

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)
        up = cmd.upper()
        if "DCYC" in up:
            self._last_duty = _trailing_float(cmd)
        elif "WIDT" in up:
            self._last_width = _trailing_float(cmd)
        elif "FUNC" in up:                      # a FUNCtion PULSe/SQUare set
            arg = cmd.split()[-1].upper() if " " in cmd else ""
            if "SQU" in arg:
                self.function = "SQU"
            elif "PULS" in arg:
                self.function = "PULSE"

    def query(self, cmd: str) -> str:
        up = cmd.upper()
        if "IDN" in up:
            return "RIGOL TECHNOLOGIES,DG4162,DG4E000000000,00.01.14\n"
        if "DCYC" in up:
            val = self.duty_readback if self.duty_readback is not None else self._last_duty
            return f"{(val if val is not None else 0.0):.3f}\n"
        if "WIDT" in up:
            val = self.width_readback if self.width_readback is not None else self._last_width
            return f"{(val if val is not None else 0.0):.6e}\n"
        if "FUNC" in up:
            return f"{self.function}\n"
        return "RIGOL TECHNOLOGIES,DG4162,DG4E000000000,00.01.14\n"

    def close(self) -> None:
        pass


def _wired_wfg(fake: FakeWfgInstr | None = None,
               **kw) -> tuple[WaveformGenerator, FakeWfgInstr]:
    """A real-mode WaveformGenerator with a fake instrument injected connected."""
    defaults = dict(
        simulation=False, vendor="rigol", output_channel=1,
        frequency_hz=1000.0, pulse_width_s=100e-9,
        amplitude_V=3.3, offset_V=1.65, output_load="INFinity",
    )
    defaults.update(kw)
    wfg = WaveformGenerator(**defaults)
    fake = fake if fake is not None else FakeWfgInstr()
    wfg._instr = fake
    wfg._connected = True
    return wfg, fake


# --------------------------------------------------------------------------- #
# Safety: applying settings must never arm the output                         #
# --------------------------------------------------------------------------- #

def test_apply_defaults_never_enables_output() -> None:
    """The connect-time settings batch must not touch OUTPut:STATe at all."""
    wfg, fake = _wired_wfg()
    wfg._apply_defaults()
    # output_on/output_off are the ONLY commands using the STATe node.
    assert not any("STAT" in w.upper() for w in fake.writes), fake.writes
    # And the driver's output record stays unknown — nothing armed it.
    assert wfg.output_is_on is None


def test_no_setter_enables_output_as_side_effect() -> None:
    wfg, fake = _wired_wfg()
    wfg.set_frequency(2500.0)
    wfg.set_pulse_width(50e-9)
    wfg.set_duty_cycle(10.0)
    wfg.set_amplitude(2.0)
    wfg.set_offset(1.0)
    wfg.set_output_load(50)
    assert not any("STAT" in w.upper() for w in fake.writes), fake.writes
    assert wfg.output_is_on is None


# --------------------------------------------------------------------------- #
# Plumbing: offset + load + params actually reach the instrument              #
# --------------------------------------------------------------------------- #

def test_apply_defaults_sends_offset_and_load() -> None:
    """offset_V and output_load are the bipolar-square / amplitude-scaling
    knobs — verify they are actually written, not silently dropped.  The load
    must go out as the SOURCED :OUTPut:LOAD, never :OUTPut:IMPedance (which is
    not in the DG4000 manual — docs/research/pdl800_trigger_wavegen_lan.md)."""
    wfg, fake = _wired_wfg(offset_V=1.65, output_load="INFinity")
    wfg._apply_defaults()
    assert any("OFFS" in w.upper() and "1.65" in w for w in fake.writes), fake.writes
    assert any("LOAD" in w.upper() and "INF" in w.upper() for w in fake.writes), fake.writes
    assert not any("IMP" in w.upper() for w in fake.writes), fake.writes


def test_setters_reach_instrument_when_connected() -> None:
    wfg, fake = _wired_wfg()
    fake.writes.clear()
    wfg.set_frequency(2000.0)
    wfg.set_amplitude(1.5)
    wfg.set_offset(0.75)
    assert any("FREQ" in w.upper() and "2000" in w for w in fake.writes), fake.writes
    assert any("VOLT" in w.upper() and "1.5" in w for w in fake.writes), fake.writes
    assert any("OFFS" in w.upper() and "0.75" in w for w in fake.writes), fake.writes


# --------------------------------------------------------------------------- #
# The "settings couldn't pass" root: setters STAGE when not connected         #
# --------------------------------------------------------------------------- #

def test_setter_stages_silently_when_not_connected() -> None:
    """A real-mode driver with no session must not raise — it caches the value
    so it is applied on connect (via _apply_defaults).  The panel is what must
    surface that nothing reached hardware; the driver just stages."""
    wfg = WaveformGenerator(simulation=False, vendor="rigol")
    assert wfg.connected is False
    wfg.set_frequency(4242.0)          # must not raise
    wfg.set_amplitude(2.2)
    assert wfg._frequency == 4242.0    # cached for apply-on-connect
    assert wfg._amplitude == 2.2
    assert wfg.connected is False


# --------------------------------------------------------------------------- #
# Armed indicator: honest tri-state that tracks real transitions              #
# --------------------------------------------------------------------------- #

def test_output_is_on_tristate_simulation() -> None:
    wfg = WaveformGenerator(simulation=True)
    assert wfg.output_is_on is None        # before connect: genuinely unknown
    wfg.connect()
    assert wfg.output_is_on is False       # sim hardware is a known-off
    wfg.output_on()
    assert wfg.output_is_on is True
    wfg.output_off()
    assert wfg.output_is_on is False


def test_output_on_off_flip_record_and_emit_scpi() -> None:
    wfg, fake = _wired_wfg()
    assert wfg.output_is_on is None
    wfg.output_on()
    assert wfg.output_is_on is True
    assert any("STAT" in w.upper() and "ON" in w.upper() for w in fake.writes), fake.writes
    fake.writes.clear()
    wfg.output_off()
    assert wfg.output_is_on is False
    assert any("STAT" in w.upper() and "OFF" in w.upper() for w in fake.writes), fake.writes


def test_disconnect_only_disables_a_known_on_output() -> None:
    # Unknown state (None) must not trigger a blind output_off on disconnect.
    wfg, fake = _wired_wfg()
    assert wfg.output_is_on is None
    wfg.disconnect()
    assert not any("STAT" in w.upper() for w in fake.writes), fake.writes


# --------------------------------------------------------------------------- #
# Load: sourced :OUTP:LOAD, applied BEFORE amplitude (the half/2x trap)        #
# --------------------------------------------------------------------------- #

def test_output_load_applied_before_amplitude() -> None:
    """LOAD reinterprets every voltage that follows, so it must be written
    before the amplitude — otherwise the displayed≠delivered 2x error persists
    (docs/research/pdl800_trigger_wavegen_lan.md, DG4000 manual p.202/518)."""
    wfg, fake = _wired_wfg(output_load=50, amplitude_V=2.0)
    wfg._apply_defaults()
    load_idx = next(i for i, w in enumerate(fake.writes) if "LOAD" in w.upper())
    ampl_idx = next(i for i, w in enumerate(fake.writes)
                    if "VOLT" in w.upper()
                    and not any(t in w.upper() for t in ("OFFS", "HIGH", "LOW")))
    assert load_idx < ampl_idx, fake.writes
    assert any("LOAD" in w.upper() and "50" in w for w in fake.writes), fake.writes
    assert not any("IMP" in w.upper() for w in fake.writes), fake.writes


def test_config_output_load_50_roundtrips_to_wire() -> None:
    """The shipped devices.yaml sets output_load: 50 (the 50 Ω PDL trigger
    input) and that value reaches the wire as the sourced :OUTP:LOAD 50."""
    import yaml
    from pathlib import Path
    cfg_path = Path(__file__).resolve().parents[1] / "configs" / "devices.yaml"
    wfg_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["waveform_generator"]
    assert wfg_cfg["output_load"] == 50, wfg_cfg["output_load"]
    wfg, fake = _wired_wfg(output_load=wfg_cfg["output_load"],
                           vendor=wfg_cfg.get("vendor", "rigol"))
    wfg._apply_defaults()
    assert any("LOAD" in w.upper() and "50" in w for w in fake.writes), fake.writes
    assert not any("IMP" in w.upper() for w in fake.writes), fake.writes


# --------------------------------------------------------------------------- #
# Duty cycle: FUNCTION-AWARE node (bug fix) — the DG4162 stores duty per        #
# function, and writing SQUare:DCYCle on a PULSe function garbles the width.    #
# The 20–80 clamp is SQUare-only; PULSe wants LOW duty and is instrument-       #
# limited by the frequency-dependent minimum pulse width.                       #
# --------------------------------------------------------------------------- #

def test_duty_cycle_pulse_uses_pulse_node() -> None:
    """Default function is PULSE → duty must go to FUNCtion:PULSe:DCYCle, NOT
    the SQUare node (verified live on the DG4162, fw 00.01.14)."""
    wfg, fake = _wired_wfg(fake=FakeWfgInstr(function="PULSE"), frequency_hz=1000.0)
    fake.writes.clear()
    wfg.set_duty_cycle(30.0)
    duty = [w for w in fake.writes if "DCYC" in w.upper()]
    assert duty, fake.writes
    assert all("PULS" in w.upper() and "SQU" not in w.upper() for w in duty), duty
    assert any("30.000" in w for w in duty), duty


def test_duty_cycle_square_uses_square_node() -> None:
    """When the active function is SQUARE, duty goes to FUNCtion:SQUare:DCYCle."""
    wfg, fake = _wired_wfg(fake=FakeWfgInstr(function="SQU"), frequency_hz=1000.0)
    fake.writes.clear()
    wfg.set_duty_cycle(50.0)
    duty = [w for w in fake.writes if "DCYC" in w.upper()]
    assert duty, fake.writes
    assert all("SQU" in w.upper() for w in duty), duty
    assert any("50.000" in w for w in duty), duty


def test_duty_cycle_pulse_does_not_clamp_20_80() -> None:
    """The 20–80 % clamp is SQUare-only.  On PULSe a laser wants LOW duty, so a
    5 % request must pass through un-clamped (only the broad sanity clamp)."""
    wfg, fake = _wired_wfg(fake=FakeWfgInstr(function="PULSE"), frequency_hz=1000.0)
    fake.writes.clear()
    wfg.set_duty_cycle(5.0)
    duty = [w for w in fake.writes if "DCYC" in w.upper()]
    assert any("5.000" in w for w in duty), duty
    assert not any("20.000" in w for w in duty), duty       # NOT clamped up to 20


def test_duty_cycle_square_clamped_below_floor() -> None:
    """SQUARE, ≤10 MHz → valid 20–80 %; a 10 % request clamps to 20 %, never
    sent raw (DG4000 manual p.345)."""
    wfg, fake = _wired_wfg(fake=FakeWfgInstr(function="SQU"), frequency_hz=1000.0)
    fake.writes.clear()
    wfg.set_duty_cycle(10.0)
    duty = [w for w in fake.writes if "DCYC" in w.upper()]
    assert any("20.000" in w for w in duty), duty
    assert not any("10.000" in w for w in duty), duty


def test_duty_cycle_square_clamped_above_ceiling() -> None:
    wfg, fake = _wired_wfg(fake=FakeWfgInstr(function="SQU"), frequency_hz=1000.0)
    fake.writes.clear()
    wfg.set_duty_cycle(95.0)
    duty = [w for w in fake.writes if "DCYC" in w.upper()]
    assert any("80.000" in w for w in duty), duty


def test_duty_cycle_square_range_narrows_with_frequency() -> None:
    """SQUARE, 10 MHz < f ≤ 40 MHz → 40–60 %; a 20 % request clamps to 40 %."""
    wfg, fake = _wired_wfg(fake=FakeWfgInstr(function="SQU"), frequency_hz=20e6)
    fake.writes.clear()
    wfg.set_duty_cycle(20.0)
    duty = [w for w in fake.writes if "DCYC" in w.upper()]
    assert any("40.000" in w for w in duty), duty


def test_duty_cycle_defaults_to_pulse_when_function_unreadable() -> None:
    """If the function query yields nothing usable (staged/odd reply), the
    driver must fall back to the PULSe node — never blindly to SQUare."""
    wfg, fake = _wired_wfg(fake=FakeWfgInstr(function="RIGOL,junk"),
                           frequency_hz=1000.0)
    fake.writes.clear()
    wfg.set_duty_cycle(7.0)
    duty = [w for w in fake.writes if "DCYC" in w.upper()]
    assert all("PULS" in w.upper() for w in duty), duty
    assert any("7.000" in w for w in duty), duty


def test_duty_cycle_readback_stores_applied_and_warns_on_clamp(caplog) -> None:
    """The instrument silently clamps duty to the frequency-dependent minimum
    pulse width.  The driver must READ BACK the applied value into _duty_cycle
    (so the panel reflects reality) and warn on the mismatch."""
    fake = FakeWfgInstr(function="PULSE", duty_readback=0.3)   # device applied 0.3%
    wfg, fake = _wired_wfg(fake=fake, frequency_hz=1000.0)
    with caplog.at_level(logging.WARNING, logger="devices.waveform_generator"):
        wfg.set_duty_cycle(5.0)                                # requested 5%
    assert wfg._duty_cycle == pytest.approx(0.3)               # applied, not requested
    assert any("clamp" in r.message.lower() for r in caplog.records), caplog.text


def test_duty_cycle_readback_no_warn_when_applied_exactly(caplog) -> None:
    fake = FakeWfgInstr(function="PULSE")                      # echoes the request
    wfg, fake = _wired_wfg(fake=fake, frequency_hz=1000.0)
    with caplog.at_level(logging.WARNING, logger="devices.waveform_generator"):
        wfg.set_duty_cycle(30.0)
    assert wfg._duty_cycle == pytest.approx(30.0)
    assert not any("clamp" in r.message.lower() for r in caplog.records), caplog.text


# --------------------------------------------------------------------------- #
# Pulse width: read back the ACTUAL applied width (frequency-dependent minimum) #
# --------------------------------------------------------------------------- #

def test_pulse_width_readback_stores_applied_and_warns_on_clamp(caplog) -> None:
    """200 ns @ 1 kHz is applied by the DG4162 as 3.125 µs (frequency-dependent
    minimum, verified live).  The driver sends 200 ns but must store the 3.125 µs
    it read back and warn — so the panel stops showing the rejected request."""
    fake = FakeWfgInstr(width_readback=3.125e-6)
    wfg, fake = _wired_wfg(fake=fake, frequency_hz=1000.0)
    with caplog.at_level(logging.WARNING, logger="devices.waveform_generator"):
        wfg.set_pulse_width(200e-9)
    assert wfg._pulse_width == pytest.approx(3.125e-6, rel=1e-3)
    assert any("clamp" in r.message.lower() for r in caplog.records), caplog.text
    # It still SENT the requested value on the wire (the driver is not the bug).
    assert any("WIDT" in w.upper() and "2.000e-07" in w.lower() for w in fake.writes), fake.writes


def test_pulse_width_readback_no_warn_when_applied_exactly(caplog) -> None:
    fake = FakeWfgInstr()                                      # echoes the request
    wfg, fake = _wired_wfg(fake=fake, frequency_hz=1000.0)
    with caplog.at_level(logging.WARNING, logger="devices.waveform_generator"):
        wfg.set_pulse_width(10e-6)
    assert wfg._pulse_width == pytest.approx(10e-6, rel=1e-3)
    assert not any("clamp" in r.message.lower() for r in caplog.records), caplog.text


# --------------------------------------------------------------------------- #
# Levels path: sourced VOLT:HIGH / VOLT:LOW clean 0→+V square                  #
# --------------------------------------------------------------------------- #

def test_set_levels_emits_sourced_high_low_and_bookkeeping() -> None:
    wfg, fake = _wired_wfg()
    fake.writes.clear()
    wfg.set_levels(0.0, 2.5)
    assert any("HIGH" in w.upper() and "2.5" in w for w in fake.writes), fake.writes
    assert any("LOW" in w.upper() and "0.0000" in w for w in fake.writes), fake.writes
    assert wfg._amplitude == pytest.approx(2.5)     # high - low
    assert wfg._offset == pytest.approx(1.25)       # (high + low) / 2
    # Setting rails must never arm the trigger.
    assert not any("STAT" in w.upper() for w in fake.writes), fake.writes
    assert wfg.output_is_on is None


def test_set_levels_rejects_high_not_above_low() -> None:
    from devices.base import DeviceError
    wfg, _ = _wired_wfg()
    with pytest.raises(DeviceError):
        wfg.set_levels(2.5, 2.5)
    with pytest.raises(DeviceError):
        wfg.set_levels(1.0, 0.0)


def test_levels_config_takes_square_path_not_amplitude() -> None:
    """When both rails are configured, connect()/_apply_defaults drives a
    SQUare via VOLT:HIGH/LOW and does NOT emit amplitude or offset."""
    wfg, fake = _wired_wfg(level_low_V=0.0, level_high_V=2.5)
    wfg._apply_defaults()
    assert any("FUNC" in w.upper() and "SQU" in w.upper() for w in fake.writes), fake.writes
    assert any("HIGH" in w.upper() and "2.5" in w for w in fake.writes), fake.writes
    assert any("LOW" in w.upper() and "0.0000" in w for w in fake.writes), fake.writes
    assert not any("OFFS" in w.upper() for w in fake.writes), fake.writes
    bare_ampl = [w for w in fake.writes if "VOLT" in w.upper()
                 and not any(t in w.upper() for t in ("HIGH", "LOW", "OFFS"))]
    assert not bare_ampl, bare_ampl
    # Load still first, and the levels path still never arms the output.
    load_idx = next(i for i, w in enumerate(fake.writes) if "LOAD" in w.upper())
    high_idx = next(i for i, w in enumerate(fake.writes) if "HIGH" in w.upper())
    assert load_idx < high_idx, fake.writes
    assert not any("STAT" in w.upper() for w in fake.writes), fake.writes
    assert wfg.output_is_on is None


def test_levels_absent_keeps_legacy_amplitude_path() -> None:
    """Default (no rails) is byte-for-byte the legacy amplitude+offset PULSe
    path — the new option changes nothing unless it is set."""
    wfg, fake = _wired_wfg(amplitude_V=3.3, offset_V=0.0)
    wfg._apply_defaults()
    assert any("FUNC" in w.upper() and "PULS" in w.upper() for w in fake.writes), fake.writes
    assert any("VOLT" in w.upper() and "3.3" in w for w in fake.writes), fake.writes
    assert any("OFFS" in w.upper() for w in fake.writes), fake.writes
    assert not any("HIGH" in w.upper() or ":LOW" in w.upper() for w in fake.writes), fake.writes
