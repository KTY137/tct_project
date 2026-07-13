# Codex Style Audit 2026-07-13

Scope: S1 visual style audit. Fresh rendering was attempted with the requested
venv/offscreen command, but the venv launcher still points at a missing
WindowsApps Python 3.10 path and fails before Python starts. I used the freshest
complete capture set instead: `artifacts_claude/ui_audit_20260712T231348Z`.
Inspected both contact sheets plus representative shell, motor, camera, scope,
planner, settings, and dark/light panel captures.

Out of scope here because Adam's notes already cover them: the W1 state-color
ladder, DWM backdrop/acrylic, fake empty axes, offline-noise copy, full-width
form recomposition, and the shell chrome collapse. This file only ranks style
system tweaks still worth making.

## Verdict

Not yet good enough for the stated sleek Apple-app north star. Dark mode is
coherent and usable, but it still reads like a well-tokenized Qt control panel:
many bordered rectangles, hard micro-labels, and weak surface hierarchy. Light
mode is more obviously flat because white panels, fields, cards, and toolbar
chrome are too close in value. For an engineering lab tool it is shippable; for
"premium Mac instrument cockpit" it needs one more shared-style pass.

Materials/shading: close, but too border-only. Line spacing: mostly acceptable;
the bigger problem is label role/case, not literal leading. Typography: base
families and mono numerals are sound, but the 10 px tracked label role is too
engraved when repeated across whole panels. Shadows/elevation: do not add real
drop shadows to hot plot/camera paths; the no-effect rule is correct. Padding
and alignment: internally consistent, but default button and table/list density
still feel bulkier than macOS controls.

## Ranked Tweaks

1. Reduce the micro-label engraving.
   Impact: high. Effort: small.
   Evidence: every panel repeats uppercase/tracked captions; in the captures,
   labels like form captions, chip text, table headings, and tile captions draw
   nearly as much attention as values. Exact style anchors:
   `TCT_app/gui/style.py:211` `FONT_METRIC_LABEL_PX = 10`,
   `TCT_app/gui/style.py:214` `TRACKING_METRIC_LABEL_PX = 1`,
   `TCT_app/gui/style.py:1086`-`1090` readout titles,
   `TCT_app/gui/style.py:1152`-`1156` cluster captions, and
   `TCT_app/gui/style.py:1216`-`1220` eyebrows. `panel_kit.py:113` and
   `panel_kit.py:320` also force uppercase at construction.
   Proposed trivial token pass: `FONT_METRIC_LABEL_PX = 11` and
   `TRACKING_METRIC_LABEL_PX = 0`. Keep `WEIGHT_METRIC_LABEL = 600` for true
   metric labels, but stop promoting ordinary form captions through the
   all-caps eyebrow role when each panel is touched.

2. Increase the surface ladder contrast before adding any more "glass".
   Impact: high. Effort: small.
   Evidence: cards, group boxes, and metric tiles are distinct by border, not
   by material depth. Light mode especially makes `panel`, `raised`, `well`,
   and `canvas` read as a pale grey stack with little physical hierarchy.
   Edit points: light tokens at `style.py:351`, `style.py:357`,
   `style.py:397`-`398`; dark tokens at `style.py:433`, `style.py:435`,
   `style.py:447`-`448`; group/card consumers at `style.py:615`-`620`,
   `style.py:1080`-`1082`, and `style.py:1196`-`1199`.
   Proposed trivial values to test:
   light `canvas #E9EDF4 -> #E6EBF3`, `raised #F4F7FB -> #F8FAFD`,
   `well #EDF1F7 -> #E8EEF6`; dark `raised #192134 -> #1B253A`,
   `well #0E1420 -> #0B111C`, `hairline #222B3E -> #27344A`.
   This is not a backdrop request; the DWM path already exists.

3. Add an opt-in static-card depth style; keep plot/camera containers flat.
   Impact: medium-high. Effort: medium.
   Evidence: `QGroupBox` and `QFrame#cardPane` intentionally use uniform
   borders for hot-path safety (`style.py:608`-`620`, `style.py:1194`-`1199`),
   and `FigureCard` correctly forbids effects on plots/camera
   (`panel_kit.py:346`-`350`). That is right for plots, but static cards in
   Settings, Device Manager, Calibration, and side inspectors could carry a
   stronger machined edge without repaint risk.
   Proposal: add an opt-in selector such as
   `QFrame#cardPane[depth="raised"] { background: {p['raised']};
   border-top-color: {p['edge']}; }`, set only by `panel_kit.Card`, not
   `FigureCard`. Do not add `QGraphicsDropShadowEffect`; `style.py:498`-`505`
   is the correct guardrail.

4. Make default secondary controls denser.
   Impact: medium. Effort: small.
   Evidence: toolbar buttons, Device Manager rows, Settings actions, and panel
   utility buttons have a rectangular Qt-button weight even after the token
   pass. The global default button rule is `style.py:683`-`690`: raised fill,
   strong hairline, 8 px-ish vertical and 16 px horizontal padding, weight 560.
   Proposed trivial QSS pass: default/secondary `QPushButton` padding
   `{SPACE_SM - 2}px {SPACE_MD}px` instead of `{SPACE_SM - 1}px {SPACE_LG}px`,
   and `font-weight: 540`. Keep primary, motion, and danger actions at the
   current larger affordance. This should improve density without reworking
   individual layouts.

5. Give tables and trees a slightly richer row grammar.
   Impact: medium. Effort: small.
   Evidence: Device Manager, Monitor, Settings, and Planner still show a
   spreadsheet-like flatness. Current table/list anchors are
   `style.py:998`-`1006` and `style.py:1013`-`1019`.
   Proposed trivial QSS pass: header background `p['strip']` instead of
   `p['material']`; item padding `4px 6px` instead of `3px 2px`; hover
   background `p['raised']` with no accent. This keeps data dense but removes
   the raw Qt table feel.

6. Stop polishing the old shell chrome beyond a one-line density fix.
   Impact: medium. Effort: small now, larger later.
   Evidence: `QTabBar::tab` at `style.py:847`-`856`, `QMenuBar` at
   `style.py:867`-`872`, and `QToolBar` at `style.py:884` create stacked
   navigation that no token tweak can make Apple-like. The planned chrome
   collapse should own the real fix.
   Stopgap only: reduce tab padding to `{SPACE_SM - 3}px {SPACE_MD}px` and
   selected tab weight from 600 to 560. Do not spend more design time on this
   legacy chrome.

7. Keep the plot/camera shadow policy as-is.
   Impact: medium. Effort: none.
   Evidence: camera, scope, reference monitor, and monitor plots need stable
   repaint cost. The existing no-effect rule in `style.py:498`-`505` and
   `panel_kit.py:346`-`350` is the correct tradeoff. Depth should come from
   the instrument-well framing already planned elsewhere, not from shadows or
   glow on live widgets.

## Area Checks

Materials/shading depth: not good enough until items 2 and 3 land.
Typography: not good enough until item 1 lands; base `FONT_MD = 13` at
`style.py:90` and `FONT_HINTING = "vertical"` at `style.py:137` are fine.
Line spacing/rhythm: good enough for now; the visible problem is role misuse,
not a missing global line-height token.
Shadows/elevation: good enough if the project stays disciplined and avoids
effects on hot widgets.
Padding/alignment consistency: consistent but still too Qt-dense; item 4 is
the lowest-risk shared improvement.
Overall Apple-styleness: improved but not there. Planner and Scan Viewer are
closest; Camera, shell chrome, and Settings form grammar expose the remaining
Qt ancestry fastest.
