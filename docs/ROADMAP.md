# TCT Control — Product Roadmap

*Owner: Adam (lead architect). Written 2026-07-07. This is the strategic map; the
tactical resume point always lives in `docs/SESSION_HANDOFF.md`, and open debt in
`docs/TECH_DEBT.md`.*

## North star

A safe, reliable, and pleasant desktop app for running Transient-Current-Technique
measurements — one that a lab operator trusts with high voltage and a moving stage,
that runs fully in simulation for development, and whose every surface reads as one
designed system.

## Principles that hold across every phase

- **Safety is not a feature, it's a gate.** No hardware I/O at import/construct;
  HV ramp / motion / homing / scan-start require explicit confirmation *in Python*,
  never trusted to a UI/JS layer; fail safe on every error path (stop motion, ramp
  down, surface the error). Agents test in simulation + pytest only.
- **The app is always runnable simulated**, at every commit, with zero hardware.
- **PySide6, not PyQt6.** Small, reviewable patches over rewrites.
- **One common design scheme.** Every panel draws from the `gui/style.py` token
  system — same accent, same axis colors, same spacing/motion everywhere.

Status key: ✅ done · 🔨 in progress · ⏭ next · 🔭 horizon

---

## Phase 0 — Foundation ✅

Device-driver abstractions (`*_base.py`) with real **and** simulated backends,
the PySide6 shell, `config_validator`, the HDF5 writer, the headless pytest suite,
and the agent crew. This is the bedrock the rest stands on.

## Phase 1 — Multi-channel bias + polarity ✅ (Milestone 1)

`BiasChannel` proxy, channel-aware ISEG driver (one VISA session, N channels),
HV-gated polarity read/set, `MultiBiasPanel`, and optional `bias_channel` on scan
configs. Reviewed and safety-hardened (emergency-off disables output even if the
ramp raises). **153 tests green.**

---

## Phase 2 — GUI modernization & the scan planner 🔨 (current milestone)

The visual + interaction overhaul, culminating in the marquee feature. Design
preview: `artifacts_claude/scan_planner_preview_claude.html` (published live).

| Sub | What | Status |
|---|---|---|
| **2.1** | **Design-system foundation** — token set, scope-cyan accent (`#33c8ff`/`#0d8ba6`), axis-rail palette + `axis_color()`, `statusChip`/`eyebrow` hooks. | ✅ |
| **2.2** | **Scan Routine Planner** (the marquee) — see below. | ⏭ next |
| **2.3** | **Common scheme everywhere** — fold `axis_color()` into every panel so bias reads amber, Z violet, X teal, Y magenta, laser purple, delay green *identically* across the app. **Visual reference (user decision 2026-07-07): the planner theme** — `artifacts_claude/TCT Scan Routine Planner.html` (canonical) + `artifacts_claude/scan_planner_preview_claude.html` (token rendition) — is the example every panel converges toward. | ⏭ |
| **2.4** | **Appearance settings — adjustable colors** — see below. | ⏭ |
| **2.5** | **Tasteful motion** — animations at reasonable points, see below. | ⏭ |

### 2.2 Scan Routine Planner — how it looks & how it's built

A **Recipe Tree**: nested parameter loops (each axis = one signature color, a
colored left-edge rail carrying down through everything nested), wrapping action
leaves (Move · Settle · Acquire · Extract · Save), with **guard** nodes (green
shield: preflight, leakage check → abort+ramp-down) and **danger** nodes
(hazard-red stripe + "⚠ confirm": HV ramp, stage move, homing). A sticky
**"Before you run"** panel shows Total points / Est. runtime / Est. data / Stage
travel / HV range + warnings + **Validate / Dry Run / Arm HV / Start** (Start
locked until HV armed).

The spine already exists and is clean — `controller/scan_plan.py` (fail-closed
`ScanPlan` tree, YAML round-trip, `iter_leaf_contexts()`), but **nothing validates
or executes it yet.** Build order (each step keeps the app runnable):

1. **Pure modules** — `scan_plan_validator.py` (limits, `max_points` cap,
   fail-closed HV-confirmation requirement) + `plan_estimate.py` (points, runtime,
   data size, stage travel, HV range) + `plan_compiler.compile_plan()` (tree →
   ordered typed steps). No Qt, no hardware — unit-tested.
2. **Executor + safety gate on `ScanController`** — `start_plan()`/`_run_plan()`
   modeled byte-for-byte on the existing `start()`/`_run()` (same daemon thread,
   `_pause_event`/`_abort_event`, `_ScanBridge`, `_resolve_bias`, compliance
   abort). A **generic `DangerGate`** (`confirm(DangerAction) -> bool`) + an
   `arm_hv()` latch — the missing "confirm dangerous action" primitive — so every
   danger node and Arm-HV routes UI→Python→driver, never JS-trusted.
3. **Native panel (Option B) — ✅ DONE, and the chosen face** — `gui/planner_panel.py`,
   the first consumer of `axis_color`/`statusChip`/`eyebrow`/`dangerBtn`; wires like
   `ScanPanel` (emit signals → `tct_gui` calls the controller). Fully headless-testable.
   Shipped with a drag-and-drop block palette, movable nodes, and structural undo.
4. **Option C embed — SHELVED (user decision 2026-07-07: stay native).** The native
   panel (v1 + v2 drag-drop) overtook the embed on capability, is fully
   headless-testable, and keeps every danger confirm Python-side without a JS
   bridge. The `QWebEngineView`/`QWebChannel` embed is not being built; the exported
   artifact stays a visual reference only. Reopen only if pixel-1:1 fidelity ever
   outweighs testability.

