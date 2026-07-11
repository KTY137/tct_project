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
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Tct

Item {
    id: root
    implicitWidth: 960
    implicitHeight: 96

    Rectangle { anchors.fill: parent; color: Theme.canvas }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ------------------------------------------------------------- rail
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 48
            color: Theme.material

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
                    text: "Connect All"; tone: "accent"
                    onClicked: shell.connectAll()
                }
                ShellButton {
                    Layout.alignment: Qt.AlignVCenter
                    text: "Disconnect All"; tone: "danger"
                    onClicked: shell.disconnectAll()
                }

                Rectangle { Layout.alignment: Qt.AlignVCenter; width: 1; height: 20; color: Theme.hairline }

                // device status — a compact dot row (cached device state); the
                // device name + state lives in a hover tooltip, not a label.
                Row {
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 8
                    Repeater {
                        model: shell.devicesModel
                        Rectangle {
                            id: deviceDot
                            width: 8; height: 8; radius: 4
                            anchors.verticalCenter: parent.verticalCenter
                            color: modelData[1] === "on" ? Theme.good
                                 : modelData[1] === "sim" ? Theme.sim : "transparent"
                            border.width: modelData[1] === "off" ? 1 : 0
                            border.color: Theme.faint

                            HoverHandler { id: deviceHover }
                            ToolTip.visible: deviceHover.hovered
                            ToolTip.delay: 350
                            ToolTip.text: modelData[0] + " — " + modelData[1]
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
                        state: scopeVm.acquiring ? "busy" : (scopeVm.connected ? "good" : "neutral")
                    }
                    // The toolbar's app-state readout, re-exposed here since the
                    // classic toolbar is hidden in QML mode (tct_gui._build_central).
                    StatChip { lab: "State"; val: shell.appText; state: shell.appState }
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
                            radius: 8; height: 30
                            width: pillRow.implicitWidth + 26
                            color: active ? Theme.tint : "transparent"
                            border.width: active ? 1 : 0
                            border.color: Theme.accent

                            MouseArea {
                                anchors.fill: parent
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
                                    color: pillCell.active ? Theme.accent : Theme.muted
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
    }

    // ---- inline components ---------------------------------------------
    component ShellButton: Rectangle {
        property alias text: btnLabel.text
        property string tone: "quiet"          // "accent" | "danger" | "quiet"
        signal clicked()
        radius: 6; implicitHeight: 28; implicitWidth: btnLabel.implicitWidth + 24
        color: btnArea.pressed ? Theme.field : "transparent"
        border.width: 1
        border.color: tone === "danger" ? Theme.crit
                    : tone === "accent" ? Theme.accent : Theme.hairline
        Text {
            id: btnLabel; anchors.centerIn: parent
            font.pixelSize: Theme.fontSm; font.weight: Font.Medium
            color: tone === "danger" ? Theme.crit
                 : tone === "accent" ? Theme.accent : Theme.text
        }
        MouseArea { id: btnArea; anchors.fill: parent; onClicked: parent.clicked() }
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
        radius: 6; implicitHeight: 28; implicitWidth: 28
        color: iconArea.pressed ? Theme.field : "transparent"
        border.width: 1
        border.color: tone === "danger" ? Theme.crit
                    : tone === "accent" ? Theme.accent : Theme.hairline
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
            font.pixelSize: Theme.fontXs
            anchors.verticalCenter: parent.verticalCenter
        }

        HoverHandler { id: chipHover }
        ToolTip.visible: chipHover.hovered
        ToolTip.delay: 350
        ToolTip.text: chipRoot.lab
    }
}
