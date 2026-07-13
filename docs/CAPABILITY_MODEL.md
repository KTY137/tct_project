# TCT Capability Model

| | |
|---|---|
| **Version** | v0.1-draft |
| **Date** | 2026-07-13 |
| **Status** | awaiting Mary review → Kaya ratification (D1 gate) |
| **Owner** | Paul (driver contract) — plumbing halves (validator/config wiring) are Abel's |
| **Normative for** | roadmap stage D1a (`capabilities/model.py`) and D1b (`capabilities/adapters.py`, registry) |
| **Inputs (binding)** | `docs/ROADMAP_MASTERPLAN.md` Part I incl. bounce corrections F1/F2/F3, Codex BLOCKER-1 / MAJOR-1, and the Völundr contract addenda in Part III |

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, **MAY**, and
**NEVER** are to be interpreted as in RFC 2119. Statements labelled **LAW** are
constitution-class: they may only change with Kaya's explicit per-change
approval. Items flagged **⚑** are open questions reserved for Kaya (§14).

References in this document are **symbol-anchored** (file + symbol). Line
numbers rot; symbols are checkable. Every symbol named here exists at the time
of writing and was verified against the working tree.

---

## 1. Purpose and scope

This document specifies the **capability spine**: a GUI-free, hardware-free
data model (`TCT_app/capabilities/`) through which the planner, validator,
executor, provenance writer, and (later) generated UI can discover and drive
instrument parameters **without new per-device special cases** — additive
beside the existing device ABCs, never replacing them.

It is written to be sufficient: D1a's `capabilities/model.py` MUST be
implementable from this document without further design decisions. Where a
decision is deliberately deferred, this document says so explicitly and names
the stage that owns it.

Out of scope here (owned elsewhere):

- The `swept/` writer implementation and the SCAN_DATA_FORMAT version bump —
  **DA1** (this document fixes the names/dtypes in §10 so the two contracts
  cannot diverge; after DA1 lands, `TCT_app/SCAN_DATA_FORMAT.md` is the
  contract of record for the on-disk shape and wins on conflict).
- Per-point timing/status columns and the atomic completion marker — **DA1/DA2**
  (Codex MAJOR-3). §6 defines the lifecycle *events* those columns will
  timestamp; it does not define the columns.
- The `Axis` → `AxisSpec` migration — **P2/P3** (this document fixes the
  `capability_id` grammar and permanence promise those stages consume).
- The generated capability panel — **D4b** (this document fixes the HARD LAW
  it must obey, §7.4).

## 2. Layering laws

1. `capabilities/model.py` **MUST** import only the standard library
   (`dataclasses`, `enum`, `typing`, …). No Qt, no numpy, no `devices/`,
   no `controller/`. This makes it AST-layer-checkable in the style of
   `tests/test_layer_contracts.py::test_devices_import_nothing_above`.
2. `capabilities/adapters.py` **MAY** import `devices/*` (it wraps drivers) and
   `capabilities/model.py`. It **MUST NOT** import `controller/` or `gui/`.
3. The registry accessor lives on `controller/device_manager.py::DeviceManager`
   (§11); `controller/` may import `capabilities/`, never the reverse.
4. **LAW — no hardware I/O at import or construction.** Building a descriptor,
   a binding, or the registry performs **zero** instrument I/O. Descriptors are
   derived from constructor-time driver attributes and config (which the
   existing constructors hold without I/O — see
   `devices/base.py::BaseDevice.__init__`), never from a live query.
   `describe_capabilities()` (§11.3) is subject to the same law.

## 3. Descriptor vs. binding (F1 data/binding split)

The model separates *what a capability is* from *how to drive it*:

- **`CapabilityDescriptor`** (and subtypes, §5) — **pure data**: frozen
  dataclasses, JSON-safe by construction (§4), **no callables, no device
  references**. Descriptors are what the planner reads, what the validator
  checks against, and what provenance serialises.
- **`CapabilityBinding`** (§6) — the runtime handle carrying setter/getter
  behaviour and the staged lifecycle. Bindings hold device references and are
  **never** serialised.

**LAW —** `CapabilityDescriptor.snapshot()` is what data-provenance writes
(into `scan_config` / the `swept/` attrs, §10) — **never** the binding, and
never anything derived from a binding.

Rule of economy (roadmap risk 3): **no descriptor field without a live
consumer.** Every field in §5 names its consumer; adding a field without one
is a review-blocking defect.

## 4. JSON-safety, immutability, and snapshots

