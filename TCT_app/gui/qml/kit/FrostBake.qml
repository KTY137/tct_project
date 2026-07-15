// FrostBake — the ONE blur in the application (kit_spec_v1.md §2.4).
//
// INTERNAL to the kit: loaded by URL from LivingGround's SCENE-gated Loader,
// never resolved as a type (deliberately absent from qmldir), so the
// QtQuick.Effects import below is only ever parsed when a SCENE-tier ground
// actually activates. The living ground renders into ONE ShaderEffectSource;
// ONE MultiEffect blur pass on that SOURCE produces the shared FROST texture
// every Shelf/Card samples at its own sourceRect (FrostCrop.qml). Cost
// scales with ground CHANGES, not pane count — measured O(1) in panes
// (measurement A, artifacts_claude/lantern_frost_spike_20260714T233707Z).
//
// GLASS_LIVE_PANE_BUDGET = 1: this file is the budget. The lint in
// tests/test_qml_kit_surface.py fails the suite if a second MultiEffect ever
// appears anywhere under gui/qml/.
//
// One blur depth: the bake runs at Theme.blurPane (40 px, the Shelf depth).
// §2.2's shallower per-card depth (blurCard 16) cannot exist under the
// one-blur law without a second bake pass — reconciled in favour of §2.4's
// load-bearing mechanism; see the U2.1 beat report.
import QtQuick
import QtQuick.Effects
import Tct

Item {
    id: bake

    // Set by LivingGround after load (the wash stack — NOT the ground root,
    // which would recursively include this bake).
    property Item groundContent: null
    readonly property Item output: blur

    function scheduleGround() {
        groundSource.scheduleUpdate()
    }

    ShaderEffectSource {
        id: groundSource
        anchors.fill: parent
        sourceItem: bake.groundContent
        live: false          // cadence-driven: LivingGround.bake() schedules
        recursive: false
        visible: false
    }

    MultiEffect {
        id: blur
        anchors.fill: parent
        source: groundSource
        blurEnabled: true
        blur: 1.0
        blurMax: Theme.blurPane
        autoPaddingEnabled: false
        visible: false       // never composited directly; panes sample it
    }
}
