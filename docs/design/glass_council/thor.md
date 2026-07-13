# Thor — the rendering-pipeline ground truth (DWM ↔ Qt, backdrop attach → eyeball)

Glass council lane: mechanics only. Every layer between
`DwmSetWindowAttribute` and the photon, named, with the decision rule each
layer applies. Confidence labels: **[repo]** = verified in this repo at the
cited line, **[qt-src]** = Qt source knowledge (stable across 6.x, cite
given), **[ms]** = documented Windows behavior, **[inferred]** = mechanically
derived, needs one empirical run. Read §3 for the two live symptoms and §5
for the QML/U-track verdict.

---

## 0. Verdict in one screen

1. A DWM material is **not painted by the app**. It is a brush DWM inserts
   *behind* the window's content in DWM's own visual tree. The app's entire
   job is to deliver **per-pixel alpha < 255** to DWM through its window
   surface. Every failure in this case is one of the layers below turning
   that alpha into 255 (opaque barrier) or the material itself rendering
   light (white plate).
2. There are **four distinct flush paths** from a Qt top-level to DWM
   (§1.2). Only ONE of them (framed raster + `WA_TranslucentBackground`,
   BitBlt of an ARGB backing store) is compatible with DWMSBT materials.
   The app is on that path **only while no render-to-texture child is
   live** — and the main window owns a `GLViewWidget`
   (`TCT_app/gui/stage_view.py:214`) that flips the whole window to the
   GPU-composited path the moment the "3D" stage view is first shown.
   **The research note that ruled out GL children
   (`docs/research/dwm_backdrop_blur_recipe.md` item 4, "grep clean") is
   factually wrong** — `gui/stage_view.py` imports `pyqtgraph.opengl` and
   instantiates `gl.GLViewWidget()` at MotorPanel construction
   (`gui/motor_panel.py:604` → `StageView` → `StageView3D`). It sits hidden
   on a `QStackedWidget` page (2D is default, `stage_view.py:318`), which
   makes the barrier **time-dependent**: raster at launch, GPU-composited
   after the first 3D click. That is a mechanism that "worked earlier,
   died later" without any commit changing.
3. Nothing in this codebase ever sets `DWMWA_USE_IMMERSIVE_DARK_MODE`
   (attr 20) — grep of `gui/backdrop.py` and the whole tree: absent
   **[repo]**. To DWM every TCT window is a **light-mode window**. Mica's
   tint, Acrylic's tint, and — critically — the **solid fallback plate**
   DWM substitutes when transparency effects are off (battery saver, RDP,
   the Settings toggle) are all chosen from that flag. Light-mode fallback
   = flat near-white. That is the cheapest mechanical explanation for
   "backdrop region renders completely WHITE everywhere, incl. the simple
   dialog": the material chain is *working*, and what it delivers is the
   light-variant / light-fallback plate behind whatever alpha the canvas
   leaves open.
