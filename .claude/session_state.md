# Session state — Adam's externalized working memory

**Purpose:** the state that would otherwise live ONLY in the orchestrator's
context. A fresh session reads this file and is as informed as the old one.
Updated on every dispatch and every landing. Run `.claude/beat_status.ps1`
before every commit; stage explicit paths; never `-am`.

**Updated: 2026-07-14 early morning — NIGHT SHIFT under Kaya's new order.
He is asleep until ~10:00 and expects cooked work. The previous session
updated this file at 00:24 and then landed G-B1 at 00:54 without
refreshing it — HEAD was stale by 7 commits. Reconstructed from `git log`
+ SYNTHESIS.md, not from memory.**

## HEAD / TRUTH

- Local `design/cockpit-v5 @ 8299381`. NOT pushed, NOT benched yet.
- **The night's chain (2026-07-14):** `58df585` Odin crew ported (Brokkr/Loki/
  Baldr, adapted; Nordlys landmine defused) + path-D doc drift killed ·
  `b702a85` Brokkr round-01 (3 candidates, openable HTML) · `801f2ab` **G-B2a
  the glass contract** (GlassTier FLAT<TOKEN<WINDOW<SCENE<COMPOSED, pure
  decide_tier, 6912-env matrix, 149 tests) · `636ce78` **G-B1b — the reason
  Kaya never saw glass** (the QSS was never rebuilt on a live backdrop change;
  windows were born without an alpha surface) · `beddc37` round-01 verdict +
  2 ratifications + 6 live defects · `8299381` **the alarm with no home**
  (slow-control ALARM was invisible outside the Monitor tab).
- **origin/main @ `a7dca3f` = THE TRUNK** (unchanged).

## 🚨 KAYA'S ORDERS (2026-07-14, all NEW tonight)

1. **Full QML migration to the GlassShell.** GlassOS is the TARGET, not a
   garnish. FLAT is the fallback for machines that cannot do glass.
