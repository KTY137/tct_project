"""The system ribbon may never silently hide a safety-relevant chip.

THE BUG (audit 2026-07-14). The ribbon sat in a ``QScrollArea#ribbonScroll``
with ``setFixedHeight(54)``, the vertical scrollbar explicitly off — and the
HORIZONTAL policy never set, so it kept Qt's ``AsNeeded`` default. At the
shipped window width the content overflows the viewport and the right-hand
groups get cut off at the edge: **MOTION** (the motor connection/homing state
chip — the highest-safety-relevance item in the strip), then SCAN, then LASER.
There is no usable affordance that anything exists off-screen — the themed
scrollbar is a translucent 3 px sliver inside a 54 px strip. Confirmed on-screen
in ``artifacts_claude/ui_onscreen_20260713T202649Z/acrylic_lablight_A_light.png``.

The fix is not "make the scrollbar louder": nobody scrolls a status readout, they
glance at it. The strip WRAPS (``gui/flow_layout.py``), so a narrow window grows
a second row and every chip stays visible.

ONE window for the whole module, on purpose: repeatedly constructing and
destroying ``TCTMainWindow`` inside a single process is a known native-teardown
hazard here (see ``gui/style.py::_apply_pyqtgraph``'s note on half-destroyed
widget wrappers). Resizing the same window is what these tests actually need.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(ms: int = 80) -> None:
    app = _app()
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


@pytest.fixture(scope="module")
def win():
    from tct_gui import TCTMainWindow

    _app()
    original = TCTMainWindow._restore_window_state
    TCTMainWindow._restore_window_state = lambda self: None
    try:
        w = TCTMainWindow(config_path="configs/devices.yaml")
        w.resize(1280, 800)
        w.show()
        _pump()
        yield w
    finally:
        TCTMainWindow._restore_window_state = original
        try:
            w._teardown_panels()
        finally:
            w.hide()
            w.deleteLater()
            _pump()


def _safety_chips(w) -> dict:
    """The chips an operator must never lose. MOTION is the one the old strip
    actually dropped; leakage/compliance are the two the QML island dropped."""
    return {
        "HV": w._chip_bias_v,
        "leakage": w._chip_bias_i,
        "compliance": w._chip_bias_comp,
        "MOTION": w._chip_motion,
        "SCAN": w._chip_scan,
        "LASER": w._chip_laser,
    }


def _clipped(chip, ribbon) -> bool:
    """True when *chip* is not wholly inside the ribbon's painted area."""
    top_left = chip.mapTo(ribbon, chip.rect().topLeft())
    return not ribbon.rect().contains(chip.rect().translated(top_left))


def test_no_safety_chip_is_ever_clipped_out_of_the_ribbon(win):
    ribbon = win.findChild(QFrame, "systemRibbon")
    assert ribbon is not None

    failures = []
    for width in (1600, 1280, 1100, 960, 820, 700):
        win.resize(width, 800)
        _pump(40)
        for name, chip in _safety_chips(win).items():
            if _clipped(chip, ribbon):
                failures.append(f"{name}@{width}px")
    assert not failures, (
        f"the ribbon clips a safety-relevant chip off-screen, with no "
        f"affordance that it exists: {failures}")


def test_the_ribbon_wraps_instead_of_scrolling(win):
    """The mechanism, not just the symptom.

    (a) There must be NO scroll area around the ribbon — a fixed-height scroll
        strip is exactly what let the clip happen silently.
    (b) The layout must actually WRAP: its height-for-width has to grow as the
        available width shrinks. Asserted on the layout directly, so it does not
        depend on how the window manager honoured a resize.
    """
    ribbon = win.findChild(QFrame, "systemRibbon")

    assert win.findChild(QScrollArea, "ribbonScroll") is None, (
        "the ribbon is back inside a scroll area — it can clip again")
    assert not isinstance(ribbon.parentWidget(), QScrollArea)

    layout = ribbon.layout()
    assert layout.hasHeightForWidth()
    wide = layout.heightForWidth(2400)
    narrow = layout.heightForWidth(600)
    assert narrow > wide, (
        f"the ribbon did not grow when squeezed ({wide}px at 2400 -> "
        f"{narrow}px at 600): it is not wrapping, so its content is going "
        f"somewhere invisible")


def test_leakage_and_compliance_chips_exist_in_the_strip(win):
    """They are in the classic ribbon and must stay there (they were the ones
    DROPPED on the way into the QML island — see tests/test_qml_shell.py for
    that half of the fix)."""
    assert win._chip_bias_i.text().startswith("I ")
    assert win._chip_bias_comp.text().startswith("Compliance")
    ribbon = win.findChild(QFrame, "systemRibbon")
    for chip in (win._chip_bias_i, win._chip_bias_comp):
        assert chip.isVisibleTo(ribbon)
        assert not _clipped(chip, ribbon)
