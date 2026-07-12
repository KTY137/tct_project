// ScanStatusStrip — the strip-hierarchy row from cockpit_design_system.md §5:
// "State and HV are the two high-salience tiles; Progress·ETA merged;
// Position compact; last-charge lives at the waveform, not the strip."
// Mirrors the read-only `runState` facade (gui/run_state_viewmodel.py::
// RunStateViewModel) for run/scan state, and the `shell` rail bridge
// (gui/qml_shell.py::_ShellBridge, already a QML context property — see
// Shell.qml's own use of `shell.hvText`/`shell.hvState`) for the HV tile's
// measured-voltage readout — reusing the SAME cached bias-strip value the
// classic ribbon's HV chip shows (`_collect_shell_state()["hv"]`), never a
// new poll.
//
// VIEW ONLY, per the 3-layer law and hardware safety rule 2: this file binds
// `runState.*`/`shell.*` and `Theme.*` — it holds no logic/policy beyond pure
// presentation math (the flex-ratio tile widths below), starts no timer, and
// calls no run-control/device method (RunStateViewModel structurally exposes
// none; `shell`'s HV surface is a read-only cached mirror — see both files'
// module docstrings). The composition root's shared 1 Hz `_light_timer`
// (plus the ScanCoordinator signal feed) is what actually updates these
// sources; this file only re-renders when their NOTIFY-able properties change.
//
// `runState`/`shell` are each guarded with `x ? ... : fallback` rather than
// assumed non-null: in production both are always set once the QML chrome is
// built (see tct_gui.py), but `runState` is documented as possibly `None` for
// a future caller (build_qml_chrome's own docstring), and this file is also
// loaded standalone (tests/test_qml_scan_status.py, a bare QQmlEngine with
// only the properties a given test sets) — which becomes QML `null`, not a
// missing identifier. The guards keep both cases rendering a fallback instead
// of throwing a null-dereference — a presentation fallback, not policy.
import QtQuick
import Tct

// A plain Row (not a Flow): tile widths are computed below as an explicit
// fraction of the strip's own width (the "State 1.5fr / HV 1.1fr /
// Progress·ETA 1fr / Position 0.9fr" ratio from §5), so the row's total
// width always exactly matches its container — there is no overflow case a
// wrap would need to catch (Shell.qml's rail-compression contract still
// holds: the pill tab shelf remains the only Flickable in the chrome).
Row {
    id: root
    objectName: "scanStatusStrip"
    spacing: Theme.spaceSm

    // A run is in progress (running or paused); tiles dim (MetricTile's own
    // `stale` opacity Behavior) when it is not.
    readonly property bool _active: !!(runState && runState.active)

    // -- flex-ratio tile widths (§5's "State 1.5fr / HV 1.1fr / Progress·ETA
    // 1fr / Position 0.9fr") -------------------------------------------- #
    readonly property real _stateUnits: 1.5
    readonly property real _hvUnits: 1.1
    readonly property real _progressUnits: 1.0
    readonly property real _posUnits: 0.9
    readonly property real _totalUnits: _stateUnits + _hvUnits + _progressUnits + _posUnits
    readonly property real _gapWidth: spacing * 3
    readonly property real _unitWidth: width > 0
        ? Math.max(0, width - _gapWidth) / _totalUnits
        : 0

    // -- HV tile derivation (from the cached `shell` rail bridge) -------- #
    // shell.hvText already carries its own "HV " prefix (e.g. "HV +12.3 V" /
    // "HV --" with no reading) — the same string the classic ribbon's HV
    // chip shows; trim it here for display, matching Shell.qml's StatChip
    // convention (display-only shortening, not a new value).
    function _hvValue() {
        if (!shell) return "--"
        var t = shell.hvText
        return t.indexOf("HV ") === 0 ? t.substring(3) : t
    }
    function _hvCaption() {
        if (!shell) return "not connected"
        if (shell.hvState === "armed") return "output on"
        if (shell.hvState === "good") return "output off"
        return "not connected"
    }
    readonly property bool _hvStale: !shell || shell.hvState === "neutral"

    MetricTile {
        objectName: "tileState"
        title: "State"
        value: runState ? runState.stateName : "--"
        accent: Theme.accent          // the accented, headline tile
        stale: !root._active
        width: root._unitWidth * root._stateUnits
    }

    MetricTile {
        objectName: "tileHv"
        title: "HV · measured"
        value: root._hvValue()
        caption: root._hvCaption()
        accent: (shell && shell.hvState === "armed") ? Theme.armed : Theme.muted
        stale: root._hvStale
        width: root._unitWidth * root._hvUnits
    }

    MetricTile {
        objectName: "tileProgress"
        title: "Progress · ETA"
        value: runState ? (runState.done + "/" + runState.total + " · " + runState.etaText) : "--/-- · --"
        caption: runState ? runState.pointText : ""
        meterFraction: runState ? runState.progressFraction : -1
        stale: !root._active
        width: root._unitWidth * root._progressUnits
    }

    MetricTile {
        objectName: "tilePosition"
        title: "Position"
        value: runState ? runState.pointText : "--"
        compact: true
        stale: !root._active
        width: root._unitWidth * root._posUnits
    }
}
