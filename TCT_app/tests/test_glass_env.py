"""The glass contract's test surface — SYNTHESIS §7.1 **rung 0** ("intent").

A green rung 0 never claims rung 1+ truth: NOTHING here proves a pixel. What it
proves is that the DECISION is total, deterministic, monotone, fail-safe, blind
to run state, and that Kaya's four persisted override values still resolve.
That is the entire job of ``gui/glass_env.py``, and it is exactly the job that
can be hammered offscreen ~14 000 environments at a time in under a second.

The four matrix properties (the brief's rung-0 demand):

* **totality** — every input yields a tier; ``decide_tier`` never raises.
* **monotonicity** — removing a capability never RAISES the tier.
* **fail-safe** — an exploding / ``None`` / garbage probe lands on the safe
  floor, never higher.
* **determinism** — same environment ⇒ same tier, with no dict/hash/ordering
  dependence.

Plus the golden table (the ~15 named scenarios), the legacy-alias map, the
transition law (downgrades NEVER queue), and the two constitution guards:
G3 (the material carries no hazard information) and the ctypes quarantine.

Everything is pure Python; ``QT_QPA_PLATFORM=offscreen`` is set only because a
drift guard imports ``gui.backdrop``, which imports Qt.
"""
from __future__ import annotations

import ast
import itertools
import os
import pathlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gui import app_settings, glass_env
from gui.glass_env import (
    CANONICAL_OVERRIDES,
    DOWNGRADE_DEADLINE_MS,
    MIN_WINDOWS_MATERIAL_BUILD,
    OVERRIDE_ALIASES,
    SAFE_FLOOR,
    SHELL_CLASSIC,
    SHELL_GLASS,
    SHELL_KINDS,
    TRANSITION_APPLY,
    TRANSITION_DEFER,
    TRANSITION_NONE,
    UPGRADE_HYSTERESIS_S,
    GlassEnvironment,
    GlassTier,
    canonical_override,
    decide_tier,
    explain_tier,
    format_truth_log,
    override_ceiling,
    plan_transition,
    plan_transition_for,
    probe_environment,
)

pytestmark = pytest.mark.material_contract


# --------------------------------------------------------------------------- #
# Environment builders                                                        #
# --------------------------------------------------------------------------- #

def win11(**kw) -> GlassEnvironment:
    """A modern Win11 desktop with everything switched on — the top of the
    classic ladder."""
    base = dict(
        platform="win32",
        windows_build=26200,
        qt_platform="windows",
        rhi_backend="opengl",
        software_rasterizer=False,
        dwm_composition=True,
        transparency_enabled=True,
        high_contrast=False,
        remote_session=False,
        battery_saver=False,
    )
    base.update(kw)
    return GlassEnvironment(**base)


def linux(**kw) -> GlassEnvironment:
    base = dict(
        platform="linux",
        windows_build=0,
        qt_platform="wayland",
        rhi_backend="",
        software_rasterizer=False,
        high_contrast=False,
        remote_session=False,
    )
    base.update(kw)
    return GlassEnvironment(**base)


# --------------------------------------------------------------------------- #
# 1. The enum — one ladder, ordered, comparable                               #
# --------------------------------------------------------------------------- #

class TestGlassTierEnum:

    def test_the_ladder_is_the_ratified_one(self):
        # SYNTHESIS §3.1, verbatim. Values are frozen: the seed inherits them,
        # QML exports them, and a persisted int must not shift under anyone.
        assert [(t.name, int(t)) for t in GlassTier] == [
            ("FLAT", 0), ("TOKEN", 1), ("WINDOW", 2), ("SCENE", 3), ("COMPOSED", 4),
        ]

    def test_tiers_are_ordered_and_comparable(self):
        assert GlassTier.FLAT < GlassTier.TOKEN < GlassTier.WINDOW
        assert GlassTier.WINDOW < GlassTier.SCENE < GlassTier.COMPOSED
        assert min(GlassTier.SCENE, GlassTier.TOKEN) is GlassTier.TOKEN
        assert max(GlassTier.FLAT, GlassTier.WINDOW) is GlassTier.WINDOW
        assert sorted(GlassTier, reverse=True)[0] is GlassTier.COMPOSED

    def test_the_safe_floor_is_token_not_flat(self):
        # FLAT is a DELIBERATE accessibility look, not the failure look. A probe
        # hiccup must not strip the app's visual identity; TOKEN is opaque,
        # compositor-independent, and passes the readability contract by
        # construction (SYNTHESIS §4.2), so it is safe AND honest.
        assert SAFE_FLOOR is GlassTier.TOKEN
        assert GlassTier.FLAT < SAFE_FLOOR


# --------------------------------------------------------------------------- #
# 2. The deprecation / alias map — Kaya's disk must keep working              #
# --------------------------------------------------------------------------- #

