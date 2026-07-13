"""Config-validator tests, including the real-world contradiction that
motivated it (marlin: true with a GRBL-style negative limits envelope)."""
import pytest

from controller.config_validator import (
    validate_config, errors, warnings, ERROR, WARNING,
)


def _motor(**over):
    cfg = {
        "backend": "grbl",
        "marlin": True,
        "feed_rate_mm_min": 1500,
        "software_limits": {
            "x_min_mm": 0.0, "x_max_mm": 300.0,
            "y_min_mm": 0.0, "y_max_mm": 300.0,
            "z_min_mm": 0.0, "z_max_mm": 400.0,
        },
    }
    cfg.update(over)
    return cfg


def test_clean_config_has_no_errors():
    issues = validate_config({"motor_stage": _motor()})
    assert errors(issues) == []


def test_marlin_with_negative_envelope_is_error():
    """The exact contradiction that shipped in devices.yaml."""
    cfg = {"motor_stage": _motor(software_limits={
        "x_min_mm": -300.0, "x_max_mm": 0.0,
        "y_min_mm": -300.0, "y_max_mm": 0.0,
        "z_min_mm": -400.0, "z_max_mm": 0.0,
    })}
    errs = errors(validate_config(cfg))
    assert any("marlin" in e.lower() and "negative" in e.lower() for e in errs)


def test_min_ge_max_is_error():
    cfg = {"motor_stage": _motor(software_limits={
        "x_min_mm": 100.0, "x_max_mm": 50.0})}
    assert any("min" in e for e in errors(validate_config(cfg)))


def test_swapped_limits_is_error_naming_axis_and_values():
    """The exact shipped bug: x_min=300, x_max=0 blocks every move.

    Must be an explicit ERROR that names the axis AND both values (so an
    operator can see and fix it), not a silent pass."""
    cfg = {"motor_stage": _motor(software_limits={
        "x_min_mm": 300.0, "x_max_mm": 0.0})}
    errs = errors(validate_config(cfg))
    assert any("x" in e and "300" in e and "0" in e and "SWAP" in e.upper()
               for e in errs), errs


def test_zero_width_axis_is_error():
    """A zero-width axis (min == max) leaves one reachable point → ERROR."""
    cfg = {"motor_stage": _motor(software_limits={
        "z_min_mm": 5.0, "z_max_mm": 5.0})}
    errs = errors(validate_config(cfg))
    assert any("z" in e and "ZERO-WIDTH" in e.upper() for e in errs), errs


def test_push_steps_with_marlin_warns():
    cfg = {"motor_stage": _motor(push_steps_to_grbl=True)}
    assert any("push_steps_to_grbl" in w for w in warnings(validate_config(cfg)))


def test_unknown_key_warns():
    cfg = {"motor_stage": _motor(feedrate_mm_min=1500)}  # typo'd key
    assert any("feedrate_mm_min" in w for w in warnings(validate_config(cfg)))


def test_scope_trigger_key_mismatch_warns():
    cfg = {"oscilloscope": {"backend": "drs4", "trigger_slope": "FALL"}}
    assert any("trigger_edge" in w for w in warnings(validate_config(cfg)))


def test_visa_scope_without_address_is_error():
    cfg = {"oscilloscope": {"backend": "visa", "simulation": False}}
    assert errors(validate_config(cfg))


def test_bad_compliance_is_error():
    cfg = {"bias_supply": {"backend": "iseg", "compliance_A": 0}}
    assert any("compliance_A" in e for e in errors(validate_config(cfg)))


def test_bad_analysis_window_is_error():
    cfg = {"analysis": {"integration_window_s": [1.5e-7, 2.0e-8]}}  # reversed
    assert any("integration_window_s" in e for e in errors(validate_config(cfg)))


