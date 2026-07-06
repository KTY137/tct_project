"""
Multi-channel bias supply control panel.

A single physical HV supply can expose several output channels (see
``devices.bias_channel.BiasChannel``).  ``MultiBiasPanel`` presents one
:class:`~gui.bias_panel.BiasPanel` per channel inside a tab widget, plus a
prominent global "ALL OUTPUTS OFF" safety control above the tabs.

Design / safety notes:
  * Constructing the panel performs **no** hardware I/O — each per-channel
    ``BiasPanel`` only polls once its channel reports ``connected``.
  * A single channel renders as one tab, so the single-channel experience is
    essentially unchanged from the old single ``BiasPanel``.
  * "ALL OUTPUTS OFF" ramps + disables every connected channel **off** the GUI
    thread (reusing ``BiasPanel``'s ``_SupplyCallWorker`` pattern), and fails
    safe: it keeps switching off the remaining channels even if one errors, then
    reports the aggregated failure via the app status bus.
  * The bias+waveform (vscan) controls belong to the primary channel (the scan
    controller is bound to the primary supply), so only the primary panel's
    ``vscan_requested`` is surfaced here.
"""
from __future__ import annotations

from PySide6.QtCore import Signal, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPushButton,
)

from devices.bias_channel import BiasChannel
from controller.scan_controller import VoltageScanConfig
from gui.bias_panel import BiasPanel, _SupplyCallWorker
from gui.status_bus import notify


class MultiBiasPanel(QWidget):
    """Tabbed control surface for one or more HV bias channels."""

    # Re-emitted from the primary channel's panel so the main window can wire a
    # single, stable signal that survives channel rebuilds.
    vscan_requested = Signal(VoltageScanConfig)

    def __init__(self, channels: list[BiasChannel], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channels: list[BiasChannel] = list(channels or [])
        self._panels: list[BiasPanel] = []
        self._off_thread: QThread | None = None
        self._off_worker: _SupplyCallWorker | None = None
        self._build_ui()
        self._build_tabs(self._channels)

    # ------------------------------------------------------------------ #
    # UI construction                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self._btn_all_off = QPushButton("⏹ ALL OUTPUTS OFF")
        self._btn_all_off.setObjectName("dangerBtn")
        self._btn_all_off.setToolTip(
            "Ramp EVERY connected HV channel to 0 V and disable its output."
        )
        self._btn_all_off.clicked.connect(self._all_outputs_off)
        top.addWidget(self._btn_all_off)
        top.addStretch()
        root.addLayout(top)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

    def _build_tabs(self, channels: list[BiasChannel]) -> None:
        self._channels = list(channels or [])
        self._panels = []
        for ch in self._channels:
            panel = BiasPanel(ch)
            self._panels.append(panel)
            self._tabs.addTab(panel, f"CH{getattr(ch, 'channel', '?')}")
        # The primary channel (proxy index 0 in the normal single-primary
        # config) owns the bias+waveform scan controls; surface only its signal.
        if self._panels:
            self._panels[0].vscan_requested.connect(self.vscan_requested)

    # ------------------------------------------------------------------ #
    # Primary-channel forwarding (stable API across rebuilds)             #
    # ------------------------------------------------------------------ #

    @property
    def primary_panel(self) -> BiasPanel | None:
        return self._panels[0] if self._panels else None

    def on_vscan_point(self, voltage_V: float, charge_pC: float, current_A: float) -> None:
        """Forward a bias+waveform scan point to the primary channel's plot."""
        if self._panels:
            self._panels[0]._on_vscan_point_cb(voltage_V, charge_pC, current_A)

    def set_reading(self, r) -> None:
        """Clear/refresh the readout on every tab (used on disconnect).

        Live per-tab readout is driven by each panel's own poll thread; this is
        the hook the main window calls (with ``None``) to blank the display.
        """
        for panel in self._panels:
            panel.set_reading(r)

    # ------------------------------------------------------------------ #
    # Channel-count refresh                                               #
    # ------------------------------------------------------------------ #

    def rebuild(self, channels: list[BiasChannel]) -> None:
        """Rebuild the tabs from a new channel list (after connect enumerates
        the supply's real channel count via ``refresh_bias_channels``).

        No-ops when the channel set is unchanged so the common single-channel
        reconnect keeps the existing panels (and their plot state) intact.
        """
        new_ids = [getattr(c, "channel", i) for i, c in enumerate(channels or [])]
        cur_ids = [getattr(c, "channel", i) for i, c in enumerate(self._channels)]
        if new_ids == cur_ids and self._panels:
            return
        for panel in self._panels:
            try:
                panel.shutdown()
            except Exception:
                pass
        while self._tabs.count():
            w = self._tabs.widget(0)
            self._tabs.removeTab(0)
            if w is not None:
                w.deleteLater()
        self._build_tabs(channels)

    # ------------------------------------------------------------------ #
    # Global ALL OUTPUTS OFF (off the GUI thread)                         #
    # ------------------------------------------------------------------ #

    def _all_outputs_off(self) -> None:
        if self._off_thread is not None and self._off_thread.isRunning():
            return
        live = [c for c in self._channels if getattr(c, "connected", False)]
        if not live:
            notify("No connected HV channels to switch off.", "warn")
            return

        self._btn_all_off.setEnabled(False)
        self._off_worker = _SupplyCallWorker(lambda: self._do_all_off(live))
        self._off_thread = QThread(self)
        self._off_worker.moveToThread(self._off_thread)
        self._off_thread.started.connect(self._off_worker.run)

        def _finish(err: str) -> None:
            thread = self._off_thread
            self._off_thread = None
            self._off_worker = None
            if thread is not None:
                thread.quit()
                thread.wait(2000)
            self._btn_all_off.setEnabled(True)
            if err:
                notify(f"ALL OUTPUTS OFF: {err}", "error")
            else:
                notify("All HV outputs ramped to 0 V and disabled.", "info")

        self._off_worker.done.connect(_finish)
        self._off_thread.start()

    @staticmethod
    def _do_all_off(channels: list[BiasChannel]) -> None:
        """Ramp every channel to 0 V and disable it.  Fail-safe: keep going even
        if one channel errors, then raise the aggregated failure.

        ramp_to and output_off are attempted in SEPARATE try blocks: disabling
        the output is the safety-critical action, so it must run even if the
        ramp raised part-way (a ramp error must never leave a channel energized).
        """
        errors: list[str] = []
        for ch in channels:
            label = f"CH{getattr(ch, 'channel', '?')}"
            try:
                ch.ramp_to(0.0, step_V=20.0, delay_s=0.05)
            except Exception as exc:
                errors.append(f"{label} ramp: {exc}")
            try:
                ch.output_off()          # always attempt, even if the ramp failed
            except Exception as exc:
                errors.append(f"{label} output-off: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))

    # ------------------------------------------------------------------ #
    # Teardown                                                            #
    # ------------------------------------------------------------------ #

    def shutdown(self) -> None:
        """Stop every owned thread (the ALL-OFF worker + each panel's poll
        thread) before the widget is discarded."""
        try:
            if self._off_thread is not None and self._off_thread.isRunning():
                self._off_thread.quit()
                self._off_thread.wait(2000)
        except Exception:
            pass
        for panel in self._panels:
            try:
                panel.shutdown()
            except Exception:
                pass
