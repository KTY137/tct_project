// TCT QML chrome shell (slice 1, compressed rail — slice 2a): a calm material
// rail + a pill tab shelf.
//
// This is a VIEW only — it renders cached state and forwards intent:
//   * every colour/size binds the `Theme` singleton (gui/qml_theme.py, fed from
//     gui/style.py) — ZERO inline hex here (the no-inline-hex rule extends to
//     .qml; only named colours like "transparent" appear);
//   * device dots + HV/Motion/Scan/Laser/Scope/State readouts bind `shell`/
//     `scopeVm` (gui/qml_shell.py) which mirror the SAME cached state the
//     classic ribbon shows — no hardware I/O here;
//   * the pill shelf binds `tabShelf`, an adapter over the real
//     DetachableTabWidget: a click sets the current index, the ⧉ glyph tears the
//     tab into a floating window — the widget stays the tab/detach engine.
//
// Rail composition (slice 2a — kills the horizontal-scroll TECH_DEBT item): the
// rail's content is compressed to fit >=1280px windows with NO Flickable/
// horizontal scroll — a rail you have to scroll to find Settings was a
// composition failure. Device status is a compact DOT ROW (no per-device
// labels — the name+state lives in a hover tooltip); the HV/Motion/Scan/Laser/
// Scope/State readouts are short right-weighted VALUE-ONLY chips (the label
// lives in a hover tooltip, via the StatChip component below); the
// Devices/Settings/Log/Debug cluster (plus the theme toggle) is ICON-ONLY
// buttons with hover tooltips (IconButton component). Connect All/Disconnect
// All stay labelled — they are the primary, dangerous-adjacent actions per the
// audit's hierarchy: one calm rail, brand left, actions center-left, status
// right. Measured implicit width comfortably clears 1280px (see
// tests/test_qml_shell.py's rail-fits-1280 check) so the overflow-menu escape
// valve described in the task brief was not needed.
//
// No QtQuick.Effects / MultiEffect: the rail is a flat material (calm depth),
// which also keeps it correct headless (software renderer) and off the
// glow/hot-path-effect rule.
//
// Between the rail and the pill shelf sits the sim ribbon (law 6 — visible
// only while >=1 device is simulated); below the pill shelf sits a third,
// persistent strip: ScanStatusStrip (gui/qml/ScanStatusStrip.qml), a row of
// MetricTiles (gui/qml/MetricTile.qml) bound to the read-only `runState`
// facade (gui/run_state_viewmodel.py) for run/scan state and `shell` for the
// HV tile's cached bias readout — both already QML context properties in
// both shells (see tct_gui.py's `_run_vm` wiring / qml_shell.py's
// `build_qml_chrome`). Pure view, per those files' own header notes — no
// logic lives here either.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Tct