def test_current_shipped_yaml_parses_and_validates():
    """The live devices.yaml parses and validates with zero blocking errors.

    The historical contradiction (marlin: true + a GRBL-style negative,
    swapped-limits envelope where x_min=300 > x_max=0) has been fixed in the
    shipped config — a positive 0..296 / 0..298 / 0..400 envelope — so the
    validator must now find NO errors at all.  (push_steps_to_grbl + marlin is
    still a WARNING, which does not block connect_all.)
    """
    from pathlib import Path
    import yaml
    path = Path(__file__).resolve().parent.parent / "configs" / "devices.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    issues = validate_config(cfg)
    assert isinstance(issues, list)
    assert errors(issues) == [], \
        f"shipped devices.yaml should validate clean: {errors(issues)}"


# --------------------------------------------------------------------------- #
# Coverage for previously unvalidated sections (Phase-3 robustness):           #
# camera, laser, slow_control, influx, output, charge_calibration.             #
# Before this, typos in these blocks were silently ignored.                    #
# --------------------------------------------------------------------------- #

_COVERAGE_SECTIONS = [
    "camera", "laser", "slow_control", "influx", "output", "charge_calibration",
]


@pytest.mark.parametrize("section", _COVERAGE_SECTIONS)
def test_unknown_key_in_covered_section_warns(section):
    """An unknown/typo'd key in each newly-covered section warns, naming it."""
    cfg = {section: {"definitely_not_a_real_key": 123}}
    issues = validate_config(cfg)
    ws = warnings(issues)
    assert any("definitely_not_a_real_key" in w and section in w for w in ws), \
        f"expected a warning naming {section} + the bogus key, got {ws}"
    # Typos are advisory only — never a blocking error.
    assert errors(issues) == []


@pytest.mark.parametrize("section", _COVERAGE_SECTIONS)
def test_missing_covered_section_does_not_error(section):
    """A config that omits an optional section must not error on it."""
    issues = validate_config({"motor_stage": _motor()})  # no coverage sections
    assert not any(section in str(i) for i in issues)


def test_shipped_yaml_covered_sections_are_clean():
    """The real devices.yaml must produce zero warnings in the covered sections
    (guards that each known-key set is complete for the shipped config)."""
    from pathlib import Path
    import yaml
    path = Path(__file__).resolve().parent.parent / "configs" / "devices.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    ws = warnings(validate_config(cfg))
    for section in _COVERAGE_SECTIONS:
        offending = [w for w in ws if w.startswith(f"[{section}]")]
        assert offending == [], \
            f"shipped devices.yaml produced warnings in {section}: {offending}"


# --------------------------------------------------------------------------- #
# Waveform generator: opt-in unipolar rails (level_low_V / level_high_V).       #
# Bipolar (both absent) is the default and must validate clean; the pair is     #
# both-or-neither, numeric, low < high.                                         #
# --------------------------------------------------------------------------- #

def test_wfg_no_levels_is_clean():
    """Bipolar default (no level keys) must produce no waveform_generator issues."""
    cfg = {"waveform_generator": {
        "vendor": "rigol", "frequency_hz": 1000, "amplitude_V": 3.3,
        "offset_V": 0.0, "output_load": 50, "simulation": True,
    }}
    issues = validate_config(cfg)
    assert not any(str(i).startswith("[waveform_generator]") for i in issues), issues


def test_wfg_valid_level_pair_is_clean():
    """A valid low < high rail pair validates with zero errors/warnings."""
    cfg = {"waveform_generator": {
        "simulation": True, "level_low_V": 0.0, "level_high_V": 2.5,
    }}
    issues = validate_config(cfg)
    assert errors(issues) == [], errors(issues)
    assert not any(str(i).startswith("[waveform_generator]") for i in issues), issues


def test_wfg_low_ge_high_is_error():
    """level_low_V >= level_high_V is an ERROR (the driver's set_levels rejects it)."""
    cfg = {"waveform_generator": {
        "simulation": True, "level_low_V": 2.5, "level_high_V": 2.5,
    }}
    errs = errors(validate_config(cfg))
    assert any("level_low_V" in e and "level_high_V" in e for e in errs), errs
    cfg2 = {"waveform_generator": {
        "simulation": True, "level_low_V": 3.0, "level_high_V": 1.0,
    }}
    assert any("level_low_V" in e for e in errors(validate_config(cfg2)))


