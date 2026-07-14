// CHROME BUTTON — a shell-chrome action.
//
// SAFETY: nothing dangerous is reachable from shell chrome. Every button built
// from this component is a VIEW action (theme, backdrop, tier) or a connect of
// a SIMULATED device. HV enable / ramp / stop, homing, motion and scan start
// live in the panel that owns the hardware and go through its DangerGate —
// never here (round-01 verdict, ratified). If a future button in this file
// needs a confirmation dialog, it is in the wrong file.
import QtQuick
import QtQuick.Controls
import Tct

Rectangle {
    id: btn

    property string label: ""
    property string tip: ""
    property bool primary: false
    signal clicked()

    implicitWidth: text.implicitWidth + 2 * Theme.spaceMd
    implicitHeight: 28
    radius: Theme.radiusSm
    color: !btn.enabled ? Theme.sunk
         : area.pressed ? Theme.accentStrong
         : btn.primary  ? Theme.accent
         : area.containsMouse ? Theme.raised
         : Theme.panel2
    border.width: 1
    border.color: btn.primary ? Theme.accentStrong : Theme.hairline

    Text {
        id: text
        anchors.centerIn: parent
        text: btn.label
        color: !btn.enabled ? Theme.faint
             : btn.primary ? Theme.onAccent : Theme.text
        font.pixelSize: Theme.fontSm
        font.bold: btn.primary
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        enabled: btn.enabled
        cursorShape: Qt.PointingHandCursor
        onClicked: btn.clicked()
    }

    ToolTip.visible: area.containsMouse && btn.tip !== ""
    ToolTip.text: btn.tip
    ToolTip.delay: 300
}
