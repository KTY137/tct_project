"""Tests for the capability spine's data model (D1a, ``capabilities/model.py``).

Normative spec: ``docs/CAPABILITY_MODEL.md`` v1.0-rc — section references
below (§n) point into it.  This file is deliberately Qt-free bucket-A
material: stdlib + pytest + ``capabilities`` only (the model itself is
stdlib-only by LAW §2.1, pinned by ``test_model_module_is_stdlib_only``
below; since D1b the layer-contract suite carries the package-wide duty and
this pin guards model.py itself, relative imports included).
"""
from __future__ import annotations

import ast
import dataclasses
import json
import sys
from pathlib import Path

import pytest

from capabilities.model import (
    CAPABILITY_ID_PATTERN,
    MODEL_VERSION,
    SLOW_CONTROL_CHANNEL_ALIASES,
    CapabilityDescriptor,
    FrameSource,
    HVSource,
    Motion3D,
    Operation,
    ReadableChannel,
    ReadbackPolicy,
    SafetyClass,
    SweepableParameter,
    TriggerSource,
    WaveformSource,
    slow_control_capability_id,
)

# --------------------------------------------------------------------------- #
# Factories (spec-seed-vocabulary shaped, §5.1)                                #
# --------------------------------------------------------------------------- #


def make_base(**over):
    kw = dict(
        capability_id="camera.frame",
        device_id="camera",
        transport_id="camera",
        label="Camera frame",
        safety_class=SafetyClass.BENIGN,
        metadata={},
    )
    kw.update(over)
    return CapabilityDescriptor(**kw)


def make_sweep(**over):
    kw = dict(
        capability_id="stage.x",
        device_id="motor",
        transport_id="motor",
        label="Stage X",
        safety_class=SafetyClass.MOTION,
        metadata={},
        unit="mm",
        limits=(0.0, 100.0),
        resolution=0.001,
    )
    kw.update(over)
    return SweepableParameter(**kw)


def make_hv(**over):
    kw = dict(
        capability_id="bias.voltage",
        device_id="bias_supply",
        transport_id="bias_supply",
        label="Bias voltage (primary channel)",
        safety_class=SafetyClass.HV,
        metadata={},
        unit="V",
        limits=(-1000.0, 0.0),
        resolution=None,
        settle_s=0.5,
        readback=ReadbackPolicy.BEST_EFFORT,
        polarity="n",
        channel=0,
    )
    kw.update(over)
    return HVSource(**kw)


# --------------------------------------------------------------------------- #
# §7.1 SafetyClass total ordering                                              #
# --------------------------------------------------------------------------- #


def test_safety_class_members_and_declaration_order():
    assert [m.name for m in SafetyClass] == ["BENIGN", "MOTION", "HV", "EMITTING"]


def test_safety_class_total_ordering():
    # BENIGN < MOTION < HV < EMITTING — every strict pair, both directions.
    ladder = [SafetyClass.BENIGN, SafetyClass.MOTION, SafetyClass.HV,
              SafetyClass.EMITTING]
    for i, lower in enumerate(ladder):
        for higher in ladder[i + 1:]:
            assert lower < higher
            assert lower <= higher
            assert higher > lower
            assert higher >= lower
            assert not lower >= higher
            assert not higher <= lower


def test_safety_class_ge_idiom():
    # The spec's comparison idiom (§7.1): safety_class >= SafetyClass.MOTION.
    assert SafetyClass.HV >= SafetyClass.MOTION
    assert SafetyClass.MOTION >= SafetyClass.MOTION
    assert not (SafetyClass.BENIGN >= SafetyClass.MOTION)


def test_safety_class_reflexive_and_equality():
    for member in SafetyClass:
        assert member <= member and member >= member
        assert not (member < member) and not (member > member)


def test_safety_class_comparison_with_foreign_type_raises():
    # Ranks are unspecified (§7.1): comparing against numbers must not work.
    with pytest.raises(TypeError):
        SafetyClass.HV < 3          # noqa: B015 — the comparison IS the test
    with pytest.raises(TypeError):
        SafetyClass.HV >= "MOTION"  # noqa: B015


