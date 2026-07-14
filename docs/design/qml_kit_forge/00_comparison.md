# QML COMPONENT-KIT FORGE — the field, and where to attack it

| | |
|---|---|
| **Topic** | U1.5 deliverable: the QML component-kit spec (panel_kit analogue) — PAPER ONLY |
| **Round** | 01 (lean, per Kaya 2026-07-15: kit spec only; no full glass/SCENE round, no shell redesign, no code) |
| **Candidates** | [`candidate_twin.md`](candidate_twin.md) · [`candidate_lantern.md`](candidate_lantern.md) · [`candidate_ledger.md`](candidate_ledger.md) |
| **Forged by** | Brokkr, 2026-07-15 |

---

## 1. The axis the candidates genuinely differ on

**Where does design authority live?**

| | TWIN | LANTERN | LEDGER |
|---|---|---|---|
| **Authority** | the shipped QWidget kit + round-03 contract — QML is a second *renderer* | the scene/material — one `Surface` primitive, frost + edges + springs, components are content | a machine-readable `(role, state) → paint/motion` table — components are projections |
| **What "correct" means** | pixel-comparable to the classic shell at TOKEN | matches the `design_assets/` plates; material laws hold geometrically | every cell resolves, every cell audited by enumeration |
| **Blur posture** | **zero blur, committed** (edges are the meal) | **baked frost, central** — one blur pass on the living ground, panes sample it | **data-gated** — blur is a table field, default 0, flip-on if a spike lands |
| **Motion identity** | eases only, one duration (200 ms) | springs on interactive geometry; motion = material response | declared edges in a motion table; springs allowed as named curves |
| **Living glass status** | leaf feature under the AmbientGround contract; default **off** | layer 0 and the frost source — the organizing principle; default **subtle** | a table row calmed by the same precedence pipeline as every component; default **subtle** |
| **Classic-shell relationship during U1–U6** | parity — one look, two engines | deliberate divergence (ratified: classic = fallback, not design target) | parity of *semantics*, divergence of paint allowed per table |
| **Verification style** | golden-pixel gate (TOKEN tier) | geometric/material law assertions (dead zones, band-per-frame) | exhaustive cell enumeration + LOCKED safety rows |
| **Chief sacrifice** | the migration shows nothing new — "why QML?" unanswered visually | stands on the unspiked frost bake; two looks in one app for months | indirection + schema creep risk; a style compiler for one app |

