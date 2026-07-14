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

- Local `design/cockpit-v5 @ aa6cfbb`. **NOT pushed, NOT merged, NOT benched.**
  Nothing touched real hardware. The branch is Kaya's to review.
- **origin/main @ `a7dca3f` = THE TRUNK** (unchanged).
- **Night briefing (open this first):**
  https://claude.ai/code/artifact/8dfa85d2-692f-4603-b69f-4087d31b9d9f
  (copy in `artifacts_claude/nachtschicht_20260714/`)

## ▶ RUN THIS FIRST (Kaya's ask: "grob die full qml migration mit glass shell sehen")

```
cd TCT_app
.venv/Scripts/python.exe scripts/glass_shell_preview.py --dark
```
A REAL translucent QQuickWindow, real DWM acrylic (measured: gutter [84,84,84]
on vs [36,34,41] off, delta 140.3), a REAL BiasPanel island on a simulated
supply, real detach, leakage+compliance restored. Everything unwired wears a
visible STUB badge. `--probe` prints the measurement and exits.
**And in the real app: Theme editor → Material → Acrylic.** His persisted
`theme/window_backdrop` is `none`, and until `636ce78` turning it on did
nothing — that is very likely the whole story of "I never see glass".

## 🔑 THE DECISION WAITING FOR HIM

**Does SCENE earn its keep?** The spike proved in-scene MultiEffect works (60 fps,
0 crashes / 80 launches) — and Loki then asked what there is in THIS app that it
is architecturally permitted to blur. Answer: **nothing.** The workspace is a
QWidget tree; the chrome is a non-interop QQuickWidget island (different scene
graph). The 9 pyqtgraph/GL islands **never migrate** (ratified) and paint OVER the
QML scene via airspace, not under it. What a legal pane could still frost —
`canvas`/`card`/`well` — are flat colour fields, whose blur is themselves.
⇒ **The free DWM window material is the entire realized return of the glass
programme.** AMBIENT (0 pp CPU) vs STRUCTURAL (+13 pp/pane, needs THREE ratified
reversals and a rewrite of the 9 plots on a scene-graph API our own spike saw
segfault in ~50% of Python runs). Loki: ≥10× beats, unbounded risk, in exchange
for blurred card borders.

## ✅ THE NIGHT — 15 commits

`58df585` Odin crew ported (Brokkr/Loki/Baldr, adapted; Nordlys landmine
defused; path-D doc drift killed) · `801f2ab` **the glass contract**
(FLAT<TOKEN<WINDOW<SCENE<COMPOSED, pure decide_tier, 6912-env matrix) ·
`b702a85` round 01 · `636ce78` **G-B1b — why Kaya never saw glass** (the QSS was
never rebuilt on a live backdrop change; windows born without an alpha surface) ·
`beddc37` round-01 verdict + 2 ratifications + 6 live defects · `8299381` **the
alarm with no home** · `bbe3b10` **the shader ban is unearned — but Qt cannot
blur behind a window at all** · `c071f28` QML live-preview (first consumer of the
contract) · `f9a73bc` round 02 · `c37cac8` **the elevation ladder does not
exist** (dark canvas→panel ΔL* 1.46; light is inverted — verified by Adam) ·
`1d9eee1` **the GlassShell skeleton runs and measures its own glass** ·
`4ca8331` **71 WCAG failures, and the cause was not the colours** (19 QSS blocks
painted ink on an rgba wash of itself) · `82ddd2f` **the minimize blocker does
not exist** ([84,84,84] is DWM's inactive-window fallback) · `aa6cfbb` briefing.

## 🔥 IN FLIGHT

| Beat | Agent | Locks |
|---|---|---|
| **Mary — review of `4ca8331`** (safety-class: hazard tokens, the abort-button label, the motion command class). Her hardest question: after decoupling ink from fill, does EVERY chip still carry state in a non-colour channel? | Mary (Opus) | read-only |
| **The default shell paints over its own glass** — `TCT_QML_SHELL=1` shows 0.05% backdrop-tracking pixels vs 9.9% classic, with a HEALTHY window (alpha 8, material attached, attr38=3). The glass is not lost, it is painted over. | Noah (Opus) | `gui/qml_shell.py`, `gui/qml/*.qml`, tests |

## NEXT (queue)

1. **Wire the five glass_env probes** (`glass_env.py:972-991` are all
   `return None  # TODO(G-B2b wiring)`). Until then the RDP ceiling, the
   high-contrast → FLAT mandate and the battery rule are **inert**, and every
   "it degrades safely on RDP" claim is about unwritten code. Loki: worth more
   than either round-02 candidate.
2. **The inactive-window cosmetic fix** — extend the underlay law to ACTIVATION
   (an inactive window's material is not there; the canvas must fall back to the
   opaque pre-blend). Exact patch is in `82ddd2f`'s report. `gui/backdrop.py`.
3. **A ΔL\* surface-separation test** — nothing asserts a card is visible against
   its canvas. That is how a 1.03:1 dark ladder shipped. Land it regardless of
   who wins the round.
4. **`panel_kit.registered_glass_panes()` hands out DEAD C++ objects** after a
   window teardown (the pane registry never prunes) — found by the preview beat,
   reproduced without it.
5. Round 03 / the kit → then ONE pilot panel (Bias) → then the wave. **The kit
   BEFORE the panels**, or 13 panels become 13 dialects.
6. Bench: full suite at the wave boundary (sophonone verified UP).

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
