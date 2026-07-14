# Ymir — Environment/Degradation Matrix + Runtime Detection

**Glass Council lane: the substrate.** Ymir, Infrastructure & Deployment
(NorthStar council, on loan). 2026-07-13 night. project_tct read-only;
this file is the only deliverable.

My north star here is the same one I hold for installers: **the operator
at 2am, on whatever machine the lab happens to own, must never see a
broken window.** A material system that is beautiful on the dev laptop
and white over RDP is not a material system — it is a demo. So this
document does not argue about which glass is prettiest (other lanes do
that); it answers three questions for every environment the cockpit will
realistically meet:

1. What do Mica/Acrylic *actually do* there?
2. How can the app *honestly know* that at runtime — API, registry, or
   pixel truth, cited, no vibes?
3. Which tier must engage?

Honesty rule applied throughout: **an S_OK from DWM is a claim, not a
fact.** The afternoon investigation proved this on our own machine —
`apply_backdrop` returned success while the main window rendered
pixel-identical with the material on and off
(`docs/design/glass_gap_findings.md` §1). The detection ladder therefore
ends in a pixel probe, not in an API return code.

---

## 1. The tier model

Three tiers, one token vocabulary. Every visual token in `gui/style.py`
must have a defined value at every tier; the tier is a single global
enum, decided by the ladder in §3, consumed identically by the classic
QWidget shell today and the QML shell later.

| Tier | Name | Mechanism | OS dependency |
|---|---|---|---|
| **T0** | `real` | Live compositor material. Classic shell: DWM Mica/Acrylic (`DWMWA_SYSTEMBACKDROP_TYPE`) behind an alpha-carrying canvas (`rgba(bg, BACKDROP_CANVAS_ALPHA=0.82)`, `PANEL_GLASS_ALPHA=0.55` on `glassPane` opt-ins). QML shell: additionally in-app scenegraph blur (per-item layers) — see §7. | Win11 22H2+, native `windows` QPA, transparency on, not remoted, verified by probe |
| **T1** | `token` | **Pre-blended token glass.** The *same hues*, computed by color-mix at style-build time and painted **fully opaque**: canvas = `mix(bg, bg, …)` ≡ `bg`-family solid; `glassPane` panels = `mix(panel, bg, 0.55)` solid; the existing `chrome`/`strip`/`edge` pre-blends. Zero alpha reaches the OS. Looks like frozen glass; cannot break. | None. Pure QSS. Works on Win7-class paint, RDP, Linux, offscreen |
| **T2** | `flat` | Classic shell, plain `p['bg']` / `p['panel']` solids, no glass pretense. Required verbatim for high-contrast; also the operator's manual escape hatch. | None |

**Never-white invariants (constitution-grade, all tiers):**

- **I1 — No alpha without a verified material.** `WA_TranslucentBackground`
  / transparent palette roles / `rgba()` canvas fills may exist only
  while tier == T0 *and* the probe (§3 L6) has passed. `backdrop.py`
  already implements the apply-side half (translucency set only after
  both DWM calls succeed, backdrop.py:317-327); the ladder adds the
  verify-side half.
- **I2 — Dark-mode flag travels with the material.**
  `DWMWA_USE_IMMERSIVE_DARK_MODE` (attribute 20, documented Win11;
  functional since Win10 19041 [1]) must be asserted in the same beat as
  attribute 38, and re-asserted on every theme fan-out and every
  `WM_SETTINGCHANGE`. A lost dark flag = DWM composites **light Mica**
  behind a dark translucent canvas = the "completely white" symptom from
  tonight's live session (BRIEF symptom 2, prime suspect). This is the
  cheapest single insurance in the whole document.
- **I3 — T1/T2 are opaque by construction.** The fallback look is
  pre-blended solid hex. There is no environment in which T1 can render
  white unless the palette itself is white.
- **I4 — Downgrade is instant, upgrade is verified** (§5).
- **I5 — The decided tier and every raw input are logged as ONE
  greppable INFO line at startup and at every re-decision** (§8). When
  the 2am operator files "it looks wrong", the log answers "what did the
  app believe about its environment" without a debugger.

---

## 2. The environment matrix

Columns: what the OS materials actually do there → how we detect it
honestly → tier. Citations in §10.

