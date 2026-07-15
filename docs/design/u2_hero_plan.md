# U2 hero slice — ScanViewer implementation plan (PAPER ONLY)

| | |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-15 (night) |
| **Status** | Implementation plan on paper — **NO beat in this file may be dispatched until BOTH of Kaya's morning gates pass**: (1) the **measurement-B live operator run** (`TCT_app/scripts/spike_measurement_b.py`, windowed, operator-only) with thresholds tuned from printed numbers and ratified per kit spec §7.1; (2) the **kit-spec v1 signature** (`docs/design/qml_kit_forge/kit_spec_v1.md` §§1–6 + Appendix A). A third mechanical entry dependency: the **Theme-bridge beat** (42 exposures, `tests/test_qml_theme_bridge.py`, shadow-family promotion into `gui/style.py`) must be landed and green — it is in flight tonight (noah-bridge); U2.1 verifies, never re-does, it. |
| **Stage** | `docs/ROADMAP_MASTERPLAN.md` Part II §UI, **U2** — "ScanViewer hero slice (M; proves panel-VM-island pattern + implements the U1.5 kit spec as the reference implementation; [Kaya] pattern sign-off)" |
| **Binding design law** | `docs/design/qml_kit_forge/kit_spec_v1.md` (post-signature) — Surface/rungs/state table §2, inventory §3, focus laws §4, motion/calm §5, bridge contract §6/Appendix A |
| **Boundary law** | `docs/design/run_state_facade.md` §1 + `docs/design/u1_staging.md` §1.2 — a VM holds no controller reference, no command callables |
| **Safety carve-outs** | Masterplan NEVER-migrates list (PROTECTED); `docs/SAFETY_NORMATIVE_TESTS.md` — `tests/test_scan_viewer_wiring.py` is the safety wiring host and is **byte-untouched by every U2 beat** (§3.2 below states how it stays green anyway) |
| **Gate criteria at exit** | Standing U-stage gate incl. the ruling-8 **distillation balance** (net LOC + explicit delete list — DECISIONS 2026-07-15 night) + the named per-panel `TCT_SHELL=qml` offscreen smoke |
| **Fallback context** | If measurement B had failed, the ratified fallback is run-active **global** calm; §4 R4 states what that changes in this plan (little — one policy switch) |

U2 replaces the QWidget face of the Scan Viewer with a QML face built from the
Lantern kit, hosts its two pyqtgraph islands and its command affordances by
the ratified hole-and-frame mechanics, and retires the old face under the
distillation gate. It is the **reference implementation**: every later panel
(U3–U5) copies this pattern, so U2 optimizes for *being copyable*, not for
being minimal.

---

## 0. What U2 stands on (all landed at HEAD, verified against the tree)

- **VMs (U1.2, landed):** `TCT_app/gui/scan_viewer_viewmodel.py`
  (`ScanViewerViewModel`, composes `run` = `RunStateViewModel`) +
  `TCT_app/gui/run_state_viewmodel.py` (ETA/elapsed single derivation, Q1
  ruling). VM suite `tests/test_scan_viewer_viewmodel.py` + standing-law pair.
- **Old face:** `TCT_app/gui/scan_viewer_panel.py` (602 lines) — delegates to
  the VM; residue suite `tests/test_scan_viewer_panel.py` = **23 (b) tests**
  (recounted at HEAD this beat).
- **QML plumbing:** `gui/qml_shell.py` (RHI pin, QQuickWidget chrome,
  `_ShellBridge`), `gui/qml_theme.py` Theme singleton (+ the 42 exposures
  landing tonight), `gui/qml/MetricTile.qml` (pre-kit; stale-dim already
  retired per ruling 2), `gui/qml/ScanStatusStrip.qml`, `Shell.qml`.
- **Measurements:** A (frost bake O(1) in panes, island ≥ 30.31 Hz — HELD);
  B (acquisition headroom — the morning gate). **Both spikes hosted the
  pyqtgraph island in its own top-level window**; the in-window overlay is
  *not yet measured* → §2 U2.4 carries an entry micro-spike (spikes-are-routine
  rule).
- **Run-ownership (ruling 7):** the run-owning pane = the top-level hosting
  the ScanViewer, gated by `facade.active`. U2 is the first consumer of this
  convention (panel-scoped calm wires to `vm.run.active`).

---

## 1. The slice shape — option (a) mechanics, stated precisely

The ratified architecture (masterplan Part II §UI, web-verified note) is
**QWidget tree + QQuickWidget islands**, and its terms are load-bearing:

1. **The panel stays a QWidget** (`QWidget` subclass, same class name and
   signal/slot surface as today — see §3.2). Inside it, **one `QQuickWidget`**
   renders the whole QML face (`SizeRootObjectToView`), and the pyqtgraph
   islands + the command strip are **ordinary sibling QWidgets stacked above
   it** at published hole rects.
