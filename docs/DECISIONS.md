# Architecture Decision Record (ADR)

Lightweight log of key design and technology decisions, their rationale, and affected areas.
Each row documents: **when decided**, **what was decided**, **why**, **what it affects**, and **current status**.

## Table

| Date | Decision | Rationale | Affected | Status |
|---|---|---|---|---|
| 2026-07-04 | **GUI stack: PySide6, not PyQt6** | Early specs said PyQt6; the codebase was and is PySide6. Treating any PyQt6 mention in requests/old notes as PySide6. Never mix PyQt6 imports. | `gui/*` all modules | **LOCKED** — no PyQt6 code accepted. |
| 2026-07-05 | **numpy pinned `<2`** | PySpin 3.2 wheel (FLIR Spinnaker camera SDK) is built against numpy 1.x C-ABI; bumping numpy breaks the real-camera backend at import. 64-bit CPython 3.10 required for real-camera use. | `requirements.txt`, `TCT_app/devices/camera_blackfly.py` | **LOCKED** — do not bump numpy. Update to PySpin 4.x if available (future work). |
| 2026-07-07 | **Motor backend: keep custom GRBL driver, reject Printrun/printcore** | `printcore` (Printrun project, GPLv3+) would only replace the thin serial layer; every TCT-specific value (GRBL `$J=` jogs, machine/user coordinates, soft-limits, stall-guard, snap-to-detent, auto-detect) would still live in our code. Small reward, large cost: copyleft contamination of an IP-clean publishable repo, plus a full dependency tree (`wxPython`, `numpy`, `pyglet`, `lxml`) that threatens the `numpy<2` pin. Decision: hybrid-harden our own driver with proven Marlin/RepRap robustness patterns (line-number + checksum + Resend retransmit) from the public spec. | `TCT_app/devices/motor_grbl.py`, vendor dependencies | **ACTIVE** — consider Marlin robustness hardening in P2.3. See `docs/research/printrun_printcore_motor_eval.md`. |
| 2026-07-07 | **Bench LAN: static IPs (not DHCP-server-on-PC)** | Instruments (DG4162, scope, etc.) hung off a managed switch that drops mDNS multicast via IGMP snooping, breaking auto-discovery. A PC-hosted DHCP server adds "rogue DHCP" risk and always-on process overhead. For a fixed 3–5 instrument bench, static IPs are simpler, deterministic, and require no server. VISA works with hardcoded resource strings either way (VXI-11 or raw SCPI socket). | Bench LAN topology, `docs/BENCH_SETUP.md`, `TCT_app/devices/waveform_generator.py` (hardcoded 192.168.0.10), oscilloscope connection | **VERIFIED** — 2026-07-07 bench bring-up complete (static IPs, camera/motor/wavegen real-verified; HV/laser pending). See `docs/research/bench_lan_dhcp_static.md`. |
| 2026-07-07 | **GUI overhaul: ScanPanel retired → separate ScanViewerPanel** | The Planner is the only config/start surface for raster and bias-sweep scans. `ScanPanel` (legacy quick-raster form) is redundant and adds UI sprawl. Plan: retire `ScanPanel` widget, build a new `ScanViewerPanel` (live run monitor, kept separate from `AnalysisPanel`). Enables: unified "cockpit style" design system. Design doc: `docs/design/cockpit_style_overhaul.md`. | `TCT_app/gui/scan_panel.py` (retire), new `gui/scan_viewer_panel.py`, `tct_gui.py` panel wiring | **APPROVED** — user decision 2026-07-07; design review (`docs/research/scan_viewer_design_review.md`) completed 2026-07-08. Build order: extract `scan_coordinator` first (steps 1–2 in design doc). |
| 2026-07-08 | **Quick-scan parameter JSONs: dropped, no migration** | Old `quick_params/*.json` files (legacy pre-Planner scan configs) are no longer loaded or saved. User-approved: these are dev artifacts, not user data. Rationale: Planner + `plan_from_config.py` converters make them redundant; a migration utility would add complexity for zero user benefit. | `TCT_app/configs/quick_params/`, `plan_from_config.py` | **RESOLVED** — dropped 2026-07-08 (no conversion needed, no user data loss). |
| 2026-07-08 | **Crew scaling: tune existing agents, add no new seats** | After meta-review: Paul/Noah/Abel/Mary/Samantha/Prometheus + Kiroku/Shiori/Mamoru form a complete crew. Performance bottlenecks traced to token discipline (context bleed, over-briefing) and task routing (senior agents doing Haiku work). Solution: tighten Adam's briefings, grow the Haiku tier (Kiroku adds structured docs, Shiori adds in-repo lookups, Mamoru adds sweeps). No new agent personas. | `.claude/agents/`, agent routing rules in `CLAUDE.md`, token budget | **LOCKED** — crew complete. Future: optimize briefing templates + Haiku dispatch patterns. |
| 2026-07-11 | **QML hybrid frontend** | QML chrome (QQuickWidget islands) + pyqtgraph for ALL real-time plots as sibling QWidgets + existing DetachableTabWidget unchanged. Full-QML migration REJECTED: pyqtgraph 0.2–0.4 ms/frame vs QtCharts 4–6 ms + 25–53 ms jank (measured spike on experimental/qml-shell-spike). Rationale: FastControl/DAQ latency + increasingly complex interrelated UI. Constraints: pin app RHI to OpenGL (Motor GLViewWidget coexistence); Theme QObject singleton fed from gui/style.py; slice 1 = Scope vertical. Evidence: `docs/research/qml_hybrid_architecture.md` §1–7. | `gui/`, `controller/`, `devices/`, `docs/research/qml_hybrid_architecture.md` | **APPROVED** — assessment + spike evidence in research doc. Ratified by user 2026-07-11; ready for slice-1 build. |
| 2026-07-11 | **3-layer law** | **UI / fast Python backend / driver; compute or blocking I/O never on the GUI thread.** Founding violation: Scan Planner huge-scan estimate stall (synchronous on GUI thread). Enforcement: (1) static layer-contract guard test (`tests/test_layer_contracts.py`), (2) GUI-thread watchdog heartbeat test (`tests/test_gui_thread_watchdog.py`). Allowed edge: gui→analysis for offline analysis (4 consumers: analysis_panel, calibration_panel, scope_panel, scan_map_view) — governed by the watchdog, not import rules. Evidence: `docs/research/qml_hybrid_architecture.md` §9. | `gui/`, `controller/`, `analysis/`, `devices/`, test suite | **APPROVED** — layer-contract tests and watchdog tests in flight, landing with slice-1 build. Ratified by user 2026-07-11. |
| 2026-07-11 | **VISA-scan worker deadlock & safety rules** | Intermittent whole-process 0-CPU freeze traced to ABBA GIL vs Qt connection-mutex deadlock: (1) scope worker thread holds GIL during VISA read, (2) GUI thread enqueues a slot while holding Qt mutex, (3) worker thread tries to acquire mutex to deliver queued signal → wait-for-GIL deadlock. Root cause: worker refcount reaching zero on background thread via garbage collection (cycle breaking) → `_ScanReaper` pattern: GUI-thread-affine strong owner ensures worker never freed on non-owning thread. Rule adopted: **any QObject's last Python reference must never be droppable on a non-owning thread**. All cross-thread slots use explicit `QueuedConnection` (audited). pytest-timeout killer thread itself GIL-starved in this class of hang → `pytest.ini` faulthandler_timeout=90 added (backup to timeout watchdog). **Follow-up (2026-07-12, second entry door — py-spy at `SettingsWindow` construction):** `done -> worker.deleteLater` on the worker's *own* loop is equally unsafe — `QThreadPrivate::finish` flushes that DeferredDelete on the worker thread, so `~QObject` (Shiboken GIL re-entry + connection-pool mutex disconnect) still runs off-GUI. Extended rule: **a Python-wrapped QObject must be DESTROYED on the GUI thread, not merely have its Python refs dropped there** — `_ScanReaper._reap` re-homes the finished worker via `moveToThread(app.thread())` then `deleteLater`. **Head #2 closure (2026-07-12, commits 7ac5304 + a69af95):** verified `_ScanReaper._reap()` runs as DirectConnection on thread.finished (blocks worker until re-homing completes), then queued _reap in track() proceeds. CONNECTION ORDER is load-bearing: DirectConnection re-home MUST precede queued _reap or worker stays off-GUI. Recorded invariant: **panel worker teardown MUST remain blocking quit()+wait() on GUI thread (parks GUI thread with GIL released, so ABBA counter-party can't form); do NOT convert any panel worker to async/non-waiting teardown without moving its worker destruction GUI-side first.** Latent audit: 8 long-lived panel workers (camera/laser/scope/motor/bias/intensity `finished→worker.deleteLater`, planner `_EstimateWorker`, liveness) share the pattern but only at controlled teardown (low overlap) — follow-up candidates, defense-in-depth, not yet converted. | `gui/settings_window.py` (_ScanReaper), `gui/scope_panel.py` (worker QueuedConnection audit), pytest config, test suite (smoke-test full suite, worker-teardown regression), deadlock-free validation | **RESOLVED** — 2026-07-11 autonomous hardening + regression tests (4d887b4 + 97c07f4). 2026-07-12 head #2 closure + ordering validation (7ac5304 + a69af95). Mary APPROVE. |

