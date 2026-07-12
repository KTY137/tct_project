// ScanStatusStrip — a row of MetricTiles mirroring the read-only `runState`
// facade (gui/run_state_viewmodel.py::RunStateViewModel, already exposed as
// the "runState" QML context property by gui/qml_shell.py::build_qml_chrome
// in BOTH the classic and QML shells — see tct_gui.py's `_run_vm` wiring).
//
// VIEW ONLY, per the 3-layer law and hardware safety rule 2: this file binds
// `runState.*` and `Theme.*` — it holds no logic/policy, starts no timer, and
// calls no run-control method (RunStateViewModel structurally exposes none;
// see its module docstring). The composition root's shared 1 Hz `_light_timer`
// (plus the ScanCoordinator signal feed) is what actually updates `runState`;
// this file only re-renders when its NOTIFY-able properties change.
//
// `runState` is guarded with `runState ? ... : "--"` rather than assumed
// non-null: in production it is always set to the real view-model once the
// QML chrome is built (see tct_gui.py), but `build_qml_chrome`'s own
// docstring documents `run_vm` as possibly `None` for a future caller —
// which becomes QML `null`, not a missing identifier. The guard keeps that
// case (and a bare standalone load, e.g. a future preview tool) rendering
// "--" instead of throwing a null-dereference — a presentation fallback, not
// run-state policy.
import QtQuick
import Tct

// No Flickable here (Shell.qml's rail-compression contract: exactly one
// Flickable — the pill tab shelf — may exist in the chrome); a Flow just
// wraps tiles onto a second line if the window narrows, never scrolls.
Flow {
    id: root
    objectName: "scanStatusStrip"
    spacing: Theme.spaceSm

    // A run is in progress (running or paused); tiles dim (MetricTile's own
    // `stale` opacity Behavior) when it is not.
    readonly property bool _active: !!(runState && runState.active)

    MetricTile {
        objectName: "tileState"
        title: "State"
        value: runState ? runState.stateName : "--"
        accent: Theme.accent          // the accented, headline tile
        stale: !root._active
    }

    MetricTile {
        objectName: "tileProgress"
        title: "Progress"
        value: runState ? (runState.done + "/" + runState.total) : "--/--"
        caption: runState ? runState.pointText : ""
        stale: !root._active
    }

    MetricTile {
        objectName: "tileEta"
        title: "ETA"
        value: runState ? runState.etaText : "--"
        stale: !root._active
    }

    MetricTile {
        objectName: "tileElapsed"
        title: "Elapsed"
        value: runState ? runState.elapsedText : "--"
        stale: !root._active
    }

    MetricTile {
        objectName: "tileScan"
        title: "Scan"
        value: runState ? runState.scanType : "--"
        stale: !root._active
    }
}