2. **`QWindow.createWindowContainer` / Qt 6.7-6.8 `WindowContainer` are NOT
   used, anywhere in U2.** WindowContainer hosts *windows*, not widget trees;
   a contained window is a native child that "renders as an opaque box on top
   of the QWidget hierarchy" — airspace. That path is explicitly rejected by
   the masterplan (revisit only at Qt 6.10+ LTS with a bench spike). The
   QQuickWidget direction is the opposite one: QML *into* the widget tree,
   texture-composited, no stacking-order restriction, reparentable (which is
   what keeps detach/redock alive).
3. **Hole-and-frame (kit spec §1.4/§3 FigureCard; candidate_twin §8 mechanism,
   Lantern-ratified):** the QML `FigureCard` draws Card frame + `hairlineStrong`
   outline + `edgeShade` inner rim around a **reserved hole** and publishes the
   hole rect; the Python side positions the island QWidget into it. The kit
   never parents, paints, or overlaps island pixels. Because the QQuickWidget
   uses `SizeRootObjectToView`, QML scene coordinates == the QQuickWidget's
   logical widget coordinates — the mapping is `holeRect` offset by the
   QQuickWidget's position in the panel; no DPR arithmetic (both sides are in
   device-independent px).
4. **ScanViewer's islands are raster pyqtgraph** (`ScanMapView` ImageView +
   the z-focus `PlotWidget`) — **no `QOpenGLWidget` in this panel** (the GL
   stage view is Motor, U5). So the native-child airspace problem cannot arise
   in U2 by construction; what remains is repaint interaction (§4 R1).
5. **Never-migrates law applied to this panel:** Abort stays a QWidget
   `QPushButton` instance, **re-parented, never re-implemented** (§2 U2.5).
   U2 extends the same treatment to every command-emitting control (Pause,
   Find focus, Apply-to-Planner, Open-in-Analysis) — see the U2.5 rationale.
6. **The two-shell window:** the old face and the new face coexist behind
   `TCT_SHELL` (classic default) until the U2.7 retirement ruling at Kaya's
   sign-off. One process only ever constructs one face.

Panel composition (the pattern every U3–U5 panel copies):

```
ScanViewerPanel (QWidget, same class/signals/slots as today)
 ├── QQuickWidget  ── ScanViewer.qml (kit Surfaces; binds ctx props
 │        │           `viewer` = ScanViewerViewModel, `viewer.run`, `Theme`)
 │        └── publishes hole rects: mapHole, zfPlotHole, commandHole
 ├── ScanMapView            (sibling QWidget → positioned into mapHole)
 ├── z-focus PlotWidget      (sibling QWidget → positioned into zfPlotHole,
 │                            visibility synced to the QML CollapsibleCard)
 └── ScanViewerCommandStrip  (sibling QWidget → positioned into commandHole;
                              Pause/Abort/Find-focus/Apply/Open buttons —
                              the ONE home of command affordances, §2 U2.5)
```

---

## 2. Beat decomposition

Dependency shape (after the morning gates):

```
[overlay micro-spike]  ─┐            (day 0, parallel, throwaway)
U2.1 Surface core ──► U2.2 components ──► U2.3 face+VM
                        │                     │
                        └──► U2.4 island host ┴─► U2.5 command re-host
                                                    └─► U2.6 TCT_SHELL switch
                                                          └─► U2 exit gate
                                                                └─► U2.7 retirement + gate line
Mamoru standup at each wave boundary (U2.2|U2.4 → U2.5 → gate) — standard.
Shiori brief-check before every dispatch (paths free, named APIs real).
```

### U2.1 — `Surface` + material core (kit spec §2 as running code)

- **Owner/model:** Noah, **Fable** (design-system reference implementation =
  judgment beat per the standing rule).
- **Builds:** `gui/qml/kit/Surface.qml` (rung ladder §2.2, tier resolution
  §2.3, state table §2.6, construction throw on `rung: Hazard` + glass flags),
  `gui/qml/kit/LivingGround.qml` (band law, no semantic tint, speed setting +
  **run-active ≤1.0× clamp**, ruling 1), the frost bake (`ShaderEffectSource`
  + ONE blur on the source; per-pane `sourceRect` samplers; 0/6/12 Hz cadence),
  `gui/qml/kit/FocusRing.qml` (outside-offset ring + halo `BorderImage`,
  §4.1), pre-rendered 9-patch shadow assets + their small generator script,
  the **dead-zone registry** (scene-level list of island/hazard rects; debug
  geometric assertion), `gui/qml/kit/qmldir`.
- **Calm policy as ONE switch:** panel-scoped calm (run-owning pane stops
  scheduling its sampler, ground stills behind it) and the ratified fallback
  (run-active global calm, bake→0 Hz) are the **same hook with a policy
  flag**, decided by the morning measurement-B outcome — a B surprise flips a
  flag, not the beat (§4 R4).
- **Does NOT touch:** `gui/style.py`, `gui/qml_theme.py`, `gui/app_settings.py`
  — the bridge beat (§6 contract) owns those and lands first. Any gap found →
  escalate to Adam for a bridge micro-beat, never silent widening.
