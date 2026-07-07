"""
TCT Settings Window.

Multi-tab dialog for editing configs/devices.yaml without leaving the app.

Per-device Quick Settings tabs (Oscilloscope / Motor Stage / Bias Supply /
Waveform Gen / Camera / Data Saving)
    Each tab holds a structured form covering that device's most important
    options.  Backend dropdowns show/hide the relevant sub-fields
    automatically.  Changing any field immediately regenerates the YAML text
    in the Full YAML tab.

Full YAML tab
    Plain-text editor with YAML syntax highlighting and live parse validation.
    Editing here is the source of truth — the device tabs reflect it when
    you switch back to one of them.

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
from PySide6.QtCore import Qt, QObject, QRegularExpression, QSettings, QThread, Signal
from PySide6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget, QApplication,
)

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "configs" / "devices.yaml"
from gui.panel_kit import Card, form_row, panel_header
from gui.status_widgets import StatusChip, flash_button, set_button_busy, set_button_icon
from gui.style import DARK, FONT_XS, LIGHT, SPACE_SM


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


def _scan_visa_resources() -> list[str]:
    """Blocking VISA enumeration — only ever called off the GUI thread, via
    ``_VisaScanManager``.  May raise (``DeviceError`` / ``ImportError``); the
    caller (``_ScanWorker``) turns that into an error string for the chip /
    message box instead of letting it kill the worker thread silently."""
    from devices.waveform_generator import list_visa_resources
    return list_visa_resources()


def _scan_lan_instruments() -> list[str]:
    """Blocking mDNS/LXI discovery (~2.5 s) — only ever called off the GUI
    thread, via ``_VisaScanManager``.  An empty result is the expected
    managed-switch reality (mDNS multicast frequently dropped), not a
    failure — see ``devices.waveform_generator.discover_lan_instruments``."""
    from devices.waveform_generator import discover_lan_instruments
    return discover_lan_instruments()


# Durable, process-lifetime registry keeping every in-flight _ScanWorker
# alive.  A worker cannot have a Qt parent (QObject.moveToThread() refuses
# to move an object that has one), so its Python-side reference is the only
# thing keeping the underlying C++ object alive; without this, a worker
# built and moveToThread()'d inside _VisaScanManager._start() is a purely
# local variable that CPython garbage-collects the instant _start() returns
# — typically before the freshly spawned OS thread has even been scheduled
# — silently dropping the started -> run connection (Qt auto-disconnects a
# connection whose receiver was destroyed), so the scan simply never runs.
# Registering here, independent of any _VisaScanManager/SettingsWindow
# instance, is what lets a worker survive its own manager being torn down
# mid-scan (matching the QApplication-parented QThread in _start()).
_ACTIVE_SCAN_WORKERS: set["_ScanWorker"] = set()


class _ScanWorker(QObject):
    """Runs one blocking discovery callable (VISA list / LAN mDNS browse) on
    a dedicated QThread and reports back via a signal — never touches any
    widget itself (see ``_VisaScanManager``)."""

    done = Signal(list, str)   # (resources, error) — error is "" on success

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn
        _ACTIVE_SCAN_WORKERS.add(self)

    def run(self) -> None:
        try:
            self.done.emit(list(self._fn()), "")
        except Exception as exc:
            self.done.emit([], str(exc))
        finally:
            _ACTIVE_SCAN_WORKERS.discard(self)


class _VisaScanManager(QObject):
    """Owns every off-GUI-thread VISA/LAN discovery for one Settings dialog.

    Root cause of the freeze this replaces: each ``_VisaPicker`` used to call
    ``list_visa_resources()`` *synchronously in ``__init__``*, and
    ``_rebuild_quick_settings`` builds four pickers (scope / keithley / iseg /
    wfg) — every dialog open *and* every "switch back from Full YAML" tab
    change fired four blocking VISA scans on the GUI thread.  On a real bench
    with a slow/absent VISA backend that freezes the whole dialog.

    Fix: the resource list is scanned **once**, off-thread, and cached here;
    every picker reads the cache via ``resources_ready`` instead of scanning
    itself.  A manual rescan (🔄) re-runs the scan off-thread and refreshes
    every currently-open picker together.  Per-picker LAN (mDNS) discovery
    ("🔎 LAN") is user-initiated so it is not cached, but it is still routed
    through here purely so its worker thread's lifetime is tracked in
    ``self._threads`` and can be quit/joined from ``shutdown()`` — including
    a scan still in flight when the requesting picker has since been torn
    down (a tab-switch rebuild replaces every picker) or the dialog itself is
    closing.

    Completion is always delivered to a **bound method of a QObject living on
    the GUI thread** (the manager itself for the VISA cache; the requesting
    picker for a LAN scan) — never a bare closure.  That distinction matters:
    PySide only auto-queues a cross-thread signal to the GUI thread when the
    connected slot is a bound method of a QObject Qt can ask "which thread do
    you live on?"; connecting to a plain function/lambda runs it inline, on
    the *emitting* (worker) thread, which would silently reintroduce
    off-thread widget access.
    """

    resources_ready = Signal(list, str)   # (resources, error) — VISA cache updated

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cache: list[str] | None = None   # None == never scanned yet
        self._visa_busy = False
        self._threads: set[QThread] = set()

    # -- shared VISA resource cache ------------------------------------ #
    def ensure_scanned(self) -> None:
        """Kick off the shared scan iff there is no cache yet and none is
        already running.  Idempotent — building N pickers in one
        ``_rebuild_quick_settings`` call costs exactly one scan."""
        if self.cache is not None or self._visa_busy:
            return
        self.rescan()

    def rescan(self) -> None:
        if self._visa_busy:
            return
        self._visa_busy = True
        self._start(_scan_visa_resources, self._on_visa_done)

    def _on_visa_done(self, result: list, err: str) -> None:
        self._visa_busy = False
        self.cache = result
        self.resources_ready.emit(result, err)

    # -- per-picker LAN discovery --------------------------------------- #
    def request_lan_scan(self, on_done) -> None:
        """*on_done(resources, error)* must be a bound method of a QObject
        living on the GUI thread (see class docstring)."""
        self._start(_scan_lan_instruments, on_done)

    # -- shared worker-thread plumbing ------------------------------------ #
    def _start(self, fn, on_done) -> None:
        # Deliberately parented to the QApplication instance, NOT to self —
        # this manager (and its owning SettingsWindow) can be garbage
        # collected mid-scan (e.g. a dialog constructed with no Qt parent
        # and never explicitly closed).  A QThread whose Qt parent is
        # cascade-deleted while it is still running is a hard Qt6 crash
        # ("QThread: Destroyed while thread is still running"); parenting to
        # the long-lived QApplication instead means the thread survives its
        # manager's teardown and finishes cleanly via its own
        # done -> quit/deleteLater chain below, regardless of what happens
        # to this manager or the dialog that created it.
        thread = QThread(QApplication.instance())
        worker = _ScanWorker(fn)
        worker.moveToThread(thread)
        self._threads.add(thread)
        thread.started.connect(worker.run)
        worker.done.connect(on_done)
        # Canonical Qt "worker object" teardown: the worker asks its own
        # thread to stop and schedules its own deletion (both queued/direct
        # appropriately since each receiver lives in its own home thread);
        # the QThread controller deletes itself once fully stopped.
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_thread_finished(self) -> None:
        thread = self.sender()
        self._threads.discard(thread)

    def shutdown(self) -> None:
        """Quit + join every in-flight scan thread.  Called from
        ``SettingsWindow.closeEvent`` (and ``QApplication.aboutToQuit`` — see
        ``SettingsWindow.__init__``) so a scan started just before the
        dialog/app closes can never leak a thread or crash into a deleted
        widget.  Best-effort like the rest of the codebase's thread teardown
        (``DeviceManagerWindow.shutdown``, ``tct_gui._teardown_panels``): a
        genuinely stuck blocking call (dead VISA backend, no-timeout mDNS
        browse) cannot be force-killed safely, so ``wait()`` has a bound —
        3 s comfortably covers the documented ~2.5 s LAN-discovery window."""
        for thread in list(self._threads):
            thread.quit()
            thread.wait(3000)
        self._threads.clear()


class _VisaPicker(QWidget):
    """Editable dropdown of discovered VISA resources + a 🔄 scan button.

    Lets the user pick an instrument address instead of typing it; manual
    entry / paste still works (the combo is editable).  VISA discovery is
    shared across every picker in the dialog through a ``_VisaScanManager``
    (see above) — a picker never scans on its own, so it is fully usable
    (editable, manual entry works) the instant it appears, even while the
    shared scan is still running or a real bench VISA backend is slow/absent.
    """
    changed = Signal()

    def __init__(self, current: str = "",
                 scan_mgr: "_VisaScanManager | None" = None) -> None:
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setMinimumWidth(260)
        self._combo.setToolTip("Pick a discovered VISA instrument, or type / paste "
                               "an address.  Click 🔄 to (re)scan.")
        self._btn_scan = QToolButton()
        self._btn_scan.setText("🔄")
        self._btn_scan.setToolTip("Scan for connected VISA instruments (needs NI-VISA)")
        self._btn_scan.clicked.connect(self._refresh)
        self._btn_lan = QToolButton()
        self._btn_lan.setText("🔎 LAN")
        self._btn_lan.setToolTip("Auto-discover LAN/LXI instruments (mDNS), or enter an IP")
        self._btn_lan.clicked.connect(self._add_lan)
        self._chip_scan = StatusChip("Scan ready", "neutral", min_width=82)
        h.addWidget(self._combo, 1)
        h.addWidget(self._btn_scan)
        h.addWidget(self._btn_lan)
        h.addWidget(self._chip_scan)

        self._scan_mgr = scan_mgr
        self._pending_rescan_notice = False
        if scan_mgr is not None:
            scan_mgr.resources_ready.connect(self._on_scan_results)
            cached = scan_mgr.cache
            if cached is not None:
                self._fill(current, cached)
                self._chip_scan.set_status(f"{len(cached)} found" if cached else "No VISA",
                                           "good" if cached else "warn")
            else:
                # No cache yet (first Settings open this session) — fill with
                # just the saved value so the picker is usable immediately;
                # the shared background scan kicked off below lands via
                # _on_scan_results whenever it completes.
                self._fill(current, [])
                self._chip_scan.set_status("Scanning...", "busy")
            scan_mgr.ensure_scanned()
        else:
            # No manager wired — shouldn't happen in the running app (every
            # call site passes one), but keep the picker usable regardless.
            self._fill(current, [])
            self._chip_scan.set_status("No VISA", "warn")

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
        if self._scan_mgr is None:
            self._prompt_manual_lan_address()
            return
        self._btn_lan.setEnabled(False)
        self._chip_scan.set_status("LAN scan...", "busy")
        self._scan_mgr.request_lan_scan(self._on_lan_result)

    def _on_lan_result(self, found: list[str], err: str) -> None:
        self._btn_lan.setEnabled(True)
        if err:
            logger.info("LAN auto-discovery unavailable: %s", err)
        if found:
            for addr in found:
                if self._combo.findText(addr) < 0:
                    self._combo.addItem(addr)
            self._combo.setCurrentText(found[0])
            self.changed.emit()
            self._chip_scan.set_status(f"{len(found)} found", "good")
            self._combo.showPopup()          # let the user pick among discovered
            return
        # Empty is the expected managed-switch reality (mDNS multicast often
        # dropped by IGMP-snooping), not a failure — say so, then offer
        # manual entry instead of implying something went wrong.
        self._chip_scan.set_status("None on LAN", "warn")
        self._prompt_manual_lan_address()

    def _prompt_manual_lan_address(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        ip, ok = QInputDialog.getText(
            self.window(), "Add LAN instrument",
            "No instruments found on this network segment (mDNS discovery "
            "is often blocked by managed switches — this doesn't mean the "
            "instrument isn't reachable).\nEnter its IP or hostname:")
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

    def _fill(self, current: str, found: list[str]) -> None:
        items = list(found)
        if current and not self._looks_placeholder(current) and current not in items:
            items.append(current)
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItems(items)
        # No auto-select — even when *current* is a placeholder.  The shared
        # VISA scan returns every resource the backend can see, not just the
        # one that belongs to *this* device/section, so picking found[0]
        # here could silently hand e.g. the waveform-gen picker the scope's
        # USB address (and mark the config dirty from a choice the user
        # never made).  Leave the saved/placeholder text as-is; discovered
        # addresses are all in the dropdown for the user to pick explicitly.
        self._combo.setCurrentText(current)
        self._combo.blockSignals(False)

    def _on_scan_results(self, found: list, err: str) -> None:
        """The shared cache scan landed (initial scan or a 🔄 rescan started
        by *any* picker) — refresh this picker's dropdown without disturbing
        whatever the user currently has typed/selected (see _fill: no
        auto-select, so this never marks the config dirty on its own)."""
        keep = self._combo.currentText()
        self._fill(keep, found)
        if found:
            self._chip_scan.set_status(f"{len(found)} found", "good")
        else:
            self._chip_scan.set_status("No VISA", "warn")
        if self._pending_rescan_notice:
            # Only the picker whose 🔄 button the user actually clicked pops
            # a popup/message — a shared rescan silently refreshes every
            # other open picker's dropdown in the background.
            self._pending_rescan_notice = False
            if found:
                self._combo.showPopup()
            else:
                QMessageBox.information(
                    self.window(), "VISA scan",
                    err or "No VISA instruments found.\n"
                    "Check the USB connection and that NI-VISA is installed.")

    def _refresh(self) -> None:
        if self._scan_mgr is None:
            return
        self._pending_rescan_notice = True
        self._chip_scan.set_status("Scanning...", "busy")
        self._scan_mgr.rescan()

    def text(self) -> str:
        return self._normalize(self._combo.currentText())


# ─────────────────────────────────────────────────────────────────────
# Theme-token styling helpers (gui.style) — the Card-ified section pattern
# ─────────────────────────────────────────────────────────────────────

def _palette(theme_mode: str) -> dict:
    return DARK if theme_mode == "dark" else LIGHT


def _hint_label(text: str, theme_mode: str) -> QLabel:
    """Muted informational note — theme-token styled.

    Replaces the hardcoded ``color:#888; font-size:11px;`` idiom that was
    duplicated across every per-device Quick-Settings section.
    """
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {_palette(theme_mode)['muted']}; font-size: {FONT_XS}px;")
    return lbl


def _accent_rail(card: Card, theme_mode: str) -> None:
    """Tint *card*'s left edge with the shared UI accent colour.

    ``panel_kit.Card.set_rail()`` only covers the ``AXIS_RAIL`` tokens
    (bias / x / y / z / laser / delay / hazard) — there is no neutral
    "accent" rail for a Card that isn't tied to a scan parameter axis (the
    Oscilloscope Quick-Settings card is a device-identity accent, not a
    scan axis). This mirrors ``Card.set_rail()``'s exact CSS shape with the
    shared accent token instead of an axis colour, without touching
    panel_kit.py — see the gap noted in the rollout report.
    """
    p = _palette(theme_mode)
    card.setProperty("railAxis", "accent")
    card.setStyleSheet(
        f'QFrame#cardPane[railAxis="accent"] {{ border-left: 3px solid {p["accent"]}; }}'
    )


# ─────────────────────────────────────────────────────────────────────
# Quick-settings sections
# ─────────────────────────────────────────────────────────────────────

class _OscilloscopeSection(QWidget):
    changed = Signal()

    def __init__(self, cfg: dict, theme_mode: str = "light",
                 scan_mgr: "_VisaScanManager | None" = None) -> None:
        super().__init__()
        self._theme_mode = theme_mode
        self._build(cfg, scan_mgr)

    def _build(self, cfg: dict, scan_mgr: "_VisaScanManager | None") -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = Card("Oscilloscope", "VISA / DRS4 backend")
        _accent_rail(card, self._theme_mode)
        outer.addWidget(card)
        form = QFormLayout()

        self._backend = _combo(["visa", "drs4"], cfg.get("backend", "visa"))
        form.addRow("Backend:", self._backend)

        # ── VISA fields ───────────────────────────────────────────────
        self._visa_frame = QWidget()
        vf = QFormLayout(self._visa_frame)
        vf.setContentsMargins(0, 0, 0, 0)
        self._visa_addr   = _VisaPicker(str(cfg.get("visa_address", "")), scan_mgr)
        self._vendor      = _combo(["lecroy", "tektronix", "keysight", "rigol"],
                                    cfg.get("vendor", "lecroy"))
        self._timeout_ms  = _ispin(cfg.get("timeout_ms", 10000), 100, 120000)
        vf.addRow("VISA address:", self._visa_addr)
        vf.addRow("Vendor:", self._vendor)
        vf.addRow("Timeout (ms):", self._timeout_ms)
        vf.addRow(_hint_label("Trigger (source / level / slope) is set in the "
                              "Oscilloscope panel → Trigger Settings.", self._theme_mode))
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
        card.add_layout(form)

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


class _MotorSection(QWidget):
    changed = Signal()

    def __init__(self, cfg: dict, theme_mode: str = "light") -> None:
        super().__init__()
        self._theme_mode = theme_mode
        self._build(cfg)

    def _build(self, cfg: dict) -> None:
        from devices.printer_presets import PRINTER_PRESETS, get_preset

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = Card("Motor Stage", "printer preset · backend · travel limits")
        outer.addWidget(card)
        form = QFormLayout()

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
        gf.addRow(form_row("X limits min / max (mm)", _pair(self._lim_xmin, self._lim_xmax),
                            axis="x", theme_mode=self._theme_mode))
        gf.addRow(form_row("Y limits min / max (mm)", _pair(self._lim_ymin, self._lim_ymax),
                            axis="y", theme_mode=self._theme_mode))
        gf.addRow(form_row("Z limits min / max (mm)", _pair(self._lim_zmin, self._lim_zmax),
                            axis="z", theme_mode=self._theme_mode))
        gf.addRow("Steps/mm X·Y·Z:", _triple(self._spm_x, self._spm_y, self._spm_z))
        gf.addRow("Microsteps (jumper):", self._microsteps)
        gf.addRow("Snap to detents:", self._snap_mode)
        gf.addRow("Push steps/mm on connect:", self._push_steps)
        gf.addRow(_hint_label(
            "A4988: 1/16 max via jumpers; current via Vref pot "
            "(I = Vref / 0.4 with R050) — not software-settable. "
            "Snap=full parks the motor on stable detents (~0.2 mm grid) "
            "to stop hunting/overheating.", self._theme_mode))
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
        card.add_layout(form)

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


class _BiasSection(QWidget):
    changed = Signal()

    def __init__(self, cfg: dict, theme_mode: str = "light",
                 scan_mgr: "_VisaScanManager | None" = None) -> None:
        super().__init__()
        self._theme_mode = theme_mode
        self._build(cfg, scan_mgr)

    def _build(self, cfg: dict, scan_mgr: "_VisaScanManager | None") -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = Card("Bias Supply", "connection · compliance")
        card.set_rail("bias", self._theme_mode)
        outer.addWidget(card)
        form = QFormLayout()
        self._backend = _combo(["simulated", "keithley", "e4control", "iseg"],
                                cfg.get("backend", "simulated"))
        form.addRow("Backend:", self._backend)

        # ── Keithley (VISA — USB / GPIB / LAN) ───────────────────────
        self._keithley_frame = QWidget()
        kf = QFormLayout(self._keithley_frame)
        kf.setContentsMargins(0, 0, 0, 0)
        self._k_visa = _VisaPicker(str(cfg.get("visa_address", "")), scan_mgr)
        kf.addRow("VISA address:", self._k_visa)
        kf.addRow(_hint_label(
            "USB, GPIB, or LAN via VISA (e.g. USB0::0x05e6::0x2410::...::INSTR)",
            self._theme_mode))
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
        self._iseg_visa = _VisaPicker(iseg_addr, scan_mgr)
        self._iseg_ch   = _ispin(cfg.get("channel", 0), 0, 15)
        self._iseg_ramp = _dspin(cfg.get("ramp_speed_V_s", 50.0), 0.1, 5000.0, 1)
        gf.addRow("VISA address:", self._iseg_visa)
        gf.addRow(_hint_label(
            "USB/serial (ASRL5::INSTR for COM5, or ASRL/dev/ttyUSB0::INSTR on Linux) "
            "or LAN socket (TCPIP0::192.168.1.30::10001::SOCKET). "
            "iseg USB appears as a virtual COM port (CDC/VCP), NOT as USB0::...",
            self._theme_mode))
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
        card.add_layout(form)

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


class _DataSavingSection(QWidget):
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

    def __init__(self, cfg: dict, theme_mode: str = "light") -> None:
        super().__init__()
        self._theme_mode = theme_mode
        self._build(cfg)

    def _build(self, cfg: dict) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = Card("Data / Saving", "output directory · saved dataset groups")
        outer.addWidget(card)
        form = QFormLayout()

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
        p = _palette(self._theme_mode)
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
                # Warn notes stay loud (crit token); informational notes read
                # muted — both theme-token, replacing the old hardcoded
                # "#c0392b"/"#888" pair.
                lbl.setStyleSheet(
                    f"color: {p['crit'] if warn else p['muted']}; font-size: {FONT_XS}px;"
                )
                row = QHBoxLayout()
                row.addWidget(cb); row.addStretch(); row.addWidget(lbl)
                cont = QWidget(); cont.setLayout(row)
                form.addRow(cont)
            else:
                form.addRow(cb)
        card.add_layout(form)

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


class _WaveformSection(QWidget):
    """Waveform generator (trigger / rep-rate source — Rigol DG4000, Tek, …)."""
    changed = Signal()

    def __init__(self, cfg: dict, theme_mode: str = "light",
                 scan_mgr: "_VisaScanManager | None" = None) -> None:
        super().__init__()
        self._theme_mode = theme_mode
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        # "delay" rail — matches LaserPanel's own Waveform Generator card
        # (gui/laser_panel.py): it drives the laser's trigger/rep-rate, the
        # classic edge-TCT delay axis.
        card = Card("Waveform Generator", "trigger / rep-rate source")
        card.set_rail("delay", theme_mode)
        outer.addWidget(card)
        form = QFormLayout()
        self._addr   = _VisaPicker(str(cfg.get("visa_address", "")), scan_mgr)
        self._vendor = _combo(["rigol", "tektronix", "keysight", "siglent", "generic"],
                              str(cfg.get("vendor", "rigol")))
        self._ch     = _ispin(cfg.get("output_channel", 1), 1, 4)
        self._sim    = _combo(["false", "true"],
                              "true" if cfg.get("simulation", True) else "false")
        form.addRow("VISA address:", self._addr)
        form.addRow("Vendor:", self._vendor)
        form.addRow("Output channel:", self._ch)
        form.addRow("Simulation:", self._sim)
        form.addRow(_hint_label("Frequency / pulse width / amplitude are live controls on "
                                "the Laser/Trigger panel.", theme_mode))
        card.add_layout(form)
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


class _CameraSection(QWidget):
    """FLIR Blackfly camera (beam / repeatability imaging)."""
    changed = Signal()

    def __init__(self, cfg: dict, theme_mode: str = "light") -> None:
        super().__init__()
        self._theme_mode = theme_mode
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = Card("Camera", "FLIR Blackfly — connection & acquisition")
        outer.addWidget(card)
        form = QFormLayout()
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
        card.add_layout(form)
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
        self._dirty = False
        self._base_tab_titles: dict[int, str] = {}
        # Shared, off-GUI-thread VISA/LAN discovery for every _VisaPicker in
        # this dialog (scope / keithley / iseg / wfg) — see _VisaScanManager.
        # Created before _build_ui()/_load_file() since _rebuild_quick_settings
        # (called from _load_file) needs it to construct the pickers.
        self._visa_scan_mgr = _VisaScanManager(self)
        # Safety net for the "whole app exits without this dialog's Close
        # button ever being clicked" path: tct_gui.py caches this dialog as a
        # Qt-parented child of the main window, and — per
        # tct_gui._teardown_panels's own docstring — "child-widget deletion
        # does not fire closeEvent", so a scan still in flight when the app
        # quits would otherwise never get joined before Qt's C++ parent-child
        # cascade destroys the still-running QThread (a hard crash in Qt6).
        # aboutToQuit fires while the event loop can still process events,
        # ahead of that cascade, so it is a reliable last-chance hook here —
        # entirely self-contained, no tct_gui.py change needed.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._visa_scan_mgr.shutdown)
        # Theme mode for the Quick-Settings Card rails (bias amber, x/y/z
        # limit rows, waveform-gen "delay") and the muted/danger chrome
        # labels below — same QSettings key main.py/tct_gui.py use, mirroring
        # MotorPanel/BiasPanel/ScopePanel. Not yet wired into
        # tct_gui._toggle_theme's live-refresh loop (tct_gui.py is out of
        # this module's scope) — see refresh_theme() for a caller-driven
        # re-tint path.
        self._theme_mode = str(QSettings("TCT", "TCTSetup").value("theme", "light"))
        self._build_ui()
        self._load_file()

    # ------------------------------------------------------------------ #
    # UI construction                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        root.addWidget(panel_header("TCT Control — Configuration", "Settings"))

        # ── File path label ───────────────────────────────────────────
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Config file:"))
        self._lbl_path = QLabel(str(self._config_path))
        path_row.addWidget(self._lbl_path, 1)
        root.addLayout(path_row)

        state_row = QHBoxLayout()
        self._chip_yaml = StatusChip("YAML unknown", "neutral")
        self._chip_dirty = StatusChip("Saved", "good")
        self._chip_sim = StatusChip("Simulation --", "neutral")
        self._chip_reconnect = StatusChip("No reconnect pending", "neutral")
        for chip in (self._chip_yaml, self._chip_dirty, self._chip_sim, self._chip_reconnect):
            state_row.addWidget(chip)
        state_row.addStretch(1)
        root.addLayout(state_row)

        # ── Tabs ──────────────────────────────────────────────────────
        self._tabs = QTabWidget()

        # One scrollable tab per device section, in place of the old single
        # "Quick Settings" column.  Widgets themselves are populated after
        # loading the file (need the parsed cfg) — see _rebuild_quick_settings.
        def _device_tab(title: str) -> QScrollArea:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            self._tabs.addTab(scroll, title)
            return scroll

        self._scope_scroll = _device_tab("Oscilloscope")
        self._motor_scroll = _device_tab("Motor Stage")
        self._bias_scroll  = _device_tab("Bias Supply")
        self._wfg_scroll   = _device_tab("Waveform Gen")
        self._cam_scroll   = _device_tab("Camera")
        self._data_scroll  = _device_tab("Data Saving")
        self._base_tab_titles = {
            i: self._tabs.tabText(i)
            for i in range(self._tabs.count())
        }

        self._scope_section:  _OscilloscopeSection | None = None
        self._motor_section:  _MotorSection | None = None
        self._wfg_section:    _WaveformSection | None = None
        self._cam_section:    _CameraSection | None = None
        self._bias_section:   _BiasSection | None = None
        self._data_section:   _DataSavingSection | None = None

        # Last tab: Full YAML — Card frame around the editor surface, header
        # gives the file its own title/subtitle (highlighter/parse-validation
        # plumbing below is untouched — only the surrounding chrome changed).
        yaml_widget = QWidget()
        yaml_layout = QVBoxLayout(yaml_widget)
        yaml_card = Card("devices.yaml", str(self._config_path))
        yaml_card.body.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        self._editor = QPlainTextEdit()
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.Monospace)
        self._editor.setFont(font)
        self._editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._highlighter = _YamlHighlighter(self._editor.document())
        self._parse_error_label = QLabel("")
        self._parse_error_label.setVisible(False)
        self._editor.textChanged.connect(self._on_yaml_changed)
        yaml_card.add_widget(self._editor)
        yaml_card.add_widget(self._parse_error_label)
        yaml_layout.addWidget(yaml_card)
        self._yaml_tab_index = self._tabs.addTab(yaml_widget, "Full YAML")
        self._base_tab_titles[self._yaml_tab_index] = "Full YAML"

        self._prev_tab_index = self._tabs.currentIndex()
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs)

        # ── Status bar / info ─────────────────────────────────────────
        self._info_label = QLabel(
            "Backend changes (e.g. visa → drs4) take effect on the next app launch.  "
            "Parameter changes (compliance, speed, averages) can be applied live via "
            "Disconnect → Save → Connect All."
        )
        self._info_label.setWordWrap(True)
        root.addWidget(self._info_label)
        self._restyle_chrome_tokens()

        # ── Buttons ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_reload = QPushButton("Reload from File")
        set_button_icon(self._btn_reload, "mdi.reload")
        self._btn_reload.clicked.connect(self._load_file)
        self._btn_save = QPushButton("Save")
        set_button_icon(self._btn_save, "mdi.content-save")
        self._btn_save.setDefault(True)
        self._btn_save.clicked.connect(self._save)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(self._btn_reload)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def closeEvent(self, event) -> None:
        """Hide rather than destroy — tct_gui.py caches this dialog and
        re-shows it on the next "Settings" click (mirrors
        DeviceManagerWindow.closeEvent).  Joins any in-flight VISA/LAN scan
        thread first so a scan started just before Close can never fire into
        a hidden/rebuilt widget or leak a thread."""
        self._visa_scan_mgr.shutdown()
        event.ignore()
        self.hide()

    def _restyle_chrome_tokens(self) -> None:
        """Re-resolve the dialog-level muted/danger label colours from the
        current theme (the "Config file:" path label, the bottom info note,
        and the YAML parse-error banner) — theme-token styled instead of the
        old hardcoded greys/red, mirroring the per-instance colour pattern
        ``ScopePanel._restyle_theme_tokens`` / ``BiasPanel`` use. The parse-
        error label keeps reading the loud "crit" token (danger labels stay
        loud)."""
        p = _palette(self._theme_mode)
        self._lbl_path.setStyleSheet(f"color: {p['muted']}; font-style: italic;")
        self._info_label.setStyleSheet(f"color: {p['muted']}; font-size: {FONT_XS}px;")
        self._parse_error_label.setStyleSheet(f"color: {p['crit']}; font-weight: bold;")

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve theme-token colours after a light/dark switch — the
        Quick-Settings section Cards are rebuilt (cheap: they are already
        torn down/rebuilt on every load/tab-switch-back via
        ``_rebuild_quick_settings``) so their axis rails re-resolve, and the
        dialog chrome labels are restyled directly.

        Not currently called by ``tct_gui._toggle_theme`` — wiring the main
        window's live theme-refresh loop is outside this module's scope
        (``tct_gui.py``); until that's wired, the rails resolve once from
        QSettings at dialog construction. Provided so a caller can opt in.
        """
        if mode:
            self._theme_mode = str(mode)
        self._restyle_chrome_tokens()
        text = self._editor.toPlainText()
        try:
            cfg = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            return
        self._rebuild_quick_settings(cfg)

    # ------------------------------------------------------------------ #
    # Loading                                                             #
    # ------------------------------------------------------------------ #

    def _set_dirty(self, dirty: bool, *, reconnect_needed: bool = False) -> None:
        self._dirty = bool(dirty)
        if self._dirty:
            self._chip_dirty.set_status("Unsaved", "warn")
            self._chip_reconnect.set_status("Reconnect after save", "warn")
        else:
            self._chip_dirty.set_status("Saved", "good")
            if reconnect_needed:
                self._chip_reconnect.set_status("Reconnect needed", "warn")
            else:
                self._chip_reconnect.set_status("No reconnect pending", "neutral")

    def _set_yaml_valid(self, valid: bool, text: str | None = None) -> None:
        self._chip_yaml.set_status(text or ("Valid YAML" if valid else "Invalid YAML"),
                                   "good" if valid else "crit")
        self._set_tab_badge(self._yaml_tab_index, "invalid" if not valid else None)

    def _set_tab_badge(self, index: int, badge: str | None) -> None:
        if index < 0:
            return
        base = self._base_tab_titles.get(index, self._tabs.tabText(index).rstrip(" *!"))
        suffix = {"dirty": " *", "invalid": " !"}.get(str(badge), "")
        self._tabs.setTabText(index, base + suffix)

    def _update_sim_chip(self, cfg: dict) -> None:
        sim_count = 0
        for value in cfg.values():
            if isinstance(value, dict) and bool(value.get("simulation", False)):
                sim_count += 1
        if sim_count:
            self._chip_sim.set_status(f"Simulation {sim_count}", "simulated")
        else:
            self._chip_sim.set_status("Real config", "neutral")

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
        self._editor.setStyleSheet("")
        self._set_yaml_valid(True)
        self._set_dirty(False, reconnect_needed=False)
        for idx in range(self._tabs.count()):
            self._set_tab_badge(idx, None)
        self._update_sim_chip(cfg)
        self._rebuild_quick_settings(cfg)

    def _rebuild_quick_settings(self, cfg: dict) -> None:
        """Tear down and recreate the per-device section widgets.

        Called on load AND every "switch back from Full YAML" tab change —
        the four VISA pickers built here (scope / keithley / iseg / wfg) all
        share ``self._visa_scan_mgr``, so this never re-scans: the manager's
        cache (populated once, off-thread) is reused every time.
        """
        tm = self._theme_mode
        mgr = self._visa_scan_mgr
        self._scope_section = _OscilloscopeSection(cfg.get("oscilloscope", {}), tm, mgr)
        self._motor_section = _MotorSection(cfg.get("motor_stage", {}), tm)
        self._wfg_section   = _WaveformSection(cfg.get("waveform_generator", {}), tm, mgr)
        self._cam_section   = _CameraSection(cfg.get("camera", {}), tm)
        self._bias_section  = _BiasSection(cfg.get("bias_supply", {}), tm, mgr)
        self._data_section  = _DataSavingSection(cfg.get("output", {}), tm)

        # QScrollArea.setWidget() takes ownership of the new widget and
        # deletes whatever widget it previously held — no manual teardown
        # of the old sections needed here.
        self._scope_scroll.setWidget(self._scope_section)
        self._motor_scroll.setWidget(self._motor_section)
        self._bias_scroll.setWidget(self._bias_section)
        self._wfg_scroll.setWidget(self._wfg_section)
        self._cam_scroll.setWidget(self._cam_section)
        self._data_scroll.setWidget(self._data_section)

        for sec in (self._scope_section, self._motor_section, self._wfg_section,
                    self._cam_section, self._bias_section, self._data_section):
            sec.changed.connect(self._on_quick_settings_changed)

    # ------------------------------------------------------------------ #
    # Tab switching                                                       #
    # ------------------------------------------------------------------ #

    def _on_tab_changed(self, index: int) -> None:
        prev_index = self._prev_tab_index
        self._prev_tab_index = index
        if index != self._yaml_tab_index and prev_index == self._yaml_tab_index:
            # Coming back from Full YAML to a device tab — parse the YAML
            # and rebuild the section widgets so they reflect manual edits.
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
        self._set_yaml_valid(True)
        self._set_dirty(True)
        self._update_sim_chip(cfg)
        self._set_tab_badge(self._tabs.currentIndex(), "dirty")

    # ------------------------------------------------------------------ #
    # YAML → parse validation                                            #
    # ------------------------------------------------------------------ #

    def _on_yaml_changed(self) -> None:
        if self._suppress_yaml_update:
            return
        text = self._editor.toPlainText()
        try:
            cfg = yaml.safe_load(text) or {}
            self._parse_error_label.setVisible(False)
            self._editor.setStyleSheet("")
            self._set_yaml_valid(True)
            self._set_dirty(True)
            self._update_sim_chip(cfg)
        except yaml.YAMLError as exc:
            self._show_parse_error(str(exc))

    def _show_parse_error(self, msg: str) -> None:
        self._parse_error_label.setText(f"YAML parse error: {msg}")
        self._parse_error_label.setVisible(True)
        self._editor.setStyleSheet("border: 2px solid #c0392b;")
        self._set_yaml_valid(False)
        self._set_dirty(True)

    # ------------------------------------------------------------------ #
    # Save                                                                #
    # ------------------------------------------------------------------ #

    def _save(self) -> None:
        text = self._editor.toPlainText()
        set_button_busy(self._btn_save, True, "Saving...")
        try:
            cfg = yaml.safe_load(text) or {}   # validate before writing
        except yaml.YAMLError as exc:
            set_button_busy(self._btn_save, False)
            self._show_parse_error(str(exc))
            QMessageBox.critical(self, "Save Failed",
                                 f"Cannot save: YAML is not valid.\n\n{exc}")
            return

        try:
            self._config_path.write_text(text, encoding="utf-8")
        except OSError as exc:
            set_button_busy(self._btn_save, False)
            QMessageBox.critical(self, "Save Failed",
                                 f"Could not write to file:\n{exc}")
            return

        set_button_busy(self._btn_save, False)
        flash_button(self._btn_save, "good", "Saved")
        self._set_yaml_valid(True)
        self._set_dirty(False, reconnect_needed=True)
        self._update_sim_chip(cfg)
        for idx in range(self._tabs.count()):
            self._set_tab_badge(idx, None)
        logger.info("Settings saved to %s", self._config_path)
        self.saved.emit(str(self._config_path))
        QMessageBox.information(
            self, "Saved",
            f"Settings saved to:\n{self._config_path}\n\n"
            "Backend changes take effect on next app launch.\n"
            "Parameter changes (compliance, speed, averages) take effect after\n"
            "Disconnect → Connect All."
        )
