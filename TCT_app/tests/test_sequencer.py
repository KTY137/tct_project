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
    load_sequence_yaml, save_sequence_yaml,
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
def test_record_outcome_unknown_word_raises_valueerror():
    r = _runner(1)
    r.next_entry()                              # an entry IS running
    with pytest.raises(ValueError):
        r.record_outcome("done")                # not an HDF5 outcome word
    with pytest.raises(ValueError):
        r.record_outcome("success")


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
