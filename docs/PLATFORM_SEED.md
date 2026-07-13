# PLATFORM_SEED.md — the LabControl lift manifest

**Version:** 0.1.0-draft (§8 for the versioning rule). **Status:** early draft,
workstream S1 of `docs/ROADMAP_MASTERPLAN.md` Part VI. **Author:** Samantha
(docs-dev), from repo evidence at HEAD on `design/cockpit-v5`
(commit `7a0a447`). **Audience:** Völundr / NorthStar, building the future
LabControl platform, and the TCT crew maintaining the seed contract from this
side.

**What this is:** a contract, not marketing. Every claim below was checked
against source at draft time (file/symbol/line references, LOC counts
measured directly with ripgrep). Items the roadmap has designed but the repo
does not yet contain are marked **PENDING** with their roadmap stage — do not
build against a PENDING item as if it exists. Mamoru verifies every
file/symbol claim before it is trusted; treat an unverified claim as
provisional. **Do not implement against this draft** — it is not yet
Kaya-ratified, §6 is explicitly draft-for-review, and the seed tag
(`v1.0-platform-seed`) has not been cut (exit gate:
`docs/ROADMAP_MASTERPLAN.md` Part III, D4+D4b+P3+P4a+DA1+DA2+S0+S2+C2+PORT1).

---

## 1. What lifts untouched

Five packages under `TCT_app/` are provably GUI-free today — not by
convention, by a static test. `tests/test_layer_contracts.py` AST-walks every
`*.py` file and enforces a downward-only import graph (`_ALLOWED_TARGETS`):

| Layer | May import (project-internal) | Role |
|---|---|---|
| `analysis/` | *(nothing — pure leaf)* | stdlib + numpy only, no Qt, no project imports (`test_analysis_is_stdlib_and_numpy_pure`); named physics formulas (CCE, charge, depletion voltage, waveform/camera analysis) |
| `devices/` | *(nothing — driver floor)* | instrument drivers; never imports controller/data/analysis/gui/tct_gui/main (`test_devices_import_nothing_above`) |
| `vision/` | *(nothing — pure leaf)* | numpy + a lazily-imported `cv2` (never at module scope); ArUco fiducial / pose estimation |
| `controller/` | `devices`, `analysis`, `data` | scan sequencing, state machine, safety gating |
| `data/` | `devices`, `analysis` | HDF5 writer, save-options, optional Influx writer |

Measured LOC (ripgrep line count, 2026-07-13, `TCT_app/{devices,controller,
data,analysis,vision}/*.py`): **20,124 lines across 58 files** — devices
8,371 (24 files), controller 7,368 (17 files), data 534 (4 files), analysis
3,384 (11 files), vision 467 (2 files). This confirms the roadmap's "~20k
LOC" estimate; treat the figure above, not the roadmap's, as current.

`gui`/`tct_gui`/`main` sit above these five and are explicitly **not** part
of this lift (§2). `test_layer_contract_holds`, `test_devices_import_nothing_
above`, `test_analysis_is_stdlib_and_numpy_pure`, and
`test_only_main_py_imports_tct_gui` are the enforcement; a future LabControl
CI should re-run (or re-derive) the same AST check against whatever it
vendors from this seed, not just trust this document.

**Bucket-A test suite — PENDING artifact.** The roadmap defines a "bucket-A"
concept (~47 files, ~15k LOC of tests, green-and-unmodified as a gate on
every roadmap stage) but `docs/test_bucket_map.md` — the file that would name
the exact file list and run command — has not been committed yet (checked
2026-07-13: absent). It is a **blocking pre-D1 beat** (roadmap Part VI).
Treat "bucket-A" as a concept, not a consumable artifact, until it lands.

**Safety architecture — non-negotiable carry-overs.** These four are not
"nice patterns to imitate"; they are the mechanisms `CLAUDE.md`'s Hardware
safety rules (PROTECTED section, Kaya-approval-only) are enforced by, and
they must be re-hosted whole, never reimplemented from a description:

