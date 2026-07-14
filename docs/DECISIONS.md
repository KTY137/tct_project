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
queue, review cadence. Status: APPROVED — sequencer A1-A5 complete incl. closure fixes, Mary verdict CLOSED; Tracks B/C/D complete; E-track through E2/E6a landed, E3/E4 in flight at report time.

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

## 2026-07-13 — v6 glass material direction RATIFIED

visionOS-glassmorphism references (design_assets/, 8 images) adopted as the
v6 material north star on top of the v5 composition system. Ratified against
the A/B decision artifact (artifacts_claude/tct_bias_glass_ab.html — side A =
byte-exact style.py DARK tokens, side B = glass target): deeper radii (cards
16->20), specular hairlines (dark alpha 0.045 -> ~0.14), glass-equivalent
surface ladder via pre-blended color-mix, chip/pill grammar, fluent eased
motion. HARD LAW carried over: danger controls (kill switch, ARM latch, trip
banner) stay opaque and color-stable in every skin — glass ends at the safety
boundary. Kaya approved the artifact and delegated implementation decisions
to Adam ("du entscheidest, alles für das peak design", 2026-07-13).
Affects: gui/style.py tokens (both themes), gui/panel_kit.py, later an
animation-kit beat. Status: APPROVED — token beat in flight.

## 2026-07-13 — QML-hybrid boundary RATIFIED (shell default stays probe-gated)

Boundary per Prometheus memo (docs/research/qml_hybrid_standard_decision.md):
QML is the standard for shell chrome + light motion ornaments ONLY; QWidgets
remain the standard for all 13 panels; full per-panel QML migration REJECTED.
SAFETY TIGHTENING: no safety-critical control (NOT-AUS, ARM, kill switch,
DangerGate) is ever reimplemented in QML — single-implementation QWidgets.
No live MultiEffect/ShaderEffect glass as a standard (does not render on the
software/RDP path; unrealistic at 60 fps on the Intel iGPU) — the glass LOOK
ships via pre-blended tokens + window-level DWM backdrop. The classic ribbon
shell is FROZEN as functional fallback (QML-load failure, RDP): maintained,
but no longer a design target — ends the double-design cost observed in W3
(style.py + Shell.qml paid twice for one change). Flipping TCT_QML_SHELL to
default ON stays gated on the decisive probe on the real laptop (RHI/
GLViewWidget coexistence, detach, <5% idle CPU, one RDP session) — probe spec
in the memo; queued as a Kaya bench-checklist item. Decision taken by Adam
under Kaya's explicit delegation (2026-07-13).
Affects: gui/qml_shell.py, gui/qml/Shell.qml (design target), style.py QSS
(fallback, frozen), review routing for shell beats.
Status: APPROVED — boundary in force; shell default pending probe.

## 2026-07-13 — Orchestration upgrade after plan change RATIFIED

Kaya upgraded to an effectively unconstrained token plan; the scarcity-era
routing rules were retuned (Kaya: "ratifiziert", 2026-07-13 evening).
Changes: (1) review cadence — safety/concurrency beats get an immediate
per-beat Mary review, remaining beats in thematic parallel per-wave
batches; Mamoru wave-boundary standups become standard. (2) Shiori
brief-check before every non-trivial dispatch (two brief bugs landed
today that it would have caught). (3) Judgment-beat Opus override:
discretionary design/contract beats run Opus regardless of agent default.
(4) Report caps: findings/risks/handoff fields widened to ~1200 chars.
(5) Free-lane-first (2026-07-12) superseded: free lanes are parallel
value (second opinions, sweeps, mechanical chores), not a dispatch
precondition. Explicitly unchanged: test economy, test-lane policy,
session hygiene 1-4, hardware safety rules (PROTECTED). Rationale: the
binding constraints are now orchestrator context and file locks, not
tokens — spend goes into per-beat verification depth, not agent count.
Affects: CLAUDE.md orchestrator sections. Status: APPROVED — in force.

## 2026-07-13 — Guarded-exchange device-layer pattern ADOPTED

