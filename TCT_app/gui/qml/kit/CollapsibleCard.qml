// CollapsibleCard — a Card whose header disclosure toggle shows/hides its
// body, animated with the kit's spring identity (kit_spec_v1.md §3
// CollapsibleCard row: "as Card; unfold = motionUnfold (280 ms OutQuint) /
// spring"; §5.1 "Interactive geometry springs ... on: ... CollapsibleCard
// unfold" names `motionSpringUi`, spring 3.0/damping 0.32, as the actual
// mechanism — springs are motion IDENTITY in this kit, so the unfold uses
// the shared SpringAnimation, not a fixed-duration NumberAnimation; see the
// judgment-call note in this beat's report). Reduced motion (Theme.
// motionEnabled == false) collapses to snap (§5.2): the Behavior below is
// simply disabled, so the height change is instantaneous.
//
// QML counterpart of gui/panel_kit.py::CollapsibleCard (collapsed by default
// — the Z-focus card convention). Unlike CheckableCard (deferred, U3+;
// disables the body), collapsing only HIDES detail — whatever the caller
// puts in `headerTrailingData` (inherited from Card) stays live while
// collapsed.
//
// `collapsibleBody` is this type's OWN default property (shadowing Card's
// `cardBody` default for CollapsibleCard's own consumers) — a plain
// `CollapsibleCard { FormRow {...} }` routes its child there. This file's
// own internal items (the disclosure toggle, the unfold host) are added via
// EXPLICIT named-property assignment (`headerLeadingData: [...]` /
// `cardBody: [...]`), never as bare top-level children — the same "keep
// internals out of the default property" discipline Surface.qml/Card.qml
// use, which here also sidesteps the self-reference a bare `unfoldHost`
// declaration would hit against the freshly-declared `collapsibleBody`
// default.
import QtQuick
import Tct

Card {
    id: root
    objectName: "kitCollapsibleCard"

    property bool expanded: false

    default property alias collapsibleBody: unfoldHost.data

    // Hit target law (§2.6): interactive surfaces >= 36 px — the toggle is
    // the one truly interactive element this file adds itself.
    headerLeadingData: [
        Item {
            id: toggleGlyph
            objectName: "collapsibleToggle"
            width: 36
            height: 36

            Text {
                objectName: "collapsibleToggleGlyph"
                anchors.centerIn: parent
                // Down-caret (expanded) / right-caret (collapsed) — plain
                // Unicode glyphs, not a colour (never a hex literal).
                text: root.expanded ? "▾" : "▸"
                font.pixelSize: Theme.fontSm
                color: Theme.muted
            }
            TapHandler {
                onTapped: root.expanded = !root.expanded
            }
        }
    ]

    cardBody: [
        Column {
            id: unfoldHost
            objectName: "collapsibleBody"
            width: parent ? parent.width : 0
            height: root.expanded ? implicitHeight : 0
            clip: true
            visible: height > 0
            spacing: Theme.spaceSm

            Behavior on height {
                enabled: Theme.motionEnabled
                SpringAnimation {
                    spring: Theme.motionSpringUi.spring
                    damping: Theme.motionSpringUi.damping
                }
            }
        }
    ]
}
