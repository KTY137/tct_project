"""THE GLASS CONTRACT — the one place that answers "what glass can this machine
honestly render?".

Beat G-B2a (glass council, ``docs/design/glass_council/SYNTHESIS.md`` §2.3, §3,
§5 rows 1/2/3, §7.1 rung 0). This module is the **contract**, not the mechanism:
it holds one enum, one frozen environment dataclass, and two **pure** decision
functions. It paints nothing, it touches no window, it imports no Qt at module
level, and it imports ``ctypes`` NEVER (that stays quarantined in
``gui/backdrop.py`` — the only module in the GUI package allowed to touch DWM;
``tests/test_glass_env.py`` pins that with a source-level AST guard).

Why a whole module for a five-value enum
----------------------------------------
Because the *decision* is where glass programs die. Four council lanes shipped
four incompatible tier vocabularies in one night; the user already has an
override persisted on disk in a fifth spelling
(``gui/app_settings.py::GLASS_TIERS``); and the two things that actually decide
the answer on a real machine (attribute ORDER and HWND lifetime) were both
discovered by *measurement*, contradicting the prose. So the decision is
extracted into a function with no I/O, no globals and no Qt, which means it can
be tested to death offscreen — ~14 000 environments per run, in under a second.

The three laws this module encodes as CODE, not prose
-----------------------------------------------------
1. **The material carries NO hazard information** (SYNTHESIS §4.1 G3, §5 row 2 —
   Baldr's "alarm-de-glass" rule is KILLED). :class:`GlassEnvironment` has no
   alarm/error/danger/armed/trip field, and :func:`decide_tier` cannot see run
   state: ``scan_active`` is in the environment because the *transition* needs
   it, and :func:`decide_tier` provably ignores it (pinned by test). An operator
   on a frostless RDP session must never be able to misread the flat look as a
   standing alarm.
2. **Fail-safe direction is DOWN.** Unknown build, unreadable probe, exploding
   probe, garbage in a field, an override spelling from a future codebase — all
   of it lands on :data:`SAFE_FLOOR` (``TOKEN``), never higher. The GUI must
   never crash, hang, or *silently upgrade* because glass could not be decided.
3. **Downgrades never queue.** :func:`plan_transition` returns
   ``action="apply"`` with a ``deadline_ms`` of :data:`DOWNGRADE_DEADLINE_MS`
   for every downgrade, including mid-scan; only *upgrades* may be deferred to
   scan-idle. A dead-glass window is recoverable within one event-loop turn.
   (SYNTHESIS §5 row 1 / Fenrir rider 3.)

Ground truth (measured, and it beat the prose)
----------------------------------------------
* ``353072f`` finding 1 — **path D is REFUTED.** A live ``QOpenGLWidget`` child
  does NOT kill its window's DWM material on Qt 6.11.1 / Win11 26200 (acrylic
  84/84/84 with and without the GL child). So :attr:`GlassEnvironment.rtt_children`
  is *observed and logged* but is **not a decision input** — see
  :data:`PATH_D_CAPS_AT_TOKEN`.
* ``353072f`` finding 3 — **the RHI verdict is INVERTED.** A ``QQuickWindow``
  shell shows real glass on the **OpenGL** RHI and FLAT WHITE on D3D11 (Qt 6.11
  never creates a DirectComposition swapchain there; the flip-model present
  loses the alpha). ``main.py``'s OpenGL pin is load-bearing. Hence
  :func:`_scene_capable` requires ``rhi_backend == "opengl"`` on Windows and
  refuses the *default* D3D11.
* ``081da40`` — the HWND is recreated during startup and every DWM attribute
  dies with it. That is the event spine's problem (``gui/backdrop.py``), not
  this module's; it is named here only so nobody re-derives the tier from
  "did the material stick" instead of from the environment.
* ``docs/research/linux_compositor_glass.md`` — the Linux ladder is
  **FLAT / TOKEN / SCENE**. ``WINDOW`` has no Linux implementation we can ship
  (§3.5) and ``COMPOSED`` is Windows-only by definition. A software rasterizer
  (llvmpipe / ``QT_QUICK_BACKEND=software``) caps at ``TOKEN`` — not because
  SCENE cannot render, but because a CPU rasterizer plus the 15–30 Hz FastDAQ
  islands is exactly the contention SYNTHESIS §4.3 forbids.

Consumers
---------
Nothing consumes this yet — wiring it into ``gui/style.py`` /
``gui/backdrop.py`` is the deliberate follow-up beat. What that beat must do is
spelled out at the bottom of this docstring's sibling: the ``handoff`` section
of the G-B2a report, and the call-site notes on :func:`decide_tier` and
:func:`format_truth_log`.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Any, Callable, Optional, Sequence

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 1. THE ONE TIER ENUM (SYNTHESIS §3.1 — ratified; do not extend casually)     #
# --------------------------------------------------------------------------- #

class GlassTier(IntEnum):
    """The ONLY material-tier vocabulary in this codebase.

    Ordered and comparable (``IntEnum``): ``FLAT < TOKEN < WINDOW < SCENE <
    COMPOSED``. Downgrades move DOWN; nothing ever climbs on loss of capability.

    "A lower value is a capability subset of a higher one" is a statement about
    the RENDERER, not about the host: a ``SCENE`` renderer can always also paint
    the ``TOKEN`` look (underlay law — every glass surface paints its opaque
    pre-blend first). It does **not** mean ``SCENE`` implies a live OS material:
    on Linux, ``SCENE`` is reachable while ``WINDOW`` is not, because SCENE's
    frost is app-owned (baked ambient) and needs no compositor support at all.
    That is the whole reason the ladder is worth building.
    """

    FLAT = 0
    """Accessibility / operator escape hatch: plain opaque solids, no glass
    identity. Chosen ONLY by a deliberate input — high contrast, or the operator
    override. It is NOT the "something went wrong" tier (that is TOKEN)."""

    TOKEN = 1
    """Pre-blended opaque tokens (the v6 look) — **the guaranteed floor**. Every
    host, every compositor, byte-identical offscreen; it needs nothing from the
    OS because it is just hex. This is :data:`SAFE_FLOOR`: where every unknown,
    every failure and every garbage input lands."""

    WINDOW = 2
    """+ a real OS window material (DWM: ExtendFrame + attr 20 + attr 38) on the
    top-level window itself. Windows 11 22H2+ only. No Linux implementation
    exists that we can ship (research §3.5)."""

    SCENE = 3
    """GlassShell: a translucent ``QQuickWindow`` whose scene alpha reaches the
    compositor, with the app-owned component kit and baked, position-sampled
    frost. Portable (Windows + Linux), because the frost is ours. Unbuilt today
    — reachable only when a caller declares ``shell="glass"`` (beat G3)."""

    COMPOSED = 4
    """+ Windows composition interop (host-backdrop brush / redirection-bitmap
    alpha) — the gated G5 enhancement. **Unbuilt.** Never auto-selected: it
    requires ``composition_interop=True`` in the environment, which nothing sets
    yet, so :func:`decide_tier` cannot return it today (pinned by test)."""


SAFE_FLOOR: GlassTier = GlassTier.TOKEN
"""Where every unknown lands.

