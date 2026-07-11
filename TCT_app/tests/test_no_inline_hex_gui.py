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

``_PENDING_SWEEP`` is a small, explicit, shrinking allowlist for files with
real (non-comment) inline hex that are OUT OF SCOPE for the task that added
this guard (T3 Phase-4 mechanical sweep: gui/scope_measurements.py,
calibration_panel.py, laser_panel.py, scope_panel.py, device_panel.py only —
see that task's report for what Mamoru's original sweep missed). A follow-up
Phase-4 task should clear it out file by file; ``test_pending_sweep_entries_
still_needed`` fails loudly if an entry is stale (already cleaned up
elsewhere), so the allowlist can only shrink honestly, never silently rot.
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
_PENDING_SWEEP = {
    "motor_panel.py",      # qtawesome icon colour "#8a97a8" (stage-view centre glyph)
    "settings_window.py",  # YAML syntax-highlighter palette (6 literals) +
                            # invalid-YAML editor border "#c0392b"
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
        if path.name in _PENDING_SWEEP:
            continue
        hits = _real_hex_hits(path)
        if hits:
            failures[path.name] = hits
    assert failures == {}, (
        "inline hex literal(s) found outside gui/style.py — resolve them "
        f"through style.py tokens/constants instead: {failures}"
    )


def test_pending_sweep_entries_still_needed():
    """A stale allowlist entry (a file that's actually clean now) must fail
    loudly rather than silently keep masking a future regression there."""
    for name in _PENDING_SWEEP:
        hits = _real_hex_hits(_GUI_DIR / name)
        assert hits, (
            f"gui/{name} is listed in _PENDING_SWEEP but has zero real inline "
            "hex now — remove it from the allowlist"
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
    from gui.calibration_panel import CalibrationPanel
    from gui.style import palette

    dm = _sim_device_manager(tmp_path)
    panel = CalibrationPanel(dm)
    try:
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
