// LivingGround — layer 0 and the frost source (kit_spec_v1.md §5.3–§5.4).
//
// Look: two accent washes drifting on slow CLOSED Lissajous paths + a slow
// neutral specular sweep over the canvas token. Constitution-grade band law
// (§5.3, pinned by tests/test_qml_kit_surface.py's N-random-phase test):
//
//   * washes move POSITION, never alpha — every translucent layer here has
//     a constant opacity of 1.0 with its peak alpha baked into the sprite
//     (scripts/gen_shadow_assets.py) or fixed in KitAssets;
//   * the summed tint is <= Theme.groundTintAlphaMax (0.07) at every pixel
//     of every frame BY CONSTRUCTION: 2 x washPeakAlpha + sweepPeakAlpha is
//     asserted against the budget at bake time and re-asserted in tests, so
//     the DL* 4.0 ground band (and with it every kit.md §6 contrast receipt)
//     is frame-invariant;
//   * NO SEMANTIC TINT, EVER — washes are baked from the `accent` token and
//     the sweep is neutral white; the ground carries no information.
//
// Tier posture: FLAT = plain canvas (washes hidden); TOKEN = static wash;
// SCENE = flowing + frost bake. Reduced motion (Theme.motionEnabled false):
// static, frost baked once — the look survives, the motion doesn't (§5.2).
//
// The frost bake (§2.4, mechanism proven by measurement A —
// artifacts_claude/lantern_frost_spike_20260714T233707Z, O(1) in panes):
// the ground content renders into ONE ShaderEffectSource with ONE MultiEffect
// blur on the SOURCE (FrostBake.qml — the only MultiEffect in the
// application, GLASS_LIVE_PANE_BUDGET = 1). Panes sample the result at their
// own sourceRect (Surface/FrostCrop.qml). Cadence is bounded and
// state-driven: static -> 0 Hz, `subtle` -> 6 Hz, `full` -> 12 Hz
// (Theme.frostRebakeHz*). The whole frost stack lives behind a SCENE-gated
// Loader, so token-tier (and offscreen) construction never touches
// QtQuick.Effects.
//
// Auto-calm (§5.4, u2_hero_plan §4 R4 — ONE switch): during a run the bake
// keeps running at the idle rate and only the run-owning pane freezes its
// own sampler (Surface.samplerFrozen; panel-scoped calm, ratified). The
// run-active clamp (ruling 1) bounds the room's effective speed to <= 1.0x
// whenever ANY run is active. KitEnv.calmPolicy === "global" is the encoded
// fallback: bake -> 0 Hz and the ground stills whole. `calm` additionally
// lets a detached, run-owning top-level calm whole (its wash amplitude eases
// to 0 over the 1200 ms law).
import QtQuick
import Tct

