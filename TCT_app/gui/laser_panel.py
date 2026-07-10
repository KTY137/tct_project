"""Laser / trigger panel (PDL 800 manual settings + waveform generator control)."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QDoubleSpinBox,
    QPushButton, QComboBox, QApplication, QMessageBox,
)

from devices.laser_manual import LaserManualMetadata
from devices.waveform_generator import WaveformGenerator, list_visa_resources
from gui.panel_kit import Card, panel_header
from gui.status_widgets import StatusChip, flash_button, set_button_busy, set_button_icon
from gui.style import SPACE_MD, WARN_AMBER, palette

logger = logging.getLogger(__name__)


class _LaserWorker(QObject):
    """Runs blocking waveform-generator VISA calls off the GUI thread.

    On a dead LAN peer a single set/query blocks ≥5 s at the socket layer;
    doing that in a button slot or an ``editingFinished`` handler froze the
    whole window (the bench "the GUI locks up when I click Apply / edit a
    field" complaint).  Jobs are delivered here as *queued* invocations, so
    this worker's own event queue is the FIFO: writes reach the instrument in
    the exact order the user made them (frequency → amplitude → offset → …).
    Each job reports its result (or error text) back on the GUI thread.
    """
    job_done = Signal(int, object, str)   # job_id, result (or None), error

    @Slot(int, object)
    def run_job(self, job_id: int, fn) -> None:
        try:
            result = fn()
        except Exception as exc:
            self.job_done.emit(job_id, None, str(exc))
            return
        self.job_done.emit(job_id, result, "")


class LaserPanel(QWidget):
    # GUI → worker: (job_id, callable).  Cross-thread → Qt queues it, so the
    # worker's event queue preserves submission order (see _LaserWorker).
    _submit_job = Signal(int, object)
    def __init__(
        self,
        laser: LaserManualMetadata,
        wfg: WaveformGenerator,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._laser = laser
        self._wfg = wfg
        # Theme mode for the axis-rail accents (gui.style.axis_color): the
        # PDL 800 card reads "laser" (purple), the Waveform Generator card
        # reads "delay" (green) — it drives the laser's trigger/pulse timing,
        # the classic edge-TCT delay axis.  Read once from the same
        # QSettings key main.py/tct_gui.py use, mirroring MotorPanel/
        # BiasPanel; see refresh_theme() below.
        self._theme_mode = str(QSettings("TCT", "TCTSetup").value("theme", "light"))
        self._build_ui()
        # The output/armed chip must reflect the REAL driver output state, not
        # last-button bookkeeping — otherwise a scan arming the trigger, or a
        # failed apply while disconnected, leaves the chip lying.  Poll the
        # driver's cached state (a plain attribute read — no hardware I/O) so the
        # indicator tracks transitions the panel didn't initiate (e.g. the scan
        # thread's output_on()).  QTimer(self) stops itself when the panel is
        # destroyed on a soft-reload, so no explicit teardown is needed.
        self._output_poll = QTimer(self)
        self._output_poll.setInterval(750)
        self._output_poll.timeout.connect(self._refresh_output_chip)
        self._output_poll.start()
        self._refresh_output_chip()

        # ── Serialized VISA worker ────────────────────────────────────
        # Every wavegen set/query is a blocking VISA call (≥5 s on a dead LAN
        # peer); running them in the button/editingFinished slots froze the
        # window.  They now run on this worker thread, delivered as queued
        # invocations so they apply in submission order.  Parented to the
        # long-lived QApplication (NOT this panel): a soft config-reload
        # deletes the panel tree via setCentralWidget(), and a QThread
        # destroyed as a child while still running is a hard Qt6 abort — the
        # MotorPanel crash class.  shutdown() stops it with a bounded wait; it
        # self-deletes on ``finished``.
        self._job_seq = 0
        self._pending = 0
        self._job_callbacks: dict[int, object] = {}
        self._laser_thread: QThread | None = QThread(QApplication.instance())
        self._laser_worker = _LaserWorker()
        self._laser_worker.moveToThread(self._laser_thread)
        self._submit_job.connect(self._laser_worker.run_job)
        self._laser_worker.job_done.connect(self._on_job_done)
        self._laser_thread.finished.connect(self._laser_worker.deleteLater)
        self._laser_thread.finished.connect(self._laser_thread.deleteLater)
        self._laser_thread.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        root.setSpacing(SPACE_MD)

        root.addWidget(panel_header("TCT Control · Instrument", "Laser & Trigger"))

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self._chip_meta = StatusChip("Metadata saved", "good")
        self._chip_wfg = StatusChip("Wavegen --", "neutral")
        self._chip_output = StatusChip("Output off", "good")
        self._chip_pulse = StatusChip("Pulse --", "neutral")
        self._chip_load = StatusChip("Load --", "neutral")
        for chip in (self._chip_meta, self._chip_wfg, self._chip_output,
                     self._chip_pulse, self._chip_load):
            status_row.addWidget(chip)
        status_row.addStretch(1)
        root.addLayout(status_row)

        # ── PDL 800 manual metadata ───────────────────────────────────
        self._card_pdl = Card("PDL 800", "manual settings — recorded in metadata")
        form = QFormLayout()

        self._ed_wavelength = QDoubleSpinBox()
        self._ed_wavelength.setRange(200, 1100)
        self._ed_wavelength.setValue(self._laser.wavelength_nm)
        self._ed_wavelength.setSuffix(" nm")

        self._ed_rep_mode = QComboBox()
        self._ed_rep_mode.addItems(["external", "internal"])
        self._ed_rep_mode.setCurrentText(self._laser.repetition_mode)

        self._ed_power = QLineEdit(self._laser.power_knob_setting)
        self._ed_atten = QLineEdit(self._laser.attenuation_filter)
        self._ed_notes = QLineEdit(self._laser.notes)
        for widget in (self._ed_wavelength, self._ed_rep_mode, self._ed_power,
                       self._ed_atten, self._ed_notes):
            signal = getattr(widget, "valueChanged", None) or getattr(widget, "currentTextChanged", None) or getattr(widget, "textChanged", None)
            if signal is not None:
                signal.connect(lambda *_: self._chip_meta.set_status("Metadata dirty", "warn"))

        form.addRow("Wavelength:", self._ed_wavelength)
        form.addRow("Rep. mode:",  self._ed_rep_mode)
        form.addRow("Power knob:", self._ed_power)
        form.addRow("Attenuation:", self._ed_atten)
        form.addRow("Notes:",       self._ed_notes)

        btn_save = QPushButton("Save to metadata")
        set_button_icon(btn_save, "mdi.content-save")
        btn_save.clicked.connect(self._save_metadata)
        form.addRow(btn_save)
        self._card_pdl.add_layout(form)
        root.addWidget(self._card_pdl)

        # ── Waveform generator (trigger / rep rate) ───────────────────
        self._card_wfg = Card("Waveform Generator", "trigger / rep rate")
        wfg_form = QFormLayout()

        # Live signal controls — initialised from the device's configured values
        # (devices.yaml).  This is the single place these parameters live; the
        # Settings/Device-Manager only holds connection info (address/vendor).
        self._spin_freq = QDoubleSpinBox()
        self._spin_freq.setRange(1, 1e6)
        self._spin_freq.setValue(float(getattr(self._wfg, "_frequency", 1000.0)))
        self._spin_freq.setSuffix(" Hz")

        self._spin_width = QDoubleSpinBox()
        self._spin_width.setRange(1e-9, 1e-3)
        self._spin_width.setDecimals(9)
        self._spin_width.setValue(float(getattr(self._wfg, "_pulse_width", 100e-9)))
        self._spin_width.setSuffix(" s")

        # Pulse can be specified as absolute width OR as duty cycle (%).
        self._spin_duty = QDoubleSpinBox()
        self._spin_duty.setRange(0.001, 99.999)
        self._spin_duty.setDecimals(3)
        self._spin_duty.setSuffix(" %")
        _f0 = self._spin_freq.value()
        self._spin_duty.setValue(max(0.001, min(99.999,
                                 self._spin_width.value() * _f0 * 100.0)))
        self._pulse_mode = QComboBox()
        self._pulse_mode.addItems(["Pulse width", "Duty cycle"])
        self._pulse_hint = QLabel("")
        # Muted-caption colour is theme-token resolved by
        # _restyle_theme_tokens() below (re-run on every refresh_theme()).

        self._spin_ampl = QDoubleSpinBox()
        self._spin_ampl.setRange(1e-3, 50.0)
        self._spin_ampl.setDecimals(4)
        self._spin_ampl.setValue(float(getattr(self._wfg, "_amplitude", 3.3)))
        self._spin_ampl.setSuffix(" Vpp")

        self._spin_offset = QDoubleSpinBox()
        self._spin_offset.setRange(-5.0, 5.0)
        self._spin_offset.setDecimals(4)
        self._spin_offset.setValue(float(getattr(self._wfg, "_offset", 0.0)))
        self._spin_offset.setSuffix(" V")

        # Output load the generator assumes it drives — a mismatch here is a
        # silent up-to-2x amplitude error (the bench "wavegen amplitude wrong"
        # bug this control fixes the GUI side of).
        self._load_combo = QComboBox()
        self._load_combo.addItem("High-Z", "INFinity")
        self._load_combo.addItem("50 Ω", 50)
        _cur_load = getattr(self._wfg, "_output_load", "INFinity")
        _idx = 1 if str(_cur_load).strip().upper() not in ("INFINITY", "INF", "") else 0
        self._load_combo.setCurrentIndex(_idx)
        self._load_combo.setToolTip(
            "Load impedance the generator assumes it drives. Must match the real "
            "load (High-Z for a scope input, 50 Ω for a terminated load) or the "
            "amplitude is off by up to 2x.")
        self._load_combo.currentIndexChanged.connect(self._on_load_changed)

        wfg_form.addRow("Frequency:", self._spin_freq)
        wfg_form.addRow("Pulse spec:", self._pulse_mode)
        wfg_form.addRow("Pulse width:", self._spin_width)
        wfg_form.addRow("Duty cycle:", self._spin_duty)
        wfg_form.addRow("", self._pulse_hint)
        wfg_form.addRow("Amplitude:", self._spin_ampl)
        wfg_form.addRow("Offset:", self._spin_offset)
        wfg_form.addRow("Output load:", self._load_combo)

        self._pulse_mode.currentTextChanged.connect(self._on_pulse_mode)
        for _w in (self._spin_freq, self._spin_width, self._spin_duty):
            _w.valueChanged.connect(self._update_pulse_hint)
        self._on_pulse_mode(self._pulse_mode.currentText())

        # Live-apply each setting the moment the user finishes editing it, so a
        # changed value reaches the instrument WITHOUT a separate "Apply" click.
        # This matches the output-load combo (already live) and the Output ON/OFF
        # buttons — the previous apply-only-on-button behaviour is exactly the
        # "I change it in the GUI but it doesn't send" bench complaint.
        # ``editingFinished`` fires on Enter / focus-out, never per keystroke, so
        # it does not spam the device.  ``.value()`` is read at call time.
        self._spin_freq.editingFinished.connect(
            lambda: self._live_apply(self._wfg.set_frequency, self._spin_freq.value()))
        self._spin_ampl.editingFinished.connect(
            lambda: self._live_apply(self._wfg.set_amplitude, self._spin_ampl.value()))
        self._spin_offset.editingFinished.connect(
            lambda: self._live_apply(self._wfg.set_offset, self._spin_offset.value()))
        self._spin_width.editingFinished.connect(
            lambda: self._live_apply(self._wfg.set_pulse_width, self._spin_width.value()))
        self._spin_duty.editingFinished.connect(
            lambda: self._live_apply(self._wfg.set_duty_cycle, self._spin_duty.value()))
        _load_label = self._load_combo.currentText()
        self._chip_load.set_status(f"Load {_load_label}",
                                   "good" if _load_label == "50 Ω" else "warn")

        btn_row = QHBoxLayout()
        self._btn_on  = QPushButton("Output ON")
        self._btn_on.setObjectName("armedBtn")
        set_button_icon(self._btn_on, "mdi.power-plug", color=WARN_AMBER)
        self._btn_off = QPushButton("Output OFF")
        set_button_icon(self._btn_off, "mdi.power-plug-off")
        self._btn_on.clicked.connect(self._output_on)
        self._btn_off.clicked.connect(self._output_off)
        btn_row.addWidget(self._btn_on)
        btn_row.addWidget(self._btn_off)
        wfg_form.addRow(btn_row)

        btn_apply = QPushButton("Apply settings")
        self._btn_apply = btn_apply
        set_button_icon(btn_apply, "mdi.tune")
        btn_apply.clicked.connect(self._apply_wfg)
        wfg_form.addRow(btn_apply)

        diag_row = QHBoxLayout()
        btn_test = QPushButton("🔌 Test Connection")
        self._btn_test = btn_test
        set_button_icon(btn_test, "mdi.lan-connect")
        btn_test.setToolTip("Query *IDN? and show the reply — confirms the VISA/USB link")
        btn_test.clicked.connect(self._test_connection)
        btn_visa = QPushButton("List VISA…")
        self._btn_visa = btn_visa
        set_button_icon(btn_visa, "mdi.format-list-bulleted")
        btn_visa.setToolTip("List VISA resource strings (find the instrument's USB address)")
        btn_visa.clicked.connect(self._list_visa)
        diag_row.addWidget(btn_test)
        diag_row.addWidget(btn_visa)
        wfg_form.addRow(diag_row)
        self._card_wfg.add_layout(wfg_form)
        root.addWidget(self._card_wfg)
        root.addStretch(1)
        self._restyle_theme_tokens()

    # ------------------------------------------------------------------ #
    # Slots                                                               #
    # ------------------------------------------------------------------ #

    def _save_metadata(self) -> None:
        self._laser.wavelength_nm       = self._ed_wavelength.value()
        self._laser.repetition_mode     = self._ed_rep_mode.currentText()
        self._laser.power_knob_setting  = self._ed_power.text()
        self._laser.attenuation_filter  = self._ed_atten.text()
        self._laser.notes               = self._ed_notes.text()
        self._chip_meta.set_status("Metadata saved", "good")

    def _on_pulse_mode(self, mode: str) -> None:
        duty = (mode == "Duty cycle")
        self._spin_width.setEnabled(not duty)
        self._spin_duty.setEnabled(duty)
        self._update_pulse_hint()

    @staticmethod
    def _fmt_time(s: float) -> str:
        for scale, unit in ((1e-9, "ns"), (1e-6, "µs"), (1e-3, "ms"), (1.0, "s")):
            if abs(s) < scale * 1000:
                return f"{s/scale:.3g} {unit}"
        return f"{s:.3g} s"

    def _update_pulse_hint(self, *_) -> None:
        f = self._spin_freq.value()
        if self._pulse_mode.currentText() == "Duty cycle":
            width = (self._spin_duty.value() / 100.0) / f if f > 0 else 0.0
            self._pulse_hint.setText(f"≈ {self._fmt_time(width)} pulse  @ {f:g} Hz")
            self._chip_pulse.set_status(f"Duty {self._spin_duty.value():.3g}%", "info")
        else:
            duty = self._spin_width.value() * f * 100.0 if f > 0 else 0.0
            self._pulse_hint.setText(f"≈ {duty:.3g} % duty  @ {f:g} Hz")
            self._chip_pulse.set_status(f"Width {self._fmt_time(self._spin_width.value())}", "info")

    # ------------------------------------------------------------------ #
    # Off-thread VISA job plumbing                                        #
    # ------------------------------------------------------------------ #

    def _submit(self, fn, on_done) -> None:
        """Queue *fn* to run on the VISA worker thread; *on_done(result, err)*
        runs back on the GUI thread when it finishes.  Jobs run in submission
        order (the worker's queued event loop is the FIFO), so a burst of live
        edits reaches the instrument in the exact order the user made them."""
        self._job_seq += 1
        jid = self._job_seq
        self._job_callbacks[jid] = on_done
        self._pending += 1
        if self._pending == 1:
            self._chip_wfg.set_status("Wavegen busy…", "busy",
                                      "Sending to the waveform generator…")
        self._submit_job.emit(jid, fn)

    @Slot(int, object, str)
    def _on_job_done(self, jid: int, result, err: str) -> None:
        self._pending = max(0, self._pending - 1)
        cb = self._job_callbacks.pop(jid, None)
        if cb is not None:
            try:
                cb(result, err)
            except Exception:
                logger.debug("laser job callback failed", exc_info=True)
        # Jobs whose callbacks settle a DIFFERENT chip (output toggle, load,
        # list-VISA) would otherwise leave "Wavegen busy…" latched forever.
        # Settle the shared chip once the queue drains — but never overwrite
        # a more specific state (error/configured) a callback just painted.
        if self._pending == 0 and self._chip_wfg.text() == "Wavegen busy…":
            live = bool(getattr(self._wfg, "connected", False)
                        or getattr(self._wfg, "simulation", False))
            if live:
                self._chip_wfg.set_status("Wavegen connected", "good")
            else:
                self._chip_wfg.set_status(
                    "Staged — wavegen not connected", "warn",
                    "Values cached; sent when you Connect the wavegen.")

    def _live_apply(self, setter, value) -> None:
        """Send ONE wavegen setting (a control's editingFinished) off-thread.

        No-op with a 'staged' hint when the wavegen is not connected — the
        driver's setters silently drop writes with no VISA session, so we
        surface that rather than imply success (the earlier bench failure).
        Never enables the output.  The VISA write runs on the worker thread so
        a slow/dead instrument can never freeze the field the user just edited.
        """
        live = bool(getattr(self._wfg, "connected", False)
                    or getattr(self._wfg, "simulation", False))
        if not live:
            self._chip_wfg.set_status(
                "Staged — wavegen not connected", "warn",
                "Value cached; sent when you Connect the wavegen.")
            return
        self._submit(lambda: setter(value), self._on_live_applied)

    def _on_live_applied(self, result, err: str) -> None:
        if err:
            self._chip_wfg.set_status("Wavegen error", "crit", err)
            return
        # Reflect what the instrument ACTUALLY applied — the DG4162 clamps pulse
        # width / duty to its frequency-dependent minimum, so the request the
        # user typed may not be what the device did.
        self._reflect_applied()
        self._chip_wfg.set_status("Wavegen configured", "good")

    def _reflect_applied(self) -> None:
        """Sync the width/duty spinboxes to the driver's ACTUALLY-applied values.

        The instrument silently clamps pulse width / duty to its frequency-
        dependent minimum (e.g. 200 ns → 3.125 µs at 1 kHz).  The driver reads
        the applied value back into ``_pulse_width`` / ``_duty_cycle``; reflect
        that here so the GUI shows what the instrument really did, not the
        rejected request.  ``blockSignals`` around ``setValue`` so this cannot
        re-fire ``editingFinished`` and re-send the value in a loop.
        """
        applied_w = getattr(self._wfg, "_pulse_width", None)
        if applied_w is not None:
            self._spin_width.blockSignals(True)
            try:
                self._spin_width.setValue(float(applied_w))
            finally:
                self._spin_width.blockSignals(False)
        applied_d = getattr(self._wfg, "_duty_cycle", None)
        if applied_d is not None:
            self._spin_duty.blockSignals(True)
            try:
                self._spin_duty.setValue(float(applied_d))
            finally:
                self._spin_duty.blockSignals(False)
        self._update_pulse_hint()

    def _apply_wfg(self) -> None:
        # A disconnected real driver silently drops every write (the setters
        # no-op when there is no VISA session), so "configured" would be a lie —
        # the exact "settings couldn't pass to the wavegen" bench failure.
        # Detect it up front and report "staged" instead of a false success.
        live = bool(getattr(self._wfg, "connected", False)
                    or getattr(self._wfg, "simulation", False))
        set_button_busy(self._btn_apply, True, "Applying...")
        # Read every widget value HERE, on the GUI thread — the worker closure
        # below must never touch a Qt widget from the worker thread.
        load    = self._load_combo.currentData()
        freq    = self._spin_freq.value()
        is_duty = (self._pulse_mode.currentText() == "Duty cycle")
        duty    = self._spin_duty.value()
        width   = self._spin_width.value()
        ampl    = self._spin_ampl.value()
        offset  = self._spin_offset.value()

        def work():
            # Load first: it changes how the generator interprets the amplitude
            # that follows (High-Z vs 50 Ω is a silent up-to-2x error), so the
            # whole batch stays self-consistent — mirrors the driver's
            # _apply_defaults() ordering.
            self._wfg.set_output_load(load)
            self._wfg.set_frequency(freq)
            if is_duty:
                self._wfg.set_duty_cycle(duty)
            else:
                self._wfg.set_pulse_width(width)
            self._wfg.set_amplitude(ampl)
            self._wfg.set_offset(offset)

        self._submit(work, lambda result, err: self._on_apply_wfg_done(live, err))

    def _on_apply_wfg_done(self, live: bool, err: str) -> None:
        set_button_busy(self._btn_apply, False)
        if err:
            self._chip_wfg.set_status("Wavegen error", "crit", err)
            QMessageBox.warning(self, "WFG Error", err)
            return
        # Reflect the instrument's actually-applied width/duty back into the
        # spinboxes (it clamps to a frequency-dependent minimum).
        self._reflect_applied()
        if live:
            self._chip_wfg.set_status("Wavegen configured", "good")
            flash_button(self._btn_apply, "good", "Applied")
        else:
            self._chip_wfg.set_status(
                "Staged — wavegen not connected", "warn",
                "Values cached; they are sent when you Connect the wavegen.")
            flash_button(self._btn_apply, "warn", "Staged")

    def _on_load_changed(self, idx: int) -> None:
        load = self._load_combo.itemData(idx)
        label = self._load_combo.currentText()
        self._submit(lambda: self._wfg.set_output_load(load),
                     lambda result, err: self._on_load_done(label, err))

    def _on_load_done(self, label: str, err: str) -> None:
        if err:
            self._chip_load.set_status("Load error", "crit", err)
            QMessageBox.warning(self, "WFG Error", err)
            return
        self._chip_load.set_status(f"Load {label}", "good" if label == "50 Ω" else "warn")

    def _output_on(self) -> None:
        # Off-thread like every wavegen write.  The OFF path (below) stays just
        # as responsive, so the trigger can always be disarmed even while a slow
        # write is still draining on a dead peer.
        self._submit(self._wfg.output_on,
                     lambda result, err: self._on_output_toggled(
                         self._btn_on, "warn", "Armed", err))

    def _output_off(self) -> None:
        self._submit(self._wfg.output_off,
                     lambda result, err: self._on_output_toggled(
                         self._btn_off, "good", "Off", err))

    def _on_output_toggled(self, button: QPushButton, flash_state: str,
                           flash_text: str, err: str) -> None:
        if err:
            self._chip_output.set_status("Output error", "crit", err)
            QMessageBox.warning(self, "WFG Error", err)
            return
        # Reflect the driver's real post-command state rather than assuming
        # success (the driver flips its record only after the write path).
        self._refresh_output_chip()
        flash_button(button, flash_state, flash_text)

    def _refresh_output_chip(self) -> None:
        """Repaint the armed/output chip from the driver's REAL output record.

        Safety-relevant: the wavegen output is the PDL 800 laser trigger, so the
        indicator must never show "off" while the output is actually armed
        (e.g. a scan enabled it).  Reads only cached driver state — no hardware
        I/O — so it is safe to call from a timer.  Tri-state:
          * connected + on   -> "Output ARMED" (armed)
          * connected + off  -> "Output off" (good)
          * connected + None -> "Output state unknown" (warn): hardware may
            retain a prior ON state we neither commanded nor read back.
          * not connected    -> "Output --" (neutral): no session to trust.
        """
        try:
            live = bool(getattr(self._wfg, "connected", False)
                        or getattr(self._wfg, "simulation", False))
            state = getattr(self._wfg, "output_is_on", None)
        except Exception:
            return
        if not live:
            self._chip_output.set_status("Output --", "neutral")
        elif state is True:
            self._chip_output.set_status("Output ARMED", "armed")
        elif state is False:
            self._chip_output.set_status("Output off", "good")
        else:
            self._chip_output.set_status("Output state unknown", "warn",
                                         "Wavegen output state not read back on "
                                         "connect — toggle Output ON/OFF to define it.")

    def _test_connection(self) -> None:
        # Runs off-thread: *IDN? blocks ≥5 s on a dead LAN peer, which used to
        # freeze the window behind a wait-cursor.  The button's busy state is
        # the responsive replacement for the old override cursor.
        set_button_busy(self._btn_test, True, "Testing...")
        self._submit(self._wfg.test_connection, self._on_test_done)

    def _on_test_done(self, result, err: str) -> None:
        set_button_busy(self._btn_test, False)
        if err:
            msg = f"Test failed: {err}"
            self._chip_wfg.set_status("Wavegen error", "crit", err)
        else:
            msg = result
            self._chip_wfg.set_status("Wavegen connected", "good")
            flash_button(self._btn_test, "good", "Connected")
        QMessageBox.information(self, "Waveform Generator Test", msg)

    def _list_visa(self) -> None:
        set_button_busy(self._btn_visa, True, "Scanning...")
        self._submit(list_visa_resources, self._on_list_visa_done)

    def _on_list_visa_done(self, result, err: str) -> None:
        set_button_busy(self._btn_visa, False)
        if err:
            text = f"{err}"
        else:
            text = ("\n".join(result) if result
                    else "No VISA resources found.\nIs the instrument on and NI-VISA installed?")
        QMessageBox.information(self, "VISA Resources", text)

    def get_metadata(self) -> LaserManualMetadata:
        """Return a snapshot of the current laser metadata."""
        self._save_metadata()
        return self._laser

    # ------------------------------------------------------------------ #
    # Teardown                                                            #
    # ------------------------------------------------------------------ #

    def shutdown(self) -> None:
        """Stop the output-poll timer and the VISA worker before the panel is
        discarded (``tct_gui._teardown_panels`` on a soft config-reload / exit).

        Bounded wait — a wavegen write/query can sit ≥5 s on a dead LAN peer,
        so never wait unbounded on the GUI thread.  The worker thread is
        parented to QApplication and self-``deleteLater``s on ``finished``, so
        a call still in flight when the 3 s bound elapses finishes and cleans
        itself up rather than being destroyed as a child of this (soon-deleted)
        widget — the MotorPanel soft-reload crash class.  Idempotent.

        SAFETY ORDERING (rule 5): ``thread.quit()`` discards queued jobs that
        have not started — including a queued Output OFF.  That is safe ONLY
        because every teardown path calls ``DeviceManager.disconnect_all()``
        AFTER ``_teardown_panels()``, and ``WaveformGenerator.disconnect()``
        forces ``output_off()`` for an armed output.  Do not reorder teardown
        before checking ``test_queued_output_off_rescued_by_teardown_order``.
        """
        if getattr(self, "_output_poll", None) is not None:
            self._output_poll.stop()
        thread = self._laser_thread
        self._laser_thread = None
        if thread is not None:
            thread.quit()
            thread.wait(3000)

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # Axis-rail styling (gui.style.axis_color) — re-run by refresh_theme() #
    # ------------------------------------------------------------------ #

    def _restyle_theme_tokens(self) -> None:
        """Tint the two cards with their axis-rail identity: the PDL 800
        (the physical laser) reads "laser" (purple); the Waveform Generator
        (pulse width / frequency / trigger — the classic edge-TCT delay
        axis) reads "delay" (green). Same idiom as MotorPanel/BiasPanel's
        axis-rail accents, applied to a whole Card via ``Card.set_rail``.

        Also re-resolves the pulse-hint caption's muted colour — a per-
        instance inline style baked in at construction time (same as the
        rail colours above), so it needs this explicit refresh rather than
        relying on the app-wide stylesheet."""
        self._card_pdl.set_rail("laser", self._theme_mode)
        self._card_wfg.set_rail("delay", self._theme_mode)
        self._pulse_hint.setStyleSheet(
            f"color: {palette(self._theme_mode)['muted']}; font-size: 11px;")

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve the axis-rail accents after a light/dark switch (same
        pattern as ``MotorPanel.refresh_theme`` / ``BiasPanel.refresh_theme``).

        ``gui.style.apply_theme(app, mode)`` re-applies the QApplication-wide
        stylesheet, which already repaints every objectName-based QSS hook
        (``cardPane``, ``statusChip``, ``armedBtn``, ...) automatically; the
        rail colours above are baked in as instance-level inline styles at
        construction time, so they need this explicit refresh.

        Called live by ``tct_gui._toggle_theme`` (wired alongside the
        motor/bias/planner panels), so a theme switch re-resolves these
        instance-level colours immediately.
        """
        if mode:
            self._theme_mode = str(mode)
        self._restyle_theme_tokens()
