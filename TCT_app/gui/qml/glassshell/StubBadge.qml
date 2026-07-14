// STUB BADGE — the honesty primitive of the walking skeleton.
//
// Anything in this shell that is NOT wired to real state wears one of these.
// A skeleton whose fake parts look real is worse than no skeleton at all: the
// whole point of building it in the target technology (rather than mocking it)
// is that what you SEE is what the platform actually does. So the fakes must
// announce themselves, in the window, at a glance.
//
// Tokens only (Theme.warn / Theme.onAccent — gui/qml_theme.py). No inline hex.
import QtQuick
import QtQuick.Controls
import Tct

Rectangle {
    id: badge

    // What this badge is admitting to, in one plain sentence. Shown on hover.
    property string why: "not wired to real state in this skeleton"
    property string label: "STUB"

    implicitWidth: text.implicitWidth + 10
    implicitHeight: 15
    radius: Theme.radiusSm
    color: "transparent"
    border.width: 1
    border.color: Theme.warn

    Text {
        id: text
        anchors.centerIn: parent
        text: badge.label
        color: Theme.warn
        font.pixelSize: Theme.fontXs
        font.bold: true
        font.letterSpacing: 0.6
    }

    HoverHandler { id: hover; cursorShape: Qt.WhatsThisCursor }

    ToolTip.visible: hover.hovered
    ToolTip.text: badge.why
    ToolTip.delay: 220
}