Item {
    id: root
    objectName: "livingGround"

    readonly property var kitEnv: KitEnv

    // -- settings (live through the Theme bridge; §5.3) ---------------------
    readonly property string mode: Theme.livingGlassMode      // off|subtle|full
    readonly property bool motionOn: Theme.motionEnabled
    readonly property real requestedSpeed: Theme.livingGlassSpeed

    // Detached run-owning panel calms WHOLE (§5.4); also driven by the
    // global-calm policy fallback. Precedence (§5.4, ruling 1):
    // reduced-motion (static) -> run-active clamp (<=1.0x) -> setting.
    property bool calm: false
    readonly property bool calmActive: calm || KitEnv.globalCalm

    // Ruling 1 — run-active speed clamp, app-wide, whenever ANY run is
    // active. The persisted 0.25–2.0x range applies in full only while idle.
    readonly property real effectiveSpeed: KitEnv.runActive
        ? Math.min(1.0, requestedSpeed) : requestedSpeed

    // `subtle` = half amplitude, half speed; `full` ~ 8% of the viewport
    // over Theme.groundFlowPeriodS (§5.3).
    readonly property real modeAmplitude: mode === "full" ? 0.08
        : mode === "subtle" ? 0.04 : 0.0
    readonly property real modeSpeedFactor: mode === "subtle" ? 0.5 : 1.0

    // Calm eases wash amplitude to rest over 1200 ms (§5.4 — the same
    // 1200 ms law the lamp pulse uses; spec-fixed).
    readonly property int calmEaseMs: 1200
    property real amplitudeScale: calmActive ? 0.0 : 1.0
    Behavior on amplitudeScale {
        enabled: Theme.motionEnabled
        NumberAnimation { duration: root.calmEaseMs }
    }

    // -- flow ---------------------------------------------------------------
    // One closed cycle in [0,1); every wash position is a pure function of
    // this (the N-random-phase band test drives it directly).
    property real phase: 0
    readonly property bool flowing: visible && motionOn && mode !== "off"
        && KitEnv.tier >= KitEnv.tierScene && !calmActive
    readonly property int periodMs: Math.max(1, Math.round(
        Theme.groundFlowPeriodS * 1000
        / Math.max(0.05, effectiveSpeed * modeSpeedFactor)))
    readonly property alias flowRunning: flowAnim.running

    // Wash drift amplitudes (px).
    readonly property real ax: width * modeAmplitude * amplitudeScale
    readonly property real ay: height * modeAmplitude * amplitudeScale

    // Tint budget, restated where it is spent (asserted at bake time by the
    // generator and re-asserted against Theme.groundTintAlphaMax in tests).
    readonly property real washPeakAlpha: KitAssets.washPeakAlpha
    readonly property real sweepPeakAlpha: KitAssets.sweepPeakAlpha
    readonly property real tintBudgetPeak: 2 * washPeakAlpha + sweepPeakAlpha

    NumberAnimation on phase {
        id: flowAnim
        running: root.flowing
        from: 0
        to: 1
        loops: Animation.Infinite
        duration: root.periodMs
    }

    // -- frost bake (SCENE only) ---------------------------------------------
    property bool frostEnabled: true
    // Bounded, state-driven cadence (§2.4). Pure policy number — the Timer
    // below only runs while the SCENE loader actually holds the bake.
    readonly property int bakeHz: {
        if (KitEnv.tier < KitEnv.tierScene) return 0
        if (!motionOn || calmActive || mode === "off") return 0
        return mode === "full" ? Theme.frostRebakeHzFull
                               : Theme.frostRebakeHzSubtle
    }
    signal baked()
    readonly property bool frostActive: frostLoader.status === Loader.Ready
        && frostLoader.item !== null
    readonly property Item frostItem: frostLoader.item
        ? frostLoader.item.output : null

    function bake() {
        if (frostLoader.item) {
            frostLoader.item.scheduleGround()
            root.baked()
        }
    }

    Component.onCompleted: KitEnv.ground = root
    Component.onDestruction: if (KitEnv.ground === root) KitEnv.ground = null

    // -- layers ---------------------------------------------------------------
    Item {
        id: washStack
        anchors.fill: parent

        Rectangle {
            objectName: "groundCanvas"
            anchors.fill: parent
            color: Theme.canvas
        }

        Item {
            id: washLayer
            objectName: "groundWashLayer"
            anchors.fill: parent
            // FLAT: nothing. TOKEN+: (static) wash — §5.2/§2.3.
            visible: KitEnv.tier > KitEnv.tierFlat && root.mode !== "off"

            // Two accent washes on closed Lissajous paths (1:2 and 2:1 —
            // both loop seamlessly at phase wrap). opacity is CONSTANT 1.0:
            // the band law forbids any per-frame alpha motion; the peak
            // tint is baked into the sprite.
            Image {
                id: wash1
                objectName: "groundWash1"
                source: Theme.dark ? "assets/ground_wash_dark.png"
                                   : "assets/ground_wash_light.png"
                width: Math.max(root.width, root.height) * 0.75
                height: width
                opacity: 1.0
                x: root.width * 0.30 - width / 2
                   + root.ax * Math.sin(2 * Math.PI * root.phase)
                y: root.height * 0.35 - height / 2
                   + root.ay * Math.sin(4 * Math.PI * root.phase + Math.PI / 3)
                smooth: true
                mipmap: false
            }
            Image {
                id: wash2
                objectName: "groundWash2"
                source: Theme.dark ? "assets/ground_wash_dark.png"
                                   : "assets/ground_wash_light.png"
                width: Math.max(root.width, root.height) * 0.65
                height: width
                opacity: 1.0
                x: root.width * 0.70 - width / 2
                   + root.ax * Math.sin(4 * Math.PI * root.phase + Math.PI / 2)
                y: root.height * 0.65 - height / 2
                   + root.ay * Math.sin(2 * Math.PI * root.phase)
                smooth: true
                mipmap: false
            }

            // The slow specular sweep — a NEUTRAL white band (never a
            // semantic hue), oscillating so the loop closes without a jump.
            // opacity constant; its peak alpha is part of the tint budget.
            Rectangle {
                id: sweep
                objectName: "groundSweep"
                width: root.width * 0.35
                height: root.height
                opacity: 1.0
                x: (root.width - width) / 2
                   + (root.width / 2) * root.amplitudeScale
                     * Math.sin(2 * Math.PI * root.phase)
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0) }
                    GradientStop {
                        position: 0.5
                        color: Qt.rgba(1, 1, 1, root.sweepPeakAlpha)
                    }
                    GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0) }
                }
            }
        }
    }

    // The bake: ShaderEffectSource + the application's ONE MultiEffect, in a
    // separate file behind this SCENE-gated Loader so QtQuick.Effects is
    // never parsed at FLAT/TOKEN (or offscreen).
    Loader {
        id: frostLoader
        objectName: "groundFrostLoader"
        anchors.fill: parent
        visible: false
        active: root.frostEnabled && KitEnv.tier >= KitEnv.tierScene
        source: "FrostBake.qml"
        onLoaded: {
            item.groundContent = washStack
            // "ground static -> 0 Hz" still means A frost exists: bake once
            // on activation (reduced motion / static ground at SCENE).
            Qt.callLater(root.bake)
        }
    }

    Timer {
        objectName: "groundBakeTimer"
        interval: root.bakeHz > 0 ? Math.round(1000 / root.bakeHz) : 1000
        running: root.bakeHz > 0 && frostLoader.item !== null
        repeat: true
        onTriggered: root.bake()
    }
}
