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
import pytest

from devices.waveform_generator import WaveformGenerator


class FakeWfgInstr:
    """Minimal pyvisa-resource stand-in: records writes, scripts *IDN?."""

    def __init__(self) -> None:
        self.timeout = 5000
        self.writes: list[str] = []

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)

    def query(self, cmd: str) -> str:
        return "RIGOL TECHNOLOGIES,DG4162,DG4E000000000,00.02.00\n"

    def close(self) -> None:
        pass


def _wired_wfg(**kw) -> tuple[WaveformGenerator, FakeWfgInstr]:
    """A real-mode WaveformGenerator with a fake instrument injected connected."""
    defaults = dict(
        simulation=False, vendor="rigol", output_channel=1,
        frequency_hz=1000.0, pulse_width_s=100e-9,
        amplitude_V=3.3, offset_V=1.65, output_load="INFinity",
    )
    defaults.update(kw)
    wfg = WaveformGenerator(**defaults)
    fake = FakeWfgInstr()
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
    knobs — verify they are actually written, not silently dropped."""
    wfg, fake = _wired_wfg(offset_V=1.65, output_load="INFinity")
    wfg._apply_defaults()
    assert any("OFFS" in w.upper() and "1.65" in w for w in fake.writes), fake.writes
    assert any("IMP" in w.upper() and "INF" in w.upper() for w in fake.writes), fake.writes


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
