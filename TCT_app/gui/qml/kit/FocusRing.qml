// FocusRing — the luminous focus ring + halo (kit_spec_v1.md §4.1, ruling 3).
//
// The 2 px `accent` ring is drawn ENTIRELY OUTSIDE the component's fill
// boundary, at `Theme.focusRingOffsetPx` beyond the edge — clearing the 1 px
// `hairlineStrong` outline so the ring always reads against the SURROUNDING
// rung surface, never the component's own fill (accent-on-accent is a
// non-case by construction; the standing `ring_contrast_scan` in
// scripts/kit_contrast_check.py audits the surround pairing). Both shells
// share this one convention (QSS `outline-offset` on the QWidget side).
//
// The 8 px soft halo is a pre-rendered BorderImage (assets baked by
// scripts/gen_shadow_assets.py — never a live effect), alpha-normalised at
// bake time and driven live by `Theme.focusHaloAlpha` (0.35 dark / 0.25
// light) so a theme flip needs no rebake. The halo is garnish — the ring
// alone is the accessible channel — and it NEVER appears on hazard rungs
// (ruling 4: Surface binds `halo: false` there; the ring itself is not
// material and is ALWAYS present on hazard).
//
// Usage: anchor `fill` to the component's fill-boundary item; the ring and
// halo extend outside it via negative margins.
import QtQuick
import Tct

Item {
    id: ring
    objectName: "kitFocusRing"

    // Corner radius of the target's fill boundary (the ring runs concentric,
    // radius grows by exactly its outward offset — the concentric-radius law).
    property int targetRadius: Theme.radiusMd
    // Bound by the consumer (Surface binds `activeFocus`).
    property bool active: false
    // Ruling 4: garnish only — Surface forces this false on hazard rungs.
    property bool halo: true

    // Spec-fixed structural constants (kit_spec_v1.md §4.1 — "2 px accent
    // ring", "8 px soft halo"). Not style tokens: same class as the 1 px
    // hairline outline width; cited, not guessed.
    readonly property int ringWidth: 2
    readonly property int haloPx: 8

    visible: active

    // Halo first (below the ring). Baked at peak alpha 1.0 in the theme's
    // accent hue; interior punched out at bake time so no halo pixel ever
    // falls on the target's own fill or the ring's track.
    BorderImage {
        objectName: "focusHalo"
        visible: ring.halo
        source: Theme.dark ? "assets/focus_halo_dark.png"
                           : "assets/focus_halo_light.png"
        anchors.fill: parent
        anchors.margins: -KitAssets.haloPad
        border.left: KitAssets.haloBorder
        border.right: KitAssets.haloBorder
        border.top: KitAssets.haloBorder
        border.bottom: KitAssets.haloBorder
        opacity: Theme.focusHaloAlpha
        smooth: true
    }

    // The ring proper — a live Rectangle border (crisp at any radius, follows
    // the accent token through theme flips with zero assets involved). Its
    // OUTER edge sits at offset+width beyond the fill; border draws inward,
    // so the INNER edge lands exactly `focusRingOffsetPx` outside the fill.
    Rectangle {
        objectName: "focusRingRect"
        anchors.fill: parent
        anchors.margins: -(Theme.focusRingOffsetPx + ring.ringWidth)
        radius: ring.targetRadius + Theme.focusRingOffsetPx + ring.ringWidth
        color: "transparent"
        border.width: ring.ringWidth
        border.color: Theme.accent
    }
}
