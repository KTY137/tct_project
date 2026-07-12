# Config Keys Registry

**Maintained by Kiroku; updated when keys are added/removed; drift-checked by Mamoru. Paths repo-root-relative.**

This is a lookup table for all top-level configuration keys in `TCT_app/configs/devices.yaml`. Use this to understand what each key does, its type, whether it is required, and where it is consumed.

Organization: **one section per devices.yaml top-level key**, listing the nested keys within each section. Format: | Key | Type | Default (if any) | Validated by | Consumed by |

**Convention:** Keys marked `(opt-in)` are optional and shipped commented-out or absent; unmarked keys are required or unconditionally present. Nested dicts like `software_limits` and `save` are validated by their own consumers, not typo-checked at the top level.

---

## oscilloscope

Backend auto-selects Oscilloscope, DRS4Oscilloscope, or TekFastFrameOscilloscope based on `backend` key.

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `backend` | str | "visa" | `config_validator._check_scope()` | `device_manager.__init__()` line 121 |
| `simulation` | bool | True | — | `device_manager` Oscilloscope constructor |
| `n_averages` | int | 1 | — | `Oscilloscope.__init__()` (VISA/DRS4 only) |
| `n_channels` | int | — | `config_validator._check_scope()` WARNING if not 1–8 | `Oscilloscope.__init__()` (VISA only) |
| **VISA backend keys:** | | | | |
| `visa_address` | str | "" | `config_validator._check_scope()` ERROR if backend=visa and not simulation | `Oscilloscope.__init__()` |
| `vendor` | str | "tektronix" | — | `Oscilloscope.__init__()` |
| `timeout_ms` | int | 10000 | — | `Oscilloscope.__init__()` |
| `trigger_source` | str | "EXT" | — | `Oscilloscope.__init__()` |
| `trigger_level_V` | float | -0.41 | — | `Oscilloscope.__init__()` |
| `trigger_slope` | str | "FALL" | — | `Oscilloscope.__init__()` |
| **DRS4 backend keys:** | | | | |
| `frequency_ghz` | float | 5.0 | — | `DRS4Oscilloscope.__init__()` |
| `voltage_range` | int | 0 | — | `DRS4Oscilloscope.__init__()` |
| `trigger_edge` | str | "FALL" | — | `DRS4Oscilloscope.__init__()` |
| `trigger_delay_ns` | float | 150.0 | — | `DRS4Oscilloscope.__init__()` |
| `time_correction` | bool | True | — | `DRS4Oscilloscope.__init__()` |
| `t0_ns` | float | 20.0 | — | `DRS4Oscilloscope.__init__()` |
| `t0_threshold_V` | float | -0.45 | — | `DRS4Oscilloscope.__init__()` |
| `timeout_s` | float | 2.0 | — | `DRS4Oscilloscope.__init__()` |
| **TekFastFrame backend keys:** | | | | |
| `model` | str | — | — | `TekFastFrameOscilloscope.__init__()` |
| `trigger_channel` | str | "CH4" | — | `TekFastFrameOscilloscope.__init__()` |
| `trigger_type` | str | "EDGE" | — | `TekFastFrameOscilloscope.__init__()` |
| `trigger_mode` | str | "NORMAL" | — | `TekFastFrameOscilloscope.__init__()` |
| `timescale_s` | float | 10e-9 | — | `TekFastFrameOscilloscope.__init__()` |
| `vertical_scale_V` | float | 0.008 | — | `TekFastFrameOscilloscope.__init__()` |
| `waveform_position` | float | 0.0 | — | `TekFastFrameOscilloscope.__init__()` |
| `waveform_channel` | str | "CH4" | — | `TekFastFrameOscilloscope.__init__()` |
| `acquisition_mode` | str | "SAMPLE" | — | `TekFastFrameOscilloscope.__init__()` |
| `sample_rate_hz` | float | 10e9 | — | `TekFastFrameOscilloscope.__init__()` |
| `record_length` | int | 1000 | — | `TekFastFrameOscilloscope.__init__()` |
| `num_frames` | int | 20000 | — | `TekFastFrameOscilloscope.__init__()` |
| `num_waveforms` | int | — | — | `TekFastFrameOscilloscope.__init__()` |
| `average_number` | int | 512 | — | `TekFastFrameOscilloscope.__init__()` |
| `avg_timeout_s` | float | 30.0 | — | `TekFastFrameOscilloscope.__init__()` |

---

## motor_stage

