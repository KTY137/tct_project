# Cockpit design — state of the art for the TCT overhaul

- **Date:** 2026-07-12
- **Question (from Adam/Kaya):** For the TCT cockpit redesign, what is the current
  best-in-class prior art for a "highly polished Apple-style, functionality-first,
  instrument" desktop UI? Cover (1) Apple's *current* direction (Liquid Glass /
  macOS Tahoe 26) and what of it translates to a Qt desktop app, (2) best-in-class
  instrument/technical UI references and their concrete patterns, (3) typography for
  glanceable instrument readouts, (4) dangerous-action UX (hold-to-arm, alarm-color
  discipline), (5) evidence that this polish is reachable in Qt Quick/QML.
- **Scope:** Design research to guide the cockpit-v5 overhaul. No hardware commands.
  **Complements — does not repeat —** `ui_design.md` (8pt grid, tabular-nums Qt
  implementation, QSS perf, ISA-101 basics) and `qml_hybrid_architecture.md` (the
  QML-islands + pyqtgraph-sibling architecture, RHI/OpenGL, Theme singleton,
  3-layer law). Read those two first; this note is the *aesthetic + interaction*
  layer on top of that architecture.
- **Confidence:** **secondary source** overall (design analyses, product docs),
  with **official** anchors: Apple Newsroom/WWDC25 for Liquid Glass, FAA 14 CFR
  25.1322 for cockpit alert colors, ISA-101 / IEC 62682 / IEC 63303 for HMI/alarm
  standards, Qt/Felgo docs for QML feasibility. Design guidance — nothing here is a
  hardware command, nothing safety-critical is invented.

---

## 1. Apple's current direction — Liquid Glass (macOS Tahoe 26 / iOS 26, 2025→2026)

- **What it is (official).** Liquid Glass is a single translucent *material* that
  Apple layers across controls, navigation and chrome. It combines **real-time blur,
  depth-based refraction, and specular highlights**, and its tint is **informed by
  the content behind it**, adapting light/dark automatically. Apple calls the optical
  trick **"lensing"** — it *bends and concentrates* light rather than scattering it
  like a plain gaussian blur. (Apple Newsroom; WWDC25 "Meet Liquid Glass".)
- **The organizing principle is "hierarchy through depth."** Controls form a distinct
  **functional layer that floats above content and gives way to it** — importance is
  signalled by depth/translucency/refraction, not by heavier color or size. Practical
  reading: glass belongs on the **navigation/chrome layer, not on the content**
  (plots, images, data). (WWDC25; HIG "Materials".)
- **Material variants.** A "thin/regular vs clear/frosted" split: subtle thin glass for
  overlays, thicker/frosted glass for prominent surfaces and backgrounds. Each layer
  **continuously shifts tint, shadow and dynamic range to keep foreground text legible**
  as content scrolls beneath. (dev.to Liquid-Glass best-practices; conor.fyi reference.)
- **The 2025→2026 correction is the most important lesson for us.** The first release
  (26.0) was widely judged **"offensively illegible and shiny."** Apple did **not**
  abandon it — across **26.1 it added a "Tinted"/reduced-transparency mode** (less
  transparency, more contrast, varies per element) and **26.2 added intensity sliders /
  "Glass vs Solid" toggles**. Net: **legibility beats spectacle; translucency must be
  calibrated, tintable, and defeasible.** (Six Colors "Soaping up Liquid Glass";
  designedforhumans accessibility review.)
- **Accessibility is a first-class part of the spec.** Liquid Glass honours **Reduce
  Transparency** (frostier, more opaque), **Increase Contrast** (elements go near
  black/white with a contrasting border), and **Reduce Motion** (damps the animated
  effects). Any "glass" we build needs the same escape hatches. (designedforhumans;
  CSS-Tricks "Getting Clarity on Liquid Glass".)
- **What translates to a Qt desktop app vs what doesn't.**
  - *Translates:* the **layered-material mental model** (calm content plane + a
    floating chrome plane), **one system font + weight-for-hierarchy**, **semantic
    color roles** (systemBlue/label/background) instead of raw hex, **capsule/pill
    control shapes**, generous **corner-radius + concentricity**, and the
    **legibility-first, user-defeatable-translucency** discipline. Qt's `QSGRhi` /
    `MultiEffect` blur can approximate frosted glass on the chrome layer (our stack
    already pins OpenGL — see `qml_hybrid_architecture.md`).
  - *Does NOT translate cleanly:* real-time **content-aware refraction/lensing +
    specular highlights** are a bespoke Metal shader — expensive and un-Apple if
    faked badly. **Do not chase live lensing.** Ship a **static/near-static frosted
    panel** (one blur pass + a hairline top highlight + subtle inner shadow), and put
    the effort into type, spacing, motion restraint and color discipline, which is
    where "Apple-feel" actually lives. Never put glass over a live plot (perf + the
    "glass-on-content" anti-pattern).

