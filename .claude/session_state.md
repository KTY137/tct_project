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

- Local `design/cockpit-v5 @ 081da40` (G-B1 event spine).
- The night's landed chain (all on design/cockpit-v5):
  `76c2370` QML shell = default · `2525285` GLASS SYNTHESIS + 11-doc council
  · `7df2537` panel glass rollout · `b7f88a3` 3D GL stage view dropped
  (RTT-free classic) · `586bf41` doc-drift sweep · `11a93f7` Linux
  compositor research · `353072f` GL-island spike (MEASURED) · `081da40`
  G-B1 event spine.
- **origin/main @ `a7dca3f` = THE TRUNK** (unchanged tonight).
- Nothing pushed tonight yet. Not yet re-benched (see gates below).

## 🚨 KAYA'S NEW ORDER (2026-07-14, ~01:00) — THE PIVOT

> "our goal was to migrate fully to QML with GlassShell utilizing the Odin
> Crew from Projekt NorthStar, they have a smith dedicated for iterative
> design, he should iterate our design, our panel layout, everything to
> better user accessibility and match the design_assets like VisionOS more."

Consequences, decided by Adam:
- **Target = full QML migration to the GlassShell** (a real translucent
  `QQuickWindow` top-level), not just the trunk-hardening beats. The
  U-track and Track G merge into one program.
- **Three Odin seats ported (COPIED, adapted — NorthStar untouched, its
  tree verified clean at `4f132c3`):** `.claude/agents/brokkr.md` (Design
  Forge, Opus), `loki.md` (design adversary on paper — NOT a Mary
  duplicate; Mary attacks code), `baldr.md` (IA + accessibility).
  The other 15 were deliberately NOT ported: Huginn/Muninn/Nótt/Vörðr are
  our Shiori/Kiroku/Mamoru, and Thor/Ymir/Heimdall are NorthStar-kernel
  seats with no mandate here. (2026-07-08 all-hands: no new seats — three
  with a real mandate is in that spirit; eighteen would not be.)
- **LANDMINE DEFUSED:** NorthStar's Brokkr is instructed to build against
  the **Nordlys** design system. Nordlys must NEVER be a TCT reference
  (standing rule). The ported Brokkr/Baldr are pinned to TCT tokens
  (`gui/style.py` → `gui/qml_theme.py`) + `design_assets/` (visionOS) instead.
- **Agent registry DOES hot-load** (verified 2026-07-14): `brokkr`, `loki`,
  `baldr` became dispatchable agent types a few minutes after the files were
  written — no session restart needed. (An earlier note here claimed the
  opposite; it was wrong. Brokkr's round-01 run was launched via
  `general-purpose` with the persona inlined before the registry caught up —
  same laws, same file, no re-run needed.)

## ⚡ MEASURED CORRECTIONS — the plan was wrong twice (booked, 2026-07-14)

The GL-island spike (`353072f`) overturned two things four sources agreed on.
Both are now booked into `SYNTHESIS.md` (correction banner + 8 inline
supersede markers, Kiroku) and into `TECH_DEBT.md`:

1. **PATH-D IS REFUTED.** A live `QOpenGLWidget` child does NOT kill the
   window's DWM material on Qt 6.11.1 (acrylic 84/84/84, mica 32/32/32,
   identical to the GL-free control). The real killer was **attribute
   order**: `WA_TranslucentBackground` set after the HWND exists ⇒ no alpha
   surface, forever ⇒ DWM returns S_OK and nothing composites. Fixed and
   pinned headlessly by G-B1. **The main window CAN frost.**
2. **THE RHI VERDICT IS INVERTED.** A QQuickWindow-root shell shows real
   glass on the **OpenGL** RHI and **flat white on D3D11**. `main.py`'s
   OpenGL pin is LOAD-BEARING. → **This is the green light for GlassShell**,
   and it means SYNTHESIS §7.3's G0 criterion P1 (which names D3D) tests the
   configuration known to FAIL. **Adam must rewrite P1 before G0 runs.**
3. Spike ran on ONE host (Intel UHD iGPU). Booked as a bench item: re-run on
   a second GPU before treating the path-D refutation as universal.

## 🔥 IN FLIGHT (2026-07-14 ~01:00)

| Beat | Agent | Locks / notes |
|---|---|---|
| Mary review of G-B1 (`081da40`) — concurrency/lifecycle class, immediate per ratified cadence | Mary (Opus) | read-only; reviewing `gui/backdrop.py`, `gui/style.py`, the event spine, deferred-theme-reassert lifetime, underlay-law loss paths |
| **G-B2a — the glass contract** (`GlassTier`, `GlassEnvironment`, pure `decide_tier`, transition policy, `material_contract` marker, ~2000-case matrix test) | Noah (**Opus — Fable quota exhausted**) | `gui/glass_env.py` (NEW), `tests/test_glass_env.py` (NEW), `pytest.ini` (marker only). Deliberately does NOT touch style.py/backdrop.py — Mary holds them |
| **Brokkr round 01 — GlassShell cockpit** (2–3 materially different candidates, openable HTML, FLAT-first, WCAG AA, visionOS language) | Brokkr (Opus, via general-purpose) | `docs/design/iterations/glasshell-cockpit/round-01/` (NEW dir) |

## NEXT (Adam's queue)

1. Mary's G-B1 verdict → fix riders if any.
2. G-B2a lands → **G-B2b wiring beat** (style.py/backdrop.py consume
   `decide_tier`) once Mary releases those files.
3. **Loki attack pass** on Brokkr's round-01 candidates + **Baldr** a11y
   audit (contrast numbers at every tier) → Adam's verdict → round 02.
4. Rewrite SYNTHESIS §7.3 **G0 P1 around the OpenGL RHI** (it currently
   names D3D = the known-failing config), then G0 spike.
5. G-B3 harness upgrade (`scripts/capture_onscreen.py`: the spike found a
   REAL BUG — the probe grabs a hard-coded (60,1000) rect, off-screen on
   Kaya's 1536×864-DIP desktop, which is why it reported "INCONCLUSIVE";
   needs a 1px move-nudge + warm-up grab or the same command yields
   different pixels run to run). Plus verdict.json + lifecycle frames.
6. Full suite on the bench (sophonone is UP, verified) at the wave
   boundary — NOT per-beat (test economy).

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
