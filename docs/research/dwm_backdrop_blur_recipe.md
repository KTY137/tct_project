# DWM system backdrop (Mica/Acrylic) — why "transparent but unblurred", and the working recipe

- **Date:** 2026-07-13
- **Question:** Post-9cdc970 the window is transparent (desktop visible through the
  canvas) but the acrylic **blur does not kick in** — desktop is crisp/unblurred.
  Diagnose against `TCT_app/gui/backdrop.py` + `gui/style.py`; produce the verified
  recipe + a one-beat fix spec for Noah.
- **Model/version:** Windows 11 build **26200** (25H2-class), PySide6 (Qt 6),
  `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE=38)`, raster Qt surfaces (no GL).
- **Confidence:** official docs + secondary source (Qt forums, winmica). The DWM
  requirements are official; the QMainWindow-specific Qt failure mode is corroborated
  by multiple Qt forum reports, not a single official page.

## Decisive live evidence (Kaya, same machine/session/build)

- **Theme-editor `QDialog` → REAL acrylic blur (good).** This one fact PROVES: build
  26200 is fine, the `DwmExtendFrameIntoClientArea(-1,-1,-1,-1)` + `SYSTEMBACKDROP_TYPE`
  + `WA_TranslucentBackground` recipe is correct, and `apply_backdrop` returns S_OK.
- **`TCTMainWindow` (QMainWindow) → transparent, crisp desktop, NO blur (bug).**
- Both call `apply_window_backdrop_to(self)` then `setWindowOpacity(get_window_opacity())`
  at construction (`theme_editor.py:231-232`, `tct_gui.py:254/260`); both get
  `WA_TranslucentBackground` (test_backdrop.py:348-349). **Same code, same global
  opacity, opposite result** ⇒ the cause is *structural to QMainWindow*, not the recipe,
  not the build, not a rejected attribute.

## Diagnosis ranking for our exact symptom