Backend auto-selects GRBLMotorStage, PIMotorStage, or SimulatedMotorStage based on `backend` key. Printer preset (CR-10S, Ender-3, Pi stage, custom) supplies defaults for `feed_rate_mm_min`, `marlin`, and `software_limits`.

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `backend` | str | "simulated" | — | `device_manager.__init__()` line 172 |
| `simulation` | bool | — | — | (legacy; `backend: simulated` is preferred) |
| `model` | str | "cr10s" | — | `device_manager.__init__()` line 191 (GRBL: calls `get_preset()`) |
| `serial_port` | str | "COM3" | — | `GRBLMotorStage.__init__()`, `PIMotorStage.__init__()` |
| `baudrate` | int | 115200 | — | `GRBLMotorStage.__init__()`, `PIMotorStage.__init__()` |
| `feed_rate_mm_min` | float | preset-dependent | `config_validator._check_motor()` ERROR if ≤ 0 | `GRBLMotorStage.__init__()` |
| `marlin` | bool | preset-dependent | `config_validator._check_motor()` ERROR/WARNING for firmware-vs-limits mismatch | `GRBLMotorStage.__init__()` |
| `home_to_center` | bool | True | — | `GRBLMotorStage.__init__()` |
| `steps_per_mm` | float \| dict | 80.0 | — | `GRBLMotorStage.__init__()` (can override x/y/z individually) |
| `microsteps` | int | 16 | — | `GRBLMotorStage.__init__()` |
| `snap_mode` | str | "off" | — | `GRBLMotorStage.__init__()` |
| `push_steps_to_grbl` | bool | True | `config_validator._check_motor()` WARNING if marlin=true | `GRBLMotorStage.__init__()` |
| `poll_interval_s` | float | — | — | `GRBLMotorStage.__init__()` (optional) |
| `software_limits` | dict | — | `config_validator._check_motor()` ERROR if min > max or min == max | `GRBLMotorStage.__init__()` |
| `software_limits.x_min_mm` | float | — | (nested validation) | `GRBLMotorStage` limit checks |
| `software_limits.x_max_mm` | float | — | (nested validation) | (same) |
| `software_limits.y_min_mm` | float | — | (nested validation) | (same) |
| `software_limits.y_max_mm` | float | — | (nested validation) | (same) |
| `software_limits.z_min_mm` | float | — | (nested validation) | (same) |
| `software_limits.z_max_mm` | float | — | (nested validation) | (same) |
| **PI backend keys:** | | | | |
| `controller` | str | "C-863" | — | `PIMotorStage.__init__()` |
| `axes` | list[int] | [1, 2, 3] | — | `PIMotorStage.__init__()` |
| `velocity` | float | 5.0 | — | `PIMotorStage.__init__()` |

---

## intensity_monitor

Backend auto-selects ScopeChannelMonitor or SimulatedIntensityMonitor based on `backend` key.

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `backend` | str | — | — | `device_manager.__init__()` line 263 |
| `channel` | int | 1 | — | `ScopeChannelMonitor.__init__()`, `SimulatedIntensityMonitor.__init__()` |
| `termination_ohm` | float | 50.0 | — | `ScopeChannelMonitor.__init__()` |
| `saturation_frac` | float | 0.95 | — | `ScopeChannelMonitor.__init__()` |
| `charge_integration_window_s` | list[float] | [2.0e-08, 1.5e-07] | — | `ScopeChannelMonitor.__init__()` (queried, not validated) |

---

## bias_supply

Backend auto-selects IsegBiasSupply, KeithleyBiasSupply, E4ControlBiasSupply, or SimulatedBiasSupply based on `backend` key.

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `backend` | str | — | — | `device_manager.__init__()` line 292 |
| `simulation` | bool | — | — | (legacy; `backend: simulated` is preferred) |
| `compliance_A` | float | 3.9e-4 | `config_validator._check_bias()` ERROR if ≤ 0 | `IsegBiasSupply.__init__()`, `KeithleyBiasSupply.__init__()` |
| `voltage_range_V` | float | 2000 | `config_validator._check_bias()` ERROR if < 0 | `IsegBiasSupply.__init__()`, `KeithleyBiasSupply.__init__()` |
| `timeout_ms` | int | 5000 | — | `IsegBiasSupply.__init__()` |
| **ISEG backend keys:** | | | | |
| `visa_address` | str | "ASRL6::INSTR" | — | `IsegBiasSupply.__init__()` |
| `host` | str | — | — | `IsegBiasSupply.__init__()` (alt. to visa_address) |
| `port` | int | — | — | `IsegBiasSupply.__init__()` (with host) |
| `channel` | int | 0 | — | `IsegBiasSupply.__init__()` |
| `ramp_speed_V_s` | float | 50.0 | `config_validator._check_bias()` WARNING if > 200 | `IsegBiasSupply.__init__()` |
| **E4Control backend keys:** | | | | |
| `e4c_device` | str | — | — | `E4ControlBiasSupply.__init__()` |
| `connection_type` | str | — | — | `E4ControlBiasSupply.__init__()` |
| `ramp_step_V` | float | — | — | `E4ControlBiasSupply.__init__()` |
| `ramp_delay_s` | float | — | — | `E4ControlBiasSupply.__init__()` |