Deliberately ``TOKEN`` and not ``FLAT``. Both are opaque and both satisfy the
readability contract by construction (SYNTHESIS §4.2 — "TOKEN/FLAT pass by
construction, pure math"), so they are equally *safe*; but ``FLAT`` is a
deliberate accessibility look, and dropping the whole app's visual identity
because one probe hiccuped would be a worse failure, not a safer one. ``FLAT``
is reached only by an explicit input (high contrast, or the operator override).
"""


# --------------------------------------------------------------------------- #
# 2. The vocabulary collision — ONE canonical set + the deprecation/alias map  #
# --------------------------------------------------------------------------- #

OVERRIDE_AUTO = "auto"

CANONICAL_OVERRIDES: tuple[str, ...] = ("auto", "flat", "token", "window", "scene")
"""The operator-override vocabulary (SYNTHESIS §3.1). An override is a
**CEILING, never a floor** — it can only force the tier DOWN. Forcing UP is
structurally impossible: detection lies are answered by forcing down, never by
promising a material the host cannot render.

``composed`` is accepted by :func:`override_ceiling` for forward compatibility
but is deliberately NOT offered to the operator (G5 is unbuilt).
"""

OVERRIDE_ALIASES: dict[str, GlassTier] = {
    # --- canonical (SYNTHESIS §3.1) ---------------------------------------- #
    "auto": GlassTier.COMPOSED,   # == no ceiling: min(COMPOSED, ...) is identity
    "flat": GlassTier.FLAT,
    "token": GlassTier.TOKEN,
    "window": GlassTier.WINDOW,
    "scene": GlassTier.SCENE,
    "composed": GlassTier.COMPOSED,

    # --- LEGACY, PERSISTED ON DISK RIGHT NOW ------------------------------- #
    # gui/app_settings.py::GLASS_TIERS = ("auto", "real", "token", "flat").
    # "auto"/"token"/"flat" are already canonical spellings. "real" is the one
    # that must be translated, and it must be translated DOWNWARD-SAFELY:
    #
    #   "real"  ->  WINDOW  (the real OS material — what the word names)
    #
    # NOT to SCENE/COMPOSED. The override is a ceiling; mapping "real" to the
    # top would mean an operator who explicitly asked for something now silently
    # receives a HIGHER tier than they asked for on a GlassShell machine — the
    # one thing the fail-safe law forbids. A ceiling of WINDOW is the literal,
    # deterministic reading of the word, and it is never an upgrade.
    "real": GlassTier.WINDOW,

    # --- the three dead council vocabularies (SYNTHESIS §3.3) --------------- #
    # Where §3.3 maps a legacy rung onto TWO tiers ("WINDOW·SCENE"), we take the
    # LOWER one. Ambiguity resolves downward — always.
    "t2": GlassTier.FLAT,          # Ymir
    "t1": GlassTier.TOKEN,
    "t0": GlassTier.WINDOW,        # §3.3: WINDOW (classic) · SCENE (GlassShell)
    "r0": GlassTier.FLAT,          # Baldr
    "r1": GlassTier.TOKEN,
    "r2": GlassTier.WINDOW,
    "r3": GlassTier.SCENE,         # §3.3: SCENE · COMPOSED
    "preblend": GlassTier.TOKEN,   # Brokkr-B
    "real_backdrop": GlassTier.WINDOW,   # §3.3: WINDOW · SCENE
}
"""Every spelling this project has ever used, mapped onto the one enum.

Two rules govern every entry, and they are the whole point of this table:

* **Kaya's saved settings keep working.** Every value in
  ``app_settings.GLASS_TIERS`` resolves here, deterministically, today.
* **A legacy or unknown spelling never silently jumps to a higher tier.**
  Ambiguous legacy rungs resolve to the LOWER tier; an *unrecognized* string
  resolves to :data:`SAFE_FLOOR` (see :func:`override_ceiling`).
"""


def override_ceiling(value: Any) -> GlassTier:
    """Resolve an operator-override value to the tier CEILING it imposes.

    * absent (``None`` / ``""``) or ``"auto"`` → ``COMPOSED`` — i.e. **no
      ceiling**. ``QSettings.value()`` returns ``None`` for an unset key and
      ``app_settings.theme_glass_tier`` already coerces absence to ``"auto"``;
      honoring that as "no preference" is what keeps the shipped default intact.
    * a known canonical or legacy spelling → its tier (see
      :data:`OVERRIDE_ALIASES`), case- and whitespace-insensitive.
    * a *recognizably-a-string-but-unknown* spelling (a typo, a value written by
      a future build) → :data:`SAFE_FLOOR`. Deterministic, never higher, and the
      honest answer: "I do not know what you asked for, so you get the
      guaranteed floor."
    * anything that is not a string at all → :data:`SAFE_FLOOR`.

    Pure. Never raises.
    """
    if value is None:
        return OVERRIDE_ALIASES[OVERRIDE_AUTO]
    if not isinstance(value, str):
        return SAFE_FLOOR
    key = value.strip().lower()
    if not key:
        return OVERRIDE_ALIASES[OVERRIDE_AUTO]
    return OVERRIDE_ALIASES.get(key, SAFE_FLOOR)


def canonical_override(value: Any) -> str:
    """The canonical spelling of the ceiling ``value`` resolves to.

    ``"real"`` → ``"window"``; ``"T0"`` → ``"window"``; garbage → ``"token"``;
    absent → ``"auto"``. A pure NAME mapping — it does not read or write
    QSettings. Whether ``theme/glass_tier`` gets migrated in place is the wiring
    beat's call (``gui/app_settings.py`` is not this beat's file).
    """
    if value is None:
        return OVERRIDE_AUTO
    if isinstance(value, str) and value.strip().lower() in ("", OVERRIDE_AUTO):
        return OVERRIDE_AUTO
    return override_ceiling(value).name.lower()


# --------------------------------------------------------------------------- #
# 3. Shells, hosts, and the constants the decision keys off                    #
# --------------------------------------------------------------------------- #

SHELL_CLASSIC = "classic"
SHELL_GLASS = "glass"
SHELL_KINDS: tuple[str, ...] = (SHELL_CLASSIC, SHELL_GLASS)

SHELL_CEILINGS: dict[str, GlassTier] = {
    SHELL_CLASSIC: GlassTier.WINDOW,   # today's QWidget cockpit; the eternal fallback
    SHELL_GLASS: GlassTier.COMPOSED,   # the translucent QQuickWindow shell (unbuilt)
}

MIN_WINDOWS_MATERIAL_BUILD = 22621
"""Windows 11 22H2 — the first build with public ``DWMWA_SYSTEMBACKDROP_TYPE``.

