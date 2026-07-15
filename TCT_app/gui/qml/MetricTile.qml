// MetricTile — a single tokenized metric readout tile (view only).
//
// QML analogue of gui/panel_kit.py's MetricTile/readout_cell
// (cockpit_style_overhaul.md §2: "MetricTile(label, value, state) ... built
// on existing readout_cell"). This file is the QML-land counterpart used by
// the Scan Viewer slice's ScanStatusStrip; it holds NO logic of its own —
// every value is a property the caller binds (see ScanStatusStrip.qml
// binding runState.*). No timers, no state derivation, no run-control calls.
//
// Started from docs/design/drafts/qml/MetricTile.draft.qml (Ollama draft,
// Adam-reviewed). Fixes applied vs that draft:
//   1. ONE declarative `border.color` binding (hover-lighten) — the draft
//      declared `border.color` twice, a QML syntax error.
//   2. The inner layout uses `anchors.fill` + `anchors.margins` — the draft's
//      `Column { margins: 8 }` is not a real Column property.
//   3. 150ms Behaviors on opacity + color are restored (the draft dropped
//      them).
//   4. Real Theme import (`import Tct`, gui/qml_theme.py, fed from
//      gui/style.py) replaces the draft's placeholder `import TCT.Theme 1.0`.
//   5. The accent bar is inset top/bottom (not full `root.height`) and given
//      a small radius so it doesn't visually collide with the tile's own
//      corner radius.
//
// Cockpit v5 D0 pass (docs/design/cockpit_design_system.md §3-4, mirrors the
// same behaviours gui/panel_kit.py::MetricTile/gui/status_widgets.py::
// ReadoutCell just gained on the QWidget side):
//   6. Fit/ellipsize — "Values must ellipsize/fit — a tile can never bleed
//      into a neighbour" (§3). title/value/caption are now each bound to a
//      real, finite width (Column doesn't stretch children to its own width
//      by default) with `elide: Text.ElideRight`; the value ALSO gets
//      `fontSizeMode: Text.HorizontalFit` (shrink the font first, elide only
//      if it still doesn't fit at `minimumPixelSize`) — the two techniques
//      the task brief names ("elide/fontSizeMode"). `root.clip = true` is a
//      belt-and-suspenders backstop. This is the fix for the render audit's
//      "DISCONNECTED-overflow" bug: a long value/title used to just paint
//      past the tile's own bounds with no clipping and no shrink/truncate.
//   7. Stale ink — a stale tile (law 4) now desaturates its text colour to
//      `Theme.muted` (title/value/caption; `Theme.faint` is RETIRED for
//      text as of the 2026-07-14 WCAG pass — it was 2.6:1), not just the pre-existing
//      opacity dim, matching the QWidget-kit's ink-based treatment.
//   8. Behavior durations now bind `Theme.transitionMs` (law 8: "state
//      transitions ease ~200 ms") instead of a hardcoded `150`, so the QML
//      and QSS/QWidget sides agree on one number (gui/style.py
//      TRANSITION_MS).
//
// Cockpit v5 D2 pass (docs/design/cockpit_design_system.md §5 — the merged
// Progress·ETA strip tile "with meter"):
//   9. Optional thin progress meter — `meterFraction` (0..1; a negative value,
//      the default, hides it). QML analogue of the artifact's `.tile .meter`
//      bar. View only: the caller computes the fraction (e.g.
//      `runState.progressFraction`, already derived presentation-only on the
//      view-model) — this file just clamps + renders it, with a width
//      Behavior (law 8: values update, they don't animate continuously; this
//      eases a CHANGE, it does not run on its own).
//
// Baldr attack-pass fix (2026-07-15, docs/DECISIONS.md "Post-attack-pass
// rulings" ruling 2, docs/design/qml_kit_forge/attack_baldr.md BLOCKER-1):
//  10. The `opacity: stale ? 0.6 : 1.0` cascade is REMOVED. It stacked on
//      top of item 7's already-correct ink swap and was measured to blow AA
//      even for the non-text 3:1 floor (dark crit 5.02->2.59, light warn
//      5.43->2.52). Stale is ink-only now, per Lantern §5. Since ink alone
//      is never a legal sole channel (WCAG SC 1.4.1), the title row also
//      gains `tileStaleMark` — a small unconditional text marker ("STALE")
//      that reads even on compact tiles, whose caption (the OTHER redundant
//      channel some callers set, e.g. the HV tile's "not connected") is
//      hidden by `compact` (see the caption Text below).
import QtQuick
import Tct

