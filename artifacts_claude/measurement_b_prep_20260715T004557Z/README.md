# Measurement B — acquisition-headroom spike (Lantern U2 entry gate)

**Prep bundle. This is NOT a live result.** It contains the built harness'
offscreen mechanics-smoke log and the how-to for the real windowed run, which is
the operator's to execute (Kaya/Adam), exactly like the U0 RHI probe.

- Harness: `TCT_app/scripts/spike_measurement_b.py`
- Protocol source: `docs/design/qml_kit_forge/candidate_lantern.md` §7 (with §3.2
  bake-during-run reconciliation).
- Mechanism reused from measurement A: `layer.live:false` + a timed
  `scheduleUpdate()` = **one** blur pass; N panes are crop-blit
  `ShaderEffectSource` samplers; `bakeCount` telemetry
  (`TCT_app/scripts/spikes/lantern_frost_bake_spike.py`, commit `4c5de40`).

## What it measures

§7 names the gate: the idle-rate frost bake + living ground at `full`, running
**through a live simulated scan** (sim `DeviceManager` + `ScanController` +
`HDF5Writer` + a 30 Hz plot island), asserting **the plot holds rate** and **DAQ
cadence does not jitter**. It is a WITH/WITHOUT comparison in one process on one
`DeviceManager`/controller:

| cell | what runs |
|---|---|
| `baseline` | sim XY scan + 30 Hz pyqtgraph island (fed live per-point DUT charge). No frost scene. |
| `loaded` | the SAME scan + island, PLUS the living ground at `full` + ONE frost bake @ 12 Hz + N live crop-sampler panes. Worst case: every pane keeps sampling the shared bake (no run-owning-pane freeze), because §3.2 says the shared bake keeps serving the flowing room during a scan. |

The harness edits **no** app code — it composes `controller/`, `devices/`,
`data/` as-is. It never imports a real transport driver module directly; it goes
through the app's own composition root (`DeviceManager`), as §7 specifies.

## Safety (sim-only by construction AND by guard)

1. The harness writes its **own** forced-sim `devices.yaml` (every backend =
   simulated / `simulation: true`, `output.data_dir` = a temp path) and only
   then builds `DeviceManager`.
2. `assert_simulated(dev)` re-verifies **every** constructed device instance is
   in simulation mode **before** `connect_all` performs any I/O. Any non-sim
   backend → refuse, **exit 3**, never connect.
3. The simulated stage is homed via the sim `home()` (in-memory flag, no
   hardware) — the sim twin of the operator homing before a scan; a re-check
   guarantees it can only reach a simulated stage.
4. HDF5 is written into a temp / artifacts path only, never a real data dir.

## How to run the LIVE windowed measurement (operator only)

Standing rule: agents do not run windowed GUI locally (instruments may be
cabled). Run this on the lab laptop's real desktop session, no `QT_QPA_PLATFORM`
override:

```
cd TCT_app
.venv/Scripts/python.exe scripts/spike_measurement_b.py
```

Optional knobs: `--seconds 15` (window per cell), `--panes 6`, `--rebake-hz 12`,
`--settle 0.02` (scan per-point settle), `--hold 20` (eyeball the loaded scene +
live scan on screen, no verdict).

- **Expected duration:** ≈ `2 × (warmup + seconds)` + teardown ≈ **40–55 s** at
  defaults (15 s window, 3 s warmup, two cells). An out-of-process watchdog
  hard-kills after `2×(warmup+seconds)+150 s` so it can never hang a gate.
- **Output:** `artifacts_claude/measurement_b_<UTC>/spike_report.json` + the
  printed PASS/FAIL block; the sim scan's HDF5 lands under that folder's
  `scan_runs/`.

### What PASS looks like

```
VERDICT
  (P1) plot holds rate: island >= 28.0 Hz AND >= 0.90 × baseline island  -> PASS
  (P2) DAQ no jitter:   loaded point-rate >= 0.80 × baseline rate AND
                        loaded inter-point CV <= max(1.5 × baseline CV, 0.50) -> PASS
  (P3) frost renders:   loaded qml_fps >= 55.0                            -> PASS

  OVERALL: PASS
```

Exit codes: **0** pass · **2** fail · **3** guard-trip / real-session refused ·
**4** harness error.

If **OVERALL: FAIL**, the §7 fallback is run-active **global** calm (bake → 0 Hz
app-wide), which returns the panel-scoped-calm refinement to Kaya with the
numbers.

### Thresholds — note

§7 named the assertions ("plot holds rate", "DAQ cadence does not jitter") but
not the numbers. The island floor (28 Hz) and QML fps floor (55) are inherited
from measurement A; the retention (0.90 island, 0.80 DAQ rate) and jitter
ceiling (CV ≤ max(1.5× baseline, 0.50)) are the **entry-gate proposal** — tune
them from the printed baseline/loaded numbers before ratifying the gate. They
are named constants at the top of the harness.

## Files in this bundle

- `smoke_offscreen.log` — the `--smoke` mechanics check (offscreen, no fps
  assertions): sim guard passes; guard trips on a forced non-sim device; the sim
  scan starts and produces points; HDF5 written to a temp path; island + cadence
  telemetry emit; the frost QML parses; clean exit (`SMOKE PASS`, exit 0).
- `guard_proofs.log` — the windowed run refusing under a headless Qt platform
  (exit 3).