These cannot be merged by a stylesheet change: Twin forbids what Lantern is made of (blur,
springs, divergence), and Ledger relocates the thing both others treat as code (state
styling) into data. A merge is a *decision* (e.g. "Ledger's table + Lantern's material
vocabulary + Twin's Theme-gap audit"), not a diff.

## 2. What is shared (deliberately identical in all three — the constitution showing through)

- Zero capability loss vs `gui/panel_kit.py`; the never-migrates list untouched
  (QtDangerGate, 9 islands, camera QLabel, STOP/ALL-OFF/Abort, ArmLatch).
- Hazard surfaces opaque at every tier, five redundant channels, gate stays in the panel.
- Hole-and-frame coexistence with islands and safety QWidgets; emergency shortcuts owned by
  the top-level QWidget path; no app-wide `Shortcut` in kit code; z-order/key-injection
  merge gates (Codex BLOCKER-2).
- Tokens only via the `Theme` singleton; the **Theme exposure gap audit** (Twin §5 — 
  danger_fill/on_danger/on_armed, chip, edge/edge_shade, pressed/disabled_bg, radiusXl/
  Shelf, font/weight roles, glass alphas, motionEnabled) is prerequisite homework for ALL
  three candidates.
- Living glass honors: off/subtle/full + speed persisted, reduced-motion override, auto-calm
  on RUNNING via `run_state_facade` only, **band law per frame** (ΔL* 4.0 / summed tint
  α ≤ 0.07 at every pixel of every frame), no semantic tint, FLAT = nothing / TOKEN =
  static wash / SCENE = animated. All three amend kit.md §1.2's "never animates during a
  run" to "auto-calms to static during a run" (Kaya's 2026-07-14 directive is newer).
- State never by colour or blur alone; focus ring mandatory on every interactive component;
  hit targets ≥36 px (44 px motion/danger); no backdrop-blur-behind-the-window anywhere
  (physically impossible in Qt — none of the three specs it).

## 3. Attack surface — where Loki and Baldr should hit hardest

**Loki (cost/mechanics/kill-the-premise):**
1. **Lantern's frost bake** — the single most load-bearing unbuilt mechanism in the field.
   Demand the spike protocol *now*: N sampling panes + one pyqtgraph island at 30 Hz on the
   bench iGPU; if it fails, Lantern collapses into Twin-with-springs — say so before U2, not
   after.
2. **Twin's golden-pixel gate** — QML distance-field text vs QPainter text will not match.
   Force Twin to state the ΔE tolerance and what the gate still proves at that tolerance.
   If the honest answer is "layout, not pixels", the candidate's one law is weaker than
   advertised.
3. **Ledger's schema benders** — walk in with the jog-pad crosshair, the planner drag-ghost,
   and the scope trigger marker and make the table either grow or cheat. Also price the
   resolver machinery honestly against "per-component kit + walker test, no table".
4. **All three:** the two-shell window cost. Twin pays it in pixel tests, Lantern in double
   design truth, Ledger in resolver infrastructure. Which one is actually cheapest across
   U2–U6, in beats?
5. **Frost re-bake Hz (Lantern §7)** during *idle monitoring* — live plots run outside
   scans; the auto-calm gate does not cover them. Is 6–12 Hz re-bake + 30 Hz pyqtgraph
   acceptable on the iGPU, measured?

**Baldr (accessibility/legibility/distraction):**
1. **Living glass as a side channel** — a calm ground correlates with RUNNING. All three
   mitigate by ambiguity (calm also = off/reduced-motion) + "the chip is the indicator".
   Is that enough, or must the spec forbid *any* run-state coupling and gate the calm on
   something else (e.g. any-window-has-live-plot)?
2. **Motion safety of the flow itself** — vestibular triggers: verify the committed
   amplitude/period numbers (Lantern: ~8% viewport over 90 s) against WCAG 2.3.3 and
   reduced-motion expectations; check `full` × speed 2.0 worst case, not the default.
3. **Lantern's focus halo and hover-lift** — luminous accent near warn/crit chips at
   distance; shadow-step-on-hover as a state cue that dies at FLAT (the ring and border
   channels must carry it alone — measure the ring on every rung, both themes).
4. **Twin's stale/disabled treatments** — the shipped `MetricTile.qml` still carries a
   blanket `opacity: 0.6` stale dim *on top of* muted ink; Twin claims ink-based staleness —
   force the reconciliation and measure disabled ink on `disabled_bg`.
5. **Ledger's LOCKED coverage** — adjacent-row attack: add a plausible new `armed` variant
   row and show whether the pins catch it or the "table is safe" confidence is false.
6. **All three:** focus-ring contrast (≥3:1 non-text) over SCENE glass fills at worst legal
   ground — the ring sits on the *composited* surface, and nobody has measured a ring, only
   text inks.

**Mary (safety/concurrency, when it reaches her):**
- Run-state wiring path for auto-calm (facade VM only, no controller ref, teardown of the
  amplitude animation at shell close — the immortal-panel/leaked-animation lesson).
- QQuickWidget/engine teardown vs the kit singletons (`Theme` weak-registry pattern already
  exists; `KitStyle` must match it).
- Focus traversal across the QML↔QWidget boundary per migrated panel; danger-hole z-order.

## 4. Open questions for Kaya (the picks only he can make)

1. **Parity or divergence during the U-window?** Twin holds one look until U6; Lantern makes
   the QML shell visibly better *now* at the price of two looks in one app for months.
   Which discomfort does he want?
2. **Is edges-without-blur enough "glass feeling"?** Twin bets yes; his round-2 verdict
   ("verschluckt zu viel glass feeling") suggests no. A one-look A/B (static mock is
   sufficient) would settle it before the attack pass argues in the abstract.
3. **Living glass default:** off (Twin) or subtle (Lantern/Ledger)? And does auto-calm
   satisfy his intent, or did he want the glass alive *during* runs too (the Baldr gate says
   no — this is the one place his wish and the distraction gate can collide)?
4. **Shadow-ladder tokens** (`shadowInk`, `shadowA..D`) — promotion into `gui/style.py` is
   assumed by Lantern and available to Ledger; it is a new token family and per the token
   law needs his nod.
5. **If Ledger appeals:** does the LOCKED-row mechanism satisfy the PROTECTED-region
   governance for safety paint, or does he want safety cells kept *out* of the table
   entirely (hard-coded in the components, table forbidden to define them)?
