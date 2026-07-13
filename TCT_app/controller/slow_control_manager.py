"""
Slow-control channel manager.

Owns a list of SlowControlChannel instances built from configs/devices.yaml.
The rest of the application (MonitorPanel, InfluxWriter, HDF5Writer) calls
read_all() and never touches individual channels directly.

Adding a new sensor type
------------------------
1. Subclass SlowControlChannel and implement read() / connect() / disconnect().
2. Add an entry to SLOW_CONTROL_BACKENDS below.
3. Add a channel entry under slow_control.channels in configs/devices.yaml.

That's all — no other file needs to change.
"""
from __future__ import annotations

import logging
from typing import Any

from devices.slow_control_base import (
    AlarmThresholds,
    SlowControlChannel,
    SlowControlReading,
)
from devices.slow_control_simulated import SimulatedSlowChannel

logger = logging.getLogger(__name__)

# ── Backend registry ─────────────────────────────────────────────────────────
# Map the "backend" string in devices.yaml to a factory function
# (name, unit, thresholds, **extra_kwargs) → SlowControlChannel instance.
#
# Add new entries here when you create new SlowControlChannel subclasses.

def _make_simulated(
    name: str, unit: str, thresholds: AlarmThresholds, cfg: dict
) -> SlowControlChannel:
    return SimulatedSlowChannel(
        name=name,
        unit=unit,
        nominal=cfg.get("nominal", 25.0),
        noise=cfg.get("noise", 0.5),
        drift_amplitude=cfg.get("drift_amplitude", 2.0),
        drift_period_s=cfg.get("drift_period_s", 60.0),
        thresholds=thresholds,
    )


SLOW_CONTROL_BACKENDS: dict[
    str,
    Any,  # callable(name, unit, thresholds, cfg) → SlowControlChannel
] = {
    "simulated": _make_simulated,
    # Future backends — uncomment and implement:
    # "serial_pt100":       _make_serial_pt100,
    # "serial_sht31":       _make_serial_sht31,    # SHT31 temp+humidity sensor
    # "keithley_smu":       _make_keithley_smu,    # bias voltage / leakage current
    # "ni_daq":             _make_ni_daq,           # NI-DAQ analog input
    # "modbus_register":    _make_modbus,           # generic Modbus TCP/RTU
}


class SlowControlManager:
    """
    Central manager for all slow-control channels.

    Built from the slow_control section of configs/devices.yaml.
    The GUI panel and InfluxDB writer hold a reference to this manager,
    never to individual channel objects.
    """

    def __init__(self, channels: list[SlowControlChannel]) -> None:
        self._channels = channels

    @classmethod
    def from_config(cls, cfg: dict) -> "SlowControlManager":
        """
        Build a SlowControlManager from a devices.yaml slow_control section.

        Expected YAML structure::

            slow_control:
              poll_interval_s: 5
              channels:
                - name: temperature_C
                  unit: "°C"
                  backend: simulated
                  nominal: 22.0
                  warn_high: 30.0
                  alarm_high: 35.0
                - name: humidity_pct
                  unit: "%RH"
                  backend: simulated
                  ...
        """
        channels: list[SlowControlChannel] = []
        for entry in cfg.get("channels", []):
            name    = entry.get("name", "unnamed")
            unit    = entry.get("unit", "")
            backend = entry.get("backend", "simulated").lower()
            thresh  = AlarmThresholds.from_dict(entry)
            factory = SLOW_CONTROL_BACKENDS.get(backend)
            if factory is None:
                logger.error(
                    "Unknown slow_control backend '%s' for channel '%s'. "
                    "Available: %s",
                    backend, name, list(SLOW_CONTROL_BACKENDS),
                )
                continue
            ch = factory(name, unit, thresh, entry)
            channels.append(ch)
            logger.debug("Slow-control channel registered: %s (%s)", name, backend)
        return cls(channels)

    # ------------------------------------------------------------------ #
    # Properties                                                          #
    # ------------------------------------------------------------------ #

    @property
    def channels(self) -> list[SlowControlChannel]:
        return list(self._channels)

    @property
    def channel_names(self) -> list[str]:
        return [ch.name for ch in self._channels]

    # ------------------------------------------------------------------ #
    # Connect / disconnect                                                #
    # ------------------------------------------------------------------ #

    def connect_all(self) -> dict[str, str]:
        results: dict[str, str] = {}
        for ch in self._channels:
            try:
                ch.connect()
                results[ch.name] = "ok"
            except Exception as exc:
                results[ch.name] = str(exc)
                logger.error("Slow-control channel '%s' connect failed: %s", ch.name, exc)
        return results

    def disconnect_all(self) -> None:
        for ch in self._channels:
            try:
                ch.disconnect()
            except Exception as exc:
                logger.warning("Slow-control channel '%s' disconnect error: %s", ch.name, exc)

    # ------------------------------------------------------------------ #
    # Reading                                                             #
    # ------------------------------------------------------------------ #

    def read_all(self) -> dict[str, SlowControlReading]:
        """Return a snapshot of all channels, keyed by channel name."""
        return {ch.name: ch.read_with_status() for ch in self._channels}
