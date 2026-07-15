// PanelHeader — panel-level top bar: eyebrow+title (left) + optional
// trailing content (right, e.g. a run StatusPill) — kit_spec_v1.md §3's
// "(typography)" row (PanelHeader/SectionHeader/Eyebrow/FormRow share one
// type role: no Surface of their own, no material response). QML
// counterpart of gui/panel_kit.py::panel_header/eyebrow_title.
//
// Pure layout + type tokens (`fontPanelTitle`/`weightPanelTitle` for the
// title, the shared eyebrow metric-label voice for the caption) — no rung,
// no Surface, no ink beyond `text`/`muted` (the Pane/Shelf ink law already
// applies one level up, wherever this header sits).
import QtQuick
import Tct

Item {
    id: root
    objectName: "kitPanelHeader"

    property string eyebrow: ""
    property string title: ""

    // Trailing content (e.g. a run StatusPill) — the QWidget kit's
    // `panel_header(trailing=[...])` list, generalised to arbitrary QML
    // content via the default property.
    default property alias trailing: trailingRow.data

    implicitWidth: 200
    implicitHeight: Math.max(titleColumn.implicitHeight, trailingRow.implicitHeight)

    data: [
        Column {
            id: titleColumn
            objectName: "panelHeaderTitleColumn"
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0

            Text {
                objectName: "panelHeaderEyebrow"
                text: root.eyebrow
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fontMetricLabel
                font.weight: Theme.weightMetricLabel
                font.letterSpacing: Theme.trackingMetricLabel
                font.capitalization: Font.AllUppercase
                color: Theme.muted
            }
            Text {
                objectName: "panelHeaderTitle"
                text: root.title
                font.pixelSize: Theme.fontPanelTitle
                font.weight: Theme.weightPanelTitle
                color: Theme.text
            }
        },

        Row {
            id: trailingRow
            objectName: "panelHeaderTrailing"
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.spaceSm
        }
    ]
}