---

## Decision-making process

Decisions are recorded here *after* they have been made and tested (or explicitly approved by the user). Each row links to supporting research, design docs, or code commits in the repo.

**How to update this table:**
- Add a row only after a decision is **finalized and approved**.
- Always cite supporting docs: `docs/research/`, `docs/design/`, commit SHAs, or `CLAUDE.md` rules.
- Mark status as **LOCKED** (immutable), **ACTIVE** (in progress), **APPROVED** (awaiting build), or **RESOLVED** (completed).

---

## How decisions link to architecture

Every row above is either:
1. **A technology choice** that constrains the codebase (numpy, PySide6, GRBL).
2. **A design principle** that shapes code organization (no copyleft, static IPs, design system).
3. **A user-approved roadmap commitment** that guides the next sprint (ScanPanel retirement, crew tuning).

When working on code, check this table:
- Changing the GUI stack? Check the PySide6 row.
- Adding a new device backend? Verify it follows the static-IP / VISA pattern.
- Refactoring device manager? Recall the multi-channel bias + polarity decision.
- Adding an agent? This crew is complete (2026-07-08 meta-review).

---

## Archive

*Resolved decisions are moved here once work is complete. (Future: when table grows large, archive old entries.)*

- *None yet.*

## 2026-07-12 — Cockpit design system v4 RATIFIED as canonical (pending 2 open items)

