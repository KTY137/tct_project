# Bench Verification Checklist

**Last updated:** 2026-07-08  
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
  - Enable HV output on the primary channel (via `TCT_app` GUI → Bias panel → Output).
  - Query the channel status word: `:READ:CHAN:STAT? (@<ch>)` (replace `<ch>` with the channel number, e.g., 1).
  - Examine bit 3 of the returned value: it should be **1** if output is ON, **0** if OFF.
  - Disable HV output and repeat the query: bit 3 should now be **0**.

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
- Click "Start Plan" and observe the Scan Viewer tab.
- During the run, verify the following cockpit elements are live and updating:
  - **Live map:** 2D heatmap surface is drawn as points arrive and updates in real time.
  - **Progress chip:** shows "Point N of Total" (e.g., "5 of 9").
  - **ETA chip:** displays estimated time remaining for the scan.
  - **Elapsed-time chip:** counts up as the scan runs.
  - **Pause button:** is enabled and clickable; click it, observe the scan pauses and button changes to "Resume".
  - **Abort button:** is enabled (red/danger styling) and clickable; test abort on a later run (dangerous action, requires confirmation).
  - **Z-focus card:** (if enabled in plan) shows live Z position vs. amplitude curve as the scan sweeps Z.
- After the run completes: **Finished chip** appears (green state), map is frozen.

**Expected result:**
- All cockpit elements respond in real time; no stalls or frozen readouts.
- Pause/resume works; abort stops the scan immediately (with confirmation gate).
- "Finished" state is reached cleanly.

**Closes:**
- Functional verification of Scan Viewer cockpit design (S2b+S2c).
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

## Next Steps

Once all checklist items are complete:
1. Update `docs/TECH_DEBT.md`: change each completed TODO(bench) row's status or remove it.
2. Update `docs/BENCH_SETUP.md`: incorporate the TP-Link switch model, firmware, and any PC NIC renames.
3. Update `TCT_app/devices/waveform_generator.py` if the DG4000 query form differs from expectation (line 36).
4. Update `TCT_app/devices/oscilloscope.py` with any TBS1052C-specific query forms.
5. Update `TCT_app/devices/bias_supply_iseg.py` if the 0.5 s relay-settle budget needs adjustment.

Report back to Adam with findings and any hardware quirks discovered.
