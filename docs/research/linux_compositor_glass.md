# Linux compositor glass — the Linux rows of the glass tier ladder

| | |
|---|---|
| **Date** | 2026-07-14 |
| **Asked by** | Adam (glass architecture, roadmap PORT1 — the platform seed must ship cross-platform) |
| **Exact question** | Is there any app-controllable background blur / window material on Linux (X11 atom, Wayland protocols, GNOME/Mutter)? What does translucency-without-blur mean for our readability/underlay law? Do Qt/PySide6 + our SCENE tier (in-scene baked frost) work identically on Ubuntu and AlmaLinux, incl. llvmpipe/VM and X-forwarding? Which `GlassTier` is achievable per Linux row? |
| **Scope anchors** | `docs/design/glass_council/SYNTHESIS.md` §2–§4 (tier enum `FLAT<TOKEN<WINDOW<SCENE<COMPOSED`; underlay law; readability contract), `docs/design/glass_council/ymir.md` E13 (the Linux row this note replaces) |
| **Confidence** | **official docs / official source** for every load-bearing claim (KWin source, wayland-protocols, Mutter MR, Qt docs, Ubuntu + RHEL release notes). Secondary (Phoronix) used only for *dates and version numbers*, flagged inline. Two items explicitly marked **unverified**. |

> **Headline:** Ymir's E13 verdict ("GNOME has no blur API, never attempt desktop
> glass on Linux") is **still operationally correct for our two target distros —
> but its reasoning is now out of date.** A standard Wayland blur protocol
> (`ext-background-effect-v1`) exists and *both* KWin and Mutter have implemented
> it — in versions **newer than anything Ubuntu 26.04 LTS or AlmaLinux 10 ship**.
> And even where a compositor supports it, **PySide6 cannot reach it** (§3.4).
> Net: unchanged plan, better reasons, with a named re-check trigger.

---

## 1. Do the target distros even default to GNOME? (yes — and both are Wayland-only)

| Distro | Desktop | Session | Consequence |
|---|---|---|---|
| **Ubuntu 26.04 LTS** (current LTS, Apr 2026) | **GNOME 50** [U1] | **Wayland-only.** Official release notes: *"The Ubuntu Desktop session now runs only on the Wayland back end, because GNOME Shell can no longer run as an X.org session."* X11 apps run via XWayland [U1] | No X11 session ⇒ the KDE X11 blur atom (§2) is **structurally unreachable** on stock Ubuntu Desktop |
| **AlmaLinux 10** (= RHEL 10, May 2025) | **GNOME 47** [R1][R2] | **Wayland-only, and the X.org server is *removed*** — RHEL 10 removed-features list: the X.org server *"was previously deprecated and is removed from RHEL 10"*; only XWayland remains [R1][R3] | Same, harder: there is no X server on the box at all |
| *(reference)* Kubuntu 26.04 LTS | Plasma 6.6, Qt 6.10.2, KF 6.24 [K1] | Wayland default; `plasma-session-x11` *"remains available in the Ubuntu archive — but it is not installed by default and is not supported by the Kubuntu team"* [K1] | The one row where compositor blur is real (§2, §3) |

Ubuntu's release notes do still say other X.org sessions ("KDE on X11, Xfce, MATE,
i3") can be launched [U1]; Kubuntu's own notes qualify that for Plasma [K1]. Both
are *opt-in, non-default, unsupported-by-vendor* configurations — not something a
lab-app glass tier may depend on.

**RHEL freezes its desktop stack per major release.** GNOME 47 is what AlmaLinux 10
has for its lifecycle; blur support (GNOME 51, §3.2) is RHEL-11-era, i.e. ~2030.

---

## 2. X11: `_KDE_NET_WM_BLUR_BEHIND_REGION` — real, precise, and irrelevant to us

