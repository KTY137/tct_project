# Remote Control (Master/Slave) — Architecture Design Plan

**Status:** Proposal / design only. Nothing here is implemented yet.
**Author:** Abel (acquisition-dev), for Adam (lead architect) and the lab owner.
**Date:** 2026-07-04
**Scope:** Add the ability to operate the lab TCT setup from a second installation
of the same app running at home, over a network, without moving acquisition off
the lab machine and without weakening any hardware-safety rule.

---

## 1. Context

### 1.1 The problem
The TCT app (`TCT_app/`) is standalone today: one process
on the lab PC owns the hardware (motor stage, ISEG/Keithley bias, DRS4/VISA
scope, waveform generator, camera, slow control) via `DeviceManager`, drives
scans through `ScanController` + `StateMachine`, and writes HDF5 runs to
`runs/run_NNNNN/waveforms.h5`. The lab owner wants to sit at home and:

- watch a scan progress live,
- issue control actions (start/stop/abort a scan, move the stage, set bias,
  change scan parameters),
- get the full measurement data after the run finishes.

### 1.2 Refined model (the design this document commits to)
The verbatim intent is sound. Refined and made precise:

1. **Acquisition stays local.** The lab machine remains the sole owner of the
   hardware and the sole executor of the scan loop (`ScanController._run`,
   `_acquire_point`, `_run_voltage_scan`, `_run_z_focus*`). The network never
   sits inside a time-critical capture path. The home machine issues *intent*
   ("start this scan", "move here"); the lab machine decides, executes, and
   remains authoritative. This is the key latency decision and it is
   non-negotiable in the design.

2. **Live view is a low-bandwidth telemetry feed, not a data stream.** The home
   side receives periodic *snapshots*: scan progress (`done/total`), current
   stage position, bias V/I, laser/intensity, state-machine state, and a
   *decimated* preview of waveforms (e.g. every Nth point, downsampled). It never
   receives every full waveform live. See §3b for the refinement of the "every
   other waveform" idea.

3. **Full data transfers after the run.** The complete `waveforms.h5` (the exact
   file `HDF5Writer` already produces, per `SCAN_DATA_FORMAT.md`) is copied to the
   home machine as a bulk transfer once the writer has closed and the run reached
   `FINISHED` / `ABORTED`. No live HDF5 streaming.

### 1.3 Intended outcome
The same binary, in **lab-server mode**, exposes a guarded network surface; the
same binary in **remote-client mode** connects to it and mirrors telemetry +
sends guarded commands. With zero networking configured, the app behaves exactly
as it does today (standalone, simulation-safe, import-safe). Networking is an
*opt-in, optional* subsystem — the `InfluxWriter` optional-import discipline
(`data/influx_writer.py`) is the template.

---

## 2. Roles & terminology

To avoid the ambiguity in "master/slave", this plan uses explicit role names and
uses them consistently:

| Term | Meaning |
|---|---|
| **Lab node** (a.k.a. **server / authoritative node**) | The installation wired to the hardware. Owns `DeviceManager`, `StateMachine`, `ScanController`. It is the single source of truth. It *executes*. |
| **Remote node** (a.k.a. **client / observer-controller**) | The installation at home. Holds no real devices. It *observes* telemetry and *requests* actions. It never executes hardware I/O itself. |
| **Control request** | A message from remote node → lab node asking for an action (start scan, move, set bias). Always subject to local safety gating. |
| **Telemetry snapshot** | A message lab node → remote node with lightweight live state. |
| **Run bundle** | The `run_NNNNN/waveforms.h5` file (+ any sidecars) transferred after a run. |

**Recommendation on "two apps vs one app, two modes":** ship **one app with a run
mode**, selected at launch (CLI flag / config), not two codebases:

