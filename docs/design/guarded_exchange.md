# Guarded Exchange — structural transport serialisation for the device layer

**Status:** DESIGN NOTE (v0.1, Paul, 2026-07-13). Nothing here is implemented.
**Pairs with:** `docs/CAPABILITY_MODEL.md` §6.1/§6.2 (transport-lock accessor,
reservation-vs-fail-safe) and the roadmap's **D2 "missing ABCs"** stage
(`docs/ROADMAP_MASTERPLAN.md`, Devices chain D1 → D2 → D4b → D4).
**Question answered (Kaya):** *"Shouldn't there be an abstract motor driver
that wraps every driver, so each stage doesn't have to be serialised
individually?"*

Short answer: yes — but a naive wrapper is dangerous, because the most
important calls in the layer are precisely the ones that must **not** be
wrapped. The design below makes serialisation structural where it belongs and
makes the escape hatch structural too.

---

## 1. The problem: a rule you must remember is a rule that gets forgotten

Transport serialisation today is a **convention**: every driver is supposed to
take its transport lock around each exchange, per its own discipline. The
evidence that conventions decay:

1. **`PIMotorStage` forgot entirely.** Until `4a89647` (2026-07-13) it
   serialised *nothing* — the GUI position poller and the scan thread shared
   one GCS session unguarded. The fix's own test detector, run against the
   pre-fix pattern, reported **61 interleavings / 80 unguarded calls**
   (`tests/test_motor_transport_lock.py`, non-vacuity proof in the commit
   message).
2. **`GRBLMotorStage` remembered — on a private lock nothing could see.** Its
   I/O serialised on `self._lock` while `io_lock` sat idle, so any outside
   caller reserving `motor.io_lock` would have held a lock that guards
   nothing (Mary BLOCKER-1 in the capability spec; also fixed in `4a89647`
   via the `transport_lock` accessor).
3. **`DRS4Oscilloscope` is forgetting right now.** Found while writing this
   note: `oscilloscope_drs4.py::DRS4Oscilloscope.read_channel` performs board
   I/O (`StartDomino`, `TransferWaves`, `GetTime`, `GetWave`) with **zero
   locking** — same class of gap as pre-fix PI, still live on disk. (Flagged
   to Adam as its own fix beat; this note does not fix it.)

And locking is only one of several per-driver remember-rules. A motor
driver's `move_to` must remember, in order: `_require_connected()`,
`_require_homed()`, `_check_limits()` (frame-correct), per-exchange locking,
and the fail-safe halt on error. A bias backend's `set_voltage` must remember
`check_voltage_in_range()` ("Every setpoint path must go through this" —
`bias_supply_base.py` docstring: a sentence, not a structure). Both motor
drivers duplicate the un-homed `zero_position` warning verbatim. Every one of
these is a `PIMotorStage`-shaped accident waiting for driver #4.

### The precedents that prove base-owned invariants work here

The codebase already does this — partially:

- **`SoftwareLimits.check`** lives centrally in `devices/motor_base.py`
  (invoked via `MotorStageBase._check_limits`). The *invariant* is central;
  only the *invocation* is still conventional (each driver's `move_to` must
  remember to call it). No driver has ever shipped a wrong limits check —
  because the code lives in one place.
- **`BiasSupplyBase.ramp_to` / `_ramp_channel`** are full template methods
  already: base-owned composites over abstract primitives (`set_voltage`,
  `enable_output`), carrying the never-energise-to-ramp-to-zero SAFETY rule
  once, for every backend.
- **`SlowControlChannel.read_with_status`** wraps the abstract `read()` with
  alarm evaluation and error containment — base-owned, driver supplies the
  primitive.
- **`MotorStageBase.wait_until_ready`** is a base-owned sliced poll loop over
  the abstract `is_moving()`.

Guarded exchange is not a new idea for this layer — it is **finishing** this
pattern: move the invocation of the invariants (and the lock) into the base,
so a driver physically cannot forget them because it never owns them.

---

## 2. The pattern: template method with tiered exchange semantics

**Core shape.** The ABC owns the PUBLIC method and it is *effectively final*
(Python enforcement in §5, Stage G4). The driver implements a protected
`_do_*` primitive that performs the raw exchange. The base:

1. applies the layer's gates (connected / homed / limits / range — whatever
   that family's invariants are),
2. acquires the transport lock **according to the method's tier** (below),
3. calls the primitive,
4. handles post-state (fail-safe halt on error, state bookkeeping, logging).

A converted driver never touches its lock for normal traffic. It cannot
forget to lock, because it never owned the lock.

**The hard part is the escape hatch.** A naive "wrap everything in the lock"
base is *worse* than today's convention, because the deliberate lock-avoiders
are load-bearing safety behaviour:

- `GRBLMotorStage.stop()` is deliberately lock-free — the real-time byte
  (0x85 jog-cancel / Marlin `M410`) goes straight to the port. A locked stop
  queues behind the very move it must interrupt (its in-code comment; pinned
  by `test_stop_is_not_queued_behind_a_held_transport_lock`).
- `BaseDevice.is_alive` must "never block on the io_lock"; the scope, wavegen
  and camera implement it with `io_lock.acquire(blocking=False)`.
- `PIMotorStage.stop()` does a bounded 0.25 s acquire, then sends `STP`
  regardless — because PI's real-time semantics are not established
  (`TODO(manual needed)` on the class; researcher dispatched).
- `BiasSupplyBase.ramp_to` releases the lock **between steps**, which is the
  only reason an ALL-OFF can interleave mid-ramp (Mary BLOCKER-2 /
  CAPABILITY_MODEL §6.2).

So the base must own not one behaviour but **four**, and drivers must declare
which tier each primitive belongs to. The tiers are the design.

---

## 3. The exchange tiers

### T1 — Guarded exchange (the default)

One command/query (or query+reply pair) on the transport. The base takes
`self.transport_lock` around exactly this primitive and releases it before
returning. All gates run before the acquire (limits math and range checks
need no lock; never hold the transport while doing pure computation or —
ever — user interaction).

- Examples: `get_position` → `_do_read_position`; `set_voltage` →
  `_do_set_voltage`; every scope/wavegen/camera setter.
