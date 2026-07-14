// THE GLASS SHELL — a walking skeleton of the full-QML cockpit.
//
// This is the ROOT ITEM of a real, translucent QQuickWindow (scripts/
// glass_shell_preview.py hosts it in a QQuickView). That is the whole point of
// the beat: the classic cockpit is a QWidget window with a QML *island* in it
// and is therefore capped at the WINDOW glass rung; a QQuickWindow root is what
// unlocks SCENE (gui/glass_env.py, SHELL_GLASS).
//
// THE FIVE LAWS THIS FILE OBEYS
// -----------------------------
// 1. NO INFORMATION LIVES IN THE GLASS. Every pane below is an OPAQUE token
//    surface (Theme.panel / Theme.sunk). The glass is the WINDOW — it shows in
//    the GUTTERS between the panes, and nowhere else. Consequence: at the FLAT
//    tier (accessibility, RDP, a host with no compositor) nothing is lost, the
//    gutters simply go opaque. Legibility is not a function of the compositor.
// 2. THE SHELL DISPLAYS HAZARD STATE; IT NEVER TRIGGERS IT. The vitals strip is
//    read-only by construction (VitalChip has no signal). There is no arm, no
//    enable, no ramp and no stop in this chrome. HV lives in the BiasPanel
//    island, behind its own DangerGate.
// 3. NO in-scene frost (QtQuick.Effects / MultiEffect) ANYWHERE in this shell.
//    Not laziness — measurement: an in-scene frost pane over the window's alpha
//    hole is PIXEL-IDENTICAL to no pane at all (bbe3b10; Qt Quick has no
//    backdrop-filter and cannot have one). Every gutter here IS an alpha hole,
//    so a MultiEffect over it would cost CPU to render nothing. In-scene frost
//    only earns its keep over APP CONTENT, which this skeleton has none of yet.
// 4. THE ISLAND IS OPAQUE AND IT IS NOT OURS. `islandSlot` is an empty, fully
//    transparent Item. A REAL QWidget (gui/bias_panel.py, on a simulated
//    supply) is native-reparented into the QQuickWindow and positioned over
//    that rectangle by the host. Nothing in the scene graph may paint on top of
//    it — a native child window composites ABOVE the scene, so anything drawn
//    there would simply vanish. That is a platform fact, not a style choice.
// 5. WHAT IS NOT WIRED SAYS SO. Every unwired surface carries a StubBadge.
//
// Colours/sizes: the real `Theme` singleton (gui/qml_theme.py, fed from
// gui/style.py). ZERO inline hex — only the named colour "transparent".
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Tct

