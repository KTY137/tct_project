# QML-chrome + pyqtgraph-plots hybrid — architecture assessment

- **Date:** 2026-07-11
- **Question (from Adam/Kaya):** Before writing production QML, stress-test the concrete
  architecture for a hybrid **QML chrome + pyqtgraph real-time plots** frontend. What is the
  robust composition on Windows/D3D11, where does the QML/QWidget seam fall, does detach
  survive a mixed boundary, how do we single-source theme tokens, what are the top risks,
  and is the spike's first vertical slice the right one?
- **Addendum (Kaya, same brief):** (1) search external prior art for the "fast numpy → screen
  without blocking the UI" problem — RemoteGraphicsView, VisPy, custom QSG-from-numpy,
  why QtCharts/QtGraphs are slow, peak-preserving decimation, DAQ-process→UI shared memory —
  and answer honestly whether anything **beats or matches pyqtgraph's numpy-direct latency
  AND composites under QML material** (§8). (2) Treat the **three-layer separation
  (UI / fast Python backend / drivers), compute never blocks the UI thread** as an enforced
  law: how to document it, how to enforce it (test/static), and how the QML view-model seam
  makes it structural (§9).
- **Stack / versions:** PySide6 **6.11.1**, Qt runtime 6.11.x, CPython **3.10 (64-bit)**,
  numpy **<2** (load-bearing pin — PySpin wheel; nothing here bumps it), Windows 11,
  RHI default backend on Windows = **Direct3D 11**. pyqtgraph raster (QPainter) for 2D;
  `pyqtgraph.opengl.GLViewWidget` (OpenGL) for the 3D stage view.
- **Confidence:** official docs (Qt doc pages + official Qt engineering blog) for all
  load-bearing composition facts; engineering judgment (clearly marked) for the
  recommendations built on top of them.

---

## TL;DR verdict — GO, with three hard caveats

The hybrid is **sound and the spike's headline route is correct**: a **QWidget tree with
`QQuickWidget` islands for chrome, and pyqtgraph plots as ordinary sibling QWidgets** (spike
option **a**). Option (b) — a QML-root window with pyqtgraph punched in via
`createWindowContainer` — is **not viable**, because **embedding a QWidget inside a QML scene
is not supported by Qt**; the supported direction is only QML-into-QWidget. That single fact
decides the composition.

But the spike validated the *logic* headless (software renderer, offscreen). Three things it
could **not** exercise, each of which must gate slice 1 on a **real GPU display**:

1. **The `GLViewWidget` / QQuickWidget rendering-API collision** (new finding, see §6). The
   Motor Stage 3D view is an OpenGL widget. Qt requires *every* accelerated widget in one
   top-level window to use the *same* RHI backend. Chrome QQuickWidget defaults to D3D11 on
   Windows; the GL stage view is OpenGL → mismatch → "bad things will happen" (Qt's words).
2. **Detach destroys and recreates the QQuickWidget's render context** every time (documented
   behavior), which is exactly where historical "goes blank/black after reparent" bugs live.
   The spike proved the *QObject* survives; it did not prove the *GPU context* re-inits cleanly.
3. **The frosted-glass material and HiDPI/multi-monitor behavior** only render on a real GPU.

None is a NO-GO; all are "validate on hardware before sinking weeks."

---

## 1. Composition pattern — QWidget tree + QQuickWidget islands (option a). Confirmed.

**Recommended:** keep `TCTMainWindow` a `QMainWindow` with a QWidget central tree. Chrome
(rail, tab strip, cards, tiles, buttons) becomes **`QQuickWidget` islands**; every pyqtgraph
plot / camera image / GL stage view stays an **ordinary sibling QWidget**.

Why (a) and not (b):

- **You cannot put a QWidget inside a QML scene.** *"Embedding a QWidget into QML is not
  supported; it is only supported the other way round"* (Qt blog / forum). So there is no
  clean way to host a pyqtgraph `PlotWidget` inside a QML-root window. `createWindowContainer`
  goes the *opposite* direction (a QWindow into a widget tree) and would make the plot a
  **native child window**: it *"renders as an opaque box on top of the QWidget hierarchy,"*
  breaking clipping, overlap, rounded corners and z-order. `QQuickPaintedItem` is *"the worst
  of both worlds"* (KDAB). All roads back to (a).