- All descriptor types are `@dataclass(frozen=True)`.
- Field values are restricted to: `str`, `int`, `float`, `bool`, `None`,
  tuples of these, and string-keyed mappings of these (nested likewise).
  `metadata` mappings MUST be stored immutably (e.g. converted to
  `types.MappingProxyType` or a sorted tuple of pairs in `__post_init__`) so a
  frozen descriptor cannot be mutated through its bag.
- `snapshot() -> dict` returns a plain dict that `json.dumps` serialises with
  **no custom encoder**. It MUST include:
  - every descriptor field,
  - `"type"`: the concrete descriptor class name (e.g. `"SweepableParameter"`),
  - `"model_version"`: the capability-model version string (starts `"1"`).
- Enums serialise as member **names** (`"HV"`, `"BEST_EFFORT"`) — never
  ordinal values, because the ordinals are deliberately unspecified (§7.1).

## 5. The type family

The class tree (all in `capabilities/model.py`; concrete field lists are
normative — names, types, and defaults as written):

```python
class SafetyClass(Enum):            # §7 — total ordering, values unspecified
    BENIGN; MOTION; HV; EMITTING

class Operation(Enum):              # §7.2 — the per-operation routing axis
    READ; SET; ARM; START; STOP

class ReadbackPolicy(Enum):         # §9 — deliberately has NO "MANDATORY"
    NONE; BEST_EFFORT

@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str              # §5.1 grammar; permanent (§5.2)
    device_id: str                  # DeviceManager short key, §5.3
    label: str                      # human-readable, for UI/planner pickers
    safety_class: SafetyClass
    metadata: Mapping[str, Any]     # JSON-safe bag; NEVER policy input (LAW §7.5)

@dataclass(frozen=True)
class SweepableParameter(CapabilityDescriptor):
    unit: str                       # display/provenance unit, e.g. "V", "mm", "%"
    limits: tuple[float, float] | None   # inclusive (lo, hi); None = no static limit
    resolution: float | None        # smallest meaningful increment; None = unknown
    settle_s: float = 0.0           # descriptor DEFAULT settle; plan wins (§8)
    readback: ReadbackPolicy = ReadbackPolicy.NONE   # §9

@dataclass(frozen=True)
class ReadableChannel(CapabilityDescriptor):
    unit: str                       # scalar read-only quantity

@dataclass(frozen=True)
class WaveformSource(CapabilityDescriptor):
    channels: tuple[str, ...]       # channel labels, e.g. ("ref_ch1", "dut_ch2")

@dataclass(frozen=True)
class FrameSource(CapabilityDescriptor):
    pass                            # 2-D frame producer; shape is runtime info

@dataclass(frozen=True)
class TriggerSource(CapabilityDescriptor):
    pass                            # armable output; ARM/STOP semantics §7.3

@dataclass(frozen=True)
class HVSource(SweepableParameter):
    polarity: str | None = None     # 'p'/'n' as normalised by
                                    # devices/bias_supply_base.py::normalize_polarity;
                                    # None = unknown/fixed.  Descriptive only (§5.4).

@dataclass(frozen=True)
class Motion3D(CapabilityDescriptor):
    axes: tuple[SweepableParameter, ...]   # one per stage axis (x, y, z)
```

Field-by-field live consumers (rule of economy, §3):

| Field | Consumer that exists or is gate-scheduled |
|---|---|
| `capability_id` | registry key (§11), `swept/` group name (§10), P3 `AxisSpec` resolution |
| `device_id` | registry → `DeviceManager` device lookup; `swept/` attr (§10) |
| `label` | D4b generated form; planner axis picker |
| `safety_class` | validator danger-marking (P2 equality-parallel); D4b danger styling; `swept/` attr |
| `metadata` | free-form provenance only (LAW §7.5 forbids policy use) |
| `unit` | D4b spinbox suffix; `swept/` attr |
| `limits` | D4b spinbox clamps; P2 validator range checks (equality-parallel with `controller/scan_plan_validator.py::PlanLimits`) |
| `resolution` | D4b spinbox step default |
| `settle_s` | executor settle default (§8) |
| `readback` | binding `verify_or_skip` behaviour + `swept/` readback datasets (§9, §10) |
| `channels` | DA1 `swept/`-adjacent provenance; scope adapter surface |
| `polarity` | provenance snapshot; multi-bias UI display |
| `axes` | motion-envelope construction; planner stage axes (P3) |

### 5.1 `capability_id` grammar

- Lowercase ASCII segments matching `[a-z][a-z0-9_]*`, joined by single dots;
  at least two segments. Regex: `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$`.
- First segment = **domain** (v1 vocabulary: `stage`, `bias`, `wavegen`,
  `scope`, `camera`, `intensity`, `slow_control`); last segment = parameter.
