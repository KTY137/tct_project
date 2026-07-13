# TCT Nordstern-Masterplan — Seed einer modularen LabControl-Plattform

> Kaya's north star: a modular LabControl platform ("GUIfy E4Control",
> composable cockpit, Planner/Sequencer as measurement heart) — built
> later as a separate project. THIS repo: polish to seed maturity, run
> the full capability+UI evolution here, hand off a tagged seed.
> Designed by a Fable architecture agent from 5 codebase explorations +
> web prior-art; refined by two crew bounces (Prometheus, Mary).

## Kaya's fixed decisions (AskUserQuestion, binding)

- Design freeze after glass tuning + panel rollout; then measurement pivot.
- Workstream C (planner enrichment) = proposal-only this round.
- Workstream B (metrology) = ergebnisoffen precision budget.
- Fable tiers: architecture agents on Fable; judgment-beats upgrade
  Opus→Fable; per-dispatch Fable at Adam's discretion; Mary stays Opus.
  (CLAUDE.md governance commit = first beat after approval.)

## Phase 0 (BLOCKING): bench red at HEAD 9d2596a

`test_qml_shell_survives_repeated_production_soft_reload` hangs into the
90 s timeout inside `gui/style.py:2601 apply_theme` during
`_reload_config → _build_central` (bench stack captured; green at
1e5850c). Suspects: today's backdrop/repaint changes (9cdc970
window.update, 7cb2bd3 centralWidget translucency + QSurfaceFormat +
opacity pin) × the 4-cycle soft reload. Beat: Noah (Opus, concurrency),
root-cause with the bench stack, fix, 20x local reload loop, ONE bench
re-gate → push. Immediate Mary. **No push until green.**

---

# PART I — The capability spine (Fable architect design)

New GUI-free package `TCT_app/capabilities/` — **additive beside the
existing ABCs, never replacing them**. Prior art: QCoDeS Parameter
shape, yaq trait composition, ophyd plan/device split + describe()-
into-data, PyMeasure generated forms.

```python
# capabilities/model.py (frozen dataclasses; no Qt; AST-layer-checked)
# NOTE: ILLUSTRATIVE sketch — binding-level concerns (setter/getter,
# staged lifecycle) live on CapabilityBinding per F1 + Codex BLOCKER-1,
# NOT on the pure-data descriptor as shown shorthand below.
class SafetyClass(Enum): BENIGN; MOTION; HV; EMITTING
@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str   # "bias.voltage", "stage.x", "wavegen.duty_cycle"
    device_id: str; label: str; safety_class: SafetyClass
    metadata: Mapping[str, Any]
class SweepableParameter(CapabilityDescriptor):
    unit; limits; resolution; setter; getter; settle_s
class ReadableChannel(...); WaveformSource(...); FrameSource(...)
class TriggerSource(...); HVSource(SweepableParameter)  # NO kill() here —
    # kill stays on the single existing safety path
class Motion3D(CapabilityDescriptor): axes: tuple[SweepableParameter,...]
```

- **Declaration:** drivers need not change — `capabilities/adapters.py`
  wraps the 4 existing ABCs + the concrete wavegen/scope/camera. New
  drivers may implement `describe_capabilities()` directly. Zero ABC
  signature changes.
- **Registry:** `DeviceManager.capability_registry()` (QCoDeS Station
  analogue) over the existing 6-device dict; direct access remains,
  tests opt in.
- **Planner derivation:** `Axis` enum (scan_plan.py:37) frozen as v1
  grammar; new `AxisSpec` resolved enum→spec via static table first
  (behavior-identical), then registry-backed NEW axis_ids. Enum string
  values = permanent plan-JSON aliases (saved routines never break).
  Validator takes limits + danger-marking from safety_class —
  equality-parallel with the old tables for one stage before swap.
  **Pilot = the wavegen gap:** params['wavegen'] is validated+compiled
  but dropped at scan_controller.py:1413 — becomes the first
  capability-executed feature (duty/freq/amplitude sweepables, EMITTING).
- **Generic UI:** CapabilityViewModel + generated form (unit spinbox
  clamped to limits, danger styling from safety_class) for long-tail
  devices. HARD LAW: generation never produces safety controls;
  safety_class >= MOTION routes through the existing DangerGate/envelope.
- **HDF5 provenance:** `swept/{capability_id}` per-point datasets with
  unit/safety_class attrs (ophyd describe() shape); fixed columns stay;
  SCAN_DATA_FORMAT version bump; descriptor **snapshots** serialize into
  scan_config.
