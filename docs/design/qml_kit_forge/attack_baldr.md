# ATTACK PASS — Baldr on candidate LANTERN

| | |
|---|---|
| **Target** | `candidate_lantern.md` (RATIFIED 2026-07-15, "DO LANTERN") + `round-03/kit.md` §1.2 panel-scoped-calm amendment (same day) |
| **Scope** | Operator side: peripheral motion during live runs, local calm as state indication, focus-ring contrast on composited fills, halo/hover-lift near warn/crit, staleness/disabled on frost |
| **Method** | `kit_contrast_check.py` run as-is where it already answers the question; extended by hand (same `gui.style`/`_blend` primitives, no re-derivation) where it does not; every number below is machine-computed against the live palette, not eyeballed |
| **By** | Baldr, 2026-07-15 |

---

## 0. What I verified as SOUND (stated up front so the findings below read as real gaps, not a blanket rejection)

- **Chip law stays load-bearing.** `candidate_lantern.md` §5's "running" row is unchanged by the panel-scope amendment: material response = "ground calms (§7)"; tier-independent channel = **"run chip word + colour"**. `kit.md` §1.2's amended text states it explicitly: *"A locally-calm pane may serve as a redundant run cue but never the only one (the status chip stays the indicator; state never by motion alone)."* I looked for drift between the amendment and §5's state table and found none — the amendment only touches ground behaviour, never the chip contract. **This is correct and should not be re-litigated.**
- **Hue separation protects the halo from CVD confusion.** `accent` (blue family, `#5AA9FF` dark / `#2A6FE0` light) is chromatically distant from both `warn`/`armed` (amber) and `crit`/`danger` (red) — the two hues most commonly confused under protanopia/deuteranopia are red/green/brown, and blue survives that confusion in both directions. The halo's *hue* is not the risk (see MAJOR-2/3 for what is).
- **Danger rungs correctly refuse hover-lift/convenience** (§5 "danger: none — no hover lift"). That is exactly Baldr law 5 in practice: making a dangerous control *inviting* is the failure mode being avoided, and Lantern kills it structurally rather than by convention.

---

## 1. Findings — ranked

### BLOCKER — stale/semantic ink on `Tile` is compounded by a shipped opacity dim the spec never asked for

`kit.md` §4.3 permits semantic ink directly on the `Tile` rung ("Semantic ink is permitted here"), and Lantern's own §5 state table defines "stale" as an **ink-only** channel: *"ink `muted` + caption / `sim` ink + WORD"* — no opacity term. But the component the kit inventory says it reuses, **`TCT_app/gui/qml/MetricTile.qml:83`**, still carries `opacity: stale ? 0.6 : 1.0` on the whole `Item` — which QML cascades multiplicatively to every child, including any semantic-inked value text (lines 149–223 already do the *correct* ink-swap-to-muted; the opacity stacks on top of that, not instead of it).

I extended `kit_contrast_check.py`'s own primitives (`style._blend`, `contrast_hex`, `worst_ground`, `scene_card_rgb` — no hand hex) to model a stale semantic-ink Tile sitting on a Card, composited at 0.6 opacity over the worst legal ground:

| mode | ink | base (Tile, no stale) | **stale ×0.6 over card/SCENE** | stale ×0.6 over card/TOKEN |
|---|---|---|---|---|
| dark | crit | 5.02 | **2.59 FAIL** | 2.57 FAIL |
| dark | warn | 8.90 | **4.09 FAIL** | 4.07 FAIL |
| dark | good | 8.16 | **3.84 FAIL** | 3.82 FAIL |
| light | crit | 6.03 | **2.79 FAIL** | 2.79 FAIL |
| light | warn | 5.43 | **2.52 FAIL** | 2.50 FAIL |
| light | good | 5.37 | **2.54 FAIL** | 2.52 FAIL |

Every semantic ink fails AA (4.5:1) once stale, and most fail even the non-text 3:1 floor. I scanned for the legal ceiling: the maximum dim that still clears 4.5:1 for the worst ink is **opacity ≥ 0.94 (dark) / ≥ 0.91 (light)** — the shipped `0.6` is roughly six times more aggressive than the tree's own ladder allows.

**Operator-failure scenario:** a stale/disconnected bias or motor reading during a run — exactly the moment staleness is safety-relevant — becomes close to illegible (crit at 2.59:1, below the 3:1 non-text floor) instead of clearly marked-but-readable. This inverts the intent of the ink-based stale law.

