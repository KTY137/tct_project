// MetricTile — a single tokenized metric readout tile (view only).
//
// QML analogue of gui/panel_kit.py's MetricTile/readout_cell
// (cockpit_style_overhaul.md §2: "MetricTile(label, value, state) ... built
// on existing readout_cell"). This file is the QML-land counterpart used by
// the Scan Viewer slice's ScanStatusStrip; it holds NO logic of its own —
// every value is a property the caller binds (see ScanStatusStrip.qml
// binding runState.*). No timers, no state derivation, no run-control calls.
//
// Started from docs/design/drafts/qml/MetricTile.draft.qml (Ollama draft,
// Adam-reviewed). Fixes applied vs that draft:
//   1. ONE declarative `border.color` binding (hover-lighten) — the draft
//      declared `border.color` twice, a QML syntax error.
//   2. The inner layout uses `anchors.fill` + `anchors.margins` — the draft's
//      `Column { margins: 8 }` is not a real Column property.
//   3. 150ms Behaviors on opacity + color are restored (the draft dropped
//      them).
//   4. Real Theme import (`import Tct`, gui/qml_theme.py, fed from
//      gui/style.py) replaces the draft's placeholder `import TCT.Theme 1.0`.
//   5. The accent bar is inset top/bottom (not full `root.height`) and given
//      a small radius so it doesn't visually collide with the tile's own
//      corner radius.
import QtQuick
import Tct

Rectangle {
    id: root

    // -- property surface (per the task brief; matches the draft's names) - #
    property string title: ""
    property string value: ""
    property string unit: ""
    property string caption: ""
    property color accent: Theme.muted
    property bool stale: false
    property bool compact: false

    objectName: "metricTile"
    implicitWidth: 180
    implicitHeight: compact ? 64 : 96
    radius: Theme.radiusMd
    color: Theme.panel
    border.width: 1
    // Declarative hover-lighten border — a HoverHandler-driven binding, never
    // an imperative onEntered/onExited colour assignment.
    border.color: hoverHandler.hovered ? Theme.hairlineStrong : Theme.hairline
    opacity: stale ? 0.6 : 1.0

    Behavior on border.color { ColorAnimation { duration: 150 } }
    Behavior on opacity { NumberAnimation { duration: 150 } }

    HoverHandler { id: hoverHandler }

    // Accent bar, inset from the top/bottom edges so the tile's corner
    // radius stays clean (draft defect #5).
    Rectangle {
        width: 3
        radius: 1.5
        color: root.accent
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.topMargin: 6
        anchors.bottomMargin: 6
        anchors.leftMargin: 2

        Behavior on color { ColorAnimation { duration: 150 } }
    }

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spaceSm
        anchors.leftMargin: Theme.spaceSm + 6   // clear the accent bar
        spacing: 4

        Text {
            objectName: "tileTitle"
            text: root.title
            font.pixelSize: Theme.fontXs
            font.weight: Font.DemiBold
            // repo convention (ReadoutCell/MetricTile title.upper()) rather
            // than the draft's SmallCaps.
            font.capitalization: Font.AllUppercase
            color: Theme.muted
        }

        Row {
            spacing: 4
            Text {
                id: valueLabel
                objectName: "tileValue"
                text: root.value
                // fontDisplay is the repo's "hero numeric tile value" size
                // (gui/style.py FONT_DISPLAY, used by the widget-kit
                // MetricTile/ReadoutCell) — fontLg is its compact fallback.
                font.pixelSize: root.compact ? Theme.fontLg : Theme.fontDisplay
                font.weight: Font.DemiBold
                color: Theme.text

                Behavior on color { ColorAnimation { duration: 150 } }
            }
            Text {
                objectName: "tileUnit"
                text: root.unit
                visible: root.unit.length > 0
                font.pixelSize: Theme.fontXs
                color: Theme.muted
                anchors.baseline: valueLabel.baseline
            }
        }

        Text {
            objectName: "tileCaption"
            visible: !root.compact && root.caption.length > 0
            text: root.caption
            font.pixelSize: Theme.fontXs
            color: Theme.muted
            elide: Text.ElideRight
            width: parent.width
        }
    }
}
