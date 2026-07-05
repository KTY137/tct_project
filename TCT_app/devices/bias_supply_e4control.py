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

        self.set_compliance(self._compliance_A)
        self.set_voltage(0.0)
        self._connected = True
        logger.info(
            "e4control %s connected (%s %s:%s)",
            self._e4c_device_name, self._connection_type, self._host, self._port,
        )

    def disconnect(self) -> None:
        if self._dev is not None and not self.simulation:
            try:
                self._dev.rampVoltage(0)
                self._dev.setOutput(False)
            except Exception:
                pass
            try:
                self._dev.close()
            except Exception:
                pass
        self._dev = None
        self._connected = False
        self._setpoint_V = 0.0
        self._output_on = False

    # ------------------------------------------------------------------ #
    # BiasSupplyBase interface                                             #
    # ------------------------------------------------------------------ #

    def set_voltage(self, voltage_V: float) -> None:
        self._require_connected()
        self.check_voltage_in_range(voltage_V)
        self._setpoint_V = voltage_V
        if self.simulation or self._dev is None:
            return
        with self.io_lock:
            self._dev.setVoltage(float(voltage_V))

    def set_compliance(self, current_A: float) -> None:
        self._compliance_A = current_A
        if self.simulation or self._dev is None:
            return
        self._dev.setCurrentLimit(float(current_A))
        logger.debug("Compliance set to %.3e A", current_A)

    def output_on(self) -> None:
        self._require_connected()
        if not self.simulation and self._dev is not None:
            self._dev.setOutput(True)
        self._output_on = True
        logger.info("e4control output ON")

    def output_off(self) -> None:
        if not self.simulation and self._dev is not None:
            try:
                self._dev.setVoltage(0.0)
                self._dev.setOutput(False)
            except Exception:
                pass
        self._output_on = False
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
        """
        self._require_connected()
        self.check_voltage_in_range(target_V)
        if self.simulation or self._dev is None:
            super().ramp_to(target_V, step_V=step_V, delay_s=delay_s)
            return

        if not self._output_on:
            self.output_on()

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