class TestDeprecationMap:

    @pytest.mark.parametrize("legacy", app_settings.GLASS_TIERS)
    def test_every_persisted_legacy_value_maps_to_a_defined_tier(self, legacy):
        # ("auto", "real", "token", "flat") are on Kaya's machine RIGHT NOW.
        assert legacy in OVERRIDE_ALIASES
        assert isinstance(override_ceiling(legacy), GlassTier)

    def test_the_persisted_four_map_exactly_here(self):
        assert override_ceiling("auto") is GlassTier.COMPOSED     # == no ceiling
        assert override_ceiling("real") is GlassTier.WINDOW       # the real OS material
        assert override_ceiling("token") is GlassTier.TOKEN
        assert override_ceiling("flat") is GlassTier.FLAT

    def test_real_never_becomes_an_upgrade(self):
        # The one judgment call in the map. "real" could plausibly have meant
        # "give me the best glass you have" -> COMPOSED. It must not: an
        # override is a CEILING, and an operator who explicitly picked a value
        # may never silently receive a HIGHER tier than the word he chose.
        assert override_ceiling("real") < GlassTier.SCENE
        glass_shell = win11(shell=SHELL_GLASS, user_override="real")
        assert decide_tier(glass_shell) is GlassTier.WINDOW
        assert decide_tier(win11(shell=SHELL_GLASS, user_override="auto")) is GlassTier.SCENE

    @pytest.mark.parametrize("spelling,expected", [
        ("t2", GlassTier.FLAT), ("t1", GlassTier.TOKEN), ("t0", GlassTier.WINDOW),
        ("r0", GlassTier.FLAT), ("r1", GlassTier.TOKEN),
        ("r2", GlassTier.WINDOW), ("r3", GlassTier.SCENE),
        ("preblend", GlassTier.TOKEN), ("real_backdrop", GlassTier.WINDOW),
    ])
    def test_the_three_dead_council_vocabularies_resolve(self, spelling, expected):
        # SYNTHESIS §3.3. Where the table maps a rung onto TWO tiers
        # ("WINDOW·SCENE"), we take the LOWER: ambiguity resolves downward.
        assert override_ceiling(spelling) is expected

    @pytest.mark.parametrize("raw", ["AUTO", " Real ", "TOKEN\t", "  flat"])
    def test_case_and_whitespace_insensitive(self, raw):
        assert override_ceiling(raw) is override_ceiling(raw.strip().lower())

    @pytest.mark.parametrize("absent", [None, "", "   "])
    def test_absent_override_means_auto_not_a_downgrade(self, absent):
        # QSettings returns None for an unset key. "No preference" is the
        # shipped default and must not be read as "cap me at TOKEN".
        assert override_ceiling(absent) is GlassTier.COMPOSED

    @pytest.mark.parametrize("unknown", [
        "toklen", "ultra", "mica", "none", "T3", "glass", "REAL_GLASS",
    ])
    def test_unknown_spelling_falls_to_the_safe_floor_never_higher(self, unknown):
        # A value written by a future build, or a typo. Deterministic, loud,
        # and never an upgrade.
        assert override_ceiling(unknown) is SAFE_FLOOR

    @pytest.mark.parametrize("garbage", [42, 3.5, object(), [], {}, True])
    def test_non_string_override_falls_to_the_safe_floor(self, garbage):
        assert override_ceiling(garbage) is SAFE_FLOOR

    def test_canonical_override_is_a_migration_name_map(self):
        assert canonical_override("real") == "window"
        assert canonical_override("T0") == "window"
        assert canonical_override("auto") == "auto"
        assert canonical_override(None) == "auto"
        assert canonical_override("flat") == "flat"
        assert canonical_override("garbage") == "token"

    def test_canonical_vocabulary_is_a_subset_of_the_alias_map(self):
        for name in CANONICAL_OVERRIDES:
            assert name in OVERRIDE_ALIASES

    def test_every_persisted_value_still_boots_the_app(self):
        # The load-bearing promise: an override on disk never crashes, never
        # wedges, and never jumps above what "auto" would have given.
        auto = decide_tier(win11(user_override="auto"))
        for legacy in app_settings.GLASS_TIERS:
            tier = decide_tier(win11(user_override=legacy))
            assert isinstance(tier, GlassTier)
            assert tier <= auto


# --------------------------------------------------------------------------- #
# 3. THE MATRIX — the cartesian product, ~14k environments                    #
# --------------------------------------------------------------------------- #

# The product axes. `dwm_composition` is deliberately NOT one: its only effect
# is to veto WINDOW, which is precisely what `transparency_enabled` already
# exercises across the whole product — so as an axis it would double the matrix
# to buy a duplicate. It stays in `_LESS_CAPABLE` below, which means
# monotonicity still quantifies over it for EVERY environment, and the golden
# table + fail-safe class pin its behaviour directly. That keeps the bucket
# inside its < 20 s budget on a contended laptop, which is a real gate.
_AXES = {
    "platform": ("win32", "linux"),
    "windows_build": (0, 19045, 26200),            # none / Win10 / Win11 26H1
    "qt_platform": ("windows", "offscreen", "xcb"),
    "rhi_backend": ("opengl", "d3d11", "software"),
    "software_rasterizer": (False, True),
    "transparency_enabled": (False, True),
    "high_contrast": (False, True),
    "remote_session": (False, True),
    "shell": (SHELL_CLASSIC, SHELL_GLASS),
    "user_override": ("auto", "real", "token", "flat"),
}

# Flipping a field from the MORE-capable value to the LESS-capable one. This is
# the formal statement of "removing a capability" that the monotonicity property
# is quantified over. rhi_backend/platform/qt_platform are deliberately absent:
# they are categorical (d3d11 is not "less" than opengl in general, it is merely
# worse for OUR translucent-QQuickWindow path), so they are exercised for
# totality/determinism but not for monotonicity.
_LESS_CAPABLE = {
    "windows_build": 0,
    "software_rasterizer": True,
    "dwm_composition": False,
    "transparency_enabled": False,
    "high_contrast": True,
    "remote_session": True,
    "battery_saver": True,
    "shell": SHELL_CLASSIC,
    "composition_interop": False,
    "rtt_children": ("GLViewWidget",),
}


def _matrix():
    names = list(_AXES)
    for combo in itertools.product(*(_AXES[n] for n in names)):
        yield GlassEnvironment(**dict(zip(names, combo)))


