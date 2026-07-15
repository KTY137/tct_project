"""Guard test: zero inline hex-colour literals in ``gui/*.py`` outside
``gui/style.py`` (cockpit_style_overhaul.md Phase 4 hard rule — every panel
must resolve colour through style.py's tokens/constants, never a hand-rolled
``#rrggbb``).

Generalises the single-file idiom in
``tests/test_scan_viewer_panel.py::test_scan_viewer_panel_source_has_zero_inline_hex``
to every gui module: source is read as TEXT via ``pathlib`` (never imported —
importing every gui module here would be pointless indirection and, for a
guard test, actively wrong: it should stay import-side-effect-free). Comments
and docstrings are stripped with ``ast``/``tokenize`` before matching, so a
docstring that *mentions* a hex value as prose (e.g. "replaces the hardcoded
'#888'") does not trip the guard — only a real literal in executable code
does.

``_PENDING_SWEEP`` is a small, explicit, shrinking allowlist of the EXACT hex
literals still outstanding per file (not a blanket per-file skip — beat
C3-mini tightened this: a file with some pending literals is still scanned
for everything else, so a *new* or *regressed* hex in an otherwise-pending
file fails the guard same as anywhere else) for files that are OUT OF SCOPE
for the task that added this guard (T3 Phase-4 mechanical sweep:
gui/scope_measurements.py, calibration_panel.py, laser_panel.py,
scope_panel.py, device_panel.py only — see that task's report for what
Mamoru's original sweep missed). A follow-up Phase-4 task should clear it
out value by value; ``test_pending_sweep_entries_still_needed`` fails loudly
if an entry is stale (already cleaned up elsewhere), so the allowlist can
only shrink honestly, never silently rot.
"""
from __future__ import annotations

import ast
import io
import os
import re
import tokenize
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_GUI_DIR = Path(__file__).resolve().parent.parent / "gui"
_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")

# See module docstring — real, non-comment inline hex outside this task's
# touch list, tracked here instead of silently failing the guard.
# (motor_panel.py cleared in the batch-B migration: the jog-cluster centre
# glyph now resolves palette(mode)["faint"] instead of "#8a97a8".)
_PENDING_SWEEP: dict[str, frozenset[str]] = {
    "settings_window.py": frozenset({
        "#6a737d", "#005cc5", "#032f62", "#e36209",
    }),  # _YamlHighlighter's syntax palette only. Beat C3-mini cleared the
         # invalid-YAML editor border ("#c0392b" — now resolves through
         # style.py's "crit" token via _palette()), and narrowed this entry
         # from a whole-file skip to exactly these remaining literals, so a
         # regression of that same "#c0392b" (or any other new hex in this
         # file) is caught below same as any unlisted file.
}


def _blank_span(lines: list[str], start: tuple[int, int], end: tuple[int, int]) -> None:
    """Overwrite the half-open [start, end) token span (1-based line, 0-based
    column — the ``tokenize``/``ast`` convention) with spaces, in place."""
    (sl, sc), (el, ec) = start, end
    if sl == el:
        line = lines[sl - 1]
        lines[sl - 1] = line[:sc] + " " * (ec - sc) + line[ec:]
        return
    first = lines[sl - 1]
    trail = "\n" if first.endswith("\n") else ""
    lines[sl - 1] = first[:sc] + " " * (len(first) - sc - len(trail)) + trail
    for idx in range(sl, el - 1):
        trail = "\n" if lines[idx].endswith("\n") else ""
        lines[idx] = " " * (len(lines[idx]) - len(trail)) + trail
    last = lines[el - 1]
    lines[el - 1] = " " * ec + last[ec:]


def _strip_comments_and_docstrings(source: str) -> str:
    """Blank comment text and docstring bodies so a hex value mentioned only
    as a prose example cannot trip the guard, while a real inline-hex literal
    in executable code (a QSS string, an icon-colour kwarg, a dict value, ...)
    still does."""
    lines = source.splitlines(keepends=True)

    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            _blank_span(lines, tok.start, tok.end)

    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            _blank_span(
                lines,
                (first.value.lineno, first.value.col_offset),
                (first.value.end_lineno, first.value.end_col_offset),
            )

    return "".join(lines)


