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
                 width_readback: float | None = None,
                 output_state: str = "OFF") -> None:
        self.timeout = 5000
        self.writes: list[str] = []
        self.function = function
        self.duty_readback = duty_readback
        self.width_readback = width_readback
        # Scripted reply to :OUTPut{ch}:STATe? (the connect-time armed resolve).
        self.output_state = output_state
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
        if "STAT" in up:                        # :OUTPut{ch}:STATe? read-back
            return f"{self.output_state}\n"
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


# --------------------------------------------------------------------------- #
# Config plumbing: devices.yaml level_low_V / level_high_V reach the driver.    #
# Absent → both None → byte-identical legacy bipolar default (proven above by   #
# test_levels_absent_keeps_legacy_amplitude_path).                              #
# --------------------------------------------------------------------------- #

def _dm_from_wfg_cfg(tmp_path, wfg_extra: dict):
    """Build a fully-simulated DeviceManager whose waveform_generator block is
    the sim defaults plus *wfg_extra*; return its constructed driver."""
    import yaml
    from controller.device_manager import DeviceManager
    cfg = {
        "oscilloscope":       {"backend": "visa", "simulation": True},
        "motor_stage":        {"backend": "simulated"},
        "intensity_monitor":  {"backend": "simulated"},
        "camera":             {"simulation": True},
        "bias_supply":        {"backend": "simulated"},
        "waveform_generator": {"simulation": True, **wfg_extra},
        "output":             {"data_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    dm = DeviceManager(config_path=str(path))
    return dm


def test_config_levels_reach_constructed_driver(tmp_path) -> None:
    """level_low_V / level_high_V in devices.yaml land on the WaveformGenerator
    the DeviceManager builds (the plumbing this task adds)."""
    dm = _dm_from_wfg_cfg(tmp_path, {"level_low_V": 0.0, "level_high_V": 2.5})
    assert dm.config_errors() == [], dm.config_errors()
    wfg = dm.waveform_generator
    assert wfg._level_low == 0.0
    assert wfg._level_high == 2.5


def test_config_levels_absent_is_none_bipolar_default(tmp_path) -> None:
    """No level keys → both rails None → the driver stays on the legacy bipolar
    amplitude+offset path (byte-identical to today's default)."""
    dm = _dm_from_wfg_cfg(tmp_path, {})
    wfg = dm.waveform_generator
    assert wfg._level_low is None
    assert wfg._level_high is None


# --------------------------------------------------------------------------- #
# prime_pyvisa(): once-only, thread-safe pyvisa import warm-up (Windows AV     #
# guard) — idempotent, and it must NEVER enumerate the bus (no ResourceManager #
# / list_resources). list_visa_resources() routes its first import through it. #
# --------------------------------------------------------------------------- #

import builtins

import devices.waveform_generator as wfg_mod


@pytest.fixture
def reset_prime():
    """Save/restore the module-level prime flags so each test starts un-primed
    and can't leak its state into the rest of the suite."""
    saved = (wfg_mod._pyvisa_primed, wfg_mod._pyvisa_available)
    wfg_mod._pyvisa_primed = False
    wfg_mod._pyvisa_available = None
    try:
        yield
    finally:
        wfg_mod._pyvisa_primed, wfg_mod._pyvisa_available = saved


def test_prime_pyvisa_idempotent_and_available(reset_prime) -> None:
    pytest.importorskip("pyvisa")
    assert wfg_mod.prime_pyvisa() is True
    assert wfg_mod._pyvisa_primed is True
    # Second call returns the cached verdict without re-entering the import.
    assert wfg_mod.prime_pyvisa() is True


def test_prime_pyvisa_never_enumerates_bus(reset_prime, monkeypatch) -> None:
    """The warm-up imports pyvisa but must not touch the VISA bus — no
    ResourceManager construction, no list_resources (instrument-safe)."""
    pyvisa = pytest.importorskip("pyvisa")
    calls: list[str] = []

    class _Boom:
        def __init__(self, *a, **k) -> None:
            calls.append("ResourceManager")

        def list_resources(self, *a, **k):
            calls.append("list_resources")
            return []

    monkeypatch.setattr(pyvisa, "ResourceManager", _Boom)
    assert wfg_mod.prime_pyvisa() is True
    assert calls == [], f"prime_pyvisa touched the bus: {calls}"


def test_prime_pyvisa_reports_unavailable_when_missing(reset_prime, monkeypatch) -> None:
    """pyvisa not installed → prime swallows the ImportError and marks it
    unavailable (callers keep their 'pyvisa missing' behaviour)."""
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "pyvisa" or name.startswith("pyvisa."):
            raise ImportError("simulated missing pyvisa")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert wfg_mod.prime_pyvisa() is False
    assert wfg_mod._pyvisa_available is False


def test_list_visa_resources_raises_when_pyvisa_missing(reset_prime, monkeypatch) -> None:
    from devices.base import DeviceError
    monkeypatch.setattr(wfg_mod, "prime_pyvisa", lambda: False)
    with pytest.raises(DeviceError):
        wfg_mod.list_visa_resources()


def test_list_visa_resources_enumerates_via_prime(reset_prime, monkeypatch) -> None:
    """list_visa_resources primes first (shared once-only guard), then it — and
    only it — creates the ResourceManager and enumerates."""
    pyvisa = pytest.importorskip("pyvisa")
    primed = {"n": 0}
    real_prime = wfg_mod.prime_pyvisa

    def counting_prime():
        primed["n"] += 1
        return real_prime()

    monkeypatch.setattr(wfg_mod, "prime_pyvisa", counting_prime)

    class _FakeRM:
        def list_resources(self):
            return ("USB0::0x1AB1::0x0641::DG4162::INSTR",)

    monkeypatch.setattr(pyvisa, "ResourceManager", lambda *a, **k: _FakeRM())
    res = wfg_mod.list_visa_resources()
    assert res == ["USB0::0x1AB1::0x0641::DG4162::INSTR"]
    assert primed["n"] == 1, "list_visa_resources did not go through prime_pyvisa()"


# --------------------------------------------------------------------------- #
# connect() resolves the armed tri-state from a READ-ONLY :OUTPut:STATe? query  #
# (docs/research/dg4000_tbs1000c_query_forms.md Q1a). Never arms the output.    #
# --------------------------------------------------------------------------- #

class _FakeRM:
    """pyvisa.ResourceManager stand-in: open_resource() hands back the fake.

    Records the address and ``open_timeout`` it was called with, so tests can
    assert the connection-establishment cap is forwarded to viOpen; exposes a
    ``closed`` flag so teardown / no-leak assertions can see the RM was closed.
    """

    def __init__(self, instr) -> None:
        self._instr = instr
        self.open_addr: str | None = None
        self.open_timeout: object = "unset"   # sentinel: connect() never passed it
        self.closed = False

    def open_resource(self, addr, open_timeout=None, **kw):
        self.open_addr = addr
        self.open_timeout = open_timeout
        return self._instr

    def close(self) -> None:
        self.closed = True


def _connect_real_with_fake(monkeypatch, fake: FakeWfgInstr, **kw) -> WaveformGenerator:
    """Drive a real-mode connect() with pyvisa.ResourceManager monkeypatched to
    return *fake* — exercises the full connect path (defaults + armed resolve)."""
    pyvisa = pytest.importorskip("pyvisa")
    monkeypatch.setattr(pyvisa, "ResourceManager", lambda *a, **k: _FakeRM(fake))
    wfg = WaveformGenerator(simulation=False, vendor="rigol",
                            visa_address="USB0::0x1AB1::0x0641::DG4162::INSTR", **kw)
    wfg.connect()
    return wfg


def test_connect_resolves_armed_on(monkeypatch) -> None:
    wfg = _connect_real_with_fake(monkeypatch, FakeWfgInstr(output_state="ON"))
    assert wfg.output_is_on is True


def test_connect_resolves_armed_off(monkeypatch) -> None:
    wfg = _connect_real_with_fake(monkeypatch, FakeWfgInstr(output_state="OFF"))
    assert wfg.output_is_on is False


def test_connect_resolves_armed_header_prefixed(monkeypatch) -> None:
    """A header-ON reply (`:OUTP1:STATE ON`) resolves via the last-token parse."""
    wfg = _connect_real_with_fake(monkeypatch, FakeWfgInstr(output_state=":OUTP1:STATE ON"))
    assert wfg.output_is_on is True


def test_connect_keeps_unknown_on_garbage(monkeypatch, caplog) -> None:
    """An unrecognised reply must NOT be coerced to True/False — the armed state
    stays the honest 'unknown' (None) and warns."""
    with caplog.at_level(logging.WARNING, logger="devices.waveform_generator"):
        wfg = _connect_real_with_fake(monkeypatch, FakeWfgInstr(output_state="RIGOL,junk"))
    assert wfg.output_is_on is None
    assert any("unparseable" in r.message.lower() for r in caplog.records), caplog.text


def test_connect_state_resolve_is_read_only(monkeypatch) -> None:
    """Resolving the armed state must never write OUTPut:STATe — arming stays an
    explicit caller action (laser-safety rule)."""
    fake = FakeWfgInstr(output_state="ON")
    _connect_real_with_fake(monkeypatch, fake)
    assert not any("STAT" in w.upper() for w in fake.writes), fake.writes


@pytest.mark.parametrize("reply,expected", [
    ("ON", True), ("OFF", False),
    ("on\n", True), (" off ", False),
    ("1", True), ("0", False),
    (":OUTP1:STATE ON", True), (":OUTPUT2:STATE OFF", False),
    ("RIGOL,junk", None), ("", None), (None, None),
])
def test_parse_output_state(reply, expected) -> None:
    assert WaveformGenerator._parse_output_state(reply) is expected


def test_simulation_connect_keeps_output_state_false() -> None:
    """Sim backend has no retained state — connect() leaves a known-off (False),
    consistent with the real path resolving to a concrete True/False."""
    wfg = WaveformGenerator(simulation=True)
    assert wfg.output_is_on is None
    wfg.connect()
    assert wfg.output_is_on is False


# --------------------------------------------------------------------------- #
# connect() caps the connection-establishment wait (open_timeout) and fails    #
# safe: an unreachable TCPIP…::INSTR must not block viOpen for the OS socket    #
# timeout (the "connect freezes the app completely" report), and a failed open #
# must leak no half-open ResourceManager / session (rule 5).                    #
# --------------------------------------------------------------------------- #

def test_connect_forwards_open_timeout_to_open_resource(monkeypatch) -> None:
    """connect() must pass open_timeout (= timeout_ms) to open_resource so
    viOpen is bounded — without it an offline LAN target blocks for minutes."""
    pyvisa = pytest.importorskip("pyvisa")
    rm = _FakeRM(FakeWfgInstr(output_state="OFF"))
    monkeypatch.setattr(pyvisa, "ResourceManager", lambda *a, **k: rm)
    wfg = WaveformGenerator(simulation=False, vendor="rigol",
                            visa_address="TCPIP0::192.168.0.10::INSTR",
                            timeout_ms=4000)
    wfg.connect()
    assert rm.open_timeout == 4000, rm.open_timeout   # not the "unset" sentinel
    assert rm.open_addr == "TCPIP0::192.168.0.10::INSTR"
    assert wfg._instr.timeout == 4000                 # per-op I/O timeout too


def test_connect_open_failure_tears_down_and_no_leak(monkeypatch) -> None:
    """A failed / timed-out viOpen must raise DeviceError AND leave no half-open
    ResourceManager or session behind — a retry must start clean (fail-safe)."""
    from devices.base import DeviceError
    pyvisa = pytest.importorskip("pyvisa")

    class _BoomRM:
        def __init__(self) -> None:
            self.closed = False

        def open_resource(self, addr, open_timeout=None, **kw):
            raise OSError("simulated viOpen timeout — instrument offline")

        def close(self) -> None:
            self.closed = True

    boom = _BoomRM()
    monkeypatch.setattr(pyvisa, "ResourceManager", lambda *a, **k: boom)
    wfg = WaveformGenerator(simulation=False, vendor="rigol",
                            visa_address="TCPIP0::192.168.0.10::INSTR")
    with pytest.raises(DeviceError):
        wfg.connect()
    assert wfg._instr is None
    assert wfg._rm is None          # torn down on the failure path, not leaked
    assert boom.closed              # the half-open RM was closed
    assert wfg.connected is False
