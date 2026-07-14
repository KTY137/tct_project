# Bench Verification Checklist

**Last updated:** 2026-07-13  
**For use in:** next lab session  
**Safety notes:**
- HV items below (§ iseg) require explicit user authorization before proceeding.
- Wavegen output must feed into a **dump load only** — no laser trigger connected.
- All tests are *read-only* or low-risk configuration verifies; no hardware will be modified unless explicitly stated.

---

## 1. TP-Link Managed Switch (prerequisite)

**What to check:**
- Locate the TP-Link managed switch in the bench LAN (192.168.0.1, isolated VLANs).
- Check the back label for **model number** (e.g., TL-SG2218, TL-SG3226, etc.).
- Log into the switch's web interface (IP 192.168.0.1, default admin credentials).
  Record the **firmware version** (usually found under System Settings → Firmware).
- Test the factory-reset button: hold it for **[TBD: record actual hold time used in 2026-07-07 reset]** seconds.
  (The 2026-07-07 reset unblocked the LAN; document exactly how long to hold for future use.)

**Expected result:**
- Switch model, firmware version, and reset-hold-time are recorded in `docs/BENCH_SETUP.md` troubleshooting §5.

**Closes:**
- `docs/TECH_DEBT.md` line 42 (TODO(bench)).
- Enables: PC Ethernet discovery and LAN-backed instrument discovery.

---

## 2. PC Instrument-NIC Naming

**What to check:**
- On Windows Control PC: open Settings → Network & Internet → Advanced network settings → More network adapter options.
- Find the NIC connected to the bench instrument switch (192.168.0.2/24, static).
- Verify the **friendly name in the list** is exactly **"Ethernet"** (not "Ethernet2", "Ethernet 3", etc.).
  - If it is NOT "Ethernet", note the current name.

**Expected result:**
- If friendly name = "Ethernet": static-IP restore commands in `docs/BENCH_SETUP.md` are correct as-is.
- If friendly name ≠ "Ethernet": update the driver-restore commands in `docs/BENCH_SETUP.md` §2 to match the real NIC name.

**Closes:**
- `docs/TECH_DEBT.md` line 41 (TODO(bench)).

---

## 3. Rigol DG4162 Waveform Generator

### 3a. Output Load Setting (amplitude halving trap) + `:OUTP:LOAD?` readback

**What to check:**
- Connect to DG4162 at 192.168.0.10:5025 via VISA or front-panel GUI.
- Send (or set via front panel): `:OUTPut:LOAD 50` (change from the HighZ default if needed).
  - If you use the front panel: Menu → Output → Load (select 50 Ω).
- Press **Apply** to confirm the setting change.
- Observe the front-panel display: it should now show **50 Ω** (not HighZ).
- **Readback the load:** query `:OUTPut:LOAD?` (or `:OUTP:LOAD?`) and verify the reply:
  - After `:OUTP:LOAD 50`, the reply should be **`50`** (bare integer, no unit suffix).
  - If the unit is in High-Z, the reply is the literal token **`INFINITY`** (not a number); the parser must handle this case.
- Generate a test square wave: set Frequency = 1 kHz, waveform = Square, Amplitude = 2 V, DC Offset = 1 V (unipolar 0→2V).
- Measure the **actual peak voltage delivered** to a 50 Ω load (oscilloscope or scope probe across the PDL trigger input).

**Expected result:**
- Front panel shows **50 Ω** after Apply.
- Query `:OUTP:LOAD?` reads back **`50`** (integer); High-Z reads back **`INFINITY`** (literal keyword).
- The delivered amplitude matches the display (e.g., 2 V display ≈ 2 V peak). If it was previously **half** (1 V when set to 2 V), this fix resolves it.

**Closes:**
- `docs/TECH_DEBT.md` line 35 (TODO(bench)).
- Associated code: `TCT_app/devices/waveform_generator.py` (`:OUTPut:LOAD` SCPI sourced from manual).
- Source: `docs/research/dg4000_tbs1000c_query_forms.md` Q1b (`:OUTPut:LOAD?` query form + return format).

---

### 3b. Output State Query (armed tri-state resolution)

**What to check:**
- DG4162 firmware version: confirm via front panel (Menu → System → Version) or via SCPI: `*IDN?`. Expected: **fw 00.01.14** (or document the actual version used).
- While connected to DG4162 at 192.168.0.10:5025:
  - Enable output on channel 1 via front panel or SCPI: `:OUTPut1:STATe ON`.
  - Query the state: send `:OUTPut1:STATe?` (or short form `:OUTP1?`) and record the reply (expected: `ON` or `OFF`).
  - Disable output: `:OUTPut1:STATe OFF`.
  - Query again: send `:OUTPut1:STATe?` and record the reply (expected: `OFF`).
- Also try channel 2 if present: `:OUTPut2:STATe?` (should work identically).

**Expected result:**
- The query form `:OUTPut{ch}:STATe?` (short `:OUTP{ch}?`) **exists and returns `ON` or `OFF`** (keywords, not 1/0).
- This allows `TCT_app` to auto-resolve the tri-state armed indicator from unknown → True/False on real hardware.
- Parser handles both `ON`/`OFF` and (defensively) `1`/`0`, case-insensitive, with whitespace stripped.

**Closes:**
- `docs/TECH_DEBT.md` line 36 (resolved 2026-07-08); manual query SCPI form now sourced.
- Associated code: `TCT_app/devices/waveform_generator.py` (`:OUTPut{ch}:STATe?` query implementation).
- Source: `docs/research/dg4000_tbs1000c_query_forms.md` Q1a (manual-cited return format: `ON`/`OFF`).

---

### 3c. Pulse Duty Cycle (if testing pulse output)

**What to check:**
- Set waveform = Pulse (not Square).
- Try setting duty cycle via SCPI: `:FUNCtion:PULSe:DCYCle 5` (5%), `30` (30%), `90` (90%).
- Observe: does the duty-cycle parameter accept values outside the documented **20%–80% range**?
- If it does: does the panel spinbox clamp/reflect it, or does it accept silently and send the unclamped value?

**Expected result:**
- Duty cycle accepts only 20%–80% (hardware clamp) **or** panel spinbox enforces the clamp visually.
- No silent out-of-range sends.

