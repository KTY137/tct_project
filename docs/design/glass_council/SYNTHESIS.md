# SYNTHESIS — the TCT glass architecture

| | |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-13 (night) |
| **Status** | Council synthesis — awaiting Kaya's three nods (§10) |
| **Commissioned by** | Kaya, verbatim, tonight — the five Vorschriften in §0 |
| **Inputs (binding)** | All 10 council lanes (`docs/design/glass_council/`: BRIEF, brokkr, thor, ratatoskr, ymir, baldr, volundr, tyr, frigg + loki attack pass + fenrir kill floor), `docs/design/glass_gap_findings.md`, `docs/DECISIONS.md` (2026-07-13 QML-hybrid entry), `docs/ROADMAP_MASTERPLAN.md` U-track, `docs/CAPABILITY_MODEL.md` (layering-law precedent), commit `2cf720b` (attr-20 fix, landed after the lanes wrote) |
| **Supersedes** | Nothing yet — §8 lists exactly what it re-ratifies once Kaya nods |

The key words **MUST**, **MUST NOT**, **NEVER**, and **LAW** are used as in
`docs/CAPABILITY_MODEL.md`: LAW is constitution-class, changed only with
Kaya's explicit per-change approval. References are **symbol-anchored**
(file + symbol); line numbers appear only with "at the time of writing".
Every symbol named here was verified against the working tree tonight.

---

## 0. The commission — five Vorschriften, verbatim, and what each one binds

Kaya, tonight, verbatim:

1. **"Die UI muss top aussehen können so dass glass wie in den referencen
   aussehen kann"** — the visionOS references in `design_assets/`
   (`Core-Components-and-Interactions-1.png`, the Vision Pro dashboard,
   the glassmorphism sheets) are the look target. Consequence: the
   architecture must contain a road to *real* frosted depth on the
   cockpit itself — not only on dialogs — and that road must be funded.
2. **"Es muss modular sein."** Consequence: contract/mechanism split. A
   panel declares a material *role*; it never paints a material. Tokens,
   tiers, and the component kit are the module boundaries; renderers are
   swappable underneath them (§2, §3).
3. **"Robust mit unserer Architektur und FastDAQ."** With sub-clause 3.1:
   **"Wir wollen unsere Python-Struktur, dass wir easy andere Driver dazu
   adden können, behalten."** Consequence: the safety laws are absolute
   and non-tradeable (§4); the fast-DAQ display islands render untouched
   and the material machinery never contends with acquisition (§4.3);
   the glass system is GUI-layer-only — `devices/`, `controller/`, and
   the capability spine of `docs/CAPABILITY_MODEL.md` are structurally
   unreachable from it (§4.4).
4. **"Koste es was es wolle — wenn wir irgendwelche Sachen sehr low-level
   implementieren müssen damit es klappt, dann machen wir das jetzt."**
   Consequence: the options the council parked as "too heavy" are back on
   the table where — and only where — they buy the reference look: the
   real-`QQuickWindow` shell pulled forward (§2.2.2), the Windows
   composition/host-backdrop interop layer (§2.2.3), the custom in-scene
   material renderer with baked frost (§2.2.2, G4 beat).
5. **"Zur Not ein eigenes modifiziertes UI-System genau dafür."**
   Consequence: the GlassShell + component kit (§2.2.2) *is* that system
   — our own material renderer, our own composition rules, built on Qt
   Quick primitives rather than forked from them, so it stays
   maintainable by one physicist + AI.

What money **cannot** buy (stated up front, because Vorschrift 4 does not
repeal physics): per-pixel DWM alpha through a QWidget top-level that
hosts any render-to-texture child. Thor's path-D mechanics
(`thor.md` §1.2, empirically anchored in-repo: the GL-free dialog blurs,
the GL-hosting main window measured pixel-equal) mean the classic cockpit
window can never show the real material while
`gui/stage_view.py::StageView3D`'s `GLViewWidget` or the
`gui/qml_shell.py` chrome `QQuickWidget` is alive in it. No budget
changes that. What Vorschrift 4 buys instead is the **shell where the
physics work for us**: a real `QQuickWindow`, where scenegraph alpha
reaches DWM first-class and the same GL/safety content lives in native
island windows that no longer poison anything (§2.2.2).

---

## 1. Ground truth this design stands on (post-council baseline)

Verified against the tree tonight — including changes that landed *after*
the lanes wrote:

1. **The WHITE emergency is fixed.** Commit `2cf720b`:
   `gui/backdrop.py::apply_backdrop` now takes `dark=` and asserts
   `DWMWA_USE_IMMERSIVE_DARK_MODE` (attr 20) *before* the material attach;
   `gui/style.py::apply_window_backdrop_to` relays the live theme mode and
   re-asserts on every theme switch; 4 regression tests incl.
   tint-survives-QSS-skip. Loki's minimum-program item 1 is therefore
   ~70 % landed. **Still open from that item:** re-assert on
   `QEvent.WinIdChange` (grep tonight: **zero hits in `TCT_app/`**) and on
   `WM_SETTINGCHANGE`/`WM_THEMECHANGED` — the HWND-recreation and
   OS-toggle halves of Fenrir K9/K5. That is beat **G-B1** (§6).
2. **QtAds is not instantiated in production** (`2cf720b` commit message
   confirms the council correction; Loki re-verified by grep). Everything
   this document says about dock containers is *forward design* for the
   future dock cockpit, not case forensics.
3. **The packed cockpit exposes ~0 canvas pixels**
   (`glass_gap_findings.md` §4). Per-pixel plumbing on the classic shell
   buys photons that do not exist.
4. **Path D is real and time-dependent** (`thor.md` §1.2/§3.1): raster at
   launch, GPU-composed after the first "3D" click on the Motor tab,
   back to raster if that tab is detached
   (`gui/detachable_tabs.py::_DetachedWindow`). This mechanically explains
   "worked earlier, dead later, no commit changed."
5. **The ratified DECISIONS entry is self-contradictory** (Loki
   CRITICAL-1): `docs/DECISIONS.md` 2026-07-13 "QML-hybrid boundary"
   promises "pre-blended tokens **+ window-level DWM backdrop**" *and* the
   `QQuickWidget`-chrome architecture — mutually exclusive on the same
   HWND by path D. And the U-track as written ends at U6 = "QML chrome
   default", which is still the `QQuickWidget` island inside a QWidget
   window — i.e. **the ratified roadmap never reaches real cockpit glass
   at any stage**. §8 names the re-ratification.
6. **The material APIs are settled** (Ratatoskr, condensed in Appendix B):
   attr 38 + attr 20 + `DwmExtendFrameIntoClientArea(-1)` is the shipping
   window mechanism (already `gui/backdrop.py`); `WS_EX_LAYERED` kills it
   (opacity pin at `gui/style.py::apply_window_opacity`, stays);
   `SetWindowCompositionAttribute` is permanently banned;
   `DWMWA_REDIRECTIONBITMAP_ALPHA` (build ≥ 26100) and
   `DWMWA_USE_HOSTBACKDROPBRUSH` (17) + `Compositor.CreateHostBackdropBrush`
   are the licensed low-level tier (§2.2.3).
7. **No tier enum exists yet** (grep `GlassTier|MaterialTier|decide_tier`:
   zero hits). Four incompatible vocabularies shipped in one night
   (Ymir `T0–T2`, Baldr `R0–R3`, Brokkr-B `REAL_BACKDROP/PREBLEND`,
   Tyr rungs 0–5). §3 publishes the one enum and deprecates the rest.

---

## 2. The architecture — one contract, two shells, one spine

