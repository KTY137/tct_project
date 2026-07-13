# State Color Census (D4)

Scope: static source census of `TCT_app/gui/` Python and QML files for W1.
Source ladder: `docs/design/council_v5_paul.md` section 1.
No app code was changed.

Rungs used below: OFFLINE, CONNECTING, SIM, IDLE, ACTIVE-motion,
ACTIVE-HV, ACTIVE-benign, UNKNOWN, TRIPPED, or command-class/not-state.

## Ranked flags

| Rank | Flag | Hits | W1 mapping |
|---|---|---|---|
| 1 | Green-on-nominal connectivity still exists. | `device_panel.py:21` maps connected to `OK_GREEN` in the legacy helper; `device_panel.py:210` marks all-connected summary `good`; `qml/Shell.qml:172` paints real-connected device dots `Theme.good`; `qml/Shell.qml:198` paints connected scope `good`; `style.py:760-777` keeps green connect-button chrome. | Connected/ok/ready should be IDLE neutral, not green. |
| 2 | Red/crit is used for non-HV, non-abort, non-trip command/data/config errors. | Shared path: `style.py:1178-1180`, `status_widgets.py:56-60`; specific consumers include `analysis_panel.py:362-385,427,440`, `calibration_panel.py:418,504`, `settings_window.py:1528-1529,1699`, `panel_kit.py:882,900`. | Most are command-class/not-state. Red should stay ACTIVE-HV, TRIPPED, or abort. |
| 3 | UNKNOWN is sometimes rendered as a confident fill or as amber warning. | `style.py:1243-1244` fills `StatusLamp[unknown]`; `qml/Shell.qml:534-538` has no `unknown` branch so unknown-like values fall to filled faint; `laser_panel.py:575` uses warn for "Output state unknown"; `style.py:1229-1230` documents a filled unknown lamp. | UNKNOWN should be muted dashed hollow/no confident fill. |
| 4 | ACTIVE-HV-live is still amber/armed in several places. | `bias_panel.py:553,563,590,598,604,682,716,857,868`; `qml/ScanStatusStrip.qml:91`; `planner_panel.py:2088,2124-2128,2222-2223,2354`. | Energized/ramping HV should map to ACTIVE-HV red; pre-arm gates can remain ACTIVE-motion amber. |
| 5 | Simulation is mostly marked, but some dots are solid fills. | `style.py:1255-1256` fills simulated lamps under a dashed border; `qml/Shell.qml:538` fills StatChip simulated dots; `qml/Shell.qml:279-323` does the stronger hatched ribbon correctly. | SIM should be hatched/dashed cyan ring, not a confident solid fill. |

## Shared primitives

