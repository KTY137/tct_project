"""
Abstract interface for slow-control measurement channels.

A "channel" is any scalar quantity sampled at low frequency:
temperature, humidity, bias voltage, leakage current, etc.

To add a new sensor type:
  1. Subclass SlowControlChannel and implement read().
  2. Register it in SLOW_CONTROL_BACKENDS inside
     controller/slow_control_manager.py.
  3. Add one entry under slow_control.channels in configs/devices.yaml.

The rest of the application (SlowControlManager, MonitorPanel,
InfluxWriter) references only SlowControlChannel — no concrete class
leaks past the device layer.
"""
from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .base import BaseDevice


class AlarmStatus(Enum):
    OK          = "OK"
    WARN_LOW    = "WARN_LOW"
    WARN_HIGH   = "WARN_HIGH"
    ALARM_LOW   = "ALARM_LOW"
    ALARM_HIGH  = "ALARM_HIGH"
    UNAVAILABLE = "UNAVAILABLE"


# Colour hint for GUI panels
ALARM_COLORS: dict[AlarmStatus, str] = {
    AlarmStatus.OK:          "#27ae60",
    AlarmStatus.WARN_LOW:    "#f39c12",
    AlarmStatus.WARN_HIGH:   "#f39c12",
    AlarmStatus.ALARM_LOW:   "#c0392b",
    AlarmStatus.ALARM_HIGH:  "#c0392b",
    AlarmStatus.UNAVAILABLE: "#7f8c8d",
}


@dataclass
class AlarmThresholds:
    warn_low:   Optional[float] = None
    warn_high:  Optional[float] = None
    alarm_low:  Optional[float] = None
    alarm_high: Optional[float] = None

    def evaluate(self, value: float) -> AlarmStatus:
        if self.alarm_low  is not None and value <= self.alarm_low:
            return AlarmStatus.ALARM_LOW
        if self.alarm_high is not None and value >= self.alarm_high:
            return AlarmStatus.ALARM_HIGH
        if self.warn_low   is not None and value <= self.warn_low:
            return AlarmStatus.WARN_LOW
        if self.warn_high  is not None and value >= self.warn_high:
            return AlarmStatus.WARN_HIGH
        return AlarmStatus.OK

    @classmethod
    def from_dict(cls, d: dict) -> "AlarmThresholds":
        return cls(
            warn_low=d.get("warn_low"),
            warn_high=d.get("warn_high"),
            alarm_low=d.get("alarm_low"),
            alarm_high=d.get("alarm_high"),
        )


@dataclass
class SlowControlReading:
    name:      str
    value:     float
    unit:      str
    timestamp: float
    status:    AlarmStatus


class SlowControlChannel(BaseDevice):
    """
    Backend-agnostic interface for a single slow-control scalar channel.

    Concrete implementations:
        SimulatedSlowChannel  — software simulation (default)
        (add more in devices/ and register in slow_control_manager.py)
    """

    def __init__(
        self,
        name: str,
        unit: str,
        thresholds: AlarmThresholds | None = None,
        simulation: bool = False,
    ) -> None:
        super().__init__(simulation=simulation)
        self.name = name
        self.unit = unit
        self.thresholds = thresholds or AlarmThresholds()

    @abstractmethod
    def read(self) -> float:
        """Return the current scalar measurement value in self.unit."""

    def read_with_status(self) -> SlowControlReading:
        """Read, evaluate alarm thresholds, return a full SlowControlReading."""
        try:
            value  = self.read()
            status = self.thresholds.evaluate(value)
        except Exception as exc:
            self.logger.warning("Channel '%s' read failed: %s", self.name, exc)
            return SlowControlReading(
                name=self.name,
                value=float("nan"),
                unit=self.unit,
                timestamp=time.time(),
                status=AlarmStatus.UNAVAILABLE,
            )
        return SlowControlReading(
            name=self.name,
            value=value,
            unit=self.unit,
            timestamp=time.time(),
            status=status,
        )
