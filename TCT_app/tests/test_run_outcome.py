"""The file must say how the run ended.

Before this, HDF5Writer.close() wrote only ``stop_time``: a trip-aborted run,
an operator abort, and a clean short run were byte-for-byte indistinguishable
to an analyst opening the file — no outcome, no abort reason, anywhere.

Covers both layers:

* ``HDF5Writer.set_outcome`` / ``close`` directly (data/hdf5_writer.py) —
  including the single most important case: a writer closed WITHOUT a prior
  ``set_outcome()`` call (crash, killed process, a missed call site) must
  read back as ``"unknown"``, never ``"finished"``.
* ``ScanController._end_run`` wiring (controller/scan_controller.py) — a
  real finished scan, a real operator abort, and a real trip-aborted scan
  (same simulated-trip idiom as tests/test_trip_detection.py) all produce
  the right ``outcome`` / ``abort_reason`` on disk.

Everything below runs on fully-simulated backends; no hardware.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time

import h5py
import pytest
import yaml

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import ScanController, ScanConfig
from devices.bias_supply_base import BiasReading
from data.hdf5_writer import HDF5Writer
from data.save_options import SaveOptions


# =========================================================================== #
# Layer 1 — HDF5Writer.set_outcome / close, in isolation                      #
# =========================================================================== #

def test_finished_writer_writes_outcome_finished_no_abort_reason(tmp_path):
    writer = HDF5Writer(tmp_path / "run_00001", save_options=SaveOptions())
    writer.open()
    writer.set_outcome("finished")
    writer.close()

    with h5py.File(tmp_path / "run_00001" / "waveforms.h5", "r") as f:
        assert f.attrs["outcome"] == "finished"
        assert f.attrs["abort_reason"] == ""


def test_aborted_writer_writes_outcome_aborted_with_reason(tmp_path):
    writer = HDF5Writer(tmp_path / "run_00002", save_options=SaveOptions())
    writer.open()
    writer.set_outcome("aborted", reason="Operator abort")
    writer.close()

    with h5py.File(tmp_path / "run_00002" / "waveforms.h5", "r") as f:
        assert f.attrs["outcome"] == "aborted"
        assert f.attrs["abort_reason"] == "Operator abort"


def test_error_writer_writes_outcome_error_with_reason(tmp_path):
    writer = HDF5Writer(tmp_path / "run_00003", save_options=SaveOptions())
    writer.open()
    writer.set_outcome("error", reason="DeviceError: scope timeout")
    writer.close()

    with h5py.File(tmp_path / "run_00003" / "waveforms.h5", "r") as f:
        assert f.attrs["outcome"] == "error"
        assert "scope timeout" in f.attrs["abort_reason"]


def test_set_outcome_rejects_unknown_value(tmp_path):
    writer = HDF5Writer(tmp_path / "run_00004", save_options=SaveOptions())
    writer.open()
    with pytest.raises(ValueError):
        writer.set_outcome("success!")   # not one of the valid outcomes
    writer.close()


def test_writer_closed_without_outcome_reads_unknown_never_finished(tmp_path):
    """THE most important test in this file.

    A writer that is opened, used, and closed WITHOUT ever calling
    set_outcome() (a crash, a killed process, a forgotten call site) must
    read back as "unknown" — the honest default for "we don't know how this
    run ended" — and must NEVER be "finished".  A crashed run must not be
    able to masquerade as a clean one.
    """
    writer = HDF5Writer(tmp_path / "run_00005", save_options=SaveOptions())
    writer.open()
    # No set_outcome() call at all.
    writer.close()

    with h5py.File(tmp_path / "run_00005" / "waveforms.h5", "r") as f:
        assert f.attrs["outcome"] == "unknown"
        assert f.attrs["outcome"] != "finished"


def test_outcome_survives_run_metadata_disabled(tmp_path):
    """outcome/abort_reason are root attrs, not gated behind the optional
    'run_metadata' save toggle — they are integrity information, not
    reconstructable scan config, so they must be written even when
    run_metadata is off (and /run_info therefore never exists at all)."""
    opts = SaveOptions(run_metadata=False)
    writer = HDF5Writer(tmp_path / "run_00006", save_options=opts)
    writer.open()
    writer.set_outcome("aborted", reason="Slow-control ALARM")
    writer.close()

    with h5py.File(tmp_path / "run_00006" / "waveforms.h5", "r") as f:
        assert "run_info" not in f
        assert f.attrs["outcome"] == "aborted"
        assert f.attrs["abort_reason"] == "Slow-control ALARM"


# =========================================================================== #
# Layer 2 — ScanController._end_run wiring, on real (simulated) runs          #
# =========================================================================== #

@pytest.fixture
def make_ctrl(tmp_path):
    """(dm, ctrl, sm) on fully-simulated backends, state READY.

    Same harness idiom as tests/test_trip_detection.py.
    """
    created: list = []

    def _factory():
        cfg = {
            "oscilloscope":       {"backend": "visa", "simulation": True},
            "motor_stage":        {"backend": "simulated"},
            "intensity_monitor":  {"backend": "simulated"},
            "camera":             {"simulation": True},
            "waveform_generator": {"simulation": True},
            "bias_supply":        {"backend": "simulated"},
            "output":             {"data_dir": str(tmp_path / "runs")},
        }
        path = tmp_path / "devices.yaml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        dm = DeviceManager(config_path=str(path))
        assert dm.config_errors() == [], dm.config_errors()
        assert all(v == "ok" for v in dm.connect_all().values())
        dm.motor.home()
        sm = StateMachine()
        for st in (AppState.CONNECTED, AppState.HOMED,
                   AppState.CONFIGURED, AppState.READY):
            sm.transition(st)
        ctrl = ScanController(dm, sm)
        ctrl._PAUSE_POLL_S = 0.02        # fast park supervision for tests
        created.append(dm)
        return dm, ctrl, sm

    yield _factory
    for dm in created:
        dm.disconnect_all()


def _xy(**over) -> ScanConfig:
    """A 4-point XY map (fast: no settle)."""
    d = dict(x_start_mm=0.0, x_stop_mm=0.1, x_step_mm=0.1,
             y_start_mm=0.0, y_stop_mm=0.1, y_step_mm=0.1,
             n_averages=1, settle_time_s=0.0)
    d.update(over)
    return ScanConfig(**d)


def _join(ctrl, timeout=20.0) -> None:
    if ctrl._thread is not None:
        ctrl._thread.join(timeout=timeout)
        assert not ctrl._thread.is_alive(), "worker thread did not finish"


def _outcome_attrs(ctrl) -> dict:
    path = ctrl.last_run_path
    assert path is not None and path.exists(), "run file was never written"
    with h5py.File(path, "r") as f:
        return {"outcome": f.attrs.get("outcome"),
                "abort_reason": f.attrs.get("abort_reason")}


def _reading(**over) -> BiasReading:
    d = dict(voltage_V=-100.0, current_A=2e-9, compliant=False,
             status_word=0x0008, tripped=False, output_on_hw=True)
    d.update(over)
    return BiasReading(**d)


def test_finished_scan_writes_outcome_finished(make_ctrl):
    dm, ctrl, sm = make_ctrl()

    ctrl.start(_xy())
    _join(ctrl)

    assert sm.state is AppState.FINISHED
    attrs = _outcome_attrs(ctrl)
    assert attrs["outcome"] == "finished"
    assert attrs["abort_reason"] == ""


def test_operator_abort_writes_outcome_aborted_with_reason(make_ctrl):
    dm, ctrl, sm = make_ctrl()
    stopped = threading.Event()
    ctrl.on_point_done = lambda r: (stopped.set(), ctrl.abort())

    ctrl.start(_xy())
    _join(ctrl)

    assert stopped.is_set()
    assert sm.state is AppState.ABORTED
    attrs = _outcome_attrs(ctrl)
    assert attrs["outcome"] == "aborted"
    assert attrs["abort_reason"]                  # non-empty
    assert "abort" in attrs["abort_reason"].lower()


def test_trip_aborted_scan_writes_outcome_aborted_naming_the_trip(make_ctrl):
    """Same simulated-trip idiom as
    test_trip_detection.py::test_latched_trip_midscan_aborts_and_failsafes —
    the file must name the trip, not just say "aborted"."""
    dm, ctrl, sm = make_ctrl()
    bias = dm.bias_supply
    bias.ramp_to(-100.0, step_V=100.0, delay_s=0.0)

    tripped_now = threading.Event()
    ctrl.on_point_done = lambda r: tripped_now.set()

    def tripping_read():
        if not tripped_now.is_set():
            return _reading()
        return _reading(voltage_V=0.0, current_A=1e-12, compliant=False,
                        status_word=0x0810, tripped=True, output_on_hw=False)
    bias.read = tripping_read

    ctrl.start(_xy())
    _join(ctrl)

    assert sm.state is AppState.ABORTED
    attrs = _outcome_attrs(ctrl)
    assert attrs["outcome"] == "aborted"
    assert "trip" in attrs["abort_reason"].lower()


# =========================================================================== #
# Round trip — the value is readable back from the HDF5 (explicit, minimal)   #
# =========================================================================== #

def test_outcome_round_trip_readable_from_hdf5(tmp_path):
    writer = HDF5Writer(tmp_path / "run_rt", save_options=SaveOptions())
    writer.open()
    writer.set_outcome("aborted", reason="Slow-control ALARM: temperature_C")
    writer.close()

    with h5py.File(tmp_path / "run_rt" / "waveforms.h5", "r") as f:
        outcome = f.attrs["outcome"]
        reason = f.attrs["abort_reason"]

    assert isinstance(outcome, str)
    assert outcome == "aborted"
    assert isinstance(reason, str)
    assert reason == "Slow-control ALARM: temperature_C"