| File | Lines | Widget/state color use | Should map to |
|---|---:|---|---|
| `style.py` | 280-309,320-321,405-407,485-489 | Base tokens: good/green, warn/armed, crit/danger, sim, error, glow aliases. | Token source; W1 should reserve green from hardware state, danger for ACTIVE-HV/TRIPPED/abort, sim for SIM. |
| `style.py` | 648-715 | Button states: primary/accent, busy/accent, good/green, warn/armed, crit/red, secondary/accent, ghost/muted, motion/armed. | command-class; motion buttons may indicate ACTIVE-motion command class, not device state. |
| `style.py` | 760-777 | `connectBtn` green and `disconnectBtn` crit button chrome. | command-class; connect/disconnect should be neutral/accent, not state green/red. |
| `style.py` | 919-928 | `dangerBtn` and `QPushButton[state=danger]` red. | command-class abort/kill; valid only for STOP/OFF/abort-danger actions. |
| `style.py` | 994-1001 | `ReadoutCell`/`MetricTile` value ink: good, warn/armed, crit/danger, sim. | Depends on caller: IDLE/command for good, ACTIVE-motion or ACTIVE-HV for armed/warn, TRIPPED or command error for crit, SIM for sim. |
| `style.py` | 1015-1021 | Temporary `flash` border states accent/warn/crit. | command-class transient feedback, not hardware state. |
| `style.py` | 1160-1201 | `StatusChip` states neutral, disconnected, unknown, good, warn/fault, crit, info/busy, armed, simulated. | OFFLINE/UNKNOWN/SIM/IDLE/ACTIVE-* by caller; `good` should not mean connected nominal. |
| `style.py` | 1203-1225 | `motionPulse` variants: laser uses crit, hv uses warn, scan uses accent. | laser should ACTIVE-benign or UNKNOWN, not red; hv live should ACTIVE-HV; scan ACTIVE-motion/benign. |
| `style.py` | 1239-1271 | `StatusLamp`/`StatusPill` state colors. | Same state ladder; unknown lamp fill is a W1 fix. |
| `style.py` | 1319-1322 | Planner guard row uses good green. | command-class validation/guard, not hardware state. |
| `style.py` | 1417,1533-1536 | Safety tokens locked against theme overrides. | Token governance, not a device state. |
| `status_widgets.py` | 47-70 | Alias map: connected/ok/ready/off -> neutral; invalid/error/alarm/compliance/fault -> crit; running/live -> busy; on/armed -> armed; sim -> simulated. | Good normalization for nominal aliases; `on -> armed` needs caller care because HV-on should ACTIVE-HV. |
| `status_widgets.py` | 121,141,178,290 | `StatusChip`, `StatusLamp`, `StatusPill`, `ReadoutCell` set dynamic state. | Shared presentation hooks; caller supplies rung. |
| `status_widgets.py` | 317,344 | Busy buttons and `flash_button()` set button state. | command-class transient feedback. |
| `panel_kit.py` | 403-409,471-476 | `MetricTile` allowed states and LED mapping. | Same as `ReadoutCell`; caller-specific rung. |
| `panel_kit.py` | 606-617 | `ActionBar` assigns secondary/primary/motion/danger. | command-class; danger reserved for abort/kill. |
| `panel_kit.py` | 840,882,900 | `EmptyState(variant=error)` uses crit for title/icon. | command-class error unless it represents TRIPPED/FAULT. |
| `qml_theme.py` | 70-78,198-214 | Exposes good/warn/crit/sim/danger/armed to QML. | Token bridge only; QML callers decide rung. |
| `qml/MetricTile.qml` | 65,115,222 | Generic accent bar and meter fill use caller-provided accent. | Caller-specific; not a state by itself. |
| `qml/ScanStatusStrip.qml` | 70-75,81-92 | App state tile accent; HV caption and accent use `hvState == armed ? Theme.armed : Theme.muted`. | HV output-on should ACTIVE-HV; output-off IDLE; disconnected OFFLINE. |
| `qml/Shell.qml` | 139-148,454-462,485-493 | Shell/Icon button tones accent/danger/quiet. | command-class; no device state. |
| `qml/Shell.qml` | 172-175 | Device dots: on green, fault red, sim ring, off hollow. | on -> IDLE neutral; sim -> SIM; off -> OFFLINE; fault -> TRIPPED. |
| `qml/Shell.qml` | 192-208,534-538 | HV/Motion/Scan/Laser/Scope/State StatChip dot colors from good/warn/armed/crit/busy/sim/default. | Per readout; add explicit OFFLINE/UNKNOWN/SIM/ACTIVE-HV mapping in W1. |
| `qml/Shell.qml` | 279-323 | Sim ribbon tint, hatch, text. | SIM; this is the strongest existing sim marking. |
| `qml_shell.py` | 205-212,235-244,313-337 | Bridge stores/forwards shell readout state strings to QML. | No color here; mapping lands in `qml/Shell.qml`. |
| `motion.py` | 49-72,127-129,159-166 | Pulse and flash properties consumed by QSS. | ACTIVE-* or command transient by caller. |
| `theme_editor.py` | 55-62,277-349,381-383 | Locked safety swatches for danger/armed/sim/error. | Theme governance, not hardware state. |

## Panel and dialog census

