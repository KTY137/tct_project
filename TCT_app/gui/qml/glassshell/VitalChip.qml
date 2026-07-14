// VITAL CHIP — one read-only fact about the machine.
//
// RATIFIED LAW (round-01 verdict): the shell may DISPLAY hazard state; it may
// NEVER trigger it. So this component has no clickable surface, no action, no
// signal — it is a Text and a dot. Danger belongs to the panel that owns the
// hardware (here: the real BiasPanel in the island, with its own DangerGate).
//
// It must stay legible at the FLAT tier — an operator on a frostless RDP
// session, or one who chose flat for accessibility, reads the SAME chip. That
// is why the chip is an OPAQUE token surface: no information ever lives in the
// glass. The glass is only ever the window BEHIND the panes.
import QtQuick
import QtQuick.Controls
import Tct

Rectangle {
    id: chip

    property string label: ""
    property string value: "--"
    property string state: "neutral"     // neutral | good | warn | crit | sim
    property bool stub: false
    property string why: ""

    // The dot/value colour. Named tokens only — a chip never invents a colour.
    readonly property color stateColor:
        state === "good" ? Theme.good
      : state === "warn" ? Theme.warn
      : state === "crit" ? Theme.crit
      : state === "sim"  ? Theme.sim
      : Theme.muted

    implicitWidth: row.implicitWidth + 2 * Theme.spaceMd
    implicitHeight: 30
    radius: Theme.radiusSm
    // Opaque, always (see the header): the FLAT tier is not a downgraded
    // reading experience, it is the same reading experience without glass.
    color: Theme.sunk
    border.width: 1
    border.color: chip.stub ? Theme.warn : Theme.hairline

    Row {
        id: row
        anchors.centerIn: parent
        spacing: Theme.spaceSm

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 7; height: 7; radius: 4
            color: chip.stateColor
            visible: !chip.stub
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: chip.label
            color: Theme.muted
            font.pixelSize: Theme.fontMetricLabel
            font.letterSpacing: Theme.trackingMetricLabel / 10.0
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: chip.value
            color: chip.stub ? Theme.muted : chip.stateColor
            font.pixelSize: Theme.fontValueCompact
            font.family: Theme.monoFamily
            font.bold: true
        }

        StubBadge {
            anchors.verticalCenter: parent.verticalCenter
            visible: chip.stub
            why: chip.why !== "" ? chip.why
                 : chip.label + ": no device is constructed for this readout in "
                   + "the skeleton (no auto-connect — hardware safety rule 1)."
        }
    }

    HoverHandler { id: hover }
    ToolTip.visible: hover.hovered && chip.why !== ""
    ToolTip.text: chip.why
    ToolTip.delay: 260
}
