# Printrun `printcore` as the TCT motor backend — evaluation

- **Date:** 2026-07-07
- **Author:** Prometheus (researcher / first-officer advisor)
- **Exact question:** Should the TCT app's custom Marlin/GRBL motor driver
  (`TCT_app/devices/motor_grbl.py`) be replaced by Printrun's `printcore`
  (the Printrun project's serial/G-code communication core) for robustness?
- **Software under review:** Printrun / `printcore`, package version **2.2.0**
  (PyPI, 2024-10-20), `printcore.py` `__version__ = "2.2.0"`. GPLv3+.
- **Confidence:** official docs + primary source (upstream GitHub, PyPI, license
  file, RepRap G-code spec). Bench-fit judgement is my advisory opinion.

---

## TL;DR — RECOMMENDATION

> **DON'T switch. HYBRID-harden our own driver instead.**
> Re-implement `printcore`'s robustness *patterns* (Marlin line-number +
> `*`checksum + `Resend:` retransmit + explicit `busy:`/`wait` handling) in
> `motor_grbl.py` from the public RepRap/Marlin serial spec — under our own
> license, no GPL dependency.
>
> **Deciding factor:** `printcore` is **GPLv3+** and only replaces the *thin*
> serial layer, while every piece of TCT-specific value (GRBL `$J=` jogs,
> machine/user coordinate frame, soft-limit guarding, stall guard, snap-to-detent,
> firmware auto-detect) would still have to live in our backend. Small reward,
> large cost: copyleft contamination of a repo that is *deliberately* kept
> IP-clean and publishable, plus a full-GUI dependency tree (`wxPython`, `numpy`,
> `pyglet`, `lxml`) that also threatens the app's `numpy<2` pin.

