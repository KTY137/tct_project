# TCT Scan Output — Data Format

What the app writes to disk for each scan: on-disk layout, dtypes, ordering,
which groups are optional, and how to choose them. Source: `data/hdf5_writer.py`,
`data/save_options.py`, `controller/scan_controller.py`, `controller/device_manager.py`.

## Where files go

- Each scan creates a new run directory: `runs/run_00001/`, `runs/run_00002/`, …
  containing one file, **`waveforms.h5`** (HDF5).
- The base directory comes from `output.data_dir` in `configs/devices.yaml`
  (default `runs`). **Relative paths are anchored to the app root** (`TCT_app/`),
  so the location no longer depends on the directory you launch from. Set an
  absolute path to write elsewhere. The run index is `max(existing)+1`.
- A run directory is created for **every** scan type now: XY scans, voltage (IV)
  scans, and Z-focus scans (previously IV / Z-focus were not saved).

## Choosing what to save

Controlled by `output.save` in `configs/devices.yaml`, editable in the GUI at
**Settings… → Data / Saving**. Per group:

| Group          | Default | Toggleable | Notes |
|----------------|---------|------------|-------|
| `waveforms`    | on      | **No (mandatory)** | raw ref/dut traces + time axis |
| `positions`    | on      | **No (mandatory)** | x/y/z stage coordinates |
| `timestamp`    | on      | yes | per-point epoch seconds |
| `analysis`     | on      | yes | **derived** — recomputable from waveforms |
| `bias`         | on      | yes | **measured** V/I — NOT recomputable |
| `slow_control` | off     | yes | **measured** env snapshot — NOT recomputable |
| `camera_frame` | off     | yes | per-point image — large |
| `run_metadata` | on      | yes | scan config + devices.yaml snapshot + calibration |

`waveforms` + `positions` are always written. Disabling `bias` / `slow_control`
loses information that cannot be reconstructed offline (the UI warns in red).

## File format: HDF5

A single `.h5` file written incrementally. Open with `h5py`, `PyTables`, MATLAB
`h5read`, or HDFView.

### Root attributes
| Attr         | Type | Notes |
|--------------|------|-------|
| `start_time` | str  | `YYYY-MM-DDTHH:MM:SS` when the file was opened |
| `stop_time`  | str  | when the writer closed |

### `/run_info` (group, attrs) — when `run_metadata` is on
Self-describing metadata so a run is interpretable without external context:
- `scan_type` — `xy_scan` | `voltage_scan` | `z_focus_amplitude` | `z_focus_edge`
- `scan_config` — JSON of the scan dataclass (ranges, steps, averages, …)
- `devices_config` — JSON snapshot of `devices.yaml` (Influx token redacted)
- `charge_calibration` — JSON of the calibration block in effect
- `software_limits` — stage travel limits
- `start_time`

### Datasets (XY scans)

`N` = points written, `S` = samples per waveform. Scalar datasets are extensible
(`maxshape=(None,)`, gzip, chunk 64).

**`/points/`** (f8, `(N,)`) — `x_mm`, `y_mm`, `z_mm` *(mandatory)*, `timestamp` *(opt)*

**`/waveforms/`** *(mandatory)*
| Dataset             | dtype | Shape    | Notes |
|---------------------|-------|----------|-------|
| `waveforms/time_s`  | f8    | `(S,)`   | written once from the first point |
| `waveforms/ref_ch1` | f4    | `(N, S)` | reference channel (last average of each point) |
| `waveforms/dut_ch2` | f4    | `(N, S)` | DUT channel (last average of each point) |

**`/analysis/`** (f8, `(N,)`) — when `analysis` is on. `ref_amplitude_V`,
`ref_charge_pC`, `dut_amplitude_V`, `dut_charge_pC`, `dut_charge_norm`,
`dut_charge_cal` *(present only when a charge calibration is configured)*,
`baseline_rms_V`, `drift_time_ns`, `rise_time_ns`, `cfd_time_ns`, `onset_time_ns`.
Times are ns; missing values are `NaN`.

**`/bias/`** (f8, `(N,)`) — when `bias` is on. `voltage_V`, `current_A` (measured at each point).

**`/slow_control/<channel>`** (f8, `(N,)`) — when `slow_control` is on. One dataset
per configured channel (e.g. `temperature_C`, `humidity_pct`).

**`/camera/frames`** (`(N, H, W)`, gzip) — when `camera_frame` is on. Per-point image;
frames whose size differs from the first are skipped.

### Datasets (other scan types)

- **Voltage (IV) scans** → `/voltage_scan/{voltage_V, charge_pC, current_A}` (f8, `(K,)`).
- **Z-focus scans** → `/z_focus/{z_mm, metric}` (f8, `(K,)`); `metric` is DUT amplitude
  (amplitude mode) or edge sharpness `|dQ/dx|` (edge mode).

The saved trace is the **last** average; the scalar amplitude/charge values are the
**mean** over `n_averages`.

## Point ordering — IMPORTANT (serpentine)

XY scans walk X outer, Y inner, **reversing Y on every other X row** (boustrophedon,
to minimise stage travel). Row index `i` is therefore **not** a row-major grid index.
Reconstruct the 2-D map from the actual `points/x_mm` / `points/y_mm` datasets — do
**not** `reshape(ny, nx)`.

## Minimal read example

```python
import h5py, numpy as np, json
from analysis.scan_grid import points_to_grid

with h5py.File("runs/run_00001/waveforms.h5", "r") as f:
    info = {k: f["run_info"].attrs[k] for k in f["run_info"].attrs} if "run_info" in f else {}
    x = f["points/x_mm"][:]; y = f["points/y_mm"][:]
    q = f["analysis/dut_charge_pC"][:]
    t = f["waveforms/time_s"][:]; dut = f["waveforms/dut_ch2"][:]

# 2-D charge map (handles serpentine ordering; unsampled cells are NaN, not
# dropped — see analysis/scan_grid.py for the full NaN-counting contract).
result = points_to_grid(x, y, q)
grid, xi, yi = result.grid, result.x_mm, result.y_mm
```