Guarded-exchange pattern adopted as the device-layer concurrency standard,
staged per `docs/design/guarded_exchange.md`: G0 base helpers + detector
landed (commit 7a55d03); motor + bias as own track; scope/wavegen/camera
born-guarded in D2. Pattern ensures transport-lock invariants across
multi-threaded access (no interleaving of GCS/SCPI exchanges with
concurrent pollers or state queries). Safety-first rationale: any two
threads touching shared hardware must serialize at the transport layer,
and the contract must be verifiable per-driver. Kaya: "ja darfste alles
machen hast mein GO" / "Baller durch" (2026-07-13, after asking "was
meinst du mit guarded exchange" and receiving the explanation + earlier
proposing the abstraction himself). Affects: `devices/`, `tests/`.
Status: APPROVED — foundation in place, phased adoption.

## 2026-07-13 — Capability safety-routing SHAPE

Capability safety-routing shape = option (c): class floor + monotone
add-only override (per `CAPABILITY_MODEL.md` §14.1). Option (a)
rejected as unsafe per Mary's adversarial review (permits role downgrade).
Pattern: a safety-routing capability assigns a class (e.g. "motion") and
accepts override-to-higher only, never downgrade. Fail-closed on unknown
class. Kaya: "ich bestätige". Affects: `controller/capability.py`,
`controller/arm_envelope.py`. Status: APPROVED — ready for capability
bootstrap (D1/D2).

## 2026-07-13 — Multi-channel HV capability naming

Multi-channel HV capability naming per `CAPABILITY_MODEL.md` §14.2:
`bias.voltage` is the primary-channel ROLE id (backward-compatible); for
secondary channels, `bias.ch{n}.voltage` identifies physical channel n.
`HVSource.channel` attribute + swept/channel naming ensures UI can surface
"which HV supplies which bias loop" distinctly. Harmonizes multi-channel
IV sweeps with capability-gating. Kaya: "ja nick ich ab". Affects:
`controller/bias_channel.py`, `devices/bias_supply_base.py`, `gui/`.
Status: APPROVED — ready for multi-channel IV routing (D5).

## 2026-07-13 — Platform seed ships MIT-licensed

Platform seed ships MIT-licensed at repo root: `LICENSE` file (MIT
copyright 2026 Kaya Yesilyurt) + `PLATFORM_SEED.md` license clause.
e4control functionality reimplemented-from-prior-art per vendor docs,
upstream informally-confirmed open. Enables: publishable, IP-clean repo
baseline with no copyleft taint (rejects Printrun GPLv3+ per 2026-07-07
decision). Kaya: "Put an MIT Lizenz in den Platform_Seed damit keiner
meckert." Affects: `/LICENSE`, `PLATFORM_SEED.md`, `CLAUDE.md`. Status:
APPROVED — foundation in place.

## 2026-07-13 — Blanket GO on pending operational gates

Blanket GO issued on pending Phase-0.5 blockers: S2 manifest v0.2 RATIFIED;
Phase-0.5 merge authorized on next bench-green evidence; stale worktrees
`agent-aa19d2caf98c928dd` + `slice1-ui` removal authorized and EXECUTED.
**Scope note (Kaya, same message):** this repo prepares TCT_app as the
platform BASE only — LabControl construction is explicitly out of scope
here. Kaya: "ja darfste alles machen hast mein GO." Affects: phase gates,
branch hygiene, merge readiness. Status: APPROVED — blockers cleared.

## 2026-07-14 — Danger topology RATIFIED

**A dangerous action belongs to the PANEL that owns the hardware, NOT to the shell.**
The shell may *display* hazard state (HV live, voltage, leakage, motion, scan) permanently and prominently, but it must **never trigger** a dangerous action. No presentation-layer mediator holding the bias supply / motor / scan controller is to be built.
Rationale: moving danger into the shell forces a mediator, makes muscle memory a safety mechanism, and produces candidates like A's HV-on-double-click defect; it is also the single cost driver (25–34 beats vs ~10 for a panel-owned design).
Consequence: `bias_panel.py` keeps gating its own ramps through the injected `QtDangerGate`; the planner/sequencer keep their own `ArmLatch`. Candidate A's "always-visible armed rail" is **not** adopted; its vitals strip is (display only).
Affects: `gui/bias_panel.py`, `gui/scan_planner_panel.py`, `controller/scan_controller.py`, `controller/arm_envelope.py`.
Status: **LOCKED** — safety-first design law, no reimplementation of danger mediators.

## 2026-07-14 — Detachable panels RATIFIED

> "Naja wir wollen ja aufjedenfall unsere panels behalten also das die detachable sind" (Kaya)

