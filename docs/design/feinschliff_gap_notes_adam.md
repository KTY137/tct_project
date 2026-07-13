# Feinschliff gap notes — Adam's own eyes (capture set ui_audit_20260712T184707Z)

Personal panel-by-panel review against the v5 bar (sleek, subtle translucency,
Apple-app feel). Dark = primary theme. Capture caveat: headless font fallback
fakes terminal-caps — glyph/case quality is NOT judged here, composition and
color are real.

## Shell / chrome (both themes)
- STACKED CHROME (Codex loss #1 confirmed live): menubar + toolbar + device
  ribbon + tab row + breadcrumb + panel title ≈ 200px before content.
- Device ribbon OVERFLOWS at 1440px — horizontal scrollbar under the ribbon;
  BIAS/HV strip clipped at right edge. Composition bug, not taste.
- Triple redundancy: tab "Motor Stage" + breadcrumb "TCT Control · Motion" +
  panel title "Motor Stage".
- Toolbar: green CONNECT ALL button = color spent on a command; color should
  encode state only. Icon+text toolbar buttons read Win95, not sleek.
- LIGHT theme: position readout renders as a black slab (dark plot styling
  leaks into light) — pasted-on effect; plot titles washed out/low contrast.
- Statusbar bottom "DISCONNECTED" plain text, duplicated by toolbar STATE chip.

## Motor Stage (dark)
- Left column = form stack (Position / Jog / Absolute Move groups), right =
  stage view. Stage view is the natural hero and already ~55% width — good
  base for D2's "stage view hero + command tray".
- Jog cluster: per-axis colored accent brackets on buttons (cyan/pink/purple
  X/Y/Z) — charming but busy; step-size segmented row + custom spin cramped.
- Position group when OFFLINE is a large empty slab with em-dashes — honest
  (quiet-nominal ok) but prime real estate spent on nothing; wants a compact
  offline state.
- MOVE TO button amber-framed (motion=amber law respected).

## Reference Monitor (dark)
- Composition already half-way to D2 (metric capsules + waveform + command
  row). Gaps: capsules are heavy framed half-width slabs, not floating chips;
  GroupBox header + inner frame = double frame around the plot.
- Empty state fakes a live plot: full grid + 0.1–0.9 axes while OFFLINE.
  Wants a designed empty state (dim canvas + "Monitor offline" center note),
  not fake axes. (Law 7 adjacent: UI shouldn't imply data that isn't there.)

## Camera (dark)
- Composition decent: camera well left, inspector column right (Acquisition /
  Image Processing / Trigger / Camera Info).
- **LAW VIOLATION: "CAMERA NOT CONNECTED" rendered RED** — red is HV/abort
  only. Offline is neutral, not danger. Fix in any v5 wave regardless.
- Camera well only ~40% of panel height — 4 stacked groups below (Histogram,
  Beam Stats, Frame Info, View&Capture) crush the hero. D2 full-bleed well +
  overlay rail is right.
- 7 identical "NO FRAME YET" beam-stat capsules = offline noise; Frame Info
  tile labels truncate ("T (…", "GAI…"). Histogram draws a fake flat line
  while offline.

## Oscilloscope (dark)
- Trace is already the hero (~70% width) — right base. But the right rail
  OVERFLOWS: headers truncated ("LIVE RE…", "…MEASUR…"), DUT-analysis
  capsules clipped at the right edge, "DISPLAY & SCALE" cut at bottom.
  Composition bug: rail content wider+taller than the rail.
- Channel cards with color spines (amber CH1 / cyan CH2) = good bones.
- Bottom command row mixes classes: LIVE/SINGLE (acquisition) + AVG OFF /
  CURSOR OFF (state toggles) + EXPORT CSV / TEST / LIST VISA (utilities).
- Empty plot fakes full grid + −200..200 ns axes while offline (same
  fake-axes pattern as RefMon).

## Laser / Trigger (dark)
- Manual-laser truth banner (amber) = law-conform, keep.
- **LAW VIOLATION: "OUTPUT STATE UNKNOWN" chip in red** — unknown ≠ danger;
  red is HV/abort only. Should be amber/neutral-unknown.
- "LOAD 50 Ω" chip GREEN = decorative green on a nominal config value
  (quiet-nominal violation; green is also sim-adjacent — never decorative).
- Comically wide fields: FREQUENCY input spans ~1200px for "1000.00 Hz".
  Bottom half of the panel is empty void. Wants D2's two-sheet split
  (warning record card + compact wavegen command sheet).

## Scan Viewer (dark)
- CLOSEST TO V5 ALREADY: designed empty state (map icon + "configure in the
  Scan Planner"), metric capsules, Z-focus as collapsed bottom sheet.
- Gaps: 4× "NO RUN YET" repetition; tiny cryptic icon-only buttons top-right;
  PAUSE/ABORT live in a bottom row that will fight the run-HUD idea (D2:
  overlay HUD on the map during run).

## Scan Planner (dark)
- Already the 3-column Mac shape (palette / recipe / preflight inspector) —
  D2 move #7 is half-done. Right rail (Points/Runtime/Data/Travel/HV range
  tiles + Validate/Dry-Run + arm latch with explainer) is GOOD.
- **LAW VIOLATION: MOVE STAGE recipe row + its CONFIRM pill are RED** —
  motion must be AMBER; red is HV only (RAMP HV row red = correct).
- Recipe header row overlaps/clips the first tree row (PREFLIGHT half-cut).
- Pill zoo: 7 STEPS / 21 PTS / A CONFIRM / SNAKE… per-row noise adds up;
  needs a quieter row grammar (one accent per row max).

## Bias Supplies (dark)
- ALL OUTPUTS OFF (red, top-right) + OUTPUT OFF (0 V) (red, filled) both
  visible while DISCONNECTED = two loud red slabs in quiet-nominal state.
  Keep kill-switch always visible but outline/quiet until HV is live.
- Metric capsules (V measured / I / HV state) are small; D2's safety
  dashboard (measured V + HV state as the hero pair) is the right move.
- "LIMIT OK" rendered as a full-width bar-slab = odd; POLARITY group nearly
  empty; full-width compliance field again. Amber spine on Bias Voltage
  group reads as armed accent while idle — confusing.

## Calibration (dark)
- Full-width caps prose sentence + formula as the panel opener = engraving.
- "SAVED" chip GREEN (same green misuse). Giant explainer paragraph in caps
  inside the repeatability card. Full-width dropdown/fields. Bottom third
  empty. D2's two-procedure-cards-on-one-sheet is right.

## Monitor (dark)
- Composition already ≈ D2 (tile strip / table / history hero). Gaps:
  **"ALL NOMINAL" chip while zero readings exist = UI implying health with
  no data (law 8 adjacent)** — needs a NO DATA state. 4× "NO READING YET"
  noise; empty history plot fakes axes; large void between table and plot.

## Analysis (dark)
- Weakest panel: a near-empty void. Top strip has FOUR gray "NO …" chips
  (file/dataset/map/export) = quadruple offline noise; recents list is
  full-width with one entry; browse button bottom-right orphaned.
  D2's Finder/Preview pattern (recents source-list left, preview hero) is
  exactly the fix.

## Settings (dark)
- Actually decent dialog bones (tabs, footer actions). Gaps: VALID YAML +
  SAVED chips GREEN (misuse); full-width fields; caps prose explainers;
  config path breadcrumb shouting in caps.

## Device Manager (dark)
- 6 devices × (CONNECT + DISCONNECT buttons, each icon+text) = 12-button
  zoo in a 620px dialog; device names truncate ("OSCILL…", "WAVEF… GENER…").
  SIM chips hatched cyan = law respected. Wants status-dot rows + single
  toggle + Connect All primary.

## LIGHT THEME (contact sheet + shell)
- **Dark data surfaces pasted as holes**: Scope trace, RefMon waveform,
  Monitor history, Camera histogram stay black slabs in white panels —
  while StageView themes correctly light. PLOT_BG dark is a ratified law
  (viridis data ink) — so the FIX is a designed "instrument well" frame:
  rounded dark well, hairline bezel, glass header, inner shadow, so the
  dark plot reads as a deliberate instrument screen, not a hole.
- Motor position readout = black slab in light (same pasted effect, but
  this one is NOT a plot — should follow the panel surface).
- Red filled HV-off buttons even louder on white; green CONNECT ALL ditto.

## Cross-cutting synthesis (feeds v5)
1. Chrome stack must collapse (ribbon overflow bug is proof) — QML shell
   owns nav/status/commands; toolbar demoted (D2 #1, command palette idea).
2. Color discipline drifted: green on nominal chips/commands (connect,
   saved, valid, load) + red on non-danger (camera offline, output unknown,
   MOVE STAGE row). One law-sweep fixes many panels at once.
3. Offline noise pattern everywhere: N identical "NO X YET" capsules.
   Needs ONE designed offline state per panel (dim + single line), not
   per-widget placeholders.
4. Fake empty axes on offline plots (RefMon/Scope/Monitor) — replace with
   designed empty canvas.
5. Full-width form fields as default = the single biggest "not Apple"
   tell in every config panel; fields need intrinsic widths + right-aligned
   values (settings-pane grammar).
6. Dark plots in light theme need the instrument-well treatment (bezel).
7. Overflow/clipping bugs: device ribbon @1440px, scope right rail,
   planner recipe header, device-manager names, camera frame-info tiles.
8. Uppercase density: capture font exaggerates it, but the deliberate
   uppercase label roles + caps prose ARE in style.py — v5 reserves
   caps-mono for tiny eyebrows/quantities only (D2 #4), sentence case
   for prose/commands. Verify on real display.
