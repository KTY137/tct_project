# RB-GLASS-01 — Prior art: shipping Mica/Acrylic-class glass through complex UI stacks

**Author:** Frigg (Glass Council, internet-research lane) · **Date:** 2026-07-13
**Method:** Web research, primary sources only (vendor docs, bug trackers, product
source). Every claim below carries a citation; where evidence is a *null result*
(nothing found), that is stated explicitly as a finding, not silence.
**Scope:** How real products attach Windows 11 DWM materials through complex UI
stacks (Windows Terminal, WinUI 3, Firefox, Electron/VS Code, WPF), the Qt-specific
failure modes (bug tracker + forums), QtAds prior art, and how Qt Quick/QML apps do
it. Feeds the council's mechanism/degradation-ladder decision; per protocol this
brief **informs** the design, it does not pick it.

---

## 0. Executive verdict (evidence summary)

1. **The DWM material is painted by the compositor *behind* the window; every layer
   the framework paints on top must be transparent, or the material is invisible.**
   Microsoft states this as the contract for its own framework: "Mica will only
   appear if all layers between the UI element and the window are set to
   transparent" [S1]. The tct afternoon finding (opaque QSS rule defeating the
   backdrop) is exactly this contract being violated — every framework in this
   brief hit the same wall.
2. **No mainstream product ships per-pixel DWM glass under a dense, fully-painted
   client area.** The products that ship Mica (Terminal, Files/WinUI 3, Firefox)
   show it in *chrome zones* — titlebar, tab row, nav panes, margins — and keep
   content surfaces opaque. Microsoft's own design guidance explicitly says
   "**Don't** put desktop acrylic on large background surfaces of your app" [S3].
3. **Everyone that tried shipped a long tail of lifecycle bugs** — white/stale
   regions on first paint (Firefox [S10], Qt QML [S26]), material lost on
   minimize/maximize (Electron [S13][S14][S15]), crashes dragging between monitors
   (WinUI 3 itself [S42]), app-won't-launch (Terminal [S6]). Glass is not a
   set-and-forget attribute; it needs lifecycle re-assertion and regression tests.
4. **Qt has no official system-backdrop API** (QtWinExtras was dropped in Qt 6
   [S27]); all Qt prior art is raw `DwmSetWindowAttribute` plus community
   frameless-window libraries, of which the most mature (qwindowkit) still marks
   its mica/acrylic attributes **experimental** [S30].
5. **QtAds null result:** a GitHub issue search of the QtAds tracker for
   transparent/translucent/acrylic finds *zero* Windows-material items (only Linux
   compositor issues [S37][S38]). Nobody has publicly shipped DWM glass through a
   QtAds dock stack. The council would be first — plan margins accordingly.
6. **The most popular QML Fluent library fakes Mica**: zhuzichu520/FluentUI's
   `FluWindow` loads the desktop **wallpaper image** and blurs it in-shader
   (`FluAcrylic` over a hidden `Image` of `FluTheme.desktopImagePath`) instead of
   using DWM at all [S32][S33]. The "honest fake" is not a compromise position —
   it is the *established* position in the Qt ecosystem.
7. **The WHITE-window symptom has two documented prior-art causes** (§6): Mica
   genuinely renders near-white when the window's dark-mode flag
   (`DWMWA_USE_IMMERSIVE_DARK_MODE`) is unset/lost [S21][S39][S40], and
   stale-buffer/invalidation bugs that leave white regions until a resize or
   minimize forces a repaint — shipped by Firefox 133 [S10] and reproduced on Qt
   6.10.1 QML [S26].

---

## 1. The universal contract (Microsoft's own framework)

Microsoft Learn, *System backdrops (Mica/Acrylic)* [S1] and *Mica material* [S2]:

- **Draw order:** the backdrop is a composition brush rendered *behind* the whole
  window; WinUI 3 apps opt in via `Window.SystemBackdrop = MicaBackdrop /
  DesktopAcrylicBackdrop`, or at a lower level via the Composition
  `MicaController` / `DesktopAcrylicController` targeting anything implementing
  `ICompositionSupportsSystemBackdrop` [S1].