class TestMatrix:

    def test_matrix_is_big_enough_to_mean_something(self):
        n = 1
        for values in _AXES.values():
            n *= len(values)
        assert n == len(list(_matrix())) == 6912

    def test_totality_determinism_and_the_standing_invariants(self):
        """ONE pass over the product, asserting every law that is a property of
        a single environment.

        Deliberately one loop rather than five prettier ones: each extra pass
        costs a full re-decide of ~14k environments, and the material_contract
        bucket has a hard < 20 s budget it must fit even on a contended laptop.
        """
        for env in _matrix():
            tier = decide_tier(env)

            # totality — a tier, always, no exception
            assert isinstance(tier, GlassTier)

            # determinism — same env in, same tier out; and the explanation
            # agrees with the shorthand. No dict/hash ordering may leak in.
            again = decide_tier(GlassEnvironment(**vars(env)))
            assert again is tier
            decision = explain_tier(env)
            assert decision.tier is tier
            assert decision.ceilings == tuple(sorted(decision.ceilings))

            # G3, applied to the run: the TARGET tier is a property of the
            # MACHINE. Only the TIMING of reaching it is a property of the run
            # (plan_transition). If the tier itself moved with scan state, the
            # material would be carrying run-state information — one short step
            # from carrying hazard information, which is forbidden outright.
            assert decide_tier(
                GlassEnvironment(**{**vars(env), "scan_active": True})) is tier

            # 353072f finding 1: a live QOpenGLWidget child does NOT kill its
            # window's DWM material on Qt 6.11.1. The census is observed and
            # logged; it is not decisive.
            assert decide_tier(GlassEnvironment(
                **{**vars(env), "rtt_children": ("GLViewWidget",)})) is tier

            # an override is a CEILING, never a floor — it can only push down
            assert tier <= decide_tier(
                GlassEnvironment(**{**vars(env), "user_override": "auto"}))

            # the floor always exists, the answer is always something the host
            # can actually paint, and nothing renders above the cap
            assert GlassTier.FLAT in decision.renderable
            assert SAFE_FLOOR in decision.renderable
            assert tier in decision.renderable
            assert tier <= decision.cap

            # high contrast outranks EVERYTHING (SYNTHESIS §3.1)
            if env.high_contrast:
                assert tier is GlassTier.FLAT

            # a remote session is capped at TOKEN, by policy (research §7)
            if env.remote_session:
                assert tier <= SAFE_FLOOR

            # a software rasterizer never costs a measurement (SYNTHESIS §4.3)
            if env.software_rasterizer or env.rhi_backend == "software":
                assert tier <= SAFE_FLOOR

            # WINDOW — the real OS material — is Windows-only and 22H2+; there
            # is no Linux implementation we can ship (research §3.5). Asserted
            # on RENDERABLE, not on `tier >= WINDOW`: the ladder is a SET, not a
            # staircase every host climbs in order. SCENE sits above WINDOW
            # numerically but requires none of it — its frost is app-owned — so
            # a Linux (or Win10) GlassShell legitimately reaches SCENE with no
            # WINDOW rung beneath it. That property is the whole argument for
            # having built the frost ourselves.
            if GlassTier.WINDOW in decision.renderable:
                assert env.platform == "win32"
                assert env.qt_platform == "windows"
                assert env.windows_build >= MIN_WINDOWS_MATERIAL_BUILD

            # SCENE needs the GlassShell to exist at all
            if GlassTier.SCENE in decision.renderable:
                assert env.shell == SHELL_GLASS
                # ...and on Windows it needs the OpenGL RHI: D3D11 renders a
                # translucent QQuickWindow FLAT WHITE (353072f finding 3).
                if env.platform == "win32":
                    assert env.rhi_backend == "opengl"

            # COMPOSED is UNBUILT and must therefore be unreachable
            assert tier < GlassTier.COMPOSED

    def test_monotonicity_removing_a_capability_never_raises_the_tier(self):
        """THE property. Quantified over the whole product × every capability.

        A flip to the value the field ALREADY holds is skipped — it re-decides
        an identical environment and proves nothing, and at ~14k envs those
        no-ops are most of the runtime.
        """
        for env in _matrix():
            before = decide_tier(env)
            for name, worse in _LESS_CAPABLE.items():
                if getattr(env, name) == worse:
                    continue
                after = decide_tier(GlassEnvironment(**{**vars(env), name: worse}))
                assert after <= before, (
                    f"{name} -> {worse!r} RAISED the tier "
                    f"({before.name} -> {after.name}) for {env}")

    def test_path_d_is_refuted_and_the_undo_flag_is_still_there(self):
        # The census-blindness itself is asserted per-environment in the matrix
        # pass above; this pins the flag that would undo it if the bench ever
        # overturns 353072f's single-host measurement.
        assert glass_env.PATH_D_CAPS_AT_TOKEN is False


# --------------------------------------------------------------------------- #
# 4. Fail-safe — garbage, None, and exploding probes all land DOWN            #
# --------------------------------------------------------------------------- #

