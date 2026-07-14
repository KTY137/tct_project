// PHASE RAIL — the left spine of the cockpit (revised candidate A, round-01).
//
// HONESTY: the rail RENDERS, but it is not wired to any run state. There is no
// phase model in the app yet, and inventing one here — inferring "we are in the
// Bias phase" from nothing — would be exactly the lie this skeleton exists to
// avoid. So the whole rail carries a STUB badge and the active phase is a plain
// local property that only the rail itself moves. When the real phase model
// lands, this file binds it and the badge comes off; nothing else changes.
//
// Clicking a phase does NOT arm, enable, home or start anything (there is
// nothing to start). It moves a highlight.
import QtQuick
import QtQuick.Controls
import Tct

Rectangle {
    id: rail

    // Purely local — see the header. NOT bound to a controller.
    property int activeIndex: 2
    readonly property var phases: [
        { name: "SETUP",   glyph: "1" },
        { name: "ALIGN",   glyph: "2" },
        { name: "BIAS",    glyph: "3" },
        { name: "SCAN",    glyph: "4" },
        { name: "ANALYSE", glyph: "5" }
    ]

    implicitWidth: 150
    radius: Theme.radiusMd
    color: Theme.panel                 // opaque pane — no info lives in glass
    border.width: 1
    border.color: Theme.hairline

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spaceSm
        spacing: Theme.spaceXs

        Item {
            width: parent.width
            height: 26
            Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: "PHASE"
                color: Theme.faint
                font.pixelSize: Theme.fontMetricLabel
                font.bold: true
                font.letterSpacing: Theme.trackingMetricLabel / 10.0
            }
            StubBadge {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                why: "The phase rail is NOT wired: the app has no phase/workflow "
                     + "model yet. Clicking a phase moves a highlight and nothing "
                     + "else — it does not arm, home, bias or start a scan."
            }
        }

        Repeater {
            model: rail.phases
            delegate: Rectangle {
                required property int index
                required property var modelData

                width: parent.width
                height: 40
                radius: Theme.radiusSm
                color: index === rail.activeIndex ? Theme.raised
                     : phaseArea.containsMouse ? Theme.panel2
                     : "transparent"
                border.width: 1
                border.color: index === rail.activeIndex ? Theme.accent : "transparent"

                Row {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spaceSm
                    spacing: Theme.spaceSm

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 20; height: 20; radius: 10
                        color: index === rail.activeIndex ? Theme.accent : Theme.sunk
                        Text {
                            anchors.centerIn: parent
                            text: modelData.glyph
                            color: index === rail.activeIndex ? Theme.onAccent : Theme.muted
                            font.pixelSize: Theme.fontXs
                            font.bold: true
                        }
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.name
                        color: index === rail.activeIndex ? Theme.text : Theme.muted
                        font.pixelSize: Theme.fontSm
                        font.bold: index === rail.activeIndex
                        font.letterSpacing: 0.5
                    }
                }

                MouseArea {
                    id: phaseArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: rail.activeIndex = index
                }
            }
        }
    }
}