- `--role=standalone` (default; today's behaviour, no networking imported),
- `--role=lab-server` (standalone + a remote-access service bound to a chosen
  interface),
- `--role=remote-client host:port` (GUI in observer/controller mode; no real
  `DeviceManager`, devices are all "remote proxies").

Rationale: the remote node must render the *same* telemetry semantics the lab
node emits (states, ScanResult fields, progress). Sharing one codebase means the
`AppState` enum, `ScanResult` dataclass, and `SCAN_DATA_FORMAT.md` contract stay
in lockstep automatically. Two apps would drift. The mode flag keeps
`main.py → TCTMainWindow(config_path=...)` almost unchanged; a new optional
`role`/`remote` argument selects wiring.

Lab node is authoritative in every conflict. If the remote node's view disagrees
with the lab node (stale telemetry, dropped link), the lab node's state wins and
the remote node is the one that must reconcile.

---

## 3. Three logical channels

These are deliberately separated because their latency/bandwidth/reliability
needs differ. They can share one transport connection (multiplexed by message
type) or run on separate sockets; §4 recommends a concrete split.

### 3a. Control channel (request/response, low rate, high assurance)

**Purpose:** carry discrete commands: `connect_all` / `disconnect_all`,
`start_scan(cfg)`, `pause` / `resume` / `abort`, `start_voltage_scan(cfg)`,
`start_z_focus(cfg)`, `move_to(x,y,z)`, `set_bias(V)` / `ramp` / `output_off`,
`set_scan_params`. Each command gets an explicit acknowledgement/response
(accepted / rejected-with-reason / not-permitted).

**Binding into existing code (must route through, never bypass):**
- Scan lifecycle commands map **one-to-one** onto existing `ScanController`
  methods: `start(cfg)`, `pause()`, `resume()`, `abort()`,
  `start_voltage_scan(cfg)`, `start_z_focus_scan(cfg)`. Those already gate on
  `self._sm.can(AppState.RUNNING)` and raise if the state forbids it — the remote
  layer inherits that gating for free by calling them rather than re-implementing.
- A rejected command (wrong state, safety veto) returns the `RuntimeError`
  message ("Cannot start scan in current state.") back over the wire as a
  structured error response; the remote GUI shows it.
- Device-level commands (`move_to`, bias set) must go through the **same
  confirmation/gating policy the local GUI uses**, not straight to the driver.
  See §5 for the local-confirmation policy that makes this safe.

**Design rule:** the control channel is a thin *adapter* that translates a
validated message into a call on the existing controller/state-machine API. It
introduces **no new path to the hardware** — every effect it can cause is one a
local operator could already cause through the GUI.

### 3b. Live-telemetry channel (pub/sub, lightweight snapshots)

**What the lab node already emits that we reuse:**
- `StateMachine.add_callback(cb)` fires `(old, new)` on every transition — the
  authoritative run state (`RUNNING/PAUSED/FINISHED/ABORTED/ERROR`).
- `ScanController` callbacks: `on_progress(done, total)`, `on_point_done(result)`,
  `on_vscan_point(v, c, i)`, `on_finished()`, `on_error(msg)`. In `tct_gui.py`
  these are already marshalled through `_ScanBridge` Qt signals (lines ~322–333)
  — the telemetry publisher taps the **same** callbacks.
- `gui/status_bus.py` `STATUS.message = Signal(str, str)` — app-wide human
  status/notification text. The telemetry channel should **mirror** this: subscribe
  to `STATUS.message` on the lab node and forward each `(text, level)` to remotes,
  so the home operator sees the same status-bar/log notifications.

**Snapshot payload (per tick), all small scalars:**
- `state` (AppState name), `progress` (done, total),
- stage position (x,y,z mm — from the last `ScanResult.point` or a periodic
  `motor` position read),
- bias `voltage_V` / `current_A` / `compliant` (already on `ScanResult` and read
  live by the bias poll),
- reference intensity / `ref_amplitude_V`, `dut_amplitude_V`, `dut_charge_pC`
  (already computed per point in `ScanResult`),
- slow-control snapshot (already gathered by
  `_read_slow_control_snapshot()`),
- timestamp + units.

**Refining the "every other waveform" idea — assessment and recommendation:**

The owner's instinct (don't stream every waveform, send a decimated preview) is
correct and viable. Refinements:

- **Decimate in point-space AND sample-space.** "Every Nth waveform" decimates in
  point-space (send the preview trace only for 1-in-N scan points). Also
  **downsample the trace itself** (e.g. `S=1024` → 128–256 samples via strided or
  min/max envelope decimation) and send as `float16`/`float32`. A single decimated
  preview trace is then ~0.5–1 kB, trivial to push a few times per second.
