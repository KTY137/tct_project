# PI GCS stop / on-target semantics for `motor_pi.py`

- **Date:** 2026-07-13
- **Requested by:** Adam (safety fix follow-up to commit 4a89647 — replace the
  bounded-lock `STP` compromise in `PIMotorStage.stop()` and harden
  `_wait_on_target()`).
- **Hardware in scope:** PI **C-663 Mercury Step** (stepper, single-axis
  daisy-chain) driving **L-836** stages; **C-884** sibling; **pipython** (PI's
  official Python wrapper over GCS 2.0). GCS 2.0 command layer is shared across
  these controllers, so command-layer facts below apply to all three.
- **Exact questions:** (1) Is `STP` real-time/immediate? (2) Is the single-char
  `#24` stop the correct e-stop primitive, and how do `STP`/`HLT`/`#24` differ?
  (3) Post-stop error latch + how to clear it. (4) Is there an `IsMoving`
  false-"on-target" race, and what is the correct wait sequence?

---

## TL;DR for Paul

1. **The emergency-stop primitive is the single-character `#24` (0x18), not the
   `STP` mnemonic.** In pipython that is `GCSDevice.StopAll()` /
   `pitools.stopall(gcs)`. `#24` is a one-byte, non-LF-terminated fast command;
   `STP` is a normal LF-terminated command line. Use `#24`.
2. **`stop()` can drop the 0.25 s bounded lock and become effectively lock-free.**
   pipython's message layer already serialises every exchange with its *own*
   internal lock that is released between polls (even during `home()`), so a
   `StopAll()` from another thread waits at most one in-flight exchange (~ms),
   never the whole move — the exact property the driver's io_lock was standing in
   for. Send `StopAll(noraise=True)` **without** taking `io_lock`.
