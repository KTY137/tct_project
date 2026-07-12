# Session state — Adam's externalized working memory

**Purpose:** this file holds the state that would otherwise live ONLY in the
orchestrator's context — and is therefore the state that a context compaction
silently corrupts. Adam updates it on every dispatch and every landing.
A fresh session reads this file and is immediately as informed as the old one.

**The one thing it exists for:** knowing which beat holds which file. Getting
that wrong means a commit that sweeps another agent's in-flight work.

Updated: 2026-07-12 night shift.

## HEAD

`design/cockpit-v5 @ 3f6e2b7` (pushed).

## IN FLIGHT — file locks (do NOT stage these paths)

| Beat | Agent | Locked paths |
|---|---|---|
| auto-enable sweep (Mary BLOCKER) | Paul | `TCT_app/devices/`, `TCT_app/tests/test_driver_truth.py`, `test_bias_multichannel.py`, `test_bias_all_off.py`, `test_bias_polarity.py`, `test_bias_and_calibration.py`, `test_bias_simulation_mode.py` |
| latched-trip detection (Mary MAJOR) | Abel | `TCT_app/controller/scan_controller.py`, `TCT_app/tests/test_trip_detection.py` |
| wiring debt + black box + theme r2 | Noah | `TCT_app/gui/style.py`, `gui/theme_editor.py`, `gui/status_widgets.py`, `tct_gui.py`, `TCT_app/tests/test_theme_editor.py`, `test_scan_viewer_wiring.py`, `tests/conftest.py` |

## NEXT BEAT (queued, do not forget)

**StateMachine.transition() is unlocked check-then-act** (Abel's Kings-retro
gripe #2, TECH_DEBT RISK row). Noah proved the parallel lane now SURFACES it:
`test_fault_injection_legacy::test_voltage_scan_compliance_trip_failsafe`
mislabels the terminal state in ~4/6 parallel runs under CPU contention. Our
one green parallel run was a single sample. This is a terminal-state REPORTING
defect, not a flake — fix the race (lock or SM-level invariant), do not
quarantine the test. **Owner: Abel.** Must land before `-n auto` becomes the
bench default.

Also queued: `gui/app_settings.py` accessor so QSettings isolation is
structural rather than a conftest shim (the app names `QSettings("TCT",
"TCTSetup")` in ~6 places; the test suite was writing into the developer's
REAL registry until 2d4684b). **Owner: Noah.**
Also: `pytest-xdist` is installed on the bench venv only — add to
`TCT_app/requirements.txt` if `-n auto` should work on the laptop too.

## LANDED tonight (all pushed)

| Commit | What |
|---|---|
| `5730644` | fail-closed guard on all four scan start paths (Mary REQUEST-CHANGES on dac5b67) |
| `9b91ed1` | 1D map slicer (Jonathan) |
| `c12a6a1` | theme editor + glass_amount override layer (Noah) |
| `7663d74` | z-focus/voltage coordinator slots fail closed (Mary standup find) |
| `8d302fc` | mosaic stitch math A4a (Jonathan) |
| `e3d323f` | bench checklist arm-latch flow + docs index (Samantha) |
| `5e70b10` | UI monkey harness v1 (Abel) — found 2 real GUI bugs |
| `7892a26` | slicer stale-run provenance fix (Mary REQUEST-CHANGES) |
| `c1d552d` | Codex D5 review + monkey findings ledgered |
| `a4d05f6` | **HV ramp behind DangerGate** (rule-2 violation, found by Samantha) |
| `f2b9acc` | RATIFIED: danger-gate boundary, jog stays ungated (Kaya) |
| `3f6e2b7` | **z-focus/voltage arm Pause/Abort — and Pause actually pauses** (Codex find → Abel found the wedge) |
| `9cc14dd` | Coffee Break of Kings: 17 findings → TECH_DEBT |
| `81d1f6a` | orchestrator state externalized (this ledger + `beat_status.ps1`) |
| `99c527e` | CLAUDE.md session-hygiene rules (Kaya-approved) |
| `bf9e009` | **homing / absolute move / centre / zero-here behind DangerGate** (new kind `zero_here`) |

## ONE-LINE DEBT — must land before the app is trusted on a bench

`9c207a1` fixed the controller (a compliance trip now settles ABORTED), but
the VIEWER still paints the green "Scan finished" banner on a trip until one
line exists in `tct_gui.py`:

    coord.error_dialog.connect(self._scan_viewer.on_scan_error)

`ScanViewerPanel.on_scan_error(title, msg)` exists and is test-proven; Abel
could not wire it (tct_gui.py was outside his locks). Mirror it in
`tests/test_scan_viewer_wiring.py::_wire_like_tct_gui` — that helper is the
declared lock-step contract with the composition root. **Owner: Noah.**

## PENDING REVIEWS (Mary)

- theme editor `c12a6a1` — standalone (never stack with another feature).
- Paul's driver-truth batch — safety class, mandatory, when it lands.
- Abel's pause-parking semantics in `3f6e2b7` (he flagged it himself:
  PAUSED→RUNNING→FINISHED promotion + HV holds last voltage while paused).
- Noah's motion gate — when it lands.

## NEXT QUEUED (full list: docs/NIGHT_SHIFT_20260712.md)

1. **A2 QML shell default** (Noah, Kaya-ratified) — unblocked, but must wait
   for Noah's motion gate to land (both hold `tct_gui.py`).
2. Abel safety beats from the Kings retro: unify controller-tier danger-gating
   across all 4 start paths · `StateMachine.transition()` lock · slow-control
   UNAVAILABLE escalation · fuzzer covering voltage/z-focus loops.
3. Jonathan data beats: ref-channel baseline subtraction (biases every saved
   charge today) · silent camera-frame drops · `*_ns` vs `*_s` quantity-name
   mismatch · V_dep fit quality.
4. Noah GUI beats: W1 taxonomy sweep per `docs/design/state_color_census.md` ·
   `scan_map_view` redraw throttle · the 2 monkey-found bugs.

## PARKED — needs Kaya

v5 ratification (14 artifacts) · sequencer envelope semantics · Ollama watcher
restart with GPU env · command-palette allow-list · hover/lag verdict on the
real display.
