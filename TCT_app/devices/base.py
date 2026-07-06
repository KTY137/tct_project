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

    def is_alive(self) -> bool:
        """Cheap link-liveness check, polled by the DeviceManager monitor.

        Default implementation trusts the ``connected`` flag (for drivers
        without a cheap probe).  Overrides should verify the physical link
        (e.g. an IEEE 488.2 ``*STB?``) and set ``_connected = False`` when it
        is gone, so a yanked cable can never keep showing a green flag.
        Must be fast, must not change instrument state, and must never block
        on the io_lock (skip the probe when the device is mid-conversation).
        """
        return self._connected

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...