- **`QQuickWidget` is a true QWidget** with **no stacking-order restriction** — *"the
  restrictions on stacking order do not apply, making QQuickWidget the more flexible
  alternative, behaving more like an ordinary widget"* (Qt docs). It composites via an
  offscreen texture, so it clips/stacks with siblings and, crucially, is reparentable — which
  is what makes detach keep working.
- **Windows/D3D11:** since Qt 6.4 `QQuickWidget` *"drops the OpenGL requirement"* and runs on
  the platform default (D3D11 on Windows) via a **mini-compositor** that textures the QQuick
  content together with the QPainter-rendered widgets. This is the modern, supported path and
  needs **zero new dependencies** (env spike confirms QtQuick/Controls/Effects already ship in
  the 6.11.1 venv).

**Where (a) bites (and the mitigations):**

- **Extra render pass / no threaded render loop.** *"QQuickWidget involves at least one
  additional render pass targeting an offscreen color buffer … followed by drawing a texture
  quad"* and *"disables the threaded render loop on all platforms."* Consequence: QML
  animations run on the **GUI thread**. Fine for chrome (breathing/spin dots), but keep QML
  animation light and never put a hot 60 Hz plot inside a QQuickWidget — which is exactly the
  spike's rule, and it holds. pyqtgraph plots are separate raster QWidgets, unaffected.
- **One RHI backend per window.** *"All the widgets within the same window must use the same
  rendering API … When there is disagreement between the widgets, bad things will happen."*
  This is the §6 landmine — see below.

---

## 2. Detach across a mixed boundary — holds, with a real GPU-context caveat.

**Verdict: the pattern holds for mixed tabs.** `DetachableTabWidget` reparents a QWidget page
into a floating `_DetachedWindow` (`setCentralWidget` + `content.show()`) and back. A
QQuickWidget-backed panel is a first-class QWidget, so it tears off and redocks with **zero
changes** to `detachable_tabs.py` — the spike proved 11/11, same `QObject` preserved, state
intact. Mixing QML-chrome panels and pyqtgraph-heavy panels in the same tab widget is fine;
each page is an independent QWidget.

**The caveat the spike could not test (headless software renderer):** per Qt docs, a
QQuickWidget's *"OpenGL context is destroyed … when the widget gets reparented into another
top-level widget's child hierarchy."* **Detach is exactly that reparent.** So every
detach/redock **tears down and rebuilds the QQuickWidget's GPU render resources**. This is
the precise code path where Qt's well-known "QQuickWidget blank/black until a forced repaint
after reparent" reports cluster. On the offscreen software backend this is a no-op, which is
why the spike passed — but it says nothing about the D3D11/OpenGL reality.

Mitigations / validation:
- **Re-verify detach on a real GPU** for (i) a QML-chrome panel and (ii) the GL stage panel,
  docked→float→drag to a second monitor→redock. Watch for a blank first frame; if it appears,
  an explicit `update()`/`repaint()` nudge after reparent (or toggling visibility) is the
  standard fix.
- **Multi-monitor / per-monitor DPI:** dragging a detached window to a different-DPR monitor
  triggers a resize + re-render *on top of* the reparent context rebuild — the riskiest single
  path. pyqtgraph raster also re-rasterizes on DPR change. Must be checked on real hardware.
- Detached windows stay plain `QMainWindow` (as today). They can gain their own small QML
  title chrome later, but that is optional and out of slice 1.

---

## 3. Token single-source-of-truth — a runtime `Theme` singleton fed from `style.py`. Do NOT codegen QML.