- IDs carry **no unit suffix** — the unit lives in the `unit` field. Hence
  `wavegen.duty_cycle` (unit `"%"`), even though the plan-grammar key is
  `duty_cycle_pct` (`controller/scan_plan_validator.py::_KNOWN_WAVEGEN_KEYS`).
  The adapter owns that mapping; the two vocabularies are linked by a static
  table, never by string munging.
- Seed vocabulary (v1): `stage.x`, `stage.y`, `stage.z`, `bias.voltage`,
  `wavegen.frequency`, `wavegen.pulse_width`, `wavegen.duty_cycle`,
  `wavegen.amplitude`, `wavegen.offset`, `wavegen.output` (TriggerSource),
  `scope.waveform` (WaveformSource), `camera.frame` (FrameSource),
  `intensity.reading` (ReadableChannel), `slow_control.<channel_name>`
  (ReadableChannel, one per configured channel).
- ⚑ Multi-channel HV naming is an open Kaya question (§14.2).

### 5.2 Permanence promise and deprecation

**LAW —** a published `capability_id` string receives the **same permanence
promise as the plan-JSON enum aliases** (`controller/scan_plan.py::Axis`
values, frozen per the roadmap's non-breakage laws): it is never renamed, never
reused with a different meaning, and never removed. Saved plans and old HDF5
files stay readable forever.

Deprecation process (the only permitted evolution):

1. The registry keeps a permanent alias table `old_id → new_id`; **both**
   resolve, forever.
2. Resolving a deprecated id emits a validator **WARNING** (never an ERROR —
   old plans keep running).
3. New descriptors/plans MUST use the new id; docs list deprecated ids in a
   dedicated section of this file.
4. Deletion of an id or alias is not a deprecation step; it does not exist.

### 5.3 `device_id` vocabulary

`device_id` uses the `DeviceManager` **short keys** — the keys of the device
dict in `controller/device_manager.py::DeviceManager.connect_all` and the
values of `DeviceManager._DISPLAY_TO_SHORT`: `motor`, `scope`, `bias_supply`,
`intensity_monitor`, `camera`, `waveform_generator` (plus
`slow_control/<name>` for slow-control channels, matching the `connect_all`
result keys). These strings inherit the §5.2 permanence promise the moment a
descriptor publishes them.

### 5.4 Type-specific rules

- **`HVSource` has NO kill.** **LAW —** neither `HVSource` nor its binding
  exposes a kill/NOT-AUS/emergency-off surface. Kill stays on the single
  existing safety path (the STOP/ALL-OFF QWidget instances and the driver
  fail-safe paths); the capability layer never grows a second one. Polarity
  switching (`devices/bias_supply_base.py::BiasSupplyBase.set_polarity`, a
  DANGEROUS relay action) is likewise **not** a capability in v1 — it stays a
  panel-only, gate-confirmed action; the descriptor's `polarity` field is
  descriptive only.
- **`Motion3D`** aggregates per-axis `SweepableParameter`s (`stage.x/y/z`,
  unit `"mm"`). Axis `limits` MUST be derived from
  `devices/motor_base.py::MotorStageBase.limits_user_frame()` — the user-frame
  envelope — **not** raw `self.limits`, and (per that method's docstring)
  MUST be re-derived whenever the frame can have changed (after home/zero).
  See §5.5.
- **`TriggerSource`** models an armable output (e.g.
  `devices/waveform_generator.py::WaveformGenerator.output_on` /
  `output_off`). Arming is an ARM operation (§7.3) and NEVER happens
  implicitly (no auto-arm on connect, on registry build, or on binding
  construction).
- **`WaveformSource` / `FrameSource` / `ReadableChannel`** are READ-operation
  producers; their bindings expose acquisition, not setting.

### 5.5 Descriptor freshness

Descriptors are immutable **value snapshots**. Because some source-of-truth
values move at runtime (the GRBL user-frame offset shifts
`limits_user_frame()` after home/zero), the registry re-derives descriptors on
each `descriptors()` / `get()` call (§11.2). Consumers MUST NOT cache
descriptors across home/zero/reconnect events. Provenance writes the
descriptor **in effect at run start** (its `snapshot()`), which is the honest
record of what the run was validated against.

The driver-internal runtime gates (`MotorStageBase.move_to`'s limit check,
`BiasSupplyBase.check_voltage_in_range`) remain **authoritative** regardless
of descriptor staleness — the capability layer adds pre-flight checks, it
never bypasses or weakens a driver gate.

## 6. `CapabilityBinding` — staged lifecycle

A binding is obtained from the registry (§11.2), holds a device reference, and
drives exactly one capability. Its lifecycle (Codex BLOCKER-1):

```
reserve → prepare → apply → wait_settled → verify_or_skip → abort
```

- **`reserve()`** — acquire the transport reservation (§6.1). Returns a
  context manager / token; the reservation is released when the token exits
  (normal completion after `verify_or_skip`, or the `abort` path). `reserve`
  MUST take a timeout and MUST NOT be held across user-interaction waits
  (a modal confirmation happens *before* reserve).
- **`prepare(value)`** — validate `value` against descriptor limits and the
  driver's runtime gates; pre-compute the command(s). MUST NOT perform
  state-changing instrument I/O (read-only queries are permitted). Raises on
  an out-of-range value — fail closed *before* anything is sent.
- **`apply(value)`** — issue the setting. For `HVSource` this MUST route
  through the shaped-ramp path
  (`devices/bias_supply_base.py::BiasSupplyBase.ramp_to` semantics — never a
  direct `set_voltage` jump; a ramp-to-zero never energises an idle channel,
  per that method's SAFETY docstring). For a `Motion3D` axis it routes
  through `MotorStageBase.move_to` (which re-checks limits and homing
  internally). `apply` entry is the "command-issued" event DA1's timing
  columns will timestamp.
- **`wait_settled(timeout_s)`** — block until the setpoint is physically
  settled: motion waits on the driver's readiness
  (`MotorStageBase.wait_until_ready` semantics), then dwells the **effective
  settle** (§8); non-motion capabilities dwell the effective settle. Return
  is the "settled" timing event. **LAW —** the executor MUST NOT begin an
  acquisition against this capability's point before `wait_settled` has
  returned (D1 exit includes the simulated delayed-apply test proving this).
  Timeout raises `devices.base.DeviceError`-class failure → executor
  fail-safe path (safety rule 5).
- **`verify_or_skip()`** — the best-effort read-back stage (§9). Returns a
  `VerifyResult` (status ∈ {`measured`, `skipped`, `failed`}, value:
  `float | None`). It never raises on a mere mismatch and never blocks the
  run in v1: it *records*; policy stays with the executor. A mismatch beyond
  a declared tolerance SHOULD log a WARNING.
- **`abort()`** — return the capability to a safe idle: motion → `stop()`;
  HV → the **existing** fail-safe pair (ramp to 0, output off) via the same
  driver methods every fail-safe path already uses; trigger outputs →
  `output_off`. `abort` MUST be callable from any stage, idempotent, and
  MUST NOT raise (it is the cleanup path). It introduces **no new safety
  path** — it delegates to the single existing one.

**LAW —** bindings NEVER auto-connect, auto-home, auto-enable HV, or restore a
previous setpoint. Constructing or reserving a binding changes no instrument
state.

### 6.1 Transport reservation

The reservation unit is the owning device's existing
`devices/base.py::BaseDevice.io_lock` (the re-entrant lock whose docstring
records the hazard: GUI pollers and the scan thread share one VISA/serial
session, and interleaved query/reply pairs garble each other — the bench-
observed TBS1052C `CURVE?`-wedge class).

- **MUST** reserve via that same lock — never a parallel second lock over the
  same transport (two locks = the interleave hazard returns).
- Multi-capability atomic sets (e.g. frequency+duty on one wavegen) reserve
  once per device; cross-device grouped reservations MUST acquire in sorted
  `device_id` order (deadlock avoidance) and MUST use timeouts.
- Capabilities that share one physical transport (e.g. `intensity.reading`
  reads a scope channel via
  `controller/device_manager.py` wiring of `ScopeChannelMonitor(scope=...)`)
  reserve the **underlying** device's lock; the adapter declares which device
  that is via `device_id`.

## 7. Safety model

### 7.1 `SafetyClass` — explicit total ordering

`SafetyClass` members: `BENIGN`, `MOTION`, `HV`, `EMITTING`, with the
**total ordering**

```
BENIGN < MOTION < HV < EMITTING
```

- Comparisons are made with `>=` (e.g. `safety_class >= SafetyClass.MOTION`).
  The enum MUST implement rich comparisons over a private rank
  (`functools.total_ordering` or explicit dunders).
- **The concrete rank values are UNSPECIFIED and not part of the contract**
  (Völundr): only the relative order is promised. They MUST be tightened
  (frozen and documented) before any policy surface — anything that persists
  or transmits a numeric class — exists. Serialisation uses member names
  (§4), which is what makes leaving the values loose safe today.
- The class is a **coarse display/floor tier**, not a complete hazard
  statement — that is exactly why routing is declared per operation (§7.2).
  The order does not claim EMITTING is more dangerous than HV in every
  context; it claims generated UI and validators may treat it as at-least-as
  gated.

### 7.2 Per-OPERATION gate routing

Operations: `READ`, `SET`, `ARM`, `START`, `STOP` (§5). Gate **route names**
(strings, part of the permanent vocabulary):

| Route name | Existing implementation it names |
|---|---|
| `danger_gate` | `controller/danger_gate.py::DangerGate` protocol (GUI: `gui/qt_danger_gate.py::QtDangerGate`), with `DangerAction` kinds `"hv_ramp"` / `"move"` / `"scan_start"` |
| `motion_envelope` | `devices/motor_base.py::SoftwareLimits.check` enforced in `MotorStageBase.move_to`, pre-flighted by `controller/scan_plan_validator.py::PlanLimits` from `limits_user_frame()` |
| `hv_lock` | `devices/bias_supply_base.py::BiasSupplyBase.check_voltage_in_range` + the validator's fail-closed `safety.require_hv_confirmation` check (`controller/scan_plan_validator.py::validate_plan`, check (f)) + `DangerAction("hv_ramp")` confirmation |
| `emission_interlock` | **RESERVED — no implementation exists (P3).** Until P3 lands, wavegen arming stays exactly where it is: inside `controller/scan_controller.py::ScanController._acquire_core` (output_on → acquire → output_off); `_apply_wavegen_settings` never touches output state. The reserved name MUST NOT be wired to anything before P3. |

Default class-floor routing (v1; the shape Kaya picks in §14.1 plugs in here):

| Class floor | `SET` | `ARM` / `START` | `READ` | `STOP` |
|---|---|---|---|---|
| `BENIGN` | — | — | — | — |
| `MOTION` | `motion_envelope` (+ `danger_gate` where the existing executor already confirms: first move / scan start) | `danger_gate` | — | — |
| `HV` | `hv_lock` + `danger_gate` | `danger_gate` | — | — |
| `EMITTING` | — (setters like duty/frequency are un-gated today, matching `_apply_wavegen_settings`) | `emission_interlock` (reserved; hard-coded path until P3) | — | — |

Normative rules regardless of shape:

- **LAW — `STOP` is never gated.** Stop/abort/disable operations MUST NOT
  require confirmation or any gate. Gating a stop is a safety inversion.
- `READ` is never gated but MUST respect transport reservation (§6.1).
- Routing may only **tighten** relative to the class floor (add gates), never
  loosen (remove a floor gate). Mixed-hazard capabilities (motion-adjacent
  AND emitting — Codex MAJOR-1) get dedicated tests before any generated UI
  renders them.

### 7.3 Class assignments (v1)

- `stage.x/y/z`, `Motion3D` → `MOTION`.
- `bias.voltage` (`HVSource`) → `HV`.
- `wavegen.*` setters and `wavegen.output` → `EMITTING` (the wavegen drives
  the laser trigger — see the EMITTING note in
  `ScanController._apply_wavegen_settings`'s docstring). The laser itself has
  no PC control (`devices/laser_manual.py::LaserManualMetadata` is
  metadata-only) — there is deliberately **no** `laser.*` capability in v1.
- `scope.waveform`, `camera.frame`, `intensity.reading`, `slow_control.*` →
  `BENIGN`.

### 7.4 HARD LAW — generated UI and safety controls

**Generated UI NEVER produces safety controls.** A generated form (D4b) may
render values, units, limits, and danger *styling*, but any operation on a
capability with `safety_class >= MOTION` routes through the **existing QWidget
gates** (`QtDangerGate` modal and the established envelope/lock paths). No
generated widget may fire a gated operation without the gate, and no generated
widget may implement a STOP/kill/ALL-OFF control — those remain the
hand-written QWidget instances on the single existing safety path.

### 7.5 LAW — `metadata` is never policy input

No safety decision, gate routing, limit, or validator behaviour may read
`CapabilityDescriptor.metadata`. It is an unvalidated provenance bag; policy
fields must be first-class typed fields with named consumers.

## 8. Settle precedence

The existing plan-side precedence is the contract, cited by symbol:
`controller/scan_plan.py::LeafMeta.settle_s` is resolved by
`controller/scan_plan.py::_child_meta` — the **nearest enclosing loop whose
`settle_s` is positive wins** (0.0 means "no settle"; the dataclass has no
unset sentinel), and an action's own params override loop context downstream
in the compiler (per the `LeafMeta` docstring).

Capability rule (F2):

```
effective_settle = plan_resolved_settle  if plan_resolved_settle > 0.0
                   else descriptor.settle_s
```

- **Plan-explicit settle beats the descriptor default.** The descriptor's
  `settle_s` is only a fallback for plans that set none.
- Known v1 wrinkle (documented, not silently resolved): because 0.0 doubles
  as the unset sentinel in the plan grammar, a plan **cannot** express
  "explicitly zero settle" for a capability whose descriptor default is
  positive. This is a grammar limitation inherited from
  `LoopBlock.settle_s`; if it needs fixing, that is a P2/`AxisSpec` change
  (an explicit null-vs-0 distinction), not a capability-model change.
- `wait_settled` (§6) consumes the effective settle; the executor passes the
  plan-resolved value in, so the binding never re-implements plan precedence.

## 9. Read-back contract (best-effort, never mandatory)

Bench truth first (F2, Loki-amended): a mandatory mid-scan query per point
would interleave with acquisition traffic on shared VISA/serial transports —
exactly the TBS1052C `CURVE?`-wedge class this bench has already produced, and
exactly what `BaseDevice.io_lock`'s docstring warns about. Therefore:

- Read-back is **declared per capability** via
  `SweepableParameter.readback: ReadbackPolicy`:
  - `NONE` — `verify_or_skip()` always returns `skipped`; no readback
    datasets are written (§10).
  - `BEST_EFFORT` — `verify_or_skip()` attempts one read-back inside the
    existing reservation; failure degrades to `failed`, never to a raise and
    never to a retry storm (reads MAY be retried only where the driver
    already proves the query idempotent-safe).
- **`ReadbackPolicy` deliberately has NO `MANDATORY` member.** Adding one is a
  constitution-class change requiring Kaya ratification — it would reintroduce
  the wedge class as a matter of policy.
- **LAW — never silently label commanded values as measured.** A commanded
  value MUST NOT be copied into any dataset, column, or attribute whose name
  implies measurement. The `wavegen_command_trace` run metadata written by
  `ScanController._flush_wavegen_trace` obeys this today (COMMANDED values,
  labelled as such); `swept/` (§10) carries the distinction structurally.
- The wavegen driver already models the honest pattern: `set_duty_cycle` /
  `set_pulse_width` store the instrument's *applied* value from a read-back
  query and warn on clamp — the capability layer standardises that pattern,
  it does not invent it.

## 10. HDF5 provenance — `swept/{capability_id}` (extends SCAN_DATA_FORMAT)

This section **extends** `TCT_app/SCAN_DATA_FORMAT.md` (it does not redefine
it): the fixed columns and groups documented there stay byte-identical; DA1
adds the `swept/` group and bumps the format version, folding this section
into that contract. Conventions below deliberately match the existing ones
("Scalar datasets are extensible (`maxshape=(None,)`, gzip, chunk 64)").

Layout — one HDF5 **group per swept capability**, named by its
`capability_id` (dots are legal in HDF5 link names; readers MUST NOT treat
the dot as a path separator):

```
/swept/bias.voltage/commanded          f8  (N,)
/swept/bias.voltage/readback           f8  (N,)   [BEST_EFFORT only]
/swept/bias.voltage/readback_skipped   u1  (N,)   [BEST_EFFORT only]
```

Literal dataset names and dtypes:

| Dataset | dtype | shape | Presence | Meaning |
|---|---|---|---|---|
| `commanded` | `f8` | `(N,)` | always (for a swept capability) | value commanded at each point; `NaN` where this capability was not set at that point (NaN-honesty: never zero-filled) |
| `readback` | `f8` | `(N,)` | only when `readback == BEST_EFFORT` | **measured** value; `NaN` where skipped or failed. MUST contain only measured values (LAW §9) |
| `readback_skipped` | `u1` | `(N,)` | only when `readback == BEST_EFFORT` | `0` = measured; `1` = skipped by policy/reservation hold; `2` = read attempted but failed/unparseable |

Rows are index-aligned with `/points` (row *i* ↔ `points/x_mm[i]` etc.),
extensible, gzip, chunk 64 — the established scalar-dataset shape. Runs that
write no `/points` rows (e.g. photo-only surveys) write no `swept/` group;
anything beyond that alignment rule is DA1's to design under its own [Kaya]
gate.

Literal **group attributes** on each `swept/{capability_id}` group (HDF5
string attrs unless noted):

| Attr | Type | Value |
|---|---|---|
| `capability_id` | str | the id (redundant with the group name, kept for self-description) |
| `device_id` | str | §5.3 short key |
| `unit` | str | descriptor `unit` |
| `safety_class` | str | enum member NAME (`"HV"`), never a number (§7.1) |
| `label` | str | descriptor `label` |
| `readback_policy` | str | `"NONE"` / `"BEST_EFFORT"` |
| `model_version` | str | capability-model version (§4) |

Additionally the full `descriptor.snapshot()` of every swept capability
serialises into the run's `scan_config` metadata (the `/run_info` group per
SCAN_DATA_FORMAT) — the descriptor, never the binding (LAW §3).

Until DA1 lands, the P0' honesty stopgap remains:
`ScanController._flush_wavegen_trace` writes `wavegen_command_trace`
(per-point COMMANDED values) into `/run_info`. P1's pilot proof-of-done
includes the RECORDED sweep in `swept/` (roadmap F4 ordering).

## 11. Adapter strategy and registry

### 11.1 Drivers need not change

**Zero ABC signature changes.** The four existing ABCs —
`devices/motor_base.py::MotorStageBase`,
`devices/bias_supply_base.py::BiasSupplyBase`,
`devices/slow_control_base.py::SlowControlChannel`,
`devices/intensity_base.py::IntensityMonitorBase` — and the concrete
non-ABC drivers (`devices/waveform_generator.py::WaveformGenerator`,
`devices/oscilloscope.py::Oscilloscope`,
`devices/camera_blackfly.py::BlackflyCamera`) are wrapped by
`capabilities/adapters.py`. Indicative adapter surface (D1b finalises; the
normative part is *which driver symbol each capability drives*, because those
are the proven, gated paths):

| Capability | Driver path it wraps |
|---|---|
| `stage.x/y/z` (via `Motion3D`) | `MotorStageBase.move_to` / `get_position` / `wait_until_ready` / `stop`; limits from `limits_user_frame()` |
| `bias.voltage` (`HVSource`) | `BiasSupplyBase.ramp_to` (shaped), `read()` → `BiasReading` for read-back; limits from `voltage_range_V` |
| `wavegen.frequency/pulse_width/duty_cycle/amplitude/offset` | `WaveformGenerator.set_frequency` / `set_pulse_width` / `set_duty_cycle` / `set_amplitude` / `set_offset` — the same setters `_apply_wavegen_settings` forwards today, in the same deterministic order (frequency first) |
| `wavegen.output` (`TriggerSource`) | `WaveformGenerator.output_on` / `output_off` (ARM path hard-coded until P3, §7.2) |
| `scope.waveform` (`WaveformSource`) | `Oscilloscope.acquire` / `read_channel` |
| `camera.frame` (`FrameSource`) | `BlackflyCamera.get_frame` / `get_frame_with_meta` |
| `intensity.reading` (`ReadableChannel`) | `IntensityMonitorBase.read` |
| `slow_control.<name>` (`ReadableChannel`) | `SlowControlChannel.read_with_status` |

New drivers MAY implement `describe_capabilities() -> tuple[CapabilityDescriptor, ...]`
directly (duck-typed; no new abstract method on `BaseDevice` — that would be
an ABC signature change). The registry prefers a driver's own
`describe_capabilities()` over the adapter table when present. It MUST obey
LAW §2.4 (no I/O).

### 11.2 Registry

`DeviceManager.capability_registry()` (new method, D1b — flagged as
contract+plumbing: the `DeviceManager` wiring half is Abel's) returns a
`CapabilityRegistry` built over the existing device attributes (`self.motor`,
`self.scope`, `self.bias_supply`, `self.camera`, `self.waveform_generator`,
`self.intensity_monitor`, `self.slow_control` channels) — the same instances,
not copies. API:

- `descriptors() -> tuple[CapabilityDescriptor, ...]` — re-derived per call
  (§5.5), stable ordering (sorted by `capability_id`).
- `get(capability_id) -> CapabilityDescriptor` — resolves deprecation aliases
  (§5.2); raises `KeyError` on unknown ids (fail closed).
- `binding(capability_id) -> CapabilityBinding` — constructs the runtime
  handle; performs no I/O.

**Direct access remains**: nothing existing migrates to the registry; panels,
scan controller, and tests keep using `DeviceManager` attributes; tests opt
in to the registry. The registry is additive discovery, not a mandatory
indirection.

### 11.3 Pilot

The first capability-executed feature is the wavegen (P1), re-landing the
now-shipped P0' behaviour (`ScanController._apply_wavegen_settings` +
`wavegen_command_trace`) behind the capability path, gated on behavior
equality against P0' — command order + point index + final `swept/` rows,
never just a run-level setting (Codex MAJOR-2). Note for reviewers: the
roadmap's Part I line "params['wavegen'] … dropped at scan_controller.py:1413"
described the pre-P0' state and is **stale at HEAD** — the executor forwards
per-point wavegen params today; P1's job is re-hosting, not fixing.

## 12. v2 extensions — declared, NOT designed

Reserved for a future model version; deliberately absent from v1 (each would
violate the no-field-without-consumer rule today):

- **Discrete-valued parameters** (enumerated choices, e.g. coupling,
  pixel format). v1 `SweepableParameter` is continuous-only.
- **Per-set max-step** (a per-transition delta clamp distinct from `limits`
  and from the HV ramp shaping the plan grammar already carries in
  `LoopBlock.ramp_step_V` / `ramp_delay_s`).

Declaring them here reserves the concepts so nobody wedges them into
`metadata` (which LAW §7.5 would forbid consuming anyway).

## 13. Non-breakage laws

1. **Additive only.** The capability spine adds modules; it modifies no ABC
   signature, no driver behaviour, no existing dataset or group.
2. **Enum aliases permanent.** `Axis` string values (`"stage_x"`,
   `"stage_y"`, `"stage_z"`, `"bias_V"`) are frozen plan-JSON grammar;
   `capability_id`s and `device_id`s inherit the same promise (§5.2, §5.3).
3. **Equality-parallel swaps (F3).** Any validator/planner behaviour moving
   onto capability data runs equality-parallel with the old tables for one
   stage: FULL issue sets compared (severity, path, message-class),
   WARNINGs included, over the saved-routine corpus plus generated plans;
   divergences enter a Mary-ratified allowlist before swap; exactly ONE
   serializer (the old one) writes plan JSON during the parallel stage.
4. **Bucket-A gate.** The bucket-A suite green UNMODIFIED gates every stage.
5. **No descriptor field without a live consumer** (§3, table in §5).

## 14. ⚑ Open questions for Kaya

1. **⚑ Per-operation routing SHAPE** (Codex MAJOR-1 — this is Kaya's
   personal gate; the options below are all compatible with Völundr's total
   ordering, which stays either way as the display/floor tier):
   - **(a) Class ladder only** — `safety_class` alone implies one gate set
     for all operations. Simplest; cannot express mixed-hazard capabilities
     (motion-adjacent AND emitting).
   - **(b) Full per-operation table on the descriptor** — an explicit
     `Mapping[Operation, tuple[route_name, ...]]` field. Maximally explicit;
     every descriptor carries routing boilerplate, and a wrong table is a
     descriptor bug in safety-relevant data.
   - **(c) Floor + monotone override (recommended presentation, not a
     decision)** — the class provides default routing (§7.2 table); a
     descriptor MAY override per operation, but overrides may only ADD
     routes, never remove a floor route. Mixed hazards expressible; loosening
     structurally impossible.
   Whatever the shape, the §7.2 LAWs (STOP never gated; tighten-only;
   generated UI never a safety control) hold.
2. **⚑ Multi-channel HV `capability_id` naming.** The grammar (§5.1) admits
   more segments. Proposal: the primary channel is `bias.voltage`
   (permanent), additional channels `bias.ch{n}.voltage` mirroring the
   `BiasChannel` index that `DeviceManager.refresh_bias_channels` enumerates.
   Since published ids are permanent (§5.2), the naming needs Kaya's nod
   before the first multi-channel descriptor is published. (D1 can ship with
   only the primary-channel id and defer this.)

## 15. TCT will NEVER guarantee

Per the Völundr contract addenda — an explicit no-promise list, so the
platform seed cannot inherit implied commitments:

- **No live data streaming.** The HDF5 file is a post-hoc artifact; no
  consumer may depend on reading a run while it is being written.
- **No network RPC control.** No remote entity sets, arms, starts, or stops
  anything. Cross-ref the PreflightHook invariant (roadmap Part III): safety
  computes locally and may veto; remote/platform I/O is never required to
  *permit*. Remote may only forbid, never enable.
- **Serpentine ordering permanent.** Point ordering stays boustrophedon as
  documented in `TCT_app/SCAN_DATA_FORMAT.md` §"Point ordering"; row index is
  not a grid index, and no future version will promise row-major order.
- **No mandatory read-back** (§9): `ReadbackPolicy.MANDATORY` does not exist
  and its absence is contractual.
- **No implicit arming or energising, ever**: no registry, descriptor,
  binding construction, or generated UI will ever connect, home, arm, or
  enable HV as a side effect.

## 16. Document history

- **v0.1-draft, 2026-07-13 (Paul)** — initial draft from roadmap Part I +
  bounce corrections F1/F2/F3, Codex BLOCKER-1/MAJOR-1/MAJOR-2, Völundr
  addenda; symbols verified against the working tree at authoring time.
  Awaiting Mary taxonomy review (S1) → Kaya ratification (D1 gate).
