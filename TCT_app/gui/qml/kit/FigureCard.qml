// FigureCard — Card frame around a reserved island hole (kit_spec_v1.md §3
// FigureCard row: "Card frame around the reserved island hole; the kit
// draws the frame ONLY — never content into the hole; edgeShade inner top
// on the island rim"; u2_hero_plan.md §1.3 point 3). The Python IslandHost
// (U2.4, a LATER beat — not built here) looks up `figureCardHole` by
// objectName and positions the real pyqtgraph QWidget (ScanMapView / the
// z-focus PlotWidget) into it as a sibling stacked above this QQuickWidget;
// this file never parents, paints, or overlaps island pixels — the hole
// stays a plain transparent Item.
//
// `holeRect` is a convenience, test-friendly mirror of the hole's own scene
// geometry (mapped to the root item's own coordinate space) — offered so an
// offscreen suite can assert hole placement without a live top-level window.
// It is NOT the authoritative hand-off mechanism U2.4 will use (objectName
// lookup + the QQuickWidget's own SizeRootObjectToView coordinate identity,
// per u2_hero_plan.md §1.3) and this file deliberately does NOT register the
// hole with KitEnv's dead-zone registry — u2_hero_plan.md §2 U2.4 names
// IslandHost as the owner of that registration (batched with its own
// geometry-change tracking), so registering here too would double-count the
// zone once U2.4 lands.
import QtQuick
import Tct

Card {
    id: root
    objectName: "kitFigureCard"

    property rect holeRect: Qt.rect(0, 0, 0, 0)
    property int holeHeight: 160

    function _syncHoleRect() {
        if (!holeItem)
            return
        var p = holeItem.mapToItem(null, 0, 0)
        root.holeRect = Qt.rect(p.x, p.y, holeItem.width, holeItem.height)
    }

    cardBody: [
        Item {
            id: holeItem
            objectName: "figureCardHole"
            width: parent ? parent.width : 0
            height: root.holeHeight
            onXChanged: root._syncHoleRect()
            onYChanged: root._syncHoleRect()
            onWidthChanged: root._syncHoleRect()
            onHeightChanged: root._syncHoleRect()
            Component.onCompleted: root._syncHoleRect()

            // edgeShade inner top on the island rim (§2.5/§3) — the frame's
            // own rim treatment, not "content into the hole": a 1 px seam
            // that only peeks through once the real island widget is
            // positioned very slightly inset from this hole's own top edge.
            Rectangle {
                objectName: "figureCardHoleEdgeShade"
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 1
                color: Theme.edgeShade
            }
        }
    ]
}
