// FrostCrop — one pane's frost sampler (kit_spec_v1.md §2.4).
//
// INTERNAL to the kit: loaded by URL from Surface's glass-gated Loader,
// never resolved as a type (absent from qmldir), so the QtQuick.Shapes
// import is only parsed when a pane actually goes glass at SCENE.
//
// Samples the shared FROST texture (FrostBake.output) at this pane's own
// scene rect via ShaderEffectSource.sourceRect — panes are ~free samplers;
// the blur already happened once, at the source. The crop is re-snapshotted
// on every ground bake by Surface's Connections — UNLESS the pane is the
// run-owning pane of an active run (panel-scoped calm: the sampler simply
// stops being scheduled and this texture becomes the stale crop, §5.4
// mechanism (a)).
//
// Rounded corners come from ShapePath.fillItem (Qt 6.8+): the sampled
// texture fills a rounded PathRectangle on the scene graph — no mask effect,
// no second MultiEffect, the pane budget stays 1.
import QtQuick
import QtQuick.Shapes

Item {
    id: crop

    property Item frostSource: null
    property real cornerRadius: 0
    property rect cropRect: Qt.rect(0, 0, 0, 0)

    function resample() {
        sampler.scheduleUpdate()
    }

    ShaderEffectSource {
        id: sampler
        sourceItem: crop.frostSource
        sourceRect: crop.cropRect
        live: false          // scheduled per bake by Surface; frozen = stale crop
        visible: false
    }

    Shape {
        anchors.fill: parent
        ShapePath {
            strokeWidth: -1
            fillItem: sampler
            PathRectangle {
                x: 0; y: 0
                width: crop.width
                height: crop.height
                radius: crop.cornerRadius
            }
        }
    }
}
