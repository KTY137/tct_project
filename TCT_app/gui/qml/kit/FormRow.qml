// FormRow — a caption-over-control column (kit_spec_v1.md §3's
// "(typography)" row grouping, alongside PanelHeader/SectionHeader/Eyebrow).
// QML counterpart of gui/panel_kit.py::form_row: an eyebrow caption above a
// caller-supplied control (a QtQuick.Controls SpinBox, a kit component,
// ...). Pure layout — no Surface, no rung, no material response.
import QtQuick
import Tct

Item {
    id: root
    objectName: "kitFormRow"

    property string caption: ""

    default property alias control: controlHost.data

    implicitWidth: Math.max(captionText.implicitWidth, controlHost.width, 120)
    implicitHeight: captionText.implicitHeight + col.spacing + controlHost.implicitHeight

    data: [
        Column {
            id: col
            anchors.fill: parent
            spacing: 2

            Text {
                id: captionText
                objectName: "formRowCaption"
                text: root.caption
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fontMetricLabel
                font.weight: Theme.weightMetricLabel
                font.letterSpacing: Theme.trackingMetricLabel
                font.capitalization: Font.AllUppercase
                color: Theme.muted
            }
            Item {
                id: controlHost
                objectName: "formRowControl"
                width: parent.width
                implicitHeight: childrenRect.height
                height: implicitHeight
            }
        }
    ]
}
