"""D1b tests: adapters + ``CapabilityRegistry`` + the binding skeleton.

Normative spec: ``docs/CAPABILITY_MODEL.md`` v1.0-rc — §6 (lifecycle), §6.1
(transport reservation / lock resolver), §6.2 (reservation vs. fail-safe),
§7.2 (route table + build-time LAWS), §11.1/§11.2 (adapters/registry), §14.2
(multi-channel HV naming).

Hardware safety (rules 3/6): every DeviceManager here is fully simulated; the
one non-sim GRBL instance talks to an in-memory serial STUB (the recorder
pattern from tests/test_motor_transport_lock.py) and is never connect()ed.
Safe to run with real instruments attached.
"""
from __future__ import annotations

import json
import threading
import time

import pytest
import yaml

from capabilities.adapters import (
    WAVEGEN_PLAN_KEYS,
    CapabilityBinding,
    VerifyResult,
    bias_descriptors,
)
from capabilities.model import (
    CapabilityDescriptor,
    FrameSource,
    HVSource,
    Operation,
    ReadableChannel,
    SafetyClass,
    SweepableParameter,
    TriggerSource,
    WaveformSource,
)
from capabilities.registry import (
    CLASS_FLOOR_ROUTES,
    KNOWN_ROUTES,
    RESERVED_ROUTES,
    ROUTE_DANGER_GATE,
    ROUTE_EMISSION_INTERLOCK,
    ROUTE_HV_LOCK,
    ROUTE_MOTION_ENVELOPE,
    CapabilityRegistry,
    check_v1_laws,
)
from controller.device_manager import DeviceManager
from controller.scan_plan_validator import _KNOWN_WAVEGEN_KEYS
from devices.base import DeviceError
from devices.bias_channel import BiasChannel
from devices.bias_supply_simulated import SimulatedBiasSupply


# --------------------------------------------------------------------------- #
# Fixtures — fully simulated DeviceManager                                     #
# --------------------------------------------------------------------------- #

_SOFT_LIMITS = {
    "x_min_mm": 0.0, "x_max_mm": 235.0,
    "y_min_mm": 0.0, "y_max_mm": 235.0,
    "z_min_mm": 0.0, "z_max_mm": 250.0,
}


