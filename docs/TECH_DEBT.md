# Tech-debt & gripes ledger

Living record of known drift, debt, and "someone should fix this" items, fed by
the **Coffee Break / Standup protocol** (see `.claude/AGENT_PROTOCOL.md`).
Kiroku curates it; Adam ranks by risk. Each item: severity, what, where, owner,
date noticed. Remove items when resolved (note the fix in the git history, not here).

Severity: **BLOCKER** (unsafe / broken) > **RISK** (latent bug / safety-adjacent) >
**ANNOYANCE** (friction, papercut) > **NIT** (cosmetic).

| Sev | Item | Where | Owner | Noticed |
|---|---|---|---|---|
| RISK | `tct_gui.py` is trending toward a God object (~870 lines: panels, wiring, connect/scan orchestration, shutdown). Extract ConnectionController / ScanCoordinator / shutdown unit. | `TCT_app/tct_gui.py` | Noah | 2026-07-06 |
| RISK | `tek_fastframe` scope backend is non-functional — vendored `dustin_scope` package missing from `TCT_app/vendor/`; targets MSO5204B, not the bench TBS1052C. | `TCT_app/devices/oscilloscope_tek_fastframe.py` | Paul | 2026-07-06 |
| RISK | Only the oscilloscope implements `is_alive()`; motor/bias/camera still use the flag-based default, so a yanked cable on those shows CONNECTED. (Bias HV probe needs a cited manual command first.) | `TCT_app/devices/*` | Paul | 2026-07-06 |
| ANNOYANCE | `_OscilloscopeSection.to_dict()` hardcodes DRS4 `trigger_source`/`time_correction`/`t0_ns` regardless of form state — no UI control. | `TCT_app/gui/settings_window.py` | Noah | 2026-07-06 |
| TODO(bench) | Confirm the iseg polarity relay settle time; the 0.5 s confirm budget (`_POL_CONFIRM_BUDGET_S`) is an unverified guess flagged in the research note. | `TCT_app/devices/bias_supply_iseg.py` | Paul | 2026-07-06 |
| RISK | Real `IsegBiasSupply.set_polarity` gate logic has no automated coverage — tests exercise only the simulated backend. Add fake-`_inst` tests for the refuse-on-Is-On / refuse-above-threshold / refuse-on-None-status / confirm-timeout paths. | `TCT_app/tests/test_bias_polarity.py` | Paul | 2026-07-06 |
| TODO(bench) | Verify `CH1:PRObe:GAIN?` and `CH1:COUPling?` query forms answer on the TBS1052C; if model-specific, guard like the WFMOutpre?/WFMPre? fallback. | `TCT_app/devices/oscilloscope.py` | Paul | 2026-07-06 |
| TODO(bench) | Verify iseg SCPI token forms on real HV: lowercase p/n accepted, `:READ:CHAN:STAT?` bit3=Is-On, `:CONF:OUTP:POL:LIST?` / `:READ:MODULE:CHANNELNUMBER?` reply formats. | `TCT_app/devices/bias_supply_iseg.py` | Paul | 2026-07-06 |
| NIT | Scope `apply_chan_config` reports success even when zero channels are enabled (nothing sent). | `TCT_app/gui/scope_panel.py` | Noah | 2026-07-06 |
| NIT | `set_output_load` formats numeric loads with `:g` → scientific notation for large ohms a Rigol may reject (low impact; GUI only offers INFinity/50). | `TCT_app/devices/waveform_generator.py` | Paul | 2026-07-06 |
| MINOR | During global ALL-OUTPUTS-OFF, per-panel Ramp/Output buttons stay enabled → a contradictory per-tab ramp can interleave. Disable per-panel controls for the duration. | `TCT_app/gui/multi_bias_panel.py` | Noah | 2026-07-06 |
| MINOR | `_ReadoutPoller` (and `_BiasPoller`) `deleteLater` is posted after the thread loop exits → poller+timer leak one per rebuild/reload. Delete explicitly after `wait()`. Pre-existing pattern. | `TCT_app/gui/bias_panel.py` | Noah | 2026-07-06 |
| MINOR | Bias+Waveform (vscan) Start button is live on non-primary bias tabs but wired only for the primary → dead control on CH1+. Hide/disable vscan on non-primary panels. | `TCT_app/gui/bias_panel.py` | Noah | 2026-07-06 |
| NIT | statusChip unlisted-state renders neutral silently: a panel setting an unlisted `state` value (e.g. "error") gets a neutral pill with no warning. Docstring already lists valid set; acceptable as-is, logged for awareness. | `TCT_app/gui/style.py` | Noah | 2026-07-06 |
| NIT | warn chip contrast on light theme: warn `#d98c17` chip text over a 0.16-alpha tint on light bg is borderline for contrast; legible at font-weight 700 but could be darkened for light theme. Non-blocking. | `TCT_app/gui/style.py` | Noah | 2026-07-06 |
| ANNOYANCE | `influx.measurement` consumed by `data/influx_writer.py:39` (default `"slow_control"`) but absent from shipped `configs/devices.yaml` — document or add to example config. | `TCT_app/data/influx_writer.py` | Paul | 2026-07-07 |
| ANNOYANCE | Nested config dicts (`output.save.*`, `charge_calibration.reference.*`, `slow_control.channels[].*`) still not typo-checked — same boundary as `motor_stage.software_limits`; candidate for recursive known-keys pass. | `TCT_app/controller/config_validator.py` | Paul | 2026-07-07 |
| RISK | Executor resume-after-abort must RE-ASSERT HV state: `compile_plan` emits a deduped BiasStep list, so "resume from step N" would skip the re-ramp — executor must re-establish bias on resume, never trust the deduped list. (**Must-do in step 2**; Mary residual-risk note from M2.2 step-1 review.) | `TCT_app/controller/scan_controller.py` | Abel | 2026-07-07 |
