"""Blackfly camera driver tests — simulation + mockable hardware paths only.

Covers two bench-diagnosed robustness fixes (real BFLY-U3-23S6M, SN 19112408):

  1. GenTL producer env auto-locate: ``_ensure_gentl_env`` points
     ``FLIR_GENTL64_CTI_VS140`` at an existing .cti so ``System.GetInstance()``
     works without restarting the process.  Tested as a pure function with an
     injected env dict and a fake .cti under ``tmp_path`` — no PySpin, no SDK.

  2. Binning writability guard: a non-writable ``BinningHorizontal`` node is
     skipped (INFO) instead of raising the GenICam AccessException seen on the
     bench.  Exercised with a fake QuickSpin cam + fake PySpin namespace, so no
     hardware and no PySpin install are required.

No test touches real hardware; the simulation smoke test uses the default
simulated backend.
"""
import logging
import os
import types

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from devices.camera_blackfly import (  # noqa: E402
    BlackflyCamera,
    _default_gentl_probe_paths,
    _ensure_gentl_env,
    _GENTL_ENV_VAR,
    _GENTL_PATH_VAR,
)


# --------------------------------------------------------------------------- #
# Fix 2 — GenTL env auto-locate                                               #
# --------------------------------------------------------------------------- #

class TestEnsureGentlEnv:
    def test_sets_var_when_probe_path_exists_and_unset(self, tmp_path):
        cti = tmp_path / "FLIR_GenTL_v140.cti"
        cti.write_bytes(b"\x00")           # fake producer file on disk
        env: dict = {}                     # var unset

        changed = _ensure_gentl_env([str(cti)], env)

        assert env[_GENTL_ENV_VAR] == str(cti)
        assert changed[_GENTL_ENV_VAR] == str(cti)
        # its directory is registered on the GenTL search path
        assert str(tmp_path) in env[_GENTL_PATH_VAR].split(";")
        assert changed[_GENTL_PATH_VAR] == env[_GENTL_PATH_VAR]

    def test_noop_when_already_set(self, tmp_path):
        cti = tmp_path / "FLIR_GenTL_v140.cti"
        cti.write_bytes(b"\x00")
        env = {_GENTL_ENV_VAR: r"X:\already\set.cti"}

        changed = _ensure_gentl_env([str(cti)], env)

        assert changed == {}                       # nothing overridden
        assert env[_GENTL_ENV_VAR] == r"X:\already\set.cti"
        assert _GENTL_PATH_VAR not in env

    def test_noop_and_no_raise_when_nothing_found(self, tmp_path):
        missing = tmp_path / "does_not_exist.cti"
        env: dict = {}

        changed = _ensure_gentl_env([str(missing)], env)   # must not raise

        assert changed == {}
        assert _GENTL_ENV_VAR not in env

    def test_bad_probe_entry_is_skipped_not_raised(self):
        # ``None`` / junk entries must never blow up the probe loop.
        env: dict = {}
        changed = _ensure_gentl_env([None, "", 12345], env)  # type: ignore[list-item]
        assert changed == {}
        assert _GENTL_ENV_VAR not in env

    def test_empty_string_var_is_treated_as_unset(self, tmp_path):
        cti = tmp_path / "FLIR_GenTL_v140.cti"
        cti.write_bytes(b"\x00")
        env = {_GENTL_ENV_VAR: "   "}       # whitespace-only == unset

        changed = _ensure_gentl_env([str(cti)], env)

        assert changed[_GENTL_ENV_VAR] == str(cti)


class TestDefaultGentlProbePaths:
    def test_includes_confirmed_flir_path(self):
        paths = _default_gentl_probe_paths(env={})
        assert any(
            p == r"C:\Program Files\FLIR Systems\Spinnaker\cti\vs2015\FLIR_GenTL_v140.cti"
            for p in paths
        )

    def test_honors_genicam_gentl64_path_dirs(self):
        env = {_GENTL_PATH_VAR: r"D:\producers\a;D:\producers\b"}
        paths = _default_gentl_probe_paths(env=env)
        joined = "\n".join(paths)
        assert "FLIR_GenTL_v140.cti" in joined
        assert any(p.startswith(r"D:\producers\a") for p in paths)
        assert any(p.startswith(r"D:\producers\b") for p in paths)