def _write_cfg(tmp_path, *, motor=None, slow_channels=None) -> str:
    cfg = {
        "oscilloscope": {"backend": "visa", "simulation": True, "n_channels": 2},
        "motor_stage": motor or {
            "backend": "grbl", "simulation": True, "marlin": True,
            "software_limits": dict(_SOFT_LIMITS),
        },
        "intensity_monitor": {"backend": "scope_channel", "channel": 1},
        "camera": {"simulation": True},
        "waveform_generator": {"simulation": True},
        "bias_supply": {"backend": "simulated", "channel": 0,
                        "sim_channel_count": 3},
        "slow_control": {
            "poll_interval_s": 1.0,
            "channels": slow_channels if slow_channels is not None else [
                {"name": "temperature_C", "unit": "°C",
                 "backend": "simulated", "nominal": 22.0},
                {"name": "box_temp", "unit": "K",
                 "backend": "simulated", "nominal": 295.0},
            ],
        },
        "output": {"data_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return str(path)


@pytest.fixture
def dm(tmp_path):
    """Unconnected, fully simulated DeviceManager (GRBL sim motor)."""
    manager = DeviceManager(config_path=_write_cfg(tmp_path))
    assert manager.config_errors() == []
    return manager


@pytest.fixture
def connected_dm(tmp_path):
    """Connected simulated DeviceManager — bias channels enumerated (3)."""
    manager = DeviceManager(config_path=_write_cfg(tmp_path))
    assert manager.config_errors() == []
    results = manager.connect_all()
    assert all(v == "ok" for v in results.values()), results
    yield manager
    manager.disconnect_all()


# ---- non-sim GRBL over an in-memory serial stub (recorder pattern) --------- #

class _StubSerial:
    """Minimal in-memory GRBL endpoint (pattern:
    tests/test_motor_transport_lock.py::LockWatchingSerial) — answers the
    real-time '?' with an Idle status frame.  No hardware anywhere."""

    def __init__(self):
        self.is_open = True
        self._buf = b""
        self._replies = {
            b"?": b"<Idle|MPos:1.000,2.000,3.000|FS:0,0>\n",
            b"$X": b"ok\n",
        }

    def write(self, data: bytes) -> None:
        reply = self._replies.get(data.strip())
        if reply:
            self._buf += reply

    def flush(self) -> None: ...

    def reset_input_buffer(self) -> None:
        self._buf = b""

    def readline(self) -> bytes:
        if not self._buf:
            time.sleep(0.005)
            return b""
        idx = self._buf.find(b"\n")
        if idx >= 0:
            line, self._buf = self._buf[:idx + 1], self._buf[idx + 1:]
            return line
        line, self._buf = self._buf, b""
        return line

    def close(self) -> None:
        self.is_open = False

    @property
    def in_waiting(self) -> int:
        return len(self._buf)


@pytest.fixture
def stub_serial_dm(tmp_path):
    """DeviceManager whose GRBL motor runs the REAL locked I/O path against an
    in-memory stub (simulation=False, never connect()ed — no port is opened;
    the stub is injected exactly like tests/test_motor_transport_lock.py)."""
    manager = DeviceManager(config_path=_write_cfg(tmp_path, motor={
        "backend": "grbl", "simulation": False, "serial_port": "MOCK",
        "marlin": False, "home_to_center": False,
        "software_limits": dict(_SOFT_LIMITS),
    }))
    manager.motor._ser = _StubSerial()
    manager.motor._connected = True
    return manager


def _by_id(registry) -> dict[str, CapabilityDescriptor]:
    return {d.capability_id: d for d in registry.descriptors()}


# --------------------------------------------------------------------------- #
# Registry build + seed vocabulary (§5.1, §11.2)                               #
# --------------------------------------------------------------------------- #


def test_registry_builds_before_connect_no_io(dm):
    """LAW §2.4: build + derivation need no connection (and, with every
    backend simulated, could not reach hardware anyway)."""
    registry = dm.capability_registry()
    assert isinstance(registry, CapabilityRegistry)
    assert registry.descriptors()
    # No instrument state was touched: everything still disconnected.
    assert not dm.motor.connected
    assert not dm.bias_supply.connected


def test_seed_vocabulary_exact_after_connect(connected_dm):
    """§5.1 seed vocabulary, pinned EXACTLY for this config (id permanence
    spot-check): primary HV role + the two non-primary physical channels."""
    ids = set(_by_id(connected_dm.capability_registry()))
    assert ids == {
        "stage.x", "stage.y", "stage.z",
        "bias.voltage", "bias.ch1.voltage", "bias.ch2.voltage",
        "wavegen.frequency", "wavegen.pulse_width", "wavegen.duty_cycle",
        "wavegen.amplitude", "wavegen.offset", "wavegen.output",
        "scope.waveform", "camera.frame",
        "intensity.amplitude", "intensity.charge",
        "slow_control.temperature", "slow_control.box_temp",
    }


def test_descriptor_types_match_spec(connected_dm):
    table = _by_id(connected_dm.capability_registry())
    assert type(table["stage.x"]) is SweepableParameter
    assert type(table["bias.voltage"]) is HVSource
    assert type(table["bias.ch1.voltage"]) is HVSource
    assert type(table["wavegen.frequency"]) is SweepableParameter
    assert type(table["wavegen.output"]) is TriggerSource
    assert type(table["scope.waveform"]) is WaveformSource
    assert type(table["camera.frame"]) is FrameSource
    assert type(table["intensity.amplitude"]) is ReadableChannel
    assert type(table["slow_control.temperature"]) is ReadableChannel


def test_descriptors_sorted_and_rederived_per_call(dm):
    registry = dm.capability_registry()
    first = registry.descriptors()
    second = registry.descriptors()
    assert [d.capability_id for d in first] == sorted(
        d.capability_id for d in first)
    assert first == second                      # deterministic content
    # §5.5: re-derived per call — fresh objects, never a cached tuple.
    assert first is not second


def test_get_unknown_id_fails_closed(dm):
    registry = dm.capability_registry()
    with pytest.raises(KeyError):
        registry.get("stage.warp_drive")
    with pytest.raises(KeyError):
        registry.binding("no.such_capability")


def test_primary_channel_published_once_with_physical_index(connected_dm):
    """§14.2: bias.voltage is the primary ROLE (physical index rides in
    HVSource.channel); the primary's physical channel is NEVER also published
    as bias.ch{n}.voltage — one channel, one id."""
    table = _by_id(connected_dm.capability_registry())
    assert "bias.ch0.voltage" not in table      # primary index is 0 here
    primary = table["bias.voltage"]
    assert primary.channel == 0
    assert table["bias.ch1.voltage"].channel == 1
    assert table["bias.ch2.voltage"].channel == 2
    # All bias.* share the ONE transport (§6.1/§14.2).
    assert {table[i].transport_id for i in
            ("bias.voltage", "bias.ch1.voltage", "bias.ch2.voltage")} \
        == {"bias_supply"}


def test_bias_channels_appear_after_refresh(dm):
    """§5.5 freshness: before connect only the primary proxy exists; after
    connect_all → refresh_bias_channels the ch{n} descriptors appear on the
    next derivation — no rebuild of the registry object required."""
    registry = dm.capability_registry()
    assert {i for i in _by_id(registry) if i.startswith("bias.")} \
        == {"bias.voltage"}
    results = dm.connect_all()
    try:
        assert all(v == "ok" for v in results.values()), results
        assert {i for i in _by_id(registry) if i.startswith("bias.")} \
            == {"bias.voltage", "bias.ch1.voltage", "bias.ch2.voltage"}
    finally:
        dm.disconnect_all()


def test_hv_limits_derived_from_voltage_range():
    """Adapter-level: limits mirror BiasSupplyBase.check_voltage_in_range's
    |V| ceiling; range None → limits None (§5, the real limits=None case)."""
    ranged = SimulatedBiasSupply(channel=0, channel_count=1,
                                 voltage_range_V=1000.0)
    (d,) = bias_descriptors(BiasChannel(ranged, 0), ())
    assert d.limits == (-1000.0, 1000.0)
    assert d.polarity == "n"      # sim default, derivable without I/O (§2.4)
    unranged = SimulatedBiasSupply(channel=0, channel_count=1)
    (d2,) = bias_descriptors(BiasChannel(unranged, 0), ())
    assert d2.limits is None


def test_stage_limits_come_from_user_frame_and_rederive_after_zero(connected_dm):
    """§5.4/§5.5: axis limits derive from limits_user_frame(), and a
    home→zero shift is visible on the very next descriptors() call."""
    registry = connected_dm.capability_registry()
    motor = connected_dm.motor
    before = _by_id(registry)["stage.x"]
    lim = motor.limits_user_frame()
    assert before.limits == (lim.x_min, lim.x_max)
    assert before.unit == "mm"

    motor.home()               # simulated homing (explicit test action)
    motor.zero_position()      # shifts the user-frame origin
    after = _by_id(registry)["stage.x"]
    lim2 = motor.limits_user_frame()
    assert after.limits == (lim2.x_min, lim2.x_max)
    assert after.limits != before.limits, \
        "user-frame shift must show up in re-derived descriptors (§5.5)"


def test_wavegen_vocabulary_mirrors_plan_grammar(dm):
    """§5.1: the adapter's static table links capability ids to the plan
    grammar's suffixed keys — pinned equal to the validator's
    _KNOWN_WAVEGEN_KEYS so the two vocabularies can never drift."""
    assert set(WAVEGEN_PLAN_KEYS.values()) == set(_KNOWN_WAVEGEN_KEYS)
    table = _by_id(dm.capability_registry())
    sweepable_wavegen = {
        i for i, d in table.items()
        if i.startswith("wavegen.") and isinstance(d, SweepableParameter)
    }
    assert sweepable_wavegen == set(WAVEGEN_PLAN_KEYS)
    # Units live in the descriptor, never the id (§5.1).
    assert table["wavegen.duty_cycle"].unit == "%"
    assert table["wavegen.frequency"].unit == "Hz"
    assert table["wavegen.pulse_width"].unit == "s"


def test_slow_control_alias_consumption(dm):
    """§5.1.1: grandfathered name maps through the permanent alias table;
    conforming new names map to slow_control.<name>; device_id keeps the RAW
    config name (connect_all result-key vocabulary, §5.3)."""
    table = _by_id(dm.capability_registry())
    temp = table["slow_control.temperature"]
    assert temp.device_id == "slow_control/temperature_C"
    assert temp.transport_id == "slow_control/temperature_C"
    assert temp.unit == "°C"
    box = table["slow_control.box_temp"]
    assert box.device_id == "slow_control/box_temp"
    assert box.unit == "K"


def test_unmappable_slow_control_name_fails_registry_build(tmp_path):
    """§5.1.1 item 3 / §11.4 item 5: the registry FAILS CLOSED on a channel
    name it cannot map — never silently munged into a permanent id.  (The
    validator half flags the same config as an ERROR; the registry must not
    depend on that.)"""
    manager = DeviceManager(config_path=_write_cfg(tmp_path, slow_channels=[
        {"name": "Bad-Name", "unit": "K", "backend": "simulated"},
    ]))
    assert manager.config_errors() != []        # Abel's validator half agrees
    with pytest.raises(ValueError):
        manager.capability_registry()


def test_driver_own_describe_capabilities_is_preferred(dm):
    """§11.1: a driver MAY publish its own descriptors (duck-typed); the
    adapter table is the fallback."""
    own = FrameSource(
        capability_id="camera.frame", device_id="camera",
        transport_id="camera", label="OWN", safety_class=SafetyClass.BENIGN,
        metadata={},
    )

    class _SelfDescribing:
        transport_lock = threading.RLock()

        @staticmethod
        def describe_capabilities():
            return (own,)

    dm.camera = _SelfDescribing()
    table = _by_id(dm.capability_registry())
    assert table["camera.frame"].label == "OWN"


# --------------------------------------------------------------------------- #
# §6.1 transport-lock resolver — is-identity + fail-closed + behaviour         #
# --------------------------------------------------------------------------- #


def test_transport_lock_identity_for_every_registered_descriptor(connected_dm):
    """D1b identity requirement (§6.1): for EVERY registered descriptor the
    binding's lock — resolved through transport_lock_for, the ONE resolver —
    IS the lock object the owning driver's I/O acquires."""
    registry = connected_dm.capability_registry()
    for d in registry.descriptors():
        resolved = registry.transport_lock_for(d.transport_id)
        binding = registry.binding(d.capability_id)
        assert binding.transport_lock is resolved, d.capability_id


def test_grbl_transport_lock_is_the_private_command_lock(connected_dm):
    """GRBL serialises on its private _lock, never io_lock (Mary BLOCKER-1);
    the resolver must return THAT object."""
    registry = connected_dm.capability_registry()
    motor = connected_dm.motor
    resolved = registry.transport_lock_for("motor")
    assert resolved is motor._lock
    assert resolved is motor.transport_lock
    assert resolved is not motor.io_lock


def test_bias_lock_resolves_on_the_shared_driver_never_the_proxy(connected_dm):
    """§6.1 (Codex BLOCKER-A): BiasChannel proxies own no lock — the resolver
    goes to the ONE shared driver; every HV channel shares that object."""
    registry = connected_dm.capability_registry()
    driver = connected_dm.bias_supply.driver
    resolved = registry.transport_lock_for("bias_supply")
    assert resolved is driver.transport_lock
    assert resolved is driver.io_lock            # BaseDevice default accessor
    for cap in ("bias.voltage", "bias.ch1.voltage", "bias.ch2.voltage"):
        assert registry.binding(cap).transport_lock is resolved, cap
    # The proxy really owns nothing a resolver could have (mis)used.
    assert not hasattr(connected_dm.bias_supply, "io_lock")
    assert not hasattr(connected_dm.bias_supply, "transport_lock")


def test_scope_channel_monitor_passthrough_lock_is_the_scopes(connected_dm):
    """§6.1 worked example (normative): device_id='intensity_monitor' (honest
    provenance), transport_id='scope' (honest lock owner); the monitor's own
    idle io_lock is never the reservation unit."""
    registry = connected_dm.capability_registry()
    table = _by_id(registry)
    for cap in ("intensity.amplitude", "intensity.charge"):
        d = table[cap]
        assert d.device_id == "intensity_monitor"
        assert d.transport_id == "scope"
        lock = registry.binding(cap).transport_lock
        assert lock is connected_dm.scope.transport_lock
        assert lock is connected_dm.scope.io_lock
        assert lock is not connected_dm.intensity_monitor.io_lock


def test_unknown_transport_id_fails_closed(dm):
    registry = dm.capability_registry()
    with pytest.raises(KeyError):
        registry.transport_lock_for("teleporter")


def test_descriptor_with_unmappable_transport_fails_at_build(dm, monkeypatch):
    """§6.1: KeyError at registry BUILD, before any reserve can exist."""
    rogue = FrameSource(
        capability_id="camera.frame", device_id="camera",
        transport_id="teleporter", label="rogue",
        safety_class=SafetyClass.BENIGN, metadata={},
    )
    monkeypatch.setattr("capabilities.registry.describe_capabilities",
                        lambda _dm: (rogue,))
    with pytest.raises(KeyError):
        dm.capability_registry()


def test_reservation_blocks_concurrent_driver_io(stub_serial_dm):
    """Behavioural §6.1 gate: while a reservation is held, a concurrent
    driver I/O call (GRBL get_position → _grbl_status, which takes _lock)
    BLOCKS, and proceeds once released."""
    registry = stub_serial_dm.capability_registry()
    binding = registry.binding("stage.x")
    started = threading.Event()
    finished = threading.Event()

    def _poller():
        started.set()
        stub_serial_dm.motor.get_position()      # real locked I/O path (stub)
        finished.set()

    token = binding.reserve(timeout_s=2.0)
    try:
        thread = threading.Thread(target=_poller, daemon=True)
        thread.start()
        assert started.wait(2.0)
        assert not finished.wait(0.25), \
            "driver I/O proceeded WHILE the transport was reserved"
    finally:
        token.release()
    assert finished.wait(5.0), "driver I/O never completed after release"


def test_reservation_is_reentrant_for_same_thread_driver_calls(stub_serial_dm):
    """§6.1: the reservation wraps driver calls that re-acquire the same lock
    (RLock) — a holder may call the driver without deadlocking."""
    registry = stub_serial_dm.capability_registry()
    binding = registry.binding("stage.x")
    done = threading.Event()

    def _reserved_call():
        with binding.reserve(timeout_s=2.0):
            stub_serial_dm.motor.get_position()
        done.set()

    thread = threading.Thread(target=_reserved_call, daemon=True)
    thread.start()
    assert done.wait(5.0), "driver deadlocked against its own reservation"


def test_reserve_times_out_against_a_foreign_holder(dm):
    registry = dm.capability_registry()
    binding = registry.binding("wavegen.frequency")
    held = threading.Event()
    release = threading.Event()

    def _holder():
        token = binding.reserve(timeout_s=1.0)
        held.set()
        release.wait(5.0)
        token.release()

    thread = threading.Thread(target=_holder, daemon=True)
    thread.start()
    assert held.wait(2.0)
    try:
        with pytest.raises(DeviceError):
            binding.reserve(timeout_s=0.1)
    finally:
        release.set()
        thread.join(timeout=5.0)


def test_reserve_requires_a_positive_timeout(dm):
    """§6.1: reserve MUST take a timeout — an unbounded wait is refused."""
    binding = dm.capability_registry().binding("stage.x")
    for bad in (0, -1.0, None, True):
        with pytest.raises((ValueError, TypeError)):
            binding.reserve(timeout_s=bad)


def test_reservation_token_is_context_manager_and_idempotent(dm):
    binding = dm.capability_registry().binding("stage.x")
    lock = binding.transport_lock
    with binding.reserve(timeout_s=1.0) as token:
        assert lock._is_owned()                  # held by this thread
        assert token.transport_id == "motor"
    assert not lock._is_owned()                  # released on exit
    token.release()                              # idempotent — no raise
    binding.release()                            # bookkeeping — no raise


# --------------------------------------------------------------------------- #
# §7.2 laws as code — max-hazard, no-spanning, route table                     #
# --------------------------------------------------------------------------- #


def test_no_v1_capability_spans_hazard_domains(connected_dm):
    """The §7.2 D1 registry-wide test: every published descriptor's driver
    path touches exactly one hazard domain, and safety_class equals that
    domain's class (check_v1_laws raises otherwise — also run at build)."""
    for d in connected_dm.capability_registry().descriptors():
        check_v1_laws(d)                        # must not raise


def test_class_assignments_match_spec_7_3(connected_dm):
    table = _by_id(connected_dm.capability_registry())
    expected = {
        "stage.x": SafetyClass.MOTION, "stage.y": SafetyClass.MOTION,
        "stage.z": SafetyClass.MOTION,
        "bias.voltage": SafetyClass.HV, "bias.ch1.voltage": SafetyClass.HV,
        "bias.ch2.voltage": SafetyClass.HV,
        "wavegen.frequency": SafetyClass.EMITTING,
        "wavegen.output": SafetyClass.EMITTING,
        "scope.waveform": SafetyClass.BENIGN,
        "camera.frame": SafetyClass.BENIGN,
        "intensity.amplitude": SafetyClass.BENIGN,
        "slow_control.temperature": SafetyClass.BENIGN,
    }
    for cap, cls in expected.items():
        assert table[cap].safety_class is cls, cap


def test_spanning_descriptor_is_rejected():
    """Negative teeth: a capability whose path crosses hazard domains (the
    hypothetical combined move+bias of Mary BLOCKER-3) fails check_v1_laws."""
    spanning = SweepableParameter(
        capability_id="stage.bias_combo", device_id="motor",
        transport_id="bias_supply", label="illegal",
        safety_class=SafetyClass.HV, metadata={},
        unit="V", limits=None, resolution=None,
    )
    with pytest.raises(ValueError, match="spans hazard domains"):
        check_v1_laws(spanning)


def test_mislabelled_safety_class_is_rejected():
    """Max-hazard LAW: a motor-path capability declared HV (or BENIGN) fails —
    safety_class is not a chosen label."""
    for wrong in (SafetyClass.HV, SafetyClass.BENIGN):
        mislabelled = SweepableParameter(
            capability_id="stage.x", device_id="motor", transport_id="motor",
            label="mislabelled", safety_class=wrong, metadata={},
            unit="mm", limits=None, resolution=None,
        )
        with pytest.raises(ValueError, match="MAXIMUM hazard"):
            check_v1_laws(mislabelled)


def test_route_floors_match_spec_7_2(connected_dm):
    registry = connected_dm.capability_registry()
    assert registry.effective_routes("bias.voltage", Operation.SET) \
        == {ROUTE_HV_LOCK, ROUTE_DANGER_GATE}
    assert registry.effective_routes("stage.x", Operation.SET) \
        == {ROUTE_MOTION_ENVELOPE}
    assert registry.effective_routes("stage.x", Operation.START) \
        == {ROUTE_DANGER_GATE}
    # EMITTING SET is ungated (the §7.1 non-monotonicity, normative in §7.4:
    # wavegen setters never touch output state; ARMING is the gated op).
    assert registry.effective_routes("wavegen.duty_cycle", Operation.SET) \
        == frozenset()
    assert registry.effective_routes("wavegen.output", Operation.ARM) \
        == {ROUTE_EMISSION_INTERLOCK}
    assert registry.effective_routes("scope.waveform", Operation.READ) \
        == frozenset()


def test_stop_is_never_gated_anywhere(connected_dm):
    """LAW §7.2, structurally and per descriptor."""
    for per_op in CLASS_FLOOR_ROUTES.values():
        assert per_op[Operation.STOP] == frozenset()
    registry = connected_dm.capability_registry()
    for d in registry.descriptors():
        assert registry.effective_routes(d.capability_id, Operation.STOP) \
            == frozenset(), d.capability_id


def test_read_is_never_gated_anywhere(connected_dm):
    registry = connected_dm.capability_registry()
    for d in registry.descriptors():
        assert registry.effective_routes(d.capability_id, Operation.READ) \
            == frozenset(), d.capability_id


def test_route_override_is_add_only_and_stop_override_is_refused(dm):
    """§14.1 ratified option (c): overrides ADD routes (union — loosening is
    structurally impossible); a STOP override or an unknown route name fails
    the build."""
    registry = CapabilityRegistry(dm, route_overrides={
        "wavegen.duty_cycle": {Operation.SET: {ROUTE_DANGER_GATE}},
    })
    assert registry.effective_routes("wavegen.duty_cycle", Operation.SET) \
        == {ROUTE_DANGER_GATE}                  # floor (empty) + override
    assert registry.effective_routes("wavegen.frequency", Operation.SET) \
        == frozenset()                           # others untouched
    with pytest.raises(ValueError, match="STOP"):
        CapabilityRegistry(dm, route_overrides={
            "stage.x": {Operation.STOP: {ROUTE_DANGER_GATE}},
        })
    with pytest.raises(ValueError, match="unknown route"):
        CapabilityRegistry(dm, route_overrides={
            "stage.x": {Operation.SET: {"voodoo_gate"}},
        })


def test_emission_interlock_is_reserved_vocabulary():
    """§7.2: the route NAME exists (permanent vocabulary), is marked RESERVED,
    and nothing in the capability layer wires it to an implementation —
    generated UI must render it DISABLED until P3 (§7.4)."""
    assert ROUTE_EMISSION_INTERLOCK in KNOWN_ROUTES
    assert RESERVED_ROUTES == {ROUTE_EMISSION_INTERLOCK}


# --------------------------------------------------------------------------- #
# §6 binding skeleton                                                          #
# --------------------------------------------------------------------------- #


def test_binding_construction_changes_no_instrument_state(connected_dm):
    """LAW §6/§15: no auto-connect/home/HV-enable/setpoint-restore."""
    registry = connected_dm.capability_registry()
    ch = connected_dm.bias_supply
    for cap in ("bias.voltage", "stage.x", "wavegen.output", "camera.frame"):
        registry.binding(cap)
    assert ch.is_output_on is False
    assert ch.setpoint_V == 0.0
    assert connected_dm.waveform_generator.output_is_on is False
    assert not connected_dm.motor.homed


def test_prepare_fails_closed_on_limits_and_type(connected_dm):
    registry = connected_dm.capability_registry()
    stage = registry.binding("stage.x")
    assert stage.prepare(10.0) == 10.0
    with pytest.raises(ValueError):
        stage.prepare(1e9)                       # outside the user-frame limits
    with pytest.raises(TypeError):
        stage.prepare("10")
    with pytest.raises(TypeError):
        stage.prepare(True)
    with pytest.raises(ValueError):
        stage.prepare(float("nan"))
    with pytest.raises(TypeError):
        registry.binding("camera.frame").prepare(1.0)    # not settable
    # HV prepare consults the driver's own runtime gate (limits=None here —
    # the sim supply has no configured range, so any float passes the gate).
    assert registry.binding("bias.voltage").prepare(-50.0) == -50.0


def test_apply_and_wait_settled_are_p1_territory(dm):
    """D1b skeleton: no binding is connected to a live setter this beat."""
    binding = dm.capability_registry().binding("stage.x")
    with pytest.raises(NotImplementedError):
        binding.apply(1.0)
    with pytest.raises(NotImplementedError):
        binding.wait_settled(1.0)


def test_verify_or_skip_is_honest(dm):
    """§9: v1 descriptors declare NONE → skipped; a read-only producer has
    nothing to verify → skipped; a value is never fabricated."""
    registry = dm.capability_registry()
    for cap in ("stage.x", "bias.voltage", "wavegen.duty_cycle", "camera.frame"):
        result = registry.binding(cap).verify_or_skip()
        assert result == VerifyResult(status="skipped", value=None), cap


def test_verify_result_status_vocabulary_enforced():
    with pytest.raises(ValueError):
        VerifyResult(status="commanded", value=1.0)   # the §9 dishonesty class


def test_abort_hv_delegates_to_the_existing_failsafe_pair(connected_dm):
    """§6 abort: HV → ramp to 0 + output off via the SAME driver methods the
    executor fail-safe uses; idempotent; callable from any stage."""
    registry = connected_dm.capability_registry()
    ch = connected_dm.bias_supply
    ch.set_voltage(-10.0)          # explicit test actions, gated driver paths
    ch.enable_output()
    assert ch.is_output_on is True

    binding = registry.binding("bias.voltage")
    binding.abort()
    assert ch.is_output_on is False
    assert ch.setpoint_V == 0.0
    binding.abort()                # idempotent — safe idle stays safe idle
    assert ch.is_output_on is False


def test_abort_trigger_and_stage_delegate_and_never_raise(connected_dm):
    registry = connected_dm.capability_registry()
    wfg = connected_dm.waveform_generator
    wfg.output_on()                # explicit test action
    registry.binding("wavegen.output").abort()
    assert wfg.output_is_on is False
    # Stage abort → stop(); safe to call at any time, including idle.
    registry.binding("stage.x").abort()
    registry.binding("stage.x").abort()
    # Read producers: abort is a documented no-op and must not raise.
    registry.binding("intensity.amplitude").abort()


def test_abort_never_raises_even_when_every_delegate_raises():
    """§6 LAW: abort MUST NOT raise (it is the cleanup path) — and the
    output-off try is SEPARATE from the ramp try (the _bias_failsafe
    discipline: the safety-critical off runs even if the ramp fails)."""
    calls: list[str] = []

    class _BrokenBias:
        channel = 0

        @staticmethod
        def ramp_to(*a, **k):
            calls.append("ramp_to")
            raise RuntimeError("ramp boom")

        @staticmethod
        def output_off():
            calls.append("output_off")
            raise RuntimeError("off boom")

    descriptor = HVSource(
        capability_id="bias.voltage", device_id="bias_supply",
        transport_id="bias_supply", label="hv", safety_class=SafetyClass.HV,
        metadata={}, unit="V", limits=None, resolution=None, channel=0,
    )
    binding = CapabilityBinding(descriptor, _BrokenBias(), threading.RLock())
    binding.abort()                              # must not raise
    assert calls == ["ramp_to", "output_off"], \
        "output_off must still be attempted after a raising ramp_to"


def test_abort_does_not_take_the_reservation(connected_dm):
    """LAW §6.2: abort is never subject to the transport reservation — it
    completes while ANOTHER thread holds the reserved lock (sim wavegen
    output_off does no locked I/O; the point is abort() itself never waits
    on the reservation)."""
    registry = connected_dm.capability_registry()
    binding = registry.binding("wavegen.output")
    connected_dm.waveform_generator.output_on()
    held = threading.Event()
    release = threading.Event()

    def _holder():
        with binding.reserve(timeout_s=1.0):
            held.set()
            release.wait(5.0)

    thread = threading.Thread(target=_holder, daemon=True)
    thread.start()
    assert held.wait(2.0)
    try:
        done = threading.Event()

        def _abort():
            binding.abort()
            done.set()

        aborter = threading.Thread(target=_abort, daemon=True)
        aborter.start()
        assert done.wait(1.0), "abort() waited on the transport reservation"
        assert connected_dm.waveform_generator.output_is_on is False
    finally:
        release.set()
        thread.join(timeout=5.0)


# --------------------------------------------------------------------------- #
# §4/§10 snapshot-not-binding provenance round trip                            #
# --------------------------------------------------------------------------- #


def test_every_registered_descriptor_snapshot_round_trips_json(connected_dm):
    """LAW §3: snapshot() — never the binding — is what provenance writes;
    every registered descriptor serialises with NO custom encoder."""
    for d in connected_dm.capability_registry().descriptors():
        loaded = json.loads(json.dumps(d.snapshot()))
        assert loaded["capability_id"] == d.capability_id
        assert loaded["device_id"] == d.device_id
        assert loaded["transport_id"] == d.transport_id
        assert loaded["type"] == type(d).__name__
        assert loaded["model_version"].startswith("1")
        assert loaded["safety_class"] == d.safety_class.name   # names, §4


def test_hv_snapshot_carries_channel_disambiguation(connected_dm):
    """§14.2/§10: the physical channel index survives into provenance."""
    table = _by_id(connected_dm.capability_registry())
    assert json.loads(json.dumps(table["bias.voltage"].snapshot()))["channel"] == 0
    assert json.loads(json.dumps(
        table["bias.ch2.voltage"].snapshot()))["channel"] == 2


# --------------------------------------------------------------------------- #
# §11.2 DeviceManager accessor stays additive                                  #
# --------------------------------------------------------------------------- #


def test_capability_registry_accessor_is_additive(dm):
    """Direct device access remains: the registry is opt-in discovery."""
    registry = dm.capability_registry()
    assert isinstance(registry, CapabilityRegistry)
    # Fresh registry per call (over the SAME live instances, never copies).
    assert dm.capability_registry() is not registry
    assert dm.capability_registry().binding("stage.x").target is dm.motor
    # The established direct surface is untouched.
    assert dm.named_devices()["Motor Stage"] is dm.motor
    assert dm.bias_supply is dm.bias_channels[0]