| File | Lines | Widget/state color use | Should map to |
|---|---:|---|---|
| `analysis_panel.py` | 97-100 | Neutral file/dataset/map/export chips. | command-class data state. |
| `analysis_panel.py` | 341,571,587 | Good button flashes for loaded/exported. | command-class transient. |
| `analysis_panel.py` | 362-385 | Load error crit; file loaded good; dataset arrays good/warn. | command-class file/data validity, not hardware state. |
| `analysis_panel.py` | 427,440,458,471-472,508,552 | Map invalid crit, missing warn, ready good, no-bias warn, Vdep info. | command-class analysis/data state. |
| `arm_latch.py` | 74,87-89,216-218,291-308,359,374,390 | Arm button motion/armed, Execute danger, amber well rail, muted hint. | Arm gate ACTIVE-motion command; Execute is command-class run start, not abort. |
| `bias_panel.py` | 232,613,655-657 | Bias connection chip disconnected/neutral. | OFFLINE/IDLE. |
| `bias_panel.py` | 269,520-526 | Compliance high crit + red label; limit ok neutral. | command-class safety setting; real compliance trip is TRIPPED. |
| `bias_panel.py` | 328-349 | Output OFF and polarity buttons use `dangerBtn`. | command-class HV kill/reversal; red is acceptable for HV-danger action. |
| `bias_panel.py` | 553,563,572,583-605,640-644,682,716,857-872 | HV and current tiles: ramping/settled/live?/moving? warn/armed, trips/errors crit, off normal. | Ramping/settled/live voltage -> ACTIVE-HV; compliant/error -> TRIPPED; off -> IDLE; unknown readback captions -> UNKNOWN where no voltage is known. |
| `bias_panel.py` | 850,861,872 | Good button flashes for apply/ramp/off. | command-class transient. |
| `calibration_panel.py` | 141-144,239-240,360-365,381-382 | Method/dirty/reference/repeat chips: good/warn/info/neutral. | command-class calibration state. |
| `calibration_panel.py` | 283-284 | Repeatability Stop `dangerBtn`. | command-class abort/stop for motion test. |
| `calibration_panel.py` | 398,418,436-438 | Reference running busy, failed crit, acquired good. | ACTIVE-benign while acquiring; failure/success command-class. |
| `calibration_panel.py` | 486,491,504,509-516,550 | Repeatability running busy, failed crit, done good, stopping warn, save flash. | ACTIVE-motion while running/stopping; result states command-class. |
| `camera_panel.py` | 246-251,618-653 | Camera/FPS/temp/sat/ROI/BG chips; offline disconnected, starting busy, stopped neutral. | OFFLINE, CONNECTING, IDLE. |
| `camera_panel.py` | 659-663,758-779 | Camera live busy, saturation warn/good, temp crit/warn/good, FPS busy. | Live/FPS ACTIVE-benign; saturation/temperature warnings TRIPPED only if hardware fault, otherwise command/data warning; OK/good should become IDLE/neutral. |
| `camera_panel.py` | 762,767 | Temp readout direct WARN_RED/WARN_AMBER styling. | Temperature fault/warning; non-HV red should be reviewed under TRIPPED/FAULT criteria. |
| `camera_panel.py` | 889,896-918 | Save/BG/ROI good/info flashes/chips. | command-class. |
| `device_panel.py` | 20-24,40-42,196-203 | Legacy status style connected green, simulated cyan, disconnected red, error orange; row chip uses state string. | connected -> IDLE, simulated -> SIM, disconnected -> OFFLINE, error -> UNKNOWN/TRIPPED depending failure. |
| `device_panel.py` | 97-98,151-159,205-212,245,269-270 | Summary/busy/row chips; all connected good, partial warn, busy accent. | Aggregate IDLE/SIM/OFFLINE/CONNECTING; all-connected green is a W1 fix. |
| `device_panel.py` | 304,312 | Connect/disconnect good flashes. | command-class transient. |
| `intensity_panel.py` | 107,167-182 | Reference monitor offline disconnected, saturated warn, live busy, amp warn/normal. | OFFLINE, ACTIVE-benign, data warning/UNKNOWN for saturation. |
| `intensity_panel.py` | 195,204-210 | Scale/stability good/warn/crit. | command-class measurement quality. |
| `laser_panel.py` | 119-123,174,282-283,334,354-358 | Metadata/WFG/output/pulse/load chips; dirty warn, load 50 good, pulse info. | command-class config/readback; green load is nominal config, not hardware state. |
| `laser_panel.py` | 136-140,673-677 | Manual laser truth banner warn rail/text. | UNKNOWN emission state. |
| `laser_panel.py` | 287-288,526-542,565-575 | Output-on armed button/chip, off neutral, unknown warn, error crit. | Wavegen output on -> ACTIVE-motion/ACTIVE-benign trigger state; unknown -> UNKNOWN; error -> TRIPPED only for real fault. |
| `laser_panel.py` | 374-427,492-505,515-518,590-594 | Wavegen busy/good/warn/crit and flashes. | CONNECTING/IDLE for real connection, command-class for staged/configured/load/test result. |
| `monitor_panel.py` | 111,141-143,186,249 | Alarm/polling/stale/count/legend/table chips. | IDLE/ACTIVE-benign/UNKNOWN/TRIPPED by readings. |
| `monitor_panel.py` | 260-266,301-338,379-385 | Polling busy/neutral; table alarm state; tiles normal/warn/crit/unknown. | Polling ACTIVE-benign; alarms TRIPPED; unavailable UNKNOWN; nominal IDLE. |
| `monitor_panel.py` | 413-424,431-433 | Alarm banner/count/stale warn/crit/unknown/neutral. | TRIPPED/UNKNOWN/IDLE; stale is UNKNOWN-like. |
| `motor_panel.py` | 247-256,759-760,805-838 | Homed/motion/limits/switches/last chips; moving busy, offline disconnected, not homed/near limit warn, soft-limit error crit. | Moving ACTIVE-motion; offline OFFLINE; homed/soft-ok IDLE; switches unknown UNKNOWN; soft-limit error TRIPPED. |
| `motor_panel.py` | 464,502-504 | Move button motion, STOP `dangerBtn`. | Move command ACTIVE-motion; STOP command-class abort. |
| `motor_panel.py` | 712-716,907 | Last error crit, last done neutral, copied flash good. | command-class operation result. |
| `multi_bias_panel.py` | 63-77,104-111,192-216 | All outputs off danger button; all-off/channels/compliance chips; disconnected/warn/busy/crit/good. | HV kill action command-class; channel summary OFFLINE/IDLE/mixed; all-off running ACTIVE-HV if voltage may be live, result command-class/TRIPPED on error. |
| `planner_panel.py` | 750,765,1426-1428,1859-1868 | Delta/HV status chips warn/armed/neutral. | command-class plan readiness; armed pre-run gate ACTIVE-motion. |
| `planner_panel.py` | 781-812,2348-2355,2384 | Arm/Start motion/armed, Abort danger, running busy. | Arm/Start command-class ACTIVE-motion; Abort command-class abort; running ACTIVE-motion/ACTIVE-HV depending plan. |
| `planner_panel.py` | 1252-1259,2124-2128,2222-2223,2274-2276 | Guard green, HV danger span, issue-row good/warn/crit. | Guard/issues command-class; HV span ACTIVE-HV. |
| `planner_panel.py` | 2058-2088,2393-2402,2410 | Estimate/progress tiles normal/warn/crit/armed/good; run finished good/error crit. | Plan metrics command-class; HV range ACTIVE-HV preview; terminal result command-class. |
| `scan_map_view.py` | 166,389,448-449 | Points chip no data/sampled neutral. | command-class data coverage. |
| `scan_map_view.py` | 476,489 | Export flashes good. | command-class transient. |
| `scan_viewer_panel.py` | 115,178,208,330,350-356,384,425-434,487 | Run/finished/focus chips busy/good/warn/neutral. | Running/focus ACTIVE-motion or ACTIVE-benign by scan type; paused/aborting command-class; finished command-class terminal. |
| `scan_viewer_panel.py` | 155-160 | Abort button enters `ActionBar` danger slot. | command-class abort. |
| `scope_panel.py` | 268,305,311-312 | Channel lamp neutral/disconnected; role chip info/neutral. | IDLE/OFFLINE for channel enabled; role is command-class config. |
| `scope_panel.py` | 675-679,893-914,1462 | Scope connection/live/trigger/avg/channels chips; error warn. | OFFLINE/IDLE/ACTIVE-benign/UNKNOWN; trigger/avg config command-class. |
| `scope_panel.py` | 1560 | Probe attenuation warning uses warn token. | command-class setup warning. |
| `settings_window.py` | 492,505-519,544-563,612-632 | VISA/LAN scan chip good/warn/busy. | CONNECTING while scanning; found/no-found command-class discovery result. |
| `settings_window.py` | 1177-1178,1485-1487,1699 | Data-policy note crit/muted, parse label crit, inline red YAML border. | command-class config/data warning; inline red is non-HV and should move to tokens. |
| `settings_window.py` | 1369-1372,1518-1547,1528-1529,1728 | YAML/dirty/sim/reconnect chips; saved/good, warn, crit, simulated; save flash. | command-class config validity; SIM for sim-count chip. |
| `stage_view.py` | 64-65,331-334 | (REMOVED 2026-07-13 b7f88a3) Plot legend colors: scan good, laser warn, Position good, Limits neutral, Scan area info — deprecated 3D GL view removed, replaced by 2D X-Y/X-Z views. | Legacy entry; legend colors were overlay-only, not hardware state. |

## Files with no direct state-color styling

No direct status/state color use found in `__init__.py`, `detachable_tabs.py`,
`liveness.py`, `qt_danger_gate.py`, `run_state_viewmodel.py`,
`scope_measurements.py`, and `status_bus.py`. `scan_coordinator.py` emits
status/dialog signals and `notify(..., "warn"/"error")`, but it does not color
widgets itself; the visual mapping happens in connected panels or the main
window outside this D4 scope.
