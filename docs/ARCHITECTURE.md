# TCT App — Architecture Bookkeep

**This is the crew's shared architecture reference.** Owner: `docs-dev` (Samantha).
Every agent consults this file before working on an unfamiliar module. Whenever a
change adds/removes/renames a module, class, signal, config key, or data group,
the change is not finished until this file is updated (delegate to Samantha).
Entries must describe what the code *actually does* — verify against the source,
never document intentions. Add a line to the changelog at the bottom for every
update.

App root: `TCT_app/` — all paths below are relative to it.

## Big picture

```
configs/devices.yaml ──► controller/config_validator ──► controller/device_manager
                                                              │ owns all device instances
        GUI (PySide6, main thread)                            ▼
  tct_gui.TCTMainWindow ◄── signals/callbacks ──► controller/scan_controller (worker thread)
  │  gui/* panels (abstract interfaces only)         │ move→settle→image→trigger→acquire
  │  gui/status_bus, _QtLogHandler log bridge        │ →analyse→save→update map
  ▼                                                  ▼
controller/state_machine (AppState)            data/hdf5_writer ──► runs/run_XXXXX/waveforms.h5
                                               data/influx_writer (slow control → InfluxDB)
```

Core design rules (verified in code):
- GUI panels and scan logic reference **only abstract device interfaces**
  (`*_base.py`); concrete drivers are chosen by `device_manager` from
  `devices.yaml`. Hardware swaps need no UI/scan-code changes.
- Every device family has a `simulated` backend; the whole app runs with zero
  hardware.
- `devices/base.py:BaseDevice` gives every driver a `simulation` flag, a
  `connected` property, and an **`io_lock` (re-entrant)** that serialises hardware
  I/O — GUI pollers and the scan thread share one VISA/serial session per device.

## Entry point

- `main.py` — logging setup, `QApplication`, applies saved theme
  (`QSettings("TCT", "TCTSetup")`), builds
  `TCTMainWindow(config_path="configs/devices.yaml")`.
- `tct_gui.py` — `TCTMainWindow`: assembles all panels into detachable tabs
  (`gui/detachable_tabs.DetachableTabWidget`), wires `ScanController` callbacks,
  owns the `StateMachine`. `_QtLogHandler`/`_LogBridge` forward log records onto
  the main thread via a Qt signal (thread-safe in-app log view).

## controller/

- `state_machine.py` — `AppState` enum and validated transitions:
  `DISCONNECTED → CONNECTED → HOMED → CONFIGURED → READY → RUNNING →
  {PAUSED, FINISHED, ERROR, ABORTED}`; `PAUSED → {RUNNING, ABORTED}`; terminal
  states fall back to `CONFIGURED`. **Every state may reset to `DISCONNECTED`**
  (universal recovery, incl. crashed scans). Invalid transitions raise
  `ValueError`; observers register callbacks.
- `scan_controller.py` — `ScanController` drives the scan loop
  (move → settle → image → trigger → acquire → analyse → save → update map) on a
  worker thread (`threading`). Scan types as dataclass configs:
  - `ScanConfig` — XY raster (start/stop/step per axis, fixed Z, `n_averages`,
    `settle_time_s`).
  - `ZFocusScanConfig` — focal calibration; `mode="amplitude"` (legacy, max DUT
    amplitude) or `mode="edge_scan"` (recommended: max spatial gradient |dQ/dx|
    across a metal/silicon edge per Z step).
  - `VoltageScanConfig` — IV / bias sweeps.
- `device_manager.py` — owns all device instances; single
  connect/disconnect/status interface for the GUI. Backend registries map
  `devices.yaml` keys to classes: `MOTOR_BACKENDS` (`pi`, `grbl`, `simulated`),
  `INTENSITY_BACKENDS` (`scope_channel`, `simulated`), etc. `_APP_ROOT` anchors
  relative output paths to `TCT_app/` regardless of launch cwd. New driver =
  new registry entry.
- `slow_control_manager.py` — environment/slow-control channels; feeds
  `data/influx_writer` and the HDF5 `slow_control` group.
- `config_validator.py` — validates `devices.yaml` before use.
- `repeatability.py` — stage repeatability measurement logic.

## devices/ (one family = base + backends)

| Family | Base | Backends |
|---|---|---|
| Motor stage | `motor_base.py` (`MotorStageBase`, `SoftwareLimits`) | `motor_grbl.py`, `motor_pi.py`, `motor_simulated.py` (+ `printer_presets.py`) |
| Bias supply (HV) | `bias_supply_base.py` (`BiasSupplyBase`) | `bias_supply_iseg.py`, `bias_supply_keithley.py`, `bias_supply_e4control.py`, `bias_supply_simulated.py` |
| Oscilloscope | — | `oscilloscope.py` (VISA), `oscilloscope_drs4.py` (PSI DRS4 eval board) |
| Intensity monitor | `intensity_base.py` | `intensity_scope_ch.py`, `intensity_simulated.py` |
| Slow control | `slow_control_base.py` | `slow_control_simulated.py` |
| Other | `waveform_generator.py` (VISA), `camera_blackfly.py` (FLIR PySpin), `laser_manual.py` (metadata-only laser record) | |

