# Apple Vibrancy / "Liquid Glass" in Qt — Feasibility for the Cockpit

**Date:** 2026-07-12  **Author:** Prometheus (researcher)
**Question:** How does Apple actually use translucency, what makes it read "sleek"
without blur, and what is genuinely achievable in a PySide6 (Qt Widgets/QSS + a
little QML) cockpit on Windows 11 — where is real translucency worth it and what
should we fake?
**Targets:** macOS 12–26 (AppKit `NSVisualEffectView`; "Liquid Glass" = macOS 26),
Qt 6.x / PySide6, Windows 11 (DWM system backdrops).
**Confidence:** mixed — Apple/Qt primary docs are *official docs*; macOS 26 Liquid
Glass and the 8pt/typography specifics are *secondary source*. Flagged per line.

---

## 1. How Apple actually uses translucency  *(official docs)*

- `NSVisualEffectView` = the one primitive: adds translucency + vibrancy + blur.
  Materials are chosen by **semantic role**, never by apparent color — the
  color-named cases (`light`/`dark`/`mediumLight`…) are deprecated. Role materials:
  `titlebar`, `menu`, `popover`, `sidebar`, `headerView`, `sheet`, `hudWindow`,
  `fullScreenUI`, `toolTip`, plus background materials `windowBackground`,
  `underWindowBackground`, `contentBackground`, `selection`. [1][2][9]
- **Two blending modes.** `behindWindow` blends/blurs with whatever is *behind the
  window* (desktop, other windows) — used for sidebars, HUDs, title bars.
  `withinWindow` blends with content *inside the same window* (e.g. an overlay HUD
  over a document). This is the load-bearing distinction: chrome uses behind-window;
  in-app overlays use within-window. [3][4]
- **Where Apple deliberately does NOT use it:** colorful content — photos, image
  views, data/plot surfaces — bypass vibrancy so colors stay accurate; custom
  RGB colors always render as-is; a plain content area is an opaque
  `windowBackground`, not glass. Vibrancy is a *chrome* effect, not a *content*
  effect. [1][5][9]
- **Vibrancy + text contrast:** legibility comes from (a) *vibrant* system colors
  layered on the material (auto-adapted so they never go too dark/bright), and
  (b) **material thickness** — thicker materials give better text contrast. HIG
  target is **4.5:1 text/background after blur**. Don't put arbitrary custom colors
  or fine text on thin glass. [5][6]
- **Reduce Transparency (accessibility):** materials automatically honor *Reduce
  Transparency*, *Reduce Motion* and *Increase Contrast*; under Reduce
  Transparency the glass collapses to an opaque solid. Practical pattern: ship a
  Default (glass) and a Fallback (≈opaque/20%-alpha solid) variant bound to the
  reduced-transparency flag and swap at runtime. **A translucent design must have a
  first-class opaque fallback or it fails accessibility.** [5][8]
- **macOS 26 "Liquid Glass" vs classic vibrancy** *(secondary):* real-time
  *refraction* of content behind the element (not just blur), specular highlights
  that react to motion, a darkened edge + brighter highlight for depth. Apple added
  a **translucency slider** (System Settings ▸ Appearance) because default glass hurt
  text legibility — i.e. Apple itself shipped a "make it more opaque" escape hatch
  after Tahoe backlash; macOS 27 is reportedly dialing it back further. Takeaway:
  even Apple treats aggressive translucency as a legibility risk to be tunable. [7][10][11]

## 2. What makes it read "sleek" *without* blur

Apple's "sleek" is mostly **not** the blur — it survives Reduce Transparency. The
recipe, with concrete numbers where sources give them:
- **Deference / quiet surfaces:** chrome recedes, content leads; large calm
  neutral fields, minimal ornament (Clarity / Deference / Depth). [12]
- **Hairline separators** instead of boxes/shadows — thin, low-alpha 1px (≈0.5px @2x)
  dividers do the structural work. [12]  *(our `hairline`/`edge`/`specular` tokens
  already do exactly this.)*
- **Type discipline:** one system family (SF Pro; our Windows analog is Segoe UI
  Variable), a small weight ladder (Ultralight→Black available, but hierarchy is
  built from a *few* weights + optical size, not many faces), sentence case, tabular
  numerals for values. [13][14]
