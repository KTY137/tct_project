# U2.4 island-hosting decision — container-hosted QML with native-child islands (PAPER)

| | |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-15 |
| **Author** | U2.4 island-hosting architect (Fable, architecture-class beat) |
| **Status** | Decision on measured evidence + amended U2.4 beat design ON PAPER. Execution gated on the [K] items in §6 (isolated there; nothing else in this doc needs Kaya). |
| **Supersedes** | `docs/design/u2_hero_plan.md` §1 items 1–2 (the option-(a) *hosting mechanics* incl. the WindowContainer-rejection paragraph) and §2 U2.4 as written. Everything else in the hero plan stands — see §3.4 for exactly what survives. The hero-plan/masterplan text amendments are a separate doc chore AFTER [K1] (this file is this beat's only lock). |
| **Authority** | The masterplan's own revisit clause ("revisit only at Qt 6.10+ LTS with a bench spike") is ACTIVE: we run Qt/PySide 6.11.1 and the bench spikes exist. Exercising the clause per its own terms is following the ratified plan; the resulting wording amendment still gets Kaya's per-change nod ([K1]). Ratified thresholds (island ≥ 28 Hz, scene ≥ 55 fps — DECISIONS 2026-07-15) are **binding numbers, unchanged by this doc**. |
| **Evidence** | `artifacts_claude/island_overlay_spike_matrix_20260715T{121526,123629,124443,124802,125157}Z/` · `artifacts_claude/measurement_b_20260715T102648Z/` · harness `TCT_app/scripts/spikes/island_overlay_spike.py` |

---

## 1. What the measurements established (the refuted mechanism, stated as law)

All numbers: lab laptop (i7-10510U, Intel UHD, DPR 2.5, Windows 11 build 26200),
PySide6/Qt 6.11.1, windowed, quiet machine, 6 frost panes, bake 12 Hz, island
drive 30 Hz nominal, 2 passes per cell per run.

### 1.1 QQuickWidget cannot coexist with ANY sibling in its top-level

| cell | mechanism | scene fps | island feed Hz | CPU (1-core %) | verdict |
|---|---|---|---|---|---|
| m0_control | frost scene alone, no island | 59.99–60.09 | — | 22–27 | REFERENCE, every pass, every run |
| m0_overlay | raster sibling over QQuickWidget | 21.7–28.3 | 13–21 | 68–82 | FAIL |
| m1/m2/m1+m2 | opacity/damage-clip flags | 19.6–25.3 | 13–18 | 75–79 | FAIL |
| m3 | **half-area, NON-overlapping** sibling | 24.1–27.4 | 16–19 | 66–74 | FAIL — overlap is not required |
| m4 | island driven at 15/8 Hz | 20.0–24.5 | (by construction low) | 72–78 | FAIL — not rate-paced |
| m5 | QSG_RENDER_LOOP=basic | 18.1–21.1 | 16–17 | 70–74 | FAIL (worse) |
| m6 | **WA_NativeWindow island**, QQuickWidget stays | 22.6–23.1 | 13–16 | 79–81 | FAIL — a native surface does not rescue the QQuickWidget path |

Twenty-two failing passes, zero exceptions. The mechanism (per the harness
docstring, confirmed by m3+m4+m6): the mere **presence** of a sibling —
raster *or native*, overlapping or not, fast or slow — forces Qt to
CPU-composite the QQuickWidget's whole backing store per QML frame on this
build. It is a compositing-model fact of `QQuickWidget`-plus-sibling, **not a
tunable**. Two consequences beyond U2.4:

- **The hero plan's pre-designed R1 fallback (interleaved strips) is DEAD.**
  m3 is precisely that layout (QQuickWidget beside a non-overlapping island)
  and it fails. It must not be reached for later.
- **m6 kills "QQuickWidget face + everything else floats" as a pure option:**
  the command strip (which hosts **Abort**) would have to float in its own
  top-level too — a z-order-fragile floating safety control. Rejected outright
  (§2, option A-pure).

### 1.2 The two surviving mechanisms, both measured

**m7 — QQuickView + `QWidget.createWindowContainer` (QML on a native
swapchain) + WA_NativeWindow island, same top-level.** Six passes over three
runs converge tightly:

| run/pass | scene fps | island feed Hz | CPU % |
|---|---|---|---|
| 124443Z p1/p2 | 52.77 / 52.36 | 24.82 / 25.09 | 68.7 / 65.8 |
| 124802Z p1/p2 | 53.26 / 52.25 | 24.94 / 25.49 | 65.9 / 66.0 |
| 125157Z p1/p2 | 54.33 / 53.13 | 25.96 / 25.94 | 67.2 / 65.2 |

Stable near-miss: scene 1.2–5.0 % under the 55 floor, island 7.3–11.4 % under
the 28 floor, **CPU not saturated** (65–67 % of one core; the failing cells sat
at 75–82 %). Measured under a **harsher-than-shipped synthetic load** (§1.3).
Known hazard: deterministic segfault at process exit under a *naive* teardown
order; the disciplined order (feed → island → host → container,
`NativeContainerWindow.close()`, harness ~line 1121) was clean 7/7.

**Measurement B — island in its OWN top-level, QML unopposed, under REAL
acquisition** (sim scan + controller + HDF5 writer): island 30.24 Hz, QML
60.03 fps, DAQ CV 0.084 — all three ratified assertions PASS. The
separate-surface family is proven under production-class load on this exact
laptop.

### 1.3 The load honesty note (why m7's miss is not the shipped number)

The m7 cells ran: **full**-amplitude ground, 6 panes sampling, bake 12 Hz
(= the "full" setting), island hot at 30 Hz — simultaneously. The shipped
combinations differ (kit spec §5.4, ratified):

- **Ship default is `subtle`** → bake 6 Hz, lower wash amplitude.
- **During a run** (the only time the island is hot), the run-owning pane
  **calms**: its sampler stops, its wash amplitude eases to 0; the room flows
  at the ruling-1 clamp ≤ 1.0×; the shared bake continues at the setting's
  idle rate.
- The synthetic worst case (full flow + hot island, nothing calm) is **not a
  shipped run-state**. But the worst *legal* shipped run-state — user-set
  `full` + run → bake 12 Hz + hot island, minus one pane's sampler and
  amplitude — approaches it. Load-shaping is therefore real headroom but not
  a free pass: the representative cells must include the full-setting run
  (§4.1), and what counts as "representative" is Kaya's to ratify ([K2]).

The scene cost at ship-default subtle + panel-scoped calm is **UNMEASURED**.
It is carried as spike cells (§4.1), never assumed.

---

## 2. The decision space, weighed honestly

**A-pure — separate top-levels for everything non-QML (QQuickWidget face).**
Proven rates (measurement B). But m6 (§1.1) forces the command strip to float
as well: three frameless tool windows per ScanViewer (map, z-plot, strip),
geometry-tracked over holes, each with its own z-order/activation/minimize/
drag-lag story — multiplied over the 9 islands of U3–U5, inside QtAds docking.
The drag rubber-banding of a floating island during a panel move is exactly
the jank class Kaya's quality directive forbids, and a floating **Abort**
strip is a safety-UX regression. **Rejected as the primary.**

**B — m7 container + bounded pacing/optimization spike with hard go/no-go.**
One top-level: QtAds docking, detach/redock, alt-tab, minimize all inherit for
free; the strip stays an in-panel native child. Near-miss is 1.2–5 % on scene
with CPU unsaturated, under a harsher-than-shipped load; the residual gap is
plausibly event-loop pacing (§4.1 — note the feed timer is *already*
`PreciseTimer`, harness line 725, so the space is scheduling/coalescing/paint
cost, not timer type). Known hazards (teardown order, focus chain, airspace)
are all nameable, testable, and bounded. **Primary path.**

**C — load-shaping within the ratified spec.** Cannot rescue the sibling path
(m3/m4: the collapse is load-independent) — so C is **not an independent
option**; it is the representative-load leg of B's gate plus one contingent
lever (run-active bake clamp, [K3]).

**D — combination fallback: container face + native strip in-window, islands
as separate top-levels (the measurement-B mechanism), geometry-tracked to the
holes.** Keeps the safety strip in-window (no floating Abort), floats only the
islands whose rates are proven at 30 Hz. Unmeasured in exactly this
composition → pre-measured as a cell in the same spike (§4.1 cell F) so
falling back is a bounded step, not a redesign. **The fallback.**

### The recommendation

**B, with C folded into its gate and D as the pre-measured fallback.**

1. **Decided now, on 22 failing passes:** the QML face's hosting vehicle is
   `QQuickView` + `createWindowContainer`; QQuickWidget is retired from any
   top-level that contains islands or the command strip. Every surviving path
   (B *and* D) requires this, so the container mechanism, its teardown law,
   and the native-child airspace law are **unconditional** U2.4 requirements.
2. **Gated on U2.4a, never assumed:** island placement — in-window native
   child (primary) vs floating top-level (fallback D) — is decided by the
   representative-load + pacing spike against the **unchanged ratified
   floors**, with the fallback trigger stated in §4.1.

---

## 3. The decision, stated precisely

### 3.1 Hosting mechanics (amends hero-plan §1 items 1–2)

1. **The panel stays a QWidget** — same class name, same signal/slot surface,
   same VM boundary (unchanged from the hero plan).
2. Inside it, **one `QQuickView`** renders the whole QML face
   (`SizeRootObjectToView`), embedded via `QWidget.createWindowContainer`.
   The container widget is an ordinary child of the panel — reparentable,
   dockable, part of the widget tree. QML renders through a real native
   swapchain and never touches the backing-store composite path.
3. **Everything stacked above the QML face is a native child**
   (`WA_NativeWindow`, `winId()` forced at registration): the two pyqtgraph
   islands AND the `ScanViewerCommandStrip`. Native children render above the
   container by construction (airspace) — **legal here because the kit's
   dead-zone law already forbids anything above islands**; the strip's rects
   join the same dead-zone registry.
4. **Coordinate mapping is unchanged:** `SizeRootObjectToView` on QQuickView
   gives scene coordinates == container-local logical coordinates, exactly as
   the QQuickWidget mapping did — hole rects published by objectName offset by
   the container's position in the panel; no DPR arithmetic. **U2.3's hole
   publication needs zero changes** (it is hosting-agnostic by design).
5. **The teardown law (hard design requirement, with a test):** `IslandHost`
   owns a single `shutdown()` — stop feeds → close/release islands (and
   strip) → close the host QQuickView/container — wired into the panel's
   closeEvent and the app quit path. The naive destruction order segfaults
   deterministically on this build; the disciplined order was clean 7/7.
   No caller may tear these objects down in any other order.
6. **App-level attribute:** `Qt.AA_DontCreateNativeWidgetSiblings` is set at
   application start (composition root). Without it, Qt may propagate
   nativeness to arbitrary siblings in the same window — in the real app that
   window also hosts the chrome QQuickWidget and every classic panel, and an
   involuntarily-native sibling next to the chrome QQuickWidget is the m6
   failure. Pinning the attribute makes native-child scope explicit and ours.

### 3.2 What this dissolves and what it inherits

The masterplan's original WindowContainer rejection had two grounds:
*airspace* (native box above the widget hierarchy) and *hosts windows, not
widget trees*. The first is dissolved by the kit's own dead-zone law — nothing
is ever allowed above an island anyway, and the strip joins the registry. The
second is priced and accepted: the container **is** a QWidget in the tree
(reparent/detach/redock live on — verified by test, §4.2), and the QML content
tree is unaffected. What the container path *inherits* is the teardown hazard
(law §3.1.5) and the focus-forwarding seam (§4.2, verified not assumed).

### 3.3 Forward consequences (named now, not decided now)

- **U6 shell swap rides the same law.** A QML chrome as QQuickWidget
  coexisting with raster/native panels in the main window is the measured
  dead end at U6 scale. The U6 line in the masterplan should be annotated to
  "container-hosted chrome or equivalent measured mechanism" at the next
  masterplan pass (doc chore, after [K1]; not this beat's lock).
- **U5 GL island (Motor) and U4 camera QLabel** ride the same native-child
  law. A `QOpenGLWidget` is itself backing-store-composited — under the
  container it must be native (or a QWindow-based GL surface). Carried as a
  named spike placeholder at U5 entry (`gl_island_native_child_spike`),
  never assumed.
- **Chrome + panel in one window under TCT_SHELL=qml** (U2.6): the current
  chrome QQuickWidget will coexist with the ScanViewer's natives in the main
  window. Low-motion chrome pays the per-QML-frame composite rarely, but this
  is exactly the class of "worked in the spike, died in the app" — carried as
  spike cell G (§4.1), measured before U2.6 lands.

### 3.4 What survives untouched from the ratified plan

QWidget panel tree and class/signal surface; islands stay raster pyqtgraph
QWidgets (never-migrates); Abort/strip re-parented never re-implemented
(U2.5 unchanged in substance — one surface-policy note, §5); hole-and-frame
FigureCard contract (kit spec §1.4/§3); dead-zone law (extended, §5);
panel-scoped calm + ruling-1 clamp + ruling-7 ownership; the VM boundary; the
two-shell window and U2.6/U2.7 structure; `tests/test_scan_viewer_wiring.py`
byte-untouched; all ratified thresholds.

---

## 4. Amended U2.4 beat design

U2.4 splits into **U2.4a (spike, throwaway)** and **U2.4b (host build)**.
U2.4b's scaffold may start immediately (the host API is
placement-agnostic); its *island-placement* wiring lands only after U2.4a's
verdict.

### U2.4a — representative-load + pacing spike (throwaway, 1-day box)

- **Owner/model:** Noah, opus (measurement + Qt render-loop mechanics).
  Windowed runs on the lab laptop, quiet-machine protocol, artifacts to
  `artifacts_claude/`.
- **Vehicle:** extend `TCT_app/scripts/spikes/island_overlay_spike.py`
  (config-driven cells already exist). New capabilities: per-pane calm toggle
  (sampler stop + amplitude 0 — the §5.4 mechanism), subtle/full parameter
  set (6/12 Hz bake + amplitude), a dormant native button-row stand-in for
  the strip, a second (cold) island stand-in for the z-plot, a floating-tool-
  window island mode (for cell F), and an app-shaped cell (G).
- **Cells (all with container-hosted QML + native strip stand-in present —
  measure the shipped composition, not a simplification):**
  - **A `rep_idle_subtle`** — subtle, islands cold. Expected ≈60/—.
  - **B `rep_idle_full`** — full, islands cold. The worst shipped *idle* state.
  - **C `rep_run_subtle`** — subtle + run-state calm (own pane calmed, clamp
    on) + map island hot 30 Hz + z-plot cold. The shipped default run-state.
  - **D `rep_run_full`** — full + run-state calm + hot island. The worst
    *legal* shipped run-state.
  - **E pacing variants on C/D only if they miss** — three named levers,
    bounded: (i) island update coalescing/batching (feed ticks decouple from
    repaint; latest-wins compression of paint work on the GUI thread),
    (ii) render-paced feed (drive island data pushes from the QQuickView's
    `frameSwapped`/`afterFrameEnd` metronome instead of a free-running timer),
    (iii) event/priority tuning (posted-event priorities,
    `AA_CompressHighFrequencyEvents`, render-loop env pin verification).
    The feed timer is already `PreciseTimer` — timer *type* is not the lever.
  - **F `fallback_float`** — container face + native strip in-window, map
    island in its own frameless `Qt.Tool` top-level positioned at the hole
    rect, hot 30 Hz. Pre-measures fallback D so its adoption (if triggered)
    is measured, not assumed.
  - **G `app_shaped`** — cell C plus a second, low-motion QQuickWidget chrome
    stand-in in the same top-level (today's TCT_QML_SHELL chrome situation).
    Diagnostic for §3.3's U2.6 risk; gates U2.6, not U2.4.
- **Pass bar (the ratified floors, unchanged):** scene ≥ 55 fps in A–D;
  island feed ≥ 28 Hz in C and D (the hot cells). Two passes per cell,
  quiet-rerun protocol (±10 % near-floor ⇒ rerun on a quiet machine), same
  as every prior matrix.
- **Go/no-go (hard):**
  - C **and** D clear both floors (with or without E levers) → **primary
    path confirmed**; U2.4b wires in-window native-child placement.
  - C passes, D misses, and only D → the [K3] bake-clamp lever goes to Kaya
    with the numbers; if declined, treat as fallback trigger.
  - C misses after all three E levers within the box → **fallback fires**:
    U2.4b wires cell-F placement (floating islands, strip stays in-window),
    provided F cleared its floors. F failing too → STOP; back to Adam/Kaya
    with the full matrix — no further improvisation inside the beat.
  - Box: 1 day. +1 day extension only if a specific, named fix is identified
    mid-box and Adam approves it explicitly.
- **Explicitly out of scope for the spike:** `QSG_NO_VSYNC` and other
  non-shippable knobs may be run as *diagnostic* cells to separate pacing
  from throughput, but can never satisfy the pass bar.
- **Locks:** `scripts/spikes/island_overlay_spike.py` (throwaway),
  `artifacts_claude/` output dirs.
- **Exit:** matrix table + verdict in the spike report JSON; numbers quoted
  in the ledger; the go/no-go branch taken is recorded in this file's
  amendment log.

### U2.4b — `IslandHost` on the container mechanism

- **Owner/model:** Noah, **opus** (widget/window lifecycle, teardown,
  focus — his real bug class per the standing override).
- **Builds:** `gui/qml_island_host.py` — `IslandHost`:
  1. Owns the `QQuickView` + container (applies the same RHI pin as
     `gui/qml_shell.py`; one pin, one place — read it, don't duplicate it).
  2. Looks up published hole rects by objectName (U2.3 contract, unchanged);
     positions registered widgets (`setGeometry`), tracks geometry via the
     batched 0-timer as planned.
  3. **Applies surface policy at registration** — the host, not the client,
     sets `WA_NativeWindow` + forces `winId()` on every registered widget
     (islands, strip). Clients stay plain QWidgets (§8: U2.5 must-not).
  4. Syncs visibility (z-focus island hides while its CollapsibleCard is
     collapsed; unfold-then-appear ≤ 100 ms crossfade law unchanged).
  5. Registers every hole AND the strip rect in the dead-zone registry.
  6. **Owns `shutdown()`** — the §3.1.5 teardown law, wired into panel
     closeEvent and `aboutToQuit`. Idempotent; ordering asserted in debug.
  7. Placement strategy is one internal seam (`_place_in_window` /
     `_place_floating`) so a U2.4a fallback verdict changes one code path,
     not the API. Only the verdict's branch ships; the other is deleted
     (distillation, ruling 8 — no speculative dual mechanism in the tree).
- **Tests (locks):**
  - `tests/test_qml_island_host.py` — positioner (resize, theme flip,
    hide/show, detach/redock), registration policy (registered widgets are
    native; strip included), **teardown-order suite**: (a) disciplined
    `shutdown()` in a subprocess exits 0 (the crash-shaped proof, subprocess-
    isolated so a regression can never take down the test run); (b) ordering
    assertions on shutdown(); (c) double-shutdown/idempotency; (d) shutdown
    during an active feed.
  - `tests/test_qml_dead_zones.py` — as planned (all Surfaces × all holes ×
    {sample, shadow, halo}, ≥ 12 px), **plus** the strip rect as a dead zone
    and the "natives-only above the container" structural assertion.
  - Focus-walk additions to `tests/test_scan_viewer_qml.py` stay with U2.3's
    suite as planned, but U2.4b contributes the container-boundary cases:
    tab into the container (forwarding to the QML scene), tab out of the
    last QML item into the strip, strip → island toolbar → back to QML;
    Qt's container focus-forwarding is a known-warty seam — **verified,
    not assumed**.
  - Detach/redock smoke: the hybrid panel torn into a floating top-level and
    redocked **through the QtAds mechanics the app actually uses** (container
    reparent survives; bindings survive; `shutdown()` NOT triggered by a
    reparent). Detached copy calms whole (ruling 7) — unchanged.
- **Locks:** `gui/qml_island_host.py` (new), `tests/test_qml_island_host.py`
  (new), `tests/test_qml_dead_zones.py` (new).
- **Exit:** U2.4a verdict recorded and above floors on the shipped branch;
  all suites green offscreen (offscreen runs use the disciplined teardown —
  the segfault class is exactly why); dead-zone walker green;
  **immediate Mary review** — concurrency/lifecycle class, safety-adjacent
  at landing (teardown segfault class; native-window lifecycle; the strip
  that hosts Abort rides this host; app-exit path).
- **Offscreen caveat (stated, not hidden):** rate floors are windowed-only
  facts; offscreen tests prove mechanics (construction, geometry, teardown,
  focus), never fps. The windowed numbers live in U2.4a's artifacts and the
  Kaya sign-off.

### Effort delta vs the hero plan

U2.4a = the old day-0 micro-spike grown to 1 day (it now carries the gate).
U2.4b ≈ unchanged (1–1.5 d) + 0.5 d for the teardown/focus test surface.
Critical path impact: U2.4 stays off-path (parallel to U2.2/U2.3, joins
before U2.5) — unchanged from the hero plan.

---

## 5. New/extended design laws (kit + panel level)

1. **Teardown law** (§3.1.5) — hard requirement, tested, Mary-reviewed.
2. **Airspace/native-child law** — extension of the dead-zone law: in a
   container-hosted panel, *only* IslandHost-registered native children may
   exist above the QML face; the registry asserts it. The strip's rect is a
   dead zone for {sample, shadow, halo} like any island hole.
3. **Surface policy is the host's** — no panel/strip/island code sets
   `WA_NativeWindow` on itself; registration is the single site (keeps U2.5
   and every U3–U5 panel byte-free of hosting knowledge).
4. **`AA_DontCreateNativeWidgetSiblings`** set once at the composition root
   (lands with U2.4b's first consumer wiring or U2.6, whichever constructs
   the container first — implementer confirms placement with Adam).
5. **U2.5 surface note (informational, no U2.5 redesign):** the strip remains
   a plain QWidget built exactly as planned; QSS theming and the outside-
   offset focus ring are unaffected by nativeness. The only behavioral
   difference: the strip renders on its own HWND — the windowed Kaya
   checklist gains a seam check (§6, [K5]).

Popups (QComboBox, tooltips, menus) and the QtDangerGate modal are separate
top-level windows and stack above native children by OS compositing — but
**modal-above-island is verified in the windowed review ([K5]), not assumed**,
because it is safety-relevant (the gate must never appear under an island).

---

## 6. [Kaya] items — isolated, everything else in this doc is not his to carry

- **[K1] Hosting-mechanism amendment nod.** The masterplan's revisit clause
  is exercised on its own stated terms (Qt 6.11.1 + bench spikes): option-(a)
  hosting mechanics amend from "QQuickWidget + raster siblings" to
  "QQuickView-in-container + native children". All safety sub-clauses,
  never-migrates items, and the QWidget-tree/island/strip guarantees are
  untouched (§3.4). One-line confirmation; recommended to ride the same
  conversation as [K2]. (Design-domain and arguably within Adam's delegation,
  but the amended sentence lives in a Kaya-approved plan text — his nod keeps
  the governance clean.)
- **[K2] Representative-load ratification (BLOCKING for the U2.4a gate).**
  Ratify the §4.1 cell family A–D as *the* load under which the (unchanged)
  floors gate U2.4: ship-default subtle and user-set full, idle and run-state
  with panel-scoped calm active, hot island 30 Hz in run cells, strip + cold
  z-plot present. Recommendation: all four cells gate. The spike may be
  *built and run* before this ratification; its verdict *binds* only after.
- **[K3] Contingent lever — run-active bake clamp.** If (and only if) cell D
  alone misses: clamp the shared bake to 6 Hz whenever a run is active
  (analogous to ruling 1's speed clamp; strengthens calm during runs, never
  reverses it). Amends kit spec §5.4's "bake keeps running at the idle rate
  (6/12 Hz per setting)" — a Kaya-signed section, so his call, with the
  numbers on the table. Not requested pre-emptively.
- **[K4] Contingent threshold re-rating — NOT recommended.** Only if the
  spike converges ≤ 2 % under a floor with CPU headroom and visually clean
  pixels would a re-rating request be admissible; default posture is floors
  unchanged and the fallback fires. Listed only because thresholds are his
  alone to change.
- **[K5] Windowed sign-off checklist additions** (hero plan §5 grows three
  items): (i) move/resize/dock-drag flicker of native children (the spike's
  static geometry read cannot see it); (ii) QtDangerGate modal renders above
  islands and strip; (iii) the strip's visual seam on its own surface
  (theming/focus ring) is invisible. Plus the multi-monitor/DPR-change
  behavior of native children if he docks to an external display.

---

## 7. Named unknowns carried as spikes/tests — nothing rides as an assumption

| # | unknown | carrier | pass bar |
|---|---|---|---|
| 1 | Scene/island rates at *shipped* loads (subtle/full × idle/run-calm) | U2.4a cells A–D | ratified floors, 2 passes, quiet protocol |
| 2 | Pacing headroom (is the m7 gap scheduling, not throughput?) | U2.4a cell E levers | same floors; levers bounded to the three named |
| 3 | Fallback-D composition (container + native strip + floating island) | U2.4a cell F | same floors |
| 4 | Chrome QQuickWidget coexisting with natives in one window (U2.6 risk) | U2.4a cell G | diagnostic; gates U2.6, reported either way |
| 5 | Container teardown on the *windows* QPA in the app lifecycle | U2.4b teardown suite + windowed spike exit codes | subprocess exit 0 with disciplined order, every run |
| 6 | Container focus forwarding (in/out of the QML scene, strip, toolbars) | U2.4b focus-walk cases | every stop reachable in visual order, offscreen |
| 7 | Container reparent through QtAds detach/redock | U2.4b detach smoke | bindings + rendering survive; no shutdown triggered |
| 8 | Native-child flicker on move/resize/dock-drag; modal-above-island | [K5] operator eyeball (windowed) | Kaya's eye; no jank ships |
| 9 | GL island (U5) / camera QLabel (U4) as native children | named U5/U4-entry spike placeholders | defined at those beats' entry |

---

## 8. What U2.3 and U2.5 must NOT do meanwhile (in-flight guardrails)

**U2.3 (face + VM, in flight — its files are not locked by this beat):**
- Keep hole publication objectName-based in root-item scene coordinates —
  no hosting imports, no QQuickWidget/QQuickView references in QML or VM,
  no coordinate math that assumes a hosting vehicle.
- Do not consume any IslandHost API yet; do not add anchors/parents for
  island content into the QML tree (the kit draws frames only).
- No `Screen`/DPR compensation in the face — the mapping stays 1:1 logical.

**U2.5 (command strip):**
- Build the strip as a plain QWidget; **never** set `WA_NativeWindow`,
  call `winId()`, or add raise_()/stackUnder z-order logic — surface policy
  is the host's at registration (§5.3).
- Do not assume the strip can overlay the QML face without going through
  IslandHost registration (raster-over-container renders *below* — airspace).
- No new lifecycle hooks: the strip must tolerate being closed by
  `IslandHost.shutdown()` order without owning any teardown of its own.

**Everyone:** the hero-plan §1 / masterplan §UI option-(a) *text* stays as-is
until [K1]; the amendment is a queued doc chore, not an inline edit by any
implementing beat.

---

## 9. External research asks (for Adam to dispatch to Prometheus — optional, parallel, non-blocking)

1. **QQuickWidget + sibling compositing:** known QTBUGs / Qt 6.10–6.12
   changelogs for backing-store recomposition with (native or raster)
   siblings — confirms "not a tunable" and whether a Qt upgrade ever changes
   the calculus (feeds the U6 annotation, §3.3).
2. **createWindowContainer prior art on Windows:** focus-forwarding
   limitations, reparent behavior, and teardown-order crash reports on
   Qt 6.11/PySide6 — sharpens U2.4b's focus cases and teardown test design.
3. **GUI-thread pacing on Windows for Qt Quick's threaded render loop:**
   documented behavior of the sync phase vs GUI-thread paint bursts,
   `AA_CompressHighFrequencyEvents`, posted-event priorities, and any
   render-loop pacing env knobs in 6.11 — feeds U2.4a's E-lever definitions.

---

## Amendment log

| date | change | authority |
|---|---|---|
| 2026-07-15 | v1.0 — decision on the five committed spike matrices + measurement B; container hosting adopted unconditionally; island placement gated on U2.4a; [K1]–[K5] isolated | U2.4 architect beat (Fable); masterplan revisit clause exercised on its own terms; thresholds untouched |
