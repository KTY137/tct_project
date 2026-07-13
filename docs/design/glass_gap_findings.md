# Glass gap findings — why the theme editor "looks like glass" and the rest doesn't

Noah, 2026-07-13. Companion to the C2/C3 backdrop work (`gui/backdrop.py`,
`gui/style.py`). Read `gui/backdrop.py`'s module docstring first — most of
the vocabulary here (canvas vs content, `_CANVAS_MODE`) is defined there.

## 1. Mechanism: CONFIRMED, with one correction

Adam's hypothesis is right in spirit, wrong in one detail. Every top-level
window in this app — `TCTMainWindow` (`tct_gui.py:254`), `ThemeEditorDialog`,
`SettingsWindow`, and `_DetachedWindow` (torn-off tabs) — calls
`style.apply_window_backdrop_to(self)` identically at construction, and every
one of them is re-touched identically by `apply_window_backdrop(app)`'s
fan-out on every `_toggle_theme()`. **The backdrop plumbing was never
selective — it was uniformly defeated everywhere**, main window included,
not just "blocked by panels while the editor got through." The barrier was
one layer *before* panels even enter the picture.

## 2. Barrier list (paint order, outermost first)

1. **`QMainWindow, QDialog { background: {p['bg']}; }`** (`gui/style.py`
   `build_qss`) — a fully opaque hex, unconditionally, on literally the same
   selector `gui.backdrop._prepare_window_canvas` had just set a transparent
   `Window`-role palette on. This is the actual bug: two code paths agreeing
   on nothing, one painting exactly where the other cleared. Root cause,
   confirmed by an onscreen capture Adam ran (`artifacts_claude/
   ui_onscreen_20260713T125721Z/`): `acrylic_default_A_dark.png` is pixel-
   identical to `none_default_A_dark.png` on the **main window** — not just
   "panels block it," the window canvas itself never showed the material at
   all, anywhere, before this fix.
2. `QWidget#mainShell` — same opaque rule, same fix.
3. `QFrame#cardPane` / `#channelCard` (every `panel_kit.Card`, i.e. every
   panel) — opaque `p['panel']`. **Deliberately left untouched** — see §3.
4. Plots/camera — untouched, already independently opaque (own `pg.PlotWidget`
   background / frame paint), never actually at risk (see §3).

## 3. What I wired — and what I did NOT

`gui/style.py`: `_canvas_fill(p)` + `BACKDROP_CANVAS_ALPHA = 0.82`. The
`QMainWindow, QDialog` / `#mainShell` canvas rule now calls `_canvas_fill(p)`
instead of `p['bg']` directly: byte-identical opaque hex when
`get_window_backdrop() == "none"` (the shipped default), an `rgba()` alpha
fill otherwise. This is genuinely the existing `_CANVAS_MODE` idea's missing
half: `backdrop.py`'s `_prepare_window_canvas` handles the *Qt-attribute*
side (`WA_TranslucentBackground` + transparent palette); this QSS change is
the *paint* side that was never told about it.

**Scope stops at the canvas, not the panel role**, and this is not a
timidity call — it matches the *original ratified design intent* recorded in
`artifacts_claude/tct_bias_glass_ab.html`'s own footer (the Glass preset's
source artifact): *"Seite B nutzt `backdrop-filter`; im Qt-Port entspricht
das DWM-Backdrop (Fensterebene, gebaut) + Fake-Glas-Tokens (Panel-Ebene) +
QML-Shader nur dort, wo echtes Blur über App-Inhalt gebraucht wird."* —
window level gets real DWM backdrop, **panel level gets the fake/opaque
glass tokens on purpose** (exactly the existing `chrome`/`strip`/`edge`
pre-blend the "Surface tint" slider already drives), real blur reserved for
a future QML shader path. A `QFrame#cardPane` selector also cannot
distinguish a plot/camera-hosting Card from a plain one — extending alpha
there risks the hard "content stays opaque" rule for the one thing that
actually matters (live readouts), for a look the source material never
asked panels to have anyway. If Kaya wants panels to go translucent too,
that needs a per-instance opt-in (a property, not a blanket selector), and
is a new decision, not a plumbing gap — flagging it rather than deciding it.

**Byte-identical-when-off guard**: `tests/test_theme_editor.py::
test_canvas_fill_is_byte_identical_when_backdrop_is_none` (default state,
QSS text-diffed) + `test_canvas_fill_never_touches_panel_or_readout_surfaces`
(cardPane stays a flat hex regardless of backdrop state).

## 4. Renders + comparison

`scripts/capture_panels.py` run once (it already captures classic
`shell_full.png` *and* `TCT_QML_SHELL=1`'s `qml_chrome.png` per theme in one
pass — running it "twice" would just be the same code path twice) with the
Glass preset + `backdrop=acrylic` pre-applied:
`artifacts_claude/ui_audit_glassgap_20260713T130124Z/` (`{light,dark}/*.png`,
manifest.txt). Plus a supplementary direct A/B I captured since
`capture_panels.py`'s panel list doesn't include `ThemeEditorDialog`:
`.../supplementary/theme_editor_glass_{acrylic,none}_dark.png`.