---

## waveform_generator

Generates trigger pulses via VISA/SCPI command set.

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `visa_address` | str | "TCPIP0::192.168.0.10::INSTR" | — | `WaveformGenerator.__init__()` |
| `vendor` | str | "rigol" | — | `WaveformGenerator.__init__()` |
| `frequency_hz` | float | 1000 | — | `WaveformGenerator.__init__()` |
| `pulse_width_s` | float | 1.0e-07 | — | `WaveformGenerator.__init__()` |
| `amplitude_V` | float | 3.3 | — | `WaveformGenerator.__init__()` (bipolar legacy path) |
| `offset_V` | float | 0.0 | — | `WaveformGenerator.__init__()` (bipolar legacy path) |
| `output_load` | int \| str | 50 | — | `WaveformGenerator.__init__()` |
| `output_channel` | int | 1 | — | `WaveformGenerator.__init__()` |
| `simulation` | bool | False | — | `WaveformGenerator.__init__()` |
| `timeout_ms` | int | — | — | `WaveformGenerator.__init__()` (optional) |
| **Unipolar square-rail keys (opt-in):** | | | | |
| `level_low_V` | float | — | `config_validator._check_waveform()` ERROR if only one is set, or if low ≥ high | `WaveformGenerator.set_levels()` (triggers unipolar path) |
| `level_high_V` | float | — | `config_validator._check_waveform()` ERROR if only one is set, or if low ≥ high | `WaveformGenerator.set_levels()` (triggers unipolar path) |

---

## camera

FLIR Blackfly camera configuration (requires `PySpin` SDK runtime and 64-bit CPython 3.10).

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `serial_number` | str | "19112408" | — | `BlackflyCamera.__init__()` |
| `exposure_us` | float | 4991.0 | — | `BlackflyCamera.__init__()` |
| `gain_db` | float | 0.0 | — | `BlackflyCamera.__init__()` |
| `pixel_format` | str | "Mono8" | — | `BlackflyCamera.__init__()` |
| `gamma_enabled` | bool | True | — | `BlackflyCamera.__init__()` |
| `gamma_value` | float | 1.0 | — | `BlackflyCamera.__init__()` |
| `binning` | int | 1 | — | `BlackflyCamera.__init__()` |
| `fps` | float | 10.0 | — | `BlackflyCamera.__init__()` |
| `simulation` | bool | False | — | `BlackflyCamera.__init__()` |

---

## laser

Manual laser configuration (no active driver; metadata only).

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `wavelength_nm` | int | 660 | — | `LaserManualMetadata.__init__()` (stored in run metadata) |
| `repetition_mode` | str | "external" | — | `LaserManualMetadata.__init__()` |
| `repetition_frequency_hz` | float | 1000 | — | `LaserManualMetadata.__init__()` |

---

## slow_control

Environmental monitoring (temperature, humidity, bias voltage, leakage current, etc.). Per-channel config is validated by `SlowControlManager.from_config()`.

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `poll_interval_s` | float | 5.0 | — | `SlowControlManager.__init__()` |
| `channels` | list[dict] | — | `SlowControlManager.from_config()` | `SlowControlManager.__init__()` |
| `channels[].name` | str | — | (nested validation) | Channel metadata |
| `channels[].unit` | str | — | (nested validation) | Channel metadata |
| `channels[].backend` | str | "simulated" | (nested validation) | Channel backend selection |
| `channels[].nominal` | float | — | (nested validation) | `SimulatedSlowControlChannel.__init__()` |
| `channels[].noise` | float | — | (nested validation) | (simulated backend) |
| `channels[].drift_amplitude` | float | — | (nested validation) | (simulated backend) |
| `channels[].drift_period_s` | float | — | (nested validation) | (simulated backend) |
| `channels[].warn_low` | float | — | `SlowControlManager.from_config()` ERROR if low ≥ high | Per-point analysis status (advisory WARN level, scan continues) |
| `channels[].warn_high` | float | — | `SlowControlManager.from_config()` ERROR if low ≥ high | Per-point analysis status (advisory WARN level, scan continues) |
| `channels[].alarm_low` | float | — | `SlowControlManager.from_config()` ERROR if low ≥ high | Per-point analysis status (critical ALARM level, scan continues) |
| `channels[].alarm_high` | float | — | `SlowControlManager.from_config()` ERROR if low ≥ high | Per-point analysis status (critical ALARM level, scan continues) |

