"""Panel-glass rollout — the Z-ladder, the hazard exclusion, and the scrim floor.

Kaya's order was "das Glass muss durch die ganzen Panels kommen". These tests pin
the three council laws that bound HOW far it may come:

* **Baldr's Z-ladder** (docs/design/glass_council/baldr.md §1): glass is the
  costume of *chrome*, never of data. A pane that hosts an instrument screen
  (Z3), a readout (Z4) or a danger control (Z5) is never glass.
* **Völundr's invariant G2/G3** (docs/design/glass_council/volundr.md §4):
  hazard signalling never rides on translucency, and toggling ANY material knob
  changes **zero pixels** of a hazard-signalling element.
* **Baldr's readability contract** (§1.2): text on a glass surface clears
  WCAG-AA (4.5:1) against a **worst-case white AND black desktop** — because
  what is really behind real glass is the user's desktop, not the token colour.
  That is the ``scrim floor``, and it is what the alpha clamps in ``gui/style.py``
  exist to enforce. Here it is an executable gate rather than taste.

The census test (``test_glass_role_census_*``) is the general form: it walks the
LIVE registry after building every wired panel and refuses any glass pane that
contains a hazard/readout/plot/table descendant. A future panel that opts a
danger surface into glass fails here without anyone remembering to add a case.
"""
from __future__ import annotations

import os

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _clean_material_state():
    """Every test here mutates global material state (glass switch, alphas).
    Reset it both ways so neither this file nor its neighbours inherit a
    half-tuned style module (the alphas feed build_qss for the whole session)."""
    from gui import panel_kit, style

    panel_kit.set_panel_glass(False)
    style.reset_theme_customization()
    yield
    panel_kit.set_panel_glass(False)
    style.reset_theme_customization()


