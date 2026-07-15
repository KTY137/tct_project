// ActionBar — frame + classed primary/secondary/motion/danger layout
// (kit_spec_v1.md §3 ActionBar row: "classes primary/secondary/motion/
// danger; danger sits alone, fills dangerFill/onDanger; motion class >= 44
// px targets"). Shelf-rung Surface as the frame; QML counterpart of
// gui/panel_kit.py::ActionBar's row, minus the buttons themselves.
//
// u2_hero_plan.md §1.5 / §2 U2.5 (never-migrates law, restated in this
// beat's brief): the danger and motion slots are RESERVED HOLES, not
// buttons — Abort/Find-focus stay real QWidget instances, re-parented (never
// re-implemented) into these holes by U2.5's IslandHost positioning. This
// file therefore paints NO button of its own anywhere: every slot is a
// plain transparent Item, found by objectName and positioned by the (later)
// island host — "the kit draws frames, never command content."
//
// No press/tap animation lives here (§3's "press at motionTap" obligation
// belongs to the re-hosted QWidget buttons' own feedback, not to this empty
// scaffold) — noted as a judgment call in this beat's report.
import QtQuick
import Tct

Surface {
    id: root
    objectName: "kitActionBar"
    rung: Surface.Shelf

    readonly property alias secondaryHole: secondaryHoleItem
    readonly property alias primaryHole: primaryHoleItem
    readonly property alias motionHole: motionHoleItem
    readonly property alias dangerHole: dangerHoleItem

    property int secondaryHoleWidth: 96
    property int primaryHoleWidth: 96
    property int motionHoleWidth: 120
    property int dangerHoleWidth: 96

    implicitHeight: 44 + 2 * Theme.spaceSm
    implicitWidth: secondaryHoleWidth + primaryHoleWidth + motionHoleWidth
        + dangerHoleWidth + 4 * Theme.spaceSm

    data: [
        Item {
            id: layout
            objectName: "actionBarLayout"
            anchors.fill: parent
            anchors.margins: Theme.spaceSm

            Row {
                id: leftRow
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.spaceSm

                // Hit target law (§2.6): interactive surfaces >= 36 px.
                Item {
                    id: secondaryHoleItem
                    objectName: "actionBarSecondaryHole"
                    width: root.secondaryHoleWidth
                    height: Math.max(36, layout.height)
                }
                Item {
                    id: primaryHoleItem
                    objectName: "actionBarPrimaryHole"
                    width: root.primaryHoleWidth
                    height: Math.max(36, layout.height)
                }
                // Motion class (§2.6/§3): >= 44 px — a motion command starts
                // real stage movement (hardware safety rule 2 class).
                Item {
                    id: motionHoleItem
                    objectName: "actionBarMotionHole"
                    width: root.motionHoleWidth
                    height: Math.max(44, layout.height)
                }
            }

            // Danger sits alone, separated from the rest by the layout's own
            // width (anchored right, not part of leftRow) — the QML analogue
            // of the QWidget ActionBar's `row.addStretch(1)` before danger.
            Item {
                id: dangerHoleItem
                objectName: "actionBarDangerHole"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: root.dangerHoleWidth
                height: Math.max(44, layout.height)
            }
        }
    ]
}
