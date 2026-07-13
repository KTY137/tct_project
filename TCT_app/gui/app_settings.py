"""Central QSettings accessors for GUI/user preferences."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

ORG_NAME = "TCT"
APP_NAME = "TCTSetup"

THEME_KEY = "theme"
WINDOW_GEOMETRY_KEY = "geometry"
ACTIVE_TAB_KEY = "active_tab"
DETACHED_TITLES_KEY = "detached_titles"
PLANNER_ARM_LATCH_KEY = "planner/arm_latch"
MOTION_ENABLED_KEY = "ui/motion_enabled"

THEME_GLASS_AMOUNT_KEY = "theme/glass_amount"
THEME_OVERRIDES_KEY = "theme/overrides"
THEME_TYPOGRAPHY_KEY = "theme/typography"
THEME_RADIUS_SCALE_KEY = "theme/radius_scale"
THEME_WINDOW_OPACITY_KEY = "theme/window_opacity"
THEME_WINDOW_BACKDROP_KEY = "theme/window_backdrop"
THEME_PANEL_GLASS_KEY = "theme/panel_glass"
THEME_CANVAS_ALPHA_KEY = "theme/canvas_alpha"
THEME_PANEL_GLASS_ALPHA_KEY = "theme/panel_glass_alpha"
THEME_GLASS_TIER_KEY = "theme/glass_tier"
THEME_PRESETS_KEY = "theme/presets"

# Ymir's operator material-override tier (docs/design/glass_council/ymir.md §7):
# the "for when detection lies" escape hatch. "auto" lets the app pick; the
# other three force a rung. Real translucency is NEVER guaranteed on any host,
# so no hazard information may ever be encoded in the tier (Völundr G3).
GLASS_TIERS = ("auto", "real", "token", "flat")


def settings():
    """Return the application's persistent QSettings store."""
    from PySide6.QtCore import QSettings

    return QSettings(ORG_NAME, APP_NAME)


def _store(store=None):
    return settings() if store is None else store


def theme_mode(store=None) -> str:
    return str(_store(store).value(THEME_KEY, "light"))


def set_theme_mode(mode: str, store=None) -> None:
    _store(store).setValue(THEME_KEY, str(mode))


def window_geometry(store=None):
    return _store(store).value(WINDOW_GEOMETRY_KEY)


def set_window_geometry(geometry, store=None) -> None:
    _store(store).setValue(WINDOW_GEOMETRY_KEY, geometry)


def active_tab_index(store=None) -> int | None:
    raw = _store(store).value(ACTIVE_TAB_KEY)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_active_tab_index(index: int, store=None) -> None:
    _store(store).setValue(ACTIVE_TAB_KEY, int(index))


def detached_titles(store=None) -> list[str]:
    raw = _store(store).value(DETACHED_TITLES_KEY) or []
    if isinstance(raw, str):
        return [raw]
    try:
        return [str(title) for title in raw]
    except TypeError:
        return []


def set_detached_titles(titles: Iterable[str], store=None) -> None:
    _store(store).setValue(DETACHED_TITLES_KEY, list(titles))


def planner_arm_latch_enabled(store=None) -> bool:
    raw = _store(store).value(PLANNER_ARM_LATCH_KEY, True)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ("false", "0", "no", "off")


def motion_enabled(store=None) -> bool:
    """Global "fluent motion" kill switch (``gui/motion_kit.py`` — NOT the
    pre-existing ``gui/motion.py``, see that module's own docstring for the
    naming collision) — the app's prefers-reduced-motion equivalent. Default
    ``True``; every ``gui.motion_kit`` helper becomes a no-op
    jump-to-end-state when this is ``False``. No settings-UI toggle yet (a
    follow-up), but the key is live today."""
    raw = _store(store).value(MOTION_ENABLED_KEY, True)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ("false", "0", "no", "off")


def set_motion_enabled(enabled: bool, store=None) -> None:
    _store(store).setValue(MOTION_ENABLED_KEY, bool(enabled))


def theme_glass_amount_value(store=None) -> Any:
    return _store(store).value(THEME_GLASS_AMOUNT_KEY, None)


def theme_window_opacity_value(store=None) -> Any:
    return _store(store).value(THEME_WINDOW_OPACITY_KEY, None)


def theme_window_backdrop_value(store=None) -> Any:
    return _store(store).value(THEME_WINDOW_BACKDROP_KEY, None)


def theme_panel_glass_enabled(store=None) -> bool:
    """Experimental "Panel glass" switch (gui/theme_editor.py) — whether
    REGISTERED safe panes carry the ``glassPane`` tint. A window-level knob,
    auto-persisted on change (not a draft styling token), default OFF."""
    raw = _store(store).value(THEME_PANEL_GLASS_KEY, False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def set_theme_panel_glass_enabled(enabled: bool, store=None) -> None:
    _store(store).setValue(THEME_PANEL_GLASS_KEY, bool(enabled))


def theme_glass_tier(store=None) -> str:
    """The persisted material-override tier (Ymir §7). Fails safe to ``auto``
    for any absent/garbage value — an unknown tier never wedges startup."""
    raw = str(_store(store).value(THEME_GLASS_TIER_KEY, "auto") or "auto").strip().lower()
    return raw if raw in GLASS_TIERS else "auto"


def set_theme_glass_tier(tier: str, store=None) -> None:
    key = str(tier).strip().lower()
    _store(store).setValue(THEME_GLASS_TIER_KEY, key if key in GLASS_TIERS else "auto")


def theme_overrides_json(store=None) -> str:
    return str(_store(store).value(THEME_OVERRIDES_KEY, "") or "{}")


def theme_typography_json(store=None) -> str:
    return str(_store(store).value(THEME_TYPOGRAPHY_KEY, "") or "{}")


def theme_radius_scale(store=None) -> str:
    return str(_store(store).value(THEME_RADIUS_SCALE_KEY, "m"))


def save_theme_customization_values(
    *,
    glass_amount: float,
    window_opacity: float,
    window_backdrop: str,
    overrides_json: str,
    typography_json: str,
    radius_scale: str,
    store=None,
) -> None:
    s = _store(store)
    s.setValue(THEME_GLASS_AMOUNT_KEY, float(glass_amount))
    s.setValue(THEME_WINDOW_OPACITY_KEY, float(window_opacity))
    s.setValue(THEME_WINDOW_BACKDROP_KEY, str(window_backdrop))
    s.setValue(THEME_OVERRIDES_KEY, str(overrides_json))
    s.setValue(THEME_TYPOGRAPHY_KEY, str(typography_json))
    s.setValue(THEME_RADIUS_SCALE_KEY, str(radius_scale))
    s.sync()


def user_presets_json(store=None) -> str:
    return str(_store(store).value(THEME_PRESETS_KEY, "") or "[]")


def set_user_presets_json(blob: str, store=None) -> None:
    s = _store(store)
    s.setValue(THEME_PRESETS_KEY, str(blob))
    s.sync()
