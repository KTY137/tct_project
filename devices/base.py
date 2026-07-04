import logging
import threading
from abc import ABC, abstractmethod


class DeviceError(Exception):
    """Raised when a device operation fails."""


class BaseDevice(ABC):
    def __init__(self, simulation: bool = False):
        self.simulation = simulation
        self._connected = False
        self.logger = logging.getLogger(type(self).__name__)
        # Serialises hardware I/O: GUI pollers and the scan thread share one
        # VISA/serial session per device, and interleaved query/reply pairs
        # garble each other.  Re-entrant so nested driver calls are fine.
        self.io_lock = threading.RLock()

    @property
    def connected(self) -> bool:
        return self._connected

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...
