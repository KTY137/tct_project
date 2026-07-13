"""controller/yaml_persist.py -- the comment-preserving devices.yaml writer.

Regression coverage for the "config-persist round trip eats every comment"
bug (TECH_DEBT.md RISK 2026-07-10, second occurrence 2026-07-11: the
waveform_generator level_low_V/level_high_V unipolar-trigger comment block
was deleted twice by yaml.safe_load -> yaml.dump round trips in
gui/scope_panel.py and gui/settings_window.py).
"""
from __future__ import annotations

import textwrap

import yaml

from controller.yaml_persist import merge_yaml_text, update_yaml_file

# A trimmed stand-in for configs/devices.yaml with the exact comment block
# that was destroyed twice -- pinned verbatim as the regression case.
_WAVEGEN_DOC = textwrap.dedent("""\
    oscilloscope:
      backend: visa
      simulation: true
      trigger_level_V: 1.0
      trigger_slope: FALL
      trigger_source: CH1
    waveform_generator:
      visa_address: TCPIP0::192.168.0.10::INSTR
      vendor: rigol
      amplitude_V: 3.3
      offset_V: 0.0
      simulation: true
      # Default (both commented) = BIPOLAR trigger via amplitude_V/offset_V above
      # (the manual-confirmed safe path). Uncomment BOTH to drive a clean unipolar
      # 0->+V square instead, via SCPI :VOLTage:LOW / :VOLTage:HIGH. When set they
      # take over from amplitude_V/offset_V; both are required and low < high.
      # level_low_V: 0.0
      # level_high_V: 2.5
    motor_stage:
      backend: grbl
      simulation: true
      software_limits:
        x_min_mm: 1.0
        x_max_mm: 296.0
    """)


def test_wavegen_comment_block_survives_scope_key_update():
    """The pinned regression case: updating an unrelated oscilloscope key
    must not touch the waveform_generator comment block at all."""
    new_text = merge_yaml_text(_WAVEGEN_DOC, {"oscilloscope": {"trigger_source": "CH2"}})
    for line in (
        "  # Default (both commented) = BIPOLAR trigger via amplitude_V/offset_V above",
        "  # (the manual-confirmed safe path). Uncomment BOTH to drive a clean unipolar",
        "  # 0->+V square instead, via SCPI :VOLTage:LOW / :VOLTage:HIGH. When set they",
        "  # take over from amplitude_V/offset_V; both are required and low < high.",
        "  # level_low_V: 0.0",
        "  # level_high_V: 2.5",
    ):
        assert line in new_text, f"comment line lost: {line!r}"
    # And the actual value did update.
    cfg = yaml.safe_load(new_text)
    assert cfg["oscilloscope"]["trigger_source"] == "CH2"


def test_wavegen_comment_block_survives_its_own_section_update():
    """Updating a *sibling* key inside waveform_generator itself (not the
    commented-out level_low_V/level_high_V) must also leave the comment
    block untouched."""
    new_text = merge_yaml_text(_WAVEGEN_DOC, {"waveform_generator": {"amplitude_V": 5.0}})
    assert "# level_low_V: 0.0" in new_text
    assert "# level_high_V: 2.5" in new_text
    cfg = yaml.safe_load(new_text)
    assert cfg["waveform_generator"]["amplitude_V"] == 5.0
    assert "level_low_V" not in cfg["waveform_generator"]  # still commented out


def test_updates_only_named_keys_rest_is_byte_identical():
    new_text = merge_yaml_text(_WAVEGEN_DOC, {"oscilloscope": {"simulation": False}})
    old_lines = _WAVEGEN_DOC.splitlines()
    new_lines = new_text.splitlines()
    assert len(old_lines) == len(new_lines)
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    assert changed == [old_lines.index("  simulation: true")]


def test_nested_key_update_motor_stage_software_limits():
    new_text = merge_yaml_text(
        _WAVEGEN_DOC, {"motor_stage": {"software_limits": {"x_min_mm": 2.5}}}
    )
    cfg = yaml.safe_load(new_text)
    assert cfg["motor_stage"]["software_limits"]["x_min_mm"] == 2.5
    assert cfg["motor_stage"]["software_limits"]["x_max_mm"] == 296.0  # untouched
    assert "# Default (both commented)" in new_text


def test_missing_leaf_key_is_appended_not_fabricated_elsewhere():
    """Switching the motor backend introduces keys (e.g. velocity for 'pi')
    that don't exist yet in the file -- they must be appended, not silently
    dropped, and must not disturb anything else."""
    new_text = merge_yaml_text(_WAVEGEN_DOC, {"motor_stage": {"velocity": 2.0}})
    cfg = yaml.safe_load(new_text)
    assert cfg["motor_stage"]["velocity"] == 2.0
    assert cfg["motor_stage"]["backend"] == "grbl"
    assert "# level_low_V: 0.0" in new_text


def test_missing_section_is_appended_at_end_of_file():
    new_text = merge_yaml_text(_WAVEGEN_DOC, {"laser": {"wavelength_nm": 660}})
    cfg = yaml.safe_load(new_text)
    assert cfg["laser"]["wavelength_nm"] == 660
    assert "# level_low_V: 0.0" in new_text


def test_boolean_and_none_scalar_rendering_matches_pyyaml_style():
    new_text = merge_yaml_text(_WAVEGEN_DOC, {"oscilloscope": {"simulation": True}})
    assert "simulation: true" in new_text
    new_text2 = merge_yaml_text(_WAVEGEN_DOC, {"oscilloscope": {"simulation": False}})
    assert "simulation: false" in new_text2