def _sim_device_manager(tmp_path):
    """Fully-simulated DeviceManager from a throwaway devices.yaml. Never
    connected — construction only (hardware-safety rule 1)."""
    from controller.device_manager import DeviceManager

    cfg = {
        "oscilloscope":       {"backend": "visa", "simulation": True},
        "motor_stage":        {"backend": "simulated"},
        "intensity_monitor":  {"backend": "simulated"},
        "camera":             {"simulation": True},
        "waveform_generator": {"simulation": True},
        "bias_supply":        {"backend": "simulated"},
        "output":             {"data_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return DeviceManager(config_path=str(path))


# --------------------------------------------------------------------------- #
# The role census — Baldr's Z-ladder as a walk of the live registry           #
# --------------------------------------------------------------------------- #

# Z5: every objectName this app uses for a hazard control. A pane hosting one
# must never be glass (Baldr §5.2 "danger controls never BEHIND translucency").
HAZARD_OBJECT_NAMES = frozenset({"dangerBtn", "killSwitchBtn", "armedBtn"})


def _glass_disqualifiers(pane) -> list[str]:
    """Every reason *pane* is ineligible for glass, per the Z-ladder. Empty list
    == a legitimate Z1/Z2 chrome surface."""
    import pyqtgraph as pg
    from PySide6.QtWidgets import QTableWidget, QWidget

    from gui.arm_latch import ArmLatch
    from gui.panel_kit import FigureCard
    from gui.status_widgets import ReadoutCell

    reasons: list[str] = []
    # The pane itself, plus everything under it — a glass fill sits behind ALL
    # of its descendants, so a single hazard child disqualifies the whole pane.
    for w in [pane, *pane.findChildren(QWidget)]:
        name = w.objectName()
        if name in HAZARD_OBJECT_NAMES:
            reasons.append(f"Z5 hazard control #{name}")
        if isinstance(w, ArmLatch):
            reasons.append("Z5 ArmLatch danger well")
        if isinstance(w, ReadoutCell):          # MetricTile subclasses this
            reasons.append("Z4 readout cell")
        if isinstance(w, (FigureCard, pg.PlotWidget)):
            reasons.append("Z3 instrument screen")
        if isinstance(w, QTableWidget):
            reasons.append("Z4 live data table")
    return reasons


@pytest.fixture(scope="module")
def panels(qapp, tmp_path_factory):
    """Every panel this beat touched, plus the two deliberately left fully
    opaque (bias, monitor) so the census also proves their exclusion.

    Built ONCE for the module and torn down explicitly: these panels own
    QThreads and QTimers, and a QThread destroyed by the garbage collector while
    still running is a hard Qt6 abort (the documented MotorPanel crash class).
    Strong refs are held for the whole module, then shutdown() + deleteLater().
    """
    from devices.laser_manual import LaserManualMetadata

    from gui.bias_panel import BiasPanel
    from gui.calibration_panel import CalibrationPanel
    from gui.laser_panel import LaserPanel
    from gui.monitor_panel import MonitorPanel
    from gui.planner_panel import PlannerPanel

    tmp_path = tmp_path_factory.mktemp("glass")
    dm = _sim_device_manager(tmp_path)

    class _Chan:
        def __init__(self, name, unit):
            self.name, self.unit = name, unit

    class _Mgr:
        channels = [_Chan("temperature_C", "C"), _Chan("humidity_pct", "%RH")]

        def read_all(self):
            return {}

    built = {
        "laser": LaserPanel(LaserManualMetadata(), dm.waveform_generator),
        "calibration": CalibrationPanel(dm),
        "planner": PlannerPanel(),
        "bias": BiasPanel(dm.bias_supply),
        "monitor": MonitorPanel(_Mgr(), poll_interval_s=5.0),
    }
    built["_keepalive_device_manager"] = dm     # never connected; just kept alive
    panels_only = {k: v for k, v in built.items() if not k.startswith("_")}
    yield panels_only

    for panel in panels_only.values():
        shutdown = getattr(panel, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except Exception:
                pass
        panel.deleteLater()
    qapp.processEvents()


def test_glass_role_census_no_registered_pane_hosts_a_hazard_or_data_surface(panels):
    """Tyr's census, the general form: build every wired panel, turn the switch
    ON, and walk the LIVE registry. Any pane carrying glassPane that contains a
    danger control, an ArmLatch, a readout cell, a plot or a data table is a
    Z-ladder violation — no matter which panel put it there."""
    from gui import panel_kit

    try:
        panel_kit.set_panel_glass(True)

        registered = panel_kit.registered_glass_panes()
        assert registered, "the wired panels registered nothing at all"

        # Scope to panes belonging to the panels we just built (the registry is
        # process-global; a neighbouring test's throwaway Card is not our
        # business). isAncestorOf covers a pane nested at any depth.
        ours = [p for p in registered
                if any(root is p or root.isAncestorOf(p) for root in panels.values())]
        assert ours, "none of the built panels registered a glass pane"

        offenders = {
            f"{p.objectName() or type(p).__name__}": _glass_disqualifiers(p)
            for p in ours
        }
        offenders = {k: v for k, v in offenders.items() if v}
        assert not offenders, (
            "glass pane(s) host a surface the Z-ladder forbids: "
            f"{offenders}")

        # And every one of them really did take the tint.
        for pane in ours:
            assert pane.property("glassPane") == "true"
    finally:
        panel_kit.set_panel_glass(False)


def test_hazard_and_data_panes_are_never_registered(panels):
    """The named exclusions, spelled out (the census above proves the rule; this
    proves we did not simply register nothing). Each of these is a real surface
    in a shipped panel that MUST stay opaque."""
    from gui import panel_kit

    try:
        panel_kit.set_panel_glass(True)
        registered = set(map(id, panel_kit.registered_glass_panes()))

        laser, calib, planner, bias = (
            panels["laser"], panels["calibration"],
            panels["planner"], panels["bias"])

        denied = {
            # Laser: the wavegen card hosts the "Output on" ARMED trigger
            # button; the amber banner is a hazard-ink honesty surface.
            "laser wavegen card (armedBtn)": laser._card_wfg,
            "laser manual-laser banner (warn ink)": laser._banner_card,
            # Calibration: readout cells / the repeatability STOP button.
            "calibration reference box (readouts)": calib._ref_box,
            # Bias is the safety dashboard — every card is entangled with a
            # hazard control, so the panel opts NOTHING in.
            "bias voltage card (kill switch)": bias._volt_box,
            "bias sweeps card (plots)": bias._sweeps_card,
        }
        for why, pane in denied.items():
            assert id(pane) not in registered, f"{why} must never be registered"
            assert not pane.property("glassPane"), f"{why} must never go glass"

        # The planner's "before you run" aside hosts the ArmLatch + Abort +
        # estimate tiles: nothing in the planner that carries it may be glass.
        for pane in panel_kit.registered_glass_panes():
            if planner.isAncestorOf(pane):
                assert not _glass_disqualifiers(pane)
    finally:
        panel_kit.set_panel_glass(False)


def test_wired_panels_register_their_chrome_panes(panels):
    """The positive half: the surfaces that SHOULD carry glass do."""
    from gui import panel_kit

    try:
        registered = set(map(id, panel_kit.registered_glass_panes()))
        # Laser: the PDL metadata card (pure bookkeeping chrome).
        assert id(panels["laser"]._card_pdl) in registered
        # Calibration: the electronics-gain group (pure parameter chrome).
        assert id(panels["calibration"]._elec_box) in registered
        # Planner: the "add blocks" palette (a rail of draggable buttons).
        assert id(panels["planner"]._palette_card) in registered
    finally:
        panel_kit.set_panel_glass(False)


def test_bias_panel_opts_nothing_in(panels):
    """Bias is the safety dashboard (Baldr §1: the operator's eye lives on the
    HV readout). Its compliance / voltage / polarity / sweeps cards each host a
    kill switch, a danger button, a hazard warn label or a plot — so the panel
    contributes ZERO glass panes. Pinning this so a future 'make bias pretty'
    pass has to argue with a test."""
    from gui import panel_kit

    try:
        bias = panels["bias"]
        bias_panes = [p for p in panel_kit.registered_glass_panes()
                      if bias is p or bias.isAncestorOf(p)]
        assert bias_panes == []
    finally:
        panel_kit.set_panel_glass(False)


# --------------------------------------------------------------------------- #
# Völundr G3 — material carries ZERO hazard information                       #
# --------------------------------------------------------------------------- #

def _hazard_widgets(panels):
    from PySide6.QtWidgets import QWidget
    out = []
    for root in panels.values():
        for w in [root, *root.findChildren(QWidget)]:
            if w.objectName() in HAZARD_OBJECT_NAMES:
                out.append(w)
    return out


def test_toggling_panel_glass_changes_zero_hazard_widget_state(panels):
    """G3 as widgets: flipping the glass switch must not touch one property of
    one hazard control. Structurally guaranteed (they are never registered, and
    the QSS hook is a per-instance property) — asserted so it stays that way."""
    from gui import panel_kit

    try:
        hazards = _hazard_widgets(panels)
        assert hazards, "no hazard controls found — the census would be vacuous"

        def snapshot():
            return [(w.objectName(), w.styleSheet(), w.property("glassPane"),
                     w.property("state")) for w in hazards]

        before = snapshot()
        panel_kit.set_panel_glass(True)
        assert snapshot() == before
        panel_kit.set_panel_glass(False)
        assert snapshot() == before
    finally:
        panel_kit.set_panel_glass(False)


def test_material_knobs_never_alter_a_safety_token_in_the_qss():
    """G3 as QSS text: no reachable material state (backdrop kind, either alpha,
    at either clamp bound) may change how a LOCKED safety token renders. The
    six-name SAFETY_TOKENS set is indivisible (Völundr §2 T1)."""
    from gui import style

    def safety_lines(qss: str) -> list[str]:
        # Every QSS line that paints with a locked safety colour, in order.
        tokens = {t: style.palette("dark")[t] for t in style.SAFETY_TOKENS}
        return [ln for ln in qss.splitlines()
                if any(hexv.lower() in ln.lower() for hexv in tokens.values())]

    style.reset_theme_customization()
    baseline = safety_lines(style.build_qss(style.palette("dark")))
    assert baseline, "no safety-token QSS lines found — the guard would be vacuous"

    for kind in ("none", "mica", "acrylic"):
        for canvas_a in (style.MIN_BACKDROP_CANVAS_ALPHA,
                         style.MAX_BACKDROP_CANVAS_ALPHA):
            for panel_a in (style.MIN_PANEL_GLASS_ALPHA,
                            style.MAX_PANEL_GLASS_ALPHA):
                style.set_window_backdrop(kind)
                style.set_backdrop_canvas_alpha(canvas_a)
                style.set_panel_glass_alpha(panel_a)
                qss = style.build_qss(style.palette("dark"))
                assert safety_lines(qss) == baseline, (
                    f"a safety token moved at backdrop={kind} "
                    f"canvas={canvas_a} panel={panel_a}")
    style.reset_theme_customization()


# --------------------------------------------------------------------------- #
# Baldr §1.2 — the scrim floor / worst-case contrast contract                  #
# --------------------------------------------------------------------------- #

def _relative_luminance(rgb) -> float:
    def _lin(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a, b) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _composite(fg, alpha: float, bg):
    return tuple(alpha * fg[i] + (1 - alpha) * bg[i] for i in range(3))


def _worst_case_glass_contrast(canvas_alpha: float, panel_alpha: float) -> float:
    """The contrast a label on an opted-in glass pane actually survives, in the
    worst corner Baldr names: the pane's rgba over the canvas's rgba over a
    **pure white or pure black desktop**, in both themes, for both the primary
    and the (lower-contrast) muted ink."""
    from gui import style

    worst = float("inf")
    for mode in ("dark", "light"):
        p = style.palette(mode)
        bg, panel = _hex_rgb(p["bg"]), _hex_rgb(p["panel"])
        for ink in ("text", "muted"):
            ink_rgb = _hex_rgb(p[ink])
            for desktop in ((255, 255, 255), (0, 0, 0)):
                canvas = _composite(bg, canvas_alpha, desktop)
                surface = _composite(panel, panel_alpha, canvas)
                worst = min(worst, _contrast(ink_rgb, surface))
    return worst


def test_shipped_glass_alphas_clear_wcag_aa_against_any_desktop():
    """The shipped defaults are defensible, not a placeholder: text on a glass
    pane clears 4.5:1 even when what is behind the window is pure white."""
    from gui import style

    worst = _worst_case_glass_contrast(
        style.BACKDROP_CANVAS_ALPHA, style.PANEL_GLASS_ALPHA)
    assert worst >= 4.5, f"shipped glass alphas only reach {worst:.2f}:1"


def test_the_alpha_clamps_ARE_the_scrim_floor():
    """The whole point of the clamps: the most translucent LEGAL combination —
    both alphas dragged to their floor at once — still clears WCAG-AA. A slider
    that cannot express an unsafe value needs no user discipline (the same rail
    as MIN_WINDOW_OPACITY)."""
    from gui import style

    worst = _worst_case_glass_contrast(
        style.MIN_BACKDROP_CANVAS_ALPHA, style.MIN_PANEL_GLASS_ALPHA)
    assert worst >= 4.5, (
        f"the clamp floors permit {worst:.2f}:1 — the scrim floor is too low")


# --------------------------------------------------------------------------- #
# The alphas: clamps, fail-safe parsing, persistence                          #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("setter,getter,lo,hi", [
    ("set_backdrop_canvas_alpha", "get_backdrop_canvas_alpha",
     "MIN_BACKDROP_CANVAS_ALPHA", "MAX_BACKDROP_CANVAS_ALPHA"),
    ("set_panel_glass_alpha", "get_panel_glass_alpha",
     "MIN_PANEL_GLASS_ALPHA", "MAX_PANEL_GLASS_ALPHA"),
])
def test_alpha_setters_clamp_and_fail_opaque(setter, getter, lo, hi):
    from gui import style

    set_, get_ = getattr(style, setter), getattr(style, getter)
    floor, ceil = getattr(style, lo), getattr(style, hi)

    assert set_(0.0) == floor            # below the scrim floor -> the floor
    assert get_() == floor
    assert set_(5.0) == ceil             # above 1.0 -> opaque
    assert set_(-1.0) == floor
    # Garbage / NaN fail to the OPAQUE end (never to a ghost surface).
    for junk in (None, "", "0.2abc", float("nan")):
        assert set_(junk) == ceil
    mid = (floor + ceil) / 2
    assert set_(mid) == pytest.approx(mid)
    style.reset_theme_customization()


def test_alphas_round_trip_through_qsettings_and_a_hand_edited_store(tmp_path):
    """Persistence + the fail-safe on load: a registry hand-edited below the
    scrim floor is RAISED to the floor on load, never obeyed."""
    from PySide6.QtCore import QSettings

    from gui import style

    ini = str(tmp_path / "t.ini")
    s = QSettings(ini, QSettings.Format.IniFormat)

    style.set_backdrop_canvas_alpha(0.86)
    style.set_panel_glass_alpha(0.62)
    style.save_theme_customization(s)

    style.reset_theme_customization()
    assert style.get_panel_glass_alpha() == style.PANEL_GLASS_ALPHA

    style.load_theme_customization(s)
    assert style.get_backdrop_canvas_alpha() == pytest.approx(0.86)
    assert style.get_panel_glass_alpha() == pytest.approx(0.62)

    # Hand-edit the store to a ghost-cockpit value; the load must clamp it.
    s.setValue("theme/canvas_alpha", 0.05)
    s.setValue("theme/panel_glass_alpha", 0.01)
    s.sync()
    style.load_theme_customization(s)
    assert style.get_backdrop_canvas_alpha() == style.MIN_BACKDROP_CANVAS_ALPHA
    assert style.get_panel_glass_alpha() == style.MIN_PANEL_GLASS_ALPHA
    style.reset_theme_customization()


def test_panel_glass_alpha_drives_the_glass_qss_rule():
    """The tuning knob actually reaches the paint. (Round-03 kit: the pane
    tint paints the `card` rung now — kit §2.1 "one rung up, at your rung's
    alpha"; in light card == panel byte-for-byte.)"""
    from gui import style

    p = style.palette("dark")
    style.set_panel_glass_alpha(0.90)
    qss = style.build_qss(p)
    assert style._rgba(p["card"], 0.90) in qss

    style.set_panel_glass_alpha(style.MIN_PANEL_GLASS_ALPHA)
    qss = style.build_qss(p)
    assert style._rgba(p["card"], style.MIN_PANEL_GLASS_ALPHA) in qss
    style.reset_theme_customization()


def test_canvas_alpha_drives_the_canvas_fill_only_when_a_backdrop_is_active():
    """The canvas alpha is inert without a material — the byte-identical-when-off
    guard (Völundr I2) still holds with the knob at any legal value."""
    from gui import style

    p = style.palette("dark")
    style.set_window_backdrop("none")
    for alpha in (style.MIN_BACKDROP_CANVAS_ALPHA, 0.9,
                  style.MAX_BACKDROP_CANVAS_ALPHA):
        style.set_backdrop_canvas_alpha(alpha)
        assert style._canvas_fill(p) == p["bg"]      # opaque hex, unchanged

    style.set_window_backdrop("acrylic")
    style.set_backdrop_canvas_alpha(0.88)
    assert style._canvas_fill(p) == style._rgba(p["bg"], 0.88)
    style.reset_theme_customization()


# --------------------------------------------------------------------------- #
# The Material menu — Ymir's operator override                                #
# --------------------------------------------------------------------------- #

def _tmp_settings(tmp_path):
    from PySide6.QtCore import QSettings
    return QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat)


