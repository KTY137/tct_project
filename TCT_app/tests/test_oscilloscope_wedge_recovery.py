"""Headless regression tests for the 2026-07-06 scope wedge-recovery fixes.

These exercise the exact behaviours that fixed the bench failure — without
hardware — by injecting a fake VISA instrument into the driver:

  * read_channel() fails fast (no CURVE?) when a channel's display is off,
    including when the scope answers with a header prefix (HEADer ON);
  * a failed CURVE? triggers a VISA device-clear (_recover_session) so the
    session self-heals instead of staying wedged;
  * is_alive() reports the link dead (and flips the flag) when *STB? fails;
  * _ScopeReader.read_once delivers the channels that DID read even when
    another channel raises (per-channel fault isolation).
"""
import numpy as np
import pytest

from devices.base import DeviceError
from devices.oscilloscope import Oscilloscope


class FakeInstr:
    """Minimal pyvisa-resource stand-in: scripted query replies + call log."""

    def __init__(self, replies: dict[str, str] | None = None,
                 curve_error: Exception | None = None,
                 stb_error: Exception | None = None) -> None:
        self.timeout = 5000
        self._replies = replies or {}
        self._curve_error = curve_error
        self._stb_error = stb_error
        self.writes: list[str] = []
        self.cleared = 0

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)

    def query(self, cmd: str) -> str:
        if cmd == "*STB?" and self._stb_error is not None:
            raise self._stb_error
        return self._replies.get(cmd, "0") + "\n"

    def query_binary_values(self, cmd, datatype="b", is_big_endian=True):
        if self._curve_error is not None:
            raise self._curve_error
        return [0, 1, 2, 3]

    def clear(self) -> None:
        self.cleared += 1

    def close(self) -> None:
        pass


def _wired_scope(fake: FakeInstr) -> Oscilloscope:
    """A real-mode Oscilloscope with the fake instrument injected as connected."""
    scope = Oscilloscope(simulation=False, vendor="tektronix")
    scope._instr = fake
    scope._connected = True
    return scope


def test_read_channel_fails_fast_when_display_off_no_curve() -> None:
    fake = FakeInstr(replies={"SELect:CH2?": "0"})
    scope = _wired_scope(fake)
    with pytest.raises(DeviceError, match="not active"):
        scope.read_channel(2)
    # The critical property: CURVE? must NOT have been issued on the off
    # channel (that is what wedges the output queue).
    assert "CURVE?" not in fake.writes


def test_read_channel_precheck_survives_header_on_prefix() -> None:
    # With HEADer ON the scope answers ":SELECT:CH2 0"; the precheck must
    # still recognise the channel as off (parses the trailing token).
    fake = FakeInstr(replies={"SELect:CH2?": ":SELECT:CH2 0"})
    scope = _wired_scope(fake)
    with pytest.raises(DeviceError, match="not active"):
        scope.read_channel(2)


def test_failed_curve_triggers_device_clear() -> None:
    import pyvisa.errors  # noqa: F401  (import guard; may be absent)

    fake = FakeInstr(replies={"SELect:CH1?": "1"},
                     curve_error=RuntimeError("VI_ERROR_TMO"))
    scope = _wired_scope(fake)
    with pytest.raises(DeviceError, match="waveform read failed"):
        scope.read_channel(1)
    # Session must have been cleared so the next read isn't garbled.
    assert fake.cleared >= 1


def test_is_alive_marks_disconnected_on_stb_failure() -> None:
    fake = FakeInstr(stb_error=RuntimeError("VI_ERROR_TMO"))
    scope = _wired_scope(fake)
    assert scope.is_alive() is False
    assert scope.connected is False        # flag flipped, fail-safe


def test_is_alive_true_on_healthy_fake_link() -> None:
    fake = FakeInstr(replies={"*STB?": "0"})
    scope = _wired_scope(fake)
    assert scope.is_alive() is True
    assert scope.connected is True


# --------------------------------------------------------------------------- #
# _ScopeReader per-channel fault isolation (needs a QApplication)             #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeScope:
    """Stand-in for Oscilloscope: CH1 reads fine, CH2 raises."""
    connected = True

    def read_channel(self, ch):
        if ch == 2:
            raise DeviceError("CH2 is not active on the oscilloscope")
        t = np.linspace(0, 1e-7, 100)
        return t, np.zeros_like(t)


def test_read_once_isolates_a_failing_channel(qapp) -> None:
    from gui.scope_panel import _ScopeReader

    reader = _ScopeReader(_FakeScope())
    reader.set_enabled_channels(frozenset({1, 2}))

    acquired: list[dict] = []
    failed: list[str] = []
    reader.acquired.connect(acquired.append)
    reader.failed.connect(failed.append)

    reader.read_once()

    # CH1 still delivered despite CH2 failing — the bench "nothing plots" bug.
    assert acquired and 1 in acquired[0] and 2 not in acquired[0]
    assert failed and "CH2" in failed[0]