def _gui_modules() -> list[Path]:
    return sorted(p for p in _GUI_DIR.glob("*.py") if p.name != "style.py")


def _real_hex_hits(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    stripped = _strip_comments_and_docstrings(source)
    return _HEX_RE.findall(stripped)


def test_gui_modules_glob_is_non_empty():
    # Guards the guard: if the glob path is ever wrong, the loop below would
    # vacuously "pass" without actually checking anything.
    assert len(_gui_modules()) > 10


def test_no_inline_hex_outside_style_py():
    failures: dict[str, list[str]] = {}
    for path in _gui_modules():
        hits = _real_hex_hits(path)
        allowed = _PENDING_SWEEP.get(path.name)
        if allowed:
            hits = [h for h in hits if h not in allowed]
        if hits:
            failures[path.name] = hits
    assert failures == {}, (
        "inline hex literal(s) found outside gui/style.py — resolve them "
        f"through style.py tokens/constants instead: {failures}"
    )


def test_pending_sweep_entries_still_needed():
    """A stale allowlist entry (a hex value that's actually gone now) must
    fail loudly rather than silently keep masking a future regression of
    that same literal."""
    for name, allowed in _PENDING_SWEEP.items():
        hits = set(_real_hex_hits(_GUI_DIR / name))
        missing = allowed - hits
        assert not missing, (
            f"gui/{name}'s _PENDING_SWEEP lists {sorted(missing)} but they "
            "are no longer present — remove them from the allowlist"
        )


def test_touched_panels_are_clean():
    """The five panels this task's sweep targeted, named explicitly as a
    belt-and-suspenders check on top of the repo-wide scan above."""
    for name in (
        "scope_measurements.py", "calibration_panel.py", "laser_panel.py",
        "scope_panel.py", "device_panel.py",
    ):
        assert _real_hex_hits(_GUI_DIR / name) == [], name


# --------------------------------------------------------------------------- #
# Headless construction + theme-switch smoke tests for the touched panels    #
# --------------------------------------------------------------------------- #

import time

import yaml  # noqa: E402  (kept below os.environ.setdefault, matching the file's idiom)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, seconds: float = 0.2) -> None:
    """Process the Qt event loop briefly so a shutdown()'s queued thread
    quit/deleteLater actually flushes (same helper pattern as
    tests/test_motor_panel_reload.py::_pump)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


def _sim_device_manager(tmp_path):
    """A fully-simulated DeviceManager built from a throwaway devices.yaml —
    same pattern as tests/test_scan_coordinator.py::_sim_config_path. Never
    connected (construction-only — hardware-safety rule 1)."""
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


def test_measurement_panel_construct_and_theme_switch():
    """MeasurementPanel's value colour (ACCENT_DARK) is a fixed-both-themes
    token by design (see gui/scope_measurements.py) — there is no per-panel
    refresh_theme() to exercise, so this only checks construction resolves
    the token. Deliberately does NOT call gui.style.apply_theme(): that is
    an expensive, QApplication-global stylesheet recompute (re-polishes
    every live widget in the process) already dedicated-tested by
    tests/test_apply_theme_lifetime.py — redundantly calling it here, many
    times across many new tests, only adds shared risk to an already-long
    headless run without exercising anything specific to this panel."""
    _app()
    from gui.scope_measurements import MeasurementPanel
    from gui.style import ACCENT_DARK

    panel = MeasurementPanel()
    assert ACCENT_DARK in panel._values["vpp"].styleSheet()


def test_calibration_panel_construct_and_theme_switch(tmp_path):
    """Exercises CalibrationPanel.refresh_theme() directly for its local
    per-instance label colours, without calling global apply_theme()."""
    _app()
    from PySide6.QtWidgets import QLabel

    from gui.calibration_panel import CalibrationPanel
    from gui.style import palette

    dm = _sim_device_manager(tmp_path)
    panel = CalibrationPanel(dm)
    try:
        intro_text = "Set charge-conversion parameters, then apply and save them for analysis."
        labels = {label.text(): label for label in panel.findChildren(QLabel)}
        assert any("calibration" in t.lower() and "tct control" in t.lower() for t in labels)
        assert "Calibration" in labels
        assert intro_text in labels

        panel.refresh_theme("dark")
        assert palette("dark")["text"] in panel._current.styleSheet()
        assert palette("dark")["muted"] in panel._rep_progress.styleSheet()
        panel.refresh_theme("light")
        assert palette("light")["text"] in panel._current.styleSheet()
        assert palette("light")["muted"] in panel._rep_progress.styleSheet()
    finally:
        panel.shutdown()   # no worker running (never clicked Run) — no-op, cheap


def test_laser_panel_construct_and_theme_switch():
    """Exercises LaserPanel.refresh_theme() directly (the panel's own local
    per-instance re-style, not the global gui.style.apply_theme())."""
    app = _app()
    from devices.laser_manual import LaserManualMetadata
    from devices.waveform_generator import WaveformGenerator
    from gui.laser_panel import LaserPanel
    from gui.style import palette

    wfg = WaveformGenerator(simulation=True)
    panel = LaserPanel(LaserManualMetadata(), wfg)
    try:
        panel.refresh_theme("dark")
        assert palette("dark")["muted"] in panel._pulse_hint.styleSheet()
        panel.refresh_theme("light")
        assert palette("light")["muted"] in panel._pulse_hint.styleSheet()
    finally:
        panel.shutdown()   # stop the VISA worker thread it now owns
        _pump(app, 0.1)


def test_motor_panel_stage_view_refreshes_theme_tokens():
    """MotorPanel owns StageView, so its refresh hook must fan the live theme
    into the cached stage-plot colors.

    (The former ``_v3d`` GL page was removed 2026-07-13 — see
    tests/test_no_render_to_texture_children_in_gui.py; only the 2D view is
    themed now.)"""
    app = _app()
    from devices.motor_simulated import SimulatedMotorStage
    from gui.motor_panel import MotorPanel
    from gui.stage_view import _HAS_PG
    from gui.style import palette

    panel = MotorPanel(SimulatedMotorStage())
    try:
        panel.refresh_theme("light")
        assert panel._stage_view._theme_mode == "light"
        assert panel._stage_view._v2d._theme_mode == "light"
        if _HAS_PG:
            bg = panel._stage_view._v2d._top["w"].backgroundBrush().color().name()
            assert bg.lower() == palette("light")["sunk"].lower()

        panel.refresh_theme("dark")
        assert panel._stage_view._theme_mode == "dark"
        assert panel._stage_view._v2d._theme_mode == "dark"
        if _HAS_PG:
            bg = panel._stage_view._v2d._top["w"].backgroundBrush().color().name()
            assert bg.lower() == palette("dark")["sunk"].lower()
    finally:
        panel.shutdown()
        _pump(app, 0.1)


def test_channel_card_readout_color_resolves_from_palette():
    """Exercises gui.scope_panel._ChannelCard.set_readout_color() directly —
    the actual unit this task's mechanical fix touched — without paying for a
    full ScopePanel (which spins up a live acquisition QThread; unnecessary
    here and avoided deliberately, see test_oscilloscope_channel_count.py for
    the full-panel construction/rebuild/thread-lifetime coverage)."""
    from gui.scope_panel import _ChannelCard, _ChannelState
    from gui.style import palette

    _app()
    state = _ChannelState(number=1, color=(0, 200, 255), role="DUT", enabled=True, label="DUT")
    card = _ChannelCard(state)
    card.set_readout_color(palette("dark")["muted"])
    assert palette("dark")["muted"] in card._readout.styleSheet()
    card.set_readout_color(palette("light")["muted"])
    assert palette("light")["muted"] in card._readout.styleSheet()


def test_trigger_dialog_status_color_resolves_from_theme_mode():
    """Exercises gui.scope_panel._TriggerDialog's theme_mode plumbing
    directly (constructed standalone, same reasoning as the channel-card
    test above — no full ScopePanel / reader thread needed)."""
    from devices.oscilloscope import Oscilloscope
    from gui.scope_panel import _TriggerDialog
    from gui.style import palette

    _app()
    scope = Oscilloscope(simulation=True)
    dlg = _TriggerDialog(scope, None, lambda *a, **k: None, None, theme_mode="light")
    assert palette("light")["muted"] in dlg._status.styleSheet()
    dlg.refresh_theme("dark")
    assert palette("dark")["muted"] in dlg._status.styleSheet()
    dlg.refresh_theme("light")
    assert palette("light")["muted"] in dlg._status.styleSheet()


def test_device_manager_window_construct_and_theme_switch(tmp_path):
    """_STATUS_STYLE's colours are only ever read for their (label, colour)
    tuple's label half — see gui/device_panel.py::_refresh — StatusChip does
    all the actual (theme-aware, QSS-driven) painting from the ``state``
    string. Construction-only check for the same apply_theme() cost/risk
    reasoning as the other panels above."""
    app = _app()
    from gui.device_panel import DeviceManagerWindow

    dm = _sim_device_manager(tmp_path)
    win = DeviceManagerWindow(dm)
    try:
        assert win._table.rowCount() == len(dm.named_devices())
    finally:
        win.shutdown()   # stops the 1 s refresh QTimer
        _pump(app, 0.1)


# --------------------------------------------------------------------------- #
# LANTERN kit QML — the same zero-inline-hex law, extended to gui/qml/kit/    #
# (U2.1, kit_spec_v1.md §6: "Everything through Theme.*; no inline hex, ever" #
# — additive: the *.py scan above is untouched).                              #
# --------------------------------------------------------------------------- #

_KIT_QML_DIR = _GUI_DIR / "qml" / "kit"


def _strip_qml_comments(source: str) -> str:
    """Blank ``//`` and ``/* */`` comment text in QML source. String literals
    are deliberately NOT stripped — in QML a hex colour arrives as a string
    (``color: "#123456"``), so the string IS what the guard must see."""
    out: list[str] = []
    i, n = 0, len(source)
    in_line = in_block = False
    quote: str | None = None
    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
            continue
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            if c == "\n":
                out.append(c)
            i += 1
            continue
        if quote is not None:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(nxt)
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _kit_qml_files() -> list[Path]:
    return sorted(_KIT_QML_DIR.glob("*.qml"))


def test_kit_qml_glob_is_non_empty():
    # Guards the guard, same as test_gui_modules_glob_is_non_empty above.
    assert len(_kit_qml_files()) >= 5


def test_no_inline_hex_in_kit_qml():
    failures: dict[str, list[str]] = {}
    for path in _kit_qml_files():
        hits = _HEX_RE.findall(
            _strip_qml_comments(path.read_text(encoding="utf-8")))
        if hits:
            failures[path.name] = hits
    assert failures == {}, (
        "inline hex literal(s) in kit QML — every colour resolves through "
        f"the Theme bridge (kit_spec_v1.md §6), never a literal: {failures}"
    )


def test_device_manager_connected_state_never_renders_green(tmp_path):
    """State-color census D4 rank-1 hit: ``_STATUS_STYLE["connected"]`` still
    names ``OK_GREEN`` (gui/device_panel.py), but that colour half is dead --
    ``StatusChip`` paints purely from the ``state`` string, and
    ``status_widgets._STATE_ALIASES`` already normalizes "connected" to
    "neutral" (law 1: quiet nominal, connected is routine, not a green
    light). Pins the LIVE behaviour end to end: a device that is connected
    but NOT simulated renders its row chip and the header summary chip both
    "neutral", never "good"/green. Flips ``_connected``/``simulation``
    directly on the (never actually connected) sim device object -- a plain
    attribute set, no hardware I/O, matching this module's construction-only
    pattern."""
    app = _app()
    from gui.device_panel import DeviceManagerWindow

    dm = _sim_device_manager(tmp_path)
    win = DeviceManagerWindow(dm)
    try:
        for _name, dev in dm.named_devices().items():
            # "Bias Supply" is a BiasChannel PROXY (connected/simulation are
            # read-only properties delegating to the shared driver) -- flip
            # the underlying driver for that one, the device itself for
            # every plain BaseDevice.
            target = getattr(dev, "_driver", dev)
            target._connected = True
            target.simulation = False   # "connected" (real), not "simulated"
        win._refresh()
        for row in win._row_map:
            chip = win._table.cellWidget(row, 1)
            assert chip.property("state") == "neutral"
            assert chip.property("state") != "good"
        assert win._chip_summary.property("state") == "neutral"
        assert win._chip_summary.property("state") != "good"
    finally:
        win.shutdown()
        _pump(app, 0.1)
