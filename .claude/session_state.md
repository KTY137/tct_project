# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit; stage explicit paths; never `-am`.

**Updated: 2026-07-13 late evening — MASTER PLAN EXECUTING (Kaya away
~1 h: "push und mach weiter mit dem plan"). Plan =
`docs/ROADMAP_MASTERPLAN.md` (Kaya-approved, 6-bounce-hardened, Codex
R1+R2 done).**

## HEAD / TRUTH

- `design/cockpit-v5 @ 7272233` local; **origin @ `031bc53` — PUSHED
  2026-07-13 evening after the SERIAL bench gate went green: 1870
  passed, 2 skipped, 1 xfailed in 24:31, exit 0, NO QThread-destroyed
  line (Phase-0b reaper verified against the at-exit crash class).**
  Origin = verified set; the two commits on top ride the NEXT gate.
- Unpushed on top of origin:
  - `5c75696` **P0' wavegen-apply** (per-point `_apply_wavegen_settings`
    before `_acquire_core`; `/run_info` attr `wavegen_command_trace`
    commanded-only; validator `_KNOWN_WAVEGEN_KEYS` unknown-key=ERROR;
    `HDF5Writer.set_run_metadata`; EMITTING byte-identical, setter
    errors → fail-safe with test; 73+72 targeted green).
  - `7272233` **gate-enforcement pre-D1** (docs/test_bucket_map.md
    A=47/B=18/C=39/D=5; .claude/check_bucket_a.ps1 self-tested incl.
    true-positive vs HEAD~1; R1–R6 routines + frozen
    tests/fixtures/routine_corpus/, all 0 ERR/0 WARN, sha256-identical).
- Phase-0/0b history: `26538a4` identical-QSS skip (Mary APPROVE,
  timeout 240→90 ratified) · `031bc53` conftest sessionfinish reaper +
  permanent leak guard (Mary RISK-NOTES mergeable; xdist masks the
  class — serial gate is the honest one).

## 🔥 IN FLIGHT

| Beat | Agent | Locks / notes |
|---|---|---|
| P0' Mary-riders: ACQUIRE_WAVEFORM outer-key typo → action-scoped ERROR (+corpus 0/0 regression proof) · fail-safe test tightened (output_off count after on_error, bias-untouched assert) · docstring contracts (point_index attempt-semantics, no-settle-today) | Abel (acquisition-dev) | `controller/scan_plan_validator.py`, `controller/scan_controller.py`, `tests/test_scan_plan_validator.py`, `tests/test_plan_executor.py` |
| CAPABILITY_MODEL.md v0.1-draft (D1 entry artifact, beat 5 of Part VI) | Paul (hardware-dev, Fable) | `docs/CAPABILITY_MODEL.md` (new) |
| Kiroku booking batch (post-push) | kiroku | `docs/ARCHITECTURE.md` changelog, `docs/TECH_DEBT.md` |

**Durable evidence line — [Mary] P0': gate=P0'-immediate-review,
sha=5c75696, verdict=RISK-NOTES (emission-safe proven: setters
setter-only vs _WFG_CMDS incl. sim parity; exception path fires with
output OFF; finally cannot strand ON; bracket byte-identical; trace
honest incl. partial-on-abort; validator sound, duty-0/100 reject
defensible, amplitude-0 allowed), date=2026-07-13.** Residual: settle
gap = P1 rider (apply→wait_settled→acquire); real-DG4000 settle timing
= bench question; retained-ON first-point edge = pre-existing,
documented. Mary items 2-4 → Abel rider beat above; settle-gap +
trace-semantics rows → next Kiroku batch (TECH_DEBT.md locked now).

## NEXT (post-push chain, in order)

1. Mary P0' verdict → fixes if needed (P0' rides the NEXT bench gate
   with the gates commit).
2. CAPABILITY_MODEL.md + SAFETY_NORMATIVE_TESTS.md drafts → [Mary] →
   ⚑[Kaya]; then D1 slice: `capabilities/model.py` + adapters
   (additive, [A-green] via check_bucket_a.ps1 from a stage-base ref
   taken AFTER P0'/P1 land).
3. venv migration (`agent_env\tools\recreate_tct_venv.ps1`, CPython
   3.10.11 installed) — ONLY when no agent is running local pytest
   (Mary first). Then stale-worktree cleanup
   (`agent-aa19d2caf98c928dd`, `slice1-ui`).
4. Phase 0.5 prep (needs Kaya): design/cockpit-v5 → main merge with
   bench-green evidence; polish-freeze tag machinery.
5. Follow-ups booked: P2-entry corpus-replay pytest (size≥5 guard +
   byte-diff); xdist honesty follow-up (workeroutput/testnodedown);
   per-test shutdown hygiene TECH_DEBT; trunk note in test_bucket_map
   at Phase 0.5.

**Part-VI parity check CLOSED (2026-07-13 evening):** experimental
branch's test_state_fuzz variant contains NOTHING extra — its only
unique content was the historical xfail probe for start-while-PAUSED;
HEAD has the bug FIXED (5730644 fail-closed guard, all 4 entry points)
and covers it with three real tests (test_state_fuzz.py:
start_while_paused / start_z_focus_while_paused /
start_voltage_while_paused). Worktree removal (agent-aa19d2caf98c928dd,
slice1-ui) was DENIED by the permission classifier — needs Kaya's
explicit go (branches keep all commits regardless). C10 second-opinion
review enqueued on Codex lane (watcher restarted, background).

## ✅ Standing verdicts (do not re-derive)

- HV gate CLOSED (`df10f8e`+`0f1c012`, Mary APPROVE, bench green).
- Sequencer safety-signed: Mary CLOSED (A5.1 surgical locks, A5.2a/b
  manual_pause can never enter a queue).
- Teardown-race fix `41a8ab2` Mary APPROVE.
- E3 calibrate_affine Mary APPROVE (riders before GUI wiring).
- Master plan: 6 bounce rounds integrated (Prometheus, Mary, Loki,
  Völundr, Codex R1/R2); honest ledger in ROADMAP_MASTERPLAN.md.
- Test economy binding (CLAUDE.md): agent output tail = verification;
  bench gates only; serial bench = honest gate for at-exit class.
- Day shift (see git log 2026-07-13): E-track E1–E7 complete, v6 glass
  landed + ratified, motion kit, WorkerThread batch 1, 9 presets,
  Echtglas chain (opacity pin), lane hardening (agent_env).

## 🧑‍🔬 NEEDS KAYA (personal gates, from the roadmap)

- ⚑ per-operation safety-routing SHAPE · ⚑ e4control seed choice
  (upstream MIT ask vs written-permission note) · Trusted-operator
  contradiction ruling (PLATFORM_SEED §6) · C1 top-3 routine selection ·
  reticle tier ($17/$276/$630) · tolerance_um working value ·
  GS-upgrade timing · S0/S2 ratifications · design-freeze declaration
  (opens U-track) · blur eyeball + alpha tuning (0.82/0.55/blue bias) ·
  U1.5 Design Council later · Phase 0.5 merge go.

## Rules pointers (already binding, in CLAUDE.md)

Test economy · test-lane policy (bench full suites; targeted local) ·
session hygiene 1–4 · free lanes never idle · Codex = queue-file only ·
ONE here-string commit per shell call, verify `git log --stat`.
