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

## 2026-07-14 — Semantic state ink may live on OWN-ground glass (Kaya)

Verbatim: *"ja drop die regel wir sind designer und designen geile Sachen"*

**Extends the glass INK law.** The old rule pinned only neutral ink (`text`/`muted`) as legal TEXT on a registered glass surface (`tests/test_glass_text_contract.GLASS_SAFE_TEXT_TOKENS`). That rule encoded the **unknown-desktop belief** — a glass pane could be composited over any wallpaper, so a coloured state word could not be guaranteed legible. That belief **died with the owned-glass ratification** (`23aea87`, above): the ground beneath every in-scene pane is now the app's own **band-clamped ambient wash** (ΔL* ≤ 4.0, kit §1.1, measured 3.58 and pinned by `tests/test_ambient_ground.py`), not a wallpaper. Per the standing rule directly above — *a rule that encodes a belief gets attacked* — the belief was measured and overturned.

**Measured basis.** `scripts/kit_contrast_check.py` (arbitrated `28e6dec`) walks the exact shipped compositing model — the glass fill one rung up, at the surface's alpha, over the **worst legal ground** (the ΔL* 4.0 band edge). Result: every semantic ink (`good`/`warn`/`crit`/`accent`/`sim`) clears WCAG AA on DARK glass at **every** alpha; on LIGHT glass the binding pair is `good`, which needs **α ≥ 0.24** (`crit` needs no floor; `warn`/`accent`/`sim` 0.18–0.21). The kit ships 0.55 (pane) / 0.86 (light card) / 0.62 (dark card) — 2–3× the floor. `tests/test_glass_text_contract.py` now (a) carries the semantic tokens in the whitelist and (b) **derives** that floor live and asserts every shipped/clamp glass alpha stays ≥ floor + a 0.10 buffer, naming the binding token pair on failure — so a future alpha tweak below the floor fails the suite rather than silently shipping unreadable state text. Render proof (dark + light, ratios printed): `artifacts_claude/semantic_ink_on_glass/`.

**What did NOT change.** Hazard surfaces stay **opaque at every tier** with their existing ink rules (the laser banner idiom; `danger_fill`/`on_danger`/`on_armed` stay off glass); **wells still refuse semantic ink** (kit §4.4 — measured failure on the light well, `tests/test_material_contract.py`); **hot-path islands** (camera view, pyqtgraph plots) are untouched. The decoupling on OPAQUE chips (`4ca8331` — ink-on-a-wash-of-itself) stays; that was a different bug and its guard remains.

**PROTECTED-region note:** the glass ink law is PROTECTED. This change was made with Kaya's **explicit per-change approval** (verbatim above), not autonomously.

Affects: `tests/test_glass_text_contract.py`, `docs/DECISIONS.md`, `artifacts_claude/semantic_ink_on_glass/`. (No QSS gate existed — the law lived only in the test; `gui/style.py` untouched.)
Status: **RATIFIED** — glass ink law extended; enforced by the derived-floor test.

## 2026-07-15 — LANTERN is the QML kit; the ground auto-calms during a run (Kaya)

Verbatim: *"DO LANTERN"* · auto-calm amendment: *"you have my nod"* — the nod
was followed by his question *"but what is auto calm?"*; the mechanism (idle =
flow per off/subtle/full + speed; RUNNING = freeze to static wash; resume after)
AND the one collision (if he wanted glass alive *during* runs, auto-calm is the
opposite) were explained in full, and **"DO LANTERN" came after that
explanation** — Lantern's spec contains auto-calm verbatim, so the pick is
informed consent for both decisions.

**Adopted: candidate LANTERN** (`docs/design/qml_kit_forge/candidate_lantern.md`)
as the U1.5 QML component-kit direction — one `Surface` material (elevation rung
+ baked position-sampled frost + edge ladder + springs), the living ground as
layer 0 and the frost source, living glass default **subtle**, deliberate
classic-shell divergence during U1–U6 (classic = fallback, not design target —
consistent with the owned-glass ratification of 2026-07-14).

**kit.md §1.2 amended** (PROTECTED region, per-change approval given as above):
"never animates during a run" → "auto-calms to static during a run", with the
band law holding per frame (washes move position, never alpha — what makes
living glass legal at all).