- **Transparency chain:** the material shows only where *every* layer above it is
  transparent. WinUI templates arrange this; any opaque background anywhere in the
  tree occludes it [S1][S2]. For title bars, Microsoft's guidance is to extend
  content into the non-client area and make the titlebar transparent [S2].
- **Region-level glass exists — as the app's own blur, not DWM's.** For "glass on
  a card/panel", the current API is `SystemBackdropElement` (bounded backdrop
  region) [S1] and, longer-standing, **in-app acrylic**, which blurs *the app's
  own content* rather than other windows/desktop [S3]. This is Microsoft's answer
  to per-panel glass over app content — precisely the role a QML per-item layer
  effect would play in the U-track shell.
- **Cost model:** Mica samples the wallpaper **once** — near-zero ongoing GPU cost,
  recommended as the app's base layer; Acrylic is a live blur, "GPU-intensive",
  reserved for transient surfaces [S2][S3].
- **The degradation ladder is system policy, not app code:** acrylic falls back to
  a solid fill when the user turns off *Transparency effects*, in Battery Saver,
  on low-end hardware, in High Contrast; background acrylic additionally drops to
  solid when the window deactivates [S3]. Controllers expose
  `IsSupported()`/`FallbackColor` so the app always has a deterministic solid-color
  end state [S1]. **Implication:** any design that only looks right *with* the
  material is wrong by Microsoft's own rules — the pre-blended-token fallback the
  tct crew already ratified is the same architecture Microsoft mandates.

## 2. Windows Terminal — glass through a real, complex app

Terminal (Win32 + XAML Islands + custom DX text renderer) is the closest thing to
a "cockpit" shipping Mica:

- Mica is a **theme property** (`theme.window.useMica`), requires Windows build
  ≥ 22621, and the docs tell users to set layers above it transparent — e.g.
  `unfocusedBackground: "#00000000"` on tab/tabRow "for the best visual results"
  [S4]. Same transparency-chain contract as §1, surfaced as user configuration.
