"""
Charge-calibration panel.

Exposes both calibration methods from the GUI:

* **Electronics gain** — enter the amplifier gain / transimpedance and
  termination; the raw integrated charge is converted to absolute pC.
* **Reference diode** — run a short acquisition on a calibrated reference PIN
  diode, enter its thickness, and the panel computes the ``k_factor`` that puts
  the DUT charge into MIP-equivalent (or pC / electron) units.

Results are persisted to ``configs/charge_calibration.yaml`` (a sidecar so the
documented ``devices.yaml`` is left untouched) and applied live to the running
DeviceManager.

HAZARD note (2026-07-15 lab-safety fix): ``_run_reference``'s
``_ReferenceWorker`` arms the wavegen output — the SAME PDL 800 laser trigger
path ``gui/laser_panel.py``'s "Output on" button arms — so it is a rule-2
dangerous action and confirms through the injected ``DangerGate`` (see
``_confirm_reference_arm``) exactly like the repeatability test's motion does;
no gate ⇒ refuse, same fail-safe stance.
"""
from __future__ import annotations

import logging
import time

import numpy as np
import yaml
from PySide6.QtCore import Qt, QObject, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from analysis.charge_calibration import ChargeCalibration, q_one_mip_pC
from analysis.waveform_analysis import analyse_waveform
from controller.danger_gate import DangerAction, DangerGate
from controller.repeatability import RepeatabilityTester
from gui.app_settings import theme_mode
from gui.panel_kit import GlassPane, HazardSurface, panel_header, register_glass_pane
from gui.status_widgets import ReadoutCell, StatusChip, flash_button, set_button_busy, set_button_icon
from gui.style import FONT_SM, MONO_FAMILIES, palette


class _RepeatWorker(QObject):
    """Runs the (long, blocking) repeatability test off the GUI thread."""
    progress = Signal(int, int)
    finished = Signal(object)        # RepeatabilityResult on success, else Exception

    def __init__(self, tester: RepeatabilityTester, params: dict) -> None:
        super().__init__()
        self._tester = tester
        self._p = params
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            px_per_mm = None
            if self._p.get("calibrate"):
                px_per_mm = self._tester.calibrate(
                    axis=self._p["cal_axis"], dist_mm=self._p["cal_dist"],
                    settle_s=self._p["settle"])
            res = self._tester.run(
                n=self._p["n"], approach_mm=self._p["approach"],
                settle_s=self._p["settle"], px_per_mm=px_per_mm,
                progress=lambda i, n: self.progress.emit(i, n),
                should_stop=lambda: self._stop)
            self.finished.emit(res)
        except Exception as exc:        # surfaced in the GUI thread
            self.finished.emit(exc)


class _ReferenceWorker(QObject):
    """Runs reference-diode acquisition off the GUI thread."""

    finished = Signal(object)        # mean q_ref on success, else Exception

    def __init__(self, devices, n: int) -> None:
        super().__init__()
        self._devices = devices
        self._n = n

    def run(self) -> None:
        scope = self._devices.scope
        charges = []
        try:
            self._devices.waveform_generator.output_on()
            time.sleep(0.02)
            for _ in range(self._n):
                t, v = scope.read_channel(2)
                charges.append(
                    analyse_waveform(t, v, **self._devices.analysis_kwargs).charge_pC)
            self.finished.emit(float(np.mean(charges)))
        except Exception as exc:
            self.finished.emit(exc)
        finally:
            try:
                self._devices.waveform_generator.output_off()
            except Exception:
                pass

logger = logging.getLogger(__name__)


