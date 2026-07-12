# Council v5 — Abel's seat: run-control grammar

Date: 2026-07-12. Scope: the run-control *language* across Scan Planner, Scan
Viewer, and the shell run strip. Inside the 8 laws (`cockpit_design_system.md`)
and the RATIFIED envelope/latch (§11): HV approved **once** per run via one
two-step arm latch, executor re-validates against the armed envelope, no
per-step modals. Grounded in `gui/qml/ScanStatusStrip.qml`,
`gui/run_state_viewmodel.py`, `AppState`, `planner_panel`/`scan_viewer_panel`.

## 1. Planner — recipe-row grammar

Keep the half-built 3-column Mac shape (palette 200 / recipe tree / aside 340).
The aside owns the ladder (Points/Runtime/Data/Travel/HV-range + Validate →
Dry-Run → arm latch). **Latch flow untouched:** Dry-Run unlocks arming; Arm is
the two-step hold over the FULL envelope text; armed ~10 s; Execute. Envelope
approved once — recipe rows NEVER carry their own arm/confirm.

**One accent per row, keyed to command class (law 2):**
- Nominal rows (loop, in-plan move, settle, acquire): grey hairline spine, no
  saturated color (law 1).
- Motion rows (MOVE STAGE): **amber** spine — fixes Adam's live law-2 violation
  (row + CONFIRM pill are RED today; motion is amber, red is HV only).
- HV rows (RAMP HV): red spine (correct today, keep).

Per-row pills, de-zoo'd (kills 7 STEPS / 21 PTS / A CONFIRM / SNAKE noise):
- Quantities (steps, points) are numbers → right-aligned quiet **mono chips**,
  never colored (law 3) — engraving, not status.
- Behaviors (snake, settle) → tiny mono eyebrow in the row caption, not pills.
- **The CONFIRM pill is killed** by the envelope model (a per-row confirm
  contradicts "no per-step modals"). It becomes a read-only **hazard glyph on
  the spine** (amber / red on HV) meaning *"enumerated in the armed envelope"* —
  an indicator, never a button. Hazard rows = colored spine + glyph; nominal
  rows disappear into quiet-nominal; all affordances live in the aside.

## 2. Viewer — the run-HUD single-source ruling

The strip already owns State / HV·measured / Progress·ETA / Position. Codex
move #6 ("overlay progress, ETA, point, elapsed on the map") **double-reports
all four.** Ruling — one source per quantity:

| Quantity | Single source | Why |
|---|---|---|
| AppState (RUNNING/PAUSED/…) | **Strip** State tile | global always-on chrome |
| HV·measured | **Strip** HV tile | global safety readout |
| Progress · ETA · elapsed | **Strip** Progress tile (elapsed = caption) | strip merges these |
| Position (x/y/z numeric) | **Strip** Position tile | the coordinates |
| *Where* on the grid | **Map** spatial cursor | a picture, not a number |

So the map overlay is **spatial only**: live acquisition cursor on the cell
being taken, snake path trail, designed empty/stale canvas — plus the one text
element the strip does NOT own: the derived **sub-phase eyebrow** (arming /
moving / settling / acquiring / saving — presentation only, §5, finer than the
AppState). No numeric progress/ETA/point/elapsed floats on the map. This also
dissolves Adam's "PAUSE/ABORT bottom row fights the HUD" gap: no numeric HUD
frees the map corner for a glass Pause/Abort (§3). The strip travels with a
detached Viewer (§8), so it is always co-present as the number source.

## 3. Run-lifecycle visibility — quiet until it isn't

Nominal RUNNING = quiet: State tile on the single blue accent, viridis map, zero
red/amber. Color enters only on a hold or a fault.

- **PAUSED (manual OR ratified WARN-hold):** State tile → "PAUSED", accent
  **amber** (attention, not danger). HV tile keeps the *held* measured voltage,
  caption "held", NOT stale. Progress freezes but ETA reads "paused", never a
  frozen number pretending to count (law 4). Map: cursor stops, quiet amber
  "Paused" glass caption; WARN-hold adds the excursion reason (temp/humidity/
  leakage) + amber WARN chip, manual pause shows none. Planner aside: armed
  envelope still shown active, latch stays consumed (no silent re-arm).
- **ALARM → abort (fail-safe):** State tile → "ABORTED" rendered **neutral-crit,
  not red** (§5 — red is the abort *action*, not the resting result). HV → OFF,
  caption "fail-safe". Map retained + stale-dimmed with a neutral banner
  "Aborted — N/M points saved · file flushed" (honors data-preserved). Only a
  genuine trip/fault is `AppState.ERROR` with red errorText surfaced — distinct
  from ABORTED.

**Abort affordance:** global ABORT / ALL-HV-OFF is an instant tap (law 5, no
latch) in the shell run strip — **outline-red while idle/nominal** (reachable,
quiet), **filled-red only while a run is live/armed** (bias-kill discipline).
The Viewer repeats Pause + Abort as a **glass corner** on the map (space freed
in §2), same outline→filled rule, routing through `ScanCoordinator` to the
identical abort path. The Planner owns Arm/Start, not a standing abort; its
Abort mirrors the same coordinator call, enabled only while its armed run lives.

## 4. Command palette (Codex idea) — verdict: KEEP, class-filtered, D6

Must NEVER bypass the arm latch (safety rule 2). Filter by command class **at
the registry source** — danger commands structurally *absent*, not disabled:
- **Allowed:** panel switch, "open last run in Analysis", "export plot/CSV"
  (read/nav); **Dry-Run** (touches no hardware — it *unlocks* arming); and
  fail-safe stops Pause / Abort / All-HV-off (law 5 makes these one-tap, no
  latch — can only make things safer).
- **Forbidden:** Start / Arm / Execute / Ramp HV / Enable HV / Home / Move —
  every DangerAction. A palette "Start" bypasses the two-step latch. A shortcut
  may only *navigate* to the armed control (open Planner on the latch), never
  execute.

Verdict: **keep**, safe subset only, built in D6 — not before the latch and
DangerGate seams are locked.

## Conflicts spotted in Codex's proposals

1. Move #6's numeric run-HUD double-reports the strip's State/HV/Progress/
   Position — resolved by the spatial-only map ruling (§2). UX, not safety.
2. Idea #2's "safe hardware actions only" is too loose — must be pinned to
   fail-safe stops + Dry-Run ONLY; any Start/Arm/Ramp/Home/Move would bypass
   the latch (rule 2 + law 5). Forbidden in §4.
3. Planner move #7 matches the ratified latch — no conflict; the CONFIRM-pill
   kill (§1) aligns the recipe rows to the once-per-run envelope.