**This is not new to Lantern** (the file predates the candidate) but Lantern's own inventory (§4) lists `MetricTile` as a reused capability with zero stated change, and its own §5 table implies the opacity term should not exist. Ship either fix before U2: (a) drop the `opacity` cascade and rely on ink alone (matches the spec as written), or (b) if a chrome dim is wanted, apply it only to non-text chrome (fill/border), never to the `Behavior on opacity` node ink inherits from, and cap it ≥0.94/0.91 if the parent-`opacity` pattern is kept.

**Location:** `TCT_app/gui/qml/MetricTile.qml:83, 149-223`; cites `candidate_lantern.md` §4/§5, `kit.md` §4.3.

---

### BLOCKER — the "ring ≥3:1 on every rung" claim is not actually audited, and the pairing that matters most fails by a wide margin

`candidate_lantern.md` §5 asserts the focus ring is *"the 2 px ring itself (≥3:1 non-text contrast on every rung — **audited**)."* `kit_contrast_check.py` cannot have produced that audit: it walks `accent` against the **containing rung's** composite (card/shelf) only — never against a component's **own resting fill**. I extended the script with the same primitives to close that gap:

| mode | accent-ring vs `raised` (Tile) | vs `well` | vs its **own accent fill** (same-hue variant) | vs `accent_strong` (hover fill) |
|---|---|---|---|---|
| dark | 6.23 PASS | 8.07 PASS | **1.00 FAIL** | **1.37 FAIL** |
| light | 5.42 PASS | 3.97 PASS | **1.00 FAIL** | **1.28 FAIL** |

Tile and Well backgrounds are fine. The failure is structural: any interactive surface whose **own** resting/hover/pressed fill is already accent-toned — primary/motion `ActionBar` class (`style.py` QSS precedent, `QPushButton:default`/`[state="primary"]`, `background: accent`), pressed `secondary` buttons (`background: accent` on press), `StatusPill` info/busy (`border-color: accent@0.55`), a selected `SegmentedControl` thumb tinted accent — draws the **same hue ring against the same hue fill**. 1.00–1.37:1 is not a subtle miss; it is functionally invisible.

**Mitigating factor, not a fix:** the shipped QSS precedent (`QPushButton:focus { outline: 2px solid accent@0.30; outline-offset: 1px; }`) draws the ring **outside** the button, landing on the surrounding pane instead of the button's own fill — where accent already clears comfortably (6.65 dark / 5.47 light on card/SCENE, both computed by the unmodified script). *If* Lantern's `BorderImage` ring preserves that outward-offset convention on every rung and every accent-toned variant, this failure may be unreachable in practice. But the spec never states an offset value, never enumerates which components have accent-toned resting fills, and the "audited" claim in §5 is not backed by any check that actually walks this pairing.

**Operator-failure scenario:** tabbing to "Start Scan" or a motion-class command (both plausibly accent-styled) produces no visible focus change — a keyboard-only or low-vision operator cannot confirm which control is about to receive Enter/Space, directly against Baldr law 4.

**Missing-check spec** (deliverable requested explicitly): extend `kit_contrast_check.py` with:
1. a `NON_TEXT_PASS_THRESHOLD = 3.0` path alongside the existing hardcoded 4.5 in `_pass()` (currently text-only; the ring needs the UI-component floor, not the text floor);
2. a `ring_contrast_scan()` that walks the ring hex against **every** rung's SCENE+TOKEN composite (card, shelf, tile=`raised`, well, island=`PLOT_BG`, hazard=`panel`) — today only card/shelf are modelled;
3. a second pass that walks the ring against every interactive **component's own** fill token (`accent`, `accent_strong`, `tint`, `pressed`) read from `style.palette()` by name, not hand-copied — this is exactly the pairing that fails above and the one the current script structurally cannot see;
4. the halo modelled separately, at its own alpha (0.35/0.25), explicitly labelled "decorative — informational only, does not gate ship" per §6's own "ring is the accessible channel; halo is garnish" language, so a halo-only miss never blocks the ring's pass/fail verdict.

---

### BLOCKER — Hazard-rung focus visibility is ambiguous in the spec text, on the single highest-stakes control class

§5's "danger" row: *"none — the material is DEAD on hazard rungs: no hover lift, no frost, no halo."* §5's "focus" row: *"the luminous focus ring is the same component everywhere, so focus visibility is audited once, per rung, not per widget."* These two rows are in tension and the spec never resolves it in writing: does "no halo" (danger row) also suppress the **ring** on Hazard controls, or only the decorative glow?

