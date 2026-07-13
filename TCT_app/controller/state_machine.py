from enum import Enum, auto
from typing import Callable
import threading
import logging

logger = logging.getLogger(__name__)


class AppState(Enum):
    DISCONNECTED = auto()
    CONNECTED = auto()
    HOMED = auto()
    CONFIGURED = auto()
    READY = auto()
    RUNNING = auto()
    PAUSED = auto()
    FINISHED = auto()
    ERROR = auto()
    ABORTED = auto()


# Valid state transitions.  DISCONNECTED is the universal reset state: a
# disconnect / config reload must be possible from anywhere (including a
# crashed scan), so every state may fall back to it.
_TRANSITIONS: dict[AppState, set[AppState]] = {
    AppState.DISCONNECTED: {AppState.CONNECTED},
    AppState.CONNECTED:    {AppState.HOMED},
    AppState.HOMED:        {AppState.CONFIGURED},
    AppState.CONFIGURED:   {AppState.READY, AppState.HOMED},
    AppState.RUNNING:      {AppState.PAUSED, AppState.FINISHED, AppState.ERROR, AppState.ABORTED},
    AppState.PAUSED:       {AppState.RUNNING, AppState.ABORTED},
    AppState.READY:        {AppState.RUNNING, AppState.CONFIGURED},
    AppState.FINISHED:     {AppState.CONFIGURED},
    AppState.ERROR:        {AppState.CONFIGURED},
    AppState.ABORTED:      {AppState.CONFIGURED},
}
for _state, _targets in _TRANSITIONS.items():
    if _state is not AppState.DISCONNECTED:
        _targets.add(AppState.DISCONNECTED)


class StateMachine:
    def __init__(self) -> None:
        self._state = AppState.DISCONNECTED
        self._callbacks: list[Callable[[AppState, AppState], None]] = []
        # Guards the check-then-act in transition() and every read/write of
        # _state and _callbacks.  transition() is called from BOTH the GUI thread
        # and scan worker threads; without this lock the can()->swap sequence is a
        # race and two transitions from the same state could both "win",
        # mislabelling the terminal state.  RLock (reentrant) because can() and
        # the state property take the same lock while transition() already holds
        # it.  Callbacks are invoked OUTSIDE this lock (see transition()).
        self._lock = threading.RLock()

    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state

    def can(self, target: AppState) -> bool:
        with self._lock:
            return target in _TRANSITIONS.get(self._state, set())

    def transition(self, target: AppState) -> None:
        # Re-check the guard and swap _state atomically under the lock so exactly
        # one of two racing transitions from the same state wins.  The loser
        # re-checks against the winner's new state and raises ValueError.
        # ValueError-on-race is a CONTRACT: scan_controller's
        # _settle_terminal_state / _settle_error_state retry loops re-read the
        # state and retry when transition() raises, so this exception (and its
        # exact message) must be preserved.
        with self._lock:
            if not self.can(target):
                raise ValueError(
                    f"Invalid transition: {self._state.name} → {target.name}"
                )
            old = self._state
            self._state = target
            # Freeze the callback list for THIS transition while still holding
            # the lock, then release before invoking any of them.
            callbacks = list(self._callbacks)
        logger.info("State: %s → %s", old.name, target.name)
        # Callbacks run OUTSIDE the lock on purpose: a callback may re-enter
        # transition() (the controller's settle/advance paths do), so holding a
        # non-reentrant section here would deadlock; and holding the lock across
        # GUI callback work would serialise it needlessly.
        for cb in callbacks:
            try:
                cb(old, target)
            except Exception:
                logger.exception("State callback failed")

    def add_callback(self, cb: Callable[[AppState, AppState], None]) -> None:
        with self._lock:
            self._callbacks.append(cb)