class TestFailSafe:

    @pytest.mark.parametrize("field,garbage", [
        ("platform", None), ("platform", 42), ("platform", object()),
        ("windows_build", None), ("windows_build", "26200"),
        ("windows_build", -1), ("windows_build", 3.5), ("windows_build", True),
        ("qt_platform", None), ("qt_platform", 7),
        ("rhi_backend", None), ("rhi_backend", []),
        ("software_rasterizer", "yes"), ("software_rasterizer", 1),
        ("dwm_composition", "true"), ("transparency_enabled", 0),
        ("high_contrast", "on"), ("remote_session", "1"),
        ("battery_saver", 0.0), ("composition_interop", None),
        ("rtt_children", "GLViewWidget"), ("rtt_children", [None]),
        ("rtt_children", 3),
        ("shell", "qml"), ("shell", None), ("shell", 5),
        ("user_override", 42), ("user_override", object()),
        ("scan_active", "yes"), ("degraded", "no"),
    ])
    def test_garbage_in_any_field_degrades_to_the_safe_floor_never_higher(
            self, field, garbage):
        # Start from the BEST possible environment, so a garbage field can only
        # be observed as a downgrade.
        best = win11(shell=SHELL_GLASS)
        assert decide_tier(best) is GlassTier.SCENE

        broken = GlassEnvironment(**{**vars(best), field: garbage})
        tier = decide_tier(broken)
        assert isinstance(tier, GlassTier)
        assert tier <= SAFE_FLOOR
        assert explain_tier(broken).degraded is True

    def test_a_bare_environment_is_the_guaranteed_floor(self):
        assert decide_tier(GlassEnvironment()) is SAFE_FLOOR

    def test_an_exploding_probe_degrades_the_whole_decision(self, monkeypatch):
        def boom():
            raise RuntimeError("dwmapi went to lunch")

        monkeypatch.setattr(glass_env, "_platform_probe", lambda: "win32")
        monkeypatch.setattr(glass_env, "_windows_build_probe", lambda: 26200)
        monkeypatch.setattr(glass_env, "_qt_platform_probe", lambda: "windows")
        monkeypatch.setattr(glass_env, "_transparency_probe", boom)

        env = probe_environment(user_override="auto")
        assert env.degraded is True
        assert decide_tier(env) is SAFE_FLOOR     # never WINDOW, despite the build

    @pytest.mark.parametrize("probe", [
        "_platform_probe", "_windows_build_probe", "_qt_platform_probe",
        "_rhi_backend_probe", "_software_rasterizer_probe",
        "_dwm_composition_probe", "_transparency_probe", "_high_contrast_probe",
        "_remote_session_probe", "_battery_saver_probe",
        "_composition_interop_probe", "_override_probe",
    ])
    def test_probe_environment_never_raises_whatever_a_probe_does(
            self, probe, monkeypatch):
        def boom():
            raise OSError(f"{probe} exploded")

        monkeypatch.setattr(glass_env, probe, boom)
        env = probe_environment()                 # must NOT raise
        assert env.degraded is True
        assert decide_tier(env) <= SAFE_FLOOR

    # NOT 42: a bare int is a perfectly coercible (if absurd) build number, and
    # it degrades nothing — it simply falls below the material floor. These are
    # the values a build probe cannot honestly be read as at all.
    @pytest.mark.parametrize("junk", [None, object(), "26200", 3.5, -1, True])
    def test_a_probe_returning_garbage_degrades_too(self, junk, monkeypatch):
        monkeypatch.setattr(glass_env, "_windows_build_probe", lambda: junk)
        env = probe_environment(user_override="auto")
        assert env.degraded is True
        assert decide_tier(env) <= SAFE_FLOOR

    def test_a_merely_absurd_build_number_is_not_garbage_it_is_just_too_old(
            self, monkeypatch):
        monkeypatch.setattr(glass_env, "_platform_probe", lambda: "win32")
        monkeypatch.setattr(glass_env, "_qt_platform_probe", lambda: "windows")
        monkeypatch.setattr(glass_env, "_windows_build_probe", lambda: 42)
        env = probe_environment(user_override="auto")
        assert env.degraded is False
        assert decide_tier(env) is SAFE_FLOOR

    def test_unknown_tristates_do_not_veto_the_material(self):
        """The one place ``None`` is deliberately NOT treated as ``False``.

        A tri-state ``None`` means "this host cannot be asked" (Linux has no
        high-contrast API at all; the native transparency probe is not wired
        yet). Vetoing on unknown would force FLAT on every Linux box and kill
        the glass that demonstrably works on Kaya's machine today. Nothing
        hazardous follows from a wrong guess: the underlay law degrades a
        material that does not composite to the opaque token pre-blend.
        """
        unknowable = win11(
            dwm_composition=None, transparency_enabled=None,
            high_contrast=None, remote_session=None, battery_saver=None,
            software_rasterizer=None)
        assert decide_tier(unknowable) is GlassTier.WINDOW
        assert explain_tier(unknowable).degraded is False   # unknown != broken

    def test_a_positive_observation_of_absence_does_veto(self):
        assert decide_tier(win11(transparency_enabled=False)) is SAFE_FLOOR
        assert decide_tier(win11(dwm_composition=False)) is SAFE_FLOOR
        assert decide_tier(win11(battery_saver=True)) is SAFE_FLOOR


# --------------------------------------------------------------------------- #
# 5. The golden table — the named scenarios, each one a sentence              #
# --------------------------------------------------------------------------- #