The charitable reading — supported by §6's "the ring is the accessible channel; halo is garnish" — is that the ring survives on Hazard (it is not a "material"/glass response, it is a pre-rendered `BorderImage` accessibility primitive) and only the halo dies there along with hover/frost. But **the spec never states this explicitly**, and the control class in question is HV enable, arm, homing, scan start — Baldr law 4's least-negotiable case and the one place a silent ambiguity is least acceptable. Read literally, "no halo" full-stop on a rung whose interaction-states are all supposed to be tier-independent (§11: "hazard channels are all tier-independent") could be implemented as "no focus indicator at all," which is a WCAG 2.4.7 (Focus Visible) failure on the ArmLatch/DangerGate controls.

**Fix is one sentence, not a redesign:** the spec should say explicitly — *"the 2 px ring is not part of 'the material' the danger row kills; Hazard rungs keep the ring, lose only the halo."* Flag as BLOCKER given the stakes of getting this wrong by omission, not because the fix is hard.

---

### MAJOR — peripheral motion during a live run, worst legal setting: the numbers, and where they brush the ratified panel scope

Per `candidate_lantern.md` §7 and the round-03 amendment: `groundFlowPeriodS` = 90 s base, `full` amplitude ≈ 8% of the viewport, speed scales 0.25–2.0×. At the **worst legal combination** requested by the brief (full × speed 2.0, assuming period = base/speed, which the spec does not state explicitly as a formula — see MINOR-2): **period ≈ 45 s, amplitude ≈ 8% of viewport** (~150 px on a 1920 px lab window), continuously, for the duration of any run, in every panel that does not own that run — by design, per the panel-scoped ratification.

**Numbered-SC check:** no single WCAG SC is unambiguously breached.
- SC 2.2.2 (Pause/Stop/Hide, Level A) requires *a mechanism*; the persisted `off/subtle/full` setting satisfies the letter of it — **provided it is genuinely reachable**. I checked: it does not exist yet (`TCT_app/gui/app_settings.py`, `TCT_app/gui/style.py` — only the pre-existing `MOTION_ENABLED_KEY`/`motion_enabled()` reduced-motion toggle exists, a different, coarser switch that also kills interactive springs). "Off remains one click away" (§7) is an unverified aspiration against an unbuilt control, not a located one — see MINOR-1.
- SC 2.3.1/2.3.3 don't cleanly apply (sub-1 Hz ambient motion is not flashing, and this isn't interaction-triggered).

**The real finding is operational, not a numbered-SC violation:** an operator watching Panel A's live scope trace during acquisition, with Panel B (motor) or Panel C (bias) in peripheral view — panels the operator is *also* actively watching for the same run, not decorative dead space — sees large (~150 px), continuous, slow-drifting washes in their peripheral field for the entire run. This is a textbook vection/attention-competition trigger for motion-sensitive operators, and it works directly against Baldr law 6 (glance-readability, sustained attention while a beam is on) independent of whether any WCAG number technically clears.

**This does brush the ratified panel-scope decision itself** — not the "only the owning panel stills" mechanic, which I am not contesting, but its unstated assumption that "the rest of the room" is attention-idle during a run. In a multi-instrument cockpit, adjacent panels (motor, bias) are frequently *also* being watched during the same acquisition. `00_comparison.md` §3 already flagged this exact question as open for Kaya ("must the spec forbid any run-state coupling and gate the calm on something else, e.g. any-window-has-live-plot?") — I am answering it with a measured worst-case number instead of leaving it abstract, per this brief's explicit instruction to name the number and propose the narrowest fix rather than re-litigate the ratification.

**Narrowest fix, in order of preference:**
1. **Clamp, not calm:** whenever *any* panel anywhere is RUNNING, cap the *effective* speed multiplier at 1.0× app-wide (not 2.0×), restoring the full 0.25–2.0× range only when the whole app is idle. The rest of the room keeps flowing exactly as ratified — it just cannot reach its fastest/largest setting while a beam is on anywhere. This preserves "by design" peripheral motion while bounding the worst case to the numbers a subtle-tier default already ships (half amplitude/speed).
2. Alternatively/additionally: extend "owns the run" from the single run-controlling panel to "any panel currently rendering live telemetry for the same run" (motor/bias readouts watched alongside the scope) — narrower than whole-room calm, wider than the single owning panel.

**Flagging per the brief: this finding touches the ratified panel-scope's assumptions and Kaya should hear it verbatim, not just the mitigation.**

---

### MAJOR — the halo is a third translucent-pixel mechanism, and §8's dead-zone law never names it