| Component | File | What it does |
|---|---|---|
| State machine | `controller/state_machine.py` | `AppState` enum + validated transitions (`DISCONNECTED → CONNECTED → HOMED → CONFIGURED → READY → RUNNING → {PAUSED, FINISHED, ERROR, ABORTED}`); any state can reset to `DISCONNECTED`; thread-safe (`RLock`); invalid transitions raise |
| Danger gate | `controller/danger_gate.py` | `DangerAction`/`DangerGate` protocol — async request/confirm workflow; `QtDangerGate` is worker→GUI, **fail-closed on timeout** |
| Arm envelope | `controller/arm_envelope.py` | `ArmedEnvelope` (frozen: bias channels, HV min/max, ramp shape, per-axis motion bounds) + `ArmedEnvelopeGate` — auto-approves only actions provably inside the envelope, denies outside/after expiry, fail-closed, no side effects |
| Sequencer | `controller/sequencer.py` | `SequenceRunner` — pure state, no Qt, no threads, no device access; **fail-closed by construction**: first non-`"finished"` outcome, first preflight veto, or a raising preflight hook HALTS the queue (culprit FAILED, rest SKIPPED) — no continue-on-failure option exists in v1 |

`docs/SAFETY_CONSTITUTION.md` (roadmap S0, extracting the constitution text
out of `CLAUDE.md` into its own document) and `docs/SAFETY_NORMATIVE_TESTS.md`
(roadmap S2, the 1:1 port-disposition manifest for every safety-normative
test) are **PENDING** — neither file exists in the repo yet (checked
2026-07-13). Until S0/S2 land, the authoritative safety text is `CLAUDE.md`'s
"Hardware safety rules" section, and the authoritative test set is whatever
currently matches a `fault|danger|trip|kill|arm` grep of `tests/` — informal,
not yet a named artifact.

---

## 2. What is TCT-specific (rebuild, don't lift)

The layer above the five packages is TCT's presentation, not a portable
contract:

- **`gui/*.py`** — 39 files, ~25,500 lines (measured) of `QWidget` panel
  bodies (`bias_panel.py`, `motor_panel.py`, `scope_panel.py`,
  `planner_panel.py`, `analysis_panel.py`, `sequencer_panel.py`, …). These
  encode TCT's specific instrument layout and workflow, not a general
  measurement-platform UI.
- **`tct_gui.py`** — the composition root (`TCTMainWindow`, 1,834 lines):
  instantiates every panel and device, wires signals to
  `gui/scan_coordinator.ScanCoordinator`, owns the `StateMachine`. Only
  `main.py` may import it (`test_only_main_py_imports_tct_gui`).
- **The classic ribbon/tab shell** — `gui/detachable_tabs.DetachableTabWidget`
  with a fixed 12-tab layout: 11 built in `tct_gui.py`'s `_build_central`
  plus the Scan Sequencer tab inserted post-hoc (tct_gui.py:639) (§3a).

LabControl should treat these as reference implementation, not lift
candidates: they show *how* TCT wires panels to the backend contract, but a
platform with a different device roster needs its own shell.

---

## 3. Three known structural obstacles

Each of these is a real, checked-in constraint today, not a hypothetical.
Each maps to a named roadmap stage that removes it — none of the three is
fixed yet.

| # | Obstacle | Evidence | Roadmap stage |
|---|---|---|---|
| 1 | **Hardcoded 12-tab composition.** The main window's tab set is 11 literal `self._tabs.addTab(...)` calls plus one post-hoc insert, not data. | `tct_gui.py`, method `_build_central` (defined at line 265), tab calls at lines 405–418: Motor Stage, Reference Monitor, Camera, Oscilloscope, Laser/Trigger, Scan Viewer, Scan Planner, Bias Supply, Calibration, Monitor, Analysis — plus **Scan Sequencer inserted at tct_gui.py:639** (12 total) | D4 — config-driven composition replacing the fixed layout; default config must be byte-identical to today |
| 2 | **Fixed 6-device dict.** `DeviceManager` exposes exactly six named devices as a Python dict literal, not a registry. | `controller/device_manager.py`, method `named_devices()` (line 582): `{"Motor Stage": self.motor, "Oscilloscope": self.scope, "Bias Supply": self.bias_supply, "Intensity Monitor": self.intensity_monitor, "Camera": self.camera, "Waveform Generator": self.waveform_generator}` | D1a/D1b — `DeviceManager.capability_registry()` layered **over** this dict (direct access remains; additive, not a replacement) |
| 3 | **Missing scope/camera/wavegen ABCs.** Four device families have an abstract interface (`motor_base.py`, `bias_supply_base.py`, `slow_control_base.py`, `intensity_base.py`); three do not — their concrete drivers inherit `devices.base.BaseDevice` directly. | `devices/oscilloscope.py:104 class Oscilloscope(BaseDevice)`, `devices/waveform_generator.py:253 class WaveformGenerator(BaseDevice)`, `devices/camera_blackfly.py:158 class BlackflyCamera(BaseDevice)` — no `oscilloscope_base.py`/`camera_base.py`/`waveform_generator_base.py` exists (checked 2026-07-13) | D2 — extract the three missing ABCs from the concrete drivers, zero signature changes per the roadmap's "Declaration" rule |

