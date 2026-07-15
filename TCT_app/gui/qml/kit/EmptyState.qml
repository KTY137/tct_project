// EmptyState (+error) — centred title/hint placeholder, hosted ON a Card
// (kit_spec_v1.md §3 EmptyState row: "on Card | body prose fontBody; error
// variant uses `error` token + word + glyph | entrance <= 100 ms crossfade
// only"). QML counterpart of gui/panel_kit.py::EmptyState — no Surface of
// its own (it is CONTENT a caller places inside their own Card/Well), so
// this file is pure layout + typography, matching the spec's rung column.
//
// Error variant redundant channels (never colour alone): the glyph (a plain
// Unicode mark, not an icon-font dependency QML cannot resolve the same way
// qtawesome does) + the WORD (title text itself, unconditional) + the
// `error` token tinting both.
//
// The 100 ms crossfade is a SPEC-FIXED constant (kit_spec_v1.md §3 EmptyState
// row), same class as FocusRing.qml's ringWidth/haloPx — cited, not guessed,
// and NOT gated by `Theme.motionEnabled`: kit_spec_v1.md §5.2 explicitly
// keeps "only <= 100 ms opacity crossfades" alive under reduced motion.
import QtQuick
import Tct

Item {
    id: root
    objectName: "kitEmptyState"

    property string title: ""
    property string hint: ""
    property string reason: ""
    property string variant: "default"   // "default" | "error"
    readonly property bool isError: variant === "error"

    // Optional retry affordance slot (e.g. a "Retry" button) — this class
    // only lays it out, never wires the click (retrying a failed connect is
    // a controller call, out of a pure-view widget's remit; QWidget kit
    // parity comment).
    property alias retrySlotData: retryHost.data

    implicitWidth: 260
    implicitHeight: col.implicitHeight

    opacity: 0
    Behavior on opacity {
        NumberAnimation { duration: 100 }   // kit_spec_v1.md §3 — spec-fixed, cited
    }
    Component.onCompleted: opacity = 1

    data: [
        Column {
            id: col
            objectName: "emptyStateColumn"
            anchors.centerIn: parent
            width: Math.min(parent.width > 0 ? parent.width : 320, 320)
            spacing: Theme.spaceSm

            Text {
                objectName: "emptyStateGlyph"
                visible: root.isError
                text: "✕"
                anchors.horizontalCenter: parent.horizontalCenter
                font.pixelSize: Theme.fontXl
                color: Theme.error
            }
            Text {
                objectName: "emptyStateTitle"
                text: root.title
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.pixelSize: Theme.fontLg
                font.weight: Theme.weightPanelTitle
                color: root.isError ? Theme.error : Theme.text
            }
            Text {
                objectName: "emptyStateHint"
                visible: root.hint.length > 0
                text: root.hint
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.pixelSize: Theme.fontBody
                font.weight: Theme.weightBody
                color: Theme.muted
            }
            Text {
                objectName: "emptyStateReason"
                visible: root.isError && root.reason.length > 0
                text: root.reason
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.pixelSize: Theme.fontBody
                font.weight: Theme.weightBody
                color: Theme.muted
            }
            Row {
                id: retryHost
                objectName: "emptyStateRetrySlot"
                anchors.horizontalCenter: parent.horizontalCenter
            }
        }
    ]
}