Sources: [Apple Newsroom — new software design (Liquid Glass)](https://www.apple.com/newsroom/2025/06/apple-introduces-a-delightful-and-elegant-new-software-design/) ·
[WWDC25 — Meet Liquid Glass](https://developer.apple.com/videos/play/wwdc2025/219/) ·
[Six Colors — Soaping up Liquid Glass](https://sixcolors.com/post/2025/11/soaping-up-liquid-glass-less-transparency-more-contrast/) ·
[Designed for Humans — Liquid Glass & accessibility](https://designedforhumans.tech/blog/liquid-glass-smart-or-bad-for-accessibility) ·
[CSS-Tricks — Getting clarity on Liquid Glass](https://css-tricks.com/getting-clarity-on-apples-liquid-glass/) ·
[Liquid Glass in Swift — official best practices](https://dev.to/diskcleankit/liquid-glass-in-swift-official-best-practices-for-ios-26-macos-tahoe-1coo)

---

## 2. Best-in-class instrument / technical UI references — concrete patterns

- **Apple pro apps (Logic Pro, Final Cut Pro, Instruments) — the density model.**
  A **dark, near-monochrome canvas** with larger toolbar icons + white text "viewable
  at a glance," a **single customizable window** (no modal sprawl), and a persistent
  **inspector** for detail on demand. The lesson for expert density: **quiet dark
  chrome, content is the color**, controls collapse into inspectors/toolbars rather
  than filling the frame. (9to5Mac Logic Pro X review; Apple Logic Pro.)
- **Raycast — the most directly copyable "polished dark tool" spec.** Concrete,
  reusable patterns:
  - **No drop-shadow elevation at all**; depth is a **4-step surface ladder** —
    each notch lighter on the dark scale = one step closer. (Our `bg→panel→border`
    already seeds this; formalize to ~4 steps.)
  - **A single white "CTA pill" as the universal primary action**; everything else
    monochrome. Color appears **only** as small category accents (per-device, per-
    status), never as decoration.
  - **Keyboard-first**: a command surface + instant results; chrome earns its pixels.
  (Raycast DESIGN.md.)
- **Linear — restraint + craft as a product value.** Monochrome base, one accent,
  obsessive spacing/alignment, motion used sparingly for continuity. Their public
  "how we redesigned the UI" writeups reinforce: **fewer colors, tighter grid,
  consistent radii read as "expensive."** (Linear design writeups.)
- **SpaceX Crew Dragon displays — mission-ops discipline.** Human-centered goal was
  **"minimum crew interaction."** ~30 physical buttons + 3 touchscreens; **every datum
  reachable, but the resting screen is calm** with static 3D control affordances in
  fixed corners. Built in **HTML/CSS/JS (Chromium)** — evidence a "flight-deck" feel is
  a *design* achievement, not a native-toolkit one. Takeaway: **fixed, predictable
  control zones + a calm nominal state + emergency commands one layer away.**
  (shanemielke.com SpaceX case study; RocketSTEM.)
- **Modern lab instruments — Moku (Liquid Instruments) & PicoScope 7.**
  - **Moku:** *"one user interface with consistent controls across instruments"* — a
    single design language reused across scope / spectrum-analyzer / etc. The win is
    **consistency across modes**, not per-mode bespoke screens. Directly relevant: our
    scope/motor/bias/scan panels should feel like one instrument, not five apps.
  - **PicoScope 7:** rewritten for modern displays + touch, **deep-memory views in
    time and frequency**, a named analysis feature ("DeepMeasure") surfaced as a
    first-class verb. Lesson: **name and elevate the expert analysis actions**; give
    dense captures room; touch-friendly hit targets don't preclude density.
  (Liquid Instruments Oscilloscope; PicoScope 7 hands-on.)
- **Plot chrome / annunciation synthesis across all of the above:** dark plot canvas,
  hairline (not heavy) grid, **status lives in small persistent tiles/pills** around the
  plot, **irreversible verbs are visually distinct and never adjacent to benign ones**
  (NN/g "consequential options proximity"), and **empty states say what to do next**
  ("Connect a device to begin" / "No scan loaded"), not a blank pane.

Sources: [9to5Mac — Logic Pro X UI](https://9to5mac.com/2013/07/26/logic-pro-x-review-powerful-new-features-a-simplified-ui-with-no-compromises-for-pros/) ·
[Raycast DESIGN.md](https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/raycast/DESIGN.md) ·
[Linear — how we redesigned the UI](https://linear.app/now/how-we-redesigned-the-linear-ui) ·
[Shane Mielke — SpaceX Crew Dragon displays](https://www.shanemielke.com/work/spacex/crew-dragon-displays/) ·
[Liquid Instruments — Oscilloscope](https://liquidinstruments.com/products/integrated-instruments/oscilloscope/) ·
[PicoScope 7 hands-on](https://www.picotech.com/library/articles/blog/hands-on-with-picoscope-7-pico-technologys-latest-oscilloscope-software) ·
[NN/g — consequential options proximity](https://www.nngroup.com/articles/proximity-consequential-options/)

---

## 3. Typography for instrumentation

- **One system family, weight for hierarchy.** Apple's model = **SF Pro** everywhere,
  hierarchy from **size + weight**, not new families or color. On Windows our analogue
  is **Segoe UI** (fine) or **Inter** (cross-platform, ships tabular figures). SF Mono
  is Apple's code/mono face. (Superdesign Apple breakdown; see `ui_design.md` §1.2.)
- **A concrete Apple-ish scale to adapt** (from the iOS Dynamic Type ladder): Large
  Title ≈ 34, Title ≈ 22–28, Headline ≈ 17 semibold, **Body ≈ 17 (the "legibility
  floor")**, Caption ≈ 11–13. For a dense desktop cockpit, compress but keep the
  *ratios*: e.g. hero metric 28–34, section title 15–17, body 13, caption 11–12.
  (Superdesign Apple breakdown.)
- **Numerals must be tabular / lining for every live readout** (voltage, current,
  position, ToT, timers, rates) so digits don't jitter as they update — the single
  cheapest "instrument-grade" upgrade. Prefer the font **feature** `tabular-nums`
  (Qt 6.7+ `QFont.setFeature`) over switching to a mono face; fall back to a
  mono/tabular face **only for the numeric label** if needed. (Full Qt implementation
  detail already in `ui_design.md` §1.2; MyFonts/useyourloaf on monospace digits.)
- **Large, soft hero metrics (the user's brief).** Real instruments make the primary
  reading big and calm: a **large tabular number + a small muted unit/label**, one per
  tile. Avoid segmented-LCD/"digital readout" display faces (e.g. *SF Digital Readout*)
  — they read retro/gimmicky, not premium; use a clean sans with tabular figures.
  (SF Digital Readout listing shown as the anti-pattern.)
- **Case: sentence case for labels, UPPERCASE only for tiny annunciator tags.**
  Apple/Linear/Raycast use sentence case for readability; reserve short **UPPERCASE**
  for small status chips (`ARMED`, `HV ON`, `FAULT`) where the all-caps *is* the
  signal. Don't uppercase body text or long labels. (Convention across the Apple/
  Linear/Raycast references above; supports glanceability.)

Sources: [Superdesign — Apple design system breakdown (2026)](https://superdesign.dev/blog/apple-design-system) ·
[Use Your Loaf — monospace digits](https://useyourloaf.com/blog/monospace-digits/) ·
[DEV — tabular numbers in CSS](https://dev.to/alanwest/tabular-numbers-in-css-font-variant-numeric-vs-monospace-hacks-25cn) ·
[SF Digital Readout (anti-pattern reference)](https://www.myfonts.com/collections/sf-digital-readout-pro-font-cheapprofonts/)

---

## 4. Dangerous-action UX — hold-to-arm + alarm-color discipline

- **Hold-to-confirm / hold-to-arm is a real, recommended pattern for irreversible
  actions**, superior to a click-through dialog because it converts a reflex into a
  **conscious, sustained gesture** and is hard to trigger by accident. It must show a
  **progress indicator** (a filling ring/bar) and give immediate feedback on a stray
  tap ("hold to confirm"). Recommended durations scale with severity: **~1–1.5 s** for
  easily-reversible, **~3 s** for terminal/destructive, **up to ~5 s** for actions that
  affect others/hardware. (Medium "Why holding buttons is superior"; Smashing "Manage
  dangerous actions".) **Fit for TCT:** HV-enable, HV-ramp, homing, stage-move, and
  scan-start are exactly the "sustained-intent" class → hold-to-arm with a progress
  ring, distinct danger color, and physical separation from benign controls. This
  *augments*, does not replace, the app's mandatory explicit-confirmation safety rule.
- **Keep consequential options away from benign ones.** Placing an irreversible verb
  next to a routine one causes slips; separate them spatially and style them
  differently. (NN/g "proximity of consequential options".)
- **ISA-101 / high-performance-HMI color law — the backbone of our color discipline.**
  Design the whole UI in **greys; ~90% of the screen stays neutral**; **saturated color
  means "look here now"** — reserved for abnormal/alarm/operator-action states.
  Documented result: **~48% improvement in detecting abnormal situations before alarms**
  and up to ~50% faster operator response from disciplined color use. ISA-101 is now
  also **IEC 63303**; alarm management references **IEC 62682**. (control.com "Going
  Gray"; plcprogramming.io ISA-101 guide; RealPars.)
- **A converging alert-color convention (ISA-101 ∩ FAA/EFIS cockpit).** Use one small,
  fixed palette and never overload it:
  - **RED = warning / immediate action / limit exceeded** (HV trip, interlock,
    motor fault, lost connection mid-scan).
  - **AMBER/YELLOW = caution / awareness / out-of-range-soon** (approaching a soft
    limit, ramp in progress, degraded).
  - **GREEN = normal / satisfactory / engaged** — use *sparingly*; a sea of green
    defeats the "color = abnormal" rule.
  - **CYAN/BLUE = advisory / informational / parameter labels** (also our focus/accent).
    Per FAA 14 CFR 25.1322 advisories may be **any color except red or green**.
  - **Never green or red for advisory; never reuse the accent to mean "good."**
  (FAA 25.1322 via EFIS refs; Wikipedia EFIS / EICAS 7-color scheme.) This directly
  extends the `ok/warn/critical/info` token set recommended in `ui_design.md` §1.3.
- **Annunciator behavior, not just color.** Pair every status color with **text/icon**
  (colorblind safety); make a new **critical** alarm *move* (a single attention pulse)
  while nominal states are static — motion is another scarce signal, spent only on
  abnormality, and must respect a Reduce-Motion setting (§1).

Sources: [Medium — Why holding buttons beats confirmation dialogs](https://medium.com/@tomj.pro/why-holding-buttons-is-superior-to-confirmation-dialogs-in-ux-design-69790ff30e06) ·
[Smashing — How to manage dangerous actions](https://www.smashingmagazine.com/2024/09/how-manage-dangerous-actions-user-interfaces/) ·
[NN/g — consequential options proximity](https://www.nngroup.com/articles/proximity-consequential-options/) ·
[control.com — Going Gray (ISA-101)](https://control.com/technical-articles/going-gray/) ·
[plcprogramming.io — ISA-101 guide](https://plcprogramming.io/blog/hmi-design-best-practices-complete-guide) ·
[RealPars — high-performance HMI](https://www.realpars.com/blog/high-performance-hmi) ·
[Wikipedia — Electronic flight instrument system (EFIS/EICAS colors, FAA 25.1322)](https://en.wikipedia.org/wiki/Electronic_flight_instrument_system)

---

## 5. Is this polish reachable in Qt Quick / QML? — yes (evidence)

- **Qt Quick is the toolkit automakers ship polished digital cockpits on.** The
  **Qt Automotive Suite** and reference cockpits (e.g. the Outrun multi-screen HMI,
  Qt Quick Ultralite automotive cluster) demonstrate production-grade, animated,
  material-rich instrument UIs in QML — the exact "instrument cockpit" idiom we want.
  (Qt Automotive Suite; Qt for MCUs automotive example.)
- **Felgo's showcase apps** (Component Showcase, Coffee Machine UI, E-Bike HMI) and the
  **Qt Quick Dial Control example** (Image + Rotation + SpringAnimation) show gauges,
  cards and controls at commercial polish, plus **QML hot-reload** for fast visual
  iteration. (Felgo docs; Felgo hot-reload.)
- **Community car-dashboard QML projects** (e.g. cppqtdev Qt-HMI-Display-UI) confirm the
  dark-glass, large-metric, single-accent look is routinely achieved in Qt Quick by
  non-Apple teams. (GitHub Qt-HMI-Display-UI.)
- **Frosted-glass specifically** is achievable via `MultiEffect`/shader blur on the QML
  chrome layer; our architecture note already validated the compositing path
  (QQuickWidget islands, RHI pinned to OpenGL, plots as sibling QWidgets) — so the
  material and the fast plots coexist. **The limiter is discipline, not the toolkit.**
  (See `qml_hybrid_architecture.md`.)
- **Caveat carried from the architecture note:** QML's threaded render loop is off in
  `QQuickWidget`, so keep chrome animation light and **never** host a hot plot in QML —
  which is already our rule. Polish yes; hot-path plotting stays pyqtgraph.

Sources: [Qt — Automotive Suite](https://qt.io/qt-automotive-suite) ·
[Qt for MCUs — Automotive cluster demo](https://doc.qt.io/QtForMCUs/quickultralite-automotive-example.html) ·
[Felgo — Dial Control example](https://felgo.com/doc/qt5/qtquick-customitems-dialcontrol-example/) ·
[Felgo — QML hot reload](https://blog.felgo.com/release-felgo-qml-hot-reload-for-qt-projects) ·
[GitHub — Qt-HMI-Display-UI (car dashboard QML)](https://github.com/cppqtdev/Qt-HMI-Display-UI)

---

## Top 10 concrete recommendations for TCT (ranked by impact)

1. **Adopt ISA-101 "quiet grey by default, color = abnormal" as the color law.** The
   whole cockpit is neutral/monochrome at rest; saturated amber/red appear only for
   HV-on, faults, out-of-range, interlock, lost-connection. Highest-impact single move
   — it's *both* the professional-instrument look and directly aligned with the safety
   rules. (Extends `ui_design.md` §1.3/§1.5.)
2. **Fix the alert palette and never overload it:** RED=warning/immediate,
   AMBER=caution/awareness, GREEN=normal (used sparingly), CYAN/BLUE=advisory + accent.
   One accent, one danger color; advisory is never red/green; the accent never means
   "good." Pair every color with text/icon for colorblind safety.
3. **Tabular numerals on every live readout** (V, I, position, ToT, rate, timers) via
   the Qt font feature, mono fallback only for the numeral. Cheap, and it's the
   difference between "homemade" and "instrument-grade." (Impl in `ui_design.md` §1.2.)
4. **Large, calm hero metrics: one big tabular number + small muted unit per tile.**
   Clean sans (Segoe/Inter), weight-and-size hierarchy, sentence-case labels, UPPERCASE
   only for tiny status chips. Avoid segmented-LCD display faces.
5. **Hold-to-arm for every dangerous verb** (HV enable/ramp, home, move, scan start):
   a filling progress ring, ~3 s (up to ~5 s for HV/motion), distinct danger styling,
   physically separated from benign controls. Augments — never replaces — the explicit
   confirmation the safety rules require.
6. **Depth by surface ladder + hairlines, not drop shadows (Raycast model).** Formalize
   ~4 dark surface steps + subtle borders; reserve one static frosted-glass treatment
   for the chrome/rail only. Glass floats *above* content and **never** covers a plot.
7. **Ship translucency legibility-first and defeasible (Apple's own 26.1/26.2 lesson).**
   One near-static frosted panel (single blur + hairline highlight + faint inner
   shadow), plus a **Reduce Transparency / Reduce Motion / High Contrast** switch that
   makes glass opaque and stills motion. Do **not** chase live lensing/specular.
8. **One instrument, five panels — a single reused design language (Moku model).**
   Scope/motor/bias/scan/camera share the same tiles, chips, buttons, spacing, plot
   chrome. Consistency across modes reads as more premium than per-panel bespoke.
9. **Calm nominal state + emergency one layer away + meaningful empty states
   (SpaceX/pro-app model).** Fixed, predictable control zones; resting screen quiet;
   irreversible verbs distinct and never adjacent to benign ones; empty panes say
   "Connect a device to begin", not blank.
10. **Motion is a scarce signal — spend it only on abnormality and continuity.** A
    single attention pulse when a critical alarm arrives; gentle transitions for
    layout continuity; nominal readouts are static. Keep QML chrome animation light
    (threaded render loop is off in `QQuickWidget`); hot plots stay pyqtgraph.