**In one paragraph:** the material system is split into a
shell-independent **contract** (one `GlassTier` enum, token triples,
Baldr's Z-ladder of surface roles, and the safety invariants — all
resolved by a pure `decide_tier` function per top-level window), two
**renderers** that honor it — the **ClassicShell** (today's QWidget
cockpit: pre-blended TOKEN look on the cockpit window *by construction*,
real DWM material on RTT-free satellite windows; the eternal, always
shippable fallback) and the **GlassShell** (a real translucent
`QQuickWindow` cockpit on the D3D RHI with DWM material composited behind
the scene, QWidget safety controls and FastDAQ/GL islands hosted as their
own native windows via Qt 6.7+ `WindowContainer`, and an app-owned
component kit whose baked, textured frost is the *deterministic* glass
look on every rung where the OS material is absent) — plus one **event
spine** (WinIdChange / settings / session / power / device-loss
re-assertion, the path-D census, scan-aware deferral) and one **test
spine** (Tyr's verdict rungs, run at the honest cadence). The GlassShell
is Vorschrift 4's purchase: pulled forward into the U-track so the
reference look arrives with the hero panel, not after U6. The Windows
composition interop layer (host-backdrop brush, redirection-bitmap alpha)
is the licensed low-level tier: adopted where documented and cheap,
spiked as the contingency road if the GlassShell probe fails.

```
             ┌───────────────────────────────────────────────────────────┐
             │ LAYER M — MATERIAL CONTRACT (shell-independent, seed-bound)│
             │  GlassTier enum · decide_tier() pure · token triples in   │
             │  gui/style.py · Z-ladder roles · G1–G3 + underlay LAW ·   │
             │  glassPane registrar · Theme singleton crossing           │
             └───────────────┬───────────────────────┬───────────────────┘
                             │                       │
   ┌─────────────────────────▼─────────┐   ┌─────────▼──────────────────────────┐
   │ RENDERER A — ClassicShell (today, │   │ RENDERER B — GlassShell (U-track,  │
   │ eternal fallback)                 │   │ the reference look)                │
   │ cockpit window: TOKEN by          │   │ real QQuickWindow, D3D RHI, DWM    │
   │ construction (path-D law)         │   │ 38+20 behind transparent scene ·   │
   │ satellites (dialogs, theme editor,│   │ component kit (Ambient, GlassPane, │
   │ detached non-GL tabs, floating    │   │ SolidPane, ScreenPane, Readout,    │
   │ docks): WINDOW material via       │   │ ChromeBar, Popover, Scrim,         │
   │ gui/backdrop.py                   │   │ DangerSurface) · baked textured    │
   │                                   │   │ frost = deterministic glass ·      │
   │                                   │   │ QWidget safety + FastDAQ/GL panels │
   │                                   │   │ = native island windows           │
   └─────────────────────────┬─────────┘   └─────────┬──────────────────────────┘
                             │                       │
             ┌───────────────▼───────────────────────▼───────────────────┐
             │ LOW-LEVEL TIER (Vorschrift-4 licensed, Windows-only)      │
             │  DWMWA_REDIRECTIONBITMAP_ALPHA (≥26100, documented) ·     │
             │  DWMWA_USE_HOSTBACKDROPBRUSH(17)+CreateHostBackdropBrush  │
             │  via small C++/winrt helper — gated spike G5, NEVER       │
             │  load-bearing (underlay law)                              │
             └───────────────┬───────────────────────────────────────────┘
                             │
             ┌───────────────▼───────────────────────────────────────────┐
             │ LAYER S — EVENT SPINE + VERIFICATION                      │
             │  WinIdChange re-assert · WM_SETTINGCHANGE/THEMECHANGED ·  │
             │  WTS session · power broadcast · DPI/screenChanged ·      │
             │  sceneGraphError/device-loss → instant TOKEN · path-D     │
             │  census · scan-aware deferral · Tyr verdict rungs +       │
             │  onscreen harness at gate cadence                         │
             └───────────────────────────────────────────────────────────┘
```

### 2.1 Layer M — the material contract

The contract is what Vorschrift 2 means by modular and what the seed
inherits (Völundr):

- **Token triples.** Every material token is defined **once** in
  `gui/style.py` as `(base_color, alpha, preblend_result)` — the QSS
  builder consumes it one way (classic), `gui/qml_theme.py::Theme` the
  other (QML). Existing values slot in unchanged:
  `BACKDROP_CANVAS_ALPHA` (0.82), `PANEL_GLASS_ALPHA` (0.55),
  `_GLASS_BLEND_ALPHAS` (chrome/strip/edge pre-blends), plus Baldr's
  additions `glass.blur_px` (26, from the reference artifact),
  `glass.scrim_min` (per-role worst-case-contrast floor, §4.2), and the
  `elev.0..3` elevation table. A theme designer edits one number; both
  shells and the seed move. Enforced by a generated parity test
  (Tyr §4(a)) — never a hand-copied constant in QML.
- **The Z-ladder** (Baldr §1, adopted verbatim as the role vocabulary):

  | Z | Role | Glass? |
  |---|---|---|
  | Z0 | Canvas (window's unclaimed background) | yes — the primary glass surface |
  | Z1 | Chrome (rail, tab strips, status-strip frame) | yes, with `scrim_min` floor |
  | Z2 | Panel/Card (working surface) | opt-in only via `register_glass_pane`, never data-carrying panes |
  | Z3 | Instrument screen (plots, camera, scan map) | **never** — `gui/panel_kit.py::register_glass_pane` already refuses |
  | Z4 | Readout (hero values, wells, HV state) | never |
  | Z5 | Danger/alarm (DangerGate, STOP, Abort, ARMED, trip banners) | **never, in either direction** (§4.1) |

- **The `glassPane` registrar as contract** (Völundr §5, frozen): opt-in,
  per-instance, default-off, refusal-API
  (`gui/panel_kit.py::register_glass_pane` raises on ineligible panes),
  enumerable (`registered_glass_panes()`). The QML kit enforces the same
  deny-list and feeds the same registry concept; the resolver refuses
  glass-on-glass nesting (inner pane resolves to `SolidPane`).
- **The Theme-singleton boundary law** (Völundr §3, frozen): one value
  source (`gui/style.py`), read-only crossing
  (`gui/qml_theme.py::Theme`, getter-only properties), one validation
  choke point (`sanitize_overrides` upstream). T3 mechanism tokens
  (`Theme.backdropMode`, `Theme.panelGlassAlpha`, `Theme.glassTier`)
  cross the same boundary — a QML shell that hard-codes its own alpha has
  forked the system on day one.
- **The seed shape:** `PLATFORM_SEED.md` carries the `MATERIAL_TOKENS`
  table (name | tier | semantics | mutability class | QML property),
  generated from `style.py`, never hand-copied. Names and semantics are
  permanent (capability_id-grade promise); values and mechanisms are
  never promised; **no consumer may detect which tier is active** (G3).

### 2.2 Layer R — the renderers

#### 2.2.1 ClassicShell (today; the eternal fallback)

Amended Candidate B, stated without the overstatement Loki flagged:

- **The cockpit window is the TOKEN look by construction** for the entire
  option-(a) era. Not a degradation rung — its *design*. The v6
  pre-blends, the specular/edge grammar, the ambient-canvas gradient
  (Baldr §3.3, a QSS `qlineargradient` on Z0 only — cheap, static,
  painted on resize) carry the glass identity. This must be re-ratified
  in DECISIONS as the honest restatement (§8).
- **Real DWM material lives on RTT-free satellite top-levels**: the theme
  editor, `SettingsWindow`, dialogs, `_DetachedWindow` torn-off tabs
  (non-GL), and future floating dock containers — via the existing
  `gui/backdrop.py` chain + `gui/style.py::apply_window_backdrop_to`
  fan-out, which already passes `dark=`. "Glass satellites, opaque
  cockpit" (Ratatoskr §3.3) works today with zero new mechanism.
- **The path-D census makes the satellite rule enforceable** (§2.3): any
  top-level that gains a visible RTT child forfeits material *for that
  window*, logged, re-resolved per window — never averaged (Thor
  constraint 4). Redocking the 3D view is then an explained, logged
  transition instead of tonight's silent mystery.
- Future QtAds cockpit (when instantiated): the dock manager's bundled
  stylesheet is replaced at construction
  (`CDockManager.setStyleSheet(...)` with our ADS-namespaced rules, Thor
  §4.1); splitter gutters + tab strips become the Z1 chrome zones;
  floating containers get native title bars **forced** (frameless float =
  Thor path C = material impossible — a config assertion, not a hope;
  Fenrir K8-a).

#### 2.2.2 GlassShell (the Vorschrift-4 purchase — the reference look)

The one road to real glass on the cockpit itself (Thor §5.3), pulled
forward. Mechanism, precisely:

- **The shell top-level is a real `QQuickWindow`** (`ApplicationWindow`),
  `color: "transparent"`, alpha buffer via the app default surface format
  (`main.py::_enable_translucent_window_surface` already sets it) plus
  `QQuickWindow.setDefaultAlphaBuffer(True)` before creation, on the
  **D3D RHI** — the DirectComposition path where per-pixel alpha is
  first-class (Thor §5.1, Frigg [S26]/[S41]: demonstrated working with
  Mica on Qt 6.10.1). DWM attach (38 + 20) on its HWND through a new
  HWND-level entry point extracted from `gui/backdrop.py` (the current
  `apply_backdrop` takes a `QWidget`; the extraction is mechanical).
- **The OpenGL RHI pin does not apply to the GlassShell.**
  `gui/qml_shell.py::pin_opengl_rhi` exists so the chrome `QQuickWidget`
  and the `GLViewWidget` can share one window's context. In the
  GlassShell there is no `QQuickWidget` and no widget-tree GL child:
  **every GL/FastDAQ island and every QWidget safety island becomes its
  own native window**, hosted in the scene via Qt 6.7+ `WindowContainer`
  (the masterplan already web-verified: WindowContainer hosts *windows*,
  not widget trees — so QWidget panels get `WA_NativeWindow` and are
  hosted via their `windowHandle()`). Each island owns its own swapchain/
  context; the RHI choice decouples per window. This resolves Loki
  MAJOR-2 (B's unpriced D3D-vs-OpenGL-pin dependency) *by construction*
  — and the G0 spike proves it before the track bets on it (§7.3).
- **Islands are opaque, above the scene, by mechanism** (airspace): which
  is exactly the law for Z3/Z4/Z5 content. `DangerSurface` (the kit
  component hosting re-parented STOP/Abort/ArmLatch QWidgets) is
  therefore opaque-and-topmost *by construction*, not by review
  vigilance. Corollary rule: popovers/flyouts/scrims treat island rects
  as exclusion zones (they cannot render above them anyway; the resolver
  refuses placements that would try). The one modal exception stays: a
  full `Scrim` + DangerGate, with the gate itself a topmost island.
- **The component kit** (Baldr §4.2, adopted; input to the U1.5 kit-spec
  ratification): `Ambient`, `GlassPane`, `SolidPane`, `ScreenPane`,
  `ReadoutTile`, `StatusPill/Chip`, `ChromeBar/Rail`, `Popover/Flyout`,
  `Scrim`, `DangerSurface`. Materials never animate their own alpha;
  focus = specular rim brightening; heaviest material on the most
  transient surface (visionOS rule); vibrancy text refused; adaptive
  re-tinting of semantic colors refused; glass-on-glass refused.
- **Two frost sources, one `GlassPane`, resolved per window:**
  1. **`windowMaterialLive == true`** (Win11 desktop session, effects
     on): the real DWM material behind the transparent scene *is* the
     frost — the actual desktop, actually blurred by the OS, through
     every scene-alpha pixel. This is the reference look, genuinely.
  2. **`windowMaterialLive == false`** (RDP, transparency-off, battery
     saver, Linux, device-loss recovery): the pane samples the
     **baked, textured Ambient** — an app-owned canvas composition
     (gradient + glows **+ ratified visible texture/grain**, §10
     decision 3) pre-blurred once at theme-build time into textures,
     position-sampled at the pane's scene coordinates (parallax on
     drag). Plain `Image` sampling — no ShaderEffect, no MultiEffect,
     works on the software scenegraph backend, pixel-hashable in CI.
     Loki's optical critique is answered head-on: the blur earns its
     keep **only if** the ambient has high-frequency content — that is
     the Kaya taste ratification, on an A/B artifact, before the bake
     pipeline is built (beat G1). If Kaya picks the flat ambient, the
     kit ships position-sampled ambient *without* a blur pipeline
     (cheaper, same look) and says so honestly.
  The switch is one `effectiveMaterial` property flip driven by the
  event spine; geometry, tint, hairline, and specular are identical in
  both sources. **Headline property:** in the GlassShell, the OS killing
  transparency costs only the live-desktop showthrough — the glass
  identity survives, deterministically, on every rung down to TOKEN.
- **The two Fenrir laws are kit contracts, not lore** (K3/K10):
  **retention law** — the CPU-side source of every baked texture is
  never freed while any pane samples it (TDR/eviction recovery);
  **underlay law** — see §4.2 (constitution-grade).
- **The ambient is never the wallpaper.** Brokkr C's wallpaper mode is
  cut (Loki §4: one path for per-monitor wallpapers, fit/span/tile
  re-implementation, unreliable slideshow events; Fenrir K4: stale frost
  or mid-scan CPU spikes). The bundled/procedural source kills the entire
  K4 class and is the honest static skin. Anyone "improving" the ambient
  by sourcing the wallpaper inherits K4 — refuse.
- **What stays banned in the GlassShell:** live `MultiEffect`/
  `ShaderEffect` glass (ratified; enforced by the object-tree-walk gate,
  Tyr §4(c)); glass over Z3/Z4/Z5 (enforced by the registrar and the
  island opacity gate, Tyr §4(d)).

#### 2.2.3 The low-level tier (licensed by Vorschrift 4, bounded by honesty)

Two mechanisms, two very different price tags:

1. **`DWMWA_REDIRECTIONBITMAP_ALPHA` (documented, build ≥ 26100)** — the
   first *documented* per-pixel-alpha switch for plain windows,
   premultiplied (Ratatoskr §1.3). Adopt conditionally in
   `gui/backdrop.py` (build-gated beside `_MIN_SUPPORTED_BUILD`), keeping
   `DwmExtendFrameIntoClientArea(-1)` for 22621–26100. Cheap (S),
   low-risk, pure hardening of the satellite path. Part of beat G-B1.
2. **`DWMWA_USE_HOSTBACKDROPBRUSH` (17) + Windows.UI.Composition
   `CreateHostBackdropBrush`** — the only true per-region behind-window
   material (Ratatoskr §1.8, sample-proven on plain Win32:
   Win32Acrylic/Win32Acrylic2). Real cost: a small C++/winrt (or
   python-winrt) helper — `ICompositorDesktopInterop`,
   `CreateDesktopWindowTarget(hwnd, isTopmost=FALSE)`, a
   `DispatcherQueue` pumped on the GUI thread beside the Qt loop, and
   app-side region bookkeeping. **Honest scoping:** it still requires
   real alpha holes in the window's own content above each visual — it
   therefore *cannot* rescue the classic path-D cockpit either. Its
   legitimate roles: (a) the **contingency road** to the reference look
   if the G0 spike fails (composition visuals + `isTopmost=TRUE` chrome
   drawn in the visual layer — the full "eigenes UI-System" endpoint,
   priced only if needed); (b) an **enhancement** (`COMPOSED` tier) for
   true per-region desktop sampling on satellite windows or scene
   regions where window-level material is not enough. Beat G5, gated,
   never load-bearing: by the underlay law, a dead visual degrades to
   the pane's underlay, never to a hole.
3. **Permanently banned, ratify as such** (§8):
   `SetWindowCompositionAttribute`/`ACCENT_POLICY` (drag-lag 1903+,
   broken 22631 — Ratatoskr verdict 3), `DWMWA_MICA_EFFECT` 1029
   (deleted by Microsoft), `DwmEnableBlurBehindWindow` blur (dead since
   Win8). This also closes the Win10 question forever: **Win10 = TOKEN,
   full stop.**

### 2.3 Layer S — the event spine and the census

One `QAbstractNativeEventFilter` + Qt-event hooks, in one module
(`gui/glass_env.py`, companion to `gui/backdrop.py` under the same
"only place that touches ctypes/DWM" quarantine rule). Loki cut Ymir's
watcher subsystem *for the classic shell* (defended harm: a few RGB
units on satellite margins) — **the GlassShell changes the blast
radius**: on a translucent `QQuickWindow` the material is behind the
whole cockpit, so session/power transitions become whole-window events.
Resolution (explicit, per Kaya's depth directive): the event spine is
**tiered with the shell** —

| Trigger | Mechanism | ClassicShell action | GlassShell action |
|---|---|---|---|
| HWND recreated | `QEvent.WinIdChange` on every top-level | full re-assert in order: ExtendFrame → attr 20 → attr 38 → canvas prep → opacity pin → log | same, on the shell HWND + island windows |
| Theme toggle | in-app | landed (`2cf720b`) + **post-toggle re-assert one event-loop turn later** (beats Qt's palette heuristic, Fenrir rider 2) | Theme NOTIFY rebinds scene; one attr-20 re-assert |
| OS theme/transparency/HC toggled | `WM_SETTINGCHANGE`/`WM_THEMECHANGED` | re-assert + re-resolve tier (HC → FLAT is the one non-cosmetic stake) | same + frost-source flip |
| RDP connect/disconnect | `WTSRegisterSessionNotification` → `WM_WTSSESSION_CHANGE` | *not wired* (satellite margins only — Loki cut stands) | **wired**: downgrade instant (§3.2) |
| Battery saver / power | `WM_POWERBROADCAST` | not wired (same rationale) | wired: `windowMaterialLive=false`, frost source flips — look survives |
| Monitor/DPI change | `screenChanged` + `WM_DPICHANGED` | re-assert + resize-jiggle heal (W4) on satellites | same on shell + per-screen texture DPR re-key |
| GPU device loss / TDR | `QQuickWindow::sceneGraphError` + RHI device-lost | n/a | **instant drop to TOKEN** (one swap), re-init, restore only after verified re-pass (Ymir I4) |
| Sleep/resume | `PBT_APMRESUMEAUTOMATIC` | resume = cold re-derive on satellites | resume = cold re-derive, first-expose probe re-run |
| Dock/detach layout change | ADS/tab signals | **path-D census**: enumerate visible RTT children per top-level; any window containing one forfeits material *for that window*, logged (Fenrir rider 5) | islands are native windows — census trivially per-island |

The **runtime pixel probe is settled between Ymir and Loki as follows**:
Ymir's L6 attribute-*toggling* inertness probe is **cut** (flicker vector,
false verdicts under Acrylic — Loki §5.1). What remains is a **read-only
luminance guard**: one 8×8 physical-px BitBlt of a declared margin patch,
compared against the active palette, run only at first-expose (+2 frames),
after event-spine re-asserts, never mid-scan, never while
`WTS_SESSION_LOCK` is active. Dark theme + bright probe ⇒ re-assert attr
20 once, re-probe, still bright ⇒ tier drop + log. That preserves the
white-guard (W1 detection) with zero attribute churn. Everything deeper
is the onscreen harness at gate cadence (§7).

**Scan-aware deferral (Fenrir rider 7, resolving Baldr-vs-Ymir):**
*Downgrades are never queued* — a material→fallback downgrade applies
instantly as ONE opaque-token swap (Fenrir rider 3). *Upgrades* and all
expensive work (re-bakes, probes, restyles) wait for acquisition-idle +
60 s hysteresis + verified re-pass. Baldr's "dead glass unreachable" is
restated as its falsifiable form: **re-resolve within one event-loop turn
of the triggering message (≤ 200 ms), with the mid-scan exception applying
to upgrades only.** The scan-idle signal is consumed from the existing
GUI-side run-state (status_bus) — zero new coupling into `controller/`.

---

## 3. The ONE tier enum

### 3.1 Definition (lands in `gui/glass_env.py`, exported to QML as `Theme.glassTier`, frozen into the seed)

```python
class GlassTier(IntEnum):
    """The ONLY material-tier vocabulary. Monotonic: a lower value is
    always a strict capability subset of a higher one. Downgrades move
    down; nothing ever climbs on loss of capability."""
    FLAT     = 0  # accessibility / operator escape hatch: plain p['bg']/p['panel'] solids
    TOKEN    = 1  # pre-blended opaque tokens (the v6 look) — the guaranteed floor, every host, byte-identical offscreen
    WINDOW   = 2  # + real DWM material (38+20+ExtendFrame) on RTT-free top-level windows
    SCENE    = 3  # GlassShell: translucent QQuickWindow, scene alpha to DWM, in-scene kit; frost source resolved per §2.2.2
    COMPOSED = 4  # + Windows composition interop (host-backdrop visuals / redirection-bitmap alpha) — gated enhancement
```

**Resolution:** `tier(window) = min(policy, shell_ceiling, window_census,
override)` where `decide_tier(env) -> GlassTier` is a **pure function** of
a frozen `GlassEnvironment` dataclass (platform, build, qt_platform,
remote_session, transparency_enabled, battery_saver, high_contrast,
scenegraph_api, override) — every probe injectable exactly like
`backdrop._version_probe`/`_platform_probe`, so the whole environment
matrix is a parametrized offscreen test (Tyr §3.1's demand, honored).
Shell ceilings: ClassicShell = `WINDOW`; GlassShell = `COMPOSED`.
Window census: a top-level with a visible RTT child caps at `TOKEN`
(path-D law); the classic cockpit window is therefore `TOKEN` by
construction whenever the 3D view or QML chrome lives in it. High
contrast ⇒ `FLAT`, mandatory, outranks everything. Tier is resolved
**per top-level window, never averaged**.

**Operator override:** QSettings `theme/glass_tier ∈
auto|flat|token|window|scene` — a *ceiling*, never a floor (forcing up is
impossible; detection lies are answered by forcing down). Loudly logged.

**Truth log (Ymir I5, kept):** one greppable INFO line at startup and
every re-decision:
`glass: tier=token window=main (build=26200 remote=0 transparency=1 hc=0 saver=0 census=rtt:GLViewWidget override=auto)`.

### 3.2 Transition policy

Down: same event, immediately, as one token swap. Up: trigger + verified
re-pass + ≥ 60 s hysteresis + acquisition idle. No undefined states; a
fresh session re-derives from disk-truth inputs (session-hygiene rule 1
applied to pixels).

### 3.3 Deprecation map (the other three vocabularies get these lines; Loki contradiction 3 closed)

| Deprecated | Where it appeared | Reads as |
|---|---|---|
| Ymir `T2` / `T1` / `T0` | ymir.md | `FLAT` / `TOKEN` / `WINDOW` (classic) · `SCENE` (GlassShell); the `T0-DWM`/`T0-QML` split is the per-window `windowMaterialLive` boolean *inside* `SCENE`, not an enum value |
| Baldr `R0`–`R3` | baldr.md | `FLAT` / `TOKEN` / `WINDOW` / `SCENE`·`COMPOSED` |
| Brokkr-B `PREBLEND` / `REAL_BACKDROP` | brokkr.md | `TOKEN` / `WINDOW`·`SCENE` |
| Tyr "rungs 0–5" | tyr.md | **kept, renamed "verdict rungs"** — an orthogonal *test-evidence* axis (§7.1). A claim about glass names both: the tier that paints and the rung that proved it. |

---

## 4. The safety constitution of the material system (Vorschrift 3 — absolute)

### 4.1 The frozen invariants (LAW; §8 files G1–G3 + the underlay law in the PROTECTED region)

- **G1 — deterministic backing.** Every hazard-signaling element
  (`danger`/`armed`/`sim`/`error` chips, lamps, `#dangerBtn`,
  `[state="danger"|"armed"]`, the DangerGate modal, trip banners) renders
  on an opaque token surface — never composited over desktop or blurred
  app content. Soft `_rgba` tints stay legal *because* they sit on such
  backings.
- **G2 — glass ineligibility of danger surfaces.**
  `gui/panel_kit.py::register_glass_pane` already refuses plot
  containers; the deny-list extends to any pane hosting a hazard surface
  (STOP / ALL-OUTPUTS-OFF / Abort hosts, armed banners, safety chips, the
  kill switch). Refusal is API behavior, not a styling guideline. In the
  GlassShell, `DangerSurface` islands are opaque-and-topmost by
  mechanism (§2.2.2).
- **G3 — material carries zero hazard information.** Toggling backdrop
  kind, `glassPane`, or landing on any tier changes **zero pixels of any
  hazard element** — pixel-gated (hazard-crop byte-equality across all
  modes and tiers, Völundr §6). Corollary, resolving Loki contradiction
  2: **Baldr's alarm-de-glass rule (§5.3) is killed.** A state cue that
  exists only on `WINDOW`+-tier machines is dishonest state; alarms have
  their own channel (the locked `SAFETY_TOKENS` at
  `gui/style.py::SAFETY_TOKENS` — six names, indivisible, incl. the
  `crit`/`warn` byte-aliases).
- **THE UNDERLAY LAW (Fenrir rider 4, promoted to LAW):** every glass
  surface in every renderer paints its `TOKEN` pre-blend **first**;
  frost, material, and composition effects sit strictly above it.
  Eviction, device loss, stale cache, missing texture, dead composition
  visual — all degrade to the ratified fallback **by construction**,
  never to transparency, never to white. One rule retires the worst
  outcome of Fenrir K2, K3, K7, and K10 simultaneously.
- **Unchanged and sovereign:** the opacity pin
  (`gui/style.py::apply_window_opacity`, `MIN_WINDOW_OPACITY = 0.80`,
  backdrop-before-opacity ordering, `tests/test_backdrop.py` pin);
  `SAFETY_TOKENS` lock (`apply_theme_overrides` raises,
  `sanitize_overrides` drops); sim marking survives material (G5-class,
  structurally satisfied by G1/G2).
- Baldr's G4 numeric contrast floors and the exact deny-list wording are
  **design-spec, not constitution** (Loki contradiction 5: the PROTECTED
  region grows by invariants, not by tables) — they live in this
  document and the U1.5 kit spec, gate-checked per preset.

### 4.2 The readability contract

Text/icons on any glass-class surface (Z0/Z1, opted-in Z2): contrast
≥ 4.5:1 against **both** worst-case extremes (material over pure white
AND pure black); whichever fails sets `glass.scrim_min` for that role —
a token, not taste. `TOKEN`/`FLAT` pass by construction (opaque blends —
pure math, tested offscreen). Only `WINDOW`/`SCENE` need the onscreen
harness, and only in Z0/Z1 regions.

### 4.3 FastDAQ protection (Vorschrift 3, second clause)

"FastDAQ islands" = the fast acquisition/display path: the 9
pyqtgraph/GL islands, the camera raster QLabel, the ~15–30 Hz plot
updates (the masterplan's "NEVER migrates" list). Laws:

1. **Islands render untouched.** `ScreenPane` hosts them opaque; no
   material, no blur, no alpha, no `layer.enabled`, in any tier, in
   either shell (gate: Tyr §4(d) island-opacity walk).
2. **The material machinery never contends with acquisition** (Fenrir
   H6, the invisible kill): no bakes, probes, restyles, or attribute
   churn while the acquisition state machine is active — downgrades
   excepted as one swap (§2.3). Bake workers run below-normal priority,
   at scan-idle only. Baked assets are sized to the window, not the
   desktop.
3. **No per-frame material cost on the hot path.** Frost is
   position-sampled static texture; ambient is static; motion animates
   geometry, never material alpha.

### 4.4 The driver structure stays (Vorschrift 3.1)

Layering law, parallel to `docs/CAPABILITY_MODEL.md` §2 and
AST-checkable the same way (`tests/test_layer_contracts.py` pattern):

- `gui/glass_env.py`, `gui/backdrop.py`, the kit, and everything in this
  document **MUST NOT** import `devices/`, `controller/`, or
  `capabilities/`. The one touch point is the read-only run-state signal
  already exposed to the GUI (status_bus).
- Nothing in the glass system appears in any driver, adapter, registry,
  or capability path. Adding a new instrument driver
  (`devices/*_base.py` + real + simulated backend, config in
  `configs/devices.yaml`) involves **zero** glass-system files. The
  capability spine (D1a/D1b) proceeds untouched and unaware.

---

## 5. Cross-lane contradictions — resolved (none papered over)

| # | Contradiction | Resolution | Rationale |
|---|---|---|---|
| 1 | Baldr "dead glass must be unreachable" vs Ymir scan-freeze (dead glass persists a full run by design) | **Latency bound** (≤ 200 ms / one event-loop turn) for downgrades, which are never queued; upgrades wait for scan-idle (Fenrir rider 3) | "Unreachable" is unfalsifiable; downgrade-instant + underlay law makes every dead state a shrug, not a hazard |
| 2 | Baldr alarm-de-glass (§5.3) vs Völundr G3 (material carries no hazard info) | **G3 wins; alarm rule killed** | Cue exists only on high-tier machines → operator misreads a frostless RDP session as a standing alarm; constitution-grade invariant beats a taste feature |
| 3 | Four tier vocabularies | **One `GlassTier` + deprecation map** (§3.3); Tyr's rungs kept as the orthogonal evidence axis | Seed must inherit exactly one enum or LabControl forks by picking the wrong doc |
| 4 | Ymir L2/L4/L6 watcher subsystem vs Loki's cut | **Tiered with the shell** (§2.3): classic keeps only the cheap rungs (HC, override, WinIdChange, settings-change, truth log); GlassShell wires session/power/device-loss because the material becomes whole-window load-bearing there | Loki's blast-radius argument was correct *for satellites*; the GlassShell changes the blast radius, so the spine scales with it |
| 5 | Ymir L6 attribute-toggle pixel probe vs Loki flicker/false-verdict objection vs Fenrir K2's "re-run probe" MUST | **Read-only luminance guard** at first-expose/re-assert events only; the toggle-based inertness check moves to the onscreen harness at gates | Keeps W1 white-detection with zero attribute churn in a lab GUI |
| 6 | Baldr baked-blur centerpiece vs Loki "optically a near-identity" | **Taste gate first (G1 beat):** textured ambient (blur earns its keep) vs flat ambient (ship position-sampling only, no blur pipeline). Kaya decides on an A/B artifact before the pipeline is built | The blur is only worth building if there is high-frequency content to blur; that is a design decision, not a default |
| 7 | Brokkr C wallpaper acquisition vs Loki §4 autopsy + Fenrir K4 | **Wallpaper mode cut entirely**; ambient is bundled/procedural, app-owned | Per-monitor/fit-mode re-implementation + unreliable slideshow events + mid-scan re-blur CPU = three kills for one garnish |
| 8 | Tyr opaque-ancestor census (§1.2b) vs Loki "reimplements the QSS cascade" | **Fixed-list attribute/palette/autoFill assertions** on the named canvas-path widgets + QSS-*text* guards extended to future ADS selectors | An allowlist you can honestly enumerate beats a cascade you cannot honestly resolve |
| 9 | Brokkr A (One Sheet of Glass) vs the evidence | **Killed, recorded** (Loki §2.1, Fenrir 9-of-10 kill score). Surviving organs: the ADS-stylesheet eviction as *forward design* for the dock cockpit (§2.2.1), the pattern-behind A/B harness idea (→ §7.2), the attr-20 rider (landed) | Its go/no-go was already answered in-repo; its prize was ~0 px; its forensic suspect was not in the tree |
| 10 | DECISIONS "window-level DWM backdrop" clause vs QQuickWidget-chrome architecture (Loki CRITICAL-1) | **Re-ratification** (§8): cockpit = TOKEN by construction in the option-(a) era; the U-track endpoint becomes the GlassShell | The two clauses cannot both be true of the same HWND (path D); and as written the roadmap never reaches cockpit glass at all |
| 11 | BENCH_CHECKLIST §11 flip probe has no material row (the pre-scheduled next white-night) | **Material rows added** (§7.2): with acrylic active post-flip, dialog margins still frost; main-window frost expected NO (stated); GlassShell rows added when G3 lands | One row cancels a scheduled incident |

---

## 6. The staged build plan (beats, sizes, owners, U-track mapping)

Sizes use the masterplan scale (S/M/L/XL). Safety/concurrency-class beats
get immediate Mary review (ratified cadence). The ClassicShell remains
shippable after every single beat — that is the Vorschrift-3 robustness
guarantee: **at no point does the reference-look program hold the working
cockpit hostage.**

### Track G — trunk beats (now, before/beside the U-track)

| Beat | Size | Owner | Content | Gate |
|---|---|---|---|---|
| **G-B1 — event spine, classic subset** | S/M | Noah (**opus** — Qt lifecycle class) | `QEvent.WinIdChange` full re-assert on every top-level (order: ExtendFrame → 20 → 38 → canvas → opacity pin → log); `WM_SETTINGCHANGE`/`WM_THEMECHANGED` hook; post-theme-toggle re-assert one event-loop turn later; HC → FLAT; operator override key; truth log; `DWMWA_REDIRECTIONBITMAP_ALPHA` conditional adoption (≥ 26100); headless WinIdChange-recreation test (WA_NativeWindow toggle, recorded call sequence repeats) | material_contract bucket green; Mary immediate |
| **G-B2 — the contract** | M · judgment beat (**Fable**) | Noah + style owner | `gui/glass_env.py`: `GlassTier`, `GlassEnvironment` frozen dataclass, injectable probes, pure `decide_tier`; token triples in `gui/style.py`; transition policy (downgrade-instant law); deprecation map lines into the four lane docs; matrix property test (totality/monotonicity/fail-safe/determinism, ~2000 cases) + golden table for the ~10 named scenarios | material_contract green; Mary immediate (concurrency-adjacent: native event filter) |
| **G-B3 — harness upgrade** | M | Noah + Tyr's spec | `scripts/capture_onscreen.py`: INV-A/B/D invariants, lifecycle frames (first-show, resize burst, minimize-restore, detach→redock round-trip, theme-toggle burst), region masks emitted from live geometry into the manifest, `verdict.json` (per-invariant PASS/FAIL + env fingerprint incl. `EnableTransparency`, accent, wallpaper hash); path-D census helper + the 30-second detach discriminator as a scripted scenario; **§11 material rows** into `docs/BENCH_CHECKLIST.md` | verdict.json format ratified; ledger artifact class |

### Track G — GlassShell beats (branch `ui-qml-migration`, mapped onto the U-track)

| Beat | Size | Rides | Content | Gate |
|---|---|---|---|---|
| **G0 — GlassShell spike** | M · [Bench] | **U0** (extends the existing RHI probe) | Translucent `QQuickWindow` + D3D RHI + DWM 38/20 (HWND-level `apply_backdrop` extraction) + one `WindowContainer`-hosted QWidget island (mock STOP) + one `GLViewWidget` island window + RDP session + transparency-off + resize/minimize/DPI burst + idle-CPU/heartbeat budget. **Pass criteria in §7.3.** This is Loki's demand ("the transparent-QQuickWindow spike moves into U0, before the shell bet") funded | go/no-go for the whole GlassShell program; verdict.json in ledger |
| **G1 — ambient taste gate** | S · [Kaya] | pre-**U1.5** | A/B artifact: textured ambient (grain/glow texture → blur does real optical work) vs flat ambient (position-sampling only, no blur pipeline). Kaya's nod decides whether the bake pipeline exists at all (§5 row 6) | [Kaya] |
| **G2 — component kit** | L · judgment (**Fable** spec, Noah impl) | **U1.5 → U2** | The kit of §2.2.2 implemented per the ratified U1.5 spec: underlay law in every component, retention law, nesting refusal, exclusion zones, `Theme.glassTier` context property, generated token-parity test, object-tree-walk gates (no ShaderEffect/MultiEffect; island opacity law) | U1.5 [Kaya] kit-spec gate + per-stage qml-boot material clause |
| **G3 — GlassShell hero** | L | **U2** (with the ScanViewer hero) | The shell window itself: chrome + docking-lite + ScanViewer hero slice inside the GlassShell; full event spine (WTS/power/DPI/sceneGraphError → instant TOKEN); per-window tier resolution; first-expose luminance guard | U2 [Kaya] pattern sign-off + rung-4 harness verdict |
| **G4 — frost bake** | M | U2/U3 window | Baked textured frost (iff G1 chose textured): theme-build-time bake in a below-normal-priority worker, per-(screen, DPR) keyed textures sized to the window, atomic swap, scan-aware deferral, CPU-source retention | material_contract + harness INV-A on frost tier |
| **G5 — composition interop** | M/L · **contingent** | after G3 (or immediately if G0 **fails**) | The winrt helper (host-backdrop brush per §2.2.3): as COMPOSED enhancement, or as the contingency road to the reference look. Scope questions the spike must answer are pre-registered in §7.3 | Mary immediate (new native surface + thread pump) |
| **U3–U5** | (existing plan) | U3–U5 | Panels migrate onto the kit; per-panel glass eligibility declared via the registrar; hazard-crop byte-equality per panel; U4 Bias / U5 Motor keep the re-parented-never-reimplemented island rule | existing standing gates + material clause |
| **U6 — redefined** | M | U6 | **GlassShell becomes the default shell** (was: QQuickWidget-chrome flip). ClassicShell frozen as the eternal fallback (one env var). Full-matrix onscreen capture across exercised rungs; dark-flag consistency assertion | [Bench][Mary][Kaya] |

Docs riders (same beats, Kiroku/Samantha): `docs/ARCHITECTURE.md` index +
changelog; `docs/DECISIONS.md` entries per §8; seed section per Völundr §7
when the seed tag approaches.

**Cost honesty:** trunk 3 beats (S/M+M+M); GlassShell 5–6 beats
(M+S+L+L+M, G5 contingent) riding U-stages that exist anyway; panel-wave
cost is absorbed by U3–U5. Total glass-specific ≈ 9–10 beats — more than
Loki's 5-item minimum program (which lives on inside G-B1…B3 + G0 and is
independently shippable), less than the council's naive 12–18 sum, and it
buys the actual reference look instead of deferring it. Scheduling note:
the masterplan's WIP limit (max 2 gate-bearing tracks) means pulling U0
forward is a Kaya scheduling call — named in decision 2, not smuggled.

---

## 7. Test gates

### 7.1 Verdict rungs (Tyr, revised — "a green rung N never claims rung N+1 truth")

| Rung | Proves | Runs | Content (delta to what exists) |
|---|---|---|---|
| 0 | intent | headless, per-beat | `decide_tier` matrix (totality/monotonicity/fail-safe/determinism) + golden scenario table; token schema guard (domain + no drifted literals) |
| 1 | Qt-side state agrees with itself | headless, per-beat | existing 55+ `tests/test_backdrop.py` spine; legal-triples test (translucent-attr/palette/fill never mixed — the July-13 bug class, generalized); **fixed-list** canvas-path attribute assertions (replaces the QSS-cascade census, §5 row 8); `_CANVAS_MODE` candidate-B state symmetry; WinIdChange recreation test |
| 2 | native calls would be right | headless, per-beat | recorded-DWM-call seams (exists); attr-20-with-38 batch + order test (landed with `2cf720b`, kept green forever); HWND-level entry point seams for the GlassShell |
| 3 | alpha is multiplied | headless where cheap | offscreen margin-delta smoke (promote `glass_gap_findings.md` §4's one-green-unit measurement to a test); GlassShell: `QQuickWindow::grabWindow` scene-alpha assertions; kit object-tree walks (shader ban, island opacity, `materialTier` reported); frost textures pixel-hashed in CI (deterministic — the app-owned source's whole point) |
| 4 | the compositor rendered it | real desktop, **gate cadence** | harness INV-A (none vs material differ in canvas regions ≥ 1 %, content regions near-equal — the anti-pixel-equal guard), INV-B (mica ≠ acrylic), INV-D (dark theme + material ⇒ margin luminance < threshold — the white tripwire), lifecycle frames, hazard-crop byte-equality (G3 as pixels), verdict.json to ledger. INV-C (3-frame flash guard) demoted to eyeball-notes (Loki: it will flake) |
| 5 | taste | Kaya | blur quality, artifacts, the G1 A/B, `_CANVAS_MODE` A/B — phase gates, `BENCH_CHECKLIST.md` §8 |

**Cadence honesty (Loki's Tyr revision, adopted):** rung 4 + 5 run at
wave boundaries, U-stage merge-backs, and phase gates; per-beat only for
diffs touching `gui/backdrop.py`/`gui/glass_env.py`/DWM code. Rungs 0–3
are the `material_contract` pytest bucket (< 20 s, offscreen), a per-beat
gate for any diff touching backdrop/glass_env/style-canvas/panel_kit/
`main.py` surface-format code. No golden images of real materials, ever
— invariants within one run only; golden images only for TOKEN/FLAT
(compositor-independent).

### 7.2 The §11 flip-probe material rows (added by G-B3; cancels the pre-scheduled white-night)

To `docs/BENCH_CHECKLIST.md` §11: **R6** — with acrylic active and the
chrome island live, theme-editor/dialog margins still frost (expected:
YES); main-window margins frost (expected: **NO — by design**, path-D law,
stated so nobody debugs it in three weeks); **R7** — detach Motor tab →
main-window margins begin frosting; redock + click "3D" → frost dies +
census log line appears (expected: exactly that, with the log line as the
proof the census works). GlassShell rows (R8+) land with G3.

### 7.3 G0 pass criteria (the go/no-go, pre-registered so the spike cannot be argued green)

- **P1** Translucent `QQuickWindow` + D3D RHI + attr 38/20: INV-A/INV-D
  pass on the shell window (material demonstrably composites behind the
  scene, dark).
- **P2** QWidget island (mock STOP) + `GLViewWidget` island: render,
  receive input, stay opaque; no RHI/context errors; float/re-embed
  round-trip survives (K8 analog of §11 R2).
- **P3** Resize burst + minimize-restore + DPI/monitor move: no sticky
  white frame (W4/S26 class) that survives one automated heal.
- **P4** RDP mid-session connect: instant downgrade fires (≤ 200 ms
  swap), scene stays readable (frost source flips or TOKEN), no white
  lattice; console reconnect restores only after verified re-pass.
- **P5** Idle CPU < 5 % and GUI-heartbeat gap < 100 ms with a simulated
  15 Hz scope island live (§11 F3 bounds, applied to the new shell —
  the FastDAQ contention gate).
- **P6** Device-loss hook demonstrably drops to TOKEN (fault-injected via
  the sceneGraphError path if a real TDR cannot be provoked safely).

**If G0 fails** (P1/P2 irreparable on the bench GPU): the GlassShell bet
is off; G5 (composition interop) is spiked next as the licensed
alternative road; the ClassicShell + satellites + kit-on-classic remains
the shipped look meanwhile. Pre-registered G5-spike questions: can a
DesktopWindowTarget visual tree carry the chrome above/below Qt content
at acceptable complexity; DispatcherQueue-beside-Qt-loop stability;
input hit-testing through visuals; RDP behavior of host-backdrop
visuals.

---

## 8. What gets re-ratified in DECISIONS (the collision, named at full volume)

One new DECISIONS entry, drafted for Kaya's per-change approval
(PROTECTED-region governance honored — no agent rewords ratified text
autonomously; this section is the *proposal*):

1. **Amend the 2026-07-13 "QML-hybrid boundary" entry:** the clause "the
   glass LOOK ships via pre-blended tokens + window-level DWM backdrop"
   is restated as: *the classic cockpit window ships the pre-blended
   TOKEN look by construction (path-D law); window-level DWM material
   applies to RTT-free satellite top-levels only; the QQuickWidget
   chrome island and main-window DWM material are mutually exclusive by
   mechanism.* The safety sub-clauses (no safety control ever in QML,
   no live shader glass, single implementation) survive verbatim.
2. **Re-specify the U-track endpoint:** U6 becomes *GlassShell default*
   (real `QQuickWindow` shell per this document) — superseding
   "QML-chrome-island default flip" as the end state; option (a) remains
   the interim classic-shell architecture only. G0 (rides U0) is the
   funded go/no-go. This supersedes the corresponding masterplan lines
   the way the masterplan itself superseded the boundary entry
   (plan-approval = re-ratification, per its own governance note).
3. **File as LAW in the PROTECTED region:** the underlay law (§4.1) and
   invariants G1–G3. (G4 contrast numbers + G5 phrasing stay design-spec
   — constitution grows by invariants, not tables.)
4. **Ratify permanently:** `SetWindowCompositionAttribute`/ACCENT ban;
   `DWMWA_MICA_EFFECT` 1029 ban; no wallpaper capture as a frost source;
   Win10 = TOKEN forever; Baldr's alarm-de-glass rule rejected.
5. **Adopt the ONE `GlassTier` vocabulary** (§3) with the deprecation
   map; the seed inherits this enum and nothing else.
6. **BENCH_CHECKLIST §11 gains the material rows** (§7.2) as part of the
   flip-probe definition — the flip can no longer go green while glass
   dies silently.

---

## 9. What we still cannot have (the honest list — unchanged by budget)

1. **Real DWM material on the classic QWidget cockpit window** while any
   GL/Quick child lives in it. Path-D physics; not "yet" — *ever*, on
   that shell. The GlassShell exists because of this sentence.
2. **Real OS material over RDP, transparency-off, battery saver, Win10,
   Win11 21H2, Linux.** OS policy and API absence; no code changes it.
   What we *can* have there (GlassShell): the deterministic baked frost —
   the glass identity without the live desktop behind it. On the software
   scenegraph (RDP worst case): TOKEN.
3. **Live blur of app content behind panes.** The ratified shader ban
   stands in both shells (object-tree-walk-enforced). Frost is baked and
   position-sampled, not live. Re-ratifiable later for a proven-GPU tier
   only, by Kaya, never by drift.
4. **Live desktop content updating through in-scene frost.** The baked
   ambient is app-owned; a window dragged behind the cockpit does not
   show through it. Only the true window-level material (tier ≥ WINDOW
   with `windowMaterialLive`) shows the real desktop — where the OS
   permits it.
5. **Glass on or behind plots, camera, readouts, danger surfaces** — by
   law (G1/G2/Z-ladder), not by limitation. This is also why we can claim
   the visionOS reference honestly: visionOS itself keeps precision
   content opaque inside glass windows.
6. **QML popovers/scrims rendering above native islands** (airspace).
   Answered by exclusion-zone placement rules + the DangerGate island
   being topmost by construction — the one surface that *should* win.
7. **Per-region DWM material via dwmapi.** Does not exist (attr 38 is
   whole-window; the legacy region API lost blur in Win8). True
   per-region needs the composition interop tier (G5) and even that
   requires alpha holes above each visual.
8. **A wallpaper-derived frost.** Cut (multi-monitor, fit-modes,
   slideshow staleness, mid-scan CPU). The bundled/procedural ambient is
   the honest static skin.
9. **Golden-image regression tests of real materials.** Compositor-,
   wallpaper-, and build-dependent by nature; we test invariants within
   one run instead (INV-A/B/D), and golden-image only TOKEN/FLAT.
10. **"Glass works" as an unqualified claim.** Every claim names its
    tier and its verdict rung; a capture run without `verdict.json` is an
    eyeball session, not a gate.

---

## 10. The three decisions Kaya must nod

1. **The collision re-ratification (§8, items 1–2):** classic cockpit
   window = TOKEN by construction, real material on satellites only; and
   the U-track endpoint becomes the **GlassShell** (real `QQuickWindow`
   cockpit) instead of the QQuickWidget-chrome flip — with the §11
   material rows so the probe can never again go green while glass dies.
   *This is the "Vorschrift 1 + honesty" nod: it names where the
   reference look genuinely lives and stops promising it where physics
   forbid it.*
2. **Fund the GlassShell program as specified (§6):** G-B1…B3 on trunk
   now; G0 spike rides U0 as the pre-registered go/no-go (§7.3); on
   green, G1–G4 ride U1.5–U2 so the reference look arrives with the hero
   panel; on red, G5 (composition interop) is the licensed contingency
   road. ClassicShell stays shippable after every beat. Includes the
   scheduling call that U0's pull-forward makes against the max-2-tracks
   WIP limit. *This is the "koste es was es wolle" nod, made concrete:
   ≈ 9–10 glass beats + one contingency, instead of an open-ended vow.*
3. **Constitution + taste:** (a) file the underlay law + G1–G3 as LAW in
   the PROTECTED region (G4/G5 stay design-spec); kill the alarm-de-glass
   rule; ratify the permanent API bans (§8 items 3–4). (b) The one pure
   taste call only Kaya can make: **textured ambient** (frost with real
   optical work) vs **flat ambient** (position-sampling only, no blur
   pipeline) — decided on the G1 A/B artifact at the bench, before any
   bake pipeline is built.

---

## Appendix A — Fenrir rider compliance map (all 8 mandatory; where each lands)

| Rider | Lands in |
|---|---|
| 1. WinIdChange full re-assert + headless recreation test | G-B1 |
| 2. Attr 20 batched with 38, ordered, registry fan-out, post-toggle re-assert | landed (`2cf720b`) + G-B1 completes (WM_SETTINGCHANGE + event-loop-turn re-assert) |
| 3. Downgrades never queued (one opaque swap; upgrades wait) | G-B2 policy (§2.3, §3.2) |
| 4. Underlay law, contract-grade | §4.1 LAW; kit enforcement in G2; classic canvas already opaque-by-construction at TOKEN |
| 5. Path-D census per layout change, per window, logged | G-B3 helper + §2.3 spine row |
| 6. Event spine (WTS/power/settings/DPI; resume = cold re-derive) | G-B1 (classic subset) + G3 (GlassShell full) |
| 7. Scan-aware deferral for expensive regeneration | G-B2 policy + G4 bake worker |
| 8. Harness scenarios (resize burst, detach/redock, theme burst, first-show/minimize-restore) | G-B3 |

## Appendix B — API ground truth, condensed decision table (Ratatoskr, verdicts final)

| API | Verdict | Role here |
|---|---|---|
| `DWMWA_SYSTEMBACKDROP_TYPE` (38) + `DwmExtendFrameIntoClientArea(-1)` | SHIP (shipping) | the window material, `gui/backdrop.py`; floor build 22621 (`_MIN_SUPPORTED_BUILD`) |
| `DWMWA_USE_IMMERSIVE_DARK_MODE` (20) | SHIP (landed, `2cf720b`) | mandatory companion; the WHITE fix; re-assert via G-B1 spine |
| `WS_EX_LAYERED` / `setWindowOpacity<1` | keep as separate dimming knob | opacity pin stays sovereign (`apply_window_opacity`, ordering test) |
| `DWMWA_REDIRECTIONBITMAP_ALPHA` (≥ 26100, documented) | ADOPT conditionally | G-B1; ExtendFrame kept for 22621–26100 |
| `DWMWA_USE_HOSTBACKDROPBRUSH` (17) + `CreateHostBackdropBrush` | licensed low-level tier | G5 spike: COMPOSED enhancement / contingency road |
| WinAppSDK `MicaController` etc. | NO for now | runtime redistributable cost ≫ benefit |
| `SetWindowCompositionAttribute` / ACCENT | **NEVER** (ratify) | drag-lag 1903+, dead 22631 |
| `DWMWA_MICA_EFFECT` (1029) | **NEVER** (ratify) | deleted by Microsoft within one cycle |
| `DwmEnableBlurBehindWindow` | NO | blur dead since Win8; historical only |

---

*Synthesis lane, glass council, 2026-07-13 night. The council forged ten
documents; this one is built from the parts that survived Loki's attack
and Fenrir's kill floor, with every contradiction resolved by name. The
skeleton is honest (TOKEN everywhere, forever, by construction), the
ambition is funded (the GlassShell is the reference look on the road the
physics actually permit), and the safety constitution never entered the
negotiation.*