# --------------------------------------------------------------------------- #
# §5/§7.2/§9 the other enums                                                   #
# --------------------------------------------------------------------------- #


def test_operation_members_exact():
    assert set(Operation.__members__) == {"READ", "SET", "ARM", "START", "STOP"}


def test_readback_policy_has_no_mandatory_member():
    # §9/§15: MANDATORY does not exist and its absence is contractual.
    assert set(ReadbackPolicy.__members__) == {"NONE", "BEST_EFFORT"}


# --------------------------------------------------------------------------- #
# Construction happy paths per type (§5)                                       #
# --------------------------------------------------------------------------- #


def test_base_descriptor_constructs():
    d = make_base(metadata={"note": "hello"})
    assert d.capability_id == "camera.frame"
    assert d.safety_class is SafetyClass.BENIGN


def test_sweepable_defaults():
    d = make_sweep()
    assert d.settle_s == 0.0
    assert d.readback is ReadbackPolicy.NONE
    assert d.limits == (0.0, 100.0)
    assert d.unit == "mm"


def test_readable_channel_constructs():
    d = ReadableChannel(
        capability_id="intensity.amplitude",
        device_id="intensity_monitor",
        transport_id="scope",  # §6.1 pass-through: lock owner is the scope
        label="Laser intensity amplitude",
        safety_class=SafetyClass.BENIGN,
        metadata={},
        unit="V",
    )
    assert d.device_id == "intensity_monitor"
    assert d.transport_id == "scope"


def test_waveform_source_constructs():
    d = WaveformSource(
        capability_id="scope.waveform",
        device_id="scope",
        transport_id="scope",
        label="Scope waveform",
        safety_class=SafetyClass.BENIGN,
        metadata={},
        channels=("ref_ch1", "dut_ch2"),
    )
    assert d.channels == ("ref_ch1", "dut_ch2")


def test_frame_and_trigger_sources_construct():
    f = FrameSource(
        capability_id="camera.frame", device_id="camera", transport_id="camera",
        label="Camera frame", safety_class=SafetyClass.BENIGN, metadata={},
    )
    t = TriggerSource(
        capability_id="wavegen.output", device_id="waveform_generator",
        transport_id="waveform_generator", label="Wavegen output",
        safety_class=SafetyClass.EMITTING, metadata={},
    )
    assert isinstance(f, CapabilityDescriptor)
    assert isinstance(t, CapabilityDescriptor)


def test_hv_source_constructs_and_is_sweepable():
    d = make_hv()
    assert isinstance(d, SweepableParameter)
    assert isinstance(d, CapabilityDescriptor)
    assert d.polarity == "n"
    assert d.channel == 0


def test_hv_source_defaults_polarity_and_channel_none():
    d = make_hv(polarity=None, channel=None)
    assert d.polarity is None
    assert d.channel is None


def test_hv_source_nonprimary_channel_id_conforms():
    # §14.2: bias.ch{n}.voltage is grammar-conforming (ch1 matches a segment).
    d = make_hv(capability_id="bias.ch1.voltage", channel=1)
    assert d.capability_id == "bias.ch1.voltage"


def test_descriptors_are_frozen():
    d = make_sweep()
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.label = "other"
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.metadata = {}


# --------------------------------------------------------------------------- #
# §5.1 capability_id grammar (fail closed at construction)                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("good", [
    "stage.x", "bias.voltage", "bias.ch1.voltage", "wavegen.duty_cycle",
    "slow_control.temperature", "a.b_2.c3", "scope.waveform",
])
def test_capability_id_grammar_accepts(good):
    assert CAPABILITY_ID_PATTERN.match(good)
    make_base(capability_id=good)  # must not raise


@pytest.mark.parametrize("bad", [
    "stage",            # one segment — at least two required
    "Stage.x",          # uppercase domain
    "stage.X",          # uppercase parameter
    "stage..x",         # empty segment
    ".stage.x",         # leading dot
    "stage.x.",         # trailing dot
    "stage.1x",         # segment starts with a digit
    "1stage.x",
    "stage.x-y",        # hyphen not in charset
    "stage x",
    "",
    "stage.x\n",
])
def test_capability_id_grammar_rejects(bad):
    with pytest.raises(ValueError):
        make_base(capability_id=bad)