**Scope refinement (Kaya, same session):** verbatim *"also auto calm should
only then apply to that panel"* — the calm is **PANEL-SCOPED**: during a run,
only the ground behind the panel that owns the run stills; the rest of the room
keeps flowing. A detached panel is its own top-level with its own ground, so it
calms whole. Two consequences, on the record: (1) the Baldr distraction gate is
no longer fully satisfied by auto-calm — motion in the operator's periphery
during a live run is back in scope, explicitly booked as attack-pass item #1;
(2) a locally-calm pane now *signals* which panel is running — permitted as a
redundant cue, but never the only run indicator (the status chip stays the
carrier; state never by motion alone).

**Conditions carried with the ratification** (Adam's recommendation, on which
the pick was made — "the frost-bake spike is the entry ticket"):
1. The **frost-bake spike runs BEFORE any U2 architecture commits to Lantern**:
   N sampling panes + one pyqtgraph island at 30 Hz, re-bake 6–12 Hz, measured
   on the weakest realistic GPU (the laptop iGPU), per the standing
   spikes-are-routine rule. If the bake fails, Lantern collapses into
   Twin-with-springs and the pick returns to Kaya with the numbers.
2. The **Loki/Baldr attack pass** runs against Lantern WITH the spike numbers
   in hand (queued after U0; attack surface pre-mapped in
   `docs/design/qml_kit_forge/00_comparison.md` §3).
3. **Twin's Theme-gap audit is prerequisite homework regardless of pick**
   (real `gui/qml_theme.py` TOKEN_MAP gaps); **Ledger's LOCKED-safety-row idea
   stays available for merge** — a merge is a decision, not a diff.

What did NOT change: hazard surfaces opaque at every tier; the never-migrates
list; the ink laws; the Baldr distraction gate (auto-calm IS its satisfaction).

Affects: `docs/design/iterations/glasshell-cockpit/round-03/kit.md` §1.2,
`docs/design/qml_kit_forge/`, the U1.5 deliverable, U2 reference implementation.
Status: **RATIFIED**.

## 2026-07-15 — Design authority delegated to Adam: token law + design changes (Kaya)

Verbatim: *"u have all token law approvals to implement the best looking awesome
design if you need to change stuff do it dont ask me again"*

**Adopted (delegation, per the masterplan's delegable-gates mechanism):**
token-law approvals — including NEW token families — and design-domain change
decisions during the QML migration are delegated to **Adam**, with post-hoc
logging in this file instead of pre-asking. The quality bar he set is explicit:
*the best looking awesome design*.

**Immediately exercised:** the Lantern shadow token family (`shadowInk`,
`shadowA..D` → `shCard`/`shPane`/`shFloat`) is **APPROVED** for promotion into
`gui/style.py` and the QML Theme bridge (resolves Loki MINOR-5, 2026-07-15).

**Explicit carve-outs (NOT delegated — constitution unchanged):**
1. Hardware safety rules 1–6 and every safety sub-clause of ratified entries
   (hazard-surface opacity, danger topology, the never-migrates list) remain
   PROTECTED and personal to Kaya — design authority is not safety authority.
2. Reversing one of Kaya's own explicit design ratifications (e.g. dropping
   LANTERN, un-ratifying panel-scoped calm) still goes back to him; the
   delegation covers implementing and evolving the ratified direction, not
   overturning it.
3. Constitution-class gates from the masterplan (S0, S2, seed tag, M2
   go/no-go, U-track supersede, U3 checkpoint) stay personal as listed.

Affects: `docs/DECISIONS.md` process, U1.5/U2 design beats, `gui/style.py`
token family growth, `gui/qml_theme.py` TOKEN_MAP.
Status: **RATIFIED** (standing delegation).

## 2026-07-15 — Post-attack-pass rulings (Adam, under the delegated design authority)

Both attack passes on ratified LANTERN are in (`docs/design/qml_kit_forge/
attack_loki.md`, `attack_baldr.md`). Rulings, logged post-hoc per the
delegation above:

1. **Run-active motion clamp (Baldr MAJOR-4 adopted):** whenever ANY run is
   active, the living-glass effective speed clamps to ≤1.0× app-wide
   (worst legal case was full × 2.0 = ~8% viewport / 45 s period in panels the
   operator watches during the same acquisition). This BOUNDS the ratified
   panel-scoped calm; it does not reverse it — the room still flows, calmer.
   Baldr's verbatim challenge to the panel-scope assumption is ON RECORD in
   attack_baldr.md for Kaya to read; the clamp is the narrowest fix and ships
   unless he overrules.
2. **Stale state is ink-only (Baldr BLOCKER-1):** the shipped
   `MetricTile.qml` `opacity: 0.6` stale dim (measured AA failure: crit
   5.02→2.59 dark, warn 5.43→2.52 light) is removed in favor of ink-based
   staleness per Lantern §5; kit.md §4.3's Tile-dim permission is amended to
   cap any opacity cascade over semantic ink at the measured legal ceiling.
3. **Ring-vs-own-fill becomes a standing check (Baldr BLOCKER-2):**
   `kit_contrast_check.py` gains the ring-on-component's-own-fill
   measurement; the spec must state the ring offset convention explicitly.
4. **Hazard-rung focus text (Baldr BLOCKER-3):** the ambiguity ("no halo" vs
   "ring is the accessible channel") is resolved in favor of: RING ALWAYS
   PRESENT on hazard rungs, halo never — focus visibility on the highest-
   stakes controls is non-negotiable (this direction strengthens the safety
   posture; the hazard-opacity law itself is untouched).
5. **Dead-zone law names the halo (Baldr MAJOR-5):** the enumerated
   translucent-pixel mechanisms extend from {sample, shadow} to {sample,
   shadow, halo} — a strengthening of a protective law. *(Location
   correction, caught by Brokkr in the revision pass: the enumeration lives
   in candidate_lantern.md §8 and kit.md §7 law 4 — not "kit.md §8" as this
   entry first said; implemented at both real locations.)*
6. **Spec reconciliation (Loki BLOCKER-1/MAJOR-2):** candidate_lantern §3.2/§7
   rewritten to the true post-ratification behavior — the bake runs at idle
   rate during scans; only the run-owning pane freezes its own sampler
   (mechanism (a), stale-crop seam named and handed to visual review);
   "zero material cost during acquisition" claim retired, replaced by the
   measured standing cost + measurement B as U2 entry gate.

Execution: Brokkr revision pass (spec files + kit.md design text) + Noah
micro-beat (MetricTile.qml, kit_contrast_check.py). Measurement B queued as
U2-entry requirement. Safety carve-outs untouched.
Status: **ACTIVE** (delegated decisions, post-hoc logged).

## 2026-07-15 — Ruling 7: run-ownership convention for panel-scoped calm (Adam, under the delegated design authority)

Source: Loki's routing note ("the facade must resolve WHICH panel owns the
run"), investigated by Mary (review of 6452da3, item 2). Finding: the app is
single-run by construction (one global StateMachine/ScanController/
ScanCoordinator; the Sequencer drives that same coordinator), so the
facade's single `active` flag suffices — the gap was definitional, not
structural.

**Ruling:** "the run-owning panel" for panel-scoped calm (kit.md §1.2) is
defined as **the top-level currently hosting the ScanViewer/ScanStatusStrip,
gated by `facade.active`** — explicitly NOT the arming panel (Planner or
Sequencer). This definition survives Planner-close-mid-run and the detached
ScanViewer (which calms whole, per Lantern). Sequencer-driven runs stay
ScanViewer-scoped; if that ever changes, the extension seam is a read-only
run-source/owner STRING on the facade, fed like runPath/scanType — never a
controller reference (the read/command boundary is untouched).

Consequences: (a) queued spec chore — candidate_lantern §7's "ownership
resolves through run_state_facade only" overstates the facade and will be
amended to name the ScanViewer-host convention (next spec pass); (b) the
U1 staging design pins this convention in its run-ownership seam section
(relayed to the architect in-flight); (c) under ruling 1's fallback
(run-active GLOBAL calm) the question is moot — no ownership resolution
needed.
Status: **ACTIVE** (delegated decision, post-hoc logged).