def test_wfg_lone_level_key_is_error():
    """A lone level key (silently reverts to bipolar) is an ERROR, both ways."""
    only_low = {"waveform_generator": {"simulation": True, "level_low_V": 0.0}}
    errs = errors(validate_config(only_low))
    assert any("level_high_V" in e and "BOTH" in e for e in errs), errs
    only_high = {"waveform_generator": {"simulation": True, "level_high_V": 2.5}}
    errs = errors(validate_config(only_high))
    assert any("level_low_V" in e and "BOTH" in e for e in errs), errs


def test_wfg_non_numeric_level_is_error():
    cfg = {"waveform_generator": {
        "simulation": True, "level_low_V": "zero", "level_high_V": 2.5,
    }}
    assert any("numeric" in e for e in errors(validate_config(cfg)))


def test_wfg_nan_or_inf_level_is_error():
    """YAML `.nan` passes numeric checks but every NaN comparison is False —
    it would silently bypass the low < high guard AND the driver's own
    set_levels() rejection. Same for `.inf`. Both must be refused."""
    cfg = {"waveform_generator": {
        "simulation": True, "level_low_V": float("nan"), "level_high_V": 2.5,
    }}
    assert any("finite" in e for e in errors(validate_config(cfg)))
    cfg2 = {"waveform_generator": {
        "simulation": True, "level_low_V": 0.0, "level_high_V": float("inf"),
    }}
    assert any("finite" in e for e in errors(validate_config(cfg2)))


def test_wfg_level_keys_are_known():
    """The two new keys are recognised (no unknown-key typo warning)."""
    cfg = {"waveform_generator": {
        "simulation": True, "level_low_V": 0.0, "level_high_V": 2.5,
    }}
    ws = warnings(validate_config(cfg))
    assert not any("level_low_V" in w or "level_high_V" in w for w in ws), ws


def test_covered_section_real_keys_do_not_warn():
    """A block using every real key of a covered section stays warning-free."""
    cfg = {"camera": {
        "serial_number": "19112408", "exposure_us": 5000.0, "gain_db": 0.0,
        "pixel_format": "Mono8", "gamma_enabled": True, "gamma_value": 1.0,
        "binning": 1, "fps": 10.0, "simulation": True,
    }}
    assert not any(w.startswith("[camera]") for w in warnings(validate_config(cfg)))


# --------------------------------------------------------------------------- #
# bias_supply.sim_channel_count — the SIMULATION-ONLY HV channel count, and    #
# its interaction with `channel` (the PRIMARY channel INDEX).                  #
#                                                                              #
# Gap it closes: the multi-channel bias machinery (BiasChannel views, one GUI  #
# tab per channel, ALL OUTPUTS OFF over every channel, plan safety             #
# 'bias_channel') was unreachable in simulation — the normal dev mode and the  #
# mode every test runs in — because DeviceManager built a bare                 #
# SimulatedBiasSupply() (count always 1) and no config key existed at all.     #
# --------------------------------------------------------------------------- #
def _bias_sim(**over):
    cfg = {"backend": "simulated"}
    cfg.update(over)
    return {"bias_supply": cfg}


def test_sim_channel_count_absent_is_clean():
    """Optional key: omitting it must behave exactly as before (count 1)."""
    issues = validate_config(_bias_sim())
    assert errors(issues) == []
    assert not any("sim_channel_count" in w for w in warnings(issues))


def test_sim_channel_count_valid_is_clean():
    issues = validate_config(_bias_sim(sim_channel_count=3))
    assert errors(issues) == []
    # And it is a KNOWN key — no "unknown key" typo warning.
    assert not any("sim_channel_count" in w for w in warnings(issues))


