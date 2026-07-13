"""Regression test for the MultiBiasPanel 'ALL OUTPUTS OFF' fail-safe.

Guards the HV-safety property (Mary review, 2026-07-06): a ramp_to() failure
on one channel must NOT skip that channel's output_off(), and must NOT stop
the other channels from being shut down. Errors are aggregated and raised.

_do_all_off is a pure @staticmethod, so no QApplication is needed.
"""
import pytest

from gui.multi_bias_panel import MultiBiasPanel


class _FakeChannel:
    def __init__(self, channel: int, raise_on_ramp: bool = False):
        self.channel = channel
        self._raise_on_ramp = raise_on_ramp
        self.ramped = False
        self.output_off_called = False

    def ramp_to(self, target_V, step_V=5.0, delay_s=0.1):
        if self._raise_on_ramp:
            raise RuntimeError("comms glitch during ramp")
        self.ramped = True

    def output_off(self):
        self.output_off_called = True


def test_all_off_disables_output_even_when_ramp_raises():
    bad = _FakeChannel(0, raise_on_ramp=True)
    good = _FakeChannel(1)

    with pytest.raises(RuntimeError) as exc:
        MultiBiasPanel._do_all_off([bad, good])

    # The safety-critical action ran on BOTH channels despite bad's ramp error.
    assert bad.output_off_called, "output_off must run even if ramp_to raised"
    assert good.output_off_called and good.ramped
    # The failure is surfaced (not swallowed) and names the offending channel.
    assert "CH0" in str(exc.value)


def test_all_off_clean_when_every_channel_ok():
    chans = [_FakeChannel(0), _FakeChannel(1)]
    MultiBiasPanel._do_all_off(chans)          # must not raise
    assert all(c.ramped and c.output_off_called for c in chans)


def test_all_off_aggregates_output_off_failure():
    class _OffFails(_FakeChannel):
        def output_off(self):
            raise RuntimeError("output-off rejected")

    ch = _OffFails(2)
    with pytest.raises(RuntimeError) as exc:
        MultiBiasPanel._do_all_off([ch])
    assert "CH2" in str(exc.value)
