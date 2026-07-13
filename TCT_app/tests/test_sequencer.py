"""Tests for controller.sequencer — the pure queue-state engine + persistence.

Pure pytest: no Qt, no threads, no device access.  Covers the advance/halt
matrix (finished advances; error/aborted halt with remaining SKIPPED), a
preflight veto halt, mid-queue cancel semantics, record_outcome guards, the
next_entry double-run guard, progress/is_complete across a full run, and YAML
round-trip + fail-closed malformed-entry loading.
"""
from __future__ import annotations

import pytest

from controller.scan_plan import (
    ActionBlock, ActionType, Axis, LoopBlock, ScanPlan,
)
from controller.sequencer import (
    EntryState, NullPreflight, PreflightResult, SequenceEntry, SequenceRunner,
    assert_sequencer_compatible, load_sequence_yaml, save_sequence_yaml,
)


# --------------------------------------------------------------------------- #
# tiny plan / entry builders (cheapest existing pattern, per test_arm_envelope) #
# --------------------------------------------------------------------------- #
def _plan(name: str, values=(0.0, 1.0)) -> ScanPlan:
    loop = LoopBlock(
        axis=Axis.STAGE_X,
        values=[float(v) for v in values],
        children=[
            ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={}),
            ActionBlock(action=ActionType.SAVE_POINT, params={}),
        ],
    )
    return ScanPlan(name=name, root=[loop])


def _entry(name: str, values=(0.0, 1.0), source_path=None) -> SequenceEntry:
    return SequenceEntry(name=name, plan=_plan(name, values),
                         source_path=source_path)


def _plan_with_manual_pause(name: str, *, trailing: bool) -> ScanPlan:
    """A plan whose COMPILED step list contains a ManualPauseStep.

    ``trailing=True`` puts the manual_pause as the LAST compiled step (Mary's
    PAUSED->FINISHED silent-skip case); ``trailing=False`` places it mid-plan
    with acquire/save steps following it (Mary's wedge-holding-HV case).  Built
    as a plain ``SequenceEntry``/``ScanPlan`` — neither is gated — so the fixture
    itself never trips the guard under test.
    """
    pause = ActionBlock(action=ActionType.MANUAL_PAUSE,
                        params={"prompt": "change the laser filter"})
    acquire = ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={})
    save = ActionBlock(action=ActionType.SAVE_POINT, params={})
    if trailing:
        # single point → move, acquire, save, manual_pause: pause compiles LAST.
        loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                         children=[acquire, save, pause])
    else:
        # two points → the pause has acquire/save (and the next point) after it.
        loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0],
                         children=[pause, acquire, save])
    return ScanPlan(name=name, root=[loop])


def _pause_entry(name: str, *, trailing: bool) -> SequenceEntry:
    return SequenceEntry(name=name,
                         plan=_plan_with_manual_pause(name, trailing=trailing))


def _runner(n=3, preflight=None) -> SequenceRunner:
    entries = [_entry(f"routine_{i}") for i in range(n)]
    return SequenceRunner(entries, preflight=preflight)


class _VetoPreflight:
    """Preflight that vetoes a named entry (else passes)."""

    def __init__(self, veto_name: str, message: str = "focus lost") -> None:
        self._veto = veto_name
        self._message = message

    def run(self, entry: SequenceEntry) -> PreflightResult:
        if entry.name == self._veto:
            return PreflightResult(ok=False, message=self._message)
        return PreflightResult(ok=True)


class _RaisingPreflight:
    """Preflight whose hook RAISES (models a buggy / hardware-faulting check)."""

    def __init__(self, message: str = "focus probe exploded") -> None:
        self._message = message

    def run(self, entry: SequenceEntry) -> PreflightResult:
        raise RuntimeError(self._message)


# --------------------------------------------------------------------------- #
# advance: a clean finish lets the next entry run                              #
# --------------------------------------------------------------------------- #
def test_finished_advances_to_next():
    r = _runner(2)
    e0 = r.next_entry()
    assert e0 is r.entries[0]
    assert e0.state is EntryState.RUNNING
    assert r.current is e0

    r.record_outcome("finished")
    assert e0.state is EntryState.DONE
    assert r.current is None

    e1 = r.next_entry()
    assert e1 is r.entries[1]
    assert e1.state is EntryState.RUNNING

    r.record_outcome("finished")
    assert e1.state is EntryState.DONE
    assert r.next_entry() is None      # queue exhausted
    assert r.is_complete is True
    assert r.progress == (2, 2)


