# Fenrir — the kill floor: ten ways the glass dies mid-scan

Glass Council round 2, 2026-07-13 night. Fenrir, the Nemesis (NorthStar, on
loan). My charter says I attack the *running* thing and paper is Loki's lane —
the council has ordered a paper hunt anyway, so I hold myself to the same
standard on paper: **every break below names its mechanism** (the exact
Win32 message, Qt event, or compositor behavior that fires it), grounded in
the other lanes' cited ground truth (Thor's flush paths, Ratatoskr's attribute
lifetimes, Ymir's environment matrix, Frigg's prior-art bug tail, Brokkr's
candidate specs). No vibes, no "might". If a break here cannot be reproduced
on the bench by following its trigger line, strike it from the record.

project_tct is READ-ONLY for me; this file is the only deliverable.

---

## 1. The hazard, precisely

**An operator mid-HV-scan with an unreadable or flickering cockpit.** Bias at
hundreds of volts, stage in motion, a scan that costs hours to restart. The
operator does not need beauty at that moment; they need to *see*.

What the existing design law already saves, in every candidate, in every
scenario below: **Z3/Z4/Z5 are opaque by frozen contract** (Baldr's Z-ladder,
Völundr's G1–G5, the `SAFETY_TOKENS` lock). Plots, camera, HV readouts, the
STOP/Abort/DangerGate surfaces cannot go glass and therefore cannot go white
*by material failure*. That law is the single best safety property on the
table and no candidate may weaken it.

So the honest hazard taxonomy is:

| Class | What actually dies | Operator impact |
|---|---|---|
| **H1 — chrome whiteout** | Z0 canvas + Z1 chrome (dock tab strips, area title bars, rail, status-strip frame) go white/plate/desktop-see-through | Navigation dies: 13 panels, white tab bars, white-on-white labels. Operator can still see the plot in front of them but cannot find the bias panel. Panic multiplier. |
| **H2 — pane whiteout** | Z2 `glassPane` opt-ins go white/plate | Working surfaces (whatever was opted in) unreadable. Proportional to opt-in count. |
| **H3 — whole-window white** | Stale-backing white box (Frigg S26, Ymir W4): a white rectangle **over everything, content included**, until a resize/minimize forces repaint | The one true unreadable-screen case. Covers readouts. This is the class that must be unreachable. |
| **H4 — see-through cockpit** | DWM attrs lost while alpha canvas persists: desktop composites through the holes (Ratatoskr §1.3) | Email popups and wallpaper visible *through* the cockpit chrome mid-scan. Not white — worse: moving, distracting, uncanny. |
| **H5 — flicker/storm** | Repaint storms, material blink during drags, tier flapping, per-resize-step flashes | Draws the eye off the measurement; on the CPU-bound laptop, contends with acquisition timing. |
| **H6 — acquisition contention** | Material machinery (re-blur jobs, restyle fan-outs, probe toggles) stealing CPU/GPU from the 30 Hz acquisition path mid-scan | Not a pixel failure at all — dropped frames, timing jitter. The laptop already demonstrably degrades under CPU contention (test-lane policy exists because of it). |

"Dies" below means: the candidate produces H1–H4 with no self-detection, or
H5/H6 at a magnitude that perturbs a running scan.

## 2. The accused

- **A — "One Sheet of Glass"** (Brokkr): per-pixel alpha punched through the
  whole QtAds stack to window-level DWM material. Zone registry, ADS
  stylesheet eviction, path-B raster flush everywhere glass is wanted.
- **B — split-horizon** (Brokkr): classic shell = window-level DWM at
  margins/seams only + pre-blended token panels; QML shell = transparent
  QQuickWindow, scenegraph alpha, DWM behind the scene. One token contract.
  Where the sub-shell matters I write **B-classic** / **B-QML**.
- **C — "Forged Glass"** (Brokkr): app-owned raster frost — wallpaper read,
  blurred once in a worker, painted as position-tracked pixmap slices. No DWM
  dependency.
- **baked — in-scene baked-blur** (Baldr §4.1, C's scenegraph cousin): the
  app-owned Ambient layer pre-blurred into GPU textures; QML `GlassPane`
  samples the texture at its scene position. Deterministic, compositor-free.

## 3. The ten kill scenarios

Format per scenario: **trigger mechanism → who dies → what the operator
sees → the detection + recovery that MUST exist** (if it doesn't exist in the
winning design, the candidate ships broken).

### K1 — Resize storm during acquisition

**Mechanism.** Operator drags the window edge or a splitter while the scan
runs. Per resize step: backing store realloc; on an alpha surface every dirty
region pre-clears to `Qt::transparent` before widgets repaint (Thor §1.3), so
between clear and paint the region is a 100 % alpha hole; DWM composites
material — or the fallback plate — into it for however long the paint lags.
Interactive resize is also the documented trigger/healer of the Qt 6.10.x
stale-backing white box (Frigg S26, Ymir E2). Simultaneously the 30 Hz plot
repaints contend for the same paint budget.

**Who dies.** **A, hardest.** A's glass area is the whole declared zone grid —
every tab strip, gutter, and opted-in pane flashes plate/material per resize
step; on a light-flagged or effects-off machine each flash is *white* (H1+H5).
If any RTT child is live (see §4), the window is on path D where translucent
resize behavior is officially undefined — black rects are the historical
artifact (Thor §1.2-D). **B-classic** flashes only at margins — cosmetic.
**B-QML** re-renders whole frames atomically (scenegraph) but pays swapchain
resize; a frame of plate can slip between swapchain recreate and first scene
present. **C/baked** repaint synchronously from local pixels/textures —
survive clean; C's only exposure is one-frame slice-offset lag ("frost
slides").

**Operator sees.** A: strobing white/plate lattice across the cockpit chrome
for the duration of the drag, mid-scan. B-classic: margin shimmer. C/baked:
nothing notable.

**MUST exist.** (a) Interactive-resize guard: no attribute churn, no probe
toggles, no tier re-evaluation while `isResizing`/moveResize loop is active —
defer to release. (b) Harness INV-C (Týr §2.1) extended with a scripted resize
burst: no frame's canvas luminance may leave the endpoint envelope. (c) For A
specifically: there is no mitigation for the pre-clear flash except *reducing
the alpha area* — which is conceding to B.

### K2 — Monitor hot-plug / DPI change mid-run

**Mechanism.** Operator plugs the bench projector / docks the laptop.
`WM_DISPLAYCHANGE` + `WM_DPICHANGED`; Qt migrates the window
(`screenChanged`), recreates surfaces at the new scale factor, and on some
paths recreates the native window entirely (→ K9). WinUI itself shipped a
crash dragging Mica windows between monitors (Frigg S42). The stale-backing
white box (H3) is precisely a surface-recreation bug.

**Who dies.** **A** — biggest alpha area exposed to the white box + zone
registry rects go stale in physical pixels + possible full attr loss via K9.
**C** — the blurred pixmaps are per-screen-resolution and the slice offset
math is DPI-dependent; until regeneration, frost paints at the wrong scale or
the source rect runs off the pixmap edge. If the paint hook has no underlay,
an out-of-bounds slice paints *nothing* → whatever the widget beneath shows.
**baked** — texture DPR mismatch = blur renders soft/misaligned (cosmetic).
**B-classic** — margins only; **B-QML** — swapchain recreate, one plate frame.

**Operator sees.** A: white rectangle over part or all of the cockpit until
someone resizes it — mid-scan, hands off the mouse, it just sits there white
(H3 is *sticky*). C: glass visibly slides or doubles for a beat.

**MUST exist.** (a) `screenChanged`/`WM_DPICHANGED` handler: re-assert attrs
(20 then 38 + ExtendFrame), issue a real resize jiggle (±1 px, restore) — the
documented heal for W4 — then re-run pixel probe L6 (Ymir). (b) C: per-screen
pixmap cache keyed by (screen, DPR); paint the R1 pre-blend hex *underneath
every frost blit always*, so a missing/stale slice degrades to token glass,
never to undefined. (c) Probe coordinates always physical px via the target
screen's `devicePixelRatio()` (Ymir E10).

### K3 — GPU driver reset (TDR)

**Mechanism.** Driver hangs > 2 s → Windows TDR: device removed
(`DXGI_ERROR_DEVICE_REMOVED`), every GPU context and GPU-resident resource on
the machine destroyed, DWM re-initializes (system-wide black flash), then
everything re-creates. Mid-scan on a bench machine driving GL plots + camera
preview, TDR is not exotic — a flaky camera driver or a heavy Ollama job on
the same GPU can trigger it.

**Who dies.** **baked, deadest** — the pre-blurred textures are GPU-resident;
after device loss the scene graph can only restore them if a CPU-side source
(QImage / re-runnable provider) was *retained*. If the pipeline dropped the
CPU copy to save RAM, every GlassPane samples a dead texture: white, black, or
garbage — inside a transparent QQuickWindow that means the DWM plate shows
where panes were (H2, possibly H1 if chrome is baked too). **B-QML** — Qt's
RHI device-loss recovery re-inits the scenegraph, but the window is
`color: transparent`: between device loss and first re-rendered frame, DWM
composites the bare plate — whole-window white/dark flash, potentially
seconds on a slow re-init. **A** — if a GL island is live (path D), the
composeAndFlush context dies; pyqtgraph's GLViewWidget does not handle context
loss — the island can stay black until recreated, and the window's
translucent-over-RHI recovery is exactly the artifact zone Brokkr's go/no-go
gate fears. **C — immune**: QPixmaps on the raster engine are system memory;
QPainter needs no GPU. C's whole bet, cashed.

**Operator sees.** System-wide black blink (unavoidable, OS-level), then:
baked/B-QML: white or hollow panes until re-init; A: black GL island + margin
artifacts; C: cockpit back exactly as it was.

**MUST exist.** (a) Device-loss hook (QQuickWindow::sceneGraphError /
RHI device-lost callback / `WM_DISPLAYCHANGE` fallback) → **instant tier drop
to T1** (opaque tokens) before attempting re-init, restore only after L5+L6
re-pass (Ymir I4: down instant, up verified). (b) baked: **retention law** —
the CPU-side blurred source is never freed while any pane samples it; write it
into the U1.5 kit spec as a MUST. (c) The R1-underlay law from K2 applies
identically: a dead texture must reveal pre-blend hex, not window transparency.

### K4 — Wallpaper change while frost slices are cached

**Mechanism.** `WM_SETTINGCHANGE` (SPI_SETDESKWALLPAPER). Windows slideshow
wallpapers fire this **every 1–30 minutes, forever**. C's cached blur is now
of the wrong image; its re-derivation pipeline (downscale→blur→upscale, two
strengths, ~100–300 ms + ~64 MB churn) wants to run — in the acquisition
process, on the CPU-bound i7-10510U, mid-scan.

**Who dies.** **C, deadest — and it dies two ways at once.** Way 1 (visual):
stale frost — the glass shows a desktop that is no longer there. Readable,
but the illusion is broken exactly at its load-bearing claim (determinism ≙
honesty; a frost of a stale wallpaper is a *lie with tells*, Brokkr weakness
C-1 sharpened). Way 2 (H6): if it re-blurs immediately, a slideshow wallpaper
turns every scan into periodic 300 ms CPU spikes + allocation storms in the
same process that runs the DAQ loop. The observed pytest-timeout contention
on this laptop says H6 is not hypothetical. **A/B**: immune — Mica re-samples
wallpaper OS-side, free, outside our process. **baked**: immune by design —
Baldr's Ambient is app-owned; the wallpaper was never the source. (If anyone
"improves" baked by sourcing the wallpaper, they inherit this kill. Refuse.)

**Operator sees.** C without guard: nothing wrong on screen — the scan data
quietly jitters (the worst kind of failure in a lab). C with naive guard:
frost visibly swaps mid-scan.

**MUST exist.** (a) **Scan-aware deferral**: wallpaper-change marks the cache
stale; re-blur runs only when the acquisition state machine is idle. Stale
frost mid-scan is the *correct* behavior — log it, keep it. (b) Rate-limit:
one re-blur per N minutes regardless. (c) Atomic pixmap swap (build fully in
worker, swap pointer on the GUI thread) — no torn frost. (d) The blur worker
runs at below-normal priority.

### K5 — Theme toggle mid-scan

**Mechanism.** Operator (or a well-meaning colleague at the bench) flips
dark/light while the scan runs. Three coupled machines fire: (1) full QSS
rebuild + repolish fan-out to every top-level and its subtree (13 panels);
(2) attr 20 must be re-asserted per HWND — main window, theme editor,
settings, every `CFloatingDockContainer`, every `_DetachedWindow` — *in the
same batch as* attr 38, or Mica flips to the wrong variant on the missed
windows (Ratatoskr §2: tonight's WHITE, on demand); (3) Qt's own palette
heuristic may re-write attr 20 *after* us on some Qt versions
(last-writer-wins, Ratatoskr §2.3).

**Who dies.** **A** — the restyle storm re-emits rgba for every selector in
every zone's paint chain; one selector missed in the new theme's QSS = a
sealed zone or an open hole, discovered visually. Plus H5: repolishing 13
panels mid-acquisition is a repaint storm by construction. **C** — the theme
tint is *pre-multiplied into the cached pixmaps*: a theme toggle demands a
full re-blur (both strengths), hitting the K4 CPU tax on the spot; until it
completes, frost is tinted for the wrong theme (readable, wrong). **B-QML**
survives elegantly — Theme singleton NOTIFY rebinds scenegraph colors in one
frame, one window, one attr-20 re-assert. **B-classic** pays the QSS rebuild
like A but with material only at margins, a missed selector is cosmetic.

**Operator sees.** A: multi-hundred-ms restyle flicker; any window whose
attr 20 re-assert lost the race renders its material white-variant — a
half-dark, half-white cockpit (partial H1). C: glass wearing last theme's
tint for ~300 ms plus a CPU spike.

**MUST exist.** (a) Attr-20-with-38 batching per HWND, ordered 20 → 38
(WPF prior art: dark flag before backdrop or you get the white flash,
Frigg S21), fan-out enumerates *all* top-levels from one registry. (b) A
post-toggle re-assert scheduled one event-loop turn later to beat Qt's
palette heuristic, then L6 luminance probe. (c) C: theme-toggle re-blur is
exempt from K4's scan deferral only as the *single* pre-blend-first swap:
drop panes to R1 tokens instantly, frost catches up when ready. (d) Honest
question for Kaya: should theme toggle be soft-locked during an active scan
like other non-essential restyles? It is the cheapest storm to simply not
have.

### K6 — RDP connect MID-session

**Mechanism.** Scan started at the console; operator RDPs in from home to
check on it (the documented lab workflow — Ymir E5 calls it routine). Session
transitions remote: DWM keeps compositing but **materials are policy-replaced
by their solid fallback plate** (Frigg §1, Ratatoskr §4); the plate's color is
chosen by attr 20 — light = `#F3F3F3`, WHITE. Also: RDP renegotiates display
geometry → K2's surface recreation fires too. And the console session locks —
pixel probes of a locked session return garbage (Ymir L6 caveat).

**Who dies.** **A, catastrophically.** Every declared glass zone across the
cockpit — tab strips, gutters, title bars, opted-in panes — flips to the
plate *simultaneously*: with attr 20 correctly dark, a flat `#202020` lattice
under 0.82 alpha canvas (degraded, readable); with attr 20 missing on any
window, a **white lattice over the whole cockpit, mid-HV-scan, viewed from
home** (H1 at maximum area). Worse: Ymir's scan-freeze policy *queues* tier
changes mid-scan — if the queue rule is applied naively, the alpha canvas
keeps blending against the plate for the entire remaining scan. **B-QML**:
whole scene composites over the plate — canvas regions wash out; single
window, single detection, moderate. **B-classic**: plate at margins; the
cockpit core never depended on the material — designed for exactly this.
**C**: compositor not consulted; identical frost over RDP — C's headline win,
paid for in WAN bandwidth (frost gradients compress badly; cosmetic, slow,
never unreadable). **baked**: renders locally, encodes like any pixels;
survives.

**Operator sees.** A worst case: they connect from home *because the scan
matters* and are greeted by a white grid where the cockpit chrome was.

**MUST exist.** (a) `WTSRegisterSessionNotification` →
`WM_WTSSESSION_CHANGE` (`WTS_REMOTE_CONNECT`) → **immediate downgrade to T1**.
(b) **Amend the scan-freeze rule**: Ymir's "queue tier changes mid-scan" must
carve out *all* material→plate downgrades as W1-class (apply instantly, as
the single opaque-QSS swap, probe toggles deferred) — not only the white
case. Downgrades are never queued; only upgrades wait for scan end. (c) L6
must not run while `WTS_SESSION_LOCK` is active (already in Ymir; keep it).
(d) Restore to T0 on console reconnect only after full L5+L6 re-pass.

### K7 — Sleep / resume

**Mechanism.** Lid close or timeout mid-long-scan (or overnight scan with
morning resume). Resume fires the cluster: `WM_POWERBROADCAST`
(`PBT_APMRESUMEAUTOMATIC`), monitors re-enumerate (phantom hot-plug → K2
fires even with no hardware change), GPU power-cycles (mild K3), and — the
sleeper — the laptop resumes **on battery** → battery saver ON → transparency
effects OFF system-wide → all materials → plate (Ymir E7).

**Who dies.** **A** — takes K2 + K3 + E7 in one event burst: stale-backing
white boxes post-resume, possible attr loss, and even after clean recovery
the plate everywhere because the charger is out. **baked** — GPU textures may
not survive the power cycle on some drivers: K3's retention law is re-tested
on every single resume. **B-classic** degrades to margins-plate (fine).
**C** — pixmaps in system RAM survive sleep untouched; one offset recompute
if monitors shuffled; strongest again.

**Operator sees.** A: open the lid on a running scan → white boxes and/or
plate lattice until a resize + charger plug + probe cycle. The 2am operator
Ymir designs for meets this exact screen.

**MUST exist.** (a) Resume handler = cold re-derive: treat resume as
first-expose — full ladder L2–L6 re-run after the first `QExposeEvent`
+2 frames, never trust pre-sleep tier (session-hygiene rule 1, applied to
pixels — Ymir already states it; make resume an explicit trigger row).
(b) Resize jiggle post-resume before probing (heals W4). (c) Battery-saver
rung L4 re-checked on `PBT_APMPOWERSTATUSCHANGE`, downgrade instant per K6's
amended rule.

### K8 — Window detach/redock (QtAds) while material attached

**Mechanism.** Routine operator gesture in a 13-panel dock cockpit — this is
Tuesday, not an edge case. Detach: ADS re-parents the panel into a new
`CFloatingDockContainer` top-level; during the drag, ADS shows layered
(`WS_EX_LAYERED`) preview overlays — material blinks by mechanism (Thor
§4.5); if the floating container is configured frameless (non-native title),
it lives on **path C (UpdateLayeredWindow)** where DWM materials are
*impossible* (Thor §1.2-C). The new top-level needs its own ExtendFrame +
attr 20 + attr 38 + canvas prep + opacity pin *before first show* or its
first frame is a hole/plate. Redock: re-parent back → the main window's zone
rects churn; **and if the detached panel was the Motor Stage, redocking
brings the GLViewWidget home and flips the whole main window to path D — all
window glass dies, silently, everywhere** (Thor §3.3 discriminator, run in
reverse by an innocent operator). Re-parenting across window boundaries is
also Qt's classic native-window-recreation trigger → K9 fires inside K8.

**Who dies.** **A, deadest of the whole hunt.** One routine gesture chains
five mechanisms: layered drag blink (H5) → frameless-float path C (material
dead on the satellite) → missed first-frame attach (white flash) → zone
registry churn → path-D flip on redock (all glass silently gone, H1 by
absence with no error anywhere). A's entire premise — per-pixel alpha
discipline across the dock stack — is churned by the dock stack's most basic
operation. **B-classic**: floating window gets the existing window-level
fan-out (`apply_window_backdrop_to` pattern); panels opaque; worst case one
satellite's margins misbehave. **B-QML**: no ADS — QML-side docking; a
detached pane is a new QQuickWindow needing the same one-window recipe;
bounded. **C**: new top-level = one new screen-offset tracker; frost paints
correctly on the first frame because it is raster painted, not composited
from behind; drag = moveEvent-driven slice blits. Survives; its risk is an
offset bug reading as "sliding frost" during the drag. **baked**: pane needs
an Ambient instance per window (Baldr's one-per-window rule) — survives if
the kit enforces it, hollow glass if it doesn't.

**Operator sees.** A: material blinks during the drag, the floated panel's
glass is dead or white-flashed on arrival, and after redocking the 3D view
the *entire cockpit's* glass quietly turns to flat alpha-blend mush with no
event, no log, no error.

**MUST exist.** (a) Construction-time attach fan-out for
`CFloatingDockContainer` (extend the `_DetachedWindow` pattern), with native
title bars **forced** (frameless float = path C = never material — make it a
config assertion, not a hope). (b) `WinIdChange` hook (K9) on every ADS
top-level. (c) **The path-D census**: on every dock-layout change, enumerate
visible RTT children per top-level; any window containing one *forfeits
material and re-resolves to token tier for that window, logged* (Thor
constraint 4: state it per window; never average). Without this census, A's
death in K8 is undetectable by any API — S_OK everywhere, glass gone.
(d) Harness scenario: detach → capture → redock → capture → INV-A per
window.

### K9 — HWND recreation (Qt native re-parenting) dropping DWM attrs

**Mechanism.** Qt destroys and recreates the native window on:
`setParent()` across window boundaries (ADS does this constantly — K8),
certain `setWindowFlags` changes, `WA_NativeWindow` toggles, some
screen-migration paths. All per-HWND DWM state — ExtendFrame margins,
attr 20, attr 38 — **dies with the HWND, silently, S_OK-history and all**
(Ratatoskr §1.1). Qt fires exactly one breadcrumb: `QEvent.WinIdChange`.

**Who dies.** **Every DWM candidate (A, B-classic, B-QML) — equally and
totally — if and only if the WinIdChange hook is missing.** The failure mode
is H4, the nastiest visual in the taxonomy: the window still carries
`WA_TranslucentBackground` and its rgba canvas, but nothing sits behind the
alpha anymore — with ExtendFrame also gone the redirection surface alpha
handling reverts, and the holes composite against the frame fill or raw
desktop. The operator's cockpit chrome becomes a literal window onto their
desktop: wallpaper, notification toasts, a YouTube video moving *through*
the tab bars, mid-scan. **C/baked: immune** — no DWM dependency for the
glass itself (a dropped attr 20 flips their *titlebar* light; cosmetic).

**Operator sees.** Desktop bleeding through the cockpit chrome; on a light
desktop, effectively white chrome (H1/H4 hybrid). No error is logged
anywhere because nothing failed — the window is simply new.

**MUST exist.** Non-negotiable rider for any DWM candidate: an event filter
on **every** top-level (main, dialogs, floats, detached) catching
`WinIdChange` → full re-assert in order (ExtendFrame → attr 20 → attr 38 →
canvas prep → opacity pin) → log line (Ymir I5 format) → L6 re-probe
deferred to next expose. Plus a headless test: force `winId()` recreation
(toggle WA_NativeWindow), assert the recorded DWM call sequence repeats
(Týr's rung-2 seams make this cheap). Every lane flagged this; I rank it: it
is the difference between A/B being shippable at all and not.

### K10 — Low-VRAM eviction of baked textures

**Mechanism.** The QML-horizon cockpit holds screen-sized blurred textures
(2 × ~32 MB at 4K) resident next to GL plot buffers, camera streams, and the
compositor's own load. On the iGPU (UHD 620, shared memory) "VRAM" pressure
is system-RAM pressure — demotion and hitching; on a discrete low-VRAM card,
真 eviction: the scene graph's texture handle goes dead or is dropped by the
driver. Qt re-uploads only if a CPU-side source still exists (same law as
K3, chronic instead of acute).

**Who dies.** **baked** — and *how* it dies is a pure design choice made in
advance: if the GlassPane's visual stack is [blurred texture] with
transparency behind it, a dead texture reveals the transparent window →
DWM plate → **white pane** (H2). If the stack is [R1 pre-blend rect] under
[texture], a dead texture reveals… the ratified fallback look. Same failure,
one is a hazard, one is a shrug. **C**: raster pixmaps page like any process
memory — hitch, never corruption; its low-memory gate (skip pipeline
< 200 MB free) handles allocation-time; runtime is the OS's paging problem.
**A/B**: no app-side material textures; DWM manages its own (an OS problem
that manifests as system-wide, not app-white).

**Operator sees.** baked without the underlay law: panes flash white/hollow
under memory pressure — precisely when the machine is busiest, i.e. mid-scan
with the camera running. With the law: glass quietly loses its frost and
becomes token glass; nobody's scan is endangered.

**MUST exist.** (a) **The underlay law, promoted to contract**: every glass
surface in every candidate paints its R1 pre-blend *first*, frost/material
effects strictly above — eviction, device loss, stale cache, missing texture
all degrade to the ratified fallback by construction. (One rule retires the
worst outcome of K2, K3, K7, K10 simultaneously. It belongs next to G1–G5 in
Völundr's frozen set.) (b) CPU-side source retention (K3). (c) baked assets
sized to the *window*, not the desktop, where feasible — 4K-desktop textures
for a 1600 px window is self-inflicted pressure.

---

## 4. The landmine that is not on the list: the GL-island path-D flip

Not one of my ten scenarios, because it needs no environmental trigger at
all — Thor §0.2 already proved it: the Motor Stage hosts a `GLViewWidget`
one segment-click away; the first click flips the entire main window to
path D and **all window-level DWM glass dies silently until process
restart**. Every scenario above that touches A or B-classic must be read
with this behind it: on the main cockpit window, *the DWM material is
already mutually exclusive with a feature the operator uses*. K8's redock
variant is merely this landmine rearmed dynamically. Any candidate that
keeps DWM glass on the main window must ship the path-D census (K8-c) or it
is selling glass that a single click disables — and no one will file the bug,
because nothing errors.

## 5. Ranked kill-list — which scenario kills which candidate deadest

| Rank | Scenario | Kills | Why it is the deadest |
|---|---|---|---|
| **1** | **K8 detach/redock (+K9 inside it)** | **A — fatal** | A routine, daily operator gesture chains five failure mechanisms (layered drag blink, frameless-float path C, first-frame attach race, HWND recreation, path-D flip on redock). Silent — no HRESULT, no log — and it disables glass window-wide. A's core discipline is churned by the dock stack's most basic operation. This is not an edge case; it is the product being used. |
| **2** | **K6 RDP mid-session** | **A — fatal in the lab's own workflow** | The documented remote-check-on-the-scan workflow turns A's entire zone grid into the fallback plate at once; one missed attr 20 makes it a white lattice viewed from home, mid-HV-scan. Ymir's scan-freeze queue, read naively, *preserves* the broken state for the scan's remainder. |
| **3** | **K9 HWND recreation** | **A + B-classic + B-QML — fatal without the rider** | The only H4 producer: desktop bleeding through the cockpit. Zero-error, zero-log. The `WinIdChange` re-assert rider is the single cheapest life-saver in the whole council output; without it no DWM candidate may ship. |
| **4** | **K3 TDR (+K7 resume as its chronic twin)** | **baked — fatal without retention+underlay; B-QML — severe** | Device loss over a transparent QQuickWindow shows the bare plate for the whole re-init; unretained baked textures leave hollow/white panes. C walks away untouched — this scenario is C's entire justification, cashed. |
| **5** | **K4 wallpaper churn** | **C — its honesty and its DAQ purity, both** | Slideshow wallpapers make C choose forever between stale frost (a lie with tells) and periodic 300 ms CPU spikes inside the acquisition process. The only kill on the list whose worst symptom is invisible: scan-timing jitter, not pixels. |
| **6** | **K1 resize storm** | **A — severe (H5), B-QML — moderate** | Per-resize-step alpha pre-clear flashes across A's whole zone grid during acquisition; unfixable except by shrinking the alpha area, which is B. |
| **7** | **K2 monitor/DPI** | **A — severe (sticky H3 white box), C — moderate (sliding frost)** | The stale-backing white box is the one failure that covers *content*; it stays until a resize the mid-scan operator won't perform. Jiggle+probe rider mandatory. |
| **8** | **K7 sleep/resume** | **A — severe (K2+K3+battery-saver in one burst)** | The overnight-scan morning screen. Resume-on-battery lands on the plate even after perfect recovery. |
| **9** | **K5 theme toggle mid-scan** | **A — moderate/severe (restyle storm + attr-20 race), C — moderate (full re-blur)** | Half-dark-half-white cockpit if one HWND loses the attr-20 race; C pays a K4-class CPU spike per toggle. |
| **10** | **K10 low-VRAM** | **baked — moderate, fatal only without the underlay law** | A design-time one-liner decides whether eviction is a white pane or a shrug. |

**Score by candidate:** A takes fatal or severe damage in **nine of ten**
scenarios — every one of its wounds is in the alpha area it insists on
maximizing. baked dies twice (K3, K10) to the *same* missing rule and is
fully healed by retention + underlay. C dies once (K4), to a deferral rule,
and is otherwise the tank of the field — but its kill is the sneakiest
(H6, invisible). B-classic is wounded nowhere fatally: every attack that
whitens glass area finds almost none, and what it finds is not load-bearing.
B-QML inherits moderate versions of the compositor kills (K1, K3, K6) on a
single-window, single-recipe surface — bounded, testable, but real; Brokkr's
own "postponed proof" weakness stands.

## 6. Survivor verdict + the mandatory rider set

**Survivor: Candidate B-classic today, with C's raster frost as the optional
deterministic upgrade tier and baked (with the two laws) as the QML-horizon
frost.** Not because B is prettiest — because every scenario that turns a
cockpit white attacks *alpha area under compositor control*, and B is the
only candidate whose classic shell keeps that area small, non-load-bearing,
and instantly collapsible to opaque tokens. A is architecturally the maximum
attack surface for all ten scenarios at once; it should be recorded as
killed on paper before it kills a scan in the lab.

No survivor ships without these riders — each one retired at least one kill
above:

1. **WinIdChange full re-assert** on every top-level (K8, K9) + headless
   recreation test (Týr rung 2).
2. **Attr 20 batched with attr 38**, ordered 20→38, fan-out from one
   registry, post-toggle re-assert beating Qt's heuristic (K5, K6, and
   tonight's WHITE).
3. **Downgrades are never queued** — amend the scan-freeze policy: all
   material→plate/fallback downgrades apply instantly as one opaque-QSS
   swap; only upgrades wait for scan-idle + 60 s hysteresis + L5/L6 (K6, K7).
4. **The underlay law (contract-grade)**: R1 pre-blend paints beneath every
   frost/material effect in every candidate; anything missing degrades to
   the ratified fallback, never to transparency (K2, K3, K7, K10). File it
   beside Völundr's G1–G5.
5. **Path-D census per dock-layout change**: any top-level containing a
   visible RTT child forfeits material, per window, logged (K8, §4).
6. **Event spine**: WTS session + power broadcast + setting-change +
   DPI/screen-change handlers all re-run Ymir's ladder; resume = cold
   re-derive (K2, K6, K7).
7. **Scan-aware deferral for expensive regeneration** (C re-blur, baked
   re-bake): stale visuals mid-scan are correct; CPU spikes mid-scan are
   the failure (K4, K5).
8. **Harness scenarios**: resize burst, detach/redock round-trip,
   theme-toggle burst, first-show/minimize-restore — INV-A/C/D asserted per
   frame class (K1, K5, K8; Frigg §6's two white-bug classes both need
   non-steady-state frames).

The wolf's report: the pack tested every throat. A's is torn out; B walks
with riders; C limps once and only where the desktop lies to it; baked lives
iff two sentences make it into the kit spec. The binding holds only if the
riders are law, not lore.

---

```json
{
  "agent": "fenrir",
  "status": "done",
  "file_written": "docs/design/glass_council/fenrir.md",
  "top_kills": [
    "K8 QtAds detach/redock (+HWND recreation): kills Candidate A dead — a routine gesture chains layered-drag blink, frameless-float path C, attach race, attr loss, and the path-D flip; silent, window-wide, no error anywhere.",
    "K6 RDP connect mid-scan: A's whole zone grid flips to the DWM fallback plate at once — white lattice mid-HV-scan if attr 20 misses one HWND; naive scan-freeze queuing preserves the broken state to scan end.",
    "K3 TDR + K10 VRAM eviction: kill baked (hollow/white panes over a transparent window) unless CPU-source retention + the R1-underlay law are contract; K4 wallpaper churn kills C's determinism via stale frost or mid-scan re-blur CPU spikes."
  ],
  "survivor": "B-classic: DWM confined to non-load-bearing margins, panels opaque tokens; with the 8-rider set it cannot go unreadable. C/baked as frost tiers."
}
```