def test_capability_id_must_be_str():
    with pytest.raises(TypeError):
        make_base(capability_id=None)


def test_device_and_transport_ids_must_be_nonempty_str():
    with pytest.raises(ValueError):
        make_base(device_id="")
    with pytest.raises(ValueError):
        make_base(transport_id="")
    with pytest.raises(TypeError):
        make_base(device_id=None)
    with pytest.raises(TypeError):
        make_base(transport_id=7)


def test_slow_control_device_id_form_is_legal():
    # §5.3: device_id vocabulary includes slow_control/<name> — with the
    # shipped (grandfathered) uppercase name and the slash intact.
    d = ReadableChannel(
        capability_id="slow_control.temperature",
        device_id="slow_control/temperature_C",
        transport_id="slow_control/temperature_C",
        label="Box temperature",
        safety_class=SafetyClass.BENIGN,
        metadata={},
        unit="°C",
    )
    assert d.device_id == "slow_control/temperature_C"


def test_safety_class_field_type_enforced():
    with pytest.raises(TypeError):
        make_base(safety_class="HV")


# --------------------------------------------------------------------------- #
# §4 metadata: enforced JSON-safety, fail closed at construction               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_metadata", [
    {"cb": lambda: None},                    # callable
    {"dev": object()},                       # device-reference class smuggle
    {"arr": [1, 2, 3]},                      # list — must be a tuple
    {"s": {1, 2}},                           # set
    {"b": b"raw"},                           # bytes
    {"nested": {"deep": {"worse": object()}}},   # violation deep inside
    {"in_tuple": (1, object())},             # violation inside a tuple
    {1: "non-str key"},
    {"nested_key": {2: "non-str nested key"}},
])
def test_metadata_json_safety_fails_closed(bad_metadata):
    with pytest.raises(TypeError):
        make_base(metadata=bad_metadata)


def test_metadata_must_be_a_mapping():
    with pytest.raises(TypeError):
        make_base(metadata=[("a", 1)])
    with pytest.raises(TypeError):
        make_base(metadata="not a mapping")


@pytest.mark.parametrize("ambiguous", [
    {"pairs": (("a", 1),)},   # shaped exactly like an encoded mapping
    {"empty": ()},            # shaped like an encoded empty mapping
    {"deep": ("x", (("k", 1), ("l", 2)))},   # ambiguity nested in a tuple
])
def test_metadata_mapping_shaped_tuples_rejected_as_ambiguous(ambiguous):
    # Canonical-form ambiguity (§4): after canonicalisation these would be
    # indistinguishable from encoded mappings — fail closed at the door.
    with pytest.raises(TypeError):
        make_base(metadata=ambiguous)


def test_metadata_accepts_full_json_grammar():
    d = make_base(metadata={
        "str": "s", "int": 3, "float": 2.5, "bool": True, "none": None,
        "tuple": (1, "two", 3.0), "map": {"inner": (False, None)},
    })
    snap = d.snapshot()
    assert snap["metadata"] == {
        "str": "s", "int": 3, "float": 2.5, "bool": True, "none": None,
        "tuple": [1, "two", 3.0], "map": {"inner": [False, None]},
    }


def test_metadata_canonicalised_key_order_irrelevant():
    a = make_base(metadata={"b": 2, "a": 1})
    b = make_base(metadata={"a": 1, "b": 2})
    assert a == b
    assert hash(a) == hash(b)


def test_metadata_nested_key_order_irrelevant():
    a = make_base(metadata={"m": {"y": 2, "x": 1}})
    b = make_base(metadata={"m": {"x": 1, "y": 2}})
    assert a == b
    assert hash(a) == hash(b)


def test_metadata_difference_breaks_equality():
    assert make_base(metadata={"a": 1}) != make_base(metadata={"a": 2})


