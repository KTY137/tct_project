"""Static enforcement of the three-layer law (UI / fast Python backend / driver;
Kaya's architecture ratification, 2026-07-11 — see
``docs/research/qml_hybrid_architecture.md`` §9 "The three-layer law as the
foundation the hybrid sits on").

This is the STATIC half of enforcement (an AST import scan, no `import-linter`
dependency needed — this repo doesn't vendor one). It catches "wrong layer"
violations (a driver reaching upward into the backend, a panel importing the
composition root). It deliberately CANNOT catch "right layer, wrong thread"
(compute that lives in an allowed module but is *called synchronously on the
GUI thread*) — that is the dynamic half, ``tests/test_gui_thread_watchdog.py``.
Both are required; see that file's docstring for the founding case (the Scan
Planner estimate stall) this pair of tests turns into a permanent regression
gate.

Layer ranks (bottom -> top; an importer may depend only on layers reachable
from its own entry in ``_ALLOWED_TARGETS`` below, plus its own layer):

    analysis   -- pure leaf: stdlib + numpy ONLY, no project imports at all,
                  no Qt.  (Named physics formulas: CCE, charge, depletion
                  voltage, ... — see CLAUDE.md "analysis/" row.)
    devices    -- drivers: stdlib/third-party only (PyVISA, pyserial, the
                  vendored e4control transports, ...), no project imports
                  above it (not controller/data/analysis/gui/tct_gui/main).
    controller, data -- backend: may depend on devices + analysis (data may
                  also depend on devices/analysis; controller does today via
                  device_manager.py's writers/calibration imports).
    gui        -- UI: may depend on controller/devices/data/analysis (a panel
                  legitimately takes a live device object as a constructor
                  arg, and CLAUDE.md is explicit that "GUI code only calls and
                  plots [analysis] formulas" — gui -> analysis is EXPLICITLY
                  ALLOWED, see test_gui_may_depend_on_analysis below). May NOT
                  import tct_gui or main (composition-root rule,
                  docs/design/gui_architecture_plan.md §1).
    tct_gui.py -- composition root: instantiates and wires every panel/device;
                  may depend on gui/controller/devices/analysis/data.
    main.py    -- entry point: the ONLY module allowed to import tct_gui.

``tests/`` itself is exempt from the "only main.py imports tct_gui" rule —
constructing the real main window for an integration/smoke test is normal
test-harness practice, not a layering violation (the test suite sits above
every layer by design, verifying all of them).
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_APP_ROOT = Path(__file__).resolve().parent.parent

_PROJECT_LAYERS = ("analysis", "devices", "controller", "data", "gui")
_ROOT_MODULES = ("tct_gui", "main")

# Every project-internal name an import root could resolve to (layers +
# root modules) -- used to decide whether an import target is "ours" (subject
# to the contract) or third-party/stdlib (not restricted here).
_PROJECT_NAMES = set(_PROJECT_LAYERS) | set(_ROOT_MODULES)

# source layer -> set of OTHER project layers/root-modules it may import.
# A layer may always import its own siblings (e.g. controller/foo.py
# importing controller.bar) -- that is same-package, not cross-layer, and is
# handled separately in _check_layer_contract below, not listed here.
_ALLOWED_TARGETS: dict[str, set[str]] = {
    "analysis":   set(),                                   # pure leaf
    "devices":    set(),                                    # driver floor
    "controller": {"devices", "analysis", "data"},
    "data":       {"devices", "analysis"},
    "gui":        {"devices", "analysis", "controller", "data"},
    "tct_gui":    {"gui", "controller", "devices", "analysis", "data"},
    "main":       {"tct_gui", "gui", "controller", "devices", "analysis", "data"},
}

_STDLIB = set(sys.stdlib_module_names) | {"__future__"}
# The only third-party dependency analysis/ may use (numpy vectorised math for
# the physics formulas) -- see CLAUDE.md "numpy is pinned <2" note.
_ANALYSIS_THIRD_PARTY_ALLOWED = {"numpy"}


def _layer_files() -> dict[str, list[Path]]:
    """Every ``*.py`` file belonging to each layer/root-module, keyed by
    layer name (``_PROJECT_LAYERS`` package dirs + the two root files).

    ``rglob`` (not ``glob``) so a future subpackage under any layer (e.g. a
    hypothetical ``devices/e4control_vendor/*.py``) cannot silently escape the
    contract by living one directory deeper than the top-level scan -- every
    layer bucket still maps a nested file to the SAME layer regardless of its
    depth, since the bucket is keyed by which top-level dir it was collected
    under, not by the file's own immediate parent. ``__pycache__`` entries are
    excluded explicitly (compiled/cached files, never real source)."""
    files: dict[str, list[Path]] = {name: [] for name in _PROJECT_NAMES}
    for layer in _PROJECT_LAYERS:
        d = _APP_ROOT / layer
        files[layer] = sorted(
            p for p in d.rglob("*.py") if "__pycache__" not in p.parts
        )
    files["tct_gui"] = [_APP_ROOT / "tct_gui.py"]
    files["main"] = [_APP_ROOT / "main.py"]
    return files


def _import_roots(path: Path) -> set[str]:
    """Every top-level module name *path* imports (whole-file AST walk, so a
    lazy/local import inside a function is caught too, not just module-level
    ones). Relative imports (``from . import x`` / ``from .x import y``,
    ``level > 0``) resolve within the same package by construction, so they
    are same-layer by definition and skipped."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue   # relative import -- same package, not cross-layer
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def _check_layer_contract() -> dict[str, list[str]]:
    """Return ``{"layer/file.py -> target": [...]}``-shaped violations: every
    file that imports a project layer/root-module NOT reachable from its own
    entry in ``_ALLOWED_TARGETS`` (same-layer sibling imports are always OK
    and excluded)."""
    violations: dict[str, list[str]] = {}
    for layer, paths in _layer_files().items():
        allowed = _ALLOWED_TARGETS.get(layer, set())
        for path in paths:
            roots = _import_roots(path)
            bad = sorted(
                r for r in roots
                if r in _PROJECT_NAMES and r != layer and r not in allowed
            )
            if bad:
                violations[f"{layer}/{path.name}"] = bad
    return violations


# --------------------------------------------------------------------------- #
# Guards on the scan machinery itself                                         #
# --------------------------------------------------------------------------- #

def test_layer_files_glob_is_non_empty():
    files = _layer_files()
    for layer in _PROJECT_LAYERS:
        assert len(files[layer]) > 0, f"no .py files found under {layer}/ -- glob path is wrong"
    assert files["tct_gui"][0].is_file()
    assert files["main"][0].is_file()


# --------------------------------------------------------------------------- #
# The comprehensive contract (every layer against its allow-list)             #
# --------------------------------------------------------------------------- #

def test_layer_contract_holds():
    """No file imports a project layer/root-module its own layer is not
    allowed to depend on -- the general "dependencies point down only" law
    (UI -> backend -> drivers), enforced across every layered file at once."""
    violations = _check_layer_contract()
    assert violations == {}, (
        "layer-contract violation(s) -- a module imported a layer above/"
        f"outside its allowed set (see this file's module docstring): {violations}"
    )


# --------------------------------------------------------------------------- #
# The explicitly-named rules from the architecture ratification               #
# --------------------------------------------------------------------------- #

def test_devices_import_nothing_above():
    """devices/ (layer 3, drivers) must not import controller/data/analysis/
    gui/tct_gui/main -- the driver floor never reaches upward."""
    for path in _layer_files()["devices"]:
        roots = _import_roots(path)
        upward = roots & (_PROJECT_NAMES - {"devices"})
        assert not upward, f"devices/{path.name} imports upward layer(s): {upward}"


def test_only_main_py_imports_tct_gui():
    """``tct_gui.TCTMainWindow`` is the composition root
    (docs/design/gui_architecture_plan.md §1); nothing but the entry point may
    import the module that wires it. ``tests/`` is exempt by design (see this
    file's module docstring) -- constructing the real main window is normal
    test-harness practice, not a layering violation."""
    importers = []
    for layer, paths in _layer_files().items():
        if layer in ("tct_gui", "main"):
            continue
        for path in paths:
            if "tct_gui" in _import_roots(path):
                importers.append(f"{layer}/{path.name}")
    assert importers == [], (
        f"only main.py may import tct_gui; found importer(s): {importers}"
    )


def test_analysis_is_stdlib_and_numpy_pure():
    """analysis/ (named physics formulas: CCE, charge, depletion voltage, ...)
    must stay a pure leaf: stdlib + numpy only. No PySide6/Qt, no controller/
    devices/gui/data -- it must be importable and testable with zero app
    dependencies, and GUI code must never be ABLE to accidentally reach
    hardware or Qt through it."""
    violations: dict[str, list[str]] = {}
    for path in _layer_files()["analysis"]:
        roots = _import_roots(path)
        bad = sorted(
            r for r in roots
            if r != "analysis"
            and r not in _STDLIB
            and r not in _ANALYSIS_THIRD_PARTY_ALLOWED
        )
        if bad:
            violations[path.name] = bad
    assert violations == {}, (
        f"analysis/*.py must be stdlib+numpy-pure; non-stdlib/non-numpy "
        f"import(s) found: {violations}"
    )


def test_gui_may_depend_on_analysis():
    """gui -> analysis is EXPLICITLY ALLOWED (unlike gui -> tct_gui): panels
    call named physics formulas to plot them, per CLAUDE.md's analysis/ row
    ("GUI code only calls and plots them, never re-implements them inline").
    Two-part proof: (1) the allow-list actually grants it, so a future edit
    tightening _ALLOWED_TARGETS cannot silently break real panels without
    this test catching it; (2) real gui/ code exercises the allowance today,
    so the rule is not just declared but load-bearing."""
    assert "analysis" in _ALLOWED_TARGETS["gui"]
    importers = [
        path.name for path in _layer_files()["gui"]
        if "analysis" in _import_roots(path)
    ]
    assert importers, "expected at least one gui/*.py file to import analysis"