**Recommendation:** expose one Python **`Theme` QObject** that reads `style.py`'s `LIGHT`/`DARK`
dicts and publishes each token as a Qt property, registered as a **QML singleton**. QML does
`import Tct; color: Theme.accent`. On theme toggle the object swaps the active dict and emits a
`changed()` NOTIFY; QML property bindings re-evaluate automatically → **live theme switch, zero
copies, no flicker** (bind, don't poll). This is the exact analogue of what `apply_theme()`
already does for QSS, and it keeps **`style.py` the single source of truth**.

- **Do not generate a `Tokens.qml`/`Theme.qml` from `style.py` at build time.** That creates a
  second file to keep in sync and a stale-artifact risk — the "drift-prone two-system copy" to
  avoid. Single-source the **values** (style.py), not a generated stylesheet.
- **Why a singleton, not `setContextProperty`:** context properties are discouraged — they
  *"magically inject state,"* are invisible to qmllint/qmlsc, and hurt reusability/testability
  (Qt docs + Raymii). A registered singleton is reusable and tooling-visible. (The qmlsc
  argument is weaker in PySide — you don't compile QML to C++ — but the reusability/testability
  win stands.) `qmlRegisterSingletonInstance` works but has the "one instance per engine"
  wart; Qt 6.12's `setExternalSingletonInstance` is the cleanest but **is not in our 6.11.1**,
  so on 6.11 use the `@QmlElement`/`QML_SINGLETON` declarative decorators on the Python class
  (tooling-friendly), or a plain registered singleton instance if a Python-constructed object
  is required.
- **Inherent residue (accept it):** a hybrid *always* has two style consumers — the QSS string
  for remaining QWidgets, and the QML `Theme` singleton. That is unavoidable while both stacks
  coexist. Single-sourcing the token **values** in `style.py` is the mitigation; the two
  *consumers* are fine as long as neither hardcodes a hex. The existing "no inline GUI hex
  outside `gui/style.py`" rule should extend to "no inline hex in QML either — read `Theme`."

Note `style.py` already models the token structure a design system wants (global scales →
per-theme `LIGHT`/`DARK` alias dicts → component roles), and it deliberately keeps `PLOT_BG`/
`PLOT_FG`/plot grid fixed across themes. The `Theme` singleton should mirror that: expose the
per-theme tokens as NOTIFY-able properties and the fixed plot tokens as constants.

---

## 4. The clean seam — precise line, and the tab-bar subtlety.

**QML (chrome, in `QQuickWidget` islands):** outer frame + ambient background, the frosted rail
(brand, device dots, status pills), the **pill tab *strip* (view only — see below)**, card
surfaces, metric tiles, buttons, segmented controls, chips, and — later, incrementally —
non-hot-path control forms.

**QWidget (kept as-is):** every pyqtgraph plot (scope trace, scan-map `ImageView`, reference
monitor, IV sweep, analysis `ImageView`), the **camera image** (`QImage`→`QPixmap`→`QLabel`,
raster — safe on any RHI), the **3D stage `GLViewWidget`** (OpenGL — see §6), and — decisively —
the **`DetachableTabWidget` itself plus the tab *pages*/stack**, because detach reparents
QWidget pages between top-level `QMainWindow`s. That engine stays QWidget.

**The tab-bar subtlety (important):** the artifact wants a QML pill-tab shelf, but the *real*
tab+detach engine is `DetachableTabWidget` (a `QTabWidget` subclass) and it must stay. Do **not**
let QML "own" the tabs — QML and the widget would fight over current-index and page ownership,
and you'd lose the proven detach/persistence/tests. Instead:

> **QML renders the pill strip as a *view*; `DetachableTabWidget` remains the *model/engine*.**
> Hide the native `QTabBar`, keep the `QStackedWidget` of pages. A thin adapter binds
> `Theme`/current-index both ways (`currentChanged` → highlight the QML pill;
> QML pill click → `setCurrentIndex`; QML detach button → `DetachableTabWidget.detach(i)`).

This gets the QML look **and** preserves the hard-constraint contract byte-for-byte.

**Incremental vs all-or-nothing:**
- **Panel bodies are cleanly incremental.** Because each tab page is an independent QWidget, one
  panel's body can become QML (a `QQuickWidget`) while every other panel stays QWidget, and
  detach still works. This matches the audit's Track-B per-panel ordering. Note: a QML panel is
  added to the tabs **directly** (a `QQuickWidget`), not wrapped in the `_scrollable()`
  `QScrollArea` the current panels use — QML scrolls itself via `Flickable`.
- **The shell chrome is ~atomic.** A half-QML rail looks worse than none, so the rail + tab
  strip land together as one slice.
- **One-time, whole-window cost on the *first* QML island.** A pure-QWidget window never spins
  up the RHI/mini-compositor; the moment the first `QQuickWidget` appears, the entire top-level
  flips to 3D-composited and the §6 backend question activates. Budget that risk into slice 1,
  not slice 4.

---

## 5. Prior art & top risks (each with a mitigation)

Known-good pattern: "Widgets app with Qt Quick islands via `QQuickWidget`" is *the* Qt- and
KDAB-endorsed hybrid for a primarily-Widgets app — exactly our situation. Known pain concentrates
in five places:

| # | Risk | Why it hurts here | Mitigation |
|---|------|-------------------|------------|
| R1 | **Rendering-API collision** (`GLViewWidget` OpenGL vs QQuickWidget D3D11 in one window) | Motor Stage 3D view + QML chrome share the main window; Qt forbids mixed RHI per window | **Pin the whole app RHI to OpenGL** at startup (`QQuickWindow.setGraphicsApi(OpenGL)`); pyqtgraph 2D is raster (unaffected), MultiEffect glass works on OpenGL. Validate on real GPU. (§6) |
| R2 | **Detach = GPU context destroy/recreate** | Every tear-off/redock rebuilds the QQuickWidget render resources; historical blank-frame bugs live here | Re-verify detach on a **real display** (incl. 2nd monitor); if a blank first frame appears, `update()`/visibility-toggle nudge after reparent |
| R3 | **Two style systems drift** (QSS + QML) | A hex changed in one place, not the other | `Theme` singleton fed from `style.py`; forbid inline hex in QML; single-source values, not stylesheets (§3) |
| R4 | **Focus / HiDPI boundary friction** | Tabbing from a QWidget into a QML scene and back; per-monitor DPI on detach; QML manages its own focus chain | Chrome is mostly click targets (low risk); keep dense input **forms** as QWidgets until late; test tab-order + DPI on hardware |
| R5 | **Packaging** | Deploying must bundle the QtQuick/Controls/Effects QML plugin trees + any custom QML module and set the QML import path | Add QML dirs to the PyInstaller spec; runs zero-new-dep in the venv today, but frozen builds need the plugin dirs. Verify a frozen build early |
| R6 | **Compute blocks the GUI thread** (the 3-layer law) | Live example: the Scan Planner estimate runs synchronously on the GUI thread and stalls it on huge plans; pyqtgraph render is also GUI-thread | Enforce the layer law with import-linter contracts + a GUI-thread watchdog test; move compute to workers; decimate/prepare plot data off-thread (§8, §9) |

Secondary notes: the threaded render loop is off (R-perf) → keep QML animation light and hot
plots out of QML (already the rule); QtCharts/QtGraphs for hot paths stay **rejected** per the
feasibility numbers (pyqtgraph ~0.2–0.4 ms/frame vs QtCharts 4–6 ms + 25–53 ms jank); the
custom-QSG path measured ~2.45 ms/frame **from Python** (per-vertex Python loop) — fine for a
static overlay, **not** a substitute for pyqtgraph on the hot path.

---

## 6. NEW critical finding — the `GLViewWidget` OpenGL collision (not covered by the spike)

The spike's plotting probe used a Canvas/scope only. The repo also ships a **3D stage view**
(`gui/stage_view.py`) built on **`pyqtgraph.opengl.GLViewWidget`**, i.e. a **QOpenGLWidget**.
Per the Qt 6.4 engineering blog: *"All the widgets within the same window must use the same
rendering API. Putting a QOpenGLWidget into a window mandates that any QQuickWidget in the same
window is also rendering using OpenGL. When there is disagreement between the widgets, bad
things will happen."*

On Windows, a QQuickWidget defaults to **D3D11**; `GLViewWidget` is **OpenGL**. Once the QML
chrome exists in `TCTMainWindow` and the user opens the **Motor Stage** tab, both live in the
**same top-level window** → **backend mismatch**. This is a concrete, foreseeable break the
headless spike could never surface (offscreen forces the software renderer).

**Bounding it:** the GL view is optional (`_HAS_GL` guard → degrades to a "install PyOpenGL"
label) and self-contained, but `PyOpenGL` **is** in `requirements.txt`, so the normal dev and
bench setups **will** have it live.

**Recommended fix (slice-1 decision):** pin the entire app to OpenGL at startup —
`QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)` before the first
QQuickWidget/GL widget is created. Then chrome QQuickWidget and `GLViewWidget` agree on OpenGL,
pyqtgraph 2D raster is unaffected, and MultiEffect glass still renders (it works on any RHI).
Cost: forgo D3D11 for the chrome — negligible for a rail/cards/tiles that are not a hot path.
Alternative (weaker): force the GL stage view into its own top-level OpenGL window so it never
co-resides with QML — but detach makes co-residency hard to guarantee, so **global OpenGL is the
robust default**. Either way, this must be **explicitly validated on a real GPU in slice 1**.

---

## 7. First vertical slice — refined

The spike proposes: QML chrome + token singleton + one hero panel (Scope or Scan Viewer) with
pyqtgraph embedded, detach re-verified (~2–4 weeks). **Endorsed, but Addition 2 reshapes the
slice: it must prove the UI → backend → driver seam with the fast plot path — not cosmetics.**

1. **Slice 1 = shell chrome (rail + QML pill-strip *driving* the existing `DetachableTabWidget`)
   + `Theme` singleton**, RHI pinned to OpenGL, on a **real display**. Acceptance gate must
   include: **Motor Stage `GLViewWidget` renders correctly with QML chrome present, docked *and*
   detached, on a real GPU** (this validates R1 + R2 + the material look at once — the exact
   things the spike could not). This is the de-risking half-day-to-first-week that protects the
   multi-week investment.
2. **Make the hero panel Scope — as a *vertical slice through all three layers*, not a reskin.**
   Wire it: QML chrome + a **`ScopeViewModel` QObject** (backend layer) exposing trace data via
   a queued signal / Qt property; the live trace stays a **pyqtgraph sibling QWidget** fed from
   the scope driver through the existing worker thread; detach re-verified; and the GUI-thread
   **watchdog test** (§9) green under a live-acquire workload. This is what Kaya asked for: the
   slice proves driver → backend(view-model) → UI **and** the fast path in one go, so the
   architecture — not the paint — is what's validated. (Scan Viewer, the audit's *"biggest
   artifact mismatch"*, is the highest-visual-ROI **second** panel; its map is a raster
   `ImageView`, no GL, so it's a clean follow-on. Motor Stage is only *validated* in slice 1,
   not restyled.)