MUST equal ``gui.backdrop._MIN_SUPPORTED_BUILD``; duplicated here (rather than
imported) so this module stays free of the Qt/ctypes import weight, and pinned
against drift by ``tests/test_glass_env.py``. Win10 is ``TOKEN`` forever
(SYNTHESIS §2.2.3 item 3) — there is deliberately no ACCENT_POLICY fallback.
"""

_HEADLESS_QT_PLATFORMS = frozenset({"", "offscreen", "minimal", "vnc"})
"""Qt platform plugins that cannot show a compositor-composited scene at all.
``offscreen`` is the whole test suite; it is the byte-identical ``TOKEN`` floor
the test spine rests on (research L8)."""

_SOFTWARE_RHI = frozenset({"software", "softwarecontext", "null"})

PATH_D_CAPS_AT_TOKEN = False
"""Path D — "any render-to-texture child forfeits its window's material".

**Measured FALSE** on Qt 6.11.1 / Win11 26200 (``353072f`` finding 1: a window
with a live ``QOpenGLWidget`` child kept its acrylic, pixel-indistinguishable
from the GL-free control). So the census is *observed and logged*
(:attr:`GlassEnvironment.rtt_children`, :func:`format_truth_log`) but it does
**not** cap the tier, and ``tests/test_glass_env.py`` pins that
:func:`decide_tier` is independent of it.