# --------------------------------------------------------------------------- #
# halt matrix: a bad outcome fails the entry and SKIPS the remainder           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_outcome", ["error", "aborted"])
def test_bad_outcome_halts_and_skips_remainder(bad_outcome):
    r = _runner(3)
    e0 = r.next_entry()
    r.record_outcome(bad_outcome)

    assert e0.state is EntryState.FAILED
    assert bad_outcome in e0.message
    assert [e.state for e in r.entries[1:]] == [EntryState.SKIPPED,
                                                EntryState.SKIPPED]
    assert r.next_entry() is None      # halted: nothing PENDING remains
    assert r.is_complete is True
    assert r.progress == (3, 3)


# --------------------------------------------------------------------------- #
# preflight veto halts before the entry ever runs                              #
# --------------------------------------------------------------------------- #
def test_preflight_veto_fails_entry_and_halts():
    r = _runner(3, preflight=_VetoPreflight("routine_0", "no focus"))
    result = r.next_entry()

    assert result is None                       # vetoed → no entry to run
    assert r.entries[0].state is EntryState.FAILED
    assert r.entries[0].message == "no focus"
    assert [e.state for e in r.entries[1:]] == [EntryState.SKIPPED,
                                                EntryState.SKIPPED]
    assert r.is_complete is True


def test_preflight_veto_only_halts_after_the_vetoed_entry():
    # First entry passes and finishes; the SECOND is vetoed → it fails, the
    # third is skipped, the first stays DONE.
    r = _runner(3, preflight=_VetoPreflight("routine_1"))
    r.next_entry()
    r.record_outcome("finished")
    assert r.entries[0].state is EntryState.DONE

    assert r.next_entry() is None               # routine_1 vetoed
    assert r.entries[1].state is EntryState.FAILED
    assert r.entries[2].state is EntryState.SKIPPED
    assert r.progress == (3, 3)


def test_preflight_hook_that_raises_fails_entry_and_halts():
    """MINOR (Mary): a preflight hook that RAISES must not strand the entry in
    PREFLIGHT (which would wedge the queue — next_entry() would then forever
    refuse to advance past it).  The engine owns the outcome: fail the culprit
    closed with the exception text and halt, exactly like a veto, without relying
    on the coordinator to catch the exception."""
    r = _runner(3, preflight=_RaisingPreflight("focus probe exploded"))
    result = r.next_entry()

    assert result is None                       # nothing runs
    assert r.entries[0].state is EntryState.FAILED
    assert "focus probe exploded" in r.entries[0].message
    assert [e.state for e in r.entries[1:]] == [EntryState.SKIPPED,
                                                EntryState.SKIPPED]
    assert r.is_complete is True
    # The failure is on the record (a log line), not silently swallowed.
    assert any("-> failed" in line and "focus probe exploded" in line
               for line in r.log)


# --------------------------------------------------------------------------- #
# cancel mid-queue                                                             #
# --------------------------------------------------------------------------- #
def test_cancel_mid_queue_cancels_running_and_pending():
    r = _runner(3)
    r.next_entry()                              # routine_0 RUNNING
    r.record_outcome("finished")                # routine_0 DONE
    e1 = r.next_entry()                         # routine_1 RUNNING

    r.cancel()
    assert r.entries[0].state is EntryState.DONE        # preserved
    assert e1.state is EntryState.CANCELLED
    assert e1.message == "sequence aborted"
    assert r.entries[2].state is EntryState.CANCELLED
    assert r.is_complete is True
    assert r.current is None


def test_cancel_between_entries_cancels_all_pending():
    r = _runner(2)
    r.cancel()                                  # nothing running yet
    assert all(e.state is EntryState.CANCELLED for e in r.entries)
    assert r.is_complete is True


