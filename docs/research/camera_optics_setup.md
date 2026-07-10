# Camera / laser-relay optics — bench findings (2026-07-10)

- **Date / session:** 2026-07-10, Kaya's live bench session with the Blackfly camera and
  laser beam-monitoring optics. Compiled by docs-dev (Samantha) from bench photos, the
  live GUI session, and a source read of `camera_blackfly.py` + `camera_panel.py`. This
  is a bench-observation note, not an external manual/datasheet pull — filed under
  `docs/research/` because it feeds a Prometheus datasheet pull once the relay lens part
  numbers are read (open action 1).
- **Verification key:** `[photo]` off a bench-photo label · `[source]` driver/GUI source,
  file:line cited · `[live]` read off the running GUI today · `[hypothesis]` plausible,
  not yet confirmed · `TODO: verify on the actual setup` open until checked on the bench.
- **Photos** (local-only, gitignored per `docs/REFERENCE_MATERIAL.md`, paths only, none
  copied here): `lab_assets/images/blackfly_videocamera_beam_monitoring.jpeg`,
  `lab_assets/images/laser_optics_table.jpeg`.

## TL;DR

- Camera identity confirmed: FLIR **BFLY-U3-23S6M-C**, serial **19112408**, C-mount,
  1/1.2" global-shutter sensor (Sony IMX249 family), 5.86 µm pixels, 1920×1200 — matches
  the physical label, `configs/devices.yaml`, and the driver docstring.
- Optical path: camera sits atop a vertical cage-rod column; two relay lenses (focal
  lengths **unknown**) sit in the cage rings below it; a beamsplitter cube couples in the
  horizontal laser line; camera and laser **share one focusing objective** down to the
  DUT — a coaxial beam-monitoring camera, not an independent alignment camera.
- Today's working camera settings (below) are a known-good reference point, and two
  optics-looking symptoms — an image circle smaller than the sensor, and focus lost when
  the camera moves up the cage — look like relay geometry (narrow beam, one correct
  image-plane height), not a fault; both need the still-missing relay data to pin down.
- Two other symptoms (Mono16 banding; near-white binned frames) are **app-side display
  bugs**, not optics — traced to specific source lines below.
- Five bench actions are open (end of note); #1, reading the relay lens engravings,
  unblocks a magnification number and a queued Prometheus datasheet pull.

## Hardware identified

All facts below are `[photo]`, read off the physical label in
`lab_assets/images/blackfly_videocamera_beam_monitoring.jpeg`, unless marked `[source]`:

- **Model / serial / mount:** FLIR BFLY-U3-23S6M-C, serial `19112408`, C-mount. Serial
  matches `TCT_app/configs/devices.yaml` (`camera.serial_number: '19112408'`) and the
  model matches the driver docstring `[source]` (`camera_blackfly.py:2`).
- **Sensor:** 1/1.2" optical format, 5.86 µm pixel pitch, 1920×1200 active pixels, global
  shutter (Sony IMX249 family). Pixel count/pitch/sensor family also appear in the driver
  docstring and `SENSOR_W`/`SENSOR_H` `[source]` (`camera_blackfly.py:4`, `:165-166`); the
  1/1.2" format size and global-shutter designation are photo-only — the Python source
  never states either.

## Optical architecture

- **Mechanical stack `[photo]`:** camera at the top of a vertical cage-rod column, with
  two relay lenses in the first and second cage ring below it. Focal lengths are
  **unknown** (engravings unread, open action 1); cage system/vendor not identified —
  `TODO: verify on the actual setup`.
- **Laser coupling `[photo]`:** the horizontal laser line enters the shared axis via a
  beamsplitter cube. Below it, camera and laser share one focusing objective — the large
  black tube on the bench — down to the DUT, so the camera coaxially images the laser
  spot on the sample. That is what "beam monitoring" means here, not a separate
  inspection camera on its own axis.
- **Magnification:** unread relay focal lengths mean the system magnification at the DUT
  is unknown. Do not assume M = 1 — it is used below only as an explicitly-labeled
  illustrative assumption.