@pytest.mark.parametrize("pick,tier,backdrop_kind,glass_on", [
    # offscreen: is_backdrop_supported() is False, so "auto" honestly lands on
    # the token rung rather than pretending a material it cannot render.
    ("auto", "auto", "none", True),
    ("mica", "real", "mica", True),
    ("acrylic", "real", "acrylic", True),
    ("token", "token", "none", True),
    ("flat", "flat", "none", False),
])
def test_material_mode_maps_to_backdrop_and_panel_glass(
        qapp, tmp_path, pick, tier, backdrop_kind, glass_on):
    """The five-option Material menu is a macro over the two auto-persisted
    material knobs, and it records Ymir's tier for the (future) detection
    ladder's override."""
    from gui import app_settings, panel_kit, style
    from gui.theme_editor import ThemeEditorDialog

    settings = _tmp_settings(tmp_path)
    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    try:
        idx = dlg._material_mode_combo.findData(pick)
        assert idx >= 0
        # The real user gesture. `activated` also covers re-picking the item
        # already displayed — which "auto" IS on a fresh store, and which a
        # currentIndexChanged-only wiring would silently swallow.
        dlg._material_mode_combo.setCurrentIndex(idx)
        dlg._material_mode_combo.activated.emit(idx)

        assert app_settings.theme_glass_tier(settings) == tier
        assert style.get_window_backdrop() == backdrop_kind
        assert app_settings.theme_panel_glass_enabled(settings) is glass_on
    finally:
        panel_kit.set_panel_glass(False)
        dlg.deleteLater()