7-seat design council (crew + Prometheus SOTA research + Codex adversarial +
Ollama advisory), two iteration rounds. Canonical spec:
`docs/design/cockpit_design_system.md` (eight laws, tokens, type scale,
data-ink rules, lifecycle/hardware-truth mapping, panel recipes, D0-D6
roadmap with gates, Abel's 8-rule modularity charter). Interactive reference:
`artifacts_claude/tct_cockpit_design_v4_final.html`. All GUI work hard-follows
this spec; violations do not merge. OPEN for Kaya: arm-envelope model
(two-step latch) and slow-control excursion policy.

## 2026-07-12 — Kaya ratifies the two open design-system items

1. **Arm-envelope model RATIFIED**: one two-step latch (Arm: hold-3s or
   press-twice → armed state w/ timeout → Execute) authorizes the FULL
   enumerated envelope (channels, HV range, ramp shape, motion bounds) once
   per run; the executor re-validates every live dangerous action against
   the armed envelope and fail-closes anything outside it. No per-BiasStep
   modals. HV is approved exactly once, explicitly, with the numbers shown.
2. **Slow-control excursion policy RATIFIED**: WARN → safe-hold pause
   (motion stopped, HV held, operator prompt w/ ack/resume/abort);
   ALARM → full fail-safe abort (HV ramp-down, motion stop, writer flushed).
   Sensor UNAVAILABLE/stale counts as WARN. Thresholds per channel in
   devices.yaml (validated). Both items: Mary review mandatory before merge.

Migration mode (Kaya, same day): implementation first, heavy verification
batched at milestones; per-beat tests targeted-only, full suites at phase
gates.

## 2026-07-12 (night) — Kaya RATIFIES the danger-gate boundary for motion

Context: the Coffee-Break-of-Kings retro exposed a real safety rule 2 gap —
neither the bias panel (manual HV ramp, IV/vscan sweeps, polarity) nor the
motor panel (jog, absolute move, center, home, zero-here) routed through a
`DangerGate`, while `calibration_panel` already did. Fixed in a4d05f6 (HV)
and the motion follow-up.

**RATIFIED — where the gate sits:**

1. **GATED** (unbounded or frame-changing): HV enable/ramp (incl. IV and
   bias+waveform sweeps), HV polarity switch, **homing**, **absolute /
   center moves**, and **zero-here** (it does not move the stage, but it
   redefines the user origin that every later soft-limit check validates
   against — the frame-mix bug class Kaya hit). All confirm BEFORE any
   driver call, with the real numbers in the dialog text; `gate is None`
   REFUSES the action (never degrades to "no gate = no confirmation").
2. **UNGATED BY RULING — jog** (Kaya, 2026-07-12): a jog click is itself the
   explicit, deliberate, bounded act (fixed step, soft-limit checked). A
   modal per jog would make the panel unusable and would train operators to
   click through dialogs — a worse safety outcome than no dialog. Jog keeps
   the amber motion class and the soft-limit guard. Code routes motion
   through one `_confirm_motion()` helper, so re-gating jog stays a one-line
   change if the bench ever demands it.
3. **UNGATED BY LAW 5 — fail-safe stops** stay one-tap: STOP, emergency
   HV-off, "All outputs off". A stop can only make things safer; a gate in
   front of it is itself the hazard.

Rationale recorded because it is a deliberate *narrowing* of a literal
reading of safety rule 2 ("stage motion" would include jog), made by Kaya
with the trade-off stated. Any future agent proposing to gate jog must bring
this entry to Kaya, not silently "harden" it.

## 2026-07-13 — Sequencer envelope semantics RATIFIED

ONE combined envelope per routine queue (single authorization step). Arm via
hold-3s or press-twice → ONE envelope covering: max HV, total travel, every
routine named in the arm text. Executor re-validates every step at runtime.
Re-arm-per-routine rejected: defeats the unattended overnight-run purpose.
Rationale: unattended operation requires a single, explicit, conscious envelope
decision; per-routine re-arming forces operator intervention, breaking autonomy.
Affects: `controller/scan_controller.py`, `gui/scan_planner_panel.py` (arm UX).
Status: APPROVED — ready for sequencer build (Wave 0).

## 2026-07-13 — Bias-panel IV sweep: both stop causes now visible RATIFIED

Two distinct stop reasons emit a visible notification: (1) compliance limit
(previously silent), (2) hardware trip (already visible). Rationale: operator
honesty — silent failure to reach target voltage hides the reason from the bench
log. Affects: `gui/bias_panel.py`, `devices/bias_supply_*.py`. Status:
APPROVED — implement in bias-panel enhancements.

## 2026-07-13 — "Real transparency" backdrop added alongside opacity slider RATIFIED

Windows 11 acrylic/mica DWM backdrop filter (content stays opaque; plots/camera
always opaque per design law 5) ADDED as a new toggle, independent of the
existing whole-window opacity slider. Both can coexist. Opaque fallback on
non-Win11/unsupported RHI. Ships with "none" default (opaque backdrop) until
Kaya verifies rendering on real display hardware. Rationale: DWM backdrop gives
OS-native gloss without overexposure; separation from opacity slider gives users
two axes of visual control. Affects: `gui/style.py`, theme system, RHI layer.
Status: APPROVED — ready for GUI build (Wave 0).

## 2026-07-13 — Big-wave execution order RATIFIED

Wave 0 (HV gate hardening) → two structural blockers (StateMachine.transition
lock, BiasChannel.output_on rename) → four feature lanes in parallel (sequencer,
HDF5+capture_photo, backdrop, e-field/metrology) → Wave 1/3/4 items via free
lanes. Rationale: critical-path safety-system work lands first; structural
changes unblock all downstream feature work; parallelizable features ship
together to consolidate review gates. Affects: `docs/ARCHITECTURE.md`, task
queue, review cadence. Status: ACTIVE — execution in flight (2026-07-13).

## 2026-07-13 — Stitched-image feature in scope for big wave RATIFIED

Stitched-image / mosaic feature APPROVED for Wave 0: (1) survey preset (grid of
move+capture_photo planner steps), (2) offline mosaic view in analysis_panel
(affine placement, omitted frames shown as gaps, never zero-filled). Rationale:
seamless integration into existing capture/planner flow; affine alignment avoids
optical calibration complexity. Affects: `gui/scan_planner_panel.py` (preset),
`gui/analysis_panel.py` (mosaic viewer), `analysis/` (affine stitch logic).
Status: APPROVED — ready for build.

## 2026-07-13 — Sensor orientation via opencv-python-headless RATIFIED

Sensor orientation ("bonding-machine" alignment) implemented via ArUco fiducials
+ classical template matching/contours, explicitly NO CNN (no dataset, no torch).
opencv-python-headless chosen to avoid Qt-plugin clashes with PySide6. NEW
TCT_app/vision/ package created; analysis/ stdlib+numpy contract unchanged.
Lazy import + clean feature-disabled degradation. Rationale: no ML dataset
available for proprietary alignment task; classical CV sufficient; headless
variant eliminates Qt plugin conflicts endemic to GUI-heavy PySide6 apps.
Affects: new `TCT_app/vision/` package, `analysis/` interface, requirements.txt.
Status: APPROVED — ready for build.