- **Make N adaptive, not fixed.** Drive the preview by a *rate budget* (e.g. "at
  most one preview trace every 500 ms") rather than a fixed N, because point
  cadence varies wildly between a fast XY scan and a slow IV sweep. The lab node
  drops previews it doesn't have bandwidth/time for; scalars (progress, position,
  bias) are cheap and can go every tick.
- **Previews are lossy and explicitly marked as such.** The remote GUI must label
  live traces "preview (decimated)" so no one mistakes them for analysis-grade
  data. The authoritative data always arrives later via the bulk channel (§3c).
- **Pub/sub beats polling.** The lab node already has event sources (state
  callbacks, per-point callbacks). A push model (lab publishes; remote
  subscribes) matches that naturally, avoids the remote hammering the lab with
  poll requests, and gives lower latency. Use a periodic "heartbeat" snapshot
  (e.g. 1–2 Hz) for the always-on scalars plus event-driven pushes for state
  changes and per-point previews. Polling is only a fallback if the transport
  can't do server-push.

**Standard alternative worth noting:** the scalar time-series (bias V/I, temps,
intensity, progress) is exactly what `InfluxWriter` already models. A clean,
"standard" live-monitoring option is: lab node writes scalars to InfluxDB (it
already can), and home views them in Grafana — **zero new streaming code** for the
numeric dashboard. That covers everything *except* the waveform preview and the
control channel. Recommendation: treat Influx/Grafana as an optional,
complementary numeric dashboard; still build the app-native telemetry channel for
the waveform preview, state, and tight GUI integration. Don't force the owner to
run Grafana, but support it for those who already do.

### 3c. Bulk-data channel (post-run file transfer)

**What moves:** the finished `run_NNNNN/waveforms.h5` (and any run sidecars).
Layout and semantics are fixed by `SCAN_DATA_FORMAT.md` — the transfer is
byte-exact; the home node opens the identical file with `h5py`.

**Size envelope (so we transfer sanely):** waveforms dominate —
`/waveforms/ref_ch1` + `/waveforms/dut_ch2` are `f4` `(N, S)`. For `N=400` points,
`S=1024` samples that's ~3.3 MB raw (gzip-compressed on disk, so less). A dense
XY scan (thousands of points) or enabling `camera_frame` (`(N, H, W)` images) can
push a run to tens–hundreds of MB. So: transfer must be **resumable/chunked**, run
**off the acquisition thread**, and be **verified** (size + checksum) before the
remote treats the file as complete.

**When it moves:** triggered on the lab node when `HDF5Writer.close()` has run and
the state machine reached `FINISHED`/`ABORTED` (i.e. in/after
`ScanController._end_run()`), never mid-scan. The remote can also *request*
historical run bundles by run id on demand. Transfer is idempotent: same run id +
checksum ⇒ skip.

**Do not reinvent file copy for v1.** For a VPN/LAN deployment, a mature transfer
tool (rsync/SFTP/HTTPS range requests) moving the closed file is more robust than
hand-rolled chunking. The app's job is to *announce* "run 42 is complete, here is
its checksum and location" over the control/telemetry channel and optionally kick
off the transfer; the bytes can ride a proven transport.

---

## 4. Transport options

Constraints this app imposes:
- **PySide6** (Qt) app with an existing signal/slot + `threading.Thread` model
  (scan runs in a daemon thread; GUI updates marshalled via `_ScanBridge`). A
  transport must integrate with Qt's event loop or with a background thread that
  hands results back via signals — the pattern already exists.
- **Import-safe & optional.** Standalone/simulation must run with the networking
  package absent (mirror `InfluxWriter`: import inside a method, warn once, degrade
  to no-op). No new hard dependency in `requirements.txt` for the core app.
- **`numpy<2` pinned** (PySpin ABI) — any transport lib must be fine on numpy 1.x.
- Three channels with different shapes: RPC-ish control, pub/sub telemetry, bulk
  file.