| # | Environment | What Mica/Acrylic do | Honest runtime detection | Tier |
|---|---|---|---|---|
| E1 | **Win11 22H2/23H2 (22621/22631)** | Full support; attr 38 is public API from 22621 [2]. Mica samples wallpaper+theme (static, cheap); Acrylic samples live content behind the window (costlier). | `sys.getwindowsversion().build >= 22621` + `platformName()=="windows"` (exists: `backdrop.is_backdrop_supported`) + ladder L2–L6. | **T0** |
| E2 | **Win11 24H2/25H2 (26100/26200)** | Same API, verified working on our own 26200 (theme-editor dialog blurs — `docs/research/dwm_backdrop_blur_recipe.md`). Known ecosystem wrinkle: Qt 6.10.x "phantom white box" stale-backing bug on 24H2, fixed by resize [9]. Insider builds tightened Mica's wallpaper policy to the active/primary desktop — irrelevant to Acrylic. | Build gate as E1. The stale-backing case is invisible to every API — **only the pixel probe (L6) catches it**; mitigation: post-apply resize jiggle, then probe. | **T0** (probe-guarded) |
| E3 | **Win11 21H2 (22000)** | Attr 38 does not exist → `DwmSetWindowAttribute` returns `E_INVALIDARG`. Mica reachable only via undocumented `DWMWA_MICA_EFFECT=1029` [3] — unsupported, can vanish in any update. | Build gate (22000 < 22621) already excludes it; belt-and-braces: the `E_INVALIDARG` HRESULT itself is an honest signal if the gate is ever loosened. | **T1** (policy: never ship the undocumented attr) |
| E4 | **Windows 10 (any build, incl. LTSC lab images)** | No system backdrop API at all. Blur-behind only via undocumented `SetWindowCompositionAttribute`/`ACCENT_POLICY` — known jank (drag lag), already explicitly banned in `backdrop.py:63-66`. DWM composition itself is always on since Win8 (`DwmIsCompositionEnabled` returns TRUE unconditionally [4] — useless as a detector, kill that myth). | Build gate. | **T1** |
| E5 | **RDP / RemoteApp session** (lab PCs are remoted *routinely*) | DWM still composites (Win8+), but Acrylic is **replaced by its solid fallback color by design** in remote sessions; Mica likewise falls back [5]. The fallback color is system-chosen — in light mode it is near-white: exactly the broken look we must never show behind a dark theme. | `GetSystemMetrics(SM_REMOTESESSION)` (0x1000) [6]; for the console-remoted edge case compare `ProcessIdToSessionId` with `HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server\GlassSessionId` [6]. **Critical: this changes mid-session** — a locally started cockpit gets RDP'd into from home. Subscribe `WTSRegisterSessionNotification` → `WM_WTSSESSION_CHANGE` (`WTS_REMOTE_CONNECT`/`WTS_CONSOLE_CONNECT`) [7] and re-run the ladder. | **T1** on remote; restore T0 on console reconnect only after re-probe |
| E6 | **VM / no GPU / Microsoft Basic Display (WARP)** | DWM renders via WARP software rasterizer; materials are documented to fall back on "low-end hardware" [5] — whether they do is the OS's opaque decision. | No trustworthy API says "DWM decided to fall back". Optional hint: DXGI adapter enum for "Microsoft Basic Render Driver" (VID 0x1414/DID 0x8C) — heavy via ctypes and still only a hint. **The pixel probe is the only truth here.** | **T0 attempt → probe decides**; fail ⇒ T1 |
| E7 | **Battery saver ON** (laptop cockpit, unplugged) | Windows suspends transparency effects system-wide while battery saver is active; materials render fallback solids [5]. Comes and goes with the charger. | `GetSystemPowerStatus` → `SYSTEM_POWER_STATUS.SystemStatusFlag & 1` ("battery saver is on") [8]; event: `WM_POWERBROADCAST` / `PBT_APMPOWERSTATUSCHANGE`. | **T1 while active**; T0 restore on AC per §5 hysteresis |
| E8 | **Transparency effects OFF** (Settings→Personalization→Colors) | All materials render their solid fallback colors [5]. Common on lab images and IT-hardened machines. | Two sources, ranked: (a) `UISettings.AdvancedEffectsEnabled` (WinRT, documented, has a changed event [10]) — correct but drags WinRT interop into Python; (b) `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize\EnableTransparency` (DWORD, 0=off) — undocumented-but-decade-stable, free via `winreg`. Pragmatic: read (b) at decision time, re-read on `WM_SETTINGCHANGE`, let L6 arbitrate disagreement. | **T1** |
| E9 | **High contrast (Contrast Themes)** | Transparency force-disabled; system enforces its palette; per accessibility policy an app must not fake translucency. | `SystemParametersInfo(SPI_GETHIGHCONTRAST)` → `HIGHCONTRAST.dwFlags & HCF_HIGHCONTRASTON` [11]; changes broadcast via `WM_SETTINGCHANGE`/`WM_THEMECHANGED`. | **T2, mandatory** — accessibility outranks design; do not even token-glass |
| E10 | **Multi-monitor, mixed DPI** | Materials themselves work per-monitor. Real risks: (a) `WM_DPICHANGED` surface recreation can trigger the E2 stale-backing white box; (b) fractional devicePixelRatio seams expose 1px canvas lines (cosmetic); (c) **our own probes** sample wrong pixels if not per-monitor-DPI-aware. | Qt `QWindow::screenChanged` + `WM_DPICHANGED`; probe coordinates always in physical pixels via the target screen's `devicePixelRatio()`. Re-probe after every screen migration. | **T0**, re-probed on migration |
| E11 | **Windows Server (RDS hosts)** | Server 2022 = build 20348 (< 22621) ⇒ no API. Server 2025 = 26100 ⇒ API exists but the realistic access path is RDP (E5) and effects are typically disabled server-side. | Build gate + E5/E8 rungs cover it with zero extra code. | **T1** |
| E12 | **Offscreen / headless (`QT_QPA_PLATFORM=offscreen` — the whole test suite)** | No compositor exists; DWM blur is compositor-side, full stop (glass_gap_findings §4). | `platformName() != "windows"` (exists). | **T1** (tests pin T1/T2 QSS text byte-identically) |
| E13 | **Linux — PORT1: Ubuntu reference, AlmaLinux sim (roadmap, pre-seed)** | **DWM does not exist.** Desktop-blur-behind is per-compositor and non-standard: KDE/KWin exposes `_KDE_NET_WM_BLUR_BEHIND_REGION` (X11) / the KWin Wayland blur protocol [12]; GNOME/Mutter has **no** blur-behind API at all. Chasing per-compositor hints = an unbounded support matrix; policy: never attempt desktop glass on Linux v1. The QML horizon changes the game honestly: scenegraph in-app blur blurs the app's *own* content — compositor-independent, works on any GPU, and is closer to the actual visionOS look anyway (visionOS glass blurs app content, not your desktop). | `sys.platform != "win32"` (static, trivial — exists). QML horizon adds: `QSGRendererInterface::graphicsApi() == Software` or `QT_QUICK_BACKEND=software` ⇒ no live blur [13]; PORT1's ratified `QSG_INFO=1` parser already rejects silent software fallback (ROADMAP_MASTERPLAN "Portability"). | **T1** today; **T0-QML (in-app)** post-U-track iff hardware scenegraph |
| E14 | **Window deactivated (focus lost)** | Transient-window Acrylic is documented to fall back on deactivation in the WinUI material [5]; behavior of raw `DWMSBT_TRANSIENTWINDOW` on a main window is observed-variable across builds. Not a broken state — a designed one. | Do not chase it. Accept the OS's deactivation fallback; verify once per build with the pixel harness that the fallback is *its solid color*, not white-over-dark. If a build misbehaves: Mica (`DWMSBT_MAINWINDOW`) is the calmer default for a long-lived cockpit precisely because it is wallpaper-static. | **T0** (OS-managed dip) |