**What it is** (verified in KWin's own source, `src/plugins/blur/blur.cpp`, master [X1]):

- Atom name: `_KDE_NET_WM_BLUR_BEHIND_REGION` (`static const QByteArray s_blurAtomName`).
- Property type **`XCB_ATOM_CARDINAL`**, **format 32**.
- Value = a flat list of `uint32` **`(x, y, width, height)` quadruples** (window-local
  coords), read as `cardinals->size() % 4 == 0`.
- **`size() == 0` or `size() == 1` ⇒ "blur background behind whole window"** (the
  code comment says exactly that).
- It instructs the *compositor* to blur what is behind the window in that region. The
  app must still paint with alpha there — the atom grants permission/region, it does
  not make your window translucent.

**Who honors it:**

| Compositor | Honors the atom? | Evidence |
|---|---|---|
| **KWin** (Plasma, X11) | **Yes** — it is KWin's own atom | KWin source [X1] |
| **picom** | **No** (no evidence). picom blurs by *its own config rules* (`blur-background`, `blur-background-exclude` match expressions) applied to ARGB/translucent windows — **user-controlled, not app-controlled** | picom(1) man page [X2] |
| **Deepin (DDE)** | Different atom (`_NET_WM_DEEPIN_BLUR_REGION_ROUNDED`) | [X3] |
| **Mutter (GNOME) on X11** | **No** — and moot: neither target distro has a GNOME X11 session | [U1][R1] |
| xfwm4 / others | **not verified this session** — do not assume | — |

**Reachable from PySide6?** *On X11, yes, without any Qt native interface:*
`int(widget.winId())` is the XID, and the property can be set with `xcffib`/`python-xlib`.
This is exactly what KDE's own `KWindowEffects::enableBlurBehind()` does via xcb
(`kwindowsystem/src/platforms/xcb/kwindoweffects.cpp` [X4]).

**Verdict:** technically cheap, practically dead. It requires *KWin on an X11 session*.
Ubuntu Desktop has no X11 session [U1]; AlmaLinux 10 has no X server [R1]. It would
only ever serve a hand-configured Kubuntu-on-X11 box.

---

## 3. Wayland: there IS a blur protocol now — two, in fact

### 3.1 `org_kde_kwin_blur` (KDE, since 2015)

- Source of truth: `plasma-wayland-protocols/src/protocols/blur.xml` [W1].
- Interfaces: **`org_kde_kwin_blur_manager` v1** (`create(id, wl_surface)`, `unset(wl_surface)`)
  and **`org_kde_kwin_blur` v1** (`set_region(wl_region|null)`, `commit()`, `release()`).
- **License: LGPL-2.1-or-later**, © 2015 Martin Gräßlin, Marco Martin [W1] — relevant if
  we ever vendor the XML for a binding generator.
- Status: KDE-private, "unstable" [W2]. **Implemented by KWin.** (wayland.app renders a
  broad compositor-support table; I could not read it reliably and **do not cite it** —
  the only implementer I verified is KWin. Treat any "Sway/Weston/Mutter support kde-blur"
  claim as **unverified and probably false**.)

### 3.2 `ext-background-effect-v1` (the new standard) — and GNOME's flip

- **Merged into `wayland-protocols` staging (May 2025)**, authored by **Xaver Hugl (KDE)**,
  after discussion since Jan 2024; explicitly *"roughly based on the org_kde_kwin_blur
  protocol"* and generalized so other effects (e.g. contrast) can be added [W3][W4].
- Semantics: the client creates one background-effect object per surface and sets a
  **surface-local region whose *background* the compositor blurs**; double-buffered on
  surface commit; the compositor keeps rendering + policy authority [W4][G1].
- **KWin: merged → Plasma 6.7** [W5][G2 (Phoronix, version claim)].
- **GNOME/Mutter: merged → GNOME 51** [G2][G3]. Mutter MR !5071 (Kristof Imerir):
  *"Mutter captures the already-painted framebuffer contents behind the requested region,
  blurs them offscreen, and paints the blurred result back... This does not change GNOME
  Shell visuals or enable blur globally. **Clients only request the effect for their own
  surfaces, and Mutter remains responsible for rendering and policy.**"* [G3]
- **My strong prior was wrong on the reasoning, right on the outcome.** GNOME issue #3023
  ("Background blur frosted glass effect API for toolkits and applications") is **open, not
  refused** — the maintainers' position was *"help finalize the Wayland protocol proposals
  and implement it in Mutter"*, i.e. a contribution gate, not a policy veto [G1]. That gate
  has now been passed by an outside contributor.
- KWin master's blur plugin already registers through the new manager:
  `waylandServer()->backgroundEffectManager()->addBlurCapability()` [X1].

### 3.3 …but not in any version our targets ship

| Target | Ships | Blur protocol present? |
|---|---|---|
| Ubuntu 26.04 LTS (GNOME **50**) | GNOME 50 [U1] | **NO** — needs GNOME **51** [G2]. Earliest: Ubuntu 26.10; for LTS users realistically **28.04** unless Canonical backports Mutter (they do not backport GNOME majors into an LTS) |
| AlmaLinux 10 (GNOME **47**) | GNOME 47 [R1] | **NO**, and **not within the OS lifecycle** (RHEL freezes GNOME per major) |
| Kubuntu 26.04 (Plasma **6.6**) | Plasma 6.6 [K1] | `ext-background-effect-v1` **NO** (needs 6.7); **`org_kde_kwin_blur` YES** (since 2015) [W1] |

### 3.4 The killer: **PySide6 cannot reach either Wayland protocol**

- **Qt exposes no API for blur.** Neither QtWayland nor Qt Quick implements a client for
  `org_kde_kwin_blur` or `ext-background-effect-v1` (no such API in Qt 6 docs; no evidence
  found). The apps that get blur on KDE do it through **KWindowSystem's `KWindowEffects`**
  (KF6, LGPL) — e.g. VLC's MR "use `KWindowEffects::enableBlurBehind()` and enable blur in
  compositor_wayland" [X4][W6] — and that Wayland path additionally *requires the
  plasma-integration platform theme to be loaded* [X4].
- **From Python it is worse: we cannot even obtain the `wl_display`.**
  `QNativeInterface::QWaylandApplication` (and `QX11Application`, `QEGLContext`, `QGLXContext`)
  are on the official **Qt-for-Python "Missing Bindings"** list — *not exposed in PySide6* [Q1].
  So there is no supported route from pure Python to a raw Wayland protocol binding via Qt.
- Cost to change this: a C++/shiboken extension or a KF6 dependency — for a feature that
  **does not exist on either target distro anyway**.

### 3.5 Plain consequence (state this in the ladder)

> **On Ubuntu 26.04 LTS and AlmaLinux 10, compositor-provided glass is NOT available to
> this application — at any price.** Not because Linux lacks the concept (it no longer
> does), but because (a) the shipped GNOME versions predate the protocol, (b) there is no
> X11 session to fall back to, and (c) PySide6 has no binding to the protocol even where a
> compositor implements it. The Linux equivalent of the `WINDOW` tier is **absent**, and
> `COMPOSED` (DWM/Windows.UI.Composition) is Windows-only by definition.

---

## 4. Translucency without blur — and why it must stay OFF on Linux

**Correct, as stated in the brief.** On Wayland a compositor is mandatory and every surface
can carry alpha, so a translucent window "just works" — and shows **the raw, unblurred
desktop/windows behind it**. (On X11 it additionally requires a compositing WM and an ARGB
visual; with no compositor you get black/garbage.)

Consequences under our own laws:

1. **Readability contract (`SYNTHESIS.md` §4.2)** demands ≥ 4.5:1 contrast against *both*
   worst-case extremes. Behind a translucent window on GNOME sits **arbitrary user content
   of unbounded luminance** (a white browser, a black terminal, a photo wallpaper). No
   token alpha can satisfy the contract against that. Blur does not fix contrast either —
   but it at least removes high-frequency structure; **without blur there is nothing to
   argue with.**
2. **Underlay law (`SYNTHESIS.md` §4.1)**: every glass surface paints its `TOKEN` pre-blend
   **first**, opaque. If the underlay is honored, window-level translucency buys **exactly
   zero visible photons** — the opaque pre-blend already covers the surface. So on Linux,
   translucency is all risk and no reward.
3. Therefore: **Linux top-levels stay opaque.** Do not set `WA_TranslucentBackground`; do
   not set `QQuickWindow.color = "transparent"`; do not call
   `QQuickWindow::setDefaultAlphaBuffer(True)` on Linux. (`main.py::_enable_translucent_window_surface`
   must be **Windows-gated** — flag this as a concrete code check for the GlassShell beat.)
   This also sidesteps the entire class of Qt/Wayland translucency + CSD-shadow bugs
   without needing to enumerate it.

---

## 5. Qt / PySide6 on Linux

| Question | Answer | Source |
|---|---|---|
| **Default RHI backend per platform** | *"When no command-line arguments are specified, platform-specific defaults are used: **Direct 3D 11 on Windows, OpenGL on Linux, Metal on macOS/iOS**."* Vulkan is available but **not** the Linux default. | Qt 6 docs [Q2] |
| **How to pin** | `QSG_RHI_BACKEND` = `opengl` \| `vulkan` \| `d3d11` \| `metal` \| `null`, or `QQuickWindow::setGraphicsApi()` with `QSGRendererInterface::GraphicsApi` (call before window creation). | Qt 6 docs [Q2][Q3] |
| **Adaptation switch** | `QT_QUICK_BACKEND=software` (legacy `QMLSCENE_DEVICE`) or `QQuickWindow::setSceneGraphBackend("software")`. RHI is the default adaptation on all platforms since Qt 6.0. | Qt 6 docs [Q3] |
| **`WA_TranslucentBackground` X11 vs Wayland** | Works on both *in principle* (Wayland: compositor always composites; X11: needs a compositing WM + ARGB visual) — but see §4: **we must not use it on Linux.** | Qt docs [Q4] + §4 reasoning |
| **`QQuickWindow` translucency API** | *"In any application which expects to create translucent windows, it's necessary to set this [`setDefaultAlphaBuffer`] to true **before creating the first QQuickWindow**."* Default is `false`. | Qt 6 docs [Q4] |
| **QQuickWindow-root shell (GlassShell) on Linux** | No Linux-specific blocker found for a `QQuickWindow`/`ApplicationWindow` root with `WindowContainer`-hosted native islands. The DWM layer (`gui/backdrop.py`) simply no-ops off-Windows (already true). **Caveat (design, not bug):** Wayland gives clients **no absolute window positioning** (xdg-shell) — detached/floating windows and popovers are placed by the compositor. Relevant to the detach/dock and popover rules. *(Well-established Wayland design; **not re-verified this session** — mark as such.)* | — |

---

## 6. The load-bearing question: is the **SCENE** tier genuinely portable?

**SCENE** = app-owned glass rendered *inside* the QML scene graph: an opaque TOKEN underlay,
a baked/pre-blurred ambient texture sampled by `Image` at the pane's scene coordinates, plus
tint/hairline/specular geometry. `SYNTHESIS.md` §2.2.2 already bans `ShaderEffect`/`MultiEffect`
("Plain `Image` sampling … works on the software scenegraph backend, pixel-hashable in CI").

**Verdict: YES — portable, with four named caveats.** It needs **no compositor support, no
blur protocol, no translucent window, and no GPU-specific feature**. It is the *same* pixels
on Windows, Ubuntu-GNOME, AlmaLinux-GNOME, Kubuntu, and under llvmpipe — which is precisely
the property that makes it worth building.

### Caveat 1 (hard) — the *bake* must be CPU-side

The software adaptation **cannot render `ShaderEffect`** (and cannot do particles) [Q5]. If
the frost bake is implemented as a GPU shader pass or a scene-graph grab that relies on
shaders, it **dies on the software backend** (VM / X-forwarding / any no-GL host) and takes
the whole SCENE tier down with it.
→ **Rule for beat G4:** bake with `QImage`/`QPainter`/numpy (or ship the texture as a build
asset); the runtime path must be nothing but `Image` + `Rectangle` + `opacity` + gradients.
This is a *portability requirement*, not a preference.

### Caveat 2 — llvmpipe (the AlmaLinux-in-a-VM case)

- With no GPU, Mesa gives you **llvmpipe** (`GL_RENDERER` contains `llvmpipe`); Qt logs
  *"Running on a software rasterizer (LLVMpipe), expect limited performance"* [Q6].
- The QML scene **does render** — static textures, rectangles and text are exactly what a
  rasterizer is good at. What llvmpipe punishes is **per-frame full-window recomposition**,
  large blits and animation.
- Qt's own recommendations for this case: `QSG_RENDER_LOOP=basic` (prevents animations
  running wild under software rasterization) and verifying with `QSG_INFO=1` +
  `QT_LOGGING_RULES=qt.qpa.gl=true` [Q6][Q7] — which **matches PORT1's already-ratified
  `QSG_INFO=1` parser** (`ROADMAP_MASTERPLAN.md` "Portability").