# --------------------------------------------------------------------------- #
# Fix 1 — binning writability guard                                           #
# --------------------------------------------------------------------------- #

class _FakeNode:
    """Duck-typed QuickSpin node with injectable availability/writability."""

    def __init__(self, writable=True, available=True):
        self.writable = writable
        self.available = available
        self.value = None

    def SetValue(self, v):
        if not self.writable:
            # Mirror the real GenICam::AccessException the bench hit.
            raise RuntimeError("GenICam::AccessException= Node is not writable")
        self.value = v


class _FakeCam:
    def __init__(self, h_writable=True, v_writable=True):
        self.BinningHorizontal = _FakeNode(writable=h_writable)
        self.BinningVertical = _FakeNode(writable=v_writable)


def _fake_pyspin():
    """Minimal PySpin namespace exposing the node-state predicates we use."""
    return types.SimpleNamespace(
        IsAvailable=lambda n: getattr(n, "available", True),
        IsWritable=lambda n: getattr(n, "writable", True),
        IsReadable=lambda n: True,
    )


def _mock_hw_camera(cam):
    """A non-sim camera wired to a fake cam + fake PySpin, not connected to HW."""
    c = BlackflyCamera(simulation=False)
    c._cam = cam
    c._pyspin = _fake_pyspin()
    c._acquiring = False          # binning is set while acquisition is stopped
    return c


class TestBinningWritabilityGuard:
    def test_nonwritable_horizontal_is_skipped_not_raised(self, caplog):
        cam = _FakeCam(h_writable=False, v_writable=True)
        c = _mock_hw_camera(cam)

        with caplog.at_level(logging.INFO, logger="devices.camera_blackfly"):
            c.set_binning(2)                       # must NOT raise

        assert cam.BinningVertical.value == 2      # writable node was set
        assert cam.BinningHorizontal.value is None  # read-only node skipped
        text = caplog.text.lower()
        assert "binninghorizontal" in text and "not writable" in text
        # never escalated to a warning
        assert not any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_both_writable_sets_both(self):
        cam = _FakeCam(h_writable=True, v_writable=True)
        c = _mock_hw_camera(cam)
        c.set_binning(4)
        assert cam.BinningVertical.value == 4
        assert cam.BinningHorizontal.value == 4

    def test_unavailable_node_is_skipped(self, caplog):
        cam = _FakeCam()
        cam.BinningHorizontal.available = False
        c = _mock_hw_camera(cam)
        with caplog.at_level(logging.INFO, logger="devices.camera_blackfly"):
            c.set_binning(2)
        assert cam.BinningHorizontal.value is None
        assert "not available" in caplog.text.lower()


# --------------------------------------------------------------------------- #
# Binning MODE — prefer Average over Sum (Kaya's "white screen at binning 2/4") #
# --------------------------------------------------------------------------- #

class _FakeCamWithModes(_FakeCam):
    """Fake QuickSpin cam that also exposes the binning-mode enum nodes."""

    def __init__(self, h_writable=True, v_writable=True,
                 mode_writable=True, mode_available=True):
        super().__init__(h_writable=h_writable, v_writable=v_writable)
        self.BinningHorizontalMode = _FakeNode(
            writable=mode_writable, available=mode_available)
        self.BinningVerticalMode = _FakeNode(
            writable=mode_writable, available=mode_available)


def _fake_pyspin_with_modes():
    ns = _fake_pyspin()
    # Enum entry constants (opaque ints, like the real PySpin module).
    ns.BinningHorizontalMode_Average = 1
    ns.BinningVerticalMode_Average = 1
    return ns