- **Locks:** `gui/qml/kit/*` (new), `scripts/gen_shadow_assets.py` (new),
  `tests/test_qml_kit_surface.py` (new). (`scripts/kit_contrast_check.py`'s
  `ring_contrast_scan` already landed with 6452da3 — consumed, not edited.)
- **Exit:** offscreen suite green (rung resolution per tier; state table;
  hazard-throw; band-law N-random-phase test; reduced-motion collapse);
  `kit_contrast_check.py` incl. ring scan green; inline-hex guard covers the
  new `.qml` (extend `tests/test_no_inline_hex_gui.py` additively if its glob
  is `*.py`-only); no `MultiEffect` outside the single source-blur
  (`GLASS_LIVE_PANE_BUDGET = 1` lint).

### U2.2 — Kit components against the §3 inventory (ScanViewer subset)

- **Owner/model:** Noah, sonnet.
- **Builds** exactly the components the ScanViewer face consumes, each as
  `Surface` + content: `PanelHeader`, `StatusPill`, `Card`, `MetricTile`
  (kit rework of the shipped file — ink-only stale + unconditional STALE
  marker carried over), `MetricGrid`, `CollapsibleCard` (spring unfold),
  `ActionBar` (frame + primary/secondary layout; its **danger and motion
  slots are reserved holes**, not buttons — §2 U2.5), `EmptyState` (+error),
  `FormRow`, `FigureCard` (frame + published `holeRect`). Deferred to first
  consumer (U3+): `HazardSurface`, `SegmentedControl`, `CheckableCard`,
  `Well` — the spec is the contract; U2 implements the consumed subset and
  says so in the gate line.
- **Rework, feeding the delete list:** `gui/qml/ScanStatusStrip.qml` rebinds
  to the kit `MetricTile`; the pre-kit `gui/qml/MetricTile.qml` is then
  superseded and deleted (U2.7 ledger). `tests/test_qml_scan_status.py` gets
  additive assertions only.
- **Locks:** `gui/qml/kit/*.qml` (new components), `gui/qml/ScanStatusStrip.qml`,
  `tests/test_qml_kit_components.py` (new), `tests/test_qml_scan_status.py`
  (additive).
- **Exit:** per-component offscreen tests green (paint/motion obligations per
  §3 rows, incl. MetricTile stale = ink-only + marker; StatusPill never
  colour-alone; hit targets ≥36/44 px); strip renders via kit tile with
  existing strip suite green.

### U2.3 — `ScanViewer.qml` face + additive VM growth

