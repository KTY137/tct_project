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