**`gui/detachable_tabs.py` stays the detach ENGINE.** QML is a *view* over it (the `_TabShelfAdapter` pattern in `gui/qml_shell.py`) — the detach mechanism is never reimplemented in QML. Any design that removes, degrades, or reimplements panel detachment is rejected on arrival.
Consequence for the GlassShell: every detached panel is its own top-level window ⇒ its own DWM material and its own per-window tier resolution (already supported: G-B1's `_BackdropGuard` installs on every material-capable top-level; `gui/glass_env.py`'s `decide_tier` is per-environment and `shell` is an env field).
Affects: `gui/detachable_tabs.py`, `gui/qml_shell.py`, `gui/glass_env.py`, `gui/backdrop.py`.
Status: **LOCKED** — permanent operator workflow feature, no removal or reimplementation.

## 2026-07-14 — Owned glass is the foundation; the OS is the garnish (Kaya)

Verbatim: *"das windows glass sollte immer nur ein fallback bleiben wenn überhaupt — unser eigenes Glass wäre robuster für mehrere Systeme und könnte man schöner machen, so dass es näher an den Designs ist die vorgeschlagen wurden von unserem Schmied"*

**We render the glass ourselves** (in-scene, over an app-owned ambient ground). The DWM window material is a garnish and a fallback, not the foundation.

Rationale, and why it OVERTURNS round 02's premise: Round 02 killed glass for a *derived* reason — "an in-scene pane has nothing to blur, because the workspace is a QWidget tree in a different scene graph, and DWM only frosts the desktop". Logically correct; aesthetically dead. **The mockups Kaya liked never used DWM glass.** CSS `backdrop-filter` blurs what is beneath the pane *in the page* — i.e. **the app's own content**. The look was always app-owned glass over an app-owned ground. Measured and available (`bbe3b10`): in-scene `MultiEffect` frosts app content **live, 59–60 fps, 8× edge reduction, 0 crashes in 80 launches**. What it cannot do is blur the desktop — and we no longer need it to.

Consequences: **identical on Windows, Linux and RDP** (no compositor contract), **deterministic and CI-testable** (golden pixels), and **ours to make beautiful**. This RESTORES the Glass Council's original convergent verdict — *"self-composited baked-blur glass as foundation (identical on RDP/Linux, CI-testable), DWM material as garnish"* — which the spikes had appeared to overturn but in fact support. The night's DWM work is NOT wasted: it is the WINDOW rung of the `GlassTier` contract and the garnish tier.

Affects: `docs/design/glass_council/SYNTHESIS.md` (§2.2 ratification), `gui/glass_env.py`, `gui/qml_shell.py`, glass-system shell selection.
Status: **RATIFIED** — foundation-tier decision, part of the GlassShell path.

## 2026-07-14 — Candidate C's spirit, not C's mechanic (Kaya)

Verbatim: *"Kandidat C ist bis jetzt am besten von round 1, round 2 verschluckt zu viel glass feeling mit den ganzen opaquen panels"* · *"lass den Schmied jedes Panel nach Kandidat Cs philosophy designen"* · *"alles, dass Kandidat Cs spirit umgesetzt wird, auch wenn wir Regeln biegen und brechen müssen"*

**Adopted: candidate C's visual LANGUAGE** — glass cards, real translucency, structural depth, and the three-tone ladder (the only one in round 01 that survived the tier it promised to survive).
**NOT adopted: candidate C's board MECHANIC** — the freely-composable board, "situations" instead of tabs, three densities per panel. That is what cost **47–64 beats** and created C's one real safety hole (a draggable Safety card makes HV legibility an operator *preference*).

Tabs + detachable panels stay (ratified). Round 03 is briefed on exactly this split. If Brokkr believes the board mechanic is essential to the spirit, he must argue and price it, not smuggle it.

Adam's standing rule (from Kaya: *"too many rules restrict your thinking"*):
> **A rule that encodes a BELIEF gets attacked. A rule that encodes a CONSEQUENCE does not.**
> "Glass cannot do X" is a belief — measure it and overturn it (four such rules died on 2026-07-14). "HV requires confirmation" is a consequence — a human is standing at a probe station.

Note for the record: **candidate C never violated a consequence rule.** Loki verified C honoured the hazard-opacity law byte-for-byte. C was never unsafe; C was expensive.

Affects: `docs/design/cockpit_design_system.md`, panel-kit specs, round-03 design briefs.
Status: **RATIFIED** — design-system guiding principle, encoded for future panel work.
