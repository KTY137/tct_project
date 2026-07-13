# TCT Setup — Control Application

Self-contained PySide6 control app for a scanning Transient Current Technique
(TCT) setup: XYZ stage scanning, oscilloscope acquisition, bias supply,
camera, laser/trigger, slow-control monitoring, and post-scan analysis.

This folder is **self-contained**: copy it anywhere, bootstrap a venv, and run.
The e4control bias-supply library is vendored in [`vendor/e4control`](vendor/e4control)
so no sibling folders are required.

## Quick start (Windows)

```powershell
# 1. one-time setup: build .venv and install dependencies
powershell -ExecutionPolicy Bypass -File .\setup.ps1

# 2. launch
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Or manually:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

The app starts in **simulation mode** by default (see `configs/devices.yaml`),
so it runs with no hardware attached. Switch each device's `backend` /
`simulation` flags in **Settings…** (or edit `configs/devices.yaml`) to talk to
real instruments.

`run.ps1` boots the classic PySide6-widgets shell by default. Pass **`-Qml`**
(or set `TCT_QML_SHELL=1` before launching `main.py` directly) to boot the
opt-in QML-hybrid cockpit chrome instead — rail + tab shelf + status strip
rendered in QML, panels/plots unchanged. This has been ratified to become the
default, with a `-Classic` fallback flag; that flip has not landed yet.

## Architecture

Three layers, GUI never touches hardware directly:

```
main.py                     entry point (applies theme, builds the window)
tct_gui.py                  QMainWindow: menu/toolbar, tabs, status strip, log dock,
                            soft-reload of the whole config, window-state persistence

controller/                 orchestration (no Qt widgets)
  device_manager.py         reads devices.yaml, builds every device from its `backend`
  scan_controller.py        XY / Z-focus / bias (IV) scans in a background thread
  state_machine.py          app states (DISCONNECTED / CONNECTED / RUNNING …)
  slow_control_manager.py   periodic temperature / humidity / … polling
  repeatability.py          camera-based stage-repeatability test (phase correlation)

devices/                    hardware drivers behind abstract base classes
  base.py                   BaseDevice (connect/disconnect/simulation)
  motor_base.py  + motor_grbl.py / motor_pi.py / motor_simulated.py
  oscilloscope.py (VISA)  + oscilloscope_drs4.py
  waveform_generator.py   (VISA, vendor SCPI dialects)
  camera_blackfly.py      (FLIR/PySpin, falls back to a synthetic image)
  bias_supply_base.py + _keithley / _e4control / _simulated
  intensity_*  slow_control_*  laser_manual.py  printer_presets.py

gui/                        one panel per instrument + shared widgets
  motor_panel / scope_panel / camera_panel / laser_panel / scan_viewer_panel /
  planner_panel / monitor_panel / analysis_panel / calibration_panel
  multi_bias_panel.py       MultiBiasPanel — one bias_panel.BiasPanel tab per
                            HV channel (+ ALL OUTPUTS OFF)
  device_panel.py           Device Manager window (per-device connect/status)
  settings_window.py        Settings editor (Quick form + full YAML), VISA picker
  detachable_tabs.py        tear-off tabs (double-click / ⧉ → own window)
  style.py                  light/dark themes; dark plot canvas
  scan_map_view.py          shared 2-D scan-map widget (live map + PNG/CSV export)
  qml_shell.py / qml/       opt-in QML cockpit chrome (rail + pill tab shelf +
                            status strip); TCT_QML_SHELL=1 / run.ps1 -Qml

