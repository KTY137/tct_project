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
    // disabled fill: was a Theme.sunk guess — kit_spec_v1.md §2.6's disabled
    // row names a dedicated `disabledBg` fill token. pressed fill: was a
    // Theme.accentStrong guess for EVERY tone (not just primary) — the same
    // §2.6 row names one `pressed` fill token for all interactive rungs.
    color: !btn.enabled ? Theme.disabledBg
         : area.pressed ? Theme.pressed
         : btn.primary  ? Theme.accent
         : area.containsMouse ? Theme.raised
         : Theme.panel2
    border.width: 1
    border.color: btn.primary ? Theme.accentStrong : Theme.hairline

    Text {
        id: text
        anchors.centerIn: parent
        text: btn.label
        // disabled ink: was Theme.faint — repo law "faint is never text"
        // (gui/style.py); §2.6's disabled row names `muted` ink.
        color: !btn.enabled ? Theme.muted
             : btn.primary ? Theme.onAccent : Theme.text
        // Rail-chrome label role (kit_spec_v1.md Appendix A.2): was a
        // generic fontSm/font.bold guess.
        font.pixelSize: Theme.fontRail
        font.weight: Theme.weightRail
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