- The theming/Mica design went through a full spec PR (#12530) rather than a flag
  drop [S8] — evidence this is an architecture decision, not a tweak.
- **Failure tail:** tab row rendering fully transparent with Mica on 21H2 [S5];
  `useMica` themes making the app fail to launch (closed duplicate — a known bug
  class) [S6]; users unable to get Mica at all [S7]; `useAcrylicInTabRow`
  silently overriding tabRow colors [S9]. The docs concede constraint coupling:
  an unblurred transparent background and Mica tabs are not simultaneously
  possible [S4].
- Terminal's *content-area* transparency is its own renderer's alpha, not DWM
  Mica — the same division of labor as WezTerm, whose `win32_system_backdrop`
  option documents Acrylic/Mica/Tabbed for a GPU-rendered client area [S23], and
  as the Win32 per-pixel-alpha reference demos (black class brush +
  `DwmEnableBlurBehindWindow` + premultiplied-alpha swapchain) [S43][S44].
  **Implication:** in every working case, the *app renderer* owns an alpha
  channel end-to-end; the material is composited by the OS underneath it.

## 3. Firefox — the closest analog to Qt (own widget toolkit, own compositor)

Bugzilla 1764822 [S10] is the single most transferable case study: a non-UWP,
non-XAML app with its own rendering pipeline attaching Mica.

- Mechanism: plain `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE)` on the
  toplevel, behind pref `widget.windows.mica`; **no** WinRT composition controllers.
- It required *prerequisite infrastructure*: dedicated fixes for transparent
  window handling (bug 1911763) and dynamic titlebar color-scheme updates (bug
  1923334) before Mica could work at all [S10].
- Shipped in Firefox 133 (tracker: fixed), followed by a **meta-bug (1934143)**
  collecting the fallout: *completely white tab-bar backgrounds until a
  resize/repaint*, invisible window-control buttons depending on theme/window
  state, and transparency failing entirely when the GPU process is disabled
  [S10]. **Implication:** even a compositor-owning giant shipped the exact WHITE
  symptom tct saw tonight, plus a software-path failure — the degradation ladder
  (GPU off/RDP) is where glass dies first, and it must be tested, not assumed.

## 4. Electron / VS Code — the cautionary tail

- Electron gained `backgroundMaterial: 'mica'|'acrylic'|'tabbed'` via PR #38163
  (Windows 11 22H2+) [S11], needed a follow-up fix for frameless windows [S12],
  and still carries an open bug tail: maximizing a frameless window permanently
  breaks the material (black background, lost rounded corners/shadow) [S13],
  maximized-window material bugs [S14], material lost after minimize [S15],
  client-area enablement failing [S16], no Win10 support [S17], and
  maximize/restore corner+material inconsistencies [S18]. **Implication:** window
  state transitions (minimize/maximize/restore/monitor-change) are the regression
  surface; the pixel harness should capture *after* state round-trips, not just at
  steady state. WinUI 3 itself had a Mica crash when dragging between monitors
  [S42] — this bug class is universal.
- **VS Code has never shipped it.** The Mica/blur request (#141827) sits
  unimplemented; the community answer is `vscode-vibrancy-continued`, which
  patches VS Code's installation files (checksum-breaking, "unsupported, may be
  buggy", broken repeatedly by updates) [S19][S20]. **Implication:** the most
  complex Electron app in the world looked at this cost/benefit and declined —
  "minimal honest glass + robust fallback" has precedent as the *rational* choice
  for dense professional tools.

## 5. WPF + external shims — the "framework paints opaque" problem is old

- WPF (like Qt: a framework that paints the entire client area) attaches Mica by
  setting the Window background to `Transparent`, extending the glass frame
  (`WindowChrome GlassFrameThickness="-1"`), and calling `DwmSetWindowAttribute`
  — with `DWMWA_USE_IMMERSIVE_DARK_MODE` applied **before** the backdrop to avoid
  a white flash, and re-applied on every theme change [S21]. Older builds needed
  the undocumented `DWMWA_MICA_EFFECT (1029)`; ≥22523 uses public
  `DWMWA_SYSTEMBACKDROP_TYPE (38)` [S21].
- **MicaForEveryone** proves the attribute-only reality from outside: it sets
  `DWMWA_SYSTEMBACKDROP_TYPE` on arbitrary Win32 apps, and the material shows on
  the **frame/titlebar only** — the client area stays whatever the app paints; an
  "Extend Frame Into Client Area" option exists for apps whose backgrounds can
  tolerate it [S22]. **Implication:** the attribute is never the hard part; the
  app's own opaque paint is. tct's `gui/backdrop.py` chain was already correct in
  kind — the QSS canvas rule was the occluder, exactly as this model predicts.

## 6. Diagnostic leads for the WHITE symptom (direct prior art)

Two independent, documented mechanisms produce "backdrop region renders white":

1. **Light-mode Mica is near-white by design.** Mica derives from wallpaper +
   theme; without `DWMWA_USE_IMMERSIVE_DARK_MODE` the brush renders in light
   mode, and multiple implementers describe it as white/ugly until the dark-mode
   flag is set — and set *before* the backdrop type to avoid the white flash
   [S21][S40]. The flag's semantics are titlebar/backdrop theming, set per-window
   via `DwmSetWindowAttribute(20)` [S39]. A lost/reset dark-mode flag (e.g. a
   window recreated by toggling window flags, or re-styling that re-creates the
   platform window) silently reverts Mica to white. **This matches the brief's
   "light-mode Mica = looks white" suspect and is the cheapest hypothesis to
   test.**
2. **Stale-buffer/invalidation bugs render white until forced repaint.** Firefox
   133 shipped "completely white tab bar until resize/repaint" [S10]; Qt 6.10.1
   QML + Mica shows a *phantom white box at the initial window size* that
   survives resizing and clears only after minimize-restore — i.e. a graphics
   buffer that never got invalidated, machine-dependent (a second user could not
   reproduce) [S26]. **Implication:** capture-based regression tests must include
   first-show, resize, and minimize-restore frames; a single steady-state
   screenshot can miss both bugs.

## 7. Qt Widgets — what the tracker and docs actually say

- **No official API.** QtWinExtras (which had `DwmFeatures`) was removed in Qt 6
  [S27]; nothing replaced it for system backdrops. All Qt Mica/acrylic work is
  raw `DwmSetWindowAttribute` on `winId()` — as tct already does.
- **The documented translucency contract** (QWidget docs, *Creating Translucent
  Windows*): set `Qt::WA_TranslucentBackground` and paint with non-opaque colors;
  **"On Windows the widget needs to have the Qt::FramelessWindowHint window flag
  set for the translucency to work"** [S24]. In practice on Qt 6, a framed window
  with `WA_TranslucentBackground` stays black/opaque unless something forces an
  alpha channel into the window's surface — community workarounds: add a
  `QOpenGLWidget` (forces an alpha-capable surface, ~50 MB cost), or frameless;
  a plain `QSurfaceFormat::setDefaultFormat` alpha was reported *insufficient*
  by itself for the widget backing-store path [S25]. **Implication for tct:**
  the classic QWidget shell's translucency rests on partially documented
  behavior — the exact combination (framed window + backing store alpha + DWM
  backdrop) is off Qt's paved road, which is consistent with it "working once,
  then breaking."
- `WA_TranslucentBackground` also interacts with `autoFillBackground` /
  `WA_OpaquePaintEvent` / `WA_NoSystemBackground` — Qt fills the background from
  the palette before paint unless told otherwise, so palette *and* QSS must agree
  on non-opaque fills [S24] (the afternoon's root cause, confirmed independently).
- **Layered windows kill it:** `setWindowOpacity` ⇒ `WS_EX_LAYERED` ⇒ DWM
  backdrop suppressed — tct discovered this (opacity pin); the Win32 reference
  demos document layered windows as a *separate, incompatible* transparency
  mechanism from DWM composition alpha [S43][S44]. Regression-guard the pin.
- **Historical QQuick counterpart:** "Cannot make transparent background for
  QQuickView" was a long-lived tracker item [S28] — Qt window-alpha has been
  fragile on Windows across eras; treat every Qt upgrade as a re-verification
  point.
- **Qt 6.9+ finally moved toward this space:** `Qt::ExpandedClientAreaHint`
  (client area extends under the titlebar) and `Qt::NoTitleBarBackgroundHint`
  (no titlebar background fill) are official, Windows-supported window flags
  [S29a][S29b]. On PySide6 6.11 these are available and are the sanctioned way
  to get the "material flows through the titlebar" look WinUI describes [S2] —
  relevant to both the classic shell's chrome and the QML shell.
- **Community libraries:**
  - **qwindowkit** (successor to FramelessHelper [S31]) exposes
    `setWindowAttribute("mica"|"mica-alt"|"acrylic"|"dark-mode")` for Widgets and
    Quick — but the README marks the whole section **experimental** (example code
    commented out), with known interactions with the OS "accent color on title
    bars" setting [S30]. The best-maintained Qt glass code in existence does not
    yet call this production-ready.
  - **PyQt/PySide6-Fluent-Widgets + PyQt-Frameless-Window** (zhiyiYo): direct
    PySide6 prior art — `FramelessWindow`/`FramelessMainWindow` "supports Win11
    mica blur" via `windowEffect.setMicaEffect(self.winId())`; documented caveat
    that acrylic windows stutter when moved on Win10 with "no good solution"
    [S35][S36]. Worth reading their WindowsWindowEffect source for the exact
    attribute/ordering recipe that works on PySide6.

## 8. QtAds — the null result, and the actual barrier

- **Nobody has publicly pushed DWM materials through QtAds.** GitHub issue search
  across the QtAds tracker for transparent/translucent/acrylic-in-title returns
  zero Windows items [S37]; the only transparency-adjacent issues are Linux
  compositor problems (dark/black windows while dragging with compositing off
  [S38a], black main window on i3wm/x2go [S38b]) — which are themselves useful:
  QtAds *assumes* a compositor for its translucent drag previews, and degrades
  badly without one. The RDP/software rung of the ladder needs explicit testing
  with QtAds in the loop.
- **QtAds ships its own auto-loaded default stylesheet** (light/dark, follows the
  palette) styling splitters, tabs, buttons, titlebars — i.e. opaque
  `background` fills on its containers that the app's QSS never wrote. The
  documented off-switches: `setStyleSheet("")` on the dock manager or the
  `DisableStyleheet` (sic) config flag, then style ADS widgets yourself [S37b].
  **This is the likely concrete mechanism behind the brief's "dock containers
  paint opaque backgrounds our QSS canvas rules never reach"** — the fix is a
  config flag + owning the ADS selectors in `style.py`, not fighting specificity.
- Floating docks are separate native toplevels (`FloatingContainer*` flags,
  native vs QWidget titlebars) [S37b] — each detached window needs its own
  backdrop attach + dark-mode flag, which tct's fan-out already does; keep it
  that way after re-docking/re-floating (window recreation loses DWM state, §6).

## 9. Qt Quick / QML — how glass actually attaches there

- **Mechanics:** `QQuickWindow::setDefaultAlphaBuffer(true)` before window
  creation, window `color: "transparent"`, then the scenegraph clears to
  transparent and per-pixel alpha reaches DWM [S41][S26]. Combined with
  `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE)` this demonstrably renders
  real Mica behind a QML scene on Qt 6.10.1 — the forum thread's problem was a
  stale-buffer artifact, not the material failing [S26]. The RHI/D3D swapchain
  path gives QML exactly the "renderer owns alpha end-to-end" property that §2's
  working products share — this is why the brief's premise "QML makes real glass
  easier" is supported by the evidence.
- **Qt 6.9+ window hints** (§7) extend the QML window's background to the full
  frame while keeping content in safe areas — the sanctioned edge-to-edge look
  [S29a][S29b].
- **The biggest QML Fluent library chose the fake.** FluentUI's
  `blurBehindWindowEnabled` renders a hidden `Image` of the *desktop wallpaper*
  (`FluTheme.desktopImagePath`) and blurs it with its own `FluAcrylic` effect —
  no DWM involvement; and enabling it turns the native effects path off
  [S32][S33]; same library ships for PySide6 [S34]. That is: wallpaper-sample +
  in-app blur ≈ self-made Mica, fully portable, RDP-safe, identical on Linux.
  **Implication:** a static-source blur (wallpaper or a pre-rendered backdrop
  texture) is a *cheap, once-per-theme-change* operation — unlike live acrylic —
  and the ecosystem's most-starred QML design system considers it good enough to
  ship as its default "Mica".
- Per-panel glass over *app content* in QML = `layer.enabled` + a blur effect —
  which is in-app acrylic in Microsoft's taxonomy (§1) and inherits its cost
  warning ("GPU-intensive", never on large surfaces) [S3]; consistent with the
  council's ratified "no live shader glass on the software path" constraint —
  degradation to pre-blended tokens mirrors Microsoft's own solid-fallback policy.

## 10. Implications for the three horizons (evidence → design inputs)

*(Frigg informs, the council decides.)*

1. **Classic QWidget shell (today):** prior art supports *window-level material +
   opaque content zones* only — the WinUI guidance [S3], Terminal's zone model
   [S4], MicaForEveryone's frame-only reality [S22], and VS Code's refusal [S19]
   all point the same way. The two robustness musts from the field: (a) pin
   `DWMWA_USE_IMMERSIVE_DARK_MODE` before/with every backdrop attach and re-assert
   after any window recreation (§6); (b) add first-show/resize/minimize-restore
   frames to the pixel harness (§4, §6). QtAds's own stylesheet is the remaining
   occluder to own via `DisableStyleheet`/selector ownership (§8).
2. **QML shell (U-track):** the working recipe is documented and small —
   default alpha buffer + transparent window color + DWM attribute + 6.9 window
   hints (§9) — and it is exactly where Firefox/Terminal-class apps ended up:
   renderer-owned alpha over an OS-composited material. Known artifact to test
   for: the initial-size white-box buffer bug [S26].
3. **Seed / token contract:** every shipping implementation is forced into the
   same shape Microsoft codified — material + tint/luminosity parameters + a
   **solid fallback color that is always defined** [S1][S3]. A token vocabulary of
   `(backdrop_kind, tint, tint_opacity, fallback_solid)` per surface class matches
   WinUI's controller properties 1:1 and degrades to today's pre-blended tokens by
   construction. FluentUI's wallpaper-blur fake [S33] is prior art for a *middle*
   rung on the ladder (between real DWM and flat tokens) if the council wants one:
   static-source blur, computed once, no live shader.

---

## Sources

Product / platform:
- [S1] Microsoft Learn — System backdrops (Mica/Acrylic), Windows App SDK: https://learn.microsoft.com/en-us/windows/apps/develop/ui/system-backdrops
- [S2] Microsoft Learn — Mica material: https://learn.microsoft.com/en-us/windows/apps/design/style/mica
- [S3] Microsoft Learn — Acrylic material (blend types, fallback policy, do's/don'ts): https://learn.microsoft.com/en-us/windows/apps/design/style/acrylic
- [S4] Microsoft Learn — Windows Terminal theme settings (useMica, unfocusedBackground): https://learn.microsoft.com/en-us/windows/terminal/customize-settings/themes
- [S5] microsoft/terminal#15435 — tab row 100% transparent with Mica (21H2): https://github.com/microsoft/terminal/issues/15435
- [S6] microsoft/terminal#16074 — "Is `mica` dead?" (app fails to launch, closed dup): https://github.com/microsoft/terminal/issues/16074
- [S7] microsoft/terminal#14727 — Can't use Mica: https://github.com/microsoft/terminal/issues/14727
- [S8] microsoft/terminal PR #12530 — draft spec for theming, Mica: https://github.com/microsoft/terminal/pull/12530
- [S9] microsoft/terminal#19604 — useAcrylicInTabRow overrides tabRow: https://github.com/microsoft/terminal/issues/19604
- [S10] Mozilla Bugzilla 1764822 — Implement Windows 11 Mica for the title bar (landed Fx133; white tab bar, GPU-process failures; meta 1934143): https://bugzilla.mozilla.org/show_bug.cgi?id=1764822
- [S11] electron/electron PR #38163 — feat: support Mica/Acrylic on Windows: https://github.com/electron/electron/pull/38163
- [S12] electron/electron PR #39708 — fix: frameless mica/acrylic windows: https://github.com/electron/electron/pull/39708
- [S13] electron/electron#41824 — maximizing frameless window with Mica permanently breaks it: https://github.com/electron/electron/issues/41824
- [S14] electron/electron#42393 — maximized window with backgroundMaterial: https://github.com/electron/electron/issues/42393
- [S15] electron/electron#38743 — background material broken after minimize: https://github.com/electron/electron/issues/38743
- [S16] electron/electron#38454 — cannot enable background material for client area: https://github.com/electron/electron/issues/38454
- [S17] electron/electron#48440 — acrylic backgroundMaterial doesn't work on Windows 10: https://github.com/electron/electron/issues/48440
- [S18] electron/electron#46753 — material + rounded-corner inconsistencies on maximize/restore: https://github.com/electron/electron/issues/46753
- [S19] microsoft/vscode#141827 — Mica/blur support request (unimplemented): https://github.com/microsoft/vscode/issues/141827
- [S20] vscode-vibrancy-continued — community patcher (unsupported install-file patching): https://github.com/illixion/vscode-vibrancy-continued
- [S21] tvc-16.science — Apply Mica to a WPF app (transparent Window, dark-mode-before-backdrop, 1029 vs 38): https://tvc-16.science/mica-wpf.html
- [S22] MicaForEveryone — backdrop on titlebars of arbitrary Win32 apps; Extend-Frame option: https://github.com/MicaForEveryone/MicaForEveryone
- [S23] WezTerm — win32_system_backdrop (Acrylic/Mica/Tabbed with GPU-rendered content): https://wezterm.org/config/lua/config/win32_system_backdrop.html

Qt core:
- [S24] Qt 6 QWidget docs — Creating Translucent Windows (Windows: FramelessWindowHint note; autoFillBackground interplay): https://doc.qt.io/qt-6/qwidget.html
- [S25] Qt Forum — WA_TranslucentBackground on Windows without FramelessWindowHint (black/opaque symptom; QOpenGLWidget alpha workaround): https://forum.qt.io/topic/142890/how-to-make-wa_translucentbackground-work-on-windows-without-using-framelesswindowhint
- [S26] Qt Forum — Phantom white box with ApplicationWindow + Windows 11 Mica, Qt 6.10.1 (stale buffer, clears on minimize): https://forum.qt.io/topic/163927/phantom-white-box-whilst-using-application-window-and-windows-11-mica-background-on-qml-qt-6.10.1
- [S27] QTBUG-89564 — Clean up QtWinExtras for Qt 6 (DWM helpers removed, no replacement): https://bugreports.qt.io/browse/QTBUG-89564
- [S28] QTBUG-28214 — Cannot make transparent background for QQuickView (historical Windows alpha fragility): https://bugreports.qt.io/browse/QTBUG-28214
- [S29a] Qt — What's New in Qt 6.9 (ExpandedClientAreaHint, NoTitleBarBackgroundHint; Windows supported): https://doc.qt.io/qt-6/whatsnew69.html
- [S29b] Qt blog — Expanded Client Areas and Safe Areas in Qt 6.9: https://www.qt.io/blog/expanded-client-areas-and-safe-areas-in-qt-6.9
- [S41] Qt 6 QQuickWindow docs — setDefaultAlphaBuffer / setColor(transparent): https://doc.qt.io/qt-6/qquickwindow.html
- [S42] microsoft/microsoft-ui-xaml#7079 — Mica backdrop crash when dragging window between monitors: https://github.com/microsoft/microsoft-ui-xaml/issues/7079

Qt community solutions:
- [S30] stdware/qwindowkit — mica/mica-alt/acrylic/dark-mode window attributes (experimental): https://github.com/stdware/qwindowkit
- [S31] wangwenx190/framelesshelper — project moved to qwindowkit: https://github.com/wangwenx190/framelesshelper
- [S32] zhuzichu520/FluentUI — QML Fluent library (FluTheme.blurBehindWindowEnabled): https://github.com/zhuzichu520/FluentUI
- [S33] FluWindow.qml source — wallpaper Image + FluAcrylic in-shader blur, native effects disabled when active: https://github.com/zhuzichu520/FluentUI/blob/main/src/Qt6/imports/FluentUI/Controls/FluWindow.qml
- [S34] zhuzichu520/PySide6-FluentUI-QML — same library for PySide6: https://github.com/zhuzichu520/PySide6-FluentUI-QML
- [S35] zhiyiYo/PyQt-Fluent-Widgets (PySide6 branch) — Fluent widgets, Win11 mica support: https://github.com/zhiyiYo/PyQt-Fluent-Widgets
- [S36] zhiyiYo/PyQt-Frameless-Window — PySide6 frameless base, setMicaEffect(winId); Win10 acrylic-move caveat: https://github.com/zhiyiYo/PyQt-Frameless-Window

QtAds:
- [S37] GitHub issue search, QtAds repo, transparent/translucent/acrylic in title — **0 results** (queried 2026-07-13 via api.github.com/search/issues, repo:githubuser0xFFFF/Qt-Advanced-Docking-System)
- [S37b] QtAds user guide — default auto-loaded stylesheet, DisableStyleheet flag, FloatingContainer title/native flags: https://github.com/githubuser0xFFFF/Qt-Advanced-Docking-System/blob/master/doc/user-guide.md
- [S38a] QtAds#95 — dark window when dragging without compositing (Linux): https://github.com/githubuser0xFFFF/Qt-Advanced-Docking-System/issues/95
- [S38b] QtAds#485 — main window black while moving dock (i3wm/x2go): https://github.com/githubuser0xFFFF/Qt-Advanced-Docking-System/issues/485

Dark-mode / white-Mica leads:
- [S39] Microsoft Q&A — DWMWA_USE_IMMERSIVE_DARK_MODE semantics: https://learn.microsoft.com/en-us/answers/questions/966330/dwmwa-use-immersive-dark-mode-confusion
- [S40] HandyOrg/HandyControl#1032 — WPF Mica feature request (dark-mode flag forces Mica dark; white otherwise): https://github.com/HandyOrg/HandyControl/issues/1032

Win32 mechanics:
- [S43] jeweg/win32-window-transparency — per-pixel alpha reference demos (DWM composition vs layered windows): https://github.com/jeweg/win32-window-transparency
- [S44] selastingeorge/Win32-Acrylic-Effect — Win32 acrylic via DWM/DirectComposition: https://github.com/selastingeorge/Win32-Acrylic-Effect