GOLDEN: list[tuple[str, GlassEnvironment, GlassTier]] = [
    ("modern Win11 desktop, transparency ON",
     win11(), GlassTier.WINDOW),

    ("Win11, OS transparency effects OFF",
     win11(transparency_enabled=False), GlassTier.TOKEN),

    ("Win11, high contrast ON — mandatory, outranks everything",
     win11(high_contrast=True), GlassTier.FLAT),

    ("Win11 over RDP — policy: glass never eats a scan point's bandwidth",
     win11(remote_session=True), GlassTier.TOKEN),

    ("Windows 10 / pre-22621 — TOKEN forever, no ACCENT_POLICY fallback",
     win11(windows_build=19045), GlassTier.TOKEN),

    ("Win11 on battery saver — the OS suppresses the material",
     win11(battery_saver=True), GlassTier.TOKEN),

    ("Linux / X11 (xcb), classic shell — WINDOW has no Linux implementation",
     linux(qt_platform="xcb"), GlassTier.TOKEN),

    ("Linux / Wayland, classic shell",
     linux(qt_platform="wayland"), GlassTier.TOKEN),

    ("Linux / Wayland, GlassShell — SCENE is app-owned and needs no compositor",
     linux(qt_platform="wayland", shell=SHELL_GLASS), GlassTier.SCENE),

    ("Linux VM on llvmpipe, GlassShell — capped to protect FastDAQ",
     linux(qt_platform="wayland", shell=SHELL_GLASS, software_rasterizer=True),
     GlassTier.TOKEN),

    ("offscreen / CI — the byte-identical floor the whole test spine rests on",
     win11(qt_platform="offscreen"), GlassTier.TOKEN),

    ("Windows GlassShell on the OpenGL RHI — real glass (353072f finding 3)",
     win11(shell=SHELL_GLASS, rhi_backend="opengl"), GlassTier.SCENE),

    ("Windows GlassShell on the D3D11 RHI — measured FLAT WHITE, so refused",
     win11(shell=SHELL_GLASS, rhi_backend="d3d11"), GlassTier.WINDOW),

    ("Windows GlassShell, RHI unknown — the Windows default is the broken one",
     win11(shell=SHELL_GLASS, rhi_backend=""), GlassTier.WINDOW),

    # A judgment call, made visible on purpose. SYNTHESIS §2.2.3 says "Win10 =
    # TOKEN, full stop" — but it says it in the section about the DWM/ACCENT
    # low-level tier, i.e. "do not build a Win10 OS-material fallback". It is
    # NOT a ban on our OWN frost: SCENE is app-owned, needs no compositor, and
    # Linux gets it with no material underneath at all. Denying Win10 the same
    # baked frost we hand Ubuntu would be incoherent. So: Win10 has no WINDOW
    # rung (the OS material is refused, exactly as ratified) and still reaches
    # SCENE under the GlassShell.
    ("Windows 10 + GlassShell — no OS material, but our own frost still paints",
     win11(windows_build=19045, shell=SHELL_GLASS), GlassTier.SCENE),

    ("classic cockpit with a live GL child — path D is REFUTED, glass survives",
     win11(rtt_children=("GLViewWidget",)), GlassTier.WINDOW),

    ("operator override 'auto' (legacy, persisted)",
     win11(user_override="auto"), GlassTier.WINDOW),

    ("operator override 'real' (legacy, persisted) — a ceiling, not a promotion",
     win11(user_override="real"), GlassTier.WINDOW),

    ("operator override 'token' (legacy, persisted)",
     win11(user_override="token"), GlassTier.TOKEN),

    ("operator override 'flat' (legacy, persisted) — the escape hatch",
     win11(user_override="flat"), GlassTier.FLAT),

    ("operator override from a future build — unknown, so: the floor",
     win11(user_override="hyperglass"), GlassTier.TOKEN),

    ("a probe exploded — fail-safe direction is DOWN",
     win11(degraded=True), GlassTier.TOKEN),

    ("a probe exploded WHILE high contrast is on — still FLAT, still lower",
     win11(degraded=True, high_contrast=True), GlassTier.FLAT),
]


class TestGoldenTable:

    @pytest.mark.parametrize("name,env,expected",
                             GOLDEN, ids=[g[0] for g in GOLDEN])
    def test_named_scenario(self, name, env, expected):
        assert decide_tier(env) is expected, format_truth_log(explain_tier(env))

    def test_the_golden_table_covers_every_tier_it_can_reach(self):
        reached = {decide_tier(env) for _, env, _ in GOLDEN}
        assert reached == {GlassTier.FLAT, GlassTier.TOKEN,
                           GlassTier.WINDOW, GlassTier.SCENE}
        # COMPOSED is deliberately absent: G5 is unbuilt, so the tier must be
        # unreachable, not merely unlikely.

    def test_composed_needs_the_unbuilt_interop_layer_to_exist_at_all(self):
        ready = win11(shell=SHELL_GLASS, rhi_backend="opengl")
        assert decide_tier(ready) is GlassTier.SCENE
        assert decide_tier(GlassEnvironment(**{**vars(ready),
                                               "composition_interop": True})) \
            is GlassTier.COMPOSED


# --------------------------------------------------------------------------- #
# 6. THE TRANSITION LAW — downgrades never queue (SYNTHESIS §5 row 1)         #
# --------------------------------------------------------------------------- #

class TestTransitionPolicy:

    def test_downgrades_are_NEVER_queued_not_once_in_the_whole_product(self):
        """The law, quantified over every (current, target, scan_active) triple
        that exists. A dead-glass window must be recoverable within one
        event-loop turn, mid-scan or not."""
        for current, target, scan in itertools.product(GlassTier, GlassTier,
                                                       (False, True)):
            plan = plan_transition(current, target, scan)
            if target < current:
                assert plan.action == TRANSITION_APPLY
                assert plan.action != TRANSITION_DEFER
                assert plan.is_downgrade
                assert plan.deadline_ms == DOWNGRADE_DEADLINE_MS
                assert plan.hysteresis_s is None

    def test_the_downgrade_deadline_is_one_event_loop_turn(self):
        assert DOWNGRADE_DEADLINE_MS <= 200

    def test_upgrades_wait_for_scan_idle(self):
        for current, target in itertools.product(GlassTier, GlassTier):
            if target <= current:
                continue
            busy = plan_transition(current, target, True)
            assert busy.action == TRANSITION_DEFER
            assert busy.is_upgrade
            assert busy.hysteresis_s == UPGRADE_HYSTERESIS_S

            idle = plan_transition(current, target, False)
            assert idle.action == TRANSITION_APPLY
            assert idle.hysteresis_s == UPGRADE_HYSTERESIS_S
            assert idle.deadline_ms is None

    def test_no_move_is_a_legitimate_answer(self):
        for tier in GlassTier:
            for scan in (False, True):
                plan = plan_transition(tier, tier, scan)
                assert plan.action == TRANSITION_NONE
                assert plan.direction == "none"

    def test_totality_every_triple_yields_a_plan(self):
        for current, target, scan in itertools.product(GlassTier, GlassTier,
                                                       (False, True)):
            plan = plan_transition(current, target, scan)
            assert plan.action in (TRANSITION_NONE, TRANSITION_APPLY, TRANSITION_DEFER)
            assert plan.direction in ("none", "down", "up")
            assert isinstance(plan.target, GlassTier)

    @pytest.mark.parametrize("junk", [None, "token", object(), -1, 99, 3.5])
    def test_garbage_tiers_never_raise(self, junk):
        assert isinstance(plan_transition(junk, GlassTier.FLAT).target, GlassTier)
        assert isinstance(plan_transition(GlassTier.SCENE, junk).target, GlassTier)
        assert plan_transition(junk, junk).action == TRANSITION_NONE

    def test_plan_transition_for_walks_the_environment(self):
        # A live cockpit on WINDOW; the operator drags the machine into an RDP
        # session mid-scan. The tier target drops to TOKEN and the move is
        # IMMEDIATE despite the running scan.
        env = win11(remote_session=True, scan_active=True)
        plan = plan_transition_for(GlassTier.WINDOW, env)
        assert plan.target is GlassTier.TOKEN
        assert plan.action == TRANSITION_APPLY
        assert plan.deadline_ms == DOWNGRADE_DEADLINE_MS

        # ...and the reverse (RDP disconnects mid-scan) waits for idle.
        back = plan_transition_for(GlassTier.TOKEN, win11(scan_active=True))
        assert back.target is GlassTier.WINDOW
        assert back.action == TRANSITION_DEFER

    def test_scan_active_gates_only_the_timing_never_the_target(self):
        idle = plan_transition_for(GlassTier.TOKEN, win11(scan_active=False))
        busy = plan_transition_for(GlassTier.TOKEN, win11(scan_active=True))
        assert idle.target is busy.target is GlassTier.WINDOW
        assert idle.action != busy.action