3. **Lock the seam rules up front:** QML is a *view* over the `DetachableTabWidget` model (the
   widget stays the tab/detach engine, §4); QML panels bind to backend view-models only (§9),
   never to compute; extend "no inline hex outside `style.py`" to QML.

**GO / NO-GO caveats before committing weeks:**

- **GO** to build slice 1 as above.
- **Gate:** if, after pinning to OpenGL, `GLViewWidget` + QQuickWidget still cannot coexist in
  one window on the bench GPU, that is a **NO-GO-as-designed** → fall back to isolating GL and
  QML in separate top-levels (or dropping the 3D view to its detached-only window). Decide this
  in slice 1, cheaply, not after three panels are ported.
- **Do first, explicitly:** (i) real-GPU display validation of chrome+GL+detach+2nd-monitor;
  (ii) pin RHI to OpenGL; (iii) `Theme` singleton from `style.py`; (iv) land the GUI-thread
  watchdog test + import-linter layer contracts (§9) **before** the port, so the seam is
  enforced from commit one; (v) a frozen-build smoke test so packaging (R5) is not discovered
  at the end.

---

## 8. Fast numpy → screen without blocking — prior-art comparison (Addition 1)

**Bottom line: "keep pyqtgraph for every hot path, as a sibling QWidget" stands.** Nothing in
the field both **beats pyqtgraph's numpy-direct latency at TCT's data sizes** *and* **composites
under QML material** — and, decisively, **the artifact never puts a plot under glass** (traces
are solid `#0a0b0d` surfaces), so "composite under glass" is a requirement we do not actually
have. That collapses the one theoretical reason to leave pyqtgraph.