---

## 4. Patterns to adopt

### 4a. The e4control adapter pattern (device onboarding template)

`devices/bias_supply_e4control.py` is the reference for onboarding a new
instrument family without touching the app's own interfaces: it wraps an
**optional, not-vendored** local checkout of the third-party `e4control`
library, adds the first existing root
(`TCT_app/vendor/e4control` or `reference/e4control`) to `sys.path` only if
present, imports the target device class dynamically, and exposes it through
the existing `BiasSupplyBase` interface (`devices/bias_supply_base.py`) — the
rest of the app never knows the backend changed. Zero ABC changes were
needed to add it.

**License condition — resolved 2026-07-13 (Kaya-directed).** The seed
repository itself is now **MIT-licensed** (`LICENSE`, repo root; Copyright
(c) 2026 Kaya Yesilyurt, Kaya-directed 2026-07-13). This license covers
TCT's *own* source — including the adapter file below — and does **not**,
and cannot, relicense e4control's own code, which TCT never vendors into
Git or the seed (intentionally `.gitignore`d local reference material; see
`docs/REFERENCE_MATERIAL.md`). Upstream e4control carries **no formal
license file**; its authors gave Kaya an **informal confirmation of
open-source intent** (2026-07-13) — informal confirmation, not a written
grant. Concretely, for LabControl:

- The **adapter pattern** (optional-checkout discovery, dynamic import,
  ABC-wrapping shape) ships in the public seed under the seed's own MIT
  license: `devices/bias_supply_e4control.py` is 100% TCT-authored and
  never contains copied e4control source text — the same manual/datasheet-
  sourced discipline Hardware safety rule 4 already requires for every
  instrument command applies here too.
- **This does not make e4control's own code MIT-licensed or
  redistributable.** At connect time, when a local e4control checkout is
  present, the adapter *dynamically imports and calls e4control's actual
  classes/methods* (`_import_e4control_device`, `self._dev.setVoltage()`,
  `rampVoltage()`, `setOutput()`, …) — a real runtime dependency on
  third-party code, not a reimplementation of it. That third-party code is
  never vendored, embedded, or shipped with the seed.
- **Recommendation to third parties (including LabControl): treat e4control
  upstream itself as unlicensed** — an informal author confirmation is not
  a redistribution right — and use **our MIT-licensed adapter pattern**,
  sourcing e4control independently (if real e4control-backed hardware is
  needed) under whatever terms its authors actually offer.
- If a formal upstream license or written grant appears later, re-evaluate
  whether closer integration makes sense — that is Kaya's call, not a
  default outcome of this entry.

### 4b. The QML seam

Three pieces, all present in the repo today (not PENDING):

- **Bridge:** `gui/qml_shell.py` — `_TabShelfAdapter` (line 88), `_ShellBridge`
  (line 155), `build_qml_chrome()` (line 352). This is the composition-root
  glue between the classic `QWidget` tree and QML chrome (`TCT_SHELL=classic|
  qml`, classic default).
- **Theme singleton:** `gui/qml_theme.py` — `class Theme(QObject)` (line 172),
  exposed to QML as a context property; the single source of design tokens
  for both shells.