All inherit `base.py:BaseDevice` (`DeviceError`, `io_lock`, `simulation`,
abstract `connect()`/`disconnect()`).

## gui/ (PySide6 — never PyQt6)

Panels: `motor_panel`, `bias_panel`, `scope_panel`, `scan_panel`, `laser_panel`,
`intensity_panel`, `camera_panel`, `monitor_panel`, `analysis_panel`,
`calibration_panel`, `device_panel` (`DeviceManagerWindow`, `device_state`),
`settings_window`. Support: `status_bus.py` (cross-panel status),
`scan_map_window.py` (live scan map), `stage_view.py` (3D GL stage view),
`scope_measurements.py`, `detachable_tabs.py`, `style.py` (theming).
Long-running work never runs on the main thread; log records cross threads via
the `_LogBridge` signal.

## data/

- `hdf5_writer.py` — `HDF5Writer`: incremental single-file writer,
  `runs/run_XXXXX/waveforms.h5`. Group selection via `save_options.SaveOptions`;
  `waveforms` + `positions` mandatory, `timestamp`/`analysis`/`bias`/
  `slow_control`/`camera_frame`/`run_metadata` optional. `/run_info` attrs hold
  scan config, `devices.yaml` snapshot (Influx token redacted), calibration,
  software limits, timestamps. Extensible datasets, gzip, chunk 64.
  **Full contract: `TCT_app/SCAN_DATA_FORMAT.md`** — the
  authoritative data-format doc; keep both in sync.
- `influx_writer.py` — optional slow-control sink to InfluxDB.
- `save_options.py` — which HDF5 groups are written; editable in Settings GUI.

## analysis/

`waveform_analysis.py` (`analyse_waveform`, `WaveformResult` — amplitude, charge,
baseline RMS, drift/rise/CFD/onset times), `charge_calibration.py`
(`ChargeCalibration`), `laser_normalization.py` (`normalise`).

## configs/ and tests/

- `configs/devices.yaml` — single config source: backend selection per device,
  connection parameters, `output.data_dir`, `output.save` toggles, calibration,
  software limits. Validated by `config_validator`.
- `tests/` — pytest, headless, simulated backends only: state machine, config
  validator, GRBL mock, scope preamble, waveform analysis, bias & calibration.

## Local-only reference material

- `reference/` — local-only reference material, intentionally ignored by Git
  (`Printrun`, `e4control`, Dustin oscilloscope scripts, Spinnaker SDK).
- `lab_assets/` — local-only lab photos and source/manual PDFs, intentionally
  ignored by Git.
- `sources/git_history/` — local recovery bundles for the old nested repos,
  intentionally ignored by Git.
- `TCT_app/devices/bias_supply_e4control.py` can import from a local
  `reference/e4control` checkout at connect time. Keep that dependency optional
  so simulation and tests work without local reference material.

Details: `docs/REFERENCE_MATERIAL.md`.

## Known constraints

- numpy pinned `<2` (PySpin 3.2 wheel, numpy 1.x C-ABI). 64-bit CPython 3.10
  required for real-camera use.
- Real hardware extras not on PyPI: FLIR Spinnaker SDK runtime, PSI DRS4 driver.

## TODO (Samantha: verify and deepen)

- [ ] Signal/slot inventory: which ScanController callbacks TCTMainWindow wires,
      and the status_bus message types.
- [ ] Thread inventory: exact threads at runtime (GUI, scan worker, pollers,
      slow-control) and which objects live where.
- [ ] devices.yaml key reference (per-backend connection parameters).
- [ ] Confirm full backend registry list in device_manager (scope/camera/bias
      registries beyond MOTOR/INTENSITY).

## Changelog

- 2026-07-05 - Restored the missing `TCT_app/data/` package used by
  `device_manager` and `scan_controller`; added smoke coverage for the HDF5
  writer and disabled Influx sink.

- 2026-07-05 — Flattened project layout around the app: app root moved to
  `TCT_app/`; reference material moved to `reference/`; lab images/manuals moved
  to `lab_assets/`.
- 2026-07-05 — Marked third-party and lab reference folders as local-only ignored
  material; documented the clean-root policy in `docs/REFERENCE_MATERIAL.md`.
- 2026-07-04 — Initial bookkeep created from source inspection (main, tct_gui,
  state_machine, scan_controller, device_manager, base device, hdf5_writer,
  SCAN_DATA_FORMAT.md). Some sections marked TODO for deepening.
