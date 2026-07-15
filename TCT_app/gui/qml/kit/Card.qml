// Card — the titled panel-surface container (kit_spec_v1.md §3 "the
// workhorse"). QML counterpart of gui/panel_kit.py::Card: a Card rung
// Surface with an optional header (title + monospace subtitle, plus
// leading/trailing header-extra slots — the QML analogue of
// Card.add_header_widget(before_title=...)) over a body content column.
//
// Radius comes for free from Surface's own rung resolution (radiusXl,
// §2.5's concentric-radius law) — this file never sets radiusPx itself.
// Hover/press material response (§2.6) also comes for free from Surface
// whenever a consumer sets `interactive: true`; this file adds none of its
// own (rule: components don't own paint, the material does).
//
// Default-property override note (mirrors Surface.qml's own "explicit data:
// list keeps the material's own internals out of the default property"):
// Surface's own default property is named `content` (aliased to its
// contentSlot). Card cannot reuse that name (a QML type may never redeclare
// an ancestor's property identifier), so it exposes its OWN default under a
// fresh name, `cardBody` — every internal chrome item (header row, body
// column) is added via the explicit `data: [...]` list below, never as a
// bare top-level child, so it can never be mis-routed into `cardBody` by
// mistake (the exact hazard the Surface.qml comment calls out).
import QtQuick
import Tct

Surface {
    id: root
    objectName: "kitCard"
    rung: Surface.Card

    property string title: ""
    property string subtitle: ""

    // Header-extra slots (Card.add_header_widget(before_title=...) parity).
    // Non-default — assigned explicitly by name (`headerLeadingData: [...]`)
    // so a subtype (CollapsibleCard) can claim `headerLeadingData` for its
    // own disclosure toggle without colliding with a consumer's own use of
    // `headerTrailingData` for a trailing chip.
    property alias headerLeadingData: headerLeadingRow.data
    property alias headerTrailingData: headerTrailingRow.data

    // The body content slot — what a plain `Card { Text { ... } }` routes
    // its unlabeled child into. `bodyColumn` auto-stacks (Column), matching
    // the QWidget Card's `QVBoxLayout` body idiom 1:1.
    default property alias cardBody: bodyColumn.data

    implicitWidth: 240
    implicitHeight: (headerColumn.visible ? headerColumn.implicitHeight + Theme.spaceSm : 0)
        + bodyColumn.implicitHeight + 2 * Theme.spaceMd

    data: [
        Column {
            id: headerColumn
            objectName: "cardHeader"
            visible: root.title.length > 0
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: Theme.spaceMd
            anchors.rightMargin: Theme.spaceMd
            anchors.topMargin: Theme.spaceMd
            spacing: 2

            Row {
                id: headerRow
                width: parent.width
                spacing: Theme.spaceSm

                Row {
                    id: headerLeadingRow
                    objectName: "cardHeaderLeading"
                    spacing: Theme.spaceXs
                }

                Column {
                    id: titleColumn
                    width: Math.max(0, headerRow.width - headerLeadingRow.width
                        - headerTrailingRow.width
                        - (headerLeadingRow.width > 0 ? headerRow.spacing : 0)
                        - (headerTrailingRow.width > 0 ? headerRow.spacing : 0))
                    spacing: 1

                    Text {
                        objectName: "cardTitle"
                        text: root.title
                        width: parent.width
                        elide: Text.ElideRight
                        font.pixelSize: Theme.fontPanelTitle
                        font.weight: Theme.weightPanelTitle
                        color: Theme.text
                        Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
                    }
                    Text {
                        objectName: "cardSubtitle"
                        visible: root.subtitle.length > 0
                        text: root.subtitle
                        width: parent.width
                        elide: Text.ElideRight
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.fontXs
                        color: Theme.muted
                    }
                }

                Row {
                    id: headerTrailingRow
                    objectName: "cardHeaderTrailing"
                    spacing: Theme.spaceXs
                }
            }
        },

        Column {
            id: bodyColumn
            objectName: "cardBody"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.top: headerColumn.visible ? headerColumn.bottom : parent.top
            anchors.topMargin: headerColumn.visible ? Theme.spaceSm : Theme.spaceMd
            anchors.leftMargin: Theme.spaceMd
            anchors.rightMargin: Theme.spaceMd
            anchors.bottomMargin: Theme.spaceMd
            spacing: Theme.spaceSm
        }
    ]
}