Item {
    id: root
    implicitWidth: 1280
    implicitHeight: 800

    // NOTE: no full-bleed background Rectangle, deliberately. The window's own
    // clear colour is the canvas, and the HOST decides what that is — the
    // UNDERLAY LAW (gui/backdrop.py): transparent ONLY while a DWM material is
    // verifiably attached to this window's CURRENT hwnd, otherwise the opaque
    // token canvas. A translucent surface with nothing behind it is the black
    // hole that cost this project two nights; it is unreachable here because
    // this file never paints the gutters at all.

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceMd      // <- the glass gutter
        spacing: Theme.spaceSm

        // ------------------------------------------------------------------ //
        // CHROME — the command strip. View actions only (law 2).              //
        // ------------------------------------------------------------------ //
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 48
            radius: Theme.radiusMd
            color: Theme.chrome
            border.width: 1
            border.color: Theme.hairline

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceMd
                anchors.rightMargin: Theme.spaceSm
                spacing: Theme.spaceSm

                Text {
                    text: "TCT"
                    color: Theme.text
                    font.pixelSize: Theme.fontLg
                    font.bold: true
                    font.letterSpacing: 1.5
                }
                Text {
                    text: "GLASS SHELL"
                    color: Theme.accent
                    font.pixelSize: Theme.fontSm
                    font.bold: true
                    font.letterSpacing: 1.2
                }
                StubBadge {
                    label: "WALKING SKELETON"
                    why: "This is a launcher beside the app, not the app. The "
                         + "shipped cockpit (run.ps1) is completely unaffected by "
                         + "anything in this window."
                }

                Item { Layout.fillWidth: true }

                // The only device action in the chrome, and it is not a hazard:
                // it connects a SIMULATED supply. Nothing here can energize HV.
                ChromeButton {
                    label: vitals.connected ? "SIM CONNECTED" : "CONNECT (SIM)"
                    primary: !vitals.connected
                    enabled: !vitals.connected
                    tip: "Connect the SIMULATED bias supply (devices/"
                         + "bias_supply_simulated.py). No hardware, no HV. The "
                         + "app never auto-connects anything at startup "
                         + "(hardware safety rule 1) — including here."
                    onClicked: chrome.connectSim()
                }
                ChromeButton {
                    label: glass.dark ? "LIGHT" : "DARK"
                    tip: "Toggle the theme. Both themes render from gui/style.py "
                         + "tokens through the real Theme singleton."
                    onClicked: chrome.toggleTheme()
                }
                ChromeButton {
                    label: "BACKDROP: " + glass.backdrop.toUpperCase()
                    tip: "Cycle the DWM material: none -> mica -> acrylic."
                    onClicked: chrome.cycleBackdrop()
                }
                ChromeButton {
                    label: "TIER: " + glass.tier.toUpperCase()
                    tip: "Cycle the glass-tier CEILING (gui/glass_env.py). An "
                         + "override can only force the tier DOWN, never up. "
                         + "Try 'flat': every word in this window must stay "
                         + "legible with no glass at all."
                    onClicked: chrome.cycleTier()
                }
            }
        }

        // ------------------------------------------------------------------ //
        // SIM RIBBON — law 6: a simulated device may never pass as real.      //
        // ------------------------------------------------------------------ //
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 24
            radius: Theme.radiusSm
            color: Theme.sunk
            border.width: 1
            border.color: Theme.sim

            Row {
                anchors.centerIn: parent
                spacing: Theme.spaceSm
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 7; height: 7; radius: 4; color: Theme.sim
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "SIMULATED DEVICES — no instrument is attached to this "
                          + "process. Every number below is synthetic."
                    color: Theme.sim
                    font.pixelSize: Theme.fontXs
                    font.bold: true
                }
            }
        }

        // ------------------------------------------------------------------ //
        // BODY — phase rail | (vitals, tabs, island, truth)                   //
        // ------------------------------------------------------------------ //
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.spaceSm

            PhaseRail {
                Layout.fillHeight: true
                Layout.preferredWidth: 150
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Theme.spaceSm

                // -------------------------------------------------------- //
                // VITALS STRIP — DISPLAY ONLY (law 2).                      //
                //                                                           //
                // It WRAPS (Flow) instead of running off the right edge: the //
                // classic strip clips MOTION at the default width with no    //
                // scroll affordance, which is how an operator loses a fact   //
                // he never knew was there. A wrapped strip cannot clip, at   //
                // any width, by construction — no scrollbar to discover.     //
                // -------------------------------------------------------- //
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: vitalsFlow.implicitHeight + 2 * Theme.spaceSm
                    radius: Theme.radiusMd
                    color: Theme.strip
                    border.width: 1
                    border.color: Theme.hairline

                    Flow {
                        id: vitalsFlow
                        anchors.fill: parent
                        anchors.margins: Theme.spaceSm
                        spacing: Theme.spaceSm

                        VitalChip {
                            label: "HV"
                            value: vitals.hvText
                            state: vitals.hvState
                            why: "Measured bias voltage. REAL data path: the "
                                 + "BiasPanel's own readout poller (a QThread) "
                                 + "reads the simulated supply and this chip "
                                 + "mirrors the same signal the panel gets."
                        }
                        VitalChip {
                            label: "LEAKAGE"
                            value: vitals.currentText
                            state: vitals.currentState
                            why: "Leakage current. It EXISTS in the classic ribbon "
                                 + "(_chip_bias_i) and was dropped in the QML "
                                 + "migration — an operator could not watch it "
                                 + "climb. It is back, and it is real."
                        }
                        VitalChip {
                            label: "COMPLIANCE"
                            value: vitals.complianceText
                            state: vitals.complianceState
                            why: "Compliance is a FAULT state on the HV supply. It "
                                 + "exists in the classic ribbon (_chip_bias_comp) "
                                 + "and was dropped in the QML migration. Losing it "
                                 + "in a shell rewrite is a law-7 regression — "
                                 + "lying about hardware by omission."
                        }
                        VitalChip {
                            label: "MOTION"
                            value: "--"
                            state: "neutral"
                            stub: true
                            why: "No motor stage is constructed in this skeleton "
                                 + "(and nothing auto-homes — hardware safety rule "
                                 + "1). In the shipped shell this is the chip that "
                                 + "CLIPS off the right edge; here the strip wraps."
                        }
                        VitalChip {
                            label: "SCAN"
                            value: "--"
                            state: "neutral"
                            stub: true
                            why: "No ScanController is constructed in this skeleton. "
                                 + "Run state, progress and the pause/abort spine "
                                 + "are Abel's; the shell only ever displays them."
                        }
                        VitalChip {
                            label: "LASER"
                            value: "--"
                            state: "neutral"
                            stub: true
                        }
                        VitalChip {
                            label: "SCOPE"
                            value: "--"
                            state: "neutral"
                            stub: true
                        }
                    }
                }

                // -------------------------------------------------------- //
                // PILL SHELF — a VIEW over the REAL DetachableTabWidget.    //
                // Ratified: gui/detachable_tabs.py stays the ENGINE. This   //
                // shelf binds `tabShelf` (gui/qml_shell.py::_TabShelfAdapter //
                // — imported, not forked), so a pill click really moves the  //
                // widget's current index and the detach glyph really tears   //
                // the page into a floating window.                           //
                // -------------------------------------------------------- //
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 38
                    radius: Theme.radiusMd
                    color: Theme.panel2
                    border.width: 1
                    border.color: Theme.hairline

                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: Theme.spaceSm
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Theme.spaceXs

                        Repeater {
                            model: tabShelf ? tabShelf.count : 0
                            delegate: Rectangle {
                                required property int index

                                readonly property bool current:
                                    tabShelf && index === tabShelf.currentIndex

                                width: pill.implicitWidth + detachGlyph.width + 3 * Theme.spaceSm
                                height: 26
                                radius: Theme.radiusPill
                                color: current ? Theme.accent
                                     : pillArea.containsMouse ? Theme.raised
                                     : Theme.sunk

                                Text {
                                    id: pill
                                    anchors.left: parent.left
                                    anchors.leftMargin: Theme.spaceSm
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: tabShelf ? tabShelf.titles[index] : ""
                                    color: parent.current ? Theme.onAccent : Theme.muted
                                    font.pixelSize: Theme.fontSm
                                    font.bold: parent.current
                                }

                                MouseArea {
                                    id: pillArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: tabShelf.setCurrentIndex(index)
                                    onDoubleClicked: tabShelf.detach(index)
                                }

                                Text {
                                    id: detachGlyph
                                    anchors.right: parent.right
                                    anchors.rightMargin: Theme.spaceSm
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "⧉"
                                    color: parent.current ? Theme.onAccent : Theme.faint
                                    font.pixelSize: Theme.fontMd

                                    MouseArea {
                                        anchors.fill: parent
                                        anchors.margins: -4
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: tabShelf.detach(index)
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: Theme.spaceMd
                        anchors.verticalCenter: parent.verticalCenter
                        text: skeleton.detachNote
                        color: Theme.faint
                        font.pixelSize: Theme.fontXs
                    }
                }

                // -------------------------------------------------------- //
                // THE ISLAND SLOT — see law 4. Empty and transparent on      //
                // purpose: a REAL QWidget (BiasPanel) is a native child      //
                // window of this QQuickWindow, positioned over this exact    //
                // rectangle by the host, and it composites ABOVE the scene   //
                // graph. The placeholder below is visible ONLY if the island //
                // failed to attach — so a broken island is a MESSAGE, never  //
                // a mysterious hole.                                         //
                // -------------------------------------------------------- //
                Item {
                    id: islandSlot
                    objectName: "islandSlot"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 260

                    Rectangle {
                        anchors.fill: parent
                        visible: !skeleton.islandAttached
                        radius: Theme.radiusMd
                        color: Theme.well
                        border.width: 1
                        border.color: Theme.crit

                        Text {
                            anchors.centerIn: parent
                            width: parent.width - 2 * Theme.spaceXl
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                            text: "ISLAND DID NOT ATTACH\n\n" + skeleton.islandNote
                            color: Theme.crit
                            font.pixelSize: Theme.fontMd
                        }
                    }
                }

                // -------------------------------------------------------- //
                // TRUTH LINE — the greppable glass verdict, on screen.       //
                // Real: gui/glass_env.py decided it, gui/backdrop.py         //
                // verified the material against this window's CURRENT hwnd.  //
                // -------------------------------------------------------- //
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: truth.implicitHeight + 2 * Theme.spaceSm
                    radius: Theme.radiusSm
                    color: Theme.well
                    border.width: 1
                    border.color: glass.material ? Theme.good : Theme.hairline

                    Text {
                        id: truth
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: Theme.spaceSm
                        anchors.rightMargin: Theme.spaceSm
                        text: glass.truth
                        color: glass.material ? Theme.muted : Theme.warn
                        font.pixelSize: Theme.fontXs
                        font.family: Theme.monoFamily
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }
}
