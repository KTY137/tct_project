# Overnight autonomous run — log & charter

*Started 2026-07-08 night. User (Kaya) asleep, granted blanket approval:
"be ambitious, do all the things we talked about; when a sequence finishes,
construct a new one." Themes named: general style expansion, driver/intercom
robustness, more Scan Planner features, be creative.*

## Guardrails that blanket approval does NOT waive

- **No real hardware, no HV, no laser, no motor motion.** Everything simulated /
  headless. Wavegen output stays off. Bench-only verification is deferred to
  `docs/BENCH_CHECKLIST.md` (needs Kaya physically present).
- **Mary reviews every substantial change before commit.** Green full suite
  (`QT_QPA_PLATFORM=offscreen … pytest tests/ -q`) is the gate.
- **Architecture-scale work is design-first**: Prometheus stress-test + a
  `docs/design/` or `docs/research/` note before building, not build-then-hope.
- **The agent_env intercom/harness is meta-infra**: I *analyze and propose*
  (a note + patch plan), I do **not** autonomously rewrite the coordination
  layer I run on. Its changes wait for Kaya's explicit go.
- Each theme-sequence is fully built → reviewed → committed → pushed before the
  next starts. No half-landed towers.

## Sequence ledger (append one line per beat)

- **S0 DONE 2026-07-08:** viewer-prerequisites round committed+pushed (5922dbc..d990d4d, 7 commits): crew tuning, G1 ramp shaping, analysis grid/CCE, cockpit kit, pytest-timeout, pyvisa+armed fix, theme-apply AV fix. Suite 571 passed.
- **S1 DONE 2026-07-08:** shared map widget + ramp-aware estimate + PNG-export fix (7cba862, bc59250). Mary APPROVE-WITH-NITS. Suite 594.
- **S2a DONE 2026-07-08:** scan_coordinator extracted from tct_gui (behavior-preserving, Mary byte-identical HV verify) + AnalysisPanel.load_run seam (412abe1, 3d3b4b8). Suite 611. Next: S2b ScanViewerPanel, S2c retire ScanPanel.

## Theme backlog (ranked; I pull sequences from here top-down)

### T1 — Scan Viewer (Cockpit Phase 2), already scoped
Shared map widget → `scan_coordinator` extraction (Abel logic @Opus + Noah
wiring, paired, behavior-preserving) → `ScanViewerPanel` → retire ScanPanel.
Design locked in `docs/design/cockpit_style_overhaul.md` +
`docs/research/scan_viewer_design_review.md`.

### T2 — Driver robustness (sim-testable hardening)
- `is_alive()` for every backend (the `gui_architecture_plan.md` follow-up):
  GRBL motor `?` status poll, ISEG bias status query (needs cited form → maybe
  Prometheus), wavegen `*STB?`, camera PySpin `IsValid`/`DeviceConnected`.
- Fault-injection tests: connection loss mid-scan, timeout on every I/O path,
  device fault → fail-safe (stop motion / ramp-down / surface) — extend the
  existing `test_fault_injection*` suite.
- Retry/timeout audit across drivers; unify the pattern; ensure no unbounded
  retry, every read idempotent-only.
- Wire the wavegen armed-state + `:OUTPut:LOAD?` readback (INFINITY-literal
  safe) now that the query forms are manual-cited.

### T3 — General style expansion (Cockpit Phases 1 & 4)
- **Phase 1 CameraPanel rework**: big `FigureCard` instrument screen +
  Acquisition Console cards + `MetricGrid` beam stats + histogram FigureCard;
  migrate the hand-rolled temp readout to `ReadoutCell.set_state()`.
- **Phase 4 consistency sweep**: kill the 24 legacy inline-hex across 9 gui
  files (Mamoru has the list), tokenize `scope_measurements.py` cyan, give every
  color-caching panel `refresh_theme(mode)`, wire the orphan kit tokens
  (`panel_2/3`, `sunk`, `border_strong`, `hover`, `active`) into real surfaces.
- App-shell polish (rule 5 — no logic into tct_gui): toolbar icon unification,
  status "system ribbon", tab active-state.

### T4 — Scan Planner features (creative, design-first)
Candidates to stress-test with Prometheus then build the best 2-3:
recipe presets/templates library; plan dry-run preview + per-step ETA using the
new ramp-aware estimate; conditional/adaptive steps (skip-if, stop-on-threshold);
named pause-points; multi-region (stitched sub-rasters); plan diff/versioning;
plan import/export polish; live plan-vs-actual overlay in the viewer.
`plan_estimate` ramp-preview follow-up folds in here.

### T4.5 — Data pipeline & live TCT maps (Jonathan-led, design-first) ⭐ Kaya-requested
- **Live 2D TCT scan maps** — largely lands *with* the ScanViewer (T1): the
  `on_point_done` stream + Jonathan's `analysis/scan_grid.py` (already
  NaN-counting, mid-scan tolerant) feed a live heatmap. "Epic" upgrades:
  per-quantity selector (charge_pC / amplitude_V / ToT / drift_time / rise_time
  / cfd_time — the set `scan_map_window` already knows), live autoscaling
  colorbar, cursor readout of the point under the crosshair, progress overlay
  (n_missing already available). Build the map widget once, reuse live + review.
- **Modular save policy** — the storage-efficiency ask. Introduce a pluggable
  `SavePolicy` in `data/save_options.py` (strategy pattern) that the
  `hdf5_writer` consults per `ScanResult` for *what to persist*:
  - `full` — DUT + ref waveforms + derived scalars (today's behavior; default,
    unchanged).
  - `derived_only` — only the DUT scalar quantities (charge/amplitude/timing),
    **no waveforms** → order-of-magnitude smaller files for big rasters.
  - `dut_only` — drop the reference waveform, keep DUT (or a decimated form).
  - (stretch) `on_condition` — full waveform only when a threshold/flag is met.
  MODULARITY + Jonathan's non-negotiables: the policy is explicit, recorded in
  file metadata (analysis must know waveforms were *intentionally* not stored,
  not lost), and `SCAN_DATA_FORMAT.md` documents each policy's resulting layout.
  Never silently discard — the "waveforms omitted by policy X" state is a
  first-class, counted attribute. Design-first: Prometheus stress-test + a
  `docs/design/` note (format-contract change), then Jonathan implements.

### T5 — Intercom/harness robustness (PROPOSE ONLY, no auto-merge)
Read-only analysis of the `agent_env` file bus (outbox→inbox, file_bridge,
watcher, lane routing): failure modes, lost-message handling, stale-lock
recovery, the local_only fallback. Deliver a `docs/research/` note + patch plan.
Do not edit the harness autonomously.

### T6 — Test/infra hardening (fold in opportunistically)
Root-cause + kill the pyqtgraph/offscreen access-violation class properly (not
just the one call site); consider a session-scoped QApplication fixture +
deferred-delete flush in conftest; pin pytest itself in requirements.

## Open decisions parked for Kaya (I will NOT guess these)
- **Map colorbar levels (2026-07-08):** the new shared `ScanMapView` always
  autoscales the colorbar (nanmin/nanmax over sampled cells); the old
  `ScanMapWindow` "Auto levels" checkbox / manual level-lock was dropped in the
  refactor. Autoscale is the right default for a live-filling scan, but manual
  level-locking is useful for comparing runs on a fixed scale. → Decision: do
  you want a level-lock control back (min/max spinboxes or a "freeze levels"
  toggle) on the ScanViewer? Cheap to add later; not blocking. Not currently a
  regression (no live caller used the old manual mode).