**Closes:**
- Research note: `docs/research/pdl800_trigger_wavegen_lan.md` Q2 (frequency-dependent duty-cycle constraint).
- Associated code: `TCT_app/devices/waveform_generator.py` (PULSe DCYCle clamping).

---

## 4. Tektronix TBS1052C Oscilloscope (bench scope)

### 4a. Probe Gain and Coupling Queries

**What to check:**
- Connect to TBS1052C via VISA.
- Query channel 1 probe gain: send `CH1:PRObe:GAIN?` and record the reply.
- Query channel 1 coupling: send `CH1:COUPling?` and record the reply.
- If either query fails (timeout, "Undefined header" error), note the exact error.
- Also try both channels if available.

**Expected result:**
- Both queries **succeed** and return a value:
  - `CH1:COUPling?` returns one of `AC`, `DC`, or `GND` (manual-cited TBS1000C 077-1691 Vertical group).
  - `CH1:PRObe:GAIN?` returns a floating-point gain value (e.g., `0.1000E+00` for a 10× probe; gain = 1/attenuation, per 077-1691).
- These are the **correct TBS1000C forms** (not just tolerated fallbacks); defensive fallback to legacy `CH:PRObe` is for older TDS1000/TBS1000B models (no longer needed for TBS1052C).
- If queries fail on the real unit: document the exact failure; update the fallback logic in `oscilloscope.py` accordingly.

**Closes:**
- `docs/TECH_DEBT.md` line 19 (TODO(bench)); now manual-cited (077-1691) instead of unverified.
- Associated code: `TCT_app/devices/oscilloscope.py` (CH:PRObe:GAIN and CH:COUPling? query forms).
- Source: `docs/research/dg4000_tbs1000c_query_forms.md` Q2 (manual-cited TBS1000C 077-1691 Vertical group forms + same-engine TBS2000 077-1149 argument/return details).

---

### 4b. Liveness Heartbeat (if offline after recent power cycle)

**What to check:**
- After a bench power-on or PC reconnect, query the oscilloscope status: send `*STB?` (Status Byte).
- It should return a two-digit hex number (e.g., `0x40`, `0x20`).
- If it times out or is unreachable, note the exact error and check:
  - Is the scope powered on?
  - Is it still on the static IP 192.168.0.x?
  - Does a ping 192.168.0.x work from the PC?

**Expected result:**
- `*STB?` responds quickly (< 1 s).
- This confirms the liveness monitor (`gui/liveness.py`) can detect the scope as alive.

**Closes:**
- Code validation: `TCT_app/devices/oscilloscope.py::is_alive()` (uses `*STB?` heartbeat).
- Research note: `docs/research/tbs1000c_scpi.md` (liveness-contract line).

---

## 5. iseg HV Bias Supply (HV module)

**⚠️ SAFETY: All items in this section require explicit user authorization.**

### 5a. Output State Gating (channel status word)

**What to check:**
- **User must confirm:** proceed with HV tests?
- If authorized:
  - Enable HV output on the primary channel (`TCT_app` GUI → Bias panel →
    **Ramp to voltage**, a small test value; the panel has no separate
    "Output" toggle — ramping is how output turns on). Disable via
    **Output OFF (0 V)**.
  - Query the channel status word: `:READ:CHAN:STAT? (@<ch>)` (replace `<ch>` with the channel number, e.g., 1).
  - Examine bit 3 of the returned value: it should be **1** if output is ON, **0** if OFF.
  - Disable HV output and repeat the query: bit 3 should now be **0**.
  - Note: this exercises the manual Bias-panel path directly, independent of
    the Planner's two-step arm-latch (§6a). A Planner-run's HV is authorized
    once via its armed envelope (Validate → Dry run → Arm → Execute); this
    manual **Ramp to voltage** action has no confirmation dialog of its own
    today (only **Switch polarity** does, per-action).

**Expected result:**
- Bit 3 of `:READ:CHAN:STAT? (@ch)` accurately reflects output ON/OFF state.
- This is the gating check used in `TCT_app/devices/bias_supply_iseg.py::set_polarity_ch()` to refuse a polarity switch unless the output is OFF.

**Closes:**
- `docs/TECH_DEBT.md` line 20 (TODO(bench), part 1).
- Associated code: `TCT_app/devices/bias_supply_iseg.py` (`:READ:CHAN:STAT?` bit-3 gate in `set_polarity_ch`).
- Research note: `docs/research/iseg_polarity_scpi.md` §3 (gating precondition).

---

### 5b. Polarity Relay Settle Time (confirm budget)

**What to check:**
- **User must confirm:** proceed with HV polarity switch test?
- If authorized:
  - Ensure output is OFF and the HV is discharged (< 2 mV).
  - Send (or GUI-click): `:CONF:OUTP:POL P,(@<ch>)` (switch to positive polarity).
  - Immediately poll the polarity back: `:CONF:OUTP:POL? (@<ch>)` every **0.05 s** (50 ms interval).
  - Record how many polls (approximately how long) until it reads back the new polarity.
  - Repeat for negative: `:CONF:OUTP:POL N,(@<ch>)`.

**Expected result:**
- Polarity flip confirms within **< 0.5 s** (the current `_POL_CONFIRM_BUDGET_S` in the code).
- If it takes significantly longer (> 0.5 s repeatedly), the timeout budget in `TCT_app/devices/bias_supply_iseg.py::_POL_CONFIRM_BUDGET_S` should be increased and re-verified.

**Closes:**
- `docs/TECH_DEBT.md` line 17 (TODO(bench)).
- Associated code: `TCT_app/devices/bias_supply_iseg.py` (`:CONF:OUTP:POL` confirm-poll loop, `_POL_CONFIRM_BUDGET_S = 0.5 s`).
- Research note: `docs/research/iseg_polarity_scpi.md` §3 (relay-settle timeout noted as UNVERIFIED).

---

### 5c. SCPI Token Forms (module and channel queries)

**What to check:**
- **User must confirm:** proceed with HV queries?
- If authorized:
  - Query the module channel count: `:READ:MODULE:CHANNELNUMBER?`
    - Record the reply (expected: a digit like `1`, `2`, `4`, etc.).
  - Query the output polarity list (supported switches): `:CONF:OUTP:POL:LIST?`
    - Record the reply (expected: something like `P,N` or `p,n` or similar).
  - Test lowercase vs uppercase SCPI: send both `:conf:outp:pol:list?` (lowercase) and `:CONF:OUTP:POL:LIST?` (uppercase).
    - Do both work, or only one?
  - Query the channel status in two forms:
    - `:READ:CHAN:STAT? (@1)` (with @ch, typical SCPI suffix form)
    - `:READ:CHAN:STAT?` (without @ch, if the command supports it)
    - Record which form(s) respond.