# --------------------------------------------------------------------------- #
# 7. The truth log — one greppable line, frozen so it cannot drift            #
# --------------------------------------------------------------------------- #

class TestTruthLog:

    def test_the_line_carries_every_input_that_decided_it(self):
        env = win11(rtt_children=("GLViewWidget",), user_override="auto")
        line = format_truth_log(explain_tier(env), window="main", reason="apply")
        for token in ("glass:", "tier=window", "window=main", "build=26200",
                      "remote=0", "transparency=1", "hc=0", "saver=0",
                      "census=rtt:GLViewWidget", "override=auto", "cap="):
            assert token in line, line

    def test_unknown_is_visibly_different_from_off(self):
        # "we looked and it was off" and "we cannot look here" are different
        # facts, and an operator debugging a white window deserves to know which.
        line = format_truth_log(explain_tier(GlassEnvironment(platform="linux")))
        assert "hc=?" in line and "transparency=?" in line

    def test_a_degraded_decision_says_so_out_loud(self):
        line = format_truth_log(explain_tier(win11(windows_build="banana")))
        assert "DEGRADED" in line
        assert "tier=token" in line

    def test_the_binding_ceiling_is_named(self):
        d = explain_tier(win11(user_override="flat"))
        assert "override" in d.binding
        assert "high_contrast" in explain_tier(win11(high_contrast=True)).binding


# --------------------------------------------------------------------------- #
# 8. Constitution guards — G3, and the ctypes quarantine                      #
# --------------------------------------------------------------------------- #

_MODULE = pathlib.Path(glass_env.__file__)


class TestConstitution:

    def test_the_material_carries_no_hazard_information(self):
        """SYNTHESIS §4.1 G3 / §5 row 2 — Baldr's alarm-de-glass rule is KILLED.

        No field of the environment may name a hazard, an alarm, an error or an
        armed state. If one ever appears, the tier could encode safety meaning,
        and an operator on a frostless RDP session could misread a perfectly
        healthy machine as a standing alarm. This test is the tripwire.
        """
        forbidden = ("alarm", "error", "danger", "hazard", "trip", "armed",
                     "fault", "interlock", "estop", "abort", "safety")
        names = [f.lower() for f in GlassEnvironment.__dataclass_fields__]
        for name in names:
            for word in forbidden:
                assert word not in name, (
                    f"GlassEnvironment.{name} smells like hazard state — the "
                    f"material must carry ZERO hazard information (G3)")

    def test_the_contract_module_never_imports_ctypes_or_qt_at_module_level(self):
        """gui/backdrop.py is the ONLY module in the GUI package allowed to
        import ctypes / touch DWM, and the contract must stay a pure, Qt-free,
        importable-anywhere function so the seed can inherit it."""
        tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
        top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        imported: list[str] = []
        for node in top_level:
            if isinstance(node, ast.Import):
                imported += [a.name.split(".")[0] for a in node.names]
            elif node.module:
                imported.append(node.module.split(".")[0])
        assert "ctypes" not in imported, "ctypes stays quarantined in gui/backdrop.py"
        assert "PySide6" not in imported, (
            "the contract must import cleanly with no Qt — the probes import "
            "PySide6 lazily on purpose")

    def test_decide_tier_touches_no_module_state(self):
        # Pure means pure: the same environment decided a thousand times, with
        # other decisions interleaved, cannot drift.
        env = win11(shell=SHELL_GLASS)
        first = decide_tier(env)
        for other in _AXES["user_override"]:
            decide_tier(GlassEnvironment(**{**vars(env), "user_override": other}))
        assert decide_tier(env) is first

    def test_the_build_floor_does_not_drift_from_backdrop(self):
        from gui import backdrop

        assert MIN_WINDOWS_MATERIAL_BUILD == backdrop._MIN_SUPPORTED_BUILD

    def test_shell_ceilings_cover_every_shell_kind(self):
        for kind in SHELL_KINDS:
            assert kind in glass_env.SHELL_CEILINGS
        assert glass_env.SHELL_CEILINGS[SHELL_CLASSIC] is GlassTier.WINDOW
        assert glass_env.SHELL_CEILINGS[SHELL_GLASS] is GlassTier.COMPOSED