def test_descriptor_is_hashable_with_nested_metadata():
    d = make_sweep(metadata={"cal": {"slope": 1.5, "pts": (1, 2, 3)}})
    assert isinstance(hash(d), int)
    assert isinstance(d.metadata, tuple)   # the §4 canonical stored form


def test_dataclasses_replace_round_trips_canonical_metadata():
    # replace() re-feeds the stored canonical form through __init__; the
    # model must accept its own canonical output (strict inverse, §4).
    d = make_sweep(metadata={"m": {"x": 1}, "t": (1, 2)})
    r = dataclasses.replace(d, label="renamed")
    assert r.metadata == d.metadata
    assert r.label == "renamed"


def test_equality_and_hash_for_identical_descriptors():
    assert make_hv() == make_hv()
    assert hash(make_hv()) == hash(make_hv())
    assert make_hv() != make_hv(label="other")


# --------------------------------------------------------------------------- #
# §4 snapshot(): JSON provenance with no custom encoder                        #
# --------------------------------------------------------------------------- #


def test_snapshot_json_dumps_no_custom_encoder():
    for d in (make_base(), make_sweep(), make_hv(metadata={"note": {"k": (1,)}})):
        json.dumps(d.snapshot())  # must not raise, default encoder only


def test_snapshot_carries_type_and_model_version():
    snap = make_hv().snapshot()
    assert snap["type"] == "HVSource"
    assert snap["model_version"] == MODEL_VERSION
    assert MODEL_VERSION.startswith("1")


def test_snapshot_enums_serialise_as_names_never_ordinals():
    snap = make_hv().snapshot()
    assert snap["safety_class"] == "HV"
    assert snap["readback"] == "BEST_EFFORT"
    assert make_sweep().snapshot()["readback"] == "NONE"


def test_snapshot_contains_every_field():
    d = make_hv()
    snap = d.snapshot()
    for field in dataclasses.fields(d):
        assert field.name in snap
    assert snap["channel"] == 0
    assert snap["polarity"] == "n"
    assert snap["unit"] == "V"
    assert snap["limits"] == (-1000.0, 0.0)


def test_snapshot_json_round_trip():
    d = make_hv(metadata={"why": "iv-curve", "shape": {"step": 5.0}})
    loaded = json.loads(json.dumps(d.snapshot()))
    assert loaded["capability_id"] == "bias.voltage"
    assert loaded["device_id"] == "bias_supply"
    assert loaded["transport_id"] == "bias_supply"
    assert loaded["limits"] == [-1000.0, 0.0]     # tuple → JSON array
    assert loaded["metadata"] == {"why": "iv-curve", "shape": {"step": 5.0}}
    assert loaded["type"] == "HVSource"


def test_snapshot_metadata_is_plain_dict():
    snap = make_base(metadata={"m": {"x": 1}}).snapshot()
    assert isinstance(snap["metadata"], dict)
    assert isinstance(snap["metadata"]["m"], dict)


# --------------------------------------------------------------------------- #
# §5 limits / settle_s / resolution sanity (fail closed)                       #
# --------------------------------------------------------------------------- #


def test_limits_ordering_enforced():
    with pytest.raises(ValueError):
        make_sweep(limits=(100.0, 0.0))


def test_limits_nan_rejected():
    with pytest.raises(ValueError):
        make_sweep(limits=(float("nan"), 1.0))
    with pytest.raises(ValueError):
        make_sweep(limits=(0.0, float("nan")))


@pytest.mark.parametrize("bad", [
    (0.0,), (0.0, 1.0, 2.0), [0.0, 1.0], ("0", "1"), (0.0, True), 5.0,
])
def test_limits_malformed_rejected(bad):
    with pytest.raises(TypeError):
        make_sweep(limits=bad)


def test_limits_degenerate_point_range_allowed():
    assert make_sweep(limits=(5.0, 5.0)).limits == (5.0, 5.0)


