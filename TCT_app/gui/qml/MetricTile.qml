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
//      `Theme.faint` (title/value/caption), not just the pre-existing
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
    opacity: stale ? 0.6 : 1.0
    // Belt-and-suspenders backstop for fit/ellipsize below (§3 "never bleed
    // into a neighbour") — even if some future edit adds an unbound child,
    // it cannot paint outside this tile's own rectangle.
    clip: true

    Behavior on border.color { ColorAnimation { duration: Theme.transitionMs } }
    Behavior on opacity { NumberAnimation { duration: Theme.transitionMs } }

    HoverHandler { id: hoverHandler }

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

        Text {
            objectName: "tileTitle"
            text: root.title
            width: parent.width
            elide: Text.ElideRight
            font.pixelSize: Theme.fontXs
            font.weight: Font.DemiBold
            // repo convention (ReadoutCell/MetricTile title.upper()) rather
            // than the draft's SmallCaps.
            font.capitalization: Font.AllUppercase
            color: root.stale ? Theme.faint : Theme.muted

            Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
        }

        Row {
            id: valueRow
            width: parent.width
            spacing: 4
            Text {
                id: valueLabel
                objectName: "tileValue"
                text: root.value
                // fontDisplay is the repo's "hero numeric tile value" size
                // (gui/style.py FONT_DISPLAY, used by the widget-kit
                // MetricTile/ReadoutCell) — fontLg is its compact fallback,
                // and also the floor `fontSizeMode: Text.HorizontalFit`
                // shrinks toward before eliding kicks in.
                font.pixelSize: root.compact ? Theme.fontLg : Theme.fontDisplay
                font.weight: Font.DemiBold
                color: root.stale ? Theme.faint : Theme.text
                // Bounded to the row minus the unit label's own width (when
                // shown) so a long value shrinks/elides instead of pushing
                // the unit off the tile or bleeding past it (§3).
                width: unitLabel.visible
                    ? valueRow.width - unitLabel.implicitWidth - valueRow.spacing
                    : valueRow.width
                elide: Text.ElideRight
                fontSizeMode: Text.HorizontalFit
                minimumPixelSize: Theme.fontLg

                Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
            }
            Text {
                id: unitLabel
                objectName: "tileUnit"
                text: root.unit
                visible: root.unit.length > 0
                font.pixelSize: Theme.fontXs
                color: root.stale ? Theme.faint : Theme.muted
                anchors.baseline: valueLabel.baseline
            }
        }

        Text {
            objectName: "tileCaption"
            visible: !root.compact && root.caption.length > 0
            text: root.caption
            font.pixelSize: Theme.fontXs
            color: root.stale ? Theme.faint : Theme.muted
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
                color: root.stale ? Theme.faint : root.accent
                width: parent.width * Math.max(0, Math.min(1, root.meterFraction))

                Behavior on width { NumberAnimation { duration: Theme.transitionMs } }
                Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
            }
        }
    }
}