2. **The ShaderEffect/MultiEffect ban is LIFTED as policy** ("ja heb das verbot
   auf"). Adam holds ONE gate until the spike reports: the crash rate. A
   segfaulting effect kills a run, and that is data loss, not taste.
   `scripts/spikes/qml_multieffect_glass_spike.py` is measuring it now.
3. **RATIFIED — danger topology:** a dangerous action belongs to the PANEL that
   owns the hardware, NEVER to the shell. The shell may DISPLAY hazard state; it
   may never TRIGGER it. No presentation-layer mediator will be built.
4. **RATIFIED — detachable panels are permanent.** `detachable_tabs.py` stays
   the ENGINE; QML is a VIEW over it. Every detached panel is its own top-level
   ⇒ its own DWM material and its own tier.
5. **Every panel gets redesigned individually**, plus a **cross-panel META
   REVIEW at every wave boundary** (his ask: "ob die panels auch miteinander
   harmonieren"). Mechanism: the kit makes drift structurally impossible
   (token-parity + object-tree-walk gates); the CONTACT SHEET (all panels, both
   themes, every tier) makes the residue visible. Not a meeting — a picture.

## 🔥 IN FLIGHT

| Beat | Agent | Locks |
|---|---|---|
| **A11Y palette fix** — light mode fails AA systemically (sim/warn/crit/faint/good); white-on-crit fails in DARK too; `faint` on glass = 2.0:1; the laser SAFETY BANNER = 3.0:1; ribbon clips MOTION; jog icons bypass the token system | Noah (Opus) | `gui/style.py`, `gui/motor_panel.py`, `gui/laser_panel.py`, `tct_gui.py`, tests |
| **MultiEffect spike** — is the shader ban earned? Can we blur BEHIND the window? Crash rate over N≥20 | Noah (Opus) | `scripts/spikes/qml_multieffect_glass_spike.py` (NEW) |

## ⚠️ VERIFIED DEFECT — the elevation ladder does not exist (2026-07-14, Adam recomputed)

Brokkr claimed it by hand (no execution tool); Adam verified computationally
against the real `gui.style.palette()`. **Confirmed to the second decimal**, and
the recomputation found MORE than he claimed — the two themes have **INVERTED
ladders**:

| | canvas → panel | panel → raised |
|---|---|---|
| **dark** | ΔL* **1.46** (invisible, 1.03:1) | ΔL* 9.68 |
| **light** | ΔL* 7.11 | ΔL* **1.80** (invisible) |

**Neither theme has a continuous three-tone ladder.** Each has exactly ONE
visible step, and it is the OTHER one. So candidate C's "salvaged three-tone
FLAT ladder" — the thing round 01 declared the best in the round — **does not
exist in the code**. We would have built both round-02 candidates on it and
wondered why the result looked flat.
Brokkr's proposed fix (derived, not chosen): `card = _blend(raised, panel, 0.60)`
→ `#151D2D` in dark (ΔL* 7.16, a match to light's 7.11), `= panel` in light.
**Needs Kaya's nod: it partially reverses the v6 "cards recede toward the canvas"
pass, ratified two days ago.**
BLOCKED: `gui/style.py` is held by the a11y palette beat. Land after it.

## NEXT (Adam's queue)

1. **3 lines at the composition root** for the sticky alarm chip
   (`STATUS.alarm` is emitted but unrendered — the exact lines are in the
   alarm beat's report). BLOCKED until the palette beat releases `tct_gui.py`.
2. **Mary re-review** of G-B1b (she asked for it: the QSS rebuild + the fan-out
   now routing through `reassert_window_backdrop` — check for a double-pin or an
   `apply_theme` re-entrancy path) and of the alarm beat's asymmetric hold.
3. **The glass_env WIRING beat** — the contract has ZERO consumers today.
   `GlassEnvironment.high_contrast` / `.remote_session` are populated by NOTHING
   outside the tests, so every "it degrades safely on RDP" claim currently rests
   on a detector that does not exist. Handoff is written in `801f2ab`.
4. **Round 02** (Brokkr): revised A = spine + phase rail + vitals strip (display
   only, NO armed rail), inheriting C's three-tone FLAT ladder. MANDATE: raise
   the glass alphas to the repo's own 0.50 floor — A's `.42`/`.06` put muted
   text at **1.04:1** at worst case, i.e. the across-the-room readout that IS
   candidate A washes out in exactly the environment its own switch was built to
   probe.
5. **The kit BEFORE the panel wave** (else 12 panels = 12 dialects), then ONE
   pilot panel with Kaya's eyes on it. Pilot candidate: **Bias** (hazard surface
   + detached + live readouts).
6. Bench: full suite at the wave boundary (sophonone is UP, verified).

## 📋 THE PANEL CENSUS (Shiori, 2026-07-14) — the wave's foundation

- **Programs wearing a panel costume** (own beat each): `planner` 2524 ·
  `analysis` 2203 · `scope` 1655 · `motor` 1212 · `camera` 958.
- **Simple compositions** (one wave): intensity 224 · device 348 · sequencer 456
  · calibration 578 · scan_map_view 615 · laser 703 · stage_view 255.
- **Hazard surfaces (opaque at EVERY tier, keep their own gate):** bias,
  multi_bias, motor, calibration, planner, sequencer.
- **Three panels own EXTRA top-level windows** ⇒ three more glass surfaces:
  `device_panel` IS a QMainWindow · `scope` has a floating `_TriggerDialog` ·
  `camera` has a modal `_ROIDialog`.
- `multi_bias` is tabbed per HV channel — you cannot see two channels at once.

## 🧑‍🔬 NEEDS KAYA (at 10:00)

- **Fable quota is exhausted.** The ratified rule sends judgment beats to
  Fable; they are falling back to Opus tonight. Needs his nod (or a
  top-up).
- **Round-01 design verdict**: which candidate (or merge) proceeds. The
  HTML candidates are built to be double-clicked.
- Blur eyeball + alpha tuning (0.82/0.55/blue bias) — needs his eyes.
- Trusted-operator contradiction ruling (PLATFORM_SEED §6 vs
  remote_control_plan §5.1.3) — still open.
- Bench items: 2nd-GPU spike re-run · PI #24 latency + MOV-after-stop ·
  relay magnification M · printed ArUco marker · GRBL 0x85-vs-$H.
- Delete `.venv_old` after running `.\run.ps1` once.
- C1 top-3 routine selection · reticle tier · tolerance_um · GS-upgrade timing.

## ✅ Standing verdicts (do not re-derive)

- **Glass case SOLVED** (attr-20 fix `2cf720b` + the order law + underlay law
  in G-B1). QtAds is UNUSED in production.
- HV authorization chain COMPLETE + Mary-APPROVED (envelope preview →
  fresh-at-arm derivation, 180 s arm→start bound → set-membership run-time
  law → three distinguishable deny messages).
- Transport serialisation: PI serialised, disconnect-stops-first, PI stop
  lock-free (#24 manual-cited), DRS4 guarded, GRBL transport_lock declared.
- D1 capability spine COMPLETE (D1a `208207e` + D1b `b26144a` + validator
  `d7e4f63`). Mary's D1b riders still TO DO (twin fail-safe constants;
  cross-thread-release regression test; HV-abort-under-held-reservation).
- venv = real CPython 3.10.11. Sim bias multi-channel end-to-end.
- Test economy binding · bench full suites only at gates.

## Rules pointers (binding, in CLAUDE.md)

Test economy · bench full suites only · session hygiene 1–4 · free lanes
never idle · Codex = queue-file only · ONE here-string per shell call ·
verify `git log --stat` after multi-beat landings.