---

## 3. The detection ladder (the heart)

Ordered cheapest-first; **any rung failing short-circuits downward to
its stated tier; only a full pass earns T0.** Rungs L0–L4 are pure reads
(no side effects, safe at import — hardware-safety rule 1 analog:
detection must never mutate). L5–L6 run only at apply time, per window.

```
L0  Platform        sys.platform == "win32"  AND
                    QGuiApplication.platformName() == "windows"
                    (exists: backdrop._platform_probe)          fail ⇒ T1
L1  Build gate      sys.getwindowsversion().build >= 22621 [2]
                    (exists: backdrop._version_probe)           fail ⇒ T1
L2  Session         NOT (GetSystemMetrics(SM_REMOTESESSION) or
                    sessionId != GlassSessionId) [6]            fail ⇒ T1
L3  User settings   SPI_GETHIGHCONTRAST off [11]                fail ⇒ T2
                    EnableTransparency reg == 1 (E8)            fail ⇒ T1
L4  Power           GetSystemPowerStatus.SystemStatusFlag
                    & 1 == 0 (battery saver off) [8]            fail ⇒ T1
L5  Apply+readback  DWMWA_USE_IMMERSIVE_DARK_MODE(20) asserted
                    to match theme (I2), THEN attr 38 set;
                    both HRESULTs == S_OK; DwmGetWindowAttribute
                    read-back of 38 matches [2]                 fail ⇒ T1
L6  PIXEL TRUTH     micro-probe (below)                         fail ⇒ T1
```

