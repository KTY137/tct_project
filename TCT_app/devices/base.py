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

    @property
    def transport_lock(self) -> "threading.RLock":
        """The one object a caller must hold for exclusive use of this
        device's transport (serial port, VISA session, SDK handle).

        Hold it to keep a *sequence* of driver calls free of interleaving —
        e.g. a capability reservation, or a query whose reply must not be
        picked up by another thread's read.  Per-exchange serialisation is
        already the driver's own job; this exposes the same lock so an outside
        caller can widen that guarantee without reaching into private state.

        Default: :attr:`io_lock`, which is what every driver's I/O takes.
        A driver that serialises its I/O on a *different* lock MUST override
        this to return that very lock (``GRBLMotorStage`` returns its
        ``_lock``).  A second, parallel lock over one transport is a lie: the
        caller holds one, the driver takes the other, and the exchanges
        interleave exactly as before.

        Contract for overrides:
          * ``is``-identical to the lock the driver's own I/O acquires,
          * re-entrant (a holder may call driver methods that lock again),
          * **never** acquired by an emergency-stop path — a locked ``stop()``
            would be queued behind the very move it must interrupt.
        """
        return self.io_lock

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
