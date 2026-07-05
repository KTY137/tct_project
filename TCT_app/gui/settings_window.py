"""
TCT Settings Window.

Two-tab dialog for editing configs/devices.yaml without leaving the app.

Quick Settings tab
    Structured form covering the most important per-device options.
    Backend dropdowns show/hide the relevant sub-fields automatically.
    Changing any field immediately regenerates the YAML text in the other tab.

Full YAML tab
    Plain-text editor with YAML syntax highlighting and live parse validation.
    Editing here is the source of truth — Quick Settings reflects it when
    you switch back to that tab.

Save button  — writes the current YAML text to configs/devices.yaml.
Reload       — discards unsaved changes and re-reads the file from disk.

Changes that affect the device *backend* (e.g. visa → drs4) take effect on
the next app launch.  Pure parameter changes (compliance, speed, averages,
etc.) can be applied immediately without restart via "Save & Reconnect" in
the main window.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import Qt, QRegularExpression, Signal
from PySide6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "configs" / "devices.yaml"


# ─────────────────────────────────────────────────────────────────────
# YAML syntax highlighter
# ─────────────────────────────────────────────────────────────────────

class _YamlHighlighter(QSyntaxHighlighter):
    """Minimal YAML syntax highlighter for QPlainTextEdit."""

    def __init__(self, doc):
        super().__init__(doc)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        def _fmt(color: str, bold: bool = False) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(700)
            return f

        # Comment lines
        self._rules.append((QRegularExpression(r"#[^\n]*"), _fmt("#6a737d")))
        # Keys (word chars before colon)
        self._rules.append((QRegularExpression(r"^\s*[\w_-]+(?=\s*:)"), _fmt("#005cc5", bold=True)))
        # Quoted strings
        self._rules.append((QRegularExpression(r'"[^"]*"'), _fmt("#032f62")))
        self._rules.append((QRegularExpression(r"'[^']*'"), _fmt("#032f62")))
        # Booleans
        self._rules.append((QRegularExpression(r"\b(true|false|yes|no|null)\b"), _fmt("#e36209")))
        # Numbers
        self._rules.append((QRegularExpression(r"\b-?\d+\.?\d*([eE][+-]?\d+)?\b"), _fmt("#005cc5")))

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


# ─────────────────────────────────────────────────────────────────────
# Helper widgets
# ─────────────────────────────────────────────────────────────────────

def _dspin(val: float, lo: float = -1e9, hi: float = 1e9,
           decimals: int = 6) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setValue(val)
    return s


def _ispin(val: int, lo: int = 0, hi: int = 999999) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    return s


def _combo(options: list[str], current: str) -> QComboBox:
    c = QComboBox()
    c.addItems(options)
    idx = c.findText(current, Qt.MatchFixedString)
    if idx >= 0:
        c.setCurrentIndex(idx)
    return c


def _line(text: str) -> QLineEdit:
    le = QLineEdit(text)
    return le


class _VisaPicker(QWidget):
    """Editable dropdown of discovered VISA resources + a 🔄 scan button.

    Lets the user pick an instrument address instead of typing it; manual
    entry / paste still works (the combo is editable).  Scans once on creation
    and again on demand, so opening Settings already offers suggestions.
    """
    changed = Signal()

    def __init__(self, current: str = "") -> None:
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setMinimumWidth(260)
        self._combo.setToolTip("Pick a discovered VISA instrument, or type / paste "
                               "an address.  Click 🔄 to (re)scan.")
        btn = QToolButton()
        btn.setText("🔄")
        btn.setToolTip("Scan for connected VISA instruments (needs NI-VISA)")
        btn.clicked.connect(self._refresh)
        lan = QToolButton()
        lan.setText("🔎 LAN")
        lan.setToolTip("Auto-discover LAN/LXI instruments (mDNS), or enter an IP")
        lan.clicked.connect(self._add_lan)
        h.addWidget(self._combo, 1)
        h.addWidget(btn)
        h.addWidget(lan)
        # Scan once on open so suggestions are offered immediately.
        found, _err = self._scan()
        self._fill(current, found)
        self._combo.editTextChanged.connect(self.changed)
        # Normalise a bare IP to a TCPIP address when the user finishes editing.
        self._combo.lineEdit().editingFinished.connect(self._commit)

    @staticmethod
    def _normalize(s: str) -> str:
        """A bare IP / hostname (no '::') becomes a VXI-11 TCPIP address."""
        s = (s or "").strip()
        if s and "::" not in s and "..." not in s:
            return f"TCPIP0::{s}::INSTR"
        return s

    def _commit(self) -> None:
        norm = self._normalize(self._combo.currentText())
        if norm != self._combo.currentText().strip():
            self._combo.setCurrentText(norm)
            self.changed.emit()

    def _add_lan(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QInputDialog, QApplication
        # 1) try mDNS/LXI auto-discovery
        found: list[str] = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from devices.waveform_generator import discover_lan_instruments
            found = discover_lan_instruments()
        except Exception as exc:
            logger.info("LAN auto-discovery unavailable: %s", exc)
        finally:
            QApplication.restoreOverrideCursor()
        if found:
            for addr in found:
                if self._combo.findText(addr) < 0:
                    self._combo.addItem(addr)
            self._combo.setCurrentText(found[0])
            self.changed.emit()
            self._combo.showPopup()          # let the user pick among discovered
            return
        # 2) fall back to manual IP entry
        ip, ok = QInputDialog.getText(
            self.window(), "Add LAN instrument",
            "No instruments auto-discovered (mDNS).\nEnter IP or hostname:")
        if ok and ip.strip():
            addr = self._normalize(ip.strip())
            if self._combo.findText(addr) < 0:
                self._combo.addItem(addr)
            self._combo.setCurrentText(addr)
            self.changed.emit()

    @staticmethod
    def _looks_placeholder(s: str) -> bool:
        """True for empty / obviously-not-a-real-address values (e.g. the
        'USB0::...' placeholder shipped in devices.yaml)."""
        s = (s or "").strip()
        return (not s) or ("..." in s) or ("::" not in s)

    @staticmethod
    def _scan() -> tuple[list[str], str | None]:
        """Return (resources, error_message). error is None on success."""
        try:
            from devices.waveform_generator import list_visa_resources
            return list_visa_resources(), None
        except Exception as exc:
            logger.info("VISA scan failed: %s", exc)
            return [], str(exc)

    def _fill(self, current: str, found: list[str]) -> None:
        items = list(found)
        if current and not self._looks_placeholder(current) and current not in items:
            items.append(current)
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItems(items)
        # Auto-select a discovered address when the saved one is just a
        # placeholder — so discovery is visible instead of hidden in the list.
        if found and self._looks_placeholder(current):
            self._combo.setCurrentText(found[0])
        else:
            self._combo.setCurrentText(current)
        self._combo.blockSignals(False)

    def _refresh(self) -> None:
        found, err = self._scan()
        keep = "" if self._looks_placeholder(self.text()) else self.text()
        self._fill(keep, found)
        self.changed.emit()
        if found:
            self._combo.showPopup()          # show the discovered list
        else:
            QMessageBox.information(
                self.window(), "VISA scan",
                err or "No VISA instruments found.\n"
                "Check the USB connection and that NI-VISA is installed.")

    def text(self) -> str:
        return self._normalize(self._combo.currentText())


# ─────────────────────────────────────────────────────────────────────
# Quick-settings sections
# ─────────────────────────────────────────────────────────────────────

class _OscilloscopeSection(QGroupBox):
    changed = Signal()

    def __init__(self, cfg: dict) -> None:
        super().__init__("Oscilloscope")
        self._build(cfg)

    def _build(self, cfg: dict) -> None:
        form = QFormLayout(self)

        self._backend = _combo(["visa", "drs4"], cfg.get("backend", "visa"))
        form.addRow("Backend:", self._backend)

        # ── VISA fields ───────────────────────────────────────────────
        self._visa_frame = QWidget()
        vf = QFormLayout(self._visa_frame)
        vf.setContentsMargins(0, 0, 0, 0)
        self._visa_addr   = _VisaPicker(str(cfg.get("visa_address", "")))
        self._vendor      = _combo(["lecroy", "tektronix", "keysight", "rigol"],
                                    cfg.get("vendor", "lecroy"))
        self._timeout_ms  = _ispin(cfg.get("timeout_ms", 10000), 100, 120000)
        vf.addRow("VISA address:", self._visa_addr)
        vf.addRow("Vendor:", self._vendor)
        vf.addRow("Timeout (ms):", self._timeout_ms)
        _trig_note = QLabel("Trigger (source / level / slope) is set in the "
                            "Oscilloscope panel → Trigger Settings.")
        _trig_note.setWordWrap(True)
        _trig_note.setStyleSheet("color:#888; font-size:11px;")
        vf.addRow(_trig_note)
        form.addRow(self._visa_frame)

        # ── DRS4 fields ───────────────────────────────────────────────
        self._drs4_frame = QWidget()
        df = QFormLayout(self._drs4_frame)
        df.setContentsMargins(0, 0, 0, 0)
        self._freq       = _dspin(cfg.get("frequency_ghz", 5.0), 1.0, 5.0, 1)
        self._vrange     = _combo(["0  (±500 mV)", "1  (0–1 V)"],
                                    str(cfg.get("voltage_range", 0)))
        self._trig_lvl_d = _dspin(cfg.get("trigger_level_V", -0.05), decimals=3)
        self._trig_edge  = _combo(["FALL", "RISE"], cfg.get("trigger_edge", "FALL"))
        self._t0_thresh  = _dspin(cfg.get("t0_threshold_V", -0.45), decimals=3)
        df.addRow("Frequency (GHz):",  self._freq)
        df.addRow("Voltage range:",    self._vrange)
        df.addRow("Trigger level (V):", self._trig_lvl_d)
        df.addRow("Trigger edge:",     self._trig_edge)
        df.addRow("t0 threshold (V):", self._t0_thresh)
        form.addRow(self._drs4_frame)

        # ── Shared ────────────────────────────────────────────────────
        self._n_avg   = _ispin(cfg.get("n_averages", 1), 1, 10000)
        self._sim     = _combo(["true", "false"],
                                "true" if cfg.get("simulation", True) else "false")
        form.addRow("Averages:", self._n_avg)
        form.addRow("Simulation:", self._sim)

        self._backend.currentTextChanged.connect(self._on_backend)
        self._on_backend(self._backend.currentText())

        for w in (self._visa_addr, self._vendor, self._timeout_ms,
                  self._freq, self._vrange, self._trig_lvl_d, self._trig_edge,
                  self._t0_thresh, self._n_avg, self._sim):
            _connect_changed(w, self.changed)

    def _on_backend(self, text: str) -> None:
        is_visa = text == "visa"
        self._visa_frame.setVisible(is_visa)
        self._drs4_frame.setVisible(not is_visa)
        self.changed.emit()

    def to_dict(self) -> dict:
        backend = self._backend.currentText()
        d: dict[str, Any] = {
            "backend": backend,
            "n_averages": self._n_avg.value(),
            "simulation": self._sim.currentText() == "true",
        }
        if backend == "visa":
            d.update({
                "visa_address": self._visa_addr.text(),
                "vendor": self._vendor.currentText(),
                "timeout_ms": self._timeout_ms.value(),
            })
        else:
            vr_text = self._vrange.currentText()
            vr = int(vr_text.split()[0]) if vr_text[0].isdigit() else 0
            d.update({
                "frequency_ghz": self._freq.value(),
                "voltage_range": vr,
                "trigger_level_V": self._trig_lvl_d.value(),
                "trigger_edge": self._trig_edge.currentText(),
                "trigger_source": "EXT",
                "time_correction": True,
                "t0_ns": 20.0,
                "t0_threshold_V": self._t0_thresh.value(),
                "timeout_s": 2.0,
            })
        return d


class _MotorSection(QGroupBox):
    changed = Signal()

    def __init__(self, cfg: dict) -> None:
        super().__init__("Motor Stage")
        self._build(cfg)

    def _build(self, cfg: dict) -> None:
        from devices.printer_presets import PRINTER_PRESETS, get_preset

        form = QFormLayout(self)

        # ── Printer model preset ──────────────────────────────────────
        # Picking a machine fills in backend, firmware dialect, feed rate and
        # the software travel limits for that build volume.  "Custom" applies
        # nothing so the fields below stay hand-editable.
        self._model = QComboBox()
        for key, p in PRINTER_PRESETS.items():
            self._model.addItem(p.label, key)
        cur_model = str(cfg.get("model", "custom")).lower()
        midx = self._model.findData(cur_model)
        self._model.setCurrentIndex(midx if midx >= 0 else self._model.findData("custom"))
        form.addRow("Printer model:", self._model)

        self._backend = _combo(["grbl", "pi", "simulated"], cfg.get("backend", "grbl"))
        form.addRow("Backend:", self._backend)

        # Limit values: explicit YAML software_limits win; otherwise fall back
        # to the selected preset's build volume.
        sl = cfg.get("software_limits") or {}
        preset = get_preset(cur_model)

        def _lim(key: str, default: float) -> float:
            return sl.get(key, preset.limits.get(key, default))

        def _pair(a: QWidget, b: QWidget) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(a)
            h.addWidget(QLabel("…"))
            h.addWidget(b)
            return w

        def _triple(a: QWidget, b: QWidget, c: QWidget) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            for x in (a, b, c):
                h.addWidget(x)
            return w

        # GRBL
        self._grbl_frame = QWidget()
        gf = QFormLayout(self._grbl_frame)
        gf.setContentsMargins(0, 0, 0, 0)
        self._serial_port = _line(cfg.get("serial_port", "COM5"))
        self._feed_rate   = _ispin(cfg.get("feed_rate_mm_min", preset.feed_rate_mm_min), 100, 10000)
        self._marlin      = _combo(["true", "false"],
                                    "true" if cfg.get("marlin", preset.marlin) else "false")
        # Signed software limits.  GRBL machines that home to a corner have a
        # NEGATIVE work envelope (0 → -max), so both min and max are editable.
        self._lim_xmin = _dspin(_lim("x_min_mm", -300.0), -2000.0, 2000.0, 1)
        self._lim_xmax = _dspin(_lim("x_max_mm",    0.0), -2000.0, 2000.0, 1)
        self._lim_ymin = _dspin(_lim("y_min_mm", -300.0), -2000.0, 2000.0, 1)
        self._lim_ymax = _dspin(_lim("y_max_mm",    0.0), -2000.0, 2000.0, 1)
        self._lim_zmin = _dspin(_lim("z_min_mm", -400.0), -2000.0, 2000.0, 1)
        self._lim_zmax = _dspin(_lim("z_max_mm",    0.0), -2000.0, 2000.0, 1)
        # Microstepping / step-snapping
        spm = cfg.get("steps_per_mm") or {}
        if not isinstance(spm, dict):
            spm = {"x": spm, "y": spm, "z": spm}
        self._spm_x = _dspin(float(spm.get("x", 80.0)), 1.0, 100000.0, 3)
        self._spm_y = _dspin(float(spm.get("y", 80.0)), 1.0, 100000.0, 3)
        self._spm_z = _dspin(float(spm.get("z", 80.0)), 1.0, 100000.0, 3)
        self._microsteps = _combo(["1", "2", "4", "8", "16"], str(cfg.get("microsteps", 16)))
        self._snap_mode  = _combo(["off", "full"], str(cfg.get("snap_mode", "off")))
        self._push_steps = _combo(["false", "true"],
                                   "true" if cfg.get("push_steps_to_grbl", False) else "false")
        gf.addRow("Serial port:", self._serial_port)
        gf.addRow("Feed rate (mm/min):", self._feed_rate)
        gf.addRow("Marlin firmware:", self._marlin)
        gf.addRow("X limits min / max (mm):", _pair(self._lim_xmin, self._lim_xmax))
        gf.addRow("Y limits min / max (mm):", _pair(self._lim_ymin, self._lim_ymax))
        gf.addRow("Z limits min / max (mm):", _pair(self._lim_zmin, self._lim_zmax))
        gf.addRow("Steps/mm X·Y·Z:", _triple(self._spm_x, self._spm_y, self._spm_z))
        gf.addRow("Microsteps (jumper):", self._microsteps)
        gf.addRow("Snap to detents:", self._snap_mode)
        gf.addRow("Push steps/mm on connect:", self._push_steps)
        _note = QLabel("A4988: 1/16 max via jumpers; current via Vref pot "
                       "(I = Vref / 0.4 with R050) — not software-settable. "
                       "Snap=full parks the motor on stable detents (~0.2 mm grid) "
                       "to stop hunting/overheating.")
        _note.setWordWrap(True)
        _note.setStyleSheet("color:#888; font-size:11px;")
        gf.addRow(_note)
        form.addRow(self._grbl_frame)

        # PI
        self._pi_frame = QWidget()
        pf = QFormLayout(self._pi_frame)
        pf.setContentsMargins(0, 0, 0, 0)
        self._pi_port     = _line(cfg.get("serial_port", "COM3"))
        self._pi_velocity = _dspin(cfg.get("velocity", 2.0), 0.01, 100.0, 2)
        pf.addRow("Serial port:", self._pi_port)
        pf.addRow("Velocity (mm/s):", self._pi_velocity)
        form.addRow(self._pi_frame)

        self._sim = _combo(["false", "true"],
                            "true" if cfg.get("simulation", False) else "false")
        form.addRow("Simulation:", self._sim)

        self._model.currentIndexChanged.connect(self._apply_preset)
        self._backend.currentTextChanged.connect(self._on_backend)
        self._on_backend(self._backend.currentText())

        for w in (self._serial_port, self._feed_rate, self._marlin,
                  self._lim_xmin, self._lim_xmax, self._lim_ymin,
                  self._lim_ymax, self._lim_zmin, self._lim_zmax,
                  self._spm_x, self._spm_y, self._spm_z, self._microsteps,
                  self._snap_mode, self._push_steps,
                  self._pi_port, self._pi_velocity, self._sim):
            _connect_changed(w, self.changed)

    def _apply_preset(self) -> None:
        """Fill backend / firmware / feed / limits from the chosen printer preset."""
        from devices.printer_presets import get_preset
        key = self._model.currentData()
        p = get_preset(key)
        if key == "custom":
            self.changed.emit()
            return
        bidx = self._backend.findText(p.backend, Qt.MatchFixedString)
        if bidx >= 0:
            self._backend.setCurrentIndex(bidx)
        self._marlin.setCurrentText("true" if p.marlin else "false")
        self._feed_rate.setValue(p.feed_rate_mm_min)
        if p.limits:
            self._lim_xmin.setValue(p.limits.get("x_min_mm", self._lim_xmin.value()))
            self._lim_xmax.setValue(p.limits.get("x_max_mm", self._lim_xmax.value()))
            self._lim_ymin.setValue(p.limits.get("y_min_mm", self._lim_ymin.value()))
            self._lim_ymax.setValue(p.limits.get("y_max_mm", self._lim_ymax.value()))
            self._lim_zmin.setValue(p.limits.get("z_min_mm", self._lim_zmin.value()))
            self._lim_zmax.setValue(p.limits.get("z_max_mm", self._lim_zmax.value()))
        self.changed.emit()

    def _on_backend(self, text: str) -> None:
        self._grbl_frame.setVisible(text == "grbl")
        self._pi_frame.setVisible(text == "pi")
        self.changed.emit()

    def to_dict(self) -> dict:
        backend = self._backend.currentText()
        model = self._model.currentData()
        d: dict[str, Any] = {
            "backend": backend,
            "model": model,
            "simulation": self._sim.currentText() == "true",
        }
        if backend == "grbl":
            d.update({
                "serial_port": self._serial_port.text(),
                "feed_rate_mm_min": self._feed_rate.value(),
                "marlin": self._marlin.currentText() == "true",
                "baudrate": 115200,
                "steps_per_mm": {
                    "x": self._spm_x.value(),
                    "y": self._spm_y.value(),
                    "z": self._spm_z.value(),
                },
                "microsteps": int(self._microsteps.currentText()),
                "snap_mode": self._snap_mode.currentText(),
                "push_steps_to_grbl": self._push_steps.currentText() == "true",
                # Fully user-editable, signed travel limits (negative envelope
                # for corner-homing GRBL machines).
                "software_limits": {
                    "x_min_mm": self._lim_xmin.value(),
                    "x_max_mm": self._lim_xmax.value(),
                    "y_min_mm": self._lim_ymin.value(),
                    "y_max_mm": self._lim_ymax.value(),
                    "z_min_mm": self._lim_zmin.value(),
                    "z_max_mm": self._lim_zmax.value(),
                },
            })
        elif backend == "pi":
            d.update({
                "serial_port": self._pi_port.text(),
                "velocity": self._pi_velocity.value(),
                "baudrate_pi": 115200,
                "axes": [1, 2, 3],
            })
        return d


class _BiasSection(QGroupBox):
    changed = Signal()

    def __init__(self, cfg: dict) -> None:
        super().__init__("Bias Supply")
        self._build(cfg)

    def _build(self, cfg: dict) -> None:
        form = QFormLayout(self)
        self._backend = _combo(["simulated", "keithley", "e4control", "iseg"],
                                cfg.get("backend", "simulated"))
        form.addRow("Backend:", self._backend)

        # ── Keithley (VISA — USB / GPIB / LAN) ───────────────────────
        self._keithley_frame = QWidget()
        kf = QFormLayout(self._keithley_frame)
        kf.setContentsMargins(0, 0, 0, 0)
        self._k_visa = _VisaPicker(str(cfg.get("visa_address", "")))
        kf.addRow("VISA address:", self._k_visa)
        _k_note = QLabel("USB, GPIB, or LAN via VISA (e.g. USB0::0x05e6::0x2410::...::INSTR)")
        _k_note.setWordWrap(True)
        _k_note.setStyleSheet("color:#888; font-size:11px;")
        kf.addRow(_k_note)
        form.addRow(self._keithley_frame)

        # ── e4control (special wrapper — host/port, not VISA) ────────
        self._e4c_frame = QWidget()
        ef = QFormLayout(self._e4c_frame)
        ef.setContentsMargins(0, 0, 0, 0)
        self._e4c_dev   = _combo(["K2410", "K487", "K617", "K2614"],
                                    cfg.get("e4c_device", "K2410"))
        self._conn_type = _combo(["gpib", "lan", "prologix", "serial"],
                                    cfg.get("connection_type", "gpib"))
        self._host      = _line(cfg.get("host", "192.168.1.100"))
        self._port      = _line(str(cfg.get("port", 22)))
        ef.addRow("Device:", self._e4c_dev)
        ef.addRow("Connection:", self._conn_type)
        ef.addRow("Host / IP:", self._host)
        ef.addRow("Port / GPIB addr:", self._port)
        form.addRow(self._e4c_frame)

        # ── iseg (VISA — USB or LAN socket) ───────────────────────────
        self._iseg_frame = QWidget()
        gf = QFormLayout(self._iseg_frame)
        gf.setContentsMargins(0, 0, 0, 0)
        # Auto-convert legacy host:port to TCPIP::SOCKET for the picker.
        iseg_addr = str(cfg.get("visa_address", ""))
        if not iseg_addr and cfg.get("host"):
            iseg_addr = f"TCPIP0::{cfg.get('host')}::{cfg.get('port', 10001)}::SOCKET"
        self._iseg_visa = _VisaPicker(iseg_addr)
        self._iseg_ch   = _ispin(cfg.get("channel", 0), 0, 15)
        self._iseg_ramp = _dspin(cfg.get("ramp_speed_V_s", 50.0), 0.1, 5000.0, 1)
        gf.addRow("VISA address:", self._iseg_visa)
        _iseg_note = QLabel(
            "USB/serial (ASRL5::INSTR for COM5, or ASRL/dev/ttyUSB0::INSTR on Linux) "
            "or LAN socket (TCPIP0::192.168.1.30::10001::SOCKET). "
            "iseg USB appears as a virtual COM port (CDC/VCP), NOT as USB0::..."
        )
        _iseg_note.setWordWrap(True)
        _iseg_note.setStyleSheet("color:#888; font-size:11px;")
        gf.addRow(_iseg_note)
        gf.addRow("Channel (HV-OUT):", self._iseg_ch)
        gf.addRow("Ramp (V/s):", self._iseg_ramp)
        form.addRow(self._iseg_frame)

        # ── Shared (all backends) ─────────────────────────────────────
        self._compliance = _dspin(cfg.get("compliance_A", 100e-6) * 1e6, 0.001, 10000.0, 3)
        comp_row = QHBoxLayout()
        comp_row.addWidget(self._compliance)
        comp_row.addWidget(QLabel("µA"))
        comp_widget = QWidget()
        comp_widget.setLayout(comp_row)
        form.addRow("Compliance:", comp_widget)

        self._backend.currentTextChanged.connect(self._on_backend)
        self._on_backend(self._backend.currentText())

        for w in (self._k_visa, self._e4c_dev, self._conn_type,
                  self._host, self._port, self._compliance,
                  self._iseg_visa, self._iseg_ch, self._iseg_ramp):
            _connect_changed(w, self.changed)

    def _on_backend(self, text: str) -> None:
        self._keithley_frame.setVisible(text == "keithley")
        self._e4c_frame.setVisible(text == "e4control")
        self._iseg_frame.setVisible(text == "iseg")
        self.changed.emit()

    def to_dict(self) -> dict:
        backend = self._backend.currentText()
        d: dict[str, Any] = {
            "backend": backend,
            "compliance_A": self._compliance.value() * 1e-6,
        }
        if backend == "keithley":
            d["visa_address"] = self._k_visa.text()
            d["voltage_range_V"] = 1100
            d["timeout_ms"] = 10000
        elif backend == "e4control":
            d.update({
                "e4c_device": self._e4c_dev.currentText(),
                "connection_type": self._conn_type.currentText(),
                "host": self._host.text(),
                "port": int(self._port.text()) if self._port.text().isdigit() else self._port.text(),
                "ramp_step_V": 10,
                "ramp_delay_s": 1,
            })
        elif backend == "iseg":
            d.update({
                "visa_address": self._iseg_visa.text(),
                "channel": self._iseg_ch.value(),
                "ramp_speed_V_s": self._iseg_ramp.value(),
                "voltage_range_V": 2000,
                "timeout_ms": 5000,
            })
        return d


class _DataSavingSection(QGroupBox):
    """Choose the output directory and which dataset groups each scan saves.

    ``waveforms`` and ``positions`` are mandatory and shown locked-on.  ``bias``
    and ``slow_control`` are *measured* scalars (cannot be recomputed offline),
    flagged with a warning.  ``analysis`` is derived and safe to disable.
    """
    changed = Signal()

    # (key, label, default, locked, note)
    _ROWS = [
        ("waveforms",    "Waveforms (raw ref/dut traces)",     True,  True,  "mandatory"),
        ("positions",    "Positions (x / y / z)",              True,  True,  "mandatory"),
        ("timestamp",    "Timestamp",                          True,  False, ""),
        ("analysis",     "Analysis (amplitude/charge/timing)", True,  False, "derived — recomputable"),
        ("bias",         "Bias V / I",                         True,  False, "measured — NOT recomputable"),
        ("slow_control", "Slow-control snapshot",              False, False, "measured — NOT recomputable"),
        ("camera_frame", "Camera frame per point",             False, False, "large"),
        ("run_metadata", "Run metadata (config snapshot)",     True,  False, ""),
    ]

    def __init__(self, cfg: dict) -> None:
        super().__init__("Data / Saving")
        self._build(cfg)

    def _build(self, cfg: dict) -> None:
        form = QFormLayout(self)

        self._data_dir = _line(cfg.get("data_dir", "runs"))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self._data_dir)
        dir_row.addWidget(browse)
        dir_w = QWidget(); dir_w.setLayout(dir_row)
        form.addRow("Data directory:", dir_w)
        _connect_changed(self._data_dir, self.changed)

        save = cfg.get("save", {})
        self._checks: dict[str, QCheckBox] = {}
        for key, label, default, locked, note in self._ROWS:
            cb = QCheckBox(label)
            cb.setChecked(True if locked else bool(save.get(key, default)))
            if locked:
                cb.setEnabled(False)
                cb.setToolTip("Mandatory — always saved")
            cb.toggled.connect(self.changed)
            self._checks[key] = cb
            if note:
                lbl = QLabel(note)
                warn = "NOT recomputable" in note
                lbl.setStyleSheet(
                    "color:%s; font-size:11px;" % ("#c0392b" if warn else "#888")
                )
                row = QHBoxLayout()
                row.addWidget(cb); row.addStretch(); row.addWidget(lbl)
                cont = QWidget(); cont.setLayout(row)
                form.addRow(cont)
            else:
                form.addRow(cb)

    def _browse(self) -> None:
        start = self._data_dir.text() or str(Path.cwd())
        d = QFileDialog.getExistingDirectory(self, "Select data directory", start)
        if d:
            self._data_dir.setText(d)

    def to_dict(self) -> dict:
        return {
            "data_dir": self._data_dir.text() or "runs",
            "save": {key: cb.isChecked() for key, cb in self._checks.items()},
        }


class _WaveformSection(QGroupBox):
    """Waveform generator (trigger / rep-rate source — Rigol DG4000, Tek, …)."""
    changed = Signal()

    def __init__(self, cfg: dict) -> None:
        super().__init__("Waveform Generator")
        form = QFormLayout(self)
        self._addr   = _VisaPicker(str(cfg.get("visa_address", "")))
        self._vendor = _combo(["rigol", "tektronix", "keysight", "siglent", "generic"],
                              str(cfg.get("vendor", "rigol")))
        self._ch     = _ispin(cfg.get("output_channel", 1), 1, 4)
        self._sim    = _combo(["false", "true"],
                              "true" if cfg.get("simulation", True) else "false")
        form.addRow("VISA address:", self._addr)
        form.addRow("Vendor:", self._vendor)
        form.addRow("Output channel:", self._ch)
        form.addRow("Simulation:", self._sim)
        note = QLabel("Frequency / pulse width / amplitude are live controls on "
                      "the Laser/Trigger panel.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888; font-size:11px;")
        form.addRow(note)
        for w in (self._addr, self._vendor, self._ch, self._sim):
            _connect_changed(w, self.changed)

    def to_dict(self) -> dict:
        # Connection / identity only — signal params (frequency / pulse_width /
        # amplitude) are live on the panel and preserved in YAML via .update().
        return {
            "visa_address": self._addr.text(),
            "vendor": self._vendor.currentText(),
            "output_channel": self._ch.value(),
            "simulation": self._sim.currentText() == "true",
        }


class _CameraSection(QGroupBox):
    """FLIR Blackfly camera (beam / repeatability imaging)."""
    changed = Signal()

    def __init__(self, cfg: dict) -> None:
        super().__init__("Camera")
        form = QFormLayout(self)
        self._serial   = _line(str(cfg.get("serial_number", "")))
        self._exposure = _dspin(cfg.get("exposure_us", 5000.0), 1.0, 1e7, 1)
        self._gain     = _dspin(cfg.get("gain_db", 0.0), 0.0, 48.0, 2)
        self._binning  = _ispin(cfg.get("binning", 1), 1, 8)
        self._fps      = _dspin(cfg.get("fps", 10.0), 0.1, 1000.0, 1)
        self._sim      = _combo(["false", "true"],
                                "true" if cfg.get("simulation", True) else "false")
        form.addRow("Serial number:", self._serial)
        form.addRow("Exposure (µs):", self._exposure)
        form.addRow("Gain (dB):", self._gain)
        form.addRow("Binning:", self._binning)
        form.addRow("FPS:", self._fps)
        form.addRow("Simulation:", self._sim)
        for w in (self._serial, self._exposure, self._gain,
                  self._binning, self._fps, self._sim):
            _connect_changed(w, self.changed)

    def to_dict(self) -> dict:
        # Only the managed keys — merged with .update() so pixel_format / gamma
        # in devices.yaml are preserved.
        return {
            "serial_number": self._serial.text(),
            "exposure_us": self._exposure.value(),
            "gain_db": self._gain.value(),
            "binning": self._binning.value(),
            "fps": self._fps.value(),
            "simulation": self._sim.currentText() == "true",
        }


def _connect_changed(widget: QWidget, sig: Signal) -> None:
    """Wire the appropriate change signal for each widget type to *sig*."""
    if isinstance(widget, _VisaPicker):
        widget.changed.connect(sig)
    elif isinstance(widget, (QLineEdit,)):
        widget.textChanged.connect(sig)
    elif isinstance(widget, QComboBox):
        widget.currentTextChanged.connect(sig)
    elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
        widget.valueChanged.connect(sig)


# ─────────────────────────────────────────────────────────────────────
# Main settings window
# ─────────────────────────────────────────────────────────────────────

class SettingsWindow(QDialog):
    """
    Modal-free settings dialog.  Call show() to open it as a non-blocking window.

    Signals
    -------
    saved(path)  — emitted after the YAML file has been written successfully.
    """
    saved = Signal(str)   # path to saved file

    def __init__(self, config_path: Path = _CONFIG_PATH,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings — devices.yaml")
        self.resize(820, 680)
        self._config_path = config_path
        self._suppress_yaml_update = False
        self._build_ui()
        self._load_file()

    # ------------------------------------------------------------------ #
    # UI construction                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── File path label ───────────────────────────────────────────
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Config file:"))
        self._lbl_path = QLabel(str(self._config_path))
        self._lbl_path.setStyleSheet("color: #555; font-style: italic;")
        path_row.addWidget(self._lbl_path, 1)
        root.addLayout(path_row)

        # ── Tabs ──────────────────────────────────────────────────────
        self._tabs = QTabWidget()

        # Tab 1: Quick Settings
        quick_scroll = QScrollArea()
        quick_scroll.setWidgetResizable(True)
        quick_widget = QWidget()
        self._quick_layout = QVBoxLayout(quick_widget)
        self._quick_layout.setAlignment(Qt.AlignTop)
        # Sections are populated after loading the file (need the parsed cfg)
        self._scope_section:  _OscilloscopeSection | None = None
        self._motor_section:  _MotorSection | None = None
        self._wfg_section:    _WaveformSection | None = None
        self._cam_section:    _CameraSection | None = None
        self._bias_section:   _BiasSection | None = None
        self._data_section:   _DataSavingSection | None = None
        quick_scroll.setWidget(quick_widget)
        self._tabs.addTab(quick_scroll, "Quick Settings")

        # Tab 2: Full YAML
        yaml_widget = QWidget()
        yaml_layout = QVBoxLayout(yaml_widget)
        self._editor = QPlainTextEdit()
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.Monospace)
        self._editor.setFont(font)
        self._editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._highlighter = _YamlHighlighter(self._editor.document())
        self._parse_error_label = QLabel("")
        self._parse_error_label.setStyleSheet("color: #c0392b; font-weight: bold;")
        self._parse_error_label.setVisible(False)
        self._editor.textChanged.connect(self._on_yaml_changed)
        yaml_layout.addWidget(self._editor)
        yaml_layout.addWidget(self._parse_error_label)
        self._tabs.addTab(yaml_widget, "Full YAML")

        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs)

        # ── Status bar / info ─────────────────────────────────────────
        info = QLabel(
            "Backend changes (e.g. visa → drs4) take effect on the next app launch.  "
            "Parameter changes (compliance, speed, averages) can be applied live via "
            "Disconnect → Save → Connect All."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #666; font-size: 11px;")
        root.addWidget(info)

        # ── Buttons ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_reload = QPushButton("Reload from File")
        self._btn_reload.clicked.connect(self._load_file)
        btn_save = QPushButton("Save")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._save)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(self._btn_reload)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------ #
    # Loading                                                             #
    # ------------------------------------------------------------------ #

    def _load_file(self) -> None:
        """Read devices.yaml and populate both tabs."""
        try:
            text = self._config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            QMessageBox.critical(self, "File Not Found",
                                 f"Config file not found:\n{self._config_path}")
            return

        # Put raw text in editor (suppress re-parse → quick-settings update)
        self._suppress_yaml_update = True
        self._editor.setPlainText(text)
        self._suppress_yaml_update = False

        try:
            cfg = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            self._show_parse_error(str(exc))
            return

        self._parse_error_label.setVisible(False)
        self._rebuild_quick_settings(cfg)

    def _rebuild_quick_settings(self, cfg: dict) -> None:
        """Tear down and recreate the Quick Settings section widgets."""
        # Remove old sections
        for sec in (self._scope_section, self._motor_section, self._wfg_section,
                    self._cam_section, self._bias_section, self._data_section):
            if sec is not None:
                self._quick_layout.removeWidget(sec)
                sec.deleteLater()

        self._scope_section = _OscilloscopeSection(cfg.get("oscilloscope", {}))
        self._motor_section = _MotorSection(cfg.get("motor_stage", {}))
        self._wfg_section   = _WaveformSection(cfg.get("waveform_generator", {}))
        self._cam_section   = _CameraSection(cfg.get("camera", {}))
        self._bias_section  = _BiasSection(cfg.get("bias_supply", {}))
        self._data_section  = _DataSavingSection(cfg.get("output", {}))

        for sec in (self._scope_section, self._motor_section, self._wfg_section,
                    self._cam_section, self._bias_section, self._data_section):
            sec.changed.connect(self._on_quick_settings_changed)
            self._quick_layout.addWidget(sec)

        self._quick_layout.addStretch()

    # ------------------------------------------------------------------ #
    # Tab switching                                                       #
    # ------------------------------------------------------------------ #

    def _on_tab_changed(self, index: int) -> None:
        if index == 0:
            # Switching to Quick Settings — parse YAML and rebuild widgets
            text = self._editor.toPlainText()
            try:
                cfg = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                return  # keep old widgets; parse error shown in YAML tab
            self._rebuild_quick_settings(cfg)

    # ------------------------------------------------------------------ #
    # Quick Settings → YAML                                              #
    # ------------------------------------------------------------------ #

    def _on_quick_settings_changed(self) -> None:
        """
        Regenerate the YAML editor content from the Quick Settings form values.
        Called whenever any form widget changes.
        """
        if self._suppress_yaml_update:
            return
        # Parse existing YAML to preserve other sections
        try:
            cfg = yaml.safe_load(self._editor.toPlainText()) or {}
        except yaml.YAMLError:
            cfg = {}

        # Overwrite changed sections
        if self._scope_section:
            # .update() so the trigger_* keys (now owned by the panel's Trigger
            # Settings window) survive a Quick-Settings save.
            cfg.setdefault("oscilloscope", {}).update(self._scope_section.to_dict())
        if self._motor_section:
            cfg["motor_stage"] = self._motor_section.to_dict()
        if self._wfg_section:
            cfg.setdefault("waveform_generator", {}).update(self._wfg_section.to_dict())
        if self._cam_section:
            # .update() so YAML-only keys (pixel_format, gamma_*) survive.
            cfg.setdefault("camera", {}).update(self._cam_section.to_dict())
        if self._bias_section:
            cfg["bias_supply"] = self._bias_section.to_dict()
        if self._data_section:
            cfg["output"] = self._data_section.to_dict()

        new_text = yaml.dump(cfg, default_flow_style=False, sort_keys=False, allow_unicode=True)
        self._suppress_yaml_update = True
        self._editor.setPlainText(
            "# Generated by Quick Settings — edit freely below\n" + new_text
        )
        self._suppress_yaml_update = False

    # ------------------------------------------------------------------ #
    # YAML → parse validation                                            #
    # ------------------------------------------------------------------ #

    def _on_yaml_changed(self) -> None:
        if self._suppress_yaml_update:
            return
        text = self._editor.toPlainText()
        try:
            yaml.safe_load(text)
            self._parse_error_label.setVisible(False)
            self._editor.setStyleSheet("")
        except yaml.YAMLError as exc:
            self._show_parse_error(str(exc))

    def _show_parse_error(self, msg: str) -> None:
        self._parse_error_label.setText(f"YAML parse error: {msg}")
        self._parse_error_label.setVisible(True)
        self._editor.setStyleSheet("border: 2px solid #c0392b;")

    # ------------------------------------------------------------------ #
    # Save                                                                #
    # ------------------------------------------------------------------ #

    def _save(self) -> None:
        text = self._editor.toPlainText()
        try:
            yaml.safe_load(text)   # validate before writing
        except yaml.YAMLError as exc:
            QMessageBox.critical(self, "Save Failed",
                                 f"Cannot save: YAML is not valid.\n\n{exc}")
            return

        try:
            self._config_path.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed",
                                 f"Could not write to file:\n{exc}")
            return

        logger.info("Settings saved to %s", self._config_path)
        self.saved.emit(str(self._config_path))
        QMessageBox.information(
            self, "Saved",
            f"Settings saved to:\n{self._config_path}\n\n"
            "Backend changes take effect on next app launch.\n"
            "Parameter changes (compliance, speed, averages) take effect after\n"
            "Disconnect → Connect All."
        )