def test_limits_none_constructible_even_for_dangerous_classes():
    # §7.4: a MOTION/HV descriptor with limits=None is CONSTRUCTIBLE — the
    # "render DISABLED, never an unbounded setter" rule is UI-side (D4b).
    # Real case: BiasSupplyBase.voltage_range_V is optional (float | None).
    assert make_sweep(limits=None).limits is None
    assert make_hv(limits=None).limits is None


def test_settle_s_negative_rejected():
    with pytest.raises(ValueError):
        make_sweep(settle_s=-0.1)


def test_settle_s_type_enforced():
    with pytest.raises(TypeError):
        make_sweep(settle_s="0.1")
    with pytest.raises(TypeError):
        make_sweep(settle_s=True)


@pytest.mark.parametrize("bad,exc", [
    (0.0, ValueError), (-1.0, ValueError), ("fine", TypeError), (True, TypeError),
])
def test_resolution_must_be_positive_or_none(bad, exc):
    with pytest.raises(exc):
        make_sweep(resolution=bad)


def test_readback_type_enforced():
    with pytest.raises(TypeError):
        make_sweep(readback="NONE")


def test_unit_type_enforced():
    with pytest.raises(TypeError):
        make_sweep(unit=None)


def test_waveform_source_channels_type_enforced():
    for bad in (["ch1"], ("ch1", 2), "ch1"):
        with pytest.raises(TypeError):
            WaveformSource(
                capability_id="scope.waveform", device_id="scope",
                transport_id="scope", label="Scope waveform",
                safety_class=SafetyClass.BENIGN, metadata={}, channels=bad,
            )


# --------------------------------------------------------------------------- #
# §5.4 HVSource specifics                                                      #
# --------------------------------------------------------------------------- #


def test_hv_polarity_vocabulary_enforced():
    assert make_hv(polarity="p").polarity == "p"
    with pytest.raises(ValueError):
        make_hv(polarity="x")
    with pytest.raises(ValueError):
        make_hv(polarity="N")   # normalize_polarity vocabulary is lowercase
    with pytest.raises(TypeError):
        make_hv(polarity=1)


def test_hv_channel_sanity_enforced():
    assert make_hv(channel=3).channel == 3
    with pytest.raises(ValueError):
        make_hv(channel=-1)
    with pytest.raises(TypeError):
        make_hv(channel=True)
    with pytest.raises(TypeError):
        make_hv(channel=1.0)


def test_hv_source_exposes_no_kill_surface():
    # LAW §5.4: neither HVSource nor its binding exposes a kill/NOT-AUS/
    # emergency-off surface — kill stays on the single existing safety path.
    d = make_hv()
    forbidden = ("kill", "emergency", "not_aus", "all_off")
    offenders = [
        name for name in dir(d)
        if any(word in name.lower() for word in forbidden)
    ]
    assert offenders == []


# --------------------------------------------------------------------------- #
# §5.4 Motion3D: non-registered helper, NOT a descriptor                       #
# --------------------------------------------------------------------------- #


def _stage_axes():
    return tuple(
        make_sweep(capability_id=f"stage.{axis}", label=f"Stage {axis.upper()}")
        for axis in ("x", "y", "z")
    )


def test_motion3d_constructs_and_holds_axes():
    m = Motion3D(axes=_stage_axes())
    assert len(m.axes) == 3
    assert all(isinstance(axis, SweepableParameter) for axis in m.axes)


def test_motion3d_is_not_a_capability_descriptor():
    m = Motion3D(axes=_stage_axes())
    assert not isinstance(m, CapabilityDescriptor)


def test_motion3d_has_no_capability_id_and_no_snapshot():
    # No capability_id ⇒ cannot be registered (registration is keyed by it);
    # no snapshot() ⇒ never serialised into provenance (§5.4).
    m = Motion3D(axes=_stage_axes())
    assert not hasattr(m, "capability_id")
    assert not hasattr(m, "snapshot")
    assert not hasattr(m, "safety_class")   # its axes carry the class