- **Codex-R1 corrections (folded in 2026-07-13 night; two items ⚑
  flagged for Kaya re-ratification):**
  - **Binding lifecycle (Codex BLOCKER-1):** `CapabilityBinding` is not
    a bare setter — it carries the staged lifecycle
    `reserve → prepare → apply → wait_settled → verify_or_skip → abort`
    with per-transport reservation/locking, so acquisition can never
    start against an un-applied setpoint on a shared VISA/serial line.
    D1 exit includes a simulated delayed-apply test proving the
    executor waits for `wait_settled` before acquiring.
  - **⚑ Safety routing per OPERATION, not one ladder (Codex MAJOR-1):**
    `SafetyClass` stays the coarse display tier, but gate ROUTING is
    declared per operation (`read`/`set`/`arm`/`start`/`stop`) via
    explicit route names (`danger_gate`, `motion_envelope`, `hv_lock`,
    `emission_interlock`) — a capability can be motion-adjacent AND
    emitting; mixed-hazard capabilities get tests before any generated
    UI. CAPABILITY_MODEL.md defines this; Mary's taxonomy review covers
    it. (Touches the Völundr total-ordering decision → Kaya nod needed.)
  - **P0' as equality oracle (Codex MAJOR-2):** P0' supports the
    PER-POINT duty variation (the grammar already attaches wavegen
    params per ACQUIRE action) and records a per-point command trace;
    P1's equality gate compares command order + point index + final
    `swept/` rows — never just a run-level setting.
  - **Timing + atomic completion (Codex MAJOR-3):** DA1/DA2 include a
    minimal per-point timing/status contract (command-issued, settled,
    acquisition start/end, monotonic clock) and an ATOMIC completion
    marker written only after HDF5 close — a crash can never leave a
    complete-looking file.
  - **Dual-shell settings (Codex MAJOR-4):** shell-specific QSettings
    keys are NAMESPACED; shared keys frozen in app_settings; the
    U-stage gate adds a dirty-settings round-trip (classic writes → qml
    boots → qml writes → classic boots).
  - **Safety event authority under QML (Codex BLOCKER-2):** every
    U-stage merge gate includes: QML-focused key injection reaches
    emergency shortcuts, mouse-hit tests at STOP/Abort coordinates,
    z-order assertions; emergency shortcuts are owned by the top-level
    QWidget path, never the QML scene.
  - **PORT1 re-rated M/L (Codex MAJOR-5):** explicit Linux graphics
    recipe (Xvfb/EGL/Mesa), QSG_INFO=1 log parser rejecting silent
    software fallback, pixel-smoke captures for QML AND pyqtgraph/GL,
    separate AlmaLinux sim-only verdict.
  - **Effort honesty (Codex MINOR-1):** D1 split into D1a
    (contract/model) + D1b (adapters/registry); D4 rated L unless a
    prior spike proves the panel lifecycle needs no special cases.
  - **⚑ Seed cleanliness (Codex MINOR-2):** the e4control adapter
    PATTERN ships in the public seed only if an upstream license/grant
    exists by tag time; otherwise it moves to a TCT-private appendix —
    Kaya's informal authorization covers tct_app, not third-party
    redistribution. (Kaya nod needed.)
- **Bounce-1 corrections (Prometheus, folded in):**
  - **Data/binding split (F1):** descriptors are PURE DATA (JSON-safe by
    construction, no callables, no auto-hash traps); the registry returns
    a separate `CapabilityBinding` carrying setter/getter. `snapshot()`
    on the descriptor is what DA1 writes — never the binding.
  - **Settle precedence + read-back (F2, amended by Loki bench-truth):**
    plan-explicit settle beats descriptor default (matches
    scan_plan.py:416-425 precedence); read-back is **declared-per-
    capability BEST-EFFORT, not a blanket law** — a mandatory mid-scan
    query per point would interleave with acquisition traffic on shared
    VISA/serial transports, the exact TBS1052C CURVE?-wedge class this
    bench has already produced. The LAW is: **never silently label
    commanded values as measured** — `swept/` carries a per-point
    `readback` column where the capability declares it safe, else a
    `readback_skipped` flag. Discrete-valued params and per-set max-step
    are declared v2 extensions in CAPABILITY_MODEL.md.
  - **Equality-parallel gate (F3):** compares FULL issue sets (severity,
    path, message-class) incl. WARNINGs over the saved-routine corpus +
    generated plans; divergences enter a Mary-ratified allowlist before
    swap; exactly ONE serializer (the old one) writes plan JSON during
    the parallel stage.