- **Viewmodels + the read/command boundary:** `gui/scope_viewmodel.py`
  (`ScopeViewModel`) and `gui/run_state_viewmodel.py` (`RunStateViewModel`,
  225 lines) are plain `QObject`s fed by the GUI thread — **they hold no
  reference to the controller or state machine**, so QML has no path from a
  bound property to a hardware command. Full design + the safety-critical
  boundary test plan: `docs/design/run_state_facade.md` (§1 "the single most
  important property of the design: the view-model holds no reference to
  `ScanController` or `StateMachine`. It is fed values; it cannot reach
  anything.") This is the shape LabControl's own read-only telemetry surface
  should copy: fed, not wired.

### 4c. The capability model — **PENDING (roadmap stage D1, not built)**

No `TCT_app/capabilities/` directory exists yet (checked 2026-07-13). This
subsection summarizes the *design* in `docs/ROADMAP_MASTERPLAN.md` Part I —
none of it should be treated as an existing API.

- **Shape:** frozen dataclasses, no Qt, AST-layer-checked — `CapabilityDescriptor`
  (capability_id, device_id, label, `SafetyClass`), specialized into
  `SweepableParameter`, `ReadableChannel`, `WaveformSource`, `FrameSource`,
  `TriggerSource`, `HVSource`, `Motion3D`. Descriptors are pure data
  (JSON-safe, no callables); a separate `CapabilityBinding` (not the
  descriptor) carries setter/getter.
- **Binding lifecycle (Codex BLOCKER-1):** `CapabilityBinding` is a staged
  lifecycle — `reserve → prepare → apply → wait_settled → verify_or_skip →
  abort` — with per-transport reservation/locking, so acquisition can never
  start against an unapplied setpoint on a shared VISA/serial line.
- **Per-operation safety routing (⚑ awaiting Kaya re-ratification):**
  `SafetyClass` stays a coarse display tier, but gate *routing* is declared
  per operation (`read`/`set`/`arm`/`start`/`stop`) via explicit route names
  (`danger_gate`, `motion_envelope`, `hv_lock`, `emission_interlock`) — a
  capability can be motion-adjacent *and* emitting at once.
- **Registry:** `DeviceManager.capability_registry()` sits **over** the
  existing 6-device dict (§3), additive — direct access remains.
- **Read-back law:** never silently label a commanded value as measured;
  read-back is per-capability best-effort (not a blanket mid-scan query —
  that would interleave with acquisition traffic on shared transports, the
  exact TBS1052C `CURVE?`-wedge class this bench has already hit), with an
  explicit `readback_skipped` flag when not attempted.
- **Safety-inversion guard (Völundr, carries into §6):** the planned
  `PreflightHook` contract must carry the written invariant that a hook may
  compute locally and veto, but must **never** block on or require
  remote/platform I/O to permit.

---

## 5. Data contract

Full current contract: `TCT_app/SCAN_DATA_FORMAT.md` (Samantha-owned,
verified against `data/hdf5_writer.py`/`controller/scan_controller.py`/
`data/save_options.py`). Summary for LabControl:

- One HDF5 file per run: `runs/run_NNNNN/waveforms.h5`, index =
  `max(existing)+1`.
- Root attrs: `start_time`, `stop_time`, `outcome`
  (`finished`|`aborted`|`error`|`unknown`), `abort_reason`. **`outcome` is
  already the run-completeness signal today** — written exactly once by
  `HDF5Writer.close()` from `ScanController._end_run`, present on every run
  regardless of which optional groups are enabled. `unknown` is the honest
  default for "writer closed without ever recording an outcome" (crash/kill),
  not a silent alias for `finished`.
- Mandatory groups: `waveforms/` (raw traces), `points/` (x/y/z). Optional,
  independently toggleable: `timestamp`, `analysis` (derived, recomputable),
  `bias` (measured, NOT recomputable), `slow_control` (measured, NOT
  recomputable), `camera_frame`, `run_metadata`.
- **Point ordering is serpentine (boustrophedon)**, not row-major — see
  §5's "TCT will NEVER guarantee" item below.

### Völundr contract addenda checklist (from Part III of the roadmap)

Status legend: **DONE** = true in the repo today; **PENDING(stage)** = design
decided, not yet built.

- [ ] Literal `swept/{capability_id}` attr names + dtypes — **PENDING(DA1)**,
      depends on the capability model (§4c) landing first.
- [ ] NaN-honesty invariant declared as a blanket-or-explicit-exceptions
      scope (which datasets promise NaN-for-missing vs which don't) —
      **PENDING(DA1)**. Today's partial precedent: `analysis/*` datasets
      already use `NaN` for missing values, and `camera/frame_pos_mm` uses
      `(NaN, NaN, NaN)` (never a dropped or fake-zero row) per
      `SCAN_DATA_FORMAT.md` — DA1's job is to make this a stated invariant
      across all of `swept/`, not just these two precedents.
- [x] `outcome`/`abort_reason` frozen as the run-completeness signal —
      **DONE today** (see above); DA1/DA2 extend, do not introduce, this.
- [ ] `capability_id` strings get the same permanence promise as
      `scan_plan.py`'s `Axis` enum aliases (saved routines never break) plus
      a deprecation process — **PENDING**, depends on the capability model.
- [ ] Run UUID (globally unique, distinct from the sequential `run_NNNNN`
      directory name — not a safe dedup key across machines) + per-station
      identity (hostname/app-instance UUID + TCT git-hash) + per-device
      identity (IDN, firmware, driver version, simulated flag) —
      **PENDING(DA2)**.
- **Explicit "TCT will NEVER guarantee" list** (state these to LabControl
  plainly, do not let them become implicit assumptions):
  - **No live/low-latency data feed.** The bulk data channel is
    post-run-only, triggered after `HDF5Writer.close()` (see §6); nothing in
    this seed promises a streaming/low-latency waveform path.
  - **No network RPC control surface in the base app.** Hardware I/O is only
    ever issued from the local Qt runtime; there is no existing accepted
    RPC entry point into `ScanController`/`DeviceManager` (see §6 — this is
    a *proposal*, not shipped behavior).
  - **Serpentine point ordering is permanent.** `points/x_mm`/`points/y_mm`
    row order is boustrophedon by design (minimizes stage travel); it will
    not become row-major. Reconstruct 2-D maps from the coordinate columns
    (`analysis/scan_grid.points_to_grid`), never `reshape(ny, nx)`.

**Declared post-seed** (per Völundr's own phase-gating, not seed blockers):
run-manifest publication, audit-event emission, an interlock-policy-*query*
hook. The seed is meant to be consumable as a file-based post-hoc connector
without any of these three.

---

## 6. Remote / multi-user — draft for review

**Nothing in this section is shipped.** `docs/design/remote_control_plan.md`
is explicitly "Status: Proposal / design only. Nothing here is implemented
yet" (its own header, 2026-07-04). No `remote:` config key, no WebSocket
service, no remote-client role exists in the repo today. This paragraph is
the roadmap-mandated written ruling on remote/multi-user before seed
ratification (Part III: "this paragraph must be WRITTEN and reviewed BEFORE
seed ratification, not promised").

**Affirmative statement (what the seed will guarantee if remote/multi-user
ships in any form):**

1. **Safety is local.** Every interlock (`DangerGate`, `ArmedEnvelope`, the
   `StateMachine`'s transition guards, the sequencer's fail-closed halt)
   evaluates entirely on the machine that owns the hardware. None of them
   may depend on a platform, network link, or remote peer being reachable —
   loss of connectivity degrades to "no remote input," never to "no safety
   check."
2. **A platform/remote policy may only ADD restrictions, never grant a
   required permit.** If LabControl (or any remote peer) expresses a policy
   at all, it can forbid an action the local machine would otherwise allow;
   it can never be the thing that satisfies a safety rule's "explicit user
   confirmation" requirement on the local machine's behalf.
3. **Real-time control stays in the desktop Qt runtime.** The scan loop,
   motor moves, HV ramps, and trigger/acquire timing execute only inside the
   local `ScanController`/`DeviceManager`/Qt thread model that exists today.
   No roadmap item moves any of this execution off-machine.
4. **LabControl's role is visibility, reproducibility, and audit** — telemetry
   consumption and post-run data, not a second execution path.

**⚑ Flagged contradiction — do not paper over.** Read against principle (2),
`docs/design/remote_control_plan.md` §5.1.3 is not fully consistent as
currently written. It proposes two policy modes for dangerous remote
actions:

- **Strict (its stated default):** consistent with (2) — a *local* operator
  must pre-arm a time-boxed "remote-armed" window before any remote
  dangerous-action request is even considered; the remote can only act
  within a scope a human at the lab machine already granted in advance.
- **Trusted-operator:** explicitly states "the remote node itself is
  treated as the confirming operator" for actions including stage motion
  and scan-start (HV-enable is carved out as always local-only, but motion
  and scan-start are not). This has the remote peer itself *satisfying*
  CLAUDE.md safety rule 2's "explicit user confirmation" for a dangerous
  action, with no local human in the loop at request time — which is a
  remote actor **granting** a required permit, not merely being *forbidden*
  a wider one. That is the shape principle (2) rules out.

This is a proposal document, never implemented, so nothing shipped currently
violates the invariant. But if remote/multi-user work resumes past Phase 0,
"Trusted-operator" mode as written needs either (a) reframing so the local
pre-arm step (Strict mode's design) is the *only* mechanism that ever
substitutes for local confirmation, or (b) an explicit Kaya/Mary
re-ratification of the trade-off before it is built. **This document does
not resolve that question — it surfaces it**, so it cannot be silently
designed around in a later, unreviewed beat.

**Seed-layer ruling:** given the above, remote/multi-user support is **OUT
of `v1.0-platform-seed`**. LabControl should assume TCT ships zero
network-control code at seed-tag time and build its own reachability-
independent policy layer per (1)–(4), rather than depending on
`remote_control_plan.md`'s Trusted-operator mode ever landing as designed.

---

## 7. Portability matrix

From `docs/ROADMAP_MASTERPLAN.md`'s Portability section. The stack is
reported ~95% portable by construction (PySide6/pyqtgraph/numpy/h5py/
pyserial/pyvisa-py are all cross-platform; offscreen tests are Linux-native;
`gui/backdrop.py` already no-ops cleanly off-Windows-11). Not yet
independently re-verified by Samantha on Linux — treat the "~95%" figure as
the roadmap's estimate, not a measured one.

| Platform | Role | Status |
|---|---|---|
| **Ubuntu** | Reference distro | **PENDING(PORT1/PORT2)** — sim-mode gate not yet built: needs `run.sh`/`setup.sh` twins, an explicit Xvfb/EGL/Mesa graphics recipe, a `QSG_INFO=1` log parser that rejects silent software-rendering fallback, and pixel-smoke captures for both QML and pyqtgraph/GL. Real hardware (FLIR Spinnaker Ubuntu SDK, DRS4, pyvisa-py, udev/dialout rules) is PORT2, separate from the sim-mode gate. |
| **AlmaLinux** | Sim/container path | **PENDING(PORT2)** — sim-mode + container path only; real-camera support is conditional on FLIR RPMs cooperating, checked in PORT2, not promised. |
| **Windows** | Current dev/bench platform | Full support today (this is where the app is built and run). Windows-only, degrading gracefully elsewhere: DWM acrylic/mica glass backdrop, the on-screen capture tool, and PowerShell bench tooling (`agent_env`/`daedalus` scripts). |

**Gate:** PORT1 (re-rated M/L effort per the roadmap's Codex-R1 correction,
with the graphics-recipe artifacts above as part of the *standing* gate, not
one-off setup) is required to pass **before** the seed tag is cut — the seed
is meant to ship cross-platform from day 0, not retrofitted later.

---

## 8. Versioning

This document is itself versioned, independent of the TCT app's own
version/git history: **0.1.0-draft** as of this write. Suggested rule
(mirrors the `docs/ARCHITECTURE.md` changelog convention already in use):

- **Patch** (`0.1.x`) — wording/clarification fixes, no change to any
  guarantee or checklist item.
- **Minor** (`0.x.0`) — additive: a new checklist item, a PENDING item
  flips to DONE with its evidence, a new obstacle/pattern section.
- **Major** (`x.0.0`) — any change that removes or weakens a guarantee
  in §5 or §6 (e.g. the "TCT will NEVER guarantee" list, the safety-is-
  local paragraph) — these require the same Kaya-approval-only path as
  a `docs/DECISIONS.md` RATIFIED entry, never a routine doc edit.
- The `-draft` suffix drops only at the point this document accompanies the
  actual `v1.0-platform-seed` git tag; until then every version is a draft
  regardless of its numeric value.
- A deprecation of any promised item gets a dated line here (not silently
  removed), naming the version it changed in — same discipline as the
  `capability_id`/enum-alias permanence promise this document asks the
  capability model to keep (§4c, §5).

---

## Changelog

- 2026-07-13 — Samantha: initial draft (workstream S1). All eight sections
  written; §6 flags a contradiction in `docs/design/remote_control_plan.md`
  §5.1.3 "Trusted-operator" mode against the drafted safety-is-local
  invariant. Not yet reviewed by Mamoru (file/symbol claims) or Kaya
  (ratification).
- 2026-07-13 — Samantha: §4a license paragraph resolved (Kaya-directed).
  Repo root `LICENSE` added (MIT, Copyright (c) 2026 Kaya Yesilyurt). Seed's
  own MIT license covers TCT-authored code only; e4control's own code is
  never relicensed, vendored, or copied — the adapter dynamically imports
  and calls e4control's actual classes at connect time (verified against
  `devices/bias_supply_e4control.py`), which is a runtime dependency, not a
  reimplementation. Upstream e4control still has no formal license; authors'
  informal open-source-intent confirmation to Kaya stands. §6 (remote/
  trusted-operator) untouched — separate pending ruling.