- **The real constraint is not the glass, it is FastDAQ.** `SYNTHESIS.md` §4.3 forbids the
  material machinery from contending with acquisition. A 15–30 Hz pyqtgraph/GL island plus a
  full-window QML recomposite on a CPU rasterizer is exactly that contention.
  → **Recommended policy: `GL_RENDERER ∈ {llvmpipe, swrast, softpipe}` or
  `QT_QUICK_BACKEND=software` ⇒ cap the tier at `TOKEN`** (SCENE opt-in only, for a
  screenshot/demo box). This is a one-line addition to `decide_tier`'s `GlassEnvironment`
  (`scenegraph_api` already exists in the dataclass) and it keeps the promise that glass
  never costs a measurement.

### Caveat 3 — text under the software backend

Software text rasterization *"does not respond as well to transformations such as scaling"*
[Q5]. Do not animate/scale text on the software path (we do not today).

### Caveat 4 — `layer.enabled` / item layers on the software backend

Qt's software-adaptation page names `ShaderEffect` and particles as unsupported but says
nothing definitive about item layers [Q5]. **Unverified — do not rely on `layer.enabled`
anywhere in the kit.** (Consistent with the existing ban; call it out in the kit spec.)

### Non-caveats (checked, fine)

- **Old distro Qt/Mesa is a non-issue for Qt**: we install **PySide6 from PyPI wheels**,
  which bundle their own Qt (`requirements.txt`: `PySide6>=6.5`). AlmaLinux's system Qt is
  irrelevant. What *does* come from the distro is **Mesa/the GL driver** — and RHEL-10-era
  Mesa provides a modern GL/llvmpipe; nothing in the SCENE path needs a recent GL feature.