| Option | Fit for control | Fit for telemetry | Fit for bulk | Notes |
|---|---|---|---|---|
| **Plain TCP + JSON (custom)** | ok | ok | poor | Full control, but we'd re-implement framing, reconnect, auth, backpressure — avoid. |
| **WebSocket** (e.g. `websockets`) | good (req/resp over messages) | **very good** (native server-push, bidirectional) | ok (chunk framing) | Single bidirectional channel, firewall/VPN-friendly (looks like HTTP), easy TLS. Text (JSON) or binary frames for the preview traces. |
| **ZeroMQ** (`pyzmq`) | good (REQ/REP) | very good (PUB/SUB) | ok (but manual) | Excellent multi-pattern fit (REQ/REP + PUB/SUB in one lib), low latency. Heavier mental model; no built-in auth/TLS (CURVE exists but is extra); brokerless means both ends manage discovery. |
| **gRPC** | very good (typed RPC + streaming) | very good (server-streaming) | ok (streaming) | Strong contracts (protobuf), but adds a compiler/build step and a heavier dependency; overkill for a two-node lab link and more friction with the "optional, import-safe" rule. |
| **MQTT** (broker, e.g. mosquitto) | ok (via topics) | very good (pub/sub, retained msgs) | poor | Great for telemetry fan-out, but needs a broker process and control-as-topics is awkward for request/response with veto semantics. |
| **HTTP REST + SSE** | good (REST for commands) | good (SSE = server push, one-way) | **good** (HTTP range/resumable) | Very standard, easy auth (bearer token), SSE covers telemetry push, HTTP handles bulk natively. Two-way is REST-poll + SSE rather than one socket. |

### Recommendation

**Primary: a small WebSocket service on the lab node, one persistent bidirectional
connection, carrying control (request/response with correlation ids) and telemetry
(server-pushed snapshots) multiplexed by a `type` field; plus a separate HTTP(S)
endpoint (or an off-app SFTP/rsync path) for the bulk run-bundle download.**

Rationale:
- One bidirectional WebSocket cleanly serves both the request/response control
  channel and the push telemetry channel — matching the app's existing
  event-callback model. A background thread owns the socket and hands messages to
  the Qt GUI via signals exactly like `_ScanBridge` does today; outgoing telemetry
  is fed from the same `ScanController`/`STATUS` callbacks.
- WebSocket over TLS traverses VPN/LAN/reverse-proxies easily and carries a
  bearer token in the handshake for auth (§5).
- Bulk data does not belong on the live socket; a plain authenticated HTTPS
  download (range-request/resumable) or an existing SFTP/rsync of the closed file
  is more robust and keeps big transfers off the telemetry path.
- It stays optional and import-safe: the WebSocket lib is imported lazily inside
  the remote-service module; if absent and role is not a network role, the core
  app never touches it.

**Secondary/complementary:** keep the **InfluxDB + Grafana** path (already
half-built via `InfluxWriter`) as the "standard" numeric dashboard option for
users who want it — it requires no new app code for the scalar telemetry.

**Reuse map:**
- `data/influx_writer.py` → template for optional-import, degrade-to-no-op,
  `from_config()` construction, `enabled` flag.
- `gui/status_bus.py` `STATUS.message` → telemetry source to mirror to remotes,
  and on the remote side, the sink where forwarded messages are re-emitted so the
  remote GUI's existing status wiring "just works".
- `tct_gui._ScanBridge` → the thread→Qt-signal pattern the WebSocket receive
  thread should copy on the remote side.
- `StateMachine.add_callback` + `ScanController.on_*` → the exact tap points for
  outbound telemetry on the lab side.

---

## 5. Safety & security

**This section is the center of the design, not an appendix.** The root
`CLAUDE.md` safety rules are non-negotiable and must hold *even though commands
can now arrive over a network.*

### 5.1 Hardware-safety invariants under remote control

1. **No new hardware path.** The remote control adapter may only call existing
   `ScanController` / `DeviceManager` / device methods that a local operator could
   already invoke. It must not open drivers, must not talk to instruments
   directly, and must not mutate device state behind the controllers.

2. **Local safety gating always applies.** All scan-start commands already pass
   through `self._sm.can(AppState.RUNNING)` and raise otherwise. Remote commands
   inherit this. A remote request that the state machine forbids is rejected and
   the reason is returned. The remote **cannot** force a transition the local
   `StateMachine` disallows.