def test_motion3d_axes_type_enforced():
    with pytest.raises(TypeError):
        Motion3D(axes=list(_stage_axes()))
    with pytest.raises(TypeError):
        Motion3D(axes=("not a descriptor",))
    with pytest.raises(TypeError):
        # ReadableChannel is a descriptor but NOT a SweepableParameter axis.
        Motion3D(axes=(
            ReadableChannel(
                capability_id="intensity.charge",
                device_id="intensity_monitor", transport_id="scope",
                label="Charge", safety_class=SafetyClass.BENIGN,
                metadata={}, unit="pC",
            ),
        ))


def test_motion3d_frozen_and_hashable():
    m = Motion3D(axes=_stage_axes())
    assert isinstance(hash(m), int)
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.axes = ()


# --------------------------------------------------------------------------- #
# §5.1.1 slow-control alias table                                              #
# --------------------------------------------------------------------------- #


def test_alias_table_is_exactly_the_four_shipped_names():
    assert SLOW_CONTROL_CHANNEL_ALIASES == {
        "temperature_C": "slow_control.temperature",
        "humidity_pct": "slow_control.humidity",
        "bias_voltage_V": "slow_control.bias_voltage",
        "leakage_current_nA": "slow_control.leakage_current",
    }


def test_alias_targets_are_grammar_conforming():
    for target in SLOW_CONTROL_CHANNEL_ALIASES.values():
        assert CAPABILITY_ID_PATTERN.match(target), target


@pytest.mark.parametrize("name,expected", sorted(SLOW_CONTROL_CHANNEL_ALIASES.items()))
def test_grandfathered_names_map_through_helper(name, expected):
    assert slow_control_capability_id(name) == expected


def test_conforming_new_name_maps_to_slow_control_id():
    assert slow_control_capability_id("box_temp") == "slow_control.box_temp"


@pytest.mark.parametrize("bad", [
    "Temp_C",       # uppercase, not grandfathered
    "1sensor",      # leading digit
    "dew-point",    # hyphen
    "temp C",       # space
    "",             # empty
    "box_temp\n",   # trailing newline (Python `$` tolerates it; fullmatch)
])
def test_nonconforming_names_fail_closed_never_munged(bad):
    with pytest.raises(ValueError):
        slow_control_capability_id(bad)


@pytest.mark.parametrize("colliding", [
    "temperature", "humidity", "bias_voltage", "leakage_current",
])
def test_names_colliding_with_alias_targets_rejected(colliding):
    # §5.1.1: adding a channel named `temperature` while `temperature_C`
    # owns slow_control.temperature forever must be refused.
    with pytest.raises(ValueError):
        slow_control_capability_id(colliding)


def test_alias_helper_rejects_non_str():
    with pytest.raises(TypeError):
        slow_control_capability_id(None)


# --------------------------------------------------------------------------- #
# §2.1 layering: the model imports the standard library ONLY                   #
# --------------------------------------------------------------------------- #


def test_model_module_is_stdlib_only():
    """LAW §2.1: capabilities/model.py imports only the stdlib — no Qt, no
    numpy, no devices/, no controller/, no gui/.

    D1b handover (this pin's D1a docstring promised it): the PACKAGE-wide
    duty now lives in tests/test_layer_contracts.py — `capabilities` is in
    its layer table, allowed to import `devices` only (adapters.py/registry.py
    legitimately wrap drivers) — so this pin narrowed to model.py itself.

    Mary's D1a flag, closed here: an AST scan that skips relative imports
    (``node.level > 0``) would let ``from .adapters import X`` reach devices/
    through the back door while the pin stayed green.  model.py has no
    legitimate relative import (everything above it in-package is above it in
    the layering), so ANY relative import is itself a violation.
    """
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    path = Path(__file__).resolve().parent.parent / "capabilities" / "model.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    relative: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                relative.append(node.module or ".")
            elif node.module:
                roots.add(node.module.split(".")[0])
    assert relative == [], (
        f"model.py uses relative import(s) {relative} — forbidden outright: "
        "a relative import could reach devices/ via adapters.py while an "
        "absolute-only AST pin stayed green (stdlib-only LAW §2.1)"
    )
    bad = sorted(roots - stdlib)
    assert bad == [], f"model.py imports non-stdlib module(s): {bad}"