**Expected result:**
- All documented command forms from `docs/research/iseg_polarity_scpi.md` are confirmed to work on the real unit.
- Lowercase and uppercase both work (iseg typically accepts both).
- The channel-suffix form `(@<ch>)` is the canonical form; any alternative (non-suffix) form is noted as model-specific.

**Closes:**
- `docs/TECH_DEBT.md` line 20 (TODO(bench), part 2).
- Associated code: `TCT_app/devices/bias_supply_iseg.py` (SCPI token construction).
- Research note: `docs/research/iseg_polarity_scpi.md` §1 (command table, verified against manual).

---

## 6. Scan Viewer Cockpit (live run monitor)

### 6a. Cockpit Engagement on Real Bench Plan Run

**What to check:**
- In the GUI, open Planner panel and construct a simple XY-raster plan (e.g., 3×3 grid, 1 mm spacing).
- Click **Validate** (informational — lists limit/HV/point-budget issues; unlocks nothing by itself).
- Click **Dry run** — required: walks the recipe without hardware. A pass shows "✓ Dry run" and unlocks the Arm control (the two-step arm-latch, `gui/arm_latch.py`, design law 5); until it passes, the latch reads "Dry run the recipe first — arming unlocks once the walk passes."
- Review the envelope text rendered over the latch (bias channels, HV V-range called out in red, ramp shape, motion bounds) — the full `ArmedEnvelope` the run will be authorized against.
- **Arm**: hold the Arm control ~3 s, or press it twice in quick succession (keyboard: Enter/Space twice works identically — glove-reliable per design law 5). It shows "✓ Armed · Ns · click to disarm" counting down from 10 s; a single click disarms early.
- While armed, click **Execute** (starts the run — replaces the older single "Start Plan" click) and observe the Scan Viewer tab.
- During the run, verify the following cockpit elements are live and updating:
  - **Live map:** 2D heatmap surface is drawn as points arrive and updates in real time.
  - **Progress chip:** shows "Point N of Total" (e.g., "5 of 9").
  - **ETA chip:** displays estimated time remaining for the scan.
  - **Elapsed-time chip:** counts up as the scan runs.
  - **Pause button:** is enabled and clickable; click it, observe the scan pauses and button changes to "Resume".
  - **Abort button:** is enabled (red/danger styling) and clickable; test abort on a later run — it is an instant one-tap stop by design (law 5), no second confirmation.
  - **Z-focus card:** (if enabled in plan) shows live Z position vs. amplitude curve as the scan sweeps Z.
- After the run completes: **Finished chip** appears (green state), map is frozen.

**Expected result:**
- All cockpit elements respond in real time; no stalls or frozen readouts.
- HV energization for the run is authorized **once**, by the armed envelope
  (`ArmedEnvelopeGate`) built from the Arm gesture above — the executor
  re-validates every live HV/motion action against that envelope; there is no
  further per-step HV confirmation while the plan runs (contrast the manual
  Bias-panel path in §5a, which is separate and per-action).
- Pause/resume works; Abort stops the scan immediately (one tap, no latch).
- "Finished" state is reached cleanly.

**Closes:**
- Functional verification of Scan Viewer cockpit design (S2b+S2c) and the
  two-step arm-latch (design-system law 5, `gui/arm_latch.py` +
  `gui/planner_panel.py`, commits 4498040+eafff38).
- Related commit: 8312f41, 46ff681, 48396c0, 884afe8.

---

### 6b. PNG/CSV Export + Freeze-Levels on Real Scan Data

**What to check:**
- After a completed scan (or load a past run via Analysis panel), the Scan Viewer map displays the last result.
- Locate the map card's toolbar (top-right of the map widget).
- **PNG export:** click the camera/export button, select a file path, save. Verify:
  - A PNG file is created with the correct size/colormap.
  - The file can be opened in an image viewer and matches the on-screen map.
- **CSV export:** click the table/CSV button, select a file path, save. Verify:
  - A CSV file is created with headers (x_mm, y_mm, value, etc.).
  - The CSV opens in a spreadsheet viewer and contains numerical data matching the heatmap.
- **Freeze-levels toggle:** in the map toolbar, find the "Freeze" or lock icon (or a toggle labeled "Lock levels").
  - Click it; observe the colorbar min/max spinboxes appear (or lock visually).
  - Load a second scan; the colorbar should NOT auto-scale; it stays locked to the first run's range.
  - Click the toggle again to un-freeze; colorbar should autoscale to the new run.

**Expected result:**
- PNG export produces a valid image.
- CSV export produces a valid spreadsheet with matching data.
- Freeze-levels toggle persists the colorbar range across runs.

**Closes:**
- Functional verification of ScanMapView export + freeze-levels (46ff681).
- Related code: `TCT_app/gui/scan_map_view.py` (_write_png, _write_csv, freeze-levels toggle).

---

### 6c. Motor "Set as Scan Start" → Planner "Use Current Position"

**What to check:**
- In the GUI, navigate to the Motor panel.
- Jog the motor to a non-zero position (e.g., X=5 mm, Y=10 mm, Z=2 mm).
- Locate the button labeled **"Set as Scan Start"** (or similar) in the Motor panel.
- Click it; the motor position is sent to the Planner.
- Switch to the Planner panel.
- Expand an Axis loop in the plan tree (e.g., the X-axis loop).
- Verify the **X Start spinbox** is now populated with 5 mm (the value you set in Motor).
- Do the same for Y (should be 10 mm) and Z (should be 2 mm).

**Expected result:**
- Motor "Set as Scan Start" updates the Planner's selected loop start positions.
- Flow name: motor `set_as_scan_start` signal → planner `set_position_from_motor(x, y, z)` slot.

**Closes:**
- Functional verification of G3 motor/planner affordance (48396c0).
- Related code: `TCT_app/gui/motor_panel.py` (set_as_scan_start), `TCT_app/gui/planner_panel.py` (set_position_from_motor).

---

## 7. Camera Optics Alignment (FLIR Blackfly Beam-Monitoring Setup)