### 2.4 Appearance settings — user-adjustable colors

A new **Appearance** tab in `gui/settings_window.py` (already per-device-tabbed):
color pickers for the theme accent + the axis-rail palette, live-previewed through
`apply_theme()`, persisted via `QSettings("TCT","TCTSetup")`, with a "reset to
defaults" and light/dark per-mode overrides. Because every panel reads
`gui/style.py` tokens (Phase 2.3), one edit recolors the whole app — that's the
payoff of the common scheme. Ships with sensible presets (default, high-contrast,
colorblind-safe axis set).

### 2.5 Tasteful motion

Animations only where they carry meaning, all `prefers-reduced-motion`-aware and
inside the design scheme: theme cross-fade, HV-ramp progress + status-chip pulse
on state change, panel/tab reveal, "arming" pulse on the Arm-HV control, and a
subtle running indicator during a scan. `QPropertyAnimation`/`QGraphicsOpacity`
in Qt; the CSS analogues are demonstrated in the design preview. No motion on the
data plots' hot path.

---

## Phase 3 — Robustness & verification ⏭ (requested)

Make the software trustworthy under real, flaky hardware — harden the drivers and
add *verification* everywhere before we lean on real instruments.

- **Driver hardening** — explicit timeouts, bounded retries with backoff, clean
  reconnect, and a documented fail-safe on every error path. Extend real
  liveness/heartbeat to **all** devices (today only the scope has a true `*STB?`
  probe; motor/bias/camera are flag-based).
- **Verification harness** — a read-only `verify()`/self-test per device (identify,
  ping, safe reads) and a whole-chain **pre-flight** run before any scan; close the
  `config_validator` gap (6 sections — camera/laser/slow_control/influx/output/
  charge_calibration — currently unchecked, silent-typo risk).
- **Fault-injection tests** — simulated mid-scan disconnect, HV trip, motor fault,
  compliance breach → assert the app fails safe (stops motion, ramps down/off,
  surfaces the error) and never corrupts the HDF5 run.
- **Command provenance** — resolve the bench TODOs (ISEG polarity relay settle,
  TBS1052C `PRObe:GAIN?`/`COUPling?` query forms) and codify every verified
  SCPI/GRBL command with a cited source; no guessed commands.
- **Coverage & gating** — grow the suite around the above; treat "153+ green,
  simulated" as the release gate.

**How it looks:** a "System check" surface that runs the per-device `verify()` and
the pre-flight, showing each device as a `statusChip` (good/warn/crit) — the same
component the planner uses — so health reads at a glance.

## Phase 4 — Acquisition engine maturity ⏭

Productionize the executor into a full routine engine: composable stages (XY(Z)
raster, per-channel bias sweep, z-focus/laser-align, per-point acquire+save, and
laser/wavegen params — duty cycle, amplitude, frequency), **resumable/checkpointed**
scans, richer run metadata, and rock-solid pause/resume/abort. Routines save / load
/ share (YAML round-trip already in `scan_plan.py`).

## Phase 5 — Data & analysis pipeline 🔭

Harden the HDF5 contract (`SCAN_DATA_FORMAT.md`); live in-GUI analysis & plots;
InfluxDB slow-control logging; offline analysis (charge/CCE/energy conversion,
laser normalization, ToT); scan reconstruction and calibration workflows.

## Phase 6 — Real-hardware bring-up & bench validation 🔭

Bring up the real instruments behind the sim backends — DRS4 eval board, FLIR
Blackfly, real ISEG/Keithley, PI/GRBL/Marlin stages — validating sim-vs-real
parity and resolving all bench-only TODOs (incl. the Marlin Z-endstop fix). Every
new command path goes through Phase 3's provenance rule.

## Phase 7 — Operations & UX polish 🔭

Experiment templates/presets, session management, run history + reporting/export,
remote monitoring, and operator-facing docs.

## Phase 8 — Automation & intelligence 🔭 (horizon)

Auto-alignment / auto-focus routines, unattended long-run scheduling with anomaly
detection + auto-abort, and guided setup. Everything here still delegates to the
Phase-2/3 safety gates — automation never bypasses a confirm.

---

## Near-term ordered next steps

1. **P2.2 step 1** — pure `scan_plan_validator.py` + `plan_estimate.py` +
   `plan_compiler.compile_plan()` with tests (zero runtime risk).
2. **P2.2 step 2** — `DangerGate` + `arm_hv()` latch + `start_plan()`/`_run_plan()`
   on `ScanController`; headless executor tests (unarmed/deny/compliance paths).
3. **P2.2 step 3** — native `planner_panel.py` + tab wiring + `_teardown_panels`
   registration.
4. **P2.3 / P2.4 / P2.5** — fold `axis_color` into panels; Appearance settings tab;
   motion pass.
5. **Phase 3 kickoff** — `config_validator` gap + per-device `verify()` + first
   fault-injection tests.

## Verification (how we prove each step)

- Headless suite from `TCT_app/`:
  `QT_QPA_PLATFORM=offscreen .venv\Scripts\python.exe -m pytest tests/ -q`
  (must stay green; simulation-safe with real hardware attached).
- Theme smoke: `apply_theme(app,'dark')` + `'light')` both render.
- Planner: pure-module unit tests + executor tests against simulated devices with
  a fake `DangerGate` (assert unarmed refuses HV, deny-path leaves bias at 0 V,
  compliance aborts + ramps down + output-off).
- Bench-only checks (never run by agents) stay in `docs/TECH_DEBT.md`.
