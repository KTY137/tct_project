"""Config-validator tests, including the real-world contradiction that
motivated it (marlin: true with a GRBL-style negative limits envelope)."""
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
    """Smoke test: the live devices.yaml parses and the validator runs on it.

    NOTE the shipped config currently carries a known contradiction
    (marlin: true + GRBL-style negative software_limits) that the motor
    revamp will resolve; until then the validator is *expected* to flag the
    motor_stage section, and connect_all() refuses to run with it.
    """
    from pathlib import Path
    import yaml
    path = Path(__file__).resolve().parent.parent / "configs" / "devices.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    issues = validate_config(cfg)
    assert isinstance(issues, list)
    for e in errors(issues):
        assert "motor_stage" in e, f"unexpected non-motor config error: {e}"
