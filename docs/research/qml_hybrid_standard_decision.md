# Should the QML-hybrid shell be RATIFIED as the STANDARD TCT GUI?

- **Date:** 2026-07-13
- **Question (Kaya, via Adam):** Ratify a QML-hybrid shell as *the standard* for
  the TCT GUI now, or not? Adam's prelim: *"Zielbild ja, Standard erst nach
  Tech-Probe."* Stress-test that; disagree where the evidence says so.
- **Stack:** PySide6 6.11.x, Qt 6.11, CPython 3.10 (64-bit), Windows 11.
  Deployment target: lab laptop = CPU-bound **i7-10510U + Intel iGPU**, also the
  bench PC, **possibly over RDP**. RHI default on Windows = D3D11; the slice pins
  the whole process to **OpenGL** (Motor-Stage `GLViewWidget` coexistence).
- **What already exists (read first):** branch `qml-hybrid-slice1` /
  worktree `.claude/worktrees/slice1-ui` is **not a spike** — it is a
  Mary-reviewed, headless-tested, **opt-in (`TCT_QML_SHELL=1`)** QML chrome shell
  (`gui/qml/Shell.qml`, `gui/qml_shell.py`, `gui/qml_theme.py` Theme singleton,
  `gui/scope_viewmodel.py`) that **coexists with the classic QWidget shell** and
  falls back to it on any QML load error. Layer-contract + GUI-watchdog tests
  enforce the 3-layer law. Prior analysis: `docs/research/qml_hybrid_architecture.md`
  (composition), `apple_vibrancy_qt_feasibility.md` (blur), `cockpit_design_sota.md`.
- **Confidence:** **official docs** for the load-bearing rendering facts (Qt doc
  pages); engineering judgment (flagged) for the verdict and probe thresholds.

---

## Verdict — PROBE-FIRST, but sharpen the ratification target (agree-and-refine)

**Do not ratify-now; do not drop it.** Adam is right that a standard cannot be
ratified on evidence that *structurally excludes the deciding variables* — the
entire test story runs on the **offscreen software backend**, which by
construction cannot exercise real-GPU compositing on the Intel iGPU, the
OpenGL/`GLViewWidget` coexistence, detach GPU-context rebuild, or the RDP path.
But "probe-first" is too vague. Two refinements the evidence forces:

1. **Split the decision "standard" conflates.** "QML **shell/chrome** as the
   standard navigation surface" is a small, reversible commitment (one
   `QQuickWidget` island, one env-var fallback). "QML as the standard for
   **panels/controls**" is where the regret lives. Ratify the *boundary*, not a
   blanket direction: **QWidgets stay standard for all 13 panels and every
   safety-critical control; QML is standard only for the shell chrome + motion
   ornaments.** Explicitly **reject full per-panel QML migration.** This is
   exactly what the current slice already embodies, so ratifying the boundary is
   nearly free — and it's a firmer answer than "probe first."

2. **The visionOS "very fluent / glassmorphism" aspiration is partly
   incompatible with the deployment target — cap it now.** Real backdrop-blur
   (`MultiEffect`/`ShaderEffect`) at 60 fps is not realistic on a CPU-bound iGPU
   and **does not render at all under the software backend** (headless *and*
   RDP). The slice already made the correct call: flat pre-blended color-mix
   tokens, **no `MultiEffect`**. Ship the visionOS *look* (surface ladder,
   hairlines, pill shapes, restrained motion) — not literal live glass. Apple
   itself retreated from aggressive translucency (vibrancy note §1). Motion is
   chrome-only, light, and defeasible; never a per-frame effect, never on a plot.

Net: **ratify the boundary + the no-live-glass cap now; gate standardizing even
the shell on ONE decisive real-hardware probe** (below). This *is* Adam's
position, made specific and, on point 1, more committal.

---

## Findings (each cited)

