# Qt Signal Registry

**Maintained by Kiroku; updated when signals are added/renamed; drift-checked by Mamoru. Paths repo-root-relative.**

This is a lookup table for all `Signal` instances across the TCT application GUI and controller layers. Use this to find where a signal is defined, what it carries, and what connects to it.

Organization: **one section per module**, signals listed in definition order. Format: | Signal name | Signature | Defined at (file:line) | Connected to (slot/handler, file:line) |

---

## gui/status_bus.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `_StatusBus.message` | `(str, str)` — (text, level) | `status_bus.py:21` | `TCTMainWindow._on_status_message()`, `tct_gui.py:211` |

---

## tct_gui.py — Main Window & Bridges

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `_ScanBridge.point_done` | `(object)` — ScanResult | `tct_gui.py:160` | `ScanPanel.on_point_done()`, `tct_gui.py:321` |
| `_ScanBridge.progress` | `(int, int)` — done, total | `tct_gui.py:161` | `ScanPanel.on_progress()`, `tct_gui.py:322`; `PlannerPanel.on_progress()`, `tct_gui.py:340-342` |
| `_ScanBridge.finished` | `()` | `tct_gui.py:162` | `TCTMainWindow._on_scan_finished()`, `tct_gui.py:323`; `TCTMainWindow._on_plan_maybe_finished()`, `tct_gui.py:343` |
| `_ScanBridge.error` | `(str)` | `tct_gui.py:163` | `TCTMainWindow._on_scan_error()`, `tct_gui.py:324`; `PlannerPanel.on_error()`, `tct_gui.py:344-346` |
| `_ScanBridge.z_focus_pt` | `(float, float)` — z_mm, amplitude_V | `tct_gui.py:164` | `ScanPanel.on_z_focus_point()`, `tct_gui.py:368` |
| `_ScanBridge.z_focus_done` | `(float)` — best_z_mm | `tct_gui.py:165` | `ScanPanel.on_z_focus_done()`, `tct_gui.py:369` |
| `_ScanBridge.vscan_point` | `(float, float, float)` — voltage_V, charge_pC, current_A | `tct_gui.py:166` | `BiasPanel.on_vscan_point()`, `tct_gui.py:325` |
| `_ScanBridge.manual_pause` | `(str)` — plan executor ManualPauseStep prompt | `tct_gui.py:167` | `TCTMainWindow._on_plan_manual_pause()`, `tct_gui.py:347` |
| `TCTMainWindow._bias_poll_stop_requested` | `()` | `tct_gui.py:171` | `BiasPoller.stop()`, `tct_gui.py:380` |
| `TCTMainWindow._liveness_stop_requested` | `()` | `tct_gui.py:172` | `LivenessMonitor.stop()`, `tct_gui.py:407` |
| `TCTMainWindow._state_changed_sig` | `(object, object)` — old, new AppState | `tct_gui.py:176` | `TCTMainWindow._on_state_change()`, `tct_gui.py:198` |
| `_LogBridge.record` (handler.bridge in `_build_log_view`) | `(str)` | `tct_gui.py:441` | `_log_view.appendPlainText()`, `tct_gui.py:441` |
| `_QtDeviceDebugHandler.record` (handler.bridge in `_build_debug_view`) | `(str)` | `tct_gui.py:485` | `_device_debug_view.appendPlainText()`, `tct_gui.py:485` |

---

## gui/device_panel.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `_DeviceAction.done` | `(object, str)` | `device_panel.py:46` | ? (callback registered in panel) |

---

## gui/detachable_tabs.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `_DetachableTabCloseButton.closed` | `(object)` — emits self | `detachable_tabs.py:16` | ? (used by DetachableTabWidget) |

---

## gui/liveness.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `LivenessMonitor.device_lost` | `(str)` — device display name | `liveness.py:36` | `TCTMainWindow._on_device_lost()`, `tct_gui.py:409` |

---

