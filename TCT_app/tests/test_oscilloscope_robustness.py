"""Unit tests for the oscilloscope driver robustness fixes (2026-07-06):
channel-count heuristic, averaging state, and simulation-mode behaviour.
The live-hardware behaviour (session recovery, channel-active precheck)
is covered by the bench validation script — these tests stay headless.
"""
import numpy as np
import pytest

from devices.oscilloscope import Oscilloscope, tek_channel_count_from_idn


@pytest.mark.parametrize(
    "idn, expected",
    [
        ("TEKTRONIX,TBS1052C,C010198,CF:91.1CT FV:v1.29.30", 2),
        ("TEKTRONIX,TBS1102C,C000001,CF:91.1CT", 2),
        ("TEKTRONIX,MSO5204B,SN123,FW1", 4),
        ("TEKTRONIX,DPO5104,SN123,FW1", 4),
        # TDS is deliberately excluded (unreliable last-digit naming) → None,
        # so the caller keeps its default / explicit n_channels instead.
        ("TEKTRONIX,TDS2024C,SN123,FW1", None),
        ("KEYSIGHT,DSOX1204A,SN,FW", None),   # not a Tek model string
        ("", None),
    ],
)
def test_tek_channel_count_from_idn(idn: str, expected: int | None) -> None:
    assert tek_channel_count_from_idn(idn) == expected


def test_n_channels_config_default() -> None:
    assert Oscilloscope(simulation=True).n_channels == 4
    assert Oscilloscope(simulation=True, n_channels=2).n_channels == 2


def test_set_averaging_updates_state_in_simulation() -> None:
    scope = Oscilloscope(simulation=True, n_averages=1)
    scope.set_averaging(16)
    assert scope.n_averages == 16
    scope.set_averaging(0)          # clamped to >= 1
    assert scope.n_averages == 1


def test_simulation_read_channel_still_works() -> None:
    scope = Oscilloscope(simulation=True)
    scope.connect()
    t, v = scope.read_channel(1)
    assert len(t) == len(v) > 0
    assert np.all(np.isfinite(v))


def test_set_channel_display_noop_in_simulation() -> None:
    scope = Oscilloscope(simulation=True)
    scope.connect()
    scope.set_channel_display(2, True)   # must not raise or touch hardware


def test_is_alive_tracks_connected_flag_in_simulation() -> None:
    scope = Oscilloscope(simulation=True)
    assert scope.is_alive() is False          # never connected
    scope.connect()
    assert scope.is_alive() is True
    scope.disconnect()
    assert scope.is_alive() is False


def test_is_alive_false_when_real_session_is_gone() -> None:
    # A real-mode scope whose VISA session vanished must fail safe.
    scope = Oscilloscope(simulation=False)
    scope._connected = True                   # stale flag, no _instr
    assert scope.is_alive() is False
    assert scope.connected is False           # flag flipped, not just reported