**F1 — Software renderer draws no shader effects.** With the Quick `software`
adaptation, `ShaderEffect`/effects "will not be rendered at all" [1][2]. The
offscreen test backend and any `QT_QUICK_BACKEND=software` path therefore cannot
show blur — so blur can never be a *standard* the app depends on. (Slice already
avoids it — good.)

**F2 — RDP kills GPU rendering; OpenGL is the worst RDP citizen.** GPU rendering
"has not worked over Windows Remote Desktop"; Qt falls back to `opengl32sw.dll`
(Mesa **llvmpipe** software rasterizer); D3D11 is "better supported by Microsoft
RemoteDesktop" [3]. The slice **pins OpenGL** (for `GLViewWidget`), i.e. it picks
the backend RDP handles *worst* and cannot switch to D3D11 without reintroducing
the §6 collision. This is the single most fragile standardization commitment.

**F3 — llvmpipe uses the non-threaded render loop; animation = full CPU
repaints.** The threaded loop is used on Windows D3D11 and hardware OpenGL, **not
with Mesa llvmpipe** [4]; any running animation "forces a full repaint … heavy
CPU load," and integrated Intel GPUs "are really slow" for this [5]. Combined
with `QQuickWidget` disabling the threaded loop *always* (arch note §1), all QML
animation is GUI-thread work — fine for a calm rail, dangerous if motion grows.

**F4 — QQuickWidget + docking/detach has real, documented failure modes.**
QtAds issue #530: `QQuickWidget` in a **floating dock** emits
`QOpenGLContext::makeCurrent() called with non-opengl surface` /
`QRhiGles2: Failed to make context current`; calling `winId()` forces a native
window → "reduced performance and possibly rendering glitches" [6]. Only matters
if QML ever enters a *detached* panel body — i.e. exactly the per-panel-migration
path we reject. Chrome-in-main-window (the slice) sidesteps it.

**F5 — Headless QML testing works but is flaky, and the repo already pays the
tax.** Offscreen QML tests "pass individually, fail when run together"; focus /
tooltip issues need foreground and are "not 100% reliable" [7][8][9]. The slice's
own tests document this concretely: `QQuickWidget` teardown access-violations,
`deleteLater` not flushing headless, the cross-test "widget corpse" crash, and a
**240 s timeout override** for the soft-reload pin (`tests/test_qml_shell.py`).
Every QML panel added multiplies this surface; the 13 QWidget panels do not carry
it. A strong reason to keep panels on QWidgets.

**F6 — Safety controls must stay single-implementation.** Kill-switch, ARM
latch, NOT-AUS, DangerGate are test-covered **QWidgets** (DECISIONS 2026-07-12).
The slice's pill shelf only *views* `DetachableTabWidget` and *routes* to existing
handlers — it adds **no** second safety implementation. Ratify that as a rule:
**no safety-critical control is ever reimplemented in QML** (a second,
GPU-dependent, harder-to-test path for a NOT-AUS is a safety regression, not a
UI upgrade).

---

## Boundary trade-off (Q4 — least-regret seam)

| Option | What | Regret | Verdict |
|---|---|---|---|
| (a) QML shell/chrome + QWidget panel islands | **built slice** | Low: 1 island, env-var fallback, no panel/test churn | **Adopt for the shell** |
| (b) QWidgets standard + QML only for ornaments | rule for panels | Low: keeps 13 tested panels + safety single-impl | **Adopt for panels + safety** |
| (c) Full per-panel QML migration | rewrite 13 panels | **High:** discards deep test coverage, ×13 the F5 flake surface, drags safety toward QML, hits F4 on every detached panel | **Reject** |

**Least-regret boundary = (a) for the shell ∪ (b) for everything below it** —
which the current slice already is. "Ratify the boundary" therefore costs almost
nothing and forecloses the expensive mistake (c).

---

## The decisive probe (smallest, on the REAL target — not "a real GPU")

