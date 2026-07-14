"""
Reference Monitor panel (laser-intensity reference).

Displays real-time reference photodiode / SiPM amplitude + stability with the
live waveform as the hero (design system §7 "Reference Monitor: 2 tiles +
chip + waveform hero").  Works with any IntensityMonitorBase implementation —
swap the backend and this panel adapts automatically.

Round-03 glass kit migration (wave beat, mirrors the ``BiasPanel`` pilot,
commit 074943f): the whole panel is now ONE ``GlassPane`` shelf (chrome head
+ hero tiles + waveform + controls), with numeric input recessed into a
``Well``.  Unlike the HV dashboard's blanket ``register=False`` (a
hazard-panel-only stance — "opts NOTHING in"), this shelf's ``register=False``
is a *content* consequence, not a hazard one: it hosts the 2-tile
``MetricGrid`` (``MetricTile`` subclasses ``ReadoutCell`` — Baldr's Z4) and
the waveform ``FigureCard`` (Z3) directly, and the live-registry census in
``tests/test_panel_glass_rollout.py`` refuses glass on ANY pane that contains
a readout/plot descendant, hazard or not — registering the shelf would fail
that census the moment this panel joins its fixture. The one pure-chrome
piece — the "Instrument controls" card (scale ``Well`` + the two buttons, no
readout/plot/hazard inside) — registers instead, the same "register only the
specific chrome sub-card" pattern ``laser_panel``/``calibration_panel``/
``planner_panel`` already use (their outer containers are never registered
either; only named chrome-only sub-cards are).

No ``refresh_theme`` needed by design: the waveform lives on the fixed-dark
instrument canvas (``gui.style.PLOT_BG`` — identical in both themes), its pen
is resolved once against that fixed canvas, and every other surface here —
including the new ``GlassPane``/``Card``/``Well`` kit surfaces — is styled
purely through ``gui.style``'s app-wide QSS (objectName + dynamic-property
selectors), which ``apply_theme(app, mode)`` regenerates and re-applies
globally on every theme switch.  Nothing constructed here bakes a theme-
dependent color into an instance-level stylesheet or a cached Python
attribute (the one thing that would need re-resolving after a live switch —
see ``BiasPanel.refresh_theme`` for the contrast case, where the bias axis
rail and the ``HazardSurface`` DO cache like that), so there is nothing for a
refresh hook to do; ``tests/test_wave_intensity_render.py`` exercises a live
light→dark→light toggle to prove exactly that.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QDoubleSpinBox, QPushButton,
)

try:
    import pyqtgraph as pg
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

from devices.intensity_base import IntensityMonitorBase
from gui.panel_kit import (
    Card, FigureCard, GlassPane, MetricGrid, Well, panel_header,
    register_glass_pane,
)
from gui.status_widgets import StatusChip, flash_button, set_button_icon
from gui.style import axis_color

logger = logging.getLogger(__name__)


class _IntensityReader(QObject):
    """Polls the intensity monitor in a dedicated thread."""

    reading = Signal(object)
    failed = Signal(str)

    def __init__(self, monitor: IntensityMonitorBase) -> None:
        super().__init__()
        self._monitor = monitor
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.read_once)

    def set_monitor(self, monitor: IntensityMonitorBase) -> None:
        self._monitor = monitor

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def read_once(self) -> None:
        if not self._monitor.connected:
            self.reading.emit(None)
            return
        try:
            self.reading.emit(self._monitor.read())
        except Exception as exc:
            self.failed.emit(str(exc))


class IntensityPanel(QWidget):
    """
    Live readout panel for the reference laser intensity monitor.

    Accepts any IntensityMonitorBase subclass (ScopeChannelMonitor,
    SimulatedIntensityMonitor, or a future NI-DAQ / standalone TIA
    implementation) without any code changes.
    """

    _stop_requested = Signal()

    def __init__(
        self,
        monitor: IntensityMonitorBase,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._monitor = monitor
        self._build_ui()
        self._reader = _IntensityReader(monitor)
        self._reader_thread = QThread(self)
        self._reader.moveToThread(self._reader_thread)
        self._reader_thread.started.connect(self._reader.start)
        self._stop_requested.connect(self._reader.stop)
        self._reader_thread.finished.connect(self._reader.deleteLater)
        self._reader.reading.connect(self._on_reading)
        self._reader.failed.connect(self._on_failed)
        self._reader_thread.start()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── The one shelf (round-03 kit §2.1) ──────────────────────────
        # register=False: a CONTENT consequence, not a hazard one (see the
        # module docstring) — this shelf holds the hero MetricGrid + waveform
        # FigureCard directly, and the Z-ladder census
        # (tests/test_panel_glass_rollout.py) refuses glass on any pane that
        # contains a readout/plot descendant.  The pure-chrome "Instrument
        # controls" card below registers instead.
        shelf = GlassPane(register=False)
        self._shelf = shelf

        # ONE status chip (§7): live/offline/saturated, most-important-wins.
        self._chip_live = StatusChip("Monitor offline", "disconnected")
        shelf.add_widget(panel_header(
            "TCT Control · Instrument", "Reference Monitor",
            trailing=[self._chip_live],
        ))

        # ── Top strip: exactly two tiles (§7) ─────────────────────────
        # Amplitude carries charge in its caption (subordinated, still
        # reachable); Stability holds the last stability-check result.
        self._metrics = MetricGrid(columns=2)
        self._tile_amp = self._metrics.add_tile(("Amplitude", "--"))
        self._tile_stab = self._metrics.add_tile(("Stability", "--"))
        self._tile_amp.set_stale(True, "monitor offline")
        self._tile_stab.set_stale(True, "not yet measured")
        shelf.add_widget(self._metrics)

        # ── Waveform hero ─────────────────────────────────────────────
        if _HAS_PG:
            self._figure = FigureCard("Reference waveform")
            self._plot = self._figure.plot
            self._plot.setLabel("left",   "Amplitude", units="V")
            self._plot.setLabel("bottom", "Time",      units="s")
            # Laser-reference data ink, resolved once against the fixed-dark
            # instrument canvas (PLOT_BG is theme-invariant, so the dark-mode
            # rail colour is always the right contrast — no refresh needed).
            self._curve = self._plot.plot(
                pen=pg.mkPen(axis_color("laser", "dark"), width=1))
            # Stretch=1 on both the shelf's own body slot and the panel's
            # root slot (below) — the waveform is the hero and should grow
            # to fill the panel, same as before the migration.
            shelf.body.addWidget(self._figure, 1)
        else:
            shelf.add_widget(QLabel("(install pyqtgraph for live waveform)"))

        # ── Command card: scale + stability check ──────────────────────
        # Pure chrome (no readout/plot/hazard inside) — registers for glass,
        # the kit default for a non-hazard panel (see module docstring).
        ctrl_card = Card("Instrument controls")
        self._ctrl_card = ctrl_card
        cmd_row = QHBoxLayout()
        cmd_row.addWidget(QLabel("Scale (V/div):"))
        self._spin_scale = QDoubleSpinBox()
        self._spin_scale.setRange(0.001, 10.0)
        self._spin_scale.setValue(0.1)
        self._spin_scale.setDecimals(3)
        # The numeric input recesses into an opaque Well (§4.4: "a value
        # being typed is never on glass") — wraps WITHOUT touching the
        # widget's attribute identity, so every enable/disable and value
        # assertion on self._spin_scale is untouched.
        cmd_row.addWidget(self._well(self._spin_scale))
        self._btn_apply_scale = QPushButton("Apply scale")
        self._btn_apply_scale.setProperty("state", "secondary")
        set_button_icon(self._btn_apply_scale, "mdi.tune")
        self._btn_apply_scale.clicked.connect(self._apply_scale)
        cmd_row.addWidget(self._btn_apply_scale)
        cmd_row.addStretch(1)
        self._btn_stab = QPushButton("Check stability (10 shots)")
        self._btn_stab.setProperty("state", "secondary")
        set_button_icon(self._btn_stab, "mdi.chart-bell-curve")
        self._btn_stab.clicked.connect(self._check_stability)
        cmd_row.addWidget(self._btn_stab)
        ctrl_card.add_layout(cmd_row)
        shelf.add_widget(ctrl_card)
        register_glass_pane(ctrl_card)

        # The one shelf now holds the whole panel (head + tiles + waveform +
        # controls); it grows with the window so the waveform hero can too.
        root.addWidget(shelf, 1)

    @staticmethod
    def _well(widget: QWidget) -> Well:
        """Wrap an input widget in an opaque Well (round-03 kit §4.4 — "a
        value being typed is never on glass").  The widget keeps its identity
        (callers still reference ``self._spin_scale`` directly, so every
        enable/disable and value assertion is untouched); only its container
        changed.  Copied verbatim from ``bias_panel.py:911`` (the pilot)."""
        well = Well()
        well.add_widget(widget)
        return well

    # ------------------------------------------------------------------ #
    # Slots                                                               #
    # ------------------------------------------------------------------ #

    def _on_reading(self, reading) -> None:
        if reading is None:
            # Law 4: the tile keeps its last value but goes stale with a
            # caption saying why — never a silently frozen number.
            self._tile_amp.set_stale(True, "monitor offline")
            self._chip_live.set_status("Monitor offline", "disconnected")
            return
        try:
            self._tile_amp.set_value(f"{reading.amplitude_V*1000:.2f} mV")
            self._tile_amp.set_stale(False, f"charge {reading.charge_pC:.3f} pC")
            if reading.saturated:
                # The single chip carries the most important state (law 2:
                # saturation is a data-validity warning, amber not red).
                self._chip_live.set_status(
                    "Saturated", "warn",
                    "Reference signal is clipping — reduce intensity or scale")
                self._tile_amp.set_state("warn")
            else:
                self._chip_live.set_status("Monitor live", "busy")
                self._tile_amp.set_state("normal")

            if _HAS_PG and reading.time_s is not None and reading.waveform_V is not None:
                self._curve.setData(reading.time_s, reading.waveform_V)
        except Exception:
            pass

    def _on_failed(self, msg: str) -> None:
        logger.debug("Intensity monitor poll failed: %s", msg)

    def _apply_scale(self) -> None:
        try:
            self._monitor.set_scale(self._spin_scale.value())
            flash_button(self._btn_apply_scale, "good", "Applied")
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Scale error", str(exc))

    def _check_stability(self) -> None:
        try:
            stable, rms_rel = self._monitor.check_stability()
            self._tile_stab.set_value(f"{rms_rel*100:.2f} %")
            self._tile_stab.set_state("normal" if stable else "warn")
            self._tile_stab.set_stale(
                False, "stable over 10 shots" if stable else "unstable over 10 shots")
            flash_button(self._btn_stab, "good" if stable else "warn")
        except Exception as exc:
            self._tile_stab.set_value("--")
            self._tile_stab.set_state("crit")
            self._tile_stab.set_stale(False, f"check failed: {exc}")

    def set_monitor(self, monitor: IntensityMonitorBase) -> None:
        """Hot-swap the intensity monitor backend at runtime."""
        self._monitor = monitor
        self._reader.set_monitor(monitor)

    def shutdown(self) -> None:
        try:
            self._stop_requested.emit()
            self._reader_thread.quit()
            self._reader_thread.wait(2000)
        except Exception:
            pass