- **`gui/backdrop.py` already no-ops off Windows** (platform probe) — no Linux work needed
  there; it just never earns a tier above what §3.5 allows.

---

## 7. X-forwarding / VNC

- Qt's VNC platform plugin **does not render OpenGL content**; the historical guidance for
  Qt Quick over remote/VNC is the **software backend** (`QT_QUICK_BACKEND=software`,
  legacy `QMLSCENE_DEVICE=softwarecontext`) [Q8].
- `ssh -X` to a Qt Quick app relies on **indirect GLX**, which is commonly unavailable or
  broken; the practical answer is again the software backend (or `QT_XCB_GL_INTEGRATION=none`),
  and on AlmaLinux 10 the *server* has no X.org at all [R1] — X11 apps are XWayland clients,
  and remote GUI is expected to go via Wayland-native remoting/RDP (gnome-remote-desktop) or VNC.
- **Verdict: TOKEN.** Glass over a WAN link is bandwidth spent on decoration while the
  operator waits for a scan point. This is a policy call, not a limitation — and it is the
  same answer Ymir gave for RDP on Windows.

---

## 8. Recommendation — the Linux rows of the tier ladder

Enum per `SYNTHESIS.md` §3.1: `FLAT(0) < TOKEN(1) < WINDOW(2) < SCENE(3) < COMPOSED(4)`.
"Max tier" = the ceiling `decide_tier` should allow on that row.