4. QML: a **real `QQuickWindow`** (QQuickView / ApplicationWindow) gets
   glass essentially for free — scene cleared to transparent + alpha
   swapchain (DirectComposition path on Windows, the same composition
   family WinUI uses) + the existing attr-38 attach on its HWND. A
   **`QQuickWidget` gets nothing for free and actively harms the host
   window's glass**: it renders to a texture and drags the whole QWidget
   top-level onto the GPU-compose flush path (§5.2) — the same
   alpha-killer as the GLViewWidget. This decides the U-track: glass
   arrives when the *shell window itself* is a QQuickWindow (U-track
   final state), not while chrome rides as QQuickWidget islands inside a
   QWidget shell (today's option (a)).

---

## 1. The composition stack, bottom-up (QWidget app on Windows 11)

### 1.1 Layer 0 — DWM's side: visuals, redirection surfaces, and the two attributes

Every top-level HWND owns exactly one **content source** DWM composites:

* **Redirection surface** (default): GDI/BitBlt output of the window is
  captured into a DWM-owned bitmap. It has a BGRA layout — the alpha
  bytes physically exist — but DWM treats the surface as **opaque unless
  the window is glass-eligible**: historically, per-pixel alpha in the
  client area is honored only inside regions covered by
  `DwmExtendFrameIntoClientArea` ("frame" pixels) **[ms]**. This is why
  `backdrop.py` extends a full sheet (`_MARGINS(-1,-1,-1,-1)`,
  `gui/backdrop.py:160`) before applying the material: it converts the
  entire client into alpha-honoring territory. (winmica reports attr 38
  alone suffices on Win11; treat extend-frame as required belt-and-braces
  — it is cheap and the failure mode without it is "alpha ignored".)
* **Legacy layered surface** (`WS_EX_LAYERED`): two sub-modes.
  `SetLayeredWindowAttributes` (uniform alpha — what
  `QWidget.setWindowOpacity(<1)` uses) and `UpdateLayeredWindow`
  (per-pixel bitmap handed to DWM wholesale). **Both suppress DWMSBT
  materials** — the layered path short-circuits the window's normal
  visual, and the material brush hangs off that visual. The repo already
  discovered and pinned the uniform-alpha case
  (`gui/style.py:2136-2147`, opacity pinned to 1.0 while a material is
  active) **[repo]**. The per-pixel case matters below (§1.2, path C).
* **Composition swapchain** (DXGI flip-model / DirectComposition,
  optionally `WS_EX_NOREDIRECTIONBITMAP`): the modern path. The app hands
  DWM premultiplied-alpha frames directly; per-pixel alpha is first-class
  and composes correctly against backdrop materials. WinUI lives here.
  **Qt Quick's D3D RHI lands here for translucent windows** (§5.1).

The two DWM attributes in play:

* `DWMWA_SYSTEMBACKDROP_TYPE` (38): inserts the material visual
  (Mica=DWMSBT_MAINWINDOW, Acrylic=DWMSBT_TRANSIENTWINDOW) **behind** the
  window's content visual. It does nothing visible unless content alpha
  < 255 somewhere. `gui/backdrop.py:169-183` **[repo]**.
* `DWMWA_USE_IMMERSIVE_DARK_MODE` (20): declares the window dark-mode to
  DWM. Drives the material's tint variant AND the solid color DWM
  substitutes when transparency effects are unavailable/disabled
  **[ms]**. **Never set anywhere in this repo** **[repo]** — every
  window is light-mode as far as materials are concerned, regardless of
  the app's dark QSS.

Per-HWND persistence: both attributes live on the HWND. If Qt ever
destroys/recreates the native window (window flag changes, some
attribute toggles, screen changes), the attach is **gone** and
`winId()` changes — reattach is required. `apply_window_backdrop_to`'s
re-issue-on-every-toggle behavior (`gui/style.py:2230-2265`) is the
right instinct for this **[repo]**.

### 1.2 Layer 1 — Qt's flush-path decision (the fork that decides everything)

Qt picks how a top-level's pixels reach Windows. Four paths **[qt-src:
`qwindowsbackingstore.cpp::flush`, `qrhibackingstore`/
`QWidgetRepaintManager`]**:

| Path | Trigger | Mechanism | DWMSBT-compatible? |
|---|---|---|---|
| **A. Opaque raster** | default | BitBlt of `Format_RGB32` backing store (alpha bytes 0xFF) | material attached but invisible — every pixel opaque |
| **B. Framed translucent raster** | `WA_TranslucentBackground`, window HAS a frame | BitBlt of `Format_ARGB32_Premultiplied` backing store; alpha bytes copied verbatim into the redirection surface; **no WS_EX_LAYERED** | **YES — the only working QWidget path.** Alpha honored where frame is extended (§1.1). The theme-editor dialog's real, live-verified acrylic blur (`docs/research/dwm_backdrop_blur_recipe.md`, decisive evidence) is this path. |
| **C. Frameless translucent raster** | `WA_TranslucentBackground` + `FramelessWindowHint` | `UpdateLayeredWindowIndirect`, `WS_EX_LAYERED` | no — layered suppresses the material (you get per-pixel see-through to the raw desktop, no blur) |
| **D. GPU-composited ("composeAndFlush"/rhiFlush)** | ANY visible render-to-texture child in the window: `QOpenGLWidget`, `GLViewWidget`, `QQuickWidget` | whole window's raster content is uploaded as a texture, composed with the RTT textures in one GL/RHI context, presented via swapchain | **effectively no** — per-pixel alpha through this path to DWM is outside Qt's supported matrix on Windows (QTBUG-58178-class; QOpenGLWidget docs' translucency limitation). Result ranges from opaque to black to undefined, and it is *sticky per window while the RTT child is visible*. |

Corollaries that decide this case:

* `setWindowOpacity(<1)` forces `WS_EX_LAYERED` on **any** of these paths
  → material dead. Already pinned **[repo]**.
* Path B→D is not a startup property; it **flips at runtime** when the
  first RTT child becomes visible. The Motor Stage tab is tab 0; its 3D
  view is one segment-button click away (`stage_view.py:348-349`).
* Under `TCT_QML_SHELL=1` the chrome `QQuickWidget`
  (`gui/qml_shell.py:417`) makes the main window path-D **from launch,
  unconditionally**.
* Detached tabs (`gui/detachable_tabs.py:27-35`) are their own
  top-levels: detaching the Motor Stage tab moves the GL widget OUT of
  the main window — the main window returns to path B. This is the
  cheapest live discriminator experiment there is (§3.3).

### 1.3 Layer 2 — backing store format and the pre-clear rule

* `QRasterBackingStore::format()`: `ARGB32_Premultiplied` iff the
  window's surface format has alpha, else `RGB32` **[qt-src]**.
* `QRasterBackingStore::beginPaint()`: iff the image has alpha, the dirty
  region is pre-filled with `Qt::transparent` in `CompositionMode_Source`
  **[qt-src]**. So on an alpha surface, any pixel no widget paints stays
  **alpha 0** → shows 100 % material (or 100 % fallback plate).
* `WA_TranslucentBackground` implies `WA_NoSystemBackground` on the
  widget and sets alpha 8 on its window format
  (`QWidgetPrivate::updateIsTranslucent`) — but only reliably **before
  native window creation**. `main.py:41-44`'s default-format alpha
  (`_enable_translucent_window_surface`) **[repo]** removes that timing
  hazard: every top-level surface is born ARGB. Side effect worth
  knowing: with the default format carrying alpha, *every* window's
  backing store pre-clears to transparent; an opaque window is opaque
  only because its root widget paints its full background (next layer).

### 1.4 Layer 3 — per-widget background decision (why an intermediate widget goes opaque — or white)

Within one top-level, Qt walks the widget tree and each widget decides
whether to paint a background *before* its own `paintEvent`:

1. **QSS background rule matches** → the stylesheet engine paints it and
   sets `WA_StyledBackground`. `rgba()` alphas here are real: they land
   in the ARGB backing store (this is the `_canvas_fill` mechanism,
   `gui/style.py:725-734`, painted at `style.py:770-771`) **[repo]**.
2. else **`autoFillBackground` true** → fill with the palette's
   `Window` role.
3. else **paint nothing** → parent's pixels (or the pre-clear
   transparency, on the root) show through.

