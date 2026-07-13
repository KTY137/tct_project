"""State-machine tests: the full happy path must be walkable — regression for
the bug where nothing could ever reach READY and no scan could start."""
import pytest

from controller.state_machine import StateMachine, AppState


def walk(sm: StateMachine, *states: AppState) -> None:
    for s in states:
        sm.transition(s)


def test_happy_path_to_running_and_back():
    sm = StateMachine()
    walk(sm, AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED,
         AppState.READY, AppState.RUNNING, AppState.FINISHED,
         AppState.CONFIGURED, AppState.READY)
    assert sm.state == AppState.READY


def test_pause_resume_abort():
    sm = StateMachine()
    walk(sm, AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED,
         AppState.READY, AppState.RUNNING, AppState.PAUSED, AppState.RUNNING,
         AppState.ABORTED, AppState.CONFIGURED, AppState.READY)
    assert sm.state == AppState.READY


def test_error_recovers_to_ready():
    sm = StateMachine()
    walk(sm, AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED,
         AppState.READY, AppState.RUNNING, AppState.ERROR,
         AppState.CONFIGURED, AppState.READY)
    assert sm.state == AppState.READY


@pytest.mark.parametrize("state", [
    AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED, AppState.READY,
    AppState.RUNNING, AppState.PAUSED, AppState.FINISHED, AppState.ERROR,
    AppState.ABORTED,
])
def test_disconnect_reachable_from_everywhere(state):
    """DISCONNECTED is the universal reset (disconnect / config reload)."""
    sm = StateMachine()
    sm._state = state          # jump directly — we only test the edge
    sm.transition(AppState.DISCONNECTED)
    assert sm.state == AppState.DISCONNECTED


def test_cannot_run_before_ready():
    sm = StateMachine()
    sm.transition(AppState.CONNECTED)
    assert not sm.can(AppState.RUNNING)
    with pytest.raises(ValueError):
        sm.transition(AppState.RUNNING)


def test_callback_fires():
    sm = StateMachine()
    seen = []
    sm.add_callback(lambda old, new: seen.append((old, new)))
    sm.transition(AppState.CONNECTED)
    assert seen == [(AppState.DISCONNECTED, AppState.CONNECTED)]


def test_callback_can_reenter_transition_without_deadlock():
    """A state callback that itself calls transition() (the controller's
    settle/advance re-entrancy pattern) must not deadlock: callbacks run OUTSIDE
    the state lock, so re-entering transition() re-acquires it cleanly."""
    sm = StateMachine()
    walk(sm, AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED,
         AppState.READY, AppState.RUNNING)
    seen = []

    def on_change(old, new):
        seen.append((old, new))
        # On landing terminal, advance one more edge from within the callback —
        # this re-enters transition() while the outer transition() is unwinding.
        if new is AppState.FINISHED:
            sm.transition(AppState.CONFIGURED)

    sm.add_callback(on_change)
    sm.transition(AppState.FINISHED)          # must return, not hang
    assert sm.state is AppState.CONFIGURED
    assert (AppState.RUNNING, AppState.FINISHED) in seen
    assert (AppState.FINISHED, AppState.CONFIGURED) in seen