| # | Row | Max tier | Honest verdict |
|---|---|---|---|
| L1 | **Ubuntu 26.04 LTS — GNOME 50, Wayland** *(reference distro)* | **SCENE** | No compositor glass at all: GNOME 50 predates `ext-background-effect-v1` (GNOME 51) and there is **no X11 session** to use the KDE atom. Windows stay **opaque**; all glass is the app-owned baked frost. This is the reference Linux look. |
| L2 | **Ubuntu ≥ 26.10 / GNOME ≥ 51** *(future)* | **SCENE** *(WINDOW-class only after new native code)* | Mutter will blur an app-requested region — but **PySide6 has no binding** to `ext-background-effect-v1` (no `QNativeInterface::QWaylandApplication` [Q1]). Re-check trigger, not a plan. |
| L3 | **Ubuntu-KDE / Kubuntu 26.04 — Plasma 6.6, Wayland** | **SCENE** *(+ optional WINDOW-class via KWin, opt-in, never load-bearing)* | KWin **does** have blur (`org_kde_kwin_blur` since 2015). Reaching it needs KWindowSystem (KF6/LGPL) or a native binding + plasma-integration theme [X4]. Nice-to-have; must degrade to the identical SCENE look, per the underlay law. |
| L4 | **Kubuntu with `plasma-session-x11`** *(non-default, vendor-unsupported [K1])* | **SCENE** *(+ WINDOW-class cheaply: the atom is settable from pure Python via `winId()` + xcffib)* | The only genuinely cheap compositor-glass path on Linux — on a session neither we nor Kubuntu support. Do not build for it; document it. |
| L5 | **AlmaLinux 10 — GNOME 47, Wayland, no X server** | **SCENE** | Same as L1 and **permanently so**: GNOME 47 for the OS lifecycle, X.org removed [R1]. Compositor glass is off the table until RHEL 11. |
| L6 | **AlmaLinux headless / VM (llvmpipe or `QT_QUICK_BACKEND=software`)** | **TOKEN** *(SCENE renders, but opt-in only)* | SCENE is *renderable* (no shaders in the kit) — but a CPU rasterizer + 15–30 Hz FastDAQ islands is exactly the contention `SYNTHESIS.md` §4.3 forbids. Cap at TOKEN by policy; allow SCENE via the operator override for demo/screenshot boxes. |
| L7 | **X-forwarding (`ssh -X`) / VNC** | **TOKEN** | No (reliable) GL; Qt's VNC path has no OpenGL at all [Q8]. Force `QT_QUICK_BACKEND=software`, ship TOKEN. |
| L8 | **Offscreen / CI (`QT_QPA_PLATFORM=offscreen`)** | **TOKEN** | Unchanged from Ymir E12 — the byte-identical, compositor-independent floor the whole test spine rests on. |
| L9 | **High contrast / accessibility (any Linux row)** | **FLAT** | Unchanged and mandatory (§3.1). *Note:* Linux HC is a GTK/a11y setting Qt does **not** pick up automatically — detection on Linux is an open item (§9), the operator override covers it meanwhile. |

