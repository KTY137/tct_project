// Surface — THE one material primitive (kit_spec_v1.md §2).
//
// "One material, lit from within. Components don't own paint; the material
// does." A single Surface resolves fill / frost / edges / shadow / focus /
// motion from its `rung` (§2.2 ladder) and the glass tier (§2.3, fed through
// KitEnv — default TOKEN, the safe floor). All U2.2+ components are
// `Surface` + content; change the material here and the whole cockpit
// follows.
//
// Laws encoded in this file (each pinned by tests/test_qml_kit_surface.py):
//  * Tier invariance (§2.3): FLAT/TOKEN paint the opaque rung token; SCENE
//    paints the token ONE RUNG UP at the rung's alpha over a frost crop, so
//    the composite lands on the rung it belongs to. Turning glass off
//    changes nothing that anything IS.
//  * Hazard is DEAD MATERIAL (§2.6 danger row, ruling 4): no hover lift, no
//    frost, no halo — ever, at every tier. An explicit glass/shadow/halo
//    flag on a Hazard rung THROWS at construction (the QML twin of
//    gui/panel_kit.py::register_glass_pane's refusal), and independently of
//    the throw the resolution clamps safe (opaque `panel`, no response).
//    The focus RING is not material and is always present (ruling 4).
//  * State never rides the material alone (§2.6): every material response
//    keeps a tier-independent channel (border token, fill token, ink) that
//    survives FLAT.
//  * Panel-scoped calm (§5.4, ruling 7): the run-owning pane (`runOwner`,
//    host-fed per the ScanViewer-host convention) stops scheduling its own
//    frost sampler while a run is active (`samplerFrozen`) and holds a stale
//    crop. The room keeps flowing; KitEnv.calmPolicy === "global" is the
//    encoded fallback that stops the bake at the source instead.
//  * No inline hex, no live effects here: shadows are pre-rendered 9-patch
//    BorderImages (§2.5); the frost crop mechanism lives in FrostCrop.qml
//    behind a Loader that only activates at SCENE with a live ground.
//
// Content: children declared on a Surface land in the padded-by-consumer
// content slot ABOVE the material (explicit `data:` list below keeps the
// material's own internals out of the default property).
import QtQuick
import Tct

