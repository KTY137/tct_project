# Ratatoskr — Win32/DWM API ground truth (Glass Council lane)

Ratatoskr, Endpoint & Systems (NorthStar council, on loan). The squirrel runs
the tree and carries the message exactly as it was spoken — every load-bearing
claim below is cited to Microsoft docs or named, credible reverse-engineering.
Where a claim is community-RE rather than documented, it is labeled as such.
project_tct read-only; this file is the only deliverable.

Grounding read: `TCT_app/gui/backdrop.py` (the app's DWM chain),
`TCT_app/gui/style.py` (opacity pin, palette backstop), `TCT_app/main.py`
(QSurfaceFormat alpha), `docs/design/glass_gap_findings.md`.

---

## 0. Verdicts up front

1. **WHITE symptom** — the window is registered **LIGHT with DWM**.
   `gui/backdrop.py` sets `DWMWA_SYSTEMBACKDROP_TYPE` (38) but **never sets
   `DWMWA_USE_IMMERSIVE_DARK_MODE` (20)**, and per Microsoft's own docs *"For
   compatibility reasons, all windows default to light mode regardless of the
   system setting"* ([DWMWINDOWATTRIBUTE]). The DWM material's tint follows
   that per-window flag (§2). A light-flagged window gives you: **light-mode
   Mica/Acrylic live (whitish, wallpaper-bleached) AND a near-white solid
   fallback (`SolidBackgroundFillColorBase` light ≈ `#F3F3F3`) whenever the
   material is policy-disabled** (transparency off, battery saver, RDP,
   inactive window). Every road from a light-flagged window ends at white.
   The app currently leaves flag 20 to Qt's palette heuristic, which is
   evaluated at native-window creation and is not contractually re-asserted
   on live theme toggles or HWND recreation (§2.3).
2. **Per-region material** — **NO** via any DWM window attribute: backdrop
   type is strictly per-top-level-HWND, drawn *"behind the entire window
   bounds"* ([DWM_SYSTEMBACKDROP_TYPE]). The one per-region DWM API that ever
   existed (`DwmEnableBlurBehindWindow` + `hRgnBlur`) has rendered **no blur
   since Windows 8** ([DwmEnableBlurBehindWindow]). **YES** via the
   Windows.UI.Composition visual layer (host backdrop brush on a
   region-sized visual, §3.2) — real but heavy interop; or by giving the
   region its own top-level HWND (floating/torn-off dock windows already
   are one, §3.3).
3. **Stability verdict on the undocumented Win10 path**
   (`SetWindowCompositionAttribute` / `ACCENT_ENABLE_ACRYLICBLURBEHIND`):
   **DO NOT SHIP.** Confirmed drag/resize lag since Win10 1903, blur loss on
   resize in 2004, and outright breakage on Win11 22631 (§1.6). The repo's
   existing decision to exclude it (`backdrop.py` line 62-65) is correct and
   should be ratified permanently.

---

## 1. API ground truth, card by card

### 1.1 `DWMWA_SYSTEMBACKDROP_TYPE` (attribute 38) — the shipping mechanism

- **What it is**: `DwmSetWindowAttribute(hwnd, 38, &DWM_SYSTEMBACKDROP_TYPE,
  4)`. DWM itself draws a material *"behind the entire window bounds"*,
  including behind the non-client area. The app never composites the
  material; it only has to leave per-pixel alpha holes for it to show
  through ([DWM_SYSTEMBACKDROP_TYPE], [DWMWINDOWATTRIBUTE]).
- **Enum semantics** (all quotes from [DWM_SYSTEMBACKDROP_TYPE]):
  - `DWMSBT_AUTO` (0) — DWM decides; *"applies the backdrop material just
    behind the default Win32 title bar"* and *"might also decide to draw no
    backdrop material at all based on internal heuristics."* Useless for us.
  - `DWMSBT_NONE` (1) — no backdrop.
  - `DWMSBT_MAINWINDOW` (2) — **Mica**: *"long-lived window"* material.
    Samples the **desktop wallpaper only, once** — not the windows behind —
    and is cheap by design: *"only samples the desktop wallpaper once to
    create its visualization"* ([Mica design]). Effectively opaque; tint
    follows theme + wallpaper.
  - `DWMSBT_TRANSIENTWINDOW` (3) — **Acrylic**, *"Desktop Acrylic, also
    known as Background Acrylic, in its brightest variant"*. This is the
    real-time blur of desktop + windows behind the window; GPU-intensive
    ([Acrylic design]).
  - `DWMSBT_TABBEDWINDOW` (4) — **Mica Alt**, stronger tint for tabbed
    title bars ([Mica design]).
  - Microsoft explicitly reserves the right to change all of these:
    *"The material effect might change with future Windows releases."*
- **OS support**: **Windows 11 build 22621 (22H2) and later, hard floor**
  ([DWM_SYSTEMBACKDROP_TYPE] Requirements). Insider builds 22523-22621 had
  it early ([tvc-16]). `backdrop.py`'s `_MIN_SUPPORTED_BUILD = 22621` is
  exactly right.
- **Scope**: top-level HWND only. Child HWNDs are not independently
  composited by DWM; setting 38 on a child does nothing useful.
- **Failure modes**: (a) per-HWND state — **destroyed silently with the
  HWND**; any native window re-creation (Qt does this on `setParent`,
  window-flag changes) drops it with no error; (b) returns `S_OK` yet
  renders nothing/solid when policy disables effects (§4) — you cannot
  detect the fallback from the HRESULT (the app's own INFO-log note at
  `backdrop.py:319-321` already suspects this — confirmed, that is real
  behavior); (c) tint follows attribute 20 (§1.2) — the WHITE class of bug.

### 1.2 `DWMWA_USE_IMMERSIVE_DARK_MODE` (attribute 20) — the tint switch, and the missing half of the recipe

- **What it is**: `BOOL`-sized attribute. Documented as titlebar/frame dark
  mode: *"Allows the window frame for this window to be drawn in dark mode
  colors when the dark mode system setting is enabled. **For compatibility
  reasons, all windows default to light mode regardless of the system
  setting.**"* ([DWMWINDOWATTRIBUTE]).
- **The undocumented-but-solid part (community RE, multiple independent
  sources)**: the same flag drives the **system backdrop's light/dark
  variant**. The Mica-for-WPF write-up states it plainly: setting
  `DWMWA_USE_IMMERSIVE_DARK_MODE` *"forces the Mica brush to render in dark
  mode"*, and without it Mica renders in its light variant ([tvc-16]).
  Microsoft's WinUI-side equivalent (`MicaController`) manages exactly this
  theme reaction for you ([apply-mica-win32]) — with raw attribute 38 you
  own it yourself. **Light-variant Mica over a typical wallpaper is
  whitish; the light fallback solid is `#F3F3F3` (WinUI token
  `SolidBackgroundFillColorBase`, named in [Mica design]) — i.e. WHITE for
  practical purposes.**
- **OS support**: documented *"starting with Windows 11 Build 22000"*
  ([DWMWINDOWATTRIBUTE]). Community RE: works on Win10 1809+ (value 19 on
  1809, 20 from 18985/19041 — e.g. ysc3839/win32-darkmode). Irrelevant here
  since the backdrop floor is already 22621.
- **Failure modes**: same per-HWND lifetime as 38 (dies with the HWND);
  and it is **owned by whoever set it last** — Qt's windows plugin also
  sets it from its own heuristic (§2.3), so an app that wants deterministic
  behavior must set it explicitly *after* Qt created the native window and
  *re-assert on every theme change*.

### 1.3 `DwmExtendFrameIntoClientArea(-1,-1,-1,-1)` — why alpha reaches DWM at all

- **What it does in this recipe**: the "sheet of glass" margins make the
  entire client area count as frame, which is the long-standing mechanism
  by which DWM honors the **per-pixel alpha of a normal (non-layered)
  window's redirection bitmap**. The DWM docs family states the alpha
  contract: *"The alpha values in the window are honored"*, with the
  explicit warning that GDI ops don't preserve alpha and child windows
  contribute *"unpredictable"* alpha values ([DwmEnableBlurBehindWindow]
  Remarks — same redirection-bitmap contract). This is why
  `backdrop.py` pairs ExtendFrame with attribute 38, and why
  `main.py` must request an alpha-capable surface format first.
- **Modern replacement on the horizon**: Windows 11 build 26100 documents
  `DWMWA_REDIRECTIONBITMAP_ALPHA` — *"Enables or disables the use of the
  alpha channel in the window's redirection bitmap"*, premultiplied
  ([DWMWINDOWATTRIBUTE]). That is the first *documented* per-pixel-alpha
  switch for plain Win32 windows; worth adopting conditionally (build
  ≥26100) later, keeping ExtendFrame(-1) for 22621-26100.
- **Failure mode specific to us**: with ExtendFrame(-1) active and the
  material **absent** (reset raced, HWND recreated, policy fallback), the
  alpha-holed regions composite against the DWM frame fill, not against a
  material — historically black on Win10, theme-fill on Win11 (light theme
  fill: white-ish). Another road to a flat white/black canvas that looks
  like "backdrop broken" but is actually "backdrop not attached".

### 1.4 `DWMWA_MICA_EFFECT` (undocumented 1029) — dead, never ship

Win11 21H2 (22000) only. Removed in insider 22494; replaced by attribute 38
from 22523 ([tvc-16]). Anyone proposing it as a 21H2 fallback should be
refused: it is a boolean on an attribute ID Microsoft deleted within one
release cycle. 21H2 hosts stay opaque (already the repo's policy).

### 1.5 `DwmEnableBlurBehindWindow` + `DWM_BLURBEHIND.hRgnBlur` — the legacy per-region API, blur is dead

- Vista/7 Aero glass API; **the** historical per-region material:
  `hRgnBlur` limited the effect to an arbitrary HRGN.
- Microsoft, verbatim: *"**Beginning with Windows 8, calling this function
  doesn't result in the blur effect**, due to a style change in the way
  windows are rendered."* ([DwmEnableBlurBehindWindow]). On Win10/11 it
  yields a transparent (unblurred) region — occasionally abused as an
  alpha-hole trick, never as glass.
- Top-level windows only (documented: *"This function can be called only on
  top-level windows"*). So even alive it never was a sub-HWND answer.
- **Verdict**: not a candidate. Its only council relevance is historical:
  it proves per-region material *was* a DWM concept once and was removed —
  region-scoped DWM glass is not coming back via dwmapi.

### 1.6 `SetWindowCompositionAttribute` / `ACCENT_POLICY` — undocumented Win10 path, stability verdict: DO NOT SHIP

- user32 export, undocumented since Win10 1607-era
  (`WCA_ACCENT_POLICY = 19`; `ACCENT_ENABLE_BLURBEHIND = 3` from 1607,
  `ACCENT_ENABLE_ACRYLICBLURBEHIND = 4` from 1803).
- **Documented-by-bug-tracker failure record**:
  - Win10 1903+: window no longer follows the mouse when dragged with
    acrylic accent enabled — severe, confirmed, never fixed in stable
    ([electron-acrylic-window #40]).
  - Win10 2004: blur lost on resize under WPF ([dotnet/wpf #3608]).
  - Win11 22631: `AcrylicBlurBehind` simply does not work anymore
    ([Avalonia #17684]).
- The API contract is "might be changed or removed in any build" — and it
  measurably has been, three times.
- **Verdict**: the repo's exclusion (`backdrop.py:62-65`, "known-jank …
  stays out of this codebase") is correct. This also closes the "Win10
  glass fallback" question permanently: **there is no shippable real-glass
  path on Windows 10.** Win10 = token fake-glass, full stop.

### 1.7 `WS_EX_LAYERED` / `SetLayeredWindowAttributes` — the kill-switch

- What Qt does: `QWidget.setWindowOpacity(x < 1.0)` makes the windows
  plugin apply `WS_EX_LAYERED` + `LWA_ALPHA` (Qt source,
  `qwindowswindow.cpp::setWindowLayered`: layered iff
  `WindowTransparentForInput`, or `hasAlpha && FramelessWindowHint`, or
  `opacity < 1.0`). Two ground-truth consequences:
  1. **A framed window with `WA_TranslucentBackground` is NOT layered** —
     that is precisely why the current recipe (alpha surface + ExtendFrame
     + attr 38) can work at all on a normal QMainWindow.
  2. **Any opacity < 1.0 flips the window into the layered path, and the
     system backdrop stops rendering.** Layered windows are composited via
     their own uniform-alpha/colorkey mechanism that predates and bypasses
     the material pipeline; no Microsoft doc states the interaction, but it
     reproduces universally (community: layered mode described as the thing
     that must be avoided for Mica/Acrylic to survive, e.g. the Electron
     ecosystem's `transparent: false` + `#00000000` background pattern and
     the per-pixel-alpha survey in [jeweg/win32-window-transparency]) — and
     **this repo proved it live** (Kaya's 98% opacity made acrylic vanish;
     the opacity pin in `gui/style.py:2136-2147` is the correct and
     necessary response).
- **Failure mode to keep guarded**: the pin is order-sensitive. Backdrop
  attach must land before any `setWindowOpacity` call on that window
  (`tests/test_backdrop.py:453` already pins this). Any new top-level
  window type that calls `setWindowOpacity` at construction while a
  material preference is active re-opens the hole.
- Layered windows themselves are rock-solid (Win2000+, work over RDP, no
  policy dependency) — which is exactly why the *uniform dimming* slider is
  the most robust "transparency" in the whole matrix, and also why it must
  never be conflated with material glass in the token vocabulary.

### 1.8 `DWMWA_USE_HOSTBACKDROPBRUSH` (17) + `Compositor.CreateHostBackdropBrush` — the only true per-region material

- **Documented**: attribute 17 *"Enables a non-UWP window to use host
  backdrop brushes"* so a Win32 app *"that calls Windows::UI::Composition
  APIs can build transparency effects using the host backdrop brush"*
  ([DWMWINDOWATTRIBUTE]; brush API: [CreateHostBackdropBrush], introduced
  Windows 10 2004/19041). Doc claims attr-17 support "starting with Windows
  11 Build 22000"; the flag shipped in the 19041 SDK and community samples
  run it on Win10 2004 with caveats (mixed reports — [MS Q&A blur-behind],
  [Win32Acrylic]).
- **Why it matters**: a `CompositionBackdropBrush` *"samples from the area
  behind the visual"* — the **visual**, not the window. Put a `SpriteVisual`
  the size of a panel into a `DesktopWindowTarget` visual tree and you have
  genuine, region-scoped, behind-the-window acrylic. This is how UWP host
  backdrop acrylic works internally, demonstrated standalone for plain
  Win32 by [Win32Acrylic] / Win32Acrylic2 (no Windows App SDK, no XAML).
- **Cost/reality for a Qt app** (why this is a QML-horizon architecture,
  not a patch): needs WinRT interop (`ICompositorDesktopInterop`,
  `CreateDesktopWindowTarget(hwnd, isTopmost=FALSE)` so visuals composite
  *behind* the window's own content), a `DispatcherQueue` pumping on the UI
  thread alongside the Qt event loop, and Qt content that leaves real alpha
  holes exactly over each visual. From Python: a small C++/winrt helper DLL
  or python-winrt. Region tracking (QtAds dock geometry → visual bounds) is
  app-side bookkeeping. Same policy fallbacks as every material (§4).
- **Verdict**: the honest "yes" to per-region — real, documented at both
  ends, sample-proven — but a subsystem, not a fix. Belongs in the U-track/
  seed design where a compositor-integration layer can own it.

### 1.9 Windows App SDK `MicaController` / `DesktopAcrylicController` — noted for completeness

Microsoft's currently recommended Win32 path ([apply-mica-win32]) — handles
theme reaction and policy for you (that is Microsoft implicitly admitting
the raw attr-38 recipe's theme handling is a footgun). Requires the Windows
App SDK runtime redistributable on every target machine plus WinRT interop.
For a PySide6 lab app: dependency cost >> benefit while attr 38 + attr 20
does the same window-level job in 40 lines of ctypes. Revisit only if the
seed platform ever takes a WinAppSDK dependency for other reasons.

---

## 2. The WHITE symptom — mechanism chain

### 2.1 What DWM thinks this window is

Nothing in `TCT_app` ever sets attribute 20 (verified: no grep hit for
`IMMERSIVE` outside comments/tests in the repo). Therefore the window's DWM
dark-mode flag is whatever **Qt** last set — and Microsoft's default is
explicit: *"all windows default to light mode regardless of the system
setting"* ([DWMWINDOWATTRIBUTE]).

### 2.2 The two white paints of a light-flagged window

| State | What DWM paints behind the alpha holes | Color |
|---|---|---|
| Material live, light variant | Light Mica = wallpaper sampled through a bright tint / light Acrylic *"in its brightest variant"* | whitish, wallpaper-dependent |
| Material policy-disabled (transparency off, battery saver, RDP, inactive, low-end HW — §4) | Solid fallback, light `SolidBackgroundFillColorBase` | ≈ `#F3F3F3` — flat WHITE |

A **dark**-flagged window in the same two states gives dark-tinted material
/ `#202020` — never white. That is why "completely WHITE everywhere incl.
the simple theme-settings window" diagnoses as **flag 20 = FALSE (light)**
on those HWNDs, independent of which of the two states the machine was in
tonight. It also explains "worked earlier": the flag is per-HWND and
Qt-owned — any window recreation, theme toggle, or creation-order change
can flip it without a single line of backdrop code changing.

### 2.3 How Qt sets it (and when it doesn't)

- Qt 6.4+: *"if the application palette is dark, then windows automatically
  use the dark window decoration"* — evaluated from the **application
  palette**, at **native window creation** ([Qt dark-mode blog]).
- This app's dark theme is mostly QSS; the palette side is only backstopped
  by `_apply_app_palette` (`gui/style.py:182-200`, sets `Window`/
  `WindowText`). At cold start `main.py` applies the theme *before* the
  main window exists, so creation-time evaluation sees dark — the launch
  case usually lands right. The unguaranteed cases: **live theme toggles**
  (Qt versions differ on re-asserting the frame flag on palette change —
  application patches exist in the wild precisely for this, e.g.
  [FreeCAD #20627]), **windows created while a light palette is current**,
  and **any HWND recreation** (all DWM attributes die with the HWND,
  silently).
- The Vista widget style additionally *"will always replace the system
  palette with the light system palette"* ([Qt dark-mode blog]) — the
  explicit `Window`/`WindowText` override wins for the darkness comparison,
  but this is a heuristic tower nobody should build glass on.

### 2.4 Prescription (one line of ctypes, owner: Noah — stated, not implemented)

In `backdrop.py`, immediately before the attribute-38 call, set attribute
20 explicitly from the active theme (`dark` → TRUE), and re-assert **both**
attributes (a) on every theme mode change, (b) whenever a top-level's
`winId` changes (Qt fires `QEvent::WinIdChange`). This is exactly the
pattern of every working Win32 Mica sample ([tvc-16], [apply-mica-win32]'s
controller doing it internally). It also fixes the mismatched titlebar
color for free. Falsification test for tonight's white: apply backdrop,
then `DwmSetWindowAttribute(hwnd, 20, TRUE)` by hand — if the white region
snaps dark, case closed.

---

## 3. Per-window vs per-region reality

### 3.1 The blunt truth

DWM materials are a **top-level-HWND-granularity** feature. Attribute 38
draws *"behind the entire window bounds"*; there is no rect/region/child
variant, and the one legacy region API lost its effect in Windows 8 (§1.5).
"Make only the QtAds dock canvas a material but not the cards" is **not
expressible in dwmapi.** Whatever look the council designs for the classic
shell must be built from: (window-level material) + (per-pixel alpha holes
where it may show) + (opaque token surfaces everywhere else) — which is
exactly the architecture `backdrop.py`/`style.py` already has.

### 3.2 The real per-region mechanism (composition visual layer)

`DWMWA_USE_HOSTBACKDROPBRUSH` + `CreateHostBackdropBrush` on a
`SpriteVisual` sized to the region (§1.8). Genuine behind-window sampling
per visual; sample-proven on plain Win32 ([Win32Acrylic]); heavy interop for
a Python/Qt app; policy-degrades like all materials. Right home: the QML
U-track / platform seed, as a designed compositor-integration subsystem.
(In-app blur of the app's *own* content — Qt Quick layer effects — is the
QML shell's cheaper cousin and another lane's brief; it is not a DWM
matter: no OS API blurs *other windows* into a sub-region except the
composition path above.)

### 3.3 The pragmatic per-region loophole that already exists

Every **top-level** window gets its own attribute-38 material for two ctypes
calls: QtAds **floating dock containers** and the app's `_DetachedWindow`
torn-off tabs are real top-levels and can each be a full material window
(`apply_window_backdrop_to` already fans out to them). "Glass palettes,
opaque cockpit" — material on satellites/transients (matches Microsoft's
own guidance: acrylic *for* transient surfaces, [Acrylic design]) with the
main cockpit on window-level Mica + token glass — is achievable **today**
with zero new mechanism.

---

## 4. Environment kill matrix

What each environmental condition does to each mechanism. "Fallback" =
solid fill, light `#F3F3F3` / dark `#202020` class colors, chosen by the
window's flag-20 state (§2.2).

| Condition | Attr-38 Mica / Mica Alt | Attr-38 Acrylic | SWCA accent (unshipped) | Host backdrop brush | WS_EX_LAYERED opacity | Token fake-glass (QSS) |
|---|---|---|---|---|---|---|
| Transparency effects OFF (Settings > Personalization > Colors) | Fallback solid — documented ([Mica design]) | Fallback solid — documented ([Acrylic design]) | dead/tint-only | fallback | **unaffected** | **unaffected** |
| Battery saver | Fallback solid — documented (both pages) | Fallback solid + *"automatically disabled"* ([Acrylic design]) | dead | fallback | unaffected | unaffected |
| RDP / VM session | effects policy-disabled → fallback (Terminal docs: *"like being in power saver … or when accessing a machine by using Remote Desktop"* [Terminal troubleshooting]) | same — *"over remote desktop, acrylic likely doesn't work"* | dead | fallback | unaffected (plain alpha blend) | unaffected |
| Window deactivated | Fallback — documented (*"an app window on desktop deactivates"*, [Mica design]) | DWM-side acrylic observed to persist unfocused (community; WinUI background acrylic documented to fall back) | n/a | brush keeps sampling | unaffected | unaffected |
| High contrast | user's chosen solid ([Mica design]/[Acrylic design]) | same | dead | fallback | unaffected | theme's own HC handling |
| Low-end HW | fallback (documented) | fallback (documented) | jank | fallback | unaffected | unaffected |
| Win11 21H2 (22000-22620) | **API absent** (1029 corpse only — never ship) | absent | works-ish, laggy | attr 17 present | works | works |
| Windows 10 | absent | absent | **the only path — and DO NOT SHIP (§1.6)** | SWCA-gated, mixed reports | works | works |
| Linux / offscreen / non-`windows` QPA | no DWM — clean no-op (already gated, `backdrop.py:124-137`) | — | — | — | compositor-dependent | **works — this is the floor** |

**Design law this table dictates** (confirming the brief's honesty rule):
the material is a *progressive enhancement* that can vanish at runtime
without any API error. The app must look intentional in the fallback state
at all times — which the pre-blended token look already provides. The only
runtime detectables: transparency setting (registry
`HKCU\...\Themes\Personalize!EnableTransparency`, or
`UISettings.AdvancedEffectsEnabled`), battery saver
(`SYSTEM_POWER_STATUS`), RDP (`GetSystemMetrics(SM_REMOTESESSION)`). If the
canvas alpha should track material presence (avoid alpha-holes over a flat
fallback), poll/subscribe those three — never trust the attr-38 HRESULT.

---

## 5. Decision table — API × OS × failure modes

| # | API | Does what | OS floor→ceiling | Scope | Killed / degraded by | Verdict for TCT |
|---|---|---|---|---|---|---|
| 1 | `DWMWA_SYSTEMBACKDROP_TYPE` (38) + `DwmExtendFrameIntoClientArea(-1)` | DWM draws Mica(2)/Acrylic(3)/MicaAlt(4) behind whole window; app leaves alpha holes | Win11 22621 → current | whole top-level HWND | flag-20 light = white variant; HWND recreation; layered mode (opacity<1); policy fallback to solid (§4) | **SHIP** — the classic-shell mechanism. Must gain explicit attr-20 handling (§2.4) |
| 2 | `DWMWA_USE_IMMERSIVE_DARK_MODE` (20) | Dark frame **and** dark material variant + dark fallback solid | doc: 22000+ (RE: Win10 1809+) | per HWND | Qt heuristic overwrites at creation; dies with HWND | **SHIP** — mandatory companion of #1; the WHITE fix |
| 3 | `DWMWA_MICA_EFFECT` (1029, undoc.) | Mica on 21H2 | 22000 → **removed 22494** | per HWND | deleted by Microsoft | **NEVER** |
| 4 | `DwmEnableBlurBehindWindow` + `hRgnBlur` | Vista/7: per-region blur; Win8+: transparency, **no blur** | Vista → blur dead Win8 | top-level, region-capable (dead) | Windows 8 | **NO** — historical only |
| 5 | `SetWindowCompositionAttribute` + `ACCENT_*` (undoc.) | Win10 blur/acrylic accent | Win10 1607/1803 → broken 22631 | whole window | drag lag 1903+; resize blur loss 2004; dead 22631; undocumented | **DO NOT SHIP** — ratify the existing exclusion |
| 6 | `WS_EX_LAYERED` / `setWindowOpacity<1` | Uniform whole-window alpha | Win2000 → current, incl. RDP | whole window | nothing environmental — but **kills #1** on that window | **KEEP as separate dimming knob** + keep the opacity pin & ordering test |
| 7 | `DWMWA_USE_HOSTBACKDROPBRUSH` (17) + `CreateHostBackdropBrush` | Behind-window acrylic sampled **per visual** = true per-region | Win10 2004 (brush) / doc 22000 (attr) → current | **arbitrary region** via composition visual | policy fallback (§4); WinRT interop + DispatcherQueue + alpha-hole bookkeeping | **U-track/seed candidate** — the real per-region architecture, not a patch |
| 8 | WinAppSDK `MicaController`/`DesktopAcrylicController` | #1+#2+policy, managed | Win11 (SDK-dep) | window target | runtime redistributable dependency | **NO for now** — dependency cost |
| 9 | `DWMWA_REDIRECTIONBITMAP_ALPHA` (26100+) | Documented per-pixel alpha for plain windows (replaces the ExtendFrame(-1) hack) | Win11 26100 → current | per HWND | build-gated | **ADOPT conditionally** later, keep ExtendFrame for 22621-26100 |

---

## 6. Sources

Microsoft documentation:
- [DWM_SYSTEMBACKDROP_TYPE] https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type
- [DWMWINDOWATTRIBUTE] https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
- [DwmEnableBlurBehindWindow] https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmenableblurbehindwindow
- [apply-mica-win32] https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-mica-win32
- [Mica design] https://learn.microsoft.com/en-us/windows/apps/design/style/mica
- [Acrylic design] https://learn.microsoft.com/en-us/windows/apps/design/style/acrylic
- [CreateHostBackdropBrush] https://learn.microsoft.com/en-us/uwp/api/windows.ui.composition.compositor.createhostbackdropbrush
- [Terminal troubleshooting] https://learn.microsoft.com/en-us/windows/terminal/troubleshooting
- [MS Q&A blur-behind] https://learn.microsoft.com/en-ie/answers/questions/152914/how-to-blur-behind-classic-win32-or-wpf-window-usi

Credible reverse-engineering / bug-tracker record:
- [tvc-16] https://tvc-16.science/mica-wpf.html (attr 20 forces Mica dark variant; 1029 → 22523 transition)
- [electron-acrylic-window #40] https://github.com/Seo-Rii/electron-acrylic-window/issues/40 (SWCA drag lag, Win10 1903+)
- [dotnet/wpf #3608] https://github.com/dotnet/wpf/issues/3608 (SWCA blur loss on resize, Win10 2004)
- [Avalonia #17684] https://github.com/AvaloniaUI/Avalonia/issues/17684 (SWCA acrylic dead on Win11 22631)
- [Win32Acrylic] https://github.com/wangwenx190/Win32Acrylic2 and https://github.com/ALTaleX531/Win32Acrylic (host backdrop brush on plain Win32, no WinAppSDK)
- [jeweg/win32-window-transparency] https://github.com/jeweg/win32-window-transparency (per-pixel alpha vs layered-window survey)
- [Qt dark-mode blog] https://www.qt.io/blog/dark-mode-on-windows-11-with-qt-6.5 (Qt 6.4+ frame follows app palette; Vista style forces light palette)
- [FreeCAD #20627] https://github.com/FreeCAD/FreeCAD/pull/20627 (apps patching Qt 6.5+ titlebar/frame re-assertion in the wild)
- Qt source: `qtbase/src/plugins/platforms/windows/qwindowswindow.cpp` (`setWindowLayered` conditions; dark-frame heuristic at window creation)
- In-repo empirical: `docs/design/glass_gap_findings.md` (pixel-equal verdict; opacity-pin discovery), `TCT_app/gui/backdrop.py`, `TCT_app/gui/style.py:2136-2147`, `tests/test_backdrop.py:453`
