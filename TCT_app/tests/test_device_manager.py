"""DeviceManager construction wiring — config → device-constructor plumbing.

Fully headless / simulated: builds a DeviceManager from an in-memory
devices.yaml and asserts the constructed device objects carry the config values.
No hardware, no VISA/serial, no Qt — safe with a real instrument attached.

Covers Paul's D4 rider: the reference-channel ScopeChannelMonitor must use the
SAME baseline-sample count as the DUT waveform analysis, taken from the existing
``analysis.baseline_samples`` config value (option b — no new config key).
"""
from __future__ import annotations

import yaml

from controller.device_manager import DeviceManager
from devices.intensity_scope_ch import ScopeChannelMonitor


def _cfg_path(tmp_path, *, analysis=None) -> str:
    """Write a fully-simulated devices.yaml with a scope_channel intensity
    monitor (so a real ScopeChannelMonitor is constructed) and return its path.
    An optional ``analysis`` block is added verbatim when provided."""
    cfg = {
        "oscilloscope":       {"backend": "visa", "simulation": True},
        "motor_stage":        {"backend": "simulated"},
        "intensity_monitor":  {"backend": "scope_channel"},
        "camera":             {"simulation": True},
        "waveform_generator": {"simulation": True},
        "bias_supply":        {"backend": "simulated"},
        "output":             {"data_dir": str(tmp_path / "runs")},
    }
    if analysis is not None:
        cfg["analysis"] = analysis
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


def test_scope_channel_monitor_gets_analysis_baseline_samples(tmp_path):
    """analysis.baseline_samples is plumbed into the ScopeChannelMonitor so the
    reference channel is corrected with the same window the DUT analysis uses."""
    dm = DeviceManager(
        config_path=_cfg_path(tmp_path, analysis={"baseline_samples": 42})
    )
    assert dm.config_errors() == []
    assert isinstance(dm.intensity_monitor, ScopeChannelMonitor)
    assert dm.intensity_monitor._baseline_samples == 42


def test_scope_channel_monitor_baseline_samples_defaults_when_absent(tmp_path):
    """Absent analysis.baseline_samples → the monitor's own default (20), so
    behaviour is unchanged for every config that never set the key."""
    dm = DeviceManager(config_path=_cfg_path(tmp_path))   # no analysis block
    assert dm.config_errors() == []
    assert isinstance(dm.intensity_monitor, ScopeChannelMonitor)
    assert dm.intensity_monitor._baseline_samples == 20
