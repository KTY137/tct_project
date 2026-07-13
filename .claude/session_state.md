# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit; stage explicit paths; never `-am`.

**Updated: 2026-07-13 night — MASTER PLAN EXECUTING. Kaya is ACTIVE in
session and issued 5 verbatim ratifications tonight (see DECISIONS.md).
Scope reminder from Kaya: this repo prepares TCT_app as the platform
BASE only — LabControl is NOT built here.**

## HEAD / TRUTH

- Local `design/cockpit-v5 @ b77d92c`+ (D1a `208207e`, G0 `b77d92c`;
  **gate #4 bench running at b77d92c**).
- origin/design-cockpit-v5 @ `54baf62` (gate #3 GREEN: **1995 passed,
  26:06, exit 0** — third green gate of the day after 1870@031bc53 and
  1885@98629c1).
- **origin/main @ `a7dca3f` = THE TRUNK** (Phase 0.5 executed as a
  theirs-tree merge — tree byte-identical to 54baf62, old pre-restructure
  history preserved via 2nd parent; evidence = gate #3's 1995 passed,
  cited in the merge message). `polish-freeze` tag pushed on it (U-track
  entry gate + seed baseline). design/cockpit-v5 retires after in-flight
  work lands.
- **Kaya's 5 ratifications (2026-07-13, verbatim quotes in
  DECISIONS.md):** (1) guarded-exchange staged adoption; (2) capability
  routing shape = option (c); (3) multi-channel HV naming per §14.2;
  (4) MIT license in the platform seed; (5) blanket GO on pending
  operational gates (S2 manifest, Phase-0.5 merge, worktree removal —
  all EXECUTED).
- CAPABILITY_MODEL.md = **v1.0-rc, D1 gate OPEN** (Mary RATIFY-READY,
  amendments applied 54baf62). Mary APPROVEs tonight: expiry-fix
  665319e, transport-locks 4a89647 (w/ risks, all closed), bias-channels
  a75dfba, D1a 208207e, G0 b77d92c.

## 🔥 IN FLIGHT

| Beat | Agent | Locks / notes |
|---|---|---|
| Gate #4: serial bench at b77d92c (D1a+G0+180s-bound+comment) | sophonone | push both branches on green |
| D1b: adapters + registry + transport_lock_for resolver + §7.2 build-time laws + §4 ratifying sentence | Paul (Fable) | `capabilities/adapters.py`+`registry.py` (new), `capabilities/__init__.py`, `controller/device_manager.py` (capability_registry() only), `tests/test_capability_registry.py` (new), `tests/test_layer_contracts.py` (wiring only), `docs/CAPABILITY_MODEL.md` (§4 sentence) |
| Validator charset for slow-control names (§11.4 item 4, mirrors capabilities.model.slow_control_capability_id) | Abel | `controller/config_validator.py`, `tests/test_config_validator.py` |

## NEXT

1. Gate #4 green → push design/cockpit-v5; D1b + validator land → Mary
   on D1b (build-time laws = safety surface) → gate #5 → push.
2. After D1: **P1** (wavegen re-hosted as capability pilot,
   equality-gated vs P0' behavior; bundle with **DA1** swept/ writer
   slice per roadmap F4) + **S1** taxonomy review.
3. Rider queue: `start_voltage_scan` fail-open (HIGH — controller
   boundary has NO arm/gate for the IV sweep; GUI-only confirm) ·
   sequence_coordinator on_deny hook (1 line) · WaitStep.reason display
   decision (planner tooltip + runtime status line) · iseg emergency-off
   TODO(manual) · pytest filterwarnings for GuardedExchangeWarning.
4. G-track: G1 motors (FIRST CONVERSION GATE: behavioral T2 pin — Mary)
   after D1b lands; G2 bias before D3.
5. U-track formally OPEN (polish-freeze exists) — starts after the
   D-wave per WIP limit. U0 = branch cut + RHI probe.

## ✅ Standing verdicts (do not re-derive)

- HV authorization chain COMPLETE + Mary-APPROVED: envelope preview →
  fresh-at-arm derivation (180 s arm→start bound, 4bb82d7) → set-
  membership-only run-time law (665319e) → three distinguishable deny
  messages. Kaya's silent-abort bug pinned by
  test_kaya_regression_aged_arm_still_finishes.
- Transport serialisation: PI serialised (4a89647), disconnect-stops-
  first (fbf94d8), PI stop lock-free #24 manual-cited (7a55d03), DRS4
  guarded (3930f58), GRBL transport_lock declared. All Mary-reviewed.
- venv migrated to real CPython 3.10.11 (PySpin parity restored, 128
  smoke green); Codex lane can run pytest again. Rollback `.venv_old`.
- Sim bias multi-channel reachable end-to-end: `sim_channel_count`
  config + validator + settings-GUI (to_dict silent-drop fixed).
- HV gate CLOSED (df10f8e+0f1c012) · Sequencer safety-signed ·
  Teardown-race 41a8ab2 · E3 calibrate_affine (riders before GUI
  wiring) · Master plan 6-bounce-hardened · Test economy binding ·
  Day shift: E-track complete, v6 glass ratified.
- Mary's forward-looking GATE REQUIREMENTS (booked in TECH_DEBT.md):
  G1 behavioral T2 pin · G4 registry de-dup/type-keying · is_alive
  busy-streak bound · output_off per-exchange-only · AST pin
  relative-imports (in-flight D1b) · §4 asymmetry sentence (in-flight).

## 🧑‍🔬 NEEDS KAYA (still genuinely open)

- Trusted-operator contradiction ruling (PLATFORM_SEED §6 vs
  remote_control_plan §5.1.3) — NOT covered by the blanket GO.
- C1 top-3 routine selection · reticle tier ($17/$276/$630) ·
  tolerance_um working value · GS-upgrade timing.
- Blur eyeball + alpha tuning (0.82/0.55/blue bias) — needs his eyes on
  the real display; token values can change post-freeze without
  reopening it.
- U1.5 Design Council round (his explicit ask, later).
- Bench items: PI #24 latency + MOV-after-stop (BENCH_CHECKLIST §13),
  relay magnification M, printed ArUco marker, GRBL 0x85-vs-$H.
- Delete `.venv_old` after running `.\run.ps1` once.

## Rules pointers (binding, in CLAUDE.md)

Test economy · bench full suites only · session hygiene 1–4 · free
lanes never idle · Codex = queue-file only · ONE here-string per shell
call (msgfiles preferred) · verify `git log --stat` after multi-beat
landings.
