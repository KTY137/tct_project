"""gui/scope_panel.py's devices.yaml writers (`_save_scope_keys_to_yaml`,
`_save_trigger_to_yaml`) must preserve comments -- regression coverage for
the comment-eating yaml.safe_load/yaml.dump round trip fixed via
controller/yaml_persist.py (TECH_DEBT.md RISK 2026-07-10, second occurrence
2026-07-11: the waveform_generator level_low_V/level_high_V comment block).

No QApplication/Qt needed: both functions are plain module-level helpers
that take a path and keyword scalars, independent of the ScopePanel widget.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml

from gui.scope_panel import _save_scope_keys_to_yaml, _save_trigger_to_yaml

_DOC = """\
oscilloscope:
  backend: visa
  simulation: false
  trigger_level_V: 1.0
  trigger_slope: FALL
  trigger_source: CH1
waveform_generator:
  amplitude_V: 3.3
  offset_V: 0.0
  simulation: true
  # Default (both commented) = BIPOLAR trigger via amplitude_V/offset_V above
  # (the manual-confirmed safe path). Uncomment BOTH to drive a clean unipolar
  # 0->+V square instead, via SCPI :VOLTage:LOW / :VOLTage:HIGH. When set they
  # take over from amplitude_V/offset_V; both are required and low < high.
  # level_low_V: 0.0
  # level_high_V: 2.5
"""


def _write_doc(tmp_path):
    p = tmp_path / "devices.yaml"
    p.write_text(_DOC, encoding="utf-8")
    return p


def test_save_scope_keys_preserves_wavegen_comment_block(tmp_path):
    p = _write_doc(tmp_path)
    _save_scope_keys_to_yaml(str(p), backend="drs4", n_averages=4)
    text = p.read_text(encoding="utf-8")
    assert "# level_low_V: 0.0" in text
    assert "# level_high_V: 2.5" in text
    cfg = yaml.safe_load(text)
    assert cfg["oscilloscope"]["backend"] == "drs4"
    assert cfg["oscilloscope"]["n_averages"] == 4
    assert cfg["oscilloscope"]["trigger_source"] == "CH1"  # untouched, still merged-in


def test_save_trigger_to_yaml_preserves_wavegen_comment_block(tmp_path):
    p = _write_doc(tmp_path)
    _save_trigger_to_yaml(str(p), "CH2", -0.41, "RISE")
    text = p.read_text(encoding="utf-8")
    assert "# level_low_V: 0.0" in text
    assert "# level_high_V: 2.5" in text
    cfg = yaml.safe_load(text)
    assert cfg["oscilloscope"]["trigger_source"] == "CH2"
    assert cfg["oscilloscope"]["trigger_level_V"] == -0.41
    assert cfg["oscilloscope"]["trigger_slope"] == "RISE"


def test_save_scope_keys_no_path_is_a_silent_noop():
    # Historical "best effort" behaviour: no config path -> nothing happens,
    # no exception.
    _save_scope_keys_to_yaml(None, backend="drs4")


def test_save_scope_keys_missing_file_is_a_silent_noop(tmp_path):
    missing = tmp_path / "does_not_exist.yaml"
    _save_scope_keys_to_yaml(str(missing), backend="drs4")
    assert not missing.exists()