### L6 — the pixel truth probe

The only rung that can catch E2 (stale backing), E6 (silent WARP
fallback), the pixel-equal barrier we actually shipped, and any future
"S_OK but inert" mode. It is `scripts/capture_onscreen.py`'s verdict
logic distilled to a runtime micro-check:

- **When:** first `QExposeEvent` of the backdrop window + 2 frames
  (material needs composited frames to exist); again after every ladder
  re-run; never while `WTS_SESSION_LOCK` is active (screen capture of a
  locked session returns garbage) and never mid-scan (§5).
- **What:** BitBlt a designated ~8×8 px patch of *exposed canvas* (the
  window's outer margin — glass_gap_findings §4 established margins are
  the only honestly-exposed canvas) from the **screen DC** (compositor
  output; `PrintWindow` sees only the app's own paint and is useless
  here). Coordinates in physical pixels via the window's screen
  `devicePixelRatio()` (E10).
- **Two checks, two failure classes:**
  1. **Inertness:** toggle attr 38 `DWMSBT → NONE → DWMSBT` across ~2
     frames at fixed geometry (desktop behind is static at that
     timescale); delta below noise threshold ⇒ material is not
     compositing ⇒ **T1**. This is precisely the check that would have
     flagged the afternoon's pixel-equal barrier at runtime instead of
     in a post-mortem.
  2. **Wrong-material (white guard):** probe luminance vs the active
     palette. Dark theme + probe luminance > threshold ⇒ light material
     behind dark chrome (W1, tonight's suspect) ⇒ re-assert attr 20
     once, re-probe; still bright ⇒ **T1 immediately**. This rung alone
     discharges the product mandate: *never show broken white* — worst
     case the user sees pre-blended dark tokens one probe-cycle
     (~100 ms) after the failure.
- **Cost:** two 8×8 BitBlts + one attribute toggle, per decision event
  — not per frame. Negligible.
- **Honesty about the probe itself:** it needs the window visible on a
  real screen. If the probe *cannot run* (occluded, minimized, locked),
  the tier stays at its last verified value and the state is logged as
  `probe=deferred` — unverified T0 is never newly *granted*, but an
  already-verified T0 is not revoked by mere inability to re-measure.

### Re-evaluation triggers (the ladder is an event loop, not a startup rite)

| Event | Mechanism | Rungs re-run |
|---|---|---|
| RDP connect/disconnect, console switch, lock | `WM_WTSSESSION_CHANGE` via `WTSRegisterSessionNotification` [7] | L2, L5–L6 |
| Transparency/theme/contrast toggled | `WM_SETTINGCHANGE` (incl. `"ImmersiveColorSet"`), `WM_THEMECHANGED` | L3, I2 re-assert, L5–L6 |
| Charger pulled / battery saver | `WM_POWERBROADCAST` | L4, L5–L6 |
| Monitor migration / DPI change | Qt `screenChanged` + `WM_DPICHANGED` | L6 |
| Theme fan-out (`_toggle_theme`) | in-app | I2 re-assert, L6 |

All native messages arrive through one `QAbstractNativeEventFilter`
installed at app start — PySide6 supports this directly; it belongs in
the same single ctypes-owning module as the rest (backdrop.py's "only
place in the GUI package that touches DWM" rule extends to "only place
that reads the environment").

---

## 4. White-failure taxonomy → which rung catches it

| # | Failure | Look | Caught by |
|---|---|---|---|
| W1 | Dark-mode flag lost → light Mica behind dark theme | **solid white regions** (tonight's symptom) | I2 (prevention) + L6 luminance (detection) |
| W2 | Alpha hole, no material behind (QMainWindow client no-alpha — proven, recipe note §1) | crisp desktop through margins; white if desktop light | I1 ordering (prevention) + L6 inertness |
| W3 | System fallback solid under our alpha canvas (E5/E7/E8) | wrong-tinted, possibly near-white | L2/L3/L4 (prediction) + L6 (verification) |
| W4 | Stale backing store (Qt 6.10/24H2 phantom white box [9]) | white rectangle until resize | post-apply resize jiggle + L6 |
| W5 | `WS_EX_LAYERED` uniform alpha suppressing material (the opacity-pin, found & fixed once) | crisp desktop through *everything* | existing opacity/backdrop mutual-exclusion pin + its regression test; keep as invariant |

---

## 5. Tier transition policy (hysteresis)

- **Down: same event, immediately.** A downgrade is one style re-apply
  (opaque token QSS) + one DWM reset — the fail-safe direction is never
  rate-limited.
- **Up: only after (a) a trigger says the environment improved, (b) L5+L6
  pass, (c) ≥60 s since the last upgrade attempt.** Charger-flapping on
  a marginal battery must not strobe the cockpit.
- **Scan freeze:** while the acquisition state machine is in an active
  run, tier changes are **queued, not applied** (a full-window restyle
  repaint storm during a measurement is a lab no-no; and L6's attribute
  toggle must not perturb capture timing). Applied at run end. Downgrade
  exception: W1-class white *is* applied mid-scan — broken-white beats
  repaint purity — but as the single opaque-QSS swap only, probe toggles
  deferred.
- **No undefined states:** the tier variable has exactly the three
  values; every transition is logged (I5); a fresh session re-derives it
  from disk-truth inputs, never from a cached belief. (Session-hygiene
  rule 1, applied to pixels.)

---

## 6. Three horizons

- **Horizon 1 — classic QWidget cockpit (now):** everything above,
  verbatim. T0 remains honest-but-modest: material in canvas margins and
  `glassPane` opt-ins only; panels/plots/camera stay opaque (ratified).
  The matrix says the *typical lab deployment* (RDP'd Win10/Server
  boxes, hardened images) lands on **T1 more often than T0** — which is
  exactly why T1 must be first-class-pretty, not an apology. Budget
  accordingly: T1 is the look most users see.
- **Horizon 2 — QML U-track (U0–U6):** the ladder is unchanged; two
  rungs extend. (a) L0 gains a scenegraph check:
  `QSGRendererInterface::graphicsApi()` must be a hardware API
  (D3D11/Vulkan/Metal/OpenGL); `Software` ⇒ no live blur ⇒ T1 [13] —
  aligned with PORT1's ratified QSG_INFO parser. (b) T0 splits
  internally: *T0-DWM* (desktop shows through window canvas —
  Windows-only, cosmetic) and *T0-QML* (in-app per-item layer blur —
  portable, works on Linux/E13, GPU-gated, RDP-**tolerant** since it
  needs no compositor materials, though bandwidth still argues for T1
  over WAN). The QML shell consumes the same tier enum via a context
  property; QML must contain **zero** environment logic of its own.
- **Horizon 3 — the seed:** the inheritable artifact is *this contract*:
  the tier enum, the token-per-tier vocabulary, the ladder module, and
  the probe harness. `PLATFORM_SEED.md` already carries a portability
  matrix (roadmap); the glass matrix above is its display-stack chapter.
  LabControl inherits "never broken white" as a tested property, not as
  folklore.

---

## 7. Proposed module contract (design only — no code in this beat)

`gui/glass_env.py` (companion to `gui/backdrop.py`, same ctypes-quarantine
rule):

- `probe_environment() -> GlassEnvironment` — frozen dataclass of every
  raw L0–L4 input (build, platform, remote, high_contrast, transparency,
  battery_saver, screens…). Pure reads, monkeypatchable per field
  exactly like `backdrop._version_probe` / `_platform_probe` already are
  — **the whole matrix in §2 becomes a parametrized offscreen test**, no
  matching host required.
- `decide_tier(env) -> GlassTier` — pure function of the dataclass ⇒
  every row of §2 is one assert.
- `verify_material(window) -> ProbeResult` — L5+L6; the only impure part;
  skipped/stubbed offscreen (offscreen pins T1 anyway, E12).
- `GlassWatcher(QAbstractNativeEventFilter)` — the §3 trigger table;
  emits `tierChanged(GlassTier)`; `style.py`/QML subscribe.
- **Operator override:** `QSettings` key `theme/glass_tier` ∈
  `auto|real|token|flat` (default `auto`). When detection lies — and
  somewhere, someday, on some driver, it will — the 2am human forces
  `flat` and the cockpit obeys without a code change. Override is logged
  loudly (I5) so a forgotten `flat` doesn't masquerade as a regression.
- **One-line truth log:** `glass: tier=token (build=26100 remote=1
  transparency=1 hc=0 saver=0 hr38=0x0 probe=inert)` — greppable,
  bench-checklist-able, attachable to any bug report.

**Regression hooks:** (1) the parametrized `decide_tier` matrix test;
(2) the byte-identical-when-off QSS guards already landed
(`test_theme_editor.py`) extend to per-tier golden QSS; (3) the onscreen
pixel harness (`capture_onscreen.py`) stays the *bench* gate for what
offscreen cannot see — its scenario list should add `rdp` (run once via
an actual loopback RDP session), `transparency_off`, and `battery_saver`
rows, each asserting non-white margins under the dark theme.

---

## 8. Report JSON

```json
{
  "status": "done",
  "file_written": "docs/design/glass_council/ymir.md",
  "detection_ladder": "L0 platform → L1 build≥22621 → L2 session (SM_REMOTESESSION+GlassSessionId, WM_WTSSESSION_CHANGE) → L3 settings (EnableTransparency, SPI_GETHIGHCONTRAST) → L4 power (battery-saver flag) → L5 DWM S_OK+readback+dark-flag → L6 pixel truth probe; any fail ⇒ opaque token tier, HC ⇒ flat; downgrade instant, upgrade verified"
}
```

---

## 9. Sources

1. `DWMWA_USE_IMMERSIVE_DARK_MODE` (attr 20) — Support Dark/Light themes
   in Win32 apps: https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-windows-themes
2. `DWMWA_SYSTEMBACKDROP_TYPE` (attr 38, "supported starting Windows 11
   Build 22621") + `DWM_SYSTEMBACKDROP_TYPE` enum:
   https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type ;
   Apply Mica in Win32: https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-mica-win32
3. `DWMWA_MICA_EFFECT=1029` undocumented (21H2 community path, e.g.
   winmica): https://github.com/amnweb/winmica — policy-excluded.
4. `DwmIsCompositionEnabled` remarks ("always enabled" since Win8):
   https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmiscompositionenabled
5. Material fallback conditions (transparency off, battery saver,
   low-end hardware, remote desktop, deactivation): Acrylic —
   https://learn.microsoft.com/en-us/windows/apps/design/style/acrylic ;
   Mica — https://learn.microsoft.com/en-us/windows/apps/design/style/mica ;
   System backdrops — https://learn.microsoft.com/en-us/windows/apps/develop/ui/system-backdrops
6. `SM_REMOTESESSION` + `GlassSessionId` — Detecting the Terminal
   Services environment:
   https://learn.microsoft.com/en-us/windows/win32/termserv/detecting-the-terminal-services-environment
7. `WTSRegisterSessionNotification` / `WM_WTSSESSION_CHANGE`:
   https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/nf-wtsapi32-wtsregistersessionnotification
8. `GetSystemPowerStatus` / `SYSTEM_POWER_STATUS.SystemStatusFlag`
   (bit 0 = battery saver on):
   https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-system_power_status
9. Qt 6.10.x Mica phantom-white/stale-backing on 24H2 (resize-fixed):
   https://forum.qt.io/topic/163927 (corroborated in
   `docs/research/dwm_backdrop_blur_recipe.md`).
10. `UISettings.AdvancedEffectsEnabled` (+Changed event):
    https://learn.microsoft.com/en-us/uwp/api/windows.ui.viewmanagement.uisettings.advancedeffectsenabled
    (`EnableTransparency` registry key: well-known but *not* contractual
    — flagged as such in E8.)
11. `SPI_GETHIGHCONTRAST` / `HIGHCONTRAST` / `HCF_HIGHCONTRASTON`:
    https://learn.microsoft.com/en-us/windows/win32/winauto/high-contrast-parameter
12. KWin blur-behind (X11 `_KDE_NET_WM_BLUR_BEHIND_REGION`; KWin Wayland
    blur protocol) — KDE compositor-specific, non-standard:
    https://invent.kde.org/plasma/kwin (protocol docs); GNOME/Mutter has
    no equivalent public API.
13. `QSGRendererInterface::graphicsApi` / software scenegraph adaptation:
    https://doc.qt.io/qt-6/qsgrendererinterface.html ,
    https://doc.qt.io/qt-6/qtquick-visualcanvas-adaptations.html
