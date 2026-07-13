"""
Bias supply backend using an optional local e4control checkout.

e4control is a device-control library collection kept as local-only reference
material when available; it is intentionally not tracked in the main Git repo.
This backend wraps e4control's K2410 (or K487/K617) device class so the rest
of the TCT application can use it transparently through the BiasSupplyBase
interface.

Supported e4control device classes
-----------------------------------
K2410  — Keithley 2410 SMU (most common in TCT setups)
K487   — Keithley 487 picoammeter/HV source
K617   — Keithley 617 electrometer
K2614  — Keithley 2614 dual SMU

Connection types (e4control Device base)
-----------------------------------------
"gpib"      — VISA-GPIB via vxi11 (host = GPIB gateway IP, port = GPIB address)
"lan"       — TCP/IP (host = instrument IP, port = TCP port)
"prologix"  — Prologix GPIB-USB adapter (host = COM port or IP)
"serial"    — direct RS-232 / pylink TCP

Config keys  (devices.yaml → bias_supply, backend: e4control)
-------------------------------------------------------------
e4c_device      : "K2410"          # e4control class name
connection_type : "gpib"           # gpib | lan | prologix | serial
host            : "192.168.1.100"  # GPIB gateway IP (or COM port for prologix)
port            : 22               # GPIB address (or TCP port)
compliance_A    : 100.0e-6         # current compliance — set before apply!
ramp_step_V     : 10               # built-in ramp step (V)
ramp_delay_s    : 1                # built-in ramp delay (s)
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

from .base import DeviceError
from .bias_supply_base import BiasSupplyBase, BiasReading

logger = logging.getLogger(__name__)

# Candidate roots that contain the importable ``e4control`` package, tried in
# order.  The first supports an optional local vendored copy; the second is the
# root-level local-only reference checkout.
_E4C_ROOTS = [
    Path(__file__).parent.parent / "vendor",                       # TCT_app/vendor
    Path(__file__).parents[2] / "reference" / "e4control",
]


def _import_e4control_device(class_name: str) -> Any:
    """
    Import *class_name* from the bundled e4control package.

    Adds the first existing e4control root to sys.path if it isn't already
    present so this works without a pip install of e4control.
    """
    for root in _E4C_ROOTS:
        if (root / "e4control").is_dir():
            e4c_root = str(root)
            if e4c_root not in sys.path:
                sys.path.insert(0, e4c_root)
            break

    try:
        from e4control.devices import __init__ as _  # noqa: F401 (side-effect import)
        import importlib
        devices_mod = importlib.import_module("e4control.devices")
        cls = getattr(devices_mod, class_name, None)
        if cls is None:
            # Try direct submodule (e.g. K2410 lives in e4control.devices.K2410)
            submod = importlib.import_module(f"e4control.devices.{class_name}")
            cls = getattr(submod, class_name)
        return cls
    except (ImportError, AttributeError) as exc:
        roots = " or ".join(str(r) for r in _E4C_ROOTS)
        raise DeviceError(
            f"Cannot find e4control device class '{class_name}' "
            f"in {roots}.\n"
            f"Available devices: K2410, K2614, K487, K617, K196, K2000\n"
            f"Original error: {exc}"
        ) from exc


class E4ControlBiasSupply(BiasSupplyBase):
    """
    Bias supply backend that delegates to a local e4control device class.

    The e4control library is NOT pip-installed by the app. When used, it is
    imported from a local vendor or reference checkout at connect time.
    """

    # Fail-safe teardown: 1 initial ramp-down attempt + 1 retry before giving up
    # and surfacing the failure loudly (see disconnect / _shutdown_output).
    _SHUTDOWN_ATTEMPTS = 2

    def __init__(
        self,
        e4c_device: str = "K2410",
        connection_type: str = "gpib",
        host: str = "192.168.1.100",
        port: int | str = 22,
        compliance_A: float = 100e-6,
        ramp_step_V: float = 10.0,
        ramp_delay_s: float = 1.0,
        simulation: bool = False,
        **_kwargs: Any,
    ) -> None:
        super().__init__(simulation=simulation)
        self._e4c_device_name = e4c_device
        self._connection_type = connection_type
        self._host = host
        self._port = int(port) if str(port).isdigit() else port
        self._compliance_A = compliance_A
        self._ramp_step_V = ramp_step_V
        self._ramp_delay_s = ramp_delay_s
        self._dev = None

    # ------------------------------------------------------------------ #
    # BaseDevice interface                                                 #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        if self.simulation:
            self._connected = True
            logger.info("E4ControlBiasSupply: simulation mode (%s)", self._e4c_device_name)
            return

        cls = _import_e4control_device(self._e4c_device_name)
        try:
            self._dev = cls(self._connection_type, self._host, self._port)
        except Exception as exc:
            raise DeviceError(
                f"e4control {self._e4c_device_name} connect failed "
                f"({self._connection_type} {self._host}:{self._port}): {exc}"
            ) from exc

        # Configure as voltage source
        try:
            self._dev.initialize()
        except Exception:
            pass  # not all devices have initialize()

        # The link is up, so the driver counts as connected BEFORE the
        # compliance-then-park-at-0 V init below: set_voltage() goes through
        # _require_connected(), which would otherwise raise here and make this
        # backend impossible to connect at all.  A failing init rolls the flag
        # back rather than leaving a half-configured supply claiming "connected".
        self._connected = True
        try:
            self.set_compliance(self._compliance_A)   # compliance BEFORE any HV
            self.set_voltage(0.0)                     # park at 0 V
        except Exception as exc:
            self._connected = False
            raise DeviceError(
                f"e4control {self._e4c_device_name}: compliance/park-at-0V init "
                f"failed: {exc}"
            ) from exc
        logger.info(
            "e4control %s connected (%s %s:%s)",
            self._e4c_device_name, self._connection_type, self._host, self._port,
        )

    def disconnect(self) -> None:
        """Ramp the output to 0 V and switch it off, THEN close the link.

        Fail-safe, and never fail-silent: a supply that refuses to come down is
        logged at ERROR, keeps its TRUTHFUL local state (not a fabricated
        "0 V / off"), and the failure is raised so it reaches the operator.
        Mirrors IsegBiasSupply.disconnect().  ``rampVoltage(0)`` is only issued
        when the output is actually ON — never enable HV to walk it to zero.
        """
        failure: Exception | None = None
        if self._dev is not None and not self.simulation:
            try:
                self._shutdown_output()
            except Exception as exc:
                failure = exc
                logger.error(
                    "e4control: fail-safe ramp-down FAILED on disconnect after %d "
                    "attempts — THE OUTPUT MAY STILL BE ENERGIZED. Verify the "
                    "supply physically. Last error: %s",
                    self._SHUTDOWN_ATTEMPTS, exc,
                )
            try:
                self._dev.close()
            except Exception as exc:
                logger.warning("e4control: closing the device link failed: %s", exc)
        self._dev = None
        self._connected = False
        if failure is not None:
            raise DeviceError(
                f"e4control disconnect: fail-safe ramp-down FAILED ({failure}) — "
                "the output may still be energized. The link has been closed; "
                "verify the supply physically before leaving the setup."
            )
        self._setpoint_V = 0.0
        self._output_on = False

    def _shutdown_output(self) -> None:
        """Bring the output to 0 V and switch it off — **raises** on failure.

        Retried once: ``setVoltage(0)`` / ``setOutput(False)`` are idempotent and
        drive the supply toward the SAME safe state, so re-issuing them after a
        dropped frame cannot raise the voltage.

        ``rampVoltage(0)`` and ``setVoltage(0)`` are both a COURTESY (a smooth
        descent); ``setOutput(False)`` is the SAFETY GUARANTEE.  Each lives in
        its OWN try, so a transport that rejects value writes but would accept
        the disable still gets it issued — the load-bearing step never lives
        behind the ramp.  Local state is updated only once the hardware has
        acknowledged; a failed disable leaves the state UNKNOWN (believed-ON),
        never a false OFF.
        """
        last: Exception | None = None
        for attempt in range(self._SHUTDOWN_ATTEMPTS):
            with self.io_lock:
                # Courtesy 1: walk the HV down gently while the output is on.
                try:
                    if self._output_on:
                        self._dev.rampVoltage(0)
                except Exception as exc:
                    logger.warning(
                        "e4control: gentle ramp-down attempt %d/%d failed (%s) — "
                        "attempting the output-disable regardless.",
                        attempt + 1, self._SHUTDOWN_ATTEMPTS, exc,
                    )
                # Courtesy 2: park the register at 0 V (also a value write).
                zeroed = True
                try:
                    self._dev.setVoltage(0.0)
                except Exception as exc:
                    zeroed = False
                    logger.warning(
                        "e4control: 0 V park attempt %d/%d failed (%s) — "
                        "attempting the output-disable regardless.",
                        attempt + 1, self._SHUTDOWN_ATTEMPTS, exc,
                    )
                # SAFETY GUARANTEE: disable the output, isolated from every value
                # write above so it is attempted even when the ramp/park could not.
                try:
                    self._dev.setOutput(False)
                except Exception as exc:
                    last = exc
                    logger.warning(
                        "e4control: output-disable attempt %d/%d failed: %s",
                        attempt + 1, self._SHUTDOWN_ATTEMPTS, exc,
                    )
                    continue
            self._output_on = False
            if zeroed:
                self._setpoint_V = 0.0
            logger.info("e4control output switched OFF (disconnect)")
            return
        raise DeviceError(
            f"output-disable failed after {self._SHUTDOWN_ATTEMPTS} attempts: {last}"
        )

    # ------------------------------------------------------------------ #
    # BiasSupplyBase interface                                             #
    # ------------------------------------------------------------------ #

    def set_voltage(self, voltage_V: float) -> None:
        """Command a new setpoint (no ramp).  Hardware FIRST, local state after —
        a write that failed must not advance the driver's idea of the setpoint."""
        self._require_connected()
        self.check_voltage_in_range(voltage_V)
        if not (self.simulation or self._dev is None):
            with self.io_lock:
                self._dev.setVoltage(float(voltage_V))
        self._setpoint_V = voltage_V

    def set_compliance(self, current_A: float) -> None:
        """Set the HV CURRENT LIMIT.  Hardware FIRST, local state after.

        Recording first meant a failed write left the driver believing a limit
        the supply never took (e.g. 10 µA while the hardware kept a far higher
        one) — and the scan's trip detection then compares readings against a
        limit that does not exist.  On failure the OLD value stays in place and
        the exception reaches the caller.
        """
        if not (self.simulation or self._dev is None):
            self._dev.setCurrentLimit(float(current_A))
            logger.debug("Compliance set to %.3e A", current_A)
        self._compliance_A = current_A

    def enable_output(self) -> None:
        self._require_connected()
        if not self.simulation and self._dev is not None:
            self._dev.setOutput(True)
        self._output_on = True
        logger.info("e4control output ON")

    def output_off(self) -> None:
        """Switch the output off.  Fail-safe: never raises.

        Abort / ``finally`` paths depend on this not raising, so the non-raising
        contract is kept — but it must not *lie* either: a write that FAILED no
        longer clears the local ``_output_on`` flag (which would claim an OFF
        that was never achieved).  The failure is logged at ERROR and the state
        is left as-is, so the UI keeps showing the channel as ON — the truth,
        because we do not know that it is off.

        The ``setVoltage(0)`` write is a COURTESY (a disabled output holds no HV
        anyway); the ``setOutput(False)`` disable is the SAFETY GUARANTEE.  Each
        gets its OWN try so a dropped 0 V frame can NEVER suppress the disable.
        """
        zeroed = True
        if not self.simulation and self._dev is not None:
            with self.io_lock:
                try:
                    self._dev.setVoltage(0.0)                # cosmetic
                except Exception as exc:
                    zeroed = False
                    logger.warning(
                        "e4control: cosmetic 0 V write failed (%s) — proceeding "
                        "to the safety-critical output-disable regardless.", exc,
                    )
                try:
                    self._dev.setOutput(False)               # the guarantee
                except Exception as exc:
                    logger.error(
                        "e4control: OUTPUT-OFF WRITE FAILED (%s) — the output may "
                        "still be ENERGIZED; leaving local state ON rather than "
                        "claiming an OFF we never achieved.", exc,
                    )
                    return
        self._output_on = False
        if zeroed:
            self._setpoint_V = 0.0
        logger.info("e4control output OFF")

    def read(self) -> BiasReading:
        if self.simulation:
            import random
            return BiasReading(
                voltage_V=self._setpoint_V,
                current_A=self._setpoint_V * 1e-9 + random.gauss(0, 1e-11),
                compliant=False,
            )
        try:
            with self.io_lock:  # GUI bias poller + scan thread share the link
                v = float(self._dev.getVoltage())
                i = float(self._dev.getCurrent())
            compliant = abs(i) >= self._compliance_A * 0.99
            return BiasReading(voltage_V=v, current_A=i, compliant=compliant)
        except Exception as exc:
            logger.warning("e4control read error: %s", exc)
            return BiasReading(
                voltage_V=self._setpoint_V, current_A=float("nan"), compliant=False
            )

    def ramp_to(
        self,
        target_V: float,
        step_V: float = 5.0,
        delay_s: float = 0.1,
    ) -> None:
        """
        Ramp to target_V using e4control's built-in rampVoltage when connected
        to a real device, otherwise use the base-class step ramp.

        SAFETY — like BiasSupplyBase.ramp_to, a ramp to zero NEVER enables an
        idle output (rule 1: never auto-enable HV).  This override re-implements
        the ramp locally, so it must re-implement the guard locally too: fixing
        only the base class would leave this third HV backend energizing a
        channel on every fail-safe "ramp to 0 V, then switch off" path.
        """
        self._require_connected()
        self.check_voltage_in_range(target_V)
        if self.simulation or self._dev is None:
            super().ramp_to(target_V, step_V=step_V, delay_s=delay_s)
            return

        if not self._output_on:
            if target_V == 0.0:
                # Park the setpoint register only — a write to a disabled output
                # moves no HV.  set_voltage() records after the write, so a
                # failed write cannot leave a 0 V claim we never achieved.
                self.set_voltage(0.0)
                return
            self.enable_output()      # genuine energize request only

        # Update ramp params on the device object for this call
        ramp_step = max(abs(step_V), 1.0)
        self._dev.setRampSpeed(int(ramp_step), max(delay_s, 0.05))

        # e4control rampVoltage is recursive — use the base class loop instead
        # to avoid deep recursion on large voltage swings
        current = self._setpoint_V
        sign = 1.0 if target_V >= current else -1.0
        while abs(target_V - current) > ramp_step / 2:
            current += sign * ramp_step
            if sign > 0:
                current = min(current, target_V)
            else:
                current = max(current, target_V)
            self._dev.setVoltage(current)
            self._setpoint_V = current
            time.sleep(delay_s)
            if self.read().compliant:
                logger.warning("Compliance trip at %.1f V during ramp", current)
                break

        self._dev.setVoltage(target_V)
        self._setpoint_V = target_V