3. **Dangerous actions require a LOCAL confirmation policy — remote alone cannot
   arm them.** HV enable, HV ramp, stage motion, homing, and scan start are
   "dangerous actions" per rule 2 of `CLAUDE.md`. Over the network there is no
   human at the lab UI to click "confirm". Two policies, chosen by the lab owner
   (open question §7):
   - **Strict (default): dangerous remote actions are disabled unless a local
     operator has explicitly enabled a time-boxed "remote-armed" window** at the
     lab machine (e.g. "Allow remote control for 2 h"). Outside that window the
     lab node *rejects* HV-enable/motion/homing/scan-start requests with a clear
     "remote dangerous actions not armed" error, while still serving telemetry and
     read-only queries. This keeps a human in the loop and honors "explicit user
     confirmation".
   - **Trusted-operator: the remote node itself is treated as the confirming
     operator** (owner running his own VPN), but still bounded by per-action
     policy flags (e.g. remote may move stage and start scans, but HV-enable
     always stays local-only). Even here, HV enable should remain the most
     restricted action.
   The chosen policy lives in `configs/devices.yaml` (new `remote:` block),
   validated by `config_validator.py`, and defaults to the most restrictive.

4. **Never continue after a safety-critical hardware error (rule 5) — including
   loss of the control link.** The existing fail-safe behaviour (compliance trip →
   abort + ramp bias to 0 V + `output_off`; scope/motor error → `ERROR` state) is
   untouched and remains local. Additionally: **if the control link drops during a
   RUNNING scan, the lab node does not silently keep taking commands from a stale
   client.** Policy: the *scan itself continues locally to completion or safe
   stop* (acquisition is authoritative and local — pulling the plug at home must
   not corrupt a run), **but** no queued/in-flight remote command is executed
   after link loss, and any "remote-armed" window may be configured to auto-expire
   on disconnect so a reconnecting client must re-arm. A deliberate variant the
   owner may choose: link-loss triggers a safe **pause** rather than continue —
   this is an explicit policy decision (§7), defaulting to "continue to safe
   completion" because aborting a long scan on a Wi-Fi blip is worse.

5. **Simulation/import safety (rules 3 & 6).** The whole remote subsystem must be
   exercisable against simulated backends and must be import-safe. Tests
   (`python -m pytest tests/ -q`) run headless with mocks; a remote command in a
   test must be safe with real hardware attached (it goes through the same gating).
   The networking dependency being absent must not break import or the standalone
   app.

6. **Nothing auto-starts (rule 1).** The remote service must not connect devices,
   home, move, enable HV, or start a scan at import or startup. `lab-server` mode
   starts the *listener* only; it performs no hardware action until an authorized,
   policy-permitted command arrives.

### 5.2 Network security

- **Assume the link runs over a VPN or trusted LAN**, never a raw public port.
  Document this as the supported deployment. The service should default-bind to a
  configured interface, not `0.0.0.0`, and refuse to start on an untrusted
  interface without an explicit override.
- **Authentication:** bearer token / pre-shared key presented in the WebSocket
  handshake (and on the bulk HTTP endpoint). Token lives outside version control
  (env var or a gitignored secret file), and — like the Influx token in
  `config_snapshot()` — is **redacted** from any run metadata / logs.
- **Transport encryption:** TLS on the WebSocket and the bulk endpoint. On a
  closed VPN this is defense-in-depth; still recommended.
- **Least privilege by action, not just by connection:** the token/role determines
  which command classes are permitted (telemetry-only, safe-control,
  dangerous-control). HV-enable and motion are gated *both* by the safety policy
  (§5.1.3) *and* by the connection's permission class.
- **Auditability:** every accepted/rejected control command is logged (who, what,
  when, result) via the standard logging + `STATUS` bus, so there's a record of
  remote actions.
- **Rate limiting / single-controller:** at most one remote node may hold the
  "controller" role at a time (others are observers) to avoid two operators
  fighting over the stage. The lab operator can always reclaim/kick control
  locally.

---

## 6. Phased implementation roadmap