- **Owner/model:** Noah, sonnet (Adam may lift to Fable — the face layout is
  the panel's design moment).
- **Builds:** `gui/qml/panels/ScanViewer.qml`: header (PanelHeader + run
  StatusPill), FigureCard(mapHole), terminal banner (Card + StatusPill +
  reserved hole edge for the Open button — strip-hosted, §U2.5), MetricGrid
  of 4 tiles bound `viewer.progress*/run.etaText/currentPositionText/
  run.elapsedText` + staleness, ActionBar frame (commandHole), z-focus
  CollapsibleCard (FormRow + SpinBoxes + FigureCard(zfPlotHole) + best-Z
  readout).
- **VM growth (additive, boundary-preserving — `gui/scan_viewer_viewmodel.py`):**
  1. **Terminal-variant derivation moves in from the old face's
     `_paint_terminal`:** `terminalVariant` (`"fault" | "aborted" |
     "finished" | ""`), `bannerText`, `runChipWord`/`runChipToken` — with the
     pinned semantics: fault outranks abort; abort is per-run one-shot; fault
     survives the double `scan_finished` on the fault path. Fed by a new
     display feed the panel calls from its Abort click. **Naming hazard,
     flagged:** the standing-law test forbids command-named attributes
     (`abort` among them) — the feed must be named to pass it (e.g.
     `note_operator_stop_pressed()`); the implementer aligns the name with
     `test_read_only_no_command_surface`'s actual matcher before landing.
  2. **`lastBestZ`** (float-or-None mirror; Apply eligibility) — the old
     face's `_last_best_z` moves in.
  3. **Z-focus form model:** plain data fields (mode, y, z0/z1/dz, averages,
     settle, edge center/range/step) + `set_*` feeds bound from the QML form;
     defaults identical to today's spinbox defaults. The VM never builds
     `ZFocusScanConfig` (no `controller` import — same discipline as
     `RunStateViewModel`); the panel assembles the config from VM fields at
     the Find-focus click.
  All growth lands with (a)-class tests; the standing-law pair must stay
  green on the grown VM.
- **Locks:** `gui/qml/panels/ScanViewer.qml` (new), `gui/scan_viewer_viewmodel.py`,
  `tests/test_scan_viewer_viewmodel.py` (additive), `tests/test_scan_viewer_qml.py`
  (new — the QML-walker suite, §3.3).
- **Exit:** face loads offscreen bound to a live VM; walker suite green;
  grown VM suite + standing-law pair green; `tests/test_scan_viewer_panel.py`
  residue **byte-untouched and green** (old face still delegates correctly —
  the U1 fidelity proof repeated for the VM growth).

### U2.4 — Island embedding (hole-and-frame runtime)

- **Owner/model:** Noah, **opus** (widget lifecycle/reparent/teardown class).
- **Entry micro-spike (throwaway, half-day box, runs day 0 in parallel):**
  `scripts/spikes/island_overlay_spike.py` — ScanMapView overlaid on a
  QQuickWidget in ONE top-level (living ground `full`, bake 12 Hz), sim scan
  point feed; measure island effective Hz + QML fps + full-window repaint
  storms. Both prior measurements used a *separate* top-level for the island;
  this closes that gap before architecture commits (spikes-are-routine).
  Pass bar: island ≥ 28 Hz and QML fps ≥ 55 (measurement-A floors). Artifacts
  to `artifacts_claude/`.
- **Builds:** `gui/qml_island_host.py` — `IslandHost`: owns the QQuickWidget,
  looks up published hole rects by objectName, positions registered sibling
  QWidgets (`setGeometry` + `raise_()`), tracks geometry changes (batched via
  a 0-timer on the QML items' rect-changed signals), syncs visibility (the
  z-focus island hides while its CollapsibleCard is collapsed — and per the
  kit law, the unfold spring never animates *adjacent to* the open hole: the
  card unfolds first, then the island appears, ≤100 ms crossfade), and
  registers every hole in the U2.1 dead-zone registry.
- **Dead-zone law as tests:** `tests/test_qml_dead_zones.py` — offscreen
  walker: all Surfaces × all holes × all three mechanisms {sample, shadow,
  halo}, ≥ `spaceMd` (12 px) clearance; plus the runtime debug assertion
  wired in `IslandHost`.
- **Detach smoke now, not at flip:** hybrid panel torn into a floating
  top-level and redocked (QQuickWidget reparent) without losing bindings —
  a detached ScanViewer is its own ground and **calms whole** (ruling 7).
- **Locks:** `gui/qml_island_host.py` (new), `tests/test_qml_island_host.py`
  (new), `tests/test_qml_dead_zones.py` (new), `scripts/spikes/
  island_overlay_spike.py` (throwaway).
- **Exit:** spike numbers recorded and above floors; positioner tests green
  (resize, theme flip, hide/show, detach/redock); dead-zone walker green.
  **Immediate Mary review** (lifecycle/teardown class).

### U2.5 — Command/danger affordance re-hosting (re-parent, never re-implement)

- **Owner/model:** Noah, **opus** (danger-affordance class per the standing
  override). **Immediate Mary review** (safety-class beat).
- **The one-home extraction:** a new `ScanViewerCommandStrip(QWidget)`
  (inside `gui/scan_viewer_panel.py` or as `gui/scan_viewer_commands.py`)
  becomes the **single construction site** of the five command buttons —
  Pause, **Abort** (`objectName="dangerBtn"`, `state="danger"`, unchanged),
  Find focus (`state="motion"`), Apply-to-Planner, Open-in-Analysis — plus
  their enable-state logic reading the VM (`run.active`,
  `openInAnalysisEligible`, `lastBestZ`). Both faces then **re-parent** this
  strip: the old face embeds it where its ActionBar row sat (panel attributes
  `_btn_pause`/`_btn_abort`/`_btn_zf_start`/`_btn_apply_best_z`/
  `_btn_open_analysis` become aliases to the strip's buttons so the 23 (b)
  residue tests stay **byte-untouched and green**); the hybrid face positions
  it into the ActionBar/banner holes via `IslandHost`.
- **Why all five, not just Abort:** Abort is never-migrates law (PROTECTED).
  Find focus starts real stage motion (rule 2 class). Pause/Apply/Open are
  not safety-listed — but hosting them QML-side would fork the command
  surface into two technologies inside one panel and put `emit`-capable
  items into QML in the very slice meant to prove "the shell displays, the
  panel acts". One strip = one review surface for Mary, byte-stable command
  signals, and the exact `SequencerCommandHost` shape U4/U5 already plan.
  The kit's QML `ActionBar` is still exercised — as the *frame* those
  buttons sit on.
- **What is explicitly NOT built:** no second Abort implementation, no QML
  item that emits any of the five command signals, no change to any
  `*_requested` signal signature, no edit to `tests/test_scan_viewer_wiring.py`.
- **Locks:** `gui/scan_viewer_panel.py` (strip extraction + aliasing; chrome
  otherwise untouched), `gui/scan_viewer_qml_panel.py` (new — the hybrid
  face host, assembling QQuickWidget + IslandHost + strip + islands behind
  the same class-surface contract, §3.2), `tests/test_scan_viewer_panel_qml.py`
  (new — the K-class re-hosts, §3.1).
- **Exit:** `tests/test_scan_viewer_panel.py` green **byte-untouched**;
  `tests/test_scan_viewer_wiring.py` green **byte-untouched**; hybrid suite
  green; Mary confirms: same button instances/objectNames, no new command
  path, no QML emit surface, hit targets ≥ 44 px for danger/motion.

### U2.6 — `TCT_SHELL` switch path + composition-root VM lift

- **Owner/model:** Noah, sonnet.
- **The switch (masterplan name, introduced here):** `TCT_SHELL ∈ {classic,
  qml}`, unset ⇒ `classic`. `qml` ⇒ QML chrome (today's `TCT_QML_SHELL=1`
  path) **+ the QML face for every migrated panel** (U2: ScanViewer only).
  `classic` ⇒ everything as today. Back-compat: `TCT_QML_SHELL=1` with
  `TCT_SHELL` unset keeps meaning chrome-only (existing tests/`run.ps1`
  behavior unchanged); `run.ps1` gains `-Shell qml` and keeps its current
  default. One shim in `main.py`/`tct_gui.py`, resolved once, logged.
- **VM lift (u1_staging §1.1's booked second step):** under `qml` the
  composition root constructs `ScanViewerViewModel`, registers it as QML
  context property (`viewer`), and hands it to the hybrid face. The classic
  face gains an optional `vm=None` kwarg (constructs its own by default —
  additive; (b) tests untouched). Coordinator signal wiring in `tct_gui.py`
  (lines ~659–713 today) is face-agnostic because both faces expose the same
  slots — the connect block does not fork.
- **The named per-panel smoke (standing gate, instantiated):**
  `tests/test_shell_switch_scan_viewer.py::`
  `test_scan_viewer_boots_under_tct_shell_qml_offscreen` (TCTMainWindow, sim
  config, hybrid face constructed, QML status != Error) and
  `::test_vm_contract_replay_under_qml_face` (the VM-contract event sequence
  driven through the hybrid panel's slots, VM properties asserted) — "a
  flagged panel that is green-on-classic but dead-under-qml can never merge."
- **Locks:** `TCT_app/main.py`, `TCT_app/tct_gui.py`, `TCT_app/run.ps1`,
  `tests/test_shell_switch_scan_viewer.py` (new), `TCT_app/README.md`
  (switch table). *(Busy-file warning: `tct_gui.py` — ledger lock required;
  no parallel beat may hold it.)*
- **Exit:** both boots green offscreen; classic boot behavior-identical
  (wiring + residue suites green); `test_qml_shell.py` green.

### U2 exit gate (standing gate instantiated — runs BEFORE U2.7)

1. **[A-green]** — `.claude/check_bucket_a.ps1`.
2. **S2 normative suites** — targeted: `test_scan_viewer_wiring.py`
   (byte-untouched), `test_qt_danger_gate.py`, `test_scan_coordinator.py`,
   `test_run_state_viewmodel.py`, sequencer (c) residue.
3. **[Bench]** — one full suite on sophonone (`bench_run.ps1 -Branch
   ui-qml-migration`); bench down ⇒ said explicitly, merge waits.
4. **Per-panel qml smoke** — the two named tests in U2.6.
5. **Classic + qml shells boot in simulation** (`run.ps1` smoke both ways).
6. **Mary** — U2.4/U2.5 already immediate; U2.1+U2.2+U2.3 as one thematic
   "kit conformance + VM boundary" batch; U2.6 rides the gate review.
7. **Mamoru standup** — claims-vs-git + lock/tree cross-check.
8. **[Kaya] pattern sign-off** — §5. The distillation gate line (U2.7)
   reports at this sign-off.

### U2.7 — Old-face retirement + the distillation gate line (post-sign-off)

- **Owner/model:** Noah sonnet (code) + Samantha (pattern doc) + Kiroku
  (ledger/bucket-map/ARCHITECTURE) — three small dispatches.
- **The face-flip ruling (taken AT the §5 sign-off):** Kaya rules whether the
  classic QWidget face retires now (hybrid face serves both shells; FLAT/TOKEN
  tier is the degradation posture — tier invariance §2.3 makes the QML face
  fully legible with glass off) or is retained as fallback until U6.
  - **Flip ⇒ delete list executes:** `gui/scan_viewer_panel.py` loses its
    QWidget chrome (`_build_ui`, `_build_finished_banner`,
    `_build_z_focus_card`, `_paint_terminal`, tile/chip/banner painting,
    banner QSS in `refresh_theme` — ≈420 of 602 lines); the hybrid host takes
    over the module/class name (import path + class surface preserved, so
    `test_scan_viewer_wiring.py` stays byte-untouched and green — the
    invariant detector across the flip); `tests/test_scan_viewer_panel.py`
    retires with a per-test disposition map in the diff (§3.1);
    `gui/qml/MetricTile.qml` (pre-kit, 278 lines) deleted.
  - **Retain ⇒ deferred-delete ledger:** the same list, booked verbatim
    against U6 in the gate line + `docs/TECH_DEBT.md`; ruling 8's
    "deliberately retained = ratified essence" clause covers it only via
    Kaya's explicit retention ruling — which this sign-off is.
  - **Deletes that happen in EITHER outcome** (the guaranteed non-empty
    delete list): the old face's duplicated state mirrors —
    `_run_active`, `_last_run_path`, `_zf_z_data`/`_zf_a_data`,
    `_last_best_z`, `_fault_pending`/`_fault_reason`/`_abort_pending` +
    `_paint_terminal` (all superseded by U2.3 VM growth; the classic face
    reads the VM), and the pre-kit `MetricTile.qml` once the strip rebind
    lands.
- **Gate-line format (ruling 8, proposed accounting convention — Adam
  confirms, §7 Q2):** report (a) whole-stage net LOC, split **kit-platform**
  (one-time, amortized over U3–U5) vs **panel-scope** (hybrid face + VM
  growth − deleted old face/tests — expected ≈flat-to-negative under the
  flip), and (b) the explicit delete list with file:symbol granularity.
- **Pattern doc (masterplan risk 7):**
  `docs/design/panel_vm_island_pattern.md` — the copyable recipe (host shape,
  hole publication, command-strip law, VM lift, smoke names); every U3–U5
  panel PR cites it.
- **Locks:** `gui/scan_viewer_panel.py`, `gui/scan_viewer_qml_panel.py`,
  `tests/test_scan_viewer_panel.py`, `tests/test_scan_viewer_panel_qml.py`,
  `docs/design/panel_vm_island_pattern.md` (new), `docs/test_bucket_map.md`,
  `docs/ARCHITECTURE.md`, `docs/TECH_DEBT.md` (if retained).
- **Exit:** suite green post-deletion; both shells boot; gate line recorded
  in the ledger + this file's amendment log.

---

## 3. Test strategy

### 3.1 The 23 (b) residue tests — per-test disposition

Legend: **K** = re-hosts on the hybrid face (command strip + islands survive;
near-byte-identical, lands in `tests/test_scan_viewer_panel_qml.py` during the
two-shell window and becomes THE panel suite at the flip) · **W** = becomes
QML-walker class (`tests/test_scan_viewer_qml.py` — offscreen item lookup by
objectName, binding/state assertions) · **V** = its guarantee moves to the VM
suite (U2.3 growth) · **S** = split.

| # | test | disposition |
|---|---|---|
| 1 | `test_construct_headless_no_hardware` | K (asserts VM defaults instead of dead panel attrs) |
| 2 | `test_initial_state_shows_empty_state_and_disabled_run_control` | S — buttons+map K; banner-hidden → W |
| 3 | `test_map_toolbar_reachable_in_empty_state` | K (island internals untouched) |
| 4 | `test_point_done_before_scan_started_still_swaps_to_map` | K |
| 5 | `test_abort_finish_shows_aborted_banner_variant` | S — map retention K; chip/banner words → **V** (`terminalVariant`/`bannerText`, incl. fault-outranks-abort + per-run one-shot) + W (binding) |
| 6 | `test_pause_toggle_emits_signal_only_while_enabled` | K (strip button, same guard) |
| 7 | `test_abort_button_emits_abort_requested` | K; the "Aborting" chip word → V/W |
| 8 | `test_abort_disabled_when_idle_rule` | K |
| 9 | `test_z_focus_start_emits_config_and_resets_curve` | K (config now assembled from VM form fields; defaults pinned equal) |
| 10 | `test_z_focus_done_sets_marker_and_label` | S — pyqtgraph marker K; Best-Z label → W (VM text already exists) |
| 11–14 | `test_apply_best_z_*` (4) | K (strip button; eligibility reads `vm.lastBestZ`) |
| 15 | `test_z_focus_mode_switch_toggles_edge_and_amp_frames` | W (QML form sections) |
| 16 | `test_z_focus_card_collapsed_by_default_with_header_controls` | W (kit CollapsibleCard) |
| 17 | `test_open_in_analysis_click_emits_path` | K |
| 18 | `test_zf_spin_suffixes_match_units` | W (QML SpinBox suffixes) |
| 19 | `test_open_in_analysis_noop_without_path` | K |
| 20 | `test_theme_switch_survives_with_data` | rewritten K′ — the hybrid theme fan-out test (QML mode sync + island pens + data survival) |
| 21 | `test_theme_switch_before_any_data_does_not_raise` | K′ |
| 22 | `test_abort_uses_shared_danger_language` | **K byte-identical** — same button instance, objectName `dangerBtn`, `state="danger"` |
| 23 | `test_no_graphics_effect_on_map_or_zfocus_plot` | K (islands survive; rule 3 unchanged) |

Tally: 15 K (+2 K′ rewritten), 4 W, 2 S (each K-part + W/V-part), 0 silently
dropped. Every W/V move states the old test name in the diff — nothing
retires without a named successor (the U1.2 discipline).

### 3.2 The safety wiring host — untouched, and why it stays green

`tests/test_scan_viewer_wiring.py` (S2 manifest) is **not in any U2 lock
list**. It stays green through every beat and across the flip because the
contract it pins is preserved structurally: the class import path
(`gui.scan_viewer_panel.ScanViewerPanel`), the five OUT signals, the slot
surface (`on_scan_started/on_progress/on_point_done/on_scan_finished/
on_scan_error/on_manual_pause/on_z_focus_pt/on_z_focus_done/
set_current_position/set_last_run_path`), and the pause/abort **button
instances** all survive — U2.5 re-parents, U2.7 re-homes the module, neither
re-implements. Its rule-8 detach/redock test doubles as the QQuickWidget
reparent proof at the flip. If any U2 diff would require editing this file,
the beat is mis-designed — stop and return to Adam.

### 3.3 New suites (bucket assignments via Kiroku at wave boundaries)

- `tests/test_qml_kit_surface.py`, `tests/test_qml_kit_components.py` — kit
  conformance (bucket D).
- `tests/test_scan_viewer_qml.py` — the panel QML-walker (bucket D→B): item
  lookup, binding assertions, focus-order walk (§4 R2), stale/terminal
  states. This is the seed of the U6 monkey QML-walker; keep its item-walking
  helper generic.
- `tests/test_qml_island_host.py`, `tests/test_qml_dead_zones.py` — geometry
  laws (bucket B).
- `tests/test_scan_viewer_panel_qml.py` — the K-class re-hosts (bucket B).
- `tests/test_shell_switch_scan_viewer.py` — the named standing-gate smoke.
- Offscreen tier note: offscreen runs cap at TOKEN (`gui/glass_env.py`), so
  offscreen suites assert FLAT/TOKEN invariants + geometry/band laws; SCENE
  pixels are verified in the windowed Kaya review (capture via
  `scripts/capture_panels.py`, artifacts to `artifacts_claude/`).

Test economy: implementing agents paste output tails (that IS verification);
one reconciliation run after U2.5 lands (three beats touch `gui/qml/kit/*`);
full suite only at the exit gate, on the bench.

---

## 4. Risk register

**R1 — island overlay repaint interaction (the real z-order risk).** No
native-window airspace exists in U2 (both islands are raster pyqtgraph;
QQuickWidget is texture-composited — sibling stacking is legal and
documented). The unmeasured part is repaint interference in ONE window: a
30 Hz island blitting above a 12 Hz-rebaking QML texture could trigger
full-window recomposition storms on the lab iGPU. *Mitigation:* U2.4 entry
micro-spike before any host code (floors: island ≥ 28 Hz, QML fps ≥ 55);
the kit law "nothing animates adjacent to a hole" is enforced by the
dead-zone walker. *Fallback (cheap, pre-designed):* interleaved-strips
layout — the panel becomes a QVBox of QQuickWidget strips and island widgets
with zero overlay; costs the frame-around-hole look, changes no VM/test
architecture. Decision point: spike day 0.

**R2 — focus chain across the QWidget/QML boundary.** The tab chain must
traverse: QML interactive Surfaces (`activeFocusOnTab`, luminous ring §4.1)
→ the QWidget command strip (QSS `outline-offset` ring — both shells share
the one outside-offset convention, so the seam is invisible) → island
toolbars → back into QML, in visual order. QQuickWidget is one widget-chain
stop; entering/exiting the scene needs explicit handling. *Mitigation:*
`IslandHost` owns the boundary — explicit `setTabOrder` chain over
{QQuickWidget, strip, islands} + a QML `FocusScope` per section; a dedicated
focus-walk test in `test_scan_viewer_qml.py` asserts every command button
and ≥1 QML interactive item is keyboard-reachable in order, offscreen.
Hazard focus (ruling 4) has no U2 instance (no hazard rung in this panel) —
noted so the walker doesn't fake-cover it.

**R3 — theme fan-out across two shells during the window.** Two faces × two
engines read one truth (`gui/style.py` → QSS and → Theme bridge). Drift mode:
classic repolish happens but `qml_theme.set_theme_mode` lags (or vice versa),
or island pens (pyqtgraph `axis_color`/`PLOT_OVERLAY`) miss the flip.
*Mitigation:* the hybrid host's `refresh_theme` does all three in one method
(QML mode, island pens, strip repolish) and registers with the existing
fan-out completeness test (`test_theme_fanout_completeness` auto-discovery);
K′ theme tests (§3.1) assert data survival + pen change under both faces;
`test_qml_theme_specular_sync.py` precedent extends to the new exposures.
The bridge beat landing first (entry dependency) is what makes this a
wiring problem, not a token-guessing problem.

**R4 — measurement-B failure / late surprise (run-active global calm).**
If the morning run fails or Kaya tunes thresholds down, the ratified fallback
is global calm: bake → 0 Hz app-wide whenever `facade.active` — which also
**moots ruling 7's ownership resolution** for calm purposes. Plan impact is
deliberately one switch (U2.1 calm-policy flag): panel-scoped freeze code
still ships (it is the ratified design), the policy default flips, the
stale-crop seam review (§5) becomes vacuous (no seam when the whole ground
is frozen), and the run-active ≤1.0× clamp is subsumed (0 Hz < 1.0×). No
beat is restructured; the gate line records which policy shipped.

**R5 — standing-law naming trap on the VM growth.** The abort-noted display
feed and `lastBestZ` must not trip `test_read_only_no_command_surface`
(attribute-name matcher includes `abort`/`arm`/…). Named in U2.3; Shiori
brief-check verifies the matcher's actual pattern before dispatch.

**R6 — two-shell drag inside one panel.** During the window, z-focus config
assembly exists twice (old face spinboxes / hybrid VM form). Accepted,
bounded: the duplication dies at U2.7 in either flip outcome (the classic
face can also read the VM form after the growth); listed in the gate line so
it cannot silently persist.

---

## 5. The [Kaya] pattern sign-off checklist (U2 exit)

What Kaya **sees** (windowed, lab laptop, sim mode — captures archived to
`artifacts_claude/`):

1. The hybrid ScanViewer at **FLAT → TOKEN → SCENE** (tier walk; same tones,
   ΔL* ≤ 1.0 — turning glass off changes nothing that anything *is*).
2. Living ground `subtle` and `full`, speed slider; then a **live sim scan**:
   panel-scoped calm behind the viewer, room keeps flowing at ≤ 1.0×
   (ruling 1), run chip + pulse (1200 ms law). **The stale-crop seam judged
   on rendered pixels** — the named open item (kit spec §7.2).
3. Mid-run **Abort** (same physical button as ever) → ABORTED banner variant;
   a fault-path run → FAULT variant, never green.
4. Z-focus: collapse/unfold spring, form → Find focus → live curve island →
   Apply-to-Planner staging.
5. Theme toggle live in **both shells**; detach → redock of the panel
   (detached copy calms whole).
6. Keyboard-only pass: tab traversal across QML ↔ strip ↔ islands, luminous
   ring outside-offset everywhere.
7. The numbers: measurement-B live thresholds (his morning ratification,
   restated), overlay-spike floors, the **distillation gate line** (net LOC,
   kit vs panel scope, explicit delete list).

What Kaya **approves** (each recorded in `docs/DECISIONS.md`):

- **A1 — the pattern:** panel-VM-island (hybrid host + hole-and-frame +
  command strip + VM lift + named smoke) as THE template for U3–U5;
  `docs/design/panel_vm_island_pattern.md` becomes citable law.
- **A2 — stale-crop seam:** accept, or order the neighbouring-wash fallback
  (kit spec §5.4) at re-measured cost.
- **A3 — the face-flip ruling** (§2 U2.7): classic ScanViewer face retires
  now vs retained-until-U6 (deferred-delete ledger).
- **A4 — gate-line accounting convention** (kit-platform vs panel-scope
  split) if Adam has not already ruled it (§7 Q2).

What is **not** on the table: safety carve-outs, never-migrates list, hazard
laws — PROTECTED, not re-opened by this gate.

---

## 6. Effort + critical path

| Beat | Size | Est. |
|---|---|---|
| overlay micro-spike | S (boxed) | 0.5 d, day 0, parallel |
| U2.1 Surface core | **L** | 2–3 d |
| U2.2 components | M | 1.5–2 d |
| U2.3 face + VM growth | M | 1–1.5 d |
| U2.4 island host | M | 1–1.5 d (post-spike; scaffold parallel to U2.2) |
| U2.5 command re-host (+ immediate Mary) | S/M | 1 d |
| U2.6 shell switch + smoke | S/M | 1 d |
| exit gate (bench + Mary batch + standup) | — | 0.5–1 d |
| U2.7 retirement + gate line + pattern doc | S | 0.5–1 d |

**Critical path:** U2.1 → U2.2 → U2.3 → U2.5 → U2.6 → gate → U2.7 ≈ **7–9
working days**; U2.4 runs off-path (spike day 0; host parallel to
U2.2/U2.3, joins before U2.5). The masterplan's M rating holds only because
U2.1's kit cost is platform cost — the gate line makes that split explicit.
Longest-lever risk: U2.1 (everything queues behind `Surface`); Adam should
dispatch it within hours of the morning gates passing.

---

## 7. Open questions (few, by design)

- **Q1 (Kaya, at sign-off — already scheduled as A3):** face-flip vs
  retained fallback. Architect's recommendation: **flip** — the tier ladder
  is the degradation story, two-shell drag is risk #5, and the hero slice
  should prove the full distillation loop including deletion; retention
  remains a legitimate ruling and is pre-costed (deferred ledger).
- **Q2 (Adam, one line, before U2.7):** confirm the ruling-8 accounting
  convention — whole-stage net PLUS the kit-platform / panel-scope split
  (§2 U2.7). Decline ⇒ report raw net only; the delete list is unchanged.
- **Q3 (Adam, at U2.3 dispatch):** the VM display-feed name for
  abort-noted state (R5) — brief must carry the exact standing-law matcher.

## Amendment log

| date | change | authority |
|---|---|---|
| 2026-07-15 | v1.0 plan on paper (U2 architect beat) | awaiting morning gates; no dispatch before they pass |