data/hdf5_writer.py         HDF5 run writer (see SCAN_DATA_FORMAT.md)
analysis/                   waveform_analysis.py, charge_calibration.py
configs/devices.yaml        the single source of truth for all device settings
vendor/e4control/           vendored third-party GPIB library (do not merge into devices/)
```

**Adding a device backend:** subclass the relevant `*_base.py`, implement the
abstract methods, and register the class in the backend map in
`controller/device_manager.py` (e.g. `MOTOR_BACKENDS`). No GUI change needed —
panels talk only to the base interfaces.

## GUI features

- **Menu bar + toolbar** (Connect/Disconnect/Settings/Log) and a per-device
  status strip (green = real, purple = simulated, grey = disconnected).
- **Detachable tabs** — double-click a tab or press **⧉** to pop a panel into its
  own window (multi-monitor); close it to re-dock.
- **Dark mode** (View → Dark mode) and **layout persistence** (window size, active
  tab, theme and detached panels are restored on next launch).
- **Theme editor** (View → Theme…) — preset browser (built-in + saved user
  presets), color/typography/corner-radius controls, and a glass↔opaque
  material slider; the safety palette (danger/armed/sim/error) is locked.
- **Live settings** — saving in Settings soft-reloads the whole config without
  restarting the process.
- **Oscilloscope panel** — scope-style **t/div, V/div, offset sliders + manual
  entry**, **Autoscale**, optional **“Sync scales to scope”** (SCPI), a **Trigger
  Settings** window, and auto ns/µs/ms time axis.

## Instrument connectivity (VISA — USB & LAN)

The oscilloscope and waveform generator use **VISA** (via `pyvisa`), which needs
a VISA backend installed — **NI-VISA** is recommended (vendor-agnostic: Rigol,
Tektronix, Keysight, …). One install covers USB and LAN.

Address formats (set in Settings → the **VISA picker**, or `configs/devices.yaml`):

| Transport | Example address |
|-----------|-----------------|
| USB       | `USB0::0x1AB1::0x0641::DG4xxxxxxxx::INSTR` (Rigol), `USB0::0x0699::…::INSTR` (Tektronix) |
| LAN VXI-11| `TCPIP0::192.168.1.50::INSTR`  ← recommended for LAN |
| LAN HiSLIP| `TCPIP0::192.168.1.50::hislip0::INSTR` |
| LAN socket| `TCPIP0::192.168.1.50::5555::SOCKET` (raw socket; the app sets `\n` terminators automatically) |

The VISA picker **🔄 scans** for connected instruments and offers them as
suggestions. LAN devices are usually not auto-discovered — type the IP (it is
auto-wrapped to `TCPIP0::<ip>::INSTR`) or use **+ LAN**. Tektronix scopes use one
`vendor: tektronix` for both TBS-1000C (USB) and 4000-series (LAN); the driver
tries `WFMOutpre?` then `WFMPre?` for the waveform preamble.

For this lab's actual bench LAN (isolated static-IP instrument network,
switch/PC/DG4162 addresses, and connectivity troubleshooting), see
[`docs/BENCH_SETUP.md`](../docs/BENCH_SETUP.md).

## Real-hardware-only SDKs (not on PyPI)

These are vendor binary SDKs; install them separately when using that hardware.
Everything else installs from `requirements.txt`.

| Hardware | SDK |
|----------|-----|
| FLIR Blackfly camera | FLIR Spinnaker SDK + PySpin (`spinnaker-python`) — needs the **64-bit** SDK and a **direct USB-3 port** (no hub); see [`docs/BENCH_SETUP.md`](../docs/BENCH_SETUP.md) §6 |
| PSI DRS4 oscilloscope | DRS4 evaluation-board driver |
| Any VISA instrument (scope/WFG) | NI-VISA (or another VISA implementation) |

GPIB bias-supply connections (`e4control` backend, `connection_type: gpib`) use
`python-vxi11`, which **is** installed by `requirements.txt`. TCP/serial/Prologix
connections use a built-in socket shim and need nothing extra.

## Data output

Scans are written to `runs/run_NNNNN/waveforms.h5` (HDF5). The on-disk layout,
mandatory vs optional groups, and the save-selection options are documented in
[`SCAN_DATA_FORMAT.md`](SCAN_DATA_FORMAT.md).

## Bias supplies

Backends (`bias_supply.backend` in `configs/devices.yaml`): `simulated`,
`keithley` (SMU/HV over VISA), `e4control` (GPIB/LAN via the vendored lib), and
**`iseg`** (SHR/NHR/SR HV modules over **LAN**, iseg SCPI on a TCPIP socket, port
10001 — set `host` / `port` / `channel` in Settings → Bias Supply). The bias is
always **ramped** in steps and is **auto-ramped to 0 V** on disconnect / close /
config-reload for sensor safety; a compliance trip shows a red status + log.

## Roadmap / robustness backlog

Done recently: VISA USB+LAN with mDNS/LXI auto-discovery, oscilloscope panel that
**drives the instrument** (t/div, V/div, offset → SCPI) and **reads settings
back**, visible errors via the status bar/log, bias ramp-down safety, iseg backend.

Still open (tracked so they aren't forgotten):

- **Connection health-check + reconnect** — probe each configured endpoint on
  startup (serial port / VISA resource present) and offer a one-click reconnect
  after a USB/LAN drop.
- **Automated tests / CI** for the device layer + analysis (currently verified
  manually in simulation).