@pytest.mark.parametrize("bad", [0, -1, 2.5, "3", True, [3]])
def test_sim_channel_count_bad_value_is_error(bad):
    """0 / negative / non-integer must be a blocking ERROR, never a silent 1."""
    assert any("sim_channel_count" in e
               for e in errors(validate_config(_bias_sim(sim_channel_count=bad))))


def test_sim_channel_count_above_ceiling_is_error():
    assert any("sim_channel_count" in e
               for e in errors(validate_config(_bias_sim(sim_channel_count=17))))


def test_sim_channel_count_at_ceiling_is_ok():
    assert errors(validate_config(_bias_sim(sim_channel_count=16))) == []


def test_sim_channel_count_on_real_backend_warns_as_ignored():
    """It is a simulation-only knob: on a real backend (even simulation: true)
    the channel count comes from the hardware, so the key is WARNED as ignored —
    never silently obeyed, and never an error that blocks connecting."""
    cfg = {"bias_supply": {"backend": "iseg", "simulation": True,
                           "visa_address": "ASRL6::INSTR", "channel": 0,
                           "sim_channel_count": 3}}
    issues = validate_config(cfg)
    assert errors(issues) == []
    assert any("sim_channel_count" in w and "IGNORED" in w for w in warnings(issues))


def test_primary_channel_outside_sim_channel_count_is_error():
    """channel (primary INDEX) >= sim_channel_count addresses a channel the
    supply does not expose — a hard config error, not a phantom extra tab."""
    issues = validate_config(_bias_sim(channel=2, sim_channel_count=1))
    assert any("channel" in e and "primary" in e.lower() for e in errors(issues))
    # Same when no count is configured at all (implicit count of 1).
    assert any("channel" in e
               for e in errors(validate_config(_bias_sim(channel=2))))


def test_primary_channel_inside_sim_channel_count_is_clean():
    assert errors(validate_config(_bias_sim(channel=2, sim_channel_count=3))) == []


@pytest.mark.parametrize("bad", [-1, 1.5, "0", True])
def test_bad_primary_channel_index_is_error(bad):
    assert any("channel" in e
               for e in errors(validate_config(_bias_sim(channel=bad))))


def test_real_backend_primary_channel_is_not_bounded_by_the_sim_key():
    """A real module's channel count is hardware truth, unknowable here — so a
    high primary index on a real backend must NOT be rejected by the sim key."""
    cfg = {"bias_supply": {"backend": "iseg", "visa_address": "ASRL6::INSTR",
                           "channel": 3}}
    assert errors(validate_config(cfg)) == []


# --------------------------------------------------------------------------- #
# slow_control channel NAMES → permanent capability_id (§5.1.1).                #
#                                                                              #
# The naming truth lives in capabilities/model.py::slow_control_capability_id; #
# the validator IMPORTS and CALLS it (controller/ may import capabilities/,    #
# spec §2), so there is ONE source and nothing to keep in sync — pinned by     #
# test_validator_shares_model_capability_id below. Four names are grandfathered #
# forever; any NEW name must be lowercase [a-z][a-z0-9_]* and must not collide  #
# with a grandfathered alias target; two channels may never share one id.       #
# --------------------------------------------------------------------------- #

_SHIPPED_SLOW_CONTROL_NAMES = [
    "temperature_C", "humidity_pct", "bias_voltage_V", "leakage_current_nA",
]


def _sc_names(*names):
    """A slow_control block whose channels carry only the given names."""
    return {"slow_control": {"channels": [{"name": n} for n in names]}}


def test_shipped_slow_control_names_validate_clean():
    """Each grandfathered shipped channel name is accepted, alone and together."""
    for name in _SHIPPED_SLOW_CONTROL_NAMES:
        assert errors(validate_config(_sc_names(name))) == [], name
    assert errors(validate_config(_sc_names(*_SHIPPED_SLOW_CONTROL_NAMES))) == []


def test_conforming_new_slow_control_name_is_clean():
    """A brand-new lowercase name that does not collide validates clean."""
    assert errors(validate_config(_sc_names("dew_point_c"))) == []


