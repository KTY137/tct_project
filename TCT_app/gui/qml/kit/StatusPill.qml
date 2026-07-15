// StatusPill — lamp + WORD pill (kit_spec_v1.md §3 StatusPill row: "glyph +
// WORD + colour, `chip` fill — never colour alone"; motion: width change
// springs `motionSpringUi`). QML counterpart of
// gui/status_widgets.py::StatusPill, rebuilt on the kit material instead of
// its own QFrame/QSS.
//
// State vocabulary mirrors gui/status_widgets.py::normalize_state's
// canonical set (neutral/disconnected/unknown/good/warn/crit/armed/fault/
// info/busy/simulated) — the same dot-colour ternary already shipped in
// gui/qml/Shell.qml's StatChip component (Theme-token-only, no hex; not
// re-derived here, just the same mapping restated for this pill's own glyph
// dot so the two chip families read as ONE colour language).
//
// SURFACE KNOB GAP (reported per this beat's brief — no Surface.qml edit
// made): the ladder (§2.2) fixes Tile rung's opaque fill to `raised`, but
// this row's obligation is a fixed `chip` fill regardless of state. Surface
// has no override for its own resolved fill TOKEN (only the tri-state
// glass/shadow/halo response overrides, §2.1) — a fill-token override (or a
// dedicated Chip/Pill rung) is the missing knob. Interim fix: `chipFill`
// below paints `Theme.chip` INSIDE the content slot, on top of Surface's own
// (otherwise-correct) Tile fill — shadow/border/hover/focus-ring mechanics
// still resolve from Surface untouched; only the visible base tone is
// re-painted. Flagged for Adam/a future Surface amendment, never worked
// around by editing Surface.qml directly.
import QtQuick
import Tct

Surface {
    id: root
    objectName: "kitStatusPill"
    rung: Surface.Tile

    property string text: ""
    property string state: "neutral"

    function _dotColor(s) {
        return s === "good" ? Theme.good
             : (s === "warn" || s === "armed") ? Theme.warn
             : (s === "crit" || s === "fault") ? Theme.crit
             : (s === "busy" || s === "info") ? Theme.accent
             : s === "simulated" ? Theme.sim
             : Theme.muted
    }

    // Hit target law (§2.6): interactive surfaces >= 36 px. StatusPill is a
    // read-only status readout (not a command control), but the floor still
    // applies to any focusable/interactive instance a future caller makes.
    implicitHeight: Math.max(Theme.fontMetricLabel + 2 * (Theme.spaceXs + 2), 36)
    // Bound directly off `dot`/`wordText`'s own implicit sizes rather than
    // `pillRow.implicitWidth` — a Row's OWN implicit-size recompute is
    // scheduled through its positioner polish cycle (driven by the hosting
    // window's render loop), so depending on it here would leave this
    // Surface's implicitWidth a frame late off-window (never a visible
    // issue under the app's real QQuickWidget render loop, but needlessly
    // indirect); `Text.implicitWidth` recomputes immediately on content
    // change, so binding through it keeps this reactive with no extra hop.
    implicitWidth: dot.width + pillRow.spacing + wordText.implicitWidth
        + 2 * (Theme.spaceSm + 2)

    // Motion obligation (§3 StatusPill row): width change springs, the same
    // spring identity as CollapsibleCard unfold / SegmentedControl thumb.
    Behavior on implicitWidth {
        id: widthSpringBehavior
        objectName: "statusPillWidthSpring"
        enabled: Theme.motionEnabled
        SpringAnimation {
            objectName: "statusPillWidthSpringAnimation"
            spring: Theme.motionSpringUi.spring
            damping: Theme.motionSpringUi.damping
        }
    }

    data: [
        // See the SURFACE KNOB GAP note above.
        Rectangle {
            objectName: "statusPillChipFill"
            anchors.fill: parent
            radius: root.radiusPx
            color: Theme.chip
        },

        Row {
            id: pillRow
            objectName: "statusPillRow"
            anchors.centerIn: parent
            spacing: Theme.spaceXs + 2

            Rectangle {
                id: dot
                objectName: "statusPillGlyph"
                width: 8
                height: 8
                radius: 4
                anchors.verticalCenter: parent.verticalCenter
                color: root._dotColor(root.state)
                Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
            }
            Text {
                id: wordText
                objectName: "statusPillWord"
                text: root.text
                anchors.verticalCenter: parent.verticalCenter
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fontXs
                font.weight: Theme.weightMetricLabel
                color: Theme.text
            }
        }
    ]
}