1. **[MOST LIKELY] The QMainWindow client never carries per-pixel alpha to DWM.**
   `backdrop._prepare_window_canvas` (backdrop.py:203-216) sets `WA_TranslucentBackground`
   + a transparent `Window` palette **only on the top-level widget passed in**. A flat
   `QDialog` *is* that widget, so its own `rgba(bg,0.82)` canvas (the `QMainWindow,QDialog`
   QSS rule) becomes an ARGB surface DWM composites its material behind → blur in the card
   margins. A `QMainWindow`'s client is instead filled by the `#mainShell` **child**
   (`tct_gui.py:319`) inside an edge-to-edge `DetachableTabWidget`; `#mainShell` is never
   given `WA_TranslucentBackground` nor a transparent role, and QMainWindow's own window
   *surface has no alpha channel by default* (documented Qt behavior — see Qt forum
   #142890/#46849). Net: the QMainWindow client is not a DWM-eligible transparent surface,
   the material (proven rendering on the dialog) has nothing to composite behind, and the
   window's translucent regions fall straight through to the **crisp, unblurred desktop**.
   This is the textbook "alpha hole punched, no material behind" case.
2. **[SECONDARY] Whole-window uniform-alpha (`setWindowOpacity`<1, `WS_EX_LAYERED`).**
   A layered uniform-alpha window shows crisp desktop through the *entire* window
   (panels included) and **suppresses the DWM backdrop**. Logically ruled out as the
   *discriminator* here (both windows share the same global opacity; the dialog blurs, so
   opacity ≈ 1.0), but it is the OTHER thing that produces this exact look, so confirm the
   slider reads 100% before touching code (glass_gap_findings §5(d)).
3. **[LOW] Attribute silently ineffective / stale backing store.** DWM can return S_OK yet
   not render (Qt 6.10.x "phantom white box", Win11 24H2, fixed by minimize+resize — a
   surface-staleness bug). Our `apply_window_backdrop_to` calls `window.update()`, which is
   weaker than a resize; note it, but the dialog rendering fine on the same build makes this
   unlikely to be the primary cause.
4. **[RULED OUT] Native/GL child surface, build-26200 regression, missing extend-frame.**
   No `QOpenGLWidget`/`QVideoWidget`/`WA_NativeWindow`/`createWindowContainer` anywhere in
   `gui/` (grep clean) — camera/plots are raster. Build 26200 renders the dialog fine.
   `DwmExtendFrameIntoClientArea` is present (backdrop.py:160) and, per winmica/MS, is not
   even required for the modern `SYSTEMBACKDROP_TYPE` attribute.

## The verified recipe (Win11 22H2+ / build 26200)

For a plain per-window backdrop (our path, = winmica's path — NOT the WinUI
`MicaController`/`WS_EX_COMPOSITED` compositor path):

1. Get the HWND (`winId()` forces native creation) — backdrop.py already does this.
2. `DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, &v, 4)`, v = `DWMSBT_MAINWINDOW`(2,
   Mica) / `DWMSBT_TRANSIENTWINDOW`(3, Acrylic). **This alone applies the material to the
   whole window**; `DwmExtendFrameIntoClientArea(-1,-1,-1,-1)` is optional belt-and-braces
   (needed only for the legacy `DWMWA_MICA_EFFECT=1029` path). Keep it, but note that if it
   ever returns non-zero, backdrop.py:264-268 **aborts the whole backdrop** — a fragility.
3. **The window must expose real per-pixel alpha in its CLIENT paint stack**, all the way
   down to whatever covers the client — not just the top-level. Where the composited pixel
   alpha < 255, DWM shows the material; where the app paints opaque, the material is hidden;
   where the surface has NO alpha channel, translucency degrades to a plain desktop hole.
4. Paint requirement: leave the canvas semi-/fully-transparent (our `rgba(bg,0.82)`), keep
   *content* (plots/camera/cards) opaque (design law) — the material shows only in the gaps.

## Interaction matrix (pin this in code)

| WA_TranslucentBackground | setWindowOpacity | SYSTEMBACKDROP set | Result |
|---|---|---|---|
| off | 1.0 | yes | opaque paint hides material → no visible blur |
| **on, ARGB client surface** (flat QDialog) | 1.0 | yes | **material composites → REAL blur** ✓ |
| on, top-level only, client covered by opaque/no-alpha child (our QMainWindow) | 1.0 | yes | **transparent-but-unblurred → crisp desktop** ✗ (our bug) |
| on | <1.0 | yes | `WS_EX_LAYERED` uniform alpha **suppresses backdrop** → crisp desktop, whole window |
| off | <1.0 | yes | layered uniform alpha over opaque paint → dimmed crisp desktop, no blur |

Rule of thumb: **`setWindowOpacity(<1)` and DWM system backdrop are mutually exclusive**
(layered uniform alpha wins, no material). `WA_TranslucentBackground` at opacity 1.0 is the
only translucency mode compatible with the backdrop — and it must reach the client surface.

## Build 26200 notes

No documented `SYSTEMBACKDROP_TYPE` regression vs 22H2/23H2 that matches this symptom; and
the dialog blurs correctly on 26200, so the behavior is intact. (Known unrelated item: some
Insider builds tightened Mica's "wallpaper only when window is on the primary/active desktop"
policy — irrelevant to Acrylic, which we use.) Treat 26200 as compliant.

## Fix spec for Noah (one beat)

Root fix — make the QMainWindow client an alpha-carrying surface like the flat dialog does:

1. **Propagate the canvas prep to the central widget.** In `backdrop._prepare_window_canvas`
   (backdrop.py:203-216), when the window is a `QMainWindow`, also set
   `WA_TranslucentBackground` + transparent `Window` role on `window.centralWidget()`
   (`#mainShell`) — and clear it in `_clear_window_canvas` symmetrically. The child that
   covers the client must be translucent, or the top-level's translucency never reaches DWM.
2. **Force an ARGB window surface (belt-and-braces for the "QMainWindow has no alpha
   channel" quirk).** Once, before the main window is created (e.g. `main.py`/`tct_gui`
   startup), set a default `QSurfaceFormat` with `setAlphaBufferSize(8)` via
   `QSurfaceFormat.setDefaultFormat(...)`. This is the documented Qt remedy for QMainWindow
   translucency without a QOpenGLWidget (Qt forum #142890).
3. Keep opacity/ backdrop mutually-exclusive at the UI: when backdrop != "none", pin
   `setWindowOpacity(1.0)` (or disable the opacity slider) so the layered path can't silently
   kill the material (matrix row 4). Log the `apply_backdrop` HRESULTs at INFO so a silent
   rejection is visible in the log.
4. Do NOT extend the alpha to panel/card surfaces (ratified design; glass_gap_findings §3).
   Expected honest outcome after the fix: the main window blurs **in its exposed margins /
   inter-widget gaps only** (like the dialog) — the packed opaque panels still cover the bulk.

### How to verify blur is real (capture tool / Kaya)

- Blur is visually unambiguous: **desktop text/icons become unreadable/soft** through the
  window. "Crisp, readable desktop" = NOT blurred (current bug); "smeared frosted desktop
  color" = success.
- Discriminating test (run FIRST, decides cause #1 vs #2): is the crisp desktop visible
  **through panel/tab CONTENT** (a plot face, a card) → that's the opacity slider (#2, reset
  to 100%); or **only in the thin margins/gaps** around panels → that's the canvas passthrough
  with the material missing (#1, apply the fix above).
- After the fix: the main window's 12px outer margin + ribbon/tab gaps should frost like the
  theme-editor dialog's card margins do today. `none_*` vs `acrylic_*` onscreen captures
  should stop being pixel-identical in exactly those margin regions (offscreen still can't
  show DWM blur — compositor-side only).

## Sources

- DWM_SYSTEMBACKDROP_TYPE enum — https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type
- Apply Mica in Win32 desktop apps — https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-mica-win32
- System backdrops (Mica/Acrylic), WinUI — https://learn.microsoft.com/en-us/windows/apps/develop/ui/system-backdrops
- DwmExtendFrameIntoClientArea (negative margins = sheet of glass) — https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmextendframeintoclientarea
- Qt forum: WA_TranslucentBackground on Windows / QMainWindow needs alpha surface (QSurfaceFormat / QOpenGLWidget) — https://forum.qt.io/topic/142890 , https://forum.qt.io/topic/46849
- winmica (PyQt/PySide Mica via WA_TranslucentBackground + DwmSetWindowAttribute) — https://github.com/amnweb/winmica
- Qt 6.10.1 Mica "phantom white box" (stale backing, fixed by resize) — https://forum.qt.io/topic/163927