# --------------------------------------------------------------------------- #
# 9. probe_environment on the live (offscreen) host                           #
# --------------------------------------------------------------------------- #

class TestProbeEnvironment:

    def test_the_test_host_itself_resolves_to_the_offscreen_floor(self):
        # The suite runs offscreen. Whatever machine this is, the honest answer
        # is TOKEN — and that is what makes rungs 0-3 compositor-independent.
        #
        # ``<=``, not ``is``, since G-B2b wired the probes: this suite now reads
        # the REAL host, and a developer running it on a high-contrast Windows
        # desktop legitimately decides FLAT (which is LOWER, so the invariant that
        # actually matters — never above the floor — still holds exactly).
        env = probe_environment(user_override="auto")
        assert env.degraded is False
        assert decide_tier(env) <= SAFE_FLOOR

    def test_the_caller_supplies_what_only_it_knows(self):
        env = probe_environment(shell=SHELL_GLASS, scan_active=True,
                                rtt_children=["GLViewWidget"],
                                user_override="token")
        assert env.shell == SHELL_GLASS
        assert env.scan_active is True
        assert env.rtt_children == ("GLViewWidget",)
        assert env.user_override == "token"

    def test_the_native_probes_are_tri_state_and_never_lie(self):
        """G-B2b: the five native probes are WIRED (``gui.backdrop``, the ctypes
        quarantine) — they used to be a hardcoded ``None``.

        This runs on whatever host the suite is on, so it cannot assert a VALUE.
        What it asserts is the type contract the whole fail-safe story rests on:
        each one is ``True``, ``False`` or ``None`` — never a string, never an
        int, never an exception — and ``None`` (Linux, a missing API, a denied
        key) is preserved as the legal "cannot be asked" rather than being
        guessed into a ``False`` that would veto, or a ``True`` that would lie
        upward."""
        env = probe_environment(user_override="auto")
        for field in ("dwm_composition", "transparency_enabled", "high_contrast",
                      "remote_session", "battery_saver"):
            value = getattr(env, field)
            assert value is None or isinstance(value, bool), f"{field}={value!r}"
        assert env.degraded is False
        # COMPOSED stays unbuilt and therefore unreachable, wiring or not.
        assert env.composition_interop is False

    def test_the_probes_are_all_unknown_on_a_non_windows_host(self, monkeypatch):
        """All five observations are Win32-only. On Linux the contract must not
        even pay the ``gui.backdrop`` import to learn that — and it must not
        invent a ``False`` (which would veto the material) either."""
        monkeypatch.setattr(glass_env.sys, "platform", "linux")

        env = probe_environment(user_override="auto")

        assert env.dwm_composition is None
        assert env.transparency_enabled is None
        assert env.high_contrast is None
        assert env.remote_session is None
        assert env.battery_saver is None
        assert env.degraded is False           # unknown is NOT broken

    def test_a_native_probe_that_explodes_is_an_unknown_not_a_crash(self, monkeypatch):
        """``gui.backdrop``'s probes are written never to raise — but this pins
        the belt UNDER them: if one ever does (a future ctypes signature change,
        a hostile mock), the contract answers ``None`` and the GUI keeps running.
        A probe that throws must not be able to take the app down."""
        from gui import backdrop

        def boom():
            raise OSError("user32 went to lunch")

        monkeypatch.setattr(glass_env.sys, "platform", "win32")
        monkeypatch.setattr(backdrop, "high_contrast_probe", boom)
        monkeypatch.setattr(backdrop, "remote_session_probe", boom)

        assert glass_env._high_contrast_probe() is None
        assert glass_env._remote_session_probe() is None

    def test_an_injected_probe_set_reaches_the_window_tier(self, monkeypatch):
        """The full injectable path, end to end: the environment on Kaya's actual
        machine."""
        monkeypatch.setattr(glass_env, "_platform_probe", lambda: "win32")
        monkeypatch.setattr(glass_env, "_windows_build_probe", lambda: 26200)
        monkeypatch.setattr(glass_env, "_qt_platform_probe", lambda: "windows")
        monkeypatch.setattr(glass_env, "_dwm_composition_probe", lambda: True)
        monkeypatch.setattr(glass_env, "_transparency_probe", lambda: True)
        monkeypatch.setattr(glass_env, "_high_contrast_probe", lambda: False)
        monkeypatch.setattr(glass_env, "_remote_session_probe", lambda: False)
        monkeypatch.setattr(glass_env, "_battery_saver_probe", lambda: False)

        env = probe_environment(user_override="auto")
        assert env.degraded is False
        assert decide_tier(env) is GlassTier.WINDOW
        assert "tier=window" in format_truth_log(explain_tier(env))


# --------------------------------------------------------------------------- #
# 10. THE LADDER ACTUALLY MOVES (beat G-B2b)                                   #
#                                                                              #
# Section 3's matrix proves the DECISION honours the RDP ceiling and the        #
# high-contrast mandate. It proves nothing about the machine, because until      #
# G-B2b the five native probes returned a hardcoded None: on a real host the     #
# tier was decided by build + RHI + shell ALONE, so both rules were inert.       #
#                                                                               #
# These tests drive the WHOLE wired path — glass_env's delegating probe → the    #
# lazy import → gui.backdrop's real probe code — and fake only the five ctypes/   #
# winreg PRIMITIVES at the very bottom. Nothing here touches DWM, user32 or the  #
# registry; everything above the primitive is the shipping code.                 #
# --------------------------------------------------------------------------- #