## gui/bias_panel.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `_BiasReadWorker.point` | `(float, float)` — (V, I) | `bias_panel.py:53` | ? (to parent BiasPanel) |
| `_BiasReadWorker.progress` | `(int)` | `bias_panel.py:54` | ? |
| `_BiasReadWorker.finished` | `()` | `bias_panel.py:55` | ? |
| `_BiasReadWorker.error` | `(str)` | `bias_panel.py:56` | ? |
| `_VoltageScanWorker.done` | `(str)` — "" on success, error text on failure | `bias_panel.py:99` | ? (to parent BiasPanel) |
| `BiasPanel.reading` | `(object)` — BiasReading, or None when unavailable | `bias_panel.py:124` | ? (part of main-window status display via separate poller) |
| `BiasPanel.polarity` | `(object, bool)` — (polarity 'p'/'n'/None, supports_switch) | `bias_panel.py:125` | ? |
| `BiasPanel.output_toggled` | `(bool)` | `bias_panel.py:170` | ? |
| `BiasPanel.vscan_requested` | `(VoltageScanConfig)` | `bias_panel.py:171` | `TCTMainWindow._start_voltage_scan()`, `tct_gui.py:358` |
| `BiasPanel._read_stop_requested` | `()` | `bias_panel.py:172` | ? |

---

## gui/intensity_panel.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `_IntensityReadWorker.reading` | `(object)` | `intensity_panel.py:35` | ? (to parent IntensityPanel) |
| `_IntensityReadWorker.failed` | `(str)` | `intensity_panel.py:36` | ? |
| `IntensityPanel._stop_requested` | `()` | `intensity_panel.py:73` | ? |

---

## gui/calibration_panel.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `_CalibrationWorker.progress` | `(int, int)` | `calibration_panel.py:38` | ? |
| `_CalibrationWorker.finished` | `(object)` — RepeatabilityResult on success, else Exception | `calibration_panel.py:39` | ? |
| `_ZCalibWorker.finished` | `(object)` — mean q_ref on success, else Exception | `calibration_panel.py:70` | ? |
| `CalibrationPanel.calibration_changed` | `()` — emitted after a successful save | `calibration_panel.py:102` | ? |

---

## gui/multi_bias_panel.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `MultiBiasPanel.vscan_requested` | `(VoltageScanConfig)` | `multi_bias_panel.py:42` | ? |

---

## gui/motor_panel.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `_PollWorker.position_updated` | `(float, float, float)` | `motor_panel.py:54` | ? (to parent MotorPanel) |
| `_CommandWorker.done` | `(str)` — "" on success, else the error message | `motor_panel.py:96` | ? (to parent MotorPanel) |
| `MotorPanel.set_as_scan_start` | `(float, float, float)` | `motor_panel.py:119` | `ScanPanel.set_start_position()`, `tct_gui.py:361-362` |
| `MotorPanel._poll_stop_requested` | `()` | `motor_panel.py:120` | ? |

---

## gui/planner_panel.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `_TreeModel.itemActivatedForAppend` | `(dict)` | `planner_panel.py:202` | ? |
| `PlannerPanel.start_plan_requested` | `(object)` | `planner_panel.py:358` | `TCTMainWindow._start_plan_from_planner()`, `tct_gui.py:349` |
| `PlannerPanel.arm_hv_requested` | `()` | `planner_panel.py:359` | `TCTMainWindow._on_arm_hv_requested()`, `tct_gui.py:348` |
| `PlannerPanel.abort_requested` | `()` | `planner_panel.py:360` | `ScanController.abort()`, `tct_gui.py:350` |

---

## gui/scan_panel.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `ScanPanel.start_requested` | `(ScanConfig)` | `scan_panel.py:36` | `TCTMainWindow._start_scan()`, `tct_gui.py:354` |
| `ScanPanel.abort_requested` | `()` | `scan_panel.py:37` | `ScanController.abort()`, `tct_gui.py:355` |
| `ScanPanel.pause_requested` | `(bool)` — True = pause, False = resume | `scan_panel.py:38` | `TCTMainWindow._toggle_pause()`, `tct_gui.py:372` |
| `ScanPanel.z_focus_requested` | `(ZFocusScanConfig)` | `scan_panel.py:39` | `TCTMainWindow._start_z_focus()`, `tct_gui.py:356` |
| `ScanPanel.vscan_requested` | `(VoltageScanConfig)` | `scan_panel.py:40` | `TCTMainWindow._start_voltage_scan()`, `tct_gui.py:357` |
| `ScanPanel.open_in_planner_requested` | `(ScanConfig)` | `scan_panel.py:43` | `TCTMainWindow._open_in_planner()`, `tct_gui.py:352` |

---