Options investigated, with the honest verdict on each:

| Approach | What it is | Speed vs pyqtgraph | Composites under QML glass? | Verdict for TCT |
|---|---|---|---|---|
| **pyqtgraph (current)** | numpy-direct → `QPainter` raster in a `QGraphicsView` QWidget | baseline: ~0.2–0.4 ms/frame @ 2000 pts (spike) | No (sibling QWidget beside QML) — but not needed | **Keep.** Under 60 Hz budget with huge margin; gives axes/autorange/decimation free |
| **pyqtgraph decimation** (`setDownsampling(mode='peak')` + `setClipToView(True)`, or `autoDownsample`) | min/max "peak" saw-wave envelope; clips to visible x-range | keeps huge traces cheap; `peak` preserves spikes (glitches/transients survive) | same as pyqtgraph | **Adopt for long records / million-point traces.** The answer to "huge trace" *inside* pyqtgraph |
| **pyqtgraph `RemoteGraphicsView`** | renders in a **child process**, ships pixels back via shared memory; items created by proxy | offloads render CPU off the GUI process; not lower per-point latency | No (it's still a QWidget; proxied items) | **Escape hatch** if GUI-thread *render* becomes the bottleneck; adds proxy complexity — not needed now |
| **VisPy** | GPU/OpenGL shader scene-graph, numpy-native; embeds in PySide6 as a canvas | **wins only at millions of points** (GPU offload); no advantage at 2000 pts | No — it is a **QOpenGLWidget**, so it (a) can't go under QML either and (b) triggers the §6 OpenGL-API constraint | **Reserve** for a genuine million-point *interactive* case; overkill for the scope |
| **Custom QML `QSGGeometryNode` from numpy** | build a line-strip in `updatePaintNode`, ideally zero-copy into the vertex buffer | spike measured **~2.45 ms/frame** with a Python per-vertex loop; a vectorized-numpy + buffer-memcpy could be faster but is fragile native-pointer code | **Yes** — this is the *only* path that draws the trace *inside* the QML scene | **Reject.** Slower from Python, reimplements pyqtgraph's axes/decimation, and solves the non-problem of "trace under glass" |
| **QtCharts / QtGraphs** | `QLineSeries.replace(QList<QPointF>)` | **4–6 ms + 25–53 ms jank** (spike); even bulk `replace()` is ~2.5 µs/pt (50k→126 ms) → per-point `QPointF` build + `pointAdded` overhead | QtGraphs is QML-native | **Reject** (already rejected by the spike; confirmed *why*) |
| **DAQ process → UI via `multiprocessing.shared_memory`** | acquire in a separate process, numpy over a lockless ring buffer | decouples acquisition from render; sidesteps the GIL for compute-heavy acquire | orthogonal (feeds whatever renderer) | **Backend-layer option** if single-process acquire+compute can't keep up; heavier than a worker QThread — adopt only when measured necessary |

**Why QtCharts/QtGraphs are slow — confirmed:** the cost is **per-point `QPointF` marshalling
plus a `pointAdded()` signal per point** and repeated internal resizes; the mitigation is
`replace()` with a bulk container (much faster than `append()`), but it *still* lands at
~126 ms for 50k points — an order of magnitude over pyqtgraph — and there is no numpy-array
fast-append that avoids building the `QPointF` container. So the marshalling tax is structural,
not a usage bug.

**Synthesis with the layer law (§9):** the fast-plot path is not merely "use pyqtgraph" — it is
"use pyqtgraph **with off-thread data prep and peak decimation so every GUI-thread render stays
bounded**." A million-point autorange or a giant `ImageView` update *can* stall the GUI thread
even in pyqtgraph; decimate/prepare off-thread (or `RemoteGraphicsView`) so the render the GUI
thread actually performs is always small. That is the 3-layer law applied to plotting.

## 9. The three-layer law as the foundation the hybrid sits on (Addition 2)

Kaya has promoted the separation to a **law**: **UI / fast Python backend / drivers — and
compute or blocking I/O must never run on the GUI thread.** This is not in tension with the
hybrid; it is *why* the hybrid is worth doing. Treat it as the foundation and let it place the
seam.

### 9.1 The contract (for `docs/ARCHITECTURE.md`, stated testably)

> **Layer 1 — UI** (`gui/`, and the new QML): renders state and forwards intent. May depend on
> the backend's view-model interfaces (properties/signals/slots) **only**. Must not import
> `analysis/` or perform physics/estimation/file parsing inline, and must not call a
> potentially-blocking backend method synchronously on the GUI thread.
> **Layer 2 — backend** (`controller/`, `analysis/`, `data/`): owns all compute
> (estimation, reconstruction, calibration, ToT/charge/energy), owns run/state orchestration,
> and drives the drivers. Long work runs in a worker (QThread/QThreadPool) and returns to the
> UI via **queued** signals. Never touches a QWidget.
> **Layer 3 — drivers** (`devices/`): own hardware I/O behind the `*_base.py` interfaces;
> no I/O in constructors/imports; simulation backends mandatory.
> **Invariant:** dependencies point **down only** (UI → backend → drivers), and **no compute or
> blocking I/O executes on the GUI thread**.

### 9.2 Enforcement — you need *both*, because they catch different failures

- **Static: `import-linter` layer + forbidden contracts** (run in CI / pre-commit via
  `lint-imports`). A **Layers** contract `gui > controller > devices` plus a **Forbidden**
  contract "`gui` may not import `analysis`" makes a whole class of violation *structurally
  impossible* — a panel literally cannot `import analysis...` to do physics inline.
- **Dynamic: a GUI-thread watchdog test.** Static analysis **cannot** catch the live Scan
  Planner stall, because `estimate_plan` already lives in `controller.plan_estimate` (an
  *allowed* import) — the bug is that `_recompute_estimate()` → `_safe_estimate()` →
  `estimate_plan(self._plan)` is **called synchronously on the GUI thread**. Only a runtime
  responsiveness probe catches "allowed import, wrong thread." Mature Qt practice is a
  **watchdog thread monitoring the main event loop** (KDAB's `UiWatchDog`; Qt Application
  Manager ships one that warns then kills on `warnTimeout`/`killTimeout`). The testable form:
  a headless pytest that installs a QTimer **heartbeat** (e.g. 10 ms) on the GUI thread, drives
  a representative workload (build a max-`max_points` plan and trigger a re-estimate; run a live
  simulated acquire), and **fails if the measured heartbeat interval ever exceeds N ms**
  (e.g. 50–100 ms). Under the current planner that test *fails* — which is the point: it turns
  the shelved off-thread-estimate fix into a regression gate. (The estimate compute already sits
  in the backend layer; the fix is purely to dispatch it to a worker and deliver the
  `PlanEstimate` back via a queued signal to `_render_estimate` — layering is right, threading
  is wrong.)

### 9.3 The QML view-model seam makes the law structural — with one honest caveat

Binding a QML panel to the backend through a **view-model QObject** (Q_PROPERTY + signals +
invokable slots) means the panel can only touch what the view-model exposes. It **cannot** reach
into `estimate_plan()` or a driver and block inline — the boundary is enforced by construction,
which is a real, durable win over QWidget panels that can freely `import` and call anything. **The
caveat:** the view-model seam guarantees *where* the call is made, not that the callee is
*async* — a view-model slot that computes synchronously still blocks the GUI thread. So the
seam + the worker discipline + the watchdog test are complementary: the seam localizes every
UI→backend call to one auditable surface; the worker pattern moves the work off-thread; the
watchdog test proves it stayed off-thread. This is exactly why slice 1 (§7) is a *vertical* —
Scope through `ScopeViewModel` to the driver worker — so the seam and the fast path are proven
together, not just the paint.

## Sources

- Qt blog, *Qt Quick and Widgets, Qt 6.4 Edition* — mini-compositor, "QQuickWidget is a true
  QWidget," "same rendering API per window / bad things will happen," drops OpenGL requirement:
  https://www.qt.io/blog/qt-quick-and-widgets-qt-6.4-edition
- Qt blog, *Window embedding in Qt Quick* — embedding direction is one-way (QML into widgets,
  not widgets into QML): https://www.qt.io/blog/window-embedding-in-qt-quick
- Qt docs, *QQuickWidget Class* — disables threaded render loop; extra offscreen render pass;
  stacking-order restriction lifted; context destroyed on reparent into another top-level;
  transparency via `setClearColor(Qt::transparent)`:
  https://doc.qt.io/qt-6/qquickwidget.html
- Qt docs, *QQuickWidget – QQuickView Comparison Example* — createWindowContainer embedded
  window renders as an opaque box on top:
  https://doc.qt.io/qt-6/qtquick-quickwidgets-qquickwidgetversuswindow-opengl-example.html
- Qt forum, *Embedding a QWidget inside a QML scene?* / *How to embed QWidget into QML?* —
  not supported: https://forum.qt.io/topic/42348/embedding-a-qwidget-inside-a-qml-scene
- Qt docs, *Singletons in QML*: https://doc.qt.io/qt-6/qml-singleton.html
- Qt blog, *What's new in QML Tooling in 6.11, part 3: context property support* — context
  properties are unqualified/invisible to tooling:
  https://www.qt.io/blog/whats-new-in-qmllint-for-qt-6.11-part-3
- Raymii, *Qt/QML: why setContextProperty is not the best idea*:
  https://raymii.org/s/articles/Qt_QML_Integrate_Cpp_with_QML_and_why_ContextProperties_are_bad.html
- KDAB, *Cleaner QML Controller Wiring with Singleton Instances* (Qt 6.12
  `setExternalSingletonInstance`): https://www.kdab.com/singleton-controllers-in-times-of-declarative-qml/
- KDAB, *Declarative Widgets / QQuickPaintedItem "worst of both worlds"*:
  https://www.kdab.com/declarative-widgets/
- pyqtgraph, *RemoteGraphicsView* (child-process render + shared memory):
  https://pyqtgraph.readthedocs.io/en/latest/api_reference/widgets/remotegraphicsview.html
- pyqtgraph, *PlotDataItem* — `setDownsampling(mode='peak'|'mean'|'subsample')` + `setClipToView`:
  https://pyqtgraph.readthedocs.io/en/latest/api_reference/graphicsItems/plotdataitem.html
- VisPy — GPU/OpenGL, millions of points, embed-in-Qt:
  https://vispy.org/gallery/scene/realtime_data/ex01_embedded_vispy.html and https://github.com/vispy/vispy
- Qt forum / QtCentre, *QLineSeries extremely slow* — per-point `QPointF` + `pointAdded`; use
  bulk `replace()`: https://forum.qt.io/topic/140576/qt-charts-extremely-slow-qlineseries and
  https://www.qtcentre.org/threads/69429-SOLVED-QLineSeries-extremely-slow
- Python docs, *multiprocessing.shared_memory* (numpy-over-shm DAQ decoupling):
  https://docs.python.org/3/library/multiprocessing.shared_memory.html
- KDAB, *UiWatchDog: a keepalive monitor for the GUI thread*:
  https://www.kdab.com/uiwatchdog-a-keepalive-monitor-for-the-gui-thread/
- Qt docs, *Watchdog | Qt Application Manager* (main-loop + render-thread watchdog):
  https://doc.qt.io/QtApplicationManager/watchdog.html
- Import Linter — *Layers* and *Forbidden modules* contracts:
  https://import-linter.readthedocs.io/en/latest/contract_types.html
- Repo: `TCT_app/gui/planner_panel.py` (`_recompute_estimate`→`_safe_estimate`→`estimate_plan`,
  GUI-thread), `TCT_app/controller/plan_estimate.py`,
  `TCT_app/gui/detachable_tabs.py`, `TCT_app/tct_gui.py`,
  `TCT_app/gui/style.py`, `TCT_app/gui/stage_view.py` (GLViewWidget),
  `TCT_app/gui/camera_panel.py` (raster QImage/QLabel),
  spike worktree `.claude/worktrees/agent-aa19d2caf98c928dd/spike/qml_shell/`.