- **8pt spacing rhythm** (4pt subdivisions), 44pt min hit target — a reliable
  convention that matches Apple output. [12]  *(our SPACE 4/8/12/16/24 already
  follows this.)*
- **Depth from a surface ladder + one subtle specular top edge**, restrained
  shadows, a slight saturation lift on vibrant colors over glass — not drop-shadow
  soup. [5][7]

Net: our design system §2 ("surface ladder + hairlines + one frosted chrome strip;
no drop-shadow soup; radii 8/12/16") is already the correct Apple recipe. The blur
is the *last 10%*, and the optional 10%.

## 3. Qt feasibility (Windows 11, perf-honest)

**Qt Widgets / QSS — real blur is impossible; pre-blended fakes are the answer.**
- The Qt Style Sheets reference supports only CSS2 box-model props (background*,
  border*, border-radius, border-image, margin/padding). **No `filter`, no
  `backdrop-filter`, no blur.** [15]  A QSS widget can never sample pixels behind it.
- What *is* achievable and is what we already do in `gui/style.py`: **pre-blended
  color-mix tokens** — `_blend()` resolves an opaque hex approximating "panel-2 over
  panel," `chrome = blend(panel_2, panel, .74)`, translucent `rgba()` fills, a
  lighter `edge` top border faking an inset specular. This *reads* frosted without
  compositing. (Real backdrop blur behind a QWidget would need `QGraphicsBlurEffect`
  on a grabbed pixmap — a hot-path repaint cost our law 8 forbids on plots.)

**Qt Quick / QML — real blur possible, but snapshot-once, not live.**
- `MultiEffect` (Qt 6, successor to GraphicalEffects) does real Gaussian-ish blur in
  one pass; **blur+shadow are its heaviest ops.** Guidance: prefer raising
  `blurMultiplier` over `blurMax`, keep the effect item small (fewer pixels), and
  **avoid animating source items** so the blur isn't regenerated every frame. [16][17]
- Qt's own "blurred panels" recipe: **blur the content behind, captured via
  `ShaderEffectSource` with a tight `sourceRect`, `autoPaddingEnabled: false`,
  `blurMax: 64–80`** — i.e. grab a snapshot and blur it, re-grabbing only when the
  background actually changes. [18]  This is exactly the **"grab + blur once"**
  static-background approach, and it is the right call for us: a QQuickWidget
  frosted strip over a *static* backdrop is cheap; blurring live pyqtgraph frames
  is not (per-frame re-grab of an animating source is the pattern Qt says to avoid).
- Cost on an embedded `QQuickWidget` in a QWidget app is a real render-target +
  extra pass per repaint of the effect; fine for small static chrome, wrong for any
  hot path.

**Windows 11 DWM Mica/Acrylic backdrop — feasible per top-level window, with fights.**
- `DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_MAINWINDOW|…)` on
  `winId()` enables Mica/Acrylic; also set `DWMWA_USE_IMMERSIVE_DARK_MODE` for dark.
  [19]  Proven in Python-Qt by **`winmica`** (PyQt6; PySide6 "untested" but the API
  is identical). [20]
- **Pitfalls:** it works **per top-level window only** (not per-panel), so it only
  reaches the main window frame / title-bar zone, not inner cards. It requires
  `WA_TranslucentBackground`, and in **Qt 6 that flag effectively needs a frameless
  window** (a regression from Qt5); on a normal window it yields a black/opaque
  backdrop that won't composite with Mica. Any **opaque widget painting on top hides
  the backdrop** — so every widget over the Mica zone must be transparent, which
  fights our solid ISA-101 panels. Community reports "phantom white/black box"
  artifacts (Qt 6.10). [19][20][21]  Verdict: high-effort, brittle, and it only
  frosts the outer frame — low value for a docked multi-panel cockpit.

## 4. Verdict for us

1. **Keep faking it in QSS.** Our `_blend()`/`chrome`/`edge`/`specular` pre-blended
   tokens already deliver the Apple "sleek" that survives Reduce Transparency — that
   is 90% of the look and costs zero paint budget. Do not chase real blur here.
2. **One place real translucency earns its keep:** the outer chrome only — the
   frosted rail / top ribbon / status strip — as a **QML `MultiEffect` blur of a
   snapshotted static backdrop** (Qt's `ShaderEffectSource` recipe), *if* we already
   own a QQuickWidget there. Grab-and-blur-once, re-grab only on resize/theme change.
3. **Never over a plot or a hot path.** pyqtgraph canvases, the camera view, and any
   ticking panel stay **fully opaque** (design law 8; §2 "nothing translucent over a
   plot"). No `QGraphicsBlurEffect`/`MultiEffect` on animating sources.
4. **Skip DWM Mica/Acrylic** for now: per-top-level-window only, fights opaque
   panels and the Qt6 frameless/translucent regression — high risk, frames only the
   outer window, not our docked cards.
5. **Mandatory opaque fallback + contrast floor.** Whatever we frost must have an
   opaque variant (a "reduce transparency"/legibility toggle), and text over any
   glass must clear **4.5:1** — same discipline Apple itself retreated to with the
   Liquid Glass translucency slider.

---

## Sources

1. [NSVisualEffectView — Apple Developer](https://developer.apple.com/documentation/appkit/nsvisualeffectview) *(official docs)*
2. [NSVisualEffectView.Material — Apple Developer](https://developer.apple.com/documentation/appkit/nsvisualeffectview/material) *(official docs)*
3. [BlendingMode — Apple Developer](https://developer.apple.com/documentation/appkit/nsvisualeffectview/blendingmode) *(official docs)*
4. [BlendingMode.behindWindow — Apple Developer](https://developer.apple.com/documentation/appkit/nsvisualeffectview/blendingmode/behindwindow) *(official docs)*
5. [Materials — Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/materials) *(official docs)*
6. [Sufficient Contrast evaluation criteria — Apple Developer](https://developer.apple.com/help/app-store-connect/manage-app-accessibility/sufficient-contrast-evaluation-criteria) *(official docs)*
7. [Apple introduces a new software design (Liquid Glass) — Apple Newsroom](https://www.apple.com/newsroom/2025/06/apple-introduces-a-delightful-and-elegant-new-software-design/) *(official, marketing)*
8. [Liquid Glass: accessibility guidance — designed for humans](https://designedforhumans.tech/blog/liquid-glass-smart-or-bad-for-accessibility) *(secondary source)*
9. [Dark Side of the Mac: Appearance & Materials — mackuba.eu](https://mackuba.eu/2018/07/04/dark-side-mac-1/) *(secondary source)*
10. [All the Liquid Glass Changes in macOS — MacRumors](https://www.macrumors.com/2026/06/09/macos-golden-gate-liquid-glass/) *(secondary source)*
11. [Apple to refine macOS 27 Liquid Glass after backlash — MacDailyNews](https://macdailynews.com/2026/05/11/apple-to-refine-macos-27-with-liquid-glass-design-tweaks-after-macos-26-tahoe-backlash/) *(secondary source)*
12. [How Apple Designs Their UI — Superdesign (2026)](https://superdesign.dev/blog/apple-design-system) *(secondary source)*
13. [Fonts (SF Pro) — Apple Developer](https://developer.apple.com/fonts/) *(official docs)*
14. [Meet the expanded San Francisco font family — WWDC22](https://developer.apple.com/videos/play/wwdc2022/110381/) *(official docs)*
15. [Qt Style Sheets Reference — Qt 6](https://doc.qt.io/qt-6/stylesheet-reference.html) *(official docs)*
16. [MultiEffect QML Type — Qt 6](https://doc.qt.io/qt-6/qml-qtquick-effects-multieffect.html) *(official docs)*
17. [FastBlur QML Type (Qt5Compat) — Qt 6](https://doc.qt.io/qt-6/qml-qt5compat-graphicaleffects-fastblur.html) *(official docs)*
18. [Qt Quick and Blurred Panels — Qt Blog](https://www.qt.io/blog/qt-quick-and-blurred-panels) *(official docs)*
19. [System backdrops (Mica/Acrylic) — Microsoft Learn](https://learn.microsoft.com/en-us/windows/apps/develop/ui/system-backdrops) *(official docs)*
20. [winmica — Windows 11 Mica for PyQt6 (GitHub)](https://github.com/amnweb/winmica) *(secondary source)*
21. [Phantom white box: Mica on QML Qt 6.10 — Qt Forum](https://forum.qt.io/topic/163927/) *(secondary source)*