def test_quoted_numeric_looking_string_stays_quoted():
    new_text = merge_yaml_text(_WAVEGEN_DOC, {"oscilloscope": {"trigger_source": "19112408"}})
    cfg = yaml.safe_load(new_text)
    assert cfg["oscilloscope"]["trigger_source"] == "19112408"
    assert "'19112408'" in new_text  # quoted, not re-parsed as an int


def test_no_op_update_returns_text_unchanged():
    assert merge_yaml_text(_WAVEGEN_DOC, {}) == _WAVEGEN_DOC


def test_update_yaml_file_round_trip(tmp_path):
    p = tmp_path / "devices.yaml"
    p.write_text(_WAVEGEN_DOC, encoding="utf-8")
    update_yaml_file(p, {"oscilloscope": {"trigger_source": "CH3"}})
    text = p.read_text(encoding="utf-8")
    assert "# level_low_V: 0.0" in text
    assert yaml.safe_load(text)["oscilloscope"]["trigger_source"] == "CH3"


def test_update_yaml_file_atomic_path_preserves_content_and_comments(tmp_path):
    """The atomic write path (temp file + os.replace) must yield a file that is
    byte-identical to computing merge_yaml_text in memory -- comments and all."""
    p = tmp_path / "devices.yaml"
    p.write_text(_WAVEGEN_DOC, encoding="utf-8")
    update_yaml_file(p, {"oscilloscope": {"trigger_source": "CH3"}})
    on_disk = p.read_text(encoding="utf-8")
    assert on_disk == merge_yaml_text(_WAVEGEN_DOC, {"oscilloscope": {"trigger_source": "CH3"}})
    assert "# level_low_V: 0.0" in on_disk


def test_update_yaml_file_failed_write_leaves_original_untouched(tmp_path, monkeypatch):
    """A crash during the atomic replace must leave the ORIGINAL file intact
    (soft limits / HV ranges live here) and must not leak a temp file."""
    import controller.yaml_persist as yp

    p = tmp_path / "devices.yaml"
    p.write_text(_WAVEGEN_DOC, encoding="utf-8")

    def boom(*_a, **_k):
        raise OSError("simulated crash during replace")

    monkeypatch.setattr(yp.os, "replace", boom)
    try:
        update_yaml_file(p, {"oscilloscope": {"trigger_source": "CH9"}})
    except OSError:
        pass
    else:  # pragma: no cover - the monkeypatched replace must raise
        raise AssertionError("expected the simulated write failure to propagate")

    # Original content is byte-for-byte intact.
    assert p.read_text(encoding="utf-8") == _WAVEGEN_DOC
    # No stray temp files left behind in the directory.
    leftovers = [q.name for q in tmp_path.iterdir() if q.name != "devices.yaml"]
    assert leftovers == [], f"temp file(s) leaked: {leftovers}"


def test_no_trailing_newline_preserved():
    doc = _WAVEGEN_DOC.rstrip("\n")
    new_text = merge_yaml_text(doc, {"oscilloscope": {"trigger_source": "CH4"}})
    assert not new_text.endswith("\n\n")
    assert not doc.endswith("\n")
    assert not new_text.endswith("\n")


# --------------------------------------------------------------------------- #
# List-valued leaves (Mary review, 2026-07-11): _yaml_scalar_text used to     #
# silently render a list leaf as an EMPTY value ("axes:" -> parses as null)   #
# because yaml.safe_dump's default block style for a list is multi-line and  #
# the ':' partition on the first line yielded ''. Fixed by flow-style-       #
# rendering list/tuple leaves onto the single key: [..] line this module's   #
# rewrite/append paths already produce.                                      #
# --------------------------------------------------------------------------- #

def test_list_leaf_in_place_rewrite_round_trips():
    doc = textwrap.dedent("""\
        motor_stage:
          backend: pi
          axes:
          - 1
          - 2
          - 3
        """)
    new_text = merge_yaml_text(doc, {"motor_stage": {"axes": [4, 5, 6]}})
    assert "axes: [4, 5, 6]" in new_text
    cfg = yaml.safe_load(new_text)
    assert cfg["motor_stage"]["axes"] == [4, 5, 6]


def test_list_leaf_append_round_trips():
    new_text = merge_yaml_text(_WAVEGEN_DOC, {"motor_stage": {"axes": [1, 2, 3]}})
    assert "axes: [1, 2, 3]" in new_text
    cfg = yaml.safe_load(new_text)
    assert cfg["motor_stage"]["axes"] == [1, 2, 3]
    assert "# level_low_V: 0.0" in new_text  # unrelated comment block untouched


def test_pi_branch_to_dict_axes_survives_quick_settings_merge():
    """The actual shipping caller pinned: _MotorSection.to_dict()'s PI branch
    (gui/settings_window.py) emits ``"axes": [1, 2, 3]`` alongside other PI
    keys -- a Quick-Settings save after switching motor_stage to "pi" must
    not corrupt axes to null."""
    pi_to_dict = {
        "backend": "pi",
        "model": "custom",
        "simulation": False,
        "serial_port": "COM3",
        "velocity": 2.0,
        "baudrate_pi": 115200,
        "axes": [1, 2, 3],
    }
    new_text = merge_yaml_text(_WAVEGEN_DOC, {"motor_stage": pi_to_dict})
    cfg = yaml.safe_load(new_text)
    assert cfg["motor_stage"]["axes"] == [1, 2, 3]
    assert cfg["motor_stage"]["backend"] == "pi"
    assert cfg["motor_stage"]["velocity"] == 2.0
    assert "# level_low_V: 0.0" in new_text