- **Non-breakage laws:** additive only · enum aliases permanent ·
  equality-parallel swaps · **bucket-A suite (47 files ~15k LOC) green
  UNMODIFIED is a gate on every stage below.**

# PART II — Staged roadmap per domain

Gates: [Mary] safety review · [Kaya] ratification · [Bench] full suite
on sophonone · [A-green] bucket-A unmodified green.

**Phase 0.5 — DEFINE TRUNK (Mary BLOCKER-1, blocking before any
roadmap stage):** "trunk" is currently undefined — `origin/main` is a
stale pre-restructure state (2026-07-04, no TCT_app/, 6 tests); the
entire live codebase lives only on `design/cockpit-v5`.
**Recommendation: after Phase 0 is bench-green, merge
design/cockpit-v5 → main (bench-green evidence attached to the merge),
main becomes THE trunk; design/cockpit-v5 retires.** All
"trunk"/[A-green] references resolve to main@post-merge. The
polish-freeze TAG (Mary MAJOR: referenced but never created) is then
cut explicitly: `polish-freeze` on trunk@<design-freeze SHA>, recorded
in the ledger — it is the U-track entry gate (U0 asserts the tag
resolves) and the seed baseline ancestor.

**Gate enforcement (Loki CRITICAL-2 + Mary BLOCKER-2 — gates must be
failable, with named artifacts):**
- **Pre-D1 beat (blocking):** commit `docs/test_bucket_map.md` — the
  explicit A/B/C/D file lists, **the exact run command**
  (`QT_QPA_PLATFORM=offscreen pytest <A-files> -q`), the target branch,
  and where the green tail is recorded (ledger) — plus a diff-check
  script (`git diff --stat <base> -- <bucket-A files>` must be EMPTY)
  wired into `.claude/beat_status.ps1` and Mamoru standups. [A-green]
  becomes machine-checkable BEFORE it is first invoked.
- **Routine corpus:** freeze ≥5 real saved plans as
  `tests/fixtures/routine_corpus/` — **"corpus exists and predates P2"
  is a P2-ENTRY artifact**; the replay script asserts corpus size
  (vacuous pass forbidden) and the byte-diff result lands in the ledger.
- **[Mary]/[Kaya] sign-offs get durable evidence** (Mary RISK): each
  appends to the ledger: gate-id, commit SHA reviewed, one-line
  verdict, date. Mamoru audits presence at phase gates. Beat briefs
  anchor by SYMBOL, not line number (lines rot).
- **U0 pass criterion defined:** `QSG_RHI_BACKEND=opengl` set; probe
  logs `GL_RENDERER == <expected bench GPU>`; zero software-fallback
  lines; artifact = probe log linked in the ledger. Same threshold
  re-asserted at every per-stage [Bench].
- **[Bench] is ONE shared serial resource** (one-full-suite-at-a-time,
  ratified): trunk gates, U-stage merge-backs, and PORT1 queue on the
  same sophonone — expected gate latency is real and the plan's
  "parallel tracks" are parallel in authorship, serial at the gates.

**Kaya throughput (Loki MAJOR — the ratifier does not scale):**
- **WIP limit: max 2 gate-bearing tracks concurrent** (opening state:
  D+DA on trunk; U-branch does not start until D1 has landed).
- [Kaya] gates are marked **personal** (constitution-class: S0, S2,
  seed tag, M2 go/no-go, U-track supersede, U3 checkpoint) vs
  **delegable-to-Adam with post-hoc report** (routine doc reviews,
  D4 schema details, B memo acceptance). Delegated decisions are
  logged in DECISIONS.md with attribution, as practiced today.