def test_material_mode_reflects_the_persisted_tier_on_reopen(qapp, tmp_path):
    """The menu is not write-only: a dialog reopened after a restart shows the
    rung the operator forced (``real`` resolves back through the backdrop key)."""
    from gui import panel_kit, style
    from gui.theme_editor import ThemeEditorDialog

    settings = _tmp_settings(tmp_path)
    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    try:
        idx = dlg._material_mode_combo.findData("acrylic")
        dlg._material_mode_combo.setCurrentIndex(idx)
        dlg._material_mode_combo.activated.emit(idx)
    finally:
        dlg.deleteLater()

    # Fresh dialog, same store — as if the app had been restarted.
    style.load_theme_customization(settings)
    dlg2 = ThemeEditorDialog(mode="dark", settings=settings)
    try:
        assert dlg2._material_mode_combo.currentData() == "acrylic"
    finally:
        panel_kit.set_panel_glass(False)
        dlg2.deleteLater()


def test_material_alpha_sliders_are_clamped_by_their_own_range(qapp, tmp_path):
    """The sliders cannot even EXPRESS a sub-floor alpha — the range IS the
    clamp, so there is no unsafe value to drag to (Baldr §5.4)."""
    from gui import panel_kit, style
    from gui.theme_editor import ThemeEditorDialog

    settings = _tmp_settings(tmp_path)
    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    try:
        assert dlg._canvas_alpha_slider.minimum() == int(
            round(style.MIN_BACKDROP_CANVAS_ALPHA * 100))
        assert dlg._panel_alpha_slider.minimum() == int(
            round(style.MIN_PANEL_GLASS_ALPHA * 100))

        # Driving below the floor lands ON the floor, and persists clamped.
        dlg._panel_alpha_slider.setValue(0)
        assert style.get_panel_glass_alpha() == style.MIN_PANEL_GLASS_ALPHA
        assert float(settings.value("theme/panel_glass_alpha")) == pytest.approx(
            style.MIN_PANEL_GLASS_ALPHA)
    finally:
        panel_kit.set_panel_glass(False)
        dlg.deleteLater()
