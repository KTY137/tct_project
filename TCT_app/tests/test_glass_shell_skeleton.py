"""GlassShell walking skeleton — headless construction + honesty guards.

Runs offscreen (``QT_QPA_PLATFORM=offscreen``), against SIMULATED devices only.
What it can and cannot prove, stated plainly:

* It CAN prove the module imports, the QML loads with ZERO errors, the bridges
  expose the fields the shell binds, the vitals strip is display-only, the
  island/detach engine is real, and nothing leaks.
* It CANNOT prove anything about pixels: offscreen has no compositor, so the DWM
  material is a no-op there by construction (``gui.backdrop.is_backdrop_supported``
  is False). The glass claim is measured on a real display by
  ``scripts/glass_shell_preview.py --probe``, not asserted here. A test that
  "verified" glass offscreen would be lying, which is precisely the failure mode
  this skeleton exists to prevent.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtQuick")

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from gui import glass_env, qml_theme

_TCT_APP = Path(__file__).resolve().parents[1]
_SCRIPT = _TCT_APP / "scripts" / "glass_shell_preview.py"


def _load_module():
    """Import the launcher by path — ``scripts/`` is not a package."""
    if str(_TCT_APP) not in sys.path:
        sys.path.insert(0, str(_TCT_APP))
    spec = importlib.util.spec_from_file_location("glass_shell_preview", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def gsp():
    return _load_module()


@pytest.fixture
def shell(qapp, gsp):
    """The REAL shell: real QQuickView, real BiasPanel, real DetachableTabWidget,
    simulated supply. Torn down completely (the panel owns a QThread)."""
    gsp.pin_opengl_rhi()
    s = gsp.build_shell(mode="light", backdrop_kind="acrylic", tier=None)
    yield s
    s.shutdown()
    QApplication.processEvents()


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


# --------------------------------------------------------------------------- #
# 1. It builds, and the QML is clean                                           #
# --------------------------------------------------------------------------- #
def test_qml_loads_with_zero_errors(shell):
    assert shell.errors == [], f"GlassShell.qml failed to load: {shell.errors}"
    assert shell.view.rootObject() is not None


def test_the_root_is_a_real_quickwindow_not_a_widget_island(shell):
    """The whole point of the beat. A QQuickWidget island in a QWidget window IS
    the classic shell; only a QQuickWindow root can reach the SCENE rung."""
    from PySide6.QtQuick import QQuickWindow

    assert isinstance(shell.view, QQuickWindow)


def test_the_island_slot_exists_for_the_host_to_aim_at(shell):
    from PySide6.QtQuick import QQuickItem

    root = shell.view.rootObject()
    assert root.findChild(QQuickItem, "islandSlot") is not None


# --------------------------------------------------------------------------- #
# 2. The shell declares itself SHELL_GLASS — that is what unlocks SCENE        #
# --------------------------------------------------------------------------- #
def test_shell_declares_itself_as_the_glass_shell(shell):
    env = shell._environment()
    assert env.shell == glass_env.SHELL_GLASS
    assert glass_env.SHELL_CEILINGS[env.shell] == glass_env.GlassTier.COMPOSED


def test_offscreen_decides_a_safe_tier_and_attaches_no_material(shell):
    """Offscreen has no compositor: the honest answer is no material, and the
    canvas must therefore be the OPAQUE token pre-blend (underlay law)."""
    shell.apply_glass(reason="test")
    assert shell.glass.material is False
    assert shell.view.color().alpha() == 255, (
        "UNDERLAY LAW VIOLATION: a translucent scene clear with no material "
        "behind it is the black-hole bug.")
    assert shell.tier <= glass_env.GlassTier.WINDOW


# --------------------------------------------------------------------------- #
# 3. THE RATIFIED LAW: the shell displays hazard state, it never triggers it   #
# --------------------------------------------------------------------------- #
def test_vitals_bridge_is_display_only(gsp):
    """No slot on the vitals bridge may change hardware state. The strip is a
    readout; danger belongs to the panel that owns the device."""
    from PySide6.QtCore import QMetaMethod

    vitals = gsp.VitalsBridge()
    meta = vitals.metaObject()
    slots = {meta.method(i).name().data().decode()
             for i in range(meta.methodOffset(), meta.methodCount())
             if meta.method(i).methodType() == QMetaMethod.MethodType.Slot}
    forbidden = {"arm", "enable", "disable", "ramp", "stop", "start", "home",
                 "setVoltage", "outputOn", "outputOff", "abort"}
    assert not (slots & forbidden), f"hazard-triggering slot in the shell: {slots}"
    assert slots <= {"on_reading"}, f"unexpected vitals slot: {slots}"


def test_chrome_exposes_no_hazard_action(gsp, shell):
    """The chrome may switch themes, cycle the backdrop/tier and connect a
    SIMULATED supply. It may not energize, home, or scan."""
    from PySide6.QtCore import QMetaMethod

    meta = shell._chrome.metaObject()
    slots = {meta.method(i).name().data().decode()
             for i in range(meta.methodOffset(), meta.methodCount())
             if meta.method(i).methodType() == QMetaMethod.MethodType.Slot}
    assert slots == {"toggleTheme", "cycleBackdrop", "cycleTier", "connectSim"}


def test_nothing_is_connected_or_energized_at_construction(shell):
    """Hardware safety rule 1, honoured even against a fake device."""
    assert shell._supply.connected is False
    assert shell.vitals.connected is False
    assert shell.vitals.hvText == "--"


# --------------------------------------------------------------------------- #
# 4. The vitals the QML migration DROPPED are back, and they are real          #
# --------------------------------------------------------------------------- #
def test_leakage_and_compliance_are_exposed(shell):
    for prop in ("hvText", "hvState", "currentText", "currentState",
                 "complianceText", "complianceState", "connected"):
        assert shell.vitals.metaObject().indexOfProperty(prop) >= 0, prop


def test_vitals_render_a_real_reading_from_the_panels_own_poller(shell):
    """The data path, end to end: a BiasReading (the exact object the panel's
    QThread poller emits) lands in the strip as formatted text + a state."""
    from devices.bias_supply_base import BiasReading

    shell.vitals.on_reading(BiasReading(voltage_V=-120.0, current_A=2.5e-9,
                                        compliant=False))
    assert shell.vitals.hvText == "-120.0 V"
    assert shell.vitals.currentText == "+2.50 nA"
    assert shell.vitals.complianceText == "OK"
    assert shell.vitals.complianceState == "good"

    shell.vitals.on_reading(BiasReading(voltage_V=-120.0, current_A=1.2e-3,
                                        compliant=True))
    assert shell.vitals.complianceText == "IN COMPLIANCE"
    assert shell.vitals.complianceState == "crit", (
        "compliance is a FAULT state on the HV supply — it may never render calm")

    shell.vitals.on_reading(None)               # disconnected / unreadable
    assert shell.vitals.hvText == "--"


def test_the_panels_poller_really_feeds_the_strip(shell):
    """Not a hand-call: the panel's own poller signal is connected to the strip,
    so the strip cannot silently drift away from what the panel shows."""
    from devices.bias_supply_base import BiasReading

    shell.panel._read_poller.reading.emit(
        BiasReading(voltage_V=-42.0, current_A=0.0, compliant=False))
    QApplication.processEvents()
    assert shell.vitals.hvText == "-42.0 V"


# --------------------------------------------------------------------------- #
# 5. The island and the detach engine are REAL                                 #
# --------------------------------------------------------------------------- #
def test_island_hosts_the_real_bias_panel_on_a_simulated_supply(shell):
    from devices.bias_supply_simulated import SimulatedBiasSupply
    from gui.bias_panel import BiasPanel

    assert isinstance(shell.panel, BiasPanel)
    assert isinstance(shell._supply, SimulatedBiasSupply)
    assert shell._supply.simulation is True


def test_the_panel_keeps_its_own_danger_gate(shell):
    """The hazard gate lives with the hardware panel, not in the shell."""
    from gui.qt_danger_gate import QtDangerGate

    assert isinstance(shell.panel._gate, QtDangerGate)


def test_detach_is_the_real_engine_not_a_reimplementation(shell):
    """gui/detachable_tabs.py stays the ENGINE; the QML pill shelf is a VIEW over
    it via gui.qml_shell._TabShelfAdapter (imported, never forked)."""
    from gui.detachable_tabs import DetachableTabWidget
    from gui.qml_shell import _TabShelfAdapter

    assert isinstance(shell.tabs, DetachableTabWidget)
    assert isinstance(shell._tab_adapter, _TabShelfAdapter)
    assert shell._tab_adapter.titles == ["Bias", "Scan (stub)"]

    shell._tab_adapter.detach(0)                # what the ⧉ glyph calls
    assert shell.tabs.detached_titles() == ["Bias"]
    assert shell._tab_adapter.titles == ["Scan (stub)"]

    shell.tabs.redock_all()
    QApplication.processEvents()
    assert shell.tabs.detached_titles() == []


# --------------------------------------------------------------------------- #
# 6. Honesty: everything unwired wears a STUB badge                            #
# --------------------------------------------------------------------------- #
def test_every_unwired_vital_is_marked_stub_in_the_qml():
    """A skeleton whose fakes look real is worse than no skeleton. The four
    readouts with no device behind them must carry ``stub: true`` in the QML."""
    qml = (_TCT_APP / "gui" / "qml" / "glassshell" / "GlassShell.qml").read_text(
        encoding="utf-8")
    for label in ("MOTION", "SCAN", "LASER", "SCOPE"):
        i = qml.index(f'label: "{label}"')
        block = qml[i:i + 400]
        assert "stub: true" in block, f"{label} is unwired but not marked STUB"
    for real in ("HV", "LEAKAGE", "COMPLIANCE"):
        i = qml.index(f'label: "{real}"')
        assert "stub: true" not in qml[i:i + 300], (
            f"{real} IS wired to the real poller — it must not claim to be a stub")


def _qml_code_only(path: Path) -> str:
    """The .qml with its ``//`` comment lines stripped — so a guard greps CODE,
    not the prose that explains the code."""
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("//"))


def test_qml_has_no_inline_hex():
    """Tokens only (gui/qml_theme.py). The rule extends to .qml."""
    import re

    for f in (_TCT_APP / "gui" / "qml" / "glassshell").glob("*.qml"):
        assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", _qml_code_only(f)), \
            f"inline hex in {f.name}"


def test_no_multieffect_over_the_island_or_anywhere(shell):
    """Measured (bbe3b10): an in-scene frost over the window's alpha hole is
    pixel-identical to no pane at all — and a MultiEffect may never go over a
    hot-path island. Every gutter here IS an alpha hole, so the shell uses none.

    Comments are stripped: this file EXPLAINS why it uses no MultiEffect, and a
    guard that cannot tell code from prose would forbid saying so."""
    for f in (_TCT_APP / "gui" / "qml" / "glassshell").glob("*.qml"):
        body = _qml_code_only(f)
        assert "MultiEffect" not in body, f"MultiEffect in {f.name}"
        assert "QtQuick.Effects" not in body, f"QtQuick.Effects imported in {f.name}"


# --------------------------------------------------------------------------- #
# 7. Theme switch, both directions, no leaks                                   #
# --------------------------------------------------------------------------- #
def test_theme_switch_repaints_both_directions(shell):
    start = qml_theme.current_mode()
    shell.toggle_theme()
    assert qml_theme.current_mode() != start
    assert shell.glass.dark == (qml_theme.current_mode() == "dark")
    shell.toggle_theme()
    assert qml_theme.current_mode() == start


def test_tier_override_can_only_force_down_never_up(shell):
    """The ceiling law. 'flat' must reach FLAT; no override may promote."""
    shell._tier_override = "flat"
    shell.apply_glass(reason="test")
    assert shell.tier == glass_env.GlassTier.FLAT
    assert shell.glass.material is False

    shell._tier_override = "scene"              # asking for more than offscreen has
    shell.apply_glass(reason="test")
    assert shell.tier <= glass_env.GlassTier.WINDOW, (
        "an override must never promote a tier the host cannot render")


def test_shutdown_is_idempotent_and_stops_the_panel_thread(qapp, gsp):
    gsp.pin_opengl_rhi()
    s = gsp.build_shell(mode="dark", backdrop_kind="mica", tier=None)
    panel = s.panel
    s.shutdown()
    s.shutdown()                                # twice — must not raise
    QApplication.processEvents()
    assert not panel._read_thread.isRunning()
    assert s._island_host is None


def test_shell_does_not_touch_the_shipped_app(gsp):
    """This is a launcher BESIDE the app: the shipped cockpit must be unaffected.

    So it may not import the composition root (``tct_gui``/``main``) or the
    ``DeviceManager`` — pulling those into a preview process would drag in the
    real device stack and the config, which is exactly what "no hardware, ever"
    forbids. Checked against the AST (the real import statements), not the source
    text: this module's own docstring talks ABOUT DeviceManager to say it does
    not use one, and a guard that cannot tell code from prose is a guard that
    punishes honesty."""
    import ast

    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            imported.add(base)
            imported.update(f"{base}.{a.name}" for a in node.names)

    banned = {"tct_gui", "main", "controller.device_manager"}
    assert not (imported & banned), f"the preview imports the shipped app: {imported & banned}"
    assert not any(name.endswith("DeviceManager") for name in imported)