Item {
    id: root
    implicitWidth: 960
    // Height mirrors mainColumn's own implicitHeight (rail 48 + sim ribbon
    // 0/26 (visible only when >=1 device is simulated) + pill shelf 44 +
    // scan status strip 112 = 204 baseline, +26 with the ribbon showing) —
    // computed, not a hardcoded magic number, so it stays honest as rows are
    // added/resized. NOT load-bearing on the Python side any more (unlike
    // the pre-D2 constant this replaced): SizeRootObjectToView means the
    // widget's own size still drives this item's actual `height`, and
    // gui/qml_shell.py::build_qml_chrome sizes the QQuickWidget itself from
    // ``bridge.hasSimulated`` (the same cached device list this ribbon
    // renders from) rather than reading this property back — see that
    // file's docstring.
    implicitHeight: mainColumn.implicitHeight

    // Sim-ribbon derivation (law 6) — computed straight from the SAME
    // `shell.devicesModel` the rail's device dots already bind (no new
    // Python field: presentation-only filtering of already-cached state).
    readonly property var simNames: {
        var out = []
        var list = shell ? shell.devicesModel : []
        for (var i = 0; i < list.length; i++) {
            if (list[i][1] === "sim") out.push(list[i][0])
        }
        return out
    }
    readonly property int simCount: simNames.length
    readonly property int totalCount: shell ? shell.devicesModel.length : 0

    Rectangle { anchors.fill: parent; color: Theme.canvas }

    ColumnLayout {
        id: mainColumn
        anchors.fill: parent
        spacing: 0

        // ------------------------------------------------------------- rail
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 48
            // "One frosted chrome strip" (spec §2): Theme.chrome is the
            // solid color-mix fallback for the artifact topbar's backdrop
            // blur (translucency over a live camera/plot is banned anyway).
            color: Theme.chrome

            Rectangle {  // specular top edge — machined-chrome highlight
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: 1; color: Theme.specular
            }

            Rectangle {  // bottom hairline
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 1; color: Theme.hairline
            }

            // No Flickable: the whole cluster below is sized to fit inside a
            // >=1280px window (see the header note) — every affordance stays
            // visible and reachable in ONE view, never behind a scroll.
            RowLayout {
                id: railRow
                objectName: "railRow"
                anchors.fill: parent
                anchors.leftMargin: 16; anchors.rightMargin: 16
                spacing: 14

                // wordmark
                Row {
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 8
                    Rectangle {
                        width: 18; height: 18; radius: 5; color: Theme.accent
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            anchors.centerIn: parent; text: "T"; color: Theme.onAccent
                            font.pixelSize: 10; font.bold: true
                        }
                    }
                    Text {
                        text: "TCT Control"; color: Theme.text
                        font.pixelSize: Theme.fontSm; font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                Rectangle { Layout.alignment: Qt.AlignVCenter; width: 1; height: 20; color: Theme.hairline }

                // connect / disconnect (route to the same window handlers) —
                // the primary, dangerous-adjacent actions: stay labelled.
                ShellButton {
                    Layout.alignment: Qt.AlignVCenter
                    text: "Connect All"; tone: "accent"       // primary-quiet
                    onClicked: shell.connectAll()
                }
                ShellButton {
                    Layout.alignment: Qt.AlignVCenter
                    // Command classes (cockpit_design_system.md §1 law 2):
                    // red is reserved for HV energization/trips/Abort. A bulk
                    // disconnect is a neutral, safe action — never red.
                    text: "Disconnect All"; tone: "quiet"
                    onClicked: shell.disconnectAll()
                }

                Rectangle { Layout.alignment: Qt.AlignVCenter; width: 1; height: 20; color: Theme.hairline }

                // device status — a compact dot row (cached device state); the
                // device name + state lives in a hover tooltip, not a label.
                // 4-state per council_v5_paul.md §1 state taxonomy (state-
                // color census D4 rank-1 fix — real-connected used to be a
                // solid GOOD/green dot, a green-on-nominal violation of law
                // 1/6): real-connected (solid MUTED — IDLE-nominal, quiet,
                // no colour) / simulated (a hatched-cyan RING — never a
                // solid cyan fill, so it can never be mistaken for "good" at
                // a glance — law 6) / disconnected (faint hollow ring) /
                // fault (solid red — attempted-and-failed, from the last
                // connect_all() result; distinct from a plain never-attempted
                // disconnect — see tct_gui._collect_shell_state).
                Row {
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 8
                    Repeater {
                        model: shell.devicesModel
                        Rectangle {
                            id: deviceDot
                            readonly property string st: modelData[1]
                            width: 8; height: 8; radius: 4
                            anchors.verticalCenter: parent.verticalCenter
                            color: st === "on" ? Theme.muted
                                 : st === "fault" ? Theme.crit : "transparent"
                            border.width: st === "sim" ? 1.6 : (st === "off" ? 1 : 0)
                            border.color: st === "sim" ? Theme.sim : Theme.faint

                            HoverHandler { id: deviceHover }
                            ToolTip.visible: deviceHover.hovered
                            ToolTip.delay: 350
                            ToolTip.text: modelData[0] + " — " + st
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                // right-side status readouts (cached) — value-only chips; the
                // label lives in each chip's hover tooltip.
                Row {
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 14
                    StatChip { lab: "HV"; val: shell.hvText; state: shell.hvState }
                    StatChip { lab: "Motion"; val: shell.motionText; state: shell.motionState }
                    StatChip { lab: "Scan"; val: shell.scanText; state: shell.scanState }
                    StatChip { lab: "Laser"; val: shell.laserText; state: shell.laserState }
                    StatChip {
                        lab: "Scope"; val: scopeVm.statusText
                        // State-color census D4 rank-1 fix: a connected-but-
                        // idle scope is IDLE-nominal (law 1: quiet, never a
                        // green "good"), not ACTIVE·benign -- that accent
                        // fill is reserved for a genuinely live acquisition
                        // (the "busy" branch above).
                        state: scopeVm.acquiring ? "busy"
                             : (scopeVm.connected ? "neutral" : "disconnected")
                    }
                    // The toolbar's app-state readout, re-exposed here since the
                    // classic toolbar is hidden in QML mode (tct_gui._build_central).
                    // Readiness ladder (design system §5/§6 — "say WHY Start is
                    // disabled") lives in this chip's tooltip: shell.appReadiness
                    // is "" once RUNNING/PAUSED/terminal (tct_gui._readiness_
                    // caption), in which case the tooltip falls back to the
                    // plain "State" label like every other chip.
                    StatChip {
                        lab: "State"; val: shell.appText; state: shell.appState
                        tip: shell.appReadiness.length > 0
                             ? ("State — " + shell.appReadiness) : ""
                    }
                }

                Rectangle { Layout.alignment: Qt.AlignVCenter; width: 1; height: 20; color: Theme.hairline }

                // Non-duplicated toolbar affordances, re-exposed as a compact
                // icon-only cluster routed to the SAME existing window handlers
                // (the classic toolbar is hidden in QML mode — see
                // build_qml_chrome). Each button's label lives in its tooltip.
                Row {
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 4
                    IconButton {
                        glyph: "🖥"  // 🖥 desktop computer — Devices
                        tip: "Devices"
                        onClicked: shell.openDeviceManager()
                    }
                    IconButton {
                        glyph: "⚙"  // ⚙ gear — Settings
                        tip: "Settings"
                        onClicked: shell.openSettings()
                    }
                    IconButton {
                        glyph: "≡"  // ≡ identical-to (list) — Log
                        tone: shell.logVisible ? "accent" : "quiet"
                        tip: "Log"
                        onClicked: shell.toggleLog()
                    }
                    IconButton {
                        glyph: "⚠"  // ⚠ warning sign — Device Debug
                        tone: shell.debugVisible ? "accent" : "quiet"
                        tip: "Device Debug"
                        onClicked: shell.toggleDeviceDebug()
                    }
                }

                Rectangle { Layout.alignment: Qt.AlignVCenter; width: 1; height: 20; color: Theme.hairline }

                // theme toggle (routes to the same window handler)
                IconButton {
                    Layout.alignment: Qt.AlignVCenter
                    glyph: Theme.dark ? "☀" : "🌙"  // ☀ sun : 🌙 crescent moon
                    tip: Theme.dark ? "Switch to light theme" : "Switch to dark theme"
                    onClicked: shell.toggleTheme()
                }
            }   // end railRow (RowLayout)
        }

        // ------------------------------------------------------ sim ribbon
        // Law 6 ("simulation can never pass as real"): a thin persistent
        // strip, visible only while >=1 named device is simulated, naming
        // which ones — cached from the SAME `shell.devicesModel` the rail's
        // device dots already render (no new poll). `visible: false` makes
        // ColumnLayout skip this row entirely in its height sum, so the
        // ribbon truly disappears (not just an empty gap) when nothing is
        // simulated.
        Rectangle {
            id: simRibbon
            objectName: "simRibbon"
            Layout.fillWidth: true
            implicitHeight: 26
            visible: root.simCount > 0
            // The classic-shell "cheap hatch approximation" (gui/style.py:
            // a soft tinted fill, never a solid one) plus an actual diagonal
            // stripe texture via Canvas — a static, one-shot paint (redrawn
            // only on resize/theme change, never per-frame), so this stays
            // inside the "no glow/animated effect" rule (law 8: nothing
            // decorative MOVES; this doesn't).
            color: Qt.rgba(Theme.sim.r, Theme.sim.g, Theme.sim.b, 0.08)

            Canvas {
                id: hatchCanvas
                anchors.fill: parent
                // Default (Canvas.Image, a CPU QImage backend) rather than
                // FramebufferObject — this repaints rarely (resize/theme
                // toggle only) and Image is the reliable choice under a
                // software/offscreen scene graph (the test harness's mode),
                // with no dependency on a working GL context.
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    ctx.strokeStyle = Theme.sim
                    ctx.globalAlpha = 0.30
                    ctx.lineWidth = 5
                    var step = 14
                    for (var x = -height; x < width + height; x += step) {
                        ctx.beginPath()
                        ctx.moveTo(x, height)
                        ctx.lineTo(x + height, 0)
                        ctx.stroke()
                    }
                }
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
                Connections {
                    target: Theme
                    function onChanged() { hatchCanvas.requestPaint() }
                }
            }

            Rectangle {  // bottom hairline
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 1; color: Theme.hairline
            }

            Text {
                objectName: "simRibbonText"
                anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
                text: "SIMULATION — " + root.simCount + " of " + root.totalCount
                    + " devices simulated (" + root.simNames.join(", ") + ")"
                    + " · no hardware driven"
                color: Theme.sim
                // Mono + a touch of tracking, per the artifact's .simribbon
                // (mono 10.5px, letter-spacing .05em).
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fontXs
                font.letterSpacing: 0.5
                elide: Text.ElideRight
                width: parent.width - 32
            }
        }

        // ------------------------------------------------------- pill shelf
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 44
            color: Theme.canvas

            Flickable {
                anchors.fill: parent
                contentWidth: tabRow.width; clip: true
                Row {
                    id: tabRow
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4; leftPadding: 14; rightPadding: 14
                    Repeater {
                        model: tabShelf.titles
                        Rectangle {
                            id: pillCell
                            property bool active: index === tabShelf.currentIndex
                            // Artifact `.pill[aria-selected]` (law 1): the
                            // ACTIVE tab is a neutral RAISED pill — a place,
                            // not a state — never accent-tinted.
                            // HOVER (regression triage 2026-07-12): with the
                            // native QTabBar hidden this shelf is the app's
                            // tab bar, so non-active pills carry a calm field
                            // wash + hairline ring on hover — what's
                            // interactive must look interactive. Chrome-only
                            // animation (never a hot-path widget).
                            radius: Theme.radiusSm; height: 30
                            width: pillRow.implicitWidth + 26
                            color: active ? Theme.raised
                                 : pillArea.containsMouse ? Theme.field
                                 : "transparent"
                            border.width: (active || pillArea.containsMouse) ? 1 : 0
                            border.color: active ? Theme.hairlineStrong : Theme.hairline
                            Behavior on color { ColorAnimation { duration: Theme.transitionMs } }

                            MouseArea {
                                id: pillArea
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: tabShelf.setCurrentIndex(index)
                            }
                            Row {
                                id: pillRow
                                anchors.centerIn: parent
                                spacing: 6
                                Text {
                                    text: modelData
                                    font.pixelSize: Theme.fontSm
                                    font.weight: pillCell.active ? Font.DemiBold : Font.Medium
                                    color: (pillCell.active || pillArea.containsMouse)
                                         ? Theme.text : Theme.muted
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                // detach affordance on the active pill
                                Text {
                                    visible: pillCell.active
                                    text: "⧉"
                                    color: Theme.accent
                                    font.pixelSize: Theme.fontSm
                                    anchors.verticalCenter: parent.verticalCenter
                                    MouseArea {
                                        anchors.fill: parent; anchors.margins: -4
                                        onClicked: tabShelf.detach(index)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {  // bottom hairline
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 1; color: Theme.hairline
            }
        }

        // ------------------------------------------------- scan status strip
        // Persistent live readout — State / HV·measured / Progress·ETA
        // (merged, with meter) / Position (compact) — see the file header
        // above and gui/qml/ScanStatusStrip.qml (design system §5's strip
        // hierarchy). Sized to the same >=1280px baseline the rail's
        // no-Flickable contract targets (4 tiles fit one row well under that
        // width); binds ONLY, no logic.
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: statusStrip.implicitHeight + 2 * Theme.spaceSm
            // Recessed wash (artifact `.statusstrip`: color-mix(sunk 55%,
            // panel)) so the tiles read as raised cards sitting IN a tray —
            // the surface-ladder step round 1 flattened onto plain canvas.
            color: Theme.strip

            ScanStatusStrip {
                id: statusStrip
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.topMargin: Theme.spaceSm
                anchors.leftMargin: 16
                anchors.rightMargin: 16
            }

            Rectangle {  // bottom hairline — separates chrome from tab content
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 1; color: Theme.hairline
            }
        }
    }

    // ---- inline components ---------------------------------------------
    component ShellButton: Rectangle {
        property alias text: btnLabel.text
        property string tone: "quiet"          // "accent" | "danger" | "quiet"
        signal clicked()
        radius: Theme.radiusSm; implicitHeight: 28; implicitWidth: btnLabel.implicitWidth + 24
        // Hover = raised wash (+ hairline-strong ring on quiet tone) — calm,
        // token-only, chrome-only (regression triage 2026-07-12).
        color: btnArea.pressed ? Theme.field
             : btnArea.containsMouse ? Theme.raised : "transparent"
        border.width: 1
        border.color: tone === "danger" ? Theme.crit
                    : tone === "accent" ? Theme.accent
                    : btnArea.containsMouse ? Theme.hairlineStrong : Theme.hairline
        Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
        Text {
            id: btnLabel; anchors.centerIn: parent
            font.pixelSize: Theme.fontSm; font.weight: Font.Medium
            color: tone === "danger" ? Theme.crit
                 : tone === "accent" ? Theme.accent : Theme.text
        }
        MouseArea {
            id: btnArea; anchors.fill: parent; hoverEnabled: true
            onClicked: parent.clicked()
        }
    }

    // Icon-only affordance: a unicode glyph + a hover tooltip carrying the
    // label (used by the Devices/Settings/Log/Debug cluster and the theme
    // toggle — the compact replacement for a labelled ShellButton).
    component IconButton: Rectangle {
        id: iconBtn
        property alias glyph: iconLabel.text
        property string tone: "quiet"          // "accent" | "danger" | "quiet"
        property string tip: ""
        signal clicked()
        radius: Theme.radiusSm; implicitHeight: 28; implicitWidth: 28
        // Same calm hover recipe as ShellButton (iconArea already tracks
        // hover for its tooltip).
        color: iconArea.pressed ? Theme.field
             : iconArea.containsMouse ? Theme.raised : "transparent"
        border.width: 1
        border.color: tone === "danger" ? Theme.crit
                    : tone === "accent" ? Theme.accent
                    : iconArea.containsMouse ? Theme.hairlineStrong : Theme.hairline
        Behavior on color { ColorAnimation { duration: Theme.transitionMs } }
        Text {
            id: iconLabel; anchors.centerIn: parent
            font.pixelSize: Theme.fontMd
            color: tone === "danger" ? Theme.crit
                 : tone === "accent" ? Theme.accent : Theme.text
        }
        MouseArea {
            id: iconArea; anchors.fill: parent; hoverEnabled: true
            onClicked: iconBtn.clicked()
        }
        ToolTip.visible: iconArea.containsMouse
        ToolTip.delay: 300
        ToolTip.text: iconBtn.tip
    }

    // Compact right-side readout: a state dot + the VALUE only. The label
    // (e.g. "HV", "Motion") lives in a hover tooltip instead of a second
    // visible Text, so six readouts fit the rail without a scroll.
    component StatChip: Row {
        id: chipRoot
        property string lab
        property string val
        property string state: "neutral"
        // Optional tooltip override (e.g. the State chip's readiness ladder);
        // empty (the default) falls back to the plain label every other chip
        // shows.
        property string tip: ""
        spacing: 5

        // Cached readout values already carry their own label as a prefix
        // (e.g. "HV +12.3 V", "State: CONNECTED" — the same strings the
        // classic ribbon/toolbar chips show). A value-only chip re-shows
        // that prefix, so trim it here for display; the untrimmed value is
        // preserved in gui/qml_shell.py — this is display-only shortening in
        // the view layer, not a new value.
        function trimmed() {
            var spacePrefix = lab + " "
            if (val.indexOf(spacePrefix) === 0) return val.substring(spacePrefix.length)
            var colonPrefix = lab + ": "
            if (val.indexOf(colonPrefix) === 0) return val.substring(colonPrefix.length)
            return val
        }

        Rectangle {
            width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter
            color: state === "good" ? Theme.good
                 : (state === "warn" || state === "armed") ? Theme.warn
                 : state === "crit" ? Theme.crit
                 : (state === "busy" || state === "info") ? Theme.accent
                 : state === "simulated" ? Theme.sim : Theme.faint
        }
        Text {
            text: chipRoot.trimmed(); color: Theme.text
            // Chip values are physical quantities/state words — mono, like
            // the artifact's `.chip` (law 3: numbers are mono).
            font.family: Theme.monoFamily
            font.pixelSize: Theme.fontXs
            anchors.verticalCenter: parent.verticalCenter
        }

        HoverHandler { id: chipHover }
        ToolTip.visible: chipHover.hovered
        ToolTip.delay: 350
        ToolTip.text: chipRoot.tip.length > 0 ? chipRoot.tip : chipRoot.lab
    }
}
