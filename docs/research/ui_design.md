# GUI redesign research — style, performance, PySide6 theming

- **Date:** 2026-07-05
- **Question:** What are current, primary-sourced best practices for making a dense,
  professional PySide6 (Qt6) + pyqtgraph + QtAds + superqt/qtawesome instrument-control
  UI look premium and stay fast, and how should the QSS theme system be structured?
- **Scope:** Design guidance for the GUI-redesign meeting. Applies to `gui/style.py`
  and the PySide6 panels. No hardware commands involved.
- **Confidence:** Design/library guidance from official docs (Qt, pyqtgraph, superqt,
  qtawesome, Material Design, ISA) and reputable secondary design references. Not a
  hardware-command note — nothing here is safety-critical. Every rule is cited below.

---

## 1. STYLE & BEAUTY

### 1.1 Spacing rhythm (the single biggest "premium vs homemade" lever)
- Use one **spacing scale**, all multiples of a base unit, not by-feel numbers. The
  dominant systems (Material, IBM Carbon) use an **8pt grid with a 4pt sub-step**:
  4 / 8 / 12 / 16 / 24 / 32 / 40 / 48. Pick paddings/margins/gaps only from this set.
  [Material spacing], [8pt grid].
- Dense instrument panels benefit from the **4pt sub-grid** for control-internal
  padding while keeping 8pt for inter-group spacing — high-density UIs use the finer
  granularity, low-density ones use pure 8pt. [8pt grid].
- What reads as amateur is a type/spacing scale "with random jumps or favorite sizes
  added by feel"; a professional scale has no special-case values — every step
  strengthens hierarchy. [EightShapes typography].
- **Grouping:** honor the "internal ≤ external" rule — space *inside* a group must be
  smaller than the space *between* groups, or grouping reads ambiguously.
  [spacing best practices].

Current `style.py` already does this reasonably (GroupBox radius 8, padding 12,
margin-top 14). The action item is to make the scale *explicit and reused* rather than
ad-hoc per widget.

### 1.2 Typography for a control UI
- Establish a small **type scale** (e.g. 12 caption / 13 body / 15 subtitle / 20 title)
  with consistent weights; hierarchy comes from size+weight, not color alone.
  [EightShapes typography].
- **Numeric readouts (voltages, currents, positions, timers) must use tabular /
  lining figures** so digits don't jitter when values update. The modern, correct way
  is `font-variant-numeric: tabular-nums` — NOT switching to a monospace font. In Qt
  this is set on a `QFont` via `QFont.setFeatures()` / `setFeature(QFont.Tag("tnum"), 1)`
  (Qt 6.7+) or historically via `QFont::StyleStrategy`; where feature control isn't
  available, fall back to a mono/tabular face (JetBrains Mono, Roboto Mono) *only for the
  numeric label*. Proportional fonts give "1" and "8" different widths, so an updating
  readout shifts horizontally — "for timers, live prices it's terrible UX."
  [tabular-nums DEV], [MDN font-variant-numeric].
- Apply tabular figures **only where alignment matters** (readouts, tables, scan
  coordinates); keep proportional digits for prose. Mixing is expected.
  [Tailwind font-variant-numeric].
- Segoe UI (current default) is fine on Windows; Inter is a good cross-platform
  fallback and ships both proportional and tabular figure sets. [tabular-nums DEV].

### 1.3 Color: semantic status must be separate from brand accent
- **Keep brand/accent tokens separate from functional/status tokens.** Material 3 ships
  `primary/secondary/tertiary/error/surface/outline` but deliberately has **no
  success/warning/info roles — you define your own tokens**; brand tokens "express
  identity," functional tokens "handle usability signals like errors, warnings, success."
  [M3 color roles], [MD collective].
- Practical status palette to standardize (distinct hues, readable on both themes):
  - OK / good — green
  - Warning / caution — amber/yellow (add this; the app currently only has green+red)
  - Critical / fault / error — red
  - Info / neutral state — the accent blue *or* a neutral gray, but **do not reuse the
    accent for "success"** or the meaning collapses.