# --------------------------------------------------------------------------- #
# record_outcome guards                                                        #
# --------------------------------------------------------------------------- #
def test_record_outcome_nonstandard_word_halts_instead_of_raising():
    """NEW semantics (Mary MINOR): record_outcome accepts ANY string; only the
    literal "finished" advances.  Every other word — the "unknown" the HDF5
    layer writes for a crashed run, or an unexpected caller word — FAILS the
    entry and HALTS the queue (remaining SKIPPED), with the word in the message.

    It deliberately does NOT raise: the crashed-run "unknown" is the outcome that
    most needs to halt an unattended overnight queue, so the outcome path must
    never throw (a raise would escape the engine and could strand the sequence).
    """
    for word in ("unknown", "gibberish", "done", "success"):
        r = _runner(3)
        r.next_entry()                          # an entry IS running
        r.record_outcome(word)                  # must NOT raise
        assert r.entries[0].state is EntryState.FAILED, word
        assert word in r.entries[0].message, word
        assert [e.state for e in r.entries[1:]] == [EntryState.SKIPPED,
                                                    EntryState.SKIPPED], word
        assert r.is_complete is True, word


def test_record_outcome_without_running_entry_raises_runtimeerror():
    r = _runner(1)
    with pytest.raises(RuntimeError):
        r.record_outcome("finished")            # nothing RUNNING yet


# --------------------------------------------------------------------------- #
# next_entry double-run guard                                                  #
# --------------------------------------------------------------------------- #
def test_next_entry_refuses_to_advance_while_running():
    r = _runner(3)
    r.next_entry()                              # routine_0 RUNNING
    with pytest.raises(RuntimeError):
        r.next_entry()                          # must record_outcome first


# --------------------------------------------------------------------------- #
# progress / is_complete across a full clean run                               #
# --------------------------------------------------------------------------- #
def test_progress_tracks_across_full_run():
    r = _runner(3)
    assert r.progress == (0, 3)
    assert r.is_complete is False

    r.next_entry(); r.record_outcome("finished")
    assert r.progress == (1, 3)
    assert r.is_complete is False

    r.next_entry(); r.record_outcome("finished")
    assert r.progress == (2, 3)

    r.next_entry(); r.record_outcome("finished")
    assert r.progress == (3, 3)
    assert r.is_complete is True
    assert all(e.state is EntryState.DONE for e in r.entries)


def test_empty_queue_is_trivially_complete():
    r = SequenceRunner([])
    assert r.is_complete is True
    assert r.progress == (0, 0)
    assert r.next_entry() is None


def test_default_preflight_is_null():
    r = SequenceRunner([_entry("solo")])
    assert isinstance(r._preflight, NullPreflight)
    e = r.next_entry()
    assert e.state is EntryState.RUNNING


def test_state_changes_are_logged():
    r = _runner(1)
    r.next_entry()
    r.record_outcome("finished")
    # created + PREFLIGHT + RUNNING + DONE lines, each timestamped.
    assert any("-> running" in line for line in r.log)
    assert any("-> done" in line for line in r.log)
    assert all(line.startswith("[") for line in r.log)


# --------------------------------------------------------------------------- #
# YAML round-trip: plans, names, order preserved                              #
# --------------------------------------------------------------------------- #
def test_yaml_round_trip_preserves_plans_names_and_order(tmp_path):
    entries = [
        _entry("alpha", values=(0.0, 1.0, 2.0), source_path="routines/a.yaml"),
        _entry("beta", values=(-5.0, 5.0), source_path=None),
        _entry("gamma", values=(3.0,), source_path="routines/g.yaml"),
    ]
    path = tmp_path / "seq.yaml"
    save_sequence_yaml(path, entries)

    loaded = load_sequence_yaml(path)
    assert [e.name for e in loaded] == ["alpha", "beta", "gamma"]
    assert [e.source_path for e in loaded] == [
        "routines/a.yaml", None, "routines/g.yaml",
    ]
    # plans compare byte-for-byte through their canonical dict form.
    for orig, got in zip(entries, loaded):
        assert got.plan.to_dict() == orig.plan.to_dict()
    # every loaded entry is a fresh PENDING (state is NOT persisted).
    assert all(e.state is EntryState.PENDING for e in loaded)


def test_yaml_load_ignores_persisted_state(tmp_path):
    # Save a queue that has already been partially run; the reload is all PENDING.
    r = _runner(2)
    r.next_entry(); r.record_outcome("finished")   # routine_0 DONE
    path = tmp_path / "seq.yaml"
    save_sequence_yaml(path, r.entries)
    loaded = load_sequence_yaml(path)
    assert [e.state for e in loaded] == [EntryState.PENDING, EntryState.PENDING]


