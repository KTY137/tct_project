# Handoff — Marlin Z-Homing Debug (2026-07-06)

Session export so we know exactly where to resume tomorrow.

## TL;DR
- Flashed a **trimmed (XYZ-only) Marlin 2.1.2.8** onto the Mega2560/RAMPS board (`sources/Marlin-2.1.2.8`).
- X and Y home fine. **Z homing drives *down* (correct direction) into the endstop and never stops.**
- Root cause narrowed to: **the Z endstop is not triggering — hardware side.** Firmware config is correct on paper.
- Separate, still-pending software bug: the app's `software_limits` have the wrong sign for Marlin.

## What we confirmed is CORRECT (don't touch)
Firmware (`sources/Marlin-2.1.2.8/Marlin/Configuration.h`):
- `Z_HOME_DIR -1` and `INVERT_Z_DIR true` → Z homes downward = matches the switch being at the bottom. ✔
- `ENDSTOPPULLUPS` on, `Z_MIN_ENDSTOP_INVERTING false`. ✔
- `USE_ZMIN_PLUG` on, `Z_MIN_PROBE_USES_Z_MIN_ENDSTOP_PIN` on, `USE_PROBE_FOR_Z_HOMING` off → Z homing uses the **Z-MIN endstop pin** (no probe). ✔
- `MOTHERBOARD BOARD_RAMPS_CREALITY`, `BAUDRATE 115200`.
- Bed/travel: `X_BED_SIZE 296`, `Y_BED_SIZE 298`, `Z_MAX_POS 400`, `Z_MIN_POS 0`.

Because X/Y home OK, their endstops work on this board profile → the fault is isolated to the **Z-min signal path only**.

## Tooling note
- **UGS does NOT support Marlin.** Use **Pronterface** (`reference/Printrun/pronterface.py`, or `pip install printrun` → `pronterface`) or PlatformIO's monitor:
  ```powershell
  & 'C:\Users\nukei\Desktop\project_tct\sources\.pioenv\Scripts\python.exe' -m platformio device monitor -p COM4 -b 115200
  ```
- COM4 is **exclusive** — close the TCT app / UGS before connecting, or you get "access denied."

## ▶ START HERE TOMORROW — hardware diagnosis (~10 min)

Connect Pronterface @ COM4 / 115200. `M119` reports endstop states.

### 1. Swap test (decisive — uses X as a known-good reference)
- Unplug the **Z switch**, plug it into the **X-min header**. Press the Z switch by hand → `M119`.
  - `x_min` → `TRIGGERED`  ⇒ **Z switch + cable are good** → fault is the board Z-min header/pin or firmware pin-map.
  - `x_min` stays `open`    ⇒ **switch or cable is dead** → continuity test.
- Plug a **known-good X switch** into the **Z-min header**. Press → `M119`.
  - `z_min` triggers ⇒ Z header fine (confirms switch/cable fault).
  - `z_min` stays `open` ⇒ **Z-min pin/header is the problem** (likely wrong `MOTHERBOARD` profile mapping the Z-min pin, or damaged pin).

### 2. Multimeter continuity (verifies the switch alone)
Across the two wires at the connector: lever released vs pressed **must** flip state. No change = bad switch / broken wire / wrong terminals.

### 3. The three usual hardware culprits
- **Wrong terminal pair:** microswitch has COM/NO/NC — use the pair that goes **closed when pressed** = **COM + NO**.
- **Wrong header pins:** RAMPS Z-min header is **S / GND / +5V**; the two switch wires must land on **S + GND**, not +5V.
- **Not a plain microswitch:** if the Z sensor is inductive/optical/hall, it needs +5V power and only triggers on the right target — wired like a bare switch it stays dead. (Open question: is it a lever microswitch or a cylindrical probe?)

## ▶ Pending SOFTWARE fix (independent of the endstop)
`TCT_app/configs/devices.yaml` has `motor_stage.marlin: true`, but `software_limits` are in **GRBL-negative** convention:
```yaml
software_limits:
  x_min_mm: -300.0   x_max_mm: 0.0
  y_min_mm: -300.0   y_max_mm: 0.0
  z_min_mm: -400.0   z_max_mm: 0.0
```
Marlin homes to a **positive** frame (origin 0,0,0 at the homed min corner). Consequences once homing works:
- `move_to()` guards targets in machine coords → every normal move gets **refused** as out-of-range.
- Auto post-home centering computes `-150` and sends `G1 X-150` → Marlin rejects it.

**Fix (apply when ready):**
```yaml
software_limits:
  x_min_mm: 0.0    x_max_mm: 296.0
  y_min_mm: 0.0    y_max_mm: 298.0
  z_min_mm: 0.0    z_max_mm: 400.0
```
(Trim maxes to real usable travel if less than the firmware bed size.)

Also: `push_steps_to_grbl: true` is a **no-op in Marlin mode** (that push only runs in the GRBL-only reset path in `TCT_app/devices/motor_grbl.py`). Set steps/mm in firmware (`M92`) instead.

## Relevant files
- Firmware: `sources/Marlin-2.1.2.8/Marlin/Configuration.h`
- App motor driver (supports Marlin + firmware auto-detect): `TCT_app/devices/motor_grbl.py`
- App config: `TCT_app/configs/devices.yaml`