**Devices:** **D1a contract/model (S/M) → D1b adapters/registry (M)**
(split per Codex MINOR-1 — lifecycle/persistence/tests are the hard
part, not the model code; exit [A-green][Mary taxonomy][Kaya
CAPABILITY_MODEL.md]) → D2 missing ABCs
Scope/Camera/Wavegen extracted from concrete drivers (M) → D3 e4control
expansion via the proven one-adapter pattern (L; K2614/HMP4040/JULABO…;
[Bench] probe per device, sim≠real check; **license status — resolved
FOR TCT-INTERNAL USE ONLY (Kaya, 2026-07-13: informal confirmation from
the E4 authors — open-source intent, no formal license text).
Vendoring/recoding into tct_app is Kaya-authorized. For the PUBLIC SEED
this is NOT resolved (Codex R2: forced, not optional) — exactly two
sound options by tag time: an upstream license/written grant exists, or
the adapter pattern moves to a TCT-private appendix. Kaya chooses WHICH,
not whether. Default implementation path stays
reimplementation-with-e4control-as-prior-art (safety rule 4 requires
manual-sourced commands anyway). We never push upstream or touch their
repo.**) — **D3 is a PARALLEL, post-seed-
eligible branch, NOT on the seed critical path (Loki MAJOR): the
D-chain is D1 → D2 → D4b → D4 → seed; D3 devices join whenever their
bench probes pass** → **D4b generic capability panel proven on
ONE long-tail device (wavegen) — the PyMeasure-shape form; without it
the "composable cockpit" seed claim is hollow (bounce-1 F5)** → D4
config-driven composition replacing the fixed 6-dict; default config
byte-identical to today (**L per Codex MINOR-1, unless a prior spike
proves the panel lifecycle needs no special cases**; [Kaya] schema).

**Connection:** C1 transport inventory + injection (S) → C2 connection
registry with probe/identify + simulated transport (M; [Bench]) → C3
reconnect/health policy (S).