- The app's accent `#2d7ff9` is currently *also* the focus/selection color. That's fine —
  but it means blue must never be overloaded to mean "good." Status = green/amber/red only.
- **Don't rely on color alone.** Pair status color with an icon or text label
  (qtawesome makes this cheap) for colorblind users. [MDN font-variant-numeric context /
  accessibility is standard M3 guidance].

### 1.4 Dark-mode dashboard done well
- **Never pure black (#000).** Pure black kills elevation cues and creates harsh
  contrast; use a dark gray base (~`#121212`+). The current dark `bg #1f242b` /
  `panel #272d36` is already correct. [dark-mode best practices].
- **Elevation by surface lightness, not shadows** — shadows are nearly invisible on
  dark; separate cards with lighter background steps and/or subtle borders. The app's
  `bg → panel → border` triad already does this; keep 2–3 discrete surface levels.
  [dark-mode best practices].
- **Desaturate accents in dark mode** (~20 points lower saturation, slightly higher
  lightness) so saturated colors don't vibrate against dark surfaces. The current shared
  `#2d7ff9` accent is quite saturated; a slightly desaturated dark-mode variant is worth a
  token. [dark-mode best practices].
- **Off-white text, not pure white** (e.g. `#e5e7eb`) to cut glare — the app's
  `text #e6e9ee` is already correct. [dark-mode best practices].

### 1.5 How pro instrument / DAQ / control UIs present controls (ISA-101 "High-Performance HMI")
This is the most directly relevant prior art for a lab-control app:
- **Design the base UI in grays; reserve saturated color for abnormal/alarm states.**
  In ISA-101 high-performance HMI, "color is the attention-getter... used to indicate an
  abnormal situation very quickly." A screen that is calm gray at rest and turns
  amber/red only on fault is the professional pattern. [ISA-101 guide], [Going Gray].
- Light-gray (or dark-gray) backgrounds over pure white/black reduce eye strain over
  long shifts. [Industrial HMI grayscale].
- Muted resting palette prevents "alarm flooding" fatigue; full-intensity color only for
  critical/urgent conditions. Reported ~48% improvement in early abnormal-situation
  detection and up to ~50% faster operator response from disciplined color use.
  [ISA-101 guide], [RealPars high-performance HMI].
- Implication for TCT: the scan/HV/motor panels should look quiet and monochrome while
  nominal; HV-on, motor-fault, out-of-range, and interlock states are where the
  amber/red semantic tokens earn their keep — consistent with the app's safety rules.

### 1.6 "Premium" checklist (synthesis)
Reads premium: one spacing scale, one type scale, tabular readouts, restrained neutral
palette + a single accent + disciplined semantic status, consistent 6–8px radii,
consistent icon set, generous-but-consistent padding, alignment to a grid.
Reads homemade: mixed ad-hoc paddings, saturated colors everywhere, jittering readouts,
mismatched icon styles, color as the only status signal, pure black/white surfaces.

---

## 2. PERFORMANCE

### 2.1 QSS cost — real, and worth engineering around
- QSS is convenient but **not free**: applying a stylesheet creates a `QStyleSheetStyle`
  and "performance is not very good" for heavy cases. [Qt style-sheet syntax / KDAB].
- KDAB (Qt consultancy) quantifies the costs: **each `setStyleSheet()` call triggers a
  full re-parse**; **each widget reparent clears the stylesheet-rules cache and
  recalculates everything**; the **"polish" phase costs "several milliseconds each"** and
  "adds up quickly" with many widgets in complex nested layouts. QSS is fine for "few
  widgets with static layouts and few refreshes"; avoid for "many widgets... with
  frequent tear-downs and refreshes." [KDAB Say No to QSS].
- Practical rules for this app (it already applies one app-wide sheet — good):
  - **Set the stylesheet once at the application level**, not per-widget. `apply_theme`
    already does `app.setStyleSheet(...)` once. Keep it that way. [KDAB], [Qt].
  - **Don't call `setStyleSheet()` repeatedly** to reflect state (e.g. per data update).
    Use a **dynamic Qt property + one `unpolish()/polish()`** — Qt docs/forum note that
    an `unpolish()/polish()` pair is the fastest way to force a restyle, and the pattern
    is: `w.setProperty("state","warn"); w.style().unpolish(w); w.style().polish(w)`.
    [Qt forum recalc].
  - Keep selectors **generic and shared**; style only properties that must change, so
    parsing stays short and rule-matching is fast. [Qt forum embedded perf].
  - **Never restyle inside a fast loop or a live-plot callback.**
- Specificity/cascade facts to design the sheet around (from the Qt manual):
  specificity is CSS2 `(#id=a, attrs/pseudo=b, type=c)`; "**the widget's own style sheet
  is always preferred to any inherited style sheet, irrespective of specificity**"; later
  rules win when specificity ties. Prefer object-name/property selectors over deeply
  nested descendant selectors. [Qt style-sheet syntax].

### 2.2 Keep the event loop responsive (the app already does this)
- The GUI thread handles input, painting, and the event loop; any blocking call there
  freezes the UI. Long I/O (VISA, serial, HV ramps, camera grabs) must run off-thread.
  [Real Python QThread], [KDAB 8 rules].
- Correct pattern: worker `QObject` + `moveToThread(thread)` + signals/slots; **never
  touch Qt widgets from a worker thread** ("Qt GUI classes are not thread-safe... always
  use signals and slots"). `moveToThread` fails if the worker has a parent, and the
  worker must be moved *before* `start()`. [linuxvox], [KDAB 8 rules].
- superqt provides ready-made **signal throttling/debouncing** and an
  **`ensure_main_thread`** decorator — use throttling to cap how often high-rate device
  telemetry repaints widgets (see §2.4). [superqt].

### 2.3 Efficient custom painting for the colored-rail scan tree
- For a tree/table with per-row status rails/badges, **paint in a
  `QStyledItemDelegate.paint()` with `QPainter`; do NOT embed real widgets per cell.**
  Qt docs + community guidance: delegate painting "is the most performant way," and
  creating actual widget instances per cell "would be expensive." Hold at most one
  reusable widget in the delegate and re-init it per paint if you must mimic a widget.
  [QStyledItemDelegate], [codeofzion delegate].
- In `paint()`: fill a small rail `QRect`, draw text/icon, keep it allocation-free
  (pre-build `QColor`/`QPen`/`QBrush`/`QFont` once, reuse them — pyqtgraph gives the same
  advice, §2.4). Call `super().paint()` for the base item then overlay the rail.
- Model updates should emit **narrow `dataChanged(topLeft, bottomRight, roles)`** signals
  so only affected rows repaint, not the whole view.

### 2.4 pyqtgraph live-plot performance (primary docs)
For the scope/live traces, from pyqtgraph docs (`PlotDataItem`, config options):
- **Downsample:** `plot.setDownsampling(ds=N, auto=True, method='peak')`. `ds` reduces
  displayed points by factor N (`ds=1` disables); `auto=True` picks ds from the visible
  range; methods: `'subsample'` (fastest, least accurate), `'mean'`, `'peak'` (best
  visual, slower/default). For a scope trace, `auto=True, method='peak'` preserves
  glitches while cutting draw cost. Set it on the **PlotItem**. [PlotDataItem].
- **Clip to view:** `plot.setClipToView(True)` — "can result in significant performance
  improvements" by only drawing what's on screen. [PlotDataItem].
- **Pen width = 1:** "All wider pens cause a loss in performance." Use width-1 pens for
  live traces; reserve thick pens for static/exported plots. [PlotDataItem].
- **Antialiasing off for live** (`pg.setConfigOptions(antialias=False)` globally, or per
  item): "Enabling antialiasing... at the cost of reduced performance." Turn AA on only
  for a paused/final view. [PlotDataItem], [config options].
- **`skipFiniteCheck=True`** on setData when data is guaranteed finite — skips the NaN/inf
  scan (but "unpredictable behavior" if a non-finite value sneaks in). [PlotDataItem].
- **Reuse pens/brushes:** pass pre-created `QPen`/`QBrush` objects, not string specs, to
  avoid creating "many internal" objects each update. [PlotDataItem].
- **`useOpenGL` is a maybe, not a default win.** `pg.setConfigOptions(useOpenGL=True)`
  applies to 2D lines only; pyqtgraph's own docs/issues report OpenGL "slows things down"
  on Windows and has bugs on macOS/Linux — there are open issues about OpenGL performance
  regression on Windows. **Benchmark on the actual lab PC before enabling; do not enable
  blindly.** [config options], [pyqtgraph #2227], [pyqtgraph #2257].
- **Batch/throttle updates:** don't repaint per sample. Buffer incoming data and refresh
  on a `QTimer` at a fixed rate (e.g. 30–60 Hz) or via superqt throttling — the human eye
  gains nothing above that and it decouples acquisition rate from paint rate. [superqt].

---

## 3. PRACTICAL PYSIDE6 THEMING

### 3.1 Structure a maintainable QSS system (the app is already close)
- **Token/palette dict → single QSS template** rendered per theme is the right pattern,
  and `gui/style.py` already does exactly this (`LIGHT`/`DARK` dicts → `build_qss(p)`).
  Light and dark share layout and differ only in color tokens — keep this.
- Recommended token groups to formalize (so panels reference tokens, not literals):
  - **Neutrals/surfaces:** `bg`, `panel`, `panel_alt` (a 3rd surface step), `border`.
  - **Text:** `text`, `muted`, `disabled`.
  - **Accent:** `accent`, `accent_dark`, plus a **dark-mode-desaturated** accent (§1.4).
  - **Semantic status:** `ok`, `warn` (ADD amber), `critical`, `info` — one set, both
    themes, chosen to be legible on either base (current `OK_GREEN`/`WARN_RED` are the
    seed; add warning-amber and an info token).
  - **Spacing scale + radii + type sizes** as Python constants reused in QSS and in
    layout code (`layout.setSpacing`, `setContentsMargins`) so QSS and hand-built layouts
    agree. This is what turns "looks styled" into "looks systematic."
- Keep it **one app-level sheet** (perf, §2.1). Expose semantic state via
  `objectName`/dynamic properties + `unpolish/polish`, not per-widget `setStyleSheet`.

### 3.2 What superqt and qtawesome give you
- **qtawesome:** iconic fonts (bundles Font Awesome, Material Design Icons `mdi`/`mdi6`,
  Phosphor, Remix, Codicons, Elusive) as `QIcon`s, addressed by `prefix.name`
  (e.g. `qta.icon('mdi6.power')`). Icons are recolorable/animatable at runtime, so they
  can follow theme + semantic status color programmatically (pass `color=`, `color_active=`).
  Works with PySide6 via the QtPy layer; `qta-browser` lists all glyphs. A single
  consistent icon set is a big "premium" win vs mixed ad-hoc icons. [qtawesome docs].
- **superqt:** fills gaps in QtWidgets. Directly useful here:
  - `QLabeledSlider` / `QLabeledDoubleSlider` / `QLabeledRangeSlider` — labeled + range
    sliders for scan bounds, thresholds, voltage limits.
  - `QToggleSwitch` — modern on/off affordance (e.g. enable/arm toggles).
  - `QEnumComboBox`, `QSearchableComboBox`, `QColormapComboBox`, `QElidingLabel`,
    `QCollapsible`, `QFlowLayout`, `QLargeIntSpinBox`.
  - Utilities: **signal throttling/debouncing**, **`ensure_main_thread`**, thread
    workers, `QMessageHandler`, error-dialog context managers. [superqt widgets/utils].
  - Note `QIconifyIcon` in superqt is an alternative icon route; pick **one** icon system
    (qtawesome vs iconify) and standardize to avoid mixed styles.

### 3.3 QSS pitfalls to brief the GUI dev on
- **Specificity surprises:** a widget's *own* stylesheet always beats an inherited app
  sheet regardless of specificity; ties are broken by rule order (last wins). Avoid
  setting per-widget sheets that silently override the theme. [Qt style-sheet syntax].
- **Subcontrols need full re-specification:** styling e.g. `QComboBox::drop-down` or
  `QScrollBar::handle` often forces you to redraw the *whole* control's subcontrols,
  because touching one can drop the native rendering of others. Style complete controls,
  not fragments. [Qt style-sheet syntax].
- **`qproperty-` runs once at polish**, so it can't react to pseudo-states like `:hover`;
  use real pseudo-state selectors for interactive changes. [Qt forum].
- **Platform inconsistency:** QSS-styled widgets bypass the native style, so a fully
  themed app looks identical cross-platform (good for consistency) but loses native
  behaviors (e.g. native focus rings, high-DPI subcontrol metrics). Test on the actual
  Windows lab machine + high-DPI. Mixing QSS with a custom `QStyle`/`QProxyStyle` is where
  KDAB warns things get slow and fragile — pick one primary approach. [KDAB], [Qt].
- **Don't re-`setStyleSheet` for state** — see §2.1 (dynamic property + polish instead).

---

## RECOMMENDATIONS FOR THIS APP (actionable for the meeting)

1. **Formalize a design-token module.** Extend `gui/style.py` from color-only dicts to
   full tokens: surfaces (3 steps), text, accent (+ dark-desaturated variant),
   **semantic status set `ok/warn/critical/info`** (add amber warning + info; today it's
   only green/red), a **spacing scale (4/8/12/16/24/32)**, radii, and a **type scale**.
   Reuse the spacing/type constants in both QSS and layout code.
2. **Adopt ISA-101 "quiet-by-default" coloring.** Panels neutral/gray at rest; saturated
   amber/red only for HV-on, faults, out-of-range, interlock, lost-connection — aligns
   with the app's safety rules and reads as professional instrumentation.
3. **Tabular numerals for every live readout** (voltage, current, position, ToT, timers)
   via `font-variant-numeric: tabular-nums` / Qt font feature, mono fallback only if
   needed. Kills digit jitter — cheap, high perceived-quality gain.
4. **State via dynamic properties + `unpolish/polish`, never per-update `setStyleSheet`.**
   Keep the single app-level sheet. This is both the perf-safe and the maintainable path.
5. **Colored-rail scan tree = `QStyledItemDelegate.paint()` with pre-built pens/brushes**,
   no per-cell widgets; emit narrow `dataChanged` so only changed rows repaint.
6. **pyqtgraph live-plot preset:** `setDownsampling(auto=True, method='peak')` +
   `setClipToView(True)` + width-1 pens + `antialias=False` while live (AA on when
   paused) + `skipFiniteCheck=True` for known-finite buffers + a 30–60 Hz `QTimer`/
   throttled repaint. **Benchmark `useOpenGL` on the lab PC before enabling** — it
   regresses on Windows in pyqtgraph's own issue tracker.
7. **Standardize on qtawesome (`mdi6`) for one consistent, theme-colored icon set**, and
   use superqt `QToggleSwitch`/labeled+range sliders + signal throttling where they fit.
   Don't mix qtawesome and superqt `QIconifyIcon` icon styles.
8. **Dark mode:** keep off-white text and no pure black (already correct); add a
   slightly **desaturated dark accent** token; convey elevation with surface steps +
   borders, not shadows.

---

## Sources

Style & beauty
- Material Design — Spacing methods (8dp grid): https://m2.material.io/design/layout/spacing-methods.html
- 8pt grid system (UX Planet): https://uxplanet.org/everything-you-should-know-about-8-point-grid-system-in-ux-design-b69cb945b18d
- Spacing best practices / internal ≤ external (Cieden): https://cieden.com/book/sub-atomic/spacing/spacing-best-practices
- Typography in design systems (EightShapes / Nathan Curtis): https://medium.com/eightshapes-llc/typography-in-design-systems-6ed771432f1e
- Tabular numbers in CSS — font-variant-numeric vs monospace (DEV): https://dev.to/alanwest/tabular-numbers-in-css-font-variant-numeric-vs-monospace-hacks-25cn
- MDN — font-variant-numeric: https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric
- Tailwind — font-variant-numeric (where to use tabular): https://tailwindcss.com/docs/font-variant-numeric
- Material Design 3 — Color roles (no success/warning role; add your own): https://m3.material.io/styles/color/roles
- Semantic color ownership / brand vs functional (Design Systems Collective): https://www.designsystemscollective.com/rethinking-semantic-color-ownership-in-design-systems-is-success-a-border-deaba5bc93ba
- Dark-mode dashboard patterns (AYDesign): https://www.aydesign.ai/blog/dark-mode-dashboard-design-patterns-2026
- ISA-101 high-performance HMI guide: https://plcprogramming.io/blog/hmi-design-best-practices-complete-guide
- "Going Gray: A New HMI Standard" (control.com): https://control.com/technical-articles/going-gray/
- High-Performance HMI (RealPars): https://www.realpars.com/blog/high-performance-hmi
- Industrial HMI grayscale / alarm management: https://industrialmonitordirect.com/blogs/knowledgebase/high-performance-hmi-design-principles-for-industrial-control

Performance
- Qt 6 — The Style Sheet Syntax (selectors, specificity, cascade): https://doc.qt.io/qt-6/stylesheet-syntax.html
- KDAB — "Say No to Qt Style Sheets" (QSS cost, polish/reparent, QStyle alternative): https://www.kdab.com/say-no-to-qt-style-sheets/
- Qt Forum — forcing restyle via unpolish()/polish(): https://forum.qt.io/topic/1314/how-to-force-a-style-sheet-recalculation
- Qt Forum — improving QSS/CSS performance (share generic rules): https://forum.qt.io/topic/74733/how-to-improve-qt-s-qss-css-performance-on-embedded-devices
- KDAB — The Eight Rules of Multithreaded Qt: https://www.kdab.com/the-eight-rules-of-multithreaded-qt/
- Real Python — Use PyQt's QThread to prevent freezing GUIs: https://realpython.com/python-pyqt-qthread/
- Modifying Qt GUI from a worker thread safely (linuxvox): https://linuxvox.com/blog/modify-qt-gui-from-background-worker-thread/
- Qt 6 — QStyledItemDelegate (paint()/sizeHint(), delegate painting): https://doc.qt.io/qt-6/qstyleditemdelegate.html
- Custom QTreeView delegate painting (codeofzion): https://codeofzion.wordpress.com/2012/04/27/custom-qtreeview-with-multiple-custom-widgets-as-rendering-delegates/
- pyqtgraph — PlotDataItem (setDownsampling/setClipToView/pen/skipFiniteCheck): https://pyqtgraph.readthedocs.io/en/latest/api_reference/graphicsItems/plotdataitem.html
- pyqtgraph — Global configuration options (useOpenGL, antialias): https://pyqtgraph.readthedocs.io/en/latest/api_reference/config_options.html
- pyqtgraph issue #2227 — OpenGL on Windows slows things down: https://github.com/pyqtgraph/pyqtgraph/issues/2227
- pyqtgraph issue #2257 — PlotCurveItem OpenGL performance regression: https://github.com/pyqtgraph/pyqtgraph/issues/2257

PySide6 theming / libraries
- qtawesome — Usage (prefix.name, mdi/mdi6, coloring, PySide6): https://qtawesome.readthedocs.io/en/stable/usage.html
- qtawesome — GitHub (bundled fonts, qta-browser): https://github.com/spyder-ide/qtawesome
- superqt — home (widgets + utilities index): https://pyapp-kit.github.io/superqt/
- superqt — widgets list: https://pyapp-kit.github.io/superqt/widgets/