**Say this loudly: none of these offscreen PNGs show glass.** `QT_QPA_
PLATFORM=offscreen` has no compositor — DWM blur is compositor-side, full
stop, by this module's own design (see `gui/backdrop.py`'s docstring). What
an offscreen render *can* show is whether the QSS text is right, and whether
the alpha channel is actually being multiplied against something (proof the
plumbing fired, not a look preview): pixel-sampling the theme-editor
supplementary pair's corner margin gives `#080e1d` (acrylic) vs `#080f1d`
(none) — a real, measurable difference, one unit of green, from `rgba(8,
15, 29, 0.82)` blending against Qt's own backing-store fill instead of a
desktop. That's the ceiling of what offscreen can prove.

`shell_full.png` (main window, either theme) shows **no visible change** —
correctly: the classic shell's tab content fills edge-to-edge (ribbon, tab
strip, one dense Card), leaving ~0px of exposed bare canvas for the alpha
fill to touch. The theme editor's own capture shows the same near-invisible
difference for the same reason: its Cards + preset list also fill almost the
whole client area, margins only being `SPACE_MD` (12px) wide. **Real
structural deltas vs the `design_assets/` references** (`Core-Components-
and-Interactions-1.png`, the Apple Vision Pro dashboard, the glassmorphism
sheet): those show heavy Gaussian blur (the artifact cites 26px) at the
*card* level with soft/borderless edges — QSS cannot add blur anywhere, only
let DWM's blur (window-level only) through; our cardPane keeps a crisp 1px
hairline border by design (cockpit instrument-panel look, not soft glass) —
that delta is intentional, not a bug.

## 5. Answering Adam's four questions

- **(a) Which windows get `apply_window_backdrop_to` today:** all of them —
  `TCTMainWindow` at construction (`tct_gui.py:254`), `ThemeEditorDialog`/
  `SettingsWindow`/`_DetachedWindow` at their own construction, and every
  live top-level window again via `apply_window_backdrop(app)`'s fan-out on
  every `_toggle_theme()`. Nothing was selective; see §1.
- **(b) Is the near-zero live delta on the main window fully explained by
  the opaque chain:** yes for the *pre-fix* pixel-identical result (§1) —
  the canvas was 100% blocked, full stop. **Post-fix it is only partially
  explained**: the canvas layer now passes alpha through correctly, but the
  main window's tab content leaves ~0 exposed canvas pixels (§4), so
  visually it will *still* look almost unchanged post-fix — that remainder
  is the panel-role question in §3, not a residual bug.
- **(c) What the capture tool should expect after this fix (regression
  check):** offscreen (`capture_panels.py`) — the QSS text for `QMainWindow,
  QDialog`/`#mainShell` should read `rgba(R, G, B, 0.82)` whenever
  `style.get_window_backdrop() != "none"`, exactly `p['bg']` otherwise
  (`tests/test_theme_editor.py`'s two canvas guards pin this precisely — a
  good post-fix regression baseline). Onscreen (`capture_onscreen.py`) —
  expect **no visible change on the packed main-window scenarios** (near-
  zero exposed canvas, as measured above); the theme-editor dialog and any
  view with visible margins/gaps are where a real difference should now be
  eyeball-checkable. `none_*` vs `acrylic_*`/`mica_*` should stop being
  pixel-identical **only** in those margin regions.
- **(d) Was the transparency Kaya saw live the window-OPACITY effect, not
  backdrop blur:** almost certainly yes, and this is a clean code-level
  distinction, not a guess — `setWindowOpacity()` (`WS_EX_LAYERED`, a
  uniform whole-window alpha blend, `gui/style.py`'s `apply_window_opacity`)
  is completely independent of the backdrop combo and, unlike backdrop
  *before this fix*, was never blocked by anything — it blends the already-
  opaque QSS-painted image as a whole, canvas and panels alike. It defaults
  to fully opaque (`DEFAULT_WINDOW_OPACITY == 1.0`), so "some transparency
  live, backdrop toggle barely mattering" is exactly what a persisted
  `theme/window_opacity < 1.0` from an earlier round-2 slider test would
  produce, independent of and prior to any backdrop testing. Five-second
  check for Kaya: View → Theme… → Material card → "Window opacity" slider
  position; if it reads under 100%, that's the transparency he saw.

## 6. Eyeball steps for Kaya (extends `docs/BENCH_CHECKLIST.md` §8)

Run §8's existing A1–B2 matrix first (unchanged). Then, specific to this
fix:
1. Set Window opacity to 100% first (isolate backdrop from §5(d)'s effect).
2. View → Theme… → select **Glass** preset → Apply. Backdrop combo → Acrylic
   → Apply.
3. Look at the theme editor dialog's own margins (around the preset list,
   around/between the Material/Colors/Typography/Radius cards, the footer
   strip below "Apply/Save as preset…/Close") — these are the exposed-canvas
   regions from §4; this is where the alpha fill should be visible as DWM
   material now showing through, where before this fix it was flatly opaque.
4. Repeat on the main window: expect little to no visible change per §5(b)
   — check window edges / any gap around the central tab widget instead of
   the tab content itself.
5. Canvas-mode A/B (`gui/backdrop.py`'s `_CANVAS_MODE`, still unevaluated):
   if step 3 shows an artifact (wrong redraw on resize, a flash), hand-flip
   `_CANVAS_MODE` to `"no_system_background"` and repeat steps 2–3 — nothing
   else needs to change for that swap (see that module's docstring).
6. Toggle dark ↔ light (B1 in §8) with Acrylic still active — canvas alpha
   should track the new palette's `bg` token, not freeze on the old one.