---

## influx

InfluxDB writer configuration. Parsed by `InfluxWriter.from_config()` in `data/influx_writer.py`.

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `enabled` | bool | False | — | `data/influx_writer.py` (export logic gates) |
| `url` | str | "http://localhost:8086" | — | `InfluxWriter.__init__()` |
| `token` | str | "my-influx-token" | — | `InfluxWriter.__init__()` |
| `org` | str | "tct" | — | `InfluxWriter.__init__()` |
| `bucket` | str | "tct_slowcontrol" | — | `InfluxWriter.__init__()` |
| `measurement` | str | — | — | `InfluxWriter.__init__()` (not in shipped devices.yaml) |

---

## output

Data storage and export configuration.

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `data_dir` | str | "runs" | — | `hdf5_writer.HDF5Writer.__init__()` |
| `save` | dict | — | `SaveOptions.from_config()` | `data/save_options.py` |
| `save.waveforms` | bool | True | (nested validation) | `HDF5Writer.record_point()` |
| `save.positions` | bool | True | (nested validation) | `HDF5Writer.record_point()` |
| `save.timestamp` | bool | True | (nested validation) | `HDF5Writer.record_point()` |
| `save.analysis` | bool | True | (nested validation) | `HDF5Writer.record_point()` |
| `save.bias` | bool | True | (nested validation) | `HDF5Writer.record_point()` |
| `save.slow_control` | bool | False | (nested validation) | `HDF5Writer` (slow-control group write) |
| `save.camera_frame` | bool | False | (nested validation) | `HDF5Writer` (camera frame write) |
| `save.run_metadata` | bool | True | (nested validation) | `HDF5Writer.write_metadata()` |

---

## analysis

Signal processing and calibration parameters.

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `termination_ohm` | float | 50.0 | `config_validator._check_analysis()` ERROR if ≤ 0 | `analysis/*.py` scripts |
| `integration_window_s` | list[float] | [2.0e-08, 1.5e-07] | `config_validator._check_analysis()` ERROR if not [t0, t1] with t0 < t1 | `analysis/laser_normalization.py`, impulse-response routines |
| `baseline_samples` | int | 20 | `config_validator._check_analysis()` ERROR if < 2 | `analysis/ToT_charge_energy.py` (baseline subtraction) |
| `cfd_fraction` | float | 0.3 | `config_validator._check_analysis()` ERROR if not in (0, 1) | `analysis/ToT_charge_energy.py` (constant-fraction discriminator) |
| `onset_threshold_fraction` | float | 0.1 | — | `analysis/ToT_charge_energy.py` (trigger-onset detection) |

---

## charge_calibration

Charge calibration reference and output units.

| Key | Type | Default | Validated by | Consumed by |
|-----|------|---------|--------------|-------------|
| `method` | str | "none" | — | `ChargeCalibration.from_config()` line ? |
| `termination_ohm` | float | 50.0 | — | `ChargeCalibration.__init__()` |
| `amp_gain` | float | 1.0 | — | `ChargeCalibration.__init__()` |
| `transimpedance_ohm` | float \| null | null | — | `ChargeCalibration.__init__()` |
| `output_units` | str | "pC" | — | `ChargeCalibration.__init__()` |
| `reference` | dict | — | `ChargeCalibration.from_config()` (nested validation) | `ChargeCalibration.__init__()` |
| `reference.diode_thickness_um` | float | 300.0 | (nested validation) | Calibration metadata |
| `reference.q_ref_raw_pC` | float \| null | null | (nested validation) | Calibration factor |
| `reference.k_factor` | float \| null | null | (nested validation) | Calibration factor |
| `reference.calibrated_at` | str \| null | null | (nested validation) | Calibration timestamp |

---

## Notes

- Keys are listed in the order they appear in the shipped `devices.yaml`.
- Some keys have no explicit default if they are backend-conditional or obtained from a printer preset (motor stage).
- Nested dicts like `software_limits`, `save`, `reference`, and `channels` are validated by their consuming modules, not the top-level typo checker, so they appear as single rows.
- Opt-in unipolar keys (`level_low_V`/`level_high_V`) are shipped commented-out; the bipolar legacy path (amplitude + offset) is the default.
- All VISA/serial paths assume Windows COM naming (COM3, COM4, etc.); cross-platform paths may differ.

