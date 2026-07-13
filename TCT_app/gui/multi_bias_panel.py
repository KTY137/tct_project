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
    reports the aggregated failure via the app status bus.  It is deliberately
    **not** danger-gated: a stop can only make the setup safer, so it stays one
    tap (cockpit design law 5).
  * The injected :class:`~controller.danger_gate.DangerGate` is a pure
    pass-through to each per-channel ``BiasPanel`` (which confirms every
    HV-energizing action against it — CLAUDE.md rule 2); it survives
    :meth:`rebuild`, so channels enumerated after connect are gated too.
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
from controller.danger_gate import DangerGate
from controller.scan_controller import VoltageScanConfig
from gui.bias_panel import BiasPanel, _SupplyCallWorker
from gui.panel_kit import panel_header
from gui.status_bus import notify
from gui.status_widgets import StatusChip, set_button_icon


class MultiBiasPanel(QWidget):
    """Tabbed control surface for one or more HV bias channels."""

    # Re-emitted from the primary channel's panel so the main window can wire a
    # single, stable signal that survives channel rebuilds.
    vscan_requested = Signal(VoltageScanConfig)

    def __init__(self, channels: list[BiasChannel], parent: QWidget | None = None,
                 *, gate: DangerGate | None = None) -> None:
        super().__init__(parent)
        self._channels: list[BiasChannel] = list(channels or [])
        # Handed to every per-channel BiasPanel (and to any panel built later by
        # rebuild()): each one confirms its HV-energizing actions against it.
        self._gate = gate
        self._panels: list[BiasPanel] = []
        self._off_thread: QThread | None = None
        self._off_worker: _SupplyCallWorker | None = None
        # Manual-danger lock state (A5.1), forwarded to every child panel and
        # re-applied to channels enumerated later by rebuild() — the same
        # "survives a rebuild" contract the injected gate has.  The global
        # ALL OUTPUTS OFF is never gated by it (cockpit law 5).
        self._danger_locked = False
        self._build_ui()
        self._build_tabs(self._channels)

    # ------------------------------------------------------------------ #
    # UI construction                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # The danger control sits in the header's trailing slot — top-right,
        # ahead of the tabs, so it stays reachable and visible from any tab.
        self._btn_all_off = QPushButton("⏹ ALL OUTPUTS OFF")
        self._btn_all_off.setObjectName("dangerBtn")
        set_button_icon(self._btn_all_off, "mdi.power", color="white")
        self._btn_all_off.setToolTip(
            "Ramp EVERY connected HV channel to 0 V and disable its output."
        )
        self._btn_all_off.clicked.connect(self._all_outputs_off)
        root.addWidget(panel_header(
            "TCT Control — High Voltage", "Bias Supplies",
            trailing=[self._btn_all_off],
        ))

        status_row = QHBoxLayout()
        self._chip_all_off = StatusChip("All-off idle", "neutral")
        self._chip_channels = StatusChip("Channels --", "neutral")
        self._chip_compliance = StatusChip("Compliance --", "neutral")
        status_row.addWidget(self._chip_all_off)
        status_row.addWidget(self._chip_channels)
        status_row.addWidget(self._chip_compliance)
        status_row.addStretch()
        root.addLayout(status_row)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

    def _build_tabs(self, channels: list[BiasChannel]) -> None:
        self._channels = list(channels or [])
        self._panels = []
        for ch in self._channels:
            panel = BiasPanel(ch, gate=self._gate)
            # A channel enumerated while a sequence already owns the hardware
            # must come up locked, exactly as it comes up gated.
            if self._danger_locked:
                panel.set_manual_danger_locked(True)
            self._panels.append(panel)
            self._tabs.addTab(panel, f"CH{getattr(ch, 'channel', '?')}")
        self._refresh_summary()
        # The primary channel (proxy index 0 in the normal single-primary
        # config) owns the bias+waveform scan controls; surface only its signal.
        if self._panels:
            self._panels[0].vscan_requested.connect(self.vscan_requested)

    def _refresh_summary(self) -> None:
        total = len(self._channels)
        connected = sum(1 for c in self._channels if getattr(c, "connected", False))
        if total == 0:
            self._chip_channels.set_status("No channels", "neutral")
        elif connected == 0:
            self._chip_channels.set_status(f"0/{total} connected", "disconnected")
        elif connected == total:
            # Quiet nominal (law 1): all-connected is routine, not a green light.
            self._chip_channels.set_status(f"{connected}/{total} connected", "neutral")
        else:
            self._chip_channels.set_status(f"{connected}/{total} connected", "warn")
        for idx, ch in enumerate(self._channels):
            label = f"CH{getattr(ch, 'channel', '?')}"
            # "connected", not "LIVE" — a serial link up is NOT an energized
            # output (law 7); HV state lives on the per-channel hero tile.
            if getattr(ch, "connected", False):
                label += " · connected"
            self._tabs.setTabText(idx, label)

    # ------------------------------------------------------------------ #
    # Primary-channel forwarding (stable API across rebuilds)             #
    # ------------------------------------------------------------------ #

    @property
    def primary_panel(self) -> BiasPanel | None:
        return self._panels[0] if self._panels else None

    def set_manual_danger_locked(self, locked: bool) -> None:
        """Forward the manual-danger lock to every channel's BiasPanel while a
        Scan Sequencer run owns the hardware (``tct_gui._on_sequence_active``).

        Each child locks its own HV-ENERGIZING controls; the global
        ``ALL OUTPUTS OFF`` here and each child's per-channel Output OFF stay
        live — a stop is never gated (cockpit law 5).  The state is stored so a
        channel enumerated later by :meth:`rebuild` inherits the current lock,
        exactly as the injected gate survives a rebuild."""
        self._danger_locked = bool(locked)
        for panel in self._panels:
            panel.set_manual_danger_locked(self._danger_locked)

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
        self._refresh_summary()

    def refresh_theme(self, mode: str | None = None) -> None:
        """Forward a light/dark theme refresh to every tab's BiasPanel.

        Each newly-built tab (see rebuild()/_build_tabs()) already resolves
        the *current* theme itself at construction time (BiasPanel reads
        QSettings directly), so this only matters for tabs that already
        existed before the switch.  Called live by ``tct_gui._toggle_theme``
        after ``apply_theme``; see BiasPanel.refresh_theme() for the pattern.
        """
        for panel in self._panels:
            panel.refresh_theme(mode)

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
        # ONE TAP, no danger gate (law 5): this is the kill switch.  A stop can
        # only make the setup safer, so it must never wait on a confirmation
        # dialog — never route this through self._gate.
        if self._off_thread is not None and self._off_thread.isRunning():
            return
        live = [c for c in self._channels if getattr(c, "connected", False)]
        if not live:
            notify("No connected HV channels to switch off.", "warn")
            self._chip_all_off.set_status("Nothing live", "warn")
            return

        self._btn_all_off.setEnabled(False)
        self._chip_all_off.set_status("All-off running", "busy")
        self._tabs.setEnabled(False)
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
            self._tabs.setEnabled(True)
            if err:
                self._chip_all_off.set_status("All-off error", "crit")
                notify(f"ALL OUTPUTS OFF: {err}", "error")
            else:
                self._chip_all_off.set_status("All outputs off", "good")
                notify("All HV outputs ramped to 0 V and disabled.", "info")
            self._refresh_summary()

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