**`COMPOSED` is unreachable on Linux by definition** (it is the Windows composition-interop
tier). **`WINDOW` has no Linux implementation we can ship today.** The Linux ladder is
therefore effectively **FLAT / TOKEN / SCENE** — and the fact that SCENE is *identical* to
the Windows SCENE look, because it is app-owned, is the strongest argument in the whole glass
architecture for having built it that way.

### Direct answers to the brief

- **GNOME verdict:** No app-controllable blur in *shipped* GNOME. GNOME did **not** refuse it
  (issue #3023 open, "help implement it") — Mutter merged `ext-background-effect-v1` for
  **GNOME 51**, which neither Ubuntu 26.04 (GNOME 50) nor AlmaLinux 10 (GNOME 47) ships.
- **KDE verdict:** Real blur exists — X11 atom `_KDE_NET_WM_BLUR_BEHIND_REGION` (KWin only)
  and Wayland `org_kde_kwin_blur`; `ext-background-effect-v1` from Plasma 6.7. **Qt/PySide6
  cannot reach the Wayland ones** without KWindowSystem or native code.
- **SCENE portable:** **True.** Caveats: CPU-side bake mandatory (no `ShaderEffect` on the
  software backend); no `layer.enabled`; llvmpipe ⇒ cap TOKEN to protect FastDAQ; no
  transform-scaled text on the software path.

---

## 9. Open items / what I did **not** verify

1. **wayland.app's compositor-support matrix** for `kde-blur` — the page renders a table I
   could not read reliably; the summary I got (18 compositors incl. Mutter/Weston/Sway) is
   almost certainly a mis-parse of the tracked-compositor list. **Only KWin is verified.**
   Do not cite that matrix.
2. **xfwm4 / other X11 compositors** honoring the KDE atom — unverified, assumed no.
3. **Item layers (`layer.enabled`) on the software adaptation** — Qt's docs do not say;
   avoid.
4. **Wayland absolute window positioning** (xdg-shell has none) — stated from general
   knowledge, not re-verified this session; matters for detached windows/popovers.
5. **Linux high-contrast detection** from Qt — no mechanism identified; open design item.
6. **Licensing**, if we ever vendor protocol XML: `blur.xml` (plasma-wayland-protocols) is
   **LGPL-2.1-or-later** [W1]; `wayland-protocols` (where `ext-background-effect-v1` lives)
   is MIT repo-wide — **not re-verified this session**. KWindowSystem is LGPL (KF6) — a
   dependency decision, not a copy-paste one.

**Re-check trigger for this note:** when a target distro ships **GNOME ≥ 51** *and* Qt/PySide6
gains a public API (or `QNativeInterface::QWaylandApplication` binding) for
`ext-background-effect-v1`. Both must be true before the Linux `WINDOW` row changes.

---

## Sources

**Distros**
- [U1] Ubuntu 26.04 LTS release notes — summary for LTS users (GNOME 50; *"The Ubuntu Desktop session now runs only on the Wayland back end, because GNOME Shell can no longer run as an X.org session."*): https://documentation.ubuntu.com/release-notes/26.04/summary-for-lts-users/
- [R1] Red Hat Enterprise Linux 10 Release Notes — *Removed features* (X.org server removed; Wayland default; XWayland only): https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/10/html/10.0_release_notes/removed-features
- [R2] RHEL 10 release coverage — GNOME 47 (secondary, version claim only): https://blog.desdelinux.net/en/Rheel-10-arrives-with-Gnome-47--Linux-6-and-12--initial-support-for-RSI-and-more./
- [R3] Red Hat — *RHEL 10 plans for Wayland and Xorg server*: https://www.redhat.com/en/blog/rhel-10-plans-wayland-and-xorg-server
- [K1] Kubuntu 26.04 LTS release notes (Plasma 6.6, Qt 6.10.2, KF 6.24; `plasma-session-x11` not installed by default / unsupported): https://kubuntu.org/news/kubuntu-26-04-release-notes/

**X11**
- [X1] KWin blur plugin source (atom name, `XCB_ATOM_CARDINAL`/32, x/y/w/h quadruples, `size()==0||1 ⇒ whole window`; `backgroundEffectManager()->addBlurCapability()`): https://invent.kde.org/plasma/kwin/-/raw/master/src/plugins/blur/blur.cpp
- [X2] picom(1) man page (`blur-background`, `blur-background-exclude` — compositor-config-driven blur): https://man.archlinux.org/man/picom.1.en
- [X3] Enabling backdrop blur in a desktop application (KDE + Deepin atoms) — secondary: https://notes.yvt.jp/Desktop-Apps/Enabling-Backdrop-Blur/
- [X4] KWindowSystem `KWindowEffects::enableBlurBehind()` — xcb implementation + Wayland caveat (needs plasma-integration platform theme): https://github.com/KDE/kwindowsystem/blob/master/src/platforms/xcb/kwindoweffects.cpp , https://api.kde.org/frameworks/kwindowsystem/html/kwindoweffects_8cpp_source.html

**Wayland protocols**
- [W1] `plasma-wayland-protocols/src/protocols/blur.xml` (interfaces, requests, LGPL-2.1-or-later, © 2015 Gräßlin/Martin): https://github.com/KDE/plasma-wayland-protocols/blob/master/src/protocols/blur.xml
- [W2] KDE blur protocol reference (v1, unstable): https://wayland.app/protocols/kde-blur *(support matrix deliberately not cited — see §9.1)*
- [W3] Phoronix — *Wayland ext-background-effect-v1 Merged For Background Blur Feature* (2025-05-27; Xaver Hugl; based on org_kde_kwin_blur): https://www.phoronix.com/news/Wayland-Background-Effect
- [W4] `ext-background-effect-v1` protocol reference: https://wayland.app/protocols/ext-background-effect-v1
- [W5] KWin MR !4890 — *wayland: support ext-background-effect-v1*: https://invent.kde.org/plasma/kwin/-/merge_requests/4890
- [W6] VLC MR !3835 — *use KWindowEffects::enableBlurBehind() and enable blur in compositor_wayland* (evidence that apps need KWindowSystem for this): https://code.videolan.org/videolan/vlc/-/merge_requests/3835

**GNOME**
- [G1] GNOME/mutter issue #3023 — *Background blur frosted glass effect API for toolkits and applications* (OPEN; maintainers point to finalizing the Wayland protocol + implementing in Mutter): https://gitlab.gnome.org/GNOME/mutter/-/work_items/3023
- [G2] Phoronix — *GNOME Lands ext-background-effect-v1 Support For Background Blur Effect* (2026-07-04; GNOME 51; author Kristof Imerir; notes Plasma 6.7 added it earlier): https://www.phoronix.com/news/GNOME-Mutter-Background-Blur
- [G3] GNOME/mutter MR !5071 — *wayland: Add ext-background-effect-v1 blur support* (client requests effect for its own surfaces; Mutter retains rendering + policy): https://gitlab.gnome.org/GNOME/mutter/-/merge_requests/5071

**Qt / PySide6**
- [Q1] Qt for Python — *Missing Bindings* wiki (`QNativeInterface.QWaylandApplication`, `QNativeInterface.QX11Application` NOT exposed in PySide6): https://wiki.qt.io/Qt_for_Python_Missing_Bindings
- [Q2] Qt 6 — RHI Window Example (*"platform-specific defaults are used: Direct 3D 11 on Windows, OpenGL on Linux, Metal on macOS/iOS"*): https://doc.qt.io/qt-6/qtgui-rhiwindow-example.html
- [Q3] Qt 6 — *Scene Graph Adaptations* (`QSG_RHI_BACKEND`, `QT_QUICK_BACKEND`, `QQuickWindow::setSceneGraphBackend()`; RHI default since 6.0): https://doc.qt.io/qt-6/qtquick-visualcanvas-adaptations.html
- [Q4] Qt 6 — `QQuickWindow` (`setDefaultAlphaBuffer()` must be set *before creating the first QQuickWindow*; `color` = clear color): https://doc.qt.io/qt-6/qquickwindow.html
- [Q5] Qt 6 — *Qt Quick Software Adaptation* (ShaderEffect "cannot be rendered"; particles impossible; software text does not scale well; fractional-DPI partial updates): https://doc.qt.io/qt-6/qtquick-visualcanvas-adaptations-software.html
- [Q6] Qt Wiki — *MesaLlvmpipe* / Qt forum "Running on a software rasterizer (LLVMpipe), expect limited performance": https://wiki.qt.io/MesaLlvmpipe , https://forum.qt.io/topic/107321
- [Q7] Qt Application Manager — *Troubleshooting* (`QT_QUICK_BACKEND=software` only if no explicit OpenGL/shader features; `QSG_RENDER_LOOP=basic` for software rasterizers; `QSG_INFO=1` + `QT_LOGGING_RULES=qt.qpa.gl=true` to verify): https://doc.qt.io/QtApplicationManager/troubleshoot.html
- [Q8] Qt Quick over VNC / remote X — VNC platform plugin does not render OpenGL content; software renderer guidance: https://doc.qt.io/QtVNCServer/ , https://forum.qt.io/topic/113906/cannot-start-qml-apps-from-remote-desktop-connection