@pytest.mark.parametrize("bad", [
    "Temperature",   # uppercase
    "temp-c",        # hyphen
    "1temp",         # leading digit
    "temp c",        # space
    "_temp",         # leading underscore
    "temp.c",        # dot
])
def test_bad_charset_slow_control_name_is_error(bad):
    """A name that is neither grandfathered nor [a-z][a-z0-9_]* is refused,
    because it would otherwise become a PERMANENT capability_id."""
    errs = errors(validate_config(_sc_names(bad)))
    assert any(bad in e for e in errs), errs
    assert any("capability_id" in e for e in errs), errs


def test_new_name_colliding_with_alias_target_is_error():
    """Direction 1: a NEW channel literally named 'temperature' collides with the
    permanent alias target of grandfathered 'temperature_C' — even when the
    grandfathered sibling is absent (the id is reserved forever)."""
    errs = errors(validate_config(_sc_names("temperature")))
    assert any("temperature" in e and "slow_control.temperature" in e
               for e in errs), errs


def test_grandfathered_plus_colliding_new_name_is_error():
    """Direction 2: both 'temperature_C' (→ slow_control.temperature) and a new
    'temperature' present — still an ERROR, order-independent."""
    for names in (("temperature_C", "temperature"),
                  ("temperature", "temperature_C")):
        errs = errors(validate_config(_sc_names(*names)))
        assert any("temperature" in e for e in errs), (names, errs)


def test_duplicate_slow_control_name_is_error():
    """Two channels with the SAME name map to one id — a hard ERROR (each name
    is a permanent capability_id, and connect_all keys results by name)."""
    errs = errors(validate_config(_sc_names("dew_point_c", "dew_point_c")))
    assert any("dew_point_c" in e and "once" in e.lower() for e in errs), errs
    # Duplicate GRANDFATHERED names collide the same way (both → one alias id).
    errs2 = errors(validate_config(_sc_names("temperature_C", "temperature_C")))
    assert any("temperature_C" in e for e in errs2), errs2


def test_two_distinct_valid_names_do_not_collide():
    """Distinct conforming names map to distinct ids → no collision."""
    assert errors(validate_config(_sc_names("sensor_a", "sensor_b"))) == []


def test_validator_shares_model_capability_id():
    """The single-source guarantee: the validator holds the SAME function object
    as capabilities/model.py (imported, not duplicated) — so the naming rule can
    never drift between the two halves. Whatever the model refuses, the validator
    errors on; whatever it accepts, validates clean."""
    from capabilities.model import slow_control_capability_id as model_fn
    from controller import config_validator
    assert config_validator.slow_control_capability_id is model_fn
    # Accepted by the model → clean in the validator.
    model_fn("my_new_sensor")  # does not raise
    assert errors(validate_config(_sc_names("my_new_sensor"))) == []
    # Refused by the model → error in the validator.
    with pytest.raises(ValueError):
        model_fn("Bad Name")
    assert errors(validate_config(_sc_names("Bad Name")))


def test_non_string_slow_control_name_is_not_a_naming_error():
    """A missing/non-string name is out of this check's scope (the capability
    layer/manager owns it) — it must not raise or emit a naming ERROR here."""
    issues = validate_config({"slow_control": {"channels": [{"unit": "C"}]}})
    assert not any("capability_id" in str(i) for i in issues)
    issues2 = validate_config({"slow_control": {"channels": [{"name": 123}]}})
    assert not any("capability_id" in str(i) for i in issues2)


def test_shipped_yaml_slow_control_names_are_clean():
    """The live devices.yaml's four slow-control channel names validate clean."""
    from pathlib import Path
    import yaml
    path = Path(__file__).resolve().parent.parent / "configs" / "devices.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    sc_errs = [e for e in errors(validate_config(cfg)) if e.startswith("[slow_control]")]
    assert sc_errs == [], sc_errs
