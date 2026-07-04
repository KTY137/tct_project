"""
PicoQuant PDL 800 laser driver — metadata-only model.

The PDL 800 is not PC-controllable, so this class does not issue any
hardware commands.  It stores the manually chosen settings as run
metadata and provides a structured object the scan controller and
data writer can serialise to YAML/JSON.

To swap to a PC-controllable laser driver in the future:
  1. Subclass or replace this with a class that inherits BaseDevice.
  2. Implement connect() / disconnect() and add setter methods.
  3. Update configs/devices.yaml and devices/__init__.py accordingly.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class LaserManualMetadata:
    """
    Snapshot of manually set PDL 800 parameters recorded into run metadata.

    Fields can be edited by the user in the Laser panel GUI and are
    embedded verbatim in the run's config.yaml / metadata.json.
    """
    driver: str = "PicoQuant PDL 800"
    pc_controllable: bool = False
    wavelength_nm: float = 660.0
    repetition_mode: str = "external"        # "internal" | "external"
    repetition_frequency_hz: float = 1000.0  # used only for metadata; actual rate set by waveform generator
    power_knob_setting: str = ""             # free text, e.g. "approx 3.5"
    attenuation_filter: str = ""             # free text, e.g. "ND 1.0"
    monitor_detector: str = "SiPM/photodiode"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LaserManualMetadata":
        known = {k for k in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
