"""Laser / trigger panel (PDL 800 manual settings + waveform generator control)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QLineEdit, QDoubleSpinBox,
    QPushButton, QComboBox,
)

from devices.laser_manual import LaserManualMetadata
from devices.waveform_generator import WaveformGenerator, list_visa_resources


class LaserPanel(QWidget):
    def __init__(
        self,
        laser: LaserManualMetadata,
        wfg: WaveformGenerator,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._laser = laser
        self._wfg = wfg
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── PDL 800 manual metadata ───────────────────────────────────
        pdl_box = QGroupBox("PDL 800 (manual settings — recorded in metadata)")
        form = QFormLayout(pdl_box)

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

        form.addRow("Wavelength:", self._ed_wavelength)
        form.addRow("Rep. mode:",  self._ed_rep_mode)
        form.addRow("Power knob:", self._ed_power)
        form.addRow("Attenuation:", self._ed_atten)
        form.addRow("Notes:",       self._ed_notes)

        btn_save = QPushButton("Save to metadata")
        btn_save.clicked.connect(self._save_metadata)
        form.addRow(btn_save)
        root.addWidget(pdl_box)

        # ── Waveform generator (trigger / rep rate) ───────────────────
        wfg_box = QGroupBox("Waveform Generator (trigger / rep rate)")
        wfg_form = QFormLayout(wfg_box)

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
        self._pulse_hint.setStyleSheet("color:#888; font-size:11px;")

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

        btn_row = QHBoxLayout()
        self._btn_on  = QPushButton("Output ON")
        self._btn_off = QPushButton("Output OFF")
        self._btn_on.clicked.connect(self._output_on)
        self._btn_off.clicked.connect(self._output_off)
        btn_row.addWidget(self._btn_on)
        btn_row.addWidget(self._btn_off)
        wfg_form.addRow(btn_row)

        btn_apply = QPushButton("Apply settings")
        btn_apply.clicked.connect(self._apply_wfg)
        wfg_form.addRow(btn_apply)

        diag_row = QHBoxLayout()
        btn_test = QPushButton("🔌 Test Connection")
        btn_test.setToolTip("Query *IDN? and show the reply — confirms the VISA/USB link")
        btn_test.clicked.connect(self._test_connection)
        btn_visa = QPushButton("List VISA…")
        btn_visa.setToolTip("List VISA resource strings (find the instrument's USB address)")
        btn_visa.clicked.connect(self._list_visa)
        diag_row.addWidget(btn_test)
        diag_row.addWidget(btn_visa)
        wfg_form.addRow(diag_row)
        root.addWidget(wfg_box)

    # ------------------------------------------------------------------ #
    # Slots                                                               #
    # ------------------------------------------------------------------ #

    def _save_metadata(self) -> None:
        self._laser.wavelength_nm       = self._ed_wavelength.value()
        self._laser.repetition_mode     = self._ed_rep_mode.currentText()
        self._laser.power_knob_setting  = self._ed_power.text()
        self._laser.attenuation_filter  = self._ed_atten.text()
        self._laser.notes               = self._ed_notes.text()

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
        else:
            duty = self._spin_width.value() * f * 100.0 if f > 0 else 0.0
            self._pulse_hint.setText(f"≈ {duty:.3g} % duty  @ {f:g} Hz")

    def _apply_wfg(self) -> None:
        try:
            self._wfg.set_frequency(self._spin_freq.value())
            if self._pulse_mode.currentText() == "Duty cycle":
                self._wfg.set_duty_cycle(self._spin_duty.value())
            else:
                self._wfg.set_pulse_width(self._spin_width.value())
            self._wfg.set_amplitude(self._spin_ampl.value())
            self._wfg.set_offset(self._spin_offset.value())
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "WFG Error", str(exc))

    def _on_load_changed(self, idx: int) -> None:
        try:
            self._wfg.set_output_load(self._load_combo.itemData(idx))
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "WFG Error", str(exc))

    def _output_on(self) -> None:
        try:
            self._wfg.output_on()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "WFG Error", str(exc))

    def _output_off(self) -> None:
        try:
            self._wfg.output_off()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "WFG Error", str(exc))

    def _test_connection(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox, QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            msg = self._wfg.test_connection()
        except Exception as exc:
            msg = f"Test failed: {exc}"
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Waveform Generator Test", msg)

    def _list_visa(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox, QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = list_visa_resources()
            text = ("\n".join(res) if res
                    else "No VISA resources found.\nIs the instrument on and NI-VISA installed?")
        except Exception as exc:
            text = f"{exc}"
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "VISA Resources", text)

    def get_metadata(self) -> LaserManualMetadata:
        """Return a snapshot of the current laser metadata."""
        self._save_metadata()
        return self._laser
