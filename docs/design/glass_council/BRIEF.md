# Glass Council — shared case brief (2026-07-13 night)

**Convened by:** Adam (lead detective, project_tct) on Kaya's order:
"setz da Odins Team zusätzlich drauf an eine effektive Lösung für die
Glas Solution zu erzeugen, nutz alle Agenten."

**Read this first, then your persona file, then work your lane.**
project_tct is **READ-ONLY** for every council member; your ONLY
deliverable is `docs/design/glass_council/<your-name>.md`. No code
edits — a separate empirical investigation (Noah, project_tct crew) is
live in `gui/backdrop.py`/`gui/style.py`; do not collide with it.

## The case

Goal (Kaya-ratified design direction): a real visionOS-like glass look
for the TCT lab cockpit — Windows 11 DWM materials (Mica/Acrylic)
showing through the app, with fluent motion. PySide6 6.11 + pyqtgraph +
**QtAds docking** (13 panels, GL plot islands, camera raster).

**Symptoms (today):**
1. Afternoon, pixel-measured: toggling Acrylic on/off is **pixel-equal**
   in the main window — the material makes zero visible difference. A
   photo-confirmed opaque "barrier" exists somewhere in the stack.
2. Tonight, Kaya live: backdrop region renders **completely WHITE**
   everywhere incl. the (simpler) theme-settings window. It visibly
   worked at some point earlier (transparency was seen after the
   opacity-pin fix).
3. Kaya's read: "das sitzt tiefer" — likely the same structural cause
   as the main-window barrier, not merely tonight's commits.

## What the tct crew already knows (do not rediscover)

- The DWM chain exists and once produced visible transparency:
  window-level backdrop attach in `gui/backdrop.py`
  (DWMWA_SYSTEMBACKDROP_TYPE-class), QSurfaceFormat alpha at startup,
  centralWidget translucency, an **opacity pin** (WS_EX_LAYERED
  suppresses DWM materials — discovered and fixed once already), a
  canvas rgba fill via style tokens `BACKDROP_CANVAS_ALPHA≈0.82` /
  `PANEL_GLASS_ALPHA≈0.55`, and a `glassPane` opt-in registry for
  panels.
- **Ratified constraints:** no live MultiEffect/ShaderEffect glass (must
  degrade on software/RDP path); pre-blended color-mix tokens are the
  fallback look; safety-critical controls stay QWidget, single
  implementation; classic shell must remain a functional fallback.
  Roadmap: QWidget tree + QQuickWidget chrome islands (option a); a QML
  U-track starts later from the `polish-freeze` tag.
- Findings doc of the afternoon investigation:
  `docs/design/glass_gap_findings.md` (read it). Onscreen pixel-capture
  harness exists: `TCT_app/scripts/capture_onscreen.py` (compositor-
  true screenshots; produced the pixel-equal verdict).
- Suspected structural barrier: **QtAds dock containers** paint opaque
  backgrounds our QSS canvas rules never reach; also candidate: the
  window dark-mode flag (DWMWA_USE_IMMERSIVE_DARK_MODE) lost →
  light-mode Mica = looks white.

## Mandate expansion (Kaya, verbatim): "kannst ruhig einmal big time
denken. Das wird wichtig für den seed, und der vollständigen QML
Migration."

So: do NOT design a QWidget patch. Design the **material system** for
three horizons at once: (1) the classic QWidget cockpit today, (2) the
full QML migration (U-track U0–U6: QML shell + viewmodels + QWidget
safety/GL islands — where QML actually makes real glass EASIER:
scenegraph alpha, Qt Quick materials, per-item layers), and (3) the
platform seed — the material/token contract LabControl inherits. The
right answer may well be: minimal honest glass on the classic shell +
the REAL glass architecture specified for the QML shell, with one token
vocabulary spanning both.

## What the council must produce

An **effective, robust glass solution** — not a patch. The winning
answer must state: the mechanism (which API/layer produces the visual),
how it survives the QtAds dock stack + GL islands + camera raster, its
degradation ladder (RDP / transparency-off / battery saver / Win10 /
Linux where DWM does not exist → the token-based fake-glass fallback),
its cost, and how it is regression-tested (the pixel harness).

Honesty rule: if real per-pixel DWM glass through a full QtAds cockpit
is NOT robustly achievable, say so and design the best honest
alternative (e.g. window-level material + selective glass zones +
pre-blended tokens) rather than promising a look that dies on the
first RDP session.