class TestBinningModeAverage:
    def test_set_binning_selects_average_mode_on_hw(self):
        cam = _FakeCamWithModes()
        c = BlackflyCamera(simulation=False)
        c._cam = cam
        c._pyspin = _fake_pyspin_with_modes()
        c._acquiring = False

        c.set_binning(2)

        assert cam.BinningVerticalMode.value == 1     # Average enum written
        assert cam.BinningHorizontalMode.value == 1
        assert c._binning_mode == "Average"

    def test_missing_mode_node_is_skipped_not_raised(self, caplog):
        # A model without the mode nodes must not break set_binning.
        cam = _FakeCam()                              # no *Mode attributes
        c = BlackflyCamera(simulation=False)
        c._cam = cam
        c._pyspin = _fake_pyspin_with_modes()
        c._acquiring = False
        with caplog.at_level(logging.INFO, logger="devices.camera_blackfly"):
            c.set_binning(2)                          # must NOT raise
        assert cam.BinningVertical.value == 2
        assert "absent" in caplog.text.lower()
        assert c._binning_mode == "Average"           # state still updated

    def test_missing_enum_constant_is_skipped(self, caplog):
        cam = _FakeCamWithModes()
        c = BlackflyCamera(simulation=False)
        c._cam = cam
        c._pyspin = _fake_pyspin()                    # no *_Average constants
        c._acquiring = False
        with caplog.at_level(logging.INFO, logger="devices.camera_blackfly"):
            c.set_binning(2)
        assert cam.BinningVerticalMode.value is None  # enum absent → skipped
        assert "enum entry absent" in caplog.text.lower()


# --------------------------------------------------------------------------- #
# Simulation path stays green (default runnable, no hardware)                  #
# --------------------------------------------------------------------------- #

class TestSimulationPath:
    def test_connect_and_grab_frame(self):
        c = BlackflyCamera(simulation=True)
        c.connect()
        assert c.connected
        frame, meta = c.get_frame_with_meta()
        assert frame.ndim == 2
        assert frame.dtype == np.uint8            # default Mono8
        assert meta.width == frame.shape[1]
        c.disconnect()

    def test_set_binning_noop_without_camera(self):
        c = BlackflyCamera(simulation=True)
        c.connect()
        c.set_binning(2)                          # _cam is None → benign no-op
        assert c._binning == 2
        c.disconnect()

    def test_set_binning_selects_average_mode_on_sim(self):
        c = BlackflyCamera(simulation=True)
        c.connect()
        assert c._binning_mode == "Sum"           # camera's raw default
        c.set_binning(2)
        assert c._binning == 2
        assert c._binning_mode == "Average"       # driver prefers Average
        c.disconnect()

    def test_sim_binning_reduces_frame_dimensions(self):
        c = BlackflyCamera(simulation=True)
        c.connect()
        full, _ = c.get_frame_with_meta()
        c.set_binning(2)
        binned, meta = c.get_frame_with_meta()
        assert binned.shape[0] == full.shape[0] // 2
        assert binned.shape[1] == full.shape[1] // 2
        assert meta.width == binned.shape[1]      # meta tracks binned size
        c.disconnect()

    def test_sim_sum_saturates_but_average_does_not(self):
        """The sim must reproduce the Sum-vs-Average intensity distinction so a
        regression that drops the mode selection is caught: Sum at 2x2 pins the
        beam to the format max, Average keeps it in range."""
        c = BlackflyCamera(simulation=True, pixel_format="Mono16")
        c.connect()
        c._binning = 2

        c._binning_mode = "Sum"
        summed, _ = c.get_frame_with_meta()
        c._binning_mode = "Average"
        averaged, _ = c.get_frame_with_meta()

        assert summed.max() == 65535              # Sum saturates the beam core
        assert averaged.max() < 65535             # Average stays in range
        c.disconnect()

    def test_sim_sum_frame_not_white_after_display_path(self):
        """Binning-2 Sum-mode sim frame → the panel display path (autoscale)
        must NOT yield a uniform white screen: background stays dark, only the
        saturated beam clips (the robustness fix for Kaya's white-screen bug)."""
        from gui.camera_panel import CameraPanel

        c = BlackflyCamera(simulation=True, pixel_format="Mono16")
        c.connect()
        c._binning = 2
        c._binning_mode = "Sum"                   # force the raw-default bug
        frame, _ = c.get_frame_with_meta()

        disp = CameraPanel._to_display_8bit(frame)
        assert disp.dtype == np.uint8
        assert disp.min() < 32                    # dark background survives
        assert not np.all(disp == 255)            # not a white screen
        c.disconnect()