class CalibrationPanel(QWidget):
    """GUI for configuring and running charge calibration."""

    calibration_changed = Signal()   # emitted after a successful save

    def __init__(self, devices, parent: QWidget | None = None,
                 *, gate: DangerGate | None = None) -> None:
        super().__init__(parent)
        self._devices = devices
        # Confirmation gate for every dangerous action this panel can start:
        # the (motion-driving) repeatability test, AND the reference-diode
        # acquisition (2026-07-15 fix — Mary's every-submitter grep found
        # _ReferenceWorker.run() arms the wavegen output, the PDL 800 laser
        # trigger; that is emission, same class as laser_panel._output_on).
        # The main window injects the same QtDangerGate the plan executor
        # uses; with no gate BOTH actions refuse (fail-safe), so the panel
        # surfaces that up front rather than firing a worker that will raise.
        self._gate = gate
        self._loading = True
        self._ref_thread: QThread | None = None
        self._ref_worker: _ReferenceWorker | None = None
        self._rep_thread: QThread | None = None
        self._rep_worker: _RepeatWorker | None = None
        self._theme_mode = theme_mode()
        self._build_ui()
        self._load_from(devices.charge_calibration)
        self._loading = False
        self._set_dirty(False)

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── The one shelf (round-03 kit §2.1) ──────────────────────────
        # HAZARD PANEL — the shelf itself is a content shell and opts NOTHING
        # into the panel-glass switch (register=False). This panel drives the
        # motor stage (the repeatability test moves hardware), so its danger
        # zone lives on an opaque HazardSurface below; the shelf carries only
        # chrome. The two eligible parameter groups (Method + Electronics gain)
        # keep their individual opt-ins from the Z-ladder rollout, unchanged.
        shelf = GlassPane(register=False)
        self._shelf = shelf

        shelf.add_widget(panel_header("TCT Control · Calibration", "Calibration"))

        intro = QLabel("Set charge-conversion parameters, then apply and save them for analysis.")
        intro.setWordWrap(True)
        shelf.add_widget(intro)

        chip_row = QHBoxLayout()
        self._chip_method = StatusChip("Method --", "neutral")
        self._chip_dirty = StatusChip("Saved", "good")
        self._chip_ref = StatusChip("Reference --", "neutral")
        self._chip_repeat = StatusChip("Repeatability idle", "neutral")
        for chip in (self._chip_method, self._chip_dirty, self._chip_ref, self._chip_repeat):
            chip_row.addWidget(chip)
        chip_row.addStretch(1)
        shelf.add_layout(chip_row)

        # Method selector
        method_box = QGroupBox("Method")
        mform = QFormLayout(method_box)
        self._method = QComboBox()
        self._method.addItems(["none", "electronics", "reference_diode"])
        self._method.currentTextChanged.connect(self._on_method_changed)
        mform.addRow("Calibration method:", self._method)
        self._units = QComboBox()
        self._units.addItems(["pC", "MIP", "e"])
        mform.addRow("Output units:", self._units)
        shelf.add_widget(method_box)
        # Panel glass (opt-in, Baldr Z-ladder): the Method + Electronics-gain
        # groups are pure parameter chrome (selectors / gain fields), no live
        # readout, no motion/danger control — eligible. The Reference-diode
        # group is DENIED below (it carries Q_ref/k_factor readout cells,
        # Baldr Z4) and so is the Stage-Repeatability group (it hosts the
        # #dangerBtn Stop button — Völundr G2 / Baldr §5.2).
        register_glass_pane(method_box)

        # Electronics group
        self._elec_box = QGroupBox("Electronics gain")
        eform = QFormLayout(self._elec_box)
        self._termination = _dspin(50.0, 0.1, 1e6, 2)
        self._amp_gain = _dspin(1.0, 1e-6, 1e9, 4)
        self._transimpedance = QLineEdit()
        self._transimpedance.setPlaceholderText("blank = use voltage gain above")
        eform.addRow("Termination (Ω):", self._termination)
        eform.addRow("Amplifier gain (V/V):", self._amp_gain)
        eform.addRow("Transimpedance (V/A):", self._transimpedance)
        shelf.add_widget(self._elec_box)
        register_glass_pane(self._elec_box)

        # Reference-diode group
        self._ref_box = QGroupBox("Reference diode (MIP calibration)")
        rform = QFormLayout(self._ref_box)
        self._thickness = _dspin(300.0, 1.0, 5000.0, 1)
        self._ref_averages = QSpinBox(); self._ref_averages.setRange(1, 1000); self._ref_averages.setValue(10)
        run_row = QHBoxLayout()
        self._btn_run = QPushButton("Run reference-diode calibration")
        set_button_icon(self._btn_run, "mdi.play")
        self._btn_run.setToolTip("Acquire on scope CH2 (reference), integrate charge, compute k_factor")
        self._btn_run.clicked.connect(self._run_reference)
        run_row.addWidget(self._btn_run)
        run_row.addStretch()
        run_w = QWidget(); run_w.setLayout(run_row)
        rform.addRow("Diode thickness (µm):", self._thickness)
        rform.addRow("Averages:", self._ref_averages)
        rform.addRow(run_w)
        self._lbl_qref = ReadoutCell("Q_ref_raw", "--")
        self._lbl_k = ReadoutCell("k_factor", "--")
        self._lbl_when = ReadoutCell("Calibrated", "never")
        for lbl in (self._lbl_qref, self._lbl_k, self._lbl_when):
            rform.addRow(lbl)
        shelf.add_widget(self._ref_box)

        # Buttons + status
        btn_row = QHBoxLayout()
        self._btn_save = QPushButton("Apply && Save")
        set_button_icon(self._btn_save, "mdi.content-save")
        self._btn_save.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_save)
        shelf.add_layout(btn_row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        shelf.add_widget(self._status)

        self._current = QLabel("")
        shelf.add_widget(self._current)

        self._build_repeatability(shelf)
        self._restyle_theme_tokens()

        root.addWidget(shelf)
        root.addStretch()
        self._wire_dirty_tracking()

    def _wire_dirty_tracking(self) -> None:
        widgets = (
            self._method, self._units, self._termination, self._amp_gain,
            self._transimpedance, self._thickness, self._ref_averages,
            self._rep_n, self._rep_approach, self._rep_settle,
            self._rep_cal, self._rep_cal_axis, self._rep_cal_dist,
        )
        # ``self._mark_dirty`` is a BOUND METHOD, never a lambda: PySide6 holds
        # bound-method slots weakly, so these connections do not keep the panel
        # alive. A ``lambda *_: self._set_dirty(True)`` (what these were) is
        # stored STRONGLY by the child widget's C++ connection list and closes
        # the cycle child -> connection -> closure -> panel -> child, one hop of
        # which gc cannot see. See tests/test_no_immortal_panels.py.
        for widget in widgets:
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self._mark_dirty)
            elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                widget.valueChanged.connect(self._mark_dirty)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._mark_dirty)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._mark_dirty)

    def _mark_dirty(self, *_) -> None:
        """Any edit to a tracked field marks the calibration unsaved.

        Takes ``*_`` because the four signals wired above deliver different
        payloads (str / float / str / bool) and none of them is used.
        """
        self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        if getattr(self, "_loading", False):
            return
        self._chip_dirty.set_status("Unsaved" if dirty else "Saved",
                                    "warn" if dirty else "good")

    # ------------------------------------------------------------------ #
    # Stage repeatability (camera)                                        #
    # ------------------------------------------------------------------ #

    def _build_repeatability(self, shelf: GlassPane) -> None:
        box = QGroupBox("Stage Repeatability (camera)")
        form = QFormLayout(box)
        intro = QLabel(
            "Measures the <b>real</b> mechanical repeatability the stepper stage "
            "cannot self-report: returns to a target N times from different "
            "directions and measures the camera-image scatter by sub-pixel phase "
            "correlation. Point the camera at a textured target (the printed µm "
            "strips). Requires motor homed + camera connected."
        )
        intro.setWordWrap(True)
        form.addRow(intro)

        self._rep_n = QSpinBox(); self._rep_n.setRange(2, 1000); self._rep_n.setValue(20)
        self._rep_approach = _dspin(5.0, 0.1, 100.0, 1)
        self._rep_settle = _dspin(0.4, 0.0, 10.0, 2)
        form.addRow("Repetitions:", self._rep_n)
        form.addRow("Approach move (mm):", self._rep_approach)
        form.addRow("Settle per grab (s):", self._rep_settle)

        self._rep_cal = QCheckBox("Self-calibrate px→mm first (one known move)")
        self._rep_cal.setChecked(True)
        self._rep_cal_axis = QComboBox(); self._rep_cal_axis.addItems(["X", "Y"])
        self._rep_cal_dist = _dspin(1.0, 0.05, 50.0, 2)
        cal_row = QHBoxLayout()
        cal_row.addWidget(self._rep_cal_axis)
        cal_row.addWidget(QLabel("dist (mm):"))
        cal_row.addWidget(self._rep_cal_dist)
        cal_w = QWidget(); cal_w.setLayout(cal_row)
        form.addRow(self._rep_cal)
        form.addRow("Calibration move:", cal_w)

        btn_row = QHBoxLayout()
        self._btn_repeat = QPushButton("Run Repeatability Test")
        set_button_icon(self._btn_repeat, "mdi.play")
        self._btn_repeat.clicked.connect(self._run_repeatability)
        self._btn_rep_stop = QPushButton("Stop")
        self._btn_rep_stop.setObjectName("dangerBtn")
        set_button_icon(self._btn_rep_stop, "mdi.stop", color="white")
        self._btn_rep_stop.setEnabled(False)
        self._btn_rep_stop.clicked.connect(self._stop_repeatability)
        btn_row.addWidget(self._btn_repeat)
        btn_row.addWidget(self._btn_rep_stop)
        btn_row.addStretch()
        bw = QWidget(); bw.setLayout(btn_row)
        form.addRow(bw)

        self._rep_progress = QLabel("")
        form.addRow(self._rep_progress)
        self._rep_result = QLabel("")
        # Token mono stack, PIXEL-sized (round-2 type pass — was pt-sized,
        # off the px scale every other readout uses).
        _mono = QFont()
        _mono.setFamilies(MONO_FAMILIES)
        _mono.setPixelSize(FONT_SM)
        _mono.setStyleHint(QFont.Monospace)
        self._rep_result.setFont(_mono)
        self._rep_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self._rep_result)

        # ── Motion hot zone, on the HazardSurface (round-03 kit §4.6) ──
        # The repeatability test DRIVES THE STAGE: this whole group (the Run
        # button, the #dangerBtn Stop at ~line 306, the progress/outcome
        # labels) is a PURE PARENT-FRAME WRAP inside an OPAQUE HazardSurface
        # carrying the ``armed`` (motion-class) stripe + 45° hatch — opaque at
        # every tier, never registered (register_glass_pane refuses a
        # HazardSurface outright). Only the container changed; the box, its
        # buttons and every bit of run/stop/worker logic are byte-identical.
        # refresh_theme re-resolves the surface's cached stripe/hatch/fill
        # (same idiom as BiasPanel/the sequencer wave, git show bf41854).
        self._hazard = HazardSurface(stripe="armed", theme_mode=self._theme_mode)
        self._hazard.add_widget(box)
        shelf.add_widget(self._hazard)

    # ------------------------------------------------------------------ #
    # Theme-token styling (gui.style) — re-run by refresh_theme()         #
    # ------------------------------------------------------------------ #

    def _restyle_theme_tokens(self) -> None:
        """Re-resolve per-instance label colours after a light/dark switch."""
        p = palette(self._theme_mode)
        self._current.setStyleSheet(f"color: {p['text']}; font-weight: bold;")
        self._rep_progress.setStyleSheet(f"color: {p['muted']};")

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve label colours baked into instance-level styles, and
        forward to the motion HazardSurface — it caches its stripe/hatch/fill
        per theme at construction, so a live light/dark switch must re-resolve
        them (same idiom as BiasPanel.refresh_theme; registered in
        ``tct_gui._toggle_theme``)."""
        if mode:
            self._theme_mode = str(mode)
        self._restyle_theme_tokens()
        self._hazard.refresh_theme(self._theme_mode)

    # ------------------------------------------------------------------ #
    # State <-> widgets                                                   #
    # ------------------------------------------------------------------ #

    def _load_from(self, cal: ChargeCalibration) -> None:
        self._method.setCurrentText(cal.method)
        self._units.setCurrentText(cal.output_units)
        self._termination.setValue(cal.termination_ohm)
        self._amp_gain.setValue(cal.amp_gain)
        self._transimpedance.setText("" if cal.transimpedance_ohm is None
                                     else str(cal.transimpedance_ohm))
        self._thickness.setValue(cal.diode_thickness_um)
        self._update_ref_labels(cal)
        self._on_method_changed(cal.method)
        self._refresh_current(cal)

    def _gather(self) -> ChargeCalibration:
        ti = self._transimpedance.text().strip()
        cal = ChargeCalibration(
            method=self._method.currentText(),
            termination_ohm=self._termination.value(),
            amp_gain=self._amp_gain.value(),
            transimpedance_ohm=float(ti) if _is_float(ti) else None,
            output_units=self._units.currentText(),
            diode_thickness_um=self._thickness.value(),
            q_ref_raw_pC=self._devices.charge_calibration.q_ref_raw_pC,
            k_factor=self._devices.charge_calibration.k_factor,
            calibrated_at=self._devices.charge_calibration.calibrated_at,
        )
        return cal

    def _update_ref_labels(self, cal: ChargeCalibration) -> None:
        self._lbl_qref.set_value("--" if cal.q_ref_raw_pC is None else f"{cal.q_ref_raw_pC:.4g} pC")
        self._lbl_k.set_value("--" if cal.k_factor is None else f"{cal.k_factor:.4g}")
        self._lbl_when.set_value(cal.calibrated_at or "never")
        valid = cal.q_ref_raw_pC is not None and cal.k_factor is not None
        self._chip_ref.set_status("Reference valid" if valid else "Reference missing",
                                  "good" if valid else "neutral")

    def _refresh_current(self, cal: ChargeCalibration) -> None:
        self._chip_method.set_status(f"Method {cal.method}",
                                     "neutral" if cal.method == "none" else "info")
        if cal.method == "none":
            self._current.setText("Active: no calibration — raw integral reported as pC.")
        elif cal.method == "electronics":
            self._current.setText(
                f"Active: electronics — gain {cal.amp_gain:g} V/V, "
                f"{cal.termination_ohm:g} Ω → output pC."
            )
        else:
            self._current.setText(
                f"Active: reference diode — k={cal.k_factor}, output {cal.output_units}."
            )

    def _on_method_changed(self, method: str) -> None:
        self._elec_box.setVisible(method == "electronics")
        self._ref_box.setVisible(method == "reference_diode")
        self._chip_method.set_status(f"Method {method}",
                                     "neutral" if method == "none" else "info")
        self._set_dirty(True)

    # ------------------------------------------------------------------ #
    # Reference routine                                                   #
    # ------------------------------------------------------------------ #

    def _confirm_reference_arm(self, n: int) -> bool:
        """Ask the injected gate to confirm arming the wavegen output for the
        reference-diode acquisition (rule 2).

        ``_ReferenceWorker.run()`` calls ``waveform_generator.output_on()`` —
        the same wavegen output ``laser_panel._output_on`` arms, i.e. the PDL
        800 laser trigger; arming it is emission if the manual head is armed.
        Confirms through the SAME injected gate, called on the GUI thread
        BEFORE the worker/thread are even constructed: a refusal must start
        nothing.

        With **no gate injected** the arm is REFUSED and surfaced — the same
        fail-safe stance this panel already takes for gate-less motion (see
        ``_run_repeatability`` below): an un-wired confirmation path must
        never degrade into "no confirmation needed".
        """
        wfg = self._devices.waveform_generator
        freq = getattr(wfg, "_frequency", None)
        ampl = getattr(wfg, "_amplitude", None)
        summary = f"Arm laser trigger — reference-diode acquisition ({n} averages)"
        if freq is not None and ampl is not None:
            summary += f", wavegen {freq:g} Hz / {ampl:g} Vpp"
        detail: dict = {"averages": n}
        if freq is not None:
            detail["frequency_Hz"] = freq
        if ampl is not None:
            detail["amplitude_Vpp"] = ampl
        action = DangerAction(kind="laser_arm", summary=summary, detail=detail)
        if self._gate is None:
            QMessageBox.warning(
                self, "Confirmation unavailable",
                f"{summary}\n\n"
                "This arms the laser trigger (wavegen output → PDL 800 "
                "trigger input) and needs a confirmation gate, which is not "
                "wired. Cannot proceed.")
            return False
        return bool(self._gate.confirm(action))

    def _run_reference(self) -> None:
        scope = self._devices.scope
        if not getattr(scope, "connected", False):
            QMessageBox.warning(self, "Not connected",
                                "Connect the oscilloscope first (Connect All).")
            return
        if self._ref_thread is not None and self._ref_thread.isRunning():
            return
        n = self._ref_averages.value()
        # Rule 2: confirm arming the laser trigger BEFORE the worker (which
        # arms the wavegen output) is even constructed. A decline (or no gate)
        # starts NOTHING — the worker/thread are never created.
        if not self._confirm_reference_arm(n):
            return
        self._chip_ref.set_status("Reference running", "busy")
        set_button_busy(self._btn_run, True, "Running...")
        self._ref_worker = _ReferenceWorker(self._devices, n)
        self._ref_thread = QThread(self)
        self._ref_worker.moveToThread(self._ref_thread)
        self._ref_thread.started.connect(self._ref_worker.run)
        self._ref_worker.finished.connect(self._on_reference_finished)
        self._ref_worker.finished.connect(self._ref_thread.quit)
        self._ref_thread.finished.connect(self._ref_thread.deleteLater)
        self._ref_thread.start()

    def _on_reference_finished(self, result: object) -> None:
        thread = self._ref_thread
        self._ref_thread = None
        self._ref_worker = None
        if thread is not None:
            thread.quit()
            thread.wait(2000)
        set_button_busy(self._btn_run, False)
        if isinstance(result, Exception):
            self._chip_ref.set_status("Reference failed", "crit", str(result))
            QMessageBox.critical(self, "Acquisition failed", str(result))
            return
        q_ref = float(result)
        thickness = self._thickness.value()
        cal = self._devices.charge_calibration
        k, expected = cal.compute_reference(q_ref, thickness)
        # Update the live object so _gather/_save persist it.
        cal.q_ref_raw_pC = q_ref
        cal.k_factor = k
        cal.diode_thickness_um = thickness
        cal.calibrated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._update_ref_labels(cal)
        self._status.setText(
            f"Reference acquired: Q_ref_raw = {q_ref:.4g} pC, "
            f"expected = {expected:.4g} pC (1 MIP @ {thickness:g} µm) → "
            f"k = {k:.4g}.  Click Apply &amp; Save to persist."
        )
        self._chip_ref.set_status("Reference acquired", "good")
        self._set_dirty(True)
        flash_button(self._btn_run, "good", "Acquired")

    # ------------------------------------------------------------------ #
    # Persist                                                             #
    # ------------------------------------------------------------------ #

    def _run_repeatability(self) -> None:
        motor = self._devices.motor
        cam = self._devices.camera
        if not getattr(motor, "connected", False):
            QMessageBox.warning(self, "Not connected",
                                "Connect the motor first (Connect All).")
            return
        if not getattr(motor, "homed", False):
            QMessageBox.warning(self, "Not homed",
                                "Home the stage before measuring repeatability.")
            return
        if not getattr(cam, "connected", False):
            QMessageBox.warning(self, "Not connected",
                                "Connect the camera first (Connect All).")
            return
        if self._gate is None:
            # Fail-safe: the tester refuses to move without a confirmation gate.
            # Surface it here rather than letting the worker raise mid-run.
            QMessageBox.warning(
                self, "Confirmation unavailable",
                "The repeatability test moves the stage and needs a "
                "confirmation gate, which is not wired. Cannot proceed.")
            return
        params = dict(
            n=self._rep_n.value(),
            approach=self._rep_approach.value(),
            settle=self._rep_settle.value(),
            calibrate=self._rep_cal.isChecked(),
            cal_axis=self._rep_cal_axis.currentText().lower(),
            cal_dist=self._rep_cal_dist.value(),
        )
        tester = RepeatabilityTester(motor, cam, logger, gate=self._gate)
        self._rep_worker = _RepeatWorker(tester, params)
        self._rep_thread = QThread(self)
        self._rep_worker.moveToThread(self._rep_thread)
        self._rep_thread.started.connect(self._rep_worker.run)
        self._rep_worker.progress.connect(self._on_rep_progress)
        self._rep_worker.finished.connect(self._on_rep_finished)
        self._btn_repeat.setEnabled(False)
        self._btn_rep_stop.setEnabled(True)
        self._rep_result.setText("")
        self._rep_progress.setText("Starting…")
        self._chip_repeat.set_status("Repeatability running", "busy")
        self._rep_thread.start()

    def _on_rep_progress(self, i: int, n: int) -> None:
        self._rep_progress.setText(f"Cycle {i}/{n}…")
        self._chip_repeat.set_status(f"Repeat {i}/{n}", "busy")

    def _on_rep_finished(self, res: object) -> None:
        thread = self._rep_thread
        self._rep_thread = None
        self._rep_worker = None
        if thread is not None:
            thread.quit()
            thread.wait(2000)
        self._btn_repeat.setEnabled(True)
        self._btn_rep_stop.setEnabled(False)
        if isinstance(res, Exception):
            self._rep_progress.setText("Failed.")
            self._chip_repeat.set_status("Repeatability failed", "crit", str(res))
            QMessageBox.critical(self, "Repeatability failed", str(res))
            return
        self._rep_progress.setText(f"Done ({res.n} cycles).")
        self._rep_result.setText(res.summary())
        self._chip_repeat.set_status("Repeatability done", "good")
        flash_button(self._btn_repeat, "good", "Done")

    def _stop_repeatability(self) -> None:
        if self._rep_worker is not None:
            self._rep_worker.stop()
        self._rep_progress.setText("Stopping after current cycle…")
        self._chip_repeat.set_status("Stopping", "warn")

    def shutdown(self) -> None:
        """Stop the repeatability worker thread — call before discarding."""
        if self._ref_thread is not None:
            self._ref_thread.quit()
            self._ref_thread.wait(3000)
        if self._rep_worker is not None:
            self._rep_worker.stop()
        if self._rep_thread is not None:
            self._rep_thread.quit()
            self._rep_thread.wait(3000)

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def _save(self) -> None:
        cal = self._gather()
        path = self._devices.cal_sidecar_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                yaml.dump(cal.to_config(), default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", f"Could not write:\n{exc}")
            return
        # Apply live
        self._devices.charge_calibration = cal
        self._refresh_current(cal)
        self._status.setText(f"Saved to {path.name} and applied.")
        self._set_dirty(False)
        flash_button(self._btn_save, "good", "Saved")
        self.calibration_changed.emit()
        logger.info("Charge calibration saved: method=%s units=%s k=%s",
                    cal.method, cal.output_units, cal.k_factor)


def _dspin(val: float, lo: float, hi: float, decimals: int) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setValue(val)
    return s


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False