- **T1g — atomic group** (variant): a short, bounded multi-exchange sequence
  that must be indivisible. Precedent: `IsegBiasSupply.set_polarity_ch` holds
  `io_lock` across status-check → confirm → relay-switch so no other thread
  can energise the output between the check and the throw. Allowed because
  it is short and bounded; **never** allowed around a ramp or motion wait
  (that is T4's law). The base provides this as an explicit
  `with self.transport_lock:` block inside a base-owned method — the same
  thing CAPABILITY_MODEL §6 calls "one short atomic multi-set".

### T2 — Escape (stop / abort / fail-safe)

**LAW: no lock, no reservation, and no gate may ever stand between the
operator and a stop.** No blocking acquire, no `_require_connected` that
raises (stop on a disconnected device is a silent no-op, never an
exception), no danger-gate re-check, and — restating CAPABILITY_MODEL §6.2 —
never subject to a capability reservation. A T2 path also never raises: it
swallows and logs (it *is* the cleanup path).

Two sub-forms, because hardware differs:

- **T2-RT — real-time, out-of-band.** The transport has a primitive the
  controller acts on regardless of in-band traffic. The base calls
  `_do_stop_realtime()` with **no acquire at all**. Driver primitives:
  GRBL 0x85 (jog-cancel) / Marlin `M410` raw port writes — existing, proven.
- **T2-B — bounded escape, in-band.** The protocol has no established
  real-time primitive; the stop is an ordinary command on the shared session.
  The base does `transport_lock.acquire(timeout=T2_BOUND)`, then sends the
  primitive **regardless of whether the acquire succeeded**, releasing only
  if it acquired. Rationale (unchanged from `4a89647`): the worst case of an
  unguarded send is a garbled in-flight exchange, which surfaces as
  `DeviceError` and fails safe; the worst case of a *queued* stop is a crash.
  **Never invert that trade.** Driver primitives: an HV output-off write
  (§4.2 discusses whether HV needs T2 at all today).
  *(Update 2026-07-13 late: PI was UPGRADED from T2-B to T2-RT — the manual
  research (`docs/research/pi_gcs_stop_semantics.md`) established that the
  single-character `#24`/`StopAll()` IS a real-time primitive and that
  pipython's message layer serialises per exchange internally; `stop()` is
  now fully lock-free per commit `7a55d03`, and
  `PIMotorStage._STOP_LOCK_TIMEOUT_S` no longer exists. T2-B currently has
  NO live occupant — it stays defined for future in-band-only devices,
  e.g. if the iseg emergency-off turns out to have no out-of-band form.)*

**How the base enforces "a stop never takes the lock".** Three layers,
honestly ranked:

1. *Shape*: the base-owned public `stop()` contains no blocking acquire —
   a driver cannot add one to the public path because it does not own the
   public path.
2. *Refusal*: the base's T1 helper (`_guarded_exchange`, §5) logs a loud
   ERROR and refuses if invoked from within a T2 call (a re-entrancy flag on
   the instance, same-thread only) — a driver whose `_do_stop_*` primitive
   calls back into guarded machinery is a bug the base makes *loud*.
3. *Test*: the per-driver contract test (the `4a89647` template) holds
   `transport_lock` in a foreign thread and asserts `stop()` completes < 1 s
   AND the stop primitive demonstrably went out (recorder fake), lock not
   held (T2-RT) or held-only-if-free (T2-B). A primitive that internally
   grabs some *other* private lock can defeat layers 1–2; layer 3 is why the
   contract test is mandatory for every conversion, not optional.

Related teardown rule: `disconnect()` is a T2-B *composite* — stop first
(GRBL already does; PI's missing stop-on-disconnect is flagged in `4a89647`
as its own beat), then close the session under a bounded acquire (PI's
`disconnect` already does exactly this).

### T3 — Non-contending probe

Liveness/health polls that must never block: `acquire(blocking=False)`; if
the transport is busy, report from the last known state ("mid-conversation ⇒
presumed alive") and return immediately. Existing implementations —
`Oscilloscope.is_alive`, `WaveformGenerator.is_alive`,
`BlackflyCamera.is_alive` — already have exactly this shape; the base
provides it once as `_probe_exchange(_do_probe)` and the three drivers'
copies collapse into primitives.

### T4 — Sliced composite (yes, the fourth tier is needed)

**LAW: never hold the transport across a multi-step motion/ramp/settle
loop — slice it.** A composite operation (move-and-wait, ramp, homing) is a
base-owned *sequence* of T1 exchanges with the lock released between
iterations; the base owns the loop, the driver owns the per-iteration
primitive.

- This law already saved us twice: `BiasSupplyBase.ramp_to` releases the lock
  between steps, so ALL-OFF interleaves mid-ramp within ~one step delay —
  Mary caught exactly the held-across-the-ramp inversion in the capability
  spec (§6.2); and `PIMotorStage._wait_on_target` polls per-exchange so the
  position display keeps updating during a 60 s move (the `4a89647` rework;
  pinned by `test_position_poll_is_not_starved_by_a_move`).
- Base shapes: `move_to` = gates → `_do_issue_move(target)` (T1) →
  `_wait_motion_done()` (base loop over `_do_poll_motion()` T1 exchanges,
  with sleep between); `ramp_to` stays exactly the template it already is,
  with each `set_voltage` step now a base-guarded T1.

**Documented exception — the monolithic hold.** Some operations cannot be
sliced:

- `PIMotorStage.home()` runs `pitools.startup()`, which owns its own poll
  loop inside pipython and therefore holds the transport for the entire
  referencing move (the position display freezes; accepted in `4a89647`
  because stop remains reachable via T2-B fall-through).
- `GRBLMotorStage.home()`'s `_send_wait("$H", timeout=120.0)` holds
  `self._lock` until GRBL's `ok` — also a monolithic hold in practice.
  TODO(bench): confirm on the real GRBL board what `stop()`'s 0x85 does to an
  in-progress `$H` homing cycle (jog-cancel may not abort homing; a soft
  reset 0x18 might be required — do not change the stop primitive without
  the manual/bench answer).

A monolithic hold is allowed only when (a) the vendor call cannot be sliced,
(b) the driver's stop tier remains reachable while it runs (T2 property),
and (c) it is marked `# MONOLITHIC HOLD` at the call site and named in the
driver docstring. The base cannot make pipython cooperative; it can force
the exception to be explicit instead of ambient.

---

## 4. Per-device mapping (verified against the code on disk)

Method names below were read from the actual files; none are invented.

### 4.1 Motors — `MotorStageBase` (GRBL, PI, Simulated)

| Public method (base-owned) | Tier | Driver primitive | Base-applied gates |
|---|---|---|---|
| `get_position` | T1 | `_do_read_position() -> Position` | connected |
| `is_moving` | T1 | `_do_poll_motion() -> MotionPoll` | none (False when disconnected) |
| `at_limit_switch` | T1 (T1g on PI: 3-axis sweep) | `_do_read_limit_switches()` | connected |
| `move_to` | T4 | `_do_issue_move(Position)` + `_do_poll_motion()` | connected, homed, **user-frame limits via `limits_user_frame()`**; fail-safe halt (base calls `stop()`) on error |
| `move_relative` | T4 | same primitives | same |
| `home` | T4 / monolithic (both drivers today) | `_do_home(axes)` | connected; sets `_homed` on success only; fail-safe halt on error |
| `stop` | **T2** (GRBL: T2-RT 0x85/M410; PI: T2-B `STP`; Sim: flag) | `_do_stop_realtime()` | **none — LAW** |
| `zero_position` | T1 | `_do_zero_position()` | connected; the un-homed warning moves to the base (currently duplicated in both drivers) |
| `test_connection` | T1/T1g | `_do_identify() -> str` | none (returns strings, never raises to GUI) |
| `wait_until_ready` | T4 | loops `is_moving` (already base-owned) | — |
| `limits_user_frame`, `move_to_center` | pure/composite of `move_to` | stay concrete, no lock of their own | — |

**Frame subtlety (GRBL):** the base gate checks the *user-frame* target
against `limits_user_frame()` (documented equivalent envelope: a user
coordinate passes iff its machine coordinate is inside `self.limits`). A
driver that transforms the target (GRBL's user→machine conversion + full-step
snapping) MUST re-check the final machine-frame target inside
`_do_issue_move` — GRBL's `move_to`/`move_relative` already do exactly this
post-snap check, and it stays driver-internal. Two checks, one authoritative
envelope; the base check can never be *more* permissive than the driver's.

**GRBL poll interpretation:** `_grbl_wait_idle`'s alarm/hold/door handling
and the stall guard are GRBL-specific readings of the poll. The
`MotionPoll` result type therefore carries `done | fault:str|None |
position:Position|None`, the base loop handles timeout + generic fault →
fail-safe halt, and the dialect-specific interpretation lives inside
`_do_poll_motion`. (Alternative — driver overrides the whole wait loop — is
rejected: that reopens the "forgot to slice" hole.)

### 4.2 Bias supplies — `BiasSupplyBase` (iseg, Keithley, e4control, Simulated; `BiasChannel` proxy untouched)

| Public method | Tier | Driver primitive | Base-applied gates |
|---|---|---|---|
| `set_voltage` / `set_voltage_ch` | T1 | `_do_set_voltage(ch, V)` | connected, **`check_voltage_in_range`** (invocation becomes structural — today each backend must remember it) |
| `set_compliance` / `_ch` | T1 | `_do_set_compliance(ch, A)` | connected |
| `enable_output` / `output_on_ch` | T1 | `_do_enable_output(ch)` | connected; **danger confirmation stays at the caller/GUI** (layering; never hold a lock across user interaction) |
| `output_off` / `output_off_ch` | T1 today; T2-B candidate (below) | `_do_output_off(ch)` | connected; the keep-`_output_on`-truthful-on-failure contract (df10f8e) enforced in the base |
| `read` / `read_ch` | T1 | `_do_read(ch) -> BiasReading` | connected |
| `ramp_to` / `ramp_to_ch` / `_ramp_channel` | **T4** — already the base's template; unchanged shape, steps become base-guarded T1 | existing primitives | LAW: lock per step, never across the loop (§6.2 precedent) |
| `set_polarity` / `_ch` | **T1g atomic group** | `_do_set_polarity(ch, p)` + status primitives | off-and-discharged verification stays inside the group (iseg's gated sequence is the model) |
| `get_polarity`, `supports_polarity_switch`, `channel_count` | T1 | `_do_*` | — |
| `is_output_on`, `setpoint_V`, `compliance_A` | pure properties, no I/O, no lock | — | — |

**Does HV need a T2 escape?** Today: **no held path exceeds one exchange** on
a bias transport — `ramp_to` slices, every backend exchange has an I/O
timeout — so a blocking `output_off` waits at most ~one exchange timeout.
That is why the current fail-safe chain (ALARM handler, EMERGENCY-OFF,
ALL-OFF, scan abort, shutdown → ramp-to-0 + output_off) is acceptable as T1.
The design *reserves* T2-B for HV (`emergency_off()` on the base: bounded
acquire, `_do_output_off` regardless, never raise) but **defers it**:
introducing it is a driver-contract change the capability spine's `abort()`
would want to route through, and a dedicated iseg hardware emergency
primitive must come from the SHR/NHR manual — `TODO(manual needed): iseg
SCPI — is there an emergency-off command distinct from :VOLT OFF, is it
acted on with a reply outstanding, and what latches afterwards?` Nothing is
invented here.

### 4.3 Oscilloscope — `Oscilloscope` (VISA), `DRS4Oscilloscope`, `TekFastFrame` — **fold into D2**

These are concrete classes without an ABC; D2 ("missing ABCs:
Scope/Camera/Wavegen extracted from concrete drivers") is where their base is
born. **Write the D2 ABC guarded from birth** instead of retrofitting first.

- T1: `acquire`, `read_channel`, `set_channel_scale`, `set_channel_position`,
  `set_probe_attenuation`, `set_coupling`, `set_bandwidth_limit`,
  `set_timebase`, `set_channel_display`, `set_averaging`, `read_settings`,
  `configure_tct_trigger`, `test_connection` → `_do_*` (the VISA driver
  already locks every one of these; DRS4 locks **none** — the live gap).
- T1g: `_recover_session` (device clear + drain — a control-transfer group,
  already held under `io_lock` re-entrantly).
- T2: none — a passive digitiser has nothing to stop; honesty: do not
  manufacture an escape tier where no hazard exists.
- T3: `is_alive` (already non-contending in the VISA driver).
- T4: DRS4 `read_channel`'s n_averages trigger-wait loop should slice per
  acquisition (lock per `StartDomino`→`TransferWaves` cycle), so a scan-time
  multi-average read cannot starve a concurrent settings change.

### 4.4 Waveform generator — `WaveformGenerator` — fold into D2

- T1: `set_frequency`, `set_pulse_width`, `set_duty_cycle`, `set_amplitude`,
  `set_offset`, `set_levels`, `set_output_load`, `output_on`, `burst`,
  `test_connection`, `_resolve_output_state` → `_do_*` via the existing
  `_write`/`_query` helpers (already locked).
- `output_off` is the laser-trigger kill: same analysis as HV §4.2 — T1 is
  acceptable today (short exchanges only), T2-B reserved.
- T3: `is_alive` (already non-contending).

### 4.5 Camera — `BlackflyCamera` — fold into D2

- T1: every setter (`set_exposure` … `set_trigger`), `get_temperature`,
  `get_fps_actual`, `get_camera_info`, `get_roi`, `capture_background`,
  `clear_background` → `_do_*` (all already locked).
- `get_frame` / `get_frame_with_meta`: a single SDK grab bounded by the grab
  timeout — an accepted single-exchange hold (T1), noted, not T4.
- T2: none (nothing moves, nothing is energised). Teardown
  (`_release_hw`) follows the disconnect composite rule.
- T3: `is_alive` (already non-contending).

### 4.6 Slow control & intensity — `SlowControlChannel`, `IntensityMonitorBase`

- T1: `read` → `_do_read`; `read_with_status` stays the base template it
  already is. Intensity: `read`, `set_scale`, `get_amplitude`, `get_charge`
  → `_do_*`.
- **Pass-through devices**: `ScopeChannelMonitor` owns no transport — its
  real lock is the scope's (CAPABILITY_MODEL §6.1's worked
  `transport_id="scope"` example). Its `_do_*` primitives call the *scope's
  public guarded methods*; the monitor's own base-held lock is honest but
  vacuous (it serialises monitor-local state only). The design keeps the
  base uniform rather than special-casing; the spine's `transport_id` handles
  the real reservation routing.
- `laser_manual.py` is metadata-only (no transport, not a `BaseDevice`
  driver) — out of scope. `BiasChannel` performs no I/O of its own and
  inherits everything through the shared driver — no change.

---

## 5. Base sketch (shape, not final code)

```python
# devices/base.py — additions (Stage G0)
class BaseDevice(ABC):
    _T2_BOUND_S = 0.25        # bounded-escape acquire budget

    def _guarded_exchange(self, fn, *a, **kw):
        """T1: one exchange under transport_lock. Refuses (ERROR log) if
        called from inside a T2 escape on the same thread."""
        with self.transport_lock:
            return fn(*a, **kw)

    def _probe_exchange(self, fn, *, busy_result):
        """T3: try-acquire; on contention return busy_result immediately."""
        if not self.transport_lock.acquire(blocking=False):
            return busy_result
        try:
            return fn()
        finally:
            self.transport_lock.release()

    def _escape_exchange(self, fn, *, realtime: bool):
        """T2: never blocking-acquire, never raise. realtime=True → no
        acquire at all; False → bounded acquire, send regardless."""
        ...

    def __init_subclass__(cls, **kw):   # Stage G0: warn; Stage G4: raise
        ...  # detect overrides of base-owned public methods per family
```

```python
# devices/motor_base.py — the template (Stage G1), abridged
class MotorStageBase(BaseDevice):
    def move_to(self, x_mm, y_mm, z_mm) -> None:          # base-owned, final
        self._require_connected(); self._require_homed()
        lim = self.limits_user_frame()
        if lim is not None:
            lim.check(Position(x_mm, y_mm, z_mm))          # structural now
        try:
            self._guarded_exchange(self._do_issue_move, Position(x_mm, y_mm, z_mm))
            self._wait_motion_done()                       # T4 sliced loop
        except Exception:
            self._fail_safe_halt("move_to")                # calls stop() (T2)
            raise

    def stop(self) -> None:                                # base-owned, final
        # LAW: no lock, no gate, no raise.
        self._escape_exchange(self._do_stop_realtime,
                              realtime=self._STOP_IS_REALTIME)

    @abstractmethod                                        # end-state only —
    def _do_issue_move(self, target: Position) -> None: ...  # see §6 staging
```

Converted-driver internals: GRBL's `_send`/`_send_wait`/`_grbl_status` keep
their internal `with self._lock:` — under the base's re-entrant hold they
re-acquire harmlessly on the same thread, so conversion does not require
rewriting the helper layer in the same beat.

---

## 6. Migration — non-breaking, one driver per beat

**The load-bearing Python fact:** when the ABC gains a concrete public
`move_to`, an *unconverted* driver's own `move_to` override simply wins by
MRO — unconverted drivers keep working with **zero change**. Conversion of a
driver = delete its public override, rename the body to `_do_*` primitives.
The app runs simulated at every stage.

Rejected alternative (from the brief): a default `_do_*` that delegates back
to the driver's current public method. Pointless-to-dangerous — while the
public override exists the base template never runs, and the moment the
override is deleted the delegation recurses into the base's own public
method. The default `_do_*` instead raises
`DeviceError("driver not yet converted to guarded exchange")`; it is promoted
to `@abstractmethod` only in G4 (adding `@abstractmethod` earlier would make
every unconverted concrete driver un-instantiable — a hard break).

**Stages:**

- **G0 — base machinery (S).** `_guarded_exchange` / `_probe_exchange` /
  `_escape_exchange` in `devices/base.py`; `__init_subclass__` override
  detector in **WARNING** mode. No driver changes; suite must be green
  unchanged.
- **G1 — motors (the family with real gates and real stakes).** Order:
  `motor_simulated.py` (S — proves the template), `motor_pi.py` (M — already
  per-exchange clean after `4a89647`), `motor_grbl.py` (L — dialect split,
  snap/frame transform, stall guard, and `tests/test_motor_grbl_mock.py`
  exercises private internals). One driver per beat, contract test each.
- **G2 — bias supplies, BEFORE roadmap D3.** `bias_supply_base.py` (M,
  channel-aware doubling) then iseg (M), keithley (S), e4control (S/M),
  simulated (S — **file currently locked by another beat; sequence after**).
  Payoff: every D3 driver (K2614/HMP4040/JULABO…) is *born* unable to forget.
- **G3 — inside D2, not before it.** Scope/wavegen/camera get their ABCs in
  D2; write those ABCs guarded-from-birth (S each, incremental on D2's M).
  Retrofitting the concrete classes pre-D2 would churn the same methods
  twice. Exception: DRS4's unguarded `read_channel` is a live bug and gets a
  *conventional* lock fix in its own beat now, structural conversion at D2.
- **G4 — flip the detector.** Per family, once every in-tree backend is
  converted: `__init_subclass__` WARNING → raise, and `_do_*` defaults →
  `@abstractmethod`. From this point a new driver that overrides a public
  guarded method fails at class-definition time — the "effectively final"
  becomes real.

**The test that proves each conversion** (template =
`tests/test_motor_transport_lock.py`, `4a89647`):

1. A fake transport that records lock ownership at every write/call
   (`LockWatchingSerial` / `FakeGCS` pattern): all T1 traffic lock-held, zero
   unguarded calls, zero cross-thread interleavings under a poller+mover
   hammer.
2. **Non-vacuity:** the same detector run against a deliberately unconverted
   stand-in (a subclass restoring the old public-override pattern) must
   report violations — pre-fix PI scored 61/80; a detector that cannot fail
   proves nothing.
3. Stop-under-held-lock: foreign thread holds `transport_lock`; `stop()`
   completes < 1 s and the primitive demonstrably went out (lock-free for
   T2-RT; unguarded-after-bound for T2-B).
4. Re-entrancy: a holder of `transport_lock` can call every guarded method.
5. Poller-not-starved: position/read polls progress while a T4 composite
   runs.

---

## 7. Interaction with the capability spine (CAPABILITY_MODEL v0.2)

- **Reservation composes with the guarded base — verified.** §6.1's
  reservation unit is the `transport_lock` accessor; the base's guarded
  methods acquire *the same object*. `BaseDevice.io_lock` is an `RLock` by
  construction (`base.py` line 18) and GRBL's `_lock` became an `RLock` in
  `4a89647` precisely so a holder can call driver methods that lock again —
  pinned by `test_transport_lock_is_reentrant` (both drivers). So a
  `CapabilityBinding` holding its per-exchange reservation calls guarded
  public methods and re-enters cleanly on the same thread, while excluding
  every other thread — exactly the §6.1 semantics.
- **Identity becomes true by construction — but stays tested.** Because the
  base acquires via the `transport_lock` *accessor* (not a private name), a
  converted driver's I/O lock IS the reservation lock automatically —
  Mary BLOCKER-1 (a lock nothing acquires) cannot recur for converted
  drivers. The §6.1 D1b `is`-identity tests stay: a primitive that grows a
  second private lock or session can still lie, and only the behavioural
  recorder catches that.
- **Restated invariant the spine depends on: a reservation can never make a
  device unstoppable.** T2 never blocking-acquires the lock the reservation
  holds; `abort()`/STOP/fail-safe are never subject to the reservation
  (§6.2 LAW, unchanged). T4's slicing keeps `ramp_to` interruptible
  mid-ramp, which is what makes the spine's per-exchange reservation rule
  honest rather than aspirational.
- **§11.1 "zero ABC signature changes" is unaffected.** Guarded exchange
  changes who *implements* `move_to`/`ramp_to`/`read_channel`, not their
  names or signatures — the adapter table's driver symbols
  (`MotorStageBase.move_to`, `BiasChannel.ramp_to`,
  `Oscilloscope.read_channel`, …) resolve unchanged. No D1 rework.
- **File-contention note:** D1a (`capabilities/model.py`) and D1b
  (adapters/registry) do not edit `devices/*`, so G0/G1 can run in parallel
  with D1 without lock conflicts. The *conceptual* dependency is the other
  way: G2 before D3, G3 inside D2.

---

## 8. What this pattern does NOT fix (honesty section)

1. **Vendor-internal poll loops stay monolithic.** `pitools.startup()` owns
   its loop inside pipython; the base cannot slice it. PI homing keeps
   freezing the position display for the whole referencing move. The pattern
   only forces the exception to be declared (`# MONOLITHIC HOLD`), not gone.
2. **It cannot invent a real-time stop where hardware has none.** PI stays
   T2-B until the GCS manual answers the three `TODO(manual needed)`
   questions; SCPI HV supplies have no established out-of-band primitive
   (manual question, §4.2). Tier labels describe reality; they do not
   improve it.
3. **A primitive can still subvert it.** `_do_*` code that opens a second
   session, takes a private lock, or performs I/O outside the primitives is
   invisible to the base. The change is from "must remember to lock" to
   "must not actively bypass" — a much smaller bug class, caught only by the
   mandatory recorder tests (which is why they are mandatory).
4. **Danger confirmation stays at the caller.** HV enable, polarity, homing,
   scan start remain GUI/CLI-gated explicit actions (safety rule 2); the
   base never adds interactive confirmation (and never holds a lock across
   one).
5. **Cross-device composition is out of scope.** Ordering, grouped
   reservations, deadlock-avoidance across transports — that is the spine's
   §6.1 job, unchanged.
6. **The migration window has a hole by design.** Until G4 flips per family,
   a new out-of-tree driver can still override public methods (it gets a
   WARNING, not an error). The window is the price of non-breaking staging;
   G4 closes it.
7. **Driver-specific frame/dialect correctness stays driver work.** GRBL's
   post-snap machine-frame recheck, Marlin's M114 retry protocol, iseg's
   status decoding — the base guards *that* an exchange is serialised and
   gated, not *what* the driver says on the wire.

## 9. Cost (honest)

Churn class: public method bodies move/rename to `_do_*` across `devices/`,
and driver tests that call internals follow.

| Item | Effort | Notes |
|---|---|---|
| G0 `devices/base.py` helpers + detector | **S** | additive only |
| `motor_base.py` templates + MotionPoll | **M** | the real design work |
| `motor_simulated.py` | **S** | also hosts the template's first tests |
| `motor_pi.py` | **M** | already per-exchange clean |
| `motor_grbl.py` | **L** | dialect split, snap/frame, stall guard; `tests/test_motor_grbl_mock.py` (~17+ tests) touches internals |
| `bias_supply_base.py` | **M** | zero-arg + `*_ch` surfaces |
| `bias_supply_iseg.py` | **M** | locking already central in `_write`/`_query` — mostly mechanical |
| `bias_supply_keithley.py` / `_e4control.py` / `_simulated.py` | **S / S–M / S** | simulated currently beat-locked |
| slow-control + intensity family | **S** | `read_with_status` already template |
| D2-born ABCs (scope/wavegen/camera) | **S each, incremental** | on top of D2's own M |
| DRS4 conventional lock hotfix (now) | **S** | separate beat, not this design |

Total: two L/M-heavy beats (GRBL, bias family) plus ~6–8 S/M beats ≈ a
multi-wave track, comfortably parallel to D1. Placement: **G0 anytime; G1
after the current transport-lock/PI-disconnect follow-ups settle; G2 before
D3; G3 inside D2.** Not on the seed critical path and should not block it.

## 10. Recommendation

**Do it — staged, not big-bang, and not everywhere at once.**

- **Do now (G0):** the base tier helpers + override detector (S, additive,
  zero behaviour change) and the DRS4 conventional lock hotfix (separate
  beat — it is a live bug regardless of this design).
- **Do as a track (G1, G2):** motors and bias supplies — the two families
  with genuine safety gates that are currently conventions
  (`_require_homed`, limits, `check_voltage_in_range`), and the two with a
  proven forgetting record. G2 lands before D3 so the e4control expansion
  drivers are born structural.
- **Fold, don't retrofit (G3):** scope/wavegen/camera become guarded when D2
  gives them ABCs anyway — near-zero marginal cost, no double churn.

Why not "don't"? The alternative to structural enforcement is what we have:
a convention plus a per-driver contract test that someone must remember to
*write*. `4a89647`'s test template is excellent, but it exists for exactly
two drivers because a specific bug forced it — DRS4 shows the next
forgetting had already happened before the ink dried. If Kaya prefers to
defer the full template anyway, the minimum honest fallback is: (a) G0's
detector in WARNING mode (it costs an afternoon and names every unconverted
public override at import time), (b) the recorder-test template promoted to
a required checklist item for every new driver in `docs/ARCHITECTURE.md`'s
devices section, and (c) the DRS4 hotfix regardless. But the fallback still
relies on remembering — the recommendation is the structure.
