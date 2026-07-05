"""
Printer / motor-stage presets.

Each preset bundles the settings that change when you physically swap the
stage: which backend driver to use, the firmware dialect (Marlin vs GRBL),
a safe default feed rate, and — most importantly — the software travel
limits for that machine's build volume.

Selecting a preset in the Settings window (motor_stage.model) fills these in.
The "custom" preset applies nothing, leaving whatever is written in
devices.yaml untouched so you can hand-tune the limits yourself.

To add a new machine, append one entry to PRINTER_PRESETS.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PrinterPreset:
    key: str                       # devices.yaml motor_stage.model value
    label: str                     # human label shown in the settings dropdown
    backend: str                   # "grbl" | "pi"
    marlin: bool                   # firmware dialect for the grbl backend
    feed_rate_mm_min: int          # safe default travel speed
    limits: dict[str, float] = field(default_factory=dict)  # software_limits block


# Ordered so the dropdown reads sensibly.  "custom" is last.
PRINTER_PRESETS: dict[str, PrinterPreset] = {
    "cr10s": PrinterPreset(
        key="cr10s",
        # GRBL firmware (not Marlin).  GRBL's post-homing convention puts MPos 0
        # at the homed corner with a NEGATIVE work area (0 → -max) on every
        # axis — exactly what UGS reports.
        label="Creality CR-10S (300×300×400, GRBL)",
        backend="grbl",
        marlin=False,
        feed_rate_mm_min=1500,
        limits={
            "x_min_mm": -300.0, "x_max_mm": 0.0,
            "y_min_mm": -300.0, "y_max_mm": 0.0,
            "z_min_mm": -400.0, "z_max_mm": 0.0,
        },
    ),
    "ender3": PrinterPreset(
        key="ender3",
        label="Previous printer (235×235×250)",
        backend="grbl",
        marlin=True,
        feed_rate_mm_min=1500,
        limits={
            "x_min_mm": 0.0, "x_max_mm": 235.0,
            "y_min_mm": 0.0, "y_max_mm": 235.0,
            "z_min_mm": 0.0, "z_max_mm": 250.0,
        },
    ),
    "pi_stage": PrinterPreset(
        key="pi_stage",
        label="PI motor stage (precision)",
        backend="pi",
        marlin=False,
        feed_rate_mm_min=300,
        limits={
            "x_min_mm": -50.0, "x_max_mm": 50.0,
            "y_min_mm": -50.0, "y_max_mm": 50.0,
            "z_min_mm": -10.0, "z_max_mm": 10.0,
        },
    ),
    "custom": PrinterPreset(
        key="custom",
        label="Custom / manual limits",
        backend="grbl",
        marlin=False,
        feed_rate_mm_min=1500,
        limits={},          # empty → never overrides devices.yaml
    ),
}

DEFAULT_PRINTER = "custom"


def get_preset(key: str | None) -> PrinterPreset:
    """Return the preset for *key*, falling back to the custom preset."""
    if not key:
        return PRINTER_PRESETS[DEFAULT_PRINTER]
    return PRINTER_PRESETS.get(str(key).lower(), PRINTER_PRESETS[DEFAULT_PRINTER])