Item {
    id: root
    objectName: "kitSurface"

    enum Rung { Shelf, Card, Tile, Well, Island, Hazard }

    // ---- public API (frozen for U2.2 component authors) ------------------
    property int rung: Surface.Card
    // Enables the §2.6 material responses (hover/press/focus). Surface owns
    // NO input semantics beyond hover — components drive `pressed` from
    // their own handlers; the material never emits anything (the shell
    // displays, the panel acts).
    property bool interactive: false
    property bool pressed: false
    // Test/preview hook only: OR'd with the live HoverHandler (offscreen
    // suites cannot synthesize hover). Never set by production components.
    property bool previewHover: false
    // Ruling 7: the host marks the pane of the top-level currently hosting
    // the ScanViewer. Drives `samplerFrozen` (panel-scoped calm).
    property bool runOwner: false
    // Tri-state response overrides: undefined = rung-resolved; `false`
    // disables; `true` can never grant a response the rung refuses — on a
    // Hazard rung an explicit `true` THROWS at construction (§2.1).
    property var glassOverride: undefined
    property var shadowOverride: undefined
    property var haloOverride: undefined
    // Rung radius (§2.5 concentric-radius law); override only for nesting.
    property int radiusPx: rung === Surface.Shelf ? Theme.radiusShelf
        : (rung === Surface.Card || rung === Surface.Hazard) ? Theme.radiusXl
        : Theme.radiusMd

    default property alias content: contentSlot.data
    // The engine-scoped scene state, exposed so hosts/tests reach the
    // singleton without qmlTypeId plumbing.
    readonly property var kitEnv: KitEnv

    activeFocusOnTab: interactive && enabled

    // ---- resolution (§2.2 / §2.3 / §2.6) ----------------------------------
    readonly property bool hazard: rung === Surface.Hazard

    readonly property bool hovered: interactive && enabled && !hazard
        && (hoverHandler.hovered || previewHover)

    readonly property string materialState: !enabled ? "disabled"
        : (interactive && !hazard && pressed) ? "pressed"
        : hovered ? "hover"
        : "idle"

    // Frost capability is strictly rung-based (Shelf/Card only), gated on
    // the SCENE tier and the enabled state (§2.6 disabled: sampling OFF).
    // An override can only turn glass OFF, never on.
    readonly property bool effectiveGlass: !hazard && enabled
        && (rung === Surface.Shelf || rung === Surface.Card)
        && KitEnv.tier >= KitEnv.tierScene
        && glassOverride !== false

    // The TOKEN this surface paints (opaque at FLAT/TOKEN; one rung up when
    // glass is live — §2.3 "paint one rung up, at your rung's alpha").
    readonly property color resolvedFillColor: {
        if (!enabled)
            return Theme.disabledBg
        if (interactive && !hazard && pressed)
            return Theme.pressed
        if (effectiveGlass)
            return rung === Surface.Shelf ? Theme.card : Theme.raised
        if (rung === Surface.Shelf)  return Theme.shelf
        if (rung === Surface.Card)   return Theme.card
        if (rung === Surface.Tile)   return Theme.raised
        if (rung === Surface.Well)   return Theme.well
        if (rung === Surface.Island) return Theme.plotBg
        return Theme.panel            // Hazard — opaque at every tier
    }

    // Pressed paints the opaque `pressed` token (§2.6 fill-token channel);
    // idle/hover glass keeps the rung alpha over the frost crop.
    readonly property real resolvedFillAlpha:
        (effectiveGlass && !(interactive && pressed))
            ? (rung === Surface.Shelf ? Theme.glassPaneAlpha : Theme.glassCardAlpha)
            : 1.0

    // Mandatory `hairlineStrong` outline on shelf/card/island/hazard (§2.5);
    // tile rests on `hairline` (shipped MetricTile precedent) and answers
    // hover with the §2.6 tier-independent border -> hairlineStrong channel.
    readonly property int resolvedBorderWidth: rung === Surface.Well ? 0 : 1
    readonly property color resolvedBorderColor: {
        if (rung === Surface.Well)
            return Theme.hairline      // width 0 — never painted
        if (rung === Surface.Tile)
            return hovered ? Theme.hairlineStrong : Theme.hairline
        return Theme.hairlineStrong
    }

    // Shadow ladder (§2.5): rung base, stepped one up on hover / one down on
    // press (§2.6). None on well/island/hazard — and none may FALL on an
    // island either (dead-zone law §4.4, mechanism "shadow").
    readonly property string shadowLevel: {
        if (shadowOverride === false || !enabled || hazard)
            return "none"
        var base = rung === Surface.Shelf ? 3
                 : rung === Surface.Card ? 2
                 : rung === Surface.Tile ? 1 : 0
        if (base === 0)
            return "none"
        if (interactive) {
            if (pressed)      base = Math.max(1, base - 1)
            else if (hovered) base = Math.min(4, base + 1)
        }
        return ["none", "contact", "card", "pane", "float"][base]
    }

    // Panel-scoped calm (§5.4 mechanism (a)): the run-owning pane stops
    // scheduling its own sampler and holds a stale crop of the shared FROST
    // texture. Under the "global" policy the bake itself stops (LivingGround)
    // — this flag is then subsumed, harmlessly true.
    readonly property bool samplerFrozen: runOwner && KitEnv.runActive

    // ---- construction guard (§2.1 — the register_glass_pane twin) ---------
    Component.onCompleted: {
        if (rung === Surface.Island || rung === Surface.Hazard)
            KitEnv.registerDeadZone(objectName, root)
        if (hazard && (glassOverride === true || shadowOverride === true
                       || haloOverride === true))
            throw new Error(
                "kit.Surface: Hazard rung refuses glass/shadow/halo response "
                + "flags (kit_spec_v1.md §2.1 — hazard surfaces are opaque, "
                + "dead material at every tier; the QML twin of "
                + "register_glass_pane's refusal)")
        if (!hazard && glassOverride === true
                && rung !== Surface.Shelf && rung !== Surface.Card)
            console.warn("kit.Surface: glassOverride=true is ignored on rung",
                         rung, "— frost is a Shelf/Card capability (§2.2)")
    }
    Component.onDestruction: KitEnv.unregisterDeadZone(root)

    // ---- material stack (explicit data: — see header) ---------------------
    data: [
        // 1. Shadow (pre-rendered 9-patch, behind everything; §2.5).
        BorderImage {
            id: shadowImg
            objectName: "surfaceShadow"
            readonly property int patchBorder: root.shadowLevel === "none"
                ? 0 : KitAssets.shadowBorder[root.shadowLevel]
            visible: root.shadowLevel !== "none"
            source: root.shadowLevel === "none" ? ""
                : "assets/shadow_" + root.shadowLevel
                  + (Theme.dark ? "_dark" : "_light") + ".png"
            anchors.fill: parent
            anchors.margins: root.shadowLevel === "none"
                ? 0 : -KitAssets.shadowPad[root.shadowLevel]
            border.left: shadowImg.patchBorder
            border.right: shadowImg.patchBorder
            border.top: shadowImg.patchBorder
            border.bottom: shadowImg.patchBorder
            smooth: true
        },

        // 2. Frost crop (SCENE + live ground only; FrostCrop.qml holds the
        //    ShaderEffectSource + rounded-clip Shape so its QtQuick.Shapes
        //    import is never parsed on the token-tier path).
        Loader {
            id: frostLoader
            objectName: "surfaceFrostLoader"
            anchors.fill: parent
            active: root.effectiveGlass && KitEnv.ground !== null
                && KitEnv.ground.frostActive
            source: "FrostCrop.qml"
            onLoaded: {
                item.frostSource = Qt.binding(function () {
                    return KitEnv.ground ? KitEnv.ground.frostItem : null
                })
                item.cornerRadius = Qt.binding(function () {
                    return root.radiusPx
                })
                item.cropRect = root._frostRect()
            }
        },

        // Re-crop + re-snapshot after every bake — unless this pane is the
        // run-owning pane of an active run (panel-scoped calm, stale crop).
        Connections {
            target: KitEnv.ground
            enabled: frostLoader.active
            function onBaked() {
                if (root.samplerFrozen || !frostLoader.item)
                    return
                frostLoader.item.cropRect = root._frostRect()
                frostLoader.item.resample()
            }
        },

        // 3. Fill: the resolved token at the resolved alpha (opaque token at
        //    FLAT/TOKEN; one-rung-up tint over the frost crop at SCENE).
        Rectangle {
            id: fillRect
            objectName: "surfaceFill"
            anchors.fill: parent
            radius: root.radiusPx
            color: Qt.rgba(root.resolvedFillColor.r, root.resolvedFillColor.g,
                           root.resolvedFillColor.b, root.resolvedFillAlpha)
            border.width: root.resolvedBorderWidth
            border.color: root.resolvedBorderColor
            Behavior on color {
                enabled: Theme.motionEnabled
                ColorAnimation { duration: Theme.motionTap }
            }
            Behavior on border.color {
                enabled: Theme.motionEnabled
                ColorAnimation { duration: Theme.transitionMs }
            }
        },

        // 4a. Specular inner top edge — the machined-edge highlight
        //     (shelf/card/tile; §2.5). Hover brightens it one step (§2.6):
        //     the token's own alpha x1.5, clamped — a live derivation of
        //     Theme.specular, never a second literal.
        Rectangle {
            objectName: "surfaceSpecular"
            visible: root.enabled && (root.rung === Surface.Shelf
                || root.rung === Surface.Card || root.rung === Surface.Tile)
            anchors.top: fillRect.top
            anchors.left: fillRect.left
            anchors.right: fillRect.right
            anchors.topMargin: 1
            anchors.leftMargin: root.radiusPx
            anchors.rightMargin: root.radiusPx
            height: 1
            color: root.hovered
                ? Qt.rgba(1, 1, 1, Math.min(1.0, Theme.specular.a * 1.5))
                : Theme.specular
        },

        // 4b. edgeShade inner top — the inverse cue, wells and islands only
        //     (§2.5). Rendered as the 1 px pre-blended token line (QSS
        //     border-top-color parity); the "real inner gradient" upgrade
        //     needs a numeric edgeShade-alpha exposure — reported as a
        //     bridge gap, not guessed here.
        Rectangle {
            objectName: "surfaceEdgeShade"
            visible: root.rung === Surface.Well || root.rung === Surface.Island
            anchors.top: fillRect.top
            anchors.left: fillRect.left
            anchors.right: fillRect.right
            anchors.topMargin: 1
            anchors.leftMargin: root.radiusPx
            anchors.rightMargin: root.radiusPx
            height: 1
            color: Theme.edgeShade
        },

        // 4c. Hazard left stripe (§2.2 hazard edge channel; 4 px is the
        //     spec-fixed stripe width, kit_spec_v1.md §3 HazardSurface row).
        //     The 45-degree hatch + eyebrow word + glyph are HazardSurface
        //     content obligations (§3, deferred to first consumer, U3+).
        Rectangle {
            objectName: "surfaceHazardStripe"
            visible: root.hazard
            width: 4
            anchors.left: fillRect.left
            anchors.top: fillRect.top
            anchors.bottom: fillRect.bottom
            anchors.margins: 1
            color: Theme.danger
        },

        // 5. Content slot (components put ink/controls here, above the
        //    material, below the focus ring).
        Item {
            id: contentSlot
            anchors.fill: parent
        },

        // 6. Focus ring + halo (§4.1). The ring is ALWAYS wired, hazard
        //    included (ruling 4); only the halo dies on hazard rungs.
        FocusRing {
            anchors.fill: parent
            targetRadius: root.radiusPx
            active: root.interactive && root.enabled && root.activeFocus
            halo: !root.hazard && root.haloOverride !== false
        },

        HoverHandler {
            id: hoverHandler
            enabled: root.interactive && root.enabled && !root.hazard
        }
    ]

    // Scene rect of this pane in the frost texture's coordinates.
    function _frostRect() {
        var g = KitEnv.ground
        if (!g || !g.frostItem)
            return Qt.rect(0, 0, 0, 0)
        var p = root.mapToItem(g.frostItem, 0, 0)
        return Qt.rect(p.x, p.y, root.width, root.height)
    }
}