Run the **unchanged `TCT_QML_SHELL=1` shell on the actual lab laptop
(i7-10510U + Intel iGPU)** and once **over an RDP session into it** — those are
the two rendering paths a *standard* must survive. Metrics + pass gates:

1. **RHI coexistence (R1):** Motor-Stage `GLViewWidget` + QML chrome render
   correctly in one OpenGL-pinned window on the iGPU — no black box, no RHI error.
2. **Detach (R2):** Motor Stage → float → 2nd monitor (diff DPI if available) →
   redock: no *persistent* blank frame (a one-shot `update()` nudge is OK).
3. **Perf on the i7 (F3):** idle chrome (rail + pill hover `ColorAnimation` +
   1 Hz poll) **< 5 % CPU**; with a live simulated scope acquire (pyqtgraph 15 Hz
   sibling) the GUI-thread heartbeat gap stays **< 100 ms** (reuse
   `test_gui_thread_watchdog.py`'s bound, on real hardware).
4. **RDP (F2):** shell launches and is usable under `opengl32sw`/llvmpipe. Pass =
   usable **OR** the classic shell (`TCT_QML_SHELL` unset) is the documented
   remote mode — the flag already makes that a **one-env-var** fallback, which is
   the strongest argument *for* this architecture: it degrades to the proven
   shell for free.
5. **Frozen build (R5):** a PyInstaller smoke build loads the QtQuick plugin tree
   + `Shell.qml` error-free.

**Decision rule:** 1-3 + 5 green on the iGPU → **ratify the shell as standard**,
with (b)+F6 as the standing rule for panels/safety. 4 fails → ratify with
"classic shell is the supported RDP/remote mode." Any of 1-3 fails as-designed →
isolate `GLViewWidget` to its own top-level, re-probe; do **not** standardize
until it passes. Budget: hours-to-a-day, not weeks — this protects the multi-week
investment.

---

## Sources

- Repo: `docs/research/qml_hybrid_architecture.md` (composition, §6 RHI, §9 law),
  `docs/research/apple_vibrancy_qt_feasibility.md`,
  `docs/research/cockpit_design_sota.md`, `docs/DECISIONS.md` (2026-07-11 QML
  hybrid + 3-layer law; 2026-07-12 danger-gate),
  `.claude/worktrees/slice1-ui/TCT_app/gui/qml_shell.py`, `.../gui/qml/Shell.qml`,
  `.../gui/qml_theme.py`, `.../tests/test_qml_shell.py`,
  `.../tests/test_gui_thread_watchdog.py`, `.../tests/test_layer_contracts.py`.
- [1] Qt Quick Software Adaptation — effects not rendered under software:
  https://doc.qt.io/qt-6/qtquick-visualcanvas-adaptations-software.html
- [2] ShaderEffect QML Type (unsupported on some backends):
  https://doc.qt.io/qt-6/qml-qtquick-shadereffect.html
- [3] Qt for Windows — Graphics Acceleration (RDP, opengl32sw/llvmpipe, D3D11):
  https://doc.qt.io/qt-6/windows-graphics.html
- [4] Qt Quick Scene Graph Default Renderer (threaded loop not with llvmpipe):
  https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph-renderer.html
- [5] Qt Quick Performance considerations (animation full-repaint CPU cost):
  https://doc.qt.io/qt-6/qtquick-performance.html
- [6] Qt-Advanced-Docking-System issue #530 — QQuickWidget in floating dock:
  https://github.com/githubuser0xFFFF/Qt-Advanced-Docking-System/issues/530
- [7] Qt Quick Test (qmltest, `-platform offscreen`):
  https://doc.qt.io/qt-6/qtquicktest-index.html
- [8] pytest-qml (drive QML tests from pytest): https://jgirardet.github.io/pytest-qml/
- [9] pytest-qt offscreen focus/flakiness (issue #426):
  https://github.com/pytest-dev/pytest-qt/issues/426