# --------------------------------------------------------------------------- #
# fail-closed loading: malformed entry raises naming its index                 #
# --------------------------------------------------------------------------- #
def test_malformed_entry_missing_plan_raises_with_index(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "version: 1\n"
        "entries:\n"
        "  - name: ok\n"
        "    plan: {name: ok, root: []}\n"
        "  - name: broken\n"          # no 'plan' key
        "    source_path: null\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"\[1\]"):
        load_sequence_yaml(path)


def test_malformed_entry_bad_axis_raises_with_index(tmp_path):
    # A structurally valid entry whose PLAN is illegal (laser_power is not an
    # axis) must fail closed through ScanPlan.from_dict, naming the index.
    path = tmp_path / "bad_axis.yaml"
    path.write_text(
        "version: 1\n"
        "entries:\n"
        "  - name: fine\n"
        "    plan: {name: fine, root: []}\n"
        "  - name: cursed\n"
        "    plan:\n"
        "      name: cursed\n"
        "      root:\n"
        "        - {type: loop, axis: laser_power, values: [1.0], children: []}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"\[1\]"):
        load_sequence_yaml(path)


def test_unsupported_version_raises(tmp_path):
    path = tmp_path / "v2.yaml"
    path.write_text("version: 2\nentries: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        load_sequence_yaml(path)


def test_entries_not_a_list_raises(tmp_path):
    path = tmp_path / "notlist.yaml"
    path.write_text("version: 1\nentries: {}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_sequence_yaml(path)


# --------------------------------------------------------------------------- #
# fail-closed: manual_pause is incompatible with an UNATTENDED sequence        #
# (Mary A5.2a) — rejected at every add/load entry point, mid-plan AND trailing #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("trailing", [False, True])
def test_assert_sequencer_compatible_rejects_manual_pause(trailing):
    plan = _plan_with_manual_pause("night_shift", trailing=trailing)
    with pytest.raises(ValueError) as ei:
        assert_sequencer_compatible(plan, name="night_shift")
    msg = str(ei.value)
    assert "night_shift" in msg          # names the routine
    assert "manual_pause" in msg         # names the offending step kind


def test_assert_sequencer_compatible_passes_clean_plan():
    # A plan without any blacklisted step returns None (no raise), and falls back
    # to plan.name when no explicit name is given.
    assert assert_sequencer_compatible(_plan("clean")) is None


@pytest.mark.parametrize("trailing", [False, True])
def test_load_rejects_manual_pause_naming_index_and_routine(tmp_path, trailing):
    # A queue file whose SECOND entry carries a manual_pause plan fails closed on
    # load, naming the entry index AND the routine — never a shortened queue.
    entries = [
        _entry("clean_0"),
        _pause_entry("night_shift", trailing=trailing),
    ]
    path = tmp_path / "seq.yaml"
    save_sequence_yaml(path, entries)     # save is provenance-only, not gated

    with pytest.raises(ValueError) as ei:
        load_sequence_yaml(path)
    msg = str(ei.value)
    assert "[1]" in msg                   # the offending entry index
    assert "night_shift" in msg           # the routine
    assert "manual_pause" in msg          # the offending step kind


@pytest.mark.parametrize("trailing", [False, True])
def test_sequencerunner_init_rejects_manual_pause_entry(trailing):
    # Belt-and-braces: an entry built PROGRAMMATICALLY (no YAML path) is rejected
    # at SequenceRunner construction, so a bad entry can never enter a live queue.
    good = _entry("clean")
    bad = _pause_entry("cursed", trailing=trailing)
    with pytest.raises(ValueError) as ei:
        SequenceRunner([good, bad])
    msg = str(ei.value)
    assert "cursed" in msg
    assert "manual_pause" in msg


def test_clean_queue_still_loads_and_constructs(tmp_path):
    # Backward compatibility: a manual_pause-free queue is untouched by the gate —
    # it saves, loads and constructs a runner exactly as before.
    entries = [_entry("a"), _entry("b")]
    path = tmp_path / "clean.yaml"
    save_sequence_yaml(path, entries)
    loaded = load_sequence_yaml(path)
    assert [e.name for e in loaded] == ["a", "b"]
    r = SequenceRunner(loaded)
    assert r.progress == (0, 2)
    assert r.next_entry() is r.entries[0]
