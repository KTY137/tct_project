# TCT Capability Model

| | |
|---|---|
| **Version** | v0.3 |
| **Date** | 2026-07-13 |
| **Status** | v1.0-rc — Mary RATIFY-READY (amendments applied) · Kaya-ratified §14.1(c)+§14.2 2026-07-13 · D1 gate OPEN |
| **Owner** | Paul (driver contract) — plumbing halves (validator/config wiring) are Abel's |
| **Normative for** | roadmap stage D1a (`capabilities/model.py`) and D1b (`capabilities/adapters.py`, registry) |
| **Inputs (binding)** | `docs/ROADMAP_MASTERPLAN.md` Part I incl. bounce corrections F1/F2/F3, Codex BLOCKER-1 / MAJOR-1, the Völundr contract addenda in Part III, Mary's S1 taxonomy review (REQUEST-CHANGES, 2026-07-13), and the Codex C11 adversarial review (2026-07-13) — dispositions in §17 |

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
   `describe_capabilities()` (§11.1) is subject to the same law.

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
- **The restriction is ENFORCED, not advisory.** `__post_init__` MUST
  recursively validate `metadata` (and every nested value) against the allowed
  types and raise `TypeError` on anything else — a callable, an ndarray, a
  device reference fails at **construction**, not at provenance-write time.
  An unvalidated `Mapping[str, Any]` would smuggle behaviour past the F1
  data/binding split; fail closed at the door.
- `metadata` MUST be canonicalised in `__post_init__` to a **sorted tuple of
  `(key, value)` pairs** (nested mappings likewise, via
  `object.__setattr__` — the standard frozen-dataclass pattern).
  `types.MappingProxyType` is **REJECTED** for this role: a frozen dataclass
  with `eq=True` auto-generates `__hash__`, and hashing a descriptor with a
  `MappingProxyType` field raises `TypeError` — exactly the auto-hash trap F1
  warned about. The sorted-tuple form keeps the auto-generated `__hash__`
  working and makes snapshot ordering deterministic. `snapshot()` re-renders
  the pairs as plain dicts for JSON.
- As built in D1a (`capabilities/model.py::_canonicalise_json`, commit
  `208207e`, Mary-APPROVED), the canonical form forces a fail-closed
  ambiguity rule with a deliberate asymmetry: a user-supplied metadata tuple
  whose every element is a `(str, value)` 2-tuple — including the empty tuple
  `()` — is REJECTED at construction as indistinguishable from the
  encoded-mapping form, while a tuple of non-string-keyed pairs (e.g.
  `((1, 2), (3, 4))`) passes as plain data; the acceptance side is a
  consequence of the encoding, not a promise — pass a mapping (or reshape the
  tuple), never rely on a pair-shaped tuple staying accepted.
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
    device_id: str                  # IDENTITY — DeviceManager short key, §5.3
    transport_id: str               # LOCK OWNER — whose transport_lock reserve()
                                    # takes (§6.1); same §5.3 vocabulary; usually
                                    # == device_id, differs for pass-through
                                    # devices (ScopeChannelMonitor → "scope")
    label: str                      # human-readable, for UI/planner pickers
    safety_class: SafetyClass
    metadata: Mapping[str, Any]     # JSON-safe bag, validated+canonicalised in
                                    # __post_init__ (§4); NEVER policy input (LAW §7.5)

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
    channel: int | None = None      # resolved PHYSICAL BiasChannel index
                                    # (devices/bias_channel.py::BiasChannel.channel);
                                    # None = the driver has no channel concept.
                                    # Provenance disambiguation, §14.2 — never policy.

# NOT a CapabilityDescriptor (§5.4, Codex MAJOR-D): a non-registered grouping
# helper.  It has no capability_id BY CONSTRUCTION and can never be registered
# or snapshot into provenance — the registered capabilities are its axes.
@dataclass(frozen=True)
class Motion3D:
    axes: tuple[SweepableParameter, ...]   # the registered stage.x/y/z descriptors
