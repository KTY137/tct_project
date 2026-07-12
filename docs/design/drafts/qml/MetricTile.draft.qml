// DRAFT — Ollama qwen2.5-coder:14b (GPU lane), 2 rounds, 2026-07-12.
// Reviewed by Adam: NOT runnable as-is. Known defects for the implementer:
//   1. `border.color` is declared twice on the root Rectangle (syntax error) —
//      keep only the declarative hover binding.
//   2. `Column { margins: 8 }` is not a property — use anchors.fill +
//      anchors.margins: 8.
//   3. The 150 ms Behaviors (opacity/color) were dropped — re-add.
//   4. `import TCT.Theme 1.0` is a placeholder URI — use the real Theme
//      singleton import from gui/qml (see Shell.qml).
//   5. Accent bar: 3 px Rectangle with radius 10 renders oddly — inset it or
//      mask the right edge.
// Structure/layout/property surface below matches the mockup spec and is the
// agreed starting point for the Scan Viewer slice tiles.

import TCT.Theme 1.0

Rectangle {
    id: root
    implicitWidth: 180
    implicitHeight: compact ? 64 : 96
    radius: 10
    color: Theme.surface
    border.width: 1
    border.color: hover.hovered ? Qt.alpha(Theme.text, 0.25) : Theme.stroke

    property string title
    property string value
    property string unit
    property string caption
    property color accent: Theme.muted
    property bool stale: false
    property bool compact: false

    HoverHandler { id: hover }

    Column {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8

        Text {
            id: titleLabel
            text: title
            font.pixelSize: 12
            font.capitalization: Font.SmallCaps
            color: Theme.muted
        }

        Row {
            spacing: 4
            Text {
                text: value
                font.pixelSize: 24
                color: Theme.text
                opacity: stale ? 0.6 : 1
            }
            Text {
                text: unit
                font.pixelSize: 12
                color: Theme.muted
            }
        }

        Text {
            visible: !compact
            text: caption
            font.pixelSize: 12
            color: Theme.muted
        }
    }

    Rectangle {
        width: 3
        height: root.height
        color: accent
        anchors.left: parent.left
    }
}
