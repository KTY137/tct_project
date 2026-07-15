// MetricTile — kit rework of the shipped gui/qml/MetricTile.qml (U2.2, kit_
// spec_v1.md §3 MetricTile row). Same property surface, same objectNames, so
// gui/qml/ScanStatusStrip.qml's rebind (kit_spec_v1.md §3, this beat) and its
// existing test suite (tests/test_qml_scan_status.py) need zero changes to
// what they bind/assert — only WHICH file they resolve `MetricTile` from.
//
// What the kit rework buys: hover/press/border/shadow/focus-ring material
// response now come from Surface (rung: Tile) instead of this file hand-
// rolling its own HoverHandler + declarative border-lighten (the exact
// duplication the kit exists to remove) — "components don't own paint; the
// material does."
//
// Carried over UNCHANGED (the ratified MetricTile law, kit_spec_v1.md §2.6
// stale row / §3 MetricTile row):
//   * stale is INK-ONLY, never an opacity dim — this Surface stays fully
//     opaque in every state (no `opacity:` binding here at all); the value/
//     meter Text swap ink to `muted` instead (Baldr BLOCKER-1, ruling 2).
//   * the unconditional `tileStaleMark` ("STALE") text carrier — ink alone
//     is never a legal sole channel (WCAG SC 1.4.1); shown regardless of
//     `compact` (compact only hides the OTHER redundant channel, caption).
//   * fit/ellipsize: value/title/caption each bound to a real finite width
//     with `elide: Text.ElideRight`; the value additionally shrinks first
//     via `fontSizeMode: Text.HorizontalFit` before eliding (a tile can
//     never bleed into a neighbour).
//   * the optional thin progress meter (merged Progress·ETA strip tile).
//
// Leaf component: no nested/externally-supplied content, so everything is
// added via the explicit `data: [...]` list — Surface's own `content`
// default property is simply never touched (nothing to route into it).
import QtQuick
import Tct

Surface {
    id: root
    objectName: "kitMetricTile"
    rung: Surface.Tile

    property string title: ""
    property string value: ""
    property string unit: ""
    property string caption: ""
    property color accent: Theme.muted
    property bool stale: false
    property bool compact: false
    // -1 (default) hides the meter; any 0..1 value shows it (clamped so a
    // caller's rounding/timing glitch can never paint a bar past the tile).
    property real meterFraction: -1

    implicitWidth: 180
    implicitHeight: compact ? 64 : 96

    data: [
        // Accent bar, inset from the top/bottom edges so the tile's own
        // corner radius stays clean (parity with the pre-kit file).
        Rectangle {
            objectName: "tileAccentBar"
            width: 3
            radius: 1.5
            color: root.accent
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.topMargin: Theme.spaceXs + 2
            anchors.bottomMargin: Theme.spaceXs + 2
            anchors.left: parent.left
            anchors.leftMargin: 2
            Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
        },

        Column {
            id: body
            objectName: "tileBody"
            anchors.fill: parent
            anchors.margins: Theme.spaceSm
            anchors.leftMargin: Theme.spaceSm + 6   // clear the accent bar
            spacing: 4
            // Belt-and-suspenders backstop (§3 "never bleed into a
            // neighbour") on top of the per-Text elide/fit below.
            clip: true

            Row {
                id: titleRow
                width: parent.width
                spacing: 4

                Text {
                    id: titleText
                    objectName: "tileTitle"
                    text: root.title
                    // Leaves room for `tileStaleMark` only while it is
                    // actually shown.
                    width: root.stale
                        ? Math.max(0, titleRow.width - staleMark.implicitWidth - titleRow.spacing)
                        : titleRow.width
                    elide: Text.ElideRight
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.fontMetricLabel
                    font.weight: Theme.weightMetricLabel
                    font.letterSpacing: Theme.trackingMetricLabel
                    font.capitalization: Font.AllUppercase
                    color: Theme.muted
                    Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
                }

                Text {
                    id: staleMark
                    objectName: "tileStaleMark"
                    visible: root.stale
                    // Non-colour carrier for staleness — unconditional (not
                    // gated on `compact`) so every tile, including a compact
                    // tile whose caption is hidden, still visibly reads as
                    // stale without colour perception.
                    text: "STALE"
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.fontMetricLabel
                    font.weight: Theme.weightMetricLabel
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
                    font.family: Theme.monoFamily
                    font.pixelSize: root.compact ? Theme.fontValueCompact : Theme.fontValue
                    font.weight: Theme.weightValue
                    color: root.stale ? Theme.muted : Theme.text
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
                    font.pixelSize: Theme.fontUnit
                    color: Theme.muted
                    anchors.baseline: valueLabel.baseline
                }
            }

            Text {
                objectName: "tileCaption"
                visible: !root.compact && root.caption.length > 0
                text: root.caption
                font.pixelSize: Theme.fontXs
                color: Theme.muted
                elide: Text.ElideRight
                width: parent.width
            }

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
    ]
}