Each phase keeps the app fully runnable (standalone + simulation) at every step;
networking stays optional throughout. Owners refer to the persona crew.

### Phase 0 — Design sign-off & scaffolding (Adam + Abel)
- Land this document; get owner decisions on the §7 open questions (esp. safety
  policy and VPN).
- Add an **inert** `remote:` config block to `devices.yaml` (disabled by default)
  and its validation in `config_validator.py`. No behaviour change.
- Add the `--role` launch flag plumbing in `main.py`/`tct_gui.py` defaulting to
  `standalone` (no-op today). **Owner:** Abel (acquisition/run-control) with Noah
  for the launch/GUI wiring.

### Phase 1 — Read-only remote telemetry (lowest risk, high value)
- **Lab side:** a `RemoteTelemetryPublisher` that taps `StateMachine` callbacks,
  `ScanController.on_progress/on_point_done/on_vscan_point`, and `STATUS.message`,
  builds snapshot messages (scalars + decimated waveform preview per §3b), and
  pushes them over WebSocket. Import-safe/optional like `InfluxWriter`.
- **Remote side:** `remote-client` run mode that connects, receives snapshots, and
  drives a **read-only** mirror of the GUI (progress bar, position, bias readout,
  preview plot, state light, status bar). Reuses the `_ScanBridge` thread→signal
  pattern to marshal socket messages onto the Qt loop.
- **No control commands yet.** Home can watch but not touch.
- **Owners:** Abel (telemetry tap + snapshot schema), Noah (remote-client GUI
  mode, preview plotting), Prometheus (evaluate/confirm the chosen WebSocket lib &
  TLS/auth approach before coding). Optional: Jonathan if Influx/Grafana path is
  pursued in parallel.

### Phase 2 — Safe remote commands (guarded control channel)
- Add the control channel: request/response messages mapping to
  `ScanController.start/pause/resume/abort/start_voltage_scan/start_z_focus_scan`
  and guarded device actions.
- Implement the **local safety policy** (§5.1.3): `remote:` config selects
  strict/trusted; add the "arm remote control" local UI affordance; enforce
  per-action permission + state-machine gating; return structured rejections.
- Implement auth token + single-controller lock + audit logging.
- Start with the *least* dangerous commands (pause/resume/abort, scan-parameter
  edits, start-scan under an armed window); keep **HV-enable local-only by
  default**.
- **Owners:** Abel (command→controller adapter, gating, link-loss policy), Paul
  (hardware/HV/motion action permissions and fail-safe semantics), Noah (arm-UI +
  remote command buttons), Mary (qa-critic review of the safety gating and race
  conditions — mandatory before merge).

### Phase 3 — Post-run bulk transfer
- On the lab node, after `_end_run()` + `FINISHED/ABORTED`, announce
  "run complete" with run id + checksum + size over the control channel, and
  expose the closed `waveforms.h5` via the authenticated bulk endpoint (or trigger
  an SFTP/rsync). Resumable, verified, idempotent, off the acquisition thread.
- On the remote node, fetch on announce (or on demand by run id), verify checksum,
  drop into a local `runs/` mirror, and let the existing Analysis panel open it —
  the file is byte-identical, so no format work is needed.
- **Owners:** Jonathan (data/HDF5 integrity, checksum/verify, analysis-panel
  hookup), Abel (announce hook in run lifecycle), Noah (download progress UI).

### Phase 4 (optional) — Hardening & niceties
- Reconnect/backoff, telemetry rate adaptation, Grafana dashboard doc, multi-
  observer fan-out, session/audit view. **Owners:** as above; Mary reviews.

After any phase that adds a module/signal/config key/HDF5 group, **Samantha
(docs-dev)** updates `docs/ARCHITECTURE.md` and relevant docs in the same task,
per the orchestrator rules.

---

## 7. Open questions / risks (need the owner's decision)

**Decisions required:**
1. **Deployment surface:** VPN into the lab LAN (recommended) vs a public server
   with port-forwarding (discouraged). This determines how hard the auth/TLS story
   must be. *Recommendation: VPN only, service bound to the VPN interface.*