Palette resolution for rule 2: instance palette → parent chain → app
palette → **platform default (light gray ≈ #f0f0f0)**. The three ways an
"intermediate widget goes opaque-white" in practice:

* **W1 — autoFill + unthemed palette.** `backdrop._set_canvas_translucent(w, False)`
  restores exactly `setAutoFillBackground(True)` + blank `QPalette()`
  (`gui/backdrop.py:239-241`). A blank instance palette resolves through
  the app palette (dark, `_apply_app_palette`, `style.py:198`), so here
  it lands dark — but any window that misses `_apply_app_palette` (or a
  future embedded context with its own QApplication-less palette chain)
  lands **platform white**.
* **W2 — a foreign widget-level stylesheet** using `palette(window)` or
  hard-coded light colors paints its whole subtree opaque and, per Qt's
  cascade, **beats the app stylesheet** (widget sheet > app sheet for the
  same widget) — our `rgba` canvas rules cannot reach in. This is the
  QtAds trap (§4).
* **W3 — the "black/white box" trap already hit once**: any broad QSS
  type-selector background turns thousands of children into painters
  (`style.py:746-762` history note) **[repo]**. The repaired rule paints
  shells by name only. Keep it that way; every widget that paints is one
  more opaque layer the material must get around.

### 1.5 Layer 4 — what the eye sees (extended interaction matrix)

The research note's matrix (`dwm_backdrop_blur_recipe.md`) is correct
**[repo-verified live]**; extended with the white-plate producers:

| Surface state | Material state | Eye sees |
|---|---|---|
| alpha reaches DWM (path B), canvas rgba 0.82 | material composites, window declared dark | dark frosted margins — the goal |
| alpha reaches DWM | material composites, **no attr 20** (today) | **light Mica/Acrylic** behind the canvas → milky/washed; where canvas paint is thin/absent → **white** |
| alpha reaches DWM | transparency effects OFF (battery saver / RDP / Settings) | **solid fallback plate** in the window's theme variant — without attr 20: **flat white** |
| alpha reaches DWM | attr 38 never (re)applied on this HWND (recreated window) | crisp desktop through the alpha holes, no blur |
| path D (GL/Quick child live) | any | alpha never arrives; opaque/undefined — material invisible |
| any + `WS_EX_LAYERED` (opacity < 1) | any | material suppressed; uniform see-through of the opaque image |
| stale surface after live attribute churn (Qt 6.10/6.11 + Win11 24H2-class, "phantom white box", forum 163927) | any | **white rectangle until a real repaint/resize** — `window.update()` (`style.py:2263`) is a weaker nudge than the resize the bug report needed |

---

## 2. project_tct mapped onto the stack (evidence lines)

| Layer | Where in repo | State |
|---|---|---|
| attr 38 + extend-frame | `TCT_app/gui/backdrop.py:153-183, 268-328` | correct, fail-safe ordered, HRESULTs logged |
| attr 20 (dark-mode) | — | **absent everywhere** |
| ARGB surface | `TCT_app/main.py:25-44` | default-format alpha 8, pre-QApplication — correct |
| canvas prep (Qt attrs) | `backdrop.py:203-261` — top-level + `#mainShell` central widget | correct post-fix; `_CANVAS_MODE` candidate B (`no_system_background`) still uneval'd |
| canvas paint (QSS) | `style.py:725-734, 770-771` — `rgba(bg, 0.82)` iff kind ≠ none | correct post glass-gap fix |
| opacity/layered conflict | `style.py:2136-2147` opacity pin | correct |
| flush path | `gui/stage_view.py:214` GLViewWidget (hidden page, live after first "3D" click); `gui/qml_shell.py:417` QQuickWidget (QML shell mode) | **the unaccounted layer** — flips the window to path D |
| per-window fan-out | `style.py:2286-2317`; construction attach `tct_gui.py:254`, `theme_editor.py:231`, `settings_window.py:1359`, `detachable_tabs.py:31` | uniform, matches findings doc |
| panel opt-in glass | `style.py:1440-1441` `glassPane` property, `panel_kit.py:941-991` registry | by design opaque unless opted in |

---

## 3. The two symptoms, mechanically

### 3.1 Symptom 1 — acrylic on/off pixel-equal on the main window

Historical root cause (opaque QSS canvas painting over the transparent
palette) is confirmed and fixed — `glass_gap_findings.md` §2 **[repo]**.
The *residual* main-window vs dialog asymmetry has a second, still-live
mechanism the afternoon investigation explicitly (and wrongly) ruled
out: **the main window is the only window that can host render-to-texture
children.** While the GLViewWidget (or the QML chrome widget) is/was
visible, the whole main window flushes via path D and its canvas alpha
never reaches DWM — the dialog, GL-free, keeps blurring on path B. Same
code, same recipe, opposite result, exactly the observed discriminator —
with no need for the QMainWindow-surface quirk to carry the whole
explanation.

### 3.2 Symptom 2 — everything renders WHITE (incl. the theme-settings dialog)

Ranked by mechanism cost:

1. **Light-variant material / light fallback plate (attr 20 missing).**
   The one candidate that turns *both* windows white *simultaneously*
   without any Qt-side breakage: DWM composites its light-mode plate
   behind every alpha region. If Windows transparency effects went off
   between the "it blurred" sighting and tonight (battery saver on a
   CPU-bound laptop does this **automatically**; RDP does too), the
   material degrades to a **solid light plate** — flat white, no blur,
   everywhere a backdrop window leaves alpha < 255. Checks: Settings →
   Personalization → Colors → "Transparency effects" + power state at
   repro time; then apply attr 20 = TRUE per window and re-test.
2. **Canvas paint absent while surface is translucent.** If the QSS in
   effect was built while `get_window_backdrop() == "none"` (build-order
   or a skipped rebuild via `apply_theme`'s identical-QSS guard) but
   `WA_TranslucentBackground` is applied, the canvas region is alpha-0 →
   100 % plate from (1) → pure white. One log line decides this: dump
   `get_window_backdrop()` + whether the active QSS contains `rgba(` in
   the `QMainWindow, QDialog` rule at repro time.
3. **Stale-surface white box** (matrix last row): live attribute/palette
   churn on shown windows — every `_toggle_theme` re-runs the full chain
   on every top-level (`style.py:2230-2265`) — with only `update()` as
   repaint nudge. Matches "white until poked"; distinguishable because a
   resize instantly heals it.

Note these compound: (2) or (3) opens the hole, (1) paints it white.
A dark composite (0.82 · dark bg + 0.18 · plate) can never be "completely
white" — so the canvas paint was **not** landing wherever pure white was
seen. That is the sharpest single fact tonight's white gives us.

### 3.3 Discriminator experiments (cheap, ordered, all live-runnable)

1. **Transparency-effects check** (10 s): Windows Settings toggle + power
   plan at repro. If OFF → symptom 2 is (1) by definition.
2. **attr-20 probe** (one ctypes line in a scratch script, or temporarily
   in `apply_backdrop`): set `DWMWA_USE_IMMERSIVE_DARK_MODE=1` before
   attr 38 on the dialog only; compare white → dark-material.
3. **GL flush-path A/B** (30 s, decides §3.1): with acrylic active and
   margins frosting nowhere on the main window — detach the Motor Stage
   tab (its GL widget leaves the window). If the main window's margins
   start frosting, path D is confirmed as the barrier. Counter-probe:
   re-dock, click "3D", watch the frost die.
4. **Resize heal** (5 s): if white heals on a manual resize → stale
   surface (3.2-3), and the fix is a real repaint/resize nudge after
   attribute churn, not more attribute churn.
5. **Pixel harness regression pins** (`scripts/capture_onscreen.py`
   already probes DWM compositing): add scenarios (a) main window with
   3D view active vs detached, (b) with/without attr 20, so both barriers
   stay pinned once fixed.

---

## 4. QtAds — where a dock stack inserts opaque layers

Ground truth first: **QtAds is not in the widget tree yet.** It is a
requirement (`TCT_app/requirements.txt:12`, `PySide6-QtAds>=4.1`) and the
design target; the shipped shell is `DetachableTabWidget` + two plain
`QDockWidget`s (`tct_gui.py:401-418, 725, 770`). So this section is the
forward map for the cockpit the council is designing (QtAds 4.x
internals, **[library]** confidence):

Hierarchy a docked panel actually sits in:

```
top-level window
└── CDockManager (QFrame; IS a CDockContainerWidget)
    └── root CDockSplitter (QSplitter subclass; handles paint)
        └── CDockAreaWidget (QFrame)
            ├── CDockAreaTitleBar → CDockAreaTabBar → CDockWidgetTab (QFrames)
            └── QStackedWidget (area content stack)
                └── CDockWidget (QFrame)
                    └── [optional CDockWidgetScrollArea] → user panel
```

Opaque-layer insertions, in paint order:

1. **CDockManager installs its own widget-level stylesheet at
   construction** (loads `:/ads/stylesheets/default.css`, or the
   focus-highlighting variant, and calls `setStyleSheet` on itself).
   Per §1.4-W2 this **beats the app stylesheet for the entire dock
   subtree** — every `ads--*` rule painting `palette(window)`/solid
   colors is an opaque plate our canvas `rgba` rules can never reach.
   This is precisely the BRIEF's suspicion, with the mechanism named:
   it is not that ADS "paints opaque" per se, it is that its own sheet
   **outranks ours**. Fix derivation: after constructing the manager,
   replace its sheet (`dock_manager.setStyleSheet(...)`) with our own
   ADS-namespaced rules — canvas-role surfaces get `_canvas_fill`-class
   rgba, content stacks stay opaque per design law. One function in
   `gui/style.py`, same token vocabulary.
2. **QSplitter gutters + area title bars** — these are exactly the
   "exposed canvas" of a dock cockpit (the margins where glass reads).
   With rule 1 solved they are the natural glass zones; without it they
   are the opaque grid that makes acrylic-on/off pixel-equal again.
3. **QStackedWidget content stacks** paint nothing themselves — the
   opaque layer inside an area is the panel (cardPane), which is by
   ratified design opaque unless `glassPane`-opted-in. No new mechanism.
4. **CFloatingDockContainer** — a separate top-level window. Needs the
   same per-window treatment `_DetachedWindow` already gets
   (`detachable_tabs.py:27-35`): backdrop attach + canvas prep + opacity
   pin at construction, *and* attr 20 once that lands. If ADS's
   "force native title bar" config is off, floating containers are
   frameless → **path C (ULW layered)** → material impossible there;
   prefer native-title-bar floating windows for glass parity.
5. **Dock overlays / drop previews** are already translucent windows —
   irrelevant to the material question, but they are `WS_EX_LAYERED`
   while dragging; expect the material to blink during drags. Cosmetic,
   not structural.
6. **RTT children still rule**: a GL plot island docked anywhere in the
   main container puts the *whole window* on path D regardless of ADS
   styling. In a QtAds cockpit with GL islands, **window-level DWM glass
   and visible GL widgets are mutually exclusive in the same top-level**
   (until the shell itself is a QQuickWindow, §5). The honest QWidget-era
   design is therefore: token-based fake glass as the default cockpit
   look, real material only on GL-free windows (dialogs, detached
   non-GL panels) — which is what the ratified fallback already says.

---

## 5. The same analysis for a QML shell

### 5.1 QQuickWindow / scene-graph alpha (the mechanics)

* A `QQuickWindow` clears its color buffer to `QQuickWindow::color`
  every frame — **default opaque white** **[qt-doc]**. (The literal
  white plate is a QML default, worth remembering while triaging white
  symptoms in any future hybrid.)
* Recipe for a translucent Quick window: `color: "transparent"` +
  alpha in the surface format (`QQuickWindow::setDefaultAlphaBuffer(true)`
  before creation, or the app-wide default format `main.py` already
  sets). The scene graph then renders premultiplied alpha into the
  swapchain.
* On Windows with the D3D RHI, a translucent Quick window is presented
  through a **composition swapchain (DirectComposition)** — Layer-0's
  modern path, per-pixel alpha first-class, no `WS_EX_LAYERED`, no
  redirection-surface folklore **[qt-src/ms]**. Attach attr 38 (+20) to
  the QQuickWindow's HWND with the *existing, unchanged*
  `gui/backdrop.py` and the material composites behind scene alpha the
  way it does behind WinUI apps. Items paint whatever alpha they want;
  there is no per-widget attribute fight because there are no widgets —
  an Item paints nothing unless told (no autoFill, no palette fills).
  The intermediate-widget-goes-white failure class **does not exist**
  inside a scene graph.
* Caveats that go straight into the degradation ladder:
  `QT_QUICK_BACKEND=software` renders through the raster backing store —
  QWidget-era rules return; RDP sessions keep DWM but **disable
  Mica/Acrylic by policy** → the solid fallback plate (set attr 20 or it
  is white); Linux/Win10: attr 38 doesn't exist → token fallback. The
  current shell already pins the Quick RHI to OpenGL for GLViewWidget
  coexistence (`qml_shell.py:66-76`); note that the DComp translucency
  path is the **D3D** RHI's — an OpenGL-pinned Quick window falls back
  to WGL surfaces where translucent top-levels are the old, fragile
  story. **The RHI pin and window-level QML glass are in tension; the
  U-track shell should be D3D-RHI with GL islands replaced or
  window-contained** [inferred — needs one empirical run on the bench].

### 5.2 QQuickWidget vs QQuickView — the difference that decides the U-track

* **QQuickView / ApplicationWindow**: the scene *is* the native window.
  Alpha flows scene → swapchain → DWM. Glass = configuration
  (transparent clear + alpha format + attr 38/20), not architecture.
* **QQuickWidget**: the scene renders into an offscreen target; the
  result is composed into the **host QWidget window's** flush. Two
  consequences, both fatal for free glass: (a) its own `clearColor`
  becomes an in-window plate — the current shell sets it **opaque
  canvas** (`qml_shell.py:420`) and `Shell.qml:78` adds an opaque
  root `Rectangle` (both correct for the ratified fallback look, and
  both barriers if anyone expects material through them); (b) it is a
  render-to-texture child → the whole top-level flips to **path D**,
  killing per-pixel alpha for the *entire window*, including the QWidget
  margins that frost today without it. So under `TCT_QML_SHELL=1` the
  main window cannot show a DWM material **anywhere**, by mechanism, no
  matter how the canvas is painted. Today's option (a) chrome islands
  and window-level real glass are mutually exclusive.

### 5.3 U-track verdict

**Glass is free at the window level the day the shell top-level is a real
QQuickWindow** — transparent scene clear, alpha swapchain, the existing
backdrop attach, plus the missing attr 20. QWidget safety islands and GL
plot islands embedded via window containers are opaque rectangles in that
composition — which is exactly the ratified design law (content stays
opaque) — and they no longer poison the rest of the window, because they
are their own native surfaces composited by DWM, not texture children of
a raster flush. What is *not* free on any horizon: in-scene frosted blur
of app content (needs ShaderEffect/MultiEffect — ratified ban stands;
the pre-blended token look remains the fallback), and any glass at all
on software/RDP/Win10/Linux rungs — the token vocabulary is the floor of
the ladder everywhere.

---

## 6. Constraints any derived fix must respect

1. Never `setWindowOpacity(<1)` with a material (already pinned).
2. Attr 20 must be set per-HWND alongside attr 38 and re-asserted on the
   same reissue cadence (it is lost with the HWND like attr 38).
3. Canvas alpha rides QSS `rgba` only — no palette-role alphas, no broad
   type selectors (the W3 trap, `style.py:746-762`).
4. Any window meant to show material must stay RTT-free: GL/Quick-widget
   children move to their own top-levels, or the window forfeits material
   and runs the token look. State it per window; do not average.
5. Every rung of the ladder (no-DWM, transparency-off, RDP, software
   Quick) must land on the pre-blended token look **by construction**
   (the `_canvas_fill`-style "byte-identical when off" pattern is the
   right template — extend it to attr-20/QtAds/QML knobs).
6. Regression truth = the onscreen pixel harness, extended with the §3.3
   scenarios; offscreen captures can only ever pin QSS text and alpha
   plumbing, never the material (compositor-side, full stop).

## 7. Confidence ledger

* **[repo]-verified**: every file:line cited; attr-20 absence; GLViewWidget
  existence/location/visibility default; QQuickWidget opaque clearColor;
  opacity pin; canvas fill mechanics; fan-out uniformity.
* **[qt-src]**, high confidence: flush-path fork incl. the frameless-only
  ULW condition; backing-store format/pre-clear; RTT → composeAndFlush.
  One empirical anchor exists in-repo: dialog blurs (path B works) while
  the GL-hosting main window did not.
* **[inferred]**, needs one live run each: path D as the *current*
  main-window barrier (experiment §3.3-3); attr 20 turning tonight's
  white dark (experiment §3.3-2); D3D-RHI DComp translucency for the
  U-track shell on this exact driver (bench eyeball).

— Thor, glass council, 2026-07-13 night. Read-only lane; no code touched.
