"""The routine-corpus freeze gate — the test the corpus README promised.

``tests/fixtures/routine_corpus/`` is the P2-entry artifact required by
``docs/ROADMAP_MASTERPLAN.md`` §"Gate enforcement": >= 5 real saved plans, frozen
byte-identically from ``TCT_app/routines/``, so the plan-grammar migration
(``Axis`` -> ``AxisSpec``, registry-backed axes, versioned plan JSON) cannot
silently break saved routines — roadmap risk #6.

Until now that freeze was asserted by the README and by *nothing else*: the
corpus could drift from ``routines/`` (or shrink to nothing) with a green suite.
This file is that gate:

1. the corpus is non-empty and holds >= 5 plans — the **vacuous-pass guard**: a
   test that iterates an empty glob and "passes" is worse than no test at all,
   so every check below asserts the floor before it compares anything;
2. the FILE-NAME SETS of ``routines/*.yaml`` and the corpus match — a routine
   added/renamed/deleted without re-freezing fails here (that desync is exactly
   what happens when someone edits a routine and forgets the copy — e.g. the
   bias-settle dwell comment);
3. per file, ``read_bytes()`` equality — byte-identity, not "parses the same";
4. every corpus plan still loads through the real ``ScanPlan.load_yaml`` and
   validates with 0 ERROR / 0 WARNING under the README's bench-realistic limits.

Qt-free and hardware-free by construction: pure file reads plus the pure plan
model/validator (no device, no writer, no widget).  Paths are resolved from this
file's own location, never from the CWD, so the gate holds under any test runner.
"""
from pathlib import Path

import pytest

from controller.scan_plan import ScanPlan
from controller.scan_plan_validator import PlanLimits, errors, validate_plan, warnings

# tests/ -> TCT_app/ ; package-relative, never CWD-relative.
_APP_ROOT = Path(__file__).resolve().parent.parent
_ROUTINES_DIR = _APP_ROOT / "routines"
_CORPUS_DIR = _APP_ROOT / "tests" / "fixtures" / "routine_corpus"

#: The freeze floor from the roadmap gate ("freeze >= 5 real saved plans").
MIN_CORPUS_PLANS = 5

#: The README's bench-realistic limits: stage +/-25 mm, HV +/-500 V, a camera
#: available (R3/R4 carry CAPTURE_PHOTO, an ERROR without one), and a generous
#: point cap.  Deliberately spelled out here rather than imported from a GUI
#: default, so a panel-side limit change can never silently loosen this gate.
BENCH_LIMITS = PlanLimits(
    x_min_mm=-25.0, x_max_mm=25.0,
    y_min_mm=-25.0, y_max_mm=25.0,
    z_min_mm=-25.0, z_max_mm=25.0,
    voltage_range_V=500.0,
    max_points=250_000,
    camera_available=True,
)


def _corpus_files() -> list[Path]:
    """Corpus plans, sorted — asserting the anti-vacuous floor before returning."""
    files = sorted(_CORPUS_DIR.glob("*.yaml"))
    assert len(files) >= MIN_CORPUS_PLANS, (
        f"routine corpus holds {len(files)} plan(s) at {_CORPUS_DIR}; the "
        f"roadmap gate requires >= {MIN_CORPUS_PLANS}. An empty/truncated corpus "
        "must fail loudly, never pass vacuously."
    )
    return files


def _routine_files() -> list[Path]:
    return sorted(_ROUTINES_DIR.glob("*.yaml"))


# --------------------------------------------------------------------------- #
# 1. the corpus exists and clears the floor (vacuous-pass guard)               #
# --------------------------------------------------------------------------- #

def test_corpus_dir_exists_and_holds_at_least_five_plans():
    assert _CORPUS_DIR.is_dir(), f"missing routine corpus at {_CORPUS_DIR}"
    files = _corpus_files()                       # asserts >= MIN_CORPUS_PLANS
    assert all(f.stat().st_size > 0 for f in files), "empty corpus file(s)"


# --------------------------------------------------------------------------- #
# 2. + 3. the freeze itself: same names, same bytes                            #
# --------------------------------------------------------------------------- #

def test_corpus_and_routines_have_the_same_file_names():
    """A routine added, renamed or deleted without re-freezing fails HERE."""
    corpus = {f.name for f in _corpus_files()}
    live = {f.name for f in _routine_files()}
    assert live == corpus, (
        "routines/ and the frozen corpus disagree.\n"
        f"  only in routines/: {sorted(live - corpus)}\n"
        f"  only in corpus/  : {sorted(corpus - live)}\n"
        "Re-freeze the corpus (copy the routine verbatim) — or, if a plan was "
        "intentionally removed, record the corpus change in the ledger."
    )


def test_corpus_files_are_byte_identical_to_the_live_routines():
    """Byte-identity, not merely 'parses the same'.

    The corpus is the evidence base for the grammar migration: a serializer
    change that rewrites a routine (quoting, key order, a dropped comment) must
    surface as a *recorded, ratified* byte-diff, never as a silent rewrite.  The
    physics comment on R1/R5's bias-settle WAIT is the live example — it lives in
    the file bytes and the canonical serializer drops it, so only a byte compare
    can prove the two copies agree."""
    files = _corpus_files()
    drift = []
    for frozen in files:
        live = _ROUTINES_DIR / frozen.name
        assert live.is_file(), f"corpus plan has no live routine: {live}"
        if live.read_bytes() != frozen.read_bytes():
            drift.append(frozen.name)
    assert not drift, (
        f"corpus plans differ byte-for-byte from routines/: {drift}. "
        "Re-freeze the corpus copies (byte-identical) and record the diff in "
        "the ledger — the corpus predates P2 and must never drift silently."
    )


# --------------------------------------------------------------------------- #
# 4. every frozen plan still loads and validates clean                         #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", [f.name for f in sorted(_CORPUS_DIR.glob("*.yaml"))])
def test_corpus_plan_loads_and_validates_clean(name):
    """Each frozen plan loads via the real ``ScanPlan.load_yaml`` (the Load-routine
    path) and validates with 0 ERROR / 0 WARNING under bench-realistic limits.

    A WARNING counts as a failure on purpose: the README's claim is "all validate
    with 0 errors / 0 warnings", and a grammar migration that starts warning
    (unknown key, unknown reduce, dropped param) is exactly the silent breakage
    this corpus exists to catch."""
    _corpus_files()                               # anti-vacuous floor first
    plan = ScanPlan.load_yaml(str(_CORPUS_DIR / name))
    assert plan.root, f"{name} loaded to an empty plan"

    issues = validate_plan(plan, BENCH_LIMITS)
    assert errors(issues) == [], f"{name} has validation ERRORs: {errors(issues)}"
    assert warnings(issues) == [], f"{name} has validation WARNINGs: {warnings(issues)}"


def test_parametrization_covered_every_corpus_plan():
    """Guard for the guard: the parametrized ids above are computed at import
    time from a glob, so an empty/short corpus would silently collect ZERO
    validation tests.  This asserts the floor independently of that glob."""
    assert len(_corpus_files()) >= MIN_CORPUS_PLANS