**Pixel-scale arithmetic (a bound, not a measurement).** Under two unverified
assumptions — (a) magnification **M = 1** (depends on the unread relay focal lengths,
could be far from 1) and (b) sub-pixel centroid precision of about **1/10 pixel** (a
common image-processing rule of thumb, not benchmarked here) — the 5.86 µm pixel pitch
implies an object-space bound of 5.86 / 10 ≈ 0.59 µm, i.e. "~0.6 µm at M = 1". This is
arithmetic under the two stated assumptions, not a spec, and will be superseded by a
real mm-per-pixel calibration once the relay focal lengths are known (open action 4).

## Known-good settings

`[live]`, screenshot-verified from today's session. Labels match the Camera panel
verbatim (`TCT_app/gui/camera_panel.py`, Acquisition / Gamma / Trigger / Frame Info):

| Control | Value | Notes |
| --- | --- | --- |
| Pixel format | Mono8 | |
| Binning | 1 | |
| Exposure | 13,009 µs (~13.0 ms) | |
| Gain | 14.00 dB | |
| Gamma | Enabled, γ value 1.00 | |
| Hardware trigger (Line0 ↓) | Off | free-running acquisition |
| Frame rate | ~1.0 fps | full 1920×1200 readout, no ROI crop yet |
| TEMP readout | Active / live | populated, not the `–` placeholder |
| Saturated chip | ON | expected — target is the focused laser spot itself; clipping at the spot core alone does not indicate misconfiguration |

Known-good starting point for "camera sees the laser spot, chip states are sane," not a
claim of *optimal* settings. Note: `configs/devices.yaml`'s shipped default
(`exposure_us: 4991.0`, `gain_db: 0.0`) differs from this working point — a generic
startup value, not a claim about the correct beam-monitoring exposure; whether to update
it is an open call for the config owner, not decided here.

## Observed limitations & their explanations

**1. Bright image circle smaller than the sensor (vignette).** `[live]` — the displayed
frame shows a circular bright region surrounded by black. `[hypothesis]`: the relay's
image circle is smaller than the 1/1.2" sensor format, so the outer sensor area simply
receives no light — a geometric relay/sensor mismatch, not a fault. Consequence: a
hardware ROI cropped to the image circle would recover all *useful* pixels and, since
GenICam frame time scales with the read-out region, should also raise the frame rate
above today's ~1.0 fps — a queued app feature, not yet built. Plumbing already exists:
ROI get/set in the driver (`set_roi()`/`get_roi()`, `camera_blackfly.py:495-511`,
`:610-624`) and a manual "Set ROI…" dialog in the GUI (`_ROIDialog`,
`_open_roi_dialog`); missing is an assisted "fit ROI to the image circle" step. Node
writability while streaming is unconfirmed — open action 5.

**2. Focus lost when the camera moves up the cage, not recoverable.** `[live]` — moving
the camera further up the cage column blurs the image, and the blur did not resolve by
any means tried at the time. `[hypothesis]`: consistent with a fixed-image-plane relay —
the image forms at one specific plane and the sensor must sit exactly there; there is no
"focus by sliding the camera" behavior. Whether this height is also parfocal with the
laser's own focus on the DUT is **not yet verified** — open action 2.

## App-side bugs (queued)

Both items are display/data-path issues in `TCT_app`, identified by reading source, not
yet fixed or unit-tested. Do not chase either on the bench — they are software, not
optics.

**Mono16 pixel format: aliasing-like banding.** `[live]` — switching Pixel format to
Mono16 produces banding that looks like aliasing, not a clean 16-bit image. `[source]` —
the driver docstring records Mono16 output as "16-bit, camera outputs 12-bit
zero-padded" (`camera_blackfly.py:5`). Inside `_display()` (starts `camera_panel.py:474`),
the cast is (lines 476-479):

```python
if frame.dtype == np.uint16:
    disp = (frame >> 4).astype(np.uint8)   # 12-bit effective range
else:
    disp = frame
```