`kit.md` §8 (carried into Lantern verbatim): island and hazard rects are dead zones — *"no pane may sample, shadow, or extend translucent pixels within `spaceMd` of them"* — enforced by a runtime geometric assertion and an offscreen "walk all Surfaces × all holes" test. That enumeration names two mechanisms: **sample** (frost bake, §3.2) and **shadow** (the 9-patch ladder, §3.1). The focus halo is explicitly a **third, separate** translucent-pixel mechanism — §5 calls it out by name as "not an effect... pre-rendered `BorderImage`," distinct from both frost and shadow — and it is not named in the dead-zone enumeration or its test.

**Concrete risk:** a focused Card/Tile within `spaceMd` of an Island (a live plot) or a Hazard stripe can legally render its 8 px soft halo bleeding into that dead zone, and the promised offscreen test would not catch it — it was never told to look for a third channel. This is the same "adjacent-row" class of gap the brief's own attack language names for Ledger's table, found instead in Lantern's own geometric law.

This is also the structural reason candidate's own weakness #4 (halo near warn/crit chips, "flirts with the alarm-adjacent") cannot be fully dismissed by hue-separation alone (see §0 above): hue protects against *misreading* the halo as a state colour; it does not protect against the halo visually merging with a chip at real viewing distance if no minimum gutter is enforced between them. Chips/hazard elements are exactly the case §8 already tries to protect and simply forgot to extend to the third channel.

**Fix:** add "halo" to §8's dead-zone enumeration and its geometric/offscreen test before U2. One line in the spec, one line in the future test's mechanism list.

---

### MINOR — `living_glass` off/subtle/full has no located control yet

Grepped `TCT_app/gui/app_settings.py` and `TCT_app/gui/style.py`: no `living_glass` persisted key exists. The only related control is the pre-existing `MOTION_ENABLED_KEY`/`motion_enabled()` reduced-motion toggle, which is a different, coarser switch (also disables interactive springs, not just ambient flow). §7's "off remains one click away" is a design intent, not a located UI element. Recommend U2 spec exactly where the quick toggle lives (chrome-level, not nested in a preferences dialog) and explicitly document the relationship/precedence between the new 3-state setting and the existing reduced-motion switch so support doesn't inherit two overlapping toggles with unclear interaction.

### MINOR — "speed-scaled 0.25–2.0×" formula is unstated

I assumed `period = groundFlowPeriodS / speed` (2.0× ⇒ 45 s) to compute the MAJOR-1 worst case. The spec never states the formula. A one-line clarification prevents an implementer from inverting it (accidentally shipping a *slower* "2.0×" or a much faster one than intended).

### MINOR — existing `VitalChip.qml` is a colour-only precedent Lantern's `StatusPill` must not inherit

`TCT_app/gui/qml/glassshell/VitalChip.qml:47-52` ships a 7×7 px state dot with no independent glyph/shape; its redundancy today comes only from accompanying value text that is *itself* state-inked (same colour source, not an independent channel), while the label word stays neutral `muted`. Not a Lantern defect — this file predates the candidate and is presumably superseded — but it is a live pattern in the tree under a similar name to Lantern's own `chip`/`StatusPill` (kit.md §4.7: "glyph + word + colour"). Flagging so U2 doesn't copy this file forward under the Lantern name without adding the glyph channel kit.md already promises.

---

## 2. Verdict

**Not ready to move to code as written — but every BLOCKER here is a one-to-few-line spec fix, not a redesign, and none touch the frost-bake premise (that risk belongs to Loki's pass, not mine).** The material system, the tier-invariance rule, and the chip-as-indicator law are sound and I found no drift in them. The failures cluster in exactly the two places the brief predicted an attack pass would need to look — the newly-permitted peripheral motion, and the ring/halo's contrast against composited fills nobody had modelled — plus one I found by extending the arbitration script rather than re-arguing it: the stale-Tile opacity stacking, which is a real, already-shipped, already-numeric AA failure waiting in `MetricTile.qml`, independent of anything Lantern adds.

**One finding brushes the ratified panel-scope decision's assumptions** (peripheral motion during runs the operator is actually watching, not decorative dead space) — flagged above for Kaya verbatim, with a narrow clamp-based fix proposed rather than a request to re-open "does the rest of the room still."

---

## 3. Open questions for Kaya (routed through Adam)

1. Peripheral-motion clamp during runs (MAJOR-1): accept the "cap speed at 1.0× app-wide while any run is active" clamp, or does he want the full 0.25–2.0× range preserved even during acquisition and accept the operator-distraction cost as the price of "the glass stays alive"? This is the same collision `00_comparison.md` already named between his living-glass wish and the distraction gate — I'm bringing back a number, not reopening the question.
2. Confirm the Hazard-ring reading (BLOCKER-3): ring survives, only halo dies on Hazard rungs — needs to be spec text, not inference.
