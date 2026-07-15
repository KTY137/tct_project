// MetricGrid — a grid arrangement of MetricTiles (kit_spec_v1.md §3: "lays
// out Tiles; owns no paint"). QML counterpart of gui/panel_kit.py::MetricGrid
// — pure layout, no Surface of its own (the spec's rung column is literally
// "(layout)"): each child MetricTile is its own Surface and paints itself.
//
// Children route to the internal Grid via the `tiles` default property; the
// Grid itself is declared through the explicit `data: [...]` list (not as a
// bare top-level child) so it can never be mis-routed into its own `.data`
// when a consumer instantiates `MetricGrid { MetricTile {...} ... }`.
import QtQuick
import Tct

Item {
    id: root
    objectName: "kitMetricGrid"

    property int columns: 4

    default property alias tiles: grid.data

    implicitWidth: grid.implicitWidth
    implicitHeight: grid.implicitHeight

    data: [
        Grid {
            id: grid
            objectName: "kitMetricGridInner"
            anchors.fill: parent
            columns: root.columns
            columnSpacing: Theme.spaceSm
            rowSpacing: Theme.spaceSm
        }
    ]
}