3. **After any stop the controller latches GCS error 10** ("Controller was
   stopped by command"). `StopAll(noraise=True)` / `pitools.stopall()` read-and-
   mask it for you, so the next command does not inherit it. Do **not** let the
   stop path re-raise.
4. **The correct on-target signal is target-relative (`qONT` for closed-loop,
   `qOSN` steps-left for open-loop), not raw `IsMoving`.** Use PI's own
   `pitools.ontarget(gcs, ids)` per poll — it picks the right signal from the
   servo state and is immune to the "polled not-moving before the move started"
   race, because `qONT`/`qOSN` are defined against the *new* commanded target.

---

## Q1 — Is `STP` real-time / immediate?

**Answer: the `STP` *mnemonic* is NOT guaranteed real-time; the single-character
`#24` IS the immediate stop. Confidence: HIGH on the mechanism, but the exact
"executed the instant the byte arrives, mid-command" wording was not found
verbatim — see uncertainty.**

GCS 2.0 has two command shapes (PI E-727 manual, "GCS Syntax for Syntax Version
2.0", notation section):

- **Mnemonic commands** — three-letter (`STP`, `HLT`, `MOV`, …), *space-separated
  args, terminated with LF*. Parsed as a full command line.
- **Single-character commands** — one ASCII byte written `#<decimal>` (e.g.
  `#24`, `#5`, `#7`). The manual states verbatim: *"Single-character commands are
  not followed by a termination character."* (E-727 manual p.179). Because there
  is no terminator to wait for, the byte is actionable the moment it is received.

Convergent evidence that `#24` preempts an in-flight/long-running command
(i.e. behaves like GRBL's real-time 0x85), rather than queueing:

- pipython uses the single-char **`#5` (`IsMoving`)** and **`#7`
  (`IsControllerReady`)** specifically to poll *while the controller is executing
  a long-lasting command*. `pitools.waitonready` exists precisely because
  *mnemonic* commands are not answered during long operations but the single-char
  fast commands are — establishing that single-char commands are serviced
  out-of-band from the mnemonic command flow. (pipython `gcscommands.py`
  `IsMoving`→`chr(5)`, `IsControllerReady`→`chr(7)`; `pitools.waitonready`.)
- PI Mercury GCS Commands manual (C-663/C-863 family) and multiple PI manuals:
  *"moves can be interrupted by `#24`"*, and *"when stopping … with the `#24`,
  `STP` or `HLT` commands, the target position is set to the current position."*
- Third-party PI driver (delmic/odemis `pigcs.py`) sends `"\x18"` (= `#24`) for
  its `Stop()` and comments it as an *"immediate stop"*.

**Practical consequence:** the driver does not need `STP` at all for the e-stop;
switch to `#24` (`StopAll`). And because `#24` is immediate and pipython
serialises the wire internally (Q-lock discussion below), the stop no longer
needs the driver's `io_lock` — it becomes the GRBL-0x85-shaped lock-free stop the
class comment wanted.

### Why the io_lock can go away (the load-bearing detail)

pipython's `gcsmessages.py` `send()`/`read()` each do
`with self.__lock: __send(...); __checkerror(...)` — i.e. **pipython holds its own
lock for the duration of one exchange only, and releases it between exchanges.**
Nothing in pipython (nor in this driver's `_wait_on_target`, nor in
`pitools.startup`'s internal poll loops) holds that lock across a whole move —
every poll is a separate lock/unlock. Therefore a `StopAll()` issued from the
GUI/abort thread blocks at most one in-flight exchange (~ms) before its `#24`
byte goes out, during a `move_to` **or** a `home()`. The driver's `io_lock` was a
coarser second lock whose only long hold is `home()` wrapping `pitools.startup`;
keeping `stop()` off `io_lock` removes the one case (`home()`) where the current
bounded-acquire could time out and fall through unguarded.

---

## Q2 — `STP` vs `HLT` vs `#24`; which is the e-stop primitive?

**Answer: `#24` (pipython `GCSDevice.StopAll()`), abrupt, all axes. Confidence:
HIGH (PI's own pipython source + manuals).**

| Command | pipython call | Byte(s) on wire | Scope | Deceleration | Sets ERR 10 |
|---|---|---|---|---|---|
| `#24` | `GCSDevice.StopAll()` / `pitools.stopall(gcs)` | `chr(24)` (0x18) | **all axes** | **abrupt** | yes |
| `STP` | `GCSDevice.STP()` | `"STP\n"` | all axes | abrupt | yes |
| `HLT` | `GCSDevice.HLT(axes)` | `"HLT …\n"` | **given axes** | **smooth (decel ramp)** | yes |

Verbatim (pipython `gcscommands.py`):
- `STP` docstring: *"Stop all axes **abruptly**. Stop all motion caused by move
  commands (MOV, MVR, GOH, STE, SVA, SVR), referencing commands (FNL, FPL, FRF),
  macros, wave generator output and by the autozero procedure…"*
- `StopAll` docstring: *"Stop all axes **abruptly by sending `#24`**. Stop all
  motion caused by move commands…"* — code: `self.__msgs.send(chr(24))`.
- `HLT` docstring: *"**Halt** the motion of given 'axes' **smoothly**. Error code
  10 is set."*

**PI's e-stop designation:** the abrupt `#24`/`StopAll` (all axes, immediate) is
the emergency stop; `HLT` is a *soft* stop (decelerated, per-axis) and is not the
e-stop. `STP` is the mnemonic equivalent of `#24` but, being an LF-terminated
command line, does not carry the "immediate/preempting" property that makes `#24`
the right choice for a safety stop. pipython's own convenience helper is
`pitools.stopall(gcs)`, which calls `StopAll()` and masks error 10 — i.e. PI
packages exactly this as the "stop everything now" primitive.

> Note there is an even harder command, **`#27` (ESC)**, described in some PI
> manuals as a full-system abort that *resets servo registers and turns the
> servo loop off*. That is a reset, NOT the e-stop we want — `#24` stops motion
> and latches error 10 but does not (by itself) tear down servo/enable state.
> Do **not** substitute `#27`.

---

## Q3 — Post-stop error latch and how to clear it

**Answer: yes — GCS error 10 latches; it is cleared by reading the error (`ERR?`
/ `qERR`), which pipython's `StopAll(noraise=True)` / `pitools.stopall()` do for
you. Confidence: HIGH.**

- Error code: `PI_CNTR_STOP = 10` — *"Controller was stopped by command"*
  (PI `PI_ControllerErrors.h`; pipython `gcserror.E10_PI_CNTR_STOP`).
- After `#24`/`STP`/`HLT`, the controller sets error 10. Standard GCS: the error
  register returns its value on `ERR?` and **resets to 0 on read** — so a single
  `ERR?`/`qERR` both reports and clears it.
- pipython does the read for you as part of its automatic error check. Both PI
  helpers explicitly mask exactly this:
  - `pitools.stopall`: `try: pidevice.StopAll() except GCSError as exc: if
    E10_PI_CNTR_STOP != exc: raise` — the failing `ERR?` read (value 10) is
    what's masked; the read clears the register.
  - `GCSDevice.StopAll(noraise=True)` masks `E10_PI_CNTR_STOP` internally.
- Corroboration (odemis `pigcs.py`): after sending `"\x18"` it calls
  `GetErrorNum()` and comments *"need to recover from the 'error', otherwise
  nothing works"* — i.e. if you don't consume error 10, **the next command
  raises**, which is exactly the "abort looks like a second fault" failure Adam
  flagged.

**Servo/enable after a stop:** `#24` stops motion and latches error 10 but does
*not* itself disable the servo/axis (that is the harder `#27`). After clearing
error 10, a fresh `MOV` should be accepted without re-homing. This is **not
verbatim-confirmed for the C-663 firmware** — treat "MOV works after StopAll +
error-clear without re-home" as a bench check (see uncertainty). The driver's
existing `_require_homed`/`DeviceError` paths already fail safe if a later `MOV`
is refused, so the abort path stays safe either way.

---

## Q4 — `IsMoving` false-"on-target" race and the correct wait sequence

**Answer: use a *target-relative* on-target signal (`qONT` closed-loop /
`qOSN` open-loop), i.e. PI's `pitools.ontarget()`, not raw `IsMoving`. That is
inherently free of the start-race. Confidence: HIGH on the correct signal; the
existence/width of the raw-`IsMoving` start-race is inferred, not documented.**

The concern: after an async `MOV` is accepted but before motion physically
starts, could a poll read "not moving" and conclude "arrived"? With raw
`IsMoving` this is a real, if brief, possibility (the motion-generator flag may
not be set the instant `MOV` returns). PI's own code avoids it by never using
`IsMoving` as the primary arrival signal:

`pitools.ontarget(pidevice, axes)` (verbatim behaviour):
1. `servo = qSVO(axes)` → split into **closed-loop** and **open-loop** axes.
2. Closed-loop: `qONT(axes)` if `HasqONT()`, else fall back to `not IsMoving`.
3. Open-loop (steppers — the C-663/L-836 default without the optional encoder):
   `qOSN(axes)` (steps-left) if `HasqOSN()`; on-target ⇔ steps-left == 0.

`qONT` and `qOSN` are defined **relative to the newly commanded target**, so
immediately after a real `MOV` they read *not-on-target* (you are not within the
new target's window / steps-left > 0) and only flip true on actual arrival —
there is no window in which they falsely say "done." `IsMoving` is a raw
motion-state flag and is the only branch with a start-race, which is why PI keeps
it as a last-resort fallback.

Also note `pitools.waitontarget()` calls `waitonready()` **before** polling
`qONT` — a "controller has taken up the command" guard. The current driver's
fixed `time.sleep(0.02)` is a weaker stand-in for that.

Corroboration (odemis `pigcs.py`): prefers `IsOnTarget` over `isMoving` because
near the target the stage *"might constantly be slightly moving (around the
target)"* — i.e. `IsMoving` also flickers at the *end* of a move, another reason
it is the wrong primary signal.

---

## Concrete recommendation — `PIMotorStage.stop()`

Replace the bounded-lock + `STP` compromise with a lock-free `#24` stop. Do
**not** take `io_lock` (pipython's internal per-exchange lock is the wire-safety
guarantee; `#24` is immediate; taking `io_lock` would only risk queueing behind
`home()`'s long hold — the exact failure to avoid):

```python
def stop(self) -> None:
    # Emergency stop = single-character #24 (GCS "stop all axes", immediate),
    # sent via pipython StopAll(). NOT the STP mnemonic (a normal LF-terminated
    # command line) and NOT under io_lock: pipython serialises each exchange with
    # its own internal lock released between polls, so this waits at most one
    # in-flight exchange (~ms), never a whole move. StopAll(noraise=True) also
    # reads-and-masks GCS error 10 ("controller was stopped by command"), so the
    # next command does not inherit it. Source: pipython gcscommands.StopAll /
    # pitools.stopall; PI GCS #24. See docs/research/pi_gcs_stop_semantics.md.
    gcs = self._gcs
    if gcs is None:
        logger.warning("PI stage STOP requested while not connected — no-op")
        return
    try:
        gcs.StopAll(noraise=True)          # sends chr(24); masks E10_PI_CNTR_STOP
    except Exception as exc:
        # A stop path must never raise.
        logger.debug("PI StopAll raised (swallowed on stop path): %s", exc)
        # Belt-and-suspenders: if this pipython build left error 10 latched
        # (e.g. errcheck disabled), consume it so the abort's next command
        # does not look like a second fault.
        try:
            gcs.qERR()                     # ERR? — reports AND clears error 10
        except Exception:
            pass
    logger.warning("PI stage STOP issued (#24 StopAll)")
```

Notes:
- `pitools.stopall(gcs)` is an equally valid substitute for `gcs.StopAll(noraise=True)`
  (it calls `StopAll()` and masks `E10_PI_CNTR_STOP`). Either satisfies safety
  rule 4 with a cited PI source.
- This **removes** `_STOP_LOCK_TIMEOUT_S` from the stop path and the
  guarded/unguarded branch. `disconnect()` may keep its own bounded acquire.
- The `TODO(manual needed)` block on the class can be deleted and replaced with a
  one-line pointer to this note (its three sub-questions a/b/c are now answered).

## Concrete recommendation — `PIMotorStage._wait_on_target()`

Poll PI's `pitools.ontarget()` (correct signal per servo state; race-free),
keeping the per-poll `io_lock` acquire/release so the GUI poller is not frozen:

```python
def _wait_on_target(self, ids: list[str]) -> None:
    deadline = time.monotonic() + self._move_timeout
    time.sleep(0.02)   # small "command taken up" guard (cf. pitools.waitonready)
    while time.monotonic() < deadline:
        try:
            with self.io_lock:
                # pitools.ontarget() reads qSVO once, then qONT (closed-loop) or
                # qOSN steps-left (open-loop stepper), falling back to IsMoving
                # only if the controller supports neither. qONT/qOSN are defined
                # against the NEW target, so they cannot falsely read on-target
                # in the window right after MOV. Source: pipython pitools.ontarget.
                on_target = self._pitools.ontarget(self._gcs, ids)
            if on_target and all(on_target.values()):
                return
        except Exception:
            # Extremely defensive: if ontarget() itself errors, fall back to the
            # old IsMoving check rather than spin.
            try:
                with self.io_lock:
                    moving = self._gcs.IsMoving(ids)
                if not any(moving.values()):
                    return
            except Exception:
                return
        time.sleep(0.02)
    raise DeviceError(
        f"PI move did not complete within {self._move_timeout:.0f} s "
        "(check servo, referencing and that the target is within travel)."
    )
```

Notes:
- If a fully self-contained implementation is preferred over calling
  `pitools.ontarget` (e.g. to avoid the per-poll `qSVO`), cache the servo state
  from `qSVO` once per move and then poll `qONT` (closed-loop) or `qOSN`
  (open-loop) directly — same logic, one fewer exchange per poll. The current
  `IsMoving`-first / `qONT`-fallback ordering is *backwards* for race-safety and
  should be replaced.
- The pre-loop `time.sleep(0.02)` can stay as a cheap "command taken up" guard;
  it is no longer the sole race defence once `qONT`/`qOSN` are the arrival signal.

---

## Sources

Confidence legend: **official library source** = PI's own pipython (repo
`PI-PhysikInstrumente/PIPython`; read here via the `royerlab/pipython` mirror and
`pipython.physikinstrumente.com`); **official manual** = PI user manual; **secondary**
= third-party driver / corroboration.

- pipython `gcscommands.py` — `STP`, `HLT`, `StopAll` (`chr(24)`), `IsMoving`
  (`chr(5)`), `IsControllerReady` (`chr(7)`), `SVO`, `EAX`; docstrings +
  `E10_PI_CNTR_STOP` masking. *(official library source)*
  https://raw.githubusercontent.com/royerlab/pipython/master/pipython/gcscommands.py ·
  https://github.com/PI-PhysikInstrumente/PIPython
- pipython `gcsmessages.py` — `send()`/`read()` internal `self.__lock`
  (per-exchange), `errcheck` property, embedded `ERR?` auto-check. *(official library source)*
  https://raw.githubusercontent.com/royerlab/pipython/master/pipython/gcsmessages.py
- pipython `pitools.py` — `stopall()` (`StopAll()` + mask E10), `waitontarget()`
  (`waitonready` then `qONT`), `ontarget()` (`qSVO` split; `qONT`/`qOSN`/`IsMoving`).
  *(official library source)*
  https://raw.githubusercontent.com/royerlab/pipython/master/pipython/pitools.py ·
  https://pipython.physikinstrumente.com/pitools.html
- PI E-727 User Manual, "GCS Commands / Notation / GCS Syntax for Syntax Version
  2.0" (pp.178–179) — `#24` = single-character command; *"Single-character
  commands are not followed by a termination character."* *(official manual)*
  https://www.manualslib.com/manual/1672823/Pi-E-727.html?page=178
- PI Mercury GCS Commands manual MS163E (C-663/C-863 family) — `STP`/`HLT`/`#24`
  stop; "target set to current position" on stop; `STP` sets ERR 10. *(official
  manual; PDF did not text-extract in-tool — content via PI search index, treat
  C-663-specific quirks as bench-confirmable)*
  https://twiki.cern.ch/twiki/pub/ILCBDSColl/Phase2Preparations/Mercury_GCS_Commands_MS163E102.pdf
- PI `PI_ControllerErrors.h` — `#define PI_CNTR_STOP 10L /* Controller was
  stopped by command */`. *(official header, via mirror)*
  https://github.com/nsteins/Labview/blob/master/E-816/E816_DLL/picontrollererrors.h
- delmic/odemis `pigcs.py` — `Stop()` sends `"\x18"` ("immediate stop");
  error-10 recovery *"otherwise nothing works"*; prefers `IsOnTarget` over
  `isMoving`. *(secondary, corroborating)*
  https://github.com/delmic/odemis/blob/master/src/odemis/driver/pigcs.py

## Uncertainty — what could NOT be established (read before implementing)

- **No single verbatim PI sentence** "single-character commands are executed
  immediately / preempt an in-flight command line." The real-time property of
  `#24` is *inferred* from convergent evidence (single-char/no-terminator
  notation + PI's use of `#5`/`#7` to poll during long ops + `#24`-interrupts-
  moves manual wording + odemis "immediate"). Strong, but **bench-confirm** that
  `StopAll()` actually halts a running `FRF`/`MOV` on the C-663 with sub-command
  latency (should be indistinguishable from instant).
- **C-663 Mercury GCS Commands PDF did not text-extract** in-tool (binary
  stream). Command-layer facts are taken from PI's pipython source and the E-727
  manual, which are the same GCS 2.0 family — but a **C-663-firmware-specific**
  quirk (e.g. `StopAll`/`HasqONT`/`HasqOSN` support) is not individually verified.
  `pitools.ontarget` already probes `HasqONT`/`HasqOSN`, so it degrades safely.
- **Servo state after `#24`** on the C-663: I assert `#24` stops + latches error
  10 but does *not* disable the servo (that is `#27`). Not verbatim-confirmed for
  C-663 firmware — bench-confirm that a `MOV` is accepted after `StopAll` +
  error-clear **without** re-homing. (Fail-safe either way: a refused `MOV`
  surfaces as `DeviceError`.)
- **Open- vs closed-loop default** of the L-836 + C-663 depends on the optional
  linear encoder / configured `SVO`. This decides whether `qONT` or `qOSN` is the
  arrival signal — `pitools.ontarget` handles both automatically, which is why it
  is recommended over a hand-picked single signal.
- Whether `StopAll(noraise=True)` clears error 10 in **every** pipython build
  regardless of the `errcheck` setting: the belt-and-suspenders `qERR()` in the
  `stop()` sketch covers the case where `errcheck` is off and the register is
  left latched.