2. **Safety policy for dangerous remote actions:** strict "local must arm a
   time-boxed window" (default) vs trusted-operator with per-action flags. And
   specifically: **should HV-enable ever be remote-triggerable at all?**
   *Recommendation: never remote HV-enable in v1; motion/scan-start only under an
   armed window.*
3. **Link-loss behaviour during a RUNNING scan:** continue to safe completion
   (default recommendation) vs auto-pause vs auto-abort. Aborting on a Wi-Fi blip
   wastes long scans; continuing is safest for data but means the remote can't
   intervene until reconnect.
4. **How much remote control does he actually want?** Watch-only (Phase 1) may
   already cover "monitor from home". Full remote motion/bias is a much larger
   safety surface — confirm it's wanted before Phase 2.
5. **Transport choice confirmation:** WebSocket+HTTPS (recommended) vs adopting the
   Influx/Grafana stack for the numeric dashboard (complementary). Prometheus to
   validate the specific library and its numpy<2 / PySide6 event-loop fit before
   Phase 1 code.

**Viability caveats on the live-snapshot approach:**
- The waveform *preview* is intentionally lossy (decimated point-space and
  sample-space). It is for eyeballing scan health, **not** analysis. Must be
  labeled as such in the GUI; the authoritative data is the post-run bundle.
- Preview cadence must be budget-limited, not fixed-N, or a fast scan floods the
  link and a slow scan feels dead. Adaptive rate is required, not optional.
- Telemetry and control share the lab machine's CPU with acquisition. The
  publisher must be cheap and off the acquisition thread; if it ever competes with
  capture, drop telemetry, never acquisition (acquisition is authoritative).
- Bulk transfer of camera-frame-heavy runs can be hundreds of MB — must be
  resumable and off the hot path; a naive single-shot copy over a home link will
  frustrate. Consider transferring the HDF5 with `camera_frame` optionally
  excluded/streamed separately.
- Two-operator conflict (home + lab) is a real hazard; the single-controller lock
  and local reclaim (§5.2) are mandatory, not nice-to-have.

**Race-condition risks to design against (for Mary's review in Phase 2):**
- stop/abort arriving over the network *during* a stage move or *during* readout —
  same class of race the local `abort()` already handles (`_abort_event` +
  `motor.stop()`); remote abort must funnel into the identical path, not a new one.
- telemetry publisher reading device/driver state from a second thread while the
  scan thread uses it — telemetry must consume *already-emitted* snapshots
  (`ScanResult`, callback payloads, `STATUS` messages), not call drivers
  concurrently. A driver instance is used from one thread at a time.

---

## Appendix — concrete anchor points for implementers

- **State/authority:** `controller/state_machine.py` — `AppState`, `_TRANSITIONS`,
  `StateMachine.can/transition/add_callback`.
- **Run control to expose over control channel:**
  `controller/scan_controller.py` — `ScanController.start`, `pause`, `resume`,
  `abort`, `start_voltage_scan`, `start_z_focus_scan`; callbacks
  `on_point_done`, `on_progress`, `on_finished`, `on_error`, `on_vscan_point`;
  `ScanResult` dataclass = the per-point telemetry payload; fail-safe blocks in
  `_run` (compliance trip → `bias_supply.ramp_to(0)`/`output_off`) and `_end_run`.
- **Device ownership / gating:** `controller/device_manager.py` — `connect_all`,
  `disconnect_all`, `named_devices`, `config_snapshot` (token redaction pattern),
  `data_dir` (run location).
- **Telemetry sources to mirror:** `gui/status_bus.py` `STATUS.message`
  `Signal(str, str)`; the `_ScanBridge` wiring in `tct_gui.py` (~lines 322–333)
  as the thread→Qt-signal template.
- **Optional-import discipline template:** `data/influx_writer.py`
  (`from_config`, `enabled`, lazy import, warn-once, no-op degrade).
- **Bulk payload contract:** `SCAN_DATA_FORMAT.md` + `data/hdf5_writer.py`
  (`run_NNNNN/waveforms.h5`) + `data/save_options.py` (what groups exist / sizes).
- **New config:** a `remote:` block in `configs/devices.yaml`, validated by
  `controller/config_validator.py`; token redacted like `influx.token`.
```