## 2026-07-15 (night) — Ruling 8: distillation balance as a U2+ stage-gate criterion (Adam, under the delegated design authority; Kaya-directed)

Source: Kaya's migration-vs-rewrite deliberation (external Gemini second
opinion raised "migration leaves too much legacy code"). Outcome of the
discussion: **migration confirmed, rewrite rejected** — with Kaya's
binding synthesis-routine directive (verbatim): *"behalte Destillation/
Struktur-maxxing mit altcode minimizing + verification am ende im
gedächnis das hört sich nach na guten Syntheseroutine an."*

**Ruling:** the standing U-stage gate gains a distillation-balance
criterion for U2 and later: every stage gate reports net LOC and an
explicit delete list; a stage that only adds does not pass. Deliberately
retained code (safety controls, GL islands, the never-migrates list) is
ratified essence, never residue. U1 is exempt — viewmodel and old face
legitimately coexist until the QML face replaces the QWidget face.
Written into docs/ROADMAP_MASTERPLAN.md standing-gate bullet. Rationale
on the record: migration = distillation (extract essence fraction by
fraction with tests as the thermometer, forced deletion per stage);
rewrite = re-synthesis from memory (unspecified behavior is lost, which
for a lab-control app is a safety cost, not an aesthetic one).
Status: **ACTIVE** (delegated decision, post-hoc logged; principle also
persisted in Adam's cross-session memory).

## 2026-07-15 (night) — Ruling 9: session-scoped QApplication in conftest; §7.4a gate letter amended (Adam, under the delegated design authority)

Source: Mary's wave-1 RISK finding (VM suites error solo in the
_widget_reaper teardown) → Noah's micro-beat guard uncovered the deeper
defect: the file-local bare-Core `_app()` pattern
(`QCoreApplication.instance() or QCoreApplication([])`) permanently
poisons the process-wide Qt singleton — any widget test running later in
the same process crashes natively (exit 127, no Python exception). The
old reaper bug had been masking this as an accidental circuit-breaker;
alphabetical collection dodges it in full runs by luck, not by design.

**Ruling:** tests/conftest.py gains a session-scoped autouse fixture
creating ONE offscreen QApplication before any test; file-local `_app()`
helpers then always find it via .instance() and the bare-Core hazard
class is closed for all current and future suites, in one file. The U1
gate letter (u1_staging.md §7.4a) is amended accordingly: VM suites
prove headless-ness offscreen; the no-widget boundary is proven by the
standing-law test pair, not by the application class. Implementation +
verification: noah-conftest beat (incl. the previously-crashing
VM-first mixed order, which must fully pass).
Status: **ACTIVE** (delegated decision, post-hoc logged).

## 2026-07-15 — U1.5 kit spec v1 signed (Kaya): the [Kaya] gate on the QML component kit

Kaya's morning checklist item ③: **"I approve the kit spec from the
smith"** — `docs/design/qml_kit_forge/kit_spec_v1.md` (Brokkr
consolidation, commit 1e35626) is **signed as the binding QML
component-kit contract** for U2 and every later U-stage: §§1–6 (Surface
material + rungs + state table, 15-component inventory, focus/contrast
laws, motion + panel-scoped auto-calm incl. the ruling-7 ownership
convention, 42-token bridge contract).

Scope notes, exactly as the spec stages them (§7):

- **§7.1 measurement-B thresholds are ratified in KIND, not in number.**
  The harness's proposed floors (island 28 Hz, qml 55 fps, retention
  0.90/0.80, jitter CV rule) bind only after the live operator run
  prints real numbers and Kaya confirms/tunes them. Measurement B
  remains the U2 **entry** gate; if it fails, the ratified fallback is
  run-active GLOBAL calm, back to Kaya with the numbers.
- §7.2 items stay as decided elsewhere: living-glass default = subtle
  (Kaya may still overrule to off, delegation carve-out 2); shadow-token
  family carried with Kaya's nod.
- Change mechanism §8 active: amendments land here (DECISIONS) first,
  then in the spec — never the reverse.

Status: **RATIFIED** (Kaya, explicit, this entry logged with his
per-change approval).