**Last updated:** 2026-07-10 (Samantha's bench-observation note, 5 actions harvested)

### 7a. Relay Lens Identification

**What to check:**
- The camera sits atop a vertical cage-rod column with two relay lenses in the first and second cage ring below it.
- **Read the engravings / part numbers** off both relay lenses (focal lengths, vendor).
- Record the cage system/vendor if visible.

**Expected result:**
- Part numbers + focal lengths are recorded. Unlocks: system magnification calculation, and a queued Prometheus datasheet pull for optical performance specs.

**Closes:**
- `docs/research/camera_optics_setup.md` open action 1.
- Feeds: camera-survey-metrology feature build (mm-per-pixel calibration).

---

### 7b. Parfocality Verification (camera ↔ laser shared focus)

**What to check:**
- With the laser focused on the DUT (via its own Z-focus adjust or the Planner focus-Z feature), observe the camera image on the Camera panel.
- **Is the image simultaneously sharp** at the laser's Z-focus point, or does the camera need independent focus adjustment?

**Expected result:**
- Camera image is sharp when laser is focused (parfocal) **OR** camera needs independent Z height adjustment.
- Either outcome is documented; the hypothesis is that the relay has a fixed image plane and the camera height (open action 3) must sit at that plane.

**Closes:**
- `docs/research/camera_optics_setup.md` open action 2.

---

### 7c. Camera Height Lock Mechanism

**What to check:**
- The camera currently sits at some height on the cage-rod column.
- Locate the mechanism (set screw, clamp collar, locking ring, etc.) that holds the camera at that height.
- Verify the mechanism is secure and can be reproduced after accidental disturbance.

**Expected result:**
- Locking mechanism is identified and documented (e.g., "M6 set screw on the cage ring").
- **Known-good height is recorded** (e.g., cage ring #1 at 45 mm from the base, camera locked by the set screw on the north side).

**Closes:**
- `docs/research/camera_optics_setup.md` open action 3.

---

### 7d. Pixel-Scale Staircase Calibration (after ROI feature lands)

**What to check:**
- This action defers until after the ROI (Region-of-Interest) feature is built into the GUI (planned, not yet done).
- Once ROI is wired, construct a calibration target with known spatial features (e.g., a printed grid or a semiconductor feature at known spacing).
- Acquire images at several camera Z positions and measure the pixel-to-mm scale.

**Expected result:**
- Pixel scale (mm-per-pixel) is measured and recorded for the system magnification and relay focal lengths identified in action 1.
- This feeds the planned camera-survey-stitching and stage-metrology features.

**Closes:**
- `docs/research/camera_optics_setup.md` open action 4.
- Feeds: `docs/design/camera_survey_metrology.md` stitch precision calculations.

---

### 7e. ROI Writeability While Streaming

**What to check:**
- In the Camera panel, configure a small Region of Interest (ROI) by either:
  - (A) Manually entering OffsetX, OffsetY, Width, Height spinbox values, **while the camera is streaming (acquiring)**, or
  - (B) Using the planned "Set ROI…" assisted dialog (once it is built) **during a live acquisition**.
- Observe: does the ROI change take effect immediately, or does the camera require acquisition to stop first?

**Expected result:**
- If writable while streaming: no action needed; driver code `_set_node_if_writable()` already guards it (see `camera_blackfly.py:703-706`).
- If **read-only while streaming**: the driver's `_set_node_if_writable()` safeguard is correct, and the GUI must stop acquisition before applying an ROI change.
- **Document the finding** in `camera_blackfly.py` docstring or a comment next to the ROI-write calls.

**Closes:**
- `docs/research/camera_optics_setup.md` open action 5.
- Impacts: planned ROI-cropping feature in camera-survey-metrology.

---

### 7f. Known-Good Camera Settings Reference

**For future bench sessions:** Use these Acquisition Console settings as a known-good starting point (verified 2026-07-10):

| Control | Value | Notes |
| --- | --- | --- |
| Pixel Format | Mono8 | (Mono16 has display banding bug; Mono8 is safe) |
| Binning | 1 | (Binning 2/4 shows white-frame bug; bin1 is stable) |
| Exposure | 13,009 µs (~13 ms) | ~1.0 fps readout for full 1920×1200 |
| Gain | 14.00 dB | Bright laser spot with controlled clipping at core |
| Gamma | Enabled, γ = 1.00 | |
| Hardware Trigger (Line 0 ↓) | Off | Free-running acquisition |
| TEMP Readout | Active/Live | Should populate; `–` placeholder means connection issue |
| Saturated Pixels | ON | Expected (laser spot core saturates); not a misconfiguration |

Source: `docs/research/camera_optics_setup.md` (verified live 2026-07-10).

---

## 8. Backdrop Eyeball Block (Windows 11 DWM Material Effects)

**Last updated:** 2026-07-13

**What to check:**
- Launch TCT app with QML shell enabled (`TCT_QML_SHELL=1`).
- Open **Settings → Theme**.
- Locate the **Window Backdrop** combo (values: none | mica | acrylic).
- Opacity slider behavior: verify it auto-pins to 100% and is disabled while a backdrop is active (with visible note indicating this constraint).
- Test all six scenarios below; observe for **visual correctness** (no crashes, no grey flash on real DWM compositor, smooth transitions):

| Scenario | Check | Expected |
|---|---|---|
| A1 | Mica ↔ Acrylic toggle | Material change visible; no flicker or grey flash |
| A2 | Opacity slider with Mica | Translucency changes smoothly; blur effect present |
| A3 | Opacity slider with Acrylic | Translucency changes; acrylic effect consistent |
| A4 | Backdrop → None | Grey disappears, window becomes opaque; clean transition |
| B1 | Theme toggle (dark ↔ light) under active material | Material/opacity persist; theme colors update independently |
| B2 | Window resize + DPI change + detach tab | Material/opacity survive; no reset to defaults; detached window inherits material |
| B3 | Blur pass (visual only) | **Desktop text behind frosted regions must be UNREADABLE; crisp readable desktop = fail** (baseline: text legibility loss confirms the frosted effect is active) |

**Expected result:**
- All seven scenarios pass without visual artifacts or crashes.
- Danger-chip (red) legibility under Mica+opacity is acceptable (4.5:1 contrast floor).
- Settings auto-apply and auto-persist (no manual Apply click required).
- Opacity slider auto-pinned to 100% and disabled while a backdrop is active (with visible note).
- Panel glass (experimental) = theme-editor cards only for now.

**Closes:**
- C1/C2 feature acceptance (backdrop.py + style.py integration + theme_editor UI).
- Visual verification of DWM ctypes isolation and fail-safe fallback.

---

## 9. Camera Binning SpinView Check (FLIR Blackfly SN 19112408)

**What to check:**
- Connect to FLIR Blackfly camera via Acquisition Console or `pyspin` (real hardware).
- Locate SpinView "Binning" node tree:
  - **BinningMode** (dropdown: Horizontal | Vertical | Both)
  - **BinningSelector** (if present: selects which binning to configure)
  - **BinningHorizontal** / **BinningVertical** (spinners for bin factor)
- Check the **WriteAccessibility** (IsWritable property) of each node:
  - **While NOT acquiring (idle):** each node should be writable.
  - **While acquiring (streaming):** record which nodes become read-only.

**Expected result:**
- Idle state: Binning nodes fully writable.
- Streaming state: per-node write-state recorded (e.g., "BinningHorizontal is read-only during stream on SN 19112408").
- This informs `gui/camera_panel.py::_set_node_if_writable()` safeguard: skip read-only nodes, warn on failure.

**Closes:**
- `docs/research/camera_optics_setup.md` open action 5 (ROI writeability) — extends to Binning.
- Guards against silent "apply binning, then discover it's ignored mid-acquisition" trap.

---

## 10. Reference-Channel Baseline Window Pulse-Free (Real Timebase)

**What to check:**
- In TCT app, enable ref-channel monitoring (oscilloscope CH2 as intensity reference).
- Acquire a waveform at real lab timebase (e.g., 1 µs/div, time-window capture the laser pulse + pre/post baseline).
- In the Analysis panel (after run completion), export the ref-channel waveform (time, voltage).
- **Inspect the pre-trigger baseline window** (before laser pulse):
  - Is the voltage noise-only (zero mean, small RMS)?
  - Or is there a visible DC offset / thermal drift / 50/60 Hz mains hum?

**Expected result:**
- Baseline is clean (noise-only, zero mean, RMS < 5 mV typ.).
- No systematic DC offset that would bias all saved charge/CCE values.
- `analysis/waveform_analysis.correct_baseline()` (D4, committed 2026-07-13) now corrects both DUT and ref channels identically; this check verifies the optical setup + acquisition are not introducing spurious baseline shifts.

**Closes:**
- Verification of D4 baseline-correction fix (Kings retro RISK row 85: latent DC-offset bias).
- Confidence that ref-charge and CCE ratios are now unbiased.

---

## 11. QML Shell Probe (decision-gated: TCT_QML_SHELL default flip)

**Requires Kaya at the real display. Prerequisites:** decision to ratify the shell as standard (ratified 2026-07-13, `docs/research/qml_hybrid_standard_decision.md`).

| Step | Check | Expected | Notes |
|---|---|---|---|
| R1 | (RETIRED 2026-07-13 b7f88a3) **RHI coexistence:** 3D GL stage view + QML chrome — MOOT, stage_view.py removed. | Classic cockpit is now RTT-free (2D X-Y/X-Z views, no QML shell-embedded GLViewWidget). Design-rule guard test added. | See commit b7f88a3 (3D GL stage view removed). |
| R2 | **Detach under QML shell:** Motor Stage → float → 2nd monitor (diff DPI if available) → redock. No persistent blank frame (a one-shot `update()` nudge is OK). | Redock restores live motor updates; no permanent render gap. | Tests window lifecycle + GPU context rebuild. |
| F3 | **Perf on i7 (5% CPU idle; 100 ms heartbeat under load):** `TCT_QML_SHELL=1` app idle: rail + pill hover ColorAnimation + 1 Hz poll < 5% CPU. With a live simulated scope acquire (pyqtgraph 15 Hz sibling), GUI-thread heartbeat gap < 100 ms. | CPU stays calm; scope/motor updates are not starved. | Reuse `tests/test_gui_thread_watchdog.py` bounds on real hardware. Integrates animation cost into budget. |
| F2/R4 | **RDP usability:** Launch the shell via RDP into the lab laptop (Microsoft Remote Desktop on Windows). Shell must launch and be usable under `opengl32sw`/llvmpipe (Mesa software backend). | App is responsive or gracefully falls back to classic shell (TCT_QML_SHELL unset). | If RDP path fails: document it; classic shell is the supported remote mode (one-env-var fallback). |
| R5 | **Frozen PyInstaller build:** Build a snapshot with PyInstaller; app launches without "missing QtQuick" error. Shell.qml loads error-free. | No plugin/resource missing errors; QML engine boots cold on a fresh machine. | Smoke test for release build integrity. |

**Decision rule (per `docs/research/qml_hybrid_standard_decision.md`):** Steps R1-R3 + R5 green on the iGPU → ratify shell as standard, with QWidgets+safety single-impl as standing rule for panels. F2 fails → ratify with "classic shell is the supported RDP/remote mode" (design already permits this via env-var fallback).

---

## 12. DWM Material on Classic Main Window (Windows 11 Real Display)

**Last updated:** 2026-07-13 · **Requires Kaya at the real display.**

**What to check:**
- Launch TCT app in classic mode (do NOT set `TCT_QML_SHELL=1`; the default is now classic).
- Navigate to **Settings → Theme**.
- Locate the **Window Backdrop** combo (values: none | mica | acrylic).
- Test each scenario below; observe for **visual correctness** under DWM on real glass (no crashes, no grey flash, material effect visible):

| Scenario | Check | Expected |
|---|---|---|
| A1 (main) | Main window (classic QWidget panels only, no QML shell) with Mica enabled | Frosted material effect visible; blur on underlying desktop/windows is clear |
| A2 (main) | Main window with Acrylic enabled | Acrylic/noise pattern visible; slightly less legible text behind frosted area vs. Mica |
| A3 (detach) | Detach a panel (e.g., Motor) to a floating window; material should be inherited | Detached window also has material applied; no regression or loss of effect |
| A4 (reload) | Close and re-open the theme window (`Settings → Theme`) while material is active | No black screen, no loss of material, no stall |

**Expected result:**
- All four scenarios pass without visual artifacts or crashes.
- Material effects are **real DWM effects** (not our code's fake blur) — legibility of desktop text MUST drop noticeably; if text stays crisp/readable, the frosted effect is NOT active.
- Opacity slider behavior: when a backdrop is active, opacity is auto-pinned to 100% and slider is disabled (with visible note).
- Material/opacity persist across theme toggles (dark/light), app close/reopen, and detach/redock cycles.

**Closes:**
- C1/C2 feature acceptance on real hardware (backdrop.py + style.py integration + theme_editor UI; classic shell verification).
- DWM ctypes isolation and fail-safe fallback soundness.

---

## 13. Metrology Bench Protocol — Stage↔Camera (Workstream B3)

**Last updated:** 2026-07-13 · **Requires Kaya at the bench** (every step commands stage motion or
needs hands on the optics). Feeds: `docs/research/metrology_feasibility.md` §7 (the measured-results
table) and the M2 go/no-go. Existing code only — anything that would need new code is marked
"(needs beat …)" instead of pretended.

**Ground rules for the whole section:**
- Motion is danger-gated (`controller/danger_gate.py`) or typed explicitly by the operator at a
  REPL — never scripted unattended (CLAUDE.md safety rules 1–2).
- REPL steps run from `TCT_app\` in the app venv **with the GUI app closed** (camera/COM port have
  a single owner).
- Evidence directory: create `artifacts_claude\metrology\<yyyymmdd>\` first
  (`scripts/metrology_report.py:write_report` does NOT create parent directories).
- Every measured number is transcribed into `docs/research/metrology_feasibility.md` §7
  (quantity, value, date, artifact path) — that table is the record, not the terminal scrollback.
- REPL session preamble (shared by steps 0–3). `ConsoleGate` is a session-local shim typed by the
  operator — the explicit CLI confirmation of safety rule 2, not app code (wiring a real gate +
  `calibrate_affine` into a GUI "Stage Metrology" page is a separate beat, design
  `docs/design/camera_survey_metrology.md` §E.8):

  ```python
  # from TCT_app\ in the app venv, app CLOSED
  import numpy as np
  from controller.device_manager import DeviceManager
  from controller.repeatability import RepeatabilityTester

  class ConsoleGate:                       # session-local; rule-2 CLI confirmation
      def confirm(self, action):
          print(action.summary); print(action.detail)
          return input("Type YES to allow this motion: ").strip() == "YES"

  dev = DeviceManager("configs/devices.yaml")
  dev.motor.connect(); dev.camera.connect()
  dev.motor.home()                         # explicit operator command — the stage WILL move
  tester = RepeatabilityTester(dev.motor, dev.camera, gate=ConsoleGate())
  ```

### 12a. Step 0 — Measure relay magnification M (prerequisite for every µm number)

**What to check:**
- Place a known-pitch target at the DUT/laser focal plane (§7b parfocality): AmScope MR095
  (10 µm div / 1 mm — the $17 tier) preferred; today's paper print is acceptable for a FIRST
  estimate only (~1 % printer-scale honesty — flag it in the record).
- Focus using the Camera panel live view (§7f known-good settings), then close the app and grab a
  frame in the REPL session above:

  ```python
  frame = np.asarray(dev.camera.get_frame())
  np.save(r"..\artifacts_claude\metrology\<yyyymmdd>\step0_reticle_frame.npy", frame)
  ```

- Read the pixel coordinates of the FIRST and LAST clearly visible division line spanning `N_div`
  divisions of pitch `p_mm` (any viewer with a pixel cursor works; `pyqtgraph.image(frame)` from
  the same venv gives one).
- Compute: `px_per_mm = |u_last − u_first| / (N_div * p_mm)`; `M = px_per_mm / 170.65`
  (IMX249 5.86 µm pixels; `px_per_mm ≈ 170.6·M`, `docs/design/camera_survey_metrology.md` §0).
- If the target permits, rotate ~90° and repeat along the other image axis; expect agreement to
  ~1 % (larger disagreement = tilt or anisotropy — record it, do not average it away).

**Expected result:**
- `M`, `px_per_mm`, target identity/pitch, and the saved `.npy` frame recorded in
  `metrology_feasibility.md` §7. Unlocks the µm columns of every later step.

**Closes:** feasibility-memo unknown 1; supersedes the scale part of §7d (which stays for the
post-ROI distortion pass).

### 12b. Step 1 — Noise floor + N-cycle return-to-target repeatability

**What to check:**
- **Noise floor (REPL only — the GUI approach spinbox has min 0.1 mm,
  `gui/calibration_panel.py:261`, so a zero-excursion run cannot be started from the panel):**

  ```python
  floor = tester.run(n=20, approach_mm=0.0, settle_s=0.4, px_per_mm=<step0 value>)
  print(floor.summary())
  np.save(r"..\artifacts_claude\metrology\<yyyymmdd>\step1_floor_shifts_px.npy",
          np.array(floor.shifts_px))
  ```

  Zero-distance moves ⇒ the scatter is pure registration + vibration — the floor every other
  number is compared against.
- **Return-to-target repeatability** (same shape, real excursion; direction cycles
  +X, +Y, −X, −Y per `RepeatabilityTester.run`, so this scatter is the POOLED multi-direction
  number — per-direction grouping / a clean unidirectional-only mode is **(needs beat:
  per-direction stats, design §B.0-3)**; per-axis backlash comes from step 2 instead):

  ```python
  rep = tester.run(n=20, approach_mm=5.0, settle_s=0.4, px_per_mm=<step0 value>)
  print(rep.summary())
  np.save(r"..\artifacts_claude\metrology\<yyyymmdd>\step1_rep_shifts_px.npy",
          np.array(rep.shifts_px))
  ```

- GUI alternative (no saved arrays, summary text only): Calibration panel → Repeatability group
  (`gui/calibration_panel.py:_run_repeatability`; requires Connect All + homed stage + the
  main-window gate). Persisting `RepeatabilityResult` arrays from the panel is
  **(needs beat: result persistence)**.
- Check `n_low_quality` in both results — nonzero means frames were excluded by the
  `prepare_metrology_roi` quality gate (feasibility unknown 8: texture adequacy).

**Expected result:**
- `floor` std ≈ the registration class (~0.05–0.1 px ⇒ sub-µm at M ≥ 1); `rep` std/p2p in µm is
  OUR first real repeatability number (prior-art prediction: ±5–15 µm class, memo §2 row b).
- Evidence: two `.npy` arrays + both `summary()` texts in the bench log + §7 table rows 3–4.

**Closes:** feasibility-memo unknowns 2, 3, 8.

### 12c. Step 2 — Backlash staircase + affine fit (`calibrate_affine`)

**What to check:**
- Jog to a textured, in-focus region near the middle of travel first (Motor panel or REPL
  `dev.motor.move_to(...)` — typed explicitly).
- No GUI path exists for `calibrate_affine` (grep 2026-07-13: wired only in tests) — REPL, same
  session **(needs beat: Stage Metrology page, design §E.8)**:

  ```python
  cal = tester.calibrate_affine(nx=3, ny=3, step_mm=0.5, settle_s=0.5, tolerance_um=5.0)
  print(cal.notes)
  from scripts.metrology_report import write_report
  write_report(cal, r"..\artifacts_claude\metrology\<yyyymmdd>\step2_affine_report.html",
               tolerance_um=5.0)
  ```

- Staircase geometry: 3×3 grid, 0.5 mm steps ⇒ 1×1 mm extent, 30 commanded positions, ONE gate
  confirmation for the whole staircase; the stage is left at the last point (no auto-return).
- Step-size guard: neighbour image shift = `step_mm × px_per_mm` must stay well under half the
  frame (phase correlation aliases past it, `repeatability.py` TODO(bench) note). 0.5 mm is safe
  for M ≤ 2; use `step_mm=0.2` if step 0 measured M ≥ 4.
- `tolerance_um=5.0` is the working gate from the B1 ±5 µm prior — informational, Kaya judges.

**Expected result:**
- `cal.affine` is not None; `cal.notes` reads like
  `"30 pts; rms 0.xxx px (x.xx um); backlash N pair(s): X=aa.aa um, Y=bb.bb um"` — the
  `backlash_mm` fields are the per-axis mean forward-minus-return discrepancy in stage mm
  (`controller/repeatability.py:fit_stage_camera_affine`; both axes measurable by construction,
  `tests/test_affine_selfcal.py::test_calibrate_affine_reports_backlash_on_both_axes_on_sim`).
  `"backlash unmeasured (no matched forward/return pair)"` means too many low-quality exclusions —
  re-illuminate/re-focus and rerun.
- The HTML report shows: PASS/FAIL banner vs 5 µm, Scale X/Y (px/mm — cross-check against step 0:
  the ratio staircase-scale / reticle-scale is the steps-per-mm truth, feasibility unknown 6),
  rotation/shear, RMS + max residual (linearity), residual quiver, and a `Backlash (mm)` row.
- Evidence: the HTML report (the primary artifact) + §7 table rows 5–6.

**Closes:** feasibility-memo unknowns 4, 5, 6.

### 12d. Step 3 — 30-minute drift series (fixed target, ~30 s cadence)

**What to check:**
- Stage parked on the step-2 target; do not touch the bench during the series.
- Record temperature at start / 15 min / end: camera TEMP readout (§7f) + room thermometer; note
  any HVAC/door events. (Automatic wall-clock timestamps + a temperature channel inside
  `RepeatabilityResult` are **(needs beat: timestamped drift series)** — until then the cadence is
  `settle_s` + move/grab overhead, which is good enough for a µm/h slope.)

  ```python
  drift = tester.run(n=60, approach_mm=0.0, settle_s=30.0, px_per_mm=<step0 value>)
  np.save(r"..\artifacts_claude\metrology\<yyyymmdd>\step3_drift_shifts_px.npy",
          np.array(drift.shifts_px))
  ```

  (~30–35 min: 60 zero-move cycles, one frame per ~30 s, all registered against the fixed
  reference frame.)

**Expected result:**
- `drift.shifts_px` vs cycle index shows a smooth trend, not random scatter; slope × cadence ⇒
  µm/hour, and against the ΔT notes ⇒ µm/°C. Prior-art prediction: ~1.3 µm/°C class (B1 §2) —
  ours may differ; that is the point.
- Evidence: the `.npy` array + temperature notes in the bench log + §7 table row 7. This number
  sets the re-registration cadence for any ≤2 µm ambition (memo verdict V3).

**Closes:** feasibility-memo unknown 7. Together, 12a–12d give M2 everything memo §6 lists.

---

## 13. PI C-663 Stop Semantics (post 7a55d03)

**What to check:**
- Verify that the PI C-663 controller's `StopAll` (#24) command halts a running FRF/MOV with single-character latency (sub-10 ms expected).
- Confirm that after `StopAll` + error-clear, a new `MOV` is accepted WITHOUT re-homing (e.g., stage halts mid-jog, a second `MOV` to a different target succeeds, no stall or reset required).
- Verify that `IsMoving`/`ontarget` poll reports on-target state for a normal `MOV` exactly as `pitools.waitontarget` did on C-663+L-836 (parity with legacy behavior).
- **GRBL:** Confirm that `0x85` (real-time byte for soft-reset) does not halt an in-progress `$H` homing cycle; if it does, document the behavior in `docs/design/guarded_exchange.md`.

**Expected result:**
- PI C-663 StopAll halts sub-command latency; MOV resumption works without re-home; polling parity holds.
- GRBL soft-reset behavior documented (if not already).

**Closes:**
- `docs/TECH_DEBT.md` pending research notes (pi_gcs_stop_semantics, scpi_capability_discovery).
- BENCH_CHECKLIST consistency note: _wait_on_target parity (PI motion completion semantics) verified identically across both PI + simulated backends.

---

## 13. Open-Timeout Bounds Verification (Wave-1 Fix 2026-07-14)

**Last updated:** 2026-07-14  
**Requires Kaya at the bench** (every step verifies real powered-off instrument behavior).

### 13a. Wavegen Connect Fail-Fast (5 s expected)

**What to check:**
- Start the TCT app in simulated mode (no bench connection).
- Manually shut down the DG4162 waveform generator at the power switch (or unplug the Ethernet cable to 192.168.0.10).
- In the GUI, click **Connect All** (or manually re-enable the wavegen in Devices panel).
- Observe the **connection attempt timeout behavior:**
  - Old behavior: hang for ~90 s (PyVISA default).
  - New behavior: fail fast within ~5 s (now bounded by `open_timeout=5.0` in config).
- Check the log for a clean "Timeout opening resource" message (not a hung thread or crash).
- Power the DG4162 back on and reconnect; verify it connects normally.

**Expected result:**
- Wavegen connect timeout ~5 s (instead of minutes). Connection state reported cleanly to the GUI. No thread leaks or zombie VISA sessions left behind.

**Closes:**
- 7b4ea94 + 8e85f2a fix (open_timeout bounds on all VISA devices).
- Addresses Kaya's bench observation: "reconnect on a powered-off wavegen used to hang the app."

---

### 13b. All-VISA Reconnect Stress (Liveness-Monitored Cycles)

**What to check:**
- With all instruments powered on (DG4162, TBS1052C scope, iseg HV, Keithley HV, DRS4 if present):
  - Click **Disconnect All** in the GUI (Devices panel).
  - Observe liveness monitor (§4b/§5 heartbeat probes) report all devices as DISCONNECTED within 3 s.
  - Immediately click **Connect All** and observe all devices report CONNECTED.
  - Repeat the cycle **5 times** without any app crash, thread stall, or GUI freeze.
- Log the time taken for each Disconnect/Connect cycle (expect ~1–2 s per cycle; hangs >5 s indicate an io_lock deadlock or incomplete teardown).

**Expected result:**
- Disconnect/Connect stress cycles crash-free. All devices re-connect on subsequent attempts. No accumulation of stale VISA sessions or file descriptors (check Process Monitor or `Get-NetTCPConnection` for TCP/IP port leaks if using physical instruments).

**Closes:**
- e0a9d91 + 5576378 fixes (io_lock teardown + _run_bg completion + main-window bg-thread join).
- Verifies the fail-safe open-failure path on all backends (VISA timeout recovery, session cleanup).

---

### 13c. Per-Driver TODO(bench) Items from 7b4ea94/8e85f2a

**What to check (read-only audit):**
- `TCT_app/devices/waveform_generator.py`: open_timeout set to 5.0 s (VISA DG4162 TCPIP).
- `TCT_app/devices/oscilloscope.py`: open_timeout set to 5.0 s (VISA TBS1052C or DRS4).
- `TCT_app/devices/bias_supply_iseg.py`: open_timeout set to 5.0 s (iseg VISA/serial).
- `TCT_app/devices/bias_supply_keithley.py`: open_timeout set to 5.0 s (Keithley VISA).
- `TCT_app/devices/oscilloscope_drs4.py`: open_timeout set to 5.0 s (DRS4 USB).
- All drivers implement `_teardown_session()` (called on disconnect) to close/null VISA instrument + RM.

**Expected result:**
- Confirm source code matches the list above (grep for `open_timeout` and `_teardown_session`). No TODO(bench) markers remain in those files.

**Closes:**
- 7b4ea94/8e85f2a implementation audit (no manual instrumentation needed; code review).

---

## 14. On-Screen Rendering (Post-4ca8331 Theme Commit)

**Last updated:** 2026-07-14  
**Requires Kaya at the real display.**

### 14a. Wrapped Ribbon at Real DPI

**What to check:**
- Launch TCT app (classic mode, no QML shell).
- Verify the status ribbon (top strip of status chips: Devices, Settings, Log, Debug, Motion/Scan/etc.) on the running app at real display DPI.
- The ribbon **no longer scrolls**; it now wraps (new `gui/flow_layout.py` layout).
- The app ships at 1280 px default width; with the new wrap, it grows a second row (41 px → 104 px ribbon height).
- Verify:
  - No safety chip is clipped at the screen edge.
  - The second row does not fight the status bar (no visual overlap or awkward spacing).
  - All chips remain legible and clickable after wrapping.

**Expected result:**
- Wrapped ribbon renders cleanly at real DPI; no clipping, no layout jank.

**Closes:**
- `docs/TECH_DEBT.md` BENCH row (post-4ca8331 ribbon rendering).

---

### 14b. Re-Tinted Icons at Real DPI (Both Themes)

**What to check:**
- In the launched app: toggle the theme (Settings → Theme → Dark/Light).
- Verify all icon buttons (motor jog, bias ramp, scope configure, capture, etc.) re-color correctly in both dark and light modes.
- **Special case:** perform a **light→dark→light** toggle (rapidly clicking the theme selector) and confirm icons refresh each time.
  - (The bug was that the icon pixmap was frozen at construction; 4ca8331 fixed it.)
- No icons should remain the old color after a theme switch.

**Expected result:**
- Icons follow theme color dynamically; no stale pixmaps.
- Light→dark→light cycles show live re-tinting.

**Closes:**
- `docs/TECH_DEBT.md` BENCH row (icon re-tinting on theme toggle).

---

### 14c. New Chip Look — Neutral Ink, Hue in Fill/Border (Both Themes)

**What to check:**
- Examine the status chips in both dark and light themes (Devices, Settings, Log, Debug, Motion, Scan, etc.).
- Verify:
  - Each chip's **label text is now neutral** (no saturated hue in the ink).
  - The **fill color and 1 px border carry the hue** (good/warn/crit state is visible in fill + border, not ink).
  - The visual distinction between states is still clear (good/warn/crit are distinguishable).
- **Kaya's eye decides:** does the classic ribbon need a **saturated state dot** added (the QML island's default) to restore glanceability?
  - If yes: add a small 6–8 px saturated colored dot to the QWidget `StatusChip` (TECH_DEBT row 4 design call).
  - If no: accept the current look as-is.

**Expected result:**
- Chip ink is neutral across the board; hue lives in fill/border.
- Kaya makes the call on whether the saturated dot is needed for usability.

**Closes:**
- Design validation of Mary's 4ca8331 review (APPROVE-WITH-NITS) and Kaya's pending design call (TECH_DEBT row 4).

---

## Next Steps

Once all checklist items are complete:
1. Update `docs/TECH_DEBT.md`: change each completed TODO(bench) row's status or remove it.
2. Update `docs/BENCH_SETUP.md`: incorporate the TP-Link switch model, firmware, and any PC NIC renames.
3. Update `TCT_app/devices/waveform_generator.py` if the DG4000 query form differs from expectation (line 36).
4. Update `TCT_app/devices/oscilloscope.py` with any TBS1052C-specific query forms.
5. Update `TCT_app/devices/bias_supply_iseg.py` if the 0.5 s relay-settle budget needs adjustment.

Report back to Adam with findings and any hardware quirks discovered.
