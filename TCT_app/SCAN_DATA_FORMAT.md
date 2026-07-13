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
| Attr           | Type | Notes |
|----------------|------|-------|
| `start_time`   | str  | `YYYY-MM-DDTHH:MM:SS` when the file was opened |
| `stop_time`    | str  | when the writer closed |
| `outcome`      | str  | how the run ended — see "Run outcome" below |
| `abort_reason` | str  | free text; empty for a clean `finished` run |

#### Run outcome — how did this run end?

Before this existed, a trip-aborted run was **byte-for-byte indistinguishable**
from a scan that simply finished early: the file carried only `start_time` /
`stop_time`, and `run_info` only ever held the *pre-run* config snapshot.
`outcome` closes that gap. Written by `HDF5Writer.close()` from
`ScanController._end_run` (`HDF5Writer.set_outcome(outcome, reason=None)`,
called once, right before `close()`), so it is present on **every** run
regardless of which optional groups (`run_metadata` included) were enabled —
this is integrity information, not reconstructable scan metadata, so it is a
root attr rather than nested under `/run_info`.

| `outcome`  | Meaning |
|------------|---------|
| `finished` | Clean end of the scan/sweep — `abort_reason` is empty. |
| `aborted`  | Operator abort, a denied danger-gate confirmation, a bias compliance/hardware trip, or a slow-control ALARM fail-safe. `abort_reason` names the cause (e.g. contains `"trip"`, `"Compliance"`, `"ALARM"`, or `"Operator abort"`). |
| `error`    | An unhandled exception during the run. `abort_reason` carries `str(exc)`. |
| `unknown`  | **The writer was closed without ever recording an outcome** — a crash, a killed process, or (in principle) a bug that skipped the call. This is the honest default, not a fallback to `finished`: an analyst seeing `unknown` should treat the run the same as `aborted`/`error` — trust only the points actually on disk, and do not assume the scan covered its full configured range. |

**Analyst guidance:** always check `outcome` before treating a run as a
complete dataset. `aborted` / `error` / `unknown` all mean the file may hold
fewer points than `run_info/scan_config` describes — data already written is
valid and preserved, but the run did not necessarily reach its planned end.

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

**`/camera/`** — when `camera_frame` is on (or after `set_camera_calibration` is called).
`M` = frames actually written (`M <= N`; see below).

- `camera/frames` (frame dtype, gzip, shape `(M, H, W)`) — one entry per frame
  **actually written**.
- `camera/frame_point_index` (i8, shape `(M,)`) — `frame_point_index[k]` is the
  `points/` row that `frames[k]` belongs to.
- `camera` group attr `n_frames_omitted` (int) — count of dropped frames over
  the whole run; always present (even `0`) whenever the `camera` group exists.
- `camera` group attr `px_per_mm` (f8, optional) — from `set_camera_calibration`.
- `camera` group attr `affine` (f8 array, optional) — flat array from
  `set_camera_calibration` (shape is the caller's convention — see
  `analysis/camera_calibration.py`).
- `camera/frame_pos_mm` (f8, shape `(M, 3)`, columns `[x_mm, y_mm, z_mm]`,
  dataset attr `columns` names them) — the stage position each written frame
  was grabbed at, index-aligned with `frames`/`frame_point_index` (row `k`
  ↔ `frames[k]`). Present whenever the `camera` group has at least one
  written frame (both `HDF5Writer.save_point`'s implicit per-point grab and
  the standalone `save_camera_frame` write it — see CAPTURE_PHOTO below).
  **A frame with unknown position gets a `(NaN, NaN, NaN)` row, never a
  dropped row and never a fake `(0, 0, 0)`** — `frame_pos_mm` stays exactly
  `M` rows long like its siblings, so it never desyncs with them; check
  `np.isnan(...)` per row rather than assuming every frame's position is
  known. (Older files written before this dataset existed simply lack it —
  guard reads with `"frame_pos_mm" in f["camera"]`.)

A frame is dropped (counted in `n_frames_omitted`, and logged via
`logging.getLogger("data.hdf5_writer")` at `WARNING`) when: the grabbed frame
is `None` (grab failure), its array has `ndim < 2`, or its shape differs from
the first accepted frame's shape.

**`camera/frames` is never zero-padded and may be shorter than `points/`.**
`M <= N`: a dropped frame simply does not get an entry — the old behaviour of
`resize()`-ing to the point count (silently backfilling a skipped point with
an all-zero frame, indistinguishable from a real dark frame) is gone. Always
use `frame_point_index` to map `frames[k]` back to `points/x_mm[frame_point_index[k]]`
etc.; do **not** assume `frames[i]` corresponds to `points[i]`.

#### CAPTURE_PHOTO — standalone photo captures (e.g. camera surveys/mosaics)

A `CAPTURE_PHOTO` plan step (`controller/scan_plan.py` `ActionType.CAPTURE_PHOTO`,
built e.g. by `controller/survey_plan.plan_survey` for a snake-raster camera
survey) is a **passive, non-acquiring** capture: it settles, grabs one frame,
and writes it through `HDF5Writer.save_camera_frame(frame, pos_mm=...)` (the
executor supplies the current stage position — see below) — **not** through
`save_point`. Consequences for the file:

- It writes **only** the `/camera` group (`frames`, `frame_point_index`,
  `frame_pos_mm`) — no `waveforms`, `analysis`, `bias`, or `points/` row.
  Routing a photo-only capture through `save_point` would either crash (a
  zero-size chunk on the mandatory `waveforms` dataset) or desync the
  waveforms/points parallel arrays, so it deliberately does not.
- It does **not** advance the point counter — `frame_point_index[k]` for a
  CAPTURE_PHOTO frame **names the point row this frame will belong to once a
  later `SAVE_POINT` at the same coordinate is written**; it does not require
  that row to already exist yet.
- **Dangling-tag caveat:** a plan that calls CAPTURE_PHOTO and then never
  writes a matching `SAVE_POINT` for that coordinate (run ends early, moves
  on without saving, or — the common case — a **photo-only survey that has
  no acquire/save step at all**, so `points/` stays empty for the whole run)
  leaves `frame_point_index[k] >= len(points/x_mm)`. Readers must
  bounds-check `frame_point_index` against `points/` length before indexing
  with it — do not assume it is always a valid row.
- **Position for a photo-only survey (no `points/` rows to hold it) comes
  from `camera/frame_pos_mm` instead**: `controller/scan_controller.py`'s
  `_write_camera_frame` reads the stage's current position (the move already
  landed before the settle+grab) and passes it through, so
  `frame_pos_mm[k]` is populated even though `frame_point_index[k]` may be
  dangling. A survey's tile geometry is *also* independently reconstructable
  from `run_info/scan_config`'s `safety.survey` block (`area_mm`, `fov_mm`,
  `overlap_frac`, `origin_mm`, `rows`, `cols`, snake order) — see
  `controller/survey_plan.py` — `frame_pos_mm` is the direct per-frame record,
  the `safety.survey` geometry is the derivable cross-check.

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