```

Field-by-field live consumers (rule of economy, §3):

| Field | Consumer that exists or is gate-scheduled |
|---|---|
| `capability_id` | registry key (§11), `swept/` group name (§10), P3 `AxisSpec` resolution |
| `device_id` | registry → `DeviceManager` device lookup; `swept/` attr (§10) — **identity/provenance only, never the lock key** |
| `transport_id` | §6.1 reservation lock resolution; grouped-reservation deadlock ordering (sorted by `transport_id`); `swept/` attr (§10) |
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
| `channel` | `swept/` `channel` attr (§10) — disambiguates which physical HV channel a run drove (§14.2); multi-bias UI display |
| `axes` | motion-envelope construction; planner stage axes (P3) — a field of the `Motion3D` *helper* (§5.4), not of any descriptor |

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
- Seed vocabulary (v1): `stage.x`, `stage.y`, `stage.z`, `bias.voltage`
  (the primary-HV-channel *role*, §14.2), `bias.ch{n}.voltage` (one per
  non-primary physical HV channel, §14.2 — grammar-conforming: `ch1` matches
  `[a-z][a-z0-9_]*`), `wavegen.frequency`, `wavegen.pulse_width`,
  `wavegen.duty_cycle`, `wavegen.amplitude`, `wavegen.offset`,
  `wavegen.output` (TriggerSource), `scope.waveform` (WaveformSource),
  `camera.frame` (FrameSource), `intensity.amplitude` + `intensity.charge`
  (ReadableChannels, §5.4), `slow_control.<channel>` (ReadableChannel, one
  per configured channel, named per §5.1.1).
- Multi-channel HV naming is **specified** in §14.2 (Codex MAJOR-E: the
  deferral was unsound) and **Kaya-ratified 2026-07-13** ("ja nick ich ab")
  inside the D1-gate ratification of this document — the ⚑ is cleared.

### 5.1.1 Slow-control channel names — config→id mapping (decided)

The shipped channel names in `configs/devices.yaml` (`temperature_C`,
`humidity_pct`, `bias_voltage_V`, `leakage_current_nA`) violate this grammar
twice: uppercase, and unit suffixes in the id. Silent normalisation is
unfixable later (ids are permanent, §5.2; lowercasing can collide two channels
onto one id), so the mapping is decided **now**:

1. **Permanent static alias table** for exactly the four shipped names —
   the same machinery as §5.2 deprecation aliases, present from day one:

   | `devices.yaml` channel `name` | `capability_id` |
   |---|---|
   | `temperature_C` | `slow_control.temperature` (unit `"°C"`) |
   | `humidity_pct` | `slow_control.humidity` (unit `"%RH"`) |
   | `bias_voltage_V` | `slow_control.bias_voltage` (unit `"V"`) |
   | `leakage_current_nA` | `slow_control.leakage_current` (unit `"nA"`) |

   The config names themselves are **not** renamed: the channel `name` is a
   user-edited config key that also feeds the `connect_all` result keys
   (`slow_control/<name>`), slow-control HDF5/Influx series, and GUI labels —
   renaming it is a user-visible break of bench configs and existing data
   continuity for zero user benefit. The alias table costs one static dict.
2. **`config_validator` ERRORs** on any slow-control channel `name` outside
   `[a-z][a-z0-9_]*` that is not one of the four grandfathered names above,
   and on any name that collides with an alias target (e.g. adding a channel
   named `temperature` while `temperature_C` exists). Today
   `controller/config_validator.py::_check_slow_control` constrains the
   per-channel *keys* and threshold ordering but never the name charset —
   this is a **required D1a code change** (validator half: Abel; see §11.4).
3. **The registry FAILS CLOSED** on a channel name it cannot map: not in the
   alias table and not grammar-conforming → raise at registry build, never
   silently munge a name into an id.

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

`device_id` uses the `DeviceManager` **short keys**. Precisely (the two
sources do not coincide, so both are named): the local `devices` dict inside
`controller/device_manager.py::DeviceManager.connect_all` holds **five** keys
(`scope`, `motor`, `camera`, `waveform_generator`, `bias_supply`);
`intensity_monitor` is *not* in that dict — `connect_all` connects it
separately and adds it to its `results` — and it appears alongside the other
six as a value of `DeviceManager._DISPLAY_TO_SHORT`, which is the complete
six-entry vocabulary: `motor`, `scope`, `bias_supply`, `intensity_monitor`,
`camera`, `waveform_generator`. Slow-control channels use
`slow_control/<name>`, matching the `connect_all` result keys built from
`controller/slow_control_manager.py::SlowControlManager.connect_all`. These
strings inherit the §5.2 permanence promise the moment a descriptor publishes
them. `transport_id` (§6.1) draws from the same vocabulary — it names the
device whose transport lock the reservation takes.

### 5.4 Type-specific rules

- **`HVSource` has NO kill.** **LAW —** neither `HVSource` nor its binding
  exposes a kill/NOT-AUS/emergency-off surface. Kill stays on the single
  existing safety path (the STOP/ALL-OFF QWidget instances and the driver
  fail-safe paths); the capability layer never grows a second one. Polarity
  switching (`devices/bias_supply_base.py::BiasSupplyBase.set_polarity`, a
  DANGEROUS relay action) is likewise **not** a capability in v1 — it stays a
  panel-only, gate-confirmed action; the descriptor's `polarity` field is
  descriptive only.
- **`Motion3D` is a helper, NOT a capability** (decided v0.3, Codex
  MAJOR-D — v0.2 gave it descriptor *shape* with no registry *identity*).
  It aggregates the per-axis `SweepableParameter`s (`stage.x/y/z`, unit
  `"mm"`) so the registry builder and planner can treat the stage as one
  envelope, but it does **not** inherit `CapabilityDescriptor`: it has no
  `capability_id`, CANNOT be registered (registration is keyed by
  `capability_id`, which it lacks by construction), and is never snapshot
  into provenance — its *axes* are the registered, classed, serialised
  capabilities. Why this way and not a registered `stage.position`:
  (i) a binding drives exactly one capability and each axis already is one —
  a registered 3-vector twin would publish the same MOTION hazard path a
  second time, needing duplicate gate wiring for zero new ability;
  (ii) rule of economy — no consumer for a vector setpoint exists (the plan
  grammar's `Axis` and P3's `AxisSpec` are per-axis);
  (iii) v0.2's shape was self-contradictory anyway: a descriptor field
  holding `tuple[SweepableParameter, ...]` violates §4's JSON-scalar field
  restriction, so `Motion3D` never was a valid descriptor. A coordinated
  multi-axis-move capability, if ever needed, is a declared v2 extension
  (§12) — `stage.position` is REJECTED for v1, recorded so it is not
  re-proposed without a consumer.
  Axis `limits` MUST be derived from
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
  producers; their bindings expose acquisition, not setting. A
  `ReadableChannel` is a **single scalar quantity with one honest `unit`** —
  never a composite squeezed into one number.
- **Intensity publishes TWO channels, not one.**
  `devices/intensity_base.py::IntensityMonitorBase.read()` returns a
  *composite* `IntensityReading` (`amplitude_V`, `charge_pC`,
  `time_s`/`waveform_V` arrays, `saturated` flag); a single
  `intensity.reading` ReadableChannel would force the adapter to silently
  pick one quantity — the dishonest-label class §9 itself forbids, on a
  permanent id. Therefore v1 publishes `intensity.amplitude` (unit `"V"`,
  wrapping the proven `IntensityMonitorBase.get_amplitude`) and
  `intensity.charge` (unit `"pC"`, wrapping
  `IntensityMonitorBase.get_charge`). The waveform arrays and the
  `saturated` flag stay on the driver surface (the scan controller keeps
  consuming the composite directly); a typed composite `ReadableGroup` is a
  declared-not-designed v2 extension (§12).

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
drives exactly one capability. Its lifecycle (Codex BLOCKER-1; terminal stage
renamed in v0.2 — the normal path *releases*, the fault path *aborts*):

```
reserve → prepare → apply → wait_settled → verify_or_skip → release | abort
```

- **`reserve()`** — acquire the transport reservation (§6.1) for **one
  command exchange** (or one short atomic multi-set on the same transport,
  §6.1). Returns a context manager / token. `reserve` MUST take a timeout,
  MUST NOT be held across user-interaction waits (a modal confirmation
  happens *before* reserve), and MUST NOT be held across the blocking spans
  §6.2 forbids — the lifecycle re-reserves per exchange (apply's command
  issue, verify_or_skip's read), it does **not** hold one reservation across
  the whole apply→wait_settled→verify span.
- **`prepare(value)`** — validate `value` against descriptor limits and the
  driver's runtime gates; pre-compute the command(s). MUST NOT perform
  state-changing instrument I/O (read-only queries are permitted). Raises on
  an out-of-range value — fail closed *before* anything is sent.
- **`apply(value, *, shaping: Mapping[str, float] | None = None)`** — issue
  the setting. For `HVSource` this MUST route through the shaped-ramp path
  (`devices/bias_supply_base.py::BiasSupplyBase.ramp_to` semantics — never a
  direct `set_voltage` jump; a ramp-to-zero never energises an idle channel,
  per that method's SAFETY docstring). For a stage axis (`stage.x/y/z`) it
  routes through `MotorStageBase.move_to` (which re-checks limits and homing
  internally). `apply` entry is the "command-issued" event DA1's timing
  columns will timestamp.

  **`shaping` — the HV ramp-shape channel (Mary BUG-4).** The plan grammar
  carries ramp shaping (`controller/scan_plan.py::LoopBlock.ramp_step_V` /
  `ramp_delay_s`, folded by `_child_meta` onto each step's
  `LeafMeta.bias_ramp_step_V` / `bias_ramp_delay_s`), and the executor passes
  it into the driver today (`controller/scan_controller.py::ScanController.
  _ramp_bias` → `ramp_to(step_V=…, delay_s=…)`). A bare `apply(value)` gives
  that no channel, so a capability-hosted `HVSource` would silently fall back
  to the driver defaults (5 V / 0.1 s) — a safety-relevant **rate** change
  that the F3 equality-parallel gate cannot catch (it compares validator
  *issue sets*, not ramp timing). Therefore:
  - the executor passes plan-resolved shaping into `apply` exactly as it
    passes plan-resolved settle into `wait_settled` (§8); the binding never
    re-implements plan precedence;
  - `HVSource` shaping keys are the plan vocabulary, `"ramp_step_V"` and
    `"ramp_delay_s"`; the adapter maps them onto `ramp_to(step_V=…,
    delay_s=…)` exactly as `_ramp_bias` does today (including its `abs()` on
    the step and its bare-`ramp_to(target_V)` call when both are unset) —
    missing shaping = driver default, **byte-identical to today**;
  - a capability with no shaping semantics MUST raise on `shaping is not
    None` — silently ignoring it is the same dishonesty class this
    parameter exists to close.
- **`wait_settled(timeout_s)`** — block until the setpoint is physically
  settled: motion waits on the driver's readiness
  (`MotorStageBase.wait_until_ready` semantics), then dwells the **effective
  settle** (§8); non-motion capabilities dwell the effective settle. Return
  is the "settled" timing event. **LAW —** the executor MUST NOT begin an
  acquisition against this capability's point before `wait_settled` has
  returned. D1 exit includes the simulated delayed-apply test proving this,
  hosted on `devices/motor_simulated.py::SimulatedMotorStage` — the only
  simulated backend with genuine asynchronous settling (a background move
  thread behind `is_moving`/`wait_until_ready`); every other simulated
  backend applies synchronously and cannot exercise the race.
  Timeout raises `devices.base.DeviceError`-class failure → executor
  fail-safe path (safety rule 5).
- **`verify_or_skip()`** — the best-effort read-back stage (§9). Returns a
  `VerifyResult` (status ∈ {`measured`, `skipped`, `failed`}, value:
  `float | None`). It never raises on a mere mismatch and never blocks the
  run in v1: it *records*; policy stays with the executor. A mismatch beyond
  a declared tolerance SHOULD log a WARNING.
- **`release()`** — the normal terminal: drop any held reservation token.
  Pure bookkeeping; touches no instrument state.
- **`abort()`** — the fault terminal: return the capability to a safe idle:
  motion → `stop()`; HV → the **existing** fail-safe pair (ramp to 0, output
  off) via the same driver methods every fail-safe path already uses; trigger
  outputs → `output_off`. `abort` MUST be callable from any stage,
  idempotent, MUST NOT raise (it is the cleanup path), and per §6.2 is
  NEVER subject to the transport reservation. It introduces **no new safety
  path** — it delegates to the single existing one.

  **LAW — the binding lifecycle NEVER replaces the executor's finally-based
  fail-safe.** `abort()` is an *additional*, idempotent entry to the same
  path — it does not become the home of the fail-safe. A **clean finish**
  (which calls no `abort`) still runs the executor's fail-safe: today
  `ScanController._run_plan`'s `finally` unconditionally leaves HV safe
  (`_bias_failsafe`: ramp to 0, output off) whenever the run contained a
  `BiasStep`, on **every** exit path including success. Reading
  "abort delegates to the fail-safe" as license to *move* the fail-safe into
  `abort()` would leave HV energised at the last setpoint after a clean
  finish — that reading is forbidden.

**LAW —** bindings NEVER auto-connect, auto-home, auto-enable HV, or restore a
previous setpoint. Constructing or reserving a binding changes no instrument
state.

### 6.1 Transport reservation — the transport-lock ACCESSOR contract

The hazard the reservation kills is the one
`devices/base.py::BaseDevice.io_lock`'s docstring records: GUI pollers and
the scan thread share one VISA/serial session, and interleaved query/reply
pairs garble each other — the bench-observed TBS1052C `CURVE?`-wedge class.

v0.1 declared `io_lock` *itself* the reservation unit. **That was factually
wrong for motion** (Mary BLOCKER-1): `devices/motor_grbl.py::GRBLMotorStage`
serialises its serial link on a **private `self._lock`** (taken in `_send`,
`_send_wait`, `_grbl_status`) and never touches `io_lock`, and
`devices/motor_pi.py::PIMotorStage` serialised **nothing at all** at v0.1
authoring (fixed since in `4a89647` — it now guards on `io_lock`). Reserving
`motor.io_lock` would therefore have been, for GRBL, exactly the forbidden
second lock:
it excludes other bindings but NOT the GUI position poller, leaving the
interleave hazard alive on the one device class where it moves hardware.

The v0.2 contract is an **accessor**, not a fixed lock:

- **LAW — the reservation unit is the lock object the driver's own I/O
  methods actually acquire.** Every driver exposes it as a documented
  attribute, **`transport_lock`**:
  - `BaseDevice` provides the default, `transport_lock → self.io_lock` —
    already correct for the scope, wavegen, camera, bias supplies, and the
    slow-control backends (their I/O paths take `io_lock` today:
    `bias_supply_iseg.py`, `bias_supply_keithley.py`,
    `bias_supply_e4control.py`, `camera_blackfly.py`, …).
  - `GRBLMotorStage` MUST override it to return `self._lock` — the lock its
    serial exchanges actually take. Because the reservation wraps driver
    calls that internally re-acquire that lock (e.g. `get_position` →
    `_grbl_status`), `_lock` MUST become re-entrant
    (`threading.Lock` → `threading.RLock`). Same-thread re-entrancy is the
    only behavioural change; cross-thread exclusion is untouched, and the
    deliberately lock-free `stop()` is unaffected. **Named driver work,
    §11.4.**
  - `PIMotorStage` MUST serialise its GCS calls (`qPOS`, `MOV`, `IsMoving`,
    homing): before `4a89647` they ran unserialised, so a GUI poller and the
    scan thread could interleave on the shared GCS session — a pre-existing
    driver gap this contract surfaced. **Landed** (`4a89647`): every
    GCS-touching method acquires the transport lock, and PI meets the contract
    via `io_lock` — its `transport_lock` returns `io_lock` (the `BaseDevice`
    default, re-declared only for explicitness), **not a new dedicated lock**.
    **Named driver work, §11.4.**
- **MUST** reserve via `transport_lock` — never a parallel second lock over
  the same transport (two locks = the interleave hazard returns).
- **`device_id` is identity; `transport_id` is the lock key — they are
  separate fields and MAY disagree** (Mary BUG-6). **Worked pass-through
  example (normative):**
  `devices/intensity_scope_ch.py::ScopeChannelMonitor` is a `BaseDevice`
  with its *own* (idle) `io_lock` but reads through
  `Oscilloscope.read_channel` — the real transport lock is the **scope's**.
  Its capabilities declare `device_id="intensity_monitor"` (honest
  provenance) and `transport_id="scope"` (honest lock owner); the binding
  reserves the scope's `transport_lock`, and the monitor's own idle
  `io_lock` is never the reservation unit. The adapter for a pass-through
  device MUST set `transport_id` to the short key of the device whose I/O
  path the wrapped method actually exercises (the adapter layer may import
  `devices/*` per §2.2, so an `isinstance(monitor, ScopeChannelMonitor)`
  dispatch is legal and sufficient). Overloading `device_id` for both
  roles would force a lie into one of them.
- **The lock RESOLVER (Codex BLOCKER-A) — exactly one API maps
  `transport_id` to a lock object.** `CapabilityRegistry` (D1b, §11.2)
  builds a **transport map** at construction, from the same `DeviceManager`
  attributes §11.2 enumerates — no live query, per LAW §2.4:
  - `"motor"` → `self.motor`, `"scope"` → `self.scope`,
    `"camera"` → `self.camera`,
    `"waveform_generator"` → `self.waveform_generator`,
    `"intensity_monitor"` → `self.intensity_monitor`,
    `"slow_control/<name>"` → that `SlowControlChannel` instance (a
    `BaseDevice`, so it carries the default accessor);
  - `"bias_supply"` → **the shared driver**, reached as
    `self.bias_supply.driver`
    (`devices/bias_channel.py::BiasChannel.driver`): `DeviceManager.bias_supply`
    and every entry of `bias_channels` are `BiasChannel` **proxies with no
    lock of their own** — their I/O delegates to the one shared
    `BiasSupplyBase`, whose per-call `io_lock` is the real transport lock.
    Resolving on the proxy would re-create Mary BLOCKER-1 (a lock nothing
    acquires); all HV channels sharing one `transport_id` = one lock is
    exactly right, because they share one physical transport.
  The resolved lock is `transport_map[descriptor.transport_id].transport_lock`
  — one attribute lookup on one named instance, no fallback, no search. A
  `transport_id` outside the map raises `KeyError` at **registry build /
  binding construction** (fail closed, before any reserve). The registry
  exposes this as `CapabilityRegistry.transport_lock_for(transport_id)`;
  bindings resolve their lock **through it at construction** — no second
  resolution path may exist.
- Multi-capability atomic sets (e.g. frequency+duty on one wavegen) reserve
  once per transport; cross-transport grouped reservations MUST acquire in
  sorted **`transport_id`** order (deadlock avoidance — sorting by
  `device_id` would order by the wrong key when the two differ) and MUST
  use timeouts.
- **D1b test requirement (identity, not convention):** for every registered
  binding, the object the reservation acquires MUST be **identical** —
  `is`, not merely equivalent — to the lock the driver's own I/O path
  acquires, **resolved through `transport_lock_for`, not asserted ad hoc**
  (e.g. `binding.transport_lock is grbl._lock`,
  `intensity_binding.transport_lock is scope.io_lock`,
  `bias_ch1_binding.transport_lock is dm.bias_supply.driver.transport_lock`
  — the same object for every HV channel). A per-adapter identity assertion,
  one resolver fail-closed test (unknown `transport_id` raises at build),
  plus one behavioural test (hold the reservation in simulation, prove a
  concurrent driver I/O call blocks) gate D1b exit.

### 6.2 Reservation vs. fail-safe — never in the way of STOP

(Mary BLOCKER-2.) A reservation held across a whole
apply→wait_settled→verify span would make emergency paths *wait for the
hazard to finish*. Concretely: `BiasSupplyBase.ramp_to` acquires and releases
the transport lock **per step** today (each `set_voltage`/`read` inside the
backends takes `io_lock` per call), so a cross-thread ALL-OFF/emergency-off
interleaves within about one step delay (~0.05–0.1 s). Under a held
reservation it would wait out the **entire ramp** — seconds to tens of
seconds on a −1000 V ramp. That is a safety inversion, same family as the
gated-STOP inversion §7.2 forbids.

- **LAW — STOP, abort, and fail-safe paths are NEVER subject to the
  transport reservation.** They never wait on it, are never queued behind
  it, and no reservation design may require them to acquire it.
- **The reservation MUST NOT be held across any blocking multi-step driver
  loop** — `ramp_to`'s step loop, `wait_until_ready`/`_grbl_wait_idle`-class
  readiness polling, or any dwell. Reserve **per command exchange**; if a
  future design needs a longer hold, the token MUST be preemptible by the
  fail-safe path (and that design change needs its own review).
- The codebase already knows this pattern — two proven non-contending prior
  arts, cited as the models to follow:
  - `motor_grbl.py::GRBLMotorStage.stop()` is deliberately lock-free: *"a
    locked stop would be queued behind the very move it is supposed to
    interrupt"* (its in-code comment).
  - The liveness probe never blocks on the lock:
    `BaseDevice.is_alive`'s contract ("must never block on the io_lock")
    and `camera_blackfly.py::BlackflyCamera.is_alive`'s
    `io_lock.acquire(blocking=False)` implementation.
- Per-command reservation gives up nothing: exchange-atomicity is exactly
  the protection the drivers' own per-exchange locking provides today; the
  reservation adds cross-binding exclusion and atomic grouping, not longer
  holds.

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
- The class is a **coarse display tier**, not a complete hazard statement —
  that is exactly why routing is declared per operation (§7.2). The order
  does not claim EMITTING is more dangerous than HV in every context.
- **`>=` comparisons are legal ONLY for display/styling decisions** (danger
  colouring, confirmation prominence, the §7.4 disabled-control rule) —
  **NEVER for deriving gate sets.** The §7.2 floor table is *non-monotone*
  in this ordering (EMITTING, the highest class, has an **empty** `SET`
  floor while MOTION and HV do not), so `safety_class >= X` cannot be
  trusted to mean "at least as gated" — v0.1's claim to that effect was
  unsound (Mary BLOCKER-3) and is withdrawn. Gate sets come only from the
  per-hazard union LAW in §7.2.

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
- **LAW — `safety_class` is the MAXIMUM hazard, not a chosen label.** A
  capability's `safety_class` MUST equal the max (§7.1 ordering) of the
  class of **every** hazard its driver path can cause. Nothing in v0.1
  required this, so a hypothetical combined move+bias capability declared
  `MOTION` was legal — and would have shipped with no `hv_lock`
  (Mary BLOCKER-3).
- **LAW — routing is the UNION over touched hazards.** A capability's
  effective routing MUST be the union of the floor routes of every hazard
  class its driver path touches — never just the floor of its (single)
  declared class. A capability spanning **two hazard domains MUST be
  split** into per-domain capabilities in v1; the union rule is the
  backstop, the split is the requirement.
- **D1 test requirement:** a registry-wide test asserts that **no v1
  capability spans hazard domains** — for every published descriptor, the
  driver path it wraps (§11.1 table) touches exactly one hazard domain, and
  its `safety_class` equals that domain's class. This is what makes the
  §7.2 floor table sufficient for v1 despite its non-monotonicity (§7.1).

### 7.3 Class assignments (v1)

- `stage.x/y/z` → `MOTION`. (The `Motion3D` envelope helper carries no
  class of its own — it is not a descriptor, §5.4; its axes are the classed
  capabilities.)
- `bias.voltage` and every `bias.ch{n}.voltage` (`HVSource`, §14.2) → `HV`.
- `wavegen.*` setters and `wavegen.output` → `EMITTING` (the wavegen drives
  the laser trigger — see the EMITTING note in
  `ScanController._apply_wavegen_settings`'s docstring). The laser itself has
  no PC control (`devices/laser_manual.py::LaserManualMetadata` is
  metadata-only) — there is deliberately **no** `laser.*` capability in v1.
- `scope.waveform`, `camera.frame`, `intensity.amplitude`,
  `intensity.charge`, `slow_control.*` → `BENIGN`.

### 7.4 HARD LAW — generated UI and safety controls

**Generated UI NEVER produces safety controls, and the gate law binds per
(capability, OPERATION) — never per class alone** (rewritten in v0.3, Codex
MAJOR-F: v0.2's per-class wording contradicted the §7.2 route table for
EMITTING setters). A generated form (D4b) may render values, units, limits,
and danger *styling* (class-based `>=` styling stays legal, §7.1), and:

- For every (capability, operation) a generated widget can fire, the
  **effective route set** comes from §7.2 (class floor plus any §14.1
  add-only override). If that set is **non-empty**, the operation MUST
  route through the existing QWidget gates (`QtDangerGate` modal and the
  established envelope/lock paths); no generated widget may fire it without
  them.
- If the set is **empty**, the generated control fires ungated — that is
  the route table's meaning, not a loophole. Concretely: `wavegen.*` `SET`
  is ungated today (`_apply_wavegen_settings`) and MUST stay so in a
  generated panel. What makes EMITTING `SET` safe is a **driver-path
  property, stated here normatively: wavegen setters never touch output
  state** — `_apply_wavegen_settings` "NEVER touches `output_on` /
  `output_off`" (its docstring; the setters adjust parameters of an output
  that is only ever armed inside `_acquire_core`). The emission **ARMING**
  is the gated operation, not the parameter value — which is why the ladder
  needs no modal per duty-cycle edit. A per-edit confirmation on
  frequency/duty would push the operator toward an auto-confirm
  workaround — the exact gate-defeat path this section exists to prevent.
- An operation whose floor names a **RESERVED** route
  (`emission_interlock` before P3) MUST be rendered **DISABLED** (reason
  shown) in generated UI — never fired ungated, never given an invented
  stand-in gate. Concretely: no generated ARM control for `wavegen.output`
  until P3 lands.
- No generated widget may implement a STOP/kill/ALL-OFF control — those
  remain the hand-written QWidget instances on the single existing safety
  path. (`STOP` being ungated in §7.2 is about those existing controls; it
  licenses no generated one.)
- A generated control for a capability with `safety_class >= MOTION` whose
  descriptor has `limits=None` MUST be rendered **DISABLED** (with the
  reason shown), never as an unbounded setter — the `>=` here is legal
  because disabling can only fail closed (§7.1). This case is real, not
  theoretical: `BiasSupplyBase.voltage_range_V` is optional
  (`float | None`), so an `HVSource` descriptor can legally carry
  `limits=None`.
- **D4b test requirement — the contract is testable against the route
  table:** for every published (capability, operation) pair, a D4b test
  asserts the generated widget (a) fires the gate **iff** the effective
  route set is non-empty, (b) renders DISABLED for RESERVED routes and for
  the `limits=None` case, and (c) exposes no STOP/kill surface. The route
  table is data; the UI law is checkable against it, not against prose.

### 7.5 LAW — `metadata` is never policy input

No safety decision, gate routing, limit, or validator behaviour may read
`CapabilityDescriptor.metadata`. It is a provenance bag — type-checked for
JSON-safety (§4) but semantically unvalidated; policy fields must be
first-class typed fields with named consumers.

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
  - `BEST_EFFORT` — `verify_or_skip()` attempts one read-back inside its own
    per-command reservation (§6.1); failure degrades to `failed`, never to a raise and
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
/swept/bias.voltage/commanded          f8  (N,)   point-aligned (alignment table)
/swept/bias.voltage/readback           f8  (N,)   [BEST_EFFORT only]
/swept/bias.voltage/readback_skipped   u1  (N,)   [BEST_EFFORT only]
/swept/bias.voltage/event_value        f8  (M,)   apply-indexed, NOT point-aligned
/swept/bias.voltage/event_row          i8  (M,)   dangling-tag row reference
```

Literal dataset names and dtypes:

| Dataset | dtype | shape | Presence | Meaning |
|---|---|---|---|---|
| `commanded` | `f8` | `(N,)` | always (for a swept capability) | value commanded at each point; `NaN` where this capability was not set at that point (NaN-honesty: never zero-filled) |
| `readback` | `f8` | `(N,)` | only when `readback == BEST_EFFORT` | **measured** value; `NaN` where skipped or failed. MUST contain only measured values (LAW §9) |
| `readback_skipped` | `u1` | `(N,)` | only when `readback == BEST_EFFORT` | `0` = measured; `1` = skipped by policy/reservation hold; `2` = read attempted but failed/unparseable |

**Alignment — per scan type, not `/points`-only (Codex BLOCKER-B).** v0.2
aligned `swept/` exclusively with `/points`, which lost two truths:
`SCAN_DATA_FORMAT.md` has non-`/points` scan tables, and a command whose
point row never lands had no home. Both are fixed structurally:

Every run type has at most one **alignment table** — the per-point record
its point-aligned `swept/` datasets index into (real shapes from
`TCT_app/SCAN_DATA_FORMAT.md` §"Datasets (other scan types)"; writer symbols
verified):

| `run_info/scan_type` | Alignment table | Row appended by |
|---|---|---|
| `xy_scan` | `/points` | `HDF5Writer.save_point` |
| `voltage_scan` | `/voltage_scan` | `HDF5Writer.save_voltage_point` |
| `z_focus_amplitude` / `z_focus_edge` | `/z_focus` | `HDF5Writer.save_z_focus_point` |

- The point-aligned datasets (`commanded`, `readback`, `readback_skipped`)
  are index-aligned with the run's alignment table (row *i* ↔ that table's
  row *i*), extensible, gzip, chunk 64 — the established scalar-dataset
  shape. A point-aligned row is appended by **the same event that appends
  its alignment-table row** (`save_point` / `save_voltage_point` /
  `save_z_focus_point`), so the two can never desync; a set whose point
  never reaches that save writes **no** point-aligned row — by
  construction — and survives in the event datasets below instead. Each
  `swept/` group records which table via the `aligned_with` attr (below),
  so a reader never guesses.
- Honesty note on the existing tables (verified in
  `controller/scan_controller.py`): `/voltage_scan/voltage_V` is
  **measured** (`_save_voltage(reading.voltage_V, …)` — the post-ramp
  `BiasReading`), while `/z_focus/z_mm` is **commanded** (the loop saves the
  setpoint `float(z)`). The `swept/` layer adds the commanded/readback
  distinction *structurally* instead of per-table lore — e.g. a voltage
  scan's `swept/bias.voltage/commanded` (the setpoint) is genuinely new
  information beside the measured `voltage_V` column, and no existing
  column is re-labelled.
- A run whose alignment table gets no rows (e.g. a photo-only survey)
  writes no point-aligned datasets — but MAY still write **event** datasets
  (below), which need no table.

**Command events — apply-indexed, NOT point-aligned (Codex BLOCKER-B /
Mary RISK-9).** Two further datasets per `swept/` group:

| Dataset | dtype | shape | Presence | Meaning |
|---|---|---|---|---|
| `event_value` | `f8` | `(M,)` | always (for a swept capability) | value of apply-attempt *k*, in command order |
| `event_row` | `i8` | `(M,)` | always | the alignment-table row attempt *k* was commanded FOR — the row a later save at that point WILL occupy; **dangling** (`>=` table length) when that row never landed |

Semantics — deliberately the proven `camera/frame_point_index` dangling-tag
pattern (`SCAN_DATA_FORMAT.md` §CAPTURE_PHOTO), not a new invention:

- An event row is appended at **`apply` entry** (§6's command-issued event:
  after `prepare`'s fail-closed validation, immediately before the first
  driver command of the exchange). A `prepare`-rejected value therefore
  never gets an event (nothing was issued); an `apply` that raises
  mid-exchange still leaves its event — the post-mortem question "what was
  the last thing we asked the instrument to do?" MUST be answerable from
  the file. (This is deliberately *stronger* than the P0' stopgap, whose
  trace appends only after a setter returns; the delta is visible only on
  runs that abort mid-apply, so the §11.3 equality gate is unaffected.)
- Events are appended **incrementally** (extensible dataset, the
  established writer behaviour) — never buffered to run end. A fault after
  a successful set loses nothing; a hard kill loses at most the event in
  flight, matching `outcome="unknown"` honesty.
- `event_row` values are not unique (a retried point commands twice) and
  readers MUST bounds-check them against the alignment table's length
  before indexing — exactly the `frame_point_index` reader contract. Where
  a row *did* land, the LAST event with `event_row == i` is the command in
  effect at that row's save, and MUST equal `commanded[i]` — a DA1 writer
  test.
- Worked fault cases (both real, verified in `scan_controller.py`):
  1. **Wavegen set + acquire fails:** `_apply_wavegen_settings` runs BEFORE
     `_acquire_core`; a duty-cycle set that succeeds followed by a failing
     acquire aborts the run with no `/points` row for that attempt — the
     `swept/wavegen.duty_cycle` events keep the command, `event_row`
     dangling. The P0' honesty property, now structural.
  2. **IV compliance trip:** the voltage sweep ramps to step *k*'s
     setpoint, `reading.compliant` trips, and the loop `break`s **before**
     `_save_voltage` — `/voltage_scan` holds rows `0..k-1`, and the
     `swept/bias.voltage` events end with the trip setpoint at dangling
     `event_row == k`. The trip voltage is in the file.

**LAW — commanded-but-unsaved sets MUST survive in provenance** (Mary
RISK-9). The event datasets above are the specified mechanism; DA1
implements them (under its own [Kaya] gate) and MUST keep the P0'
`wavegen_command_trace` alongside until the §11.3 equality gate confirms
the events reproduce it. DA1 owns the implementation; this honesty rule is
owned here and gates DA1's design — it is settled BEFORE the format
freezes, not during.

Literal **group attributes** on each `swept/{capability_id}` group (HDF5
string attrs unless noted):

| Attr | Type | Value |
|---|---|---|
| `capability_id` | str | the id (redundant with the group name, kept for self-description) |
| `device_id` | str | §5.3 short key — identity/provenance (never the lock key, §6.1) |
| `transport_id` | str | §6.1 lock owner (usually == `device_id`) |
| `unit` | str | descriptor `unit` |
| `safety_class` | str | enum member NAME (`"HV"`), never a number (§7.1) |
| `label` | str | descriptor `label` |
| `readback_policy` | str | `"NONE"` / `"BEST_EFFORT"` |
| `model_version` | str | capability-model version (§4) |
| `aligned_with` | str | absolute path of the run's alignment table (`"/points"`, `"/voltage_scan"`, `"/z_focus"`) — present whenever point-aligned datasets are |
| `channel` | int | **`HVSource` groups only** — the resolved physical `BiasChannel` index the run drove (descriptor `channel`, §14.2); disambiguates `bias.voltage` across configs |

Additionally the full `descriptor.snapshot()` of every swept capability
serialises into the run's `scan_config` metadata (the `/run_info` group per
SCAN_DATA_FORMAT) — the descriptor, never the binding (LAW §3).

Until DA1 lands, the P0' honesty stopgap remains:
`ScanController._flush_wavegen_trace` writes `wavegen_command_trace`
(per-point COMMANDED values) into `/run_info`. P1's pilot proof-of-done
includes the RECORDED sweep in `swept/` (roadmap F4 ordering).

## 11. Adapter strategy and registry

### 11.1 Zero ABC signature changes (small named driver additions in §11.4)

**Zero ABC signature changes** — but no longer "drivers need not change at
all": the §6.1 accessor contract requires the small, additive driver-side
items enumerated in §11.4. The four existing ABCs —
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
| `stage.x/y/z` (grouped by the `Motion3D` helper, §5.4 — the axes are the registered capabilities) | `MotorStageBase.move_to` / `get_position` / `wait_until_ready` / `stop`; limits from `limits_user_frame()` |
| `bias.voltage` (`HVSource`) | `BiasChannel.ramp_to` / `read()` on the primary proxy (`DeviceManager.bias_supply`) — delegates to the driver's `ramp_to_ch`/`read_ch`, preserving `BiasSupplyBase.ramp_to` shaped-ramp semantics; limits from `voltage_range_V` |
| `bias.ch{n}.voltage` (`HVSource`, §14.2) | the same `BiasChannel` surface on `DeviceManager.bias_channels[n]` — same shared driver, same `transport_id="bias_supply"`, same lock (§6.1) |
| `wavegen.frequency/pulse_width/duty_cycle/amplitude/offset` | `WaveformGenerator.set_frequency` / `set_pulse_width` / `set_duty_cycle` / `set_amplitude` / `set_offset` — the same setters `_apply_wavegen_settings` forwards today, in the same deterministic order (frequency first) |
| `wavegen.output` (`TriggerSource`) | `WaveformGenerator.output_on` / `output_off` (ARM path hard-coded until P3, §7.2) |
| `scope.waveform` (`WaveformSource`) | `Oscilloscope.acquire` / `read_channel` |
| `camera.frame` (`FrameSource`) | `BlackflyCamera.get_frame` / `get_frame_with_meta` |
| `intensity.amplitude` (`ReadableChannel`) | `IntensityMonitorBase.get_amplitude` |
| `intensity.charge` (`ReadableChannel`) | `IntensityMonitorBase.get_charge` |
| `slow_control.<name>` (`ReadableChannel`) | `SlowControlChannel.read_with_status` |

Recorded divergence (v0.1 claimed this note was in-doc; it was not — Mary
NIT-12): there is **no `waveform_generator_simulated.py`** — unlike the
motor/bias/intensity/slow-control backends, the wavegen's simulation path is
**in-class** (`simulation=True` branches inside
`devices/waveform_generator.py::WaveformGenerator`). Adapter tests for the
`wavegen.*` capabilities use that in-class path; the D1-exit delayed-apply
test does NOT use the wavegen (it applies synchronously) but
`SimulatedMotorStage` (§6, `wait_settled` LAW).

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
- `transport_lock_for(transport_id)` — the ONE lock resolver (§6.1);
  bindings resolve their lock through it at construction; unknown
  `transport_id` raises `KeyError` (fail closed). No I/O — the transport
  map is built from the same device attributes above.

**Direct access remains**: nothing existing migrates to the registry; panels,
scan controller, and tests keep using `DeviceManager` attributes; tests opt
in to the registry. The registry is additive discovery, not a mandatory
indirection.

### 11.3 Pilot

The first capability-executed feature is the wavegen (P1), re-landing the
now-shipped P0' behaviour (`ScanController._apply_wavegen_settings` +
`wavegen_command_trace`) behind the capability path, gated on behavior
equality against P0' — command order + point index + final `swept/` rows,
never just a run-level setting (Codex MAJOR-2). The §10 event datasets are
the structural home of that attempt-indexed comparison: on any run that does
not abort mid-apply, trace entries map 1:1 onto event rows. Note for reviewers: the
roadmap's Part I line "params['wavegen'] … dropped at scan_controller.py:1413"
described the pre-P0' state and is **stale at HEAD** — the executor forwards
per-point wavegen params today; P1's job is re-hosting, not fixing.

### 11.4 Required code work this contract implies (scheduled, not hidden)

This spec is not free. Landing D1 against it requires the following named
changes — each small and additive, none an ABC *signature* change, all
needing tests (and the driver items a Mary review, safety class):

| # | Change | File / symbol | Owner half |
|---|---|---|---|
| 1 | `transport_lock` default accessor (returns `self.io_lock`) — concrete attribute/property, not abstract | `devices/base.py::BaseDevice` | Paul |
| 2 | `GRBLMotorStage._lock`: `threading.Lock` → `threading.RLock`, plus `transport_lock` override returning it. Same-thread re-entrancy only; `stop()` stays lock-free | `devices/motor_grbl.py` | Paul |
| 3 | `PIMotorStage` transport serialisation: every GCS-touching method (`get_position`, `is_moving`, `at_limit_switch`, `move_to`, `home`, `_wait_on_target`) guarded on `io_lock`; `transport_lock` returns `io_lock` (the `BaseDevice` default, no new dedicated lock). **Landed** `4a89647` (+ disconnect-stops-first `fbf94d8`, lock-free `stop()` `7a55d03`). Fixed a pre-existing unserialised-transport gap, capability layer or not | `devices/motor_pi.py` | Paul |
| 4 | Slow-control channel-name charset check: ERROR on a `name` outside `[a-z][a-z0-9_]*` that is not one of the four §5.1.1 grandfathered names; ERROR on collision with an alias target | `controller/config_validator.py::_check_slow_control` | Abel (validator half — dispatch in the same beat wave as D1a) |
| 5 | Registry fail-closed on unmappable slow-control names + the §5.1.1 static alias table | `capabilities/` registry (D1b) | Paul |
| 6 | `CapabilityRegistry.transport_lock_for` — the §6.1 transport map/resolver (`bias_supply` → `BiasChannel.driver`); `KeyError` at build on unknown `transport_id` | `capabilities/` registry (D1b) | Paul |
| 7 | `HVSource.channel` populated from `BiasChannel.channel`; `bias.ch{n}.voltage` descriptors published per §14.2 | `capabilities/` adapters + registry (D1b) | Paul |

Items 1–3 are the **driver-side follow-up of the §6.1 accessor contract**
(Mary BLOCKER-1) — real work, recorded here so it is scheduled, not
discovered. Status (verified in the working tree): items **1–3 have LANDED** —
`BaseDevice.transport_lock` and the GRBL `RLock`+override exist, and `4a89647`
guards every PI GCS exchange (`get_position`, `is_moving`, `at_limit_switch`,
`move_to`, `home`, `_wait_on_target`) on `io_lock` (which `transport_lock`
returns), `fbf94d8` made PI `disconnect()` stop the stage first, and `7a55d03`
made PI `stop()` lock-free (`#24`/StopAll). Only the later items remain
**outstanding**: validator charset (**4**), registry fail-closed (**5**), the
transport resolver (**6**), and `bias.ch{n}` publication (**7**). Items 6–7
are new in v0.3 (Codex BLOCKER-A / MAJOR-E).

Beyond D1, this contract also gates (scheduled at their own stages, listed
here so the schedulable list is complete):

| Stage | Change | File / symbol | Owner |
|---|---|---|---|
| DA1 | `swept/` event datasets (`event_value`/`event_row`), `aligned_with`/`channel` attrs, per-scan-type alignment (§10) | `data/hdf5_writer.py` + `SCAN_DATA_FORMAT.md` version bump | Jonathan (under DA1's [Kaya] gate) |
| D4b | Route-table conformance test for generated UI (§7.4): gate fired iff route set non-empty; RESERVED/`limits=None` → DISABLED; no STOP surface | D4b test suite | Noah |

## 12. v2 extensions — declared, NOT designed

Reserved for a future model version; deliberately absent from v1 (each would
violate the no-field-without-consumer rule today):

- **Discrete-valued parameters** (enumerated choices, e.g. coupling,
  pixel format). v1 `SweepableParameter` is continuous-only.
- **Per-set max-step** (a per-transition delta clamp distinct from `limits`
  and from the HV ramp shaping that rides `apply(…, shaping=…)` per §6,
  sourced from `LoopBlock.ramp_step_V` / `ramp_delay_s`).
- **`ReadableGroup`** — a typed composite read (multiple quantities plus
  quality flags from one physical readout, the `IntensityReading` shape:
  amplitude + charge + waveform arrays + `saturated`). v1 publishes the two
  scalar `ReadableChannel`s instead (§5.4); the composite stays on the
  driver surface until a v2 consumer exists.
- **Coordinated multi-axis motion** — a registered vector-setpoint
  capability (`stage.position`-style). v1 deliberately registers only the
  per-axis `stage.x/y/z` (`Motion3D` is a non-registered helper, §5.4);
  a vector capability needs vector `limits`/`unit` semantics and has no
  consumer today.

Declaring them here reserves the concepts so nobody wedges them into
`metadata` (which LAW §7.5 would forbid consuming anyway).

## 13. Non-breakage laws

1. **Additive only.** The capability spine adds modules; it modifies no ABC
   signature, no observable driver behaviour, no existing dataset or group.
   The §11.4 driver items are the audited exceptions and are additive in
   effect: a default accessor, a lock-type widening whose only behavioural
   delta is same-thread re-entrancy (no code path nests it today — plain
   `Lock` would deadlock if one did), and serialisation where none existed.
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

## 14. Open questions for Kaya — both RATIFIED 2026-07-13

1. **Per-operation routing SHAPE — RATIFIED: option (c)** (Codex MAJOR-1 —
   Kaya's personal gate; ratified 2026-07-13, Kaya verbatim: "ich bestätige").
   The menu below is preserved for the record; (c) is the ratified shape, and
   it was honest about safety after Mary's S1 taxonomy review — not three
   neutral options:
   - **(c) Class floor + monotone add-only override — the crew's
     RECOMMENDATION, and the only shape Mary signs.** The class provides
     default routing (§7.2 table); a descriptor MAY override per operation,
     but overrides may only **ADD** routes, never remove a floor route.
     Mixed hazards expressible; loosening structurally impossible; works
     with the §7.2 union LAW as its backstop.
   - **(b) Full per-operation table on the descriptor** — the heavier
     alternative: an explicit `Mapping[Operation, tuple[route_name, ...]]`
     field. Maximally explicit, but every descriptor carries routing
     boilerplate, and a wrong table is a descriptor bug in safety-relevant
     data. Acceptable to Mary in principle; more surface for the same
     guarantee.
   - **(a) Class ladder only — REJECTED (Mary ruling, S1 review): UNSAFE as
     written.** Recorded so it is not re-proposed: `safety_class` alone
     cannot express mixed-hazard capabilities, and the §7.2 floor table is
     non-monotone in the §7.1 ordering (EMITTING's empty `SET` floor), so
     class-only routing lets a combined move+bias capability declared
     `MOTION` legally ship with no `hv_lock`. The §7.2 max-hazard and union
     LAWs close that hole regardless of shape, but (a) would rely on the
     backstop as its *only* mechanism — a ladder that cannot say what it
     means is not a safety surface.
   Whatever the shape, the §7.1/§7.2 LAWs (STOP never gated; tighten-only;
   `>=` never derives gate sets; max-hazard class; union routing; generated
   UI never a safety control) hold.
2. **Multi-channel HV `capability_id` naming — SPECIFIED in v0.3, RATIFIED
   2026-07-13 (Codex MAJOR-E; Kaya verbatim: "ja nick ich ab").** v0.2 deferred
   this behind a Kaya flag, but the deferral was unsound:
   `ScanController._resolve_bias` +
   `DeviceManager.refresh_bias_channels` already execute non-primary
   `BiasChannel`s today (`safety["bias_channel"]=1` is a runnable saved
   plan), so a D1 without the naming either serialises such a run as plain
   `bias.voltage`/`device_id="bias_supply"` — indistinguishable from the
   primary channel — or has no descriptor for a plan that runs. The naming
   (option **a**, ratify now):
   - **`bias.voltage` is the primary-channel ROLE id** — permanent, and the
     honest continuation of every historic single-channel file. It is
     deliberately **NOT an alias for channel 0**: the primary's physical
     index is config-chosen (`DeviceManager._bias_primary_ch`, from the
     driver's configured channel), so pinning `bias.voltage := ch0` would
     lie on any bench with a different primary. The resolved physical index
     rides first-class in `HVSource.channel` (§5) and the `swept/`
     `channel` attr (§10), so provenance is always disambiguable per run.
   - **`bias.ch{n}.voltage` names PHYSICAL channel *n*** — the 0-based
     `BiasChannel.channel` index `DeviceManager.refresh_bias_channels`
     enumerates. Its meaning never moves with config; it is *published* for
     each non-primary channel of the current config (config-dependent
     publication is not id removal — a bench without a camera publishes no
     `camera.frame` either).
   - **Physical identity wins the mapping**: `_resolve_bias` with an
     explicit index equal to the primary returns the SAME primary proxy
     object, so the registry maps it to `bias.voltage` — one physical
     channel is never two simultaneously-published ids, and `swept/` group
     names stay unambiguous.
   - All `bias.*` capabilities share `transport_id="bias_supply"` — one
     physical transport, one lock (§6.1) — so two channels can never
     interleave on the shared link.
   - **Rejected alternative (b) — fail-closed block on non-primary
     provenance/execution until ratification**: rejected because it either
     refuses a plan that runs today (breaking a working user workflow over
     bookkeeping, not hazard) or lets DA1 write channel-1 provenance
     labelled as the primary — the exact dishonesty MAJOR-E names.
     Fail-closed is for hazards; this one we know how to record honestly.
   Published ids are permanent (§5.2), so this naming needed Kaya's explicit
   nod: **given 2026-07-13** ("ja nick ich ab") as part of the D1-gate
   ratification of this document. Multi-channel descriptors MAY now be
   published. D1 was never left with an unrunnable case — the spec was
   complete either way he ruled.

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
- **v0.2, 2026-07-13 (Paul)** — closes Mary's S1 taxonomy review
  (REQUEST-CHANGES: 3 BLOCKER, 4 BUG, 2 RISK, 2 NIT; disposition table in
  §17). Headline changes: transport reservation rebuilt as the
  `transport_lock` accessor contract with named driver work (§6.1, §11.4);
  reservation never blocks STOP/fail-safe and never spans blocking driver
  loops (§6.2); max-hazard + union-routing LAWs and the `>=`-derivation ban
  (§7.1/§7.2); §14.1 option (a) REJECTED per Mary's ruling, (c) recommended;
  `apply` gains the shaping channel; slow-control id mapping decided
  (§5.1.1); `transport_id` split from `device_id`; intensity split into two
  honest channels; metadata validation fail-closed; swept/ append-time +
  survival rules; lifecycle terminal renamed `release | abort`. All v0.1
  symbols re-verified against the working tree; Mary's code claims confirmed
  before each fix. Awaiting Mary re-review → Kaya ratification (D1 gate).
- **v0.3, 2026-07-13 (Paul)** — closes the Codex C11 adversarial review
  (2 BLOCKER, 4 MAJOR, 1 confirm-clean; disposition table in §17). Headline
  changes: §6.1 gains the lock RESOLVER
  (`CapabilityRegistry.transport_lock_for`, transport map with
  `bias_supply → BiasChannel.driver`); §10 rebuilt around per-scan-type
  alignment tables (`/points`, `/voltage_scan`, `/z_focus`) plus
  apply-indexed `event_value`/`event_row` command-event datasets (the RISK-9
  honesty LAW's specified mechanism); `Motion3D` demoted to a non-registered
  helper; multi-channel HV naming specified (`bias.voltage` = primary role,
  `bias.ch{n}.voltage` = physical channel, `HVSource.channel` field) pending
  Kaya's ⚑ ratification; §7.4 rewritten operation-aware with a D4b
  route-table conformance test. Two Codex sub-findings verified already
  clean at f84f1e0 (mid-write review snapshot — see §17). All new claims
  verified against the working tree (`_save_voltage(reading.voltage_V, …)`
  measured vs `/z_focus` commanded; the IV compliance-trip `break` before
  `_save_voltage`; §11.4 items 1–2 landed, item 3 outstanding).

## 17. Review history (v0.1 → Mary S1 → v0.2 → Codex C11 → v0.3)

Mary's S1 taxonomy review of v0.1 (a6d58e0): REQUEST-CHANGES, 12 findings.
Disposition — every finding closed in v0.2, none deferred:

| Finding | Disposition in v0.2 |
|---|---|
| BLOCKER-1 io_lock law wrong for MOTION | §6.1 rewritten: `transport_lock` accessor contract + `is`-identity D1b test; driver work named in §11.4 (GRBL RLock+override, PI gains serialisation) |
| BLOCKER-2 held reservation delays emergency-off | §6.2: LAW — STOP/fail-safe never subject to the reservation; per-command reserve, no holds across `ramp_to`/`wait_until_ready`; prior art cited (`stop()` lock-free, non-blocking `is_alive`) |
| BLOCKER-3 taxonomy hole + non-monotone floor | §7.2: max-hazard LAW + union-routing LAW + domain-split rule + D1 no-spanning test; §7.1 bans `>=`-derived gate sets; §14.1 rewritten — (a) REJECTED (Mary ruling), (c) recommended, (b) alternative; ⚑ stays with Kaya |
| BUG-4 apply() drops HV ramp shaping | §6: `apply(value, *, shaping=…)`; plan-vocabulary keys; missing shaping = driver default, byte-identical; non-shaped capabilities raise |
| BUG-5 slow_control ids violate grammar | §5.1.1: permanent 4-entry alias table (no config rename — user-visible break); validator ERROR on non-conforming/colliding names (§11.4 item 4); registry fails closed |
| BUG-6 device_id overloaded (identity vs lock key) | `transport_id` descriptor field; deadlock ordering sorts by it; `ScopeChannelMonitor` example fixed (`device_id="intensity_monitor"`, `transport_id="scope"`); swept/ attr added |
| BUG-7 ReadableChannel can't describe intensity | §5.4: two ids — `intensity.amplitude` [V] / `intensity.charge` [pC] via `get_amplitude`/`get_charge`; composite `ReadableGroup` declared v2 (§12) |
| RISK-8 pure-data guarantee unenforceable | §4: recursive JSON-safety validation in `__post_init__` (TypeError at construction); sorted-tuple canonical form mandated; MappingProxyType rejected (auto-`__hash__` trap) |
| RISK-9 swept/ loses P0' honesty | §10: rows append at SAVE_POINT; LAW — commanded-but-unsaved sets survive (attempt-indexed trace or explicit attempts dataset); gates DA1 |
| RISK-10 lifecycle vs executor finally | §6: LAW — lifecycle never replaces `_run_plan`'s finally fail-safe; clean finish still runs it; terminal renamed `release \| abort` |
| NIT-11 unbounded generated setter | §7.4: `safety_class >= MOTION` + `limits=None` → control rendered DISABLED |
| NIT-12 v0.1 commit-message honesty debt | §11.1: in-class wavegen sim divergence now recorded + delayed-apply test device named (`SimulatedMotorStage`); §5.3 rewritten to the real symbols (five-key `connect_all` dict vs six-entry `_DISPLAY_TO_SHORT`) |

Codex C11 adversarial review of v0.2 (findings in `docs/CODEX_QUEUE.md` §C11;
Codex noted the working tree changed under him mid-review, and two
sub-findings match an earlier snapshot, not the landed f84f1e0 — each is
dispositioned on disk truth, verified, never assumed):

| Codex finding | Disposition in v0.3 |
|---|---|
| BLOCKER-A `transport_id` split half-done | The genuinely open half closed in §6.1: the lock RESOLVER is now specified (`CapabilityRegistry.transport_lock_for`; transport map over the §11.2 `DeviceManager` attributes; `bias_supply` resolves to `BiasChannel.driver` — the proxies own no lock; build-time `KeyError` fail-closed) + the pass-through example labelled normative + resolver folded into the D1b identity test (§11.4 item 6). The other sub-items — sorted-by-`transport_id` grouping, the §10 `transport_id` attr, the `ScopeChannelMonitor` example — were **already present in landed v0.2** (mid-write snapshot); re-verified: zero residual `device_id`-as-lock statements |
| BLOCKER-B `swept/` loses command events | §10 rebuilt: per-scan-type ALIGNMENT TABLE (`/points`, `/voltage_scan`, `/z_focus` — real shapes from `SCAN_DATA_FORMAT.md`) + `aligned_with` attr; apply-indexed `event_value`/`event_row` datasets on the proven `camera/frame_point_index` dangling-tag pattern, appended at `apply` entry, incrementally — the set-succeeds/acquire-fails case AND the IV compliance-trip case (both verified in `scan_controller.py`) survive in the file; photo-only runs may hold events without point-aligned datasets; settled before DA1 freezes the format |
| MAJOR-C stale `intensity.reading` | **VERIFIED CLEAN at f84f1e0** (mid-write snapshot): zero `intensity.reading` occurrences outside §5.4's negative rationale; §7.3 and §11.1 already carry `intensity.amplitude`/`intensity.charge`. No change needed; recorded so the claim is auditable |
| MAJOR-D `Motion3D` shape without identity | §5/§5.4: `Motion3D` no longer inherits `CapabilityDescriptor` — a non-registered frozen helper with no `capability_id` by construction (its `axes` field violated §4's descriptor field restriction anyway); the registered capabilities are `stage.x/y/z`; `stage.position` REJECTED for v1 (duplicate MOTION hazard path, no consumer), declared v2 (§12); §7.3/§11.1 wording fixed |
| MAJOR-E multi-channel HV cannot be deferred | §14.2 rewritten — naming SPECIFIED (option a): `bias.voltage` = primary-channel ROLE (never a ch0 alias — the primary index is config-chosen), `bias.ch{n}.voltage` = physical channel *n*, physical identity wins the mapping, one shared `transport_id="bias_supply"`; `HVSource.channel` field + `swept/` `channel` attr disambiguate provenance; alternative (b) fail-closed block REJECTED (breaks a runnable plan or writes dishonest provenance); ⚑ retained for Kaya's D1-gate nod |
| MAJOR-F §7.2 vs §7.4 contradict for EMITTING SET | §7.4 rewritten OPERATION-aware: the gate law binds per (capability, operation) via the §7.2 route table; empty route set ⇒ ungated generated control (wavegen `SET` — safe because setters never touch output state; ARMING is the gated operation, stated normatively); RESERVED route ⇒ DISABLED until P3; D4b route-table conformance test required (§11.4 beyond-D1 table) |
| Confirm-clean §5.1.1 alias table | No action — Codex verified the slow-control permanence trap closed; recorded |

Mary's re-review of v0.3 (**RATIFY-READY-WITH-AMENDMENTS**, 2026-07-13): the
taxonomy and contract pass; the ratification-blocking amendments were
mechanical staleness fixes, all applied in this revision:

| Amendment | Disposition |
|---|---|
| §11.4 item 3 + §6.1 misclassify PI serialisation as outstanding | Reclassified **LANDED**: `4a89647` guards every PI GCS exchange on `io_lock` (`transport_lock` returns it — no new dedicated lock), `fbf94d8` disconnect-stops-first, `7a55d03` `stop()` lock-free `#24`; only items 4–7 (validator charset, registry fail-closed, resolver, `ch{n}` publication) remain outstanding |
| §14.1 / §14.2 ⚑ flags + §5.1 pending-nod note | Cleared: Kaya **ratified** §14.1 option (c) ("ich bestätige") and §14.2 multi-channel naming ("ja nick ich ab") 2026-07-13; D1 gate OPEN |

Same-beat sibling: `docs/design/guarded_exchange.md` staleness swept (PI stop →
T2-RT per `7a55d03`; DRS4 → conventionally guarded per `3930f58`).