The bench-side hypothesis going in was "an unshifted 8-bit cast"; the code does shift
(`>> 4`) before the cast, so it is not literally unshifted. The more precise mechanism,
read from the code's own comment: after the shift `disp` is still "12-bit effective
range" (0–4095), and `.astype(np.uint8)` does not clip or rescale that range — NumPy
truncates to the low 8 bits, wrapping every 256 counts, which reproduces the repeating
light/dark bands seen. Refined `[hypothesis]` from source reading, not confirmed with a
debugger trace or a saved Mono16 frame.

**Binning 2/4: near-white frames.** `[live]` — setting Binning to 2 or 4 produces a frame
that reads as almost uniformly white. `[source]` — `set_binning()`
(`camera_blackfly.py:447-465`) writes the `BinningVertical`/`BinningHorizontal` *value*
nodes but never sets a `BinningHorizontalMode`/`BinningVerticalMode` node, so whether the
camera sums or averages binned pixels is left at the camera's own default, which this
driver never reads or logs. `[hypothesis]`: if that default is "Sum" (unverified —
`TODO: verify on the actual setup`), binning already-bright pixels under the "Saturated"
spot would pin many pixels at the format maximum; `_display()` branches only on
`frame.dtype`, not the binning factor, so there is no compensating rescale — consistent
with a near-white frame.

## Open bench actions

1. Read the engravings / part numbers off the two relay lenses (first and second cage
   ring below the camera) — `TODO: verify on the actual setup`. Unlocks system
   magnification and a concrete lens/spacer recommendation; once read, queue a
   Prometheus datasheet pull on those part numbers.
2. Verify parfocality: with the laser focused on the DUT (via its Z-focus assist), is
   the camera image simultaneously sharp? (Ties to "Observed limitations" #2.)
3. Find and lock the correct camera height (the relay's image plane); record the locking
   mechanism (set screw, clamp collar, or similar — `TODO: verify on the actual setup`)
   so it can be reproduced after any accidental disturbance.
4. Once the ROI feature lands (see "Observed limitations" #1), run a pixel-scale
   (mm-per-pixel) staircase calibration — feeds the planned survey-stitching +
   stage-metrology features; design note in progress at
   `docs/design/camera_survey_metrology.md`.
5. Check whether the hardware ROI nodes (`OffsetX`/`OffsetY`/`Width`/`Height`) are
   writable on this BFLY while streaming, or only while acquisition is stopped.
   `_set_node_if_writable()`'s docstring already names this risk generically — "Format
   nodes (binning, some ROI controls) are read-only on certain models or only writable
   while acquisition is stopped" (`camera_blackfly.py:703-706`) — but the concrete,
   bench-verified case behind it was a binning node; confirm the same holds for the ROI
   offset/size nodes on this unit — `TODO: verify on the actual setup`.

## Sources

- Bench photos (local-only, gitignored, `docs/REFERENCE_MATERIAL.md`):
  `lab_assets/images/blackfly_videocamera_beam_monitoring.jpeg` (camera label),
  `lab_assets/images/laser_optics_table.jpeg` (cage/relay/beamsplitter/objective stack).
- Live bench GUI session, 2026-07-10 (Camera panel settings, chip states).
- `TCT_app/devices/camera_blackfly.py` (docstring :1-35, `SENSOR_W`/`SENSOR_H` :165-166,
  `set_binning()` :447-465, `set_roi()`/`get_roi()` :495-511/:610-624,
  `_set_node_if_writable()` :700-724) and `TCT_app/gui/camera_panel.py` (field labels
  :200-365, saturation chip :463-468, `_display()` :474-479).
- `TCT_app/configs/devices.yaml` `camera:` block (:43-52); no pre-existing entries for
  these findings found in `docs/TECH_DEBT.md` or `docs/BENCH_CHECKLIST.md` (checked
  2026-07-10).

Confidence: hardware identity/settings are photo/live-verified; optical architecture is
photo-verified; the app-side bug mechanisms are source-read hypotheses, not yet
confirmed by test or hardware trace.