def _wire_win11(monkeypatch, *, remote=0, high_contrast=0, transparency=1,
                composition=True, power_flag=0):
    """A Win11 26H1 host that would otherwise reach WINDOW, with the five native
    primitives under our control. (``glass_env.sys`` and ``backdrop.sys`` are the
    same module object — one patch covers both, and it keeps the test honest on a
    Linux runner too.)"""
    from gui import backdrop

    monkeypatch.setattr(glass_env.sys, "platform", "win32")
    monkeypatch.setattr(glass_env, "_platform_probe", lambda: "win32")
    monkeypatch.setattr(glass_env, "_windows_build_probe", lambda: 26200)
    monkeypatch.setattr(glass_env, "_qt_platform_probe", lambda: "windows")

    monkeypatch.setattr(backdrop, "_system_metric",
                        lambda index: remote if index == backdrop.SM_REMOTESESSION else 0)
    monkeypatch.setattr(backdrop, "_high_contrast_flags", lambda: high_contrast)
    monkeypatch.setattr(backdrop, "_transparency_setting", lambda: transparency)
    monkeypatch.setattr(backdrop, "_dwm_composition_enabled", lambda: composition)
    monkeypatch.setattr(backdrop, "_power_status_flag", lambda: power_flag)
    return backdrop


class TestTheLadderActuallyMoves:

    def test_the_control_a_healthy_win11_host_reaches_window(self, monkeypatch):
        # Without this, the two proofs below could pass vacuously (everything
        # lands on TOKEN when nothing works).
        _wire_win11(monkeypatch)
        env = probe_environment(user_override="auto")

        assert env.remote_session is False
        assert env.high_contrast is False
        assert env.transparency_enabled is True
        assert env.dwm_composition is True
        assert env.battery_saver is False
        assert decide_tier(env) is GlassTier.WINDOW

    def test_a_remote_session_caps_the_tier_at_token(self, monkeypatch):
        """PROOF 1 — the RDP ceiling, executed. ``GetSystemMetrics`` reports a
        Terminal Services session; the same host that just reached WINDOW must
        now cap at TOKEN, and the truth log must NAME the reason."""
        _wire_win11(monkeypatch, remote=1)

        env = probe_environment(user_override="auto")
        decision = explain_tier(env)

        assert env.remote_session is True
        assert decision.tier is GlassTier.TOKEN
        assert "remote_session" in decision.binding
        assert "remote=1" in format_truth_log(decision)

    def test_high_contrast_forces_flat(self, monkeypatch):
        """PROOF 2 — the accessibility mandate, executed. ``SPI_GETHIGHCONTRAST``
        reports the feature ON; the tier must be FLAT, which outranks every other
        ceiling (it is the bottom of the ladder, so ``min()`` does the
        outranking)."""
        _wire_win11(monkeypatch, high_contrast=1)

        env = probe_environment(user_override="auto")
        decision = explain_tier(env)

        assert env.high_contrast is True
        assert decision.tier is GlassTier.FLAT
        assert "high_contrast" in decision.binding
        assert "hc=1" in format_truth_log(decision)

    def test_high_contrast_outranks_even_an_operator_who_asked_for_glass(
            self, monkeypatch):
        _wire_win11(monkeypatch, high_contrast=1)
        assert decide_tier(probe_environment(user_override="real")) is GlassTier.FLAT

    def test_high_contrast_beats_rdp_because_flat_is_lower_than_token(
            self, monkeypatch):
        _wire_win11(monkeypatch, high_contrast=1, remote=1)
        assert decide_tier(probe_environment(user_override="auto")) is GlassTier.FLAT

    @pytest.mark.parametrize("kwargs,field", [
        ({"transparency": 0}, "transparency_enabled"),
        ({"composition": False}, "dwm_composition"),
        ({"power_flag": 1}, "battery_saver"),
    ])
    def test_every_other_wired_veto_also_lands(self, monkeypatch, kwargs, field):
        """The OS turned transparency off / DWM says it is not compositing /
        battery saver is engaged. Each is a POSITIVE observation of absence, so
        each vetoes the OS material — the same host drops from WINDOW to TOKEN."""
        _wire_win11(monkeypatch, **kwargs)
        env = probe_environment(user_override="auto")

        expected = False if field != "battery_saver" else True
        assert getattr(env, field) is expected
        assert decide_tier(env) is SAFE_FLOOR

    def test_an_unreadable_primitive_is_unknown_and_does_not_veto(self, monkeypatch):
        """The fail-soft direction, at the bottom of the real stack: every
        primitive answers "cannot be asked". None of them vetoes (that is the
        ratified tri-state law), nothing degrades, and the host keeps the material
        it demonstrably renders today."""
        _wire_win11(monkeypatch, remote=None, high_contrast=None,
                    transparency=None, composition=None, power_flag=None)

        env = probe_environment(user_override="auto")

        assert (env.remote_session, env.high_contrast, env.transparency_enabled,
                env.dwm_composition, env.battery_saver) == (None,) * 5
        assert env.degraded is False           # unknown is not broken
        assert decide_tier(env) is GlassTier.WINDOW

    def test_the_probes_never_take_the_gui_down(self, monkeypatch):
        """A primitive that RAISES (rather than returning None) must not escape
        either: the contract's own belt (``_ask_backdrop``) answers it as unknown
        and the decision stands. ``probe_environment`` runs on the GUI thread — a
        probe that throws must not be able to take the app down."""
        backdrop = _wire_win11(monkeypatch)

        def boom(*_args):
            raise OSError("user32.dll is on fire")

        for primitive in ("_system_metric", "_high_contrast_flags",
                          "_transparency_setting", "_dwm_composition_enabled",
                          "_power_status_flag"):
            monkeypatch.setattr(backdrop, primitive, boom)

        env = probe_environment(user_override="auto")     # must NOT raise

        assert env.remote_session is None
        assert env.high_contrast is None
        assert decide_tier(env) <= GlassTier.WINDOW