**Planner:** **P0' direct wavegen-apply fix FIRST (Loki MAJOR: Kaya's
one concrete ask must not be held hostage by the spine) — a day-sized
direct patch applying params['wavegen'] PER-POINT in the executor (the
grammar attaches wavegen params per ACQUIRE action; a run-level-only
shortcut is forbidden per Codex MAJOR-2), recording a per-point command
trace as the honesty stopgap; [Bench][Mary]** →
P1 re-lands the same behavior AS the capability pilot (S; gated on
behavior-equality against P0') — ordered AFTER (or bundled WITH) DA1's
swept/-writer slice (bounce-1 F4): the pilot's proof-of-done includes
the RECORDED sweep in the HDF5; a pilot that sweeps unrecorded would
commit the exact provenance sin the spine ends → P2 Axis→AxisSpec equality-parallel (M; [A-green]) → P3
registry-backed axes + plan-JSON version (M; **saved-routine corpus
replay byte-identical** [Kaya]) → **P4a generic PreflightHook mechanism
+ sim tests (S, UNGATED, seed candidate) → P4b camera-correction hook
(gated on Metrology M2 go, feeds M3) [Mary]** (bounce-1 F8 split).

**Analysis:** A1 provenance-keyed analysis registry (S/M, depends DA1)
→ A2 pluggable pipeline (mostly LabControl-side post-seed).

**Metrology:** M1 feasibility workstream B (unchanged, below) → M2
measured numbers → explicit closed-loop **go/no-go [Kaya]** → M3
camera-corrected positioning via PreflightHook (L; [Mary][Bench]).

**Data:** DA1 SCAN_DATA_FORMAT v+1 (swept/ datasets; old-file
round-trip tests; [Kaya]) → DA2 provenance completeness audit (S).

**Safety (re-hosted, never migrated):** S0 SAFETY_CONSTITUTION.md
extraction ([Kaya][Mary]) · S1 safety_class taxonomy review (blocks D1
exit, [Mary]) · S2 SAFETY_NORMATIVE_TESTS.md — the 1:1-port manifest
**with an explicit port-disposition column per test (byte-identical
bucket-A / GUI-half-rehost / QML-walker)**: test_arm_envelope
(bucket-A, byte-identical), bias+motor danger-gate suites
(gate-declines-refuse; NOT-AUS/STOP/output-off live under locks),
kill-switch escalation ladder (+ stays-escalated), arm_latch (abort
never latched), trip_detection + classic_loop_safety (failsafe
HV-at-zero), sequencer manual_pause rejection (3 entry points),
ui_monkey DENIAL RULESET (portable ~20%; QTest harness retires,
rewritten as QML-item walker), **PLUS the six Mary-bounce additions:
test_fault_injection + test_fault_injection_legacy (mid-scan fail-safe
— the direct enforcement of safety rule 5: worker exits, HV→0, laser/
wavegen off, HDF5 closed, pre-fault data preserved),
test_slow_control_policy (WARN→safe-hold pause / ALARM→full fail-safe
abort), test_bias_api_guard (output_on→enable_output footgun
invariant), test_bias_trip_visibility (latched trip wins over
compliance; GUI half = genuine 1:1-port item), test_reconnect_liveness
(stale-green health), test_bias_polarity (HV polarity gating).** S2
exit: Mary ratifies the manifest against a fault/danger/trip/kill/arm
grep of tests/ so nothing normative is missed. ([Mary][Kaya])

**UI — branch `ui-qml-migration`, cut at the polish-freeze tag; option
(a) throughout.** **⚠ SUPERSEDES DECISIONS.md 2026-07-13 "QML-hybrid
boundary" (which rejected per-panel migration): Kaya's approval of THIS
plan is the explicit re-ratification of that entry (Loki CRITICAL-1;
governance rule honored — a RATIFIED entry changes only with Kaya's
per-change approval, which plan approval constitutes). The safety
sub-clauses of that entry survive unchanged: no safety-critical control
is ever reimplemented in QML; no live shader glass; islands stay.** (web-verified: Qt 6.7/6.8 WindowContainer hosts
windows, not widget trees; airspace + QQuickWidget non-interop
documented → the ratified QWidget-tree + QQuickWidget-chrome
architecture stands; revisit only at Qt 6.10+ LTS with a bench spike):
- U0 branch cut + RHI/GL pin probe on the bench GPU (S).
- U1 **viewmodel-first test reclaim (C→B) BEFORE porting** (L):
  test_planner_panel (1.7k), test_scan_map_view + test_scan_viewer_panel
  (1.2k), test_sequencer_panel — rewritten against new viewmodels per
  the run_state_facade boundary (VM holds no controller ref, no
  start/stop callables). **Bounce-1 ordering note: the PLANNER slice of
  U1 consumes AxisSpec (lands after trunk-P2), because planner_panel.py
  hard-codes Axis members in ~15 places — baking the enum into a new
  viewmodel would churn twice when P3 axes flow trunk→branch. Other U1
  slices are P-track-independent.**
- U2 ScanViewer hero slice (M; proves panel-VM-island pattern; [Kaya]
  pattern sign-off).
- U3 easy panels: Calibration, RefMonitor, Monitor, Laser (M).
- U4 medium: Camera, Bias (**kill switch re-parented, never
  re-implemented**; [Mary]), Analysis (L).
- U5 hard: Scope, Motor (GL island + STOP re-host), Planner drag&drop
  tree + **ArmLatch faithful port** (own [Mary] + test_arm_latch 1:1) (XL).
- U6 shell swap: QML chrome default, registry-driven composition
  replaces tct_gui.py:401-418; monkey QML-walker runs the denial
  ruleset ([Bench][Mary]).
- **NEVER migrates:** QtDangerGate modal, the 9 pyqtgraph/GL islands,
  camera raster QLabel, STOP/ALL-OFF/Abort QWidget instances, any
  second implementation of a safety control.
- Standing gate every U-stage: [A-green] + S2 normative suites green +
  [Bench] before each merge-back **+ (Mary MAJOR — the qml path must be
  exercised BEFORE U6): the migrated panel boots under TCT_SHELL=qml
  offscreen AND its viewmodel-contract suite runs green under qml — a
  named per-panel smoke; a flagged panel that is green-on-classic but
  dead-under-qml can never merge.** Continue/pause checkpoint with Kaya
  after U3; U4/U5 are explicitly DESCOPE-ABLE post-seed (the seed needs
  only U0–U2; the two-shell window bound is credible precisely because
  of this).

**Portability (NEW, Kaya requirement: Ubuntu + AlmaLinux):** the stack
is ~95% portable by construction (PySide6/pyqtgraph/numpy/h5py/pyserial/
pyvisa-py all cross-platform; offscreen tests are Linux-native; the
OpenGL RHI pin is the Linux default; QSettings abstracts storage;
backdrop.py already no-ops cleanly off-Win11 → v6 design degrades to
tokens without compositor glass). Real work is vendor SDKs + plumbing:
- **PORT1 (M/L, re-rated per Codex MAJOR-5): Linux sim-mode gate** —
  `run.sh`/`setup.sh` twins, bucket-A + offscreen GUI suite green in an
  Ubuntu container/VM **with an explicit graphics-stack recipe
  (Xvfb/EGL/Mesa), a QSG_INFO=1 log parser that REJECTS silent software
  fallback, and pixel-smoke captures for QML and pyqtgraph/GL** — these
  artifacts are part of the standing gate, not one-off setup. Enters
  the roadmap BEFORE the seed tag — the seed ships cross-platform.
- **PORT2 (M): hardware-on-Ubuntu validation** — FLIR Spinnaker Ubuntu
  SDK + Linux PySpin wheel, DRS4 (PSI, Linux-friendly), pyvisa-py,
  udev/dialout rules; Ubuntu = reference distro. AlmaLinux: sim-mode +
  container path documented; real-camera support only if FLIR RPMs
  cooperate (checked in PORT2, not promised).
- Windows-only remains (documented, degrading): DWM glass, the onscreen
  capture tool, bench PowerShell tooling.
- Seed implication: PLATFORM_SEED.md carries the portability matrix +
  PORT1 gate; LabControl starts cross-platform on day 0.

**Cross-domain sequencing:** D1 → {P1, DA1, S1} → P2 → P3 → D4 →
PORT1 → seed tag. UI branch parallel from U0 (needs only the polish
freeze). M-track independent until P4/M3.

# PART III — Branch / repo / seed strategy

- **Trunk** stays shippable; capability track (D/P/DA/S/C stages) lands
  ON TRUNK (additive). UI work on long-lived `ui-qml-migration`; fixes
  flow trunk→branch (weekly); branch→trunk merge-back per completed
  U-stage behind `TCT_SHELL=classic|qml` (classic default until U6);
  classic shell deleted one release AFTER QML becomes default.
- **Seed hand-off (amended per bounce-1 F5/F7 + bounce-4 Völundr):** when
  **D4+D4b+P3+P4a+DA1+DA2+S0+S2+C2+PORT1** on trunk → tag
  **`v1.0-platform-seed`** + `PLATFORM_SEED.md` (capability model +
  registry, layer contract, SAFETY_CONSTITUTION, normative-test
  manifest, SCAN_DATA_FORMAT contract, QML hybrid pattern docs,
  e4control adapter PATTERN only (no code — unlicensed upstream),
  test-bucket map, portability matrix, **and one paragraph ruling
  remote/multi-user in or out of the seed layer contract, citing
  docs/design/remote_control_plan.md — **this paragraph must be WRITTEN
  and reviewed BEFORE seed ratification, not promised** (Völundr: the
  unwritten paragraph is exactly where a safety inversion could be
  drafted unnoticed)**). DA2 explicitly delivers per-device identity
  (IDN, firmware, driver version, simulated flag) PLUS per-STATION
  identity (hostname/app-instance UUID + TCT git-hash) PLUS a
  **globally-unique run UUID** distinct from the sequential run_NNNNN
  dir name (Völundr: not a safe dedup key across machines).
- **Völundr contract addenda for PLATFORM_SEED.md** (his 14-item
  contract-notes list is the authoritative checklist; highlights):
  literal attr names/dtypes for swept/ metadata; NaN-honesty declared
  as blanket-or-explicit-exceptions invariant; outcome/abort_reason
  frozen as the run-completeness signal; capability_id strings get the
  same permanence promise as enum aliases + a deprecation process;
  explicit "TCT will NEVER guarantee" list (no live data, no network
  RPC control, serpentine ordering permanent); PLATFORM_SEED.md itself
  semver'd. Declared POST-seed (LabControl-contract work, not seed
  blockers, per Völundr's own phase-gating): run-manifest publication,
  audit-event emission, interlock-policy-QUERY hook — the seed is
  consumable as a file-based post-hoc connector without them.
- **Safety-inversion guards (Völundr):** CAPABILITY_MODEL.md defines an
  explicit total ordering for safety_class (compared with >= today,
  values unspecified — tighten before any policy surface exists), and
  P4a's PreflightHook contract carries the written invariant: **a hook
  may compute locally and veto, but must NEVER block on or require
  remote/platform I/O to permit** — safety stays local, platform may
  only forbid.
  LabControl initializes from the tag; TCT continues as first tenant.
  UI migration need NOT be complete for the seed — U0–U2 suffice.

# PART IV — Risk register (top 8, each with catching gate)

1. RHI/GL collision → pin QSG_RHI_BACKEND=opengl; islands per option (a)
   — caught by U0 probe + per-stage [Bench].
2. C-bucket churn (~13.7k LOC) → U1 reclaims high-value third into
   contract tests FIRST — caught by A-green gate + behavior-equal review.
3. Capability over-abstraction → pilot on the real wavegen gap first;
   rule "no descriptor field without a live consumer" — caught by [Kaya]
   D1 exit + P2 equality-parallel.
4. e4control license/quality (GPL-family contamination of the seed) →
   license audit before seed tag; adapter isolation — caught by
   PLATFORM_SEED license audit + D3 probes.
5. Two-shell maintenance drag → window bounded U1–U6, per-stage
   merge-backs, trunk UI freeze — caught by weekly sync + [Kaya]
   checkpoint.
6. Grammar migration breaks saved routines → permanent enum aliases +
   versioned schema — caught by P3 corpus-replay-byte-identical gate.
7. QML pattern debt → patterns proven (Theme/_ShellBridge/
   _TabShelfAdapter/run_state_facade); every panel PR cites the pattern
   doc — caught by U2 sign-off + per-panel review.
8. Scope creep vs lab uptime → trunk always shippable; M2 go/no-go;
   S/M-sliced capability stages — caught by [Bench] gates + Mamoru
   standups.

# PART V — Near-term workstreams (run before/alongside the roadmap)

**Workstream B — metrology feasibility** (M1): Prometheus external
research (CR-10-class mechanics: belt backlash/microstep truth under
load/thermal drift; reticle options + prices; prior art hobby-stage
metrology) → Jonathan memo `docs/research/metrology_feasibility.md`
(µm budget best/expected/worst as f(M); mechanics × optics × algorithm;
Guizar-Sicairos ~0.01 px upgrade note) + bench protocol as
BENCH_CHECKLIST §12 (step 0: measure relay magnification M; then
repeatability N-cycles, backlash staircase, 30-min drift — existing
code only: repeatability.py, calibrate_affine, metrology_report.py).
Facts base: M unknown (px_per_mm ≈ 170.6·M); X/Y 12.5 µm microstep /
200 µm full-step detent; zero measured bench numbers in-repo; paper
target only — traceable ~2 µm needs a chrome-on-glass reticle.

**Workstream C — planner enrichment PROPOSAL** (feeds P-track): Abel
(Fable per judgment rule) writes `docs/design/planner_routines_v2.md`:
the inert-wavegen headline; candidate axes (duty cycle = Kaya's ask,
freq/amplitude, scope hw averaging, camera exposure, time/stability
loop) each with safety/validator/data implications + S/M/L effort;
routine example gallery as `routines/*.yaml` via the existing Save/Load
path (no new UI for v1). No implementation this round.

**Workstream S-seed:** S1 PLATFORM_SEED.md draft early (Samantha, from
explorer evidence; Mamoru verifies every file:line claim — prose-about-
code gets the confabulation treatment); S3 salvage test_state_fuzz from
the experimental branch (bucket-A, zero Qt, found a real
start-while-PAUSED bug; anchors the A-green gate) — Abel, bench-gated.

# PART VI — First 5 concrete beats after approval

0. (First: the two Codex-Sol bounces per the finalization protocol.)
1. Phase 0 bench-red fix (Noah Opus) → re-gate → push (blocking).
2. Governance commit: Fable-tier rules into CLAUDE.md. **(Loki: the
   old "salvage test_state_fuzz" beat is STALE — the file already
   exists at HEAD 9d2596a; replaced by a small parity check that the
   experimental-branch variant contains nothing extra.)**
3. **Gate-enforcement beat (pre-D1, Loki CRITICAL-2):**
   `docs/test_buckets.md` + bucket-A diff-check script wired into
   beat_status/Mamoru + freeze `tests/fixtures/routine_corpus/` (≥5
   real plans).
4. **P0' direct wavegen-apply fix** ([Bench][Mary]) — Kaya's duty-cycle
   ramp works THIS week; P1 re-lands it as the capability pilot later,
   behavior-equality-gated.
5. CAPABILITY_MODEL.md + SAFETY_NORMATIVE_TESTS.md drafts → [Mary] →
   [Kaya]; then capabilities/model.py (D1a) and adapters/registry (D1b)
   as SEPARATE beats (Codex MINOR-1 split).
Parallel: B1 Prometheus research + C1 Abel proposal + S1 seed doc.

# Verification

- Phase 0: bench re-gate green at new HEAD, then push (origin rule).
- Every roadmap stage: its named exit gate ([A-green]/[Mary]/[Kaya]/
  [Bench]) — no stage merges without its gate evidence in the ledger.
- Docs deliverables (B memo, C proposal, seed doc, model docs): Kaya
  review + Mamoru file:line verification pass.
- Bench protocol (B3): verified by execution at the bench with Kaya;
  HTML metrology reports are the evidence artifacts.
- The plan itself: multi-bounced before submission — exact per-round
  status in the ledger below, nothing claimed beyond it (Loki MINOR-7:
  this document obeys session-hygiene rule 4 too).

# Bounce protocol & findings

Internal rounds (honest ledger):
- Bounce 1 — Prometheus (Fable): DONE, INTEGRATED — 8 findings (4
  HOLEs): descriptor/binding split, settle/read-back contract,
  full-issue-set equality gate, P1-after-DA1, D4b + C2/P4a/PORT1 into
  the seed gate, e4control license handling (RESOLVED by Kaya),
  remote/IDN paragraph, P4a/P4b split, U1-after-P2, U4/U5 descope.
- Bounce 2 — Mary (Opus, gates/verification): DONE, INTEGRATED —
  verdict "gates-structurally-weak" → structural fixes applied:
  2 BLOCKERs (trunk undefined/origin-main stale → Phase 0.5 defines
  trunk via cockpit-v5→main merge; bucket map = named artifact with
  exact command before first [A-green]), 4 MAJORs (state_fuzz
  branch-dependence resolves with trunk; polish-freeze tag beat
  created explicitly; S2 manifest +6 missing normative tests incl.
  fault_injection; per-U-stage qml-boot smoke gate), 3 RISKs (U0 pass
  criterion; corpus-predates-P2 artifact; [Mary]/[Kaya] durable
  evidence lines), 1 NIT (symbol-anchoring). All folded in.
- Bounce 3 — Loki (NorthStar persona, Fable): DONE, INTEGRATED —
  2 CRITICAL (U-track supersede header; failable gates: bucket
  manifest + routine corpus), 4 MAJOR (Kaya WIP limit + gate
  delegability; P0' un-hostages the duty-cycle fix; read-back demoted
  to best-effort per TBS1052C wedge truth; D3 off the seed critical
  path), 2 MINOR (this ledger's honesty; stale state_fuzz beat +
  bench-as-serial-resource). Verdict: revise → revisions applied.
- Bounce 4 — Völundr (NorthStar persona, Sonnet): DONE, INTEGRATED —
  seed gate +DA2/station-identity/run-UUID; remote paragraph written-
  before-ratification; PreflightHook non-blocking-on-remote invariant;
  safety_class total ordering; 14-item contract checklist; manifest/
  audit/policy-query declared post-seed. Verdict: withhold sign-off
  until the three named items are in — all three are in.
- Bounce 5 — Codex R1 (external lane; NOTE: lane could not pin
  "Codex 5.6 Sol", ran with the available Codex model): DONE,
  INTEGRATED (2026-07-13 night) — 2 BLOCKER (CapabilityBinding staged
  lifecycle + transport reservation; QML safety EVENT-AUTHORITY gate),
  5 MAJOR (per-operation safety routing ⚑Kaya; P0' per-point oracle;
  per-point timing + atomic completion marker; dual-shell QSettings
  namespacing + round-trip; PORT1 re-rated M/L with graphics recipe),
  2 MINOR (D1a/D1b split + D4→L; seed cleanliness for the e4control
  pattern ⚑Kaya). Explicit holds: trunk/gate repair and the metrology
  stream confirmed sound. Full review:
  docs/design/codex_masterplan_review_r1.md. The two ⚑ items await
  Kaya's nod (they touch his prior decisions); everything else is
  design-hardening consistent with plan intent, integrated under the
  autonomy mandate.
- Bounce 6 — Codex R2 (delta review): DONE, APPLIED — verdict "not
  ready as integrated; one text cleanup pass"; all 5 reconciliations
  made (illustrative-sketch note on the model code block; P0' wording
  now per-point command trace, run-level-only forbidden; PORT1 labeled
  M/L everywhere with graphics artifacts in the standing gate; D1a/D1b
  split + D4=L in Devices AND Part VI; e4control "resolved" scoped to
  TCT-internal use only). R2's reframing ADOPTED: both ⚑ items are
  FORCED safety/cleanliness corrections — Kaya ratifies the SHAPE
  (taxonomy compatibility with Völundr's ordering; upstream grant vs
  private appendix), not the whether. Review:
  docs/design/codex_masterplan_review_r2.md.
  **FINALIZATION PROTOCOL COMPLETE (2026-07-13 night) — execution
  begins per the plan sequence: Phase 0 → push → Part-V/VI wave.**

**Finalization protocol (Kaya directive): after Kaya approves this
plan, TWO Codex-lane bounces run as the FIRST execution steps** (queue-
file tasks per lane protocol; advisory-only, no code edits; model
request "Codex 5.6 Sol" passed to the lane — flagged if the CLI cannot
pin it): Codex round 1 reviews the full plan adversarially (fresh
non-Claude perspective); findings integrated; Codex round 2 reviews the
integrated delta. Material changes from either round go back to Kaya
for re-ratification before any roadmap beat starts. Only then: Phase 0
fix → first beats.
