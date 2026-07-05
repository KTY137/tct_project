from enum import Enum, auto
from typing import Callable
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

    @property
    def state(self) -> AppState:
        return self._state

    def can(self, target: AppState) -> bool:
        return target in _TRANSITIONS.get(self._state, set())

    def transition(self, target: AppState) -> None:
        if not self.can(target):
            raise ValueError(f"Invalid transition: {self._state.name} → {target.name}")
        old = self._state
        self._state = target
        logger.info("State: %s → %s", old.name, target.name)
        for cb in list(self._callbacks):
            try:
                cb(old, target)
            except Exception:
                logger.exception("State callback failed")

    def add_callback(self, cb: Callable[[AppState, AppState], None]) -> None:
        self._callbacks.append(cb)