Kept as a named constant, not deleted, because the spike ran on ONE host (Intel
UHD iGPU) and its own commit message says "re-run on the bench before betting
the synthesis on the path-D refutation". If the bench contradicts it, the fix is
this flag plus three lines in :func:`_renderable_tiers` — not an archaeology
expedition through a deleted concept.
"""


# --------------------------------------------------------------------------- #
# 4. The environment — frozen, injectable, and free of hazard information      #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class GlassEnvironment:
    """Everything the tier decision depends on — and nothing else.

    Every field is either an OBSERVATION of the host or a DECLARATION by the
    caller. There is deliberately **no alarm, error, danger, armed or trip
    field** and there never may be one (SYNTHESIS §4.1 G3): the material carries
    zero hazard information, so an operator on a frostless machine can never
    misread the absence of glass as a standing alarm. That invariant is enforced
    by a test that greps this dataclass's own field names.

    Tri-state booleans (``bool | None``) are not sloppiness — ``None`` means
    **"not observable on this host"**, which is a different thing from ``False``
    and must be treated differently:

    * ``False`` is a positive observation that a capability is absent → it
      VETOES the tier that needs it.
    * ``None`` is "we cannot see it here" → it does **not** veto. Windows
      high-contrast has no Qt API and Linux has no detection mechanism at all
      (research §9.5); forcing ``FLAT`` on every Linux box because we cannot read
      a flag it does not have would be absurd, and refusing the material because
      we cannot read ``EnableTransparency`` would kill glass that demonstrably
      works today. Nothing hazardous can follow from a wrong guess here: the
      underlay law (``gui/backdrop.py``) already degrades a material that does
      not composite to the opaque token pre-blend.

    A *broken* probe is a third thing entirely, and it is NOT ``None``: it sets
    :attr:`degraded`, which caps the whole decision at :data:`SAFE_FLOOR`.
    """

    # --- host ---------------------------------------------------------------
    platform: str = ""
    """``sys.platform``: ``"win32"`` | ``"linux"`` | ``"darwin"`` | ``""``."""

    windows_build: int = 0
    """Windows build number; ``0`` on any non-Windows host or if unreadable.
    ``< MIN_WINDOWS_MATERIAL_BUILD`` ⇒ no ``WINDOW`` tier, ever (Win10 = TOKEN
    forever)."""

    qt_platform: str = ""
    """Qt's active platform plugin: ``"windows"`` | ``"xcb"`` | ``"wayland"`` |
    ``"offscreen"`` | ... The DWM material needs the real ``"windows"`` plugin;
    the whole test suite runs ``"offscreen"``, which is the TOKEN floor."""

    rhi_backend: str = ""
    """The Qt RHI / scenegraph backend (SYNTHESIS §3.1 calls this
    ``scenegraph_api``): ``"opengl"`` | ``"d3d11"`` | ``"vulkan"`` | ``"metal"``
    | ``"software"`` | ``""`` (unknown).

    **This field is why the spike mattered.** On Windows, a translucent
    ``QQuickWindow`` shows real glass on **OpenGL** and FLAT WHITE on D3D11
    (``353072f`` finding 3) — and D3D11 is Qt's Windows *default*. So on
    ``win32`` the ``SCENE`` tier requires ``rhi_backend == "opengl"``
    explicitly; ``""`` (unknown) does NOT qualify, because the unknown default
    is the broken one. On Linux the default IS OpenGL (Qt docs), so ``""``
    there does not veto."""

    software_rasterizer: bool | None = None
    """``QT_QUICK_BACKEND=software``, or a GL renderer of llvmpipe / swrast /
    softpipe. ``True`` ⇒ ceiling ``TOKEN`` — not because SCENE cannot render
    (it has no shaders, by law), but because a CPU rasterizer plus the 15–30 Hz
    FastDAQ islands is exactly the acquisition contention SYNTHESIS §4.3
    forbids. Glass never costs a measurement."""

    dwm_composition: bool | None = None
    """``DwmIsCompositionEnabled``. ``False`` ⇒ no ``WINDOW``."""

    transparency_enabled: bool | None = None
    """The OS "Transparency effects" setting. ``False`` ⇒ no ``WINDOW`` (the
    material composes as a flat tint). ``SCENE`` survives — its frost source
    simply flips to the baked ambient. That is the GlassShell's headline
    property."""

    high_contrast: bool | None = None
    """``True`` ⇒ ``FLAT``, mandatory, outranking everything (SYNTHESIS §3.1).
    Expressed as a ceiling, so the ``min()`` in :func:`explain_tier` needs no
    special case."""

    remote_session: bool | None = None
    """RDP / X-forwarding / VNC. ``True`` ⇒ ceiling ``TOKEN``. Policy, not
    limitation: glass over a WAN link is bandwidth spent on decoration while the
    operator waits for a scan point (research §7, which notes this is "the same
    answer Ymir gave for RDP on Windows"). It is also what makes SYNTHESIS §7.3
    P4's "instant downgrade on RDP connect" a *deterministic* function of the
    environment rather than a hand-written special case."""

    battery_saver: bool | None = None
    """Windows battery saver suppresses transparency effects ⇒ no ``WINDOW``.
    ``SCENE`` survives (baked frost)."""

    composition_interop: bool = False
    """The G5 winrt host-backdrop helper is loaded and healthy. **Nothing sets
    this yet**, which is exactly why :func:`decide_tier` can never return
    ``COMPOSED`` today — an unbuilt tier must be unreachable, not merely
    unlikely."""

    rtt_children: tuple[str, ...] = ()
    """The path-D census: names of visible render-to-texture children in this
    top-level. **Observed and logged, NOT decisive** — see
    :data:`PATH_D_CAPS_AT_TOKEN`."""

    # --- caller declarations ------------------------------------------------
    shell: str = SHELL_CLASSIC
    """Which renderer is asking (:data:`SHELL_KINDS`). The ceiling comes from
    :data:`SHELL_CEILINGS`. It is an input rather than a module constant so the
    GlassShell beat never has to edit this pure function to introduce itself."""

    user_override: str = OVERRIDE_AUTO
    """The persisted operator ceiling (``theme/glass_tier``). See
    :func:`override_ceiling`."""

    scan_active: bool = False
    """A run is in progress (GUI-side ``RunStateViewModel.active``; no coupling
    into ``controller/``).

    **:func:`decide_tier` MUST NOT and DOES NOT read this.** The TARGET tier is
    a property of the machine; only the TIMING of reaching it is a property of
    the run (:func:`plan_transition`). If the tier itself depended on run state,
    the material would be carrying run-state information — one short step from
    carrying hazard information, which is forbidden. Pinned by test."""

    degraded: bool = False
    """A probe raised, or a field held uncoercible garbage. Caps the whole
    decision at :data:`SAFE_FLOOR`."""


# --------------------------------------------------------------------------- #
# 5. Coercion — so a hand-built or half-broken environment can never explode   #
# --------------------------------------------------------------------------- #

class _Garbage(Exception):
    """Internal marker: a field held a value we refuse to guess about."""


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    raise _Garbage(f"expected str, got {type(value).__name__}")


def _coerce_build(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _Garbage(f"expected a non-negative build int, got {value!r}")
    return value


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise _Garbage(f"expected bool, got {type(value).__name__}")


def _coerce_tri(value: Any) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise _Garbage(f"expected bool|None, got {type(value).__name__}")


def _coerce_names(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raise _Garbage("expected a sequence of names, got a bare str")
    if not isinstance(value, Sequence):
        raise _Garbage(f"expected a sequence, got {type(value).__name__}")
    out = []
    for item in value:
        if not isinstance(item, str):
            raise _Garbage(f"expected str names, got {type(item).__name__}")
        out.append(item)
    return tuple(out)


def _coerce_override(value: Any) -> str:
    """Overrides get their own rule: an *unknown string* is not garbage — it is
    an unrecognized ceiling, and :func:`override_ceiling` already resolves it to
    :data:`SAFE_FLOOR`. Only a non-string (and non-``None``) is garbage."""
    if value is None:
        return OVERRIDE_AUTO
    if isinstance(value, str):
        return value.strip().lower() or OVERRIDE_AUTO
    raise _Garbage(f"expected str override, got {type(value).__name__}")


def _coerce_shell(value: Any) -> str:
    key = _coerce_str(value)
    if key not in SHELL_KINDS:
        raise _Garbage(f"unknown shell {value!r}")
    return key


_COERCERS: dict[str, Callable[[Any], Any]] = {
    "platform": _coerce_str,
    "windows_build": _coerce_build,
    "qt_platform": _coerce_str,
    "rhi_backend": _coerce_str,
    "software_rasterizer": _coerce_tri,
    "dwm_composition": _coerce_tri,
    "transparency_enabled": _coerce_tri,
    "high_contrast": _coerce_tri,
    "remote_session": _coerce_tri,
    "battery_saver": _coerce_tri,
    "composition_interop": _coerce_bool,
    "rtt_children": _coerce_names,
    "shell": _coerce_shell,
    "user_override": _coerce_override,
    "scan_active": _coerce_bool,
    "degraded": _coerce_bool,
}

_SAFE_DEFAULTS: dict[str, Any] = {
    "platform": "",
    "windows_build": 0,
    "qt_platform": "",
    "rhi_backend": "",
    "software_rasterizer": None,
    "dwm_composition": None,
    "transparency_enabled": None,
    "high_contrast": None,
    "remote_session": None,
    "battery_saver": None,
    "composition_interop": False,
    "rtt_children": (),
    "shell": SHELL_CLASSIC,
    "user_override": OVERRIDE_AUTO,
    "scan_active": False,
    "degraded": False,
}


def normalize(env: GlassEnvironment) -> GlassEnvironment:
    """Return ``env`` with every field coerced, and ``degraded=True`` if any
    field held garbage.

    Pure. Never raises — that is the point: :func:`decide_tier` is called from
    an event filter in a lab GUI, and a ``ValueError`` there would abort an
    unrelated Qt event delivery. Garbage in a field is not a crash; it is a
    downgrade.
    """
    values: dict[str, Any] = {}
    degraded = False
    for name, coerce in _COERCERS.items():
        raw = getattr(env, name, _SAFE_DEFAULTS[name])
        try:
            values[name] = coerce(raw)
        except Exception as exc:                # _Garbage, or anything a weird
            degraded = True                     # __getattr__ managed to throw
            values[name] = _SAFE_DEFAULTS[name]
            logger.warning(
                "glass: environment field %s=%r is not usable (%s) — the whole "
                "decision degrades to %s (fail-safe direction is DOWN)",
                name, raw, exc, SAFE_FLOOR.name.lower())
    values["degraded"] = bool(values["degraded"]) or degraded
    return GlassEnvironment(**values)


# --------------------------------------------------------------------------- #
# 6. THE PURE DECISION                                                         #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class TierDecision:
    """The full, explainable result of one tier resolution — everything the
    truth log and the wiring beat need, with no second call into this module."""

    tier: GlassTier
    cap: GlassTier
    renderable: tuple[GlassTier, ...]
    """The tiers this (host, shell) pair can ACTUALLY paint, ascending. Always
    contains FLAT and TOKEN."""
    ceilings: tuple[tuple[str, GlassTier], ...]
    """Every ceiling that applied, ``(name, tier)``, sorted by name (so the
    decision is byte-deterministic — no dict/hash ordering leaks into a log
    line or a test)."""
    binding: tuple[str, ...]
    """The name(s) of the ceiling(s) that actually bound the result — i.e. why
    you are not getting more glass. This is the sentence the operator deserves."""
    degraded: bool
    env: GlassEnvironment
    """The NORMALIZED environment (post-coercion)."""


def _window_capable(e: GlassEnvironment) -> bool:
    """Can this host paint a real OS window material?

    Windows-only, today and for the foreseeable future: the Linux ``WINDOW`` row
    is *absent* — GNOME's blur protocol postdates every version our target
    distros ship, there is no X11 session to fall back to, and PySide6 has no
    binding to the protocol even where a compositor implements it
    (research §3.5). Saying so in one predicate beats discovering it in a bug
    report.
    """
    if e.platform != "win32" or e.qt_platform != "windows":
        return False
    if e.windows_build < MIN_WINDOWS_MATERIAL_BUILD:
        return False
    # False vetoes; None ("cannot observe it here") does not — see the
    # GlassEnvironment docstring. A wrong guess costs a flat tint, and the
    # underlay law catches it; a wrong veto costs Kaya his glass.
    if e.dwm_composition is False:
        return False
    if e.transparency_enabled is False:
        return False
    if e.battery_saver is True:
        return False
    return True


def _scene_capable(e: GlassEnvironment) -> bool:
    """Can this host paint the app-owned in-scene frost?

    Needs a real scene graph and nothing else — no compositor support, no blur
    protocol, no translucent window, no GPU feature. That portability is the
    strongest argument in the whole glass architecture (research §6).

    Two hard refusals:

    * a software rasterizer (llvmpipe / ``QT_QUICK_BACKEND=software``) — SCENE
      *renders* there, but a CPU rasterizer plus the FastDAQ islands is the
      contention SYNTHESIS §4.3 forbids;
    * **D3D11 on Windows** — measured FLAT WHITE on a translucent
      ``QQuickWindow`` (``353072f`` finding 3). And D3D11 is Qt's Windows
      default, so an *unknown* RHI on Windows is refused too: on this one field,
      the unknown value is the broken one.
    """
    if e.software_rasterizer is True:
        return False
    if e.rhi_backend in _SOFTWARE_RHI:
        return False
    if e.qt_platform in _HEADLESS_QT_PLATFORMS:
        return False
    if e.platform == "win32" and e.rhi_backend != "opengl":
        return False
    return True


def _composed_capable(e: GlassEnvironment) -> bool:
    """Windows composition interop (G5). Unbuilt — and therefore UNREACHABLE,
    not merely unlikely: it demands ``composition_interop=True``, which no probe
    sets. An enum value that nothing can render must not be selectable."""
    return (
        e.composition_interop is True
        and e.platform == "win32"
        and _window_capable(e)
        and _scene_capable(e)
    )


def _renderable_tiers(e: GlassEnvironment) -> tuple[GlassTier, ...]:
    """The tiers this (host, shell) pair can actually paint, ascending.

    ``FLAT`` and ``TOKEN`` are unconditional — they are hex, they cannot fail.
    Everything above is a capability of the host AND of the shell, which is why
    a Linux GlassShell yields ``{FLAT, TOKEN, SCENE}`` with no ``WINDOW`` under
    it, and a classic Windows cockpit yields ``{FLAT, TOKEN, WINDOW}`` with no
    ``SCENE`` above it. The ladder is not a staircase every host climbs in
    order; it is a set, and the answer is its maximum below the cap.
    """
    tiers = [GlassTier.FLAT, GlassTier.TOKEN]
    if PATH_D_CAPS_AT_TOKEN and e.rtt_children:
        # Currently unreachable (path D refuted, 353072f). Kept so a bench
        # refutation of the refutation is a one-flag change.
        return tuple(tiers)
    if _window_capable(e):
        tiers.append(GlassTier.WINDOW)
    if e.shell == SHELL_GLASS:
        if _scene_capable(e):
            tiers.append(GlassTier.SCENE)
        if _composed_capable(e):
            tiers.append(GlassTier.COMPOSED)
    return tuple(tiers)


def _ceilings(e: GlassEnvironment) -> dict[str, GlassTier]:
    """Every ceiling that applies to a NORMALIZED environment.

    A ceiling only ever pushes DOWN, and a capability only ever ADDS to
    ``renderable`` — which is exactly why the monotonicity property holds by
    construction rather than by vigilance.
    """
    ceilings: dict[str, GlassTier] = {
        "shell": SHELL_CEILINGS.get(e.shell, SAFE_FLOOR),
        "override": override_ceiling(e.user_override),
    }
    if e.high_contrast is True:
        # Mandatory, outranks everything (SYNTHESIS §3.1). No special case
        # needed: FLAT is the bottom, so min() does the outranking for us.
        ceilings["high_contrast"] = GlassTier.FLAT
    if e.remote_session is True:
        ceilings["remote_session"] = SAFE_FLOOR
    if e.software_rasterizer is True or e.rhi_backend in _SOFTWARE_RHI:
        ceilings["software_rasterizer"] = SAFE_FLOOR
    if e.degraded:
        ceilings["degraded"] = SAFE_FLOOR
    return ceilings


def decide_tier(env: GlassEnvironment) -> GlassTier:
    """THE pure decision. ``GlassEnvironment`` in, :class:`GlassTier` out.

    PURE: no I/O, no Qt, no globals, no logging, no clock. Same environment ⇒
    same tier, byte for byte, forever. Total (never raises), monotone (removing
    a capability never raises the tier), fail-safe (anything unknown lands on
    :data:`SAFE_FLOOR` or below), and blind to run state and hazard state by
    construction.

    The resolution, in one sentence: **the tier is the highest rung this host
    and shell can actually paint that is not above any ceiling.**

        tier = max{ t ∈ renderable(host, shell) : t ≤ min(all ceilings) }

    ``renderable`` always contains ``FLAT``, so the maximum always exists — that
    is what makes this function total rather than merely well-tested.

    Deliberately does NOT build a :class:`TierDecision`: the event spine calls
    this per window per event, and nobody should pay for an explanation they did
    not ask for. Callers that want to log WHY call :func:`explain_tier` +
    :func:`format_truth_log` instead of re-deriving the reasoning.
    """
    try:
        e = normalize(env)
        cap = min(_ceilings(e).values())
        return max(t for t in _renderable_tiers(e) if t <= cap)
    except Exception:                                   # pragma: no cover
        # The last belt. This is called from Qt event handlers; it may not
        # raise, ever. If the impossible happens, the answer is the floor.
        logger.exception("glass: tier decision failed — falling back to %s",
                         SAFE_FLOOR.name.lower())
        return SAFE_FLOOR


def explain_tier(env: GlassEnvironment) -> TierDecision:
    """:func:`decide_tier`, with its reasoning attached — for the truth log, the
    theme editor, and the capture harness. Same purity guarantees."""
    try:
        e = normalize(env)
        ceilings = _ceilings(e)
        cap = min(ceilings.values())
        renderable = _renderable_tiers(e)
        tier = max(t for t in renderable if t <= cap)
        binding = tuple(sorted(n for n, c in ceilings.items() if c == cap)) \
            if tier == cap else ("host",)

        return TierDecision(
            tier=tier,
            cap=cap,
            renderable=renderable,
            ceilings=tuple(sorted(ceilings.items())),
            binding=binding,
            degraded=e.degraded,
            env=e,
        )
    except Exception:                                   # pragma: no cover
        logger.exception("glass: tier explanation failed — falling back to %s",
                         SAFE_FLOOR.name.lower())
        safe = replace(GlassEnvironment(), degraded=True)
        return TierDecision(
            tier=SAFE_FLOOR, cap=SAFE_FLOOR,
            renderable=(GlassTier.FLAT, GlassTier.TOKEN),
            ceilings=(("degraded", SAFE_FLOOR),), binding=("degraded",),
            degraded=True, env=safe,
        )


# --------------------------------------------------------------------------- #
# 7. THE TRANSITION POLICY — downgrades never queue (SYNTHESIS §5 row 1)       #
# --------------------------------------------------------------------------- #

DOWNGRADE_DEADLINE_MS = 200
"""A downgrade must be applied within ONE event-loop turn — ≤ 200 ms from the
triggering event. Baldr's unfalsifiable "dead glass must be unreachable" was
restated as this number (SYNTHESIS §5 row 1); it is the whole reason a dead
material is a shrug instead of a hazard."""

UPGRADE_HYSTERESIS_S = 60.0
"""An upgrade waits for acquisition-idle **plus** this settle time **plus** a
verified re-pass (SYNTHESIS §3.2). Upgrades are the expensive, flappy direction;
nothing about them is urgent."""

TRANSITION_NONE = "none"
TRANSITION_APPLY = "apply"
TRANSITION_DEFER = "defer"


@dataclass(frozen=True)
class Transition:
    """A plan, not an action. The wiring beat executes it; this module decides
    it, purely, so the law cannot be got wrong at the call site."""

    action: str
    """``"none"`` | ``"apply"`` (do it now, within :attr:`deadline_ms`) |
    ``"defer"`` (a run is in progress — re-plan at scan-idle)."""
    direction: str
    """``"none"`` | ``"down"`` | ``"up"``."""
    current: GlassTier
    target: GlassTier
    deadline_ms: int | None
    """Set ONLY for downgrades. A downgrade that misses this deadline is a bug,
    not a preference."""
    hysteresis_s: float | None
    """Set ONLY for upgrades: the minimum settle time the caller must observe
    (on top of scan-idle and a verified re-pass) before applying."""
    reason: str

    @property
    def is_downgrade(self) -> bool:
        return self.direction == "down"

    @property
    def is_upgrade(self) -> bool:
        return self.direction == "up"


def _coerce_tier(value: Any) -> GlassTier:
    if isinstance(value, GlassTier):
        return value
    try:
        return GlassTier(int(value))
    except Exception:
        return SAFE_FLOOR


def plan_transition(current: Any, target: Any, scan_active: Any = False) -> Transition:
    """THE transition law, as code (SYNTHESIS §2.3 / §3.2 / §5 row 1).

    * **DOWNGRADES ARE NEVER QUEUED.** ``target < current`` ⇒ ``action="apply"``
      with ``deadline_ms=`` :data:`DOWNGRADE_DEADLINE_MS`, *including mid-scan*.
      One opaque token swap, one event-loop turn. This is the single line that
      makes a lost material a cosmetic event instead of a stuck window an
      operator cannot read. There is deliberately NO branch here that can return
      ``"defer"`` for a downgrade — the impossibility is structural, and pinned
      by an exhaustive test over every (current, target, scan_active) triple.
    * **UPGRADES WAIT FOR SCAN-IDLE.** ``target > current`` while
      ``scan_active`` ⇒ ``action="defer"``. Bakes, probes, restyles and
      attribute churn never contend with acquisition (SYNTHESIS §4.3). Idle
      upgrades still carry :data:`UPGRADE_HYSTERESIS_S`.
    * Equal ⇒ ``"none"``. Nothing to do is a legitimate, cheap answer, and the
      event spine calls this on every settings change.

    Pure. Never raises — garbage tiers coerce to :data:`SAFE_FLOOR`.
    """
    cur = _coerce_tier(current)
    tgt = _coerce_tier(target)
    active = scan_active is True

    if tgt == cur:
        return Transition(
            action=TRANSITION_NONE, direction="none", current=cur, target=tgt,
            deadline_ms=None, hysteresis_s=None,
            reason="already at the target tier")

    if tgt < cur:
        return Transition(
            action=TRANSITION_APPLY, direction="down", current=cur, target=tgt,
            deadline_ms=DOWNGRADE_DEADLINE_MS, hysteresis_s=None,
            reason=("downgrade: applied immediately as one opaque token swap"
                    + (" (mid-scan — downgrades are NEVER queued)" if active else "")))

    if active:
        return Transition(
            action=TRANSITION_DEFER, direction="up", current=cur, target=tgt,
            deadline_ms=None, hysteresis_s=UPGRADE_HYSTERESIS_S,
            reason="upgrade deferred: a run is active, and glass never contends "
                   "with acquisition")

    return Transition(
        action=TRANSITION_APPLY, direction="up", current=cur, target=tgt,
        deadline_ms=None, hysteresis_s=UPGRADE_HYSTERESIS_S,
        reason="upgrade: acquisition idle; apply after the hysteresis window and "
               "a verified re-pass")


def plan_transition_for(current: Any, env: GlassEnvironment) -> Transition:
    """Convenience: decide the target from ``env`` and plan the move to it.

    The ONE call the event spine needs per re-resolution. Pure."""
    e = normalize(env)
    return plan_transition(current, decide_tier(e), e.scan_active)


# --------------------------------------------------------------------------- #
# 8. The truth log (Ymir I5 format, frozen here so it cannot drift)            #
# --------------------------------------------------------------------------- #

def _flag(value: bool | None) -> str:
    return "?" if value is None else ("1" if value else "0")


def format_truth_log(decision: TierDecision, *, window: str = "main",
                     reason: str = "resolve") -> str:
    """The one greppable line, emitted at startup and on every re-decision
    (SYNTHESIS §3.1).

    Pure string building — the CALLER logs it. Frozen here rather than at the
    call site so the format cannot drift between the classic shell, the
    GlassShell and the capture harness, all three of which will grep it.

    ``?`` means "not observable on this host" (a tri-state ``None``) — visibly
    different from ``0``, because "we looked and it was off" and "we cannot look
    here" are different facts and an operator debugging a white window deserves
    to know which one he has.
    """
    e = decision.env
    census = ",".join(e.rtt_children) if e.rtt_children else "none"
    return (
        f"glass: {reason} tier={decision.tier.name.lower()} window={window} "
        f"(build={e.windows_build} qt={e.qt_platform or '?'} "
        f"rhi={e.rhi_backend or '?'} shell={e.shell} "
        f"remote={_flag(e.remote_session)} transparency={_flag(e.transparency_enabled)} "
        f"hc={_flag(e.high_contrast)} saver={_flag(e.battery_saver)} "
        f"census=rtt:{census} override={e.user_override} "
        f"cap={decision.cap.name.lower()} by={'+'.join(decision.binding)}"
        f"{' DEGRADED' if decision.degraded else ''})"
    )


# --------------------------------------------------------------------------- #
# 9. The probes — injectable, exactly like gui/backdrop.py's                   #
# --------------------------------------------------------------------------- #
#
# Every probe is a module-level function so a test can monkeypatch it without a
# matching host (the pattern backdrop.py established with _version_probe /
# _platform_probe, and the reason its whole matrix is testable on any machine).
#
# THE CTYPES QUARANTINE: gui/backdrop.py is the only module in the GUI package
# that may import ctypes or touch DWM. The five native observations below
# (composition, transparency, high contrast, remote session, battery saver) are
# therefore IMPLEMENTED THERE and merely CALLED here, through a local, failure-
# proof, Windows-gated import (see _ask_backdrop). Beat G-B2b, and it is not a
# formality: while these five returned a hardcoded None, the tier on a real
# machine was decided by build + RHI + shell alone — the RDP ceiling was inert,
# the high-contrast FLAT mandate never fired, and every "it degrades safely on
# RDP / high contrast" claim in this project was a claim about unwritten code.

def _platform_probe() -> str:
    return sys.platform


def _windows_build_probe() -> int:
    if sys.platform != "win32":
        return 0
    return int(sys.getwindowsversion().build)   # type: ignore[attr-defined]


def _qt_platform_probe() -> str:
    """Qt's active platform plugin name. PySide6 is imported LAZILY so this
    module stays importable (and unit-testable) with no Qt at all."""
    from PySide6.QtGui import QGuiApplication   # local: keep the module Qt-free

    app = QGuiApplication.instance()
    return "" if app is None else str(app.platformName())


def _rhi_backend_probe() -> str:
    """The RHI backend, from the environment Qt itself reads.

    There is no way to ask for the *effective* backend without a live
    ``QQuickWindow``, so this reports what was REQUESTED. The GlassShell beat —
    which sets the backend itself — should pass ``rhi_backend=`` explicitly
    rather than trust this."""
    if os.environ.get("QT_QUICK_BACKEND", "").strip().lower() in _SOFTWARE_RHI:
        return "software"
    return os.environ.get("QSG_RHI_BACKEND", "").strip().lower()


def _software_rasterizer_probe() -> bool | None:
    """``True`` for an explicit software scenegraph. llvmpipe/swrast detection
    needs a live GL context (``GL_RENDERER``), which this module will not create
    — so it stays ``None`` (unknown) unless the caller knows better."""
    if os.environ.get("QT_QUICK_BACKEND", "").strip().lower() in _SOFTWARE_RHI:
        return True
    return None


def _ask_backdrop(probe: str) -> bool | None:
    """Ask ``gui.backdrop`` — the ctypes quarantine — for ONE native observation
    (beat G-B2b).

    The import is deliberately LOCAL and deliberately Windows-gated:

    * local, because this module must stay importable with no Qt and no ctypes
      at all (the seed inherits it, and ``tests/test_glass_env.py`` pins the
      module-level import list with an AST guard). This is the same pattern
      ``_qt_platform_probe`` and ``_override_probe`` already use — the contract
      never *contains* the mechanism, it *calls* it;
    * Windows-gated, because all five observations are Win32-only. On Linux we do
      not even pay the Qt import to learn that the answer is ``None``.

    Returns ``None`` on any failure at all — a missing API, a denied registry
    key, a ``gui.backdrop`` that will not import, a probe that was monkeypatched
    into something broken. ``None`` is the legal "cannot be asked" (it vetoes
    nothing); it is NOT ``False`` (a positive observation of absence, which
    vetoes) and it is never a guess in the UP direction. This function therefore
    cannot raise — which matters, because :func:`probe_environment` runs from the
    GUI thread and an exception here would degrade the whole decision (and, in
    the worst case, take an unrelated Qt event delivery with it).

    The return value is passed through UNCOERCED on purpose: if a future
    ``gui.backdrop`` returns something that is not ``bool | None``,
    :func:`normalize` sees the garbage and degrades to :data:`SAFE_FLOOR`, which
    is the honest answer and the safe direction. Silently mapping it to ``None``
    here would hide a broken probe behind a legal-looking "unknown".
    """
    if sys.platform != "win32":
        return None
    try:
        from gui import backdrop        # local: ctypes stays quarantined THERE

        return getattr(backdrop, probe)()
    except Exception:
        logger.debug("glass: native probe backdrop.%s is unavailable — the "
                     "observation stays unknown (None)", probe, exc_info=True)
        return None


def _dwm_composition_probe() -> bool | None:
    """``DwmIsCompositionEnabled``. ``False`` ⇒ no ``WINDOW``."""
    return _ask_backdrop("dwm_composition_probe")


def _transparency_probe() -> bool | None:
    """``HKCU\\...\\Themes\\Personalize\\EnableTransparency``. ``False`` ⇒ no
    ``WINDOW`` (the material composes as a flat tint). Absent from the registry
    ⇒ ``None``: a fresh profile that never touched the setting is "cannot be
    asked", and reading it as OFF would kill glass that works."""
    return _ask_backdrop("transparency_probe")


def _high_contrast_probe() -> bool | None:
    """``SystemParametersInfoW(SPI_GETHIGHCONTRAST)``. ``True`` ⇒ ``FLAT``,
    mandatory, outranking everything. There is no Qt API for this and no Linux
    mechanism at all (research §9.5) — on Linux it stays ``None`` and the
    operator override covers that row."""
    return _ask_backdrop("high_contrast_probe")


def _remote_session_probe() -> bool | None:
    """``GetSystemMetrics(SM_REMOTESESSION)``. ``True`` ⇒ ceiling ``TOKEN``.

    The probe that turns SYNTHESIS §7.3 P4's "instant downgrade on RDP" from a
    sentence into a function of the environment. X-forwarding / VNC on Linux is
    not observable this way and stays ``None`` (research §7)."""
    return _ask_backdrop("remote_session_probe")


def _battery_saver_probe() -> bool | None:
    """``GetSystemPowerStatus().SystemStatusFlag``. ``True`` ⇒ no ``WINDOW``
    (Windows battery saver suppresses transparency effects outright)."""
    return _ask_backdrop("battery_saver_probe")


def _composition_interop_probe() -> bool:
    return False    # G5 is unbuilt; COMPOSED must stay unreachable, not unlikely.


def _override_probe() -> str:
    """The persisted operator ceiling. Reads QSettings — which is exactly why it
    is a probe and not part of the pure decision."""
    from gui import app_settings                # local: no import cost, no cycle

    return app_settings.theme_glass_tier()


def _safe(name: str, probe: Callable[[], Any], fallback: Any) -> tuple[Any, bool]:
    """Run one probe. A probe that RAISES is a broken probe: it degrades the
    whole decision to :data:`SAFE_FLOOR` (the brief's fail-safe law). A probe
    that returns a legal ``None`` (= "not observable here") does not."""
    try:
        return probe(), False
    except Exception:
        logger.warning("glass: probe %s() raised — the decision degrades to %s",
                       name, SAFE_FLOOR.name.lower(), exc_info=True)
        return fallback, True


def probe_environment(
    *,
    shell: str = SHELL_CLASSIC,
    scan_active: bool = False,
    rtt_children: Sequence[str] = (),
    user_override: Optional[str] = None,
) -> GlassEnvironment:
    """Build a :class:`GlassEnvironment` from the live host. The ONLY function
    in this module that performs I/O.

    Never raises: every probe is guarded, and a probe that blows up sets
    ``degraded=True`` rather than taking the GUI with it. The caller supplies
    what only it knows (which shell is asking, whether a run is active, this
    window's RTT census); ``user_override=None`` means "read it from QSettings".
    """
    values: dict[str, Any] = {}
    degraded = False

    for name, probe, fallback in (
        ("platform", _platform_probe, ""),
        ("windows_build", _windows_build_probe, 0),
        ("qt_platform", _qt_platform_probe, ""),
        ("rhi_backend", _rhi_backend_probe, ""),
        ("software_rasterizer", _software_rasterizer_probe, None),
        ("dwm_composition", _dwm_composition_probe, None),
        ("transparency_enabled", _transparency_probe, None),
        ("high_contrast", _high_contrast_probe, None),
        ("remote_session", _remote_session_probe, None),
        ("battery_saver", _battery_saver_probe, None),
        ("composition_interop", _composition_interop_probe, False),
    ):
        values[name], broke = _safe(name, probe, fallback)
        degraded = degraded or broke

    if user_override is None:
        values["user_override"], broke = _safe("override", _override_probe, OVERRIDE_AUTO)
        degraded = degraded or broke
    else:
        values["user_override"] = user_override

    values["shell"] = shell
    values["scan_active"] = scan_active
    values["rtt_children"] = tuple(rtt_children)
    values["degraded"] = degraded

    # normalize() catches anything a probe returned that is the wrong TYPE (a
    # probe can be monkeypatched, or a future Qt can change a return type) and
    # degrades on it — so the environment that leaves this function is always
    # well-formed, and decide_tier's own coercion is a second belt, not the only
    # one.
    return normalize(GlassEnvironment(**values))


__all__ = [
    "GlassTier", "SAFE_FLOOR",
    "GlassEnvironment", "TierDecision", "Transition",
    "decide_tier", "explain_tier", "normalize",
    "plan_transition", "plan_transition_for",
    "override_ceiling", "canonical_override",
    "format_truth_log", "probe_environment",
    "OVERRIDE_ALIASES", "CANONICAL_OVERRIDES", "OVERRIDE_AUTO",
    "SHELL_KINDS", "SHELL_CLASSIC", "SHELL_GLASS", "SHELL_CEILINGS",
    "MIN_WINDOWS_MATERIAL_BUILD", "PATH_D_CAPS_AT_TOKEN",
    "DOWNGRADE_DEADLINE_MS", "UPGRADE_HYSTERESIS_S",
    "TRANSITION_NONE", "TRANSITION_APPLY", "TRANSITION_DEFER",
]
