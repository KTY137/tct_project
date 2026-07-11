// TCT QML chrome shell (slice 1): a calm material rail + a pill tab shelf.
//
// This is a VIEW only — it renders cached state and forwards intent:
//   * every colour/size binds the `Theme` singleton (gui/qml_theme.py, fed from
//     gui/style.py) — ZERO inline hex here (the no-inline-hex rule extends to
//     .qml; only named colours like "transparent" appear);
//   * device dots + HV/Motion/Scan/Laser/Scope readouts bind `shell`/`scopeVm`
//     (gui/qml_shell.py) which mirror the SAME cached state the classic ribbon
//     shows — no hardware I/O here;
//   * the pill shelf binds `tabShelf`, an adapter over the real
//     DetachableTabWidget: a click sets the current index, the ⧉ glyph tears the
//     tab into a floating window — the widget stays the tab/detach engine.
//
// No QtQuick.Effects / MultiEffect: the rail is a flat material (calm depth),
// which also keeps it correct headless (software renderer) and off the
// glow/hot-path-effect rule.
import QtQuick
import QtQuick.Layouts
import Tct

Item {
    id: root
    implicitWidth: 1040
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

            // Horizontally scrollable, same precedent as the classic ribbon
            // strip's QScrollArea (tct_gui._build_central's ``strip_scroll``):
            // the rail content can outgrow a narrow window (more readouts +
            // the Devices/Settings/Log/Debug cluster than the old 4-readout
            // rail), so every affordance stays REACHABLE (scroll) even when
            // not all simultaneously visible, instead of being silently
            // clipped off the QQuickWidget's fixed bounds.
            Flickable {
                id: railFlick
                objectName: "railFlick"
                anchors.fill: parent
                anchors.leftMargin: 16; anchors.rightMargin: 16
                clip: true
                contentWidth: railRow.width
                contentHeight: height
                boundsBehavior: Flickable.StopAtBounds

                RowLayout {
                    id: railRow
                    objectName: "railRow"
                    height: parent.height
                    // Fills the viewport when content fits (so the trailing
                    // spacer below can still push the right cluster flush to
                    // the edge); falls back to its natural minimum width —
                    // making the Flickable scrollable — when it doesn't.
                    width: Math.max(railFlick.width, implicitWidth)
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

                // connect / disconnect (route to the same window handlers)
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

                // device dots (cached device state)
                Row {
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 10
                    Repeater {
                        model: shell.devicesModel
                        Row {
                            spacing: 5
                            Rectangle {
                                width: 7; height: 7; radius: 4
                                anchors.verticalCenter: parent.verticalCenter
                                color: modelData[1] === "on" ? Theme.good
                                     : modelData[1] === "sim" ? Theme.sim : "transparent"
                                border.width: modelData[1] === "off" ? 1 : 0
                                border.color: Theme.faint
                            }
                            Text {
                                text: modelData[0]; anchors.verticalCenter: parent.verticalCenter
                                font.pixelSize: Theme.fontXs; font.weight: Font.Medium
                                color: modelData[1] === "sim" ? Theme.sim
                                     : modelData[1] === "off" ? Theme.faint : Theme.muted
                            }
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                // right-side status readouts (cached)
                StatReadout { Layout.alignment: Qt.AlignVCenter; lab: "HV"; val: shell.hvText; state: shell.hvState }
                StatReadout { Layout.alignment: Qt.AlignVCenter; lab: "Motion"; val: shell.motionText; state: shell.motionState }
                StatReadout { Layout.alignment: Qt.AlignVCenter; lab: "Scan"; val: shell.scanText; state: shell.scanState }
                StatReadout { Layout.alignment: Qt.AlignVCenter; lab: "Laser"; val: shell.laserText; state: shell.laserState }
                StatReadout {
                    Layout.alignment: Qt.AlignVCenter
                    lab: "Scope"; val: scopeVm.statusText
                    state: scopeVm.acquiring ? "busy" : (scopeVm.connected ? "good" : "neutral")
                }
                // The toolbar's app-state readout, re-exposed here since the
                // classic toolbar is hidden in QML mode (tct_gui._build_central).
                StatReadout { Layout.alignment: Qt.AlignVCenter; lab: "State"; val: shell.appText; state: shell.appState }

                Rectangle { Layout.alignment: Qt.AlignVCenter; width: 1; height: 20; color: Theme.hairline }

                // Non-duplicated toolbar affordances, re-exposed as a compact
                // cluster routed to the SAME existing window handlers (the
                // classic toolbar is hidden in QML mode — see build_qml_chrome).
                ShellButton {
                    Layout.alignment: Qt.AlignVCenter
                    text: "Devices"; tone: "quiet"
                    onClicked: shell.openDeviceManager()
                }
                ShellButton {
                    Layout.alignment: Qt.AlignVCenter
                    text: "Settings"; tone: "quiet"
                    onClicked: shell.openSettings()
                }
                ShellButton {
                    Layout.alignment: Qt.AlignVCenter
                    text: "Log"; tone: shell.logVisible ? "accent" : "quiet"
                    onClicked: shell.toggleLog()
                }
                ShellButton {
                    Layout.alignment: Qt.AlignVCenter
                    text: "Debug"; tone: shell.debugVisible ? "accent" : "quiet"
                    onClicked: shell.toggleDeviceDebug()
                }

                Rectangle { Layout.alignment: Qt.AlignVCenter; width: 1; height: 20; color: Theme.hairline }

                // theme toggle (routes to the same window handler)
                ShellButton {
                    Layout.alignment: Qt.AlignVCenter
                    text: Theme.dark ? "Light" : "Dark"; tone: "quiet"
                    onClicked: shell.toggleTheme()
                }
                }   // end railRow (RowLayout)
            }       // end railFlick (Flickable)
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

    component StatReadout: Row {
        property string lab
        property string val
        property string state: "neutral"
        spacing: 5
        Rectangle {
            width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter
            color: state === "good" ? Theme.good
                 : (state === "warn" || state === "armed") ? Theme.warn
                 : state === "crit" ? Theme.crit
                 : (state === "busy" || state === "info") ? Theme.accent
                 : state === "simulated" ? Theme.sim : Theme.faint
        }
        Text {
            text: lab; color: Theme.faint
            font.pixelSize: Theme.fontXs; font.weight: Font.Medium
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: val; color: Theme.text; font.pixelSize: Theme.fontXs
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