Rectangle {
    id: root

    // -- property surface (per the task brief; matches the draft's names) - #
    property string title: ""
    property string value: ""
    property string unit: ""
    property string caption: ""
    property color accent: Theme.muted
    property bool stale: false
    property bool compact: false
    // -1 (default) hides the meter; any 0..1 value shows it (values outside
    // 0..1 are clamped so a caller's rounding/timing glitch can never paint a
    // bar past the tile's own bounds).
    property real meterFraction: -1

    objectName: "metricTile"
    implicitWidth: 180
    implicitHeight: compact ? 64 : 96
    radius: Theme.radiusMd
    color: Theme.panel
    border.width: 1
    // Declarative hover-lighten border — a HoverHandler-driven binding, never
    // an imperative onEntered/onExited colour assignment.
    border.color: hoverHandler.hovered ? Theme.hairlineStrong : Theme.hairline
    // NOTE: no `opacity: stale ? ... : 1.0` here — removed, see item 10
    // above. Stale renders through ink alone (value/meter Text below) plus
    // the `tileStaleMark` non-colour carrier; the tile itself stays fully
    // opaque in every state.
    // Belt-and-suspenders backstop for fit/ellipsize below (§3 "never bleed
    // into a neighbour") — even if some future edit adds an unbound child,
    // it cannot paint outside this tile's own rectangle.
    clip: true

    Behavior on border.color { ColorAnimation { duration: Theme.transitionMs } }

    HoverHandler { id: hoverHandler }

    // Specular top edge (round-2 material pass): the artifact's
    // `inset 0 1px 0 var(--specular)` machined-edge highlight, drawn as a
    // real 1px translucent line just inside the border (QML can composite
    // true alpha, unlike the QSS side's border-top-color approximation).
    // Inset from the corners by ~the corner radius so it never crosses the
    // rounded arc. Static — not an effect, nothing animates.
    Rectangle {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: 1
        anchors.leftMargin: root.radius
        anchors.rightMargin: root.radius
        height: 1
        color: Theme.specular
    }

    // Accent bar, inset from the top/bottom edges so the tile's corner
    // radius stays clean (draft defect #5).
    Rectangle {
        width: 3
        radius: 1.5
        color: root.accent
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.topMargin: 6
        anchors.bottomMargin: 6
        anchors.leftMargin: 2

        Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
    }

    Column {
        id: body
        anchors.fill: parent
        anchors.margins: Theme.spaceSm
        anchors.leftMargin: Theme.spaceSm + 6   // clear the accent bar
        spacing: 4

        Row {
            id: titleRow
            width: parent.width
            spacing: 4

            Text {
                id: titleText
                objectName: "tileTitle"
                text: root.title
                // Leaves room for `tileStaleMark` only while it is actually
                // shown — a Row does not shrink its children itself, so an
                // unconditional full-width title would let the marker
                // overflow the tile when both are present.
                width: root.stale
                    ? Math.max(0, titleRow.width - staleMark.implicitWidth - titleRow.spacing)
                    : titleRow.width
                elide: Text.ElideRight
                // Metric-label role (§3): tiny tracked MONO uppercase engraving —
                // same constants the QSS QLabel#readoutCellTitle rule reads, so
                // strip tiles and panel tiles carry one label voice.
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fontMetricLabel
                font.weight: Font.DemiBold
                font.letterSpacing: Theme.trackingMetricLabel
                // repo convention (ReadoutCell/MetricTile title.upper()) rather
                // than the draft's SmallCaps.
                font.capitalization: Font.AllUppercase
                color: Theme.muted

                Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
            }

            Text {
                id: staleMark
                objectName: "tileStaleMark"
                visible: root.stale
                // Non-colour carrier for staleness (item 10 above / Baldr
                // BLOCKER-1): ink swaps (this row's title stays `muted`
                // always; the value/meter Text below swap text->muted) can
                // never be the ONLY channel per WCAG SC 1.4.1. Unconditional
                // (not gated on `compact`) so every tile — including the
                // strip's compact Position tile, whose caption is hidden —
                // still visibly reads as stale without colour perception.
                text: "STALE"
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fontMetricLabel
                font.weight: Font.DemiBold
                font.letterSpacing: Theme.trackingMetricLabel
                color: Theme.muted
            }
        }

        Row {
            id: valueRow
            width: parent.width
            spacing: 4
            Text {
                id: valueLabel
                objectName: "tileValue"
                text: root.value
                // Hero-value role (§3): "primary values mono 24-28 px w600
                // tabular" — the round-1 proportional DemiBold was the
                // single biggest type mismatch vs both the artifact
                // (`.tile .val` mono tabular) and the QWidget-kit tile
                // (QLabel#readoutCellValue, MONO_FAMILY). fontValueCompact
                // is both the compact size and the HorizontalFit floor.
                font.family: Theme.monoFamily
                font.pixelSize: root.compact ? Theme.fontValueCompact : Theme.fontValue
                font.weight: Font.DemiBold
                color: root.stale ? Theme.muted : Theme.text
                // Bounded to the row minus the unit label's own width (when
                // shown) so a long value shrinks/elides instead of pushing
                // the unit off the tile or bleeding past it (§3).
                width: unitLabel.visible
                    ? valueRow.width - unitLabel.implicitWidth - valueRow.spacing
                    : valueRow.width
                elide: Text.ElideRight
                fontSizeMode: Text.HorizontalFit
                minimumPixelSize: Theme.fontValueCompact

                Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
            }
            Text {
                id: unitLabel
                objectName: "tileUnit"
                text: root.unit
                visible: root.unit.length > 0
                // Unit role (§3): "units 11-12 px muted" — subordinated to
                // the value, never the value's own size/ink.
                font.pixelSize: Theme.fontUnit
                color: root.stale ? Theme.muted : Theme.muted
                anchors.baseline: valueLabel.baseline
            }
        }

        Text {
            objectName: "tileCaption"
            visible: !root.compact && root.caption.length > 0
            text: root.caption
            font.pixelSize: Theme.fontXs
            // Caption ink steps DOWN from the (muted) label — faint, like the
            // artifact's `.tile .cap` and the QSS metricTileCaption rule.
            color: Theme.muted
            elide: Text.ElideRight
            width: parent.width
        }

        // Thin progress meter (defect #9 above) — a static track + a fill
        // that eases its width on change, never on its own.
        Rectangle {
            objectName: "tileMeter"
            visible: root.meterFraction >= 0
            width: parent.width
            height: 2
            radius: 1
            color: Theme.hairline

            Rectangle {
                objectName: "tileMeterFill"
                height: parent.height
                radius: parent.radius
                color: root.stale ? Theme.muted : root.accent
                width: parent.width * Math.max(0, Math.min(1, root.meterFraction))

                Behavior on width { NumberAnimation { duration: Theme.transitionMs } }
                Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
            }
        }
    }
}
