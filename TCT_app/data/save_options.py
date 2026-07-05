"""Configuration object for optional HDF5 output groups."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SaveOptions:
    """Which optional groups the HDF5 writer should persist.

    Waveforms and positions are mandatory per ``SCAN_DATA_FORMAT.md`` and are
    therefore forced on even if an old config tries to disable them.
    """

    waveforms: bool = True
    positions: bool = True
    timestamp: bool = True
    analysis: bool = True
    bias: bool = True
    slow_control: bool = False
    camera_frame: bool = False
    run_metadata: bool = True

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "SaveOptions":
        cfg = cfg or {}
        return cls(
            waveforms=True,
            positions=True,
            timestamp=bool(cfg.get("timestamp", True)),
            analysis=bool(cfg.get("analysis", True)),
            bias=bool(cfg.get("bias", True)),
            slow_control=bool(cfg.get("slow_control", False)),
            camera_frame=bool(cfg.get("camera_frame", False)),
            run_metadata=bool(cfg.get("run_metadata", True)),
        )

    def to_dict(self) -> dict[str, bool]:
        return {
            "waveforms": self.waveforms,
            "positions": self.positions,
            "timestamp": self.timestamp,
            "analysis": self.analysis,
            "bias": self.bias,
            "slow_control": self.slow_control,
            "camera_frame": self.camera_frame,
            "run_metadata": self.run_metadata,
        }