Secondary finding worth stating plainly to Adam: **`printcore` would not have
prevented any of the recent bench pain.** The Z-endstop homing failure, the
marlin/grbl flag confusion, and the soft-limit sign bug are physical-endstop /
config-convention / coordinate-frame bugs. `printcore` hardens *line-level
transmission integrity* (corruption/desync), which is a different failure class
than what has actually been hurting us. So the headline motivation ("recent motor
pain") is only weakly served by adopting it.

---

## Q1 — What `printcore` actually is

`printcore` is the pure-Python communication core of Printrun (the
Pronterface/Pronsole host suite). It is `printrun.printcore.printcore`, a class
that owns the serial link to a RepRap/Marlin printer and runs G-code jobs.

- Import + minimal use (from upstream README):
  ```python
  from printrun.printcore import printcore
  from printrun import gcoder
  p = printcore('COM3', 115200)      # or '/dev/ttyUSB0'
  while not p.online:                 # wait for handshake
      time.sleep(0.1)
  p.send_now("M105")                  # interactive command, jumps the queue
  gcode = gcoder.LightGCode([l.strip() for l in open('f.gcode')])
  p.startprint(gcode)                 # run a whole job
  p.pause(); p.resume(); p.disconnect()
  ```
- Constructor: `printcore(port=None, baud=None, dtr=None)`.
- Key attribute: `online` (True after the firmware handshake completes).
- Methods: `connect()`, `disconnect()`, `send()` (queued), `send_now()`
  (priority/interactive), `startprint(gcode)`, `pause()`, `resume()`, `reset()`.
- Architecture (from `printcore.py` source): a **background reader thread**
  (`self.read_thread = threading.Thread(target=self._listen, ...)`, started in
  `connect()`) plus **two send queues** — `mainqueue` (the print job) and
  `priqueue` (priority/interactive commands). `send_now()` routes to `priqueue`.
- Callbacks — **two eras**:
  - *Modern:* `self.event_handler = PRINTCORE_HANDLER`, a **list of handler
    objects** implementing `on_connect`, `on_recv`, `on_send`, `on_error`,
    `on_temp`, `on_online`, etc.
  - *Deprecated:* the old scalar attributes `recvcb`, `sendcb`, `tempcb`,
    `errorcb`, `startcb`, `endcb`, `onlinecb`, `printsendcb`, `preprintsendcb`,
    `layerchangecb`. The source emits deprecation warnings for these.
- It speaks the **Marlin/RepRap serial dialect**, not GRBL's real-time protocol.
  `printcore.py` module imports are stdlib-only + `pyserial` + Printrun
  submodules (`gcoder`, `device`, `utils`, `plugins`) — **no `wx`, no `numpy`**
  at the `printcore.py` level.

Sources: upstream README + `printcore.py` on GitHub; PyPI page (below).

## Q2 — Robustness it gives vs. what `motor_grbl.py` lacks

`printcore._listen` / `_send` implement the resilient Marlin line protocol:

| Feature | `printcore` | our `motor_grbl.py` |
|---|---|---|
| Line numbering (`N<n>`) | Yes (`"N"+str(lineno)+" "+command`) | **No** |
| Checksum (`*<xor>`) | Yes (`_checksum`, XOR of the prefix) | **No** |
| `Resend:`/`rs` parse + retransmit | Yes (sets `self.resendfrom`, replays from that line) | **No** |
| `ok`-gated flow control | Yes (`clear` flag; sender blocks until `ok`) | Partial — synchronous `write → readline until ok/error` under a lock (`_send_wait`) |
| `busy:`/`wait` handling | Yes (parsed in `_listen`) | Only skips `ok T:` temp auto-reports; no explicit `busy:`/`wait` |
| Async reader thread (decoupled RX) | Yes | **No** — reads inline while holding `self._lock` |
| Priority queue (interactive vs job) | Yes (`priqueue`/`mainqueue`) | N/A (one command at a time) |

So our driver's gaps are specifically: **no line numbers, no checksums, no
resend recovery, no `busy:`/`wait` handling, no background reader.** On a noisy
USB-CDC link those are the things that cause a corrupted `G1` to be silently
dropped or a stale `ok` to be mis-attributed. Our `_send_wait` does already do a
*form* of ok-based flow control and even guards against mid-command GRBL resets
and stale `ok T:` temp reports — so the flow-control half is decent; the
transmission-integrity half (checksum + resend) is the genuine missing piece.

Conversely, `printcore` gives us **none** of what `motor_grbl.py` does that
matters for TCT: GRBL `$J=` jog semantics, GRBL real-time `?` status, the
machine↔user coordinate frame (`_to_user`/`_to_machine`/`_zero`), soft-limit
checks in machine coords, the stall guard, snap-to-detent, and firmware
auto-detect (`M115`/banner). `printcore` is Marlin-only and job-oriented; it has
no GRBL awareness at all.

## Q3 — LICENSING (the decisive factor)

- **License: GNU GPL v3 or later.** Confirmed three ways: the repo `COPYING`
  file is verbatim "GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007"; the
  `printcore.py` header ("...under the terms of the GNU General Public License
  ... either version 3 of the License..."); and the PyPI classifier
  "GNU General Public License v3 or later (GPLv3+)".
- **Copyleft reach:** `import printcore` links Printrun into the same Python
  process as the TCT app. Under the FSF's own interpretation, importing a GPL
  module makes the combined program a derivative work; **if the combined work is
  ever conveyed/distributed, the whole thing must be offered under GPLv3.** For a
  purely internal lab tool that is never distributed, GPL obligations are not
  *triggered* (no conveyance) — but this project's stated posture is the opposite
  of "never distributed": it deliberately keeps third-party/vendor IP **out of
  git** so the app stays clean and publishable (`CLAUDE.md`, `docs/REFERENCE_MATERIAL.md`).
  Adding a GPL runtime dependency contaminates exactly that posture.
- **Options and verdict:**
  1. *Hard pip dependency on Printrun* — copyleft reach on any future
     distribution, and it advertises a GPL dep in `requirements.txt`. ✗ for a
     repo meant to stay clean/publishable.
  2. *Vendor just `printcore.py` (+ `gcoder`/`device`/`utils`/`plugins`)* — this
     literally puts GPL source into the tree the project works to keep IP-clean.
     Worst option. ✗
  3. *Subprocess isolation* (run `printcore` in a separate GPL-licensed helper
     process, talk to it over a pipe/socket → "mere aggregation") — legally the
     cleanest way to *use* it, but it's heavy, fragile IPC for what is ultimately
     "send a G-code line and wait for ok". ✗ (not worth the machinery).
  4. *Don't import it; re-implement the patterns* — the Marlin line protocol and
     G-code are **published specifications, not copyrightable expression**. A
     clean-room implementation from the RepRap G-code spec carries **no GPL
     obligation**. ✓ This is the recommended path.

## Q4 — Footprint / fit

- **Declared install deps (`requirements.txt`):** `pyserial>=3.0`, **`wxPython>=4.2.0`**,
  **`numpy>=1.8.2`**, `pyglet>=1.1,<2.0`, `psutil>=2.1`, `lxml>=2.9.1`,
  `platformdirs`, `puremagic`, plus platform extras (`pillow`+`pyreadline3` on
  win32, `dbus-python` on linux, `pyobjc-framework-Cocoa` on darwin).
  So `pip install Printrun` drags the **entire Pronterface GUI stack** in for
  what we need (serial + G-code).
- **numpy-pin hazard:** Printrun pins `numpy>=1.8.2` with **no upper bound**. The
  TCT app pins **`numpy<2`** because the vendored FLIR PySpin wheel needs the
  numpy 1.x C-ABI. A fresh resolve that satisfies Printrun could pull numpy 2.x
  and **break real-camera mode.** Real, not hypothetical.
- **Python / Windows:** PyPI classifiers list Python **3.8–3.13** and OS Windows
  — so CPython 3.10 / Windows (our real-hardware target) is supported. No
  compatibility blocker there.
- **Importable as a library w/o the GUI?** `printcore.py` itself imports only
  stdlib + `pyserial` + Printrun submodules (no `wx`), so the *class* runs
  headless. But the *pip package's* metadata still forces `wxPython`/`numpy`/etc.
  to install. You only escape that by vendoring (option 2 above = the GPL-in-tree
  problem) — so "importable headless" doesn't rescue the footprint verdict.

## Q5 — Mapping to `MotorStageBase`

A `motor_printcore.py(MotorStageBase)` is *implementable*, but note the impedance
mismatch and how little it actually replaces:

- **Transport only.** `printcore` would replace roughly the ~120 lines of
  `_send`/`_send_wait`/serial plumbing. Everything else in `motor_grbl.py`
  (coordinate frame, soft limits, stall guard, snap, auto-detect, GRBL path)
  stays ours.
- **Async model fights our sync contract.** `MotorStageBase.get_position()` must
  *return* a `Position`. `printcore` is asynchronous: `M114`'s reply arrives on
  the reader thread and is delivered via `recvcb`/`on_recv`, not as a return
  value. We'd have to bolt a synchronous "send `M114`, block on an Event until
  the recv callback parses `X:.. Y:.. Z:..`" wrapper back on top — re-adding the
  very blocking behaviour our current design already has natively.
- **G-code emitted** (all standard Marlin/RepRap, so nothing invented — cited in
  Q on sources):
  - `move_to` → `G90` then `G0/G1 X.. Y.. Z.. F..`, then `M400` to wait for the
    move to finish.
  - `move_relative` → `G91` + `G1 ...` (+ `G90` restore) or track absolute.
  - `home` → `G28` (optionally `G28 X`/`Y`/`Z`).
  - `get_position` → `M114`, parse `X:.. Y:.. Z:..` (Marlin path only; GRBL uses `?`).
  - `stop` → `M410` (quickstop) — already what our Marlin path does.
  - `zero_position` → `G92 X0 Y0 Z0` (matches the ABC docstring).
- The **simulated backend and all tests stay intact** — they target
  `MotorStageBase`, not any transport. Good news, but equally true for the
  hybrid-harden path, so it isn't a differentiator in printcore's favour.

Net: a printcore backend would be a *thin* transport swap that keeps ~80% of our
code, adds an async→sync shim, and — critically — is **Marlin-only**, so it can't
replace the GRBL path that `configs/devices.yaml` and `motor_grbl.py` support. We
would end up maintaining two real backends, not one.

## Q6 — Alternatives

- **(a) Adopt `printcore`.** GPL contamination + full-GUI dep tree + numpy-pin
  hazard + async/sync shim + Marlin-only (GRBL path still ours). Reward: proven
  checksum/resend. **Not worth it.**
- **(b) HARDEN our own driver [RECOMMENDED].** Add an *optional* Marlin resilient
  mode to `motor_grbl.py`, re-implemented from the RepRap/Marlin serial spec:
  - prefix `N<lineno>` + append `*<xor-checksum>` (XOR of the bytes up to `*`),
    reset with `M110 N0` on connect;
  - parse `Resend:`/`rs <n>` and retransmit from that line;
  - handle `busy: processing` / `wait` (keep waiting, don't treat as error);
  - keep the existing `ok`-flow, GRBL `$J=` path, coordinate frame, stall guard.
  Protocols/G-code aren't copyrightable → **no GPL, no wxPython, no numpy risk.**
  Directly closes the one genuine gap (transmission integrity) without a
  dependency. Can read `printcore` for *understanding* the pattern, but write our
  own from the spec (clean-room) to avoid copying GPL expression.
- **(c) Other libs.** `pyserial` (already a dep) + our thin robust layer = path
  (b). `moonraker`/Klipper is massive overkill and requires **Klipper firmware**
  flashed on the board (we run Marlin/GRBL) — not applicable. `pyserial` + a
  small BSD/MIT G-code helper would work but none is as battle-tested as just
  copying the well-documented pattern ourselves.

## Effort / risk for the recommended path (b)

- **Effort:** small–moderate. ~40–80 lines added to the Marlin branch of
  `motor_grbl.py`: checksum helper, line-number counter + `M110 N0` on connect,
  a resend buffer of the last-sent line(s), `Resend:`/`busy:`/`wait` handling in
  the read loop. Gate behind a config flag (e.g. `checksummed: true`) so GRBL and
  plain-Marlin paths are unaffected. No new dependency, no license change.
- **Risk:** low. Purely additive to the serial layer; the simulated backend and
  the whole pytest suite (which target `MotorStageBase`) are untouched and remain
  the regression net. New logic is unit-testable with a fake serial (feed it a
  `Resend:5` and assert we retransmit from line 5). No hardware needed to test the
  protocol logic.
- **Contrast:** path (a) is higher effort *and* higher risk (dependency
  resolution against `numpy<2`, async shim, GPL review) for a strictly smaller
  net gain.

---

## Sources

- Printrun repo + README (printcore usage, API, GPL note): https://github.com/kliment/Printrun
- `printcore.py` source (class, callbacks, `_listen`/`_send`, checksum, resend, queues, threads, `__version__=2.2.0`): https://github.com/kliment/Printrun/blob/master/printrun/printcore.py
- License file (`COPYING` = GNU GPL v3, 29 June 2007): https://github.com/kliment/Printrun/blob/master/COPYING
- PyPI (v2.2.0, 2024-10-20; Python 3.8–3.13; OS Windows; GPLv3+ classifier): https://pypi.org/project/Printrun/
- `requirements.txt` (pyserial, wxPython>=4.2, numpy>=1.8.2, pyglet, lxml, ...): https://github.com/kliment/Printrun/blob/master/requirements.txt
- RepRap G-code spec — serial line-number/checksum/`Resend`/`M110` protocol and
  G0/G1/G28/G90/G91/G92/M114/M400 semantics ("checksum ... exor-ing the bytes ...
  up to and not including the `*`"): https://reprap.org/wiki/G-code