## gui/scope_panel.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `_ChannelCheckbox.changed` | `()` — enable or role changed | `scope_panel.py:227` | ? |
| `_ChannelCheckbox.toggled` | `(int, bool)` — channel number, enabled | `scope_panel.py:228` | ? |
| `_ScopeReadWorker.acquired` | `(object)` — dict[int, (t, v)] | `scope_panel.py:310` | ? (to parent ScopePanel) |
| `_ScopeReadWorker.failed` | `(str)` | `scope_panel.py:311` | ? |
| `_ScopeReadWorker.test_done` | `(str)` | `scope_panel.py:312` | ? |
| `_ScopeReadWorker.settings_done` | `(object, str)` — settings dict, error text | `scope_panel.py:313` | ? |
| `_ScopeReadWorker.sync_done` | `(str)` | `scope_panel.py:314` | ? |
| `_ScopeReadWorker.trigger_done` | `(str)` | `scope_panel.py:315` | ? |
| `_ScopeReadWorker.display_done` | `(int, bool, str)` — channel, on, error text | `scope_panel.py:316` | ? |
| `_ScopeReadWorker.avg_done` | `(str)` | `scope_panel.py:317` | ? |
| `_ScopeReadWorker.chan_config_done` | `(str)` | `scope_panel.py:318` | ? |
| `ScopePanel._acquire_requested` | `()` | `scope_panel.py:433` | ? (internal QTimer trigger) |
| `ScopePanel._live_start_requested` | `()` | `scope_panel.py:434` | ? (internal QTimer start) |
| `ScopePanel._live_stop_requested` | `()` | `scope_panel.py:435` | ? (internal QTimer stop) |
| `ScopePanel._test_requested` | `()` | `scope_panel.py:436` | ? (internal worker start) |
| `ScopePanel._settings_requested` | `()` | `scope_panel.py:437` | ? |
| `ScopePanel._sync_requested` | `(float, float, float)` | `scope_panel.py:438` | ? |
| `ScopePanel._trigger_requested` | `(str, float, str)` | `scope_panel.py:439` | ? |
| `ScopePanel._display_requested` | `(int, bool)` | `scope_panel.py:440` | ? |
| `ScopePanel._avg_requested` | `(int)` | `scope_panel.py:441` | ? |
| `ScopePanel._chan_config_requested` | `(float, str, str)` — probe factor, coupling, bw limit | `scope_panel.py:442` | ? |

---

## gui/qt_danger_gate.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `QtDangerGate._confirm_requested` | `(object, object)` | `qt_danger_gate.py:66` | ? |

---

## gui/settings_window.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `_VisaRescanWorker.done` | `(list, str)` — (resources, error) — error is "" on success | `settings_window.py:162` | ? (to parent) |
| `_VisaRescanWorker.resources_ready` | `(list, str)` — (resources, error) — VISA cache updated | `settings_window.py:209` | ? |
| `_OscilloscopeTab.changed` | `()` | `settings_window.py:301` | ? |
| `_MotorTab.changed` | `()` | `settings_window.py:512` | ? |
| `_BiasTab.changed` | `()` | `settings_window.py:616` | ? |
| `_WaveformTab.changed` | `()` | `settings_window.py:817` | ? |
| `_LaserTab.changed` | `()` | `settings_window.py:945` | ? |
| `_AnalysisTab.changed` | `()` | `settings_window.py:1024` | ? |
| `_InfluxTab.changed` | `()` | `settings_window.py:1068` | ? |
| `SettingsWindow.saved` | `(str)` — path to saved file | `settings_window.py:1133` | `TCTMainWindow._reload_config()`, `tct_gui.py:724` |

---

## gui/panel_kit.py

| Signal | Signature | Defined at | Connected to |
|--------|-----------|-----------|--------------|
| `CheckableCard.toggled` | `(bool)` — checked state | `panel_kit.py:507` | ? (internal; forwards header checkbox toggled state to parent) |

---

## Notes

- Signals marked `?` are internal to their panel/class and do not appear in the main window wiring log; some feed internal `QThread` workers or `QTimer` machinery.
- `_LogBridge` and `_QtDeviceDebugHandler` are defined inline in `tct_gui.py` under logging setup and are not separate classes.
- Multiple `changed()` signals in `settings_window.py` tabs are used to track form state changes within the settings dialog.
- `BiasPoller.reading` and `LivenessMonitor` live on separate `QThread` instances and their signals cross thread boundaries (enqueued mode, safe).

