// KitEnv — the kit's scene-state singleton (one instance per QML engine).
//
// The seam between the Python host and the LANTERN material system
// (kit_spec_v1.md §2.3 tier resolution, §5.4 auto-calm, §4.4 dead-zone law).
// The composition root / island host (U2.3–U2.4) feeds these properties; the
// kit only ever READS them. Nothing here talks to hardware, controllers or
// run logic — `runActive` is a display-side mirror of the read-only run
// facade's `active` flag, fed by the host exactly like `runState.*`.
//
// Tier vocabulary mirrors gui/glass_env.py::GlassTier (FLAT < TOKEN < WINDOW
// < SCENE — COMPOSED never reaches the kit). The default is TOKEN: the same
// SAFE_FLOOR glass_env lands every unknown on, and the tier every offscreen
// test run caps at (u2_hero_plan.md §3.3). A host that never touches KitEnv
// gets the fully-legible opaque cockpit — fail-safe direction is DOWN.
//
// CALM POLICY — ONE switch (u2_hero_plan.md §4 R4, DECISIONS "U1 CLOSED, U2
// entry gate PAID"): measurement B PASSED, so `calmPolicy` defaults to
// "panel" (panel-scoped calm ships: the run-owning pane freezes its own
// frost sampler — Surface.samplerFrozen — and the room keeps flowing at the
// run-active <=1.0x clamp). The ratified fallback, run-active GLOBAL calm
// (bake -> 0 Hz app-wide, ground stills whole), stays encoded behind the
// SAME hook as the "global" policy value, default off. A measurement-B
// surprise flips this one flag, not the architecture.
pragma Singleton
import QtQuick
import Tct

QtObject {
    id: env

    // -- glass tier (gui/glass_env.py::GlassTier ints; COMPOSED never here) --
    readonly property int tierFlat: 0
    readonly property int tierToken: 1
    readonly property int tierWindow: 2
    readonly property int tierScene: 3
    // Host-fed. TOKEN = SAFE_FLOOR (glass_env) = the offscreen test tier.
    property int tier: tierToken

    // -- run state (read-only mirror of the facade's `active`, host-fed) ----
    property bool runActive: false

    // -- the one calm switch (§5.4 / u2_hero_plan §4 R4) --------------------
    // "panel" (ratified default): run-owning pane freezes its own sampler.
    // "global" (encoded fallback): bake -> 0 Hz + ground stills, app-wide.
    property string calmPolicy: "panel"
    readonly property bool globalCalm: calmPolicy === "global" && runActive

    // -- the living ground / frost source (one per engine; a detached panel
    //    is its own top-level with its own engine, ground and frost phase —
    //    kit_spec_v1.md §5.4 window-boundary caveat) -------------------------
    property var ground: null

    // ---------------------------------------------------------------------
    // Dead-zone registry (kit_spec_v1.md §4.4, ruling 5): island and hazard
    // rects are dead zones — no pane may extend translucent pixels within
    // `Theme.spaceMd` (12 px) of them by ANY of the three translucent-pixel
    // mechanisms {sample, shadow, halo}. This singleton owns the scene-level
    // list + the debug geometric assertion; the offscreen all-surfaces
    // walker lands with the island host (U2.4, tests/test_qml_dead_zones.py).
    // ---------------------------------------------------------------------
    property bool debugAsserts: false
    // [{name, item|null, rect|null}] — reassigned (never mutated in place)
    // so QML bindings on `deadZones` re-evaluate.
    property var deadZones: []

    function registerDeadZone(name, item) {
        var zs = deadZones.slice()
        zs.push({ "name": String(name), "item": item, "rect": null })
        deadZones = zs
    }

    // Rect-based registration for zones with no live item (and for tests).
    function registerDeadZoneRect(name, rect) {
        var zs = deadZones.slice()
        zs.push({ "name": String(name), "item": null, "rect": rect })
        deadZones = zs
    }

    function unregisterDeadZone(ref) {
        deadZones = deadZones.filter(function (z) {
            return z.item !== ref && z.name !== ref
        })
    }

    // Scene-space rects of every registered zone (item zones mapped live, so
    // a moved/resized island is always current — nothing cached).
    function deadZoneRects() {
        var out = []
        for (var i = 0; i < deadZones.length; ++i) {
            var z = deadZones[i]
            if (z.item) {
                var p = z.item.mapToItem(null, 0, 0)
                out.push({ "name": z.name, "x": p.x, "y": p.y,
                           "width": z.item.width, "height": z.item.height })
            } else if (z.rect) {
                out.push({ "name": z.name, "x": z.rect.x, "y": z.rect.y,
                           "width": z.rect.width, "height": z.rect.height })
            }
        }
        return out
    }

    // True when rect a keeps >= clearance distance from rect b on some axis.
    // Exactly `clearance` apart is legal (the law is ">= spaceMd clearance").
    function rectsClear(a, b, clearance) {
        return a.x >= b.x + b.width + clearance
            || b.x >= a.x + a.width + clearance
            || a.y >= b.y + b.height + clearance
            || b.y >= a.y + a.height + clearance
    }

    // Violations of the dead-zone law for one translucent-pixel extent
    // (`rect`, scene coords) of one mechanism ("sample" | "shadow" | "halo").
    function violations(rect, mechanism, clearance) {
        var c = (clearance === undefined) ? Theme.spaceMd : clearance
        var out = []
        var zones = deadZoneRects()
        for (var i = 0; i < zones.length; ++i) {
            if (!rectsClear(rect, zones[i], c))
                out.push({ "zone": zones[i].name,
                           "mechanism": String(mechanism) })
        }
        return out
    }

    // The runtime debug assertion (wired per-geometry-change by the island
    // host in U2.4; callable by anything that opens a translucent extent).
    function assertClear(rect, mechanism, sourceName) {
        var v = violations(rect, mechanism, undefined)
        if (v.length > 0 && debugAsserts) {
            for (var i = 0; i < v.length; ++i)
                console.error("kit dead-zone violation:", sourceName,
                              "extends", v[i].mechanism, "pixels within",
                              Theme.spaceMd, "px of island/hazard zone",
                              v[i].zone, "(kit_spec_v1.md §4.4, ruling 5)")
        }
        return v
    }

    // Test/teardown convenience — one engine == one KitEnv, so a fresh
    // engine is the usual isolation; this is for same-engine reuse.
    function reset() {
        tier = tierToken
        runActive = false
        calmPolicy = "panel"
        ground = null
        deadZones = []
        debugAsserts = false
    }
}
